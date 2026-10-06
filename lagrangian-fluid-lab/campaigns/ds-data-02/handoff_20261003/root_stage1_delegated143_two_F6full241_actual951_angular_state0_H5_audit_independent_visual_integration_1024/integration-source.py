from pathlib import Path
import json,hashlib,subprocess,datetime,xml.etree.ElementTree as ET,shutil,runpy
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.txt','.log','.xml','.xmf','.png'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_143_f6_dyzx_delegated_visual_acceptance_v1';commit='23fa6769a594042e8f64dc65e9ebab789fe16ea9'
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==8
adopted=[]
for name in names:
    assert Path(name).suffix in {'.json','.py','.md'}
    raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes()
    p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_delegated143_two_F6full241_actual951_angular_state0_H5_audit_independent_visual_integration_1024';O.mkdir(exist_ok=True);assert not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_150.json').exists();assert not list(O.glob('*-delegated-visual-decision.json'))
validator=P/'workers/validate_fresh143.py'; report=P/'metadata/validator-result.json'; original=ref(report); namespace=runpy.run_path(str(validator)); original_write=Path.write_text; writes=[]
def redirect(self,data,*args,**kwargs):
 assert self==report;writes.append(str(self));return original_write(O/'independent-source143-validator-output.json',data,*args,**kwargs)
try:
 Path.write_text=redirect; namespace['main']()
finally:Path.write_text=original_write
assert writes==[str(report)] and ref(report)==original
put(O/'actual-source143-validator.json',{'status':'PASS','validator':ref(validator),'original_source_report_preserved':original,'only_report_write_redirected':ref(O/'independent-source143-validator-output.json'),'scientific_payload_IO':False})
rawc=load(P/'metadata/chain-closure.json'); v=load(P/'metadata/visual-review.json');assert not v['global_credit_updated_by_agent'] and not v['scientific_payload_read_or_hashed'];normalized={};reviews0={a['case_id']:a for a in v['cases']}
for row in rawc['cases']:
 cid=row['case_id']; a=row['producer_chain']; vr=reviews0[cid]; t=load(a['typed_conversion']['conversion_report']['path']);x=load(a['xmf']['manifest']['path']); nr=load(a['full_native']['execution_receipt']['path']); n=vr['physical_metadata']['counts'];sc0=row['scope_separation']
 sc={'source_canonical_or_basic_qa_scope_sha256':sc0['canonical_physical_binding']['sha256'],'actual_converter_scope_sha256':sc0['actual_typed_producer']['sha256'],'source_plan_scope_sha256':sc0['source_plan']['sha256'],'original_source143_scope_roles':sc0}
 for owner_role in ['canonical_physical_binding','classified_converter_owner']:
  z=sc0[owner_role];assert sha(z['owner_path'])==z['owner_sha256']
 ch={}
 for role,source in [('gencase','gencase'),('initial_qa','initial_native_qa'),('native_full','full_native'),('typed','typed_conversion'),('h5_audit','typed_h5_audit'),('floatinginfo','floatinginfo_state0')]:
  z=a[source];ch[role]={'execution_receipt':z['execution_receipt']['path']}
  for key in ['generated_xml','prepared_input_report','report','conversion_report','audit_report']:
   if key in z:ch[role][key]=z[key]['path']
 ch['floatinginfo']['audit']=ch['floatinginfo'].pop('audit_report');ch['xmf']={'execution_receipt':a['xmf']['execution_receipt']['path'],'manifest':a['xmf']['manifest']['path'],'case_xmf':a['xmf']['case_xmf']['path']}
 rq=next(H.glob('root*_951'))/'requests'/(cid+'-render-request.json');assert rq.is_file()
 normalized[cid]={'family_id':'F6','case_id':cid,'physical_case_id':nr['request']['physical_case_id'],'chain_paths':ch,'render':{'request':str(rq),'receipt':row['render_receipt'],'publish_receipt':row['render_publish_receipt'],'integrity_report':row['render_report']},'counts_identity':n,'scope_separation':sc,'lifecycle':vr['producer_lifecycle']}
 vr['physical_case_id']=nr['request']['physical_case_id'];vr['render']={'contact_sheets':len(vr['viewed_contact_sheet_indices']),'key_frames':vr['viewed_key_frame_indices']};vr['observations']=vr['visual_review']['observations'];vr['observations']['initial_state']={'personally_reviewed_key_frame0':0 in vr['viewed_key_frame_indices'],'observed':vr['observations']['failure_screen']['initial_state']}
