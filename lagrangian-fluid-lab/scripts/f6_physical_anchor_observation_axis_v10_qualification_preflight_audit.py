#!/usr/bin/env python3
"""Audit all 15 v4 F6 native preflight receipts without launching a solver."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
DESIGN_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921"
)
DESIGN = DESIGN_DIR / "design.json"
ADMISSION = DESIGN_DIR / "root-admission.json"
PREFLIGHT_ROOT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-preflight-v4-20260921"
)
OUTPUT = PREFLIGHT_ROOT / "qualification-preflight-audit.json"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def audit() -> dict[str, Any]:
    design = load(DESIGN)
    admission = load(ADMISSION)
    issues: list[str] = []
    if admission.get("status") != "admitted_for_fresh_native_preflight_only":
        issues.append("root admission is not open for fresh preflight")
    if design.get("status") != "root_review_only_not_submitted" or design.get("matrix_cell_count") != 15:
        issues.append("design status or count mismatch")

    rows: list[dict[str, Any]] = []
    for index, cell in enumerate(design.get("cells", [])):
        receipt_path = PREFLIGHT_ROOT / f"cell-{index:02d}" / "native" / "preflight.json"
        row: dict[str, Any] = {
            "index": index,
            "cell_id": cell.get("cell_id"),
            "path": str(receipt_path.relative_to(LAB)),
            "sha256": sha256(receipt_path) if receipt_path.is_file() else None,
        }
        if not receipt_path.is_file():
            row["pass"] = False
            row["issues"] = ["missing receipt"]
            issues.append(f"cell {index:02d}: missing receipt")
            rows.append(row)
            continue
        receipt = load(receipt_path)
        local: list[str] = []
        if receipt.get("status") != "cpu_native_preflight_pass_exact_one" or receipt.get("preflight_pass") is not True:
            local.append("native preflight did not pass exact-one")
        if receipt.get("cell_binding", {}).get("cell_id") != cell.get("cell_id"):
            local.append("cell identity mismatch")
        if receipt.get("qualification_claim") != "none" or receipt.get("qualification_credit") != 0 or receipt.get("T1") is not False:
            local.append("qualification guard failed")
        if receipt.get("qualification_only") is not True:
            local.append("not qualification-only")
        controls = receipt.get("execution_controls", {})
        for key in ("solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
            if controls.get(key) is not False:
                local.append(f"forbidden control {key}")
        for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "qualification_credit"):
            if controls.get(key) != 0:
                local.append(f"forbidden mutation {key}")
        native = receipt.get("native", {})
        if abs(float(native.get("mass_error_relative", 1.0))) > 0.05:
            local.append("continuous mass gate outside 5%")
        if not all(receipt.get("fresh_identity", {}).get("checks", {}).values()):
            local.append("fresh identity check failed")
        expected_frames = int(cell.get("time_contract", {}).get("expected_frame_count", -1))
        if receipt.get("event_window", {}).get("expected_frame_count") != expected_frames:
            local.append("expected frame count mismatch")
        row.update({
            "pass": not local,
            "issues": local,
            "design_cell": cell.get("design_cell"),
            "q": cell.get("parameter", {}).get("q"),
            "dp_m": cell.get("resolution", {}).get("dp_m"),
            "expected_frame_count": expected_frames,
            "native_particles": native.get("total_particles"),
            "fluid_particles": native.get("fluid_particles"),
            "mass_error_relative": native.get("mass_error_relative"),
        })
        if local:
            issues.extend([f"cell {index:02d}: {item}" for item in local])
        rows.append(row)

    complete = len(rows) == 15 and not issues and all(row.get("pass") for row in rows)
    return {
        "schema": "core.f6.observation_axis.qualification_preflight_audit.v1",
        "record_id": "F6_observation_axis_v10_qualification_preflight_audit_v4_20260921",
        "created_at_utc": stamp(),
        "status": "all_15_native_preflights_passed_no_solver_authorization" if complete else "qualification_preflight_audit_failed",
        "family": design.get("family"),
        "scope_id": design.get("scope_id"),
        "revision_id": design.get("revision_id"),
        "design_sha256": sha256(DESIGN),
        "admission_sha256": sha256(ADMISSION),
        "cell_count": len(rows),
        "matrix_complete": complete,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "solver_authorized": False,
        "gpu_launched": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "issues": issues,
        "cells": rows,
        "next_gate": "independent_root_authorization_for_solver_canary_cells" if complete else "retain_failures_and_revise_scope",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    value = audit()
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "cell_count": value["cell_count"], "matrix_complete": value["matrix_complete"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if value["matrix_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
