#!/usr/bin/env python3
"""Metadata-only fresh102 Root711 mixed XMF/Root023 contract validator.

The validator reads only JSON/source metadata and filesystem stat information for
Root711 completed producer paths. It never opens or hashes H5/BI4/CSV/DAT
scientific payloads and never launches a runner or renderer.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
ROOT711_REG = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_all24_mixed699success7_plus709future17_XMF_registration_711/actual-mixed24-XMF-registration.json')
INTEGRATION_ROOT = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
INTEGRATION_CWD = INTEGRATION_ROOT / 'lagrangian-fluid-lab'
OFFICIAL_XMF = INTEGRATION_CWD / 'campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_100_actual_root607_root658_xmf_native023_render_v1/workers/export_xmf.py'
REQUIRED = ('family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds', 'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root')
XMF_LITERAL = ('bound_metadata_sha256', 'conversion_report', 'expected_frames', 'physical_case_id', 'physical_condition_sha256', 'physical_window_s', 'producer_scope_schema', 'native_receipt', 'trajectory_h5', 'typed_receipt')
SCIENTIFIC_SUFFIXES = {'.h5', '.hdf5', '.bi4', '.ibi4', '.csv', '.dat'}
COMPLETED = 'actual699_completed0_N3_pass'
WAITING = 'registered709_WAIT_actual707_CPUphase_drain'

class ContractError(RuntimeError):
    pass

def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENTIFIC_SUFFIXES:
        raise ContractError(f'scientific payload hash attempted: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)

def literal_binding_fields(worker: Path) -> set[str]:
    tree = ast.parse(worker.read_text(encoding='utf-8'))
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in XMF_LITERAL
    }

def validate_required_fields(request: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED if key not in request]
    if missing:
        raise ContractError('missing request field(s): ' + ', '.join(missing))
    require(request.get('kind') == 'cpu', 'renderer must be CPU audit kind')
    require(request.get('cpu_task_kind') == 'audit', 'renderer CPU task kind')
    require(isinstance(request.get('command'), list) and request['command'] and all(isinstance(x, str) for x in request['command']), 'command argv')
    require(isinstance(request.get('input_files'), list) and request['input_files'], 'input provenance')
    require(isinstance(request.get('worktree_root'), str) and Path(request['worktree_root']).is_absolute(), 'absolute worktree_root')
    require(isinstance(request.get('cwd'), str) and Path(request['cwd']).is_absolute(), 'absolute cwd')
    require(request['worktree_root'] == str(INTEGRATION_ROOT), 'Root142 worktree_root must be integration checkout')
    require(request['cwd'] == str(INTEGRATION_CWD), 'Root142 cwd must be integration lab root')
    require(isinstance(request.get('estimated_storage_bytes'), int) and request['estimated_storage_bytes'] > 0, 'positive estimated storage')
    require(isinstance(request.get('max_wall_seconds'), int) and request['max_wall_seconds'] > 0, 'positive wall limit')
    require(isinstance(request.get('cpu_threads'), int) and request['cpu_threads'] >= 1, 'positive CPU threads')

def validate_closure(obj: dict[str, Any], label: str, *, allow_binding: Path | None = None) -> None:
    files = obj.get('input_files'); hashes = obj.get('input_sha256', {})
    require(isinstance(files, list) and isinstance(hashes, dict), f'{label}: input closure shape')
    require(set(files) == set(hashes), f'{label}: input closure key mismatch')
    for text in files:
        path = Path(text)
        require(path.is_file(), f'{label}: missing input {path}')
        require(path.suffix.lower() not in SCIENTIFIC_SUFFIXES, f'{label}: scientific payload in source closure {path}')
        require(sha(path) == hashes[text], f'{label}: input digest mismatch {path}')
    if allow_binding is not None:
        require(str(allow_binding) not in files, f'{label}: binding self-reference')

def validate_bound_metadata(binding: dict[str, Any], label: str, own_binding: Path) -> None:
    values = binding.get('bound_metadata_sha256')
    require(isinstance(values, dict), f'{label}: bound metadata map')
    require(str(own_binding) not in values, f'{label}: bound metadata self-reference')
    for text, digest in values.items():
        path = Path(text)
        require(path.is_file(), f'{label}: bound metadata missing {path}')
        require(path.suffix.lower() not in SCIENTIFIC_SUFFIXES, f'{label}: scientific bound metadata {path}')
        require(sha(path) == digest, f'{label}: bound metadata digest mismatch {path}')

def validate_root711_record(record: dict[str, Any], case: str, registry_sha: str) -> dict[str, Any]:
    require(record.get('case_id') == case, f'{case}: Root711 record identity')
    require(record.get('root711_registry_sha256') == registry_sha, f'{case}: Root711 registry digest')
    req_path = Path(record['registered_request']); bind_path = Path(record['registered_binding'])
    require(req_path.is_file() and bind_path.is_file(), f'{case}: Root711 registered metadata missing')
    require(sha(req_path) == record.get('registered_request_sha256'), f'{case}: registered request digest')
    require(sha(bind_path) == record.get('registered_binding_sha256'), f'{case}: registered binding digest')
    root_req = load(req_path); root_bind = load(bind_path)
    require(root_req.get('case_id') == case and root_bind.get('case_id') == case, f'{case}: producer metadata case')
    require(root_req.get('binding') == str(bind_path), f'{case}: producer binding pointer')
    require(root_req.get('expected_native_frames') == 241 and root_req.get('expected_particles') == 417505, f'{case}: producer request dimensions')
    require(root_bind.get('expected_frames') == 241 and root_bind.get('expected_particles') == 417505, f'{case}: producer binding dimensions')
    require(root_req.get('worktree_root') == str(INTEGRATION_ROOT), f'{case}: producer worktree_root')
    require(root_req.get('cwd') == str(INTEGRATION_CWD), f'{case}: producer cwd')
    require(isinstance(root_req.get('estimated_storage_bytes'), int) and root_req['estimated_storage_bytes'] > 0, f'{case}: producer storage')
    attempt_root = Path(record['attempt_root'])
    receipt = Path(record['producer_receipt']); manifest = Path(record['producer_manifest']); case_xmf = Path(record['producer_case_xmf'])
    require(receipt == attempt_root / 'execution-receipt.json', f'{case}: receipt path')
    require(manifest == attempt_root / 'xdmf/manifest.json', f'{case}: manifest path')
    require(case_xmf == attempt_root / 'xdmf/case.xmf', f'{case}: case path')
    status = record.get('root711_status')
    require(status in {COMPLETED, WAITING}, f'{case}: unsupported Root711 status')
    if status == COMPLETED:
        require(record.get('producer_outputs_attested') is True, f'{case}: completed output attestation')
        for key, path in [('producer_receipt_sha256', receipt), ('producer_manifest_sha256', manifest), ('producer_case_xmf_sha256', case_xmf)]:
            require(isinstance(record.get(key), str) and len(record[key]) == 64, f'{case}: completed {key}')
            require(path.is_file(), f'{case}: completed producer output missing {path}')
    else:
        require(record.get('producer_outputs_attested') is False, f'{case}: waiting output attestation')
        require(record.get('producer_receipt_sha256') is None and record.get('producer_manifest_sha256') is None and record.get('producer_case_xmf_sha256') is None, f'{case}: waiting producer hash')
    return root_req

def validate_future_null(obj: dict[str, Any], label: str) -> None:
    require(obj.get('future_hashes_null') is True, f'{label}: future render hash guard')
    for key, value in obj.get('future_outputs', {}).items():
        if key.endswith('_sha256') or key in {'frames_sha256', 'gif_sha256', 'pvsm_sha256', 'report_sha256'}:
            require(value is None, f'{label}: fabricated render hash {key}')

def main() -> int:
    require(ROOT711_REG.is_file(), 'Root711 registry missing')
    registry_sha = sha(ROOT711_REG)
    root711 = load(ROOT711_REG)
    require(root711.get('schema') == 'ds02.f6.root-mixed24-XMF-registration.v1', 'Root711 schema')
    records = {item['case_id']: item for item in root711.get('cases', [])}
    require(len(records) == 24, 'Root711 case count')
    require(sum(x.get('status') == COMPLETED for x in records.values()) == 7, 'Root711 completed count')
    require(sum(x.get('status') == WAITING for x in records.values()) == 17, 'Root711 waiting count')
    worker = PACKAGE / 'workers/render_native023.py'
    require(worker.is_file(), 'Root023 worker missing')
    worker_digest = sha(worker)
    require(OFFICIAL_XMF.is_file(), 'official XMF worker missing')
    require(set(XMF_LITERAL) <= literal_binding_fields(OFFICIAL_XMF), 'official XMF literal binding fields incomplete')
    requests = sorted((PACKAGE / 'requests/render').glob('*.json'))
    bindings = sorted((PACKAGE / 'bindings/render').glob('*.json'))
    require(len(requests) == len(bindings) == 24, 'fresh102 must contain 24 request/binding pairs')
    details = []
    for request_path, binding_path in zip(requests, bindings):
        request = load(request_path); binding = load(binding_path)
        case = request.get('case_id')
        require(case in records and binding.get('case_id') == case, f'{case}: case identity')
        require(request.get('fresh_id') == 'fresh102' and binding.get('fresh_id') == 'fresh102', f'{case}: fresh identity')
        require(request.get('disabled') is True and request.get('execution_allowed') is False and request.get('launch_allowed') is False, f'{case}: request enabled')
        require(binding.get('disabled') is True and binding.get('execution_allowed') is False and binding.get('launch_allowed') is False, f'{case}: binding enabled')
        validate_required_fields(request)
        require(request.get('expected_frames') == 241 and binding.get('expected_frames') == 241, f'{case}: expected_frames')
        require(request.get('expected_particles') == 417505 and binding.get('expected_particles') == 417505, f'{case}: expected_particles')
        require(request.get('cpu_threads') == 24 and request.get('declared_cpu_cores') == 24, f'{case}: request CPU')
        require(binding.get('cpu_threads') == 24 and binding.get('declared_cpu_cores') == 24, f'{case}: binding CPU')
        require(request.get('max_wall_seconds') == 14400 and binding.get('max_wall_seconds') == 14400, f'{case}: wall')
        require(request.get('worker') == str(worker) and request.get('worker_sha256') == worker_digest, f'{case}: request worker')
        require(binding.get('worker') == str(worker) and binding.get('worker_sha256') == worker_digest, f'{case}: binding worker')
        require(request.get('render_binding') == str(binding_path), f'{case}: binding path')
        require(request.get('render_binding_sha256') == sha(binding_path), f'{case}: binding digest')
        require(binding.get('xmf_worker_literal_binding_fields') == list(XMF_LITERAL), f'{case}: worker field declaration')
        reg = request.get('xmf_registration_711')
        require(isinstance(reg, dict), f'{case}: Root711 registration missing')
        require(reg.get('root711_status') == records[case]['status'], f'{case}: Root711 status mismatch')
        producer = validate_root711_record(reg, case, registry_sha)
        dep = request.get('xmf_dependency')
        require(isinstance(dep, dict) and dep.get('producer_status') == records[case]['status'], f'{case}: XMF dependency status')
        for key in ('expected_frames', 'expected_particles'):
            require(dep.get(key) == (241 if key == 'expected_frames' else 417505), f'{case}: dependency dimensions')
        completed = records[case]['status'] == COMPLETED
        for key, objkey in [('receipt_sha256', 'xmf_receipt_sha256'), ('case_sha256', 'xmf_case_sha256'), ('manifest_sha256', 'xmf_manifest_sha256')]:
            expected = records[case]['actual_receipt_sha256' if key == 'receipt_sha256' else 'actual_case_xmf_sha256' if key == 'case_sha256' else 'actual_manifest_sha256'] if completed else None
            require(dep.get(key) == expected, f'{case}: dependency {key}')
            require(request.get(objkey) == expected, f'{case}: top-level {objkey}')
        require(request.get('render_environment', {}).get('OMP_NUM_THREADS') == '2', f'{case}: OMP')
        require(request.get('render_environment', {}).get('VTK_SMP_MAX_THREADS') == '2', f'{case}: VTK')
        require(request.get('render_environment', {}).get('MESA_GLTHREAD') == 'false', f'{case}: MESA')
        camera = request.get('camera_policy', {})
        require(camera.get('fixed_camera_override') is False and camera.get('camera_bounds_in_manifest') is False and camera.get('domain_bounds_in_manifest') is False, f'{case}: camera clipping policy')
        validate_closure(request, f'{case}: request')
        validate_closure(binding, f'{case}: binding', allow_binding=binding_path)
        validate_bound_metadata(binding, f'{case}: bound metadata', binding_path)
        validate_future_null(request, f'{case}: request')
        validate_future_null(binding, f'{case}: binding')
        # XMF producer inputs may be attested for Root711 completed cases, but typed H5 remains null.
        future_sha = request.get('future_input_sha256', {})
        for text, value in future_sha.items():
            if Path(text).suffix.lower() in {'.h5', '.hdf5'}:
                require(value is None, f'{case}: source fabricated typed H5 hash')
        details.append({'case_id': case, 'root711_status': records[case]['status'], 'producer_outputs_attested': completed, 'expected_frames': 241, 'render_hashes_null': True})
    probe = {key: 'present' for key in REQUIRED}
    probe.pop('worktree_root')
    try:
        validate_required_fields(probe)
    except ContractError as error:
        require('worktree_root' in str(error), 'negative missing-worktree_root rejected wrong field')
    else:
        raise ContractError('negative missing-worktree_root was accepted')
    print(json.dumps({'status': 'pass', 'fresh_id': 'fresh102', 'cases': len(details), 'root711_completed_cases': sum(d['producer_outputs_attested'] for d in details), 'root711_future_cases': sum(not d['producer_outputs_attested'] for d in details), 'expected_frames': 241, 'expected_particles': 417505, 'declared_cpu_cores': 24, 'cpu_threads': 24, 'max_wall_seconds': 14400, 'environment_threads': 2, 'render_hashes_null': True, 'required_runner_fields': list(REQUIRED), 'required_xmf_binding_fields': list(XMF_LITERAL), 'negative_missing_worktree_root': 'rejected_before_reservation', 'no_scientific_payload_read_or_hashed': True, 'details': details}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
