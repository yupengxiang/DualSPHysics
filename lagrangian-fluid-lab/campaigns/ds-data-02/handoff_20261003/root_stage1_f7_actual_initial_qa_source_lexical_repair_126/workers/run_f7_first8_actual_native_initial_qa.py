#!/usr/bin/env python3
"""Per-case native initial QA worker derived from the fresh065 worker.

Root enables this worker only after the fresh066 actual GenCase binding is
reviewed.  It delegates the immutable lineage/type checks to the fresh065
worker, while replacing its CSV reader with an explicit PartVTK contract:
three summary rows, header at zero-based line 3, and ignored trailing empty
rows.  It reads BI4 only through the official PartVTK invocation when Root
runs the disabled request; this source package never launches it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SOURCE_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/"
    "root_followup_065_stage1_first8_target_angles_v1/workers/"
    "run_f7_first8_target_angle_native_initial_qa.py"
)


def sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_source_worker(path: Path):
    spec = importlib.util.spec_from_file_location("fresh065_native_qa_worker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import source QA worker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def robust_export_csv(module: Any, case: dict[str, Any], output: Path, partvtk: str):
    csv_path = output / f"{case['role']}-initial-all.csv"
    require(not csv_path.exists(), f"refusing to overwrite {csv_path}")
    before = module.sha(case["generated_bi4"])
    command = [
        partvtk,
        "-filedata", case["generated_bi4"],
        "-filexml", case["generated_xml"],
        "-threads:2",
        "-savecsv", str(csv_path),
        "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
        "-csvsep:1",
    ]
    subprocess.run(command, cwd=str(output), check=True)
    require(module.sha(case["generated_bi4"]) == before, f"{case['case_id']}: PartVTK mutated BI4")
    require(csv_path.is_file(), f"{case['case_id']}: PartVTK did not produce CSV")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header_index = next((index for index, row in enumerate(rows) if "Pos.x [m]" in row), None)
    require(header_index == 3, f"{case['case_id']}: official CSV header index {header_index} is not line 3 (zero-based)")
    summary = rows[:header_index]
    require(len(summary) == 3, f"{case['case_id']}: official CSV summary has {len(summary)} rows, expected 3")
    header = rows[header_index]
    indices = []
    for key in module.CSV_FIELDS:
        require(key in header, f"{case['case_id']}: official CSV field missing: {key}")
        indices.append(header.index(key))
    data = rows[header_index + 1:]
    trailing_empty_rows = 0
    while data and not any(field.strip() for field in data[-1]):
        data.pop()
        trailing_empty_rows += 1
    require(all(any(field.strip() for field in row) for row in data), f"{case['case_id']}: interior empty CSV row")
    expected_rows = int(case["expected"]["total_particles"])
    require(len(data) == expected_rows, f"{case['case_id']}: CSV data rows {len(data)} != {expected_rows}")
    selected = []
    for row_number, row in enumerate(data, start=header_index + 2):
        require(len(row) > max(indices), f"{case['case_id']}: CSV row {row_number} is too short")
        try:
            selected.append([float(row[index]) for index in indices])
        except ValueError as exc:
            raise RuntimeError(f"{case['case_id']}: CSV row {row_number} has nonnumeric selected fields") from exc
    values = np.asarray(selected, dtype=float)
    return values, {
        "official_csv": str(csv_path),
        "official_csv_sha256": module.sha(csv_path),
        "initial_bi4_sha256": before,
        "partvtk_command": command,
        "csv_summary_line_count": len(summary),
        "csv_header_line_zero_based": header_index,
        "csv_trailing_empty_rows_ignored": trailing_empty_rows,
        "csv_contract": "official PartVTK: 3 summary rows, header index 3, trailing empty rows ignored",
    }


def adapt_fresh066_binding(binding: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add the fresh065 worker's legacy flat fields without changing the binding."""
    plan_path = Path(binding["source_plan"]["source_absolute_path"])
    plan = load_json(plan_path)
    endpoints = {row["endpoint_id"]: row for row in plan["endpoints"]}
    adapted = dict(binding)
    adapted["partvtk"] = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
    adapted["partvtk_sha256"] = sha(adapted["partvtk"])
    adapted["forcing_source"] = {
        "source_plan": binding["source_plan"]["source_absolute_path"],
        "source_plan_sha256": binding["source_plan"]["source_sha256"],
        "motion_preparation_report": binding["root116_motion_report"]["source_absolute_path"],
        "motion_preparation_report_sha256": binding["root116_motion_report"]["source_sha256"],
        "motion_preparation_receipt": binding["root116_motion_receipt"]["source_absolute_path"],
        "motion_preparation_receipt_sha256": binding["root116_motion_receipt"]["source_sha256"],
        "motion_preparation_schema": "ds02.f7.target-angle-source-preparation.v1",
        "endpoint_metadata": {case["case_id"]: case["motion"]["root116_report_endpoint"] for case in binding["cases"]},
    }
    adapted["source_wet_obstacle_contract"] = {
        "required_definition_fragments": [
            'dp="0.02"', '<setmkbound mk="2" />', '<setmkfluid mk="1" />',
            "Explicit native cell-center slab 0", "Explicit native cell-center slab 1",
            "Explicit native cell-center slab 2", "Explicit native cell-center slab 3",
            '<boxfill>solid</boxfill>',
        ],
    }
    target_case_id = None
    for case in binding["cases"]:
        endpoint = endpoints[case["case_id"]]
        source_definition = (plan_path.parent / endpoint["source_definition_clone"]).resolve()
        case["source_definition"] = str(source_definition)
        case["source_definition_sha256"] = sha(source_definition)
        case["prepared_definition"] = case["motion"]["prepared_definition"]
        case["prepared_definition_sha256"] = case["motion"]["prepared_definition_sha256"]
        case["source_motion"] = case["motion"]["motion_file"]
        case["source_motion_sha256"] = case["motion"]["motion_file_sha256"]
        gencase = case["gencase"]
        case.update({
            "gencase_receipt": gencase["per_case_receipt"],
            "gencase_receipt_sha256": gencase["per_case_receipt_sha256"],
            "prepared_input_report": gencase["prepared_input_report"],
            "prepared_input_report_sha256": gencase["prepared_input_report_sha256"],
            "generated_xml": gencase["generated_xml"],
            "generated_xml_sha256": gencase["generated_xml_sha256"],
            "generated_bi4": gencase["generated_bi4"],
            "generated_bi4_sha256": gencase["generated_bi4_sha256"],
            "generated_definition": case["motion"]["prepared_definition"],
            "generated_definition_sha256": case["motion"]["prepared_definition_sha256"],
            "generated_motion": case["motion"]["motion_file"],
            "generated_motion_sha256": case["motion"]["motion_file_sha256"],
            "expected": {
                "total_particles": 70179,
                "fixed_particles": 27495,
                "moving_particles": 1984,
                "fluid_particles": 40700,
                "solver_dimension": 3,
                "dp_m": 0.02,
                "motion_rows": 12001,
                "type_mk_blocks": [
                    {"name": "fixed", "begin": 0, "count": 27495, "type": 0, "mk": 10},
                    {"name": "moving", "begin": 27495, "count": 1984, "type": 1, "mk": 12},
                    {"name": "fluid", "begin": 29479, "count": 40700, "type": 3, "mk": 2},
                ],
                "velocity_zero_tolerance_m_per_s": 1e-12,
                "native_fluid_mass_kg": 325.60001628,
                "continuum_envelope_mass_kg": 320.1984,
                "mass_tolerance_kg": 1e-8,
            },
        })
        if target_case_id is None:
            target_case_id = case["case_id"]
    target = next(case for case in adapted["cases"] if case["case_id"] == target_case_id)
    return adapted, target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-worker", default=str(DEFAULT_SOURCE_WORKER))
    args = parser.parse_args()
    binding_path = Path(args.binding).resolve()
    output = Path(args.output_dir).resolve()
    source_worker = Path(args.source_worker).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binding = load_json(binding_path)
    require(binding.get("schema") == "ds02.f7.first8.actual-gencase-native-source-binding.v1", "unexpected fresh066 binding schema")
    adapted_binding, _ = adapt_fresh066_binding(binding)
    cases = [case for case in adapted_binding.get("cases", []) if case.get("case_id") == args.case_id]
    require(len(cases) == 1, f"case not uniquely bound: {args.case_id}")
    case = cases[0]
    require(adapted_binding.get("launch_allowed") is False, "binding unexpectedly enabled")
    require(source_worker.is_file(), f"source QA worker missing: {source_worker}")
    source_sha = sha(source_worker)
    require(source_sha == binding["source_qa_worker"]["source_sha256"], "source QA worker hash changed")
    module = load_source_worker(source_worker)
    module.export_csv = lambda selected_case, selected_output, partvtk: robust_export_csv(module, selected_case, selected_output, partvtk)
    result = module.check_case(adapted_binding, case, output)
    result["source_qa_worker"] = {"source_absolute_path": str(source_worker), "source_sha256": source_sha}
    result["fresh066_binding"] = {"source_absolute_path": str(binding_path), "source_sha256": sha(binding_path)}
    report = {
        "schema": "ds02.f7.first8.actual-native-initial-qa-case.v1",
        "scope_id": binding["scope_id"],
        "case_id": args.case_id,
        "binding": str(binding_path),
        "binding_sha256": sha(binding_path),
        "cases": [result],
        "all_cases_passed": True,
        "independent_case_count_increment": 0,
        "q_n": "not_granted",
        "production_approval": "none",
        "precision_status": "not_accepted",
        "visual_acceptance": "not_assessed",
        "claim_boundary": "Per-case native source and initial typed QA only; no solver dynamics, full-window qualification, visual acceptance, or Q-N claim.",
    }
    destination = output / "native-initial-qa.json"
    require(not destination.exists(), f"refusing to overwrite {destination}")
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "case_id": args.case_id, "report": str(destination), "array_files_opened": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
