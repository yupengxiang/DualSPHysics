"""Synthetic-only tests for the F3 MLP seed29 authority projection gap."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_seed29_authority_projection_gap_v1 as gap


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _plan(path: Path, **overrides: object) -> None:
    payload: dict[str, object] = {
        "schema": gap.ROLLOUT_PLAN_SCHEMA,
        "status": "dry_run_ready",
        "mode": "dry_run",
        "launched": False,
        "seed": 29,
        "model": "mlp",
        "hidden": 16,
        "updates": 500,
        "run_id": "f3-mlp500-hidden16-currentmanifest-seed29-20260929",
        "namespace_nonce": "a" * 32,
        "output_namespace": "/tmp/f3-mlp-seed29-full835-a" * 1,
        "gpu_index": 4,
        "manifest_sha256": "b" * 64,
        "training_receipt_sha256": "c" * 64,
        "checkpoint": {"sha256": "d" * 64, "bytes": 1},
    }
    payload.update(overrides)
    _write_json(path, payload)


def test_seed29_gap_is_fail_closed_and_never_launches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = tmp_path / "seed29-plan.json"
    _plan(observed)
    monkeypatch.setattr(gap, "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH", tmp_path / "missing-key")
    monkeypatch.setattr(gap, "EXTERNAL_SCHEDULER_ROOT", tmp_path / "missing-root")

    report = gap.build_report(observed_plan=observed)

    assert report["status"] == "blocked_projection_gap"
    assert report["scope"]["seed"] == 29
    assert report["scope"]["model_kind"] == "mlp"
    assert report["external_authority"]["verified"] is False
    assert report["resource_binding"]["verified"] is False
    assert report["projection_contract"]["safe_local_projection_implemented"] is False
    assert report["launch_boundary"]["popen_attempted"] is False
    assert report["launch_boundary"]["launch_allowed"] is False
    assert "external_scheduler_authority_document" in report["missing_requirements"]
    assert "authority_gpu_uuid_pci_binding" in report["missing_requirements"]
    assert "independently_bound_terminal_receipt" in report["missing_requirements"]
    assert report["credit"] == 0
    assert gap.validate_report(report) == []


def test_nonce_namespace_and_gpu_index_are_not_resource_authority(tmp_path: Path) -> None:
    observed = tmp_path / "seed29-plan.json"
    _plan(observed, namespace_nonce="e" * 32, gpu_index=7)

    report = gap.build_report(observed_plan=observed)

    assert report["observed_plan"]["namespace_nonce_present"] is True
    assert report["observed_plan"]["output_namespace_present"] is True
    assert report["resource_binding"]["local_gpu_index_is_not_identity"] is True
    assert report["resource_binding"]["verified"] is False
    assert report["observed_plan"]["namespace_inode_binding_present"] is False
    assert report["observed_plan"]["resource_snapshot_present"] is False
    assert gap.validate_report(report) == []


def test_supplied_authority_path_is_metadata_only_and_not_promoted(tmp_path: Path) -> None:
    observed = tmp_path / "seed29-plan.json"
    authority = tmp_path / "authority.json"
    _plan(observed)
    _write_json(authority, {"schema": "untrusted.local.claim", "seed": 29})

    report = gap.build_report(observed_plan=observed, authority_document=authority)

    assert report["external_authority"]["path_supplied"] is True
    assert report["external_authority"]["supplied_path_state"]["present"] is True
    assert report["external_authority"]["verified"] is False
    assert report["projection_contract"]["runner_consumable"] is False
    assert report["projection_contract"]["durable_receipt_written"] is False
    assert any("metadata-only" in item for item in report["blockers"])
    assert gap.validate_report(report) == []


def test_caller_authority_shaped_field_is_rejected_by_report_validator(tmp_path: Path) -> None:
    observed = tmp_path / "seed29-plan.json"
    _plan(observed)
    report = gap.build_report(observed_plan=observed)
    forged = copy.deepcopy(report)
    forged["observed_plan"]["authority_field_present"] = True

    assert gap.validate_report(forged)


def test_contract_inventory_is_shared_mlp_only_and_has_no_authority_boundary(tmp_path: Path) -> None:
    observed = tmp_path / "seed29-plan.json"
    _plan(observed)
    report = gap.build_report(observed_plan=observed)

    assert set(report["contract_sources"]) == {
        "rollout_launcher",
        "training_evidence",
        "case_matrix",
        "terminal_evidence",
    }
    assert all(
        "f3_mlp_hidden16_current_manifest_" in item["path"]
        and "seed17" not in item["path"]
        and "seed43" not in item["path"]
        for item in report["contract_sources"].values()
    )
    assert report["current_contract"]["external_authority_boundary_present"] is False
    assert report["current_contract"]["explicit_execute_path_present"] is True
    assert report["admission_contract"]["signature_algorithm"] == "ed25519"
    assert report["admission_contract"]["caller_claim_can_substitute"] is False
    assert report["side_effects"]["registry_writes"] == 0
    assert report["side_effects"]["plan_writes"] == 0


@pytest.mark.parametrize("field", ["credit", "formal", "launch_boundary"])
def test_report_validator_rejects_promotion_mutation(tmp_path: Path, field: str) -> None:
    observed = tmp_path / "seed29-plan.json"
    _plan(observed)
    report = gap.build_report(observed_plan=observed)
    forged = copy.deepcopy(report)
    if field == "credit":
        forged[field] = 1
    elif field == "formal":
        forged[field] = True
    else:
        forged[field]["launch_allowed"] = True

    assert gap.validate_report(forged)
