#!/usr/bin/env python3
"""Metadata-only validator for fresh200; never opens producer science payloads."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
CASE="F2_STAGE1_FIRST48_EXPANSION_RX061_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT105"
ATTEMPT="root-stage1-f2-rx061-rot105-actual1144-full401-116-023-nvme-hard2gib-root1154"
CAN="fe08f5271b43f4658c757daed157c1eaf6600236d3b43dee2f5869af80ac058b"
LEG="c826ec6243784b178c74db69b1ae1da31c3e63ad4b2d30ee7402319134705926"
KEY=[0,50,100,150,200,250,300,350,400]
def req(x,m):
    if not x: raise AssertionError(m)
def load(n): return json.loads((ROOT/"metadata"/n).read_text())
def dg(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    man=json.loads((ROOT/"manifest.json").read_text())
    req(man["source_only"] is True,"source_only")
    req(man["science_payloads_copied"] is False,"payload copied")
    req(man["scientific_jobs_started_by_source_agent"] is False,"job started")
    req(man["shared_state_written_by_source_agent"] is False,"shared state")
    req(man["manifest_excludes_self"] is True,"manifest self")
    entries={x["path"]:x for x in man["files"]}
    expected={"README.md","metadata/actual-render-metadata.json","metadata/png-visual-evidence.json","metadata/physical-stage-closure.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh200.py"}
    req(set(entries)==expected,"package file set")
    req("manifest.json" not in entries,"manifest self listed")
    for rel,e in entries.items():
        p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(dg(p)==e["sha256"],"hash "+rel)
    render=load("actual-render-metadata.json"); png=load("png-visual-evidence.json"); close=load("physical-stage-closure.json"); upstream=load("upstream-evidence.json"); visual=load("visual-decision.json")
    for d in (render,png,close,upstream,visual):
        req(d["case_id"]==CASE,"case"); req(d["physical_case_id"]==PHYS,"physical case")
    req(render["attempt_id"]==ATTEMPT,"attempt")
    req(render["execution_receipt"]["status"]=="completed" and render["execution_receipt"]["returncode"]==0,"execution")
    req(render["publish_receipt"]["status"]=="published_after_atomic_rename","publish")
    e=render["expected_and_actual"]
    req(e["frames"]==401 and e["source_frames"]==401 and e["particles"]==418104 and e["contact_sheets"]==17,"render dimensions")
    req(e["keyframe_indices"]==KEY and e["all_frames_rendered"] is True and e["actual_times_preserved_exactly"] is True,"frame closure")
    c=render["producer_counts"]
    req(c=={"fixed":372840,"moving":24150,"floating":0,"fluid_initial":21114,"total_initial":418104,"solver_dimension":3,"data2d":False},"counts")
    req(render["render_report"]["nonfinite_active_states"]==0,"nonfinite")
    req(render["render_report"]["numerical_precision_status"]=="not accepted","precision status")
    life=close["typed_lifecycle"]
    req(life["initial_fluid_uids"]==21114 and life["final_missing_particles"]==9 and life["first_missing_frame"]==165 and life["frames_with_any_missing_particle"]==236 and life["cumulative_particle_frame_omissions"]==1330,"omission evidence")
    req(life["unknown_missing_locations_states_causes"] is True and life["no_missing_particle_state_reconstructed"] is True,"unknown omission semantics")
    scopes=upstream["producer_scope_roles"]
    req(scopes["canonical_native_request_condition_sha256"]==CAN and scopes["native_source_plan_field_present"] is True and scopes["native_source_plan_field_sha256"]==CAN,"canonical scope")
    req(scopes["actual_converter_legacy_scope_sha256"]==LEG and scopes["xmf_source_plan_field_present"] is False and scopes["xmf_source_plan_field_sha256"] is None,"legacy scope separation")
    req(scopes["scope_equality_claimed"] is False,"scope equality")
    req(len(png["producer_attested_contact_sheets"])==17 and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
    req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keyframes")
    req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
    req(close["container_or_bed_diagnostic"]["strict_container_guarantee"] is False and close["container_or_bed_diagnostic"]["sub_dp_penetration_claim"] is False,"container limits")
    dec=visual["decision"]
    req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["needs_root_image_intervention"] is False,"visual decision")
    req(dec["strict_container_guarantee"] is False and dec["sub_dp_penetration_absence_claim"] is False and dec["numerical_precision_accepted"] is False,"visual limits")
    req(dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["independent_case_count_increment"]==0,"credit")
    io=render["source_agent_science_payload_io"]
    req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False and io["scientific_job_started"] is False,"payload isolation")
    req(upstream["main_qi"]["stage1_QI_full_native_identity_and_state_verified"] is True,"main QI")
    print("fresh200 metadata/visual handoff validation PASS")
    print("package="+str(ROOT))
    print("case=F2 RX061/ROT105 frames=401 particles=418104 contacts=17 keyframes=9 final_missing_fluid=9")
if __name__=="__main__": main()
