from pathlib import Path
import json,hashlib,subprocess,datetime,os,collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');root=lambda n:next(H.glob(f'root*_{n}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.png','.xml','.xmf','.log','.txt'} or str(p) in {str(L/'.venv/bin/python'),'/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython','/usr/bin/env'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
commit='7f8022dffcc1c4d56e95d637ed04f309406c35c2';prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_172_dzxy_s1375_render_queue_audit_v1';P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==3
before={n:sha(W/n) for n in names};validator=P/'scripts/validate_fresh172.py';v=subprocess.run(['python3','-B',str(validator)],capture_output=True,text=True);assert v.returncode==0 and before=={n:sha(W/n) for n in names}
audit=load(P/'metadata/queue-audit.json');co=audit['controller'];target=audit['target']
for f,k in [('controller_path','controller_sha256'),('controller_config_path','controller_config_sha256'),('fair_dispatch_path','fair_dispatch_sha256'),('root142_launch_path','root142_launch_sha256')]:assert sha(co[f])==co[k]
request=load(target['request_path']);assert sha(target['request_path'])==target['request_sha256']
assert load(co['controller_config_path'])['outer_requests'][target['outer_request_index']]==target['request_path']
for p in request['input_files']:
 p=Path(p)
 if p.suffix.lower() not in {'.h5','.hdf5','.bi4','.csv','.dat','.vtk'}:assert sha(p)==request['input_sha256'][str(p)]
 else:assert p.is_file()
# Independently recheck each previously removed exact filename using stat only.
old_cleanup=root(1235)/'cleanup-actual-results-and-retention-proof.json';cleanup=load(old_cleanup);deleted=[];retained=[];original_failed_receipts=[]
for row in cleanup['actual_cleanup_receipts']:
 assert sha(row['actual_receipt'])==row['receipt_sha256'] and sha(row['result'])==row['result_sha256']
 result=load(row['result']);plan=load(result['plan']);assert sha(result['plan'])==result['plan_sha256']
 if row['root']==965:
  for a in plan['eligible_attempts']:
   deleted.extend(x['path'] for x in a['delete_files']);retained.extend(a['preserved_frame_paths']);original_failed_receipts.append({'path':a['receipt'],'sha256':a['receipt_sha256']})
 elif row['root']==1054:
  deleted.extend(x['path'] for x in plan['eligible_files']);original_failed_receipts.extend(x['receipt'] for x in plan['eligible_files'])
 else:
  for a in plan['attempts']:
   deleted.extend(x['path'] for x in a['eligible_files']);retained.extend(x['path'] for x in a['preserved_files'])
  for a in result['attempt_results']:original_failed_receipts.append({'path':a['original_failed_receipt'],'sha256':a['original_failed_receipt_sha256']})
assert len(deleted)==len(set(deleted))==cleanup['cumulative_deleted_files']==17203
assert all(not Path(p).exists() for p in deleted) and all(Path(p).is_file() for p in retained)
for r in original_failed_receipts:assert sha(r['path'])==r['sha256']
cpp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_211.json';cp=load(cpp);assert cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==277
old_growing=root(1246)/'F5-actual-first24-growing-prefix15-frozen8-acceptance-order.json';g=load(old_growing)
oldref=g['current_authoritative_checkpoint'];actual=sha(oldref['path']);assert oldref['path']==str(cpp) and oldref['sha256']!=actual
assert len(g['physical_case_ids_actual_delivery_order'])==15 and g['physical_case_ids_actual_delivery_order'][:8]==g['first8_physical_case_ids']
for e in g['actual_visual_decisions']:assert sha(e['path'])==e['sha256']
O=H/'root_stage1_source172_lastF6_queue_mechanism_cleanup17203_actual_absence_F5_prefix15_reference_closure_checkpoint_1247';assert not O.exists() and not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_212.json').exists();O.mkdir();adopted=[]
for n in names:
 b=subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W);assert (W/n).read_bytes()==b;p=R/n;assert not p.exists() or p.read_bytes()==b;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);adopted.append(ref(p))
