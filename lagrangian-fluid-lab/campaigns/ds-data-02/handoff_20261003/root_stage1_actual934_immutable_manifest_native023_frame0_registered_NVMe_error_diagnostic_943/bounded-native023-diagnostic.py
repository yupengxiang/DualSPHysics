from pathlib import Path
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
 payload=(json.dumps(result,indent=2)+'\n').encode();assert len(payload)<=1024**2
 with Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock').open('r') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);ledger=json.loads(Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json').read_text());own=[x for x in ledger['reservations'] if x.get('id')==cfg['reservation_id']];assert len(own)==1;others=sum(x.get('new_storage_bytes',0) for x in ledger['reservations'] if x.get('id')!=cfg['reservation_id']);assert shutil.disk_usage('/home/jade').free-others-len(payload)>=max(500*1024**3,ledger['limits']['home_min_free_bytes']);out.write_bytes(payload);fcntl.flock(lock,fcntl.LOCK_UN)
print(json.dumps(result),flush=True);raise SystemExit(0 if result['status']=='diagnostic_completed' else 1)
