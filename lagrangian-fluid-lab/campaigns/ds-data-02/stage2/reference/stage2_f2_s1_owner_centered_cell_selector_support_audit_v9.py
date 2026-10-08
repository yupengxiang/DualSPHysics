#!/usr/bin/env python3
"""Strict, grid-parameterized F2-S1 initial support QA (forward V9).

V8 was intentionally tied to the completed coarse ``.0088`` product.  This
forward worker keeps its binary VTK parser and guarded pre/post file contract,
but derives every count and selector from the supplied middle/fine candidate
and terminal generated XML.  It therefore cannot silently apply a coarse
particle count or selector to a different grid.  The owner mass (18.876 kg)
and the source control/motion identity remain frozen diagnostics; generated
particle mass is never rescaled and never grants numerical qualification.

The worker reads only the terminal GenCase XML/Fluid.vtk/Bound.vtk and small
source/request files after the parent CPU reservation.  It never reads BI4,
HDF5, or solver output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V8_PATH = HERE / "stage2_f2_s1_owner_centered_cell_selector_support_audit_v8.py"
SPEC = importlib.util.spec_from_file_location("stage2_f2_support_v8_runtime", V8_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(V8_PATH)
V8 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V8
SPEC.loader.exec_module(V8)

OWNER_MASS_KG = 18.876
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
GRID = {
    "middle": {"dp_m": 0.0044, "label": "DP0044"},
    "fine": {"dp_m": 0.0022, "label": "DP0022"},
}
TOL = 1e-9


def _same(a: Any, b: Any) -> bool:
    return a == b


def _assert_identity(request: dict[str, Any], grid: str) -> None:
    if request.get("schema") != "ds02.request.v1":
        raise ValueError("unexpected GenCase request schema")
    if request.get("family_id") != "F2" or request.get("sentinel_id") != "F2-S1":
        raise ValueError("GenCase request is not F2-S1")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("GenCase physical case identity mismatch")
    binding = request.get("source_binding") or {}
    representation = binding.get("representation") or {}
    actual_grid = representation.get("grid_name") or binding.get("grid_name")
    if actual_grid is not None and actual_grid != grid:
        raise ValueError(f"request grid {actual_grid!r} != requested {grid!r}")


def _configure_from_xml(candidate: dict[str, Any], source: dict[str, Any], generated: dict[str, Any], grid: str) -> None:
    """Configure the consumed parser without carrying V8's coarse constants."""
    if grid not in GRID:
        raise ValueError(f"unsupported forward grid {grid!r}")
    expected_dp = GRID[grid]["dp_m"]
    if abs(candidate["dp_m"] - expected_dp) > TOL:
        raise ValueError(f"candidate dp {candidate['dp_m']} is not registered {grid} dp {expected_dp}")
    if candidate["shape_mode"] != "dp | actual | bound":
        raise ValueError(f"candidate shape mode is not the registered three-mode selector: {candidate['shape_mode']!r}")
    if len(source["fluid_boxes"]) != 3 or len(candidate["fluid_boxes"]) != 3 or len(generated["fluid_boxes"]) != 3:
        raise ValueError("F2-S1 requires exactly three fluid selector boxes")
    if len(generated["fluid_blocks"]) != 3 or any(int(b["count"]) <= 0 for b in generated["fluid_blocks"]):
        raise ValueError("generated XML must contain three non-empty typed fluid blocks")
    # The owner boxes are parsed from the frozen source, while all selector
    # values and block counts are taken from the actual supplied files.
    V8.OWNER_MASS_KG = OWNER_MASS_KG
    V8.OWNER_LAYER_LOWS = [list(box["low_m"]) for box in source["fluid_boxes"]]
    V8.OWNER_LAYER_SIZE = list(source["fluid_boxes"][0]["size_m"])
    V8.EXPECTED_DP = expected_dp
    V8.EXPECTED_SHAPE_MODE = candidate["shape_mode"]
    V8.EXPECTED_SELECTOR_LOWS = [list(box["low_m"]) for box in candidate["fluid_boxes"]]
    V8.EXPECTED_SELECTOR_SIZE = list(candidate["fluid_boxes"][0]["size_m"])
    V8.EXPECTED_BLOCK_COUNT = int(generated["fluid_blocks"][0]["count"])
    V8.EXPECTED_FLUID_COUNT = int(generated["fluid_count"])


