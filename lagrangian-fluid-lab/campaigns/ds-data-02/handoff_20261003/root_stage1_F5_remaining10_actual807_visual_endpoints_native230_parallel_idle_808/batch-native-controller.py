from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,subprocess,time,sys,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=Path(__file__).parent;sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text())
def run(qp):
 q=load(qp)
 while True:
  snap=rt.inventory();leased={json.loads(p.read_text())['uuid'] for p in (D/'leases').glob('*.json')}
  try:gpu.choose_gpu(snap,leased,4096);break
  except RuntimeError:time.sleep(3)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),qp],cwd=L,capture_output=True,text=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(Path(qp).read_bytes()).hexdigest();row={'request':qp,'physical_case_id':q['physical_case_id'],'actual_receipt':str(rp),'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'native_saved_frame_file_count':len(list((Path(q['attempt_root'])/'solver_output/data').glob('Part_*.bi4'))),'independent_case_increment':0,'launcher_error':p.stderr[-2000:]};row['actual_native_pass']=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and row['native_saved_frame_file_count']==801;print(json.dumps(row),flush=True);return row
qs=load(O/'dispatch-config.json')['requests'];rows=[run(qs[0])];failed=not rows[0]['actual_native_pass'];index=1
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<7 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_native_pass']:failed=True
result={'requested':10,'completed0':sum((x['status'],x['returncode'])==('completed',0) for x in rows),'actual_full801_native_pass_count':sum(x['actual_native_pass'] for x in rows),'pending_held':len(qs)-index,'results':rows,'maximum_parallel_jobs':7,'independent_case_increment':0};(O/'controller-result.json').write_text(json.dumps(result,indent=2)+'\n');raise SystemExit(1 if failed else 0)
