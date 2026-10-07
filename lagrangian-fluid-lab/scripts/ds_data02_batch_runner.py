#!/usr/bin/env python3
"""Batch runner for DS-DATA-02 requests using subprocess pool and supervisor accounting."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = REPO / "scripts/ds_data02_runtime.py"
PYTHON_BIN = REPO / ".venv/bin/python"


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_batch(request_paths: list[Path], max_concurrency: int = 2, label: str = "batch") -> int:
    pending = [Path(p).resolve() for p in request_paths]
    running: dict[subprocess.Popen, tuple[Path, float]] = {}
    completed: list[dict] = []
    failed: list[dict] = []

    print(f"[{now_str()}] Starting batch '{label}' with {len(pending)} requests (max concurrency: {max_concurrency})")

    while pending or running:
        # Launch new tasks if capacity allows
        while pending and len(running) < max_concurrency:
            req_path = pending.pop(0)
            print(f"[{now_str()}] Launching: {req_path.name}")
            cmd = [str(PYTHON_BIN), str(RUNTIME_SCRIPT), "run", "--request", str(req_path)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            running[proc] = (req_path, time.monotonic())

        # Check running tasks
        time.sleep(1.0)
        done_procs = []
        for proc, (req_path, start_t) in running.items():
            ret = proc.poll()
            if ret is not None:
                elapsed = time.monotonic() - start_t
                out, _ = proc.communicate()
                done_procs.append(proc)
                print(f"[{now_str()}] Finished: {req_path.name} (code: {ret}, elapsed: {elapsed:.1f}s)")
                
                # Parse stdout for receipt summary
                try:
                    receipt = json.loads(out)
                    status = receipt.get("status", "unknown")
                except Exception:
                    receipt = {"raw_output": out}
                    status = "success" if ret == 0 else "failed"

                record = {
                    "request": str(req_path),
                    "returncode": ret,
                    "elapsed_seconds": elapsed,
                    "status": status,
                }
                if ret == 0 and status == "completed":
                    completed.append(record)
                else:
                    record["error_snippet"] = out[-1000:] if len(out) > 1000 else out
                    failed.append(record)
                    print(f"[{now_str()}] WARNING: Task failed: {req_path.name}\n{record.get('error_snippet')}")

        for proc in done_procs:
            del running[proc]

    print(f"[{now_str()}] Batch '{label}' finished: {len(completed)} completed, {len(failed)} failed.")
    return len(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requests", nargs="+", type=Path, help="Paths to request JSON files")
    parser.add_argument("--concurrency", type=int, default=2, help="Max concurrency")
    parser.add_argument("--label", type=str, default="batch", help="Batch label")
    args = parser.parse_args()

    sys.exit(run_batch(args.requests, max_concurrency=args.concurrency, label=args.label))


if __name__ == "__main__":
    main()
