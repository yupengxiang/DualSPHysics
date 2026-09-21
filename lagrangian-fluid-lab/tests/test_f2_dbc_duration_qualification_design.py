from __future__ import annotations

import json
from pathlib import Path

from scripts import f2_dbc_duration_qualification_design as design
from scripts import f2_dbc_extension5s_collect as collector
from scripts import f2_dbc_extension5s_observer_v2 as observer_v2


LAB = Path(__file__).resolve().parents[1]


def test_dbc_design_has_independent_13_plus_2_rows_and_static_mass_passes():
    value = design.build_design(LAB)
    assert value["cell_count"] == 15
    assert value["spatial_cell_count"] == 13
    assert value["temporal_cell_count"] == 2
    assert value["event_window"]["registered_initial_window_s"] == 5.0
    assert value["event_window"]["maximum_extended_window_s"] == 5.0
    assert value["static_mass_status"] == {
        "all_15_rows_present": True,
        "all_mass_gates_pass": True,
        "mass_rescaling": False,
        "continuous_volume_m3": 0.023595,
        "native_count_is_resolution_dependent": True,
    }
    assert all(row["qualification_claim"] == "none" for row in value["cells"])
    assert all(row["canary_reuse"]["allowed"] is False for row in value["cells"])
    assert all(row["static_mass_check"]["mass_rescaling"] is False for row in value["cells"])
    assert {row["dp_m"] for row in value["cells"]} == {0.01, 0.0075, 0.005}


def test_dbc_design_uses_full_cup_contract_and_actual_time_control_provenance():
    value = design.build_design(LAB)
    fixed = value["fixed_physical_case"]
    assert fixed["fluid_boxes"] == [
        {
            "low": [0.0, -0.15, 0.65],
            "size": [0.425, 0.3, 0.18505882352941178],
            "mkfluid": 0,
        }
    ]
    assert fixed["catchment_wall_spec"]["floor"]["fluid_facing_surface_z_m"] == -0.2
    assert fixed["catchment_wall_spec"]["closed_faces"] == ["left", "right", "front", "back"]
    internal = next(row for row in value["cells"] if row["temporal_variant"] == "internal_time")
    assert internal["time_control"]["DtIni"] == design.INTERNAL_DT_INI_S
    assert internal["time_control"]["DtMin"] == design.INTERNAL_DT_MIN_S
    assert value["time_control_provenance"]["baseline_run_out"]["actual_dt_ini_s"] == design.BASELINE_ACTUAL_DT_INI_S
    assert value["time_control_provenance"]["baseline_run_out"]["actual_dt_min_s"] == design.BASELINE_ACTUAL_DT_MIN_S
    assert value["execution_status"].startswith("design_only")


def test_collection_refuses_partial_h5_without_opening_it(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "worker-status.json").write_text(json.dumps({"status": "running"}))
    (product / "trajectory.h5.partial").write_bytes(b"sentinel")
    out = tmp_path / "collection.json"
    report = collector.collect(product, out)
    assert report["collection_status"] == "pending"
    assert report["h5_opened"] is False
    assert report["reason"]["trajectory_h5_partial_present"] is True


def test_collection_marks_completed_but_unsettled_canary_without_h5_read(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "worker-status.json").write_text(json.dumps({"status": "complete_with_evidence"}))
    (product / "trajectory.h5").write_bytes(b"unread-sentinel")
    (product / "result.json").write_text(json.dumps({
        "hard_integrity_pass": True,
        "requested_horizon_reached": True,
        "event_window_complete": False,
        "event_window": {"event_times_s": {"settled": None}},
    }))
    (product / "audit.json").write_text(json.dumps({}))
    (product / "observations.json").write_text(json.dumps({}))
    out = tmp_path / "collection.json"
    report = collector.collect(product, out)
    assert report["collection_status"] == "collected"
    assert report["scientific_decision"]["decision"] == "candidate_insufficient_event_window"
    assert report["scientific_decision"]["independent_matrix_numerator_eligible"] is False
    assert report["h5_opened"] is False
    assert report["trajectory_h5"]["sha256"] is None


def test_physical_cup_contract_includes_side_wet_initial_centres():
    points = observer_v2.np.asarray([[0.0025, -0.145, 0.66], [0.0, -0.15, 0.65]])
    low = observer_v2.np.asarray([0.0, -0.15, 0.65])
    high = observer_v2.np.asarray([0.425, 0.15, 1.10])
    mask = observer_v2._inside(points, low, high)
    assert mask.tolist() == [True, True]
