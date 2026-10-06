from pathlib import Path
import json,fcntl,subprocess,time,shutil,sys,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
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
def run(qp):
 assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==cfg['request_sha256'][qp]
 (stdout,stderr),rc=dispatch(qp);q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((rp.parent/'solver_output/data').glob('Part_*.bi4')));passed=rc==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==801
 return {'tag':q['source_condition']['tag'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':rc,'native_saved_frame_file_count':frames,'actual_full801_native_pass':passed,'stdout_tail':stdout[-1500:],'stderr_tail':stderr[-1500:],'case_credit':0}
with ThreadPoolExecutor(max_workers=7) as pool:
 pending={pool.submit(run,qp):qp for qp in cfg['requests']}
 for f in as_completed(pending):
  z=f.result();results.append(z);(O/'actual-progress.json').write_text(json.dumps({'results':results,'not_submitted_or_running':len(cfg['requests'])-len(results),'case_credit':0},indent=2)+'\n');print(json.dumps(z),flush=True)
(O/'controller-result.json').write_text(json.dumps({'requested':len(cfg['requests']),'results':results,'actual_native_completed0':sum(x['actual_full801_native_pass'] for x in results),'case_credit':0},indent=2)+'\n')
raise SystemExit(0 if len(results)==len(cfg['requests']) and all(x['actual_full801_native_pass'] for x in results) else 1)
