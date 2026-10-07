from pathlib import Path
import json,hashlib,subprocess,datetime,copy,collections,math,os,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02');root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md','.png'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def check(e):assert sha(e['path'])==e['sha256'],e['path']
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='da36598b8c133c18cf8985fa195fdd709c0903c3';P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003').glob('root_followup_226_*'));prefix=P.relative_to(W)
expected={'README.md','manifest.json','metadata/source-provenance.json','metadata/root1436-final48-adoption.json','metadata/f2-final48-products.json','scripts/validate_fresh226.py'}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names};assert all((W/n).read_bytes()==b and (R/n).read_bytes()==b for n,b in blobs.items());before={n:sha(W/n) for n in names}
rv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh226.py')],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names} and all((R/n).read_bytes()==b for n,b in blobs.items())
sc=load(R/prefix/'metadata/f2-final48-products.json');assert sc['accepted_actual_product_count']==48 and sc['pending_primary_count']==0
oldp=root(1330)/'F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json';assert sha(oldp)=='74b44471d91e24bef6ce5dd78a811cbf52f7ddc6d521ca4c200f63af1f1e32dd';old=load(oldp);oldmap={r['physical_case_id']:r for r in old['main_corrected_actual_primary_and_published_navigation_sidecars']};assert len(oldmap)==42
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_328.json';cp=load(cpfile);ip=root(1443)/'full336-current332-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile) and cp['stage1_visual_accepted_complete_independent_cases']==332 and cp['accepted_per_family']['F2']==48
f2={r['physical_case_id']:r for r in idx['cases'] if r['family_id']=='F2'};assert len(f2)==48 and all(r.get('accepted_decision') for r in f2.values())
mem=old['membership'];assert all(sc['membership'][k]==mem[k] for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']);ids=mem['registered_final48_physical_case_ids'];assert [r['physical_case_id'] for r in sc['products']]==ids and set(ids)==set(f2)
assert [len(mem[k]) for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']]==[8,24,48] and set(mem['frozen_first8_physical_case_ids'])<=set(mem['actual_first24_physical_case_ids'])<=set(ids)
products=[];pubabs=[];native_cond_abs=[];typed_unknown=[];source_null_masks=[];allcontacts=0;allnav=0
for sr in sc['products']:
 pid=sr['physical_case_id'];row=f2[pid];dr=row['accepted_decision'];check(dr);decision=load(dr['path']);new=pid not in oldmap;qi_ref=None;recovery=None;qa_join=None
 if not new:
  o=oldmap[pid];assert o['accepted_visual_decision']==dr
  er={'native_receipt':o['actual_native_receipt'],'XMF_manifest':o['primary_XMF_manifest'],'XMF_XML':o['primary_XMF_XML'],'render_report':o['primary_render_report'],'render_receipt':o['actual_render_receipt']}
  contacts=o['main_contact_refs'];sourcekeys=o['main_source_key_refs'];oldnav=o['main_published_navigation_keys'];typed_obs=o['source_typed_runtime_observations']
 else:
  qi_ref=sr['proofs']['own_full401_QI'];check(qi_ref);qi=load(qi_ref['path']);assert qi['physical_case_id']==pid and qi['all401_UID_axis_identity_N3_finite_active_states_native_actual_times_verified'];er=qi['actual_completed_metadata_evidence']
  assert all(sr['proofs']['accepted_visual_decision'][k]==dr[k] for k in ['path','sha256']) and all(all(sr['primary_product_metadata'][k][a]==e[a] for a in ['path','sha256']) for k,e in er.items())
  if 'initial_qa_receipt' not in er:
   corrected=decision['actual_completed_metadata_evidence'];assert all(all(corrected[k][a]==e[a] for a in ['path','sha256']) for k,e in er.items())
   er={**er,**{k:corrected[k] for k in ['initial_qa_receipt','initial_qa_report']}}
   assert all(all(sr['primary_product_metadata'][k][a]==er[k][a] for a in ['path','sha256']) for k in ['initial_qa_receipt','initial_qa_report'])
  contacts=decision['contact_sheets'];sourcekeys=decision['keyframes'];oldnav=None;typed_obs=[{'receipt':er['typed_receipt'],'status':'completed','returncode':0}]
 for e in er.values():check(e)
 n=load(er['native_receipt']['path']);x=load(er['XMF_manifest']['path']);r=load(er['render_report']['path']);rc=load(er['render_receipt']['path']);xp=Path(er['XMF_XML']['path']);cid=n['request']['case_id'];N=x['particles']
 assert (n['status'],n['returncode'])==('completed',0) and (rc['status'],rc['returncode'])==('completed',0) and rc['request']['case_id']==cid and x['case_id']==cid and x['physical_case_id']==pid
 if 'conversion_report' in x:
  tr=er.get('typed_report') or ref(x['conversion_report']);check(tr);t=load(tr['path']);assert t['conversion_status']=='completed'
 else:
  assert not new and 'P03' in pid;recovery=x['recovery_provenance'];orig=recovery['original_conversion_receipt'];audit=recovery['artifact_recovery_audit']
  for e in [orig['receipt'],orig['report'],audit['receipt'],audit['report']]:check(e)
  assert load(orig['receipt']['path'])['status']=='running' and 'returncode' not in load(orig['receipt']['path']) and not orig['conversion_completed_claim']
  assert (load(audit['receipt']['path'])['status'],load(audit['receipt']['path'])['returncode'])==('completed',0) and audit['verified_frames']==401 and audit['verified_particles']==418104 and audit['verified_trajectory_sha256']==x['source_h5_sha256'];tr=orig['report'];t=load(tr['path']);typed_unknown.append(pid)
 er={**er,'actual_producer_conversion_report':tr}
 assert t['frames']==x['frames']==r['frames']==r['source_frames']==401 and t['particles']==N and N==(421566 if pid=='F2H10V2_OFFSET_V1' else 418104)
 assert t['solver_dimension']['solver_dimension']==3 and t['typed_identity']['key']=='(Zone,Idp)' and t['partvtk_validation']['all_passed']
 assert t['source_provenance']['solver_receipt']['path']==er['native_receipt']['path'] and t['output_sha256']==x['source_h5_sha256']==r['source_h5_sha256']
 assert r['all_frames_rendered'] and r['actual_times_preserved_exactly'] and r['native_identity_axis_preserved'] and r['nonfinite_active_states']==0 and r['manifest_sha256']==sha(er['XMF_manifest']['path'])
 assert x['xdmf']==str(xp) and x['xdmf_sha256']==sha(xp) and x['fields']['position']['shape']==x['fields']['velocity']['shape']==[401,N,3]
 fs=t['lifecycle']['frame_summary'];ds=r['frame_diagnostics'];gs=ET.parse(xp).findall('.//Grid[@GridType="Uniform"]');times=x['actual_time_s'];assert len(fs)==len(ds)==len(gs)==len(times)==401
 assert times==[f['time'] for f in fs]==[d['actual_time_s'] for d in ds]==[float(g.find('Time').get('Value')) for g in gs] and times[0]==0 and times[-1]>=4 and all(math.isfinite(v) for v in times) and all(a<b for a,b in zip(times,times[1:]))
 for i,(f,d,g) in enumerate(zip(fs,ds,gs)):
  assert f['frame']==d['frame']==i and f['active_particles']==d['active'] and f['missing_particles']==d['missing'] and f['active_particles']+f['missing_particles']==N
  assert all(f['type_counts'][code]==d['type_counts_active'][name] for code,name in [('0','fixed'),('1','moving'),('2','floating'),('3','fluid')])
  assert d['finite_positions_active'] and all(e['finite_active'] and e['nonfinite_active']==0 for e in d['finite_fields'].values())
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')==f'{N} 3';vv=next(a for a in g.findall('Attribute') if a.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')==f'{N} 3'
 gc=t['source_provenance']['gencase_receipt'];xml=t['source_provenance']['generated_xml'];check(gc);check(xml);gcr=load(gc['path']);assert (gcr['status'],gcr['returncode'])==('completed',0)
 if new:
  qrc=load(er['initial_qa_receipt']['path']);qa=load(er['initial_qa_report']['path']);assert (qrc['status'],qrc['returncode'])==('completed',0) and qrc['request']['case_id']==qa['case_id']==cid and qa['status']=='pass' and all(qa['checks'].values())
  assert qa['gencase_receipt']['path']==gc['path'] and qa['gencase_receipt']['sha256']==gc['sha256'] and qa['prepared_evidence']['dimension']==3 and qa['prepared_evidence']['total']==N
  qa_join={'actual_QA_receipt':er['initial_qa_receipt'],'actual_QA_report':er['initial_qa_report'],'genuine_GenCase':gc,'actual_generated_XML':xml,'genuine_initial_QA_pass_not_precision_certificate':True}
 for obs in typed_obs:check(obs['receipt'])
 masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',n['request']),('XMF',x)]}
 if new:
  assert masks==qi['actual_native_XMF_plan_field_namespaces']
  if sr['physical_scope_roles']['actual_native_XMF_plan_namespaces'] is None:source_null_masks.append(pid)
 ncond={'present':'physical_condition_sha256' in n['request'],'value':n['request'].get('physical_condition_sha256')}
 if not ncond['present']:native_cond_abs.append(pid)
 if not new:assert ncond==o['actual_native_condition_field']
 pubp=Path(er['render_report']['path']).parent/'render-publish-receipt.json';pub=load(pubp) if pubp.exists() else None;pubref=ref(pubp) if pub else None
 if pub:
  assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['report_sha256_after_rebind']==sha(er['render_report']['path']);out=Path(pub['published_output_root']);pf={e['relative_path']:e for e in pub['files_excluding_receipt']}
 else:assert not new;pubabs.append(pid);pf={}
 assert len(contacts)==17 and len({e['path'] for e in contacts})==17
 vc=[]
 for e in contacts+sourcekeys:
  p=Path(e['path']);dg=sha(p);decls=[e[k] for k in ['sha256','declared_sha256','producer_sha256'] if e.get(k)];assert decls and all(dg==v for v in decls)
  if pub:assert dg==pf[str(p.relative_to(out))]['sha256'] and p.stat().st_size==pf[str(p.relative_to(out))]['bytes']
  if e in contacts:vc.append({**e,'sha256':dg,'main_actual_PNG_SHA_verified':True})
 frame_dir=Path(sourcekeys[0]['path']).parent if new else Path(oldnav[0]['path']).parent;nav=[]
 for frame in range(0,401,50):
  p=frame_dir/f'frame_{frame:04d}.png';dg=sha(p)
  if pub:assert dg==pf[str(p.relative_to(out))]['sha256']
  else:assert dg==next(e['sha256'] for e in oldnav if e['path']==str(p))
  nav.append({'path':str(p),'sha256':dg,'bytes':p.stat().st_size,'frame':frame,'actual_time_s':times[frame],'role':'navigation metadata, no new personal review'})
 omission={'final_missing_particles':fs[-1]['missing_particles'],'max_missing_per_frame':max(f['missing_particles'] for f in fs),'first_missing_frame':next((f['frame'] for f in fs if f['missing_particles']),None),'cumulative_particle_frame_omissions':sum(f['missing_particles'] for f in fs),'actual_quantified_cause_and_state_unknown_preserved':True,'accepted_decision_omission_limits':decision.get('lifecycle_omissions',decision.get('actual_quantified_missing_fluid'))}
 if new:assert all(omission[k]==qi['lifecycle_omissions'][k] for k in ['final_missing_particles','max_missing_per_frame','first_missing_frame','cumulative_particle_frame_omissions'])
 products.append({'family_id':'F2','case_id':cid,'physical_case_id':pid,'accepted_visual_decision':dr,'own_full401_QI':qi_ref,'primary_metadata':er,'ParaView_open_XMF':er['XMF_XML'],'frames':401,'particles':N,'actual_time_window_s':[times[0],times[-1]],'all401_UID_axis_N3_native_times_finite_render_metadata_verified':True,'genuine_GenCase':gc,'actual_generated_XML':xml,'new6_genuine_initial_QA':qa_join,'old42_initial_QA_limits_inherited_not_new_certification':not new,'actual_native_condition_field':ncond,'actual_typed_producer_scope':t['hash_scopes'].get('physical_condition_sha256'),'actual_XMF_condition_sha256':x['physical_condition_sha256'],'actual_native_XMF_plan_field_namespaces':masks,'source226_null_plan_mask_preserved_as_source_normalization_gap_not_raw_absence':new and sr['physical_scope_roles']['actual_native_XMF_plan_namespaces'] is None,'original_typed_runtime_observations':typed_obs,'P03_original_unfinalized_conversion_and_completed_artifact_audit_roles_preserved':recovery,'lifecycle_omission_metadata':omission,'atomic_publish_receipt':pubref,'legacy_atomic_publish_receipt_absent':pub is None,'contacts17_actual_SHA_verified':vc,'source_personal_key_refs_preserved':sourcekeys,'navigation9_actual_SHA_verified':nav,'old42_corrected_primary_row_preserved':o if not new else None,'new6_own_full401_QI_limits_preserved':qi if new else None,'new_case_credit':0,'new_personal_review':False,'Q_N':0,'Q_E':0,'precision_status':'视觉检查通过、数值精度未验收'})
 allcontacts+=17;allnav+=9
assert len(products)==48 and allcontacts==816 and allnav==432 and len(typed_unknown)==1 and len(native_cond_abs)==1
now=datetime.datetime.now(datetime.timezone.utc);raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(z['kind'] for z in ld['attempts']);gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source226_F2_final48_actual401_UID_N3_times_816contacts432navigation_P03_unknown_and_old_scope_limits_preserved_1444';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_329.json';assert not O.exists() and not np.exists();O.mkdir()
proof=O/'source226-main48-full401-own-metadata-PNG-joins-and-original-runtime-limits-proof.json';put(proof,{'schema':'ds02.main.source226.F2.final48.actual-primary-proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_exact_files':[ref(R/n) for n in names],'source_before_after_SHA':before,'validator_stdout':rv.stdout,'main_all48_direct_native401_XML_N3_exact_times_UID_render_metadata_checked':True,'main_new6_actual_initial_QA_receipts_and_reports_pass_GenCase_joins_checked':True,'old42_QA_limits_inherited_not_new_percase_initial_certificate':True,'published_contacts_SHA_verified':allcontacts,'navigation_keys_SHA_verified':allnav,'original_typed_runtime_unknown_cases':typed_unknown,'actual_native_condition_absence_cases':native_cond_abs,'actual_atomic_publish_receipt_absence_cases':pubabs,'source226_new_null_plan_mask_cases_raw_masks_directly_recovered_in_main_sidecar':source_null_masks,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'new_case_credit':0,'Q_N':0,'Q_E':0})
product=O/'F2-FINAL48-COMPLETE-ACTUAL401-PRIMARY-DELIVERY.json';put(product,{'schema':'ds02.main.F2.actual-final48-complete-primary.v1','at_utc':now.isoformat(),'authoritative_checkpoint':ref(cpfile),'source226_catalog':ref(R/prefix/'metadata/f2-final48-products.json'),'main_independent_verification':ref(proof),'membership':mem,'accepted48_actual_primary_rows':products,'pending_cases':[],'delivery_complete':True,'accepted48_primary_bindings_complete':True,'legacy_unknowns_and_field_absences_preserved':True,'new_case_credit':0,'Q_N':0,'Q_E':0,'scientific_payload_IO':False})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);newcp=copy.deepcopy(cp);newcp.update(checkpoint=329,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: previous goal turn accepted330to332 and completed two F5ownQIs. This turn F2final48 actual primary401 delivered after direct48 metadata and816contact432navigation checks, originalP03typedunknown and legacy scope limits retained.',authorized_work_state='Active332/336 remaining4. F2 actual final48 primary complete; F5two completedQIs pending personal204/228; original1101/1149 render. Final F3/F5 and global actual336 delivery remains required.')
newcp['actual_progress']['F2_final48_complete_actual_primary_delivery']=ref(product);newcp['next_executable_tasks'].insert(0,'Integrate delegated F5personal204/228 with actual1440/1442 QIs then extend F5current45 product; after1101/1149 natural0/pub complete fullQI and delegate reviews; finalize all336 actual primary delivery.')
put(np,newcp);idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0);idx['F2_final48_complete_actual_primary_delivery']=ref(product);put(O/'full336-current332-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
(O/'README.md').write_text('F2最终48个独立物理案例实际401帧动态主文件交付；frozen8⊂actual24⊂final48保持不变。核对实际XML/原生时间/UID/N3/有限状态及816张总览和432张导航图SHA，保留粒子遗漏和原P03 typed135运行状态未知、真实artifact197完成证据、母例421566粒子和原native条件字段缺失、四例旧renderrequest462纠正以及legacy发布缺口。新六例真实初态QA单独核对；旧42例初态限制继承。视觉检查通过、数值精度未验收。\n')
paths=[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: complete actual F2 final48 primary401 delivery retaining legacy runtime and scope limits','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':329,'accepted':332,'F2_actual_final_primary':48,'contacts':allcontacts,'navigation':allnav,'typed_unknown':typed_unknown,'native_condition_absent':native_cond_abs,'atomic_publish_absence_count':len(pubabs),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
