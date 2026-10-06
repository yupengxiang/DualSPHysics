from pathlib import Path
import json,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));O=H/'root_stage1_actual934_immutable_manifest_native023_frame0_registered_NVMe_error_diagnostic_943';O.mkdir(exist_ok=False);load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();put=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n');old=load(load(root(934)/'controller-config.json')['outer_requests'][0]);w=load(root(934)/'wrapper-requests'/(old['physical_case_id']+'-enabled-wrapper.json'));r=load(Path(old['attempt_root'])/'execution-receipt.json');assert (r['status'],r['returncode'])==('failed',1);assert not (Path(old['attempt_root'])/'render').exists()
worker=O/'bounded-native023-diagnostic.py';worker.write_text('''from pathlib import Path
import os,json,sys,subprocess,tempfile,time,signal,shutil,fcntl,traceback
cfg=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);cache=Path(cfg['nvme_root']);cache.mkdir(parents=True,exist_ok=True);assert cache.stat().st_dev!=Path('/home/jade').stat().st_dev;assert shutil.disk_usage(cache).free>=100*1024**3+24*1024**3
stage=Path(tempfile.mkdtemp(prefix=cfg['attempt_id']+'-',dir=cache));render=stage/'render';render.mkdir();stdout_path=stage/'renderer.stdout.log';stderr_path=stage/'renderer.stderr.log';argv=[cfg['pvpython'],'--force-offscreen-rendering',cfg['renderer'],'--manifest',cfg['manifest'],'--output-dir',str(render),'--diagnostic-frames','0'];env=os.environ.copy();env.update(cfg['render_environment']);result={'schema':'ds02.registered.native023.frame0-failure-diagnostic.v1','expanded_argv':argv,'full_native_render_requested':False,'full_native_render_pass':False,'case_credit':0,'source934_first_failure_preserved':True,'science_payload_IO_only_inside_registered_ParaView_child':True,'science_payload_IO_by_orchestrator':False};p=None;started=time.monotonic()
def stop_owned():
 if p is not None and p.poll() is None:
  os.killpg(p.pid,signal.SIGTERM)
  try:p.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
def on_signal(signum,frame):raise RuntimeError('owned diagnostic received signal '+str(signum))
signal.signal(signal.SIGTERM,on_signal);signal.signal(signal.SIGINT,on_signal)
def tail(path):
 if not path.exists():return ''
 with path.open('rb') as f:f.seek(max(0,path.stat().st_size-16384));return f.read(16384).decode('utf-8',errors='replace')
try:
 with stdout_path.open('wb') as stdout,stderr_path.open('wb') as stderr:
  p=subprocess.Popen(argv,cwd=cfg['cwd'],env=env,stdout=stdout,stderr=stderr,start_new_session=True);result.update(pid=p.pid,pgid=os.getpgid(p.pid));reason=None
  while p.poll() is None:
   used=sum(x.stat().st_size for x in stage.rglob('*') if x.is_file())
   if used>24*1024**3:reason='private stage cap exceeded'
   elif shutil.disk_usage(cache).free<100*1024**3:reason='NVMe free floor reached'
   elif time.monotonic()-started>1100:reason='bounded diagnostic wall limit reached'
   if reason:stop_owned();break
   time.sleep(.2)
  result.update(returncode=p.wait(),termination_reason=reason)
 report=render/'paraview-full-animation-report.json'
 if report.exists():
  a=json.loads(report.read_text());result.update(diagnostic_report={'frames':a['frames'],'source_frames':a['source_frames'],'diagnostic_only':a['diagnostic_only'],'frame_selection':a['frame_selection'],'all_frames_rendered':a['all_frames_rendered'],'nonfinite_active_states':a['nonfinite_active_states'],'native_identity_axis_preserved':a['native_identity_axis_preserved'],'actual_times_preserved_exactly':a['actual_times_preserved_exactly'],'frame_diagnostics':a['frame_diagnostics']})
 result['status']='diagnostic_completed' if result['returncode']==0 and result.get('diagnostic_report',{}).get('frame_selection')==[0] else 'diagnostic_failed'
except BaseException:
 stop_owned();result.update(status='diagnostic_exception',traceback=traceback.format_exc(),returncode=p.returncode if p else None)
finally:
 result.update(stdout_tail=tail(stdout_path),stderr_tail=tail(stderr_path),elapsed_seconds=time.monotonic()-started,private_stage_removed=True)
 shutil.rmtree(stage)
 # Publish only the bounded diagnostic JSON, counting all other live reservations.
 payload=(json.dumps(result,indent=2)+'\\n').encode();assert len(payload)<=1024**2
 with Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock').open('r') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);ledger=json.loads(Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json').read_text());own=[x for x in ledger['reservations'] if x.get('id')==cfg['reservation_id']];assert len(own)==1;others=sum(x.get('new_storage_bytes',0) for x in ledger['reservations'] if x.get('id')!=cfg['reservation_id']);assert shutil.disk_usage('/home/jade').free-others-len(payload)>=max(500*1024**3,ledger['limits']['home_min_free_bytes']);out.write_bytes(payload);fcntl.flock(lock,fcntl.LOCK_UN)
print(json.dumps(result),flush=True);raise SystemExit(0 if result['status']=='diagnostic_completed' else 1)
''');compile(worker.read_text(),str(worker),'exec')
aid='root-stage1-f6-s0625-yawm06-native023-frame0-NVMe-error-diagnostic-root943';ar=D/'families'/old['family_id']/old['case_id']/aid;assert not ar.exists();config=O/'diagnostic-config.json';put(config,{'pvpython':w['pvpython'],'renderer':w['renderer'],'manifest':w['manifest'],'render_environment':w['render_environment'],'nvme_root':'/tmp/ds02-visual-diagnostic-cache-root943','cwd':str(L),'attempt_id':aid,'reservation_id':'/'.join([old['family_id'],old['case_id'],aid])})
q={k:v for k,v in old.items() if k.startswith('root_')};inputs=old['input_sha256'].copy();inputs.update({str(worker):sha(worker),str(config):sha(config),str(root(934)/'controller-result.json'):sha(root(934)/'controller-result.json'),str(root(937)/'preflight.json'):sha(root(937)/'preflight.json')});q.update(schema='ds02.runner-request.v2',family_id=old['family_id'],case_id=old['case_id'],physical_case_id=old['physical_case_id'],physical_condition_sha256=old['physical_condition_sha256'],attempt_id=aid,attempt_root=str(ar),kind='cpu',cpu_task_kind='audit',cpu_threads=24,max_wall_seconds=1200,estimated_storage_bytes=64*1024**2,launch_owner='root',worktree_root=str(R),cwd=str(L),command=[str(L/'.venv/bin/python'),str(worker),str(config),'{attempt_root}/native023-error-diagnostic.json'],input_files=sorted(inputs),input_sha256=inputs,source_h5_producer_sha256=old['source_h5_producer_sha256'],disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,independent_case_count_increment=0,full_native_render_requested=False,diagnostic_frame_selection=[0]);put(O/'enabled-diagnostic-request.json',q)
controller=O/'diagnostic-controller.py';controller.write_text('''from pathlib import Path
import json,runpy
O=Path(__file__).parent;cfg=json.loads((O/'controller-config.json').read_text());p=runpy.run_path(cfg['fair_dispatch'])['dispatch'](cfg['request']);result={'launcher_returncode':p.returncode,'stdout_tail':p.stdout[-40000:],'stderr_tail':p.stderr[-16384:],'case_credit':0};(O/'controller-result.json').write_text(json.dumps(result,indent=2)+'\\n');print(json.dumps(result),flush=True);raise SystemExit(p.returncode)
''');put(O/'controller-config.json',{'fair_dispatch':str(root(928)/'fair_CPU_dispatch.py'),'request':str(O/'enabled-diagnostic-request.json')});put(O/'metadata-only-preflight.json',{'original934_failed1_immutable':True,'bounded_original023_frame0_not_full_retry':True,'nested_environment_same934':True,'CPU24_env2_shared_cap2':True,'H5_input_hash_retained_from_actual_producer_only':old['source_h5_producer_sha256'],'NVMe24GiB_limit100GiB_floor':True,'Home_only_bounded_diagnostic_JSON_1MiB':True,'source_render_science_unchanged':True,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print(O)
