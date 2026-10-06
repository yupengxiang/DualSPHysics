from pathlib import Path
import json,hashlib,subprocess,datetime,ast
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=H/'root_stage1_F2_remaining24_actual_source801_GenCase_after796_registered_cap2_804';O.mkdir(exist_ok=False)
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def root(n):return next(H.glob(f'root*_{n}'))
review=root(801)/'actual-source-generation-review.json';a=load(review);rp=Path(a['actual_report']);assert sha(rp)==a['actual_report_sha256'];src=load(rp);assert src['generated_source_conditions']==24
ar=Path(a['actual_receipt']);r=load(ar);assert (r['status'],r['returncode'])==('completed',0)
corner=root(803)/'actual-integration-review.json';assert load(corner)['stage1_visually_reviewed_corner_domain']['numerical_qualification']=='not_granted'
profile=load(root(801)/'registered-source-generation-request.json');base={k:v for k,v in profile.items() if k.startswith('root_') or k=='resource_window'}
worker=L/'campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1/workers/f2_motion_prepared_gencase_worker.py';g=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64');gd=sha(g);assert gd=='a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226'
for dn in ['bindings','requests']:(O/dn).mkdir()
requests=[]
for c in src['cases']:
 cid=c['case_id'];assert .46<c['receiver_x_m']<.64 and .65<c['rotation_duration_s']<1.2
 for k in ['definition','metadata','owner']:assert sha(c[k]['path'])==c[k]['sha256']
 md=load(c['metadata']['path']);assert md['actual_counts'] is None and md['physical_condition_sha256']==c['physical_condition_sha256'];assert hashlib.sha256(json.dumps(md['physical_condition'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==c['physical_condition_sha256']
 b={'schema':'ds02.f2.stage1.fresh100.motion-safe-gencase-binding.v1','case_id':cid,'physical_case_id':c['physical_case_id'],'family_id':'F2','definition':c['definition']['path'],'definition_sha256':c['definition']['sha256'],'assets':[{'relative_name':Path(c['motion']['path']).name,'xml_name':Path(c['motion']['path']).name,'role':'official GenCase mvrotfile control asset','source':c['motion']['path'],'sha256':c['motion']['sha256'],'digest_origin':'Root801 registered source generation producer; never hashed by Root'}],'dimension':3,'dp_m':.01,'threads':4,'expected_fluid':None,'gencase':str(g),'gencase_sha256':gd,'canonical_physical_binding_sha256':None,'source_plan_physical_condition_sha256':c['physical_condition_sha256'],'predictions':{'counts':None,'mass':None,'native_initial_qa':'pending actual measurement'}}
 bp=O/'bindings'/(cid+'.json');put(bp,b)
 inputs={str(p):sha(p) for p in [bp,worker,g,L/'.venv/bin/python',review,rp,ar,corner,L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_home_floor_inventory_dispatch_142/launch.py',H/'root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json']}
 for k in ['definition','metadata','owner','motion']:inputs[c[k]['path']]=c[k]['sha256']
 attempt='root-stage1-f2-'+cid.lower()+'-actual-gencase-source801-root804';ap=D/'families/F2'/cid/attempt;assert not ap.exists()
 q={**base,'schema':'ds02.runner-request.v2','family_id':'F2','case_id':cid,'physical_case_id':c['physical_case_id'],'physical_condition_sha256':c['physical_condition_sha256'],'source_plan_physical_condition_sha256':c['physical_condition_sha256'],'attempt_id':attempt,'attempt_root':str(ap),'kind':'cpu','cpu_task_kind':'gencase','cpu_threads':4,'launch_owner':'root','worktree_root':str(R),'cwd':str(L),'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'max_wall_seconds':600,'estimated_storage_bytes':512*1024**2,'command':[str(L/'.venv/bin/python'),str(worker),'--binding',str(bp),'--output-dir','{attempt_root}/prepared'],'input_files':sorted(inputs),'input_sha256':inputs,'actual_counts':None,'native_initial_qa_required_before_solver':True,'independent_case_increment':0,'numerical_precision_status':'not_accepted','production_approval':'none','motion_digest_source':'Root801 producer attestation verified inside unchanged registered GenCase worker; Root never reads/hashes DAT'}
 qp=O/'requests'/(cid+'-gencase-request.json');put(qp,q);requests.append(str(qp))
config={'requests':requests,'wait_priority_controller':str(root(796)/'controller-launch-process.json'),'wait_priority_directory':str(root(796)),'maximum_parallel_GenCase_jobs':2,'CPU_threads_per_job':4,'reason_for_wait':'Avoid overlapping the Root796 preflight requiring all scientific CPU leases drained; start only after an actual Root796 science render is live or the verified controller is terminal','source_generation_report':str(rp),'stage1_corner_visual_release':str(corner),'no_new_independent_completed_case_credit':True};put(O/'dispatch-config.json',config)
controller='''from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,subprocess,time,datetime,hashlib,os
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def put(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\\n')
def live(pid,ticks=None):
 p=Path('/proc')/str(pid)
 if not p.exists():return False
 try:
  f=(p/'stat').read_text().split(') ',1)[1].split();return f[0]!='Z' and (ticks is None or f[19]==ticks)
 except FileNotFoundError:return False
c=load(O/'dispatch-config.json');pc=load(c['wait_priority_controller']);P=Path(c['wait_priority_directory']);gate=False
while not gate:
 for qp in P.glob('*-render-request.json'):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json'
  if rp.exists():
   r=load(rp)
   if r['status']=='running' and live(r.get('pid')):gate=True;put(O/'actual-priority-render-live-before-gencase.json',{'pid':r['pid'],'receipt':str(rp),'request':str(qp),'actual_live_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()});break
 if not gate and not live(pc['pid'],pc['proc_start_ticks']):
  assert (P/'controller-result.json').exists(),'Root796 handle absent without terminal evidence: no independent science dispatch'
  gate=True;put(O/'actual-priority-terminal-before-gencase.json',{'controller':pc,'result':str(P/'controller-result.json')})
 if not gate:time.sleep(3)
def run(qp):
 q=load(qp);ap=Path(q['attempt_root']);assert not ap.exists()
 while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+4>64:time.sleep(2)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_home_floor_inventory_dispatch_142/launch.py'),qp],cwd=L,capture_output=True,text=True);rp=ap/'execution-receipt.json';r=load(rp) if rp.exists() else {};passed=False;prep={}
 if (r.get('status'),r.get('returncode'))==('completed',0):
  pp=ap/'prepared/prepared-input-report.json';prep=load(pp);passed=prep['case_id']==q['case_id'] and prep['actual_generated_constants']['data2d']['value']=='false' and prep['actual_total_particles']>0 and prep['generated_xml_particle_counts']['fluid']>0 and all(a['verified_post_gencase_sha256']==a['sha256'] for a in prep['assets'])
 row={'case_id':q['case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_GenCase_pass':passed,'prepared_input_report':str(ap/'prepared/prepared-input-report.json') if passed else None,'actual_total_particles':prep.get('actual_total_particles'),'actual_particle_counts':prep.get('generated_xml_particle_counts'),'independent_case_increment':0,'native_initial_qa_still_required':True,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
qs=c['requests'];rows=[run(qs[0])];failed=not rows[0]['actual_GenCase_pass'];index=1
with ThreadPoolExecutor(max_workers=2) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<2 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_GenCase_pass']:failed=True
summary={'requested':24,'completed0':sum((r.get('status'),r.get('returncode'))==('completed',0) for r in rows),'actual_GenCase_pass_count':sum(r['actual_GenCase_pass'] for r in rows),'pending_held':len(qs)-index,'maximum_parallel_jobs':2,'CPU_threads_per_job':4,'independent_case_increment':0,'results':rows};put(O/'controller-result.json',summary);raise SystemExit(1 if failed else 0)
'''
cp=O/'batch-controller.py';cp.write_text(controller);ast.parse(controller)
p=subprocess.Popen([str(L/'.venv/bin/python'),str(cp)],cwd=L,stdout=(O/'controller.log').open('ab'),stderr=subprocess.STDOUT,start_new_session=True);fields=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();put(O/'controller-launch-process.json',{'pid':p.pid,'proc_start_ticks':fields[19],'controller':str(cp),'controller_sha256':sha(cp),'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'detached_parent_session':True,'actual_GenCase_jobs_started_at_launch':0,'guarded_wait_before_scientific_dispatch':True})
(O/'root-preparation-and-validation.py').write_bytes(Path(__file__).read_bytes());print(json.dumps({'controller_pid':p.pid,'prepared_requests':len(requests),'no_fake_counts_or_credit':True}))
