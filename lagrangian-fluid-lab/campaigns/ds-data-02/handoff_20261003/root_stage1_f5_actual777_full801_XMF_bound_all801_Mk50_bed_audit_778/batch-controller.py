from pathlib import Path
import subprocess,json
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
rows=[]
for item in load(O/'actual-root-bed-enabling-review.json')['rows']:
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),item['request']],cwd=L,text=True,capture_output=True)
 ar=Path(item['actual_attempt']);rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};report=ar/'audit-output/c082s1-full-event-bed-footprint-audit.json';passed=False
 if (r.get('status'),r.get('returncode'))==('completed',0):
  v=load(report);passed=len(v['frame_reports'])==801 and not v['source_arrays_modified'] and not v['source_arrays_dropped_or_masked'];assert passed
 row={**item,'receipt':str(rp),'report':str(report),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full801_bed_report_complete':passed,'launcher_error':p.stderr[-1500:]};rows.append(row);print(json.dumps(row),flush=True)
 if not passed:break
v={'requested':2,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full801_bed_report_complete_count':sum(r['actual_full801_bed_report_complete'] for r in rows),'pending_held':2-len(rows),'results':rows};(O/'controller-result.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:x for k,x in v.items() if k!='results'}),flush=True);raise SystemExit(0 if v['actual_full801_bed_report_complete_count']==2 else 1)
