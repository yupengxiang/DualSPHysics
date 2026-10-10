"""Bind existing controls and the reserved staged worker to fresh runtime requests."""
from pathlib import Path
import importlib.util
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def stat_record(path):
    value = Path(path).stat()
    return dict(bytes=value.st_size, mtime_ns=value.st_mtime_ns,
                ctime_ns=value.st_ctime_ns, st_dev=value.st_dev, st_ino=value.st_ino)


def prepare(source, namespace, predecessor, extra=(), *, dry_run=False):
    admission = module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'grid_v2_admission')
    source_q = admission.load(source)
    assert source_q['source_only'] and source_q['launch_disabled']
    staged = source_q['sentinel_id'] == 'F3-S1'
    deferred = {}
    if staged:
        q = source_q
        assert q['request_variant'] == 'three-sentinel-owner-grid-gencase-producer-f3force-staged-v3'
        assert q['command'][0] == PYTHON
        worker = S / 'reference/stage2_three_sentinel_owner_grid_f3_staged_gencase_worker_v3.py'
        assert q['command'][1] == str(worker)
        assert admission.sha(worker) == q['staged_gencase_worker']['worker_path']['sha256']
        owner = q['staged_gencase_worker']['owner_forcing']
        original = Path(owner['path'])
        assert original.is_file() and not original.is_symlink()
        assert original.stat().st_size == owner['bytes'] == 14919771
        assert owner['sha256'] == 'a4afb8a99ba1e7404b2892b84a2d2b293b11653d792a118867abfaec6593fb48'
        expected_stat = owner['stat_after']
        actual_stat = stat_record(original)
        assert actual_stat == dict(bytes=expected_stat['bytes'], mtime_ns=expected_stat['mtime_ns'],
            ctime_ns=expected_stat['ctime_ns'], st_dev=expected_stat['device'], st_ino=expected_stat['inode'])
        assert str(original) in q['input_files'] and q['input_sha256'][str(original)] == owner['sha256']
        deferred[str(original)] = owner['sha256']
        candidate = q['staged_gencase_worker']['candidate_def']
        definition = Path(candidate['path'])
        assert admission.sha(definition) == candidate['sha256']
        nodes = list(ET.fromstring(definition.read_bytes()).iter('acctimesfile'))
        assert len(nodes) == 1 and nodes[0].get('value') == 'CaseSloshingAccData.csv'
        controls = [dict(path=str(original), sha256=owner['sha256'], stat=actual_stat,
                         root_content_read=False, actual_parent_prepost_hash_required=True)]
        q['physical_case_id'] = q['case_id']
        q['row_key'] = q['sentinel_id'] + ':' + q['grid_label']
    else:
        old = module(S / 'governance/root-owned-owner-grid-admission-v1/prepare_actual_gencase_v1.py', 'grid_v2_motion_preflight')
        preview = old.prepare(source, namespace, predecessor, dry_run=True)
        q = preview['request_preview']
        assert q['sentinel_id'] in {'F2-S2', 'F5-S1'}
        assert not preview['root_stat_only_deferred']
        controls = q['root_exact_auxiliary_closure']
    q['attempt_id'] = f'root{namespace}-{q["sentinel_id"].lower()}-{q["grid_label"]}-gencase-v3-after321-001'
    final_attempt = q['attempt_id'] + '-root-forward-030-001'
    output_root = D / 'families' / q['family_id'] / q['case_id'] / final_attempt
    destination = S / f'requests/owner-grid-gencase-v3-root-forward-{namespace}-after321-001.json'
    assert not destination.exists() and not output_root.exists()
    q.update(cpu_task_kind='gencase', cpu_threads=1, omp_threads=1,
        max_memory_bytes=4294967296, max_wall_seconds=1800,
        cwd=str(LAB.parent) if staged else q['cwd'], worktree_root=str(LAB.parent),
        source_only=False, launch_disabled=False, execution_allowed=True,
        status='READY_ROOT_OWNER_GRID_V3_EXACT_RUNTIME_CLOSURE',
        output_root=str(output_root), planned_output_root=str(output_root), root_rebind_required=False)
    if staged:
        q['command'] = [arg.replace('{request_path}', str(destination)) for arg in q['command']]
        q['estimated_storage_bytes'] = 8589934592
        q['estimated_storage_status'] = 'CONSERVATIVE_STAGED_GENCASE_OUTPUT_RESERVATION_NOT_MEASURED_SIZE'
    assert 0 < q['estimated_storage_bytes'] <= 8589934592
    names = dict(generated_xml='generated.xml', fluid_vtk='generated_Fluid.vtk',
                 bound_vtk='generated_Bound.vtk', native_bi4='generated.bi4',
                 gencase_receipt='execution-receipt.json')
    q['output'] = dict(root=str(output_root), prefix=str(output_root / 'generated'),
        products={key: dict(path=str(output_root / name)) for key, name in names.items()})
    q['gencase_receipt_contract'] = dict(output_root=str(output_root), schema='ds02.execution-receipt.v1')
    q['root_exact_auxiliary_closure'] = controls
    q['preceding_actual_serial_handoff'] = admission.ref(predecessor)
    q['root_canonical_gencase_binding'] = dict(namespace=namespace, source_request=admission.ref(source),
        staged_worker=staged, exact_auxiliary_prepost_required=True, scientific_Q_credit=0,
        staged_copies_not_in_runtime_static_inputs=True if staged else None,
        runtime_existing_original_forcing_source_hash_required=staged,
        staged_worker_report='{attempt_root}/report/f3-staged-gencase-worker-v1.json' if staged else None,
        generated_payload_read_by_root=False)
    if dry_run:
        q.update(source_only=True, launch_disabled=True, execution_allowed=False,
                 status='DIAGNOSTIC_ROOT_V3_PREVIEW_NO_WRITE_NO_LAUNCH')
        return dict(request_preview=q, root_stat_only_deferred=deferred,
                    request_written=False, actual_parent_launched=False)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_owner_grid_v3_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    context['write'](q, source, destination.name, extra=[Path(__file__), predecessor, *extra], deferred=deferred)
    bound = admission.load(destination)
    assert bound['attempt_id'] == final_attempt and bound['output_root'] == str(output_root)
    assert set(deferred) <= set(bound['input_files'])
    assert all('{request_path}' not in value for value in bound['command'])
    return destination
