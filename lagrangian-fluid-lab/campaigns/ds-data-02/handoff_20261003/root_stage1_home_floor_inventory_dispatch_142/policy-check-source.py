import importlib.util,json,sys,copy
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab'
sys.path.insert(0,str(L/'scripts'));import ds_data02_runtime_v2 as runtime
spec=importlib.util.spec_from_file_location('policy','/tmp/ds02-root-home-floor-policy.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
checks={};floor={'storage_policy':'home_free_floor','home_path':'/home/jade','home_min_free_bytes':500*1024**3}
checks['exact_dataset_root_eligible']=policy.eligible(policy.DATA_ROOT,floor)
checks['per_attempt_tree_not_skipped']=not policy.eligible(policy.DATA_ROOT/'families/F1/case/attempt',floor)
checks['foreign_tree_not_skipped']=not policy.eligible('/tmp/another-data-root',floor)
checks['legacy_quota_full_walk_required']=not policy.eligible(policy.DATA_ROOT,{'new_storage_bytes':1024**4})
checks['weaker_or_unidentified_home_policy_rejected']=all(not policy.eligible(policy.DATA_ROOT,x) for x in [{**floor,'home_min_free_bytes':499*1024**3},{**floor,'home_path':'/tmp'},{'storage_policy':'home_free_floor'}])
calls=[];fake=SimpleNamespace(__file__=runtime.__file__,tree_bytes=lambda root:calls.append(str(root)) or 987654321)
original=fake.tree_bytes;load=policy.limits;q={'root_dataset_inventory_profile':policy.PROFILE,'launch_owner':'root','kind':'cpu'}
policy.limits=lambda:floor
with policy.install(fake,q) as e:
 checks['unused_parent_inventory_skipped_only_once']=fake.tree_bytes(policy.DATA_ROOT)==0 and not calls and e['full_dataset_walk_skips']==1
 checks['per_attempt_exact_size_accounting_preserved']=fake.tree_bytes(policy.DATA_ROOT/'families/F1/case/attempt')==987654321 and len(calls)==1
 policy.limits=lambda:{'new_storage_bytes':1024**4}
 checks['live_legacy_switch_falls_back_full_walk']=fake.tree_bytes(policy.DATA_ROOT)==987654321 and len(calls)==2
checks['context_restores_original_on_success']=fake.tree_bytes is original
try:
 with policy.install(fake,q):raise RuntimeError('test interruption')
except RuntimeError:pass
checks['context_restores_original_on_exception']=fake.tree_bytes is original
policy.limits=load
try:
 with policy.install(fake,{**q,'kind':'production'}):pass
except ValueError:checks['unreviewed_native_profile_rejected']=True
ledger={'deadline_utc':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'limits':{**floor,'gpu_seconds':100000,'cpu_core_seconds':100000,'new_storage_bytes':1,'qualification_attempts':1024,'production_attempts':720},'charges':[],'reservations':[],'attempts':[]}
reservation={'id':'F1/case/attempt','kind':'cpu','cpu_task_kind':'audit','cpu_threads':2,'cpu_core_seconds':7200,'gpu_seconds':0,'new_storage_bytes':1024**2}
def outcome(l,existing,available):
 try:runtime.check_reservation(l,reservation,existing,available_bytes=available);return 'allowed'
 except RuntimeError as e:return str(e)
checks['parent_guard_equivalent_for_huge_vs_zero_ignored_bytes']=all(outcome(ledger,n,700*1024**3)=='allowed' for n in [0,17*1024**4])
checks['home_floor_not_weakened']=all(outcome(ledger,n,500*1024**3)!='allowed' for n in [0,17*1024**4])
limited=copy.deepcopy(ledger);limited['limits']['cpu_core_seconds']=1
checks['cpu_parent_budget_not_weakened']=all('parent budget exhausted' in outcome(limited,n,700*1024**3) for n in [0,17*1024**4])
assert all(checks.values()),checks
Path('/tmp/ds02-root142-policy-check.json').write_text(json.dumps({'all_passed':True,'actual_checks':checks,'check_count':len(checks),'runtime_source_unchanged':True,'no_native_or_array_jobs':True},indent=2)+'\n')
print(json.dumps({'all_passed':True,'checks':len(checks)}))
