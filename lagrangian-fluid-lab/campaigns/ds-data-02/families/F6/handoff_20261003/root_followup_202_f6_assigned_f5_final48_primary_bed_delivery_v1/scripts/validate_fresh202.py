#!/usr/bin/env python3
"""Read-only validation for the fresh202 F5 metadata handoff."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ABSENT = {
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_A080',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_A120',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T080',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100',
}
META = {'.json', '.xml', '.xmf', '.py', '.md', '.txt', '.yaml', '.yml'}
SCI = {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.hdf5'}

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def load(p):
    with Path(p).open(encoding='utf-8') as f: return json.load(f)

def fail(errors, msg): errors.append(msg)

def walk_refs(x, errors, label=''):
    if isinstance(x, dict):
        if x.get('declared_sha256') and x.get('path'):
            p = Path(x['path']); ext = p.suffix.lower()
            if not p.exists(): fail(errors, f'missing ref {label}: {p}')
            elif ext in META:
                actual = sha(p)
                if actual != x['declared_sha256']:
                    fail(errors, f'metadata SHA mismatch {label}: {p}')
                if x.get('metadata_sha256') != actual:
                    fail(errors, f'metadata hash was not recorded {label}: {p}')
            elif ext in SCI:
                if x.get('metadata_sha256') is not None:
                    fail(errors, f'scientific payload was hashed {label}: {p}')
        for k, v in x.items(): walk_refs(v, errors, f'{label}/{k}')
    elif isinstance(x, list):
        for i, v in enumerate(x): walk_refs(v, errors, f'{label}[{i}]')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--package', type=Path, required=True)
    args = ap.parse_args(); root = args.package.resolve(); errors = []
    mp = root/'metadata/f5-final48-primary-bed-delivery.json'
    if not mp.exists(): raise SystemExit(f'missing {mp}')
    j = load(mp)
    if j.get('schema') != 'ds02.f5.fresh202.final48.current44.primary-bed-delivery.v1': fail(errors, 'wrong package schema')
    if j.get('case_credit') != 0 or j.get('Q_N') is not False or j.get('Q_E') is not False: fail(errors, 'credit/Q flags are not zero/false')
    if j.get('scientific_payload_IO') is not False: fail(errors, 'scientific payload IO is not false')
    c = j.get('counts', {})
    if c.get('accepted_current') != 44 or c.get('pending_current') != 4 or c.get('registered_final48') != 48: fail(errors, f'bad counts {c}')
    a = j.get('accepted_products', []); p = j.get('pending_products', [])
    if len(a) != 44 or len(p) != 4: fail(errors, 'accepted/pending product cardinality is not 44/4')
    aids = [x.get('physical_case_id') for x in a]; pids = [x.get('physical_case_id') for x in p]
    if len(set(aids)) != 44 or len(set(pids)) != 4 or set(aids) & set(pids): fail(errors, 'accepted/pending IDs are not disjoint')
    if set(pids) != {'F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090','F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T085','F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085','F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100'}: fail(errors, 'pending IDs differ from the four registered F5 pending cases')
    mem = j.get('membership', {}).get('arrays', {})
    f8 = mem.get('frozen_first8_physical_case_ids', []); f24 = mem.get('actual_first24_physical_case_ids', []); f48 = mem.get('registered_final48_physical_case_ids', [])
    if [len(f8), len(f24), len(f48)] != [8, 24, 48]: fail(errors, 'membership cardinalities are not 8/24/48')
    if not (set(f8) <= set(f24) <= set(f48) and set(f48) == set(aids) | set(pids)): fail(errors, 'membership subset or roster mismatch')
    if mem.get('frozen8_subset_actual24_subset_registered48') is not True: fail(errors, 'membership source did not assert explicit subset')
    if len(j.get('legacy_atomic_publish_absences', [])) != 4: fail(errors, 'four legacy publish absences not preserved')
    if {x.get('physical_case_id') for x in j['legacy_atomic_publish_absences']} != ABSENT: fail(errors, 'wrong legacy absence IDs')
    for row in a:
        pid = row['physical_case_id']; acc = row.get('acceptance', {}); d = acc.get('accepted_decision') or {}
        if not d.get('path_in_checkpoint320'): fail(errors, f'{pid}: decision is not a cp320 accepted path')
        if d.get('decision_status') not in {'visual-approved-by-root', 'visual-approved-by-delegated-agent', 'visual-approved-in-checkpoint'}: fail(errors, f'{pid}: decision status not accepted: {d.get("decision_status")}')
        if d.get('physical_case_id') != pid: fail(errors, f'{pid}: decision physical ID mismatch')
        if row.get('case_credit') != 0 or row.get('Q_N') is not False or row.get('Q_E') is not False: fail(errors, f'{pid}: nonzero credit/Q')
        rp = row.get('render_products', {}); contacts = rp.get('contacts', []); keys = rp.get('navigation_keys', [])
        if len(contacts) != 34 or len(keys) != 9: fail(errors, f'{pid}: PNG role cardinality is {len(contacts)}/{len(keys)}, expected 34/9')
        if rp.get('status') == 'legacy_atomic_publish_receipt_absent':
            if pid not in ABSENT or rp.get('publish_receipt') is not None: fail(errors, f'{pid}: invalid legacy publication absence')
        else:
            if pid in ABSENT: fail(errors, f'{pid}: legacy absence was filled')
            if rp.get('publish_receipt') is None or rp.get('execution_receipt') is None: fail(errors, f'{pid}: published row lacks execution/publish receipt')
        for im in contacts + keys:
            if not im.get('path') or not Path(im['path']).exists(): fail(errors, f'{pid}: missing PNG metadata path')
            if im.get('declared_sha256') is None and im.get('sha256') is None: fail(errors, f'{pid}: missing producer PNG SHA')
            if im.get('stat_bytes') is None: fail(errors, f'{pid}: missing PNG stat')
        cert = row.get('full801_certificate', {})
        if cert.get('full_frames') != 801: fail(errors, f'{pid}: not full801')
        # The 14 current additions must carry their own QI proof; legacy 30 are explicitly sourced from Root1344.
        if pid not in set(x.get('physical_case_id') for x in j.get('legacy_atomic_publish_absences', [])) and row.get('own_full801_QI'):
            qm = row['own_full801_QI'].get('metadata') or {}
            if qm.get('full_frames') != 801: fail(errors, f'{pid}: own QI frame count')
            if qm.get('all801_geometry_velocity_N3_times_UID_finite_verified') is not True: fail(errors, f'{pid}: own QI N3/finite gate')
    # The old 30, including four absent-publish rows, are identified by their legacy source reference.
    legacy_rows = sum(bool(x.get('legacy_delivery_source_row')) for x in a)
    if legacy_rows != 30: fail(errors, f'legacy row count {legacy_rows}, expected 30')
    for row in p:
        if row.get('actual_primary_outputs', {}).get('render_receipt') is not None: fail(errors, f'{row["physical_case_id"]}: pending render receipt filled')
        if row.get('actual_primary_outputs', {}).get('future_hashes') is not None: fail(errors, f'{row["physical_case_id"]}: pending future hashes not null')
        if row.get('acceptance', {}).get('accepted_decision') is not None: fail(errors, f'{row["physical_case_id"]}: pending accepted decision filled')
    walk_refs(j, errors)
    if not (root/'README.md').exists(): fail(errors, 'README missing')
    if errors:
        print('\n'.join('ERROR: '+e for e in errors)); return 1
    print(f'PASS fresh202: accepted={len(a)} pending={len(p)} roster={len(a)+len(p)}; metadata refs and role/cardinality gates verified')
    return 0

if __name__ == '__main__': raise SystemExit(main())
