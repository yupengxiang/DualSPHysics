#!/usr/bin/env python3
"""CURRENT v4 lifecycle-bound typed-event admission.

This is a forward-only successor to the consumed v5 adapter.  The v5
adapter accepted a generic stage2 plan and a generic producer registry.  The
actual lifecycle products are stricter: the plan and registry have v4
schemas, both point at the same CURRENT336 catalog, and a saved-mask row is
only useful when its producer attempt is joined to a completed registry
producer.  This module performs that bounded metadata join.  It grants no
event, qualification, or physical credit; missing source/region/control
roles still produce the normal UNKNOWN short circuit.
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


_V5 = _load(
    "namespace331_v16_typed_event_adapter_v5_for_adapter_v6",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v5.py",
)
_V4 = _V5._V4

ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v6"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v6"
REQUEST_SCHEMA = _V4.REQUEST_SCHEMA
MAX_ARTIFACT_BYTES = int(_V4.MAX_ARTIFACT_BYTES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v4"
CURRENT_STATUS = "ACTUAL_SAVED_MASK_COMPLETED"
SOURCE_JOIN = "EXACT_CURRENT_AUDIT_METADATA_JOIN"
SOURCE_CLOSURE = "COMPLETED_H5_PREPOST_SHA_AND_STAT_EQUAL"


class TypedEventAdapterV6Error(ValueError):
    """Request or lifecycle metadata is not admissible."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V4.canonical_sha(value)


def _read_json(path: Path | str, *, role: str) -> dict[str, Any]:
    try:
        return _V4._read_json(path, role=role)
    except Exception as error:
        raise TypedEventAdapterV6Error(str(error)) from error


def _file_sha(path: Path | str) -> str:
    try:
        return _V4._file_sha(Path(path))
    except Exception as error:
        raise TypedEventAdapterV6Error(str(error)) from error


