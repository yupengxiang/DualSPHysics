#!/usr/bin/env python3
"""V3 metadata-only typed-event admission with an UNKNOWN-role short circuit.

The consumed V2 adapter remains immutable.  This additive entrypoint reuses
its strict request and typed-event validation, but adds a sealed V3 adapter
binding and a pre-read path: when source or region-owner proof is UNKNOWN, the
parent returns an all-UNKNOWN metadata result without opening the deferred
typed/V16 product.  A known-role result still goes through the existing V2
Zone/Idp, mass, region, event-order, and censoring checks.  No model or CFD is
invoked and no original-path fallback is permitted.
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


# V2 is an explicitly pinned implementation dependency.  This file never
# mutates it; all V3 behavior is layered in this module.
_V2 = _load(
    "namespace331_v16_typed_event_adapter_v2_for_adapter_v3",
    SCRIPT_DIR / "ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py",
)


ADAPTER_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-adapter.v3"
UNKNOWN_ADMISSION_SCHEMA = "ds02.stage2.namespace331.v16-typed-event-unknown-admission.v3"
REQUEST_SCHEMA = _V2.REQUEST_SCHEMA
EVENT_SCHEMA = _V2.EVENT_SCHEMA
MAX_TYPED_JSON_BYTES = int(_V2.MAX_TYPED_JSON_BYTES)
MAX_ARTIFACT_BYTES = int(_V2._V3.MAX_ARTIFACT_BYTES)
REQUIRED_ROLES = tuple(_V2.REQUIRED_ROLES)
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
UNKNOWN_METRICS = (
    "first_arrival_mass_weighted_time_s", "first_arrival_mass_kg", "first_arrival_count",
    "right_censored_mass_kg", "excluded_mass_kg", "no_arrival_observed_mass_kg",
    "crossing_count", "gross_crossing_mass_kg", "net_flux_mass_kg",
    "net_flux_rate_kg_s", "mass_weighted_residence_time_s", "residence_mass_time_kg_s",
)


class TypedEventAdapterV3Error(ValueError):
    """Request, source binding, or deferred result is not admissible."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    return _V2.canonical_sha(value)


