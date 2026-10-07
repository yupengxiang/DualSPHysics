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
commit='3bd5156df0997a08d4ef3f048d502124bf151e71';P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003').glob('root_followup_201_*'));prefix=P.relative_to(W)
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines()
expected={'README.md','package-manifest.json','metadata/visual-review.json','scripts/validate_fresh201.py'}
assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};man=load(P/'package-manifest.json');assert {e['path'] for e in man['files']}==expected-{'package-manifest.json'}
for e in man['files']:assert sha(P/e['path'])==e['sha256'] and (P/e['path']).stat().st_size==e['bytes']
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh201.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
qip=root(1423)/'actual1176-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';qi=load(qip);assert sha(qip)=='2ebb39a807f2da63f3c8e8c0e0c7330b3bacfedf781aae9d970f15e2d884349c'
s=load(P/'metadata/visual-review.json');cid=qi['case_id'];pid=qi['physical_case_id'];rawv=s['visual_review'];roles0=s['scope_roles'];contract=s['actual_render_contract']
assert s['model']=='gpt-5.6-luna/max' and rawv['personally_viewed_with_view_image'] and not s['scientific_payload_policy']['payloads_read'] and not s['scientific_payload_policy']['payloads_hashed'] and not s['producer_png_policy']['png_hashes_independently_computed']
v={'status':rawv['status'],'case_credit':rawv['case_credit'],'q_n_granted':rawv['q_n'],'q_e_granted':rawv['q_e'],'contact_sheets':rawv['contact_sheets'],'key_frames_viewed':[{**e,'frame':e['frame_index']} for e in rawv['key_frames']],'observations':rawv['observations']}
assert contract['counts']=={'fixed_particles':158559,'moving_particles':4210,'floating_particles':0,'fluid_particles':31658,'total_particles':194427,'solver_dimension':3}
render0=load(s['actual_terminal_evidence']['render_report']['path'])
ps={'full_frames':contract['frames'],'particles':contract['particles'],'initial_fluid_particles':contract['counts']['fluid_particles'],'actual_time_window_s':contract['actual_time_window_s'],'type_counts_per_frame':{'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0},'last_frame_type_counts':{'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0},'all_frames_rendered':render0['all_frames_rendered'],'actual_times_preserved_exactly':render0['actual_times_preserved_exactly'],'native_identity_axis_preserved':render0['native_identity_axis_preserved'],'nonfinite_active_states':render0['nonfinite_active_states'],'initial_QA_precision_negative':s['limitations']['initial_QA_precision_negative']}
sr={'canonical_native_condition_sha256':roles0['canonical_native_condition_sha256'],'typed_legacy_scope_sha256':roles0['typed_legacy_scope_sha256'],'source_definition_file_sha256':roles0['bed_SourceDef_sha256'],'source_plan_file_sha256':roles0['source_plan_JSON_sha256'],'roles_are_distinct':roles0['roles_are_separate']}
for ns,prefix0 in [('native','native'),('XMF','xmf')]:
 for field0,short0 in [('source_plan_condition_sha256','source_plan_condition'),('source_plan_physical_condition_sha256','source_plan_physical_condition')]:
  sr[prefix0+'_'+short0+'_field_present']=roles0[ns][field0]['present'];sr[prefix0+'_'+short0+'_sha256']=roles0[ns][field0]['value']
for e in s['metadata_refs']:check(e);assert Path(e['path']).stat().st_size==e['bytes']
for k,role0 in [('execution_receipt','render_receipt'),('render_report','render_report'),('publish_receipt','render_publish_receipt')]:assert same(s['actual_terminal_evidence'][k],qi['actual_completed_metadata_evidence'][role0])

