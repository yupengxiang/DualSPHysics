#!/usr/bin/env python3
"""Run bounded-memory Q-I integrity audits on all F2 Stage 8 cases."""

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
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F2"

STAGE8_CASES = [
    "F2_CENTER_P01",
    "F2_OFFSET_P01",
    "F2_CENTER_P02",
    "F2_OFFSET_P02",
    "F2_CENTER_P03",
    "F2_OFFSET_P03",
    "F2_CENTER_P04",
    "F2_OFFSET_P04",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_f2_case(case_id: str) -> dict:
    case_dir = DATA_ROOT / "families/F2" / case_id

    conv_dirs = sorted(case_dir.glob("full-typed-native-conversion-*"))
    conv_dir = None
    for cd in reversed(conv_dirs):
        if (cd / "trajectory.h5").is_file():
            conv_dir = cd
            break
    if conv_dir is None:
        conv_dir = conv_dirs[-1] if conv_dirs else case_dir / "full-typed-native-conversion-001"

    traj_path = conv_dir / "trajectory.h5"
    audit_output = conv_dir / "audit.json"

    qual_dirs = sorted(case_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_log = None
    for qd in reversed(qual_dirs):
        cand = qd / "solver/Run.out"
        rec = qd / "execution-receipt.json"
        if cand.is_file() and rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_log = cand
                    break
            except Exception:
                pass
    if not solver_log:
        for qd in reversed(qual_dirs):
            cand = qd / "solver/Run.out"
            if cand.is_file():
                solver_log = cand
                break

    if not traj_path.is_file():
        return {
            "case_id": case_id,
            "status": "missing_trajectory",
            "path": str(traj_path),
        }
    if not solver_log or not solver_log.is_file():
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
    print(f"[{now_str()}] Starting Q-I integrity audits for {len(args.cases)} cases...")
    for cid in args.cases:
        r = audit_f2_case(cid)
        results.append(r)
        status_label = r.get("status", "unknown")
        print(f"  {cid}: status={status_label} (solver_match={r.get('solver_log_consistency')})")

    summary_file = FAMILY_DIR / "stage8_integrity_audit_summary.json"
    summary_file.write_text(json.dumps(results, indent=2) + "\n")
    print(f"[{now_str()}] Written audit summary to {summary_file}")


if __name__ == "__main__":
    main()
