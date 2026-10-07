from pathlib import Path
import json,hashlib,subprocess,datetime,copy,collections,os,re
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.png','.py','.md'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def checked(e):
 if isinstance(e,str):e={'path':e}
 p=Path(e['path']);assert p.is_file()
 if e.get('sha256'):assert sha(p)==e['sha256'],str(p)
 if e.get('bytes') is not None:assert p.stat().st_size==e['bytes'],str(p)
 return ref(p)
def put(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
commit='3160085bf0016a4f936fa68477449892bd7781f8';prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_172_f3_final48_primary_delivery_39accepted_nine_pending_v1');P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==5
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};rv=subprocess.run(['python3','-B',str(P/'validate_fresh172.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
for e in load(P/'package-manifest.json')['files']:assert sha(P/e['path'])==e['sha256']
sp=P/'F3-FINAL48-PRIMARY-DELIVERY-39ACCEPTED-NINE-PENDING.json';assert sha(sp)=='cdc2015aeaa5c4bcc4159ef7973dd856e17e7cbd9a1645f1a7cef071432cb6e3';s=load(sp)
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_251.json';cp=load(cpfile);assert cp['checkpoint']==251 and cp['stage1_visual_accepted_complete_independent_cases']==300 and cp['accepted_per_family']['F3']==39
ip=root(1326)/'full336-current300-actual-final48-delivery-progress-index.json';index=load(ip);current={r['physical_case_id']:r for r in index['cases'] if r['family_id']=='F3'}
fixed=load(root(1276)/'F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json');member=s['membership'];f8=member['frozen_first8_physical_case_ids'];f24=member['actual_first24_physical_case_ids'];f48=member['registered_final48_physical_case_ids']
assert len(set(f8))==8 and len(set(f24))==24 and len(set(f48))==48 and set(f8)<=set(f24)<=set(f48)==set(current)
assert f8==fixed['frozen_first8_physical_case_ids'] and f24==fixed['actual_first24_physical_case_ids']
verified=[];pendingverified=[];contacts=keys=navcount=0;diffs=[];idabs=[];unlisted=[];native_recovery_boundaries=[]
for row in s['rows']:
 pid=row['physical_case_id'];a=row.get('accepted_visual_metadata')
 if not a:
  p=row['pending_metadata'];ready=p['source166_case_metadata'];assert ready['physical_case_id']==pid and ready['visual_credit']==0 and p['accepted_decision'] is None and p['primary_particle_xmf_render_refs'] is None and p['primary_png_refs'] is None and not current[pid].get('accepted_decision')
  rr=ready['actual_metadata_evidence']
  for e in rr.values():checked(e)
  for group in ['native_metadata_refs','typed_metadata_refs','xmf_metadata_refs','artifact_audit_metadata_refs']:
   for e in p[group]:checked(e)
  m=load(rr['xmf_manifest']['path']);nr=load(rr['native_receipt']['path']);nq=nr['request'];tr=load(rr['typed_receipt']['path']);xr=load(rr['xmf_receipt']['path'])
  assert nr['status']=='completed' and nr['returncode']==0 and xr['status']=='completed' and xr['returncode']==0
  assert nr['request']['physical_condition_sha256']==ready['native_condition_sha256']==current[pid]['native_request_scope']['sha256']
  assert m['physical_case_id']==pid and m['frames']==836 and m['particles']==179208
  if ready['original_typed_receipt_still_unknown']:
   assert 'AY0270' in pid and tr['status']=='running' and 'returncode' not in tr
  else:assert tr['status']=='completed' and tr['returncode']==0
  currentQI=None
  for orig,qn in [(1141,1324),(1135,1325)]:
   if m['case_id']==('F3_STAGE1_DP006_P1200_AY0640' if orig==1141 else 'F3_STAGE1_DP006_P1200_AY0570'):
    currentQI=ref(root(qn)/f'actual{orig}-full836-completed-QI-UID-N3-native-scope-previsual-proof.json')
  pendingverified.append({'physical_case_id':pid,'actual_readiness_metadata_reverified':rr,'actual_native_completed0':True,'actual_typed_status_retained':tr['status'],'actual_typed_returncode_field_present':'returncode' in tr,'actual_typed_returncode':tr.get('returncode'),'original_pending154_not_promoted':ready['original_typed_receipt_still_unknown'],'actual_XMF_manifest':ref(rr['xmf_manifest']['path']),'current_completed_original_QI_pending_visual':currentQI,'source_historical_live_snapshot_is_not_current_status':True,'accepted_decision':None,'visual_credit':0,'main_scientific_payload_IO':False});continue
 assert a['accepted_decision']==current[pid]['accepted_decision'];checked(a['accepted_decision'])
 mp=Path(a['actual_xmf_manifest']['path']);xp=Path(a['actual_xmf_xml']['path']);rp=Path(a['actual_render_report']['path']);rcp=Path(a['actual_render_receipt']['path'])
 for e in [a['actual_xmf_manifest'],a['actual_xmf_xml'],a['actual_render_report'],a['actual_render_receipt']]:checked(e)
 m=load(mp);r=load(rp);rc=load(rcp);nativep=Path(m['native_receipt']);nr=load(nativep);nq=nr['request']
 assert rc['status']=='completed' and rc['returncode']==0
 if nr['status']=='completed':assert nr['returncode']==0
 else:assert nr['status']=='running' and 'returncode' not in nr
 assert m['physical_case_id']==pid and m['frames']==r['frames']==836 and m['particles']==179208
 if 'source_frames' in r:assert r['source_frames']==836
 assert r['all_frames_rendered'] and not r['diagnostic_only'] and r['nonfinite_active_states']==0 and r['native_identity_axis_preserved'] and r['actual_times_preserved_exactly']
 assert r['manifest_sha256']==sha(mp) and r['input_manifest']==str(mp)
 if 'native_receipt_sha256' in m:assert m['native_receipt_sha256']==sha(nativep)
 assert m['xdmf_sha256']==sha(xp) and m['xdmf']==str(xp)
 for k,value in [('source_h5_sha256',m['source_h5_sha256']),('xdmf',str(xp)),('xdmf_sha256_before',sha(xp)),('xdmf_sha256_after',sha(xp))]:
  if k in r:assert r[k]==value
 typedreport=Path(m['conversion_report']);t=load(typedreport)
 assert t['output_sha256']==m['source_h5_sha256'] and t['source_provenance']['solver_receipt']==ref(nativep)
 recovery_boundary=None
 if nr['status']=='running':
  alternatives=current[pid]['historical_native_alternate_completion_evidence']
  for e in alternatives:assert sha(e['path'])==e['observed_sha256'] and (not e.get('declared_sha256') or e['declared_sha256']==e['observed_sha256'])
  scp=next(Path(e['path']) for e in alternatives if e['role']=='bindings.recovery_conversion_sidecar');ar=next(Path(e['path']) for e in alternatives if e['role']=='bindings.recovery_audit_receipt')
  sc=load(scp);checked(sc['recovery']);checked(sc['reconciliation']);auditreceipt=load(ar);audit=load(sc['recovery']['path'])
  assert auditreceipt['status']=='completed' and auditreceipt['returncode']==0 and audit['status']=='native-completion-verified-runtime-finalization-unavailable'
  assert not audit['runtime_receipts_modified'] and not sc['original_runtime_receipts_modified'] and sc['runtime_returncode_unobserved'] and sc['converted_all_frames']==836 and sc['output_sha256']==m['source_h5_sha256']
  observed=next(e for e in audit['cases'] if e['physical_case_id']==pid)
  assert observed==sc['observations'][0]['native_completion'] and observed['runtime_receipt']['path']==str(nativep) and observed['runtime_receipt']['sha256']==sha(nativep)
  assert observed['native_solver_completed_evidence'] and observed['native_log_finish_code']==0 and observed['actual_native_frames']==836 and observed['native_total_particles']==179208 and observed['native_parts_out']==0 and observed['source_inputs_unchanged'] and observed['runtime_process_returncode_unobserved']
  assert abs(observed['actual_last_time_s']-m['actual_time_s'][-1])<=1e-6
  for ih in [auditreceipt['input_hashes_at_launch'],auditreceipt['input_hashes_after_run']]:assert ih[str(nativep)]==sha(nativep)
  recovery_boundary={'physical_case_id':pid,'original_native_receipt':ref(nativep),'original_status':'running','original_process_returncode_field_present':False,'original_process_returncode':None,'actual_completed_recovery_audit_receipt':ref(ar),'actual_native_completion_recovery_report':checked(sc['recovery']),'actual_recovered_full836_conversion_sidecar':ref(scp),'actual_native_frames':836,'native_solver_log_finish_code_observed_by_registered_auditor':0,'original_runtime_process_returncode_not_inferred_from_native_log':True,'registered_auditor_verified_full_native_completion_and_source_inputs_unchanged':True,'audit_declared_physical_condition_sha256_retained_not_used_as_native_condition_authority':observed['physical_condition_sha256'],'native_scientific_logs_and_CSV_not_read_or_hashed_by_main':True};native_recovery_boundaries.append(recovery_boundary)
 assert [x['frame'] for x in r['frame_diagnostics']]==list(range(836)) and [x['actual_time_s'] for x in r['frame_diagnostics']]==m['actual_time_s']
 assert m['fields']['position']['shape']==m['fields']['velocity']['shape']==[836,179208,3]
 h5launch=rc['input_hashes_at_launch'].get(m['trajectory_h5']);h5after=rc['input_hashes_after_run'].get(m['trajectory_h5'])
 for ih in [rc['input_hashes_at_launch'],rc['input_hashes_after_run']]:assert ih[str(mp)]==sha(mp) and ih[str(xp)]==sha(xp)
 if h5launch is not None or h5after is not None:assert h5launch==h5after==m['source_h5_sha256']
 canonical=nq['physical_condition_sha256'];assert canonical==current[pid]['native_request_scope']['sha256']
 roles=a['native_vs_xmf_role_metadata'];assert roles['native_request_physical_condition_sha256']==canonical and roles['xmf_manifest_physical_condition_sha256']==m['physical_condition_sha256'] and roles['native_request_physical_case_id_field_present']==('physical_case_id' in nq) and roles['native_request_physical_case_id']==nq.get('physical_case_id')
 if canonical!=m['physical_condition_sha256']:diffs.append(pid)
 if 'physical_case_id' not in nq:idabs.append(pid)
 else:assert nq['physical_case_id']==pid
 for group in ['native_refs','typed_refs']:
  for e in a[group]:checked(e)
 cpng=a['contact_png_refs'];kpng=a['key_png_refs'];contactpaths=[e if isinstance(e,str) else e['path'] for e in cpng];assert len(cpng)==35
 if 'outputs' in r:assert contactpaths==r['outputs']['contact_sheets']
 else:assert all(Path(p).parent==rp.parent for p in contactpaths)
 cref=[checked(e) for e in cpng];kref=[checked(e) for e in kpng];contacts+=len(cref);keys+=len(kref)
 if not kpng:unlisted.append(pid)
 fd=Path(r['outputs']['frames_dir']) if 'outputs' in r else rp.parent/'frames';assert fd.is_relative_to(D) and sorted(p.name for p in fd.glob('frame_*.png'))==[f'frame_{i:04d}.png' for i in range(836)]
 nav=[]
 for i in [0,100,200,300,400,500,600,700,835]:
  fp=fd/f'frame_{i:04d}.png';assert fp.is_file() and fp.stat().st_size>0;nav.append({**ref(fp),'bytes':fp.stat().st_size,'frame':i,'actual_time_s':m['actual_time_s'][i],'role':'main_actual_published_navigation_not_new_personal_review'})
 navcount+=len(nav)
 verified.append({'physical_case_id':pid,'accepted_visual_decision':checked(a['accepted_decision']),'actual_native_receipt':ref(nativep),'actual_native_runtime_status':nr['status'],'actual_native_runtime_returncode_field_present':'returncode' in nr,'actual_native_runtime_returncode':nr.get('returncode'),'actual_registered_orphan_native_completion_recovery_boundary':recovery_boundary,'actual_native_case_id':nq['case_id'],'actual_native_physical_case_id_field_present':'physical_case_id' in nq,'actual_native_physical_case_id':nq.get('physical_case_id'),'native_canonical_condition_sha256':canonical,'own_XMF_declared_condition_sha256':m['physical_condition_sha256'],'native_and_XMF_scope_role_difference_retained':canonical!=m['physical_condition_sha256'],'native_actual_field_not_filled_from_typed_or_XMF':True,'primary_XMF_manifest':ref(mp),'primary_XMF_XML':ref(xp),'primary_typed_report':ref(typedreport),'primary_render_report':ref(rp),'primary_render_receipt':ref(rcp),'all836_particle_native_time_identity_N3_render_metadata_bindings_verified':True,'legacy_raw_render_report_field_masks':{k:{'present':k in r,'value':r.get(k) if k!='outputs' else None} for k in ['source_frames','source_h5_sha256','xdmf','xdmf_sha256_before','xdmf_sha256_after','outputs']},'actual_render_receipt_H5_launch_attestation_field_present':h5launch is not None,'actual_render_receipt_H5_after_attestation_field_present':h5after is not None,'actual_render_receipt_H5_launch_digest':h5launch,'actual_render_receipt_H5_after_digest':h5after,'own_manifest_and_XML_digests_bound_by_actual_render_receipt':True,'typed_producer_H5_digest_equals_own_manifest':True,'missing_H5_render_attestation_not_filled_from_producer_or_manifest':True,'main_does_not_new_certify_legacy_render_H5_payload_bytes':h5launch is None,'source_contacts_verified':len(cpng),'source_keys_verified':len(kpng),'source_unlisted_key_field_preserved':not bool(kpng),'main_actual_contact_refs':cref,'main_actual_source_enumerated_key_refs':kref,'main_published_navigation_keys':nav,'new_case_credit':0,'new_personal_visual_review':False,'main_scientific_payload_IO':False})
assert len(verified)==39 and len(pendingverified)==9 and contacts==1365 and keys==185 and navcount==351 and len(unlisted)==13 and len(diffs)==15 and idabs==['F3_TWOAXIS_AY0P50_PITCH_NOMINAL']
assert len(native_recovery_boundaries)==4
raw=(D/'runtime/resource-ledger.json').read_bytes();ledger=json.loads(raw);counts=collections.Counter(r['kind'] for r in ledger['attempts']);gpu=sum(r.get('gpu_seconds',0) for r in ledger['charges'])/3600;cpu=sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])/3600;v=os.statvfs('/home/jade');free=v.f_bavail*v.f_frsize/2**30;now=datetime.datetime.now(datetime.timezone.utc)
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source172_F3_final48_actual39_visual_primary_bindings_15_native_XMF_role_differences_mother_id_absence_351_navigation_keys_nine_pending_1328';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_252.json';assert not O.exists() and not np.exists();O.mkdir()
for n,b in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
vp=O/'source172-byte-exact-readonly-validator-main39-own-particle-render-preview-and9-readiness-proof.json';put(vp,{'schema':'ds02.main.source172.actualF3-final48-primary-proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'before_after_SHA':before,'validator_stdout':rv.stdout,'validator_stderr':rv.stderr,'main_accepted39_primary_bindings':verified,'main_pending9_readiness_boundaries':pendingverified,'four_original_native_unknown_runtime_receipts_and_actual_completed_recovery_audit_preserved':native_recovery_boundaries,'legacy_H5_render_launch_after_attestation_absence_count':sum(not r['actual_render_receipt_H5_launch_attestation_field_present'] for r in verified),'native_vs_XMF_15_scope_role_differences':diffs,'native_request_physical_case_id_true_absences':idabs,'source_contacts_SHA_verified':contacts,'source_keys_SHA_verified':keys,'source13_unlisted_key_cases_retained':unlisted,'main_actual_published_navigation_keys351':navcount,'new_case_credit':0,'new_personal_visual_review':False,'main_scientific_payload_IO':False,'Q_N':0,'Q_E':0})
product=copy.deepcopy(s);product.update(schema='ds02.main.F3.final48.actual39accepted-ninepending-primary-delivery.v1',status='actual39_primary_visual_metadata_verified_nine_visual_pending',at_utc=now.isoformat(),source_original_exact_package=ref(R/prefix/sp.name),stable_predecessor_checkpoint=ref(cpfile),main_independent_verification=ref(vp));product['main_accepted_primary_and_published_navigation_sidecars']=verified;product['main_pending_readiness_and_original_receipt_boundary_sidecars']=pendingverified
pp=O/'F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json';put(pp,product);snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw)
new=copy.deepcopy(cp);new.update(checkpoint=252,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ledger['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: originalF3 full836 1141 and1135 completed0/published, ownQI1324/1325 complete, personalfresh207/186 reviews active. Source172 actualF3 final48 catalog independently verified39 primary animations and1365contacts185sourcekeys plus351real navigation previews; native/XMF15role differences and mother physical-id absence retained; ninepending and oldtyped154 unknownreceipt not promoted.',authorized_work_state='Active300/336; F3=39 with actual original1141 and1135 both own836QI ready but not yet visualaccepted. ActualF3final48 primary39/9 delivery joined; source173 F2final48 actual42/6 catalog assigned. OriginalF5 1181 M105T080 and1191 M112T095 now automatically rendering on same faircap2.')
new['actual_progress']['F3_final48_primary_actual39accepted_ninepending_delivery']=ref(pp);new['actual_progress']['F3_final48_primary_actual39_main_independent_proof']=ref(vp)
for orig,qn in [(1141,1324),(1135,1325)]:new['actual_progress'][f'actual{orig}_full836_own_QI']=ref(root(qn)/f'actual{orig}-full836-completed-QI-UID-N3-native-scope-previsual-proof.json')
new['source_agents']['production_recovery']='fresh172 actualF3 final48 catalog39accepted/ninepending exact adopted, own39primary and15scope differences verified; nextfresh173 F2final48 actual42accepted/sixpending in progress'
put(np,new);index.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0);index['actual_F3_final48_primary_39accepted_ninepending_delivery']=ref(pp)
for r in index['cases']:
 if r['family_id']=='F3':r['actual_F3_final48_primary_39accepted_ninepending_delivery']=ref(pp)
put(O/'full336-current300-actual-final48-delivery-progress-index.json',index);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());(O/'README.md').write_text('F3最终注册48例当前39通过/9待审图的真实目录，固定8⊂24⊂48。主进程核对39个本例836帧粒子动画、1365contact/185源枚举key，并另列351实际发布导航key；源13个未枚举key的事实保留。15个实际native与XMF条件字段的不同角色原样保留，mother native物理ID字段缺失不补值；pending154转换收据未知仍不升级。两个original1141/1135已经完成实际渲染和ownQI，但尚未个人视觉通过，继续pending。未读科学payload，不新增案例或精度信用。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: deliver actualF3 final48 primary39 preserving native and XMF role differences and nine pending','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':252,'accepted':300,'F3_primary_verified':39,'pending_readiness':9,'contacts':contacts,'sourcekeys':keys,'navigationkeys':navcount,'condition_role_differences':len(diffs),'product':ref(pp),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