now=datetime.datetime.now(datetime.timezone.utc).isoformat();put(O/'source172-readonly-validator.json',{'validator':ref(validator),'returncode':v.returncode,'stdout':v.stdout,'stderr':v.stderr,'source_bytes_unchanged':True})
put(O/'source172-original-immutable-adoption-proof.json',{'source_commit':commit,'adopted_files':adopted,'source_frozen_observation':ref(R/prefix/'metadata/queue-audit.json'),'original_951_request_and_guard_source_hashes_match':True,'all44_nonscience_input_hashes_match_request':True,'science_input_stat_only':True,'source_queue_state_is_historical_at_observation_not_current':True,'current1100_completed0_controller_result':ref(root(1100)/'controller-result.json'),'no_controller_restart_or_request_source_mutation':True,'case_credit':0,'scientific_payload_IO':False})
# Correct a pre-finalization metadata digest through a separately named view; never edit the original.
g['current_authoritative_checkpoint']=ref(cpp);g.update(schema='ds02.main.F5.actual-first24-growing-delivery-prefix.v2',at_utc=now,previous_prefix15_preserved=ref(old_growing),checkpoint_role='stable checkpoint211 accepted277/F5=15; no circular dependency on successor212')
gout=O/'F5-actual-first24-growing-prefix15-frozen8-stable-checkpoint211.json';put(gout,g)
put(O/'original-prefix15-pre-finalization-checkpoint-digest-correction.json',{'original_growing_prefix15':ref(old_growing),'original_declared_checkpoint_reference':oldref,'actual_final_checkpoint211':ref(cpp),'original_declared_digest_matched_final_bytes':False,'cause':'prefix file captured checkpoint211 digest before main added its prefix reference; new immutable view binds finalized checkpoint211 without a cycle','new_corrected_immutable_prefix_view':ref(gout),'membership_and_visual_decision_bytes_unchanged':True,'original_bytes_preserved':True,'new_case_credit':0})
free=os.statvfs('/home/jade').f_bavail*os.statvfs('/home/jade').f_frsize/2**30;assert free>=500
storage=O/'cleanup17203-exact-path-absence-retention-and-current-home-proof.json';put(storage,{'at_utc':now,'original_cleanup_proof':ref(old_cleanup),'exact_deleted_paths_stat_checked':len(deleted),'all_deleted_paths_still_absent':True,'all_retained_first_last_filenames_present':True,'retained_samples_count':len(retained),'all_original_failed_receipt_hashes_unchanged':True,'original_failed_receipts_count':len(original_failed_receipts),'cumulative_released_allocated_GiB':cleanup['cumulative_deleted_allocated_GiB'],'current_Home_free_GiB':free,'Home_floor_GiB':500,'no_extra_deletion_this_verification':True,'scientific_payload_IO':False})
# Actual current state is metadata-only and explicitly separate from frozen source172.
pid=co['pid'];ps=Path(f'/proc/{pid}/stat');live={}
if ps.exists():t=ps.read_text().rsplit(')',1)[1].split();live={'state':t[0],'startticks':t[19],'same_PID_startticks_live':t[19]==str(co['proc_start_ticks'])}
arp=Path(target['attempt_root']);er=arp/'execution-receipt.json'
obs={'at_utc':now,'951_controller':live,'target_attempt_root_exists':arp.exists(),'target_receipt':({'path':str(er),'status':load(er).get('status'),'returncode':load(er).get('returncode'),'hash_observation_only':sha(er)} if er.exists() else None),'1100_actual_controller_completed0':load(root(1100)/'controller-result.json')['returncode']==0,'source172_wait_snapshot_never_promoted_to_current_live_state':True}
put(O/'original951-current-live-state-metadata-only.json',obs)
lb=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(lb);lf=O/'resource-ledger-frozen.json';lf.write_bytes(lb);counts=collections.Counter(r['kind'] for r in ld['attempts']);gpu=sum(r.get('gpu_seconds',0) for r in ld['charges'])/3600;cpu=sum(r.get('cpu_core_seconds',0) for r in ld['charges'])/3600
assert gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720
cp.update(checkpoint=212,at_utc=now,predecessor=str(cpp),predecessor_sha256=sha(cpp),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(lb).hexdigest(),ledger_immutable_snapshot=ref(lf),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: actual1109 accepted277/F5=15, source172 realqueue mechanism adopted; all17203 deleted filenames independently stat checked absent, immutable failed receipts and firstlast diagnostics retained.',authorized_work_state='Active277/336, numeric precision not accepted. Original1100 completed0 personal fresh156 review; original1183 fresh197 tracking; lastF6original951 same originalhandle, sharedcapacity wait not qualification failure. Home floor500GiB protected. Prefix15 metadata reference corrected through a new view, originals unchanged.')
cp['actual_progress']['source172_original951_actual_queue_mechanism']=ref(O/'source172-original-immutable-adoption-proof.json');cp['actual_progress']['F5_actual_first24_prefix15_corrected_stable_checkpoint211']=ref(gout);cp['actual_progress']['user_cleanup_all17203_actual_absence_retention_reverified']=ref(storage);cp['source_agents']['f6_endpoint_initial_qa']='fresh172 adopted; fresh173 original951 realterminal tracking or firstnextF2 actualcompleted metadata identification';cp['next_executable_tasks']=[x for x in cp['next_executable_tasks'] if 'Adopt source172' not in x]
newcp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_212.json';put(newcp,cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(e['path']).relative_to(R)) for e in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str(newcp.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: adopt last F6 capacity audit and reverify failed cleanup with immutable prefix correction','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':212,'accepted':277,'all_deleted_paths_absent':len(deleted),'Home_free_GiB':free,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
