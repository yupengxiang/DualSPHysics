"""Root metadata admission: preserve known payload hashes and seal the actual argv."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
sys.path.insert(0, str(LAB / 'scripts'))
from ds_data02_runtime_v8 import _light_validate
from external_storage_v1 import small


def prepare():
    source = S / 'requests/root242-v11-primary-source-prepared-001/root242-v11-parent-request.json'
    out = S / 'requests/portable-typed-root242-v11-root-forward-242-001.json'
    assert not out.exists()
    q, source_sha = small(source)
    contract = Path(q['root213_metadata_contract']['path'])
    m, _ = small(contract)
    roles = m['root242_source_binding']['roles']
    deferred = {r['source_path_provenance']: r['source_sha256'] for r in roles if r['deferred_content']}
    assert len(deferred) == 3
    for r in roles:
        p = Path(r['source_path_provenance']); z = p.stat(); expect = r['source_stat_provenance']
        actual = {'bytes': z.st_size, 'mode_bits': z.st_mode & 0o7777, 'mtime_ns': z.st_mtime_ns,
                  'ctime_ns': z.st_ctime_ns, 'st_dev': z.st_dev, 'st_ino': z.st_ino}
        assert all(actual[k] == v for k, v in expect.items()), r['logical_role']
    root = Path(q['storage_scope']['external_filesystem'])
    assert not root.exists()
    q['worktree_root'] = str(LAB.parent)
    q['cwd'] = str(LAB)
    q['cpu_threads'] = q['omp_threads'] = 1
    q['max_memory_bytes'] = 16 * 1024**3
    q['max_wall_seconds'] = 900
    q['estimated_storage_bytes'] = 16 * 1024**3
    q['root_external_storage_accounting'] = {
        'same_parent_atomic_reservation_bytes': q['estimated_storage_bytes'],
        'home_reserved_bytes': 4 * 1024**3, 'external_reserved_bytes': 12 * 1024**3,
        'external_free_floor_bytes': 16 * 1024**3,
        'external_actual_fee': 'STAT_ONLY_SUPPLEMENT_UNDER_EXISTING_PARENT_LEDGER_LOCK',
        'failed_partial_copy_accounted': True, 'repeat_fee_idempotent_required': True}
    code = ('import sys,os,json;sys.path.insert(0,' + repr(str(LAB / 'scripts')) + ');'
            'from ds_data02_stage2_f2_root242_portable_typed_executor_v11 import run;'
            'r=run(request=' + repr(str(out)) + ',output_root=' + repr(str(root)) +
            ',parent_pid=os.getppid(),max_wall_seconds=900);print(json.dumps(r))')
    q['command'] = [PYTHON, '-B', '-I', '-c', code]
    extras = [source, Path(__file__), HERE / 'parent_entry_v1.py', HERE / 'external_storage_v1.py',
              HERE / 'verify_actual_v1.py', HERE / 'launch_v1.py',
              S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
              S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py']
    extras += [LAB / 'scripts' / x for x in ('ds_data02_runtime_v2.py', 'ds_data02_runtime_v6.py',
               'ds_data02_runtime_v8.py', 'ds_data02_batch_runner.py', 'ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py')]
    q['input_files'] = list(dict.fromkeys(q['input_files'] + list(map(str, extras))))
    # The source template retains a historical input_hashes provenance map;
    # input_sha256 is its exact selected input_files closure.
    old = q['input_sha256']; assert set(old) == set(q['input_files']) - set(map(str, extras)) or set(old).issubset(q['input_files'])
    hashes = {}
    for raw in q['input_files']:
        p = Path(raw)
        if raw in deferred:
            hashes[raw] = deferred[raw]
            assert old[raw] == hashes[raw]
        else:
            assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.jsonl'} and p.stat().st_size <= 10485760
            hashes[raw] = hashlib.sha256(p.read_bytes()).hexdigest()
            if raw in old:
                assert old[raw] == hashes[raw], raw
    q['input_hashes'] = q['input_sha256'] = hashes
    q['runtime_binding'] = {'path': str(LAB / 'scripts/ds_data02_runtime_v8.py'),
                            'sha256': hashes[str(LAB / 'scripts/ds_data02_runtime_v8.py')]}
    q['root_forward_provenance'] = {'source_request': str(source), 'source_request_sha256': source_sha,
        'deferred_payload_content_read_by_root': False, 'actual_hash_phase': 'PARENT_AFTER_ATOMIC_RESERVATION',
        'external_storage_accounting_required': True, 'scientific_Q': 'UNKNOWN'}
    canonical = dict(q); canonical.pop('sha256', None)
    q['sha256'] = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    _light_validate(q, data_root=D)
    with out.open('x') as f:
        json.dump(q, f, indent=2, sort_keys=True); f.write('\n')
    spec = importlib.util.spec_from_file_location('root242_admitted_builder_v11', LAB / 'scripts/ds_data02_stage2_f2_root242_v11_source_request.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = module.validate_request(request=out, contract=contract)
    print(json.dumps(result))


if __name__ == '__main__':
    prepare()
