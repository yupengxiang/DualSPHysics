from pathlib import Path
import json

PKG = Path(__file__).resolve().parents[1]

def test_wait_report_has_no_eligible_render():
    data=json.loads((PKG/"metadata/f3-registered-render-wait-audit.json").read_text())
    assert data["family"] == "F3"
    assert data["eligible_terminal_completed0_count"] == 0
    assert data["case_credit_granted"] is False
    assert all(c["terminal_receipt_path"] is None for c in data["candidates"])

def test_every_candidate_has_pid_tick_match():
    data=json.loads((PKG/"metadata/f3-registered-render-wait-audit.json").read_text())
    assert data["candidate_count"] == 12
    assert all(c["controller_identity"]["ticks_match"] for c in data["candidates"])
