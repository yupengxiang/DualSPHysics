#!/usr/bin/env python3
"""Independently review and authorize exactly one v3 CPU/native preflight.

The receipt is issued only after re-hashing the v4 failure audit, the v3
candidate, fresh Definition, static contract, writer/audit adapters, tests,
and the parent scope closure.  Its only positive permissions are CPU GenCase
and native decode for the exact v3 case.  Solver, GPU, job, queue, ledger,
registry, matrix, and qualification authority remain closed.  This module
never invokes any runtime executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_submerged_orifice_normal_remediation_v3 import (  # noqa: E402
    CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_BASE,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_OUTPUT_PREFIX,
    DEFAULT_PREFLIGHT,
    EXPECTED_ROWS,
    PARENT_V4_CASE_ID,
    Q,
    DP_M,
    REVISION_ID,
    SCHEMA_CANDIDATE,
    SCHEMA_CONTRACT,
    inspect_definition,
    verify_contract,
)
from scripts.f2_submerged_orifice_v4_failure_audit_v1 import (  # noqa: E402
    SCHEMA as AUDIT_SCHEMA,
)
from scripts.f2_submerged_orifice_scope_v1 import (  # noqa: E402
    SCOPE_ID,
    load_json,
    verify_bundle,
)


SCHEMA = "core.f2.submerged_orifice_transfer.normal_remediation.root_review_receipt.v3"
REVIEW_ID = "F2_SUBMERGED_ORIFICE_NORMAL_REMEDIATION_ROOT_REVIEW_V3"
CREATED_AT = "2026-09-21T00:00:00+00:00"
MATRIX_INDEX = 4
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
MASS_RELATIVE_ERROR_MAX = 0.025
DEFAULT_RECEIPT = DEFAULT_BASE / "normal-remediation-v3/root-review-receipt-v3.json"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports/F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-ROOT-REVIEW-V3-2026-09-21.zh-CN.md"
)
V3_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_v3.py"
ROOT_REVIEW_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_root_review_v3.py"
V3_ADAPTER = LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_v3.py"
AUDIT_ADAPTER = LAB_ROOT / "scripts/f2_submerged_orifice_v4_failure_audit_v1.py"
SCOPE_ADAPTER = LAB_ROOT / "scripts/f2_submerged_orifice_scope_v1.py"
SCOPE_TEST = LAB_ROOT / "tests/test_f2_submerged_orifice_scope_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def verify_ref(item: Mapping[str, Any], label: str, expected: Path | None = None) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: path missing")
    path = Path(value).resolve()
    if expected is not None and path != Path(expected).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA-256 mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def _assert_closed_mutations(value: Mapping[str, Any], label: str) -> None:
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if value.get(key) is not False:
            raise ValueError(f"{label} opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if value.get(key) != 0:
            raise ValueError(f"{label} opened {key}")


def _check_parent_scope(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    bundle = verify_bundle(base)
    if bundle.get("status") != "root_review_only_contract_verified":
        raise ValueError("parent scope bundle is not independently verified")
    matrix = load_json(base / "fixed-matrix-v1.json")
    if matrix.get("schema") != "core.f2.submerged_orifice_transfer.fixed_matrix.v1":
        raise ValueError("parent matrix schema mismatch")
    if matrix.get("cell_count") != EXPECTED_ROWS or matrix.get("matrix_credit") != 0:
        raise ValueError("parent matrix count/credit changed")
    rows = matrix.get("rows", [])
    if len(rows) != EXPECTED_ROWS or any(row.get("status") != "not_started" for row in rows):
        raise ValueError("parent matrix has a started row")
    row = rows[MATRIX_INDEX]
    if row.get("q") != Q or row.get("dp_m") != DP_M or row.get("status") != "not_started":
        raise ValueError("parent matrix index 4 identity/status changed")
    denominator = load_json(base / "failure-denominator-v1.json")
    if (
        denominator.get("planned") != EXPECTED_ROWS
        or denominator.get("executed") != 0
        or denominator.get("credit") != 0
        or denominator.get("preservation", {}).get("all_rows_retained") is not True
        or denominator.get("preservation", {}).get("same_input_retry") is not False
        or denominator.get("preservation", {}).get("threshold_relaxation") is not False
    ):
        raise ValueError("parent denominator is not closed")
    lineage = load_json(base / "lineage-clarification-v1.json")
    source = lineage.get("source_asset_policy", {})
    if (
        source.get("new_definition_required") is not True
        or source.get("new_generated_native_required") is not True
        or source.get("old_failed_definition_reused") is not False
        or source.get("old_failed_trajectory_reused") is not False
        or source.get("cpu_native_preflight_status") != "not_run"
    ):
        raise ValueError("parent lineage permits reuse or records runtime")
    if any(
        item.get("historical_execution_reused") is True
        or item.get("same_input_retry") is True
        for item in lineage.get("comparison_and_noninheritance", [])
    ):
        raise ValueError("parent lineage comparison permits reuse")
    root_contract = load_json(base / "root-review-contract-v1.json")
    if (
        root_contract.get("matrix_credit") != 0
        or root_contract.get("authorized_anchor") is not False
        or root_contract.get("authorized_runtime_preparation") is not False
    ):
        raise ValueError("parent root contract is not closed")
    _assert_closed_mutations(root_contract.get("authorization", {}), "parent authorization")
    return {
        "bundle": bundle,
        "matrix": matrix,
        "denominator": denominator,
        "lineage": lineage,
        "root_contract": root_contract,
    }


def _check_audit(audit_path: Path, preflight_path: Path) -> dict[str, Any]:
    audit = load_json(audit_path)
    if audit.get("schema") != AUDIT_SCHEMA or audit.get("case_id") != PARENT_V4_CASE_ID:
        raise ValueError("v4 failure audit identity/schema mismatch")
    if audit.get("status") != "read_only_v4_boundnor_failure_audited":
        raise ValueError("v4 failure audit is not read-only")
    scope = audit.get("input_scope", {})
    for key in (
        "definition_read", "bi4_read", "native_decoder_invoked", "gencase_invoked",
        "solver_invoked", "gpu_invoked",
    ):
        if scope.get(key) is not False:
            raise ValueError(f"v4 audit opened prohibited path: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if scope.get(key) != 0:
            raise ValueError(f"v4 audit mutated protected state: {key}")
    summary = audit.get("generated_field_summary", {})
    if (
        summary.get("point_count") != 255906
        or summary.get("global_zero_boundnor_count") != 64899
        or summary.get("global_zero_normal_size_count") != 64899
        or summary.get("arrays_finite") is not True
    ):
        raise ValueError("v4 audit hard evidence changed")
    parts = {int(row["mk"]): row for row in audit.get("mk_partitions", [])}
    if (
        parts.get(17, {}).get("particle_count") != 226422
        or parts.get(17, {}).get("zero_boundnor_count") != 64899
        or parts.get(18, {}).get("particle_count") != 29484
        or parts.get(18, {}).get("zero_boundnor_count") != 0
    ):
        raise ValueError("v4 audit Mk partition changed")
    preflight = load_json(preflight_path)
    if (
        preflight.get("schema") != "core.f2.submerged_orifice_transfer.cpu_native_preflight.v4"
        or preflight.get("case_id") != PARENT_V4_CASE_ID
        or preflight.get("preflight_pass") is not False
        or preflight.get("matrix_credit") != 0
    ):
        raise ValueError("v4 preflight evidence identity/status changed")
    counts = preflight.get("generated_counts", {})
    native = preflight.get("native_initial", {})
    mass = native.get("hard_gates", {}).get("mass", {})
    if (
        counts.get("fluid_particles") != 240198
        or counts.get("boundary_particles") != 255906
        or native.get("zero_boundnor_count") != 64899
        or native.get("zero_normal_size_count") != 64899
        or mass.get("relative_error") != 0.04718017578125
        or mass.get("max_relative_error") != MASS_RELATIVE_ERROR_MAX
    ):
        raise ValueError("v4 preflight hard evidence changed")
    return {"audit": audit, "preflight": preflight}


def _check_v3_inputs(base: Path, audit_path: Path, preflight_path: Path) -> dict[str, Any]:
    parent = _check_parent_scope(base)
    evidence = _check_audit(audit_path, preflight_path)
    definition = inspect_definition(DEFAULT_DEFINITION)
    if definition.get("case_id") != CASE_ID or definition.get("runtime_invoked") is not False:
        raise ValueError("v3 Definition identity/runtime status changed")
    if definition.get("source_lattice", {}).get("expected_particle_count") != 231168:
        raise ValueError("v3 source lattice prediction changed")
    candidate = load_json(DEFAULT_CANDIDATE)
    if (
        candidate.get("schema") != SCHEMA_CANDIDATE
        or candidate.get("case_id") != CASE_ID
        or candidate.get("candidate_status") != "root_review_only_static_candidate_not_run"
        or candidate.get("matrix_credit") != 0
        or candidate.get("qualification_claim") != "none"
    ):
        raise ValueError("v3 candidate is not closed static input")
    identity = candidate.get("new_input_identity", {})
    for key in (
        "old_anchor_definition_reused", "old_anchor_native_input_reused",
        "v4_failed_definition_reused", "v4_failed_native_input_reused",
        "old_trajectory_reused",
    ):
        if identity.get(key) is not False:
            raise ValueError(f"v3 candidate permits reuse: {key}")
    gates = candidate.get("hard_preflight_gates", {})
    if (
        gates.get("zero_boundnor_count_max") != 0
        or gates.get("zero_normal_size_count_max") != 0
        or gates.get("zero_normal_norm_threshold_m") != ZERO_NORMAL_TOLERANCE_M
        or gates.get("native_mass_relative_error_max") != MASS_RELATIVE_ERROR_MAX
        or gates.get("threshold_relaxation") is not False
        or gates.get("survivor_renormalization") is not False
    ):
        raise ValueError("v3 candidate hard gates changed")
    denominator = candidate.get("denominator_preservation", {})
    if (
        denominator.get("planned_rows") != EXPECTED_ROWS
        or denominator.get("executed_rows") != 0
        or denominator.get("qualification_numerator") != 0
        or denominator.get("all_rows_retained") is not True
    ):
        raise ValueError("v3 candidate denominator changed")
    controls = candidate.get("execution_controls", {})
    for key in (
        "gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked",
        "job_created", "matrix_submission",
    ):
        if controls.get(key) is not False:
            raise ValueError(f"v3 candidate records execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v3 candidate records mutation: {key}")
    contract = verify_contract(
        DEFAULT_CONTRACT,
        base,
        DEFAULT_CANDIDATE,
        DEFAULT_AUDIT,
        DEFAULT_PREFLIGHT,
        DEFAULT_DEFINITION,
        V3_TEST,
    )
    if contract.get("case_id") != CASE_ID or contract.get("authorized_now") is not False:
        raise ValueError("v3 contract is not closed")
    if contract.get("preflight", {}).get("status") != "not_run":
        raise ValueError("v3 contract contains a runtime result")
    if contract.get("failure_denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("v3 contract contains credit")
    return {
        "parent": parent,
        "evidence": evidence,
        "definition": definition,
        "candidate": candidate,
        "contract": contract,
    }


def _static_bindings(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    return {
        "v4_preflight_evidence": ref(DEFAULT_PREFLIGHT, "v4 failed preflight evidence"),
        "v4_boundnor_failure_audit": ref(DEFAULT_AUDIT, "v4 read-only Bound.vtk audit"),
        "v4_failure_audit_adapter": ref(AUDIT_ADAPTER, "v4 read-only audit adapter"),
        "v3_candidate": ref(DEFAULT_CANDIDATE, "v3 static candidate"),
        "v3_fresh_definition": ref(DEFAULT_DEFINITION, "v3 fresh literal Definition"),
        "v3_static_contract": ref(DEFAULT_CONTRACT, "v3 runtime-closed contract"),
        "v3_writer_adapter": ref(V3_ADAPTER, "v3 Definition/candidate/contract writer"),
        "v3_contract_test": ref(V3_TEST, "v3 static regression test"),
        "parent_fixed_matrix": ref(base / "fixed-matrix-v1.json", "parent 15-row matrix"),
        "parent_failure_denominator": ref(base / "failure-denominator-v1.json", "parent zero-credit denominator"),
        "parent_lineage": ref(base / "lineage-clarification-v1.json", "parent lineage closure"),
        "parent_root_contract": ref(base / "root-review-contract-v1.json", "parent root contract"),
        "scope_adapter": ref(SCOPE_ADAPTER, "parent scope adapter"),
        "scope_test": ref(SCOPE_TEST, "parent scope regression test"),
        "v3_root_review_adapter": ref(Path(__file__).resolve(), "v3 root-review adapter"),
        "v3_root_review_test": ref(ROOT_REVIEW_TEST, "v3 root-review regression test"),
    }


def _assert_output_prefix_unmaterialized(prefix: Path) -> None:
    prefix = Path(prefix).resolve()
    if prefix.exists():
        raise ValueError(f"v3 output prefix already materialized: {prefix}")
    if prefix.parent.exists() and any(prefix.parent.iterdir()):
        raise ValueError(f"v3 output directory is not fresh: {prefix.parent}")


def build_receipt(
    base: Path = DEFAULT_BASE,
    output: Path = DEFAULT_RECEIPT,
) -> dict[str, Any]:
    base = Path(base).resolve()
    reviewed = _check_v3_inputs(base, DEFAULT_AUDIT, DEFAULT_PREFLIGHT)
    # A receipt is immutable authorization evidence.  After its one
    # permitted CPU/native preflight has run, verification remains read-only
    # and must not reject the receipt merely because the authorized output is
    # now present.  Freshness is still enforced by ``build_receipt`` before
    # authorization and by the preflight runner before execution.
    bindings = _static_bindings(base)
    receipt = {
        "schema": SCHEMA,
        "review_id": REVIEW_ID,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "reviewed_revision_id": REVISION_ID,
        "reviewed_candidate_id": reviewed["candidate"]["candidate_id"],
        "decision": "authorized_one_fresh_cpu_native_preflight_only",
        "status": "hash_review_passed_cpu_native_only_runtime_not_run",
        "authorized_for_one_fresh_cpu_native_preflight": True,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_case_id": CASE_ID,
        "authorized_matrix_index": MATRIX_INDEX,
        "case": {
            "case_id": CASE_ID,
            "q": Q,
            "dp_m": DP_M,
            "parent_failed_case_id": PARENT_V4_CASE_ID,
            "fresh_definition": str(DEFAULT_DEFINITION.resolve()),
            "fresh_definition_sha256": sha256(DEFAULT_DEFINITION),
            "generated_prefix": str(DEFAULT_OUTPUT_PREFIX.resolve()),
            "output_prefix_unmaterialized": True,
            "failed_definition_reused": False,
            "failed_native_input_reused": False,
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
        "hash_review": {
            "all_bindings_current": True,
            "parent_matrix_rows": EXPECTED_ROWS,
            "parent_matrix_all_not_started": True,
            "parent_denominator_planned": EXPECTED_ROWS,
            "parent_denominator_credit": 0,
            "parent_lineage_source_reuse": False,
            "v4_failure_audit_zero_boundnor": reviewed["evidence"]["audit"]["generated_field_summary"]["global_zero_boundnor_count"],
            "v4_failure_audit_outer_mk17_zero_boundnor": 64899,
            "v4_failure_audit_gate_mk18_zero_boundnor": 0,
            "v4_mass_relative_error": 0.04718017578125,
            "v4_mass_relative_error_max": MASS_RELATIVE_ERROR_MAX,
            "v3_candidate_status": reviewed["candidate"]["candidate_status"],
            "v3_contract_status": reviewed["contract"]["status"],
            "v3_hard_zero_boundnor_max": 0,
            "v3_hard_zero_normal_size_max": 0,
            "v3_hard_mass_relative_error_max": MASS_RELATIVE_ERROR_MAX,
        },
        "hash_bindings": bindings,
        "preflight_requirements": {
            "must_use_exact_case_id": CASE_ID,
            "must_use_exact_fresh_definition_sha256": sha256(DEFAULT_DEFINITION),
            "must_use_exact_new_output_prefix": str(DEFAULT_OUTPUT_PREFIX.resolve()),
            "zero_boundnor_count_required": 0,
            "zero_normal_size_count_required": 0,
            "normal_norm_threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "finite_arrays_required": True,
            "ids_unique_and_xml_aligned_required": True,
            "outer_endpoint_count_required": 0,
            "gate_endpoint_penetration_count_required": 0,
            "native_mass_relative_error_max": MASS_RELATIVE_ERROR_MAX,
            "qualification_credit": 0,
            "stop_on_any_hard_gate_failure": True,
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
        "prohibited_actions": [
            "do not reuse v4 failed Definition or native input",
            "do not launch solver or GPU",
            "do not create a job or mutate queue, ledger, or registry",
            "do not submit or expand the matrix",
            "do not relax zero-normal or mass gates",
            "do not grant qualification credit from this receipt",
        ],
        "next_step": "An operator may run exactly one fresh v3 CPU GenCase/native decode preflight under this receipt; no solver action follows automatically.",
    }
    write_json(output, receipt)
    return receipt


def verify_receipt(
    receipt_path: Path = DEFAULT_RECEIPT,
    base: Path = DEFAULT_BASE,
) -> dict[str, Any]:
    base = Path(base).resolve()
    receipt = load_json(Path(receipt_path).resolve())
    if receipt.get("schema") != SCHEMA:
        raise ValueError("v3 root-review receipt schema mismatch")
    if receipt.get("decision") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("v3 receipt decision changed")
    if receipt.get("authorized_for_one_fresh_cpu_native_preflight") is not True:
        raise ValueError("v3 receipt did not authorize the exact preflight")
    if receipt.get("authorized_case_id") != CASE_ID or receipt.get("authorized_matrix_index") != MATRIX_INDEX:
        raise ValueError("v3 receipt case/matrix identity changed")
    auth = receipt.get("authorization", {})
    if auth.get("cpu_gencase") is not True or auth.get("native_decode") is not True:
        raise ValueError("v3 receipt omitted CPU/native authorization")
    _assert_closed_mutations(auth, "v3 receipt authorization")
    if receipt.get("matrix_credit") != 0 or receipt.get("qualification_claim") != "none":
        raise ValueError("v3 receipt contains credit")
    case = receipt.get("case", {})
    if (
        case.get("case_id") != CASE_ID
        or case.get("fresh_definition") != str(DEFAULT_DEFINITION.resolve())
        or case.get("fresh_definition_sha256") != sha256(DEFAULT_DEFINITION)
        or case.get("generated_prefix") != str(DEFAULT_OUTPUT_PREFIX.resolve())
        or case.get("output_prefix_unmaterialized") is not True
    ):
        raise ValueError("v3 receipt fresh input identity changed")
    for key in ("failed_definition_reused", "failed_native_input_reused", "trajectory_reused"):
        if case.get(key) is not False:
            raise ValueError(f"v3 receipt permits reuse: {key}")
    bindings = receipt.get("hash_bindings", {})
    expected = {
        "v4_preflight_evidence": DEFAULT_PREFLIGHT,
        "v4_boundnor_failure_audit": DEFAULT_AUDIT,
        "v4_failure_audit_adapter": AUDIT_ADAPTER,
        "v3_candidate": DEFAULT_CANDIDATE,
        "v3_fresh_definition": DEFAULT_DEFINITION,
        "v3_static_contract": DEFAULT_CONTRACT,
        "v3_writer_adapter": V3_ADAPTER,
        "v3_contract_test": V3_TEST,
        "parent_fixed_matrix": base / "fixed-matrix-v1.json",
        "parent_failure_denominator": base / "failure-denominator-v1.json",
        "parent_lineage": base / "lineage-clarification-v1.json",
        "parent_root_contract": base / "root-review-contract-v1.json",
        "scope_adapter": SCOPE_ADAPTER,
        "scope_test": SCOPE_TEST,
        "v3_root_review_adapter": Path(__file__).resolve(),
        "v3_root_review_test": ROOT_REVIEW_TEST,
    }
    for key, path in expected.items():
        verify_ref(bindings.get(key, {}), f"v3 receipt {key}", path)
    reviewed = _check_v3_inputs(base, DEFAULT_AUDIT, DEFAULT_PREFLIGHT)
    # Verification is read-only after the authorized one-shot preflight.  The
    # fresh-prefix guard remains in build_receipt and in the runner, where it
    # prevents any same-input retry.
    if receipt.get("hash_review", {}).get("all_bindings_current") is not True:
        raise ValueError("v3 receipt hash review is not closed")
    if receipt.get("execution_controls", {}).get("qualification_numerator_credit") != 0:
        raise ValueError("v3 receipt grants credit")
    controls = receipt.get("execution_controls", {})
    for key in ("cpu_gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"v3 receipt records execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v3 receipt records mutation: {key}")
    if ".bi4" in json.dumps(receipt, sort_keys=True).lower():
        raise ValueError("v3 receipt must not bind a failed native input path")
    if reviewed["candidate"].get("case_id") != CASE_ID:
        raise ValueError("v3 candidate changed during receipt verification")
    return receipt


def build_report(
    receipt_path: Path = DEFAULT_RECEIPT,
    output: Path = DEFAULT_REPORT,
) -> Path:
    receipt = verify_receipt(receipt_path)
    bindings = receipt["hash_bindings"]
    lines = [
        "# F2 submerged-orifice normal remediation v3 root review",
        "",
        "本报告是独立静态 root review receipt 的中文报告。v4 failure audit、v3 candidate、fresh Definition、writer/audit adapters、测试以及父 scope 闭合文件均重新 SHA 校验通过。",
        "",
        "审计证据显示 v4 的 64,899 个 zero `BoundNor/NormalSize` 全部在外壁 `Mk=17`，闸板 `Mk=18` 为 0；v4 源粒子数为 86×57×49=240,198，质量误差为 +4.718017578125%。v3 只提出一个几何/法向闭合假设：GeometryForNormals 镜像活动 shell 层，并将 source lattice 静态收敛为 86×56×48=231,168。",
        "",
        "由于全部输入闭合，receipt 只授权一个全新 v3 case 的 CPU GenCase 与 native decode。solver、GPU、job、queue、ledger、registry、matrix submission 均关闭；zero-normal 必须为 0、NormalSize 必须为 0、数组/ID/端点和 mass≤2.5% 门槛保持不变。",
        "",
        f"授权 case：`{receipt['authorized_case_id']}`；matrix index：`{receipt['authorized_matrix_index']}`；当前仍未执行 runtime，credit=0。",
        "",
        "## Hash closure",
        "",
    ]
    for key, item in bindings.items():
        lines.append(f"- `{key}`: `{item['path']}` SHA-256 `{item['sha256']}` ({item['bytes']} bytes)")
    lines.extend(["", f"Receipt SHA-256 `{sha256(Path(receipt_path))}` ({Path(receipt_path).stat().st_size} bytes)", ""])
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-receipt", "verify-receipt", "write-report"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-receipt":
        result: Any = build_receipt(args.base, args.output or args.receipt)
    elif args.command == "verify-receipt":
        result = verify_receipt(args.receipt, args.base)
    else:
        result = str(build_report(args.receipt, args.output or DEFAULT_REPORT))
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
