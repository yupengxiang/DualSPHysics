#!/usr/bin/env python3
"""Audit the completed H2 solver product without rerunning the canary.

The native solver reached the requested horizon and wrote a complete
trajectory.  The old runtime wrapper then failed while rebinding its final
receipt because the H2 manifest called the source hash
``source_preflight_sha256``.  This audit keeps that infrastructure defect
separate from the scientific wall-integrity result and gives the canary zero
qualification credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
ATTEMPT = LAB / "campaigns/core-v1/runtime/attempts/f2-static-full-cup-boundary-repair-h2-cell0-canary-v1/20260921T124208-8586758b73e0"
OUTPUT = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-postrun-audit-v1.json"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-root-review-v1.json"
JOB_ID = "f2-static-full-cup-boundary-repair-h2-cell0-canary-v1"
CASE_ID = "CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def build(*, attempt: Path = ATTEMPT, output: Path = OUTPUT) -> dict[str, Any]:
    attempt = Path(attempt).resolve()
    product = attempt / "product"
    spec = load(attempt / "spec.json")
    queue_result = load(attempt / "result.json")
    prepared = load(product / "prepared.json")
    result = load(product / "result.json")
    audit = load(product / "audit.json")
    worker = load(product / "worker-status.json")
    root_review = load(ROOT_REVIEW)
    if spec.get("job_id") != JOB_ID or spec.get("prepared_case_id") != CASE_ID:
        raise ValueError("H2 attempt identity mismatch")
    if spec.get("root_review_sha256") != digest(ROOT_REVIEW):
        raise ValueError("H2 attempt is not bound to the current runtime root review")
    if result.get("schema") != "core.cfd.v1" or result.get("case_id") != CASE_ID:
        raise ValueError("H2 product result schema/case mismatch")
    if audit.get("hard_integrity_pass") is not False or result.get("hard_integrity_pass") is not False:
        raise ValueError("H2 product is no longer a hard-integrity negative")
    structural = result.get("structural", {})
    expected = {
        "requested_horizon_reached": result.get("requested_horizon_reached") is True,
        "frame_count": structural.get("frame_count") == 31,
        "time_end_s": float(structural.get("time_end_s", 0.0)) >= 0.60,
        "endpoint_violation_particle_frames": result.get("endpoint_violation_particle_frames") == 168,
        "saved_chord_crossing_count": result.get("saved_chord_crossing_count") == 21,
        "wall_violation_count": structural.get("wall_violation_count") == 168,
        "excluded_particle_count": structural.get("death_count") == 14,
        "complete_worker_product": worker.get("status") == "complete_with_evidence",
        "solver_finished_code_zero": "Finished execution (code=0)." in (product / "solver.stdout.log").read_text(encoding="utf-8"),
    }
    if not all(expected.values()):
        raise ValueError(f"H2 scientific/solver evidence changed: {expected}")
    wrapper_text = (attempt / "stdout.log").read_text(encoding="utf-8")
    wrapper_failure = "KeyError: 'source_prepared_sha256'" in wrapper_text
    if not wrapper_failure:
        raise ValueError("expected wrapper postrun metadata failure is absent")
    payload = {
        "schema": "core.f2.static_full_cup.boundary_repair_h2.runtime_postrun_audit.v1",
        "record_id": "f2-static-full-cup-boundary-repair-h2-runtime-postrun-audit-v1",
        "created_at_utc": stamp(),
        "family": "F2", "scope_id": "F2_static_full_cup_volume_hold_x_v1",
        "repair_id": "F2_static_full_cup_initial_support_clearance_h2_v1",
        "job_id": JOB_ID, "case_id": CASE_ID,
        "root_review": ref(ROOT_REVIEW, "H2 runtime root review"),
        "attempt": ref(attempt / "spec.json", "immutable coordinator attempt spec"),
        "queue_result": ref(attempt / "result.json", "coordinator execution receipt"),
        "prepared": ref(product / "prepared.json", "H2 runtime prepared manifest"),
        "product_result": ref(product / "result.json", "native solver result/audit product"),
        "product_audit": ref(product / "audit.json", "full trajectory wall audit"),
        "trajectory": ref(product / "trajectory.h5", "converted native trajectory"),
        "scientific_status": {
            "solver_execution": "completed_to_registered_horizon",
            "solver_exit_code": 0,
            "hard_integrity_pass": False,
            "T1_numerical": False,
            "qualification_claim": "none; one H2 solver canary negative result",
            "wall_endpoint_violation_particle_frames": 168,
            "unique_wall_violation_id_count": len(result.get("unique_wall_violation_ids", [])),
            "saved_chord_crossing_count": 21,
            "excluded_particle_count": 14,
            "requested_horizon_reached": True,
        },
        "infrastructure_status": {
            "coordinator_execution_status": queue_result.get("execution_status"),
            "worker_product_complete": True,
            "wrapper_postrun_failure": wrapper_failure,
            "failure_class": "postrun_metadata_rebind_missing_source_prepared_sha256",
            "compatibility_patch_recorded": True,
            "same_input_retry": False,
        },
        "fixed_failure_denominator": {
            "planned": 15, "executed": 1, "passed": 0, "failed": 1, "unattempted": 14,
            "survivor_renormalization": False, "same_input_retry": False,
        },
        "resource_usage": queue_result.get("usage", {}),
        "authorization_boundary": {
            "solver_invoked": True, "gpu_invoked": True, "registry_mutation": 0,
            "ledger_mutation": 0, "qualification_credit": 0, "matrix_expansion": False,
        },
        "checks": expected,
        "interpretation": "The support-clearance input passed CPU/native gates but failed the full static solver wall-integrity gate. The wrapper metadata exception is preserved separately and does not turn the scientific negative into an infrastructure-only result.",
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=Path, default=ATTEMPT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    value = build(attempt=args.attempt, output=args.output)
    print(json.dumps({"status": value["scientific_status"]["qualification_claim"], "hard_integrity_pass": value["scientific_status"]["hard_integrity_pass"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
