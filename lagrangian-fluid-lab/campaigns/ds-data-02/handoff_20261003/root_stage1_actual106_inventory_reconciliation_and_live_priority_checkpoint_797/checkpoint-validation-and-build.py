from pathlib import Path
import json,hashlib,collections,datetime,os,subprocess,ast
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def root(n):return next(H.glob(f'root*_{n}'))
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_actual106_inventory_reconciliation_and_live_priority_checkpoint_797';O.mkdir(exist_ok=True)
prev=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_101.json';cp=load(prev);new=[]
for n in [791,794]:new+=load(root(n)/'actual-integration-review.json')['decisions']
accepted=cp['accepted_decisions']+new;rows=[load(p) for p in accepted];assert len(accepted)==106 and len({x.get('physical_case_id',x['case_id']) for x in rows})==106 and len({x['physical_condition_sha256'] for x in rows})==106
assert all(load(p)['status']=='visual-approved-by-delegated-agent' and not load(p)['main_personally_viewed_pngs'] for p in new)
controllers=[]
for n in [773,774,783,793,796]:
 c=load(root(n)/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);assert p.exists();fields=(p/'stat').read_text().split(') ',1)[1].split();assert fields[19]==c['proc_start_ticks'];assert c['controller'].encode() in (p/'cmdline').read_bytes().split(b'\0');assert sha(c['controller'])==c['controller_sha256'];controllers.append({**c,'number':n,'actual_live_at_checkpoint':True,'actual_state':fields[0],'actual_result':ref(root(n)/'controller-result.json') if (root(n)/'controller-result.json').exists() else None})
retired=[]
for n,proof in [(786,root(793)/'owned786_wait_controller_retirement.json'),(775,root(796)/'owned775_wait_controller_retirement.json')]:
 c=load(root(n)/'controller-launch-process.json');p=Path('/proc')/str(c['pid']);assert not p.exists() or (p/'stat').read_text().split(') ',1)[1].split()[0]=='Z';retired.append({'number':n,'actual_owned_waiter_absent_or_zombie':True,'proof':ref(proof),'science_workers_not_signalled':True})
requests=[]
for n in [783,793]:
 for qp in root(n).glob('*render-request.json'):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp);p=Path('/proc')/str(r.get('pid'));requests.append({'request':ref(qp),'actual_receipt':ref(rp),'status':r['status'],'returncode':r.get('returncode'),'pid':r.get('pid'),'actual_pid_live':p.exists(),'actual_frame_png_count':len(list((Path(q['attempt_root'])/'render/frames').glob('frame_*.png'))),'independent_case_increment':0})
  if r['status']=='running':assert p.exists()
