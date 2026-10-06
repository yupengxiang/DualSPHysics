from pathlib import Path
import json, hashlib, ast, subprocess, datetime

R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L=R/'lagrangian-fluid-lab'; H=L/'campaigns/ds-data-02/handoff_20261003'
O=H/'root_stage1_F5_next34_own_source824_to_registered_GenCase_shared_CPU2_835'
O.mkdir()
controller=r'''from pathlib import Path
import json,hashlib,time,subprocess,fcntl,datetime
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def put(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.xml'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def root(n):return next(H.glob(f'root*_{n}'))
plan_path=root(823)/'source-plan.json';plan=load(plan_path);source_qp=root(824)/'registered-source-generation-request.json';source_q=load(source_qp);source_root=Path(source_q['attempt_root']);rp=source_root/'execution-receipt.json';sp=source_root/'source-generation-report.json'
assert len(plan['candidates'])==34 and plan['candidate_count']==34 and plan['expected_frames']==801 and plan['full_window_s']==[0,16] and plan['T120_held']
while True:
 if rp.exists():
  r=load(rp)
  if r['status']=='completed':
   assert r['returncode']==0 and r['request']['attempt_id']==source_q['attempt_id'];break
  assert r['status'] in ['running','reserved'],f'source generation terminal: {r["status"]}'
 else:
  c=load(root(824)/'controller-launch-process.json');proc=Path('/proc')/str(c['pid']);assert proc.exists(),'source controller missing with no receipt';f=(proc/'stat').read_text().split(') ',1)[1].split();assert f[0]!='Z' and f[19]==c['proc_start_ticks']
 time.sleep(3)
source=load(sp);assert source['status']=='completed' and source['candidate_count']==34 and len(source['cases'])==34 and source['base_motion']['sha256_before']==source['base_motion']['sha256_after']==plan['base_motion_sha256_producer_attested']
sources={c['tag']:c for c in source['cases']};assert len(sources)==34
worker=H/'root_native_source_preflight_tools_003/gencase.py';assert sha(worker)=='6e09e6b83234200e2481ecb9c34d4e9f03fd96996fafd1d166c70e95076d5d07'
gencase=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64');gencase_sha='a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226'
python=str(L/'.venv/bin/python');python_sha='a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae'
launch=H/'root_stage1_home_floor_inventory_dispatch_142/launch.py';results=[]
for c in plan['candidates']:
 s=sources[c['tag']];assert all(s[k]==c[k] for k in ['case_id','physical_case_id','physical_condition_sha256','amplitude_scale','time_scale']);assert s['rows']==641 and s['output_time_first_s']==0 and abs(s['output_time_last_s']-c['motion_duration_s'])<1e-12
 for key in ['definition','owner']:assert sha(s[key]['path'])==s[key]['sha256']
 assert s['definition']['sha256']==c['source_xml_sha256'] and s['owner']['sha256']==c['source_owner_sha256']
 aid=f'root-stage1-f5-next34-{c["tag"].lower()}-own824-genuine-gencase-root835';ap=D/'families/F5'/c['case_id']/aid;assert not ap.exists()
 bp=O/'bindings'/(c['tag']+'-gencase-binding.json')
 b={'schema':'ds02.f5.next34.actual-source824-gencase-binding.v1','case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'family_id':'F5','attempt_id':aid,'definition':s['definition']['path'],'definition_sha256':s['definition']['sha256'],'owner':s['owner']['path'],'owner_sha256':s['owner']['sha256'],'physical_condition_sha256':c['physical_condition_sha256'],'gencase':str(gencase),'gencase_sha256':gencase_sha,'threads':2,'dp_m':0.02,'expected_fluid':None,'actual_counts':None,'assets':[{'source':s['motion']['path'],'sha256':s['motion']['sha256'],'relative_name':'assets/'+c['motion_filename']}],'full_event_window_s':[0,16],'expected_saved_frames':801,'source_generation_receipt':ref(rp),'source_generation_report':ref(sp),'amplitude_scale':c['amplitude_scale'],'time_scale':c['time_scale'],'predictions':{'counts':'prospective only until this own official GenCase producer','initial_placement_QA':'required after this own producer, no inherited pass'},'independent_case_count_increment':0,'q_n_granted':False};put(bp,b)
 q={k:v for k,v in source_q.items() if k not in ['input_files','input_sha256','input_sha256_provenance','command']};q.update(case_id=c['case_id'],physical_case_id=c['physical_case_id'],physical_condition_sha256=c['physical_condition_sha256'],attempt_id=aid,attempt_root=str(ap),kind='cpu',cpu_task_kind='gencase',cpu_threads=2,max_wall_seconds=1800,estimated_storage_bytes=5*1024**3,binding=str(bp),binding_sha256=sha(bp),expected_counts=None,expected_dimension=3,genuine_gencase=True,full801_authorized=False,command=[python,str(worker),'--binding',str(bp),'--output-dir','{attempt_root}/prepared'])
 files=[bp,plan_path,source_qp,rp,sp,worker,Path(s['definition']['path']),Path(s['owner']['path']),launch,Path(source_q['root_inventory_policy_source']),L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(823)/'static-source-validation.json',Path(plan['range_gate'])]
 q['input_files']=[str(p) for p in files]+[python,str(gencase),s['motion']['path']];q['input_sha256']={str(p):sha(p) for p in files};q['input_sha256'].update({python:python_sha,str(gencase):gencase_sha,s['motion']['path']:s['motion']['sha256']});q['input_sha256_provenance']={s['motion']['path']:'actual own Root824 producer report; payload is verified only inside registered runner/worker'};qp=O/'requests'/(c['tag']+'-gencase-request.json');put(qp,q)
 with (D/'runtime/stage1-fullnative-conversion-dispatch.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  while sum(x.get('cpu_threads',0) for x in load(D/'runtime/resource-ledger.json')['reservations'])+2>64:time.sleep(3)
  p=subprocess.run([python,str(launch),str(qp)],cwd=L,capture_output=True,text=True)
 rr=ap/'execution-receipt.json';pr=ap/'prepared/prepared-input-report.json';r=load(rr) if rr.exists() else {};prepared=load(pr) if pr.exists() else {};counts=prepared.get('generated_xml_particle_counts');passed=(r.get('status'),r.get('returncode'))==('completed',0) and p.returncode==0 and prepared.get('case_id')==c['case_id'] and prepared.get('actual_total_particles')==194427 and counts=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658} and prepared.get('actual_generated_constants',{}).get('data2d',{}).get('value')=='false'
 out={'tag':c['tag'],'case_id':c['case_id'],'request':ref(qp),'actual_receipt_path':str(rr),'actual_prepared_report_path':str(pr),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'own_genuine_GenCase_pass':passed,'actual_total_particles':prepared.get('actual_total_particles'),'actual_counts':counts,'independent_case_count_increment':0,'native_initial_QA':'pending registered own Mk50 placement/identity audit','launcher_error':p.stderr[-2000:]};results.append(out);put(O/'actual-progress.json',{'actual_cases':results,'independent_case_count_increment':0});print(json.dumps(out),flush=True);assert passed,out
put(O/'controller-result.json',{'status':'completed','actual_own_GenCase_count':len(results),'cases':results,'no_inherited_native_counts':True,'initial_QA_required_per_condition':True,'independent_case_count_increment':0})
'''
ast.parse(controller)
(O/'batch-controller.py').write_text(controller)
(O/'root-preparation-source.py').write_bytes(Path(__file__).read_bytes())
(O/'controller-contract.json').write_text(json.dumps({'schema':'ds02.f5.next34.Gencase-controller.v1','source_root':824,'own_source_completed0_required':True,'case_count':34,'shared_CPU_lock':'/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/stage1-fullnative-conversion-dispatch.lock','cpu_threads':2,'shared_CPU_reservation_cap':64,'Home_min_free_gib':500,'runtime_worker_unchanged':True,'future_scientific_digests_claimed':False,'root_scientific_payload_reads_or_hashes':False,'independent_case_increment':0},indent=2)+'\n')
assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=R,text=True).strip()
subprocess.run(['git','add','--',str(O.relative_to(R))],cwd=R,check=True)
subprocess.run(['git','commit','-m','ds02: queue each own F5 next34 GenCase after registered source0'],cwd=R,check=True,stdout=subprocess.DEVNULL)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
with (O/'controller.log').open('ab') as log:
 p=subprocess.Popen([str(L/'.venv/bin/python'),str(O/'batch-controller.py')],cwd=L,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split()
out={'pid':p.pid,'proc_start_ticks':f[19],'controller':str(O/'batch-controller.py'),'controller_sha256':hashlib.sha256((O/'batch-controller.py').read_bytes()).hexdigest(),'launch_commit':commit,'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(O/'controller-launch-process.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))
