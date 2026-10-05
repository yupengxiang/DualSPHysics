#!/usr/bin/env python3
"""Metadata-only preflight for fresh078.

The script validates source JSON/XML/Python contracts and converter scope. It
rejects raw payloads in current input closures and never opens, hashes, or
copies BI4/H5/CSV/DAT/scientific arrays.
"""
from __future__ import annotations
import hashlib, importlib.util, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CONVERTER = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py')
VENV = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python')
RAW = {'.bi4','.csv','.h5','.hdf5','.dat','.ibi4','.vtk','.npy','.npz'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
def sha(p):
    if Path(p).suffix.lower() in RAW: raise RuntimeError(f'raw hash forbidden: {p}')
    h=hashlib.sha256();
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
    owner_path=next((HERE/'owners').glob('*.json')); owner=load(owner_path)
    assert owner['case_id']=='F7_OBSTACLE_QUINTIC_B08_A052P5'
    assert owner['status'].startswith('source_only_disabled') and owner['launch_allowed'] is False
    spec=importlib.util.spec_from_file_location('fresh078_converter',CONVERTER); m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
    scope=m._physical_condition_scope(owner); scope_sha=m.canonical_hash(scope)
    assert scope_sha==owner['canonical_physical_binding_sha256']==owner['physical_condition_sha256']
    assert owner['condition_hash_semantics']['declared_source_hash'] != scope_sha
    expected={'total':70179,'fixed':27495,'moving':1984,'floating':0,'fluid':40700,'dimension':3}
    requests=[]; raw_current=[]
    for p in sorted((HERE/'requests').rglob('*.json')):
        d=load(p); requests.append(str(p))
        assert d.get('disabled') is True and d.get('launch_allowed') is False and d.get('execution_allowed') is False
        assert d.get('future_hashes_null') is True
        if d.get('expected_counts') and isinstance(d['expected_counts'],dict):
            for k,v in expected.items():
                if k in d['expected_counts'] and d['expected_counts'][k] != v: raise AssertionError(f'{p}: expected {k}')
        files=d.get('input_files',[]); hashes=d.get('input_sha256',{})
        assert set(files)==set(hashes), f'{p}: input closure mismatch'
        provenance=d.get('input_hash_provenance',{})
        for raw in files:
            suffix=Path(raw).suffix.lower()
            if suffix in RAW:
                attested=provenance.get(raw) or provenance.get(str(Path(raw).resolve()))
                if suffix=='.h5' and isinstance(attested,str) and attested.startswith('producer_attested:'):
                    continue
                raw_current.append(raw)
    assert not raw_current, raw_current
    cov=load(HERE/'metadata/physical-coverage-audit.json'); assert cov['existing_unique_source_case_count']==47 and cov['gap_count']==1
    out={'schema':'ds02.f7.fresh078.source-validation-report.v1','scope_sha256':scope_sha,'request_count':len(requests),'requests':requests,'coverage_count':47,'gap_count':1,'raw_current_inputs':raw_current,'arrays_read':False,'payloads_read_or_hashed':False,'jobs_started':False,'shared_state_written':False,'adapter_fixes':['Path template expansion via expand_template(pattern, case_id)','solver_dimension metadata object accepted only when nested solver_dimension=3, run_out_dimensions=[3], xml_data2d=false'],'claim_boundary':'Source metadata and disabled requests only; no GenCase, QA, solver, typed, visual, Q-N, precision, or production claim.'}
    (HERE/'metadata/source-validation-report.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__': main()
