from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,subprocess,time,sys,hashlib,datetime
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text())
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCIENCE;return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n')
c=load(O/'dispatch-config.json');qc=load(c['qa_controller']);result=Path(c['qa_result'])
while not result.exists():
 proc=Path('/proc')/str(qc['pid']);assert proc.exists(),'QA controller missing without terminal evidence; no native release';fields=(proc/'stat').read_text().split(') ',1)[1].split();assert fields[19]==qc['proc_start_ticks'] and fields[0]!='Z';time.sleep(3)
qaresult=load(result);assert qaresult['completed0']==qaresult['actual_initial_QA_pass_count']==24 and qaresult['pending_held']==0
source=load(c['gencase_result']);byid={x['case_id']:x for x in qaresult['results']};baseq=load(c['native_profile_request']);profile={k:v for k,v in baseq.items() if k.startswith('root_') and k not in ['root_reviewed_source_request','root_reviewed_source_request_sha256','root_scope','root730_recipe_visual_gate','root730_gate_required','root_review_required'] or k in ['runtime_entrypoint','runtime_sha256','strict_dispatch_entrypoint','strict_dispatch_sha256','resource_window']};profile['root_dataset_inventory_profile']='root_home_floor_no_legacy_dataset_walk_native_v1';profile['root_gpu_selection_profile']='root_live_all_idle_uuid_leased_eight_solver_v2';profile['root_solver_concurrency_cap']=8
solver=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64');assert sha(solver)=='0415b10e5e32af8b8b7ad2a703f9043dca67df7626eb98f1c05a50856fde29';qs=[]
for row in source['results']:
 cid=row['case_id'];gq=load(row['request']);prep=load(row['prepared_input_report']);gr=load(row['actual_receipt']);qa=byid[cid];qr=load(qa['actual_receipt']);a=load(qa['actual_QA_report']);assert (gr['status'],gr['returncode'])==(qr['status'],qr['returncode'])==('completed',0);assert gr['total_particles']==prep['actual_total_particles'] and gr['fluid_particles']==prep['generated_xml_particle_counts']['fluid'] and gr['solver_dimension_from_gencase']==3;assert a['status']=='pass' and all(a['checks'].values()) and a['prepared_evidence']['total']==prep['actual_total_particles'];prefix=prep['prefix'];xml=Path(prefix+'.xml');assert sha(xml)==prep['xml_sha256'];md={str(p):sha(p) for p in [Path(row['request']),Path(row['actual_receipt']),Path(row['prepared_input_report']),Path(qa['request']),Path(qa['actual_receipt']),Path(qa['actual_QA_report']),result,Path(c['gencase_result']),Path(c['F2_actual_four_corner_visual_gate']),Path(c['native_profile_request']),O/'dispatch-config.json',Path(__file__),xml,solver,L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py',H/'root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py',H/'root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py',H/'root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json']}
 for key,dig in gq['input_sha256'].items():
  if Path(key).suffix.lower() in SCIENCE:md[key]=dig
  else:assert sha(key)==dig;md[key]=dig
 md[prefix+'.bi4']=prep['bi4_sha256']
 for asset in prep['assets']:assert asset['verified_post_gencase_sha256']==asset['sha256'];md[asset['copied_to']]=asset['sha256']
 csv=a['csv_summary']['csv'];md[csv['path']]=csv['sha256'];attempt='root-stage1-f2-'+cid.lower()+'-full401-native-source801-qa809-root811';ar=D/'families/F2'/cid/attempt;assert not ar.exists()
 q={**profile,'schema':'ds02.runner-request.v2','family_id':'F2','case_id':cid,'physical_case_id':gq['physical_case_id'],'physical_condition_sha256':gq['physical_condition_sha256'],'source_plan_physical_condition_sha256':gq['physical_condition_sha256'],'attempt_id':attempt,'attempt_root':str(ar),'kind':'qualification','qualification_stage':'stage1_inside_actual_visually_reviewed_corner_domain','cpu_task_kind':'solver','cpu_threads':2,'omp_threads':2,'launch_owner':'root','worktree_root':str(R),'cwd':str(Path(prefix).parent),'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'root_review_required':False,'max_wall_seconds':7200,'estimated_storage_bytes':10*1024**3,'estimated_peak_gpu_mib':4096,'command':[str(solver),prefix,'{attempt_root}/solver_output','-tmax:4','-tout:0.01'],'gencase_receipt':row['actual_receipt'],'gencase_receipt_sha256':sha(row['actual_receipt']),'initial_qa_receipt':qa['actual_receipt'],'initial_qa_report':qa['actual_QA_report'],'expected_particles':prep['actual_total_particles'],'actual_counts':prep['generated_xml_particle_counts'],'expected_native_frames':401,'expected_dimension':3,'physical_window_s':[0,4],'save_interval_s':.01,'input_files':sorted(md),'input_sha256':md,'independent_case_increment':0,'production_approval':'none','q_n':'not_granted','precision_status':'not_accepted','foreign_process_protection_required':True,'shared_lease_required':True,'root_visual_range_release':c['F2_actual_four_corner_visual_gate'],'source_scientific_digests_origin':'GenCase804/QA809 and source801 registered workers only; never read/hashed by controller'};qp=O/'requests'/(cid+'-native-request.json');put(qp,q);qs.append(str(qp))
put(O/'actual-24-native-enablement-review.json',{'requests':qs,'actual_all24_GenCase_and_initial_QA_completed0':True,'own_counts_measured_not_mother_substituted':True,'full401_complete_window_s':4,'new_independent_case_credit':0,'Q_N_granted':False,'science_payloads_read_or_hashed_by_main_or_controller':False})
def run(qp):
 q=load(qp)
 while True:
  snap=rt.inventory();leased={load(p)['uuid'] for p in (D/'leases').glob('*.json')}
  try:gpu.choose_gpu(snap,leased,4096);break
  except RuntimeError:time.sleep(3)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),qp],cwd=L,text=True,capture_output=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((Path(q['attempt_root'])/'solver_output/data').glob('Part_*.bi4')));passed=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==401;row={'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':qp,'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'actual_full401_native_pass':passed,'native_saved_frame_file_count':frames,'independent_case_increment':0,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
rows=[run(qs[0])];failed=not rows[0]['actual_full401_native_pass'];index=1
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<7 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_full401_native_pass']:failed=True
summary={'requested':24,'completed0':sum((r['status'],r['returncode'])==('completed',0) for r in rows),'actual_full401_native_pass_count':sum(r['actual_full401_native_pass'] for r in rows),'pending_held':len(qs)-index,'maximum_parallel_jobs':7,'results':rows,'independent_case_increment':0};put(O/'controller-result.json',summary);raise SystemExit(1 if failed else 0)
