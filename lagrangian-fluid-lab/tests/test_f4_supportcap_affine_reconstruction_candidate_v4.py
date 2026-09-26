from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.core_material import (
    F4_V3_ERROR_ESTIMATOR,
    F4_V3_NEIGHBOURS,
    GATE,
    REGULARIZATION_M,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import (
    BACKEND,
    CANDIDATE_ID,
    ERROR_ESTIMATOR,
    FIXED_GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    NEIGHBOURS,
    candidate_spec,
    sample_candidate,
)
from scripts.f4_material_calibration import _box_lattice
from scripts.f4_material_calibration_v3 import (
    FIELD_IDS,
    Q_CASES,
    SUPPORT_SPACING_M,
    manufactured_velocity_v3,
    query_regions,
)
from scripts.core_material import f4_destination_region, f4_source_region, f4_walls


LAB = Path(__file__).resolve().parents[1]
CARD = LAB / "campaigns/core-v1/material/candidates/f4-supportcap-local-affine-reconstruction-v4/candidate-card-v1.json"
CALIBRATION = LAB / "campaigns/core-v1/material/evidence/f4-supportcap-local-affine-reconstruction-v4-synthetic-calibration-v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_candidate_contract_preserves_registered_gate_and_scope() -> None:
    spec = candidate_spec()
    assert spec["candidate_id"] == CANDIDATE_ID
    assert spec["backend"] == BACKEND
    assert spec["support"]["neighbours"] == NEIGHBOURS == F4_V3_NEIGHBOURS
    assert spec["support"]["maximum_support_distance_m"] == MAXIMUM_SUPPORT_DISTANCE_M == 0.03
    assert spec["support"]["regularization_m"] == REGULARIZATION_M
    assert spec["fixed_gate"] == FIXED_GATE == GATE
    assert spec["error_estimator"] == ERROR_ESTIMATOR
    assert spec["threshold_policy"] == "unchanged_registered_f4_gate"
    assert spec["qualification_claim"] == "none"
    assert spec["credit"] == 0
    assert spec["T1_numerical"] is False
    assert spec["T2_macro"] is False
    assert spec["T2_path"] is False
    assert spec["production_tracer_registered"] is False


def test_weighted_affine_predictor_exactly_reproduces_affine_velocity() -> None:
    axis = np.linspace(-0.04, 0.04, 9)
    xx, yy, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    position = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    matrix = np.array([[0.4, -0.2, 0.1], [0.3, 0.5, -0.4], [-0.1, 0.2, 0.6]])
    offset = np.array([0.2, -0.3, 0.4])
    velocity = position @ matrix.T + offset
    query = np.array([[0.001, -0.002, 0.003], [0.008, 0.006, -0.004]])

    predicted, support, passed, diagnostics = sample_candidate(position, velocity, query)

    np.testing.assert_allclose(predicted, query @ matrix.T + offset, atol=1e-12, rtol=1e-12)
    assert np.all(support <= MAXIMUM_SUPPORT_DISTANCE_M)
    assert passed.all()
    assert diagnostics["backend"] == BACKEND
    assert diagnostics["predictor"] == "weighted_local_affine_least_squares_at_query"
    assert np.all(diagnostics["interpolation_reconstruction_error_mps"] < 1e-12)
    assert np.all(diagnostics["estimated_interpolation_error_mps"] <= FIXED_GATE["maximum_reconstruction_error_mps"])


def test_candidate_changes_predictor_but_preserves_v3_fixed_gate_decision() -> None:
    axis = np.linspace(-0.05, 0.05, 11)
    xx, yy, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    position = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    velocity = np.column_stack((position[:, 0] ** 2, position[:, 1] ** 2, position[:, 2] ** 2))
    query = np.array([[0.003, -0.004, 0.002]])
    walls = np.empty((0, 3, 3), dtype=np.float64)

    baseline, support_v3, passed_v3, diag_v3 = sample_v3(
        position,
        velocity,
        query,
        walls,
    )
    affine, support_v4, passed_v4, diag_v4 = sample_candidate(position, velocity, query, walls)

    assert not np.allclose(affine, baseline)
    np.testing.assert_array_equal(support_v4, support_v3)
    np.testing.assert_array_equal(passed_v4, passed_v3)
    np.testing.assert_allclose(
        diag_v4["estimated_interpolation_error_mps"],
        diag_v3["estimated_interpolation_error_mps"],
        rtol=1e-12,
        atol=1e-14,
    )
    assert diag_v3["error_estimator"] == F4_V3_ERROR_ESTIMATOR
    assert diag_v4["error_estimator"] == ERROR_ESTIMATOR


@pytest.mark.parametrize(
    "which,bad",
    [
        ("position", np.array([np.nan, 0.0, 0.0])),
        ("velocity", np.array([0.0, np.inf, 0.0])),
        ("query", np.array([0.0, 0.0, np.nan])),
    ],
)
def test_nonfinite_arrays_are_rejected_without_silent_denominator_reduction(which, bad) -> None:
    position = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]])
    velocity = np.ones_like(position)
    query = np.zeros((1, 3))
    if which == "position":
        position[0] = bad
    elif which == "velocity":
        velocity[0] = bad
    else:
        query = bad[None, :]

    with pytest.raises(ValueError, match="nonfinite"):
        sample_candidate(position, velocity, query)


