#!/usr/bin/env python3
"""Dry-run planner for an orphaned typed conversion.

This helper reads only small JSON receipt/report/liveness evidence. It never
opens payloads, hashes H5/BI4/CSV data, launches or kills processes, edits a
receipt, releases a lease, or changes shared runtime state. The shared runner
must perform any eventual reconciliation after reviewing this plan.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LIVE_STATES = {"R", "S", "D", "T", "t", "W"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def plan(receipt: dict[str, Any], report: dict[str, Any] | None, liveness: dict[str, Any]) -> dict[str, Any]:
    qualified = liveness.get("probe_status") == "qualified_host_namespace"
    receipt_pid = receipt.get("pid")
    child_pid = liveness.get("child_pid")
    receipt_status = receipt.get("status")
    report_status = report.get("conversion_status") if report else None
    facts = {
        "receipt_status": receipt_status,
        "receipt_returncode": receipt.get("returncode"),
        "receipt_pid": receipt_pid,
        "child_pid": child_pid,
        "child_state": liveness.get("child_state"),
        "launcher_pid": liveness.get("launcher_pid"),
        "launcher_state": liveness.get("launcher_state"),
        "conversion_report_status": report_status,
        "reported_output_sha256": report.get("output_sha256") if report else None,
        "reported_partvtk_all_passed": (
            report.get("partvtk_validation", {}).get("all_passed") if report else None
        ),
    }
    base = {
        "schema": "ds02.typed-conversion-recovery-plan.v1",
        "source_only_dry_run": True,
        "payloads_opened": False,
        "commands_run": [],
        "mutations_performed": False,
        "facts": facts,
    }
    if not qualified:
        base.update({
            "action": "hold_unqualified_liveness",
            "lease_decision": "preserve",
            "retry_allowed": False,
            "reason": "A default-namespace or missing liveness probe cannot establish child exit.",
        })
        return base
    if receipt_pid is not None and child_pid is not None and receipt_pid != child_pid:
        base.update({
            "action": "hold_pid_mismatch_for_manual_review",
            "lease_decision": "preserve",
            "retry_allowed": False,
            "reason": "Receipt PID and qualified host child PID differ; no inference is safe.",
        })
        return base
    state = liveness.get("child_state")
    if state in LIVE_STATES:
        base.update({
            "action": "preserve_live_child",
            "lease_decision": "preserve",
            "retry_allowed": False,
            "reason": "Qualified host evidence still shows a live child; duplicate start and release are forbidden.",
        })
        return base
    if state == "absent" and receipt_status == "running" and report_status == "completed":
        base.update({
            "action": "request_runner_owned_finalization_review",
            "lease_decision": "preserve_until_runner_finalizes",
            "retry_allowed": False,
            "reason": "Report completion does not close a running receipt; runner must reconcile lifecycle atomically.",
            "required_proofs": [
                "qualified host namespace proves launcher and child absence",
                "runner verifies the report-provided output hash with its approved opaque-artifact path",
                "runner verifies PartVTK/report/source closure without source mutation",
                "runner writes the normal receipt transition atomically; this helper never edits JSON",
                "runner preserves original receipt/report and records the reconciliation lineage",
            ],
        })
        return base
    base.update({
        "action": "hold_for_runner_review",
        "lease_decision": "preserve",
        "retry_allowed": False,
        "reason": "Observed receipt/report/liveness combination has no safe automatic transition.",
    })
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--liveness-json", type=Path, required=True)
    args = parser.parse_args()
    receipt = load(args.receipt)
    report = load(args.report) if args.report else None
    liveness = load(args.liveness_json)
    print(json.dumps(plan(receipt, report, liveness), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
