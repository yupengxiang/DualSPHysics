from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f4_s1_quarter_pair_v5.py"
SPEC = importlib.util.spec_from_file_location("stage2_f4_s1_quarter_pair_v5", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source(value: float) -> dict:
    return {
        "accepted_saved_crossings": 2,
        "first_saved_crossings": 1,
        "later_saved_crossings": 1,
        "positive_saved_crossings": 1,
        "negative_saved_crossings": 1,
        "event_weighted_mass_kg": value,
        "event_weighted_positive_mass_kg": value * 0.75,
        "event_weighted_negative_mass_kg": value * 0.25,
        "event_weighted_net_transport_mass_kg": value * 0.5,
        "unique_first_mass_kg": value * 0.5,
        "unique_first_net_transport_mass_kg": value * 0.25,
        "later_recross_mass_kg": value * 0.5,
        "later_net_transport_mass_kg": value * 0.25,
        "first_bracket_width_max_s": 0.1,
        "first_bracket_width_median_s": 0.05,
    }


def _variant(value: float, *, time_variant: str) -> dict:
    return {
        "whole_initial_mass_kg": 10.0,
        "saved_time_window_s": [0.0, 1.0],
        "sources": {"pool": _source(value), "falling_drop": _source(value * 0.5)},
        "occupancy": {
            "pool": {
                "saved_interval_occupancy_seconds": 0.8,
                "saved_right_hold_residence_mass_time_kg_s": value * 0.4,
                "saved_trapezoid_residence_mass_time_kg_s": value * 0.39,
            },
            "falling_drop": {
                "saved_interval_occupancy_seconds": 0.4,
                "saved_right_hold_residence_mass_time_kg_s": value * 0.2,
                "saved_trapezoid_residence_mass_time_kg_s": value * 0.19,
            },
        },
        "source_control_geometry_closure": {
            "lineage_group_id": "lineage",
            "control_family_id": "control",
            "geometry_family_id": "geometry",
            "mass_policy": "native",
            "source_to_native_mk": {"pool": 1, "falling_drop": 2},
        },
        "time_variant": time_variant,
    }


def _report() -> dict:
    variants = {
        "coarse-native": _variant(1.0, time_variant="native"),
        "medium-native": _variant(1.1, time_variant="native"),
        "fine-native": _variant(2.0, time_variant="native"),
        "fine-half_dt": _variant(2.1, time_variant="half_dt"),
        "fine-half_save": _variant(2.0, time_variant="half_save"),
    }
    closure = {}
    for name in variants:
        closure[name] = dict(variants[name]["source_control_geometry_closure"], physical_binding_sha256="binding")
    return {
        "schema": MODULE.V4_SCHEMA,
        "status": "completed_source_bound_saved_segment_diagnostic",
        "source_control_geometry_closure": {
            "all_variants_source_hashes_verified": True,
            "same_control_geometry_lineage_tuple_across_variants": True,
            "trajectory_h5_opened": False,
            "bi4_partout_opened": False,
            "variant_closure": closure,
        },
        "variants": variants,
    }


def test_pair_scope_only_allows_same_fine_spatial_recipe() -> None:
    report = _report()
    save = MODULE._pair_scope(report, "save_sampling")
    step = MODULE._pair_scope(report, "integration_step")
    assert save["resolution_comparison"] == "held_fine"
    assert step["resolution_comparison"] == "held_fine"
    assert save["excluded_spatial_variants"]["coarse-native"].startswith("excluded")
    assert step["excluded_spatial_variants"]["medium-native"].startswith("excluded")


def test_pair_comparison_reports_mass_fraction_without_amount_gate() -> None:
    result = MODULE._compare_pair(_report(), "integration_step")
    pool = result["sources"]["pool"]
    metric = pool["metrics"]["event_weighted_mass_kg"]
    assert metric["absolute_difference"] == pytest.approx(0.1)
    assert metric["absolute_difference_fraction_of_reference_whole_initial_mass"] == pytest.approx(0.01)
    assert pool["current_amount_is_observation_not_error_gate"] is True
    assert pool["repeated_crossings_are_not_net_flux"] is True
    assert result["qualification_credit"] == "not_granted"


def test_s2_terminal_summary_reads_only_small_runparts_sidecar(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0}) + "\n", encoding="utf-8")
    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov;NpSim;NpfSim\n"
        "0;0;0;0;0;0;10;8\n"
        "1;1.2;0;0;0;0;9;7\n",
        encoding="utf-8",
    )
    result = MODULE._s2_terminal_summary(receipt, runparts)
    assert result["final_saved_time_s"] == pytest.approx(1.2)
    assert result["max_native_excluded_particles"] == 0
    assert result["final_simulated_particles"] == 9

