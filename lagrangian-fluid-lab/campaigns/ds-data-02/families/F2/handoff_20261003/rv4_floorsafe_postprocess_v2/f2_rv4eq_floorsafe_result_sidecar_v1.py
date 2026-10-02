#!/usr/bin/env python3
"""Bind the completed floor-safe PartVTKOut CPU diagnosis to a compact sidecar.

This reads the terminal shared-runtime receipt and the diagnostic JSON produced
by the official PartVTKOut request.  It records native counts and positions as
unknown numerical fate; it does not reinterpret any exclusion as physical
spill and does not grant Q-I/Q-N.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ROOT = Path(__file__).resolve().parents[2]
REQUEST = Path(__file__).resolve().parent / "rv4_floorsafe_native_partvtkout_request_v2.json"
CASE = "F2_RV4EQ_FLOORSAFE_NATIVE_PARTVTKOUT_20261003_V2"
ATTEMPT = "rv4-floorsafe-native-preflight-002"
OUTPUT_ROOT = DATA_ROOT / "families/F2" / CASE / ATTEMPT
SCHEMA = "ds-data-02.f2.rv4-floorsafe-result-sidecar.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def build(output: Path | None = None) -> dict[str, Any]:
    request = read_json(REQUEST, "floor-safe PartVTKOut request")
    receipt_path = OUTPUT_ROOT / "execution-receipt.json"
    report_path = OUTPUT_ROOT / "rv4-floorsafe-native-partvtkout-diagnostic.json"
    receipt = read_json(receipt_path, "shared-runtime receipt")
    report = read_json(report_path, "PartVTKOut diagnostic")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("floor-safe request does not have a terminal successful receipt")
    if report.get("status") != "diagnostic_complete_pending_scientific_review":
        raise ValueError(f"unexpected diagnostic status: {report.get('status')}")
    cases = []
    for case in report.get("cases", []):
        timeline = case["native_timeline"]
        exclusion = case["partvtkout_exclusions"]
        records = exclusion["records"]
        first_times = [float(row["first_missing_time_s"]) for row in records]
        first_frames = [int(row["first_missing_frame"]) for row in records]
        if not all(row.get("physical_fate") == "unknown" for row in records):
            raise ValueError(f"physical fate was assigned in native diagnostic: {case['case_id']}")
        cases.append({
            "case_id": case["case_id"],
            "background": case["background"],
            "mechanism_id": case["mechanism_id"],
            "dp_m": case["dp_m"],
            "timeline": {
                "rows": timeline["rows"],
                "first_time_s": timeline["first_time_s"],
                "last_time_s": timeline["last_time_s"],
                "NpOut_sum": timeline["NpOut_sum"],
                "NpOutPos_sum": timeline["NpOutPos_sum"],
                "NpOutRho_sum": timeline["NpOutRho_sum"],
                "NpOutMov_sum": timeline["NpOutMov_sum"],
                "full_window_completed": timeline["full_window_completed"],
                "runparts_sha256": timeline["sha256"],
            },
            "motive_totals": exclusion["motive_totals"],
            "record_count": len(records),
            "first_missing_frame_range": [min(first_frames), max(first_frames)] if first_frames else None,
            "first_missing_time_range_s": [min(first_times), max(first_times)] if first_times else None,
            "domain_face_evidence_totals": exclusion["domain_face_evidence_totals"],
            "all_rows_native_numerical_unknown": exclusion["all_rows_are_native_numerical_unknown"],
            "records_jsonl": exclusion["enriched_records"],
            "official_partvtkout": exclusion["binary"],
        })
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "scope_id": "F2_SCOPE_RV4_EQUIVALENT_DP005_FLOORSAFE_NATIVE_DIAGNOSTIC_20261003",
        "request": {"path": str(REQUEST.resolve()), "sha256": sha256(REQUEST), "attempt_id": ATTEMPT, "case_id": CASE},
        "runtime_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path), "status": receipt["status"], "returncode": receipt["returncode"], "elapsed_seconds": receipt.get("elapsed_seconds"), "cpu_core_seconds": receipt.get("cpu_core_seconds"), "gpu_seconds": receipt.get("gpu_seconds", 0.0)},
        "diagnostic_report": {"path": str(report_path), "sha256": sha256(report_path), "status": report["status"]},
        "cases": cases,
        "verdict": {
            "official_partvtkout_completed": True,
            "all_native_exclusions_remain_unknown": all(case["all_rows_native_numerical_unknown"] for case in cases),
            "domain_and_motive_evidence_recorded": all(case["record_count"] == case["timeline"]["NpOut_sum"] for case in cases),
            "moving_boundary_exclusion_sum_zero": all(case["timeline"]["NpOutMov_sum"] == 0 for case in cases),
            "physical_spill_claim": "none",
            "q_i_status": "native exclusion evidence only; moving-pose/lifecycle/full-QI closure pending",
            "q_n_status": "not_assessed",
            "production_status": "not_evaluated",
        },
        "claim_boundary": "Motive 1/2 and domain-face positions describe native numerical exclusions. They do not establish cup departure, legal tray spill, wall penetration, or Q-N without pose-resolved lifecycle evidence.",
    }
    output = Path(output or (Path(__file__).resolve().parent / "rv4-floorsafe-result-sidecar-v1.json")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = {"path": str(output), "sha256": sha256(output)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps(result["verdict"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
