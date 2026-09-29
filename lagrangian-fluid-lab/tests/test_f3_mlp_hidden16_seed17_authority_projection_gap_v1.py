"""Synthetic-only tests for the F3 MLP hidden16 seed17 authority gap."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_seed17_authority_projection_gap_v1 as gap


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _projection_inputs(tmp_path: Path) -> dict[str, Path]:
    manifest = tmp_path / "manifest-identity.json"
    training = tmp_path / "training-evidence.json"
    terminal = tmp_path / "terminal-evidence.json"
    plan = tmp_path / "seed17-rollout-plan.json"
    _write_json(
        manifest,
        {
            "schema": "core.f3.mlp.hidden16.current_manifest.identity_projection.v1",
            "status": "bound",
            "source_bound": True,
            "diagnostic_only": True,
            "formal": False,
            "credit": 0,
            "manifest": {"raw": {"sha256": "a" * 64}, "canonical": {"sha256": "b" * 64}},
        },
    )
    _write_json(
        training,
        {
            "schema": "core.f3.mlp.hidden16.current_manifest_training_evidence.v1",
            "status": "diagnostic_bound",
            "source_bound": True,
            "diagnostic_only": True,
            "formal": False,
            "credit": 0,
            "runs": [
                {
                    "seed": 17,
                    "status": "bound",
                    "evidence": {
                        "model": "mlp",
                        "hidden": 16,
                        "updates": 500,
                        "run_id": "fixture-mlp-seed17",
                        "checkpoint_identity": {"path": "/tmp/checkpoint.pt", "sha256": "c" * 64, "bytes": 1},
                    },
                    "source": {"path": "/tmp/training.json", "sha256": "d" * 64, "bytes": 1},
                }
            ],
        },
    )
    _write_json(
        terminal,
        {
            "schema": "core.f3.mlp.hidden16.current_manifest_terminal_evidence.v1",
            "status": "diagnostic_bound",
            "source_bound": True,
            "diagnostic_only": True,
            "formal": False,
            "credit": 0,
            "seed_matrix": [
                {"seed": 17, "status": "bound", "blocked_reasons": [], "evidence": {}, "sources": {"process_exit_proof": {}}}
            ],
        },
    )
    _write_json(
        plan,
        {
            "schema": "core.f3.mlp.hidden16.current_manifest_rollout_launcher_plan.v1",
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "seed": 17,
            "run_id": "fixture-mlp-seed17",
            "model": "mlp",
            "hidden": 16,
            "updates": 500,
            "case_id": "F3_DEV_00_a0p903125",
            "split": "test",
            "transitions": 835,
            "frames": 836,
            "gpu_index": 2,
            "manifest_sha256": "b" * 64,
            "manifest_file_sha256": "a" * 64,
            "training_receipt_sha256": "d" * 64,
            "output_namespace": "/tmp/f3-mlp500-hidden16-currentmanifest-seed17-full835-nonce" + "e" * 32,
            "namespace_nonce": "e" * 32,
            "command_sha256": "f" * 64,
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "credit": 0,
        },
    )
    return {
        "manifest_identity": manifest,
        "training_evidence": training,
        "terminal_evidence": terminal,
        "rollout_plan": plan,
    }


def test_seed17_gap_is_fail_closed_without_local_authority(tmp_path: Path) -> None:
    report = gap.build_report(inputs=_projection_inputs(tmp_path))

    assert report["status"] == "blocked_projection_gap"
    assert report["scope"]["model"] == "mlp"
    assert report["scope"]["seed"] == 17
    assert report["external_authority"]["verified"] is False
    assert report["external_authority"]["configured_scheduler_root"] is None
    assert report["resource_binding"]["verified"] is False
    assert report["binding_status"]["nonce_declared"] is True
    assert report["binding_status"]["namespace_declared"] is True
    assert report["binding_status"]["external_signature_verified"] is False
    assert "external_scheduler_authority_document" in report["missing_requirements"]
    assert "scheduler_owned_resource_snapshot.gpu_uuid_pci_vram" in report["missing_requirements"]
    assert report["projection_contract"]["runner_consumable"] is False
    assert report["projection_contract"]["popen_allowed"] is False
    assert report["credit"] == 0
    assert gap.validate_report(report) == []


def test_missing_projection_is_reported_without_synthesizing_fields(tmp_path: Path) -> None:
    inputs = _projection_inputs(tmp_path)
    inputs["terminal_evidence"] = tmp_path / "missing-terminal.json"
    report = gap.build_report(inputs=inputs)

    assert report["observed_inputs"]["terminal_evidence"]["observed"] is False
    assert "observed_projection:terminal_evidence" in report["missing_requirements"]
    assert report["admission_contract"]["local_projection_allowed"] is False
    assert report["projection_contract"]["durable_receipt_written"] is False
    assert report["projection_contract"]["historical_receipt_rewritten"] is False
    assert report["credit"] == 0
    assert gap.validate_report(report) == []


def test_tampered_report_cannot_add_authority_or_side_effect(tmp_path: Path) -> None:
    report = gap.build_report(inputs=_projection_inputs(tmp_path))

    forged = deepcopy(report)
    forged["credit"] = 1
    assert gap.validate_report(forged)

    forged = deepcopy(report)
    forged["external_authority"]["verified"] = True
    assert gap.validate_report(forged)

    forged = deepcopy(report)
    forged["side_effects"]["popen_attempted"] = True
    assert gap.validate_report(forged)


def test_contract_inventory_stays_in_mlp_scope(tmp_path: Path) -> None:
    report = gap.build_report(inputs=_projection_inputs(tmp_path))

    assert set(report["contract_sources"]) == set(gap.CONTRACT_SOURCE_PATHS)
    assert all("f3_mlp_hidden16" in item["path"] for item in report["contract_sources"].values())
    assert all("graph_raw" not in item["path"] and "graph_residual" not in item["path"] for item in report["contract_sources"].values())
    assert report["admission_contract"]["signature_algorithm"] == "ed25519"
    assert report["admission_contract"]["caller_claim_can_substitute"] is False
    assert report["admission_contract"]["implicit_resource_probe_allowed"] is False


def test_cli_has_no_execution_alias() -> None:
    parsed = gap._parse_args([])
    assert not hasattr(parsed, "execute")
    assert not hasattr(parsed, "authority_document")
