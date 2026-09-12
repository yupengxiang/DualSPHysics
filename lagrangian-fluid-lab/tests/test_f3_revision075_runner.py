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

    monkeypatch.setattr(runner.launch_gate, "verify_authorization",
                        lambda: (_ for _ in ()).throw(PermissionError("owner authorization required")))
    monkeypatch.setattr("scripts.l1r_branch_runner.run", forbidden, raising=False)
    with pytest.raises(PermissionError):
        runner.run_one("R075-ZERO")
    assert called == []


def test_run_accepts_gpu_selected_in_persisted_solver_evidence(monkeypatch, tmp_path):
    record = runner._records()[0]
    monkeypatch.setattr(runner, "_records", lambda: [record])
    monkeypatch.setattr(runner.launch_gate, "verify_authorization",
                        lambda: {"authorization": {"recipe_id": runner.launch_gate.RECIPE}})
    monkeypatch.setattr(runner, "check_input", lambda _: None)
    monkeypatch.setattr(runner, "LAB", tmp_path)
    attempts = tmp_path / "campaigns/l1-resume/runs/branches" / record["id"] / "attempts"
    attempts.mkdir(parents=True)
    solver_path = tmp_path / "campaigns/l1-resume/continuation" / f"{record['id']}-SOLVER.json"
    solver_path.parent.mkdir(parents=True)
    solver_path.write_text(json.dumps({"resource_preflight": {"selected_gpu_index": 4}}))
    monkeypatch.setattr("scripts.l1r_branch_runner.run", lambda _: {"audit_status": "pass_diagnostic"})
    result = runner.run_one(record["plan_case_id"])
    assert result["case_id"] == record["id"]
