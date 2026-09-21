import json
from pathlib import Path

from scripts.f4_tallwall_qualification_evaluator import evaluate, verify_static_manifest


LAB = Path(__file__).resolve().parents[1]
MANIFEST = LAB / "campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v1.json"
EQUIVALENCE = LAB / "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/canary-cell12-equivalence-v2.json"


def test_tallwall_evaluator_binds_frozen_14_plus_reused_cell12_without_claim():
    report = verify_static_manifest(MANIFEST)
    assert report["static_contract_pass"] is True
    assert report["scheduled_solver_cells"] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14]
    assert report["reused_canary_cells"] == [12]
    assert report["qualification_claim"] == "none"
    assert report["T1_numerical"] is False
    evidence = json.loads(EQUIVALENCE.read_text())
    assert evidence["mdbc_normal_array_comparison"]["all_exact"] is True
    assert evidence["matrix_cell_new_bi4_executed"] is False


def test_tallwall_evaluator_keeps_missing_runtime_products_pending():
    report = evaluate(MANIFEST)
    assert report["static_contract_pass"] is True
    assert report["matrix_complete"] is False
    assert report["T1_numerical"] is False
    assert len(report["missing"]) == 14
    assert all(row["status"] == "runtime_not_supplied" for row in report["missing"])


def test_tallwall_evaluator_rejects_relabelled_cell12_reexecution(tmp_path):
    value = json.loads(MANIFEST.read_text())
    value["cell12_reuse"]["new_candidate_bi4_executed"] = True
    altered = tmp_path / "manifest.json"
    altered.write_text(json.dumps(value))
    report = verify_static_manifest(altered)
    assert report["static_contract_pass"] is False
    assert "cell12_new_candidate_bi4_executed" in report["static_issues"]
