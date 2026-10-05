#!/usr/bin/env python3
"""Metadata-only assembler for the disabled Root205/206 request pair."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def check_request(p, kind):
    d=load(p)
    if d.get('kind')!='cpu' or d.get('cpu_task_kind')!='audit': raise ValueError(f'{p}: wrong CPU audit kind')
    if d.get('launch') is not False or d.get('execution_allowed') is not False or d.get('disabled') is not True: raise ValueError(f'{p}: request enabled')
    if set(d.get('input_files',[])) != set(d.get('input_sha256',{})): raise ValueError(f'{p}: input/hash closure')
    if set(d.get('future_input_files',[])) != set(d.get('future_input_sha256',{})): raise ValueError(f'{p}: future input/hash closure')
    if kind=='xmf' and d['command'][-1] != '{attempt_root}/xdmf': raise ValueError(f'{p}: bad XMF output dir')
    if kind=='render' and d['command'][-1] != '{attempt_root}/render': raise ValueError(f'{p}: bad render output dir')
    if any(k.endswith('sha256') and v is not None for k,v in d.get('future_outputs',{}).items()): raise ValueError(f'{p}: fabricated future output hash')
    if any(v is not None for v in d.get('future_input_sha256',{}).values()): raise ValueError(f'{p}: fabricated future input hash')
    return d


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument('--output-dir',type=Path); ap.add_argument('--root-adoption-receipt',type=Path); ap.add_argument('--enable',action='store_true'); a=ap.parse_args(); pkg=a.package.resolve(); idx=load(pkg/'metadata/five-case-index.json'); rows=[]
    for row in idx['cases']:
        x=pkg/'requests'/f"{row['case_id']}.root205-xmf-request.json"; r=pkg/'requests'/f"{row['case_id']}.root206-render-request.json"; check_request(x,'xmf'); check_request(r,'render'); rows.append({'case_id':row['case_id'],'xmf_request':str(x),'render_request':str(r),'disabled':True})
    if a.enable:
        if a.root_adoption_receipt is None or not a.root_adoption_receipt.is_file(): raise SystemExit('--enable requires a primary root adoption receipt')
        if load(a.root_adoption_receipt).get('status') not in {'approved','adopted','completed'}: raise SystemExit('root adoption receipt is not approved')
    report={'schema':'ds02.f6.fresh078.metadata-only-assembler-report.v1','package':str(pkg),'case_count':len(rows),'cases':rows,'source_only':not a.enable,'enabled_staging':bool(a.enable),'no_scientific_array_read':True,'no_runner_invocation':True,'claim_boundary':'Request assembly only; no solver, conversion, visual, Q-N or precision result.'}
    if a.output_dir:
        a.output_dir.mkdir(parents=True,exist_ok=True); (a.output_dir/'assembly-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        for row in rows:
            for key in ('xmf_request','render_request'):
                src=Path(row[key]); (a.output_dir/src.name).write_text(src.read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps(report,indent=2,sort_keys=True)); return 0


if __name__=='__main__': raise SystemExit(main())
