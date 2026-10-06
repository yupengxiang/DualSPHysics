from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import subprocess,json,hashlib,time,runpy,xml.etree.ElementTree as ET,fcntl,shutil
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=H/'root_stage1_F4_actual669_remaining22_render_CPU_capacity_wait_distinct_successor_856';P=next((L/'campaigns/ds-data-02/families/F4/handoff_20261003').glob('root_followup_107_*'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.dat','.csv','.bi4','.ibi4','.vtk','.vtu','.npy','.npz'},str(p)
 return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def await_controller(number,expected,passkey=None):
 cp=next(H.glob('root_*_'+str(number)))/'controller-result.json'
 while not cp.exists():time.sleep(10)
 v=load(cp);assert v['completed0']==expected and v['pending_held']==0
 if passkey:assert v[passkey]==expected
 return cp
upstream_xmf=await_controller(670,24,'actual_XMF_N3_pass_count')
upstream_render=H/'root_stage1_f4_root638_recovered_artifacts_successor_queue_gate_766/successor-queue-gate.json'
gate=load(upstream_render);assert gate['status']=='ready-for-successor-render-queue' and gate['original_completed0_count']==22 and gate['recovered_artifact_audit_completed0_count']==2 and gate['all_previous_render_processes_drained'] and gate['old_renderer_exit_codes_unknown_preserved']
for row in gate['completed_originals']:
 rp=Path(row['receipt']);r=load(rp);assert sha(rp)==row['receipt_sha256'] and (r.get('status'),r.get('returncode'))==('completed',0)
for row in gate['unknown_originals']:assert sha(row['old_receipt'])==row['old_receipt_sha256'] and load(row['old_receipt']).get('returncode') is None
for row in gate['independent_actual_audits']:
 rp=Path(row['receipt']);r=load(rp);assert sha(rp)==row['receipt_sha256'] and (r.get('status'),r.get('returncode'))==('completed',0) and sha(row['audit_report'])==row['audit_report_sha256']
prior=sorted(next(H.glob('root_*_638')).glob('*render-request.json'));assert len(prior)==24
print(json.dumps({'actual669_XMF24_completed0':True,'actual638_original_render22_completed0':True,'recovered_artifacts2_actual_audits_completed0':True,'old_renderer_exit_unknown_preserved':True,'global_renderer_cap2_handoff':'all previous shared renders drained'}),flush=True)
preflight=runpy.run_path(str(P/'workers/verify_root669_xmf_render_binding.py'))['preflight_render_binding'];adoption=next(H.glob('root_*_687'))/'actual-source-adoption-review.json';profile=load(prior[0])
def dispatch(qp,q):
 with (D/'runtime/stage1-fullnative-render-registration.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while True:
   ledger=load(D/'runtime/resource-ledger.json');cpu=sum(x.get('cpu_threads',0) for x in ledger['reservations']);reserved=sum(x.get('new_storage_bytes',0) for x in ledger['reservations']);renderers=sum(x.get('cpu_threads',0)==24 for x in ledger['reservations'])
   if cpu+q['cpu_threads']+2<=64 and renderers<2 and shutil.disk_usage('/home/jade').free-reserved-q['estimated_storage_bytes']-2*1024**3>=ledger['limits']['home_min_free_bytes']:break
   time.sleep(3)
  p=subprocess.Popen([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),str(qp)],cwd=L,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE);rp=Path(q['attempt_root'])/'execution-receipt.json'
  while p.poll() is None:
   if rp.exists() and load(rp)['status']=='running':break
   time.sleep(.2)
 stdout,stderr=p.communicate();return subprocess.CompletedProcess(p.args,p.returncode,stdout,stderr)
def run(planpath):
 try:
  plan=load(planpath);cid=plan['case_id'];xq=Path(plan['actual669_request']);x=load(xq);xa=Path(x['attempt_root']);xr=xa/'execution-receipt.json';rv=load(xr);assert (rv['status'],rv['returncode'])==('completed',0) and rv['request_sha256']==sha(xq);mp=xa/'xmf/manifest.json';m=load(mp);cp=Path(m['conversion_report']);c=load(cp);tr=Path(m['typed_receipt']);tv=load(tr);native=Path(m['native_receipt']);nv=load(native);assert (tv['status'],tv['returncode'])==(nv['status'],nv['returncode'])==('completed',0);assert c['conversion_status']=='completed' and c['frames']==1201 and c['particles']==83233 and c['solver_dimension']['solver_dimension']==3 and c['partvtk_validation']['all_passed'];assert m['frames']==1201 and m['particles']==83233 and m['source_h5_read_only'] and m['source_h5_sha256']==c['output_sha256'];assert m['physical_case_id']==cid and m['physical_condition_sha256']==c['hash_scopes']['physical_condition_sha256'];xf=Path(m['xdmf']);assert sha(xf)==m['xdmf_sha256'];grids=ET.parse(xf).getroot().findall('.//Grid[@GridType="Uniform"]');assert len(grids)==1201 and all(g.find('Geometry/DataItem').get('Dimensions')==g.find('Attribute[@Name="velocity"]/DataItem').get('Dimensions')=='83233 3' for g in grids)
  source=Path(plan['source_render_request']);q=load(source);sb=Path(plan['source_renderer_binding']);b=load(sb);scope=dict(b['physical_scope']);scope.update(actual_scope_sha256=m['physical_condition_sha256'],source_binding_condition_sha256=b['physical_condition_sha256'],status='actual648_and669_producer_scope_confirmed_forecast_legacy_hash_preserved_no_precision_approval');b['physical_scope']=scope;b['source_binding_physical_condition_sha256']=b['physical_condition_sha256'];b['physical_condition_sha256']=m['physical_condition_sha256'];actualbp=Path(__file__).parent/(cid+'-actual648-669-render-binding.json');assert not actualbp.exists();put(actualbp,b)
  typed={'receipt':{'path':str(tr),'sha256':sha(tr),'status':tv['status'],'returncode':tv['returncode']},'conversion_report':{**c,'path':str(cp),'sha256':sha(cp),'physical_condition_sha256':m['physical_condition_sha256']},'trajectory_h5':{'path':m['trajectory_h5'],'sha256':c['output_sha256']},'native_receipt':{'path':str(native),'sha256':sha(native)},'physical_scope':scope};checked_manifest={**m,'uniform_grid_count':len(grids),'n3_shapes':{'positions':'N 3','velocity':'N 3'}};checked_receipt={**rv,'path':str(xr),'sha256':sha(xr)};check=preflight(b,typed648=typed,xmf_receipt=checked_receipt,xmf_manifest=checked_manifest);assert check['status']=='READY_FOR_ROOT023';proof=Path(__file__).parent/(cid+'-actual669-render-preflight.json');assert not proof.exists();put(proof,{'source_binding':str(sb),'source_binding_sha256':sha(sb),'actual648_typed_receipt':str(tr),'actual_conversion_report':str(cp),'actual669_request':str(xq),'actual669_receipt':str(xr),'actual669_manifest':str(mp),'actual_grid_count':len(grids),'actual_N3_shapes':'83233 3','shape_summary_derived_from_actual_XML_original_manifest_unmodified':True,'physical_scope':scope,'preflight':check,'case_increment':0})
  attempt=q['attempt_id']+'-CPU-admission-successor-root923';ar=D/'families/F4'/cid/attempt;assert not ar.exists();md={}
  for raw,dig in q['input_sha256'].items():assert Path(raw).suffix.lower() not in {'.h5','.hdf5','.dat','.csv','.bi4','.ibi4','.vtk','.vtu'} and sha(raw)==dig,raw;md[raw]=dig
  for p in [source,sb,actualbp,planpath,proof,xq,xr,mp,xf,cp,tr,native,adoption,upstream_xmf,upstream_render,Path(__file__),O/'controller-config.json',Path(cfg['retirement_proof']),L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json',Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython'),Path('/usr/bin/env'),Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json')]:md[str(p)]=sha(p)
  md[str(Path(x['xmf_binding']['path']))]=sha(x['xmf_binding']['path']);md[str(H/'root_stage1_f4_wait690_runtime_fields_output_contract_prelaunch_interception_714'/'prelaunch-contract-interception-review.json')]=sha(H/'root_stage1_f4_wait690_runtime_fields_output_contract_prelaunch_interception_714'/'prelaunch-contract-interception-review.json');md[m['trajectory_h5']]=c['output_sha256'];cmd=list(q['command']);cmd[cmd.index('--manifest')+1]=str(mp);cmd[cmd.index('--output-dir')+1]='{attempt_root}/render'
  for key in ['deferred_input_files','deferred_input_sha256','expected_outputs','future_hashes']:q.pop(key,None)
  q.update(schema='ds02.runner-request.v2',launch_owner='root',worktree_root=str(R),cwd=str(L),estimated_storage_bytes=profile['estimated_storage_bytes'],attempt_id=attempt,attempt_root=str(ar),command=cmd,disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,cpu_threads=24,cpu_task_kind='audit',kind='cpu',max_wall_seconds=14400,root_dataset_inventory_profile=profile['root_dataset_inventory_profile'],root_inventory_policy_sha256=profile['root_inventory_policy_sha256'],root_actual_launch_source=profile['root_actual_launch_source'],root_actual_launch_source_sha256=profile['root_actual_launch_source_sha256'],manifest=str(mp),case_xmf=str(xf),trajectory_h5=m['trajectory_h5'],physical_scope=scope,physical_condition_sha256=m['physical_condition_sha256'],source_binding_physical_condition_sha256=b['source_binding_physical_condition_sha256'],actual_renderer_binding=str(actualbp),input_files=sorted(md),input_sha256=md,depends_on_attempts=[x['attempt_id'],Path(tr).parent.name],root_actual669_preflight=str(proof),root_actual669_preflight_sha256=sha(proof),root_scope='Actual own669 N3 XMF with actual own648 full1201 pass -> Root023 fullnative view only after766 recovered artifact and natural-drain gate. Env2 CPU24, immutable arrays; numerical precision notaccepted; visual review delegated under current user GOAL.',independent_case_count_increment=0)
  required=('family_id','case_id','attempt_id','kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','worktree_root');assert all(k in q for k in required);assert q['launch_owner']=='root' and q['command'][q['command'].index('--output-dir')+1]=='{attempt_root}/render';qp=O/(cid+'-render-request.json');assert not qp.exists();put(qp,q);r=dispatch(qp,q);rp=ar/'execution-receipt.json';receipt=load(rp) if rp.exists() else {};passed=False
  if (receipt.get('status'),receipt.get('returncode'))==('completed',0):
   report=load(ar/'render/paraview-full-animation-report.json');passed=report['frames']==report['source_frames']==1201 and report['all_frames_rendered'] and report['native_identity_axis_preserved'] and report['actual_times_preserved_exactly'];assert passed
  row={'case_id':cid,'request':str(qp),'actual_receipt':str(rp),'status':receipt.get('status'),'returncode':receipt.get('returncode'),'launcher_returncode':r.returncode,'actual_full1201_render_pass':passed,'launcher_error':r.stderr[-1000:]}
 except Exception as e:row={'case_id':load(planpath)['case_id'],'status':'controller_preflight_failed','returncode':None,'launcher_returncode':1,'actual_full1201_render_pass':False,'error':str(e)}
 print(json.dumps(row),flush=True);return row
cfg=load(O/'controller-config.json');assert load(cfg['retirement_proof'])['same_metadata_handle_retired'];assert len(cfg['preserved_actual856_completed6'])==6;queue=cfg['queue'];rows=[];failed=False;index=0
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(queue) and not failed):
  while len(active)<2 and index<len(queue) and not failed:active[pool.submit(run,Path(queue[index]))]=queue[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row);failed|=not row['actual_full1201_render_pass'];put(O/'actual-progress.json',{'results':rows,'pending_not_launched':len(queue)-index,'case_credit':0})
summary={'requested':24,'original_already_completed0':8,'new_requested':16,'new_completed0':sum(r['actual_full1201_render_pass'] for r in rows),'completed0':8+sum(r['actual_full1201_render_pass'] for r in rows),'actual_full1201_render_pass_count':8+sum(r['actual_full1201_render_pass'] for r in rows),'pending_held':len(queue)-index,'global_parallel_cap':2,'source_already_completed0_cases':cfg['original_actual_completed0_cases'],'results':rows,'case_credit':0};put(O/'controller-result.json',summary);raise SystemExit(1 if failed else 0)
