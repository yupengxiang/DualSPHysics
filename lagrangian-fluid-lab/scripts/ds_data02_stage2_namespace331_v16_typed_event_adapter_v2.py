#!/usr/bin/env python3
"""Admit and consume a V3 hash-bound typed-event request.

This is the executable interface after :mod:`namespace331_role_proof_loader_v3`.
The request preflight is metadata-only.  ``build_event_stream_from_request``
accepts a typed result mapping only after an outer parent has reserved and
verified the deferred result; it delegates identity, mass, Zone/Idp, target
region, event ordering and censoring checks to the existing strict V2 event
consumer.  No model or CFD is invoked.

The command-line ``convert`` path is intentionally bounded to the small JSON
fixture limit.  A production typed result larger than that must be supplied to
the mapping API by the parent guard after its content hash/stat checks; this
module never opens H5/BI4/raw data or falls back to an original path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_V3 = _load("namespace331_role_proof_loader_v3_for_adapter_v2",
            SCRIPT_DIR / "ds_data02_stage2_namespace331_role_proof_loader_v3.py")
_V1 = _load("namespace331_typed_event_adapter_v1_for_adapter_v2",
            SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v1.py")


ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v2"
REQUEST_SCHEMA = _V3.REQUEST_SCHEMA
EVENT_SCHEMA = _V1.EVENT_SCHEMA
MAX_TYPED_JSON_BYTES = int(_V1.MAX_METADATA_BYTES)
REQUIRED_ROLES = tuple(_V3.REQUIRED_ROLES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class TypedEventAdapterV2Error(ValueError):
    """Request, deferred result, or source binding is not admissible."""


def _sha(value: Any, name: str) -> str:
    try:
        return _V3._sha(value, name)
    except Exception as error:
        raise TypedEventAdapterV2Error(str(error)) from error


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V3.canonical_sha(value)


def _read_request(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > _V3.MAX_ARTIFACT_BYTES:
        raise TypedEventAdapterV2Error("request must be a bounded regular non-symlink JSON file")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterV2Error(str(error)) from error
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV2Error("request must be a JSON object")
    return dict(value)


def _request_roles(request: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    raw = request.get("role_proof_artifacts")
    if not isinstance(raw, list):
        raise TypedEventAdapterV2Error("request role_proof_artifacts is required")
    by_role: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypedEventAdapterV2Error("role proof entry is not an object")
        role = item.get("requested_role")
        if role not in REQUIRED_ROLES or role in by_role:
            raise TypedEventAdapterV2Error("request has missing or duplicate requested role")
        if not isinstance(item.get("artifact_path"), str) or not item["artifact_path"]:
            raise TypedEventAdapterV2Error(f"role {role} lacks an artifact path")
        if item.get("artifact_sha256") is None:
            raise TypedEventAdapterV2Error(f"role {role} lacks artifact SHA")
        _sha(item.get("artifact_sha256"), f"role {role} artifact_sha256")
        if item.get("status") not in {"KNOWN", "UNKNOWN"}:
            raise TypedEventAdapterV2Error(f"role {role} has unsupported status")
        reasons = item.get("unknown_reasons")
        if reasons is not None and (not isinstance(reasons, list) or
                                    any(not isinstance(reason, str) or not reason for reason in reasons)):
            raise TypedEventAdapterV2Error(f"role {role} has malformed unknown_reasons")
        if item.get("status") == "KNOWN":
            if item.get("derived_semantic_role") != role:
                raise TypedEventAdapterV2Error(f"known role {role} has mismatched semantic role")
            if not isinstance(item.get("artifact_schema"), str) or not item["artifact_schema"]:
                raise TypedEventAdapterV2Error(f"known role {role} lacks artifact schema")
            if not isinstance(item.get("proof_status"), str) or item["proof_status"].upper() not in {
                "VERIFIED", "SOURCE_BOUND", "PASS", "COMPLETED"
            }:
                raise TypedEventAdapterV2Error(f"known role {role} lacks a verified proof status")
            if reasons:
                raise TypedEventAdapterV2Error(f"known role {role} carries unknown reasons")
        elif not reasons:
            raise TypedEventAdapterV2Error(f"unknown role {role} lacks an explicit reason")
        by_role[str(role)] = dict(item)
    missing = set(REQUIRED_ROLES) - set(by_role)
    if missing:
        raise TypedEventAdapterV2Error(f"request lacks roles: {', '.join(sorted(missing))}")
    return by_role, str(request.get("status"))


def validate_request_v3(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the small V3 request without reading the deferred typed file."""
    if not isinstance(request, Mapping) or request.get("schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV2Error(f"request schema must be {REQUEST_SCHEMA}")
    if request.get("request_sha256") != canonical_sha(request):
        raise TypedEventAdapterV2Error("request canonical SHA mismatch")
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or not isinstance(identity.get("family_id"), str) \
            or not isinstance(identity.get("physical_case_id"), str):
        raise TypedEventAdapterV2Error("request case_identity is incomplete")
    typed = request.get("typed_result")
    current = request.get("current_binding")
    if not isinstance(typed, Mapping) or not isinstance(current, Mapping):
        raise TypedEventAdapterV2Error("request typed_result/current_binding is incomplete")
    _sha(typed.get("sha256"), "typed_result.sha256")
    _sha(current.get("sha256"), "current_binding.sha256")
    if not str(typed.get("content_policy", "")).startswith("PARENT_GUARD"):
        raise TypedEventAdapterV2Error("typed result is not deferred to parent guard")
    contract = request.get("event_contract")
    if not isinstance(contract, Mapping) or not isinstance(contract.get("source_region"), str) \
            or not isinstance(contract.get("target_region"), str):
        raise TypedEventAdapterV2Error("request event contract is incomplete")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("parent_supervision_required") is not True \
            or execution.get("model_invoked") is not False:
        raise TypedEventAdapterV2Error("request lacks parent supervision/model boundary")
    roles, declared_status = _request_roles(request)
    if declared_status not in {"READY_FOR_PARENT_GUARD_ROLE_PROOFS", "ROLE_PROOF_METADATA_PARTIAL_UNKNOWN"}:
        raise TypedEventAdapterV2Error("request status is not an admissible V3 role-proof status")
    all_known = all(item.get("status") == "KNOWN" for item in roles.values())
    return {
        "schema": REQUEST_SCHEMA,
        "case_identity": {"family_id": identity["family_id"],
                           "physical_case_id": identity["physical_case_id"]},
        "typed_result": dict(typed), "current_binding": dict(current),
        "event_contract": dict(contract), "execution": dict(execution),
        "roles": roles, "declared_status": declared_status,
        "all_roles_known": all_known,
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _source_bindings(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for role in REQUIRED_ROLES:
        item = context["roles"][role]
        known = item.get("status") == "KNOWN" and not item.get("unknown_reasons")
        binding: dict[str, Any] = {
            "role": role,
            "semantic_role": role,
            "path": item.get("artifact_path"),
            "sha256": item.get("artifact_sha256"),
            "observed_sha256": item.get("artifact_sha256") if known else None,
            "content_verified": bool(known),
            "hash_verified_after_reservation": bool(known),
            "content_policy": "V3_ROLE_PROOF_BOUNDED_METADATA",
        }
        if known:
            binding["role_attestation"] = {
                "semantic_role": role,
                "content_schema": item.get("artifact_schema"),
                "proof_status": item.get("proof_status") or "SOURCE_BOUND",
                "content_sha256": item.get("artifact_sha256"),
            }
        bindings.append(binding)
    return bindings


def build_event_stream_from_request(
    typed_result: Mapping[str, Any], request: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert a parent-guarded typed mapping through the strict V1/V2 path."""
    context = validate_request_v3(request)
    if not isinstance(typed_result, Mapping):
        raise TypedEventAdapterV2Error("guarded typed result must be a JSON object")
    contract = context["event_contract"]
    try:
        document = _V1.build_event_stream_from_v16(
            typed_result,
            current_binding=context["current_binding"],
            source_bindings=_source_bindings(context),
            source_region=contract["source_region"],
            target_region=contract["target_region"],
        )
    except Exception as error:
        raise TypedEventAdapterV2Error(str(error)) from error
    document = copy.deepcopy(document)
    document["adapter"]["schema"] = ADAPTER_SCHEMA
    document["adapter"]["request_schema"] = REQUEST_SCHEMA
    document["adapter"]["request_sha256"] = request["request_sha256"]
    document["adapter"]["parent_guard_content_boundary"] = "GUARDED_TYPED_MAPPING"
    document["adapter"]["event_credit"] = (
        "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN"
    )
    document["adapter"]["fixture_role_proof_credit"] = any(
        item.get("producer_source_closure", {}).get("credit_boundary") == "MANUFACTURED_FIXTURE_ONLY"
        for item in context["roles"].values() if isinstance(item.get("producer_source_closure"), Mapping)
    )
    document["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return document


def convert_bounded_json(request: Mapping[str, Any], typed_path: Path | str) -> dict[str, Any]:
    """Small-fixture CLI path; production uses the guarded mapping API above."""
    target = Path(typed_path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_TYPED_JSON_BYTES:
        raise TypedEventAdapterV2Error("CLI typed JSON is missing, symlinked, or exceeds bounded fixture limit")
    try:
        typed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterV2Error(str(error)) from error
    return build_event_stream_from_request(typed, request)


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV2Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-request")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    convert = sub.add_parser("convert")
    convert.add_argument("--request", type=Path, required=True)
    convert.add_argument("--typed-result", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = _read_request(args.request)
        if args.command == "validate-request":
            context = validate_request_v3(request)
            result = {"schema": "ds02.stage2.namespace331.v16-typed-event-admission.v2",
                      "status": "READY_FOR_PARENT_GUARDED_TYPED_MAPPING",
                      "request_sha256": request["request_sha256"],
                      "case_identity": context["case_identity"],
                      "all_roles_known": context["all_roles_known"],
                      "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
                      "qualification": dict(UNKNOWN_QUALIFICATION),
                      "typed_content_read": False}
            if args.output:
                _write_json(args.output, result)
            print(json.dumps(result, sort_keys=True))
        else:
            document = convert_bounded_json(request, args.typed_result)
            _write_json(args.output, document)
            print(json.dumps({"output": str(args.output), "schema": document["schema"],
                              "status": document["adapter"]["status"],
                              "event_credit": document["adapter"]["event_credit"]}, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV2Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
