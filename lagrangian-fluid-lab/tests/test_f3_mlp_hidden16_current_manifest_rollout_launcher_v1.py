"""Tests for the additive current-manifest F3 MLP rollout adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_mlp_hidden16_current_manifest_rollout_launcher_v1 as launcher


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return _sha_bytes(raw)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "lab"
    reports = root / "reports"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    reports.mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    (root / "scripts" / "core_learning.py").write_text("# fixture\n", encoding="utf-8")

    manifest_payload = {
        "schema": "core.dataset.v2",
        "case_count": 0,
        "cases": [],
        "formal_release": False,
    }
    manifest = root / "campaigns" / "current" / "manifest.json"
    _write_json(manifest, manifest_payload)
    manifest_sha = _canonical_sha(manifest_payload)

    checkpoint = tmp_path / "current-seed17-hidden16.pt"
    checkpoint.write_bytes(b"current-checkpoint-bytes")
    checkpoint_sha = _sha_bytes(checkpoint.read_bytes())
    run_id = "f3-mlp500-hidden16-currentmanifest-seed17-20260929"
    training = tmp_path / "training-seed17.json"
    checkpoint_meta = {
        "schema": launcher.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": checkpoint_sha,
        "bytes": checkpoint.stat().st_size,
        "update": launcher.UPDATES,
    }
    receipt = {
        "schema": launcher.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": launcher.MODEL,
        "seed": 17,
        "run_id": run_id,
        "completed_updates": launcher.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": manifest_sha,
            "model_kind": launcher.MODEL,
            "hidden": launcher.HIDDEN,
            "updates": launcher.UPDATES,
            "run_id": run_id,
            "seed": 17,
            "paired_seed": 17,
            "sampler_seed": 17,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
    }
    _write_json(training, receipt)
    return {
        "root": root,
        "manifest": manifest,
        "checkpoint": checkpoint,
        "training": training,
        "run_id": run_id,
        "manifest_sha": manifest_sha,
    }


def _plan(fixture: dict[str, object], tmp_path: Path, *, nonce: str = "a" * 32):
    (tmp_path / "rollout").mkdir(parents=True, exist_ok=True)
    return launcher.build_plan(
        fixture["root"],
        seed=17,
        manifest=fixture["manifest"],
        checkpoint=fixture["checkpoint"],
        training_receipt=fixture["training"],
        run_id=fixture["run_id"],
        nonce=nonce,
        output_namespace=tmp_path / "rollout" / "current-manifest-seed17-full835",
        gpu_index=5,
    )


def test_build_plan_binds_explicit_current_manifest_inputs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path)

    assert plan.manifest == fixture["manifest"]
    assert plan.checkpoint_path == fixture["checkpoint"]
    assert plan.run_id == fixture["run_id"]
    assert plan.manifest_sha256 == fixture["manifest_sha"]
    assert plan.legacy_plan.command[plan.command.index("--manifest") + 1] == str(fixture["manifest"])
    assert plan.legacy_plan.command[plan.command.index("--checkpoint") + 1] == str(fixture["checkpoint"])
    assert plan.outputs["evaluation"].name.startswith("current-manifest-seed17-full835-evaluation")
    assert "20260928" not in plan.run_id
    assert plan.as_dict()["input_boundary"]["checkpoint_content_opened"] is False
    assert plan.as_dict()["credit"] == 0


def test_default_cli_is_dry_run_and_never_calls_execution_engine(tmp_path: Path, monkeypatch, capsys) -> None:
    fixture = _fixture(tmp_path)
    (tmp_path / "rollout").mkdir()

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not call the execution engine")

    monkeypatch.setattr(launcher.legacy, "execute_plan", forbidden)
    result = launcher.main(
        [
            "--root", str(fixture["root"]),
            "--seed", "17",
            "--manifest", str(fixture["manifest"]),
            "--checkpoint", str(fixture["checkpoint"]),
            "--training-receipt", str(fixture["training"]),
            "--run-id", fixture["run_id"],
            "--nonce", "b" * 32,
            "--output-namespace", str(tmp_path / "rollout" / "cli-seed17-full835"),
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == launcher.SCHEMA
    assert output["status"] == "dry_run_ready"
    assert output["launched"] is False
    assert output["manifest"] == str(fixture["manifest"])
    assert output["checkpoint"]["path"] == str(fixture["checkpoint"])
    assert output["side_effects"]["processes_started"] == 0


def test_old_launcher_proof_constant_is_restored_after_adapter_binding(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path)
    original = launcher.legacy.PROCESS_PROOF_FILENAME
    with launcher._bind_legacy_proof_filename(plan):
        assert launcher.legacy.PROCESS_PROOF_FILENAME == plan.proof_filename
        assert launcher.legacy._output_paths(plan.namespace, plan.root, plan.seed) == dict(plan.outputs)
    assert launcher.legacy.PROCESS_PROOF_FILENAME == original


def test_training_receipt_manifest_or_checkpoint_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["config"]["manifest_sha256"] = "f" * 64
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(launcher.LauncherError, match="manifest_sha256"):
        _plan(fixture, tmp_path)

    fixture = _fixture(tmp_path / "checkpoint-drift")
    payload = json.loads(Path(fixture["training"]).read_text(encoding="utf-8"))
    payload["checkpoint"]["path"] = str(tmp_path / "wrong.pt")
    _write_json(Path(fixture["training"]), payload)
    with pytest.raises(launcher.LauncherError, match="checkpoint path"):
        _plan(fixture, tmp_path / "checkpoint-drift")


def test_old_fixed_historical_matrix_is_not_required(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plan = _plan(fixture, tmp_path)
    assert plan.training_receipt != plan.root / "reports" / launcher.legacy.TRAINING_MATRIX_FILENAME
    assert plan.training_receipt != plan.root / "reports" / launcher.legacy.HISTORY_FILENAME.format(seed=17)


def test_namespace_alias_and_collision_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(launcher.LauncherError, match="lexical path alias"):
        launcher.build_plan(
            fixture["root"],
            seed=17,
            manifest=fixture["manifest"],
            checkpoint=fixture["checkpoint"],
            training_receipt=fixture["training"],
            run_id=fixture["run_id"],
            nonce="c" * 32,
            output_namespace=tmp_path / "rollout" / "alias" / ".." / "target",
        )

    namespace = tmp_path / "rollout" / "collision"
    namespace.parent.mkdir(parents=True, exist_ok=True)
    namespace.write_text("occupied", encoding="utf-8")
    with pytest.raises(launcher.LauncherError, match="reuse|output"):
        launcher.build_plan(
            fixture["root"],
            seed=17,
            manifest=fixture["manifest"],
            checkpoint=fixture["checkpoint"],
            training_receipt=fixture["training"],
            run_id=fixture["run_id"],
            nonce="d" * 32,
            output_namespace=namespace,
        )
