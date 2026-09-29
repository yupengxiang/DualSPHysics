"""Fail-closed tests for the audited, non-executing runner v2 boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import h5py
import pytest

from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission
from scripts import f3_graph_raw_hidden16_seed17_diagnostic_runner_v2 as runner


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    for relative in admission.SOURCE_RELATIVE_PATHS.values():
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"# runner v2 pinned source {relative}\n", encoding="utf-8")
    manifest_payload = {
        "schema": admission.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "a" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    _write_json(manifest, manifest_payload)
    checkpoint = root / "inputs" / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint_raw = b"runner v2 checkpoint fixture"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(checkpoint_raw)
    checkpoint_meta = {
        "schema": admission.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
        "bytes": len(checkpoint_raw),
        "update": admission.UPDATES,
    }
    run_id = "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3"
    training = root / "inputs" / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
    _write_json(training, {
        "schema": admission.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": admission.MODEL,
        "seed": admission.SEED,
        "run_id": run_id,
        "completed_updates": admission.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": admission.launcher.canonical_digest(manifest_payload),
            "model_kind": admission.MODEL,
            "hidden": admission.HIDDEN,
            "updates": admission.UPDATES,
            "run_id": run_id,
            "seed": admission.SEED,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **admission.launcher.ZERO_CREDIT,
    })
    resource_snapshot = admission.resource.probe_resource_admission(
        2,
        root=root,
        gpu_rows={2: {"total_mib": 49152, "used_mib": 1024, "free_mib": 48128}},
        cpu_count=16,
        load_1m=1.0,
        tmp_free_bytes=16 * 1024**3,
        root_free_bytes=16 * 1024**3,
    )
    gpu = resource_snapshot["gpu"]
    gpu.update({
        "physical_index": 2,
        "uuid": "GPU-12345678-90ab-cdef-1234-567890abcdef",
        "pci_bus_id": "0000:65:00.0",
        "logical_index": 0,
        "cuda_visible_devices": "2",
        "cuda_device": "cuda:0",
        "cuda_device_order": "PCI_BUS_ID",
        "identity_source": "scheduler_owned_snapshot",
        "identity_attested": True,
    })
    gpu["identity_sha256"] = admission.canonical_digest(admission._gpu_identity(gpu))
    resource_snapshot["owner"] = {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "host": admission.CURRENT_HOST,
        "scope": "scheduler_owned_diagnostic_snapshot",
        "snapshot_nonce": "b" * 32,
    }
    (tmp_path / "output").mkdir()
    receipt = admission.mint_admission(
        root,
        manifest=manifest,
        training_receipt=training,
        checkpoint=checkpoint,
        nonce="a" * 32,
        output_root=tmp_path / "output",
        resource_admission=resource_snapshot,
    )
    return {"root": root, "receipt": Path(receipt["receipt_path"]), "resource": resource_snapshot}


def test_default_runner_is_dry_run_and_never_reaches_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("dry-run must not call Popen")

    monkeypatch.setattr(runner, "_REAL_POPEN", forbidden)
    report = runner.build_report(fixture["receipt"])
    assert runner.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["popen_attempted"] is False
    assert report["wait_attempted"] is False
    assert report["real_workload_started"] == 0
    assert report["diagnostic_execute_allowed"] is False
    assert calls == []
    assert not Path(fixture["receipt"]).parent.joinpath(".diagnostic-admission-consumed").exists()


def test_diagnostic_execute_flag_is_explicitly_blocked_and_does_not_consume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)

    def forbidden_consume(*args: object, **kwargs: object) -> None:
        raise AssertionError("blocked execution must not consume the receipt")

    def forbidden_popen(*args: object, **kwargs: object) -> None:
        raise AssertionError("blocked execution must not call Popen")

    monkeypatch.setattr(runner.admission, "consume_receipt", forbidden_consume)
    monkeypatch.setattr(runner, "_REAL_POPEN", forbidden_popen)
    report = runner.build_report(fixture["receipt"], execute_requested=True)
    assert runner.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["execute_requested"] is True
    assert report["popen_attempted"] is False
    assert report["wait_attempted"] is False
    assert report["real_workload_started"] == 0
    assert len(report["blocked_reasons"]) == 8
    assert not Path(fixture["receipt"]).parent.joinpath(".diagnostic-admission-consumed").exists()


def test_execute_api_has_no_authorizing_capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    monkeypatch.setattr(runner, "_REAL_POPEN", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Popen forbidden")))
    with pytest.raises(runner.RunnerError, match="not admitted"):
        runner.execute_diagnostic(plan, object())


def test_runner_accepts_only_diagnostic_execute_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        runner._parse_args(["--execute"])
    parsed = runner._parse_args(["--diagnostic-execute"])
    assert parsed.diagnostic_execute is True


def test_source_drift_fails_closed_before_any_runtime_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    root = Path(fixture["root"])
    (root / admission.SOURCE_RELATIVE_PATHS["hdf5_validator"]).write_text("# drift\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_REAL_POPEN", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Popen forbidden")))
    report = runner.build_report(fixture["receipt"], execute_requested=True)
    assert runner.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["popen_attempted"] is False


def test_report_verify_cli_accepts_blocked_contract(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = runner.build_report(fixture["receipt"], execute_requested=True)
    report_path = tmp_path / "runner-v2-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert runner.main(["--verify-report", str(report_path)]) == 0


def test_plan_binds_complete_allowlist_environment_and_stable_inputs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    assert plan.effective_env_sha256 == runner._environment_digest(dict(plan.env))
    assert set(plan.effective_env_keys) == {
        "CUDA_VISIBLE_DEVICES",
        "CUDA_DEVICE_ORDER",
        "PYTHONDONTWRITEBYTECODE",
    }
    assert plan.binding_sha256 == runner._binding_digest(plan)
    for descriptor in (*plan.input_descriptors.values(), plan.executable_descriptor, plan.cwd_descriptor):
        assert descriptor["stable_fd"] is True
        assert descriptor["fd_identity_stable"] is True
        assert descriptor["path_reopened"] is False


def test_future_real_popen_path_is_still_unreachable_without_calling_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("bounded runner must not call Popen")

    monkeypatch.setattr(runner, "_SEALED_POPEN", forbidden)
    with pytest.raises(runner.RunnerError, match="not admitted"):
        runner._run_real_popen_wait(plan, object())
    assert calls == []


def test_external_process_witness_and_caller_constructor_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    with pytest.raises(TypeError, match="internal real-Popen witness"):
        runner._SealedProcessWitness(object())
    with pytest.raises(runner.RunnerError, match="internal sealed real Popen/wait witness"):
        runner._validate_process_witness(plan, {"pid": 1, "returncode": 0})


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_stable_artifact_rejects_symlink_and_hardlink(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    source = root / "source.bin"
    source.write_bytes(b"stable artifact")
    candidate = root / f"{kind}.bin"
    if kind == "symlink":
        candidate.symlink_to(source)
    else:
        os.link(source, candidate)
    with pytest.raises(runner.RunnerError, match="symlink|hard link"):
        runner._stable_artifact(candidate, root, kind, max_bytes=1024)


def _write_minimal_trajectory(path: Path, *, unsafe_link: bool = False) -> None:
    with h5py.File(path, "w") as handle:
        for name in ("time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"):
            handle.create_dataset(name, data=[0])
        if unsafe_link:
            handle["unsafe"] = h5py.SoftLink("time")


def test_terminal_hdf5_receipt_is_snapshot_bound_and_zero_credit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    trajectory = plan.outputs["trajectory"]
    _write_minimal_trajectory(trajectory)
    descriptor, raw = runner._secure_artifact(trajectory, plan.namespace.parent, "trajectory", max_bytes=runner.MAX_HDF5_BYTES)
    receipt = runner._terminal_hdf5_receipt(plan, trajectory, descriptor, raw)
    assert receipt["synthetic_only"] is False
    assert receipt["stable_fd"] is True
    assert receipt["path_reopened"] is False
    assert receipt["sha256"] == descriptor["sha256"]
    for key, expected in runner.ZERO_CREDIT.items():
        assert receipt[key] == expected


def test_terminal_hdf5_receipt_rejects_unsafe_hdf5_links(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = runner.build_plan(fixture["receipt"], resource_admission=fixture["resource"])
    trajectory = plan.outputs["trajectory"]
    _write_minimal_trajectory(trajectory, unsafe_link=True)
    descriptor, raw = runner._secure_artifact(trajectory, plan.namespace.parent, "trajectory", max_bytes=runner.MAX_HDF5_BYTES)
    with pytest.raises((runner.RunnerError, ValueError), match="link|HDF5"):
        runner._terminal_hdf5_receipt(plan, trajectory, descriptor, raw)


def test_report_keeps_formal_and_credit_isolation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = runner.build_report(fixture["receipt"], execute_requested=True)
    assert report["status"] == "blocked_fail_closed"
    assert runner.validate_report(report) == []
    for key, expected in runner.ZERO_CREDIT.items():
        assert report[key] == expected
    forged = copy.deepcopy(report)
    forged["credit"] = 1
    assert runner.validate_report(forged)
