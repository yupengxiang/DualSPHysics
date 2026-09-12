import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import campaign_runner as executor
from scripts import l1r_branch_runner as runner
from scripts import l1r_continuation_evidence as evidence
from scripts import l1r_input_preflight as input_preflight


LIMITS = {
    "qualification": 72,
    "development": 40,
    "gpu_hours": 64,
    "cpu_core_hours": 768,
    "materials": 32,
    "storage_gib": 512,
}


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    out = tmp_path / "campaigns/l1-resume/continuation"
    out.mkdir(parents=True)
    monkeypatch.setattr(evidence, "LAB", tmp_path)
    monkeypatch.setattr(evidence, "OUT", out)
    monkeypatch.setattr(runner, "LAB", tmp_path)
    monkeypatch.setattr(runner, "OUT", out)
    (out / "RESOURCE-LIMITS.json").write_text(json.dumps({"limits": LIMITS}))
    (out / "HISTORICAL-CPU-RESERVE.json").write_text(
        json.dumps({"cpu_core_hours_conservative_reserve": 1.0})
    )
    (out / "RESOURCE-ACTIVE-WINDOWS.json").write_text("[]")
    return tmp_path, out


@pytest.mark.parametrize("category", [None, "development"])
@pytest.mark.parametrize("returncode", [0, 1])
def test_attempt_records_category_before_execution_and_after_terminal_status(
    tmp_path, monkeypatch, category, returncode
):
    observed = []

    def fake_run(command, **kwargs):
        partial = Path(command[-1])
        observed.append(json.loads((partial / "attempt.json").read_text()))
        (partial / "data").mkdir()
        (partial / "data/Part_0000.bi4").write_bytes(b"test fixture")
        return SimpleNamespace(returncode=returncode, stdout="Finished")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    kwargs = {} if category is None else {"resource_category": category}
    result = executor.execute_attempt(
        "case", ["mock-solver", "{output}"], tmp_path,
        required_text="Finished", **kwargs
    )
    expected = category or "qualification"
    assert observed[0]["status"] == "running"
    assert observed[0]["resource_category"] == expected
    final = json.loads((Path(result["attempt_directory"]) / "attempt.json").read_text())
    assert final["resource_category"] == result["resource_category"] == expected
    assert final["status"] == ("failed" if returncode else "completed")


def test_invalid_category_is_rejected_before_creating_an_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        executor.subprocess, "run", lambda *a, **k: pytest.fail("must not launch")
    )
    with pytest.raises(ValueError, match="resource category"):
        executor.execute_attempt(
            "case", ["mock-solver"], tmp_path / "runs", resource_category="training"
        )
    assert not (tmp_path / "runs").exists()


def test_ledger_separates_attempt_pools_without_reclassifying_history(campaign):
    lab, out = campaign
    specs = [
        ("historical", None, "completed", 3600, True),
        ("explicit-qualification", "qualification", "completed", 1800, False),
        ("development-completed", "development", "completed", 7200, True),
        ("development-failed", "development", "failed", 900, True),
        ("development-running", "development", "running", None, True),
    ]
    originals = {}
    for name, category, status, elapsed, gpu in specs:
        path = lab / "campaigns/l1-resume/runs" / name / "attempts/one/attempt.json"
        path.parent.mkdir(parents=True)
        row = {"case_id": name, "attempt_id": name, "status": status,
               "elapsed_seconds": elapsed, "command": ["solver", "-gpu:4" if gpu else "-cpu"]}
        if category is not None:
            row["resource_category"] = category
        if status == "running":
            row["timeout_seconds"] = 1800
        path.write_text(json.dumps(row))
        originals[path] = path.read_bytes()
    supplement = lab / "diagnostics/f3-audit/direct-attempt-reconciliation.json"
    supplement.parent.mkdir(parents=True)
    supplement.write_text(json.dumps({"additional_attempts": [{
        "id": "historic-direct", "status": "failed", "elapsed_seconds": 900,
        "resource_category": "development",
    }]}))
    originals[supplement] = supplement.read_bytes()

    evidence.ledger()
    report = json.loads((out / "RESOURCE-LEDGER.json").read_text())
    assert report["qualification_attempts_used"] == 3
    assert report["qualification_attempts_remaining"] == 69
    assert report["development_attempts_used"] == 3
    assert report["development_attempts_remaining"] == 37
    assert report["gpu_solver_hours"] == 3.5
    assert report["gpu_budget_charge_hours"] == 4.0
    assert report["cpu_core_hours_upper_bound"] == 1.0
    by_id = {row["attempt_id"]: row for row in report["attempts"]}
    assert by_id["historical"]["resource_category"] == "qualification"
    assert by_id["historic-direct"]["resource_category"] == "qualification"
    assert by_id["development-running"]["elapsed_seconds"] is None
    assert by_id["development-running"]["budget_reserve_seconds"] == 1800
    assert all(path.read_bytes() == before for path, before in originals.items())


def test_unknown_explicit_category_does_not_disappear_from_accounting(campaign):
    lab, out = campaign
    path = lab / "campaigns/l1-resume/runs/one/attempt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"resource_category": "unbudgeted"}))
    with pytest.raises(ValueError, match="resource category"):
        evidence.ledger()
    assert not (out / "RESOURCE-LEDGER.json").exists()


def budget(qualification=0, development=40):
    return {
        "qualification_attempts_remaining": qualification,
        "development_attempts_remaining": development,
        "gpu_budget_charge_hours": 0.0,
        "gpu_solver_hours": 0.0,
        "cpu_core_hours_upper_bound": 1.0,
        "limits": LIMITS,
        "conservative_expiry_utc": "2099-01-01T00:00:00+00:00",
    }


