#!/usr/bin/env python3
"""Metadata-only validator for the F5-assigned F3 Root1141 personal review."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
CASE="F3_STAGE1_DP006_P1200_AY0640"
PHYS="F3_TWOAXIS_P1200_AY0640_STAGE1_FIRST48_PITCH_VARIANT"
ATTEMPT="root-stage1-f3-p1200-ay0640-actual1076-full836-116-023-nvme-hard2gib-root1141"
CAN="c4ad5c82e0d1e06389b1934f2fa42741e7d4ac3f6e764ed65dd11fa28b3917da"
XMF_PLAN="4a36ea685ab84ef64afc89a60f5fa778ed1a8d3ba220c2d49ec8aeaf67705abc"
QI_SHA="41a88e6bee1315c43bd10ee637ca503f1403711ac5b8c9521c332f35948f3d4a"
KEY=[0,100,200,300,400,500,600,700,835]
EXPECTED={"README.md","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh207.py"}
def load(rel): return json.loads((ROOT/rel).read_text())
def digest(p):
 h=hashlib.sha256();
 with p.open("rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
 return h.hexdigest()
def req(x,msg):
 if not x: raise AssertionError(msg)
def main():
 man=load("manifest.json"); req(man["source_only"] is True,"source_only"); req(man["manifest_excludes_self"] is True,"manifest self exclusion")
 req(man["assigned_family_id"]=="F3" and man["stored_under_source_family"]=="F5","assignment roles")
 req(man["science_payloads_copied"] is False and man["scientific_jobs_started_by_source_agent"] is False and man["shared_state_written_by_source_agent"] is False,"isolation")
 entries={x["path"]:x for x in man["files"]}; req(set(entries)==EXPECTED,"package file set")
 for rel,e in entries.items():
  p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(digest(p)==e["sha256"],"hash "+rel)
 render=load("metadata/actual-render-metadata.json"); png=load("metadata/png-visual-evidence.json"); close=load("metadata/physical-stage-closure.json"); upstream=load("metadata/upstream-evidence.json"); visual=load("metadata/visual-decision.json")
 for d in (render,png,close,upstream,visual): req(d["case_id"]==CASE,"case id"); req(d["physical_case_id"]==PHYS,"physical id")
 req(render["family_id"]=="F3" and render["assigned_agent_family"]=="F5","family roles"); req(render["attempt_id"]==ATTEMPT,"attempt")
 er=render["execution_receipt"]; req(er["status"]=="completed" and er["returncode"]==0,"render receipt")
 pub=render["publish_receipt"]; req(pub["status"]=="published_after_atomic_rename" and pub["renderer_delegated_to_root023"] is True,"atomic publish")
 ea=render["expected_and_actual"]; req(ea["frames"]==836 and ea["source_frames"]==836 and ea["particles"]==179208 and ea["contact_sheets"]==35,"dimensions"); req(ea["keyframe_indices"]==KEY and ea["all_frames_rendered"] is True and ea["actual_times_preserved_exactly"] is True,"frame closure"); req(ea["native_identity_axis_preserved"] is True and ea["nonfinite_active_states"]==0,"identity finite")
 req(render["producer_counts"]=={"fixed":111708,"moving":0,"floating":0,"fluid_initial":67500,"total_initial":179208,"solver_dimension":3,"data2d":False},"counts"); req(render["render_report"]["numerical_precision_status"]=="not accepted","precision")
 scopes=upstream["producer_scope_roles"]; req(scopes["native_request_condition_sha256"]==CAN and scopes["actual_converter_condition_sha256"]==CAN and scopes["native_source_plan_condition_field_present"] is False and scopes["native_source_plan_condition_sha256"] is None and scopes["native_source_plan_physical_condition_field_present"] is False and scopes["native_source_plan_physical_condition_sha256"] is None,"native namespace")
 req(scopes["xmf_source_plan_condition_sha256"]==XMF_PLAN and scopes["xmf_source_plan_condition_field_present"] is True and scopes["xmf_source_plan_physical_condition_field_present"] is False and scopes["xmf_source_plan_physical_condition_sha256"] is None,"xmf namespace")
 req(scopes["scope_equality_claimed"] is False and scopes["roles_are_distinct"] is True,"scope separation")
 req(len(png["producer_attested_contact_sheets"])==35 and [x["index"] for x in png["producer_attested_contact_sheets"]]==list(range(35)) and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
 req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keyframes")
 req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer hashes"); req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
 req(close["stage_chain"]["render_completed_zero_and_published"] is True and close["visual_scope_limits"]["strict_container_guarantee"] is False and close["visual_scope_limits"]["sub_dp_penetration_claim"] is False,"limits")
 dec=visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False,"visual decision"); req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
 io=render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False,"payload isolation"); req(upstream["main_qi"]["all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified"] is True,"main QI")
 qip=Path(upstream["main_qi"]["path"]); req(qip.is_file(),"QI path"); req(digest(qip)==QI_SHA,"QI sha")
 t=datetime.fromisoformat(render["personal_review_scope"]["reviewed_at_utc"].replace("Z","+00:00")); f=datetime.fromisoformat(er["finished_at_utc"].replace("Z","+00:00")); req(t>=f,"review before producer finished"); req(t<=datetime.now(timezone.utc),"review in future")
 print("fresh207 assigned-F3 P1200/AY0640 metadata and personal visual handoff validation PASS"); print("package="+str(ROOT)); print("reviewed=35 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__=="__main__": main()
