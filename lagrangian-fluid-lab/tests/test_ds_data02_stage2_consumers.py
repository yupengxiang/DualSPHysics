"""Manufactured and CURRENT-bound checks for the Stage 2 consumer interface."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_consumers import (
    BindingError,
    LifecycleError,
    audit_legacy_consumers,
    build_prospective_split,
    canonical_sha256,
    load_current_catalog,
    materialize_labels,
    prepare_sentinel_observation_plan,
    read_case_window,
    sha256,
    validate_label_config,
)


def _h5_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    source = tmp_path / "trajectory.h5"
    times = np.asarray([0.0, 1.0, 2.0])
    ids = np.asarray([10, 11, 12, 13, 14], dtype="uint32")
    zones = np.asarray([0, 0, 0, 0, 1], dtype="int16")
    initial_type = np.asarray([3, 3, 3, 3, 2], dtype="int8")
    initial_mass = np.asarray([2.0, 3.0, 5.0, 7.0, 11.0], dtype="float32")
    initial_mk = np.asarray([10, 10, 11, 11, 1], dtype="int16")
    valid = np.asarray([[1, 1, 1, 0, 1], [1, 1, 1, 0, 1], [1, 1, 1, 0, 1]], dtype=bool)
    position = np.asarray([
        [[0.25, .5, .5], [-.5, .5, .5], [0., .5, .5], [10., .5, .5], [.5, .5, .5]],
        [[1.25, .5, .5], [-.5, .5, .5], [np.nan, np.nan, np.nan], [10., .5, .5], [.5, .5, .5]],
        [[1.25, .5, .5], [-.5, .5, .5], [.1, .5, .5], [10., .5, .5], [.5, .5, .5]],
    ], dtype="float32")
    velocity = np.zeros_like(position)
    velocity[0, 0] = [1., 0., 0.]
    velocity[1, 0] = [1., 0., 0.]
    velocity[2, 0] = [0., 0., 0.]
    velocity[:, 1:, 0] = 0.
    density = np.full((3, 5), 1000., dtype="float32")
    pressure = np.zeros((3, 5), dtype="float32")
    mass = np.tile(initial_mass, (3, 1))
    frame_type = np.tile(initial_type, (3, 1))
    mk = np.tile(initial_mk, (3, 1))
    with h5py.File(source, "w") as handle:
        handle.attrs.update(
            schema="ds-data-02.hdf5-schema.v1",
            identity_key="(Zone,Idp)",
            coordinate_frame="manufactured_world",
            units_json=json.dumps({"density": "kg/m^3", "mass": "kg", "position": "m",
                                   "pressure": "Pa", "time": "s", "velocity": "m/s"}),
        )
        for name, data in {
            "time": times, "particle_id": ids, "particle_zone": zones,
            "initial_type": initial_type, "initial_mass": initial_mass, "initial_mk": initial_mk,
        }.items():
            handle.create_dataset(name, data=data)
        for name, data in {
            "valid": valid, "type": frame_type, "mk": mk, "density": density,
            "mass": mass, "pressure": pressure,
        }.items():
            handle.create_dataset(name, data=data, chunks=(1, 5))
        handle.create_dataset("position", data=position, chunks=(1, 5, 3))
        handle.create_dataset("velocity", data=velocity, chunks=(1, 5, 3))

    fields = {}
    with h5py.File(source, "r") as handle:
        for name, dataset in handle.items():
            fields[name] = {"shape": list(dataset.shape), "dtype": str(dataset.dtype),
                            "chunks": list(dataset.chunks) if dataset.chunks is not None else None}
    row = {
        "family_id": "F0",
        "physical_case_id": "MANUFACTURED_MOVING_SURFACE",
        "frames": 3,
        "particles": 5,
        "actual_time_window_s": [0.0, 2.0],
        "manifest": None,
        "xmf": None,
        "trajectory": {"path": str(source), "producer_declared_sha256": sha256(source),
                       "recomputed_sha256": None, "bytes": source.stat().st_size,
                       "mtime_ns": source.stat().st_mtime_ns},
        "header": {"fields": fields,
                   "units": {"density": "kg/m^3", "mass": "kg", "position": "m",
                             "pressure": "Pa", "time": "s", "velocity": "m/s"},
                   "identity_key": "(Zone,Idp)", "coordinate_frame": "manufactured_world"},
        "source_bindings": {},
        "quality": {"visual": "STAGE1_PRESERVED", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    catalog_path = tmp_path / "CURRENT336.json"
    source_catalog = tmp_path / "CASES_336.json"
    source_catalog.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
    payload = {"schema": "ds02.stage2.current336.v1", "source_catalog": str(source_catalog),
               "source_catalog_sha256": sha256(source_catalog), "unresolved": 0,
               "total_hdf5_bytes": source.stat().st_size, "cases": [row]}
    catalog_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    config = {
        "schema": "ds02.stage2.observation-config.v2",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "manufactured_world",
        "source_assignment": "initial_regions",
        "source_regions": [{"id": "left_source", "bounds": [[-1, 1], [0, 1], [0, 1]]}],
        "destination_regions": [
            {"id": "left", "bounds": [[-1, 1], [0, 1], [0, 1]]},
            {"id": "right", "bounds": [[1, 2], [0, 1], [0, 1]]},
        ],
        "events": [{
            "id": "sweeping_wall",
            "surface": {"kind": "translating_plane", "point_m": [.5, 0, 0],
                         "normal_m": [2, 0, 0], "velocity_m_s": [.25, 0, 0],
                         "aperture_axes": [1, 2], "aperture_bounds": [[0, 1], [0, 1]],
                         "aperture_frame": "surface_local", "reference_time_s": 0},
        }],
    }
    return catalog_path, source, config


@pytest.fixture
def fixture(tmp_path):
    return _h5_fixture(tmp_path)


def test_current_binding_and_bounded_window(fixture):
    catalog_path, source, _ = fixture
    catalog = load_current_catalog(catalog_path, expected_case_count=1, verify_source_catalog=True)
    case = catalog.case("MANUFACTURED_MOVING_SURFACE")
    binding = case.inspect(verify_source_hash=True)
    assert binding["catalog_sha256"] == sha256(catalog_path)
    assert binding["trajectory"]["recomputed_sha256"] == sha256(source)
    assert binding["physical_condition_scopes"]["hdf5"]["recomputed_sha256"] == sha256(source)
    assert binding["physical_condition_scopes"]["equality_claim"] == "NOT_APPLICABLE"
    window = read_case_window(case, frame_start=0, frame_stop=1, particle_start=0, particle_stop=2,
                              fields=("time", "position", "valid", "particle_id", "particle_zone"))
    assert window["position"].shape == (1, 2, 3)
    np.testing.assert_array_equal(window["particle_id"], [10, 11])
    assert window["binding"]["quality"]["QN"] == "UNKNOWN"


def test_labels_keep_all_initial_fluid_mass_nan_invalid_and_relative_motion(fixture, tmp_path):
    catalog_path, _, config = fixture
    catalog = load_current_catalog(catalog_path, expected_case_count=1)
    output = tmp_path / "moving-labels.h5"
    report = materialize_labels(catalog, "MANUFACTURED_MOVING_SURFACE", output, config, particle_chunk=2)
    assert report["initial_fluid_mass_kg"] == pytest.approx(17.0)
    with h5py.File(output, "r") as handle:
        assert handle.attrs["schema"] == "ds02.stage2.observation-labels.v2"
        assert handle.attrs["initial_fluid_mass_kg"] == pytest.approx(17.0)
        assert handle.attrs["initial_source_unknown_mass_kg"] == pytest.approx(7.0)
        np.testing.assert_array_equal(handle["source_label"][:], [1, 1, 1, 0, 0])
        np.testing.assert_array_equal(handle["initially_active"][:], [True, True, True, False, False])
        assert handle["invalid_state_mass_kg"][1] == pytest.approx(5.0)
        assert handle["missing_mass_kg"][0] == pytest.approx(7.0)
        # Particle 10 crosses x=.5+.25t; its relative normal speed is 1-.25.
        assert handle["forward_backward_mass_kg"][1, 0, 0] == pytest.approx(2.0)
        assert handle["first_passage_chord_time"][0, 0] == pytest.approx(1.0 / 3.0)
        assert handle["first_passage_relative_normal_speed_m_s"][0, 0] == pytest.approx(.75)
        assert handle.attrs["q_n_status"] == "NOT_ASSESSED"
        assert handle.attrs["q_e_status"] == "NOT_ASSESSED"
        assert handle.attrs["model_invoked"] in (False, np.False_)


def test_identity_time_and_operator_counterexamples(fixture, tmp_path):
    catalog_path, source, config = fixture
    with h5py.File(source, "r+") as handle:
        handle["particle_id"][1] = handle["particle_id"][0]
    expected_mtime = json.loads(catalog_path.read_text())["cases"][0]["trajectory"]["mtime_ns"]
    os.utime(source, ns=(expected_mtime, expected_mtime))
    catalog = load_current_catalog(catalog_path, expected_case_count=1)
    with pytest.raises(BindingError, match="duplicate"):
        catalog.case("MANUFACTURED_MOVING_SURFACE").inspect()
    with h5py.File(source, "r+") as handle:
        handle["particle_id"][1] = 11
        handle["time"][2] = .5
    os.utime(source, ns=(expected_mtime, expected_mtime))
    # The CURRENT stat/hash binding rejects a changed source before a consumer
    # can sort or interpolate an invalid time axis.
    with pytest.raises(BindingError):
        catalog.case("MANUFACTURED_MOVING_SURFACE").inspect()
    bad = json.loads(json.dumps(config))
    bad["events"][0]["surface"]["kind"] = "fixed_plane"
    bad["events"][0]["surface"]["velocity_m_s"] = [.25, 0, 0]
    with pytest.raises(BindingError, match="fixed_plane"):
        validate_label_config(bad)


def test_lifecycle_revival_is_rejected(fixture, tmp_path):
    catalog_path, source, config = fixture
    with h5py.File(source, "r+") as handle:
        handle["time"][2] = 2.0
        handle["valid"][1, 3] = 1
    # Rebind the changed fixture to isolate the lifecycle error from CURRENT.
    catalog_path.unlink()
    source_catalog = catalog_path.parent / "CASES_336.json"
    payload = json.loads(source_catalog.read_text())
    row = payload["cases"][0]
    row["trajectory"].update(bytes=source.stat().st_size, mtime_ns=source.stat().st_mtime_ns,
                              producer_declared_sha256=sha256(source))
    with h5py.File(source, "r") as handle:
        row["header"]["fields"] = {name: {"shape": list(ds.shape), "dtype": str(ds.dtype),
                                           "chunks": list(ds.chunks) if ds.chunks is not None else None}
                                    for name, ds in handle.items()}
    source_catalog.write_text(json.dumps(payload), encoding="utf-8")
    catalog_payload = {"schema": "ds02.stage2.current336.v1", "source_catalog": str(source_catalog),
                       "source_catalog_sha256": sha256(source_catalog), "unresolved": 0,
                       "total_hdf5_bytes": source.stat().st_size, "cases": [row]}
    catalog_path.write_text(json.dumps(catalog_payload), encoding="utf-8")
    catalog = load_current_catalog(catalog_path, expected_case_count=1)
    with pytest.raises(LifecycleError, match="revived"):
        materialize_labels(catalog, "MANUFACTURED_MOVING_SURFACE", tmp_path / "bad.h5", config)


def test_split_is_prospective_and_never_hidden(fixture):
    catalog_path, _, _ = fixture
    catalog = load_current_catalog(catalog_path, expected_case_count=1)
    split = build_prospective_split(catalog)
    assert split["schema"] == "ds02.stage2.prospective-split.v1"
    assert split["hidden_test"] is False
    assert split["cases"][0]["stage1_seen"] is True
    assert split["cases"][0]["hidden_test"] is False
    assert split["cases"][0]["task_eligibility"]["QN"] == "UNKNOWN"


def test_real_sentinel_plan_binds_fourteen_rows_without_claiming_precision():
    root = Path(__file__).resolve().parents[1]
    catalog_path = root / "campaigns/ds-data-02/stage2/CURRENT336.json"
    matrix = root / "campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
    plan = prepare_sentinel_observation_plan(catalog_path, matrix)
    assert plan["schema"] == "ds02.stage2.sentinel-observation-plan.v1"
    assert len(plan["sentinels"]) == 14
    assert all(row["label_status"] == "NOT_MATERIALIZED" for row in plan["sentinels"])
    assert all(row["hidden_test"] is False and row["QN"] == "UNKNOWN" for row in plan["sentinels"])


def test_real_current_preserves_four_aliases_and_f2_f3_manifest_variants():
    root = Path(__file__).resolve().parents[1]
    catalog_path = root / "campaigns/ds-data-02/stage2/CURRENT336.json"
    catalog = load_current_catalog(catalog_path)

    aliases = [case for case in catalog.cases() if case.row.get("manifest_physical_case_id")]
    assert len(aliases) == 4
    for case in aliases:
        row = case.row
        assert row["manifest_physical_case_id"] != row["physical_case_id"]
        evidence = row["accepted_alias_evidence"]
        assert evidence["canonical_physical_case"]["inventory_physical_case_id"] == row["physical_case_id"]
        assert evidence["actual_converter_scope"]["separate_from_canonical_source_scope"] is True
        # This is intentionally not an equality assertion: the canonical
        # inventory scope and the actual legacy converter scope remain distinct.
        assert "not asserted" in evidence["actual_converter_scope"]["scope_equality_claim"]
        manifest = json.loads(Path(row["manifest"]["path"]).read_text(encoding="utf-8"))
        assert manifest["physical_case_id"] == row["manifest_physical_case_id"]
        assert manifest["family_id"] == row["family_id"]
        # HDF5 header and one-frame scope separation is exercised by the
        # guarded current-probe worker; this unit test remains metadata-only.
        assert len(row["trajectory"]["producer_declared_sha256"]) == 64

    f2 = next(case for case in catalog.cases() if case.family_id == "F2")
    f3 = next(case for case in catalog.cases() if case.family_id == "F3")
    f2_manifest = json.loads(Path(f2.row["manifest"]["path"]).read_text(encoding="utf-8"))
    f3_manifest = json.loads(Path(f3.row["manifest"]["path"]).read_text(encoding="utf-8"))
    assert f2_manifest["schema"] == "ds02.stage1.paraview-temporal-product.v1"
    assert f3_manifest["schema"] == "ds02.stage1.paraview-temporal-product.v1"
    # F2/F3 use the same declared product schema while carrying family-specific
    # temporal contracts and windows; consumers must not infer one from the other.
    assert f2_manifest["stage1_contract"] != f3_manifest["stage1_contract"]
    assert f2_manifest["physical_window_s"] != f3_manifest["physical_window_s"]


def test_legacy_inventory_reports_the_known_migration_hazards():
    root = Path(__file__).resolve().parents[1]
    report = audit_legacy_consumers(root)
    rows = {row["path"]: row for row in report["rows"]}
    assert "latest_or_glob_discovery" in rows["scripts/ds_data02_f3_stage8_labels.py"]["findings"]
    assert "solver_log_dependency" in rows["scripts/ds_data02_f3_stage8_audit.py"]["findings"]
    assert "fixed_case_list" in rows["scripts/ds_data02_f2_stage8_labels.py"]["findings"]
