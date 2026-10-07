#!/usr/bin/env python3
"""Read-only validator for the fresh193 user delivery index draft.

Only JSON metadata is loaded or hashed.  No scientific payload or PNG is
opened, copied, or hashed by this validator.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
INDEX = PACKAGE / "metadata" / "full336-user-delivery-index.json"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
EXPECTED_ACCEPTED = {"F1": 48, "F2": 48, "F3": 47, "F4": 48, "F5": 45, "F6": 48, "F7": 48}
EXPECTED_PENDING = {
    "F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T085",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: Path) -> dict:
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        fail(f"forbidden payload read: {path}")
    if not path.is_file():
        fail(f"missing JSON metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON object required: {path}")
    return value


def json_sha(path: Path) -> str:
    if path.suffix.lower() != ".json":
        fail(f"validator may hash JSON only: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ref(value: dict, role: str | None = None) -> None:
    path = Path(value["path"])
    if path.suffix.lower() != ".json":
        fail(f"source reference is not JSON metadata: {path}")
    if json_sha(path) != value.get("sha256"):
        fail(f"source JSON SHA mismatch: {path}")
    if role is not None and value.get("role") != role:
        fail(f"wrong source role for {path}")


def main() -> int:
    index = load_json(INDEX)
    assert index["schema"] == "ds02.f3.user-delivery.full336-directory-index-draft.v1"
    assert index["fresh_id"] == "fresh193"
    assert index["package_status"] == "metadata_only_user_delivery_draft_not_final_complete"

    snapshot = index["authoritative_snapshot"]
    assert snapshot["checkpoint_number"] == 326
    check_ref(snapshot["checkpoint"], "authoritative_checkpoint_326")
    check_ref(snapshot["current_index"], "authoritative_full336_index_332_plus4")
    assert snapshot["checkpoint"]["path"].endswith("ROOT_LIVE_RESUMPTION_CHECKPOINT_326.json")
    assert snapshot["current_index"]["path"].endswith("full336-current332-actual-final48-delivery-progress-index.json")

    counts = index["counts"]
    assert counts == {
        "target_independent_cases": 336,
        "accepted_independent_cases": 332,
        "pending_independent_cases": 4,
        "union_distinct_physical_cases": 336,
        "delivery_complete": False,
        "accepted_per_family": EXPECTED_ACCEPTED,
        "family_roster_counts": {family: 48 for family in EXPECTED_ACCEPTED},
        "Q_N": 0,
        "Q_E": 0,
        "new_case_credit": 0,
    }

    families = index["families"]
    if set(families) != set(EXPECTED_ACCEPTED):
        fail(f"family set mismatch: {set(families)}")
    all_ids: list[str] = []
    for family, expected in EXPECTED_ACCEPTED.items():
        item = families[family]
        assert item["accepted_count_at_checkpoint"] == expected
        assert item["pending_count_at_checkpoint"] == 48 - expected
        assert item["accepted_count_in_product"] == expected
        check_ref(item["primary_product"], "family_primary_delivery_product")
        mem = item["membership"]
        first8 = mem["frozen_first8_physical_case_ids"]
        first24 = mem["actual_first24_physical_case_ids"]
        final48 = mem["registered_final48_physical_case_ids"]
        assert len(first8) == 8 and len(first24) == 24 and len(final48) == 48
        assert len(set(first8)) == 8 and len(set(first24)) == 24 and len(set(final48)) == 48
        assert set(first8).issubset(first24)
        assert set(first24).issubset(final48)
        all_ids.extend(final48)
        contract = item["navigation_contract"]
        assert contract["open_with_ParaView"].startswith("Use the per-case")
        assert contract["animation_overview"].startswith("Use the per-case")
        assert item["role_limits"]["physical_case_id_is_authority"] is True
        assert item["role_limits"]["accepted_decision_hash_is_not_automatically_native_scope"] is True
        assert item["role_limits"]["native_typed_xmf_source_definition_source_plan_are_separate_roles"] is True
        assert item["role_limits"]["case_credit"] == 0
    assert len(all_ids) == 336 and len(set(all_ids)) == 336

    pending = index["pending_cases"]
    pending_ids = {row["physical_case_id"] for row in pending}
    assert pending_ids == EXPECTED_PENDING
    assert len(pending) == 4
    for row in pending:
        assert row["status"] == "original-render-registered-still-pending"
        assert row["registered_render_request"] is not None
        obs = row["historical_queue_observation"]
        assert obs["actual_receipt"] is None
        assert obs["controller_terminal"] is None
        assert obs["published0"] is False
        assert row["future_visual_credit"] == 0
        assert row["future_hashes"] is None
        assert obs["source_role"].startswith("historical observation")

    latest = index["latest_f5_extension"]
    assert latest["physical_case_id"] == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100"
    check_ref(latest["source_product"], "latest_f5_45_primary_bed_product")
    check_ref(latest["accepted_decision"])
    check_ref(latest["own_full801_QI"])
    check_ref(latest["render_request"])

    # The source226 product is explicitly the F2 final source in the F5 agent
    # worktree; this is a provenance check, not a cross-worktree write.
    f2_source = families["F2"]["primary_product"]
    assert f2_source["source_git_commit"] == "da36598b8c133c18cf8985fa195fdd709c0903c3"
    assert "ds-data-02-f5" in f2_source["path"]

    policy = index["membership_contract"]
    assert policy["frozen8_subset_actual24_subset_registered48"] is True
    assert "no sorting" in policy["selection_authority"]
    boundaries = index["source_boundaries"]
    assert boundaries == {
        "scientific_payload_read": False,
        "scientific_payload_hashed": False,
        "scientific_payload_copied": False,
        "PNG_read_or_hashed": False,
        "new_jobs_started": False,
        "shared_state_written": False,
        "case_credit_granted": 0,
        "model": "gpt-5.6-luna/max",
        "recursive_delegation": False,
    }

    for path in PACKAGE.rglob("*"):
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            fail(f"forbidden scientific payload in package: {path}")

    print("fresh193 full336 user delivery index PASS")
    print("accepted=332 pending=4; family rosters=7*48; delivery_complete=false")
    print("membership=explicit 8/24/48 arrays; no sorting or alias substitution")
    print("science_payload_read_or_hashed=false; PNG_read_or_hashed=false; new_jobs=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
