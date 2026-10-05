from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003'
a=sorted((H/'root_stage1_f1_actual_native299_qa307_eight_typed_321').glob('*-typed-request.json'));b=sorted((H/'root_stage1_f7_actual_native313_sixteen_full601_typed_322').glob('*-typed-request.json'));assert len(a)==8 and len(b)==16
requests=[]
for i in range(16):
 if i<len(a):requests.append(a[i])
 requests.append(b[i])
def run(path):
 q=json.loads(path.read_text());p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(path)],cwd=L,text=True,capture_output=True)
 row={'family_id':q['family_id'],'case_id':q['case_id'],'attempt_id':q['attempt_id'],'launcher_returncode':p.returncode,'launcher_output':p.stdout[-1800:],'launcher_error':p.stderr[-1800:]}
 print(json.dumps(row),flush=True);return row
rows=[]
with ThreadPoolExecutor(max_workers=2) as pool:
 for task in as_completed([pool.submit(run,p) for p in requests]):rows.append(task.result())
print(json.dumps({'registered_conversion_requests':24,'launcher_successes':sum(r['launcher_returncode']==0 for r in rows),'parallel_controller_cap':2,'arrays_read_by_controller':False,'visual_credit':0}),flush=True)
raise SystemExit(0 if all(r['launcher_returncode']==0 for r in rows) else 1)
