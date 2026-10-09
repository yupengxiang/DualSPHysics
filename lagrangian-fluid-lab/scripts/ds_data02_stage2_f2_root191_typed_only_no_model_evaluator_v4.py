#!/usr/bin/env python3
"""ROOT191 V4 hardened typed-only entrypoint.

V3 remains immutable.  V4 reuses its strict ROOT200/179C/V15 admission and
the real V8/V12 validators, but closes the result-file boundary: the bound
result is stat'ed before and after the single JSON read, all identity fields
are retained in the report, and the validated V12 summary is emitted without
silently replacing missing fields with ``None``.  ``run`` is a real child
process entrypoint; no semantic hook is replaced by this module.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V3_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py"
if not V3_SCRIPT.is_file():
    raise RuntimeError(f"ROOT191 V3 dependency is unavailable: {V3_SCRIPT}")
import importlib.util

_spec = importlib.util.spec_from_file_location("ds02_bound_root191_v3_for_v4", V3_SCRIPT)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load ROOT191 V3 dependency: {V3_SCRIPT}")
V3 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = V3
_spec.loader.exec_module(V3)

REQUEST_SCHEMA = V3.REQUEST_SCHEMA
UNKNOWN = V3.UNKNOWN
MAX_RESULT_BYTES = V3.MAX_RESULT_BYTES


class Root191V4Error(RuntimeError):
    """A strict V4 source, stat, or semantic boundary error."""


def _full_stat(path: Path) -> dict[str, int]:
    try:
        info = path.stat()
    except OSError as error:
        raise Root191V4Error(f"cannot stat bound result {path}: {error}") from error
    if not path.is_file() or path.is_symlink():
        raise Root191V4Error(f"bound result must remain a regular non-symlink file: {path}")
    return {
        "bytes": int(info.st_size),
        "mode_bits": int(info.st_mode & 0o7777),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
    }


def _check_binding_stat(binding: Mapping[str, Any], stat: Mapping[str, int]) -> None:
    expected = binding.get("stat")
    if not isinstance(expected, Mapping):
        raise Root191V4Error("result binding lacks its expected stat contract")
    # Existing ROOT200 metadata binds bytes/mode/mtime.  ctime/dev/ino are
    # intentionally captured at runtime and must be stable across the read.
    for key in ("bytes", "mtime_ns"):
        if key in expected and int(expected[key]) != int(stat[key]):
            raise Root191V4Error(f"result binding stat differs for {key}")
    mode = expected.get("mode_bits", expected.get("mode"))
    if mode is not None and int(mode) != int(stat["mode_bits"]):
        raise Root191V4Error("result binding stat differs for mode_bits")


def _strict_v12_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        raise Root191V4Error("V12 validator did not return a summary object")
    required = ("source_binding", "case_identity", "cohort", "initial_mass_denominator",
                "time", "events", "result_bytes", "result_sha256")
    missing = [key for key in required if key not in summary or summary[key] is None]
    if missing:
        raise Root191V4Error(f"V12 summary is incomplete: {', '.join(missing)}")
    time_summary = summary["time"]
    if not isinstance(time_summary, Mapping) or any(time_summary.get(key) is None for key in ("frame_count", "first_s", "last_s")):
        raise Root191V4Error("V12 summary time fields are incomplete")
    cohort = summary["cohort"]
    if not isinstance(cohort, Mapping) or any(cohort.get(key) is None for key in ("selected_count", "identity_sha256")):
        raise Root191V4Error("V12 summary cohort fields are incomplete")
    mass = summary["initial_mass_denominator"]
    if not isinstance(mass, Mapping) or mass.get("denominator_kg") is None:
        raise Root191V4Error("V12 summary denominator is incomplete")
    return dict(summary)


def validate_request(path: Path | str) -> dict[str, Any]:
    """Run the immutable V3 metadata admission through the V4 source."""
    result = V3.validate_request(path)
    request_path, request = V3._json(path, "ROOT191 V4 request")
    execution = request.get("execution")
    if not isinstance(execution, Mapping):
        raise Root191V4Error("ROOT191 V4 execution contract is missing")
    if execution.get("read_hdf5_or_bi4") is not False or execution.get("raw_opened") is not False:
        raise Root191V4Error("ROOT191 V4 content boundary is open")
    return {
        "schema": "ds02.stage2.f2-root191-metadata-preflight.v4",
        "status": "ROOT191_V4_METADATA_VALIDATED_READY_FOR_PARENT",
        "request": {"path": str(request_path), "file_sha256": V3.sha256_file(request_path),
                    "canonical_sha256": request["sha256"]},
        "v3": result,
        "payload_read": False,
        "hdf5_bi4_native_read": False,
        "qualification": dict(UNKNOWN),
    }


def run_trial(request_path: Path | str, *, output: Path | str, parent_pid: int,
              max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run the actual V8/V12/scorer chain with a full result stat boundary."""
    started = time.monotonic()
    if os.getppid() != int(parent_pid):
        raise Root191V4Error("ROOT191 V4 run requires the direct parent guard")
    request_file, request = V3._json(request_path, "ROOT191 V4 request")
    # The parent owns reservation/admission.  This call only reads bounded
    # request/code metadata; the result is opened below after the direct-parent
    # check and its pre-stat capture.
    validate_request(request_file)
    execution = request["execution"]
    limit = float(max_wall_seconds if max_wall_seconds is not None else execution.get("max_wall_seconds", 900.0))
    if limit <= 0:
        raise Root191V4Error("max_wall_seconds must be positive")
    root = request["root200_binding"]
    pair = V3._load_pair(root["inner_request"]["path"], root["outer_wrapper"]["path"])
    result_path, expected_sha, declared_bytes = V3._validate_result_binding(request, pair)
    binding = root["result"]
    pre_stat = _full_stat(result_path)
    _check_binding_stat(binding, pre_stat)
    if pre_stat["bytes"] != declared_bytes or pre_stat["bytes"] > int(execution.get("max_result_bytes", MAX_RESULT_BYTES)):
        raise Root191V4Error("bound result size differs from the request limit")
    if time.monotonic() - started > limit:
        raise Root191V4Error("ROOT191 V4 deadline expired before result read")

    try:
        proof_request = V3.V8._load_object(pair["inner_path"])
        bound_info = V3.V8._validate_request(proof_request, verify_result_stat=True)
        result, observed_sha, observed_bytes = V3.V8._read_result(result_path, int(bound_info["max_result_bytes"]))
        post_stat = _full_stat(result_path)
        if pre_stat != post_stat:
            raise Root191V4Error("result stat changed during JSON read")
        if observed_sha != expected_sha or observed_bytes != declared_bytes:
            raise Root191V4Error("result content differs from the bound ROOT200 product")
        contract = V3.V12._load_marker(pair["inner_path"])[2]
        old_scope = V3.V12._ACTIVE_SCOPE
        V3.V12._ACTIVE_SCOPE = contract
        try:
            v12_summary = _strict_v12_summary(
                V3.V12._validate_result_v12(result, bound_info, observed_sha, observed_bytes))
        finally:
            V3.V12._ACTIVE_SCOPE = old_scope
    except Root191V4Error:
        raise
    except Exception as error:
        raise Root191V4Error(f"real V8/V12 validation failed: {error}") from error
    if time.monotonic() - started > limit:
        raise Root191V4Error("ROOT191 V4 deadline expired after semantic validation")
    frozen_path = V3._file(request["source_frozen_request"]["path"], "V4 frozen V15 request")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if V3.sha256_file(frozen_path) != request["source_frozen_request"]["file_sha256"]:
        raise Root191V4Error("frozen V15 request changed during run")
    try:
        operator_score = V3.EVALUATOR._score_typed_result(result, frozen)
    except Exception as error:
        raise Root191V4Error(f"existing typed-only scorer rejected the result: {error}") from error
    if not isinstance(operator_score, Mapping) or operator_score.get("cases") is None:
        raise Root191V4Error("existing typed-only scorer returned no case summary")
    output_path = Path(output).expanduser().resolve()
    fresh_root = Path(request["fresh_output_namespace"]["root"]).expanduser().resolve()
    if output_path != fresh_root and not str(output_path).startswith(str(fresh_root) + os.sep):
        raise Root191V4Error("V4 output is outside the fresh ROOT191 namespace")
    if output_path.exists():
        raise Root191V4Error(f"refusing existing V4 output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": "ds02.stage2.f2-root191-typed-only-no-model-evaluator-report.v4",
        "status": "PASS_DEVELOPMENT_TYPED_ONLY_NO_MODEL_OPERATOR_TRIAL_ROOT191_V4",
        "request": {"path": str(request_file), "file_sha256": V3.sha256_file(request_file),
                    "canonical_sha256": request["sha256"]},
        "result_source": {
            "path": str(result_path), "sha256": observed_sha, "bytes": observed_bytes,
            "binding_stat": dict(binding["stat"]), "pre_stat": pre_stat, "post_stat": post_stat,
            "pre_post_stat_equal": pre_stat == post_stat, "content_sha_verified": True,
            "read_phase": "AFTER_DIRECT_PARENT_AND_PARENT_RESERVATION",
        },
        "result_summary": v12_summary,
        "operator_score": operator_score,
        "root200_guard": request["root200_binding"],
        "producer_179c_binding": request["producer_179c_binding"],
        "source_frozen_request": request["source_frozen_request"],
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                             "portable_cold_replay_credit": "NOT_CLAIMED", "scientific_qualification": "UNKNOWN"},
        "execution": {"json_only": True, "hdf5_or_bi4_content_read": False, "raw_opened": False,
                       "direct_parent_verified": True, "wall_seconds_from_entry": time.monotonic() - started,
                       "max_wall_seconds": limit},
    }
    report["sha256"] = V3.canonical_sha(report)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {"schema": report["schema"], "status": report["status"], "report": str(output_path),
            "sha256": report["sha256"], "result_source": report["result_source"],
            "qualification": dict(UNKNOWN), "payload_read": True, "hdf5_bi4_native_read": False}


