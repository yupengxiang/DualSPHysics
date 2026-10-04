#!/usr/bin/env python3
"""Validate the v2 F3 input recipe without launching any workload."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
RECIPE = HERE / "F3_INTERIOR012_PRODUCTION_REQUEST_RECIPE.v1.json"
ENTRY_TEMPLATE = HERE / "F3_FIRST8_V2_SCOPE_ENTRY.template.json"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def binding(value: Mapping[str, Any], label: str) -> Path:
    path = Path(str(value["path"]))
    if not path.is_absolute():
        path = (HERE / path).resolve()
    require(path.is_file(), f"{label}: missing {path}")
    require(sha256(path) == value["sha256"], f"{label}: hash mismatch {path}")
    return path


def main() -> int:
    recipe = read(RECIPE)
    entry = read(ENTRY_TEMPLATE)
    require(recipe["schema"] == "ds02.stage1.production-authorizer-v2-recipe.v1", "recipe schema")
    require(recipe["status"] == "input_recipe_only", "recipe status")
    require(recipe["launch_allowed"] is False, "recipe must not launch")
    require(recipe["production_scope_approval"] is False, "recipe production flag")
    require(recipe["q_n"] == "not_granted" and recipe["q_e"] == "not_assessed", "recipe Q-N/Q-E")
    require(entry["status"] == "pending_root_adapter_index_review", "entry template status")
    require(entry["execution_allowed"] is False, "entry template must not launch")
    require(entry["production_scope_approval"] is False, "entry template production flag")
    require(entry["selected_case_ids"] == recipe["frozen_membership"]["prospective_case_ids"], "entry selected IDs")

    goal = binding(recipe["goal_authority"], "current GOAL")
    domain_decision_path = binding(recipe["root_visual_domain_decision"], "root domain decision")
    decision = read(domain_decision_path)
    require(decision["schema"] == "ds02.stage1.root-visual-domain-decision.v1", "domain decision schema")
    require(decision["status"] == "visual-domain-approved-by-root", "domain decision status")
    require(decision["goal_authority"]["path"] == str(goal), "domain decision GOAL path")
    require(decision["goal_authority"]["sha256"] == recipe["goal_authority"]["sha256"], "domain decision GOAL hash")
    require(decision["production_scope_approval"] is False, "domain decision production flag")
    require(decision["q_n"] == "not_granted" and decision["q_e"] == "not_assessed", "domain decision Q-N/Q-E")
    require(decision["prospective_execution_authorized"] is True, "domain prospective permission")
    require(decision["prospective_case_visual_acceptance"] is False, "prospective visual acceptance was inferred")

    physical_path = binding(recipe["source_manifest"]["physical_domain"], "054 physical domain")
    provenance_path = binding(recipe["source_manifest"]["case_provenance"], "054 case provenance")
    physical_doc = read(physical_path)
    provenance_doc = read(provenance_path)
    expected_ids = recipe["frozen_membership"]["prospective_case_ids"]
    rows = {row["case_id"]: row for row in provenance_doc["cases"]}
    require(len(expected_ids) == 5, "five prospective cases")
    require(recipe["frozen_membership"]["transverse_amplitude_m_s2"] == [0.25, 0.32, 0.39, 0.46, 0.5, 0.57, 0.64, 0.75], "SI AY axis")
    require(recipe["frozen_membership"]["no_interpolation_or_extrapolation"] is True, "membership rule")
    require(recipe["frozen_membership"]["nominal_pitch_multiplier"] == 1.0, "pitch")
    require(recipe["frozen_membership"]["time_window_s"] == [0.0, 8.35], "event window")
    require(recipe["frozen_membership"]["expected_saved_frames"] == 836, "frame count")
    require(physical_doc["physical_axis"]["transverse_amplitude_m_s2"] == recipe["frozen_membership"]["transverse_amplitude_m_s2"], "physical axis")
    require(rows["F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005"]["physical_case_id"] == "F3_TWOAXIS_AY0P50_PITCH_NOMINAL", "mother identity")

    for item in recipe["prospective_cases"]:
        row = rows[item["case_id"]]
        require(item["qa_semantics"] == "exact_initial_clone_of_genuine_3d_parent", f"{item['case_id']}: QA branch")
        require(item["independent_case_count_increment"] == 0, f"{item['case_id']}: count")
        require(item["visual_decision"] is None, f"{item['case_id']}: future visual decision")
        prepared = item["prepared_input"]
        report_path = binding(prepared["report"], f"{item['case_id']} prepared report")
        report = read(report_path)
        require(report["case_id"] == item["case_id"], f"{item['case_id']}: report case")
        require(report["physical_case_id"] == item["physical_case_id"], f"{item['case_id']}: report physical identity")
        require(report["physical_condition_sha256"] == item["physical_condition_sha256"], f"{item['case_id']}: condition")
        require(report["xml_byte_identical_to_baseline"] is True, f"{item['case_id']}: XML clone")
        require(report["initial_bi4_byte_identical_to_baseline"] is True, f"{item['case_id']}: BI4 clone")
        require(report["production_approval"] == "none", f"{item['case_id']}: production flag")
        require(report["independent_case_increment"] == 0, f"{item['case_id']}: report count")
        require(report["physical_window_s"] == [0, 8.35], f"{item['case_id']}: report window")
        require(report["expected_frames"] == 836, f"{item['case_id']}: report frames")
        for label in ("forcing", "generated_xml", "initial_bi4"):
            binding(prepared[label], f"{item['case_id']} {label}")
        require(prepared["generated_xml"]["sha256"] == provenance_doc["shared_initial_state"]["initial_xml_sha256"], f"{item['case_id']}: parent XML identity")
        require(prepared["initial_bi4"]["sha256"] == provenance_doc["shared_initial_state"]["initial_bi4_sha256"], f"{item['case_id']}: parent BI4 identity")

    print("F3 v2 recipe: current Root domain, five exact prospective IDs, and source hashes verified")
    print("execution/jobs/approval: disabled")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
