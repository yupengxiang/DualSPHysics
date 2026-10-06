from pathlib import Path
import os,json,subprocess,sys,traceback
cfg=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);env=os.environ.copy();env.update(cfg['render_environment']);argv=[cfg['pvpython'],'--force-offscreen-rendering',cfg['probe_script']]
result={'expanded_argv':argv,'science_payload_IO':False,'environment_allowlist':{k:env.get(k) for k in ['PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','LD_LIBRARY_PATH','HDF5_PLUGIN_PATH','HDF5_PLUGIN_PRELOAD']},'render_environment':cfg['render_environment']}
try:
 p=subprocess.Popen(argv,cwd=cfg['cwd'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,text=True)
 result.update(pid=p.pid,pgid=os.getpgid(p.pid));stdout,stderr=p.communicate(timeout=90);result.update(returncode=p.returncode,stdout_tail=stdout[-16384:],stderr_tail=stderr[-16384:],status='imports_pass' if p.returncode==0 else 'imports_failed')
except BaseException:
 if 'p' in locals() and p.poll() is None:
  p.terminate()
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:p.kill();p.wait()
 result.update(status='probe_exception',traceback=traceback.format_exc())
out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);raise SystemExit(0 if result['status']=='imports_pass' else 1)
