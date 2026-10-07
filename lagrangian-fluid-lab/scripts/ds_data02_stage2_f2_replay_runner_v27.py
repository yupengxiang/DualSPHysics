#!/usr/bin/env python3
"""Forward v27 runner for the typed-only F2 full401 replay.

v26 finished the 401-frame consumer and wrote the complete v15 result, but
the copied v25 runner failed while printing ``result["status"]`` because the
successful result used ``runner_status``.  This additive runner has two
fail-closed paths:

* ``repair`` validates the immutable v26 receipt/result and writes a new
  schema-correct v27 report without reopening HDF5 or rerunning the 401
  frames.  It is the preferred path when the v26 result passes the contract.
* ``run`` delegates a fresh parent-approved run to the immutable v25 worker,
  then adds an explicit ``status`` field before writing a new output.

The v25 module, v26 output, receipt, and all consumed bundles remain
immutable.  Every path in this module is a binding; no original-source
fallback is introduced.  QI/QN/QE stay UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


V26_SCHEMA = "ds02.stage2.f2-s1-typed-only-full401-replay.v26"
V26_RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v15"
REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-only-full401-replay-repair-report.v27"
RUNNER_REPORT_SCHEMA = "ds02.stage2.f2-s1-replay-runner-report.v27"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class ReplayV27Error(ValueError):
    """Raised when a v26 result cannot be reused safely."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayV27Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ReplayV27Error(f"JSON object required: {target}")
    return value


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ReplayV27Error(f"{name} must be a lowercase SHA-256")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ReplayV27Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def _binding(path: Path, role: str, *, digest: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise ReplayV27Error(f"bound {role} is missing: {path}")
    stat = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest or sha256_file(path),
    }


def _validate_v26_request(request_path: Path, request: Mapping[str, Any]) -> None:
    if request.get("schema") != "ds02.request.v1" or request.get("orchestration_schema") != V26_SCHEMA:
        raise ReplayV27Error("v26 request schema/orchestration binding differs")
    if request.get("status") != "READY_FOR_PARENT_IO_SLOT" or request.get("role") != "DEVELOPMENT":
        raise ReplayV27Error("v26 request is not the immutable development request")
    if request.get("qualification") != UNKNOWN:
        raise ReplayV27Error("v26 request qualification was promoted")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ReplayV27Error("v26 request claims model/CFD execution")
    if request.get("sha256") != canonical_sha(request):
        raise ReplayV27Error("v26 request canonical SHA differs")
    if not request_path.is_file():
        raise ReplayV27Error("v26 request disappeared")


def _validate_reusable(v26_request_path: Path | str, receipt_path: Path | str,
                       result_path: Path | str) -> dict[str, Any]:
    request_file = Path(v26_request_path).expanduser().resolve()
    receipt_file = Path(receipt_path).expanduser().resolve()
    result_file = Path(result_path).expanduser().resolve()
    request = _load(request_file)
    _validate_v26_request(request_file, request)
    receipt = _load(receipt_file)
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise ReplayV27Error("v26 execution receipt schema differs")
    if receipt.get("status") != "failed" or receipt.get("returncode") != 1:
        raise ReplayV27Error("v26 receipt is not the known output-print failure")
    if Path(str(receipt.get("output_root"))).resolve() != result_file.parent:
        raise ReplayV27Error("v26 result is outside the receipt output root")
    if receipt.get("terminal_storage_guard", {}).get("status") != "passed":
        raise ReplayV27Error("v26 terminal storage guard did not pass")
    before = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping) or dict(before) != dict(after):
        raise ReplayV27Error("v26 input hashes changed during the completed run")
    if not result_file.is_file():
        raise ReplayV27Error("v26 full401 result is missing")
    result = _load(result_file)
    if result.get("schema") != V26_RESULT_SCHEMA or result.get("runner_status") != "COMPLETE_PROVISIONAL_H5_READ":
        raise ReplayV27Error("v26 result is not a complete provisional H5-read result")
    if result.get("trajectory_read") is not True or result.get("original_path_fallback") != "FORBIDDEN":
        raise ReplayV27Error("v26 result lacks strict trajectory/fallback boundary")
    if result.get("qualification") != UNKNOWN or result.get("model_invoked") is not False:
        raise ReplayV27Error("v26 result qualification or model boundary changed")
    scope = result.get("typed_replay_scope")
    if not isinstance(scope, Mapping) or scope.get("raw_to_typed_reconstruction_invoked") is not False or scope.get("raw_to_label_complete") is not False:
        raise ReplayV27Error("v26 typed-only boundary is missing")
    window = result.get("window")
    if not isinstance(window, Mapping) or window.get("frame_count") != 401 or window.get("frame_start") != 0 or window.get("frame_stop") != 400:
        raise ReplayV27Error("v26 result is not the complete 401-frame window")
    if len(result.get("frame_observations", [])) != 401:
        raise ReplayV27Error("v26 result does not contain all frame observations")
    if len(result.get("labels", [])) != 21114 or len(result.get("receiver_volume_labels", [])) != 21114:
        raise ReplayV27Error("v26 result does not contain the exact 21114-particle label axes")
    denominator = result.get("initial_mass_denominator", {})
    if denominator.get("denominator_kg") != 21.114001002861187 or denominator.get("initial_missing_mass_kg") != 0.0:
        raise ReplayV27Error("v26 initial mass denominator differs")
    source = result.get("source_binding")
    if not isinstance(source, Mapping) or source.get("binding_status") != "EXACT_CURRENT_SOURCE_BOUND":
        raise ReplayV27Error("v26 source binding is not exact CURRENT")
    h5_entries = [(str(path), str(digest)) for path, digest in after.items()
                  if str(path).lower().endswith((".h5", ".hdf5"))]
    producer_sha = _require_sha(source.get("trajectory_h5_producer_sha256"), "result H5 producer SHA")
    if len(h5_entries) != 1 or h5_entries[0][1] != producer_sha:
        raise ReplayV27Error("v26 receipt does not preserve exactly one verified H5 input")
    stdout = receipt.get("stdout_sha256")
    if not isinstance(stdout, str) or len(stdout) != 64:
        raise ReplayV27Error("v26 stdout SHA is missing")
    return {
        "request": request,
        "receipt": receipt,
        "result": result,
        "request_binding": _binding(request_file, "v26_request"),
        "receipt_binding": _binding(receipt_file, "v26_execution_receipt"),
        "result_binding": _binding(result_file, "v26_full401_result"),
        "h5_input": {"path": h5_entries[0][0], "sha256": h5_entries[0][1], "content_hash_source": "v26_parent_receipt_after_run"},
        "stdout_sha256": stdout,
    }


