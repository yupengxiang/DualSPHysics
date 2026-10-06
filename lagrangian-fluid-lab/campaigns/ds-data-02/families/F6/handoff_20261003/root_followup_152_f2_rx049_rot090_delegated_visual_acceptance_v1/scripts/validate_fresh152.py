#!/usr/bin/env python3
"""Bounded fresh152 validator: JSON/XML metadata plus PNG evidence only."""
from __future__ import annotations
import hashlib, json, pathlib, sys

PKG = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = {'.h5', '.hdf5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.pvd'}
def digest(path: pathlib.Path) -> str:
    if path.suffix.lower() in FORBIDDEN:
        raise AssertionError(f'forbidden payload suffix: {path}')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()
def load(name): return json.loads((PKG / 'metadata' / name).read_text())
def check_file(ref):
    p = pathlib.Path(ref['path'])
    assert p.is_file(), p
    assert digest(p) == ref['sha256'], p

def main():
    visual = load('visual-review.json')
    evidence = load('png-evidence.json')
    chain = load('chain-closure.json')
    assert visual['status'] == 'visual-approved-by-delegated-agent'
    assert visual['case_credit'] == 0
    assert visual['all_contact_sheets_and_keys_personally_viewed'] is True
    assert chain['scope_separation']['scope_equality_not_claimed'] is True
    assert chain['native_identity_and_counts']['particles'] == 418104
    assert chain['native_identity_and_counts']['dimension'] == 3
    assert chain['actual_terminal_chain'][-1]['frames'] == 401
    assert chain['actual_terminal_chain'][-1]['all_frames_rendered'] is True
    assert chain['actual_terminal_chain'][-1]['actual_times_preserved_exactly'] is True
    assert chain['actual_terminal_chain'][-1]['native_identity_axis_preserved'] is True
    assert chain['actual_terminal_chain'][-1]['nonfinite_active_states'] == 0
    for stage in chain['actual_terminal_chain']:
        rec = stage['receipt']
        check_file(rec)
        assert rec['status'] == 'completed' and rec['returncode'] == 0, rec
        for key in ('report', 'generated_xml', 'manifest', 'xmf_xml', 'animation_report', 'publish_receipt'):
            if key in stage: check_file(stage[key])
    assert evidence['all_contact_sheets_viewed'] and len(evidence['contact_sheets']) == 17
    assert evidence['all_key_frames_viewed'] and len(evidence['key_frames']) == 9
    for ref in evidence['contact_sheets'] + evidence['key_frames']: check_file(ref)
    # Evidence package must not contain scientific payload paths.
    for p in PKG.rglob('*'):
        if p.is_file() and p.suffix.lower() in FORBIDDEN:
            raise AssertionError(f'forbidden package file: {p}')
    print('fresh152 validation PASS: terminal chain, 401-frame metadata, 17 contacts, 9 keys, scope split, case_credit=0')
if __name__ == '__main__': main()
