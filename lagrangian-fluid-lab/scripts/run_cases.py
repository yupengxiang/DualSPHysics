#!/usr/bin/env python3
"""Run prepared exploratory cases across explicitly selected GPUs."""

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
PREPARED = LAB_ROOT / "reports" / "runtime" / "prepare-summary.json"
SOLVER = (LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" /
          "bin" / "linux" / "DualSPHysics5.4_linux64")
RUN_ROOT = LAB_ROOT / "runs"
REPORT = LAB_ROOT / "reports" / "runtime" / "run-summary.json"


def run_case(record, gpu_id):
    case_id = record["id"]
    definition = LAB_ROOT / record["definition"]
    case_prefix = definition.parent / "generated" / case_id
    output_dir = RUN_ROOT / case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{SOLVER.parent}:{env.get('LD_LIBRARY_PATH', '')}"
    started = time.monotonic()
    proc = subprocess.run(
        [str(SOLVER), f"-gpu:{gpu_id}", str(case_prefix), str(output_dir)],
        cwd=LAB_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    elapsed = time.monotonic() - started
    (output_dir / "solver.stdout.log").write_text(proc.stdout)
    part_files = sorted((output_dir / "data").glob("Part_*.bi4"))
    finished = "Finished execution (code=0)" in proc.stdout
    status = "completed" if proc.returncode == 0 and finished and part_files else "run_failed"
    steps = None
    match = re.search(r"Total Runtime:\s*[^\n]*", proc.stdout)
    result = {
        "id": case_id,
        "family": record["family"],
        "mechanism": record["mechanism"],
        "status": status,
        "returncode": proc.returncode,
        "gpu": gpu_id,
        "elapsed_seconds": round(elapsed, 4),
        "frames": len(part_files),
        "output_bytes": sum(p.stat().st_size for p in output_dir.rglob("*") if p.is_file()),
        "runtime_line": match.group(0) if match else None,
        "log": str((output_dir / "solver.stdout.log").relative_to(LAB_ROOT)),
    }
    print(f"GPU {gpu_id}: {case_id:28s} {status:10s} frames={len(part_files)} time={elapsed:.2f}s")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpus", default="4,5,6,7", help="comma-separated physical GPU ids")
    parser.add_argument("--cases", nargs="*", help="case ids; default is every prepared case")
    args = parser.parse_args()
    if not SOLVER.is_file():
        raise SystemExit(f"missing solver executable: {SOLVER}")
    prepared = json.loads(PREPARED.read_text())
    records = [r for r in prepared["cases"] if r["status"] == "prepared"]
    if args.cases:
        requested = set(args.cases)
        records = [r for r in records if r["id"] in requested]
        missing = requested - {r["id"] for r in records}
        if missing:
            raise SystemExit(f"unknown or unprepared cases: {sorted(missing)}")
    gpu_ids = [int(x) for x in args.gpus.split(",") if x.strip()]
    if not gpu_ids:
        raise SystemExit("at least one GPU id is required")

    queues = {gpu: [] for gpu in gpu_ids}
    for index, record in enumerate(records):
        queues[gpu_ids[index % len(gpu_ids)]].append(record)

    def run_queue(gpu_id, queue):
        return [run_case(record, gpu_id) for record in queue]

    results = []
    with ThreadPoolExecutor(max_workers=len(gpu_ids)) as pool:
        futures = [pool.submit(run_queue, gpu, queue) for gpu, queue in queues.items()]
        for future in as_completed(futures):
            results.extend(future.result())
    if args.cases and REPORT.is_file():
        previous = json.loads(REPORT.read_text()).get("cases", [])
        results = [record for record in previous if record["id"] not in requested] + results
    results.sort(key=lambda r: r["id"])
    summary = {
        "schema_version": 1,
        "solver": str(SOLVER.relative_to(LAB_ROOT)),
        "completed": sum(r["status"] == "completed" for r in results),
        "failed": sum(r["status"] != "completed" for r in results),
        "cases": results,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"completed={summary['completed']} failed={summary['failed']}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
