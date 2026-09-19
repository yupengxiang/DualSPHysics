#!/usr/bin/env python3
"""Reconcile the L2-R resource ledger without rewriting historical state.

The original L2 summary predates the resume namespace and therefore cannot be
used as the sole source of current attempt counts.  This report keeps the old
snapshot, counts immutable L2-R attempt IDs, and exposes the remaining parent
caps conservatively.  It deliberately does not emit a qualification receipt or
change the scheduler state.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns/l2-multifamily"
RESUME = CAMPAIGN / "resume-c6b28c8"
STATE = RESUME / "state.json"


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_qualified_resume_attempts() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in RESUME.rglob("*.json"):
        try:
            payload = _read(path)
        except (OSError, json.JSONDecodeError):
            continue

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                attempt_id = value.get("attempt_id")
                category = value.get("resource_category")
                if (
                    isinstance(attempt_id, str)
                    and category == "qualification"
                    and not attempt_id.startswith("20260913")
                ):
                    rows.setdefault(
                        attempt_id,
                        {
                            "attempt_id": attempt_id,
                            "resource_category": category,
                            "source": str(path.relative_to(LAB)),
                        },
                    )
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
    return rows


def _unique_training_attempts() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted((RESUME / "b2r-attempts").glob("*/attempt.json")):
        try:
            payload = _read(path)
        except (OSError, json.JSONDecodeError):
            continue
        attempt_id = payload.get("execution_attempt_id") or payload.get("attempt_id")
        if isinstance(attempt_id, str):
            rows.setdefault(
                attempt_id,
                {
                    "attempt_id": attempt_id,
                    "resource_category": "training",
                    "source": str(path.relative_to(LAB)),
                    "status": payload.get("status"),
                },
            )
    return rows


def build_report() -> dict[str, Any]:
    state = _read(STATE)
    old_usage = dict(state.get("observed_usage", {}))
    parent = dict(state.get("parent_limits", {}))
    qualification = _unique_qualified_resume_attempts()
    training = _unique_training_attempts()
    material_report = RESUME / "b1r-material-preflight/r5-f1-material-task.json"
    material_configurations = 0
    material_status = "missing"
    if material_report.is_file():
        material = _read(material_report)
        material_status = material.get("execution_status", "unknown")
        material_configurations = len(material.get("configurations", []))

    new_counts = {
        "qualification_solver_attempts": len(qualification),
        "development_solver_attempts": 1 if (LAB / "campaigns/l2-multifamily/f1r-h1/runs").exists() else 0,
        "training_attempts": len(training),
        "material_configurations": material_configurations,
    }
    total_counts = {
        key: int(old_usage.get(key, 0)) + value for key, value in new_counts.items()
    }
    remaining = {
        "qualification_solver_attempts": max(0, int(parent.get("qualification_solver_attempts", 0)) - total_counts["qualification_solver_attempts"]),
        "development_solver_attempts": max(0, int(parent.get("development_solver_attempts", 0)) - total_counts["development_solver_attempts"]),
        "training_attempts": max(0, int(parent.get("training_attempts", 0)) - total_counts["training_attempts"]),
        "full_material_configurations": max(0, int(parent.get("full_material_configurations", 0)) - total_counts["material_configurations"]),
    }
    return {
        "schema": "l2r.resource_reconciliation.v1",
        "generated_at_utc": _utc_now(),
        "resume_id": state.get("resume_id"),
        "source_commit": state.get("current_commit"),
        "historical_snapshot": old_usage,
        "new_l2r_counts": new_counts,
        "reconciled_total_counts": total_counts,
        "remaining_parent_caps": remaining,
        "new_l2r_qualification_attempts": sorted(qualification.values(), key=lambda row: row["attempt_id"]),
        "new_l2r_training_attempts": sorted(training.values(), key=lambda row: row["attempt_id"]),
        "material_report": {
            "path": str(material_report.relative_to(LAB)),
            "status": material_status,
            "configuration_count": material_configurations,
        },
        "accounting_policy": {
            "deduplicate_by": "immutable attempt_id or execution_attempt_id",
            "historical_snapshot_is_not_rewritten": True,
            "unknown_gpu_cpu_storage_usage_is_not_freed": True,
            "qualification_receipt_emission": False,
            "note": "The earlier reconciled-ledger excluded resume assets; this report includes the L2-R resume namespace and separates old snapshot from new counts.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESUME / "resource-reconciliation.json")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else LAB / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_report(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"report": str(output), "status": "written"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
