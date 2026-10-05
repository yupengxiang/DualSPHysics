from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import datetime,timezone
import runpy,subprocess,json,time
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');G=H/'root_stage1_f4_actualtyped533_full1201_normal_N3_XMF_547';P=L/'campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_098_stage1_f4_root530_typed_xmf_render_v1';prepare=runpy.run_path(str(G/'enable_actual_completed.py'))['prepare'];queue=sorted((P/'requests').glob('*-xmf-fresh098-disabled.request.json'));assert len(queue)==24;rows=[];index=0;failed=False

def run(p):
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True);rp=D/'families/F4'/q['case_id']/q['attempt_id']/'execution-receipt.json';a=json.loads(rp.read_text()) if rp.is_file() else {};row={'case_id':q['case_id'],'request':str(p),'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'launcher_output':r.stdout[-1400:],'launcher_error':r.stderr[-1400:]};print(json.dumps(row),flush=True);return row

def stop():return datetime.now(timezone.utc)>=datetime.fromisoformat('2026-10-14T07:23:48+00:00')
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  if stop():failed=True
  while index<len(queue) and not failed and len(active)<(2 if rows else 1):
   p=prepare(queue[index])
   if p is None:break
   active[pool.submit(run,p)]=p;index+=1
  if active:
   done,_=wait(active,timeout=10,return_when=FIRST_COMPLETED)
   for f in done:
    active.pop(f);r=f.result();rows.append(r)
    if r['launcher_returncode']!=0 or (r['status'],r['returncode'])!=('completed',0):failed=True
  elif index<len(queue) and not failed:time.sleep(10)
summary={'requested':24,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'first_failure_holds_pending':True,'waits_actual_fulltyped533_completed0_before_enabling_each_request':True,'results':rows};(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
