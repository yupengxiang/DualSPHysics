"""Contract tests for the bounded native-.002 F3 cadence adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f3_native_cadence_adapter_v1 import (
    FIXED_GATES,
    MATCHED_STRIDE,
    NATIVE_INTERVAL_S,
    build_preflight,
    inspect_native_source,
    make_direct_selection,
    run_canary,
)


def _source(tmp_path: Path, *, interval: float = NATIVE_INTERVAL_S) -> Path:
    path = tmp_path / "native.h5"
    frames, particles = 11, 4
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    position[:, :, 2] = 0.05
    velocity = np.zeros_like(position)
    mass = np.full((frames, particles), 1.0e-3, dtype=np.float32)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    with h5py.File(path, "w") as handle:
        handle["time"] = np.arange(frames, dtype=np.float64) * interval
        handle["position"] = position
        handle["velocity"] = velocity
        handle["mass"] = mass
        handle["density"] = density
        handle["valid"] = np.ones((frames, particles), dtype=np.uint8)
        handle["type"] = np.full((frames, particles), 3, dtype=np.int8)
    return path


def _prepared(tmp_path: Path) -> Path:
    xml = tmp_path / "candidate.xml"
    xml.write_text('<parameter key="Kernel" value="2"/>\n', encoding="utf-8")
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps({
        "dp_m": 0.0075,
        "candidate_definition": str(xml),
        "case_id": "synthetic-native002",
        "recipe_id": "contract",
        "qualified": False,
        "formal_release": False,
    }), encoding="utf-8")
    return path


def test_preflight_binds_fixed_gates_denominator_and_lineage(tmp_path: Path) -> None:
    source = _source(tmp_path)
    prepared = _prepared(tmp_path)

    report = build_preflight(source, prepared, seeds=512, substeps=4, canary_intervals=4)

    assert report["status"] == "ready_for_bounded_canary"
    assert report["qualification_claim"] == "none"
    assert report["cadence_contract"]["native_output_interval_s"] == NATIVE_INTERVAL_S
    assert report["cadence_contract"]["interpolation"] is False
    assert report["fixed_gates_unchanged"] == FIXED_GATES
    assert report["failure_denominator"]["seed_population"].startswith("all geometric")
    assert report["event_window"]["full_window_available"] is False
    assert report["bounded_canary"]["frames_including_initial"] == 5
    assert len(report["lineage"]["lineage_sha256"]) == 64
    assert report["lineage"]["source"]["sha256"] == report["source"]["sha256"]
    assert report["registry_mutations"] == 0
    assert report["ledger_mutations"] == 0


def test_direct_selection_is_every_fifth_native_frame_and_immutable(tmp_path: Path) -> None:
    source = _source(tmp_path)
    selection_path = tmp_path / "selection.json"
    selection = make_direct_selection(source, selection_path)
    value = json.loads(selection_path.read_text(encoding="utf-8"))

    assert value["source_frame_indices"] == [0, 5, 10]
    assert value["selection_mode"] == "every_fifth_direct_native_frame"
    assert value["interpolation"] is False
    assert selection["sha256"] == hashlib.sha256(selection_path.read_bytes()).hexdigest()
    assert value["source_native_saved_interval_s"] == NATIVE_INTERVAL_S
    assert value["target_nominal_interval_s"] == 0.01
    assert MATCHED_STRIDE == 5


def test_preflight_rejects_coarse_source_as_native002(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"not native \.002"):
        inspect_native_source(_source(tmp_path, interval=0.01))


def test_preflight_rejects_selection_hash_or_interpolation_drift(tmp_path: Path) -> None:
    source = _source(tmp_path)
    prepared = _prepared(tmp_path)
    selection_path = tmp_path / "selection.json"
    make_direct_selection(source, selection_path)
    value = json.loads(selection_path.read_text(encoding="utf-8"))
    value["interpolation"] = True
    value["selection_sha256"] = "0" * 64
    selection_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="strict direct native selection"):
        build_preflight(source, prepared, frame_selection=selection_path)


def test_unreviewed_runner_refuses_long_run_before_backend_call(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unreviewed long run"):
        run_canary(source=_source(tmp_path), prepared=_prepared(tmp_path),
                   output=tmp_path / "trace.h5", stop_after=21)
