"""Synthetic safety tests for the graph_raw audited executor boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import f3_graph_raw_hidden16_current_manifest_audited_executor_v1 as executor


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    path.write_bytes(raw)
    return raw


def _admission(gpu: int = 5) -> dict[str, object]:
    return executor.probe_resource_admission(
        gpu,
        gpu_rows={gpu: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140}},
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )


def _fixture(tmp_path: Path, *, seed: int = 17, exit_code: int = 0) -> dict[str, object]:
    root = tmp_path / "lab"
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "reports").mkdir()
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(Path(sys.executable).resolve().read_bytes())
    python.chmod(0o755)
    script = root / "scripts" / "core_learning.py"
    script.write_text(f"raise SystemExit({exit_code})\n", encoding="utf-8")

    manifest_payload = {
        "schema": executor.identity.MANIFEST_SCHEMA,
        "case_count": 32,
        "dataset_id": "F3_registered32_core_native_v2",
        "formal_release": False,
        "source_manifest_sha256": "a" * 64,
    }
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    manifest_raw = _write_json(manifest, manifest_payload)
    manifest_sha = executor.identity.canonical_digest(manifest_payload)
    run_id = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3"
    checkpoint = inputs / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-checkpoint.pt"
    checkpoint_raw = f"checkpoint-{seed}".encode()
    checkpoint.write_bytes(checkpoint_raw)
    checkpoint_meta = {
        "schema": executor.identity.CHECKPOINT_SCHEMA,
        "path": str(checkpoint),
        "sha256": _sha_bytes(checkpoint_raw),
        "bytes": len(checkpoint_raw),
        "update": executor.UPDATES,
    }
    training = inputs / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
    receipt = {
        "schema": executor.identity.TRAINING_SCHEMA,
        "evidence_status": "complete",
        "model_kind": executor.MODEL,
        "seed": seed,
        "run_id": run_id,
        "completed_updates": executor.UPDATES,
        "checkpoint_verified": True,
        "checkpoint": checkpoint_meta,
        "checkpoints": [checkpoint_meta],
        "config": {
            "manifest_sha256": manifest_sha,
            "model_kind": executor.MODEL,
            "hidden": executor.HIDDEN,
            "updates": executor.UPDATES,
            "run_id": run_id,
            "seed": seed,
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
        },
        **executor.ZERO_CREDIT,
    }
    training_raw = _write_json(training, receipt)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "training": training,
        "training_raw": training_raw,
        "checkpoint": checkpoint,
        "run_id": run_id,
    }


def _plan(tmp_path: Path, *, seed: int = 17, nonce: str = "a" * 32, exit_code: int = 0):
    fixture = _fixture(tmp_path, seed=seed, exit_code=exit_code)
    namespace = tmp_path / f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    plan = executor.build_audited_plan(
        fixture["root"],
        seed=seed,
        manifest=fixture["manifest"],
        training_receipt=fixture["training"],
        checkpoint=fixture["checkpoint"],
        nonce=nonce,
        output_namespace=namespace,
        gpu_index=5,
        admission=_admission(),
    )
    return fixture, plan


def test_build_audited_plan_binds_fixed_identity_and_exact_digest(tmp_path: Path) -> None:
    fixture, plan = _plan(tmp_path)

    assert executor.MODEL == "graph_raw"
    assert plan.identity_plan.seed == 17
    assert plan.identity_plan.run_id == fixture["run_id"]
    assert executor.CASE_ID == "F3_DEV_00_a0p903125"
    assert plan.identity_plan.command_sha256
    assert len(plan.exact_command_digest) == 64
    assert plan.admission["status"] == "admitted"
    assert not plan.namespace.exists()
    assert plan.identity_plan.as_dict()["launch_allowed"] is False


def test_execute_blocks_before_popen_when_terminal_capability_is_absent(tmp_path: Path) -> None:
    _fixture_data, plan = _plan(tmp_path)

    with pytest.raises(executor.ExecutorError, match="terminal HDF5/artifact identity"):
        executor.execute_plan(
            plan,
            admission_probe=lambda _gpu: _admission(),
        )
    assert not plan.namespace.exists()


def test_injected_popen_and_caller_capability_are_rejected_before_any_side_effect(
    tmp_path: Path,
) -> None:
    _fixture_data, plan = _plan(tmp_path)
    called = {"count": 0}

    def spoof_factory(*args: object, **kwargs: object) -> object:
        called["count"] += 1
        raise AssertionError("injected Popen must never be called")

    with pytest.raises(executor.ExecutorError, match="caller-supplied, fake, or injected Popen"):
        executor._run_popen_wait(
            plan,
            terminal_capability=object(),
            popen_factory=spoof_factory,
            admission_probe=lambda _gpu: _admission(),
        )
    assert called["count"] == 0
    assert not plan.outputs["log"].exists()


def test_input_path_toc_tou_drift_is_rejected_before_popen(tmp_path: Path) -> None:
    fixture, plan = _plan(tmp_path)
    training = fixture["training"]
    training.write_bytes(fixture["training_raw"] + b"drift")

    with pytest.raises(executor.ExecutorError, match="training_receipt changed"):
        executor._revalidate_for_execution(plan, admission_probe=lambda _gpu: _admission())


def test_existing_namespace_is_rejected_and_lexical_alias_is_rejected(tmp_path: Path) -> None:
    _fixture_data, plan = _plan(tmp_path)
    plan.namespace.mkdir()
    with pytest.raises(executor.ExecutorError, match="output namespace"):
        executor._revalidate_for_execution(plan, admission_probe=lambda _gpu: _admission())

    fixture = _fixture(tmp_path / "alias")
    nonce = "b" * 32
    with pytest.raises(executor.identity.ContractError, match="lexical path alias"):
        executor.build_audited_plan(
            fixture["root"],
            seed=17,
            manifest=fixture["manifest"],
            training_receipt=fixture["training"],
            checkpoint=fixture["checkpoint"],
            nonce=nonce,
            output_namespace=Path("/tmp") / ".." / "tmp" / f"f3-graph_raw500-hidden16-currentmanifest-seed17-full835-nonce{nonce}",
            gpu_index=5,
            admission=_admission(),
        )


def test_caller_supplied_pid_returncode_or_mapping_cannot_mint_process_proof(
    tmp_path: Path,
) -> None:
    _fixture_data, plan = _plan(tmp_path)
    forged = {
        "evaluator_pid": 12345,
        "evaluator_returncode": 0,
        "wait_returncode": 0,
        "wait_observed": True,
    }
    with pytest.raises(executor.ExecutorError, match="sealed record"):
        executor.build_process_proof(plan, forged)
    with pytest.raises(TypeError, match="internal sealed witness"):
        executor._ExecutionRecord()
    malformed_record = object.__new__(executor._ExecutionRecord)
    with pytest.raises(executor.ExecutorError, match="sealed record is malformed"):
        executor.build_process_proof(plan, malformed_record)


def test_unknown_authority_alias_is_rejected_from_report(tmp_path: Path) -> None:
    fixtures = [_fixture(tmp_path / f"seed{seed}", seed=seed) for seed in executor.SEEDS]
    output_root = tmp_path / "out"
    output_root.mkdir()
    report = executor.build_report(
        fixtures[0]["root"],
        manifest=fixtures[0]["manifest"],
        training_receipts={seed: fixture["training"] for seed, fixture in zip(executor.SEEDS, fixtures)},
        checkpoints={seed: fixture["checkpoint"] for seed, fixture in zip(executor.SEEDS, fixtures)},
        nonces={17: "1" * 32, 29: "2" * 32, 43: "3" * 32},
        gpu_indices={17: 4, 29: 5, 43: 6},
        output_root=output_root,
        gpu_rows={
            4: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
            5: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
            6: {"total_mib": 49140, "used_mib": 1000, "free_mib": 48140},
        },
        cpu_count=128,
        load_1m=1.0,
        tmp_free_bytes=100 * 1024**3,
        root_free_bytes=100 * 1024**3,
    )
    assert executor.validate_report(report) == []
    forged = copy.deepcopy(report)
    forged["unknown_formal_credit_alias"] = 0
    assert executor.validate_report(forged)
