"""Synthetic contract tests for the bounded host-I/O probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import core_material_host_io_probe_v1 as probe


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-29-RERUN1.json"
HISTORICAL_REPORT = ROOT / "reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-28.json"


def _positive(tmp_path: Path) -> dict:
    return probe.run_probe(
        temp_parent=tmp_path,
        probe_bytes=32 * 1024,
        concurrency=2,
        owned_io_bytes_per_worker=128 * 1024,
        minimum_free_disk_bytes=1,
    )


def test_positive_probe_is_bounded_explicit_and_non_authorizing(tmp_path: Path) -> None:
    report = _positive(tmp_path)

    assert probe.validate_report(report) == []
    assert report["status"] == "diagnostic_pass"
    assert report["probe"]["probe_pass"] is True
    assert report["workspace"]["max_files"] == 1
    assert report["workspace"]["max_bytes"] == probe.MAX_WORKSPACE_BYTES
    assert report["workspace"]["used_bytes"] == 32 * 1024
    assert report["workspace"]["cleaned"] is True
    assert report["workspace"]["exists_after_cleanup"] is False

    io = report["io_measurement"]
    assert io["bytes_requested"] == 32 * 1024
    assert io["bytes_written"] == 32 * 1024
    assert io["bytes_read"] == 32 * 1024
    assert io["fsync_count"] == 1
    assert io["readback_sha256_match"] is True
    assert all(io[name] >= 0.0 for name in (
        "write_elapsed_seconds",
        "fsync_elapsed_seconds",
        "read_elapsed_seconds",
        "elapsed_seconds",
    ))

    projection = report["owned_io_projection"]
    assert projection["concurrency"] == 2
    assert projection["projected_owned_io_bytes"] == 256 * 1024
    assert projection["projected_total_io_bytes"] == 320 * 1024
    assert projection["observed"] is False

    filesystem = report["filesystem"]["before"]
    assert filesystem["device_id"] >= 0
    assert filesystem["filesystem_id"] >= 0
    assert filesystem["filesystem_type"]
    assert filesystem["mount_point"]
    assert report["disk"]["before"]["free_bytes"] >= 0
    assert report["cpu"]["after"]["affinity_cpu_count"] >= 1
    assert report["ram"]["after"]["available_bytes"] >= 0

    boundary = report["authorization_boundary"]
    assert boundary["probe_is_authorization"] is False
    assert boundary["worker_launch_authorized"] is False
    assert boundary["formal_admission"] is False
    assert boundary["qualification_credit"] == 0
    controls = report["execution_controls"]
    assert controls["production_hdf5_opened"] is False
    assert controls["material_worker_started"] is False
    assert controls["solver_started"] is False
    assert controls["gpu_initialized"] is False
    assert controls["queue_or_scheduler_started"] is False


def test_invalid_request_fails_closed_without_io(tmp_path: Path) -> None:
    report = probe.run_probe(
        temp_parent=tmp_path,
        probe_bytes=0,
        concurrency=1,
        owned_io_bytes_per_worker=1,
        minimum_free_disk_bytes=1,
    )

    assert probe.validate_report(report) == []
    assert report["status"] == "failed_closed"
    assert report["probe"]["probe_pass"] is False
    assert report["failure"]["fail_closed"] is True
    assert report["failure"]["stage"] == "input_validation"
    assert report["io_measurement"]["bytes_written"] is None
    assert report["authorization_boundary"]["worker_launch_authorized"] is False
    assert list(tmp_path.iterdir()) == []


def test_snapshot_exception_fails_closed(monkeypatch, tmp_path: Path) -> None:
    def fail_ram_snapshot() -> dict:
        raise RuntimeError("synthetic missing RAM field")

    monkeypatch.setattr(probe, "_ram_snapshot", fail_ram_snapshot)
    report = _positive(tmp_path)

    assert probe.validate_report(report) == []
    assert report["status"] == "failed_closed"
    assert report["failure"]["error_type"] == "RuntimeError"
    assert report["failure"]["fail_closed"] is True
    assert report["probe"]["measurement_complete"] is False
    assert report["authorization_boundary"]["formal_admission"] is False
    assert list(tmp_path.iterdir()) == []


def test_missing_field_never_validates_as_a_pass(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    del report["io_measurement"]["bytes_read"]

    errors = probe.validate_report(report)
    assert "missing field: io_measurement.bytes_read" in errors
    assert report["probe"]["probe_pass"] is True
    # Callers must require validation before interpreting probe_pass.
    assert errors


def test_internal_checks_cannot_be_tampered_into_a_positive_receipt(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    report["probe"]["checks"]["filesystem_identity_stable"] = False

    errors = probe.validate_report(report)

    assert "probe_pass is inconsistent with diagnostic checks" in errors
    assert errors


def test_filesystem_identity_drift_is_rejected_even_with_passing_flags(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    report["filesystem"]["stable"] = False
    report["filesystem"]["after"]["filesystem_id"] += 1

    errors = probe.validate_report(report)

    assert "filesystem identity is not marked stable" in errors
    assert "filesystem identity changed between snapshots" in errors


def test_request_and_projection_are_cross_bound(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    report["request"]["minimum_free_disk_bytes"] = 0

    errors = probe.validate_report(report)

    assert "disk minimum free bytes are not bound to the request" in errors
    assert errors


def test_workspace_path_must_be_a_fresh_direct_child(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    report["workspace"]["path"] = str(tmp_path / "nested" / "not-a-probe")

    errors = probe.validate_report(report)

    assert "temporary workspace path is not a direct child of its parent" in errors
    assert errors


def test_workspace_usage_rejects_symlink_entries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alias").symlink_to(tmp_path / "outside")

    with pytest.raises(ValueError, match="non-regular entry"):
        probe._workspace_usage(workspace)


def test_resource_negative_is_complete_but_fail_closed(tmp_path: Path) -> None:
    report = probe.run_probe(
        temp_parent=tmp_path,
        probe_bytes=8 * 1024,
        concurrency=1,
        owned_io_bytes_per_worker=1,
        minimum_free_disk_bytes=10**30,
    )

    assert probe.validate_report(report) == []
    assert report["status"] == "diagnostic_fail_closed"
    assert report["probe"]["contract_valid"] is True
    assert report["probe"]["probe_pass"] is False
    assert report["disk"]["free_disk_pass"] is False
    assert report["failure"]["fail_closed"] is True
    assert report["authorization_boundary"]["worker_launch_authorized"] is False


def test_report_writer_is_new_file_only(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    destination = tmp_path / "diagnostic.json"
    assert probe.write_report(report, destination) == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == report
    try:
        probe.write_report(report, destination)
    except FileExistsError:
        pass
    else:
        raise AssertionError("diagnostic writer must not overwrite an existing artifact")


def test_report_writer_rejects_symlinked_parent(tmp_path: Path) -> None:
    report = _positive(tmp_path)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked parent"):
        probe.write_report(report, alias_parent / "diagnostic.json")
    assert list(real_parent.iterdir()) == []


def test_committed_diagnostic_fixture_is_zero_credit_and_non_authorizing() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert probe.validate_report(report) == []
    assert report["status"] == "diagnostic_pass"
    assert report["authorization_boundary"]["probe_is_authorization"] is False
    assert report["authorization_boundary"]["worker_launch_authorized"] is False
    assert report["authorization_boundary"]["formal_admission"] is False
    assert report["authorization_boundary"]["qualification_credit"] == 0
    assert report["execution_controls"]["production_hdf5_opened"] is False


def test_historical_probe_fixture_remains_immutable_after_security_rerun() -> None:
    historical = json.loads(HISTORICAL_REPORT.read_text(encoding="utf-8"))
    current = json.loads(REPORT.read_text(encoding="utf-8"))

    assert probe.validate_report(historical) == []
    assert probe.validate_report(current) == []
    assert historical["status"] == "diagnostic_pass"
    assert current["status"] == "diagnostic_pass"
    assert current["observed_at_utc"] != historical["observed_at_utc"]
