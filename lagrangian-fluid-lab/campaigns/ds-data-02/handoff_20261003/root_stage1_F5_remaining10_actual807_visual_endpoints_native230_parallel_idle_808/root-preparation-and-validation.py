from pathlib import Path
import json,hashlib,ast,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');P=next((L/'campaigns/ds-data-02/families/F5/handoff_20261003').glob('root_followup_131_*'));O=H/'root_stage1_F5_remaining10_actual807_visual_endpoints_native230_parallel_idle_808';O.mkdir(exist_ok=True);assert not (O/'controller-launch-process.json').exists()
def load(p):return json.loads(Path(p).read_text())
SCIENCE={'.h5','.hdf5','.bi4','.ibi4','.dat','.csv','.vtk','.vtu','.npy','.npz'}
def sha(p):
 p=Path(p);assert p.suffix.lower() not in SCIENCE;return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,x):Path(p).write_text(json.dumps(x,indent=2)+'\n')
def root(n):return next(H.glob(f'root*_{n}'))
gate=root(807)/'actual-integration-review.json';ga=load(gate);assert ga['stage1_visual_range_release']['released_for_bounded_first_stage_native_production_after_each_actual_initial_QA'];end=[]
for dp in ga['decisions']:
 d=load(dp);e=d['actual_completed_metadata_evidence'];b=load(e['bed_audit_report']['path']);qa=load(e['initial_qa_report']['path']);assert qa['all_basic_placement_checks_pass'] and all(qa['checks'].values());assert b['scan']['frames_scanned']==801 and len(b['frame_reports'])==801 and b['time_provenance']['first_s']==0 and b['time_provenance']['last_s']>=16 and b['time_provenance']['match'] and b['time_provenance']['strictly_increasing'];assert all(f['penetration']['one_dp']['count']==f['penetration']['two_dp']['count']==f['nonfinite_initial_fluid_uid_count']==0 and f['current_valid_type3_fluid_count']==31658 and f['penetration']['depth_unevaluable_current_fluid_count']==0 for f in b['frame_reports']);end.append({'path':dp,'sha256':sha(dp),'candidate':d['candidate_id'],'actual_full801_render_and_bed_metadata_crosschecked':True})
