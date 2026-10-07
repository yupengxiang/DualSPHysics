from pathlib import Path
import json, hashlib, subprocess, datetime, copy, collections, os
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.png','.py','.md'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def checked(e):
 if isinstance(e,str):e={'path':e}
 p=Path(e['path']);assert p.is_file()
 if e.get('sha256'):assert sha(p)==e['sha256'],str(p)
 if e.get('bytes') is not None:assert p.stat().st_size==e['bytes'],str(p)
 return ref(p)
commit='5bc95aa2b7144f43538d090fc5502c002500d799'
prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_171_f3_assigned_f6_final48_particle_rigid_47accepted_one_pending_delivery_v1')
P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==5
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names}
rv=subprocess.run(['python3','-B',str(P/'validate_fresh171.py')],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names}
for x in load(P/'package-manifest.json')['files']:
 assert (P/x['path']).stat().st_size==x['bytes'] and sha(P/x['path'])==x['sha256']
sp=P/'F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING.json';source=load(sp)
assert sha(sp)=='c58bfff055d0075dae2e59b73efdf1fdf9d2f3451e614cc8be7119f51dc19eba'
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_247.json';cp=load(cpfile)
assert cp['checkpoint']==247 and cp['stage1_visual_accepted_complete_independent_cases']==298 and cp['accepted_per_family']['F6']==47
ip=root(1320)/'full336-current298-actual-final48-delivery-progress-index.json';index=load(ip)
current={r['physical_case_id']:r for r in index['cases'] if r['family_id']=='F6'}
fixed=load(root(1313)/'F6-ACTUAL_FIRST24-PARTICLE-RIGID-JOINED-DELIVERY.json')
member=source['membership'];f8=member['frozen_first8_physical_case_ids'];f24=member['actual_first24_physical_case_ids'];f48=member['registered_final48_physical_case_ids']
assert len(set(f8))==8 and len(set(f24))==24 and len(set(f48))==48 and set(f8)<=set(f24)<=set(f48)==set(current)
assert f8==fixed['membership']['frozen_first8_physical_case_ids'] and f24==fixed['membership']['actual_first24_physical_case_ids']
baseline='F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE';pending='F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025'
verified=[];contacts=keys=navcount=0;unlisted=[];legacy=None
for row in source['rows']:
 pid=row['physical_case_id'];rig=row['rigid_motion_join'];a=row.get('accepted_visual_metadata')
 if a:
  assert a['accepted_decision']==current[pid]['accepted_decision'];checked(a['accepted_decision'])
  if a.get('independent_metadata_closure'):checked(a['independent_metadata_closure'])
  mp=Path(a['actual_xmf_manifest']['path']);checked(a['actual_xmf_manifest'])
 else:
  assert pid==pending and current[pid].get('accepted_decision') is None
  assert row['pending_visual_boundary']['accepted_decision'] is None and row['pending_visual_boundary']['primary_png_refs'] is None
  mp=Path(rig['native_time_source']['path']);assert ref(mp)==rig['native_time_source']
 m=load(mp);assert m['physical_case_id']==pid and m['frames']==241 and len(m['actual_time_s'])==241
 nativep=Path(m['native_receipt']);native=load(nativep);nq=native['request']
 assert native['status']=='completed' and native['returncode']==0
 for e in [rig['actual_export_report'],rig['actual_export_receipt']]:checked(e)
 export=load(rig['actual_export_report']['path']);receipt=load(rig['actual_export_receipt']['path'])
 assert receipt['status']=='completed' and receipt['returncode']==0
 csv=rig['official_rigid_motion_CSV'];assert Path(csv['path']).stat().st_size==csv['bytes_stat_verified']
 if pid==baseline:
  assert nq['case_id']==m['case_id']==row['case_id']=='F6_ANGULAR_RELEASE_DP025'
  assert 'physical_condition_sha256' not in nq and 'physical_case_id' not in nq
  assert m['rigid_state_provenance']['solver_receipt']==ref(nativep)
  assert export['source_sha256'][str(nativep)]==sha(nativep) and export['source_sha256'][csv['path']]==csv['sha256_producer_attested']
  assert export['all_actual_checks_passed'] and all(export['checks'].values())
  s=export['actual_rigid_history']['trajectory_summary']
  assert s['total_frames']==241 and s['full_12s_window_complete'] and s['all_motion_values_finite']
  assert abs(s['final_time_s']-m['actual_time_s'][-1])<=1e-6
  assert rig['legacy_Part_column_validation_field_present'] is False and rig['legacy_Part_unique_count'] is None
  legacy={'actual_native_receipt':ref(nativep),'actual_native_case_alias':nq['case_id'],'native_condition_field_present':False,'native_condition':None,'native_physical_case_id_field_present':False,'native_physical_case_id':None,'legacy_Part_column_validation_field_present':False,'legacy_Part_unique_count':None,'full_baseline_CSV_time_vector_independently_verified_this_main_join':False,'existing_actual_full241_checks_preserved':export['checks'],'official_endpoint_minus_particle_native_time_s':s['final_time_s']-m['actual_time_s'][-1],'endpoint_time_tolerance_s':1e-6}
  bindings={'historical_baseline_absence_and_time_boundary':legacy}
 else:
  assert export['native_receipt']['path']==str(nativep)
  assert export['native_receipt']['actual_sha256']==sha(nativep)==m['native_receipt_sha256']
  assert ref(nativep)==rig['actual_complete_native_receipt']
  assert nq['physical_case_id']==pid and nq['physical_condition_sha256']==rig['actual_native_condition_sha256']
  role=a['root1320_native_field_role_closure'] if a else row['root1320_native_field_role_closure']
  assert role['actual_complete_native_receipt']==ref(nativep) and role['actual_native_condition_sha256']==nq['physical_condition_sha256']
  parse=export['parse'];nt=parse['native_time_comparison']
  assert nt['native_times_s']==m['actual_time_s'] and nt['max_abs_delta_s']<=1e-6
  assert parse['part_values_observed']==list(range(241)) and parse['rigid_fields_finite_rows']==241
  assert export['output']['sha256']==csv['sha256_producer_attested']
  bindings={'same_actual_native_receipt_for_particle_and_rigid':ref(nativep),'native_condition_sha256_from_actual_solver':nq['physical_condition_sha256'],'all241_native_particle_and_rigid_worker_times_equal':True,'actual_official_times_not_resampled_and_within_1e6_tolerance':True,'actual_Part_indices':list(range(241))}
 out={'physical_case_id':pid,'actual_particle_manifest':ref(mp),'actual_fulltime_rigid_report':ref(rig['actual_export_report']['path']),'own_native_particle_rigid_bindings':bindings,'main_scientific_payload_IO':False,'new_case_credit':0,'new_visual_review':False}
 if a:
  xp=Path(a['actual_xmf_xml']['path']);xsha=sha(xp);assert xsha==m['xdmf_sha256']
  rr=load(a['actual_render_report']['path']);rc=load(a['actual_render_receipt']['path'])
  checked(a['actual_render_report']);checked(a['actual_render_receipt'])
  assert rc['status']=='completed' and rc['returncode']==0
  assert rr['frames']==rr['source_frames']==241 and rr['all_frames_rendered'] and not rr['diagnostic_only']
  assert rr['manifest_sha256']==sha(mp) and rr['source_h5_sha256']==m['source_h5_sha256']
  assert rr['xdmf']==str(xp) and rr['xdmf_sha256_before']==rr['xdmf_sha256_after']==xsha
  assert [x['frame'] for x in rr['frame_diagnostics']]==list(range(241))
  assert [x['actual_time_s'] for x in rr['frame_diagnostics']]==m['actual_time_s']
  for inputs in [rc['input_hashes_at_launch'],rc['input_hashes_after_run']]:
   assert inputs[str(mp)]==sha(mp) and inputs[str(xp)]==xsha and inputs[m['trajectory_h5']]==m['source_h5_sha256']
  expectedcontacts=rr['outputs']['contact_sheets']
  assert [x['path'] if isinstance(x,dict) else x for x in a['contact_png_refs']]==expectedcontacts and len(expectedcontacts)==11
  contactrefs=[checked(e) for e in a['contact_png_refs']]
  keyrefs=[checked(e) for e in a['key_png_refs']]
  contacts+=len(a['contact_png_refs']);keys+=len(a['key_png_refs'])
  if not a['key_png_refs']:unlisted.append(pid)
  framesdir=Path(rr['outputs']['frames_dir']);assert framesdir.is_relative_to(D)
  assert len(list(framesdir.glob('frame_*.png')))==241
  nav=[]
  for i in [0,1,30,60,90,120,150,180,210,240]:
   fp=framesdir/f'frame_{i:04d}.png';assert fp.is_file() and fp.stat().st_size>0
   nav.append({**ref(fp),'bytes':fp.stat().st_size,'frame':i,'actual_time_s':m['actual_time_s'][i],'role':'main_published_navigation_sidecar_not_new_personal_review'})
  navcount+=len(nav)
  out.update(accepted_visual_decision=checked(a['accepted_decision']),primary_XMF_XML=ref(xp),primary_render_report=checked(a['actual_render_report']),primary_render_receipt=checked(a['actual_render_receipt']),source_contacts_verified=len(a['contact_png_refs']),source_keys_verified=len(a['key_png_refs']),source_named_keys_unlisted_retained=not bool(a['key_png_refs']),source_contact_refs_without_declared_sha256=sum(isinstance(e,str) or not e.get('sha256') for e in a['contact_png_refs']),main_actual_published_contact_refs=contactrefs,main_actual_source_enumerated_key_refs=keyrefs,main_actual_published_navigation_previews=nav)
 else:
  out.update(accepted_visual_decision=None,primary_visual_render_report=None,primary_PNG_refs=None,visual_status='pending_no_credit',source_prior_live_snapshot_is_not_current_observation=True)
 verified.append(out)
