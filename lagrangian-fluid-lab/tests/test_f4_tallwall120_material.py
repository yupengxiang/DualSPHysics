"""CPU contract tests for the independent F4 tall-wall material overlay."""

import json
from pathlib import Path

import numpy as np

from scripts import f4_tallwall120_material as material


def _state(n=4, offset=0.0):
    return {
        "position": np.full((n, 3), offset, dtype=np.float64),
        "reliable": np.ones(n, dtype=bool),
        "contact_time": np.full(n, np.nan, dtype=np.float64),
        "upward_time": np.full(n, np.nan, dtype=np.float64),
        "return_time": np.full(n, np.nan, dtype=np.float64),
        "residence": np.zeros(n, dtype=np.float64),
        "contacted": np.zeros(n, dtype=bool),
        "upward": np.zeros(n, dtype=bool),
        "returned": np.zeros(n, dtype=bool),
    }


def test_definition_binds_tall_wall_and_continuous_events():
    definition = material._tallwall_definition(0.5, 0.0075)

    assert definition["scope_id"] == material.SCOPE_ID
    assert definition["wall_bounds_m"]["zmax"] == 1.2
    assert definition["closed_faces"] == ["bottom", "left", "right", "front", "back"]
    assert definition["open_faces"] == ["top"]
    assert definition["source_definition"]["box_low_m"] == [0.36, 0.12, 0.4]
    assert definition["source_definition"]["box_size_m"] == [0.26, 0.16, 0.14]
    assert definition["destination_definition"]["box_high_m"] == [1.2, 0.4, 0.18]
    assert definition["event_definition"]["contact"]["interface_plane_z_m"] == 0.18
    assert definition["event_definition"]["residence"]["right_censored_if_unresolved"] is True


def test_wall_triangles_reach_1p2_and_keep_top_open():
    walls = material.tallwall_walls()

    assert walls.shape == (10, 3, 3)
    assert float(walls[:, :, 2].max()) == 1.2
    # Five faces are represented by two triangles each; the top face is absent.
    assert not np.any(np.all(np.isclose(walls[:, :, 2], 1.2), axis=1))


def test_checkpoint_generation_fault_preserves_previous_manifest(tmp_path):
    output = tmp_path / "trace.h5"
    binding = "binding-v1"
    first = _state()
    second = _state(offset=1.0)

    first_record = material.write_checkpoint(output, binding, 0, first)
    manifest_path, generation_dir, _ = material._checkpoint_paths(output)
    assert first_record["generation"] in {p.name for p in generation_dir.iterdir()}
    old_manifest = json.loads(manifest_path.read_text())

    try:
        material.write_checkpoint(output, binding, 1, second, fault_after_publish=True)
    except RuntimeError as exc:
        assert "generation publication" in str(exc)
    else:
        raise AssertionError("fault injection did not fire")

    assert json.loads(manifest_path.read_text()) == old_manifest
    recovered = material.read_checkpoint(output, binding)
    assert recovered is not None
    frame, state = recovered
    assert frame == 0
    np.testing.assert_array_equal(state["position"], first["position"])
    assert len(list(generation_dir.glob("state-*.npz"))) == 2


def test_checkpoint_manifest_hash_and_binding_are_fail_closed(tmp_path):
    output = tmp_path / "trace.h5"
    binding = "binding-v1"
    material.write_checkpoint(output, binding, 0, _state())

    try:
        material.read_checkpoint(output, "other-binding")
    except ValueError as exc:
        assert "provenance" in str(exc)
    else:
        raise AssertionError("binding mismatch was accepted")

    manifest_path, generation_dir, _ = material._checkpoint_paths(output)
    record = json.loads(manifest_path.read_text())
    (generation_dir / record["generation"]).write_bytes(b"changed")
    try:
        material.read_checkpoint(output, binding)
    except ValueError as exc:
        assert "changed" in str(exc)
    else:
        raise AssertionError("changed generation was accepted")


def test_proposal_files_are_qualification_only_and_bind_tallwall_source():
    root = Path(__file__).resolve().parents[1]
    short = json.loads((root / "campaigns/core-v1/material/jobs/core-f4-tallwall120-material-canary-s2-v1.json").read_text())
    full = json.loads((root / "campaigns/core-v1/material/jobs/core-f4-tallwall120-material-full434-s2-v1.json").read_text())

    for spec in (short, full):
        assert spec["qualification_only"] is True
        assert spec["qualification_claim"] == "none"
        assert spec["central_ledger_mutation"] == 0
        assert spec["gpu_started"] is False
        assert spec["source_definition"]["wall_bounds_m"]["zmax"] == 1.2
        assert spec["backend"]["unknown_gate_fraction_max"] == 0.01
        assert spec["source"]["source_h5"]["sha256"] == "78631cec15acdd5abcd5c43f326c2dd7c215b3248fd99ec544718bca72a74cad"
    assert short["event_window"]["short_canary_is_event_right_censored"] is True
    assert full["depends_on"] == [short["job_id"]]
