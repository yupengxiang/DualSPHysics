#!/usr/bin/env python3
"""Bind the completed F7 same-CFL v5 RunPARTs as an observed end gate.

The consumed v1 gate was based on the older 0.02-second, 601-row reference.
This forward gate reads the exact v5 terminal receipt and its small native
RunPARTs.csv, derives the actual ``-tmax``/``-tout`` command values, and keeps
the observed 1201-row/12.00003209155591-second result.  It never infers a
1202-row count and never opens BI4/HDF5 or grants scientific qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/"
    "execution-receipt.json"
)
CASE_ID = "F7_OBSTACLE_QUINTIC_B08_A065"
ATTEMPT_ID = "F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.f7-same-cfl-runparts-end-gate.v2"


class GateError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GateError(f"JSON object required: {path}")
    return value


def _command_value(command: list[Any], prefix: str) -> float:
    for item in command:
        token = str(item)
        if token.startswith(prefix):
            try:
                value = float(token[len(prefix):])
            except ValueError as error:
                raise GateError(f"malformed {prefix} command token: {token}") from error
            if not math.isfinite(value) or value <= 0:
                raise GateError(f"nonpositive {prefix} command value: {token}")
            return value
    raise GateError(f"bound command lacks {prefix} token")


def _runparts_parser():
    # Keep the exact native parser as a source binding.  Importing it is
    # bounded and reads no repository data until parse() receives RunPARTs.
    package_root = str(ROOT)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from scripts.f8_r008_runparts_realstr_cadence_diagnostic_v1 import parse_raw_runparts_csv
    return parse_raw_runparts_csv


def build_gate(receipt_path: Path | str = RECEIPT) -> dict[str, Any]:
    receipt_file = Path(receipt_path).expanduser().resolve()
    receipt = load_json(receipt_file)
    if receipt.get("schema") != "ds02.stage2.external-solver-report.v5":
        raise GateError("bound receipt is not the actual F7 v5 solver report")
    if receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise GateError("F7 v5 receipt is not terminal development-complete")
    if receipt.get("attempt_id") != ATTEMPT_ID:
        raise GateError("F7 v5 receipt attempt differs")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not True:
        raise GateError("F7 v5 receipt invocation flags are inconsistent")
    execution = receipt.get("execution")
    filesystem = receipt.get("filesystem")
    if not isinstance(execution, Mapping) or not isinstance(filesystem, Mapping):
        raise GateError("F7 v5 receipt lacks execution/filesystem binding")
    command = execution.get("launch_argv")
    if not isinstance(command, list):
        raise GateError("F7 v5 launch argv is missing")
    tmax = _command_value(command, "-tmax:")
    tout = _command_value(command, "-tout:")
    if not math.isclose(tout, 0.01, rel_tol=0.0, abs_tol=1e-15):
        raise GateError(f"actual command TimeOut is not 0.01 s: {tout}")
    output_root = Path(str(filesystem.get("output_root", ""))).expanduser().resolve()
    runparts = output_root / "solver_output" / "RunPARTs.csv"
    if not runparts.is_file():
        raise GateError(f"actual v5 RunPARTs is missing: {runparts}")
    parse = _runparts_parser()
    parsed = parse(runparts.read_bytes())
    rows = parsed["raw_rows"]
    times = [float(item["time_step_binary64"]["value"]) for item in rows]
    intervals = [right - left for left, right in zip(times, times[1:])]
    if not intervals or any(not math.isfinite(value) or value <= 0 for value in intervals):
        raise GateError("actual RunPARTs has invalid positive time intervals")
    last_time = float(parsed["last_recorded_time_s"])
    if last_time < tmax:
        raise GateError("actual RunPARTs does not reach the bound solver TimeMax")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "OBSERVED_NATIVE_SAME_CFL_RUNPARTS",
        "role": "DEVELOPMENT",
        "family_id": "F7",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "receipt": {
            "path": str(receipt_file),
            "sha256": sha256_file(receipt_file),
            "bytes": receipt_file.stat().st_size,
            "mtime_ns": receipt_file.stat().st_mtime_ns,
            "status": receipt["status"],
        },
        "runparts": {
            "path": str(runparts),
            "sha256": sha256_file(runparts),
            "bytes": runparts.stat().st_size,
            "mtime_ns": runparts.stat().st_mtime_ns,
            "first_part": parsed["first_part"],
            "last_part": parsed["last_part"],
            "numeric_rows": parsed["data_row_count"],
            "first_time_s": times[0],
            "last_time_s": last_time,
            "last_time_token": parsed["last_recorded_time_token"],
            "native_parser_payload_sha256": parsed["raw_payload_sha256"],
        },
        "observed_control": {
            "command": [str(value) for value in command],
            "time_max_s": tmax,
            "time_out_s": tout,
            "time_out_source": "actual_terminal_receipt.execution.launch_argv",
            "time_max_source": "actual_terminal_receipt.execution.launch_argv",
            "interval_min_s": min(intervals),
            "interval_max_s": max(intervals),
            "interval_mean_s": sum(intervals) / len(intervals),
            "intervals_are_solver_save_timestamps": True,
        },
        "checks": {
            "receipt_terminal": True,
            "native_solver_invoked": True,
            "command_time_out_0p01": True,
            "terminal_time_max_reached": True,
            "observed_1201_rows": parsed["data_row_count"] == 1201,
            "observed_part_0_to_1200": parsed["first_part"] == 0 and parsed["last_part"] == 1200,
            "planned_1202_rows_claimed": False,
            "planned_12p00003209155591_claimed_as_expected": False,
            "hdf5_or_bi4_opened_by_gate": False,
        },
        "scientific_credit": "NONE; source-bound development control/end gate only",
        "qualification": dict(UNKNOWN),
        "limitations": [
            "The 1201 rows and 12.00003209155591 s endpoint are actual v5 evidence; 1202 is not required or claimed.",
            "RunPARTs is telemetry/provenance and cannot replace Part_*.bi4 typed arrays for labels.",
            "The gate does not infer the half-CFL result and grants no QI/QN/QE.",
        ],
    }
    result["sha256"] = canonical_sha(result)
    return result


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise GateError(f"refusing to overwrite existing gate: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build_gate(args.receipt)
    write_new(args.output, value)
    print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                      "rows": value["runparts"]["numeric_rows"],
                      "last_time_s": value["runparts"]["last_time_s"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
