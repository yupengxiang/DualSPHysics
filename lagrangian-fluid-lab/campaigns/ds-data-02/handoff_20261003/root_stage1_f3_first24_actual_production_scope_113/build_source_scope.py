from pathlib import Path
import copy,json,hashlib,sys,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');LAB=R/'lagrangian-fluid-lab';H=LAB/'campaigns/ds-data-02/handoff_20261003'
infra=Path('/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003')
adapter=infra/'root_followup_055_stage1_production_adapter_v2'
source=infra/'root_followup_056_f3_stage1_production_authorization_v3'
sys.path[:0]=[str(adapter),str(LAB/'scripts')]
import ds_data02_stage1_production_v2 as auth
out=H/'root_stage1_f3_first24_actual_production_scope_113';assert not out.exists();out.mkdir();(out/'requests').mkdir()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
bind=lambda p:{'path':str(p),'sha256':sha(p)}
write=lambda p,v:p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
load=lambda p:json.loads(Path(p).read_text())
prep=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_FIRST24_SOURCE_PREPARATION/root-stage1-f3-first24-source-preparation-064')
assert load(prep/'execution-receipt.json')['status']=='completed'
index=load(prep/'prepared/fresh064-prepared-index.json');assert len(index['prepared_cases'])==16
manifest=load(source/'F3_FIRST8_V3_CASE_MANIFEST.json');domain=load(source/'F3_FIRST8_V3_PHYSICAL_DOMAIN.json')
registry=load(LAB/'campaigns/ds-data-02/APPROVED_VISUAL_SCOPES.json');entry=copy.deepcopy(next(x for x in registry['scopes'] if x['family_id']=='F3'))
oldrows=copy.deepcopy(manifest['cases']);template=next(x for x in oldrows if x.get('transverse_amplitude_m_s2')==.32)
scope='F3_STAGE1_FIRST24_AY0250_AY0750_VISUAL_V1'
newrows=[]
for order,p in enumerate(index['prepared_cases'],8):
 actual=load(p['prepared_input_report']['path']);row=copy.deepcopy(template)
 row.update(order=order,role=f'interior{order-7:02d}_first24_new',case_id=p['case_id'],physical_case_id=actual['physical_case_id'],transverse_amplitude_m_s2=p['transverse_amplitude_m_s2'],physical_condition_sha256=p['physical_condition_sha256'],split='first24_new_interior',source_owner=p['prepared_input_report'])
 row['parameter_tuple']['transverse_amplitude_m_s2']=p['transverse_amplitude_m_s2']
 row['motion'].update(transverse_amplitude_m_s2=p['transverse_amplitude_m_s2'],actual_forcing_sha256=p['forcing']['sha256'],output_sha256=p['forcing']['sha256'])
 row['actual_solver_command'][2]=p['prepared_prefix']
 row['prepared_input'].update(report=p['prepared_input_report'],forcing=p['forcing'],generated_xml=p['generated_xml'],initial_bi4=p['initial_bi4'],prepared_prefix=p['prepared_prefix'])
 row['exact_initial_clone_receipt']=bind(prep/'execution-receipt.json')
 row['clone_provenance']['first24_preparation_receipt']=bind(prep/'execution-receipt.json')
 inputs=[p['prepared_input_report'],p['forcing'],p['generated_xml'],p['initial_bi4'],row['exact_initial_clone_receipt']]
 evidence=out/'evidence'/p['case_id'];evidence.mkdir(parents=True)
 for key in ['initial_mass_discrepancy_report','physics_evidence','geometry_evidence','motion_evidence','no_overlap_finite_state_evidence']:
  e=load(template[key]['path']);e.update(case_id=row['case_id'],physical_case_id=row['physical_case_id'],physical_condition_sha256=row['physical_condition_sha256'])
  if 'status' in e:e['status']=e['status'].replace('strict012','strict112_actual_preparation064')
  if 'motion' in e:e['motion']=copy.deepcopy(row['motion'])
  if 'source_bindings' in e:e['source_bindings']['prepared_input_report']=p['prepared_input_report'];e['source_bindings']['first24_preparation_receipt']=bind(prep/'execution-receipt.json')
  e['inference_basis']='Metadata inference from actual byte-identical parent XML/BI4 and original native initial QA058. Forcing is actual newly generated. No new particle arrays or postrun states inferred.'
  file=evidence/(key+'.json');write(file,e);row[key]=bind(file);inputs.append(row[key])
 row['input_bindings']=inputs;newrows.append(row)
