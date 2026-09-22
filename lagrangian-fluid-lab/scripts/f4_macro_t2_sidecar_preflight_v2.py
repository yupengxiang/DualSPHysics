"""F4 macro-T2 preflight with the versioned JSON acceptance validator wired in.

The v1 preflight remains immutable historical evidence.  This version reuses
its read-only CFD/cadence/matrix observations and additionally sends every
registered F4 case sidecar through
``evaluate_f4_tallwall120_diagnostic_json``.  Existing sidecars are expected
to fail closed because they are legacy summaries or right-censored diagnostics;
that failure is recorded, never converted into T2 credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.f4_macro_t2_sidecar_preflight_v1 import (
    build_preflight as build_v1_preflight,
    load_json,
    resolve_path,
    sha256_file,
)
from scripts.core_material_acceptance import evaluate_f4_tallwall120_diagnostic_json


SCHEMA = "core.material.f4.macro_t2_sidecar_preflight.v2"
CASE_BRIDGE = Path(
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922.json"
)
VALIDATOR = Path("scripts/core_material_acceptance.py")
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-v2-20260923.json"
)
DEFAULT_REPORT = Path("reports/F4-MACRO-T2-SIDECAR-PREFLIGHT-2026-09-23.md")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sidecar_payloads(payloads: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Run the F4 JSON validator once per registered payload, without I/O."""
    rows = []
    for index, payload in enumerate(payloads):
        result = evaluate_f4_tallwall120_diagnostic_json(payload)
        rows.append({
            "index": index,
            "input_schema": payload.get("schema") if isinstance(payload, dict) else None,
            "input_case_id": payload.get("case_id") if isinstance(payload, dict) else None,
            "validator_status": result["diagnostic_state"],
            "passed": result["passed"],
            "failure_reasons": list(result["failure_reasons"]),
            "blocking_reasons": list(result["blocking_reasons"]),
            "qualification_claim": result["qualification_claim"],
            "qualification_credit": result["qualification_credit"],
            "T2_macro": result["T2_macro"],
            "execution_constraints": result["execution_constraints"],
        })
    return {
        "validator_schema": "core.material.f4.tallwall120.diagnostic.v1",
        "validator_function": "evaluate_f4_tallwall120_diagnostic_json",
        "registered_case_count": len(rows),
        "validator_invocation_count": len(rows),
        "passed_case_count": sum(row["passed"] for row in rows),
        "blocked_case_count": sum(not row["passed"] for row in rows),
        "formal_acceptance_receipt_count": 0,
        "all_cases_pass": bool(rows) and all(row["passed"] for row in rows),
        "rows": rows,
        "qualification_claim": "none",
        "T2_macro": False,
        "T2_path": False,
    }


def _load_registered_payloads(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bridge_path = resolve_path(root, CASE_BRIDGE)
    bridge = load_json(bridge_path)
    bindings = bridge.get("case_input_bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("F4 case bridge has no registered case_input_bindings")
    payloads = []
    for key in sorted(bindings):
        binding = bindings[key]
        if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
            raise ValueError(f"F4 case binding {key} is malformed")
        payloads.append(load_json(resolve_path(root, Path(binding["path"]))))
    return bridge, payloads


def build_preflight(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    value = build_v1_preflight(root)
    bridge, payloads = _load_registered_payloads(root)
    json_acceptance = validate_sidecar_payloads(payloads)
    value["schema"] = SCHEMA
    value["json_acceptance"] = json_acceptance
    value["json_acceptance_input"] = {
        "path": str(CASE_BRIDGE),
        "sha256": sha256_file(resolve_path(root, CASE_BRIDGE)),
        "registered_case_count": len(payloads),
    }
    value["validator_binding"] = {
        "path": str(VALIDATOR),
        "sha256": sha256_file(resolve_path(root, VALIDATOR)),
        "function": "evaluate_f4_tallwall120_diagnostic_json",
        "json_source_only": True,
    }
    value["gate_evaluation"]["json_case_validator_invoked"] = json_acceptance["validator_invocation_count"] == 6
    value["gate_evaluation"]["json_case_acceptance_pass"] = json_acceptance["all_cases_pass"]
    value["gate_evaluation"]["formal_acceptance_receipt_count"] = json_acceptance["formal_acceptance_receipt_count"]
    value["blocking_reasons"].append(
        f"the wired F4 JSON validator processed {json_acceptance['registered_case_count']} registered case sidecars; "
        f"{json_acceptance['blocked_case_count']} are structurally or scientifically blocked and none has formal acceptance credit"
    )
    value["execution_constraints"]["json_validator_invocations"] = json_acceptance["validator_invocation_count"]
    value["execution_constraints"]["json_validator_mutation"] = 0
    value["interpretation_boundary"] = (
        "This v2 preflight explicitly invokes the F4 JSON validator for every registered case. "
        "Validator output is diagnostic/readiness evidence only; legacy sidecars, right-censored "
        "windows, missing tolerance fields, and absent formal receipts remain blocked."
    )
    return value


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    acceptance = value["json_acceptance"]
    lines = [
        "# F4 Macro-T2 Sidecar Preflight v2（2026-09-23）",
        "",
        "本版本保留 v1 历史回执，并把已有 F4 JSON validator 接入逐案例 preflight。没有打开 active H5、启动 solver/GPU/queue，或修改 registry、ledger、matrix 和科学分母。",
        "",
        f"当前结论：`T2_macro={str(value['T2_macro']).lower()}`、`T2_path={str(value['T2_path']).lower()}`、`qualification_claim={value['qualification_claim']}`。",
        "",
        "## Validator wiring",
        "",
        f"- validator：`{value['validator_binding']['path']}::{value['validator_binding']['function']}`",
        f"- registered case sidecars：`{acceptance['registered_case_count']}`",
        f"- validator invocations：`{acceptance['validator_invocation_count']}`",
        f"- blocked cases：`{acceptance['blocked_case_count']}`；passed cases：`{acceptance['passed_case_count']}`",
        f"- formal acceptance receipts：`{acceptance['formal_acceptance_receipt_count']}`",
        "",
        "逐案例调用已完成，但现有 sidecar 是旧版摘要或诊断数据，不能满足 `core.material.f4.tallwall120.diagnostic.v1` 的完整 identity/hash/event/tolerance contract；因此全部 fail-closed，不产生 T2 credit。",
        "",
        "## Scientific boundary",
        "",
        "unknown、right-censor、residence/事件容差、checkpoint/generation、33 行矩阵和正式 receipt 仍分别验收；source 可用或 preflight 通过不等于材料资格。",
        "",
        f"Evidence：`{evidence_path}`",
        "",
    ]
    return "\n".join(lines)


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output = output.resolve()
    report = report.resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite existing F4 v2 preflight artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=root)
    parser.add_argument("--output", type=Path, default=root / DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=root / DEFAULT_REPORT)
    args = parser.parse_args(argv)
    value = build_preflight(args.lab_root)
    write_artifacts(value, args.output, args.report)
    print(json.dumps({"schema": value["schema"], "status": value["status"], "blocked_cases": value["json_acceptance"]["blocked_case_count"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
