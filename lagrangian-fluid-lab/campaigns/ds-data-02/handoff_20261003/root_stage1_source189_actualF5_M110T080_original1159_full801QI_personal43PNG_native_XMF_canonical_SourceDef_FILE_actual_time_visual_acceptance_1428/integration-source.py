from pathlib import Path
import json,hashlib,subprocess,datetime,re,copy,collections,os
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf','.png'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def check(e):assert sha(e['path'])==e['sha256'],e['path']
def same(a,b):return a['path']==b['path'] and a['sha256']==b['sha256']
def parse(t):return datetime.datetime.fromisoformat(re.sub(r'(\.\d{6})\d+(?=Z|[+-])',r'\1',t).replace('Z','+00:00'))
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='4285171367a67586e860f9368e2b7a1455ca89fd'
P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003').glob('root_followup_189_*'));prefix=P.relative_to(W)
expected={'README.md','manifest.json','metadata/actual1159-personal-visual-decision.json','metadata/png-evidence/actual1159.json','scripts/validate_fresh189.py'}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
assert all((W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b) for n,b in blobs.items())
before={n:sha(W/n) for n in names};man=load(P/'manifest.json');assert set(man['files'])==expected and man['manifest_self_hash'] is None
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh189.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
qip=root(1421)/'actual1159-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';assert sha(qip)=='cfd70e7795e0cc3af9c2cae68775d9cc78e0ae7ed11cf900d0b8eaaa24757922';qi=load(qip)
s=load(P/'metadata/actual1159-personal-visual-decision.json');ev=load(P/'metadata/png-evidence/actual1159.json');v=s['personal_review'];sr=s['scope_roles'];er=qi['actual_completed_metadata_evidence']
cid=qi['case_id'];pid=qi['physical_case_id'];assert cid==s['case_id']==ev['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T080_NEXT34' and pid==s['physical_case_id']==ev['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T080'
assert s['assigned_worktree_family']=='F3' and s['actual_case_family']=='F5' and s['configured_model']=='gpt-5.6-luna/max' and not s['model_substitution']
assert s['visual_status']=='visual-approved-by-delegated-agent' and s['case_credit']==s['q_n']==s['q_e']==0
assert v['reviewer']=='production_recovery' and v['method']=='view_image' and v['all_required_published_pngs_viewed'] and not v['png_bytes_hashed_by_reviewer']
assert v['contact_sheets_viewed']==34 and v['key_frames_viewed']==9 and v['key_frame_indices']==list(range(0,801,100))
assert ev['all_paths_stat_checked'] and ev['all_required_images_personally_viewed'] and ev['reviewer_did_not_hash_pngs']
assert ev['review_completed_at_utc']==v['review_completed_at_utc']
assert not s['read_boundary']['scientific_payload_read_or_hashed'] and not s['read_boundary']['new_job_started'] and not s['read_boundary']['fresh188_modified']
for e in er.values():check(e)
for k,ek in [('render_receipt','render_receipt'),('render_report','render_report'),('publish_receipt','render_publish_receipt')]:assert same(s['actual_provenance'][k],er[ek])
assert same(s['actual_provenance']['qi_proof'],ref(qip))
assert ev['render_report']==er['render_report']['path'] and ev['render_publish_receipt']==er['render_publish_receipt']['path']
assert qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked'] and qi['all_native_UIDs_active_each_frame']
for k,e in er.items():
 if k.endswith('_receipt') and k!='render_publish_receipt':
  j=load(e['path']);assert j['schema']=='ds02.execution-receipt.v1' and (j['status'],j['returncode'])==('completed',0) and j['request']['case_id']==cid
n=load(er['native_receipt']['path']);x=load(er['xmf_manifest']['path']);t=load(er['typed_report']['path']);bedr=load(er['bed_receipt']['path']);binding=load(bedr['request']['binding'])
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sdref=qi['actual_SourceDef'];check(sdref);sd=sdref['sha256']
assert canonical==sr['native_canonical_physical_condition_sha256']==sr['xmf_physical_condition_sha256']==n['request']['physical_condition_sha256']==x['physical_condition_sha256']=='873b4e8ab9cc1fe351876d13063f1eb42fb722302f2f77b7684a6bd44ee1fbee'
assert legacy==sr['typed_legacy_owner_scope_sha256']==t['hash_scopes']['physical_condition_sha256']==x['source_h5_physical_condition_sha256']=='06e5dafcbb4dd8f471b6071dbff6a51e97111a2c13fe3108f5a5169ed5c8b034'
assert sd==sr['bed_source_definition_sha256']=='426b2eb0d07213735d4754efa99fb02c8a5d94a2bc66b4bfbb45767f1c933047'
assert t['output_sha256']==sr['source_h5_producer_attested_sha256']==x['source_h5_sha256']
assert qi['binding_source_definition_field_present'] and qi['native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified']
masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',n['request']),('XMF',x)]}
assert masks==qi['actual_native_XMF_plan_field_namespaces']
for m in masks.values():assert m=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}}
assert sr['xmf_source_plan_condition_present'] is False and sr['xmf_source_plan_physical_condition_sha256']==canonical and sr['roles_are_distinct']
plan=ref(binding['source_plan_file']);assert same(plan,qi['actual_source_plan_JSON_file']) and plan['sha256']==binding['source_plan_file_sha256']==sr['source_plan_file_sha256']
assert binding['source_definition']==sdref['path'] and binding['source_definition_sha256']==binding['source_plan_physical_condition_sha256']==sd
for j in [n,bedr]:assert j['input_hashes_at_launch'][plan['path']]==j['input_hashes_after_run'][plan['path']]==plan['sha256']
assert bedr['input_hashes_at_launch'][sdref['path']]==bedr['input_hashes_after_run'][sdref['path']]==sd
assert len({canonical,legacy,sd,plan['sha256']})==4
assert qi['actual_time_window_s']==[0.0,16.00010155849339] and qi['full_frames']==801 and qi['particles']==194427 and qi['fluid_initial_UIDs']==31658
assert s['runtime_identity']['time_window_s']==[0.0,16.0] # Original nominal declaration retained, not actual endpoint.
assert not qi['actual_initial_QA_precision_negative']['pass_at_original_threshold']
contacts=ev['contacts'];keys=ev['keys'];assert len(contacts)==34 and [e['role'] for e in contacts]==[f'contact_{i:02d}' for i in range(34)] and len(keys)==9
assert [e['role'] for e in keys]==[f'key_frame_{i}' for i in range(0,801,100)]
pub=load(er['render_publish_receipt']['path']);r=load(er['render_report']['path']);rc=load(er['render_receipt']['path']);out=Path(pub['published_output_root']);pubfiles={e['relative_path']:e for e in pub['files_excluding_receipt']}
assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['attempt_id']==rc['request']['attempt_id'] and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
assert r['frames']==r['source_frames']==801 and r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['manifest_sha256']==sha(er['xmf_manifest']['path'])
assert [e['path'] for e in contacts]==r['outputs']['contact_sheets'] and [e['path'] for e in keys]==[str(out/f'frames/frame_{i:04d}.png') for i in range(0,801,100)]
assert len({e['path'] for e in contacts+keys})==43
joined_contacts=[];joined_keys=[]
for e,group in [(e,joined_contacts) for e in contacts]+[(e,joined_keys) for e in keys]:
 p=Path(e['path']);rel=str(p.relative_to(out));decl=pubfiles[rel];dg=sha(p)
 assert e['relative_path']==rel and e['personally_viewed_with_view_image'] and e['stat_checked'] and not e['reviewer_hashed_or_read_bytes_directly'] and e['bytes']==p.stat().st_size==decl['bytes'] and dg==e['producer_declared_sha256']==decl['sha256']
 joined={**e,'sha256':dg,'viewed':True,'view_method':'view_image','main_hash_matches_actual_publisher':True}
 if group is joined_keys:joined['frame']=int(p.stem.split('_')[1])
 group.append(joined)
