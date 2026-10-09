#!/usr/bin/env python3
"""ROOT191 V5 strict full-stat wrapper around the consumed V4 entrypoint.

V4 remains immutable.  V5 performs the new six-field result-stat admission
before delegating the actual V8/V12/no-model operation to V4.  The delegated
V4 path already captures full pre/post stat dictionaries; V5 checks those
dictionaries against the enriched contract after a successful operation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V4_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py"
BUILDER_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_root191_v5_stat_enriched_builder.py"
if not V4_SCRIPT.is_file() or V4_SCRIPT.is_symlink():
    raise RuntimeError(f"ROOT191 V4 dependency is unavailable: {V4_SCRIPT}")
if not BUILDER_SCRIPT.is_file() or BUILDER_SCRIPT.is_symlink():
    raise RuntimeError(f"ROOT191 V5 stat builder is unavailable: {BUILDER_SCRIPT}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load ROOT191 dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load(V4_SCRIPT, "ds02_bound_root191_v4_for_v5")
BUILDER = _load(BUILDER_SCRIPT, "ds02_bound_root191_v5_builder_for_v5")

FULL_STAT_FIELDS = BUILDER.FULL_STAT_FIELDS


class Root191V5Error(RuntimeError):
    """A strict V5 stat or delegated evaluator error."""


def _json(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root191V5Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Root191V5Error(f"{role} must be a JSON object")
    return value


def _full_stat(value: Any, role: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise Root191V5Error(f"{role} is missing")
    result: dict[str, int] = {}
    for field in FULL_STAT_FIELDS:
        if field not in value or isinstance(value[field], bool):
            raise Root191V5Error(f"{role} lacks {field}")
        try:
            result[field] = int(value[field])
        except (TypeError, ValueError) as error:
            raise Root191V5Error(f"{role}.{field} is not an integer") from error
    return result


def _strict_request_stat(request: Mapping[str, Any]) -> dict[str, int]:
    contract = request.get("root191_v5_stat_contract")
    if not isinstance(contract, Mapping):
        raise Root191V5Error("request has no V5 full-stat contract")
    expected = _full_stat(contract.get("current_full_stat"), "V5 current_full_stat")
    result_contract = contract.get("result")
    binding = request.get("root200_binding", {}).get("result")
    if not isinstance(result_contract, Mapping) or not isinstance(binding, Mapping):
        raise Root191V5Error("V5 result stat bindings are incomplete")
    for label, item in (("expected_pre_stat", result_contract.get("expected_pre_stat")),
                        ("expected_post_stat", result_contract.get("expected_post_stat")),
                        ("ROOT200 result.stat", binding.get("stat"))):
        if _full_stat(item, label) != expected:
            raise Root191V5Error(f"{label} differs from V5 current_full_stat")
    result_path = Path(str(binding.get("path"))).expanduser()
    actual = BUILDER._full_stat(result_path)
    if actual != expected:
        raise Root191V5Error("bound result current full stat differs from V5 expected stat")
    return expected


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path = Path(path).expanduser().resolve()
    request = _json(request_path, "ROOT191 V5 request")
    # The builder performs the source/V15/ROOT200 joins and the proof-file
    # check.  It does not read the deferred V16 result content.
    checked = BUILDER.validate_enriched(request_path)
    expected = _strict_request_stat(request)
    return {
        "schema": "ds02.stage2.f2-root191-metadata-preflight.v5",
        "status": "ROOT191_V5_FULL_STAT_VALIDATED_READY_FOR_PARENT",
        "request": checked["request"],
        "result": checked["result"],
        "expected_full_stat": expected,
        "payload_read": False,
        "hdf5_bi4_native_read": False,
        "solver_or_evaluator_launched": False,
    }


def run_trial(request_path: Path | str, *, output: Path | str, parent_pid: int,
              max_wall_seconds: float | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _json(request_file, "ROOT191 V5 request")
    expected = _strict_request_stat(request)
    # Validate all bounded evidence before V4 opens the result.  V4 then owns
    # the direct-parent check, V8/V12 semantic checks and full pre/post stat.
    validate_request(request_file)
    result = V4.run_trial(request_file, output=Path(output).expanduser().resolve(),
                          parent_pid=int(parent_pid), max_wall_seconds=max_wall_seconds)
    source = result.get("result_source")
    if not isinstance(source, Mapping):
        raise Root191V5Error("delegated V4 result has no result_source stat report")
    pre = _full_stat(source.get("pre_stat"), "V4 result_source.pre_stat")
    post = _full_stat(source.get("post_stat"), "V4 result_source.post_stat")
    if pre != expected or post != expected or pre != post:
        raise Root191V5Error("delegated V4 pre/post stat does not satisfy the V5 full-stat contract")
    return {
        "schema": "ds02.stage2.f2-root191-typed-only-no-model-evaluator-report.v5",
        "status": "PASS_DEVELOPMENT_TYPED_ONLY_NO_MODEL_OPERATOR_TRIAL_ROOT191_V5",
        "delegated_v4": result,
        "result_stat_contract": {"expected": expected, "pre": pre, "post": post, "equal": True},
        "payload_read": True,
        "hdf5_bi4_native_read": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        value = validate_request(args.request) if args.command == "validate" else run_trial(
            args.request, output=args.output, parent_pid=args.parent_pid,
            max_wall_seconds=args.max_wall_seconds)
    except (Root191V5Error, BUILDER.Root191V5BuilderError, V4.Root191V4Error,
            BUILDER.PRIMARY.V3.Root191V3Error, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"ROOT191 V5 typed-only evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": value.get("schema"), "status": value.get("status"),
                      "request": value.get("request"), "result_stat_contract": value.get("result_stat_contract"),
                      "payload_read": value.get("payload_read")}, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
