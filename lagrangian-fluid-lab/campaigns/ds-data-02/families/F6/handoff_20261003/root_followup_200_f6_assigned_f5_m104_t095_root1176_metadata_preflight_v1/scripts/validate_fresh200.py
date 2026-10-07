#!/usr/bin/env python3
"""Read-only fresh200 preflight validator; no scientific payload IO."""
import hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]; d=json.loads((ROOT/"metadata/preflight.json").read_text()); BAD={".h5",".bi4",".csv",".dat",".vtk"}
def sha(p):
 h=hashlib.sha256();
 with open(p,"rb") as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def fail(x):raise SystemExit("FAIL: "+x)
assert d["schema"]=="ds02.f6.fresh200.f5.metadata-preflight.v1" and d["package_id"]=="fresh200"
assert d["assigned_family"]=="F6" and d["physical_family"]=="F5"
assert d["case_id"]=="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M104_T095_NEXT34" and d["physical_case_id"]=="F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T095"
p=d["scientific_payload_policy"]; assert not p["payloads_read"] and not p["payloads_hashed"] and not p["payloads_copied"]
for r in d["metadata_refs"]:
 q=pathlib.Path(r["path"]);
 if q.suffix.lower() in BAD:fail("payload ref "+str(q))
 if not q.is_file():fail("missing "+str(q))
 if q.stat().st_size!=r["bytes"] or sha(q)!=r["sha256"]:fail("metadata drift "+str(q))
c=d["actual_input_contract"]; assert c["expected_frames"]==801 and c["expected_particles"]==194427 and c["expected_contact_sheets"]==34 and c["keyframe_indices"]==[0,100,200,300,400,500,600,700,800]
assert c["expected_counts"]==c["actual_counts"] and c["actual_counts"]["solver_dimension"]==3 and c["typed_time"]["frames"]==801 and c["typed_time"]["strictly_increasing"]
x=c["xmf_structure"]; assert x["grid_count"]==802 and x["uniform_frames"]==801 and x["topology_count"]==801 and x["topology_elements"]==["194427"] and x["geometry_count"]==801 and x["geometry_types"]==["XYZ"] and "velocity" in x["vector_attributes"] and not x["dataitem_hdf_values_read"]
r=d["scope_roles"]; assert r["canonical"]["value"]=="83831d4fc2150e22f79c5bc6d4a6e655c2ab6c43b517288c531b490ed3563877" and r["typed_legacy"]["value"]=="c7a06c6bdcbf126b3758317aabda1815621e3b2368d9ad546c14ef95d4e0aae1" and r["bed_source_definition"]["definition_sha256"]=="c4e0a0ad9924c53eba206011b0bac762a8babc706fc1bf101e1ca2e1f6450965"
assert not r["native_plan"]["condition"]["present"] and r["native_plan"]["physical"]["present"] and not r["typed_plan"]["condition"]["present"] and not r["xmf_plan"]["condition"]["present"] and r["xmf_plan"]["physical"]["present"] and r["roles_are_namespaced_and_not_collapsed"]
rt=d["runtime_observation"]["receipt"]; assert rt["status"]=="running" and rt["returncode"] is None and rt["mutable_source"]
assert d["render_state"]["status"]=="running" and not d["render_state"]["atomic_publish"] and not d["render_state"]["personally_viewed_png"]
assert d["future_output_hashes"]=={"render_receipt_sha256":None,"render_report_sha256":None,"published_png_sha256":None}
assert d["review_limits"]["case_credit"]==0 and not d["review_limits"]["q_n_granted"] and not d["review_limits"]["q_e_granted"]
print("PASS fresh200: immutable metadata preflight, scopes, XMF structure, running receipt snapshot; no terminal/visual claim")
