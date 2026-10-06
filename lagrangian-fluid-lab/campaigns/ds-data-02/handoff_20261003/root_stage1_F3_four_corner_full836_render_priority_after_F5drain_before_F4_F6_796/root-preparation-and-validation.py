from pathlib import Path
import json,hashlib,datetime,os,signal,subprocess,time,ast
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
def root(n):return next(H.glob(f'root*_{n}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_F3_four_corner_full836_render_priority_after_F5drain_before_F4_F6_796';O.mkdir(exist_ok=False)
old=root(775);lm=load(old/'controller-launch-process.json');proc=Path('/proc')/str(lm['pid']);assert proc.exists() and (proc/'stat').read_text().split(') ',1)[1].split()[19]==lm['proc_start_ticks'];assert lm['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\0');assert not (proc/'task'/str(lm['pid'])/'children').read_text().strip();assert not (root(774)/'controller-result.json').exists();assert not (old/'controller-result.json').exists();assert not list(root(748).glob('*render-request.json'))
os.kill(lm['pid'],signal.SIGTERM)
for _ in range(20):
 if not proc.exists():break
 time.sleep(.1)
assert not proc.exists() or (proc/'stat').read_text().split(') ',1)[1].split()[0]=='Z'
put(O/'owned775_wait_controller_retirement.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':lm['pid'],'proc_start_ticks':lm['proc_start_ticks'],'exact_controller_identity_verified':True,'no_child_before_signal':True,'SIGTERM_only_owned_waiting_controller':True,'no_scientific_worker_signalled':True,'reason':'Move four F3 corner renders before bulk F4/F6 renders to enable independent F3 GPU production sooner','old775_not_dispatched':True,'old_source_preserved':True})
config={'wait793_result':str(root(793)/'controller-result.json'),'held773_controller':load(root(773)/'controller-launch-process.json'),'ledger_path':'/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json','existing_root715_requests':str(root(715)),'effective_renderer_cap':2,'shared_CPU_guard_cap':64,'source775_controller':lm,'source748_plans':str(root(748)/'plans'),'science_arrays_not_read_by_controller':True};put(O/'dispatch-config.json',config)
body=(old/'batch-controller.py').read_text();start=body.index("up=next(H.glob('root_*_774'))");end=body.index('worker=P/')
body=body[:start]+"up=Path(__file__).parent/'dispatch-config.json'\n"+body[end:]
body=body.replace("O=H/'root_stage1_f3_actual743_four_full836_renderer023_runtime_plan_748'",f"A=H/'root_stage1_f3_actual743_four_full836_renderer023_runtime_plan_748';O=Path(__file__).parent")
body=body.replace("O/'actual-four-full836-render-plan-review.json'","A/'actual-four-full836-render-plan-review.json'").replace("(O/'plans').glob('*.json')","(A/'plans').glob('*.json')").replace("q['attempt_id']+'-root748'","q['attempt_id']+'-root796'")
body=body.replace("Path(__file__),A/", "Path(__file__),O/'priority-render-body.py',O/'owned775_wait_controller_retirement.json',A/")
ast.parse(body);bp=O/'priority-render-body.py';bp.write_text(body)
controller='''from pathlib import Path
import json,time,os,signal,datetime
O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\\n')
def verify(h):
 p=Path('/proc',str(h['pid']));assert p.exists() and (p/'stat').read_text().split(') ',1)[1].split()[19]==h['proc_start_ticks'];assert h['controller'].encode() in (p/'cmdline').read_bytes().split(b'\\0');return p
c=load(O/'dispatch-config.json');up=Path(c['wait793_result'])
while not up.exists():
 h=load(up.parent/'controller-launch-process.json');verify(h);time.sleep(10)
u=load(up);assert u['held773_resumed'] and u['effective_shared_render_cap']==2
h=c['held773_controller'];proc=verify(h);os.kill(h['pid'],signal.SIGSTOP)
for _ in range(20):
 if '\\tT ' in (proc/'status').read_text():break
 time.sleep(.1)
assert '\\tT ' in (proc/'status').read_text()
put(O/'owned773_future_dispatch_hold.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':h['pid'],'proc_start_ticks':h['proc_start_ticks'],'only_future_controller_dispatch_SIGSTOP':True,'running_scientific_children_not_signalled':True,'reason':'Four F3 full836 corner renders first; global renderer cap2 retained'})
try:
 while True:
  l=load(c['ledger_path']);active=[x for x in l['reservations'] if x['id'].startswith('F4/') and x['id'].endswith('root715')]
  if not active:break
  # Shared launchers, not state files alone, prove existing worker lifecycle.
  for x in active:assert Path('/proc',str(x['launcher_pid'])).exists(),'Existing owned F4 launcher missing; inspect metadata, never restart by timeout'
  time.sleep(10)
 assert sum(x.get('cpu_threads',0) for x in load(c['ledger_path'])['reservations'])==0
 body=(O/'priority-render-body.py').read_text();exec(compile(body,str(O/'priority-render-body.py'),'exec'),{'__file__':str(Path(__file__).resolve()),'__name__':'__main__'})
finally:
 l=load(c['ledger_path']);assert not any(x['id'].startswith('F3/') and x['id'].endswith('root796') for x in l['reservations']),'Priority F3 leases not drained; manual recovery required before resume'
 proc=verify(h);assert '\\tT ' in (proc/'status').read_text();os.kill(h['pid'],signal.SIGCONT)
 put(O/'actual773_after_priority_controller_resume.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':h['pid'],'proc_start_ticks':h['proc_start_ticks'],'SIGCONT_only_owned773':True,'no_priority_F3_reservations_remaining':True,'scientific_children_not_signalled':True,'F4_F6_bulk_queue_resume':True})
'''
cp=O/'batch-controller.py';ast.parse(controller);cp.write_text(controller)
f=(O/'controller.log').open('ab');p=subprocess.Popen([str(L/'.venv/bin/python'),str(cp)],cwd=L,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);f.close();time.sleep(.2);proc=Path('/proc')/str(p.pid);assert proc.exists()
put(O/'controller-launch-process.json',{'pid':p.pid,'proc_start_ticks':(proc/'stat').read_text().split(') ',1)[1].split()[19],'controller':str(cp),'controller_sha256':sha(cp),'detached_parent_session':True,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'verified_wait_on_live_actual793':True})
print(json.dumps({'priority_controller_pid':p.pid,'retired_only_owned775_waiter':True,'priority_jobs':4,'actual_wait793':config['wait793_result'],'global_renderer_cap':2}))
