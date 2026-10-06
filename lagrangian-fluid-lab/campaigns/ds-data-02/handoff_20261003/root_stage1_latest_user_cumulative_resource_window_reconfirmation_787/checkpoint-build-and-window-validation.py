from pathlib import Path
import json,hashlib,subprocess,datetime,collections,os
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.xml','.xmf','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def root(n):return next(H.glob(f'root*_{n}'))
def ref(p):return {'path':str(p),'sha256':sha(p)}
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
lp=D/'runtime/resource-ledger.json';ledger_bytes=lp.read_bytes();ledger=json.loads(ledger_bytes)
limits=ledger['limits'];assert limits['gpu_seconds']==512*3600 and limits['cpu_core_seconds']==3840*3600 and limits['qualification_attempts']==1024 and limits['production_attempts']==720 and limits['home_min_free_bytes']==500*1024**3
assert ledger['adopted_at_utc']=='2026-09-30T07:23:48+00:00' and ledger['deadline_utc']=='2026-10-14T07:23:48+00:00'
F=H/'root_stage1_latest_user_cumulative_resource_window_reconfirmation_787';F.mkdir(exist_ok=True)
confirmation={'schema':'ds02.user.cumulative-window-reconfirmation.v1','at_utc':now,'authority':'current explicit user message: 累计资源窗口512 GPU·h、3840 CPU core·h、资格1024、生产720','user_cumulative_window':{'gpu_hours':512,'cpu_core_hours':3840,'qualification_attempts':1024,'production_attempts':720},'actual_shared_ledger_limits_verified':limits,'limits_already_match_no_mutation_needed':True,'ledger_usage_and_reservations_preserved_no_reset':True,'adopted_at_utc':ledger['adopted_at_utc'],'deadline_utc':ledger['deadline_utc'],'home_min_free_bytes':500*1024**3,'runtime_concurrent_CPU_reservation_cap':64,'effective_renderer_cap':2,'all_source_agents_informed':True}
put(F/'latest-user-resource-confirmation-verified-current.json',confirmation)
# Adopt source131 disabled production definitions; no launch and no case credit.
A=H/'root_stage1_f5_fresh131_remaining10_nonT120_disabled_exact_adoption_790';A.mkdir(exist_ok=True)
W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');src=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003').glob('root_followup_131_*'));rel=src.relative_to(W);commit='ddf186cc4c3f4b7b13ce4959fe1c78660e7fdf9d'
files=subprocess.run(['git','ls-tree','-r','--name-only',commit,'--',str(rel)],cwd=W,capture_output=True,text=True,check=True).stdout.splitlines();assert files;adopted=[]
for name in files:
 p=W/name;assert p.suffix in {'.json','.py','.md','.xml'}
 blob=subprocess.run(['git','show',f'{commit}:{name}'],cwd=W,capture_output=True,check=True).stdout;assert blob==p.read_bytes()
 dst=R/name;dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists():assert dst.read_bytes()==blob
 else:dst.write_bytes(blob)
 adopted.append(ref(dst))
put(A/'actual-source-adoption-review.json',{'at_utc':now,'source_commit':commit,'source_package':str(src),'adopted_files':adopted,'source_adopted_byte_exact':True,'requests_kept_disabled':True,'production_release_condition':'Both actual M085/M115 completed0 full801 renders and delegated visual acceptance integrated by Root','historical_precision_and_bed_failures_retained':True,'T120_excluded_no_time_extension_approval':True,'independent_case_increment':0,'no_jobs_started':True})
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_100.json');accepted=cp['accepted_decisions'].copy();new=[]
for n,name in [(780,'actual-first2-integration-review.json'),(784,'actual-integration-review.json'),(788,'actual-integration-review.json'),(789,'actual-integration-review.json')]:new+=load(root(n)/name)['decisions']
accepted+=new;assert len(accepted)==102
rows=[load(p) for p in accepted];assert len({r.get('physical_case_id',r['case_id']) for r in rows})==102 and len({r['physical_condition_sha256'] for r in rows})==102
for p in new:assert load(p)['status']=='visual-approved-by-delegated-agent' and not load(p)['main_personally_viewed_pngs']
controllers=[]
for n in [773,774,775,783,786]:
 c=load(root(n)/'controller-launch-process.json');proc=Path('/proc')/str(c['pid']);assert proc.exists();fields=(proc/'stat').read_text().split(') ',1)[1].split();assert fields[19]==c['proc_start_ticks'];assert c['controller'].encode() in (proc/'cmdline').read_bytes().split(b'\0');assert sha(c['controller'])==c['controller_sha256'];controllers.append({**c,'actual_live_at_checkpoint':True,'actual_state':fields[0],'actual_result':ref(root(n)/'controller-result.json') if (root(n)/'controller-result.json').exists() else None})
