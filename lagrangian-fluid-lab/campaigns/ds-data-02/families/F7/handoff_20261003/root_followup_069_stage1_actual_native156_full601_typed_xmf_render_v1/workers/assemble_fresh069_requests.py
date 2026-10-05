#!/usr/bin/env python3
"""Metadata-only post-completion assembler for fresh069.

It reads receipts/reports/manifests and never opens trajectory.h5, BI4, CSV, or motion payloads.
It writes enabled staging copies; immutable disabled templates remain unchanged.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
RAW_SUFFIXES=('.bi4','.dat','.h5','.csv','.ibi4')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(p.read_text())
def put(p,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,ensure_ascii=False,sort_keys=True)+'\n')
def input_hashes(paths, overrides=None):
    out={}
    overrides=overrides or {}
    for s in paths:
        p=Path(s)
        if not p.is_absolute() or not p.is_file(): raise SystemExit(f'missing input: {p}')
        ps=str(p)
        if '/solver_output/data/' in ps:
            raise SystemExit(f'raw scientific payload cannot be source-hashed: {p}')
        if any(ps.lower().endswith(x) for x in RAW_SUFFIXES):
            if ps not in overrides:
                raise SystemExit(f'raw scientific payload requires a producer-attested SHA override: {p}')
            out[ps]=overrides[ps]
            continue
        out[ps]=overrides.get(ps,sha(p))
    return out
def enable(d):
    d['launch']=True; d['launch_allowed']=True; d['execution_allowed']=True; d['source_only']=False
    d['disabled']=False; d['status']='root_enabled_pending_actual_execution'; d['disabled_reason']=None
    return d
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='stage',required=True)
    x=sub.add_parser('xmf'); x.add_argument('--package-root',type=Path,required=True); x.add_argument('--case-id',required=True); x.add_argument('--typed-receipt',type=Path,required=True); x.add_argument('--conversion-report',type=Path,required=True); x.add_argument('--trajectory-sha256',required=True); x.add_argument('--output-dir',type=Path,required=True)
    r=sub.add_parser('render'); r.add_argument('--package-root',type=Path,required=True); r.add_argument('--case-id',required=True); r.add_argument('--xmf-receipt',type=Path,required=True); r.add_argument('--manifest',type=Path,required=True); r.add_argument('--xdmf',type=Path,required=True); r.add_argument('--output-dir',type=Path,required=True)
    a=ap.parse_args(); root=a.package_root; case=a.case_id
    if a.stage=='xmf':
        receipt=load(a.typed_receipt); report=load(a.conversion_report)
        if (receipt.get('status'),receipt.get('returncode'))!=('completed',0): raise SystemExit('typed receipt is not completed/0')
        if report.get('output_sha256')!=a.trajectory_sha256: raise SystemExit('supplied H5 producer SHA does not match conversion report')
        src=root/'bindings'/f'{case}.xmf-binding.json'; b=load(src)
        b['typed_receipt']=str(a.typed_receipt); b['typed_receipt_sha256']=sha(a.typed_receipt)
        b['conversion_report']=str(a.conversion_report); b['conversion_report_sha256']=sha(a.conversion_report)
        # Root supplies the producer H5 SHA; no H5 bytes are opened here.
        b['trajectory_h5']=str(Path(report.get('output_hdf5') or report.get('output') or b['trajectory_h5']))
        b['trajectory_h5_sha256']=a.trajectory_sha256
        out=a.output_dir; out.mkdir(parents=True,exist_ok=True); bout=out/f'{case}.xmf-binding.json'; put(bout,b); bsha=sha(bout)
        req=load(root/'requests/xmf'/f'{case}.full601-normal-xmf-request.json')
        req['command'][req['command'].index('--binding')+1]=str(bout)
        static=[str(x) for x in req['input_files'] if str(x)!=str(root/'bindings'/f'{case}.xmf-binding.json')]
        static += [str(bout),str(a.typed_receipt),str(a.conversion_report),str(b['trajectory_h5'])]
        req['input_files']=static
        req['input_sha256']=input_hashes(static,{str(bout):bsha,str(b['trajectory_h5']):a.trajectory_sha256})
        req['future_hashes_null']=False; req=enable(req); req['actual_typed_inputs_bound']=True
        put(out/f'{case}.full601-normal-xmf-enabled-request.json',req)
        print(json.dumps({'stage':'xmf','binding':str(bout),'request':str(out/f'{case}.full601-normal-xmf-enabled-request.json')}))
    else:
        xr=load(a.xmf_receipt)
        if (xr.get('status'),xr.get('returncode'))!=('completed',0): raise SystemExit('XMF receipt is not completed/0')
        src=root/'bindings'/f'{case}.render-binding.json'; b=load(src)
        b['xmf_receipt']=str(a.xmf_receipt); b['xmf_receipt_sha256']=sha(a.xmf_receipt)
        b['manifest']=str(a.manifest); b['manifest_sha256']=sha(a.manifest)
        b['xdmf']=str(a.xdmf); b['xdmf_sha256']=sha(a.xdmf)
        out=a.output_dir; out.mkdir(parents=True,exist_ok=True); bout=out/f'{case}.render-binding.json'; put(bout,b); bsha=sha(bout)
        req=load(root/'requests/render'/f'{case}.full601-native023-render-request.json')
        req['command'][req['command'].index('--manifest')+1]=str(a.manifest)
        static=[str(x) for x in req['input_files'] if str(x)!=str(root/'bindings'/f'{case}.render-binding.json')]
        static += [str(bout),str(a.xmf_receipt),str(a.manifest),str(a.xdmf)]
        req['input_files']=static
        req['input_sha256']=input_hashes(static,{str(bout):bsha})
        req['future_hashes_null']=False; req=enable(req); req['actual_xmf_inputs_bound']=True
        put(out/f'{case}.full601-native023-render-enabled-request.json',req)
        print(json.dumps({'stage':'render','binding':str(bout),'request':str(out/f'{case}.full601-native023-render-enabled-request.json')}))
if __name__=='__main__': main()
