#!/usr/bin/env python3
"""Build the F6 final-48 primary delivery from frozen metadata sources.

This builder reads JSON metadata and records XML/XMF/PNG references.  It does
not open, hash, copy, or parse H5/BI4/CSV/DAT/VTK scientific payloads.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003")
F6ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics")
OUT = Path(__file__).resolve().parents[1]
F6HANDOFF = F6ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003"
LAST = "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
META_SUFFIXES = {".json", ".xml", ".xmf"}

P1276 = INTEGRATION / "root_stage1_sources178164_actual_F2_F3_F6_first24_delivery72_correct_own_primary_XMF_PNG_8_subset24_subset48_1276/F6-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json"
P1313 = INTEGRATION / "root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_same_native_receipts_times_and_baseline_absence_main_delivery_1313/F6-ACTUAL_FIRST24-PARTICLE-RIGID-JOINED-DELIVERY.json"
P1321 = INTEGRATION / "root_stage1_source171_F6_final48_particle_rigid_actual47_visual_bindings_470_published_navigation_keys_one_pending_no_credit_1321/F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING-DELIVERY.json"
P1345 = INTEGRATION / "root_stage1_source189_lastF6_actual951_full241_particle_rigid_QI_personal21PNG_three_fluid_omissions_F6_final48_visual_acceptance305_1345/full336-current305-actual-final48-delivery-progress-index.json"
P1345_ADOPTION = INTEGRATION / "root_stage1_source189_lastF6_actual951_full241_particle_rigid_QI_personal21PNG_three_fluid_omissions_F6_final48_visual_acceptance305_1345/source189-actual951-lastF6-full241-particle-rigid-QI-personal-visual-adoption.json"
P1341 = INTEGRATION / "root_stage1_lastF6_actual951_full241_render_particle_UID_N3_three_fluid_omissions_fulltime_rigid_part_times_scope_independent_previsual_QI_1341/actual951-lastF6-full241-render-plus-rigid-QI-three-fluid-omissions-scope-previsual-proof.json"
P1305 = INTEGRATION / "root_stage1_F6_actual48_fulltime_official_rigid_motion_47new241rows_one_existing_history_CPU2_and_pendingF5_1131_1180_ownQI_checkpoint_1305/F6-FINAL48-FULLTIME-RIGID-MOTION-DELIVERY.json"
P262 = INTEGRATION / "ROOT_LIVE_RESUMPTION_CHECKPOINT_262.json"
P189_LOCAL = F6HANDOFF / "root_followup_189_f6_last_DZXY_S1375_YAWP18_original951_personal_visual_review_v1/metadata/personal-visual-decision.json"


def load(path: Path):
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metadata_ref(path: Path, kind: str = "metadata") -> dict:
    path = Path(path)
    allowed_source = kind == "source" and path.suffix.lower() == ".py"
    allowed_documentation = kind == "documentation" and path.suffix.lower() == ".md"
    if path.suffix.lower() not in META_SUFFIXES and not allowed_source and not allowed_documentation:
        raise ValueError(f"metadata_ref refuses non-metadata suffix: {path}")
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "kind": kind}


def ref_copy(value):
    return copy.deepcopy(value)


def normalize_descriptor(value):
    """Normalize an existing metadata reference without touching payloads."""
    if not isinstance(value, dict) or "path" not in value:
        return ref_copy(value)
    out = ref_copy(value)
    path = Path(out["path"])
    probe = out.get("metadata_probe") if isinstance(out.get("metadata_probe"), dict) else {}
    if path.suffix.lower() in META_SUFFIXES:
        if not out.get("sha256"):
            out["sha256"] = out.get("declared_sha256") or probe.get("declared_sha256") or probe.get("json_sha256") or sha(path)
        if not out.get("bytes"):
            out["bytes"] = probe.get("bytes_stat") or path.stat().st_size
    return out


def normalize_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return [normalize_descriptor(x) for x in value]
    return [normalize_descriptor(value)]


def current_decision_summary(current: dict) -> dict:
    decision = current.get("accepted_decision") or {}
    decision_json = load(Path(decision["path"])) if decision.get("path") and Path(decision["path"]).is_file() else {}
    return {
        "status": current.get("status"),
        "frozen_checkpoint_262_accepted": True,
        "accepted_decision": ref_copy(decision),
        "accepted_decision_top_condition_sha256": current.get("accepted_decision_top_condition_sha256"),
        "accepted_decision_top_hash_role": current.get("accepted_decision_top_hash_role"),
        "declared_source_plan_condition_sha256": current.get("declared_source_plan_condition_sha256"),
        "declared_source_definition_sha256": current.get("declared_source_definition_sha256"),
        "declared_actual_converter_scope_sha256": current.get("declared_actual_converter_scope_sha256"),
        "precision_status": decision_json.get("precision_status", current.get("precision_status")),
        "q_n": decision_json.get("q_n", decision_json.get("Q_N", False)),
        "q_e": decision_json.get("q_e", decision_json.get("Q_E", False)),
        "independent_case_increment": decision_json.get("independent_case_increment"),
    }


def last_accepted_metadata(fresh: dict, current: dict) -> dict:
    e = fresh["evidence"]
    v = fresh["visual_review"]
    d = fresh["decision"]
    def pick(name):
        return ref_copy(e[name])
    contact = [ref_copy(x) for x in v["contact_sheets"]]
    keys = [ref_copy(x) for x in v["key_frames"]]
    return {
        "accepted_decision": ref_copy(current["accepted_decision"]),
        "independent_metadata_closure": {
            "source_personal_visual_review": metadata_ref(P189_LOCAL),
            "main_qi_proof": pick("main_qi_proof"),
            "root1341_qi_role": "independent full241 particle/rigid metadata QI; no new scientific read by this package",
        },
        "actual_xmf_manifest": pick("xmf_manifest"),
        "actual_xmf_xml": pick("xmf_xml"),
        "actual_render_report": pick("render_report"),
        "actual_render_receipt": pick("render_receipt"),
        "actual_render_publish_receipt": pick("render_publish_receipt"),
        "native_refs": [pick("native_receipt"), pick("native_request")],
        "typed_refs": [pick("typed_receipt"), pick("typed_report")],
        "gencase_or_definition_refs": [pick("gencase_receipt"), pick("gencase_report"), pick("generated_xml"), pick("source_definition")],
        "initial_qa_or_audit_refs": [pick("initial_qa_receipt"), pick("initial_qa_report"), pick("state0_receipt"), pick("state0_report"), pick("h5_audit_receipt"), pick("h5_audit_report")],
        "owner_or_source_refs": [pick("canonical_owner"), pick("classified_owner"), pick("readiness_evidence")],
        "contact_png_refs": contact,
        "key_png_refs": keys,
        "png_evidence_sources": [{"path": pick("render_publish_receipt")["path"], "sha256": pick("render_publish_receipt")["sha256"], "role": "producer publish receipt; PNG hashes are producer attestations and are not recomputed here"}],
        "decision_visual_metadata": {
            "status": d["status"],
            "visual_review": {"personally_viewed_with": v["personally_viewed_with"], "contact_sheet_count": v["contact_sheet_count"], "key_frame_count": v["key_frame_count"], "wrapper_keyframe_indices_original9_preserved": v["wrapper_keyframe_indices_original9_preserved"]},
            "observations": d["observations"],
        },
        "source_scope": {
            "native_canonical_physical_condition_sha256": fresh["case"]["native_canonical_physical_condition_sha256"],
            "typed_xmf_legacy_producer_scope_sha256": fresh["case"]["typed_xmf_legacy_producer_scope_sha256"],
            "source_plan_condition_sha256": fresh["case"]["source_plan_condition_sha256"],
            "source_plan_physical_condition_sha256": fresh["case"]["source_plan_physical_condition_sha256"],
            "roles_must_remain_distinct": True,
            "native_source_plan_physical_condition_sha256": fresh["case"]["scope_roles"]["native_source_plan_physical_condition_sha256"],
            "xmf_source_plan_physical_condition_sha256": fresh["case"]["scope_roles"]["xmf_source_plan_physical_condition_sha256"],
        },
        "limits": {
            "declared_counts": fresh["case"]["declared_counts"],
            "terminal_counts": fresh["case"]["terminal_counts"],
            "lifecycle_omissions": fresh["case"]["lifecycle_omissions"],
            "physical_mass_kg": fresh["case"]["physical_mass_kg"],
            "native_support_mass_kg": fresh["case"]["native_support_mass_kg"],
            "mass_rescaling": fresh["case"]["mass_rescaling"],
            "precision_status": d["precision_status"],
            "q_n_granted": d["q_n_granted"],
            "q_e_granted": d["q_e_granted"],
            "strict_container_guarantee": d["strict_container_guarantee"],
        },
    }


def png_refs_from_sidecar(sidecar: dict, fallback_meta: dict | None = None) -> dict:
    if sidecar:
        return {
            "contacts": normalize_list(sidecar.get("main_actual_published_contact_refs", [])),
            "navigation_previews": normalize_list(sidecar.get("main_actual_published_navigation_previews", [])),
            "source_counts": {"contacts": sidecar.get("source_contacts_verified"), "keys": sidecar.get("source_keys_verified"), "named_keys_unlisted_retained": sidecar.get("source_named_keys_unlisted_retained")},
        }
    fallback_meta = fallback_meta or {}
    return {
        "contacts": normalize_list(fallback_meta.get("contact_png_refs", [])),
        "navigation_previews": normalize_list(fallback_meta.get("key_png_refs", [])),
        "source_counts": {"contacts": len(fallback_meta.get("contact_png_refs", [])), "keys": len(fallback_meta.get("key_png_refs", [])), "named_keys_unlisted_retained": False},
    }


def primary_refs(row: dict, sidecar: dict | None) -> dict:
    m = row.get("accepted_visual_metadata") or {}
    rigid = row.get("rigid_motion_join") or row.get("progress_index_row", {}).get("actual_fulltime_rigid_motion_evidence")
    def first_list(name):
        v = m.get(name, [])
        return ref_copy(v) if isinstance(v, list) else [ref_copy(v)] if v else []
    return {
        "gencase_or_definition": normalize_list(m.get("gencase_or_definition_refs", [])),
        "initial_qa_or_audit": normalize_list(m.get("initial_qa_or_audit_refs", [])),
        "owner_or_source": normalize_list(m.get("owner_or_source_refs", [])),
        "native": normalize_list(m.get("native_refs", [])),
        "typed": normalize_list(m.get("typed_refs", [])),
        "xmf": {
            "receipt": normalize_descriptor(m.get("actual_xmf_receipt")) if m.get("actual_xmf_receipt") else None,
            "manifest": normalize_descriptor(m.get("actual_xmf_manifest")) if m.get("actual_xmf_manifest") else None,
            "xml": normalize_descriptor(m.get("actual_xmf_xml")) if m.get("actual_xmf_xml") else None,
        },
        "render": {
            "receipt": normalize_descriptor(m.get("actual_render_receipt")) if m.get("actual_render_receipt") else None,
            "report": normalize_descriptor(m.get("actual_render_report")) if m.get("actual_render_report") else None,
            "publish_receipt": normalize_descriptor(m.get("actual_render_publish_receipt")) if m.get("actual_render_publish_receipt") else None,
        },
        "png": png_refs_from_sidecar(sidecar, m),
        "rigid": ref_copy(rigid),
    }


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False) + "\n")


def build():
    p1276, p1313, p1321, p1345, p1345_adopt, p1341, p1305, p262 = map(load, [P1276, P1313, P1321, P1345, P1345_ADOPTION, P1341, P1305, P262])
    fresh = load(P189_LOCAL)
    current_cases = {r["physical_case_id"]: r for r in p1345["cases"] if r.get("family_id") == "F6"}
    old_rows = p1321["rows"]
    sidecars = {r["physical_case_id"]: r for r in p1321["main_native_particle_rigid_and_published_navigation_sidecars"]}
    final_ids = list(p1321["membership"]["registered_final48_physical_case_ids"])
    first8 = list(p1276["frozen_first8_physical_case_ids"])
    first24 = list(p1276["actual_first24_physical_case_ids"])
    assert final_ids == list(p1313["membership"]["registered_final48_physical_case_ids"])
    assert set(first8).issubset(first24) and set(first24).issubset(final_ids)
    assert len(first8) == 8 and len(first24) == 24 and len(final_ids) == 48 and len(set(final_ids)) == 48
    assert set(current_cases) == set(final_ids)
    assert p262["checkpoint"] == 262 and p262["accepted_per_family"]["F6"] == 48
    rows = []
    for base in old_rows:
        pid = base["physical_case_id"]
        assert pid in final_ids and pid in current_cases
        row = copy.deepcopy(base)
        current = current_cases[pid]
        row["visual_status"] = current.get("status")
        row["frozen_checkpoint_262_accepted"] = True
        row["current_checkpoint_262_case_index"] = {"source": metadata_ref(P1345), "physical_case_id": pid, "status": current.get("status"), "accepted_decision": ref_copy(current.get("accepted_decision")), "accepted_decision_top_condition_sha256": current.get("accepted_decision_top_condition_sha256")}
        row["current_accepted_decision_summary"] = current_decision_summary(current)
        if pid == LAST:
            row["accepted_visual_metadata"] = last_accepted_metadata(fresh, current)
            row["accepted_visual_decision_summary"] = current_decision_summary(current)
            row["scope_roles"] = {
                "roles_must_remain_distinct": True,
                "current_checkpoint_262_top_decision": ref_copy(current.get("accepted_decision")),
                "native_canonical_physical_condition_sha256": fresh["case"]["native_canonical_physical_condition_sha256"],
                "typed_xmf_legacy_producer_scope_sha256": fresh["case"]["typed_xmf_legacy_producer_scope_sha256"],
                "source_plan_condition_sha256": fresh["case"]["source_plan_condition_sha256"],
                "source_plan_physical_condition_sha256": None,
            }
        row["primary_refs"] = primary_refs(row, sidecars.get(pid))
        if pid == LAST:
            # sidecar 1321 predates the final Root951 review; use fresh189's
            # published PNG metadata without reopening or hashing PNG bytes.
            row["primary_refs"]["png"] = png_refs_from_sidecar(None, row["accepted_visual_metadata"])
            row["primary_refs"]["png"]["source_counts"] = {"contacts": fresh["visual_review"]["contact_sheet_count"], "keys": fresh["visual_review"]["key_frame_count"], "named_keys_unlisted_retained": True}
        rows.append(row)
    assert len(rows) == 48 and {r["physical_case_id"] for r in rows} == set(final_ids)
    out = {
        "schema": "ds02.f6.fresh190.final48-complete-particle-rigid-primary-delivery.v1",
        "fresh_id": "fresh190",
        "status": "complete_final48_primary_delivery_metadata_only",
        "family_id": "F6",
        "assigned_family": "F6",
        "actual_family": "F6",
        "created_at_utc": "2026-10-07T00:00:00Z",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "recursive_delegation": False,
        "authoritative_sources": {
            "frozen_checkpoint_262": metadata_ref(P262),
            "root1345_current_final48_index": metadata_ref(P1345),
            "root1345_source189_adoption": metadata_ref(P1345_ADOPTION),
            "root1321_particle_rigid_47_plus_one_pending": metadata_ref(P1321),
            "root1313_actual_first24_particle_rigid": metadata_ref(P1313),
            "root1276_actual_first24_dynamic": metadata_ref(P1276),
            "root1305_full48_rigid_product": metadata_ref(P1305),
            "root1341_lastF6_particle_rigid_QI": metadata_ref(P1341),
            "fresh189_personal_review_source": metadata_ref(P189_LOCAL),
        },
        "membership": {
            "frozen_first8_physical_case_ids": first8,
            "actual_first24_physical_case_ids": first24,
            "final48_physical_case_ids": final_ids,
            "frozen8_subset_actual24_subset_final48": True,
            "membership_order_authority": "Root1276 F6-ACTUAL_FIRST24_DYNAMIC_DELIVERY plus Root1321 registered_final48 order",
            "no_sorted_or_replica_selection": True,
        },
        "delivery": {
            "final48_count": 48,
            "accepted_visual_count_at_checkpoint262": 48,
            "pending_visual_count": 0,
            "all_rows_have_actual_native_typed_xmf_xml_render_png_metadata_roles": True,
            "new_case_credit": 0,
            "new_visual_credit": 0,
            "Q_N": False,
            "Q_E": False,
            "precision_status": "visual acceptance only; numeric precision not accepted",
            "production_approval": False,
        },
        "scope_policy": {
            "native_canonical_vs_typed_legacy_vs_xmf_plan_are_distinct": True,
            "accepted_top_condition_never_substitutes_actual_native_condition": True,
            "source_plan_condition_never_substitutes_absent_source_plan_physical_condition": True,
            "F6_OMEGA_BASELINE_V1_actual_native_condition_field": {"present": False, "value": None, "role": "preserved true absence from Root1320/1321 baseline metadata"},
            "baseline_legacy_part_field": {"present": False, "value": None, "role": "preserved boundary; no new full-CSV vector certification"},
            "full_csv_time_vector_independently_reverified_in_this_package": False,
            "CSV_policy": "reference/stat metadata only; no CSV payload read or hash by this package",
        },
        "mass_semantics": {"physical_mass_kg": 128, "native_support_mass_kg": 256, "mass_equality_claimed": False, "rescaling": False},
        "rigid_product": {
            "source": metadata_ref(P1305),
            "required_fields_finite_all241": True,
            "native_time_tolerance_s": 1e-6,
            "official_times_not_resampled": True,
            "part_baseline_boundary_false_null": True,
            "per_case_rigid_join_is_by_physical_case_id": True,
        },
        "last_case_limits": {
            "physical_case_id": LAST,
            "final_missing_fluid": 3,
            "first_missing_frame": 7,
            "frames_with_any_missing": 234,
            "cumulative_particle_frame_omissions": 700,
            "missing_location_state_cause_unknown": True,
            "all_native_uids_active_claim": False,
            "strict_container_guarantee": False,
            "declared_omega_rad_s": [0.0825, 0.11, 0.165],
            "observed_state0_omega_rad_s": [0.082500003, 0.11, 0.16500001],
            "particle_v0_proves_omega": False,
        },
        "source_boundaries": {"science_payload_read": False, "science_payload_hashed": False, "science_payload_copied": False, "new_science_jobs": False, "shared_registry_or_ledger_written": False, "historical_source_bytes_changed": False, "recursive_delegation": False},
        "rows": rows,
    }
    write_json(OUT / "metadata/final48-delivery.json", out)
    manifest = {
        "schema": "ds02.f6.fresh190.package-manifest.v1",
        "fresh_id": "fresh190",
        "self_excluded": True,
        "files": [
            metadata_ref(OUT / "metadata/final48-delivery.json"),
            metadata_ref(OUT / "README.md", "documentation"),
            metadata_ref(OUT / "scripts/build_final48.py", "source"),
            metadata_ref(OUT / "scripts/validate_final48.py", "source"),
        ],
    }
    write_json(OUT / "metadata/package-manifest.json", manifest)
    return out


if __name__ == "__main__":
    result = build()
    print(f"fresh190 built: {len(result['rows'])} rows; first8={len(result['membership']['frozen_first8_physical_case_ids'])}; first24={len(result['membership']['actual_first24_physical_case_ids'])}; final48={len(result['membership']['final48_physical_case_ids'])}")
