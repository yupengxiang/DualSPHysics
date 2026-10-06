from pathlib import Path
import json,hashlib,subprocess,datetime,xml.etree.ElementTree as ET,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.txt','.xml','.xmf','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_137_f5_f6_angular_delegated_visual_acceptance_v1';commit='9762deedf606832b8d84b747a191b836eb33f66d'
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert 8<=len(names)<=15
adopted=[]
for name in names:
 assert Path(name).suffix in {'.json','.py','.md'};raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);adopted.append(ref(p))
P=R/prefix;O=H/'root_stage1_delegated137_two_F6_full241_independent_QI_angular_visual_F5_bed_pending_989';O.mkdir(exist_ok=True);assert not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_136.json').exists() and not list(O.glob('*-delegated-visual-decision.json'))
vld=P/'workers/validate_fresh137.py';vr=subprocess.run([str(L/'.venv/bin/python'),str(vld)],capture_output=True,text=True);put(O/'actual-source137-validator.json',{'validator':ref(vld),'returncode':vr.returncode,'stdout':vr.stdout,'stderr':vr.stderr});assert vr.returncode==0,(vr.stdout,vr.stderr)
c=load(P/'metadata/chain-closure.json');v=load(P/'metadata/visual-review.json');assert not c['arrays_read_by_reviewer'] and not c['global_credit_updated_by_agent']
reviews={z['case_id']:z for z in v['cases']};assert set(reviews)==set(c['cases'])
for z in load(P/'metadata/evidence-files.json')['files']:assert Path(z['path']).stat().st_size==z['bytes'] and sha(z['path'])==z['sha256']
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_135.json');old=[load(p) for p in cp['accepted_decisions']];assert len(old)==sum(cp['accepted_per_family'].values())==208
ids={z.get('physical_case_id',z['case_id']) for z in old};scopes={z['physical_condition_sha256'] for z in old};decisions=[];pending=[]
for cid,z in c['cases'].items():
 fam=z['family_id'];vis=reviews[cid];ch=z['producer_chain'];ch={k:dict(v) for k,v in ch.items()};ch['render']={k:z['render'][k] for k in ['request','receipt','report','publish_receipt']};n=z['counts_identity'];F=241 if fam=='F6' else 801;end=12 if fam=='F6' else 16
 assert vis==z and vis['status']=='visual-approved-by-delegated-agent'
 assert vis['agent_personally_viewed_all_contact_sheets'] and vis['agent_personally_viewed_all_key_frames'] and len(z['render']['key_frames'])==9
 receipts={}
 for role,item in ch.items():
  p=item.get('receipt',item.get('execution_receipt'))
  if p:
   rr=load(p);assert (rr['status'],rr['returncode'])==('completed',0);assert rr['request']['case_id']==cid;receipts[role]=rr
 t=load(ch['typed']['conversion_report']);r=load(ch['render']['report']);x=load(ch['xmf']['manifest'])
 qp=ch['initial_native_qa'].get('report',ch['initial_native_qa'].get('placement_report'));qa=load(qp)
 if fam=='F6': assert qa['checks'] and all(qa['checks'].values())
 else:
  qa2=load(ch['initial_native_qa']['placement_audit']);assert qa2['checks'] and all(val for key,val in qa2['checks'].items() if 'precision' not in key and 'lattice' not in key)
 assert t['frames']==r['frames']==r['source_frames']==x['frames']==F and t['particles']==x['particles']==n['total']
 assert n['dimension']==t['solver_dimension']['solver_dimension']==3 and sum(n[k] for k in ['fixed','moving','floating','fluid'])==n['total']
 assert t['conversion_status']=='completed' and t['partvtk_validation']['all_passed'] and all(f['passed'] and f['identity_type_mk_exact'] for f in t['partvtk_validation']['frames'])
 assert t['lifecycle']['introduced_ids']=='rejected' and t['typed_identity']['key']=='(Zone,Idp)' and t['typed_identity']['initial_exclusion_ledger']['count']==0
 assert r['all_frames_rendered'] and r['native_identity_axis_preserved'] and r['actual_times_preserved_exactly'] and r['nonfinite_active_states']==0
 assert t['output_sha256']==r['source_h5_sha256']==x['source_h5_sha256']
 assert r['manifest_sha256']==sha(ch['xmf']['manifest']) and x['xdmf_sha256']==sha(ch['xmf']['case_xmf'])
 for role,field in [('native_full','solver_receipt'),('gencase','gencase_receipt')]:assert t['source_provenance'][field]==ref(ch[role]['execution_receipt'])
 assert t['source_provenance']['generated_xml']==ref(ch['gencase']['generated_xml']);om=t['source_provenance']['owner_metadata'];assert sha(om['path'])==om['sha256']
 sc=z['scope_separation'];actual=t['hash_scopes']['physical_condition_sha256'];canonical=sc['source_canonical_or_owner_scope_sha256'];plan=sc['source_plan_scope_sha256']
 assert actual==sc['actual_converter_or_producer_scope_sha256'] and receipts['native_full']['request']['physical_condition_sha256']==canonical
 assert receipts['native_full']['request']['physical_case_id']==z['physical_case_id']==t['hash_scopes']['physical_condition']['physical_case_id']==x['physical_case_id']
 if fam=='F6':
  assert x['physical_condition_sha256']==actual and x['source_canonical_physical_condition_sha256']==canonical and x['source_plan_condition_sha256']==plan and t['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1'
 else:
  assert x['physical_condition_sha256']==x['canonical_physical_condition_sha256']==canonical and x['source_h5_physical_condition_sha256']==actual and x['source_plan_physical_condition_sha256']==plan and t['hash_scopes']['physical_condition']['schema']=='legacy-owner-scope.v0'
 fs=t['lifecycle']['frame_summary'];ds=r['frame_diagnostics'];grids=ET.parse(ch['xmf']['case_xmf']).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s']
 assert len(fs)==len(ds)==len(grids)==len(times)==F and times==[f['time'] for f in fs]==[f['actual_time_s'] for f in ds]==[float(g.find('Time').get('Value')) for g in grids]
 assert times[0]==0 and times[-1]>=end and all(a<b for a,b in zip(times,times[1:])) and x['fields']['position']['shape']==x['fields']['velocity']['shape']==[F,n['total'],3]
 counts={'0':n['fixed'],'1':n['moving'],'2':n['floating'],'3':n['fluid']};assert fs[0]['missing_particles']==0
 for i,(f,d,g) in enumerate(zip(fs,ds,grids)):
  assert f['frame']==d['frame']==i and f['active_particles']==d['active'] and f['missing_particles']==d['missing'] and f['active_particles']+f['missing_particles']==n['total']
  assert f['missing_type_counts'].get('3',0)==f['missing_particles'] and all(f['type_counts'][k]+f['missing_type_counts'].get(k,0)==v for k,v in counts.items())
  assert d['identity_axis_preserved'] and d['finite_positions_active'] and all(a['finite_active'] and a['nonfinite_active']==0 for a in d['finite_fields'].values())
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')==f"{n['total']} 3"
  vv=next(q for q in g.findall('Attribute') if q.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')==f"{n['total']} 3"
 life={'final_missing_particles':fs[-1]['missing_particles'],'final_missing_fraction_initial_fluid':fs[-1]['missing_particles']/n['fluid'],'final_missing_id_first_producer_attested':fs[-1]['missing_id_first'],'final_missing_ids_sha256_producer_attested':fs[-1]['missing_ids_sha256'],'first_missing_frame':next((f['frame'] for f in fs if f['missing_particles']),None),'max_missing_per_frame':max(f['missing_particles'] for f in fs),'frames_with_any_missing_particle':sum(f['missing_particles']>0 for f in fs),'cumulative_particle_frame_omissions':sum(f['missing_particles'] for f in fs),'unknown_missing_locations_states_and_causes':True,'omission_frame_events_not_unique_final_UID_count':True,'all_fixed_moving_floating_native_UIDs_active_every_frame':True}
 assert z['physical_case_id'] not in ids
 if fam=='F5':
  assert life['max_missing_per_frame']==0
  pending.append({'family_id':fam,'physical_case_id':z['physical_case_id'],'source_visual_review':ref(P/'metadata/visual-review.json'),'actual_completed_metadata_evidence':ch,'full_native_frames':F,'full_time_N3_finite_identity_pass':True,'stage1_case_credit':0,'reason':'Full801 bed-penetration audit actual0 is absent from delegated137 evidence; main requires actual audit producer closure before case credit.','lifecycle':life,'source_h5_sha256_producer_attested':t['output_sha256']});continue
 assert life['frames_with_any_missing_particle']==z['lifecycle']['transient_missing_frame_count']==234 and life['cumulative_particle_frame_omissions']==z['lifecycle']['particle_frame_omission_events_by_type']['3']
 a=load(ch['h5_audit']['report']);ang=load(ch['floatinginfo_state0']['audit_report']);ar=receipts['h5_audit']
 assert a['status']==ang['status']=='pass' and all(a['checks'].values()) and all(ang['checks'].values()) and a['case_id']==ang['case_id']==cid
 assert a['producer_physical_condition_sha256']==actual and a['source_canonical_physical_condition_sha256']==canonical and a['physical_case_id']==z['physical_case_id']
 assert a['conversion_report']['sha256']==sha(ch['typed']['conversion_report']) and a['typed_execution_receipt']['sha256']==sha(ch['typed']['execution_receipt'])
 source_h5=t['output_hdf5'];assert a['trajectory_h5_sha256'] is None and a['trajectory_h5']['path']==source_h5 and ar['input_hashes_at_launch'][source_h5]==ar['input_hashes_after_run'][source_h5]==ar['request']['input_sha256'][source_h5]==t['output_sha256']
 assert a['state0_dependency']['audit_report']==ch['floatinginfo_state0']['audit_report'] and a['state0_dependency']['audit_report_sha256']==sha(ch['floatinginfo_state0']['audit_report'])
 expected=qa['angular_state']['declared_angularvelini_rad_s'];observed=ang['observed_state0_angular_velocity_rad_s'];ep=ang['endpoint'];assert expected==ang['expected_angular_velocity_rad_s']==ep['declared_angular_velocity_rad_s'] and observed==a['state0_dependency']['observed_omega_rad_s']
 assert all(abs(u-w)<=ang['omega_tolerance_rad_s'] for u,w in zip(expected,observed));assert sha(ep['canonical_owner'])==ep['canonical_owner_sha256'] and ep['physical_condition_sha256']==canonical and sha(ep['generated_xml'])==ep['generated_xml_sha256']==sha(ch['gencase']['generated_xml'])
 assert a['mass_policy']['physical_mass_kg']==128 and a['mass_policy']['native_support_mass_kg']==256 and a['mass_policy']['normalization']=='none' and not a['mass_policy']['equality_required']
 af=a['lifecycle']['frames'];assert len(af)==F and [f['time_s'] for f in af]==times and all(f['frame']==i and f['excluded_count']==fs[i]['missing_particles'] and f['active_count']==fs[i]['active_particles'] for i,f in enumerate(af))
 assert actual not in scopes;ids.add(z['physical_case_id']);scopes.add(actual)
 extra={'actual_angular_velocity_state0':{'declared_rad_s':expected,'observed_rad_s':observed,'tolerance_rad_s':ang['omega_tolerance_rad_s'],'actual_receipt':ref(ch['floatinginfo_state0']['execution_receipt']),'actual_report':ref(ch['floatinginfo_state0']['audit_report']),'particle_v0_is_not_omega_evidence':True},'full241_independent_H5_audit':ref(ch['h5_audit']['report']),'audit_local_H5_digest_preserved_null':True,'actual_audit_runner_same_source_H5_digest_before_after':t['output_sha256'],'mass_policy':a['mass_policy'],'ever_excluded_count_actual_independent_audit':a['lifecycle']['ever_excluded_count']}
 decisions.append({'schema':'ds02.stage1.delegated-visual-metadata-integration.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':vis['status'],'family_id':fam,'case_id':cid,'physical_case_id':z['physical_case_id'],'physical_condition_sha256':actual,'source_canonical_physical_condition_sha256':canonical,'actual_converter_scope_sha256':actual,'producer_scope_schema_verified_from_actual_report':t['hash_scopes']['physical_condition']['schema'],'source_review_commit':commit,'source_visual_review':ref(P/'metadata/visual-review.json'),'source_review_closure':ref(P/'metadata/chain-closure.json'),'scope_separation':sc,'lifecycle':life,'family_specific_proof':extra,'actual_completed_metadata_evidence':ch,'full_native_frames':F,'particles':n['total'],'actual_physical_window_s':[times[0],times[-1]],'all_actual_times_exact_typed_XMF_XML_render':True,'all_frames_geometry_velocity_N3_identity_and_finite_active_fields':True,'stage1_QI_full_native_identity_and_state_verified':True,'agent_personally_viewed_all_contacts_and_keys':True,'agent_observations':vis['observations'],'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'q_n_granted':False,'q_e_granted':False,'precision_status':'视觉检查通过、数值精度未验收','independent_case_increment':1})
assert len(decisions)==2 and len(pending)==1
dp=[]
for decision in decisions:
 p=O/(decision['physical_case_id']+'-delegated-visual-decision.json');put(p,decision);dp.append(str(p));cp['accepted_per_family'][decision['family_id']]+=1
put(O/'adoption-and-two-case-independent-review.json',{'adopted_files':adopted,'actual_source137_validator':ref(O/'actual-source137-validator.json'),'previous_accepted':208,'new_accepted':210,'new_decisions':[ref(p) for p in dp],'pending_F5_no_credit':pending,'main_scientific_payload_IO':False,'all83_contact_key_PNGs_personally_viewed_by_delegated_agent':True,'frozen_route_no_live_metadata_repair_needed':True})
cp.update(checkpoint=136,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_135.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_135.json'),stage1_visual_accepted_complete_independent_cases=210,new_accepted_decisions=dp,accepted_decisions=cp['accepted_decisions']+dp,previous_goal_turn_classification='Progress: previous actual full-native physical visual integration raised208 and first F3 full836 XMF977 completed0; unchanged original116023 renderer987 launched. Failed-native cleanup14/439GiB revalidated; no new failed native candidates. This turn two actual F6 visuals fully independently closed to210; F5M085T090 full801 visual pending missing actual bed proof preserved, not credited.')
assert sum(cp['accepted_per_family'].values())==len(cp['accepted_decisions'])==210
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);cp.update(home_free_gib=shutil.disk_usage('/home/jade').free/1024**3,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),active_reservations=ledger['reservations'],attempt_counts={k:sum(z['kind']==k for z in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(z.get('gpu_seconds',0) for z in ledger['charges'])/3600,cpu_core_hours_charged=sum(z.get('cpu_core_seconds',0) for z in ledger['charges'])/3600)
cp['actual_progress']['delegated137_two_F6_visual_integrated_F5_bed_pending']=ref(O/'adoption-and-two-case-independent-review.json');cp['source_agents']['f6_endpoint_initial_qa']='fresh137 byte-exact adopted: two F6 full241 angular identity visual accepted to210; F5M085T090 full801 visual pending actual bed audit; fresh138 actual completed visual review active';cp['next_executable_tasks']=['Adopt fresh166 regular-file-only correct-tool12 full801 F5 typed requests, exclude actual98312 and accepted/pending physics; admit928serial CPU2 with4GiB cap.','Adopt source125 two actual completed full836 F3 typed978 original104 XMF requests, then only actual0 bind original116023 renders.','Close pending F5M085T090 full801 bed actual0 with original138 worker; visual review137 already complete, no duplicate science if prior exact bed audit exists.','Integrate fresh138 next <=3 actual completed delegated visuals after allframe family-specific independent QI.','Observe actual951/972/978/981/983/984/987 same live process handles; no restarts from quiet or timeout.'];put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_136.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(z['path']).relative_to(R)) for z in adopted]+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_136.json').relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: accept two complete F6 angular visuals and retain F5 full801 bed audit prerequisite','--',*paths],cwd=R,check=True);print({'accepted':210,'counts':cp['accepted_per_family'],'lifecycle':[d['lifecycle'] for d in decisions],'F5_pending_bed':True,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
