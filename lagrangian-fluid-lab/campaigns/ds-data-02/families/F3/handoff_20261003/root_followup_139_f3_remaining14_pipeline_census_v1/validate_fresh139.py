#!/usr/bin/env python3
"""Metadata-only validator for the fresh139 F3 census package."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load(name: str):
    return json.loads((ROOT / 'metadata' / name).read_text())

def main() -> int:
    authority = load('authority-checkpoint.json')
    census = load('remaining14-census.json')
    gaps = load('downstream-gap-report.json')
    visual = load('visual-review-readiness.json')
    assert authority['fresh_id'] == 'fresh139'
    assert authority['authoritative_checkpoint']['checkpoint'] == 172
    assert authority['authoritative_checkpoint']['accepted_per_family']['F3'] == 34
    assert authority['remaining_case_count'] == 14
    assert len(census['cases']) == 14
    assert len(set(x['case_id'] for x in census['cases'])) == 14
    assert gaps['gap_count'] == 5
    assert all(x['registered_request_found'] is False for x in gaps['gaps'])
    assert visual['selected_cases'] == []
    assert authority['payload_access_policy']['scientific_payloads_opened'] is False
    assert authority['payload_access_policy']['scientific_payloads_hashed'] is False
    assert authority['payload_access_policy']['jobs_started'] is False
    assert authority['payload_access_policy']['shared_state_modified'] is False
    # Only package metadata is examined; this validator never follows external paths.
    prohibited_names = {'.bi4', '.h5', '.csv', '.dat', '.vtk', '.pvsm', '.png'}
    payload_files = [p.name for p in ROOT.rglob('*') if p.is_file() and p.suffix.lower() in prohibited_names]
    assert not payload_files, payload_files
    print(json.dumps({
        'status': 'pass',
        'fresh_id': 'fresh139',
        'checkpoint': 172,
        'f3_accepted': 34,
        'remaining_cases': 14,
        'bounded_gaps': 5,
        'visual_cases_selected': 0,
        'scientific_payload_files_in_package': 0,
    }, sort_keys=True))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError) as exc:
        print(f'fresh139 validation failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
