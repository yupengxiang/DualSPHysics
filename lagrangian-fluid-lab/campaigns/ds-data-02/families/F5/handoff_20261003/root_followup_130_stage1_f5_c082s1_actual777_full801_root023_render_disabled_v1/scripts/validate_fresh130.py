#!/usr/bin/env python3
"""Metadata-only validator for the fresh130 Root023 render package.

It hashes package metadata and static tools, but never opens a scientific payload.
Producer-attested H5 hashes are compared with JSON metadata only.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'manifest.json'
REPORT = ROOT / 'metadata/fresh130-validator-report.json'
SCIENCE = {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.vtp', '.raw'}

def sha(p: Path) -> str:
    if p.suffix.lower() in SCIENCE:
        raise AssertionError(f'validator refuses science payload: {p}')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()

def read(p: Path):
    return json.loads(p.read_text())

def check(cond, msg):
    if not cond:
        raise AssertionError(msg)

m = read(MANIFEST)
check(m.get('manifest_self_excluded') is True, 'manifest self exclusion missing')
check(m.get('validator_report_excluded') is True, 'validator report exclusion missing')
for name, expected in m['files'].items():
    p = ROOT / name
    check(p.exists(), f'missing package file {name}')
    check(sha(p) == expected, f'manifest hash mismatch {name}')

checks = []
for tag in ('M085_T080', 'M115_T100'):
    b = read(ROOT / f'bindings/{tag}-full801-root023-render-binding.json')
    q = read(ROOT / f'requests/{tag}-full801-root023-render-request.json')
    x = read(ROOT / f'metadata/root777-xmf-attestation-{tag}.json')
    a = read(ROOT / f'metadata/root778-bed-attestation-{tag}.json')
    check(b['schema'].endswith('fresh130.v1'), f'{tag} binding schema')
    check(q['schema'].endswith('fresh130.v1'), f'{tag} request schema')
    check(q['disabled'] is True and q['execution_allowed'] is False, f'{tag} request disabled')
    check(q['launch'] is False and q['launch_allowed'] is False, f'{tag} launch disabled')
    check(q['kind'] == 'cpu' and q['cpu_task_kind'] == 'audit', f'{tag} runtime kind')
    check(q['cpu_threads'] == 24 and q['max_wall_seconds'] == 14400, f'{tag} render reservation')
    check(q['root_render_concurrency_cap'] == 2 and q['shared_render_concurrency_cap'] == 2, f'{tag} render cap')
    check(q['root_dataset_inventory_profile'] == 'root_home_floor_no_legacy_dataset_walk_v1', f'{tag} home profile')
    check(q['root_inventory_policy_source_sha256'] == '2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5', f'{tag} policy hash')
    check(q['input_sha256_required'] is True, f'{tag} input hash guard')
    check(q['full801_authorized'] is False and q['q_n_granted'] is False, f'{tag} promotion gate')
    check(q['independent_case_count_increment'] == 0, f'{tag} case credit')
    check(q['future_output_hashes']['render_manifest_sha256'] is None, f'{tag} future render hash')
    check(q['future_output_hashes']['render_receipt_sha256'] is None, f'{tag} future receipt hash')
    check(b['actual_bed_audit']['report_status'] == 'completed_worker_output_pending_root_review', f'{tag} bed status')
    check(b['actual_bed_audit']['physics_acceptance'] is False, f'{tag} physics status')
    check(b['actual_bed_audit']['root_visual_review_required'] is True, f'{tag} visual gate')
    check(a['frames'] == 801 and a['particle_axis_count'] == 194427, f'{tag} audit shape')
    check(a['initial_fluid_uid_count'] == 31658, f'{tag} fluid denominator')
    for key in ('one_dp', 'two_dp'):
        check(a['penetration'][key]['min_count'] == 0 and a['penetration'][key]['max_count'] == 0, f'{tag} {key} count')
        check(a['penetration'][key]['nonzero_frames'] == 0, f'{tag} {key} nonzero')
    for key in ('missing_initial_uid', 'unexpected_current_uid', 'nonfinite_position', 'nonfinite_mass', 'outside_x', 'outside_y'):
        check(a['integrity'][key]['max_count'] == 0, f'{tag} {key}')
    check(all(a['deepest_depth'][k]['nonnull_frames'] == 0 and a['deepest_depth'][k]['max_m'] is None for k in ('one_dp', 'two_dp')), f'{tag} depth')
    check(x['actual_xmf']['frames'] == 801 and x['actual_xmf']['particles'] == 194427, f'{tag} XMF shape')
    check(x['actual_xmf']['dimension'] == 3, f'{tag} XMF dimension')
    check(x['source_h5']['read_or_rehashed_by_source_agent'] is False, f'{tag} H5 provenance')
    check(b['canonical_physical_scope_sha256'] != b['source_h5_legacy_scope_sha256'], f'{tag} scope separation')
    for item in q['input_files']:
        check('<root-bind:' not in item, f'{tag} unresolved input placeholder {item}')
        check(item in q['input_sha256'], f'{tag} missing input hash {item}')
    for item, digest in q['input_sha256'].items():
        check(item in q['input_files'], f'{tag} extra input hash {item}')
        p = Path(item)
        if p.suffix.lower() in SCIENCE:
            check(item == b['trajectory_h5'], f'{tag} unexpected science input {item}')
            check(digest == b['trajectory_h5_sha256_producer_attested'], f'{tag} H5 producer digest')
        else:
            check(p.exists(), f'{tag} missing external input {item}')
            check(sha(p) == digest, f'{tag} external input hash {item}')
    checks.append({'tag': tag, 'disabled': True, 'metadata_checks': 'pass', 'physics_acceptance': False})

result = {
    'schema': 'ds02.f5.c082s1.fresh130.validator-report.v1',
    'status': 'pass',
    'manifest_excluded_report': True,
    'scientific_payloads_opened_or_hashed_by_source_agent': False,
    'checks': checks,
    'full801_visual_gate': 'WAIT_until_Root023_render_and_manual_root_visual_review',
}
REPORT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps(result, indent=2, sort_keys=True))
