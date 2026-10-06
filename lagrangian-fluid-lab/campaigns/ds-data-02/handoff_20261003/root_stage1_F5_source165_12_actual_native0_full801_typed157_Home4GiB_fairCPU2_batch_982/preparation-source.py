from pathlib import Path
import json, hashlib, subprocess, runpy, re, datetime

R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
L = R/'lagrangian-fluid-lab'
H = L/'campaigns/ds-data-02/handoff_20261003'
W = Path('/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics')
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
root = lambda n: next(H.glob(f'root*_{n:03d}'))
load = lambda p: json.loads(Path(p).read_text())
def put(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def sha(p):
    p = Path(p)
    assert p.is_file() and p.suffix.lower() in {'.json','.jsonl','.py','.md','.xml','.xmf','.sh','.toml','.ini'}
    return hashlib.sha256(p.read_bytes()).hexdigest()
ref = lambda p: {'path':str(p), 'sha256':sha(p)}
prefix = 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_165_f5_native_ready_typed157_home4gib_disabled_v1'
commit = 'cb64d3d323f0f7b05d1bf7e8995ed31628c5f0d2'
names = subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'--',prefix],cwd=W,text=True).splitlines()
assert len(names)==30
adopted=[]
for name in names:
    assert Path(name).suffix in {'.json','.py','.md'}
    raw=subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=W)
    assert raw==(W/name).read_bytes()
    p=R/name
    assert not p.exists() or p.read_bytes()==raw
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(raw)
    adopted.append(ref(p))
P=R/prefix
O=H/'root_stage1_F5_source165_12_actual_native0_full801_typed157_Home4GiB_fairCPU2_batch_982'
O.mkdir(exist_ok=True)
assert not (O/'controller-config.json').exists()
validator=P/'scripts/validate_fresh165.py'
v=runpy.run_path(str(validator))
source_report_before=ref(P/'metadata/fresh165-validator-report.json')
requests=sorted((P/'requests').glob('*.json'))
assert len(requests)==12
results=[v['validate_one'](P,p) for p in requests]
assert len({z['tag'] for z in results})==12
negative=False
try:
    v['require_worker_hash']('stale-worker-sha')
except AssertionError:
    negative=True
assert negative
for rel,digest in load(P/'manifest.json')['files'].items():
    assert sha(P/rel)==digest
assert source_report_before==ref(P/'metadata/fresh165-validator-report.json')
put(O/'actual-source165-independent-validator.json',{
    'source_validator':ref(validator),'status':'pass-disabled-metadata-only',
    'entrypoint':'Unchanged validate_one, require_worker_hash and all manifest checks; main() not invoked because its default output would overwrite a consumed source report.',
    'original_source_report_preserved':source_report_before,
    'requests':results,'negative_stale_worker_rejected':True,'science_payload_IO':False})

cp=load(H/'ROOT_LIVE_RESUMPTION_CHECKPOINT_133.json')
accepted=[load(p) for p in cp['accepted_decisions']]
ids={z.get('physical_case_id',z['case_id']) for z in accepted}
scopes={z['physical_condition_sha256'] for z in accepted}
for n in [939,972,971]:
    for p in root(n).glob('*request*.json'):
        q=load(p)
        if q.get('physical_case_id'):
            ids.add(q['physical_case_id'])
        if q.get('physical_condition_sha256'):
            scopes.add(q['physical_condition_sha256'])
