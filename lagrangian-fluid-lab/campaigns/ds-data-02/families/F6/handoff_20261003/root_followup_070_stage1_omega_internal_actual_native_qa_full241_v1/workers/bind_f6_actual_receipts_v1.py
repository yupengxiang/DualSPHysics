#!/usr/bin/env python3
"""Bind actual F6 fresh070 owner and terminal receipt hashes without launching work."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def require_completed(path: Path, label: str) -> dict[str, Any]:
    value = load(path)
    if value.get("status") != "completed" or value.get("returncode") != 0:
        raise RuntimeError(f"{label} is not completed/0: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binder", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--qa-receipt", required=True, type=Path)
    parser.add_argument("--qa-index", required=True, type=Path)
    parser.add_argument("--qa-reports-dir", required=True, type=Path)
    parser.add_argument("--state0-summary", required=True, type=Path)
    args = parser.parse_args()
    binder = load(args.binder)
    if binder.get("status") != "source_only_disabled" or binder.get("launch_allowed") is not False:
        raise RuntimeError("input binder is not the disabled fresh070 source contract")
    qa_receipt = require_completed(args.qa_receipt, "initial QA receipt")
    qa_index = load(args.qa_index)
    if qa_index.get("status") != "initial-native-integrity-pass" or qa_index.get("pass") is not True:
        raise RuntimeError("initial QA index is not terminal pass")
    qa_summary = load(args.state0_summary)
    if qa_summary.get("all_cases_passed") is not True:
        raise RuntimeError("state0 summary is not terminal all-pass")
    state_cases = {str(x["case_id"]): x for x in qa_summary.get("cases", []) if isinstance(x, dict)}
    out_cases = []
    for case in binder.get("cases", []):
        case_id = str(case["case_id"])
        owner_path = Path(str(case["canonical_owner"]))
        owner = load(owner_path)
        condition = owner.get("physical_condition_sha256")
        if not isinstance(condition, str) or len(condition) != 64:
            raise RuntimeError(f"canonical physical condition hash missing: {case_id}")
        if owner.get("physical_case_id") != case_id:
            raise RuntimeError(f"canonical owner identity mismatch: {case_id}")
        for key in ("gencase_receipt", "gencase_xml", "gencase_bi4"):
            path = Path(str(case[key]))
            observed = sha256(path)
            if observed != str(case[f"{key}_sha256"]):
                raise RuntimeError(f"bound {key} hash changed: {case_id}")
        full_path = Path(str(case["full241_receipt"]))
        full = require_completed(full_path, f"full241 receipt {case_id}")
        command = full.get("command", [])
        if not isinstance(command, list) or "-tmax:12" not in command or "-tout:0.05" not in command:
            raise RuntimeError(f"full241 recipe drift: {case_id}")
        if any(str(item).startswith(("-dbc", "-mdbc", "-forcing", "-motion", "-cpu")) for item in command):
            raise RuntimeError(f"forbidden solver option in full241 receipt: {case_id}")
        report = args.qa_reports_dir / case_id / "initial-native-qa.json"
        report_obj = load(report)
        if report_obj.get("pass") is not True:
            raise RuntimeError(f"initial QA report is not pass: {case_id}")
        state = state_cases.get(case_id)
        if state is None or state.get("status") != "pass":
            raise RuntimeError(f"state0 report missing/pass false: {case_id}")
        out_cases.append({
            **case,
            "canonical_owner_sha256": sha256(owner_path),
            "physical_condition_sha256": condition,
            "initial_qa_receipt": str(args.qa_receipt),
            "initial_qa_receipt_sha256": sha256(args.qa_receipt),
            "initial_qa_report": str(report),
            "initial_qa_report_sha256": sha256(report),
            "full241_receipt_sha256": sha256(full_path),
            "state0_audit": state.get("audit"),
            "state0_audit_sha256": state.get("audit_sha256"),
            "state0_summary": str(args.state0_summary),
            "state0_summary_sha256": sha256(args.state0_summary),
            "status": "actual_owner_qa_full241_state0_bound",
        })
    result = {
        **binder,
        "schema": "ds02.f6.stage1-omega-internal-strict-actual-receipts-binder.v3",
        "status": "actual_bound",
        "launch_allowed": False,
        "cases": out_cases,
        "terminal_gates": {
            "initial_qa_receipt": str(args.qa_receipt),
            "initial_qa_receipt_sha256": sha256(args.qa_receipt),
            "initial_qa_index": str(args.qa_index),
            "initial_qa_index_sha256": sha256(args.qa_index),
            "state0_summary": str(args.state0_summary),
            "state0_summary_sha256": sha256(args.state0_summary),
        },
        "quality": {"q_n": "not_assessed", "precision": "not_accepted", "production_approval": "none", "visual": "not_passed"},
        "independent_case_count_increment": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