now=datetime.datetime.now(datetime.timezone.utc);reviewed=v['review_completed_at_utc'];assert parse(rc['finished_at_utc'])<=parse(reviewed)<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_316.json';cp=load(cpfile);assert cp['checkpoint']==316 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==327 and cp['accepted_per_family']['F5']==42
ip=root(1426)/'full336-current327-actual-final48-delivery-progress-index.json';idx=load(ip);assert same(idx['source_authoritative_checkpoint'],ref(cpfile));row=next(e for e in idx['cases'] if e['physical_case_id']==pid);assert not row.get('accepted_decision') and row['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<parse(cp['deadline_utc'])
O=H/'root_stage1_source189_actualF5_M110T080_original1159_full801QI_personal43PNG_native_XMF_canonical_SourceDef_FILE_actual_time_visual_acceptance_1428';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_317.json';assert not O.exists() and not np.exists();O.mkdir()
for name,b in blobs.items():p=R/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh189.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/name).read_bytes()==b and (W/name).read_bytes()==b for name,b in blobs.items())
proof=O/'source189-byte-exact-readonly-validator-main43publishedPNG-own801QI-and-actual-time-proof.json'
put(proof,{'schema':'ds02.source189.main.actualF5.adoption.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/name) for name in names],'source_before_after_SHA':before,'source_manifest_self_hash_explicit_null':True,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'full801_own_QI':ref(qip),'all43_unique_publishedPNG_SHA_match_actual_atomic_publish':True,'configured_model':s['configured_model'],'source_roles':sr,'actual_native_XMF_plan_namespaces':masks,'actual_personal_review_time_utc_original_string':reviewed,'UTC_parser_trimmed_only_extra_fraction_digits':True,'review_after_actual_publication':True,'original_runtime_identity_time_window_s_retained':[0.0,16.0],'original_window_is_nominal_not_exact_native_terminal':True,'actual_native_time_window_s':qi['actual_time_window_s'],'main_scientific_payload_IO':False})
dp=O/(pid+'-delegated-visual-decision.json')
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':'F3','actual_review_family':'F5','source_personal_visual_review':ref(R/prefix/'metadata/actual1159-personal-visual-decision.json'),'source_review_closure':ref(proof),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':{'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0},'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_XMF_plan_field_namespaces':masks,'actual_bed_SourceDef_XML_FILE':sdref,'actual_source_plan_JSON_file':plan,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_planFILE_roles_are_distinct':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'personal_reviewed_at_utc':reviewed,'contact_sheets':joined_contacts,'keyframes':joined_keys,'visual_observations':v['observations'],'visual_limits':s['retained_limits'],'historical_negative_flags':qi['historical_negative_flags'],'original_precision_negative':qi['actual_initial_QA_precision_negative'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source189-actual1159-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(proof),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1
new.update(checkpoint=317,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=328,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: user cleanup reverified, fresh189 actual1159 personally reviewed43PNG/full801 own1421 accepted328; actual1176 and1119 naturally completed0/published and own1423/1425 passed; fresh201/223 now personally reviewing.',authorized_work_state='Active328/336 remaining8. F1/F4/F6/F7=48 F2=46 F3=47 F5=43. Original1176 and1119 completed0/published/fullQI; personal201/223 pending. Final actual percase primary deliveries remain required.')
new['actual_progress']['source189_F5_actual1159_visual_acceptance']=ref(ap)
new['source_agents'].update(production_recovery='fresh189 actual1159 accepted328; next final primary metadata task available',f6_endpoint_initial_qa='fresh201 original1176 personal34+9 after actual0/pub and own1423',f5_bed_recovery='fresh223 original1119 personal17+9 after actual0/pub and own1425')
new['next_executable_tasks'].insert(0,'Integrate fresh201 original1176 and fresh223 original1119 once actual personal PNG evidence is complete; continue registered original1101 and final48 actual primary case bindings.')
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==328
for original,qin,filename in [(1176,1423,'actual1176-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json'),(1119,1425,'actual1119-full401-own-QI-UID-N3-native-typed-role-one-fluid-omission-previsual-proof.json')]:
 qp=root(qin)/filename;j=load(qp);rr=next(e for e in idx['cases'] if e['physical_case_id']==j['physical_case_id']);assert not rr.get('accepted_decision');rr.update(actual_completed0_published_QI=ref(qp),personal_visual_status='pending delegated review after own completed QI',case_credit_already_in_authoritative_checkpoint=0)
 new['actual_progress'][f'original{original}_completed0_published_ownQI']=ref(qp)
put(np,new)
idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=328,registered_pending_independent_physical_cases=8,new_case_credit=1)
row.update(status='visual-approved-in-checkpoint317',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
idx['actual_unaccepted_completed0_published_physical_cases']=[load(root(n)/f)['physical_case_id'] for n,f in [(1423,'actual1176-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json'),(1425,'actual1119-full401-own-QI-UID-N3-native-typed-role-one-fluid-omission-previsual-proof.json')]]
assert len(idx['cases'])==len({e['physical_case_id'] for e in idx['cases']})==336 and sum(bool(e.get('accepted_decision')) for e in idx['cases'])==328
put(O/'full336-current328-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: accept F5 M110T080 personal43PNG full801QI and record next two completed render integrity proofs','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':317,'accepted':328,'F5':43,'pending':8,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
