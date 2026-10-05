from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_f7_actualQA310_sixteen_full601_native_313'
requests=sorted(O.glob('*-native-request.json'));assert len(requests)==16
def run(path):
 q=json.loads(path.read_text());p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(path)],cwd=L,text=True,capture_output=True)
 return {'case_id':q['case_id'],'attempt_id':q['attempt_id'],'launcher_returncode':p.returncode,'launcher_output':p.stdout[-1400:],'launcher_error':p.stderr[-1400:]}
rows=[]
with ThreadPoolExecutor(max_workers=7) as pool:
 for task in as_completed([pool.submit(run,p) for p in requests]):
  row=task.result();rows.append(row);print(json.dumps(row),flush=True)
print(json.dumps({'registered_solver_requests':16,'launcher_successes':sum(r['launcher_returncode']==0 for r in rows),'parallel_controller_cap':7,'native_output_and_visual_acceptance_not_inferred':True}),flush=True)
raise SystemExit(0 if all(r['launcher_returncode']==0 for r in rows) else 1)