manifest['cases']=oldrows+newrows;domain['cases']=copy.deepcopy(manifest['cases'])
for doc in [manifest,domain]:doc.update(scope_id=scope,status='actual_prepared_first24_explicit_visual_domain_pending_case_acceptance',production_scope_approval=False)
manifest['first8_original_rows_preserved']=True;manifest['source_documents']['first24_actual_preparation_receipt']=bind(prep/'execution-receipt.json');manifest['source_documents']['first24_actual_prepared_index']=bind(prep/'prepared/fresh064-prepared-index.json')
write(out/'case-manifest.json',manifest);write(out/'physical-domain.json',domain)
decision=load(H/'root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json')
decision.update(scope_id=scope,at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),numerical_precision_status='not_accepted',membership_is_explicit=True,selected_case_ids=[r['case_id'] for r in newrows],prospective_execution_authorized=True)
original_observed=list(decision['observed_case_ids'])
decision['observed_case_ids']=original_observed
decision['prospective_case_ids']=[r['case_id'] for r in manifest['cases'] if r['case_id'] not in original_observed]
decision['source_observed_domain']=bind(H/'root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json')
decision['first24_actual_preparation']=bind(prep/'execution-receipt.json')
decision['domain_extension_basis']='Sixteen explicitly prepared amplitudes strictly inside the already Root-inspected .25..75 endpoints, unchanged genuine3D initial geometry/BI4, recipe/pitch/window, actual distinct frozen forcing hashes. Prospective complete runs authorized; case counts remain0 until each full saved visual review.'
decision['membership_semantics']='Observed lists retained original range-establishing mother/endpoints. Additional first8 visual progress is separately bound; only16 new conditions are selected for execution here.'
decision['additional_visual_progress']=[bind(H/d/'root-visual-decision.json') for d in ['root_stage1_f3_interior032_full836_visual_acceptance_097','root_stage1_f3_interior039_full836_visual_acceptance_104','root_stage1_f3_interior046_full836_visual_acceptance_108']]
write(out/'root-visual-domain-decision.json',decision)
entry.update(scope_id=scope,root_visual_domain_decision=bind(out/'root-visual-domain-decision.json'),case_manifest=bind(out/'case-manifest.json'),physical_domain=bind(out/'physical-domain.json'),selected_case_ids=[r['case_id'] for r in newrows])
entry['visual_evidence']['prospective']=[{'case_ids':entry['selected_case_ids'],'status':'pending actual complete solver/state/ParaView/root case decisions','decision':None,'integrity_report':None}]
write(out/'scope-entry.json',entry)
registry['scopes'].append(entry);registry['at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();write(out/'candidate-index.json',registry)
oldq=load(H/'root_stage1_f3_five_interior_actual_production_059/F3_STAGE1_DP006_P1000_AY0320.json')
preflights=[]
for row in newrows:
 q=auth.build_prospective_request(manifest,row['case_id'],family_id='F3',scope_id=scope,attempt_id=f"root-stage1-f3-first24-ay{int(round(row['transverse_amplitude_m_s2']*1000)):04d}-full836-visual-production-113",adapter_path=adapter/'ds_data02_stage1_dispatch_v2.py',strict_path=LAB/'scripts/ds_data02_strict_dispatch_v1.py',runtime_path=LAB/'scripts/ds_data02_runtime_v2.py',input_files=[str(out/'case-manifest.json'),str(out/'physical-domain.json'),str(out/'root-visual-domain-decision.json')],max_wall_seconds=7200,cpu_threads=4,estimated_storage_bytes=16*1024**3,estimated_peak_gpu_mib=8192,worktree_root=str(R),launch_allowed=True,execution_allowed=True,launch_owner='root',future_case_visual_review='required_after_actual_complete_run')
 q['gencase_receipt']=oldq['gencase_receipt'];q['gencase_receipt_sha256']=oldq['gencase_receipt_sha256'];q['schema']='ds02.runner-request.v2'
 context={};hashes=auth.authorize(q,index_path=out/'candidate-index.json',approval_context=context)
 preflights.append({'case_id':q['case_id'],'authorized_hash_count':len(hashes),'lease_acquired':False,'resource_reserved':False,'native_executed':False})
 write(out/'requests'/f"{q['case_id']}.json",q)
assert len({x['forcing']['sha256'] for x in index['prepared_cases']})==16
write(out/'authorize-preflight.json',{'all16_passed':True,'actual_prepared_native_inputs':True,'unchanged_shared_strict_runtime':True,'results':preflights})
(out/'launch.py').write_text((H/'root_stage1_f3_five_interior_actual_production_059/launch.py').read_text())
print('Prepared and authorized16 prospective requests; register scope after local commit:',out)
