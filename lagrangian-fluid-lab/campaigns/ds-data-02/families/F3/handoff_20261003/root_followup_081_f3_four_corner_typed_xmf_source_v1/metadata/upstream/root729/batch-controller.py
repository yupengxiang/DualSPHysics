from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,time
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_four_actual706_native_corners_full836_NVMe_typed_728')
queue=sorted(O.glob('*-typed-request.json'));assert len(queue)==4
u=json.loads(Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_XMF709_wait_native707_actual_list_reservations_controller_repair_718/controller-result.json').read_text());assert u['completed0']==u['finished']==17
while True:
 ledger=json.loads((D/'runtime/resource-ledger.json').read_text());reserved=sum(v.get('cpu_threads',0) for v in ledger['reservations'])
 if reserved+4<=64:break
 time.sleep(10)
def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(L/'campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True);a=D/'families'/q['family_id']/q['case_id']/q['attempt_id'];rp=a/'execution-receipt.json';receipt=json.loads(rp.read_text()) if rp.exists() else {};ok=r.returncode==0 and (receipt.get('status'),receipt.get('returncode'))==('completed',0)
 if ok:
  c=json.loads((a/'conversion-report.json').read_text());assert c['conversion_status']=='completed' and c['frames']==836 and c['particles']==179208 and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'];assert c['hash_scopes']['physical_condition_sha256']==q['physical_condition_sha256'];assert c['time_evidence']['strictly_increasing'];assert receipt['input_hashes_at_launch']==receipt['input_hashes_after_run']
 row={'case_id':q['case_id'],'request':str(p),'actual_receipt':str(rp),'launcher_returncode':r.returncode,'status':receipt.get('status'),'returncode':receipt.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row
rows=[run(queue[0])];failed=rows[0]['launcher_returncode']!=0 or (rows[0]['status'],rows[0]['returncode'])!=('completed',0);index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if row['launcher_returncode']!=0 or (row['status'],row['returncode'])!=('completed',0):failed=True
summary={'requested':4,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) and r['launcher_returncode']==0 for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'results':rows};(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
