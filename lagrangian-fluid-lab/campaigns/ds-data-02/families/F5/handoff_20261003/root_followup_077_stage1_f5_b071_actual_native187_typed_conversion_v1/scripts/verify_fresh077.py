#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071')
CASE='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071'
NATIVE=DATA/'root-stage1-f5-b071-short-native-qualification-187/execution-receipt.json'
NATIVE_SHA='b1028f85aa11eb6890dd8c7d9206f9414aff739a473aee9b47b64217a4cc546a'
NATIVE_REQUEST_SHA='4bc13b5bf347113a4c89ebf3bd105a995caa302dd1df541bc227fd86803e0658'
GEN=DATA/'root-stage1-f5-b071-genuine-gencase-163/execution-receipt.json'
QA=DATA/'root-stage1-f5-b071-initial-qa-output-root-binding-repair-175/execution-receipt.json'
COV=DATA/'root-stage1-f5-b071-native-bed-marker-mapping-repair-185/execution-receipt.json'

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while True:
   b=f.read(1024*1024)
   if not b: break
   h.update(b)
 return h.hexdigest()
def load(p):
 with p.open(encoding='utf-8') as f:return json.load(f)
def req(c,m):
 if not c: raise AssertionError(m)
def rid(x):
 r=x.get('request') if isinstance(x.get('request'),dict) else {}
 return x.get('case_id') or r.get('case_id')

def receipt(p, expected, label):
 req(p.is_file(),label+' missing');req(sha(p)==expected,label+' hash');x=load(p);req(x.get('schema')=='ds02.execution-receipt.v1',label+' schema');req(x.get('status')=='completed' and x.get('returncode')==0,label+' status');req(rid(x)==CASE,label+' nested case');return x
b=load(ROOT/'binding.json');a=load(ROOT/'actual-native187-binding.json');t=load(ROOT/'typed-conversion-request.json');x=load(ROOT/'xmf-binding-template.json');xr=load(ROOT/'xmf-request-template.json');br=load(ROOT/'short-bed-audit-binding-template.json');q=load(ROOT/'short-bed-audit-request.json');rr=load(ROOT/'render-request-template.json');d=load(ROOT/'downstream-disabled.json');m=load(ROOT/'manifest.json')
req(b['package_id']=='root_followup_077_stage1_f5_b071_actual_native187_typed_conversion_v1','package');req(b['actual_native_qualification']['native_attempt']['attempt_id']=='root-stage1-f5-b071-short-native-qualification-187','native binding')
n=receipt(NATIVE,NATIVE_SHA,'native187');g=receipt(GEN,'52ce589ee3cb51136daf7188c0cedbc5a43999e28ee13557942d646d115c56dd','gencase');qa=receipt(QA,'d5ff39fe430b0dc2047cd6489dd8e1d2384fd1330c7527ad4f7a3ee50eb0e268','qa');cov=receipt(COV,'74cfb6c7e690c8572c0387e2e5c343d9a3a61018b5efc4224d3cf729b1fad818','root185')
req(n.get('request_sha256')==NATIVE_REQUEST_SHA,'native request hash');nr=n['request'];req(nr.get('case_id')==CASE and nr.get('attempt_id')=='root-stage1-f5-b071-short-native-qualification-187','native request identity');req(nr.get('physical_condition_sha256')=='d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f','native condition');req(nr.get('source_plan_physical_condition_sha256')=='e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72','native source plan');req(nr.get('expected_frames')==51 and nr.get('expected_particle_axis')==174896 and nr.get('expected_fluid_particles')==40710,'native counts');req(nr.get('all_saved_frames_contract',{}).get('uniform_time_spacing_assumption') is False,'native time contract');req('-tmax:1.0' in n.get('command',[]) and '-tout:0.02' in n.get('command',[]),'actual native command')
req(a['native_attempt']['receipt_sha256']==NATIVE_SHA and a['native_attempt']['request_sha256']==NATIVE_REQUEST_SHA,'actual binding hashes');req(a['contract']['full16_authorized'] is False and a['contract']['full801_authorized'] is False,'native acceptance gate');req(a['array_policy']['source_agent_opened_h5'] is False,'native array policy')
req(t['schema']=='ds02.runner-request.v2' and t['cpu_task_kind']=='conversion' and t['cpu_threads']==2,'strict CPU conversion');req(t['launch_allowed'] is False and t['execution_allowed'] is False and t['conversion_allowed'] is False,'conversion disabled');req(t['depends_on_attempt']=='root-stage1-f5-b071-short-native-qualification-187','conversion dependency');req(t['command'][0].endswith('/.venv/bin/python'),'LAB venv');req('/tmp/ds02-nvme-conversion' in t['command'] and '25769803776' in t['command'],'NVMe staging');req(t['nvme_policy']['concurrency']==2 and t['nvme_policy']['staging_peak_limit_bytes']==25769803776 and t['nvme_policy']['free_space_floor_bytes']==107374182400,'NVMe cap2 policy');req(t['actual_bindings']['short_solver_receipt']==str(NATIVE) and t['actual_bindings']['short_solver_receipt_sha256']==NATIVE_SHA,'native receipt bound to conversion');req(t['future_bindings']['output_hdf5_sha256'] is None and t['future_bindings']['conversion_report_sha256'] is None,'future typed hashes null');req(not any('resource-ledger.json' in z for z in t['input_files']),'live ledger');req(not any(str(z).lower().endswith(('.h5','.csv','.bi4')) for z in t['input_files']),'future arrays registered as immutable source');req(t['independent_case_count_increment']==0 and t['full801_authorized'] is False and t['full16_authorized'] is False,'conversion gate')
for name,z in [('xmf',xr),('bed',q),('render',rr)]:
 req(z['launch_allowed'] is False and z['execution_allowed'] is False,name+' enabled');req(z.get('full801_authorized') is False and z.get('full16_authorized') is False,name+' full gate');req(not any('resource-ledger.json' in str(v) for v in z.get('input_files',[])),name+' ledger')
