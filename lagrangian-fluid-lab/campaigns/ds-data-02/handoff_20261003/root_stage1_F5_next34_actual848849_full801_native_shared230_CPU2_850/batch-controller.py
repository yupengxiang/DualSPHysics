from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,hashlib,subprocess,time,sys,datetime,shutil
O=Path(__file__).parent;R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text())
def root(n):return next(H.glob(f'root*_{n:03d}'))
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCIENCE;return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');t.replace(p)
source=root(823)/'source-plan.json';plan=load(source);assert len(plan['candidates'])==34
basepath=next(root(808).glob('*full801-native-request.json'));base=load(basepath);profile={k:v for k,v in base.items() if (k.startswith('root_') and k not in ['root_reviewed_source_request','root_reviewed_source_request_sha256','root_scope']) or k in ['runtime_entrypoint','runtime_sha256','strict_dispatch_entrypoint','strict_dispatch_sha256','resource_window']}
assert profile['resource_window']['gpu_hours']==512 and profile['resource_window']['cpu_core_hours']==3840 and profile['resource_window']['qualification_attempts']==1024 and profile['resource_window']['production_attempts']==720
solver=Path(base['command'][0]);assert sha(solver)=='0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29'
gate=root(807)/'actual-integration-review.json';decisions=load(gate)['decisions'];assert len(decisions)==2
for dp in decisions:
 d=load(dp);assert d['status']=='visual-approved-by-delegated-agent' and d['actual_frames']==801 and d['actual_particles']==194427 and d['actual_fluid_particles']==31658 and d['actual_last_time_s']>=16
