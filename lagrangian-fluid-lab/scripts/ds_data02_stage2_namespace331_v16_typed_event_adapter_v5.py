#!/usr/bin/env python3
"""CURRENT-bound typed-event admission with a strict identity scope.

This is additive to the consumed V4 adapter.  A request whose producer roles
are UNKNOWN still short-circuits to the V4 all-UNKNOWN result and does not
open the deferred typed product.  A request that would consume typed labels
must additionally bind a bounded CURRENT lifecycle plan and producer
registry.  The exact case row must be saved, joined to CURRENT, and have no
historical alias.  A canonical-looking string or a caller supplied role
proof cannot substitute for that scope.
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


_V4 = _load(
    "namespace331_v16_typed_event_adapter_v4_for_adapter_v5",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v4.py",
)

ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v5"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v5"
REQUEST_SCHEMA = _V4.REQUEST_SCHEMA
MAX_ARTIFACT_BYTES = int(_V4.MAX_ARTIFACT_BYTES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class TypedEventAdapterV5Error(ValueError):
    """Request or CURRENT identity scope is not admissible."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V4.canonical_sha(value)


def _read_json(path: Path | str, *, role: str) -> dict[str, Any]:
    try:
        return _V4._read_json(path, role=role)
    except Exception as error:
        raise TypedEventAdapterV5Error(str(error)) from error


def _file_sha(path: Path | str) -> str:
    try:
        return _V4._file_sha(Path(path))
    except Exception as error:
        raise TypedEventAdapterV5Error(str(error)) from error


