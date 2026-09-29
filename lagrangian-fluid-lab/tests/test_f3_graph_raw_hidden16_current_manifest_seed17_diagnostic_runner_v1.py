"""Focused fail-closed tests for the single-seed diagnostic runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import h5py
import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_seed17_diagnostic_runner_v1 as runner


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return raw


def _admission(root: Path, *, admitted: bool = True) -> dict[str, object]:
    probe_errors = () if admitted else ("synthetic blocked admission",)
    return runner.admission.probe_resource_admission(
        runner.GPU_INDEX,
        root=root,
        gpu_rows={runner.GPU_INDEX: {"total_mib": 49152, "used_mib": 1024, "free_mib": 48128}},
        cpu_count=16,
        load_1m=1.0,
        tmp_free_bytes=16 * 1024**3,
        root_free_bytes=16 * 1024**3,
        probe_errors=probe_errors,
    )


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    (root / "scripts" / "core_learning.py").write_text("# bounded fixture\n", encoding="utf-8")

    manifest_payload = {
        "schema": runner.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "1" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    _write_json(manifest, manifest_payload)
    manifest_sha = runner.launcher.canonical_digest(manifest_payload)

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    checkpoint = inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint_raw = b"checkpoint metadata fixture; runner never opens this content"
    checkpoint.write_bytes(checkpoint_raw)
    checkpoint_meta = {
        "schema": runner.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": _sha_bytes(checkpoint_raw),
        "bytes": len(checkpoint_raw),
        "update": runner.UPDATES,
    }
    training = inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
    receipt = {
        "schema": runner.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": runner.MODEL,
        "seed": runner.SEED,
        "run_id": "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3",
        "completed_updates": runner.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": manifest_sha,
            "model_kind": runner.MODEL,
            "hidden": runner.HIDDEN,
            "updates": runner.UPDATES,
            "run_id": "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3",
            "seed": runner.SEED,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **runner.launcher.ZERO_CREDIT,
    }
    training_raw = _write_json(training, receipt)
    return {
        "root": root,
        "manifest": manifest,
        "training": training,
        "training_raw": training_raw,
        "checkpoint": checkpoint,
        "admission": _admission(root),
    }


def _plan(fixture: dict[str, object], tmp_path: Path, nonce: str = "a" * 32) -> runner.DiagnosticPlan:
    return runner.build_plan(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_root=tmp_path,
        resource_admission=fixture["admission"],
    )


def test_dry_run_reserves_one_namespace_and_binds_exact_gpu2_command(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path)
    assert plan.identity_plan.seed == runner.SEED
    assert plan.identity_plan.command[3] == "evaluate"
    assert plan.identity_plan.command[15] == str(runner.TRANSITIONS)
    assert plan.identity_plan.command[-1] == "--diagnostic"
    assert plan.identity_plan.command[19] == "cuda:0"
    assert plan.identity_plan.env["CUDA_VISIBLE_DEVICES"] == "2"
    assert plan.reservation.namespace.is_dir()
    assert plan.reservation.marker.is_file()
    assert plan.input_snapshots["checkpoint"]["content_opened"] is False
    assert plan.input_snapshots["training_receipt"]["content_opened"] is True


def test_build_report_is_zero_credit_and_never_launches(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = runner.build_report(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce="b" * 32,
        output_root=tmp_path,
        resource_admission=fixture["admission"],
    )
    assert runner.validate_report(report) == []
    assert report["status"] == "dry_run_ready"
    assert report["launch_allowed"] is False
    assert report["real_workload_started"] == 0
    assert report["popen_attempted"] is False
    assert report["terminal_receipt"] is None
    assert report["credit"] == 0


def test_execute_rejects_fake_popen_before_any_call(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="c" * 32)
    calls: list[object] = []

    def fake_popen(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    with pytest.raises(runner.RunnerError, match="fake, or injected Popen"):
        runner.execute_diagnostic(plan, popen_factory=fake_popen)
    assert calls == []


def test_execute_rejects_before_real_popen_when_capability_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="d" * 32)
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("real Popen must not be reached")

    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    with pytest.raises(runner.RunnerError, match="capability is not admitted"):
        runner.execute_diagnostic(plan)
    assert calls == []


def test_execute_rejects_caller_capability_without_side_effect(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="e" * 32)
    with pytest.raises(runner.RunnerError, match="capability is not admitted"):
        runner.execute_diagnostic(plan, capability=object())
    assert not list(plan.identity_plan.namespace.glob("*-evaluation.json"))


def test_input_snapshot_drift_is_fail_closed_before_future_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path, nonce="f" * 32)
    training = Path(fixture["training"])
    training.write_bytes(bytes(fixture["training_raw"]) + b" ")
    with pytest.raises(runner.RunnerError, match="capability is not admitted"):
        runner.execute_diagnostic(plan)
    # The capability gate is intentionally checked before any future Popen
    # path; the changed input remains outside the execution side effect path.
    assert not list(plan.identity_plan.namespace.glob("*-trajectory.h5"))


def test_report_rejects_authorizing_mutations_and_wrong_gpu(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = runner.build_report(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce="1" * 32,
        output_root=tmp_path,
        resource_admission=fixture["admission"],
    )
    forged = json.loads(json.dumps(report))
    forged["env_overrides"]["CUDA_VISIBLE_DEVICES"] = "3"
    assert runner.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["side_effects"]["registry_writes"] = 1
    assert runner.validate_report(forged)


def test_blocked_gpu_admission_remains_dry_run_and_zero_workload(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    blocked = _admission(fixture["root"], admitted=False)
    report = runner.build_report(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce="2" * 32,
        output_root=tmp_path,
        resource_admission=blocked,
    )
    assert runner.validate_report(report) == []
    assert report["resource_admission"]["admitted"] is False
    assert report["launch_allowed"] is False
    assert report["real_workload_started"] == 0


def test_hardened_hdf5_checks_reject_soft_links_without_runtime(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("safe", data=[1])
        handle["unsafe"] = h5py.SoftLink("/safe")
    with pytest.raises(runner.RunnerError, match="unsafe link"):
        runner._hardened_hdf5_checks(path.read_bytes())


def test_hardened_hdf5_checks_reject_external_links_without_runtime(tmp_path: Path) -> None:
    path = tmp_path / "external.h5"
    with h5py.File(path, "w") as handle:
        handle["external"] = h5py.ExternalLink("outside.h5", "/dataset")
    with pytest.raises(runner.RunnerError, match="unsafe link"):
        runner._hardened_hdf5_checks(path.read_bytes())
