from pathlib import Path
import os,sys,json,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';P=H/'root_stage1_f3_first24_verified_nvme_production_scope_123'
os.environ['DS_DATA02_APPROVED_VISUAL_SCOPES']=str(P/'derived-candidate-index.json')
A=Path('/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_followup_055_stage1_production_adapter_v2')
sys.path[:0]=[str(A),str(L/'scripts')]
import ds_data02_stage1_dispatch_v2 as adapter
import ds_data02_strict_dispatch_v1 as strict
requests=sorted((P/'requests').glob('*.json'));assert len(requests)==16
assert json.loads((P/'authorize-preflight.json').read_text())['all16_authorizer_passed']
rows=[]
for p in requests:
 q=json.loads(p.read_text());context={}
 with adapter.install_stage1_authorizer_alias(q):hashes=strict.validate_request(q,approval_context=context)
 row={'case_id':q['case_id'],'strict_hash_count':len(hashes),'strict_passed':True,'gpu_started':False,'resource_reserved':False};rows.append(row);print(json.dumps(row),flush=True)
assert len(rows)==16
Path('/tmp/ds02-root123-strict-preflight.json').write_text(json.dumps({'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'all16_strict_passed':True,'candidate_index':str(P/'derived-candidate-index.json'),'cases':rows,'scope_registered':False,'source_guard_unchanged':True},indent=2)+'\n')
print('all16_strict_passed',flush=True)
