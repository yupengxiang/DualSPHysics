#!/usr/bin/env python3
"""Build the F2 fresh105 metadata-only semantic/CSV-layout adapter.

Only JSON, XML and source files are read or hashed here.  Producer-recorded
hashes for CSV, BI4, DAT, H5 and solver outputs are carried as provenance and
are never recomputed by this builder.  All generated requests are disabled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

INFRA = Path('/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics').resolve()
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics').resolve()
BASE = Path('/home/jade/Projects/DualSPHysics').resolve()
DATA_ROOT = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02').resolve()
HERE = Path(__file__).resolve().parent
HANDOFF = INFRA / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003'
FRESH103 = HANDOFF / 'root_followup_103_f2_fresh102_native_path_xmf_adapter_v1'
FRESH104 = HANDOFF / 'root_followup_104_f2_actual_qa_csv_parser_repair_v1'
M103 = FRESH103 / 'F2_STAGE1_FRESH103_NATIVE_PATH_XMF_ADAPTER_MANIFEST.json'
ROOT396 = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual16_nativeGen354_fresh104_CSV_initialQA_396'
LAB = INTEGRATION / 'lagrangian-fluid-lab'
PYTHON = LAB / '.venv/bin/python'
RUNTIME = LAB / 'scripts/ds_data02_runtime_v2.py'
STRICT = LAB / 'scripts/ds_data02_strict_dispatch_v1.py'
ROOT142 = LAB / 'campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py'
ROOT230D = LAB / 'campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230'
ROOT230 = ROOT230D / 'root_native_home_floor_inventory_policy.py'
ROOT230LAUNCH = ROOT230D / 'launch.py'
ROOT230CONTRACT = ROOT230D / 'source-policy-contract.json'
GPU_POLICY = LAB / 'campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py'
RESOURCE = LAB / 'campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json'
SOLVER = BASE / 'lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64'
PARTVTK = BASE / 'lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64'
FRESH_ID = 'fresh105'
SCOPE = 'F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1'
LOGICAL_GUARD = 'a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a'
STRICT_DISPATCH_SHA = '81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'
STATIC_SUFFIXES = {'.json', '.xml', '.py', '.md', '.txt'}
RAW_SUFFIXES = {'.dat', '.bi4', '.ibi4', '.h5', '.hdf5', '.csv', '.vtk', '.vtu', '.vtp', '.xmf', '.png', '.gif'}
COUNT_KEYS = ('fixed', 'moving', 'floating', 'fluid')
QA_MAX_WALL = 1800
QA_STORAGE = 256 * 1024 * 1024
QA_THREADS = 4


def sha_static(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() not in STATIC_SUFFIXES or path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f'fresh105 refuses non-static path: {path}')
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'JSON object required: {path}')
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def binding(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha_static(path), 'bytes': path.stat().st_size, 'exists': True}


def add_static(files: dict[str, str], path: Path) -> None:
    path = Path(path).resolve()
    files[str(path)] = sha_static(path)


def closure_from_template(template: Mapping[str, Any]) -> dict[str, str]:
    """Refresh metadata hashes and preserve producer hashes for scientific paths."""
    files: dict[str, str] = {}
    for raw_path, expected in (template.get('input_sha256') or {}).items():
        path = Path(str(raw_path)).resolve()
        if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f'producer digest missing for {path}')
            files[str(path)] = expected
        else:
            actual = sha_static(path)
            if actual != expected:
                raise ValueError(f'metadata hash drift: {path}')
            files[str(path)] = actual
    return files


def strict_guard(native: bool) -> dict[str, Any]:
    root_policy = ROOT230 if native else ROOT142
    return {
        'strict_guard_digest': LOGICAL_GUARD,
        'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA,
        'source_only': True,
        'worktree_root': str(INFRA),
        'input_closure': 'set(input_files)==set(input_sha256); producer-recorded scientific inputs are not read by fresh105; future outputs remain null',
        'runtime_v2': {'path': str(RUNTIME), 'sha256': sha_static(RUNTIME)},
        'strict_dispatch': {'path': str(STRICT), 'sha256': sha_static(STRICT)},
        'root142_inventory_policy': {'path': str(ROOT142), 'sha256': sha_static(ROOT142)},
        'root230_inventory_policy': {'path': str(ROOT230), 'sha256': sha_static(ROOT230)},
        'root_inventory_policy': {'path': str(root_policy), 'sha256': sha_static(root_policy)},
        'resource_window': {'path': str(RESOURCE), 'sha256': sha_static(RESOURCE)},
    }


def runtime_contract() -> dict[str, Any]:
    """Record fields from runtime_v2 source without importing/calling it."""
    source = RUNTIME.read_text(encoding='utf-8')
    required = ['family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds', 'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root']
    gencase = ['returncode', 'gencase_returncode', 'total_particles', 'fluid_particles', 'solver_dimension_from_gencase', 'gencase_receipt_sha256']
    for term in required + gencase + ['CPU_KINDS', 'validate_request', 'estimated_peak_gpu_mib']:
        if term not in source:
            raise ValueError(f'runtime contract term not found in source: {term}')
    return {
        'schema': 'ds02.f2.stage1.fresh105.runtime-v2-structural-contract.v1',
        'source': binding(RUNTIME),
        'extraction_method': 'literal source inspection only; runtime_v2.validate_request was not imported or called',
        'required_request_fields': required,
        'cpu_task_allowlist_symbol': 'CPU_KINDS',
        'qualification_checks': {
            'approved_solver_command': True,
            'estimated_peak_gpu_mib_positive': True,
            'gencase_receipt_fields': gencase,
            'raw_receipt_hash_optional_but_when_present_verified': True,
        },
        'semantic_adapter_fields_supplied_separately': ['status', 'returncode', 'solver_dimension_from_gencase', 'total_particles', 'fluid_particles'],
        'source_validator_does_not_call_runtime_validate_request': True,
    }


def root396_request(cid: str) -> tuple[Path, dict[str, Any]]:
    path = ROOT396 / f'{cid}-initial-qa-request.json'
    return path, load(path)


def root397_observation(cid: str, req: Mapping[str, Any]) -> dict[str, Any]:
    """Read Root397 JSON reports only; never open the report's CSV path."""
    attempt = str(req['attempt_id'])
    report_path = DATA_ROOT / 'families' / 'F2' / cid / attempt / 'actual-initial-qa.json'
    receipt_path = report_path.parent / 'execution-receipt.json'
    report = load(report_path) if report_path.is_file() else None
    receipt = load(receipt_path) if receipt_path.is_file() else None
    checks = (report or {}).get('checks', {})
    scientific_keys = {
        'actual_gencase_terminal_success', 'actual_initial_csv_available', 'source_xml_contract',
        'row_count_exact_expected_particles', 'all_required_rows_parse', 'all_reported_fields_finite',
        'particle_ids_unique_complete', 'positive_type3_fluid', 'type_partition_matches_prepared_counts',
        'positive_mass_all_rows', 'positive_density_all_rows',
    }
    layout_keys = {'semicolon_delimiter', 'units_row_skipped_once'}
    return {
        'case_id': cid,
        'attempt_id': attempt,
        'request': binding(Path(str(req['_path']))),
        'report': binding(report_path) if report is not None else {'path': str(report_path.resolve()), 'sha256': None, 'exists': False},
        'receipt': binding(receipt_path) if receipt is not None else {'path': str(receipt_path.resolve()), 'sha256': None, 'exists': False},
        'report_status': report.get('status') if report else None,
        'receipt_status': receipt.get('status') if receipt else None,
        'receipt_returncode': receipt.get('returncode') if receipt else None,
        'checks': checks,
        'scientific_checks_all_true': bool(report and all(checks.get(key) is True for key in scientific_keys)),
        'layout_checks_false': [key for key in sorted(layout_keys) if report and checks.get(key) is not True],
        'passed': bool(report and report.get('status') == 'pass' and receipt and receipt.get('status') == 'completed' and receipt.get('returncode') == 0 and all(value is True for value in checks.values())),
        'negative_evidence_preserved': bool(report and not (report.get('status') == 'pass' and all(value is True for value in checks.values()))),
        'csv_path_recorded_by_root': ((report or {}).get('csv_summary') or {}).get('csv', {}).get('path'),
        'csv_sha256_recorded_by_root': ((report or {}).get('csv_summary') or {}).get('csv', {}).get('sha256'),
        'csv_read_or_hashed_by_builder': False,
    }


