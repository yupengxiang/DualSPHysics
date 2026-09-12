import json

import pytest

from scripts import f3_revision075_runner as runner


def test_describe_is_read_only_and_lists_all_cells():
    rows = runner.describe()
    assert len(rows) == 11
    assert {row["plan_case_id"] for row in rows} == {
        "R075-ZERO", "R075-TIME", "R075-OUTPUT",
        "R075-ENDPOINT-LOW-010", "R075-ENDPOINT-LOW-0075", "R075-ENDPOINT-LOW-006",
        "R075-ENDPOINT-HIGH-010", "R075-ENDPOINT-HIGH-0075", "R075-ENDPOINT-HIGH-006",
        "R075-INTERNAL-0075", "R075-INTERNAL-006",
    }


def test_preflight_never_authorizes_launch():
    result = runner.preflight("R075-ZERO")
    assert result == {
        "status": "preflight_passed", "plan_case_id": "R075-ZERO",
        "case_id": "F3_REV075_R075-ZERO", "launch_allowed": False,
        "solver_invocations": 0,
    }


def test_run_requires_owner_authorization_before_shared_runner(monkeypatch):
    called = []

    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("shared solver runner must not be reached")

    monkeypatch.setattr("scripts.l1r_branch_runner.run", forbidden, raising=False)
    with pytest.raises((PermissionError, ValueError)):
        runner.run_one("R075-ZERO")
    assert called == []
