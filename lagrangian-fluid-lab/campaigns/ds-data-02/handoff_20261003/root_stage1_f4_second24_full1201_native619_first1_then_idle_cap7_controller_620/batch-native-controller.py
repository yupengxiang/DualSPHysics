from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,hashlib
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families')
queue=sorted((H/'root_stage1_f4_actualGen604_basicQA616_full1201_native_second24_619').glob('*-native-request.json'));assert len(queue)==24
def run(path):
 q=json.loads(path.read_text());assert not q['disabled'] and not q['source_only'] and q['execution_allowed'] and q['launch_owner']=='root'
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(path)],cwd=L,text=True,capture_output=True)
 rp=D/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
 row={'case_id':q['case_id'],'request':str(path),'actual_receipt':str(rp) if rp.exists() else None,'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'launcher_output':p.stdout[-1500:],'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
rows=[];failed=False
first=queue[0];queue.remove(first);row=run(first);rows.append(row);failed=(row['launcher_returncode']!=0 or row['status']!='completed' or row['returncode']!=0)
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while queue or active:
  while queue and len(active)<7 and not failed:
   p=queue.pop(0);active[pool.submit(run,p)]=p
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   p=active.pop(f)
   try:row=f.result()
   except Exception as e:row={'request':str(p),'launcher_returncode':1,'controller_error':str(e)};print(json.dumps(row),flush=True)
   rows.append(row);failed=failed or row['launcher_returncode']!=0 or row.get('status')!='completed' or row.get('returncode')!=0
result={'requested':24,'finished':len(rows),'completed0':sum(r.get('status')=='completed' and r.get('returncode')==0 for r in rows),'pending_held':len(queue),'first1_then_parallel_cap':7,'shared_live_UUID_lease_protects_foreign_processes':True,'results':rows};out=Path(__file__).parent/'controller-result.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
