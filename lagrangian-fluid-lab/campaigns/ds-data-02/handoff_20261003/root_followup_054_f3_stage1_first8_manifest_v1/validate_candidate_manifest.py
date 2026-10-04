#!/usr/bin/env python3
"""Validate the F3 first8 candidate records without running any workload.

This checks source hashes and decision/report metadata only.  It deliberately
does not open raw particle arrays, launch a runner, create an approval index,
or turn a pending candidate into a production scope.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "F3_FIRST8_CANDIDATE_MANIFEST.template.json"
DOMAIN = HERE / "F3_FIRST8_PHYSICAL_DOMAIN.v1.json"
PROVENANCE = HERE / "F3_FIRST8_CASE_PROVENANCE.v1.json"
REQUIREMENTS = HERE / "ADAPTER_V2_REQUIREMENTS.json"

EXPECTED_AY = [0.25, 0.32, 0.39, 0.46, 0.50, 0.57, 0.64, 0.75]
EXPECTED_CASES = [
    "F3_STAGE1_DP006_P1000_AY0250",
    "F3_STAGE1_DP006_P1000_AY0320",
    "F3_STAGE1_DP006_P1000_AY0390",
    "F3_STAGE1_DP006_P1000_AY0460",
    "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005",
    "F3_STAGE1_DP006_P1000_AY0570",
    "F3_STAGE1_DP006_P1000_AY0640",
    "F3_STAGE1_DP006_P1000_AY0750",
]


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_bindings(value: Any, label: str) -> None:
    """Verify every concrete file binding nested in a document."""

    if isinstance(value, Mapping):
        path = value.get("path")
        expected = value.get("sha256")
        if isinstance(path, str) and isinstance(expected, str):
            target = Path(path)
            if not target.is_absolute():
                target = HERE / target
            require(target.is_file(), f"{label}: missing binding {target}")
            require(sha256(target) == expected, f"{label}: hash mismatch {target}")
        for key, child in value.items():
            verify_bindings(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            verify_bindings(child, f"{label}[{index}]")


def verify_endpoint_decision(binding: Mapping[str, Any], expected_case: str) -> None:
    path = Path(binding["path"])
    decision = read(path)
    require(decision["schema"] == "ds02.stage1.root-visual-case-decision.v1", f"{path}: schema")
    require(decision["status"] == "visual-approved-by-root", f"{path}: status")
    require(decision["family_id"] == "F3", f"{path}: family")
    require(decision["case_id"] == expected_case, f"{path}: case identity")
    require(decision["stage1_label"] == "视觉检查通过、数值精度未验收", f"{path}: label")
    require(decision["production_scope_approval"] is False, f"{path}: production flag")
    require(decision["q_n"] in {"not_granted", "not_assessed"}, f"{path}: Q-N")
    require(decision["q_e"] in {"not_granted", "not_assessed"}, f"{path}: Q-E")
    require(decision["physical_window_s"] == [0, 8.35], f"{path}: physical window")


def verify_integrity(binding: Mapping[str, Any]) -> None:
    path = Path(binding["path"])
    report = read(path)
    require(report["all_frames_rendered"] is True, f"{path}: all_frames_rendered")
    require(report["actual_times_preserved_exactly"] is True, f"{path}: actual times")
    require(report["diagnostic_only"] is False, f"{path}: diagnostic_only")
    require(len(report.get("frame_diagnostics", [])) == 836, f"{path}: frame count")
    require(
        all(row.get("missing", 0) == 0 for row in report["frame_diagnostics"]),
        f"{path}: missing frame state",
    )


def verify_prepared_report(row: Mapping[str, Any]) -> None:
    prepared = row.get("prepared_input")
    if not isinstance(prepared, Mapping) or not isinstance(prepared.get("report"), Mapping):
        return
    report_path = Path(prepared["report"]["path"])
    report = read(report_path)
    require(report["case_id"] == row["case_id"], f"{report_path}: case identity")
    require(report["physical_case_id"] == row["physical_case_id"], f"{report_path}: physical identity")
    require(report["physical_condition_sha256"] == row["physical_condition_sha256"], f"{report_path}: condition")
    require(report["transverse_amplitude_m_s2"] == row["transverse_amplitude_m_s2"], f"{report_path}: AY")
    require(report["forcing_sha256"] == prepared["forcing"]["sha256"], f"{report_path}: forcing")
    require(report["xml_sha256"] == prepared["generated_xml"]["sha256"], f"{report_path}: XML")
    require(report["bi4_sha256"] == prepared["initial_bi4"]["sha256"], f"{report_path}: BI4")
    require(report["production_approval"] == "none", f"{report_path}: approval")
    require(report["independent_case_increment"] == 0, f"{report_path}: count increment")


def main() -> int:
    candidate = read(CANDIDATE)
    domain = read(DOMAIN)
    provenance = read(PROVENANCE)
    requirements = read(REQUIREMENTS)

    require(candidate["schema"] == "ds02.f3.stage1-first8-candidate-manifest.v1", "candidate schema")
    require(candidate["status"] == "pending_root_aggregate_domain_decision", "candidate pending status")
    require(candidate["execution_allowed"] is False, "candidate must not launch")
    require(candidate["production_scope_approval"] is False, "candidate production flag")
    require(candidate["q_n"] == "not_granted", "candidate Q-N")
    require(candidate["root_visual_domain_decision"]["path"] is None, "aggregate decision must remain pending")
    require(candidate["root_visual_domain_decision"]["schema_expected"] == "ds02.stage1.root-visual-domain-decision.v1", "aggregate schema")
    require(candidate["domain_design"]["transverse_amplitude_m_s2"] == EXPECTED_AY, "candidate AY axis")

    require(domain["schema"] == "ds02.f3.stage1-first8-physical-domain.v1", "domain schema")
    require(domain["status"] == "pending_root_visual_scope_decision", "domain status")
    require(domain["physical_axis"]["transverse_amplitude_m_s2"] == EXPECTED_AY, "domain AY axis")
    require([row["case_id"] for row in domain["cases"]] == EXPECTED_CASES, "domain case order")
    require(domain["production_scope_approval"] is False, "domain production flag")

    require(provenance["schema"] == "ds02.f3.stage1-first8-case-provenance.v1", "provenance schema")
    require(provenance["status"] == "candidate_pending_full_scope_visual_decision", "provenance status")
    require([row["case_id"] for row in provenance["cases"]] == EXPECTED_CASES, "provenance case order")
    require(provenance["cases"][4]["physical_case_id"] == "F3_TWOAXIS_AY0P50_PITCH_NOMINAL", "mother identity")
    require(
        all(
            row["physical_case_id"] != "F3_TWOAXIS_PITCH1000_AY0500_STAGE1_BATCH8"
            for row in provenance["cases"]
        ),
        "mother recast",
    )
    require(provenance["pending_scope_evidence"]["root_visual_decision_for_full_scope"] is None, "scope decision")
    require(provenance["pending_scope_evidence"]["final_visualization_decision"] is None, "final decision")
    for row in provenance["cases"]:
        verify_prepared_report(row)

    require(requirements["launch_allowed"] is False, "requirements launch flag")
    require(requirements["production_scope_approval"] is False, "requirements production flag")
    require(requirements["current_goal"]["sha256"] == candidate["goal_authority"]["sha256"], "goal binding")

    verify_bindings(candidate, "candidate")
    verify_bindings(domain, "domain")
    verify_bindings(provenance, "provenance")
    verify_bindings(requirements, "requirements")

    endpoint_rows = candidate["visual_evidence"]["endpoints"]
    verify_endpoint_decision(endpoint_rows[0]["decision"], "F3_STAGE1_DP006_P1000_AY0250")
    verify_endpoint_decision(endpoint_rows[1]["decision"], "F3_STAGE1_DP006_P1000_AY0750")
    verify_integrity(endpoint_rows[0]["full_saved_frames"]["integrity_report"])
    verify_integrity(endpoint_rows[1]["full_saved_frames"]["integrity_report"])

    print("candidate manifest: pending, source hashes and endpoint evidence verified")
    print("execution/jobs/approval: disabled")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
