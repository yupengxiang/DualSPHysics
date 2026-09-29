"""Tests for the seed43 authority-bound admission gap artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_seed43_authority_bound_diagnostic_admission_gap_audit_v1 as audit


def test_existing_seed43_contract_is_covered_and_production_gap_is_exact() -> None:
    report = audit.audit()

    assert report["scope"]["seed"] == 43
    assert report["scope"]["model_kind"] == "graph_raw"
    assert report["scope"]["hidden"] == 16
    assert all(report["implementation_coverage"].values())
    assert report["implementation_evidence"]["missing_functions"] == []
    assert report["implementation_evidence"]["forbidden_imports"] == []
    assert report["implementation_evidence"]["forbidden_call_names"] == []
    assert report["readiness"] == {
        "credit": 0,
        "diagnostic_only": True,
        "formal": False,
        "gpu_execution_observed": False,
        "launch_allowed": False,
        "popen_attempted": False,
        "queue_submitted": False,
        "solver_started": False,
        "worker_started": False,
    }
    assert {gap["id"] for gap in report["exact_gaps"]} >= {
        "F3-S43-AUTH-ROOT-001",
        "F3-S43-AUTH-DOC-002",
        "F3-S43-AUTH-CLAIM-003",
        "F3-S43-AUTH-VERIFY-004",
    }
    assert report["production_observation"]["production_authority_verified"] is False


def test_present_metadata_never_becomes_verified_authority(tmp_path: Path) -> None:
    key = tmp_path / "scheduler.key"
    root = tmp_path / "scheduler"
    root.mkdir()
    key.write_bytes(b"metadata-only-test-key")
    (root / "fake.authority.json").write_bytes(b"not read")
    (root / "fake.claim.json").write_bytes(b"not read")

    report = audit.audit(
        trusted_scheduler_public_key=key,
        external_scheduler_root=root,
    )

    assert report["production_observation"]["production_authority_verified"] is False
    assert report["status"] == "blocked_static_unverified"
    assert "F3-S43-AUTH-VERIFY-004" in {gap["id"] for gap in report["exact_gaps"]}


def test_bounded_reader_rejects_oversized_input(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.py"
    oversized.write_bytes(b"x" * (audit.MAX_SOURCE_BYTES + 1))

    with pytest.raises(audit.AuditError, match="bounded audit read limit"):
        audit._read_small(
            oversized,
            max_bytes=audit.MAX_SOURCE_BYTES,
            name="oversized source",
        )


def test_report_writer_is_seed43_scoped(tmp_path: Path) -> None:
    report = audit.audit()
    json_path = tmp_path / "F3-GRAPH-RAW-HIDDEN16-SEED43-GAP.json"
    md_path = tmp_path / "F3-GRAPH-RAW-HIDDEN16-SEED43-GAP.md"
    audit.write_reports(report, report_path=json_path, markdown_path=md_path)

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["schema"] == audit.REPORT_SCHEMA
    assert parsed["readiness"]["credit"] == 0
    assert "seed43" in md_path.read_text(encoding="utf-8")