def case_inputs(row: Mapping[str, Any]) -> dict[str, Any]:
    side_path = Path(str(row['gencase_evidence']['path'])).resolve()
    side = load(side_path)
    receipt_path = Path(str(side['raw_gencase_receipt']['path'])).resolve()
    report_path = Path(str(side['prepared_input_report']['path'])).resolve()
    xml_path = Path(str(side['prepared_generated_xml']['path'])).resolve()
    receipt = load(receipt_path)
    report = load(report_path)
    counts = report.get('generated_xml_particle_counts')
    total = report.get('actual_total_particles')
    if not isinstance(counts, dict) or any(not isinstance(counts.get(k), int) for k in COUNT_KEYS):
        raise ValueError(f'prepared counts missing: {row["case_id"]}')
    if not isinstance(total, int) or total <= 0 or sum(counts[k] for k in COUNT_KEYS) != total:
        raise ValueError(f'prepared count closure failed: {row["case_id"]}')
    if side.get('raw_gencase_receipt', {}).get('raw_receipt_immutable') is not True or side.get('contract_checks', {}).get('root353_solver_dimension_three') is not True:
        raise ValueError(f'fresh102 evidence contract missing: {row["case_id"]}')
    return {
        'row': row, 'side_path': side_path, 'side': side, 'receipt_path': receipt_path, 'receipt': receipt,
        'report_path': report_path, 'report': report, 'xml_path': xml_path,
        'receipt_sha': sha_static(receipt_path), 'report_sha': sha_static(report_path), 'side_sha': sha_static(side_path),
        'xml_sha': sha_static(xml_path), 'counts': {k: int(counts[k]) for k in COUNT_KEYS}, 'total': total,
    }


