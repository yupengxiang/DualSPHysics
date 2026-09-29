"""Fail-closed tests for the residual seed17 secure runner v2."""

from __future__ import annotations

import base64
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
from scripts import f3_graph_residual_hidden16_seed17_diagnostic_runner_v2 as runner


_TEST_SCHEDULER_KEY: Ed25519PrivateKey | None = None


@pytest.fixture(autouse=True)
def _synthetic_scheduler_trust_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use only a temporary signed fixture; this is not a production scheduler."""

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
    gpu.update({
        "physical_index": admission.GPU_INDEX,
        "uuid": "GPU-12345678-90ab-cdef-1234-567890abcdef",
        "pci_bus_id": "0000:65:00.0",
        "logical_index": 0,
        "cuda_visible_devices": str(admission.GPU_INDEX),
        "cuda_device": "cuda:0",
        "cuda_device_order": admission.CUDA_DEVICE_ORDER,
        "identity_source": "scheduler_owned_snapshot",
        "identity_attested": True,
    })
    gpu["identity_sha256"] = admission.canonical_digest(admission._gpu_identity(gpu))
    value["owner"] = {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST, "scope": "scheduler_owned_diagnostic_snapshot", "snapshot_nonce": "a" * 32}
    return value


def _fixture(tmp_path: Path) -> dict[str, object]:
    if not admission.DEFAULT_MANIFEST.is_file() or not admission.DEFAULT_TRAINING.is_file() or not admission.DEFAULT_CHECKPOINT.is_file():
        pytest.skip("current residual seed17 training evidence is unavailable")
    output_root = tmp_path / "admission-output"
    output_root.mkdir(parents=True, exist_ok=True)
    python = tmp_path / "regular-python"
    shutil.copyfile(Path(sys.executable).resolve(), python)
    python.chmod(0o755)
    return {"root": admission.LAB_ROOT, "manifest": admission.DEFAULT_MANIFEST, "training": admission.DEFAULT_TRAINING, "checkpoint": admission.DEFAULT_CHECKPOINT, "python": python, "resource": _resource(), "output_root": output_root}


def _authority(fixture: dict[str, object], nonce: str) -> Path:
    key = _TEST_SCHEDULER_KEY
    assert key is not None
    namespace = Path(fixture["output_root"]) / f"f3-graph-residual500-hidden16-currentmanifest-seed17-full835-nonce{nonce}"
    namespace.mkdir(mode=0o700)
    plan = admission._build_reserved_plan(fixture["root"], manifest=fixture["manifest"], training_receipt=fixture["training"], checkpoint=fixture["checkpoint"], nonce=nonce, namespace=namespace, gpu_index=admission.GPU_INDEX, python_executable=fixture["python"])
    namespace_descriptor = admission._existing_namespace_descriptor(namespace)
    authority_id = hashlib.sha256(f"synthetic-residual-seed17-runner:{namespace}".encode()).hexdigest()
    scheduler_root = Path(admission.EXTERNAL_SCHEDULER_ROOT)
    authority_path = scheduler_root / f"{authority_id}.authority.json"
    consume_path = scheduler_root / f"{authority_id}.claim.json"
    public_key = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    gpu = admission._gpu_identity(fixture["resource"]["gpu"])
    unsigned = {
        "schema": admission.EXTERNAL_AUTHORITY_SCHEMA, "authority_id": authority_id,
        "state": "issued", "one_shot": True,
        "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST},
        "scheduler": {"uid": os.getuid(), "gid": os.getgid(), "host": admission.CURRENT_HOST, "role": "external_scheduler"},
        "namespace": namespace_descriptor, "nonce": nonce,
        "plan_sha256": admission._plan_binding_digest(plan),
        "resource_snapshot_sha256": admission.canonical_digest(fixture["resource"]),
        "gpu": gpu, "gpu_identity_sha256": admission.canonical_digest(gpu),
        "consume_path": str(consume_path), "key_id": hashlib.sha256(public_key).hexdigest(), "signature_algorithm": "ed25519",
    }
    _write_json(authority_path, {**unsigned, "signature_base64": base64.b64encode(key.sign(admission._authority_signing_message(unsigned))).decode("ascii")})
    authority_path.chmod(0o600)
    return authority_path


def _mint(tmp_path: Path, nonce: str = "a" * 32) -> Path:
    fixture = _fixture(tmp_path)
    authority = _authority(fixture, nonce)
    receipt = admission.mint_admission(fixture["root"], manifest=fixture["manifest"], training_receipt=fixture["training"], checkpoint=fixture["checkpoint"], nonce=nonce, output_root=fixture["output_root"], resource_admission=fixture["resource"], external_authority=authority, python_executable=fixture["python"])
    return Path(receipt["receipt_path"])


def test_build_plan_is_receipt_bound_and_non_launching(tmp_path: Path) -> None:
    receipt = _mint(tmp_path)
    plan = runner.build_plan(receipt)
    value = plan.as_dict()
    assert value["seed"] == 17
    assert value["model_kind"] == "graph_residual"
    assert value["transitions"] == 835
    assert value["frames"] == 836
    assert value["launch_allowed"] is False
    assert value["diagnostic_execute_allowed"] is False
    assert value["popen_attempted"] is False
    assert value["real_workload_started"] == 0
    assert value["credit"] == 0
    assert not Path(str(plan.outputs["terminal_receipt"])).exists()


def test_dry_run_never_calls_popen_or_consumes_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _mint(tmp_path)
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
    assert not Path(receipt).parent.joinpath(admission.CONSUMED_NAME).exists()


def test_explicit_execute_fails_before_consumption_or_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _mint(tmp_path)
    plan = runner.build_plan(receipt)
    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("blocked execution must not call Popen")

    monkeypatch.setattr(runner, "_SEALED_POPEN", forbidden)
    with pytest.raises(runner.RunnerError, match="not admitted"):
        runner.execute_diagnostic(plan, object())
    assert calls == []
    assert not Path(receipt).parent.joinpath(admission.CONSUMED_NAME).exists()


def test_no_execute_alias_and_terminal_binding_rejects_synthetic_payload(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        runner._parse_args(["--execute"])
    assert runner._parse_args(["--diagnostic-execute"]).diagnostic_execute is True
    plan = runner.build_plan(_mint(tmp_path))
    with pytest.raises(runner.RunnerError, match="synthetic"):
        runner.validate_terminal_receipt(plan, {"schema": runner.TERMINAL_RECEIPT_SCHEMA, "status": "terminal_verified_diagnostic_only", "synthetic": True})


def test_report_without_receipt_is_blocked_and_zero_credit() -> None:
    report = runner.build_report(None, execute_requested=True)
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["launch_allowed"] is False
    assert report["popen_attempted"] is False
    assert report["terminal_receipt"] is None
    assert report["credit"] == 0


def test_report_rejects_claimed_process_or_validator_side_effects() -> None:
    report = runner.build_report(None)
    for key in ("popen_called", "wait_observed", "validator_started"):
        forged = json.loads(json.dumps(report))
        forged["side_effects"][key] = True
        assert runner.validate_report(forged), key
    assert runner.validate_report(report) == []