def _validate_xml_contract(source: dict[str, Any], candidate: dict[str, Any], generated: dict[str, Any], grid: str) -> dict[str, Any]:
    expected_dp = GRID[grid]["dp_m"]
    if abs(generated["dp_m"] - expected_dp) > TOL:
        raise ValueError("generated definition dp differs from registered candidate")
    if generated["shape_mode"] != candidate["shape_mode"]:
        raise ValueError("generated shape mode differs from candidate")
    generated_boxes = generated["fluid_boxes"]
    candidate_boxes = candidate["fluid_boxes"]
    box_equal = all(
        _same(g["low_m"], c["low_m"]) and _same(g["size_m"], c["size_m"])
        for g, c in zip(generated_boxes, candidate_boxes)
    )
    if not box_equal:
        raise ValueError("generated selector geometry differs from candidate definition")
    control_keys = ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting", "SlipMode", "StepAlgorithm")
    controls_equal = all(source["parameters"].get(k) == candidate["parameters"].get(k) for k in control_keys)
    boundary_equal = source["boundary_boxes"] == candidate["boundary_boxes"]
    if not controls_equal or not boundary_equal:
        raise ValueError("candidate changes frozen source controls or boundary geometry")
    return {
        "grid": grid,
        "registered_dp_m": expected_dp,
        "generated_dp_m": generated["dp_m"],
        "candidate_selector_equals_generated": box_equal,
        "source_candidate_solver_controls_equal": controls_equal,
        "source_candidate_boundary_geometry_equal": boundary_equal,
        "candidate_motion_path_identity_checked_by_worker": True,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    grid = args.grid
    generated = V8.parse_xml(args.generated_xml.resolve(), generated=True)
    source = V8.parse_xml(args.source_def.resolve(), generated=False)
    candidate = V8.parse_xml(args.candidate_def.resolve(), generated=False)
    request = json.loads(args.gencase_request.resolve().read_text(encoding="utf-8"))
    _assert_identity(request, grid)
    _configure_from_xml(candidate, source, generated, grid)
    contract = _validate_xml_contract(source, candidate, generated, grid)
    report = V8.build_report(args)
    report["schema"] = "ds02.stage2.f2-s1.owner-centered-cell-selector-support-audit.v9"
    report["status"] = "COMPLETED_PARAMETERIZED_INITIAL_XML_VTK_SUPPORT_AUDIT"
    report["grid"] = grid
    report["registered_representation"] = {
        "dp_m": GRID[grid]["dp_m"],
        "owner_continuous_mass_kg": OWNER_MASS_KG,
        "particle_count_source": "actual generated XML fluid blocks; no forecast or coarse constant",
        "selector_source": "actual candidate and generated XML fluid boxes",
        "continuous_geometry_and_particle_selector_are_separate": True,
    }
    report["strict_contract_v9"] = contract
    report["qualification"]["reason"] = (
        "parameterized F2-S1 generated XML/VTK support and frozen-owner mass/control audit; "
        "actual counts are reported, selector/continuous owner geometry remain separate, no CFD"
    )
    return report


def self_test() -> dict[str, Any]:
    if GRID["middle"]["dp_m"] != 0.0044 or GRID["fine"]["dp_m"] != 0.0022:
        raise AssertionError("registered F2 ladder changed")
    candidate = {"dp_m": 0.0044, "shape_mode": "dp | actual | bound", "fluid_boxes": [{"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0]}] * 3, "parameters": {}, "boundary_boxes": []}
    source = {"fluid_boxes": [{"low_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 1.0]}] * 3, "parameters": {}, "boundary_boxes": []}
    generated = {"dp_m": 0.0044, "shape_mode": "dp | actual | bound", "fluid_boxes": candidate["fluid_boxes"], "fluid_blocks": [{"count": 1}] * 3, "fluid_count": 3}
    _configure_from_xml(candidate, source, generated, "middle")
    contract = _validate_xml_contract(source, candidate, generated, "middle")
    if not contract["candidate_selector_equals_generated"]:
        raise AssertionError(contract)
    try:
        bad = dict(generated); bad["dp_m"] = 0.0088
        _validate_xml_contract(source, candidate, bad, "middle")
    except ValueError:
        pass
    else:
        raise AssertionError("unregistered coarse dp accepted")
    return {"status": "PASS", "grids": sorted(GRID), "coarse_constants_rejected": True, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--grid", choices=sorted(GRID))
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "gencase-request", "owner-closure", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "gencase-request", "owner-closure", "generated-xml", "receipt"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.grid, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.gencase_request, args.output]
    if any(value is None for value in required):
        parser.error("--grid and all generated/static paths and --output are required")
    report = build_report(args)
    V8.write_new(args.output, report)
    print(json.dumps({"status": report["status"], "grid": args.grid, "mass_gate": report["mass_audit"]["gate"], "support_gate": report["vtk_support"]["support_gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
