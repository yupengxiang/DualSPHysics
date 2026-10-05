#!/usr/bin/env python3
"""Build fresh107 actual-native -> disabled typed/NVME bindings.

Only JSON/XML/Python/source metadata is read or hashed. Native Run.out and
solver data directories are stat'ed as producer outputs but never opened or
hashed. BI4/DAT/H5/CSV remain producer-recorded inputs with null future H5
hashes. No converter, solver, PartVTK, or runtime validation is run here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

INFRA = Path('/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics').resolve()
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics').resolve()
BASE = Path('/home/jade/Projects/DualSPHysics').resolve()
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02').resolve()
HERE = Path(__file__).resolve().parent
HANDOFF = INFRA / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003'
FRESH100 = HANDOFF / 'root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1'
FRESH106 = HANDOFF / 'root_followup_106_f2_actual_qa_semantic_native_binding_v1'
LAB = INTEGRATION / 'lagrangian-fluid-lab'
PYTHON = LAB / '.venv/bin/python'
DIRECT = LAB / 'scripts/ds_data02_direct_convert.py'
NVME = LAB / 'scripts/ds_data02_nvme_convert_v1.py'
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
DECODER = BASE / 'lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump'
SCOPE = 'F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1'
FRESH_ID = 'fresh107'
STRICT_SHA = '81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'
GUARD_SHA = 'a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a'
RAW_SUFFIXES = {'.csv', '.dat', '.bi4', '.ibi4', '.h5', '.hdf5', '.vtk', '.vtu', '.vtp', '.xmf', '.png', '.gif'}
STATIC_SUFFIXES = {'.json', '.xml', '.py', '.md', '.txt'}


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
    if path.suffix.lower() not in STATIC_SUFFIXES or path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f'fresh107 refuses raw/non-metadata hash: {path}')
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


def add_static(files: dict[str, str], path: Path) -> None:
    path = Path(path).resolve()
    files[str(path)] = sha_static(path)


def add_producer(files: dict[str, str], path: Path, digest: str) -> None:
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f'producer digest missing: {path}')
    files[str(Path(path).resolve())] = digest


def closure_from_template(template: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw, expected in (template.get('input_sha256') or {}).items():
        p = Path(str(raw)).resolve(); suffix = p.suffix.lower()
        if suffix in RAW_SUFFIXES or suffix not in STATIC_SUFFIXES:
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f'producer hash missing for {p}')
            out[str(p)] = expected
        else:
            actual = sha_static(p)
            if actual != expected:
                raise ValueError(f'static hash drift: {p}')
            out[str(p)] = actual
    return out


def unique_paths(paths: list[Path]) -> list[Path]:
    result = []; seen = set()
    for p in paths:
        p = Path(p).resolve()
        if str(p) not in seen:
            seen.add(str(p)); result.append(p)
    return result


def actual_binding(path: Path) -> dict[str, Any]:
    return binding(path)


def actual_native(cid: str) -> dict[str, Any]:
    case_root = DATA / 'families' / 'F2' / cid
    receipts = sorted(case_root.glob('*full401-native-semantic-105/execution-receipt.json'))
    if len(receipts) != 1:
        raise ValueError(f'{cid}: expected one completed native105 receipt, got {len(receipts)}')
    receipt_path = receipts[0].resolve(); receipt = load(receipt_path)
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError(f'{cid}: native receipt is not completed/0')
    request = receipt.get('request') if isinstance(receipt.get('request'), dict) else {}
    command = [str(x) for x in request.get('command') or []]
    if '-tmax:4.0' not in command or '-tout:0.01' not in command or any('mdbc' in x.lower() for x in command):
        raise ValueError(f'{cid}: native recipe drift')
    output_root = Path(str(receipt.get('output_root'))).resolve()
    run_out = output_root / 'solver_output' / 'Run.out'
    data_root = output_root / 'solver_output' / 'data'
    if not output_root.is_dir() or not run_out.is_file() or not data_root.is_dir():
        raise ValueError(f'{cid}: native output path metadata incomplete')
    return {
        'receipt_path': receipt_path, 'receipt': receipt, 'request': request,
        'receipt_binding': actual_binding(receipt_path), 'output_root': output_root,
        'run_out': run_out, 'data_root': data_root,
        'output_metadata': {'output_root_exists': True, 'run_out_exists': True, 'data_root_exists': True,
                           'run_out_bytes': run_out.stat().st_size, 'data_root_entries_not_scanned': True,
                           'scientific_output_read_or_hashed_here': False},
        'recipe': {'command': command, 'tmax_s': 4.0, 'tout_s': 0.01, 'expected_frames_from_request': request.get('expected_native_frames', 401),
                   'actual_frame_count': None, 'frame_completeness_audited': False},
    }


def probe_scope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    manifest_path = HERE / 'metadata/scope-probe-input.json'
    probe_path = HERE / 'evidence/legacy-scope-probe.json'
    dump(manifest_path, {'schema': 'ds02.f2.stage1.fresh107.scope-probe-input.v1', 'owners': [
        {'case_id': r['case_id'], 'path': str(r['owner_path']), 'expected_legacy_scope_sha256': r['expected_scope']} for r in rows]})
    subprocess.run([str(PYTHON), str(HERE / 'workers/fresh107_legacy_scope_probe.py'), '--owner-manifest', str(manifest_path), '--converter', str(DIRECT), '--output', str(probe_path)], check=True)
    probe = load(probe_path)
    if probe.get('status') != 'pass' or len(probe.get('owners', [])) != 16:
        raise ValueError('legacy scope probe did not pass all 16 owners')
    return probe


def command_candidates(command: list[str]) -> list[str]:
    skip_values = {'--staging-root', '--staging-limit-bytes', '--particle-chunk'}
    result = []
    for i, raw in enumerate(command):
        token = str(raw)
        if not token or token.startswith('-') or '{' in token or '}' in token or token == '--':
            continue
        prev = str(command[i - 1]) if i else ''
        if prev in skip_values:
            continue
        if i == 0 and 'python' in Path(token).name:
            continue
        if token.startswith('/') or '/' in token or Path(token).suffix.lower() in STATIC_SUFFIXES | RAW_SUFFIXES:
            result.append(str(Path(token).resolve()))
    return sorted(set(result))


def typed_command_closure(req: Mapping[str, Any]) -> dict[str, Any]:
    files = {str(Path(k).resolve()): v for k, v in (req.get('input_sha256') or {}).items()}
    listed = {str(Path(k).resolve()) for k in (req.get('input_files') or [])}
    missing_map = sorted(set(files) ^ listed)
    invalid = sorted(k for k, v in files.items() if not isinstance(v, str) or len(v) != 64)
    future = {str(Path(k).resolve()) for k in req.get('future_input_files') or []}
    missing = []; mismatched = []
    for candidate in command_candidates([str(x) for x in req.get('command') or []]):
        if candidate in future:
            continue
        if candidate == str(Path('/tmp/ds02-nvme-conversion').resolve()):
            continue
        suffix = Path(candidate).suffix.lower()
        if suffix in STATIC_SUFFIXES and Path(candidate).is_file():
            if candidate not in files: missing.append(candidate)
            elif sha_static(Path(candidate)) != files[candidate]: mismatched.append(candidate)
        elif suffix in RAW_SUFFIXES:
            if candidate not in files and candidate not in future: missing.append(candidate)
        elif Path(candidate).is_file() and candidate not in files:
            missing.append(candidate)
    return {'input_files_equals_input_sha256': not missing_map, 'invalid_input_digests': invalid,
            'missing_command_inputs': missing, 'static_command_hash_mismatches': mismatched,
            'future_native_inputs_explicit': sorted(future), 'passed': not (missing_map or invalid or missing or mismatched),
            'scientific_payloads_read_or_hashed_here': []}


def main() -> int:
    m106 = load(FRESH106 / 'F2_STAGE1_FRESH106_ACTUAL_QA_SEMANTIC_NATIVE_BINDING_MANIFEST.json')
    base_paths = sorted(FRESH100.glob('requests/*-typed-disabled.json'))
    if len(base_paths) != 16 or m106.get('case_count') != 16:
        raise SystemExit('fresh100/fresh106 must both contain 16 cases')
    m106_by_case = {r['case_id']: r for r in m106['cases']}
    source_rows = []
    for base_path in base_paths:
        template = load(base_path); cid = str(template['case_id'])
        owner_path = FRESH100 / 'owners' / f'{cid}.motion-adapted-owner.json'
        owner = load(owner_path)
        source_rows.append({'case_id': cid, 'base_path': base_path, 'template': template, 'owner_path': owner_path,
                            'owner': owner, 'expected_scope': owner['typed_scope_contract']['prospective_legacy_scope_sha256']})
    probe = probe_scope(source_rows)
    probe_by_case = {r['case_id']: r for r in probe['owners']}
    rows = []
    csv_rows = []
    all_ready = True
    for source in source_rows:
        cid = source['case_id']; template = source['template']; owner = source['owner']; mrow = m106_by_case[cid]
        actual = actual_native(cid)
        sem_path = Path(mrow['actual_semantic_receipt']['path']).resolve(); qa_path = Path(mrow['actual_qa_report']['path']).resolve()
        sem_exec = Path(mrow['actual_semantic_execution']['path']).resolve(); qa_exec = Path(mrow['actual_qa_execution']['path']).resolve()
        sem = load(sem_path); prep_path = Path(str((sem.get('provenance') or {}).get('prepared_input_report', {}).get('path'))).resolve()
        xml_path = Path(str((sem.get('provenance') or {}).get('generated_xml', {}).get('path'))).resolve()
        prepared = load(prep_path)
        probe_row = probe_by_case[cid]; scope_sha = probe_row['prospective_legacy_scope_sha256']
        scope_path = HERE / 'owners' / f'{cid}.actual-native-typed-scope.owner.json'
        scope_doc = {
            'schema': 'ds02.f2.stage1.fresh107.actual-native-typed-scope-owner.v1', 'case_id': cid, 'family_id': 'F2', 'scope_id': SCOPE,
            'owner_metadata': binding(source['owner_path']), 'owner_whole_record_sha256': sha_static(source['owner_path']),
            'source_plan_physical_condition_sha256': owner.get('source_plan_physical_condition_sha256'),
            'prospective_legacy_scope_sha256': scope_sha, 'actual_converter_physical_condition_sha256': None,
            'canonical_physical_binding_sha256': None, 'canonical_grant': False,
            'physical_condition_hash_scope': 'ds_data02_direct_convert._physical_condition_scope(owner); legacy-owner-scope.v0',
            'semantic_binding_status': probe_row['scope'].get('semantic_binding_status'),
            'probe': {'worker': str((HERE / 'workers/fresh107_legacy_scope_probe.py').resolve()), 'converter': str(DIRECT), 'probe_result': str((HERE / 'evidence/legacy-scope-probe.json').resolve()), 'probe_result_sha256': sha_static(HERE / 'evidence/legacy-scope-probe.json')},
            'actual_native': {'receipt': actual['receipt_binding'], 'output_root': str(actual['output_root']), 'run_out': str(actual['run_out']), 'data_root': str(actual['data_root']), 'frame_count_actual': None},
            'gencase_semantic_receipt': binding(sem_path), 'initial_qa_report': binding(qa_path), 'semantic_execution_receipt': binding(sem_exec), 'qa_execution_receipt': binding(qa_exec),
            'prepared_generated_xml': binding(xml_path), 'prepared_input_report': binding(prep_path),
            'producer_recorded_science_assets': {'bi4_sha256': prepared.get('bi4_sha256'), 'motion_dat_sha256': next((a.get('sha256') for a in prepared.get('assets', []) if str(a.get('relative_name', '')).endswith('.dat')), None), 'read_or_hashed_here': False},
            'future_typed_receipt_sha256': None, 'future_conversion_report_sha256': None, 'future_trajectory_h5_sha256': None,
            'source_only': True, 'no_science_payloads_read_or_hashed_here': True,
        }
        dump(scope_path, scope_doc)
        old_native_root = str(Path(str(template['native_receipt'])).resolve().parent)
        actual_native_root = str(actual['output_root'])
        command = [str(x).replace(old_native_root, actual_native_root) for x in template['command']]
        attempt = f'root-stage1-f2-{cid.lower()}-full401-typed-nvme-native420-421-107'
        typed_root = DATA / 'families' / 'F2' / cid / attempt
        typed_receipt = typed_root / 'execution-receipt.json'; report_path = typed_root / 'conversion-report.json'; h5_path = typed_root / 'trajectory.h5'
        files = closure_from_template(template)
        raw_gencase_receipt = Path(str(template['gencase_receipt'])).resolve()
        static_add = [HERE / 'workers/fresh107_legacy_scope_probe.py', HERE / 'metadata/scope-probe-input.json', HERE / 'evidence/legacy-scope-probe.json', scope_path,
                      FRESH106 / 'F2_STAGE1_FRESH106_ACTUAL_QA_SEMANTIC_NATIVE_BINDING_MANIFEST.json', Path(mrow['native_request']['path']).resolve(),
                      sem_path, qa_path, sem_exec, qa_exec, actual['receipt_path'], raw_gencase_receipt, xml_path, prep_path, RUNTIME, STRICT, ROOT142, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT, GPU_POLICY, RESOURCE]
        for p in unique_paths(static_add): add_static(files, p)
        input_files = sorted(files)
        native_attempt = str(actual['receipt'].get('request', {}).get('attempt_id', actual['receipt_path'].parent.name))
        gate = {'qa_semantic_actual': bool(mrow['gate']['enable_eligible']), 'native_receipt_completed0': True, 'native_output_paths_present': True,
                'recipe_matches': bool(actual['recipe']['tmax_s'] == 4.0 and actual['recipe']['tout_s'] == 0.01), 'frame_count_actual': None, 'frame_completeness_audited': False}
        typed = dict(template)
        typed.update({
            'schema': 'ds02.runner-request.v3', 'fresh_id': FRESH_ID, 'scope_id': SCOPE, 'attempt_id': attempt, 'command': command,
            'cwd': str(LAB), 'worktree_root': str(INFRA), 'kind': 'cpu', 'cpu_task_kind': 'conversion', 'launch_owner': 'root', 'root_only': True,
            'execution_allowed': False, 'launch_allowed': False, 'launch': False, 'disabled': True, 'source_only': True, 'future_hashes_null': True,
            'max_wall_seconds': 5400, 'cpu_threads': 2, 'estimated_storage_bytes': 34359738368,
            'depends_on_attempts': [str(template.get('gencase_attempt_id')), str(template.get('initial_qa_attempt_id')), native_attempt],
            'gencase_receipt': str(sem_path), 'gencase_receipt_sha256': sha_static(sem_path), 'gencase_receipt_semantics': 'Root419 completed0 fresh105 semantic receipt; raw GenCase receipt immutable',
            'initial_qa_report': str(qa_path), 'initial_qa_report_sha256': sha_static(qa_path), 'initial_qa_execution_receipt': str(qa_exec), 'initial_qa_execution_receipt_sha256': sha_static(qa_exec),
            'initial_qa_gate': {'passed': True, 'required_attempt': str(mrow['gate']['case_id'] and Path(mrow['actual_qa_report']['path']).parent.name), 'report_sha256': sha_static(qa_path), 'execution_returncode': 0},
            'semantic_receipt': str(sem_path), 'semantic_receipt_sha256': sha_static(sem_path), 'semantic_execution_receipt': str(sem_exec), 'semantic_execution_receipt_sha256': sha_static(sem_exec),
            'native_receipt': str(actual['receipt_path']), 'native_receipt_sha256': actual['receipt_binding']['sha256'], 'native_attempt_id': native_attempt,
            'native_output_root': str(actual['output_root']), 'native_solver_log': str(actual['run_out']), 'native_data_root': str(actual['data_root']), 'native_output_metadata': actual['output_metadata'],
            'actual_native_gate': gate, 'expected_dimension': 3, 'expected_native_frames': 401, 'expected_particles': 418104,
            'prepared_particle_counts': {'fixed': 372840, 'moving': 24150, 'fluid': 21114, 'floating': 0}, 'prepared_generated_xml': str(xml_path), 'prepared_generated_xml_sha256': sha_static(xml_path), 'prepared_input_report': str(prep_path), 'prepared_input_report_sha256': sha_static(prep_path),
            'typed_receipt': str(typed_receipt), 'typed_receipt_sha256': None, 'conversion_report': str(report_path), 'conversion_report_sha256': None, 'trajectory_h5': str(h5_path), 'trajectory_h5_sha256': None,
            'future_input_files': [str(actual['data_root']), str(actual['run_out'])], 'future_input_sha256': {str(actual['data_root']): None, str(actual['run_out']): None},
            'future_outputs': {'execution_receipt': str(typed_receipt), 'conversion_report': str(report_path), 'trajectory_h5': str(h5_path), 'typed_h5_sha256': None},
            'expected_output_contract': {'dimension': 3, 'native_frames_from_recipe': 401, 'window_s': 4.0, 'save_interval_s': 0.01, 'particle_counts_from_actual_semantic_receipt': {'total': 418104, 'fluid': 21114, 'fixed': 372840, 'moving': 24150, 'floating': 0}, 'actual_typed_frame_count': None},
            'physical_condition_sha256': scope_sha, 'source_plan_physical_condition_sha256': owner.get('source_plan_physical_condition_sha256'), 'prospective_legacy_scope_sha256': scope_sha,
            'actual_converter_physical_condition_sha256': None, 'canonical_physical_binding_sha256': None, 'canonical_grant': False, 'producer_scope_schema': 'legacy-owner-scope.v0', 'typed_scope_owner': str(scope_path), 'typed_scope_owner_sha256': sha_static(scope_path),
            'metadata_only_scope_probe': {'callable': 'ds_data02_direct_convert._physical_condition_scope(owner)', 'canonical_hash': 'ds_data02_direct_convert.canonical_hash(scope)', 'scope_sha256': scope_sha, 'private_module_import': True, 'actual_conversion_executed': False},
            'resource_contract': {'conversion_concurrency': 2, 'cpu_threads': 2, 'home_min_free_bytes': 536870912000, 'nvme_free_space_floor_bytes': 107374182400, 'nvme_staging_peak_limit_bytes': 25769803776, 'nvme_staging_root': '/tmp/ds02-nvme-conversion', 'max_wall_seconds': 5400},
            'nvme_policy': {'global_cap': 2, 'home_floor_bytes': 536870912000, 'nvme_floor_bytes': 107374182400, 'stage_peak_limit_bytes': 25769803776, 'root_owned': True},
            'strict_guard_digest': GUARD_SHA, 'strict_dispatch_file_sha256': STRICT_SHA, 'strict_guard': {'source_only': True, 'worktree_root': str(INFRA), 'input_closure': 'static metadata hashes verified; raw native outputs/DAT/BI4 are producer-only; future H5 null', 'runtime_v2_validate_request_called': False},
            'input_files': input_files, 'input_sha256': {p: files[p] for p in input_files},
            'root230_dispatch': {'policy': str(ROOT230), 'launch': str(ROOT230LAUNCH), 'resolved_gpu_uuid': None, 'lease_handle': None, 'source_agent_must_not_resolve': True},
            'disabled_reason': 'Root421 native completed0 is bound by JSON receipt and output-path metadata. Enable only after Root reviews typed scope and reserves NVMe cap2; converter will produce fresh H5/report/receipt. No native restart, canonical/Q-N/production grant, or frame-completeness claim.',
            'root_review_required': True, 'enable_eligible': True, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True,
            'qualification_claim': 'none', 'production_claim': 'none', 'numerical_precision_status': 'not accepted',
        })
        typed_path = HERE / 'requests' / f'{cid}-typed-nvme-native420-421-actual-disabled.json'; dump(typed_path, typed)
        closure = typed_command_closure(typed)
        scope_doc['typed_request'] = binding(typed_path); scope_doc['typed_request']['sha256'] = sha_static(typed_path); dump(scope_path, scope_doc)
        # CSV reuse is an immutable metadata handoff; it never starts PartVTK.
        # Root416 requests are retained verbatim.  Several of them did not carry
        # a CSV producer record because PartVTK was not in their command closure;
        # Root417's completed report is the producer authority for this new
        # read-only reuse request.
        upstream = load(FRESH106 / 'evidence/upstream-actual-binding.json')
        u = next(x for x in upstream['cases'] if x['case_id'] == cid)
        qa_request_binding = mrow.get('qa_request') or u['qa_request']
        qa_request_path = Path(str(qa_request_binding['path'])).resolve()
        qa_request = load(qa_request_path)
        qa_report = load(qa_path)
        upstream_csv = qa_request.get('registered_existing_csv') or {}
        report_csv = ((qa_report.get('csv_summary') or {}).get('csv') or {})
        if upstream_csv.get('path') and upstream_csv.get('sha256'):
            csv_info = dict(upstream_csv)
            digest_source = 'Root416 producer record'
        else:
            csv_info = dict(report_csv)
            digest_source = 'Root417 actual QA report producer record'
        csv_path = Path(str(csv_info.get('path'))).resolve() if csv_info.get('path') else None
        csv_sha = csv_info.get('sha256')
        command = [str(x) for x in qa_request.get('command') or []]
        expected = command[command.index('--expected-csv-sha256') + 1] if '--expected-csv-sha256' in command else None
        old_input_files = {str(Path(x).resolve()) for x in qa_request.get('input_files', [])}
        old_input_sha = {str(Path(k).resolve()): v for k, v in (qa_request.get('input_sha256') or {}).items()}
        root416_command_csv_present = '--csv' in command
        root416_command_csv_closure = bool(csv_path and csv_sha and expected == csv_sha and str(csv_path) in old_input_files and old_input_sha.get(str(csv_path)) == csv_sha)
        historical_qa_closure = ((u.get('command_input_closure') or {}).get('qa_request') or {})
        root416_partvtk_missing = sorted(str(x) for x in historical_qa_closure.get('missing_command_inputs', [])
                                         if Path(str(x)).name == 'PartVTK_linux64')
        report_csv_matches = bool(csv_path and isinstance(csv_sha, str) and len(csv_sha) == 64 and
                                  str(report_csv.get('path')) == str(csv_path) and report_csv.get('sha256') == csv_sha)
        # This is a producer-record binding, so it may pass without reopening
        # the CSV.  The old Root416 closure is reported separately and remains
        # false when its PartVTK command input was absent.
        csv_closure = report_csv_matches
        csv_req = {'schema': 'ds02.f2.stage1.fresh107.csv-reuse-binding-request.v1', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'case_id': cid,
                   'attempt_id': f'root-stage1-f2-{cid.lower()}-initial-qa-csv-reuse-107', 'kind': 'cpu', 'cpu_task_kind': 'audit', 'source_only': True,
                   'execution_allowed': False, 'launch_allowed': False, 'disabled': True, 'reuse_only': True, 'no_partvtk_rerun_required': True,
                   'actual_qa_report': binding(qa_path), 'actual_qa_execution_receipt': binding(qa_exec), 'root416_request': binding(qa_request_path),
                   'registered_csv': {'path': str(csv_path) if csv_path else None, 'sha256': csv_sha, 'read_or_hashed_here': False, 'digest_source': digest_source, 'producer_record': 'Root417 actual-initial-qa.json csv_summary.csv'},
                   'command_input_closure': {'csv_in_new_reuse_binding': bool(csv_path and csv_sha), 'actual_report_csv_producer_record_present': report_csv_matches,
                                             'upstream_root416_command_csv_present': root416_command_csv_present, 'upstream_root416_command_csv_closure': root416_command_csv_closure,
                                             'upstream_root416_partvtk_missing_inputs': root416_partvtk_missing,
                                             'upstream_root416_partvtk_gap_preserved': bool(root416_partvtk_missing), 'passed': csv_closure},
                   'future_hashes_null': True, 'no_arrays_read': True, 'no_jobs_started': True, 'no_shared_registry_write': True, 'raw_csv_not_read_or_hashed_here': True,
                   'disabled_reason': 'Existing Root417 CSV/QA evidence is reusable; this request is a metadata closure only and must not rerun PartVTK. Root416 input-closure gaps remain disclosed.'}
        csv_req_path = HERE / 'requests' / f'{cid}-initial-qa-csv-reuse-disabled.json'; dump(csv_req_path, csv_req)
        csv_rows.append({'case_id': cid, 'request': binding(csv_req_path), 'closure': csv_req['command_input_closure']})
        row = {'case_id': cid, 'typed_request': binding(typed_path), 'typed_command_closure': closure, 'typed_attempt_id': attempt,
               'scope_owner': binding(scope_path), 'legacy_scope_sha256': scope_sha, 'source_plan_sha256': owner.get('source_plan_physical_condition_sha256'),
               'actual_native_receipt': actual['receipt_binding'], 'actual_native_status': 'completed/0', 'actual_native_output_metadata': actual['output_metadata'], 'frame_count_actual': None,
               'actual_qa_report': binding(qa_path), 'actual_semantic_receipt': binding(sem_path), 'enable_eligible': bool(closure['passed']), 'future_typed_hashes_null': True,
               'csv_reuse_request': binding(csv_req_path), 'csv_reuse_closure': csv_req['command_input_closure']}
        rows.append(row); all_ready = all_ready and bool(closure['passed']) and bool(csv_closure)
    dump(HERE / 'evidence/csv-reuse-closure.json', {'schema': 'ds02.f2.stage1.fresh107.csv-reuse-closure.v1', 'case_count': 16, 'all_csv_closures_pass': all(x['closure']['passed'] for x in csv_rows), 'partvtk_reruns_required': False, 'raw_csv_read_or_hashed_here': False, 'cases': csv_rows})
    validation = {'schema': 'ds02.f2.stage1.fresh107.source-validation.v1', 'fresh_id': FRESH_ID, 'case_count': 16,
                  'actual_native_completed0_count': sum(1 for x in rows if x['actual_native_status'] == 'completed/0'), 'typed_requests_disabled': all(not load(Path(x['typed_request']['path'])).get('execution_allowed') for x in rows),
                  'all_typed_command_closures_pass': all(x['typed_command_closure']['passed'] for x in rows), 'all_csv_reuse_closures_pass': all(x['csv_reuse_closure']['passed'] for x in rows),
                  'typed_completed0_count': 0, 'future_h5_hashes_null': all(load(Path(x['typed_request']['path'])).get('trajectory_h5_sha256') is None for x in rows),
                  'actual_converter_scope_sha256_claimed': 0, 'canonical_grant': False, 'native_restarted': False, 'runtime_v2_validate_request_called': False,
                  'scientific_payloads_read_or_hashed_here': [], 'status': 'pass' if all_ready else 'review'}
    dump(HERE / 'evidence/fresh107-source-validation.json', validation)
    dump(HERE / 'F2_STAGE1_FRESH107_ACTUAL_NATIVE_TYPED_SCOPE_BIND_MANIFEST.json', {'schema': 'ds02.f2.stage1.fresh107.actual-native-typed-scope-bind-manifest.v1', 'fresh_id': FRESH_ID, 'family_id': 'F2', 'scope_id': SCOPE, 'case_count': 16, 'cases': rows, 'all_typed_requests_disabled': True, 'actual_native_completed0_count': 16, 'typed_completed0_count': 0, 'csv_reuse_case_count': 16, 'canonical_grant': False, 'independent_case_count_increment': 0, 'future_h5_hashes_null': True, 'scientific_payloads_read_or_hashed_here': [], 'source_only_disclosure': 'Root420/421 native receipt JSON is actual completed/0; native frame count remains unclaimed until a downstream typed/report audit. Typed requests are disabled for Root-owned NVMe cap2 execution.'})
    dump(HERE / 'metadata/contracts/typed-binding-contract.json', {'schema': 'ds02.f2.stage1.fresh107.typed-binding-contract.v1', 'native_recipe': {'frames_from_request': 401, 'window_s': 4.0, 'save_interval_s': 0.01, 'dimension': 3}, 'counts': {'total': 418104, 'fluid': 21114, 'fixed': 372840, 'moving': 24150, 'floating': 0}, 'scope': {'callable': 'ds_data02_direct_convert._physical_condition_scope(owner)', 'hash_callable': 'ds_data02_direct_convert.canonical_hash(scope)', 'schema': 'legacy-owner-scope.v0', 'canonical_grant': False, 'actual_converter_scope_sha256': None}, 'nvme': {'global_cap': 2, 'stage_peak_limit_bytes': 25769803776, 'nvme_free_floor_bytes': 107374182400, 'home_free_floor_bytes': 536870912000}, 'future_h5_sha256': None, 'source_only': True})
    dump(HERE / 'metadata/contracts/csv-reuse-contract.json', {'schema': 'ds02.f2.stage1.fresh107.csv-reuse-contract.v1', 'existing_root417_qa_reused': True, 'partvtk_rerun': False, 'csv_hash_policy': 'carry Root416 producer SHA; source builder never reads or hashes CSV', 'all_scientific_checks_retain_root417_report': True})
    print(json.dumps({'status': validation['status'], 'fresh_id': FRESH_ID, 'case_count': 16, 'native_completed0': 16, 'typed_requests_disabled': True, 'typed_command_closures_pass': validation['all_typed_command_closures_pass'], 'csv_reuse_closures_pass': validation['all_csv_reuse_closures_pass'], 'typed_completed0': 0, 'scientific_payloads_read_or_hashed': []}, indent=2, sort_keys=True))
    return 0 if validation['status'] == 'pass' else 2


if __name__ == '__main__':
    raise SystemExit(main())