def _file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise TypedEventAdapterV3Error(f"metadata source is not a regular file: {path}")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise TypedEventAdapterV3Error(f"metadata source exceeds bound: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_request(path: Path | str) -> dict[str, Any]:
    try:
        return _V2._read_request(path)
    except Exception as error:
        raise TypedEventAdapterV3Error(str(error)) from error


def _source_bindings(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        return _V2._source_bindings(context)
    except Exception as error:
        raise TypedEventAdapterV3Error(str(error)) from error


def _validate_adapter_binding(request: Mapping[str, Any]) -> None:
    binding = request.get("v3_adapter_binding")
    if not isinstance(binding, Mapping):
        return
    if binding.get("adapter_schema") != ADAPTER_SCHEMA:
        raise TypedEventAdapterV3Error("V3 adapter binding schema is unsupported")
    script_path = binding.get("adapter_script_path")
    script_sha = binding.get("adapter_script_file_sha256")
    if not isinstance(script_path, str) or not isinstance(script_sha, str) or len(script_sha) != 64:
        raise TypedEventAdapterV3Error("V3 adapter binding lacks script path/SHA")
    source = binding.get("source_request")
    if not isinstance(source, Mapping):
        raise TypedEventAdapterV3Error("V3 adapter binding lacks source request provenance")
    if not isinstance(source.get("path"), str) or not isinstance(source.get("file_sha256"), str):
        raise TypedEventAdapterV3Error("V3 source request provenance lacks path/SHA")
    if not isinstance(source.get("canonical_sha256"), str) or len(source["canonical_sha256"]) != 64:
        raise TypedEventAdapterV3Error("V3 source request provenance lacks canonical SHA")
    if source.get("request_schema") != REQUEST_SCHEMA:
        raise TypedEventAdapterV3Error("V3 source request schema provenance is unsupported")


def validate_request_v3(
    request: Mapping[str, Any], *, allow_fixture: bool = False,
) -> dict[str, Any]:
    """Validate request metadata without opening its deferred typed result."""
    try:
        context = _V2.validate_request_v3(request, allow_fixture=allow_fixture)
    except Exception as error:
        raise TypedEventAdapterV3Error(str(error)) from error
    _validate_adapter_binding(request)
    return context


def typed_content_required(request: Mapping[str, Any], *, allow_fixture: bool = False) -> bool:
    return bool(validate_request_v3(request, allow_fixture=allow_fixture)["all_roles_known"])


def build_unknown_event_result_from_request(
    request: Mapping[str, Any], *, allow_fixture: bool = False,
) -> dict[str, Any]:
    """Produce a terminal UNKNOWN result before any typed-content read."""
    context = validate_request_v3(request, allow_fixture=allow_fixture)
    if context["all_roles_known"]:
        raise TypedEventAdapterV3Error(
            "all required roles are known; use the parent-guarded typed mapping path"
        )
    unknown_roles = [
        role for role in REQUIRED_ROLES
        if context["roles"][role].get("status") != "KNOWN"
    ]
    return {
        "schema": UNKNOWN_ADMISSION_SCHEMA,
        "status": "UNKNOWN_REQUIRED_ROLE_PROOF",
        "case_identity": dict(context["case_identity"]),
        "binding_status": {
            role: ("KNOWN" if context["roles"][role].get("status") == "KNOWN" else "UNKNOWN")
            for role in REQUIRED_ROLES
        },
        "unknown_roles": unknown_roles,
        "unknown_reason": "required role proof is UNKNOWN; typed content was not read",
        "typed_content_read": False,
        "event_stream_materialization": "SKIPPED_REQUIRED_ROLE_UNKNOWN",
        "labels": [],
        "metrics": {key: None for key in UNKNOWN_METRICS},
        "source_bindings": _source_bindings(context),
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "model_invoked": False,
        "cfd_invoked": False,
        "adapter": {
            "schema": ADAPTER_SCHEMA,
            "request_schema": REQUEST_SCHEMA,
            "request_sha256": request["request_sha256"],
            "event_credit": "NONE_ROLE_PROOF_UNKNOWN",
            "production_eligible": context["production_eligible"],
            "fixture_execution_allowed": context["fixture_execution_allowed"],
            "typed_content_required": False,
        },
    }


def build_event_stream_from_request(
    typed_result: Mapping[str, Any] | None,
    request: Mapping[str, Any],
    *,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    """Run the V2 strict consumer only when all required proofs are known."""
    context = validate_request_v3(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        if typed_result is not None:
            raise TypedEventAdapterV3Error(
                "typed mapping must not be supplied when a required role is UNKNOWN"
            )
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    if not isinstance(typed_result, Mapping):
        raise TypedEventAdapterV3Error("guarded typed result must be a JSON object")
    try:
        result = _V2.build_event_stream_from_request(
            typed_result, request, allow_fixture=allow_fixture,
        )
    except Exception as error:
        raise TypedEventAdapterV3Error(str(error)) from error
    document = copy.deepcopy(result)
    adapter = document.setdefault("adapter", {})
    adapter["schema"] = ADAPTER_SCHEMA
    adapter["request_schema"] = REQUEST_SCHEMA
    adapter["request_sha256"] = request["request_sha256"]
    adapter["parent_guard_content_boundary"] = "GUARDED_TYPED_MAPPING"
    adapter["event_credit"] = "DEVELOPMENT_UNKNOWN"
    adapter["production_eligible"] = context["production_eligible"]
    adapter["fixture_execution_allowed"] = context["fixture_execution_allowed"]
    document["qualification"] = dict(UNKNOWN_QUALIFICATION)
    return document


def convert_bounded_json(
    request: Mapping[str, Any], typed_path: Path | str, *, allow_fixture: bool = False,
) -> dict[str, Any]:
    """Bounded fixture conversion; unknown roles short-circuit before opening it."""
    context = validate_request_v3(request, allow_fixture=allow_fixture)
    if not context["all_roles_known"]:
        return build_unknown_event_result_from_request(request, allow_fixture=allow_fixture)
    target = Path(typed_path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_TYPED_JSON_BYTES:
        raise TypedEventAdapterV3Error("CLI typed JSON is missing, symlinked, or exceeds fixture bound")
    try:
        typed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEventAdapterV3Error(str(error)) from error
    return build_event_stream_from_request(typed, request, allow_fixture=allow_fixture)


def bind_request(source_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Create a fresh V3 overlay while preserving source request provenance."""
    source_path = Path(source_request_path).expanduser()
    source = _read_request(source_path)
    context = validate_request_v3(source)
    script_path = Path(__file__).resolve()
    bound = copy.deepcopy(source)
    bound["v3_adapter_binding"] = {
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
        raise TypedEventAdapterV3Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bound, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")
    return {
        "schema": bound["schema"],
        "adapter_schema": ADAPTER_SCHEMA,
        "request_path": str(target),
        "request_sha256": bound["request_sha256"],
        "source_request_sha256": source["request_sha256"],
        "all_roles_known": bool(context["all_roles_known"]),
        "typed_content_required": bool(context["all_roles_known"]),
        "event_credit": "DEVELOPMENT_UNKNOWN" if context["all_roles_known"] else "NONE_ROLE_PROOF_UNKNOWN",
        "qualification": dict(UNKNOWN_QUALIFICATION),
    }


def _write_json(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise TypedEventAdapterV3Error(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-request")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--allow-fixture", action="store_true")
    bind = sub.add_parser("bind-request")
    bind.add_argument("--source-request", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    convert = sub.add_parser("convert")
    convert.add_argument("--request", type=Path, required=True)
    convert.add_argument("--typed-result", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "bind-request":
            result = bind_request(args.source_request, args.output)
        else:
            request = _read_request(args.request)
            if args.command == "validate-request":
                context = validate_request_v3(request, allow_fixture=args.allow_fixture)
                result = {
                    "schema": ADAPTER_SCHEMA,
                    "status": "READY_FOR_PARENT_GUARDED_TYPED_MAPPING",
                    "request_sha256": request["request_sha256"],
                    "case_identity": context["case_identity"],
                    "all_roles_known": context["all_roles_known"],
                    "fixture_roles": context["fixture_roles"],
                    "production_eligible": context["production_eligible"],
                    "typed_content_required": context["all_roles_known"],
                    "event_credit": "NONE_ROLE_PROOF_UNKNOWN" if not context["all_roles_known"] else "DEVELOPMENT_UNKNOWN",
                    "qualification": dict(UNKNOWN_QUALIFICATION),
                    "typed_content_read": False,
                }
            else:
                document = convert_bounded_json(
                    request, args.typed_result, allow_fixture=args.allow_fixture,
                )
                _write_json(args.output, document)
                result = {"output": str(args.output), "schema": document["schema"],
                          "status": document["adapter"]["status"],
                          "event_credit": document["adapter"]["event_credit"]}
            if args.output and args.command == "validate-request":
                _write_json(args.output, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, TypedEventAdapterV3Error) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
