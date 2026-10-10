#!/usr/bin/env python3
"""Strict producer-proof joins for the namespace331 event adapter.

V7 selected the retry terminal correctly, but its producer-proof checks were
permissive for legacy metadata fields.  V8 keeps V7 immutable and requires
the real ``root-actual-verification.v1`` proof closure: request, manifest,
receipt, report and their hashes; a successful terminal receipt; and the
selected case's manifest/receipt/summary and trajectory bindings.  This is a
metadata-only identity gate.  It never reads H5/BI4/raw arrays and never
grants event, physical or qualification credit.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace331_v16_typed_event_adapter_v7_for_v8",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v7.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("V7 typed event adapter is unavailable")
_V7 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V7)

ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v8"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v8"
CURRENT_STATUS = _V7.CURRENT_STATUS
SOURCE_JOIN = _V7.SOURCE_JOIN
SOURCE_CLOSURE = _V7.SOURCE_CLOSURE
UNKNOWN_QUALIFICATION = dict(_V7.UNKNOWN_QUALIFICATION)
CURRENT_CATALOG_SHA256 = _V7.CURRENT_CATALOG_SHA256
CURRENT_CATALOG_SCHEMA = _V7.CURRENT_CATALOG_SCHEMA
REQUEST_SCHEMA = _V7.REQUEST_SCHEMA


class TypedEventAdapterV8Error(ValueError):
    """The selected producer proof is incomplete or crossed."""


def _fail(message: str) -> None:
    raise TypedEventAdapterV8Error(message)


def _read(path: Path | str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _V7._metadata_ref({"path": str(path), "sha256": _V7._file_sha(path)}, role=role)
    except Exception as error:
        _fail(str(error))


def _same_path(left: Any, right: Any) -> bool:
    return _V7._same_path(left, right)


def _ref(value: Any, expected: Mapping[str, Any], role: str) -> None:
    if not isinstance(value, Mapping):
        _fail(f"{role} reference is missing")
    if not _same_path(value.get("path"), expected.get("path")):
        _fail(f"{role} path differs")
    declared = value.get("sha256", value.get("file_sha256"))
    if declared != expected.get("sha256"):
        _fail(f"{role} SHA differs")


def _required_proof_fields(proof: Mapping[str, Any], case_id: str) -> None:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        _fail(f"{case_id} selected proof schema is unsupported")
    required = (
        "request", "request_sha256", "receipt", "receipt_sha256",
        "report", "report_sha256", "manifest", "manifest_sha256",
        "case_verifications", "counts", "failed_cases",
        "parent_reservation_released", "guarded_receipt_status", "outer_unit_result",
    )
    missing = [key for key in required if key not in proof]
    if missing:
        _fail(f"{case_id} selected proof lacks required fields: {','.join(missing)}")
    if not isinstance(proof["case_verifications"], list):
        _fail(f"{case_id} selected proof case_verifications is not a list")
    if not isinstance(proof["counts"], Mapping):
        _fail(f"{case_id} selected proof counts is not a mapping")
    if not isinstance(proof["failed_cases"], list) or proof["failed_cases"]:
        _fail(f"{case_id} selected proof has failed cases")
    if proof.get("parent_reservation_released") is not True:
        _fail(f"{case_id} selected proof reservation is not released")
    if str(proof.get("guarded_receipt_status", "")).lower() != "completed":
        _fail(f"{case_id} selected proof receipt is not completed")
    if str(proof.get("outer_unit_result", "")).lower() not in {"success", "completed"}:
        _fail(f"{case_id} selected proof outer unit did not succeed")
    if proof["counts"].get("failed", 0) != 0:
        _fail(f"{case_id} selected proof counts.failed is not zero")


def _selected_proof_join(plan: Mapping[str, Any], registry: Mapping[str, Any],
                         case_id: str, join: Mapping[str, Any]) -> dict[str, Any]:
    rows = [row for row in plan.get("case_records", [])
            if isinstance(row, Mapping) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        _fail(f"{case_id} plan row is not unique")
    row = rows[0]
    evidence = row.get("producer_evidence")
    if not isinstance(evidence, Mapping):
        _fail(f"{case_id} producer evidence is missing")
    producer_id = join.get("producer_id")
    producers = [item for item in registry.get("producers", [])
                 if isinstance(item, Mapping) and item.get("producer_id") == producer_id
                 and case_id in item.get("case_ids", [])]
    if len(producers) != 1 or producers[0].get("status") != "COMPLETED":
        _fail(f"{case_id} selected producer is not a unique completed producer")
    producer = producers[0]
    docs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for key in ("request", "manifest", "proof"):
        value = producer.get(key)
        if not isinstance(value, Mapping):
            _fail(f"{case_id} producer {key} binding is missing")
        path = value.get("path")
        sha = value.get("sha256")
        if not isinstance(path, str) or not isinstance(sha, str):
            _fail(f"{case_id} producer {key} binding is incomplete")
        doc, ref = _V7._metadata_ref({"path": path, "sha256": sha}, role=f"{case_id} producer {key}")
        docs[key] = (doc, ref)
    request, request_ref = docs["request"]
    manifest, manifest_ref = docs["manifest"]
    proof, proof_ref = docs["proof"]
    _required_proof_fields(proof, case_id)
    if request.get("schema") != "ds02.request.v1" or request.get("attempt_id") != join.get("plan_attempt_id"):
        _fail(f"{case_id} selected request attempt/schema differs")
    if case_id not in request.get("physical_case_ids", []) and request.get("case_id") != case_id:
        _fail(f"{case_id} selected request does not bind the case")
    if manifest.get("schema") != "ds02.stage2.typed-lifecycle-batch.v1":
        _fail(f"{case_id} selected manifest schema is unsupported")
    if proof.get("request") != request_ref["path"] or proof.get("request_sha256") != request_ref["sha256"]:
        _fail(f"{case_id} selected proof request binding differs")
    if proof.get("manifest") != manifest_ref["path"] or proof.get("manifest_sha256") != manifest_ref["sha256"]:
        _fail(f"{case_id} selected proof manifest binding differs")
    _, receipt_ref = _read(proof["receipt"], f"{case_id} selected receipt")
    _, report_ref = _read(proof["report"], f"{case_id} selected report")
    if receipt_ref["sha256"] != proof["receipt_sha256"] or report_ref["sha256"] != proof["report_sha256"]:
        _fail(f"{case_id} selected receipt/report SHA differs")
    rows = [item for item in proof["case_verifications"]
            if isinstance(item, Mapping) and item.get("physical_case_id") == case_id]
    if len(rows) != 1:
        _fail(f"{case_id} selected proof case row is not unique")
    selected = rows[0]
    if selected.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        _fail(f"{case_id} selected proof row is not saved-mask diagnostic-only")
    for key, evidence_key, sha_key in (("case_manifest", "case_manifest", "case_manifest_sha256"),
                                       ("receipt", "case_receipt", "receipt_sha256"),
                                       ("summary", "summary", "summary_sha256")):
        value = selected.get(key)
        expected = evidence.get(evidence_key)
        if not isinstance(value, str) or not isinstance(expected, Mapping):
            _fail(f"{case_id} selected proof {key} binding is missing")
        if not _same_path(value, expected.get("path")) or selected.get(sha_key) != expected.get("sha256"):
            _fail(f"{case_id} selected proof {key} differs from plan evidence")
    trajectory = selected.get("source_trajectory")
    if not isinstance(trajectory, Mapping) or not _same_path(trajectory.get("path"), row.get("trajectory_path")):
        _fail(f"{case_id} selected proof trajectory path differs from CURRENT")
    known = evidence.get("trajectory_source_sha256")
    if not isinstance(known, str) or trajectory.get("known_sha256") != known:
        _fail(f"{case_id} selected proof trajectory SHA differs from plan evidence")
    if trajectory.get("pre_sha256") != trajectory.get("post_sha256") or trajectory.get("known_sha256") != trajectory.get("post_sha256"):
        _fail(f"{case_id} selected trajectory pre/post SHA is not closed")
    return {"proof": proof_ref, "request": request_ref, "manifest": manifest_ref,
            "receipt": receipt_ref, "report": report_ref,
            "selected_case_status": selected.get("status"),
            "failed_history_count": join.get("failed_history_count", 0)}


def validate_request_v8(request: Mapping[str, Any], *, allow_fixture: bool = False,
                        require_binding: bool = False) -> dict[str, Any]:
    try:
        context = _V7.validate_request_v7(request, allow_fixture=allow_fixture,
                                          require_binding=False)
    except Exception as error:
        raise TypedEventAdapterV8Error(str(error)) from error
    scope = context.get("current_identity_scope")
    if context.get("all_roles_known") and isinstance(scope, Mapping) and scope.get("join"):
        current_plan = scope.get("plan")
        current_registry = scope.get("producer_registry")
        if not isinstance(current_plan, Mapping) or not isinstance(current_registry, Mapping):
            _fail("V8 CURRENT scope refs are missing")
        plan, _ = _V7._metadata_ref({"path": current_plan["path"], "sha256": current_plan["file_sha256"]}, role="V8 CURRENT plan")
        registry, _ = _V7._metadata_ref({"path": current_registry["path"], "sha256": current_registry["file_sha256"]}, role="V8 producer registry")
        strict = _selected_proof_join(plan, registry, request["case_identity"]["physical_case_id"], scope["join"])
        new_scope = copy.deepcopy(dict(scope))
        new_scope["join"] = dict(scope["join"])
        new_scope["join"]["proof_closure"] = strict
        context = dict(context)
        context["current_identity_scope"] = new_scope
    elif require_binding and context.get("all_roles_known"):
        _fail("V8 strict binding requires a CURRENT scope")
    context = dict(context)
    context["production_eligible"] = False
    return context


def build_unknown_event_result_from_request(request: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    context = validate_request_v8(request, allow_fixture=allow_fixture)
    if context.get("all_roles_known"):
        _fail("UNKNOWN result is not admissible when all roles are known")
    result = copy.deepcopy(_V7.build_unknown_event_result_from_request(request, allow_fixture=allow_fixture))
    result["schema"] = UNKNOWN_ADMISSION_SCHEMA
    result["adapter"] = {**result.get("adapter", {}), "schema": ADAPTER_SCHEMA,
                          "production_eligible": False, "typed_content_required": False}
    result["current_identity_scope"] = context["current_identity_scope"]
    result["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = _V7._read_json(args.request, role="V8 request")
        context = validate_request_v8(request, allow_fixture=args.allow_fixture)
        print(json.dumps({"schema": ADAPTER_SCHEMA, "status": "READY_FOR_PARENT_GUARDED_MAPPING",
                          "case_identity": context.get("case_identity"),
                          "current_identity_scope": context.get("current_identity_scope"),
                          "production_eligible": False}, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV8Error) as error:
        print(f"typed event adapter v8: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
