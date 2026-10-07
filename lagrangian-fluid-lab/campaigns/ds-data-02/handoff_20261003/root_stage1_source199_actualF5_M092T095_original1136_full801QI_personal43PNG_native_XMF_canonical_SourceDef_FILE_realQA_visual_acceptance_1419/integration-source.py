from pathlib import Path
import json, hashlib, subprocess, copy, datetime, collections, os, re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md','.png'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def check(e):assert sha(e['path'])==e['sha256'],e['path']
def same(a,b):return a['path']==b['path'] and a['sha256']==b['sha256']
def parse(t):return datetime.datetime.fromisoformat(re.sub(r'(\.\d{6})\d+(?=Z|[+-])',r'\1',t).replace('Z','+00:00'))
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='87fa7cd9f99089393432b9299a4fd28445f0ef45';P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003').glob('root_followup_199_*'));prefix=P.relative_to(W)
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines()
expected={'README.md','package-manifest.json','metadata/visual-review.json','scripts/validate_fresh199.py'}
assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};man=load(P/'package-manifest.json');assert {e['path'] for e in man['files']}==expected-{'package-manifest.json'}
for e in man['files']:assert sha(P/e['path'])==e['sha256'] and (P/e['path']).stat().st_size==e['bytes']
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh199.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
qip=root(1412)/'actual1136-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';qi=load(qip);assert sha(qip)=='38166ff90e8e09af3619de83264a5cadd0e8789b7ec8554ee5664499c58d3643'
s=load(P/'metadata/visual-review.json');cid=qi['case_id'];pid=qi['physical_case_id'];v=s['personal_visual_review'];ps=s['producer_metadata_summary'];sr=s['physical_scope_roles']
assert cid==s['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34' and pid==s['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095'
assert s['assigned_family']=='F6' and s['physical_family']=='F5' and s['reviewer']=='/root/f6_endpoint_initial_qa'
assert v['status']=='visual-approved-by-delegated-agent' and v['case_credit']==0 and not v['q_n_granted'] and not v['q_e_granted']
assert not s['metadata_hash_policy']['png_hashed'] and not s['metadata_hash_policy']['scientific_payload_hashed']
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sdref=qi['actual_SourceDef'];sd=sdref['sha256'];check(sdref)
assert sr['canonical_native_condition_sha256']==canonical=='5adae02901dfdd5e70f7de3b62694c5f7f62f5d76ade14b0a8688ae9c2d0d273'
assert sr['typed_legacy_scope_sha256']==legacy=='04b4720db5456a4e01f5c5cbc3af67d2d1cedb15d784689ed7175c060a959fa8'
assert sr['source_definition_file_sha256']==sd=='6a56496593d43b8ca6f1910c3a934202c493db1a071e286f28c10488f38adeb9'
assert qi['binding_source_definition_field_present'] and qi['native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified']
assert qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked'] and qi['all_native_UIDs_active_each_frame']
er=qi['actual_completed_metadata_evidence'];chain={e['role']:e for e in s['producer_chain']};assert len(chain)==len(s['producer_chain'])
for e in chain.values():check(e)
assert same(chain['main_full801_QI_proof'],ref(qip)) and same(chain['registered_bed_SourceDef_XML'],sdref)
roles={'bed_receipt':'bed_execution_receipt','bed_report':'bed_event_footprint_report','gencase_receipt':'gencase_execution_receipt','generated_xml':'generated_case_xml','initial_qa_receipt':'initial_QA_execution_receipt','initial_qa_report':'initial_QA_report','native_receipt':'full_native_execution_receipt','typed_receipt':'typed_execution_receipt','typed_report':'typed_conversion_report','xmf_receipt':'XMF_execution_receipt','xmf_manifest':'XMF_manifest','xmf_xml':'XMF_case_xml','render_receipt':'render_execution_receipt','render_report':'render_report','render_publish_receipt':'render_publish_receipt'}
assert set(roles)==set(er)
for k,e in er.items():
 check(e);assert same(chain[roles[k]],e)
 if k.endswith('_receipt') and k!='render_publish_receipt':
  j=load(e['path']);assert j['schema']=='ds02.execution-receipt.v1' and j['status']=='completed' and j['returncode']==0 and j['request']['case_id']==cid
n=load(er['native_receipt']['path']);x=load(er['xmf_manifest']['path']);bedr=load(er['bed_receipt']['path']);binding=load(bedr['request']['binding'])
masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',n['request']),('XMF',x)]}
assert masks==qi['actual_native_XMF_plan_field_namespaces'] and sr['roles_are_distinct']
for ns,m in masks.items():
 assert m=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}}
 pre='native' if ns=='native' else 'xmf'
 assert sr[pre+'_source_plan_condition_field_present'] is False and sr[pre+'_source_plan_condition_sha256'] is None
 assert sr[pre+'_source_plan_physical_condition_field_present'] and sr[pre+'_source_plan_physical_condition_sha256']==canonical
