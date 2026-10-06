#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path

WT=Path("/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics")
FAM=WT/"lagrangian-fluid-lab/campaigns/ds-data-02/families/F3"
HAND=FAM/"handoff_20261003"
SRC066=HAND/"root_followup_066_f3_four_corner_native706_typed_nvme_source_v1"
SRC080=HAND/"root_followup_080_f3_actual_typed267_xmf_render_v1"
OUT=HAND/"root_followup_081_f3_four_corner_typed_xmf_source_v1"
IT=Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
R728=IT/"lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_four_actual706_native_corners_full836_NVMe_typed_728"
R729=IT/"lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_typed728_afterF6_718_terminal_CPU2_global2_controller_729"
DATA=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FRESH="fresh067-corner706"
CASES=["F3_STAGE1_DP006_P0800_AY0250","F3_STAGE1_DP006_P0800_AY0750","F3_STAGE1_DP006_P1200_AY0250","F3_STAGE1_DP006_P1200_AY0750"]
BAD={".bi4",".ibi4",".csv",".dat",".h5",".hdf5",".vtk",".npy",".npz"}
PYTHON=IT/"lagrangian-fluid-lab/.venv/bin/python"
RUNTIME=IT/"lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT=IT/"lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
ROOT142=IT/"lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142"
RESOURCE=IT/"lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
PV=Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
DECODER=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
RENDER_ORIGIN=IT/"lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
RENDER_SHA="5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"

def load(p): return json.loads(Path(p).read_text())
def dump(p,x):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def cp(a,b):
 b=Path(b); b.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(a,b)
def digest(p):
 p=Path(p)
 if p.suffix.lower() in BAD: raise AssertionError("payload hash refused: "+str(p))
 h=hashlib.sha256()
 with p.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
 return h.hexdigest()
def close(paths):
 out={}
 for p in sorted({Path(x) for x in paths},key=str):
  if p.suffix.lower() in BAD: raise AssertionError("payload in closure: "+str(p))
  if not p.is_file(): raise AssertionError("missing closure file: "+str(p))
  out[str(p)]=digest(p)
 return out
def info(case):
 rq=R728/(case+"-typed-request.json"); ow=SRC066/"owners"/(case+".json")
 q=load(rq); o=load(ow); root=Path(q["attempt_root"])
 tr=root/"execution-receipt.json"; cr=root/"conversion-report.json"; h5=root/"trajectory.h5"
 status="pending"; rc=None; td={}; rd={}; trs=None; crs=None
 if tr.is_file():
  td=load(tr); status=td.get("status","unknown"); rc=td.get("returncode"); trs=digest(tr)
 if cr.is_file(): rd=load(cr); crs=digest(cr)
 done=status=="completed" and rc==0
 if done:
  assert rd.get("conversion_status")=="completed"
  assert (rd.get("frames"),rd.get("particles"))==(836,179208)
  assert rd.get("solver_dimension",{}).get("solver_dimension")==3
  assert rd.get("partvtk_validation",{}).get("all_passed") is True
  ph=rd["hash_scopes"]["physical_condition"]
  assert ph.get("schema")==q["actual_converter_physical_condition_scope"]["schema"]
  assert ph.get("physical_case_id")==q["physical_case_id"]
  assert rd["hash_scopes"]["physical_condition_sha256"]==q["physical_condition_sha256"]
 nr=q["actual_native_binding"]["native_receipt"]; np=Path(nr["path"]); nd=load(np); ns=digest(np)
 assert (nd.get("status"),nd.get("returncode"))==("completed",0)
 od=OUT/"owners"/(case+".actual-converter-scope.owner.json")
 ud=OUT/"metadata/upstream/root728"/(case+"-typed-request.json")
 cp(ow,od); cp(rq,ud)
 scope=q["actual_converter_physical_condition_scope"]
 return dict(case=case,q=q,o=o,root=root,attempt=q["attempt_id"],tr=tr,cr=cr,h5=h5,status=status,rc=rc,td=td,rd=rd,trs=trs,crs=crs,done=done,np=np,nd=nd,ns=ns,od=od,ud=ud,
  physical=q["physical_case_id"], phash=q["physical_condition_sha256"], shash=q.get("source_physical_condition_sha256",o.get("source_physical_condition_sha256")),
  scope=scope["schema"], scopehash=q["actual_converter_physical_condition_scope_sha256"], h5sha=rd.get("output_sha256") if done else None)

