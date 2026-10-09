#!/usr/bin/env python3
"""Strict V4 CLI boundary for the typed-event UNKNOWN admission path.

This is additive to the consumed V2 and V3 adapters.  It seals a source
request to this exact script, verifies both file and canonical SHA bindings,
and provides a real bind -> validate -> convert -> validate-result CLI chain.
When source or region-owner proof is UNKNOWN, convert never opens the typed
path, writes a small terminal UNKNOWN result, and gives no scientific credit.
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


_V3 = _load(
    "namespace331_v16_typed_event_adapter_v3_for_adapter_v4",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v3.py",
)


ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v4"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v4"
REQUEST_SCHEMA = _V3.REQUEST_SCHEMA
MAX_ARTIFACT_BYTES = min(int(_V3.MAX_ARTIFACT_BYTES), 10 * 1024 * 1024)
MAX_TYPED_JSON_BYTES = min(int(_V3.MAX_TYPED_JSON_BYTES), MAX_ARTIFACT_BYTES)
REQUIRED_ROLES = tuple(_V3.REQUIRED_ROLES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
UNKNOWN_METRICS = tuple(_V3.UNKNOWN_METRICS)


class TypedEventAdapterV4Error(ValueError):
    """Request, binding, or UNKNOWN result is not admissible."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V3.canonical_sha(value)


