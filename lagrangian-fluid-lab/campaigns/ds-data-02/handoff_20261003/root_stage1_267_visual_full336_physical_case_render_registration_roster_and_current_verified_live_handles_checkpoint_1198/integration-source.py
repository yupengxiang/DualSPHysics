from pathlib import Path
import json,hashlib,datetime,os,subprocess,collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):
 with Path(p).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
cp_path=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_182.json';cp=load(cp_path);assert cp['stage1_visual_accepted_complete_independent_cases']==267
O=H/'root_stage1_267_visual_full336_physical_case_render_registration_roster_and_current_verified_live_handles_checkpoint_1198';O.mkdir(exist_ok=False)
accepted={};rows=[]
for p in cp['accepted_decisions']:
 a=load(p);pid=a['physical_case_id'];assert pid not in accepted;accepted[pid]=a;rows.append({'family_id':a['family_id'],'physical_case_id':pid,'case_id':a['case_id'],'canonical_physical_condition_sha256':a['physical_condition_sha256'],'status':'visual-approved-by-delegated-agent-and-main-evidence-adoption','accepted_decision':ref(p),'case_credit_already_in_authoritative_checkpoint':1,'new_case_credit':0,'precision_status':'视觉检查通过、数值精度未验收'})
pending={}
for d in H.glob('root*'):
 s=d.name.rsplit('_',1)[-1]
 if not s.isdigit() or int(s)<951 or not (d/'controller-config.json').is_file():continue
 c=load(d/'controller-config.json');qs=[c['request']] if 'request' in c else c.get('requests',c.get('outer_requests',[]))
 for qp in qs:
  if not Path(qp).is_file():continue
  q=load(qp)
  if not q.get('expected_contact_sheets') or not q.get('physical_case_id') or not q.get('attempt_root'):continue
  pid=q['physical_case_id']
  if pid in accepted:continue
  if pid not in pending or int(s)>pending[pid]['root']:pending[pid]={'root':int(s),'request_path':Path(qp),'request':q,'controller_root':d}
assert len(accepted)==267 and len(pending)==69 and len(set(accepted)|set(pending))==336
handles=[]
for pid,z in sorted(pending.items()):
 q=z['request'];d=z['controller_root'];lp=d/'controller-launch-process.json';v=load(lp);stat=Path('/proc')/str(v['pid'])/'stat';same=False;state=None
 if stat.exists():
  s=stat.read_text().split(') ',1)[1].split();state=s[0];same=s[0]!='Z' and s[19]==str(v['proc_start_ticks'])
 rp=Path(q['attempt_root'])/'execution-receipt.json';r=load(rp) if rp.exists() else {};terminal=(r.get('status'),r.get('returncode'))==('completed',0);cr=d/'controller-result.json'
 assert same or terminal or cr.exists(),(pid,z['root'],'missing handle and no terminal evidence')
 assert q['expected_contact_sheets']==(q['expected_frames']+23)//24
 observation={'controller_launch':ref(lp),'same_actual_PID_start_ticks_live':same,'observed_proc_state':state,'actual_worker_receipt':ref(rp) if rp.exists() else None,'actual_worker_status':r.get('status','no_actual_receipt'),'actual_worker_returncode':r.get('returncode'),'actual_controller_terminal':ref(cr) if cr.exists() else None}
 handles.append({'root':z['root'],'physical_case_id':pid,**observation})
 rows.append({'family_id':q['family_id'],'physical_case_id':pid,'case_id':q['case_id'],'declared_render_request_condition_sha256':q.get('physical_condition_sha256'),'declared_actual_converter_scope_sha256':q.get('actual_converter_scope_sha256'),'status':'complete-render-awaiting-delegated-visual-review' if terminal else 'registered-render-still-pending','latest_registered_render_request':ref(z['request_path']),'expected_frames':q['expected_frames'],'expected_particles':q['expected_particles'],'expected_contact_sheets':q['expected_contact_sheets'],'actual_observation':observation,'case_credit':0,'not_accepted_by_registration_or_exit_code_alone':True})
