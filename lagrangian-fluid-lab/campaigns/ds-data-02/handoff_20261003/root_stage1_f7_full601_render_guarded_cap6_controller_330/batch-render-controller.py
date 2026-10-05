from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003'
queue=sorted((H/'root_stage1_f7_actual_xmf327_sixteen_full601_render_329').glob('*-render-request.json'));assert len(queue)==16
def run(path):
 q=json.loads(path.read_text());assert q['source_only'] is False and q['disabled'] is False and q['launch_allowed'] is True and q['execution_allowed'] is True and q['root_review_required'] is False
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(path)],cwd=L,text=True,capture_output=True)
 row={'case_id':q['case_id'],'attempt_id':q['attempt_id'],'launcher_returncode':p.returncode,'launcher_output':p.stdout[-1500:],'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
rows=[];failed=False
with ThreadPoolExecutor(max_workers=6) as pool:
 active={}
 while queue or active:
  while queue and len(active)<6 and not failed:
   path=queue.pop(0);active[pool.submit(run,path)]=path
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for task in done:
   path=active.pop(task)
   try:row=task.result()
   except Exception as e:row={'request':str(path),'launcher_returncode':1,'controller_error':str(e)};print(json.dumps(row),flush=True)
   rows.append(row);failed=failed or row['launcher_returncode']!=0
print(json.dumps({'requests':16,'finished':len(rows),'successes':sum(r['launcher_returncode']==0 for r in rows),'pending_held_after_first_failure':len(queue),'parallel_cap':6,'arrays_read_by_controller':False}),flush=True)
raise SystemExit(1 if failed else 0)
