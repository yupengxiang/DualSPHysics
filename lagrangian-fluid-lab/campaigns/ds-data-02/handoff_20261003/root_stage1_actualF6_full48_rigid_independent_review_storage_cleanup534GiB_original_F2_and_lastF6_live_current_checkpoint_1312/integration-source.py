from pathlib import Path
import json,hashlib,datetime,copy,os,collections,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
oldp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_240.json';old=load(oldp);assert old['checkpoint']==240 and old['stage1_visual_accepted_complete_independent_cases']==len(old['accepted_decisions'])==295
ip=root(1306)/'full336-current295-actual-final48-delivery-progress-index.json';index=load(ip);assert len(index['cases'])==336 and sum(bool(r.get('accepted_decision')) for r in index['cases'])==295
proofp=root(1310)/'source169-byte-exact-readonly-validator-and-main48-rigid-metadata-adoption.json';proof=load(proofp);assert proof['actual_fulltime_rigid_cases']==48 and proof['new_case_credit']==0 and len(proof['fresh47_independently_bound_metadata'])==47
cleanupp=root(1311)/'current-storage-cleanup-verification.json';cleanup=load(cleanupp);assert cleanup['all_deleted_paths_still_absent'] and cleanup['all_preserved_samples_present'] and cleanup['original_failed_receipts_bytes_unchanged']
now=datetime.datetime.now(datetime.timezone.utc);assert now<datetime.datetime.fromisoformat(old['deadline_utc'])
observations=[]
for number,pid,start,expected in [(1132,500008,212753945,401),(1110,502412,212774819,401),(951,4004579,207142232,241)]:
 p=Path(f'/proc/{pid}/stat');actual=None
 if p.exists():actual=int(p.read_text().rsplit(')',1)[1].split()[19])
 cache=Path(f'/tmp/ds02-visual-render-cache-root{number}');names=[p.name for p in cache.rglob('frame_*.png')] if cache.exists() else []
 result=root(number)/'controller-result.json'
 observations.append({'original_root':number,'process_pid':pid,'expected_startticks':start,'actual_startticks':actual,'same_process_live':actual==start,'private_frame_filename_count_stat_only':len(names),'expected_full_frames':expected,'authoritative_controller_terminal_present':result.exists(),'observation_at_utc':now.isoformat(),'private_PNGs_read_or_hashed':False})
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);counts=collections.Counter(r['kind'] for r in ledger['attempts']);gpu=sum(c.get('gpu_seconds',0) for c in ledger['charges'])/3600;cpu=sum(c.get('cpu_core_seconds',0) for c in ledger['charges'])/3600
v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720
for key,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==old['unmodified_guards'][key]
O=H/'root_stage1_actualF6_full48_rigid_independent_review_storage_cleanup534GiB_original_F2_and_lastF6_live_current_checkpoint_1312';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_241.json';assert not O.exists() and not np.exists();O.mkdir()
put(O/'current-original-process-observations.json',{'at_utc':now.isoformat(),'observations':observations,'observation_timeout_not_terminal':True,'no_job_restart':True,'new_case_credit':0})
snapshot=O/'ledger-immutable-snapshot.json';snapshot.write_bytes(raw)
new=copy.deepcopy(old);new.update(checkpoint=241,at_utc=now.isoformat(),predecessor=str(oldp),predecessor_sha256=sha(oldp),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snapshot),active_reservations=ledger['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: source169 exact4 committed metadata files adopted; main independently bound all47 actual full241 export report/receipt/request/native scope and retained existing baseline Part absence, fulltime motion delivery48 confirmed. User failed-output cleanup17203 absences and38 diagnostic samples plus21 original failed receipts reverified; new deletion0, Home787GiB. Existing render processes remain live; no restarts.',authorized_work_state='Active295/336,41 visual cases pending; F1/F4/F7=48,F2=40,F3=39,F5=25,F6=47. Full48 F6 rigid histories and source169 independent metadata closure complete; actual fixed24 particle/rigid joined index fresh170 in progress. F5 original1180 awaits fresh183 personal43PNG review; two original F2 renders nearing completion.')
new['actual_progress']['F6_full48_source169_independent_metadata_adoption']=ref(proofp)
new['actual_progress']['user_failed_storage_cleanup534GiB_current_retention_verification']=ref(cleanupp)
new['actual_progress']['current_original1132_1110_951_process_observations']=ref(O/'current-original-process-observations.json')
new['source_agents']['production_recovery']='fresh169 completed and exact adopted; fresh170 fixed actualF6-first24 particle/XMF with actual fulltime rigid histories joined delivery in progress'
new['next_executable_tasks']=['After terminal original1132 publication execute prepared own401QI1307 and send exact proof to fresh205 actualF2 personal26PNG reviewer; preserve final35fluid omissions and unknown causes.','After terminal original1110 publication execute prepared own401QI1308; after fresh183 integration assign fresh184 actualF2 personal26PNG review preserving final3fluid omissions.','Adopt fresh183 actualF5 original1180 against ownQI1298 and path label correction; nativeplan namespace absence must remain false/null.','Independently integrate fresh170 actual fixedF6-first24 particle+rigid joined delivery after scoped source commit, retaining baseline alias/Part gaps and no new case credit.','Continue remaining41 original render and personal visual reviews without science reruns; lastF6 original951 is a live registered waiter, not a terminal failure.']
put(np,new)
index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,current_original_process_metadata=ref(O/'current-original-process-observations.json'))
index['actual_F6_final48_fulltime_rigid_motion_independent_review']=ref(proofp)
put(O/'full336-current295-actual-final48-delivery-progress-index.json',index)
(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: checkpoint295 with full48 rigid review and storage cleanup retention','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':241,'accepted':295,'pending':41,'Home_GiB':free,'gpu_hours':gpu,'CPU_core_hours':cpu,'process_observations':observations,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