def semantic_request(case: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case['row']['case_id'])
    slug = cid.lower()
    attempt = f'root-stage1-f2-{slug}-gencase-semantic-metadata-105'
    worker = HERE / 'workers/fresh105_gencase_semantic_adapter.py'
    contract_path = HERE / 'metadata/contracts/gencase-semantic-contract.json'
    files: dict[str, str] = {}
    for path in (worker, HERE / 'workers/fresh104_parser_base.py', contract_path, RUNTIME, STRICT, ROOT142, RESOURCE, case['receipt_path'], case['report_path'], case['side_path'], case['xml_path']):
        add_static(files, path)
    output = f'{{attempt_root}}/semantic-gencase-receipt.json'
    out = {
        'schema': 'ds02.runner-request.v3', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'scope_id': SCOPE,
        'case_id': cid, 'attempt_id': attempt, 'kind': 'cpu', 'cpu_task_kind': 'audit', 'cpu_threads': QA_THREADS,
        'max_wall_seconds': QA_MAX_WALL, 'estimated_storage_bytes': QA_STORAGE, 'launch_owner': 'root', 'root_only': True,
        'worktree_root': str(INFRA), 'cwd': str(HERE), 'execution_allowed': False, 'launch_allowed': False, 'disabled': True,
        'source_only': True, 'future_hashes_null': True, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
        'disabled_reason': 'Enable only as a Root-owned metadata audit after review; it derives a separate semantic receipt and never rewrites the raw GenCase receipt.',
        'command': [str(PYTHON), str(worker), '--case-id', cid, '--gencase-receipt', str(case['receipt_path']), '--prepared-input-report', str(case['report_path']), '--runtime-evidence', str(case['side_path']), '--generated-xml', str(case['xml_path']), '--output', output],
        'gencase_receipt': str(case['receipt_path']), 'gencase_receipt_sha256': case['receipt_sha'],
        'prepared_input_report': str(case['report_path']), 'prepared_input_report_sha256': case['report_sha'],
        'runtime_evidence_sidecar': str(case['side_path']), 'runtime_evidence_sidecar_sha256': case['side_sha'],
        'prepared_generated_xml': str(case['xml_path']), 'prepared_generated_xml_sha256': case['xml_sha'],
        'expected_dimension': 3, 'expected_particles': case['total'], 'prepared_report_observed_counts': case['counts'],
        'semantic_receipt': {'path': output, 'sha256': None, 'status': None, 'returncode': None, 'raw_receipt_rewritten': False},
        'future_output_paths': {'semantic_receipt': output}, 'future_input_files': [output], 'future_input_sha256': {output: None},
        'output_contract': {'semantic_receipt_sha256': None, 'solver_dimension_from_gencase': 3, 'total_particles': case['total'], 'fluid_particles': case['counts']['fluid']},
        'strict_guard_digest': LOGICAL_GUARD, 'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA, 'strict_guard': strict_guard(native=False),
        'runtime_contract': contract,
        'input_files': sorted(files), 'input_sha256': {path: files[path] for path in sorted(files)},
        'scientific_payloads_read_or_hashed': [], 'canonical_grant': False, 'canonical_physical_binding_sha256': None,
    }
    path = HERE / 'requests' / f'{cid}-gencase-semantic-metadata-disabled.json'
    dump(path, out)
    return path, out


