import json
from pathlib import Path

from scripts.f2_static_full_cup_boundary_repair_h2_proposal_v1 import (
    DENOMINATOR,
    HYPOTHESIS_ID,
    build_contract,
    verify,
    write,
)


def test_h2_proposal_is_closed_and_zero_credit():
    payload = build_contract()
    assert payload["repair_id"] == HYPOTHESIS_ID
    assert payload["status"] == "proposal_only_root_review_required"
    assert payload["qualification_claim"].startswith("none;")
    assert payload["matrix_credit"] == 0
    assert payload["fixed_failure_denominator"]["planned"] == DENOMINATOR
    assert payload["fixed_failure_denominator"]["survivor_renormalization"] is False
    assert payload["authorization"]["solver"] is False
    assert payload["authorization"]["registry_mutation"] == 0
    assert payload["hypothesis"]["fresh_identity"]["old_definition_reused"] is False
    assert payload["static_fit_screen"]["all_continuous_fit"] is True
    assert payload["static_fit_screen"]["mass_and_native_sampling_pending"] is True


def test_h2_proposal_verify_round_trip(tmp_path: Path):
    path = tmp_path / "proposal.json"
    write(path, build_contract())
    payload = json.loads(path.read_text())
    result = verify(path)
    assert result["ok"] is True
    assert payload["evidence"]["h1"]["sha256"]
