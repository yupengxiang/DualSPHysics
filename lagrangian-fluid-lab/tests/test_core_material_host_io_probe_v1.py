"""Synthetic contract tests for the bounded host-I/O probe."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import core_material_host_io_probe_v1 as probe


REPORT = Path(__file__).resolve().parents[1] / "reports/CORE-MATERIAL-HOST-IO-PROBE-2026-09-28.json"


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


def test_committed_diagnostic_fixture_is_zero_credit_and_non_authorizing() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert probe.validate_report(report) == []
    assert report["status"] == "diagnostic_pass"
    assert report["authorization_boundary"]["probe_is_authorization"] is False
    assert report["authorization_boundary"]["worker_launch_authorized"] is False
    assert report["authorization_boundary"]["formal_admission"] is False
    assert report["authorization_boundary"]["qualification_credit"] == 0
    assert report["execution_controls"]["production_hdf5_opened"] is False