def qa_request(case: Mapping[str, Any], root_req: Mapping[str, Any], observation: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case['row']['case_id'])
    slug = cid.lower()
    attempt = f'root-stage1-f2-{slug}-prepared-report-qa-csv-layout-repair-105'
    worker = HERE / 'workers/fresh105_initial_qa_csv_parser.py'
    base_worker = HERE / 'workers/fresh104_parser_base.py'
    parser_contract = HERE / 'metadata/contracts/csv-parser-contract.json'
    files: dict[str, str] = {}
    for path in (worker, base_worker, parser_contract, RUNTIME, STRICT, ROOT142, RESOURCE, case['receipt_path'], case['report_path'], case['side_path'], case['xml_path'], Path(str(root_req['_path']))):
        add_static(files, path)
    if observation['report']['exists']:
        add_static(files, Path(str(observation['report']['path'])))
    if observation['receipt']['exists']:
        add_static(files, Path(str(observation['receipt']['path'])))
    output = '{attempt_root}/actual-initial-qa.json'
    command = [str(PYTHON), str(worker), '--case-id', cid, '--definition', str(case['xml_path']), '--gencase-receipt', str(case['receipt_path']), '--prepared-input-report', str(case['report_path']), '--runtime-evidence', str(case['side_path']), '--partvtk', str(PARTVTK), '--partvtk-output-dir', '{attempt_root}/partvtk', '--output', output]
    if observation.get('csv_path_recorded_by_root') and observation.get('csv_sha256_recorded_by_root'):
        command += ['--csv', str(observation['csv_path_recorded_by_root']), '--expected-csv-sha256', str(observation['csv_sha256_recorded_by_root'])]
    out = {
        'schema': 'ds02.runner-request.v3', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'scope_id': SCOPE,
        'case_id': cid, 'attempt_id': attempt, 'kind': 'cpu', 'cpu_task_kind': 'audit', 'cpu_threads': QA_THREADS,
        'max_wall_seconds': QA_MAX_WALL, 'estimated_storage_bytes': QA_STORAGE, 'launch_owner': 'root', 'root_only': True,
        'worktree_root': str(INFRA), 'cwd': str(HERE), 'execution_allowed': False, 'launch_allowed': False, 'disabled': True,
        'source_only': True, 'future_hashes_null': True, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
        'disabled_reason': 'Fresh104 scientific checks passed in four Root397 reports; only delimiter/units-layout interface checks failed. Enable only after Root reviews this bounded parser repair; old failed reports remain immutable.',
        'retry_of_attempt': str(root_req['attempt_id']), 'depends_on_attempts': [str(root_req['gencase_attempt_id'])],
        'command': command, 'gencase_receipt': str(case['receipt_path']), 'gencase_receipt_sha256': case['receipt_sha'],
        'prepared_input_report': str(case['report_path']), 'prepared_input_report_sha256': case['report_sha'],
        'runtime_evidence_sidecar': str(case['side_path']), 'runtime_evidence_sidecar_sha256': case['side_sha'],
        'prepared_generated_xml': str(case['xml_path']), 'prepared_generated_xml_sha256': case['xml_sha'],
        'prepared_flat_prefix': str(case['report_path'].parent), 'expected_dimension': 3, 'expected_particles': case['total'],
        'prepared_report_observed_counts': case['counts'], 'prepared_report_count_source': 'actual prepared-input-report via fresh102 sidecar; never raw receipt partition fields',
        'registered_existing_csv': ({'path': str(observation['csv_path_recorded_by_root']), 'sha256': observation['csv_sha256_recorded_by_root'], 'read_or_hashed_here': False, 'digest_source': 'Root397 report'} if observation.get('csv_path_recorded_by_root') else None),
        'parser_contract': str(parser_contract.resolve()), 'parser_contract_sha256': sha_static(parser_contract),
        'strict_guard_digest': LOGICAL_GUARD, 'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA, 'strict_guard': strict_guard(native=False),
        'resource_contract': {'max_wall_seconds': QA_MAX_WALL, 'estimated_storage_bytes': QA_STORAGE, 'cpu_threads': QA_THREADS},
        'future_input_files': [output, '{attempt_root}/execution-receipt.json', '{attempt_root}/partvtk/initial*.csv'],
        'future_input_sha256': {output: None, '{attempt_root}/execution-receipt.json': None, '{attempt_root}/partvtk/initial*.csv': None},
        'output_contract': {'actual_qa_report_sha256': None, 'execution_receipt_sha256': None, 'scientific_csv_sha256': None, 'actual_counts': None, 'qa_passed': None},
        'root397_observation': observation, 'runtime_contract': contract,
        'input_files': sorted(files), 'input_sha256': {path: files[path] for path in sorted(files)},
        'qualification_claim': 'none', 'production_claim': 'none', 'canonical_grant': False, 'canonical_physical_binding_sha256': None,
    }
    path = HERE / 'requests' / f'{cid}-initial-qa-csv-layout-repair-disabled.json'
    dump(path, out)
    return path, out


