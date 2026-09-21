import json
from pathlib import Path

from scripts.f2_receiver_overflow_negative_evidence_v1 import collect


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"
ATTEMPT = LAB / "campaigns/core-v1/runtime/attempts/f2-receiver-overflow-weir-q05-dp0075-anchor-002/20260920T233516-a2d286da6be4"
ROOT_REVIEW = BASE / "root-review-one-anchor-v2.json"
JOB = BASE / "anchor-job-v2.json"


def test_terminal_negative_evidence_preserves_anchor_failure_and_zero_credit(tmp_path):
    matrix_path = tmp_path / "terminal-matrix.json"
    denominator_path = tmp_path / "terminal-denominator.json"
    evidence_path = tmp_path / "negative-evidence.json"
    evidence = collect(
        ATTEMPT,
        base=BASE,
        root_review=ROOT_REVIEW,
        job=JOB,
        matrix_output=matrix_path,
        denominator_output=denominator_path,
        evidence_output=evidence_path,
    )
    matrix = json.loads(matrix_path.read_text())
    denominator = json.loads(denominator_path.read_text())
    assert evidence["status"] == "completed_scientific_negative_anchor"
    assert evidence["scientific_failure_class"] == "hard_integrity_failure_with_event_censoring"
    assert evidence["qualification_claim"] == "none"
    assert evidence["matrix_credit"] == 0
    assert evidence["hard_integrity"]["pass"] is False
    assert evidence["hard_integrity"]["requested_horizon_reached"] is True
    assert evidence["event_window"]["complete"] is False
    assert matrix["denominator"] == {
        "planned": 15,
        "executed": 1,
        "passed": 0,
        "failed": 1,
        "event_censored": 1,
        "unattempted": 14,
        "credit": 0,
        "categories_may_overlap": True,
    }
    assert matrix["rows"][4]["status"] == "failed_hard_integrity_and_event_censored"
    assert all(row["status"] == "not_started" for row in matrix["rows"] if row["index"] != 4)
    assert denominator["preservation"]["same_input_retry"] is False
    assert denominator["preservation"]["infrastructure_retry"] is True
    assert denominator["preservation"]["all_rows_retained"] is True