def shape():
 return {"dynamic_scalar":{"dataset_shape":[836,179208],"outshape":"shape[1:]","xmf_dimensions":"179208"},
 "dynamic_vector":{"dataset_shape":[836,179208,3],"field":"velocity","outshape":"shape[1:]","xmf_dimensions":"179208 3"},
 "static_scalar":{"dataset_shape":[179208],"xmf_dimensions":"179208"}}

def main():
 if OUT.exists(): raise SystemExit("refusing existing output "+str(OUT))
 OUT.mkdir(parents=True)
 cp(SRC080/"workers/export_xmf.py",OUT/"workers/export_xmf.py")
 cp(SRC080/"workers/render_native023.py",OUT/"workers/render_native023.py")
 cp(R729/"batch-controller.py",OUT/"metadata/upstream/root729/batch-controller.py")
 cp(ROOT142/"policy-check.json",OUT/"metadata/root142/policy-check.json")
 cp(ROOT142/"source-policy-contract.json",OUT/"metadata/root142/source-policy-contract.json")
 xs=[info(c) for c in CASES]
 worker_sha=digest(OUT/"workers/export_xmf.py"); render_sha=digest(OUT/"workers/render_native023.py")
 dump(OUT/"metadata/contracts/base-binary-contract.json",{"schema":"ds02.f3.fresh067-corner706.base-binary-contract.v1","source_only":True,
  "decoder":{"path":str(DECODER),"sha256":"b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e","hash_source":"Root supplied digest; source builder did not execute or rehash"},
  "partvtk":{"path":str(PARTVTK),"sha256":"62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00","hash_source":"Root supplied digest; typed producer report adopted"}})
 dump(OUT/"metadata/contracts/n3-vector-spec.json",{"schema":"ds02.f3.fresh067-corner706.n3-vector-spec.v1","source_only":True,"semantic_type":"N3","field":"velocity","components":["vx","vy","vz"],"dataset_shape":[836,179208,3],"outshape_rule":"dynamic dataset shape[1:]","xmf_dimensions":"179208 3","preserve_all_native_fields":True})
 dump(OUT/"metadata/contracts/root023-render-contract.json",{"schema":"ds02.f3.fresh067-corner706.root023-render-contract.v1","source_only":True,"renderer_origin":str(RENDER_ORIGIN),"renderer_origin_sha256":RENDER_SHA,"dimension":3,"frames":836,"particles":179208,"frame_selection":"0..835 inclusive; every saved frame","software_offscreen":True,"automatic_native_bounds":True,"fixed_camera_bounds_forbidden":True,"all_native_fields_retained":True,"xmf_vector_shape":"179208 3"})
 dump(OUT/"metadata/contracts/xmf-worker-contract.json",{"schema":"ds02.f3.fresh067-corner706.xmf-worker-contract.v1","source_only":True,"worker":"export_xmf.py","worker_sha256":worker_sha,"producer_scope_schema":"ds-data-02.physical-binding.v1",
  "required_binding_keys":["typed_receipt","native_receipt","bound_metadata_sha256","conversion_report","physical_condition_sha256","producer_scope_schema","physical_case_id","trajectory_h5","expected_frames","physical_window_s","xmf_shape_contract"],
  "preflight_checks":["typed receipt completed/0","native receipt completed/0","bound JSON/source metadata digests close","no raw payload in bound hash map","report physical scope digest/schema/case equals binding","report output_hdf5 equals trajectory_h5","PartVTK producer report passes","dynamic vectors use shape[1:] and N=3"],
  "source_agent_reads_h5":False,"source_agent_reads_bi4_csv_dat_vtk":False})
 dump(OUT/"metadata/runtime-contract.json",{"schema":"ds02.f3.fresh067-corner706.root142-runtime-contract.v1","source_only":True,"disabled":True,"cpu_task_kind":"audit","cpu_threads":2,"launch_owner":"root","max_wall_seconds":14400,
  "runtime_v2":{"path":str(RUNTIME),"sha256":digest(RUNTIME)},"strict_dispatch":{"path":str(STRICT),"sha256":digest(STRICT)},"interpreter":{"path":str(PYTHON),"sha256":digest(PYTHON)},"resource_window":{"path":str(RESOURCE),"sha256":digest(RESOURCE)},"root142_policy":"root_home_floor_no_legacy_dataset_walk_v1","storage_policy":{"home_floor_gib":500,"nvme_staging_limit_bytes":25769803776},"xmf_concurrency_cap":2,"render_concurrency_cap":2})
 dump(OUT/"metadata/lineage-policy.json",{"schema":"ds02.f3.fresh067-corner706.lineage-policy.v1","family_id":"F3","fresh_id":FRESH,"source_only":True,"source_and_actual_scopes_are_distinct":True,"source_and_canonical_hashes_are_distinct":True,"physical_scope":"Root728 actual ds-data-02.physical-binding.v1; no legacy alignment","typed_outputs_are_producer_attestations":True,"h5_bi4_csv_dat_vtk_payloads_read_by_source_builder":False,"jobs_started_by_source_builder":False,"shared_state_modified_by_source_builder":False,"precision_or_qn_claim":"none"})
 rows=[]
 for x in xs:
  rows.append({"case_id":x["case"],"physical_case_id":x["physical"],"attempt_id":x["attempt"],"attempt_root":str(x["root"]),
   "typed_receipt":{"path":str(x["tr"]),"sha256":x["trs"],"exists_at_build":x["tr"].is_file(),"status":x["status"],"returncode":x["rc"]},
   "conversion_report":{"path":str(x["cr"]),"sha256":x["crs"],"exists_at_build":x["cr"].is_file(),"status":x["rd"].get("conversion_status") if x["cr"].is_file() else None},
   "trajectory_h5":{"path":str(x["h5"]),"sha256":x["h5sha"],"sha_source":"Root728 conversion-report output_sha256; source builder did not read or hash H5"},
   "native_receipt":{"path":str(x["np"]),"sha256":x["ns"],"status":x["nd"].get("status"),"returncode":x["nd"].get("returncode")},
   "physical_condition_sha256":x["phash"],"source_physical_condition_sha256":x["shash"],"actual_converter_scope_schema":x["scope"],"actual_converter_scope_sha256":x["scopehash"],
   "native_contract":{"frames":836,"particles":179208,"dimension":3,"tmax":8.35,"tout":0.01},
   "typed_summary":{"frames":x["rd"].get("frames"),"particles":x["rd"].get("particles"),"dimension":x["rd"].get("solver_dimension",{}).get("solver_dimension"),"partvtk_all_passed":x["rd"].get("partvtk_validation",{}).get("all_passed")} if x["done"] else None,
   "future_hashes_null_until_completed0":not x["done"],"source_agent_read_science_payloads":False,"source_agent_hashed_science_payloads":False})
 dump(OUT/"metadata/actual-typed728-provenance.json",{"schema":"ds02.f3.fresh067-corner706.actual-typed728-provenance.v1","family_id":"F3","fresh_id":FRESH,"scope":"Four Root706 corners, own Root728 typed attempt; downstream XMF/render disabled","source_only":True,"cases":rows,"root729_controller_script":str(OUT/"metadata/upstream/root729/batch-controller.py"),"source_builder_consumed_root729_result":False,"source_agent_read_arrays":False,"source_agent_started_jobs":False,"source_agent_modified_shared_state":False,"independent_case_count_increment":0})
 dump(OUT/"metadata/case-registry.json",{"schema":"ds02.f3.fresh067-corner706.case-registry.v1","family_id":"F3","fresh_id":FRESH,"source_only":True,"case_count":4,"independent_case_count_increment":0,"scope_semantics":"Root728 canonical physical-binding.v1 preserved; source and producer scopes separate","native_contract":{"dimension":3,"fixed_particles":111708,"fluid_particles":67500,"moving_particles":0,"total_particles":179208,"frames":836,"tmax":8.35,"tout":0.01},"cases":rows})
 dump(OUT/"metadata/selection.json",{"schema":"ds02.f3.fresh067-corner706.selection.v1","family_id":"F3","fresh_id":FRESH,"included_cases":CASES,"included_case_count":4,"selection":"Root706 four pitch/AY corners only","source_only":True,"no_visual_acceptance_claim":True,"no_qn_or_precision_claim":True})
 common=[OUT/"metadata/actual-typed728-provenance.json",OUT/"metadata/case-registry.json",OUT/"metadata/selection.json",OUT/"metadata/runtime-contract.json",OUT/"metadata/lineage-policy.json",
  OUT/"metadata/contracts/base-binary-contract.json",OUT/"metadata/contracts/n3-vector-spec.json",OUT/"metadata/contracts/root023-render-contract.json",OUT/"metadata/contracts/xmf-worker-contract.json",OUT/"metadata/root142/policy-check.json",OUT/"metadata/root142/source-policy-contract.json",OUT/"workers/export_xmf.py",OUT/"workers/render_native023.py",OUT/"metadata/upstream/root729/batch-controller.py",PYTHON,RUNTIME,STRICT,RESOURCE]
 for x in xs:
  common.extend([x["od"],x["ud"],x["np"]])
  if x["done"]: common.extend([x["tr"],x["cr"]])
 bound=close(common)
 xb=[]; rb=[]
 for x in xs:
  typereq=OUT/"requests/xmf"/(x["case"]+"-normal-xmf-request.json"); typebind=OUT/"requests/xmf"/(x["case"]+"-xmf-binding.json")
  rep=x["rd"]; ps=rep.get("hash_scopes",{}).get("physical_condition",{})
  b={"schema":"ds02.f3.fresh067_corner706.actual-typed-xmf-binding.v1","family_id":"F3","fresh_id":FRESH,"case_id":x["case"],"physical_case_id":ps.get("physical_case_id",x["physical"]),"physical_condition_sha256":rep.get("hash_scopes",{}).get("physical_condition_sha256",x["phash"]),"source_physical_condition_sha256":x["shash"],"physical_condition_hash_scope":"Root728 actual converter physical scope; ds-data-02.physical-binding.v1 retained; no legacy alignment","producer_scope_schema":ps.get("schema",x["scope"]),"actual_converter_physical_condition_scope_sha256":x["scopehash"],"actual_converter_owner":{"path":str(x["od"]),"sha256":digest(x["od"])},
   "typed_receipt":str(x["tr"]),"typed_receipt_sha256":x["trs"],"typed_receipt_status":{"status":x["status"],"returncode":x["rc"],"receipt_exists":x["tr"].is_file()},"conversion_report":str(x["cr"]),"conversion_report_sha256":x["crs"],"trajectory_h5":str(x["h5"]),"trajectory_h5_sha256":x["h5sha"],"producer_payload_hash_source":"Root728 conversion-report output_sha256 producer attestation; source builder did not open or hash H5","native_receipt":str(x["np"]),"native_receipt_sha256":x["ns"],"native_status":{"status":x["nd"].get("status"),"returncode":x["nd"].get("returncode"),"attempt_id":x["q"]["actual_native_binding"].get("attempt_id")},"expected_frames":836,"expected_particles":179208,"dimension":3,"physical_window_s":[0.0,8.35],"save_interval_s":0.01,"xmf_shape_contract":shape(),
   "n3_vector_spec":{"semantic_type":"N3","field":"velocity","components":["vx","vy","vz"],"dynamic_shape":[836,179208,3],"outshape_rule":"shape[1:]","xmf_dimensions":"179208 3","preserve_all_native_fields":True},"bound_metadata_sha256":bound,"future_outputs":{"execution_receipt":"{attempt_root}/execution-receipt.json","manifest":"{attempt_root}/xdmf/manifest.json","xdmf":"{attempt_root}/xdmf/case.xmf","execution_receipt_sha256":None,"manifest_sha256":None,"xdmf_sha256":None,"visual_decision":None},"future_input_files":[str(x["tr"]),str(x["cr"])] if not x["done"] else [],"source_only":True,"jobs_started":False,"arrays_read":False,"source_agent_read_science_payloads":False,"source_agent_hashed_science_payloads":False,"source_and_actual_scopes_are_distinct":True,"source_and_canonical_hashes_are_distinct":True,"numerical_precision_status":"not_accepted","production_approval":"none","q_n":"not_granted","independent_case_count_increment":0,"visual_review_pending":True,"request_status":"typed_completed0_waiting_root_enablement" if x["done"] else "typed_running_or_missing_waiting_root728_completion"}
  dump(typebind,b)
  cmd=[str(PYTHON),str(OUT/"workers/export_xmf.py"),"--binding",str(typebind),"--output-dir","{attempt_root}/xdmf"]
  rq={"schema":"ds02.runner-request.v2","family_id":"F3","fresh_id":FRESH,"case_id":x["case"],"attempt_id":f"root-stage1-f3-{x['case'].lower()}-typed728-to-xmf-{FRESH}","physical_case_id":x["physical"],"physical_condition_sha256":x["phash"],"producer_scope_schema":x["scope"],"kind":"cpu","cpu_task_kind":"audit","command":cmd,"cwd":str(IT/"lagrangian-fluid-lab"),"worktree_root":str(WT),"launch_owner":"root","cpu_threads":2,"max_wall_seconds":14400,"estimated_storage_bytes":4294967296,"disabled":True,"execution_allowed":False,"launch_allowed":False,"source_only":True,"env":{"OMP_NUM_THREADS":"2","OPENBLAS_NUM_THREADS":"2","MKL_NUM_THREADS":"2","NUMEXPR_NUM_THREADS":"2","PYTHONUNBUFFERED":"1"},"resource_guards":{"cpu_threads_per_request":2,"xmf_concurrency_cap":2,"home_free_space_floor_gib":500,"source_deadline":"2026-10-14T07:23:48Z","root142_profile":"root_home_floor_no_legacy_dataset_walk_v1","root142_policy_path":str(OUT/"metadata/root142/policy-check.json")},"input_files":sorted(bound),"input_sha256":bound,"future_input_files":[str(x["tr"]),str(x["cr"])] if not x["done"] else [],"future_input_sha256":{str(x["tr"]):None,str(x["cr"]):None} if not x["done"] else {},"binding":str(typebind),"output_dir_contract":{"child_output":"{attempt_root}/xdmf","xdmf":"{attempt_root}/xdmf/case.xmf","manifest":"{attempt_root}/xdmf/manifest.json","fresh_child_only":True},"depends_on_typed":{"attempt_id":x["attempt"],"attempt_root":str(x["root"]),"receipt":str(x["tr"]),"receipt_sha256":x["trs"],"status":x["status"],"returncode":x["rc"],"report":str(x["cr"]),"report_sha256":x["crs"]},"depends_on_native":{"receipt":str(x["np"]),"receipt_sha256":x["ns"],"status":x["nd"].get("status"),"returncode":x["nd"].get("returncode")},"future_outputs":{"execution_receipt":"{attempt_root}/execution-receipt.json","manifest":"{attempt_root}/xdmf/manifest.json","xdmf":"{attempt_root}/xdmf/case.xmf","execution_receipt_sha256":None,"manifest_sha256":None,"xdmf_sha256":None,"visual_decision":None},"actual_typed_completed0":x["done"],"root_enablement_requirements":["own Root728 typed receipt/report completed/0","strict CPU audit with shared cap2","metadata hashes close at launch","producer confirms 836 frames, 179208 particles, 3-D and PartVTK pass","Root visual review pending; no Q-N/precision claim"],"physical_scope_preserved":True,"legacy_scope_alignment":"not applied"}
  dump(typereq,rq)
  xb.append({"case_id":x["case"],"physical_case_id":x["physical"],"binding":str(typebind),"sha256":digest(typebind),"request":str(typereq),"request_sha256":digest(typereq),"typed_status":x["status"],"typed_returncode":x["rc"]})
  rbind=OUT/"requests/render"/(x["case"]+"-render-binding.json"); rreq=OUT/"requests/render"/(x["case"]+"-root023-render-request.json")
  rbmeta=dict(bound); rbmeta[str(typebind)]=digest(typebind); rbmeta[str(typereq)]=digest(typereq)
  rbj={"schema":"ds02.f3.fresh067_corner706.root023-render-binding.v1","family_id":"F3","fresh_id":FRESH,"case_id":x["case"],"physical_case_id":x["physical"],"physical_condition_sha256":x["phash"],"source_physical_condition_sha256":x["shash"],"producer_scope_schema":x["scope"],"actual_converter_physical_condition_scope_sha256":x["scopehash"],"typed_receipt":str(x["tr"]),"typed_receipt_sha256":x["trs"],"conversion_report":str(x["cr"]),"conversion_report_sha256":x["crs"],"trajectory_h5":str(x["h5"]),"trajectory_h5_sha256":x["h5sha"],"native_receipt":str(x["np"]),"native_receipt_sha256":x["ns"],"normal_xmf_request":str(typereq),"normal_xmf_binding":str(typebind),"normal_xmf_attempt_id":rq["attempt_id"],"manifest":"{normal_attempt_root}/xdmf/manifest.json","xdmf":"{normal_attempt_root}/xdmf/case.xmf","expected_frames":836,"expected_particles":179208,"dimension":3,"physical_window_s":[0.0,8.35],"n3_vector_spec":{"semantic_type":"N3","components":["vx","vy","vz"],"dynamic_shape":[836,179208,3],"xmf_dimensions":"179208 3","outshape_rule":"shape[1:]"},"renderer_contract":{"origin":str(RENDER_ORIGIN),"origin_sha256":RENDER_SHA,"all_saved_frames":"0..835 inclusive","software_offscreen":True,"automatic_native_bounds":True,"all_native_fields_retained":True,"xmf_vector_shape":"179208 3"},"bound_metadata_sha256":rbmeta,"future_outputs":{"execution_receipt":"{attempt_root}/execution-receipt.json","render_manifest":"{attempt_root}/render/render-manifest.json","render_report":"{attempt_root}/render/render-report.json","full_saved_animation":"{attempt_root}/render/full_saved_animation.gif","pvsm":"{attempt_root}/render/case.pvsm","contact_pages":"{attempt_root}/render/contact-pages","execution_receipt_sha256":None,"render_manifest_sha256":None,"render_report_sha256":None,"visual_decision":None},"source_only":True,"jobs_started":False,"arrays_read":False,"shared_state_modified":False,"visual_review_pending":True,"request_status":"wait_for_own_xmf_completed0"}
  dump(rbind,rbj)
  rcmd=["/usr/bin/env","VTK_SMP_MAX_THREADS=2","LP_NUM_THREADS=2","LIBGL_ALWAYS_SOFTWARE=1","MESA_LOADER_DRIVER_OVERRIDE=llvmpipe","__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json","VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow","QT_QPA_PLATFORM=offscreen","OMP_NUM_THREADS=2",str(PV),"--force-offscreen-rendering",str(OUT/"workers/render_native023.py"),"--manifest","{normal_attempt_root}/xdmf/manifest.json","--output-dir","{attempt_root}/render"]
  rr={"schema":"ds02.runner-request.v2","family_id":"F3","fresh_id":FRESH,"case_id":x["case"],"attempt_id":f"root-stage1-f3-{x['case'].lower()}-xmf-to-root023-{FRESH}","physical_case_id":x["physical"],"physical_condition_sha256":x["phash"],"kind":"cpu","cpu_task_kind":"audit","command":rcmd,"cwd":str(IT/"lagrangian-fluid-lab"),"worktree_root":str(WT),"launch_owner":"root","cpu_threads":2,"max_wall_seconds":14400,"estimated_storage_bytes":8589934592,"disabled":True,"execution_allowed":False,"launch_allowed":False,"source_only":True,"env":{"VTK_SMP_NUM_THREADS":"2","LP_NUM_THREADS":"2","LIBGL_ALWAYS_SOFTWARE":"1","MESA_LOADER_DRIVER_OVERRIDE":"llvmpipe","VTK_DEFAULT_OPENGL_WINDOW":"vtkEGLRenderWindow","QT_QPA_PLATFORM":"offscreen","OMP_NUM_THREADS":"2"},"resource_guards":{"render_concurrency_cap":2,"home_free_space_floor_gib":500,"root142_profile":"root_home_floor_no_legacy_dataset_walk_v1","software_renderer":"llvmpipe"},"input_files":sorted(rbmeta),"input_sha256":rbmeta,"future_input_files":["{normal_attempt_root}/xdmf/case.xmf","{normal_attempt_root}/xdmf/manifest.json"],"future_input_sha256":{"{normal_attempt_root}/xdmf/case.xmf":None,"{normal_attempt_root}/xdmf/manifest.json":None},"binding":str(rbind),"depends_on_normal_xmf_request":str(typereq),"depends_on_normal_xmf_binding":str(typebind),"output_dir_contract":{"child_output":"{attempt_root}/render","full_animation":"{attempt_root}/render/full_saved_animation.gif","all_frames":"0..835 inclusive","n3_vector_shape":"179208 3"},"future_outputs":{"execution_receipt":"{attempt_root}/execution-receipt.json","render_manifest":"{attempt_root}/render/render-manifest.json","render_report":"{attempt_root}/render/render-report.json","execution_receipt_sha256":None,"render_manifest_sha256":None,"render_report_sha256":None,"visual_decision":None},"root_enablement_requirements":["own XMF request completed/0","Root023 manifest/shape preflight","software offscreen cap2 CPU2","visual review pending; no Q-N/precision claim"]}
  dump(rreq,rr); rb.append({"case_id":x["case"],"physical_case_id":x["physical"],"binding":str(rbind),"sha256":digest(rbind),"request":str(rreq),"request_sha256":digest(rreq)})
 dump(OUT/"requests/xmf-bindings.json",{"schema":"ds02.f3.fresh067-corner706.xmf-bindings.v1","family_id":"F3","fresh_id":FRESH,"source_only":True,"case_count":4,"cases":xb})
 dump(OUT/"requests/render-bindings.json",{"schema":"ds02.f3.fresh067-corner706.render-bindings.v1","family_id":"F3","fresh_id":FRESH,"source_only":True,"case_count":4,"cases":rb})
 dump(OUT/"manifest.json",{"schema":"ds02.f3.fresh067-corner706.source-manifest.v1","family_id":"F3","fresh_id":FRESH,"package_path":str(OUT),"case_count":4,"cases":CASES,"source_only":True,"jobs_started":False,"scientific_payloads_read_or_hashed":False,"shared_state_modified":False,"typed_status_at_build":{x["case"]:{"status":x["status"],"returncode":x["rc"],"receipt_exists":x["tr"].is_file(),"report_exists":x["cr"].is_file()} for x in xs},"future_output_hashes_null_until_actual_producer":True,"physical_scope":"ds-data-02.physical-binding.v1 from Root728 actual converter scope","legacy_scope_alignment":"none","n3_shape":"N x 3; velocity dimensions 179208 3","root023":"downstream disabled requests only"})
 Path(OUT/"README.md").write_text(f"""# F3 {FRESH} typed-to-XMF source handoff

Four disabled per-case XMF requests bind each Root706 native corner to its own
Root728 typed receipt/report path. Disabled Root023 render successors preserve
all 836 frames and the velocity N3 shape 179208 3.

The builder read or hashed only JSON/Python/XML metadata and producer-attested
digests. It did not open or hash H5, BI4, CSV, DAT, VTK, or scientific arrays,
and started no job. A Root728 receipt that was live or absent at build time is
recorded as WAIT with null typed/report/H5/XMF/render future hashes. Root must
derive an enabled request from that case's own completed producer JSON.

Root enablement requires typed completed/0, native completed/0, closed metadata
hashes, CPU2 and shared cap2, then Root023 full-animation visual review. This
package makes no visual, precision, Q-N, or production claim.

The historical root_followup_067_native_nvme_staging_contract_v1 remains
untouched; the collision-safe package directory is root_followup_081... and
the assignment id is {FRESH}.
""")
 print(json.dumps({"package":str(OUT),"fresh_id":FRESH,"typed_status":{x["case"]:[x["status"],x["rc"]] for x in xs},"completed0":[x["case"] for x in xs if x["done"]]},indent=2))
if __name__=="__main__": main()
