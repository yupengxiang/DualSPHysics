from pathlib import Path
import json,hashlib,subprocess,importlib.util,copy,datetime,collections,os,xml.etree.ElementTree as ET
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');W=Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics');H=R/'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'))
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 p=Path(p);assert p.suffix in {'.json','.py','.md','.xml','.xmf'};return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def put(p,j):
 with Path(p).open('x') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
commit='b0870178c9fcda66445a718c0ccde7fee6010912'
prefix=Path('lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_197_f6_assigned_f2_final48_gate_repair_v2');P=W/prefix
names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',str(prefix)],cwd=W,text=True).splitlines();assert len(names)==7
blobs={n:subprocess.check_output(['git','show',f'{commit}:{n}'],cwd=W) for n in names}
for n,b in blobs.items():assert (W/n).read_bytes()==b and (not (R/n).exists() or (R/n).read_bytes()==b)
before={n:sha(W/n) for n in names};manifest=load(P/'package-manifest.json')
assert {e['path'] for e in manifest['files']}=={str(Path(n).relative_to(prefix)) for n in names if not n.endswith('package-manifest.json')}
for e in manifest['files']:assert sha(P/e['path'])==e['sha256']
contract=load(P/'metadata/input-contract.json');inp={e['role']:Path(e['path']) for e in contract['inputs']}
argv=['--checkpoint',str(inp['checkpoint']),'--current-index',str(inp['current_index']),'--membership',str(inp['fixed_membership']),'--legacy-catalog',str(inp['legacy_catalog_and_root1330_corrections'])]
rv=subprocess.run(['python3','-B',str(P/'scripts/validate_fresh197.py'),*argv,'--package-dir',str(P)],capture_output=True,text=True);assert rv.returncode==0,(rv.stdout,rv.stderr)
assert before=={n:sha(W/n) for n in names};validation=json.loads(rv.stdout);assert validation['status']=='PASS' and all(validation['negative_contract_tests'].values())
spec=importlib.util.spec_from_file_location('main197_audit',P/'scripts/build_fresh197.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
packaged=load(P/'metadata/current-readiness/fresh197-readiness.json');ready=next(x for x in packaged['accepted_ref_audit'] if x['primary_ref_completeness']['complete_for_final_primary_delivery'])
decision=load(ready['accepted_decision']['path']);cid=decision['case_id'];pid=decision['physical_case_id'];visual=copy.deepcopy(ready)
baseline=b._primary_completeness(visual,cid,pid);assert baseline['complete_for_final_primary_delivery']
toy=copy.deepcopy(ready);toy['contact_png_refs']=[copy.deepcopy(toy['contact_png_refs'][0]) for _ in range(17)];toy['key_png_refs']=[copy.deepcopy(toy['key_png_refs'][0]) for _ in range(9)]
duplicate=b._primary_completeness(toy,cid,pid);assert duplicate['complete_for_final_primary_delivery']
rec_ref=ready['actual_render_receipt'];actual=load(rec_ref['path']);changed=copy.deepcopy(actual);changed['input_hashes_after_run']={k:'0'*64 for k in changed['input_hashes_after_run']};assert changed['input_hashes_at_launch']!=changed['input_hashes_after_run']
oldjson=b._json_object
def mismatch_ref(refval,role):
 if isinstance(refval,dict) and refval.get('path')==rec_ref['path']:return copy.deepcopy(changed),None
 return oldjson(refval,role)
b._json_object=mismatch_ref
try:runtime=b._execution_receipt_certificate(rec_ref,cid,pid,'actual_render_receipt_digest_mismatch_component_test')
finally:b._json_object=oldjson
assert runtime['verified']
qa_refs=ready['initial_qa_or_audit_refs'];qa_gate=b._qa_certificate(qa_refs,cid,pid);assert qa_gate['verified'];qa_report=next(e for e in qa_refs if load(e['path']).get('schema')!='ds02.execution-receipt.v1');qa_obj=load(qa_report['path']);wrongqa=copy.deepcopy(qa_obj)
for k in ('prepared_evidence','gencase_receipt','xml_contract'):wrongqa[k]={'path':'/nonexistent/source197-main-component-wrong-input-scope/'+k+'.json','sha256':'0'*64}
def wrong_qa_ref(refval,role):
 if isinstance(refval,dict) and refval.get('path')==qa_report['path']:return copy.deepcopy(wrongqa),None
 return oldjson(refval,role)
b._json_object=wrong_qa_ref
try:qa_mismatch=b._qa_certificate(qa_refs,cid,pid)
finally:b._json_object=oldjson
assert qa_mismatch['verified']
xml_ref=ready['actual_xmf_xml'];parsed=ET.parse(xml_ref['path']);tampered=copy.deepcopy(parsed)
for grid in tampered.findall('.//Grid[@GridType="Uniform"]'):grid.find('Time').set('Value','nan')
oldparse=b.ET.parse;b.ET.parse=lambda p:tampered if str(p)==xml_ref['path'] else oldparse(p)
try:xml_nan=b._xml_certificate(xml_ref,cid,baseline['runtime_gate']['expected_particles_from_manifest'],baseline['runtime_gate']['render_report']['actual_times'])
finally:b.ET.parse=oldparse
assert xml_nan['verified']
assert before=={n:sha(W/n) for n in names}
cpfile=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_308.json';cp=load(cpfile);assert cp['checkpoint']==308 and cp['stage1_visual_accepted_complete_independent_cases']==len(cp['accepted_decisions'])==sum(cp['accepted_per_family'].values())==324
ip=root(1414)/'full336-current324-actual-final48-delivery-progress-index.json';idx=load(ip);assert idx['source_authoritative_checkpoint']==ref(cpfile)
O=H/'root_stage1_source197_F2_current46_readiness_actual_duplicate_PNG_runtime_digest_QA_scope_NaN_time_gate_defects_bounded_manual_final_primary_1416';np=H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_309.json';assert not O.exists() and not np.exists();O.mkdir()
for n,bytes_ in blobs.items():p=R/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes_)
curargv=['--checkpoint',str(cpfile),'--current-index',str(ip),'--membership',str(inp['fixed_membership']),'--legacy-catalog',str(inp['legacy_catalog_and_root1330_corrections'])]
mainout=O/'main-current46-readiness';br=subprocess.run(['python3','-B',str(R/prefix/'scripts/build_fresh197.py'),*curargv,'--output-dir',str(mainout)],capture_output=True,text=True);assert br.returncode==0,(br.stdout,br.stderr)
cv=subprocess.run(['python3','-B',str(R/prefix/'scripts/validate_fresh197.py'),*curargv,'--package-dir',str(R/prefix)],capture_output=True,text=True);assert cv.returncode==0,(cv.stdout,cv.stderr)
assert all((W/n).read_bytes()==bytes_ and (R/n).read_bytes()==bytes_ for n,bytes_ in blobs.items())
current=load(mainout/'fresh197-readiness.json');assert current['observed_counts']=={'registered_final48':48,'accepted_visual':46,'pending_visual':2} and current['complete_final48_emitted'] is False and not (mainout/'F2-FINAL48-COMPLETE-PRIMARY-DELIVERY.json').exists()
defects=[
 {'issue':'runtime digest snapshots presence does not prove equality or producer/consumer join','lines':[2156,2185,2191],'observed_component_false_positive':runtime['verified'],'actual_request_after_values_mutated_only_in_memory':True},
 {'issue':'exact17/9 cardinality allows seventeen repeats of one contact and nine repeats of one key','lines':[2523,2538,2544],'observed_component_false_positive':duplicate['complete_for_final_primary_delivery'],'missing_publish_report_membership_frame_indices_unique_paths_SHA_and_actual_personal_review_time_join':True},
 {'issue':'QA report paths counted without checking direct scope digests or join to genuine QA receipt and typed GenCase','lines':[2391,2426,2445],'observed_component_false_positive':qa_mismatch['verified'],'nonexistent_report_scope_paths_mutated_only_in_memory':True},
 {'issue':'XML comparison abs(nan-real)>1e-9 evaluates false and missing explicit finite check allows all401 time values nan','lines':[1040,1075,1107],'observed_component_false_positive':xml_nan['verified'],'actual_XML_parsed_then_mutated_only_in_memory':True},
 {'issue':'typed gate checks ledger presence and partvtk all_passed rather than per-frame type/Mk identity checks and exclusion accounting','lines':[2323,2345,2378]},
 {'issue':'typed source-provenance GenCase/XML/native selected refs not joined to report output and native input digests','lines':[2454,2472]},
 {'issue':'manifest frame/particle/dimension assertions omit actual time-vector and H5 position velocity tensor checks and producer report digest join','lines':[2299,2317]},
 {'issue':'genuine historical schemas and decision evidence layouts are incompletely resolved; 45accepted rows flagged despite prior main case QI and visual closure','lines':[2056,2138]},
 {'issue':'existing empty output directory can be reused, despite broader instruction requiring fresh immutable output','lines':[1737,1745]}]
