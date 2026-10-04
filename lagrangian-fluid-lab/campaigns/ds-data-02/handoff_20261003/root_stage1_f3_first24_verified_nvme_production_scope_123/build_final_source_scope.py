from pathlib import Path
import json,hashlib,sys,subprocess,datetime,copy,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
infra=Path('/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003');S=infra/'root_followup_062_f3_visual_nvme_replica_v1';A=infra/'root_followup_055_stage1_production_adapter_v2'
P=D/'families/F3/F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_REPLICA';copy_receipt=P/'root-stage1-f3-visual-evidence-opaque-nvme-copy-118/replica-receipt.json';audit=P/'root-stage1-f3-visual-nvme-replica-strict-audit-122'
load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();bind=lambda p:{'path':str(p),'sha256':sha(p)}
for p in [copy_receipt.parent/'execution-receipt.json',audit/'execution-receipt.json',audit/'strict-cpu-audit.json']:
 j=load(p);assert (j['status'],j['returncode'])==('completed',0),p
original=H/'root_stage1_f3_first24_actual_production_scope_113';out=H/'root_stage1_f3_first24_verified_nvme_production_scope_123';out.mkdir(exist_ok=False);scope='F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1'
result=subprocess.run([str(L/'.venv/bin/python'),str(S/'derive_visual_scope.py'),'--candidate-index',str(original/'candidate-index.json'),'--scope-id',scope,'--receipt',str(copy_receipt),'--output-dir',str(out)],capture_output=True,text=True);assert result.returncode==0,result.stdout+result.stderr
candidate=load(out/'derived-candidate-index.json');entry=next(e for e in candidate['scopes'] if e['scope_id']==scope)
for e in entry['visual_evidence']['observed']:
 p=Path(e['decision']['path']);j=load(p)
 original_decision=j['derived_visual_replica']['source_case_decision']['source_absolute_path']
 j['derived_visual_replica']['completed_strict_copy_receipt']=bind(copy_receipt.parent/'execution-receipt.json')
 j['derived_visual_replica']['actual_byte_copy_proof']=bind(copy_receipt)
 j['derived_visual_replica']['original_root_case_decision']=bind(original_decision)
 j['derived_visual_replica']['completed_strict_cache_audit']=bind(audit/'execution-receipt.json')
 j['derived_visual_replica']['actual_cache_audit_result']=bind(audit/'strict-cpu-audit.json')
 p.write_text(json.dumps(j,indent=2,ensure_ascii=False)+'\n');e['decision']['sha256']=sha(p)
entry['actual_cache_audit']=bind(audit/'strict-cpu-audit.json')
entry['source_consumed_scope_113_preserved']=True
(out/'derived-scope-entry.json').write_text(json.dumps(entry,indent=2,ensure_ascii=False)+'\n')
(out/'derived-candidate-index.json').write_text(json.dumps(candidate,indent=2,ensure_ascii=False)+'\n')
(out/'requests').mkdir()
sys.path[:0]=[str(A),str(L/'scripts')]
import ds_data02_stage1_production_v2 as auth
manifest=load(original/'case-manifest.json');oldq=load(H/'root_stage1_f3_five_interior_actual_production_059/F3_STAGE1_DP006_P1000_AY0320.json');rows=[r for r in manifest['cases'] if r['case_id'] in entry['selected_case_ids']];assert len(rows)==16
results=[]
for row in rows:
 amplitude=int(round(row['transverse_amplitude_m_s2']*1000))
 q=auth.build_prospective_request(manifest,row['case_id'],family_id='F3',scope_id=scope,attempt_id=f'root-stage1-f3-first24-ay{amplitude:04d}-full836-visual-production-123',adapter_path=A/'ds_data02_stage1_dispatch_v2.py',strict_path=L/'scripts/ds_data02_strict_dispatch_v1.py',runtime_path=L/'scripts/ds_data02_runtime_v2.py',input_files=[str(original/'case-manifest.json'),str(original/'physical-domain.json'),str(original/'root-visual-domain-decision.json'),str(out/'derived-scope-entry.json')],max_wall_seconds=7200,cpu_threads=4,estimated_storage_bytes=16*1024**3,estimated_peak_gpu_mib=8192,worktree_root=str(R),launch_allowed=True,execution_allowed=True,launch_owner='root',future_case_visual_review='required_after_actual_complete_run')
 q['gencase_receipt']=oldq['gencase_receipt'];q['gencase_receipt_sha256']=oldq['gencase_receipt_sha256'];q['schema']='ds02.runner-request.v2'
 context={};hashes=auth.authorize(q,index_path=out/'derived-candidate-index.json',approval_context=context)
 results.append({'case_id':q['case_id'],'authorized_hash_count':len(hashes),'gpu_started':False,'resource_reserved':False})
 (out/'requests'/(q['case_id']+'.json')).write_text(json.dumps(q,indent=2,ensure_ascii=False)+'\n');print(json.dumps(results[-1]),flush=True)
assert len(results)==16
(out/'authorize-preflight.json').write_text(json.dumps({'all16_authorizer_passed':True,'cases':results,'scope_registered':False,'original_source_preserved':True,'precision_accepted':False,'case_count_increment':0},indent=2)+'\n')
shutil.copy2(H/'root_stage1_f3_five_interior_actual_production_059/launch.py',out/'launch.py')
shutil.copy2('/tmp/ds02-build-root123.py',out/'build_final_source_scope.py')
print(out,flush=True)
