#!/usr/bin/env python3
"""Forward CURRENT v4 event admission with retry-lineage proof joins.

The v6 adapter is immutable and intentionally accepts one attempt lineage.
The real v4 registry preserves failed attempts alongside a later successful
retry (for example ROOT301 -> ROOT327).  This version selects exactly one
successful terminal lineage and cross-checks the selected producer's request,
proof and manifest metadata.  Failed history remains provenance and never
contributes event or qualification credit.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_V6 = _load(
    "namespace331_v16_typed_event_adapter_v6_for_adapter_v7",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v6.py",
)
_V4 = _V6._V4

ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v7"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v7"
REQUEST_SCHEMA = _V6.REQUEST_SCHEMA
UNKNOWN_QUALIFICATION = dict(_V6.UNKNOWN_QUALIFICATION)
PLAN_SCHEMA = _V6.PLAN_SCHEMA
REGISTRY_SCHEMA = _V6.REGISTRY_SCHEMA
CURRENT_STATUS = _V6.CURRENT_STATUS
SOURCE_JOIN = _V6.SOURCE_JOIN
SOURCE_CLOSURE = _V6.SOURCE_CLOSURE
CURRENT_CATALOG_SCHEMA = "ds02.stage2.current336.v1"
CURRENT_CATALOG_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"


class TypedEventAdapterV7Error(ValueError):
    """Request or retry-aware lifecycle metadata is not admissible."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V6.canonical_sha(value)


def _read_json(path: Path | str, *, role: str) -> dict[str, Any]:
    try:
        return _V4._read_json(path, role=role)
    except Exception as error:
        raise TypedEventAdapterV7Error(str(error)) from error


def _file_sha(path: Path | str) -> str:
    try:
        return _V4._file_sha(Path(path))
    except Exception as error:
        raise TypedEventAdapterV7Error(str(error)) from error


