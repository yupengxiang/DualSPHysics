from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,hashlib
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003'
queue=sorted((H/'root_stage1_f6_actual_native563_last2_nested_FloatingInfo_state0_595').glob('*-state0-request.json'));assert len(queue)==2

def run(path):
 q=json.loads(path.read_text());p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(path)],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(path.read_bytes()).hexdigest();auditp=Path(q['actual_state0_omega_audit']);audit=json.loads(auditp.read_text()) if auditp.exists() else {};apass=audit.get('status')=='pass' and bool(audit.get('checks')) and all(audit['checks'].values());row={'request':str(path),'case_id':q['case_id'],'actual_receipt':str(rp) if rp.exists() else None,'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'actual_omega_audit_pass':apass,'actual_omega_audit':str(auditp) if audit else None,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
rows=[];failed=False;row=run(queue.pop(0));rows.append(row);failed=row['launcher_returncode']!=0 or row['status']!='completed' or row['returncode']!=0 or not row['actual_omega_audit_pass']
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while queue or active:
  while queue and len(active)<2 and not failed:p=queue.pop(0);active[pool.submit(run,p)]=p
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   p=active.pop(f)
   try:row=f.result()
   except Exception as e:row={'request':str(p),'launcher_returncode':1,'controller_error':str(e)}
   rows.append(row);failed=failed or row['launcher_returncode']!=0 or row.get('status')!='completed' or row.get('returncode')!=0 or not row.get('actual_omega_audit_pass',False)
result={'requested':2,'completed0':sum(r.get('status')=='completed' and r.get('returncode')==0 for r in rows),'actual_omega_pass_count':sum(r.get('actual_omega_audit_pass',False) for r in rows),'pending_held':len(queue),'first1_then_parallel_cap':2,'results':rows};p=Path(__file__).parent/'controller-result.json';assert not p.exists();p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
