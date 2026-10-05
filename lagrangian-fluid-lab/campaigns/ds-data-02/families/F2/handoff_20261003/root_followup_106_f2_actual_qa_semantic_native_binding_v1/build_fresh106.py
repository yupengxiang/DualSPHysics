#!/usr/bin/env python3
"""Build fresh106 from Root416/418 metadata and producer JSON evidence.

This builder reads JSON/XML/source metadata only.  It never opens, copies, or
hashes CSV, DAT, BI4, H5, VTK, or solver output.  Native requests remain
source-only and disabled; Root owns any later enablement and UUID lease.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

INFRA = Path('/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics').resolve()
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics').resolve()
BASE = Path('/home/jade/Projects/DualSPHysics').resolve()
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02').resolve()
HERE = Path(__file__).resolve().parent
HANDOFF = INFRA / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003'
FRESH099 = HANDOFF / 'root_followup_099_f2_stage1_first24_domain_expansion_v1'
FRESH105 = HANDOFF / 'root_followup_105_f2_actual_gencase_semantic_adapter_v1'
ROOT416 = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual16_fresh105_CSV_initialQA_416'
ROOT418 = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_actual16_fresh105_GenCase_semantic_requests_418'
LAB = INTEGRATION / 'lagrangian-fluid-lab'
RUNTIME = LAB / 'scripts/ds_data02_runtime_v2.py'
STRICT = LAB / 'scripts/ds_data02_strict_dispatch_v1.py'
ROOT230D = LAB / 'campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230'
ROOT230 = ROOT230D / 'root_native_home_floor_inventory_policy.py'
ROOT230LAUNCH = ROOT230D / 'launch.py'
ROOT230CONTRACT = ROOT230D / 'source-policy-contract.json'
GPU_POLICY = LAB / 'campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py'
RESOURCE = LAB / 'campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json'
SOLVER = BASE / 'lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64'
PARTVTK = BASE / 'lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64'
SCOPE = 'F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1'
FRESH_ID = 'fresh106'
STRICT_DISPATCH_SHA = '81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'
LOGICAL_GUARD = 'a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a'
STATIC_SUFFIXES = {'.json', '.xml', '.py', '.md', '.txt'}
RAW_SUFFIXES = {'.csv', '.dat', '.bi4', '.ibi4', '.h5', '.hdf5', '.vtk', '.vtu', '.vtp', '.xmf', '.png', '.gif'}
REQUIRED_QA_CHECKS = {
    'actual_gencase_terminal_success', 'actual_initial_csv_available',
    'all_reported_fields_finite', 'all_required_rows_parse',
    'header_found_after_preface', 'particle_ids_unique_complete',
    'positive_density_all_rows', 'positive_mass_all_rows',
    'positive_type3_fluid', 'row_count_exact_expected_particles',
    'source_xml_contract', 'supported_delimiter',
    'type_partition_matches_prepared_counts', 'units_layout_supported',
}
EXPECTED_COUNTS = {'total_particles': 418104, 'fluid_particles': 21114,
                   'fixed_particles': 372840, 'moving_particles': 24150,
                   'floating_particles': 0}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'JSON object required: {path}')
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def sha_static(path: Path) -> str:
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix not in STATIC_SUFFIXES or suffix in RAW_SUFFIXES:
        raise ValueError(f'fresh106 refuses scientific/raw path: {path}')
    if not path.is_file():
        raise FileNotFoundError(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def binding(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha_static(path), 'bytes': path.stat().st_size, 'exists': True}


def producer_binding(path: str | Path, digest: str | None, *, source: str) -> dict[str, Any]:
    # A producer digest is evidence, not a permission to touch the raw payload.
    return {'path': str(Path(path).resolve()), 'sha256': digest, 'read_or_hashed_here': False,
            'digest_source': source}


def add_static(files: dict[str, str], path: Path) -> None:
    path = Path(path).resolve()
    files[str(path)] = sha_static(path)


def add_producer(files: dict[str, str], path: str | Path, digest: str | None) -> None:
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f'missing producer digest: {path}')
    files[str(Path(path).resolve())] = digest


def closure_from_template(template: Mapping[str, Any]) -> dict[str, str]:
    """Carry fresh105 closure; recompute only static files, never raw files."""
    result: dict[str, str] = {}
    for raw_path, expected in (template.get('input_sha256') or {}).items():
        path = Path(str(raw_path)).resolve()
        suffix = path.suffix.lower()
        if suffix in RAW_SUFFIXES or suffix not in STATIC_SUFFIXES:
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f'producer digest missing for {path}')
            result[str(path)] = expected
        else:
            actual = sha_static(path)
            if actual != expected:
                raise ValueError(f'static hash drift: {path}')
            result[str(path)] = actual
    return result


def request_binding(path: Path) -> tuple[Path, dict[str, Any]]:
    d = load(path)
    d['_path'] = str(Path(path).resolve())
    return path, d


def root_attempts(cid: str) -> tuple[tuple[Path, dict[str, Any]], tuple[Path, dict[str, Any]]]:
    qa_path, qa = request_binding(ROOT416 / f'{cid}-initial-qa-request.json')
    sem_path, sem = request_binding(ROOT418 / f'{cid}-semantic-request.json')
    return (qa_path, qa), (sem_path, sem)


def actual_receipts(cid: str, qa_req: Mapping[str, Any], sem_req: Mapping[str, Any]) -> dict[str, Any]:
    qa_dir = DATA / 'families' / 'F2' / cid / str(qa_req['attempt_id'])
    sem_dir = DATA / 'families' / 'F2' / cid / str(sem_req['attempt_id'])
    paths = {
        'qa_report': qa_dir / 'actual-initial-qa.json',
        'qa_execution': qa_dir / 'execution-receipt.json',
        'semantic_receipt': sem_dir / 'semantic-gencase-receipt.json',
        'semantic_execution': sem_dir / 'execution-receipt.json',
    }
    docs = {k: load(p) for k, p in paths.items()}
    return {'paths': paths, 'docs': docs, 'bindings': {k: binding(p) for k, p in paths.items()}}


def actual_gate(cid: str, actual: Mapping[str, Any]) -> dict[str, Any]:
    qa = actual['docs']['qa_report']; qae = actual['docs']['qa_execution']
    sem = actual['docs']['semantic_receipt']; seme = actual['docs']['semantic_execution']
    qchecks = qa.get('checks') if isinstance(qa.get('checks'), dict) else {}
    qa_pass = (qa.get('status') == 'pass' and qae.get('status') == 'completed' and qae.get('returncode') == 0
               and all(qchecks.get(k) is True for k in REQUIRED_QA_CHECKS))
    sem_counts = {k: sem.get(k) for k in EXPECTED_COUNTS}
    sem_pass = (sem.get('status') == 'completed' and sem.get('returncode') == 0
                and sem.get('solver_dimension_from_gencase') == 3
                and sem_counts == EXPECTED_COUNTS
                and seme.get('status') == 'completed' and seme.get('returncode') == 0
                and seme.get('status') == 'completed' and seme.get('returncode') == 0)
    return {
        'case_id': cid,
        'qa_pass': qa_pass,
        'qa_status': qa.get('status'), 'qa_execution_status': qae.get('status'),
        'qa_execution_returncode': qae.get('returncode'),
        'qa_checks_all_required_true': all(qchecks.get(k) is True for k in REQUIRED_QA_CHECKS),
        'qa_checks': qchecks,
        'semantic_pass': sem_pass,
        'semantic_status': sem.get('status'), 'semantic_returncode': sem.get('returncode'),
        'semantic_execution_status': seme.get('status'), 'semantic_execution_returncode': seme.get('returncode'),
        'semantic_counts': sem_counts, 'semantic_dimension': sem.get('solver_dimension_from_gencase'),
        'enable_eligible': bool(qa_pass and sem_pass),
        'future_native_hashes_null': True,
    }


def command_candidates(command: list[str]) -> list[str]:
    """Extract file-like command inputs without opening any candidate."""
    skip_value = {'--case-id', '--expected-csv-sha256', '--tmax', '--tout', '--gpu-index', '--threads'}
    candidates: list[str] = []
    for i, token in enumerate(command):
        token = str(token)
        if not token or token.startswith('-') or '{' in token or '}' in token:
            continue
        prev = str(command[i - 1]) if i else ''
        if prev in skip_value:
            continue
        suffix = Path(token).suffix.lower()
        path_like = token.startswith('/') or '/' in token or suffix in STATIC_SUFFIXES or suffix in RAW_SUFFIXES
        if not path_like:
            continue
        # The interpreter is runtime environment, while worker/solver/PartVTK are inputs.
        if i == 0 and (Path(token).name.startswith('python') or Path(token).name in {'python', 'python3'}):
            continue
        candidates.append(str(Path(token).resolve()) if token.startswith('/') else token)
    return sorted(set(candidates))


def check_command_input_closure(req: Mapping[str, Any]) -> dict[str, Any]:
    files = {str(Path(p).resolve()): v for p, v in (req.get('input_sha256') or {}).items()}
    listed = {str(Path(p).resolve()) for p in (req.get('input_files') or [])}
    missing_map = sorted(set(files) ^ listed)
    invalid_digest = sorted(p for p, h in files.items() if not isinstance(h, str) or len(h) != 64)
    missing_command: list[str] = []
    mismatched_static: list[str] = []
    for candidate in command_candidates([str(x) for x in req.get('command') or []]):
        suffix = Path(candidate).suffix.lower()
        if suffix in STATIC_SUFFIXES and Path(candidate).is_file():
            if candidate not in files:
                missing_command.append(candidate)
            elif sha_static(Path(candidate)) != files[candidate]:
                mismatched_static.append(candidate)
        elif suffix in RAW_SUFFIXES or (candidate.startswith('/') and Path(candidate).is_file()):
            if candidate not in files:
                missing_command.append(candidate)
    return {
        'request': str(req.get('_path', '')),
        'input_files_equals_input_sha256': not missing_map,
        'invalid_input_digests': invalid_digest,
        'missing_command_inputs': missing_command,
        'static_command_hash_mismatches': mismatched_static,
        'passed': not (missing_map or invalid_digest or missing_command or mismatched_static),
        'raw_inputs_are_producer_only': True,
        'scientific_payloads_read_or_hashed_here': [],
    }


def converter_scope(cid: str, owner_path: Path, owner: Mapping[str, Any], base: Mapping[str, Any],
                    sem: Mapping[str, Any], prepared: Mapping[str, Any]) -> dict[str, Any]:
    source = owner.get('source') if isinstance(owner.get('source'), dict) else {}
    meta = source.get('metadata') if isinstance(source.get('metadata'), dict) else {}
    definition = source.get('definition') if isinstance(source.get('definition'), dict) else {}
    meta_path = Path(str(meta.get('path'))).resolve()
    def_path = Path(str(definition.get('path'))).resolve()
    generated_xml = Path(str((sem.get('provenance') or {}).get('generated_xml', {}).get('path'))).resolve()
    prepared_report = Path(str((sem.get('provenance') or {}).get('prepared_input_report', {}).get('path'))).resolve()
    prefix = str(prepared.get('prefix'))
    bi4_path = Path(prefix + '.bi4').resolve()
    motion = next((x for x in (prepared.get('assets') or []) if str(x.get('relative_name', '')).endswith('.dat')), {})
    motion_path = Path(str(motion.get('copied_to', ''))).resolve()
    plan = owner.get('source_plan_physical_condition_sha256') or owner.get('physical_condition_sha256')
    legacy = base.get('prospective_legacy_scope_sha256')
    return {
        'schema': 'ds02.f2.stage1.fresh106.converter-scope-binding.v1',
        'case_id': cid,
        'owner_record': binding(owner_path),
        'source_plan_physical_condition_sha256': plan,
        'prospective_legacy_scope': {
            'schema': 'legacy-owner-scope.v0', 'sha256': legacy,
            'source': 'fresh105/fresh099 prospective owner metadata; not an actual converter receipt',
        },
        'actual_converter_scope_sha256': None,
        'canonical_physical_binding_sha256': None,
        'canonical_grant': False,
        'scope_status': 'legacy-owner-scope only; actual converter has not run',
        'source_metadata': binding(meta_path),
        'source_definition': binding(def_path),
        'actual_generated_xml': binding(generated_xml),
        'actual_prepared_input_report': binding(prepared_report),
        'producer_recorded_science_assets': {
            'bi4': producer_binding(bi4_path, prepared.get('bi4_sha256'), source='Root353/354 prepared-input-report producer record'),
            'motion_dat': producer_binding(motion_path, motion.get('sha256'), source='Root353/354 prepared-input-report producer record'),
        },
        'converter_scope_rule': 'Do not substitute owner record SHA or source-plan SHA for actual converter scope; actual_converter_scope_sha256 remains null until Root-owned converter receipt exists.',
        'source_only': True,
        'no_science_payloads_read_or_hashed_here': True,
    }


def native_request(cid: str, base: Mapping[str, Any], actual: Mapping[str, Any], gate: Mapping[str, Any],
                   scope_path: Path, scope_doc: Mapping[str, Any], qa_req_path: Path, sem_req_path: Path,
                   qa_req: Mapping[str, Any], sem_req: Mapping[str, Any], owner: Mapping[str, Any],
                   owner_path: Path, prepared: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    old_attempt = str(base['attempt_id'])
    slug = cid.lower()
    attempt = f'root-stage1-f2-{slug}-full401-native-qa416-semantic418-106'
    out = dict(base)
    command = [str(x).replace(old_attempt, attempt) for x in base['command']]
    sem_path = actual['paths']['semantic_receipt'].resolve()
    qa_path = actual['paths']['qa_report'].resolve()
    sem_exec = actual['paths']['semantic_execution'].resolve()
    qa_exec = actual['paths']['qa_execution'].resolve()
    native_root = DATA / 'families' / 'F2' / cid / attempt
    native_receipt = native_root / 'execution-receipt.json'
    run_out = native_root / 'solver_output' / 'Run.out'
    files = closure_from_template(base)
    for p in (sem_path, qa_path, sem_exec, qa_exec, scope_path, qa_req_path, sem_req_path, RUNTIME, STRICT, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE):
        add_static(files, p)
    # Actual generated XML and prepared report are already in fresh105 closure; verify/add safely.
    generated_xml = Path(str((actual['docs']['semantic_receipt'].get('provenance') or {}).get('generated_xml', {}).get('path'))).resolve()
    prepared_report_path = Path(str((actual['docs']['semantic_receipt'].get('provenance') or {}).get('prepared_input_report', {}).get('path'))).resolve()
    for p in (generated_xml, prepared_report_path, owner_path):
        add_static(files, p)
    prefix = str(prepared.get('prefix'))
    add_producer(files, Path(prefix + '.bi4'), prepared.get('bi4_sha256'))
    for asset in prepared.get('assets') or []:
        if str(asset.get('relative_name', '')).endswith('.dat'):
            add_producer(files, asset.get('copied_to'), asset.get('sha256'))
    input_files = sorted(files)
    sem_attempt = str(sem_req['attempt_id']); qa_attempt = str(qa_req['attempt_id'])
    out.update({
        'schema': 'ds02.runner-request.v3', 'fresh_id': FRESH_ID, 'attempt_id': attempt,
        'command': command, 'cwd': str(Path(str(base.get('cwd'))).resolve()), 'worktree_root': str(INFRA),
        'depends_on_attempts': [str(base.get('gencase_attempt_id')), sem_attempt, qa_attempt],
        'semantic_adapter_attempt_id': sem_attempt, 'semantic_adapter_request': str(sem_req_path.resolve()),
        'semantic_adapter_request_sha256': sha_static(sem_req_path),
        'gencase_attempt_id': str(base.get('gencase_attempt_id')), 'gencase_receipt': str(sem_path),
        'gencase_receipt_sha256': actual['bindings']['semantic_receipt']['sha256'],
        'gencase_receipt_semantics': 'Root419 completed0 fresh105 semantic receipt; raw GenCase receipt remains immutable provenance.',
        'initial_qa_attempt_id': qa_attempt, 'initial_qa_request': str(qa_req_path.resolve()),
        'initial_qa_request_sha256': sha_static(qa_req_path), 'initial_qa_report': str(qa_path),
        'initial_qa_report_sha256': actual['bindings']['qa_report']['sha256'],
        'initial_qa_execution_receipt': str(qa_exec), 'initial_qa_execution_receipt_sha256': actual['bindings']['qa_execution']['sha256'],
        'initial_qa_gate': {'required_attempt': qa_attempt, 'passed': bool(gate['qa_pass']), 'enable_only_after_actual_report_pass': True,
                            'report_status': gate['qa_status'], 'execution_status': gate['qa_execution_status'], 'execution_returncode': gate['qa_execution_returncode']},
        'semantic_gate': {'required_attempt': sem_attempt, 'passed': bool(gate['semantic_pass']), 'receipt_status': gate['semantic_status'],
                          'receipt_returncode': gate['semantic_returncode'], 'execution_status': gate['semantic_execution_status'],
                          'execution_returncode': gate['semantic_execution_returncode']},
        'semantic_receipt_execution_receipt': str(sem_exec), 'semantic_receipt_execution_receipt_sha256': actual['bindings']['semantic_execution']['sha256'],
        'expected_dimension': 3, 'expected_native_frames': 401, 'expected_particles': EXPECTED_COUNTS['total_particles'],
        'prepared_particle_count': EXPECTED_COUNTS['total_particles'], 'prepared_particle_counts': {k: EXPECTED_COUNTS[k] for k in ('fixed_particles','moving_particles','fluid_particles','floating_particles')},
        'native_receipt': str(native_receipt), 'native_receipt_sha256': None, 'run_out': str(run_out), 'run_out_sha256': None,
        'future_input_files': [str(native_receipt), str(run_out), str(native_root / 'solver_output' / 'data')],
        'future_input_sha256': {str(native_receipt): None, str(run_out): None, str(native_root / 'solver_output' / 'data'): None},
        'future_output_paths': {'execution_receipt': str(native_receipt), 'run_out': str(run_out), 'solver_output': str(native_root / 'solver_output'), 'frames': None},
        'expected_output': {'frame_count': 401, 'full_window_s': 4.0, 'save_interval_s': 0.01, 'solver_dimension': 3, 'particle_counts': None, 'native_output_hash': None},
        'converter_scope_binding': str(scope_path.resolve()), 'converter_scope_binding_sha256': sha_static(scope_path),
        'actual_converter_scope_sha256': None, 'canonical_physical_binding_sha256': None, 'canonical_grant': False,
        'producer_scope_schema': 'legacy-owner-scope.v0', 'source_plan_physical_condition_sha256': owner.get('source_plan_physical_condition_sha256'),
        'prospective_legacy_scope_sha256': base.get('prospective_legacy_scope_sha256'),
        'root230_dispatch': base.get('root230_dispatch'),
        'shared_gpu_lease_policy': {'profile': 'Root230 live UUID lease at enable time', 'resolved_gpu_uuid': None, 'lease_handle': None, 'source_agent_must_not_resolve': True, 'foreign_gpu_protected': True},
        'strict_guard_digest': LOGICAL_GUARD, 'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA, 'strict_guard': base.get('strict_guard'),
        'input_files': input_files, 'input_sha256': {p: files[p] for p in input_files},
        'source_only': True, 'execution_allowed': False, 'launch_allowed': False, 'disabled': True,
        'enable_eligible': bool(gate['enable_eligible']), 'root_review_required': True, 'future_hashes_null': True,
        'disabled_reason': 'Enable only after Root reviews actual416/418 completed0 evidence and resolves a live Root230 UUID lease. Future native receipt, frames, Run.out and H5 remain null. No converter/canonical/Q-N/production grant is inferred.',
        'native_initial_qa_required': True, 'native_frame0_qa_required': True, 'native_frame0_qa_receipt_sha256': None,
        'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
        'qualification_claim': 'none', 'production_claim': 'none', 'numerical_precision_status': 'not accepted',
    })
    path = HERE / 'requests' / f'{cid}-native401-actual-binding-disabled.json'
    dump(path, out)
    return path, out


def main() -> int:
    base_paths = sorted(FRESH105.glob('requests/*-native401-semantic-disabled.json'))
    if len(base_paths) != 16:
        raise SystemExit(f'expected 16 fresh105 native templates, got {len(base_paths)}')
    rows: list[dict[str, Any]] = []
    upstream: list[dict[str, Any]] = []
    all_pass = True
    for base_path in base_paths:
        base = load(base_path); cid = str(base['case_id'])
        (qa_path, qa_req), (sem_path, sem_req) = root_attempts(cid)
        actual = actual_receipts(cid, qa_req, sem_req)
        gate = actual_gate(cid, actual)
        upstream_checks = {'qa_request': check_command_input_closure(qa_req), 'semantic_request': check_command_input_closure(sem_req)}
        upstream.append({'case_id': cid, 'qa_request': binding(qa_path), 'semantic_request': binding(sem_path), 'qa_execution_attempt_id': qa_req['attempt_id'], 'semantic_execution_attempt_id': sem_req['attempt_id'], 'actual': actual['bindings'], 'gate': gate, 'command_input_closure': upstream_checks})
        owner_path = FRESH099 / 'owners' / f'{cid}.owner.json'; owner = load(owner_path)
        prepared_path = Path(str((actual['docs']['semantic_receipt'].get('provenance') or {}).get('prepared_input_report', {}).get('path'))).resolve()
        prepared = load(prepared_path)
        scope_doc = converter_scope(cid, owner_path, owner, base, actual['docs']['semantic_receipt'], prepared)
        scope_path = HERE / 'owners' / f'{cid}.actual-converter-scope-binding.json'; dump(scope_path, scope_doc)
        native_path, native = native_request(cid, base, actual, gate, scope_path, scope_doc, qa_path, sem_path, qa_req, sem_req, owner, owner_path, prepared)
        native_closure = check_command_input_closure(native)
        row = {
            'case_id': cid, 'physical_case_id': owner.get('physical_case_id'),
            'source_plan_physical_condition_sha256': owner.get('source_plan_physical_condition_sha256'),
            'prospective_legacy_scope_sha256': base.get('prospective_legacy_scope_sha256'),
            'gencase_attempt_id': base.get('gencase_attempt_id'),
            'actual_qa_report': actual['bindings']['qa_report'], 'actual_qa_execution': actual['bindings']['qa_execution'],
            'actual_semantic_receipt': actual['bindings']['semantic_receipt'], 'actual_semantic_execution': actual['bindings']['semantic_execution'],
            'gate': gate, 'converter_scope_binding': binding(scope_path),
            'native_request': binding(native_path), 'native_command_input_closure': native_closure,
            'native_enabled': False, 'native_receipt_sha256': None, 'native_output_hash': None,
            'raw_receipts_immutable': True, 'canonical_grant': False,
        }
        rows.append(row)
        all_pass = all_pass and bool(gate['enable_eligible']) and bool(native_closure['passed'])
    # The upstream reports are evidence; the validator explicitly exposes any old Root416/418 omissions.
    dump(HERE / 'evidence/upstream-actual-binding.json', {'schema': 'ds02.f2.stage1.fresh106.upstream-actual-binding.v1', 'fresh_id': FRESH_ID, 'case_count': len(upstream), 'cases': upstream, 'scientific_payloads_read_or_hashed_here': [], 'raw_receipts_immutable': True})
    dump(HERE / 'evidence/fresh106-source-validation.json', {'schema': 'ds02.f2.stage1.fresh106.source-validation.v1', 'case_count': len(rows), 'all_actual_gates_pass': all(bool(x['gate']['enable_eligible']) for x in rows), 'all_native_requests_disabled': all(not bool(load(Path(x['native_request']['path'])).get('execution_allowed')) for x in rows), 'all_native_closures_pass': all(bool(x['native_command_input_closure']['passed']) for x in rows), 'overall_native_binding_ready_for_root_review': all_pass, 'upstream416_418_command_closure_is_reported_not_rewritten': True, 'runtime_v2_validate_request_called': False, 'scientific_payloads_read_or_hashed_here': [], 'future_native_hashes_null': True})
    dump(HERE / 'F2_STAGE1_FRESH106_ACTUAL_QA_SEMANTIC_NATIVE_BINDING_MANIFEST.json', {
        'schema': 'ds02.f2.stage1.fresh106.actual-qa-semantic-native-binding-manifest.v1', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'scope_id': SCOPE,
        'case_count': len(rows), 'cases': rows, 'all_requests_disabled': True, 'execution_allowed': False, 'launch_allowed': False,
        'enable_eligible_case_count': sum(1 for x in rows if x['gate']['enable_eligible']), 'actual_qa_completed0_count': sum(1 for x in rows if x['gate']['qa_pass']),
        'actual_semantic_completed0_count': sum(1 for x in rows if x['gate']['semantic_pass']), 'native_completed0_count': 0,
        'future_native_hashes_null': True, 'raw_receipts_immutable': True, 'canonical_grant': False, 'independent_case_count_increment': 0,
        'strict_dispatch_file_sha256': STRICT_DISPATCH_SHA, 'resource_window': str(RESOURCE), 'root230_policy': str(ROOT230),
        'source_only_disclosure': 'Actual Root417/419 JSON receipts are bound; native requests remain disabled and future solver receipts/H5/output hashes are null. CSV/BI4/DAT are producer-recorded only.',
        'scientific_payloads_read_or_hashed_here': [],
    })
    dump(HERE / 'metadata/contracts/native-binding-contract.json', {
        'schema': 'ds02.f2.stage1.fresh106.native-binding-contract.v1', 'recipe': ['-tmax:4.0', '-tout:0.01'], 'expected_frames': 401,
        'expected_dimension': 3, 'expected_total_particles': EXPECTED_COUNTS['total_particles'], 'expected_fluid_particles': EXPECTED_COUNTS['fluid_particles'],
        'approved_solver': str(SOLVER), 'root230_uuid_lease_at_enable': True, 'no_extra_solver_option_added': True,
        'enable_gate': ['Root417 QA execution completed0', 'QA report status pass and all required checks true', 'Root419 semantic execution completed0', 'semantic receipt status completed0 and exact 3D/count closure'],
        'future_native_receipt_sha256': None, 'future_native_output_hashes': None,
        'command_input_closure': 'All request command file inputs must be listed in input_files with matching input_sha256; raw science assets use producer-recorded digests and are not read by this source builder.',
    })
    dump(HERE / 'metadata/contracts/converter-scope-contract.json', {
        'schema': 'ds02.f2.stage1.fresh106.converter-scope-contract.v1', 'actual_converter_scope_sha256': None,
        'prospective_scope_schema': 'legacy-owner-scope.v0', 'canonical_grant': False,
        'rule': 'owner/source-plan SHA is never substituted for an actual converter scope; Root-owned converter receipt must establish actual scope later.',
        'raw_asset_policy': 'BI4 and motion DAT paths/digests are producer provenance only; no read/hash/copy here.',
    })
    print(json.dumps({'status': 'pass' if all_pass else 'review', 'fresh_id': FRESH_ID, 'case_count': len(rows), 'actual_qa_completed0': sum(x['gate']['qa_pass'] for x in rows), 'actual_semantic_completed0': sum(x['gate']['semantic_pass'] for x in rows), 'native_requests_disabled': True, 'native_completed0': 0, 'all_native_closures_pass': all(bool(x['native_command_input_closure']['passed']) for x in rows), 'scientific_payloads_read_or_hashed': []}, indent=2, sort_keys=True))
    return 0 if all_pass else 2


if __name__ == '__main__':
    raise SystemExit(main())
