#!/usr/bin/env python3
"""Metadata-only validator for fresh202; never opens producer science payloads."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M098_T085_NEXT34"
PHYS="F5_COMPACT_RUNUP_RECOVERY_C082S1_M098_T085"
ATTEMPT="root-stage1-f5-m098_t085-actual1112-bed0-full801-original116023-frozen-progress-root1156"
CAN="4948403fe1511a43b1d7b775382b2c2c8524a1af4059885f55b3f840f2a2fde0"
LEG="b1b1c4526657e519940751eca1a1bb0c944dc293284e0949e1762089d13f4cb3"
SRC="d9f9ef7a870dfb8ccf2d273f6f888c1f457e9110edcf15bcd19dbfdf011d73ba"
KEY=[0,100,200,300,400,500,600,700,800]
def req(x,m):
    if not x: raise AssertionError(m)
def load(n): return json.loads((ROOT/"metadata"/n).read_text())
def dg(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    man=json.loads((ROOT/"manifest.json").read_text())
    for k in ("source_only","manifest_excludes_self"):
        req(man[k] is True,k)
    for k in ("science_payloads_copied","scientific_jobs_started_by_source_agent","shared_state_written_by_source_agent"):
        req(man[k] is False,k)
    entries={x["path"]:x for x in man["files"]}
    expected={"README.md","metadata/actual-render-metadata.json","metadata/png-visual-evidence.json","metadata/physical-stage-closure.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh202.py"}
    req(set(entries)==expected,"package file set")
    for rel,e in entries.items():
        p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(dg(p)==e["sha256"],"hash "+rel)
    render=load("actual-render-metadata.json"); png=load("png-visual-evidence.json"); close=load("physical-stage-closure.json"); upstream=load("upstream-evidence.json"); visual=load("visual-decision.json")
    for d in (render,png,close,upstream,visual): req(d["case_id"]==CASE,"case"); req(d["physical_case_id"]==PHYS,"physical case")
    req(render["attempt_id"]==ATTEMPT,"attempt"); req(render["execution_receipt"]["status"]=="completed" and render["execution_receipt"]["returncode"]==0,"execution"); req(render["publish_receipt"]["status"]=="published_after_atomic_rename","publish")
    e=render["expected_and_actual"]; req(e["frames"]==801 and e["source_frames"]==801 and e["particles"]==194427 and e["contact_sheets"]==34,"render dimensions"); req(e["keyframe_indices"]==KEY and e["all_frames_rendered"] is True and e["actual_times_preserved_exactly"] is True,"frame closure"); req(e["native_identity_axis_preserved"] is True and e["nonfinite_active_states"]==0,"identity finite")
    req(render["producer_counts"]=={"fixed":158559,"moving":4210,"floating":0,"fluid_initial":31658,"total_initial":194427,"solver_dimension":3,"data2d":False},"counts"); req(render["render_report"]["numerical_precision_status"]=="not accepted","precision status")
    scopes=upstream["producer_scope_roles"]; req(scopes["canonical_native_request_condition_sha256"]==CAN and scopes["native_source_plan_field_present"] is True and scopes["native_source_plan_field_sha256"]==CAN,"canonical scope"); req(scopes["actual_converter_legacy_scope_sha256"]==LEG and scopes["bed_source_definition_sha256"]==SRC,"role scopes"); req(scopes["scope_equality_claimed"] is False,"scope equality")
    req(len(png["producer_attested_contact_sheets"])==34 and [x["index"] for x in png["producer_attested_contact_sheets"]]==list(range(34)) and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts"); req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keyframes")
    req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer PNG hashes"); req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
    req(close["container_or_bed_diagnostic"]["strict_container_guarantee"] is False and close["container_or_bed_diagnostic"]["sub_dp_penetration_claim"] is False,"container limits"); req(close["container_or_bed_diagnostic"]["one_dp_below_count_all_frames"]==0 and close["container_or_bed_diagnostic"]["two_dp_below_count_all_frames"]==0,"bed metadata")
    dec=visual["decision"]; req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False,"visual decision"); req(dec["strict_container_guarantee"] is False and dec["sub_dp_penetration_absence_claim"] is False and dec["numerical_precision_accepted"] is False,"visual limits"); req(dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
    io=render["source_agent_science_payload_io"]; req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False,"payload isolation"); req(upstream["main_qi"]["stage1_QI_full_native_identity_and_state_verified"] is True,"main QI")
    print("fresh202 M098/T085 metadata and personal visual handoff validation PASS")
    print("package="+str(ROOT))
    print("case=M098/T085 frames=801 particles=194427 contacts=34 keyframes=9")
if __name__=="__main__": main()
