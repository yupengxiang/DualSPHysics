#!/usr/bin/env python3
"""Record the sampled hard failure of the protected F5 solver anchor.

The F5 anchor produced a complete raw solver product, but the first worker
classified it as failed because it parsed ``Run.out`` with the wrong cadence
field.  A read-only postrun audit repaired that execution classification.  A
separate sampled scientific review then found positive wall penetration and
saved-frame chord crossings.  One positive sample is sufficient to fail the
registered zero-tolerance geometry gate; this collector preserves that fact
without rerunning the solver or claiming full-frame coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.f5.third_t1.solver_anchor.negative_evidence.v1"
FAMILY = "F5"
SCOPE_ID = "F5_prescribed_wave_runup_x_v1"
EXPECTED_CASE = "F5_wave_runup_q0p50_dp0p0075_v2"


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


def collect(*, attempt: Path, job_spec: Path, root_review: Path,
            postrun_audit: Path, scientific_review: Path,
            output: Path) -> dict[str, Any]:
    attempt = Path(attempt).resolve()
    job_spec = Path(job_spec).resolve()
    root_review = Path(root_review).resolve()
    postrun_audit = Path(postrun_audit).resolve()
    scientific_review = Path(scientific_review).resolve()
    product = attempt / "product"
    receipt_path = attempt / "result.json"
    required = (
        attempt / "spec.json", receipt_path, product / "solver/Run.out",
        product / "postrun-audit-v2.json", product / "scientific-review-sampled-v1.json",
        job_spec, root_review,
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    spec = load(attempt / "spec.json")
    receipt = load(receipt_path)
    job = load(job_spec)
    review = load(root_review)
    postrun = load(postrun_audit)
    scientific = load(scientific_review)
    if job.get("scope_id") != SCOPE_ID or job.get("prepared_case_id") != EXPECTED_CASE:
        raise ValueError("F5 job identity mismatch")
    if review.get("scope_id") != SCOPE_ID or review.get("candidate_case_id") != EXPECTED_CASE:
        raise ValueError("F5 root review identity mismatch")
    if job.get("root_review", {}).get("sha256") != digest(root_review):
        raise ValueError("job is not bound to the root review")
    if postrun.get("raw_solver_product_complete") is not True:
        raise ValueError("raw solver product is not complete")
    if postrun.get("cadence_reconciliation", {}).get("pass") is not True:
        raise ValueError("Run.out cadence reconciliation did not pass")
    if postrun.get("execution_reconciliation", {}).get("same_input_retry") is not False:
        raise ValueError("same-input retry was recorded")
    if scientific.get("case_id") != EXPECTED_CASE or scientific.get("matrix_credit") != 0:
        raise ValueError("scientific review is not bound to the zero-credit F5 anchor")
    coverage = scientific.get("coverage", {})
    geometry = scientific.get("geometry", {})
    penetration = int(geometry.get("entity_penetration_particle_frames", 0))
    crossings = int(geometry.get("saved_chord_crossing_count", 0))
    if coverage.get("frames_available") != 801 or coverage.get("full_frame_coverage") is not False:
        raise ValueError("sampled review does not preserve its partial-coverage boundary")
    if penetration <= 0 or crossings <= 0:
        raise ValueError("sampled review has no positive hard-gate violation")
    if scientific.get("qualification_claim") != "none":
        raise ValueError("scientific review carries a qualification claim")

    payload = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_scientific_negative_anchor_sampled_geometry",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "case_id": EXPECTED_CASE,
        "scientific_failure_class": "sampled_zero_tolerance_geometry_failure",
        "interpretation": (
            "The raw solver product is complete, but sampled frames contain positive "
            "entity penetration and saved-frame chord crossings. The registered F5 "
            "hard gates require zero of both; one observed positive sample is enough "
            "to reject this anchor. The report intentionally does not claim full-frame "
            "coverage, event completion, or T1 credit."
        ),
        "execution": {
            "raw_solver_product_complete": True,
            "solver_finished_code_zero": postrun.get("run", {}).get("finished_code_zero"),
            "requested_horizon_s": postrun.get("run", {}).get("timemax_s"),
            "output_cadence_s": postrun.get("run", {}).get("output_dt_values_s"),
            "frames": postrun.get("frames", {}).get("count"),
            "excluded_particles": postrun.get("run", {}).get("excluded_particles"),
            "worker_cadence_parser_bug": postrun.get("cadence_reconciliation", {}).get("parser_bug_in_prior_worker"),
            "same_input_retry": False,
        },
        "hard_integrity": {
            "pass": False,
            "gate_policy": {
                "entity_penetration_particle_frames": 0,
                "saved_chord_crossing_count": 0,
            },
            "observed_sampled": {
                "frames_decoded": coverage.get("frames_decoded"),
                "frames_available": coverage.get("frames_available"),
                "entity_penetration_particle_frames": penetration,
                "saved_chord_crossing_count": crossings,
                "by_component": geometry.get("entity_penetration_by_component_particle_frames", {}),
                "full_frame_coverage": coverage.get("full_frame_coverage"),
                "full_particle_coverage": coverage.get("full_particle_coverage"),
            },
        },
        "events": {
            "status": "not_admitted_after_hard_geometry_failure",
            "event_thresholds_preregistered": False,
            "external_reference_acceptance": "diagnostic_only",
        },
        "artifacts": {
            "attempt_spec": ref(attempt / "spec.json", "immutable coordinator attempt spec"),
            "attempt_receipt": ref(receipt_path, "coordinator execution receipt"),
            "job_spec": ref(job_spec, "protected F5 job spec"),
            "root_review": ref(root_review, "protected F5 root review"),
            "postrun_audit": ref(postrun_audit, "read-only cadence/product audit"),
            "scientific_review": ref(scientific_review, "sampled geometry/event review"),
            "run_out": ref(product / "solver/Run.out", "raw solver log"),
        },
        "authorization_boundary": {
            "solver_invoked": True,
            "gpu_invoked": True,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
            "same_input_retry": False,
        },
    }
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--job-spec", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--postrun-audit", type=Path, required=True)
    parser.add_argument("--scientific-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = collect(attempt=args.attempt, job_spec=args.job_spec, root_review=args.root_review,
                     postrun_audit=args.postrun_audit, scientific_review=args.scientific_review,
                     output=args.output)
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "matrix_credit": result["matrix_credit"],
                      "entity_penetration_particle_frames": result["hard_integrity"]["observed_sampled"]["entity_penetration_particle_frames"],
                      "saved_chord_crossing_count": result["hard_integrity"]["observed_sampled"]["saved_chord_crossing_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
