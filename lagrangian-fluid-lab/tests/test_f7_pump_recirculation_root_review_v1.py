from __future__ import annotations

import json

from scripts import f7_pump_recirculation_root_review_v1 as review


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_f7_package_is_source_bound_and_not_admitted():
    result = review.verify()
    assert result["status"] == "root_review_only_blocked"
    assert result["physical_novelty_plausible"] is True
    assert result["interface_ready"] is False
    assert result["qualification_credit"] == 0


def test_official_pump_source_has_fixed_fluid_and_prescribed_rotor():
    candidate = load(review.CANDIDATE)
    observed = candidate["official_source_observation"]
    assert observed["fluid_mk"] == 1
    assert observed["fixed_boundary_mk"] == 0
    assert observed["moving_boundary_mk"] == 2
    assert observed["moving_object_ref"] == 2
    assert observed["drawfilevtk"] == ["pump_fixed.vtk", "pump_moving.vtk"]
    assert len(observed["rotation_schedule"]) == 2
    assert observed["rotation_schedule"][0]["acceleration_deg_s2"] == 500.0
    assert observed["rotation_schedule"][0]["initial_velocity_deg_s"] == 90.0


def test_f7_matrix_is_15_row_proposal_only():
    candidate = load(review.CANDIDATE)
    plan = candidate["planned_matrix"]
    assert len(plan["rows"]) == 15
    assert sum(row["kind"] == "spatial_anchor" for row in plan["rows"]) == 9
    assert sum(row["kind"] == "held_out" for row in plan["rows"]) == 4
    assert sum(row["kind"] in {"internal_time", "native_output"} for row in plan["rows"]) == 2
    assert plan["executed"] == 0
    assert plan["credit"] == 0
    assert plan["formal_t1_denominator_mutation"] == 0
    internal = next(row for row in plan["rows"] if row["kind"] == "internal_time")
    output = next(row for row in plan["rows"] if row["kind"] == "native_output")
    assert internal["control_change"] == {
        "parameter": "cflnumber",
        "baseline": 0.2,
        "variant": 0.1,
        "actual_gate": {
            "max_actual_dt_ratio_to_baseline": 0.8,
            "min_actual_step_count_ratio_to_baseline": 1.25,
        },
    }
    assert output["control_change"] == {
        "parameter": "TimeOut",
        "baseline_s": 0.02,
        "variant_s": 0.01,
        "actual_gate": {
            "min_saved_frame_ratio_to_baseline": 1.5,
            "max_actual_cadence_s": 0.011,
        },
    }


def test_interface_review_fails_closed_before_any_runtime():
    interface = load(review.INTERFACE_REVIEW)
    findings = interface["static_findings"]
    assert interface["status"] == "blocked_after_core_adapter_before_runtime_admission"
    assert findings["f7_family_is_currently_supported"] is True
    assert findings["f7_core_adapter_wired"] is True
    assert findings["drawfilevtk_pump_reader_present"] is False
    assert findings["isolated_f7_geometry_adapter_present"] is True
    assert findings["isolated_f7_material_observer_present"] is True
    assert findings["isolated_f7_return_observer_present"] is True
    assert findings["f7_causal_sidecar_producer_present"] is True
    assert findings["f7_runtime_canary_planner_present"] is True
    assert findings["f7_runtime_canary_executor_present"] is True
    assert findings["f7_runtime_canary_evidence_present"] is True
    assert findings["moving_wall_saved_chord_operator_present"] is True
    assert findings["moving_affine_material_frame_present"] is True
    assert interface["authorization"]["definition_writer"] is False
    assert interface["authorization"]["solver"] is False
    assert interface["authorization"]["gpu"] is False


def test_package_has_no_materialized_runtime_products():
    assert list(review.NAMESPACE.glob("*.xml")) == []
    assert list(review.NAMESPACE.glob("*.bi4")) == []
    assert list(review.NAMESPACE.glob("*.vtk")) == []
    assert list(review.NAMESPACE.glob("*.h5")) == []


def test_implementation_has_no_execution_entry_point():
    source = review.LAB.joinpath("scripts/f7_pump_recirculation_root_review_v1.py").read_text(
        encoding="utf-8"
    )
    assert "subprocess" not in source
    assert "subprocess.run" not in source
    assert "os.system" not in source
    assert "queue_mutation" in source
    assert 'default="verify"' in source


def test_isolated_contracts_are_bound_but_not_core_admitted():
    candidate = load(review.CANDIDATE)
    isolated = candidate["isolated_implementation"]
    assert isolated["status"] == "implemented_read_only_not_admitted"
    assert isolated["geometry_adapter"]["returns_core_prescribed_geometry_in_memory"] is True
    assert isolated["geometry_adapter"]["core_adapter_wired"] is True
    assert isolated["material_observer"]["all_initial_fluid_denominator"] is True
    assert isolated["material_observer"]["survivor_renormalization"] is False
    assert isolated["material_observer"]["finite_torque_independence_contract_gate"] is True
    assert isolated["material_observer"]["physical_independence_claim"] is False
    assert isolated["material_observer"]["trajectory_evidence_present"] is False
    observation = candidate["runtime_canary_observation"]
    assert observation["status"] == "runtime_canary_observed_unqualified"
    assert observation["trajectory_evidence_present"] is True
    assert observation["nonzero_prescribed_motion_observed"] is True
    assert observation["torque_evidence_present"] is False
    assert observation["admitted_to_core"] is False
    assert len(isolated["bindings"]) == 13
    assert {item["path"] for item in isolated["bindings"]} >= {
        "scripts/f7_pump_root_review_contract_v2.py",
        "tests/test_f7_pump_root_review_contract_v2.py",
        "scripts/f7_pump_causal_sidecar_v1.py",
        "tests/test_f7_pump_causal_sidecar_v1.py",
    }
