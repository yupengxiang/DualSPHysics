#!/usr/bin/env python3
"""Run GenCase for every case definition and report particle counts/errors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


LAB_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = LAB_ROOT / "cases" / "manifest.json"
GENCASE = LAB_ROOT / "vendor" / "bin" / "linux" / "GenCase_linux64"
REPORT = LAB_ROOT / "reports" / "runtime" / "prepare-summary.json"


def run_one(record):
    case_id = record["id"]
    definition = LAB_ROOT / record["definition"]
    generated = definition.parent / "generated"
    generated.mkdir(exist_ok=True)
    target = generated / case_id
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{GENCASE.parent}:{env.get('LD_LIBRARY_PATH', '')}"
    started = time.monotonic()
    proc = subprocess.run(
        [str(GENCASE), str(definition.with_suffix("")),
         str(target), "-save:all"],
        cwd=LAB_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    elapsed = time.monotonic() - started
    log_path = generated / "gencase.log"
    log_path.write_text(proc.stdout)
    fluid_match = re.search(r"Fluid\.\.\.\.:\s+([0-9,]+)", proc.stdout)
    total_match = re.search(r"Total particles:\s+([0-9,]+)", proc.stdout)
    result = {
        **record,
        "status": "prepared" if proc.returncode == 0 else "prepare_failed",
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 4),
        "fluid_particles": int(fluid_match.group(1).replace(",", "")) if fluid_match else None,
        "total_particles": int(total_match.group(1).replace(",", "")) if total_match else None,
        "log": str(log_path.relative_to(LAB_ROOT)),
    }
    print(f"{case_id:28s} {result['status']:14s} fluid={result['fluid_particles']}")
    return result


def main():
    if not GENCASE.is_file():
        raise SystemExit(f"missing GenCase executable: {GENCASE}")
    manifest = json.loads(MANIFEST.read_text())
    results = [run_one(record) for record in manifest["cases"]]
    summary = {
        "schema_version": 1,
        "prepared": sum(r["status"] == "prepared" for r in results),
        "failed": sum(r["status"] != "prepared" for r in results),
        "cases": results,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"prepared={summary['prepared']} failed={summary['failed']}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
