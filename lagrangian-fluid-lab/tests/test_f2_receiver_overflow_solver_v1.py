import json
from pathlib import Path

from scripts.f2_receiver_overflow_solver_v1 import (
    JOB_ID,
    MATRIX_CASE_ID,
    MATRIX_INDEX,
    REVIEW_DECISION,
    make_job,
    make_root_review,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"


def test_root_review_is_exact_one_anchor_and_no_scientific_credit(tmp_path):
    path = tmp_path / "review.json"
    review = make_root_review(BASE, path)
    assert path.is_file()
    assert review["decision"] == REVIEW_DECISION
    assert review["authorized_case_ids"] == ["F2_receiver_overflow_weir_q0p5_anchor"]
    assert review["authorized_matrix_indices"] == [MATRIX_INDEX]
    assert review["authorized_matrix_case_ids"] == [MATRIX_CASE_ID]
    assert review["exact_one_anchor"] is True
    assert review["qualification_claim"] == "none"
    assert review["matrix_credit"] == 0
    assert review["authorization"]["solver_launch"] is True
    assert review["authorization"]["gpu_launch"] is True
    assert review["authorization"]["registry_mutation"] is False
    assert review["authorization"]["matrix_submission"] is False
    assert review["execution_boundary"]["same_input_retry"] is False
    assert len(review["input_hash_bindings"]) >= 14


def test_job_is_hash_bound_to_review_and_still_zero_credit(tmp_path):
    review_path = tmp_path / "review.json"
    job_path = tmp_path / "job.json"
    make_root_review(BASE, review_path)
    job = make_job(BASE, review_path, job_path)
    saved = json.loads(job_path.read_text())
    assert saved["schema"] == "core.cfd.job.v1"
    assert saved["job_id"] == JOB_ID
    assert saved["matrix_index"] == MATRIX_INDEX
    assert saved["matrix_case_id"] == MATRIX_CASE_ID
    assert saved["qualification_claim"] == "none"
    assert saved["solver_launch_authorized"] is True
    assert saved["registry_mutation_authorized"] is False
    assert saved["matrix_submission_authorized"] is False
    assert saved["argv"][-1] == "{attempt_dir}/product"
    assert len(saved["input_files"]) == 11
