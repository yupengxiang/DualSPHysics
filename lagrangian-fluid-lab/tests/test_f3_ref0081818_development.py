import pytest

from scripts import f3_ref0081818_development as development


def test_missing_ref008_gate_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(development, "OUT", tmp_path)
    with pytest.raises(ValueError, match="missing required record"):
        development.verify_revision_gate()


def test_dry_run_never_checks_budget_or_calls_shared_solver(monkeypatch):
    calls = []
    monkeypatch.setattr(development, "candidate", lambda case_id: {"case_id": case_id, "pilot": True})
    monkeypatch.setattr(
        development,
        "_context",
        lambda register: {"source": {"record": {"id": "F3_REF008_SOURCE"}}},
    )
    monkeypatch.setattr(development, "check_budget", lambda **_: calls.append("budget"))
    monkeypatch.setattr("scripts.l1r_branch_runner.run", lambda *_: calls.append("solver"))
    result = development.run("F3_DEV_00_a0p903125", dry_run=True)
    assert result["status"] == "dry_run"
    assert result["solver_attempts"] == 0
    assert calls == []


def test_development_fields_bind_ref008_recipe_and_production_resolution(monkeypatch, tmp_path):
    source = {
        "id": "F3_REF008_SOURCE",
        "generated_prefix": "campaigns/l1-resume/artifacts/f3-ref0081818/F3_CELL3_plain_0p008181818",
        "gencase": {"total_particles": 1, "fluid_particles": 1, "boundary_particles": 0},
    }
    context = {"source": {"record": source, "prefix": tmp_path / "F3_CELL3_plain_0p008181818"}}
    row = {
        "case_id": "F3_DEV_00_a0p903125", "drive_amplitude": .903125,
        "control_path": "campaigns/l1-resume/data/f3-development-inputs/F3_DEV_00_a0p903125.csv",
        "control_file_sha256": "a" * 64, "effective_control_sha256": "b" * 64,
        "physical_lineage_sha256": "c" * 64, "index": 0,
        "split": "test", "evaluation_role": "development_extrapolation", "pilot": True,
    }
    monkeypatch.setattr(development.q2, "sha256", lambda _: "test-digest")
    result = development._fields(row, context, development.LAB / "campaigns/l1-resume/artifacts/test-case")
    assert result["recipe_id"] == development.REVISION_RECIPE
    assert result["resource_category"] == "development"
    assert result["dp_m"] == .0075
    assert result["source_revision_gate_sha256"]
