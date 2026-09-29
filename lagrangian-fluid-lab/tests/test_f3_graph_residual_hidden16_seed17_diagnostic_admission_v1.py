"""Fail-closed tests for the residual seed17 admission boundary.

The fixture uses the tracked current manifest and temporary training inputs.
It never launches a process, touches CUDA, or creates a terminal receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity
from scripts import f3_graph_residual_hidden16_seed17_diagnostic_admission_v1 as admission


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")


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
        "snapshot_nonce": "b" * 32,
    }
    return value


def _fixture(tmp_path: Path) -> dict[str, object]:
    if not admission.DEFAULT_MANIFEST.is_file():
        pytest.skip("tracked current manifest is unavailable")
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_id = admission.RUN_ID
    checkpoint = tmp_path / f"{run_id}-checkpoint.pt"
    checkpoint_raw = b"residual seed17 checkpoint fixture"
    checkpoint.write_bytes(checkpoint_raw)
    training = tmp_path / f"{run_id}-training.json"
    config = dict(launcher.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": launcher.CURRENT_CANONICAL_MANIFEST_SHA256,
            "paired_seed": admission.SEED,
            "run_id": run_id,
            "sampler_seed": admission.SEED,
            "seed": admission.SEED,
        }
    )
    payload = {
        "schema": launcher.TRAINING_SCHEMA,
        "status": "completed",
        "evidence_status": "complete",
        "model_kind": launcher.MODEL,
        "seed": admission.SEED,
        "run_id": run_id,
        "completed_updates": launcher.UPDATES,
        "parameter_count": launcher.PARAMETER_COUNT,
        "checkpoint_verified": True,
        "checkpoint": {
            "schema": launcher.CHECKPOINT_SCHEMA,
            "path": str(checkpoint),
            "sha256": _sha(checkpoint_raw),
            "bytes": len(checkpoint_raw),
            "update": launcher.UPDATES,
        },
        "config": config,
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": "core.training.initialization_evidence.v1",
                "status": "captured",
                "model_kind": launcher.MODEL,
                "hidden": launcher.HIDDEN,
                "parameter_count": launcher.PARAMETER_COUNT,
                "seed": admission.SEED,
                "constructed_before_first_update": True,
                "parameter_digest": _sha(b"parameter-17"),
            },
            "normalization": {
                "schema": "core.training.normalization_evidence.v1",
                "requested_maximum_transitions": 16,
                "selected_transition_count": 16,
                "selection_seed": admission.SEED,
                "source_split": "train",
                "target_reference": "raw_dual_increment_train_shared",
            },
            "residual_prior": {
                "schema": "core.training.prior_evidence.v1",
                "enabled": True,
                "history_complete": True,
                "execution_calls": launcher.UPDATES,
                "rows": 17_280_000,
                "finite": True,
            },
        },
        **launcher.ZERO_CREDIT,
    }
    _write_json(training, payload)
    return {
        "root": admission.LAB_ROOT,
        "manifest": admission.DEFAULT_MANIFEST,
        "training": training,
        "checkpoint": checkpoint,
        "python": Path(sys.executable).resolve(),
        "resource": _resource(),
    }


def _mint(tmp_path: Path, *, nonce: str = "a" * 32) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _fixture(tmp_path)
    receipt = admission.mint_admission(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_root=tmp_path,
        resource_admission=fixture["resource"],
        python_executable=fixture["python"],
    )
    return receipt, fixture


def test_admission_binds_residual_identity_and_stays_zero_credit(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path)
    assert admission.validate_receipt(receipt) == []
    assert receipt["identity"]["seed"] == 17
    assert receipt["identity"]["model_kind"] == "graph_residual"
    assert receipt["identity"]["transitions"] == 835
    assert receipt["identity"]["frames"] == 836
    assert set(receipt["identity"]["source_files"]) == set(admission.SOURCE_RELATIVE_PATHS)
    assert receipt["identity"]["command"]["env_overrides"] == {
        "CUDA_VISIBLE_DEVICES": "4",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert receipt["diagnostic_execute_only"] is True
    assert receipt["terminal_receipt_minting"] is False
    assert receipt["credit"] == 0
    namespace = Path(receipt["namespace"])
    assert namespace.stat().st_mode & 0o777 == 0o700
    assert (namespace / admission.NAMESPACE_MARKER).is_file()


def test_receipt_consumption_is_atomic_and_one_shot(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path, nonce="b" * 32)
    receipt_path = Path(receipt["receipt_path"])
    capability = admission.consume_receipt(receipt_path)
    assert capability.receipt_path == receipt_path
    assert capability.as_dict()["popen_authorized"] is False
    assert capability.as_dict()["launch_allowed"] is False
    assert capability.lock_path.is_file()
    assert capability.consumed_marker.is_file()
    with pytest.raises(admission.AdmissionError, match="already been consumed"):
        admission.consume_receipt(receipt_path)


def test_source_checkpoint_and_gpu_identity_drift_fail_closed(tmp_path: Path) -> None:
    receipt, fixture = _mint(tmp_path, nonce="c" * 32)
    forged_source = dict(receipt)
    forged_identity = dict(forged_source["identity"])
    forged_files = dict(forged_identity["source_files"])
    forged_core = dict(forged_files["core_learning"])
    forged_core["mtime_ns"] = int(forged_core["mtime_ns"]) + 1
    forged_files["core_learning"] = forged_core
    forged_identity["source_files"] = forged_files
    forged_source["identity"] = forged_identity
    forged_source["identity_sha256"] = admission.canonical_digest(forged_identity)
    with pytest.raises(admission.AdmissionError, match="receipt digest|source.core_learning identity drifted"):
        admission.revalidate_receipt(forged_source)

    receipt2, fixture2 = _mint(tmp_path / "second", nonce="d" * 32)
    forged = dict(receipt2)
    forged_identity = dict(forged["identity"])
    forged_resource = dict(forged_identity["resource_admission"])
    forged_gpu = dict(forged_resource["gpu"])
    forged_gpu["uuid"] = "GPU-fedcba98-7654-3210-fedc-ba9876543210"
    forged_gpu["identity_sha256"] = admission.canonical_digest(admission._gpu_identity(forged_gpu))
    forged_resource["gpu"] = forged_gpu
    forged_identity["resource_admission"] = forged_resource
    forged["identity"] = forged_identity
    forged["identity_sha256"] = admission.canonical_digest(forged_identity)
    with pytest.raises(admission.AdmissionError, match="resource|receipt digest"):
        admission.revalidate_receipt(forged)
    assert fixture2["checkpoint"].is_file()


def test_unknown_or_duplicate_json_is_rejected_before_authority(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path, nonce="e" * 32)
    forged = dict(receipt)
    forged["unexpected"] = True
    assert admission.validate_receipt(forged)

    path = Path(receipt["receipt_path"])
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"status":"admission_issued"', b'"status":"admission_issued","status":"admission_issued"', 1))
    with pytest.raises(admission.AdmissionError, match="duplicate"):
        admission.load_receipt(path)


def test_default_report_is_blocked_without_implicit_receipt(tmp_path: Path) -> None:
    report = admission.build_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["receipt_valid"] is False
    assert report["popen_attempted"] is False
    assert report["terminal_receipt_minted"] is False
    assert admission.validate_report(report) == []
