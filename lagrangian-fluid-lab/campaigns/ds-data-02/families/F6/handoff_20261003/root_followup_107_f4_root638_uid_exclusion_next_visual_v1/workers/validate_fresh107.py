#!/usr/bin/env python3
"""Metadata-only validator for fresh107."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
INDEX = HERE / 'metadata/root638-next-two-uid-visual-index.json'
MANIFEST = HERE / 'manifest.json'
SCIENCE = {'.h5', '.bi4', '.ibi4', '.csv', '.dat', '.npy', '.npz', '.vtk', '.vtu'}

def check(ok: bool, msg: str) -> None:
    if not ok: raise SystemExit('fresh107 validation failed: ' + msg)

def walk_paths(v):
    if isinstance(v, dict):
        for key, item in v.items():
            if isinstance(item, str) and (key == 'path' or key.endswith('_path') or key.endswith('_root')):
                yield item
            yield from walk_paths(item)
    elif isinstance(v, list):
        for item in v: yield from walk_paths(item)

def main() -> None:
    d = json.loads(INDEX.read_text(encoding='utf-8'))
    check(d['schema'] == 'ds02.f6.fresh107.f4-root638-uid-exclusion-next-visual-index.v1', 'schema')
    check(d['fresh_id'] == 'fresh107', 'fresh id')
    check(d['base_sidecars']['fresh105']['immutable'] is True, 'fresh105 immutable')
    check(d['base_sidecars']['fresh106']['immutable'] is True, 'fresh106 immutable')
    check(len(d['cases']) == 2, 'two selected cases')
    ids = [c['case_id'] for c in d['cases']]
    check(ids == ['F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p60000', 'F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p40000'], 'selection order')
    for c in d['cases']:
        r = c['actual_paths']['root638_render_receipt']
        check(r['status'] == 'completed' and r['returncode'] == 0, f'{c["case_id"]}: Root638 receipt')
        inv = c['render_metadata']['file_inventory']
        check(inv['contact_sheet_count'] == 51 and inv['saved_frame_count'] == 1201, f'{c["case_id"]}: frame filenames')
        check(all(k['exists'] for k in inv['keyframes']), f'{c["case_id"]}: keyframes')
        pages = c['render_metadata']['contact_pages']
        check(pages['frames'] == 1201 and pages['page_count'] == 51 and len(pages['page_files']) == 51, f'{c["case_id"]}: contact pages')
        m = c['typed_xmf_metadata']['manifest_fields']
        check(m['frames'] == 1201 and m['particles'] == 83233, f'{c["case_id"]}: manifest')
        tr = c['actual_paths']['typed_receipt_from_manifest']
        check(tr['status'] == 'completed' and tr['returncode'] == 0, f'{c["case_id"]}: typed terminal')
        cr = c['typed_xmf_metadata']['typed_conversion_report']
        check(cr['conversion_status'] == 'completed' and cr['frames'] == 1201 and cr['particles'] == 83233 and cr['solver_dimension'] == 3, f'{c["case_id"]}: conversion metadata')
        check(cr['partvtk_validation_all_passed'] is True, f'{c["case_id"]}: PartVTK metadata')
        check(c['initial_native_qa']['report_summary']['pass'] is True, f'{c["case_id"]}: initial QA')
        check(c['numeric_limits_and_status']['visual_acceptance_granted'] is False, f'{c["case_id"]}: visual status')
    inv = d['cases'][0]['uid_exclusion_investigation']
    check(inv['native_stdout_evidence']['exists'] is True, 'stdout evidence')
    check(inv['count_level_comparison']['native_stdout_excluded_particles'] == 2, 'native excluded count')
    check(inv['count_level_comparison']['native_stdout_excluded_due_to_density'] == 2, 'native density exclusion')
    check(inv['count_level_comparison']['counts_match'] is True, 'count corroboration')
    check(inv['count_level_comparison']['initial_typed_exclusion_ledger_count'] == 0, 'initial exclusion ledger')
    check(inv['identity_binding_decision'].startswith('count-level'), 'identity limitation')
    paths = [x for x in walk_paths(d) if Path(x).suffix.lower() in SCIENCE]
    check(not paths, 'scientific payload path leaked')
    md = json.loads(MANIFEST.read_text(encoding='utf-8'))
    for e in md['files']:
        p = HERE / e['path']; check(p.is_file(), f'manifest missing {e["path"]}')
        check(hashlib.sha256(p.read_bytes()).hexdigest() == e['sha256'], f'manifest digest {e["path"]}')
    print('fresh107 validation PASS: native exclusion evidence and next two Root638 visual cases')

if __name__ == '__main__': main()
