from pathlib import Path
import json,hashlib,datetime,subprocess,copy,os,collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.png','.py','.md'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def checked(e):
 assert sha(e['path'])==e['sha256']
 if 'bytes' in e:assert Path(e['path']).stat().st_size==e['bytes']
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='0facccb6e6fecdab85e13f41c8c0bbb284d785e6';P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003').glob('root_followup_215_*'));prefix=P.relative_to(W)
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines()
expected={'README.md','manifest.json','metadata/actual-render-metadata.json','metadata/physical-stage-closure.json','metadata/png-visual-evidence.json','metadata/upstream-evidence.json','metadata/visual-decision.json','scripts/validate_fresh215.py'}
assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
man=load(P/'manifest.json');assert {e['path'] for e in man['files']}==expected-{'manifest.json'}
for e in man['files']:assert sha(P/e['path'])==e['sha256'] and (P/e['path']).stat().st_size==e['bytes']
before={n:sha(W/n) for n in names};rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh215.py')],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
qip=root(1380)/'actual1151-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';qi=load(qip);assert sha(qip)=='cff63d81004e5cfefe2bfc3021ed2000fc250c1921781f7cc7dd58d97586bd50'
s=load(P/'metadata/visual-decision.json');a=load(P/'metadata/actual-render-metadata.json');u=load(P/'metadata/upstream-evidence.json');v=load(P/'metadata/png-visual-evidence.json');cl=load(P/'metadata/physical-stage-closure.json');cid=qi['case_id'];pid=qi['physical_case_id']
for j in [s,a,u,v,cl]:assert j['case_id']==cid and j['physical_case_id']==pid
assert cid=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M108_T085_NEXT34' and pid=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M108_T085'
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sd=qi['actual_SourceDef']['sha256'];checked(qi['actual_SourceDef'])
assert len({canonical,legacy,sd})==3 and qi['binding_source_definition_field_present'] and qi['native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified']
assert qi['full_frames']==801 and qi['particles']==194427 and qi['fluid_initial_UIDs']==31658 and qi['all_native_UIDs_active_each_frame'] and qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked']
er=qi['actual_completed_metadata_evidence'];assert set(u['actual_completed_metadata_evidence'])==set(er)
for k,e in er.items():
 checked(e);se=u['actual_completed_metadata_evidence'][k];assert se['path']==e['path'] and se['sha256']==e['sha256']
 if k.endswith('_receipt') and k!='render_publish_receipt':
  rr=load(e['path']);assert rr['schema']=='ds02.execution-receipt.v1' and rr['status']=='completed' and rr['returncode']==0 and rr['request']['case_id']==cid
checked(u['main_qi']);checked(s['qi_reference']);assert u['main_qi']['path']==s['qi_reference']['path']==str(qip)
n=load(er['native_receipt']['path']);x=load(er['xmf_manifest']['path']);native=n['request']
masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',native),('XMF',x)]}
assert masks==qi['actual_native_XMF_plan_field_namespaces']
assert all(m=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}} for m in masks.values())
sr=u['producer_scope_roles'];assert sr==a['scope_roles']==cl['scope_roles']
assert sr['canonical_physical_condition_sha256']==canonical and sr['actual_converter_legacy_scope_sha256']==sr['typed_legacy_scope_sha256']==legacy and sr['source_definition_sha256']==sd
for ns in ['native','xmf']:
 assert sr[f'{ns}_source_plan_condition_field_present'] is False and sr[f'{ns}_source_plan_condition_sha256'] is None
 assert sr[f'{ns}_source_plan_physical_condition_field_present'] is True and sr[f'{ns}_source_plan_physical_condition_sha256']==canonical
