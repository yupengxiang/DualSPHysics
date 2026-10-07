#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh199; never opens science payloads."""
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYS="F5_COMPACT_RUNUP_RECOVERY_C082S1_M105_T090"
CAN="723086161aec499a8977dfb457b9cd0a5b380bc6c78c44cf6fcd9f5639d9df80"
LEG="3e6efe94e0a242645cf49a7ea0898e80b4878c94dc6771b974c18eb129d1a17e"
HIST="3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
DEF="47f948306970a3f97e3273bd117b1bab7ba3d00017572cd74764cd3ee2cb4f15"
ATTEMPT="root-stage1-f5-m105_t090-actual1172-bed0-full801-original116023-frozen-progress-root1182"
KEY=[0,100,200,300,400,500,600,700,800]
def req(x,m):
    if not x: raise AssertionError(m)
def load(n): return json.loads((ROOT/"metadata"/n).read_text())
def dg(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    man=json.loads((ROOT/"manifest.json").read_text())
    req(man["source_only"] is True,"source_only"); req(man["science_payloads_copied"] is False,"payload copied")
    req(man["scientific_jobs_started_by_source_agent"] is False,"job started"); req(man["shared_state_written_by_source_agent"] is False,"shared state")
    req(man["manifest_excludes_self"] is True,"manifest self")
    entries={x["path"]:x for x in man["files"]}
    expected={"README.md","metadata/actual-render-metadata.json","metadata/bed-audit-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh199.py"}
    req(set(entries)==expected,"package file set"); req("manifest.json" not in entries,"manifest self-listed")
    for rel,e in entries.items():
        p=ROOT/rel; req(p.is_file(),"missing "+rel); req(p.stat().st_size==e["bytes"],"bytes "+rel); req(dg(p)==e["sha256"],"hash "+rel)
    render=load("actual-render-metadata.json"); bed=load("bed-audit-metadata.json"); close=load("physical-stage-closure.json"); png=load("png-visual-evidence.json"); visual=load("visual-decision.json")
    for d in (render,bed,close,png,visual):
        req(d["case_id"]==CASE,"case identity"); req(d["physical_case_id"]==PHYS,"physical identity")
    req(render["attempt_id"]==ATTEMPT,"attempt")
    req(render["execution_receipt"]["status"]=="completed" and render["execution_receipt"]["returncode"]==0,"render receipt")
    req(render["publish_receipt"]["status"]=="published_after_atomic_rename","publish")
    req(render["render_report"]["frames"]==801 and render["render_report"]["source_frames"]==801 and render["render_report"]["all_frames_rendered"] is True,"801 render")
    req(render["producer_counts"]=={"total_particles":194427,"fixed_particles":158559,"moving_particles":4210,"fluid_particles":31658,"floating_particles":0,"solver_dimension":3,"data2d":False},"counts")
    s=render["scope_roles"]
    req(s["canonical_native_physical_condition_sha256"]==CAN,"canonical")
    req(s["typed_converter_actual_legacy_scope_sha256"]==LEG and s["historical_source_h5_scope_sha256"]==HIST,"legacy roles")
    req(s["native_request_source_plan_field_present"] is False and s["native_request_source_plan_physical_condition_sha256"] is None and s["actual_native_source_plan_file_sha256"] is None,"native plan absence")
    req(s["xmf_source_plan_condition_field_present"] is True and s["xmf_source_plan_condition_sha256"]==DEF,"xmf plan")
    req(s["source_definition_and_bed_declared_plan_sha256"]==DEF and s["canonical_owner_and_SourceDef_are_distinct"] is True,"SourceDef role")
    io=render["source_agent_science_payload_io"]
    req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False,"raw science IO")
    req(bed["diagnostic_only"] is True and bed["full16_authorized_in_source_report"] is False and bed["q_n_status"]=="not_granted","bed gate")
    req(bed["scan"]["frames_scanned"]==801 and bed["scan"]["particle_axis_count"]==194427 and bed["scan"]["initial_fluid_uid_count"]==31658,"bed scan")
    ad=bed["all_frame_diagnostics"]
    req(ad["missing_initial_uid_max"]==0 and ad["unexpected_current_uid_max"]==0,"UID")
    req(ad["nonfinite_mass_current_fluid_max"]==0 and ad["nonfinite_position_current_fluid_max"]==0,"finite")
    req(ad["one_dp_count_max"]==0 and ad["two_dp_count_max"]==0 and ad["zero_bins_are_not_sub_dp_depth_proof"] is True,"diagnostic bins")
    req(len(png["producer_attested_contact_sheets"])==34 and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
    req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in png["producer_attested_keyframes"]),"keyframes")
    req(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
    dec=visual["decision"]
    req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["weak_wave_only"] is True,"visual decision")
    req(dec["large_inundation_or_runup_claim"] is False and dec["strict_container_guarantee"] is False and dec["bed_zero_bins_are_sub_dp_depth_proof"] is False,"visual limits")
    req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["independent_case_count_increment"]==0,"credit/precision")
    vs=visual["scope_and_negative_evidence"]
    req(vs["native_request_source_plan_field_present"] is False and vs["native_request_source_plan_condition_sha256"] is None,"visual native plan absence")
    req(close["native_source_plan_semantics"]["present_in_native_request"] is False and close["native_source_plan_semantics"]["value"] is None and close["native_source_plan_semantics"]["absence_preserved"] is True,"closure plan absence")
    print("fresh199 metadata/visual handoff validation PASS")
    print("package="+str(ROOT))
    print("contacts=34 keyframes=9 frames=801 particles=194427 fluid=31658")
if __name__=="__main__": main()