assert cid==s['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M104_T095_NEXT34' and pid==s['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T095'
assert s['assigned_family']=='F6' and s['physical_family']=='F5' and s['reviewer']=='/root/f6_endpoint_initial_qa'
assert v['status']=='visual-approved-by-delegated-agent' and v['case_credit']==0 and not v['q_n_granted'] and not v['q_e_granted']
assert not s['producer_png_policy']['png_hashes_independently_computed'] and not s['scientific_payload_policy']['payloads_hashed']
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sdref=qi['actual_SourceDef'];sd=sdref['sha256'];check(sdref)
assert sr['canonical_native_condition_sha256']==canonical=='83831d4fc2150e22f79c5bc6d4a6e655c2ab6c43b517288c531b490ed3563877'
assert sr['typed_legacy_scope_sha256']==legacy=='c7a06c6bdcbf126b3758317aabda1815621e3b2368d9ad546c14ef95d4e0aae1'
assert sr['source_definition_file_sha256']==sd=='c4e0a0ad9924c53eba206011b0bac762a8babc706fc1bf101e1ca2e1f6450965'
assert qi['binding_source_definition_field_present'] and qi['native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified']
assert qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked'] and qi['all_native_UIDs_active_each_frame']
er=qi['actual_completed_metadata_evidence'];chain={e['role']:e for e in s['metadata_refs']};assert len(chain)==len(s['metadata_refs'])
for e in chain.values():check(e)
assert same(chain['main_full801_qi_proof'],ref(qip)) and same(chain['bed_SourceDef_xml'],sdref)
roles={k:k for k in er}
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
assert ps['full_frames']==801 and ps['particles']==194427 and ps['initial_fluid_particles']==31658 and ps['actual_time_window_s']==qi['actual_time_window_s']==[0.0,16.00012550006781]
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
 assert e['personally_viewed_with_view_image'] and 'sha256' not in e and e['bytes']==e['producer_bytes']==p.stat().st_size==decl['bytes'] and dg==e['producer_sha256']==decl['sha256']
 group.append({**e,'sha256':dg,'producer_sha256':decl['sha256'],'viewed':True,'view_method':'view_image','main_hash_matches_actual_publisher':True})
now=datetime.datetime.now(datetime.timezone.utc);reviewed=s['review_completed_utc'];assert parse(rc['finished_at_utc'])<=parse(reviewed)<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_318.json';cp=load(cpfile);assert cp['checkpoint']==318 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==328 and cp['accepted_per_family']['F5']==43
ip=root(1429)/'full336-current328-actual-final48-delivery-progress-index.json';idx=load(ip);assert same(idx['source_authoritative_checkpoint'],ref(cpfile));row=next(e for e in idx['cases'] if e['physical_case_id']==pid);assert not row.get('accepted_decision') and row['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<parse(cp['deadline_utc'])
O=H/'root_stage1_source201_actualF5_M104T095_original1176_full801QI_personal43PNG_native_XMF_canonical_SourceDef_FILE_realQA_visual_acceptance_1431';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_319.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh201.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/n).read_bytes()==b and (W/n).read_bytes()==b for n,b in blobs.items())
proof=O/'source201-byte-exact-readonly-validator-main43publishedPNG-own801QI-scope-and-review-time-proof.json'
put(proof,{'schema':'ds02.source201.main.actualF5.adoption.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'source_before_after_SHA':before,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'full801_own_QI':ref(qip),'all43_unique_publishedPNG_SHA_match_actual_atomic_publish':True,'source_only_stat_recorded_PNGs_main_adds_actual_publisher_SHA_join':True,'source_explicit_model':s['model'],'normalized_source_projection_is_main_only_original_bytes_unchanged':True,'known_assigned_reviewer_model_from_applicable_AGENTS_and_this_child_task':'gpt-5.6-luna/max','source_roles':sr,'actual_native_XMF_plan_namespaces':masks,'actual_personal_review_time_utc_original_string':reviewed,'UTC_parser_trimmed_only_extra_fraction_digits':True,'review_after_actual_publication':True,'main_scientific_payload_IO':False})
dp=O/(pid+'-delegated-visual-decision.json')
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':'F6','actual_review_family':'F5','source_personal_visual_review':ref(R/prefix/'metadata/visual-review.json'),'source_review_closure':ref(proof),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':ps['type_counts_per_frame'],'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_XMF_plan_field_namespaces':masks,'actual_bed_SourceDef_XML_FILE':sdref,'actual_source_plan_JSON_file':plan,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_planFILE_roles_are_distinct':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'personal_reviewed_at_utc':reviewed,'contact_sheets':joined_contacts,'keyframes':joined_keys,'visual_observations':v['observations'],'visual_limits':s['limitations'],'historical_negative_flags':qi['historical_negative_flags'],'original_precision_negative':qi['actual_initial_QA_precision_negative'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source201-actual1176-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(proof),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1
new.update(checkpoint=319,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=329,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: source189 actual1159 accepted328; actual1176 own1423 and source201 all43 personalPNG now accepted329/F5=44. Source223 actual1119 personal review pending; actual1063/1189 render workers verified live.',authorized_work_state='Active329/336 remaining7. F1/F4/F6/F7=48 F2=46 F3=47 F5=44. Final family/global actual primary delivery remains required.')
new['actual_progress']['source201_F5_actual1176_visual_acceptance']=ref(ap);new['source_agents']['f6_endpoint_initial_qa']='fresh201 actual1176 accepted329; next F5 actual1189 metadata preflight available';new['next_executable_tasks'].insert(0,'Integrate source223 original1119 after personal17+9; continue source190 F3 actual47 primary and current registered1063/1189 render completions.')
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==329;put(np,new)
idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=329,registered_pending_independent_physical_cases=7,new_case_credit=1)
row.update(status='visual-approved-in-checkpoint319',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
idx['actual_unaccepted_completed0_published_physical_cases']=[e for e in idx['actual_unaccepted_completed0_published_physical_cases'] if (e if isinstance(e,str) else e['physical_case_id'])!=pid]
assert len(idx['cases'])==len({e['physical_case_id'] for e in idx['cases']})==336 and sum(bool(e.get('accepted_decision')) for e in idx['cases'])==329
put(O/'full336-current329-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: accept F5 M104T095 personal43PNG full801QI actual time and distinct source file roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':319,'accepted':329,'F5':44,'pending':7,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
