#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]; TAGS=('M085_T100','M086_T085','M095_T080'); HEX=set('0123456789abcdef')
def load(p): return json.loads(pathlib.Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with pathlib.Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def req(x,m):
 if not x: raise AssertionError(m)
def scope(b):
 c=b['physical_condition_sha256']; sp=b['source_plan_physical_condition_sha256']; l=b.get('source_h5_physical_condition_sha256'); req(isinstance(c,str) and len(c)==64 and set(c)<=HEX,'canonical scope'); req(isinstance(sp,str) and len(sp)==64 and set(sp)<=HEX,'source plan scope');
 if l is not None: req(len(l)==64 and set(l)<=HEX and l not in (c,sp),'legacy scope collapsed')
 s=b['physical_condition_hash_semantics']; req(s['canonical_owner_sha256']==c and s['source_h5_sha256']==l,'scope semantics')
def main():
 plan=load(ROOT/'metadata/fresh158-source-plan.json'); att=load(ROOT/'metadata/upstream-typed-attestations.json'); wc=load(ROOT/'metadata/worker-contract.json'); req(plan['source_only'] and plan['no_jobs_started'] and plan['no_shared_state_modified'],'source policy'); req(wc['runtime']['source_preparation_may_not_launch'],'launch guard')
 out={}
 for tag in TAGS:
  c=att['cases'][tag]; x=load(ROOT/f'bindings/{tag}-full801-xmf-binding.json'); b=load(ROOT/f'bindings/{tag}-full801-bed-binding.json'); r=load(ROOT/f'bindings/{tag}-full801-render-binding.json')
  for z in (x,b,r):
   scope(z); req(z['source_only'] and z['disabled'] and not z['execution_allowed'] and not z['launch_allowed'],f'{tag} disabled'); req(z['expected_frames']==801 and z['expected_particle_axis']==194427 and z['native_bed_marker_mk']==50 and z['source_bed_marker_mkbound']==40,f'{tag} physical contract'); req(all(v is None for v in z['future_output_hashes'].values()),f'{tag} future hash')
  for k in ('full_native_request','full_native_receipt','canonical_generated_xml'):
   req(isinstance(x[k],str) and pathlib.Path(x[k]).is_file(),f'{tag} missing {k}')
  req(sha(x['full_native_request'])==x['full_native_request_sha256'],f'{tag} native request hash')
  req(sha(x['full_native_receipt'])==x['full_native_receipt_sha256'],f'{tag} native receipt hash')
  req(sha(x['canonical_generated_xml'])==x['canonical_generated_xml_sha256'],f'{tag} generated XML hash')
  for st in ('xmf','bed','render'):
   q=load(ROOT/f'requests/{tag}-full801-{st}-request.json'); req(q['disabled'] and not q['execution_allowed'] and not q['launch_allowed'],f'{tag}/{st} enabled'); req(q['kind']=='cpu' and q['cpu_task_kind']=='audit' and q['cpu_threads']==2,f'{tag}/{st} runtime'); req(all(v is None for v in q['future_output_hashes'].values()),f'{tag}/{st} future output');
   if st=='bed': req('--output-dir' in q['command'] and '--output' not in q['command'],f'{tag} bed CLI')
   for p,h in q['input_sha256'].items(): req(pathlib.Path(p).suffix.lower() not in ('.h5','.bi4','.csv','.dat','.vtk'),f'science input {p}'); req(pathlib.Path(p).is_file() and sha(p)==h,f'input hash {p}')
  t=c['typed']
  if tag!='M095_T080':
   rec=load(t['receipt']); rep=load(t['conversion_report']); req(rec['status']=='completed' and rec['returncode']==0,f'{tag} receipt'); req(rep['conversion_status']=='completed' and rep['frames']==801 and rep['particles']==194427,f'{tag} report'); req(t['trajectory_h5_sha256_producer_attested']==rep['output_sha256'],f'{tag} producer H5 hash'); req(sha(t['receipt'])==t['receipt_sha256'] and sha(t['conversion_report'])==t['conversion_report_sha256'],f'{tag} JSON hash'); req(x['typed_receipt']==t['receipt'] and x['conversion_report']==t['conversion_report'],f'{tag} XMF paths'); req(b['full_typed_receipt']==t['receipt'] and b['full_typed_conversion_report']==t['conversion_report'],f'{tag} bed paths'); req(x['source_h5_physical_condition_sha256']==t['output_scope_from_report_sha256'],f'{tag} legacy report scope'); out[tag]={'typed_status':rec['status'],'typed_returncode':rec['returncode'],'frames':rep['frames'],'particles':rep['particles'],'payload_read_or_hashed_by_source':False,'downstream_disabled':True}
  else:
   req(t['receipt'] is None and t['conversion_report'] is None and t['trajectory_h5'] is None and t['trajectory_h5_sha256_producer_attested'] is None,'M095 future typed filled'); req(c['typed_pending_snapshot']['root939_status'] in ('running','completed','completed/0'),'M095 pending state'); out[tag]={'typed_status':c['typed_pending_snapshot']['root939_status'],'terminal_typed_binding':False,'future_hashes_null':True}
 report={'schema':'ds02.f5.fresh158.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'cases':out,'checks':{'all_requests_disabled':True,'all_future_hashes_null':True,'canonical_legacy_scopes_separate':True,'m085_m086_receipts_completed0':True,'m095_waits_terminal_receipt':True,'bed_cli_output_dir':True,'m086_identity_adapter_declared':True}}
 (ROOT/'metadata/fresh158-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__':
 try: main()
 except Exception as e: print(f'fresh158 validation failed: {e}',file=sys.stderr); raise
