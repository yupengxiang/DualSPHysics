from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_v2.py"
spec = importlib.util.spec_from_file_location("family_label_quality_v2", SCRIPT)
assert spec and spec.loader
QUALITY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(QUALITY)


def test_strict_complete_boolean_policy() -> None:
    assert QUALITY._strict_true(np.bool_(True), np) is True
    assert QUALITY._strict_true(True, np) is True
    assert QUALITY._strict_true("False", np) is False
    assert QUALITY._strict_true("True", np) is False
    assert QUALITY._strict_true(1, np) is False


@pytest.mark.skipif(
    not Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_LOWER_HEAD_V1/f1-family-label-canary-v2-lowerhead-root-forward-001/label-report.json").is_file(),
    reason="actual F1 materialized canary is not mounted",
)
def test_actual_f1_quality_allows_one_exposed_development_case(tmp_path: Path) -> None:
    base = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_ECC_THICK_DBC_LOWER_HEAD_V1/f1-family-label-canary-v2-lowerhead-root-forward-001")
    entries = [{
        "entry_key": "F1-lowerhead",
        "family_id": "F1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "report": str(base / "label-report.json"),
        "labels_h5": str(base / "native-labels.h5"),
        "split": "development",
    }]
    manifest_path = tmp_path / "manifest.json"
    QUALITY.make_manifest(entries, manifest_path)
    manifest = QUALITY.read_json(manifest_path, "manifest")[1]
    assert manifest["split_policy"]["effective_component_audit_external"] is True
    assert "effective_split_audit" not in manifest
    output = tmp_path / "quality.json"
    result = QUALITY.run(manifest_path, output)
    assert result["status"] == "FAMILY_LABEL_QUALITY_V2_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND"
    assert result["manifest"]["entry_count"] == 1
    assert result["cases"][0]["split_scope"]["recovery_safe"] is False
    assert result["cases"][0]["split_scope"]["family_leakage_checked"] is False
    assert result["read_policy"]["original_trajectory_h5_opened"] is False


def test_manifest_rejects_missing_external_split_policy(tmp_path: Path) -> None:
    payload = {
        "schema": QUALITY.MANIFEST_SCHEMA,
        "split_policy": {"unit": "complete_physical_case", "identity_level_split": False},
        "entries": [],
        "claim_boundary": {},
    }
    with pytest.raises(QUALITY.QualityError, match="effective split proof external"):
        QUALITY._validate_manifest_payload(payload, check_paths=False, verify_artifacts=False)

