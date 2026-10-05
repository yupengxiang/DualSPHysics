#!/usr/bin/env python3
"""Validate fresh069 source closure without opening BI4/H5/CSV/motion payloads."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
RAW_SUFFIXES = ('.bi4', '.dat', '.h5', '.csv', '.ibi4')

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def load(p): return json.loads(p.read_text())
def fail(msg): raise SystemExit('fresh069 validation failed: '+msg)
def check_request(p):
    d=load(p)
    if d.get('launch') is not False or d.get('launch_allowed') is not False or d.get('execution_allowed') is not False:
        fail(f'{p}: request is enabled')
    if d.get('future_hashes_null') is not True: fail(f'{p}: future_hashes_null missing')
    files=d.get('input_files', []); hs=d.get('input_sha256', {})
    if set(files)!=set(hs): fail(f'{p}: input_files/input_sha256 not closed')
    for s in files:
        q=Path(s)
        if not q.is_absolute() or not q.is_file(): fail(f'{p}: missing/non-file input {s}')
        if any(s.lower().endswith(x) for x in RAW_SUFFIXES) or '/solver_output/data/' in s:
            fail(f'{p}: scientific payload registered as source input {s}')
        if sha(q)!=hs[s]: fail(f'{p}: source hash mismatch {s}')
    if 'xmf' in p.name and d.get('actual_sidecar_output_subdirectory')!='xdmf': fail(f'{p}: xmf output is not isolated')
    if 'render' in p.name and '/render' not in json.dumps(d.get('command', [])): fail(f'{p}: render output is not isolated')
    if 'xmf' in p.name:
        c=d.get('xmf_shape_contract', {})
        if c.get('dynamic_vector_dimensions')!='70179 3' or c.get('implementation')!='outshape = shape[1:]': fail(f'{p}: vector shape contract missing')
    return {'path':str(p),'case_id':d.get('case_id'),'input_count':len(files),'disabled':True}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package-root',type=Path,required=True); ap.add_argument('--write-report',type=Path)
    a=ap.parse_args(); root=a.package_root
    cases=[]
    for p in sorted((root/'requests/typed').glob('*.json')): cases.append(check_request(p))
    for p in sorted((root/'requests/xmf').glob('*.json')): cases.append(check_request(p))
    for p in sorted((root/'requests/render').glob('*.json')): cases.append(check_request(p))
    if len(cases)!=15: fail(f'expected 15 disabled requests, found {len(cases)}')
    report={'schema':'ds02.f7.fresh069.source-validation-report.v1','package_root':str(root),'requests':cases,'all_passed':True,'arrays_read':False,'jobs_started':False,'shared_registry_write':False,'future_hashes_null':True}
    print(json.dumps(report,indent=2))
    if a.write_report: a.write_report.parent.mkdir(parents=True,exist_ok=True); a.write_report.write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__': main()