def test_empty_query_retains_empty_shapes_without_opening_any_provider() -> None:
    position = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]])
    velocity = np.ones_like(position)
    predicted, support, passed, diagnostics = sample_candidate(position, velocity, np.empty((0, 3)))
    assert predicted.shape == (0, 3)
    assert support.shape == passed.shape == (0,)
    assert diagnostics["backend"] == BACKEND


def test_candidate_card_and_synthetic_receipt_are_hash_closed_zero_credit() -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert card["candidate_id"] == CANDIDATE_ID
    assert card["status"] == "proposal_only_cpu_native_preflight_authorized_runtime_not_authorized"
    assert card["qualification_claim"] == "none"
    assert card["credit"] == 0
    assert card["T1_numerical"] is False
    assert card["T2_macro"] is False
    assert card["T2_path"] is False
    for binding in card["input_bindings"].values():
        path = LAB / binding["path"]
        assert path.is_file(), binding["path"]
        assert _sha(path) == binding["sha256"], binding["path"]
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    assert calibration["candidate_id"] == CANDIDATE_ID
    assert calibration["summary"]["total_queries"] == 5632
    assert calibration["summary"]["v3_gate_pass_count"] == 5632
    assert calibration["summary"]["v4_gate_pass_count"] == 5632
    assert calibration["summary"]["v4_truth_error_within_fixed_maximum_all_queries"] is True
    assert calibration["interpretation"]["native_or_event_validation"] is False
    assert calibration["interpretation"]["credit"] == 0


def test_registered_heldout_manufactured_fields_keep_fixed_gates_and_expose_tradeoff() -> None:
    walls = f4_walls()
    per_field: dict[str, list[tuple[float, float]]] = {name: [] for name in FIELD_IDS}
    total = total_v3_pass = total_v4_pass = 0
    for q in Q_CASES:
        destination = f4_destination_region()
        source = f4_source_region(float(q))
        cloud = np.concatenate(
            [
                _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
                _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
            ]
        )
        for field_id in FIELD_IDS:
            field_velocity = manufactured_velocity_v3(cloud, field_id)
            for _, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v3(query, field_id)
                v3, _, passed_v3, _ = sample_v3(
                    cloud,
                    field_velocity,
                    query,
                    walls,
                )
                v4, _, passed_v4, _ = sample_candidate(cloud, field_velocity, query, walls)
                err_v3 = np.linalg.norm(v3 - truth, axis=1)
                err_v4 = np.linalg.norm(v4 - truth, axis=1)
                per_field[field_id].append(
                    (float(np.mean(err_v3**2)), float(np.mean(err_v4**2)))
                )
                assert np.all(err_v4 <= FIXED_GATE["maximum_reconstruction_error_mps"])
                np.testing.assert_array_equal(passed_v4, passed_v3)
                total += len(query)
                total_v3_pass += int(passed_v3.sum())
                total_v4_pass += int(passed_v4.sum())

    assert total == 5632
    assert total_v3_pass == total_v4_pass == total
    shear_v3_mse = float(np.mean([value[0] for value in per_field["quintic_shear"]]))
    shear_v4_mse = float(np.mean([value[1] for value in per_field["quintic_shear"]]))
    interface_v3_mse = float(np.mean([value[0] for value in per_field["gaussian_interface"]]))
    interface_v4_mse = float(np.mean([value[1] for value in per_field["gaussian_interface"]]))
    assert shear_v4_mse < 0.5 * shear_v3_mse
    assert interface_v4_mse > interface_v3_mse
    assert np.sqrt(interface_v4_mse) < FIXED_GATE["maximum_reconstruction_error_mps"]