req(x['native_receipt']==str(NATIVE) and x['native_receipt_sha256']==NATIVE_SHA,'XMF native role');req(x['typed_receipt_sha256'] is None and x['trajectory_h5_sha256'] is None,'XMF future products');req(br['short_solver_receipt']==str(NATIVE) and br['short_solver_receipt_sha256']==NATIVE_SHA,'bed native role');req(rr['future_bindings']['xmf_manifest_sha256'] is None and rr['future_bindings']['xmf_sha256'] is None,'render future products')
req(d['stages']['full801_native']['full801_authorized'] is False,'full801 disabled');req(d['actual_native187_completed0'] is True,'downstream native status')
for rel in ('workers/bed_audit.py','workers/export_xmf.py','workers/render_full_saved_animation.py','scripts/verify_fresh077.py'):
 s=(ROOT/rel).read_text(encoding='utf-8');ast.parse(s,filename=rel);req('hashlib' in s and 'read(' in s,'hash helper '+rel)
 if rel!='scripts/verify_fresh077.py':req('UnboundLocalError' not in s,'sentinel '+rel)
for rel,expected in m['files'].items():
 p=ROOT/rel;req(p.is_file(),'manifest file '+rel);req(sha(p)==expected,'manifest hash '+rel)
req('manifest.json' not in m['files'],'manifest cycle')
print(json.dumps({'status':'metadata_ast_pass','native187':'completed0_nested_case_bound','native187_request_sha256':NATIVE_REQUEST_SHA,'typed189_request_disabled':True,'cpu_task_kind':'conversion','cpu_threads':2,'nvme_staging_peak_bytes':25769803776,'nvme_free_floor_bytes':107374182400,'xmf_bed_render_disabled':True,'full801_authorized':False,'arrays_opened':False,'jobs_started':False},sort_keys=True))