counts=collections.Counter(a['family_id'] for a in rows);assert dict(counts)=={f'F{i}':48 for i in range(1,8)}
roster=O/'full336-physical-case-registration-progress-index.json';put(roster,{'schema':'ds02.stage1.full336.actual-registration-progress-index.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_authoritative_checkpoint':ref(cp_path),'accepted_independent_physical_cases':267,'registered_pending_independent_physical_cases':69,'union_distinct_physical_case_ids':336,'per_family_union_counts':dict(counts),'delivery_complete':False,'numeric_reference_cases':0,'registration_or_exit_code_does_not_grant_visual_case_credit':True,'main_scientific_payload_IO':False,'new_case_credit':0,'cases':sorted(rows,key=lambda a:(a['family_id'],a['physical_case_id']))})
put(O/'current_actual_pending_render_controller_handles.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'handles':handles,'all_registered_pending_have_current_same_handle_or_actual_terminal_evidence':True,'observation_timeout_not_restart':True,'case_credit':0})
for k,p in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(p)==cp['unmodified_guards'][k]
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw);fs=os.statvfs('/home/jade');free=fs.f_bavail*fs.f_frsize/2**30;assert free>=500
cp.update(checkpoint=183,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(cp_path),predecessor_sha256=sha(cp_path),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600,cpu_core_hours_charged=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600,authorized_work_state='Active267/336: full336 physical-case roster verified as267accepted+69registeredpending, eachfamily48. Root1064 F2RX053ROT105 realfull401 render nowcompleted0 and awaitingfresh162personal17contacts9keys. Root1173 F5M102T085 realfull801 renderprogressing; otherownsamehandles preserved incl951lastF6/1194AY0270. No native reruns launched.',previous_goal_turn_classification='Progress: actual full336 uniquephysical registry coverage proved for sevenfamily48 each; selectedpendinglatestownrequests69 all have samecurrentlivePID/startticks or actualterminal evidence, no falsecompletedcasecredit. Actual1064full401render completed0 observed and assignedpersonalreview162; original1173 full801 actualprivateframefilenames show543/801 progress withoutreadingunpublishedimages. Previousturn acceptedfresh161/fresh188267 and actual1193XMF0/render1194 launched.')
cp['actual_progress']['full336_physical_case_registered_roster']=ref(roster);cp['actual_progress']['current69_pending_actual_render_handles']=ref(O/'current_actual_pending_render_controller_handles.json');cp['source_agents'].update(f6_endpoint_initial_qa='fresh162 F2RX053ROT105 actual1064 nowcompleted0 personal17contacts9keys; lastF6 original951 stillwaiting',f5_bed_recovery='fresh187 actualF5-48 coverage and nextactual1173 M102T085 personalreview aftercompleted0',production_recovery='fresh145 nextactualcompleted F3full836 personalreview, original1031etc queued; AY0270 actual1194 queued')
cp['next_executable_tasks']=['Adopt fresh162 F2actual1064 personal17contacts9keys afterfinalcommit, independently closeownfull401 UID/scopes/time and preserveactualmissing states','Observe Root1173 full801 realrender, actual0 publishedoutputtoF5personalreview189; fresh187 onlygenuineuncovereddependency','Observe original951 lastF6 ownunacceptedS1375YAWP18 and registered1194AY0270 full836 actualsamehandles; norestartfromwait','Continue remaining69 visualcase deliveries; registry336 is not completion, Q-N/Q-E0 and numeric limits remain']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_183.json',cp);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_183.json').relative_to(R))]+[str((root(1064)/'controller-result.json').relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: verify complete physical registration roster and retain live pending render evidence','--',*paths],cwd=R,check=True);print({'checkpoint':183,'accepted':267,'pending_registered':69,'union_physical_cases':336,'each_family':48,'Home_free_GiB':free,'CPUcoreh':cp['cpu_core_hours_charged'],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
