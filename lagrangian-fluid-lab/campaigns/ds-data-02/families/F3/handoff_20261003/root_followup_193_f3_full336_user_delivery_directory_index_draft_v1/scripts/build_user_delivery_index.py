#!/usr/bin/env python3
"""Build a metadata-only user delivery index from the frozen main records.

This builder reads JSON metadata only.  It preserves the explicit membership
order supplied by each family product, records the current 332/336 state, and
keeps the four pending physical cases as observations rather than promoting
them to accepted products.  It never opens or hashes scientific payloads or
PNG files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
)
F5_WORKTREE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003"
)
CHECKPOINT = INTEGRATION / "ROOT_LIVE_RESUMPTION_CHECKPOINT_326.json"
CURRENT_INDEX = INTEGRATION / (
    "root_stage1_F5_actual45_primary801_fullbed_extend44_actual1189_personal43PNG_"
    "distinct_native_CAN_XMF_SourceDef_scope_1439/"
    "full336-current332-actual-final48-delivery-progress-index.json"
)
ROOT1261 = INTEGRATION / (
    "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_primary_"
    "XMF_native_scope_observation_1261"
)
FAMILY_SOURCES = {
    "F1": INTEGRATION / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_primary_"
        "XMF_native_scope_observation_1261/F1-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F4": INTEGRATION / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_primary_"
        "XMF_native_scope_observation_1261/F4-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F7": INTEGRATION / (
        "root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_primary_"
        "XMF_native_scope_observation_1261/F7-ACTUAL_FINAL48_DELIVERY_8_24_48.json"
    ),
    "F6": INTEGRATION / (
        "root_stage1_source190_F6_final48_actual_particle_rigid_primary_baseline_"
        "native_typed_XMF_receipt_recovery_condition_absence_threefluid_limits_1353/"
        "F6-FINAL48-COMPLETE-PARTICLE-RIGID-ACTUAL-PRIMARY-DELIVERY.json"
    ),
    "F3": INTEGRATION / (
        "root_stage1_source190_F3_actual47_primary836_true_shared_initial_QA_XML_"
        "BI4_producer_join_legacy_native_unknown_pub_H5_absences_preserved_1433/"
        "F3-FINAL48-ACTUAL47ACCEPTED-ONEPENDING-PRIMARY-DELIVERY.json"
    ),
    "F5": INTEGRATION / (
        "root_stage1_F5_actual45_primary801_fullbed_extend44_actual1189_personal43PNG_"
        "distinct_native_CAN_XMF_SourceDef_scope_1439/"
        "F5-FINAL48-ACTUAL45ACCEPTED-THREEPENDING-PRIMARY-BED-DELIVERY.json"
    ),
    "F2": F5_WORKTREE / (
        "root_followup_226_f5_assigned_f2_final48_actual_primary_delivery_v1/"
        "metadata/f2-final48-products.json"
    ),
}
FAMILY_COMMITS = {
    "F1": "8ee21b13e32e86e9b0474eead8edcb659a72acba",
    "F4": "8ee21b13e32e86e9b0474eead8edcb659a72acba",
    "F7": "8ee21b13e32e86e9b0474eead8edcb659a72acba",
    "F2": "da36598b8c133c18cf8985fa195fdd709c0903c3",
}

PENDING_FIELDS = {
    "F3": "35 contact sheets / 836 frames / 179208 particles; no receipt or publish",
    "F5": "34 contact sheets / 801 frames / 194427 particles; no receipt or publish",
}


def load_json(path: Path) -> dict:
    if path.suffix.lower() != ".json":
        raise RuntimeError(f"metadata JSON required: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    if path.suffix.lower() != ".json":
        raise RuntimeError(f"builder may hash JSON only: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path, role: str, **extra: object) -> dict:
    result = {"path": str(path), "sha256": sha256_file(path), "role": role}
    result.update(extra)
    return result


def membership(product: dict) -> dict:
    source = product.get("membership") or {}
    registered = source.get("registered_final48_physical_case_ids", source.get("final48_physical_case_ids"))
    if all(k in source for k in ("frozen_first8_physical_case_ids", "actual_first24_physical_case_ids")) and registered is not None:
        return {
            "frozen_first8_physical_case_ids": list(source["frozen_first8_physical_case_ids"]),
            "actual_first24_physical_case_ids": list(source["actual_first24_physical_case_ids"]),
            "registered_final48_physical_case_ids": list(registered),
            "order_source": "explicit product membership arrays; no lexical or directory selection",
        }
    return {
        "frozen_first8_physical_case_ids": list(product["first8_physical_case_ids"]),
        "actual_first24_physical_case_ids": list(product["first24_physical_case_ids"]),
        "registered_final48_physical_case_ids": list(product["final48_physical_case_ids"]),
        "order_source": "explicit product membership arrays; no lexical or directory selection",
    }


def accepted_rows(product: dict) -> list[dict]:
    for key in (
        "cases",
        "rows",
        "accepted47_actual_primary_rows",
        "accepted45_actual_primary_bed_rows",
        "products",
    ):
        if isinstance(product.get(key), list):
            return product[key]
    return []


def family_access(family: str, product: dict) -> dict:
    if family in {"F1", "F4", "F7"}:
        fields = [
            "accepted_visual_decision",
            "primary_paraview_xmf",
            "primary_xmf_manifest",
            "primary_full_render_reports",
            "contact_sheets",
            "key_frames",
            "actual_native_condition_observation",
        ]
    elif family == "F2":
        fields = [
            "accepted_visual_decision",
            "actual_native_receipt",
            "primary_XMF_XML",
            "primary_XMF_manifest",
            "primary_render_report",
            "main_contact_refs",
            "main_published_navigation_keys",
            "actual_native_condition_field",
        ]
    elif family == "F3":
        fields = [
            "accepted_visual_decision",
            "own_completed_full836_QI",
            "primary_metadata",
            "ParaView_open_XMF",
            "contacts35_actual_SHA_verified",
            "navigation_keys9_actual_SHA_verified",
            "actual_native_runtime_status",
            "native_fields_not_backfilled",
        ]
    elif family == "F5":
        fields = [
            "accepted_visual_decision",
            "own_full801_QI",
            "primary_metadata",
            "ParaView_open_XMF",
            "contacts34_actual_SHA_verified",
            "navigation9_actual_SHA_verified",
            "actual_native_XMF_plan_field_namespaces",
            "legacy_atomic_publish_receipt_absent",
        ]
    else:
        fields = [
            "accepted_visual_metadata",
            "accepted_visual_decision_summary",
            "scope_roles",
            "rigid_motion_join",
            "progress_index_row",
        ]
    return {
        "accepted_row_count": len(accepted_rows(product)),
        "per_case_metadata_fields_for_navigation": fields,
        "open_with_ParaView": "Use the per-case primary XMF/XML and manifest ref in the accepted row; never substitute a case alias or another row.",
        "animation_overview": "Use the per-case primary render report and its published output refs; do not infer a completed animation from a request or readiness row.",
        "personal_review": "Accepted decision and published navigation refs describe review provenance; they do not assert that the current reader personally viewed the PNGs.",
    }


def pending_case(row: dict) -> dict:
    obs = row.get("current_controller_observation", {}) or {}
    live = obs.get("live_observation", {}) or {}
    wrapper = row.get("actual_wrapper_contract_and_live_observation", {}) or {}
    wrapper_live = wrapper.get("live_observation", {}) or {}
    latest_request = row.get("latest_registered_render_request")
    return {
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "case_id": row.get("case_id"),
        "status": row.get("status"),
        "expected_frames": row.get("expected_frames"),
        "expected_particles": row.get("expected_particles"),
        "expected_contact_sheets": row.get("expected_contact_sheets"),
        "registered_render_request": latest_request,
        "actual_manifest": wrapper.get("actual_manifest"),
        "historical_queue_observation": {
            "at_utc": live.get("at_utc") or wrapper_live.get("at_utc"),
            "pid": live.get("pid") or wrapper_live.get("pid"),
            "start_ticks": live.get("recorded_start_ticks") or wrapper_live.get("recorded_start_ticks"),
            "proc_state": live.get("proc_state") or wrapper_live.get("proc_state"),
            "same_pid_startticks_live": obs.get("same_actual_PID_startticks_live", wrapper_live.get("same_pid_startticks_live")),
            "actual_receipt": obs.get("actual_receipt"),
            "actual_worker_status": obs.get("actual_worker_status"),
            "controller_terminal": obs.get("controller_terminal"),
            "published0": obs.get("published0"),
            "wait_is_not_restart": obs.get("wait_is_not_restart"),
            "source_role": "historical observation from the frozen index; not a new live probe by this package",
        },
        "future_visual_credit": 0,
        "future_hashes": None,
    }


def main() -> int:
    checkpoint = load_json(CHECKPOINT)
    current = load_json(CURRENT_INDEX)
    families: dict[str, dict] = {}
    expected_accepted = checkpoint["accepted_per_family"]

    for family, path in FAMILY_SOURCES.items():
        product = load_json(path)
        mem = membership(product)
        assert len(mem["frozen_first8_physical_case_ids"]) == 8
        assert len(mem["actual_first24_physical_case_ids"]) == 24
        assert len(mem["registered_final48_physical_case_ids"]) == 48
        assert set(mem["frozen_first8_physical_case_ids"]).issubset(mem["actual_first24_physical_case_ids"])
        assert set(mem["actual_first24_physical_case_ids"]).issubset(mem["registered_final48_physical_case_ids"])
        assert len(set(mem["registered_final48_physical_case_ids"])) == 48
        rows = accepted_rows(product)
        accepted = len(rows)
        if family == "F2":
            source_status = "48 accepted; source226 primary package is in the F5 worktree"
        elif family == "F3":
            source_status = "47 accepted primary rows; original1101 AY0390 pending"
        elif family == "F5":
            source_status = "45 accepted primary/bed rows; three pending rows"
        else:
            source_status = f"{accepted} accepted primary rows"
        families[family] = {
            "family_id": family,
            "accepted_count_in_product": accepted,
            "accepted_count_at_checkpoint": expected_accepted[family],
            "pending_count_at_checkpoint": 48 - expected_accepted[family],
            "status": source_status,
            "primary_product": ref(path, "family_primary_delivery_product", source_git_commit=FAMILY_COMMITS.get(family)),
            "membership": mem,
            "navigation_contract": family_access(family, product),
            "role_limits": {
                "physical_case_id_is_authority": True,
                "accepted_decision_hash_is_not_automatically_native_scope": True,
                "native_typed_xmf_source_definition_source_plan_are_separate_roles": True,
                "numerical_precision": "visual screen only; not accepted",
                "Q_N": 0,
                "Q_E": 0,
                "case_credit": 0,
            },
        }

    pending = [pending_case(row) for row in current["cases"] if row.get("status") == "original-render-registered-still-pending"]
    pending.sort(key=lambda row: (row["family_id"], row["physical_case_id"]))
    assert len(pending) == 4
    active_reservations = []
    for reservation in checkpoint.get("active_reservations", []):
        active_reservations.append({
            "id": reservation.get("id"),
            "kind": reservation.get("kind"),
            "cpu_task_kind": reservation.get("cpu_task_kind"),
            "cpu_threads": reservation.get("cpu_threads"),
            "launcher_pid": reservation.get("launcher_pid"),
            "reserved_at_utc": reservation.get("reserved_at_utc"),
            "new_storage_bytes": reservation.get("new_storage_bytes"),
            "source_role": "checkpoint reservation snapshot; not a new live probe and not a restart instruction",
        })

    f5_latest = next(row for row in current["cases"] if row.get("physical_case_id") == "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100")
    delivery = {
        "schema": "ds02.f3.user-delivery.full336-directory-index-draft.v1",
        "fresh_id": "fresh193",
        "package_status": "metadata_only_user_delivery_draft_not_final_complete",
        "generated_at_utc": checkpoint["at_utc"],
        "authoritative_snapshot": {
            "checkpoint": ref(CHECKPOINT, "authoritative_checkpoint_326"),
            "current_index": ref(CURRENT_INDEX, "authoritative_full336_index_332_plus4"),
            "checkpoint_number": checkpoint["checkpoint"],
            "at_utc": checkpoint["at_utc"],
        },
        "counts": {
            "target_independent_cases": 336,
            "accepted_independent_cases": checkpoint["stage1_visual_accepted_complete_independent_cases"],
            "pending_independent_cases": current["registered_pending_independent_physical_cases"],
            "union_distinct_physical_cases": current["union_distinct_physical_case_ids"],
            "delivery_complete": current["delivery_complete"],
            "accepted_per_family": checkpoint["accepted_per_family"],
            "family_roster_counts": current["per_family_union_counts"],
            "Q_N": 0,
            "Q_E": 0,
            "new_case_credit": 0,
        },
        "membership_contract": {
            "selection_authority": "Each family product's explicit frozen_first8, actual_first24, registered_final48 arrays; no sorting, directory order, alias substitution, or resolution replica counting.",
            "frozen8_subset_actual24_subset_registered48": True,
            "first8_use": "Use only the eight IDs in the family membership array for the frozen first cohort.",
            "first24_use": "Use only the ordered 24 IDs in the family membership array for the actual first24 cohort.",
            "final48_use": "Use the 48 registered physical IDs as the family roster; require an accepted decision and own primary evidence before calling a member accepted.",
            "physical_identity": "Deduplicate by physical_case_id, preserving case_id aliases and native/typed/XMF/source namespaces separately.",
        },
        "families": families,
        "pending_cases": pending,
        "latest_f5_extension": {
            "source_product": ref(
                INTEGRATION / (
                    "root_stage1_F5_actual45_primary801_fullbed_extend44_actual1189_personal43PNG_"
                    "distinct_native_CAN_XMF_SourceDef_scope_1439/F5-FINAL48-ACTUAL45ACCEPTED-THREEPENDING-PRIMARY-BED-DELIVERY.json"
                ),
                "latest_f5_45_primary_bed_product",
            ),
            "physical_case_id": f5_latest["physical_case_id"],
            "accepted_decision": f5_latest.get("accepted_decision"),
            "own_full801_QI": f5_latest.get("actual_full801_QI") or f5_latest.get("actual_completed0_published_QI"),
            "render_request": f5_latest.get("latest_registered_render_request"),
            "personal_visual_status": f5_latest.get("personal_visual_status"),
            "roles_are_not_backfilled_from_equal_hashes": True,
        },
        "four_remaining_physical_cases": pending,
        "active_reservations_snapshot": active_reservations,
        "family_limitations": {
            "unknown_particle_loss": "Per-case omissions and causes remain exactly as reported by the family primary products; no cross-family or neighbor-case counts are substituted.",
            "runtime_unknown": "Original runtime/returncode absences and recovery evidence remain role-specific; an artifact audit or readiness record is not rewritten as the original runner exit.",
            "legacy_atomic_publish_absence": "Missing legacy publication receipts remain missing; a request or planning record is not promoted to a receipt.",
            "precision": "Visual inspection passed where accepted; numerical precision, strict containment, sub-DP depth, run-up magnitude, and production acceptance are not certified.",
            "labels": "Pending, readiness, source-plan, and historical aliases retain their original labels and are not promoted to accepted products.",
            "F6": "Full-time rigid-state product is metadata-bound; baseline Part/time verification limitations and mass/continuum semantics remain explicit.",
            "F3": "47 accepted with original154 typed runtime unknown/recovery role preserved; AY0390 remains pending.",
            "F5": "Latest primary product is 45 accepted with three pending; M110/T100 extension is accepted with native canonical, typed legacy, XMF/SourceDef roles separate.",
            "F2": "The 48-row primary product is fresh226 in the F5 worktree; older 42/6 and 33/15 partial products are historical, not the final source.",
        },
        "para_view_user_path": {
            "case_selection": "Select an accepted physical_case_id from families.<family>.membership and then resolve that row in the referenced primary product.",
            "xmf": "Open that row's primary_XMF_XML/ParaView_open_XMF and primary_XMF_manifest in ParaView; do not infer a path from a case alias or another row.",
            "animation": "Use the same row's primary_render_report and render receipt/publication refs for the full animation; a request, readiness row, or private staged output is insufficient.",
            "navigation": "Use the row's published contact/key refs for overview/navigation. Their presence documents product provenance; it does not add personal visual credit by this package.",
            "source_roles": "Keep native canonical condition, typed legacy scope, XMF condition/physical plan, SourceDef, and source-plan JSON in their named namespaces.",
            "future_pending": "The four pending rows expose expected frame/particle counts and historical queue observations only; future output hashes and visual credit remain null/zero.",
        },
        "source_boundaries": {
            "scientific_payload_read": False,
            "scientific_payload_hashed": False,
            "scientific_payload_copied": False,
            "PNG_read_or_hashed": False,
            "new_jobs_started": False,
            "shared_state_written": False,
            "case_credit_granted": 0,
            "model": "gpt-5.6-luna/max",
            "recursive_delegation": False,
        },
    }
    out = PACKAGE / "metadata" / "full336-user-delivery-index.json"
    out.write_text(json.dumps(delivery, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(out)
    print("accepted=", delivery["counts"]["accepted_independent_cases"], "pending=", delivery["counts"]["pending_independent_cases"])
    print("families=", delivery["counts"]["accepted_per_family"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
