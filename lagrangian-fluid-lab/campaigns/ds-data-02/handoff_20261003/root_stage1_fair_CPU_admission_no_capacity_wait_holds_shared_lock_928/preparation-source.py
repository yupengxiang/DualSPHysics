from pathlib import Path
import json,datetime,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';O=H/'root_stage1_fair_CPU_admission_no_capacity_wait_holds_shared_lock_928';O.mkdir(exist_ok=False)
source='''from pathlib import Path
import json,fcntl,subprocess,time,shutil,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
LAUNCH=H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'
LAUNCH_SHA='708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76'
HOME_FLOOR=500*1024**3;HEADROOM=2*1024**3

def load(p):return json.loads(Path(p).read_text())
def dispatch(request_path, *, serial_conversion=False):
 request_path=Path(request_path);q=load(request_path)
 assert q['kind']=='cpu' and q['launch_owner']=='root' and not q['disabled']
 assert q['cpu_threads'] in ([2] if serial_conversion else [24])
 assert q['estimated_storage_bytes']>0
 assert hashlib.sha256(LAUNCH.read_bytes()).hexdigest()==LAUNCH_SHA
 receipt=Path(q['attempt_root'])/'execution-receipt.json'
 assert not Path(q['attempt_root']).exists(), 'No retry or restart of consumed attempt'
 lock_path=D/'runtime'/('stage1-fullnative-conversion-dispatch.lock' if serial_conversion else 'stage1-fullnative-render-registration.lock')
 while True:
  admitted=False
  with lock_path.open('a') as lock:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:
    pass
   else:
    ledger=load(D/'runtime/resource-ledger.json')
    assert ledger['limits']['home_min_free_bytes']>=HOME_FLOOR
    reservations=ledger['reservations']
    cpu=sum(x.get('cpu_threads',0) for x in reservations)
    reserved=sum(x.get('new_storage_bytes',0) for x in reservations)
    renderer_count=sum(x.get('cpu_threads',0)==24 for x in reservations)
    fit=(cpu+q['cpu_threads']+2<=64 and (serial_conversion or renderer_count<2)
         and shutil.disk_usage('/home/jade').free-reserved-q['estimated_storage_bytes']-HEADROOM>=ledger['limits']['home_min_free_bytes'])
    if fit:
     assert not Path(q['attempt_root']).exists()
     p=subprocess.Popen([str(L/'.venv/bin/python'),str(LAUNCH),str(request_path)],cwd=L,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
     admitted=True
     if serial_conversion:
      # The serial conversion lock is retained only while an actual admitted
      # producer runs, never during an insufficient-capacity wait.
      stdout,stderr=p.communicate()
     else:
      # Prevent concurrent launchers from racing the registration snapshot.
      while p.poll() is None:
       if receipt.exists() and load(receipt).get('status')=='running':break
       time.sleep(.2)
    fcntl.flock(lock,fcntl.LOCK_UN)
  if admitted:
   if not serial_conversion:stdout,stderr=p.communicate()
   return subprocess.CompletedProcess(p.args,p.returncode,stdout,stderr)
  # Releasing the shared lock allows another family whose smaller bounded
  # output fits to make progress. Root142 still reserves atomically.
  time.sleep(3)
'''
compile(source,str(O/'fair_CPU_dispatch.py'),'exec');(O/'fair_CPU_dispatch.py').write_text(source);proof={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'status':'prepared_not_used_for_any_scientific_launch_yet','old_consumed_controllers_unmodified':True,'CPU_cap':64,'render_cap':2,'CPU24_renderer_and_CPU2_serial_conversion':True,'Home_floor_GiB':500,'extra_headroom_GiB':2,'no_capacity_wait_holds_shared_lock':True,'scientific_jobs_only_via_original142':True,'atomic_shared_runner_reservation_retained':True,'no_restart_of_existing_attempt':True,'case_credit':0};(O/'source-protocol-review.json').write_text(json.dumps(proof,indent=2)+'\n');(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print('Prepared fair capacity admission, scientific launches0')
