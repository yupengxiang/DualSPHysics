#!/usr/bin/env python3
from datetime import datetime, timezone
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
CASE='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M114_T085_NEXT34'; PHYS='F5_COMPACT_RUNUP_RECOVERY_C082S1_M114_T085'; ATT='root-stage1-f5-m114_t085-actual1140-bed0-full801-original116023-frozen-progress-root1164'
CAN='859a739d1f7159e033b57f1842fc18264fcf44140f78483469e11ff4f05aefba'; XMF='8849139c088a0807e52f796edbf4b0ecaeafa3ac49c80870ced7ad3fcf528eba'; LEGACY='e0074c15b562c6e7eb4d34e3da768b91e522f4f977385b0b972b1a16f26e7360'; SDEF='8849139c088a0807e52f796edbf4b0ecaeafa3ac49c80870ced7ad3fcf528eba'; QI='0838f7b98c889c2b61da61c24bef1aaa6187a47e87359bb94409744076c29416'; KEY=[0, 100, 200, 300, 400, 500, 600, 700, 800]
EXPECTED={"README.md","metadata/actual-render-metadata.json","metadata/physical-stage-closure.json","metadata/png-visual-evidence.json","metadata/upstream-evidence.json","metadata/visual-decision.json","scripts/validate_fresh211.py"}
def ld(r): return json.loads((ROOT/r).read_text())
def dg(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
 return h.hexdigest()
def ok(x,m):
 if not x: raise AssertionError(m)
def main():
 m=ld("manifest.json"); ok(m["source_only"] and m["manifest_excludes_self"],"manifest"); ok(m["assigned_family_id"]=="F5" and not m["science_payloads_copied"] and not m["scientific_jobs_started_by_source_agent"] and not m["shared_state_written_by_source_agent"],"isolation")
 es={x["path"]:x for x in m["files"]}; ok(set(es)==EXPECTED,"files")
 for r,e in es.items(): p=ROOT/r; ok(p.is_file(),"missing "+r); ok(p.stat().st_size==e["bytes"],"bytes "+r); ok(dg(p)==e["sha256"],"sha "+r)
 r=ld("metadata/actual-render-metadata.json"); c=ld("metadata/physical-stage-closure.json"); p=ld("metadata/png-visual-evidence.json"); u=ld("metadata/upstream-evidence.json"); v=ld("metadata/visual-decision.json")
 for d in (r,c,p,u,v): ok(d["case_id"]==CASE and d["physical_case_id"]==PHYS,"identity")
 ok(r["attempt_id"]==ATT and r["execution_receipt"]["status"]=="completed" and r["execution_receipt"]["returncode"]==0,"receipt"); ok(r["publish_receipt"]["status"]=="published_after_atomic_rename","publish")
 e=r["expected_and_actual"]; ok(e["frames"]==801 and e["source_frames"]==801 and e["particles"]==194427 and e["fluid_initial_UIDs"]==31658 and e["contact_sheets"]==34 and e["keyframe_indices"]==KEY,"dimensions"); ok(e["all_frames_rendered"] and e["actual_times_preserved_exactly"] and e["native_identity_axis_preserved"] and e["nonfinite_active_states"]==0,"state")
 ok(r["producer_counts"]=={"data2d":False,"fixed":158559,"moving":4210,"floating":0,"fluid_initial":31658,"total_initial":194427,"solver_dimension":3},"counts"); ok(r["render_report"]["numerical_precision_status"]=="not accepted","precision")
 s=r["scope_roles"]; ok(s["native_request_and_actual_converter_canonical"]==CAN and s["typed_legacy_scope"]==LEGACY,"native/legacy scope"); ok(not s["native_source_plan_condition_field_present"] and s["native_source_plan_condition_sha256"] is None and s["native_source_plan_physical_condition_field_present"] and s["native_source_plan_physical_condition_sha256"]==CAN,"native masks"); ok(not s["xmf_source_plan_condition_field_present"] and s["xmf_source_plan_condition_sha256"] is None and s["xmf_source_plan_physical_condition_field_present"] and s["xmf_source_plan_physical_condition_sha256"]==XMF and s["xmf_source_plan_physical_condition_has_SourceDef_role"] and not s["xmf_source_plan_physical_condition_has_native_canonical_role"],"XMF masks"); ok(s["bed_declared_source_plan_file_sha256"]==SDEF and s["roles_are_distinct"] and not s["scope_equality_claimed"],"bed scope")
 ok(len(p["producer_attested_contact_sheets"])==34 and [x["index"] for x in p["producer_attested_contact_sheets"]]==list(range(34)) and all(x["reviewed"] for x in p["producer_attested_contact_sheets"]),"contacts"); ok(len(p["producer_attested_keyframes"])==9 and [x["frame_index"] for x in p["producer_attested_keyframes"]]==KEY and all(x["reviewed"] for x in p["producer_attested_keyframes"]),"keys"); ok(all(re.fullmatch(r"[0-9a-f]{64}",x["sha256"]) for x in p["producer_attested_contact_sheets"]+p["producer_attested_keyframes"]),"png hashes"); ok(not p["review_coverage"]["source_agent_computed_png_hashes"],"png provenance")
 d=v["decision"]; ok(d["standalone_first_stage_visual_approved"] and not d["severe_visual_failure"] and not d["needs_root_image_intervention"] and d["weak_or_localized_response_limit"],"visual"); ok(not d["numerical_precision_accepted"] and not d["q_n_granted"] and not d["q_e_granted"] and d["independent_case_count_increment"]==0,"credit")
 ok(u["main_qi"]["sha256"]==QI and dg(Path(u["main_qi"]["path"]))==QI and u["main_qi"]["all801_geometry_velocity_N3_times_UID_finite_verified"] and u["main_qi"]["all_native_UIDs_active_each_frame"],"QI")
 rr=datetime.fromisoformat(r["personal_review_scope"]["reviewed_at_utc"].replace("Z","+00:00")); ff=datetime.fromisoformat(r["execution_receipt"]["finished_at_utc"].replace("Z","+00:00")); ok(rr>=ff and rr<=datetime.now(timezone.utc),"review time"); ok(v["reviewer"]["model"]=="gpt-5.6-luna/max" and not v["reviewer"]["recursive_delegation"],"model")
 print("fresh211 F5 M114/T085 metadata and personal visual handoff validation PASS"); print("package="+str(ROOT)); print("reviewed=34 contact sheets + 9 keyframes; case_credit_increment=0")
if __name__=="__main__": main()
