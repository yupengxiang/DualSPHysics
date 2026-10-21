"""One exact full official5s baseline; reuse canonical v14 and paid BUILD004."""
from pathlib import Path
import copy,datetime,hashlib,json,runpy,resource
P=Path(__file__).resolve().parents[1]
H=runpy.run_path(str(P/'control/prepare_F3_existing601_mass_task_actual001_v1.py'))
pin,publish,canonical=(H[k] for k in ('pin','publish','canonical'))
ROOT=Path('/data/nas/jade/Simulation/DualSPHysics/lfd-01')
C=P/'decisions/CASEFORCES_FULL5_SCIENCE_CONTRACT_V1.json'
REVIEW=P/'work/LFD01-CaseForces-full5-source-science-nonauthor-review/20261021-v1/REVIEW.json'
PREFLIGHT=P/'decisions/CASEFORCES_DERIVED_GENCASE_SOURCE_PREFLIGHT_V1.json'
Q=P/'requests/CaseForces-full5-timecontrol-solver001-v1'
CASE='LFD01_F2_OFFICIAL_CASEFORCES_DP020_CFL0125_FULL5';LEAF='LFD01_SOLVER_001';AID='F2/'+CASE+'/'+LEAF;JOB='LFD01_CASEFORCES_FULL5_TIMECONTROL_SOLVER_001';OUT=ROOT/'runs'/AID

