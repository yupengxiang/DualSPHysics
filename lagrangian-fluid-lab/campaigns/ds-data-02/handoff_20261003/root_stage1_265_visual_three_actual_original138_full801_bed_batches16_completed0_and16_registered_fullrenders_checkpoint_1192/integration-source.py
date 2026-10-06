from pathlib import Path
import json,hashlib,datetime,os,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text());root=lambda n:next(H.glob(f'root*_{n:03d}'))
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):
 with Path(p).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
cp_path=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_179.json';cp=load(cp_path);assert cp['stage1_visual_accepted_complete_independent_cases']==265 and len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==265
O=H/'root_stage1_265_visual_three_actual_original138_full801_bed_batches16_completed0_and16_registered_fullrenders_checkpoint_1192';O.mkdir(exist_ok=False)
beds=[]
for n,expected in [(1171,5),(1172,7),(1185,4)]:
 d=root(n);cfg=load(d/'controller-config.json');progress=load(d/'actual-progress.json');result=load(d/'controller-result.json');assert (result['status'],result['returncode'],result['actual_worker_completed0'])==('completed',0,expected)
 assert len(cfg['requests'])==len(progress['results'])==expected
 (O/f'Root{n}-completed-progress-frozen.json').write_bytes((d/'actual-progress.json').read_bytes())
 for qp in cfg['requests']:
  q=load(qp);ar=Path(q['attempt_root']);rp=ar/'execution-receipt.json';bp=ar/'audit-output/c082s1-full-event-bed-footprint-audit.json';r=load(rp);b=load(bp)
  assert (r['status'],r['returncode'])==('completed',0)
  assert r['request']['attempt_id']==q['attempt_id'] and r['request']['physical_case_id']==q['physical_case_id'] and b['bound_actual_inputs']['physical_case_id']==q['physical_case_id']
  assert b['scan']['frames_scanned']==len(b['frame_reports'])==801 and b['scan']['particle_axis_count']==194427 and b['scan']['initial_fluid_uid_count']==31658
  assert not b['source_arrays_modified'] and not b['source_arrays_dropped_or_masked']
  assert all(f['initial_fluid_uid_count']==f['current_valid_type3_fluid_count']==f['finite_position_current_fluid_count']==31658 and f['uid_tracking']['missing_initial_uid']['count']==0 and f['penetration']['one_dp']['count']==f['penetration']['two_dp']['count']==0 for f in b['frame_reports'])
  beds.append({'producer_root':n,'tag':q['tag'],'physical_case_id':q['physical_case_id'],'actual_request':ref(qp),'actual_receipt':ref(rp),'actual_report':ref(bp),'full801_UID_N3_time_and_scope_review_in_render_registration':True,'original_condition_top_alias_absent_preserved': 'physical_condition_sha256' not in q,'case_credit':0})
assert len(beds)==len({b['physical_case_id'] for b in beds})==16
render_numbers=[1173,1174,1175,1176,1177,1180,1181,1182,1183,1184,1186,1187,1188,1189,1190,1191];renders=[]
for n in render_numbers:
 d=root(n);cfg=load(d/'controller-config.json');qp=Path(cfg['request']);q=load(qp);lp=d/'controller-launch-process.json';v=load(lp);assert sha(qp)==v['request_sha256'] and sha(v['controller'])==v['controller_sha256'];assert q['expected_frames']==801 and q['expected_contact_sheets']==34 and q['expected_particles']==194427
 assert q['physical_case_id'] in {b['physical_case_id'] for b in beds}
 rec=Path(q['attempt_root'])/'execution-receipt.json';cr=d/'controller-result.json';s=None;actual=None
 if rec.exists():
  a=load(rec);actual={'status':a.get('status'),'returncode':a.get('returncode'),'receipt':ref(rec)}
 if cr.exists():
  z=load(cr);s={'controller_terminal_status':z['status'],'controller_terminal_returncode':z['returncode'],'controller_result':ref(cr)}
 else:
  stat=Path(f"/proc/{v['pid']}/stat");assert stat.exists();t=stat.read_text().split(') ',1)[1].split();assert t[0]!='Z' and str(t[19])==str(v['proc_start_ticks']);s={'same_actual_pid_live':v['pid'],'actual_proc_start_ticks':t[19],'proc_state':t[0]}
 proof=d/'actual-full801-bed-UID-footprint-times-and-scope-independent-review.json';p=load(proof);assert p['all801_UID_fluid31658_finite_and_footprint_checked'] and p['observed_counts_above_one_DP_and_two_DP_bins_zero'] and p['case_credit']==0
 renders.append({'root':n,'physical_case_id':q['physical_case_id'],'actual_launch':ref(lp),'full801_independent_metadata_review':ref(proof),'request':ref(qp),'observed_controller':s,'actual_worker_receipt':actual,'case_credit':0})