assert len(verified)==48 and contacts==517 and keys==136 and navcount==470 and len(unlisted)==23 and legacy is not None
assert sum('accepted_visual_decision' in r and r['accepted_visual_decision'] is not None for r in verified)==47
# Read live process identity only; retain old source snapshot bytes.
proc=Path('/proc/4004579/stat');ptext=proc.read_text() if proc.exists() else None
parts=ptext[ptext.rfind(')')+2:].split() if ptext else []
live={'pid':4004579,'expected_startticks':207142232,'actual_startticks':int(parts[19]) if parts else None,'same_handle_live':bool(parts and int(parts[19])==207142232 and parts[0] not in ['Z','X']),'state':parts[0] if parts else None,'restart':False}
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);counts=collections.Counter(r['kind'] for r in ledger['attempts'])
gpu=sum(r.get('gpu_seconds',0) for r in ledger['charges'])/3600;cpu=sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])/3600
v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc)
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source171_F6_final48_particle_rigid_actual47_visual_bindings_470_published_navigation_keys_one_pending_no_credit_1321'
np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_248.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
vp=O/'source171-byte-exact-readonly-validator-main48-own-native-particle-rigid-and47-published-preview-proof.json'
put(vp,{'schema':'ds02.main.source171.final48-particle-rigid-primary-binding-proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'main_independent_bindings':verified,'actual47_new_particle_and_rigid_native_time_vectors_equal':True,'accepted_visual47':47,'pending_visual1':1,'contacts_SHA_verified':contacts,'source_enumerated_keys_SHA_verified':keys,'source23_unlisted_key_path_cases_preserved':unlisted,'main_published_navigation_previews470':navcount,'legacy_baseline_absence_and_time_boundary':legacy,'current_original951_handle_observation':live,'new_case_credit':0,'new_visual_review':False,'Q_N':0,'Q_E':0,'main_scientific_payload_IO':False})
product=copy.deepcopy(source);product.update(schema='ds02.main.F6.final48.particle-rigid-47accepted-one-pending-delivery.v1',status='actual47_visual_primary_bindings_verified_one_visual_pending',at_utc=now.isoformat(),source_original_exact_package=ref(R/prefix/sp.name),stable_predecessor_checkpoint=ref(cpfile),main_independent_verification=ref(vp));product['main_native_particle_rigid_and_published_navigation_sidecars']=verified
pp=O/'F6-FINAL48-PARTICLE-RIGID-47ACCEPTED-ONE-PENDING-DELIVERY.json';put(pp,product)
snapshot=O/'ledger-immutable-snapshot.json';snapshot.write_bytes(raw)
new=copy.deepcopy(cp);new.update(checkpoint=248,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snapshot),active_reservations=ledger['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: source171 actual final48 F6 particle/rigid directory independently joined; 47 accepted primary animations and published previews rebound, 470 navigation previews provided without new personal-review credit; last F6 visual remains pending. Actual1126 and1187 original801 renders and ownQI1315/1316 now complete.',authorized_work_state='Active298/336; F6 actual48 fulltime rigid and47 accepted particle animation delivery joined; finalF6 visual pending. F5 actual1126/1187 ownQI complete, fresh206/185 personal43PNG reviews running. Original1141 AY0640 and1135 AY0570 F3 full836 render automatically running; retain original shared fair2 capacity.')
new['actual_progress']['F6_final48_particle_rigid_47accepted_one_pending_delivery']=ref(pp)
new['actual_progress']['F6_final48_particle_rigid_47accepted_main_independent_binding']=ref(vp)
new['actual_progress']['actual1126_full801_own_QI']=ref(root(1315)/'actual1126-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json')
new['actual_progress']['actual1187_full801_own_QI']=ref(root(1316)/'actual1187-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json')
new['source_agents']['production_recovery']='fresh171 final48 F6 exact adopted, 47 primary bindings and last pending preserved; fresh172 F3 final48 current39accepted/ninepending actual directory assigned'
put(np,new);index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0)
index['actual_F6_final48_particle_rigid_47accepted_one_pending_delivery']=ref(pp)
for row in index['cases']:
 if row['family_id']=='F6':row['actual_F6_final48_particle_rigid_47accepted_one_pending_delivery']=ref(pp)
put(O/'full336-current298-actual-final48-delivery-progress-index.json',index)
(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
(O/'README.md').write_text('F6 注册48例实际粒子/刚体联合目录：47例已有个人视觉通过、最后1例视觉等待；所有48例完整官方刚体历史与本例XMF实际native来源一致。主进程核对47个新完整241时刻向量，核对47个已通过案例的原始动画及517 contact和136原始枚举key公开PNG，并另列470真实公开导航帧。23例原始key路径未枚举的事实保留，不新增视觉审核或案例。baseline保留实际native字段缺失、历史Part未独立验证及本次未逐行复核CSV时刻向量的边界。科学payload未读取或哈希，Q-N/Q-E=0。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','DS02: join finalF6 primary particle animations and fulltime rigid delivery preserving last visual pending','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':248,'accepted':298,'sourcecontacts':contacts,'sourcekeys':keys,'mainnavigationkeys':navcount,'original951':live,'product':ref(pp),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
