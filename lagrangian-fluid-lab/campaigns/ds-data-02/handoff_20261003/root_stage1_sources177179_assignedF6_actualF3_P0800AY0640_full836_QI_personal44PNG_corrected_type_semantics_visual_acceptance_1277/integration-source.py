from pathlib import Path
import json, hashlib, subprocess, copy, datetime, os, collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.xml','.xmf','.png'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def check(e):
 assert sha(e['path'])==e['sha256']
 if 'bytes' in e:assert Path(e['path']).stat().st_size==e['bytes']
 return load(e['path']) if Path(e['path']).suffix=='.json' else None
commits={177:'c025e12e62f3c0b5508be4f533572726e57c015d',179:'5cb9e0d5f81d907c0790ed28e4840573b7e8ead3'}
blobs={};prefixes={};validations={}
for n,c in commits.items():
 P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003').glob(f'root_followup_{n}_*'))
 prefixes[n]=P.relative_to(W)
 names=subprocess.check_output(['git','ls-tree','-r','--name-only',c,'--',str(prefixes[n])],cwd=W,text=True).splitlines();assert len(names)==5
 before={}
 for name in names:
  b=subprocess.check_output(['git','show',f'{c}:{name}'],cwd=W);assert (W/name).read_bytes()==b
  assert not (R/name).exists() or (R/name).read_bytes()==b
  blobs[name]=b;before[name]=sha(W/name)
 rv=subprocess.run(['python3','-B',str(P/f'scripts/validate_fresh{n}.py')],capture_output=True,text=True)
 assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={name:sha(W/name) for name in names}
 validations[n]={'source_commit':c,'source_SHA_before_after':before,'stdout':rv.stdout,'stderr':rv.stderr,'source_bytes_unchanged':True}
v=load(W/prefixes[177]/'metadata/personal-visual-decision.json')
png=load(W/prefixes[177]/'metadata/png-evidence.json')
c=load(W/prefixes[179]/'metadata/semantic-clarification.json')
direct=load(W/prefixes[179]/'metadata/direct-recheck-png-evidence.json')
qp=root(1269)/'actual1046-full836-completed-QI-UID-N3-native-scope-previsual-proof.json';qi=load(qp)
cid=qi['case_id'];pid=qi['physical_case_id'];canonical=qi['native_request_condition_sha256']
assert v['case']['case_id']==c['case']['case_id']==cid and v['case']['physical_case_id']==c['case']['physical_case_id']==pid
assert v['model']==c['model']=='gpt-5.6-luna' and v['reasoning_effort']==c['reasoning_effort']=='max'
assert not v['recursive_delegation'] and not c['recursive_delegation']
assert v['actual_case_family']==c['actual_physical_family']=='F3' and v['family_id']==c['assigned_family']=='F6'
assert v['decision']['status']=='visual-approved-by-delegated-agent' and v['decision']['case_credit']==0
assert qi['all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified'] and qi['all_native_UIds_active_each_frame']
assert canonical==qi['actual_converter_condition_sha256']==c['case']['canonical_native_scope_sha256']==c['case']['actual_converter_scope_sha256']
assert not qi['native_source_plan_physical_condition_field_present'] and not qi['XMF_source_plan_physical_condition_field_present']
assert not c['case']['native_source_plan_physical_condition_field_present'] and not c['case']['xmf_source_plan_physical_condition_field_present']
assert c['case']['source_namespace']['source_physical_condition_sha256'] is None
assert c['semantic_correction']['classification']=='template_semantic_misuse_confirmed_by_actual_counts_and_rendered_type_legend'
assert not c['semantic_correction']['new_physical_failure_identified']
for e in c['recheck'].values():
 if isinstance(e,dict) and 'path' in e:check(e)
assert c['recheck']['root1269_proof']['path']==str(qp) and c['recheck']['root1269_proof']['sha256']==sha(qp)
for e in qi['actual_completed_receipts'].values():
 z=check(e);assert (z['status'],z['returncode'])==('completed',0) and z['request']['case_id']==cid