c={'cases':normalized,'arrays_read_by_reviewer':False,'global_credit_updated_by_agent':False,'scientific_payload_read_or_hashed_by_reviewer':False};put(O/'source143-original-schema-actual-F6-chain-adapter.json',{'original_chain':ref(P/'metadata/chain-closure.json'),'original_visual':ref(P/'metadata/visual-review.json'),'metadata_representation_only':True,'cases':normalized,'source_reports_and_scientific_arrays_unchanged':True,'main_scientific_payload_IO':False})

reviews={z['case_id']:z for z in v['cases']}
assert not c['arrays_read_by_reviewer'] and not c['global_credit_updated_by_agent'] and not c['scientific_payload_read_or_hashed_by_reviewer']
for z in load(P/'metadata/evidence-files.json')['files']:
    assert ('bytes' not in z or Path(z['path']).stat().st_size==z['bytes']) and sha(z['path'])==z['sha256']
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_149.json');old=[load(p) for p in cp['accepted_decisions']]
assert len(old)==sum(cp['accepted_per_family'].values())==226
ids={z.get('physical_case_id',z['case_id']) for z in old};scopes={z['physical_condition_sha256'] for z in old}
proofs=[];decisions=[]
for cid,z in c['cases'].items():
    fam=z['family_id'];vis=reviews[cid];ch={k:dict(v) for k,v in z['chain_paths'].items()};ch['initial_native_qa']=ch.pop('initial_qa');ch['render']={k:z['render'][k] for k in ['request','receipt','publish_receipt']};ch['render']['report']=z['render']['integrity_report']
    if fam=='F6':
        ch['typed_h5_audit']=ch.pop('h5_audit');ch['floatinginfo_state0']=ch.pop('floatinginfo');ch['floatinginfo_state0']['audit_report']=ch['floatinginfo_state0'].pop('audit')
    n=z['counts_identity'];F={'F4':1201,'F6':241}[fam];end={'F4':1.2,'F6':12.0}[fam]
    assert z['case_id']==vis['case_id'] and z['physical_case_id']==vis['physical_case_id'] and vis['status']=='visual-approved-by-delegated-agent'
    assert vis['agent_personally_viewed_all_contact_sheets'] and vis['agent_personally_viewed_all_key_frames']
    assert vis['render']['contact_sheets']=={'F4':51,'F6':11,'F2':17}[fam] and len(vis['render']['key_frames'])==9
    assert {'mechanism','initial_state','all_contact_sheets','key_frames','failure_screen'}<=set(vis['observations'])
    receipts={}
    for role,item in ch.items():
        p=item.get('receipt',item.get('execution_receipt'))
        if p:
            rr=load(p);assert (rr['status'],rr['returncode'])==('completed',0);assert rr['request']['case_id']==z['case_id'];receipts[role]=rr
    t=load(ch['typed']['conversion_report']);r=load(ch['render']['report']);x=load(ch['xmf']['manifest']);qa=load(ch['initial_native_qa']['report']);qa_checks=qa.get('audit',qa)['checks'];assert qa_checks and all(qa_checks.values())
    assert t['frames']==r['frames']==r['source_frames']==x['frames']==F and t['particles']==x['particles']==n['total']
    assert n['dimension']==t['solver_dimension']['solver_dimension']==3 and sum(n[k] for k in ['fixed','moving','floating','fluid'])==n['total']
    assert t['conversion_status']=='completed' and t['partvtk_validation']['all_passed']
    assert all(f['passed'] and f['identity_type_mk_exact'] for f in t['partvtk_validation']['frames'])
    assert t['lifecycle']['introduced_ids']=='rejected' and t['typed_identity']['key']=='(Zone,Idp)'
    assert t['typed_identity']['initial_exclusion_ledger']['count']==0
    assert r['all_frames_rendered'] and r['native_identity_axis_preserved'] and r['actual_times_preserved_exactly'] and r['nonfinite_active_states']==0
    assert t['output_sha256']==r['source_h5_sha256']==x['source_h5_sha256']
    assert r['manifest_sha256']==sha(ch['xmf']['manifest']) and x['xdmf_sha256']==sha(ch['xmf']['case_xmf'])
    assert t['source_provenance']['solver_receipt']==ref(ch['native_full']['execution_receipt'])
    gencase_bridge=None
    if fam=='F4':
        observed=t['source_provenance']['gencase_receipt'];assert sha(observed['path'])==observed['sha256'];g=load(observed['path'])
        assert g['semantic_adapter'] and g['raw_receipt_immutable'] and g['raw_execution_receipt']==ref(ch['gencase']['execution_receipt'])
        assert g['generated_xml']==ref(ch['gencase']['generated_xml']) and g['prepared_input_report']==ref(ch['gencase']['prepared_input_report'])
        assert g['case_id']==z['case_id'] and g['actual_total_particles']==n['total'] and g['solver_dimension_from_gencase']==3
        assert g['actual_particle_counts']=={k:n[k] for k in ['fixed','moving','floating','fluid']}
        gencase_bridge={'typed_semantic_evidence':observed,'actual_raw_receipt':g['raw_execution_receipt'],'actual_prepared_report':g['prepared_input_report'],'semantic_adapter_does_not_rewrite_raw_receipt':True}
    else:
        assert t['source_provenance']['gencase_receipt']==ref(ch['gencase']['execution_receipt'])
    assert t['source_provenance']['generated_xml']==ref(ch['gencase']['generated_xml'])
    sc=z['scope_separation'];actual=t['hash_scopes']['physical_condition_sha256'];canonical=sc['source_canonical_or_basic_qa_scope_sha256'];plan=sc['source_plan_scope_sha256']
    assert actual==sc['actual_converter_scope_sha256']==x['physical_condition_sha256']
    assert receipts['native_full']['request']['physical_condition_sha256']==canonical
    assert receipts['native_full']['request']['physical_case_id']==z['physical_case_id']
    assert t['hash_scopes']['physical_condition']['physical_case_id']==x['physical_case_id']==z['physical_case_id']
    if fam=='F2':
        assert x['canonical_source_physical_condition_sha256']==canonical==plan and x['actual_converter_legacy_scope_sha256']==actual
        assert t['hash_scopes']['physical_condition']['schema']=='legacy-owner-scope.v0'
    elif fam=='F4':
        assert x['source_owner_physical_condition_sha256']==canonical and x['source_plan_condition_sha256']==plan
        assert t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
    else:
        assert x['source_canonical_physical_condition_sha256']==canonical and x['source_plan_condition_sha256']==plan
        assert t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
    fs=t['lifecycle']['frame_summary'];ds=r['frame_diagnostics'];grids=ET.parse(ch['xmf']['case_xmf']).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s']
    assert len(fs)==len(ds)==len(grids)==len(times)==F
    assert times==[f['time'] for f in fs]==[f['actual_time_s'] for f in ds]==[float(g.find('Time').get('Value')) for g in grids]
    assert times[0]==0 and times[-1]>=end and all(a<b for a,b in zip(times,times[1:]))
    assert x['fields']['position']['shape']==x['fields']['velocity']['shape']==[F,n['total'],3]
    assert fs[0]['missing_particles']==0
    initial_counts={'0':n['fixed'],'1':n['moving'],'2':n['floating'],'3':n['fluid']}
    for i,(f,d,g) in enumerate(zip(fs,ds,grids)):
        assert f['frame']==d['frame']==i and f['active_particles']==d['active'] and f['missing_particles']==d['missing']
        assert f['active_particles']+f['missing_particles']==n['total'] and f['missing_type_counts'].get('3',0)==f['missing_particles']
        assert all(f['type_counts'][key]+f['missing_type_counts'].get(key,0)==value for key,value in initial_counts.items())
        assert d['identity_axis_preserved'] and d['finite_positions_active'] and all(a['finite_active'] and a['nonfinite_active']==0 for a in d['finite_fields'].values())
        assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')==f"{n['total']} 3"
        vv=next(q for q in g.findall('Attribute') if q.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')==f"{n['total']} 3"
    life={'final_missing_particles':fs[-1]['missing_particles'],'final_missing_fraction_initial_fluid':fs[-1]['missing_particles']/n['fluid'],
        'final_missing_id_first_producer_attested':fs[-1]['missing_id_first'],'final_missing_ids_sha256_producer_attested':fs[-1]['missing_ids_sha256'],
        'first_missing_frame':next((f['frame'] for f in fs if f['missing_particles']),None),
        'max_missing_per_frame':max(f['missing_particles'] for f in fs),
        'frames_with_any_missing_particle':sum(f['missing_particles']>0 for f in fs),
        'cumulative_particle_frame_omissions':sum(f['missing_particles'] for f in fs),
        'unknown_missing_locations_states_and_causes':True,'omission_frame_events_not_unique_final_UID_count':True,
        'all_fixed_moving_floating_native_UIDs_active_every_frame':True}
    assert life['frames_with_any_missing_particle']==z['lifecycle']['transient_missing_frame_count']
    extra={}
    if fam=='F4':
        assert t['typed_identity']['blocks'][1]['count']==53248 and t['typed_identity']['blocks'][2]['count']==5824
        f0=load(ch['native_frame0']['report']);f0rows=[a for a in f0['cases'] if a['case_id']==z['case_id']];assert len(f0rows)==1;f0a=f0rows[0]
        assert f0a['pass'] and f0a['status']=='completed_pass' and f0a['finite_rows']==f0a['unique_identity_count']==f0a['native_rows']==n['total']
        assert f0a['actual_particle_counts']=={k:n[k] for k in ['fixed','moving','floating','fluid']} and f0a['fluid_rows_by_mk']=={'1':53248,'2':5824}
        assert f0a['native_raw_velocity_observed'] and not f0a['gencase_declared_velocity_used_as_evidence'] and f0a['max_abs_velocity_error_m_per_s']<=f0a['velocity_tolerance_m_per_s']
        assert f0a['generated_xml_sha256']==sha(ch['gencase']['generated_xml']) and all(v>1 for v in f0a['native_3d_levels'])
        extra={'actual_GenCase_semantic_receipt_provenance_bridge':gencase_bridge,'actual_native_frame0_velocity_audit':ref(ch['native_frame0']['report']),'native_frame0_velocity_tolerance_pass':True,'pool_native_particles':53248,'drop_native_particles':5824}
    if fam=='F2':assert life['final_missing_particles']==7 and life['frames_with_any_missing_particle']==245
    if fam=='F6':
        a=load(ch['typed_h5_audit']['report']);ang=load(ch['floatinginfo_state0']['audit_report']);ar=receipts['typed_h5_audit']
        assert a['status']==ang['status']=='pass' and all(a['checks'].values()) and all(ang['checks'].values())
        assert a['producer_physical_condition_sha256']==actual and a['source_canonical_physical_condition_sha256']==canonical
        assert a['case_id']==ang['case_id']==z['case_id'] and a['physical_case_id']==z['physical_case_id']
        assert a['conversion_report']['sha256']==sha(ch['typed']['conversion_report'])
        assert a['typed_execution_receipt']['sha256']==sha(ch['typed']['execution_receipt'])
        assert a['trajectory_h5_sha256'] is None and a['trajectory_h5']['path']==t['output_hdf5']
        source_h5=t['output_hdf5'];assert ar['input_hashes_at_launch'][source_h5]==ar['input_hashes_after_run'][source_h5]==ar['request']['input_sha256'][source_h5]==t['output_sha256']
        assert a['state0_dependency']['audit_report']==ch['floatinginfo_state0']['audit_report'] and a['state0_dependency']['audit_report_sha256']==sha(ch['floatinginfo_state0']['audit_report'])
        expected=qa['angular_state']['declared_angularvelini_rad_s'];observed=ang['observed_state0_angular_velocity_rad_s']
        assert expected==ang['expected_angular_velocity_rad_s'] and observed==a['state0_dependency']['observed_omega_rad_s']
        assert all(abs(a-b)<=ang['omega_tolerance_rad_s'] for a,b in zip(expected,observed))
        ep=ang['endpoint'];assert sha(ep['canonical_owner'])==ep['canonical_owner_sha256'] and ep['physical_condition_sha256']==canonical
        assert sha(ep['generated_xml'])==ep['generated_xml_sha256']==sha(ch['gencase']['generated_xml'])
        assert expected==ep['declared_angular_velocity_rad_s']
        assert a['mass_policy']['physical_mass_kg']==128 and a['mass_policy']['native_support_mass_kg']==256 and a['mass_policy']['normalization']=='none' and not a['mass_policy']['equality_required']
        af=a['lifecycle']['frames'];assert len(af)==F and [f['time_s'] for f in af]==times
        assert all(f['frame']==i and f['excluded_count']==fs[i]['missing_particles'] and f['active_count']==fs[i]['active_particles'] for i,f in enumerate(af))
        assert life['frames_with_any_missing_particle']==234 and a['lifecycle']['ever_excluded_count']==z['lifecycle']['ever_excluded_count']==z['lifecycle']['ever_excluded_count']
        extra={'actual_angular_velocity_state0':{'declared_rad_s':expected,'observed_rad_s':observed,'tolerance_rad_s':ang['omega_tolerance_rad_s'],
            'actual_receipt':ref(ch['floatinginfo_state0']['execution_receipt']),'actual_report':ref(ch['floatinginfo_state0']['audit_report']),'particle_v0_is_not_omega_evidence':True},
            'full241_independent_H5_audit':ref(ch['typed_h5_audit']['report']),'audit_local_H5_digest_preserved_null':True,
            'actual_audit_runner_same_source_H5_digest_before_after':t['output_sha256'],'mass_policy':a['mass_policy'],
            'ever_excluded_count_actual_independent_audit':a['lifecycle']['ever_excluded_count']}
    acceptance_scope=actual if fam=='F6' else canonical
    assert z['physical_case_id'] not in ids and acceptance_scope not in scopes
    ids.add(z['physical_case_id']);scopes.add(acceptance_scope)
    decisions.append({'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status':vis['status'],'family_id':fam,'case_id':z['case_id'],'physical_case_id':z['physical_case_id'],
        'physical_condition_sha256':acceptance_scope,'source_canonical_physical_condition_sha256':canonical,'actual_converter_scope_sha256':actual,
        'producer_scope_schema_verified_from_actual_report':t['hash_scopes']['physical_condition']['schema'],
        'source_review_commit':commit,'source_visual_review':ref(P/'metadata/visual-review.json'),'source_review_closure':ref(P/'metadata/chain-closure.json'),
        'scope_separation':sc,'lifecycle':life,'family_specific_proof':extra,'actual_completed_metadata_evidence':ch,
        'full_native_frames':F,'particles':n['total'],'actual_physical_window_s':[times[0],times[-1]],
        'all_actual_times_exact_typed_XMF_XML_render':True,'all_frames_geometry_velocity_N3_identity_and_finite_active_fields':True,
        'stage1_QI_full_native_identity_and_state_verified':True,'agent_personally_viewed_all_contacts_and_keys':True,
        'agent_observations':vis['observations'],'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,
        'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
    proofs.append({'family_id':fam,'physical_case_id':z['physical_case_id'],'full_native_frames':F,'lifecycle':life,'family_specific_proof':extra})
assert len(decisions)==2
dp=[]
for decision in decisions:
    p=O/(decision['physical_case_id']+'-delegated-visual-decision.json');put(p,decision);dp.append(str(p));cp['accepted_per_family'][decision['family_id']]+=1
put(O/'adoption-and-two-case-independent-review.json',{'adopted_files':adopted,'actual_source143_validator':ref(O/'actual-source143-validator.json'),
    'previous_accepted':226,'new_accepted':228,'cases':proofs,'new_decisions':[ref(p) for p in dp],
    'main_scientific_payload_IO':False,'all22_contact_sheets_and18_keys_personally_viewed_by_delegated_agent':True,
    'source143_frozen_reports_preserved':True,'small_observed_fluid_omissions_preserved_not_subject_to_previous_other_case_max2_assumption':True})
cp.update(checkpoint=150,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_149.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_149.json'),
    stage1_visual_accepted_complete_independent_cases=228,new_accepted_decisions=dp,accepted_decisions=cp['accepted_decisions']+dp,
    previous_goal_turn_classification='Progress: two genuine F6 full241 native/typed/XMF/render0, independent H5 audit and angular-state0, delegated143 personal22contacts18keys independently accepted228. Source canonical/plan/classified/producer scopes remain separate. Missing fluid UID counts4 and3 with933/700 particle-frame events remain unknown causes; mass physical128kg/native256kg not rescaled; no Q-N/Q-E.')
assert sum(cp['accepted_per_family'].values())==len(cp['accepted_decisions'])==228
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw)
cp.update(home_free_gib=shutil.disk_usage('/home/jade').free/1024**3,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),
    active_reservations=ledger['reservations'],attempt_counts={k:sum(z['kind']==k for z in ledger['attempts']) for k in ['qualification','production','cpu']},
    gpu_hours_charged=sum(z.get('gpu_seconds',0) for z in ledger['charges'])/3600,cpu_core_hours_charged=sum(z.get('cpu_core_seconds',0) for z in ledger['charges'])/3600)
cp['actual_progress']['delegated143_two_F6_full241_visual_integrated']=ref(O/'adoption-and-two-case-independent-review.json')
cp['source_agents']['f6_endpoint_initial_qa']='fresh143 two F6 actual951 full241 independently accepted228; fresh144 two ready F6 full241 visuals active'
cp['next_executable_tasks']=[s for s in cp['next_executable_tasks'] if 'fresh143' not in s]
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_150.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(z['path']).relative_to(R)) for z in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_150.json').relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: accept two F6 angular-release full241 visuals with independent native and H5 audit closure','--',*paths],cwd=R,check=True)
print({'accepted':228,'counts':cp['accepted_per_family'],'cases':[{'family':p['family_id'],'frames':p['full_native_frames'],'lifecycle':p['lifecycle']} for p in proofs],
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
