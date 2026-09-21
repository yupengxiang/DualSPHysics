#!/usr/bin/env python3
"""Independently review and authorize exactly one F2 v4 CPU/native preflight.

This review reads only the v3 failure evidence and v4 static contract.  It
does not call GenCase, the native decoder, solver, GPU, queue, ledger,
registry, or matrix code.  The resulting receipt opens one fresh CPU/native
preflight and grants no qualification credit.
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
CONTRACT = REMEDIATION / "root-review-only-contract-v4.json"
CANDIDATE = REMEDIATION / "normal-remediation-candidate-v4.json"
EVIDENCE = REMEDIATION / "v3-failure-evidence-v4.json"
DEFINITION = REMEDIATION / "fresh-definition-v4/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4_Def.xml"
OUTPUT_PREFIX = REMEDIATION / "preflight-v4/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
V3_PREFLIGHT = BASE / "normal-remediation-v3/preflight-v3/preflight.json"
PARENT_MATRIX = BASE / "fixed-matrix-v1.json"
PARENT_DENOMINATOR = BASE / "failure-denominator-v1.json"
PARENT_LINEAGE = BASE / "lineage-clarification-v1.json"
PARENT_ROOT = BASE / "root-review-contract-v1.json"
ADAPTER = LAB / "scripts/f2_submerged_orifice_normal_remediation_v4.py"
CONTRACT_TEST = LAB / "tests/test_f2_submerged_orifice_normal_remediation_v4.py"
OUTPUT = REMEDIATION / "root-review-receipt-v4.json"
REPORT = LAB / "reports/F2-SUBMERGED-ORIFICE-ROOT-REVIEW-V4-2026-09-21.zh-CN.md"

CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
MATRIX_INDEX = 4
MASS_GATE = 0.025
ZERO_TOL = 1.0e-12


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
        raise ValueError(f"{label}: path missing")
    path = Path(value).resolve()
    if expected is not None and path != Path(expected).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: stale hash/bytes")
    return path


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def _assert_parent_closed() -> None:
    matrix = load(PARENT_MATRIX)
    denominator = load(PARENT_DENOMINATOR)
    if matrix.get("cell_count") != 15 or matrix.get("matrix_credit") != 0:
        raise ValueError("parent matrix is not closed")
    if any(row.get("status") != "not_started" for row in matrix.get("rows", [])):
        raise ValueError("parent matrix contains a started row")
    if denominator.get("planned") != 15 or denominator.get("credit") != 0:
        raise ValueError("parent denominator is not closed")
    lineage = load(PARENT_LINEAGE)
    # The v1 lineage record uses the explicit qualification_claim field and
    # predates the later qualification_credit spelling.  Treat an absent
    # credit field as closed only when the claim is explicitly ``none``.
    if lineage.get("qualification_claim") != "none":
        raise ValueError("parent lineage carries a qualification claim")
    if lineage.get("qualification_credit", 0) not in (0, "none", None):
        raise ValueError("parent lineage carries credit")


def _assert_static_inputs() -> dict[str, Any]:
    candidate = load(CANDIDATE)
    evidence = load(EVIDENCE)
    contract = load(CONTRACT)
    v3 = load(V3_PREFLIGHT)
    if candidate.get("case_id") != CASE_ID or candidate.get("matrix_credit") != 0:
        raise ValueError("v4 candidate identity/credit changed")
    if candidate.get("candidate_status") != "root_review_only_static_candidate_not_run":
        raise ValueError("v4 candidate is not static")
    if evidence.get("status") != "read_only_v3_failure_evidence_closed" or evidence.get("matrix_credit") != 0:
        raise ValueError("v3 failure evidence is not closed")
    if v3.get("preflight_pass") is not False or v3.get("matrix_credit") != 0:
        raise ValueError("v3 preflight is not a closed negative result")
    if contract.get("schema") != "core.f2.submerged_orifice_transfer.normal_remediation.root_review_only.v4":
        raise ValueError("v4 contract schema mismatch")
    if contract.get("authorized_now") is not False or contract.get("proposal_only") is not True:
        raise ValueError("v4 contract already carries runtime authority")
    if contract.get("matrix_credit") != 0 or contract.get("failure_denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("v4 contract carries credit")
    auth = contract.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v4 contract opens {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v4 contract opens {key}")
    if contract.get("fresh_input", {}).get("generated_products_present") is not False or contract.get("fresh_input", {}).get("native_input_present") is not False:
        raise ValueError("v4 generated input already exists")
    if OUTPUT_PREFIX.exists() or (OUTPUT_PREFIX.parent.exists() and any(OUTPUT_PREFIX.parent.iterdir())):
        raise ValueError("v4 output prefix is not fresh")
    if ".bi4" in json.dumps(contract, sort_keys=True).lower():
        raise ValueError("v4 static contract contains native input path")
    gates = candidate.get("hard_preflight_gates", {})
    if gates.get("zero_boundnor_count_max") != 0 or gates.get("zero_normal_size_count_max") != 0 or gates.get("native_mass_relative_error_max") != MASS_GATE:
        raise ValueError("v4 hard gates changed")
    if candidate.get("source_lattice_closure", {}).get("expected_relative_error") != 0.0078125:
        raise ValueError("v4 predicted source mass closure changed")
    return {"candidate": candidate, "evidence": evidence, "contract": contract, "v3": v3}


def build_receipt(output: Path = OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    _assert_parent_closed()
    inputs = _assert_static_inputs()
    bindings = {
        "v4_candidate": ref(CANDIDATE, "v4 static candidate"),
        "v3_failure_evidence": ref(EVIDENCE, "closed v3 failure evidence"),
        "v4_static_contract": ref(CONTRACT, "v4 runtime-closed contract"),
        "v4_definition": ref(DEFINITION, "new v4 literal Definition"),
        "v3_failed_preflight": ref(V3_PREFLIGHT, "closed v3 failed preflight"),
        "parent_matrix": ref(PARENT_MATRIX, "parent 15-row matrix"),
        "parent_denominator": ref(PARENT_DENOMINATOR, "parent full denominator"),
        "parent_lineage": ref(PARENT_LINEAGE, "parent lineage closure"),
        "parent_root_contract": ref(PARENT_ROOT, "parent root contract"),
        "adapter": ref(ADAPTER, "v4 static candidate adapter"),
        "contract_test": ref(CONTRACT_TEST, "v4 static contract test"),
        "root_review_adapter": ref(Path(__file__), "independent v4 root-review adapter"),
        "root_review_test": ref(LAB / "tests/test_f2_submerged_orifice_root_review_v4.py", "independent v4 root-review test"),
    }
    receipt = {
        "schema": "core.f2.submerged_orifice_transfer.root_review_receipt.v4",
        "record_id": "F2_SUBMERGED_ORIFICE_ROOT_REVIEW_V4",
        "created_at_utc": "2026-09-21T00:00:00+00:00",
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "decision": "one_new_case_cpu_gencase_native_decode_only",
        "scope_id": "F2_submerged_orifice_transfer_v1",
        "revision_id": "F2_submerged_orifice_normal_remediation_v4",
        "authorized_case_id": CASE_ID,
        "authorized_matrix_index": MATRIX_INDEX,
        "authorized_for_one_fresh_cpu_native_preflight": True,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "case": {
            "case_id": CASE_ID,
            "fresh_definition": str(DEFINITION.resolve()),
            "fresh_definition_sha256": sha256(DEFINITION),
            "generated_prefix": str(OUTPUT_PREFIX.resolve()),
            "output_prefix_unmaterialized": True,
            "old_anchor_definition_reused": False,
            "old_anchor_native_input_reused": False,
            "v3_failed_definition_reused": False,
            "v3_failed_native_input_reused": False,
            "trajectory_reused": False,
        },
        "authorization": {
            "cpu_gencase": True,
            "native_decode": True,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "failure_denominator": {"planned_rows": 15, "attempted_rows": 0, "failed_rows": 0, "unattempted_rows": 15, "qualification_numerator": 0},
        "hard_gates": {
            "zero_boundnor_count_required": 0,
            "zero_normal_size_count_required": 0,
            "normal_norm_threshold_m": ZERO_TOL,
            "finite_arrays_required": True,
            "ids_unique_and_xml_aligned_required": True,
            "outer_endpoint_count_required": 0,
            "gate_endpoint_penetration_count_required": 0,
            "native_mass_relative_error_max": MASS_GATE,
            "stop_on_any_failure": True,
        },
        "execution_controls": {
            "root_review_invoked": True,
            "cpu_gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_numerator_credit": 0,
        },
        "hash_review": {
            "all_static_bindings_current": True,
            "v3_zero_boundnor": inputs["evidence"]["observed_failure"]["zero_boundnor_count"],
            "v3_zero_normal_size": inputs["evidence"]["observed_failure"]["zero_normal_size_count"],
            "v3_mass_relative_error": inputs["evidence"]["observed_failure"]["mass_relative_error"],
            "v4_predicted_mass_relative_error": inputs["candidate"]["source_lattice_closure"]["expected_relative_error"],
            "parent_matrix_rows": 15,
            "parent_matrix_all_not_started": True,
        },
        "hash_bindings": bindings,
        "prohibited_actions": [
            "do not reuse any v3 or older Definition/native input",
            "do not start solver, GPU, job, queue, ledger, registry, or matrix submission",
            "do not relax hard gates, drop failures, or grant qualification credit",
            "do not retry the v4 input after any hard-gate failure",
        ],
        "next_step": "Run exactly one fresh v4 CPU GenCase/native decode; stop on any hard-gate failure and retain zero credit.",
    }
    write_json(output, receipt)
    return receipt


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f2.submerged_orifice_transfer.root_review_receipt.v4":
        raise ValueError("v4 receipt schema mismatch")
    if value.get("authorized_for_one_fresh_cpu_native_preflight") is not True or value.get("matrix_credit") != 0:
        raise ValueError("v4 receipt authority/credit mismatch")
    if value.get("case", {}).get("case_id") != CASE_ID or value["case"]["output_prefix_unmaterialized"] is not True:
        raise ValueError("v4 case identity changed")
    auth = value.get("authorization", {})
    if auth.get("cpu_gencase") is not True or auth.get("native_decode") is not True:
        raise ValueError("v4 CPU/native authorization missing")
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v4 receipt opens {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v4 receipt opens {key}")
    for key, expected in {
        "v4_candidate": CANDIDATE, "v3_failure_evidence": EVIDENCE, "v4_static_contract": CONTRACT,
        "v4_definition": DEFINITION, "v3_failed_preflight": V3_PREFLIGHT, "parent_matrix": PARENT_MATRIX,
        "parent_denominator": PARENT_DENOMINATOR, "parent_lineage": PARENT_LINEAGE, "parent_root_contract": PARENT_ROOT,
        "adapter": ADAPTER, "contract_test": CONTRACT_TEST, "root_review_adapter": Path(__file__),
        "root_review_test": LAB / "tests/test_f2_submerged_orifice_root_review_v4.py",
    }.items():
        verify_ref(value.get("hash_bindings", {}).get(key, {}), f"v4 receipt {key}", expected)
    if value.get("failure_denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("v4 receipt carries credit")
    controls = value.get("execution_controls", {})
    for key in ("cpu_gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"v4 receipt records execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v4 receipt records mutation: {key}")
    if ".bi4" in json.dumps(value, sort_keys=True).lower():
        raise ValueError("v4 receipt contains native input path")
    return value


def render_report(receipt: dict[str, Any], output: Path = REPORT) -> Path:
    output = Path(output).resolve()
    text = "\n".join([
        "# F2 submerged-orifice v4 independent root review",
        "",
        "该 review 只检查 v3 失败证据、v4 Definition/candidate/contract 及父 scope hash closure，没有执行 GenCase/native decoder、solver、GPU、queue、ledger、registry 或 matrix 操作。",
        "",
        "v4 的唯一假设是镜像 GeometryForNormals 层方向并把源格点固定为 86×56×48；预测离散质量相对误差为 +0.78125%，zero-normal、ID、有限值、端点和质量门槛保持原登记值。",
        "",
        "receipt 只授权一次全新 v4 CPU GenCase/native decode，credit=0。任何 hard-gate 失败都停止并保留 15 行分母，不能转 solver 或资格。",
        "",
        f"receipt SHA-256：`{sha256(OUTPUT)}`。",
        "",
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write-receipt", "verify-receipt", "write-report"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.command == "write-receipt":
        value = build_receipt(args.output)
    elif args.command == "verify-receipt":
        value = verify(args.output)
    else:
        value = str(render_report(verify(OUTPUT)))
    print(json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, dict) else value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
