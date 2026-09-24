"""Recompute an R008 v2 D table from a closed B→C→D provenance chain.

This read-only orchestration layer composes the existing reviewed bundle
verifier with the separately reviewed v2 table semantics checker. External
authorization authenticity and the caller's interpreter/runtime attestation
remain trust inputs; this module launches no native tools and grants no T1
credit.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_fluid_table_bundle_verifier.v1"
LAB = Path(__file__).resolve().parents[1]
PARAMETER_CONTRACT_RELATIVE = (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json"
)
PARAMETER_CONTRACT_SHA256 = "f15d9db7e41fd626311f0040b3a3fd4c4498cf6152f23e446d0c23cc495865d6"
TABLE_V2_CODE_RELATIVE = "scripts/f8_r008_native_fluid_table_v2.py"
TABLE_REVIEW_SCHEMA = "core.cfd.f8.r008_native_fluid_table_schema_implementation_review.v2"
TABLE_REVIEW_RECORD_ID = "f8-r008-native-fluid-table-schema-implementation-review-v2"
TABLE_REVIEW_AGENT_ID = "01a0d297-70b1-79b3-b4ba-40c479490929"
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
HEX16 = re.compile(r"[0-9a-f]{16}\Z", re.ASCII)


class NativeFluidBundleVerificationError(ValueError):
    """The R008 v2 table is not bound to the closed B/C/D source context."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidBundleVerificationError(message)


def _check_frozen_source_binding(
    receipt: Mapping[str, Any], row: Mapping[str, Any], field: str, lab_fd: int,
) -> dict[str, Any]:
    frozen = row.get(field)
    binding = receipt.get(f"{field}_binding")
    _require(isinstance(frozen, dict)
             and set(frozen) == {"path", "bytes", "role", "sha256"},
             f"frozen Definition/control pack entry {field} is malformed")
    expected = {key: frozen[key] for key in ("path", "bytes", "sha256")}
    _require(isinstance(binding, dict) and set(binding) == {"path", "bytes", "sha256"}
             and binding == expected,
             f"B {field} binding differs from the exact frozen R008 pack row")
    _require(isinstance(expected["bytes"], int) and not isinstance(expected["bytes"], bool)
             and 0 < expected["bytes"] <= bundle.MAX_RECEIPT_BYTES
             and isinstance(expected["sha256"], str) and bool(HEX64.fullmatch(expected["sha256"])),
             f"frozen R008 {field} size or SHA-256 is invalid")
    payload = bundle._stable_read_beneath(lab_fd, expected["path"], expected["bytes"])
    _require(len(payload) == expected["bytes"]
             and hashlib.sha256(payload).hexdigest() == expected["sha256"],
             f"frozen R008 {field} source bytes differ from their pinned pack binding")
    return expected


def _fluid_ids_from_cohorts(cohorts: Mapping[str, Any]) -> np.ndarray:
    case_np = cohorts.get("case_np")
    ranges = cohorts.get("group_ranges", {}).get("fluid")
    _require(isinstance(case_np, int) and not isinstance(case_np, bool)
             and 0 < case_np <= decoder.MAX_ARRAY_COUNT,
             "B fluid cohort has an invalid CaseNp universe")
    _require(isinstance(ranges, list) and bool(ranges),
             "B generated XML has no registered fluid ID ranges")
    pieces: list[np.ndarray] = []
    total = 0
    for item in ranges:
        _require(isinstance(item, dict) and set(item) == {"begin", "count"}
                 and isinstance(item["begin"], int) and not isinstance(item["begin"], bool)
                 and isinstance(item["count"], int) and not isinstance(item["count"], bool)
                 and item["begin"] >= 0 and item["count"] > 0
                 and item["begin"] + item["count"] <= case_np,
                 "B fluid ID range is outside the verified CaseNp universe")
        total += item["count"]
        _require(total <= case_np, "B fluid ID range total exceeds CaseNp")
        pieces.append(np.arange(item["begin"], item["begin"] + item["count"], dtype="<u4"))
    ids = np.concatenate(pieces)
    _require(ids.size == total and np.all(ids[1:] > ids[:-1]),
             "B fluid ID ranges are duplicated or not strictly increasing")
    _require(cohorts.get("group_counts", {}).get("fluid") == total,
             "B fluid range total differs from the re-derived group count")
    return ids


