from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_source_closed_development_split_v25.py"
spec = importlib.util.spec_from_file_location("source_closed_development_split_v25", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
QUALITY_MANIFEST = ROOT / "campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
QUALITY_REPORT = DATA / "families/infra/DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
QUALITY_RECEIPT = QUALITY_REPORT.parent / "execution-receipt.json"
MECHANISM_REPORT = DATA / "families/infra/STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V3/omission-mechanism-probe-v3-forward-002-primary-001-root-001/omission-mechanism-probe-v3-forward-002.json"
MECHANISM_RECEIPT = MECHANISM_REPORT.parent / "execution-receipt.json"
V24_PREDICTED = ROOT / "campaigns/ds-data-02/stage2/requests/effective-condition-cards-v24-forward-002/seven-effective-condition-cards-v24.json"
V24_ACTUAL = DATA / "families/infra/DS02_STAGE2_EFFECTIVE_CONDITION_CARDS_V24/seven-effective-condition-cards-v24-forward-002-root-forward-030-001/seven-effective-condition-cards-v24.json"
V24_PROOF = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/SEVEN_EFFECTIVE_CONDITION_CARDS_V24_ACTUAL_INDEPENDENT_VERIFICATION_001.json"


def _mounted() -> bool:
    return all(path.is_file() for path in (CURRENT, QUALITY_MANIFEST, QUALITY_REPORT, QUALITY_RECEIPT, MECHANISM_REPORT, MECHANISM_RECEIPT, V24_PREDICTED, V24_ACTUAL, V24_PROOF))


def test_development_role_mapping_is_metadata_only() -> None:
    assert MODULE._development_role("development") == "development_train"
    assert MODULE._development_role("development_validation") == "development_validation"
    assert MODULE._development_role("development_test") == "development_test"
    assert MODULE._development_role("other") == "development_unassigned"


@pytest.mark.skipif(not _mounted(), reason="actual stage2 v24/quality/mechanism products are not mounted")
def test_actual_v25_split_closes_aliases_without_cross_role_credit(tmp_path: Path) -> None:
    output = tmp_path / "split.json"
    manifest = tmp_path / "manifest.json"
    result = MODULE.build(
        CURRENT, QUALITY_MANIFEST, QUALITY_REPORT, QUALITY_RECEIPT,
        MECHANISM_REPORT, MECHANISM_RECEIPT, V24_PREDICTED, V24_ACTUAL,
        V24_PROOF, manifest, output,
    )
    assert result["status"] == "PREPARED_SOURCE_CLOSED_DEVELOPMENT_SPLIT_V24_ACTUAL_VERIFIED_NO_PHYSICAL_QUALIFICATION"
    assert result["verification"]["v24_predicted_cards_preserved"] is True
    assert result["verification"]["v24_actual_cards_root_verified"] is True
    closure = result["mechanism_alias_semantic_closure"]
    assert closure["case_count"] == 118
    assert closure["family_counts"] == {"F2": 48, "F4": 22, "F6": 48}
    assignments = {row["family_id"]: row for row in result["development_split"]["assignments"]}
    assert assignments["F1"]["source_role"] == "native_initial_mk"
    assert assignments["F3"]["source_role"] == "initial_spatial_region"
    assert assignments["F3"]["saved_frame_role"] == "development_test"
    assert result["development_split"]["cross_component_transfer_edges"] == []
    assert result["development_split"]["physical_qualification"] == "UNKNOWN"
    assert result["read_policy"]["materialized_label_h5_opened"] is False
    assert result["read_policy"]["original_trajectory_h5_opened"] is False
    assert result["read_policy"]["mechanism_particle_observations_copied"] is False
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["schema"] == MODULE.MANIFEST_SCHEMA
    assert manifest_payload["mechanism_v3"]["alias_semantic_closure"].startswith("exact")


@pytest.mark.skipif(not _mounted(), reason="actual stage2 v24/quality/mechanism products are not mounted")
def test_v25_request_source_cost_excludes_scientific_payloads(tmp_path: Path) -> None:
    predicted_request = ROOT / "campaigns/ds-data-02/stage2/requests/effective-condition-cards-v24-forward-002/seven-effective-condition-cards-v24-forward-002-request.json"
    actual_request = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/seven-effective-condition-cards-v24-root-forward-030-001.json"
    output = tmp_path / "request.json"
    request = MODULE.make_request(
        CURRENT, QUALITY_MANIFEST, QUALITY_REPORT, QUALITY_RECEIPT,
        MECHANISM_REPORT, MECHANISM_RECEIPT, V24_PREDICTED, V24_ACTUAL,
        V24_PROOF, predicted_request, actual_request, output,
        runtime_root=PRIMARY,
        worker_root=Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics"),
    )
    assert request["launch_allowed"] is True
    assert request["v24_predicted_cards_preserved"] is True
    assert request["v24_actual_cards_required_root_verified"] is True
    assert request["source_cost"]["materialized_label_h5_bytes_read"] == 0
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert all(Path(path).suffix.lower() not in {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"} for path in request["input_files"])
