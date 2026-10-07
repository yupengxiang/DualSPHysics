#!/usr/bin/env python3
"""Run bounded-memory Q-I integrity audits on all F7 Stage 8 cases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
INTEGRITY_SCRIPT = REPO / "scripts/ds_data02_integrity.py"
PYTHON_BIN = REPO / ".venv/bin/python"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

STAGE8_CASES = [
    "F7_PUMP_P00_FINE",
    "F7_PUMP_P01_FINE",
    "F7_PUMP_P02_FINE",
    "F7_PUMP_P03_FINE",
    "F7_OBSTACLE_P00_FINE",
    "F7_OBSTACLE_P01_FINE",
    "F7_OBSTACLE_P02_FINE",
    "F7_OBSTACLE_P03_FINE",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_f7_case(case_id: str) -> dict:
    case_dir = DATA_ROOT / "families/F7" / case_id
    traj_path = case_dir / "full-typed-native-conversion-001/trajectory.h5"
    solver_log = case_dir / f"{case_id}_QUALIFICATION_001/solver/Run.out"
    audit_output = case_dir / "full-typed-native-conversion-001/audit.json"

    if not traj_path.is_file():
        return {
            "case_id": case_id,
            "status": "missing_trajectory",
            "path": str(traj_path),
        }
    if not solver_log.is_file():
        return {
            "case_id": case_id,
            "status": "missing_solver_log",
            "path": str(solver_log),
        }

    cmd = [
        str(PYTHON_BIN),
        str(INTEGRITY_SCRIPT),
        str(traj_path),
        "--solver-log",
        str(solver_log),
        "--output",
        str(audit_output),
        "--particle-chunk",
        "65536",
    ]

    t0 = time.monotonic()
    res = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    elapsed = time.monotonic() - t0

    if res.returncode != 0:
        return {
            "case_id": case_id,
            "status": "audit_failed",
            "returncode": res.returncode,
            "stderr": res.stderr[-500:],
            "elapsed_seconds": elapsed,
        }

    try:
        audit_data = json.loads(audit_output.read_text())
        solver_match = audit_data.get("solver_log_consistency", {}).get("status")
        return {
            "case_id": case_id,
            "status": "pass" if solver_match == "pass" else "inconsistent",
            "solver_log_consistency": solver_match,
            "audit_file": str(audit_output),
            "elapsed_seconds": elapsed,
            "comparisons": audit_data.get("solver_log_consistency", {}).get("comparisons", []),
        }
    except Exception as e:
        return {
            "case_id": case_id,
            "status": "parse_error",
            "error": str(e),
            "elapsed_seconds": elapsed,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=STAGE8_CASES)
    args = parser.parse_args()

    results = []
    print(f"[{now_str()}] Starting F7 Stage 8 Q-I integrity audits on {len(args.cases)} cases...")
    for cid in args.cases:
        res = audit_f7_case(cid)
        print(f"[{now_str()}] {cid}: status={res.get('status')} (elapsed={res.get('elapsed_seconds', 0.0):.1f}s)")
        results.append(res)

    out_summary = REPO / "campaigns/ds-data-02/families/F7/stage8_integrity_audit_summary.json"
    out_summary.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Summary written to {out_summary}")

    passed = sum(1 for r in results if r.get("status") == "pass")
    print(f"[{now_str()}] Audits passed: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
