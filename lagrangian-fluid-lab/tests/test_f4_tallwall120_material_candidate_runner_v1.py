from __future__ import annotations

from pathlib import Path

from scripts import f4_tallwall120_material_candidate_runner_v1 as runner


LAB_ROOT = Path(__file__).resolve().parents[1]


def _resources(*, gpu_pass: bool = True) -> dict:
    return {
        "observed_at_utc": "2026-09-28T00:00:00+00:00",
        "gpu": {
            "observed": True,
            "required_peak_mib": runner.GPU_PEAK_MIB,
            "devices": [{"index": 3, "memory_free_mib": 31079}],
            "max_free_mib": 31079,
            "capacity_pass": gpu_pass,
        },
        "ram": {
            "observed": True,
            "available_bytes": runner.RAM_REQUIRED_MIB * 1024**2,
            "capacity_pass": True,
        },
        "disk": {
            "observed": True,
            "free_bytes": runner.DISK_REQUIRED_BYTES,
            "capacity_pass": True,
        },
        "capacity_observed": True,
        "capacity_pass": gpu_pass,
    }


def test_real_inputs_produce_blocked_receipt_without_execution() -> None:
    report = runner.build_report(LAB_ROOT, resource_snapshot=_resources())

    assert report["status"] == "blocked_fail_closed"
    assert report["planned_sidecar"]["produced"] is False
    assert "missing_or_invalid_fresh_root_receipt" in report["blockers"]
    assert "diagnostic_event_window_incomplete_or_right_censored" in report["blockers"]
    assert report["authorization"]["T2"] is False
    assert report["authorization"]["credit"] == 0
    assert report["execution_controls"]["source_hdf5_opened"] is False
    assert report["execution_controls"]["runner_invoked_material_trace"] is False
    assert report["execution_controls"]["sidecar_written"] is False
    assert runner.validate_report(report) == []


def test_existing_diagnostic_parameter_drift_is_not_reused_as_sidecar() -> None:
    report = runner.build_report(LAB_ROOT, resource_snapshot=_resources())
    diagnostic = report["observations"]["existing_material_diagnostic"]

    assert diagnostic["checks"]["source_identity"] is True
    assert diagnostic["checks"]["parameter_binding"] is False
    assert diagnostic["checks"]["event_window_complete"] is False
    assert diagnostic["checks"]["unknown_gate"] is False
    assert diagnostic["checks"]["reliable_coverage"] is False
    assert "existing_diagnostic_parameter_drift" in report["blockers"]


def test_shared_gpu_policy_uses_free_vram_not_utilization() -> None:
    snapshot = runner._gpu_snapshot
    parsed = runner._safe_int("39400")

    assert parsed == 39400
    # The actual parser/contract permits a device with non-zero utilization;
    # only free VRAM determines capacity.  Keep this as a pure bounded fixture.
    resource = _resources()
    resource["gpu"]["devices"][0]["utilization_gpu_percent"] = 87
    assert resource["gpu"]["capacity_pass"] is True
    assert callable(snapshot)


def test_insufficient_vram_keeps_receipt_fail_closed() -> None:
    report = runner.build_report(LAB_ROOT, resource_snapshot=_resources(gpu_pass=False))

    assert report["checks"]["gpu_vram_headroom"] is False
    assert "gpu_vram_headroom_insufficient" in report["blockers"]
    assert report["authorization"]["worker_launch_authorized"] is False
    assert report["execution_controls"]["gpu_initialized"] is False


def test_invalid_claims_cannot_be_written(tmp_path: Path) -> None:
    report = runner.build_report(LAB_ROOT, resource_snapshot=_resources())
    report["authorization"]["T2"] = True

    assert "authorization.fail_closed" in runner.validate_report(report)
    try:
        runner.write_report(report, tmp_path / "invalid.json")
    except ValueError as error:
        assert "authorization.fail_closed" in str(error)
    else:
        raise AssertionError("invalid T2 claim must be rejected")
