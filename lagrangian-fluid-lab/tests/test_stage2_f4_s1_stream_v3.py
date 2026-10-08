from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f4_s1_stream_v3.py"
SPEC = importlib.util.spec_from_file_location("stage2_f4_s1_stream_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source_binding() -> dict:
    return {
        key: {"path": f"/source/{key}.json", "sha256": "c" * 64}
        for key in MODULE.SOURCE_BINDING_KEYS
    }


def _source_identity() -> dict:
    return {
        "physical_case_id": MODULE.EXPECTED_CASE,
        "physical_binding_sha256": "a" * 64,
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
        "mass_policy": "native_rho_dp_cubed_no_rescaling",
        "typed_identity_binding": {
            "fluid_mkfluid_to_native_mk": {"0": 1, "1": 2},
            "source": "generated XML typed fluid ranges",
        },
    }


def manifest() -> dict:
    items = []
    variants = (
        ("coarse-native", "coarse", "native"),
        ("medium-native", "medium", "native"),
        ("fine-native", "fine", "native"),
        ("fine-half_dt", "fine", "half_dt"),
        ("fine-half_save", "fine", "half_save"),
    )
    for suffix, resolution, time_variant in variants:
        items.append({
            "artifact_id": f"{MODULE.EXPECTED_ARTIFACT_PREFIX}-{suffix}",
            "case_id": MODULE.EXPECTED_CASE,
            "resolution": resolution,
            "time_variant": time_variant,
            "physical_binding_sha256": "a" * 64,
            "trajectory_hdf5": {"path": f"/trajectory/{suffix}.h5", "sha256": "b" * 64},
            "metadata": {"path": f"/metadata/{suffix}.json", "sha256": "d" * 64},
            "conversion_report": {"path": f"/conversion/{suffix}.json", "sha256": "e" * 64},
            "conversion_receipt": {"path": f"/receipt/{suffix}.json", "sha256": "f" * 64},
            "source_regions": {"path": f"/regions/{suffix}.json", "sha256": "1" * 64},
            "source_binding": _source_binding(),
            "source_identity": _source_identity(),
        })
    return {
        "schema": MODULE.MANIFEST_SCHEMA,
        "family_id": "F4",
        "case_id": MODULE.EXPECTED_CASE,
        "physical_binding_sha256": "a" * 64,
        "trajectory_read_policy": "guarded_h5_read_only_no_bi4_no_solver",
        "claim_boundary": {
            "physical_fate": "unknown",
            "continuous_event_time_between_saved_frames": "unknown",
        },
        "source_evidence": {"path": "/source/f4-actual-evidence-v1.json", "sha256": "2" * 64},
        "operator_contract": {
            "schema": "ds02.stage2.f4-typed-operator.v3",
            "mass_denominator": "whole_initial_fluid_mass_kg",
            "legacy_event_budget_fraction": None,
            "legacy_temporal_item_allocation": None,
        },
        "artifacts": items,
    }


def metadata() -> dict:
    return {
        "schema": "ds02.f4.direct-binding.v1",
        "family_id": "F4",
        "physical_case_id": MODULE.EXPECTED_CASE,
        "mechanism_id": "finite_drop_pool",
        "physical_binding_sha256": "a" * 64,
        "physical_binding": {
            "family_id": "F4",
            "mechanism_id": "finite_drop_pool",
            "control_family_id": "F4_native_dbc_verlet_wendland_v1",
            "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
            "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
            "mass_policy": "native_rho_dp_cubed_no_rescaling",
            "event_window": {"time_start_s": 0.0, "time_end_s": 1.2},
            "geometry": {"pool": {"low_m": [-1.0, -0.1, -0.1], "size_m": [1.0, 0.2, 0.2]}},
            "initial_state": {"source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"}},
        },
        "typed_identity_binding": _source_identity()["typed_identity_binding"],
        "source_binding": _source_binding(),
    }


def test_manifest_requires_v3_operator_contract_and_source_identity():
    entries = MODULE.validate_manifest_dict(manifest())
    assert [entry["variant"] for entry in entries] == list(MODULE.EXPECTED_ARTIFACT_SUFFIXES)

    bad = copy.deepcopy(manifest())
    bad["operator_contract"]["legacy_event_budget_fraction"] = 0.02
    with pytest.raises(MODULE.StreamContractError):
        MODULE.validate_manifest_dict(bad)

    bad = copy.deepcopy(manifest())
    bad["artifacts"][0]["source_identity"]["control_family_id"] = "wrong-control"
    with pytest.raises(MODULE.StreamContractError):
        MODULE.validate_manifest_dict(bad)


