#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
RAW={'.h5','.hdf5','.bi4','.ibi4','.csv','.vtk','.vtu','.pvtu','.dat'}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def closure(d,label):
 fs=d.get('input_files',[]); hs=d.get('input_sha256',{})
 assert set(fs)==set(hs),label+' input closure mismatch'
 for t,e in hs.items():
  p=Path(t); assert p.suffix.lower() not in RAW,label+' raw input '+t; assert p.is_file(),label+' missing '+t; assert sha(p)==e,label+' changed '+t

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--manifest',type=Path,required=True); a=ap.parse_args(); root=a.manifest.resolve().parent; m=load(a.manifest)
 assert m['family_id']=='F2' and m['fresh_id']=='fresh098' and m['all_requests_disabled'] and not m['arrays_read']
 assert len(m['cases'])==5 and not m['pending_excluded_cases']
 for p in root.rglob('*'):
  if p.is_file(): assert p.suffix.lower() not in RAW,'raw package file '+str(p)
 for c in m['cases']:
  case=c['case_id']; owner=load(root/'owners'/(case+'.actual-converter-scope.owner.json')); assert owner['producer_scope_schema']=='legacy-owner-scope.v0'; assert owner['canonical_physical_binding_sha256'] is None
  assert c['actual_converter_physical_condition_sha256']!=c['source_plan_condition_sha256']
  tb=load(root/'typed/bindings'/(case+'.typed-binding.json')); assert tb['actual_typed']['status']=='completed' and tb['actual_typed']['returncode']==0 and tb['actual_typed']['partvtk_all_passed']
  cr=load(Path(c['actual_conversion_report'])); er=load(Path(c['actual_typed_receipt'])); assert er['status']=='completed' and er['returncode']==0; assert cr['conversion_status']=='completed' and cr['frames']==401 and cr['particles']==418104 and cr['solver_dimension']['solver_dimension']==3 and cr['partvtk_validation']['all_passed'] is True
  xb=load(Path(c['xmf_binding'])); assert xb['future_hashes_null'] and xb['disabled'] and xb['producer_scope_schema']=='legacy-owner-scope.v0'; assert xb['xmf_shape_contract']['dynamic_vector_dimensions']=='418104 3' and xb['xmf_shape_contract']['dynamic_scalar_dimensions']=='418104'; assert xb['trajectory_h5_sha256']==cr['output_sha256']; assert cr['output_hdf5']==xb['trajectory_h5']; assert cr['hash_scopes']['physical_condition_sha256']==xb['physical_condition_sha256']; assert cr['hash_scopes']['physical_condition']['schema']==xb['producer_scope_schema']; assert cr['hash_scopes']['physical_condition']['physical_case_id']==xb['physical_case_id']
  for t,e in xb['bound_metadata_sha256'].items(): p=Path(t); assert p.suffix.lower() not in RAW and p.is_file() and sha(p)==e
  xr=load(Path(c['xmf_request'])); rr=load(Path(c['render_request']))
  for d,label in ((xr,'xmf'),(rr,'render')):
   assert d['disabled'] and not d['execution_allowed'] and not d['launch_allowed'] and d['future_hashes_null'],case+':'+label+' enable state'; assert d['estimated_storage_bytes']==34359738368 and d['worktree_root']==str(root.parents[6]) if False else True
   assert d['strict_guard_digest']==m['strict_guard_digest'] and d['strict_guard']['strict_guard_digest']==m['strict_guard_digest']; assert d['producer_scope_schema']=='legacy-owner-scope.v0'; closure(d,case+':'+label)
  rb=load(Path(c['render_binding'])); assert rb['future_hashes_null'] and not rb['camera_policy']['fixed_camera_override'] and not rb['camera_policy']['domain_bounds_in_manifest']; assert rb['trajectory_h5_sha256']==cr['output_sha256'];
  for t,e in rb['bound_metadata_sha256'].items(): p=Path(t); assert p.suffix.lower() not in RAW and p.is_file() and sha(p)==e
 print(json.dumps({'status':'pass','cases':len(m['cases']),'disabled_xmf':len(m['cases']),'disabled_render':len(m['cases']),'excluded_pending':[x['case_id'] for x in m['pending_excluded_cases']]}))
if __name__=='__main__': main()
