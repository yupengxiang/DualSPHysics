from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_bounded_development_catalog_v26.py"
spec = importlib.util.spec_from_file_location("bounded_development_catalog_v26", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)

DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
V25 = ROOT / "campaigns/ds-data-02/stage2/requests/source-closed-development-split-v25-forward-003/current336-source-closed-development-split-v25.json"
V25_MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/source-closed-development-split-v25-forward-003/current336-task-evidence-manifest-v25.json"
V25_PROOF = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/SOURCE_CLOSED_DEVELOPMENT_SPLIT_V25_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
QUALITY_MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
QUALITY_REPORT = DATA / "families/infra/DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
QUALITY_RECEIPT = QUALITY_REPORT.parent / "execution-receipt.json"
MECHANISM_REPORT = DATA / "families/infra/STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V3/omission-mechanism-probe-v3-forward-002-primary-001-root-001/omission-mechanism-probe-v3-forward-002.json"
MECHANISM_RECEIPT = MECHANISM_REPORT.parent / "execution-receipt.json"
FULL_RAW = {
    family: PRIMARY / f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/{name}"
    for family, name in {
        "F4": "F4_FULL1201_RAW_RECONSTRUCTION_ACTUAL_INDEPENDENT_VERIFICATION_001.json",
        "F5": "F5_FULL801_RAW_RECONSTRUCTION_ACTUAL_INDEPENDENT_VERIFICATION_001.json",
        "F6": "F6_FULL241_RAW_RECONSTRUCTION_ACTUAL_INDEPENDENT_VERIFICATION_001.json",
        "F7": "F7_FULL601_RAW_RECONSTRUCTION_ACTUAL_INDEPENDENT_VERIFICATION_001.json",
    }.items()
}


def _mounted() -> bool:
    return all(path.is_file() for path in (CURRENT, V25, V25_MANIFEST, V25_PROOF, QUALITY_MANIFEST,
                                           QUALITY_REPORT, QUALITY_RECEIPT, MECHANISM_REPORT, MECHANISM_RECEIPT,
                                           *FULL_RAW.values()))


@pytest.mark.skipif(not _mounted(), reason="root v25/quality/mechanism/full-raw products are not mounted")
def test_catalog_exposes_all336_and_bounded_scopes_without_hiding_cases(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "catalog.json"
    result = MODULE.build(CURRENT, V25, V25_MANIFEST, V25_PROOF, QUALITY_MANIFEST, QUALITY_REPORT,
                          QUALITY_RECEIPT, MECHANISM_REPORT, MECHANISM_RECEIPT, FULL_RAW, manifest, output)
    assert result["status"] == "PREPARED_EXACT_CURRENT336_BOUNDED_TASK_SCOPE_NO_PHYSICAL_QUALIFICATION"
    assert result["coverage"]["current_case_count"] == 336
    assert result["coverage"]["hidden_current_cases"] == 0
    assert len(result["cases"]) == 336
    assert {row["current_index"] for row in result["cases"]} == set(range(336))
    assert len(result["task_case_keys"]["owner_control_geometry_metadata"]) == 336
    assert len(result["task_case_keys"]["saved_frame_artifact"]) == 7
    assert len(result["task_case_keys"]["native_cause_alias_join"]) == 118
    assert result["failure_censoring_summary"]["physical_destination_known"] == 0
    assert result["read_policy"]["materialized_label_h5_opened_by_this_worker"] is False
    assert result["read_policy"]["original_trajectory_h5_opened_by_this_worker"] is False
    assert result["read_policy"]["part_bi4_opened_by_this_worker"] is False
    assert result["family_cards"]["F4"]["full_raw_reconstruction_proof"]["status"].startswith("PASS_ACTUAL")
    assert result["family_cards"]["F1"]["full_raw_reconstruction_proof"] is None
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["schema"] == MODULE.MANIFEST_SCHEMA
    assert len(manifest_payload["cases"]) == 336
    assert manifest_payload["v25"]["actual_verification_proof"]["status"] == "PASS_ACTUAL_SEVEN_SOURCE_CLOSED_DEVELOPMENT_COMPONENT_ROLES"


@pytest.mark.skipif(not _mounted(), reason="root v25/quality/mechanism/full-raw products are not mounted")
def test_catalog_request_is_small_json_only_and_exactly_bound(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request = MODULE.make_request(CURRENT, V25, V25_MANIFEST, V25_PROOF, QUALITY_MANIFEST, QUALITY_REPORT,
                                  QUALITY_RECEIPT, MECHANISM_REPORT, MECHANISM_RECEIPT, FULL_RAW, request_path,
                                  PRIMARY, ROOT.parent)
    assert request["launch_allowed"] is True
    assert request["coverage_contract"] == {"exact_current_case_count": 336, "hidden_current_cases": 0,
                                             "native_alias_cases": 118, "seven_anchor_cards": 7}
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert all(Path(path).suffix.lower() not in MODULE.FORBIDDEN_SUFFIXES for path in request["input_files"])
    assert str(V25_PROOF) in request["input_files"]


def test_proof_validator_rejects_unverified_or_qualified_proof(tmp_path: Path) -> None:
    proof = {
        "schema": "ds02.stage2.f4-full1201-raw-reconstruction-independent.v1",
        "status": "PASS_ACTUAL_FULL_RAW_RECONSTRUCTION_BYTE_IDENTICAL_CURRENT_TYPED",
        "root_original_reference_h5_reread": False,
        "root_new_reconstructed_h5_byte_hash_read": False,
        "scientific_qualification": {"QN": "KNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN"},
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(MODULE.CatalogError):
        MODULE._validate_full_raw_proof(path, proof, "F4")
