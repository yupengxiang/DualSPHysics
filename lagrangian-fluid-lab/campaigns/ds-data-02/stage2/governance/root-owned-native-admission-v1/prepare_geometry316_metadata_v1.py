#!/usr/bin/env python3
"""Close the parent metadata inputs for four GenCase VTK diagnostics."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
STAGE = LAB / 'campaigns/ds-data-02/stage2'
PAYLOAD = {'.h5', '.hdf5', '.bi4', '.obi4', '.ibi4', '.vtk', '.vtu', '.jsonl'}


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in PAYLOAD and path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = STAGE / 'requests/root316-geometry-support-primary-source-001/source-request.json'
    q = json.loads(source.read_text()); assert q['family_id'] == 'DS02-MULTI'
    manifest = Path(q['manifest']['path']); assert sha(manifest) == q['manifest']['sha256']
    assert len(q['cases']) == 4 and len(q['deferred_input_records']) == 12
    assert {c['sentinel_id'] for c in q['cases']} == {'F2-S2', 'F4-S2', 'F5-S2', 'F7-S1'}
    for case in q['cases']:
        assert case['continuous_owner']['status'] in {'UNKNOWN_CONTINUOUS_OWNER', 'UNVERIFIED_CROSS_SENTINEL_TARGET'}
    records = q['deferred_input_records']
    for r in records:
        p = Path(r['path']); assert not p.is_symlink()
        s = p.stat()
        assert r['stat_at_build'] == dict(device=s.st_dev, inode=s.st_ino, bytes=s.st_size,
                                          mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns), p
    assert sum(Path(r['path']).suffix.lower() == '.vtk' for r in records) == 8
    assert sum(Path(r['path']).suffix.lower() == '.bi4' for r in records) == 4
    q['deferred_input_files'] = [r['path'] for r in records]
    q['source_family_id'] = q['family_id']
    assert '-B' not in q['command']; q['command'].insert(1, '-B')
    q.update(family_id='infra', shared_runtime_version='v8', kind='cpu', cpu_task_kind='audit',
             cpu_threads=1, omp_threads=1, max_wall_seconds=1800, max_memory_bytes=4294967296,
             estimated_storage_bytes=1073741824, estimated_hdf5_read_bytes=0,
             cwd=str(LAB), worktree_root=str(LAB.parent), launch_allowed=True, execution_allowed=True,
             qualification={'QI': 'UNKNOWN', 'QN': 'UNKNOWN', 'QE': 'UNKNOWN'})
    q['manifest_contract'] = {'path': str(manifest), 'sha256': sha(manifest)}
    q['root_canonical_binding'] = {'namespace': 316, 'source_request': str(source),
                                   'source_sha256': sha(source), 'payload_content_read': False, 'launch_performed': False,
                                   'fresh_resources_and_nonoverlap_required': True,
                                   'cross_sentinel_owner_target': 'UNVERIFIED_NOT_S2_FAILURE_OR_QUALIFICATION'}
    q['root_deferred_scope'] = {'VTK_file_count': 8, 'VTK_stat_bytes': sum(r['stat']['bytes'] for r in records if Path(r['path']).suffix.lower() == '.vtk'),
                               'BI4_stat_only_count': 4, 'BI4_content_read': False,
                               'core_v8_hashes_deferred': False, 'first_payload_read': 'reserved worker stable captured byte image'}
    forward = STAGE / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_geometry_metadata_forward', '__file__': str(forward)}
    exec(forward.read_text(), context); context['sha'] = sha
    output = STAGE / 'requests/four-sentinel-geometry-audit-root-forward-316-001.json'
    context['write'](q, source, output.name, extra=[Path(__file__),
                     STAGE / 'reference/stage2_four_sentinel_gencase_geometry_support_audit_request_v1.py',
                     STAGE / 'reference/stage2_four_sentinel_gencase_geometry_admission_v1.py',
                     STAGE / 'CURRENT336.json', Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg'),
                     Path('/usr/bin/python3.10')])
    print(json.dumps({'namespace': 316, 'request': str(output), 'sha256': sha(output),
                      'cases': 4, 'VTK_payload_files': 8, 'BI4_stat_only': 4,
                      'owner_Q': 'UNKNOWN', 'payload_content_read': False, 'launch_performed': False}))


if __name__ == '__main__':
    main()
