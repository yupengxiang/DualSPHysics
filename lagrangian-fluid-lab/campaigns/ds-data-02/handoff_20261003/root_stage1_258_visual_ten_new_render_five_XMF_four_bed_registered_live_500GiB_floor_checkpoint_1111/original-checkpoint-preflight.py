from pathlib import Path
import json,hashlib,subprocess,datetime,os,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
O=H/'root_stage1_258_visual_ten_new_render_five_XMF_four_bed_registered_live_500GiB_floor_checkpoint_1111';O.mkdir(exist_ok=False)
prefix='lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_151_failed_artifact_storage_incremental_audit_v1';commit='b1b86db6b6108369d5fdb0d2b88e5b827cc8395e';names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines();assert len(names)==5
for name in names:
 raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W);assert raw==(W/name).read_bytes();p=R/name;assert not p.exists() or p.read_bytes()==raw;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
P=W/prefix;vld=P/'scripts/validate_fresh151.py';source=vld.read_text();needle="(ROOT/'metadata/validation-result.json').write_text";assert source.count(needle)==1;redirect=source.replace(needle,"(Path("+repr(str(O/'actual-original151-validator-output.json'))+")).write_text");before={name:sha(W/name) for name in names};exec(compile(redirect,str(vld),'exec'),{'__file__':str(vld),'__name__':'__main__'});assert before=={name:sha(W/name) for name in names};put(O/'source151-readonly-validator-adoption.json',{'source_commit':commit,'adopted_files':[ref(R/name) for name in names],'original_validator':ref(vld),'redirect_only_final_report_output':True,'actual_output':ref(O/'actual-original151-validator-output.json'),'source_bytes_unchanged':True,'science_payload_IO':False,'no_new_cleanup_candidates':True,'case_credit':0})
cp_path=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_167.json';cp=load(cp_path);assert cp['stage1_visual_accepted_complete_independent_cases']==258 and len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==258
checks=[(root(142)/'launch.py','708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76'),(L/'scripts/ds_data02_runtime_v2.py','5098262e26dc5560487760181466b0a93a0e66239e5e761ae67a60'),(L/'scripts/ds_data02_strict_dispatch_v1.py','81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'),(root(928)/'fair_CPU_dispatch.py','e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f')]
# Use the actual recorded immutable runtime digest (full 64 hex), never abbreviated display text.
checks[1]=(checks[1][0],'5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60')
for p,h in checks:assert sha(p)==h
now=datetime.datetime.now(datetime.timezone.utc).isoformat();handles=[];terminals=[]
for directory in sorted(H.glob('root*')):
 m=re.search(r'_(\d+)$',directory.name)
 if not m or int(m.group(1))<940:continue
 p=directory/'controller-launch-process.json'
 if not p.exists():continue
 j=load(p);pid=j['pid'];s=Path(f'/proc/{pid}/stat');live=False;state=None
 if s.exists():
  parts=s.read_text().split(') ',1)[1].split();state=parts[0];live=state!='Z' and parts[19]==str(j['proc_start_ticks'])
 row={'root':int(m.group(1)),'launch':ref(p),'pid':pid,'start_ticks':j['proc_start_ticks'],'same_handle_live_now':live,'proc_state':state}
 if live:handles.append(row)
 elif (directory/'controller-result.json').exists():row['actual_terminal_controller_result']=ref(directory/'controller-result.json');terminals.append(row)
 else:row['no_terminal_result_observed']=True;terminals.append(row)
put(O/'actual_live_handles_and_terminal_receipts.json',{'at_utc':now,'live':handles,'terminal_or_missing_handle':terminals,'no_restart_from_timeout':True})
for n in range(1096,1111):
 row=next((a for a in handles if a['root']==n),None)
 if row is None:
  d=root(n);assert (d/'controller-result.json').exists(),'Missing handle requires actual terminal classification'
 # All registered request input metadata is immutable; H5 digests are producer attestations only.
 cfg=load(root(n)/'controller-config.json');qs=cfg.get('requests',[cfg.get('request')]);assert qs and all(qs)
 for qp in qs:
  q=load(qp);assert q['kind']=='cpu' and q['cpu_threads'] in [2,24] and q['case_credit']==0
  for p,h in q['input_sha256'].items():
   if Path(p).suffix.lower() not in {'.h5','.bi4','.dat','.csv','.vtk'}:assert sha(p)==h
