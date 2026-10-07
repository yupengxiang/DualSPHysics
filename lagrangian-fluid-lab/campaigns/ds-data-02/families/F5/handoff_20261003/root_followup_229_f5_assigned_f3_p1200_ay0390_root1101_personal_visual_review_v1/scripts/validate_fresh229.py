#!/usr/bin/env python3
"""Metadata-only validator for F5-assigned F3 AY0390 personal visual review."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
CASE = "F3_STAGE1_DP006_P1200_AY0390"
PHYS = "F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT"
ATTEMPT = "root-stage1-f3-p1200-ay0390-actual1075-full836-116-023-nvme-hard2gib-root1101"
CAN = "6785314266d78e2247839c32a986838025663f371a65081ce5d42dc38eb80cac"
XMF_CONDITION = "7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5"
QI_SHA = "2d764fca467c180ac070e5f7d9e07e13d77a422c72aaf0bc7f932fd7ef8398a5"
KEY = [0,104,208,312,417,521,626,730,835]
EXPECTED = {"README.md","manifest.json","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh229.py"}
def load(rel): return json.loads((ROOT/rel).read_text())
def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()
def req(v,m):
    if not v: raise AssertionError(m)
def iso(s): return datetime.fromisoformat(s.replace("Z","+00:00"))
def main():
    man=load("manifest.json"); req(man["source_only"] is True and man["manifest_excludes_self"] is True,"manifest policy")
    req(man["assigned_family_id"]=="F5" and man["stored_under_source_family"]=="F5" and man["physical_family_id"]=="F3","family")
    req(man["science_payloads_copied"] is False and man["scientific_jobs_started_by_source_agent"] is False and man["shared_state_written_by_source_agent"] is False,"isolation")
    entries={x["path"]:x for x in man["files"]}; req(set(entries)==EXPECTED-{ "manifest.json" },"file set")
    for rel,e in entries.items():
        p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(digest(p)==e["sha256"],"hash "+rel)
    render=load("metadata/actual-render-metadata.json"); close=load("metadata/physical-stage-closure.json"); png=load("metadata/png-visual-evidence.json"); up=load("metadata/upstream-evidence.json"); visual=load("metadata/visual-decision.json")
    for d in (render,close,png,up,visual): req(d["case_id"]==CASE and d["physical_case_id"]==PHYS,"identity")
    req(render["assigned_agent_family"]=="F5" and render["physical_family_id"]=="F3" and render["family_id"]=="F3" and render["attempt_id"]==ATTEMPT,"assignment")
    er=render["execution_receipt"]; req(er["status"]=="completed" and er["returncode"]==0,"receipt")
    pub=render["publish_receipt"]; req(pub["status"]=="published_after_atomic_rename" and pub["renderer_delegated_to_root023"] is True,"publish")
    ea=render["expected_and_actual"]; req(ea["frames"]==836 and ea["source_frames"]==836 and ea["particles"]==179208 and ea["fixed_particles"]==111708 and ea["fluid_initial_UIDs"]==67500 and ea["contact_sheets"]==35 and ea["keyframe_indices"]==KEY,"dimensions")
    req(ea["actual_times_preserved_exactly"] is True and ea["all_frames_rendered"] is True and ea["native_identity_axis_preserved"] is True and ea["nonfinite_active_states"]==0,"frame integrity")
    req(render["producer_counts"]=={"total_initial":179208,"fixed":111708,"moving":0,"floating":0,"fluid_initial":67500,"solver_dimension":3,"data2d":False},"counts")
    req(render["render_report"]["numerical_precision_status"]=="not accepted","precision")
    sc=render["scope_roles"]; req(sc["canonical_physical_condition_sha256"]==CAN and sc["actual_converter_scope_sha256"]==CAN,"canonical scope")
    req(sc["native_source_plan_condition_field_present"] is False and sc["native_source_plan_condition_sha256"] is None and sc["native_source_plan_physical_condition_field_present"] is False and sc["native_source_plan_physical_condition_sha256"] is None,"native masks")
    req(sc["xmf_source_plan_condition_field_present"] is True and sc["xmf_source_plan_condition_sha256"]==XMF_CONDITION and sc["xmf_source_plan_physical_condition_field_present"] is False and sc["xmf_source_plan_physical_condition_sha256"] is None,"XMF masks")
    req(sc["xmf_condition_is_not_native_canonical_digest"] is True and sc["roles_are_distinct"] is True and sc["scope_equality_claimed"] is False and sc["condition_plan_absence_preserved_without_backfill"] is True,"role separation")
    req(len(png["producer_attested_contact_sheets"])==35 and [x["index"] for x in png["producer_attested_contact_sheets"]]==list(range(35)) and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
    req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keys")
    all_png=png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]; req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in all_png),"producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False and png["review_coverage"]["private_or_unpublished_pngs_opened"] is False,"PNG provenance")
    pub_path=Path(pub["path"]); req(pub_path.is_file(),"publish receipt path"); producer={x["relative_path"]:x for x in json.loads(pub_path.read_text())["files_excluding_receipt"]}
    for item in all_png:
        rel=item["relative_path"]; req(rel in producer,"PNG absent from producer receipt: "+rel); p=Path(item["absolute_path"]); req(p.is_file(),"published PNG missing: "+rel); req(p.stat().st_size==item["bytes"]==producer[rel]["bytes"],"published PNG stat: "+rel); req(item["sha256"]==producer[rel]["sha256"] and item["sha256_source"].startswith("producer "),"PNG producer attestation: "+rel)
    req(close["stage_chain"]["render_completed_zero_and_atomically_published"] is True and close["visual_scope_limits"]["strict_container_guarantee"] is False and close["visual_scope_limits"]["sub_dp_penetration_claim"] is False,"limits")
    dec=visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False and dec["coherent_full_time_wave_mechanism_seen"] is True,"visual")
    req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
    io=render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False and io["shared_state_written"] is False,"payload")
    req(up["main_qi"]["all836_geometry_velocity_N3_times_UID_finite_verified"] is True and up["main_qi"]["all_native_UIDs_active_each_frame"] is True,"QI")
    qp=Path(up["main_qi"]["path"]); req(qp.is_file() and digest(qp)==QI_SHA,"QI reference")
    reviewed=iso(render["personal_review_scope"]["reviewed_at_utc"]); finished=iso(er["finished_at_utc"]); req(reviewed>=finished,"review before producer finish"); req(reviewed<=datetime.now(timezone.utc),"review in future")
    req(render["personal_review_scope"]["reviewer_model"]=="gpt-5.6-luna/max" and render["personal_review_scope"]["recursive_delegation"] is False,"model")
    print("fresh229 F5-assigned F3 AY0390 personal metadata and visual handoff validation PASS")
    print("package="+str(ROOT)); print("reviewed=35 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__=="__main__": main()
