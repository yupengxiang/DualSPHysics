from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,time,subprocess,runpy,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');P=L/'campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_103_actual_root718_queue_gate_root023_v1';O=H/'root_stage1_f6_actual722_full241_renderer023_complete_runtime_plan_732'
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
up=next(H.glob('root_*_716'))/'controller-result.json'
while not up.exists():time.sleep(10)
u=load(up);assert u['completed0']==u['actual_full1201_render_pass_count']==24 and u['pending_held']==0
upq=sorted(next(H.glob('root_*_715')).glob('*render-request.json'));assert len(upq)==24
for p in upq:
 q=load(p);r=load(Path(q['attempt_root'])/'execution-receipt.json');assert (r['status'],r['returncode'])==('completed',0) and r['request_sha256']==sha(p)
profile=load(upq[0]);worker=P/'workers/render_native023.py';assert sha(worker)=='5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66';preflight=runpy.run_path(str(worker))['load_manifest'];regp=next(H.glob('root_*_722'))/'actual-all24-XMF-terminal-registration.json';reg=load(regp);records={x['case_id']:x for x in reg['cases']};assert len(records)==24
print(json.dumps({'actualF4_716_all24_terminal':True,'actualF6_722_all24_XMF':True,'launch':'first1 then shared2 CPU24/env2'}),flush=True)
def run(planp):
 try:
  plan=load(planp);source=Path(plan['source_request']);assert sha(source)==plan['source_request_sha256'];q=load(source);cid=q['case_id'];t=records[cid];mp=Path(t['actual_manifest']);xr=Path(t['actual_receipt']);xf=Path(t['actual_case_xmf']);assert sha(mp)==t['actual_manifest_sha256'] and sha(xr)==t['actual_receipt_sha256'] and sha(xf)==t['actual_case_xmf_sha256'];rv=load(xr);assert (rv['status'],rv['returncode'])==('completed',0)
  m=preflight(mp);assert m['frames']==241 and m['particles']==417505 and m['source_h5_read_only'];cp=Path(m['conversion_report']);c=load(cp);tr=Path(m['typed_receipt']);nr=Path(m['native_receipt']);assert c['conversion_status']=='completed' and c['frames']==241 and c['particles']==417505 and c['partvtk_validation']['all_passed'] and c['solver_dimension']['solver_dimension']==3;assert c['output_sha256']==m['source_h5_sha256']==q['actual_h5_producer_sha256'];assert c['hash_scopes']['physical_condition_sha256']==m['physical_condition_sha256']==q['physical_condition_sha256'];assert all((load(p)['status'],load(p)['returncode'])==('completed',0) for p in (tr,nr));grids=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(grids)==241 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='417505 3' for g in grids)
  md={}
  for raw,dig in q['input_sha256'].items():assert sha(raw)==dig,raw;md[raw]=dig
  for p in [source,planp,worker,Path(q['render_binding']),mp,xf,xr,cp,tr,nr,regp,up,Path(__file__),O/'actual722-render-plan-review.json',next(H.glob('root_*_731'))/'actual-source-adoption-review.json',L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json',Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython'),Path('/usr/bin/env'),Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json')]:md[str(p)]=sha(p)
  md[m['trajectory_h5']]=c['output_sha256'];cmd=list(q['command']);cmd[cmd.index('--manifest')-1]=str(worker);cmd[cmd.index('--manifest')+1]=str(mp);assert cmd[cmd.index('--output-dir')+1]=='{attempt_root}/render';attempt=q['attempt_id']+'-root732';ar=D/'families/F6'/cid/attempt;assert not ar.exists()
  for key in ['future_input_files','future_input_sha256','future_input_hash_sources','future_outputs','future_hashes_null','disabled_reason']:q.pop(key,None)
  q.update(schema='ds02.runner-request.v2',attempt_id=attempt,attempt_root=str(ar),kind='cpu',cpu_task_kind='audit',launch_owner='root',worktree_root=str(R),cwd=str(L),command=cmd,worker=str(worker),worker_sha256=sha(worker),disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,cpu_threads=24,declared_cpu_cores=24,max_wall_seconds=14400,contact_pages=11,root_dataset_inventory_profile=profile['root_dataset_inventory_profile'],root_inventory_policy_sha256=profile['root_inventory_policy_sha256'],root_actual_launch_source=profile['root_actual_launch_source'],root_actual_launch_source_sha256=profile['root_actual_launch_source_sha256'],input_files=sorted(md),input_sha256=md,depends_on_attempts=[Path(xr).parent.name,Path(tr).parent.name],root_scope='Actual722 all24 own full241 N3 XMF and actual716 full1201 rendererdrain -> Root023 full native allsavedtime view; exact arrays immutable; numerical precision notaccepted.',independent_case_count_increment=0)
  required=('family_id','case_id','attempt_id','kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','worktree_root');assert all(k in q for k in required) and q['estimated_storage_bytes']>0;qp=O/(cid+'-render-request.json');assert not qp.exists();put(qp,q)
  p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,capture_output=True);rp=ar/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False
  if (r.get('status'),r.get('returncode'))==('completed',0):
   v=load(ar/'render/paraview-full-animation-report.json');passed=v['frames']==v['source_frames']==241 and v['all_frames_rendered'] and v['native_identity_axis_preserved'] and v['actual_times_preserved_exactly'] and len(v['outputs']['contact_sheets'])==11
  row={'case_id':cid,'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full241_render_pass':passed,'launcher_error':p.stderr[-1500:]}
 except Exception as e:row={'case_id':load(planp)['case_id'],'status':'controller_preflight_failed','returncode':None,'actual_full241_render_pass':False,'error':str(e)}
 print(json.dumps(row),flush=True);return row
queue=sorted((O/'plans').glob('*.json'));assert len(queue)==24;rows=[run(queue[0])];failed=not rows[0]['actual_full241_render_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_full241_render_pass']:failed=True
summary={'requested':24,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full241_render_pass_count':sum(r['actual_full241_render_pass'] for r in rows),'pending_held':len(queue)-index,'global_parallel_cap':2,'results':rows};put(Path(__file__).parent/'controller-result.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