@pytest.mark.parametrize("category", ["qualification", "development"])
def test_budget_checks_requested_pool_and_preserves_common_caps(campaign, monkeypatch, category):
    _, out = campaign
    monkeypatch.setattr(evidence, "ledger", lambda: None)
    monkeypatch.setattr(
        "shutil.disk_usage", lambda _: SimpleNamespace(total=2 * 1024**4, free=1024**4)
    )
    report = budget(qualification=int(category == "qualification"),
                    development=int(category == "development"))
    path = out / "RESOURCE-LEDGER.json"
    path.write_text(json.dumps(report))
    # The default remains qualification even when development has room.
    call = (lambda: evidence.check_budget()) if category == "qualification" else (
        lambda: evidence.check_budget(category="development")
    )
    assert call()[f"{category}_attempts_remaining"] == 1
    preflight = json.loads((out / "RESOURCE-PREFLIGHT.json").read_text())
    assert preflight["resource_category"] == category
    for key, limit in ((f"{category}_attempts_remaining", 0),
                       ("gpu_budget_charge_hours", 64), ("cpu_core_hours_upper_bound", 768)):
        exhausted = {**report, key: limit}
        path.write_text(json.dumps(exhausted))
        with pytest.raises(RuntimeError, match="parent resource budget exhausted"):
            call()


@pytest.fixture
def development_record(campaign):
    _, out = campaign
    row = {
        "case_id": "F3_DEV_00_a0p903125", "drive_amplitude": 0.9031250000000001,
        "control_file_sha256": "a" * 64, "physical_lineage_sha256": "b" * 64,
    }
    (out / "F3-DEVELOPMENT-CANDIDATES.json").write_text(json.dumps({"cases": [row]}))
    return {
        "id": row["case_id"], "case_id": row["case_id"], "family": "F3",
        "drive_amplitude": row["drive_amplitude"], "drive_sha256": row["control_file_sha256"],
        "physical_lineage_sha256": row["physical_lineage_sha256"],
        "resource_category": "development", "generated_prefix": "inputs/case",
        "gencase": {"total_particles": 57060}, "solver_mode": "-mdbc_noslip:1",
    }


def test_development_category_matches_registered_physical_case(development_record):
    assert runner.check_record_resource_category(development_record) == "development"
    assert runner.check_record_resource_category({"id": "historical"}) == "qualification"


@pytest.mark.parametrize("changes", [
    {"id": "old-qualification", "case_id": "old-qualification"},
    {"id": "different-from-case-id"},
    {"family": "F1"},
    {"drive_amplitude": 1.0},
    {"drive_amplitude": 0.903125},
    {"drive_sha256": "c" * 64},
    {"physical_lineage_sha256": "c" * 64},
    {"drive_sha256": None},
])
def test_relabelled_or_mismatched_development_is_rejected_before_activity(
    development_record, monkeypatch, changes
):
    monkeypatch.setattr(
        evidence, "begin_activity_window", lambda: pytest.fail("must reject before activity writes")
    )
    with pytest.raises(ValueError, match="development"):
        runner.run({**development_record, **changes})


@pytest.mark.parametrize("category", ["qualification", "development"])
def test_runner_passes_category_to_budget_and_attempt_without_using_other_pool(
    campaign, development_record, monkeypatch, category
):
    record = dict(development_record)
    if category == "qualification":
        record.pop("resource_category")
        record.update(id="qualification-canary", case_id="qualification-canary")
    calls = []

    def check_budget(category="qualification"):
        calls.append(("budget", category))
        return budget(qualification=int(category == "qualification"),
                      development=int(category == "development"))

    def execute(*args, **kwargs):
        calls.append(("attempt", kwargs["resource_category"]))
        return {"status": "failed", "resource_category": kwargs["resource_category"]}

    monkeypatch.setattr(evidence, "begin_activity_window", lambda: None)
    monkeypatch.setattr(evidence, "check_budget", check_budget)
    monkeypatch.setattr(input_preflight, "check_input", lambda _: None)
    monkeypatch.setattr(runner, "resource_limits", lambda: LIMITS)
    monkeypatch.setattr(runner, "ledger", lambda: None)
    monkeypatch.setattr(runner, "write", lambda *a: None)
    monkeypatch.setattr(runner.q2, "atomic_json", lambda *a: None)
    monkeypatch.setattr(runner.q2, "sha256", lambda _: "test-digest")
    monkeypatch.setattr(runner.q2, "choose_gpu", lambda _: (4, {"snapshot": []}))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    monkeypatch.setattr(
        runner.shutil, "disk_usage", lambda _: SimpleNamespace(total=2 * 1024**4, free=1024**4)
    )
    monkeypatch.setattr(runner, "execute_attempt", execute)
    result = runner.run(record)
    assert result["resource_category"] == category
    assert calls == [("budget", category), ("attempt", category)]


def test_existing_untagged_attempt_cannot_be_reused_as_development(
    campaign, development_record, monkeypatch
):
    lab, _ = campaign
    latest = lab / "campaigns/l1-resume/runs/branches" / development_record["id"] / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps({"status": "completed"}))
    monkeypatch.setattr(evidence, "begin_activity_window", lambda: None)
    monkeypatch.setattr(input_preflight, "check_input", lambda _: None)
    monkeypatch.setattr(runner, "process", lambda *a: pytest.fail("must not reuse under a new category"))
    with pytest.raises(ValueError, match="historical attempts cannot be relabelled"):
        runner.run(development_record)
