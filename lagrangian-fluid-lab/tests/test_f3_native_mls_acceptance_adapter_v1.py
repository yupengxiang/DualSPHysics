from copy import deepcopy

import pytest

from scripts.f3_native_mls_acceptance_adapter_v1 import (
    CDF_LIMIT,
    FULL_WINDOW_S,
    MATRIX_ROW_COUNT,
    NATIVE_INTERVAL_S,
    SCHEMA,
    UNKNOWN_LIMIT,
    build_receipt,
)


def _cdf():
    return {
        "time_s": [0.0, 1.0, FULL_WINDOW_S],
        "lower_mass_fraction": [0.0, 0.2, 0.6],
        "upper_mass_fraction": [0.0, 0.25, 0.7],
    }


def _source_row():
    return {
        "final_unknown_fraction": 0.005,
        "first_passage_cdf_bounds": _cdf(),
        "return_cdf_bounds": _cdf(),
        "residence_cdf_bounds": {**_cdf(), "value_s": [0.0, 1.0, 2.0]},
    }


def _comparison():
    row = _source_row()
    return {
        "schema": "core.material.f3.native_volume_mls.comparison.v2",
        "status": "diagnostic_only",
        "qualification_claim": "none",
        "common_binding": {
            "source_definition": {"source_label": "initial_x_ge_0"},
            "event_definition": {"event_plane": "x=0"},
        },
        "source_comparison": {
            "0": {"left": deepcopy(row), "right": deepcopy(row), "difference": {
                "first_passage_cdf_sup_abs_difference_bound": 0.01,
                "return_cdf_sup_abs_difference_bound": 0.01,
                "residence_cdf_sup_abs_difference_bound": 0.01,
            }},
            "1": {"left": deepcopy(row), "right": deepcopy(row), "difference": {
                "first_passage_cdf_sup_abs_difference_bound": 0.01,
                "return_cdf_sup_abs_difference_bound": 0.01,
                "residence_cdf_sup_abs_difference_bound": 0.01,
            }},
        },
    }


def _window():
    return {
        "schema": "core.material.f3.native_volume_mls.source_window.v1",
        "start_s": 0.0,
        "end_s": FULL_WINDOW_S,
        "observed_start_s": 0.0,
        "observed_end_s": FULL_WINDOW_S,
        "native_interval_s": NATIVE_INTERVAL_S,
        "frame_count": 4176,
        "complete": True,
        "right_censored": False,
        "cadence_pass": True,
        "native_rows_exact": True,
        "no_stride_or_synthetic_cadence": True,
    }


def _checkpoint():
    return {
        "schema": "core.material.f3.native_volume_mls.checkpoint.v1",
        "state_sha256": "1" * 64,
        "file_sha256": "2" * 64,
        "binding_sha256": "3" * 64,
        "seed_hash": "4" * 64,
        "committed_frame": 4176,
        "fields": ["position", "reliable", "permanent_unknown"],
        "checkpoint_npz": "trace.h5.checkpoint.00004176.npz",
    }


def _artifacts():
    return [
        {"artifact_id": "source", "role": "source_window", "sha256": "3" * 64},
        {"artifact_id": "material", "role": "material_output", "sha256": "5" * 64},
        {"artifact_id": "checkpoint", "role": "checkpoint", "sha256": "6" * 64},
    ]


def _matrix():
    return [
        {"matrix_index": i, "matrix_stage": "resolution_substep" if i < 24 else "cadence" if i < 28 else "seed_density", "acceptance_receipt": False, "qualification_claim": "none"}
        for i in range(MATRIX_ROW_COUNT)
    ]


def _build(**overrides):
    values = {
        "comparison": _comparison(),
        "source_window": _window(),
        "checkpoint": _checkpoint(),
        "artifact_bindings": _artifacts(),
        "matrix_rows": _matrix(),
        "physical_case_id": "F3-physical-00",
        "case_id": "F3-material-00",
    }
    values.update(overrides)
    return build_receipt(**values)


def test_bridge_is_diagnostic_only_and_keeps_full_matrix_denominator():
    receipt = _build()
    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "blocked_for_macro_t2"
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["T2_macro"] is False
    assert receipt["matrix"]["row_count"] == 33
    assert receipt["matrix"]["acceptance_receipt_count"] == 0
    assert receipt["execution_constraints"]["hdf5_opened"] is False


def test_scientific_gates_pass_only_at_fixed_limits():
    receipt = _build()
    assert receipt["gates"]["per_source_unknown_mass"] is True
    assert receipt["gates"]["cdf_scientific_gate"] is True

    bad = _comparison()
    bad["source_comparison"]["0"]["left"]["final_unknown_fraction"] = UNKNOWN_LIMIT + 1e-6
    receipt = _build(comparison=bad)
    assert receipt["gates"]["per_source_unknown_mass"] is False
    assert "per_source_unknown_mass" in receipt["failure_reasons"]

    bad = _comparison()
    bad["source_comparison"]["0"]["difference"]["residence_cdf_sup_abs_difference_bound"] = CDF_LIMIT + 1e-6
    receipt = _build(comparison=bad)
    assert receipt["gates"]["cdf_scientific_gate"] is False
    assert "cdf_scientific_gate" in receipt["failure_reasons"]


def test_right_censor_and_incomplete_window_fail_closed():
    window = _window()
    window["right_censored"] = True
    with pytest.raises(ValueError, match="right-censored"):
        _build(source_window=window)

    window = _window()
    window["observed_end_s"] = FULL_WINDOW_S - 0.002
    with pytest.raises(ValueError, match="observed bounds"):
        _build(source_window=window)


def test_checkpoint_and_artifact_roles_are_required():
    checkpoint = _checkpoint()
    checkpoint["fields"] = ["position"]
    with pytest.raises(ValueError, match="omit required"):
        _build(checkpoint=checkpoint)

    artifacts = _artifacts()[:2]
    with pytest.raises(ValueError, match="required roles"):
        _build(artifact_bindings=artifacts)


def test_matrix_cannot_shrink_or_duplicate_rows():
    with pytest.raises(ValueError, match="exactly the registered 33 rows"):
        _build(matrix_rows=_matrix()[:-1])
    rows = _matrix()
    rows[-1]["matrix_index"] = 0
    with pytest.raises(ValueError, match="duplicate"):
        _build(matrix_rows=rows)


def test_trace_and_cdf_schema_are_required():
    comparison = _comparison()
    comparison["source_comparison"]["0"]["left"].pop("residence_cdf_bounds")
    with pytest.raises(ValueError, match="residence_cdf_bounds"):
        _build(comparison=comparison)
