from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.r4_tracer_actual_scenario_audit import (
    build_report,
    cross_resolution_permutation_probe,
)


ROOT = Path(__file__).parents[1]


def _write_material_fixture(path: Path) -> None:
    with h5py.File(path, "w") as h5:
        h5.attrs.update({
            "schema_version": "0.1",
            "case_id": "tiny_actual",
            "family": "F2",
            "solver": "fixture",
            "identity_key": "particle_id",
            "trajectory_semantics": "numerical identity fixture",
            "world_frame": "right-handed Cartesian; z up; SI",
            "time_units": "s",
            "length_units": "m",
            "mass_units": "kg",
        })
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("particle_id", data=np.asarray([10, 11], dtype=np.int64))
        h5.create_dataset("particle_zone", data=np.zeros(2, dtype=np.int16))
        h5.create_dataset("valid", data=np.ones((3, 2), dtype=bool))
        positions = np.asarray([
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        ], dtype=np.float32)
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=np.zeros((3, 2, 3), dtype=np.float32))
        h5.create_dataset("density", data=np.full((3, 2), 1000.0, dtype=np.float32))
        h5.create_dataset("pressure", data=np.zeros((3, 2), dtype=np.float32))
        h5.create_dataset("mass", data=np.asarray([[2.0, 3.0]] * 3, dtype=np.float32))
        h5.create_dataset("type", data=np.full((3, 2), 3, dtype=np.int8))
        h5.create_dataset("mk", data=np.asarray([[1, 2]] * 3, dtype=np.int16))

        material = h5.create_group("material")
        material.attrs["seed_selection"] = "fixture source-stratified selection"
        material.attrs["source_label_semantics"] = "initial metadata only"
        material.attrs["integration"] = "Heun"
        material.attrs["integration_substeps"] = 2
        material.attrs["wall_visibility"] = "wall_aware"
        material.create_dataset("tracer_id", data=np.asarray([100, 101], dtype=np.int64))
        material.create_dataset("seed_particle_id", data=np.asarray([10, 11], dtype=np.int64))
        material.create_dataset("seed_particle_zone", data=np.zeros(2, dtype=np.int16))
        material.create_dataset("source_label", data=np.asarray([1, 2], dtype=np.int16))
        material.create_dataset("mass_weight", data=np.asarray([2.0, 3.0], dtype=np.float64))
        material.create_dataset(
            "valid",
            data=np.asarray([[True, True], [False, True], [False, True]], dtype=bool),
        )
        material.create_dataset("position", data=positions)
        material.create_dataset(
            "nearest_support_distance",
            data=np.asarray([[0.0, 0.0], [0.2, 0.01], [0.2, 0.01]], dtype=np.float32),
        )
        material.create_dataset(
            "support_gate_pass",
            data=np.asarray([[True, True], [False, True], [False, True]], dtype=bool),
        )
        material.create_dataset("effective_sample_size", data=np.ones((3, 2), dtype=np.float32))
        material.create_dataset("support_geometry_rank", data=np.full((3, 2), 3, dtype=np.int8))
        material.create_dataset("support_anisotropy", data=np.ones((3, 2), dtype=np.float32))
        material.create_dataset(
            "interpolation_reconstruction_error_mps",
            data=np.zeros((3, 2), dtype=np.float32),
        )
        material.create_dataset("wall_crossing", data=np.zeros((3, 2), dtype=bool))


def _write_fixture_manifest(root: Path, h5_path: Path) -> Path:
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "0.1",
        "release_id": "fixture",
        "formal_release": False,
        "cases": [{
            "case_id": "tiny_actual",
            "family": "F2",
            "lineage_group_id": "tiny_actual",
            "split": "test",
            "hdf5": h5_path.name,
            "geometry": {},
            "numerics": {"particle_spacing_m": 0.1},
            "observation": {"frame_interval_s": 0.5},
            "destination_spec": {
                "lifecycle_model": "closed",
                "destination_frame": {"kind": "world"},
                "sources": {"mode": "mk"},
                "destinations": [{
                    "name": "right",
                    "type": "halfspace",
                    "normal": [1.0, 0.0, 0.0],
                    "offset": 0.25,
                    "side": "ge",
                }],
            },
        }],
    }, indent=2) + "\n")
    return manifest_path


