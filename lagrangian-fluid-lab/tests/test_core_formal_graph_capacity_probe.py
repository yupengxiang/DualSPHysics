"""Tests for the bounded full-field graph resource probe semantics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.core_formal_admission_audit import _graph_probe_observation
from scripts.core_formal_graph_capacity_probe import _load_candidate, _manifest_binding


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


def test_graph_probe_candidate_reader_rejects_duplicate_keys_and_symlinks(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        _load_candidate(duplicate)

    source = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
    symlink = tmp_path / "candidate-link.json"
    symlink.symlink_to(source)
    with pytest.raises(ValueError, match="symlink is forbidden"):
        _load_candidate(symlink)


def test_graph_manifest_binding_parses_and_hashes_one_strict_byte_snapshot(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    raw = b'{"schema":"core.dataset.v2","cases":[]}'
    manifest.write_bytes(raw)
    candidate = {
        "manifest_bindings": [{
            "path": "manifest.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }],
    }

    payload, binding = _manifest_binding(candidate, manifest, tmp_path)

    assert payload == {"schema": "core.dataset.v2", "cases": []}
    assert binding == {
        "path": "manifest.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_graph_probe_refuses_missing_production_denominator(tmp_path: Path) -> None:
    candidate_path = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["admission_observation"].pop("production_denominator")
    path = tmp_path / "missing-denominator.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit production denominator"):
        _load_candidate(path)


def test_graph_probe_rejects_empty_probe_shape() -> None:
    candidate_path = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
    candidate = _load_candidate(candidate_path)
    with pytest.raises(ValueError, match="hidden and centers"):
        # Manifest/data-root are not reached because shape validation is first.
        from scripts.core_formal_graph_capacity_probe import run_probe
        run_probe(candidate, manifest=ROOT / "missing.h5", data_root=ROOT,
                  hidden=0, centers=0, device="cpu")
