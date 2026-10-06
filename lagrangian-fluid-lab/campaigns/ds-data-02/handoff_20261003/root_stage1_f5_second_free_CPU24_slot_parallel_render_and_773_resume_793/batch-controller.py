from pathlib import Path
import json,subprocess,time,os,signal,datetime
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
c=load(O/'dispatch-config.json');rp=Path(c['prior_M115_receipt'])
q=load(c['new_M085_request']);ledger=load(c['ledger_path']);assert sum(x.get('cpu_threads',0) for x in ledger['reservations'])+q['cpu_threads']<=64
p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),c['new_M085_request']],cwd=L,text=True,capture_output=True)
ar=Path(c['new_M085_attempt']);newrp=ar/'execution-receipt.json';v=load(newrp) if newrp.exists() else {};rows=[{'case':'M085_T080','status':v.get('status'),'returncode':v.get('returncode'),'actual_receipt':str(newrp),'launcher_returncode':p.returncode,'launcher_error':p.stderr[-1500:]}]
while True:
 r=load(rp)
 if r['status']!='running':break
 pid=r.get('pid');assert pid and Path('/proc',str(pid)).exists(),'Actual M115 handle missing; inspect authoritative termination without restart'
 time.sleep(10)
rows.append({'case':'M115_T100','status':r['status'],'returncode':r.get('returncode'),'actual_receipt':str(rp)})
ledger=load(c['ledger_path']);owned={q['attempt_id'],r['request']['attempt_id']};assert not any(x['id'].split('/')[-1] in owned for x in ledger['reservations']),'owned F5 leases not drained'
held=c['held773_controller'];proc=Path('/proc')/str(held['pid']);assert proc.exists() and (proc/'stat').read_text().split(') ',1)[1].split()[19]==held['proc_start_ticks'];assert held['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\0');assert '\tT ' in (proc/'status').read_text();os.kill(held['pid'],signal.SIGCONT)
put(O/'actual773-controller-resume.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':held['pid'],'proc_start_ticks':held['proc_start_ticks'],'SIGCONT_sent':True,'only_own_controller_resumed':True,'no_owned_F5_reservations_remaining':True,'scientific_children_not_signalled':True})
put(O/'controller-result.json',{'actual_F5_cases_terminal':rows,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'held773_resumed':True,'effective_shared_render_cap':2,'CPU_guard_cap':64,'independent_case_increment':0});print(json.dumps({'F5_terminal_cases':rows,'773_resumed':True}),flush=True)
