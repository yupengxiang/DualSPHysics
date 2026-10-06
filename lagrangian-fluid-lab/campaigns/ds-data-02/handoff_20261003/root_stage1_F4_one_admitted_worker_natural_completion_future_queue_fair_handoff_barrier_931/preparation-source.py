from pathlib import Path
import json,hashlib,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';old=next(H.glob('root*_924'));O=H/'root_stage1_F4_one_admitted_worker_natural_completion_future_queue_fair_handoff_barrier_931';O.mkdir(exist_ok=True);assert not list(O.iterdir());load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();c=load(old/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);f=(p/'stat').read_text().split(') ',1)[1].split();assert f[19]==c['proc_start_ticks'] and c['controller'].encode() in (p/'cmdline').read_bytes() and sha(c['controller'])==c['controller_sha256'];children=sorted({int(x) for t in (p/'task').iterdir() for x in (t/'children').read_text().split()});assert len(children)==1;child=Path('/proc')/str(children[0]);cf=(child/'stat').read_text().split(') ',1)[1].split();items=[]
for qp in old.glob('*request.json'):
 q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else None
 if r:assert r['status']=='running' and r.get('returncode') is None and r['pid']>0;worker=Path('/proc')/str(r['pid']);wf=(worker/'stat').read_text().split(') ',1)[1].split();assert wf[0] not in ['Z','T','t']
 else:assert not Path(q['attempt_root']).exists()
 items.append({'request':str(qp),'request_sha256':sha(qp),'case_id':q['case_id'],'attempt_root':q['attempt_root'],'attempt_id':q['attempt_id'],'receipt':str(rp),'state_at_preparation':r['status'] if r else 'unlaunched','scientific_worker_pid':r['pid'] if r else None,'scientific_worker_ticks':wf[19] if r else None})
assert len(items)==2 and sum(x['state_at_preparation']=='running' for x in items)==1;config={'old_controller':c,'old_launch_file':str(old/'controller-launch-process.json'),'old_launch_sha256':sha(old/'controller-launch-process.json'),'old_controller_root':str(old),'launcher_child_pid':children[0],'launcher_child_ticks':cf[19],'requests':items,'receipt_poll_seconds':3,'natural_finish_deadline_seconds':15000};(O/'barrier-config.json').write_text(json.dumps(config,indent=2)+'\n')
s='''from pathlib import Path
import json,hashlib,os,signal,time,datetime
O=Path(__file__).parent;load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();cfg=load(O/'barrier-config.json');c=cfg['old_controller'];pid=c['pid'];pr=Path('/proc')/str(pid);retired=False

def fields(p):return (p/'stat').read_text().split(') ',1)[1].split()
def children():return sorted({int(x) for t in (pr/'task').iterdir() for x in (t/'children').read_text().split()})
def assert_same():
 f=fields(pr);assert f[19]==c['proc_start_ticks'] and c['controller'].encode() in (pr/'cmdline').read_bytes() and sha(c['controller'])==c['controller_sha256'];return f

def put(name,x):(O/name).write_text(json.dumps(x,indent=2)+'\\n')
try:
 f=assert_same();assert f[0] not in ['Z','T','t'];assert children()==[cfg['launcher_child_pid']]
 ch=Path('/proc')/str(cfg['launcher_child_pid']);assert fields(ch)[19]==cfg['launcher_child_ticks']
 assert sha(cfg['old_launch_file'])==cfg['old_launch_sha256']
 for x in cfg['requests']:assert sha(x['request'])==x['request_sha256']
 os.kill(pid,signal.SIGSTOP)
 for _ in range(30):
  if assert_same()[0] in ['T','t']:break
  time.sleep(.05)
 assert assert_same()[0] in ['T','t']
 # Freeze only the metadata queue owner; every admitted launcher and science
 # worker remains independently scheduled and is allowed to finish naturally.
 active=next(x for x in cfg['requests'] if x['state_at_preparation']=='running')
 w=Path('/proc')/str(active['scientific_worker_pid']);wf=fields(w);assert wf[19]==active['scientific_worker_ticks'] and wf[0] not in ['T','t','Z']
 put('actual-metadata-barrier-running.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'metadata_PID_frozen':pid,'metadata_ticks':c['proc_start_ticks'],'scientific_worker_PID_not_frozen':active['scientific_worker_pid'],'launcher_PID_not_frozen':cfg['launcher_child_pid'],'current_registered_receipt':active['receipt'],'no_worker_terminated_or_restarted':True,'reason':'Prevent future lock-holding12GiB waiters before fair bounded successor; let current full1201 actual worker complete normally.'})
 start=time.monotonic()
 while True:
  assert assert_same()[0] in ['T','t']
  r=load(active['receipt']);ch=Path('/proc')/str(cfg['launcher_child_pid']);cf=fields(ch) if ch.exists() else [];worker=Path('/proc')/str(active['scientific_worker_pid']);wf=fields(worker) if worker.exists() else []
  child_terminal=not cf or (cf[19]==cfg['launcher_child_ticks'] and cf[0]=='Z')
  science_terminal=not wf or (wf[19]==active['scientific_worker_ticks'] and wf[0]=='Z')
  if r['status'] in ['completed','failed','timed_out'] and child_terminal and science_terminal:break
  if time.monotonic()-start>cfg['natural_finish_deadline_seconds']:raise RuntimeError('Natural completion observation deadline; resume same parent, never kill worker')
  time.sleep(cfg['receipt_poll_seconds'])
 assert children() in [[],[cfg['launcher_child_pid']]]
 for x in cfg['requests']:
  assert sha(x['request'])==x['request_sha256']
  if x['state_at_preparation']=='unlaunched':assert not Path(x['attempt_root']).exists()
 ledger=load('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json');own={f"F4/{x['case_id']}/{x['attempt_id']}" for x in cfg['requests']};assert not any(x.get('id') in own for x in ledger['reservations'])
 evidence={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'same_metadata_handle_retired':True,'metadata_PID':pid,'metadata_ticks':c['proc_start_ticks'],'admitted_scientific_receipt':active['receipt'],'receipt_sha256':sha(active['receipt']),'actual_status':r['status'],'actual_returncode':r.get('returncode'),'launcher_child_state':cf[0] if cf else 'missing','launcher_child_exit_status':cf[-1] if cf else None,'scientific_worker_state':wf[0] if wf else 'missing','own_reservations':0,'other_reservations_preserved':ledger['reservations'],'future_unlaunched_request_preserved':next(x for x in cfg['requests'] if x['state_at_preparation']=='unlaunched'),'worker_terminated_or_restarted':False,'old_bytes_unchanged':True,'case_credit':0}
 os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT);retired=True
 for _ in range(50):
  if not pr.exists() or fields(pr)[0]=='Z':break
  time.sleep(.1)
 assert not pr.exists() or fields(pr)[0]=='Z';evidence['terminal_metadata_state']=fields(pr)[0] if pr.exists() else 'missing';put('metadata-only-original924-natural-completion-retirement-proof.json',evidence);print(json.dumps({'metadata_retired':pid,'science_status':r['status'],'science_rc':r.get('returncode'),'science_interrupted':False}),flush=True)
finally:
 if not retired and pr.exists() and fields(pr)[19]==c['proc_start_ticks'] and fields(pr)[0] in ['T','t']:os.kill(pid,signal.SIGCONT)
'''
compile(s,str(O/'natural_completion_barrier.py'),'exec');(O/'natural_completion_barrier.py').write_text(s);(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print({'barrier_prepared':True,'active_F4_worker':next(x['scientific_worker_pid'] for x in items if x['state_at_preparation']=='running'),'science_not_touched':True})
