#!/usr/bin/env python3
"""Metadata-only validator for the F5 M090/T080 personal review handoff."""
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M090_T080_NEXT34"
PHYS="F5_COMPACT_RUNUP_RECOVERY_C082S1_M090_T080"
ATTEMPT="root-stage1-f5-m090_t080-actual1115-bed0-full801-original116023-frozen-progress-root1127"
CAN="090cfa143a5a838cb79d392a3944fe9c43d86e0340485504b2030a642d35d953"
LEG="d93ff9c98dbad0e67f6355b3dafaaeddd5369a5f59c190bacf3d614a2204c931"
SRC="24ddc0c38512f2877e76c9a1861ef371801d5842a9b40de9066e6d997577621a"
KEY=[0,100,200,300,400,500,600,700,800]
EXPECTED={"README.md","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh203.py"}
def load(rel): return json.loads((ROOT/rel).read_text())
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
 return h.hexdigest()
def req(x,msg):
 if not x: raise AssertionError(msg)
def main():
 man=load("manifest.json")
 req(man["source_only"] is True,"source_only"); req(man["manifest_excludes_self"] is True,"manifest self exclusion")
 req(man["science_payloads_copied"] is False,"payload copy"); req(man["scientific_jobs_started_by_source_agent"] is False,"job launch"); req(man["shared_state_written_by_source_agent"] is False,"shared write")
 entries={x["path"]:x for x in man["files"]}; req(set(entries)==EXPECTED,"package file set")
 for rel,e in entries.items():
  p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(digest(p)==e["sha256"],"hash "+rel)
 render=load("metadata/actual-render-metadata.json"); png=load("metadata/png-visual-evidence.json"); close=load("metadata/physical-stage-closure.json"); upstream=load("metadata/upstream-evidence.json"); visual=load("metadata/visual-decision.json")
 for d in (render,png,close,upstream,visual): req(d["case_id"]==CASE,"case id"); req(d["physical_case_id"]==PHYS,"physical id")
 req(render["attempt_id"]==ATTEMPT,"attempt"); er=render["execution_receipt"]; req(er["status"]=="completed" and er["returncode"]==0,"render receipt")
 pub=render["publish_receipt"]; req(pub["status"]=="published_after_atomic_rename" and pub["renderer_delegated_to_root023"] is True,"atomic publish")
 ea=render["expected_and_actual"]; req(ea["frames"]==801 and ea["source_frames"]==801 and ea["particles"]==194427 and ea["contact_sheets"]==34,"dimensions"); req(ea["keyframe_indices"]==KEY and ea["all_frames_rendered"] is True and ea["actual_times_preserved_exactly"] is True,"frame closure"); req(ea["native_identity_axis_preserved"] is True and ea["nonfinite_active_states"]==0,"identity finite")
 req(render["producer_counts"]=={"fixed":158559,"moving":4210,"floating":0,"fluid_initial":31658,"total_initial":194427,"solver_dimension":3,"data2d":False},"counts"); req(render["render_report"]["numerical_precision_status"]=="not accepted","precision status")
 scopes=upstream["producer_scope_roles"]; req(scopes["canonical_native_request_condition_sha256"]==CAN and scopes["native_source_plan_field_present"] is True and scopes["native_source_plan_field_sha256"]==CAN,"canonical role"); req(scopes["actual_converter_legacy_scope_sha256"]==LEG and scopes["bed_source_definition_sha256"]==SRC,"scope roles"); req(scopes["scope_equality_claimed"] is False and scopes["roles_are_distinct"] is True,"scope separation")
 req(len(png["producer_attested_contact_sheets"])==34,"contact count"); req([x["index"] for x in png["producer_attested_contact_sheets"]]==list(range(34)),"contact indices"); req(all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contact review")
 req(len(png["producer_attested_keyframes"])==9,"keyframe count"); req([x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY,"keyframe indices"); req(all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keyframe review")
 req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer PNG hashes"); req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
 bed=close["bed_diagnostic"]; req(bed["one_dp_below_count_all_frames"]==0 and bed["two_dp_below_count_all_frames"]==0,"bed bins"); req(bed["strict_container_guarantee"] is False and bed["sub_dp_penetration_claim"] is False,"bed limits")
 dec=visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False,"visual decision"); req(dec["strict_container_guarantee"] is False and dec["sub_dp_penetration_absence_claim"] is False and dec["numerical_precision_accepted"] is False,"visual limits"); req(dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
 io=render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False,"payload isolation"); req(upstream["main_qi"]["stage1_QI_full_native_identity_and_state_verified"] is True,"main QI")
 print("fresh203 M090/T080 metadata and personal visual handoff validation PASS"); print("package="+str(ROOT)); print("reviewed=34 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__=="__main__": main()
