import json
from pathlib import Path

from scripts.r3_g2_transport_spec_audit import audit_examples, audit_release, build_report


ROOT = Path(__file__).parents[1]


def test_protocol_examples_are_valid_but_release_has_no_destination_links():
    examples = audit_examples()
    cases = audit_release()
    assert len(examples) == 2
    assert all(row["valid"] for row in examples)
    assert len(cases) == 13
    assert sum(row["destination_spec_present"] for row in cases) == 0
    assert sum(row["boundary_sidecar_present"] for row in cases) == 12
    assert sum(row["t2_contract_ready"] for row in cases) == 0


def test_transport_spec_audit_report_preserves_candidate_only_gate():
    report = build_report()
    assert report["examples"]["all_valid"]
    assert report["release"]["destination_spec_linked_count"] == 0
    assert report["release"]["t2_contract_ready_count"] == 0
    assert report["formal_ready"] is False
    assert "destination specification" in report["open_blockers"][0]


def test_checked_in_transport_spec_report_matches_recomputed_state():
    checked_in = json.loads((ROOT / "campaigns/v0.1-candidate/r3-g2-transport-spec-audit.json").read_text())
    current = build_report()
    assert checked_in["examples"]["valid_count"] == current["examples"]["valid_count"]
    assert checked_in["release"]["case_count"] == current["release"]["case_count"]
    assert checked_in["release"]["destination_spec_linked_count"] == current["release"]["destination_spec_linked_count"]
    assert checked_in["release"]["t2_contract_ready_count"] == current["release"]["t2_contract_ready_count"]
