from pathlib import Path
import json,hashlib,datetime,copy,subprocess
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.xml','.xmf','.md'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
# Both preflights are the fully read previous main checks, adapted only to actual case metadata.
preflights={};contexts={}
for n in (1129,1136):
 p=Path(f'/tmp/ds02-next{n}-upstream-preflight1410.py');code=p.read_text();preflights[n]=code;g={'__file__':str(p)};exec(compile(code,str(p),'exec'),g);contexts[n]=g
a=contexts[1129];b=contexts[1136];cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_305.json';cp=load(cpfile)
assert a['cp']==b['cp']==cp and cp['stage1_visual_accepted_complete_independent_cases']==323
O=H/'root_stage1_current323_nextF3_original1129_XMFplan_present_nextF5_original1136_canonical_SourceDef_trueQA_durable1411_1412_1410'
np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_306.json';assert not O.exists() and not np.exists() and not list(H.glob('root*_1411')) and not list(H.glob('root*_1412'));O.mkdir()
entries={}
for n,out,family,frames in [(1129,1411,'F3',836),(1136,1412,'F5',801)]:
 src=Path(f'/tmp/ds02-{family}-original{n}-full{frames}-own-QI{out}.py');entry=O/f'after_original{n}_terminal_full{frames}_own_QI.py';entry.write_bytes(src.read_bytes());compile(entry.read_text(),str(entry),'exec');entries[n]=entry
 for_pre=O/f'original{n}-upstream-preflight-source.py';for_pre.write_text(preflights[n])
proof=O/'next1129-1136-actual-fulltime-UID-N3-native-XMF-plan-role-trueQA-and-durable-QI-readiness.json'
front=json.loads(Path('/tmp/ds02-current323-remaining-original-render-observations.json').read_text())
put(proof,{'schema':'ds02.current323.next-two-original-durable-QI.v1','at_utc':b['now'].isoformat(),'case_credit':0,'scientific_payload_IO':False,'PNG_payload_IO':False,'new_jobs':0,'frontier_observation_snapshot':front,
 'F3_original1129':{'case_id':a['cid'],'physical_case_id':a['pid'],'prior_previsual_review':ref(a['pre']),'completed_upstream_receipts':a['s'],'typed_XMF_refs':{k:a['z'][k] for k in ['actual_typed_report','actual_XMF_manifest','actual_XMF_XML']},'genuine_source_parentQA_and_GenCase_refs':a['refs'],'full836_UID_N3_XMF_exact_actual_time_sequence_verified':True,'true_passing_parent_initial_QA_source704_GenCase_initial_scope_join_verified':True,'native_changed_forcing_initial_input_launch_after_digests_unchanged':True,'canonical_native_typed_XMF':a['canonical'],'actual_native_XMF_plan_namespaces':a['mask'],'native_both_plan_absent_XMF_condition_plan_present_physical_plan_absent':True,'actual_time_window_s':[a['times'][0],a['times'][-1]],'same_original_worker_current_live':a['front'][0],'personal_keyframe_indices':a['w']['keyframe_indices'],'durable_entry':ref(entries[1129]),'command':['python3','-B',str(entries[1129]),'1129','1411'],'future_ownQI1411_UNEXECUTED_SHA_unknown':True},
 'F5_original1136':{'case_id':b['cid'],'physical_case_id':b['pid'],'upstream_primary_refs':b['refs'],'prior_previsual_review':ref(b['pre']),'canonical_native':b['canonical'],'typed_legacy':b['legacy'],'bed_SourceDef_FILE':b['source_def'],'source_plan_JSON_FILE':b['plan'],'actual_native_XMF_plan_field_namespaces':b['mask'],'native_and_XMF_physical_plan_canonical_not_SourceDef':True,'source_plan_JSON_launch_after_native_and_bed_verified':True,'genuine_GenCase_initialQA_completed0_basicplacement_and_generated_xml_scope_join_verified':True,'initialQA_precision_negative_retained':b['qa']['numerical_precision'],'full801_UID_type_N3_XMF_bed_exact_actual_times_and_bed_UID_footprint_bins_verified':True,'subDP_positive_depth_not_quantified':True,'actual_time_window_s':[b['times'][0],b['times'][-1]],'same_original_worker_current_live':b['obs'],'personal_keyframe_indices':b['w']['keyframe_indices'],'durable_entry':ref(entries[1136]),'command':['python3','-B',str(entries[1136]),'1136','1412'],'future_ownQI1412_UNEXECUTED_SHA_unknown':True}})
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(b['raw']);new=copy.deepcopy(cp)
new.update(checkpoint=306,at_utc=b['now'].isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=b['free'],ledger_sha256_at_checkpoint=hashlib.sha256(b['raw']).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=b['ld']['reservations'],attempt_counts=dict(b['ct']),gpu_hours_charged=b['gpu'],cpu_core_hours_charged=b['cpu'],previous_goal_turn_classification='PROGRESS: actual1162 full801 ownQI1404 completed; source185 actual1031 full836 personal44PNG joined and accepted323. Next two actual original1129 and1136 admitted same-live workers; fulltime typed UID/N3/XML exacttimes/trueQA/native-source-input-role and F5 bed checks now completed and durable own1411/1412 prepared.',authorized_work_state='Active323/336 remaining13. Fresh220 personalF5original1162 active after own1404. Fresh186 nextF3original1129 and fresh198 assignedF5original1136 metadata preflight waiting real completed/0 atomicpub and own1411/1412. Both original render workers confirmed live. Final F2 source197 and F3 source196 completed pending bounded main audit; F5 source218 readiness-only manualprimary path. No new native or render jobs.')
new['actual_progress']['next_original1129_1136_durable_fulltime_QI']=ref(proof)
new['source_agents'].update(f5_bed_recovery='fresh220 personal34contacts9keys active after actual1162 own1404',production_recovery='fresh186 original1129 metadata preflight then personal35contacts9 actual-navigation keys after own1411',f6_endpoint_initial_qa='fresh198 assignedF5original1136 metadata preflight then personal34contacts9keys after own1412; completed197 finaltool pending bounded audit')
new['next_executable_tasks'].insert(0,'Integrate completed220 personal43PNG; observe sameactual1129 PID714069/start214759956 and1136 PID724322/start214858903. After each true0/atomicpub execute durableown1411/1412 once then authorize respective186/198 personalreview. No duplicate renders; continue bounded196/197 audits and actualfinal48 manualprimary joins.')
assert len(new['accepted_decisions'])==sum(new['accepted_per_family'].values())==323;put(np,new)
ip=root(1409)/'full336-current323-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile)
for n,out,g in [(1129,1411,a),(1136,1412,b)]:
 row=next(z for z in idx['cases'] if z['physical_case_id']==g['pid']);assert not row.get('accepted_decision');row.update(current_same_original_live_previsual_preparation=ref(proof),future_independent_QI_root=out,case_credit=0,prior_controller_observations_are_historical_not_current=True)
idx.update(at_utc=b['now'].isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,next_original1129_1136_durable_fulltime_QI=ref(proof))
assert len(idx['cases'])==336 and sum(bool(z.get('accepted_decision')) for z in idx['cases'])==323;put(O/'full336-current323-actual-final48-delivery-progress-index.json',idx)
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes());paths=[str(p.relative_to(R)) for p in O.iterdir()]+[str(np.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: prepare original1129 and1136 fulltime QI preserving true native XMF plan roles','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':306,'accepted':323,'proof':ref(proof),'live_workers':[a['front'][0],b['obs']],'home_free_GiB':b['free'],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
