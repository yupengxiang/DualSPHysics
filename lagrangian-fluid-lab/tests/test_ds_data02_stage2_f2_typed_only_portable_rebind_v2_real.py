"""Real relocated V8/V12/typed-scorer subprocess coverage for V2."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WT = ROOT
S = WT / "scripts"

def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
V1=load(S/'ds_data02_stage2_f2_typed_only_portable_rebind_v1.py','xv1')
V2=load(S/'ds_data02_stage2_f2_typed_only_portable_rebind_v2.py','xv2')
V8=load(S/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py','xv8')
V12=load(S/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py','xv12')
V14=load(S/'ds_data02_stage2_f2_replay_v14.py','xv14')


def test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path: Path):
    base=tmp_path; src=base/'source'; src.mkdir(parents=True)
    # identities: 0..21113; this is manufactured, with its own binding/hash.
    pairs=[(0,i) for i in range(21114)]
    identity_sha=hashlib.sha256(b''.join(__import__('struct').pack('<qq',z,i) for z,i in pairs)).hexdigest()
    DEN=21114.0
    current=src/'CURRENT.json'; current.write_text('{"fixture":"current"}\n'); current_sha=hashlib.sha256(current.read_bytes()).hexdigest()
    # source files for v15 fixture.
    def write(p, data, binary=False):
     p.parent.mkdir(parents=True,exist_ok=True)
     if binary: p.write_bytes(data)
     else: p.write_text(data,encoding='utf8')
     return p
    xml=write(src/'generated.xml','<root><objreal ref="0"><begin mov="m" start="0" finish="4"/><mvrotfile id="m" duration="4" anglesunits="degrees"/></objreal></root>')
    motion=write(src/'motion.dat','0;0\n4;-105\n')
    meta=write(src/'source-metadata.json',json.dumps({'schema':'ds02.f2.stage1.first48.prospective-source.v1','parameter_values':{'rotation_duration_s':0.9},'motion':{'sha256':'PLACE','rotation_stop_s':1.4,'static_hold_start_s':0.5,'final_angle_deg':-105.0}}))
    motion_sha=hashlib.sha256(motion.read_bytes()).hexdigest(); m=json.loads(meta.read_text());m['motion']['sha256']=motion_sha;meta.write_text(json.dumps(m,sort_keys=True))
    # receipts and engine sources
    eng={}
    for role in ('motion_engine_jmotion_obj','motion_engine_jmotion_mov','motion_engine_jmotion_data'):
     eng[role]=write(src/(role+'.cpp'),'fixture '+role+'\n')
    eng_sha={r:hashlib.sha256(p.read_bytes()).hexdigest() for r,p in eng.items()}
    receipts={}
    for role in ('gencase_receipt','solver_receipt'):
     receipts[role]=write(src/(role+'.json'),json.dumps({'input_hashes_at_launch':{'meta':hashlib.sha256(meta.read_bytes()).hexdigest(),'motion':motion_sha},'input_hashes_after_run':{'meta':hashlib.sha256(meta.read_bytes()).hexdigest(),'motion':motion_sha}}))
    # v15 minimal
    case={'current_case_index':78,'family_id':'F2','physical_case_id':'fixture-F2','manifest_case_id':'fixture-F2','runtime_case_alias':'fixture-F2'}
    times=[i*0.01 for i in range(401)]
    source_roles=[('generated_xml',xml),('motion_dat',motion),('source_metadata',meta),('gencase_receipt',receipts['gencase_receipt']),('solver_receipt',receipts['solver_receipt'])]
    sources=[{'role':r,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for r,p in source_roles]
    source_map={x['role']:x['sha256'] for x in sources}
    profile={
     'schema':'ds02.stage2.f2-s1-observer-profile.v14','profile_id':'fixture-profile','case_identity':case,
     'current_binding_sha256':current_sha,'trajectory_producer_sha256':'1'*64,
     'frozen_before_reference':True,'scientific_status':'DEVELOPMENT_PREREGISTERED_UNKNOWN',
     'position_scale_m':1.0,'velocity_scale_m_s':1.0,'kinetic_energy_scale_J':1.0,'mass_denominator_kg':DEN,'event_time_scale_s':4.0,
     'motion_control_end_angle_deg':-105.0,'motion_control_semantics':'fixture','moving_frame_semantics':{'position':'body','velocity':'world_inertial'},
     'mass_quantiles':[0.5,0.75,0.9,1.0],'normalized_bin_edges':[-2,-1,0,1,2],
     'observable_names':['mass_weighted_com_m','mass_weighted_mean_velocity_m_s','mass_weighted_kinetic_energy_J','mass_quantile_front_m','mass_distribution_fraction','event_status','event_time_s'],
     'query_frame_indices':[0,100,200,300,400],'query_times_s':[times[i] for i in [0,100,200,300,400]],
     'scientific_error_budget':{'output_sampling_fraction':.25,'time_integration_fraction':.25},
     'scope':'fixture','event_time_scale_source':'fixture','tolerance_basis':'fixture',
     'thresholds':{'position_relative':.02,'mass_fraction':.03,'event_time_fraction':.01,'velocity_relative':.03,'kinetic_energy_relative':.03,'mass_front_relative':.02},
     'source_file_sha256':source_map,
    }
    profile['sha256']=V14._canonical_sha256(profile)
    mcontrol={'active_interval_s':[0.,4.],'angles_units':'degrees','completion_policy':'hold_last_pose_zero_angular_velocity_after_finish','duration_s':4.,'end_angle_deg':-105.,'finish_inclusive':True,'finish_s':4.,'hold_until_s':4.,'rotation_duration_s':.9,'rotation_hold_start_s':.5,'rotation_stop_s':1.4,'source_role':'motion_dat','start_angle_deg':0.,'table_coverage_s':[0.,4.]}
    frozen={'schema':'ds02.stage2.f2-s1-replay-request.v15','fixture_mode':True,'role':'DEVELOPMENT','status':'MANUFACTURED_ONLY','qualification':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},'model_invoked':False,'case_identity':case,
     'source_files':sources,'cohort':{'initial_type_code':3,'expected_initial_fluid_count':21114,'selected_count':21114,'source_identity_set_sha256':identity_sha},
     'window':{'expected_times_s':times,'frame_start':0,'frame_stop':400},'motion_control':mcontrol,'motion_engine_sources':{r:{'path':str(p),'sha256':eng_sha[r]} for r,p in eng.items()},
     'observer':{'position_scale_m':1.,'velocity_scale_m_s':1.,'kinetic_energy_scale_J':1.,'mass_denominator_kg':DEN,'event_time_scale_s':4.,'mass_quantiles':[.5,.75,.9,1.0],'normalized_bin_edges':[-2,-1,0,1,2]},
     'observer_profile':profile,'current_binding':{'sha256':current_sha},'trajectory_h5':{'producer_declared_sha256':'1'*64,'path':str(src/'trajectory.h5')}}
    frozen_path=src/'frozen.json'; frozen_path.write_text(json.dumps(frozen,sort_keys=True))
    # Result
    labels=[]; receivers=[]
    for z,i in pairs:
     labels.append({'zone':z,'idp':i,'initial_mass_kg':1.0,'status':'observed','first_saved_bracket_s':[0.,.01],'event_time_s':.005,'crossing_candidate_times_s':[.005],'recross_status':'UNKNOWN_RECROSSING'})
     receivers.append({'zone':z,'idp':i,'status':'observed','final_destination_status':'inside_receiver_volume','first_saved_bracket_s':[0.,.01],'aperture_first_arrival_status':'UNKNOWN'})
    frames=[]
    for frame,t in enumerate(times):
     frames.append({'frame':frame,'time_s':t,'initial_mass_denominator_kg':DEN,'initial_missing_mass_bucket_kg':0.,'denominator_unobserved_mass_kg':0.,'mass_accounting':{'initial_missing_mass_kg':0.},'position_frame':'body','velocity_frame':'world_inertial','mass_weighted_com_m':[0.,0.,0.],'mass_weighted_mean_velocity_m_s':[0.,0.,0.],'mass_weighted_kinetic_energy_J':0.,'mass_quantile_front_m':{'0.5':0.,'0.75':0.,'0.9':0.,'1.0':0.},'mass_distribution_kg':[0.,0.,0.,0.]})
    result={'schema':'ds02.stage2.f2-s1-replay-result.v16','model_invoked':False,'cfd_invoked':False,'quality':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},'case_identity':case,
     'source_binding':{'binding_status':'EXACT_CURRENT_SOURCE_BOUND','current_catalog_sha256':current_sha,'trajectory_h5_producer_sha256':'1'*64,'source_files':source_map},
     'observer_profile':profile,'cohort':{'identity_key':'(Zone,Idp)','selected_count':21114,'initial_fluid_candidates':21114,'selected_identity_sha256':identity_sha,'source_identity_set_sha256':identity_sha},
     'initial_mass_denominator':{'denominator_kg':DEN,'initial_fluid_mass_kg':DEN,'selected_initial_mass_kg':DEN,'initial_missing_mass_kg':0.,'initially_absent_count':0,'later_missing_mass_kg':0.003000000142492354,'later_missing_unique_count':3,'missing_scope':'initial_fluid_source_cohort_global; identity fate unknown'},
     'velocity_semantics':'world_inertial','window':{'frame_count':401,'frame_start':0,'frame_stop':400,'time_start_s':0.,'time_stop_s':4.},'frame_observations':frames,'labels':labels,'receiver_volume_labels':receivers,
     'event_summary':{'label_counts':{'observed':21114},'receiver_volume_label_counts':{'observed':21114},'net_flux_total_interval_kg':[0.,0.],'gross_flux_status':'UNKNOWN','residence_output_mode':'per_particle_compact','residence_unknown_mass_time_semantics':'unknown upper bound'},}
    result_path=src/'result.json'; result_path.write_text(json.dumps(result,separators=(',',':'),sort_keys=True))
    result_sha=hashlib.sha256(result_path.read_bytes()).hexdigest(); result_bytes=result_path.stat().st_size
    print('result size',result_bytes,'sha',result_sha,'identity',identity_sha)
    # nested, sidecar, request
    nested={'schema':'ds02.stage2.f2-native-raw-to-typed-to-label-report.v2','status':'COMPLETE_DEVELOPMENT_UNKNOWN','metadata_only':True}; nested['report_sha256']=V12.report_canonical_sha(nested)
    nested_path=src/'nested.json'; nested_path.write_text(json.dumps(nested,sort_keys=True)); nested_sha=hashlib.sha256(nested_path.read_bytes()).hexdigest()
    inner={'schema':V8.REQUEST_SCHEMA,'status':'READY_FOR_PARENT_GUARD','role':'DEVELOPMENT','model_invoked':False,'cfd_invoked':False,'quality':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},'ledger_mutated':False,
     'execution':{'max_wall_seconds':120.,'max_result_bytes':100_000_000,'read_hdf5_or_bi4':False,'raw_opened':False},
     'result':{'path':str(result_path),'sha256':result_sha,'bytes':result_bytes},'relocation':{'target_root':str(src),'output_root':str(src),'original_roots':[str(base/'original')]},
     'expected':{'source_binding':result['source_binding'],'case_identity':case,'cohort':{'selected_count':21114,'identity_key':'(Zone,Idp)','identity_sha256':identity_sha},'initial_mass_denominator':{'denominator_kg':DEN,'initial_missing_mass_kg':0.,'later_missing_mass_kg':0.003000000142492354,'later_missing_unique_count':3,'tolerance_kg':1e-8},'time':{'frame_count':401,'first_s':0.,'last_s':4.,'tolerance_s':1e-9,'observer_profile_sha256':profile['sha256']},'observer_fields':[],'events':{'status_vocabulary':sorted(V8.FIRST_PASSAGE_STATUSES),'require_unknown_recross':True,'require_total_net_interval':True,'require_receiver_labels':True}},
     'current_manifest_binding':{'path':str(current),'sha256':current_sha},'source_frozen_request':{'path':str(frozen_path),'sha256':hashlib.sha256(frozen_path.read_bytes()).hexdigest()},
     'v12_forward':{'schema':V12.FORWARD_SCHEMA,'source_request':{'schema':V8.REQUEST_SCHEMA,'path':'fixture-source-request.json','sha256':'b'*64,'canonical_sha256':'c'*64},'semantic_sidecar':{'path':str(src/'sidecar.json'),'sha256':''}},
     'v66_parent_binding':{'producer_case_id':'fixture-case','producer_attempt_id':'fixture-attempt','nested_worker_report':{'path':str(nested_path),'sha256':nested_sha}},}
    # sidecar after request source binding; use placeholders v16 etc
    side={'schema':V12.SIDECAR_SCHEMA,'status':'SOURCE_BOUND_SEMANTIC_CONTRACT','producer_v66_request':{'path':'fixture-v66.json','file_sha256':'b'*64,'canonical_sha256':'c'*64,'producer_case_id':'fixture-case','producer_attempt_id':'fixture-attempt'},'producer_nested_report':{'path':str(nested_path),'sha256':nested_sha,'schema':nested['schema'],'report_canonical_sha256':nested['report_sha256']},'v16_result':{'path':str(result_path),'sha256':result_sha,'bytes':result_bytes},'current_manifest':{'path':str(current),'sha256':current_sha},'missing_scope':V12.ACCEPTED_MISSING_SCOPE,'denominator_semantics':V12.ACCEPTED_SCOPE_SEMANTICS,'scope_source':{'path':'fixture-provenance.py','sha256':'e'*64,'missing_scope_literal':V12.ACCEPTED_MISSING_SCOPE},'expected':{'identity_key':'(Zone,Idp)','selected_count':21114,'identity_sha256':identity_sha,'denominator_kg':DEN,'initial_missing_mass_kg':0.,'later_missing_mass_kg':0.003000000142492354,'later_missing_unique_count':3},'typed_fields':sorted(V12.REQUIRED_TYPED_FIELDS),'status_vocabulary':sorted(V12.REQUIRED_STATUS_VOCABULARY),'qualification':{'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'}}
    side_path=src/'sidecar.json'; side['sha256']=V12.canonical_sha(side); side_path.write_text(json.dumps(side,sort_keys=True))
    inner['v12_forward']['semantic_sidecar']['sha256']=hashlib.sha256(side_path.read_bytes()).hexdigest(); inner['sha256']=V8.canonical_sha(inner); request_path=src/'inner.json';request_path.write_text(json.dumps(inner,sort_keys=True))
    # Patch V12 copy constants for fixture current/identity/denominator; V8/scorer remain real strict operators.
    v12copy=src/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py'; shutil.copyfile(S/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py',src/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py'); txt=(S/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py').read_text(); txt=txt.replace('ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"',f'ACTUAL_CURRENT_SHA = "{current_sha}"').replace('EXPECTED_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"',f'EXPECTED_IDENTITY_SHA = "{identity_sha}"').replace('EXPECTED_DENOMINATOR = 21.114001002861187','EXPECTED_DENOMINATOR = 21114.0'); v12copy.write_text(txt)
    # run direct v8 / v12 patched / score first
    print('validate frozen direct')
    print(load(S/'ds_data02_stage2_f2_no_model_evaluator_v2.py','xv2eval').validate_frozen_request(frozen))
    print('v8 bound')
    bound=V8._validate_request(inner,verify_result_stat=False); print(bound['result_bytes'])
    res=V8._read_result(result_path,100_000_000)[0]; print('raw v8 expected reject before v12 normalization')
    V12p=load(v12copy,'xv12p'); # patch inner v12 uses source path sidecar current okay
    markerfile, markerreq, scope=V12p._load_marker(request_path); V12p._ACTIVE_SCOPE=scope; print('v12val',V12p._validate_result_v12(res,bound,result_sha,result_bytes)['cohort'])
    score=load(S/'ds_data02_stage2_f2_typed_only_evaluator_v1.py','xscore')._score_typed_result(res,frozen); print('score',score['case_expectations'])
    # prepare manifests/contract with all source roles; invoke V2 worker after copying runtime manually below later
    print('BASE',base)
    # dump paths for next script usage
    # Build a real V2 bundle and run through the copied V2 entrypoint.
    (src/'trajectory.h5').write_bytes(b'fixture trajectory placeholder')
    def art(p, role, target, kind='runtime_source', deferred=False):
     return {'logical_role':role,'source_kind':kind,'source_path_provenance':str(p),'source_sha256':V1._sha(p),'source_sha256_basis':'fixture','source_stat_provenance':V1._stat(p),'target_relative_path':target,'actionable':True,'content_read_by_manifest':not deferred}
    roles=[]
    roles += [art(request_path,'root200_inner_request','evidence/root200/inner.json','bounded_evidence'),art(current,'current336_actionable_metadata','evidence/current/CURRENT.json','bounded_evidence'),art(result_path,'root179c_typed_result_deferred','products/result.json','deferred_result_json',True),art(frozen_path,'frozen_v15_request','evidence/frozen-v15/request.json','bounded_evidence'),art(src/'trajectory.h5','trajectory_h5_deferred','products/trajectory.h5','deferred_typed_h5',True),art(side_path,'v12_semantic_sidecar','evidence/v12/semantic-sidecar.json','bounded_evidence'),art(nested_path,'producer_nested_report_v2','evidence/v12/producer-report.json','bounded_evidence')]
    # artifact path for trajectory
    for r,p in source_roles:
     roles.append(art(p,'frozen_source_'+r,'evidence/frozen-v15/'+p.name,'frozen_source'))
    for r,p in eng.items(): roles.append(art(p,r,'evidence/frozen-v15/'+p.name,'frozen_source'))
    for r,p in receipts.items(): pass
    # generated v12 source and copied runtime source
    v8src=S/'ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py'; shutil.copyfile(v8src,src/v8src.name)
    for name,p in [('v12',v12copy),('portable_rebind_v2',S/'ds_data02_stage2_f2_typed_only_portable_rebind_v2.py'),('typed_scorer',S/'ds_data02_stage2_f2_typed_only_evaluator_v1.py'),('typed_scorer_v3',S/'ds_data02_stage2_f2_no_model_evaluator_v3.py'),('typed_scorer_v2',S/'ds_data02_stage2_f2_no_model_evaluator_v2.py'),('replay_v14',S/'ds_data02_stage2_f2_replay_v14.py'),('replay_v15',S/'ds_data02_stage2_f2_replay_v15.py')]:
     targetname={'v12':v12copy.name,'portable_rebind_v2':p.name,'typed_scorer':p.name,'typed_scorer_v3':p.name,'typed_scorer_v2':p.name,'replay_v14':p.name,'replay_v15':p.name}[name]
     role={'v12':'fresh_v16_proof_consumer_v12','portable_rebind_v2':'portable_rebind_v2_entrypoint','typed_scorer':'typed_only_evaluator_v1','typed_scorer_v3':'typed_only_evaluator_v3','typed_scorer_v2':'typed_only_evaluator_v2','replay_v14':'replay_v14','replay_v15':'replay_v15'}[name]
     roles.append(art(p,role,'runtime/'+targetname,'runtime_source'))
    roles.append(art(v8src,'fresh_v16_proof_consumer_v8','runtime/'+v8src.name,'runtime_source'))
    roles.append(art(S/'ds_data02_stage2_f2_replay_v15.py','frozen_v15_request_runtime','runtime/ds_data02_stage2_f2_replay_v15.py','runtime_source'))
    # The role above duplicates target replay_v15; remove duplicate target by not adding frozen runtime; frozen request is logical frozen_v15_request.
    roles=[x for i,x in enumerate(roles) if not (x['logical_role']=='frozen_v15_request_runtime')]
    # v1 helper gets injected; interpreter/cfg
    pyvenv=src/'pyvenv.cfg'; pyvenv.write_text('home = /usr\ninclude-system-site-packages = true\nversion = 3.10.12\n')
    py=src/'python'; shutil.copyfile(sys.executable,py); py.chmod(0o755)
    roles += [art(pyvenv,'pinned_project_pyvenv_cfg','environment/pyvenv.cfg','external_environment'),art(py,'literal_project_venv_python','environment/python','external_environment_exception')]
    loading={'entrypoint_logical_role':'fresh_v16_proof_consumer_v8','entrypoint_target_relative_path':'runtime/'+v8src.name,'request_target_relative_path':'evidence/root200/inner.json','frozen_v15_target_relative_path':'evidence/frozen-v15/request.json','current_target_relative_path':'evidence/current/CURRENT.json','result_target_relative_path':'products/result.json','typed_h5_target_relative_path':'products/result.h5','fresh_proof_target_relative_path':'reports/proof.json','operator_report_target_relative_path':'reports/operator.json','runtime_sibling_directory':'runtime','source_fallback':'REJECT','no_model':True,'model_invoked':False}
    manifest={'schema':V1.MANIFEST_SCHEMA,'status':'PORTABLE_TYPED_ONLY_DEPENDENCY_AUDIT_METADATA_COMPLETE','artifacts':roles,'portable_loading_entry':loading,'path_policy':{'original_absolute_path_fallback':'REJECT'}}; manifest['sha256']=V1._canonical(manifest); manifest_path=base/'manifest.json';manifest_path.write_text(json.dumps(manifest,sort_keys=True))
    rel=base/'relocated'; contract_path=base/'contract.json'; V1.build_contract(manifest_path=manifest_path,relocated_root=rel,output=contract_path,contract_id='positive')
    contract=json.loads(contract_path.read_text())
    for role in contract['roles']:
     target=rel/role['target_relative_path']; target.parent.mkdir(parents=True,exist_ok=True); sourcep=Path(role['source_path_provenance'])
     shutil.copyfile(sourcep,target)
     if role['logical_role']=='literal_project_venv_python': target.chmod(0o755)
    # V2 script / V1 helper are added by contract roles; ensure deferred result target has real generated result.
    # overwritten copy from source was the generated 7.9MB result, okay.
    # command output is under relocated root; remove original source after sealing to prove no fallback.
    overlay=base/'overlay.json'; print('building overlay')
    print(V2.build_request_overlay(contract_path=contract_path,request_role='root200_inner_request',output=overlay,request_target_relative='requests/rebound.json',request_id='POS'))
    print('validate', V2.validate_request_overlay(overlay)['request']['status'])
    shutil.rmtree(src)
    print('run guard')
    receipt=V2.run_guard(request_path=overlay,output_relative='reports/v2-report.json',parent_pid=os.getppid(),python_path=rel/'environment/python',max_wall_seconds=120)

    report=json.loads((rel/'reports/v2-report.json').read_text())
    assert receipt['status']=='COMPLETE_RELOCATED_TYPED_ONLY_V2'
    assert report['status']=='PASS_RELOCATED_V8_V12_TYPED_SCORER'
    assert report['execution']['model_invoked'] is False
    assert report['execution']['hdf5_or_bi4_content_read'] is False
    assert report['result_source']['pre_post_stat_equal'] is True
    assert report['typed_operator_score']['case_expectations']=={'pass':'PASS','wrong_velocity':'FAIL','wrong_time':'FAIL','wrong_budget':'FAIL','wrong_shape':'BINDING_ERROR','wrong_source':'BINDING_ERROR'}
    assert receipt['stream_accounting']['timed_out'] is False
    assert receipt['stream_accounting']['stderr_bytes']==0
