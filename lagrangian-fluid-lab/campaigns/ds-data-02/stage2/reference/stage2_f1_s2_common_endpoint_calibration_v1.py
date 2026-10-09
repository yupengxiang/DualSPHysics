#!/usr/bin/env python3
"""Prepare a source-bound F1-S2 common-time native endpoint calibration task.

This is a metadata-only bridge from the terminal ROOT277/278 .5 s pair to
the existing ten-file ROOT279 observer.  It reads only proof/request/receipt
JSON and the readiness contract.  The ten native Part files remain deferred;
the parent must bind their post-reservation SHA/stat records.  Brackets are
reported as actual saved times and are never interpolated into a field value
or promoted to a time/output error bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CHECKPOINTS = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
READINESS = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_fourteen_scientific_readiness_v5.json"
CASES = {
    "same_cfl": CHECKPOINTS / "F1_S2_DP020_SAME_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_277.json",
    "half_cfl": CHECKPOINTS / "F1_S2_DP020_HALF_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_278.json",
}
SUPPORTING = {
    "owner": CHECKPOINTS / "F1_S2_CONTINUOUS_OWNER_AUDIT_V2_ACTUAL_ROOT_VERIFICATION_227.json",
    "frame0_support": CHECKPOINTS / "F1_S2_INITIAL_SUPPORT_V2_ACTUAL_ROOT_VERIFICATION_233.json",
    "query1": CHECKPOINTS / "F1_S2_QUERY1_ENDPOINT_V4_ACTUAL_ROOT_VERIFICATION_234.json",
    "query234": CHECKPOINTS / "F1_S2_QUERY234_ENDPOINT_V2_ACTUAL_ROOT_VERIFICATION_231.json",
    "cfl_entry": CHECKPOINTS / "F1_CFL_ENTRYPOINT_V2_ACTUAL_ROOT_VERIFICATION_260.json",
    "reader_calibration": CHECKPOINTS / "OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json",
}
SCHEMA = "ds02.stage2.f1-s2.common-endpoint-calibration.v1"
MAX_SMALL_BYTES = 16 * 1024 * 1024
QUERY_TIMES = (0.0, 0.25, 0.5)
PART_INDICES = (0, 49, 50, 99, 100)


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during metadata read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after}


def _small_hash(path: Path, label: str) -> dict[str, Any]:
    _, record = _small_json(path, label)
    return record


def _proof_edge(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, proof_record = _small_json(path, label)
    status = str(proof.get("status", ""))
    if not status.startswith("VERIFIED_ACTUAL"):
        raise BuildFailure(f"{label} is not an independently verified actual proof: {status}")
    if proof.get("scientific_qualification", {}).get("QI") not in (None, "UNKNOWN"):
        raise BuildFailure(f"{label} grants unsupported QI")
    request = proof.get("request")
    receipt = proof.get("receipt")
    request_sha = proof.get("request_sha256")
    receipt_sha = proof.get("receipt_sha256")
    if not all(isinstance(value, str) for value in (request, receipt, request_sha, receipt_sha)):
        raise BuildFailure(f"{label} lacks request/receipt SHA edges")
    request_record = _small_hash(Path(request), f"{label} request")
    receipt_record = _small_hash(Path(receipt), f"{label} receipt")
    if request_record["sha256"] != request_sha or receipt_record["sha256"] != receipt_sha:
        raise BuildFailure(f"{label} request/receipt SHA edge changed")
    return proof, {
        "proof": proof_record,
        "request": request_record,
        "receipt": receipt_record,
        "status": status,
    }


def _pair_member(path: Path, label: str, expected_cfl: float) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, edge = _proof_edge(path, label)
    if proof.get("native_frame_files_stat_only_count") != 101:
        raise BuildFailure(f"{label} does not contain the terminal 101-frame source scope")
    summary = proof.get("RunPARTs_summary")
    run_out = proof.get("Run_out")
    brackets = proof.get("saved_query_brackets")
    if not isinstance(summary, dict) or not isinstance(run_out, dict) or not isinstance(brackets, list):
        raise BuildFailure(f"{label} lacks RunPARTs/Run.out/bracket metadata")
    if summary.get("rows") != 101 or summary.get("initial_time_s") != 0.0 or summary.get("initial_NpfSim") != 42500.0:
        raise BuildFailure(f"{label} terminal RunPARTs baseline differs")
    if summary.get("saved_window_new_exclusion_sums") != {"NpOut": 0.0, "NpOutPos": 0.0, "NpOutRho": 0.0, "NpOutMov": 0.0}:
        raise BuildFailure(f"{label} has exclusions in the pair baseline")
    if summary.get("clamped_dt_saved_intervals") != 0:
        raise BuildFailure(f"{label} has clamped saved intervals")
    if run_out.get("effective_CFL") != expected_cfl or run_out.get("TimeMax_s") != 0.5 or run_out.get("SaveDt_logging_active") is not True:
        raise BuildFailure(f"{label} runtime controls do not match expected CFL/.5s SaveDt")
    if [item.get("query_s") for item in brackets] != list(QUERY_TIMES):
        raise BuildFailure(f"{label} query bracket set is not 0/.25/.5")
    for item in brackets:
        if item.get("interpolation") is not False or item.get("left_part") not in PART_INDICES or item.get("right_part") not in PART_INDICES:
            raise BuildFailure(f"{label} bracket contains interpolation or unexpected part index")
    return proof, {**edge, "mode": label, "effective_cfl": expected_cfl, "RunPARTs": summary, "Run_out": run_out, "saved_query_brackets": brackets}


def build(args: argparse.Namespace) -> dict[str, Any]:
    same, same_edge = _pair_member(CASES["same_cfl"], "ROOT277 same-CFL", 0.2)
    half, half_edge = _pair_member(CASES["half_cfl"], "ROOT278 half-CFL", 0.1)
    support_edges: dict[str, Any] = {}
    for key, path in SUPPORTING.items():
        _, support_edges[key] = _proof_edge(path, f"F1-S2 {key} proof")
    readiness, readiness_record = _small_json(READINESS, "fourteen-sentinel readiness")
    if readiness.get("schema") != "ds02.stage2.fourteen-scientific-readiness.v5":
        raise BuildFailure("readiness schema mismatch")
    tolerance = readiness.get("frozen_tolerance")
    if not isinstance(tolerance, dict):
        raise BuildFailure("readiness lacks frozen tolerances")
    for key in ("position_fraction_of_registered_L", "velocity_and_ke_fraction_of_registered_nonzero_scale", "time_and_output_each_fraction_of_task_tolerance"):
        if key not in tolerance:
            raise BuildFailure(f"readiness lacks {key}")
    bracket_summary = {}
    for label, edge in (("same_cfl", same_edge), ("half_cfl", half_edge)):
        bracket_summary[label] = [{"query_s": item["query_s"], "left_part": item["left_part"], "left_time_s": item["left_time_s"], "right_part": item["right_part"], "right_time_s": item["right_time_s"], "width_s": item["right_time_s"] - item["left_time_s"], "exact": item["exact"], "interpolation": item["interpolation"]} for item in edge["saved_query_brackets"]]
    return {
        "schema": SCHEMA,
        "status": "SOURCE_PREPARED_WAITING_ROOT310_TEN_NATIVE_SNAPSHOT",
        "sentinel_id": "F1-S2",
        "source_edges": {"same_cfl": same_edge, "half_cfl": half_edge, "support": support_edges, "readiness": readiness_record},
        "actual_pair_controls": {
            "same_cfl": {"effective_cfl": 0.2, "TimeMax_s": 0.5, "SaveDt_logging_active": True, "rows": 101},
            "half_cfl": {"effective_cfl": 0.1, "TimeMax_s": 0.5, "SaveDt_logging_active": True, "rows": 101},
            "common_output_contract": {"query_times_s": list(QUERY_TIMES), "output_interval_s": 0.005, "interpolation": False, "extrapolation": False},
        },
        "observed_brackets": bracket_summary,
        "observation_plan": {
            "next_parent_namespace": "ROOT279",
            "source_snapshot_namespace": "ROOT310",
            "selected_part_indices_per_run": list(PART_INDICES),
            "selected_native_file_count": 10,
            "fields": ["Idp", "role/Type/Mk", "position", "velocity", "Rhop", "native MassFluid", "native Dp"],
            "fluid_aggregates": ["native-MassFluid weighted COM", "native-MassFluid weighted velocity", "native-MassFluid KE"],
            "source_calibration": "ROOT217 official writer/decoder fixture; storage calibration does not assert production world-axis equivalence",
            "guard": {"pre_sha_stat": True, "post_decode_sha_stat": True, "no_bi4_h5_vtk_reopen_by_builder": True, "no_interpolation": True},
        },
        "frozen_tolerances": tolerance,
        "interpretation": {
            "time_bracket_width": "observed saved-output bracket metadata only; not a measured output error bound",
            "same_half_difference": "diagnostic CFL difference; not a truth/reference error",
            "position_velocity_ke": "compare only after native fields are guarded; no QN until source axis/unit and task scales are closed",
            "event_time": "UNKNOWN; no event characteristic T is registered",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "admission": {
            "owner": "ROOT227 340 kg source-owner closure is bound; discrete/native sample mass remains separate",
            "initial_support": "ROOT233 frame-0 limited support diagnostic; dynamic selected fields still require ROOT279",
            "runtime_controls": "ROOT277/278 terminal pair proves .2/.1 CFL and common .5 s SaveDt metadata",
            "next_gate": "ROOT310 must produce exact ten selected Part path/SHA/stat records before ROOT279 can run",
        },
        "read_scope": {"proof_json_read": True, "request_receipt_json_read": True, "native_payload_read": False, "hdf5_read": False, "solver_launch": False},
    }


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args)
        _write_once(args.output, result)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F1_S2_COMMON_ENDPOINT_CALIBRATION: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(_absolute(args.output)), "query_times_s": list(QUERY_TIMES), "selected_native_count": 10, "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