def test_plane_intersection_handles_endpoint_outside_and_endpoint_inside_cases():
    low = [-0.1, -0.1]
    high = [0.1, 0.1]
    both_outside = MODULE.segment_plane_aperture(
        [-1.0, -1.0, 0.0], [1.0, 1.0, 0.0], plane_x=0.0,
        aperture_low_yz=low, aperture_high_yz=high,
    )
    assert both_outside["status"] == "accepted"
    assert both_outside["direction"] == "positive_x"
    assert both_outside["u"] == pytest.approx(0.5)

    inside_then_outside = MODULE.segment_plane_aperture(
        [-1.0, 0.0, 0.0], [1.0, 1.0, 0.0], plane_x=0.0,
        aperture_low_yz=low, aperture_high_yz=high,
    )
    assert inside_then_outside["status"] == "outside_aperture"
    assert inside_then_outside["aperture_at_plane"] is False


def test_later_crossing_is_per_typed_identity_and_saved_brackets_are_explicit():
    fixture = MODULE.operator_regression_fixtures()
    events = fixture["same_identity_first_then_later_crossing"]
    assert events["accepted_saved_crossings"] == 2
    assert events["first_saved_crossings"] == 1
    assert events["later_saved_crossings"] == 1
    assert events["per_typed_identity"]["7:42"]["later_saved_crossings"] == 1
    assert events["per_typed_identity"]["7:42"]["later_brackets_s"] == [[1.0, 2.0]]
    assert events["semantics"]["continuous_event_time"] == "unknown; only adjacent saved-record bracket is retained"


def test_missing_identity_uses_whole_initial_mass_and_accumulates_unique_mass():
    records = MODULE.operator_regression_fixtures()["missing_identity_whole_initial_accumulation"]
    assert records[1]["current_unknown_fraction_whole_initial"] == pytest.approx(2.0 / 6.0)
    assert records[2]["current_unknown_fraction_whole_initial"] == 0.0
    assert records[2]["cumulative_unique_unknown_fraction_whole_initial"] == pytest.approx(2.0 / 6.0)


def test_compute_stream_synthetic_h5_counts_source_and_unknown_without_legacy_operator(tmp_path):
    h5_path = tmp_path / "fixture.h5"
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0]))
        h5.create_dataset("particle_id", data=np.asarray([10, 11, 12], dtype=np.int64))
        h5.create_dataset("particle_zone", data=np.zeros(3, dtype=np.int64))
        h5.create_dataset("initial_type", data=np.full(3, 3, dtype=np.int8))
        h5.create_dataset("initial_mk", data=np.asarray([1, 2, 1], dtype=np.int16))
        h5.create_dataset("initial_mass", data=np.asarray([1.0, 2.0, 3.0]))
        h5.create_dataset("valid", data=np.asarray([[1, 1, 1], [1, 1, 1], [1, 1, 0]], dtype=np.bool_))
        h5.create_dataset("type", data=np.full((3, 3), 3, dtype=np.int8))
        h5.create_dataset("mk", data=np.tile(np.asarray([1, 2, 1], dtype=np.int16), (3, 1)))
        h5.create_dataset("position", data=np.asarray([
            [[-1.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]],
            [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
            [[-1.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ]))
        h5.create_dataset("velocity", data=np.zeros((3, 3, 3)))
        h5.create_dataset("mass", data=np.ones((3, 3)))
    output_csv = tmp_path / "stream.csv"
    result = MODULE.compute_typed_stream_v3(
        h5_path=h5_path,
        metadata=metadata(),
        output_csv=output_csv,
        declared_h5_sha256="b" * 64,
    )
    pool = result["source_event_data"]["pool"]
    drop = result["source_event_data"]["falling_drop"]
    assert pool["accepted_saved_crossings"] == 3
    assert pool["first_saved_crossings"] == 2
    assert pool["later_saved_crossings"] == 1
    assert pool["outside_aperture_crossings"] == 0
    assert drop["candidate_plane_crossings"] == 1
    assert drop["outside_aperture_crossings"] == 1
    assert result["whole_initial_fluid_mass_kg"] == pytest.approx(6.0)
    rows = output_csv.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert result["unknown_identity_policy"]["physical_fate_inferred"] is False
