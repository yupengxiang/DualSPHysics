#!/usr/bin/env python3
"""Build a CPU-only v27 repair request for the completed v26 full401 result.

The v26 consumer wrote a complete 401-frame result and then failed in its
runner's final ``result["status"]`` print.  This builder verifies the
immutable v26 request, receipt, and result contract without reading HDF5/BI4,
then emits a new request that runs the v27 repair path.  The repair merely
normalizes the result schema and records the failed-print boundary.  If any
reuse check fails, the builder refuses to manufacture credit and the parent
must schedule a fresh v27 I/O run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.request.v1"
ORCHESTRATION_SCHEMA = "ds02.stage2.f2-s1-typed-only-full401-replay-repair.v27"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V26_SCHEMA = "ds02.stage2.f2-s1-typed-only-full401-replay.v26"
HEX64 = set("0123456789abcdef")


class TypedReplayV27RequestError(ValueError):
    """Raised when the immutable v26 output is not safely reusable."""


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
        raise TypedReplayV27RequestError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise TypedReplayV27RequestError(f"JSON object required: {target}")
    return value


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise TypedReplayV27RequestError(f"{name} must be a lowercase SHA-256")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise TypedReplayV27RequestError(f"source is missing: {role}: {path}")
    stat = path.stat()
    return {"role": role, "path": str(path.resolve()), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def _validate_v26(request_path: Path, receipt_path: Path, result_path: Path) -> dict[str, Any]:
    request = _load(request_path)
    if request.get("schema") != SCHEMA or request.get("orchestration_schema") != V26_SCHEMA:
        raise TypedReplayV27RequestError("v26 request schema differs")
    if request.get("status") != "READY_FOR_PARENT_IO_SLOT" or request.get("qualification") != UNKNOWN:
        raise TypedReplayV27RequestError("v26 request is not immutable development scope")
    if request.get("sha256") != canonical_sha(request):
        raise TypedReplayV27RequestError("v26 request canonical SHA differs")
    receipt = _load(receipt_path)
    result = _load(result_path)
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "failed" or receipt.get("returncode") != 1:
        raise TypedReplayV27RequestError("v26 receipt is not the known final-print failure")
    if Path(str(receipt.get("output_root"))).resolve() != result_path.parent:
        raise TypedReplayV27RequestError("v26 result is outside receipt output root")
    if receipt.get("terminal_storage_guard", {}).get("status") != "passed":
        raise TypedReplayV27RequestError("v26 storage guard did not pass")
    before = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(before, Mapping) or dict(before) != dict(after or {}):
        raise TypedReplayV27RequestError("v26 input hashes changed after run")
    if result.get("schema") != "ds02.stage2.f2-s1-replay-result.v15" or result.get("runner_status") != "COMPLETE_PROVISIONAL_H5_READ":
        raise TypedReplayV27RequestError("v26 result is not complete")
    if result.get("trajectory_read") is not True or result.get("original_path_fallback") != "FORBIDDEN" or result.get("qualification") != UNKNOWN:
        raise TypedReplayV27RequestError("v26 result boundary/qualification differs")
    scope = result.get("typed_replay_scope")
    if not isinstance(scope, Mapping) or scope.get("raw_to_typed_reconstruction_invoked") is not False or scope.get("raw_to_label_complete") is not False:
        raise TypedReplayV27RequestError("v26 typed-only scope differs")
    window = result.get("window")
    if not isinstance(window, Mapping) or window.get("frame_count") != 401 or window.get("frame_start") != 0 or window.get("frame_stop") != 400:
        raise TypedReplayV27RequestError("v26 result window differs")
    if len(result.get("frame_observations", [])) != 401 or len(result.get("labels", [])) != 21114 or len(result.get("receiver_volume_labels", [])) != 21114:
        raise TypedReplayV27RequestError("v26 output axes are incomplete")
    denominator = result.get("initial_mass_denominator", {})
    if denominator.get("denominator_kg") != 21.114001002861187 or denominator.get("initial_missing_mass_kg") != 0.0:
        raise TypedReplayV27RequestError("v26 mass denominator differs")
    source = result.get("source_binding")
    if not isinstance(source, Mapping) or source.get("binding_status") != "EXACT_CURRENT_SOURCE_BOUND":
        raise TypedReplayV27RequestError("v26 CURRENT source binding differs")
    h5_entries = [(str(path), str(digest)) for path, digest in after.items() if str(path).lower().endswith((".h5", ".hdf5"))]
    h5_sha = _require_sha(source.get("trajectory_h5_producer_sha256"), "trajectory H5 producer SHA")
    if len(h5_entries) != 1 or h5_entries[0][1] != h5_sha:
        raise TypedReplayV27RequestError("v26 receipt does not preserve one verified H5 source")
    return {"request": request, "receipt": receipt, "result": result, "h5_path": h5_entries[0][0], "h5_sha": h5_sha}


def build_request(v26_request_path: Path | str, v26_receipt_path: Path | str,
                  v26_result_path: Path | str, runner_path: Path | str,
                  output_path: Path | str) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise TypedReplayV27RequestError(f"refusing to overwrite request: {output}")
    request_file = Path(v26_request_path).expanduser().resolve()
    receipt_file = Path(v26_receipt_path).expanduser().resolve()
    result_file = Path(v26_result_path).expanduser().resolve()
    runner = Path(runner_path).expanduser().resolve()
    checked = _validate_v26(request_file, receipt_file, result_file)
    runner_binding = _binding(runner, "v27_repair_runner")
    request_binding = _binding(request_file, "v26_request")
    receipt_binding = _binding(receipt_file, "v26_execution_receipt")
    result_binding = _binding(result_file, "v26_full401_result")
    command = [
        sys.executable, str(runner), "repair",
        "--v26-request", str(request_file),
        "--v26-receipt", str(receipt_file),
        "--v26-result", str(result_file),
        "--output", "{attempt_root}/typed-replay-v27/f2-s1-typed-only-full401-repair-v27.json",
    ]
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "orchestration_schema": ORCHESTRATION_SCHEMA,
        "request_id": "f2-s1-portable-typed-only-full401-replay-repair-v27-001",
        "attempt_id": "portable-typed-only-full401-repair-v27-001",
        "status": "READY_FOR_PARENT_CPU_SLOT",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_scope": {
            "current_case_index": 78,
            "frames": 401,
            "particles": 418104,
            "fluid_labels": 21114,
            "identity_key": "(Zone,Idp)",
            "initial_mass_denominator_kg": 21.114001002861187,
            "trajectory_h5_sha256_inherited": checked["h5_sha"],
        },
        "reuse_scope": {
            "mode": "REUSE_IMMUTABLE_V26_FULL401_RESULT",
            "full401_calculation_rerun": False,
            "repair_reads_hdf5": False,
            "repair_reads_bi4": False,
            "source_result_schema": "ds02.stage2.f2-s1-replay-result.v15",
            "source_result_runner_status": "COMPLETE_PROVISIONAL_H5_READ",
            "source_result_qualification": UNKNOWN,
            "fallback": "if any immutable check fails, reject and schedule fresh v27 I/O; no inferred credit",
        },
        "reused_bindings": [request_binding, receipt_binding, result_binding, runner_binding],
        "inherited_hdf5_provenance": {
            "path": checked["h5_path"],
            "sha256": checked["h5_sha"],
            "content_hash_source": "V26_PARENT_EXECUTION_RECEIPT_AFTER_RUN",
            "actionable_for_repair": False,
            "hdf5_read_by_v27_repair": False,
        },
        "command": command,
        "input_files": [request_binding["path"], receipt_binding["path"], result_binding["path"], runner_binding["path"]],
        "input_hashes": {item["path"]: item["sha256"] for item in [request_binding, receipt_binding, result_binding, runner_binding]},
        "resource_request": {
            "cpu_threads": 1,
            "max_wall_seconds": 300,
            "max_rss_observational_bytes": 512 * 1024**2,
            "source_bytes_read_by_repair": result_binding["bytes"] + receipt_binding["bytes"] + request_binding["bytes"] + runner_binding["bytes"],
            "hdf5_bytes_read": 0,
            "bi4_bytes_read": 0,
            "new_storage_bytes": 0,
            "full401_compute": "reused from immutable v26 result",
        },
        "execution_contract": {
            "hdf5_or_bi4_read": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
            "output_new_only": True,
            "source_hash_revalidation": "v26 receipt input_hashes_at_launch == input_hashes_after_run plus v26 result contract",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
    }
    request["sha256"] = canonical_sha(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(request, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return request


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v26-request", type=Path, required=True)
    parser.add_argument("--v26-receipt", type=Path, required=True)
    parser.add_argument("--v26-result", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build_request(args.v26_request, args.v26_receipt, args.v26_result,
                              args.runner, args.output)
    except (OSError, json.JSONDecodeError, TypedReplayV27RequestError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"path": str(args.output.resolve()), "sha256": value["sha256"],
                      "status": value["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
