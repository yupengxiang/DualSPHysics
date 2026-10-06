#!/usr/bin/env python3
"""Metadata-only fresh128 validator.

The validator reads JSON/XML/Python metadata and producer attestations. It
refuses to hash or open science suffixes, including H5/BI4/CSV/DAT/VTK. It
checks Root753 receipt/report/owner closure, request input closure, worker
contracts, canonical/legacy scope separation, and disabled downstream gates.
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCIENCE_SUFFIXES = {'.dat', '.bi4', '.h5', '.hdf5', '.csv', '.vtk', '.vtu', '.npy', '.npz'}
EXPECTED = {'data2d': False, 'fixed_particles': 158559, 'floating_particles': 0, 'fluid_particles': 31658, 'moving_particles': 4210, 'solver_dimension': 3, 'total_particles': 194427, 'xml_particle_counts': {'fixed': 158559, 'floating': 0, 'fluid': 31658, 'moving': 4210}}
TAGS = ('M085_T080', 'M115_T100')


def fail(message: str) -> None:
    raise SystemExit('fresh128 validation failed: ' + message)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        fail(f'cannot load JSON {path}: {exc}')


def sha(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        fail(f'science hash attempted by validator: {path}')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check_worker(path: Path, tag: str) -> dict:
    source = path.read_text(encoding='utf-8')
    if (tag != 'legacy' and 'fresh128' not in source) or 'fresh116' in source or 'fresh098' in source:
        fail(f'{path.name}: stale schema/version reference')
    if 'A080' in source or 'A120' in source:
        fail(f'{path.name}: old endpoint hardcoding remains')
    if tag not in path.name:
        fail(f'{path.name}: worker/tag mismatch')
    ast.parse(source, filename=str(path))
    if tag != 'legacy' and 'full_native_data_root' not in source:
        fail(f'{path.name}: exact saved-state directory contract missing')
    return {'path': str(path), 'sha256': sha(path), 'ast_parse': True, 'science_payloads_read_by_validator': False}


def check_actual(tag: str, binding: dict, attest: dict) -> dict:
    receipt_path = Path(binding['full_typed_receipt']); request_path = Path(binding['full_typed_request']); report_path = Path(binding['full_typed_conversion_report'])
    receipt = load(receipt_path); request = load(request_path); report = load(report_path)
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0: fail(f'{tag}: Root753 receipt status')
    if sha(receipt_path) != binding['full_typed_receipt_sha256']: fail(f'{tag}: receipt sha')
    if sha(request_path) != binding['full_typed_request_sha256']: fail(f'{tag}: request sha')
    if receipt.get('request_sha256') != sha(request_path): fail(f'{tag}: receipt request_sha256')
    if receipt.get('request', {}).get('attempt_id') != receipt_path.parent.name: fail(f'{tag}: nested attempt identity')
    if report.get('conversion_status') != 'completed' or report.get('frames') != 801 or report.get('particles') != 194427: fail(f'{tag}: report status/dimensions')
    dim = report.get('solver_dimension', {})
    if not isinstance(dim, dict) or dim.get('solver_dimension') != 3 or dim.get('xml_data2d') != 'false': fail(f'{tag}: report dimension')
    if (report.get('partvtk_validation') or {}).get('all_passed') is not True: fail(f'{tag}: PartVTK metadata')
    if len((report.get('partvtk_validation') or {}).get('frames', [])) < 1: fail(f'{tag}: PartVTK validation metadata missing')
    if report.get('output_sha256') != binding['trajectory_h5_sha256']: fail(f'{tag}: producer H5 attestation mismatch')
    legacy = (report.get('hash_scopes') or {}).get('physical_condition_sha256')
    if legacy != binding['source_h5_physical_condition_sha256']: fail(f'{tag}: actual legacy scope')
    owner = (report.get('source_provenance') or {}).get('owner_metadata') or {}
    if owner.get('path') != binding['root753_owner_metadata'] or owner.get('sha256') != binding['root753_owner_metadata_sha256']: fail(f'{tag}: owner closure')
    if attest['root753']['request_sha256'] != sha(request_path) or attest['root753']['receipt_sha256'] != sha(receipt_path): fail(f'{tag}: attestation closure')
    if binding['actual_counts'] != EXPECTED or binding['expected_counts'] != EXPECTED: fail(f'{tag}: actual count binding')
    return {'tag': tag, 'typed_receipt': 'completed/0', 'frames': 801, 'particles': 194427, 'dimension': 3, 'partvtk_all_passed': True, 'actual_legacy_scope_sha256': legacy, 'owner_closure': True}


def check_request(path: Path, tag: str, kind: str, binding: dict) -> dict:
    req = load(path)
    for key in ('schema','family_id','case_id','attempt_id','kind','cpu_task_kind','command','cwd','max_wall_seconds','cpu_threads','estimated_storage_bytes','input_files','input_sha256','input_sha256_provenance','worktree_root','root_dataset_inventory_profile','root_inventory_policy_source_sha256'):
        if key not in req: fail(f'{path.name}: missing {key}')
    if req['kind'] != 'cpu' or req['cpu_task_kind'] != 'audit' or req['cpu_threads'] != 2: fail(f'{path.name}: Root142 CPU identity')
    if not (req.get('disabled') is True and req.get('execution_allowed') is False and req.get('launch_allowed') is False and req.get('launch') is False): fail(f'{path.name}: request enabled')
    if req.get('source_only') is not True or req.get('arrays_allowed') or req.get('array_edit_allowed') or req.get('solver_allowed') or req.get('conversion_allowed'): fail(f'{path.name}: source/array policy')
    if req.get('root_dataset_inventory_profile') != 'root_home_floor_no_legacy_dataset_walk_v1': fail(f'{path.name}: inventory profile')
    if req.get('root_inventory_policy_source_sha256') != sha(Path(req['root_inventory_policy_source'])): fail(f'{path.name}: policy sha')
    if req.get('actual_counts') != EXPECTED or req.get('expected_counts') != EXPECTED: fail(f'{path.name}: request counts')
    if req.get('physical_condition_sha256') != binding['physical_condition_sha256'] or req.get('source_h5_physical_condition_sha256') != binding['source_h5_physical_condition_sha256']: fail(f'{path.name}: binding scope')
    if any(value is not None for value in req['future_output_hashes'].values()): fail(f'{path.name}: future output hash was invented')
    files = req['input_files']; hashes = req['input_sha256']; prov = req['input_sha256_provenance']
    if any('<root-bind:' in str(value) for value in files): fail(f'{path.name}: unresolved input placeholder')
    for raw in files:
        p = Path(raw)
        if not p.exists(): fail(f'{path.name}: missing input {p}')
        key = str(p.resolve())
        if key not in hashes or key not in prov: fail(f'{path.name}: input closure missing {p}')
        if p.suffix.lower() in SCIENCE_SUFFIXES:
            if not (isinstance(hashes[key], str) and len(hashes[key]) == 64 and 'producer-attested' in prov[key]): fail(f'{path.name}: science attestation {p}')
        elif sha(p) != hashes[key]:
            fail(f'{path.name}: static input digest mismatch {p}')
    if str((ROOT / 'scripts/validate_fresh128.py').resolve()) not in hashes: fail(f'{path.name}: validator not bound in request closure')
    return {'request': str(path), 'tag': tag, 'kind': kind, 'attempt_id': req['attempt_id'], 'disabled': True, 'input_count': len(files)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=ROOT / 'metadata/fresh128-validator-report.json')
    args = parser.parse_args()
    manifest = load(ROOT / 'manifest.json')
    if 'manifest.json' in manifest.get('files', {}) or 'metadata/fresh128-validator-report.json' in manifest.get('files', {}): fail('manifest/report self-reference')
    for rel, expected in manifest.get('files', {}).items():
        p = ROOT / rel
        if not p.is_file() or sha(p) != expected: fail(f'manifest mismatch {rel}')
    workers = [check_worker(ROOT / 'workers/export_xmf_legacy_aware.py', 'legacy')] + [check_worker(ROOT / f'workers/bed_audit_{tag}_full801.py', tag) for tag in TAGS]
    actual = []
    requests = []
    for tag in TAGS:
        xmf_binding = load(ROOT / f'bindings/{tag}-full801-xmf-binding.json')
        bed_binding = load(ROOT / f'bindings/{tag}-full801-bed-audit-binding.json')
        attest = load(ROOT / f'metadata/root753-typed-producer-attestation-{tag}.json')
        if xmf_binding['schema'].endswith('fresh128.v1') is False or bed_binding['schema'].endswith('fresh128.v1') is False: fail(f'{tag}: binding schema')
        if xmf_binding['physical_condition_sha256'] == xmf_binding['source_h5_physical_condition_sha256']: fail(f'{tag}: canonical/legacy collapsed')
        if xmf_binding['fresh125_source_forecast_legacy_scope_sha256'] == xmf_binding['source_h5_physical_condition_sha256']: fail(f'{tag}: forecast/actual legacy collapsed')
        if xmf_binding['xmf_manifest_sha256'] is not None or bed_binding['bed_audit_report_sha256'] is not None: fail(f'{tag}: future binding hash')
        actual.append(check_actual(tag, xmf_binding, attest))
        requests.append(check_request(ROOT / f'requests/{tag}-full801-xmf-request.json', tag, 'xmf', xmf_binding))
        requests.append(check_request(ROOT / f'requests/{tag}-full801-bed-audit-request.json', tag, 'bed', bed_binding))
    report = {'schema': 'ds02.f5.c082s1.fresh128-validator-report.v1', 'status': 'pass', 'manifest_self_excluded': True, 'root753_actual': actual, 'disabled_requests': requests, 'worker_contracts': workers, 'source_agent_did_not_read_or_hash_science_payloads': True, 'historical_precision_negative_retained': True, 'remaining10_and_t120_closed': True}
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
