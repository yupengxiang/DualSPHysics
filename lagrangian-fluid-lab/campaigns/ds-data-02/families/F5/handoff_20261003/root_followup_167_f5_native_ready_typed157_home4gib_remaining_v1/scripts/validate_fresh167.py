#!/usr/bin/env python3
"""Fresh166 metadata-only validator: every runtime input is a regular file.
No science payload is opened or hashed; opaque hashes are producer attestations.
"""
from __future__ import annotations
import argparse, hashlib, json, tempfile
from pathlib import Path
SAFE={'.json','.xml','.py','.md','.sh','.toml','.ini','.yaml','.yml'}
SCIENCE={'.bi4','.dat','.csv','.h5','.vtk','.vtu','.pvtu','.png','.jpg','.jpeg','.npy','.npz','.bin'}
EXPECTED={'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'solver_dimension':3,'data2d':False}
WORKER_SHA='37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11'
PACKAGE_ID='F5_fresh167_native_ready_typed157_home4gib_remaining'
def load(p): return json.loads(Path(p).read_text())
def fail(msg): raise AssertionError(msg)
def sha_safe(p):
 p=Path(p)
 if p.suffix.lower() not in SAFE: fail(f'unsafe hash requested: {p}')
 return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(c):
 x=c.get('xml_particle_counts',{})
 return {'total_particles':int(c.get('total_particles',x.get('total'))),'fixed_particles':int(c.get('fixed_particles',x.get('fixed'))),'moving_particles':int(c.get('moving_particles',x.get('moving'))),'floating_particles':int(c.get('floating_particles',x.get('floating'))),'fluid_particles':int(c.get('fluid_particles',x.get('fluid'))),'solver_dimension':int(c.get('solver_dimension',3)),'data2d':bool(c.get('data2d',False))}
def validate_input_closure(req):
 files=req['input_files']; hashes=req['input_sha256']; prov=req['input_sha256_provenance']; cats=req['input_sha256_categories']
 if len(files)!=len(set(files)) or set(files)!=set(hashes) or set(files)!=set(prov) or set(files)!=set(cats): fail('input closure sets differ or duplicate')
 for raw in files:
  p=Path(raw)
  if not p.is_absolute() or not p.is_file(): fail(f'input_files must contain regular files only: {raw}')
  if p.suffix.lower() in SCIENCE:
   if not hashes[raw] or cats[raw]!='producer_payload_attestation' or 'producer' not in prov[raw]: fail(f'science input is not producer-attested: {raw}')
  elif p.suffix.lower() in SAFE:
   if hashes[raw]!=sha_safe(p): fail(f'metadata/source hash mismatch: {raw}')
  else:
   if not hashes[raw] or cats[raw]!='registered_binary_attestation': fail(f'binary attestation missing: {raw}')
def validate_one(pkg,rp):
 req=load(rp); tag=req['tag']; bp=Path(req['physical_binding_path']); bind=load(bp)
 if req['package_id']!=PACKAGE_ID or req['family_id']!='F5' or req['schema']!='ds02.runner-request.v2': fail(f'{tag}: request identity')
 for k in ('disabled','source_only','launch','launch_allowed','execution_allowed','conversion_allowed','solver_allowed','arrays_allowed','array_edit_allowed'):
  if req.get(k) is not ({'disabled':True,'source_only':True}.get(k,False)): fail(f'{tag}: disabled flag {k}={req.get(k)!r}')
 if req['kind']!='cpu' or req['cpu_task_kind']!='conversion' or req['cpu_threads']!=2: fail(f'{tag}: cpu contract')
 for k in ('root_actual_launch_source','root_actual_launch_source_sha256','root_inventory_policy_source','root_inventory_policy_source_sha256','root_inventory_policy_sha256','root_inventory_profile','root142_cpu_entrypoint','root142_cpu_policy','runtime_entrypoint','strict_dispatch_entrypoint'):
  if not req.get(k): fail(f'{tag}: missing Root142 field {k}')
 if req['shared_conversion_concurrency_cap']!=1 or req['estimated_storage_bytes']!=4294967296 or req['home_publish_cap_bytes']!=4294967296: fail(f'{tag}: storage cap')
 if req['home_min_free_bytes']!=536870912000 or req['home_publish_headroom_bytes']!=2147483648 or req['nvme_staging_limit_bytes']!=25769803776 or req['nvme_free_reserve_bytes']!=107374182400: fail(f'{tag}: storage floor')
 if req['current_attempt_id']!=f"F5/{req['case_id']}/{req['attempt_id']}": fail(f'{tag}: attempt identity')
 if req['physical_binding_sha256']!=sha_safe(bp) or bind['schema']!='ds02.f5.fresh167.native-ready-typed157-binding.v1': fail(f'{tag}: binding')
 if bind['tag']!=tag or bind['case_id']!=req['case_id'] or bind['physical_case_id']!=req['physical_case_id'] or bind['physical_condition_sha256']!=req['physical_condition_sha256']: fail(f'{tag}: binding identity/scope')
 if bind['source_bed_marker_mkbound']!=40 or bind['native_bed_marker_mk']!=50: fail(f'{tag}: Mk mapping')
 if not req['source_h5_legacy_scope_sha256'] or req['source_h5_legacy_scope_sha256']!=bind['source_h5_legacy_scope']['sha256'] or req['root_prospective_legacy_scope_sha256']!=req['source_h5_legacy_scope_sha256']: fail(f'{tag}: prospective legacy v0 scope')
 if bind['typed_future']['legacy_scope_sha256'] is not None: fail(f'{tag}: future producer legacy scope populated')
 if norm(req['actual_counts'])!=EXPECTED or req['actual_counts']!=req['expected_counts']: fail(f'{tag}: counts')
 if req['expected_frames']!=801 or req['expected_particle_axis']!=194427 or req['expected_dimension']!=3: fail(f'{tag}: timeline')
 if any(v is not None for v in req['future_output_hashes'].values()): fail(f'{tag}: future hash populated')
 for key,hkey in [('gencase_receipt','gencase_receipt_sha256'),('prepared_input_report','prepared_input_report_sha256'),('generated_xml','generated_xml_sha256'),('actual_initial_qa_receipt','actual_initial_qa_receipt_sha256'),('actual_initial_qa_report','actual_initial_qa_report_sha256'),('actual_native_receipt','actual_native_receipt_sha256'),('actual_native_request','actual_native_request_sha256')]:
  p=Path(req[key]);
  if p.suffix.lower() not in SAFE or sha_safe(p)!=req[hkey]: fail(f'{tag}: current metadata hash {key}')
 g=load(req['gencase_receipt']); q=load(req['actual_initial_qa_report']); n=load(req['actual_native_receipt'])
 if (g.get('status'),g.get('returncode'))!=('completed',0) or (n.get('status'),n.get('returncode'))!=('completed',0): fail(f'{tag}: upstream terminal')
 if not q.get('all_basic_placement_checks_pass') or q.get('stage1_basic_placement_proof')!='pass_excluding_numerical_precision' or q.get('numerical_precision_result_accepted') is not False: fail(f'{tag}: QA')
 if req['actual_native_dependency']['attempt_id']!=n['request']['attempt_id'] or req['actual_native_dependency']['frames']!=n['request'].get('expected_frames'): fail(f'{tag}: native identity')
 if req['generated_xml_sha256']!=load(req['prepared_input_report']).get('xml_sha256'): fail(f'{tag}: XML producer attestation')
 for ent in req['directory_provenance']:
  if ent['sha256'] is not None or not Path(ent['path']).is_dir(): fail(f'{tag}: directory provenance')
 validate_input_closure(req)
 if req['command_provenance']['worker_sha256']!=WORKER_SHA or not any('nvme_convert_home_capped_v2.py' in x for x in req['command']): fail(f'{tag}: worker')
 for x in ('--home-publish-cap-bytes','4294967296','--home-floor-bytes','536870912000','--home-publish-headroom-bytes','2147483648','--nvme-free-reserve-bytes','107374182400','--current-attempt-id',req['current_attempt_id']):
  if x not in req['command']: fail(f'{tag}: command guard {x}')
 if not isinstance(req['scientific_data_root'],dict) or not req['source_provenance']['producer_directories']: fail(f'{tag}: directory provenance fields')
 return {'tag':tag,'case_id':req['case_id'],'physical_case_id':req['physical_case_id'],'actual_native_attempt':n['request']['attempt_id'],'counts':norm(req['actual_counts']),'input_count':len(req['input_files']),'directories_not_inputs':all(Path(x).is_file() for x in req['input_files']),'status':'metadata-pass-disabled'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package-root',type=Path,required=True); a=ap.parse_args(); pkg=a.package_root; rs=sorted((pkg/'requests').glob('*.json'));
 if len(rs)!=5: fail(f'request count {len(rs)}')
 results=[validate_one(pkg,p) for p in rs]
 if len({x['tag'] for x in results})!=5: fail('duplicate tags')
 # Meaningful negative: the regular-file guard rejects a synthetic directory input.
 try:
  validate_input_closure({'input_files':[str(pkg)],'input_sha256':{str(pkg):None},'input_sha256_provenance':{str(pkg):'producer_directory'},'input_sha256_categories':{str(pkg):'producer_directory'}})
 except AssertionError: directory_negative=True
 else: directory_negative=False
 if not directory_negative: fail('directory-input negative did not reject')
 census=load(pkg/'metadata/f5-full48-census.json')
 if census.get('schema')!='ds02.f5.fresh167.full48-census.v1' or census.get('census_scope',{}).get('actual_census_row_count')!=34: fail('full48 census scope')
 cc=census.get('next34_category_counts',{})
 if cc.get('selected_fresh167_eligible')!=5 or cc.get('already_bound_fresh166')!=12 or cc.get('excluded_fresh165_or_actual983')!=5 or cc.get('excluded_already_typed864_or_accepted')!=1 or cc.get('excluded_native_not_available_or_registered_pending')!=11: fail('full48 census counts')
 if sorted(census.get('selected_tags',[]))!=['M106_T085','M106_T095','M108_T085','M108_T095','M110_T085']: fail('full48 selected tags')
 if census.get('selection_exclusions',{}).get('other_registered_pending_not_promoted') is not True: fail('pending exclusion')
 manifest=load(pkg/'manifest.json')
 for rel,h in manifest['files'].items():
  p=pkg/rel
  if not p.is_file() or sha_safe(p)!=h: fail(f'manifest mismatch {rel}')
 report={'schema':'ds02.f5.fresh167.validator-report.v1','package_id':PACKAGE_ID,'source_only':True,'arrays_read_or_hashed':False,'science_payloads_read_or_hashed':False,'request_count':5,'results':results,'negative_checks':{'directory_input_rejected':True,'prospective_legacy_scope_bound_and_future_null':True},'manifest_checked':True,'manifest_excludes_report_and_manifest':True,'future_hashes_null':True,'status':'pass-disabled-metadata-only'}
 (pkg/'metadata/fresh167-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
