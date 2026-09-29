"""Fail-closed tests for the residual seed29 secure runner v2."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 import _mint

from scripts import f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 as admission
from scripts import f3_graph_residual_hidden16_seed29_diagnostic_runner_v2 as runner


def _receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    receipt, _fixture = _mint(tmp_path, monkeypatch, nonce="f" * 32)
    return Path(receipt["receipt_path"])


def test_build_plan_binds_seed29_descriptors_and_terminal_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt(tmp_path, monkeypatch)
    plan = runner.build_plan(receipt)
    observed = plan.as_dict()
    assert observed["seed"] == 29
    assert observed["model_kind"] == "graph_residual"
    assert observed["hidden"] == 16
    assert observed["transitions"] == 835
    assert observed["frames"] == 836
    assert observed["launch_allowed"] is False
    assert observed["diagnostic_execute_allowed"] is False
    assert observed["popen_attempted"] is False
    assert observed["real_workload_started"] == 0
    assert observed["credit"] == 0
    assert not plan.outputs["terminal_receipt"].exists()


def test_default_runner_never_calls_popen_or_consumes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt(tmp_path, monkeypatch)
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
    assert report["terminal_receipt_minted"] is False
    assert calls == []
    assert not Path(receipt).parent.joinpath(admission.CONSUMED_MARKER).exists()


def test_explicit_execute_fails_before_consumption_or_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt(tmp_path, monkeypatch)
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


def test_output_reservation_is_descriptor_checked_but_child_publication_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = runner.build_plan(_receipt(tmp_path, monkeypatch))
    reservations = runner._reserve_evaluator_outputs(plan)
    runner._validate_output_reservations(reservations)
    with pytest.raises(runner.RunnerError, match="pathname-only"):
        runner._require_descriptor_bound_outputs(plan, reservations)
    runner._release_output_reservations(reservations, remove_unpublished=True)
    assert all(not plan.outputs[name].exists() for name in runner.EVALUATOR_OUTPUT_NAMES)


def test_stable_artifact_and_hdf5_link_boundary(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_bytes(b'{"ok":true}\n')
    descriptor, raw = runner._stable_artifact(path, tmp_path, "payload", max_bytes=1024)
    assert raw == b'{"ok":true}\n'
    assert descriptor["stable_fd"] is True
    assert descriptor["path_reopened"] is False
    assert descriptor["sha256"] == hashlib.sha256(raw).hexdigest()

    if runner.h5py is None:
        with pytest.raises(runner.RunnerError, match="unavailable"):
            runner._inspect_hdf5_snapshot(b"not-hdf5", required_datasets=())
        return
    hdf5_path = tmp_path / "trajectory.h5"
    with runner.h5py.File(hdf5_path, "w") as handle:
        handle.create_dataset("positions", data=[[0.0, 1.0]])
    hdf5_descriptor, hdf5_raw = runner._stable_artifact(
        hdf5_path, tmp_path, "trajectory", max_bytes=1024 * 1024
    )
    assert hdf5_descriptor["content_opened"] is True
    assert runner._inspect_hdf5_snapshot(hdf5_raw, required_datasets=("positions",))["passed"] is True

    with runner.h5py.File(hdf5_path, "a") as handle:
        handle["soft"] = runner.h5py.SoftLink("/positions")
    _descriptor, linked_raw = runner._stable_artifact(
        hdf5_path, tmp_path, "linked trajectory", max_bytes=1024 * 1024
    )
    with pytest.raises(runner.RunnerError, match="soft"):
        runner._inspect_hdf5_snapshot(linked_raw, required_datasets=())


def test_gpu_parser_and_terminal_declaration_forge_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = runner._parse_nvidia_smi_gpu_rows(
        "5, GPU-12345678-90ab-cdef-1234-567890abcdef, 0000:65:00.0, 49152, 1024, 48128\n"
    )
    assert rows[5]["uuid"].startswith("GPU-")
    processes = runner._parse_nvidia_smi_process_rows(
        "1234, GPU-12345678-90ab-cdef-1234-567890abcdef\n"
    )
    assert processes == [{"pid": 1234, "gpu_uuid": "GPU-12345678-90ab-cdef-1234-567890abcdef"}]
    plan = runner.build_plan(_receipt(tmp_path, monkeypatch))
    forged = {
        "schema": runner.TERMINAL_RECEIPT_SCHEMA,
        "status": "terminal_verified_diagnostic_only",
        "synthetic": True,
    }
    with pytest.raises(runner.RunnerError, match="synthetic"):
        runner.validate_terminal_receipt(plan, forged)


def test_parser_has_no_execute_alias_and_empty_report_is_zero_credit() -> None:
    with pytest.raises(SystemExit):
        runner._parse_args(["--execute"])
    parsed = runner._parse_args(["--diagnostic-execute"])
    assert parsed.diagnostic_execute is True
    report = runner.build_report(None, execute_requested=True)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["launch_allowed"] is False
    assert report["popen_attempted"] is False
    assert report["terminal_receipt"] is None
    assert report["credit"] == 0
    assert runner.validate_report(report) == []
