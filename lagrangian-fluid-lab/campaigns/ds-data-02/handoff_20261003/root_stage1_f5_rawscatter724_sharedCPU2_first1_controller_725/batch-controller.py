from pathlib import Path
import subprocess,json,time
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_typed590_initial_mk_seven_keyframes_raw_scatter_audit_724')
rows=[]
for p in sorted(O.glob('*-request.json')):
 while True:
  ledger=json.loads((D/'runtime/resource-ledger.json').read_text());reserved=sum(v.get('cpu_threads',0) for v in ledger['reservations'])
  if reserved+2<=64:break
  time.sleep(10)
 q=json.loads(p.read_text());r=subprocess.run([str(L/'.venv/bin/python'),str(L/'campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(p)],cwd=L,text=True,capture_output=True);a=D/'families'/q['family_id']/q['case_id']/q['attempt_id'];rp=a/'execution-receipt.json';receipt=json.loads(rp.read_text()) if rp.exists() else {};ok=r.returncode==0 and (receipt.get('status'),receipt.get('returncode'))==('completed',0)
 if ok:
  report=json.loads((a/'audit-output/initial-mk-keyframe-scatter-audit.json').read_text());assert len(report['plot_outputs'])==21 and [x['frame'] for x in report['actual_saved_frames']]==[0,97,153,219,400,718,800];assert report['inputs']['source_h5_opened_read_only'] and not report['inputs']['marker_time_varying'];assert receipt['input_hashes_at_launch']==receipt['input_hashes_after_run'];assert all(Path(x).is_file() for x in report['plot_outputs'])
 row={'request':str(p),'actual_receipt':str(rp),'candidate':q['candidate_id'],'launcher_returncode':r.returncode,'status':receipt.get('status'),'returncode':receipt.get('returncode'),'launcher_output':r.stdout[-1600:],'launcher_error':r.stderr[-1600:]};rows.append(row);print(json.dumps(row),flush=True)
 if not ok:break
summary={'requested':2,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) and r['launcher_returncode']==0 for r in rows),'results':rows,'case_increment':0};(Path(__file__).parent/'controller-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(0 if summary['completed0']==2 else 1)
