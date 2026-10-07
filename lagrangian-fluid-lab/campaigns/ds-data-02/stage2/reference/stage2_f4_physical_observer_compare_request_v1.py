#!/usr/bin/env python3
"""Register launch-disabled F4 selected-observer comparison requests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


SCHEMA = "ds02.stage2.f4-physical-observer-compare-request.v1"
REPO = Path(__file__).resolve().parents[5]
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-compare-v1"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_compare_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py")
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py")
REFERENCE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_DP0_SAME_CFL_SELECTED_PHYSICAL_OBSERVER_V2/f4-s1-dp0-same-cfl-selected-observer-primary-001/observer/f4_s1_dp0_selected_physical_observer.json")
PHYSICAL_CASE_ID = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
THRESHOLDS = {
    "position_scale_fraction_L": 0.02,
    "event_position_fraction_L": 0.05,
    "velocity_relative_fraction_nonzero_scale": 0.05,
    "kinetic_energy_relative_fraction_nonzero_scale": 0.05,
    "regional_mass_fraction_of_whole_initial": 0.03,
    "event_time_fraction": 0.01,
    "time_budget_fraction": 0.25,
    "output_budget_fraction": 0.25,
}


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def rec(path: Path) -> dict[str, object]:
    s = path.stat()
    return {"path": str(path.resolve()), "bytes": s.st_size, "mtime_ns": s.st_mtime_ns, "sha256": sha256(path)}


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def make(grid: str, attempt: str, case: str, candidate: Path, observer_request: Path, output_name: str) -> dict[str, object]:
    candidate_root = candidate.parent.parent
    # The candidate sidecar is produced by the already registered selected
    # observer request.  It is intentionally deferred: this preparation
    # request must not pretend that that worker has completed.
    input_files = [WORKER, PYTHON, DISPATCH, STRICT, RUNTIME, REFERENCE, observer_request]
    return {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": case,
        "sentinel_id": "F4-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": attempt,
        "kind": "cpu",
        "qualification_stage": "stage2_selected_observer_comparison_pending_parent_observer_output",
        "cpu_task_kind": "comparison",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 134217728,
        "estimated_peak_memory_bytes": 268435456,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [str(PYTHON), str(WORKER), "--reference", str(REFERENCE), "--variant", str(candidate), "--output", "{attempt_root}/comparison/" + output_name, "--physical-case-id", PHYSICAL_CASE_ID],
        "reference_observer": rec(REFERENCE),
        "variant_observer": {"path": str(candidate), "status": "PARENT_SELECTED_OBSERVER_OUTPUT_REQUIRED", "source_solver_or_observer_root": str(candidate_root)},
        "selected_observer_request": rec(observer_request),
        "source_binding": {
            "schema": SCHEMA,
            "sentinel_id": "F4-S1", "family_id": "F4", "physical_case_id": PHYSICAL_CASE_ID, "grid": grid,
            "reference_grid": "dp0_same_cfl",
            "variant_grid": grid,
            "query_times_s": [0.0, 0.3, 0.6, 0.9, 1.2],
            "comparison_fields": ["position", "velocity", "kinetic_energy", "fluid sample mass", "fluid region/MK allocation", "density mean"],
            "sampling": "common physical query times; retain exact/bracket status; no bracket interpolation or extrapolation",
            "particle_pairing": "not performed; aggregate observables by XML fluid ranges only",
            "mass_semantics": "native particle sample mass only; never rigid/continuum mass",
            "frozen_tolerances": THRESHOLDS,
        },
        "input_files": [str(x) for x in input_files],
        "input_hashes": {str(x): sha256(x) for x in input_files},
        "deferred_input_files": [str(candidate)],
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME),
            "cpu_parent_binding": "required", "gpu": "none", "gpu_uuid": "none",
            "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True,
            "parent_observer_receipt_required": True,
        },
        "output_protection": {"refuse_overwrite": True, "output_atomic": True},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build() -> list[Path]:
    coarse_req = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-forward-v1/f4_s1_coarse_same_cfl_selected_physical_observer.json"
    half_req = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-forward-v1/f4_s1_dp0_half_cfl_selected_physical_observer.json"
    coarse = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_COARSE_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-coarse-selected-physical-observer-forward-v1-root-001/observer/f4_s1_selected_physical_observer.json")
    half = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_HALF_CFL_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-half-cfl-selected-physical-observer-forward-v1-root-001/observer/f4_s1_selected_physical_observer.json")
    configs = [
        ("coarse", "f4-s1-coarse-observer-compare-v1-root-001", "F4_S1_COARSE_OBSERVER_COMPARE_V1", coarse, coarse_req, "f4_s1_coarse_vs_dp0_comparison.json"),
        ("half_cfl", "f4-s1-half-cfl-observer-compare-v1-root-001", "F4_S1_HALF_CFL_OBSERVER_COMPARE_V1", half, half_req, "f4_s1_half_cfl_vs_dp0_comparison.json"),
    ]
    paths = []
    for grid, attempt, case, candidate, selected_request, name in configs:
        path = REQUEST_ROOT / name
        atomic(path, make(grid, attempt, case, candidate, selected_request, name))
        paths.append(path)
    return paths


if __name__ == "__main__":
    print(json.dumps({"requests": [str(x) for x in build()]}, indent=2))
