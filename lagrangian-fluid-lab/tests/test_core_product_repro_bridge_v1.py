import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import core_product_repro_bridge_v1 as bridge


LAB = Path(__file__).resolve().parents[1]


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _fixture(tmp_path, *, bundle_schema="core.reader_bundle.v2"):
    root = tmp_path / "lab"
    lab = root / "lagrangian-fluid-lab"
    bundle = lab / "bundle"
    bundle.mkdir(parents=True)

    # Reuse the production F3/F4 manifest shapes without touching their source
    # files.  The bridge's preflight is metadata-only and does not open the
    # referenced trajectories or input assets.
    f3_manifest = lab / "f3-manifest.json"
    f4_manifest = lab / "f4-manifest.json"
    shutil.copy2(LAB / "campaigns/core-v1/f3-dataset-v2.json", f3_manifest)
    shutil.copy2(
        LAB / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
        "f4-tallwall120-formal-reader-manifest-v2-compact.json",
        f4_manifest,
    )

    dataset = {"schema": "core.dataset.v2", "cases": [{"case_id": "fixture"}]}
    dataset_path = _write_json(bundle / "dataset.json", dataset)
    dataset_sha = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    bundle_index = {
        "schema": bundle_schema,
        "case_count": 1,
        "checkpoint_count": 0,
        "files": [{
            "path": "dataset.json",
            "bytes": dataset_path.stat().st_size,
            "sha256": dataset_sha,
        }],
    }
    bundle_index_path = _write_json(bundle / "bundle.json", bundle_index)

    for name in (
        "core_package.py",
        "core_benchmark.py",
        "core_campaign.py",
        "core_independent_reproduction.py",
        "core_strict_json.py",
    ):
        _write_json(lab / "scripts" / name, {"fixture": name})

    f3_reader = _write_json(lab / "f3-reader.json", {
        "schema": "core.verification.v1", "passed": True, "case_count": 32,
    })
    f4_reader = _write_json(lab / "f4-reader.json", {
        "schema": "local.f4.core_reader_smoke.stdout.v1",
        "operation": {"source_hash_verification": {"passed": 32, "total": 32}},
        "reader_result": {"dataset_opened": True, "diagnostic_only": True,
                          "qualification_credit": 0},
    })
    f8 = _write_json(lab / "f8.json", {
        "schema": "core.cfd.f8.r008.synthetic_receipt.v1",
        "status": "diagnostic_only_synthetic",
        "authorization": {
            "diagnostic_only": True, "formal": False,
            "qualification_credit": 0, "readiness_pass": False,
        },
    })
    pair = _write_json(lab / "diagnostic-pair.json", {
        "schema": "core.a8.cross_host_diagnostic_pair_audit.v1",
        "comparator_result_schema": "core.model_reproduction.comparison.v1",
        "passed": True,
        "observed_hosts": ["ada", "h200"],
        "distinct_host_evidence": True,
        "score": {
            "passed": True,
            "cases": {"fixture": {
                "expected_frames": 3,
                "left_complete": True,
                "right_complete": True,
                "absolute_score_difference": 0.0,
            }},
        },
        "trajectory": {"fixture": {"passed": True}},
        "evidence": {
            "diagnostic_only": True,
            "formal_training": False,
            "qualification_credit": 0,
        },
    })
    local_check = _write_json(lab / "bundle-local-check.json", {
        "schema": "core.a8.bundle_local_check.v1",
        "reader_preflight": {"passed": True},
        "full_core_package_verify": "deferred",
    })
    outputs = {
        "manifest_output": lab / "manifest.json",
        "receipt_output": lab / "receipt.json",
        "report_output": lab / "report.json",
    }
    return {
        "root": root,
        "bundle": bundle,
        "f3_manifest": f3_manifest,
        "f4_manifest": f4_manifest,
        "f3_reader_report": f3_reader,
        "f4_reader_report": f4_reader,
        "f8_reports": (f8,),
        "diagnostic_pair": pair,
        "bundle_local_check": local_check,
        **outputs,
    }


