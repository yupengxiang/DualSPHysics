from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
queue=sorted((H/'root_stage1_f6_actual_native229_state238_remaining4_typed_392').glob('*-typed-request.json'));assert len(queue)==4
assert not json.loads((D/'runtime/resource-ledger.json').read_text())['reservations'], 'Await previous registered jobs terminal; global NVMe cap2'
def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True)
 rp=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.is_file() else {}
 row={'case_id':q['case_id'],'request':str(p),'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row
rows=[];failed=False;index=0
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if row['launcher_returncode']!=0 or (row['status'],row['returncode'])!=('completed',0):failed=True
summary={'requested':4,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'first_failure_holds_pending':True,'results':rows}
(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
raise SystemExit(1 if failed else 0)
