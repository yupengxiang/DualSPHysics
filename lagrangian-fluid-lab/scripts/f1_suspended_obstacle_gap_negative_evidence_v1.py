#!/usr/bin/env python3
"""Collect a hash-bound negative-evidence record for the G1 F1 anchor.

The runtime intentionally returns a non-zero status when the scientific hard
integrity gate fails.  This collector accepts that bounded scientific failure
when all products are present and the queue receipt has no infrastructure
error, preserving it in the denominator without promoting the scope.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "core.f1.suspended_obstacle_gap.negative_evidence.v1"
SCOPE_ID = "F1_suspended_obstacle_gap_v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def collect(*, attempt_dir: Path, job_spec: Path, root_review: Path, output: Path) -> dict[str, Any]:
    attempt_dir = Path(attempt_dir).resolve()
    job_spec = Path(job_spec).resolve()
    root_review = Path(root_review).resolve()
    product = attempt_dir / "product"
    receipt_path = attempt_dir / "result.json"
    required = (product / "result.json", product / "audit.json", product / "observations.json",
                product / "prepared.json", product / "trajectory.h5", receipt_path,
                job_spec, root_review)
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    spec, receipt = load(job_spec), load(receipt_path)
    result, audit = load(product / "result.json"), load(product / "audit.json")
    prepared, review = load(product / "prepared.json"), load(root_review)
    if spec.get("scope_id") != SCOPE_ID or prepared.get("config", {}).get("scope_id") != SCOPE_ID:
        raise ValueError("scope binding mismatch")
    if result.get("qualification_claim", "").startswith("none") is False:
        raise ValueError("scientific result is not qualification-neutral")
    if spec.get("root_review_sha256") != digest(root_review):
        raise ValueError("root review hash differs from job spec")
    if review.get("decision") != "approved_for_runtime_smoke" or review.get("qualification_claim") != "none":
        raise ValueError("root review is not the approved neutral anchor review")
    if receipt.get("error") not in (None, ""):
        raise ValueError("queue receipt contains an infrastructure error")
    if receipt.get("returncode") != 1 or receipt.get("execution_status") != "failed":
        raise ValueError("receipt is not the expected scientific hard-gate failure")
    if audit.get("requested_horizon_reached") is not True:
        raise ValueError("anchor did not reach its registered horizon")
    if audit.get("hard_integrity_pass") is not False:
        raise ValueError("anchor is not a negative hard-integrity result")
    evidence = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_scientific_negative_anchor",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "scope_id": SCOPE_ID,
        "family": "F1",
        "scientific_failure_class": "hard_integrity_failure_with_complete_event_window",
        "job": {"path": str(job_spec), "sha256": digest(job_spec), "job_id": spec.get("job_id"),
                "attempt_dir": str(attempt_dir), "attempt_result": ref(receipt_path, "queue execution receipt"),
                "allocation": receipt.get("allocation"), "usage": receipt.get("usage")},
        "binding": {"prepared": ref(product / "prepared.json", "runtime prepared view"),
                    "root_review": ref(root_review, "root runtime review"),
                    "case_id": result.get("case_id"),
                    "runtime_adapter": (ref(Path(result["runtime_adapter"]), "runtime adapter")
                                        if result.get("runtime_adapter") and Path(result["runtime_adapter"]).is_file()
                                        else {"path": result.get("runtime_adapter"), "sha256": None}),},
        "hard_integrity": {
            "pass": audit.get("hard_integrity_pass"),
            "requested_horizon_reached": audit.get("requested_horizon_reached"),
            "closed_wall_endpoint_particle_frames": audit.get("closed_wall_endpoint_particle_frames"),
            "obstacle_penetration_particle_frames": audit.get("obstacle_penetration_particle_frames"),
            "finite_geometry_chord_crossings": audit.get("finite_geometry_chord_crossings"),
            "structural_pass": audit.get("structural", {}).get("structural_pass"),
            "initial_valid_count": audit.get("structural", {}).get("initial_valid_count"),
            "final_valid_count": audit.get("structural", {}).get("final_valid_count"),
            "lifecycle_errors": audit.get("structural", {}).get("errors", []),
        },
        "event_window": {"complete": audit.get("event_window_complete"),
                          "status": audit.get("event_window_status"),
                          "interpretation": "event completion does not rescue failed hard integrity; scope remains unqualified"},
        "artifacts": {"result": ref(product / "result.json", "worker scientific result"),
                      "audit": ref(product / "audit.json", "hard integrity audit"),
                      "observations": ref(product / "observations.json", "geometry-aware event observations"),
                      "trajectory": ref(product / "trajectory.h5", "converted native trajectory")},
        "execution_constraints": {"registry_mutation": 0, "ledger_mutation": 0,
                                  "material_sidecar_started": False, "model_training_started": False,
                                  "qualification_matrix_expanded": False, "same_input_retry": False},
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    partial.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    partial.replace(output)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-dir", type=Path, required=True)
    parser.add_argument("--job-spec", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = collect(attempt_dir=args.attempt_dir, job_spec=args.job_spec,
                    root_review=args.root_review, output=args.output)
    print(json.dumps({"schema": value["schema"], "status": value["status"],
                      "hard_integrity": value["hard_integrity"], "matrix_credit": value["matrix_credit"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