def _validate_table_review_document(receipt_bytes: bytes, expected_sha256: str) -> dict[str, Any]:
    _require(isinstance(receipt_bytes, bytes) and 0 < len(receipt_bytes) <= bundle.MAX_RECEIPT_BYTES,
             "caller-trusted native-table review receipt is absent or oversized")
    _require(isinstance(expected_sha256, str) and bool(HEX64.fullmatch(expected_sha256))
             and hashlib.sha256(receipt_bytes).hexdigest() == expected_sha256,
             "caller-trusted native-table review receipt SHA-256 mismatch")
    receipt = bundle._parse_json(receipt_bytes, "caller-trusted native-table review receipt")
    _require(isinstance(receipt, dict)
             and set(receipt) == {
                 "schema", "record_id", "status", "reviewer", "reviewed_scope",
                 "findings", "known_boundary", "parent_validation", "review_boundary",
                 "execution_authority", "evidence",
             }
             and receipt.get("schema") == TABLE_REVIEW_SCHEMA
             and receipt.get("record_id") == TABLE_REVIEW_RECORD_ID
             and receipt.get("status") == "static_implementation_review_passed_no_execution_or_t1_credit",
             "caller-trusted native-table receipt is not the registered review schema/status")
    reviewer = receipt.get("reviewer")
    _require(isinstance(reviewer, dict)
             and reviewer.get("model") == "gpt-5.6-terra"
             and reviewer.get("reasoning_effort") == "high"
             and reviewer.get("agent_id") == TABLE_REVIEW_AGENT_ID
             and reviewer.get("verdict") == "PASS"
             and reviewer.get("review_mode") == "read_only_static_implementation_review"
             and reviewer.get("execution_or_evidence_mutation") is False,
             "native-table review receipt lacks the required Terra High PASS reviewer record")
    scope = receipt.get("reviewed_scope")
    _require(scope == {
        "table_schema": table_v2.TABLE_SCHEMA,
        "standalone_semantic_verifier": True,
        "verified_B_C_D_bundle_orchestration": False,
        "solver_or_T1_adjudication": False,
    }, "native-table review receipt scope differs from the standalone v2 verifier")
    authority = receipt.get("execution_authority")
    _require(authority == {
        "solver": False, "worker": False, "gpu": False, "queue": False,
        "T1_numerical": False, "qualification_credit": 0,
    }, "native-table review receipt expands execution or qualification authority")
    boundary = receipt.get("review_boundary")
    _require(boundary == {
        "production_bundle_read": False,
        "gencase_invoked": False,
        "native_decoder_invoked": False,
        "solver_or_worker_invoked": False,
        "gpu_or_queue_invoked": False,
        "registry_or_ledger_mutated": False,
        "qualification_credit": 0,
    }, "native-table review receipt boundary is not zero-execution")
    evidence = receipt.get("evidence")
    _require(isinstance(evidence, list), "native-table review receipt evidence is not a list")
    code_bindings = [item for item in evidence
                     if isinstance(item, dict) and item.get("path") == TABLE_V2_CODE_RELATIVE]
    _require(len(code_bindings) == 1,
             "native-table review receipt does not bind exactly one v2 semantic verifier source")
    _require(set(code_bindings[0]) == {"path", "role", "bytes", "sha256"}
             and isinstance(code_bindings[0].get("bytes"), int)
             and not isinstance(code_bindings[0].get("bytes"), bool)
             and 0 < code_bindings[0]["bytes"] <= bundle.MAX_RECEIPT_BYTES
             and isinstance(code_bindings[0].get("sha256"), str)
             and bool(HEX64.fullmatch(code_bindings[0]["sha256"])),
             "native-table review source binding is malformed")
    return code_bindings[0]


def _verify_table_review_source(
    binding: Mapping[str, Any], lab_fd: int,
) -> None:
    source = bundle._stable_read_beneath(lab_fd, TABLE_V2_CODE_RELATIVE, bundle.MAX_RECEIPT_BYTES)
    _require(len(source) == binding.get("bytes")
             and hashlib.sha256(source).hexdigest() == binding.get("sha256"),
             "standalone v2 table verifier source differs from its trusted review receipt")