assert sr['roles_are_distinct'] and not sr['scope_equality_claimed'] and sr['condition_plan_absence_preserved_without_backfill']
bedrec=load(er['bed_receipt']['path']);binding=load(bedrec['request']['binding']);plan=ref(binding['source_plan_file'])
assert plan['sha256']==binding['source_plan_file_sha256']==sr['source_plan_file_sha256']
assert n['input_hashes_at_launch'][plan['path']]==n['input_hashes_after_run'][plan['path']]==plan['sha256']
assert bedrec['input_hashes_at_launch'][plan['path']]==bedrec['input_hashes_after_run'][plan['path']]==plan['sha256']
assert binding['source_definition_sha256']==sd and binding['source_plan_physical_condition_sha256']==sd
assert a['producer_counts']=={'total_initial':194427,'fixed':158559,'moving':4210,'floating':0,'fluid_initial':31658,'solver_dimension':3,'data2d':False}
assert cl['counts_and_time']=={**a['producer_counts'],'frames':801,'time_window_s':qi['actual_time_window_s']}
assert a['expected_and_actual']['time_window_s']==u['main_qi']['actual_time_window_s']==qi['actual_time_window_s']
dec=s['decision'];assert dec['standalone_first_stage_visual_approved'] and not dec['severe_visual_failure'] and not dec['needs_root_image_intervention'] and dec['independent_case_count_increment']==0
for k in ['q_n_granted','q_e_granted','strict_container_guarantee','sub_dp_penetration_absence_claim','numerical_precision_accepted','large_runup_or_inundation_established']:assert dec[k] is False
assert dec['weak_or_localized_response_limit'] and all(cl['historical_failures_retained'].values()) and not qi['actual_initial_QA_precision_negative']['pass_at_original_threshold']
reviewed=s['reviewer']['reviewed_at_utc'];assert reviewed==a['personal_review_scope']['reviewed_at_utc']==v['reviewer']['reviewed_at_utc']
assert s['reviewer']['model']==a['personal_review_scope']['reviewer_model']==v['reviewer']['model']=='gpt-5.6-luna/max'
assert all(not q['recursive_delegation'] for q in [s['reviewer'],a['personal_review_scope'],v['reviewer']])
contacts=[{'path':e['absolute_path'],'sha256':e['sha256'],'bytes':e['bytes'],'sheet_index':e['index'],'viewed':e['reviewed']} for e in v['producer_attested_contact_sheets']]
keys=[{'path':e['absolute_path'],'sha256':e['sha256'],'bytes':e['bytes'],'frame':e['frame_index'],'viewed':e['reviewed']} for e in v['producer_attested_keyframes']]
assert len(contacts)==34 and len(keys)==9 and [e['sheet_index'] for e in contacts]==list(range(34)) and [e['frame'] for e in keys]==list(range(0,801,100))
pub=load(er['render_publish_receipt']['path']);report=load(er['render_report']['path']);receipt=load(er['render_receipt']['path'])
assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
assert report['frames']==report['source_frames']==801 and report['all_frames_rendered'] and not report['diagnostic_only'] and report['nonfinite_active_states']==0
pubroot=Path(pub['published_output_root']);pubfiles={r['relative_path']:r for r in pub['files_excluding_receipt']}
assert [e['path'] for e in contacts]==report['outputs']['contact_sheets']
for e in contacts+keys:
 p=Path(e['path']);r=pubfiles[str(p.relative_to(pubroot))];checked(e);assert e['sha256']==r['sha256'] and e['bytes']==r['bytes'] and e['viewed']
