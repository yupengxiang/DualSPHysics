from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_label_quality_evaluator_v2_strict.py"
spec = importlib.util.spec_from_file_location("family_label_quality_evaluator_v2_strict", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MANIFEST = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
REPORT = DATA / "families/infra/DS02_STAGE2_SEVEN_ACTUAL_FAMILY_LABEL_QUALITY_V3/seven-actual-family-label-quality-v3-root-029-001/seven-family-label-quality-v3.json"
RECEIPT = REPORT.parent / "execution-receipt.json"


def _mounted() -> bool:
    return all(path.is_file() for path in (MANIFEST, REPORT, RECEIPT))


@pytest.mark.skipif(not _mounted(), reason="root seven-family quality product is not mounted")
def test_strict_evaluator_binds_actual_receipt_and_keeps_unknowns(tmp_path: Path) -> None:
    result = MODULE.evaluate(MANIFEST, REPORT, RECEIPT, tmp_path / "result.json")
    assert result["status"] == "PASS_SEVEN_FAMILY_TASK_SCOPE_STRICT_PRODUCER_BOUND_NO_QUALIFICATION"
    assert len(result["family_cards"]) == 7
    assert result["inputs"]["quality_execution_receipt"]["launch_end_hashes_closed"] is True
    assert all(card["task_eligibility"]["physical_fate"] == "UNKNOWN" for card in result["family_cards"])
    assert result["read_policy"]["materialized_label_h5_opened_by_this_worker"] is False
    assert result["read_policy"]["original_trajectory_h5_opened"] is False


@pytest.mark.skipif(not _mounted(), reason="root seven-family quality product is not mounted")
def test_completed_wrong_output_root_receipt_is_rejected(tmp_path: Path) -> None:
    bad = json.loads(RECEIPT.read_text(encoding="utf-8"))
    bad["output_root"] = str(tmp_path / "other-completed-run")
    path = tmp_path / "execution-receipt.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(MODULE.EvaluationError, match="output_root"):
        MODULE.evaluate(MANIFEST, REPORT, path, tmp_path / "result.json")


@pytest.mark.skipif(not _mounted(), reason="root seven-family quality product is not mounted")
def test_completed_other_case_receipt_is_rejected(tmp_path: Path) -> None:
    bad = json.loads(RECEIPT.read_text(encoding="utf-8"))
    bad["request"]["case_id"] = "DS02_OTHER_COMPLETED_AUDIT"
    bad_dir = tmp_path / RECEIPT.parent.name
    bad_dir.mkdir()
    path = bad_dir / "execution-receipt.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(MODULE.EvaluationError, match="another producer case"):
        MODULE.evaluate(MANIFEST, REPORT, path, tmp_path / "result.json")


@pytest.mark.skipif(not _mounted(), reason="root seven-family quality product is not mounted")
def test_strict_request_has_no_scientific_payload_inputs(tmp_path: Path) -> None:
    request = MODULE.make_request(MANIFEST, REPORT, RECEIPT, tmp_path / "request.json", PRIMARY, ROOT.parent)
    assert request["launch_allowed"] is True
    assert request["strict_receipt_contract"].startswith("completed producer")
    assert request["source_cost"]["materialized_label_h5_bytes_read"] == 0
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert all(Path(path).suffix.lower() not in {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"} for path in request["input_files"])
