from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f2_h2_mdbc_static_range_v5_batch as batch


LAB = Path(__file__).resolve().parents[1]
CANDIDATE = LAB / "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
MATRIX = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/matrix-preparation.json"
)
CANARY = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "runtime-canary-evidence-cell11-v1.json"
)
CELL11_REVIEW = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5-runtime-root-review-cell11-v2.json"
)


def _prepare_batch(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    admission = batch.build_admission(lab=LAB, candidate_path=CANDIDATE,
                                      matrix_path=MATRIX, canary_path=CANARY)
    admission_path = tmp_path / "admission.json"
    batch.write_json(admission_path, admission)
    manifest = batch.build_job_specs(
        lab=LAB, admission_path=admission_path, candidate_path=CANDIDATE,
        matrix_path=MATRIX, output_dir=tmp_path / "jobs",
    )
    return admission, manifest, admission_path, tmp_path / "jobs" / "batch-job-specs.json"


def test_admission_is_root_review_ready_but_keeps_fifteen_rows_and_zero_mutation() -> None:
    value = batch.build_admission(lab=LAB, candidate_path=CANDIDATE,
                                  matrix_path=MATRIX, canary_path=CANARY)
    assert value["status"] == "root_review_ready"
    assert value["decision"] == "eligible_for_root_review_only"
    assert value["fixed_denominator"]["registered_cell_denominator"] == 15
    assert value["batch"]["requested_indices"] == list(range(8))
    assert value["batch"]["fixed_8_to_32_compatible"] is False
    assert value["qualification_only"] is True
    assert value["qualified"] is False
    assert value["T1_numerical"] is False
    assert value["authorization"]["solver_launch"] is False
    assert value["authorization"]["queue_mutation"] == 0
    assert value["authorization"]["ledger_mutation"] == 0
    assert value["authorization"]["registry_mutation"] == 0


def test_existing_cell11_review_cannot_authorize_eight_cell_batch() -> None:
    with pytest.raises(ValueError, match="eight-cell batch"):
        batch.build_admission(
            lab=LAB, candidate_path=CANDIDATE, matrix_path=MATRIX,
            canary_path=CANARY, root_review_path=CELL11_REVIEW,
        )


def test_job_specs_are_drafts_with_forbidden_mutations(tmp_path: Path) -> None:
    admission, manifest, _, _ = _prepare_batch(tmp_path)
    assert manifest["status"] == "root_review_ready_not_submitted"
    assert manifest["batch_size"] == 8
    assert manifest["cell_indices"] == list(range(8))
    assert manifest["execution_controls"] == {
        "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0,
        "ledger_mutation": 0, "registry_mutation": 0,
    }
    for item in manifest["job_specs"]:
        spec = json.loads(Path(item["path"]).read_text())
        assert spec["submission_status"] == "blocked_pending_root_review"
        assert spec["qualification_only"] is True
        assert spec["qualification_claim"] == "none"
        assert spec["solver_launch_authorized"] is False
        assert spec["gpu_launch_authorized"] is False
        assert spec["queue_mutation_authorized"] is False
        assert spec["ledger_mutation_authorized"] is False
        assert spec["registry_mutation_authorized"] is False
        assert spec["registered_denominator"] == 15
        assert spec["argv"] == []
    assert admission["authorization"]["submission_status"] == "not_submitted"


def test_empty_collection_retains_fifteen_unattempted_rows(tmp_path: Path) -> None:
    _, _, admission_path, manifest_path = _prepare_batch(tmp_path)
    evidence = batch.collect_evidence(
        admission_path=admission_path, jobs_manifest_path=manifest_path,
        attempt_dirs={}, output=tmp_path / "evidence.json",
    )
    assert evidence["matrix_credit"] == 0
    assert evidence["batch"]["registered_denominator"] == 15
    assert evidence["batch"]["attempted_count"] == 0
    assert evidence["batch"]["unattempted_count"] == 15
    assert len(evidence["failure_denominator"]["rows"]) == 15
    assert all(row["status"] == "unattempted" for row in evidence["failure_denominator"]["rows"])
    assert evidence["execution_controls"]["ledger_mutation"] == 0
    assert evidence["execution_controls"]["registry_mutation"] == 0


def test_event_censored_attempt_is_retained_as_failure(tmp_path: Path) -> None:
    _, manifest, admission_path, manifest_path = _prepare_batch(tmp_path)
    spec_item = manifest["job_specs"][0]
    spec = json.loads(Path(spec_item["path"]).read_text())
    attempt = tmp_path / "attempt"
    product = attempt / "product"
    product.mkdir(parents=True)
    prepared = {"scope_id": batch.SCOPE_ID, "schema": batch.CELL_SCHEMA}
    result = {
        "scope_id": batch.SCOPE_ID, "cell_index": 0,
        "case_id": spec["prepared_case_id"], "qualification_claim": "none; receipt",
        "qualified": False, "registry_mutation": 0,
    }
    audit = {"hard_integrity_pass": True, "requested_horizon_reached": True,
             "event_window_complete": False}
    (product / "prepared.json").write_text(json.dumps(prepared))
    (product / "result.json").write_text(json.dumps(result))
    (product / "audit.json").write_text(json.dumps(audit))
    (product / "trajectory.h5").write_bytes(b"trajectory")
    (attempt / "result.json").write_text(json.dumps({"execution_status": "succeeded", "returncode": 0}))
    evidence = batch.collect_evidence(
        admission_path=admission_path, jobs_manifest_path=manifest_path,
        attempt_dirs={spec["job_id"]: attempt}, output=tmp_path / "evidence.json",
    )
    row = evidence["failure_denominator"]["rows"][0]
    assert row["status"] == "event_censored"
    assert row["pass"] is False
    assert evidence["batch"]["attempted_count"] == 1
    assert evidence["batch"]["failed_or_unresolved_count"] == 1
    assert evidence["batch"]["unattempted_count"] == 14
    assert evidence["matrix_credit"] == 0
