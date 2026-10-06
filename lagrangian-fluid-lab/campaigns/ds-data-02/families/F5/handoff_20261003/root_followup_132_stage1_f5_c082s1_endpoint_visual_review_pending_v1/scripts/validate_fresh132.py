#!/usr/bin/env python3
"""Validate the fresh132 pending visual-review metadata package only.

This script reads package JSON and hashes package text/JSON files. It never opens
BI4, DAT, H5, CSV, VTK, VTP, VTU, or solver payloads and never launches a task.
The external receipt/request hashes in the snapshot are attestations captured by the
source preparation step; later terminal status changes require a new sidecar.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
DENIED = {'.bi4', '.dat', '.h5', '.csv', '.vtk', '.vtu', '.vtp'}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def load(rel: str):
    return json.loads((PKG / rel).read_text())

def main() -> None:
    manifest = load('manifest.json')
    if manifest.get('source_only') is not True:
        raise AssertionError('package is not source-only')
    fixed = {item['path']: item['sha256'] for item in manifest['files']}
    if 'manifest.json' in fixed or 'metadata/fresh132-validator-report.json' in fixed:
        raise AssertionError('manifest/report self-reference')
    for rel, expected in fixed.items():
        path = PKG / rel
        if not path.exists():
            raise AssertionError(f'missing {rel}')
        if path.suffix.lower() in DENIED:
            raise AssertionError(f'scientific payload entered package: {rel}')
        if sha(path) != expected:
            raise AssertionError(f'hash mismatch: {rel}')

    status = load('metadata/fresh132-endpoint-status.json')
    plan = load('metadata/fresh132-visual-review-plan.json')
    if status.get('source_only') is not True or plan.get('source_only') is not True:
        raise AssertionError('source-only marker missing')
    if status['visual_acceptance']['status'] != 'WAIT':
        raise AssertionError('visual gate opened in pending package')
    if status['visual_acceptance']['remaining10_release_enabled'] is not False:
        raise AssertionError('remaining ten release was enabled')
    if plan['gate']['status'] != 'WAIT' or plan['gate']['remaining10_release_enabled'] is not False:
        raise AssertionError('plan gate is not WAIT')
    if plan['expected_render_contract']['frames'] != 801 or plan['expected_render_contract']['contacts'] != 34:
        raise AssertionError('render contract changed')
    for tag, endpoint in status['endpoints'].items():
        if endpoint['visual_decision'] != 'WAIT':
            raise AssertionError(f'{tag}: pending visual decision is not WAIT')
        if endpoint['contact_png_count_observed'] is not None or endpoint['visual_png_sha256'] is not None:
            raise AssertionError(f'{tag}: future PNG evidence was filled')
        attempt = endpoint['root_attempt']
        if attempt['attempt_id'] != plan['endpoint_attempts'][tag]:
            raise AssertionError(f'{tag}: attempt mismatch')
    old = status['excluded_history']['M085_T080_root783_old_attempt']
    if old['eligible_for_visual_acceptance'] is not False or old['status'] != 'failed':
        raise AssertionError('old Root783 M085 failure was not excluded')
    report = {
        'schema': 'ds02.f5.c082s1.fresh132-validator-report.v1',
        'status': 'passed_metadata_only',
        'visual_gate': 'WAIT',
        'candidate_visual_reviews_completed': 0,
        'future_png_hashes_recorded': False,
        'remaining10_release_enabled': False,
        'old_m085_root783_excluded': True,
        'scientific_payloads_read_or_hashed_by_validator': False,
        'jobs_started': False,
        'shared_state_modified': False,
        'manifest_report_excluded_from_fixed_hash_set': True,
    }
    (PKG / 'metadata/fresh132-validator-report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
