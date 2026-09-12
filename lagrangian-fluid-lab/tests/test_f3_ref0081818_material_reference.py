"""Read-only and fail-closed tests for the ref008 material handoff."""

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_ref0081818_material_reference as adapter


def _score_and_gate(tmp_path, *, status="passed", material_allowed=True,
                    recipe=None, evidence_digest=None):
    out = tmp_path / "continuation"
    out.mkdir()
    adapter.LAB = tmp_path
    adapter.OUT = out
    evidence = tmp_path / "bound-evidence.json"
    evidence.write_text("bound")
    evidence_digest = evidence_digest or adapter.sha256(evidence)
    score = {
        "schema": adapter.SCORE_SCHEMA,
        "status": status,
        "recipe_id": recipe or adapter.RECIPE,
        "production_resolution_m": adapter.PRODUCTION_DP_M,
        "production_source_case_id": adapter.PRODUCTION_CASE,
        "time_window_s": [0.0, adapter.HORIZON_S],
        "coordinate_frame": adapter.COORDINATE_FRAME,
        "control_domain": adapter.CONTROL_DOMAIN,
        "evidence_sha256": {"bound-evidence.json": evidence_digest},
    }
    score_path = out / "score.json"
    score_path.write_text(json.dumps(score))
    gate = {
        "schema": adapter.GATE_SCHEMA,
        "status": status,
        "recipe_id": recipe or adapter.RECIPE,
        "material_production_allowed": material_allowed,
        "production_resolution_m": adapter.PRODUCTION_DP_M,
        "reference_resolutions_m": [adapter.preparation.DP, .0075, .006],
        "time_window_s": [0.0, adapter.HORIZON_S],
        "control_domain": adapter.CONTROL_DOMAIN,
        "coordinate_frame": adapter.COORDINATE_FRAME,
        "production_source_case_id": adapter.PRODUCTION_CASE,
        "scoring_evidence_path": adapter._relative(score_path),
        "scoring_evidence_sha256": adapter.sha256(score_path),
    }
    gate_path = out / adapter.GATE_NAME
    gate_path.write_text(json.dumps(gate))
    return out, gate_path


def test_missing_gate_is_read_only_and_blocks_before_source_access(tmp_path, monkeypatch):
    out = tmp_path / "continuation"
    out.mkdir()
    monkeypatch.setattr(adapter, "LAB", tmp_path)
    monkeypatch.setattr(adapter, "OUT", out)
    with pytest.raises(PermissionError, match="missing required ref008 material evidence"):
        adapter.plan()
    assert list(out.iterdir()) == []


def test_failed_or_historical_gate_is_rejected(tmp_path):
    _, gate_path = _score_and_gate(tmp_path, status="failed")
    with pytest.raises(PermissionError, match="passed ref0081818"):
        adapter.verify_revision_gate(gate_path)

    value = json.loads(gate_path.read_text())
    value["status"] = "passed"
    value["recipe_id"] = "F3_CELL3_NS_visco1_native_nopen"
    gate_path.write_text(json.dumps(value))
    with pytest.raises(PermissionError, match="passed ref0081818"):
        adapter.verify_revision_gate(gate_path)


def test_material_opt_in_is_required_even_after_passed_score(tmp_path):
    _, gate_path = _score_and_gate(tmp_path, material_allowed=False)
    with pytest.raises(PermissionError, match="opted in"):
        adapter.verify_revision_gate(gate_path)


def test_threshold_drift_fails_closed():
    original = copy.deepcopy(adapter.material_score.THRESHOLDS)
    adapter.material_score.THRESHOLDS["path_max_m"] = 99.0
    try:
        with pytest.raises(ValueError, match="thresholds differ"):
            adapter._verify_material_thresholds()
    finally:
        adapter.material_score.THRESHOLDS.clear()
        adapter.material_score.THRESHOLDS.update(original)


def test_material_configurations_are_production_bound_and_unqualified():
    rows = adapter.configurations()
    assert len(rows) == 3
    assert {row["source_case_id"] for row in rows} == {adapter.PRODUCTION_CASE}
    assert {row["dp_m"] for row in rows} == {adapter.PRODUCTION_DP_M}
    assert {row["amplitude"] for row in rows} == {1.0}
    assert [row["output_interval_s"] for row in rows] == [.01, .01, .002]
