#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
SAFE = {'.json','.xml','.xmf','.py','.md','.png'}
BAD = {'.h5','.bi4','.csv','.dat','.vtk','.gif','.pvsm'}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def load(rel): return json.loads((PKG/rel).read_text())

def main():
    vr=load('metadata/visual-review.json')
    sel=load('metadata/selection-frozen.json')
    png=load('metadata/png-hashes.json')
    ev=load('metadata/evidence-files.json')
    ri=load('metadata/routing/route-integrity.json')
    assert vr['schema'].endswith('fresh139.delegated-visual-review.v1')
    assert len(vr['cases']) == 3
    assert sel['checkpoint_accepted_decisions_count'] == 210
    assert ri['checkpoint_accepted_count'] == 210
    assert vr['case_credit'] == 0 and vr['global_credit_updated_by_agent'] is False
    assert vr['scientific_payload_read_or_hashed_by_reviewer'] is False
    ids=[]
    for c in vr['cases']:
        cid=c['case_id']; ids.append(cid)
        assert c['status']=='visual-approved-by-delegated-agent'
        assert c['case_credit']==0 and c['global_credit_updated_by_agent'] is False
        assert c['agent_personally_viewed_all_contact_sheets'] is True
        assert c['agent_personally_viewed_all_key_frames'] is True
        assert c['render']['all_frames_rendered'] is True
        assert c['render']['actual_times_preserved_exactly'] is True
        assert c['render']['nonfinite_active_states'] == 0
        expected=51 if c['family_id']=='F4' else 11
        assert c['render']['contact_sheets']==expected
        assert len(png['cases'][cid]['contact_sheets'])==expected
        assert len(png['cases'][cid]['key_frames'])==9
        assert c['scope_separation']['scope_equality_claim']=='none'
        if c['family_id']=='F6':
            assert c['state0_omega_audit']['status']=='pass'
            assert c['state0_omega_audit']['checks_all_pass'] is True
            assert c['state0_omega_audit']['particle_v0_zero_not_used_as_angular_proof'] is True
    assert len(set(ids))==3
    selected={x['case_id'] for x in sel['selected_cases']}
    assert selected==set(ids)
    cp=load('metadata/routing/checkpoint-137.frozen.json')
    accepted_text='\n'.join(Path(p).read_text(errors='ignore') for p in cp.get('accepted_decisions',[]) if Path(p).exists())
    for cid in ids: assert cid not in accepted_text
    for cid in sel['excluded_previous_delegated_package_case_ids']:
        assert cid not in ids
    assert sha(PKG/'metadata/routing/actual-progress.frozen.json')==sel['route_snapshot_sha256']
    assert sha(PKG/'metadata/routing/checkpoint-137.frozen.json')==sel['checkpoint_snapshot_sha256']
    seen=set()
    for rec in ev['files']:
        p=Path(rec['path']); assert p.exists(), p
        assert p.suffix.lower() in SAFE, p
        assert p.suffix.lower() not in BAD, p
        assert sha(p)==rec['sha256'], p
        assert p.stat().st_size==rec['bytes'], p
        seen.add(str(p))
    total=0
    for cid,block in png['cases'].items():
        for rec in block['contact_sheets']+block['key_frames']:
            p=Path(rec['path']); assert p.exists(),p
            assert p.suffix.lower()=='.png'
            assert sha(p)==rec['sha256'],p
            assert p.stat().st_size==rec['bytes'],p
            total += 1
    assert total == 180
    print(f'fresh139 validation PASS: cases={len(ids)} pngs={total} accepted_snapshot={sel["checkpoint_accepted_decisions_count"]}')

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print(f'fresh139 validation FAIL: {type(e).__name__}: {e}', file=sys.stderr)
        raise
