from pathlib import Path
import json,hashlib,datetime,shutil,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.xml','.xmf','.log','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_217_visual_F3_full836_downstream_F2_storage_recovered_actual_process_checkpoint_1005';O.mkdir(exist_ok=False)
# Additional F4 initial velocity proof for both cases accepted by Root1000.
f4=[]
for p in root(1000).glob('*-delegated-visual-decision.json'):
 d=load(p)
 if d['family_id']!='F4':continue
 ch=d['actual_completed_metadata_evidence'];rr=load(ch['native_frame0']['execution_receipt']);assert (rr['status'],rr['returncode'])==('completed',0)
 a=next(x for x in load(ch['native_frame0']['report'])['cases'] if x['case_id']==d['case_id'])
 assert a['pass'] and a['status']=='completed_pass' and a['finite_rows']==a['unique_identity_count']==a['actual_total_particles']==d['particles']
 assert a['native_raw_velocity_observed'] and not a['gencase_declared_velocity_used_as_evidence'] and a['max_abs_velocity_error_m_per_s']<=a['velocity_tolerance_m_per_s']
 assert a['generated_xml_sha256']==sha(ch['gencase']['generated_xml']) and all(x>1 for x in a['native_3d_levels'])
 f4.append({'case_id':d['case_id'],'decision':ref(p),'actual_frame0_receipt':ref(ch['native_frame0']['execution_receipt']),'actual_frame0_audit':ref(ch['native_frame0']['report']),'native_velocity_independent_pass':True})
assert len(f4)==2
put(O/'two-Root1000-F4-independent-native-frame0-velocity-closure.json',{'cases':f4,'science_payload_IO':False,'case_credit':0})
# Independently close actual F2 typed0 after storage floor recovery.
z=load(root(995)/'actual-progress.json')['results'];assert len(z)==1 and z[0]['actual_full401_typed_pass']
tr=Path(z[0]['actual_receipt']);rec=load(tr);tp=Path(z[0]['actual_conversion_report']);t=load(tp)
assert (rec['status'],rec['returncode'])==('completed',0) and t['conversion_status']=='completed' and t['frames']==401 and t['particles']==418104
assert t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed'] and all(x['passed'] and x['identity_type_mk_exact'] for x in t['partvtk_validation']['frames'])
assert t['typed_identity']['key']=='(Zone,Idp)' and t['lifecycle']['introduced_ids']=='rejected' and t['typed_identity']['initial_exclusion_ledger']['count']==0
for key in ['solver_receipt','gencase_receipt','generated_xml','owner_metadata']:
 p=t['source_provenance'][key];assert sha(p['path'])==p['sha256']
fs=t['lifecycle']['frame_summary'];assert len(fs)==401 and fs[0]['time']==0 and fs[-1]['time']>=4 and all(x['time']<y['time'] for x,y in zip(fs,fs[1:]))
counts={'0':372840,'1':24150,'2':0,'3':21114}
for i,f in enumerate(fs):
 assert f['frame']==i and f['active_particles']+f['missing_particles']==418104 and f['missing_type_counts'].get('3',0)==f['missing_particles']
 assert all(f['type_counts'][k]+f['missing_type_counts'].get(k,0)==v for k,v in counts.items())
