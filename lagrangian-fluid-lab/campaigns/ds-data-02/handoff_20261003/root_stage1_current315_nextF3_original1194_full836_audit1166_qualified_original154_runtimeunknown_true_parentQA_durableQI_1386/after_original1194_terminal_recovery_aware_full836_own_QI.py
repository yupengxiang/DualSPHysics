from pathlib import Path
import json, hashlib, datetime, math, os, sys, subprocess, copy, collections
import xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p): return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.py','.md','.xml','.xmf'}
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p): return {'path':str(p),'sha256':sha(p)}
def checked(e): assert sha(e['path'])==e['sha256']
def put(p,v):
 with Path(p).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def commit(paths,message):
 ps=[str(p.relative_to(R)) for p in paths]
 subprocess.run(['git','add','--',*ps],cwd=R,check=True)
 subprocess.run(['git','commit','-q','-m',message,'--',*ps],cwd=R,check=True)
 return subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
def completed(e,case=None,physical=None):
 checked(e);j=load(e['path']);assert j['schema']=='ds02.execution-receipt.v1' and (j['status'],j['returncode'])==('completed',0)
 if case is not None:assert j['request']['case_id']==case
 if physical is not None:assert j['request']['physical_case_id']==physical
 return j
F=root(1194);basep=F/'actual1193-full836-N3-UID-times-audit-qualified-legacy-native-role-review.json'
def inspect_chain():
 b=load(basep);refs={k:e for k,e in b.items() if isinstance(e,dict) and 'path' in e and 'sha256' in e}
 for e in refs.values():checked(e)
 w=load(F/'enabled-render-wrapper.json');cid=w['case_id'];pid=w['physical_case_id']
 assert cid=='F3_STAGE1_DP006_P1000_AY0270' and pid=='F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW'
 n=completed(refs['actual_native_receipt'],cid,pid);ar=completed(refs['actual_artifact_audit_receipt'],cid,pid);xr=completed(refs['actual_XMF_receipt'],cid,pid)
 old=load(refs['original_conversion_receipt']['path']);assert old['status']=='running' and 'returncode' not in old
 t=load(refs['actual_producer_conversion_report']['path']);a=load(refs['actual_artifact_audit_report']['path']);x=load(refs['actual_XMF_manifest']['path'])
 canonical=n['request']['physical_condition_sha256'];legacy=t['hash_scopes']['physical_condition_sha256']
 assert canonical=='a6a7dfcc6a3c45b895ae096d652c4bf4d203b6b3b9d228e40c7c7518e8d109e9'
 assert legacy=='217fbe56b0a884a75199c2aabef347872558260395688dcaee30c0c9a3719413' and canonical!=legacy
 assert x['physical_condition_sha256']==x['canonical_source_physical_condition_sha256']==canonical and x['actual_converter_scope_sha256']==legacy
 assert t['hash_scopes']['physical_condition']['schema']=='legacy-owner-scope.v0' and t['hash_scopes']['physical_condition']['physical_case_id']==x['physical_case_id']==pid
 assert a['case_id']==cid and a['artifact_integrity_status']=='completed' and a['worker_returncode']==0
 assert a['physical_identity']['physical_case_id']==pid and a['physical_identity']['canonical_native_condition_sha256']==canonical and a['physical_identity']['converter_legacy_scope_sha256']==legacy
 assert a['source_conversion_lifecycle']['receipt_status']=='running' and a['source_conversion_lifecycle']['receipt_returncode'] is None
 assert a['source_conversion_lifecycle']['old_os_exit_zero_claim'] is False and a['source_conversion_lifecycle']['source_conversion_reclassified'] is False and a['source_conversion_lifecycle']['source_receipt_edited'] is False
 fa=a['field_audit'];assert fa['frames']==836 and fa['particles']==179208 and fa['position_shape']==[836,179208,3]
 for k in ['finite_position_velocity_density_pressure_mass','n3_shape_verified','report_frame_ledger_verified','time_axis_verified_against_report','type_mk_verified_all_frames','uid_composite_unique']:assert fa[k] is True
 assert fa['source_arrays_modified'] is False and fa['uid_lifecycle_missing_count']==0
 ak=a['approved_temporal_kernel'];assert ak['checked_transitions']==835 and ak['full_temporal_scan'] and ak['position_velocity_n3'] and ak['uid_and_mass_validity_lifecycle']
 assert a['report_frame_ledger']=={'frames':836,'missing_particles_all_frames':0,'times_compared_to_report':True,'type_counts_compared_all_frames':True}
 assert t['conversion_status']=='completed' and t['solver_dimension']['solver_dimension']==x['xmf_shape_contract']['dimension']==3
 assert t['partvtk_validation']['all_passed'] and all(z['passed'] and z['identity_type_mk_exact'] for z in t['partvtk_validation']['frames'])
 assert t['typed_identity']['key']=='(Zone,Idp)' and t['typed_identity']['initial_exclusion_ledger']['count']==0 and t['lifecycle']['introduced_ids']=='rejected'
 h5=t['output_hdf5'];assert Path(h5).is_file();h5sha=t['output_sha256']
 assert h5sha==x['source_h5_sha256']==a['producer_attestation']['verified_trajectory_sha256']==a['producer_attestation']['producer_reported_trajectory_sha256']
 for rr in [ar,xr]:assert rr['input_hashes_at_launch'][h5]==rr['input_hashes_after_run'][h5]==h5sha
 assert a['producer_attestation']['conversion_report_sha256']==refs['actual_producer_conversion_report']['sha256']
 assert a['producer_attestation']['native_receipt_sha256']==refs['actual_native_receipt']['sha256']
 assert x['receipt_roles']['original_conversion_receipt']['path']==refs['original_conversion_receipt']['path'] and x['receipt_roles']['original_conversion_receipt']['sha256']==refs['original_conversion_receipt']['sha256']
 assert x['receipt_roles']['original_conversion_receipt']['returncode_field_present'] is False and x['receipt_roles']['original_conversion_receipt']['returncode'] is None
 assert x['receipt_roles']['artifact_audit_receipt']['sha256']==refs['actual_artifact_audit_receipt']['sha256'] and x['audit_provenance']['artifact_audit_report']['sha256']==refs['actual_artifact_audit_report']['sha256']
 assert x['audit_provenance']['old_typed_receipt_is_not_reclassified'] is True
 for key in ['solver_receipt','gencase_receipt','generated_xml','owner_metadata']:checked(t['source_provenance'][key]);refs['typed_source_'+key]=t['source_provenance'][key]
 assert t['source_provenance']['solver_receipt']==refs['actual_native_receipt'];completed(t['source_provenance']['gencase_receipt'])
 nq=n['request'];prep_ref=nq['source_owner'];checked(prep_ref);p=load(prep_ref['path']);refs['actual_preparation_report']=prep_ref
 assert p['case_id']==cid and p['physical_case_id']==pid and p['physical_condition_sha256']==canonical
 assert p['xml_byte_identical_to_baseline'] and p['initial_bi4_byte_identical_to_baseline']
 assert p['forcing_transform']['status']=='success' and p['forcing_transform']['source_sha256_before']==p['forcing_transform']['source_sha256_after']
 assert nq['nominal_pitch_multiplier']==1.0 and nq['transverse_amplitude_m_s2']==.27
 prep_receipt=nq['exact_initial_clone_receipt'];completed(prep_receipt);refs['actual_initial_clone_preparation_receipt']=prep_receipt
 qr=nq['initial_native_reference']['parent_initial_qa'];checked(qr);qa=load(qr['path']);qrec=ref(Path(qr['path']).parent/'execution-receipt.json');completed(qrec)
 qa0=next(z for z in qa['cases'] if z['role']=='twoaxis_dp006');assert qa0['passed'] and qa0['actual_3d'] and qa0['native_particles']==179208 and qa0['native_fixed']==111708 and qa0['native_fluid']==67500
 refs['genuine_parent_initial_QA_report']=qr;refs['genuine_parent_initial_QA_receipt']=qrec
 for key in ['forcing','generated_xml','initial_bi4']:
  e=nq['prepared_input'][key];assert n['input_hashes_at_launch'][e['path']]==n['input_hashes_after_run'][e['path']]==e['sha256']
 assert qa0['generated_xml_sha256']==nq['prepared_input']['generated_xml']['sha256']==sha(nq['prepared_input']['generated_xml']['path'])
 assert qa0['native_initial_BI4_sha256']==nq['prepared_input']['initial_bi4']['sha256']
 masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]}
 assert all(v=={'present':False,'value':None} for m in masks.values() for v in m.values())
 fs=t['lifecycle']['frame_summary'];times=x['actual_time_s'];xp=Path(refs['actual_XMF_XML']['path']);grids=ET.parse(xp).findall('.//Grid[@GridType="Uniform"]')
 assert x['xdmf']==str(xp) and x['xdmf_sha256']==sha(xp) and len(fs)==len(times)==len(grids)==t['frames']==x['frames']==w['expected_frames']==836
 assert t['particles']==x['particles']==w['expected_particles']==179208 and w['expected_contact_sheets']==35
 assert x['fields']['position']['shape']==x['fields']['velocity']['shape']==[836,179208,3]
 assert times==[z['time'] for z in fs]==[float(g.find('Time').get('Value')) for g in grids]
 assert times[0]==0 and times[-1]==8.3500164870623 and all(math.isfinite(v) for v in times) and all(u<v for u,v in zip(times,times[1:]))
 for i,(z,g) in enumerate(zip(fs,grids)):
  assert z['frame']==i and z['active_particles']==179208 and z['missing_particles']==0 and z['type_counts']=={'0':111708,'1':0,'2':0,'3':67500}
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='179208 3'
  vel=next(v for v in g.findall('Attribute') if v.get('Name').lower()=='velocity');assert vel.get('AttributeType')=='Vector' and vel.find('DataItem').get('Dimensions')=='179208 3'
 assert sorted(p.name for p in Path(t['source_provenance']['data_root']).glob('Part_*.bi4'))==[f'Part_{i:04d}.bi4' for i in range(836)]
 return {'refs':refs,'native':n,'audit':ar,'XMF':xr,'typed_report':t,'manifest':x,'frame_summary':fs,'times':times,'case_id':cid,'physical_case_id':pid,'masks':masks,'canonical':canonical,'legacy':legacy,'h5':h5,'h5sha':h5sha}