assert len(renders)==len({r['physical_case_id'] for r in renders})==16
put(O/'actual16-full801-bed0-and16-bound-original-fullrender-handles.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'beds':beds,'renders':renders,'main_scientific_payload_IO':False,'case_credit':0,'precision_not_implied':True})
err=root(1179)/'metadata-preflight-error-original-script-preserved.json';assert err.exists() and not (root(1179)/'controller-launch-process.json').exists();put(O/'prelaunch1179-original-failure-and-successor1184-alias-provenance.json',{'original_failed_preparation':ref(err),'old_bed1172_request_not_modified':True,'original_missing_top_condition_alias_preserved':True,'new_render1184_registration':ref(root(1184)/'registered-render-binding.json'),'new_render1184_launch':ref(root(1184)/'controller-launch-process.json'),'scientific_attempt_or_credit_for_failed_preparation1179':0})
for k,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][k]
assert sha(root(928)/'fair_CPU_dispatch.py')=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw);fs=os.statvfs('/home/jade');free=fs.f_bavail*fs.f_frsize/2**30;assert free>=500
cp.update(checkpoint=180,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(cp_path),predecessor_sha256=sha(cp_path),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600,cpu_core_hours_charged=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600,authorized_work_state='Active:265/336. Sixteen F5 full801 actual original138 bed audits completed0; all16 full801 render requests registered with own complete metadata evidence. F5 actual1147 and F2 actual1067 completed renders assigned personal delegated visual review. F3 source143 pre-adoption position metadata omission found: immutable143 preserved, agent preparing fresh144 successor; no science job launched for143. Original render wait handles preserved.',previous_goal_turn_classification='Progress: one F3 actual1103/fresh142 independently accepted265; source185 bed5/source157159 motherbed7/source186 bed4 actual full801 completed0;16 full801 original116023 renders registered/launched after own UID/N3/time/footprint/scope closure. Original prelaunch1179 KeyError preserved; new1184 derives canonical from actualbed/native with absent old alias unchanged. Failed output cleanup515.503GiB already independently verified; Home500GiB floor protected.')
cp['actual_progress']['sixteen_actual_full801_bed0_and_registered_renders']=ref(O/'actual16-full801-bed0-and16-bound-original-fullrender-handles.json');cp['actual_progress']['original1179_prelaunch_failure_and1184_successor']=ref(O/'prelaunch1179-original-failure-and-successor1184-alias-provenance.json');cp['source_agents'].update(production_recovery='fresh143 immutable final; prepare fresh144 position-metadata successor, preserve original154 unknown lifecycle and actual1166 audit role',f5_bed_recovery='fresh188 personal full801 M094T085 actual1147 visual; fresh187 actual48 stage census',f6_endpoint_initial_qa='fresh161 personal full401 F2RX049ROT105 actual1067 visual')
cp['next_executable_tasks']=['Independently adopt fresh188 actual1147 personal34contacts9keys ownfull801 review then credit one F5','Independently adopt fresh161 actual1067 personal17contacts9keys ownfull401 review then credit one F2 with actual UID losses disclosed','Adopt final fresh144 audit-aware XMF source successor only after position metadata contract closure; register CPU2 serial1 with original154 lifecycle unchanged','Preserve all16 registered F5 full801 render processes; terminal0 results get personal delegated visual review','Observe original Root951 lastF6 same launch identity; no duplicate/restart on fairwait']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_180.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[p for p in O.iterdir() if p.is_file()]+[H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_180.json']
for n in [1171,1172,1185,*render_numbers]:
 d=root(n)
 for name in ['actual-progress.json','controller-result.json','controller-launch-process.json']:
  if (d/name).exists():paths.append(d/name)
paths.extend(p for p in root(1179).iterdir() if p.is_file());rels=[str(p.relative_to(R)) for p in paths]
subprocess.run(['git','add','--',*rels],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint265 accepted and sixteen real full801 bed audits with bound render queue','--',*rels],cwd=R,check=True)
print({'checkpoint':180,'accepted':265,'actual_F5_beds_completed0':16,'bound_full801_renders':16,'Home_free_GiB':free,'cpu_coreh':cp['cpu_core_hours_charged'],'GPUh':cp['gpu_hours_charged'],'attempt_counts':cp['attempt_counts'],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