def test_actual_release_audit_covers_all_requested_axes():
    report = build_report()
    summary = report["summary"]

    assert summary["case_count"] == 13
    assert summary["material_present_count"] == 12
    assert summary["seed_material_contract_pass_count"] == 12
    assert summary["source_semantics_declared_count"] == 0
    assert summary["mass_weight_closure_pass_count"] == 12
    assert summary["output_cadence_pass_count"] == 13
    assert summary["explicit_substeps_count"] == 0
    assert summary["support_diagnostic_complete_count"] == 0
    assert summary["sidecar_structural_pass_count"] == 12
    assert summary["candidate_open_face_semantics_pass_count"] == 9
    assert summary["open_face_review_required_count"] == 3
    assert summary["material_wall_visibility_used_count"] == 0
    assert summary["destination_spec_present_count"] == 0
    assert summary["source_destination_closure_pass_count"] == 0
    assert summary["failed_mass_kg"] > 0.0
    assert all(case["support_failure"].get("failed_mass_by_source") is not None for case in report["cases"] if case["seed_material"].get("material_present"))


def test_checked_in_actual_audit_is_reproducible():
    report = build_report()
    checked_in = json.loads(
        (ROOT / "campaigns/v0.1-candidate/r4-tracer-actual-scenario-audit.json").read_text()
    )
    assert checked_in["schema_version"] == report["schema_version"]
    assert checked_in["summary"] == report["summary"]
    assert checked_in["cross_resolution"] == report["cross_resolution"]
    assert checked_in["decision"] == report["decision"]


def test_fixture_reports_support_failure_mass_and_destination_closure(tmp_path: Path):
    h5_path = tmp_path / "tiny_actual.h5"
    _write_material_fixture(h5_path)
    manifest_path = _write_fixture_manifest(tmp_path, h5_path)

    report = build_report(manifest_path, lab_root=ROOT)
    case = report["cases"][0]

    assert case["seed_material"]["status"] == "pass"
    assert case["mass_weights"]["status"] == "pass"
    assert case["cadence_and_integration"]["substeps_per_saved_interval"] == 2
    assert case["support_failure"]["status"] == "pass"
    assert case["support_failure"]["terminal_failed_mass_kg"] == 2.0
    assert case["support_failure"]["failed_mass_by_source"]["1"]["mass_kg"] == 2.0
    assert case["support_failure"]["failed_mass_by_reason"]["support_gate"]["mass_kg"] == 2.0
    assert case["source_destination"]["status"] == "pass"
    assert case["source_destination"]["closure_pass"] is True
    assert case["source_destination"]["per_source"]["1"]["mass_kg"]["numerical_loss"] == 2.0
    assert case["source_destination"]["per_source"]["2"]["mass_kg"]["right"] == 3.0


def test_cross_resolution_audit_rejects_array_index_matching():
    result = cross_resolution_permutation_probe()
    assert result["array_index_matching_allowed"] is False
    assert result["negative_control_detects_index_matching"] is True
    assert result["aggregate_invariant_under_permutation"] is True
    assert result["naive_array_index_mismatch_count"] > 0


def test_static_inventory_exposes_g4_and_producer_interface_gaps():
    report = build_report()
    inventory = report["implementation_inventory"]
    assert inventory["g4_loader"]["capabilities"]["loads_material_group"] is False
    assert inventory["g4_loader"]["capabilities"]["open_face_policy_input"] is False
    assert inventory["trajectory_io"]["capabilities"]["direct_converter_writes_material_group"] is False
    assert inventory["material_writer"]["capabilities"]["material_writer_persists_integration_substeps"] is False
    assert inventory["resolution_comparison"]["capabilities"]["stable_key_guard"] is False
    assert any(gap["id"] == "actual_release_destination_spec_missing" for gap in report["open_interface_gaps"])
