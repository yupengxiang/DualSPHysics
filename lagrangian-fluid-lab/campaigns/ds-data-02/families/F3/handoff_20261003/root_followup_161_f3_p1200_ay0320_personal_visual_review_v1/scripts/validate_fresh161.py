#!/usr/bin/env python3
"""Bounded metadata/PNG validator for F3 fresh161.

It intentionally reads only package metadata, referenced JSON/XML metadata, and
published review PNGs. Scientific payload files are not opened or hashed.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
FORBIDDEN = ('.h5', '.hdf5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.pvtu')
CASE = 'F3_STAGE1_DP006_P1200_AY0320'
PHYSICAL = 'F3_TWOAXIS_P1200_AY0320_STAGE1_FIRST48_PITCH_VARIANT'

def fail(msg: str) -> None:
    raise SystemExit('fresh161 validation failed: ' + msg)

def load(rel: str):
    p = HERE / rel
    if not p.is_file(): fail(f'missing {rel}')
    try: return json.loads(p.read_text())
    except Exception as exc: fail(f'invalid JSON {rel}: {exc}')

def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def walk_strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk_strings(k)
            yield from walk_strings(v)
    elif isinstance(value, list):
        for x in value: yield from walk_strings(x)
    elif isinstance(value, str):
        yield value

def assert_no_payload_paths(*objs):
    for obj in objs:
        for s in walk_strings(obj):
            low=s.lower()
            if any(low.endswith(ext) or ext + '/' in low or ext + '\\' in low for ext in FORBIDDEN):
                fail('forbidden scientific payload path/filename present in package metadata: '+s)

chain=load('metadata/chain-audit/F3_STAGE1_DP006_P1200_AY0320.json')
prov=load('metadata/source-review-provenance.json')
decision=load('metadata/visual-review/F3_STAGE1_DP006_P1200_AY0320-delegated-visual-decision.json')
png=load('metadata/png-hashes/F3_STAGE1_DP006_P1200_AY0320.json')
integrity=load('metadata/package-integrity.json')
assert_no_payload_paths(chain, prov, decision, png)

for obj, label in [(chain,'chain'),(prov,'provenance'),(decision,'decision'),(png,'png manifest')]:
    if obj.get('case_id') != CASE: fail(f'{label} case identity')
    if obj.get('physical_case_id') != PHYSICAL: fail(f'{label} physical identity')

if chain.get('family_id') != 'F3' or prov.get('family_id') != 'F3' or decision.get('family_id') != 'F3': fail('family identity')
if decision.get('status') != 'visual-approved-by-delegated-agent': fail('visual status')
if decision.get('visual_reviewer') != '/root/production_recovery': fail('reviewer')
if decision.get('contact_sheets',{}).get('count') != 35: fail('contact count')
if decision.get('keyframes',{}).get('count') != 9: fail('keyframe count')
if chain.get('review',{}).get('contact_sheets') != 35 or chain.get('review',{}).get('keyframes') != 9: fail('chain review count')
if chain.get('review',{}).get('keyframe_indices') != [0,104,208,312,417,521,626,730,835]: fail('keyframe indices')
if decision.get('chain_evidence',{}).get('render_frames') != 836: fail('actual render frame count')
if decision.get('chain_evidence',{}).get('particles') != 179208: fail('actual particle count')
if decision.get('limits',{}).get('case_credit') != 0 or decision.get('limits',{}).get('q_n_granted') or decision.get('limits',{}).get('q_e_granted'): fail('review limits')
if chain.get('review_boundaries',{}).get('case_credit') != 0 or chain.get('review_boundaries',{}).get('independent_case_increment') != 0: fail('chain credit')
if chain.get('review_boundaries',{}).get('scientific_payload_opened_or_hashed_by_reviewer') is not False: fail('payload boundary')
if prov.get('read_boundary',{}).get('scientific_payload_opened_or_hashed') is not False: fail('provenance payload boundary')
if chain.get('outer_request_envelope_discrepancy',{}).get('historical_outer_expected_frames') != 801: fail('outer envelope evidence')
if chain.get('outer_request_envelope_discrepancy',{}).get('actual_chain_frames') != 836: fail('actual envelope evidence')

# Every selected metadata reference must still exist and have the frozen digest.
for name, entry in chain.get('actual_paths',{}).items():
    if not isinstance(entry, dict): fail(f'bad ref {name}')
    p=Path(entry['path'])
    if not p.is_file(): fail(f'missing referenced metadata {name}: {p}')
    if digest(p) != entry.get('sha256'): fail(f'referenced metadata digest drift {name}')

entries=png.get('entries',[])
if len(entries) != 44: fail('PNG entry count')
contacts=sorted((e for e in entries if e.get('role')=='contact_sheet'), key=lambda e:e.get('contact_index',-1))
keys=sorted((e for e in entries if e.get('role')=='event_keyframe'), key=lambda e:e.get('frame_index',-1))
if [e.get('contact_index') for e in contacts] != list(range(35)): fail('contact indices')
if [e.get('frame_index') for e in keys] != [0,104,208,312,417,521,626,730,835]: fail('key indices')
for e in entries:
    if e.get('viewed') is not True or e.get('view_method') != 'view_image': fail('unreviewed PNG entry')
    p=Path(e['path'])
    if p.suffix.lower() != '.png' or not p.is_file(): fail(f'missing PNG {p}')
    if p.stat().st_size != e.get('bytes'): fail(f'PNG byte drift {p}')
    if digest(p) != e.get('sha256'): fail(f'PNG digest drift {p}')

# Package integrity is a frozen manifest for every package file except itself.
if integrity.get('package') != 'fresh161': fail('package integrity package')
listed={x['path']:x for x in integrity.get('files',[])}
actual={str(p.relative_to(HERE)):p for p in HERE.rglob('*') if p.is_file() and p.name != 'package-integrity.json'}
if set(listed) != set(actual): fail(f'package file set mismatch listed={sorted(listed)} actual={sorted(actual)}')
if integrity.get('file_count') != len(actual): fail('package file count')
for rel,p in actual.items():
    x=listed[rel]
    if digest(p) != x.get('sha256') or p.stat().st_size != x.get('bytes'): fail(f'package digest drift {rel}')

print('fresh161 validation PASS: F3 P1200 AY0320, 836-frame chain, 35 contacts, 9 keyframes, 44 PNG hashes, metadata scope and read boundaries closed')