base=load(root(974)/'enabled-typed-request.json')
fair=root(928)/'fair_CPU_dispatch.py'
assert sha(fair)=='e2796fb88cc989278bcc4d194493f11e5ded7e6d2fb79ef37349d7ae7d8d679f'
converter=runpy.run_path(str(L/'scripts/ds_data02_direct_convert.py'))
controller=O/'batch-typed-controller.py'
controller.write_text("""from pathlib import Path
import json,runpy,time,hashlib
O=Path(__file__).parent
c=json.loads((O/'controller-config.json').read_text())
assert hashlib.sha256(Path(c['fair_dispatch']['path']).read_bytes()).hexdigest()==c['fair_dispatch']['sha256']
dispatch=runpy.run_path(c['fair_dispatch']['path'])['dispatch']
results=[]
for qp in c['requests']:
    assert hashlib.sha256(Path(qp).read_bytes()).hexdigest()==c['request_sha256'][qp]
    q=json.loads(Path(qp).read_text())
    r=dispatch(qp,serial_conversion=True)
    rp=Path(q['attempt_root'])/'execution-receipt.json'
    a=json.loads(rp.read_text()) if rp.exists() else {}
    tp=Path(q['attempt_root'])/'conversion-report.json'
    t=json.loads(tp.read_text()) if tp.exists() else {}
    passed=(r.returncode==0 and a.get('status')=='completed' and a.get('returncode')==0
        and t.get('conversion_status')=='completed' and t.get('frames')==801
        and t.get('particles')==194427 and t.get('solver_dimension',{}).get('solver_dimension')==3
        and t.get('partvtk_validation',{}).get('all_passed') is True
        and t.get('hash_scopes',{}).get('physical_condition_sha256')==q['expected_converter_scope_sha256'])
    z={'tag':q['tag'],'case_id':q['case_id'],'physical_case_id':q['physical_case_id'],
       'request':qp,'actual_receipt':str(rp),'actual_conversion_report':str(tp),
       'status':a.get('status'),'returncode':a.get('returncode'),'launcher_returncode':r.returncode,
       'actual_full801_typed_pass':passed,'stdout_tail':r.stdout[-1800:],
       'stderr_tail':r.stderr[-1800:],'case_credit':0}
    results.append(z)
    progress={'results':results,'not_submitted':len(c['requests'])-len(results),'case_credit':0}
    (O/'actual-progress.json').write_text(json.dumps(progress,indent=2)+'\\n')
    print(json.dumps(z),flush=True)
    if not passed:
        (O/'controller-result.json').write_text(json.dumps({'status':'stopped_for_primary_failure_classification',
            'failed_tag':q['tag'],'not_submitted':progress['not_submitted'],
            'returncode':r.returncode or 1,'case_credit':0},indent=2)+'\\n')
        raise SystemExit(r.returncode or 1)
    time.sleep(4)
(O/'controller-result.json').write_text(json.dumps({'status':'completed','returncode':0,
    'actual_completed_conversions':len(results),'case_credit':0},indent=2)+'\\n')
""")
(O/'requests').mkdir(exist_ok=True)
assert not list((O/'requests').glob('*.json'))
enabled=[]
rows=[]
for source in requests:
    q=load(source)
    assert q['physical_case_id'] not in ids and q['physical_condition_sha256'] not in scopes
    ids.add(q['physical_case_id']);scopes.add(q['physical_condition_sha256'])
    n=load(q['actual_native_dependency']['receipt'])
    assert n['status']=='completed' and n['returncode']==0
    assert n['request']['case_id']==q['case_id'] and n['request']['physical_case_id']==q['physical_case_id']
    assert n['request']['physical_condition_sha256']==q['physical_condition_sha256']
    assert n['request']['gencase_receipt']==q['gencase_receipt']
    assert n['request']['gencase_receipt_sha256']==sha(q['gencase_receipt'])
    assert n['input_hashes_at_launch'][q['generated_xml']]==n['input_hashes_after_run'][q['generated_xml']]==q['generated_xml_sha256']
    assert str(Path(q['generated_xml']).with_suffix('')) in n['command']
    if n['request'].get('generated_xml'):
        assert n['request']['generated_xml']==q['generated_xml']
    qa_receipt=load(q['actual_initial_qa_receipt'])
    assert (qa_receipt['status'],qa_receipt['returncode'])==('completed',0)
    dr=Path(q['native_solver_data_root'])
    frames=sorted(p.name for p in dr.iterdir() if re.fullmatch(r'Part_[0-9]+\.bi4',p.name))
    assert frames==[f'Part_{i:04d}.bi4' for i in range(801)]
    owner=load(q['owner_metadata'])
    assert owner['physical_case_id']==q['physical_case_id']
    prospective_scope=converter['_physical_condition_scope'](owner)
    legacy=converter['canonical_hash'](prospective_scope)
    assert q['source_h5_legacy_scope']['schema']=='legacy-owner-scope.v0'
    assert q['source_h5_legacy_scope']['sha256']==q.get('source_h5_legacy_scope_sha256')
    # A historical source artifact digest is preserved by role; the new converter's
    # expected metadata scope is derived independently from its exact current owner.
    cmd=q['command'].copy()
    assert sha(cmd[1])=='37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11'
    md={};directories=[];payload_attestations=[]
    for p,digest in q['input_sha256'].items():
        path=Path(p)
        assert path.is_absolute() and path.exists()
        if path.is_dir():
            assert digest is None and q['input_sha256_categories'][p]=='producer_directory'
            directories.append({'path':p,'runtime_hash':None,'binding':'Actual per-case native receipt and solver data root; scientific producer validates and hashes raw saved states.'})
        else:
            assert digest is not None
            if path.suffix.lower() in v['SAFE']:
                assert sha(path)==digest
            else:
                if path.suffix.lower() in v['SCIENCE']:
                    if p==q['generated_bi4']:
                        assert digest==load(q['prepared_input_report'])['bi4_sha256']
                    else:
                        assert n['input_hashes_at_launch'].get(str(path.resolve()))==digest
                        assert n['input_hashes_after_run'].get(str(path.resolve()))==digest
                    payload_attestations.append({'path':p,'sha256_producer_attested':digest,'main_read_or_hash':False})
                else:
                    assert q['input_sha256_categories'][p]=='registered_binary_attestation'
            md[p]=digest
    for p in [controller,fair,source,O/'actual-source165-independent-validator.json']:
        md[str(p)]=sha(p)
    aid='root-stage1-f5-'+q['tag'].lower()+'-actual-native0-full801-typed157-home4gib-root982'
    ar=D/'families/F5'/q['case_id']/aid
    assert not ar.exists()
    staging='/tmp/ds02-nvme-typed-cache-root982-'+q['tag'].lower()
    assert not Path(staging).exists()
    cmd[cmd.index('--staging-root')+1]=staging
    current=f"F5/{q['case_id']}/{aid}"
    cmd[cmd.index('--current-attempt-id')+1]=current
    q.update({k:base[k] for k in ['root_dataset_inventory_profile','root_inventory_policy_sha256',
        'root_actual_launch_source','root_actual_launch_source_sha256','environment_policy']})
    q.update(attempt_id=aid,attempt_root=str(ar),current_attempt_id=current,command=cmd,
        input_files=sorted(md),input_sha256=md,worktree_root=str(R),
        disabled=False,source_only=False,launch=True,launch_allowed=True,execution_allowed=True,
        conversion_allowed=True,arrays_allowed=True,root_review_required=False,
        root_source_request=ref(source),root_source_provenance_directories=directories,
        expected_converter_scope_sha256=legacy,
        root_prospective_legacy_scope_sha256=legacy,
        root_converter_scope_is_prospective_owner_metadata_hash_not_future_H5_digest=True,
        estimated_storage_bytes=4*1024**3,cpu_threads=2,cpu_task_kind='conversion',case_credit=0,
        input_sha256_categories={p:q['input_sha256_categories'].get(p,'root_metadata_current_hash') for p in md},
        input_sha256_provenance={p:q['input_sha256_provenance'].get(p,'Primary registered immutable metadata/source SHA') for p in md})
    qp=O/'requests'/(q['tag']+'-enabled-typed-request.json')
    put(qp,q);enabled.append(str(qp))
    rows.append({'tag':q['tag'],'physical_case_id':q['physical_case_id'],
        'source_canonical_scope':q['physical_condition_sha256'],
        'source_plan_scope':q['source_plan_physical_condition_sha256'],
        'prospective_unchanged_converter_scope':legacy,
        'historical_source_h5_legacy_scope_preserved_not_expected_current_output':q['source_h5_legacy_scope'],
        'scope_roles_separate':True,'native_receipt':ref(q['actual_native_dependency']['receipt']),
        'initial_QA_receipt':ref(q['actual_initial_qa_receipt']),
        'native_full801_filename_count':801,'producer_attestations':payload_attestations,
        'directories_preserved_as_provenance_not_runtime_input_files':directories,
        'enabled_request':ref(qp),'future_output_hashes':q['future_output_hashes']})