lp=D/'runtime/resource-ledger.json';raw=lp.read_bytes();l=json.loads(raw);assert l['limits']==cp['limits'];assert l['adopted_at_utc']==cp['adopted_at_utc'] and l['deadline_utc']==cp['deadline_utc'];assert sum(x.get('cpu_threads',0) for x in l['reservations'])<=64
stat=os.statvfs('/home/jade');free=stat.f_bavail*stat.f_frsize;assert free>=500*1024**3
gpu=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_memory','--format=csv,noheader'],capture_output=True,text=True,check=True).stdout.strip();put(O/'actual-readonly-foreign-GPU-process-inventory.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'nvidia_smi_query_compute_apps':gpu,'foreign_processes_protected':True,'no_learning_process_or_scientific_outputs_inspected':True,'new_GPU_jobs_started_this_checkpoint':0,'idle_GPUs_not_used_for_redundant_already_completed_solves':True})
progress={'new_unique_delegated_visual_cases':{'F1':2,'F4':2,'total':4,'metadata_decisions':[ref(p) for p in new],'main_PNG_viewing_claim':False},'F2_F7_actual_frontier_correction':ref(root(792)/'actual-frontier-correction.json'),'F5_actual_parallel_M115783_M085793':requests,'effective_renderer_cap':2,'shared_CPU_reservation_cap':64,'live_controllers':controllers,'owned_wait_controllers_retired':retired,'F3_priority':{'controller':ref(root(796)/'controller-launch-process.json'),'jobs_planned':4,'actual_jobs_started':0,'actual_verified_wait_on793':True,'future_sequence':'793 F5 endpoints terminal/leasesdrain then Root773 resume,796 exact SIGSTOP only773 futuredispatch, drain already started ownF4 jobs, render4 F3 full836 through unchanged142 cap2, SIGCONT773 when ownF3 leasesdrain','reason':'F3 actual corners visual acceptance enables20 independent GPU solves before F4/F6 bulk render backlog finishes','Root774_F6_sequence_unchanged':True},'source132_exact_pending_historical_adoption':ref(root(795)/'actual-source-adoption-review.json'),'actual_foreign_GPU_inventory':ref(O/'actual-readonly-foreign-GPU-process-inventory.json')}
out={k:cp[k] for k in ['schema','target_stage1_independent_cases','numeric_reference_accepted_independent_products','precision_status','limits','user_cumulative_window','latest_user_resource_window_confirmation','deadline_utc','adopted_at_utc','effective_visual_review_policy','effective_agent_model_policy','unmodified_guards']}
out.update(checkpoint=102,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(prev),predecessor_sha256=sha(prev),historical_records_preserved_by_reference_no_repeated_snapshot_expansion=True,authorized_work_state='active; actual case integration and running parallel jobs; no user approval blocker',previous_goal_turn_classification='progress:102accepted/localcommit40a7994d and actual shared tasks preserved',stage1_visual_accepted_complete_independent_cases=106,accepted_per_family=dict(collections.Counter(r['family_id'] for r in rows)),accepted_decisions=accepted,new_accepted_decisions=new,attempt_counts=dict(collections.Counter(x['kind'] for x in l['attempts'])),gpu_hours_charged=sum(x.get('gpu_seconds',0) for x in l['charges'])/3600,cpu_core_hours_charged=sum(x.get('cpu_core_seconds',0) for x in l['charges'])/3600,active_reservations=l['reservations'],ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),home_free_gib=free/1024**3,actual_progress=progress,source_agents={'/root/production_recovery':'fresh088 last2 F1 DUAL then F2 RX046/RX064 rotation065/120 corners before old7 F1 inventory; native pipelines already complete','/root/f6_endpoint_initial_qa':'fresh112 next2 old638 full1201 F4 PNG visual review','/root/f5_bed_recovery':'fresh133 F7 A031P5/A032P5 full601 PNG review while real F5 renders pending; prioritize F5 full801 endpoints afteractual0'},next_executable_tasks=['Monitor actual793 M085 render plus existing783 M115; full801/34contacts/terminal0 must precede delegated visual acceptance; release10F5 nonT120 only afterbothRootaccept','Verify actual796 handoff: Root773 temporary futuredispatch hold and eventual SIGCONT after4F3renders; preserve started scientific workers and cap2/CPU64','Adopt fresh088/112/133 onlyafter unique physical identity,actualpipeline andPNGhash checks; no Root imageviewclaim','F2 range4corners delegatedvisual then prepare24 further independent conditions within confirmed range to reach48, originalcases12remaining no reruns','F1 sevenremainingcompletepipeline visual inventory +last2fresh090 reaches48; F7 all48pipelineexists and37visualpending, no more native F7 necessary','F3 full8364corners visual acceptance then sharedGPU20 independentcases; useidleGPUs afterrelease, protectliveforeignGPU7'])
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_102.json',out)
dst=O/'checkpoint-validation-and-build.py';dst.write_bytes(Path(__file__).read_bytes())
paths=[]
for n in range(791,798):
 for p in root(n).rglob('*'):
  if p.is_file() and p.suffix in {'.json','.py','.md'} and '__pycache__' not in p.parts:
   if p.suffix=='.json':load(p)
   if p.suffix=='.py':ast.parse(p.read_text())
   paths.append(str(p.relative_to(R)))
for fam,num in [('F3',87),('F6',111),('F5',132)]:
 for p in next((L/'campaigns/ds-data-02/families'/fam/'handoff_20261003').glob(f'root_followup_{num:03d}_*')).rglob('*'):
  if p.is_file() and p.suffix in {'.json','.py','.md'} and '__pycache__' not in p.parts:paths.append(str(p.relative_to(R)))
paths.append(str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_102.json').relative_to(R)))
assert not subprocess.run(['git','diff','--cached','--name-only'],cwd=R,capture_output=True,text=True,check=True).stdout.strip()
subprocess.run(['git','add','-f','--',*paths],cwd=R,check=True);r=subprocess.run(['git','diff','--cached','--check'],cwd=R,capture_output=True,text=True);assert r.returncode==0,r.stdout+r.stderr
subprocess.run(['git','commit','-m','Integrate 106 visual cases, reconcile F2/F7 inventory and advance F3 render priority'],cwd=R,check=True,stdout=subprocess.DEVNULL)
print(json.dumps({'checkpoint':102,'accepted':106,'commit':subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True,check=True).stdout.strip(),'scoped_files':len(paths),'attempts':out['attempt_counts'],'GPUh':out['gpu_hours_charged'],'CPUcoreh':out['cpu_core_hours_charged'],'home_free_gib':out['home_free_gib']}))
