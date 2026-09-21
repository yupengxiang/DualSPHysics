from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "campaigns/core-v1/material/evidence"
DECISION = EVIDENCE / "f3-f4-t2-cpu-only-next-step-decision-20260920.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_cpu_only_decision_preserves_negative_t2_state_and_registered_gates() -> None:
    decision = _load(DECISION)
    assert decision["schema"] == "core.material.t2.cpu_only_next_step_decision.v1"
    assert decision["status"] == "blocked_for_qualification"
    assert decision["qualification_claim"] == "none"
    assert decision["t2_status"] == "not_established"
    assert decision["t2_qualified"] is False
    assert decision["T2_macro"] is False
    assert decision["T2_path"] is False
    assert decision["registered_gates"]["unknown_fraction_per_source_max"] == 0.01
    assert decision["registered_gates"]["f3_cdf_sup_abs_difference_max"] == 0.02
    assert decision["safe_next_step"]["safe"] is True
    assert decision["safe_next_step"]["eligible_for_t2"] is False
    assert decision["safe_next_step"]["requires_new_cfd"] is False
    assert decision["safe_next_step"]["will_grant_t2"] is False

    for item in decision["input_evidence"]:
        path = ROOT / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]

    f3 = _load(EVIDENCE / "f3-adapter-rows29-31-terminal-negative-result-20260920.json")
    assert f3["qualification_claim"] == "none"
    assert f3["T2_macro"] is False
    assert f3["T2_path"] is False
    assert f3["rows_evidence"]["29"]["summary"]["source_rows"]["0"]["final_unknown_fraction"] > 0.01
    assert f3["rows_evidence"]["31"]["summary"]["source_rows"]["0"]["final_unknown_fraction"] > 0.01
    assert f3["rows_evidence"]["31"]["summary"]["source_rows"]["1"]["final_unknown_fraction"] > 0.01

    comparison = _load(EVIDENCE / "f3-adapter-rows29-31-terminal-comparison-20260920.json")
    cdf_bounds = [
        values["difference"][key]
        for values in comparison["source_comparison"].values()
        for key in (
            "first_passage_cdf_sup_abs_difference_bound",
            "return_cdf_sup_abs_difference_bound",
            "residence_cdf_sup_abs_difference_bound",
        )
    ]
    assert max(cdf_bounds) > 0.02

    f4 = _load(EVIDENCE / "f4-material-negative-evidence-audit-20260920.json")
    assert f4["qualification_claim"] == "none"
    assert f4["t2_status"] == "not_qualified"
    assert f4["execution_constraints"]["new_job_submitted"] is False
    assert all(canary.get("unknown_gate_pass") is False for canary in f4["canaries"][:3])
    assert f4["canaries"][3]["scientific_gate_pass"] is False
    assert all(
        canary.get("event_window_complete", False) is False
        or canary["event_window_status"] == "right_censored_or_unresolved"
        for canary in f4["canaries"]
    )
