from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "runtime-batch8-v3/observation-evidence-v1.json"
)


def test_observation_evidence_retains_fixed_denominator() -> None:
    value = json.loads(EVIDENCE.read_text())
    assert value["schema"] == "core.f2.h2_mdbc.static_range_v5.observation_evidence.v1"
    assert value["matrix_credit"] == 0
    denominator = value["failure_denominator"]
    assert denominator["planned"] == 15
    assert denominator["attempted"] == 8
    assert denominator["scientific_failed"] == 8
    assert denominator["unattempted"] == 7
    assert denominator["failed_rows_dropped"] is False
    assert denominator["survivor_renormalization"] is False
    assert value["scope_decision"]["third_t1_family_established"] is False


def test_observation_evidence_has_no_mutation_authority() -> None:
    value = json.loads(EVIDENCE.read_text())
    controls = value["execution_controls"]
    assert controls["queue_mutation_by_collector"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert all(row["qualification_credit"] is False for row in value["failure_denominator"]["rows"])
