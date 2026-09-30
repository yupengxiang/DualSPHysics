"""Focused contract checks for the DS-DATA-02 F3 family package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ds_data02_f3 as f3


def test_event_and_observation_contracts_are_explicit() -> None:
    events = f3._event_definitions()
    observations = f3._observation_plan()

    assert {item["frame_id"] for item in events["coordinate_frames"]} == {
        "fixed_tank_acceleration",
        "moving_tank_world",
    }
    assert {item["mechanism_id"] for item in f3.MECHANISMS.values()} == {
        "dual_axis_phase",
        "eccentric_baffle_exchange",
    }
    assert len(observations["two_by_three_reference_matrix"]["matrix"]) == 6
    assert observations["integration_step_study"]["status"] == "planned_no_solver"
    assert observations["sampling_cadence_study"]["status"] == "planned_no_solver"
    required_labels = {item["field"] for item in events["required_labels"]}
    assert {"source_label", "first_passage_interval", "residence_time_s", "unknown_mass_kg"} <= required_labels


@pytest.mark.skipif(
    not f3.HISTORICAL_ROOT.is_dir(),
    reason="the read-only historical F3 source tree is not mounted",
)
def test_generate_and_validate_preserve_history_and_leave_new_slots_pending(tmp_path: Path) -> None:
    output_root = tmp_path / "F3"
    audit = f3.generate_family(output_root, inspect_hdf5=False)
    report = f3.validate_family(output_root)

    assert report["valid"] is True
    assert audit["summary"]["canonical_case_count"] == 32
    assert audit["summary"]["reusable_historical_count"] == 0
    assert audit["summary"]["native_transport_labels_materialized_count"] == 0
    assert audit["portable_reuse"]["native_case_count"] == 0

    rows = [json.loads(line) for line in (output_root / "case_registry.jsonl").read_text().splitlines()]
    assert len(rows) == 48
    assert sum(row["status"] == "reused_historical_candidate" for row in rows) == 32
    assert sum(row["status"] == "planned_no_solver" for row in rows) == 16
    assert {row["solver_dimension"] for row in rows if row["status"] == "planned_no_solver"} == {
        "pending_actual_solver_output"
    }


@pytest.mark.skipif(
    not f3.HISTORICAL_ROOT.is_dir(),
    reason="the read-only historical F3 source tree is not mounted",
)
def test_light_history_audit_counts_native_3d_tracks() -> None:
    audit = f3.audit_history(inspect_hdf5=True)
    summary = audit["summary"]

    assert summary["canonical_case_count"] == 32
    assert summary["physical_case_count"] == 32
    assert summary["old_split_counts"] == {"test": 12, "train": 16, "validation": 4}
    assert summary["actual_solver_dimension_3_count"] == 32
    assert summary["light_header_pass_count"] == 32
    assert summary["reusable_historical_count"] == 32
    assert summary["reusable_new_mechanism_count"] == 0
    assert audit["portable_reuse"]["native_case_count"] == 32
    assert summary["duplicate_hdf5_hash_count"] == 0
    assert summary["duplicate_source_hash_group_count"] >= 1
    assert len(audit["material_archive"]["duplicate_groups"]) >= 1
