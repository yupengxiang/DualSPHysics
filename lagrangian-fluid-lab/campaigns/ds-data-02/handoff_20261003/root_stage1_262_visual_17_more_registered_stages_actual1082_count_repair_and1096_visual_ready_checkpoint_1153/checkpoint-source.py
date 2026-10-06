from pathlib import Path
import json,hashlib,datetime,os,subprocess,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
old=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_174.json';cp=load(old);assert cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==262 and cp['numeric_reference_accepted_independent_products']==0
outcp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_175.json';assert not outcp.exists();O=H/'root_stage1_262_visual_17_more_registered_stages_actual1082_count_repair_and1096_visual_ready_checkpoint_1153';O.mkdir(exist_ok=False);now=datetime.datetime.now(datetime.timezone.utc).isoformat();rows=[];totals={2:0,24:0};paths=[]
for n in range(1139,1153):
 d=root(n);cfg=load(d/'controller-config.json');qs=cfg.get('requests',[cfg.get('request')]);assert all(qs)
 for qp in qs:
  q=load(qp);assert q['kind']=='cpu' and not q['disabled'] and q['case_credit']==0 and q['cpu_threads'] in [2,24];totals[q['cpu_threads']]+=1
  for p,digest in q['input_sha256'].items():
   if Path(p).suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu'}:assert sha(p)==digest,(n,p)
  if q['cpu_threads']==24:
   w=load(q['command'][-1]);assert w['expected_frames']==q['expected_frames'] and w['expected_contact_sheets']==q['expected_contact_sheets']==(q['expected_frames']+23)//24 and len(w['keyframe_indices'])==9 and w['environment_threads']==2 and w['global_renderer_cap']==2
  rows.append({'root':n,'request':ref(qp),'physical_case_id':q['physical_case_id'],'cpu_threads':q['cpu_threads'],'actual_attempt_root':q['attempt_root'],'case_credit':0})
 launch=d/'controller-launch-process.json';assert launch.exists();paths.append(str(launch.relative_to(R)))
assert len(rows)==17 and totals=={2:7,24:10}
put(O/'registered17-additional-stages-no-extra-case-credit.json',{'at_utc':now,'controllers':14,'render_requests':10,'bed_requests':4,'XMF_requests':3,'requests':rows,'stage_requests_are_not_case_count':True,'original_CPU2_serial1_CPU24env2_shared2_guards_preserved':True,'source183_four_beds_independent_adoption':ref(root(1140)/'source183-four-full801-bed-independent-adoption-review.json'),'actual1082_terminal_count_failure_bounded_render_only_repair1':ref(root(1139)/'actual1082-count-rejection-immutable-render-repair1.json'),'case_credit':0})
oldq=load(root(1082)/'enabled-full801-render-request.json');oldrp=Path(oldq['attempt_root'])/'execution-receipt.json';assert (load(oldrp)['status'],load(oldrp)['returncode'])==('failed',1)
readyq=load(root(1096)/'enabled-full801-render-request.json');rp=Path(readyq['attempt_root'])/'execution-receipt.json';rr=Path(readyq['attempt_root'])/'render/paraview-full-animation-report.json';assert (load(rp)['status'],load(rp)['returncode'])==('completed',0) and rr.is_file()
put(O/'1096-full801-render0-personal-visual-review-pending.json',{'actual_render_receipt':ref(rp),'actual_render_report':ref(rr),'case_id':readyq['case_id'],'physical_case_id':readyq['physical_case_id'],'render_completed0':True,'delegated_personal_review':'fresh184 active, all34contacts and9keys required','stage1_visual_credit_before_review':0,'Q_N':0,'Q_E':0,'actual1082_oldfailed_receipt_preserved':ref(oldrp)})
live=[];terminal=[]
for d in sorted(H.glob('root*')):
 m=re.search(r'_(\d+)$',d.name)
 if not m or int(m.group(1))<940:continue
 p=d/'controller-launch-process.json'
 if not p.exists():continue
 j=load(p);st=Path(f"/proc/{j['pid']}/stat");match=False
 if st.exists():
  a=st.read_text().split(') ',1)[1].split();match=a[0]!='Z' and a[19]==str(j['proc_start_ticks'])
 v={'root':int(m.group(1)),'launch':ref(p),'pid':j['pid'],'start_ticks':j['proc_start_ticks'],'same_handle_live_now':match}
 if match:live.append(v)
 else:
  if (d/'controller-result.json').exists():v['actual_terminal_result']=ref(d/'controller-result.json')
  elif (d/'controller.stderr.log').exists():v['original_stderr_for_missing_handle']=ref(d/'controller.stderr.log')
  terminal.append(v)
