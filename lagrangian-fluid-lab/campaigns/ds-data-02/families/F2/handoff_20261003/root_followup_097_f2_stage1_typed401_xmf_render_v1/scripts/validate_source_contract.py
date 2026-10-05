#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
RAW={".h5",".hdf5",".bi4",".ibi4",".csv",".vtk",".vtu",".pvtu",".dat"}
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for block in iter(lambda: f.read(1048576), bytes()): h.update(block)
 return h.hexdigest()
def load(p): return json.loads(p.read_text())
def closure(d,label):
 fs=d.get("input_files",[]); hs=d.get("input_sha256",{})
 assert set(fs)==set(hs), label+" input closure mismatch"
 for t in fs:
  p=Path(t); assert p.suffix.lower() not in RAW, label+" raw input"
  assert p.is_file(), label+" missing "+str(p)
  assert sha(p)==hs[t], label+" changed "+str(p)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--manifest",required=True,type=Path); a=ap.parse_args()
 root=a.manifest.resolve().parent; m=load(a.manifest)
 assert m["family_id"]=="F2" and m["fresh_id"]=="fresh097" and m["all_requests_disabled"]
 assert len(m["cases"])==5 and not m["arrays_read"]
 for p in root.rglob("*"):
  if p.is_file(): assert p.suffix.lower() not in RAW, "raw package file "+str(p)
 for c in load(root/"metadata/case-registry.json")["cases"]:
  assert c["actual_converter_physical_condition_sha256"]!=c["source_plan_condition_sha256"]
  for k in ("typed_binding","typed_request","xmf_binding","xmf_request","render_binding","render_request"):
   d=load(Path(c[k])); assert d["disabled"] and not d["execution_allowed"] and d["future_hashes_null"]; closure(d,c["case_id"]+":"+k)
  o=load(root/"owners"/(c["case_id"]+".actual-converter-scope.owner.json")); assert "physical_binding" not in o and o["producer_scope_schema"]=="legacy-owner-scope.v0"
  x=load(Path(c["xmf_binding"])); assert x["producer_scope_schema"]=="legacy-owner-scope.v0"; assert x["xmf_shape_contract"]["dynamic_vector_dimensions"]=="418104 3"; assert x["xmf_shape_contract"]["dynamic_scalar_dimensions"]=="418104"
  for t,v in x["bound_metadata_sha256"].items():
   p=Path(t); assert p.suffix.lower() not in RAW and p.is_file() and sha(p)==v
  r=load(Path(c["render_binding"])); assert not r["camera_policy"]["fixed_camera_override"] and not r["camera_policy"]["domain_bounds_in_manifest"]
 print(json.dumps({"status":"pass","cases":len(m["cases"]),"disabled_requests":len(m["cases"])*3}))
if __name__=="__main__": main()
