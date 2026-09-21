#!/usr/bin/env python3
"""Full-field, read-only native trajectory oracle diagnostics.

This entrypoint is deliberately separate from the learning reader.  It uses
the real prepared-config adapter to build public ``KnownInputs``, then reads a
native trajectory's following frame to construct a privileged ``dx``/``dv``
increment.  The increment is committed through the public updater and scored
with the registered evaluator so reader, commit, physics, and fixed-denominator
semantics can be checked on complete particle axes.

The following native frame is a reference-only input to this oracle.  It is
never exposed to a predictor, normalization, training, qualification, or
checkpoint selector.  Every output is labelled diagnostic-only and
privileged-reference.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any, Mapping

import h5py
import numpy as np

# Keep the runner usable by an absolute proposal command, where Python puts
# ``scripts/`` rather than the repository root on sys.path.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_cfd_dataset import known_inputs_from_cfd_config
from scripts.core_contract import (
    State,
    StepPrediction,
    apply_prediction,
    contract_hash,
    updater_oracle,
)
from scripts.core_evaluation import score_case
from scripts.core_physics import frame_physics
from scripts.core_runtime import atomic_json


SCHEMA = "core.privileged_fullfield_oracle.v1"
PROPOSAL_SCHEMA = "core.privileged_fullfield_oracle_proposal.v1"
ORACLE_POSITION_TOLERANCE_M = 1e-12
ORACLE_VELOCITY_TOLERANCE_MPS = 1e-12
REQUIRED_DATASETS = {
    "time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_prepared(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid prepared JSON: {path}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
        raise ValueError("prepared JSON must contain a config mapping")
    return payload, payload["config"]


def _prepared_dependencies(payload: Mapping[str, Any], prepared_path: Path) -> list[dict[str, Any]]:
    """List prepared-record artifacts, including archived missing outputs.

    The adapter only needs the prepared JSON and any motion file it resolves,
    but retaining every declared artifact makes a CPU attempt auditable.  Old
    generated outputs may have been archived, so absence is recorded rather
    than silently treated as a successful hash check.
    """
    entries: dict[str, dict[str, Any]] = {}

    def add(path_value: Any, declared_hash: Any, role: str) -> None:
        if not isinstance(path_value, str) or not path_value:
            return
        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = (Path(prepared_path).parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        key = str(candidate)
        row = entries.setdefault(key, {"path": key, "roles": [], "declared_sha256": None})
        if role not in row["roles"]:
            row["roles"].append(role)
        if isinstance(declared_hash, str) and len(declared_hash) == 64:
            row["declared_sha256"] = declared_hash

    for path_value, declared_hash in (payload.get("inputs") or {}).items():
        add(path_value, declared_hash, "prepared.inputs")
    for path_key, hash_key in (
        ("source_template", "source_template_sha256"),
        ("solver_binary", "solver_sha256"),
        ("decoder", "decoder_sha256"),
    ):
        add(payload.get(path_key), payload.get(hash_key), f"prepared.{path_key}")
    audit = payload.get("definition_audit") or {}
    if isinstance(audit, Mapping):
        for path_key, hash_key in (
            ("source_definition", "source_definition_sha256"),
            ("definition", "definition_sha256"),
            ("motion_file", "motion_sha256"),
        ):
            add(audit.get(path_key), audit.get(hash_key), f"definition_audit.{path_key}")
    result = []
    for row in entries.values():
        path = Path(row["path"])
        exists = path.is_file()
        observed = sha256_file(path) if exists else None
        row["exists"] = exists
        row["observed_sha256"] = observed
        row["hash_matches"] = bool(
            exists and row["declared_sha256"] is not None
            and observed == row["declared_sha256"]
        )
        result.append(row)
    return sorted(result, key=lambda item: item["path"])


@dataclass(frozen=True)
class SourceMetadata:
    family: str
    case_id: str
    frames: int
    particles: int
    time_start_s: float
    time_end_s: float
    position_shape: tuple[int, ...]
    velocity_shape: tuple[int, ...]
    valid_shape: tuple[int, ...]
    mass_shape: tuple[int, ...]
    particle_id_sha256: str
    particle_zone_sha256: str


def _array_sha256(value: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(value)
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def inspect_trajectory(path: Path, *, family: str, case_id: str) -> SourceMetadata:
    """Validate the complete native HDF5 axis without loading all frames."""
    path = Path(path).expanduser().resolve()
    with h5py.File(path, "r") as handle:
        missing = REQUIRED_DATASETS - set(handle)
        if missing:
            raise ValueError(f"native trajectory is missing datasets: {sorted(missing)}")
        times = np.asarray(handle["time"], dtype=np.float64)
        if (times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all()
                or np.any(np.diff(times) <= 0.0)):
            raise ValueError("native trajectory time axis is invalid")
        particle_id = np.asarray(handle["particle_id"])
        particle_zone = np.asarray(handle["particle_zone"])
        if particle_id.ndim != 1 or particle_zone.shape != particle_id.shape:
            raise ValueError("native particle identity axes are invalid")
        if particle_id.dtype.kind not in "iu" or particle_zone.dtype.kind not in "iu":
            raise ValueError("native particle identities must be integer arrays")
        identities = np.column_stack((particle_zone, particle_id))
        if len(np.unique(identities, axis=0)) != len(particle_id):
            raise ValueError("native composite particle identities are not unique")
        frames, particles = len(times), len(particle_id)
        expected_vector = (frames, particles, 3)
        if tuple(handle["position"].shape) != expected_vector or tuple(handle["velocity"].shape) != expected_vector:
            raise ValueError("native position/velocity datasets do not preserve the full [frame,N,3] axis")
        if tuple(handle["valid"].shape) != (frames, particles):
            raise ValueError("native valid dataset does not preserve the full [frame,N] axis")
        if tuple(handle["mass"].shape) not in ((particles,), (frames, particles)):
            raise ValueError("native mass dataset has unsupported shape")
        if handle["valid"].dtype.kind not in "biu":
            raise ValueError("native valid dataset must be boolean/integer")
        mass = np.asarray(handle["mass"][0] if handle["mass"].ndim == 2 else handle["mass"], dtype=np.float64)
        if (mass.shape != (particles,) or not np.isfinite(mass).all()
                or np.any(mass <= 0.0)):
            raise ValueError("native mass must be finite and positive")
        return SourceMetadata(
            family=str(family), case_id=str(case_id), frames=frames, particles=particles,
            time_start_s=float(times[0]), time_end_s=float(times[-1]),
            position_shape=tuple(int(x) for x in handle["position"].shape),
            velocity_shape=tuple(int(x) for x in handle["velocity"].shape),
            valid_shape=tuple(int(x) for x in handle["valid"].shape),
            mass_shape=tuple(int(x) for x in handle["mass"].shape),
            particle_id_sha256=_array_sha256(particle_id),
            particle_zone_sha256=_array_sha256(particle_zone),
        )


def _read_state(handle, frame: int, times: np.ndarray, particle_id: np.ndarray,
                particle_zone: np.ndarray, mass_reference: np.ndarray) -> State:
    mass = np.asarray(
        handle["mass"][frame] if handle["mass"].ndim == 2 else handle["mass"],
        dtype=np.float64,
    )
    valid = np.asarray(handle["valid"][frame], dtype=bool)
    # A native full-axis file may contain NaN payloads after an identity is
    # invalidated.  Bind mass to the initial identity axis and enforce the
    # invariant only for particles that are active at this frame.
    if valid.any() and (not np.isfinite(mass[valid]).all()
                        or not np.isfinite(mass_reference[valid]).all()
                        or not np.array_equal(mass[valid], mass_reference[valid])):
        raise ValueError(f"changed active particle mass at frame {frame}")
    return State(
        float(times[frame]),
        np.asarray(handle["position"][frame], dtype=np.float64),
        np.asarray(handle["velocity"][frame], dtype=np.float64),
        particle_id,
        particle_zone,
        mass_reference,
        valid,
    )


def _finite_active(state: State) -> bool:
    return bool(
        state.valid.any()
        and np.isfinite(state.position[state.valid]).all()
        and np.isfinite(state.velocity[state.valid]).all()
    )


def _native_commit(committed_previous: State, native_previous: State,
                   following: State, dt: float) -> tuple[State, dict[str, Any]]:
    """Commit fixed native increments onto the continuously propagated state.

    ``native_previous`` and ``following`` are the two reference frames used
    only to define ``dx`` and native saved-velocity ``dv``.  ``committed_previous``
    is the state produced by the prior commit and is the sole updater input;
    this prevents a bad updater from being corrected by re-reading its own
    error as the next increment.  Shared active particles retain the public
    ``apply_prediction`` result.  Only newly-valid and inactive lifecycle
    entries are synchronized explicitly.
    """
    for name in ("particle_id", "particle_zone", "mass"):
        if not np.array_equal(getattr(native_previous, name), getattr(following, name)):
            raise ValueError(f"native {name} changed between saved frames")
        if not np.array_equal(getattr(committed_previous, name), getattr(native_previous, name)):
            raise ValueError(f"committed {name} identity diverged from native axis")
    if not _finite_active(native_previous) or not _finite_active(following):
        raise ValueError("native frame has no finite active particle state")
    if not _finite_active(committed_previous):
        raise ValueError("committed previous frame has no finite active particle state")
    shared = native_previous.valid & following.valid
    newly_valid = ~native_previous.valid & following.valid
    lost_valid = native_previous.valid & ~following.valid
    displacement = np.zeros_like(native_previous.position)
    delta_velocity = np.zeros_like(native_previous.velocity)
    displacement[shared] = following.position[shared] - native_previous.position[shared]
    delta_velocity[shared] = following.velocity[shared] - native_previous.velocity[shared]
    prediction = StepPrediction(displacement, delta_velocity)
    updated = apply_prediction(committed_previous, prediction, dt)
    commit_position = np.array(updated.position, dtype=np.float64, copy=True)
    commit_velocity = np.array(updated.velocity, dtype=np.float64, copy=True)
    # A newly valid native identity has no causal prior value.  Preserve its
    # native current state explicitly and expose the lifecycle transition.
    commit_position[newly_valid] = following.position[newly_valid]
    commit_velocity[newly_valid] = following.velocity[newly_valid]
    # Inactive payload is outside the public active-state update contract. Keep
    # it synchronized for complete-axis output, while never overwriting shared
    # active particles with reference values.
    commit_position[~following.valid] = following.position[~following.valid]
    commit_velocity[~following.valid] = following.velocity[~following.valid]
    committed = State(
        following.time_s, commit_position, commit_velocity,
        following.particle_id, following.particle_zone, following.mass, following.valid,
    )
    shared_position_error = (
        float(np.max(np.abs(updated.position[shared] - following.position[shared])))
        if shared.any() else 0.0)
    shared_velocity_error = (
        float(np.max(np.abs(updated.velocity[shared] - following.velocity[shared])))
        if shared.any() else 0.0)
    committed_position_error = (
        committed.position[following.valid] - following.position[following.valid])
    committed_velocity_error = (
        committed.velocity[following.valid] - following.velocity[following.valid])
    dx = displacement[shared]
    dv = delta_velocity[shared]
    chord_rate = dx / float(dt)
    return committed, {
        "shared_active_particles": int(shared.sum()),
        "newly_valid_particles": int(newly_valid.sum()),
        "lost_valid_particles": int(lost_valid.sum()),
        "previous_active_particles": int(native_previous.valid.sum()),
        "following_active_particles": int(following.valid.sum()),
        "dx_max_abs_m": float(np.max(np.abs(dx))) if shared.any() else 0.0,
        "dv_max_abs_mps": float(np.max(np.abs(dv))) if shared.any() else 0.0,
        "dx_rmse_m": float(np.sqrt(np.mean(dx * dx))) if shared.any() else 0.0,
        "dv_rmse_mps": float(np.sqrt(np.mean(dv * dv))) if shared.any() else 0.0,
        "native_dv_minus_dx_over_dt_max_abs_mps": (
            float(np.max(np.abs(dv - chord_rate))) if shared.any() else 0.0
        ),
        "commit_position_max_abs_error_m": shared_position_error,
        "commit_native_velocity_max_abs_error_mps": shared_velocity_error,
        "committed_position_max_abs_error_m": (
            float(np.max(np.abs(committed_position_error))) if len(committed_position_error) else 0.0),
        "committed_velocity_max_abs_error_mps": (
            float(np.max(np.abs(committed_velocity_error))) if len(committed_velocity_error) else 0.0),
        "committed_position_rmse_m": (
            float(np.sqrt(np.mean(committed_position_error ** 2))) if len(committed_position_error) else 0.0),
        "committed_velocity_rmse_mps": (
            float(np.sqrt(np.mean(committed_velocity_error ** 2))) if len(committed_velocity_error) else 0.0),
        "velocity_semantics": "native saved numerical velocity; dv = v[t+1]-v[t], never dx/dt",
    }


def _geometry_summary(known) -> dict[str, Any]:
    geometry = known.geometry
    result = {
        "type": type(geometry).__name__,
        "triangle_count": int(len(geometry.triangles)),
        "coordinate_frame": geometry.coordinate_frame,
        "contract_sha256": contract_hash(known),
        "public_control_only": True,
        "predictor_future_state_inputs": False,
        "future_reference_state_used_by_oracle": True,
    }
    if hasattr(geometry, "motion_version"):
        result.update({
            "motion_version": geometry.motion_version,
            "motion_sha256": geometry.motion_sha256,
            "schedule_knot_count": int(len(geometry.sample_times)),
            "schedule_time_s": [float(x) for x in geometry.sample_times],
            "schedule_angle_degrees": [float(x) for x in geometry.sample_angles_degrees],
            "axis_point": np.asarray(geometry.axis_point).tolist(),
            "axis_direction": np.asarray(geometry.axis_direction).tolist(),
        })
    return result


def _atomic_progress(path: Path | None, *, family: str, case_id: str,
                     completed: int, expected: int, particles: int,
                     status: str, failure_category: str | None = None,
                     first_failure_frame: int | None = None,
                     failure_detail: str | None = None,
                     elapsed_s: float = 0.0) -> None:
    if path is None:
        return
    atomic_json(path, {
        "schema": "core.privileged_fullfield_oracle_progress.v1",
        "family": family, "case_id": case_id, "status": status,
        "completed_frames": int(completed), "expected_frames": int(expected),
        "particles": int(particles), "elapsed_seconds": float(elapsed_s),
        "failure_category": failure_category,
        "first_failure_frame": first_failure_frame,
        "failure_detail": failure_detail,
        "privileged_reference_oracle": True,
        "training_excluded": True, "qualification_excluded": True,
        "predictor_future_state_inputs": False,
        "future_reference_state_used_by_oracle": True,
    })


def run_privileged_oracle(prepared_path: Path, trajectory_path: Path, *,
                          output: Path | None = None,
                          progress_output: Path | None = None,
                          progress_every: int = 25,
                          include_physics: bool = True) -> dict[str, Any]:
    """Run a complete read-only oracle over one native full-field trajectory."""
    if isinstance(progress_every, bool) or int(progress_every) < 1:
        raise ValueError("progress_every must be positive")
    started = time.perf_counter()
    prepared_path = Path(prepared_path).expanduser().resolve()
    trajectory_path = Path(trajectory_path).expanduser().resolve()
    prepared, config = _load_prepared(prepared_path)
    prepared_dependencies = _prepared_dependencies(prepared, prepared_path)
    family = str(config.get("family", "")).upper()
    if family not in {"F2", "F4"}:
        raise ValueError(f"privileged oracle supports F2/F4, got {family!r}")
    case_id = str(config.get("case_id", trajectory_path.stem))
    metadata = inspect_trajectory(trajectory_path, family=family, case_id=case_id)
    known = known_inputs_from_cfd_config(config, family=family, data_root=prepared_path.parent)
    expected_frames = metadata.frames - 1
    failure_category = None
    first_failure_frame = None
    failure_detail = None
    frame_rows: list[dict[str, Any]] = []
    position_rmse: list[float] = []
    velocity_rmse: list[float] = []
    physics_rows: list[dict[str, Any] | None] = []
    lifecycle_rows: list[dict[str, Any]] = []
    native_previous = None
    committed_previous = None
    atomic_progress_path = Path(progress_output).expanduser().resolve() if progress_output else None
    _atomic_progress(atomic_progress_path, family=family, case_id=case_id,
                     completed=0, expected=expected_frames, particles=metadata.particles,
                     status="running", elapsed_s=time.perf_counter() - started)
    try:
        with h5py.File(trajectory_path, "r") as handle:
            times = np.asarray(handle["time"], dtype=np.float64)
            particle_id = np.asarray(handle["particle_id"], dtype=np.int64)
            particle_zone = np.asarray(handle["particle_zone"], dtype=np.int64)
            mass_reference = np.asarray(
                handle["mass"][0] if handle["mass"].ndim == 2 else handle["mass"],
                dtype=np.float64,
            )
            native_previous = _read_state(handle, 0, times, particle_id, particle_zone, mass_reference)
            committed_previous = native_previous
            if not _finite_active(native_previous):
                raise ValueError("native initial frame has no finite active state")
            for frame in range(1, metadata.frames):
                try:
                    following = _read_state(handle, frame, times, particle_id, particle_zone, mass_reference)
                    dt = float(following.time_s - native_previous.time_s)
                    committed, increment = _native_commit(
                        committed_previous, native_previous, following, dt)
                    physics = None
                    if include_physics:
                        geometry_next = known.geometry_at(following.time_s)
                        physics = frame_physics(
                            committed_previous, committed, following, known.geometry, geometry_next,
                        )
                    updater = None
                    if (np.array_equal(native_previous.valid, following.valid)
                            and bool(native_previous.valid.any())):
                        updater = updater_oracle(native_previous, following)
                    row = {
                        "frame": int(frame), "time_s": float(following.time_s), "dt_s": dt,
                        "increment": increment,
                        "updater_oracle": updater,
                        "physics": physics,
                    }
                    frame_rows.append(row)
                    lifecycle_rows.append(increment)
                    # Score the actual propagated commit against the native
                    # following frame. Missing frames remain absent and are
                    # penalized by score_case below.
                    position_rmse.append(float(increment["committed_position_rmse_m"]))
                    velocity_rmse.append(float(increment["committed_velocity_rmse_mps"]))
                    physics_rows.append(physics)
                    native_previous = following
                    committed_previous = committed
                except FloatingPointError as error:
                    failure_category = "native_nonfinite_state"
                    first_failure_frame = frame
                    failure_detail = f"{type(error).__name__}: {error}"
                    _atomic_progress(atomic_progress_path, family=family, case_id=case_id,
                                     completed=frame - 1, expected=expected_frames,
                                     particles=metadata.particles, status="failed",
                                     failure_category=failure_category,
                                     first_failure_frame=first_failure_frame,
                                     failure_detail=failure_detail,
                                     elapsed_s=time.perf_counter() - started)
                    break
                except ValueError as error:
                    message = str(error).lower()
                    failure_category = (
                        "native_identity_or_mass_mismatch" if any(
                            token in message for token in ("particle_id", "particle_zone", "mass")
                        ) else "oracle_commit_or_physics_error"
                    )
                    first_failure_frame = frame
                    failure_detail = f"{type(error).__name__}: {error}"
                    _atomic_progress(atomic_progress_path, family=family, case_id=case_id,
                                     completed=frame - 1, expected=expected_frames,
                                     particles=metadata.particles, status="failed",
                                     failure_category=failure_category,
                                     first_failure_frame=first_failure_frame,
                                     failure_detail=failure_detail,
                                     elapsed_s=time.perf_counter() - started)
                    break
                except Exception as error:  # pragma: no cover - integration failure path
                    failure_category = "oracle_execution_error"
                    first_failure_frame = frame
                    failure_detail = f"{type(error).__name__}: {error}"
                    _atomic_progress(atomic_progress_path, family=family, case_id=case_id,
                                     completed=frame - 1, expected=expected_frames,
                                     particles=metadata.particles, status="failed",
                                     failure_category=failure_category,
                                     first_failure_frame=first_failure_frame,
                                     failure_detail=failure_detail,
                                     elapsed_s=time.perf_counter() - started)
                    break
                if frame % int(progress_every) == 0 or frame == metadata.frames - 1:
                    _atomic_progress(
                        atomic_progress_path, family=family, case_id=case_id,
                        completed=frame, expected=expected_frames, particles=metadata.particles,
                        status="running", elapsed_s=time.perf_counter() - started,
                    )
    except (OSError, ValueError) as error:
        if failure_category is None:
            failure_category = "source_reader_error"
            first_failure_frame = len(frame_rows) + 1
            failure_detail = f"{type(error).__name__}: {error}"
        _atomic_progress(atomic_progress_path, family=family, case_id=case_id,
                         completed=len(frame_rows), expected=expected_frames,
                         particles=metadata.particles, status="failed",
                         failure_category=failure_category,
                         first_failure_frame=first_failure_frame,
                         failure_detail=failure_detail,
                         elapsed_s=time.perf_counter() - started)

    execution_complete = len(frame_rows) == expected_frames and failure_category is None
    finite_rollout_complete = execution_complete and all(
        np.isfinite(row["increment"]["committed_position_rmse_m"])
        and np.isfinite(row["increment"]["committed_velocity_rmse_mps"])
        for row in frame_rows
    )
    oracle_accuracy_pass = execution_complete and all(
        row["increment"]["committed_position_max_abs_error_m"] <= ORACLE_POSITION_TOLERANCE_M
        and row["increment"]["committed_velocity_max_abs_error_mps"] <= ORACLE_VELOCITY_TOLERANCE_MPS
        for row in frame_rows
    )
    known_length = max(
        float(np.ptp(known.geometry_at(0.0).triangles.reshape(-1, 3), axis=0).max()),
        float(known.numerics["dp_m"]),
    )
    gravity = np.asarray(known.physics.get("gravity_mps2", [0.0, 0.0, -9.81]), dtype=float)
    speed_scale = float(np.sqrt(np.linalg.norm(gravity) * known_length))
    score = score_case(
        position_rmse, velocity_rmse, expected_frames=expected_frames,
        length_m=known_length, speed_mps=speed_scale,
        executed=bool(frame_rows) or execution_complete,
        failure_category=failure_category,
    )
    wall_statuses = Counter()
    wall_particles = 0
    wall_mass = 0.0
    validity_mismatch = 0
    for physics in physics_rows:
        if not physics:
            continue
        validity_mismatch += int(physics.get("validity_mismatch_count", 0) > 0)
        wall = physics.get("wall_chord", {})
        wall_statuses[str(wall.get("status"))] += 1
        if isinstance(wall.get("particle_count"), (int, np.integer)):
            wall_particles += int(wall["particle_count"])
        if isinstance(wall.get("mass_kg"), (float, int, np.floating, np.integer)):
            wall_mass += float(wall["mass_kg"])
    report = {
        "schema": SCHEMA,
        "family": family, "case_id": case_id,
        "prepared": {"path": str(prepared_path), "sha256": sha256_file(prepared_path)},
        "prepared_dependencies": prepared_dependencies,
        "trajectory": {"path": str(trajectory_path), "sha256": sha256_file(trajectory_path)},
        "source_metadata": metadata.__dict__,
        "known_inputs": _geometry_summary(known),
        "state_propagation": {
            "native_reference_increment_source": "native_previous -> following",
            "committed_state_feedback": "committed_previous -> apply_prediction -> committed",
            "shared_active_reference_writeback": False,
            "newly_valid_or_inactive_lifecycle_writeback": True,
            "position_error_source": "committed vs following active state",
            "velocity_error_source": "committed vs following active state",
        },
        "physics": {
            "included": bool(include_physics),
            "frames_expected": expected_frames,
            "frames_completed": len(physics_rows),
            "wall_chord_statuses": dict(sorted(wall_statuses.items())),
            "wall_chord_particle_count_sum": wall_particles,
            "wall_chord_mass_kg_sum": wall_mass,
            "validity_mismatch_frames": validity_mismatch,
        },
        "evaluator": {
            "protocol": "core.scoring_protocol.v1",
            "fixed_denominator_expected_frames": expected_frames,
            "length_m": known_length, "speed_mps": speed_scale,
            "oracle_accuracy_tolerances": {
                "position_abs_m": ORACLE_POSITION_TOLERANCE_M,
                "velocity_abs_mps": ORACLE_VELOCITY_TOLERANCE_MPS,
            },
            "score": score,
        },
        "frames": frame_rows,
        "summary": {
            "expected_frames": expected_frames,
            "completed_frames": len(frame_rows),
            "execution_complete": execution_complete,
            "finite_rollout_complete": finite_rollout_complete,
            "oracle_accuracy_pass": oracle_accuracy_pass,
            "scientific_status": "diagnostic_only_privileged_oracle",
            "failure_category": failure_category,
            "first_failure_frame": first_failure_frame,
            "failure_detail": failure_detail,
            "native_lifecycle_transition_count": sum(
                bool(row["lost_valid_particles"] or row["newly_valid_particles"])
                for row in lifecycle_rows
            ),
            "native_lost_valid_particles_total": sum(row["lost_valid_particles"] for row in lifecycle_rows),
            "native_newly_valid_particles_total": sum(row["newly_valid_particles"] for row in lifecycle_rows),
        },
        "privileged_reference_oracle": True,
        "privileged_reference_increments": True,
        "predictor_future_state_inputs": False,
        "future_reference_state_used_by_oracle": True,
        "training_excluded": True,
        "qualification_excluded": True,
        "formal_selection_excluded": True,
        "ledger_write": False,
        "host": platform.node(),
        "elapsed_seconds": float(time.perf_counter() - started),
        "progress_output": str(atomic_progress_path) if atomic_progress_path else None,
    }
    _atomic_progress(
        atomic_progress_path, family=family, case_id=case_id,
        completed=len(frame_rows), expected=expected_frames, particles=metadata.particles,
        status="completed" if execution_complete else "failed",
        failure_category=failure_category, first_failure_frame=first_failure_frame,
        failure_detail=failure_detail,
        elapsed_s=report["elapsed_seconds"],
    )
    if output is not None:
        atomic_json(output, report)
    return report


def make_proposal(prepared_path: Path, trajectory_path: Path, *, output_path: Path,
                  report_path: Path, progress_path: Path | None = None,
                  include_physics: bool = True) -> dict[str, Any]:
    """Build a CPU-only proposal; this function never submits or writes a ledger."""
    prepared_path = Path(prepared_path).expanduser().resolve()
    trajectory_path = Path(trajectory_path).expanduser().resolve()
    prepared, config = _load_prepared(prepared_path)
    prepared_dependencies = _prepared_dependencies(prepared, prepared_path)
    family = str(config.get("family", "")).upper()
    case_id = str(config.get("case_id", trajectory_path.stem))
    metadata = inspect_trajectory(trajectory_path, family=family, case_id=case_id)
    known = known_inputs_from_cfd_config(config, family=family, data_root=prepared_path.parent)
    command = [
        sys.executable, str(Path(__file__).resolve()), "run",
        "--prepared", str(prepared_path), "--trajectory", str(trajectory_path),
        "--output", str(Path(report_path).resolve()),
    ]
    if progress_path is not None:
        command.extend(("--progress-output", str(Path(progress_path).resolve())))
    command.append("--include-physics" if include_physics else "--no-physics")
    proposal = {
        "schema": PROPOSAL_SCHEMA,
        "job_id": f"core-privileged-oracle-{family.lower()}-{case_id.lower().replace('_', '-')}",
        "category": "privileged_oracle_diagnostic",
        "family": family, "case_id": case_id,
        "qualification_only": True, "formal_eligible": False,
        "training_excluded": True, "ledger_write": False,
        "inputs": [
            {"role": "prepared_config", "path": str(prepared_path), "sha256": sha256_file(prepared_path)},
            {"role": "native_trajectory", "path": str(trajectory_path), "sha256": sha256_file(trajectory_path)},
        ],
        "prepared_dependencies": prepared_dependencies,
        "runner": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "entrypoint": "run",
        },
        "known_inputs": _geometry_summary(known),
        "source_metadata": metadata.__dict__,
        "command": command,
        "outputs": [
            {"role": "oracle_report", "path": str(Path(report_path).resolve()), "schema": SCHEMA},
            *([{"role": "progress_sidecar", "path": str(Path(progress_path).resolve()),
                "schema": "core.privileged_fullfield_oracle_progress.v1"}] if progress_path else []),
        ],
        "resources": {
            "device": "cpu", "gpu": False, "cpu_threads": 4,
            "memory_mib": 4096, "timeout_seconds": 1800,
            "reason": "full-axis native oracle with optional finite-wall physics per saved frame",
        },
        "oracle_semantics": {
            "dx": "native position[t+1] - position[t] on shared active identities",
            "dv": "native saved velocity[t+1] - velocity[t], never position chord / dt",
            "commit": "public apply_prediction on the continuously propagated commit; explicit lifecycle synchronization only for newly-valid/inactive entries",
            "evaluator": "core.scoring_protocol.v1 fixed frame denominator",
            "geometry": "prepared-config KnownInputs; no future fluid state",
            "reference_writeback": "shared active following values are never copied into the committed state",
            "accuracy_tolerances": {
                "position_abs_m": ORACLE_POSITION_TOLERANCE_M,
                "velocity_abs_mps": ORACLE_VELOCITY_TOLERANCE_MPS,
            },
        },
        "proposal_only": True,
    }
    atomic_json(output_path, proposal)
    return proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--trajectory", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--progress-output", type=Path)
    run.add_argument("--progress-every", type=int, default=25)
    run.add_argument("--include-physics", dest="include_physics", action="store_true", default=True)
    run.add_argument("--no-physics", dest="include_physics", action="store_false")
    proposal = sub.add_parser("proposal")
    proposal.add_argument("--prepared", type=Path, required=True)
    proposal.add_argument("--trajectory", type=Path, required=True)
    proposal.add_argument("--output", type=Path, required=True)
    proposal.add_argument("--report-path", type=Path, required=True)
    proposal.add_argument("--progress-path", type=Path)
    proposal.add_argument("--include-physics", dest="include_physics", action="store_true", default=True)
    proposal.add_argument("--no-physics", dest="include_physics", action="store_false")
    args = parser.parse_args(argv)
    if args.command == "run":
        result = run_privileged_oracle(
            args.prepared, args.trajectory, output=args.output,
            progress_output=args.progress_output, progress_every=args.progress_every,
            include_physics=args.include_physics,
        )
    else:
        result = make_proposal(
            args.prepared, args.trajectory, output_path=args.output,
            report_path=args.report_path, progress_path=args.progress_path,
            include_physics=args.include_physics,
        )
    print(json.dumps({
        "schema": result["schema"], "family": result.get("family"),
        "case_id": result.get("case_id"), "proposal_only": result.get("proposal_only", False),
        "execution_complete": result.get("summary", {}).get("execution_complete"),
        "completed_frames": result.get("summary", {}).get("completed_frames"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
