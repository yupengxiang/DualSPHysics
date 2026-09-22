"""Version the F3 T2 gap audit after the native-MLS bridge landed.

The v1 audit is immutable historical evidence and intentionally continues to
describe the pre-bridge gap.  This v2 wrapper reuses its read-only scientific
observations, binds the new JSON-only acceptance adapter, and changes only the
software-surface interpretation.  It does not rerun HDF5, solver, GPU, queue,
registry, ledger, or matrix work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.f3_t2_admission_acceptance_gap_audit_v1 import (
    build_audit as build_v1_audit,
    bind_file,
    resolve_path,
)


SCHEMA = "core.material.f3.t2.admission_acceptance_gap_audit.v2"
ADAPTER = Path("scripts/f3_native_mls_acceptance_adapter_v1.py")
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-t2-admission-acceptance-gap-audit-v3-20260923.json"
)
DEFAULT_REPORT = Path("reports/F3-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-23.zh-CN.md")


def _contains(text: str, needle: str) -> bool:
    return needle in text


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_audit(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    value = build_v1_audit(root)
    adapter_path = resolve_path(root, ADAPTER)
    adapter_text = adapter_path.read_text(encoding="utf-8")
    value["schema"] = SCHEMA
    value["input_bindings"]["native_mls_acceptance_adapter"] = bind_file(root, ADAPTER)

    value["code_contracts"]["native_mls_acceptance_adapter"] = {
        "module_schema": _contains(adapter_text, 'SCHEMA = "core.material.f3.native_mls_acceptance_adapter.v1"'),
        "native_trace_schema": _contains(adapter_text, "TRACE_SCHEMA_PREFIX"),
        "native_checkpoint_schema": _contains(adapter_text, "CHECKPOINT_SCHEMA_PREFIX"),
        "native_cadence_gate": _contains(adapter_text, "NATIVE_INTERVAL_S"),
        "full_window_gate": _contains(adapter_text, "FULL_WINDOW_S"),
        "per_source_unknown_gate": _contains(adapter_text, "UNKNOWN_LIMIT"),
        "three_event_cdf_gate": all(_contains(adapter_text, name) for name in ("first_passage", "return", "residence")),
        "right_censored_zero_credit": _contains(adapter_text, "right_censored_counts_as_acceptance"),
        "full_matrix_denominator": _contains(adapter_text, "MATRIX_ROW_COUNT = 33"),
        "qualification_claim_none": _contains(adapter_text, '"qualification_claim": "none"'),
        "execution_mutations_zero": all(_contains(adapter_text, name) for name in ("registry_mutation", "ledger_mutation", "matrix_mutation")),
    }
    value["acceptance_gates"]["native_mls_acceptance_bridge_present"] = all(
        value["code_contracts"]["native_mls_acceptance_adapter"].values()
    )
    value["blocking_reasons"] = [
        reason for reason in value["blocking_reasons"]
        if "core_material_acceptance does not admit the native-MLS" not in reason
    ]
    value["blocking_reasons"].append(
        "the new native-MLS bridge is present, but it is an admission/readiness surface only; "
        "current scientific unknown/CDF gates, right-censored canary, missing exact source rows, "
        "and zero formal row receipts still block macro T2"
    )
    value["minimal_next_executable_repair"] = {
        **value["minimal_next_executable_repair"],
        "status": "bridge_present_pending_exact_source_and_collection_wiring",
        "action": "feed exact native-MLS comparison/checkpoint/source-window receipts through the versioned bridge; do not promote diagnostics",
        "adapter_binding": value["input_bindings"]["native_mls_acceptance_adapter"],
        "qualification_effect": "none; bridge output remains diagnostic until independent 33-row collection acceptance",
    }
    value["version_transition"] = {
        "previous_schema": "core.material.f3.t2.admission_acceptance_gap_audit.v1",
        "previous_evidence_preserved": True,
        "new_adapter_path": str(ADAPTER),
        "new_adapter_sha256": _sha256(adapter_path),
        "scientific_denominator_changed": False,
        "thresholds_changed": False,
    }
    return value


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    gates = value["acceptance_gates"]
    source = value["observed_gate_comparison"]["source_window"]
    matrix = value["matrix"]
    adapter = value["code_contracts"]["native_mls_acceptance_adapter"]
    return "\n".join([
        "# F3 宏观 T2 admission/acceptance gap audit v2（2026-09-23）",
        "",
        "本版本保留 v1 历史审计，不覆盖旧 receipt；仅把新提交的 native-MLS JSON acceptance bridge 纳入静态软件闭环。没有打开 HDF5、启动 solver/GPU/queue，也没有修改 registry、ledger、matrix 或科学分母。",
        "",
        f"当前结论：`T2_macro={str(value['T2_macro']).lower()}`、`T2_path={str(value['T2_path']).lower()}`、`qualification_credit={value['qualification_credit']}`。",
        "",
        "## 新增 bridge",
        "",
        f"- adapter：`{value['input_bindings']['native_mls_acceptance_adapter']['path']}`",
        f"- SHA-256：`{value['input_bindings']['native_mls_acceptance_adapter']['sha256']}`",
        f"- 静态 contract closure：`{str(all(adapter.values())).lower()}`",
        "- bridge 只消费 JSON evidence；仍保持 `qualification_claim=none` 和 zero credit。",
        "",
        "## 仍未通过的科学门",
        "",
        f"- source unknown 最大值：`{source['unknown_mass']['maximum_observed']}`；固定门为 `0.01`。",
        f"- CDF 最大差异：`{source['cdf']['maximum_observed']}`；固定门为 `0.02`。",
        f"- 33 行矩阵：`{matrix['registered_row_count']}` 行，formal acceptance receipts=`{matrix['formal_acceptance_receipt_count']}`。",
        f"- bridge presence gate：`{str(gates['native_mls_acceptance_bridge_present']).lower()}`；它不替代 exact source 与逐行 acceptance。",
        "",
        "## 边界",
        "",
        "这一步完成的是 acceptance 入口的代码闭环，不是 T2 资格。right-censored canary、超限 unknown/CDF、缺失 exact CFD source 和未完成 33-row receipt 仍必须保留在分母中。",
        "",
    ])


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output = output.resolve()
    report = report.resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite existing v2 gap-audit artifact")
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
    value = build_audit(args.lab_root)
    write_artifacts(value, args.output, args.report)
    print(json.dumps({"schema": value["schema"], "status": value["status"], "output": str(args.output.resolve()), "report": str(args.report.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