put(O/'actual-visual-range-release.json',{'actual_endpoint_review':ref(gate),'actual_endpoint_decisions':[ref(p) for p in decisions],'amplitude_scale_range':[.85,1.15],'time_scale_range':[.8,1.0],'T120_released':False,'full_window_s':[0,16],'expected_saved_frames':801,'Q_N_granted':False,'independent_case_increment':0})
def make_request(c):
 assert .85<=c['amplitude_scale']<=1.15 and .8<=c['time_scale']<=1.0
 gp=root(848)/'requests'/(c['tag']+'-gencase-request.json');qp=root(849)/'requests'/(c['tag']+'-initial-QA-request.json')
 while True:
  if qp.exists():
   qa=load(qp);qr=Path(qa['attempt_root'])/'execution-receipt.json'
   if qr.exists():
    rr=load(qr)
    if rr['status']=='completed':assert rr['returncode']==0;break
    assert rr['status'] in ['reserved','running']
  terminal=root(849)/'controller-result.json'
  if terminal.exists():assert load(terminal)['actual_own_initial_QA_count']==34
  else:
   launch=load(root(849)/'controller-launch-process.json');proc=Path('/proc')/str(launch['pid']);assert proc.exists(),'Own QA scheduler missing without terminal report';f=(proc/'stat').read_text().split(') ',1)[1].split();assert f[19]==launch['proc_start_ticks'] and f[0]!='Z'
  time.sleep(3)
 gq=load(gp);gr=Path(gq['attempt_root'])/'execution-receipt.json';g=load(gr);pp=Path(gq['attempt_root'])/'prepared/prepared-input-report.json';p=load(pp);ar=Path(qa['attempt_root'])/'initial-qa/placement/c082s1-stage1-placement-mk50-audit.json';a=load(ar)
 assert (g['status'],g['returncode'])==('completed',0) and p['case_id']==c['case_id']==qa['case_id']==gq['case_id'] and p['actual_generated_constants']['data2d']['value']=='false'
 assert gq['physical_case_id']==qa['physical_case_id']==c['physical_case_id'] and gq['physical_condition_sha256']==qa['physical_condition_sha256']==c['physical_condition_sha256']
 counts=p['generated_xml_particle_counts'];assert counts=={'fixed':158559,'moving':4210,'floating':0,'fluid':31658} and p['actual_total_particles']==194427 and g['total_particles']==194427
 assert a['stage1_basic_placement_proof']=='pass_excluding_numerical_precision' and a['all_basic_placement_checks_pass'] and all(a['checks'].values()) and a['actual_counts']['total_particles']==194427 and not a['numerical_precision_result_accepted'] and not a['numerical_precision']['accepted_as_stage1_placement_gate']
 prefix=p['prefix'];xml=Path(prefix+'.xml');assert sha(xml)==p['xml_sha256'];md={}
 paths=[gp,gr,pp,qp,qr,ar,xml,source,basepath,gate,O/'actual-visual-range-release.json',O/'controller-contract.json',Path(__file__),solver,L/'.venv/bin/python',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py',root(230)/'launch.py',root(230)/'root_native_home_floor_inventory_policy.py',root(134)/'ds02_root_all_idle_gpu_policy_v2.py',root(64)/'resource-window-approval.json',*map(Path,decisions)]
 for path in paths:md[str(path)]=sha(path)
 for path,digest in gq['input_sha256'].items():
  if Path(path).suffix.lower() not in SCIENCE:assert sha(path)==digest
  md[path]=digest
 md[prefix+'.bi4']=p['bi4_sha256']
 for asset in p['assets']:
  assert asset['verified_post_gencase_sha256']==asset['sha256'];md[asset['copied_to']]=asset['sha256']
 md[a['input_provenance']['official_csv']]=a['input_provenance']['official_csv_sha256']
 aid='root-stage1-f5-next34-'+c['tag'].lower()+'-own848849-full801-native-root850';ap=D/'families/F5'/c['case_id']/aid;assert not ap.exists()
 q={**profile,'schema':'ds02.runner-request.v2','family_id':'F5','case_id':c['case_id'],'physical_case_id':c['physical_case_id'],'physical_condition_sha256':c['physical_condition_sha256'],'source_plan_physical_condition_sha256':c['physical_condition_sha256'],'attempt_id':aid,'attempt_root':str(ap),'kind':'qualification','qualification_stage':'stage1_inside_actual_visually_reviewed_endpoints','cpu_task_kind':'solver','cpu_threads':2,'omp_threads':2,'launch_owner':'root','worktree_root':str(R),'cwd':str(Path(prefix).parent),'disabled':False,'source_only':False,'launch':True,'launch_allowed':True,'execution_allowed':True,'root_review_required':False,'max_wall_seconds':7200,'estimated_storage_bytes':base['estimated_storage_bytes'],'estimated_peak_gpu_mib':4096,'command':[str(solver),prefix,'{attempt_root}/solver_output','-tmax:16','-tout:0.02'],'gencase_receipt':str(gr),'gencase_receipt_sha256':sha(gr),'initial_qa_receipt':str(qr),'initial_qa_report':str(ar),'initial_qa_report_sha256':sha(ar),'source_owner':c['source_owner'],'source_condition':c,'actual_counts':{'total_particles':194427,'solver_dimension':3,**{k+'_particles':v for k,v in counts.items()}},'expected_particles':194427,'expected_fluid_particles':31658,'expected_native_frames':801,'expected_frames':801,'expected_dimension':3,'physical_window_s':[0,16],'save_interval_s':.02,'amplitude_scale':c['amplitude_scale'],'time_scale':c['time_scale'],'input_files':sorted(md),'input_sha256':md,'independent_case_increment':0,'production_approval':'none','q_n':'not_granted','precision_status':'not_accepted','numerical_precision_diagnostic':a['numerical_precision'],'foreign_process_protection_required':True,'shared_lease_required':True,'root_visual_range_release':str(O/'actual-visual-range-release.json'),'source_scientific_digests_origin':'Own registered GenCase848 and initialQA849 producer metadata only; no controller scientific payload read or hash'}
 np=O/'requests'/(c['tag']+'-full801-native-request.json');put(np,q);return np

def run(c):
 qp=make_request(c);q=load(qp)
 while True:
  ledger=load(D/'runtime/resource-ledger.json');snap=rt.inventory();leased={load(p)['uuid'] for p in (D/'leases').glob('*.json')}
  reserved_bytes=sum(x.get('new_storage_bytes',0) for x in ledger['reservations'])
  if shutil.disk_usage('/home/jade').free-reserved_bytes-q['estimated_storage_bytes']<ledger['limits']['home_min_free_bytes']:
   return {'tag':c['tag'],'case_id':c['case_id'],'request':str(qp),'status':'held_for_home_floor_before_registration','returncode':None,'actual_full801_native_pass':False,'independent_case_increment':0}
  if sum(x.get('cpu_threads',0) for x in ledger['reservations'])+2>64:time.sleep(3);continue
  try:gpu.choose_gpu(snap,leased,4096);break
  except RuntimeError:time.sleep(3)
 p=subprocess.run([str(L/'.venv/bin/python'),str(root(230)/'launch.py'),str(qp)],cwd=L,capture_output=True,text=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};frames=len(list((Path(q['attempt_root'])/'solver_output/data').glob('Part_*.bi4')));passed=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and frames==801
 row={'tag':c['tag'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],'request':str(qp),'actual_receipt':str(rp),'status':r.get('status'),'returncode':r.get('returncode'),'launcher_returncode':p.returncode,'native_saved_frame_file_count':frames,'actual_full801_native_pass':passed,'independent_case_increment':0,'launcher_error':p.stderr[-1500:]};print(json.dumps(row),flush=True);return row
cases=plan['candidates'];results=[run(cases[0])];failed=not results[0]['actual_full801_native_pass'];index=1;put(O/'actual-progress.json',{'results':results,'pending_not_launched':len(cases)-index,'independent_case_increment':0})
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(cases) and not failed):
  while len(active)<7 and index<len(cases) and not failed:active[pool.submit(run,cases[index])]=cases[index]['tag'];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);r=f.result();results.append(r);failed|=not r['actual_full801_native_pass'];put(O/'actual-progress.json',{'results':results,'pending_not_launched':len(cases)-index,'independent_case_increment':0})
put(O/'controller-result.json',{'requested':34,'actual_full801_native_pass_count':sum(r['actual_full801_native_pass'] for r in results),'pending_not_launched':len(cases)-index,'results':results,'maximum_parallel_jobs_after_first_pass':7,'independent_case_increment':0});raise SystemExit(1 if failed else 0)
