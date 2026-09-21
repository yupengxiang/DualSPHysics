#!/usr/bin/env python3
"""Audit the F2 v4 CPU/native preflight from the material/T2 boundary.

This is a read-only review.  It consumes the already materialized exact-one
CPU/native preflight and its static authorization records, but never opens the
BI4 payload, starts an executable, changes the parent matrix, or writes a
ledger/registry record.  The review makes the T2 boundary explicit: an F2
CPU/native integrity preflight, including a hard failure or a hypothetical
hard pass, cannot establish material T2 credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
REMEDIATION = BASE / "normal-remediation-v4"
ROOT_RECEIPT = REMEDIATION / "root-review-receipt-v4.json"
STATIC_CONTRACT = REMEDIATION / "root-review-only-contract-v4.json"
CANDIDATE = REMEDIATION / "normal-remediation-candidate-v4.json"
FAILURE_EVIDENCE = REMEDIATION / "v3-failure-evidence-v4.json"
PREFLIGHT_CONTRACT = REMEDIATION / "preflight-contract-v4.json"
PREFLIGHT = REMEDIATION / "preflight-v4/preflight.json"
DEFINITION = REMEDIATION / "fresh-definition-v4/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4_Def.xml"
PARENT_MATRIX = BASE / "fixed-matrix-v1.json"
PARENT_DENOMINATOR = BASE / "failure-denominator-v1.json"
PARENT_LINEAGE = BASE / "lineage-clarification-v1.json"
PARENT_ROOT = BASE / "root-review-contract-v1.json"
ROOT_REVIEW_SCRIPT = LAB / "scripts/f2_submerged_orifice_root_review_v4.py"
ROOT_REVIEW_TEST = LAB / "tests/test_f2_submerged_orifice_root_review_v4.py"
PREFLIGHT_SCRIPT = LAB / "scripts/f2_submerged_orifice_preflight_v4.py"
PREFLIGHT_TEST = LAB / "tests/test_f2_submerged_orifice_preflight_v4.py"
OUTPUT = LAB / "campaigns/core-v1/material/evidence/f2-submerged-orifice-v4-t2-material-review-20260921.json"
REPORT = LAB / "reports/F2-SUBMERGED-ORIFICE-V4-T2-MATERIAL-REVIEW-2026-09-21.zh-CN.md"

CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
PARENT_SCOPE = "F2_submerged_orifice_transfer_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(item: Mapping[str, Any], label: str, expected: Path | None = None) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: missing path")
    path = Path(value).resolve()
    if expected is not None and path != Path(expected).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: stale hash/bytes")
    return path


def _assert_zero_permission(value: Mapping[str, Any], label: str) -> None:
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if value.get(key) is not False:
            raise ValueError(f"{label} opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if value.get(key) != 0:
            raise ValueError(f"{label} opened {key}")


def _assert_parent_scope() -> dict[str, Any]:
    matrix = load(PARENT_MATRIX)
    denominator = load(PARENT_DENOMINATOR)
    lineage = load(PARENT_LINEAGE)
    if matrix.get("scope_id") != PARENT_SCOPE or matrix.get("cell_count") != 15:
        raise ValueError("parent matrix scope/count changed")
    rows = matrix.get("rows")
    if not isinstance(rows, list) or len(rows) != 15:
        raise ValueError("parent matrix row count changed")
    if {row.get("index") for row in rows} != set(range(15)):
        raise ValueError("parent matrix indices are not 0..14")
    if any(row.get("status") != "not_started" for row in rows):
        raise ValueError("parent matrix contains an attempted row")
    if matrix.get("matrix_credit") != 0 or matrix.get("qualified") is not False or matrix.get("qualification_claim") != "none":
        raise ValueError("parent matrix carries qualification state")
    md = matrix.get("denominator", {})
    expected_matrix_denominator = {"planned": 15, "executed": 0, "passed": 0, "failed": 0, "unattempted": 15, "event_censored": 0, "credit": 0}
    if any(md.get(key) != value for key, value in expected_matrix_denominator.items()):
        raise ValueError("parent matrix denominator is not closed")
    expected_denominator = {"planned": 15, "executed": 0, "passed": 0, "failed": 0, "unattempted": 15, "credit": 0}
    if any(denominator.get(key) != value for key, value in expected_denominator.items()):
        raise ValueError("parent failure denominator is not closed")
    if denominator.get("qualified") is not False or denominator.get("qualification_claim") != "none":
        raise ValueError("parent failure denominator carries qualification")
    preservation = denominator.get("preservation", {})
    for key in ("all_rows_retained", "horizon_extension_before_anchor", "prior_lineages_merged", "same_input_retry", "static_hold_substitution", "survivor_renormalization", "threshold_relaxation"):
        expected = key in {"all_rows_retained"}
        if preservation.get(key) is not expected:
            raise ValueError(f"parent denominator preservation changed: {key}")
    if lineage.get("scope_id") != PARENT_SCOPE or lineage.get("qualification_claim") != "none":
        raise ValueError("parent lineage carries qualification")
    if lineage.get("source_asset_policy", {}).get("cpu_native_preflight_status") != "not_run":
        raise ValueError("parent lineage CPU/native status changed")
    return {
        "matrix_rows": 15,
        "matrix_all_not_started": True,
        "matrix_denominator": md,
        "failure_denominator": {key: denominator.get(key) for key in expected_denominator},
        "lineage_cpu_native_preflight_status": lineage["source_asset_policy"]["cpu_native_preflight_status"],
    }


def _assert_static_records() -> dict[str, Any]:
    root_receipt = load(ROOT_RECEIPT)
    static_contract = load(STATIC_CONTRACT)
    candidate = load(CANDIDATE)
    failure = load(FAILURE_EVIDENCE)
    preflight_contract = load(PREFLIGHT_CONTRACT)
    preflight = load(PREFLIGHT)

    if root_receipt.get("schema") != "core.f2.submerged_orifice_transfer.root_review_receipt.v4":
        raise ValueError("root review receipt schema changed")
    if root_receipt.get("authorized_case_id") != CASE_ID or root_receipt.get("matrix_credit") != 0 or root_receipt.get("qualification_claim") != "none":
        raise ValueError("root review receipt identity/credit changed")
    if root_receipt.get("authorized_for_one_fresh_cpu_native_preflight") is not True:
        raise ValueError("root review receipt no longer records exact-one scope")
    _assert_zero_permission(root_receipt.get("authorization", {}), "root review receipt")
    controls = root_receipt.get("execution_controls", {})
    for key in ("cpu_gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"root review receipt records execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "qualification_numerator_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"root review receipt records mutation/credit: {key}")

    if static_contract.get("authorized_now") is not False or static_contract.get("proposal_only") is not True:
        raise ValueError("static contract opened runtime authority")
    if static_contract.get("qualification_claim") != "none" or static_contract.get("matrix_credit") != 0:
        raise ValueError("static contract carries credit")
    _assert_zero_permission(static_contract.get("authorization", {}), "static contract")
    if static_contract.get("preflight", {}).get("qualification_credit") != 0:
        raise ValueError("static contract preflight carries credit")

    if candidate.get("candidate_status") != "root_review_only_static_candidate_not_run" or candidate.get("qualified") is not False:
        raise ValueError("candidate is not static")
    if candidate.get("qualification_claim") != "none" or candidate.get("matrix_credit") != 0:
        raise ValueError("candidate carries credit")
    if candidate.get("denominator_preservation", {}).get("planned_rows") != 15 or candidate.get("denominator_preservation", {}).get("unattempted_rows") != 15:
        raise ValueError("candidate denominator changed")
    if candidate.get("denominator_preservation", {}).get("qualification_numerator") != 0:
        raise ValueError("candidate carries numerator credit")
    if candidate.get("source_lattice_closure", {}).get("runtime_count_observed") is not False:
        raise ValueError("candidate prediction was relabeled as observation")
    gates = candidate.get("hard_preflight_gates", {})
    if gates.get("zero_boundnor_count_max") != 0 or gates.get("zero_normal_size_count_max") != 0 or gates.get("native_mass_relative_error_max") != 0.025:
        raise ValueError("candidate hard gates changed")
    if gates.get("threshold_relaxation") is not False or gates.get("survivor_renormalization") is not False:
        raise ValueError("candidate relaxed a gate")

    if failure.get("status") != "read_only_v3_failure_evidence_closed" or failure.get("qualification_claim") != "none" or failure.get("matrix_credit") != 0:
        raise ValueError("v3 failure evidence is not closed")
    if preflight_contract.get("qualification_claim") != "none" or preflight_contract.get("matrix_credit") != 0:
        raise ValueError("CPU/native contract carries credit")
    if preflight_contract.get("denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("CPU/native contract carries denominator credit")

    if preflight.get("schema") != "core.f2.submerged_orifice_transfer.cpu_native_preflight.v4" or preflight.get("case_id") != CASE_ID:
        raise ValueError("preflight identity changed")
    if preflight.get("preflight_pass") is not False or preflight.get("qualified") is not False:
        raise ValueError("preflight is not a hard negative")
    if preflight.get("qualification_claim") != "none" or preflight.get("matrix_credit") != 0:
        raise ValueError("preflight carries credit")
    if "no solver trajectory" not in preflight.get("interpretation_boundary", ""):
        raise ValueError("preflight interpretation boundary missing")
    pctrl = preflight.get("execution_controls", {})
    if pctrl.get("cpu_gencase_invoked") is not True or pctrl.get("cpu_native_decode_invoked") is not True:
        raise ValueError("preflight does not record exact-one CPU/native execution")
    for key in ("solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if pctrl.get(key) is not False:
            raise ValueError(f"preflight records prohibited operation: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "qualification_numerator_credit"):
        if pctrl.get(key) != 0:
            raise ValueError(f"preflight records mutation/credit: {key}")
    native = preflight.get("native_initial", {})
    if native.get("all_hard_gates_pass") is not False or native.get("zero_boundnor_count") != 29484 or native.get("zero_normal_size_count") != 29484:
        raise ValueError("preflight hard-negative normal counts changed")
    hard = native.get("hard_gates", {})
    if hard.get("mass", {}).get("pass") is not True or hard.get("ids", {}).get("pass") is not True or hard.get("finite", {}).get("pass") is not True or hard.get("endpoints", {}).get("pass") is not True:
        raise ValueError("preflight non-normal hard-gate evidence changed")
    if hard.get("zero_boundnor", {}).get("required") != 0 or hard.get("normal_size", {}).get("required") != 0:
        raise ValueError("preflight zero-normal gate relaxed")

    return {
        "v3_failure": {
            "zero_boundnor": failure["observed_failure"]["zero_boundnor_count"],
            "zero_normal_size": failure["observed_failure"]["zero_normal_size_count"],
            "mk17_outer_zero": failure["observed_failure"]["mk17_outer_zero_count"],
            "mk18_gate_zero": failure["observed_failure"]["mk18_gate_zero_count"],
            "mass_relative_error": failure["observed_failure"]["mass_relative_error"],
        },
        "v4_preflight": {
            "status": preflight["status"],
            "preflight_pass": False,
            "zero_boundnor": native["zero_boundnor_count"],
            "zero_normal_size": native["zero_normal_size_count"],
            "mass_relative_error": hard["mass"]["relative_error"],
            "mass_pass": hard["mass"]["pass"],
            "ids_pass": hard["ids"]["pass"],
            "finite_pass": hard["finite"]["pass"],
            "endpoints_pass": hard["endpoints"]["pass"],
            "solver_product_present": preflight.get("solver_product_present") is True,
        },
        "root_receipt_historical_unmaterialized": root_receipt["case"]["output_prefix_unmaterialized"],
        "root_receipt_now_stale": False,
    }


def _check_current_materialization() -> dict[str, Any]:
    receipt = load(ROOT_RECEIPT)
    prefix = Path(receipt["case"]["generated_prefix"]).resolve()
    output_root = prefix.parent
    expected = {
        "root": output_root,
        "preflight": output_root / "preflight.json",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
    }
    present = {key: path.is_file() for key, path in expected.items() if key != "root"}
    materialized = output_root.is_dir() and any(output_root.iterdir())
    if not materialized or not all(present.values()):
        raise ValueError("expected exact-one preflight output is not materialized")
    return {
        "historical_receipt_claim": bool(receipt["case"]["output_prefix_unmaterialized"]),
        "current_output_root_materialized": True,
        "current_artifacts_present": present,
        "root_receipt_now_stale": True,
        "preflight_sha256": sha256(expected["preflight"]),
        "preflight_bytes": expected["preflight"].stat().st_size,
        "output_root": str(output_root),
    }


def build_receipt(output: Path = OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    parent = _assert_parent_scope()
    static = _assert_static_records()
    materialized = _check_current_materialization()
    bindings = {
        "root_review_receipt": ref(ROOT_RECEIPT, "historical exact-one root review receipt"),
        "static_contract": ref(STATIC_CONTRACT, "v4 runtime-closed static contract"),
        "candidate": ref(CANDIDATE, "v4 static candidate"),
        "v3_failure_evidence": ref(FAILURE_EVIDENCE, "closed v3 failure evidence"),
        "preflight_contract": ref(PREFLIGHT_CONTRACT, "exact-one CPU/native contract"),
        "preflight": ref(PREFLIGHT, "existing hard-negative CPU/native preflight"),
        "v4_definition": ref(DEFINITION, "v4 literal Definition"),
        "parent_matrix": ref(PARENT_MATRIX, "parent 15-row fixed matrix"),
        "parent_denominator": ref(PARENT_DENOMINATOR, "parent 15-row failure denominator"),
        "parent_lineage": ref(PARENT_LINEAGE, "parent lineage closure"),
        "parent_root_contract": ref(PARENT_ROOT, "parent root contract"),
        "root_review_script": ref(ROOT_REVIEW_SCRIPT, "root review implementation"),
        "root_review_test": ref(ROOT_REVIEW_TEST, "root review test"),
        "preflight_script": ref(PREFLIGHT_SCRIPT, "CPU/native preflight implementation"),
        "preflight_test": ref(PREFLIGHT_TEST, "CPU/native preflight test"),
        "material_review_script": ref(Path(__file__).resolve(), "independent T2 boundary review"),
        "material_review_test": ref(LAB / "tests/test_f2_submerged_orifice_t2_material_review_v1.py", "independent T2 boundary test"),
    }
    receipt = {
        "schema": "core.f2.submerged_orifice_transfer.t2_material_boundary_review.v1",
        "record_id": "F2_SUBMERGED_ORIFICE_V4_T2_MATERIAL_REVIEW_20260921",
        "created_at_utc": "2026-09-21T00:00:00+00:00",
        "status": "negative_cpu_native_preflight_zero_t2_credit",
        "decision": "hard_gate_failure_closed_for_t2; no_same_input_retry",
        "scope_id": PARENT_SCOPE,
        "case_id": CASE_ID,
        "read_only_review": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "matrix_credit": 0,
        "t2_boundary": {
            "T2_macro": False,
            "T2_path": False,
            "t2_status": "not_established",
            "material_acceptance_attempted": False,
            "material_source_window_or_event_result": False,
            "future_cpu_native_preflight_is_t2_eligible": False,
            "future_run_interpretation": "CPU/native initial-integrity evidence only; never material T2 or T1/matrix credit",
            "future_same_input_retry_allowed": False,
            "hard_pass_would_still_be_t2_credit": 0,
            "core_gate_changed": False,
        },
        "root_review_snapshot": {
            "historical_output_prefix_unmaterialized": materialized["historical_receipt_claim"],
            "current_output_prefix_unmaterialized": False,
            "historical_snapshot_is_stale": True,
            "reason": "The exact-one output prefix and preflight receipt were materialized after the root-review snapshot.",
        },
        "parent_scope": parent,
        "v3_failure": static["v3_failure"],
        "v4_preflight": static["v4_preflight"],
        "current_materialization": materialized,
        "execution_controls": {
            "review_opened_solver": False,
            "review_opened_gpu": False,
            "review_created_job": False,
            "review_mutated_queue": 0,
            "review_mutated_ledger": 0,
            "review_mutated_registry": 0,
            "review_submitted_matrix": False,
            "scientific_denominator_changed": False,
            "existing_preflight_cpu_gencase_invoked": True,
            "existing_preflight_cpu_native_decode_invoked": True,
            "existing_preflight_solver_invoked": False,
            "existing_preflight_gpu_invoked": False,
            "existing_preflight_job_created": False,
            "existing_preflight_queue_mutation": 0,
            "existing_preflight_ledger_mutation": 0,
            "existing_preflight_registry_mutation": 0,
            "existing_preflight_matrix_submission": False,
            "existing_preflight_qualification_numerator_credit": 0,
        },
        "observed_action_boundary": [
            "Do not rerun the failed v4 input.",
            "Do not reinterpret CPU/native integrity as material T2.",
            "Do not relax zero-normal, finite/ID, endpoint, or 2.5% mass gates.",
            "Do not change the parent 15-row denominator, registry, ledger, or Core gate.",
        ],
        "hash_bindings": bindings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    partial.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(output)
    return receipt


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(Path(path).resolve())
    if value.get("schema") != "core.f2.submerged_orifice_transfer.t2_material_boundary_review.v1":
        raise ValueError("material review schema mismatch")
    if value.get("qualification_claim") != "none" or value.get("qualification_credit") != 0 or value.get("matrix_credit") != 0:
        raise ValueError("material review carries credit")
    boundary = value.get("t2_boundary", {})
    if boundary.get("T2_macro") is not False or boundary.get("T2_path") is not False or boundary.get("future_cpu_native_preflight_is_t2_eligible") is not False:
        raise ValueError("material review opens T2 interpretation")
    if boundary.get("hard_pass_would_still_be_t2_credit") != 0 or boundary.get("future_same_input_retry_allowed") is not False:
        raise ValueError("material review leaves a T2/retry loophole")
    if value.get("parent_scope", {}).get("matrix_rows") != 15 or value.get("parent_scope", {}).get("matrix_all_not_started") is not True:
        raise ValueError("material review parent closure changed")
    if value.get("current_materialization", {}).get("root_receipt_now_stale") is not True:
        raise ValueError("materialized-output finding missing")
    for key, expected in {
        "root_review_receipt": ROOT_RECEIPT,
        "static_contract": STATIC_CONTRACT,
        "candidate": CANDIDATE,
        "v3_failure_evidence": FAILURE_EVIDENCE,
        "preflight_contract": PREFLIGHT_CONTRACT,
        "preflight": PREFLIGHT,
        "v4_definition": DEFINITION,
        "parent_matrix": PARENT_MATRIX,
        "parent_denominator": PARENT_DENOMINATOR,
        "parent_lineage": PARENT_LINEAGE,
        "parent_root_contract": PARENT_ROOT,
        "root_review_script": ROOT_REVIEW_SCRIPT,
        "root_review_test": ROOT_REVIEW_TEST,
        "preflight_script": PREFLIGHT_SCRIPT,
        "preflight_test": PREFLIGHT_TEST,
        "material_review_script": Path(__file__).resolve(),
        "material_review_test": LAB / "tests/test_f2_submerged_orifice_t2_material_review_v1.py",
    }.items():
        verify_ref(value.get("hash_bindings", {}).get(key, {}), f"material review {key}", expected)
    return value


def render_report(receipt: Mapping[str, Any], output: Path = REPORT) -> Path:
    output = Path(output).resolve()
    lines = [
        "# F2 submerged-orifice v4 材料/T2 边界复核",
        "",
        "本报告只读复核现有 root-review receipt、v4 static candidate、exact-one CPU/native preflight 与父 scope；没有启动任何新 executable，也没有修改 solver、GPU、job、queue、ledger、registry 或 matrix。",
        "",
        "复核结论：现有 v4 CPU/native preflight 为硬失败，`zero_boundnor=29484`、`zero_normal_size=29484`；finite、ID、端点和 2.5% 质量门通过，但整体 `preflight_pass=false`。因此该结果保持 `qualification_claim=none`、`qualification_credit=0`、`matrix_credit=0`。",
        "",
        "父 F2 scope 仍是固定 15 行，当前 `executed=0`、`passed=0`、`failed=0`、`unattempted=15`、`credit=0`，所有 matrix row 仍为 `not_started`。CPU/native preflight 没有提交 matrix。",
        "",
        "root-review receipt 原先记录 output prefix 未物化；本复核发现其后已有 preflight JSON、XML 与 BI4，因此把该静态 freshness 字段标记为历史快照过期，不覆盖旧回执，也不重跑同一输入。",
        "",
        "T2 边界明确关闭：`T2_macro=false`、`T2_path=false`、`t2_status=not_established`。即使 CPU/native integrity 假设通过，也不能解释为 material T2、T1 或 matrix credit；同一 hard-failed input 禁止重试，不能放宽 zero-normal、finite/ID、端点或质量门。",
        "",
        f"材料边界 review receipt SHA-256：`{sha256(OUTPUT)}`。",
        f"现有 preflight SHA-256：`{receipt['current_materialization']['preflight_sha256']}`。",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write-receipt", "verify-receipt", "write-report"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.command == "write-receipt":
        result: Any = build_receipt(args.output)
    elif args.command == "verify-receipt":
        result = verify(args.output)
    else:
        result = str(render_report(verify(OUTPUT)))
    print(json.dumps(result, indent=2, ensure_ascii=False) if isinstance(result, dict) else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
