"""Fail-closed tests for the audited, non-executing runner v2 boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat
import sys

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
    assert report["status"] == "dry_run_ready"
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
