from __future__ import annotations

from scripts import f2_static_receiver_ballistic_catch_solver_infra_retry_root_review_v1 as review


def test_retry_is_bound_to_loader_failure_and_keeps_science_fixed():
    result = review.verify_review()
    assert result["status"] == "ok"
    assert result["retry_index"] == 1
    assert result["scientific_input_changed"] is False
    assert result["matrix_credit"] == 0
    failure = review.check_first_failure()
    assert failure["returncode"] == 127
    assert failure["frame_count"] == 0
    assert failure["defect"] == "missing_official_shared_library_path"


def test_retry_job_spec_does_not_open_registry_or_matrix():
    spec = review.build_job_spec()
    assert spec["retry_policy"]["scientific_input_changed"] is False
    assert spec["retry_policy"]["same_input_scientific_retry"] is False
    assert spec["registry_mutation"] == 0
    assert spec["matrix_credit"] == 0