def _validate_v5_binding(request: Mapping[str, Any], *, require: bool = False) -> None:
    binding = request.get("v5_adapter_binding")
    if binding is None:
        if require:
            raise TypedEventAdapterV5Error("V5 adapter binding is required")
        return
    if not isinstance(binding, Mapping) or binding.get("adapter_schema") != ADAPTER_SCHEMA:
        raise TypedEventAdapterV5Error("V5 adapter binding schema is unsupported")
    script_path = binding.get("adapter_script_path")
    script_sha = binding.get("adapter_script_file_sha256")
    if script_path != str(SCRIPT_DIR / Path(__file__).name) or not isinstance(script_sha, str):
        raise TypedEventAdapterV5Error("V5 adapter script path/SHA is not current")
    if _file_sha(script_path) != script_sha:
        raise TypedEventAdapterV5Error("V5 adapter script SHA differs")
    source = binding.get("source_request")
    if not isinstance(source, Mapping):
        raise TypedEventAdapterV5Error("V5 source request binding is missing")
    source_path = source.get("path")
    source_sha = source.get("file_sha256")
    source_canonical = source.get("canonical_sha256")
    if not all(isinstance(value, str) for value in (source_path, source_sha, source_canonical)):
        raise TypedEventAdapterV5Error("V5 source request binding lacks path/file/canonical SHA")
    source_value = _read_json(source_path, role="V5 bound source request")
    if source_value.get("schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV5Error("V5 bound source request schema differs")
    if _file_sha(source_path) != source_sha:
        raise TypedEventAdapterV5Error("V5 bound source request file SHA differs")
    if source_value.get("request_sha256") != source_canonical:
        raise TypedEventAdapterV5Error("V5 bound source request canonical SHA differs")
    current = copy.deepcopy(dict(request))
    current.pop("request_sha256", None)
    current.pop("v5_adapter_binding", None)
    if canonical_sha(current) != canonical_sha(source_value):
        raise TypedEventAdapterV5Error("V5 request semantic fields differ from sealed source request")


def _scope_ref(scope: Mapping[str, Any], key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = scope.get(key)
    if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("file_sha256"), str):
        raise TypedEventAdapterV5Error(f"CURRENT scope {key} binding lacks path/file SHA")
    path = Path(ref["path"]).expanduser()
    value = _read_json(path, role=f"CURRENT scope {key}")
    observed = _file_sha(path)
    if observed != ref["file_sha256"]:
        raise TypedEventAdapterV5Error(f"CURRENT scope {key} file SHA differs")
    schema = value.get("schema")
    if not isinstance(schema, str) or not schema.startswith("ds02.stage2."):
        raise TypedEventAdapterV5Error(f"CURRENT scope {key} schema is not a bound stage2 metadata schema")
    return value, {"path": str(path.resolve()), "file_sha256": observed, "schema": schema}


def _rows(document: Mapping[str, Any], key: str, role: str) -> list[Mapping[str, Any]]:
    rows = document.get(key)
    if not isinstance(rows, list) or not rows:
        raise TypedEventAdapterV5Error(f"CURRENT scope {role} lacks explicit {key} rows")
    result: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypedEventAdapterV5Error(f"CURRENT scope {role} has malformed {key} row")
        result.append(row)
    return result


def validate_current_identity_scope(
    request: Mapping[str, Any], *, require: bool,
) -> dict[str, Any]:
    """Validate strict CURRENT coverage for a request's exact case.

    The scope is intentionally explicit and small: it contains a plan and a
    producer registry reference.  We do not search arbitrary nested metadata
    or infer identity from a source string.
    """
    context_identity = request.get("case_identity")
    if not isinstance(context_identity, Mapping) or not isinstance(context_identity.get("physical_case_id"), str):
        raise TypedEventAdapterV5Error("request case identity is incomplete")
    case_id = str(context_identity["physical_case_id"])
    scope = request.get("lifecycle_scope")
    if scope is None:
        if require:
            raise TypedEventAdapterV5Error("known-role admission requires a strict CURRENT lifecycle scope")
        return {
            "status": "UNKNOWN_NO_CURRENT_LIFECYCLE_SCOPE",
            "physical_case_id": case_id,
            "identity_admission": "UNKNOWN_NO_CURRENT_SCOPE",
            "typed_label_admission": False,
        }
    if not isinstance(scope, Mapping):
        raise TypedEventAdapterV5Error("CURRENT lifecycle scope is malformed")
    if scope.get("physical_case_id") != case_id:
        raise TypedEventAdapterV5Error("CURRENT lifecycle scope case differs")
    plan, plan_ref = _scope_ref(scope, "current_plan")
    registry, registry_ref = _scope_ref(scope, "producer_registry")
    plan_rows = _rows(plan, "case_records", "current plan")
    matches = [row for row in plan_rows if row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise TypedEventAdapterV5Error("CURRENT plan does not contain exactly one requested case")
    row = matches[0]
    if row.get("historical_alias") != "NONE":
        raise TypedEventAdapterV5Error("historical alias is not admissible for typed labels")
    if row.get("actual_saved_mask_coverage") is not True:
        raise TypedEventAdapterV5Error("requested case is not actually covered by CURRENT")
    if row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
        raise TypedEventAdapterV5Error("requested case lacks exact CURRENT audit join")
    if row.get("canonical_case_id", case_id) != case_id:
        raise TypedEventAdapterV5Error("CURRENT canonical case identity differs")
    if row.get("status") not in {"COMPLETED", "COMPLETED_ACTUAL", "ACTUAL_COVERED"}:
        raise TypedEventAdapterV5Error("CURRENT case is not in a completed saved state")

    producers = _rows(registry, "producers", "producer registry")
    completed: list[Mapping[str, Any]] = []
    for producer in producers:
        case_ids = producer.get("case_ids")
        if not isinstance(case_ids, list):
            raise TypedEventAdapterV5Error("producer registry row lacks case_ids")
        if case_id in case_ids and producer.get("status") == "COMPLETED":
            completed.append(producer)
    if len(completed) != 1:
        raise TypedEventAdapterV5Error("CURRENT case does not have exactly one completed producer")
    expected = scope.get("expected")
    if expected is not None:
        if not isinstance(expected, Mapping):
            raise TypedEventAdapterV5Error("CURRENT scope expected fields are malformed")
        for key in ("historical_alias", "actual_saved_mask_coverage", "source_join_status", "status"):
            if key in expected and expected[key] != row.get(key):
                raise TypedEventAdapterV5Error(f"CURRENT scope expected {key} differs")
    return {
        "status": "CURRENT_EXACT_COVERAGE",
        "physical_case_id": case_id,
        "identity_admission": "CURRENT_EXACT_NO_HISTORICAL_ALIAS",
        "typed_label_admission": True,
        "plan": plan_ref,
        "producer_registry": registry_ref,
        "producer_id": completed[0].get("producer_id"),
        "plan_row_status": row.get("status"),
        "historical_alias": row.get("historical_alias"),
        "actual_saved_mask_coverage": row.get("actual_saved_mask_coverage"),
        "source_join_status": row.get("source_join_status"),
    }


def validate_request_v5(
    request: Mapping[str, Any], *, allow_fixture: bool = False, require_binding: bool = False,
) -> dict[str, Any]:
    try:
        context = _V4.validate_request_v4(request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV5Error(str(error)) from error
    _validate_v5_binding(request, require=require_binding)
    scope = validate_current_identity_scope(request, require=bool(context["all_roles_known"]))
    context = dict(context)
    context["current_identity_scope"] = scope
    # A fixture role proof is never production-eligible even with a valid
    # lifecycle row.  The scope only proves identity, not scientific quality.
    if context.get("fixture_roles"):
        context["production_eligible"] = False
    return context


def build_unknown_event_result_from_request(
    request: Mapping[str, Any], *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v5(request, allow_fixture=allow_fixture)
    if context["all_roles_known"]:
        raise TypedEventAdapterV5Error("UNKNOWN result is not admissible when all roles are known")
    result = _V4.build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    result = copy.deepcopy(result)
    result["schema"] = UNKNOWN_ADMISSION_SCHEMA
    result["status"] = "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE"
    result["unknown_reason"] = (
        "required role proof is UNKNOWN; typed content was not read"
        if context["current_identity_scope"]["status"] == "UNKNOWN_NO_CURRENT_LIFECYCLE_SCOPE"
        else result.get("unknown_reason")
    )
    result["current_identity_scope"] = context["current_identity_scope"]
    adapter = result.setdefault("adapter", {})
    adapter["schema"] = ADAPTER_SCHEMA
    adapter["status"] = "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE"
    adapter["typed_content_required"] = False
    adapter["identity_admission"] = context["current_identity_scope"]["identity_admission"]
    return result


def build_event_stream_from_request(
    typed_result: Mapping[str, Any] | None,
    request: Mapping[str, Any],
    *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v5(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        if typed_result is not None:
            raise TypedEventAdapterV5Error("typed mapping must not be supplied when a role is UNKNOWN")
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    # validate_request_v5 requires an exact CURRENT scope before this path.
    try:
        result = _V4.build_event_stream_from_request(
            typed_result, request, allow_fixture=allow_fixture,
        )
    except Exception as error:
        raise TypedEventAdapterV5Error(str(error)) from error
    result = copy.deepcopy(result)
    result.setdefault("adapter", {})["schema"] = ADAPTER_SCHEMA
    result["adapter"]["identity_admission"] = context["current_identity_scope"]["identity_admission"]
    result["current_identity_scope"] = context["current_identity_scope"]
    return result


def bind_request(source_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source = _V4._read_json(source_request_path, role="V5 source request")
    context = validate_request_v5(source)
    target = Path(output_path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV5Error(f"refusing to overwrite: {target}")
    script_path = SCRIPT_DIR / Path(__file__).name
    bound = copy.deepcopy(source)
    bound["v5_adapter_binding"] = {
        "adapter_schema": ADAPTER_SCHEMA,
        "adapter_script_path": str(script_path),
        "adapter_script_file_sha256": _file_sha(script_path),
        "source_request": {
            "path": str(Path(source_request_path).expanduser().resolve()),
            "file_sha256": _file_sha(source_request_path),
            "canonical_sha256": source["request_sha256"],
            "request_schema": REQUEST_SCHEMA,
        },
        "content_policy": "SMALL_REQUEST_METADATA_ONLY; CURRENT_SCOPE_AND_TYPED_CONTENT_DEFERRED_TO_PARENT",
        "identity_admission": context["current_identity_scope"]["identity_admission"],
    }
    bound["request_sha256"] = canonical_sha(bound)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bound, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return {
        "schema": bound["schema"], "adapter_schema": ADAPTER_SCHEMA,
        "request_path": str(target), "request_sha256": bound["request_sha256"],
        "identity_admission": context["current_identity_scope"]["identity_admission"],
        "typed_content_required": bool(context["all_roles_known"]),
        "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV5Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


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
    convert.add_argument("--typed-result", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = _read_json(args.request, role="V5 request") if args.command != "bind-request" else None
        if args.command == "bind-request":
            result = bind_request(args.source_request, args.output)
        elif args.command == "validate-request":
            context = validate_request_v5(request, allow_fixture=args.allow_fixture, require_binding=True)
            result = {
                "schema": ADAPTER_SCHEMA,
                "status": "READY_FOR_PARENT_GUARDED_TYPED_MAPPING",
                "request_sha256": request["request_sha256"],
                "case_identity": context["case_identity"],
                "all_roles_known": context["all_roles_known"],
                "current_identity_scope": context["current_identity_scope"],
                "production_eligible": context["production_eligible"],
                "typed_content_required": context["all_roles_known"],
                "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
                "qualification": dict(UNKNOWN_QUALIFICATION), "typed_content_read": False,
            }
            if args.output:
                _write_json(args.output, result)
        else:
            document = build_event_stream_from_request(None, request, allow_fixture=args.allow_fixture)
            _write_json(args.output, document)
            result = {"output": str(args.output), "schema": document["schema"], "status": document["adapter"]["status"], "identity_admission": document["adapter"].get("identity_admission")}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV5Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
