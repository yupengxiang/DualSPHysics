import copy
import json

from scripts.core_dataset import (COMPACT_SCHEMA, CoreDataset, _write_npz_asset,
                                  compactify_manifest, sha256_file, validate_manifest)

from test_core_contract import example_known, tiny_manifest


def test_compact_manifest_resolves_hashed_shared_inputs(tmp_path):
    base = tiny_manifest(tmp_path)
    known = example_known()
    geometry_path = tmp_path / "geometry.npz"
    control_path = tmp_path / "control.npz"
    geometry_hash = _write_npz_asset(
        geometry_path,
        arrays={"triangles": known.geometry.triangles, "component_id": known.geometry.component_id,
                "body_id": known.geometry.body_id, "wall_velocity": known.geometry.wall_velocity},
        metadata={"kind": "geometry", "coordinate_frame": known.coordinate_frame,
                  "version": "core.input_asset.v1"})
    control_hash = _write_npz_asset(
        control_path, arrays={"samples": known.control.samples},
        metadata={"kind": "control", "version": "core.input_asset.v1"})
    row = copy.deepcopy(base["cases"][0])
    row.pop("known_inputs")
    row["known_inputs_ref"] = {
        "geometry": {"path": "geometry.npz", "sha256": geometry_hash},
        "control": {"path": "control.npz", "sha256": control_hash},
        "physics": dict(known.physics), "numerics": dict(known.numerics),
        "coordinate_frame": known.coordinate_frame, "contract_version": known.contract_version,
    }
    manifest = {"schema": COMPACT_SCHEMA, "dataset_id": "tiny-v2", "cases": [row]}
    validate_manifest(manifest)
    with CoreDataset(manifest, tmp_path) as data:
        loaded = data.known_inputs("tiny")
        assert data.verify_sources()["tiny"] == row["sha256"]
        assert loaded.control.samples.shape == known.control.samples.shape
        assert loaded.geometry.triangles.shape == known.geometry.triangles.shape


def test_compactify_v1_materializes_hash_bound_assets_without_opening_hdf5(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest_path = source / "manifest.json"
    manifest_path.write_text(json.dumps(tiny_manifest(source)))
    output = source / "manifest-v2.json"

    compact = compactify_manifest(manifest_path, source, output_manifest=output)

    assert compact["schema"] == COMPACT_SCHEMA
    assert compact["formal_release"] is False
    assert compact["source_schema"] == "core.dataset.v1"
    assert output.is_file()
    row = compact["cases"][0]
    assert "known_inputs" not in row
    assert set(row["known_inputs_ref"]) >= {
        "geometry", "control", "physics", "numerics", "coordinate_frame",
        "contract_version",
    }
    geometry = source / row["known_inputs_ref"]["geometry"]["path"]
    control = source / row["known_inputs_ref"]["control"]["path"]
    assert geometry.is_file() and control.is_file()
    validate_manifest(compact)
    with CoreDataset(compact, source) as data:
        known = data.known_inputs(row["case_id"])
        assert known.control.centre == tuple(example_known().control.centre)
        assert known.geometry.triangles.shape == example_known().geometry.triangles.shape