put(O/'actual995-F2-full401-storage-recovered-typed-independent-review.json',{'receipt':ref(tr),'conversion_report':ref(tp),'physical_case_id':rec['request']['physical_case_id'],'frames':401,'particles':418104,'all401_typed_UID_and_counts_pass':True,'source_H5_SHA_actual_producer_only':t['output_sha256'],'final_missing_particles':fs[-1]['missing_particles'],'maximum_missing_particles':max(x['missing_particles'] for x in fs),'omission_causes_and_states_unknown':True,'next':'Bind existing original F2 XMF worker after actual typed0, then full401 render and delegated visual review','science_payload_IO':False,'case_credit':0})
cleanup=O/'actual-failed-cleanup-reverification.json';cleanup.write_bytes(Path('/tmp/ds02-failed-cleanup-latest-verification.json').read_bytes())
observed=[]
for n in [951,972,978,983,984,987,988,991,995,997,998,1002,1003,1004]:
 o=root(n);launches=[]
 for p in o.glob('*.json'):
  if 'launch' not in p.name:continue
  x=load(p)
  if isinstance(x,dict) and x.get('pid'):launches.append((p,x))
 entry={'root':n,'live':False,'case_credit':0}
 for p,x in launches:
  stat=Path(f"/proc/{x['pid']}/stat");live=False
  if stat.exists():
   raw=stat.read_text().split(') ',1)[1].split();live=raw[0]!='Z' and raw[19]==str(x.get('proc_start_ticks',x.get('start_ticks')))
  if live:entry.update(live=True,pid=x['pid'],start_ticks=raw[19],actual_launch_receipt=ref(p))
 for filename in ['actual-progress.json','controller-result.json','actual-result.json']:
  p=o/filename
  if p.exists():
   frozen=O/f'root{n}-{filename}-frozen.json';frozen.write_bytes(p.read_bytes());entry[filename]=ref(frozen)
 observed.append(entry)
put(O/'actual-process-and-terminal-observation.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processes':observed,'no_restarts':True,'case_credit':0})
cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_142.json');assert len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==217
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw)
cp.update(checkpoint=143,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor=str(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_142.json'),predecessor_sha256=sha(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_142.json'),new_accepted_decisions=[],home_free_gib=shutil.disk_usage('/home/jade').free/2**30,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),active_reservations=ledger['reservations'],attempt_counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']},gpu_hours_charged=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600,cpu_core_hours_charged=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600,previous_goal_turn_classification='Progress: six delegated full-window visuals independently adopted to217, with native lifecycle negatives disclosed; three new actual typed0 F3 XMF1002 jobs admitted, two actual997 XMF0 bound to full836 render1003/1004; actual995 F2 storage-recovery typed0 independently verified. Exact failed-native cleanup receipt and15995 deletions rechecked, no new failed native outputs found.')
assert cp['home_free_gib']>=500
cp['actual_progress']['217_visual_full836_F3_downstream_F2_actual995_storage_recovery']=ref(O/'actual-process-and-terminal-observation.json')
cp['next_executable_tasks']=['Integrate fresh169 F5 full801 original138 bed handoff for actual993 M086T095 XMF0; observe original remaining998 same handle.','Adopt fresh167 five unused F5 NEXT34 native0 typed157 requests, preserving stale decoder contract; bind actual974 correct decoder/PartVTK to new enabled regular-file inputs.','Integrate delegated F2 fresh140 <=12 of remaining20 native8120 full401 typed requests, excluding successful995 RX049 ROT075; no GPU native reruns.','Bind actual995 F2 typed0 original XMF then full401 render, retaining native omission evidence.','Observe original1002/1003/1004 and existing live951/978/983/988/991 etc; only actual render0 can proceed to personal delegated review.','Reconcile source F3 full48 true physical case aliases and F5 full48 authoritative Mother plus NEXT34 census from existing evidence before new native jobs.']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_143.json',cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_143.json').relative_to(R))]
for n in [1002,1003,1004]:paths.extend(str(p.relative_to(R)) for p in root(n).glob('*launch*.json'))
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint217 visual cases and actual F3 downstream F2 storage-recovery producers','--',*paths],cwd=R,check=True)
print({'checkpoint':143,'accepted':217,'counts':cp['accepted_per_family'],'gpu_hours':cp['gpu_hours_charged'],'cpu_core_hours':cp['cpu_core_hours_charged'],'attempt_counts':cp['attempt_counts'],'home_free_GiB':cp['home_free_gib'],'processes':[{'root':x['root'],'live':x['live']} for x in observed],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
