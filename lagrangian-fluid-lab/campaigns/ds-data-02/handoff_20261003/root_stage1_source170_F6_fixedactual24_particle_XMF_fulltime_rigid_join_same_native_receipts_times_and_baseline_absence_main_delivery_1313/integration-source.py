from pathlib import Path
import json,hashlib,subprocess,datetime,copy,collections,os
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
commit='236167309bb00dd1f601c242483e568fb5ada142';prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_170_f3_assigned_f6_actual24_particle_rigid_joined_delivery_v1');P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==4
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};rv=subprocess.run(['python3','-B',str(P/'validate_fresh170.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
package=load(P/'metadata/package-manifest.json')
for r in package['files']:assert sha(W/r['path'])==r['sha256'] and (W/r['path']).stat().st_size==r['bytes']
sp=P/'metadata/f6-first24-particle-rigid-joined-delivery.json';source=load(sp);assert sha(sp)=='682cb2c2f6b79c618db7228a65ef4af43fad86e366cadd914141b8992a2e6b40'
frozen=source['membership']['frozen_first8_physical_case_ids'];first24=source['membership']['actual_first24_physical_case_ids'];final48=source['membership']['registered_final48_physical_case_ids'];assert len(set(frozen))==8 and len(set(first24))==24 and len(set(final48))==48 and set(frozen)<=set(first24)<=set(final48)
verified=[];contacts=0;keys=0;legacy=None
for row in source['rows']:
 a=row['particle_dynamic_xmf_and_visual_refs'];rig=row['rigid_motion_join'];pid=row['physical_case_id'];mp=Path(a['actual_xmf_manifest']['path']);m=load(mp);rr=load(a['actual_render_report']['ref']['path'])
 for e in [a['accepted_decision'],a['actual_xmf_manifest'],a['actual_xmf_xml'],a['actual_render_report']['ref']]+a['contact_png_refs']+a['key_png_refs']:
  assert sha(e['path'])==e['sha256'] and Path(e['path']).stat().st_size==e['bytes']
 contacts+=len(a['contact_png_refs']);keys+=len(a['key_png_refs'])
 assert m['frames']==rr['frames']==rr['source_frames']==241 and m['physical_case_id']==pid
 assert rr['all_frames_rendered'] and not rr['diagnostic_only'] and rr['manifest_sha256']==sha(mp)
 assert rr['source_h5_sha256']==m['source_h5_sha256'] and sha(a['actual_xmf_xml']['path'])==m['xdmf_sha256']
 nativep=Path(m['native_receipt']);native=load(nativep);assert native['status']=='completed' and native['returncode']==0
 export=load(rig['actual_export_report']['path']);receipt=load(rig['actual_export_receipt']['path']);assert receipt['status']=='completed' and receipt['returncode']==0
 for e in [rig['actual_export_report'],rig['actual_export_receipt']]:assert ref(e['path'])==e
 csv=rig['official_rigid_motion_CSV'];assert Path(csv['path']).stat().st_size==csv['bytes_stat_verified'];nq=native['request']
 if pid=='F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE':
  assert nq['case_id']==row['case_id']=='F6_ANGULAR_RELEASE_DP025' and m['rigid_state_provenance']['solver_receipt']==ref(nativep)
  assert export['source_sha256'][str(nativep)]==sha(nativep) and export['source_sha256'][csv['path']]==csv['sha256_producer_attested']
  assert export['all_actual_checks_passed'] and all(export['checks'].values())
  summary=export['actual_rigid_history']['trajectory_summary'];assert summary['total_frames']==241 and summary['full_12s_window_complete'] and summary['all_motion_values_finite'] and abs(summary['final_time_s']-m['actual_time_s'][-1])<=1e-6
  assert rig['legacy_Part_column_validation_field_present'] is False and rig['legacy_Part_unique_count'] is None
  legacy={'native_receipt':ref(nativep),'actual_native_condition_field_present':'physical_condition_sha256' in nq,'actual_native_condition_value':nq.get('physical_condition_sha256'),'actual_native_physical_id_field_present':'physical_case_id' in nq,'actual_native_physical_id_value':nq.get('physical_case_id'),'alias':nq['case_id'],'full_native_time_vector_match_to_CSV_independently_verified_this_main_join':False,'existing_full_history_checks_preserved':export['checks'],'Part_independent_validation':False,'Part_unique_count':None,'official_endpoint_minus_particle_native_time_s':summary['final_time_s']-m['actual_time_s'][-1],'endpoint_time_tolerance_s':1e-6}
  extras={'historical_baseline_role_and_absence':legacy}
 else:
  assert export['native_receipt']['path']==str(nativep) and export['native_receipt']['actual_sha256']==sha(nativep)==m['native_receipt_sha256']
  assert nq['physical_case_id']==pid and nq['physical_condition_sha256']==rig['actual_native_condition_sha256']
  assert ref(nativep)==rig['actual_complete_native_receipt']
  parse=export['parse'];assert parse['native_time_comparison']['native_times_s']==m['actual_time_s'] and parse['part_values_observed']==list(range(241)) and parse['rigid_fields_finite_rows']==241
  assert parse['native_time_comparison']['max_abs_delta_s']<=1e-6 and export['output']['sha256']==csv['sha256_producer_attested']
  extras={'native_condition_from_actual_solver_receipt':nq['physical_condition_sha256'],'same_native_receipt_for_particle_and_rigid':ref(nativep),'all241_native_times_exactly_same_particle_manifest_and_rigid_worker_input':True,'official_motion_times_within_explicit_1e6_sec_tolerance':True}
 verified.append({'physical_case_id':pid,'primary_particle_manifest':ref(mp),'accepted_visual_decision':ref(a['accepted_decision']['path']),'actual_fulltime_rigid_report':ref(rig['actual_export_report']['path']),'own_particle_rigid_bindings':extras,'contact_PNGs_verified':len(a['contact_png_refs']),'key_PNGs_verified':len(a['key_png_refs']),'main_scientific_payload_IO':False})
assert len(verified)==24 and legacy is not None
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_241.json';cp=load(cpfile);assert cp['checkpoint']==241 and cp['stage1_visual_accepted_complete_independent_cases']==295
ip=root(1312)/'full336-current295-actual-final48-delivery-progress-index.json';index=load(ip);assert len(index['cases'])==336
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);counts=collections.Counter(r['kind'] for r in ledger['attempts']);gpu=sum(r.get('gpu_seconds',0) for r in ledger['charges'])/3600;cpu=sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])/3600;v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc);assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source170_F6_fixedactual24_particle_XMF_fulltime_rigid_join_same_native_receipts_times_and_baseline_absence_main_delivery_1313';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_242.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
vp=O/'source170-byte-exact-readonly-validator-and-main24-same-native-particle-rigid-proof.json';put(vp,{'schema':'ds02.main.source170.actual-first24-joined-proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'main_independent_bindings':verified,'all23_new_full241_native_time_vectors_match_particle_manifests':True,'legacy_baseline_actual_native_fields_absent_retained':legacy,'primary_contacts':contacts,'primary_keys':keys,'new_case_credit':0,'new_visual_review':False,'Q_N':0,'Q_E':0,'main_scientific_payload_IO':False})
product=copy.deepcopy(source);product.update(schema='ds02.main.F6.fixedactual24.particle-rigid-joined-delivery.v1',status='completed_actual_same_native_particle_rigid_join_metadata_verified',at_utc=now.isoformat(),source_original_exact_package=ref(R/prefix/'metadata/f6-first24-particle-rigid-joined-delivery.json'),stable_predecessor_checkpoint=ref(cpfile),main_independent_verification=ref(vp));product['main_native_particle_rigid_binding_sidecars']=verified;product['legacy_baseline_actual_native_fields_and_time_certification_boundary']=legacy
pp=O/'F6-ACTUAL_FIRST24-PARTICLE-RIGID-JOINED-DELIVERY.json';put(pp,product);snapshot=O/'ledger-immutable-snapshot.json';snapshot.write_bytes(raw)
new=copy.deepcopy(cp);new.update(checkpoint=242,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snapshot),active_reservations=ledger['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: current source169 full48 rigid metadata closure and failed-output retention recorded in cp241; actual1132 originalfull401 complete and ownQI1307 verified. Source170 fixedF6actual24 particle/XMF with fulltime rigid CSV joined and main separately verifies same native receipts, 23new full241 native time vectors and all primary published previews; legacy native scope/physical-id and Part/time-vector certification gaps retained.',authorized_work_state='Active295/336,41 visual pending; F6fixedactual24 particle+rigid joined actual delivery complete; original1132 actualF2 own401QI1307 ready for fresh205, original1110 approaches publication; fresh183 actualF5 review being finalized.')
new['actual_progress']['F6_fixedactual24_particle_rigid_joined_delivery']=ref(pp);new['actual_progress']['F6_fixedactual24_particle_rigid_joined_independent_proof']=ref(vp);new['actual_progress']['actual1132_full401_own_QI']=ref(root(1307)/'actual1132-full401-independent-UID-N3-time-scope-QI-proof.json');new['source_agents']['production_recovery']='fresh170 complete and exactadopted; actual fixed24 F6 particle/rigid main joined product delivered; next source task to be assigned'
put(np,new);index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0);index['actual_F6_first24_particle_rigid_joined_delivery']=ref(pp)
for r in index['cases']:
 if r['physical_case_id'] in first24:r['actual_F6_first24_particle_rigid_joined_delivery']=ref(pp)
put(O/'full336-current295-actual-final48-delivery-progress-index.json',index);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());(O/'README.md').write_text('固定 F6 actual-first24 联合交付：每例自身粒子动态 XMF、已有视觉证据和完整官方刚体 CSV。主进程核对同一实际求解收据，23 个新导出的241原生时刻向量与粒子XMF一致；baseline保留历史字段缺失、Part未独立验证及本次未逐行复核CSV时刻的限制。8⊂24⊂48，不增加案例或精度信用。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: deliver fixedF6-first24 joined particle and fulltime rigid histories','--',*paths],cwd=R,check=True);print({'checkpoint':242,'accepted':295,'joined24':24,'contacts':contacts,'keys':keys,'baseline_native_field_absence':legacy,'product':ref(pp),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
