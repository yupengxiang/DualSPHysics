from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,time,subprocess,runpy
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');P=L/'campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_081_f3_four_corner_typed_xmf_source_v1';O=H/'root_stage1_f3_actual743_four_full836_renderer023_runtime_plan_748'
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
up=next(H.glob('root_*_771'))/'controller-result.json'
while not up.exists():time.sleep(10)
u=load(up);assert u['completed0']==u['actual_full241_render_pass_count']==24 and u['pending_held']==0
for p in sorted(next(H.glob('root_*_732')).glob('*-render-request.json')):
 q=load(p);r=load(Path(q['attempt_root'])/'execution-receipt.json');assert (r['status'],r['returncode'])==('completed',0) and r['request_sha256']==sha(p)
assert len(list(next(H.glob('root_*_732')).glob('*-render-request.json')))==24
worker=P/'workers/render_native023.py';assert sha(worker)=='5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66';preflight=runpy.run_path(str(worker))['load_manifest'];profile=load(next(next(H.glob('root_*_638')).glob('*-render-request.json')))
def run(planp):
 try:
  plan=load(planp);source=Path(plan['source_request']);assert sha(source)==plan['source_request_sha256'];q=load(source);t=plan['actual743_XMF'];mp=Path(t['manifest']);xr=Path(t['receipt']);xf=Path(t['xdmf']);assert sha(mp)==t['manifest_sha256'] and sha(xr)==t['receipt_sha256'] and sha(xf)==t['xdmf_sha256'];assert (load(xr)['status'],load(xr)['returncode'])==('completed',0)
  m=preflight(mp);cp=Path(m['conversion_report']);c=load(cp);tr=Path(m['typed_receipt']);nr=Path(m['native_receipt']);assert m['frames']==c['frames']==836 and c['particles']==179208 and c['partvtk_validation']['all_passed'];assert c['output_sha256']==m['source_h5_sha256']==t['source_h5_sha256_producer_attested'];assert c['hash_scopes']['physical_condition_sha256']==m['physical_condition_sha256']==q['physical_condition_sha256']
  md={}
  for raw,dig in q['input_sha256'].items():
   s=str(P)+raw[len(str(P).replace('ds-data-02-integration','ds-data-02-f3')):] if raw.startswith(str(P).replace('ds-data-02-integration','ds-data-02-f3')+'/') else raw
   assert sha(s)==dig,s;md[s]=dig
  for p in [source,planp,worker,mp,xf,xr,cp,tr,nr,up,Path(__file__),O/'actual-four-full836-render-plan-review.json',next(H.glob('root_*_740'))/'actual-source-adoption-review.json',next(H.glob('root_*_746'))/'actual-four-full836-XMF-terminal-review.json',L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json',Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython'),Path('/usr/bin/env'),Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json')]:md[str(p)]=sha(p)
  md[m['trajectory_h5']]=c['output_sha256'];cmd=list(q['command']);cmd[cmd.index('--manifest')-1]=str(worker);cmd[cmd.index('--manifest')+1]=str(mp);assert cmd[cmd.index('--output-dir')+1]=='{attempt_root}/render';attempt=q['attempt_id']+'-root748';ar=D/'families/F3'/q['case_id']/attempt;assert not ar.exists()
  for k in ['future_input_files','future_input_sha256','future_outputs','input_hashes']:q.pop(k,None)
  env=dict(q.get('env',{}));env.update({k:'2' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VTK_SMP_MAX_THREADS','VTK_SMP_NUM_THREADS','LP_NUM_THREADS']});env['MESA_GLTHREAD']='false'
  q.update(attempt_id=attempt,attempt_root=str(ar),kind='cpu',cpu_task_kind='audit',launch_owner='root',worktree_root=str(R),cwd=str(L),command=cmd,env=env,worker=str(worker),worker_sha256=sha(worker),disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,cpu_threads=24,max_wall_seconds=14400,estimated_storage_bytes=16*1024**3,contact_pages=35,root_dataset_inventory_profile=profile['root_dataset_inventory_profile'],root_inventory_policy_sha256=profile['root_inventory_policy_sha256'],root_actual_launch_source=profile['root_actual_launch_source'],root_actual_launch_source_sha256=profile['root_actual_launch_source_sha256'],input_files=sorted(md),input_sha256=md,independent_case_count_increment=0)
  qp=O/(q['case_id']+'-render-request.json');assert not qp.exists();put(qp,q)
  p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,capture_output=True);rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False
  if (r.get('status'),r.get('returncode'))==('completed',0):
   v=load(ar/'render/paraview-full-animation-report.json');passed=v['frames']==v['source_frames']==836 and v['all_frames_rendered'] and v['native_identity_axis_preserved'] and v['actual_times_preserved_exactly'] and len(v['outputs']['contact_sheets'])==35
  row={'case_id':q['case_id'],'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full836_render_pass':passed,'launcher_error':p.stderr[-1500:]}
 except Exception as e:row={'case_id':load(planp)['case_id'],'status':'controller_preflight_failed','returncode':None,'actual_full836_render_pass':False,'error':str(e)}
 print(json.dumps(row),flush=True);return row
queue=sorted((O/'plans').glob('*.json'));assert len(queue)==4;rows=[run(queue[0])];failed=not rows[0]['actual_full836_render_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_full836_render_pass']:failed=True
summary={'requested':4,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full836_render_pass_count':sum(r['actual_full836_render_pass'] for r in rows),'pending_held':len(queue)-index,'global_parallel_cap':2,'results':rows};put(Path(__file__).parent/'controller-result.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