assert {x['candidate'] for x in end}=={'M085_T080','M115_T100'}
put(O/'actual-endpoint-audit-crosscheck.json',{'actual_endpoints':end,'scientific_payloads_read_or_hashed':False,'original_thresholds_unchanged':True,'stage1_only_no_precision_grant':True})
baseq=load(next(root(738).glob('*request.json')));prior=set()
for dp in load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_102.json')['accepted_decisions']+ga['decisions']:prior.add(load(dp).get('physical_case_id',load(dp)['case_id']))
qs=[];rows=[]
for qp in sorted((P/'requests').glob('*-full801-native-release-request.json')):
 q=load(qp);tag=qp.name.split('-')[0];assert q['disabled'] and q['motion_end_s']<=16 and q['time_scale']<=1 and q['physical_case_id'] not in prior
 gp=Path(q['gencase_prepared_root']);pr=gp/'prepared-input-report.json';g=load(pr);gr=load(q['gencase_receipt']);qr=load(q['actual_initial_qa_receipt']);qa=load(q['actual_initial_qa_report']);assert (gr['status'],gr['returncode'])==(qr['status'],qr['returncode'])==('completed',0);assert qa['all_basic_placement_checks_pass'] and all(qa['checks'].values()) and qa['actual_counts']['total_particles']==194427 and qa['actual_counts']['fluid_particles']==31658 and g['actual_total_particles']==194427
 assert g['bi4_sha256']==q['generated_bi4_sha256']==qa['input_provenance']['generated_bi4_sha256'];assert sha(q['generated_xml'])==q['generated_xml_sha256']==g['xml_sha256'];assert g['prefix']+'.bi4'==q['generated_bi4']
 md={}
 for raw,dig in q['input_sha256'].items():
  if raw.startswith('<root-bind:'):continue
  if raw.startswith(str(H.parent)+'/root_'):raw=str(H)+raw[len(str(H.parent)):]
  if raw.startswith(str(H.parent)+'/families/') and not Path(raw).exists():raise AssertionError('Unresolved source metadata path: '+raw)
  if Path(raw).is_dir():assert dig is None;continue
  if Path(raw).suffix.lower() in SCIENCE:assert isinstance(dig,str) and len(dig)==64;md[raw]=dig
  else:
   got=sha(raw);assert dig is None or got==dig,raw;md[raw]=got
 for item in g['assets']:assert item['verified_post_gencase_sha256']==item['sha256']==q['motion_asset_sha256'];md[item['copied_to']]=item['verified_post_gencase_sha256']
 md[qa['input_provenance']['official_csv']]=qa['input_provenance']['official_csv_sha256']
 for p in [qp,pr,gate,O/'actual-endpoint-audit-crosscheck.json',Path(q['gencase_receipt']),Path(q['actual_initial_qa_receipt']),Path(q['actual_initial_qa_report'])]:md[str(p)]=sha(p)
 for e in end:md[e['path']]=e['sha256']
 for p in gp.glob('*.xml'):md[str(p)]=sha(p)
 for k in ('root_inventory_policy_source_sha256','root_effective_reservation_function_sha256','root_actual_launch_source','root_actual_launch_source_sha256','runtime_entrypoint','runtime_sha256','strict_dispatch_entrypoint','strict_dispatch_sha256'):q[k]=baseq[k]
 assert q['runtime_sha256']=='5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60' and md[q['command'][0]]=='0415b10e5e32af8b8b7ad2a703f9043dca67dfcf7626eb98f1c05a50856fde29'
 cmd=list(q['command']);cmd[1]=g['prefix'];attempt=q['attempt_id']+'-root808';ar=D/'families/F5'/q['case_id']/attempt;assert not ar.exists()
 for k in ['future_candidate_counts_and_hashes_null','solver_command_is_template_only']:q.pop(k,None)
 q.update(command=cmd,cwd=str(gp),gencase_prefix=g['prefix'],attempt_id=attempt,attempt_root=str(ar),input_files=sorted(md),input_sha256=md,disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,root_review_required=False,full801_authorized=True,full_native_authorized=True,solver_allowed=True,no_jobs_started=False,kind='qualification',qualification_stage='stage1_range_batch_native_after_actual_full801_endpoints',production_approval='none')
 q.update(worktree_root=str(R),launch_owner='root',expected_native_frames=801,root_reviewed_source_request=str(qp),root_reviewed_source_request_sha256=sha(qp),root_scope='Each actual640 GenCase/661 placement plus Root807 full801 visually accepted endpoint range. 10 independent complete16s first-stage native runs; Q-N not granted. T120 excluded.',depends_on_attempts=[q['gencase_attempt_id'],Path(q['actual_initial_qa_receipt']).parent.name],physical_window_s=[0,16],independent_case_count_increment=0,upstream_full801_visual_gate={'status':'Root actual delegated evidence adopted; first-stage range only','remaining10_release_enabled':True,'endpoint_decisions':end,'source_gate_snapshot_preserved_in_original_request':str(qp),'T120_release_enabled':False,'precision_negative_retained':True},root730_gate_required=True)
 target=O/(tag+'-full801-native-request.json');put(target,q);qs.append(str(target));rows.append({'tag':tag,'physical_case_id':q['physical_case_id'],'physical_condition_sha256':q['physical_condition_sha256'],'motion_end_s':q['motion_end_s'],'actual_initial_QA_pass':True,'request':str(target),'array_hashes_main_recomputed':False})