def _assemble(fixture):
    return bridge.assemble(
        lab_root=fixture["root"],
        bundle=fixture["bundle"],
        f3_manifest=fixture["f3_manifest"],
        f4_manifest=fixture["f4_manifest"],
        f3_reader_report=fixture["f3_reader_report"],
        f4_reader_report=fixture["f4_reader_report"],
        f8_reports=fixture["f8_reports"],
        diagnostic_pair=fixture["diagnostic_pair"],
        bundle_local_check=fixture["bundle_local_check"],
        manifest_output=fixture["manifest_output"],
        receipt_output=fixture["receipt_output"],
        report_output=fixture["report_output"],
    )


def test_v2_fixture_assembles_all_coarse_stages_without_claims(tmp_path):
    fixture = _fixture(tmp_path)
    result = _assemble(fixture)
    report = result["report"]

    assert report["schema"] == bridge.REPORT_SCHEMA
    assert report["coarse_chain_passed"] is True
    assert report["local_package_ready"] is True
    assert report["diagnostic_only"] is True
    assert report["claims"] == bridge.FALSE_CLAIMS
    assert report["mutations"] == bridge.ZERO_MUTATIONS
    assert result["manifest"]["read_boundary"]["hdf5_opened"] is False
    assert result["manifest"]["read_boundary"]["checkpoint_opened"] is False
    assert result["receipt"]["cross_host_reproduction"] is False
    assert result["receipt"]["full_product_reproduction"] is False
    assert bridge.validate_outputs(
        manifest_path=fixture["manifest_output"],
        receipt_path=fixture["receipt_output"],
        report_path=fixture["report_output"],
        lab_root=fixture["root"],
    ) == []
    assert all(path.stat().st_size < bridge.MAX_BRIDGE_JSON_BYTES for path in (
        fixture["manifest_output"], fixture["receipt_output"], fixture["report_output"],
    ))


def test_legacy_v1_bundle_is_explicitly_blocked_and_diagnostic(tmp_path):
    fixture = _fixture(tmp_path, bundle_schema="core.reader_bundle.v1")
    result = _assemble(fixture)

    assert result["report"]["coarse_chain_passed"] is True
    assert result["report"]["local_package_ready"] is False
    assert any("legacy_or_unsupported_bundle_schema" in item
               for item in result["report"]["blockers"])
    assert result["receipt"]["claims"]["T1_numerical"] is False
    assert result["receipt"]["claims"]["T2_macro"] is False
    assert result["receipt"]["claims"]["credit"] == 0
    assert bridge.validate_outputs(
        manifest_path=fixture["manifest_output"],
        receipt_path=fixture["receipt_output"],
        report_path=fixture["report_output"],
        lab_root=fixture["root"],
    ) == []


def test_validate_rejects_claim_drift_and_cross_file_hash_drift(tmp_path):
    fixture = _fixture(tmp_path)
    _assemble(fixture)
    receipt = json.loads(fixture["receipt_output"].read_text())
    receipt["claims"]["credit"] = 1
    fixture["receipt_output"].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    errors = bridge.validate_outputs(
        manifest_path=fixture["manifest_output"],
        receipt_path=fixture["receipt_output"],
        report_path=fixture["report_output"],
        lab_root=fixture["root"],
    )
    assert any("receipt.claims.credit" in item for item in errors)
    assert any("report reproduction receipt hash mismatch" in item for item in errors)


def test_symlinked_json_input_is_rejected_before_binding(tmp_path):
    target = _write_json(tmp_path / "target.json", {"schema": "fixture.v1"})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(bridge.BridgeContractError, match="symlink"):
        bridge._portable_json_ref(link, tmp_path, label="fixture")


def test_cli_validate_is_read_only_and_succeeds_for_valid_chain(tmp_path):
    fixture = _fixture(tmp_path)
    _assemble(fixture)
    before = {
        path: path.read_bytes()
        for path in (fixture["manifest_output"], fixture["receipt_output"], fixture["report_output"])
    }
    assert bridge.main([
        "validate",
        "--lab-root", str(fixture["root"]),
        "--manifest", str(fixture["manifest_output"]),
        "--receipt", str(fixture["receipt_output"]),
        "--report", str(fixture["report_output"]),
    ]) == 0
    after = {
        path: path.read_bytes()
        for path in (fixture["manifest_output"], fixture["receipt_output"], fixture["report_output"])
    }
    assert after == before
