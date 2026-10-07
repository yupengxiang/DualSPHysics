"""Validate planning metadata only. No solver, GPU, scientific array or model IO."""
from pathlib import Path
import json,math,hashlib
R=Path(__file__).resolve().parent
read=lambda n:json.loads((R/n).read_text())
p=read('CAMPAIGN_PLAN.json');m=read('SENTINEL_MATRIX.json');results=[]
def ck(name,test):
 if not test:raise AssertionError(name)
 results.append({'check':name,'pass':True})
for k in ['learning_training','learning_inference','model_checkpoint_replay','public_release','hidden_test_generation','modify_stage1_bytes','rewrite_historical_receipts']:
 ck('scope_false:'+k,p['scope'][k] is False)
ck('seven_family_tasks',all((R/f'families/F{i}.md').is_file()for i in range(1,8)))
ck('fourteen_existing_sentinels',len(m['sentinels'])==14 and len({r['source_physical_case_id']for r in m['sentinels']})==14)
for f in [f'F{i}'for i in range(1,8)]:
 ck('two_sentinels:'+f,len([r for r in m['sentinels']if r['family']==f])==2)
for r in m['sentinels']:
 ck('finite_positive_spacing:'+r['sentinel_id'],all(math.isfinite(x)and x>0 for x in r['proposed_spacing_m']))
 ck('center_spacing_is_actual:'+r['sentinel_id'],r['proposed_spacing_m'][1]==r['actual_dp_m'])
 ck('half_cfl_distinct:'+r['sentinel_id'],r['proposed_half_cfl']==r['baseline_cfl']/2)
ck('suballocations_sum_to_cap',sum(p['qualification_attempt_buckets'].values())==p['stage2_soft_budget']['qualification_attempts'])
b=p['parent_budget_snapshot'];s=p['stage2_soft_budget']
ck('gpu_within_reported_parent_remaining',s['gpu_hours']<=b['gpu_hours_total']-b['gpu_hours_used'])
ck('cpu_within_reported_parent_remaining',s['cpu_core_hours']<=b['cpu_core_hours_total']-b['cpu_core_hours_used'])
ck('attempts_within_reported_parent_remaining',s['qualification_attempts']<=b['qualification_attempts_total']-b['qualification_attempts_used'])
ck('deadline_not_reset',b['deadline_utc']=='2026-10-14T07:23:48Z' and b['no_reset'])
ck('owner_adoption_not_forged',p['status']=='proposed_for_owner_adoption_not_executed'and b['actual_approval_required'])
ck('no_model_task_in_dag',not any('train' in r['title'].lower()for r in p['tasks']))
ids={r['id'] for r in p['tasks']};done=set()
while len(done)<len(ids):
 ready=[r['id']for r in p['tasks'] if r['id']not in done and set(r['requires'])<=done]
 if not ready:raise AssertionError('task graph cycle or missing prerequisite')
 done.update(ready)
ck('dag_acyclic',True)
ck('stage1_replay_still_zero_science_credit',read('audit/INDEPENDENT_PACKAGE_VALIDATION.json')['new_Q_N_Q_E_credit']==0)
report={'result':'pass','checks':len(results),'tests':results,'scope':'plan consistency and supplied evidence metadata only; no CFD, no QN/QE, no raw HDF5, no training'}
(R/'PLAN_VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'result':'pass','checks':len(results),'scope':report['scope']},ensure_ascii=False))