def _open_stage_outputs(
    stage_results: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    roots: dict[str, int] = {}
    outputs: dict[str, int] = {}
    try:
        for stage in ("B", "C", "D"):
            roots[stage], outputs[stage] = bundle._open_verified_outputs(stage_results[stage])
        return roots, outputs
    except BaseException:
        for fd in (*outputs.values(), *roots.values()):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def verify_native_fluid_table_chain(
    bundle_roots: Mapping[str, Path | str],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_table_review_receipt_bytes: bytes,
    trusted_table_review_receipt_sha256: str,
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify B/C/D, frozen Definition/control inputs, and every v2 table row.

    The v1 bundle verifier is deliberately left byte-for-byte unchanged because
    its source digest is part of existing D receipts. This wrapper first
    verifies each immutable stage, securely reopens its output directory, then
    revalidates the complete B→C→D chain after table/source recomputation to
    detect bundle mutation during this pass.
    """
    table_review_binding = _validate_table_review_document(
        trusted_table_review_receipt_bytes, trusted_table_review_receipt_sha256,
    )
    _require(set(bundle_roots) == {"B", "C", "D"}
             and set(trusted_authorization_bytes) == {"B", "C", "D"}
             and set(trusted_authorization_sha256) == {"B", "C", "D"}
             and set(expected_authorization_envelopes) == {"B", "C", "D"},
             "v2 table verification requires exactly the B/C/D roots and trust bindings")
    stage_results = {
        stage: bundle.verify_stage_bundle(
            bundle_roots[stage], stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
            trusted_code_review_receipt_bytes=(
                trusted_code_review_receipt_bytes if stage == "D" else None
            ),
            trusted_runtime_assumption=(trusted_runtime_assumption if stage == "D" else None),
        )
        for stage in ("B", "C", "D")
    }
    _require(all(stage_results[stage]["status"] == "passed" for stage in ("B", "C", "D")),
             "v2 table semantics require passed B, C, and D stage receipts")
    case_ids = {stage_results[stage]["case_id"] for stage in ("B", "C", "D")}
    _require(len(case_ids) == 1, "B/C/D table source case identities differ")
    case_id = next(iter(case_ids))
    frozen_row = bundle._frozen_qualification_row(case_id)
    expected_axis = bundle.expected_time_axis_hex(frozen_row)
    c_manifest = stage_results["C"]["_manifest_document"]
    c_frames = c_manifest.get("frames")
    _require(isinstance(c_frames, list) and len(c_frames) == len(expected_axis),
             "C raw frame manifest does not equal the complete frozen time axis")

    stage_roots, stage_outputs = _open_stage_outputs(stage_results)
    lab_fd: int | None = None
    table_fd: int | None = None
    try:
        lab_fd, _lab_absolute = bundle._open_absolute_directory(bundle.LAB)
        _verify_table_review_source(table_review_binding, lab_fd)
        b_receipt = stage_results["B"]["_receipt_document"]
        definition_binding = _check_frozen_source_binding(
            b_receipt, frozen_row, "definition", lab_fd,
        )
        control_binding = _check_frozen_source_binding(
            b_receipt, frozen_row, "control", lab_fd,
        )
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(hashlib.sha256(parameter_contract).hexdigest() == PARAMETER_CONTRACT_SHA256,
                 "frozen F8 parameter contract differs from its pinned SHA-256")

        cohorts, mass_bits_hex = bundle._verify_b_materialization_semantics(
            stage_outputs["B"], stage_results["B"]["_output_file_manifest"], b_receipt,
        )
        fluid_ids = _fluid_ids_from_cohorts(cohorts)
        _require(isinstance(mass_bits_hex, str) and bool(HEX16.fullmatch(mass_bits_hex)),
                 "B initial MassFluid is not exact canonical binary64 hexadecimal")
        initial_mass_bits = bytes.fromhex(mass_bits_hex)

        c_raw_manifest_sha = stage_results["C"]["manifest_sha256"]
        table_attributes = table_v2.expected_root_attributes(
            case_id=case_id,
            generated_xml_sha256=b_receipt["generated_xml_path"]["sha256"],
            definition_sha256=definition_binding["sha256"],
            materialization_receipt_sha256=stage_results["B"]["receipt_sha256"],
            raw_solver_manifest_sha256=c_raw_manifest_sha,
            scope_receipt_sha256=bundle.FROZEN_INPUT_SHA256["scope"],
            parameter_contract_sha256=PARAMETER_CONTRACT_SHA256,
        )
        d_receipt = stage_results["D"]["_receipt_document"]
        table_binding = d_receipt["native_fluid_table_binding"]
        _require(table_binding.get("path") == "outputs/native-fluid-frame-table-v2.h5",
                 "D receipt does not bind the registered v2 native-fluid table path")
        table_relative = table_binding["path"][len("outputs/"):]
        table_fd = decoder.open_regular_beneath(stage_outputs["D"], table_relative)

        def iter_source_frames():
            for ordinal, entry in enumerate(c_frames):
                _require(entry.get("ordinal") == ordinal
                         and entry.get("expected_time_s_ieee754_hex") == expected_axis[ordinal],
                         "C raw frame ordinal/time differs from the complete frozen axis")
                raw_fd = decoder.open_regular_beneath(stage_outputs["C"], entry["path"])
                try:
                    yield table_v2.read_native_source_frame_fd(
                        raw_fd, entry["sha256"], expected_bytes=entry["bytes"],
                    )
                finally:
                    os.close(raw_fd)

        source_frames = iter_source_frames()
        try:
            table_result = table_v2.verify_native_fluid_table_fd(
                table_fd,
                expected_table_bytes=table_binding["bytes"],
                expected_table_sha256=table_binding["sha256"],
                expected_attributes=table_attributes,
                expected_time_axis_hex=expected_axis,
                expected_fluid_ids=fluid_ids,
                expected_case_np=cohorts["case_np"],
                initial_massfluid_binary64_le=initial_mass_bits,
                source_frames=source_frames,
            )
        finally:
            source_frames.close()

        # Reopen and revalidate every receipt, detached manifest, and raw frame
        # after the semantic pass; the per-file table/raw-FD checks above do not
        # replace full chain closure or caller-side authority authentication.
        chain = bundle.verify_provenance_chain(
            bundle_roots,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
            trusted_code_review_receipt_bytes=trusted_code_review_receipt_bytes,
            trusted_runtime_assumption=trusted_runtime_assumption,
        )
        for stage in ("B", "C", "D"):
            _require(chain["receipt_sha256"][stage] == stage_results[stage]["receipt_sha256"]
                     and chain["manifest_sha256"][stage] == stage_results[stage]["manifest_sha256"],
                     f"{stage} receipt/manifest changed during v2 table verification")
        _require(chain["all_stages_passed"] is True,
                 "revalidated B/C/D chain contains a non-passed stage")
        final_row = bundle._frozen_qualification_row(case_id)
        _require(final_row == frozen_row,
                 "frozen R008 Definition/control/scope row changed during table verification")
        _check_frozen_source_binding(b_receipt, final_row, "definition", lab_fd)
        _check_frozen_source_binding(b_receipt, final_row, "control", lab_fd)
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(hashlib.sha256(parameter_contract).hexdigest() == PARAMETER_CONTRACT_SHA256,
                 "frozen F8 parameter contract changed during table verification")
        _verify_table_review_source(table_review_binding, lab_fd)
        return {
            "schema": SCHEMA,
            "case_id": case_id,
            "provenance_chain_references_closed": True,
            "definition_control_bindings_match_frozen_pack_and_source_bytes": True,
            "native_fluid_table": table_result,
            "stage_statuses": chain["stage_statuses"],
            "receipt_sha256": chain["receipt_sha256"],
            "manifest_sha256": chain["manifest_sha256"],
            "native_table_review_receipt_sha256": trusted_table_review_receipt_sha256,
            "native_table_review_authenticity": "caller_supplied_trust_not_authenticated_here",
            "integration_wrapper_code_identity_verified": False,
            "authorization_authenticity": chain["authority_authenticity"],
            "loaded_module_code_identity_verified": False,
            "runtime_environment_assumption": chain["runtime_environment_assumption"],
            "native_integrity_evaluated": False,
            "metrics_evaluated": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }
    finally:
        if table_fd is not None:
            os.close(table_fd)
        if lab_fd is not None:
            os.close(lab_fd)
        for fd in (*stage_outputs.values(), *stage_roots.values()):
            os.close(fd)


__all__ = [
    "NativeFluidBundleVerificationError", "SCHEMA", "verify_native_fluid_table_chain",
]