assert len(enabled)==12
put(O/'controller-config.json',{'requests':enabled,'request_sha256':{p:sha(p) for p in enabled},
    'fair_dispatch':ref(fair),'effective_shared_serial_conversion_concurrency':1,
    'cooperative_yield_between_admitted_jobs_seconds':4,'case_credit':0})
put(O/'source165-adoption-and-primary-12case-metadata-review.json',{
    'source_commit':commit,'adopted_files':adopted,'cases':rows,
    'prior_unlaunched_primary_scope_role_assertion_failure_preserved':ref(root(980)/'aborted-unlaunched-preparation-classification.json'),
    'all12_actual_native0_initial_QA0_GenCase0_full801':True,
    'accepted205_and_pending_M095T080_M086T085_excluded':True,
    'source_package_validator_report_not_overwritten':source_report_before,
    'runtime_files_only_guard':'Source directory references retained separately as provenance; enabled strict runtime input_files contain actual immutable files only. Runtime source and all checks unchanged.',
    'science_payload_IO_by_primary':False,'future_scientific_product_hashes_null':True,
    'numeric_precision_negatives_preserved':True,'q_n_granted':False,'q_e_granted':False,
    'case_credit':0,'Home_floor_GiB':500,'per_output_cap_GiB':4})
(O/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
paths=[str(Path(z['path']).relative_to(R)) for z in adopted]+[str(p.relative_to(R)) for p in O.rglob('*') if p.is_file()]
subprocess.run(['git','add','--',*paths],cwd=R,check=True)
subprocess.run(['git','commit','-q','-m','ds02: register twelve distinct full801 F5 native cases for capped typed157 conversion','--',*paths],cwd=R,check=True)
print({'root':str(O),'enabled_cases':12,'source_files':len(adopted),
    'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()})
