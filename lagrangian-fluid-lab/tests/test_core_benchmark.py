import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import h5py
import pytest

from test_core_contract import tiny_manifest
from scripts.core_benchmark import (_checkpoint_registration,
                                     _compare_paired_reproduction,
                                     inspect_dataset, phase_plan, reproduce,
                                     verify_dataset)
from scripts.core_dataset import CoreDataset, sha256_file
from scripts.core_learning import train_model
from scripts.core_package import build_bundle


def test_phase_plan_connects_all_entrypoints_and_freezes_denominator(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps(tiny_manifest(source)))
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller)

    plan = phase_plan("manifest.json", source)

    assert plan["schema"] == "core.phase_plan.v1"
    assert plan["passed"] is True
    assert plan["phase_order"] == [
        "verify", "inspect", "train", "rollout", "evaluate", "reproduce",
    ]
    assert plan["denominator"]["registered_case_count"] == 1
    assert plan["denominator"]["expected_frames_by_case"] == {"tiny": 1}
    assert plan["denominator"]["trajectory_frames_by_case"] == {"tiny": 2}
    assert plan["denominator"]["missing_denominator_case_ids"] == []
    assert plan["denominator"]["missing_execution_preserves_expected_frames"] is True
    assert plan["guards"]["future_state_inputs"] is False
    assert plan["guards"]["formal_training_started"] is False
    assert plan["formal_readiness"]["formal_job_count"] == 0
    assert plan["formal_readiness"]["required_formal_job_count"] == 9

    # The same explicit data_root interpretation must hold for all source-only
    # entrypoints, even though the caller cwd does not contain manifest.json.
    inspection = inspect_dataset("manifest.json", source)
    verification = verify_dataset("manifest.json", source, case_ids=["tiny"])
    assert inspection["case_count"] == 1
    assert verification["passed"] is True

    completed = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "scripts/core_benchmark.py"),
         "phase-plan", "--manifest", "manifest.json", "--data-root", str(source)],
        cwd=caller, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    cli_plan = json.loads(completed.stdout)
    assert cli_plan["schema"] == "core.phase_plan.v1"
    assert cli_plan["denominator"]["expected_frames_by_case"] == {"tiny": 1}


def test_verify_dataset_rejects_nonbinary_valid_mask(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    payload = tiny_manifest(source)
    path = source / "data.h5"
    with h5py.File(path, "r+") as handle:
        del handle["valid"]
        handle.create_dataset("valid", data=[[2, 1], [1, 1]])
    payload["cases"][0]["sha256"] = sha256_file(path)
    payload["cases"][0]["bytes"] = path.stat().st_size
    manifest.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="valid"):
        verify_dataset(manifest, source, case_ids=["tiny"])


def _model_bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps(tiny_manifest(source)))
    checkpoint = source / "weights.pt"
    with CoreDataset(manifest, source) as data:
        train_model(
            data, model_kind="mlp", seed=17, updates=1, centers_per_update=1,
            hidden=8, normalization_transitions=1, checkpoint=checkpoint,
            checkpoint_every=1, validation_every=0, log_every=1,
        )
    registration = source / "registered.json"
    registration.write_text(json.dumps({"checkpoints": [{
        "path": str(checkpoint), "sha256": sha256_file(checkpoint),
        "model_kind": "mlp", "seed": 17, "update": 1,
    }]}))
    bundle = tmp_path / "bundle"
    build_bundle(manifest, source, bundle, checkpoint_manifest=registration)
    relocated = tmp_path / "relocated"
    bundle.rename(relocated)
    return relocated


def test_checkpoint_reproduction_rejects_unregistered_manifest(tmp_path):
    bundle = _model_bundle(tmp_path)
    alternate = bundle / "unregistered.json"
    alternate.write_bytes((bundle / "dataset.json").read_bytes())
    with pytest.raises(ValueError, match="bundle registered dataset.json"):
        reproduce(alternate, bundle, ["tiny"], checkpoint="models/checkpoint-000.pt",
                  output_dir=tmp_path / "reproduction")


def test_relocated_checkpoint_reproduction_writes_full_trajectory_and_score(tmp_path):
    bundle = _model_bundle(tmp_path)
    output = tmp_path / "reproduction"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    command = [
        sys.executable, str(bundle / "code/scripts/core_benchmark.py"), "reproduce",
        "--manifest", str(bundle / "dataset.json"), "--data-root", str(bundle),
        "--checkpoint", "models/checkpoint-000.pt", "--case-id", "tiny",
        "--output-dir", str(output),
    ]
    completed = subprocess.run(command, cwd=tmp_path, env=environment,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / "reproduction.json").read_text())
    assert report["schema"] == "core.model_reproduction.v1"
    assert report["passed"] and report["full_horizon_reproduction"]
    assert not report["full_product_reproduction"]
    assert report["full_horizon"]["requested_maximum_steps"] is None
    assert report["comparison"]["status"] == "not_requested"
    trajectory = output / report["cases"]["tiny"]["trajectory"]["path"]
    with h5py.File(trajectory, "r") as handle:
        assert handle["time"].shape == (2,)
        assert handle["position"].shape == (2, 2, 3)
        assert handle["velocity"].shape == (2, 2, 3)
    score = json.loads((output / "scores.json").read_text())
    assert score["schema"] == "core.model_reproduction.score.v1"
    assert score["cases"]["tiny"]["expected_frames"] == 1
    assert report["resource"]["wall_seconds"] >= 0
    assert report["code"]["closure_sha256"]


def test_checkpoint_registry_version_hash_and_same_host_pair_are_rejected(tmp_path):
    bundle = _model_bundle(tmp_path)
    registry_path = bundle / "checkpoints.json"
    original = registry_path.read_text()
    registry = json.loads(original)
    registry["schema"] = "future.checkpoint.registry"
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="unsupported checkpoint registry version"):
        _checkpoint_registration(bundle, "models/checkpoint-000.pt")
    registry_path.write_text(original)

    checkpoint = bundle / "models/checkpoint-000.pt"
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checkpoint artifact hash mismatch"):
        _checkpoint_registration(bundle, "models/checkpoint-000.pt")

    # A pair with the same observed hostname is never promoted to a
    # cross-host/full-product claim, even when the local artifacts compare.
    # Use a clean bundle/output for the report after the intentional tamper.
    clean = tmp_path / "clean"
    clean.mkdir()
    clean_bundle = _model_bundle(clean)
    output = clean / "reproduction"
    report = reproduce(
        clean_bundle / "dataset.json", clean_bundle, ["tiny"],
        checkpoint="models/checkpoint-000.pt", output_dir=output,
    )
    comparison = _compare_paired_reproduction(
        report, output / "reproduction.json", output / "reproduction.json")
    assert not comparison["passed"]
    assert not comparison["distinct_host_evidence"]
    assert any("distinct host" in error for error in comparison["errors"])
