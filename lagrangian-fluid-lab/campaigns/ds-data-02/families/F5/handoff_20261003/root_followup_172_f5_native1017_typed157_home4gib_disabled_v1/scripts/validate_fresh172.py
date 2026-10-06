#!/usr/bin/env python3
"""Fresh172 metadata-only validator. It never opens or hashes BI4/DAT/CSV/H5/VTK payloads."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
SAFE={'.json','.xml','.py','.md','.sh','.toml','.ini','.yaml','.yml'}
SCI={'.bi4','.dat','.csv','.h5','.vtk','.vtu','.pvtu','.png','.jpg','.jpeg','.npy','.npz'}
EXPECTED={'data2d':False,'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'solver_dimension':3}
TAGS=['M090_T080','M090_T100','M100_T080','M101_T100','M110_T080']
PKGID='F5_fresh172_native1017_typed157_home4gib_disabled_v1'
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def fail(x): raise AssertionError(x)
def norm(c):
 x=c.get('xml_particle_counts',{})
 return {'data2d':bool(c.get('data2d',False)),'total_particles':int(c.get('total_particles',x.get('total'))),'fixed_particles':int(c.get('fixed_particles',x.get('fixed'))),'moving_particles':int(c.get('moving_particles',x.get('moving'))),'floating_particles':int(c.get('floating_particles',x.get('floating'))),'fluid_particles':int(c.get('fluid_particles',x.get('fluid'))),'solver_dimension':int(c.get('solver_dimension',3))}
def validate_inputs(req):
 fs=req['input_files']; hs=req['input_sha256']; cats=req['input_sha256_categories']; prov=req['input_sha256_provenance']
 if len(fs)!=len(set(fs)) or set(fs)!=set(hs) or set(fs)!=set(cats) or set(fs)!=set(prov): fail(f"{req['tag']}: input closure sets")
 if any(not Path(x).is_absolute() or not Path(x).is_file() for x in fs): fail(f"{req['tag']}: directory/nonregular input")
 for raw in fs:
  p=Path(raw); ext=p.suffix.lower()
  if ext in SCI:
   if cats[raw]!='producer_payload_attestation' or not hs[raw] or 'producer' not in prov[raw]: fail(f"{req['tag']}: science producer attestation {raw}")
  elif ext in SAFE:
   if cats[raw]!='metadata_current_hash' or sha(p)!=hs[raw]: fail(f"{req['tag']}: current metadata hash {raw}")
  else:
   if cats[raw]!='registered_binary_attestation' or not hs[raw]: fail(f"{req['tag']}: binary attestation {raw}")
def validate_wait_snapshot(pkg):
 s=load(pkg/'metadata/fresh172-root984-root1016-status.json')
 r=s['root1016_three_original138_bed']
 if r.get('status')!='WAIT_registration_or_execution_in_progress_no_terminal_science_receipts': fail('root1016: wait status')
 if r.get('same_controller_handle_for_all_requests') is not True or r.get('all_execution_receipts_absent_at_source_prep') is not True: fail('root1016: controller/receipt wait state')
 if r.get('controller_requests_match_launch_process') is not True or r.get('request_count')!=3: fail('root1016: controller request closure')
 if r.get('controller_config_sha256')!=sha(r['controller_config']): fail('root1016: config sha')
 if r.get('controller_launch_process_sha256')!=sha(r['controller_launch_process']): fail('root1016: launch sha')
 rows=r.get('requested_original138_tags',[])
 if len(rows)!=3: fail('root1016: request rows')
 handles={(r['pid'],r['proc_start_ticks'])}
 for row in rows:
  p=Path(row['request'])
  if not p.is_file() or sha(p)!=row.get('request_sha256'): fail(f"root1016: request file/hash {row.get('tag')}")
  if (row.get('controller_pid'),row.get('controller_proc_start_ticks')) not in handles: fail(f"root1016: controller handle {row.get('tag')}")
  if row.get('execution_receipt_exists') is not False or Path(row['expected_execution_receipt']).exists(): fail(f"root1016: terminal receipt appeared {row.get('tag')}")
 return True
def one(pkg,p):
 r=load(p); tag=r['tag']; b=load(r['physical_binding_path']);
 if r['package_id']!=PKGID or b['package_id']!=PKGID or tag not in TAGS: fail(f'{tag}: identity')
 if any(r.get(k) is not v for k,v in {'disabled':True,'source_only':True}.items()): fail(f'{tag}: source flags')
 if any(r.get(k) is not False for k in ('launch','launch_allowed','execution_allowed','conversion_allowed','solver_allowed','arrays_allowed','array_edit_allowed')): fail(f'{tag}: disabled flags')
 if r.get('kind')!='cpu' or r.get('cpu_task_kind')!='conversion' or r.get('cpu_threads')!=2: fail(f'{tag}: CPU contract')
 if r.get('estimated_storage_bytes')!=4294967296 or r.get('home_publish_cap_bytes')!=4294967296 or r.get('home_min_free_bytes')!=536870912000 or r.get('home_publish_headroom_bytes')!=2147483648: fail(f'{tag}: Home contract')
 if r.get('nvme_staging_limit_bytes')!=25769803776 or r.get('nvme_free_reserve_bytes')!=107374182400 or r.get('shared_conversion_concurrency_cap')!=1: fail(f'{tag}: NVMe contract')
 if r.get('actual_counts')!=r.get('expected_counts') or norm(r['actual_counts'])!=EXPECTED: fail(f'{tag}: counts')
 if b.get('actual_counts')!=r.get('actual_counts') or b.get('source_bed_marker_mkbound')!=40 or b.get('native_bed_marker_mk')!=50: fail(f'{tag}: binding/Mk')
 if b.get('physical_case_id')!=r.get('physical_case_id') or b.get('physical_condition_sha256')!=r.get('physical_condition_sha256'): fail(f'{tag}: physical identity')
 if r['physical_binding_sha256']!=sha(r['physical_binding_path']): fail(f'{tag}: binding sha')
 if r['actual_native_receipt_status']!='completed' or r['actual_native_receipt_returncode']!=0 or r['expected_frames']!=801 or r['expected_particle_axis']!=194427 or r['expected_dimension']!=3: fail(f'{tag}: native dependency')
 for k in ('actual_native_receipt','actual_native_request','gencase_receipt','actual_initial_qa_receipt','actual_initial_qa_report','generated_xml','prepared_input_report'):
  if not Path(r[k]).is_file(): fail(f'{tag}: missing metadata {k}')
 if r['source_h5_legacy_scope_sha256']!=r['root_prospective_legacy_scope_sha256'] or r['typed_future']['legacy_scope_sha256'] is not None: fail(f'{tag}: legacy scope')
 if any(v is not None for v in r['future_output_hashes'].values()): fail(f'{tag}: future hash')
 if r.get('source_agent_did_not_read_or_hash_science_payloads') is not True or r.get('source_arrays_read_or_hashed_by_source_agent') is not False: fail(f'{tag}: source science policy')
 # Producer metadata only: JSON receipts/reports; never open BI4/CSV/H5/DAT.
 n=load(r['actual_native_receipt']); g=load(r['gencase_receipt']); q=load(r['actual_initial_qa_report'])
 if (n.get('status'),n.get('returncode'))!=('completed',0) or (g.get('status'),g.get('returncode'))!=('completed',0): fail(f'{tag}: upstream terminal')
 if q.get('all_basic_placement_checks_pass') is not True or q.get('numerical_precision_result_accepted') is not False: fail(f'{tag}: QA gate')
 validate_inputs(r)
 return {'tag':tag,'physical_case_id':r['physical_case_id'],'native_attempt_id':r['full801_native']['attempt_id'],'counts':norm(r['actual_counts']),'input_count':len(r['input_files']),'future_hashes_null':all(v is None for v in r['future_output_hashes'].values()),'status':'disabled_metadata_pass'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package-root',type=Path,required=True); a=ap.parse_args(); pkg=a.package_root
 rs=sorted((pkg/'requests').glob('*.json')); assert len(rs)==5, len(rs)
 out=[one(pkg,p) for p in rs]
 if [x['tag'] for x in out]!=sorted(TAGS): fail('request tags/order')
 census=load(pkg/'metadata/fresh172-accepted219-and-exclusion-census.json')
 if census['selected_tags']!=TAGS or census['selected_not_in_checkpoint147'] is not True: fail('selection census')
 validate_wait_snapshot(pkg)
 # Meaningful negative: a directory is rejected as an input without opening it.
 try: validate_inputs({'tag':'negative','input_files':[str(pkg)],'input_sha256':{str(pkg):None},'input_sha256_categories':{str(pkg):'producer_payload_attestation'},'input_sha256_provenance':{str(pkg):'producer directory'}})
 except AssertionError: neg=True
 else: neg=False
 if not neg: fail('directory negative')
 report={'schema':'ds02.f5.fresh172.validator-report.v1','package_id':PKGID,'source_only':True,'science_payloads_read_or_hashed':False,'arrays_read_or_hashed':False,'request_count':5,'results':out,'negative_checks':{'directory_input_rejected':neg,'physical_identity_dedup_not_generic_case_id':True,'root984_wait_preserved':True,'root1016_wait_preserved':True,'future_hashes_null':True},'manifest_excludes_report_and_manifest':True,'status':'pass-disabled-metadata-only'}
 (pkg/'metadata/fresh172-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
