"""Validate this planning package, NOT a solver/dataset/production receipt."""
from pathlib import Path
import json
R=Path(__file__).resolve().parents[1]
p=json.loads((R/'CAMPAIGN_PLAN.json').read_text())
g=json.loads((R/'TASK_GRAPH.json').read_text())
f=json.loads((R/'FAMILY_CARDS.json').read_text())
checks={}
checks['seven_families'] = [x['id'] for x in f]==[f'F{i}' for i in range(1,8)]
checks['family_prompts_exist'] = all((R/x['card']).is_file() for x in p['family_plans'])
checks['model_budgets_zero'] = p['limits']['training_attempts']==p['limits']['inference_attempts']==0
checks['qualification_soft_caps_within_parent'] = sum(x['qualification_soft_cap'] for x in p['family_plans'])+p['qualification_shared_reserve']==p['limits']['qualification_attempts']
checks['production_soft_caps_within_parent'] = sum(x['production_soft_cap'] for x in p['family_plans'])==p['limits']['production_attempts']
checks['production_targets_consistent'] = sum(x['target_independent_cases'] for x in p['family_plans'])==336
checks['parent_approval_not_fabricated'] = p['adoption_status']=='proposed_pending_actual_owner_adoption'
checks['publication_is_not_automatic'] = not p['publication']['public_upload'] and not p['publication']['hidden_test_generation']
ids={t['id'] for t in g['tasks']}
checks['task_ids_unique'] = len(ids)==len(g['tasks'])
checks['dependency_ids_exist'] = all(set(t.get('requires',[]))<=ids for t in g['tasks'])
remaining={t['id']:set(t.get('requires',[])) for t in g['tasks']};done=set()
while remaining:
 ready={k for k,v in remaining.items() if v<=done}
 if not ready: break
 done |= ready
 for k in ready: del remaining[k]
checks['acyclic_graph'] = not remaining
checks['all_family_sources_initially_ready'] = all(next(t for t in g['tasks'] if t['id']==f'F{i}_SOURCE')['requires']==[] for i in range(1,8))
checks['no_cross_family_qualification_dependencies'] = all(all(not d.startswith('F') or d.startswith(t['scope']+'_') for d in t.get('requires',[])) for t in g['tasks'] if 'scope' in t and t['scope'] != 'shared')
checks['actual_atlas_count'] = sum(x['atlas'] for x in f)==26
checks['actual_reference_entry_count'] = sum(x['refs'] for x in f)==33
report={'scope':'planning_structure_and_counts_only_not_CFD_or_dataset_acceptance','checks':checks,'passed':all(checks.values()),'check_count':len(checks)}
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
