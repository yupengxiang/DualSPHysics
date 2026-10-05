from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,hashlib,time,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=H/'root_stage1_f4_actual648_N3_XMF_shared_queue_handoff_repair1_669';load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.dat','.bi4','.ibi4','.h5','.hdf5','.csv','.vtk','.vtu','.npy','.npz'},str(p)
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def ready(plan):
 tq=Path(plan['actual648_typed_request']);q=load(tq);a=Path(q['attempt_root']);rp=a/'execution-receipt.json';cp=a/'conversion-report.json'
 while True:
  if rp.is_file():
   r=load(rp)
   if r.get('status') in ['failed','cancelled','blocked']:raise ValueError('Own648 typed failed: '+plan['case_id'])
   if (r.get('status'),r.get('returncode'))==('completed',0):break
  time.sleep(10)
 c=load(cp);assert r['request_sha256']==sha(tq);assert c['conversion_status']=='completed' and c['frames']==1201 and c['particles']==83233 and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'];assert c['hash_scopes']['physical_condition_sha256']==q['physical_condition_sha256'];assert c['time_evidence']['strictly_increasing']
 return tq,q,a,rp,cp,c
def run(planpath):
 try:
  plan=load(planpath);tq,tqv,ta,trp,cp,c=ready(plan);source=Path(plan['source_xmf_request']);q=load(source);sourcebinding=Path(q['command'][q['command'].index('--binding')+1]);b=load(sourcebinding);native=Path(tqv['actual_solver_receipt']);nr=load(native);assert (nr['status'],nr['returncode'])==('completed',0) and sha(native)==tqv['actual_solver_receipt_sha256'];initial=tqv['native_frame0_gate']['actual_report'];assert sha(initial['path'])==initial['sha256'] and initial['pass_result'];assert b['expected_frames']==1201 and b['expected_particles']==83233 and b['physical_window_s']==[0.0,1.2];assert b['physical_condition_sha256']==c['hash_scopes']['physical_condition_sha256']
  b.update(typed_receipt=str(trp),native_receipt=str(native),conversion_report=str(cp),trajectory_h5=str(ta/'trajectory.h5'),source_only=False,execution_allowed=True,root_actual648_request=str(tq),root_actual648_request_sha256=sha(tq),root_actual648_typed_receipt_sha256=sha(trp),root_actual648_conversion_report_sha256=sha(cp),root_source105_preserved_binding=str(sourcebinding),root_source105_preserved_binding_sha256=sha(sourcebinding),root_native_frame0_QA623=initial,root_no_native_or_typed_rerun=True,root_repair_ordinal=1,root_preserved_original666_failure_review='/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_XMF666_actual_shared_conversion_capacity_failure_review_668/actual-shared-conversion-capacity-failure-review.json')
  assert all(isinstance(b[k],str) and Path(b[k]).is_absolute() for k in ['typed_receipt','native_receipt','conversion_report','trajectory_h5']);bp=O/'bindings'/(plan['case_id']+'-actual648-XMF-binding.json');assert not bp.exists();put(bp,b)
  attempt=q['attempt_id']+'-root669';ar=D/'families/F4'/q['case_id']/attempt;assert not ar.exists();md={}
  for raw,dig in q['input_sha256'].items():assert Path(raw).suffix.lower() not in {'.h5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu'} and dig==sha(raw);md[raw]=dig
  for p in [planpath,source,sourcebinding,bp,tq,trp,cp,native,Path(initial['path']),L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json',Path(__file__),O/'percase-actual648-to-XMF-plan-review.json']:md[str(p)]=sha(p)
  md[b['trajectory_h5']]=c['output_sha256'];q['command'][q['command'].index('--binding')+1]=str(bp);q['command'][q['command'].index('--output-dir')+1]='{attempt_root}/xmf'
  for key in ['deferred_input_files','deferred_input_sha256','expected_outputs','future_hashes']:q.pop(key,None)
  q.update(attempt_id=attempt,attempt_root=str(ar),disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,binding=str(bp),binding_sha256=sha(bp),root_dataset_inventory_profile=tqv['root_dataset_inventory_profile'],root_inventory_policy_sha256=tqv['root_inventory_policy_sha256'],root_actual_launch_source=tqv['root_actual_launch_source'],root_actual_launch_source_sha256=tqv['root_actual_launch_source_sha256'],depends_on_attempts=[tqv['attempt_id'],native.parent.name],input_files=sorted(md),input_sha256=md,conversion_report=str(cp),actual_manifest=str(ar/'xmf/manifest.json'),root_scope='Own actual648 full1201 typed -> genuine N3 sidecar only; no native/typed rerun, old source105 untouched, immutable H5 hashes verified by shared runner/exporter; unknown exclusions retained.',independent_case_count_increment=0)
  qp=O/(plan['case_id']+'-xmf-request.json');assert not qp.exists();put(qp,q);r=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,capture_output=True);rp=ar/'execution-receipt.json';a=load(rp) if rp.is_file() else {};mp=ar/'xmf/manifest.json';passed=False
  if (a.get('status'),a.get('returncode'))==('completed',0) and mp.is_file():
   m=load(mp);grids=ET.parse(m['xdmf']).getroot().findall('.//Grid[@GridType="Uniform"]');passed=m['frames']==1201 and m['particles']==83233 and m['source_h5_read_only'] and m['source_h5_sha256']==c['output_sha256'] and len(grids)==1201 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='83233 3' for g in grids);assert passed
  row={'case_id':q['case_id'],'request':str(qp),'actual_receipt':str(rp),'actual_XMF_N3_pass':passed,'launcher_returncode':r.returncode,'status':a.get('status'),'returncode':a.get('returncode'),'manifest':str(mp),'launcher_error':r.stderr[-1000:],'launcher_output':r.stdout[-1000:]}
 except Exception as e:row={'case_id':load(planpath)['case_id'],'status':'controller_preflight_failed','returncode':None,'actual_XMF_N3_pass':False,'launcher_returncode':1,'error':str(e)}
 print(json.dumps(row),flush=True);return row
upstream_controller=H/'root_stage1_f4_typed648_first1_then_NVMe_cap2_controller_649'/'controller-result.json'
assert upstream_controller.parent.is_dir()
while not upstream_controller.is_file():time.sleep(10)
upstream=load(upstream_controller);assert upstream['completed0']==24 and upstream['actual_typed_pass_count']==24
for planpath in sorted((O/'plans').glob('*.json')):
 ready(load(planpath))
print(json.dumps({'actual648_all24_completed0':True,'global_conversion_cap2_handoff':'typed stage drained before first XMF'}),flush=True)
queue=sorted((O/'plans').glob('*.json'));assert len(queue)==24;rows=[run(queue[0])];failed=not rows[0]['actual_XMF_N3_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or (index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,queue[index])]=queue[index];index+=1
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_XMF_N3_pass']:failed=True
summary={'requested':24,'finished':len(rows),'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_XMF_N3_pass_count':sum(r['actual_XMF_N3_pass'] for r in rows),'pending_held':len(queue)-index,'parallel_cap':2,'own648_wait_before_reservation':True,'first_failure_holds_pending':True,'results':rows};put(Path(__file__).parent/'controller-result.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True);raise SystemExit(1 if failed else 0)
