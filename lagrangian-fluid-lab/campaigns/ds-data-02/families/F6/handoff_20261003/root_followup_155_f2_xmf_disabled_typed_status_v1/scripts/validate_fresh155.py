#!/usr/bin/env python3
"""Bounded fresh155 metadata validator; never opens scientific payloads."""
from __future__ import annotations
import hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATUS = ROOT / 'metadata' / 'f2-current-render-status.json'
SUMMARY = ROOT / 'metadata' / 'typed-scope-summary.json'
REQ_DIR = ROOT / 'requests' / 'xmf'
FORBIDDEN_SUFFIXES = ('.h5', '.bi4', '.csv', '.dat', '.vtk')


def fail(msg: str) -> None:
    raise AssertionError(msg)


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest_metadata(path_string: str) -> str:
    p = pathlib.Path(path_string)
    if p.suffix.lower() not in {'.json', '.py'}:
        fail(f'non-metadata digest requested: {p}')
    if not p.is_file():
        fail(f'metadata file missing: {p}')
    h = hashlib.sha256()
    with p.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def walk_strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk_strings(k)
            yield from walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk_strings(v)
    elif isinstance(value, str):
        yield value


def main() -> int:
    status = load(STATUS)
    summary = load(SUMMARY)
    reqs = sorted(REQ_DIR.glob('*.json'))
    checks = []
    if status.get('schema') != 'ds02.f6.fresh155.f2-render-and-typed-status.v1':
        fail('wrong status schema')
    if status['root_checkpoint']['checkpoint'] != 173 or status['root_checkpoint']['accepted_per_family']['F2'] != 29:
        fail('checkpoint 173/F2=29 snapshot mismatch')
    checks.append('checkpoint_snapshot')

    rows = status.get('render_observations', [])
    target = {r['registration_id']: r for r in rows if r['registration_id'] in {'1063','1064','1065','1097','1098'}}
    if set(target) != {'1063','1064','1065','1097','1098'}:
        fail('priority render set incomplete')
    if any(r['registration_status'] != 'registered_live_no_terminal_receipt' or r['controller_result'] is not None or r['visual_review_eligible'] for r in target.values()):
        fail('a priority render was incorrectly treated as terminal/reviewable')
    if status['visual_review']['attempted'] or status['visual_review']['case_credit'] != 0:
        fail('fresh155 must not claim visual review or credit')
    checks.append('no_unaccepted_completed_render')

    if len(reqs) != 2:
        fail('fresh155 must contain exactly two XMF request files')
    request_data = [load(p) for p in reqs]
    by_case = {r['case_id']: r for r in request_data}
    expected_cases = {
        'F2_STAGE1_FIRST48_EXPANSION_RX061_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010',
        'F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010',
    }
    if set(by_case) != expected_cases:
        fail('request case set mismatch')
    checks.append('request_case_set')

    for req in request_data:
        for key, expected in {
            'schema': 'ds02.runner-request.v2', 'disabled': True, 'launch': False,
            'launch_allowed': False, 'execution_allowed': False, 'source_only': True,
            'case_credit': 0, 'q_n_granted': False, 'q_e_granted': False,
            'full401_N3_authorized': True, 'cpu_task_kind': 'audit', 'cpu_threads': 2,
        }.items():
            if req.get(key) != expected:
                fail(f'{req["case_id"]}: {key} mismatch')
        if req.get('input_files') is not None or req.get('input_sha256') is not None:
            fail(f'{req["case_id"]}: science input closure must remain absent')
        if any(req.get('future_outputs', {}).get(k) is not None for k in ('xmf_manifest_sha256','render_manifest_sha256','render_receipt_sha256')):
            fail(f'{req["case_id"]}: future output hash is fabricated')
    checks.append('disabled_runner_contract')

    rx061 = by_case['F2_STAGE1_FIRST48_EXPANSION_RX061_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010']
    if rx061['status'] != 'ready_after_root_binding_typed_producer' or rx061['typed_prerequisite']['status'] != 'completed0':
        fail('RX061/ROT105 is not bound to actual typed completed0')
    if rx061['actual_typed_conversion']['frames'] != 401 or rx061['actual_typed_conversion']['particles'] != 418104 or rx061['actual_typed_conversion']['dimension'] != 3:
        fail('RX061 actual typed recipe mismatch')
    if rx061['physical_condition_sha256'] != 'c826ec6243784b178c74db69b1ae1da31c3e63ad4b2d30ee7402319134705926':
        fail('RX061 actual producer scope mismatch')
    if rx061['canonical_source_physical_condition_sha256'] != 'fe08f5271b43f4658c757daed157c1eaf6600236d3b43dee2f5869af80ac058b':
        fail('RX061 source scope mismatch')
    checks.append('rx061_actual_typed_scope')

    rx063 = by_case['F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010']
    if rx063['status'] != 'blocked_missing_typed157_terminal' or rx063['typed_prerequisite']['status'] != 'missing_terminal_producer':
        fail('RX063/ROT105 must remain blocked')
    if rx063['physical_condition_sha256'] is not None or rx063['typed_prerequisite']['receipt'] is not None or rx063['typed_prerequisite']['report'] is not None:
        fail('RX063 future producer metadata was fabricated')
    if rx063['canonical_source_physical_condition_sha256'] != '5fd9915cc92b45a2d6f041effd000c27452eb070c996bf1e3e9bf43f87399987' or rx063['prospective_legacy_converter_scope_sha256'] != '0cbdc3828bbda74455646b49635665dc7083c619b768fd2b3f2cdbec4aca9a4d':
        fail('RX063 source/prospective scope mismatch')
    checks.append('rx063_blocked_scope')

    if summary.get('schema') != 'ds02.f6.fresh155.typed-scope-summary.v1' or len(summary.get('cases', [])) != 2:
        fail('typed scope summary mismatch')
    # Recheck only explicitly named JSON metadata and the worker source.
    for case in summary['cases']:
        for item_key in ('owner_metadata','typed_receipt','conversion_report','actual_gencase_receipt','actual_initial_qa_receipt','actual_native_receipt'):
            item = case.get(item_key)
            if item and item.get('path'):
                actual = digest_metadata(item['path'])
                if item.get('sha256') and actual != item['sha256']:
                    fail(f'{case["case_id"]}: metadata digest mismatch for {item_key}')
    worker = summary['worker_contract']['worker_path']
    if digest_metadata(worker) != summary['worker_contract']['worker_sha256']:
        fail('worker source digest mismatch')
    checks.append('external_metadata_only_digests')

    all_values = list(walk_strings(status)) + list(walk_strings(summary))
    for req in request_data:
        all_values.extend(walk_strings(req))
    bad = [s for s in all_values if s.lower().endswith(FORBIDDEN_SUFFIXES)]
    if bad:
        fail('scientific payload path present in fresh155 package: ' + bad[0])
    checks.append('no_science_payload_paths')

    policy = status['policy']
    expected_policy = {'scientific_payloads_read_or_hashed': False, 'jobs_started': False, 'shared_state_modified': False, 'global_credit_added': False, 'q_n_granted': False, 'q_e_granted': False, 'case_credit': 0}
    if policy != expected_policy:
        fail('policy changed')
    checks.append('source_only_policy')

    print(json.dumps({'status': 'PASS', 'schema': status['schema'], 'checks': checks, 'visual_reviewed': False, 'request_count': len(reqs)}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f'fresh155 validation FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1)