def _path(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise TypedEventAdapterV7Error(f"{role} path is missing")
    return Path(value).expanduser()


def _same_path(left: Any, right: Any) -> bool:
    try:
        return _path(left, "path").resolve() == _path(right, "path").resolve()
    except TypedEventAdapterV7Error:
        return False


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise TypedEventAdapterV7Error(f"{role} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise TypedEventAdapterV7Error(f"{role} is not hexadecimal") from error
    return value


def _ref_equal(left: Any, right: Any, role: str) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise TypedEventAdapterV7Error(f"{role} reference is missing")
    if not _same_path(left.get("path"), right.get("path")):
        raise TypedEventAdapterV7Error(f"{role} paths differ")
    lsha = left.get("sha256", left.get("file_sha256"))
    rsha = right.get("sha256", right.get("file_sha256"))
    if not isinstance(lsha, str) or not isinstance(rsha, str) or lsha != rsha:
        raise TypedEventAdapterV7Error(f"{role} SHAs differ")


def _metadata_ref(value: Any, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV7Error(f"{role} reference is malformed")
    path = _path(value.get("path"), f"{role}.path")
    declared = _sha(value.get("sha256"), f"{role}.sha256")
    document = _read_json(path, role=role)
    observed = _file_sha(path)
    if observed != declared:
        raise TypedEventAdapterV7Error(f"{role} SHA differs")
    return document, {"path": str(path.resolve()), "sha256": observed}


def _scope_ref(scope: Mapping[str, Any], key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value = scope.get(key)
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV7Error(f"CURRENT scope {key} is missing")
    path = _path(value.get("path"), f"CURRENT scope {key}.path")
    declared = _sha(value.get("file_sha256"), f"CURRENT scope {key}.file_sha256")
    document = _read_json(path, role=f"CURRENT scope {key}")
    observed = _file_sha(path)
    if observed != declared:
        raise TypedEventAdapterV7Error(f"CURRENT scope {key} SHA differs")
    return document, {"path": str(path.resolve()), "file_sha256": observed, "schema": document.get("schema")}


def _rows(document: Mapping[str, Any], key: str, role: str) -> list[Mapping[str, Any]]:
    rows = document.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise TypedEventAdapterV7Error(f"{role} lacks valid {key}")
    return [row for row in rows if isinstance(row, Mapping)]


def _producer_document_ref(producer: Mapping[str, Any], key: str, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value = producer.get(key)
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV7Error(f"{case_id} selected producer lacks {key}")
    return _metadata_ref(value, role=f"{case_id} selected producer {key}")


def _validate_plan_registry_v7(
    plan: Mapping[str, Any], registry: Mapping[str, Any], scope: Mapping[str, Any], case_id: str,
) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise TypedEventAdapterV7Error("CURRENT plan schema is not typed-lifecycle-continuation-plan.v4")
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise TypedEventAdapterV7Error("producer registry schema is not typed-lifecycle-evidence-registry.v4")
    plan_catalog = plan.get("current_catalog")
    registry_catalog = registry.get("current")
    _ref_equal(plan_catalog, registry_catalog, "CURRENT catalog")
    current, current_ref = _metadata_ref(plan_catalog, role="CURRENT336 catalog")
    if current.get("schema") != CURRENT_CATALOG_SCHEMA:
        raise TypedEventAdapterV7Error("CURRENT catalog schema is not current336.v1")
    if current_ref["sha256"] != CURRENT_CATALOG_SHA256:
        raise TypedEventAdapterV7Error("CURRENT catalog SHA is not the pinned CURRENT336 catalog")
    case_rows = [row for row in _rows(plan, "case_records", "CURRENT plan")
                 if row.get("physical_case_id") == case_id]
    if len(case_rows) != 1:
        raise TypedEventAdapterV7Error("CURRENT plan does not contain exactly one case row")
    row = case_rows[0]
    if row.get("historical_alias") != "NONE":
        raise TypedEventAdapterV7Error("historical alias is not admissible")
    if row.get("actual_saved_mask_coverage") is not True:
        raise TypedEventAdapterV7Error("CURRENT case is not saved-mask covered")
    if row.get("source_join_status") != SOURCE_JOIN:
        raise TypedEventAdapterV7Error("CURRENT source join is not exact")
    if row.get("status") != CURRENT_STATUS:
        raise TypedEventAdapterV7Error("CURRENT case status is not ACTUAL_SAVED_MASK_COMPLETED")
    evidence = row.get("producer_evidence")
    if not isinstance(evidence, Mapping):
        raise TypedEventAdapterV7Error("CURRENT case lacks producer_evidence")
    if evidence.get("status") != CURRENT_STATUS or evidence.get("reported_status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise TypedEventAdapterV7Error("CURRENT producer evidence status is not the saved-mask diagnostic status")
    if evidence.get("source_closure") != SOURCE_CLOSURE:
        raise TypedEventAdapterV7Error("CURRENT producer source closure is incomplete")
    attempt_id = evidence.get("attempt_id")
    lineage = row.get("attempt_lineage")
    if not isinstance(attempt_id, str) or not isinstance(lineage, list):
        raise TypedEventAdapterV7Error("CURRENT case attempt lineage is missing")
    # Failed attempts are retained as provenance.  Exactly one successful
    # saved-mask terminal is admissible; a second success is ambiguous.
    terminal = [item for item in lineage if isinstance(item, Mapping)
                and item.get("status") == CURRENT_STATUS
                and item.get("actual_saved_mask_coverage") is True]
    if len(terminal) != 1 or terminal[0].get("attempt_id") != attempt_id:
        raise TypedEventAdapterV7Error("CURRENT case has zero or multiple successful terminal attempts")
    producers = _rows(registry, "producers", "producer registry")
    matching = [producer for producer in producers if case_id in producer.get("case_ids", [])]
    completed = [producer for producer in matching if producer.get("status") == "COMPLETED"]
    if len(completed) != 1:
        raise TypedEventAdapterV7Error("CURRENT case does not have exactly one completed producer after retry history")
    producer = completed[0]
    if producer.get("producer_id") != terminal[0].get("producer_id"):
        raise TypedEventAdapterV7Error("selected completed producer differs from terminal lineage")
    request_doc, request_ref = _producer_document_ref(producer, "request", case_id)
    proof_doc, proof_ref = _producer_document_ref(producer, "proof", case_id)
    manifest_doc, manifest_ref = _producer_document_ref(producer, "manifest", case_id)
    if request_doc.get("attempt_id") != attempt_id:
        raise TypedEventAdapterV7Error("selected producer request attempt differs from plan evidence")
    if proof_doc.get("request") is not None and not _same_path(proof_doc.get("request"), request_ref["path"]):
        raise TypedEventAdapterV7Error("selected proof request path differs from registry request")
    if proof_doc.get("request_sha256") is not None and proof_doc.get("request_sha256") != request_ref["sha256"]:
        raise TypedEventAdapterV7Error("selected proof request SHA differs from registry request")
    if proof_doc.get("manifest") is not None and not _same_path(proof_doc.get("manifest"), manifest_ref["path"]):
        raise TypedEventAdapterV7Error("selected proof manifest path differs from registry manifest")
    if proof_doc.get("manifest_sha256") is not None and proof_doc.get("manifest_sha256") != manifest_ref["sha256"]:
        raise TypedEventAdapterV7Error("selected proof manifest SHA differs from registry manifest")
    proof_rows = proof_doc.get("case_verifications")
    if isinstance(proof_rows, list):
        matching_proof_rows = [item for item in proof_rows if isinstance(item, Mapping)
                               and item.get("physical_case_id") == case_id]
        if len(matching_proof_rows) != 1:
            raise TypedEventAdapterV7Error("selected proof does not contain exactly one requested case")
    expected_catalog = scope.get("current_catalog")
    if expected_catalog is not None:
        _ref_equal(plan_catalog, expected_catalog, "scope CURRENT catalog")
    plan_registry = plan.get("evidence_registry")
    # The scope uses file_sha256 while the v4 plan uses sha256.
    registry_path = scope["producer_registry"]["path"]
    registry_sha = scope["producer_registry"]["file_sha256"]
    _ref_equal(plan_registry, {"path": registry_path, "sha256": registry_sha}, "plan evidence registry")
    return {
        "case_id": case_id,
        "status": CURRENT_STATUS,
        "identity_admission": "CURRENT_EXACT_NO_HISTORICAL_ALIAS_SAVED_MASK_ONLY",
        "plan_attempt_id": attempt_id,
        "producer_id": producer.get("producer_id"),
        "failed_history_count": sum(1 for item in lineage if isinstance(item, Mapping)
                                     and item.get("status") != CURRENT_STATUS),
        "completed_producer_count": 1,
        "producer_request": request_ref,
        "producer_proof": proof_ref,
        "producer_manifest": manifest_ref,
        "current_catalog": current_ref,
        "source_join_status": SOURCE_JOIN,
        "source_closure": SOURCE_CLOSURE,
        "typed_label_admission": False,
        "scientific_credit": "NONE_PHYSICAL_SAVED_MASK_ONLY",
    }


def validate_current_identity_scope(request: Mapping[str, Any], *, require: bool) -> dict[str, Any]:
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or not isinstance(identity.get("physical_case_id"), str):
        raise TypedEventAdapterV7Error("request case identity is incomplete")
    case_id = str(identity["physical_case_id"])
    scope = request.get("lifecycle_scope")
    if scope is None:
        if require:
            raise TypedEventAdapterV7Error("known-role admission requires CURRENT v4 scope")
        return {"status": "UNKNOWN_NO_CURRENT_LIFECYCLE_SCOPE", "physical_case_id": case_id,
                "identity_admission": "UNKNOWN_NO_CURRENT_SCOPE", "typed_label_admission": False,
                "production_eligible": False}
    if not isinstance(scope, Mapping) or scope.get("physical_case_id") != case_id:
        raise TypedEventAdapterV7Error("CURRENT scope physical case differs")
    plan, plan_ref = _scope_ref(scope, "current_plan")
    registry, registry_ref = _scope_ref(scope, "producer_registry")
    joined = _validate_plan_registry_v7(plan, registry, scope, case_id)
    return {"status": "CURRENT_EXACT_SAVED_MASK_COMPLETED", "physical_case_id": case_id,
            "identity_admission": joined["identity_admission"], "typed_label_admission": False,
            "production_eligible": False, "plan": plan_ref, "producer_registry": registry_ref,
            "join": joined, "qualification": dict(UNKNOWN_QUALIFICATION)}


def _validate_v7_binding(request: Mapping[str, Any], *, require: bool = False) -> None:
    binding = request.get("v7_adapter_binding")
    if binding is None:
        if require:
            raise TypedEventAdapterV7Error("V7 adapter binding is required")
        return
    if not isinstance(binding, Mapping) or binding.get("adapter_schema") != ADAPTER_SCHEMA:
        raise TypedEventAdapterV7Error("V7 adapter binding schema is unsupported")
    script_path = binding.get("adapter_script_path")
    script_sha = binding.get("adapter_script_file_sha256")
    if script_path != str(SCRIPT_DIR / Path(__file__).name) or not isinstance(script_sha, str):
        raise TypedEventAdapterV7Error("V7 adapter script path/SHA is not current")
    if _file_sha(script_path) != script_sha:
        raise TypedEventAdapterV7Error("V7 adapter script SHA differs")
    source = binding.get("source_request")
    if not isinstance(source, Mapping):
        raise TypedEventAdapterV7Error("V7 source request binding is missing")
    source_path = source.get("path")
    source_sha = source.get("file_sha256")
    source_canonical = source.get("canonical_sha256")
    if not all(isinstance(item, str) for item in (source_path, source_sha, source_canonical)):
        raise TypedEventAdapterV7Error("V7 source request binding is incomplete")
    source_value = _read_json(source_path, role="V7 bound source request")
    if source_value.get("schema") != REQUEST_SCHEMA or _file_sha(source_path) != source_sha:
        raise TypedEventAdapterV7Error("V7 bound source request schema/file SHA differs")
    if source_value.get("request_sha256") != source_canonical:
        raise TypedEventAdapterV7Error("V7 bound source request canonical SHA differs")
    current = copy.deepcopy(dict(request))
    current.pop("request_sha256", None)
    current.pop("v7_adapter_binding", None)
    if canonical_sha(current) != canonical_sha(source_value):
        raise TypedEventAdapterV7Error("V7 request semantic fields differ from sealed source")


def validate_request_v7(request: Mapping[str, Any], *, allow_fixture: bool = False,
                        require_binding: bool = False) -> dict[str, Any]:
    try:
        context = _V4.validate_request_v4(request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV7Error(str(error)) from error
    _validate_v7_binding(request, require=require_binding)
    scope = validate_current_identity_scope(request, require=bool(context["all_roles_known"]))
    context = dict(context)
    context["current_identity_scope"] = scope
    context["production_eligible"] = False
    return context


def build_unknown_event_result_from_request(request: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    context = validate_request_v7(request, allow_fixture=allow_fixture)
    if context["all_roles_known"]:
        raise TypedEventAdapterV7Error("UNKNOWN result is not admissible when all roles are known")
    result = copy.deepcopy(_V4.build_unknown_event_result_from_request(request, allow_fixture=allow_fixture))
    result["schema"] = UNKNOWN_ADMISSION_SCHEMA
    result["status"] = "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE"
    result["current_identity_scope"] = context["current_identity_scope"]
    result["qualification"] = dict(UNKNOWN_QUALIFICATION)
    result.setdefault("adapter", {}).update({"schema": ADAPTER_SCHEMA,
        "status": "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE", "typed_content_required": False,
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "production_eligible": False})
    return result


def build_event_stream_from_request(typed_result: Mapping[str, Any] | None,
                                    request: Mapping[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    context = validate_request_v7(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        if typed_result is not None:
            raise TypedEventAdapterV7Error("typed mapping must not be supplied when a role is UNKNOWN")
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    try:
        result = copy.deepcopy(_V4.build_event_stream_from_request(typed_result, request, allow_fixture=allow_fixture))
    except Exception as error:
        raise TypedEventAdapterV7Error(str(error)) from error
    result.setdefault("adapter", {}).update({"schema": ADAPTER_SCHEMA,
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "production_eligible": False})
    result["current_identity_scope"] = context["current_identity_scope"]
    result["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = _read_json(args.request, role="V7 request")
        context = validate_request_v7(request, allow_fixture=args.allow_fixture)
        print(json.dumps({"schema": ADAPTER_SCHEMA, "status": "READY_FOR_PARENT_GUARDED_MAPPING",
                          "case_identity": context["case_identity"],
                          "current_identity_scope": context["current_identity_scope"],
                          "production_eligible": False}, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV7Error) as error:
        print(f"typed event adapter v7: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