for k in ('typed_report','XMF_manifest','XMF_XML','render_report','publish','initial_parent_QA_report','initial_parent_QA_receipt','source_preparation_report'):check(qi[k])
report=load(qi['render_report']['path']);manifest=load(qi['XMF_manifest']['path']);pub=load(qi['publish']['path'])
assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==qi['render_report']['sha256']
assert report['frames']==report['source_frames']==manifest['frames']==836 and report['manifest_sha256']==qi['XMF_manifest']['sha256']
assert report['xdmf']==manifest['xdmf']==qi['XMF_XML']['path'] and report['xdmf_sha256_after']==manifest['xdmf_sha256']==qi['XMF_XML']['sha256']
assert report['all_frames_rendered'] and report['native_identity_axis_preserved'] and report['nonfinite_active_states']==0
assert report['frame_selection']==list(range(836)) and [x['actual_time_s'] for x in report['frame_diagnostics']]==manifest['actual_time_s']
assert png['personal_view_completed'] and png['personally_viewed_with']=='view_image' and len(png['items'])==44
contacts=[e for e in png['items'] if 'sheet_index' in e];keys=[e for e in png['items'] if 'sheet_index' not in e]
assert len(contacts)==35 and len(keys)==9 and [e['path'] for e in contacts]==report['outputs']['contact_sheets']
assert png['key_frame_indices']==[0,104,208,312,417,521,626,730,835]
out=Path(pub['published_output_root']);published={e['relative_path']:e for e in pub['files_excluding_receipt']}
for e in png['items']:
 assert e['viewed'] and e['viewed_with']=='view_image';check(e)
 pe=published[str(Path(e['path']).relative_to(out))];assert pe['sha256']==e['sha256'] and pe['bytes']==e['bytes']
for e in direct['items']:check(e);assert e['viewed_again'] and e['viewed_with']=='view_image'
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_228.json';cp=load(cpfile)
assert cp['checkpoint']==228 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==287 and cp['accepted_per_family']['F3']==38
old=[load(p) for p in cp['accepted_decisions']];assert pid not in {z.get('physical_case_id',z['case_id']) for z in old}
idxp=root(1276)/'full336-current287-actual-final48-delivery-progress-index.json';idx=load(idxp)
targets=[r for r in idx['cases'] if r['physical_case_id']==pid];assert len(targets)==1 and not targets[0].get('accepted_decision') and targets[0]['native_request_scope']['sha256']==canonical
assert all(r.get('native_request_scope',{}).get('sha256')!=canonical for r in idx['cases'] if r.get('accepted_decision'))
for k,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][k]
now=datetime.datetime.now(datetime.timezone.utc);assert datetime.datetime.fromisoformat(v['created_at_utc'])<=now
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600
sv=os.statvfs('/home/jade');free=sv.f_bavail*sv.f_frsize/2**30
assert free>=500 and gpu<512 and cpu<3840 and counts['qualification']<=1024 and counts['production']<=720
O=H/'root_stage1_sources177179_assignedF6_actualF3_P0800AY0640_full836_QI_personal44PNG_corrected_type_semantics_visual_acceptance_1277'
nextcp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_229.json';assert not list(H.glob('root*_1277')) and not nextcp.exists()
O.mkdir();adopted=[]
for rel,b in blobs.items():
 p=R/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);adopted.append(ref(p))