def main():
    cfg=json.loads(C.read_bytes());rv=json.loads(REVIEW.read_bytes())
    assert rv['status'].startswith('accepted_static'),rv['status']
    pre=json.loads(PREFLIGHT.read_bytes());fact_cl=json.loads((P/'requests/CaseForces-initial-facts001-v1/ACTUAL_INITIAL_FACTS_CLOSURE_V1.json').read_bytes())
    asset=json.loads((P/'requests/F2-official-CaseForces-gencase001-v1/ACTUAL_ASSET_PARENT_NEGATIVE_CLOSURE_V1.json').read_bytes())
    asset_report=json.loads(Path(asset['asset_report']['path']).read_bytes())
    assert not Q.exists() and not OUT.exists() and not (ROOT/'runs/.lfd01-control/jobs'/JOB).exists()
    request=json.loads((P/'requests/F3-centered-full6-solver-v2/request.json').read_bytes())
    grant=json.loads((P/'requests/F3-centered-full6-solver-v2/grant.json').read_bytes())
    base=json.loads((P/'requests/F6-unread-field-QA-actual001-v1/request.json').read_bytes())
    rows=copy.deepcopy(base['source_bindings'][:12]);by_path={r['path']:r for r in rows}
    def add(role,ref,deferred=False,cached=False):
        ref={k:ref[k] for k in ('path','bytes','sha256')}
        if ref['path'] in by_path:
            row=by_path[ref['path']];assert all(row[k]==ref[k] for k in ref) and row['deferred']==deferred
            row['role']=role;return
        if not deferred and not cached:assert pin(ref['path'])==ref
        row=dict(ref,role=role,deferred=deferred);rows.append(row);by_path[ref['path']]=row
    att=copy.deepcopy(request['compiled_binary_attestation'])
    for row in att['normal_inputs']:add(row['role'],row,cached=True)
    add('compiled_binary_artifact',request['binary_binding'],True,True)
    for role,ref in [('full5_science_contract',pin(C)),('source_science_nonauthor_review',pin(REVIEW)),('derived_real_GenCase_preflight',pin(PREFLIGHT)),('initial_native_facts_closure',pin(P/'requests/CaseForces-initial-facts001-v1/ACTUAL_INITIAL_FACTS_CLOSURE_V1.json')),('initial_native_facts',fact_cl['result']),('GenCase_asset_closure',pin(P/'requests/F2-official-CaseForces-gencase001-v1/ACTUAL_ASSET_PARENT_NEGATIVE_CLOSURE_V1.json')),('GenCase_asset_report',asset['asset_report']),('Root_bootstrap_explicit_revision',pin(P/'decisions/CASEFORCES_BOOTSTRAP_POLICY_EXPLICIT_REVISION_V1.json')),('adoption',pin(P/'control/ADOPTION.json')),('runtime_source_review',pin(P/'decisions/S01_V14_SOURCE_REVIEW_V1.json')),('compiled_source_trace_proof',pin(P/'decisions/BUILD004_CFL_OVERRIDE_AND_ACCEPTED_TRACE_SOURCE_PROOF_V1.json'))]:add(role,ref)
    source_cfg=json.loads((P/'decisions/OFFICIAL_CASEFORCES_GENCASE_ASSET_CONTRACT_V2.json').read_bytes())
    for i,ref in enumerate(source_cfg['official_inputs']):add('official_input_'+str(i),ref)
    add('initial_generated_xml',asset['generated_xml'],True)
    add('initial_frame_native',asset['initial_bi4'],True)
    for i,ref in enumerate(asset_report['forcing_inputs']):add('generated_forcing_'+str(i),ref,True)
    # Reuse actual-tested current-mount S01 v16; old v14 attempt remains unmodified.
    replacements={str(P/'work/S01/v14/lfd01_forward_runtime.py'):P/'work/S01/v16/lfd01_forward_runtime.py',str(P/'work/S01/v14/candidate-schema.json'):P/'work/S01/v16/candidate-schema.json'}
    for row in rows:
        if row['path'] in replacements:
            row.update(pin(replacements[row['path']]))
    by_path.clear();by_path.update({r['path']:r for r in rows})
    for role,path in [('current_mount_runtime_contract',P/'work/S01/v16/CURRENT_MOUNT_FORWARD_CONTRACT.v16.json'),('current_mount_runtime_nonauthor_review',P/'work/LFD01-S01-current-mount-forward-review/20261021-v2/REVIEW.json'),('current_mount_runtime_actual39',P/'requests/S01-current-mount-software003-v1/actual-tests-closure.json'),('current_mount_binary_paid_probe',P/'requests/F4-cached-BUILD004-probe-actual001-v1/actual-probe-closure.json'),('full5_protocol_adoption',P/'decisions/CASEFORCES_FULL5_PROTOCOL_ADOPTION_V1.json')]:add(role,pin(path))
    reused=json.loads((P/'work/LFD01-S01-current-mount-forward-review/20261021-v2/REVIEW.json').read_bytes());assert reused['status'].startswith('accepted')
    request['runtime_actual_tests']=pin(P/'requests/S01-current-mount-software003-v1/actual-tests-closure.json')
    grant['runtime_actual_tests']=request['runtime_actual_tests']
    add('completed_baseline_terminal_closure',pin(P/'requests/CaseForces-full5-baseline-solver001-v3/ACTUAL_SOLVER_TERMINAL_CLOSURE_V1.json'))
    Q.mkdir()
    manifest=publish(Q/'manifest.json',dict(schema='lfd01.Root.CaseForces.baseline-full5-manifest.v1',contract=pin(C),review=pin(REVIEW),source_preflight=pin(PREFLIGHT),source_bindings=rows,command_scope='unchangedofficialsource, compiledBUILD004GPU, DBCdefault, explicitCFL.125, fullTimeMax5/TimeOut.02',output_root=str(OUT),science_credit=0,core_credit=0))
    add('frozen_solver_manifest',manifest)
    normal=[r['path'] for r in rows if not r['deferred']];bindings_sha=hashlib.sha256(canonical(rows)).hexdigest()
    prefix=Path(asset['initial_bi4']['path']).with_suffix('')
    purpose='Preregistered T temporalcontrol full5s originalofficial3DCaseForces, exactsamegeneratedinputs/DBCdefault, onlyCFL.25to.125 per frozenfive-row sciencecontract; actualacceptedtraceandtolerancespending, numericalvariantnotnewcondition. FailedGenCaseparentnotrelabeled; derivedactualpreflightisnotexecutionreceipt. NoG1/G2/core fromsolvercompletion.'
    request.update(family_id='F2',case_id=CASE,attempt_id=LEAF,reservation_id=AID,controller_job_id=JOB,request_path=str(Q/'request.json'),grant_path=str(Q/'grant.json'),contract_path=str(C),manifest_path=str(Q/'manifest.json'),manifest_binding=manifest,manifest_sha256=manifest['sha256'],output_root=str(OUT),tmpdir=str(OUT/'.tmp'),command=[request['binary_binding']['path'],'-gpu',str(prefix),'-cfl:0.125',str(OUT)],gencase_receipt=str(PREFLIGHT),gencase_receipt_sha256=pin(PREFLIGHT)['sha256'],source_bindings=rows,source_bindings_sha256=bindings_sha,input_files=normal,normal_input_paths=normal,max_wall_seconds=1800,cpu_threads=1,affinity_cpus=[0],ram_limit_bytes=64*1024**3,nas_peak_bytes=64*1024**3,estimated_storage_bytes=2*1024**3,max_output_bytes=2*1024**3,max_stdout_bytes=1*1024**2,estimated_peak_gpu_mib=4096,required_dispatch_environment=dict(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYTHONOPTIMIZE='0',TMPDIR=str(OUT/'.tmp')),pre_solver_initial_scope=dict(accepted_gate=pin(REVIEW),initial_frame_native=dict(asset['initial_bi4'],deferred=True),scoped_input_predicates_passed=True,full_G0_G1_G2_core_credit=False,original_failed_GenCase_parent_preserved=True),full_event_observation=dict(window_s=[0,5],nominal_frame_count=251,time_max_s=5,time_out_s=.02,actual_endpoint_policy='Retain all actualframes andterminalovershoot, never crop/rescale/taildrop.',saved_task_contract=pin(C)),purpose=purpose,science_credit=0,core_credit=0)
    rr=publish(Q/'request.json',request)
    grant.update(family_id='F2',case_id=CASE,leaf_attempt_id=LEAF,attempt_id=AID,reservation_id=AID,controller_job_id=JOB,tranche_id=JOB,request_path=rr['path'],request_sha256=rr['sha256'],source_bindings=rows,source_bindings_sha256=bindings_sha,input_files=normal,normal_input_paths=normal,stage='CaseForces_full5_preregistered_T_temporalcontrol',allocation=dict(gpu_seconds=1800,cpu_core_seconds=3600,new_storage_bytes=4*1024**3,solver_attempts=1),issued_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),non_author_payload_review=pin(REVIEW),permitted_scope=purpose)
    grant.pop('payload_sha256',None);grant['payload_sha256']=hashlib.sha256(canonical(grant)).hexdigest();gr=publish(Q/'grant.json',grant)
    print(json.dumps(publish(Q/'MATERIALIZATION.json',dict(schema='lfd01.Root.CaseForces.baseline-full5-materialization.v1',status='prepared_pending_live_shared_admission',request=rr,grant=gr,manifest=manifest,contract=pin(C),review=pin(REVIEW),source_preflight=pin(PREFLIGHT),normal_rows=len(normal),deferred_rows=len(rows)-len(normal),normal_bytes=sum(r['bytes'] for r in rows if not r['deferred']),output_root=str(OUT),reservation_id=AID,controller_job_id=JOB,root_native_ELF_generatedXML_or_old_fullbuildreport_read=False,cached_build_attestation_reused=True,science_credit=0,core_credit=0,root_self_cpu_pending_uniqueinfra=sum(resource.getrusage(resource.RUSAGE_SELF)[:2])))))
if __name__=='__main__':main()
