from pathlib import Path
import json, hashlib, subprocess, datetime, collections, copy, os, re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p); assert p.suffix.lower() in {'.json','.md','.py','.xml','.xmf','.png'}
 if p.suffix.lower()=='.png': assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p): return {'path':str(p),'sha256':sha(p)}
def check(e): assert sha(e['path'])==e['sha256'],e['path']
def same(a,b): return a['path']==b['path'] and a['sha256']==b['sha256']
def put(p,v):
 with Path(p).open('x') as f: json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def parse(t): return datetime.datetime.fromisoformat(re.sub(r'(\.\d{6})\d+(?=Z|[+-])',r'\1',t).replace('Z','+00:00'))
commit='8c88e1a8e16ad786721e360544a02b7e2b73c3c8'
prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_185_f3_assigned_f3_p0800_ay0500_actual1031_personal_visual_review_v1')
P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==6
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items(): assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names}
rv=subprocess.run(['python3','-B',str(P/'validate_fresh185.py')],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
s=load(P/'metadata/actual1031-personal-visual-decision.json');png=load(P/'metadata/png-evidence/actual1031.json');man=load(P/'package-manifest.json')
assert man['package_manifest_excluded_from_own_hash'] and {e['path'] for e in man['files']}=={str(Path(n).relative_to(prefix)) for n in names if not n.endswith('package-manifest.json')}
qip=root(1401)/'actual1031-full836-completed-QI-UID-N3-native-scope-previsual-proof.json';qi=load(qip)
assert sha(qip)=='d25ae2322b4ec192f488a670938f0cdd68277ed9137015f7d5c0f643204e29a9'
assert same(s['provenance']['qi_proof'],ref(qip))
cid=qi['case_id'];pid=qi['physical_case_id'];canonical=qi['native_request_condition_sha256']
assert canonical=='f78c73b5fd41160a14509e76c6cc3033492af762d217108a18db737c745eef99'
assert s['case_id']==png['case_id']==cid and s['physical_case_id']==png['physical_case_id']==pid
assert s['assigned_worktree_family']==s['actual_case_family']=='F3' and s['configured_model']=='gpt-5.6-luna/max' and not s['model_substitution'] and not s['recursive_delegation']
v=s['visual_review'];limits=s['precision_and_limits']
assert v['status']=='visual-approved-by-delegated-agent' and v['screen']=='pass_first_stage'
assert v['png_files_opened_with_view_image'] and not v['scientific_jobs_started_or_restarted'] and not v['scientific_payload_opened_or_hashed_by_reviewer'] and not v['shared_state_modified']
assert limits['case_credit']==v['case_credit']==0 and not limits['q_n_granted'] and not limits['q_e_granted'] and not v['q_n_granted'] and not v['q_e_granted']
chain=s['actual_chain'];receipts={}
for role,e in qi['actual_completed_receipts'].items():
 se=chain[role+'_receipt'];check(se);assert same(se,e)
 j=load(e['path']);assert j['schema']=='ds02.execution-receipt.v1' and j['status']=='completed' and j['returncode']==0 and j['request']['case_id']==cid and j['request']['physical_case_id']==pid;receipts[role]=j
for key in ['typed_report','XMF_manifest','XMF_XML','render_report','publish','initial_parent_QA_receipt','initial_parent_QA_report','source_preparation_report']:
 check(chain[key]);assert same(chain[key],qi[key])
nq=receipts['native']['request'];x=load(qi['XMF_manifest']['path'])
masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]}
assert masks==qi['actual_native_XMF_plan_field_namespaces']==s['physical_condition_roles']['native_and_xmf_plan_field_namespaces']
assert all(not e['present'] and e['value'] is None for row in masks.values() for e in row.values())
sc=s['physical_condition_roles'];assert canonical==qi['actual_converter_condition_sha256']==x['physical_condition_sha256']==sc['native_canonical_condition_sha256']==sc['typed_legacy_converter_scope_sha256']==sc['xmf_physical_condition_sha256']
assert qi['all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified'] and qi['all_native_UIds_active_each_frame']
dims=s['actual_dimensions'];assert dims['frames']==836 and dims['particles']==179208 and dims['vector_shape']=='N x 3' and dims['time_window_s']==qi['actual_time_window_s']==[0.0,8.350012599876457]
assert dims['render_type_counts_frame0']==dims['render_type_counts_last_frame']=={'fixed':111708,'moving':0,'floating':0,'fluid':67500,'unknown':0}
qa=load(qi['initial_parent_QA_receipt']['path']);assert qa['status']=='completed' and qa['returncode']==0
r=load(qi['render_report']['path']);pub=load(qi['publish']['path']);assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==sha(qi['render_report']['path'])
assert pub['attempt_id']==receipts['render']['request']['attempt_id'] and r['manifest_sha256']==sha(qi['XMF_manifest']['path'])
assert r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['frames']==r['source_frames']==836
out=Path(pub['published_output_root']);published={e['relative_path']:e for e in pub['files_excluding_receipt']}
contacts=s['visual_evidence']['contacts'];keys=s['visual_evidence']['keys'];assert contacts==png['contacts'] and keys==png['keys']
assert len(contacts)==35 and [e['relative_path'] for e in contacts]==[f'all_frames_{n:03d}.png' for n in range(35)]
keyids=[0,100,200,300,400,500,600,700,835];assert len(keys)==9 and [e['relative_path'] for e in keys]==[f'frames/frame_{n:04d}.png' for n in keyids]
assert [e['path'] for e in contacts]==r['outputs']['contact_sheets'] and v['contact_sheets_viewed']==35 and v['key_frames_viewed']==keyids
for e in contacts+keys:
 p=Path(e['path']);assert p==out/e['relative_path'] and sha(p)==e['declared_sha256']==published[e['relative_path']]['sha256'] and p.stat().st_size==e['bytes']==published[e['relative_path']]['bytes']
 assert e['personally_viewed_with_view_image'] and e['stat_checked'] and e['sha256_source']=='render_publish_receipt'
