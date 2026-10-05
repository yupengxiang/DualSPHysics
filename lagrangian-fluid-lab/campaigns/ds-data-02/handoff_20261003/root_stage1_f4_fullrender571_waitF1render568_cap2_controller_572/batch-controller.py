from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
queue=sorted((H/'root_stage1_f4_actualfullXMF547_all24_Root023_render_571').glob('*-render-request.json'));assert len(queue)==24
def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True)
 rp=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.is_file() else {}
 row={'case_id':q['case_id'],'request':str(p),'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row
import time
prior=sorted((H/'root_stage1_f1_full401_actualXMF517_registered_rootowner_render_568').glob('*-render-request.json'));assert len(prior)==24
while True:
 states=[]
 for p in prior:
  v=json.loads(p.read_text());rp=D/'families'/v['family_id']/v['case_id']/v['attempt_id']/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};states.append(r)
 if any(r.get('status') in {'failed','timeout','cancelled'} for r in states):raise RuntimeError('Prior F1 full render failed; hold F4 queue pending Root review')
 if all((r.get('status'),r.get('returncode'))==('completed',0) for r in states):break
 time.sleep(5)
print(json.dumps({'F1_prior_full_render24_completed0':True,'global_render_cap2_handoff':'drained before F4 dispatch'}),flush=True)

rows=[];failed=False;index=0
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if row['launcher_returncode']!=0 or (row['status'],row['returncode'])!=('completed',0):failed=True
summary={'requested':24,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'first_failure_holds_pending':True,'results':rows}
(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
raise SystemExit(1 if failed else 0)
