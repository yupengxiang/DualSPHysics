#!/usr/bin/env python3
"""Validate/assemble disabled fresh079 request metadata only.

This helper never calls GenCase, DualSPHysics, PartVTK, the NVMe converter,
ParaView, or any decoder.  Root supplies actual upstream receipts and hashes
before enabling the corresponding copies through the approved runner.
"""
from __future__ import annotations
import argparse, json, hashlib
from pathlib import Path

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def check(p):
    d=load(p)
    if d.get('launch') is not False or d.get('launch_allowed') is not False or d.get('execution_allowed') is not False or d.get('disabled') is not True: raise ValueError(f'{p}: request is not disabled')
    if set(d.get('input_files',[])) != set(d.get('input_sha256',{})): raise ValueError(f'{p}: input hash closure')
    for x,v in d.get('input_sha256',{}).items():
        q=Path(x)
        if not q.is_file(): raise ValueError(f'{p}: missing static input {q}')
        if sha(q)!=v: raise ValueError(f'{p}: static input changed {q}')
    if set(d.get('future_input_files',[])) != set(d.get('future_input_sha256',{})): raise ValueError(f'{p}: future input closure')
    if any(v is not None for v in d.get('future_input_sha256',{}).values()): raise ValueError(f'{p}: fabricated future input hash')
    for value in d.get('future_outputs',{}).values():
        if isinstance(value,dict) and value.get('sha256') is not None: raise ValueError(f'{p}: fabricated future output hash')
        if isinstance(value,str) and value.endswith('sha256') and value is not None: raise ValueError(f'{p}: fabricated future hash')
    return {'path':str(p),'case_id':d.get('case_id'),'kind':d.get('kind'),'cpu_task_kind':d.get('cpu_task_kind'),'disabled':True}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument('--output',type=Path); a=ap.parse_args(); pkg=a.package.resolve(); rows=[]
    for pattern in ('gencase/requests/*.json','qualification/requests/*.json','typed/requests/*.json','xmf/requests/*.json','render/requests/*.json','qa/requests/*.json'):
        for p in sorted(pkg.glob(pattern)): rows.append(check(p))
    plan=load(pkg/'metadata/stage24-omega-plan.json'); assert len(plan['proposed_rows'])==8; assert len({r['scale'] for r in plan['proposed_rows']})==8
    assert all(.25 < float(r['scale']) < 2.0 for r in plan['proposed_rows'])
    report={'schema':'ds02.f6.fresh079.metadata-only-assembler-report.v1','package':str(pkg),'request_count':len(rows),'requests':rows,'existing_unique_omega_count':8,'new_proposed_count':8,'projected_omega_grid_count':16,'stage24_target':24,'future_hashes_null':True,'source_only':True,'scientific_arrays_read':False,'jobs_started':False,'claim_boundary':'Request assembly only; Root must perform actual GenCase, native QA, qualification, conversion and rendering.'}
    if a.output: a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
