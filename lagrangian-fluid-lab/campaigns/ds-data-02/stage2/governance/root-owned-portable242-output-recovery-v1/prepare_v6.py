"""Seal a fresh V13 portable request without reading deferred source content."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

HERE=Path(__file__).resolve().parent
S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
sys.path.insert(0,str(S/'governance/root-owned-portable-admission-v1'))
from external_storage_v1 import small

def sha(p):
    p=Path(p);assert (not p.is_symlink() or (str(p)==PY and str(p.resolve())=='/usr/bin/python3.10')) and p.stat().st_size<=10485760
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
    return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare():
    scripts=LAB/'scripts';sys.path.insert(0,str(scripts))
    import ds_data02_stage2_f2_root242_v15_recursive_source_request as builder
    old=S/'requests/portable-typed-root242-v13-root-forward-242-004.json';oq,_=small(old)
    outdir=S/'requests/root242-v15-list-string-primary-prepared-006'
    source=outdir/'source-parent-request.json';contract=outdir/'source-contract.json'
    case='STAGE2_F2_ROOT242_V15_LIST_STRING_20261010_R006'
    attempt='f2-s1-root242-v15-list-string-root-forward-242-006'
    root=Path('/var/tmp/STAGE2_F2_ROOT242_V15_LIST_STRING_ROOT_006')
    assert not root.exists() and not (D/'families/F2'/case/attempt).exists()
    builder.build_request(source_contract=oq['root213_metadata_contract']['path'],source_request=old,preflight_report=S/'checkpoints/ROOT242_V15_ACTUAL_METADATA_RECURSIVE_SOURCE_PREFLIGHT_V1.json',
        output_contract=contract,output_request=source,fresh_root=root,
        home_receipt=D/'families/F2'/case/attempt/'execution-receipt.json',case_id=case,attempt_id=attempt,
        primary_scripts_root=LAB.parent)
    q,_=small(source);c,_=small(contract)
    roles=c['root242_source_binding']['roles'];assert len(roles)==491
    assert len(roles)==q['root242_v14_preflight_binding']['role_count']+2
    deferred={r['source_path_provenance']:r for r in roles if r['deferred_content']};assert len(deferred)==410
    out=S/'requests/portable-typed-root242-v15-root-forward-242-006.json'
    q['cwd']=str(LAB);q['worktree_root']=str(LAB.parent)
    q['cpu_threads']=q['omp_threads']=1;q['max_wall_seconds']=1800;q['max_memory_bytes']=16*1024**3
    q['estimated_storage_bytes']=36*1024**3
    q['root_external_storage_evidence']={'path':str(S/'accounting/root242-v15-list-string-external-storage-evidence-v1.json'),'version':'fresh-v15-attempt'}
    q['root_external_storage_accounting']=dict(oq['root_external_storage_accounting'])
    q['root_external_storage_accounting']['external_reserved_bytes']=32*1024**3
    q['root_external_storage_accounting']['same_parent_atomic_reservation_bytes']=q['estimated_storage_bytes']
    q['root_external_storage_accounting']['home_reserved_bytes']=4*1024**3
    q['storage_scope']['external_reservation_bytes']=32*1024**3
    q['storage_scope']['home_reservation_bytes']=4*1024**3
    q['storage_scope']['home_receipt_reserved_bytes']=4*1024**3
    q['storage_scope']['estimated_storage_bytes']=q['estimated_storage_bytes']
    assert q['root_external_storage_accounting']['home_reserved_bytes']+q['root_external_storage_accounting']['external_reserved_bytes']==q['estimated_storage_bytes']
    q['storage_scope']['external_storage_bytes']=32*1024**3
    q['estimated_peak_memory_bytes']=q['max_memory_bytes']
    code='import sys,os,json;sys.path.insert(0,'+repr(str(scripts))+');from ds_data02_stage2_f2_root242_portable_typed_executor_v14 import run;r=run(request='+repr(str(out))+',output_root='+repr(str(root))+',parent_pid=os.getppid(),max_wall_seconds=1800);print(json.dumps(r))'
    q['command']=[PY,'-B','-I','-c',code]
    extras=[source,old,Path(__file__),HERE/'parent_entry_v4.py',HERE/'launch_v5.py',HERE/'verify_v5.py',HERE/'continue_v7.py',
        S/'checkpoints/ROOT242_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json',
        S/'checkpoints/ROOT242_V13_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json',
        S/'checkpoints/ROOT242_V15_ACTUAL_METADATA_RECURSIVE_SOURCE_PREFLIGHT_V1.json',
        scripts/'ds_data02_stage2_f2_root242_recursive_source_preflight_v14.py',
        scripts/'ds_data02_stage2_f2_root242_portable_typed_executor_v14.py',
        S/'checkpoints/GEOMETRY_SUPPORT_ACTUAL_ROOT_VERIFICATION_316.json',
        scripts/'ds_data02_stage2_f2_root242_v15_recursive_source_request.py',
        scripts/'ds_data02_stage2_f2_typed_only_portable_rebind_v15.py',
        S/'checkpoints/ROOT242_V14_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json',
        scripts/'ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py']
    extras += [scripts/name for name in ['ds_data02_runtime_v8.py','ds_data02_runtime_v6.py','ds_data02_runtime_v2.py','ds_data02_batch_runner.py']]
    extras += [S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py', S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py', S/'governance/root-owned-portable-admission-v1/external_storage_v1.py', S/'governance/root-owned-portable-admission-v1/verify_actual_v1.py']
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    hashes={}
    for raw in q['input_files']:
        if raw in deferred:
            assert q['input_sha256'][raw]==deferred[raw]['source_sha256']
            hashes[raw]=deferred[raw]['source_sha256']
        else:
            hashes[raw]=sha(raw)
            if raw in q['input_sha256']:assert hashes[raw]==q['input_sha256'][raw],raw
    q['input_hashes']=q['input_sha256']=hashes
    q['runtime_binding']={'path':str(scripts/'ds_data02_runtime_v8.py'),'sha256':hashes[str(scripts/'ds_data02_runtime_v8.py')]}
    q['root_output_slot_retry_provenance']={'failed_request':str(old),'failed_request_sha256':sha(old),'source_request':str(source),'source_request_sha256':sha(source),'old_partial_copy_preserved':True,'root_payload_content_read':False,'scientific_Q':'UNKNOWN'}
    q['root242_v15_runtime_forward']={'source':str(scripts/'ds_data02_stage2_f2_typed_only_portable_rebind_v15.py'),'sha256':sha(scripts/'ds_data02_stage2_f2_typed_only_portable_rebind_v15.py'),'consumed_target_role':'portable_rebind_v2_entrypoint','copied_launcher_version':14,'runtime_rebinder_version':15,'previous_failed_v14':str(S/'checkpoints/ROOT242_V14_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json')}
    canonical=dict(q);canonical.pop('sha256',None)
    q['sha256']=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q,data_root=D)
    with out.open('x') as f:json.dump(q,f,indent=2,sort_keys=True);f.write('\n')
    checked=builder.validate_request(request=out,contract=contract)
    print(json.dumps({'request':str(out),'request_sha256':sha(out),'status':checked['status'],'role_count':491,'root_payload_content_read':False}))
    return out

if __name__=='__main__':prepare()
