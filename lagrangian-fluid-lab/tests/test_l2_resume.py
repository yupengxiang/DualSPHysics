from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import l2_campaign
from scripts import l2_resume
from scripts import l2_d0_e0_closeout
from scripts.l2_d0_e0_closeout import load_qualified_receipts


def _receipt(*, expected_source_hash: str | None = None) -> dict:
    receipt = {
        "receipt_id": "fixture-f3-control",
        "status": "accepted",
        "verdict": "qualified_t1",
        "scope": {"family": "F3", "subdomain": "offaxis_control"},
        "recipe_id": "fixture-recipe-v1",
        "case_ids": ["fixture-case-1", "fixture-case-2"],
        "evidence": {
            "source_hashes": ["source-hash-a"],
            "split_check": {"passed": True},
            "input_check": {"passed": True},
            "spatiotemporal_metrics": {"position_rmse": 0.01, "event_time_error": 0.02},
        },
    }
    if expected_source_hash is not None:
        receipt["expected_source_hash"] = expected_source_hash
    return receipt


def test_recipe_registry_accepts_scoped_receipt_and_rejects_changed_source_hash(tmp_path: Path):
    registry = tmp_path / "recipe-registry.json"
    registry.write_text(json.dumps({"receipts": [_receipt(), _receipt(expected_source_hash="changed")]}, indent=2))

    accepted, rejected = load_qualified_receipts(registry)

    assert len(accepted) == 1
    assert accepted[0]["scope"]["family"] == "F3"
    assert rejected == [{"receipt_id": "fixture-f3-control", "reason": "source_hash_mismatch"}]

    canary = _receipt()
    canary["canary"] = True
    registry.write_text(json.dumps({"receipts": [canary]}))
    accepted, rejected = load_qualified_receipts(registry)
    assert accepted == []
    assert rejected == [{"receipt_id": "fixture-f3-control", "reason": "canary_not_qualification"}]


def test_resume_ready_requires_terminal_dependencies_and_real_artifacts(monkeypatch, tmp_path: Path):
    resume_root = tmp_path / "resume"
    monkeypatch.setattr(l2_resume, "RESUME_ROOT", resume_root)
    state = {
        "tasks": [
            {"task_id": "R0", "status": "blocked", "requires": [], "artifacts": []},
            {"task_id": "R1", "status": "pending", "requires": ["R0"], "artifacts": []},
        ]
    }
    l2_resume._refresh_ready(state)
    assert state["tasks"][1]["status"] == "pending"

    state["tasks"][0]["status"] = "complete_with_findings"
    state["tasks"][0]["artifacts"] = ["r0.json"]
    l2_resume._refresh_ready(state)
    assert state["tasks"][1]["status"] == "pending"
    assert l2_resume.terminal_predicate(state)["can_finalize"] is False
    assert "R0" in l2_resume.terminal_predicate(state)["missing_artifacts"]

    (resume_root / "r0.json").parent.mkdir(parents=True, exist_ok=True)
    (resume_root / "r0.json").write_text("{}\n")
    l2_resume._refresh_ready(state)
    assert state["tasks"][1]["status"] == "ready"
    assert l2_resume.terminal_predicate(state)["all_terminal_artifacts_present"] is True


def test_complete_with_findings_and_blocked_external_have_distinct_contracts(monkeypatch, tmp_path: Path):
    resume_root = tmp_path / "resume"
    monkeypatch.setattr(l2_resume, "RESUME_ROOT", resume_root)

    invalid = {
        "tasks": [{"task_id": "X", "status": "blocked_external", "requires": [], "blocker": {"id": "only-id"}}]
    }
    result = l2_resume.terminal_predicate(invalid)
    assert result["can_finalize"] is False
    assert result["invalid_external_blocks"] == ["X"]

    valid = {
        "tasks": [{
            "task_id": "X",
            "status": "blocked_external",
            "requires": [],
            "blocker": {
                "id": "external-anchor",
                "requirement": "matched physical anchor",
                "evidence": {"source": "owner-supplied evidence"},
                "release_conditions": ["anchor is supplied and audited"],
            },
        }]
    }
    result = l2_resume.terminal_predicate(valid)
    assert result["can_finalize"] is True
    assert result["terminal_evidence_contract_valid"] is True

    complete_without_artifacts = {
        "tasks": [{"task_id": "X", "status": "complete_with_findings", "requires": [], "artifacts": []}]
    }
    result = l2_resume.terminal_predicate(complete_without_artifacts)
    assert result["can_finalize"] is False
    assert result["invalid_terminal_evidence"]["X"] == "complete_status_requires_artifacts"


