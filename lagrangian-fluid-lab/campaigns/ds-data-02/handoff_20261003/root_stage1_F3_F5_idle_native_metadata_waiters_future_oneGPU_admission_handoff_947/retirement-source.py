from pathlib import Path
import json,hashlib,os,signal,time,datetime,fcntl
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));O=H/'root_stage1_F3_F5_idle_native_metadata_waiters_future_oneGPU_admission_handoff_947';O.mkdir(exist_ok=False);load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in ['.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'];return hashlib.sha256(p.read_bytes()).hexdigest()
put=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n');order=[871,884];by={};frozen=[]
for n in order:
 c=load(root(n)/'controller-launch-process.json');by[n]={'ticks':c['proc_start_ticks'],'controller_sha256':c['controller_sha256']}
def prove(n,stopped=False):
 old=root(n);c=load(old/'controller-launch-process.json');pr=Path('/proc')/str(c['pid']);f=(pr/'stat').read_text().split(') ',1)[1].split();assert f[0]!='Z' and f[19]==c['proc_start_ticks']==by[n]['ticks'];assert sha(c['controller'])==c['controller_sha256']==by[n]['controller_sha256'];assert c['controller'].encode() in (pr/'cmdline').read_bytes();children=sorted({int(x) for t in (pr/'task').iterdir() for x in (t/'children').read_text().split()});assert not children,(n,children)
 if stopped:assert f[0] in ['T','t']
 rows=[];ids=set()
 for qp in sorted(list(old.glob('*request.json'))+list((old/'requests').glob('*request.json'))):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else None;rid='/'.join([q['family_id'],q['case_id'],q['attempt_id']]);ids.add(rid)
  if r:assert (r.get('status'),r.get('returncode'))==('completed',0),(n,rp,r.get('status'))
  else:assert not Path(q['attempt_root']).exists(),(n,qp,'unreceipted attempt root')
  rows.append({'request':str(qp),'request_sha256':sha(qp),'reservation_id':rid,'actual_receipt':str(rp),'receipt_sha256':sha(rp) if r else None,'status':r['status'] if r else 'unlaunched','returncode':r.get('returncode') if r else None})
 with (D/'runtime/resource-ledger.lock').open('r') as lock:
  fcntl.flock(lock,fcntl.LOCK_SH);ledger=load(D/'runtime/resource-ledger.json');assert not any(x.get('id') in ids for x in ledger['reservations']);fcntl.flock(lock,fcntl.LOCK_UN)
 return {'root':n,'pid':c['pid'],'ticks':f[19],'state':f[0],'controller_sha256':c['controller_sha256'],'all_task_children':children,'own_live_reservations':0,'actual_requests':rows,'completed0_preserved':sum(x['status']=='completed' for x in rows)}
try:
 for n in order:prove(n)
 # Freeze871 metadata waiter first; actual884 native lock holder is last.
 for n in order:
  row=prove(n);os.kill(row['pid'],signal.SIGSTOP);frozen.append(row)
  for _ in range(50):
   f=(Path('/proc')/str(row['pid'])/'stat').read_text().split(') ',1)[1].split()
   if f[0] in ['T','t']:break
   time.sleep(.02)
  prove(n,True)
 verified=[prove(n,True) for n in order];assert {n['root']:n['completed0_preserved'] for n in verified if n['completed0_preserved']}=={871:11,884:4}
 proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'frozen_verified':verified,'waiter871_frozen_before_actual884_holder':True,'all_original_source_request_receipts_preserved':True,'science_workers_terminated_or_restarted':False,'case_credit':0};put(O/'frozen-own-handle-proof.json',proof)
 for row in verified:
  os.kill(row['pid'],signal.SIGTERM);os.kill(row['pid'],signal.SIGCONT)
 for _ in range(100):
  states=[]
  for row in verified:
   pr=Path('/proc')/str(row['pid']);state=(pr/'stat').read_text().split(') ',1)[1].split()[0] if pr.exists() else 'missing';states.append({'root':row['root'],'pid':row['pid'],'terminal_state':state})
  if all(x['terminal_state'] in ['Z','missing'] for x in states):break
  time.sleep(.05)
 assert all(x['terminal_state'] in ['Z','missing'] for x in states)
 # Receipt and request metadata remain byte exact after metadata retirement.
 for row in verified:
  for v in row['actual_requests']:
   assert sha(v['request'])==v['request_sha256']
   if v['receipt_sha256']:assert sha(v['actual_receipt'])==v['receipt_sha256']
 proof.update(terminal_handles=states,metadata_retired=2,completed_native0_preserved=15);put(O/'metadata-only-conversion-waiters-retirement-proof.json',proof);(O/'retirement-source.py').write_bytes(Path(__file__).read_bytes());print({'metadata_retired':2,'native0_preserved':15,'science_stopped_or_restarted':False})
except BaseException:
 for row in frozen:
  try:os.kill(row['pid'],signal.SIGCONT)
  except ProcessLookupError:pass
 raise
