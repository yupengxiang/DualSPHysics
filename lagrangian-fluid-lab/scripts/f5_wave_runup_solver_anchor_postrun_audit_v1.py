#!/usr/bin/env python3
"""Read-only reconciliation of the F5 anchor after a worker audit failure.

The first runtime worker used a stale ``TimeOut=`` parser.  This verifier
reads the immutable attempt and the actual DualSPHysics ``Output ... dt:``
records, without reopening the solver, starting CUDA, or changing queue,
ledger, registry, or matrix state.  A repaired cadence gate can make the raw
solver product reviewable, but it never turns the anchor into T1 credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts.core_cfd import native_frame

EXPECTED_FRAMES = 801
EXPECTED_TMAX = 16.0
EXPECTED_TOUT = 0.02
EXPECTED_GAUGES = {*(f"WG{i}" for i in range(1, 5)), *(f"Run-up{i}" for i in range(1, 8))}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def parse_run_out(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    timemax = re.search(r"^TimeMax=([0-9.eE+-]+)$", text, re.MULTILINE)
    outputs = re.findall(r"^\s*Output\.{5,}:\s*[^\n]*?dt:([0-9.eE+-]+)", text, re.MULTILINE)
    excluded = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    finished = "Finished execution (code=0)" in text
    return {
        "finished_code_zero": finished,
        "timemax_s": float(timemax.group(1)) if timemax else None,
        "output_dt_values_s": sorted({float(value) for value in outputs}),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def gauge_audit(solver: Path) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for path in sorted(solver.glob("GaugesSWL_*.csv")):
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            fields = line.replace(";", " ").split()
            try:
                values = [float(item) for item in fields]
            except ValueError:
                continue
            if len(values) >= 4:
                rows.append(values[:4])
        array = np.asarray(rows, dtype=np.float64)
        issues: list[str] = []
        if array.ndim != 2 or array.shape[1] != 4 or len(array) < 800:
            issues.append("fewer_than_800_rows")
        if len(array) and not np.isfinite(array).all():
            issues.append("nonfinite")
        if len(array) > 1:
            dt = np.diff(array[:, 0])
            if not np.all(dt > 0) or not np.isclose(float(np.median(dt)), EXPECTED_TOUT, atol=0.003):
                issues.append("cadence")
        if len(array) and array[-1, 0] < 15.95:
            issues.append("short_window")
        records[path.stem.removeprefix("GaugesSWL_")] = {
            "path": str(path), "rows": int(len(array)),
            "time_end_s": float(array[-1, 0]) if len(array) else None,
            "dt_median_s": float(np.median(np.diff(array[:, 0]))) if len(array) > 1 else None,
            "issues": issues, "sha256": sha256(path),
        }
    return {
        "names": sorted(records),
        "expected_names": sorted(EXPECTED_GAUGES),
        "all_expected": set(records) == EXPECTED_GAUGES,
        "all_structural_gates": bool(records) and all(not item["issues"] for item in records.values()),
        "records": records,
    }


def native_endpoint_audit(solver: Path, decoder: Path) -> dict[str, Any]:
    frames = sorted((solver / "data").glob("Part_*.bi4"))
    result: dict[str, Any] = {"frame_count": len(frames), "pass": False, "frames": []}
    if len(frames) < 2:
        return result
    import tempfile
    with tempfile.TemporaryDirectory(prefix="f5-anchor-postrun-") as temp:
        decoded = []
        for frame in (frames[0], frames[-1]):
            ids, pos, vel, rho, metadata, _info, _folder = native_frame(frame, Path(temp) / frame.stem, decoder)
            unique = len(np.unique(ids)) == len(ids)
            finite = bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all())
            fluid = int(float(metadata.get("CaseNfluid", "-1"))) if metadata.get("CaseNfluid") else -1
            decoded.append((ids, fluid))
            result["frames"].append({"path": str(frame), "particles": int(len(ids)), "fluid": fluid,
                                     "unique_ids": unique, "finite": finite})
        result["same_ids_first_last"] = bool(np.array_equal(decoded[0][0], decoded[1][0]))
        result["same_fluid_count_first_last"] = decoded[0][1] == decoded[1][1]
        result["pass"] = bool(all(row["unique_ids"] and row["finite"] for row in result["frames"])
                               and result["same_ids_first_last"] and result["same_fluid_count_first_last"])
    return result


def audit(attempt: Path, *, decoder: Path) -> dict[str, Any]:
    attempt = Path(attempt).resolve()
    solver = attempt / "product/solver"
    run_out = solver / "Run.out"
    frames = sorted((solver / "data").glob("Part_*.bi4"))
    run = parse_run_out(run_out)
    cadence_pass = run["timemax_s"] == EXPECTED_TMAX and run["output_dt_values_s"] == [EXPECTED_TOUT]
    frame_indices = [int(path.stem.removeprefix("Part_")) for path in frames]
    frame_pass = len(frames) == EXPECTED_FRAMES and frame_indices == list(range(EXPECTED_FRAMES))
    gauges = gauge_audit(solver)
    native = native_endpoint_audit(solver, decoder)
    old_result = load(attempt / "result.json") if (attempt / "result.json").is_file() else {}
    old_audit = load(attempt / "product/audit.json") if (attempt / "product/audit.json").is_file() else {}
    raw_complete = bool(run["finished_code_zero"] and run["excluded_particles"] == 0 and cadence_pass and frame_pass
                        and gauges["all_expected"] and gauges["all_structural_gates"] and native["pass"])
    result = {
        "schema": "core.f5.third_t1.solver_anchor_postrun_audit.v1",
        "status": "raw_solver_product_complete_worker_cadence_parser_failure" if raw_complete else "raw_solver_product_incomplete_or_failed",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "attempt": str(attempt),
        "attempt_result": {"path": str(attempt / "result.json"), "sha256": sha256(attempt / "result.json")} if (attempt / "result.json").is_file() else None,
        "prior_worker_audit": {"path": str(attempt / "product/audit.json"), "sha256": sha256(attempt / "product/audit.json"),
                               "status": old_audit.get("status")} if old_audit else None,
        "run": run,
        "frames": {"count": len(frames), "indices_first_last": [frame_indices[:3], frame_indices[-3:]], "pass": frame_pass},
        "cadence_reconciliation": {"expected_tmax_s": EXPECTED_TMAX, "expected_output_dt_s": EXPECTED_TOUT,
                                    "pass": cadence_pass, "parser_bug_in_prior_worker": True},
        "gauges": gauges,
        "native_endpoint": native,
        "raw_solver_product_complete": raw_complete,
        "execution_reconciliation": {
            "prior_worker_execution_status": old_result.get("execution_status"),
            "prior_worker_failure_reason": old_audit.get("hard_gates", {}).get("timeout_matches_registered"),
            "read_only": True,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
            "same_input_retry": False,
        },
        "scientific_review_pending": ["saved chord/geometry crossings", "full-window mass change", "incident/run-up/return events", "external reference alignment"],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, default=LAB / "campaigns/l1-resume/artifacts/bi4_dump")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.attempt, decoder=args.decoder)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "raw_solver_product_complete": result["raw_solver_product_complete"], "matrix_credit": 0}, indent=2))
    return 0 if result["raw_solver_product_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
