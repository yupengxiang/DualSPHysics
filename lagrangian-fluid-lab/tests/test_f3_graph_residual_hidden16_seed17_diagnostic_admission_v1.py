"""Fail-closed tests for the residual seed17 admission boundary.

The signed scheduler document below is a synthetic test fixture only.  It is
never a production scheduler authority and no test starts CUDA or a process.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity
from scripts import f3_graph_residual_hidden16_seed17_diagnostic_admission_v1 as admission


_TEST_SCHEDULER_KEY: Ed25519PrivateKey | None = None


@pytest.fixture(autouse=True)
def _synthetic_scheduler_trust_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use an isolated test trust root; never install a production authority."""

    global _TEST_SCHEDULER_KEY
    scheduler_root = tmp_path / "scheduler-ledger"
    scheduler_root.mkdir(mode=0o700)
    key_root = tmp_path / "scheduler-trust"
    key_root.mkdir(mode=0o700)
    key_path = key_root / "scheduler-ed25519-public.key"
    _TEST_SCHEDULER_KEY = Ed25519PrivateKey.generate()
    key_path.write_bytes(_TEST_SCHEDULER_KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    key_path.chmod(0o600)
    monkeypatch.setattr(admission, "EXTERNAL_SCHEDULER_ROOT", scheduler_root)
    monkeypatch.setattr(admission, "TRUSTED_SCHEDULER_PUBLIC_KEY_PATH", key_path)
    yield
    _TEST_SCHEDULER_KEY = None


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
        "snapshot_nonce": "a" * 32,
    }
    return value


def _fixture(tmp_path: Path) -> dict[str, object]:
    if not admission.DEFAULT_MANIFEST.is_file() or not admission.DEFAULT_TRAINING.is_file() or not admission.DEFAULT_CHECKPOINT.is_file():
        pytest.skip("current residual seed17 training evidence is unavailable")
    output_root = tmp_path / "admission-output"
    output_root.mkdir(parents=True)
    python = tmp_path / "regular-python"
    shutil.copyfile(Path(sys.executable).resolve(), python)
    python.chmod(0o755)
    return {
        "root": admission.LAB_ROOT,
        "manifest": admission.DEFAULT_MANIFEST,
        "training": admission.DEFAULT_TRAINING,
        "checkpoint": admission.DEFAULT_CHECKPOINT,
        "python": python,
        "resource": _resource(),
        "output_root": output_root,
    }


def _namespace(fixture: dict[str, object], nonce: str) -> Path:
    output_root = Path(fixture["output_root"])
    namespace = output_root / f"f3-graph-residual500-hidden16-currentmanifest-seed17-full835-nonce{nonce}"
    namespace.mkdir(mode=0o700)
    return namespace


def _write_external_authority(fixture: dict[str, object], nonce: str) -> Path:
    key = _TEST_SCHEDULER_KEY
    assert key is not None
    namespace = _namespace(fixture, nonce)
    plan = admission._build_reserved_plan(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        namespace=namespace,
        gpu_index=admission.GPU_INDEX,
        python_executable=fixture["python"],
    )
    namespace_descriptor = admission._existing_namespace_descriptor(namespace)
    authority_id = hashlib.sha256(f"synthetic-residual-seed17:{namespace}".encode()).hexdigest()
    scheduler_root = Path(admission.EXTERNAL_SCHEDULER_ROOT)
    authority_path = scheduler_root / f"{authority_id}.authority.json"
    consume_path = scheduler_root / f"{authority_id}.claim.json"
    public_key = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    gpu = admission._gpu_identity(fixture["resource"]["gpu"])
    unsigned = {
        "schema": admission.EXTERNAL_AUTHORITY_SCHEMA,
        "authority_id": authority_id,
        "state": "issued",
        "one_shot": True,
        "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST},
        "scheduler": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST, "role": "external_scheduler"},
        "namespace": namespace_descriptor,
        "nonce": nonce,
        "plan_sha256": admission._plan_binding_digest(plan),
        "resource_snapshot_sha256": admission.canonical_digest(fixture["resource"]),
        "gpu": gpu,
        "gpu_identity_sha256": admission.canonical_digest(gpu),
        "consume_path": str(consume_path),
        "key_id": hashlib.sha256(public_key).hexdigest(),
        "signature_algorithm": "ed25519",
    }
    document = {**unsigned, "signature_base64": base64.b64encode(key.sign(admission._authority_signing_message(unsigned))).decode("ascii")}
    _write_json(authority_path, document)
    authority_path.chmod(0o600)
    return authority_path


