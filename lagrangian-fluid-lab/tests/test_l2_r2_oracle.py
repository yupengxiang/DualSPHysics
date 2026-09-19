from __future__ import annotations

import h5py
import numpy as np

from scripts.l2_r2_oracle import (
    classify_legacy_run,
    extract_xml_contract,
    integrate_constant_acceleration,
    integrate_euler,
    run_case_oracles,
    score_prediction,
    update_from_displacement,
)


def _write_fixture(path):
    times = np.asarray([0.0, 0.1, 0.2, 0.3], dtype=np.float64)
    particle_id = np.asarray([11, 12, 13], dtype=np.int64)
    velocity = np.asarray([
        [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]],
        [[1.0, 0.1, 0.0], [0.0, 2.0, 0.1], [0.1, 0.0, 3.0]],
        [[1.0, 0.2, 0.0], [0.0, 2.0, 0.2], [0.2, 0.0, 3.0]],
        [[1.0, 0.3, 0.0], [0.0, 2.0, 0.3], [0.3, 0.0, 3.0]],
    ], dtype=np.float64)
    position = np.zeros_like(velocity)
    position[1] = position[0] + velocity[0] * 0.1
    position[2] = position[1] + velocity[1] * 0.1
    position[3] = position[2] + velocity[2] * 0.1
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("particle_id", data=particle_id)
        handle.create_dataset("valid", data=np.ones((4, 3), dtype=np.bool_))
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("mass", data=np.full((3,), 0.5, dtype=np.float64))


def test_update_helpers_and_common_score():
    position = np.asarray([[1.0, 2.0, 3.0]])
    velocity = np.asarray([[2.0, 0.0, -1.0]])
    assert np.allclose(integrate_euler(position, velocity, 0.5), [[2.0, 2.0, 2.5]])
    assert np.allclose(update_from_displacement(position, velocity), [[3.0, 2.0, 2.0]])
    next_position, next_velocity = integrate_constant_acceleration(
        position, velocity, np.asarray([[0.0, 2.0, 0.0]]), 0.5
    )
    assert np.allclose(next_position, [[2.0, 2.25, 2.5]])
    assert np.allclose(next_velocity, [[2.0, 1.0, -1.0]])
    score = score_prediction([np.zeros((2, 3))], scale=0.5, scope="test")
    assert score["sample_count"] == 2
    assert score["rmse_m"] == 0.0
    assert score["normal_result"] is True


def test_actual_source_oracles_use_same_scoring_and_bound_missing_control(tmp_path):
    path = tmp_path / "fixture.h5"
    _write_fixture(path)
    result = run_case_oracles(path, control_path=None, dp_m=0.1)
    assert result["status"] == "completed"
    assert result["source_preflight"]["status"] == "ready"
    assert result["oracles"]["source_trajectory_integrity"]["status"] == "completed"
    assert result["oracles"]["reference_displacement_same_update"]["score"]["rmse_m"] == 0.0
    assert result["oracles"]["real_velocity_same_integrator"]["status"] == "completed"
    assert result["oracles"]["constant_velocity"]["status"] == "completed"
    assert result["oracles"]["known_control_simplified"]["status"] == "bounded_rejection"
    assert result["oracles"]["known_control_simplified"]["reason"] is None


def test_legacy_run_cannot_be_promoted_to_current_contract():
    result = classify_legacy_run({
        "logical_run_id": "legacy-seed17",
        "route": "local_interaction",
        "seed": 17,
        "source_run_status": "completed",
        "feature_width": 43,
        "epochs_requested": 3,
        "epochs_run": 2,
        "source_artifacts": {},
    })
    assert result["classification"] == "legacy_reference"
    assert result["reuse_allowed"] is True
    assert result["eligible_for_current_f3_model_result"] is False
    assert result["eligible_for_new_L2_training_count"] is False
    assert "feature_width_43_not_current_48" in result["rejection_reasons"]


def test_xml_contract_reads_actual_values(tmp_path):
    path = tmp_path / "case.xml"
    path.write_text(
        """<root><gravity x=\"0\" y=\"0\" z=\"-9.81\" />"
        "<definition dp=\"0.0075\" /><cflnumber value=\"0.05\" />"
        "<accinput><acccentre x=\"0.45\" y=\"0\" z=\"0\" />"
        "<acctimesfile value=\"CaseSloshingAccData.csv\" /></accinput>"
        "<parameter key=\"ViscoTreatment\" value=\"1\" />"
        "<parameter key=\"Visco\" value=\"0.05\" />"
        "<parameter key=\"ViscoBoundFactor\" value=\"1\" />"
        "<parameter key=\"Shifting\" value=\"0\" />"
        "<parameter key=\"NoPenetration\" value=\"1\" />"
        "<parameter key=\"Boundary\" value=\"2\" /><motion /></root>"""
    )
    result = extract_xml_contract(path)
    assert result["missing"] == []
    assert result["values"]["definition_dp_m"] == 0.0075
    assert result["values"]["visco"] == 0.05
    assert result["no_penetration_declared"] is True
