from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import subprocess,json
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_f3_new24_pitch_AY_four_corner_full836_native_qualification_706';load=lambda p:json.loads(Path(p).read_text())
def run(p):
 q=load(p);r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),str(p)],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';receipt=load(rp) if rp.exists() else {};row={'case_id':q['case_id'],'request':str(p),'actual_receipt':str(rp),'launcher_returncode':r.returncode,'status':receipt.get('status'),'returncode':receipt.get('returncode'),'launcher_output':r.stdout[-1200:],'launcher_error':r.stderr[-1200:]};print(json.dumps(row),flush=True);return row
queue=sorted(O.glob('*-native-request.json'));assert len(queue)==4
with ThreadPoolExecutor(max_workers=4) as pool:rows=[f.result() for f in as_completed([pool.submit(run,p) for p in queue])]
summary={'requested':4,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'parallel_cap':4,'results':rows};(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(0 if summary['completed0']==4 else 1)
