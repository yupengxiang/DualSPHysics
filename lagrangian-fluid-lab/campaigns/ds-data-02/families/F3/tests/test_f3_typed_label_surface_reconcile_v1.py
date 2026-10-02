from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "handoff_20261003/transport_reconciliation_v1/f3_typed_label_surface_reconcile_v1.py"
SPEC = importlib.util.spec_from_file_location("f3_reconcile", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_actual_medium_compact_h5_reconciles_finite_surface_and_marks_legacy_stale():
    case = MODULE.CASES["medium"]
    label = MODULE.summarize_label_h5(case["label_h5"], case)
    surface = MODULE.summarize_surface(case["surface"])
    legacy = MODULE.legacy_summary(case["legacy_json"])
    report = MODULE.reconcile_case("medium", label, surface, legacy)

    assert report["status"] == "reconciled_compact_h5_with_finite_surface_legacy_json_stale"
    assert all(report["checks"].values())
    assert report["events"]["left_right_exchange"]["h5"]["observed_count"] == 12112
    assert report["events"]["left_right_exchange"]["finite_surface"]["crossing_count_sum"] == 84593
    assert report["events"]["front_back_exchange"]["h5"]["observed_count"] == 1766
    assert report["events"]["top_open_exit"]["h5"]["censored_count"] == 34560
    assert report["legacy_summary"]["status"] == "stale_zero_xy_aggregate"
    assert label["read_scope"]["trajectory_h5_opened"] is False
    assert label["read_scope"]["destination_time_series_read"] is False


def test_fine_native_accounting_selects_fine_entry_and_detects_old_cross_binding():
    sidecar = MODULE.fine_native_sidecar()
    assert sidecar["status"] == "fine_specific_full_window_zero_native_accounting_bound"
    assert all(sidecar["checks"].values())
    assert sidecar["native_accounting_binding"]["selected_entry"]["case_id"] == "F3_WEAK_DUAL_REFERENCE_FINE"
    assert sidecar["legacy_audit_binding"]["reported_case_id"] == "F3_WEAK_DUAL_REFERENCE_COARSE"


def test_request_never_lists_trajectory_h5_or_destination_series():
    request = MODULE.make_request(ROOT / "handoff_20261003/transport_reconciliation_v1/test-request.json")
    assert request["cpu_task_kind"] == "audit"
    assert request["solver_launch_forbidden"] is True
    assert all("trajectory.h5" not in path for path in request["input_files"])
    assert request["large_h5_policy"]["destination_time_series_read"] is False
    request_path = ROOT / "handoff_20261003/transport_reconciliation_v1/test-request.json"
    request_path.unlink()


def test_legacy_zero_flux_is_not_a_pass_without_actual_h5_flux():
    labels = {
        "population": {"fluid_particles": 2},
        "events": {
            event: {
                "observed_count": 0,
                "censored_count": 2,
                "observed_mass_kg": 0.0,
                "censored_mass_kg": 1.0,
                "final_net_flux_kg": 0.0,
                "final_forward_mass_kg": 0.0,
                "final_backward_mass_kg": 0.0,
                "censor_code_observed_count": 0,
                "first_passage_ids": [],
                "first_passage_times": {},
                "final_category_fluid_counts": {},
            }
            for event in MODULE.EVENTS
        },
    }
    surface = {
        "events": {
            event: {
                "identity_rows": 2,
                "crossing_count_sum": 0,
                "first_passage_count": 0,
                "first_passage_ids": [],
                "first_passage_times": {},
                "positive_crossing_mass_kg": 0.0,
                "negative_crossing_mass_kg": 0.0,
                "net_crossing_mass_kg": 0.0,
                "surface_record": {"accepted_crossings": 0},
            }
            for event in MODULE.EVENTS
        }
    }
    legacy = {"legacy_x_y_zero": True, "binding": {}, "aggregate": {}}
    report = MODULE.reconcile_case("synthetic", labels, surface, legacy)
    assert report["status"] == "reconciliation_incomplete"
    assert report["checks"]["legacy_json_is_not_used_as_transport_authority"] is False

