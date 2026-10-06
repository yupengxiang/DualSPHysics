from pathlib import Path
import json,subprocess,time,os,signal,datetime
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
c=load(O/'dispatch-config.json');rp=Path(c['prior_M115_receipt'])
while True:
 r=load(rp)
 if r['status']!='running':break
 pid=r.get('pid');proc=Path('/proc')/str(pid);assert pid and proc.exists(),'Actual M115 handle missing; do not restart from observation expiry'
 time.sleep(10)
rows=[{'case':'M115_T100','status':r['status'],'returncode':r.get('returncode'),'actual_receipt':str(rp)}]
if (r['status'],r.get('returncode'))==('completed',0):
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),c['new_M085_request']],cwd=L,text=True,capture_output=True);ar=Path(c['new_M085_attempt']);newrp=ar/'execution-receipt.json';v=load(newrp) if newrp.exists() else {};passed=False
 if (v.get('status'),v.get('returncode'))==('completed',0):
  report=load(ar/'render/paraview-full-animation-report.json');passed=report['frames']==report['source_frames']==801 and report['all_frames_rendered'] and report['native_identity_axis_preserved'] and report['actual_times_preserved_exactly'] and report['nonfinite_active_states']==0 and len(report['outputs']['contact_sheets'])==34
 rows.append({'case':'M085_T080','status':v.get('status'),'returncode':v.get('returncode'),'launcher_returncode':p.returncode,'actual_receipt':str(newrp),'actual_full801_render_pass':passed,'launcher_error':p.stderr[-1500:]})
ledger=load(c['ledger_path']);owned_ids={load(c['new_M085_request'])['attempt_id'],load(rp)['request']['attempt_id']};assert not any(x['id'].split('/')[-1] in owned_ids for x in ledger['reservations']),'F5 reservations not yet drained; do not release773 futuredispatch'
held=c['held773_controller'];proc=Path('/proc')/str(held['pid']);assert proc.exists() and (proc/'stat').read_text().split(') ',1)[1].split()[19]==held['proc_start_ticks'];assert held['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\0');assert '\tT ' in (proc/'status').read_text();os.kill(held['pid'],signal.SIGCONT)
put(O/'actual773-controller-resume.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':held['pid'],'proc_start_ticks':held['proc_start_ticks'],'SIGCONT_sent':True,'only_own_controller_resumed':True,'no_owned_F5_reservations_remaining':True,'scientific_children_not_signalled':True})
put(O/'controller-result.json',{'requested_new_jobs':1,'actual_F5_cases_terminal':rows,'new_M085_completed0':len(rows)==2 and (rows[1]['status'],rows[1]['returncode'])==('completed',0),'held773_resumed':True,'effective_shared_render_cap':2,'CPU_guard_cap':64,'independent_case_increment':0});print(json.dumps({'F5_terminal_cases':rows,'773_resumed':True}),flush=True)
