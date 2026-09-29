"""Fail-closed tests for the residual seed29 admission boundary.

The scheduler fixture is synthetic and local.  It supplies an Ed25519
authority only to exercise signature verification; no process, CUDA workload,
formal registry, gate, or production scheduler is started.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 as admission

identity = admission.identity


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


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


def _training_fixture(tmp_path: Path) -> tuple[Path, Path]:
    checkpoint = tmp_path / f"{admission.RUN_ID}-checkpoint.pt"
    checkpoint_raw = b"residual seed29 checkpoint fixture"
    checkpoint.write_bytes(checkpoint_raw)
    training = tmp_path / f"{admission.RUN_ID}-training.json"
    config = dict(launcher.STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": launcher.CURRENT_CANONICAL_MANIFEST_SHA256,
            "paired_seed": admission.SEED,
            "run_id": admission.RUN_ID,
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
        "run_id": admission.RUN_ID,
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
                "parameter_digest": _sha(b"parameter-29"),
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
    return training, checkpoint


def _configure_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Ed25519PrivateKey]:
    scheduler_root = tmp_path / "scheduler"
    (scheduler_root / "authority").mkdir(parents=True)
    (scheduler_root / "claims").mkdir()
    key_path = scheduler_root / "scheduler-ed25519-public.key"
    private = Ed25519PrivateKey.generate()
    key_path.write_bytes(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    key_path.chmod(0o600)
    monkeypatch.setattr(admission, "EXTERNAL_SCHEDULER_ROOT", scheduler_root)
    monkeypatch.setattr(admission, "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH", key_path)
    return scheduler_root, key_path, private


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nonce: str) -> dict[str, object]:
    if not admission.DEFAULT_MANIFEST.is_file():
        pytest.skip("tracked current manifest is unavailable")
    scheduler_root, key_path, private = _configure_scheduler(tmp_path, monkeypatch)
    training, checkpoint = _training_fixture(tmp_path)
    root = admission.LAB_ROOT
    python = Path(sys.executable).resolve()
    namespace = admission._namespace(tmp_path, nonce)
    namespace_desc = admission._mkdir_exclusive(namespace)
    resource = _resource()
    manifest_raw, manifest_desc, manifest_payload = admission._read_bound(
        admission.DEFAULT_MANIFEST, "manifest", max_bytes=admission.MAX_JSON_BYTES, parse_json=True
    )
    del manifest_raw
    assert manifest_payload is not None
    manifest_binding = launcher._manifest_binding(manifest_payload, manifest_desc, path=admission.DEFAULT_MANIFEST)
    training_raw, training_desc, training_payload = admission._read_bound(
        training, "training", max_bytes=admission.MAX_JSON_BYTES, parse_json=True
    )
    del training_raw
    assert training_payload is not None
    training_binding = identity._validate_current_training_receipt(
        training_payload,
        training_desc,
        receipt_path=training,
        checkpoint_path=checkpoint,
        seed=admission.SEED,
        run_id=admission.RUN_ID,
        manifest_sha256=manifest_binding["canonical_sha256"],
    )
    checkpoint_desc = admission._file_descriptor(checkpoint, "checkpoint", max_bytes=admission.MAX_CHECKPOINT_BYTES)
    outputs = launcher._output_paths(namespace, root, admission.SEED, nonce)
    command = launcher._build_command(
        root=root,
        python=python,
        manifest=admission.DEFAULT_MANIFEST,
        checkpoint=checkpoint,
        outputs=outputs,
    )
    env = {
        "CUDA_VISIBLE_DEVICES": str(admission.GPU_INDEX),
        "CUDA_DEVICE_ORDER": admission.CUDA_DEVICE_ORDER,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    manifest_plan = {"path": str(admission.DEFAULT_MANIFEST), "binding": manifest_binding, "file": manifest_desc}
    training_plan = {"path": str(training), "binding": training_binding, "file": training_desc}
    checkpoint_plan = {**training_binding["checkpoint"], "file": checkpoint_desc}
    plan = admission._plan_binding(
        root=root,
        manifest=manifest_plan,
        training=training_plan,
        checkpoint=checkpoint_plan,
        namespace=namespace,
        outputs=outputs,
        command=command,
        env=env,
        nonce=nonce,
    )
    consume_path = scheduler_root / "claims" / f"{nonce}.json"
    unsigned_without_id = {
        "schema": admission.EXTERNAL_AUTHORITY_SCHEMA,
        "state": "issued",
        "one_shot": True,
        "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST},
        "scheduler": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST, "role": "external_scheduler"},
        "namespace": namespace_desc,
        "nonce": nonce,
        "plan_sha256": admission.canonical_digest(plan),
        "resource_snapshot_sha256": admission.canonical_digest(resource),
        "gpu": dict(resource["gpu"]),
        "gpu_identity_sha256": admission.canonical_digest(admission._gpu_identity(resource["gpu"])),
        "consume_path": str(consume_path),
        "key_id": _sha(key_path.read_bytes()),
        "signature_algorithm": "ed25519",
    }
    authority_id = admission.canonical_digest(unsigned_without_id)
    unsigned = {"authority_id": authority_id, **unsigned_without_id}
    signature = private.sign(admission._authority_signing_message(unsigned))
    authority = {**unsigned, "signature_base64": base64.b64encode(signature).decode("ascii")}
    authority_path = scheduler_root / "authority" / f"{nonce}.json"
    _write_json(authority_path, authority)
    return {
        "root": root,
        "manifest": admission.DEFAULT_MANIFEST,
        "training": training,
        "checkpoint": checkpoint,
        "python": python,
        "resource": resource,
        "namespace": namespace,
        "authority": authority_path,
        "scheduler_root": scheduler_root,
        "plan": plan,
    }


def _mint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nonce: str = "a" * 32) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _fixture(tmp_path, monkeypatch, nonce)
    receipt = admission.mint_admission(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_root=tmp_path,
        resource_admission=fixture["resource"],
        python_executable=fixture["python"],
        external_authority=fixture["authority"],
    )
    return receipt, fixture


def test_admission_binds_residual_seed29_and_external_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, fixture = _mint(tmp_path, monkeypatch)
    assert admission.validate_receipt(receipt) == []
    assert receipt["identity"]["seed"] == 29
    assert receipt["identity"]["gpu"]["physical_index"] == 5
    assert receipt["identity"]["model_kind"] == "graph_residual"
    assert receipt["identity"]["hidden"] == 16
    assert receipt["identity"]["transitions"] == 835
    assert receipt["identity"]["frames"] == 836
    assert receipt["identity"]["external_authority"]["path"] == str(fixture["authority"])
    assert receipt["credit"] == 0
    assert receipt["terminal_receipt_minting"] is False
    assert Path(receipt["namespace"]).stat().st_mode & 0o777 == 0o700


def test_receipt_consumption_requires_independent_claim_and_is_one_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, fixture = _mint(tmp_path, monkeypatch, nonce="b" * 32)
    capability = admission.consume_receipt(Path(receipt["receipt_path"]))
    assert capability.as_dict()["popen_authorized"] is False
    assert capability.as_dict()["external_claim_path"] == str(fixture["scheduler_root"] / "claims" / ("b" * 32 + ".json"))
    assert capability.consumed_marker.is_file()
    with pytest.raises(admission.AdmissionError, match="already been consumed"):
        admission.consume_receipt(Path(receipt["receipt_path"]))


def test_missing_resource_or_external_authority_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch, "c" * 32)
    with pytest.raises(admission.AdmissionError, match="scheduler-owned GPU"):
        admission.mint_admission(
            fixture["root"],
            manifest=fixture["manifest"],
            training_receipt=fixture["training"],
            checkpoint=fixture["checkpoint"],
            nonce="c" * 32,
            output_root=tmp_path,
            resource_admission=None,
            python_executable=fixture["python"],
            external_authority=fixture["authority"],
        )
    with pytest.raises(admission.AdmissionError, match="external scheduler authority is required"):
        admission.mint_admission(
            fixture["root"],
            manifest=fixture["manifest"],
            training_receipt=fixture["training"],
            checkpoint=fixture["checkpoint"],
            nonce="c" * 32,
            output_root=tmp_path,
            resource_admission=fixture["resource"],
            python_executable=fixture["python"],
        )


def test_authority_signature_and_bound_input_drift_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, fixture = _mint(tmp_path, monkeypatch, nonce="d" * 32)
    authority = json.loads(Path(fixture["authority"]).read_text())
    authority["plan_sha256"] = "0" * 64
    _write_json(Path(fixture["authority"]), authority)
    with pytest.raises(admission.AdmissionError, match="signature verification|plan"):
        admission.revalidate_receipt(receipt)

    receipt2, fixture2 = _mint(tmp_path / "second", monkeypatch, nonce="e" * 32)
    Path(fixture2["checkpoint"]).write_bytes(b"drift")
    with pytest.raises(admission.AdmissionError, match="checkpoint"):
        admission.revalidate_receipt(receipt2)


def test_report_without_receipt_is_blocked_without_side_effects() -> None:
    report = admission.build_report(None)
    assert report["status"] == "blocked_fail_closed"
    assert report["receipt_valid"] is False
    assert report["terminal_receipt_minted"] is False
    assert report["credit"] == 0
    assert admission.validate_report(report) == []