def run_v8_fixture(request_path: Path | str, *, output: Path | str, parent_pid: int) -> dict[str, Any]:
    """Run a complete bounded V8 fixture through a real subprocess CLI.

    This command is deliberately marked ``fixture_only`` by its request and
    is never accepted by ``run_trial``.  It exists to test the actual V8
    validator/read/semantic path without monkeypatching any module hook or
    opening a production V16 file.  Scientific ROOT191 admission remains the
    V4 ``run`` path above, which invokes V12 and the existing scorer.
    """
    started = time.monotonic()
    request_file, request = V3._json(request_path, "V8 fixture request")
    if request.get("fixture_only") is not True:
        raise Root191V4Error("run-v8-fixture requires an explicit fixture_only request")
    if os.getppid() != int(parent_pid):
        raise Root191V4Error("fixture run requires the direct parent guard")
    try:
        bound = V3.V8._validate_request(request, verify_result_stat=True)
        pre_stat = _full_stat(bound["result_path"])
        result, observed_sha, observed_bytes = V3.V8._read_result(bound["result_path"], int(bound["max_result_bytes"]))
        post_stat = _full_stat(bound["result_path"])
        if pre_stat != post_stat:
            raise Root191V4Error("fixture result stat changed while reading")
        if observed_sha != bound["result_sha256"] or observed_bytes != bound["result_bytes"]:
            raise Root191V4Error("fixture result content differs from its bound SHA/stat")
        summary = V3.V8._validate_result(result, bound, observed_sha, observed_bytes)
    except Root191V4Error:
        raise
    except Exception as error:
        raise Root191V4Error(f"real V8 fixture validation failed: {error}") from error
    if not isinstance(summary, Mapping):
        raise Root191V4Error("real V8 fixture validator returned no summary")
    output_path = Path(output).expanduser().resolve()
    if output_path.exists():
        raise Root191V4Error(f"refusing existing fixture output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "ds02.stage2.f2-root191-v4-v8-fixture-report.v1",
        "status": "PASS_REAL_V8_VALIDATOR_FIXTURE_ONLY",
        "request": {"path": str(request_file), "sha256": V3.sha256_file(request_file)},
        "result_source": {"path": str(bound["result_path"]), "sha256": observed_sha,
                          "bytes": observed_bytes, "pre_stat": pre_stat, "post_stat": post_stat,
                          "pre_post_stat_equal": True},
        "validated_summary": dict(summary),
        "execution": {"subprocess_cli": True, "v8_validator": True, "hdf5_or_bi4_content_read": False,
                       "raw_opened": False, "model_invoked": False, "cfd_invoked": False,
                       "elapsed_wall_seconds": time.monotonic() - started},
        "qualification": dict(UNKNOWN),
    }
    report["sha256"] = V3.canonical_sha(report)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {"schema": report["schema"], "status": report["status"], "report": str(output_path),
            "sha256": report["sha256"], "qualification": dict(UNKNOWN)}


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
    fixture = sub.add_parser("run-v8-fixture")
    fixture.add_argument("--request", type=Path, required=True)
    fixture.add_argument("--output", type=Path, required=True)
    fixture.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            value = validate_request(args.request)
        elif args.command == "run-v8-fixture":
            value = run_v8_fixture(args.request, output=args.output, parent_pid=args.parent_pid)
        else:
            value = run_trial(args.request, output=args.output, parent_pid=args.parent_pid,
                              max_wall_seconds=args.max_wall_seconds)
    except (Root191V4Error, V3.Root191V3Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT191 V4 typed-only evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
