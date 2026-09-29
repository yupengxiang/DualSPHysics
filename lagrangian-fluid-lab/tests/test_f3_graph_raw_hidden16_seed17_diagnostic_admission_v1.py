"""Independent tests for the receipt-bound, zero-credit seed17 admission."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest

from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission


def _write_json(path: Path, payload: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return raw


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    for relative in admission.SOURCE_RELATIVE_PATHS.values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# synthetic pinned source: {relative}\n", encoding="utf-8")

    manifest_payload = {
        "schema": admission.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "a" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    manifest_sha = admission.launcher.canonical_digest(manifest_payload)
    _write_json(manifest, manifest_payload)

    checkpoint = root / "inputs" / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint_raw = b"synthetic checkpoint bytes; admission hashes this bounded fixture"
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
    training_payload = {
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
            "manifest_sha256": manifest_sha,
            "model_kind": admission.MODEL,
            "hidden": admission.HIDDEN,
            "updates": admission.UPDATES,
            "run_id": run_id,
            "seed": admission.SEED,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **admission.launcher.ZERO_CREDIT,
    }
    _write_json(training, training_payload)
    resource_snapshot = admission.resource.probe_resource_admission(
        admission.GPU_INDEX,
        root=root,
        gpu_rows={2: {"total_mib": 49152, "used_mib": 2048, "free_mib": 47104}},
        cpu_count=16,
        load_1m=1.0,
        tmp_free_bytes=16 * 1024**3,
        root_free_bytes=16 * 1024**3,
    )
    (tmp_path / "admission-output").mkdir()
    return {
        "root": root,
        "manifest": manifest,
        "training": training,
        "checkpoint": checkpoint,
        "resource": resource_snapshot,
        "output_root": tmp_path / "admission-output",
    }


def _mint(tmp_path: Path, nonce: str = "a" * 32) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _fixture(tmp_path)
    receipt = admission.mint_admission(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_root=fixture["output_root"],
        resource_admission=fixture["resource"],
    )
    return receipt, fixture


def test_receipt_binds_all_identity_domains_and_stays_zero_credit(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path)
    assert admission.validate_receipt(receipt) == []
    assert receipt["identity"]["seed"] == 17
    assert receipt["identity"]["case_id"] == admission.CASE_ID
    assert receipt["identity"]["transitions"] == 835
    assert receipt["identity"]["frames"] == 836
    assert set(receipt["identity"]["source_sha256"]) == set(admission.SOURCE_RELATIVE_PATHS)
    assert receipt["identity"]["command"]["env_overrides"] == {
        "CUDA_VISIBLE_DEVICES": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert receipt["diagnostic_execute_only"] is True
    assert receipt["credit"] == 0
    assert receipt["formal"] is False
    assert receipt["consumption"]["one_shot"] is True
    marker = Path(receipt["namespace_marker"]["path"])
    receipt_path = Path(receipt["receipt_path"])
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(marker.parent.stat().st_mode) == 0o700


def test_receipt_consumption_is_atomic_and_not_reusable(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path, nonce="b" * 32)
    receipt_path = Path(receipt["receipt_path"])
    capability = admission.consume_receipt(receipt_path)
    assert capability.receipt_path == receipt_path
    assert capability.receipt["credit"] == 0
    assert Path(capability.consumed_marker).is_file()
    with pytest.raises(admission.AdmissionError, match="already been consumed"):
        admission.consume_receipt(receipt_path)


def test_source_and_gpu_snapshot_drift_fail_closed(tmp_path: Path) -> None:
    receipt, fixture = _mint(tmp_path, nonce="c" * 32)
    source = Path(fixture["root"]) / admission.SOURCE_RELATIVE_PATHS["core_learning"]
    source.write_text("# drifted source\n", encoding="utf-8")
    with pytest.raises(admission.AdmissionError, match="source identity drifted"):
        admission.revalidate_receipt(receipt, resource_admission=fixture["resource"])

    receipt2, fixture2 = _mint(tmp_path / "second", nonce="d" * 32)
    drifted_resource = copy.deepcopy(fixture2["resource"])
    drifted_resource["gpu"]["free_mib"] -= 1
    with pytest.raises(admission.AdmissionError, match="resource snapshot drifted"):
        admission.revalidate_receipt(receipt2, resource_admission=drifted_resource)


def test_command_or_marker_tampering_is_rejected_without_execution(tmp_path: Path) -> None:
    receipt, _fixture_data = _mint(tmp_path, nonce="e" * 32)
    forged = copy.deepcopy(receipt)
    forged["identity"]["command"]["argv"][-1] = "--formal"
    assert admission.validate_receipt(forged, check_files=False)

    marker = Path(receipt["namespace_marker"]["path"])
    marker.chmod(0o644)
    with pytest.raises(admission.AdmissionError, match="mode"):
        admission.load_receipt(Path(receipt["receipt_path"]))


def test_report_is_receipt_bound_but_never_formal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = admission.build_report(
        fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce="f" * 32,
        output_root=fixture["output_root"],
        resource_admission=fixture["resource"],
    )
    assert admission.validate_report(report) == []
    assert report["status"] == "receipt_bound_admission_ready"
    assert report["admission_granted"] is True
    assert report["receipt_bound_capability_issued"] is True
    assert report["diagnostic_execute_only"] is True
    assert report["diagnostic_execute_allowed"] is False
    assert report["execution_capability_admitted"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert report["formal_state_touched"] is False
    assert report["popen_attempted"] is False
