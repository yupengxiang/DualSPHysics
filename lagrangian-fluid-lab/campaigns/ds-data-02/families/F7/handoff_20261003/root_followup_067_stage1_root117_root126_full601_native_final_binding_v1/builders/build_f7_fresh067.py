#!/usr/bin/env python3
"""Build F7 fresh067 by rebinding fresh066 to Root117/Root126 evidence.

This builder reads bounded JSON/XML metadata and hashes opaque metadata files.
It never opens BI4/H5/CSV arrays and never launches a job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

F7WT = Path('/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics')
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
H = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
SOURCE = F7WT / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_066_stage1_actual_gencase_qa_native_v1'
SCOPE = 'root_followup_067_stage1_root117_root126_full601_native_final_binding_v1'
FINAL = F7WT / f'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/{SCOPE}'
ROOT117 = H / 'root_stage1_f7_first8_actual_genuine_gencase_117'
ROOT126 = H / 'root_stage1_f7_actual_initial_qa_source_lexical_repair_126'
CASES = [
    'F7_OBSTACLE_QUINTIC_B08_A035',
    'F7_OBSTACLE_QUINTIC_B08_A040',
    'F7_OBSTACLE_QUINTIC_B08_A050',
    'F7_OBSTACLE_QUINTIC_B08_A055',
    'F7_OBSTACLE_QUINTIC_B08_A060',
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def data_attempt(case: str) -> Path:
    return DATA / 'families/F7/F7_STAGE1_FIRST8_TARGET_ANGLES/root-stage1-f7-first8-genuine-gencase-065/gencase' / case


def qa_attempt(case: str) -> Path:
    return DATA / 'families/F7' / case / f'root-stage1-f7-{case.lower()}-native-initial-qa-126'


def source_binding_case(binding: dict[str, Any], case: str) -> dict[str, Any]:
    rows = [row for row in binding['cases'] if row['case_id'] == case]
    if len(rows) != 1:
        raise RuntimeError(f'expected one fresh066 binding row for {case}')
    return rows[0]


def audit_root117(binding: dict[str, Any]) -> dict[str, Any]:
    top_receipt = DATA / 'families/F7/F7_STAGE1_FIRST8_TARGET_ANGLES/root-stage1-f7-first8-genuine-gencase-065/execution-receipt.json'
    result = top_receipt.parent / 'gencase-result.json'
    top = load(top_receipt)
    result_obj = load(result)
    if top.get('status') != 'failed' or top.get('returncode') != 0:
        raise RuntimeError('Root117 top-level wrapper failure was not preserved')
    if top.get('error') != 'GenCase actual particle count missing':
        raise RuntimeError('unexpected Root117 top-level failure reason')
    if result_obj.get('endpoint_count') != 5 or result_obj.get('status') != 'completed':
        raise RuntimeError('Root117 aggregate result is not the actual five-endpoint result')
    rows = []
    for case in CASES:
        bound = source_binding_case(binding, case)
        receipt_path = Path(bound['gencase']['per_case_receipt'])
        receipt = load(receipt_path)
        required = ['total_particles', 'fluid_particles', 'solver_dimension_from_gencase']
        missing = [key for key in required if key not in receipt or receipt[key] is None]
        if missing:
            raise RuntimeError(f'{case}: runtime GenCase fields missing: {missing}')
        if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
            raise RuntimeError(f'{case}: per-case GenCase receipt is not completed/0')
        if receipt['total_particles'] <= 0 or receipt['fluid_particles'] <= 0 or receipt['solver_dimension_from_gencase'] != 3:
            raise RuntimeError(f'{case}: invalid actual runtime GenCase fields')
        if receipt_path != data_attempt(case) / 'execution-receipt.json':
            raise RuntimeError(f'{case}: binding does not point to Root117 per-case receipt')
        rows.append({
            'case_id': case,
            'receipt': str(receipt_path),
            'receipt_sha256': sha(receipt_path),
            'status': receipt['status'],
            'returncode': receipt['returncode'],
            'runtime_fields_present': required,
            'actual_runtime_fields': {
                'total_particles': receipt['total_particles'],
                'fluid_particles': receipt['fluid_particles'],
                'solver_dimension_from_gencase': receipt['solver_dimension_from_gencase'],
            },
            'generated_xml': bound['gencase']['generated_xml'],
            'generated_xml_sha256': bound['gencase']['generated_xml_sha256'],
            'generated_bi4': bound['gencase']['generated_bi4'],
            'generated_bi4_sha256': bound['gencase']['generated_bi4_sha256'],
            'prepared_definition': bound['gencase']['prepared_definition'],
            'prepared_definition_sha256': bound['gencase']['prepared_definition_sha256'],
            'prepared_input_report': bound['gencase']['prepared_input_report'],
            'prepared_input_report_sha256': bound['gencase']['prepared_input_report_sha256'],
        })
    return {
        'schema': 'ds02.f7.root117.per-case-gencase-runtime-field-audit.v1',
        'scope_id': SCOPE,
        'root117_handoff': str(ROOT117),
        'root117_actual_input_binding': str(ROOT117 / 'actual-input-binding.json'),
        'root117_actual_input_binding_sha256': sha(ROOT117 / 'actual-input-binding.json'),
        'aggregate_result': str(result),
        'aggregate_result_sha256': sha(result),
        'aggregate_status': result_obj['status'],
        'top_level_execution_receipt': str(top_receipt),
        'top_level_execution_receipt_sha256': sha(top_receipt),
        'top_level_status': top['status'],
        'top_level_returncode': top['returncode'],
        'top_level_error': top['error'],
        'top_level_failure_preserved': True,
        'cases': rows,
        'runtime_required_fields': ['total_particles', 'fluid_particles', 'solver_dimension_from_gencase'],
        'metadata_only_qualified_input_preparation': {
            'required': False,
            'reason': 'Every Root117 per-case receipt contains the runtime-required actual total_particles, fluid_particles, and solver_dimension_from_gencase=3 fields. No GenCase rc0 or dimension is inferred from expected/XML counts.',
        },
        'read_policy': 'JSON receipt/result metadata and recorded opaque XML/BI4 hashes only; no BI4/H5/CSV/particle arrays read.',
    }


def root126_binding(root117_audit: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for case in CASES:
        sidecar = ROOT126 / f'{case}.json'
        sidecar_obj = load(sidecar)
        attempt = qa_attempt(case)
        receipt = attempt / 'execution-receipt.json'
        report = attempt / 'initial-qa/native-initial-qa.json'
        receipt_obj = load(receipt)
        report_obj = load(report)
        if receipt_obj.get('status') != 'completed' or receipt_obj.get('returncode') != 0:
            raise RuntimeError(f'{case}: Root126 receipt is not completed/0')
        if report_obj.get('all_cases_passed') is not True or report_obj.get('cases', [{}])[0].get('passed') is not True:
            raise RuntimeError(f'{case}: Root126 report is not a passing actual report')
        if sidecar_obj.get('attempt_id') != attempt.name:
            raise RuntimeError(f'{case}: Root126 sidecar attempt mismatch')
        rows.append({
            'case_id': case,
            'sidecar': str(sidecar),
            'sidecar_sha256': sha(sidecar),
            'execution_receipt': str(receipt),
            'execution_receipt_sha256': sha(receipt),
            'execution_status': receipt_obj['status'],
            'execution_returncode': receipt_obj['returncode'],
            'report': str(report),
            'report_sha256': sha(report),
            'report_all_cases_passed': report_obj['all_cases_passed'],
            'report_case_passed': report_obj['cases'][0]['passed'],
            'canonical_owner_binding_sha256': sidecar_obj['canonical_owner_binding_sha256'],
            'actual_gencase_receipt_sha256': sidecar_obj['actual_gencase']['receipt_sha256'],
            'actual_gencase_xml_sha256': sidecar_obj['actual_gencase']['xml_sha256'],
            'actual_gencase_bi4_sha256': sidecar_obj['actual_gencase']['bi4_sha256'],
        })
    semantic = ROOT126 / 'semantic-erratum.json'
    return {
        'schema': 'ds02.f7.root126.actual-initial-qa-binding.v1',
        'scope_id': SCOPE,
        'root126_handoff': str(ROOT126),
        'source_worker': str(ROOT126 / 'workers/run_f7_first8_actual_native_initial_qa.py'),
        'source_worker_sha256': sha(ROOT126 / 'workers/run_f7_first8_actual_native_initial_qa.py'),
        'semantic_erratum': str(semantic),
        'semantic_erratum_sha256': sha(semantic),
        'cases': rows,
        'future_solver_receipts_sha256': None,
        'read_policy': 'Existing Root126 JSON receipts/reports and sidecars only; no CSV/BI4/H5/particle arrays read.',
    }


def add_input(request: dict[str, Any], path: Path, recorded_sha: str | None = None) -> None:
    path_str = str(path)
    if path_str not in request['input_files']:
        request['input_files'].append(path_str)
    request['input_sha256'][path_str] = recorded_sha or sha(path)


def update_request(out: Path, case: str, root117_audit: dict[str, Any], root126: dict[str, Any]) -> dict[str, Any]:
    full = out / 'requests' / f'{case}.full601-native-qualification-request.json'
    req = load(full)
    audit = next(row for row in root117_audit['cases'] if row['case_id'] == case)
    qa = next(row for row in root126['cases'] if row['case_id'] == case)
    old_binding_path = str(SOURCE / 'metadata/actual-gencase-native-source-binding.json')
    new_binding_path = str(out / 'metadata/actual-gencase-native-source-binding.json')
    if old_binding_path in req['input_files']:
        req['input_files'] = [new_binding_path if value == old_binding_path else value for value in req['input_files']]
        old_hash = req['input_sha256'].pop(old_binding_path, None)
        req['input_sha256'][new_binding_path] = old_hash or sha(Path(new_binding_path))
    for path in [
        ROOT117 / 'actual-input-binding.json',
        ROOT117 / 'request.json',
        Path(root117_audit['aggregate_result']),
        Path(root117_audit['top_level_execution_receipt']),
        Path(audit['receipt']),
        ROOT126 / f'{case}.json',
        ROOT126 / 'semantic-erratum.json',
        Path(qa['execution_receipt']),
        Path(qa['report']),
        out / 'metadata/root117-runtime-field-audit.json',
        out / 'metadata/root126-initial-qa-binding.json',
        F7WT / f'lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_065_stage1_first8_target_angles_v1/source/{case}_Def.xml',
    ]:
        add_input(req, path)
    req['scope_id'] = SCOPE
    req['source_package'] = str(out)
    req['attempt_id'] = req['attempt_id'].replace('-066-pending', '-067-pending')
    req['launch'] = False
    req['launch_allowed'] = False
    req['execution_allowed'] = False
    req['status'] = 'source_only_disabled_root117_root126_final_binding'
    req['disabled_reason'] = 'Root117 top-level wrapper failure is preserved, while each per-case GenCase receipt is actual completed/0 with runtime total/fluid/3D fields. Root126 actual initial QA is completed/0 and passing; Root review is still required before the full601 GPU solver launch.'
    req['root117_runtime_contract'] = {
        'per_case_receipt': audit['receipt'],
        'per_case_receipt_sha256': audit['receipt_sha256'],
        'status': audit['status'],
        'returncode': audit['returncode'],
        'actual_total_particles': audit['actual_runtime_fields']['total_particles'],
        'actual_fluid_particles': audit['actual_runtime_fields']['fluid_particles'],
        'actual_solver_dimension': audit['actual_runtime_fields']['solver_dimension_from_gencase'],
        'fields_are_copied_from_receipt': True,
        'top_level_failure_preserved': True,
    }
    req['root126_initial_qa'] = {
        'attempt_id': qa['execution_receipt'].split('/')[-2],
        'execution_receipt': qa['execution_receipt'],
        'execution_receipt_sha256': qa['execution_receipt_sha256'],
        'execution_status': qa['execution_status'],
        'execution_returncode': qa['execution_returncode'],
        'report': qa['report'],
        'report_sha256': qa['report_sha256'],
        'report_all_cases_passed': qa['report_all_cases_passed'],
        'report_case_passed': qa['report_case_passed'],
    }
    req['initial_qa_required'] = {
        'status': 'completed_actual_root126',
        'required_case_id': case,
        'required_all_cases_passed': True,
        'receipt': qa['execution_receipt'],
        'receipt_sha256': qa['execution_receipt_sha256'],
        'report': qa['report'],
        'report_sha256': qa['report_sha256'],
    }
    req['future_outputs'] = {
        'solver_execution_receipt': '{attempt_root}/execution-receipt.json',
        'solver_execution_receipt_sha256': None,
        'solver_output_root': '{attempt_root}/solver_output',
        'native_frame_count': 601,
        'trajectory_h5_sha256': None,
    }
    write(full, req)

    qa_request_path = out / 'requests' / f'{case}.native-initial-qa-request.json'
    qa_request = load(qa_request_path)
    if old_binding_path in qa_request['input_files']:
        qa_request['input_files'] = [new_binding_path if value == old_binding_path else value for value in qa_request['input_files']]
        old_hash = qa_request['input_sha256'].pop(old_binding_path, None)
        qa_request['input_sha256'][new_binding_path] = old_hash or sha(Path(new_binding_path))
    old_worker_path = str(SOURCE / 'workers/run_f7_first8_actual_native_initial_qa.py')
    new_worker_path = str(out / 'workers/run_f7_first8_actual_native_initial_qa.py')
    if old_worker_path in qa_request['input_files']:
        qa_request['input_files'] = [new_worker_path if value == old_worker_path else value for value in qa_request['input_files']]
        old_hash = qa_request['input_sha256'].pop(old_worker_path, None)
        qa_request['input_sha256'][new_worker_path] = old_hash or sha(Path(new_worker_path))
    qa_request['scope_id'] = SCOPE
    qa_request['source_package'] = str(out)
    qa_request['launch'] = False
    qa_request['launch_allowed'] = False
    qa_request['execution_allowed'] = False
    qa_request['status'] = 'historical_root126_actual_completed_disabled'
    qa_request['disabled_reason'] = 'Root126 actual initial QA receipt/report are already bound; this historical QA request remains disabled and is not rerun. The full601 request consumes the immutable Root126 results.'
    qa_request['actual_root126_outputs'] = {
        'execution_receipt': qa['execution_receipt'],
        'execution_receipt_sha256': qa['execution_receipt_sha256'],
        'report': qa['report'],
        'report_sha256': qa['report_sha256'],
        'report_all_cases_passed': qa['report_all_cases_passed'],
        'report_case_passed': qa['report_case_passed'],
    }
    for path in [ROOT126 / f'{case}.json', ROOT126 / 'semantic-erratum.json', Path(qa['execution_receipt']), Path(qa['report'])]:
        add_input(qa_request, path)
    write(qa_request_path, qa_request)
    return req


def test_text() -> str:
    return '''#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = %r

def j(path):
    return json.loads(path.read_text())

def test_fresh067():
    audit = j(ROOT / 'metadata/root117-runtime-field-audit.json')
    assert audit['metadata_only_qualified_input_preparation']['required'] is False
    assert audit['top_level_failure_preserved'] is True
    assert len(audit['cases']) == 5
    for row in audit['cases']:
        assert row['actual_runtime_fields'] == {'total_particles': 70179, 'fluid_particles': 40700, 'solver_dimension_from_gencase': 3}
    qa = j(ROOT / 'metadata/root126-initial-qa-binding.json')
    assert len(qa['cases']) == 5
    assert all(row['report_all_cases_passed'] is True and row['report_case_passed'] is True for row in qa['cases'])
    for case in CASES:
        req = j(ROOT / 'requests' / f'{case}.full601-native-qualification-request.json')
        assert req['launch'] is False and req['launch_allowed'] is False and req['execution_allowed'] is False
        assert req['scope_id'].startswith('root_followup_067_')
        assert req['initial_qa_required']['status'] == 'completed_actual_root126'
        assert req['initial_qa_required']['receipt_sha256'] is not None
        assert req['initial_qa_required']['report_sha256'] is not None
        assert req['future_outputs']['solver_execution_receipt_sha256'] is None
        assert req['future_outputs']['trajectory_h5_sha256'] is None
        assert '-tmax:12' in req['command'] and '-tout:0.02' in req['command']
        assert req['cwd'].endswith(case)
        assert (Path(req['cwd']) / 'motion_obstacle_quintic.dat').is_file()
        assert req['root117_runtime_contract']['actual_solver_dimension'] == 3
        for needle in ('.xml', '.bi4', '_Def.xml', 'motion_obstacle_quintic.dat'):
            assert any(needle in value for value in req['input_files'])
    assert j(ROOT / 'manifest.json')['handoff_id'].startswith('root_followup_067_')

if __name__ == '__main__':
    test_fresh067()
    print('fresh067 contract: PASS')
''' % (CASES,)


def build(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f'output exists: {out}')
    shutil.copytree(SOURCE, out)
    binding = load(out / 'metadata/actual-gencase-native-source-binding.json')
    audit = audit_root117(binding)
    qa = root126_binding(audit)
    write(out / 'metadata/root117-runtime-field-audit.json', audit)
    write(out / 'metadata/root126-initial-qa-binding.json', qa)
    requests = [update_request(out, case, audit, qa) for case in CASES]
    test_path = out / 'tests/test_fresh067_contract.py'
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_text(), encoding='utf-8')
    builder = out / 'builders/build_f7_fresh067.py'
    builder.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), builder)
    # A compact final binding points Root at the exact five requests and all
    # immutable Root117/Root126 evidence without claiming future solver output.
    final_binding = {
        'schema': 'ds02.f7.stage1.root117-root126-full601-final-binding.v1',
        'scope_id': SCOPE,
        'family_id': 'F7',
        'source_package': str(out),
        'source_fresh066': str(SOURCE),
        'root117_runtime_audit': {'path': str(out / 'metadata/root117-runtime-field-audit.json'), 'sha256': sha(out / 'metadata/root117-runtime-field-audit.json')},
        'root126_qa_binding': {'path': str(out / 'metadata/root126-initial-qa-binding.json'), 'sha256': sha(out / 'metadata/root126-initial-qa-binding.json')},
        'cases': [
            {
                'case_id': case,
                'full601_request': {'path': str(out / 'requests' / f'{case}.full601-native-qualification-request.json'), 'sha256': sha(out / 'requests' / f'{case}.full601-native-qualification-request.json')},
                'native_initial_qa_request': {'path': str(out / 'requests' / f'{case}.native-initial-qa-request.json'), 'sha256': sha(out / 'requests' / f'{case}.native-initial-qa-request.json')},
                'root117_per_case_receipt': next(row for row in audit['cases'] if row['case_id'] == case),
                'root126_initial_qa': next(row for row in qa['cases'] if row['case_id'] == case),
            }
            for case in CASES
        ],
        'future_receipt_sha256_policy': 'All future full601 solver execution, trajectory, and output receipt hashes remain null until Root enables and runs the disabled requests.',
        'qualified_input_preparation': audit['metadata_only_qualified_input_preparation'],
        'no_arrays_read': True,
        'no_jobs_started': True,
        'no_shared_registry_write': True,
    }
    write(out / 'metadata/final-native-input-binding.json', final_binding)
    manifest = load(out / 'manifest.json')
    manifest.update({
        'handoff_id': SCOPE,
        'scope_id': SCOPE,
        'binding': {'source_absolute_path': str(out / 'metadata/final-native-input-binding.json'), 'source_sha256': sha(out / 'metadata/final-native-input-binding.json')},
        'actual_root117_per_case_completed_count': 5,
        'actual_root126_initial_qa_completed_count': 5,
        'root117_top_level_failure_preserved': True,
        'runtime_required_fields_checked': ['total_particles', 'fluid_particles', 'solver_dimension_from_gencase'],
        'qualified_input_preparation_required': False,
        'execution_allowed': False,
        'launch_allowed': False,
        'no_arrays_decoded': True,
        'no_jobs_started': True,
        'no_shared_registry_write': True,
        'next_step': 'Root reviews five disabled full601 requests and enables them through the strict runner; future solver receipt and trajectory hashes remain null here.',
    })
    request_files = []
    for case in CASES:
        for suffix in ('full601-native-qualification-request.json', 'native-initial-qa-request.json'):
            q = out / 'requests' / f'{case}.{suffix}'
            request_files.append({'source_absolute_path': str(q), 'source_sha256': sha(q)})
    manifest['request_files'] = request_files
    manifest['metadata_files'] = [
        {'source_absolute_path': str(out / 'metadata/root117-runtime-field-audit.json'), 'source_sha256': sha(out / 'metadata/root117-runtime-field-audit.json')},
        {'source_absolute_path': str(out / 'metadata/root126-initial-qa-binding.json'), 'source_sha256': sha(out / 'metadata/root126-initial-qa-binding.json')},
        {'source_absolute_path': str(out / 'metadata/final-native-input-binding.json'), 'source_sha256': sha(out / 'metadata/final-native-input-binding.json')},
    ]
    write(out / 'manifest.json', manifest)
    readme = '''# F7 fresh067 Root117/Root126 final full601 native binding

This source-only F7 package derives the five disabled full601 native solver requests from fresh066 and binds each case to the actual Root117 per-case GenCase receipt and actual Root126 initial native QA receipt/report.

Each Root117 per-case receipt is completed/0 and contains the runtime-required actual fields `total_particles=70179`, `fluid_particles=40700`, and `solver_dimension_from_gencase=3`. The Root117 top-level wrapper remains an immutable failed receipt (`returncode=0`, `GenCase actual particle count missing`) and is recorded as historical failure evidence; it is never rewritten as success. No GenCase rc0 or dimension is inferred from expected counts or XML.

Root126 has completed/0 receipt and a passing native-initial-qa report for all five cases. The full601 requests bind those actual QA hashes, genuine generated XML/BI4/Def hashes, and the Root116 prepared per-case solver cwd. Each cwd contains `motion_obstacle_quintic.dat`; the solver command preserves `-tmax:12` and `-tout:0.02` for 601 frames.

All full601 and historical QA requests remain `launch=false`, `launch_allowed=false`, and `execution_allowed=false`. Future solver execution-receipt, trajectory, and output hashes are null. No metadata-only qualified-input preparation request is needed because the runtime fields are present in every Root117 per-case receipt. No arrays, solver, GenCase, conversion, or shared registry/ledger state were touched.
'''
    (out / 'README.md').write_text(readme, encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(args.output)


if __name__ == '__main__':
    main()
