from pathlib import Path
import json,hashlib,datetime,os,signal,subprocess,time
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def root(n):return next(H.glob(f'root*_{n}'))
O=H/'root_stage1_f5_second_free_CPU24_slot_parallel_render_and_773_resume_793';O.mkdir(exist_ok=True);assert not list(O.iterdir()),'existing actual work; do not repeat'
old=root(786);launch=load(old/'controller-launch-process.json');cfg=load(old/'dispatch-config.json');oldq=load(cfg['new_M085_request']);oldar=Path(cfg['new_M085_attempt'])
assert not (oldar/'execution-receipt.json').exists() and not (old/'controller-result.json').exists()
ledger=load(cfg['ledger_path']);assert sum(x.get('cpu_threads',0) for x in ledger['reservations'])==24
assert not any(oldq['attempt_id'] in x['id'] for x in ledger['reservations'])
rp=Path(cfg['prior_M115_receipt']);r=load(rp);assert r['status']=='running' and r.get('returncode') is None and Path('/proc',str(r['pid'])).exists()
proc=Path('/proc')/str(launch['pid']);assert proc.exists();fields=(proc/'stat').read_text().split(') ',1)[1].split();assert fields[19]==launch['proc_start_ticks'];assert launch['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\0')
children=(proc/'task'/str(launch['pid'])/'children').read_text().strip();assert not children,'old786 launched child; do not retire'
os.kill(launch['pid'],signal.SIGTERM)
for _ in range(20):
 if not proc.exists():break
 time.sleep(.1)
assert not proc.exists() or (proc/'stat').read_text().split(') ',1)[1].split()[0]=='Z'
assert not (oldar/'execution-receipt.json').exists(),'race; no new launch'
put(O/'owned786_wait_controller_retirement.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':launch['pid'],'proc_start_ticks':launch['proc_start_ticks'],'exact_controller_cmdline_verified':True,'no_child_before_signal':True,'SIGTERM_only_owned_waiting_controller':True,'no_scientific_worker_signalled':True,'old786_request_not_dispatched':True,'old_records_preserved':True,'reason':'First F4 job ended; actual onlyM115CPU24 lease leaves safe secondCPU24 slot within immutable64 cap'})
q=oldq.copy();q['attempt_id']=q['attempt_id'].replace('root786','root793');ar=oldar.with_name(q['attempt_id']);q['attempt_root']=str(ar);q['status']='root-reviewed-enabled-second-free-CPU24-slot';q['root793_dispatch_note']='global2, declared48<=immutableCPU64; retain root785 correction; old waiting786 retired before any child'
qp=O/'M085_T080-render-request.json';newcfg={**cfg,'new_M085_request':str(qp),'new_M085_attempt':str(ar),'retired_owned786_controller':launch,'effective_renderer_cap':2,'shared_CPU_guard_cap':64};put(O/'dispatch-config.json',newcfg)
controller='''from pathlib import Path
import json,subprocess,time,os,signal,datetime
L=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab');H=L/'campaigns/ds-data-02/handoff_20261003';O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\\n')
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
held=c['held773_controller'];proc=Path('/proc')/str(held['pid']);assert proc.exists() and (proc/'stat').read_text().split(') ',1)[1].split()[19]==held['proc_start_ticks'];assert held['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\\0');assert '\\tT ' in (proc/'status').read_text();os.kill(held['pid'],signal.SIGCONT)
put(O/'actual773-controller-resume.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':held['pid'],'proc_start_ticks':held['proc_start_ticks'],'SIGCONT_sent':True,'only_own_controller_resumed':True,'no_owned_F5_reservations_remaining':True,'scientific_children_not_signalled':True})
put(O/'controller-result.json',{'actual_F5_cases_terminal':rows,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'held773_resumed':True,'effective_shared_render_cap':2,'CPU_guard_cap':64,'independent_case_increment':0});print(json.dumps({'F5_terminal_cases':rows,'773_resumed':True}),flush=True)
'''
cp=O/'batch-controller.py';cp.write_text(controller)
for p in [O/'owned786_wait_controller_retirement.json',O/'dispatch-config.json',cp]:
 if str(p) not in q['input_files']:q['input_files'].append(str(p))
 q['input_sha256'][str(p)]=sha(p)
put(qp,q)
f=(O/'controller.log').open('ab');p=subprocess.Popen([str(L/'.venv/bin/python'),str(cp)],cwd=L,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);f.close();time.sleep(.2);proc=Path('/proc')/str(p.pid);assert proc.exists()
put(O/'controller-launch-process.json',{'pid':p.pid,'proc_start_ticks':(proc/'stat').read_text().split(') ',1)[1].split()[19],'controller':str(cp),'controller_sha256':sha(cp),'detached_parent_session':True,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
print(json.dumps({'controller_pid':p.pid,'actual_request':str(qp),'actual_M085_receipt':str(ar/'execution-receipt.json'),'old786_owned_waiter_retired':True}))