proof=O/'source197-byte-exact-main-current46-readiness-and-remaining-final-gate-audit.json';now=datetime.datetime.now(datetime.timezone.utc)
put(proof,{'schema':'ds02.main.source197.bounded-final-primary-gate-audit.v1','at_utc':now.isoformat(),'source_commit':commit,'source_files':[ref(R/n) for n in names],'source_before_after_SHA':before,'read_review_scope':'Full prior source195 builder independently read at Root1393; all byte differences through source197 appended gates read, truncated middle reacquired; final source197 validator fully read before any import/run.','source_fixed_readonly_validator':validation,'main_current_readonly_validator':json.loads(cv.stdout),'main_current_readiness':ref(mainout/'fresh197-readiness.json'),'actual_current_boundary':current['observed_counts'],'accepted_rows_with_ref_gaps':current['accepted_rows_with_ref_gaps'],'source_current_same_F2_counts_but_original_global_snapshot_preserved':True,'actual_component_test_primary_case_id':cid,'actual_component_test_primary_physical_id':pid,'actual_positive_primary_baseline_verified':True,'remaining_gate_defects':defects,'component_tests_are_only_in_memory_not_mutation_of_campaign_inputs_or_catalog':True,'package_toy_negative_tests_do_not_prove_missing_positive_joins':True,'adoption_scope':'readiness_only_not_final48_certification','bounded_repair_exhausted_no_third_tool_repair':True,'next_final_primary_path':'main assemble authoritative actual QI/QA/runtime-original-vs-recovery/typed-native-XMF scope and published unique PNG/time evidence per physical case; completed child tool immutable','actual_accepted_cases_are_not_revoked_by_builder_lookup_gaps':True,'originalP03typed135_running_missing_returncode_and_recoveryXMF197_preserved':True,'Root1330_four_same_attempt_request_to_receipt_corrections_preserved':True,'case_credit':0,'scientific_payload_IO':False,'PNG_payload_IO':False,'new_scientific_or_render_jobs':0})
raw=(D/'runtime/resource-ledger.json').read_bytes();ld=json.loads(raw);counts=collections.Counter(e['kind'] for e in ld['attempts']);gpu=sum(e.get('gpu_seconds',0) for e in ld['charges'])/3600;cpu=sum(e.get('cpu_core_seconds',0) for e in ld['charges'])/3600;vf=os.statvfs('/home/jade');free=vf.f_bavail*vf.f_frsize/2**30
assert free>=500 and gpu<=512 and cpu<=3840 and counts['qualification']<=1024 and counts['production']<=720 and now<datetime.datetime.fromisoformat(cp['deadline_utc'])
snap=O/'ledger-immutable-snapshot.json';snap.write_bytes(raw);new=copy.deepcopy(cp)
new.update(checkpoint=309,at_utc=now.isoformat(),predecessor=str(cpfile),predecessor_sha256=sha(cpfile),new_accepted_decisions=[],home_free_gib=free,ledger_sha256_at_checkpoint=hashlib.sha256(raw).hexdigest(),ledger_immutable_snapshot=ref(snap),active_reservations=ld['reservations'],attempt_counts=dict(counts),gpu_hours_charged=gpu,cpu_core_hours_charged=cpu,previous_goal_turn_classification='PROGRESS: preceding turn source185/220 actualpersonal cases accepted323/324; original1129 own1411 completed and next1136/1139 durableQI1412/1415 prepared. This turn source197 second boundedrepair fully reviewed with exact sourcecopy/readonly validation/current46 readiness and four actual component falsepositives. Finalprimary certification will use separate actual authoritative joins; no third toolrepair/no false casecredit.',authorized_work_state='Active324/336 remaining12. Production186 actual1129 personal44PNG active. Fresh199 personalF5original1136 after futureown1412; fresh221 personalF5original1139 after futureown1415. Sameactual1136/1139 originalworkers currently live. Source197 and218 audited readiness-only/manualprimary; source196 pending bounded main audit. All Q-N/Q-E/precision limits preserved.')
new['actual_progress']['source197_F2_current46_bounded_final_gate_audit']=ref(proof)
new['next_executable_tasks'].insert(0,'Adopt completed186 personalF3actual1129 once; observe sameoriginal1136/1139 actualhandles and execute preparedown1412/1415 once after0/pub, then personal199/221. Audit196 F3 bounded tool once and assemble finalprimary using actual case evidence; do not start third197/218 repair cycle.')
put(np,new);idx.update(at_utc=now.isoformat(),source_authoritative_checkpoint=ref(np),previous_index_preserved=ref(ip),new_case_credit=0,source197_F2_current46_bounded_final_gate_audit=ref(proof));assert len(idx['cases'])==336 and sum(bool(z.get('accepted_decision')) for z in idx['cases'])==324
put(O/'full336-current324-actual-final48-delivery-progress-index.json',idx);(O/'audit-source.py').write_bytes(Path(__file__).read_bytes())
paths=names+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]+[str(np.relative_to(R))];subprocess.run(['git','add','--',*paths],cwd=R,check=True);subprocess.run(['git','commit','-q','-m','DS02: audit bounded F2 source197 readiness preserving actual final primary joins','--',*paths],cwd=R,check=True)
print(json.dumps({'checkpoint':309,'accepted':324,'source197_adoption':'readiness_only','actual_false_positives':4,'readiness_counts':current['observed_counts'],'accepted_gaps':len(current['accepted_rows_with_ref_gaps']),'proof':ref(proof),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()},ensure_ascii=False))
