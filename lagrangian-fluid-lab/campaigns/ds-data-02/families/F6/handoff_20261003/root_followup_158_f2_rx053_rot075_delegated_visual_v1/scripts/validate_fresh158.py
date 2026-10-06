#!/usr/bin/env python3
"""Fresh158 metadata/PNG-only validator; never opens H5, BI4, CSV, DAT, VTK, or arrays."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DENIED={'.h5','.hdf5','.bi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def read_json(p):
    if Path(p).suffix.lower() in DENIED: raise AssertionError('payload read denied: '+str(p))
    return json.loads(Path(p).read_text())
def main():
    chain=read_json(ROOT/'metadata/actual-chain.json'); ev=read_json(ROOT/'metadata/png-evidence.json'); dec=read_json(next((ROOT/'decisions').glob('*-decision.json')))
    assert chain['reviewer']=='/root/f6_endpoint_initial_qa'
    assert chain['family_id']=='F2' and chain['case_alias_and_physical_identity']['case_credit']==0
    assert chain['scope_separation']['scope_equality_claimed'] is False
    for x in [chain['scope_separation']['actual_converter_scope_sha256'],chain['scope_separation']['canonical_source_scope_sha256'],chain['scope_separation']['source_plan_scope_sha256']]: assert isinstance(x,str) and len(x)==64
    assert chain['render_integrity']['frames']==401 and chain['render_integrity']['all_frames_rendered'] is True
    assert chain['visual_review']['personally_viewed_all_contact_sheets'] is True and chain['visual_review']['personally_viewed_all_keyframes'] is True
    assert len(ev['contact_sheets'])==17 and len(ev['key_frames'])==9
    for item in ev['contact_sheets']+ev['key_frames']:
        p=Path(item['path']); assert p.exists() and p.suffix.lower()=='.png' and len(item['sha256'])==64
        assert sha(p)==item['sha256']
    for name,node in chain['upstream_chain'].items():
        if name in {'gencase','initial_qa','native','typed','xmf','render'}:
            assert node.get('status') in {'completed','published_after_atomic_rename'}
            assert node.get('returncode',0)==0
    assert dec['decision']=='visual-approved-by-delegated-agent' and dec['global_acceptance'] is False
    assert chain['source_boundary']['science_payload_read_or_hashed'] is False
    print('fresh158 validator PASS: 17 contact sheets + 9 keyframes; metadata chain closed; no global credit')
if __name__=='__main__': main()
