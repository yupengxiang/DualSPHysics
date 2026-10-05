from __future__ import annotations
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'expected JSON object: {path}')
    return value


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    pkg = args.package.resolve()
    aggregate = load(pkg / 'floatinginfo/state0-binding.json')
    index = load(pkg / 'floatinginfo/state0-request-index.json')
    snapshot = load(pkg / 'metadata/root563-native-snapshot.json')
    manifest = load(pkg / 'manifest.json')
    errors: list[str] = []
    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)
    check(aggregate.get('schema') == 'ds02.f6.fresh091.floatinginfo-state0-binding.v1', 'aggregate schema')
    check(aggregate.get('case_count') == 24 and len(aggregate.get('cases', [])) == 24, 'aggregate count')
    check(aggregate.get('disabled') is True and aggregate.get('execution_allowed') is False, 'aggregate disabled')
    check(aggregate.get('one_case_requests') is True and aggregate.get('no_all_cases_completion_gate') is True, 'aggregate one-case contract')
    check(index.get('case_count') == 24 and len(index.get('requests', [])) == 24, 'index count')
    check(snapshot.get('case_count') == 24 and len(snapshot.get('cases', [])) == 24, 'snapshot count')
    check(aggregate.get('actual_native_receipts_completed0_at_snapshot') == snapshot.get('completed0_count'), 'snapshot completed count')
    check(aggregate.get('actual_native_receipts_pending_or_nonterminal_at_snapshot') == snapshot.get('nonterminal_or_missing_count'), 'snapshot pending count')
    worker = pkg / 'workers/run_f6_state0_omega_fresh091_singlecase.py'
    audit = pkg / 'workers/audit_f6_endpoint_floatinginfo_state0_fresh091.py'
    check(worker.is_file() and audit.is_file(), 'worker files present')
    source_texts = {}
    for path in (worker, audit, pkg / 'workers/validate_fresh091_state0_requests.py'):
        if path.is_file():
            source = path.read_text(encoding='utf-8')
            source_texts[str(path)] = source
            try:
                ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                errors.append(f'python syntax: {path}: {exc}')
    check('import numpy' not in source_texts.get(str(worker), '') and 'import h5py' not in source_texts.get(str(worker), ''), 'worker must stay stdlib bounded')
    check('FloatingInfo' in source_texts.get(str(worker), ''), 'worker official FloatingInfo command')
    check('V0=0' in source_texts.get(str(worker), ''), 'worker V0 boundary')
    check('Root146' not in source_texts.get(str(worker), ''), 'worker must not use Root146')
    req_by_case: dict[str, dict[str, Any]] = {}
    entry_by_case = {entry.get('case_id'): entry for entry in index.get('requests', [])}
    snap_by_case = {entry.get('case_id'): entry for entry in snapshot.get('cases', [])}
    for path in sorted((pkg / 'floatinginfo/requests').glob('*.json')):
        request = load(path)
        case = request.get('case')
        case_id = case.get('case_id') if isinstance(case, dict) else None
        check(request.get('schema') == 'ds02.f6.fresh091.floatinginfo-state0-request.v1', f'{path.name}: schema')
        check(request.get('case_count') == 1 and isinstance(case, dict), f'{path.name}: one case')
        if not isinstance(case, dict) or not case_id:
            continue
        check(case_id not in req_by_case, f'duplicate request case {case_id}')
        req_by_case[case_id] = request
        check(request.get('disabled') is True and request.get('execution_allowed') is False and request.get('launch_allowed') is False, f'{case_id}: disabled')
        check(request.get('cpu_task_kind') == 'audit' and request.get('cpu_threads') == 2, f'{case_id}: CPU audit profile')
        check(request.get('launch_owner') == 'root' and request.get('root_only') is True, f'{case_id}: root ownership')
        check(request.get('root_actual_native_entry', '').endswith('/root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py'), f'{case_id}: Root230 entry')
        check('Root146' not in str(request.get('root_entry_policy', '')), f'{case_id}: Root146 policy')
        check(request.get('future_hashes_null') is True, f'{case_id}: future null')
        fut = case.get('future_outputs', {})
        check(isinstance(fut, dict) and all(fut.get(k) is not None for k in ('execution_receipt', 'audit', 'summary')), f'{case_id}: future paths')
        check(fut.get('observed_omega_rad_s') is None and fut.get('execution_receipt_sha256') is None and fut.get('audit_sha256') is None and fut.get('summary_sha256') is None, f'{case_id}: future hashes')
        contract = request.get('expected_native_contract', {})
        for key, expected in {'dimension': 3, 'total': 417505, 'fluid': 327680, 'fixed': 73441, 'floating': 16384, 'floating_type': 2, 'floating_mk': 60}.items():
            check(contract.get(key) == expected, f'{case_id}: contract {key}')
        check(contract.get('center_m') == [2.4, 1.2, 1.08], f'{case_id}: center')
        mass = request.get('mass_policy', {})
        check(mass.get('physical_mass_kg') == 128.0 and mass.get('native_support_mass_kg') == 256.0 and mass.get('normalization') == 'none' and mass.get('equality_required') is False, f'{case_id}: mass policy')
        check(request.get('particle_v0_policy') == 'V0=0 does not prove zero angular velocity', f'{case_id}: V0 policy')
        check(isinstance(case.get('declared_omega_rad_s'), list) and len(case['declared_omega_rad_s']) == 3, f'{case_id}: omega declaration')
        binding = Path(request['binding'])
        check(binding.is_file(), f'{case_id}: binding exists')
        if binding.is_file():
            check(sha256(binding) == request.get('binding_sha256'), f'{case_id}: binding sha')
            bd = load(binding)
            check(bd.get('case_id') == case_id and bd.get('case_count') == 1 and bd.get('disabled') is True, f'{case_id}: binding shape')
            check(bd.get('actual_native', {}).get('root563_request_sha256') == case.get('actual_native', {}).get('root563_request_sha256'), f'{case_id}: root request sha closure')
        actual = case.get('actual_native', {})
        receipt = Path(str(actual.get('solver_receipt', '')))
        snap = snap_by_case.get(case_id, {})
        check(snap.get('receipt') == str(receipt), f'{case_id}: snapshot receipt path')
        snapshot_terminal = snap.get('status_at_snapshot') == 'completed' and snap.get('returncode_at_snapshot') == 0
        if snapshot_terminal:
            check(isinstance(snap.get('receipt_sha256'), str) and len(snap['receipt_sha256']) == 64, f'{case_id}: completed receipt sha')
            check(actual.get('solver_receipt_sha256') == snap.get('receipt_sha256'), f'{case_id}: actual receipt sha')
            check(receipt.is_file() and sha256(receipt) == snap.get('receipt_sha256'), f'{case_id}: receipt actual hash')
        else:
            check(actual.get('solver_receipt_sha256') is None, f'{case_id}: nonterminal receipt must be null')
        check(actual.get('run_out_sha256') is None, f'{case_id}: Run.out hash must be null')
        input_sha = request.get('input_sha256', {})
        check(input_sha.get(str(binding)) == request.get('binding_sha256'), f'{case_id}: input binding sha')
        check(input_sha.get(str(receipt)) == actual.get('solver_receipt_sha256'), f'{case_id}: input receipt sha')
        check(request.get('state0_audit_contract', {}).get('one_case_only') is True, f'{case_id}: state0 one-case')
        check(request.get('state0_audit_contract', {}).get('csv_sha256') is None, f'{case_id}: CSV hash policy')
    check(len(req_by_case) == 24, f'request files cover 24 cases: {len(req_by_case)}')
    check(set(req_by_case) == set(entry_by_case), 'request index case closure')
    check(set(req_by_case) == set(snap_by_case), 'snapshot case closure')
    for case_id, entry in entry_by_case.items():
        request = req_by_case.get(case_id)
        if request is None:
            continue
        path = pkg / 'floatinginfo/requests' / Path(entry['request']).name
        check(path.is_file(), f'{case_id}: index request path')
        if path.is_file():
            check(sha256(path) == entry.get('request_sha256'), f'{case_id}: index request sha')
        check(entry.get('binding_sha256') == request.get('binding_sha256'), f'{case_id}: index binding sha')
    # Verify manifest entries against the package files.  The manifest itself is
    # deliberately excluded so the listing has no self-hash cycle.
    for item in manifest.get('files', []):
        path = pkg / item['path']
        check(path.is_file(), f'manifest missing {item["path"]}')
        if path.is_file():
            check(sha256(path) == item.get('sha256'), f'manifest hash {item["path"]}')
    report = {
        'schema': 'ds02.f6.fresh091.validation-report.v1',
        'package': str(pkg),
        'case_count': len(req_by_case),
        'completed0_snapshot_count': snapshot.get('completed0_count'),
        'nonterminal_or_missing_snapshot_count': snapshot.get('nonterminal_or_missing_count'),
        'checks': {
            'one_case_disabled_requests': not any('one case' in e or 'disabled' in e for e in errors),
            'root230_cpu2_policy': not any('CPU' in e or 'Root230' in e or 'Root146' in e for e in errors),
            'actual_completed_receipt_hashes': not any('receipt' in e for e in errors),
            'future_hashes_null': not any('future' in e or 'CSV hash' in e for e in errors),
            'manifest_closure': not any('manifest' in e for e in errors),
        },
        'errors': errors,
        'pass': not errors,
        'read_policy': 'validator reads JSON metadata and terminal receipt JSON only; it does not read/hash BI4/H5/CSV/DAT/particle arrays.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'pass': report['pass'], 'errors': len(errors), 'output': str(args.output)}, indent=2))
    return 0 if not errors else 1

if __name__ == '__main__':
    raise SystemExit(main())
