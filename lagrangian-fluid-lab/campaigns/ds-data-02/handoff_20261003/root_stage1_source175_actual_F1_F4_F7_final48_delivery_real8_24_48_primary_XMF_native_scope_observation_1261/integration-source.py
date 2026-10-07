from pathlib import Path
import json,hashlib,subprocess,copy,datetime,os,collections
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
load=lambda p:json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix.lower() in {'.json','.jsonl','.py','.md','.xml','.xmf','.txt','.log','.png'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
root=lambda n:next(H.glob(f'root*_{n}'))
commit='8ee21b13e32e86e9b0474eead8edcb659a72acba';prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_175_f1_f4_f7_final48_delivery_manifest_v1');names=['README.md','build_final48_delivery.py','final48-delivery-roster.json','validate_final48_delivery.py'];v=load('/tmp/ds02-source175-main-readonly-validation.json');assert v['source_commit']==commit and v['validator_returncode']==0 and v['source_bytes_unchanged'] and json.loads(v['stdout'])['status']=='PASS'
# Compare every selected immutable source BEFORE any adoption write.
blobs={}
for n in names:
 rel=prefix/n;b=subprocess.check_output(['git','show',f'{commit}:{rel}'],cwd=W);assert (W/rel).read_bytes()==b and hashlib.sha256(b).hexdigest()==v['source_file_hashes_before_and_after'][str(rel)];assert not (R/rel).exists() or (R/rel).read_bytes()==b;blobs[rel]=b
source=load(W/prefix/'final48-delivery-roster.json');assert source['schema']=='ds02.f6.cross-family-final48-delivery-roster.v1'
for e in source['authority'].values():assert sha(e['path'])==e['sha256']
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_221.json';cp=load(cpfile);assert cp['checkpoint']==221 and cp['stage1_visual_accepted_complete_independent_cases']==282 and len(cp['accepted_decisions'])==282 and sum(cp['accepted_per_family'].values())==282
accepted={}
for p in cp['accepted_decisions']:
 z=load(p);pid=z.get('physical_case_id',z['case_id']);assert pid not in accepted;accepted[pid]=(z,p)
frozen=load(source['authority']['root1093_frozen8']['path']);s24a=load(source['authority']['root1232_f1_f7_first24']['path']);s24b=load(source['authority']['root1238_f4_first24']['path'])
print('FIRST24_KEYS',list(s24a['families']['F1']))
family_outputs={};native_all=[];unresolved_before=resolved_missing=0;auxiliary=[];nonterminal_cases=[]
for fam in ('F1','F4','F7'):
 f=source['families'][fam];assert cp['accepted_per_family'][fam]==48
 ids=[r['physical_case_id'] for r in f['cases']];assert ids==f['final48_physical_case_ids'] and len(ids)==len(set(ids))==48
 own=[z.get('physical_case_id',z['case_id']) for z,p in accepted.values() if z['family_id']==fam];assert ids==own
 frozen_ids=[]
 for e in frozen['cases_by_family'][fam]:
  assert sha(e['path'])==e['sha256'];z=load(e['path']);frozen_ids.append(z.get('physical_case_id',z['case_id']))
 assert f['first8_physical_case_ids']==frozen_ids
 if fam=='F4':first24=[r['physical_case_id'] for r in s24b['families'][fam]['rows_actual_source_order']]
 else:
  sf=s24a['families'][fam];rows=sf.get('actual_first24',sf.get('rows_actual_source_order'));assert rows is not None;first24=[r['physical_case_id'] for r in rows]
 assert f['first24_physical_case_ids']==first24 and len(first24)==len(set(first24))==24 and set(frozen_ids)<set(first24)<set(ids)
 outrows=[]
 for row in f['cases']:
  pid=row['physical_case_id'];z,p=accepted[pid];assert z['family_id']==fam and row['accepted_decision']['path']==p and row['accepted_decision']['sha256']==sha(p);assert not row['delivery_status']['q_n'] and not row['delivery_status']['q_e'] and row['delivery_status']['case_credit']==0
  prod=row['product_metadata'];candidates=[]
  for e in prod['xmf']:
   if Path(e['path']).name!='manifest.json':continue
   assert sha(e['path'])==e['sha256'];m=load(e['path']);xp=m.get('xdmf');xm=[x for x in prod['xmf'] if x['path']==xp];reports=[]
   for r in prod['render']:
    if Path(r['path']).suffix!='.json':continue
    rz=load(r['path'])
    if rz.get('xdmf')==xp and rz.get('manifest_sha256')==e['sha256']:
     assert sha(r['path'])==r['sha256'];reports.append(r)
   if xm and reports and f'/families/{fam}/' in xp:
    assert sha(xp)==xm[0]['sha256']==m['xdmf_sha256'];assert m.get('case_id')==row['case_id'],(pid,'manifest case_id',m.get('case_id'),row['case_id']);assert m.get('physical_case_id',pid)==pid or any(load(ne['path']).get('request',{}).get('case_id')==row['case_id'] and load(ne['path']).get('request',{}).get('physical_case_id')==m.get('physical_case_id') and load(ne['path']).get('request',{}).get('physical_condition_sha256')==z.get('physical_condition_sha256') for ne in prod['native'] if Path(ne['path']).suffix=='.json'),(pid,'unbound manifest physical label',m.get('physical_case_id'));candidates.append((e,xm[0],reports,m))
  assert len(candidates)==1,(pid,len(candidates));me,xe,reports,m=candidates[0]
  other=[e for e in prod['xmf'] if e['path'] not in {me['path'],xe['path']} and (Path(e['path']).suffix=='.xmf' or Path(e['path']).name=='manifest.json')]
  if other:auxiliary.append({'family_id':fam,'physical_case_id':pid,'primary_xmf':xe,'auxiliary_xmf_metadata_context':other,'auxiliary_context_is_not_case_entrypoint_or_credit':True})
  observations=[]
  for e in prod['native']:
   if Path(e['path']).suffix!='.json':continue
   nz=load(e['path']);q=nz.get('request',{})
   if not q:continue
   assert sha(e['path'])==e['sha256'];observations.append({'receipt':e,'request_case_id':q.get('case_id'),'request_physical_case_id':q.get('physical_case_id'),'request_physical_case_id_field_present':'physical_case_id' in q,'request_condition_field_present':'physical_condition_sha256' in q,'request_condition_sha256':q.get('physical_condition_sha256'),'status':nz.get('status'),'returncode':nz.get('returncode'),'terminal_completed0_observed':nz.get('status')=='completed' and nz.get('returncode')==0,'matches_own_case_id':q.get('case_id')==row['case_id']})
  ownobs=[o for o in observations if o['matches_own_case_id']];assert ownobs,(pid,'no own native receipt');hs={o['request_condition_sha256'] for o in ownobs if o['request_condition_field_present']};assert len(hs)<=1,(pid,'native condition conflicts',hs);assert all(o['request_physical_case_id'] in (None,pid,row['case_id'],m.get('physical_case_id')) for o in ownobs),(pid,'native label mismatch',[(o['request_physical_case_id'],o['receipt']['path']) for o in ownobs],m.get('physical_case_id'))
  present=bool(hs);actual=next(iter(hs)) if present else None;oldscope=row['role_aware_native_registration']['native_request_scope'];oldsha=oldscope.get('sha256');assert oldsha is None or oldsha==actual
  if oldsha is None:
   unresolved_before+=1
   if present:resolved_missing+=1
  no={'family_id':fam,'physical_case_id':pid,'case_id':row['case_id'],'historical_source_scope_preserved':oldscope,'actual_native_request_field_present':present,'actual_native_request_condition_sha256':actual,'actual_condition_role':'observed embedded native receipt request; no numeric certificate or status promotion','accepted_top_condition_sha256':row['role_aware_native_registration']['accepted_decision_top_condition_sha256'],'accepted_top_equals_actual_native':None if not present else row['role_aware_native_registration']['accepted_decision_top_condition_sha256']==actual,'observations':observations,'true_absence_not_filled_from_owner_typed_XMF':not present,'new_case_credit':0};native_all.append(no)
  bad=prod['receipt_roles']['nonterminal_or_nonzero_preserved']
  if bad:nonterminal_cases.append({'family_id':fam,'physical_case_id':pid,'original_nonterminal_or_nonzero_metadata':bad,'recovery_evidence':prod['receipt_roles']['actual_completed_or_recovery_evidence_receipts'],'original_status_never_promoted':True})
  outrows.append({'family_id':fam,'case_id':row['case_id'],'physical_case_id':pid,'membership_role':row['membership_role'],'accepted_visual_decision':row['accepted_decision'],'original_roster_row_identity':{'source_roster_path':str(R/prefix/'final48-delivery-roster.json'),'family_id':fam,'physical_case_id':pid},'primary_paraview_xmf':xe,'primary_xmf_manifest':me,'primary_manifest_physical_case_id_field_present':'physical_case_id' in m,'primary_manifest_physical_case_id':m.get('physical_case_id'),'accepted_physical_case_id_equals_manifest':m.get('physical_case_id',pid)==pid,'original_accepted_alias_provenance':z.get('physical_scope_provenance'),'primary_full_render_reports':reports,'full_frames_producer_attested':m['frames'],'particle_count_producer_attested':m['particles'],'actual_native_condition_observation':no,'contact_sheets':prod['png']['contact_sheets'],'key_frames':prod['png']['key_frames'],'auxiliary_xmf_context':other,'all_original_other_product_and_receipt_roles_preserved_in_immutable_source_roster':True,'precision_status':'视觉检查通过、数值精度未验收','Q_N':False,'Q_E':False,'new_case_credit':0})
 family_outputs[fam]={'schema':'ds02.stage1.actual-family-final48-delivery.v1','family_id':fam,'counts':{'first8':8,'first24':24,'final48':48},'first8_physical_case_ids':frozen_ids,'first24_physical_case_ids':first24,'final48_physical_case_ids':ids,'strict_actual_subsets_verified':True,'stable_acceptance_checkpoint':ref(cpfile),'source_commit':commit,'source_roster':{'path':str(R/prefix/'final48-delivery-roster.json'),'sha256':sha(W/prefix/'final48-delivery-roster.json')},'cases':outrows,'new_case_credit':0,'Q_N':False,'Q_E':False,'precision_status':'视觉检查通过、数值精度未验收','main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False}
assert len(native_all)==144 and unresolved_before==63 and resolved_missing==60 and sum(not o['actual_native_request_field_present'] for o in native_all)==3
assert len(auxiliary)==1 and len(nonterminal_cases)==7,(len(auxiliary),len(nonterminal_cases))
for key,path in [('runtime_v2_sha256',L/'scripts/ds_data02_runtime_v2.py'),('strict_dispatch_sha256',L/'scripts/ds_data02_strict_dispatch_v1.py'),('Root142_launch_sha256',root(142)/'launch.py')]:assert sha(path)==cp['unmodified_guards'][key]
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(d['kind'] for d in ld['attempts']);gpu=sum(d.get('gpu_seconds',0) for d in ld['charges'])/3600;cpu=sum(d.get('cpu_core_seconds',0) for d in ld['charges'])/3600;sv=os.statvfs('/home/jade');free=sv.f_bavail*sv.f_frsize/2**30;assert gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and free>=500
O=H/'root_stage1_source175_actual_F1_F4_F7_final48_delivery_real8_24_48_primary_XMF_native_scope_observation_1261';nextcp=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_222.json';assert not O.exists() and not nextcp.exists()
# No writes above this line; all adoption dependencies checked.
O.mkdir();adopted=[]
for rel,b in blobs.items():
 p=R/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);adopted.append(ref(p))
(O/'source175-readonly-validation-observation.json').write_bytes(Path('/tmp/ds02-source175-main-readonly-validation.json').read_bytes());families={}
for fam,f in family_outputs.items():
 p=O/f'{fam}-ACTUAL_FINAL48_DELIVERY_8_24_48.json';put(p,f);families[fam]=ref(p)
np=O/'native-request-condition-observations-144-historical-unresolved-vs-actual-absence.json';put(np,{'schema':'ds02.native-request-metadata-role-observation.v1','rows':native_all,'actual_native_request_field_present_count':141,'true_actual_field_absence_count':3,'old_unresolved_null_count':63,'newly_directly_resolved_present_count':60,'all_original_source_nulls_preserved':True,'original_receipt_statuses_never_promoted':True,'scientific_payload_IO':False,'Q_N':False,'Q_E':False,'new_case_credit':0})
auxp=O/'primary-XMF-vs-auxiliary-cross-family-context.json';put(auxp,{'all144_primary_XMF_bound_to_actual_full_render_report':True,'cross_family_auxiliary_rows':auxiliary,'cross_family_auxiliary_context_not_case_entrypoint':True,'source_original_roster_bytes_preserved':True})
rp=O/'original-seven-nonterminal-or-nonzero-receipts-and-separate-recovery-preserved.json';put(rp,{'cases':nonterminal_cases,'original_receipts_not_reclassified':True})
manifest=O/'MAIN_ACTUAL_F1_F4_F7_FINAL48_DELIVERY144.json';put(manifest,{'schema':'ds02.actual-three-family-final48-delivery.v1','at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'families':families,'family_counts':{'F1':48,'F4':48,'F7':48},'independent_cases_already_accepted':144,'real_first8_subset_first24_subset_final48':True,'stable_predecessor_checkpoint':ref(cpfile),'source_commit':commit,'adopted_source_files':adopted,'source_validator_observation':ref(O/'source175-readonly-validation-observation.json'),'native_metadata_role_observations':ref(np),'primary_XMF_auxiliary_role_closure':ref(auxp),'original_failed_or_nonterminal_recovery_roles':ref(rp),'new_case_credit':0,'new_acceptance':False,'precision_status':'视觉检查通过、数值精度未验收','Q_N':False,'Q_E':False,'main_scientific_payload_IO':False,'main_personally_viewed_PNGs':False})
lines=['# F1 / F4 / F7：各48例动态数据交付','', '144例均已有视觉验收；数值精度未验收，Q-N/Q-E未授予。8例、24例分别是同族最终48例的实际子集。以下链接为与完整渲染报告绑定的本案例XMF入口；原始失败记录、恢复证据和其他上下文保留在清单中。','']
for fam,f in family_outputs.items():
 lines.extend([f'## {fam}', ''])
 for row in f['cases']:lines.append(f"- [{row['physical_case_id']}]({row['primary_paraview_xmf']['path']}) — {row['full_frames_producer_attested']}帧，{row['membership_role']}")
 lines.append('')
(O/'README.md').write_text('\n'.join(lines)+'\n')
ledger=O/'ledger-immutable-snapshot.json';ledger.write_bytes(raw);newcp=copy.deepcopy(cp);now=datetime.datetime.now(datetime.timezone.utc).isoformat();newcp.update(checkpoint=222,at_utc=now,predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(ledger),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: formally delivered actual F1/F4/F7 48 each with strict real8/24/48 subsets; all144 own primary XMF tied to render report;60 historical unresolved native condition fields directly resolved,3 actual absences preserved;7 original nonterminal/nonzero receipts distinct from recovery. Actual F5 M105T090 full801 QI completed in Root1263.',authorized_work_state='Active282/336; F1/F4/F7 actualfinal48 delivery registered, no new case credit. F3actual1047 and F5actual1182 completed0 with main QI; child personal visual review pending. Original render queue continues; Home floor500GiB protected.')
newcp['actual_progress']['F1_F4_F7_actual_final48_delivery144']=ref(manifest);newcp['actual_progress']['F5_actual1182_full801_previsual_QI']=ref(root(1263)/'actual1182-full801-independent-QI-UID-N3-bed-scope-previsual-proof.json');newcp['next_executable_tasks']=['Adopt fresh161 actualF3 P1200AY0320 personal35contacts9keys with Root1262 full836 QI.','Adopt fresh199 actualF5 M105T090 personal34contacts9keys with Root1263 full801 QI.','Continue actualF2 RX061ROT075 original1142 through same handle; fresh176 personal17contacts9keys after atomic publication and main own full401 QI.','Continue same original render controllers for remaining54 cases and finalF6original951, preserving globalcap2 and CPU24 reservations.'];newcp['source_agents']['f6_endpoint_initial_qa']='fresh175 exact adopted final48delivery; fresh176 actualF2RX061ROT075 personal17contacts9keys';put(nextcp,newcp)
indexp=root(1260)/'full336-current282-actual-wrapper-contract-role-aware-registration-progress-index.json';idx=load(indexp);idx['previous_index_preserved']=ref(indexp);idx['source_authoritative_checkpoint']=ref(nextcp);idx['actual_F1_F4_F7_final48_delivery']=ref(manifest);idx['at_utc']=now;idx['new_case_credit']=0;put(O/'full336-current282-actual-final48-delivery-progress-index.json',idx)
(O/'integration-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir() if p.is_file()]+[str(p.relative_to(R)) for p in (R/prefix).iterdir() if p.is_file()]+[str(nextcp.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','ds02: deliver actual F1 F4 F7 final48 with native and primary XMF roles','--',*paths],cwd=R,check=True);print(json.dumps({'status':'PASS','manifest':ref(manifest),'checkpoint':222,'accepted':282,'family_deliveries':{'F1':48,'F4':48,'F7':48},'native_present':141,'native_absent':3,'newly_resolved':60,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
