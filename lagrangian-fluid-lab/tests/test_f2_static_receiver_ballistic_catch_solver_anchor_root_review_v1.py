from __future__ import annotations

import json

from scripts import f2_static_receiver_ballistic_catch_solver_anchor_root_review_v1 as review


def test_anchor_root_review_is_zero_credit_and_exact_one():
    # The original receipt is immutable historical evidence.  Its worker hash
    # intentionally predates the later repaired-infrastructure worker.
    receipt = json.loads(review.REVIEW_OUTPUT.read_text())
    assert receipt["status"] == "authorized_one_protected_gpu_solver_anchor_pending_submission"
    assert receipt["case_id"] == review.CASE_ID
    assert receipt["authorization"]["solver_invocations"] == 1
    assert receipt["matrix_credit"] == 0
    assert receipt["submission"]["submitted"] is False


def test_anchor_job_spec_keeps_registry_closed():
    spec = review.build_job_spec()
    assert spec["solver_launch"] is True
    assert spec["gpu_launch"] is True
    assert spec["registry_mutation"] == 0
    assert spec.get("matrix_submission", 0) == 0
    assert spec["qualification_claim"].startswith("none")
    assert any(item["path"].endswith("f2_static_receiver_ballistic_catch_solver_worker_v1.py")
               for item in spec["input_files"])