reviewed=s['review_completed_at_utc'];now=datetime.datetime.now(datetime.timezone.utc)
assert parse(receipts['render']['finished_at_utc'])<=parse(reviewed)<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_304.json';cp=load(cpfile)
assert cp['checkpoint']==304 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==322 and cp['accepted_per_family']['F3']==45
ip=root(1407)/'full336-current322-actual-final48-delivery-progress-index.json';idx=load(ip);assert same(idx['source_authoritative_checkpoint'],ref(cpfile))
row=next(e for e in idx['cases'] if e['physical_case_id']==pid);assert not row.get('accepted_decision') and row['native_request_scope']['sha256']==canonical
assert len({e['physical_case_id'] for e in idx['cases']})==len(idx['cases'])==336
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(e['kind'] for e in ld['attempts'])
gpu=sum(e.get('gpu_seconds',0) for e in ld['charges'])/3600;cpu=sum(e.get('cpu_core_seconds',0) for e in ld['charges'])/3600
vf=os.statvfs('/home/jade');free=vf.f_bavail*vf.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<parse(cp['deadline_utc'])
O=H/'root_stage1_source185_actualF3_P0800AY0500_original1031_full836QI_personal44PNG_native_XMF_both_plan_absence_true_parentQA_visual_acceptance_1409'
np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_305.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'validate_fresh185.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/n).read_bytes()==b and (W/n).read_bytes()==b for n,b in blobs.items())
clar=O/'source185-personal-PNG-viewing-versus-declared-publisher-SHA-boundary-clarification.json'
put(clar,{'source_decision':ref(R/prefix/'metadata/actual1031-personal-visual-decision.json'),'source_png_read_or_hashed_flag_preserved':False,'actual_personal_view_image_count':44,'personal_image_viewing_reads_image_content':True,'reviewer_did_not_independently_hash_PNGs':True,'publisher_SHA_was_copied_and_stat_checked_by_source':True,'main_independently_hashed_all44_published_PNGs':True,'scientific_payloads_not_opened_or_hashed':True,'scope':'The source false read/hash flag describes its producer-SHA/stat workflow; it does not negate the actual personal image viewing. Source bytes preserved.'})
vp=O/'source185-byte-exact-readonly-validator-main44publishedPNG-own836QI-true-plan-absences-parentQA-proof.json'
put(vp,{'schema':'ds02.source185.main.actualF3.adoption-integrity.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'source_before_after_SHA':before,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'own_QI':ref(qip),'actual_reviewed_at_utc':reviewed,'review_after_completed_publication':True,'all44_publishedPNG_SHA_match_atomic_publish':True,'actual_native_XMF_plan_namespaces':masks,'actual_native_typed_XMF_same_canonical_digest':canonical,'source_conditions_and_plan_namespaces_are_separate_roles':True,'parent_QA_and_source704_reused_initialization_preserved_not_fabricated_percase_receipt':True,'PNG_boundary_clarification':ref(clar),'main_scientific_payload_IO':False})
nc=[{**e,'producer_sha256':e['declared_sha256'],'viewed':True,'view_method':'view_image','role':'contact_sheet'} for e in contacts]
nk=[{**e,'frame':n,'producer_sha256':e['declared_sha256'],'viewed':True,'view_method':'view_image','role':'event_keyframe'} for e,n in zip(keys,keyids)]
dp=O/(pid+'-delegated-visual-decision.json')
evidence={**chain,'actual_completed_receipts':qi['actual_completed_receipts'],'XMF_receipt':chain['xmf_receipt'],'render_publish_receipt':chain['publish']}
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F3','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':canonical,'producer_scope_schema':'ds-data-02.physical-binding.v1','source_review_commit':commit,'source_review_assigned_family':'F3','actual_review_family':'F3','source_personal_visual_review':ref(R/prefix/'metadata/actual1031-personal-visual-decision.json'),'source_review_closure':ref(vp),'independent_full836_QI':ref(qip),'actual_completed_metadata_evidence':evidence,'full_native_frames':836,'particle_count':179208,'initial_fluid_particles':67500,'actual_type_counts':dims['render_type_counts_frame0'],'actual_physical_window_s':qi['actual_time_window_s'],'all836_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'actual_native_XMF_plan_field_namespaces':masks,'native_and_XMF_plan_fields_true_absence_not_filled_from_canonical':True,'original_outer_envelope_801194427_not_actual836179208_authority':True,'true_genuine_parent_initial_QA_reused_not_fabricated_percase_runner_receipt':True,'registered_decoder_CLI_repair_actual_typed_completed0_old_failed_receipt_history_preserved':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':35,'personal_reviewed_keyframes':9,'personal_reviewed_at_utc':reviewed,'contact_sheets':nc,'keyframes':nk,'visual_observations':v['observations'],'visual_limits':v['physical_screen_limits']+limits['limits'],'strict_container_guarantee':False,'historical_and_precision_negative_evidence_preserved':True,'main_all44_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source185-actual1031-full836QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(vp),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp);new['accepted_per_family']['F3']+=1
new.update(checkpoint=305,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=323,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,authorized_work_state='Active323/336; F1/F4/F6/F7=48,F2=46,F3=46,F5=39. Source185 original1031 genuine full836 ownQI1401/personal44PNG accepted. Original1162 completed/0 and ownQI1404 passed; fresh220 personal43PNG active. Final48 F2 tool197 active, F3 tool196 pending audit; F5 tool218 bounded repair audited readiness only. No new native runs or precision credit.',previous_goal_turn_classification='PROGRESS: user storage cleanup current audit1408 confirmed original17203 deletions/38 preserved diagnostics/21 unchanged receipts and Home782GiB. This turn actual1162 own full801QI completed, source185 full836 personal44PNG independently joined and accepted323; overall336 scope unchanged.')
new['actual_progress']['source185_F3_actual1031_visual_acceptance']=ref(ap)
new['actual_progress']['original1162_full801_own_QI1404']=ref(root(1404)/'actual1162-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json')
new['actual_progress']['user_storage_current_retention1408']=ref(root(1408)/'current-storage-cleanup-verification.json')
new['source_agents'].update(f5_bed_recovery='fresh220 F5original1162 own1404 complete personal34contacts9keys active',production_recovery='fresh185 original1031 accepted323; available for next actual case personal review',f6_endpoint_initial_qa='fresh197 F2 final48 remaining gate repair active; source196 F3 completed immutable pending main code audit')
new['next_executable_tasks']=['Integrate fresh220 only after actual43PNG personal review and immutable source validation; own1404 completed do not rerun.','Observe remaining original render controllers and actual worker receipt handles; prepare the next actual F2/F3/F5 own full-time QI after completed/0 atomic publication.','Audit completed source196 F3 and source197 F2 final48 tools; bounded repair followed by manual actual primary joins, runtime unknown preserved.','Finish all remaining13 independent visual cases and actual48 F2/F3/F5 primary deliveries plus global336 navigation; Q-N/Q-E remain unaccepted.']
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==323;put(np,new)
idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=323,registered_pending_independent_physical_cases=13,new_case_credit=1)
row.update(status='visual-approved-in-checkpoint305',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full836_QI=ref(qip))
idx['actual_unaccepted_completed0_published_physical_cases']=[e for e in idx['actual_unaccepted_completed0_published_physical_cases'] if (e if isinstance(e,str) else e['physical_case_id'])!=pid]
idx['original1162_completed_full801_QI_pending_personal_visual']=ref(root(1404)/'actual1162-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json')
assert len(idx['cases'])==336 and sum(bool(e.get('accepted_decision')) for e in idx['cases'])==323
put(O/'full336-current323-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','DS02: accept F3 P0800AY0500 personal44PNG full836QI retaining true plan absences','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':305,'accepted':323,'F3':46,'pending':13,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
