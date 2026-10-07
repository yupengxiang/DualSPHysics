#!/usr/bin/env python3
"""Metadata-only fresh102 contract validator.

It verifies Root142 admission fields, Root699 XMF registration metadata, the
literal binding contract consumed by export_xmf.py, and null future outputs.
It never opens or hashes H5/BI4/CSV/DAT scientific payloads and never launches.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
ROOT699 = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_actual607_658_full241_N3_XMF_worker_binding_repair1_699')
INTEGRATION_ROOT = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
INTEGRATION_CWD = INTEGRATION_ROOT / 'lagrangian-fluid-lab'
REQUIRED = ('family_id', 'case_id', 'attempt_id', 'kind', 'command', 'cwd', 'max_wall_seconds', 'cpu_threads', 'estimated_storage_bytes', 'input_files', 'worktree_root')
XMF_LITERAL = ('bound_metadata_sha256', 'conversion_report', 'expected_frames', 'physical_case_id', 'physical_condition_sha256', 'physical_window_s', 'producer_scope_schema', 'native_receipt', 'trajectory_h5', 'typed_receipt')
SCIENTIFIC_SUFFIXES = {'.h5', '.hdf5', '.bi4', '.ibi4', '.csv', '.dat'}

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

def validate_required_fields(request: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED if key not in request]
    if missing:
        raise ContractError('missing request field(s): ' + ', '.join(missing))
    require(request['kind'] == 'cpu', 'renderer must be CPU audit kind')
    require(request.get('cpu_task_kind') == 'audit', 'renderer CPU task kind')
    require(isinstance(request['command'], list) and request['command'] and all(isinstance(x, str) for x in request['command']), 'command argv')
    require(isinstance(request['input_files'], list) and request['input_files'], 'input provenance')
    require(isinstance(request['worktree_root'], str) and Path(request['worktree_root']).is_absolute(), 'absolute worktree_root')
    require(isinstance(request['cwd'], str) and Path(request['cwd']).is_absolute(), 'absolute cwd')
    require(request['worktree_root'] == str(INTEGRATION_ROOT), 'Root142 worktree_root must be integration checkout')
    require(request['cwd'] == str(INTEGRATION_CWD), 'Root142 cwd must be integration campaign directory')
    require(isinstance(request['estimated_storage_bytes'], int) and request['estimated_storage_bytes'] > 0, 'positive estimated storage')
    require(isinstance(request['max_wall_seconds'], int) and request['max_wall_seconds'] > 0, 'positive wall limit')
    require(isinstance(request['cpu_threads'], int) and request['cpu_threads'] >= 1, 'positive CPU threads')

def literal_binding_fields(worker: Path) -> set[str]:
    # The official exporter uses direct binding[...] access, binding.get(...),
    # and a literal tuple iterated for receipt fields. Collect only the
    # contract names from its AST string constants; do not execute it.
    tree = ast.parse(worker.read_text(encoding='utf-8'))
    fields = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in XMF_LITERAL:
            fields.add(node.value)
    return fields

def future_null(obj: dict[str, Any], label: str) -> None:
    for key, value in obj.get('future_outputs', {}).items():
        if key.endswith('_sha256') or key in {'frames_sha256', 'gif_sha256', 'pvsm_sha256', 'report_sha256'}:
            require(value is None, f'{label}: fabricated future output hash {key}')
    require(obj.get('future_hashes_null') is True, f'{label}: future hash guard')
    for key, value in obj.get('future_input_sha256', {}).items():
        require(value is None, f'{label}: fabricated future input hash {key}')

def validate_registration(obj: dict[str, Any], case: str) -> dict[str, Any]:
    reg = obj.get('xmf_registration_699')
    require(isinstance(reg, dict), f'{case}: Root699 registration missing')
    require(reg.get('schema') == 'ds02.f6.fresh102.root699-xmf-registration.v1', f'{case}: registration schema')
    req_path = Path(reg['registered_request']); bind_path = Path(reg['registered_binding'])
    require(req_path.is_file() and bind_path.is_file(), f'{case}: Root699 metadata files missing')
    require(sha(req_path) == reg.get('registered_request_sha256'), f'{case}: Root699 request digest')
    require(sha(bind_path) == reg.get('registered_binding_sha256'), f'{case}: Root699 binding digest')
    root_req = load(req_path); root_bind = load(bind_path)
    require(root_req.get('case_id') == case and root_bind.get('case_id') == case, f'{case}: Root699 case identity')
    require(root_req.get('binding') == str(bind_path), f'{case}: Root699 binding path')
    require(root_req.get('disabled') is False and root_req.get('execution_allowed') is True and root_req.get('launch_allowed') is True, f'{case}: Root699 registration flags')
    require(root_req.get('worktree_root') == str(INTEGRATION_ROOT), f'{case}: Root699 worktree_root')
    require(root_req.get('cwd') == str(INTEGRATION_CWD), f'{case}: Root699 cwd')
    require(isinstance(root_req.get('estimated_storage_bytes'), int) and root_req['estimated_storage_bytes'] > 0, f'{case}: Root699 storage')
    require(root_bind.get('expected_frames') == 241 and root_bind.get('expected_particles') == 417505, f'{case}: Root699 binding dimensions')
    require(root_req.get('expected_native_frames') == 241 and root_req.get('expected_particles') == 417505, f'{case}: Root699 request dimensions')
    require(reg.get('attempt_id') == root_req.get('attempt_id'), f'{case}: Root699 attempt id')
    require(reg.get('attempt_root') == root_req.get('attempt_root'), f'{case}: Root699 attempt root')
    manifest = Path(root_req['actual_manifest'])
    attempt_root = Path(root_req['attempt_root'])
    require(manifest == attempt_root / 'xdmf/manifest.json', f'{case}: Root699 manifest path')
    require(reg.get('future_manifest') == str(manifest), f'{case}: derived manifest path')
    require(reg.get('future_case') == str(manifest.parent / 'case.xmf'), f'{case}: derived case path')
    require(reg.get('future_receipt') == str(attempt_root / 'execution-receipt.json'), f'{case}: derived receipt path')
    for key in ('future_case_sha256', 'future_manifest_sha256', 'future_receipt_sha256'):
        require(reg.get(key) is None, f'{case}: fabricated Root699 future hash {key}')
    require(reg.get('status') == 'root699_registered_waiting_terminal_xmf_receipt_and_manifest', f'{case}: Root699 status')
    return root_req

def validate_closure(obj: dict[str, Any], label: str) -> None:
    files = obj['input_files']; hashes = obj.get('input_sha256', {})
    require(set(files) == set(hashes), f'{label}: input closure key mismatch')
    for text in files:
        path = Path(text)
        require(path.is_file(), f'{label}: missing input {path}')
        require(path.suffix.lower() not in SCIENTIFIC_SUFFIXES, f'{label}: scientific payload in source closure {path}')
        require(sha(path) == hashes[text], f'{label}: input digest mismatch {path}')

def main() -> int:
    requests = sorted((PACKAGE / 'requests/render').glob('*.json'))
    bindings = sorted((PACKAGE / 'bindings/render').glob('*.json'))
    require(len(requests) == len(bindings) == 24, 'fresh102 must contain 24 request/binding pairs')
    worker = PACKAGE / 'workers/render_native023.py'
    require(worker.is_file(), 'fresh102 renderer missing')
    worker_digest = sha(worker)
    fields = literal_binding_fields(Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_100_actual_root607_root658_xmf_native023_render_v1/workers/export_xmf.py'))
    require(set(XMF_LITERAL) <= fields, f'official XMF worker literal fields incomplete: {sorted(fields)}')
    details = []
    for request_path, binding_path in zip(requests, bindings):
        request = load(request_path); binding = load(binding_path)
        case = request.get('case_id')
        require(case and binding.get('case_id') == case, f'{request_path}: case identity')
        require(request.get('fresh_id') == 'fresh102' and binding.get('fresh_id') == 'fresh102', f'{case}: fresh identity')
        require(request.get('disabled') is True and request.get('execution_allowed') is False and request.get('launch_allowed') is False, f'{case}: request enabled')
        require(binding.get('disabled') is True and binding.get('execution_allowed') is False and binding.get('launch_allowed') is False, f'{case}: binding enabled')
        validate_required_fields(request)
        require(request.get('expected_frames') == 241 and binding.get('expected_frames') == 241, f'{case}: expected_frames')
        require(request.get('expected_particles') == 417505 and binding.get('expected_particles') == 417505, f'{case}: expected_particles')
        require(request.get('cpu_threads') == 24 and request.get('declared_cpu_cores') == 24, f'{case}: CPU declaration')
        require(binding.get('cpu_threads') == 24 and binding.get('declared_cpu_cores') == 24, f'{case}: binding CPU declaration')
        require(request.get('max_wall_seconds') == 14400 and binding.get('max_wall_seconds') == 14400, f'{case}: wall')
        require(request.get('worker') == str(worker) and request.get('worker_sha256') == worker_digest, f'{case}: renderer worker')
        require(binding.get('worker') == str(worker) and binding.get('worker_sha256') == worker_digest, f'{case}: binding worker')
        require(request.get('render_binding') == str(binding_path), f'{case}: request binding path')
        require(request.get('render_binding_sha256') == sha(binding_path), f'{case}: request binding digest')
        require(binding.get('xmf_worker_literal_binding_fields') == list(XMF_LITERAL), f'{case}: worker literal-field declaration')
        root_req = validate_registration(request, case)
        dep = request.get('xmf_dependency'); require(dep and dep.get('status') == 'future_root699_xmf_receipt_and_manifest_required', f'{case}: XMF dependency')
        require(dep.get('expected_frames') == 241 and dep.get('expected_particles') == 417505, f'{case}: XMF dimensions')
        require(dep.get('receipt_sha256') is None and dep.get('case_sha256') is None and dep.get('manifest_sha256') is None, f'{case}: fabricated XMF hash')
        require(request.get('xmf_manifest_sha256') is None and request.get('xmf_case_sha256') is None, f'{case}: top-level XMF future hash')
        require(request.get('render_environment', {}).get('OMP_NUM_THREADS') == '2', f'{case}: OMP environment')
        require(request.get('render_environment', {}).get('VTK_SMP_MAX_THREADS') == '2', f'{case}: VTK environment')
        require(request.get('render_environment', {}).get('MESA_GLTHREAD') == 'false', f'{case}: MESA environment')
        require(request.get('camera_policy', {}).get('fixed_camera_override') is False, f'{case}: fixed camera override')
        require(request.get('camera_policy', {}).get('camera_bounds_in_manifest') is False, f'{case}: fixed manifest camera bounds')
        require(request.get('camera_policy', {}).get('domain_bounds_in_manifest') is False, f'{case}: fixed manifest domain bounds')
        validate_closure(request, f'{case}: request')
        validate_closure(binding, f'{case}: binding')
        future_null(request, f'{case}: request'); future_null(binding, f'{case}: binding')
        details.append({'case_id': case, 'root699_status': request['xmf_registration_699']['status'], 'expected_frames': 241, 'future_hashes_null': True})
    # Meaningful negative: this is the exact Root142 admission failure class from Root693.
    probe = {key: 'present' for key in REQUIRED}
    probe.pop('worktree_root')
    try:
        validate_required_fields(probe)
    except ContractError as error:
        require('worktree_root' in str(error), 'negative missing-worktree_root did not reject the right field')
    else:
        raise ContractError('negative missing-worktree_root was accepted')
    print(json.dumps({'status': 'pass', 'fresh_id': 'fresh102', 'cases': len(details), 'root699_registered_cases': len(details), 'expected_frames': 241, 'expected_particles': 417505, 'declared_cpu_cores': 24, 'cpu_threads': 24, 'max_wall_seconds': 14400, 'environment_threads': 2, 'future_xmf_and_render_hashes_null': True, 'required_runner_fields': list(REQUIRED), 'required_xmf_binding_fields': list(XMF_LITERAL), 'negative_missing_worktree_root': 'rejected_before_reservation', 'no_scientific_payload_read_or_hashed': True, 'details': details}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