vp=O/'sources177179-byte-exact-readonly-validation.json';put(vp,{'sources':validations,'adopted_source_files':adopted,'main_all44_published_PNG_hashes_match_actual_atomic_publication':True,'main_scientific_payload_IO':False})
dp=O/f'{pid}-delegated-visual-decision.json'
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F3','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':canonical,'source_assigned_agent_family':'F6','source_review':ref(R/prefixes[177]/'metadata/personal-visual-decision.json'),'source_review_closure':ref(R/prefixes[177]/'metadata/chain-closure.json'),'source_review_PNG_evidence':ref(R/prefixes[177]/'metadata/png-evidence.json'),'source_semantic_clarification':ref(R/prefixes[179]/'metadata/semantic-clarification.json'),'original_body_language_is_superseded_by_corrected_visual_observations':True,'corrected_visual_observations':c['semantic_correction']['corrected_fields'],'source_condition_template_file_sha256':c['case']['source_condition_template_file_sha256'],'source_condition_template_file_digest_is_provenance_not_native_XMF_physical_plan':True,'source_namespace_physical_condition_sha256':None,'native_source_plan_field_present':False,'XMF_source_plan_field_present':False,'independent_full836_QI':ref(qp),'actual_completed_metadata_evidence':qi,'full_native_frames':836,'particle_count':179208,'actual_type_counts':c['actual_type_evidence']['generated_particle_counts'],'actual_physical_window_s':qi['actual_time_window_s'],'all_native_UIDs_active_each_frame':True,'all836_UID_N3_actual_times_finite_states_verified':True,'agent_personally_viewed_all_contacts_and_keys':True,'contact_sheets':contacts,'keyframes':keys,'personal_reviewed_contacts':35,'personal_reviewed_keyframes':9,'main_all44_PNG_hashes_match_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
proof=O/'source177179-actual1046-full836-QI-personal-visual-adoption.json';put(proof,{'source_validation':ref(vp),'independent_QI':ref(qp),'new_visual_decision':ref(dp),'source_original_bytes_preserved':True,'rigid_body_template_misuse_resolved_by_child_actual_image_recheck':True,'source_template_FILE_hash_role_corrected_separately_from_native_XMF_plan_absence':True,'actual44PNG_bound_to_atomic_publish':True,'case_credit':1,'main_scientific_payload_IO':False})
ledger=O/'ledger-immutable-snapshot.json';ledger.write_bytes(raw);newcp=copy.deepcopy(cp);newcp['accepted_per_family']['F3']+=1
newcp.update(checkpoint=229,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=288,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(ledger),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: delivered actual72 first24 products and corrected6 planned/frozen-first8 flags without mutating sources; actual F3P0800AY0640 original1046 full836 ownQI1269 + child177 full44PNG and179 semantic/image clarification accepted288. F5original1148 completed and ownQI1272 done; child201 visual review ongoing.',authorized_work_state='Active288/336; F1/F4/F7=48,F2=39,F3=39,F5=19,F6=47;48 pending. All case labels visual only, QN/QE=0.')
newcp['actual_progress']['source177179_actualF3_1046_acceptance']=ref(proof)
newcp['actual_progress']['F5_actual1148_full801_QI']=ref(root(1272)/'actual1148-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json')
newcp['source_agents']['f6_endpoint_initial_qa']='fresh177+179 accepted F3=39; fresh180 last pendingF6 actualmetadata readiness/original951 observer'
newcp['source_agents']['f5_bed_recovery']='fresh201 original1148 completed0 and ownQI1272 provided; personal34contacts9keys review pending'
newcp['source_agents']['production_recovery']='fresh165 M115T080 original1186 same live handle observer and personal34contacts9keys after atomicpublication'
newcp['next_executable_tasks']=['Adopt fresh201 F5 M098T095 original1148 personal43PNG with ownQI1272.','After original1186 atomicpublication run ownfull801QI1275 and adopt fresh165 M115T080 personal43PNG.','Integrate fresh180 lastF6 native/typed/XMF readiness and observe original951 to completion.','Continue original pending render queues under cap2, actual336 target; do not rerun completed scientific calculations.']
assert len(newcp['accepted_decisions'])==sum(newcp['accepted_per_family'].values())==288;put(nextcp,newcp)
idx.update(previous_index_preserved=ref(idxp),source_authoritative_checkpoint=ref(nextcp),at_utc=now.isoformat(),accepted_independent_physical_cases=288,registered_pending_independent_physical_cases=48,new_case_credit=1)
targets[0].update(status='visual-approved-in-checkpoint229',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full836_QI=ref(qp))
idx['actual_unaccepted_completed0_published_physical_cases']=[x for x in idx['actual_unaccepted_completed0_published_physical_cases'] if (x.get('physical_case_id') if isinstance(x,dict) else x)!=pid]
assert len(idx['cases'])==336 and sum(bool(r.get('accepted_decision')) for r in idx['cases'])==288
put(O/'full336-current288-actual-final48-delivery-progress-index.json',idx)
(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=list(blobs)+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str(nextcp.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: accept F3 pitch080 ay0640 full836 after actual type semantics clarification','--',*paths],cwd=R,check=True)
print(json.dumps({'accepted':288,'F3':39,'checkpoint':229,'remaining':48,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
