#!/usr/bin/env python3
"""Validate planning metadata only. Does not run CFD, training, or scientific tests."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent

def main():
    p = json.loads((ROOT/'CAMPAIGN_PLAN.json').read_text(encoding='utf-8'))
    cards = json.loads((ROOT/'SCENARIO_CARDS.json').read_text(encoding='utf-8'))
    results=[]
    def check(name, predicate):
        ok=bool(predicate)
        results.append({'name':name,'passed':ok})
        if not ok: raise ValueError(name)
    check('baseline_exact', p['baseline_commit']=='4b554e69d69245db4a6a6772b296cf256c142a16')
    check('adoption_pending', p['owner_adoption_status']=='pending')
    check('no_old_budget_reset', not p['old_campaign_reopened'])
    for resource, cap in [('qualification_solver','qualification_solver_attempts'),('gpu_hours','gpu_hours'),('cpu_core_hours','cpu_core_hours')]:
        check('soft_total_'+resource, sum(p['soft_allocations'][resource].values())==p['limits'][cap])
    ids={x['id'] for x in p['stages']}
    check('stage_ids_unique',len(ids)==len(p['stages']))
    check('dependencies_known',all(set(x['requires'])<=ids for x in p['stages']))
    done=set()
    while len(done)<len(ids):
        ready=[x['id'] for x in p['stages'] if x['id'] not in done and set(x['requires'])<=done]
        if not ready: raise ValueError('cyclic dependencies')
        done.update(ready)
    check('acyclic_task_graph',done==ids)
    check('data_not_blocked_on_model',not p['training_success_is_data_gate'])
    check('T1_not_blocked_on_T2',not p['t2_success_is_t1_development_gate'])
    check('no_public_or_hidden_release',not p['public_release_authorized'] and not p['hidden_test_generation_authorized'])
    check('six_proposed_families', {x['family'] for x in cards['families']}=={'F1','F2','F3','F4','F5','F6'})
    check('no_raw_data_execution_claim',p['this_is_executable_runner'] is False and cards['status']=='design_not_executed')
    check('all_documents_exist',all((ROOT/x).is_file() for x in ['START_HERE_ZH.md','PLAN_ZH.md','REVIEW_ZH.md','BENCHMARK_SPEC_ZH.md','EVIDENCE_INDEX.json']))
    output={'scope':'planning metadata only; not CFD, code regression, raw artifact verification, or scientific acceptance','passed':len(results),'failed':0,'checks':results}
    (ROOT/'PLAN_VALIDATION.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'scope':output['scope'],'passed':len(results)},ensure_ascii=False))

if __name__=='__main__': main()
