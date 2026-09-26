import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import h5py
import pytest

from test_core_contract import tiny_manifest
from scripts import core_benchmark, core_learning
from scripts.core_benchmark import (_checkpoint_registration,
                                     _compare_paired_reproduction,
                                     inspect_dataset, phase_plan, reproduce,
                                     verify_dataset)
from scripts.core_dataset import CoreDataset, sha256_file
from scripts.core_learning import train_model
from scripts.core_code_manifest import CORE_RUNTIME_CODE_FILES
from scripts.core_package import build_bundle


@pytest.mark.parametrize("command", [
    "train", "profile", "rollout", "evaluate", "evaluate-checkpoints",
])
def test_unified_entrypoint_delegates_explicit_arguments_without_mutating_sys_argv(
        monkeypatch, command):
    """All learning phases honour ``main(argv)`` just like the shell CLI."""
    observed = []
    process_argv = list(sys.argv)

    def delegated(argv):
        observed.append(list(argv))
        return 37

    monkeypatch.setattr(core_learning, "main", delegated)

    result = core_benchmark.main([command, "--example", "value"])

    assert result == 37
    assert observed == [[command, "--example", "value"]]
    assert sys.argv == process_argv


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
    assert json.loads((bundle / "bundle.json").read_text())["full_core_release"] is False
    assert report["registered_case_ids"] == ["tiny"]
    assert report["selected_case_ids"] == ["tiny"]
    assert report["denominator"]["registered_case_count"] == 1
    assert report["denominator"]["selected_case_count"] == 1
    assert report["denominator"]["registered_expected_frames_by_case"] == {"tiny": 1}
    assert report["denominator"]["selected_expected_frames_by_case"] == {"tiny": 1}
    assert report["full_horizon"]["requested_maximum_steps"] is None
    assert report["comparison"]["status"] == "not_requested"
    assert report["score_artifact"]["path"] == "scores.json"
    assert not Path(report["score_artifact"]["path"]).is_absolute()
    assert report["score_artifact"]["expected_frames"] == {"tiny": 1}
    trajectory = output / report["cases"]["tiny"]["trajectory"]["path"]
    trajectory_ref = report["cases"]["tiny"]["trajectory"]
    assert not Path(trajectory_ref["path"]).is_absolute()
    assert trajectory_ref["expected_frames"] == 1
    assert trajectory_ref["trajectory_frames"] == 2
    assert trajectory_ref["bytes"] == trajectory.stat().st_size
    with h5py.File(trajectory, "r") as handle:
        assert handle["time"].shape == (2,)
        assert handle["position"].shape == (2, 2, 3)
        assert handle["velocity"].shape == (2, 2, 3)
    score = json.loads((output / "scores.json").read_text())
    assert score["schema"] == "core.model_reproduction.score.v1"
    assert score["cases"]["tiny"]["expected_frames"] == 1
    assert report["resource"]["wall_seconds"] >= 0
    assert report["code"]["closure_sha256"]


def test_checkpoint_reproduction_rejects_duplicate_and_unknown_cases(tmp_path):
    bundle = _model_bundle(tmp_path)
    with pytest.raises(ValueError, match="duplicates"):
        reproduce(bundle / "dataset.json", bundle, ["tiny", "tiny"],
                  checkpoint="models/checkpoint-000.pt", output_dir=tmp_path / "duplicate")
    with pytest.raises(ValueError, match="not registered"):
        reproduce(bundle / "dataset.json", bundle, ["unknown"],
                  checkpoint="models/checkpoint-000.pt", output_dir=tmp_path / "unknown")


def _make_distinct_host_pair(output, tmp_path):
    paired_dir = tmp_path / "paired"
    shutil.copytree(output, paired_dir)
    paired_report_path = paired_dir / "reproduction.json"
    paired_report = json.loads(paired_report_path.read_text())
    paired_report["artifact_root"] = str(paired_dir)
    paired_report["reproduction_host"] = "paired-test-host"
    paired_report["verification"]["host"] = "paired-test-host"
    paired_report_path.write_text(json.dumps(paired_report))
    return paired_report_path


