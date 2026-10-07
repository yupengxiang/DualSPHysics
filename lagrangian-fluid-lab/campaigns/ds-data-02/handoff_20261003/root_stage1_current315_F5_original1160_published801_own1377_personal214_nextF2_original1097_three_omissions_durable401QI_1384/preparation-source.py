from pathlib import Path
import json, hashlib, datetime, copy, os, collections, subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p); assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p): return {'path':str(p),'sha256':sha(p)}
def put(p,j): Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
def checked(e): assert sha(e['path'])==e['sha256']
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_287.json';cp=load(cpfile)
assert cp['checkpoint']==287 and cp['stage1_visual_accepted_complete_independent_cases']==315
ip=root(1383)/'full336-current315-actual-final48-delivery-progress-index.json';idx=load(ip)
assert idx['source_authoritative_checkpoint']==ref(cpfile)
assert len(idx['cases'])==336 and sum(bool(r.get('accepted_decision')) for r in idx['cases'])==315
F=root(1097);pre=F/'actual1077-full401-XMF-and-actual-typed-producer-typed-independent-review.json';b=load(pre)
for e in b.values():
 if isinstance(e,dict) and 'path' in e and 'sha256' in e:checked(e)
t=load(b['actual_typed_report']['path']);x=load(b['actual_XMF_manifest']['path']);n=load(b['actual_native_receipt']['path']);nq=n['request'];w=load(F/'enabled-render-wrapper.json')
canonical=nq['physical_condition_sha256'];legacy=t['hash_scopes']['physical_condition_sha256']
assert canonical=='868a719b79737c9ed2460651a54a29ee1a20904121cc505f6cb044950002d630'
assert legacy==x['physical_condition_sha256']=='f5bab12237a82b9d91b86eb375cea952ca904154bcddfa58347f9fc59a2e7565' and canonical!=legacy
assert t['source_provenance']['solver_receipt']==b['actual_native_receipt']
assert n['status']=='completed' and n['returncode']==0 and nq['case_id']==w['case_id']
assert nq['physical_case_id']==x['physical_case_id']==w['physical_case_id']=='F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090'
mask={ns:{k:{'present':k in o,'value':o.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,o in [('native',nq),('XMF',x)]}
assert mask['native']['source_plan_condition_sha256']=={'present':False,'value':None}
assert mask['native']['source_plan_physical_condition_sha256']=={'present':True,'value':canonical}
assert all(v=={'present':False,'value':None} for v in mask['XMF'].values())
qa={}
for k in ['initial_qa_receipt','initial_qa_report']:
 e=ref(nq[k]);assert n['input_hashes_at_launch'][e['path']]==n['input_hashes_after_run'][e['path']]==e['sha256'];qa[k]=e
qr=load(qa['initial_qa_receipt']['path']);qq=load(qa['initial_qa_report']['path'])
assert qr['status']=='completed' and qr['returncode']==0 and qr['request']['case_id']==w['case_id'] and qq['status']=='pass' and qq['case_id']==w['case_id']
fs=t['lifecycle']['frame_summary'];assert len(fs)==t['frames']==x['frames']==w['expected_frames']==401
assert t['particles']==x['particles']==w['expected_particles']==418104 and w['expected_contact_sheets']==17
om={'final_missing_particles':fs[-1]['missing_particles'],'max_missing_per_frame':max(z['missing_particles'] for z in fs),'first_missing_frame':next(z['frame'] for z in fs if z['missing_particles']),'cumulative_particle_frame_omissions':sum(z['missing_particles'] for z in fs),'producer_attested_final_Idp_sample':fs[-1]['missing_id_first'],'final_Idp_sample_is_partial_not_all3':False,'final_missing_Idp_digest_producer_attested':fs[-1]['missing_ids_sha256'],'missing_location_state_cause_unknown':True,'initial_UID_axis_not_dropped_or_synthetically_filled':True}
assert (om['final_missing_particles'],om['max_missing_per_frame'],om['first_missing_frame'],om['cumulative_particle_frame_omissions'])==(3,3,154,635)
assert om['producer_attested_final_Idp_sample']==[397194,403829,404024]
assert om['final_missing_Idp_digest_producer_attested']=='e69b7facc642abe4eeb86b3846acbfef868dcc7bb39456ba16c4db5fa2b07e05'
assert all(z['missing_type_counts']=={'0':0,'1':0,'2':0,'3':z['missing_particles']} and z['type_counts']=={'0':372840,'1':24150,'2':0,'3':21114-z['missing_particles']} for z in fs)
assert x['actual_time_s']==[z['time'] for z in fs] and x['actual_time_s'][-1]==4.000007783879406
live=[]
for original,pid,start in [(1097,664604,'214297664')]:
 P=Path(f'/proc/{pid}');st=(P/'stat').read_text().rsplit(')',1)[1].split();assert st[19]==start
 cmd=(P/'cmdline').read_bytes().split(b'\0');assert cmd[0].endswith(b'/pvpython')
 out=Path(cmd[cmd.index(b'--output-dir')+1].decode());assert f'root{original}' in str(out)
 live.append({'original':original,'pid':pid,'startticks':start,'state':st[0],'private_frame_filename_stat_count':len(list((out/'frames').glob('frame_*.png'))),'private_PNG_payload_IO':False,'actual_controller_terminal':ref(root(original)/'controller-result.json') if (root(original)/'controller-result.json').exists() else None,'no_restart':True,'case_credit':0})
own=next(root(1377).glob('*proof.json'));oq=load(own)
assert oq['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T085_NEXT34' and oq['all801_geometry_velocity_N3_times_UID_finite_verified']
for e in oq['actual_completed_metadata_evidence'].values():checked(e)
own1151=next(root(1380).glob('*proof.json'));oq1151=load(own1151)
assert oq1151['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M108_T085_NEXT34' and oq1151['all801_geometry_velocity_N3_times_UID_finite_verified']
for e in oq1151['actual_completed_metadata_evidence'].values():checked(e)
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(z['kind'] for z in ld['attempts'])
gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600
v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc)
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
for key,p in [('runtime_v2_sha256',R/'lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',R/'lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][key]
O=H/'root_stage1_current315_F5_original1160_published801_own1377_personal214_nextF2_original1097_three_omissions_durable401QI_1384'
np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_288.json';assert not O.exists() and not np.exists() and not list(H.glob('root*_1385'))
entry_source=Path('/tmp/ds02-F2-original1097-full401-own-QI1385.py');compile(entry_source.read_text(),str(entry_source),'exec')
O.mkdir();entry=O/'after_original1097_terminal_full401_own_QI.py';entry.write_bytes(entry_source.read_bytes())
pp=O/'current315-own1377-next1097-durable401QI-three-fluid-omissions-readiness.json'
put(pp,{'schema':'ds02.current315.completed801QI.next-original401QI-readiness.v1','at_utc':now.isoformat(),'F5_original1160_actual_full801_own_QI':ref(own),'F5_original1160_personal_review_assignment':'source214 /root/f5_bed_recovery; not yet visually accepted','F5_original1151_actual_full801_own_QI':ref(own1151),'F5_original1151_personal_review_assignment':'source215 queued after214; not yet visually accepted','next_F2_case_id':w['case_id'],'next_F2_physical_case_id':w['physical_case_id'],'actual_previsual_scientific_dependency_review':ref(pre),'actual_completed_upstream_metadata_refs':{k:e for k,e in b.items() if isinstance(e,dict) and 'path' in e and 'sha256' in e},'native_canonical_condition_sha256':canonical,'typed_XMF_legacy_condition_sha256':legacy,'actual_native_XMF_plan_field_namespaces':mask,'genuine_initial_QA_metadata':qa,'genuine_initial_QA_actual_completed0_and_report_pass':True,'actual_particle_axis':418104,'actual_initial_fluid':21114,'actual_terminal_fluid':21111,'actual401_metadata_fluid_omissions':om,'actual_time_window_s':[0.0,4.000007783879406],'same_live_originals':live,'durable_original1097_only_full401_own_QI_entrypoint':ref(entry),'future_QI1385_unexecuted_and_proof_SHA_unknown':True,'command':['python3','-B',str(entry),'1097','1385'],'science_payload_IO':False,'new_jobs':0,'case_credit':0})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp)
new.update(checkpoint=288,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: originals1160/1151 actually completed0/published801 and ownQI1377/1380 executed once passed; source214 personal review active and next215 queued. Fresh195 provisional code defects reported for repair. Next originalF2 1097 actually admitted and same pvpython664604/start214297664 live; full401 metadata/genuine QA/canonical-native versus typedlegacy/exact three-fluid omissions pinned and durable ownQI1385 prepared without execution.',authorized_work_state='Active315/336 pending21. F5 originals1160/1151 published and own1377/1380 complete; personal214 active and next215 queued. F2 original1097 same real process live with durable own1385. Source195 F2 fulltime/runtime gates and source180 F5 final delivery builder in repair; no final48 claim from readiness utility.')
new['actual_progress']['current315_completed1160_own1377_next1097_durable401_QI']=ref(pp)
new['next_executable_tasks']=['Adopt source214 personal F5original1160 after exact committed package/readonly validation/published PNG hashes and ownQI1377 check; one case credit only.', 'Continue queued source215 personal F5original1151 after ownQI1380 passed; no QI rerun.', 'Wait same original1097 PID664604/start214297664 actual0/pub then execute durable ownQI1385 once and delegate personal17contacts9keys; preserve three omitted fluid IDs, first154/cumulative635 and unknown cause.', 'Audit source195 actual full401 lifecycle/time/runtime/QA/XMF receipts before executing; preserve P03 originaltyped135 runtimeunknown with actual recovery-aware197 certificate. Audit source180 actual full801 bed/native/typed/XMF primary gates and four genuine publish absences.', 'Continue remaining21 original registered cases, then actual F2/F3/F5 final48 primary deliveries and full336 completion audit. Home500GiB floor and budgets/deadline unchanged.']
put(np,new);updated=copy.deepcopy(idx);updated.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,current315_completed1160_own1377_next1097_durable401_QI=ref(pp))
updated['actual_unaccepted_completed0_published_physical_cases']=[{'family_id':'F5','physical_case_id':z['physical_case_id'],'case_id':z['case_id'],'own_QI':ref(p),'personal_review':s,'case_credit':0} for z,p,s in [(oq,own,'source214 pending'),(oq1151,own1151,'source215 queued')]]
put(O/'full336-current315-actual-final48-delivery-progress-index.json',updated);(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','DS02: close original1160 integrity and pin next F2 original1097 full401 omitted-fluid evidence','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':288,'accepted':315,'live':live,'own1377':ref(own),'future_QI_unexecuted':1385,'entry':ref(entry),'home_free_GiB':free,'GPUh':gpu,'CPUcoreh':cpu,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
