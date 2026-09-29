"""Fail-closed tests for the residual seed17 runner v2.

The runner is intentionally not an executor in this revision.  These tests
assert that dry-run and explicit execute requests do not consume the receipt,
call Popen, start a workload, or mint a terminal receipt.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity
from scripts import f3_graph_residual_hidden16_seed17_diagnostic_admission_v1 as admission
from scripts import f3_graph_residual_hidden16_seed17_diagnostic_runner_v2 as runner


def _resource() -> dict[str, object]:
    value = identity.probe_resource_admission(
        admission.GPU_INDEX,
        gpu_rows={admission.GPU_INDEX: {"total_mib": 49152, "used_mib": 1024, "free_mib": 48128}},
        cpu_count=16,
        load_1m=1.0,
        tmp_free_bytes=16 * 1024**3,
        root_free_bytes=16 * 1024**3,
    )
    gpu = value["gpu"]
    gpu.update(
        {
            "physical_index": admission.GPU_INDEX,
            "uuid": "GPU-12345678-90ab-cdef-1234-567890abcdef",
            "pci_bus_id": "0000:65:00.0",
            "logical_index": 0,
            "cuda_visible_devices": str(admission.GPU_INDEX),
            "cuda_device": "cuda:0",
            "cuda_device_order": admission.CUDA_DEVICE_ORDER,
            "identity_source": "scheduler_owned_snapshot",
            "identity_attested": True,
        }
    )
    gpu["identity_sha256"] = admission.canonical_digest(admission._gpu_identity(gpu))
    value["owner"] = {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "host": admission.CURRENT_HOST,
        "scope": "scheduler_owned_diagnostic_snapshot",
        "snapshot_nonce": "c" * 32,
    }
    return value


def _receipt(tmp_path: Path) -> Path:
    if not admission.DEFAULT_TRAINING.is_file() or not admission.DEFAULT_CHECKPOINT.is_file():
        pytest.skip("current residual seed17 training receipt/checkpoint is unavailable")
    payload = admission.mint_admission(
        admission.LAB_ROOT,
        manifest=admission.DEFAULT_MANIFEST,
        training_receipt=admission.DEFAULT_TRAINING,
        checkpoint=admission.DEFAULT_CHECKPOINT,
        nonce="a" * 31 + "1",
        output_root=tmp_path,
        resource_admission=_resource(),
        python_executable=Path(sys.executable).resolve(),
    )
    return Path(payload["receipt_path"])


def test_build_plan_binds_receipt_and_stays_non_launching(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    plan = runner.build_plan(receipt)
    observed = plan.as_dict()
    assert observed["seed"] == 17
    assert observed["model_kind"] == "graph_residual"
    assert observed["transitions"] == 835
    assert observed["frames"] == 836
    assert observed["launch_allowed"] is False
    assert observed["diagnostic_execute_allowed"] is False
    assert observed["popen_attempted"] is False
    assert observed["real_workload_started"] == 0
    assert observed["credit"] == 0
    assert not Path(str(plan.outputs["terminal_receipt"])).exists()


def test_default_runner_is_dry_run_and_never_reaches_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _receipt(tmp_path)
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("dry-run must not call Popen")

    monkeypatch.setattr(runner, "_SEALED_POPEN", forbidden)
    report = runner.build_report(receipt)
    assert runner.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["popen_attempted"] is False
    assert report["wait_attempted"] is False
    assert report["real_workload_started"] == 0
    assert report["terminal_receipt_minted"] is False
    assert calls == []
    assert not Path(receipt).parent.joinpath(admission.CONSUMED_MARKER).exists()


def test_explicit_diagnostic_execute_fails_before_consumption_or_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _receipt(tmp_path)
    plan = runner.build_plan(receipt)
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("blocked execution must not call Popen")

    monkeypatch.setattr(runner, "_SEALED_POPEN", forbidden)
    with pytest.raises(runner.RunnerError, match="not admitted"):
        runner.execute_diagnostic(plan, object())
    assert calls == []
    assert not Path(receipt).parent.joinpath(admission.CONSUMED_MARKER).exists()


def test_runner_has_no_execute_alias_and_rejects_forged_terminal_receipt(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        runner._parse_args(["--execute"])
    parsed = runner._parse_args(["--diagnostic-execute"])
    assert parsed.diagnostic_execute is True

    plan = runner.build_plan(_receipt(tmp_path))
    forged = {
        "schema": runner.TERMINAL_RECEIPT_SCHEMA,
        "status": "terminal_verified_diagnostic_only",
        "synthetic": True,
    }
    with pytest.raises(runner.RunnerError, match="synthetic"):
        runner.validate_terminal_receipt(plan, forged)


def test_report_without_receipt_is_blocked_and_zero_credit() -> None:
    report = runner.build_report(None, execute_requested=True)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["launch_allowed"] is False
    assert report["popen_attempted"] is False
    assert report["terminal_receipt"] is None
    assert report["credit"] == 0
    assert runner.validate_report(report) == []
