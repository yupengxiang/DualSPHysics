#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCIENCE = {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
HEX = set('0123456789abcdef')
BASE = 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1'
PRODUCER = 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34'
CANONICAL = '89a891b45dae3220aaa64f9b8764645cece3164633fb45fc57c0ad8f51c734f3'
SOURCE_PLAN = '85d0e0af79ae69aeb83d88a21c4b277e321169167145c74e215d3d246704cb70'
LEGACY = 'ff41cd47740e7d7532982b004ef761ec97feb4b72cbfc77bcd7b3666df0d72c1'
BED_SHA = '89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2'
XMF_SHA = 'aeccc3204d751250bd94ffab704ed65c2c691c4739f4b2f5e0d51aefb21b4e3c'
def load(p): return json.loads(pathlib.Path(p).read_text())
def sha(p):
 p=pathlib.Path(p)
 if p.suffix.lower() in SCIENCE: raise AssertionError(f'science hash forbidden: {p}')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def req(x,m):
 if not x: raise AssertionError(m)
def validate_binding(p, base_path):
 b=load(p); base=load(base_path)
 req(b['schema']=='ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1','bed schema')
 req(base['case_id']==BASE and base['producer_case_id']==PRODUCER,'base identity')
 req(b['case_id']==PRODUCER and b['producer_case_id']==PRODUCER,'producer identity')
 req(b['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T085','physical identity')
 req(b['physical_condition_sha256']==CANONICAL and b['source_plan_physical_condition_sha256']==SOURCE_PLAN and b['source_h5_physical_condition_sha256']==LEGACY,'scope values')
 req(sha(base_path)==b['identity_adapter']['base_binding_sha256'],'base binding SHA')
 for key in ('physical_case_id','physical_condition_sha256','source_plan_physical_condition_sha256','source_h5_physical_condition_sha256','actual_counts','expected_frames','expected_dimension','expected_particle_axis','native_bed_marker_mk','source_bed_marker_mkbound','full_native_receipt','full_typed_receipt','full_typed_conversion_report','canonical_generated_xml'):
  req(b.get(key)==base.get(key),f'nonidentity field changed: {key}')
 mutable={'xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256','xmf_receipt','xmf_receipt_sha256'}
 stripped=lambda x:{k:v for k,v in x.items() if k not in ('case_id','producer_case_id','identity_adapter') and k not in mutable}
 req(stripped(b)==stripped(base),'nonidentity binding mutation')
 ia=b['identity_adapter']; req(ia['base_case_id']==BASE and ia['producer_case_id']==PRODUCER,'adapter identity'); req(ia['original_worker_sha256']==BED_SHA and ia['numerical_logic_unchanged'] is True and ia['array_edit_allowed'] is False,'adapter logic policy')
 return b

def main():
 plan=load(ROOT/'metadata/fresh159-source-plan.json'); contract=load(ROOT/'metadata/worker-contract.json')
 req(plan['source_only'] and plan['no_jobs_started'] and plan['no_shared_state_modified'],'source policy')
 req(sha(pathlib.Path(contract['original_fresh138_bed_worker']))==BED_SHA,'bed worker source SHA')
 req(sha(pathlib.Path(contract['original_xmf_worker']))==XMF_SHA,'xmf worker source SHA')
 base_bed=ROOT/'..'/'root_followup_158_m095_t080_typed_downstream_disabled_v1/bindings/M086_T085-full801-bed-binding.json'
 base_xmf=ROOT/'..'/'root_followup_158_m095_t080_typed_downstream_disabled_v1/bindings/M086_T085-full801-xmf-binding.json'
 # Resolve from package's sibling handoff directory.
 base_bed=ROOT.parent/'root_followup_158_m095_t080_typed_downstream_disabled_v1/bindings/M086_T085-full801-bed-binding.json'
 base_xmf=ROOT.parent/'root_followup_158_m095_t080_typed_downstream_disabled_v1/bindings/M086_T085-full801-xmf-binding.json'
 x=load(ROOT/'bindings/M086_T085-identity-bound-xmf-binding.json'); b=validate_binding(ROOT/'bindings/M086_T085-identity-bound-bed-binding.json',base_bed)
 req(x['schema']=='ds02.f5.c082s1.full801.xmf-binding.fresh158.v1' and x['case_id']==PRODUCER and x['producer_case_id']==PRODUCER,'xmf identity')
 req(sha(base_xmf)==x['identity_adapter']['base_binding_sha256'],'xmf base SHA')
 req(x['physical_condition_sha256']==CANONICAL and x['source_h5_physical_condition_sha256']==LEGACY,'xmf scopes')
 for stage, binding, cmd in [('xmf',ROOT/'bindings/M086_T085-identity-bound-xmf-binding.json',ROOT/'requests/M086_T085-identity-bound-xmf-request.json'),('bed',ROOT/'bindings/M086_T085-identity-bound-bed-binding.json',ROOT/'requests/M086_T085-identity-bound-bed-request.json')]:
  q=load(cmd); req(q['disabled'] and not q['execution_allowed'] and not q['launch_allowed'],f'{stage} disabled'); req(q['kind']=='cpu' and q['cpu_task_kind']=='audit' and q['cpu_threads']==2,f'{stage} runtime'); req(q['binding']==str(binding),f'{stage} binding'); req(q['binding_sha256']==sha(binding),f'{stage} binding hash'); req(all(v is None for v in q['future_output_hashes'].values()),f'{stage} future hash')
  if stage=='bed': req('--trajectory-h5' in q['command'] and '--xdmf' in q['command'] and '--output-dir' in q['command'] and '--output' not in q['command'],'bed CLI')
  for path,h in q['input_sha256'].items(): req(pathlib.Path(path).suffix.lower() not in SCIENCE,f'science input {path}'); req(pathlib.Path(path).is_file() and sha(path)==h,f'input hash {path}')
 # Metadata-only upstream receipt identity checks; no H5/BI4/CSV/DAT/VTK opened.
 for key in ('full_typed_receipt','full_native_receipt','gencase_receipt','initial_qa_receipt'):
  p=pathlib.Path(b[key]); d=load(p); nested=d.get('request',{}); req(nested.get('case_id',d.get('case_id'))==PRODUCER,f'{key} nested producer identity')
 report={'schema':'ds02.f5.fresh159.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'identity_or_xmf_metadata_only_rebound':True,'fresh138_numeric_logic_unchanged':True,'checks':{'base_and_producer_identity':True,'canonical_source_plan_legacy_separate':True,'m086_receipt_nested_identity':True,'all_requests_disabled':True,'future_hashes_null':True,'bed_cli_correct':True,'original_worker_hashes':True}}
 (ROOT/'metadata/fresh159-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
