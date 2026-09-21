#!/usr/bin/env python3
"""Root-reviewed runtime adapter for the F3 internal-baffle anchor.

The source-scope preflight predates the F4-shaped ``core_cfd`` prepared
contract.  This module is the narrow bridge for one approved anchor only.  It
validates the candidate card, fixed matrix, failure denominator, prepared
anchor, and root review before it can either emit a scheduler job spec or run
the solver.  It converts native BI4 frames itself and audits the finite tank
plus the internal baffle as a solid obstacle.  The anchor is diagnostic only:
it can never add matrix numerator credit or register F3 T1.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd
from scripts.finite_wall_audit import segment_crossing_events, wall_penetration


SCHEMA = "core.f3.baffle_exchange.runtime_adapter.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVIEW_SCHEMA = "core.root_review.v1"
SCOPE_ID = "F3_baffle_exchange_native_mdbc_x_v1"
REVISION_ID = "F3_baffle_exchange_native_mdbc_v1"
MATRIX_ID = "F3_baffle_exchange_native_mdbc_x_v1_matrix"
DENOMINATOR_ID = "F3_baffle_exchange_native_mdbc_x_v1_failure_denominator"
TARGET_MATRIX_INDEX = 4
TARGET_ROW_ID = "CORE_F3_BAFFLE_EXCHANGE_q0p50000000_dp0p007500000000_spatial"
TARGET_CASE_ID = "CORE_F3_BAFFLE_EXCHANGE_q0p50000000_dp0p007500000000_anchor"
TARGET_Q = 0.5
TARGET_DP_M = 0.0075
TARGET_OUTPUT_INTERVAL_S = 0.01
TARGET_TIME_MAX_S = 8.35
TARGET_FLUID_PARTICLES = 33120
# Immutable source-contract values used by input validation.  The public
# target constants are intentionally easy to monkeypatch in bounded audit
# tests; validation must remain tied to the registered prepared anchor.
REGISTERED_DP_M = 0.0075
REGISTERED_OUTPUT_INTERVAL_S = 0.01
REGISTERED_TIME_MAX_S = 8.35
REGISTERED_FLUID_PARTICLES = 33120
TARGET_JOB_ID = "f3-baffle-exchange-q0p5-dp0075-anchor-canary-001"
WALL_TOLERANCE_M = 1e-8
MASS_RELATIVE_TOLERANCE = 1e-8
TIME_CADENCE_RELATIVE_TOLERANCE = 1e-2
TIME_CADENCE_ABSOLUTE_FLOOR_S = 1e-7
REQUIRED_DATASETS = (
    "particle_id", "particle_zone", "source_label_initial_mk", "time",
    "position", "velocity", "density", "mass", "pressure", "valid",
    "type", "mk",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any], *, overwrite: bool = False) -> None:
    path = Path(path).resolve()
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _same_float(actual: Any, expected: float, *, tolerance: float = 1e-12) -> bool:
    try:
        return math.isfinite(float(actual)) and abs(float(actual) - expected) <= tolerance
    except (TypeError, ValueError):
        return False


def _review_control(review: dict[str, Any], key: str, expected: bool) -> None:
    value = review.get("authorization", {}).get(key)
    if value is not expected:
        raise ValueError(f"root review authorization {key} must be {expected}")


def _verify_root_review(review_path: Path, *, candidate: Path, matrix: Path,
                        denominator: Path, prepared: Path) -> dict[str, Any]:
    review = read_json(review_path)
    if review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("root review schema mismatch")
    if review.get("decision") != "approved_for_anchor_canary":
        raise ValueError("root review does not approve the anchor canary")
    if review.get("family") != "F3" or review.get("scope_id") != SCOPE_ID:
        raise ValueError("root review family/scope mismatch")
    if review.get("revision_id") != REVISION_ID:
        raise ValueError("root review revision mismatch")
    if review.get("authorized_matrix_indices") != [TARGET_MATRIX_INDEX]:
        raise ValueError("review must authorize exactly matrix index 4")
    if review.get("authorized_case_ids") != [TARGET_CASE_ID]:
        raise ValueError("review must authorize exactly the prepared anchor case")
    controls = review.get("authorization", {})
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "direct_execution"):
        _review_control(review, key, True)
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_expansion",
                "material_training", "model_training", "t1_registration"):
        _review_control(review, key, False)
    if review.get("qualification_claim") != "none":
        raise ValueError("root review qualification claim must be none")
    policy = review.get("execution_policy", {})
    if policy.get("one_anchor_only") is not True or policy.get("matrix_credit") != 0:
        raise ValueError("root review does not freeze one-anchor zero-credit policy")
    bindings = {
        "candidate_card": candidate,
        "matrix": matrix,
        "failure_denominator": denominator,
        "prepared_anchor": prepared,
    }
    for key, path in bindings.items():
        expected = review.get(key, {}).get("sha256")
        if expected != digest(path):
            raise ValueError(f"root review {key} hash mismatch")
    runtime_ref = review.get("runtime_adapter", {})
    # The coordinator freezes ``scripts/*.py`` into a content-addressed
    # snapshot before launching a worker.  The review therefore binds the
    # adapter bytes and live source path, while a worker may execute the
    # identical bytes from that snapshot path.
    runtime_path = Path(runtime_ref.get("path", "")).resolve()
    runtime_hash = runtime_ref.get("sha256")
    if runtime_hash != digest(Path(__file__)):
        raise ValueError("root review runtime adapter hash is stale")
    if runtime_path != Path(__file__).resolve() and (not runtime_path.is_file() or digest(runtime_path) != runtime_hash):
        raise ValueError("root review runtime adapter path is not a matching source")
    for key, expected_role in (("solver", "pinned DualSPHysics solver"), ("decoder", "pinned native decoder")):
        item = review.get(key, {})
        path = Path(item.get("path", "")).resolve()
        if item.get("role") != expected_role or not path.is_file() or item.get("sha256") != digest(path):
            raise ValueError(f"root review {key} binding is stale")
    return review


def _read_generated_blocks(prepared: dict[str, Any]) -> tuple[Path, ET.Element, dict[str, Any]]:
    prefix = Path(prepared.get("generated_prefix", "")).resolve()
    xml_path = prefix.with_suffix(".xml")
    if not xml_path.is_file():
        raise FileNotFoundError(xml_path)
    root = ET.parse(xml_path).getroot()
    fluid = root.findall("./execution/particles/fluid")
    fixed = root.findall("./execution/particles/fixed")
    if len(fluid) != 1 or len(fixed) != 2:
        raise ValueError("baffle generated XML must contain one fluid and two fixed-boundary blocks")
    block = fluid[0]
    required = {"begin", "count", "mkfluid", "mk"}
    if not required.issubset(block.attrib):
        raise ValueError("generated fluid block lacks native identity fields")
    count = int(block.get("count"))
    begin = int(block.get("begin"))
    if begin < 0 or count != REGISTERED_FLUID_PARTICLES:
        raise ValueError("generated fluid block does not bind the anchor particle count")
    geometry = prepared.get("geometry", {})
    if geometry.get("mkbound_roles") != {"0": "finite_outer_tank_open_top", "1": "internal_baffle"}:
        raise ValueError("prepared geometry roles are not the baffle contract")
    baffle_low = np.asarray(geometry.get("internal_baffle_low_m", []), dtype=np.float64)
    baffle_size = np.asarray(geometry.get("internal_baffle_size_m", []), dtype=np.float64)
    outer_low = np.asarray(geometry.get("outer_wall_low_m", []), dtype=np.float64)
    outer_size = np.asarray(geometry.get("outer_wall_size_m", []), dtype=np.float64)
    if baffle_low.shape != (3,) or baffle_size.shape != (3,) or outer_low.shape != (3,) or outer_size.shape != (3,):
        raise ValueError("prepared geometry bounds are incomplete")
    if not np.allclose(baffle_low, [0.58, 0.04, 0.0], atol=1e-12, rtol=0.0):
        raise ValueError("internal baffle low corner changed")
    if not np.allclose(baffle_size, [0.03, 0.18, 0.19], atol=1e-12, rtol=0.0):
        raise ValueError("internal baffle size changed")
    if not np.allclose(outer_low, [0.0, 0.0, 0.0], atol=1e-12, rtol=0.0) or not np.allclose(outer_size, [1.2, 0.4, 0.6], atol=1e-12, rtol=0.0):
        raise ValueError("outer tank bounds changed")
    return xml_path, root, {
        "fluid_begin": begin,
        "fluid_count": count,
        "fluid_mk": int(block.get("mk")),
        "baffle_low": baffle_low,
        "baffle_high": baffle_low + baffle_size,
        "outer_low": outer_low,
        "outer_high": outer_low + outer_size,
    }


def _verify_prepared(prepared_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared = read_json(prepared_path)
    if prepared.get("schema") != "core.f3.baffled_source_scope.preflight.v1":
        raise ValueError("unexpected F3 baffle prepared schema")
    if prepared.get("scope_id") != SCOPE_ID or prepared.get("revision_id") != REVISION_ID:
        raise ValueError("prepared scope/revision mismatch")
    if prepared.get("case_id") != TARGET_CASE_ID or prepared.get("preflight_pass") is not True:
        raise ValueError("prepared anchor is not the passing target preflight")
    if prepared.get("status") != "prepared_only" or prepared.get("launch_allowed") is not False:
        raise ValueError("prepared anchor must remain fail-closed before runtime")
    recipe = prepared.get("recipe", {})
    for key, expected in (("dp_m", REGISTERED_DP_M), ("output_interval_s", REGISTERED_OUTPUT_INTERVAL_S),
                          ("time_max_s", REGISTERED_TIME_MAX_S), ("cfl", 0.05), ("visco", 0.05)):
        if not _same_float(recipe.get(key), expected):
            raise ValueError(f"prepared recipe {key} mismatch")
    if recipe.get("boundary_method") != 2 or recipe.get("solver_arguments") != ["-mdbc_noslip:1"]:
        raise ValueError("prepared recipe does not bind native mDBC")
    if prepared.get("parameter", {}).get("q") != TARGET_Q or not _same_float(prepared.get("parameter", {}).get("value"), .75):
        raise ValueError("prepared anchor parameter mismatch")
    sampling = prepared.get("sampling", {})
    if sampling.get("fluid_particles") != REGISTERED_FLUID_PARTICLES or sampling.get("mass_gate_pass") is not True:
        raise ValueError("prepared native sampling/mass gate mismatch")
    controls = prepared.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked"):
        if controls.get(key) is not False:
            raise ValueError(f"prepared control {key} is not false")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "qualification_numerator_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"prepared control {key} is not zero")
    for path, expected in prepared.get("inputs", {}).items():
        path_obj = Path(path)
        if not path_obj.is_file() or digest(path_obj) != expected:
            raise ValueError("prepared input hash mismatch: " + path)
    solver = Path(prepared.get("solver_binary", "")).resolve()
    decoder = Path(prepared.get("decoder", "")).resolve()
    if not solver.is_file() or digest(solver) != prepared.get("solver_sha256"):
        raise ValueError("prepared solver hash mismatch")
    if not decoder.is_file() or digest(decoder) != prepared.get("decoder_sha256"):
        raise ValueError("prepared decoder hash mismatch")
    xml_path, _, geometry = _read_generated_blocks(prepared)
    if Path(prepared.get("generated_prefix", "")).with_suffix(".bi4").resolve() not in {Path(p).resolve() for p in prepared["inputs"]}:
        raise ValueError("prepared anchor BI4 is not hash-bound")
    geometry["xml_path"] = xml_path
    return prepared, geometry


def _verify_candidate_matrix_denominator(candidate_path: Path, matrix_path: Path,
                                         denominator_path: Path, prepared_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate, matrix, denominator = read_json(candidate_path), read_json(matrix_path), read_json(denominator_path)
    if candidate.get("scope_id") != SCOPE_ID or candidate.get("revision_id") != REVISION_ID:
        raise ValueError("candidate scope/revision mismatch")
    if candidate.get("qualified") is not False or candidate.get("status") != "candidate_handoff_root_review_only":
        raise ValueError("candidate must remain unqualified/root-review-only")
    if matrix.get("matrix_id") != MATRIX_ID or matrix.get("design_only") is not True or len(matrix.get("rows", [])) != 15:
        raise ValueError("fixed 15-row matrix contract is not closed")
    if matrix.get("anchor", {}).get("preflight_credit") != 0 or matrix.get("qualification_rule", {}).get("preflight_rows_credit") != 0:
        raise ValueError("matrix anchor credit is not explicitly zero")
    rows = matrix["rows"]
    target = rows[TARGET_MATRIX_INDEX]
    if target.get("row_id") != TARGET_ROW_ID or target.get("status") != "not_started":
        raise ValueError("target matrix row is not the unattempted anchor row")
    if target.get("row_kind") != "spatial_anchor" or target.get("q") != TARGET_Q or not _same_float(target.get("dp_m"), TARGET_DP_M):
        raise ValueError("target matrix row parameters mismatch")
    if any(row.get("status") != "not_started" for row in rows):
        raise ValueError("matrix rows changed before one-anchor canary")
    if denominator.get("denominator_id") != DENOMINATOR_ID or denominator.get("status") != "fixed_before_runtime":
        raise ValueError("failure denominator identity/status mismatch")
    accounting = denominator.get("denominator", {})
    if accounting != {"planned_rows": 15, "executed_rows": 0, "passed_rows": 0, "failed_rows": 0,
                      "unattempted_rows": 15, "preflight_rows_credited": 0, "qualification_numerator": 0}:
        raise ValueError("failure denominator was changed before canary")
    if denominator.get("fixed_rules", {}).get("preflight_anchor_is_qualification") is not False:
        raise ValueError("failure denominator allows preflight credit")
    if candidate.get("qualification_design", {}).get("matrix", {}).get("sha256") != digest(matrix_path):
        raise ValueError("candidate matrix hash binding mismatch")
    if candidate.get("qualification_design", {}).get("failure_denominator", {}).get("sha256") != digest(denominator_path):
        raise ValueError("candidate denominator hash binding mismatch")
    if candidate.get("preflight", {}).get("prepared", {}).get("sha256") != digest(prepared_path):
        raise ValueError("candidate prepared hash binding mismatch")
    return candidate, matrix, denominator, target


def verify_bindings(*, candidate_path: Path, matrix_path: Path, denominator_path: Path,
                    prepared_path: Path, review_path: Path) -> dict[str, Any]:
    candidate_path, matrix_path = Path(candidate_path).resolve(), Path(matrix_path).resolve()
    denominator_path, prepared_path, review_path = (Path(denominator_path).resolve(), Path(prepared_path).resolve(), Path(review_path).resolve())
    candidate, matrix, denominator, row = _verify_candidate_matrix_denominator(candidate_path, matrix_path, denominator_path, prepared_path)
    prepared, geometry = _verify_prepared(prepared_path)
    review = _verify_root_review(review_path, candidate=candidate_path, matrix=matrix_path,
                                 denominator=denominator_path, prepared=prepared_path)
    return {
        "candidate": candidate, "matrix": matrix, "denominator": denominator,
        "row": row, "prepared": prepared, "geometry": geometry, "review": review,
        "paths": {"candidate": candidate_path, "matrix": matrix_path,
                  "denominator": denominator_path, "prepared": prepared_path, "review": review_path},
    }


def _fluid_axis(geometry: dict[str, Any]) -> np.ndarray:
    return np.arange(geometry["fluid_begin"], geometry["fluid_begin"] + geometry["fluid_count"], dtype=np.uint32)


def convert_native(prepared: dict[str, Any], geometry: dict[str, Any], data_dir: Path,
                   output: Path) -> dict[str, Any]:
    """Convert only the native fluid block; boundary particles stay native-only."""
    paths = sorted(Path(data_dir).glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if len(paths) < 2:
        raise ValueError("fewer than two native BI4 frames")
    axis = _fluid_axis(geometry)
    n, nt = len(axis), len(paths)
    partial = Path(output).with_suffix(".h5.partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f3-baffle-native-") as folder, h5py.File(partial, "w") as handle:
        handle.attrs.update(
            schema_version=3, case_id=prepared["case_id"], family="F3",
            scope_id=SCOPE_ID, revision_id=REVISION_ID, source_asset_id=prepared["source_asset_id"],
            conversion_complete=False, particle_shifting="disabled", identity_key="particle_id",
            trajectory_semantics="native SPH fluid particle identity; baffle hard-obstacle audit is separate",
            source_label_semantics="single native fluid block mkfluid=0, source label is initial mk=1",
            data_qualification_status="anchor_canary_unqualified", matrix_credit=0,
            qualification_claim="none; one anchor canary cannot qualify the 15-row scope",
        )
        handle.create_dataset("particle_id", data=axis)
        handle.create_dataset("particle_zone", data=np.zeros(n, np.int16))
        handle.create_dataset("source_label_initial_mk", data=np.full(n, geometry["fluid_mk"], np.int16))
        handle.create_dataset("time", shape=(nt,), dtype="f8")
        chunk = min(n, 65536)
        for name in ("position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"):
            vector = name in ("position", "velocity")
            dtype = "f8" if name == "position" else "bool" if name == "valid" else "i2" if name in ("type", "mk") else "f4"
            fill = False if name == "valid" else -1 if name in ("type", "mk") else np.nan
            handle.create_dataset(name, shape=(nt, n, 3) if vector else (nt, n), dtype=dtype,
                                  chunks=(1, chunk, 3) if vector else (1, chunk), compression="lzf", fillvalue=fill)
        previous_time = -math.inf
        for frame, path in enumerate(paths):
            ids, position, velocity, density, meta, info, _ = core_cfd.native_frame(
                path, Path(folder) / "frame", Path(prepared["decoder"])
            )
            index = np.searchsorted(axis, ids)
            selected = index < n
            selected[selected] &= axis[index[selected]] == ids[selected]
            local = index[selected]
            current_time = float(info["TimeStep"])
            if not np.isfinite(current_time) or current_time <= previous_time:
                raise ValueError("native frame times are not strictly increasing")
            previous_time = current_time
            handle["time"][frame] = current_time
            handle["valid"][frame, local] = True
            selected_rho = density[selected]
            pressure = float(meta["B"]) * ((selected_rho.astype(float) / float(meta["Rhop0"])) ** float(meta["Gamma"]) - 1.0)
            mass = np.full(len(local), float(meta["MassFluid"]), dtype=np.float32)
            values = {
                "position": position[selected], "velocity": velocity[selected], "density": selected_rho,
                "mass": mass, "pressure": pressure, "type": np.full(len(local), 3, dtype=np.int16),
                "mk": np.full(len(local), geometry["fluid_mk"], dtype=np.int16),
            }
            for name, value in values.items():
                handle[name][frame, local] = value
            handle.attrs["conversion_complete_frames"] = frame + 1
        handle.attrs["conversion_complete"] = True
    partial.replace(output)
    return {"hdf5": str(Path(output).resolve()), "frames": nt, "particle_count": n,
            "sha256": digest(output), "native_output_only": True, "interpolation_used": False}


def _event_audit(handle: h5py.File, geometry: dict[str, Any], *, times: np.ndarray,
                 positions: list[np.ndarray], valid_rows: list[np.ndarray]) -> dict[str, Any]:
    """Observe baffle encounter and two-way exchange without changing gates."""
    low, high = geometry["baffle_low"], geometry["baffle_high"]
    margin = max(2.0 * TARGET_DP_M, 1e-6)
    expanded_low, expanded_high = low - margin, high + margin
    encounter_frames = 0
    encounter_particle_frames = 0
    transitions = {"left_to_right": [], "right_to_left": []}
    left_cut, right_cut = float(low[0] - WALL_TOLERANCE_M), float(high[0] + WALL_TOLERANCE_M)
    for frame, pos in enumerate(positions):
        valid = valid_rows[frame]
        finite = valid & np.isfinite(pos).all(axis=1)
        expanded = finite & np.all((pos >= expanded_low) & (pos <= expanded_high), axis=1)
        exact = finite & np.all((pos > low) & (pos < high), axis=1)
        near = expanded & ~exact
        if near.any():
            encounter_frames += 1
            encounter_particle_frames += int(near.sum())
        if frame == 0:
            continue
        previous = positions[frame - 1]
        common = finite & valid_rows[frame - 1] & np.isfinite(previous).all(axis=1)
        left0 = previous[:, 0] < left_cut
        right0 = previous[:, 0] > right_cut
        left1 = pos[:, 0] < left_cut
        right1 = pos[:, 0] > right_cut
        for direction, mask in (("left_to_right", common & left0 & right1), ("right_to_left", common & right0 & left1)):
            for particle in np.flatnonzero(mask):
                # Around-the-baffle exchange is only counted when the saved
                # chord does not intersect the finite solid obstacle.  A
                # penetration is retained as a hard failure and cannot be
                # reinterpreted as exchange.
                events = segment_crossing_events(
                    previous[particle:particle + 1], pos[particle:particle + 1],
                    {"container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4,
                                               "zmin": 0.0, "zmax": 0.6}, "closed_faces": [],
                     "obstacles": [{"id": "internal_baffle", "xmin": float(low[0]), "xmax": float(high[0]),
                                    "ymin": float(low[1]), "ymax": float(high[1]), "zmin": float(low[2]),
                                    "zmax": float(high[2])}]}, WALL_TOLERANCE_M
                )
                if not any(event.get("kind") == "obstacle" for event in events):
                    if len(transitions[direction]) < 64:
                        transitions[direction].append({"frame_start": frame - 1, "frame_end": frame,
                                                       "time_start_s": float(times[frame - 1]),
                                                       "time_end_s": float(times[frame]),
                                                       "particle_index": int(particle)})
    forward = len(transitions["left_to_right"]) > 0
    reverse = len(transitions["right_to_left"]) > 0
    encounter = encounter_frames > 0
    return {
        "contract": "baffle encounter + one forward and one reverse finite-obstacle-aware exchange + full native time window",
        "baffle_encounter": {"pass": encounter, "frame_count": encounter_frames,
                              "particle_frame_count": encounter_particle_frames, "margin_m": margin},
        "exchange": {"forward_count_capped": len(transitions["left_to_right"]),
                      "reverse_count_capped": len(transitions["right_to_left"]),
                      "forward_pass": forward, "reverse_pass": reverse,
                      "first_forward": transitions["left_to_right"][0] if forward else None,
                      "first_reverse": transitions["right_to_left"][0] if reverse else None},
        "event_window_complete": bool(encounter and forward and reverse),
        "qualification_claim": "none; event observer is diagnostic and does not add matrix credit",
    }


def audit_trajectory(prepared: dict[str, Any], geometry: dict[str, Any], trajectory: Path,
                     *, prepared_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_frames = int(round(TARGET_TIME_MAX_S / TARGET_OUTPUT_INTERVAL_S)) + 1
    expected_particles = TARGET_FLUID_PARTICLES
    outer = geometry["outer_low"], geometry["outer_high"]
    wall = {"container_interior": {"xmin": float(outer[0][0]), "xmax": float(outer[1][0]),
                                    "ymin": float(outer[0][1]), "ymax": float(outer[1][1]),
                                    "zmin": float(outer[0][2]), "zmax": float(outer[1][2])},
            "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"],
            "obstacles": [{"id": "internal_baffle", "xmin": float(geometry["baffle_low"][0]),
                           "xmax": float(geometry["baffle_high"][0]), "ymin": float(geometry["baffle_low"][1]),
                           "ymax": float(geometry["baffle_high"][1]), "zmin": float(geometry["baffle_low"][2]),
                           "zmax": float(geometry["baffle_high"][2])}]}
    report: dict[str, Any] = {
        "schema": "core.f3.baffle_exchange.runtime_audit.v1", "audit_version": 1,
        "audited_at_utc": stamp(), "prepared_json": str(prepared_path.resolve()),
        "prepared_json_sha256": digest(prepared_path), "trajectory": str(trajectory.resolve()),
        "qualification_claim": "none; one anchor canary is diagnostic only", "matrix_credit": 0,
        "expected": {"frames": expected_frames, "particles": expected_particles,
                     "time_max_s": TARGET_TIME_MAX_S, "output_interval_s": TARGET_OUTPUT_INTERVAL_S},
        "wall_geometry": wall, "errors": [], "read_only": True,
        "central_ledger_mutation": 0, "central_registry_mutation": 0,
    }
    observations: dict[str, Any] = {
        "schema": "core.f3.baffle_exchange.runtime_observations.v1", "qualification_claim": "none",
        "matrix_credit": 0, "time_s": [], "event_window_complete": False,
    }
    if not trajectory.is_file():
        report["errors"] = ["missing_trajectory"]
        report["hard_integrity_pass"] = False
        report["requested_horizon_reached"] = False
        report["event_window_complete"] = False
        return report, observations
    positions: list[np.ndarray] = []
    valid_rows: list[np.ndarray] = []
    with h5py.File(trajectory, "r") as handle:
        missing = sorted(set(REQUIRED_DATASETS) - set(handle.keys()))
        report["datasets"] = {name: list(handle[name].shape) for name in handle.keys() if hasattr(handle[name], "shape")}
        complete = bool(handle.attrs.get("conversion_complete", False))
        report["conversion_complete"] = complete
        if missing:
            report["errors"].extend("missing:" + name for name in missing)
        if not complete:
            report["errors"].append("conversion:incomplete")
        if missing:
            report.update({"hard_integrity_pass": False, "requested_horizon_reached": False,
                           "event_window_complete": False})
            return report, observations
        shape_checks = {
            "particle_id": handle["particle_id"].shape == (expected_particles,),
            "time": handle["time"].shape == (expected_frames,),
            "position": handle["position"].shape == (expected_frames, expected_particles, 3),
            "velocity": handle["velocity"].shape == (expected_frames, expected_particles, 3),
            "density": handle["density"].shape == (expected_frames, expected_particles),
            "mass": handle["mass"].shape == (expected_frames, expected_particles),
            "valid": handle["valid"].shape == (expected_frames, expected_particles),
        }
        report["shape_pass"] = all(shape_checks.values())
        if not report["shape_pass"]:
            report["errors"].extend("shape:" + name for name, value in shape_checks.items() if not value)
            report.update({"hard_integrity_pass": False, "requested_horizon_reached": False,
                           "event_window_complete": False})
            return report, observations
        ids = np.asarray(handle["particle_id"][:])
        unique = len(np.unique(ids)) == len(ids)
        times = np.asarray(handle["time"][:], dtype=np.float64)
        monotone = bool(np.isfinite(times).all() and np.all(np.diff(times) > 0))
        cadence_tol = max(TIME_CADENCE_ABSOLUTE_FLOOR_S, TIME_CADENCE_RELATIVE_TOLERANCE * TARGET_OUTPUT_INTERVAL_S)
        cadence_error = np.abs(times - np.arange(expected_frames) * TARGET_OUTPUT_INTERVAL_S)
        cadence_pass = bool(monotone and np.isfinite(cadence_error).all() and np.all(cadence_error <= cadence_tol))
        horizon = bool(cadence_pass and times[-1] >= TARGET_TIME_MAX_S - cadence_tol)
        mass_reference = np.asarray(handle["mass"][0], dtype=np.float64)
        mass_changed = 0
        max_mass_change = 0.0
        endpoint_counts = {face: 0 for face in wall["closed_faces"]}
        obstacle_count = 0
        chord_count = 0
        first_wall = None
        first_obstacle = None
        first_chord = None
        finite_active = True
        all_valid = True
        active_nonpositive_mass = 0
        for frame in range(expected_frames):
            pos = np.asarray(handle["position"][frame], dtype=np.float64)
            vel = np.asarray(handle["velocity"][frame], dtype=np.float64)
            density = np.asarray(handle["density"][frame], dtype=np.float64)
            pressure = np.asarray(handle["pressure"][frame], dtype=np.float64)
            mass = np.asarray(handle["mass"][frame], dtype=np.float64)
            valid = np.asarray(handle["valid"][frame]).astype(bool)
            valid_rows.append(valid)
            positions.append(pos)
            all_valid = all_valid and bool(valid.all())
            active = valid
            finite_active = finite_active and bool(np.isfinite(pos[active]).all() and np.isfinite(vel[active]).all()
                                                   and np.isfinite(density[active]).all() and np.isfinite(pressure[active]).all()
                                                   and np.isfinite(mass[active]).all())
            active_nonpositive_mass += int(np.sum(active & (mass <= 0)))
            relative = np.abs(mass - mass_reference) / np.maximum(np.abs(mass_reference), 1e-30)
            frame_max = float(np.max(relative))
            max_mass_change = max(max_mass_change, frame_max)
            mass_changed += int(np.sum(relative > MASS_RELATIVE_TOLERANCE))
            if active.any():
                penetration = wall_penetration(pos[active], mass[active], wall, WALL_TOLERANCE_M)
                for face, count in penetration["outside_closed_container_by_face"].items():
                    endpoint_counts[face] += int(count)
                obstacle_count += int(penetration["obstacle_penetration_count"])
                if first_wall is None and penetration["outside_closed_container_count"]:
                    first_wall = {"frame": frame, "time_s": float(times[frame]), "summary": penetration}
                if first_obstacle is None and penetration["obstacle_penetration_count"]:
                    first_obstacle = {"frame": frame, "time_s": float(times[frame]), "summary": penetration}
            if frame:
                common = valid & valid_rows[frame - 1] & np.isfinite(pos).all(axis=1) & np.isfinite(positions[frame - 1]).all(axis=1)
                if common.any():
                    events = segment_crossing_events(positions[frame - 1][common], pos[common], wall, WALL_TOLERANCE_M)
                    chord_count += len(events)
                    if events and first_chord is None:
                        first_chord = {"frame_start": frame - 1, "frame_end": frame,
                                       "time_start_s": float(times[frame - 1]), "time_end_s": float(times[frame]),
                                       "event": events[0]}
            observations["time_s"].append(float(times[frame]))
        event = _event_audit(handle, geometry, times=times, positions=positions, valid_rows=valid_rows)
        observations.update({"event": event, "event_window_complete": event["event_window_complete"]})
        wall_pass = bool(not any(endpoint_counts.values()) and obstacle_count == 0 and chord_count == 0)
        hard = bool(complete and report["shape_pass"] and unique and all_valid and finite_active
                    and active_nonpositive_mass == 0 and mass_changed == 0 and cadence_pass and horizon and wall_pass)
        report.update({
            "particle_ids_unique": unique, "frames_scanned": expected_frames,
            "particles_scanned_per_frame": expected_particles,
            "time": {"first_s": float(times[0]), "last_s": float(times[-1]), "monotone": monotone,
                      "cadence_max_abs_error_s": float(np.max(cadence_error)), "cadence_tolerance_s": cadence_tol,
                      "cadence_pass": cadence_pass},
            "validity": {"all_entries_valid": all_valid},
            "finite_active": finite_active, "active_nonpositive_mass_count": active_nonpositive_mass,
            "mass_per_particle": {"constant_pass": mass_changed == 0, "max_relative_change": max_mass_change,
                                   "changed_value_count": mass_changed, "tolerance_relative": MASS_RELATIVE_TOLERANCE},
            "wall": {"endpoint_violation_count_by_face": endpoint_counts,
                     "endpoint_violation_count": int(sum(endpoint_counts.values())),
                     "obstacle_penetration_count": obstacle_count, "saved_chord_crossing_count": chord_count,
                     "first_endpoint_violation": first_wall, "first_obstacle_penetration": first_obstacle,
                     "first_saved_chord_crossing": first_chord, "closed_faces": wall["closed_faces"],
                     "open_faces": wall["open_faces"], "pass": wall_pass},
            "requested_horizon_reached": horizon, "event_window_complete": event["event_window_complete"],
            "hard_integrity_pass": hard,
        })
        if not unique:
            report["errors"].append("particle_id:duplicate")
        if not all_valid:
            report["errors"].append("valid:fluid_frame_incomplete")
        if not finite_active or active_nonpositive_mass:
            report["errors"].append("state:active_nonfinite_or_nonpositive_mass")
        if mass_changed:
            report["errors"].append("mass:per_particle_changed")
        if not cadence_pass or not horizon:
            report["errors"].append("time:saved_cadence_or_window")
        if not wall_pass:
            report["errors"].append("wall:outer_or_baffle_penetration")
        if not event["event_window_complete"]:
            report["errors"].append("event:baffle_exchange_window_incomplete")
    report["trajectory_sha256"] = digest(trajectory)
    report["trajectory_bytes"] = trajectory.stat().st_size
    observations["trajectory_sha256"] = report["trajectory_sha256"]
    observations["qualification_claim"] = "none; diagnostic event readout only"
    return report, observations


def _input_refs(binding: dict[str, Any]) -> list[dict[str, Any]]:
    paths = binding["paths"]
    result = [
        ref(paths["candidate"], "F3 baffle candidate card"),
        ref(paths["matrix"], "fixed 15-row F3 baffle matrix"),
        ref(paths["denominator"], "fixed F3 baffle failure denominator"),
        ref(paths["prepared"], "prepared q=.5 dp=.0075 baffle anchor"),
        ref(paths["review"], "root approval for one Ada anchor canary"),
        ref(Path(binding["prepared"]["solver_binary"]), "pinned DualSPHysics solver"),
        ref(Path(binding["prepared"]["decoder"]), "pinned native decoder"),
        ref(Path(__file__), "F3 baffle runtime adapter"),
    ]
    for path, expected in binding["prepared"].get("inputs", {}).items():
        path_obj = Path(path)
        if not any(item["path"] == str(path_obj.resolve()) for item in result):
            result.append({"path": str(path_obj.resolve()), "sha256": expected, "bytes": path_obj.stat().st_size,
                           "role": "hash-bound prepared source asset"})
    return result


def build_job(*, lab: Path, candidate: Path, matrix: Path, denominator: Path,
              prepared: Path, review: Path, output: Path) -> dict[str, Any]:
    binding = verify_bindings(candidate_path=candidate, matrix_path=matrix, denominator_path=denominator,
                              prepared_path=prepared, review_path=review)
    lab = Path(lab).resolve()
    output = Path(output).resolve()
    python = lab / ".venv/bin/python"
    spec = {
        "schema": JOB_SCHEMA, "job_id": TARGET_JOB_ID, "logical_id": TARGET_JOB_ID,
        "attempt_role": "single_root_review_anchor_canary", "category": "f3_baffle_exchange_anchor_canary",
        "host": "ada", "source_lab": str(lab), "cwd": str(lab),
        "argv": [str(python), str(Path(__file__).resolve()), "--lab-root", str(lab), "run",
                 "--candidate", str(Path(candidate).resolve()), "--matrix", str(Path(matrix).resolve()),
                 "--denominator", str(Path(denominator).resolve()), "--prepared", str(Path(prepared).resolve()),
                 "--root-review", str(Path(review).resolve()), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/trajectory.h5", "product/audit.json", "product/observations.json",
                             "product/result.json", "product/prepared.json", "product/worker-status.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 8192, "gpu_peak_mib": 8192, "io_weight": 1},
        "timeout_seconds": 1800, "depends_on": [], "qualification_claim": "none",
        "qualification_status": "one anchor diagnostic canary; fixed 15-row matrix remains unqualified",
        "input_files": _input_refs(binding), "prepared_case_id": TARGET_CASE_ID,
        "matrix_row_id": TARGET_ROW_ID, "matrix_index": TARGET_MATRIX_INDEX,
        "parameter_q": TARGET_Q, "parameter_dp_m": TARGET_DP_M,
        "registered_window_s": TARGET_TIME_MAX_S, "output_interval_s": TARGET_OUTPUT_INTERVAL_S,
        "scope_id": SCOPE_ID, "revision_id": REVISION_ID, "family": "F3",
        "matrix_credit": 0, "anchor_preflight_credit": 0,
        "solver_launch_authorized": True, "gpu_launch_authorized": True,
        "job_spec_creation_authorized": True, "direct_execution_authorized": True,
        "queue_mutation_authorized": False, "ledger_mutation_authorized": False,
        "registry_mutation_authorized": False, "matrix_expansion_authorized": False,
        "t1_registration_authorized": False,
        "worker_contract": "specialized F3 baffle adapter; one coordinator-assigned CUDA_VISIBLE_DEVICES mapped to solver -gpu:0",
        "postcondition": "retain hard-integrity, event-window, and time audit regardless of result; no T1 or matrix credit",
    }
    from scripts.core_runtime import validate_spec
    validate_spec(json.loads(json.dumps(spec, allow_nan=False)))
    write_json(output, spec)
    return spec


def _write_blocker(output: Path, binding: dict[str, Any], argv: list[str], returncode: int,
                   stdout_tail: str, error: str | None = None) -> dict[str, Any]:
    blocker = {"schema": "core.f3.baffle_exchange.runtime_blocker.v1", "created_at_utc": stamp(),
               "reason": "solver_or_runtime_compatibility_failure", "returncode": returncode,
               "argv": argv, "stdout_tail": stdout_tail[-12000:], "error": error,
               "prepared_sha256": digest(binding["paths"]["prepared"]),
               "candidate_sha256": digest(binding["paths"]["candidate"]),
               "matrix_sha256": digest(binding["paths"]["matrix"]),
               "failure_denominator_sha256": digest(binding["paths"]["denominator"]),
               "root_review_sha256": digest(binding["paths"]["review"]),
               "matrix_credit": 0, "qualification_claim": "none",
               "central_ledger_mutation": 0, "central_registry_mutation": 0,
               "next_step": "inspect solver compatibility and issue a new root review; do not retry this input"}
    write_json(output / "blocker.json", blocker)
    return blocker


def run_canary(*, lab: Path, candidate: Path, matrix: Path, denominator: Path,
               prepared: Path, review: Path, output: Path) -> dict[str, Any]:
    binding = verify_bindings(candidate_path=candidate, matrix_path=matrix, denominator_path=denominator,
                              prepared_path=prepared, review_path=review)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime product directory must be fresh: {output}")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or "," in visible:
        raise ValueError("coordinator must assign exactly one CUDA_VISIBLE_DEVICES device")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "prepared.json", binding["prepared"])
    solver_dir = output / "solver"
    argv = [binding["prepared"]["solver_binary"], "-gpu:0", *binding["prepared"]["recipe"]["solver_arguments"],
            binding["prepared"]["generated_prefix"], str(solver_dir)]
    write_json(output / "worker-status.json", {"status": "running", "argv": argv,
                                                "cuda_visible_devices": visible, "started_at_utc": stamp()})
    started = time.monotonic()
    with (output / "solver.stdout.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(argv, cwd=output, env=core_cfd.environment(lab), stdout=log,
                                 stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    stdout = (output / "solver.stdout.log").read_text(encoding="utf-8", errors="replace")
    if process.returncode != 0 or "Finished execution (code=0)" not in stdout:
        _write_blocker(output, binding, argv, process.returncode, stdout)
        write_json(output / "worker-status.json", {"status": "solver_failed", "returncode": process.returncode,
                                                    "elapsed_seconds": elapsed, "finished_at_utc": stamp()}, overwrite=True)
        raise RuntimeError("DualSPHysics baffle solver failed; blocker evidence retained")
    conversion = convert_native(binding["prepared"], binding["geometry"], solver_dir / "data", output / "trajectory.h5")
    audit, observations = audit_trajectory(binding["prepared"], binding["geometry"], output / "trajectory.h5",
                                            prepared_path=binding["paths"]["prepared"])
    write_json(output / "audit.json", audit)
    write_json(output / "observations.json", observations)
    result = {"schema": "core.f3.baffle_exchange.runtime_result.v1", "job_id": TARGET_JOB_ID,
              "case_id": TARGET_CASE_ID, "scope_id": SCOPE_ID, "revision_id": REVISION_ID,
              "qualification_claim": "none; one anchor canary is diagnostic only", "matrix_credit": 0,
              "solver_elapsed_seconds": elapsed, "conversion": conversion, "audit": audit,
              "observations": observations, "source_hashes": {
                  "candidate": digest(binding["paths"]["candidate"]), "matrix": digest(binding["paths"]["matrix"]),
                  "failure_denominator": digest(binding["paths"]["denominator"]),
                  "prepared": digest(binding["paths"]["prepared"]), "root_review": digest(binding["paths"]["review"]),
                  "adapter": digest(Path(__file__)), "solver": digest(Path(binding["prepared"]["solver_binary"])),
                  "decoder": digest(Path(binding["prepared"]["decoder"])),
              }, "execution_controls": {"solver_invoked": True, "gpu_invoked": True,
                                      "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
                                      "matrix_expansion": 0, "qualification_numerator_credit": 0},
              "hard_integrity_pass": audit["hard_integrity_pass"],
              "requested_horizon_reached": audit["requested_horizon_reached"],
              "event_window_complete": audit["event_window_complete"],
              "central_ledger_mutation": 0, "central_registry_mutation": 0}
    write_json(output / "result.json", result)
    write_json(output / "worker-status.json", {"status": "complete_with_evidence",
                                                "hard_integrity_pass": audit["hard_integrity_pass"],
                                                "event_window_complete": audit["event_window_complete"],
                                                "finished_at_utc": stamp()}, overwrite=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("dry-run", "make-job", "run"):
        p = sub.add_parser(command)
        p.add_argument("--candidate", type=Path, required=True)
        p.add_argument("--matrix", type=Path, required=True)
        p.add_argument("--denominator", type=Path, required=True)
        p.add_argument("--prepared", type=Path, required=True)
        p.add_argument("--root-review", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    kwargs = {"candidate": args.candidate, "matrix": args.matrix, "denominator": args.denominator,
              "prepared": args.prepared, "review": args.root_review}
    lab = args.lab_root.resolve()
    if args.command == "dry-run":
        binding = verify_bindings(**{key + "_path": value for key, value in kwargs.items()})
        print(json.dumps({"schema": SCHEMA, "status": "dry_run_pass", "matrix_index": TARGET_MATRIX_INDEX,
                          "case_id": TARGET_CASE_ID, "matrix_credit": 0,
                          "solver": binding["prepared"]["solver_binary"], "decoder": binding["prepared"]["decoder"]}, indent=2))
        return 0
    if args.command == "make-job":
        spec = build_job(lab=lab, **kwargs, output=args.output)
        print(json.dumps({"schema": SCHEMA, "status": "job_spec_written", "job_id": spec["job_id"],
                          "matrix_index": spec["matrix_index"], "matrix_credit": spec["matrix_credit"]}, indent=2))
        return 0
    result = run_canary(lab=lab, **kwargs, output=args.output)
    print(json.dumps({"schema": SCHEMA, "status": "completed", "case_id": result["case_id"],
                      "hard_integrity_pass": result["hard_integrity_pass"],
                      "requested_horizon_reached": result["requested_horizon_reached"],
                      "event_window_complete": result["event_window_complete"], "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
