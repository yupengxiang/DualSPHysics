import numpy as np

from scripts.core_material import GATE
from scripts.f4_material_calibration import (
    FIELD_IDS,
    SCHEMA,
    _region_report,
    design,
    manufactured_velocity,
)


def test_f4_design_is_independent_and_keeps_fixed_gate():
    record = design()
    assert record["schema"] == SCHEMA
    assert record["qualification_claim"] == "none"
    assert record["geometry"]["q_cases"] == [0.5, 1.0]
    assert {row["id"] for row in record["manufactured_fields"]} == set(FIELD_IDS)
    assert record["backend_binding"]["gate"] == dict(GATE)
    assert record["macro_unknown_budget"]["maximum_unknown_mass_fraction"] == 0.01
    assert "33-cell" in record["execution"]["matrix_scope"]


def test_manufactured_fields_are_deterministic_and_have_vector_shape():
    points = np.array([[0.1, 0.05, 0.02], [0.6, 0.2, 0.18]], dtype=np.float64)
    for field_id in FIELD_IDS:
        first = manufactured_velocity(points, field_id)
        second = manufactured_velocity(points, field_id)
        assert first.shape == points.shape
        np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(manufactured_velocity(points, "constant")[0],
                               manufactured_velocity(points, "constant")[1])


def test_region_report_charges_unknown_mass_to_fixed_budget():
    query = np.zeros((4, 3), dtype=np.float64)
    truth = np.zeros_like(query)
    interpolated = np.zeros_like(query)
    passed = np.array([True, True, False, False])
    diagnostics = {
        "estimated_interpolation_error_mps": np.zeros(4),
        "support_distance": np.zeros(4),
        "effective_sample_size": np.full(4, 8.0),
        "geometry_rank": np.full(4, 3),
        "anisotropy": np.full(4, 0.5),
    }
    report = _region_report(query, truth, interpolated, passed, diagnostics,
                            np.full(4, 0.25), GATE)
    assert report["mass_closure"] == 1.0
    assert report["unknown_mass_fraction"] == 0.5
    assert report["unknown_budget_pass"] is False