def native_request(case: Mapping[str, Any], observation: Mapping[str, Any], sem_path: Path, sem_req: Mapping[str, Any], qa_path: Path, qa_req: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    cid = str(case['row']['case_id'])
    slug = cid.lower()
    base_path = FRESH104 / 'requests' / f'{cid}-native401-disabled.json'
    base = load(base_path)
    old_attempt = str(base['attempt_id'])
    attempt = f'root-stage1-f2-{slug}-full401-native-semantic-105'
    files = closure_from_template(base)
    native_contract = HERE / 'metadata/contracts/native-contract.json'
    for path in (sem_path, qa_path, native_contract, RUNTIME, STRICT, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE, case['receipt_path'], case['report_path'], case['side_path'], case['xml_path']):
        if Path(path).suffix.lower() in STATIC_SUFFIXES:
            add_static(files, Path(path))
    command = [str(value).replace(old_attempt, attempt) for value in base['command']]
    sem_output = DATA_ROOT / 'families' / 'F2' / cid / str(sem_req['attempt_id']) / 'semantic-gencase-receipt.json'
    native_root = DATA_ROOT / 'families' / 'F2' / cid / attempt
    native_receipt = native_root / 'execution-receipt.json'
    run_out = native_root / 'solver_output' / 'Run.out'
    qa_report = DATA_ROOT / 'families' / 'F2' / cid / str(qa_req['attempt_id']) / 'actual-initial-qa.json'
    out = dict(base)
    out.update({
        'fresh_id': FRESH_ID, 'attempt_id': attempt, 'command': command, 'cwd': str(case['report_path'].parent), 'worktree_root': str(INFRA),
        'depends_on_attempts': [str(case['gencase_attempt_id']), str(sem_req['attempt_id']), str(qa_req['attempt_id'])],
        'semantic_adapter_attempt_id': str(sem_req['attempt_id']), 'semantic_adapter_request': str(sem_path.resolve()), 'semantic_adapter_request_sha256': sha_static(sem_path),
        'gencase_attempt_id': str(case['gencase_attempt_id']), 'gencase_receipt': str(sem_output), 'gencase_receipt_sha256': None,
        'gencase_receipt_semantics': 'future fresh105 separate semantic receipt; raw Root353/354 receipt remains immutable and is retained as provenance',
        'prepared_generated_xml': str(case['xml_path']), 'prepared_generated_xml_sha256': case['xml_sha'], 'prepared_input_report': str(case['report_path']), 'prepared_input_report_sha256': case['report_sha'],
        'runtime_evidence_sidecar': str(case['side_path']), 'runtime_evidence_sidecar_sha256': case['side_sha'], 'gencase_prefix': str(base.get('gencase_prefix', case['report'].get('prefix'))),
        'initial_qa_attempt_id': str(qa_req['attempt_id']), 'initial_qa_request': str(qa_path.resolve()), 'initial_qa_request_sha256': sha_static(qa_path),
        'initial_qa_report': str(qa_report), 'initial_qa_report_sha256': None, 'initial_qa_gate': {'required_attempt': str(qa_req['attempt_id']), 'passed': None, 'enable_only_after_actual_report_pass': True},
        'expected_dimension': 3, 'expected_native_frames': 401, 'expected_particles': case['total'], 'prepared_particle_count': case['total'], 'prepared_particle_counts': case['counts'],
        'native_receipt': str(native_receipt), 'native_receipt_sha256': None, 'run_out': str(run_out), 'run_out_sha256': None,
        'future_input_files': [str(sem_output), str(qa_report), str(native_receipt), str(run_out), str(native_root / 'solver_output' / 'data')],
        'future_input_sha256': {str(sem_output): None, str(qa_report): None, str(native_receipt): None, str(run_out): None, str(native_root / 'solver_output' / 'data'): None},
        'future_output_paths': {'semantic_gencase_receipt': str(sem_output), 'execution_receipt': str(native_receipt), 'run_out': str(run_out), 'solver_output': str(native_root / 'solver_output'), 'frames': None},
        'expected_output': {'frame_count': 401, 'full_window_s': 4.0, 'save_interval_s': 0.01, 'solver_dimension': 3, 'particle_counts': None, 'native_output_hash': None},
        'root230_dispatch': base.get('root230_dispatch'), 'shared_gpu_lease_policy': {'profile': 'Root230 live UUID lease at enable time', 'resolved_gpu_uuid': None, 'lease_handle': None, 'source_agent_must_not_resolve': True},
        'strict_guard_digest': LOGICAL_GUARD, 'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA, 'strict_guard': strict_guard(native=True),
        'input_files': sorted(files), 'input_sha256': {path: files[path] for path in sorted(files)},
        'source_only': True, 'execution_allowed': False, 'launch_allowed': False, 'disabled': True, 'future_hashes_null': True,
        'disabled_reason': 'Enable only after fresh105 semantic receipt exists with an actual hash and fresh105 initial QA reports pass. Root230 must resolve a live UUID lease at enable time. No canonical/Q-N/production grant is inferred.',
        'canonical_physical_binding_sha256': None, 'canonical_grant': False, 'production_claim': 'none', 'qualification_claim': 'none', 'root397_observation': observation,
    })
    path = HERE / 'requests' / f'{cid}-native401-semantic-disabled.json'
    dump(path, out)
    return path, out


def main() -> int:
    m103 = load(M103)
    if m103.get('fresh_id') != 'fresh103' or m103.get('case_count') != 16:
        raise SystemExit('fresh103 manifest must contain 16 cases')
    contract = runtime_contract()
    dump(HERE / 'metadata/contracts/runtime-v2-structural-contract.json', contract)
    dump(HERE / 'metadata/contracts/csv-parser-contract.json', {
        'schema': 'ds02.f2.stage1.fresh105.csv-layout-repair-contract.v1', 'source_only': True, 'future_root_worker_only': True,
        'producer': 'official PartVTK only', 'supported_delimiters': [',', ';'],
        'header_detection': 'scan preface until Pos.x + Type + Mk + Idp typed header',
        'units_layout': 'accept inline unit labels in header or zero/one immediate standalone units row; never require either layout',
        'required_columns': ['Pos.x', 'Pos.y', 'Pos.z', 'Vel.x', 'Vel.y', 'Vel.z', 'Rhop', 'Mass', 'Idp', 'Type', 'Mk'],
        'scientific_checks_unchanged': ['row count from data rows only', 'finite numeric fields', 'unique complete Idp', 'Type/Mk partition', 'positive Mass/Rhop', '3-D XML contract'],
        'root397_evidence': 'four reports had all scientific checks true; only fixed semicolon and mandatory-units-row interface flags were false',
        'registered_csv_mode': 'Root may supply producer-recorded CSV path/SHA; this source builder never reads or hashes that CSV',
    })
    dump(HERE / 'metadata/contracts/gencase-semantic-contract.json', {
        'schema': 'ds02.f2.stage1.fresh105.gencase-semantic-contract.v1', 'raw_receipt_immutable': True, 'raw_receipt_rewritten': False,
        'derived_fields': ['solver_dimension_from_gencase', 'total_particles', 'fluid_particles', 'fixed_particles', 'moving_particles', 'floating_particles'],
        'provenance_sources': ['Root353/354 raw execution receipt status/returncode', 'prepared-input-report actual_total_particles/generated_xml_particle_counts', 'fresh102 root353_solver_dimension_three', 'generated XML data2d=false'],
        'producer_recorded_science_digest_policy': 'BI4 digest is carried from prepared-input-report and is never read or recomputed by fresh105',
        'native_gate': 'native request may be enabled only after semantic adapter receipt0/hash and independent actual initial QA pass',
    })
    dump(HERE / 'metadata/contracts/runtime-strict-guard.json', strict_guard(native=False))
    dump(HERE / 'metadata/contracts/native-contract.json', {
        'schema': 'ds02.f2.stage1.fresh105.native-contract.v1', 'recipe': ['-tmax:4.0', '-tout:0.01'], 'expected_frames': 401,
        'expected_dimension': 3, 'solver': str(SOLVER), 'root230_uuid_lease_at_enable': True, 'no_extra_mdbc_option': True,
        'future_native_receipt_sha256': None, 'future_solver_output_hashes': None,
    })
    dump(HERE / 'metadata/contracts/runtime-required-fields.json', contract)

    rows: list[dict[str, Any]] = []
    for raw_row in m103['cases']:
        cid = str(raw_row['case_id'])
        case = case_inputs(raw_row)
        root_path, root_req = root396_request(cid)
        root_req['_path'] = str(root_path.resolve())
        root_req['_request_sha256'] = sha_static(root_path)
        case['gencase_attempt_id'] = str(root_req['gencase_attempt_id'])
        observation = root397_observation(cid, root_req)
        sem_path, sem_req = semantic_request(case, contract)
        qa_path, qa_req = qa_request(case, root_req, observation, contract)
        native_path, native_req = native_request(case, observation, sem_path, sem_req, qa_path, qa_req, contract)
        rows.append({
            'case_id': cid, 'physical_case_id': raw_row.get('physical_case_id'),
            'source_plan_physical_condition_sha256': raw_row.get('source_plan_physical_condition_sha256'),
            'prospective_legacy_scope_sha256': raw_row.get('prospective_legacy_scope_sha256'),
            'gencase_attempt_id': case['gencase_attempt_id'],
            'raw_gencase_receipt': binding(case['receipt_path']), 'prepared_input_report': binding(case['report_path']), 'prepared_generated_xml': binding(case['xml_path']),
            'prepared_dimension': 3, 'prepared_total_particles': case['total'], 'prepared_particle_counts': case['counts'],
            'root397_observation': observation,
            'semantic_request': binding(sem_path), 'semantic_attempt_id': sem_req['attempt_id'], 'semantic_output_sha256': None,
            'qa_request': binding(qa_path), 'qa_attempt_id': qa_req['attempt_id'], 'qa_report_sha256': None,
            'native_request': binding(native_path), 'native_attempt_id': native_req['attempt_id'], 'native_receipt_sha256': None, 'native_output_hash': None,
            'raw_receipt_immutable': True, 'canonical_grant': False, 'canonical_physical_binding_sha256': None,
        })
    manifest = {
        'schema': 'ds02.f2.stage1.fresh105.gencase-semantic-csv-layout-adapter-manifest.v1', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'scope_id': SCOPE,
        'case_count': len(rows), 'cases': rows, 'all_requests_disabled': True, 'execution_allowed': False, 'launch_allowed': False,
        'future_hashes_null': True, 'raw_receipts_immutable': True, 'canonical_grant': False, 'independent_case_count_increment': 0,
        'actual_semantic_receipts_completed': 0, 'actual_native_receipts_completed': 0, 'actual_qa_passes_claimed': 0,
        'root397_four_reports_preserved_as_negative_interface_evidence': True, 'root397_scientific_checks_not_reclassified': True,
        'root397_csv_not_read_or_hashed_by_builder': True, 'synthetic_parser_tests_only': True,
        'scientific_payloads_read_or_hashed_by_builder': [], 'runtime_contract': contract,
        'resource_contract': {'qa_max_wall_seconds': QA_MAX_WALL, 'qa_estimated_storage_bytes': QA_STORAGE, 'qa_cpu_threads': QA_THREADS, 'native_window_s': 4.0, 'native_save_interval_s': 0.01, 'native_frames': 401},
        'strict_guard_digest': LOGICAL_GUARD, 'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA,
        'source_only_disclosure': 'semantic fields are derived from producer JSON/XML evidence; raw receipts are not patched; native and QA outputs remain future nulls',
    }
    dump(HERE / 'F2_STAGE1_FRESH105_GENCASE_SEMANTIC_CSV_LAYOUT_ADAPTER_MANIFEST.json', manifest)
    print(json.dumps({'status': 'pass', 'fresh_id': FRESH_ID, 'case_count': len(rows), 'all_requests_disabled': True, 'root397_reports_seen': sum(1 for row in rows if row['root397_observation']['report']['exists']), 'scientific_payloads_read_or_hashed': []}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
