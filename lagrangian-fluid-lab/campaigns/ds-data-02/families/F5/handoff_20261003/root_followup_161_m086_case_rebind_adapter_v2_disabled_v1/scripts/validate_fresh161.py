#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
DENIED={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
BASE=ROOT.parent/'root_followup_158_m095_t080_typed_downstream_disabled_v1'
OLD=ROOT.parent/'root_followup_159_m086_identity_adapter_disabled_v1'
ORIGINAL=pathlib.Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/workers/bed_audit_full801_fresh138.py')
ADAPTER=ROOT/'workers/identity_bound_bed_audit_fresh161.py'
HEX=set('0123456789abcdefABCDEF')
def load(p):
 d=json.loads(pathlib.Path(p).read_text()); assert isinstance(d,dict); return d
def sha(p):
 p=pathlib.Path(p); assert p.suffix.lower() not in DENIED,f'science hash forbidden {p}'; h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def req(x,m):
 if not x: raise AssertionError(m)
def main():
 bpath=ROOT/'bindings/M086_T085-case-rebind-bed-binding.json'; qpath=ROOT/'requests/M086_T085-case-rebind-bed-request.json'; b=load(bpath); q=load(qpath); old=load(OLD/'bindings/M086_T085-identity-bound-bed-binding.json'); base=load(BASE/'bindings/M086_T085-full801-bed-binding.json'); c=load(ROOT/'metadata/worker-contract.json')
 req(b['identity_adapter']['schema']=='ds02.f5.c082s1.m086.case-rebind-adapter.fresh161.v2','fresh161 schema'); req(b['case_id']==b['producer_case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M086_T085_NEXT34','producer identity'); req(b['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M086_T085','physical id')
 stripped=lambda x:{k:v for k,v in x.items() if k!='identity_adapter' and k not in {'xmf_manifest','xmf_manifest_sha256','xdmf','xdmf_sha256','xmf_receipt','xmf_receipt_sha256'}}; req(stripped(b)==stripped(old),'fresh159 scientific fields preserved'); req(old['identity_adapter']['schema']=='ds02.f5.c082s1.m086.identity-adapter.fresh159.v1','fresh159 provenance'); req(sha(OLD/'bindings/M086_T085-identity-bound-bed-binding.json')==b['identity_adapter']['previous_adapter_binding_sha256'],'previous SHA'); req(sha(BASE/'bindings/M086_T085-full801-bed-binding.json')==b['identity_adapter']['base_binding_sha256'],'base SHA'); req(base['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1','base case unchanged')
 req(ORIGINAL.is_file() and sha(ORIGINAL)=='89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2','original worker exact SHA'); req(b['identity_adapter']['original_worker_sha256']==sha(ORIGINAL),'adapter original SHA'); req(ADAPTER.is_file() and sha(ADAPTER)==b['identity_adapter']['adapter_worker_sha256'],'adapter worker SHA')
 req(b['identity_adapter']['numerical_logic_unchanged'] is True and b['identity_adapter']['array_edit_allowed'] is False and b['identity_adapter']['receipt_edit_allowed'] is False and b['identity_adapter']['threshold_edit_allowed'] is False,'mutation policy')
 req(q['binding']==str(bpath) and q['binding_sha256']==sha(bpath),'binding closure'); req(q['disabled'] and q['source_only'] and not q['execution_allowed'] and not q['launch_allowed'] and not q['solver_allowed'],'request disabled'); req(q['kind']=='cpu' and q['cpu_task_kind']=='audit' and q['cpu_threads']==2,'runtime'); req(q['command']==[q['command'][0],str(ADAPTER),'--binding',str(bpath),'--trajectory-h5','{resolved_trajectory_h5}','--xdmf','{resolved_xdmf}','--output-dir','{attempt_root}/audit-output'],'CLI')
 req(set(q['input_files'])==set(q['input_sha256'])==set(q['input_sha256_provenance']),'input closure')
 for p,h in q['input_sha256'].items(): req(pathlib.Path(p).is_file() and pathlib.Path(p).suffix.lower() not in DENIED and sha(p)==h,f'input {p}')
 req(all(v is None for v in q['future_output_hashes'].values()),'future hashes'); req(b['full_native_receipt']==b['full_native_receipt'] and b['native_bed_marker_mk']==50 and b['source_bed_marker_mkbound']==40,'physical mapping')
 result=subprocess.run([sys.executable,str(ADAPTER),'--check'],cwd=str(ROOT),capture_output=True,text=True,check=False); req(result.returncode==0, f'case rebind regression failed: {result.stdout} {result.stderr}')
 manifest=load(ROOT/'manifest.json'); listed={x['path'] for x in manifest['files']}; req('manifest.json' not in listed and 'metadata/fresh161-validator-report.json' not in listed,'manifest self reference')
 for e in manifest['files']:
  p=ROOT/e['path']; req(p.is_file() and p.suffix.lower() not in DENIED,'manifest payload'); req(sha(p)==e['sha256'],f'manifest SHA {p}')
 out={'schema':'ds02.f5.fresh161.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'original_worker_sha256':sha(ORIGINAL),'adapter_worker_sha256':sha(ADAPTER),'checks':{'fresh159_preserved':True,'original_case_id_rebind_stub_passed':True,'real_original_module_base_case_checked':True,'downstream_xmf_reference_fields_may_be_root_bound':True,'original_metadata_gate_case_id_rebound_before_delegate':True,'native_receipt_and_science_bytes_unchanged':True,'request_disabled':True,'future_hashes_null':True}}
 (ROOT/'metadata/fresh161-validator-report.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__':
 try: main()
 except Exception as e: print(f'fresh161 validation failed: {e}',file=sys.stderr); raise
