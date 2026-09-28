"""Synthetic-only tests for the additive F3 material source-path v2 sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_coarse_root_scheduler_intake_v1 as v1
from scripts import f3_material_coarse_root_scheduler_intake_v2 as v2


def _source(root: Path, relative: str = "data/clean/source.h5") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic source bytes")
    return path


def test_clean_source_path_is_closed_without_content_access(tmp_path: Path) -> None:
    _source(tmp_path)

    result = v2.audit_source_path(tmp_path, "data/clean/source.h5")

    assert result["status"] == v2.AUDIT_CLOSED
    assert all(result["checks"].values())
    assert result["content_access"] == {
        "opened": False,
        "read": False,
        "hash_recomputed": False,
        "opened_as_hdf5": False,
    }


def test_parent_symlink_is_rejected_even_when_final_node_is_regular(tmp_path: Path) -> None:
    source = _source(tmp_path)
    alias = tmp_path / "data/alias"
    alias.symlink_to(source.parent, target_is_directory=True)

    result = v2.audit_source_path(tmp_path, "data/alias/source.h5")

    assert result["status"] == v2.AUDIT_BLOCKED
    assert result["checks"]["all_components_non_symlink"] is False
    assert any(item.startswith("symlink_component:") for item in result["errors"])
    assert result["content_access"]["opened"] is False


def test_v1_final_lstat_gap_is_reproduced_by_the_same_parent_alias_fixture(tmp_path: Path) -> None:
    source = _source(tmp_path)
    alias = tmp_path / "data/alias"
    alias.symlink_to(source.parent, target_is_directory=True)

    reference, error = v1._source_metadata(
        tmp_path,
        tmp_path / "data/alias/source.h5",
        claimed_sha256="0" * 64,
    )

    assert error is None
    assert reference["exists"] is True
    assert reference["regular_file"] is True
    assert reference["symlink"] is False
    assert v2.audit_source_path(tmp_path, "data/alias/source.h5")["status"] == v2.AUDIT_BLOCKED


def test_multiple_hardlink_source_is_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    alias = tmp_path / "data/hardlink/source.h5"
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.hardlink_to(source)

    result = v2.audit_source_path(tmp_path, "data/hardlink/source.h5")

    assert result["status"] == v2.AUDIT_BLOCKED
    assert result["checks"]["source_single_hardlink"] is False
    assert "source_hardlink_or_alias" in result["errors"]


def test_symlink_root_is_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    _source(real_root)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    result = v2.audit_source_path(linked_root, "data/clean/source.h5")

    assert result["status"] == v2.AUDIT_BLOCKED
    assert result["checks"]["root_is_not_symlink"] is False
    assert "root_symlink_component" in result["errors"]


def test_invalid_source_path_is_rejected_before_lstat(tmp_path: Path) -> None:
    with pytest.raises(v2.SourcePathProvenanceError):
        v2.audit_source_path(tmp_path, "../outside/source.h5")
    with pytest.raises(v2.SourcePathProvenanceError):
        v2.audit_source_path(tmp_path, str(tmp_path / "source.h5"))


def test_source_audit_never_opens_or_reads_hdf5(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _source(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("source-path audit must use lstat metadata only")

    monkeypatch.setattr(v2.os, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = v2.audit_source_path(tmp_path, "data/clean/source.h5")

    assert result["status"] == v2.AUDIT_CLOSED
    assert result["content_access"]["read"] is False


def test_checked_in_report_is_synthetic_and_fail_closed() -> None:
    report = v2.build_report()
    assert v2.validate_report(report) == []
    assert report["status"] == v2.STATUS
    assert report["input_boundary"]["synthetic_only"] is True
    assert report["input_boundary"]["production_paths_read"] is False
    assert report["non_authorizing_boundary"]["diagnostic_only"] is True
    assert report["non_authorizing_boundary"]["credit"] == 0
    assert report["execution_constraints"]["gpu_started"] is False
    assert report["execution_constraints"]["queue_started"] is False


def test_malformed_report_validation_fails_closed_without_raising() -> None:
    report = v2.build_report()
    report["scope"] = None
    report["checks"] = None
    report["non_authorizing_boundary"] = None

    errors = v2.validate_report(report)

    assert {"scope", "checks", "non_authorizing_boundary"} <= set(errors)


def test_checked_in_machine_and_chinese_reports_match_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    report_path = root / "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V2-SYNTHETIC-SOURCE-PATH-PROVENANCE-2026-09-29.json"
    zh_path = root / "reports/F3-MATERIAL-COARSE-ROOT-SCHEDULER-INTAKE-V2-SYNTHETIC-SOURCE-PATH-PROVENANCE-2026-09-29.zh-CN.md"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == v2.build_report()
    assert v2.validate_report(report) == []
    assert zh_path.read_text(encoding="utf-8").startswith("# F3 material coarse v2")


def test_report_writers_are_bounded_and_non_overwriting(tmp_path: Path) -> None:
    report = v2.build_report()
    output = tmp_path / "report.json"
    zh_output = tmp_path / "report.zh-CN.md"

    assert v2.write_report(report, output) == output
    assert v2.write_zh_cn(report, zh_output) == zh_output
    assert json.loads(output.read_text(encoding="utf-8")) == report
    with pytest.raises(FileExistsError):
        v2.write_report(report, output)
    with pytest.raises(FileExistsError):
        v2.write_zh_cn(report, zh_output)
