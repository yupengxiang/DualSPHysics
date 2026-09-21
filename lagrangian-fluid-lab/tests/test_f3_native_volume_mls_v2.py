"""Cadence-selection tests for the versioned F3 native MLS runner."""

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f3_native_volume_mls_v2 import (
    F3ReferenceProvider,
    _selection_hash,
    audit_source,
)


ROOT = Path(__file__).parents[1]
XML = (ROOT / "campaigns/l1-resume/artifacts/cell3-nopen-qualification"
       / "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
       / "F3_CELL3_plain_0p0075_Def.xml")


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "dense.h5"
    frames, particles = 11, 4
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    position[:, :, 2] = 0.05
    position[:, :, 0] = np.arange(frames, dtype=np.float32)[:, None] * 1.0e-4
    velocity = np.zeros_like(position)
    velocity[:, :, 0] = np.arange(frames, dtype=np.float32)[:, None]
    with h5py.File(path, "w") as handle:
        handle["time"] = np.arange(frames, dtype=np.float64) * 0.002
        handle["position"] = position
        handle["velocity"] = velocity
        handle["mass"] = np.full((frames, particles), 1.0e-3, dtype=np.float32)
        handle["density"] = np.full((frames, particles), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((frames, particles), dtype=np.uint8)
        handle["type"] = np.full((frames, particles), 3, dtype=np.int8)
    return path


def _prepared(tmp_path: Path) -> Path:
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps({
        "dp_m": 0.0075,
        "candidate_definition": str(XML),
        "case_id": "synthetic-cadence",
        "recipe_id": "test",
        "qualified": False,
        "formal_release": False,
        "wall_spec": {},
    }))
    return path


def _selection(source: Path, tmp_path: Path) -> Path:
    indices = np.array([0, 5, 10], dtype=np.int64)
    value = {
        "schema": "core.material.f3.native_volume_mls.frame_selection.v1",
        "selection_id": "test-every-five",
        "selection_mode": "every_fifth_direct_native_frame",
        "source_h5": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_frame_count": 11,
        "source_native_saved_interval_s": 0.002,
        "target_nominal_interval_s": 0.01,
        "target_time_tolerance_s": 1.0e-12,
        "logical_frame_count": 3,
        "source_frame_indices": indices.tolist(),
        "selection_sha256": _selection_hash(indices),
        "interpolation": False,
        "qualification_claim": "none",
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(value))
    return path


def test_provider_selects_actual_native_frames_and_keeps_source_indices(tmp_path):
    source = _source(tmp_path)
    selection = _selection(source, tmp_path)
    with F3ReferenceProvider(source, frame_index_map=selection) as provider:
        assert provider.frame_count == 3
        assert provider.frame_indices.tolist() == [0, 5, 10]
        assert np.allclose(provider.times, [0.0, 0.01, 0.02])
        assert provider.frame(1).frame_index == 5
        assert np.all(provider.frame(1).velocity[:, 0] == 5.0)
        assert provider.frame(2).frame_index == 10


def test_audit_reports_logical_and_source_frame_counts_without_interpolation(tmp_path):
    source = _source(tmp_path)
    prepared = _prepared(tmp_path)
    selection = _selection(source, tmp_path)
    report = audit_source(source, prepared, frame_index_map=selection)
    assert report["schema"].endswith("source_preflight.v2")
    assert report["source"]["frames"] == 3
    assert report["source"]["source_frames"] == 11
    assert report["source"]["interpolation"] is False
    assert report["frame_selection"]["selection_mode"] == "every_fifth_direct_native_frame"
    assert report["frame_selection"]["source_frame_indices"] == [0, 5, 10]


def test_selection_rejects_a_hash_or_endpoint_change(tmp_path):
    source = _source(tmp_path)
    selection = _selection(source, tmp_path)
    value = json.loads(selection.read_text())
    value["selection_sha256"] = "0" * 64
    selection.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="index hash"):
        with F3ReferenceProvider(source, frame_index_map=selection):
            pass


@pytest.mark.parametrize("bad_indices", [[[0.0, 5, 10]], [[True, 5, 10]]])
def test_selection_rejects_non_integer_or_boolean_indices(tmp_path, bad_indices):
    source = _source(tmp_path)
    selection = _selection(source, tmp_path)
    value = json.loads(selection.read_text())
    value["source_frame_indices"] = bad_indices[0]
    selection.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="non-bool integers"):
        with F3ReferenceProvider(source, frame_index_map=selection):
            pass


@pytest.mark.parametrize("bad_tolerance", [float("nan"), float("inf"), -1.0])
def test_selection_rejects_nonfinite_or_negative_tolerance(tmp_path, bad_tolerance):
    source = _source(tmp_path)
    selection = _selection(source, tmp_path)
    value = json.loads(selection.read_text())
    value["target_time_tolerance_s"] = bad_tolerance
    selection.write_text(json.dumps(value, allow_nan=True))
    with pytest.raises(ValueError, match="tolerance"):
        with F3ReferenceProvider(source, frame_index_map=selection):
            pass
