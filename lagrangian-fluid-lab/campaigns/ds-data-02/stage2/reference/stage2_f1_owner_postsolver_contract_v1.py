#!/usr/bin/env python3
"""Freeze the F1 owner post-solver observation contract before decoding.

This file registers the observable scales and task-level budgets for the
owner-centred F1-S1 ``dp=.005/.0025`` runs.  It does not read a solver output
tree, native BI4, HDF5, or PartVTK data.  A later parent-guarded observer must
bind actual RunPARTs times and receipts to this contract before comparing
fields.  The contract deliberately keeps event time UNKNOWN until an event
definition and an observed bracket exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f1.owner-postsolver-observation-contract.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
PHYSICAL_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
QUALITY = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
DEFAULT_OUTPUT = REFERENCE / "stage2_f1_owner_postsolver_observation_contract_v1.json"
OWNER_MASS_KG = 40.2
GRAVITY_M_S2 = 9.81
QUERY_TIMES_S = (0.0, 0.4, 0.8, 1.2, 1.6)
DP_RUNS = {"dp005": 0.005, "dp0025": 0.0025}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(path)}


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable contract: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def _owner_geometry(owner: Mapping[str, Any]) -> dict[str, Any]:
    binding = owner.get("physical_binding", {})
    geometry = binding.get("geometry", {})
    fluid = geometry.get("fluid_reservoir", {})
    size = [float(value) for value in fluid.get("size_m", [])]
    low = [float(value) for value in fluid.get("low_m", [])]
    if len(size) != 3 or len(low) != 3 or not all(math.isfinite(value) and value > 0 for value in size):
        raise ValueError("F1 owner fluid geometry is incomplete or non-finite")
    if binding.get("physical_case_id") != "F1_ECC_THICK_DBC_LOWER_HEAD_V1":
        raise ValueError("F1 owner physical identity differs")
    if abs(float(binding.get("density_kg_m3", 1000.0)) - 1000.0) > 1e-12:
        raise ValueError("unexpected owner density")
    return {"low_m": low, "size_m": size, "mkfluid": fluid.get("mkfluid"),
            "label": fluid.get("label"), "volume_m3": math.prod(size)}


def build() -> dict[str, Any]:
    owner = load_object(OWNER, "F1 owner")
    geometry = _owner_geometry(owner)
    controls = owner.get("physical_binding", {}).get("controls", {})
    gravity = owner.get("physical_binding", {}).get("gravity_m_s2", [0.0, 0.0, -GRAVITY_M_S2])
    if len(gravity) != 3 or not all(math.isfinite(float(value)) for value in gravity):
        raise ValueError("F1 owner gravity is not finite")
    if abs(abs(float(gravity[2])) - GRAVITY_M_S2) > 1e-12:
        raise ValueError("F1 owner gravity differs from the registered scale basis")
    # The longest continuous source-fluid span is the pre-registered position
    # scale.  It is a source fact, not a scale fitted to a result.
    length_m = max(geometry["size_m"])
    velocity_m_per_s = math.sqrt(GRAVITY_M_S2 * length_m)
    ke_j = 0.5 * OWNER_MASS_KG * velocity_m_per_s**2
    if not all(math.isfinite(value) and value > 0 for value in (length_m, velocity_m_per_s, ke_j)):
        raise ValueError("registered F1 scales are not finite and non-zero")
    physical = owner.get("physical_binding", {})
    event_window = physical.get("event_window", {})
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PRE_REGISTERED_NO_SOLVER_RESULT",
        "identity": {
            "family_id": "F1", "sentinel_id": "F1-S1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "lineage_group_id": physical.get("lineage_group_id"),
        },
        "source_authority": {
            "owner": record(OWNER), "physical_binding": record(PHYSICAL_BINDING),
            "quality_label_split": record(QUALITY),
            "continuous_geometry": geometry,
            "continuous_mass_kg": OWNER_MASS_KG,
            "mass_role": "continuous owner mass; particle sample sums remain a separate diagnostic",
            "gravity_m_s2": list(gravity),
            "event_window_from_owner_s": [event_window.get("time_start_s"), event_window.get("time_end_s")],
            "solver_output_window_is_not_event_characteristic_time": True,
        },
        "spatial_runs": {
            "dp005": {"dp_m": DP_RUNS["dp005"], "role": "owner-centred fine rung", "initial_qa_required": True},
            "dp0025": {"dp_m": DP_RUNS["dp0025"], "role": "owner-centred third rung", "initial_qa_required": True},
            "cross_grid_particle_id_pairing": "FORBIDDEN",
            "continuous_geometry_and_control": "MUST_MATCH_SOURCE_AUTHORITY; only dp/h/mass/count/lattice fields may vary",
        },
        "registered_observables": {
            "query_times_s": list(QUERY_TIMES_S),
            "time_binding": "actual RunPARTs timestamps per run; EXACT/BRACKETED retained; no extrapolation",
            "fields": [
                "fluid weighted centroid by source MK", "fluid weighted velocity by source MK",
                "fluid sample mass by source MK", "fluid kinetic energy by source MK",
                "first-passage state with saved-time bracket", "terminal destination with censoring state",
            ],
            "mk_coordinate_contract": "mkfluid_relative and mk_absolute remain separate; source cohort mapping is explicit",
            "pressure_status": "NOT_DECODED_BY_OBSERVER_UNLESS_SEPARATE_SOURCE_BOUND_FIELD_TASK",
        },
        "task_tolerances": {
            "position": {
                "reference_scale_m": length_m,
                "rmse_fraction": 0.02,
                "rmse_absolute_m": 0.02 * length_m,
                "event_max_fraction": 0.05,
                "event_max_absolute_m": 0.05 * length_m,
            },
            "velocity": {"reference_scale_m_per_s": velocity_m_per_s, "rmse_fraction": 0.05},
            "kinetic_energy": {"reference_scale_j": ke_j, "rmse_fraction": 0.05,
                               "zero_or_near_zero_policy": "UNKNOWN; never divide by near-zero result"},
            "source_mass": {"denominator_kg": OWNER_MASS_KG, "absolute_fraction": 0.03,
                            "unit": "fraction of whole initial owner mass; three percentage points"},
            "event_time": {"characteristic_time": "UNKNOWN_UNTIL_EVENT_DEFINITION_AND_OBSERVATION",
                           "relative_width_fraction": 0.01, "physical_seconds_required": True},
            "time_alignment_budget": {"fraction_of_corresponding_task_tolerance": 0.25,
                                       "window_fraction_gate": "FORBIDDEN"},
            "output_reconstruction_budget": {"fraction_of_corresponding_task_tolerance": 0.25,
                                               "window_fraction_gate": "FORBIDDEN"},
        },
        "calibration_plan": {
            "status": "PENDING_PARENT_GUARDED_POSTSOLVER_OBSERVER",
            "manufactured_trajectory": {
                "purpose": "verify bracket/time interpolation implementation only",
                "trajectory": "quadratic position, linear velocity, constant mass/KE reference",
                "does_not_calibrate_physical_solver": True,
            },
            "actual_output": {
                "same_run_dense_rows_subsample_factors": [2, 4],
                "compare_only_deleted_rows_with_actual_neighbor_brackets": True,
                "time_source": "RunPARTs actual saved rows",
                "spatial_truth": "not inferred from adjacent grid differences",
                "integration_error": "separate UNKNOWN channel until an independent time/integration anchor exists",
            },
        },
        "qualification": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "reason": "pre-registration only; no postsolver fields or brackets consumed",
        },
        "scope": {"solver_started": False, "native_read": False, "hdf5_read": False,
                  "partvtk_read": False, "gpu_lease": "none"},
        "preparation_commit": _git_head(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build()
    if args.self_test:
        assert value["status"] == "PRE_REGISTERED_NO_SOLVER_RESULT"
        assert value["task_tolerances"]["time_alignment_budget"]["window_fraction_gate"] == "FORBIDDEN"
        assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                                           "reason": "pre-registration only; no postsolver fields or brackets consumed"}
        print(json.dumps({"status": "PASS", "length_m": value["task_tolerances"]["position"]["reference_scale_m"],
                          "velocity_scale_m_per_s": value["task_tolerances"]["velocity"]["reference_scale_m_per_s"]}))
        return 0
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