requests=[]
for n in [783,786]:
 for qp in sorted(root(n).glob('*render-request.json')):
  q=load(qp);rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {}
  requests.append({'request':ref(qp),'actual_receipt':ref(rp) if rp.exists() else None,'status':r.get('status','not_dispatched_waiting_actual_M115'),'returncode':r.get('returncode'),'pid':r.get('pid'),'actual_render_frame_png_count':len(list((Path(q['attempt_root'])/'render/frames').glob('frame_*.png'))),'independent_case_increment':0})
assert sum(r.get('cpu_threads',0) for r in ledger['reservations'])<=64
v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize;assert free>=500*1024**3
counts=dict(collections.Counter(x['kind'] for x in ledger['attempts']))
progress={'F5_actual_full801_N3_XMF':ref(root(777)/'controller-result.json'),'F5_actual_all801_Mk50_bed_audit':ref(root(778)/'controller-result.json'),'new_delegated_visual_cases':{'F4':4,'F1':8,'total':12,'review_decisions':[{**ref(p),'reviewer':load(p).get('visual_reviewer',load(p).get('reviewer'))} for p in new]},'actual_F1_24_pipeline_frontier_correction':ref(root(781)/'actual-F1-frontier-correction.json'),'F5_production_remaining10_disabled':ref(A/'actual-source-adoption-review.json'),'render_queue_control':{'Root782_global4_superseded':True,'effective_global_renderer_cap':2,'shared_CPU_reservation_cap':64,'Root773_state':'T; only future dispatch held, completed child not signalled','Root786_live_recovery_controller':ref(root(786)/'controller-launch-process.json'),'resume_condition':'After actual M115783 and newM085786 terminal and owned F5 leases drain, exact PID/startticks validation followed by SIGCONT own773 only','old_M085783_prelaunch_guard_rejection_preserved':True,'scientific_children_and_foreign_processes_not_signalled':True,'correction_record':ref(root(785)/'actual-resource-cap64-correction-and-dispatch-hold.json')},'actual_controllers':controllers,'F5_actual_render_requests':requests}
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_101.json',{'schema':cp['schema'],'checkpoint':101,'at_utc':now,'predecessor':str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_100.json'),'predecessor_sha256':sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_100.json'),'historical_records_preserved_by_reference_no_repeated_snapshot_expansion':True,'authorized_work_state':'active; actual cases integrated; no new approval required','stage1_visual_accepted_complete_independent_cases':102,'target_stage1_independent_cases':336,'accepted_per_family':dict(collections.Counter(r['family_id'] for r in rows)),'accepted_decisions':accepted,'new_accepted_decisions':new,'numeric_reference_accepted_independent_products':0,'precision_status':'视觉检查通过、数值精度未验收','limits':limits,'user_cumulative_window':confirmation['user_cumulative_window'],'latest_user_resource_window_confirmation':str(F/'latest-user-resource-confirmation-verified-current.json'),'deadline_utc':ledger['deadline_utc'],'adopted_at_utc':ledger['adopted_at_utc'],'attempt_counts':counts,'gpu_hours_charged':sum(x.get('gpu_seconds',0) for x in ledger['charges'])/3600,'cpu_core_hours_charged':sum(x.get('cpu_core_seconds',0) for x in ledger['charges'])/3600,'active_reservations':ledger['reservations'],'ledger_sha256_at_checkpoint':hashlib.sha256(ledger_bytes).hexdigest(),'home_free_gib':free/1024**3,'effective_visual_review_policy':cp['effective_visual_review_policy'],'effective_agent_model_policy':cp['effective_agent_model_policy'],'source_agents':{'/root/production_recovery':'fresh087 remaining4 fresh090 F1 DUAL delegated visual review, then old7 actual metadata entrances','/root/f6_endpoint_initial_qa':'fresh111 next2 old638 F4 delegated visual review','/root/f5_bed_recovery':'fresh132 actual783M115/new786M085 full801 endpoint delegated visual acceptance; do not enable fresh131 before both accepted'},'actual_progress':progress,'unmodified_guards':cp['unmodified_guards'],'next_executable_tasks':['Monitor Root786 actual live handle and exact SIGCONT of ownRoot773 once F5 render reservations drain; no timeouts treated as terminal','Root773 resumes remainingF4 full1201 cap2; Root774 F6 full241 and Root775 F3 full836 wait actual predecessor receipts','Adopt next delegated fresh087/111 visual reports only after metadata/PNGhash/unique identity verification','Both F5 endpoints actual full801 render and delegated visual acceptance needed before enabled native remaining10 nonT120','F1 actual24 already all pipeline completed; avoid redundant qualification runs; 48 unique F1 frontier uses existing accepted and remaining visual inventories']})
print(json.dumps({'checkpoint':101,'accepted':102,'counts':counts,'gpu_hours':sum(x.get('gpu_seconds',0) for x in ledger['charges'])/3600,'cpu_core_hours':sum(x.get('cpu_core_seconds',0) for x in ledger['charges'])/3600,'home_free_gib':free/1024**3}))
