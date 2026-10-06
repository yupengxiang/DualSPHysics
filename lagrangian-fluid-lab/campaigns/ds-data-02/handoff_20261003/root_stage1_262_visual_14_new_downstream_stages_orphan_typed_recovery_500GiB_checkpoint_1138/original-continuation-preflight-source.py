from pathlib import Path
import json,hashlib,subprocess,datetime,os,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'};return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
cp_path=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_173.json';cp=load(cp_path);assert cp['stage1_visual_accepted_complete_independent_cases']==262
O=next(H.glob('root*_1138'));now=datetime.datetime.now(datetime.timezone.utc).isoformat();paths=[]
adopt=load(O/'source139-140-154-byte-exact-adoption.json')
for package in adopt['packages']:
 for row in package['files']:
  assert sha(R/row['path'])==row['sha256'];paths.append(row['path'])
assert not (H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_174.json').exists()
probe1=load('/tmp/ds02-AY0270-orphan-reconciliation-probe1.json');ledger=load(D/'runtime/resource-ledger.json');probe2={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'probe':2,'pids':[{'pid':pid,'exists':Path('/proc',str(pid)).exists()} for pid in [2367325,2367173]],'matching_reservations':[a for a in ledger['reservations'] if 'ay0270-full836-typed-nvme-154' in str(a)],'original_receipt':ref(D/'families/F3/F3_STAGE1_DP006_P1000_AY0270/root-stage1-f3-ay0270-full836-typed-nvme-154/execution-receipt.json'),'new_status_inferred':False}
assert not any(p['exists'] for p in probe1['pids']+probe2['pids']) and not probe1['matching_reservations'] and not probe2['matching_reservations']
old=load(probe2['original_receipt']['path']);assert old['status']=='running' and old.get('returncode') is None
put(O/'AY0270-main-double-probe-original-receipt-preserved.json',{'probe1':probe1,'probe2':probe2,'original_receipt_preserved_running_unknown_exit':True,'original_receipt_returncode_key_present':'returncode' in old,'original_OS_exit_not_inferred':True,'physical_identity_roles':'old real receipt F3_TWOAXIS_PITCH1000_AY0270_STAGE1_FIRST24_NEW; census alias F3_TWOAXIS_P1000_AY0270_STAGE1_FIRST48_PITCH_VARIANT. Preserve and audit alias before any credit.','next_action':'fresh141 disabled registered full836 H5 read-only audit; actual Root review before downstream, no native/typed rerun or old receipt rewrite','case_credit':0})
handles=[];terminals=[]
for d in sorted(H.glob('root*')):
 m=re.search(r'_(\d+)$',d.name)
 if not m or int(m.group(1))<940:continue
 p=d/'controller-launch-process.json'
 if not p.exists():continue
 j=load(p);st=Path(f"/proc/{j['pid']}/stat");live=False
 if st.exists():
  a=st.read_text().split(') ',1)[1].split();live=a[0]!='Z' and a[19]==str(j['proc_start_ticks'])
 row={'root':int(m.group(1)),'launch':ref(p),'pid':j['pid'],'start_ticks':j['proc_start_ticks'],'same_handle_live_now':live}
 if live:handles.append(row)
 else:
  if (d/'controller-result.json').exists():row['actual_terminal_result']=ref(d/'controller-result.json')
  elif (d/'controller.stderr.log').exists():row['missing_handle_and_original_stderr']=ref(d/'controller.stderr.log')
  terminals.append(row)
put(O/'actual_live_handles_and_terminal_receipts.json',{'at_utc':now,'live':handles,'terminal_or_missing_handle':terminals,'no_restart_from_timeout':True})
roots=[*range(1125,1134),1135,1136,1137];registered=[];total={2:0,24:0}
for n in roots:
 d=root(n);c=load(d/'controller-config.json');qs=c.get('requests',[c.get('request')]);assert qs and all(qs)
 for qp in qs:
  q=load(qp);assert q['kind']=='cpu' and q['cpu_threads'] in [2,24] and q['case_credit']==0 and not q['disabled'];total[q['cpu_threads']]+=1
  for p,h in q['input_sha256'].items():
   if Path(p).suffix.lower() not in {'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu'}:assert sha(p)==h,(n,p)
  if q['cpu_threads']==24:
   w=load(q['command'][-1]);assert w['expected_contact_sheets']==q['expected_contact_sheets']==(q['expected_frames']+23)//24 and len(w['keyframe_indices'])==9 and w['environment_threads']==2 and w['global_renderer_cap']==2
  registered.append({'root':n,'request':ref(qp),'physical_case_id':q['physical_case_id'],'cpu_threads':q['cpu_threads'],'actual_attempt_root':q['attempt_root'],'case_credit':0})
assert len(registered)==14 and total=={2:4,24:10}
put(O/'registered14-new-downstream-stage-requests.json',{'at_utc':now,'controller_count':12,'render_requests':10,'XMF_requests':4,'requests':registered,'CPU24env2_shared_cap':2,'CPU2_scientific_serial_cap':1,'stage_requests_are_not_case_count':True,'source182_adoption':ref(root(1134)/'source182-byte-exact-adoption-and-readonly-validation.json'),'1130_metadata_preflight_preserved':'Absent SourceDef alias recovered from own native source_condition/source_xml exactSHA+bed plan; original failed preflight and source bytes preserved, no worker or enabled consumer existed before repair.'})
for p,h in [(root(142)/'launch.py','708c4c83d22257f7b59bad93cd19915fb66a199a2a5b1291d6ada71bb467ea76'),(L/'scripts/ds_data02_runtime_v2.py','5098262e26dc5560487760181466b0a93a0e66239e5e761ae67a60'),(L/'scripts/ds_data02_strict_dispatch_v1.py','81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'),(root(928)/'fair_CPU_dispatch.py','e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f')]:assert sha(p)==h
raw=(D/'runtime/resource-ledger.json').read_bytes();(O/'resource-ledger-frozen.json').write_bytes(raw);ledger=json.loads(raw);st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30;assert free>=500
counts={k:sum(a['kind']==k for a in ledger['attempts']) for k in ['qualification','production','cpu']};gpu=sum(a.get('gpu_seconds',0) for a in ledger['charges'])/3600;cpu=sum(a.get('cpu_core_seconds',0) for a in ledger['charges'])/3600;assert gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720
cp.update(checkpoint=174,at_utc=now,predecessor=str(cp_path),predecessor_sha256=sha(cp_path),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(O/'resource-ledger-frozen.json'),active_reservations=ledger['reservations'],attempt_counts=counts,gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='Progress: authorized cleanup515.503GiB reverified all15997 absent16receipts unchanged Home774.75GiB. Currentcontinuation registered14 actual downstream stages via12 controllers:10fullrenders4XMF; source182two M088 ownbed0 all801closed; source139/140/154 exactadopted and reconciled. AY0270 missinghistoricalPIDs/noreservation doubleprobe preserves originalrunning/null, bounded audit preparation active. No extra case or numerical credit.')
cp['actual_progress'].update(current_root1138_live_and_terminal_handles=ref(O/'actual_live_handles_and_terminal_receipts.json'),registered14_new_stages_no_case_credit=ref(O/'registered14-new-downstream-stage-requests.json'),source139140154_exactadoption_main_scope_reconciliation=ref(O/'source139-140-154-byte-exact-adoption.json'),AY0270_unfinalized_typed_double_probe=ref(O/'AY0270-main-double-probe-original-receipt-preserved.json'))
cp['source_agents'].update(production_recovery='fresh139/140 exactadopted; fresh141 disabled full836 read-only audit preparation active, no old receipt rewrite',f6_endpoint_initial_qa='fresh154 expansion subset census adopted; fresh155 new personal visual or two true-ready XMF disabled metadata active',f5_bed_recovery='fresh182 two M088 adopted1134 renders1130/1131 live; fresh183 four original138 beds or true-readyvisual active')
cp['next_executable_tasks']=['Observe ten renders1126/1127/1128/1129/1130/1131/1132/1135/1136/1137 and four XMF1125three/1133one:actual0 then delegated allcontacts/9keys beforecredit.','Adopt fresh183 true1060three and1107M114085 XMF0 original138 disabled beds; main801UIDfinite/scopeclosure; no duplicate.','Adopt fresh141 AY0270 new readonly audit; preserve old unknownexit and physicalID vs censusalias; actualCPU2serial1 audit0 and independentRootreview before downstream.','Observe remaining988M104095,1013RX063105,1020RX061105 typed; XMF1076AY0640/1117RX063090/1118RX061075; advance real0 only.','Root1082 originalwrapper35 stilllive: actualterminal beforebounded34 successor. Root951lastF6 real241render+fullaudit+personal11contacts9keys beforecredit.','Full336goal74missing; originaldeadline/resourcecounters,500GiBfloor,Q-N/Q-E0.']
put(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_174.json',cp);(O/'checkpoint-source.py').write_bytes(Path(__file__).read_bytes())
paths += [str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str((H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_174.json').relative_to(R))]+[str((root(n)/'controller-launch-process.json').relative_to(R)) for n in roots]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: checkpoint 262 visuals fourteen new downstream stages and orphan recovery evidence','--',*paths],cwd=R,check=True)
print({'checkpoint':174,'accepted':262,'families':cp['accepted_per_family'],'remaining':74,'same_handles_live':len(handles),'Home_free_GiB':free,'GPUh':gpu,'CPUcoreh':cpu,'attempts':counts,'new_registered_stages':14,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