mode=sys.argv[1];assert mode in ['prepare','complete1194']
if mode=='complete1194' and not (F/'controller-result.json').exists():
 print('WAIT: same original1194 lacks terminal; no outputs written');raise SystemExit(0)
c=inspect_chain();refs=c['refs'];times=c['times']
if mode=='complete1194':
 cr=load(F/'controller-result.json');assert (cr['status'],cr['returncode'])==('completed',0)
 rp=Path(cr['actual_receipt']);rr=completed(ref(rp),c['case_id'],c['physical_case_id']);attempt=rp.parent
 refs['actual_render_receipt']=ref(rp);report=attempt/'render/paraview-full-animation-report.json';pub=attempt/'render/render-publish-receipt.json';r=load(report);pj=load(pub)
 refs['actual_render_report']=ref(report);refs['actual_render_publish_receipt']=ref(pub)
 assert rr['request_sha256']==sha(F/'enabled-full836-render-request.json')
 assert pj['status']=='published_after_atomic_rename' and pj['case_id']==c['case_id'] and pj['report_sha256_after_rebind']==sha(report)
 assert r['frames']==r['source_frames']==836 and r['frame_selection']==list(range(836)) and r['all_frames_rendered'] and not r['diagnostic_only']
 assert r['actual_times_preserved_exactly'] and r['native_identity_axis_preserved'] and r['nonfinite_active_states']==0 and r['source_h5_read_only']
 assert r['manifest_sha256']==sha(refs['actual_XMF_manifest']['path']) and r['input_manifest']==refs['actual_XMF_manifest']['path']
 assert r['xdmf_sha256_before']==r['xdmf_sha256_after']==sha(refs['actual_XMF_XML']['path']) and r['source_h5_sha256']==c['h5sha']
 assert rr['input_hashes_at_launch'][c['h5']]==rr['input_hashes_after_run'][c['h5']]==c['h5sha']
 ds=r['frame_diagnostics'];assert len(ds)==836 and [d['actual_time_s'] for d in ds]==times
 for i,d in enumerate(ds):
  assert d['frame']==i and d['active']==179208 and d['missing']==0 and d['identity_axis_preserved'] and d['finite_positions_active']
  assert set(d['finite_fields'])=={'density','mass','pressure','velocity'} and all(z['finite_active'] and z['nonfinite_active']==0 for z in d['finite_fields'].values())
 assert len(r['outputs']['contact_sheets'])==35 and sorted(p.name for p in Path(r['outputs']['frames_dir']).glob('frame_*.png'))==[f'frame_{i:04d}.png' for i in range(836)]
 O=H/'root_stage1_F3_AY0270_actual1194_full836_UID_N3_time_ownQI_original154_runtimeunknown_audit1166_XMF1193_true_parentQA_1387';assert not O.exists();O.mkdir()
 proof=O/'actual1194-full836-recovery-aware-QI-nativecanonical-typedlegacy-original154-unknown-previsual-proof.json'
 put(proof,{'schema':'ds02.main.F3.recovery-aware-own836-previsual-QI.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'actual_completed_metadata_evidence':refs,'frames':836,'particles':179208,'actual_initial_type_counts':{'fixed':111708,'moving':0,'floating':0,'fluid':67500},'actual_time_window_s':[times[0],times[-1]],'all836_uid_type_mk_finite_geometry_velocity_N3_and_actual_times_verified':True,'all_native_UIDs_active_each_frame':True,'native_request_condition_sha256':c['canonical'],'actual_converter_condition_sha256':c['legacy'],'scope_schema':'legacy-owner-scope.v0','actual_native_XMF_plan_field_namespaces':c['masks'],'original_typed154_runtime':{'status':'running','returncode_field_present':False,'returncode':None,'not_reclassified':True},'independent_artifact_audit1166_actual_completed0':True,'recovery_aware_XMF1193_actual_completed0':True,'original_OS_exit_zero_not_claimed':True,'genuine_parent_initial_QA_and_exact_initial_clone_verified':True,'full_native_filenames_stat_checked':True,'published_contacts':35,'delegated_requested_keys':[0,104,208,312,417,521,626,730,835],'visual_status':'pending delegated personal35contacts9keys','case_credit':0,'q_n_granted':False,'q_e_granted':False,'scientific_payload_IO':False})
 (O/'independent-review-source.py').write_bytes(Path(__file__).read_bytes());co=commit(list(O.iterdir())+[F/'controller-result.json'],'DS02: close AY0270 full836 integrity retaining original154 runtime unknown and independent recovery audit')
 print(json.dumps({'proof':ref(proof),'case_credit':0,'commit':co}));raise SystemExit(0)
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_288.json';cp=load(cpfile);assert cp['checkpoint']==288 and cp['stage1_visual_accepted_complete_independent_cases']==315
ip=root(1384)/'full336-current315-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile)
live=[]
for original,pid,start in [(1097,664604,'214297664'),(1194,666759,'214319277')]:
 pp=Path(f'/proc/{pid}');st=(pp/'stat').read_text().rsplit(')',1)[1].split();assert st[19]==start
 cmd=(pp/'cmdline').read_bytes().split(b'\0');assert cmd[0].endswith(b'/pvpython');out=Path(cmd[cmd.index(b'--output-dir')+1].decode());assert f'root{original}' in str(out)
 live.append({'original':original,'pid':pid,'startticks':start,'state':st[0],'private_frame_filename_stat_count':len(list((out/'frames').glob('frame_*.png'))),'private_PNG_payload_IO':False,'no_restart':True})
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(z['kind'] for z in ld['attempts'])
gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600
v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc)
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
for key,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][key]
O=H/'root_stage1_current315_nextF3_original1194_full836_audit1166_qualified_original154_runtimeunknown_true_parentQA_durableQI_1386';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_289.json'
assert not O.exists() and not np.exists() and not list(H.glob('root*_1387'));O.mkdir();entry=O/'after_original1194_terminal_recovery_aware_full836_own_QI.py';entry.write_bytes(Path(__file__).read_bytes())
proof=O/'next-original1194-actual836-recovery-aware-primary-runtime-and-durableQI-readiness.json'
put(proof,{'schema':'ds02.main.F3.original1194.recovery-aware-full836-QI-readiness.v1','at_utc':now.isoformat(),'case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'prior_previsual_scientific_dependency_review':ref(basep),'actual_upstream_metadata_evidence':refs,'native_request_condition_sha256':c['canonical'],'typed_legacy_scope_sha256':c['legacy'],'XMF_physical_condition_canonical_role':True,'actual_native_XMF_plan_field_namespaces':c['masks'],'original_typed154_status_running_no_returncode_not_reclassified':True,'independent_artifact_audit1166_actual_completed0_and_full836_835transitions_verified':True,'recovery_aware_XMF1193_actual_completed0':True,'genuine_parent_initial_QA_and_exact_initial_clone_verified':True,'actual_time_window_s':[times[0],times[-1]],'frames':836,'particles':179208,'native_part_filenames_stat_checked':True,'same_live_originals':live,'future_ownQI1387_unexecuted_and_SHA_unknown':True,'entry':ref(entry),'command':['python3','-B',str(entry),'complete1194'],'case_credit':0,'scientific_payload_IO':False,'new_jobs':0,'code_audit_followups':{'source195':'F2 full401 report/lifecycle/XML exact times, genuine QA scope, XMF runtime and P03 original unknown recovery certificate repair required; provisional source not consumed','source180':'F5 actual CLI future checkpoint support and actual full801 native/typed/XMF/render/bed/QA provenance gates required; provisional source not consumed'}})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp)
new.update(checkpoint=289,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: next original1194 real pvpython666759/start214319277 live, original154 running/no RC preserved; actual completed0 artifact audit1166 and recovery XMF1193 plus full836 metadata UID/N3/exact time and true parent QA/clone chain independently verified. Durable future ownQI1387 prepared only; F2original1097 same live, own1385 deferred until actual0/publication.',authorized_work_state='Active315/336. F5 ownQIs1377/1380 complete awaiting source214/215 personal reviews; F2original1097 and F3original1194 rendering. Source195/180 repairs active. No final48 or numerical precision claims from incomplete builders.')
new['actual_progress']['next_originalF3_1194_recovery_aware_durable836_QI']=ref(proof)
new['next_executable_tasks']=['Adopt source214/215 F5 personal visual evidence after source commits/read-only validators/primary refs/published PNG hashes; preserve own1377/1380 and count each physical case once.', 'Observe same F2original1097 PID664604/start214297664; after actual0/pub execute root1384 durable ownQI1385 once, delegate personal17contacts9keys with three fluid omissions retained.', 'Observe same F3original1194 PID666759/start214319277; after actual0/pub execute root1386 durable recovery-aware ownQI1387 once, delegate personal35contacts9keys preserving original154 running/no RC and independent audit1166 role.', 'Independently audit source195 and180 repaired complete delivery builders; then repair source176 F3 utility fulltime/runtime gates before actual final48 delivery.', 'Continue all336 original cases; close actual F2/F3/F5 final48 deliveries and full336 objective audit, keep Home500GiB/budgets/deadline unchanged.']
put(np,new);updated=copy.deepcopy(idx);updated.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,next_originalF3_1194_recovery_aware_durable836_QI=ref(proof))
put(O/'full336-current315-actual-final48-delivery-progress-index.json',updated);(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
co=commit(list(O.iterdir())+[np],'DS02: prepare AY0270 full836 recovery-aware integrity with true original154 runtime unknown')
print(json.dumps({'checkpoint':289,'accepted':315,'live':live,'future_ownQI_unexecuted':1387,'entry':ref(entry),'proof':ref(proof),'free_GiB':free,'CPUcoreh':cpu,'commit':co}))
