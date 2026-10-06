from pathlib import Path
import json,hashlib,datetime,shutil,subprocess,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.jsonl','.py','.md','.xml','.xmf','.log'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
O=H/'root_stage1_237_visual_failed439GiB_cleanup_current_storage_and_downstream_checkpoint_1042'
assert not O.exists() and not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_156.json').exists()
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_155.json')
accepted=[load(p) for p in cp['accepted_decisions']]
assert len(accepted)==sum(cp['accepted_per_family'].values())==237
assert len({v.get('physical_case_id',v['case_id']) for v in accepted})==237
assert all(not v.get('q_n_granted',False) and not v.get('q_e_granted',False) for v in accepted)
cleanup=load(root(966)/'actual-cleanup-independent-review.json')
checks={k:sha(cleanup[k]['path'])==cleanup[k]['sha256'] for k in ['actual_registered_cleanup_receipt','actual_cleanup_result','deletion_journal','manifest']}
assert all(checks.values())
journal=[json.loads(s) for s in Path(cleanup['deletion_journal']['path']).read_text().splitlines()]
assert len(journal)==15995 and all(not Path(v['path']).exists() for v in journal)
preserved=[]
for item in cleanup['original_failure_receipts_headers_and_initial_last_dependency_frames_preserved']:
 side=load(item['cleanup_tombstone']['path']);receipt=side['original_receipt']
 assert sha(receipt)==side['original_receipt_sha256']
 assert all(Path(p).is_file() for p in side['preserved_frames'])
 preserved.append({'attempt_id':item['attempt_id'],'original_failed_receipt_unchanged':True,'preserved_frames_still_present':True})
failed=[];seen=0
for p in (D/'families').glob('*/*/*/execution-receipt.json'):
 r=load(p);seen+=1
 if r.get('status')!='failed' or r.get('returncode') in (None,0):continue
 ar=p.parent;dd=ar/'solver_output/data';fs=[]
 if dd.is_dir():
  fs=[v for v in dd.iterdir() if re.fullmatch(r'Part_\d{4,}\.bi4',v.name) and v.is_file() and not v.is_symlink()]
 already=(ar/'user-authorized-failed-native-cleanup-root965.json').exists()
 failed.append({'attempt_root':str(ar),'receipt':ref(p),'returncode':r['returncode'],'remaining_numeric_native_frames':len(fs),'remaining_numeric_native_allocated_bytes':sum(v.stat().st_blocks*512 for v in fs),'already_cleaned_root965':already})
unpruned=[v for v in failed if v['remaining_numeric_native_frames']>2 and not v['already_cleaned_root965']]
protected={v['id']:v for v in cleanup['blocked_two_referenced_failed_attempts_retained']}
for v in unpruned:
 key=str(Path(v['attempt_root']).relative_to(D/'families'))
 v['prior_explicit_dependency_protection']=protected.get(key)
 v['not_deleted_by_recheck']=True
O.mkdir()
put(O/'actual-cleanup439GiB-and-current-failed-native-recheck.json',{'at_utc':now(),'actual_original_cleanup_review':ref(root(966)/'actual-cleanup-independent-review.json'),'original_cleanup_receipts_and_manifest_unchanged':checks,'failed_attempts_already_cleaned':14,'previously_deleted_files':15995,'deleted_files_still_absent':15995,'previously_freed_allocated_GiB':cleanup['deleted_allocated_bytes']/2**30,'preserved_first_last_frames_and_failure_receipts':preserved,'direct_family_receipts_observed':seen,'actual_failed_nonzero_receipts_observed':len(failed),'remaining_unpruned_failed_native_candidates':unpruned,'additional_deleted_files_by_this_recheck':0,'main_scientific_payload_contents_IO':False,'negative_numerical_precision_alone_not_deletion_reason':True,'valid_accepted_pending_live_reusable_outputs_preserved':True,'failed_conversion_and_render_storage_audit_delegated_fresh147':True})
observations=[]
roots=[951,978,983,984,987,988,991,998,1002,1003,1006,1008,1009,1010,1013,1014,1015,1016,1017,1020,1025,1026,1028,1031,1032,1033,1034,1035,1036,1037,1038]
for n in roots:
 o=root(n);entry={'root':n,'live':False,'visual_case_credit_from_observation':0}
 for p in o.glob('*launch*.json'):
  a=load(p)
  if not isinstance(a,dict) or not a.get('pid'):continue
  st=Path(f"/proc/{a['pid']}/stat")
  try:f=st.read_text().split(') ',1)[1].split()
  except FileNotFoundError:continue
  if f[0]!='Z' and f[19]==str(a.get('proc_start_ticks',a.get('start_ticks'))):entry.update(live=True,pid=a['pid'],start_ticks=f[19],actual_launch_receipt=ref(p))
 for name in ['actual-progress.json','controller-result.json']:
  p=o/name
  if p.exists():
   frozen=O/f'root{n}-{name}-frozen.json';frozen.write_bytes(p.read_bytes());entry[name]=ref(frozen)
 cfgp=o/'controller-config.json'
 if cfgp.exists():
  cfg=load(cfgp);receipts=[];pending=[]
  for qp in cfg.get('requests',[cfg['request']] if cfg.get('request') else []):
   q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';v={'case_id':q['case_id'],'physical_case_id':q.get('physical_case_id'),'request':ref(qp),'actual_receipt_path':str(rp),'visual_case_credit':0}
   if rp.exists():
    rr=load(rp);v.update(actual_receipt=ref(rp),status=rr['status'],returncode=rr.get('returncode'));receipts.append(v)
   else:pending.append(v)
  entry['actual_scientific_receipts']=receipts;entry['pending_no_terminal_receipt']=pending
 observations.append(entry)
