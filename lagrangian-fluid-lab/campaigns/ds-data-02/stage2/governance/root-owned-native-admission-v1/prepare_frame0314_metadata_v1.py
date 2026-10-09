#!/usr/bin/env python3
"""Parent admission metadata for four source-bound native frame-zero audits."""
from pathlib import Path
import hashlib
import json

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
    source = STAGE / 'requests/root314-four-sentinel-frame0-source-v2-prepared-001/source-request.json'
    q = json.loads(source.read_text())
    assert q['family_id'] == 'DS02-MULTI'
    manifest = Path(q['manifest']['path'])
    assert sha(manifest) == q['manifest']['sha256']
    m = json.loads(manifest.read_text())
    assert {c['sentinel_id'] for c in m['cases']} == {'F2-S2', 'F4-S2', 'F5-S2', 'F7-S1'}
    assert len(m['cases']) == 4 and len(q['deferred_input_records']) == 4
    assert set(q['deferred_input_files']) == {r['path'] for r in q['deferred_input_records']}
    for r in q['deferred_input_records']:
        p = Path(r['path']); assert not p.is_symlink() and p.name == 'Part_0000.bi4'
        s = p.stat()
        assert r['stat'] == dict(device=s.st_dev, inode=s.st_ino, bytes=s.st_size,
                                 mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns), p
    resources = q.pop('resources')
    assert resources['cpu_threads'] == 1 and resources['memory_max_bytes'] == 2147483648
    q['source_family_id'] = q['family_id']
    q['root_source_resource_declaration'] = resources
    assert '-B' not in q['command']
    q['command'].insert(1, '-B')
    q.update(family_id='infra', shared_runtime_version='v8', kind='cpu', cpu_task_kind='audit',
             cpu_threads=1, omp_threads=1, max_wall_seconds=1800, max_memory_bytes=2147483648,
             estimated_storage_bytes=536870912, estimated_hdf5_read_bytes=0,
             cwd=str(LAB), worktree_root=str(LAB.parent), launch_allowed=True, execution_allowed=True,
             qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['deferred_input_policy']['parent_v8_hashes_deferred'] = False
    q['deferred_input_policy']['first_content_read'] = 'reserved worker pre-hash; core v8 does not hash deferred inputs'
    q['manifest_contract'] = {'path': str(manifest), 'sha256': sha(manifest)}
    q['root_canonical_binding'] = {
        'namespace': 314, 'source_request': str(source), 'source_sha256': sha(source),
        'four_exact_source_XML_receipt_SHA_joins_required': True,
        'partial_identity_not_reconstructed': True, 'owner_geometry_world_Q': 'UNKNOWN',
        'fresh_resource_and_nonoverlap_check_required': True,
        'payload_content_read': False, 'launch_performed': False,
    }
    extra = [Path(__file__), STAGE / 'reference/stage2_four_sentinel_frame0_support_audit_request_v2.py',
             STAGE / 'CURRENT336.json',
             Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg'),
             Path('/usr/bin/python3.10')]
    forward = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_frame0_metadata_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = sha
    output = STAGE / 'requests/four-sentinel-frame0-audit-root-forward-314-001.json'
    context['write'](q, source, output.name, extra=extra)
    saved = json.loads(output.read_text())
    for path, digest in saved['input_sha256'].items():
        assert sha(path) == digest, path
    print(json.dumps({'namespace': 314, 'request': str(output), 'sha256': sha(output),
                      'cases': 4, 'deferred_files': 4, 'static_inputs': len(saved['input_files']),
                      'payload_content_read': False, 'launch_performed': False}))


if __name__ == '__main__':
    main()
