from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,subprocess,time,sys,fcntl,shutil
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(next(H.glob('root*134')))];import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text());root=lambda n:next(H.glob(f'root*_{n}'));SCI={'.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCI;return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2)+'\n');t.replace(p)
oldqs=sorted((root(839)/'requests').glob('*native-request.json'));assert len(oldqs)==20;originals=[];queue=[];prelaunch=[]
for qp in oldqs:
 q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {}
 if r.get('status') in ['running','completed']:originals.append((qp,q,rp));continue
 if r:
  assert r['status']=='failed' and r.get('pid') is None and r.get('returncode') is None and r['error']=='RuntimeError: shared CPU thread reservation exceeded';raw=list(Path(q['attempt_root']).rglob('*.bi4'));assert not raw;prelaunch.append(ref(rp))
 else:assert not Path(q['attempt_root']).exists()
 for p,dig in q['input_sha256'].items():
  if Path(p).suffix.lower() not in SCI:assert sha(p)==dig
 new=dict(q);aid=q['attempt_id']+'-CPU-registration-successor-root880';ap=D/'families/F3'/q['case_id']/aid;assert not ap.exists();md={**q['input_sha256'],str(qp):sha(qp),str(Path(__file__)):sha(Path(__file__)),str(O/'controller-contract.json'):sha(O/'controller-contract.json')};new.update(attempt_id=aid,attempt_root=str(ap),input_files=sorted(md),input_sha256=md,root_original839_request=ref(qp),root_resource_repair='same initialized704 and forcing; no-worker CPU admission refusal preserved; atomic global native registration wait',independent_case_count_increment=0);np=O/'requests'/(q['case_id']+'-native-request.json');put(np,new);queue.append(np)
assert len(originals)==7 and len(queue)==13 and len(prelaunch)==1;put(O/'actual-source-capacity-review.json',{'original7_receipts':[str(rp) for qp,q,rp in originals],'original_no_worker_CPU_refusal':prelaunch,'new_distinct13_requests':[ref(qp) for qp in queue],'same_scientific_commands_704_forcing_and_physical_binding':True,'repair_class':'native CPU registration race','repair_attempt_for_class':1,'no_running_native_worker_restarted':True,'case_credit':0})
results=[]
for qp,q,rp in originals:
 while True:
  r=load(rp)
  if r['status']=='completed':assert r['returncode']==0;break
  assert r['status']=='running';pid=r['pid'];assert (Path('/proc')/str(pid)).exists();time.sleep(3)
 frames=len(list((rp.parent/'solver_output/data').glob('Part_*.bi4')));assert frames==836;results.append({'case_id':q['case_id'],'request':str(qp),'actual_receipt':str(rp),'status':'completed','returncode':0,'native_saved_frame_file_count':frames,'actual_full836_native_pass':True,'original839_reused':True})
def run(qp):
 q=load(qp)
 with (D/'runtime/stage1-fullnative-native-registration.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   l=load(D/'runtime/resource-ledger.json');storage=sum(x.get('new_storage_bytes',0) for x in l['reservations']);leased=set()
   for lp in (D/'leases').glob('*.json'):
    try:leased.add(load(lp)['uuid'])
    except FileNotFoundError:continue
   if sum(x.get('cpu_threads',0) for x in l['reservations'])+2>64 or shutil.disk_usage('/home/jade').free-storage-q['estimated_storage_bytes']-16*1024**3<l['limits']['home_min_free_bytes']:time.sleep(3);continue
   try:gpu.choose_gpu(rt.inventory(),leased,q['estimated_peak_gpu_mib']);break
   except RuntimeError:time.sleep(3)
  p=subprocess.Popen([str(L/'.venv/bin/python'),str(root(230)/'launch.py'),str(qp)],cwd=L,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);rp=Path(q['attempt_root'])/'execution-receipt.json'
  while p.poll() is None:
   if rp.exists() and load(rp)['status']=='running':break
   time.sleep(.2)
 stdout,stderr=p.communicate();r=load(rp) if rp.exists() else {};frames=len(list((rp.parent/'solver_output/data').glob('Part_*.bi4')));passed=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==836;out={'case_id':q['case_id'],'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full836_native_pass':passed,'native_saved_frame_file_count':frames,'launcher_error':stderr[-1500:],'case_credit':0};print(json.dumps(out),flush=True);return out
index=0;failed=False
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<7 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  if not active:break
  completed,_=wait(active,return_when=FIRST_COMPLETED)
  for f in completed:
   active.pop(f);out=f.result();results.append(out);failed|=not out['actual_full836_native_pass'];put(O/'actual-progress.json',{'results':results,'pending_held':len(queue)-index,'case_credit':0})
put(O/'controller-result.json',{'requested':20,'original7_reused':7,'new13_requested':13,'actual_full836_native_pass_count':sum(x['actual_full836_native_pass'] for x in results),'pending_held':len(queue)-index,'results':results,'case_credit':0});raise SystemExit(0 if len(results)==20 and not failed else 1)
