from __future__ import annotations

import json

from scripts.f7_pump_root_review_receipt_v2 import OUTPUT, build_receipt


def test_receipt_v2_is_no_go_and_separates_historical_execution() -> None:
    result = build_receipt()
    assert result["status"] == "root_review_only_no_go_missing_fresh_materialization"
    assert result["admission_granted"] is False
    assert result["historical_canary_separation"]["superseded_receipt_solver_invoked"] is True
    assert result["historical_canary_separation"]["current_v2_solver_invoked"] is False
    assert result["qualification_credit"] == 0
    assert all(value == 0 for value in result["protected_state_mutation"].values())


def test_receipt_v2_binds_binaries_decoder_parser_and_energy_contract() -> None:
    result = build_receipt()
    paths = {row["path"] for row in result["artifact_bindings"]}
    assert "vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64" in paths
    assert "campaigns/l1-resume/artifacts/bi4_dump" in paths
    assert "scripts/f7_pump_compute_forces_result_contract_v1.py" in paths
    assert "scripts/f7_pump_energy_consistency_contract_v1.py" in paths
    assert result["fresh_artifact_integrity"]["definition"]["exists"] is False
    assert result["fresh_artifact_integrity"]["native_integrity_receipt"]["exists"] is False


def test_committed_receipt_v2_matches_no_go_contract() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.f7.pump_recirculation.root_review_receipt.v2"
    assert result["admission_granted"] is False
    assert result["root_decision_basis"]["result_parser_bound"] is True
