from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def test_first24_are_distinct_definition_only():
    audit = load("coverage-audit.json")
    rows = audit["first24_definition"]["case_ids"]
    assert len(rows) == 24 and len(set(rows)) == 24
    assert audit["stage_coverage"] == {"definition_source":24,"actual_gencase":0,"actual_initial_qa":0,"actual_native":0,"actual_typed":0,"actual_xmf":0,"actual_render":0,"visual_accepted_exact_first24":0}

def test_no_source_launch_or_scientific_payload_read():
    audit = load("coverage-audit.json")
    guards = audit["source_only_guards"]
    assert guards["launch_allowed"] is False
    assert guards["jobs_started_by_source"] is False
    assert guards["arrays_read_by_source"] is False
    assert guards["scientific_payloads_read"] == []

def test_all_requests_disabled_and_future_outputs_null():
    index = load("requests/index.json")
    assert len(index["rows"]) == 72
    assert all(row["launch_allowed"] is False for row in index["rows"])
    for path in (ROOT / "requests").glob("*.request.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        assert d["launch_allowed"] is False and d["disabled"] is True
        assert d["source_only"] is True
        assert d["production_approval"] is False
        assert d["precision_status"] == "not_accepted"
        assert d["q_n_status"] == "not_granted"
