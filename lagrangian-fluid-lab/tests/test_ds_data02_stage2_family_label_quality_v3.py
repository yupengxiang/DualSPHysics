from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_v3.py"
spec = importlib.util.spec_from_file_location("family_label_quality_v3", SCRIPT)
assert spec and spec.loader
QUALITY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(QUALITY)


def test_recovery_source_role_is_derived_from_bound_config() -> None:
    report = {
        "schema": QUALITY._BASE.RECOVERY_REPORT_SCHEMA,
        "source_contract": {
            "config": {
                "moving_source_semantics": {
                    "source_labels": "native initial MK is fixed to typed identity"
                }
            }
        },
    }
    assert QUALITY._source_role(report)[0] == "native_initial_mk"


def test_policy_rejects_fabricated_recovery_safe(tmp_path: Path) -> None:
    payload = {
        "schema": QUALITY.MANIFEST_SCHEMA,
        "split_policy": {
            "unit": "complete_physical_case",
            "identity_level_split": False,
            "effective_component_audit_external": True,
            "recovery_safe": True,
        },
        "entries": [{
            "family_id": "F2", "physical_case_id": "P", "split": "development",
            "report": str(tmp_path / "report.json"), "labels_h5": str(tmp_path / "labels.h5"),
        }],
    }
    with pytest.raises(QUALITY.QualityV3Error, match="recovery_safe"):
        QUALITY._validate_manifest_payload(payload, check_paths=False, verify_artifacts=False)


@pytest.mark.skipif(
    not Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2/f2-s1-trajectory-labels-recovery-v2-root-forward-001/f2-s1-trajectory-labels-recovery-v2.json").is_file(),
    reason="actual F2 recovery report is not mounted",
)
def test_actual_recovery_normalizes_missing_top_level_family_id() -> None:
    base = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
    report = base / "STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2/f2-s1-trajectory-labels-recovery-v2-root-forward-001/f2-s1-trajectory-labels-recovery-v2.json"
    labels = base / "STAGE2_F2_S1_TRAJECTORY_LABELS_V1/f2-s1-trajectory-labels-v1-primary-001-root-forward-001/f2-s1-trajectory-labels-v1.h5"
    payload = {
        "schema": QUALITY.MANIFEST_SCHEMA,
        "split_policy": {
            "unit": "complete_physical_case", "identity_level_split": False,
            "effective_component_audit_external": True, "recovery_safe": False,
        },
        "entries": [{
            "entry_key": "f2-recovery", "family_id": "F2",
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "report": str(report), "labels_h5": str(labels),
            "source_role": "native_initial_mk", "split": "development",
        }],
    }
    normalized = QUALITY._validate_manifest_payload(payload, check_paths=True, verify_artifacts=False)
    assert normalized[0]["family_id"] == "F2"
    assert normalized[0]["source_role"] == "native_initial_mk"
    # The recovered report has no top-level family_id; this assertion guards
    # against reintroducing the old raw-report comparison.
    assert "family_id" not in json.loads(report.read_text())