plan=ref(binding['source_plan_file']);assert plan['sha256']==binding['source_plan_file_sha256']==sr['source_plan_file_sha256']
assert binding['source_definition']==sdref['path'] and binding['source_definition_sha256']==binding['source_plan_physical_condition_sha256']==sd
for j in [n,bedr]:assert j['input_hashes_at_launch'][plan['path']]==j['input_hashes_after_run'][plan['path']]==plan['sha256']
assert len({canonical,legacy,sd,plan['sha256']})==4
assert ps['full_frames']==801 and ps['particles']==194427 and ps['initial_fluid_particles']==31658 and ps['actual_time_window_s']==qi['actual_time_window_s']==[0.0,16.00014188025401]
assert ps['type_counts_per_frame']==ps['last_frame_type_counts']=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0}
assert ps['all_frames_rendered'] and ps['actual_times_preserved_exactly'] and ps['native_identity_axis_preserved'] and ps['nonfinite_active_states']==0
assert ps['initial_QA_precision_negative']==qi['actual_initial_QA_precision_negative'] and not ps['initial_QA_precision_negative']['pass_at_original_threshold']
contacts=v['contact_sheets'];keys=v['key_frames_viewed'];assert len(contacts)==34 and [e['index'] for e in contacts]==list(range(34)) and len(keys)==9 and [e['frame'] for e in keys]==list(range(0,801,100))
pub=load(er['render_publish_receipt']['path']);r=load(er['render_report']['path']);rc=load(er['render_receipt']['path']);out=Path(pub['published_output_root']);pubfiles={e['relative_path']:e for e in pub['files_excluding_receipt']}
assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['attempt_id']==rc['request']['attempt_id'] and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
assert r['frames']==r['source_frames']==801 and r['all_frames_rendered'] and r['manifest_sha256']==sha(er['xmf_manifest']['path'])
assert [e['path'] for e in contacts]==r['outputs']['contact_sheets']
assert [e['path'] for e in keys]==[str(out/f'frames/frame_{i:04d}.png') for i in range(0,801,100)]
assert len({e['path'] for e in contacts+keys})==43
joined_contacts=[];joined_keys=[]
for e,group in [(e,joined_contacts) for e in contacts]+[(e,joined_keys) for e in keys]:
 p=Path(e['path']);decl=pubfiles[str(p.relative_to(out))];dg=sha(p)
 assert e['personally_viewed_with_view_image'] and e['exists'] and 'sha256' not in e and e['bytes']==p.stat().st_size==decl['bytes'] and dg==decl['sha256']
 group.append({**e,'sha256':dg,'producer_sha256':decl['sha256'],'viewed':True,'view_method':'view_image','main_hash_matches_actual_publisher':True})
