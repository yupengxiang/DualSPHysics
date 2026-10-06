#!/usr/bin/env python3
"""Static metadata validator for F3 fresh067-corner706.

It opens JSON/Python/XML metadata only. It refuses scientific payload paths and
never opens or hashes H5, BI4, CSV, DAT, VTK, or any array.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

PKG=Path(__file__).resolve().parent
CASES=[
 "F3_STAGE1_DP006_P0800_AY0250",
 "F3_STAGE1_DP006_P0800_AY0750",
 "F3_STAGE1_DP006_P1200_AY0250",
 "F3_STAGE1_DP006_P1200_AY0750",
]
BAD={".bi4",".ibi4",".csv",".dat",".h5",".hdf5",".vtk",".npy",".npz"}
HEX=set("0123456789abcdef")
def load(p): return json.loads(Path(p).read_text())
def digest(p):
 p=Path(p)
 if p.suffix.lower() in BAD: raise AssertionError("scientific payload hash refused: "+str(p))
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def fail(msg): raise AssertionError(msg)
def require(cond,msg):
 if not cond: fail(msg)

def validate_binding(b):
 require(b["schema"]=="ds02.f3.fresh067_corner706.actual-typed-xmf-binding.v1","binding schema")
 for k in ["typed_receipt","native_receipt","conversion_report","trajectory_h5"]:
  require(isinstance(b[k],str) and b[k].startswith("/"),k+" must be absolute string")
 require(b["producer_scope_schema"]=="ds-data-02.physical-binding.v1","scope schema")
 require(len(b["physical_condition_sha256"])==64 and set(b["physical_condition_sha256"])<=HEX,"scope digest")
 require(b["xmf_shape_contract"]["dynamic_vector"]["dataset_shape"]==[836,179208,3],"N3 shape")
 require(b["xmf_shape_contract"]["dynamic_vector"]["xmf_dimensions"]=="179208 3","N3 XMF dimensions")
 require(b["future_outputs"]["xdmf_sha256"] is None and b["future_outputs"]["manifest_sha256"] is None,"future XMF hashes")
 require(b["source_only"] and not b["jobs_started"] and not b["arrays_read"],"source flags")
 status=b["typed_receipt_status"]
 require(status["status"]=="completed" and status["returncode"]==0 and status["receipt_exists"],"typed status")
 for path,expected in b["bound_metadata_sha256"].items():
  require(Path(path).suffix.lower() not in BAD,"payload in bound metadata")
  require(Path(path).is_file(),"missing bound metadata "+path)
  require(digest(path)==expected,"bound metadata digest mismatch "+path)
 tr=load(b["typed_receipt"]); cr=load(b["conversion_report"]); nr=load(b["native_receipt"])
 require((tr.get("status"),tr.get("returncode"))==("completed",0),"typed receipt terminal")
 require((nr.get("status"),nr.get("returncode"))==("completed",0),"native receipt terminal")
 require(cr.get("conversion_status")=="completed","conversion terminal")
 require((cr.get("frames"),cr.get("particles"))==(836,179208),"conversion dimensions")
 require(cr.get("solver_dimension",{}).get("solver_dimension")==3,"conversion dimension")
 require(cr.get("partvtk_validation",{}).get("all_passed") is True,"PartVTK")
 ph=cr["hash_scopes"]["physical_condition"]
 require(ph["schema"]==b["producer_scope_schema"],"producer scope")
 require(ph["physical_case_id"]==b["physical_case_id"],"physical case")
 require(cr["hash_scopes"]["physical_condition_sha256"]==b["physical_condition_sha256"],"physical hash")
 require(cr["output_hdf5"]==b["trajectory_h5"],"trajectory path")
 require(digest(b["typed_receipt"])==b["typed_receipt_sha256"],"typed receipt digest")
 require(digest(b["conversion_report"])==b["conversion_report_sha256"],"conversion report digest")
 require(digest(b["native_receipt"])==b["native_receipt_sha256"],"native receipt digest")

def validate_request(q):
 required=["family_id","case_id","attempt_id","kind","command","cwd","worktree_root","launch_owner","cpu_threads","env","max_wall_seconds","estimated_storage_bytes","input_files","input_sha256"]
 for k in required: require(k in q,k+" missing")
 require(q["family_id"]=="F3" and q["kind"]=="cpu","family/kind")
 require(q["disabled"] and not q["execution_allowed"] and not q["launch_allowed"] and q["source_only"],"disabled gate")
 require(q["launch_owner"]=="root" and q["cpu_threads"]==2 and q["max_wall_seconds"]==14400,"runtime")
 require(q["command"][0].endswith("/.venv/bin/python"),"approved interpreter")
 require("export_xmf.py" in q["command"][1] and "ds_data02_direct_convert.py" not in q["command"],"worker command")
 require("-mdbc_noslip:1" not in q["command"],"solver command leaked")
 require(q["input_files"]==sorted(q["input_files"]) and q["input_sha256"].keys()==set(q["input_files"]),"input closure")
 for path in q["input_files"]: require(Path(path).suffix.lower() not in BAD,"science input closure")
 require(q["future_outputs"]["xdmf_sha256"] is None and q["future_outputs"]["manifest_sha256"] is None,"future hashes")
 require(q["output_dir_contract"]["child_output"]=="{attempt_root}/xdmf","child XMF output")
 for key in ["worktree_root","cwd","launch_owner","env"]: require(key in q,key)

def validate_render(r):
 require(r["disabled"] and not r["execution_allowed"] and not r["launch_allowed"] and r["source_only"],"render disabled")
 require(r["cpu_threads"]==2 and r["launch_owner"]=="root","render runtime")
 require(r["output_dir_contract"]["n3_vector_shape"]=="179208 3","render N3")
 require(r["future_outputs"]["render_report_sha256"] is None,"render future hash")
 require(any("render_native023.py" in str(item) for item in r["command"]),"Root023 worker")
 for path in r["input_files"]: require(Path(path).suffix.lower() not in BAD,"render payload closure")

def validate():
 man=load(PKG/"manifest.json")
 require(man["schema"]=="ds02.f3.fresh067-corner706.source-manifest.v1","manifest")
 require(man["case_count"]==4 and man["source_only"] and not man["jobs_started"],"manifest flags")
 for case in CASES:
  b=load(PKG/"requests/xmf"/(case+"-xmf-binding.json"))
  q=load(PKG/"requests/xmf"/(case+"-normal-xmf-request.json"))
  r=load(PKG/"requests/render"/(case+"-render-binding.json"))
  rr=load(PKG/"requests/render"/(case+"-root023-render-request.json"))
  require(b["case_id"]==case and q["case_id"]==case and r["case_id"]==case and rr["case_id"]==case,"case binding")
  validate_binding(b); validate_request(q); validate_render(rr)
  require(r["normal_xmf_request"]==str(PKG/"requests/xmf"/(case+"-normal-xmf-request.json")),"render dependency")
 print("PASS: fresh067-corner706 four XMF bindings, Root023 successors, metadata closure, N3 contract")

def synthetic_negative_tests():
 b=load(PKG/"requests/xmf"/(CASES[0]+"-xmf-binding.json"))
 q=load(PKG/"requests/xmf"/(CASES[0]+"-normal-xmf-request.json"))
 r=load(PKG/"requests/render"/(CASES[0]+"-root023-render-request.json"))
 checks=[]
 for name,mut,fn in [
  ("typed_receipt_dict",lambda x:x.__setitem__("typed_receipt",{"path":x["typed_receipt"]}),validate_binding),
  ("payload_hash_map",lambda x:x["bound_metadata_sha256"].__setitem__("/tmp/future.h5","0"*64),validate_binding),
  ("enabled_xmf",lambda x:x.__setitem__("disabled",False),validate_request),
  ("direct_converter_token",lambda x:x["command"].append("ds_data02_direct_convert.py"),validate_request),
  ("render_shape",lambda x:x["output_dir_contract"].__setitem__("n3_vector_shape","179208"),validate_render),
 ]:
  c=copy.deepcopy({"typed_receipt_dict":b,"payload_hash_map":b,"enabled_xmf":q,"direct_converter_token":q,"render_shape":r}[name])
  mut(c)
  try: fn(c)
  except (AssertionError,KeyError,TypeError): checks.append(name)
 require(set(checks)=={"typed_receipt_dict","payload_hash_map","enabled_xmf","direct_converter_token","render_shape"},"negative cases")
 print("PASS: fresh067-corner706 negative contract tests")

if __name__=="__main__":
 validate()
 synthetic_negative_tests()
