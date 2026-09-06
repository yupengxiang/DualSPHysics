#!/usr/bin/env python3
"""Run coarse official-example probes with one sequential queue per GPU."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import subprocess
import time


LAB_ROOT = Path(__file__).resolve().parents[1]
PREPARED = LAB_ROOT / "reports" / "runtime" / "official-prepare-summary.json"
BIN = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
SOLVER = BIN / "DualSPHysics5.4_linux64"
RUN_ROOT = LAB_ROOT / "runs-official"
REPORT = LAB_ROOT / "reports" / "runtime" / "official-run-summary.json"


def run_one(record, gpu_id):
    case_id = record["id"]
    prefix = LAB_ROOT / record["case_prefix"]
    output = RUN_ROOT / case_id
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    command = [str(SOLVER), f"-gpu:{gpu_id}", str(prefix), str(output),
               f"-tmax:{record['tmax']}", f"-tout:{record['tout']}"]
    command.extend(record.get("solver_flags", []))
    started = time.monotonic()
    proc = subprocess.run(command, cwd=prefix.parent, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    (output / "solver.stdout.log").write_text(proc.stdout)
    parts = sorted(output.glob("data*/Part_*.bi4"))
    finished = "Finished execution (code=0)" in proc.stdout
    status = "completed" if proc.returncode == 0 and finished and parts else "run_failed"
    excluded = re.search(r"Excluded particles\.+:\s*([0-9,]+)", proc.stdout)
    result = {
        **record, "status": status, "returncode": proc.returncode, "gpu": gpu_id,
        "elapsed_seconds": round(elapsed, 4), "frames": len(parts),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "output_bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
        "log": str((output / "solver.stdout.log").relative_to(LAB_ROOT)),
    }
    print(f"GPU {gpu_id}: {case_id:26s} {status:10s} frames={len(parts):2d} time={elapsed:.2f}s")
    return result


def run_queue(gpu_id, records):
    return [run_one(record, gpu_id) for record in records]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="*", help="Only run these case ids and merge the report")
    args = parser.parse_args()
    selected = set(args.cases or [])
    prepared = json.loads(PREPARED.read_text())
    known = {r["id"] for r in prepared["cases"]}
    unknown = selected - known
    if unknown:
        parser.error(f"unknown case ids: {', '.join(sorted(unknown))}")
    records = [r for r in prepared["cases"]
               if r["status"] == "prepared" and (not selected or r["id"] in selected)]
    gpu_ids = [4, 5, 6, 7]
    queues = {gpu: [] for gpu in gpu_ids}
    for index, record in enumerate(records):
        queues[gpu_ids[index % len(gpu_ids)]].append(record)
    results = []
    with ThreadPoolExecutor(max_workers=len(gpu_ids)) as pool:
        futures = [pool.submit(run_queue, gpu, queue) for gpu, queue in queues.items()]
        for future in as_completed(futures):
            results.extend(future.result())
    if selected and REPORT.is_file():
        previous = json.loads(REPORT.read_text()).get("cases", [])
        results = [record for record in previous if record["id"] not in selected] + results
    results.sort(key=lambda r: r["id"])
    summary = {
        "schema_version": 1,
        "completed": sum(r["status"] == "completed" for r in results),
        "failed": sum(r["status"] != "completed" for r in results),
        "cases": results,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"completed={summary['completed']} failed={summary['failed']}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
