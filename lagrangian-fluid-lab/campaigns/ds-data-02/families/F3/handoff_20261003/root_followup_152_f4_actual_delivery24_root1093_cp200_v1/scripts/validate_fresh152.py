#!/usr/bin/env python3
"""Metadata-only validator for fresh152; never opens scientific payloads or images."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "metadata/f4-actual-delivery24-root1093-cp200.json"
META = json.loads(META_PATH.read_text())

assert META["schema"] == "ds02.f3.fresh152.f4-actual-delivery24-root1093-cp200.v1"
assert META["fresh_id"] == "fresh152"
assert META["claim_boundary"]["identity_key"] == "physical_case_id"
assert META["claim_boundary"]["lexical_or_directory_sort_used"] is False
assert META["claim_boundary"]["source_plan_exact24_used_as_delivery_order"] is False
assert META["claim_boundary"]["historical_candidate_used_as_actual_evidence"] is False
assert META["claim_boundary"]["new_case_credit"] == 0
assert META["claim_boundary"]["global_count_or_ledger_write"] is False
for key in (
    "scientific_arrays_read",
    "scientific_payloads_hashed",
    "BI4_H5_CSV_DAT_VTK_opened_or_hashed",
    "PNG_or_render_payloads_read",
    "scientific_jobs_started",
    "shared_registry_or_ledger_written",
    "new_case_credit_written",
    "recursive_delegation",
):
    assert META["payload_guards"][key] is False, (key, META["payload_guards"][key])


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Every source is a JSON metadata record.  The validator deliberately does not
# follow paths recorded inside those records, so no BI4/H5/CSV/DAT/VTK/PNG is read.
for source in META["source_references"]:
    path = Path(source["path"])
    assert path.suffix == ".json", path
    assert path.exists(), path
    assert sha(path) == source["sha256"], (path, source["sha256"], sha(path))

cp_path = Path(META["authorities"]["checkpoint200"]["path"])
checkpoint = json.loads(cp_path.read_text())
assert checkpoint["checkpoint"] == 200
accepted = []
for accepted_index, source_path in enumerate(checkpoint["accepted_decisions"], 1):
    decision_path = Path(source_path)
    decision = json.loads(decision_path.read_text())
    if decision.get("family_id") == "F4":
        accepted.append((accepted_index, decision_path, decision))
assert len(accepted) == 48
accepted_ids = [decision["physical_case_id"] for _, _, decision in accepted]
assert len(set(accepted_ids)) == 48
accepted_by_id = {decision["physical_case_id"]: (index, path, decision) for index, path, decision in accepted}

frozen = META["preserved_sets"]["frozen_root1093_actual_first8"]["order"]
historical = META["preserved_sets"]["historical_candidate_first8"]["order"]
exact = META["preserved_sets"]["current_exact24_source_plan"]["order"]
delivery = [row["physical_case_id"] for row in META["actual_delivery24"]["rows_source_order"]]
assert len(frozen) == len(set(frozen)) == 8
assert len(historical) == len(set(historical)) == 8
assert len(exact) == len(set(exact)) == 24
assert len(delivery) == len(set(delivery)) == 24
assert set(frozen) <= set(delivery) <= set(accepted_ids)
assert delivery[:8] == frozen
assert META["actual_delivery24"]["count"] == 24
assert META["actual_delivery24"]["all_rows_actual_frames_1201"] is True
assert META["actual_delivery24"]["all_rows_visual_status_approved"] is True
assert META["actual_delivery24"]["all_rows_count_increment_one"] is True

append_indices = []
for expected_index, row in enumerate(META["actual_delivery24"]["rows_source_order"], 1):
    assert row["delivery_index"] == expected_index
    physical_id = row["physical_case_id"]
    assert row["case_id"] == row["observed"]["case_id"]
    assert row["observed"]["family_id"] == "F4"
    assert row["observed"]["physical_case_id"] == physical_id
    assert row["observed"]["status"] in ("visual-approved-by-root", "visual-approved-by-delegated-agent")
    assert row["observed"]["frames_observed"] == 1201
    assert row["observed"]["count_transition"]["increment"] == 1
    assert row["decision"]["metadata_only"] is True
    decision_path = Path(row["decision"]["path"])
    assert decision_path.exists() and decision_path.suffix == ".json"
    assert sha(decision_path) == row["decision"]["sha256"]
    decision = json.loads(decision_path.read_text())
    assert decision.get("family_id") == "F4"
    assert decision.get("physical_case_id") == physical_id
    actual_frames = decision.get("actual_frames", decision.get("frames"))
    assert actual_frames == 1201, (physical_id, actual_frames)
    increment = decision.get("independent_physical_case_count_increment", decision.get("independent_case_increment"))
    assert increment == 1, (physical_id, increment)
    assert physical_id in accepted_by_id
    if expected_index <= 8:
        assert row["selection_origin"] == "root1093_frozen_actual_first8"
    else:
        assert row["selection_origin"] == "checkpoint200_accepted_decisions_append"
        append_indices.append(row["checkpoint200_accepted_index"])
        accepted_index, accepted_path, _ = accepted_by_id[physical_id]
        assert row["checkpoint200_accepted_index"] == accepted_index
        assert accepted_path == decision_path
assert append_indices == sorted(append_indices)
assert len(append_indices) == 16

# Re-read the prior authority and prove fresh152 preserved its frozen order.
fresh151_path = Path(META["fresh151_evidence_preserved"]["source_path"])
fresh151 = json.loads(fresh151_path.read_text())
assert sha(fresh151_path) == META["fresh151_evidence_preserved"]["source_sha256"]
prior_frozen = [row["physical_case_id"] for row in fresh151["frozen_root1093"]["rows_source_order"]]
assert prior_frozen == frozen

comparisons = META["set_comparisons"]
assert comparisons["frozen_actual_first8_vs_actual_delivery24"]["left_subset_right"] is True
assert comparisons["actual_delivery24_vs_checkpoint200_accepted48"]["left_subset_right"] is True
assert comparisons["actual_delivery24_vs_current_exact24_source_plan"]["intersection_count"] == 19
assert len(comparisons["actual_delivery24_vs_current_exact24_source_plan"]["left_only_in_left_order"]) == 5
assert len(comparisons["actual_delivery24_vs_current_exact24_source_plan"]["right_only_in_right_order"]) == 5
assert comparisons["historical_candidate_first8_vs_actual_delivery24"]["left_subset_right"] is False
assert META["f3_visual_priority"]["new_unaccepted_eligible_case_found"] is False

print("fresh152 metadata contract: PASS")
print("F4 delivery24: frozen Root1093 first8 + checkpoint-200 accepted append16")
print("F4 accepted roster: 48; exact24 overlap: 19; historical candidate retained: 8")