def _read_json(path: Path | str, *, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise TypedEventAdapterV4Error(f"{role} must be a regular non-symlink file")
    if target.stat().st_size > MAX_ARTIFACT_BYTES:
        raise TypedEventAdapterV4Error(f"{role} exceeds the bounded metadata limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterV4Error(f"{role} is not valid JSON: {error}") from error
    if not isinstance(value, Mapping):
        raise TypedEventAdapterV4Error(f"{role} must be a JSON object")
    return dict(value)


def _file_sha(path: Path | str) -> str:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise TypedEventAdapterV4Error(f"source binding is not a regular file: {target}")
    if target.stat().st_size > MAX_ARTIFACT_BYTES:
        raise TypedEventAdapterV4Error(f"source binding exceeds the bounded metadata limit: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_semantic(value: Mapping[str, Any]) -> str:
    return canonical_sha(value)


def _validate_v4_binding(request: Mapping[str, Any], *, require: bool = False) -> None:
    binding = request.get("v4_adapter_binding")
    if binding is None:
        if require:
            raise TypedEventAdapterV4Error("V4 adapter binding is required")
        return
    if not isinstance(binding, Mapping):
        raise TypedEventAdapterV4Error("V4 adapter binding is malformed")
    if binding.get("adapter_schema") != ADAPTER_SCHEMA:
        raise TypedEventAdapterV4Error("V4 adapter binding schema is unsupported")
    script_path = binding.get("adapter_script_path")
    declared_script_sha = binding.get("adapter_script_file_sha256")
    if script_path != str(SCRIPT_DIR / Path(__file__).name):
        raise TypedEventAdapterV4Error("V4 adapter script path is not the current pinned entrypoint")
    if not isinstance(declared_script_sha, str) or len(declared_script_sha) != 64:
        raise TypedEventAdapterV4Error("V4 adapter script SHA is malformed")
    _observed_script_sha = _file_sha(Path(script_path))
    if _observed_script_sha != declared_script_sha:
        raise TypedEventAdapterV4Error("V4 adapter script file SHA differs")
    source = binding.get("source_request")
    if not isinstance(source, Mapping):
        raise TypedEventAdapterV4Error("V4 source request binding is missing")
    source_path = source.get("path")
    source_file_sha = source.get("file_sha256")
    source_canonical_sha = source.get("canonical_sha256")
    if (not isinstance(source_path, str) or not isinstance(source_file_sha, str)
            or not isinstance(source_canonical_sha, str)):
        raise TypedEventAdapterV4Error("V4 source request binding lacks path/file/canonical SHA")
    source_value = _read_json(Path(source_path), role="bound source request")
    if source_value.get("schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV4Error("bound source request schema differs")
    if source_value.get("request_sha256") != source_canonical_sha:
        raise TypedEventAdapterV4Error("bound source request canonical SHA differs")
    if _file_sha(Path(source_path)) != source_file_sha:
        raise TypedEventAdapterV4Error("bound source request file SHA differs")
    current_without_binding = copy.deepcopy(dict(request))
    current_without_binding.pop("request_sha256", None)
    current_without_binding.pop("v4_adapter_binding", None)
    if _source_semantic(current_without_binding) != _source_semantic(source_value):
        raise TypedEventAdapterV4Error("request semantic fields differ from sealed source request")
    if source.get("request_schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV4Error("bound source request schema provenance is unsupported")


def validate_request_v4(
    request: Mapping[str, Any], *, allow_fixture: bool = False, require_binding: bool = False,
) -> dict[str, Any]:
    try:
        context = _V3.validate_request_v3(request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV4Error(str(error)) from error
    _validate_v4_binding(request, require=require_binding)
    return context


def typed_content_required(request: Mapping[str, Any], *, allow_fixture: bool = False) -> bool:
    return bool(validate_request_v4(request, allow_fixture=allow_fixture)["all_roles_known"])


def _with_v4_adapter(result: Mapping[str, Any], request: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(dict(result))
    adapter = document.setdefault("adapter", {})
    adapter["schema"] = ADAPTER_SCHEMA
    adapter["request_schema"] = REQUEST_SCHEMA
    adapter["request_sha256"] = request["request_sha256"]
    adapter["production_eligible"] = context["production_eligible"]
    adapter["fixture_execution_allowed"] = context["fixture_execution_allowed"]
    document["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return document


def build_unknown_event_result_from_request(
    request: Mapping[str, Any], *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v4(request, allow_fixture=allow_fixture)
    if context["all_roles_known"]:
        raise TypedEventAdapterV4Error("all required roles are known; UNKNOWN short-circuit is inapplicable")
    result = _V3.build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    result = _with_v4_adapter(result, request, context)
    result["schema"] = UNKNOWN_ADMISSION_SCHEMA
    result["status"] = "UNKNOWN_REQUIRED_ROLE_PROOF"
    result["adapter"]["status"] = "UNKNOWN_REQUIRED_ROLE_PROOF"
    result["adapter"]["typed_content_required"] = False
    return result


def build_event_stream_from_request(
    typed_result: Mapping[str, Any] | None,
    request: Mapping[str, Any],
    *,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v4(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        if typed_result is not None:
            raise TypedEventAdapterV4Error("typed mapping must not be supplied when required role is UNKNOWN")
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    try:
        result = _V3.build_event_stream_from_request(
            typed_result, request, allow_fixture=allow_fixture,
        )
    except Exception as error:
        raise TypedEventAdapterV4Error(str(error)) from error
    return _with_v4_adapter(result, request, context)


def convert_bounded_json(
    request: Mapping[str, Any], typed_path: Path | str, *, allow_fixture: bool = False,
) -> dict[str, Any]:
    context = validate_request_v4(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    target = Path(typed_path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_TYPED_JSON_BYTES:
        raise TypedEventAdapterV4Error("typed JSON is missing, symlinked, or exceeds bounded limit")
    try:
        typed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterV4Error(str(error)) from error
    if not isinstance(typed, Mapping):
        raise TypedEventAdapterV4Error("typed JSON must be an object")
    return build_event_stream_from_request(typed, request, allow_fixture=allow_fixture)


def bind_request(source_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source_path = Path(source_request_path).expanduser()
    source = _read_json(source_path, role="source request")
    context = validate_request_v4(source)
    script_path = SCRIPT_DIR / Path(__file__).name
    bound = copy.deepcopy(source)
    bound["v4_adapter_binding"] = {
        "adapter_schema": ADAPTER_SCHEMA,
        "adapter_script_path": str(script_path),
        "adapter_script_file_sha256": _file_sha(script_path),
        "source_request": {
            "path": str(source_path.resolve()),
            "file_sha256": _file_sha(source_path),
            "canonical_sha256": source["request_sha256"],
            "request_schema": REQUEST_SCHEMA,
        },
        "content_policy": "SMALL_REQUEST_METADATA_ONLY; DEFER_TYPED_CONTENT_TO_PARENT",
        "typed_content_required": bool(context["all_roles_known"]),
    }
    bound["request_sha256"] = canonical_sha(bound)
    target = Path(output_path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV4Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bound, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")
    return {
        "schema": bound["schema"], "adapter_schema": ADAPTER_SCHEMA,
        "request_path": str(target), "request_sha256": bound["request_sha256"],
        "source_request_sha256": source["request_sha256"],
        "all_roles_known": bool(context["all_roles_known"]),
        "typed_content_required": bool(context["all_roles_known"]),
        "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _seal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(result))
    sealed.pop("result_sha256", None)
    sealed["result_sha256"] = canonical_sha(sealed)
    return sealed


def validate_unknown_result(
    result_path: Path | str,
    request: Mapping[str, Any],
    *,
    require_binding: bool = True,
) -> dict[str, Any]:
    context = validate_request_v4(request, require_binding=require_binding)
    if context["all_roles_known"]:
        raise TypedEventAdapterV4Error("UNKNOWN result is not admissible when all roles are known")
    result = _read_json(result_path, role="UNKNOWN result")
    if result.get("result_sha256") != canonical_sha({k: v for k, v in result.items() if k != "result_sha256"}):
        raise TypedEventAdapterV4Error("UNKNOWN result SHA mismatch")
    if result.get("schema") != UNKNOWN_ADMISSION_SCHEMA or result.get("status") != "UNKNOWN_REQUIRED_ROLE_PROOF":
        raise TypedEventAdapterV4Error("UNKNOWN result schema/status mismatch")
    if result.get("typed_content_read") is not False or result.get("labels") != []:
        raise TypedEventAdapterV4Error("UNKNOWN result claims typed content or labels")
    metrics = result.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(UNKNOWN_METRICS) or any(value is not None for value in metrics.values()):
        raise TypedEventAdapterV4Error("UNKNOWN result metrics are not all NULL")
    if result.get("model_invoked") is not False or result.get("cfd_invoked") is not False:
        raise TypedEventAdapterV4Error("UNKNOWN result claims model/CFD execution")
    adapter = result.get("adapter")
    if not isinstance(adapter, Mapping) or adapter.get("schema") != ADAPTER_SCHEMA \
            or adapter.get("status") != "UNKNOWN_REQUIRED_ROLE_PROOF" \
            or adapter.get("request_sha256") != request.get("request_sha256"):
        raise TypedEventAdapterV4Error("UNKNOWN result adapter binding mismatch")
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "VERIFIED_UNKNOWN_METADATA_ONLY",
        "result_path": str(Path(result_path).expanduser()),
        "result_sha256": result["result_sha256"],
        "request_sha256": request["request_sha256"],
        "unknown_roles": result.get("unknown_roles", []),
        "typed_content_read": False,
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "read_scope": {"metadata_only": True, "payload_opened": False, "model_invoked": False},
    }


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV4Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")


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
    check = sub.add_parser("validate-result")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "bind-request":
            result = bind_request(args.source_request, args.output)
        elif args.command == "validate-request":
            request = _read_json(args.request, role="request")
            context = validate_request_v4(request, allow_fixture=args.allow_fixture, require_binding=True)
            result = {
                "schema": ADAPTER_SCHEMA, "status": "READY_FOR_PARENT_GUARDED_TYPED_MAPPING",
                "request_sha256": request["request_sha256"], "case_identity": context["case_identity"],
                "all_roles_known": context["all_roles_known"], "fixture_roles": context["fixture_roles"],
                "production_eligible": context["production_eligible"],
                "typed_content_required": context["all_roles_known"],
                "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
                "qualification": dict(UNKNOWN_QUALIFICATION), "typed_content_read": False,
            }
            if args.output:
                _write_json(args.output, result)
        elif args.command == "convert":
            request = _read_json(args.request, role="request")
            result = _seal_result(convert_bounded_json(request, args.typed_result, allow_fixture=args.allow_fixture))
            _write_json(args.output, result)
            result = {"output": str(args.output), "schema": result["schema"],
                      "status": result["adapter"]["status"],
                      "event_credit": result["adapter"]["event_credit"],
                      "result_sha256": result["result_sha256"]}
        else:
            request = _read_json(args.request, role="request")
            result = validate_unknown_result(args.result, request)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV4Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