def test_b2r_preparation_without_new_training_cannot_be_terminal(monkeypatch, tmp_path: Path):
    resume_root = tmp_path / "resume"
    monkeypatch.setattr(l2_resume, "RESUME_ROOT", resume_root)
    preparation = resume_root / "b2r-study.json"
    preparation.parent.mkdir(parents=True)
    preparation.write_text(json.dumps({
        "schema": "l2r.b2r.preparation_contract.v1",
        "acceptance": {"new_training_attempts_executed": False},
    }))
    state = {
        "tasks": [{
            "task_id": "B2R",
            "status": "complete_with_findings",
            "requires": [],
            "artifacts": ["b2r-study.json"],
        }]
    }

    result = l2_resume.terminal_predicate(state)
    assert result["can_finalize"] is False
    assert result["invalid_terminal_evidence"]["B2R"] == "B2R_requires_a_new_training_attempt_record"

    attempt = resume_root / "attempt.json"
    attempt.write_text(json.dumps({
        "schema": "l2r.b2r.training_attempt.v1",
        "execution_attempt_id": "attempt-1",
        "status": "failed",
    }))
    state["tasks"][0]["artifacts"].append("attempt.json")
    result = l2_resume.terminal_predicate(state)
    assert result["can_finalize"] is True


def test_recipe_registry_is_resolved_at_call_time_and_missing_is_not_success(
    monkeypatch, tmp_path: Path,
):
    registry = tmp_path / "dynamic-registry.json"
    monkeypatch.setattr(l2_d0_e0_closeout, "RECIPE_REGISTRY", registry)
    accepted, rejected = load_qualified_receipts()
    assert accepted == []
    assert rejected == [{"reason": "registry_missing", "path": str(registry.resolve())}]

    registry.write_text(json.dumps({"receipts": [_receipt()]}))
    accepted, rejected = load_qualified_receipts()
    assert len(accepted) == 1
    assert rejected == []


def test_d0_does_not_admit_batch_after_canary_failure(monkeypatch, tmp_path: Path):
    campaign = tmp_path / "campaign"
    reports = campaign / "reports"
    monkeypatch.setattr(l2_campaign, "CAMPAIGN", campaign)
    monkeypatch.setattr(l2_d0_e0_closeout, "CAMPAIGN", campaign)
    monkeypatch.setattr(l2_d0_e0_closeout, "REPORT_ROOT", reports)
    registry = campaign / "resume" / "recipe-registry.json"
    monkeypatch.setattr(l2_d0_e0_closeout, "RECIPE_REGISTRY", registry)

    l2_campaign.atomic_json(campaign / "state.json", {
        "owner_adoption_status": "accepted",
        "baseline_commit": "fixture",
        "stages": {"A0": {"status": "complete_with_findings"}},
    })
    for name, payload in {
        "c0-family-hypotheses.json": {"acceptance": {
            "priority_reference_cells_are_2x3": True,
            "legacy_assets_not_reclassified": True,
        }},
        "c1-canary.json": {"audits": [{"family": "F1", "canary_hard_integrity_pass": False}]},
        "c2-f3-canary.json": {"canary_pass": True},
        "c3-bounded-anchors.json": {"audits": []},
        "b2-learning-baseline.json": {"acceptance": {"causal_input_contract_checked": True}},
    }.items():
        l2_campaign.atomic_json(reports / name, payload)
    l2_campaign.atomic_json(campaign / "evidence" / "f3-canonical-manifest.json", {"cases": []})
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"receipts": [_receipt()]}))

    report = l2_d0_e0_closeout.d0()

    assert report["runtime_gate"]["new_qualified_t1_recipe_count"] == 1
    assert report["runtime_gate"]["canary_gate_pass"] is False
    assert report["production_batch"]["status"] == "not_ready"
    assert report["decision"] == "blocked_canary_failure"

    legacy = _receipt()
    legacy["recipe_id"] = "legacy-recipe"
    registry.write_text(json.dumps({"receipts": [legacy]}))
    l2_campaign.atomic_json(
        campaign / "evidence" / "f3-canonical-manifest.json",
        {"cases": [{"recipe_id": "legacy-recipe"}]},
    )
    report = l2_d0_e0_closeout.d0()
    assert report["runtime_gate"]["new_qualified_t1_recipe_count"] == 0
    assert any(item["reason"] == "legacy_recipe_not_new" for item in report["runtime_gate"]["rejected_receipts"])


def test_e0_report_failure_does_not_leave_a_terminal_placeholder(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}\n")
    report_path = tmp_path / "e0-r-checkpoint.json"
    markdown_path = tmp_path / "e0-r-checkpoint.md"
    monkeypatch.setattr(l2_d0_e0_closeout, "RESUME_STATE", state_path)
    monkeypatch.setattr(l2_d0_e0_closeout, "E0R_REPORT", report_path)
    monkeypatch.setattr(l2_d0_e0_closeout, "E0R_MARKDOWN", markdown_path)
    monkeypatch.setattr(l2_d0_e0_closeout, "RESUME_ROOT", tmp_path)
    monkeypatch.setattr(l2_d0_e0_closeout, "load_resume_state", lambda: {
        "tasks": [{"task_id": "E0R", "status": "ready"}],
    })
    marked: list[tuple] = []
    monkeypatch.setattr(l2_d0_e0_closeout, "mark_task", lambda *args, **kwargs: marked.append((args, kwargs)))

    def fail_report():
        raise RuntimeError("fixture report failure")

    monkeypatch.setattr(l2_d0_e0_closeout, "e0", fail_report)

    with pytest.raises(RuntimeError, match="fixture report failure"):
        l2_d0_e0_closeout.run_e0()

    assert marked == []
    assert not report_path.exists()
    assert not markdown_path.exists()
