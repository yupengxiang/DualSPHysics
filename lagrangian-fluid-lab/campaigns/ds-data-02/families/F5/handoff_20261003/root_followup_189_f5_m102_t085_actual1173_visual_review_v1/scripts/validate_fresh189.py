#!/usr/bin/env python3
"""Validate F5 fresh189 metadata and producer-rendered PNG evidence only.

This validator never opens H5, BI4, CSV, DAT, VTK, solver output, or any
science array. It checks JSON/XML producer metadata and PNG derivatives.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES={".h5",".bi4",".csv",".dat",".vtk",".vtu",".hdf5"}
def check(c,m):
    if not c: raise SystemExit("FAIL: "+m)
def load(rel): return json.loads((PKG/rel).read_text())
def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def metadata_path(p, role):
    p=Path(p); check(p.suffix.lower() not in SCIENCE_SUFFIXES, "science suffix in metadata role "+role)
    check(p.is_file(), "missing producer metadata "+role+": "+str(p))
    return p

actual=load("metadata/actual1173-render-metadata.json")
png=load("metadata/png-visual-evidence.json")
closure=load("metadata/physical-stage-closure.json")
decision=load("metadata/visual-decision.json")
upstream=load("metadata/upstream-evidence.json")
manifest=load("manifest.json")

for role, item in upstream["upstream_chain"].items():
    p=metadata_path(item["path"],role)
    check(digest(p)==item["sha256"], "upstream metadata hash "+role)
for role in ("execution_receipt","render_report","publish_receipt"):
    p=metadata_path(actual[role]["path"],role)
    check(digest(p)==actual[role]["sha256"], "render metadata hash "+role)

receipt=json.loads(Path(actual["execution_receipt"]["path"]).read_text())
report=json.loads(Path(actual["render_report"]["path"]).read_text())
publish=json.loads(Path(actual["publish_receipt"]["path"]).read_text())
check(actual["attempt_id"]=="root-stage1-f5-m102_t085-actual1171-bed0-full801-original116023-frozen-progress-root1173","attempt identity")
check(receipt.get("status")=="completed" and receipt.get("returncode")==0,"terminal render receipt")
check(report.get("frames")==801 and report.get("source_frames")==801 and report.get("all_frames_rendered") is True,"full render metadata")
check(report.get("actual_times_preserved_exactly") is True and report.get("native_identity_axis_preserved") is True,"time/identity metadata")
check(report.get("nonfinite_active_states")==0,"nonfinite metadata")
check(report.get("numerical_precision_status")=="not accepted","precision status")
check(publish.get("status")=="published_after_atomic_rename","publish status")
check(publish.get("report_sha256_after_rebind")==actual["render_report"]["sha256"],"publish report binding")
check(publish.get("renderer_delegated_to_root023") is True,"renderer provenance")

check(len(png["contact_sheets"])==34 and png["all_actual_contact_sheets_reviewed"] is True,"contact review")
check(png["keyframe_indices"]==[0,100,200,300,400,500,600,700,800],"keyframe set")
check(len(png["keyframes"])==9 and png["all_nine_keyframes_reviewed"] is True,"keyframe review")
for item in png["contact_sheets"]+png["keyframes"]:
    p=Path(item["path"]); check(p.is_file(),"missing PNG "+str(p))
    check(p.stat().st_size==item["bytes"],"PNG size changed "+str(p))
    check(digest(p)==item["sha256"],"PNG hash changed "+str(p))

bed_path=metadata_path(next(v["path"] for k,v in upstream["upstream_chain"].items() if k=="full801_bed_report"),"full801_bed_report")
bed=json.loads(bed_path.read_text()); frames=bed.get("frame_reports",[])
check(len(frames)==801,"bed report frame count")
for f in frames:
    check(f["current_valid_type3_fluid_count"]==31658,"bed fluid denominator")
    check(f["nonfinite_position_current_fluid_count"]==0 and f["nonfinite_mass_current_fluid_count"]==0,"bed finite counts")
    check(f["uid_tracking"]["missing_initial_uid"]["count"]==0 and f["uid_tracking"]["unexpected_current_uid"]["count"]==0,"bed UID counts")
    check(f["bed_domain"]["x_outside_exact_profile_domain_count"]==0 and f["bed_domain"]["y_outside_actual_bed_footprint_with_x_in_domain_count"]==0,"bed footprint counts")
    check(f["penetration"]["one_dp"]["count"]==0 and f["penetration"]["two_dp"]["count"]==0,"diagnostic bins")
check(closure["dynamic_bed_summary"]["sub_dp_depth_inferred"] is False,"sub-DP interpretation")
check(closure["dynamic_bed_summary"]["precision_acceptance_not_inferred"] is True,"precision interpretation")
check(decision["decision"]["standalone_first_stage_visual_approved"] is True,"visual decision")
check(decision["decision"]["strict_container_guarantee"] is False and decision["decision"]["numerical_precision_accepted"] is False,"visual limits")
check(decision["decision"]["independent_case_count_increment"]==0 and decision["decision"]["root_global_credit_written"] is False,"credit gate")
check(actual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_read"] is False and actual["source_agent_science_payload_io"]["raw_h5_bi4_csv_dat_vtk_hash"] is False,"source payload boundary")
check(upstream["scope_roles"]["roles_remain_distinct"] is True and upstream["scope_roles"]["cross_resolution_claim"] is False,"scope separation")

listed={x["path"]:x for x in manifest["files"]}
for rel in ["README.md","metadata/actual1173-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh189.py"]:
    p=PKG/rel; check(p.is_file(),"package file "+rel); check(rel in listed,"manifest entry "+rel)
    check(p.stat().st_size==listed[rel]["bytes"],"manifest size "+rel); check(digest(p)==listed[rel]["sha256"],"manifest hash "+rel)
check(manifest["manifest_excludes_self"] is True and manifest["source_only"] is True,"manifest guards")
print("PASS fresh189: M102_T085 Root1173 34 contacts + 9 keyframes; metadata/PNG only")
print("Standalone first-stage visual approval; precision/sub-DP/strict-container/Q-N/case credit remain false")
