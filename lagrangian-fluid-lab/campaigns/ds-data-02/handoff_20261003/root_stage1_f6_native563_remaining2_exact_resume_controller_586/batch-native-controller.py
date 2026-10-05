from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,json,hashlib
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003'
review=H/'root_stage1_f6_native564_controller_exit143_completed22_pending2_review_585/actual-root-controller-exit143-native22-preserved-pending2-review.json';queue=[Path(p) for p in json.loads(review.read_text())['pending_exact_requests_never_registered']];assert len(queue)==2
for p in queue:q=json.loads(p.read_text());assert not Path(q['attempt_root']).exists()
def run(p):
 q=json.loads(p.read_text());pr=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(p)],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=json.loads(rp.read_text()) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(p.read_bytes()).hexdigest();row={'request':str(p),'case_id':q['case_id'],'actual_receipt':str(rp) if rp.exists() else None,'launcher_returncode':pr.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'launcher_error':pr.stderr[-1500:]};print(json.dumps(row),flush=True);return row
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,queue))
result={'requested':2,'completed0':sum(r.get('status')=='completed' and r.get('returncode')==0 for r in rows),'results':rows};p=Path(__file__).parent/'controller-result.json';assert not p.exists();p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);raise SystemExit(0 if result['completed0']==2 else 1)
