"""Tests for the bounded full-field graph resource probe semantics."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.core_formal_admission_audit import _graph_probe_observation


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / (
    "campaigns/core-v1/learning/formal-release-candidate-v2/"
    "full-field-graph-raw-capacity-probe-f4-train0-4updates-v2.json"
)


def test_full_field_probe_is_bound_but_never_capacity_evidence() -> None:
    observation = _graph_probe_observation(PROBE, root=ROOT)
    assert observation["valid"] is True
    assert observation["formal_capacity_evidence"] is False
    assert observation["formal_runs_counted"] == 0
    assert observation["case"]["particles"] == 217086
    assert observation["io_and_graph"]["hdf5_opened_for_diagnostic"] is True
    updates = observation["updates"]
    assert updates["completed"] == 4
    assert updates["estimate_is_extrapolation"] is True
    assert updates["full_pipeline_basis"] == (
        "one representative HDF5 transition plus neighbor rebuild per optimizer update"
    )
    assert updates["estimated_32000_full_pipeline_hours"] > 100


def test_probe_without_explicit_extrapolation_semantics_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(PROBE.read_text(encoding="utf-8"))
    payload["updates"]["estimate_is_extrapolation"] = False
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    observation = _graph_probe_observation(path, root=tmp_path)
    assert observation["valid"] is False

