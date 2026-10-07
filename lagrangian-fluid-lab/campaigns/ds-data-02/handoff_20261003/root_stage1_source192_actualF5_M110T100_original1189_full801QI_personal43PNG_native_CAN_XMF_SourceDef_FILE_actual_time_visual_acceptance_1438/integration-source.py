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
commit='7308de5ae5a6778b0417004636e13bcfe8fdd4f6'
P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003').glob('root_followup_192_*'));prefix=P.relative_to(W)
expected={'README.md','manifest.json','metadata/actual1189-personal-visual-decision.json','metadata/png-evidence/actual1189.json','scripts/validate_fresh192.py','scripts/build_fresh192.py'}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
assert all((W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b) for n,b in blobs.items())
before={n:sha(W/n) for n in names};man=load(P/'manifest.json');assert {e['path'] for e in man['files']}==expected and man['manifest_self_hash']=='omitted_by_design'
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh192.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
preflight=load(P/'metadata/actual1189-personal-visual-decision.json')['actual_provenance'];pf=Path(preflight['fresh191_preflight']);assert sha(pf)==preflight['fresh191_preflight_sha256'];assert pf.read_bytes()==subprocess.check_output(['git','show',f"{preflight['fresh191_preflight_commit']}:{pf.relative_to(W)}"],cwd=W)
qip=root(1434)/'actual1189-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json';assert sha(qip)=='1842851ab604f787bfba37e8b55e68463a8e1a81d94779c05412f0da1cca2652';qi=load(qip)
s=load(P/'metadata/actual1189-personal-visual-decision.json');ev=load(P/'metadata/png-evidence/actual1189.json');v=s['personal_review'];sr=s['scope_roles'];er=qi['actual_completed_metadata_evidence']
cid=qi['case_id'];pid=qi['physical_case_id'];assert cid==s['case_id']==ev['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M110_T100_NEXT34' and pid==s['physical_case_id']==ev['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100'
assert s['assigned_worktree_family']=='F3' and s['actual_case_family']=='F5' and s['configured_model']=='gpt-5.6-luna/max' and not s['model_substitution']
assert s['visual_status']=='visual-approved-by-delegated-agent' and s['case_credit']==s['q_n']==s['q_e']==0
assert v['reviewer']=='production_recovery' and v['method']=='view_image' and v['all_required_published_pngs_viewed'] and not v['png_bytes_hashed_by_reviewer']
assert v['contact_sheets_viewed']==34 and v['key_frames_viewed']==9 and v['key_frame_indices']==list(range(0,801,100))
assert ev['review_boundary']['published_pngs_opened'] and not ev['review_boundary']['png_bytes_hashed_by_reviewer'] and not ev['review_boundary']['scientific_payload_read_or_hashed']
assert ev['review_completed_at_utc']==v['review_completed_at_utc']
assert not s['read_boundary']['scientific_payload_read_or_hashed'] and not s['read_boundary']['new_job_started'] and not s['read_boundary']['fresh191_modified']
for e in er.values():check(e)
for k,ek in [('render_receipt','render_receipt'),('render_report','render_report'),('publish_receipt','render_publish_receipt')]:assert same(s['actual_provenance'][k],er[ek])
assert same(s['actual_provenance']['qi_proof'],ref(qip))
assert same(ev['render_report'],er['render_report']) and same(ev['publish_receipt'],er['render_publish_receipt'])
assert qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked'] and qi['all_native_UIDs_active_each_frame']
for k,e in er.items():
 if k.endswith('_receipt') and k!='render_publish_receipt':
  j=load(e['path']);assert j['schema']=='ds02.execution-receipt.v1' and (j['status'],j['returncode'])==('completed',0) and j['request']['case_id']==cid
n=load(er['native_receipt']['path']);x=load(er['xmf_manifest']['path']);t=load(er['typed_report']['path']);bedr=load(er['bed_receipt']['path']);binding=load(bedr['request']['binding'])
canonical=qi['canonical_actual_native_request_condition_sha256'];legacy=qi['actual_converter_legacy_scope_sha256'];sdref=qi['actual_SourceDef'];check(sdref);sd=sdref['sha256']
assert canonical==sr['native_canonical_physical_condition_sha256']==sr['xmf_physical_condition_sha256']==n['request']['physical_condition_sha256']==x['physical_condition_sha256']=='83d6ff1798c49ce500aaf07d2319fac66f48d496d73fa1c044582fd9ec2b9024'
assert legacy==sr['typed_legacy_owner_scope_sha256']==t['hash_scopes']['physical_condition_sha256']==x['source_h5_physical_condition_sha256']=='7b383a4e371948c22f8702cd9704844d1b16d8835fa12f203b688892fbc9f2a2'
assert sd==sr['bed_source_definition_sha256']=='da761772174d2a4ba20736647649b2e1117e48c55924426a3e24194057d366a7'
assert t['output_sha256']==x['source_h5_sha256']
assert qi['binding_source_definition_field_present'] and qi['native_canonical_plan_and_XMF_SourceDef_plan_roles_and_separate_XML_FILE_independently_verified']
masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',n['request']),('XMF',x)]}
assert masks==qi['actual_native_XMF_plan_field_namespaces']
assert masks['native']=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':canonical}}
assert masks['XMF']=={'source_plan_condition_sha256':{'present':False,'value':None},'source_plan_physical_condition_sha256':{'present':True,'value':sd}}
assert sr['xmf_source_plan_condition_present'] is False and sr['xmf_source_plan_physical_condition_sha256']==sd and sr['roles_are_distinct']
plan=ref(binding['source_plan_file']);assert same(plan,qi['actual_source_plan_JSON_file']) and plan['sha256']==binding['source_plan_file_sha256']==sr['source_plan_file_sha256']
assert binding['source_definition']==sdref['path'] and binding['source_definition_sha256']==binding['source_plan_physical_condition_sha256']==sd
for j in [n,bedr]:assert j['input_hashes_at_launch'][plan['path']]==j['input_hashes_after_run'][plan['path']]==plan['sha256']
assert bedr['input_hashes_at_launch'][sdref['path']]==bedr['input_hashes_after_run'][sdref['path']]==sd
assert len({canonical,legacy,sd,plan['sha256']})==4
assert qi['actual_time_window_s']==[0.0,16.00008511666941] and qi['full_frames']==801 and qi['particles']==194427 and qi['fluid_initial_UIDs']==31658
assert s['runtime_identity']['actual_time_window_s']==qi['actual_time_window_s']
assert not qi['actual_initial_QA_precision_negative']['pass_at_original_threshold']
contacts=ev['contact_sheets'];keys=ev['key_frames'];assert len(contacts)==34 and all(e['role']=='contact_sheet' for e in contacts) and len(keys)==9
assert all(e['role']=='key_frame' for e in keys)
pub=load(er['render_publish_receipt']['path']);r=load(er['render_report']['path']);rc=load(er['render_receipt']['path']);out=Path(pub['published_output_root']);pubfiles={e['relative_path']:e for e in pub['files_excluding_receipt']}
assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['attempt_id']==rc['request']['attempt_id'] and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
assert r['frames']==r['source_frames']==801 and r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['manifest_sha256']==sha(er['xmf_manifest']['path'])
assert [e['path'] for e in contacts]==r['outputs']['contact_sheets'] and [e['path'] for e in keys]==[str(out/f'frames/frame_{i:04d}.png') for i in range(0,801,100)]
assert len({e['path'] for e in contacts+keys})==43
joined_contacts=[];joined_keys=[]
for e,group in [(e,joined_contacts) for e in contacts]+[(e,joined_keys) for e in keys]:
 p=Path(e['path']);rel=str(p.relative_to(out));decl=pubfiles[rel];dg=sha(p)
 assert e['relative_path']==rel and e['personally_viewed_with_view_image'] and not e['content_read_or_hashed_by_reviewer'] and e['bytes_stat']==p.stat().st_size==decl['bytes'] and dg==e['producer_declared_sha256']==decl['sha256']
 joined={**e,'sha256':dg,'viewed':True,'view_method':'view_image','main_hash_matches_actual_publisher':True}
 if group is joined_keys:joined['frame']=int(p.stem.split('_')[1])
 group.append(joined)
now=datetime.datetime.now(datetime.timezone.utc);reviewed=v['review_completed_at_utc'];assert parse(rc['finished_at_utc'])<=parse(reviewed)<=now
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_324.json';cp=load(cpfile);assert cp['checkpoint']==324 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==331 and cp['accepted_per_family']['F5']==44
ip=root(1437)/'full336-current331-actual-final48-delivery-progress-index.json';idx=load(ip);assert same(idx['source_authoritative_checkpoint'],ref(cpfile));row=next(e for e in idx['cases'] if e['physical_case_id']==pid);assert not row.get('accepted_decision') and row['native_request_scope']['sha256']==canonical
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(a['kind'] for a in ld['attempts']);gpu=sum(a.get('gpu_seconds',0) for a in ld['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<parse(cp['deadline_utc'])
O=H/'root_stage1_source192_actualF5_M110T100_original1189_full801QI_personal43PNG_native_CAN_XMF_SourceDef_FILE_actual_time_visual_acceptance_1438';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_325.json';assert not O.exists() and not np.exists();O.mkdir()
for name,b in blobs.items():p=R/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh192.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/name).read_bytes()==b and (W/name).read_bytes()==b for name,b in blobs.items())
proof=O/'source192-byte-exact-readonly-validator-main43publishedPNG-own801QI-and-actual-time-proof.json'
put(proof,{'schema':'ds02.source192.main.actualF5.adoption.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/name) for name in names],'source_before_after_SHA':before,'source_manifest_self_hash_excluded_by_design':True,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'full801_own_QI':ref(qip),'all43_unique_publishedPNG_SHA_match_actual_atomic_publish':True,'configured_model':s['configured_model'],'source_roles':sr,'actual_native_XMF_plan_namespaces':masks,'actual_personal_review_time_utc_original_string':reviewed,'UTC_parser_trimmed_only_extra_fraction_digits':True,'review_after_actual_publication':True,'source_runtime_identity_actual_time_window_s':qi['actual_time_window_s'],'prospective_original_wrapper_scope_preserved_separately':sr['prospective_canonical_preserved_separately'],'actual_native_time_window_s':qi['actual_time_window_s'],'main_scientific_payload_IO':False})
dp=O/(pid+'-delegated-visual-decision.json')
put(dp,{'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':now.isoformat(),'status':'visual-approved-by-delegated-agent','family_id':'F5','case_id':cid,'physical_case_id':pid,'physical_condition_sha256':canonical,'actual_converter_scope_sha256':legacy,'bed_SourceDef_scope_sha256':sd,'source_review_commit':commit,'source_review_assigned_family':'F3','actual_review_family':'F5','source_personal_visual_review':ref(R/prefix/'metadata/actual1189-personal-visual-decision.json'),'source_review_closure':ref(proof),'independent_full801_QI':ref(qip),'actual_completed_metadata_evidence':er,'full_native_frames':801,'particle_count':194427,'initial_fluid_particles':31658,'actual_type_counts':{'fixed':158559,'moving':4210,'floating':0,'fluid':31658,'unknown':0},'actual_physical_window_s':qi['actual_time_window_s'],'all801_UID_N3_actual_times_finite_states_verified':True,'all_native_UIDs_active_each_frame':True,'all801_bed_footprint_oneDP_twoDP_diagnostic_counts_zero_verified':True,'bed_bins_are_diagnostics_not_precision_thresholds':True,'strict_container_guarantee':False,'subDP_positive_depth_not_quantified':True,'actual_native_XMF_plan_field_namespaces':masks,'actual_bed_SourceDef_XML_FILE':sdref,'actual_source_plan_JSON_file':plan,'binding_source_definition_field_present':True,'canonical_legacy_SourceDef_planFILE_roles_are_distinct':True,'agent_personally_viewed_all_contacts_and_keys':True,'personal_reviewed_contacts':34,'personal_reviewed_keyframes':9,'personal_reviewed_at_utc':reviewed,'contact_sheets':joined_contacts,'keyframes':joined_keys,'visual_observations':v['observations'],'visual_limits':s['retained_limits'],'historical_negative_flags':qi['historical_negative_flags'],'original_precision_negative':qi['actual_initial_QA_precision_negative'],'main_all43_PNG_hashes_match_actual_atomic_publish':True,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
ap=O/'source192-actual1189-full801QI-personal-visual-adoption.json';put(ap,{'source_validation':ref(proof),'independent_QI':ref(qip),'new_visual_decision':ref(dp),'case_credit':1,'main_scientific_payload_IO':False});snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new['accepted_per_family']['F5']+=1
new.update(checkpoint=325,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),stage1_visual_accepted_complete_independent_cases=332,new_accepted_decisions=[str(dp)],accepted_decisions=cp['accepted_decisions']+[str(dp)],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: F2final48 accepted331, F5actual44 full801 primary delivered; fresh192 actual1189 personally reviewed43PNG and own1434 accepted332, native CAN/XMFSourceDef roles preserved.',authorized_work_state='Active332/336 remaining4. F1/F2/F4/F6/F7=48 F3=47 F5=45. Registered1184/1175 running,1101/1149 queued at11:19 snapshot. Final percase primary joins remain required.')
new['actual_progress']['source192_F5_actual1189_visual_acceptance']=ref(ap)
new['source_agents']['production_recovery']='fresh192 actual1189 accepted332; F5 actual45 primary extension next'
new['next_executable_tasks'].insert(0,'Extend actual F5 primary44 to45 including1189; integrate F2fresh226 final48; registered1184/1175/1101/1149 need natural completion and review.')
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==332
put(np,new)
idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),accepted_independent_physical_cases=332,registered_pending_independent_physical_cases=4,new_case_credit=1)
row.update(status='visual-approved-in-checkpoint325',accepted_decision=ref(dp),case_credit_already_in_authoritative_checkpoint=1,precision_status='视觉检查通过、数值精度未验收',actual_full801_QI=ref(qip))
idx['actual_unaccepted_completed0_published_physical_cases']=[e for e in idx['actual_unaccepted_completed0_published_physical_cases'] if (e if isinstance(e,str) else e['physical_case_id'])!=pid]
assert len(idx['cases'])==len({e['physical_case_id'] for e in idx['cases']})==336 and sum(bool(e.get('accepted_decision')) for e in idx['cases'])==332
put(O/'full336-current332-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: accept F5 M110T100 personal43PNG preserving nativeCAN and XMFSourceDef scope roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':325,'accepted':332,'F5':45,'pending':4,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
