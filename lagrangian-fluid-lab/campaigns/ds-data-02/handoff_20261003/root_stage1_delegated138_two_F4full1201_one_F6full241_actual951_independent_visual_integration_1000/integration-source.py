from pathlib import Path
import json,hashlib,subprocess,datetime,xml.etree.ElementTree as ET,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.txt','.log','.xml','.xmf','.png'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_138_f4_f6_delegated_visual_acceptance_v1';commit='b9ffbb5805090aa827eb243def5d1ee678f4f2f9'
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert 8<=len(names)<=15
adopted=[]
for name in names:
    assert Path(name).suffix in {'.json','.py','.md'}
    raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes()
    p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_delegated138_two_F4full1201_one_F6full241_actual951_independent_visual_integration_1000';O.mkdir(exist_ok=True);assert not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_141.json').exists();assert not list(O.glob('*-delegated-visual-decision.json'))
validator=P/'workers/validate_fresh138.py';result=subprocess.run([str(L/'.venv/bin/python'),str(validator)],capture_output=True,text=True)
put(O/'actual-source138-validator.json',{'validator':ref(validator),'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr});assert result.returncode==0,(result.stdout,result.stderr)
c=load(P/'metadata/chain-closure.json');v=load(P/'metadata/visual-review.json');reviews={z['case_id']:z for z in v['cases']}
assert not c['arrays_read_by_reviewer'] and not c['global_credit_updated_by_agent'] and not c['scientific_payload_read_or_hashed_by_reviewer']
for z in load(P/'metadata/evidence-files.json')['files']:
    assert Path(z['path']).stat().st_size==z['bytes'] and sha(z['path'])==z['sha256']
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_140.json');old=[load(p) for p in cp['accepted_decisions']]
assert len(old)==sum(cp['accepted_per_family'].values())==211
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
        assert life['max_missing_per_frame']==0 and t['typed_identity']['blocks'][1]['count']==53248 and t['typed_identity']['blocks'][2]['count']==5824
        extra={'actual_GenCase_semantic_receipt_provenance_bridge':gencase_bridge,'pool_native_particles':53248,'drop_native_particles':5824}
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
        assert life['frames_with_any_missing_particle']==234 and a['lifecycle']['ever_excluded_count']==z['lifecycle']['ever_excluded_count']==4
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
assert len(decisions)==3
dp=[]
for decision in decisions:
    p=O/(decision['physical_case_id']+'-delegated-visual-decision.json');put(p,decision);dp.append(str(p));cp['accepted_per_family'][decision['family_id']]+=1
put(O/'adoption-and-three-case-independent-review.json',{'adopted_files':adopted,'actual_source138_validator':ref(O/'actual-source138-validator.json'),
    'previous_accepted':211,'new_accepted':214,'cases':proofs,'new_decisions':[ref(p) for p in dp],
    'main_scientific_payload_IO':False,'all113_contact_sheets_and27_keys_personally_viewed_by_delegated_agent':True,
    'source138_frozen_route_no_live_metadata_repair_needed':True})
cp.update(checkpoint=141,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_140.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_140.json'),
    stage1_visual_accepted_complete_independent_cases=214,new_accepted_decisions=dp,accepted_decisions=cp['accepted_decisions']+dp,
    previous_goal_turn_classification='Verified previous cleanup: exact15995 deleted frames remain absent, immutable cleanup receipts unchanged, no new failed native frames; current turn independently accepts three new full-window F4/F6 visuals from delegated138. Root997 first full836 XMF actual0; remaining same controller live, no restart.')
assert sum(cp['accepted_per_family'].values())==len(cp['accepted_decisions'])==214
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw)
cp.update(home_free_gib=shutil.disk_usage('/home/jade').free/1024**3,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),
    active_reservations=ledger['reservations'],attempt_counts={k:sum(z['kind']==k for z in ledger['attempts']) for k in ['qualification','production','cpu']},
    gpu_hours_charged=sum(z.get('gpu_seconds',0) for z in ledger['charges'])/3600,cpu_core_hours_charged=sum(z.get('cpu_core_seconds',0) for z in ledger['charges'])/3600)
cp['actual_progress']['delegated138_three_full_native_physical_visual_integrated']=ref(O/'adoption-and-three-case-independent-review.json')
cp['source_agents']['f6_endpoint_initial_qa']='fresh138 byte-exact adopted and actual validator PASS; two F4 full1201 and one F6 full241 independently accepted to214; fresh139 three F4 visual ready, fresh140 F2 downstream source active'
cp['next_executable_tasks']=[s for s in cp['next_executable_tasks'] if 'fresh138' not in s]
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_141.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(z['path']).relative_to(R)) for z in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_141.json').relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: accept two F4 and one F6 complete physical visuals with full native identity and lifecycle closure','--',*paths],cwd=R,check=True)
print({'accepted':214,'counts':cp['accepted_per_family'],'cases':[{'family':p['family_id'],'frames':p['full_native_frames'],'lifecycle':p['lifecycle']} for p in proofs],
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
