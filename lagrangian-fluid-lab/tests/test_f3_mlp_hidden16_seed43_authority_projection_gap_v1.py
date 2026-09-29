"""Focused tests for the MLP hidden16 seed43 authority-gap artifact."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_seed43_authority_projection_gap_v1 as gap


def test_seed43_gap_is_precise_and_zero_credit() -> None:
    report = gap.audit()

    assert report["scope"]["model_kind"] == "mlp"
    assert report["scope"]["hidden"] == 16
    assert report["scope"]["seed"] == 43
    assert report["scope"]["updates"] == 500
    assert report["scope"]["transitions"] == 835
    assert report["scope"]["frames"] == 836
    assert report["status"] in {"blocked_fail_closed", "blocked_static_unverified"}
    assert report["implementation_coverage"]["current_manifest_identity_binding"] is True
    assert report["implementation_coverage"]["local_nonce_binding"] is True
    assert report["implementation_coverage"]["local_namespace_binding"] is True
    assert report["implementation_coverage"]["external_scheduler_authority_contract"] is False
    assert report["implementation_coverage"]["ed25519_signature_verification"] is False
    assert report["implementation_coverage"]["scheduler_owned_gpu_uuid_pci_binding"] is False
    assert report["implementation_coverage"]["one_shot_external_consume_witness"] is False
    assert report["implementation_coverage"]["authority_gate_before_execute"] is False
    assert report["external_authority"]["verified"] is False
    assert report["resource_binding"]["verified"] is False
    assert report["projection_contract"]["runner_consumable"] is False
    assert report["readiness"]["launch_allowed"] is False
    assert report["readiness"]["popen_attempted"] is False
    assert report["credit"] == 0
    assert {item["id"] for item in report["exact_gaps"]} >= {
        "F3-MLP43-AUTH-ROOT-001",
        "F3-MLP43-AUTH-DOC-002",
        "F3-MLP43-AUTH-CLAIM-003",
        "F3-MLP43-AUTH-IMPL-004",
        "F3-MLP43-AUTH-RESOURCE-005",
        "F3-MLP43-AUTH-VERIFY-006",
    }
    assert gap.validate_report(report) == []


def test_metadata_only_scheduler_files_never_become_verified_authority(tmp_path: Path) -> None:
    key = tmp_path / "scheduler-ed25519-public.key"
    root = tmp_path / "scheduler-root"
    root.mkdir()
    key.write_bytes(b"metadata-only-key")
    (root / "candidate.authority.json").write_bytes(b"not read")
    (root / "candidate.claim.json").write_bytes(b"not read")

    report = gap.audit(
        trusted_scheduler_public_key=key,
        external_scheduler_root=root,
    )

    observed = report["production_observation"]
    assert report["status"] == "blocked_static_unverified"
    assert observed["production_key_available"] is True
    assert observed["production_scheduler_root_available"] is True
    assert observed["authority_document_available"] is True
    assert observed["one_shot_claim_available"] is True
    assert observed["production_authority_verified"] is False
    assert report["external_authority"]["verified"] is False
    assert "F3-MLP43-AUTH-VERIFY-006" in {item["id"] for item in report["exact_gaps"]}


def test_bounded_source_reader_rejects_oversized_input(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.py"
    oversized.write_bytes(b"x" * (gap.MAX_SOURCE_BYTES + 1))

    with pytest.raises(gap.AuditError, match="bounded audit read limit"):
        gap._read_small(oversized, max_bytes=gap.MAX_SOURCE_BYTES, name="oversized source")


def test_report_writer_and_verifier_are_seed43_scoped(tmp_path: Path) -> None:
    report = gap.audit()
    json_path = tmp_path / "F3-MLP-HIDDEN16-SEED43-GAP.json"
    markdown_path = tmp_path / "F3-MLP-HIDDEN16-SEED43-GAP.md"

    written_json, written_markdown = gap.write_reports(
        report,
        report_path=json_path,
        markdown_path=markdown_path,
    )

    parsed = json.loads(written_json.read_text(encoding="utf-8"))
    assert gap.validate_report(parsed) == []
    assert written_markdown.read_text(encoding="utf-8").find("seed43") >= 0
    assert gap.main(["--verify-report", str(written_json)]) == 0


def test_validator_rejects_credit_or_launch_mutation() -> None:
    report = gap.audit()

    forged_credit = copy.deepcopy(report)
    forged_credit["credit"] = 1
    assert gap.validate_report(forged_credit)

    forged_launch = copy.deepcopy(report)
    forged_launch["projection_contract"]["popen_allowed"] = True
    assert gap.validate_report(forged_launch)


def test_writer_rejects_non_seed43_outputs(tmp_path: Path) -> None:
    report = gap.audit()
    with pytest.raises(gap.AuditError, match="seed43 report path"):
        gap.write_reports(
            report,
            report_path=tmp_path / "F3-MLP-HIDDEN16-SEED29-GAP.json",
            markdown_path=tmp_path / "F3-MLP-HIDDEN16-SEED29-GAP.md",
        )
