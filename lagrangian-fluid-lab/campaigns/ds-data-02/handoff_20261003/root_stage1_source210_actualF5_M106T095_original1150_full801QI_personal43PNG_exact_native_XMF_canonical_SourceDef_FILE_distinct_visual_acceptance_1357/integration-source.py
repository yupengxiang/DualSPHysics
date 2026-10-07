from pathlib import Path
import json, hashlib, subprocess, copy, collections, datetime, os, sys
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.png','.py','.md'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def checked(e):
 assert sha(e['path'])==e['sha256'],e
 if 'bytes' in e:assert Path(e['path']).stat().st_size==e['bytes']
def put(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
mode=int(sys.argv[1]);assert mode in [210,191]
if mode==210:
 wn=5;original=1150;qinum=1349;outnum=1357;oldcp=270;oldcount=307;oldF5=30;commit='75aff06713cc059987e85a457876f5fbae41296b';tag='M106T095';oldindexroot=1360
else:
 wn=6;original=1157;qinum=1350;outnum=1358;oldcp=271;oldcount=308;oldF5=31;commit='e7e454bd87c06d3837dae34b44418da3fd3dfee6';tag='M100T080';oldindexroot=1357
W=Path(f'/home/jade/.codex/worktrees/ds-data-02-f{wn}/DualSPHysics');P=next((W/f'lagrangian-fluid-lab/campaigns/ds-data-02/families/F{wn}/handoff_20261003').glob(f'root_followup_{mode}_*'));prefix=P.relative_to(W)
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==(8 if mode==210 else 5)
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};rv=subprocess.run(['python3','-B',str(P/f'scripts/validate_fresh{mode}.py')],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
qip=root(qinum)/f'actual{original}-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';qi=load(qip);cid=qi['case_id'];pid=qi['physical_case_id'];counts={'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'total':194427}
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sd=qi['actual_SourceDef']['sha256'];checked(qi['actual_SourceDef']);assert len({canonical,legacy,sd})==3 and qi['binding_source_definition_field_present']
assert qi['full_frames']==801 and qi['particles']==194427 and qi['fluid_initial_UIDs']==31658 and qi['all_native_UIDs_active_each_frame'] and qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked']
assert not qi['actual_native_source_plan_condition_field_present'] and qi['actual_native_source_plan_condition_sha256'] is None
assert qi['actual_native_source_plan_physical_condition_field_present'] and qi['actual_native_source_plan_physical_condition_sha256']==canonical
assert qi['XMF_source_plan_physical_condition_field_sha256']==canonical and qi['bed_declared_source_plan_field_sha256']==sd
assert qi['XMF_source_plan_physical_condition_field_has_native_canonical_role'] and not qi['XMF_source_plan_physical_condition_field_has_SourceDef_role']
er=qi['actual_completed_metadata_evidence'];native=load(er['native_receipt']['path'])['request'];xm=load(er['xmf_manifest']['path'])
rawmask={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',native),('XMF',xm)]}
assert rawmask==qi['actual_native_XMF_plan_field_namespaces']
for masks in rawmask.values():assert masks=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}}
if mode==210:
 s=load(P/'metadata/visual-decision.json');a=load(P/'metadata/actual-render-metadata.json');u=load(P/'metadata/upstream-evidence.json');v=load(P/'metadata/png-visual-evidence.json');cl=load(P/'metadata/physical-stage-closure.json');man=load(P/'manifest.json')
 for j in [s,a,u,v,cl]:assert j['case_id']==cid and j['physical_case_id']==pid
 for e in man['files']:assert sha(P/e['path'])==e['sha256'] and (P/e['path']).stat().st_size==e['bytes']
 assert u['actual_completed_metadata_evidence']==er and u['main_qi']['path']==str(qip);checked(u['main_qi']);checked(s['qi_reference']);assert u['actual_SourceDef']==qi['actual_SourceDef']
 assert a['assignment']['reviewer_model']==s['reviewer']['model']=='gpt-5.6-luna/max' and not a['assignment']['recursive_delegation'] and not s['reviewer']['recursive_delegation']
 sr=u['producer_scope_roles'];assert sr==a['scope_roles']==cl['scope_roles']
 assert sr['native_request_and_actual_converter_canonical']==canonical and sr['typed_legacy_scope']==legacy and sr['bed_declared_source_plan_file_sha256']==sd
 for ns in ['native','xmf']:
  assert sr[f'{ns}_source_plan_condition_field_present'] is False and sr[f'{ns}_source_plan_condition_sha256'] is None
  assert sr[f'{ns}_source_plan_physical_condition_field_present'] and sr[f'{ns}_source_plan_physical_condition_sha256']==canonical
 assert sr['xmf_source_plan_physical_condition_has_native_canonical_role'] and not sr['xmf_source_plan_physical_condition_has_SourceDef_role'] and sr['bed_declared_source_plan_field_has_SourceDef_role'] and sr['roles_are_distinct'] and not sr['scope_equality_claimed']
 expected={'fixed':158559,'moving':4210,'floating':0,'fluid_initial':31658,'total_initial':194427,'solver_dimension':3,'data2d':False}
 assert a['producer_counts']==expected and all(cl['counts_and_time'][k]==value for k,value in expected.items())
 assert cl['counts_and_time']['frames']==801 and cl['counts_and_time']['time_window_s']==qi['actual_time_window_s'] and cl['precision_negative_retained']==qi['actual_initial_QA_precision_negative']
 assert all(cl['historical_failures_retained'][k] for k in ['exact_lattice_or_numerical_precision_negative_retained','no_threshold_relaxation','original_A_and_B_geometric_negative_evidence_retained'])
 dec=s['decision'];assert dec['standalone_first_stage_visual_approved'] and not dec['severe_visual_failure'] and not dec['needs_root_image_intervention'] and dec['independent_case_count_increment']==0 and not dec['q_n_granted'] and not dec['q_e_granted']
 assert not dec['strict_container_guarantee'] and not dec['sub_dp_penetration_absence_claim'] and not dec['numerical_precision_accepted'] and not dec['large_runup_or_inundation_established'] and dec['weak_or_localized_response_limit']
 contacts=[{'path':e['absolute_path'],'sha256':e['sha256'],'bytes':e['bytes'],'sheet_index':e['index'],'viewed':e['reviewed']} for e in v['producer_attested_contact_sheets']]
 keys=[{'path':e['absolute_path'],'sha256':e['sha256'],'bytes':e['bytes'],'frame':e['frame_index'],'viewed':e['reviewed']} for e in v['producer_attested_keyframes']]
 reviewed=a['personal_review_scope']['reviewed_at_utc'];assert reviewed==s['reviewer']['reviewed_at_utc'];assert 'reviewed_at_utc' not in v['review_coverage'] or v['review_coverage']['reviewed_at_utc']==reviewed
 observations=v['personal_observation'];limits={'source_visual_limits':s['evidence_limits'],'source_physical_closure':cl,'source_scope_roles':sr};sourcevisualpath=prefix/'metadata/visual-decision.json'
else:
 s=load(P/'metadata/personal-visual-decision.json');c=s['case'];ev=s['evidence'];vr=s['visual_review'];dec=s['decision']
 assert c['case_id']==cid and c['physical_case_id']==pid and s['assigned_family']=='F6' and s['actual_family']=='F5'
 assert s['model']=='gpt-5.6-luna' and s['reasoning_effort']=='max' and not s['recursive_delegation']
 assert ev['main_qi_proof']['path']==str(qip);checked(ev['main_qi_proof'])
 for e in ev.values():checked(e)
 for k,e in er.items():
  x=ev['publish_receipt' if k=='render_publish_receipt' else k];assert x['path']==e['path'] and x['sha256']==e['sha256']
 assert c['canonical_native_physical_condition_sha256']==canonical and c['actual_converter_legacy_scope_sha256']==legacy and c['bed_xmf_source_definition_scope_sha256']==sd
 for ns in ['native','xmf']:assert c['source_plan_field_presence'][ns]==rawmask['native' if ns=='native' else 'XMF']
 assert c['declared_counts']==c['terminal_counts']==counts and c['actual_time_s']==qi['actual_time_window_s'] and c['dimension']==3 and c['expected_frames']==801
 assert dec['status']=='visual-approved-by-delegated-agent' and dec['case_credit']==0 and not dec['global_acceptance'] and not dec['q_n_granted'] and not dec['q_e_granted'] and not dec['production_approval']
 assert all(s['source_boundaries'][k] is False for k in ['science_payload_read','science_payload_hashed','science_jobs_started','shared_registry_or_ledger_written','historical_source_changed','model_substitution'])
 contacts=vr['contact_sheets'];keys=vr['key_frames'];reviewed=vr['reviewed_at_utc'];observations=dec['observations'];limits={'source_actual_case_and_limits':c,'source_decision_and_limits':dec,'source_boundaries':s['source_boundaries']};sourcevisualpath=prefix/'metadata/personal-visual-decision.json'
assert len(contacts)==34 and len(keys)==9 and [r['sheet_index'] for r in contacts]==list(range(34)) and [r['frame'] for r in keys]==list(range(0,801,100))
for k,e in er.items():
 checked(e)
 if k.endswith('_receipt') and k!='render_publish_receipt':
  rc=load(e['path']);assert rc['status']=='completed' and rc['returncode']==0 and rc['request']['case_id']==cid
pub=load(er['render_publish_receipt']['path']);render=load(er['render_report']['path']);receipt=load(er['render_receipt']['path']);assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
assert render['frames']==render['source_frames']==801 and render['all_frames_rendered'] and not render['diagnostic_only'] and render['nonfinite_active_states']==0
out=Path(pub['published_output_root']);pubfiles={r['relative_path']:r for r in pub['files_excluding_receipt']};assert [r['path'] for r in contacts]==render['outputs']['contact_sheets']
for e in contacts+keys:
 p=Path(e['path']);v=pubfiles[str(p.relative_to(out))];checked(e);assert e['sha256']==v['sha256'] and p.stat().st_size==e['bytes']==v['bytes'] and e['viewed']
reviewtime=datetime.datetime.fromisoformat(reviewed.replace('Z','+00:00'));finished=datetime.datetime.fromisoformat(receipt['finished_at_utc']);now=datetime.datetime.now(datetime.timezone.utc);assert finished<=reviewtime<=now
cpfile=H/f'ROOT_LIVE_RESUMPTION_CHECKPOINT_{oldcp}.json';cp=load(cpfile);assert cp['checkpoint']==oldcp and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==oldcount and cp['accepted_per_family']['F5']==oldF5
assert pid not in {load(p).get('physical_case_id',load(p)['case_id']) for p in cp['accepted_decisions']}
ip=root(oldindexroot)/f'full336-current{oldcount}-actual-final48-delivery-progress-index.json';index=load(ip);target=next(r for r in index['cases'] if r['physical_case_id']==pid);assert not target.get('accepted_decision') and target['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);attempts=collections.Counter(r['kind'] for r in ledger['attempts']);gpu=sum(r.get('gpu_seconds',0) for r in ledger['charges'])/3600;cpu=sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])/3600;vf=os.statvfs('/home/jade');free=vf.f_bavail*vf.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and attempts['qualification']<=1024 and attempts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/f'root_stage1_source{mode}_actualF5_{tag}_original{original}_full801QI_personal43PNG_exact_native_XMF_canonical_SourceDef_FILE_distinct_visual_acceptance_{outnum}';np=H/f'ROOT_LIVE_RESUMPTION_CHECKPOINT_{oldcp+1}.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
vp=O/f'source{mode}-byte-exact-readonly-validator-main43publishedPNG-own801QI-and-actual-review-time-proof.json'
put(vp,{'schema':'ds02.main.F5.personal43PNG-source-adoption-proof.v2','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'independent_own_QI':ref(qip),'all43_publishedPNG_hashes_match_actual_atomic_publish':True,'actual_personal_review_time_utc':reviewed,'review_after_completed_publication':True,'actual_native_XMF_plan_field_namespaces':rawmask,'native_XMF_physical_plans_have_canonical_role_and_bed_SourceDef_FILE_is_distinct':True,'source_legacy_alias_correction_needed':False,'all_case_count_and_scope_blocks_checked':True,'main_scientific_payload_IO':False})
dp=O/f'{pid}-delegated-visual-decision.json'
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':f'F{wn}','actual_review_family':'F5','source_personal_visual_review':ref(R/sourcevisualpath),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':counts,'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_source_plan_condition_field_present':False,'actual_native_source_plan_condition_field_value':None,'actual_native_source_plan_physical_condition_field_present':True,'actual_native_source_plan_physical_condition_field_value':canonical,'actual_XMF_source_plan_condition_field_present':False,'actual_XMF_source_plan_condition_field_value':None,'actual_XMF_source_plan_physical_condition_field_value':canonical,'actual_XMF_physical_plan_has_native_canonical_role':True,'actual_XMF_physical_plan_has_SourceDef_role':False,'actual_native_XMF_plan_field_namespaces':rawmask,'actual_bed_plan_field_value':sd,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_roles_are_distinct':True,'actual_native_plan_absence_not_filled_from_other_namespace':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'contact_sheets':contacts,'keyframes':keys,'visual_observations':observations,'visual_limits':limits,'no_strong_runup_or_inundation_magnitude_claim_from_visual_screen':True,'original_precision_negative':qi['actual_initial_QA_precision_negative'],'historical_negative_flags':qi['historical_negative_flags'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/f'source{mode}-actual{original}-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(vp),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1;new.update(checkpoint=oldcp+1,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=oldcount+1,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ledger['reservations'],attempt_counts=dict(attempts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification=f'PROGRESS: actual F5 {tag} original{original} ownQI{qinum} and delegated43PNG personal review adopted; actual native/XMF canonical physical-plan fields and distinct bed SourceDef FILE checked, historical negatives retained.',authorized_work_state=f'Active{oldcount+1}/336, {335-oldcount} pending. Next originalF3 987 and F5 1164 same registered render processes continue; ownQI1355/1359 only after actual completed0 and publication. Four families complete48; F2/F3/F5 final48 only after real acceptance48.')
new['actual_progress'][f'source{mode}_F5_actual{original}_visual_acceptance']=ref(ap);new['source_agents']['f5_bed_recovery' if wn==5 else 'f6_endpoint_initial_qa']=f'fresh{mode} actualF5 {tag} accepted; available for next original completed0/pub plus ownQI personal review'
new['next_executable_tasks']=['Adopt remaining source210/191 completed personal reviews once, preserving immutable source bytes and exact per-case namespace roles.','Observe originalF3 987 PID599335/start213680043 and F5 1164 PID604869/start213723590; once actual completed0/pub run durable ownQI1355/1359 once and then delegated personal review.','Audit source176 F3 completion-only delivery builder; do not issue final48 until actual48 accepted and complete primary references.','Continue original registered queues toward336 with Home500GiB floor and534.4086GiB cleanup evidence retained.']
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==oldcount+1;put(np,new)
index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=oldcount+1,registered_pending_independent_physical_cases=335-oldcount,new_case_credit=1)
target.update(status=f'visual-approved-in-checkpoint{oldcp+1}',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
index['actual_unaccepted_completed0_published_physical_cases']=[r for r in index['actual_unaccepted_completed0_published_physical_cases'] if (r if isinstance(r,str) else r['physical_case_id'])!=pid]
assert len(index['cases'])==336 and sum(bool(r.get('accepted_decision')) for r in index['cases'])==oldcount+1
put(O/f'full336-current{oldcount+1}-actual-final48-delivery-progress-index.json',index);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m',f'DS02: accept F5 {tag} full801 preserving actual canonical and SourceDef roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':oldcp+1,'accepted':oldcount+1,'F5':oldF5+1,'pending':335-oldcount,'new_decision':ref(dp),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
