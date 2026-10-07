#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh197."""
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYS="F5_COMPACT_RUNUP_RECOVERY_C082S1_M105_T100"
CAN="00b37ae025988a4eff9e2394f4be3863112630e8374131619c65365c66b5caff"
LEG="bdc72a61c90149c7ca7d88b4fd1928498a25b2f3cdda7bcae7111bf5e3a7f9fc"
HIST="3cd1ceab16be11428bbc1011a1b4e297c384d8c7926432c222c254064744ccd0"
DEF="39f76c74a18c4d7e35763f6fe8707cd77741bbbdafc0091aa1a360485201bd6f"
META="26e9780321226eca30fccf5db47579104327a20a18fe8f49d2a2d12be5a0afe3"
KEY=[0,100,200,300,400,500,600,700,800]
def load(n): return json.loads((ROOT/"metadata"/n).read_text())
def dg(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def req(x,m):
    if not x: raise AssertionError(m)
def main():
    man=json.loads((ROOT/"manifest.json").read_text())
    req(man["source_only"] is True,"source_only")
    req(man["science_payloads_copied"] is False,"payload copied")
    req(man["scientific_jobs_started_by_source_agent"] is False,"job started")
    req(man["shared_state_written_by_source_agent"] is False,"shared state")
    req(man["manifest_excludes_self"] is True,"manifest self")
    entries={x["path"]:x for x in man["files"]}
    req("manifest.json" not in entries,"manifest is self-listed")
    expected={"README.md","metadata/actual-render-metadata.json","metadata/bed-audit-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh197.py"}
    req(set(entries)==expected,"package file set")
    for rel,e in entries.items():
        p=ROOT/rel
        req(p.is_file(),"missing "+rel)
        req(p.stat().st_size==e["bytes"],"bytes "+rel)
        req(dg(p)==e["sha256"],"hash "+rel)
    render=load("actual-render-metadata.json"); bed=load("bed-audit-metadata.json"); close=load("physical-stage-closure.json"); png=load("png-visual-evidence.json"); visual=load("visual-decision.json")
    for d in [render,bed,close,png,visual]:
        req(d["case_id"]==CASE,"case identity")
        req(d["physical_case_id"]==PHYS,"physical identity")
    req(render["attempt_id"].endswith("root1183"),"render attempt")
    req(render["execution_receipt"]["status"]=="completed" and render["execution_receipt"]["returncode"]==0,"render receipt")
    req(render["publish_receipt"]["status"]=="published_after_atomic_rename","publish")
    req(render["render_report"]["frames"]==801 and render["render_report"]["source_frames"]==801 and render["render_report"]["all_frames_rendered"] is True,"801 render")
    req(render["producer_counts"]=={"total_particles":194427,"fixed_particles":158559,"moving_particles":4210,"fluid_particles":31658,"floating_particles":0,"solver_dimension":3,"data2d":False},"counts")
    s=render["scope_roles"]
    req(s["canonical_native_physical_condition_sha256"]==CAN,"canonical")
    req(s["typed_converter_actual_legacy_scope_sha256"]==LEG,"legacy")
    req(s["historical_source_h5_scope_sha256"]==HIST,"historical")
    req(s["source_definition_and_bed_declared_plan_sha256"]==DEF,"SourceDef")
    req(s["native_request_source_plan_physical_condition_sha256"] is None and s["native_request_source_plan_field_present"] is False and s["native_source_plan_absence_preserved"] is True,"native field absence")
    req(s["fresh159_metadata_only_plan_sha256"]==META,"metadata plan")
    io=render["source_agent_science_payload_io"]
    req(io["raw_h5_bi4_csv_dat_vtk_read"] is False and io["raw_h5_bi4_csv_dat_vtk_hash"] is False,"raw science IO")
    req(bed["diagnostic_only"] is True and bed["full16_authorized_in_source_report"] is False and bed["q_n_status"]=="not_granted","bed gate")
    req(bed["scan"]["frames_scanned"]==801 and bed["scan"]["particle_axis_count"]==194427,"bed scan")
    ad=bed["all_frame_diagnostics"]
    req(ad["missing_initial_uid_max"]==0 and ad["unexpected_current_uid_max"]==0,"UID")
    req(ad["nonfinite_mass_current_fluid_max"]==0 and ad["nonfinite_position_current_fluid_max"]==0,"finite")
    req(ad["one_dp_count_max"]==0 and ad["two_dp_count_max"]==0 and ad["zero_bins_are_not_sub_dp_depth_proof"] is True,"diagnostic bins")
    req(len(png["producer_attested_contact_sheets"])==34 and all(x["reviewed"] for x in png["producer_attested_contact_sheets"]),"contacts")
    req(len(png["producer_attested_keyframes"])==9 and [x["frame_index"] for x in png["producer_attested_keyframes"]]==KEY,"keyframes")
    req(all(x["reviewed"] and re.fullmatch("[0-9a-f]{64}",x["sha256"]) for x in png["producer_attested_contact_sheets"]+png["producer_attested_keyframes"]),"producer PNG hashes")
    req(png["review_coverage"]["source_agent_computed_png_hashes"] is False,"source PNG hash")
    dec=visual["decision"]
    req(dec["standalone_first_stage_visual_approved"] is True and dec["severe_visual_failure"] is False and dec["weak_wave_only"] is True,"visual decision")
    req(dec["large_inundation_or_runup_claim"] is False and dec["strict_container_guarantee"] is False and dec["bed_zero_bins_are_sub_dp_depth_proof"] is False,"visual limits")
    req(dec["numerical_precision_accepted"] is False and dec["q_n_granted"] is False and dec["independent_case_count_increment"]==0,"credit/precision")
    req(visual["scope_and_negative_evidence"]["native_source_plan_field_absence_preserved"] is True,"scope absence")
    req(visual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_read"] is False and visual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_hash"] is False,"visual raw IO")
    req(close["native_source_plan_semantics"]["present_in_native_request"] is False and close["native_source_plan_semantics"]["value"] is None,"closure plan")
    print("fresh197 metadata/visual handoff validation PASS")
    print("package="+str(ROOT))
    print("contacts=34 keyframes=9 frames=801 particles=194427 fluid=31658")
if __name__=="__main__":
    main()
