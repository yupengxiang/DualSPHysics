#!/usr/bin/env python3
"""Validate F3 fresh126 metadata only; never opens scientific payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
CASES = ['F3_STAGE1_DP006_P0800_AY0390','F3_STAGE1_DP006_P0800_AY0430','F3_STAGE1_DP006_P0800_AY0570']
FULL48 = json.loads((HERE/'metadata/full48-source-census.json').read_text())

def digest(p: Path):
    if p.suffix.lower() in FORBIDDEN: raise AssertionError(f'forbidden hash: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def load(p: Path):
    if p.suffix.lower() in FORBIDDEN: raise AssertionError(f'forbidden read: {p}')
    return json.loads(p.read_text())

def strings(v):
    if isinstance(v,dict):
        for x in v.values(): yield from strings(x)
    elif isinstance(v,list):
        for x in v: yield from strings(x)
    elif isinstance(v,str): yield v

def metadata_file(path_text, expected=None):
    p=Path(path_text)
    assert p.is_file(), p
    assert p.suffix.lower() not in FORBIDDEN, p
    if expected is not None: assert digest(p)==expected, (p, digest(p), expected)

def check_input_closure(obj, label):
    files=obj.get('input_files',[]); hs=obj.get('input_sha256',{})
    assert set(files)==set(hs), label
    for text in files:
        p=Path(text); assert p.suffix.lower() not in FORBIDDEN, (label,p)
        metadata_file(text, hs[text])

def check_bound(obj, label):
    for text, expected in obj.get('bound_metadata_sha256',{}).items(): metadata_file(text, expected)

def main():
    assert FULL48['expected_case_count']==48 and len(FULL48['cases'])==48
    assert set(FULL48['selected_new_typed_cases'])==set(CASES)
    assert FULL48['science_payload_opened_or_hashed_by_source_agent'] is False
    assert FULL48['global_case_credit_updated'] is False
    sel=load(HERE/'metadata/selection-snapshot.json')
    assert sel['selected_case_ids']==CASES and sel['future_xmf_render_hashes'] is None
    assert sel['root981_failed_attempt_retained']
    evidence=[]
    for cid in CASES:
        snap=load(HERE/f'metadata/case-snapshots/{cid}.json')
        owner=load(HERE/f'metadata/owners/{cid}.actual-native-physical-scope.owner.json')
        ev=load(HERE/f'metadata/typed-terminal-evidence/{cid}.json'); evidence.append(ev)
        assert snap['source_typed_status_at_snapshot']['terminal_completed0'] is True
        assert snap['typed_producer_evidence']['frames']==836 and snap['typed_producer_evidence']['particles']==179208
        assert snap['typed_producer_evidence']['solver_dimension']['solver_dimension']==3
        assert snap['typed_producer_evidence']['partvtk_all_passed'] is True
        assert owner['fresh126_typed_terminal_provenance']['status']=='completed/0'
        assert ev['status']=='completed/0' and ev['conversion_report']['frames']==836 and ev['conversion_report']['particles']==179208
        assert ev['conversion_report']['solver_dimension']==3 and ev['conversion_report']['partvtk_all_passed'] is True
        assert ev['science_payload_opened_or_hashed_by_this_source_agent'] is False
        for rel in [f'requests/xmf/{cid}-xmf-binding.json',f'requests/xmf/{cid}-xmf-request.json',f'requests/render/{cid}-render-binding.json',f'requests/render/{cid}-wrapper-request.json',f'requests/render/{cid}-root023-render-request.json']:
            o=load(HERE/rel)
            assert o.get('disabled') is True and o.get('source_only') is True and o.get('execution_allowed') is False, rel
            assert o.get('case_credit',0)==0, rel
            check_bound(o,rel)
            if 'input_files' in o: check_input_closure(o,rel)
            for key,val in o.get('future_outputs',{}).items():
                if key.endswith('sha256'): assert val is None, (rel,key,val)
            for key,val in o.get('future_input_sha256',{}).items():
                assert val is None, (rel,key,val)
        xb=load(HERE/f'requests/xmf/{cid}-xmf-binding.json')
        assert xb['bound_metadata_sha256'][str(HERE/f'metadata/case-snapshots/{cid}.json')]==digest(HERE/f'metadata/case-snapshots/{cid}.json')
        assert xb['bound_metadata_sha256'][str(HERE/f'metadata/owners/{cid}.actual-native-physical-scope.owner.json')]==digest(HERE/f'metadata/owners/{cid}.actual-native-physical-scope.owner.json')
        assert xb['conversion_report_sha256']==ev['conversion_report']['sha256']
        assert xb['typed_receipt_sha256']==ev['execution_receipt']['sha256']
        xr=load(HERE/f'requests/xmf/{cid}-xmf-request.json')
        assert xr['depends_on_typed']['terminal_completed0'] is True and xr['depends_on_typed']['conversion_report_sha256']==ev['conversion_report']['sha256']
    # Forbidden suffix scan is metadata-only and package-local; don't open forbidden files.
    for p in HERE.rglob('*'):
        if p.is_file() and p.suffix.lower() in FORBIDDEN: raise AssertionError(f'forbidden package file: {p}')
    print(json.dumps({'schema':'ds02.stage1.f3.fresh126.validator-report.v1','status':'pass','full48_count':48,'selected_case_count':3,'selected_terminal_typed_completed0':CASES,'source_only':True,'jobs_started':False,'shared_state_modified':False,'science_payload_opened_or_hashed':False},indent=2,sort_keys=True))

if __name__=='__main__': main()
