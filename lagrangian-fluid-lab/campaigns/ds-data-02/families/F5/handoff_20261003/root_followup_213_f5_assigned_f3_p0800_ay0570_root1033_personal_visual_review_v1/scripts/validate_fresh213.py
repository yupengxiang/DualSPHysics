#!/usr/bin/env python3
"""Metadata-only validator for the F5-assigned F3 Root1033 visual review."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
CASE = "F3_STAGE1_DP006_P0800_AY0570"
PHYS = "F3_TWOAXIS_P0800_AY0570_STAGE1_FIRST48_PITCH_VARIANT"
ATTEMPT = "root-stage1-f3-p0800-ay0570-actual1002-full836-116-023-nvme-hard2gib-root1033"
CAN = "bb7ed44d73920c9152d81f581e4bc9d628c5302f77a0560114c7a6a319e6a5a6"
QI_SHA = "a2eb02ce9c9a1634049838619fcd1b47857f6632e94588480502b1d675986664"
KEY = [0,100,200,300,400,500,600,700,835]
EXPECTED = {"README.md","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh213.py"}
def load(rel): return json.loads((ROOT/rel).read_text())
def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def req(v,m):
    if not v: raise AssertionError(m)
def main():
    man=load("manifest.json")
    req(man["source_only"] is True and man["manifest_excludes_self"] is True,"manifest policy")
    req(man["assigned_family_id"]=="F3" and man["stored_under_source_family"]=="F5","family assignment")
    req(man["science_payloads_copied"] is False and man["scientific_jobs_started_by_source_agent"] is False and man["shared_state_written_by_source_agent"] is False,"isolation")
    entries={x["path"]:x for x in man["files"]}
    req(set(entries)==EXPECTED,"file set")
    for rel,e in entries.items():
        p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(digest(p)==e["sha256"],"hash "+rel)
    render=load("metadata/actual-render-metadata.json"); close=load("metadata/physical-stage-closure.json"); png=load("metadata/png-visual-evidence.json"); up=load("metadata/upstream-evidence.json"); visual=load("metadata/visual-decision.json")
    for d in (render,close,png,up,visual): req(d["case_id"]==CASE and d["physical_case_id"]==PHYS,"identity")
    req(render["assigned_agent_family"]=="F5" and render["family_id"]=="F3" and render["attempt_id"]==ATTEMPT,"assignment")
    er=render["execution_receipt"]; req(er["status"]=="completed" and er["returncode"]==0,"receipt")
    pub=render["publish_receipt"]; req(pub["status"]=="published_after_atomic_rename" and pub["renderer_delegated_to_root023"] is True,"publish")
    ea=render["expected_and_actual"]; req(ea["frames"]==836 and ea["source_frames"]==836 and ea["particles"]==179208 and ea["contact_sheets"]==35 and ea["keyframe_indices"]==KEY,"dimensions")
    req(ea["actual_times_preserved_exactly"] is True and ea["all_frames_rendered"] is True and ea["native_identity_axis_preserved"] is True and ea["nonfinite_active_states"]==0,"frame integrity")
    req(render["producer_counts"]=={"total_initial":179208,"fixed":111708,"moving":0,"floating":0,"fluid_initial":67500,"solver_dimension":3,"data2d":False},"counts")
    req(render["render_report"]["numerical_precision_status"]=="not accepted","precision")
    sc=up["producer_scope_roles"]
    req(sc["native_request_condition_sha256"]==CAN and sc["actual_converter_condition_sha256"]==CAN,"canonical")
    for p in ("native","xmf"):
        req(sc[p+"_source_plan_condition_field_present"] is False and sc[p+"_source_plan_condition_sha256"] is None,p+" condition absence")
        req(sc[p+"_source_plan_physical_condition_field_present"] is False and sc[p+"_source_plan_physical_condition_sha256"] is None,p+" physical absence")
    req(sc["roles_are_distinct"] is True and sc["scope_equality_claimed"] is False and sc["plan_absence_preserved_without_backfill"] is True,"scope")
    req(len(png["producer_attested_contact_sheets"])==35 and [x["index"] for x in png["producer_attested_contact_sheets"]]==list(range(35)) and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
    req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keys")
    req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"PNG producer hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False and png["review_coverage"]["private_or_unpublished_pngs_opened"] is False,"PNG provenance")
    req(close["stage_chain"]["render_completed_zero_and_published"] is True and close["visual_scope_limits"]["strict_container_guarantee"] is False and close["visual_scope_limits"]["sub_dp_penetration_claim"] is False,"limits")
    dec=visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False,"visual")
    req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
    io=render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False,"payload")
    req(up["main_qi"]["all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"] is True,"QI")
    qp=Path(up["main_qi"]["path"]); req(qp.is_file() and digest(qp)==QI_SHA,"QI reference")
    t=datetime.fromisoformat(render["personal_review_scope"]["reviewed_at_utc"].replace("Z","+00:00")); f=datetime.fromisoformat(er["finished_at_utc"].replace("Z","+00:00"))
    req(t>=f,"review before finish"); req(t<=datetime.now(timezone.utc),"review future")
    req(render["personal_review_scope"]["reviewer_model"]=="gpt-5.6-luna/max" and render["personal_review_scope"]["recursive_delegation"] is False,"model")
    print("fresh213 assigned-F3 P0800/AY0570 metadata and personal visual handoff validation PASS")
    print("package="+str(ROOT))
    print("reviewed=35 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__=="__main__": main()