new={'registered_controller_count':15,'new_full_time_render_requests':10,'new_XMF_requests':5,'new_bed_requests':4,'render_CPU24_env2_shared_cap':2,'scientific_CPU2_serial_cap':1,'source179_M101T100_unlaunched_pending_actual_scope_fix':ref(root(1108)/'source179-original-M101T100-prospective-vs-actual-scope-prelaunch-block.json'),'actual1083_prelaunch_failure_preserved_and_new1096_frozen_successor':ref(root(1096)/'prelaunch-failure-original-evidence-and-frozen-observer-repair.json'),'case_credit_from_registered_pending_jobs':0,'new_requests_do_not_change_native_science_inputs':True};put(O/'new_actual_registered_products_and_preserved_scope_failure.json',new)
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw);st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30;assert free>=500
attempts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']};gpu=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600;assert attempts['qualification']<=1024 and attempts['production']<=720 and gpu<=512 and cpu<=3840
cp.update(checkpoint=168,at_utc=now,predecessor=str(cp_path),predecessor_sha256=sha(cp_path),new_accepted_decisions=[],previous_goal_turn_classification='Progress: fresh136 two real full836 F3 cases accepted258/F3=32; registered15 controllers for10render+5XMF+4bed using completed own scientific data; original1083 strict prelaunch observer digest failure fixed via immutable1096, original179M101prospective scope mismatch preserved and excluded from four unaffected1108bed requests; actual handles independently confirmed; cleanup515.503GiB preserved, Homefloor500GiB.',home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts=attempts,gpu_hours_charged=gpu,cpu_core_hours_charged=cpu)
cp['actual_progress'].update(current_root1111_live_and_terminal_handles=ref(O/'actual_live_handles_and_terminal_receipts.json'),registered19_new_products_root1096_through1110=ref(O/'new_actual_registered_products_and_preserved_scope_failure.json'),fresh151_no_incremental_failed_unpublished_cleanup_candidate=ref(O/'source151-readonly-validator-adoption.json'))
cp['source_agents'].update(f5_bed_recovery='fresh179 four verified bed+one render nowregistered; fresh180 fixesM101actualscope and up5newreadyXMFbed metadata',production_recovery='fresh137 personallyreviewactual1025P0800AY0430 and up2readyunaccepted836',f6_endpoint_initial_qa='fresh151 no newcleanupcandidate; fresh152 actual1066F2RX049ROT090 full401 personalreview; lastF6waitreal951terminal')
cp['next_executable_tasks']=['Integrate fresh137 F3 actual1025 full836 personal review and any other realcompleted unaccepted native/typed/XMF/render fullwindow; no numerical credit.','Integrate fresh152 F2 actual1066 full401 personal review, independently preserve recordedfluidUIDomissions and canonical vslegacy producer scope; F6lastrequires951realcompleted render.','Adopt fresh180 M101actualtyped/XMFscope80039... successor and at most5disabled owncasebed requests; original17937c47... prospectivefailure preserved, no consumedsource modification.','Observe registered serialCPU2 conversion/XMF/bed and CPU24env2shared2 render actual handles; every newlycompleted owncase advance downstream, never restart liveadmission wait.','Keep current500GiBHomefloor and cumulative512GPUh/3840CPUh/1024qualification/720production and originaldeadline; referenced/valid/pending/live data protected.']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_168.json',cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes());paths=names+[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_168.json').relative_to(R))]+[str((root(n)/'controller-launch-process.json').relative_to(R)) for n in range(1096,1111)]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint 258 visuals and nineteen registered full-time downstream products','--',*paths],cwd=R,check=True);print({'accepted':258,'families':cp['accepted_per_family'],'same_handle_live_count':len(handles),'new_controllers':15,'Home_free_GiB':free,'attempts':attempts,'GPUh':gpu,'CPUcoreh':cpu,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