def test_paired_comparison_requires_portable_bound_artifacts_and_fixed_denominators(tmp_path):
    bundle = _model_bundle(tmp_path)
    output = tmp_path / "reproduction"
    report = reproduce(
        bundle / "dataset.json", bundle, ["tiny"],
        checkpoint="models/checkpoint-000.pt", output_dir=output,
    )
    paired_report_path = _make_distinct_host_pair(output, tmp_path)

    valid = _compare_paired_reproduction(report, output / "reproduction.json", paired_report_path)
    assert valid["passed"] is True

    paired = json.loads(paired_report_path.read_text())
    paired["score_artifact"]["bytes"] += 1
    paired_report_path.write_text(json.dumps(paired))
    bad_bytes = _compare_paired_reproduction(
        report, output / "reproduction.json", paired_report_path)
    assert bad_bytes["passed"] is False
    assert any("byte count mismatch" in error for error in bad_bytes["errors"])

    paired["score_artifact"]["bytes"] -= 1
    paired["cases"]["tiny"]["trajectory"]["sha256"] = "0" * 64
    paired_report_path.write_text(json.dumps(paired))
    bad_hash = _compare_paired_reproduction(
        report, output / "reproduction.json", paired_report_path)
    assert bad_hash["passed"] is False
    assert any("hash mismatch" in error
               for error in bad_hash["trajectory"]["tiny"]["errors"])

    paired["cases"]["tiny"]["trajectory"]["sha256"] = report["cases"]["tiny"]["trajectory"]["sha256"]
    paired["score_artifact"]["path"] = str(tmp_path / "paired" / "scores.json")
    paired_report_path.write_text(json.dumps(paired))
    absolute_path = _compare_paired_reproduction(
        report, output / "reproduction.json", paired_report_path)
    assert absolute_path["passed"] is False
    assert any("portable relative path" in error for error in absolute_path["errors"])

    paired["score_artifact"]["path"] = "scores.json"
    paired["cases"]["tiny"]["trajectory"].pop("expected_frames")
    paired_report_path.write_text(json.dumps(paired))
    missing_frames = _compare_paired_reproduction(
        report, output / "reproduction.json", paired_report_path)
    assert missing_frames["passed"] is False
    assert any("expected_frames" in error for error in missing_frames["errors"])


def test_single_case_paired_run_is_diagnostic_not_full_product(tmp_path):
    bundle = _model_bundle(tmp_path)
    output = tmp_path / "reproduction"
    reproduce(bundle / "dataset.json", bundle, ["tiny"],
              checkpoint="models/checkpoint-000.pt", output_dir=output)
    paired_report_path = _make_distinct_host_pair(output, tmp_path)

    report = reproduce(
        bundle / "dataset.json", bundle, ["tiny"],
        checkpoint="models/checkpoint-000.pt", output_dir=output,
        paired_report=paired_report_path,
    )

    assert report["comparison"]["passed"] is True
    assert report["cross_host_reproduction"] is True
    assert report["paired_diagnostic_cross_host"] is True
    assert report["full_product_reproduction"] is False


def test_portable_runtime_code_closure_is_shared_and_covers_local_imports():
    from scripts.core_benchmark import MODEL_CODE_FILES
    from scripts.core_package import BUNDLE_CODE_FILES

    assert BUNDLE_CODE_FILES == MODEL_CODE_FILES == CORE_RUNTIME_CODE_FILES
    assert len(set(CORE_RUNTIME_CODE_FILES)) == len(CORE_RUNTIME_CODE_FILES)
    assert "core_package.py" in CORE_RUNTIME_CODE_FILES
    scripts_root = Path(core_benchmark.__file__).resolve().parent
    local_modules = {Path(name).stem for name in CORE_RUNTIME_CODE_FILES}
    for name in CORE_RUNTIME_CODE_FILES:
        tree = ast.parse((scripts_root / name).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "scripts":
                    imported.update(alias.name for alias in node.names)
                elif node.module.startswith("scripts."):
                    imported.add(node.module.split(".", 2)[1])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 2)[1]
                                 for alias in node.names
                                 if alias.name.startswith("scripts."))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "import_module" and node.args
                  and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)
                  and node.args[0].value.startswith("scripts.")):
                imported.add(node.args[0].value.split(".", 2)[1])
        on_disk_dependencies = {
            module for module in imported if (scripts_root / f"{module}.py").is_file()
        }
        assert on_disk_dependencies <= local_modules, name


def test_checkpoint_reproduction_rejects_short_horizon_and_marks_partial(tmp_path, monkeypatch):
    bundle = _model_bundle(tmp_path)
    original_rollout = core_learning.rollout_case

    def short_rollout(*args, **kwargs):
        result = original_rollout(*args, **kwargs)
        result["expected_frames"] -= 1
        return result

    monkeypatch.setattr(core_learning, "rollout_case", short_rollout)
    with pytest.raises(ValueError, match="full horizon"):
        reproduce(bundle / "dataset.json", bundle, ["tiny"],
                  checkpoint="models/checkpoint-000.pt", output_dir=tmp_path / "short")

    def partial_rollout(*args, **kwargs):
        result = original_rollout(*args, **kwargs)
        result["finite_rollout_complete"] = False
        result["failure_category"] = "synthetic_partial"
        return result

    monkeypatch.setattr(core_learning, "rollout_case", partial_rollout)
    report = reproduce(
        bundle / "dataset.json", bundle, ["tiny"],
        checkpoint="models/checkpoint-000.pt", output_dir=tmp_path / "partial",
    )
    assert report["passed"] is False
    assert report["full_horizon_reproduction"] is False


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
