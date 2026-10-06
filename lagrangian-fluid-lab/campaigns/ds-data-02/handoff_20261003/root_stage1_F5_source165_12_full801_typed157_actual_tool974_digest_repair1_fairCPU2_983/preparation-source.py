from pathlib import Path
import json,hashlib,subprocess,datetime
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003';D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root=lambda n:next(H.glob(f'root*_{n:03d}'));load=lambda p:json.loads(Path(p).read_text())
def put(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    p=Path(p);assert p.suffix in {'.json','.py','.md','.xml'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':str(p),'sha256':sha(p)}
old=root(982);old_config=load(old/'controller-config.json');progress=load(old/'actual-progress.json')
assert len(progress['results'])==1 and progress['results'][0]['launcher_returncode']==1
decoder=Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump')
assert "Input differs from registered digest: "+str(decoder) in progress['results'][0]['stderr_tail']
tq=load(root(974)/'enabled-typed-request.json');tr=Path(tq['attempt_root'])/'execution-receipt.json';t=load(tr)
assert (t['status'],t['returncode'])==('completed',0)
current=hashlib.sha256(decoder.read_bytes()).hexdigest()
assert current==t['input_hashes_at_launch'][str(decoder.resolve())]==t['input_hashes_after_run'][str(decoder.resolve())]=='b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e'
assert len(old_config['requests'])==12
for p in old_config['requests']:
    q=load(p);assert not Path(q['attempt_root']).exists()
failure=old/'actual-prelaunch-decoder-digest-failure-classification.json'
put(failure,{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status':'actual strict runner rejected first request before scientific process and receipt creation',
    'actual_progress':ref(old/'actual-progress.json'),'controller_result':ref(old/'controller-result.json'),
    'mismatched_registered_tool':str(decoder),'wrong_source165_digest':load(old_config['requests'][0])['input_sha256'][str(decoder)],
    'current_registered_tool_digest':current,'actual974_before_and_after_tool_provenance':ref(tr),
    'grounded_metadata_digest_repair_ordinal':1,'source_worker_and_science_recipe_unchanged':True,
    'source165_disabled_validator_did_not_check_tool_bytes':True,
    'science_jobs_launched':0,'actual_attempt_roots_created':0,'case_credit':0,
    'next_action':'New Root983 successor requests rebind only this stale tool digest; original Root982 evidence and input bindings preserved.'})
O=H/'root_stage1_F5_source165_12_full801_typed157_actual_tool974_digest_repair1_fairCPU2_983';O.mkdir(exist_ok=False)
controller=O/'batch-typed-controller.py';controller.write_bytes((old/'batch-typed-controller.py').read_bytes())
fair=root(928)/'fair_CPU_dispatch.py';assert sha(fair)==old_config['fair_dispatch']['sha256']
(O/'requests').mkdir();enabled=[];rows=[]
for p in old_config['requests']:
    source=Path(p);q=load(source);old_attempt=q['attempt_root'];old_digest=q['input_sha256'][str(decoder)]
    assert old_digest=='b8ac8cf4c71c1f0b238d1c89fbe3f2e36b1a7c2d8b2a9c7202d8d80d4dfca1ce'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==old_config['request_sha256'][p]
    md=q['input_sha256'].copy();md[str(decoder)]=current
    # All unchanged safe metadata and the other registered binary tools are
    # checked now. No scientific payload contents are touched by the primary.
    for name,digest in md.items():
        path=Path(name);assert path.is_file()
        cat=q['input_sha256_categories'].get(name)
        if cat=='registered_binary_attestation':
            observed=hashlib.sha256(path.read_bytes()).hexdigest()
            assert observed==digest==t['input_hashes_at_launch'][str(path.resolve())]==t['input_hashes_after_run'][str(path.resolve())]
        elif path.suffix in {'.json','.xml','.py','.md','.sh','.toml','.ini'}:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        else:
            assert cat=='producer_payload_attestation' and path.suffix in {'.bi4','.dat'}
    for file in [controller,fair,source,failure,tr]:md[str(file)]=sha(file)
    aid=q['attempt_id'].replace('root982','root983');ar=D/'families/F5'/q['case_id']/aid;assert not ar.exists()
    cmd=q['command'].copy();cmd[cmd.index('--staging-root')+1]=cmd[cmd.index('--staging-root')+1].replace('root982','root983')
    assert not Path(cmd[cmd.index('--staging-root')+1]).exists()
    cid=f"F5/{q['case_id']}/{aid}";cmd[cmd.index('--current-attempt-id')+1]=cid
    q.update(attempt_id=aid,attempt_root=str(ar),current_attempt_id=cid,command=cmd,
        input_files=sorted(md),input_sha256=md,
        root_grounded_decoder_metadata_repair_ordinal=1,
        root_unmodified_strict_guard_and_runtime_checks=True,
        root_preserved_actual_prelaunch_failure=ref(failure),
        root_successor_of_unlaunched_request=ref(source),
        root_registered_tool_digest_transition={'path':str(decoder),'original_declared':old_digest,
            'new_registered':current,'actual974_receipt':ref(tr),'same_digest_before_and_after':True,
            'science_tool_binary_changed':False,'main_scientific_payload_IO':False},
        input_sha256_categories={name:q['input_sha256_categories'].get(name,'root_metadata_current_hash') for name in md},
        input_sha256_provenance={name:q['input_sha256_provenance'].get(name,'Root immutable metadata SHA') for name in md})
    q['input_sha256_provenance'][str(decoder)]='Exact registered tool digest corroborated by actual974 completed runner pre/post receipts and current tool-only binary SHA'
    qp=O/'requests'/(q['tag']+'-enabled-typed-request.json');put(qp,q);enabled.append(str(qp))
    rows.append({'tag':q['tag'],'request':ref(qp),'unchanged_owner':q['owner_metadata'],
        'unchanged_native_receipt':q['actual_native_dependency']['receipt'],
        'canonical_scope':q['physical_condition_sha256'],
        'expected_prospective_unchanged_converter_scope':q['expected_converter_scope_sha256'],
        'new_attempt_root':str(ar),'original_unlaunched_attempt_root':old_attempt})
put(O/'controller-config.json',{'requests':enabled,'request_sha256':{p:sha(p) for p in enabled},
    'fair_dispatch':ref(fair),'effective_shared_serial_conversion_concurrency':1,
    'cooperative_yield_between_admitted_jobs_seconds':4,'case_credit':0})
put(O/'actual-tool-metadata-repair-and-12-request-closure.json',{'cases':rows,'source165_source_bytes_preserved':True,
    'actual982_failure_preserved':ref(failure),'registered_decoder_provenance_actual974':ref(tr),
    'science_parameters_owner_worker_and_per_case_sources_unchanged':True,
    'strict_guard_not_overridden':True,'prospective_owner_scope_and_historical_source_scope_separate':True,
    'actual_scientific_payloads_IO_by_main':False,'science_job_retry':False,'case_credit':0})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]+[str(failure.relative_to(R))]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: bind F5 successor decoder digest to actual completed registered tool evidence','--',*paths],cwd=R,check=True)
print({'root':str(O),'enabled_cases':12,'actual_prelaunch_failure_preserved':True,
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
