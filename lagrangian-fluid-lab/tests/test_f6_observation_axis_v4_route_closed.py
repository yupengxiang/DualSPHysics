"""Regression checks for the read-only F6 v4 route closure."""

from pathlib import Path
import sys


LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "scripts"))

import f6_observation_axis_v4_route_closed_v1 as closure  # noqa: E402


def test_route_closure_receipts_and_hashes_are_self_consistent():
    card = closure.verify()
    assert card["status"] == "route_closed_no_new_hypothesis"
    assert card["qualification_credit"] == 0
    assert card["T1"] is False
    assert card["execution_controls"]["solver_invoked"] is False
    assert card["execution_controls"]["gpu_started"] is False
    assert card["execution_controls"]["registry_mutation"] == 0
    assert card["execution_controls"]["ledger_mutation"] == 0
    assert card["existing_scope_audit"]["solver_canary"]["scientific_pass_fraction"] == "7/8"
    assert card["existing_scope_audit"]["solver_canary"]["failure_retained"] is True

