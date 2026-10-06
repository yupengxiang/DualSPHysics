#!/usr/bin/env python3
"""Metadata-only validator for the fresh105 Root638 index."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
INDEX = HERE / 'metadata/root638-two-case-visual-index.json'
MANIFEST = HERE / 'manifest.json'
SCIENCE = ('.h5', '.bi4', '.ibi4', '.csv', '.dat', '.npy', '.npz')

def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit('fresh105 validation failed: ' + message)

def main() -> None:
    index = json.loads(INDEX.read_text(encoding='utf-8'))
    check(index['schema'] == 'ds02.f6.fresh105.f4-root638-visual-review-index.v1', 'schema')
    check(index['fresh_id'] == 'fresh105', 'fresh id')
    check(index['family_id'] == 'F4', 'family id')
    check(index['source_policy']['scientific_arrays_read'] is False, 'array-read policy')
    check(index['source_policy']['scientific_payload_hashed'] is False, 'payload-hash policy')
    cases = index['cases']
    check(len(cases) == 2, 'exactly two selected cases')
    accepted = {x['physical_case_id'] for x in index['accepted_decisions_checkpoint']['accepted_f4']}
    seen = set()
    for case in cases:
        cid = case['physical_case_id']
        check(cid not in seen, 'duplicate selected case')
        seen.add(cid)
        check(cid not in accepted, f'accepted case selected: {cid}')
        inv = case['render_root']['file_inventory']
        check(inv['contact_sheet_count'] == 51, f'{cid}: 51 contact sheets')
        check(inv['saved_frame_files_count'] == 1201, f'{cid}: 1201 saved frames')
        check(all(x['exists'] for x in inv['keyframes']), f'{cid}: keyframe existence')
        pages = case['contact_pages']
        check(pages['frames'] == 1201 and pages['page_count'] == 51, f'{cid}: contact metadata')
        check(len(pages['page_files']) == 51 and len(set(pages['page_files'])) == 51, f'{cid}: contact names')
        render = case['render_root']['render_report']
        check(render['frames'] == 1201 and render['source_frames'] == 1201, f'{cid}: report frame count')
        check(render['all_frames_rendered'] is True, f'{cid}: all frame render')
        check(render['actual_times_preserved_exactly'] is True, f'{cid}: time preservation')
        check(render['native_identity_axis_preserved'] is True, f'{cid}: UID axis')
        check(render['visual_review'] == 'pending root inspection of the full animation and every contact sheet', f'{cid}: visual status')
        check(render['numerical_precision_status'] == 'not accepted', f'{cid}: precision status')
        typed = case['typed_and_xmf_metadata']['typed_review']
        check(typed['actual_full1201_N3'] is True, f'{cid}: typed N3')
        check(case['typed_and_xmf_metadata']['xmf_manifest']['frames'] == 1201, f'{cid}: XMF frames')
        check(case['typed_and_xmf_metadata']['xmf_manifest']['particles'] == 83233, f'{cid}: XMF particles')
        check(case['typed_and_xmf_metadata']['binding_contract']['expected_dimension'] == 3, f'{cid}: XMF dimension')
        limits = case['numerical_and_acceptance_limits']
        check(limits['visual_acceptance_granted'] is False, f'{cid}: visual grant')
        check(limits['precision_or_qn_claim'] == 'none', f'{cid}: precision/QN claim')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    for entry in manifest['files']:
        p = HERE / entry['path']
        check(p.is_file(), f'manifest file missing: {entry["path"]}')
        check(hashlib.sha256(p.read_bytes()).hexdigest() == entry['sha256'], f'manifest digest: {entry["path"]}')
    # The sidecar must not contain a source payload filename.
    raw = INDEX.read_text(encoding='utf-8').lower()
    check(not any(ext in raw for ext in SCIENCE), 'scientific payload suffix leaked into index')
    print('fresh105 validation PASS: two nonaccepted Root638 F4 cases, 1201 frames, 51 contact sheets each')

if __name__ == '__main__':
    main()
