"""Tests for the versioned, non-authorizing F3/F4 release candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

import scripts.core_formal_release_candidate as release_candidate


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
CLOSURE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/source-closure.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_campaign_registry_reader_rejects_duplicate_keys_and_symlinks(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate-registry.json"
    duplicate.write_bytes(b'{"schema":"first","schema":"second"}')
    observation = release_candidate._campaign_completion_observation(
        root=tmp_path, registry=duplicate)
    assert observation["valid"] is False
    assert "duplicate JSON object key" in observation["error"]

    symlink = tmp_path / "registry-link.json"
    symlink.symlink_to(ROOT / "campaigns/core-v1/registry.json")
    observation = release_candidate._campaign_completion_observation(
        root=tmp_path, registry=symlink)
    assert observation["valid"] is False
    assert "symlink is forbidden" in observation["error"]


def test_candidate_binds_current_closure_and_keeps_formal_gate_closed() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    assert candidate["schema"] == "core.formal_release_candidate.v1"
    assert candidate["candidate_version"] == "core-formal-release-candidate-v4"
    assert candidate["status"] == "blocked"
    assert candidate["data_contract_ready"] is True
    assert candidate["formal_training_ready"] is False
    assert candidate["formal_release"] is False
    assert candidate["formal_job_count"] == 0
    assert candidate["diagnostic_runs_counted_as_formal"] is False
    assert candidate["blocker_codes"] == [
        "STALE_SOURCE_CLOSURE", "FORMAL_RELEASE_REQUIRED", "THIRD_FAMILY_REQUIRED",
        "VALIDATION_DENOMINATOR", "RESOURCE_FRONTIER_UNPROVEN",
    ]
    assert candidate["admission_observation"]["production_denominator"]["included_case_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["hard_integrity_pass_bound_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["structural_pass_bound_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["failure_denominator_preserved"] is True
    assert candidate["admission_observation"]["graph_probe"]["valid"] is True
    assert candidate["admission_observation"]["graph_probe"]["formal_capacity_evidence"] is False
    assert closure["complete"] is True
    assert candidate["source_closure"]["sha256"] == _sha256(CLOSURE)
    assert candidate["source_closure"]["closure_sha256"] == closure["closure_sha256"]


def _ready_audit(closure_sha256: str) -> dict:
    closure = release_candidate.materialize_source_closure(root=ROOT, code_root=ROOT)
    return {
        "schema": release_candidate.ADMISSION_SCHEMA,
        "record_id": "test-ready-admission",
        "status": "ready",
        "formal_admission": True,
        "formal_job_count": 0,
        "required_formal_job_count": 9,
        "blockers": [],
        "manifests": [],
        "evidence": [],
        "family_summary": {"families": ["F1", "F2", "F3"]},
        "production_denominator": {"failure_denominator_preserved": True},
        "source_closure": {
            "fresh_admission_closure_complete": True,
            "missing_files": [],
            "current_closure_sha256": closure_sha256,
            "required_files": list(release_candidate.REQUIRED_CODE_FILES),
            "current_files": closure["files"],
        },
        "resource_profile": {},
        "resource_dryrun": {},
        "graph_probe": {},
        "execution_constraints": {
            "read_only": True,
            "formal_runs_started": 0,
            "gpu_started": False,
            "solver_started": False,
            "submitted": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "manifest_written": False,
            "formal_specs_written": False,
        },
        "admission_next_dependency": None,
    }


def _candidate_inputs(tmp_path: Path, closure_sha256: str = "closure") -> dict:
    return {
        "manifests": [],
        "evidence": [],
        "root": ROOT,
        "code_root": ROOT,
        "preprofile_index": None,
        "resource_profile": None,
        "resource_dryrun": None,
        "graph_probe": None,
        "source_closure": release_candidate.materialize_source_closure(
            root=ROOT, code_root=ROOT,
        ),
        "registry": {},
    }


def _complete_campaign() -> dict:
    checks = {name: True for name in release_candidate.CAMPAIGN_CHECKS}
    return {
        "schema": "core.completion.v1",
        "can_finalize": True,
        "checks": checks,
        "t1_families": ["F1", "F2", "F3"],
        "macro_t2_families": ["F1", "F2"],
        "training_runs": [f"run-{index}" for index in range(9)],
        "expected_training_runs": [f"run-{index}" for index in range(9)],
        "missing_training_runs": [],
        **{field: 0 for field in release_candidate.CAMPAIGN_COMPLETION_INTEGER_FIELDS},
        "issues": [],
    }


def test_ready_admission_cannot_promote_an_incomplete_closure(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        release_candidate,
        "audit_admission",
        lambda *args, **kwargs: _ready_audit(
            release_candidate.materialize_source_closure(root=ROOT, code_root=ROOT)[
                "closure_sha256"
            ]
        ),
    )
    monkeypatch.setattr(
        release_candidate,
        "campaign_completion",
        lambda payload, root: {
            "schema": "core.completion.v1",
            "can_finalize": True,
            "checks": {"all": True},
        },
    )
    inputs = _candidate_inputs(tmp_path)
    inputs["source_closure"] = {
        "complete": False,
        "missing_files": ["scripts/core_learning.py"],
        "closure_sha256": "closure",
    }

    candidate = release_candidate.build_candidate(**inputs)

    assert candidate["status"] == "blocked"
    assert candidate["formal_training_ready"] is False
    assert candidate["formal_release"] is False
    assert "SOURCE_CLOSURE_BINDING_GAP" in candidate["blocker_codes"]
    assert candidate["source_closure_contract"]["passed"] is False


def test_synthetic_admission_receipt_cannot_release(
    tmp_path: Path, monkeypatch,
) -> None:
    closure = release_candidate.materialize_source_closure(root=ROOT, code_root=ROOT)
    synthetic_admission = _ready_audit(closure["closure_sha256"])
    assert release_candidate._validate_admission_observation(synthetic_admission) == []
    # Preserve an otherwise release-capable admission object and alter only
    # its schema, so this exercises the schema discriminator specifically.
    synthetic_admission["schema"] = (
        "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8")
    assert release_candidate._validate_admission_observation(synthetic_admission) == [
        "admission audit schema is missing or unsupported",
    ]
    monkeypatch.setattr(
        release_candidate, "audit_admission",
        lambda *args, **kwargs: synthetic_admission,
    )
    monkeypatch.setattr(
        release_candidate, "campaign_completion",
        lambda payload, root: _complete_campaign(),
    )

    candidate = release_candidate.build_candidate(**_candidate_inputs(tmp_path))

    assert candidate["status"] == "blocked"
    assert candidate["formal_release"] is False
    assert candidate["formal_training_ready"] is False
    assert candidate["formal_job_count"] == 0
    assert candidate["admission_contract_valid"] is False
    assert "ADMISSION_AUDIT_INVALID" in candidate["blocker_codes"]
    assert candidate["campaign_completion"]["valid"] is True
    assert candidate["campaign_completion"]["can_finalize"] is True


def test_candidate_requires_final_campaign_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        release_candidate,
        "audit_admission",
        lambda *args, **kwargs: _ready_audit(
            release_candidate.materialize_source_closure(root=ROOT, code_root=ROOT)[
                "closure_sha256"
            ]
        ),
    )
    registry = tmp_path / "registry.json"
    registry.write_text("{}\n", encoding="utf-8")
    before = _sha256(registry)
    inputs = _candidate_inputs(tmp_path)
    inputs["registry"] = registry

    candidate = release_candidate.build_candidate(**inputs)

    assert candidate["status"] == "blocked"
    assert candidate["formal_training_ready"] is False
    assert candidate["formal_release"] is False
    assert "CAMPAIGN_COMPLETION_REQUIRED" in candidate["blocker_codes"]
    assert candidate["campaign_completion"]["valid"] is True
    assert candidate["campaign_completion"]["can_finalize"] is False
    assert candidate["campaign_completion"]["checks"]
    assert candidate["campaign_completion_required_for_full_finalize"] is True
    assert _sha256(registry) == before


def test_candidate_promotes_only_when_closure_and_completion_both_pass(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        release_candidate,
        "audit_admission",
        lambda *args, **kwargs: _ready_audit(
            release_candidate.materialize_source_closure(root=ROOT, code_root=ROOT)[
                "closure_sha256"
            ]
        ),
    )
    monkeypatch.setattr(
        release_candidate,
        "campaign_completion",
        lambda payload, root: _complete_campaign(),
    )

    candidate = release_candidate.build_candidate(**_candidate_inputs(tmp_path))

    assert candidate["status"] == "released"
    assert candidate["formal_training_ready"] is True
    assert candidate["formal_release"] is True
    assert candidate["blocker_codes"] == []
