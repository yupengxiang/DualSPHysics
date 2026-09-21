#!/usr/bin/env python3
"""Prepare-only manifest and hard audit for the F2 overflow-weir anchor.

The manifest produced here is intentionally *not* a ``core.cfd.v1`` runtime
input.  It is a hash-bound proposal that proves the existing native anchor can
be wired into a future solver worker.  The proposal has no solver, GPU, queue,
ledger, or registry authority.  The HDF5 audit is pure post-processing and
does not submit or restart a workload.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import digest, native_frame, write_json
from scripts.core_f2_receiver_overflow_weir_v1 import (
    DEFAULT_BASE,
    REVISION_ID,
    SCOPE_ID,
    evaluate_event,
    verify_candidate_bundle,
)
from scripts.finite_wall_audit import segment_crossing_events, wall_penetration


PROPOSAL_SCHEMA = "core.f2.receiver_overflow_weir.runtime_prepared_proposal.v1"
JOB_SCHEMA = "core.f2.receiver_overflow_weir.anchor_job_proposal.v1"
AUDIT_SCHEMA = "core.f2.receiver_overflow_weir.hdf5_hard_audit.v1"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    # Preflight records repository-relative paths for the generated native
    # prefix.  A prefix has no file suffix itself, so ``exists()`` cannot be
    # used to distinguish it from a path relative to the scope directory.
    # Treat the repository's top-level campaign namespace explicitly, then
    # fall back to the scope-local interpretation for ordinary artifacts.
    if path.parts and path.parts[0] == "campaigns":
        return (LAB_ROOT / path).resolve()
    root_candidate = LAB_ROOT / path
    if root_candidate.exists():
        return root_candidate.resolve()
    return (base / path).resolve()


def _wall_spec(candidate: dict[str, Any]) -> dict[str, Any]:
    tank = candidate["fixed_geometry"]["outer_tank"]
    low = tank["low_m"]
    size = tank["size_m"]
    obstacle = candidate["fixed_geometry"]["internal_weir"]
    return {
        "container_interior": {
            "xmin": float(low[0]), "xmax": float(low[0] + size[0]),
            "ymin": float(low[1]), "ymax": float(low[1] + size[1]),
            "zmin": float(low[2]), "zmax": float(low[2] + size[2]),
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [{
            "id": "internal_weir",
            "xmin": float(obstacle["low_m"][0]),
            "xmax": float(obstacle["low_m"][0] + obstacle["size_m"][0]),
            "ymin": float(obstacle["low_m"][1]),
            "ymax": float(obstacle["low_m"][1] + obstacle["size_m"][1]),
            "zmin": float(obstacle["low_m"][2]),
            "zmax": float(obstacle["low_m"][2] + obstacle["size_m"][2]),
        }],
        "runtime_domain": {
            key: float(value)
            for key, value in candidate["fixed_geometry"]["runtime_domain_m"].items()
        },
    }


def _native_anchor(base: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    definition = _resolve(base, preflight["artifacts"]["definition_path"])
    generated_prefix = _resolve(base, preflight["anchor"]["generated_prefix"])
    native_bi4 = generated_prefix.with_suffix(".bi4")
    decoder = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="f2-overflow-native-") as folder:
        ids, positions, velocities, density, meta, info, arrays = native_frame(
            native_bi4, Path(folder) / "initial", decoder
        )
    if len(ids) != int(preflight["generated_counts"]["total_particles"]):
        raise ValueError("native anchor particle count changed")
    if len(np.unique(ids)) != len(ids):
        raise ValueError("native anchor IDs are not unique")
    if not all(np.isfinite(array).all() for array in (positions, velocities, density)):
        raise ValueError("native anchor contains non-finite initial arrays")
    return {
        "definition": str(definition),
        "definition_sha256": digest(definition),
        "generated_prefix": str(generated_prefix),
        "native_bi4": str(native_bi4),
        "native_bi4_sha256": digest(native_bi4),
        "native_metadata": str(generated_prefix.with_name(generated_prefix.name + "_.xml")),
        "native_metadata_sha256": digest(generated_prefix.with_name(generated_prefix.name + "_.xml")),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "boundary_particles": int(meta["CaseNfixed"]),
        "fluid_particles": int(meta["CaseNfluid"]),
        "total_particles": int(meta["CaseNp"]),
        "dp_m": float(meta["Dp"]),
        "native_mass_fluid_kg": float(meta["MassFluid"]) * int(meta["CaseNfluid"]),
        "initial_time_s": float(info["TimeStep"]),
        # ``arrays`` is a temporary decoder directory and is removed when the
        # probe exits; never publish that ephemeral path as a reusable input.
        "normal_decode_probe": "passed",
    }


def prepare_proposal(base: Path = DEFAULT_BASE, output: Path | None = None) -> dict[str, Any]:
    """Create a read-only, solver-disabled prepared proposal from v4 inputs."""
    base = Path(base).resolve()
    contract = verify_candidate_bundle(base)
    candidate = load(base / "candidate-card-v1.json")
    preflight = load(base / "cpu-native-preflight-v1.json")
    root_review = load(base / "root-review-only-job-spec-v2.json")
    native = _native_anchor(base, preflight)
    physical = candidate["fixed_geometry"]
    source = physical["upstream_source_contract"]
    runtime_domain = physical["runtime_domain_m"]
    wall_spec = _wall_spec(candidate)
    solver = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
    proposal = {
        "schema": PROPOSAL_SCHEMA,
        "created_at_utc": stamp(),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "status": "prepared_proposal_not_runtime_authorized",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "candidate_contract": contract,
        "config": {
            "family": "F2",
            "scope_id": SCOPE_ID,
            "revision_id": REVISION_ID,
            "case_id": candidate["candidate_id"],
            "recipe": "mdbc_native",
            "recipe_id": "F2_receiver_overflow_weir_mdbc_v1",
            "stage": "anchor_proposal",
            "design_cell": "anchor",
            "qualification_only": True,
            "parameter": {
                "name": "weir_crest_height_m",
                "q": 0.5,
                "value": 0.26,
                "mapping": "crest_height_m=0.20+0.12*q",
            },
            "dp_m": 0.0075,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "initial_velocity_m_s": [0.0, 0.0, 0.0],
            "continuum_geometry": {
                "outer_tank": physical["outer_tank"],
                "internal_weir": physical["internal_weir"],
                "receiver": physical["downstream_receiver"],
            },
            "source_label_semantics": "native numerical source identity; no material qualification",
            "physical_case_id": candidate["candidate_id"],
            "lineage_group_id": "F2_receiver_overflow_weir_v1",
            "wall_spec": wall_spec,
            "runtime_domain": runtime_domain,
            "time_max_s": 1.5,
            "output_interval_s": 0.01,
            "event_window": candidate["registered_window"],
        },
        "sampling": {
            "fluid_boxes": [{
                "continuous_low_m": source["low_m"],
                "continuous_size_m": source["size_m"],
                "continuous_mass_kg": float(preflight["mass_contract"]["continuous_source_mass_kg"]),
                "discrete_mass_kg": float(preflight["mass_contract"]["discrete_native_mass_kg"]),
                "particle_count": int(preflight["generated_counts"]["fluid_particles"]),
                "mkfluid": 1,
                "native_cell_centre_sampling": True,
            }],
            "expected_fluid_particles": int(preflight["generated_counts"]["fluid_particles"]),
            "continuous_mass_kg": float(preflight["mass_contract"]["continuous_source_mass_kg"]),
            "sampled_mass_kg": float(preflight["mass_contract"]["discrete_native_mass_kg"]),
            "mass_policy": "native rho*dp^3; no mass rescaling",
        },
        "native_initial": native,
        "preflight_pass": True,
        "generated_prefix": native["generated_prefix"],
        "solver_binary": str(solver),
        "solver_sha256": digest(solver),
        "decoder": native["decoder"],
        "decoder_sha256": native["decoder_sha256"],
        "solver_arguments": ["-mdbc_noslip:1"],
        "input_hashes": {
            "candidate_card": digest(base / "candidate-card-v1.json"),
            "fixed_matrix": digest(base / "fixed-matrix-v1.json"),
            "failure_denominator": digest(base / "failure-denominator-v1.json"),
            "lineage": digest(base / "lineage-clarification-v1.json"),
            "cpu_native_preflight": digest(base / "cpu-native-preflight-v1.json"),
            "root_review_only_job_spec_v2": digest(base / "root-review-only-job-spec-v2.json"),
            "adapter": digest(LAB_ROOT / "scripts/core_f2_receiver_overflow_weir_v1.py"),
            "runtime_preparation_script": digest(Path(__file__).resolve()),
            "definition": native["definition_sha256"],
            "native_bi4": native["native_bi4_sha256"],
            "native_metadata": native["native_metadata_sha256"],
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "runtime_preparation_authorized": False,
            "submit_allowed": False,
        },
        "root_review_required": True,
        "interpretation_boundary": "proposal only; no solver product, event result, T1 credit, or qualification claim",
    }
    if output is not None:
        write_json(Path(output), proposal)
    return proposal


def make_anchor_job_proposal(prepared: Path, output: Path) -> dict[str, Any]:
    """Write an immutable, explicitly non-submittable anchor proposal."""
    prepared = Path(prepared).resolve()
    proposal = load(prepared)
    if proposal.get("schema") != PROPOSAL_SCHEMA or proposal.get("root_review_required") is not True:
        raise ValueError("prepared proposal is not a protected F2 proposal")
    result = {
        "schema": JOB_SCHEMA,
        "created_at_utc": stamp(),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "job_id": "f2-receiver-overflow-weir-q05-dp0075-anchor-proposal-v1",
        "status": "proposal_only_not_submitted",
        "prepared_proposal": str(prepared),
        "prepared_proposal_sha256": digest(prepared),
        "prepared_case_id": proposal["config"]["case_id"],
        "registered_window_s": proposal["config"]["time_max_s"],
        "input_hashes": proposal["input_hashes"],
        "execution_policy": {
            "submit_allowed": False,
            "solver_launch": False,
            "gpu_launch": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "one_anchor_only": True,
            "matrix_submission": False,
            "qualification_claim": "none",
        },
        "argv": [],
        "required_next_review": "exact one-anchor root review after solver-integrated audit implementation",
    }
    write_json(Path(output), result)
    return result


def audit_hdf5_trajectory(prepared_path: Path, hdf5_path: Path) -> dict[str, Any]:
    """Audit a supplied trajectory against finite tank and internal weir geometry."""
    prepared = load(Path(prepared_path))
    if prepared.get("schema") != PROPOSAL_SCHEMA:
        raise ValueError("audit requires the F2 prepared proposal schema")
    hdf5_path = Path(hdf5_path).resolve()
    if not hdf5_path.is_file():
        raise FileNotFoundError(hdf5_path)
    cfg = prepared["config"]
    spec = cfg["wall_spec"]
    with h5py.File(hdf5_path, "r") as handle:
        required = {"time", "position", "valid", "particle_id", "mass"}
        missing = sorted(required - set(handle.keys()))
        if missing:
            raise ValueError(f"trajectory missing datasets: {missing}")
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        ids = np.asarray(handle["particle_id"][:])
        masses = np.asarray(handle["mass"][:], dtype=float)
        if positions.ndim != 3 or positions.shape[-1] != 3 or valid.shape != positions.shape[:2]:
            raise ValueError("trajectory position/valid shapes are inconsistent")
        if ids.shape != (positions.shape[1],) or len(np.unique(ids)) != len(ids):
            raise ValueError("trajectory particle IDs are not unique")
        if times.shape != (positions.shape[0],) or len(times) < 2 or np.any(np.diff(times) <= 0):
            raise ValueError("trajectory time axis is not strictly increasing")
        if masses.ndim == 1:
            mass_by_frame = np.broadcast_to(masses[None, :], positions.shape[:2])
        elif masses.shape == positions.shape[:2]:
            mass_by_frame = masses
        else:
            raise ValueError("trajectory mass shape is inconsistent")
        initial_mass = float(mass_by_frame[0][valid[0]].sum(dtype=np.float64))
        if not np.isfinite(initial_mass) or initial_mass <= 0:
            raise ValueError("trajectory initial mass is not positive finite")
        endpoint_frames = 0
        obstacle_frames = 0
        chord_crossings = 0
        max_mass_change = 0.0
        finite_failure_frames = 0
        previous_position = None
        previous_valid = None
        for index in range(positions.shape[0]):
            frame_position = positions[index]
            frame_valid = valid[index]
            frame_mass = mass_by_frame[index]
            active = frame_valid
            finite = np.isfinite(frame_position).all(axis=1) & np.isfinite(frame_mass)
            finite_failure_frames += int(np.logical_and(active, ~finite).sum())
            if not np.isfinite(frame_position[active]).all() or not np.isfinite(frame_mass[active]).all():
                continue
            penetration = wall_penetration(frame_position[active], frame_mass[active], spec, 1e-8)
            endpoint_frames += int(penetration["outside_closed_container_count"])
            obstacle_frames += int(penetration["obstacle_penetration_count"])
            active_mass = float(frame_mass[active].sum(dtype=np.float64))
            max_mass_change = max(max_mass_change, abs(active_mass / initial_mass - 1.0))
            if previous_position is not None:
                common = previous_valid & active
                if common.any():
                    chord_crossings += len(segment_crossing_events(
                        previous_position[common], frame_position[common], spec, 1e-8
                    ))
            previous_position = frame_position
            previous_valid = active
        safe_positions = np.where(np.isfinite(positions), positions, 0.0)
        event = evaluate_event(
            safe_positions,
            times,
            mass_by_frame[0],
            float(cfg["parameter"]["value"]),
        )
        horizon_reached = bool(times[-1] >= float(cfg["time_max_s"]) - 1e-6)
    hard_pass = bool(
        horizon_reached
        and finite_failure_frames == 0
        and endpoint_frames == 0
        and obstacle_frames == 0
        and chord_crossings == 0
        and max_mass_change <= 1e-8
    )
    return {
        "schema": AUDIT_SCHEMA,
        "prepared_proposal_sha256": digest(Path(prepared_path)),
        "trajectory_path": str(hdf5_path),
        "trajectory_sha256": digest(hdf5_path),
        "hard_integrity_pass": hard_pass,
        "requested_horizon_reached": horizon_reached,
        "finite_failure_count": finite_failure_frames,
        "endpoint_violation_particle_frames": endpoint_frames,
        "obstacle_penetration_particle_frames": obstacle_frames,
        "saved_chord_crossing_count": chord_crossings,
        "mass_change_relative_max": max_mass_change,
        "event_window_complete": bool(event["event_complete"] and horizon_reached),
        "event_observation": event,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "interpretation_boundary": "post-processing audit only; this receipt does not authorize or count a T1 row",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-proposal")
    prepare.add_argument("--base", type=Path, default=DEFAULT_BASE)
    prepare.add_argument("--output", type=Path, required=True)
    job = sub.add_parser("make-job-proposal")
    job.add_argument("--prepared", type=Path, required=True)
    job.add_argument("--output", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--prepared", type=Path, required=True)
    audit.add_argument("--trajectory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-proposal":
        result = prepare_proposal(args.base, args.output)
    elif args.command == "make-job-proposal":
        result = make_anchor_job_proposal(args.prepared, args.output)
    else:
        result = audit_hdf5_trajectory(args.prepared, args.trajectory)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
