#!/usr/bin/env python3
"""Collect a completed F2 DBC extension without opening trajectory.h5.

The runtime worker owns solver execution and the qualification observer owns
the JSON evidence.  This utility only hashes terminal JSON outputs and
applies the pre-registered launch decision.  It refuses a live or partial
attempt so collection cannot race the writer or accidentally inspect HDF5.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.f2.dbc_duration.extension_collection.v1"
REQUIRED_JSON = ("result.json", "audit.json", "observations.json")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def collect(product: Path, output: Path, verification: Path | None = None) -> dict[str, Any]:
    product = Path(product).resolve()
    output = Path(output).resolve()
    # core_runtime places the terminal status beside the product outputs.
    # Keep a parent fallback for older attempt layouts.
    status_path = product / "worker-status.json"
    if not status_path.is_file():
        status_path = product.parent / "worker-status.json"
    status = json.loads(status_path.read_text()) if status_path.is_file() else {}
    partial_h5 = product / "trajectory.h5.partial"
    h5 = product / "trajectory.h5"
    missing = [name for name in REQUIRED_JSON if not (product / name).is_file()]
    terminal = status.get("status") in {"complete", "complete_with_evidence", "failed", "failed_with_evidence"}
    if partial_h5.exists() or not terminal or missing:
        report = {
            "schema": SCHEMA,
            "created_at": _stamp(),
            "product": str(product),
            "collection_status": "pending",
            "reason": {
                "worker_status": status.get("status"),
                "terminal": bool(terminal),
                "trajectory_h5_partial_present": partial_h5.exists(),
                "trajectory_h5_present": h5.exists(),
                "missing_json": missing,
            },
            "h5_opened": False,
            "qualification_claim": "none",
        }
        _write_json(output, report)
        return report

    json_files = {}
    parsed = {}
    for name in REQUIRED_JSON:
        path = product / name
        json_files[name] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        parsed[name] = json.loads(path.read_text())

    verification_record = None
    verified_trajectory_sha256 = None
    if verification is not None:
        verification = Path(verification).resolve()
        verification_record = {
            "path": str(verification),
            "sha256": _sha256(verification),
        }
        verified = json.loads(verification.read_text())
        mismatches = []
        for item in verified.get("verified_outputs", []):
            name = Path(item.get("path", "")).name
            if name == "trajectory.h5":
                verified_trajectory_sha256 = item.get("sha256")
            if name in json_files and item.get("sha256") != json_files[name]["sha256"]:
                mismatches.append(name)
        if mismatches:
            raise ValueError(f"root verification hash mismatch: {mismatches}")

    result = parsed["result.json"]
    hard = bool(result.get("hard_integrity_pass"))
    horizon = bool(result.get("requested_horizon_reached"))
    complete = bool(result.get("event_window_complete"))
    execution_succeeded = bool(
        verification_record is not None
        or status.get("status") in {"complete", "complete_with_evidence"}
    )
    if not execution_succeeded:
        decision = "candidate_insufficient_execution_status"
    elif not hard:
        decision = "candidate_insufficient_hard_integrity"
    elif not horizon:
        decision = "candidate_insufficient_horizon"
    elif not complete:
        decision = "candidate_insufficient_event_window"
    else:
        decision = "eligible_for_root_matrix_review"
    report = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "product": str(product),
        "collection_status": "collected",
        "worker_status": status,
        "verified_json_outputs": json_files,
        "verification_receipt": verification_record,
        "trajectory_h5": {
            "path": str(h5),
            "bytes": h5.stat().st_size,
            "sha256": verified_trajectory_sha256,
            "sha256_source": "external root verification receipt" if verified_trajectory_sha256 else "not computed by this H5-blind collector",
            "opened": False,
        },
        "scientific_decision": {
            "execution_succeeded": execution_succeeded,
            "hard_integrity_pass": hard,
            "requested_horizon_reached": horizon,
            "event_window_complete": complete,
            "decision": decision,
            "development_canary_only": True,
            "independent_matrix_numerator_eligible": False,
            "further_horizon_extension_allowed": False,
            "thresholds_changed": False,
        },
        "event_times_s": result.get("event_window", {}).get("event_times_s"),
        "qualification_claim": "none; extension collection and launch decision only",
        "h5_opened": False,
    }
    _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification", type=Path)
    args = parser.parse_args()
    report = collect(args.product, args.output, args.verification)
    print(json.dumps({
        "collection_status": report["collection_status"],
        "decision": report.get("scientific_decision", {}).get("decision"),
        "h5_opened": report.get("h5_opened"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
