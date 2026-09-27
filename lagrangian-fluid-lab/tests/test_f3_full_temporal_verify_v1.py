import json

import h5py
import numpy as np
import pytest

from scripts.core_contract import contract_hash
from scripts.core_dataset import compactify_manifest, sha256_file
from scripts.f3_full_temporal_verify_v1 import verify_f3_full_temporal
import scripts.f3_full_temporal_verify_v1 as verifier
from test_core_contract import example_known


def _make_v2_case(tmp_path):
    trajectory = tmp_path / "trajectory.h5"
    frame_count, particle_count = 5, 4
    base_position = np.array([
        [0.0, 0.0, 0.1], [0.1, 0.0, 0.1], [0.0, 0.1, 0.1], [0.1, 0.1, 0.1],
    ], dtype=np.float32)
    position = np.stack([base_position + np.float32(frame) * 0.002
                         for frame in range(frame_count)])
    base_velocity = np.array([
        [0.1, 0.0, 0.0], [0.2, 0.0, 0.0], [0.1, 0.1, 0.0], [0.2, 0.1, 0.0],
    ], dtype=np.float32)
    velocity = np.stack([base_velocity + np.float32(frame) * 0.03
                         for frame in range(frame_count)])
    mass = np.broadcast_to(
        np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        (frame_count, particle_count),
    ).copy()
    valid = np.ones((frame_count, particle_count), dtype=np.bool_)
    with h5py.File(trajectory, "w") as handle:
        handle.attrs["split"] = "train"
        handle["time"] = np.array([0.0, 0.1, 0.23, 0.5, 0.9], dtype=np.float64)
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = np.array([101, 102, 201, 202], dtype=np.uint32)
        handle["particle_zone"] = np.array([0, 0, 1, 1], dtype=np.int16)
        handle["mass"] = mass
        handle["valid"] = valid

    known = example_known()
    source_manifest = tmp_path / "source-v1.json"
    source_manifest.write_text(json.dumps({
        "schema": "core.dataset.v1",
        "dataset_id": "synthetic-f3",
        "cases": [{
            "case_id": "synthetic-f3",
            "physical_case_id": "synthetic-f3",
            "lineage_group_id": "synthetic-f3",
            "family": "F3",
            "split": "train",
            "hdf5": trajectory.name,
            "sha256": sha256_file(trajectory),
            "bytes": trajectory.stat().st_size,
            "known_inputs": known.as_dict(),
            "known_inputs_sha256": contract_hash(known),
        }],
    }))
    manifest = tmp_path / "dataset-v2.json"
    compactify_manifest(source_manifest, tmp_path, output_manifest=manifest)
    return manifest, trajectory


def _refresh_manifest_hash(manifest, trajectory):
    payload = json.loads(manifest.read_text())
    row = payload["cases"][0]
    row["sha256"] = sha256_file(trajectory)
    row["bytes"] = trajectory.stat().st_size
    manifest.write_text(json.dumps(payload, sort_keys=True))


def test_full_temporal_pass_uses_bounded_direct_reader_and_contracts(tmp_path, monkeypatch):
    manifest, _ = _make_v2_case(tmp_path)

    def forbidden_read_state(*_args, **_kwargs):
        raise AssertionError("full temporal verifier must not materialize CoreDataset State")

    monkeypatch.setattr(verifier.CoreDataset, "read_state", forbidden_read_state)
    result = verify_f3_full_temporal(
        manifest, tmp_path, frame_chunk_size=1, max_chunk_bytes=8 * 1024 * 1024,
    )

    assert result["schema"] == "core.f3.full_temporal_verification.v1"
    assert result["dataset_schema"] == "core.dataset.v2"
    assert result["full_temporal_scan"] is True
    assert result["qualification_inferred"] is False
    assert result["formal_training"] is False
    assert result["T1_numerical"] is False
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["case_count"] == 1
    assert result["transition_count"] == 4
    assert result["passed"] is True
    case = result["cases"][0]
    assert case["checked_transition_count"] == case["transition_count"] == 4
    assert case["oracle"]["predictor_received_future_state"] is False
    assert case["oracle"]["privileged_reference_only"] is True
    assert case["oracle"]["position_max_abs_error"] <= 1e-10
    assert case["oracle"]["native_velocity_max_abs_error"] <= 1e-10
    assert case["chunk_bound"]["frame_chunk_size"] == 1
    assert result["source_hashes"][case["case_id"]] == case["source_sha256"]


def test_chunk_size_changes_buffer_bound_not_temporal_coverage(tmp_path):
    manifest, _ = _make_v2_case(tmp_path)
    narrow = verify_f3_full_temporal(manifest, tmp_path, frame_chunk_size=1)
    wide = verify_f3_full_temporal(manifest, tmp_path, frame_chunk_size=3)

    assert narrow["transition_count"] == wide["transition_count"] == 4
    assert narrow["cases"][0]["checked_transition_count"] == 4
    assert wide["cases"][0]["checked_transition_count"] == 4
    assert narrow["cases"][0]["oracle"] == wide["cases"][0]["oracle"]
    assert narrow["cases"][0]["chunk_bound"]["frame_chunk_size"] == 1
    assert wide["cases"][0]["chunk_bound"]["frame_chunk_size"] == 3
    assert (narrow["cases"][0]["chunk_bound"]["estimated_numeric_buffer_bytes"]
            < wide["cases"][0]["chunk_bound"]["estimated_numeric_buffer_bytes"])


def test_memory_bound_is_fail_closed(tmp_path):
    manifest, _ = _make_v2_case(tmp_path)
    with pytest.raises(ValueError, match="max_chunk_bytes"):
        verify_f3_full_temporal(manifest, tmp_path, frame_chunk_size=2, max_chunk_bytes=1)


def test_cli_emits_json_only_and_does_not_create_output_directory(tmp_path, capsys):
    manifest, _ = _make_v2_case(tmp_path)
    assert verifier.main([
        "--manifest", str(manifest), "--data-root", str(tmp_path),
        "--case-id", "synthetic-f3", "--frame-chunk-size", "2",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["full_temporal_scan"] is True
    assert result["cases"][0]["checked_transition_count"] == 4
    assert not (tmp_path / "output").exists()


def _make_nonfinite(handle):
    handle["position"][1, 0, 0] = np.nan


def _make_duplicate_identity(handle):
    handle["particle_id"][1] = handle["particle_id"][0]


def _make_changed_mass(handle):
    handle["mass"][2, 1] = 99.0


def _make_changed_valid(handle):
    handle["valid"][2, 1] = False


def _make_bad_time(handle):
    handle["time"][2] = handle["time"][1]


@pytest.mark.parametrize("mutator,pattern", [
    (_make_nonfinite, "nonfinite active position"),
    (_make_duplicate_identity, "duplicate composite particle identity"),
    (_make_changed_mass, "mass lifecycle changed"),
    (_make_changed_valid, "valid lifecycle changed"),
    (_make_bad_time, "strictly increasing"),
])
def test_full_temporal_contract_rejects_invalid_native_inputs(tmp_path, mutator, pattern):
    manifest, trajectory = _make_v2_case(tmp_path)
    with h5py.File(trajectory, "r+") as handle:
        mutator(handle)
    _refresh_manifest_hash(manifest, trajectory)

    with pytest.raises(ValueError, match=pattern):
        verify_f3_full_temporal(manifest, tmp_path, frame_chunk_size=2)
