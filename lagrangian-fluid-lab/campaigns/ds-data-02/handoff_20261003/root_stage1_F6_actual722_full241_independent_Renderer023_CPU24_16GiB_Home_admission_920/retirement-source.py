from pathlib import Path
import json,hashlib,os,signal,time,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';O=next(H.glob('root*_920'));old=next(H.glob('root*_860'));load=lambda p:json.loads(Path(p).read_text());c=load(old/'controller-launch-process.json');pid=c['pid'];pr=Path('/proc')/str(pid)
def fields():return (pr/'stat').read_text().split(') ',1)[1].split()
def children():return sorted({int(x) for t in (pr/'task').iterdir() for x in (t/'children').read_text().split()})
f=fields();assert f[0]!='Z' and f[19]==c['proc_start_ticks'];assert c['controller'].encode() in (pr/'cmdline').read_bytes();assert hashlib.sha256(Path(c['controller']).read_bytes()).hexdigest()==c['controller_sha256'];assert not list(old.glob('*request.json')) and not list((old/'requests').glob('*request.json'));assert not children();ledger=load('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json');assert not ledger['reservations'];assert load(next(H.glob('root*_917'))/'actual-ready24-independent-dispatch-audit.json')['actual_cases']==24
os.kill(pid,signal.SIGSTOP)
for _ in range(30):
 f=fields()
 if f[0] in ['T','t']:break
 time.sleep(.05)
try:
 assert f[0] in ['T','t'] and f[19]==c['proc_start_ticks'] and not children();assert not list(old.glob('*request.json')) and not list((old/'requests').glob('*request.json'));assert not load('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json')['reservations'];proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'old_controller_launch':{'path':str(old/'controller-launch-process.json'),'sha256':hashlib.sha256((old/'controller-launch-process.json').read_bytes()).hexdigest()},'pid':pid,'proc_start_ticks':c['proc_start_ticks'],'controller_sha256':c['controller_sha256'],'frozen_state':f[0],'actual_children':[],'actual_registered_requests':0,'actual_scientific_reservations_at_handoff':0,'reason':'Remove immutable original860 cross-family whole F4 render gate; actual722 own24 full241 native typed XMF already0. Distinct independent successor retains16GiB reservation/CPU24/env2/cap2, uses2GiB extra admission headroom and shared Home500 floor.','scientific_worker_terminated_or_restarted':False,'original_request_receipt_or_source_bytes_changed':False,'case_increment':0};os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
except BaseException:
 os.kill(pid,signal.SIGCONT);raise
for _ in range(50):
 if not pr.exists() or fields()[0]=='Z':break
 time.sleep(.1)
assert not pr.exists() or fields()[0]=='Z';proof['same_metadata_handle_retired']=True;proof['terminal_state']='missing' if not pr.exists() else fields()[0];(O/'metadata-only-original860-retirement-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');(O/'retirement-source.py').write_bytes(Path(__file__).read_bytes());print({'metadata_pid_retired':pid,'scientific_workers_touched':0})
