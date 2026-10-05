from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
queue=sorted((H/'root_stage1_f5_actual_typed590_full801_control_dynamic_audit120_hashbinding_repair_677').glob('*-control-dynamic-audit-request.json'));assert len(queue)==16
def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True)
 rp=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.is_file() else {}
 row={'case_id':q['case_id'],'request':str(p),'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row
rows=[run(queue[0])];failed=rows[0]['launcher_returncode']!=0 or (rows[0]['status'],rows[0]['returncode'])!=('completed',0);index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if row['launcher_returncode']!=0 or (row['status'],row['returncode'])!=('completed',0):failed=True
summary={'requested':16,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'first_failure_holds_pending':True,'results':rows}
(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
raise SystemExit(1 if failed else 0)
