import json
from itertools import combinations

import pytest

from scripts import f3_ref0081818_prepare as preparation
from scripts import f3_ref0081818_score as score


def test_new_gate_uses_all_three_resolution_pairs_for_endpoints():
    expected = {
        ("R0081818", "R075-0075"),
        ("R0081818", "R075-006"),
        ("R075-0075", "R075-006"),
    }
    assert set(combinations(score.ENDPOINT_LADDER, 2)) == expected


def test_score_requires_new_owner_authorization_before_reading_solver_sources():
    if score.AUTHORIZATION.exists():
        pytest.skip("authorization is intentionally absent in the preparation-only state")
    with pytest.raises(PermissionError, match="owner authorization"):
        score.score()


def test_prepared_records_are_not_a_scored_gate():
    manifest = json.loads(score.MANIFEST.read_text())
    summary = json.loads(score.SUMMARY.read_text())
    records = score._prepared_records(manifest, summary)
    assert set(records) == {cell[0] for cell in preparation.CELLS}
    assert all(record["launch_allowed"] is False for record in records.values())
    assert all(record["qualified"] is False for record in records.values())
