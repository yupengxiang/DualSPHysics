"""Bind the exact auxiliary copies consumed by one owner-grid GenCase argv.

Preparation reads bounded metadata and small controls only. Large forcing
copies carry the frozen owner SHA into runtime input_files so that the
reserved runtime hashes each actual copy before and after GenCase.
"""
from pathlib import Path
import importlib.util
import json
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')


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
    admission = module(S / 'governance/root-owned-native-admission-v1/continue_after_serial_v1.py', 'owner_grid_metadata_admission')
    q = admission.load(source)
    assert q['cpu_task_kind'] == 'gencase' and q['cpu_threads'] == 1
    assert q['source_only'] and q['launch_disabled']
    definition = Path(q['source_binding']['candidate_def']['path'])
    assert admission.sha(definition) == q['source_binding']['candidate_def']['sha256']
    assert q['command'][1] == str(definition.with_suffix(''))
    tree = ET.fromstring(definition.read_bytes())
    auxiliary_nodes = list(tree.iter('acctimesfile')) + list(tree.iter('file'))
    assert len(auxiliary_nodes) == 1
    node = auxiliary_nodes[0]
    relative = node.get('value') if node.tag == 'acctimesfile' else node.get('name')
    assert relative and not Path(relative).is_absolute()
    auxiliary = (Path(q['cwd']) / relative).absolute()
    original = Path(q['source_binding']['motion_or_forcing']['path']).absolute()
    expected = q['source_binding']['motion_or_forcing']['sha256']
    assert len(expected) == 64
    deferred = {}
    controls = []
    for path in dict.fromkeys([original, auxiliary]):
        assert path.is_file() and not path.is_symlink()
        record = stat_record(path)
        large = record['bytes'] > 10485760
        if large:
            assert q['sentinel_id'] == 'F3-S1' and record['bytes'] == 14919771
            deferred[str(path)] = expected
        else:
            assert admission.sha(path) == expected
        controls.append(dict(path=str(path), sha256=expected, stat=record,
                             root_content_read=not large, actual_parent_prepost_hash_required=True))
        if str(path) not in q['input_files']:
            q['input_files'].append(str(path))
    q['input_hashes'].update({row['path']: row['sha256'] for row in controls})
    q['input_sha256'].update({row['path']: row['sha256'] for row in controls})
    q['attempt_id'] = f'root{namespace}-{q["sentinel_id"].lower()}-{q["grid_label"]}-gencase-after321-001'
    final_attempt = q['attempt_id'] + '-root-forward-030-001'
    output_root = D / 'families' / q['family_id'] / q['case_id'] / final_attempt
    q.update(source_only=False, launch_disabled=False, execution_allowed=True,
             status='READY_ROOT_EXACT_AUXILIARY_RUNTIME_CLOSURE', output_root=str(output_root),
             planned_output_root=str(output_root), root_rebind_required=False)
    q['output'] = dict(q['output'], root=str(output_root), prefix=str(output_root / 'generated'))
    for record in q['output']['products'].values():
        record['path'] = str(output_root / Path(record['path']).name)
    q['gencase_receipt_contract']['output_root'] = str(output_root)
    q['runtime_v8_contract'].update(static_input_files_exclude_deferred_controls=False,
                                   exact_auxiliary_copies_in_runtime_input_files=True,
                                   root_stat_only_large_control_paths=sorted(deferred))
    q['root_exact_auxiliary_closure'] = controls
    q['preceding_actual_serial_handoff'] = admission.ref(predecessor)
    q['root_canonical_gencase_binding'] = dict(namespace=namespace, source_request=admission.ref(source),
        scientific_Q_credit=0, auxiliary_xml_path=relative, auxiliary_resolved_path=str(auxiliary),
        actual_runtime_prepost_content_hash_required=True, generated_payload_read_by_root=False)
    if dry_run:
        q['status'] = 'DIAGNOSTIC_DRY_RUN_NO_REQUEST_WRITTEN_OR_LAUNCH_ALLOWED'
        q.update(execution_allowed=False, launch_disabled=True, source_only=True)
        return dict(request_preview=q, root_stat_only_deferred=deferred,
                    request_written=False, actual_parent_launched=False)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__name__': 'root_owner_grid_actual_forward', '__file__': str(forward)}
    exec(forward.read_text(), context)
    context['sha'] = admission.sha
    name = f'owner-grid-gencase-v2-root-forward-{namespace}-after321-001.json'
    context['write'](q, source, name, extra=[Path(__file__), predecessor, *extra], deferred=deferred)
    destination = S / 'requests' / name
    bound = admission.load(destination)
    assert bound['attempt_id'] == final_attempt and bound['output_root'] == str(output_root)
    assert set(deferred) <= set(bound['input_files'])
    return destination
