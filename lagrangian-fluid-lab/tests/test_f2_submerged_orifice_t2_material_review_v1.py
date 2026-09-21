from __future__ import annotations

import json

from pathlib import Path

from scripts.f2_submerged_orifice_t2_material_review_v1 import verify


# The original v1 receipt remains as historical evidence.  The current
# verifier test targets the v2 copy whose bindings include the post-run hash
# closure of the F2 preflight.
OUTPUT = Path(__file__).resolve().parents[1] / (
    "campaigns/core-v1/material/evidence/"
    "f2-submerged-orifice-v4-t2-material-review-20260921-v2.json"
)


def test_f2_v4_material_review_keeps_t2_closed_and_zero_credit():
    receipt = verify(OUTPUT)
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["matrix_credit"] == 0
    boundary = receipt["t2_boundary"]
    assert boundary["T2_macro"] is False
    assert boundary["T2_path"] is False
    assert boundary["future_cpu_native_preflight_is_t2_eligible"] is False
    assert boundary["hard_pass_would_still_be_t2_credit"] == 0


def test_f2_v4_material_review_preserves_parent_15_row_denominator():
    receipt = json.loads(OUTPUT.read_text(encoding="utf-8"))
    parent = receipt["parent_scope"]
    assert parent["matrix_rows"] == 15
    assert parent["matrix_all_not_started"] is True
    assert parent["matrix_denominator"] == {
        "credit": 0,
        "event_censored": 0,
        "executed": 0,
        "failed": 0,
        "passed": 0,
        "planned": 15,
        "unattempted": 15,
    }
    assert parent["failure_denominator"] == {
        "credit": 0,
        "executed": 0,
        "failed": 0,
        "passed": 0,
        "planned": 15,
        "unattempted": 15,
    }


def test_f2_v4_material_review_records_hard_negative_and_stale_snapshot():
    receipt = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert receipt["root_review_snapshot"]["historical_snapshot_is_stale"] is True
    assert receipt["current_materialization"]["current_output_root_materialized"] is True
    negative = receipt["v4_preflight"]
    assert negative["preflight_pass"] is False
    assert negative["zero_boundnor"] == 29484
    assert negative["zero_normal_size"] == 29484
    assert negative["mass_pass"] is True
    assert negative["ids_pass"] is True
    assert negative["endpoints_pass"] is True
    controls = receipt["execution_controls"]
    assert controls["review_opened_solver"] is False
    assert controls["review_opened_gpu"] is False
    assert controls["review_mutated_queue"] == 0
    assert controls["review_mutated_ledger"] == 0
    assert controls["review_mutated_registry"] == 0
    assert controls["scientific_denominator_changed"] is False
