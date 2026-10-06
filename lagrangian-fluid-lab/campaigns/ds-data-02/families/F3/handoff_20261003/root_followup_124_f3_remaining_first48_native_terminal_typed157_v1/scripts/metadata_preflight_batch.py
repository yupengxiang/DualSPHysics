#!/usr/bin/env python3
"""Fresh124 metadata-only converter-scope preflight; never opens science payloads."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
FORBIDDEN={'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
def sha256(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
 return h.hexdigest()
def j(p): return json.loads(p.read_text(encoding='utf-8'))
def import_converter(p):
 spec=importlib.util.spec_from_file_location('_fresh124_converter',p); assert spec and spec.loader
 m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); return m
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument('--output',type=Path); a=ap.parse_args(); pkg=a.package.resolve(); idx=j(pkg/'metadata/candidate-index.json'); rows=idx['selected_cases'];
 converter_path=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py').resolve(); conv=import_converter(converter_path); convsha=sha256(converter_path); out=[]
 for row in rows:
  owner=Path(row['owner_path']).resolve(); x=j(owner); binding=x.get('physical_binding');
  if not isinstance(binding,dict) or binding.get('schema')!='ds-data-02.physical-binding.v1': raise RuntimeError(f"{row['case_id']}: physical binding")
  scope=conv._physical_condition_scope(x); digest=conv.canonical_hash(scope)
  if digest!=row['physical_condition_sha256']: raise RuntimeError(f"{row['case_id']}: scope {digest} != row")
  ev=Path(row['native_evidence_path']).resolve(); pre=Path(row['preflight_path']).resolve();
  if j(ev)['active_progress_not_runtime_input'] is not True: raise RuntimeError(f"{row['case_id']}: active progress policy")
  out.append({'case_id':row['case_id'],'owner_path':str(owner),'owner_sha256':sha256(owner),'scope_sha256':digest,'converter_path':str(converter_path),'converter_sha256':convsha,'evidence_path':str(ev),'evidence_sha256':sha256(ev),'preflight_path':str(pre),'preflight_sha256':sha256(pre),'status':'pass_metadata_only','payload_opened_or_hashed':False})
 report=a.output or pkg/'metadata/fresh124-preflight-report.json'; report.parent.mkdir(parents=True,exist_ok=True); report.write_text(json.dumps({'schema':'ds02.stage1.f3.fresh124.preflight-report.v1','package':str(pkg),'selected_count':len(out),'results':out,'payload_opened_or_hashed':False},indent=2,sort_keys=True)+'\n'); print(json.dumps({'status':'pass','selected_count':len(out),'report':str(report.resolve())},indent=2))
if __name__=='__main__': main()
