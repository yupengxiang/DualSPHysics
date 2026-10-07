from pathlib import Path
import json, hashlib, subprocess, datetime, copy, collections, math, os
import xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.xml','.xmf','.py','.md','.png'}
 if p.suffix.lower()=='.png':assert p.is_relative_to(D) and not p.is_symlink()
 return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
def check(e):assert sha(e['path'])==e.get('sha256',e.get('declared_sha256')),e['path']
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='4bebd9b1ae327fcd179b932190f3a30f26c3bf18'
P=next((W/'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003').glob('root_followup_202_*'));prefix=P.relative_to(W)
expected={'README.md','package-manifest.json','metadata/f5-final48-primary-bed-delivery.json','scripts/build_fresh202.py','scripts/validate_fresh202.py'}
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines()
assert {str(Path(n).relative_to(prefix)) for n in names}==expected
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
assert all((W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b) for n,b in blobs.items())
before={n:sha(W/n) for n in names}
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh202.py'),'--package',str(P)],capture_output=True,text=True)
assert rv.returncode==0,(rv.stdout,rv.stderr);assert before=={n:sha(W/n) for n in names}
sc=load(P/'metadata/f5-final48-primary-bed-delivery.json')
oldp=root(1344)/'F5-FINAL48-CURRENT30ACCEPTED18PENDING-ACTUAL801-PRIMARY-BED-DELIVERY.json';old=load(oldp)
assert sha(oldp)=='582608bcb99a7abbcb8821ec3ec4a8a5b00da2143ee8fc77b45c5aa262cd3d85'
oldmap={r['physical_case_id']:r for r in old['main_current_accepted30_actual_primary_rows']};assert len(oldmap)==30
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_323.json';cp=load(cpfile)
ip=root(1436)/'full336-current331-actual-final48-delivery-progress-index.json';idx=load(ip)
assert idx['source_authoritative_checkpoint']==ref(cpfile) and cp['stage1_visual_accepted_complete_independent_cases']==331 and cp['accepted_per_family']['F5']==44
rows=[r for r in idx['cases'] if r['family_id']=='F5'];accepted=[r for r in rows if r.get('accepted_decision')];pending=[r for r in rows if not r.get('accepted_decision')]
assert (len(accepted),len(pending))==(44,4)
sm={r['physical_case_id']:r for r in sc['accepted_products']};assert set(sm)=={r['physical_case_id'] for r in accepted}
mem=old['membership'];assert sc['membership']['arrays']==mem
assert [len(mem[k]) for k in ['frozen_first8_physical_case_ids','actual_first24_physical_case_ids','registered_final48_physical_case_ids']]==[8,24,48]
assert set(mem['frozen_first8_physical_case_ids'])<=set(mem['actual_first24_physical_case_ids'])<=set(mem['registered_final48_physical_case_ids'])=={r['physical_case_id'] for r in rows}
products=[];pubabs=[];habs=[];contacts_count=0;nav_count=0;source_normalization_limits=[]
for row in accepted:
 pid=row['physical_case_id'];decision_ref=row['accepted_decision'];check(decision_ref);decision=load(decision_ref['path']);new=pid not in oldmap;sr=sm[pid]
 assert sr['acceptance']['accepted_decision']['path']['path']==decision_ref['path']
 qi_ref=None
 if not new:
  o=oldmap[pid];check(o['accepted_visual_decision']);assert o['accepted_visual_decision']==decision_ref
  er={'native_receipt':o['actual_native_receipt'],'typed_report':o['primary_typed_report'],'xmf_manifest':o['primary_XMF_manifest'],'xmf_xml':o['primary_XMF_XML'],'render_receipt':o['actual_render_execution_receipt'],'render_report':o['primary_render_report'],'bed_receipt':o['actual_full801_bed_receipt'],'bed_report':o['actual_full801_bed_report']}
  contacts=o['actual_source_contacts'];sourcekeys=o['actual_source_keys'];oldnav=o['main_actual_published_navigation_keys']
 else:
  qi_ref=row['actual_full801_QI'];check(qi_ref);qi=load(qi_ref['path'])
  assert qi['physical_case_id']==pid and qi['full_frames']==801 and qi['particles']==194427 and qi['all801_geometry_velocity_N3_times_UID_finite_verified'] and qi['all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked']
  assert qi['all_native_UIDs_active_each_frame'] and not qi['q_n_granted'] and not qi['q_e_granted']
  er=qi['actual_completed_metadata_evidence'];contacts=decision['contact_sheets'];sourcekeys=decision['keyframes'];oldnav=None
 for e in er.values():check(e)
 n=load(er['native_receipt']['path']);t=load(er['typed_report']['path']);x=load(er['xmf_manifest']['path']);r=load(er['render_report']['path']);rc=load(er['render_receipt']['path']);b=load(er['bed_report']['path']);bc=load(er['bed_receipt']['path']);xp=Path(er['xmf_xml']['path']);cid=n['request']['case_id']
 for j in [n,rc,bc]:assert (j['status'],j['returncode'])==('completed',0) and j['request']['case_id']==cid
 assert x['physical_case_id']==pid and x['case_id']==cid and t['source_provenance']['solver_receipt']['path']==er['native_receipt']['path']
 assert t['conversion_status']=='completed' and t['frames']==x['frames']==r['frames']==801 and t['particles']==x['particles']==194427
 assert t['solver_dimension']['solver_dimension']==3 and t['typed_identity']['key']=='(Zone,Idp)' and t['partvtk_validation']['all_passed']
 assert r['all_frames_rendered'] and r['native_identity_axis_preserved'] and r['actual_times_preserved_exactly'] and r['nonfinite_active_states']==0 and r['manifest_sha256']==sha(er['xmf_manifest']['path'])
 assert t['output_sha256']==x['source_h5_sha256']==r['source_h5_sha256']==b['source']['trajectory_h5_sha256']
 assert b['source']['trajectory_h5']==t['output_hdf5'] and b['source']['xdmf']==str(xp) and b['source']['xdmf_sha256']==sha(xp)
 assert x['xdmf']==str(xp) and x['xdmf_sha256']==sha(xp) and x['fields']['position']['shape']==x['fields']['velocity']['shape']==[801,194427,3]
 times=x['actual_time_s'];fs=t['lifecycle']['frame_summary'];ds=r['frame_diagnostics'];bs=b['frame_reports'];gs=ET.parse(xp).findall('.//Grid[@GridType="Uniform"]')
 assert len(times)==len(fs)==len(ds)==len(bs)==len(gs)==801
 assert times==[f['time'] for f in fs]==[d['actual_time_s'] for d in ds]==[z['time_s'] for z in bs]==[float(g.find('Time').get('Value')) for g in gs]
 assert times[0]==0 and times[-1]>=16 and all(math.isfinite(v) for v in times) and all(a<c for a,c in zip(times,times[1:]))
 for i,(f,d,z,g) in enumerate(zip(fs,ds,bs,gs)):
  assert f['frame']==d['frame']==z['frame']==i and f['active_particles']==d['active']==194427 and f['missing_particles']==d['missing']==0 and f['type_counts']=={'0':158559,'1':4210,'2':0,'3':31658}
  assert d['finite_positions_active'] and all(e['finite_active'] and e['nonfinite_active']==0 for e in d['finite_fields'].values())
  assert z['initial_fluid_uid_count']==z['current_valid_type3_fluid_count']==31658 and z['nonfinite_initial_fluid_uid_count']==0
  assert z['penetration']['one_dp']['count']==z['penetration']['two_dp']['count']==0
  assert g.find('Geometry').get('GeometryType')=='XYZ' and g.find('Geometry/DataItem').get('Dimensions')=='194427 3'
  vv=next(a for a in g.findall('Attribute') if a.get('Name').lower()=='velocity');assert vv.get('AttributeType')=='Vector' and vv.find('DataItem').get('Dimensions')=='194427 3'
 # Genuine initial placement receipts remain distinct from full-bed and raw scatter diagnostics.
 records=b['bound_actual_inputs']['records']
 for e in records:check(e)
 gc=t['source_provenance']['gencase_receipt'];xml=t['source_provenance']['generated_xml'];check(gc);check(xml);gcr=load(gc['path']);assert (gcr['status'],gcr['returncode'])==('completed',0)
 if new:qar=er['initial_qa_receipt'];qaf=er['initial_qa_report']
 else:
  qar=next(e for e in records if e['role'] in ['initial_qa_receipt','stage1_placement_receipt'])
  qaf=next(e for e in records if e['role'] in ['initial_qa_report','stage1_placement_report'])
 check(qar);check(qaf);qa=load(qaf['path']);qrc=load(qar['path'])
 assert (qrc['status'],qrc['returncode'])==('completed',0) and qa['all_basic_placement_checks_pass'] and qa['actual_counts']['solver_dimension']==3 and qa['actual_counts']['total_particles']==194427 and not qa['numerical_precision_result_accepted']
 assert qa['gencase_attempt_id']==gcr['request']['attempt_id']
 bi=qa['input_provenance']['generated_bi4_sha256'];bi_matches=[p for p,dg in n['input_hashes_at_launch'].items() if p.lower().endswith('.bi4') and dg==bi];assert bi_matches
 nq=n['request'];masks={ns:{k:{'present':k in obj,'value':obj.get(k)} for k in ['source_plan_condition_sha256','source_plan_physical_condition_sha256']} for ns,obj in [('native',nq),('XMF',x)]}
 if new:
  assert nq['physical_condition_sha256']==qi['canonical_actual_native_request_condition_sha256'] and t['hash_scopes']['physical_condition_sha256']==qi['actual_converter_legacy_scope_sha256']
  assert masks==qi['actual_native_XMF_plan_field_namespaces']
 else:
  raw=o['actual_native_typed_XMF_bed_raw_role_masks'];assert masks['native']==raw['native_plan_namespaces'] and masks['XMF']==raw['XMF_plan_namespaces']
 hp=t['output_hdf5'];hm={stage:{'present':hp in rc.get(field,{}),'value':rc.get(field,{}).get(hp)} for stage,field in [('launch','input_hashes_at_launch'),('after','input_hashes_after_run')]}
 for m in hm.values():
  if m['present']:assert m['value']==t['output_sha256']
 if not all(v['present'] for v in hm.values()):habs.append(pid)
 pubp=Path(er['render_report']['path']).parent/'render-publish-receipt.json';pub=load(pubp) if pubp.is_file() else None;pubref=ref(pubp) if pub else None
 if pub:
  assert pub['status']=='published_after_atomic_rename' and pub['case_id']==cid and pub['attempt_id']==rc['request']['attempt_id'] and pub['report_sha256_after_rebind']==sha(er['render_report']['path'])
  pubroot=Path(pub['published_output_root']);pf={z['relative_path']:z for z in pub['files_excluding_receipt']}
 else:assert not new;pubabs.append(pid);pf={}
 assert len(contacts)==34 and len({e['path'] for e in contacts})==34
 verified=[]
 for e in contacts+sourcekeys:
  p=Path(e['path']);dg=sha(p);decls=[e[k] for k in ['sha256','declared_sha256','producer_sha256'] if e.get(k)];assert decls and all(v==dg for v in decls)
  if pub:assert dg==pf[str(p.relative_to(pubroot))]['sha256'] and p.stat().st_size==pf[str(p.relative_to(pubroot))]['bytes']
  if e in contacts:verified.append({**e,'sha256':dg,'main_actual_PNG_SHA_verified':True})
 frame_dir=Path(sourcekeys[0]['path']).parent if new else Path(oldnav[0]['path']).parent;nav=[]
 for i in range(0,801,100):
  p=frame_dir/f'frame_{i:04d}.png';dg=sha(p)
  if pub:assert dg==pf[str(p.relative_to(pubroot))]['sha256']
  else:assert dg==next(e['sha256'] for e in oldnav if e['path']==str(p))
  nav.append({'path':str(p),'sha256':dg,'bytes':p.stat().st_size,'frame':i,'actual_time_s':times[i],'role':'navigation metadata, no new personal review'})
 for e in sr['render_products']['contacts']+sr['render_products']['navigation_keys']:check(e)
 # The source normalization is a locator, not a stronger per-case certificate.
 source_normalization_limits.append({'physical_case_id':pid,'source_initial_QA_ref_present':sr['primary'].get('initial_qa_receipt') is not None,'main_actual_initial_QA_ref':qar,'source_new_plan_JSON_ref_present':sr.get('source_scope_roles',{}).get('source_plan_JSON') is not None if new else None})
 products.append({'family_id':'F5','case_id':cid,'physical_case_id':pid,'accepted_visual_decision':decision_ref,'own_full801_QI':qi_ref,'primary_metadata':er,'ParaView_open_XMF':er['xmf_xml'],'frames':801,'particles':194427,'actual_time_window_s':[times[0],times[-1]],'all801_UID_N3_native_times_finite_render_and_fullbed_metadata_verified':True,'genuine_initial_placement_QA':{'receipt':qar,'report':qaf,'GenCase':gc,'generated_XML':xml,'native_initial_BI4_launch_matching_paths':bi_matches,'BI4_hash_is_producer_attestation_not_main_payload_IO':True,'numerical_precision_negative_preserved':qa['numerical_precision']},'actual_native_physical_condition_sha256':nq.get('physical_condition_sha256'),'actual_typed_scope_sha256':t['hash_scopes'].get('physical_condition_sha256'),'actual_XMF_condition_sha256':x.get('physical_condition_sha256'),'actual_native_XMF_plan_field_namespaces':masks,'actual_bed_source_plan_physical_condition_field':{'present':'source_plan_physical_condition_sha256' in b,'value':b.get('source_plan_physical_condition_sha256')},'render_H5_launch_after_field_masks':hm,'atomic_publish_receipt':pubref,'legacy_atomic_publish_receipt_absent':pub is None,'contacts34_actual_SHA_verified':verified,'source_personal_key_refs_preserved':sourcekeys,'navigation9_actual_SHA_verified':nav,'original_legacy30_row_preserved':o if not new else None,'new14_own_QI_limits_preserved':qi if new else None,'new_case_credit':0,'new_personal_review':False,'Q_N':0,'Q_E':0,'precision_status':'视觉检查通过、数值精度未验收','zero_bed_bins_are_not_subDP_or_precision_certification':True})
 contacts_count+=34;nav_count+=9
