#!/usr/bin/env python3
"""Prove SaveDt row-count semantics from small text receipts.

The helper reads only ``execution-receipt.json``, ``DtAllInfo.csv``,
``RunPARTs.csv``, and ``Run.out`` for a completed guarded run.  It does not
open H5 or native Part payloads and does not launch anything.  The default
artifact records the completed F4-S1 same-CFL run and leaves its half-CFL
partner explicitly pending.  The same analyzer can be applied to the half-CFL
receipt after the parent dispatches it.

For the observed GPU/Verlet run, ``DtAllInfo`` has 10035 rows while the sum of
the RunPARTs ``Steps`` column is 10036.  The helper preserves that mismatch as
evidence.  It records the source-level GPU initialization and PART accounting
needed to explain the one-row offset, while leaving the relationship to the
Run.out summary step count UNKNOWN rather than declaring one row per reported
step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.savedt-row-count-semantics.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DEFAULT_OUTPUT_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/"
    "f4-s1-dp0-savedt-same_cfl-primary-001"
)
DEFAULT_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/same_cfl.json"
PENDING_HALF_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/half_cfl.json"
GPU_SINGLE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/src/source/JSphGpuSingle.cpp"
)
JSPH = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/src/source/JSph.cpp"
)
SAVE_DT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/src/source/JDsSaveDt.cpp"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path)}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_evidence(path: Path, needle: str) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = [{"line": number, "text": line.strip()}
            for number, line in enumerate(lines, 1) if needle in line]
    if not hits:
        raise ValueError(f"source needle missing: {path}: {needle}")
    result = record(path)
    result.update({"needle": needle, "hits": hits})
    return result


def parse_dtall(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or not lines[0].startswith("Time [s];Dtf [s]"):
        raise ValueError(f"unexpected DtAllInfo header: {path}")
    for line in lines[1:]:
        if not line.strip():
            continue
        values = line.split(";")
        if len(values) != 2:
            raise ValueError(f"unexpected DtAllInfo row: {line!r}")
        rows.append((float(values[0]), float(values[1])))
    return rows


def parse_runparts(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or not lines[0].startswith("Part;TimeStep [s];Steps"):
        raise ValueError(f"unexpected RunPARTs header: {path}")
    rows: list[list[str]] = []
    for line in lines[1:]:
        if line and line[0].isdigit():
            rows.append(line.split(";"))
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    return {
        "numeric_rows": len(rows),
        "first_part": int(rows[0][0]),
        "last_part": int(rows[-1][0]),
        "first_time_s": float(rows[0][1]),
        "last_time_s": float(rows[-1][1]),
        "sum_steps": sum(int(row[2]) for row in rows),
        "first_nonzero_part_steps": next((int(row[2]) for row in rows if int(row[2]) > 0), 0),
        "last_part_steps": int(rows[-1][2]),
    }


def parse_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    step_match = re.search(r"Steps of simulation\.*:\s*([0-9,]+)", text)
    clamp_match = re.search(r"DTs adjusted to DtMin\.*:\s*([0-9,]+)", text)
    alg_match = re.search(r"StepAlgorithm=\"([^\"]+)\"", text)
    return {
        "reported_steps": int(step_match.group(1).replace(",", "")) if step_match else "UNKNOWN",
        "aggregate_clamp_count": int(clamp_match.group(1).replace(",", "")) if clamp_match else "UNKNOWN",
        "step_algorithm": alg_match.group(1) if alg_match else "UNKNOWN",
    }


def analyze(output_root: Path, request_path: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    request_path = request_path.resolve()
    receipt_path = output_root / "execution-receipt.json"
    solver_output = output_root / "solver_output"
    dtall_path = solver_output / "DtAllInfo.csv"
    runparts_path = solver_output / "RunPARTs.csv"
    runout_path = solver_output / "Run.out"
    receipt = load_json(receipt_path)
    request = load_json(request_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"actual receipt is not completed: {receipt_path}")
    dt_rows = parse_dtall(dtall_path)
    part = parse_runparts(runparts_path)
    runout = parse_runout(runout_path)
    endpoint = part["last_time_s"]
    sum_dtf = sum(dt for _, dt in dt_rows)
    continuity = max(
        (abs(time + dt - dt_rows[index + 1][0]) for index, (time, dt) in enumerate(dt_rows[:-1])),
        default=0.0,
    )
    last_step_endpoint = (dt_rows[-1][0] + dt_rows[-1][1]) if dt_rows else None
    sum_step_relation = part["sum_steps"] - len(dt_rows)
    runout_relation = (
        "UNKNOWN_REPORTED_STEP_COUNTER_SEMANTICS"
        if runout["reported_steps"] != len(dt_rows)
        else "MATCH"
    )
    command = receipt.get("command", [])
    gpu_backend = any(str(item).startswith("-gpu:") for item in command)
    source_proof = {
        "gpu_initial_part_offset": source_evidence(GPU_SINGLE, "PartNstep=-1; Part++;"),
        "gpu_final_step_increment": source_evidence(GPU_SINGLE, "Nstep++;"),
        "runparts_steps_formula": source_evidence(JSPH, "const int partnsteps=(Nstep-PartNstep);"),
        "savedt_all_dt_append": source_evidence(SAVE_DT, "AllDts[CountAllDts]=TDouble2(timestep,dtfinal);"),
        "savedt_all_dt_count": source_evidence(SAVE_DT, "CountAllDts++;"),
        "gpu_savedt_final_dt_call": source_evidence(GPU_SINGLE, "const double dt=DtVariable(true);"),
    }
    relation_status = "PASS" if gpu_backend and runout["step_algorithm"] == "Verlet" and sum_step_relation == 1 else "UNKNOWN"
    requested_window = request.get("physical_window_s")
    return {
        "status": "ACTUAL_TEXT_RECEIPT_ANALYZED",
        "request": {
            "file": record(request_path),
            "case_id": request.get("case_id"),
            "attempt_id": request.get("attempt_id"),
            "command": request.get("command"),
            "requested_window_s": requested_window,
            "requested_save_interval_s": request.get("save_interval_s"),
        },
        "receipt": record(receipt_path),
        "output_text": {
            "DtAllInfo": record(dtall_path),
            "RunPARTs": record(runparts_path),
            "Run.out": record(runout_path),
        },
        "backend_and_algorithm": {
            "gpu_cli_present": gpu_backend,
            "step_algorithm": runout["step_algorithm"],
            "scope": "GPU single / Verlet row-count convention only; do not generalize to other backends",
        },
        "counts": {
            "DtAllInfo_data_rows": len(dt_rows),
            "RunPARTs_numeric_rows": part["numeric_rows"],
            "RunPARTs_sum_Steps": part["sum_steps"],
            "RunPARTs_first_nonzero_part_Steps": part["first_nonzero_part_steps"],
            "RunPARTs_last_time_s": endpoint,
            "Run.out_reported_steps": runout["reported_steps"],
            "Run.out_aggregate_clamp_count": runout["aggregate_clamp_count"],
            "observed_RunPARTs_sum_minus_DtAll_rows": sum_step_relation,
            "gpu_verlet_offset_relation": relation_status,
            "Run.out_to_DtAll_relation": runout_relation,
        },
        "time_integrity": {
            "DtAll_first_time_s": dt_rows[0][0] if dt_rows else None,
            "DtAll_last_time_s": dt_rows[-1][0] if dt_rows else None,
            "DtAll_last_time_plus_dtf_s": last_step_endpoint,
            "RunPARTs_final_time_s": endpoint,
            "sum_Dtf_s": sum_dtf,
            "sum_Dtf_minus_RunPARTs_endpoint_s": sum_dtf - endpoint,
            "max_adjacent_continuity_error_s": continuity,
            "endpoint_match_within_1e-10": abs(last_step_endpoint - endpoint) <= 1e-10 if last_step_endpoint is not None else False,
            "sum_Dtf_match_within_1e-10": abs(sum_dtf - endpoint) <= 1e-10,
        },
        "semantic_explanation": {
            "observed": "DtAllInfo rows equal RunPARTs Steps sum minus one for this GPU/Verlet run.",
            "source_reason": "GPU single initializes PartNstep=-1 and RunPARTs writes Nstep-PartNstep; this creates a one-count PART accounting offset in the Steps column.",
            "scope_limit": "This explains the observed text receipt relation; it does not prove one DtAllInfo row per Run.out reported step because Run.out reports 10036 while DtAllInfo has 10035.",
            "dtall_semantics": "DtAllInfo stores AddValues at the current pre-increment TimeStep with final dt; last row plus Dtf reaches the final saved time.",
            "clamp_semantics": "Run.out provides only aggregate clamp count; no per-row clamp location is inferred.",
        },
        "source_proof": source_proof,
        "solver_started_by_helper": False,
        "hdf5_read_by_helper": False,
        "native_payload_read_by_helper": False,
    }


def pending_request(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "UNKNOWN_MISSING_REQUEST", "path": str(path)}
    request = load_json(path)
    return {
        "status": "PENDING_GUARDED_RUN",
        "request": record(path),
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "requested_window_s": request.get("physical_window_s"),
        "command": request.get("command"),
        "launch_disabled": request.get("launch_disabled"),
        "no_actual_rows_claimed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--pending-half-request", type=Path, default=PENDING_HALF_REQUEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "schema": SCHEMA,
        "status": "ACTUAL_SAME_PENDING_HALF_ROW_SEMANTICS",
        "current_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                        capture_output=True, text=True).stdout.strip(),
        "actual": analyze(args.output_root, args.request),
        "pending_half_pair": pending_request(args.pending_half_request),
        "scope": {
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    if args.output.exists():
        raise FileExistsError(f"refuse to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "dt_rows": result["actual"]["counts"]["DtAllInfo_data_rows"],
                      "runparts_sum_steps": result["actual"]["counts"]["RunPARTs_sum_Steps"],
                      "solver_started": False, "hdf5_read": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
