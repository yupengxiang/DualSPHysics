#!/usr/bin/env python3
"""Reconcile the F4 gap audit with the implemented JSON-validator route.

The v1-v3 audit receipts are immutable historical snapshots.  This version
binds the current v2 sidecar preflight and reports implementation presence
separately from scientific admission: the validator is wired, but the six
retained sidecars fail closed and F4 still lacks authoritative CDF/residence
tolerances and a complete material matrix.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f4_tallwall120_t2_admission_acceptance_gap_audit_v3 as _previous
from scripts.f4_macro_t2_sidecar_preflight_v2 import build_preflight


SCHEMA = "core.material.f4.tallwall120.t2_admission_acceptance_gap_audit.v4"
DEFAULT_OUTPUT_NAME = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v5.json"
)
DEFAULT_REPORT_NAME = Path(
    "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-23-v5.zh-CN.md"
)
PREFLIGHT_CODE = Path("scripts/f4_macro_t2_sidecar_preflight_v2.py")
PREFLIGHT_EVIDENCE = Path(
    "campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-v2-20260923.json"
)


def _bind(path: Path, root: Path) -> dict[str, Any]:
    path = path.resolve()
    try:
        display = str(path.relative_to(root))
    except ValueError:
        display = str(path)
    return {
        "path": display,
        "absolute_path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _refresh_bindings(audit: dict[str, Any], root: Path) -> None:
    bindings = audit["input_bindings"]
    for name, binding in list(bindings.items()):
        path = Path(binding.get("absolute_path") or binding["path"])
        if not path.is_absolute():
            path = root / path
        bindings[name] = _bind(path, root)

    # Preserve the old source/output explicitly as history, then bind the
    # current validator route and this audit implementation as separate input.
    old_code = bindings.get("macro_sidecar_preflight_code")
    if old_code is not None:
        bindings["macro_sidecar_preflight_v1_code"] = old_code
    old_evidence = bindings.get("macro_sidecar_preflight")
    if old_evidence is not None:
        bindings["macro_sidecar_preflight_v1_evidence"] = old_evidence
    bindings["macro_sidecar_preflight_code"] = _bind(root / PREFLIGHT_CODE, root)
    bindings["macro_sidecar_preflight"] = _bind(root / PREFLIGHT_EVIDENCE, root)
    bindings["gap_audit_implementation"] = _bind(Path(__file__), root)


def build_audit(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    value = _previous.build_audit(root)
    sidecar = build_preflight(root)
    acceptance_source = (root / "scripts/core_material_acceptance.py").read_text(encoding="utf-8")
    material_source = (root / "scripts/f4_tallwall120_material.py").read_text(encoding="utf-8")

    json_acceptance = sidecar["json_acceptance"]
    implementation = {
        "diagnostic_schema": "core.material.f4.tallwall120.diagnostic.v1",
        "diagnostic_validator_present": "evaluate_f4_tallwall120_diagnostic_json" in acceptance_source,
        "per_source_unknown_evaluator_present": "_f4_tallwall120_source_denominator" in acceptance_source,
        "residence_fields_and_censor_validator_present": (
            "residence_censored_fraction" in acceptance_source
            and "right_censor_free" in acceptance_source
        ),
        "f4_cdf_and_residence_comparators_present": (
            "f4_cdf_tolerance" in acceptance_source
            and "f4_residence_tolerance" in acceptance_source
        ),
        "endpoint_and_saved_chord_comparators_present": (
            "f4_endpoint_tolerance" in acceptance_source
            and "f4_saved_chord_tolerance" in acceptance_source
        ),
        "content_addressed_generation_present_in_tracer": "content-addressed" in material_source,
        "sidecar_preflight_calls_validator": (
            sidecar["json_acceptance"]["validator_function"]
            == "evaluate_f4_tallwall120_diagnostic_json"
        ),
        "registered_sidecar_count": json_acceptance["registered_case_count"],
        "validator_invocation_count": json_acceptance["validator_invocation_count"],
        "validator_passed_case_count": json_acceptance["passed_case_count"],
        "validator_blocked_case_count": json_acceptance["blocked_case_count"],
        "formal_acceptance_receipt_count": json_acceptance["formal_acceptance_receipt_count"],
        "authoritative_f4_cdf_tolerance_registered": False,
        "authoritative_f4_residence_tolerance_registered": False,
        "qualification_credit": 0,
    }

    old_contracts = value["code_contracts"]
    old_contracts["core_material_acceptance"].update({
        "tallwall_diagnostic_schema": implementation["diagnostic_validator_present"],
        "residence_fields_and_censor_validator": implementation["residence_fields_and_censor_validator_present"],
        "f4_tolerance_comparators": (
            implementation["f4_cdf_and_residence_comparators_present"]
            and implementation["endpoint_and_saved_chord_comparators_present"]
        ),
        "authoritative_f4_cdf_tolerance_registered": False,
        "authoritative_f4_residence_tolerance_registered": False,
    })
    old_contracts["macro_sidecar_preflight"].update({
        "acceptance_adapter_called": implementation["sidecar_preflight_calls_validator"],
        "per_case_acceptance_route": json_acceptance["validator_invocation_count"] == 6,
        "all_registered_cases_accepted": json_acceptance["all_cases_pass"],
        "formal_acceptance_receipt_count": json_acceptance["formal_acceptance_receipt_count"],
    })
    value["acceptance_implementation"] = implementation
    value["sidecar_preflight_v2"] = {
        "schema": sidecar["schema"],
        "status": sidecar["status"],
        "registered_case_count": json_acceptance["registered_case_count"],
        "validator_invocation_count": json_acceptance["validator_invocation_count"],
        "passed_case_count": json_acceptance["passed_case_count"],
        "blocked_case_count": json_acceptance["blocked_case_count"],
        "formal_acceptance_receipt_count": json_acceptance["formal_acceptance_receipt_count"],
        "all_cases_pass": json_acceptance["all_cases_pass"],
    }

    gates = value["acceptance_gates"]
    gates["tallwall_diagnostic_validator_present"] = implementation["diagnostic_validator_present"]
    gates["sidecar_preflight_bridges_acceptance"] = implementation["sidecar_preflight_calls_validator"]
    gates["per_case_sidecar_acceptance"] = (
        json_acceptance["all_cases_pass"]
        and json_acceptance["formal_acceptance_receipt_count"] == json_acceptance["registered_case_count"]
    )
    # A payload-level comparator is not an authoritative scientific tolerance
    # registration.  Keep these gates false until the family contract provides
    # frozen numerical limits and retained results satisfy them.
    gates["f4_cdf_tolerance_registered"] = False
    gates["residence_tolerance_acceptance"] = False
    gates["event_tolerance_acceptance"] = False
    gates["tallwall_schema_accepted"] = False
    value["admission_surface_pass"] = all(gates.values())

    reasons = [
        f"all six retained F4 cases fail the fixed per-source unknown-mass gate: maximum {value['observed_gate_comparison']['unknown_mass']['maximum_observed']} > 0.01",
        "all six retained F4 cases are right-censored or unresolved before the required event window completes",
        "the migration contract still has no authoritative F4 numerical CDF tolerance; the diagnostic comparator only checks a supplied tolerance field",
        "the migration contract provides gravity time but no authoritative residence-distribution tolerance",
        f"the v2 sidecar preflight invoked the validator for {json_acceptance['registered_case_count']} cases; {json_acceptance['blocked_case_count']} are blocked and {json_acceptance['formal_acceptance_receipt_count']} formal receipts exist",
        "the registered overlay is not ready: 33 rows span 15 CFD cells, with resolution/substep and seed-density material overlays pending",
        "the ESS32 full-source candidate remains proposal-only because its candidate-specific root review has authorized_one_cpu_only=false; this does not override the separate user authorization for the supportcap preflight",
        "the diagnostic validator is not a T2 qualification collector: it does not close the full material matrix, authoritative tolerance registry, recovery receipt, or formal per-case receipts",
    ]
    value["blocking_reasons"] = reasons
    value["current_qualification_state"].update({
        "diagnostic_validator_invocations": json_acceptance["validator_invocation_count"],
        "diagnostic_validator_blocked_cases": json_acceptance["blocked_case_count"],
        "formal_acceptance_receipt_count": json_acceptance["formal_acceptance_receipt_count"],
        "overall_T2_credit": 0,
        "core_gate_changed": False,
    })
    value["execution_constraints"].update({
        "diagnostic_validator_invocations": json_acceptance["validator_invocation_count"],
        "diagnostic_validator_mutation": 0,
        "solver_started": False,
        "gpu_started": False,
        "new_job_submitted": False,
        "old_evidence_overwritten": False,
    })
    value["schema"] = SCHEMA
    value["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    value["interpretation_boundary"] = (
        "The implemented F4 JSON validator and per-case preflight route are present. "
        "Their current inputs are legacy/incomplete diagnostics and all six fail closed. "
        "Comparator presence is not authoritative threshold registration, acceptance, or T2 credit."
    )
    _refresh_bindings(value, root)
    return value


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    impl = value["acceptance_implementation"]
    sidecar = value["sidecar_preflight_v2"]
    matrix = value["matrix"]
    lines = [
        "# F4 tallwall120 T2 admission/acceptance gap audit v5（2026-09-23）",
        "",
        "结论：acceptance validator 和逐例 sidecar wiring 已实现；这纠正了旧 v4 gap audit 的过时接口判断。科学资格仍为 `T2_macro=false`、`T2_path=false`、zero credit。",
        "",
        f"Evidence：`{evidence_path}`",
        "",
        "## 当前 acceptance 路径",
        "",
        f"- JSON validator：`{impl['diagnostic_schema']}`；validator invocation `{sidecar['validator_invocation_count']}/{sidecar['registered_case_count']}`。",
        f"- 当前 sidecar：通过 `{sidecar['passed_case_count']}`，fail-closed `{sidecar['blocked_case_count']}`；formal receipt `{sidecar['formal_acceptance_receipt_count']}`。",
        f"- residence/censor 结构验证：`{str(impl['residence_fields_and_censor_validator_present']).lower()}`；F4 tolerance comparators：`{str(impl['f4_cdf_and_residence_comparators_present'] and impl['endpoint_and_saved_chord_comparators_present']).lower()}`。",
        "- 重要区分：validator 可检查 payload 提供的 comparator 字段，但 migration spec 未注册权威 F4 CDF 或 residence 数值容差；这不构成科学 gate 通过。",
        "",
        "## 仍未通过的科学门",
        "",
        f"- 每 source unknown mass 最大值 `{value['observed_gate_comparison']['unknown_mass']['maximum_observed']}`，上限 `0.01`。",
        f"- 完整事件窗：`{value['observed_gate_comparison']['event_window']['all_cases_complete']}`；6 个保留案例仍 right-censored/unresolved。",
        f"- 33-row overlay 覆盖 `{matrix['existing_f4_cfd_cell_count']}` 个 CFD cells；material matrix ready=`{str(matrix['material_matrix_ready']).lower()}`。",
        f"- content-addressed tracer generation 实现存在=`{str(impl['content_addressed_generation_present_in_tracer']).lower()}`；但 recovery acceptance/执行授权仍未闭合。",
        "",
        "## 阻塞项",
        "",
    ]
    lines.extend(f"{index}. {reason}" for index, reason in enumerate(value["blocking_reasons"], 1))
    lines.extend([
        "",
        "本审计仅读取 JSON、源码和报告；未打开 H5/NPZ，未启动 solver/GPU/worker，未变更队列、账本、矩阵、科学分母、阈值或旧证据。",
        "",
        "## 输入 SHA-256",
        "",
    ])
    lines.extend(f"- `{name}`：`{binding['path']}` — `{binding['sha256']}`" for name, binding in value["input_bindings"].items())
    return "\n".join(lines) + "\n"


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output, report = Path(output).resolve(), Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite existing current F4 audit artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=root)
    parser.add_argument("--output", type=Path, default=root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=root / DEFAULT_REPORT_NAME)
    args = parser.parse_args(argv)
    value = build_audit(args.lab_root)
    write_artifacts(value, args.output, args.report)
    print(json.dumps({"schema": value["schema"], "admission_surface_pass": value["admission_surface_pass"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
