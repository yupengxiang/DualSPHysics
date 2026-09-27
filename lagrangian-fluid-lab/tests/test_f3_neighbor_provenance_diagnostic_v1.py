"""Synthetic-only tests for the F3 two-hop provenance/capacity diagnostic."""

import json

import pytest

from scripts import f3_neighbor_provenance_diagnostic_v1 as diagnostic


def test_default_cap_reproduces_required_row_fail_closed_and_missing_source():
    graph = diagnostic.synthetic_f3_adjacency()
    result = diagnostic.diagnose_two_hop_provenance(graph, cap=64, centers=(0,))

    assert result["status"] == "fail_closed_required_row_truncated"
    assert result["failure_reason"] == (
        "neighbor provenance is truncated for a required two-hop row")
    assert result["required_truncated_rows"] == [1]
    assert 69 in result["non_required_truncated_rows"]
    assert result["accepted_for_requested_centers"] is False
    assert result["missing_required_sources"] == [{"center": 0, "sources": [65]}]


def test_raised_cap_has_complete_required_and_global_provenance():
    graph = diagnostic.synthetic_f3_adjacency()
    result = diagnostic.diagnose_two_hop_provenance(graph, cap=65, centers=(0,))

    assert result["status"] == "complete"
    assert result["accepted_for_requested_centers"] is True
    assert result["provenance_complete_for_requested_centers"] is True
    assert result["global_provenance_complete"] is True
    assert result["truncated_rows"] == []
    assert result["missing_required_sources"] == [{"center": 0, "sources": []}]


def test_non_required_truncation_is_retained_but_explicit():
    graph = diagnostic.synthetic_f3_adjacency()
    result = diagnostic.diagnose_two_hop_provenance(graph, cap=64, centers=(66,))

    assert result["status"] == "complete_for_requested_centers_non_required_rows_truncated"
    assert result["accepted_for_requested_centers"] is True
    assert result["provenance_complete_for_requested_centers"] is True
    assert result["global_provenance_complete"] is False
    assert result["required_truncated_rows"] == []
    assert result["non_required_truncated_rows"] == [1, 69]


@pytest.mark.parametrize("cap", (0, -1, True, 1.5, "64"))
def test_invalid_cap_is_structured_fail_closed(cap):
    result = diagnostic.diagnose_two_hop_provenance(
        diagnostic.synthetic_f3_adjacency(), cap=cap, centers=(0,))

    assert result["status"] == "fail_closed_invalid_cap"
    assert result["failure_code"] == "invalid_cap"
    assert result["fail_closed"] is True
    assert result["accepted_for_requested_centers"] is False


def test_missing_and_incomplete_provenance_fail_closed():
    graph = diagnostic.synthetic_f3_adjacency()
    missing = diagnostic.diagnose_two_hop_provenance(
        graph, cap=65, centers=(0,), provenance=None)
    assert missing["status"] == "fail_closed_missing_provenance"
    assert missing["failure_code"] == "missing_provenance"
    assert missing["fail_closed"] is True

    table = diagnostic.build_capped_neighbor_table(graph, 65)
    incomplete = diagnostic.build_synthetic_provenance(graph, table, (0,)).to_dict()
    del incomplete["required_two_hop_sources"]
    result = diagnostic.diagnose_two_hop_provenance(
        graph, cap=65, centers=(0,), provenance=incomplete)
    assert result["status"] == "fail_closed_incomplete_provenance"
    assert result["failure_code"] == "incomplete_provenance"
    assert result["fail_closed"] is True


def test_low_level_invalid_cap_raises_instead_of_constructing_unsafe_table():
    with pytest.raises(ValueError, match="positive integer"):
        diagnostic.build_capped_neighbor_table(diagnostic.synthetic_f3_adjacency(), 0)


def test_run_diagnostic_has_required_flags_and_canonical_json():
    payload = diagnostic.run_diagnostic()
    for key, expected in {
        "diagnostic_only": True,
        "synthetic_only": True,
        "formal_training": False,
        "T1": False,
        "native_integrity": False,
        "gate": False,
        "credit": 0,
    }.items():
        assert payload[key] is expected
    assert payload["policy"]["cap_increase_is_formal_strategy"] is False
    assert payload["summary"]["negative_cases_fail_closed"] is True

    encoded = diagnostic.canonical_json(payload)
    assert encoded == diagnostic.canonical_json(json.loads(encoded))
    assert encoded == json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)


def test_cli_emits_the_same_canonical_suite(capsys):
    assert diagnostic.main([]) == 0
    output = capsys.readouterr().out.strip()
    payload = json.loads(output)
    assert payload["schema"] == diagnostic.SCHEMA
    assert output == diagnostic.canonical_json(payload)
