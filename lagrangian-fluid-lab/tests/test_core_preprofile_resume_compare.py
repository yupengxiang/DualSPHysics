import copy
import json
import hashlib
import torch

from scripts.core_dataset import CoreDataset
from scripts.core_learning import train_model
from scripts.core_preprofile_resume_compare import compare_resume
from test_core_contract import tiny_manifest


def _make_resume_triplet(tmp_path, model_kind="graph_residual"):
    manifest = tiny_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    paths = {
        "base": tmp_path / "base.json",
        "resumed": tmp_path / "resumed.json",
        "continuous": tmp_path / "continuous.json",
    }
    with CoreDataset(manifest, tmp_path) as data:
        train_model(
            data, model_kind=model_kind, seed=17, updates=2,
            centers_per_update=1, hidden=8, normalization_transitions=1,
            checkpoint=tmp_path / "base.pt", output=paths["base"],
            progress_output=tmp_path / "base-progress.json", checkpoint_every=1,
            log_every=1, validation_every=0, run_id=f"{model_kind}-seed17",
            evaluate_milestones=False,
        )
        train_model(
            data, model_kind=model_kind, seed=17, updates=4,
            centers_per_update=1, hidden=8, normalization_transitions=1,
            checkpoint=tmp_path / "resumed.pt", resume=tmp_path / "base.pt",
            output=paths["resumed"], progress_output=tmp_path / "resumed-progress.json",
            checkpoint_every=1, log_every=1, validation_every=0,
            run_id=f"{model_kind}-seed17", evaluate_milestones=False,
        )
        train_model(
            data, model_kind=model_kind, seed=17, updates=4,
            centers_per_update=1, hidden=8, normalization_transitions=1,
            checkpoint=tmp_path / "continuous.pt", output=paths["continuous"],
            progress_output=tmp_path / "continuous-progress.json", checkpoint_every=1,
            log_every=1, validation_every=0, run_id=f"{model_kind}-seed17",
            evaluate_milestones=False,
        )
    return manifest_path, paths


def test_resume_comparator_proves_digest_sampling_prior_and_control(tmp_path):
    manifest_path, paths = _make_resume_triplet(tmp_path)
    report = compare_resume(
        paths["base"], paths["resumed"], model_kind="graph_residual",
        manifest=manifest_path, data_root=tmp_path, continuous=paths["continuous"],
        base_update=2, resumed_update=4, output=tmp_path / "comparison.json",
    )
    assert report["status"] == "pass"
    assert report["failure_count"] == 0
    assert report["initialization"]["checks"]["loaded_digest_is_base16"] is True
    assert report["initialization"]["checks"]["initial_digest_equal"] is True
    assert report["sampling"]["continuation"] == "passed"
    assert report["residual_prior"]["resumed_calls"] is True
    assert report["continuous_equivalence"]["status"] == "pass"
    assert report["continuous_equivalence"]["checks"]["optimizer_state"] is True
    assert report["continuous_equivalence"]["claim"] == (
        "resume_matches_same_seed_continuous_18_step_control"
    )
    persisted = json.loads((tmp_path / "comparison.json").read_text())
    assert persisted["schema"] == "core.preprofile.resume_comparison.v1"
    assert persisted["writes_ledger"] is False


def test_resume_comparator_rejects_changed_initial_digest_and_sampler(tmp_path):
    manifest_path, paths = _make_resume_triplet(tmp_path)
    resumed = json.loads(paths["resumed"].read_text())
    resumed["evidence"]["initialization"]["parameter_digest"] = "0" * 64
    resumed["history"] = copy.deepcopy(resumed["history"])
    resumed["history"][2]["frame"] = 1
    paths["resumed"].write_text(json.dumps(resumed))
    report = compare_resume(
        paths["base"], paths["resumed"], model_kind="graph_residual",
        manifest=manifest_path, data_root=tmp_path, base_update=2, resumed_update=4,
    )
    assert report["status"] == "fail"
    codes = {item["code"] for item in report["failures"]}
    assert "resume_initialization_evidence_mismatch" in codes
    assert "sampler_continuation_mismatch" in codes


def test_resume_comparator_rejects_optimizer_only_change(tmp_path):
    manifest_path, paths = _make_resume_triplet(tmp_path, model_kind="mlp")
    checkpoint = tmp_path / "continuous.pt"
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    first = next(iter(payload["optimizer_state"]["state"].values()))
    first["exp_avg"].add_(1)
    torch.save(payload, checkpoint)
    receipt = json.loads(paths["continuous"].read_text())
    receipt["checkpoint"]["sha256"] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    receipt["checkpoint"]["bytes"] = checkpoint.stat().st_size
    paths["continuous"].write_text(json.dumps(receipt))
    report = compare_resume(
        paths["base"], paths["resumed"], model_kind="mlp",
        manifest=manifest_path, data_root=tmp_path, continuous=paths["continuous"],
        base_update=2, resumed_update=4,
    )
    assert report["status"] == "fail"
    checks = report["continuous_equivalence"]["checks"]
    assert checks["model_state"] is True
    assert checks["optimizer_state"] is False


def test_resume_comparator_does_not_claim_equivalence_without_control_or_manifest(tmp_path):
    manifest_path, paths = _make_resume_triplet(tmp_path, model_kind="mlp")
    no_control = compare_resume(
        paths["base"], paths["resumed"], model_kind="mlp",
        manifest=manifest_path, data_root=tmp_path, base_update=2, resumed_update=4,
    )
    assert no_control["status"] == "pass"
    assert no_control["continuous_equivalence"]["status"] == "not_assessed"
    assert no_control["continuous_equivalence"]["claim"] == "not_claimed"

    no_manifest = compare_resume(
        paths["base"], paths["resumed"], model_kind="mlp",
        base_update=2, resumed_update=4,
    )
    assert no_manifest["status"] == "fail"
    assert any(item["code"] == "sampling_continuation_unverified"
               for item in no_manifest["failures"])
