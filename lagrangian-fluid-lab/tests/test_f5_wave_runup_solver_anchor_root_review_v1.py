from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_solver_anchor_root_review_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_anchor_root_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_static_evidence_is_hash_closed_and_output_fresh():
    evidence = MODULE._verify_static_evidence()
    assert evidence["preflight"]["qualified"] is False
    assert evidence["preflight"]["matrix_credit"] == 0
    assert not MODULE.ANCHOR_STEM.exists()


def test_review_and_job_are_root_review_only(tmp_path):
    review_path = MODULE.ROOT / ".solver-anchor-test-review.json"
    job_path = MODULE.ROOT / ".solver-anchor-test-job.json"
    review = MODULE.build_review()
    try:
        MODULE.write_json(review_path, review)
        checked = MODULE.verify_review(review_path)
        job = MODULE.build_job(checked, review_path)
        MODULE.write_json(job_path, job)
        original_review_output = MODULE.REVIEW_OUTPUT
        MODULE.REVIEW_OUTPUT = review_path
        try:
            loaded = MODULE.verify_job(job_path)
        finally:
            MODULE.REVIEW_OUTPUT = original_review_output
        assert loaded["qualification_claim"] == "none"
        assert loaded["matrix_credit"] == 0
        assert loaded["execution_policy"]["submit_allowed"] is False
        assert loaded["anchor_output"]["logical_stem_only"] is True
        assert loaded["runtime_worker"]["runtime_enabled"] is True
    finally:
        review_path.unlink(missing_ok=True)
        job_path.unlink(missing_ok=True)


def test_no_queue_or_scientific_mutation_is_authorized():
    review = MODULE.build_review()
    assert review["review_decision"]["authorized_solver"] is True
    assert review["review_decision"]["authorized_gpu"] is True
    assert review["review_decision"]["authorized_queue"] is True
    assert review["execution_controls"]["queue_mutation"] == 0
    assert review["matrix_credit"] == 0
