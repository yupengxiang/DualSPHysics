#!/usr/bin/env python3
"""Forward builder for comparison requests after the worker source freeze."""

from __future__ import annotations

import json
from pathlib import Path

from stage2_f4_physical_observer_compare_request_v1 import (  # noqa: E402
    REPO,
    REFERENCE,
    REQUEST_ROOT as V1_ROOT,
    WORKER,
    make,
    atomic,
)


OUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-compare-v2"


def build() -> list[Path]:
    old_root = V1_ROOT
    v1_coarse = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-forward-v1/f4_s1_coarse_same_cfl_selected_physical_observer.json"
    v1_half = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-forward-v1/f4_s1_dp0_half_cfl_selected_physical_observer.json"
    configs = [
        ("coarse", "f4-s1-coarse-observer-compare-v2-root-001", "F4_S1_COARSE_OBSERVER_COMPARE_V2", "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_COARSE_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-coarse-selected-physical-observer-forward-v1-root-001/observer/f4_s1_selected_physical_observer.json", v1_coarse, "f4_s1_coarse_vs_dp0_comparison_v2.json"),
        ("half_cfl", "f4-s1-half-cfl-observer-compare-v2-root-001", "F4_S1_HALF_CFL_OBSERVER_COMPARE_V2", "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_S1_HALF_CFL_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-half-cfl-selected-physical-observer-forward-v1-root-001/observer/f4_s1_selected_physical_observer.json", v1_half, "f4_s1_half_cfl_vs_dp0_comparison_v2.json"),
    ]
    paths: list[Path] = []
    for grid, attempt, case, candidate, observer_request, filename in configs:
        value = make(grid, attempt, case, Path(candidate), observer_request, filename)
        value["qualification_stage"] = "stage2_selected_observer_comparison_v2_pending_parent_observer_output"
        value["source_binding"]["schema"] = "ds02.stage2.f4-physical-observer-compare-request.v2"
        value["source_binding"]["worker_source_freeze"] = {"path": str(WORKER), "sha256": value["input_hashes"][str(WORKER)]}
        path = OUT_ROOT / filename
        atomic(path, value)
        paths.append(path)
    return paths


if __name__ == "__main__":
    print(json.dumps({"requests": [str(path) for path in build()]}, indent=2))