assert len(products)==44 and contacts_count==1496 and nav_count==396
assert set(pubabs)=={'F5_COMPACT_RUNUP_RECOVERY_C082S1_A080','F5_COMPACT_RUNUP_RECOVERY_C082S1_A120','F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T080','F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100'}
now=datetime.datetime.now(datetime.timezone.utc);raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);ct=collections.Counter(z['kind'] for z in ld['attempts']);gpu=sum(z.get('gpu_seconds',0) for z in ld['charges'])/3600;cpu=sum(z.get('cpu_core_seconds',0) for z in ld['charges'])/3600;st=os.statvfs('/home/jade');free=st.f_bavail*st.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and ct['qualification']<=1024 and ct['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
O=H/'root_stage1_source202_F5_actual44_primary801_fullbed_genuine_initial_QA_BI4_producer_join_four_legacy_pub_absences_retained_1437';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_324.json';assert not O.exists() and not np.exists();O.mkdir()
for name,data in blobs.items():p=R/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh202.py'),'--package',str(R/prefix)],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((R/name).read_bytes()==data and (W/name).read_bytes()==data for name,data in blobs.items())
proof=O/'source202-byte-exact-readonly-validator-main44-full801-bed-initial-QA-and-PNG-join-proof.json'
put(proof,{'schema':'ds02.main.source202.actualF5.primary44.proof.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/name) for name in names],'source_before_after_SHA':before,'source_manifest_does_not_pin_content_main_exact_commit_blobs_do':True,'validator_stdout':rv.stdout,'copied_validator_stdout':cv.stdout,'builder_full_read_not_executed':True,'main44_full801_UID_N3_native_times_finite_render_and_bed_metadata_checked':True,'main44_genuine_initial_QA_receipt_completed0_placement_pass_generatedXML_and_native_initial_BI4_producer_join_verified':True,'published_contacts_SHA_verified':contacts_count,'navigation_keys_SHA_verified':nav_count,'legacy_atomic_publish_absences':pubabs,'render_H5_attestation_absences':habs,'source_normalization_limits_and_main_direct_QA_join':source_normalization_limits,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False,'new_case_credit':0,'Q_N':0,'Q_E':0})
product=O/'F5-FINAL48-ACTUAL44ACCEPTED-FOURPENDING-PRIMARY-BED-DELIVERY.json'
put(product,{'schema':'ds02.main.F5.actual-final48-primary-bed.44accepted-fourpending.v1','at_utc':now.isoformat(),'authoritative_checkpoint':ref(cpfile),'source202_catalog':ref(R/prefix/'metadata/f5-final48-primary-bed-delivery.json'),'main_independent_verification':ref(proof),'membership':mem,'accepted44_actual_primary_bed_rows':products,'pending4_registered_physical_cases':[{'physical_case_id':r['physical_case_id'],'case_id':r['case_id'],'accepted_decision':None,'personal_visual_review_complete':False,'case_credit':0,'readiness_is_historical_not_current_live_assertion':True,'source202_pending_row_preserved':next(s for s in sc['pending_products'] if s['physical_case_id']==r['physical_case_id'])} for r in pending],'source202_runtime_snapshots_historical_not_latest':True,'current_original1189_completed_own_QI_pending_personal_review':ref(root(1434)/'actual1189-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json'),'delivery_complete':False,'accepted44_primary_bindings_complete':True,'legacy_publication_absences_and_source_field_limits_preserved':True,'new_case_credit':0,'Q_N':0,'Q_E':0,'scientific_payload_IO':False})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);newcp=copy.deepcopy(cp)
newcp.update(checkpoint=324,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(ct),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: lastF2 accepted331/F2final48; F5 actual44 primary/bed product independently joined801frames, genuine initialQA and1496contacts396navigation; pending4 remain unaccepted.',authorized_work_state='Active331/336 remaining5. F2final48 product delegated226; F3 last1101 queued; F5 last4 retain registered renders and personal review dependencies.')
newcp['actual_progress']['F5_current44_actual_primary_bed_delivery']=ref(product);newcp['next_executable_tasks'].insert(0,'Integrate F2 fresh226 final48 actual primary; after F5 actual1189 fresh192 personal acceptance extend F5 primary45; remaining registered1184/1175/1149 and F3 1101 need natural completion and review.')
put(np,newcp);idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0);idx['F5_current44_actual_primary_bed_delivery']=ref(product)
put(O/'full336-current331-actual-final48-delivery-progress-index.json',idx);(O/'integration-source.py').write_bytes(Path(__file__).read_bytes())
(O/'README.md').write_text('F5 当前44例实际801帧动态主文件与床面诊断交付。逐例核对UID/N3/原生时间/有限状态/完整床面序列、真实初态QA与GenCase和初始BI4生产者凭证；核对1496张动画总览和396张导航关键帧SHA。保留四例legacy原子发布缺失、各原始scope角色与数值精度负证据。其余四例尚未视觉验收；本次不新增案例或个人视觉检查。视觉检查通过、数值精度未验收。\n')
paths=names+[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: join actual F5 primary44 full801 bed and genuine initial QA preserving legacy publication limits','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':324,'accepted':331,'F5_actual_primary':44,'contacts':contacts_count,'navigation':nav_count,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()}))