now=datetime.datetime.now(datetime.timezone.utc);reviewed=s['reviewed_at_utc'];assert parse(rc['finished_at_utc'])<=parse(reviewed)<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_311.json';cp=load(cpfile);assert cp['checkpoint']==311 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==325 and cp['accepted_per_family']['F5']==40
ip=root(1417)/'full336-current325-actual-final48-delivery-progress-index.json';idx=load(ip);assert same(idx['source_authoritative_checkpoint'],ref(cpfile));row=next(e for e in idx['cases'] if e['physical_case_id']==pid);assert not row.get('accepted_decision') and row['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<parse(cp['deadline_utc'])
O=H/'root_stage1_source199_actualF5_M092T095_original1136_full801QI_personal43PNG_native_XMF_canonical_SourceDef_FILE_realQA_visual_acceptance_1419';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_312.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh199.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/n).read_bytes()==b and (W/n).read_bytes()==b for n,b in blobs.items())
proof=O/'source199-byte-exact-readonly-validator-main43publishedPNG-own801QI-scope-and-review-time-proof.json'
put(proof,{'schema':'ds02.source199.main.actualF5.adoption.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'source_before_after_SHA':before,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'full801_own_QI':ref(qip),'all43_unique_publishedPNG_SHA_match_actual_atomic_publish':True,'source_only_stat_recorded_PNGs_main_adds_actual_publisher_SHA_join':True,'source_199_does_not_contain_explicit_configured_model_field':True,'known_assigned_reviewer_model_from_applicable_AGENTS_and_this_child_task':'gpt-5.6-luna/max','source_roles':sr,'actual_native_XMF_plan_namespaces':masks,'actual_personal_review_time_utc_original_string':reviewed,'UTC_parser_trimmed_only_extra_fraction_digits':True,'review_after_actual_publication':True,'main_scientific_payload_IO':False})
dp=O/(pid+'-delegated-visual-decision.json')
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':'F6','actual_review_family':'F5','source_personal_visual_review':ref(R/prefix/'metadata/visual-review.json'),'source_review_closure':ref(proof),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':ps['type_counts_per_frame'],'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_XMF_plan_field_namespaces':masks,'actual_bed_SourceDef_XML_FILE':sdref,'actual_source_plan_JSON_file':plan,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_planFILE_roles_are_distinct':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'personal_reviewed_at_utc':reviewed,'contact_sheets':joined_contacts,'keyframes':joined_keys,'visual_observations':v['observations'],'visual_limits':s['limitations'],'historical_negative_flags':qi['historical_negative_flags'],'original_precision_negative':qi['actual_initial_QA_precision_negative'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source199-actual1136-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(proof),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1
new.update(checkpoint=312,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=326,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: source186+187 actual1129 accepted325; source199 actual1136 own1412 and all43 personalPNG accepted326/F5=41 with published SHA joins added by main. Source221 actual1139 completed personal review awaits integration; original1159 and1176 running registered renders.',authorized_work_state='Active326/336 remaining10. F1/F4/F6/F7=48 F2=46 F3=47 F5=41. Original1139 immutable221 personal review completed and own1415 passed. Final tool audits bounded readiness only; manual actual percase delivery continues.')
new['actual_progress']['source199_F5_actual1136_visual_acceptance']=ref(ap);new['source_agents']['f6_endpoint_initial_qa']='fresh199 actual1136 accepted326; fresh200 actual1176 metadata preflight then personal review after ownQI';new['next_executable_tasks'].insert(0,'Integrate source221 original1139 with completed own1415 and genuine absent binding SourceDef/planJSON fields; prepare durable ownQI for current1159 and1176.')
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==326;put(np,new)
idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=326,registered_pending_independent_physical_cases=10,new_case_credit=1)
row.update(status='visual-approved-in-checkpoint312',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
idx['actual_unaccepted_completed0_published_physical_cases']=[e for e in idx['actual_unaccepted_completed0_published_physical_cases'] if (e if isinstance(e,str) else e['physical_case_id'])!=pid]
assert len(idx['cases'])==len({e['physical_case_id'] for e in idx['cases']})==336 and sum(bool(e.get('accepted_decision')) for e in idx['cases'])==326
put(O/'full336-current326-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: accept F5 M092T095 personal43PNG full801QI with distinct native legacy and source file roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':312,'accepted':326,'F5':41,'pending':10,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