put(O/'current-live-handles-and-terminal-receipts.json',{'at_utc':now,'live':live,'terminal_or_missing':terminal,'no_restart_from_observation_timeout':True})
guardrefs=load(root(928)/'fair_CPU_dispatch.py') if False else None
# Verify unchanged dispatch sources against previously registered immutable digests.
q0=load(root(1127)/'enabled-full801-render-request.json')
for p in [root(142)/'launch.py',root(142)/'root_home_floor_inventory_policy.py',root(928)/'fair_CPU_dispatch.py',L/'scripts/ds_data02_runtime_v2.py',L/'scripts/ds_data02_strict_dispatch_v1.py']:
 assert sha(p)==q0['input_sha256'][str(p)]
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);(O/'resource-ledger-frozen.json').write_bytes(raw)
counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']};gpu=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720
cp.update(checkpoint=175,at_utc=now,predecessor=str(old),predecessor_sha256=sha(old),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts=counts,gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='Progress:31 actual new downstream stage registrations via26 controllers sincecp173:20renders7XMF4beds. One new actual1096full801render0 readyfor delegatedpersonalreview; actual1082failedcontact35guard renderer0/publishrejected/stageremoved preserved, new1139repair1correct34 onlyrenderer rerun. Full goal336 still262accepted; no sourcearrays/no duplicate native or numerical credit.')
cp['actual_progress'].update(current_root1153_live_terminal_handles=ref(O/'current-live-handles-and-terminal-receipts.json'),registered17_additional_stages=ref(O/'registered17-additional-stages-no-extra-case-credit.json'),actual1096_full801_render0_visual_pending=ref(O/'1096-full801-render0-personal-visual-review-pending.json'))
cp['source_agents'].update(production_recovery='fresh141 disabled AY0270 readonly audit package active; original unknownOSexit preserved; maindoubleprobe frozen1138',f5_bed_recovery='fresh183 adopted1140 fourbeds live; fresh184 personal34contacts9keys actual1096 visual active',f6_endpoint_initial_qa='fresh155/156 sourcecommitted pendingadoption; fresh157 twoactual1085 mother-case-alias original138 disabledbeds prepared in ownF6 handoff active')
cp['next_executable_tasks']=['Accept fresh184 M090T085 onlyafter real all34contact9key personalreview and independent801GenQA/native/typed/XMF/bed/render closure; real1096render0 ready.','Adopt fresh141 AY0270 bounded readonly H5 audit; preserve originalrunning/returncodekeyabsent and unknownOSexit, exactoriginalactualphysicalID vs censusalias; newregisteredCPU2 auditactual0 beforeXMF.','Adopt fresh157 two M095T090/T100 actual1085 mothercasealias ownGenQA/native/typed/XMF0 original138 disabledbeds if trulycompatible; identitybyphysicalcase/control notparentdirectory.','Observe1139 bounded render-only count34repair1, four1140beds,1144/1145F2lasttwoXMF,1146F5M104095XMF and20newrenders sincecp173. Advance real0 and delegatepersonalvisual.','Remaining newF5XMF1125M102085/095/M104085,1133M114095,1146M104095 to independent801beds thenrender; legacy1085/1087/1104 alias-caseXMF to original138-bed onlywith realscopeclosure.','LastF6Root951samePID/starttick36of37waiting actual241render thenfullaudits11contacts9keys; no duplicatedalreadycompleted.','Full336goal74missing; Q-N/Q-E0, originaldeadline/resources, Homefloor500GiB, preserveallvalidpendinglive/referenced data and failureaudit.']
put(outcp,cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes());paths += [str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str(outcp.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint 262 visuals seventeen further downstream stages and actual count repair','--',*paths],cwd=R,check=True)
print({'checkpoint':175,'accepted':262,'families':cp['accepted_per_family'],'remaining':74,'current_live_controllers':len(live),'Home_free_GiB':free,'GPUh':gpu,'CPUcoreh':cpu,'attempts':counts,'new_since174_stage_requests':17,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
