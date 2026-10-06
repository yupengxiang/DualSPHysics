from pathlib import Path
import json,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));O=H/'root_stage1_F3_actual884_remaining9_same_science_fair_native230_oneGPU_10GiB_headroom2_948';O.mkdir(exist_ok=True);(O/'requests').mkdir(exist_ok=True);assert not list((O/'requests').iterdir());load=lambda p:json.loads(Path(p).read_text());put=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n')
def sha(p):
 p=Path(p);assert p.suffix.lower() not in ['.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz'];return hashlib.sha256(p.read_bytes()).hexdigest()
proof=root(947)/'metadata-only-conversion-waiters-retirement-proof.json';assert load(proof)['metadata_retired']==2 and load(proof)['completed_native0_preserved']==15;alias=root(947)/'metadata-only-native-waiters-retirement-proof.json';alias.write_bytes(proof.read_bytes())
controller=O/'fair-native-controller.py';controller.write_text('''from pathlib import Path
import json,fcntl,subprocess,time,shutil,sys,hashlib
O=Path(__file__).parent;cfg=json.loads((O/'controller-config.json').read_text());R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(next(H.glob('root*_134')))];import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text());launch=Path(cfg['native230_launch']);assert hashlib.sha256(launch.read_bytes()).hexdigest()==cfg['native230_sha256'];results=[]
def dispatch(qp):
 q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';assert not Path(q['attempt_root']).exists();assert q['kind']=='qualification' and q['cpu_threads']==2 and q['estimated_storage_bytes']==10*1024**3
 while True:
  admitted=False
  with (D/'runtime/stage1-fullnative-native-registration.lock').open('a') as lock:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:pass
   else:
    ledger=load(D/'runtime/resource-ledger.json');assert ledger['limits']['home_min_free_bytes']>=500*1024**3;res=ledger['reservations'];cpu=sum(x.get('cpu_threads',0) for x in res);reserved=sum(x.get('new_storage_bytes',0) for x in res);fit=cpu+q['cpu_threads']+2<=64 and shutil.disk_usage('/home/jade').free-reserved-q['estimated_storage_bytes']-2*1024**3>=ledger['limits']['home_min_free_bytes'];leased=set()
    if fit:
     for lp in (D/'leases').glob('*.json'):
      try:leased.add(load(lp)['uuid'])
      except FileNotFoundError:continue
     try:gpu.choose_gpu(rt.inventory(),leased,q['estimated_peak_gpu_mib'])
     except RuntimeError:fit=False
    if fit:
     assert not Path(q['attempt_root']).exists();p=subprocess.Popen([str(L/'.venv/bin/python'),str(launch),str(qp)],cwd=L,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);admitted=True
     while p.poll() is None:
      if rp.exists() and load(rp).get('status')=='running':break
      time.sleep(.2)
    fcntl.flock(lock,fcntl.LOCK_UN)
  if admitted:return p.communicate(),p.returncode
  time.sleep(3)
for qp in cfg['requests']:
 (stdout,stderr),rc=dispatch(qp);q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((rp.parent/'solver_output/data').glob('Part_*.bi4')));passed=rc==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==836;row={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':rc,'native_saved_frame_file_count':frames,'actual_full836_native_pass':passed,'stdout_tail':stdout[-1500:],'stderr_tail':stderr[-1500:],'case_credit':0};results.append(row);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted':len(cfg['requests'])-len(results),'case_credit':0},indent=2)+'\\n');print(json.dumps(row),flush=True)
 if not passed:break
(O/'controller-result.json').write_text(json.dumps({'requested':9,'results':results,'actual_native_completed0':sum(x['actual_full836_native_pass'] for x in results),'case_credit':0},indent=2)+'\\n');raise SystemExit(0 if len(results)==9 and all(x['actual_full836_native_pass'] for x in results) else 1)
''');compile(controller.read_text(),str(controller),'exec');qs=[];pre=[]
for oldp in sorted((root(884)/'requests').glob('*native-request.json')):
 old=load(oldp);rp=Path(old['attempt_root'])/'execution-receipt.json'
 if rp.exists():rr=load(rp);assert (rr['status'],rr['returncode'])==('completed',0);continue
 assert not Path(old['attempt_root']).exists();assert old['kind']=='qualification' and old['cpu_threads']==2 and old['estimated_storage_bytes']==10*1024**3 and old['expected_saved_frames']==836;md=old['input_sha256'].copy()
 for name,dig in md.items():
  p=Path(name);assert p.is_file()
  if p.suffix.lower() not in ['.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz']:assert sha(p)==dig,(name,'metadata changed')
 for p in [oldp,controller,alias]:md[str(p)]=sha(p)
 for name in [old['gencase_receipt'],old['actual_preparation_receipt']['path']]:r=load(name);assert (r['status'],r['returncode'])==('completed',0)
 q=old.copy();aid=old['attempt_id']+'-fair-native-oneGPU-headroom2-root948';ar=D/'families/F3'/old['case_id']/aid;assert not ar.exists();q.update(attempt_id=aid,attempt_root=str(ar),input_files=sorted(md),input_sha256=md,root_original884_unlaunched_request={'path':str(oldp),'sha256':sha(oldp)},root_native_metadata_admission_headroom_bytes=2*1024**3,root_original10GiB_storage_estimate_unchanged=True,root_previous_native15_completed0_preserved=True);qp=O/'requests'/(q['case_id']+'-native-request.json');put(qp,q);qs.append(str(qp));pre.append({'request':str(qp),'request_sha256':sha(qp),'physical_case_id':q['physical_case_id'],'science_command_identical_to884':q['command']==old['command'],'original_storage_GiB':10,'only_metadata_headroom_new_GiB':2,'science_payload_main_IO':False,'case_credit':0})
assert len(qs)==9;launch=root(230)/'launch.py';assert sha(launch)=='7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e';put(O/'controller-config.json',{'requests':qs,'native230_launch':str(launch),'native230_sha256':sha(launch),'at_most_one_own_solver_GPU':True,'Home_floor500GiB_preserved':True,'source15_completed0_not_rerun':True,'case_credit':0});put(O/'metadata-only-nine-preflight.json',{'requests':pre,'native947_metadata_retirement':{'path':str(alias),'sha256':sha(alias)},'original_solver_gen_geometry_forcing_8p35s_tout01_836frames_unchanged':True,'Home10GiB_reservation_unchanged':True,'admission_headroom16_to2_is_only_new_controller_metadata':True,'CPU64_cap_and_Gen_lease_foreign_process_protection_native230_preserved':True,'science_payload_main_IO':False,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print({'enabled_native':9,'at_most_one_own_GPU':True,'science_changed':False,'Home500_floor':True})
