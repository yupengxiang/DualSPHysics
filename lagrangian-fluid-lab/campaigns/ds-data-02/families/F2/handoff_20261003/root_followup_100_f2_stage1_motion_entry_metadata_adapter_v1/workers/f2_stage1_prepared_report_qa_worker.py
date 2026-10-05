#!/usr/bin/env python3
"""Gate the existing F2 initial QA worker on the actual prepared report."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--definition", required=True)
    parser.add_argument("--gencase-receipt", required=True)
    parser.add_argument("--prepared-input-report", required=True)
    parser.add_argument("--prepared-report-output", required=True)
    parser.add_argument("--partvtk", required=True)
    parser.add_argument("--partvtk-output-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    audit_command = [
        sys.executable, str(here / "f2_prepared_report_contract_audit.py"),
        "--case-id", args.case_id,
        "--prepared-input-report", args.prepared_input_report,
        "--gencase-receipt", args.gencase_receipt,
        "--output", args.prepared_report_output,
    ]
    audit = subprocess.run(audit_command, check=False)
    if audit.returncode:
        return audit.returncode
    qa_command = [
        sys.executable, str(here / "f2_stage1_initial_qa_worker.py"),
        "--case-id", args.case_id, "--definition", args.definition,
        "--gencase-receipt", args.gencase_receipt,
        "--partvtk", args.partvtk, "--partvtk-output-dir", args.partvtk_output_dir,
        "--output", args.output,
    ]
    return subprocess.run(qa_command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
