#!/usr/bin/env python3
"""Collect a hash-bound, qualification-neutral report for one F2 H2-v5 canary."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "core.f2.h2_mdbc.static_range_v5.runtime_canary_evidence.v1"
SCOPE_ID = "F2_H2_mdbc_static_range_qualification_v5"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


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
    for path in (product / "result.json", product / "audit.json", product / "prepared.json",
                 product / "trajectory.h5", receipt_path, job_spec, root_review):
        if not path.is_file():
            raise FileNotFoundError(path)
    spec = load(job_spec)
    receipt = load(receipt_path)
    result = load(product / "result.json")
    audit = load(product / "audit.json")
    prepared = load(product / "prepared.json")
    review = load(root_review)
    if spec.get("scope_id") != SCOPE_ID or prepared.get("scope_id") != SCOPE_ID or result.get("scope_id") != SCOPE_ID:
        raise ValueError("scope binding mismatch")
    if spec.get("qualification_claim") != "none" or result.get("qualification_claim", "").startswith("none") is False:
        raise ValueError("qualification claim is not neutral")
    if spec.get("prepared_sha256") != digest(product / "prepared.json"):
        raise ValueError("product prepared hash differs from job spec")
    if spec.get("root_review_sha256") != digest(root_review):
        raise ValueError("root review hash differs from job spec")
    if review.get("qualification_claim") != "none" or review.get("registry_mutation") != 0:
        raise ValueError("root review authorization is not qualification-neutral")
    if receipt.get("execution_status") != "succeeded" or receipt.get("returncode") != 0:
        raise ValueError("queue receipt is not a successful execution")
    if audit.get("hard_integrity_pass") is not True or audit.get("requested_horizon_reached") is not True:
        raise ValueError("canary hard integrity or horizon failed; collect negative evidence separately")
    result_ref = ref(product / "result.json", "worker scientific result")
    audit_ref = ref(product / "audit.json", "hard integrity audit")
    trajectory_ref = ref(product / "trajectory.h5", "converted native trajectory")
    evidence = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_bounded_runtime_canary",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "scope_id": SCOPE_ID,
        "family": "F2",
        "job": {"path": str(job_spec), "sha256": digest(job_spec), "job_id": spec.get("job_id"),
                "attempt_dir": str(attempt_dir), "attempt_result": ref(receipt_path, "queue execution receipt"),
                "allocation": receipt.get("allocation"), "usage": receipt.get("usage")},
        "binding": {"prepared": ref(product / "prepared.json", "runtime prepared view"),
                    "root_review": ref(root_review, "root runtime review"),
                    "case_id": result.get("case_id"), "cell_index": result.get("cell_index"),
                    "runtime_prepared_sha256": result.get("runtime_prepared_sha256")},
        "hard_integrity": {"pass": audit.get("hard_integrity_pass"),
                           "requested_horizon_reached": audit.get("requested_horizon_reached"),
                           "wall_violation_count": audit.get("endpoint_violation_particle_frames"),
                           "saved_chord_crossing_count": audit.get("saved_chord_crossing_count"),
                           "structural_pass": audit.get("structural", {}).get("structural_pass"),
                           "frame_count": result.get("structural", {}).get("frame_count"),
                           "particle_count": result.get("structural", {}).get("particle_count"),
                           "time_end_s": result.get("structural", {}).get("time_end_s")},
        "mass": {"initial_mass_kg": result.get("structural", {}).get("initial_mass_kg"),
                 "final_mass_kg": result.get("structural", {}).get("final_mass_kg"),
                 "mass_change_max_relative": result.get("structural", {}).get("mass_change_max_relative"),
                 "native_sampling_policy": "rho*dp^3; no mass rescaling"},
        "event_window": {"complete": audit.get("event_window_complete"),
                          "status": audit.get("event_window_status"),
                          "interpretation": "static-hold canary; event completeness is not a T1 qualification result"},
        "artifacts": {"result": result_ref, "audit": audit_ref, "trajectory": trajectory_ref},
        "execution_constraints": {"registry_mutation": 0, "ledger_mutation": 0,
                                  "material_sidecar_started": False, "model_training_started": False,
                                  "qualification_matrix_expanded": False},
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
