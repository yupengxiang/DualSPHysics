from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import sys,json,subprocess,time,hashlib
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
queue=sorted((H/'root_stage1_f5_currenttwo_actual_short51_review_full801_native_575').glob('*-native-request.json'));assert len(queue)==2
priorqs=sorted((H/'root_stage1_f6_actualGen539_QA558_full241_native24_563').glob('*-native-request.json'));assert len(priorqs)==24
priorpaths=[Path(json.loads(p.read_text())['attempt_root'])/'execution-receipt.json' for p in priorqs]
def capacity():
 # Wait until F6 has launched its last wave, then use truly idle shared capacity.
 if not all(p.exists() for p in priorpaths):return False
 snap=rt.inventory();leased={json.loads(p.read_text())['uuid'] for p in (D/'leases').glob('*.json')}
 try:gpu.choose_gpu(snap,leased,4096)
 except RuntimeError:return False
 return True
def run(path):
 q=json.loads(path.read_text());p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(path)],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(path.read_bytes()).hexdigest();row={'request':str(path),'case_id':q['physical_case_id'],'actual_receipt':str(rp) if rp.exists() else None,'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
rows=[];failed=False
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while queue or active:
  if queue and len(active)<2 and not failed and capacity():
   p=queue.pop(0);active[pool.submit(run,p)]=p
   time.sleep(3) # Allow real launcher lease acquisition before considering next capacity.
  if active:
   done,_=wait(active,timeout=10,return_when=FIRST_COMPLETED)
   for f in done:
    p=active.pop(f)
    try:row=f.result()
    except Exception as e:row={'request':str(p),'launcher_returncode':1,'controller_error':str(e)}
    rows.append(row);failed=failed or row['launcher_returncode']!=0 or row.get('status')!='completed' or row.get('returncode')!=0
  elif failed:break
  else:time.sleep(10)
result={'requested':2,'completed0':sum(r.get('status')=='completed' and r.get('returncode')==0 for r in rows),'pending_held':len(queue),'actual_GPU_idle_and_lease_wait_before_dispatch':True,'parallel_cap':2,'results':rows};p=Path(__file__).parent/'controller-result.json';assert not p.exists();p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);raise SystemExit(1 if failed else 0)
