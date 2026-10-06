from pathlib import Path
import os,signal,time,json,hashlib,ast,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');load=lambda p:json.loads(Path(p).read_text())
def root(n):return next(H.glob(f'root*_{n}'))
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def proc(c):
 p=Path('/proc')/str(c['pid']);f=(p/'stat').read_text().split(') ',1)[1].split();assert f[19]==c['proc_start_ticks'] and c['controller'].encode() in (p/'cmdline').read_bytes().split(b'\0');return p,f
old=[load(root(n)/'controller-launch-process.json') for n in [835,836]]
held=[];retired=False
try:
 for c in old:
  p,f=proc(c);assert f[0]!='Z';os.kill(c['pid'],signal.SIGSTOP);held.append(c)
  for _ in range(30):
   p,f=proc(c)
   if f[0]=='T':break
   time.sleep(.02)
  assert f[0]=='T'
 ids={c['pid'] for c in old};children=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   f=(p/'stat').read_text().split(') ',1)[1].split()
   if int(f[1]) in ids:children.append(int(p.name))
  except (FileNotFoundError,ProcessLookupError,PermissionError):pass
 assert not children,'An old preparation controller has an actual child; resume, preserve its live job'
 for n in [835,836]:
  for qp in (root(n)/'requests').glob('*request.json'):
   q=load(qp);assert not Path(q['attempt_root']).exists(),'A scientific attempt already exists; resume original controllers'
 # Only stopped metadata schedulers with no children and no attempt outputs
 # are retired. Original contracts and launch records remain immutable.
 G=H/'root_stage1_F5_next34_actual824_GenCase_independent_CPU2_atomic64_scheduler_848';Q=H/'root_stage1_F5_next34_actual848_initialQA_independent_CPU2_atomic64_scheduler_849';G.mkdir();Q.mkdir()
 gen=(root(835)/'batch-controller.py').read_text().replace('gencase-root835','gencase-root848').replace("D/'runtime/stage1-fullnative-conversion-dispatch.lock'","D/'runtime/stage1-next34-Gencase-dispatch.lock'")
 qa=(root(836)/'batch-controller.py').read_text().replace('G=root(835)','G=root(848)').replace('own835-initial-placement-mk50-root836','own848-initial-placement-mk50-root849').replace('own Root835','own Root848').replace("D/'runtime/stage1-fullnative-conversion-dispatch.lock'","D/'runtime/stage1-next34-initialQA-dispatch.lock'")
 for text in [gen,qa]:ast.parse(text)
 (G/'batch-controller.py').write_text(gen);(Q/'batch-controller.py').write_text(qa);(Q/'next34_identity_bound_original_placement_audit.py').write_bytes((root(836)/'next34_identity_bound_original_placement_audit.py').read_bytes());(Q/'identity-adapter-scope-review.json').write_bytes((root(836)/'identity-adapter-scope-review.json').read_bytes());(G/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes())
 sourceq=load(root(824)/'registered-source-generation-request.json');sr=load(Path(sourceq['attempt_root'])/'execution-receipt.json');assert (sr['status'],sr['returncode'])==('completed',0)
 contract={'change':'Only metadata preparation scheduling and new attempt identities; unchanged registered GenCase and placement workers, source824 motion, definition, owner, thresholds, native policy and strict runtime','reason':'F2 native24 completed0; old GenCase scheduler blocked on long conversion lock while its request has no actual attempt root','cpu_per_job':2,'each_stage_serial_cap':1,'shared_atomic_CPU_reservation_cap':64,'Home_min_free_gib':500,'GPU_science_not_launched_here':True,'foreign_GPU_processes_protected':True,'old_scheduler_launch_records':old,'original_source_models_and_bytes_unchanged':True,'independent_case_increment':0}
 put(G/'scheduling-scope-review.json',contract);put(Q/'scheduling-scope-review.json',contract)
 assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip();subprocess.run(['git','add','--',str(G.relative_to(R)),str(Q.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-m','ds02: prepare F5 initial cases alongside conversion within atomic CPU64'],cwd=R,check=True,stdout=subprocess.DEVNULL);commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
 for c in old:
  proc(c);os.kill(c['pid'],signal.SIGTERM);os.kill(c['pid'],signal.SIGCONT)
 for _ in range(50):
  if all(not (Path('/proc')/str(c['pid'])).exists() for c in old):break
  time.sleep(.02)
 assert all(not (Path('/proc')/str(c['pid'])).exists() for c in old),'Stopped metadata schedulers have not terminated; do not launch replacements'
 retired=True;put(G/'old_metadata_only_schedulers_retired.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'old':old,'actual_children_at_frozen_check':children,'all_scientific_attempt_outputs_absent':True,'signals_only_owned_verified_metadata_schedulers':True,'scientific_workers_signalled':False,'old_requests_and_launch_records_preserved':True})
 for p in [G,Q]:
  with (p/'controller.log').open('ab') as log:child=subprocess.Popen([str(L/'.venv/bin/python'),str(p/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  f=(Path('/proc')/str(child.pid)/'stat').read_text().split(') ',1)[1].split();c={'pid':child.pid,'proc_start_ticks':f[19],'controller':str(p/'batch-controller.py'),'controller_sha256':sha(p/'batch-controller.py'),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};put(p/'controller-launch-process.json',c);print(json.dumps(c),flush=True)
finally:
 if not retired:
  for c in held:
   try:
    p,f=proc(c)
    if f[0]=='T':os.kill(c['pid'],signal.SIGCONT)
   except (FileNotFoundError,ProcessLookupError):pass
