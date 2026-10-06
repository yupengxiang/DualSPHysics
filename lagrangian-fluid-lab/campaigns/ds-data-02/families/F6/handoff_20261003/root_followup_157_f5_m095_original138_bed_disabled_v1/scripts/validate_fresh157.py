#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
DENIED={'.h5','.bi4','.dat','.csv','.vtk','.vtu','.npy','.npz','.hdf5','.hdf'}
def load(p):
 with p.open(encoding='utf-8') as f:return json.load(f)
def sha(p):
 if p.suffix.lower() in DENIED: raise AssertionError(f'science payload hash attempted: {p}')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def req(x,msg):
 if not x:raise AssertionError(msg)
def safe_hash_entry(path, expected, label):
 p=Path(path);req(p.is_file(),f'{label} missing: {p}');req(sha(p)==expected,f'{label} SHA mismatch: {p}')
def main():
 contract=load(PKG/'metadata/worker-contract.json'); pre=load(PKG/'metadata/compatibility-preflight.json')
 req(contract['worker_sha256']==sha(Path(contract['worker_path'])),'kernel SHA')
 req(contract['case_count']==2 and contract['cpu_threads']==2 and contract['shared_conversion_concurrency_cap']==1,'serial resource contract')
 req(pre['source_boundary']=={'science_arrays_opened':False,'science_payload_hashed':False,'new_job_started':False,'shared_state_modified':False},'source boundary')
 seen=set()
 for row in pre['cases']:
  bid=Path(row['binding']); rid=Path(row['request']); req(bid.is_file() and rid.is_file(),'case files')
  b=load(bid); r=load(rid); req(b['schema']=='ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1','binding schema')
  req(b['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1','base id')
  pid=b['physical_case_id'];req(pid.startswith('F5_COMPACT_RUNUP_RECOVERY_C082S1_') and pid not in seen,'physical identity');seen.add(pid)
  req(b['next34_identity_adapter_used'] is False and r['disabled'] is True and r['execution_allowed'] is False and r['launch'] is False,'disabled/identity')
  req(b['expected_frames']==801 and b['expected_particles']==194427 and b['expected_dimension']==3,'dimensions')
  c=b['actual_counts'];req(c==b['expected_counts'] and c['solver_dimension']==3 and c['total_particles']==194427 and c['fixed_particles']==158559 and c['moving_particles']==4210 and c['fluid_particles']==31658 and c['floating_particles']==0,'counts')
  sem=b['physical_condition_hash_semantics'];req(len({b['physical_condition_sha256'],b['source_plan_physical_condition_sha256'],b['source_h5_physical_condition_sha256'],b['source_h5_legacy_scope_sha256']})==4,'scope collapse')
  req(sem['roles_remain_distinct'] is True and sem['source_h5_scope_schema']=='legacy-owner-scope.v0','scope semantics')
  for key in ['source_definition','canonical_generated_xml','gencase_receipt','gencase_prepared_report','initial_qa_receipt','initial_qa_report','full_native_receipt','full_typed_receipt','full_typed_conversion_report','xmf_manifest','xmf_receipt','xdmf','source_owner','physical_binding_path','actual983_binding','fresh157_source_plan','fresh157_chain','fresh157_compatibility']:
   p=Path(b[key]);req(p.is_file(),f'binding metadata {key}');
  # Metadata-only safe hashes; the actual H5 and native directory are deliberately excluded.
  for key,hkey in [('source_definition','source_definition_sha256'),('canonical_generated_xml','canonical_generated_xml_sha256'),('gencase_receipt','gencase_receipt_sha256'),('gencase_prepared_report','gencase_prepared_report_sha256'),('initial_qa_receipt','initial_qa_receipt_sha256'),('initial_qa_report','initial_qa_report_sha256'),('full_native_receipt','full_native_receipt_sha256'),('full_typed_receipt','full_typed_receipt_sha256'),('full_typed_conversion_report','full_typed_conversion_report_sha256'),('xmf_manifest','xmf_manifest_sha256'),('xmf_receipt','xmf_receipt_sha256'),('xdmf','xdmf_sha256')]: safe_hash_entry(b[key],b[hkey],key)
  for key in ['gencase_receipt','initial_qa_receipt','full_native_receipt','full_typed_receipt','xmf_receipt']:
   d=load(Path(b[key]));req(d.get('returncode')==0 and d.get('status') in ('completed','completed/0'),f'{key} terminal')
  conv=load(Path(b['full_typed_conversion_report']));req(conv.get('conversion_status')=='completed' and conv.get('frames')==801 and conv.get('particles')==194427,'conversion metadata')
  man=load(Path(b['xmf_manifest']));req(man.get('frames')==801 and man.get('particles')==194427 and man.get('case_id')==b['case_id'] and man.get('physical_case_id')==pid,'XMF metadata')
  req(man.get('source_h5_sha256')==b['trajectory_h5_sha256'] and man.get('physical_condition_sha256')==b['physical_condition_sha256'],'XMF scopes')
  req(len(r['input_files'])==len(r['input_sha256']) and set(r['input_files'])==set(r['input_sha256']),'request input closure')
  req(r['input_sha256'][b['trajectory_h5']]==b['trajectory_h5_sha256'] and r['input_sha256'][b['native_output_root']] is None,'producer-only blocked inputs')
  req(r['future_outputs']['bed_audit_receipt_sha256'] is None and r['future_outputs']['bed_audit_report_sha256'] is None and r['future_outputs']['bed_output_manifest_sha256'] is None,'future null')
  req(r['cpu_threads']==2 and r['serial_dispatch'] is True and r['shared_conversion_concurrency_cap']==1 and r['cpu_task_kind']=='audit','CPU contract')
  req(r['input_sha256'][str(bid)]==sha(bid) and r['binding_sha256']==sha(bid),'binding hash closure')
  req(sha(rid)==row['request_sha256'],'request index hash')
  req(row['physical_case_id']==pid,'preflight physical id')
 # Package manifest is intentionally not self-hashed.
 print('fresh157 metadata-only validator: PASS; cases=2; science_payloads_opened_or_hashed=0; jobs_started=0')
if __name__=='__main__':main()
