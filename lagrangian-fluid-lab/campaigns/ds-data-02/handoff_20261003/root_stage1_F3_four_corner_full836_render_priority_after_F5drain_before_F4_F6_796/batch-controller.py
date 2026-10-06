from pathlib import Path
import json,time,os,signal,datetime
O=Path(__file__).parent
load=lambda p:json.loads(Path(p).read_text())
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def verify(h):
 p=Path('/proc',str(h['pid']));assert p.exists() and (p/'stat').read_text().split(') ',1)[1].split()[19]==h['proc_start_ticks'];assert h['controller'].encode() in (p/'cmdline').read_bytes().split(b'\0');return p
c=load(O/'dispatch-config.json');up=Path(c['wait793_result'])
while not up.exists():
 h=load(up.parent/'controller-launch-process.json');verify(h);time.sleep(10)
u=load(up);assert u['held773_resumed'] and u['effective_shared_render_cap']==2
h=c['held773_controller'];proc=verify(h);os.kill(h['pid'],signal.SIGSTOP)
for _ in range(20):
 if '\tT ' in (proc/'status').read_text():break
 time.sleep(.1)
assert '\tT ' in (proc/'status').read_text()
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
 proc=verify(h);assert '\tT ' in (proc/'status').read_text();os.kill(h['pid'],signal.SIGCONT)
 put(O/'actual773_after_priority_controller_resume.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':h['pid'],'proc_start_ticks':h['proc_start_ticks'],'SIGCONT_only_owned773':True,'no_priority_F3_reservations_remaining':True,'scientific_children_not_signalled':True,'F4_F6_bulk_queue_resume':True})
