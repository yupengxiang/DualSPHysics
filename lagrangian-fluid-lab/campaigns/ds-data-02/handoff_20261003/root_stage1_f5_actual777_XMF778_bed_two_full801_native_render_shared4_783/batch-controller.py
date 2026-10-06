from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def run(item):
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),item['request']],cwd=L,text=True,capture_output=True)
 ar=Path(item['actual_attempt']);rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False
 if (r.get('status'),r.get('returncode'))==('completed',0):
  v=load(ar/'render/paraview-full-animation-report.json');passed=v['frames']==v['source_frames']==801 and v['all_frames_rendered'] and v['native_identity_axis_preserved'] and v['actual_times_preserved_exactly'] and v['nonfinite_active_states']==0 and len(v['outputs']['contact_sheets'])==34
 row={**item,'receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full801_native_render_pass':passed,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,load(O/'actual-root-full801-render-enabling-review.json')['rows']))
v={'requested':2,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full801_native_render_pass_count':sum(r['actual_full801_native_render_pass'] for r in rows),'pending_held':0,'batch_cap':2,'global_shared_cap':4,'results':rows};(O/'controller-result.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:x for k,x in v.items() if k!='results'}),flush=True);raise SystemExit(0 if v['actual_full801_native_render_pass_count']==2 else 1)
