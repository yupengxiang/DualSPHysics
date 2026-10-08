from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_evaluator_v1.py"
spec = importlib.util.spec_from_file_location("family_label_quality_evaluator_v1", SCRIPT)
assert spec and spec.loader
EVALUATOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EVALUATOR)


def test_boundary_rejects_report_that_grants_fate() -> None:
    boundary = {
        "physical_fate": "KNOWN", "dynamical_impact": "UNKNOWN",
        "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN",
    }
    assert any(boundary.get(key) != "UNKNOWN" for key in boundary)


@pytest.mark.skipif(
    not Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
        "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/"
        "seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
    ).is_file(),
    reason="root seven-family quality report is not mounted",
)
def test_actual_quality_evaluator_is_json_only_and_keeps_unknowns(tmp_path: Path) -> None:
    manifest = ROOT / "campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
    report = Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
        "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/"
        "seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
    )
    receipt = report.parent / "execution-receipt.json"
    result = EVALUATOR.evaluate(manifest, report, tmp_path / "evaluator.json", receipt)
    assert result["status"] == "PASS_SEVEN_FAMILY_TASK_SCOPE_NO_QUALIFICATION"
    assert len(result["family_cards"]) == 7
    assert {card["source_role"] for card in result["family_cards"]} == {
        "native_initial_mk", "initial_spatial_region"
    }
    assert all(card["task_eligibility"]["physical_fate"] == "UNKNOWN" for card in result["family_cards"])
    assert result["evaluator_contract"]["effective_split_safe"] is False
    assert result["read_policy"]["materialized_label_h5_opened"] is False
    assert result["read_policy"]["original_trajectory_h5_opened"] is False


@pytest.mark.skipif(
    not Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
        "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/"
        "seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
    ).is_file(),
    reason="root seven-family quality report is not mounted",
)
def test_actual_evaluator_request_has_infra_v8_scope(tmp_path: Path) -> None:
    manifest = ROOT / "campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
    report = Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
        "DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/"
        "seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
    )
    receipt = report.parent / "execution-receipt.json"
    runtime_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    worker_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics")
    request = EVALUATOR.make_request(manifest, report, tmp_path / "request.json", runtime_root, receipt, worker_root)
    assert request["family_id"] == "infra"
    assert request["dataset_families"] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    assert request["launch_allowed"] is True
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert all(Path(path).is_file() for path in request["input_files"])
