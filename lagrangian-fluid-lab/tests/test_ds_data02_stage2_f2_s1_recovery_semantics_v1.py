from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_s1_recovery_semantics_v1.py"
spec = importlib.util.spec_from_file_location("f2_recovery_semantics_v1", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def test_event_direction_maps_negative_axis_to_entry_mass() -> None:
    report = {
        "schema": MODULE.REPORT_SCHEMA,
        "status": "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5",
        "physical_case_id": "P",
        "case_key": "F2/P",
        "source_contract": {
            "current": {"path": "/tmp/CURRENT.json", "sha256": "a" * 64},
            "trajectory_hdf5": {"path": "/tmp/source.h5", "sha256": "b" * 64, "bytes": 10},
            "config": {},
        },
        "output_hdf5": {"path": "/tmp/labels.h5", "sha256": "c" * 64, "bytes": 20},
        "recovery": {"source_trajectory_h5_opened": False, "source_trajectory_h5_rehashed": False,
                      "input_h5_sha256": "c" * 64},
        "read_policy": {"h5_opened": True, "trajectory_content_opened": True},
        "events": [{
            "id": "entry_zm", "axis": "z", "entry_direction": "-z",
            "positive_axis_mass_kg": 2.0, "negative_axis_mass_kg": 8.0,
            "entry_direction_mass_kg": 8.0, "exit_direction_mass_kg": 2.0,
            "entry_direction_net_flux_mass_kg": 6.0,
            "observed_first_passage_mass_kg": 7.0,
            "censored_first_passage_mass_kg": 3.0,
            "repeated_crossing_particles": 1,
            "operator_column_semantics": "column0=negative-to-positive; column1=positive-to-negative",
        }],
    }
    assert MODULE._event_semantics(report)[0]["entry_direction_mass_kg"] == 8.0


def test_report_binding_requires_recovered_h5_read_and_original_h5_exclusion() -> None:
    report = {
        "schema": MODULE.REPORT_SCHEMA,
        "status": "TRAJECTORY_LABELS_RECOVERED_FROM_COMPLETED_H5",
        "physical_case_id": "P", "source_contract": {
            "current": {}, "trajectory_hdf5": {"path": "/tmp/source.h5", "sha256": "b" * 64},
        },
        "output_hdf5": {"path": "/tmp/labels.h5", "sha256": "c" * 64},
        "recovery": {"source_trajectory_h5_opened": False, "source_trajectory_h5_rehashed": False,
                      "input_h5_sha256": "c" * 64},
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False},
    }
    with pytest.raises(MODULE.RecoverySemanticsError, match="recovered label H5 content"):
        MODULE._report_binding(report)


@pytest.mark.skipif(
    not Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2/f2-s1-trajectory-labels-recovery-v2-root-forward-001/f2-s1-trajectory-labels-recovery-v2.json").is_file(),
    reason="actual F2 recovery product is not mounted",
)
def test_actual_recovery_sidecar_does_not_open_h5(tmp_path: Path) -> None:
    base = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TRAJECTORY_LABELS_RECOVERY_V2/f2-s1-trajectory-labels-recovery-v2-root-forward-001")
    output = tmp_path / "sidecar.json"
    result = MODULE.build(base / "f2-s1-trajectory-labels-recovery-v2.json", base / "execution-receipt.json", output)
    assert result["read_scope"]["this_worker_opened_h5"] is False
    assert result["read_scope"]["recovered_label_h5_opened_and_summarized_by_producer"] is True
    assert result["mass_and_censoring"]["combined_value_is_accounting_only"] is True
    assert any(item["configured_entry_direction"] == "-z" for item in result["events"])