def _mint(tmp_path: Path, nonce: str = "a" * 32) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _fixture(tmp_path)
    authority = _write_external_authority(fixture, nonce)
    receipt = admission.mint_admission(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_root=fixture["output_root"],
        resource_admission=fixture["resource"],
        external_authority=authority,
        python_executable=fixture["python"],
    )
    fixture["authority"] = authority
    return receipt, fixture


def test_receipt_binds_residual_seed17_and_stays_zero_credit(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path)
    assert admission.validate_receipt(receipt) == []
    identity_core = receipt["identity"]
    assert identity_core["seed"] == 17
    assert identity_core["model_kind"] == "graph_residual"
    assert identity_core["transitions"] == 835
    assert identity_core["frames"] == 836
    assert set(identity_core["source_sha256"]) == set(admission.SOURCE_RELATIVE_PATHS)
    assert identity_core["command"]["env_overrides"] == {
        "CUDA_VISIBLE_DEVICES": "4",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert receipt["diagnostic_execute_only"] is True
    assert receipt["terminal_receipt_minting"] is False
    assert receipt["credit"] == 0
    assert Path(receipt["identity"]["namespace"]).is_dir()
    assert Path(receipt["namespace_marker"]["path"]).stat().st_mode & 0o777 == 0o600


def test_external_authority_is_required_and_consumption_is_one_shot(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(admission.AdmissionError, match="external scheduler authority is required"):
        admission.mint_admission(
            fixture["root"], manifest=fixture["manifest"], training_receipt=fixture["training"],
            checkpoint=fixture["checkpoint"], nonce="b" * 32, output_root=fixture["output_root"],
            resource_admission=fixture["resource"], python_executable=fixture["python"],
        )
    receipt, _fixture_data = _mint(tmp_path / "with-authority", nonce="c" * 32)
    receipt_path = Path(receipt["receipt_path"])
    capability = admission.consume_receipt(receipt_path)
    assert capability.as_dict()["popen_authorized"] is False
    assert capability.as_dict()["launch_allowed"] is False
    assert capability.external_claim_path.is_file()
    assert capability.consumed_marker.is_file()
    with pytest.raises(admission.AdmissionError, match="already been consumed"):
        admission.consume_receipt(receipt_path)


def test_authority_signature_command_and_source_drift_fail_closed(tmp_path: Path) -> None:
    receipt, fixture = _mint(tmp_path, nonce="d" * 32)
    authority_path = Path(fixture["authority"])
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["nonce"] = "e" * 32
    authority_path.write_text(json.dumps(authority, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(admission.AdmissionError, match="signature verification|descriptor drifted|nonce"):
        admission.load_receipt(Path(receipt["receipt_path"]))

    forged = copy.deepcopy(receipt)
    forged["identity"]["command"]["argv"][-1] = "--formal"
    assert admission.validate_receipt(forged, check_files=False)


def test_resource_and_authority_are_not_implicit_or_promotable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = admission.build_report(
        fixture["root"], manifest=fixture["manifest"], training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"], nonce="f" * 32, output_root=fixture["output_root"],
        resource_admission=fixture["resource"],
    )
    assert admission.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["popen_attempted"] is False
    assert report["credit"] == 0
    with pytest.raises(admission.AdmissionError, match="implicit probing is disabled"):
        admission.mint_admission(
            fixture["root"], manifest=fixture["manifest"], training_receipt=fixture["training"],
            checkpoint=fixture["checkpoint"], nonce="1" * 32, output_root=fixture["output_root"],
        )