put(O/'actual-live-handles-and-terminal-metadata-observations.json',{'at_utc':now(),'processes':observations,'same_live_handles_not_restarted':True,'scientific_payload_IO':False,'case_credit':0})
new={'accepted237':{'delegated145_three_F6':ref(root(1040)/'adoption-and-three-case-independent-review.json'),'delegated132_three_F3':ref(root(1041)/'source132-adoption-three-full836-independent-QI-and-visual-review.json')},'historical_accepted231_dynamic_catalog_snapshot':ref(root(1039)/'STAGE1_VISUAL_CASE_CATALOG_231.json'),'catalog_is_historical231_not_current237':True,'catalog_actual_coverage_review':ref(root(1039)/'actual-catalog231-coverage-review.json'),'F3_new_full836_render_registered_requests':[ref(root(n)/'enabled-full836-render-request.json') for n in [1031,1032,1033,1034]],'F5_new_actual988_full801_XMF3':ref(root(1035)/'controller-config.json'),'F2_new_actual1013_full401_XMF3':[ref(root(n)/'controller-config.json') for n in [1036,1037,1038]],'conversion_global_serial_cap':1,'render_shared_cap':2,'Home_floor_GiB':500,'Q_N_Q_E_granted':False}
put(O/'new-actual-progress-and-historical-catalog-reference.json',new)
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);(O/'resource-ledger-frozen.json').write_bytes(raw)
free=shutil.disk_usage('/home/jade').free;assert free>=500*2**30
assert ledger['limits']['qualification_attempts']==1024 and ledger['limits']['production_attempts']==720
cp.update(checkpoint=156,at_utc=now(),predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_155.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_155.json'),new_accepted_decisions=[],home_free_gib=free/2**30,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(v.get('gpu_seconds',0) for v in ledger['charges'])/3600,cpu_core_hours_charged=sum(v.get('cpu_core_seconds',0) for v in ledger['charges'])/3600,previous_goal_turn_classification='Progress:237 independent visual cases preserved; actual14 failed native attempts already pruned,15995 deleted intermediates remain absent and439.037GiB allocation recovered, original failed receipts and evidence intact. Current direct failed receipt/native file stat recheck preserves referenced small failures; fresh147 audits other failed downstream storage. New1031-1038 registered downstream handles observed without restarting; historical231 dynamic catalog explicitly frozen as snapshot. No new visual credit or numerical grant from metadata alone.')
cp['actual_progress']['storage_cleanup_reverification']=ref(O/'actual-cleanup439GiB-and-current-failed-native-recheck.json')
cp['actual_progress']['actual_process_handles_and_frozen_producer_results']=ref(O/'actual-live-handles-and-terminal-metadata-observations.json')
cp['actual_progress']['237_visual_current_downstream_and_historical231_catalog']=ref(O/'new-actual-progress-and-historical-catalog-reference.json')
cp['source_agents']={'f5_bed_recovery':'fresh173 remaining6 genuine native1017 typed disabled requests completed baab880f6a5810dd1227f353f963da937f533ae9 awaiting independent adoption; fresh174 two actual1008 XMF0 original138 bed metadata preparation active','f6_endpoint_initial_qa':'fresh146 three full241 personal visual148aa7c38 awaiting independent closure; fresh147 failed downstream storage metadata-only audit active','production_recovery':'fresh133 next actual complete full836 personal visuals active'}
cp['next_executable_tasks']=['Integrate fresh146 three F6 full241 delegated visuals only after own actual native/typed/H5audit/omega/XMF/render scope and lifecycle closure; no numerical grant.','Adopt fresh173 remaining6 native1017 F5 typed157 disabled requests after full actual converter prospective scope/801/QA/GenCase/tool validation; future producer hashes stay null.','Integrate fresh133 true full836 completed F3 delegated visuals; preserve original legacy/native-canonical roles and actual initial clone/forcing attestation.','Audit fresh147 actual failed conversion/render intermediates and unused dependency graph; remove only explicitly proven failed unused intermediates with deletion journals and evidence retained.','Adopt fresh174 M090T085/M090T095 actual1008 full801 XMF0 original138 bed requests; preserve original kernel and own geometry/QA/source-plan file identity.','Advance genuine typed0 F5 root1028 and F2 root1013/1020 to immutable own-scope XMF requests once each, through unchanged fairCPU2 globalserial1.','Observe same live render/bed handles; actualworker0 diagnostics plus delegated complete contact/key visual review required before case credit.','Keep336-case goal active, cumulative512GPUh/3840CPUcoreh/1024qualification/720production and original deadline unchanged; Home must retain500GiB; accepted/pending/live/reusable data protected.']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_156.json',cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_156.json').relative_to(R))]
for n in range(1031,1039):paths.extend(str(p.relative_to(R)) for p in root(n).glob('*launch*.json'))
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: preserve failed439GiB cleanup and checkpoint237 actual downstream handles','--',*paths],cwd=R,check=True)
print(json.dumps({'accepted':237,'Home_free_GiB':free/2**30,'already_freed_allocated_GiB':cleanup['deleted_allocated_bytes']/2**30,'deleted15995_still_absent':True,'failed_receipts':len(failed),'additional_native_candidates_GiB':sum(v['remaining_numeric_native_allocated_bytes'] for v in unpruned)/2**30,'additional_deletions':0,'GPU_h':cp['gpu_hours_charged'],'CPU_core_h':cp['cpu_core_hours_charged'],'attempts':cp['attempt_counts'],'live_roots':[v['root'] for v in observations if v['live']],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
