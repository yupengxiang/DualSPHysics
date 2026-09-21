"""Checks for the non-started eight-cell F6 v4 solver-canary plan."""

from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-v4-20260921"
PLAN = ROOT / "plan.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plan_selects_eight_unique_cells_without_starting_execution() -> None:
    value = load(PLAN)
    assert value["status"] == "root_review_authorized_not_started"
    assert value["selected_indices"] == [0, 4, 5, 8, 9, 12, 13, 14]
    assert value["selected_count"] == 8
    assert len(value["jobs"]) == 8
    assert len({item["index"] for item in value["jobs"]}) == 8
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["T1"] is False
    assert value["queue_submission"] is False
    assert value["gpu_started"] is False
    assert value["registry_mutation"] == 0
    assert value["ledger_mutation"] == 0
    assert value["matrix_submission"] is False


def test_each_authorized_job_is_exact_one_and_closed_to_retry_or_mutation() -> None:
    value = load(PLAN)
    for item in value["jobs"]:
        job = load(LAB / item["job"]["path"])
        review = load(LAB / item["review"]["path"])
        assert job["job_status"] == "root_authorized_not_started"
        assert job["attempt"] == 1
        assert job["qualification_only"] is True
        assert job["qualification_claim"] == "none"
        assert job["qualification_credit"] == 0
        assert job["T1"] is False
        assert job["execution_policy"]["exactly_one_solver_attempt"] is True
        assert job["execution_policy"]["same_input_retry"] is False
        assert job["execution_policy"]["resume"] is False
        assert job["execution_policy"]["queue_submission"] is False
        assert job["execution_policy"]["registry_mutation"] is False
        assert job["execution_policy"]["ledger_mutation"] is False
        assert job["execution_policy"]["matrix_submission"] is False
        assert review["decision"]["authorized_cpu_solver"] is True
        assert review["decision"]["authorized_gpu"] is False
        assert review["decision"]["authorized_queue"] is False
        assert review["decision"]["exactly_one_solver_attempt"] is True
        assert review["qualification_claim"] == "none"
        assert review["qualification_credit"] == 0