now=datetime.datetime.now(datetime.timezone.utc);assert datetime.datetime.fromisoformat(receipt['finished_at_utc'])<=datetime.datetime.fromisoformat(reviewed.replace('Z','+00:00'))<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_290.json';cp=load(cpfile);assert cp['checkpoint']==290 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==316 and cp['accepted_per_family']['F5']==36
assert pid not in {load(p)['physical_case_id'] for p in cp['accepted_decisions']}
ip=root(1388)/'full336-current316-actual-final48-delivery-progress-index.json';index=load(ip);assert index['source_authoritative_checkpoint']==ref(cpfile)
target=next(z for z in index['cases'] if z['physical_case_id']==pid);assert not target.get('accepted_decision') and target['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(z['kind'] for z in ld['attempts']);gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600
vf=os.statvfs('/home/jade');free=vf.f_bavail*vf.f_frsize/2**30;assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source215_actualF5_M108T085_original1151_full801QI_personal43PNG_native_XMF_physicalplan_canonical_SourceDef_FILE_separate_visual_acceptance_1389';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_291.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
proof=O/'source215-byte-exact-readonly-validator-main43publishedPNG-own801QI-and-actual-review-time-proof.json'
put(proof,{'schema':'ds02.main.F5.personal43PNG-source-adoption-proof.v3','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'independent_own_QI':ref(qip),'all43_publishedPNG_hashes_match_actual_atomic_publish':True,'actual_personal_review_time_utc':reviewed,'review_after_completed_publication':True,'actual_native_XMF_plan_field_namespaces':masks,'native_and_XMF_physical_plan_canonical_and_bed_SourceDef_FILE_separate_roles_independently_checked':True,'source_plan_JSON_file_role_separately_verified':plan,'source_legacy_alias_correction_needed':False,'all_actual_primary_refs_and_genuine_QA_receipts_verified':True,'main_scientific_payload_IO':False})
dp=O/f'{pid}-delegated-visual-decision.json'
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':'F5','source_personal_visual_review':ref(R/prefix/'metadata/visual-decision.json'),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':{'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'total':194427},'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_XMF_plan_field_namespaces':masks,'actual_XMF_source_plan_physical_condition_field_value':canonical,'actual_XMF_physical_plan_has_native_canonical_role':True,'actual_XMF_physical_plan_has_SourceDef_role':False,'actual_bed_plan_field_value':sd,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_roles_are_distinct':True,'actual_source_plan_JSON_file':plan,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'actual_personal_review_time_utc':reviewed,'contact_sheets':contacts,'keyframes':keys,'visual_observations':v['personal_observation'],'visual_limits':{'source_visual_limits':s['evidence_limits'],'source_physical_closure':cl,'source_scope_roles':sr},'no_strong_runup_or_inundation_magnitude_claim_from_visual_screen':True,'original_precision_negative':qi['actual_initial_QA_precision_negative'],'historical_negative_flags':qi['historical_negative_flags'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source215-actual1151-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(proof),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1
new.update(checkpoint=291,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=317,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: F5 M108T085 original1151 ownQI1380 and source215 personal43publishedPNG accepted once; actual native/XMF canonical physical-plan versus typedlegacy/bedSourceDefFILE/planJSON independently verified, genuine initialQA/precisionnegative retained.',authorized_work_state='Active317/336 pending19. F5=37, source216 F2original1097 and source181 F3original1194 waiting publication and ownQIs1385/1387. F2original1097 and F3original1194 same registered renders active with durable future own1385/1387. Source195/180 delivery tool packages await independent main audit.')
new['actual_progress']['source215_F5_actual1151_visual_acceptance']=ref(ap);new['source_agents']['f5_bed_recovery']='fresh215 actualF5 M108T085 accepted; fresh216 F2original1097 review assigned after future ownQI1385'
new['next_executable_tasks']=['Continue source216 F2original1097 and source181 F3original1194 after actual ownQIs1385/1387.', 'Wait original1097 actual0/pub then execute prepared ownQI1385 once and delegate personal17contacts9keys preserving three fluid omissions.', 'Wait original1194 actual0/pub then execute prepared recovery-aware ownQI1387 once and delegate personal35contacts9keys preserving originaltyped154 running/no RC.', 'Complete source195 F2 and source180 F5 fulltime/runtime/primary builder repairs with actual code audits; repair F3 source176 gates before real final48 delivery.', 'Continue all remaining19 original cases, actual F2/F3/F5 final48 deliveries and full336 objective audit; Home500GiB/budgets/deadline unchanged.']
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==317;put(np,new)
index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=317,registered_pending_independent_physical_cases=19,new_case_credit=1)
target.update(status='visual-approved-in-checkpoint291',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
index['actual_unaccepted_completed0_published_physical_cases']=[z for z in index['actual_unaccepted_completed0_published_physical_cases'] if (z if isinstance(z,str) else z['physical_case_id'])!=pid]
assert len(index['cases'])==336 and sum(bool(z.get('accepted_decision')) for z in index['cases'])==317
put(O/'full336-current317-actual-final48-delivery-progress-index.json',index);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: accept F5 M108T085 full801 personal review preserving actual canonical and SourceDef roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':291,'accepted':317,'F5':37,'pending':19,'decision':ref(dp),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
