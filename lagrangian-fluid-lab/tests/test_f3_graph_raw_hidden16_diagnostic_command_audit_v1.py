"""Synthetic safety tests for the seed17 diagnostic command audit."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_raw_hidden16_diagnostic_command_audit_v1 as audit
from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as rollout


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return raw


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    inputs = tmp_path / "inputs"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "reports").mkdir(parents=True)
    inputs.mkdir(parents=True)
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    source = root / "scripts" / "core_learning.py"
    source.write_text("# synthetic source for the read-only audit\n", encoding="utf-8")

    manifest_payload = {
        "schema": rollout.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "a" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    manifest_raw = _write_json(manifest, manifest_payload)
    manifest_sha = rollout.canonical_digest(manifest_payload)
    checkpoint = inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt"
    checkpoint_raw = b"synthetic checkpoint bytes; content is never opened by the audit"
    checkpoint.write_bytes(checkpoint_raw)
    checkpoint_meta = {
        "schema": rollout.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": _sha_bytes(checkpoint_raw),
        "bytes": len(checkpoint_raw),
        "update": rollout.UPDATES,
    }
    run_id = "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3"
    training = inputs / "f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
    training_payload = {
        "schema": rollout.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": audit.MODEL,
        "seed": audit.SEED,
        "run_id": run_id,
        "completed_updates": audit.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": manifest_sha,
            "model_kind": audit.MODEL,
            "hidden": audit.HIDDEN,
            "updates": audit.UPDATES,
            "run_id": run_id,
            "seed": audit.SEED,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **audit.ZERO_CREDIT,
    }
    training_raw = _write_json(training, training_payload)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "training": training,
        "training_raw": training_raw,
        "checkpoint": checkpoint,
        "checkpoint_raw": checkpoint_raw,
        "output_root": tmp_path / "audit-output",
    }


def _report(tmp_path: Path, *, nonce: str = "a" * 32) -> tuple[dict[str, object], dict[str, object]]:
    fixture = _fixture(tmp_path)
    Path(fixture["output_root"]).mkdir()
    report = audit.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        output_root=fixture["output_root"],
        nonce=nonce,
        gpu_index=4,
    )
    return report, fixture


def test_audit_binds_seed17_command_mapping_and_identity_without_creating_outputs(tmp_path: Path) -> None:
    report, fixture = _report(tmp_path)

    assert audit.validate_report(report) == []
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is True
    assert report["readiness_pass"] is False
    assert report["launch_allowed"] is False
    assert report["credit"] == 0
    assert report["expected_contract"]["transitions"] == 835
    assert report["expected_contract"]["frames"] == 836
    command = report["exact_evaluate_command"]
    assert command["device_mapping"] == {
        "CUDA_VISIBLE_DEVICES": "4",
        "logical_device": "cuda:0",
        "physical_gpu_index": 4,
        "mapping": "cuda:0 -> physical GPU 4",
    }
    assert command["argv"][3] == "evaluate"
    assert "--diagnostic" in command["argv"]
    assert report["identity"]["checkpoint"]["content_opened"] is False
    assert report["identity"]["core_learning_source"]["content_opened"] is True
    freshness = report["fresh_namespace_and_outputs"]
    assert freshness["all_paths_fresh"] is True
    assert freshness["namespace_created_by_audit"] is False
    assert not Path(freshness["namespace"]["path"]).exists()
    assert not list(Path(fixture["output_root"]).glob("*"))


def test_audit_has_explicit_fail_closed_blockers_and_no_popen_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_popen(*args: object, **kwargs: object) -> None:
        raise AssertionError("the diagnostic command audit must not call Popen")

    monkeypatch.setattr("subprocess.Popen", forbidden_popen)
    report, _fixture_data = _report(tmp_path)
    assert audit.validate_report(report) == []
    blockers = report["blocked_reasons"]
    assert any("terminal HDF5/artifact validator" in item for item in blockers)
    assert any("Popen/wait" in item for item in blockers)
    assert any("scheduler-owned" in item for item in blockers)
    assert report["popen_attempts"] == 0
    assert report["side_effects"]["processes_started"] == 0


def test_checkpoint_content_is_not_used_and_declared_drift_is_rejected(tmp_path: Path) -> None:
    report, fixture = _report(tmp_path)
    checkpoint = Path(fixture["checkpoint"])
    checkpoint.write_bytes(b"drifted checkpoint content")
    drifted = audit.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        output_root=fixture["output_root"],
        nonce="b" * 32,
        gpu_index=4,
    )
    assert drifted["source_bound"] is False
    assert drifted["launch_allowed"] is False
    assert any("checkpoint.bytes" in item for item in drifted["blocked_reasons"])
    assert report["identity"]["checkpoint"]["content_sha256_revalidated"] is False


def test_existing_namespace_or_output_stays_fail_closed(tmp_path: Path) -> None:
    report, fixture = _report(tmp_path)
    namespace = Path(report["fresh_namespace_and_outputs"]["namespace"]["path"])
    namespace.mkdir()
    blocked = audit.build_report(
        root=fixture["root"],
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        output_root=fixture["output_root"],
        nonce="a" * 32,
        gpu_index=4,
    )
    assert blocked["source_bound"] is False
    assert blocked["launch_allowed"] is False
    assert any("output namespace" in item or "namespace" in item for item in blocked["blocked_reasons"])


def test_report_validator_rejects_launch_credit_and_mapping_forgery(tmp_path: Path) -> None:
    report, _fixture_data = _report(tmp_path)
    forged = copy.deepcopy(report)
    forged["launch_allowed"] = True
    assert audit.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["credit"] = 1
    assert audit.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["device_mapping"]["physical_gpu_index"] = 5
    assert audit.validate_report(forged)
    forged = copy.deepcopy(report)
    forged["unexpected_formal_alias"] = False
    assert audit.validate_report(forged)


def test_cli_writes_and_verifies_only_the_requested_audit_report(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output_root = Path(fixture["output_root"])
    output_root.mkdir()
    report_path = tmp_path / "audit.json"
    markdown_path = tmp_path / "audit.zh-CN.md"
    assert audit.main(
        [
            "--root",
            str(fixture["root"]),
            "--manifest",
            str(fixture["manifest"]),
            "--training-receipt",
            str(fixture["training"]),
            "--output-root",
            str(output_root),
            "--nonce",
            "d" * 32,
            "--report-output",
            str(report_path),
            "--markdown-output",
            str(markdown_path),
        ]
    ) == 0
    assert report_path.is_file()
    assert markdown_path.is_file()
    assert audit.main(["--root", str(fixture["root"]), "--verify-report", str(report_path)]) == 0
    assert not list(output_root.glob("*"))


def test_execute_flag_is_rejected_before_any_input_or_side_effect(tmp_path: Path) -> None:
    assert audit.main(["--execute", "--report-output", str(tmp_path / "nope.json")]) == 2
    assert not (tmp_path / "nope.json").exists()
