"""Contract tests for the read-only A8 cross-host root review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import core_cross_host_root_review as review
from scripts.core_cross_host_root_review import ReviewError, build_review, main


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns/core-v1"
ENV = CAMPAIGN / "environments/cross-host-py312-torch212-cu132-v1"
CANARY = CAMPAIGN / "reproduction/a8-cross-host-frontier-canary20-v2"


def _paths() -> dict[str, Path]:
    return {
        "root": ROOT,
        "ada_record": ENV / "records/ada-import.json",
        "h200_record": ENV / "records/h200-import-remote.json",
        "ada_spec": ENV / "specs/ada-f3-cross-host-float64-canary20-v1-scheduled.json",
        "h200_spec": ENV / "specs/h200-f3-cross-host-float64-canary20-v1-scheduled.json",
        "ada_canary": CANARY / "ada/float64-canary.json",
        "h200_canary": CANARY / "h200/float64-canary.json",
        "canary_comparison": CANARY / "paired-float64-comparison.json",
        "a8_ada_report": CAMPAIGN / (
            "runtime/attempts/ada-a8-f3-mlp-seed17-v3-fullcase-reproduce-v1/"
            "20260920T055509-90f7455a5a24/reproduction/reproduction.json"
        ),
        "a8_h200_report": CAMPAIGN / "reproduction/a8-full-reproduce-v1/collected/h200/reproduction/reproduction.json",
        "a8_comparison": CAMPAIGN / "reproduction/a8-full-reproduce-v1/paired-comparison-v1.json",
        "a8_root_review": CAMPAIGN / "reproduction/a8-full-reproduce-v1/paired-root-verification-v1.json",
        "metadata_root": CAMPAIGN / "reproduction/h200-model-bundle-metadata",
    }


def test_real_pair_is_admitted_as_diagnostic_cross_host_evidence() -> None:
    report = build_review(**_paths())

    assert report["status"] == "pass"
    assert report["decision"] == {
        "true_cross_host_canary": True,
        "full_horizon_paired_diagnostic": True,
        "full_product_reproduction": False,
        "scientific_qualification": False,
        "formal_training_admission": False,
        "formal_training_count": 0,
    }
    assert report["canary"]["paired_comparison"]["steps"] == 20
    assert report["canary"]["paired_comparison"]["frames"] == 21
    assert report["a8_full_horizon"]["transitions"] == 835
    assert report["execution_constraints"]["central_registry_mutation"] == 0
    assert report["execution_constraints"]["central_ledger_mutation"] == 0


def test_same_hostname_relocation_is_rejected(tmp_path: Path) -> None:
    paths = _paths()
    record = json.loads(paths["h200_record"].read_text())
    record["hostname"] = json.loads(paths["ada_record"].read_text())["hostname"]
    relocated = tmp_path / "relocated-h200-probe.json"
    relocated.write_text(json.dumps(record))
    paths["h200_record"] = relocated

    with pytest.raises(ReviewError, match="same physical hostname") as caught:
        build_review(**paths)
    assert caught.value.code == "SAME_HOST_RELOCATION_REJECTED"


def test_metadata_fallback_is_hash_bound_and_never_formal() -> None:
    report = build_review(**_paths())
    fallback = report["identity"]["metadata_fallback"]
    assert fallback["execution_role"] == "identity_fallback_only"
    assert fallback["identity"]["manifest"] == report["identity"]["manifest_sha256"]
    assert fallback["identity"]["checkpoint"] == report["identity"]["checkpoint_sha256"]
    assert fallback["identity"]["core_models"] == report["identity"]["core_models_sha256"]
    assert report["decision"]["formal_training_count"] == 0


def test_environment_probe_duplicate_package_cannot_hide_lineage_drift() -> None:
    paths = _paths()
    ada = json.loads(paths["ada_record"].read_text())
    h200 = json.loads(paths["h200_record"].read_text())
    ada["packages"].append(dict(ada["packages"][0]))

    with pytest.raises(ReviewError) as caught:
        review.validate_host_pair(ada, h200)

    assert caught.value.code == "PACKAGE_DUPLICATE"


def test_malformed_gpu_uuid_cannot_satisfy_external_host_identity() -> None:
    paths = _paths()
    ada = json.loads(paths["ada_record"].read_text())
    h200 = json.loads(paths["h200_record"].read_text())
    ada["driver_query"]["stdout"] = ada["driver_query"]["stdout"].replace(
        "GPU-", "GPU-not-a-uuid-", 1
    )

    with pytest.raises(ReviewError) as caught:
        review.validate_host_pair(ada, h200)

    assert caught.value.code == "GPU_IDENTITY_INVALID"


def test_symlinked_json_input_is_rejected_before_cross_host_review(tmp_path: Path) -> None:
    paths = _paths()
    target = tmp_path / "record.json"
    target.write_text(paths["ada_record"].read_text(), encoding="utf-8")
    link = tmp_path / "record-link.json"
    link.symlink_to(target)

    with pytest.raises(ReviewError) as caught:
        review._load_json(link)

    assert caught.value.code == "FILE_OPEN_FAILED"


def test_cli_writes_review_without_formal_job_or_central_mutation(tmp_path: Path) -> None:
    paths = _paths()
    output = tmp_path / "a8-root-review.json"
    argv = []
    for key, value in paths.items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    argv.extend(["--output", str(output)])

    assert main(argv) == 0
    report = json.loads(output.read_text())
    assert report["schema"] == "core.a8.cross_host_root_review.v1"
    assert report["execution_constraints"]["formal_runs_started"] == 0
    assert report["execution_constraints"]["submitted"] is False
    assert report["execution_constraints"]["central_registry_mutation"] == 0
    assert report["execution_constraints"]["central_ledger_mutation"] == 0
