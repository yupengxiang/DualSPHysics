from pathlib import Path
import json,hashlib,ast,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');old=next(H.glob('root*773'));oldplans=next(H.glob('root*715'));O=H/'root_stage1_F4_actual669_remaining22_render_CPU_capacity_wait_distinct_successor_856';O.mkdir();load=lambda p:json.loads(Path(p).read_text())
r=load(old/'controller-result.json');assert r['completed0']==2 and r['pending_held']==21;successful=[x for x in r['results'] if x['actual_full1201_render_pass']];failed=[x for x in r['results'] if x['status']=='failed'];assert len(failed)==1;fr=load(failed[0]['actual_receipt']);assert fr['error']=='RuntimeError: shared CPU thread reservation exceeded' and fr.get('pid') is None and fr['bytes']==0
launch=load(old/'controller-launch-process.json');assert not (Path('/proc')/str(launch['pid'])).exists();nextlaunch=load(next(H.glob('root*774'))/'controller-launch-process.json');assert not (Path('/proc')/str(nextlaunch['pid'])).exists();complete={x['case_id'] for x in successful};queue=[str(p) for p in sorted((oldplans/'plans').glob('*.json')) if load(p)['case_id'] not in complete];assert len(queue)==22
proof={'original_773_terminal_result':str(old/'controller-result.json'),'original_failed_before_science_receipt':failed[0]['actual_receipt'],'original_failure':'CPU reservation exceeded; no scientific worker PID or output','original_actual_completed0_cases':successful,'remaining_cases':22,'science_inputs_and_Root023_worker_unchanged':True,'shared_atomic_CPU_cap':64,'CPU_per_render_reserved':24,'actual_worker_environment_threads':2,'max_parallel_renders':2,'pre_registration_wait_CPU_storage':True,'Home_floor_gib':500,'new_attempt_ids_preserve_old_failure_and_successes':True,'Root774_upstream_assertion_exit_preserved':True};(O/'capacity-failure-and-recovery-review.json').write_text(json.dumps(proof,indent=2)+'\n');(O/'controller-config.json').write_text(json.dumps({'queue':queue,'original_actual_completed0_cases':successful},indent=2)+'\n')
s=(old/'batch-controller.py').read_text();s=s[:s.index("queue=sorted((O/'plans')")];s=s.replace('import subprocess,json,hashlib,time,runpy,xml.etree.ElementTree as ET','import subprocess,json,hashlib,time,runpy,xml.etree.ElementTree as ET,fcntl,shutil')
s=s.replace("O=H/'root_stage1_f4_actual669_full1201_renderer023_complete_runtime_contract_715'",f"O=H/'{O.name}'")
s=s.replace("attempt=q['attempt_id']+'-root715'","attempt=q['attempt_id']+'-CPU-capacity-repair1-root856'")
s=s.replace("actual669_preflight_sha256=sha(proof)","actual669_preflight_sha256=sha(proof)")
s=s.replace(";r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,capture_output=True)",";r=dispatch(qp,q)")
a=s.index('def run(planpath):')
dispatch=r'''def dispatch(qp,q):
 with (D/'runtime/stage1-fullnative-render-registration.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   ledger=load(D/'runtime/resource-ledger.json');cpu=sum(x.get('cpu_threads',0) for x in ledger['reservations']);reserved=sum(x.get('new_storage_bytes',0) for x in ledger['reservations']);renderers=sum(x.get('cpu_threads',0)==24 for x in ledger['reservations'])
   if cpu+q['cpu_threads']+2<=64 and renderers<2 and shutil.disk_usage('/home/jade').free-reserved-q['estimated_storage_bytes']-16*1024**3>=ledger['limits']['home_min_free_bytes']:break
   time.sleep(3)
  p=subprocess.Popen([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE);rp=Path(q['attempt_root'])/'execution-receipt.json'
  while p.poll() is None:
   if rp.exists() and load(rp)['status']=='running':break
   time.sleep(.2)
 stdout,stderr=p.communicate();return subprocess.CompletedProcess(p.args,p.returncode,stdout,stderr)
'''
s=s[:a]+dispatch+s[a:]
s+=r'''cfg=load(O/'controller-config.json');queue=cfg['queue'];rows=[];failed=False;index=0
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,Path(queue[index]))]=queue[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row);failed|=not row['actual_full1201_render_pass'];put(O/'actual-progress.json',{'results':rows,'pending_not_launched':len(queue)-index,'case_credit':0})
summary={'requested':24,'original_already_completed0':2,'new_requested':22,'new_completed0':sum(r['actual_full1201_render_pass'] for r in rows),'completed0':2+sum(r['actual_full1201_render_pass'] for r in rows),'actual_full1201_render_pass_count':2+sum(r['actual_full1201_render_pass'] for r in rows),'pending_held':len(queue)-index,'global_parallel_cap':2,'source_already_completed0_cases':cfg['original_actual_completed0_cases'],'results':rows,'case_credit':0};put(O/'controller-result.json',summary);raise SystemExit(1 if failed else 0)
'''
ast.parse(s);(O/'batch-controller.py').write_text(s);(O/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes());assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip();subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True);subprocess.run(['git','commit','-m','ds02: resume F4 remaining22 renders with capacity wait and separate attempts'],cwd=R,check=True,stdout=subprocess.DEVNULL);commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
with (O/'controller.log').open('ab') as log:p=subprocess.Popen([str(L/'.venv/bin/python'),str(O/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();out={'pid':p.pid,'proc_start_ticks':f[19],'controller':str(O/'batch-controller.py'),'controller_sha256':hashlib.sha256((O/'batch-controller.py').read_bytes()).hexdigest(),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};(O/'controller-launch-process.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
