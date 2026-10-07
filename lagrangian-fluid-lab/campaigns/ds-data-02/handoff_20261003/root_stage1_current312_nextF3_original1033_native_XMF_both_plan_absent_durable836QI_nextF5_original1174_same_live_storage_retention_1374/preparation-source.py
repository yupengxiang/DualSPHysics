from pathlib import Path
import json, hashlib, copy, datetime, collections, os, subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics'); L=R/'lagrangian-fluid-lab'; H=L/'campaigns/ds-data-02/handoff_20261003'; D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_280.json';cp=load(cpfile);assert cp['checkpoint']==280 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==312
F=root(1033);oldp=F/'actual1002-full836-XMF-and-producer-typed-independent-review.json';old=load(oldp)
for e in old.values():
 if isinstance(e,dict) and 'path' in e and 'sha256' in e:assert sha(e['path'])==e['sha256']
n=load(old['actual_native_receipt']['path']);t=load(old['actual_typed_report']['path']);x=load(old['actual_XMF_manifest']['path']);q=load(F/'enabled-full836-render-request.json');w=load(F/'enabled-render-wrapper.json');canonical=n['request']['physical_condition_sha256']
assert canonical==t['hash_scopes']['physical_condition_sha256']==x['physical_condition_sha256']=='bb7ed44d73920c9152d81f581e4bc9d628c5302f77a0560114c7a6a319e6a5a6'
assert t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
mask={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',n['request']),('XMF',x)]}
assert all(not z['present'] and z['value'] is None for obj in mask.values() for z in obj.values())
assert n['status']=='completed' and n['returncode']==0 and q['physical_case_id']==w['physical_case_id']==n['request']['physical_case_id']==x['physical_case_id']
assert w['expected_frames']==t['frames']==x['frames']==836 and w['expected_particles']==t['particles']==x['particles']==179208 and w['expected_contact_sheets']==35
assert w['cpu_threads']==w['declared_cpu_cores']==24 and w['environment_threads']==2 and w['global_renderer_cap']==2 and w['home_free_floor_bytes']==500*2**30
front=[]
for original,pid,start,ownqi in [(1033,635508,'214008910',1373),(1174,633506,'213987092',1371)]:
 P=Path(f'/proc/{pid}');live=None;terminal=root(original)/'controller-result.json'
 if P.exists():
  stat=P.joinpath('stat').read_text().split(') ',1)[1].split();assert stat[19]==start;cmd=P.joinpath('cmdline').read_bytes().split(b'\0');assert cmd[0].endswith(b'/pvpython');out=Path(cmd[cmd.index(b'--output-dir')+1].decode());assert f'root{original}' in str(out)
  live={'pid':pid,'startticks':start,'state':stat[0],'private_frame_filename_stat_count':len(list((out/'frames').glob('frame_*.png'))),'private_PNG_payload_IO':False}
 assert live is not None or terminal.exists()
 front.append({'original':original,'live_process':live,'actual_terminal':ref(terminal) if terminal.exists() else None,'future_own_QI_root':ownqi,'no_restart':True,'case_credit':0})
for key,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][key]
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc)
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
cleanup=root(1376)/'current-storage-cleanup-verification.json';cl=load(cleanup);assert cl['floor_pass'] and cl['new_deletions_this_verification']==0 and cl['cumulative_released_allocated_GiB']>534
O=H/'root_stage1_current312_nextF3_original1033_native_XMF_both_plan_absent_durable836QI_nextF5_original1174_same_live_storage_retention_1374';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_281.json';assert not O.exists() and not np.exists();O.mkdir()
entry=O/'after_original1033_terminal_full836_own_QI.py';entry.write_bytes(Path('/tmp/ds02-F3-original1033-full836-own-QI1373.py').read_bytes());compile(entry.read_text(),str(entry),'exec')
pp=O/'current312-next-original1033-1174-same-live-durable836QI-and-cleanup-retention-proof.json'
put(pp,{'schema':'ds02.current312-next-originalF3-durable836QI.v1','at_utc':now.isoformat(),'actual_same_original_processes':front,'original_F3_1033_outer_expected_historical_envelope':{k:q[k] for k in ['expected_frames','expected_particles']},'actual_loaded_wrapper_expected':{k:w[k] for k in ['expected_frames','expected_particles','expected_contact_sheets']},'outer_fields_not_actual_selection_authority':True,'actual_F3_previsual_metadata':ref(oldp),'canonical_native_typed_XMF_digest':canonical,'actual_native_XMF_plan_namespaces':mask,'actual_completed_typed_receipt':old['actual_typed_receipt'],'decoder_CLI_repair_actual_completed_receipt_selected_original_failed_history_preserved':True,'durable_original1033_only_QI_entrypoint':ref(entry),'entry_command':['python3','-B',str(entry),'1033','1373'],'future_own_QI_proof_sha256':None,'do_not_rerun_completed_QI':True,'current_user_cleanup_retention':ref(cleanup),'cleanup_released_bytes_are_cumulative_prior_actual_deletions_not_new_this_turn':True,'source193_F2_personal_review_active':'original1143/QI1366 completed; child personal review pending','source213_F3_personal_review_next':'f5_bed_recovery bounded wait for original1033 completed0/publication plus ownQI1373','case_credit':0,'scientific_payload_IO':False,'no_new_jobs_or_render_restarts':True})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp)
new.update(checkpoint=281,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,authorized_work_state='Active312/336. F2 original1143 ownQI1366 complete; source193 personal review active. F5 original1174 and F3 original1033 same live ParaView handles; durable ownQI1371/1373 prepared, run each once only after actual0 and atomic publish. Cleanup cumulative534.4086GiB/current784GiB; no additional deletions.',previous_goal_turn_classification='PROGRESS: preceding user cleanup turn produced authoritative fresh exact retention proof1376 without new deletion. Current turn pins true F3 original1033 native/XMF BOTH plan fields absent and actual836/179208 wrapper, prepares durable independent ownQI1373, and advances delegated review handoff.')
new['actual_progress']['next_original1033_durable836_QI']=ref(pp);new['actual_progress']['user_cleanup1376_exact_retention']=ref(cleanup)
new['source_agents']['f5_bed_recovery']='fresh213 actualF3 original1033 P0800AY0570 bounded wait for actual0/pub plus ownQI1373 before personal35contacts9keys; exact native/XMF both plan fields absent'
new['next_executable_tasks']=['Adopt source193 originalF2 1143 after personal17contacts9keys/final commit; preserve15 fluid omissions and genuine initial QA actual0/reportpass; ownQI1366 is not runner receipt.','Observe same F5original1174 PID633506/start213987092; after completed0/pub execute durableownQI1371 once then supply source179 personal34contacts9keys.','Observe same F3original1033 PID635508/start214008910; after completed0/pub execute durableownQI1373 once then supply source213 personal35contacts9keys.','Continue remaining24 independent cases to336; finalF2/F3/F5 complete48 catalogs only after real48 accepted and primary/runtime-unknown audit.']
put(np,new)
ip=root(1372)/'full336-current312-actual-final48-delivery-progress-index.json';index=load(ip);assert index['accepted_independent_physical_cases']==312
index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,current_next1033_durable836QI_and1174_same_live=ref(pp),current_user_storage_cleanup_status=ref(cleanup))
row=next(r for r in index['cases'] if r['physical_case_id']==q['physical_case_id']);assert not row.get('accepted_decision');row.update(current_same_original_live_previsual_preparation=ref(pp),future_independent_QI_root=1373,current_personal_review_source=213,case_credit=0)
assert len(index['cases'])==336 and sum(bool(r.get('accepted_decision')) for r in index['cases'])==312;put(O/'full336-current312-actual-final48-delivery-progress-index.json',index)
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: prepare original1033 own836QI and delegated review retaining actual plan absence','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':281,'accepted':312,'proof':ref(pp),'entry':ref(entry),'live':front,'free_GiB':free,'GPUh':gpu,'CPUh':cpu,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
