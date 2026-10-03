#!/usr/bin/env python3
"""Source-bound typed conversion templates and frozen spatial macro preregistration.

This module inspects the four completed spatial SAVE010 solver executions for matched RV4:
- CENTER coarse DP010 (98.709 s, 401 frames, 122 excluded particles)
- CENTER medium DP008 (266.534 s, 401 frames, 216 excluded particles)
- OFFSET coarse DP010 (118.527 s, 401 frames, 118 excluded particles)
- OFFSET medium DP008 (719.516 s, 401 frames, 210 excluded particles)

It compares their initial continuum fluid mass (exact matching M=24.576 kg),
geometry, and control domain against the fine DP005 baselines, and generates
source-bound typed conversion templates without launching trajectory conversion.

Scientific qualification boundaries:
- Save interval .01 s has half-bracket width 0.005 s, which is insufficient for
  the frozen event temporal allocation 0.0001467278159987655 s (halfbar .005).
- Event Q-N is never granted from these spatial macros (Q-N remains not_assessed).
- Preserves F3 weak quarter freeze original allocation
  x=0.010238388262513484 / y=0.017270993599294474.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-spatial-macro-preregistration.v1"
CONVERSION_SCHEMA = "ds-data-02.runner.request.v1"

HANDOFF_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = HANDOFF_ROOT / "artifacts"
SOLVER_REQUEST_DIR = HANDOFF_ROOT / "solver_requests_spatial_reference_v1"
CONVERSION_TEMPLATE_DIR = HANDOFF_ROOT / "conversion_templates_spatial_reference_v1"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA = DATA_ROOT / "families/F2"

INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INTEGRATION_LAB = INTEGRATION_ROOT / "lagrangian-fluid-lab"
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics") / "lagrangian-fluid-lab"
PYTHON = INTEGRATION_LAB / ".venv/bin/python"
DIRECT_CONVERTER = INTEGRATION_LAB / "scripts/ds_data02_direct_convert.py"
BI4_DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"
PARTVTK = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"

CONTINUOUS_MASS_KG = 24.576
EVENT_TIME_BUDGET_S = 0.0036681953999691376
SAVE_TOTAL_BUDGET_S = 0.0007336390799938275
SAVE_ALLOCATION_S = 0.0001467278159987655  # halfbar .005 is >> this allocation
SPATIAL_SAVE_S = 0.01
SPATIAL_HALF_BRACKET_S = 0.005
EXPECTED_FRAMES = 401
TIME_MAX_S = 4.0
MACRO_RELATIVE_BUDGET = 0.05

F3_PRESERVED_BOUNDARIES = {
    "weak_quarter_allocation_x": 0.010238388262513484,
    "weak_quarter_allocation_y": 0.017270993599294474,
    "actual_conditional_gap_x": 0.02248,
    "actual_conditional_gap_y": 0.06929,
    "gate_verdict": "fail",
    "whole_cohort_q_diagnostic_is_not_original_preregistered_gate": True,
    "f3_gpu_forbidden": True,
}

SPATIAL_CASES: list[dict[str, Any]] = [
    {
        "case_id": "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "background": "CENTER",
        "resolution": "coarse",
        "dp_m": 0.010,
        "physical_case_id": "F2H10V2_CENTER_V1",
        "physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "numerical_recipe_hash": "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7",
        "attempt_id": "qualification-f2_rv4eq_matched_center_v1_coarse_dp010-spatial-reference-save010-root-review-001",
        "expected_elapsed_seconds": 98.70925360103138,
        "expected_excluded_particles": 122,
        "initial_fluid_particles": 24576,
        "total_particles": 421566,
    },
    {
        "case_id": "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "background": "CENTER",
        "resolution": "medium",
        "dp_m": 0.008,
        "physical_case_id": "F2H10V2_CENTER_V1",
        "physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "numerical_recipe_hash": "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7",
        "attempt_id": "qualification-f2_rv4eq_matched_center_v1_medium_dp008-spatial-reference-save010-root-review-001",
        "expected_elapsed_seconds": 266.53445844212547,
        "expected_excluded_particles": 216,
        "initial_fluid_particles": 48000,
        "total_particles": 668673,
    },
    {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
        "background": "OFFSET",
        "resolution": "coarse",
        "dp_m": 0.010,
        "physical_case_id": "F2H10V2_OFFSET_V1",
        "physical_condition_hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
        "numerical_recipe_hash": "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7",
        "attempt_id": "qualification-f2_rv4eq_matched_offset_v1_coarse_dp010-spatial-reference-save010-root-review-001",
        "expected_elapsed_seconds": 118.52724714507349,
        "expected_excluded_particles": 118,
        "initial_fluid_particles": 24576,
        "total_particles": 421566,
    },
    {
        "case_id": "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
        "background": "OFFSET",
        "resolution": "medium",
        "dp_m": 0.008,
        "physical_case_id": "F2H10V2_OFFSET_V1",
        "physical_condition_hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
        "numerical_recipe_hash": "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7",
        "attempt_id": "qualification-f2_rv4eq_matched_offset_v1_medium_dp008-spatial-reference-save010-root-review-001",
        "expected_elapsed_seconds": 719.5156498579308,
        "expected_excluded_particles": 210,
        "initial_fluid_particles": 48000,
        "total_particles": 668673,
    },
]

FINE_BASELINES: dict[str, dict[str, Any]] = {
    "CENTER": {
        "case_id": "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001",
        "dp_m": 0.005,
        "fluid_particles": 196608,
        "total_particles": 1667249,
        "continuum_mass_kg": 24.576,
        "native_unknown_count": 2123,
        "native_unknown_mass_kg": 0.265375,
        "native_unknown_mass_fraction": 0.265375 / 24.576,
    },
    "OFFSET": {
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "dp_m": 0.005,
        "fluid_particles": 196608,
        "total_particles": 1667249,
        "continuum_mass_kg": 24.576,
        "native_unknown_count": 2151,
        "native_unknown_mass_kg": 2151 * (24.576 / 196608),
        "native_unknown_mass_fraction": (2151 * (24.576 / 196608)) / 24.576,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def inspect_solver_run(case: dict[str, Any]) -> dict[str, Any]:
    case_root = F2_DATA / case["case_id"] / case["attempt_id"]
    receipt_path = require(case_root / "execution-receipt.json", "solver execution receipt")
    receipt = read_json(receipt_path, "solver execution receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"solver run did not complete successfully: {case['case_id']}")

    solver_output = case_root / "solver_output"
    run_out = require(solver_output / "Run.out", "solver Run.out")
    run_csv = require(solver_output / "Run.csv", "solver Run.csv")
    run_parts = require(solver_output / "RunPARTs.csv", "solver RunPARTs.csv")
    data_dir = solver_output / "data"

    first_part = require(data_dir / "Part_0000.bi4", "first Part BI4")
    last_part = require(data_dir / "Part_0400.bi4", "last Part BI4")
    middle_part = require(data_dir / "Part_0200.bi4", "middle Part BI4")
    part_info = require(data_dir / "PartInfo.ibi4", "PartInfo")
    part_motion = require(data_dir / "PartMotionRef.ibi4", "PartMotionRef")
    part_out = require(data_dir / "PartOut_000.obi4", "PartOut")

    # Extract excluded particle count from Run.out
    ro_text = run_out.read_text(encoding="utf-8")
    excluded = None
    for line in ro_text.splitlines():
        if "Excluded particles" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                excluded = int(parts[1].strip())
    if excluded != case["expected_excluded_particles"]:
        raise ValueError(f"excluded particle count mismatch for {case['case_id']}: {excluded} != {case['expected_excluded_particles']}")

    mass_per_particle_kg = CONTINUOUS_MASS_KG / float(case["initial_fluid_particles"])
    excluded_mass_kg = excluded * mass_per_particle_kg
    excluded_mass_fraction = excluded_mass_kg / CONTINUOUS_MASS_KG

    return {
        "case_id": case["case_id"],
        "background": case["background"],
        "resolution": case["resolution"],
        "dp_m": case["dp_m"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_hash": case["physical_condition_hash"],
        "numerical_recipe_hash": case["numerical_recipe_hash"],
        "attempt_id": case["attempt_id"],
        "receipt": {
            "path": str(receipt_path),
            "sha256": sha256(receipt_path),
            "status": receipt["status"],
            "returncode": receipt["returncode"],
            "elapsed_seconds": receipt.get("elapsed_seconds"),
            "pid": receipt.get("pid"),
        },
        "metrics": {
            "frames_saved": EXPECTED_FRAMES,
            "window_seconds": TIME_MAX_S,
            "save_interval_s": SPATIAL_SAVE_S,
            "save_half_bracket_s": SPATIAL_HALF_BRACKET_S,
            "initial_fluid_particles": case["initial_fluid_particles"],
            "total_particles": case["total_particles"],
            "continuum_mass_kg": CONTINUOUS_MASS_KG,
            "mass_per_particle_kg": mass_per_particle_kg,
            "excluded_particles": excluded,
            "excluded_mass_kg": excluded_mass_kg,
            "excluded_mass_fraction": excluded_mass_fraction,
            "retained_mass_kg": CONTINUOUS_MASS_KG - excluded_mass_kg,
            "retained_mass_fraction": 1.0 - excluded_mass_fraction,
        },
        "source_bindings": {
            "solver_output_root": str(solver_output),
            "run_out": {"path": str(run_out), "sha256": sha256(run_out), "bytes": run_out.stat().st_size},
            "run_csv": {"path": str(run_csv), "sha256": sha256(run_csv), "bytes": run_csv.stat().st_size},
            "run_parts": {"path": str(run_parts), "sha256": sha256(run_parts), "bytes": run_parts.stat().st_size},
            "first_part": {"path": str(first_part), "sha256": sha256(first_part), "bytes": first_part.stat().st_size},
            "middle_part": {"path": str(middle_part), "sha256": sha256(middle_part), "bytes": middle_part.stat().st_size},
            "last_part": {"path": str(last_part), "sha256": sha256(last_part), "bytes": last_part.stat().st_size},
            "part_info": {"path": str(part_info), "sha256": sha256(part_info), "bytes": part_info.stat().st_size},
            "part_motion_ref": {"path": str(part_motion), "sha256": sha256(part_motion), "bytes": part_motion.stat().st_size},
            "part_out": {"path": str(part_out), "sha256": sha256(part_out), "bytes": part_out.stat().st_size},
        },
    }


def build_conversion_template(case_info: dict[str, Any], output_path: Path) -> dict[str, Any]:
    case_id = case_info["case_id"]
    attempt_id = f"conversion-{case_id.lower()}-spatial-reference-template-v1"
    output_root = F2_DATA / case_id / attempt_id

    source_bindings = case_info["source_bindings"]
    solver_receipt = case_info["receipt"]

    # Locate source request for gencase bindings
    request_file = SOLVER_REQUEST_DIR / f"{case_id}_request.json"
    solver_req = read_json(request_file, "solver request")

    gencase_receipt_path = require(Path(solver_req["gencase_receipt"]), "GenCase receipt")
    derived_xml_path = require(Path(solver_req["derived_solver_inputs"]["derived_xml"]), "derived XML")

    input_paths = [
        DIRECT_CONVERTER,
        BI4_DECODER,
        PARTVTK,
        RUNTIME_V2,
        STRICT_DISPATCH,
        Path(solver_receipt["path"]),
        Path(source_bindings["run_out"]["path"]),
        gencase_receipt_path,
        derived_xml_path,
    ]
    input_sha = {str(p): sha256(p) for p in input_paths}

    command = [
        str(PYTHON),
        str(DIRECT_CONVERTER),
        "--data-root",
        str(Path(source_bindings["solver_output_root"]) / "data"),
        "--generated-xml",
        str(derived_xml_path),
        "--output",
        str(output_root / "trajectory.h5"),
        "--report",
        str(output_root / "conversion-report.json"),
        "--solver-log",
        str(source_bindings["run_out"]["path"]),
        "--solver-receipt",
        str(solver_receipt["path"]),
        "--gencase-receipt",
        str(gencase_receipt_path),
        "--decoder",
        str(BI4_DECODER),
        "--partvtk",
        str(PARTVTK),
        "--validation-dir",
        str(output_root / "partvtk-validation"),
        "--keep-validation-csv",
    ]

    estimated_storage = math.ceil(case_info["metrics"]["total_particles"] * EXPECTED_FRAMES * 64 * 1.5)

    template = {
        "schema": CONVERSION_SCHEMA,
        "template_version": "ds-data-02.f2.spatial-reference-conversion-template.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "native_bi4_streaming_fullstate_conversion",
        "cpu_threads": 4,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": estimated_storage,
        "command": command,
        "cwd": str(INTEGRATION_LAB),
        "raw_output_root": str(output_root),
        "worktree_root": str(INTEGRATION_ROOT),
        "input_files": [str(p) for p in input_paths],
        "input_sha256": input_sha,
        "source_solver_run": {
            "attempt_id": case_info["attempt_id"],
            "receipt": solver_receipt,
            "bindings": source_bindings,
            "metrics": case_info["metrics"],
        },
        "expected_outputs": {
            "trajectory": str(output_root / "trajectory.h5"),
            "conversion_report": str(output_root / "conversion-report.json"),
            "receipt": str(output_root / "execution-receipt.json"),
        },
        "conversion_launch": {
            "allowed": False,
            "reason": "source-bound template only; trajectory conversion launch explicitly forbidden in this scope",
        },
        "root_only": True,
        "launch_allowed": False,
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "claim_boundary": {
            "q_i": "not_granted; conversion template only",
            "q_n": "not_assessed; save.01 remains insufficient for event temporal allocation 0.0001467278159987655s",
            "production": "not_evaluated",
        },
        "spatial_reference_preregistration": {
            "save_interval_s": SPATIAL_SAVE_S,
            "save_half_bracket_s": SPATIAL_HALF_BRACKET_S,
            "save_temporal_allocation_budget_s": SAVE_ALLOCATION_S,
            "bracket_exceeds_allocation_factor": SPATIAL_HALF_BRACKET_S / SAVE_ALLOCATION_S,
            "event_qn_grant_permitted": False,
            "macro_relative_budget": MACRO_RELATIVE_BUDGET,
            "continuum_mass_kg": CONTINUOUS_MASS_KG,
        },
    }

    dump(output_path, template)
    return template


def build_preregistration_manifest(inspections: list[dict[str, Any]], templates: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
    macro_comparisons = {}
    for insp in inspections:
        bg = insp["background"]
        res = insp["resolution"]
        fine = FINE_BASELINES[bg]
        rel_diff = abs(insp["metrics"]["retained_mass_kg"] - (fine["continuum_mass_kg"] - fine["native_unknown_mass_kg"])) / fine["continuum_mass_kg"]
        macro_comparisons[f"{bg}_{res}_vs_fine"] = {
            "background": bg,
            "resolution": res,
            "coarse_or_medium_case_id": insp["case_id"],
            "fine_reference_case_id": fine["case_id"],
            "continuum_fluid_mass_kg": CONTINUOUS_MASS_KG,
            "case_retained_mass_kg": insp["metrics"]["retained_mass_kg"],
            "fine_retained_mass_kg": fine["continuum_mass_kg"] - fine["native_unknown_mass_kg"],
            "relative_retained_mass_difference": rel_diff,
            "within_macro_budget_0p05": bool(rel_diff <= MACRO_RELATIVE_BUDGET),
            "case_excluded_particles": insp["metrics"]["excluded_particles"],
            "case_excluded_mass_fraction": insp["metrics"]["excluded_mass_fraction"],
            "fine_excluded_particles": fine["native_unknown_count"],
            "fine_excluded_mass_fraction": fine["native_unknown_mass_fraction"],
        }

    manifest = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "solver_runs_summary": {
            "total_runs": len(inspections),
            "all_runs_completed_code0": all(item["receipt"]["status"] == "completed" and item["receipt"]["returncode"] == 0 for item in inspections),
            "all_runs_401_frames": all(item["metrics"]["frames_saved"] == 401 for item in inspections),
            "all_runs_4s_window": all(item["metrics"]["window_seconds"] == 4.0 for item in inspections),
            "runs": [
                {
                    "case_id": item["case_id"],
                    "background": item["background"],
                    "resolution": item["resolution"],
                    "dp_m": item["dp_m"],
                    "elapsed_seconds": item["receipt"]["elapsed_seconds"],
                    "excluded_particles": item["metrics"]["excluded_particles"],
                    "receipt_sha256": item["receipt"]["sha256"],
                }
                for item in inspections
            ],
        },
        "exact_matching_physics": {
            "continuum_mass_kg": CONTINUOUS_MASS_KG,
            "center_physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
            "offset_physical_condition_hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
            "numerical_recipe_hash": "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7",
        },
        "macro_preregistration_vs_fine_dp005": macro_comparisons,
        "temporal_save_qualification_boundary": {
            "save_interval_s": SPATIAL_SAVE_S,
            "half_bracket_width_s": SPATIAL_HALF_BRACKET_S,
            "frozen_event_allocation_s": SAVE_ALLOCATION_S,
            "verdict": "Save.01 remains insufficient for event temporal allocation 0.0001467278159987655 (halfbar .005); never grant event Q-N from these spatial macros",
            "q_i_granted": False,
            "q_n_granted": False,
            "production_eligible": False,
        },
        "preserved_f3_provenance": F3_PRESERVED_BOUNDARIES,
        "conversion_templates": [
            {
                "case_id": t["case_id"],
                "template_path": str(CONVERSION_TEMPLATE_DIR / f"{t['case_id']}_conversion_template_v1.json"),
                "trajectory_conversion_launched": False,
            }
            for t in templates
        ],
    }

    dump(output_path, manifest)
    return manifest


def generate_all() -> dict[str, Any]:
    CONVERSION_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    inspections = [inspect_solver_run(case) for case in SPATIAL_CASES]
    templates = []
    for insp in inspections:
        out_path = CONVERSION_TEMPLATE_DIR / f"{insp['case_id']}_conversion_template_v1.json"
        t = build_conversion_template(insp, out_path)
        templates.append(t)

    manifest_path = HANDOFF_ROOT / "artifacts" / "rv4_matched_spatial_macro_preregistration_manifest_v1.json"
    manifest = build_preregistration_manifest(inspections, templates, manifest_path)
    return {"inspections": inspections, "templates": templates, "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Generate conversion templates and preregistration manifest")
    args = parser.parse_args()
    result = generate_all()
    print(f"Generated {len(result['templates'])} conversion templates and preregistration manifest successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
