#!/usr/bin/env python3
"""Normalize the concrete F6 V8 support source without payload reads or launch."""
from pathlib import Path
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
STAGE = LAB / 'campaigns/ds-data-02/stage2'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD
    assert path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = STAGE / 'requests/source-prepared276v8-primary-001/source-request-v8.json'
    q = json.loads(source.read_text())
    manifest = Path(q['command'][q['command'].index('--manifest') + 1])
    m = json.loads(manifest.read_text())
    assert m['schema'] == 'ds02.stage2.f6-initial-native-support-manifest.v8'
    assert len(m['cases']) == 6
    assert '--run' in q['command'] and '-B' in q['command']
    deferred = q['deferred_input_records']
    assert len(deferred) == 18
    assert {r['path'] for r in deferred} == set(q['deferred_input_files'])
    for r in deferred:
        p = Path(r['path']); assert not p.is_symlink()
        s = p.stat()
        current = dict(dev=s.st_dev, ino=s.st_ino, bytes=s.st_size,
                       mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns)
        assert current == r['stat_at_prepare'], p
    extra = [Path(__file__), STAGE / 'reference/stage2_f6_initial_native_support_audit_request_v8.py',
             STAGE / 'reference/stage2_native_physical_observer_v2.py',
             STAGE / 'reference/stage2_f1_native_selected_observer_v1.py',
             STAGE / 'checkpoints/ALL336_EFFECTIVE_CONDITION_UNION_V28_ACTUAL_ROOT_VERIFICATION_241.json',
             STAGE / 'checkpoints/F6_INITIAL_NATIVE_SUPPORT_V5_ACTUAL_PRODUCER_IDENTITY_FAILURE_ROOT_VERIFICATION_272.json',
             Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg'),
             Path('/usr/bin/python3.10')]
    for case in m['cases']:
        extra.extend([Path(case['decoder']['path']), Path(case['decoder_source']['path'])])
    source_resources = q.pop('resources')
    assert source_resources['cpu_threads'] == 1
    q['root_source_resource_declaration'] = source_resources
    q.update(schema='ds02.request.v1', shared_runtime_version='v8', kind='cpu',
             cpu_task_kind='audit', cpu_threads=1, omp_threads=1, cwd=str(LAB),
             worktree_root=str(LAB.parent), max_wall_seconds=3600,
             max_memory_bytes=2147483648, estimated_storage_bytes=1073741824,
             estimated_hdf5_read_bytes=0, launch_allowed=True, launch_disabled=False,
             execution_allowed=True, qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['manifest_contract'] = {'path': str(manifest), 'sha256': sha(manifest)}
    q['root_canonical_binding'] = {
        'namespace': 276, 'source_request': str(source), 'source_sha256': sha(source),
        'immutable_manifest_direct_path': str(manifest),
        'deferred_file_count': 18, 'deferred_stat_bytes': sum(r['bytes'] for r in deferred),
        'fresh_resource_and_nonoverlap_check_required': True,
        'launch_performed': False, 'payload_content_read': False,
        'parent_V8_is_sole_resource_owner': True,
    }
    forward = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_support_metadata_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    output = STAGE / 'requests/reference-audit-root-forward-276-001.json'
    context['write'](q, source, output.name, extra=extra)
    saved = json.loads(output.read_text())
    sys.path.insert(0, str(LAB / 'scripts'))
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(saved, data_root=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02'))
    for path, digest in saved['input_sha256'].items():
        assert sha(path) == digest, path
    print(json.dumps({'namespace': 276, 'request': str(output), 'sha256': sha(output),
                      'static_inputs': len(saved['input_files']), 'deferred_files': 18,
                      'payload_content_read': False, 'launch_performed': False}))


if __name__ == '__main__':
    main()
