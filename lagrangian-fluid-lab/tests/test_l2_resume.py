from __future__ import annotations

import json
from pathlib import Path

from scripts import l2_resume
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
    assert state["tasks"][1]["status"] == "ready"
    assert l2_resume.terminal_predicate(state)["can_finalize"] is False
    assert "R0" in l2_resume.terminal_predicate(state)["missing_artifacts"]

    (resume_root / "r0.json").parent.mkdir(parents=True, exist_ok=True)
    (resume_root / "r0.json").write_text("{}\n")
    assert l2_resume.terminal_predicate(state)["all_terminal_artifacts_present"] is True
