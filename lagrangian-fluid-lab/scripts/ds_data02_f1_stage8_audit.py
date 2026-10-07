#!/usr/bin/env python3
"""Run bounded-memory Q-I integrity audits on F1 Stage 8 cases."""

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
    "F1_ECC_P01_FINE",
    "F1_ECC_P02_FINE",
    "F1_ECC_P03_FINE",
    "F1_ECC_P04_FINE",
    "F1_DUAL_P01_FINE",
    "F1_DUAL_P02_FINE",
    "F1_DUAL_P03_FINE",
    "F1_DUAL_P04_FINE",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_f1_case(case_id: str, *, force: bool = False) -> dict:
    case_dir = DATA_ROOT / "families/F1" / case_id

    # Find latest conversion directory
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

    # Find latest completed qualification run for solver log
    qual_dirs = sorted(case_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_log = None
    for qd in reversed(qual_dirs):
        log_candidate = qd / "solver/Run.out"
        rec = qd / "execution-receipt.json"
        if log_candidate.is_file() and rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_log = log_candidate
                    break
            except Exception:
                pass

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

    if audit_output.is_file() and not force:
        try:
            audit_data = json.loads(audit_output.read_text())
            solver_match = audit_data.get("solver_log_consistency", {}).get("status")
            return {
                "case_id": case_id,
                "status": "pass" if solver_match == "pass" else "inconsistent",
                "solver_log_consistency": solver_match,
                "audit_file": str(audit_output),
                "elapsed_seconds": audit_data.get("elapsed_seconds", 0.0),
                "comparisons": audit_data.get("solver_log_consistency", {}).get("comparisons", []),
            }
        except Exception:
            pass

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
    parser.add_argument("--force", action="store_true", help="Force re-running audit even if audit.json exists")
    args = parser.parse_args()

    out_summary = REPO / "campaigns/ds-data-02/families/F1/stage8_integrity_audit_summary.json"
    existing_by_case = {}
    if out_summary.is_file():
        try:
            for item in json.loads(out_summary.read_text(encoding="utf-8")):
                if "case_id" in item:
                    existing_by_case[item["case_id"]] = item
        except Exception:
            pass

    print(f"[{now_str()}] Starting F1 Stage 8 Q-I integrity audits on {len(args.cases)} cases...")
    for cid in args.cases:
        res = audit_f1_case(cid, force=args.force)
        print(f"[{now_str()}] {cid}: status={res.get('status')} (elapsed={res.get('elapsed_seconds', 0.0):.1f}s)")
        existing_by_case[cid] = res

    # Sort in canonical STAGE8_CASES order
    summary_list = [existing_by_case[c] for c in STAGE8_CASES if c in existing_by_case]
    # Add any extra cases
    for c, data in sorted(existing_by_case.items()):
        if c not in STAGE8_CASES:
            summary_list.append(data)

    out_summary.write_text(json.dumps(summary_list, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Summary written to {out_summary}")

    passed = sum(1 for r in summary_list if r.get("status") == "pass")
    print(f"[{now_str()}] Audits passed: {passed}/{len(summary_list)}")
    return 0 if passed == len(summary_list) else 1


if __name__ == "__main__":
    sys.exit(main())
