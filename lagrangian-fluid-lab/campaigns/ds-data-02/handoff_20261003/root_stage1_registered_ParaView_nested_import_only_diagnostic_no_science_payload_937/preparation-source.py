from pathlib import Path
import json,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));O=H/'root_stage1_registered_ParaView_nested_import_only_diagnostic_no_science_payload_937';O.mkdir(exist_ok=False)
load=lambda p:json.loads(Path(p).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();put=lambda p,v:Path(p).write_text(json.dumps(v,indent=2)+'\n')
cfg=load(root(934)/'controller-config.json');old=load(cfg['outer_requests'][0]);wrapper=load(root(934)/'wrapper-requests'/(old['physical_case_id']+'-enabled-wrapper.json'))
pvscript=O/'import_probe.py';pvscript.write_text('''import json,sys,traceback
result={'science_payload_IO':False}
try:
 import numpy
 from PIL import Image,ImageDraw
 from paraview import servermanager
 from paraview.simple import GetAnimationScene,GetParaViewVersion,Render,SaveScreenshot,SaveState,XDMFReader
 from vtkmodules.util.numpy_support import vtk_to_numpy
 result.update(status='imports_pass',paraview_version=str(GetParaViewVersion()),python_version=sys.version)
except BaseException:
 result.update(status='imports_failed',traceback=traceback.format_exc())
print(json.dumps(result),flush=True)
raise SystemExit(0 if result['status']=='imports_pass' else 1)
''')
worker=O/'nested_probe.py';worker.write_text('''from pathlib import Path
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
out.write_text(json.dumps(result,indent=2)+'\\n');print(json.dumps(result),flush=True);raise SystemExit(0 if result['status']=='imports_pass' else 1)
''')
config=O/'probe-config.json';put(config,{'pvpython':wrapper['pvpython'],'render_environment':wrapper['render_environment'],'probe_script':str(pvscript),'cwd':str(L),'science_payload_IO':False})
aid='root-stage1-registered-pv-nested-import-only-no-H5-root937';ar=D/'families/F6/F6_METADATA_PARAVIEW_IMPORT_DIAGNOSTIC'/aid;assert not ar.exists()
inputs=[worker,pvscript,config,Path(wrapper['pvpython']),L/'.venv/bin/python',root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(64)/'resource-window-approval.json',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json')]
q={k:v for k,v in old.items() if k.startswith('root_')};q.update(schema='ds02.runner-request.v2',family_id='F6',case_id='F6_METADATA_PARAVIEW_IMPORT_DIAGNOSTIC',attempt_id=aid,attempt_root=str(ar),kind='cpu',cpu_task_kind='audit',cpu_threads=2,max_wall_seconds=120,estimated_storage_bytes=1024**2,launch_owner='root',worktree_root=str(R),cwd=str(L),command=[str(L/'.venv/bin/python'),str(worker),str(config),'{attempt_root}/import-diagnostic.json'],input_files=[str(p) for p in inputs],input_sha256={str(p):sha(p) for p in inputs},disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,independent_case_count_increment=0,science_payload_IO=False)
put(O/'registered-import-request.json',q);put(O/'preflight.json',{'source934_failure_preserved':True,'no_H5_BI4_CSV_DAT_VTK_inputs_or_readers_instantiated':True,'imports_only':True,'environment_matches934_nested_child':True,'CPU2_wall120':True,'case_credit':0});(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());print(O)
