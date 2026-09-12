import pytest

from scripts import f3_revision075_development as development


def test_missing_revision_gate_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(development, "OUT", tmp_path)
    with pytest.raises(ValueError, match="missing required record"):
        development.verify_revision_gate()


def test_gpu_contract_rejects_selector_drift(monkeypatch):
    monkeypatch.setattr(development.q2, "GPU_IDS", (0, 4, 5, 6))
    with pytest.raises(RuntimeError, match="4-7"):
        development.verify_gpu_contract()


def test_dry_run_never_checks_budget_or_calls_shared_solver(monkeypatch):
    calls = []
    monkeypatch.setattr(development, "candidate", lambda case_id: {"case_id": case_id, "pilot": True})
    monkeypatch.setattr(
        development,
        "_context",
        lambda register: {"source": {"record": {"id": "F3_REV075_SOURCE"}}},
    )
    monkeypatch.setattr(development, "check_budget", lambda **_: calls.append("budget"))
    monkeypatch.setattr(
        "scripts.l1r_branch_runner.run",
        lambda *_: calls.append("solver"),
    )
    result = development.run("F3_DEV_00_a0p903125", dry_run=True)
    assert result["status"] == "dry_run"
    assert result["solver_attempts"] == 0
    assert result["gpu_indices"] == [4, 5, 6, 7]
    assert result["protected_gpu_indices"] == [0, 1, 2, 3]
    assert calls == []


def test_real_run_checks_gate_before_budget_or_solver(monkeypatch):
    calls = []
    monkeypatch.setattr(development, "candidate", lambda case_id: {"case_id": case_id, "pilot": True})

    def blocked(*, register):
        calls.append(("context", register))
        raise ValueError("revision gate blocked")

    monkeypatch.setattr(development, "_context", blocked)
    monkeypatch.setattr(development, "check_budget", lambda **_: calls.append("budget"))
    with pytest.raises(ValueError, match="revision gate blocked"):
        development.run("F3_DEV_00_a0p903125")
    assert calls == [("context", False)]


def test_revision_record_fields_are_development_bound(monkeypatch, tmp_path):
    source = {
        "id": "F3_REV075_SOURCE",
        "generated_prefix": "campaigns/l1-resume/artifacts/f3-revision075/F3_REV075_SOURCE/F3_CELL3_plain_0p0075",
        "gencase": {"total_particles": 1, "fluid_particles": 1, "boundary_particles": 0},
    }
    context = {"source": {"record": source, "prefix": tmp_path / "F3_CELL3_plain_0p0075"}}
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
    assert result["solver_timeout_seconds"] == 3600
    assert result["source_revision_gate_sha256"]
