#!/usr/bin/env python3
"""Metadata/PNG-only validator for fresh141.

It intentionally never opens BI4/H5/CSV/DAT/VTK scientific payloads.  It checks
terminal receipts, renderer metadata, role-separated scope fields, and the
PNG inventories produced by the delegated visual review.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISUAL = ROOT / 'metadata/visual-review.json'
EVIDENCE = ROOT / 'metadata/evidence-files.json'
PNGS = ROOT / 'metadata/png-hashes.json'
FORBIDDEN = {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtp', '.vtu', '.hdf5'}
KEYS = [0, 150, 300, 450, 600, 750, 900, 1050, 1200]


def load(p: Path):
    return json.loads(p.read_text())


def sha(p: Path):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def fail(msg):
    raise SystemExit(f'FAIL: {msg}')


def main():
    visual = load(VISUAL)
    evidence = load(EVIDENCE)
    pngs = load(PNGS)
    if visual.get('package') != 'fresh141':
        fail('wrong package marker')
    if visual.get('family') != 'F4' or visual.get('reviewer') != '/root/f6_endpoint_initial_qa':
        fail('wrong family/reviewer')
    if visual.get('case_credit') != 0 or visual.get('global_credit_updated_by_agent') is not False:
        fail('package may not update credit')
    cases = visual.get('cases')
    if not isinstance(cases, list) or len(cases) != 3:
        fail('expected exactly three selected cases')
    evidence_paths = [x.get('path','') for x in evidence.get('files', [])]
    for p in evidence_paths:
        if Path(p).suffix.lower() in FORBIDDEN:
            fail(f'forbidden scientific payload in evidence list: {p}')
        if 'actual-progress.json' in p or 'controller-result.json' in p:
            fail(f'mutable routing evidence was frozen: {p}')
    if evidence.get('scientific_payload_hashing') != 'none':
        fail('scientific payload hashing marker is not none')
    if pngs.get('scientific_payload_hashing') != 'none':
        fail('PNG inventory scientific hashing marker is not none')

    seen = set()
    for c in cases:
        cid = c.get('case_id')
        if not cid or cid in seen:
            fail(f'duplicate/missing case id: {cid}')
        seen.add(cid)
        if c.get('status') != 'visual-approved-by-delegated-agent':
            fail(f'{cid}: unexpected status')
        if c.get('agent_personally_viewed_all_contact_sheets') is not True or c.get('agent_personally_viewed_all_key_frames') is not True:
            fail(f'{cid}: incomplete personal-view markers')
        if c.get('viewed_contact_sheet_indices') != list(range(51)):
            fail(f'{cid}: contact-sheet inventory is not 0..50')
        if c.get('viewed_key_frame_indices') != KEYS:
            fail(f'{cid}: key-frame inventory mismatch')
        scope = c.get('scope_separation', {})
        if not scope.get('scope_statement') or 'No equality' not in scope['scope_statement']:
            fail(f'{cid}: scope separation statement missing')
        report_path = Path(c['render_report'])
        receipt_path = Path(c['render_receipt'])
        publish_path = Path(c['render_publish_receipt'])
        for p in (report_path, receipt_path, publish_path):
            if not p.is_file():
                fail(f'{cid}: missing terminal metadata {p}')
            if p.suffix.lower() in FORBIDDEN:
                fail(f'{cid}: forbidden terminal path {p}')
        receipt = load(receipt_path)
        if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
            fail(f'{cid}: renderer receipt is not completed/0')
        report = load(report_path)
        for k, expected in [('frames',1201),('source_frames',1201),('all_frames_rendered',True),('actual_times_preserved_exactly',True)]:
            if report.get(k) != expected:
                fail(f'{cid}: report {k}={report.get(k)!r}, expected {expected!r}')
        if report.get('nonfinite_active_states') != 0:
            fail(f'{cid}: nonfinite active states reported')
        diags = report.get('frame_diagnostics')
        if not isinstance(diags, list) or len(diags) != 1201:
            fail(f'{cid}: frame diagnostics are not 1201')
        if c.get('render_report_summary', {}).get('transient_missing_frame_count') != sum(1 for d in diags if int(d.get('missing',0)) > 0):
            fail(f'{cid}: missing-frame summary mismatch')
        if c.get('render_report_summary', {}).get('maximum_missing_particles') != max(int(d.get('missing',0)) for d in diags):
            fail(f'{cid}: maximum missing summary mismatch')
        if c.get('producer_lifecycle', {}).get('final_frame_missing_particles') != int(diags[-1].get('missing',0)):
            fail(f'{cid}: final missing summary mismatch')
        png_case = pngs.get('cases', {}).get(cid)
        if not png_case:
            fail(f'{cid}: PNG inventory absent')
        contacts = png_case.get('contact_sheets', [])
        keys = png_case.get('key_frames', [])
        if len(contacts) != 51 or [x.get('index') for x in contacts] != list(range(51)):
            fail(f'{cid}: contact PNG inventory mismatch')
        if len(keys) != 9 or [x.get('index') for x in keys] != KEYS:
            fail(f'{cid}: key PNG inventory mismatch')
        for item in contacts + keys:
            p = Path(item['path'])
            if not p.is_file():
                fail(f'{cid}: missing PNG {p}')
            if p.suffix.lower() != '.png':
                fail(f'{cid}: non-PNG in visual inventory {p}')
            if sha(p) != item.get('sha256'):
                fail(f'{cid}: PNG SHA mismatch {p}')
        for item in c.get('evidence_files', []):
            p = Path(item['path'])
            if not p.is_file():
                fail(f'{cid}: missing evidence path {p}')
            if p.suffix.lower() in FORBIDDEN:
                fail(f'{cid}: forbidden evidence path {p}')
    result = {
        'schema': 'ds-data-02.fresh141.validator-result.v1',
        'status': 'PASS',
        'case_count': len(cases),
        'contact_sheets_per_case': 51,
        'key_frames_per_case': 9,
        'terminal_render_receipts_checked': True,
        'science_payload_read_or_hashed': False,
        'global_credit_updated': False,
    }
    (ROOT / 'metadata/validator-result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
