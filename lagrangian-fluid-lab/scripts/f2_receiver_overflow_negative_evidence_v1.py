#!/usr/bin/env python3
"""Collect one F2 receiver/overflow anchor as immutable negative evidence.

The preregistered fixed matrix is never edited in place.  This collector
creates a terminal matrix/denominator view that records the one executed row,
including overlapping hard-integrity and event-censor categories, and a
hash-bound scientific evidence receipt with zero qualification credit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import digest, write_json


BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"
SCOPE_ID = "F2_receiver_overflow_weir_v1"
REVISION_ID = "F2_receiver_overflow_weir_mdbc_v1"
MATRIX_INDEX = 4
MATRIX_CASE_ID = "CORE_F2_RECEIVER_OVERFLOW_WEIR_q0p50000000_crest0p26000000_dp0p007500000000_spatial"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def collect(
    attempt_dir: Path,
    *,
    base: Path = BASE,
    root_review: Path,
    job: Path,
    matrix_output: Path,
    denominator_output: Path,
    evidence_output: Path,
) -> dict[str, Any]:
    base = Path(base).resolve()
    attempt_dir = Path(attempt_dir).resolve()
    root_review = Path(root_review).resolve()
    job = Path(job).resolve()
    product = attempt_dir / "product"
    queue_receipt_path = attempt_dir / "result.json"
    product_result_path = product / "result.json"
    audit_path = product / "audit.json"
    observations_path = product / "observations.json"
    trajectory_path = product / "trajectory.h5"
    for path in (queue_receipt_path, product_result_path, audit_path, observations_path, trajectory_path, root_review, job):
        if not path.is_file():
            raise FileNotFoundError(path)
    queue_receipt = load(queue_receipt_path)
    product_result = load(product_result_path)
    audit = load(audit_path)
    observations = load(observations_path)
    root = load(root_review)
    job_payload = load(job)
    if queue_receipt.get("execution_status") != "succeeded":
        raise ValueError("anchor execution did not produce a completed queue receipt")
    if product_result.get("matrix_index") != MATRIX_INDEX or product_result.get("matrix_case_id") != MATRIX_CASE_ID:
        raise ValueError("product is not the protected matrix row")
    if audit.get("requested_horizon_reached") is not True:
        raise ValueError("negative evidence requires a complete registered horizon")
    if audit.get("hard_integrity_pass") is not False or audit.get("event_window_complete") is not False:
        raise ValueError("anchor is not the expected hard-failure/event-censor result")
    if root.get("decision") != "approved_for_one_anchor_runtime" or root.get("matrix_credit") != 0:
        raise ValueError("root review is not the protected zero-credit review")
    if job_payload.get("job_id") != queue_receipt.get("job_id"):
        raise ValueError("queue receipt/job identity mismatch")

    original_matrix_path = base / "fixed-matrix-v1.json"
    original_denominator_path = base / "failure-denominator-v1.json"
    matrix = load(original_matrix_path)
    rows = [row for row in matrix.get("rows", []) if int(row.get("index", -1)) == MATRIX_INDEX]
    if len(rows) != 1 or rows[0].get("case_id") != MATRIX_CASE_ID:
        raise ValueError("protected row missing from preregistered matrix")
    if any(row.get("status") != "not_started" for row in matrix.get("rows", [])):
        raise ValueError("preregistered matrix was edited in place")

    terminal_matrix = deepcopy(matrix)
    terminal_matrix["schema"] = "core.f2.receiver_overflow_weir.terminal_matrix.v1"
    terminal_matrix["status"] = "terminal_anchor_observed_other_rows_unattempted"
    terminal_matrix["created_at_utc"] = stamp()
    terminal_matrix["terminal_view_of"] = str(original_matrix_path)
    terminal_matrix["terminal_row"] = {
        "index": MATRIX_INDEX,
        "case_id": MATRIX_CASE_ID,
        "status": "failed_hard_integrity_and_event_censored",
        "hard_integrity_pass": False,
        "event_window_complete": False,
        "attempt_dir": str(attempt_dir),
        "product_result_sha256": digest(product_result_path),
        "audit_sha256": digest(audit_path),
        "trajectory_sha256": digest(trajectory_path),
    }
    terminal_matrix["rows"][MATRIX_INDEX] = dict(
        terminal_matrix["rows"][MATRIX_INDEX],
        status="failed_hard_integrity_and_event_censored",
        attempt_dir=str(attempt_dir),
        hard_integrity_pass=False,
        event_window_complete=False,
    )
    terminal_matrix["denominator"] = {
        "planned": 15,
        "executed": 1,
        "passed": 0,
        "failed": 1,
        "event_censored": 1,
        "unattempted": 14,
        "credit": 0,
        "categories_may_overlap": True,
    }
    terminal_matrix["qualification_claim"] = "none"
    terminal_matrix["matrix_credit"] = 0
    write_json(Path(matrix_output), terminal_matrix)

    terminal_denominator = {
        "schema": "core.f2.receiver_overflow_weir.terminal_failure_denominator.v1",
        "created_at_utc": stamp(),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualified": False,
        "qualification_claim": "none",
        "planned": 15,
        "executed": 1,
        "passed": 0,
        "failed": 1,
        "event_censored": 1,
        "unattempted": 14,
        "credit": 0,
        "categories_may_overlap": True,
        "matrix": ref(Path(matrix_output), "immutable terminal matrix view"),
        "preregistered_matrix": ref(original_matrix_path, "unchanged preregistered matrix"),
        "preregistered_denominator": ref(original_denominator_path, "unchanged preregistered denominator"),
        "preservation": {
            "all_rows_retained": True,
            "same_input_retry": False,
            "infrastructure_retry": True,
            "infrastructure_retry_reason": "one infrastructure lookup error was retained as a separate failed queue attempt; the completed anchor is the same registered input and carries no duplicate scientific credit",
            "threshold_relaxation": False,
            "horizon_extension_before_anchor": False,
            "static_hold_substitution": False,
            "survivor_renormalization": False,
            "canary_credit": 0,
            "cpu_native_preflight_credit": 0,
            "prior_lineages_merged": False,
        },
    }
    write_json(Path(denominator_output), terminal_denominator)

    evidence = {
        "schema": "core.f2.receiver_overflow_weir.negative_evidence.v1",
        "created_at_utc": stamp(),
        "status": "completed_scientific_negative_anchor",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": "F2",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "scientific_failure_class": "hard_integrity_failure_with_event_censoring",
        "event_interpretation": "receiver contact reached 1% and remained sustained, but no qualifying crest-crossing observation was recorded; event completion is false",
        "job": ref(job, "submitted exact-one-anchor job spec"),
        "root_review": ref(root_review, "exact-one-anchor root review"),
        "queue_attempt": ref(queue_receipt_path, "queue execution receipt"),
        "attempt_dir": str(attempt_dir),
        "products": {
            "result": ref(product_result_path, "worker scientific result"),
            "audit": ref(audit_path, "finite-geometry hard audit"),
            "observations": ref(observations_path, "receiver/crest observations"),
            "trajectory": ref(trajectory_path, "converted native trajectory"),
        },
        "hard_integrity": {
            "pass": False,
            "requested_horizon_reached": bool(audit["requested_horizon_reached"]),
            "finite_failure_count": int(audit["finite_failure_count"]),
            "endpoint_violation_particle_frames": int(audit["endpoint_violation_particle_frames"]),
            "obstacle_penetration_particle_frames": int(audit["obstacle_penetration_particle_frames"]),
            "saved_chord_crossing_count": int(audit["saved_chord_crossing_count"]),
            "mass_change_relative_max": float(audit["mass_change_relative_max"]),
        },
        "event_window": {
            "complete": False,
            "receiver_contact": observations["event_observation"].get("receiver_contact"),
            "crest_crossing": observations["event_observation"].get("crest_crossing"),
            "max_sustained_receiver_contact_s": observations["event_observation"].get("max_sustained_receiver_contact_s"),
        },
        "terminal_matrix": ref(Path(matrix_output), "terminal matrix view"),
        "terminal_denominator": ref(Path(denominator_output), "terminal failure denominator"),
        "execution_constraints": {
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "material_sidecar_started": False,
            "model_training_started": False,
            "qualification_matrix_expanded": False,
            "same_input_retry_scientific": False,
        },
    }
    write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-dir", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    parser.add_argument("--denominator-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(
        args.attempt_dir,
        base=args.base,
        root_review=args.root_review,
        job=args.job,
        matrix_output=args.matrix_output,
        denominator_output=args.denominator_output,
        evidence_output=args.output,
    )
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
