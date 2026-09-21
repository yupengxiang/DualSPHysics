import json
from pathlib import Path
import torch

from scripts.core_learning import train_model
from scripts.core_preprofile_collector import collect_preprofile, sha256_file
from test_core_contract import tiny_manifest
from scripts.core_dataset import CoreDataset


def _synthetic_protocol():
    return {
        "updates": 2,
        "centers_per_update": 1,
        "hidden": 8,
        "learning_rate": 1e-3,
        "checkpoint_every": 1,
        "log_every": 1,
        "validation_every": 0,
        "normalization_transitions": 1,
    }


def _three_synthetic_receipts(tmp_path):
    manifest = tiny_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    receipts = {}
    with CoreDataset(manifest, tmp_path) as data:
        for kind in ("mlp", "graph_raw", "graph_residual"):
            checkpoint = tmp_path / f"{kind}.pt"
            output = tmp_path / f"{kind}.json"
            progress = tmp_path / f"{kind}-progress.json"
            receipts[kind] = train_model(
                data, model_kind=kind, seed=17, updates=2, centers_per_update=1,
                hidden=8, normalization_transitions=1, checkpoint=checkpoint,
                output=output, progress_output=progress, checkpoint_every=1,
                log_every=1, validation_every=0, run_id=f"{kind}-seed17",
                evaluate_milestones=False,
            )
    paths = {}
    for kind, receipt in receipts.items():
        path = tmp_path / f"{kind}-receipt.json"
        path.write_text(json.dumps(receipt))
        paths[kind] = path
    return manifest_path, paths


def test_collector_pairs_complete_outputs_and_reports_limits(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    report = collect_preprofile(
        receipts, manifest=manifest_path, expected_protocol=_synthetic_protocol(),
        output=tmp_path / "collection.json",
    )

    assert report["status"] == "pass"
    assert report["failure_count"] == 0
    assert report["read_only"] is True
    assert report["hdf5_opened"] is False
    assert report["manifest"]["train_case_ids"] == ["tiny"]
    assert report["cross_model"]["shared_normalization"] is True
    assert report["cross_model"]["shared_target_scale"] is True
    assert report["cross_model"]["paired_sampler_state"] is True
    assert report["cross_model"]["paired_model_initialization_reconstruction"] is True
    assert report["cross_model"]["raw_residual_topology"] is True
    assert report["cross_model"]["residual_prior"]["checkpoint_runtime_attested"] is True
    assert report["protocol"]["normalization_transition_count"]["attested_by_checkpoint"] is True
    assert any("output attestation" in item
               for item in report["evidence_limits"])
    persisted = json.loads((tmp_path / "collection.json").read_text())
    assert persisted["schema"] == "core.preprofile_collection.v1"


def test_collector_rejects_checkpoint_receipt_normalization_mismatch(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    path = receipts["graph_raw"]
    receipt = json.loads(path.read_text())
    receipt["normalization"]["target_mean"][0] += 1.0
    path.write_text(json.dumps(receipt))
    report = collect_preprofile(receipts, manifest=manifest_path,
                                expected_protocol=_synthetic_protocol())
    assert report["status"] == "fail"
    assert any(item["code"] == "receipt_checkpoint_normalization_mismatch"
               and item["model_kind"] == "graph_raw" for item in report["failures"])


def test_collector_requires_all_three_members(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    del receipts["graph_residual"]
    report = collect_preprofile(receipts, manifest=manifest_path,
                                expected_protocol=_synthetic_protocol())
    assert report["status"] == "fail"
    assert any(item["code"] == "receipt_missing" and item["model_kind"] == "graph_residual"
               for item in report["failures"])
    assert report["cross_model"]["all_members_present"] is False


def test_collector_binds_normalization_budget_to_each_job_spec(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    jobs = []
    for kind, receipt_path in receipts.items():
        spec_path = tmp_path / f"{kind}.job.json"
        spec_path.write_text(json.dumps({
            "argv": [
                "python", "scripts/core_learning.py", "train", "--model", kind,
                "--seed", "17", "--updates", "2", "--centers", "1", "--hidden", "8",
                "--learning-rate", "0.001", "--normalization-transitions", "1",
                "--checkpoint-every", "1", "--log-every", "1", "--validation-every", "0",
                "--no-evaluate-milestones",
            ],
        }))
        jobs.append({"job_id": f"{kind}-job", "model_kind": kind,
                     "path": str(spec_path), "sha256": sha256_file(spec_path)})
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({
        "schema": "core.formal_preprofile_job_set.v2",
        "dataset": {"manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)}},
        "training_protocol": _synthetic_protocol(), "jobs": jobs,
    }))
    report = collect_preprofile(receipts, manifest=manifest_path, index=index_path)
    assert report["status"] == "pass"
    assert report["protocol"]["normalization_transition_count"]["attested_by_job_spec"] is True
    assert report["protocol"]["source"]["sha256"] == sha256_file(index_path)


def test_collector_marks_legacy_checkpoint_evidence_missing(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    path = receipts["mlp"]
    receipt = json.loads(path.read_text())
    checkpoint_path = receipt["checkpoint"]["path"]
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    payload.pop("evidence", None)
    payload.pop("evidence_status", None)
    torch.save(payload, checkpoint_path)
    receipt["checkpoint"]["sha256"] = sha256_file(checkpoint_path)
    receipt["checkpoint"]["bytes"] = Path(checkpoint_path).stat().st_size
    receipt.pop("evidence", None)
    receipt.pop("evidence_status", None)
    path.write_text(json.dumps(receipt))
    report = collect_preprofile(receipts, manifest=manifest_path,
                                expected_protocol=_synthetic_protocol())
    assert report["status"] == "fail"
    assert any(item["code"] == "evidence_missing_legacy" and item["model_kind"] == "mlp"
               for item in report["failures"])
    assert report["models"]["mlp"]["checkpoint"]["evidence_status"] == "missing_legacy"


def test_collector_rejects_receipt_evidence_tampering(tmp_path):
    manifest_path, receipts = _three_synthetic_receipts(tmp_path)
    path = receipts["graph_residual"]
    receipt = json.loads(path.read_text())
    receipt["evidence"]["initialization"]["parameter_digest"] = "f" * 64
    path.write_text(json.dumps(receipt))
    report = collect_preprofile(receipts, manifest=manifest_path,
                                expected_protocol=_synthetic_protocol())
    assert report["status"] == "fail"
    assert any(item["code"] == "receipt_checkpoint_evidence_mismatch"
               and item["model_kind"] == "graph_residual" for item in report["failures"])
