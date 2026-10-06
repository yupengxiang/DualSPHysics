#!/usr/bin/env python3
"""Fresh166 metadata-only validator: every runtime input is a regular file.
No science payload is opened or hashed; opaque hashes are producer attestations.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, tempfile
from pathlib import Path
SAFE={'.json','.xml','.py','.md','.sh','.toml','.ini','.yaml','.yml'}
SCIENCE={'.bi4','.dat','.csv','.h5','.vtk','.vtu','.pvtu','.png','.jpg','.jpeg','.npy','.npz','.bin'}
EXPECTED={'total_particles':194427,'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'solver_dimension':3,'data2d':False}
WORKER_SHA='37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11'
PACKAGE_ID='F5_fresh166_native_ready_typed157_home4gib_no_directory_inputs'
TOOL_ATTESTATIONS={
 'python':{'path':'/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python','resolved_receipt_path':'/usr/bin/python3.10','sha256':'a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae','source_fields':['input_hashes_at_launch','input_hashes_after_run'],'source_kind':'actual_terminal_producer_receipt_input_hashes_resolved_path'},
 'gencase':{'path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64','resolved_receipt_path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64','sha256':'a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226','source_fields':['input_hashes_at_launch','input_hashes_after_run'],'source_kind':'actual_terminal_producer_receipt_input_hashes_resolved_path'},
 'solver':{'path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64','resolved_receipt_path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64','sha256':'0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29','source_fields':['input_hashes_at_launch','input_hashes_after_run'],'source_kind':'actual_terminal_producer_receipt_input_hashes_resolved_path'},
 'decoder':{'path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump','resolved_receipt_path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump','sha256':'b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e','source_fields':['input_hashes_at_launch','input_hashes_after_run'],'source_kind':'actual_terminal_producer_receipt_input_hashes_resolved_path'},
 'partvtk':{'path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64','resolved_receipt_path':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64','sha256':'62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00','source_fields':['input_hashes_at_launch','input_hashes_after_run'],'source_kind':'actual_terminal_producer_receipt_input_hashes_resolved_path'},
}
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
def validate_tool_attestations(req):
 attest=req.get('registered_tool_attestations')
 if not isinstance(attest,dict) or set(attest)!=set(TOOL_ATTESTATIONS): fail(f"{req.get('tag')}: registered binary attestation names")
 for name,expected in TOOL_ATTESTATIONS.items():
  actual=attest.get(name)
  if not isinstance(actual,dict): fail(f"{req.get('tag')}: missing tool attestation {name}")
  for key in ('path','resolved_receipt_path','sha256','source_fields','source_kind'):
   if actual.get(key)!=expected[key]: fail(f"{req.get('tag')}: tool attestation {name}.{key}")
  if actual.get('source_did_not_read_or_hash_binary') is not True: fail(f"{req.get('tag')}: tool source read/hash claim")
  receipt=Path(actual.get('source_receipt',''))
  if not receipt.is_file() or receipt.suffix.lower()!='.json': fail(f"{req.get('tag')}: tool receipt path {name}")
  if not actual.get('source_receipt_sha256') or hashlib.sha256(receipt.read_bytes()).hexdigest()!=actual['source_receipt_sha256']: fail(f"{req.get('tag')}: tool receipt metadata hash {name}")
  rd=load(receipt)
  for field in expected['source_fields']:
   if not isinstance(rd.get(field),dict) or rd[field].get(expected['resolved_receipt_path'])!=expected['sha256']:
    fail(f"{req.get('tag')}: tool receipt field {name}.{field}")
  path=expected['path']
  if path not in req['input_files'] or req['input_sha256'].get(path)!=expected['sha256'] or req['input_sha256_categories'].get(path)!='registered_binary_attestation':
   fail(f"{req.get('tag')}: tool input closure {name}")
  provenance=req['input_sha256_provenance'].get(path,'')
  if 'input_hashes_at_launch' not in provenance or 'input_hashes_after_run' not in provenance or expected['source_kind'] not in actual.get('source_kind',''):
   fail(f"{req.get('tag')}: tool receipt provenance {name}")
 check=req.get('tool_attestation_source_check')
 if not isinstance(check,dict) or check.get('producer_receipt_metadata_only') is not True or check.get('science_payloads_read_or_hashed_by_source_agent') is not False:
  fail(f"{req.get('tag')}: tool attestation source check")
def validate_one(pkg,rp,worker_contract):
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
 if req['physical_binding_sha256']!=sha_safe(bp) or bind['schema']!='ds02.f5.fresh166.native-ready-typed157-binding.v1': fail(f'{tag}: binding')
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
 validate_tool_attestations(req)
 if worker_contract.get('registered_binary_attestations') != req['registered_tool_attestations']:
  fail(f'{tag}: worker/request tool attestation mismatch')
 if req['command_provenance']['worker_sha256']!=WORKER_SHA or not any('nvme_convert_home_capped_v2.py' in x for x in req['command']): fail(f'{tag}: worker')
 for x in ('--home-publish-cap-bytes','4294967296','--home-floor-bytes','536870912000','--home-publish-headroom-bytes','2147483648','--nvme-free-reserve-bytes','107374182400','--current-attempt-id',req['current_attempt_id']):
  if x not in req['command']: fail(f'{tag}: command guard {x}')
 if not isinstance(req['scientific_data_root'],dict) or not req['source_provenance']['producer_directories']: fail(f'{tag}: directory provenance fields')
 return {'tag':tag,'case_id':req['case_id'],'physical_case_id':req['physical_case_id'],'actual_native_attempt':n['request']['attempt_id'],'counts':norm(req['actual_counts']),'input_count':len(req['input_files']),'directories_not_inputs':all(Path(x).is_file() for x in req['input_files']),'status':'metadata-pass-disabled'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package-root',type=Path,required=True); a=ap.parse_args(); pkg=a.package_root; rs=sorted((pkg/'requests').glob('*.json'));
 if len(rs)!=12: fail(f'request count {len(rs)}')
 worker_contract=load(pkg/'metadata/worker-contract.json')
 if worker_contract.get('registered_binary_attestations') is None or worker_contract.get('tool_attestation_policy',{}).get('all_registered_binaries_require_resolved_receipt_hash') is not True:
  fail('worker tool attestation policy')
 results=[validate_one(pkg,p,worker_contract) for p in rs]
 if len({x['tag'] for x in results})!=12: fail('duplicate tags')
 # Meaningful negative: the regular-file guard rejects a synthetic directory input.
 try:
  validate_input_closure({'input_files':[str(pkg)],'input_sha256':{str(pkg):None},'input_sha256_provenance':{str(pkg):'producer_directory'},'input_sha256_categories':{str(pkg):'producer_directory'}})
 except AssertionError: directory_negative=True
 else: directory_negative=False
 if not directory_negative: fail('directory-input negative did not reject')
 stale=copy.deepcopy(json.loads((rs[0]).read_text()))
 stale['registered_tool_attestations']['decoder']['sha256']='b8ac8cf4c71c1f0b238d1c89fbe3f2e36b1a7c2d8b2a9c7202d8d80d4dfca1ce'
 try:
  validate_tool_attestations(stale)
 except AssertionError:
  stale_decoder_negative=True
 else:
  stale_decoder_negative=False
 if not stale_decoder_negative: fail('stale decoder attestation negative did not reject')
 manifest=load(pkg/'manifest.json')
 for rel,h in manifest['files'].items():
  p=pkg/rel
  if not p.is_file() or sha_safe(p)!=h: fail(f'manifest mismatch {rel}')
 report={'schema':'ds02.f5.fresh166.validator-report.v2','package_id':PACKAGE_ID,'source_only':True,'arrays_read_or_hashed':False,'science_payloads_read_or_hashed':False,'request_count':12,'results':results,'negative_checks':{'directory_input_rejected':True,'prospective_legacy_scope_bound_and_future_null':True,'stale_decoder_digest_rejected':stale_decoder_negative},'registered_binary_attestation_source_checked':True,'manifest_checked':True,'manifest_excludes_report_and_manifest':True,'future_hashes_null':True,'status':'pass-disabled-metadata-only'}
 (pkg/'metadata/fresh166-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
