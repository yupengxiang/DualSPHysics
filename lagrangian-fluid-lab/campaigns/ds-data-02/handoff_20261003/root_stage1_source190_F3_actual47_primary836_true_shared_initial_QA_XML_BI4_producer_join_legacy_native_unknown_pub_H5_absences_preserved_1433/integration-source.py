from pathlib import Path
import json,hashlib,subprocess,datetime,copy,collections,math,os,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md','.png'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def check(e):assert sha(e['path'])==e['sha256'],e['path']
def same(a,b):return a['path']==b['path'] and a['sha256']==b['sha256']
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='67cdcc626ceae43c31fb6023bfd858dcc3e9be03';P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003').glob('root_followup_190_*'));prefix=P.relative_to(W)
expected={'README.md','manifest.json','build_fresh190.py','validate_fresh190.py','F3-ACTUAL-FINAL48-PRIMARY-47ACCEPTED-ONE-PENDING.json'}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names};assert all((W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b) for n,b in blobs.items())
before={n:sha(W/n) for n in names};manifest=load(P/'manifest.json');assert manifest['manifest_self_hash_excluded'] and set(manifest['files'])==expected-{'manifest.json'}
rv=subprocess.run(['python3','-B',str(P/'validate_fresh190.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
sc=load(P/'F3-ACTUAL-FINAL48-PRIMARY-47ACCEPTED-ONE-PENDING.json');assert len(sc['rows'])==48 and sc['delivery']['accepted_visual_count']==47 and sc['delivery']['pending_visual_count']==1 and not sc['delivery']['delivery_complete']
oldp=root(1328)/'F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json';old=load(oldp);oldrows=old['main_accepted_primary_and_published_navigation_sidecars'];assert len(oldrows)==39;oldmap={r['physical_case_id']:r for r in oldrows}
assert sc['authoritative_sources']['root1328_f3_actual39_primary_catalog']['sha256']==sha(oldp)
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_320.json';cp=load(cpfile);ip=root(1432)/'full336-current330-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile) and cp['stage1_visual_accepted_complete_independent_cases']==330 and cp['accepted_per_family']['F3']==47
f3=[r for r in idx['cases'] if r['family_id']=='F3'];accepted=[r for r in f3 if r.get('accepted_decision')];pending=[r for r in f3 if not r.get('accepted_decision')];assert len(f3)==48 and len(accepted)==47 and len(pending)==1
assert {r['physical_case_id'] for r in sc['rows']}=={r['physical_case_id'] for r in f3}
mem=old['membership'];assert all(sc['membership'][k]==mem[k] for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids'])
first8=mem['frozen_first8_physical_case_ids'];first24=mem['actual_first24_physical_case_ids'];final48=mem['registered_final48_physical_case_ids'];assert (len(first8),len(first24),len(final48))==(8,24,48) and set(first8)<=set(first24)<=set(final48)
qiref0=load(root(1411)/'actual1129-full836-completed-QI-UID-N3-native-scope-previsual-proof.json');qaref=qiref0['initial_parent_QA_report'];qarcref=qiref0['initial_parent_QA_receipt'];check(qaref);check(qarcref);qa=load(qaref['path']);qarc=load(qarcref['path']);assert (qarc['status'],qarc['returncode'])==('completed',0)
qa0=next(z for z in qa['cases'] if z['role']=='twoaxis_dp006');assert qa0['passed'] and qa0['actual_3d'] and qa0['native_particles']==179208 and qa0['native_fixed']==111708 and qa0['native_fluid']==67500
products=[];old_unknown=0;native_abs_id=0;scope_diffs=0;render_h5_abs=[];publish_abs=[];allcontacts=0;allnav=0
for row in accepted:
 pid=row['physical_case_id'];cid=row['case_id'];dref=row['accepted_decision'];check(dref);decision=load(dref['path']);new=pid not in oldmap
 if not new:
  oldrow=oldmap[pid];assert same(oldrow['accepted_visual_decision'],dref)
  refs={'native_receipt':oldrow['actual_native_receipt'],'typed_report':oldrow['primary_typed_report'],'XMF_manifest':oldrow['primary_XMF_manifest'],'XMF_XML':oldrow['primary_XMF_XML'],'render_report':oldrow['primary_render_report'],'render_receipt':oldrow['primary_render_receipt']}
  contacts=oldrow['main_actual_contact_refs'];sourcekeys=oldrow['main_actual_source_enumerated_key_refs'];recovery=oldrow['actual_registered_orphan_native_completion_recovery_boundary'];qi_ref=None
 else:
  qi_ref=decision['independent_full836_QI'];check(qi_ref);qi=load(qi_ref['path']);assert qi['case_id']==cid and qi['physical_case_id']==pid
  if 'actual_completed_receipts' in qi:
   rr=qi['actual_completed_receipts'];refs={'native_receipt':rr['native'],'typed_report':qi['typed_report'],'XMF_manifest':qi['XMF_manifest'],'XMF_XML':qi['XMF_XML'],'render_report':qi['render_report'],'render_receipt':rr['render']}
  else:
   er=qi['actual_completed_metadata_evidence'];refs={'native_receipt':er['actual_native_receipt'],'typed_report':er['actual_producer_conversion_report'],'XMF_manifest':er['actual_XMF_manifest'],'XMF_XML':er['actual_XMF_XML'],'render_report':er['actual_render_report'],'render_receipt':er['actual_render_receipt']}
  contacts=decision['contact_sheets'];sourcekeys=decision['keyframes'];assert len(contacts)==35 and len(sourcekeys)==9;recovery=None
 for e in refs.values():check(e)
 n=load(refs['native_receipt']['path']);t=load(refs['typed_report']['path']);x=load(refs['XMF_manifest']['path']);r=load(refs['render_report']['path']);rc=load(refs['render_receipt']['path']);xp=Path(refs['XMF_XML']['path'])
 assert n['request']['case_id']==cid and t['source_provenance']['solver_receipt']['path']==refs['native_receipt']['path'] and x['physical_case_id']==pid and rc['request']['case_id']==cid and rc['status']=='completed' and rc['returncode']==0
 if n['status']=='completed':assert n['returncode']==0
 else:
  assert not new and n['status']=='running' and 'returncode' not in n and recovery is not None;old_unknown+=1
  for k in ['actual_completed_recovery_audit_receipt','actual_native_completion_recovery_report','actual_recovered_full836_conversion_sidecar']:check(recovery[k])
  audit=load(recovery['actual_completed_recovery_audit_receipt']['path']);assert (audit['status'],audit['returncode'])==('completed',0) and recovery['registered_auditor_verified_full_native_completion_and_source_inputs_unchanged']
 assert t['conversion_status']=='completed' and t['frames']==x['frames']==r['frames']==836 and t['particles']==x['particles']==179208
 assert t['solver_dimension']['solver_dimension']==3 and t['partvtk_validation']['all_passed'] and t['typed_identity']['key']=='(Zone,Idp)' and t['typed_identity']['initial_exclusion_ledger']['count']==0
 assert r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['native_identity_axis_preserved'] and r['nonfinite_active_states']==0 and r['manifest_sha256']==sha(refs['XMF_manifest']['path'])
 assert t['output_sha256']==x['source_h5_sha256'] # Metadata attestations, never H5 hash.
 assert x['xdmf']==str(xp) and x['xdmf_sha256']==sha(xp) and x['fields']['position']['shape']==x['fields']['velocity']['shape']==[836,179208,3]
 fs=t['lifecycle']['frame_summary'];ds=r['frame_diagnostics'];grids=ET.parse(xp).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s'];assert len(fs)==len(ds)==len(grids)==len(times)==836
 assert times==[z['time'] for z in fs]==[z['actual_time_s'] for z in ds]==[float(g.find('Time').get('Value')) for g in grids] and times[0]==0 and all(math.isfinite(v) for v in times) and all(a<b for a,b in zip(times,times[1:]))
 for i,(f,d,g) in enumerate(zip(fs,ds,grids)):
  assert f['frame']==d['frame']==i and f['active_particles']==d['active']==179208 and f['missing_particles']==d['missing']==0 and f['type_counts']=={'0':111708,'1':0,'2':0,'3':67500}
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='179208 3';vv=next(a for a in g.findall('Attribute') if a.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')=='179208 3'
 generated=t['source_provenance']['generated_xml'];gc_ref=t['source_provenance']['gencase_receipt'];check(generated);check(gc_ref);gc=load(gc_ref['path']);assert (gc['status'],gc['returncode'])==('completed',0)
 assert generated['sha256']==qa0['generated_xml_sha256'];matching=[p for p,dg in n['input_hashes_at_launch'].items() if p.lower().endswith('.bi4') and dg==qa0['native_initial_BI4_sha256']];assert matching
 qa_join={'genuine_shared_initial_parent_QA_report':qaref,'genuine_shared_initial_parent_QA_receipt':qarcref,'QA_role':'twoaxis_dp006','actual_generated_XML':generated,'actual_GenCase_or_clone_preparation_receipt':gc_ref,'generated_XML_actual_digest_equals_genuine_QA':True,'native_initial_BI4_launch_attested_matching_paths':matching,'native_initial_BI4_digest_source':'producer launch metadata only; BI4 not read or hashed','native_initial_BI4_launch_digest_equals_genuine_QA':True,'shared_initial_geometry_QA_not_percase_independent_forcing_QA':True,'original_native_after_field_present':'input_hashes_after_run' in n,'original_native_after_initial_BI4_match':all(n.get('input_hashes_after_run',{}).get(p)==qa0['native_initial_BI4_sha256'] for p in matching) if 'input_hashes_after_run' in n else None}
 if qa_join['original_native_after_field_present']:assert qa_join['original_native_after_initial_BI4_match']
 nq=n['request'];native_abs_id+=int('physical_case_id' not in nq);nativecond=nq.get('physical_condition_sha256');scope_diffs+=int(nativecond!=x['physical_condition_sha256'])
 masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]}
 hp=t['output_hdf5'];beforeH=rc['input_hashes_at_launch'].get(hp);afterH=rc.get('input_hashes_after_run',{}).get(hp);hmask={'launch_field_present':hp in rc['input_hashes_at_launch'],'launch_digest':beforeH,'after_field_present':hp in rc.get('input_hashes_after_run',{}),'after_digest':afterH,'absence_not_filled_from_producer_or_manifest':True}
 if hmask['launch_field_present']:assert beforeH==t['output_sha256']
 if hmask['after_field_present']:assert afterH==t['output_sha256']
 if not hmask['launch_field_present'] or not hmask['after_field_present']:render_h5_abs.append(pid)
 pubp=Path(refs['render_report']['path']).parent/'render-publish-receipt.json';pub=load(pubp) if pubp.is_file() else None;pubref=ref(pubp) if pub else None
 if pub:
  assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==sha(refs['render_report']['path']);pubroot=Path(pub['published_output_root']);pfiles={e['relative_path']:e for e in pub['files_excluding_receipt']}
 else:
  assert not new;publish_abs.append(pid);pubroot=None;pfiles={}
 assert len(contacts)==35 and len({e['path'] for e in contacts})==35
 verified_contacts=[]
 for e in contacts+sourcekeys:
  p=Path(e['path']);dg=sha(p);declarations=[e[k] for k in ['sha256','declared_sha256','producer_sha256'] if k in e];assert declarations and all(dg==declared for declared in declarations)
  if e in contacts:verified_contacts.append({**e,'sha256':dg,'main_actual_PNG_SHA_verified':True})
  if pub:assert dg==pfiles[str(p.relative_to(pubroot))]['sha256'] and p.stat().st_size==pfiles[str(p.relative_to(pubroot))]['bytes']
 if new:
  assert [e['path'] for e in contacts]==r['outputs']['contact_sheets'];frame_dir=Path(r['outputs']['frames_dir'])
 else:
  oldnav=oldrow['main_published_navigation_keys'];assert len(oldnav)==9;frame_dir=Path(oldnav[0]['path']).parent
 navigation=[]
 for frame in [0,100,200,300,400,500,600,700,835]:
  p=frame_dir/f'frame_{frame:04d}.png';dg=sha(p)
  if pub:assert dg==pfiles[str(p.relative_to(pubroot))]['sha256']
  else:assert dg==next(e['sha256'] for e in oldrow['main_published_navigation_keys'] if e['path']==str(p))
  navigation.append({'path':str(p),'sha256':dg,'bytes':p.stat().st_size,'frame':frame,'actual_time_s':times[frame],'role':'main navigation metadata; no new personal visual review'})
 contacts=verified_contacts;assert len(contacts)==35
 allcontacts+=35;allnav+=9
 products.append({'family_id':'F3','case_id':cid,'physical_case_id':pid,'accepted_visual_decision':dref,'own_completed_full836_QI':qi_ref,'primary_metadata':refs,'ParaView_open_XMF':refs['XMF_XML'],'actual_time_window_s':[times[0],times[-1]],'frames':836,'particles':179208,'all836_UID_type_N3_exact_native_times_render_identity_and_finite_aggregate_verified':True,'initial_geometry_QA_join':qa_join,'actual_native_runtime_status':n['status'],'actual_native_runtime_returncode_field_present':'returncode' in n,'actual_native_runtime_returncode':n.get('returncode'),'registered_native_completion_recovery':recovery,'actual_native_physical_case_id_field_present':'physical_case_id' in nq,'actual_native_physical_case_id':nq.get('physical_case_id'),'actual_native_condition_sha256':nativecond,'actual_XMF_condition_sha256':x['physical_condition_sha256'],'actual_native_XMF_plan_field_namespaces':masks,'actual_typed_runtime_boundary_inherited_from_immutable_acceptance':decision.get('original_typed154_runtime') if new else None,'native_fields_not_backfilled':True,'render_H5_launch_after_attestation_presence':hmask,'atomic_publish_receipt':pubref,'atomic_publish_receipt_actual_field_absent':pub is None,'contacts35_actual_SHA_verified':contacts,'source_enumerated_keys_preserved':sourcekeys,'source_key_field_absence_preserved':oldrow['source_unlisted_key_field_preserved'] if not new else False,'navigation_keys9_actual_SHA_verified':navigation,'original39_primary_role_limits_preserved':oldrow if not new else None,'new_case_credit':0,'new_personal_review':False,'Q_N':0,'Q_E':0,'precision_status':'视觉检查通过、数值精度未验收'})
assert old_unknown==4 and native_abs_id==1 and len(products)==47 and allcontacts==1645 and allnav==423
now=datetime.datetime.now(datetime.timezone.utc);raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(z['kind'] for z in ld['attempts']);gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30;assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source190_F3_actual47_primary836_true_shared_initial_QA_XML_BI4_producer_join_legacy_native_unknown_pub_H5_absences_preserved_1433';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_321.json';assert not O.exists() and not np.exists();O.mkdir()
for name,b in blobs.items():p=R/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
cv=subprocess.run(['python3','-B',str(R/prefix/'validate_fresh190.py')],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr);assert all((R/name).read_bytes()==b and (W/name).read_bytes()==b for name,b in blobs.items())
proof=O/'source190-byte-exact-readonly-validator-main47-full836-initial-QA-role-and-preview-proof.json'
put(proof,{'schema':'ds02.main.source190.actualF3.primary47.independent-proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/name) for name in names],'source_before_after_SHA':before,'source_manifest_has_no_content_digests_main_pins_exact_commit_bytes':True,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'source_builder_full_read_but_not_executed':True,'source_validator_scope_is_metadata_reference_validation_not_full_runtime_or_QA_certificate':True,'main_direct_actual47_own_primary_joins':True,'main_all47_XML_N3_times_UID_and_actual_render_metadata_checked':True,'main_all47_genuine_shared_initial_QA_generated_XML_actual_SHA_and_native_initial_BI4_producer_digest_join_verified':True,'main_native_BI4_H5_CSV_scientific_payload_IO':False,'main_published_PNG_SHA_only_no_personal_view':True,'published_contacts_checked':allcontacts,'main_navigation_keys_checked':allnav,'native_original_runtime_unknown_count_preserved':old_unknown,'native_actual_physical_id_absence_count_preserved':native_abs_id,'native_XMF_scope_role_differences_preserved':scope_diffs,'actual_render_H5_launch_or_after_attestation_absence_cases':render_h5_abs,'actual_atomic_publish_receipt_absence_cases':publish_abs,'new_case_credit':0,'Q_N':0,'Q_E':0})
product=O/'F3-FINAL48-ACTUAL47ACCEPTED-ONEPENDING-PRIMARY-DELIVERY.json';put(product,{'schema':'ds02.main.F3.actual-final48-primary.47accepted-onepending.v1','at_utc':now.isoformat(),'status':'47 visual-approved actual primary bindings, original1101 pending','authoritative_checkpoint':ref(cpfile),'source_catalog':ref(R/prefix/'F3-ACTUAL-FINAL48-PRIMARY-47ACCEPTED-ONE-PENDING.json'),'main_independent_verification':ref(proof),'membership':{k:mem[k] for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']},'accepted47_actual_primary_rows':products,'pending1_registered_physical_cases':[{'physical_case_id':pending[0]['physical_case_id'],'case_id':pending[0]['case_id'],'original_render':1101,'accepted_decision':None,'own836QI1427_completed':False,'readiness':idx['last_F3_original1101_durable836_QI'],'personal_visual_review':False,'case_credit':0}],'delivery_complete':False,'accepted47_product_primary_bindings_complete':True,'new_case_credit':0,'Q_N':0,'Q_E':0,'scientific_payload_IO':False,'all47_initial_QA_is_shared_geometry_reuse_not_independent_percase_QA':True,'native_original_runtime_unknowns_and_legacy_atomic_publish_H5_attestation_absences_remain_transparent':True})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp);new.update(checkpoint=321,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: accepted330/336; source190 F3 actual47 primary product extended from true39, all47 836 UID/N3/time and genuine initialQA XML/native-BI4 producer joins plus1645 contacts423 navigation verified; native4unknown and legacypub/H5attestation absences retained.',authorized_work_state='Active330/336 remaining6. F3 actual47 primary delivered with original1101 pending. F2/F5 actual47/44 final primary products delegated224/202; last six registered renders need natural completion and delegated visual acceptance.')
new['actual_progress']['F3_current47_actual_primary_delivery']=ref(product);new['next_executable_tasks'].insert(0,'Integrate assigned-F2 fresh224 and assigned-F5 fresh202 actual primary deliveries; after actual1101 completed0/published execute own1427 once and delegate personal35+9 then extend F3 to complete48.')
put(np,new);idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0);idx['F3_current47_actual_primary_delivery']=ref(product);put(O/'full336-current330-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());(O/'README.md').write_text('F3 实际47例完整动态主文件交付，最终48例中 original1101 尚待渲染和个人视觉验收。47例逐一核对836帧UID/N3/时间/真实来源与共享初态QA；保留4原native运行收据无返回码、legacy原子发布/H5渲染启动与结束凭证缺口、母例native物理ID缺失及不同scope角色。共核对1645张动画总览和423张导航关键帧SHA，不新增个人视觉审查或案例计数。视觉检查通过、数值精度未验收。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: extend actual F3 primary delivery to47 with genuine shared initial QA joins and preserved legacy runtime limits','--',*paths],cwd=R,check=True);print(json.dumps({'checkpoint':321,'accepted':330,'F3_actual_primary':47,'contacts':allcontacts,'navigation':allnav,'native_unknown':old_unknown,'atomic_publish_absences':len(publish_abs),'render_H5_attestation_absences':len(render_h5_abs),'product':str(product),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
