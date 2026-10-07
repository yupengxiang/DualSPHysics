#!/usr/bin/env python3
"""Metadata-only validator for F5 M112/T095 Root1191 personal review."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M112_T095_NEXT34"
PHYS = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M112_T095"
ATTEMPT = "root-stage1-f5-m112_t095-actual1185-bed0-full801-original116023-frozen-progress-root1191"
CAN = "f0d480ec9e75c70daea8aca22dc155e7e62fa5dcd1a37a65699a000f31c416ca"
XMF_PLAN = "92b9e7c7e80bbe1e0239dd3487923452e77af3d265fa6dc7794f8b3edcebaf97"
LEGACY = "f7feb75534a3f33cac3d1fd906733dc231ccb63fd430bffe3e9184c6e92f484f"
QI_SHA = "07f129aaf08299342d0e62486fe766c4aa5e8f7a04ac38378e72523e4f675285"
KEY = [0,100,200,300,400,500,600,700,800]
EXPECTED = {"README.md", "metadata/actual-render-metadata.json", "metadata/physical-stage-closure.json", "metadata/png-visual-evidence.json", "metadata/upstream-evidence.json", "metadata/visual-decision.json", "scripts/validate_fresh208.py"}
def load(rel): return json.loads((ROOT / rel).read_text())
def digest(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""): h.update(c)
    return h.hexdigest()
def req(x, msg):
    if not x: raise AssertionError(msg)
def main():
    man = load("manifest.json")
    req(man["source_only"] is True and man["manifest_excludes_self"] is True, "manifest flags")
    req(man["family_id"] == "F5" and man["stored_under_source_family"] == "F5", "family")
    req(man["science_payloads_copied"] is False and man["scientific_jobs_started_by_source_agent"] is False and man["shared_state_written_by_source_agent"] is False, "isolation")
    entries = {x["path"]: x for x in man["files"]}; req(set(entries) == EXPECTED, "file set")
    for rel, e in entries.items():
        p = ROOT / rel; req(p.is_file(), "missing " + rel); req(p.stat().st_size == e["bytes"], "bytes " + rel); req(digest(p) == e["sha256"], "hash " + rel)
    render = load("metadata/actual-render-metadata.json"); png = load("metadata/png-visual-evidence.json"); close = load("metadata/physical-stage-closure.json"); upstream = load("metadata/upstream-evidence.json"); visual = load("metadata/visual-decision.json")
    for d in (render, png, close, upstream, visual): req(d["case_id"] == CASE and d["physical_case_id"] == PHYS, "identity")
    req(render["attempt_id"] == ATTEMPT and render["family_id"] == "F5", "attempt")
    er = render["execution_receipt"]; req(er["status"] == "completed" and er["returncode"] == 0, "render receipt")
    pub = render["publish_receipt"]; req(pub["status"] == "published_after_atomic_rename" and pub["renderer_delegated_to_root023"] is True, "publish")
    ea = render["expected_and_actual"]; req(ea["frames"] == 801 and ea["source_frames"] == 801 and ea["particles"] == 194427 and ea["contact_sheets"] == 34, "dimensions")
    req(ea["keyframe_indices"] == KEY and ea["all_frames_rendered"] is True and ea["actual_times_preserved_exactly"] is True, "frame closure")
    req(ea["native_identity_axis_preserved"] is True and ea["nonfinite_active_states"] == 0, "identity finite")
    req(render["producer_counts"] == {"fixed":158559,"moving":4210,"floating":0,"fluid_initial":31658,"total_initial":194427,"solver_dimension":3,"data2d":False}, "counts")
    req(render["render_report"]["numerical_precision_status"] == "not accepted", "precision")
    scopes = upstream["producer_scope_roles"]
    req(scopes["native_source_plan_condition_field_present"] is True and scopes["native_source_plan_condition_sha256"] == CAN, "native condition scope")
    req(scopes["native_source_plan_physical_condition_field_present"] is True and scopes["native_source_plan_physical_condition_sha256"] == CAN, "native physical scope")
    req(scopes["xmf_source_plan_condition_field_present"] is False and scopes["xmf_source_plan_condition_sha256"] is None, "xmf condition scope")
    req(scopes["xmf_source_plan_physical_condition_field_present"] is True and scopes["xmf_source_plan_physical_condition_sha256"] == XMF_PLAN, "xmf physical scope")
    req(scopes["source_definition_sha256"] == XMF_PLAN and scopes["typed_converter_legacy_scope_sha256"] == LEGACY, "role scope")
    req(scopes["scope_equality_claimed"] is False and scopes["roles_are_distinct"] is True, "scope separation")
    req(len(png["producer_attested_contact_sheets"]) == 34 and [x["index"] for x in png["producer_attested_contact_sheets"]] == list(range(34)), "contacts")
    req(all(x["reviewed"] for x in png["producer_attested_contact_sheets"]), "contact review")
    req(len(png["producer_attested_keyframes"]) == 9 and [x["frame_index"] for x in png["producer_attested_keyframes"]] == KEY, "keyframes")
    req(all(x["reviewed"] for x in png["producer_attested_keyframes"]), "keyframe review")
    req(all(re.fullmatch(r"[0-9a-f]{64}", x["sha256"]) for x in png["producer_attested_contact_sheets"] + png["producer_attested_keyframes"]), "producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False, "source PNG hashing")
    req(close["bed_audit_evidence"]["diagnostic_only"] is True and close["bed_audit_evidence"]["zero_one_dp_two_dp_is_diagnostic_only"] is True, "bed diagnostic scope")
    req(close["bed_audit_evidence"]["strict_container_guarantee"] is False and close["bed_audit_evidence"]["sub_dp_penetration_absence_claim"] is False, "bed limits")
    dec = visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False, "visual decision")
    req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"] == 0, "credit")
    io = render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False, "payload isolation")
    req(upstream["main_qi"]["all801_geometry_velocity_N3_times_UID_finite_verified"] is True and upstream["main_qi"]["all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked"] is True, "main QI")
    qip = Path(upstream["main_qi"]["path"]); req(qip.is_file(), "QI path"); req(digest(qip) == QI_SHA, "QI sha")
    t = datetime.fromisoformat(render["personal_review_scope"]["reviewed_at_utc"].replace("Z", "+00:00")); f = datetime.fromisoformat(er["finished_at_utc"].replace("Z", "+00:00")); req(t >= f, "review before finish"); req(t <= datetime.now(timezone.utc), "review future")
    print("fresh208 M112/T095 metadata and personal visual handoff validation PASS")
    print("package=" + str(ROOT)); print("reviewed=34 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__ == "__main__": main()