def repair(v26_request_path: Path | str, receipt_path: Path | str,
           result_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    checked = _validate_reusable(v26_request_path, receipt_path, result_path)
    receipt = checked["receipt"]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "REUSED_V26_FULL401_OUTPUT; OUTPUT_SCHEMA_REPAIRED; DEVELOPMENT_UNKNOWN",
        "role": "DEVELOPMENT",
        "reuse_policy": {
            "mode": "REUSE_IMMUTABLE_RESULT_NO_HDF5_RERUN",
            "v26_calculation_complete": True,
            "v26_failure_scope": "runner stdout serialization only; result was already written",
            "fresh_full401_fallback": "PARENT_MUST_SCHEDULE_NEW_V27_RUN_IF_ANY_REUSE_CHECK_FAILS",
        },
        "v26_failure": {
            "receipt_status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "stdout_sha256": checked["stdout_sha256"],
            "termination_reason": receipt.get("termination_reason"),
        },
        "reused_result": checked["result_binding"],
        "source_receipt": checked["receipt_binding"],
        "source_request": checked["request_binding"],
        "inherited_hdf5": checked["h5_input"],
        "result_contract": {
            "schema": V26_RESULT_SCHEMA,
            "trajectory_read": True,
            "frames": 401,
            "particles": 418104,
            "fluid_labels": 21114,
            "raw_to_typed_reconstruction_invoked": False,
            "raw_to_label_complete": False,
            "qualification": UNKNOWN,
        },
        "execution_boundary": {
            "repair_reads_hdf5": False,
            "repair_reads_bi4": False,
            "repair_reruns_full401": False,
            "reused_immutable_result": True,
            "model_invoked": False,
            "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
        },
        "resource_observation": {
            "repair_source_bytes_read": checked["result_binding"]["bytes"] + checked["receipt_binding"]["bytes"] + checked["request_binding"]["bytes"],
            "hdf5_bytes_read_by_repair": 0,
            "bi4_bytes_read_by_repair": 0,
            "new_storage_bytes": 0,
            "full401_cpu_reused_from_v26": True,
        },
        "qualification": UNKNOWN,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def _load_v25() -> Any:
    v25_path = Path(__file__).resolve().with_name("ds_data02_stage2_f2_replay_runner_v25.py")
    if not v25_path.is_file():
        raise ReplayV27Error(f"v25 runner is unavailable for fresh fallback: {v25_path}")
    spec = importlib.util.spec_from_file_location("ds_data02_stage2_f2_replay_runner_v25_immutable", v25_path)
    if spec is None or spec.loader is None:
        raise ReplayV27Error("cannot load immutable v25 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_fresh(profile: Path, request: Path, path_map: Path, output: Path,
              *, io_slot_approved: bool) -> dict[str, Any]:
    v25 = _load_v25()
    profile_value = v25._load_json(profile)
    request_value = v25._load_json(request)
    overlay_receipt = v25._overlay_receipt(path_map)
    paths = v25._path_map(path_map)
    try:
        result = v25.run(profile_value, request_value, paths,
                         io_slot_approved=io_slot_approved,
                         overlay_receipt=overlay_receipt,
                         audit_allowed_paths=(str(output), str(profile), str(request), str(path_map)))
    except (OSError, v25.ReplayV25BindingError) as error:
        audit = getattr(error, "audit", None)
        if audit is not None:
            failure = v25._failure_receipt(error, audit)
            failure["schema"] = RUNNER_REPORT_SCHEMA
            failure["runner_version"] = "v27"
            _write_new(output, failure)
            return failure
        raise ReplayV27Error(str(error)) from error
    status = str(result.get("runner_status", result.get("status", "VALIDATED_PENDING_IO_SLOT")))
    result["status"] = status
    result["runner_version"] = "v27"
    result["schema_version_note"] = "v25 consumer result retained; v27 adds explicit top-level status"
    _write_new(output, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    repair_parser = sub.add_parser("repair")
    repair_parser.add_argument("--v26-request", type=Path, required=True)
    repair_parser.add_argument("--v26-receipt", type=Path, required=True)
    repair_parser.add_argument("--v26-result", type=Path, required=True)
    repair_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--profile", type=Path, required=True)
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--path-map", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "repair":
            result = repair(args.v26_request, args.v26_receipt, args.v26_result, args.output)
        else:
            result = run_fresh(args.profile, args.request, args.path_map, args.output,
                               io_slot_approved=args.io_slot_approved)
    except (OSError, ReplayV27Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result.get("status"), "schema": result.get("schema")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