def _path(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise TypedEventAdapterV6Error(f"{role} path is missing")
    return Path(value).expanduser()


def _same_path(left: Any, right: Any) -> bool:
    try:
        return _path(left, "left").resolve() == _path(right, "right").resolve()
    except TypedEventAdapterV6Error:
        return False


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise TypedEventAdapterV6Error(f"{role} must be a SHA-256 string")
    try:
        int(value, 16)
    except ValueError as error:
        raise TypedEventAdapterV6Error(f"{role} is not hexadecimal") from error
    return value


def _metadata_ref(value: Any, *, role: str, keys: tuple[str, ...] = ("path", "sha256")) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV6Error(f"{role} reference is malformed")
    path_key, sha_key = keys
    path = _path(value.get(path_key), f"{role}.{path_key}")
    declared = _sha(value.get(sha_key), f"{role}.{sha_key}")
    document = _read_json(path, role=role)
    observed = _file_sha(path)
    if observed != declared:
        raise TypedEventAdapterV6Error(f"{role} SHA differs from its bound metadata")
    return document, {"path": str(path.resolve()), "sha256": observed}


def _scope_ref(scope: Mapping[str, Any], key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = scope.get(key)
    if not isinstance(ref, Mapping):
        raise TypedEventAdapterV6Error(f"CURRENT scope {key} binding is missing")
    path = _path(ref.get("path"), f"CURRENT scope {key}")
    declared = _sha(ref.get("file_sha256"), f"CURRENT scope {key}.file_sha256")
    value = _read_json(path, role=f"CURRENT scope {key}")
    observed = _file_sha(path)
    if observed != declared:
        raise TypedEventAdapterV6Error(f"CURRENT scope {key} file SHA differs")
    return value, {"path": str(path.resolve()), "file_sha256": observed, "schema": value.get("schema")}


def _require_exact_ref(left: Any, right: Any, role: str) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise TypedEventAdapterV6Error(f"{role} reference is missing")
    if not _same_path(left.get("path"), right.get("path")):
        raise TypedEventAdapterV6Error(f"{role} paths differ")
    left_sha = left.get("sha256", left.get("file_sha256"))
    right_sha = right.get("sha256", right.get("file_sha256"))
    if not isinstance(left_sha, str) or not isinstance(right_sha, str) or left_sha != right_sha:
        raise TypedEventAdapterV6Error(f"{role} SHAs differ")


def _rows(document: Mapping[str, Any], key: str, role: str) -> list[Mapping[str, Any]]:
    rows = document.get(key)
    if not isinstance(rows, list) or not rows:
        raise TypedEventAdapterV6Error(f"{role} lacks explicit {key} rows")
    if not all(isinstance(row, Mapping) for row in rows):
        raise TypedEventAdapterV6Error(f"{role} has malformed {key} rows")
    return [row for row in rows if isinstance(row, Mapping)]


def _producer_ref(producer: Mapping[str, Any], key: str, *, role: str) -> dict[str, Any]:
    value = producer.get(key)
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV6Error(f"{role} producer lacks {key} reference")
    # Request, proof, and the producer manifest are small JSON metadata.  The
    # content is checked once here; payloads are never followed by this gate.
    _, bound = _metadata_ref(value, role=f"{role}.{key}")
    return bound


def _validate_plan_registry(
    plan: Mapping[str, Any], plan_ref: Mapping[str, Any],
    registry: Mapping[str, Any], registry_ref: Mapping[str, Any],
    scope: Mapping[str, Any], case_id: str,
) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise TypedEventAdapterV6Error("CURRENT plan schema is not typed-lifecycle-continuation-plan.v4")
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise TypedEventAdapterV6Error("producer registry schema is not typed-lifecycle-evidence-registry.v4")
    plan_catalog = plan.get("current_catalog")
    registry_catalog = registry.get("current")
    _require_exact_ref(plan_catalog, registry_catalog, "CURRENT catalog")
    current, current_ref = _metadata_ref(plan_catalog, role="CURRENT336 catalog")
    if not isinstance(current, Mapping):  # defensive; _read_json already returns a mapping
        raise TypedEventAdapterV6Error("CURRENT336 catalog is malformed")
    expected_catalog = scope.get("current_catalog")
    if expected_catalog is not None:
        _require_exact_ref(plan_catalog, expected_catalog, "scope CURRENT catalog")
    plan_registry = plan.get("evidence_registry")
    # The plan uses sha256 while lifecycle_scope uses file_sha256.
    _require_exact_ref(
        plan_registry,
        {"path": registry_ref["path"], "sha256": registry_ref["file_sha256"]},
        "plan evidence registry",
    )
    rows = _rows(plan, "case_records", "CURRENT plan")
    matches = [row for row in rows if row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise TypedEventAdapterV6Error("CURRENT plan does not contain exactly one requested case")
    row = matches[0]
    for field, expected in (
        ("historical_alias", "NONE"),
        ("actual_saved_mask_coverage", True),
        ("source_join_status", SOURCE_JOIN),
        ("status", CURRENT_STATUS),
    ):
        if row.get(field) != expected:
            raise TypedEventAdapterV6Error(f"CURRENT plan {case_id} {field} is not {expected}")
    evidence = row.get("producer_evidence")
    if not isinstance(evidence, Mapping):
        raise TypedEventAdapterV6Error(f"CURRENT plan {case_id} lacks producer_evidence")
    if evidence.get("status") != CURRENT_STATUS:
        raise TypedEventAdapterV6Error(f"CURRENT producer evidence {case_id} status differs")
    if evidence.get("reported_status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise TypedEventAdapterV6Error(f"CURRENT producer evidence {case_id} is not diagnostic-only")
    if evidence.get("source_closure") != SOURCE_CLOSURE:
        raise TypedEventAdapterV6Error(f"CURRENT producer evidence {case_id} lacks complete source closure")
    attempt_id = evidence.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise TypedEventAdapterV6Error(f"CURRENT producer evidence {case_id} lacks attempt_id")
    lineage = row.get("attempt_lineage")
    if not isinstance(lineage, list) or len(lineage) != 1 or not isinstance(lineage[0], Mapping):
        raise TypedEventAdapterV6Error(f"CURRENT plan {case_id} has ambiguous attempt lineage")
    line = lineage[0]
    if line.get("attempt_id") != attempt_id or line.get("status") != CURRENT_STATUS:
        raise TypedEventAdapterV6Error(f"CURRENT plan {case_id} attempt lineage differs")
    producers = _rows(registry, "producers", "producer registry")
    matched = [producer for producer in producers if case_id in producer.get("case_ids", [])]
    if len(matched) != 1:
        raise TypedEventAdapterV6Error(f"producer registry has {len(matched)} matches for {case_id}")
    producer = matched[0]
    if producer.get("status") != "COMPLETED":
        raise TypedEventAdapterV6Error(f"producer registry {case_id} is not COMPLETED")
    # Registry v4 intentionally carries the producer identity and its
    # request/proof refs, while the per-case plan row carries the exact
    # attempt id.  Join those two pieces through producer_id; requiring a
    # non-existent registry ``attempt_id`` would reject the real v4 registry.
    if producer.get("producer_id") != line.get("producer_id"):
        raise TypedEventAdapterV6Error(f"producer registry {case_id} producer_id differs")
    producer_refs = {key: _producer_ref(producer, key, role=case_id) for key in ("request", "proof", "manifest")}
    # A plan case manifest is a per-case document and the registry manifest is
    # the batch document.  They are deliberately different references; both
    # must nevertheless remain bounded, present, and hash-bound.
    for key in ("case_manifest", "case_receipt", "summary"):
        if key in evidence:
            _metadata_ref(evidence[key], role=f"{case_id}.producer_evidence.{key}")
    return {
        "case_id": case_id,
        "status": CURRENT_STATUS,
        "historical_alias": "NONE",
        "source_join_status": SOURCE_JOIN,
        "source_closure": SOURCE_CLOSURE,
        "attempt_id": attempt_id,
        "producer_id": producer.get("producer_id"),
        "producer_registry_status": producer.get("status"),
        "producer_metadata_refs": producer_refs,
        "current_catalog": current_ref,
        "scientific_credit": "NONE_PHYSICAL_SAVED_MASK_ONLY",
    }


def validate_current_identity_scope(request: Mapping[str, Any], *, require: bool) -> dict[str, Any]:
    identity = request.get("case_identity")
    if not isinstance(identity, Mapping) or not isinstance(identity.get("physical_case_id"), str):
        raise TypedEventAdapterV6Error("request case identity is incomplete")
    case_id = str(identity["physical_case_id"])
    scope = request.get("lifecycle_scope")
    if scope is None:
        if require:
            raise TypedEventAdapterV6Error("known-role admission requires a v4 CURRENT lifecycle scope")
        return {
            "status": "UNKNOWN_NO_CURRENT_LIFECYCLE_SCOPE",
            "physical_case_id": case_id,
            "identity_admission": "UNKNOWN_NO_CURRENT_SCOPE",
            "typed_label_admission": False,
            "production_eligible": False,
        }
    if not isinstance(scope, Mapping) or scope.get("physical_case_id") != case_id:
        raise TypedEventAdapterV6Error("CURRENT lifecycle scope case differs")
    plan, plan_ref = _scope_ref(scope, "current_plan")
    registry, registry_ref = _scope_ref(scope, "producer_registry")
    joined = _validate_plan_registry(plan, plan_ref, registry, registry_ref, scope, case_id)
    return {
        "status": "CURRENT_EXACT_SAVED_MASK_COMPLETED",
        "physical_case_id": case_id,
        "identity_admission": "CURRENT_EXACT_NO_HISTORICAL_ALIAS_SAVED_MASK_ONLY",
        "typed_label_admission": False,
        "production_eligible": False,
        "plan": plan_ref,
        "producer_registry": registry_ref,
        "join": joined,
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _validate_v6_binding(request: Mapping[str, Any], *, require: bool = False) -> None:
    binding = request.get("v6_adapter_binding")
    if binding is None:
        if require:
            raise TypedEventAdapterV6Error("V6 adapter binding is required")
        return
    if not isinstance(binding, Mapping) or binding.get("adapter_schema") != ADAPTER_SCHEMA:
        raise TypedEventAdapterV6Error("V6 adapter binding schema is unsupported")
    script_path = binding.get("adapter_script_path")
    script_sha = binding.get("adapter_script_file_sha256")
    if script_path != str(SCRIPT_DIR / Path(__file__).name) or not isinstance(script_sha, str):
        raise TypedEventAdapterV6Error("V6 adapter script path/SHA is not current")
    if _file_sha(script_path) != script_sha:
        raise TypedEventAdapterV6Error("V6 adapter script SHA differs")
    source = binding.get("source_request")
    if not isinstance(source, Mapping):
        raise TypedEventAdapterV6Error("V6 source request binding is missing")
    source_path = source.get("path")
    source_sha = source.get("file_sha256")
    source_canonical = source.get("canonical_sha256")
    if not all(isinstance(item, str) for item in (source_path, source_sha, source_canonical)):
        raise TypedEventAdapterV6Error("V6 source request binding lacks path/file/canonical SHA")
    source_value = _read_json(source_path, role="V6 bound source request")
    if source_value.get("schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV6Error("V6 bound source request schema differs")
    if _file_sha(source_path) != source_sha or source_value.get("request_sha256") != source_canonical:
        raise TypedEventAdapterV6Error("V6 bound source request SHA differs")
    current = copy.deepcopy(dict(request))
    current.pop("request_sha256", None)
    current.pop("v6_adapter_binding", None)
    if canonical_sha(current) != canonical_sha(source_value):
        raise TypedEventAdapterV6Error("V6 request semantic fields differ from sealed source request")


def validate_request_v6(
    request: Mapping[str, Any], *, allow_fixture: bool = False, require_binding: bool = False,
) -> dict[str, Any]:
    try:
        context = _V4.validate_request_v4(request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV6Error(str(error)) from error
    _validate_v6_binding(request, require=require_binding)
    scope = validate_current_identity_scope(request, require=bool(context["all_roles_known"]))
    context = dict(context)
    context["current_identity_scope"] = scope
    # The lifecycle join is identity/saved-mask metadata only.  It never
    # upgrades event roles or qualification, including for fixture roles.
    context["production_eligible"] = False
    return context


def build_unknown_event_result_from_request(
    request: Mapping[str, Any], *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v6(request, allow_fixture=allow_fixture)
    if context["all_roles_known"]:
        raise TypedEventAdapterV6Error("UNKNOWN result is not admissible when all roles are known")
    result = _V4.build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    result = copy.deepcopy(result)
    result["schema"] = UNKNOWN_ADMISSION_SCHEMA
    result["status"] = "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE"
    result["current_identity_scope"] = context["current_identity_scope"]
    result["qualification"] = dict(UNKNOWN_QUALIFICATION)
    adapter = result.setdefault("adapter", {})
    adapter.update({
        "schema": ADAPTER_SCHEMA,
        "status": "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE",
        "typed_content_required": False,
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "production_eligible": False,
    })
    return result


def build_event_stream_from_request(
    typed_result: Mapping[str, Any] | None,
    request: Mapping[str, Any],
    *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v6(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        if typed_result is not None:
            raise TypedEventAdapterV6Error("typed mapping must not be supplied when a role is UNKNOWN")
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    try:
        result = _V4.build_event_stream_from_request(typed_result, request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV6Error(str(error)) from error
    result = copy.deepcopy(result)
    result.setdefault("adapter", {}).update({
        "schema": ADAPTER_SCHEMA,
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "production_eligible": False,
    })
    result["current_identity_scope"] = context["current_identity_scope"]
    result["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return result


def bind_request(source_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source = _read_json(source_request_path, role="V6 source request")
    context = validate_request_v6(source)
    target = Path(output_path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV6Error(f"refusing to overwrite: {target}")
    source_path = Path(source_request_path).expanduser().resolve()
    bound = copy.deepcopy(source)
    bound["v6_adapter_binding"] = {
        "adapter_schema": ADAPTER_SCHEMA,
        "adapter_script_path": str(SCRIPT_DIR / Path(__file__).name),
        "adapter_script_file_sha256": _file_sha(SCRIPT_DIR / Path(__file__).name),
        "source_request": {
            "path": str(source_path),
            "file_sha256": _file_sha(source_path),
            "canonical_sha256": source["request_sha256"],
            "request_schema": REQUEST_SCHEMA,
        },
        "content_policy": "SMALL_REQUEST_AND_V4_LIFECYCLE_METADATA_ONLY; TYPED_CONTENT_DEFERRED",
        "identity_admission": context["current_identity_scope"]["identity_admission"],
    }
    bound["request_sha256"] = canonical_sha(bound)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema": bound["schema"],
        "adapter_schema": ADAPTER_SCHEMA,
        "request_path": str(target),
        "request_sha256": bound["request_sha256"],
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "typed_content_required": bool(context["all_roles_known"]),
        "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "NONE_PHYSICAL_SAVED_MASK_ONLY",
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV6Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind-request")
    bind.add_argument("--source-request", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate-request")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--allow-fixture", action="store_true")
    convert = sub.add_parser("convert")
    convert.add_argument("--request", type=Path, required=True)
    convert.add_argument("--typed-result", type=Path)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = _read_json(args.request, role="V6 request") if args.command != "bind-request" else None
        if args.command == "bind-request":
            result = bind_request(args.source_request, args.output)
        elif args.command == "validate-request":
            context = validate_request_v6(request, allow_fixture=args.allow_fixture, require_binding=True)
            result = {
                "schema": ADAPTER_SCHEMA,
                "status": "READY_FOR_PARENT_GUARDED_TYPED_MAPPING",
                "request_sha256": request["request_sha256"],
                "case_identity": context["case_identity"],
                "all_roles_known": context["all_roles_known"],
                "current_identity_scope": context["current_identity_scope"],
                "production_eligible": False,
                "typed_content_required": context["all_roles_known"],
                "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "NONE_PHYSICAL_SAVED_MASK_ONLY",
                "qualification": dict(UNKNOWN_QUALIFICATION),
                "typed_content_read": False,
            }
            if args.output:
                _write_json(args.output, result)
        else:
            document = build_event_stream_from_request(None, request, allow_fixture=args.allow_fixture)
            _write_json(args.output, document)
            result = {"output": str(args.output), "schema": document["schema"], "status": document["adapter"]["status"]}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV6Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