assert len(qs)==len({r['physical_case_id'] for r in rows})==10;put(O/'actual-native-range-release-review.json',{'rows':rows,'source_gate':str(gate),'complete_window16s':True,'native_attempt_ledger_kind':'qualification, preserving actual runtime numerical-reference authorization boundary','count_increment':0,'guard_and_science_hash_overrides':False,'science_payload_read_or_hashed_by_main':False})
put(O/'dispatch-config.json',{'requests':qs,'maximum_parallel_native_jobs':7,'first_actual_completed0_before_remaining':True,'each_launch_live_inventory_uuid_lease':True,'foreign_processes_protected':True,'kind':'qualification'})
s=r'''from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,subprocess,time,sys,hashlib
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');O=Path(__file__).parent;sys.path[:0]=[str(L/'scripts'),str(H/'root_stage1_f3_first24_eight_solver_resource_policy_134')]
import ds_data02_runtime_v2 as rt,ds02_root_all_idle_gpu_policy_v2 as gpu
load=lambda p:json.loads(Path(p).read_text())
def run(qp):
 q=load(qp)
 while True:
  snap=rt.inventory();leased={json.loads(p.read_text())['uuid'] for p in (D/'leases').glob('*.json')}
  try:gpu.choose_gpu(snap,leased,4096);break
  except RuntimeError:time.sleep(3)
 p=subprocess.run([str(L/'.venv/bin/python'),str(H/'root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'),qp],cwd=L,capture_output=True,text=True);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};assert not r or r['request_sha256']==hashlib.sha256(Path(qp).read_bytes()).hexdigest();row={'request':qp,'physical_case_id':q['physical_case_id'],'actual_receipt':str(rp),'launcher_returncode':p.returncode,'status':r.get('status'),'returncode':r.get('returncode'),'native_saved_frame_file_count':len(list((Path(q['attempt_root'])/'solver_output/data').glob('Part_*.bi4'))),'independent_case_increment':0,'launcher_error':p.stderr[-2000:]};row['actual_native_pass']=p.returncode==0 and (r.get('status'),r.get('returncode'))==('completed',0) and row['native_saved_frame_file_count']==801;print(json.dumps(row),flush=True);return row
qs=load(O/'dispatch-config.json')['requests'];rows=[run(qs[0])];failed=not rows[0]['actual_native_pass'];index=1
with ThreadPoolExecutor(max_workers=7) as pool:
 active={}
 while active or(index<len(qs) and not failed):
  while len(active)<7 and index<len(qs) and not failed:active[pool.submit(run,qs[index])]=qs[index];index+=1
  if not active:break
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   active.pop(f);row=f.result();rows.append(row)
   if not row['actual_native_pass']:failed=True
result={'requested':10,'completed0':sum((x['status'],x['returncode'])==('completed',0) for x in rows),'actual_full801_native_pass_count':sum(x['actual_native_pass'] for x in rows),'pending_held':len(qs)-index,'results':rows,'maximum_parallel_jobs':7,'independent_case_increment':0};(O/'controller-result.json').write_text(json.dumps(result,indent=2)+'\n');raise SystemExit(1 if failed else 0)
'''
ast.parse(s);cp=O/'batch-native-controller.py';cp.write_text(s);inventory=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_memory','--format=csv,noheader'],capture_output=True,text=True,check=True).stdout;put(O/'actual-launch-time-GPU-process-inventory.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'GPU_compute_processes':inventory,'foreign_processes_protected':True,'actual_native_jobs_started_at_snapshot':0});p=subprocess.Popen([str(L/'.venv/bin/python'),str(cp)],cwd=L,stdout=(O/'controller.log').open('ab'),stderr=subprocess.STDOUT,start_new_session=True);f=(Path('/proc')/str(p.pid)/'stat').read_text().split(') ',1)[1].split();put(O/'controller-launch-process.json',{'pid':p.pid,'proc_start_ticks':f[19],'controller':str(cp),'controller_sha256':sha(cp),'actual_launched_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'detached_parent_session':True});(O/'root-preparation-and-validation.py').write_bytes(Path(__file__).read_bytes());print({'native_conditions':10,'controller_pid':p.pid})
