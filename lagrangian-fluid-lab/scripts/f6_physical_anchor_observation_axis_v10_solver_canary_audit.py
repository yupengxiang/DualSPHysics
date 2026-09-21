#!/usr/bin/env python3
"""Aggregate the v4 solver-canary attempts without changing qualification state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CANARY_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921"
PLAN = CANARY_ROOT / "plan.json"
OUTPUT = CANARY_ROOT / "canary-audit.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def check_binding(binding: Any) -> list[str]:
    """Validate a receipt's path/hash/byte binding without opening solver data."""
    if not isinstance(binding, dict):
        return ["native_frame_audit_binding_missing"]
    raw_path = binding.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return ["native_frame_audit_binding_path_missing"]
    path = Path(raw_path)
    if not path.is_absolute():
        path = LAB / path
    path = path.resolve()
    if not path.is_file():
        return ["native_frame_audit_binding_file_missing"]
    failures: list[str] = []
    if binding.get("sha256") != sha256(path):
        failures.append("native_frame_audit_binding_sha256")
    if binding.get("bytes") != path.stat().st_size:
        failures.append("native_frame_audit_binding_bytes")
    return failures


def audit() -> dict[str, Any]:
    plan = load(PLAN)
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for item in plan.get("jobs", []):
        job = load(LAB / item["job"]["path"])
        attempt = Path(job["output"]["attempt_dir"]).resolve()
        receipt_path = attempt / "execution-receipt.json"
        row: dict[str, Any] = {"index": item["index"], "cell_id": item["cell_id"], "job_id": item["job_id"], "attempt": 1, "receipt": str(receipt_path.relative_to(LAB)), "receipt_sha256": sha256(receipt_path) if receipt_path.is_file() else None}
        if not receipt_path.is_file():
            row.update({"status": "pending", "scientific_pass": False, "hard_gate_pass": False, "issues": ["receipt not written"]})
            rows.append(row)
            continue
        receipt = load(receipt_path)
        local: list[str] = []
        controls = receipt.get("execution_controls", {})
        if receipt.get("cell_id") != item["cell_id"]:
            local.append("cell identity mismatch")
        if receipt.get("qualification_claim") != "none" or receipt.get("qualification_credit") != 0 or receipt.get("T1") is not False:
            local.append("qualification guard failed")
        if controls.get("gpu_started") is not False or controls.get("queue_mutation") != 0 or controls.get("registry_mutation") != 0 or controls.get("ledger_mutation") != 0 or controls.get("matrix_submission") is not False:
            local.append("forbidden execution or mutation control")
        hard_gate_failures = [
            str(key) for key, value in receipt.get("hard_gates", {}).items()
            if value is not True
        ]
        hard = not hard_gate_failures and bool(receipt.get("hard_gates"))
        binding_issues = check_binding(receipt.get("native_frame_audit"))
        if binding_issues:
            local.extend(binding_issues)
        scientific = receipt.get("status") == "solver_completed_sidecar_pass_pending_scientific_review" and hard and not local
        if local:
            failure_category = "execution_control_contract_failure"
        elif hard_gate_failures:
            failure_category = "scientific_hard_gate_failure"
        elif scientific:
            failure_category = None
        else:
            failure_category = "receipt_status_or_contract_failure"
        row.update({
            "status": receipt.get("status"),
            "scientific_pass": scientific,
            "hard_gate_pass": hard,
            "hard_gate_failures": hard_gate_failures,
            "receipt_binding_pass": not binding_issues,
            "receipt_binding_issues": binding_issues,
            "metadata_integrity_repaired": "metadata_integrity_repair" in receipt,
            "failure_category": failure_category,
            "issues": local,
            "recovered": receipt.get("recovery", {}).get("solver_not_reinvoked") is True,
        })
        if local:
            issues.extend([f"cell {item['index']:02d}: {x}" for x in local])
        rows.append(row)
    complete = len(rows) == int(plan.get("selected_count", 0)) and all(row["status"] != "pending" for row in rows)
    pass_count = sum(row["scientific_pass"] for row in rows)
    hard_gate_failure_counts: dict[str, int] = {}
    for row in rows:
        for failure in row.get("hard_gate_failures", []):
            hard_gate_failure_counts[failure] = hard_gate_failure_counts.get(failure, 0) + 1
    binding_failure_counts: dict[str, int] = {}
    for row in rows:
        for failure in row.get("receipt_binding_issues", []):
            binding_failure_counts[failure] = binding_failure_counts.get(failure, 0) + 1
    return {
        "schema": "core.f6.observation_axis.solver_canary_audit.v1",
        "record_id": "F6_observation_axis_v10_solver_canary_audit_v4_20260921",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "all_selected_canaries_audited" if complete else "canary_attempts_in_progress",
        "plan_sha256": sha256(PLAN),
        "selected_count": plan.get("selected_count"),
        "audited_count": sum(row["status"] != "pending" for row in rows),
        "scientific_pass_count": pass_count,
        "hard_gate_failure_counts": dict(sorted(hard_gate_failure_counts.items())),
        "receipt_binding_failure_counts": dict(sorted(binding_failure_counts.items())),
        "metadata_integrity_repair_count": sum(bool(row.get("metadata_integrity_repaired")) for row in rows),
        "complete": complete,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "issues": issues,
        "rows": rows,
        "next_gate": (
            "audit_remaining_selected_attempts" if not complete else
            "close_scope_or_open_new_scientific_scope_before_remaining_cells"
            if pass_count < int(plan.get("selected_count", 0)) else
            "root_review_canary_results_before_remaining_7_cells"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    value = audit()
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "audited_count": value["audited_count"], "scientific_pass_count": value["scientific_pass_count"], "complete": value["complete"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
