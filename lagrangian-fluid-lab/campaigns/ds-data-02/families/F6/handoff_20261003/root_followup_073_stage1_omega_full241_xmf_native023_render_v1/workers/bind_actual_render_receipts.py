#!/usr/bin/env python3
"""Bind completed XMF and Native023 output metadata without opening particle arrays."""
import argparse, hashlib, json
from pathlib import Path
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def j(p): return json.loads(Path(p).read_text())
def req(p,label):
    p=Path(p)
    if not p.is_file(): raise RuntimeError(label+' missing: '+str(p))
    d=j(p)
    if (d.get('status'),d.get('returncode')) != ('completed',0): raise RuntimeError(label+' not completed/0')
    return d
def one(c):
    xr=Path(c['xmf_output_root'])/'execution-receipt.json'; rr=Path(c['render_output_root'])/'execution-receipt.json'
    req(xr,'XMF receipt'); req(rr,'render receipt')
    x=Path(c['xmf_output_root'])/'case.xmf'; mpath=Path(c['xmf_output_root'])/'manifest.json'
    if not x.is_file() or not mpath.is_file(): raise RuntimeError('XMF outputs missing')
    m=j(mpath); times=m.get('actual_time_s')
    if m.get('schema')!='ds02.stage1.paraview-temporal-product.v1' or m.get('frames')!=241 or m.get('particles')!=417505: raise RuntimeError('XMF dimensions/schema mismatch')
    if not isinstance(times,list) or len(times)!=241 or any(float(b)<=float(a) for a,b in zip(times,times[1:])): raise RuntimeError('XMF times are not complete and strictly increasing')
    if 'camera_bounds' in m or 'domain_bounds' in m: raise RuntimeError('fixed camera bounds in XMF manifest')
    if m.get('source_h5_sha256') != c['typed068']['output_hdf5_sha256'] or m.get('xdmf_sha256') != sha(x): raise RuntimeError('XMF source hash binding mismatch')
    rp=Path(c['render_output_root'])/'paraview-full-animation-report.json'
    if not rp.is_file(): raise RuntimeError('render report missing')
    r=j(rp); cam=r.get('camera',{})
    if not (r.get('all_frames_rendered') and r.get('frames')==241 and r.get('source_frames')==241 and not r.get('diagnostic_only') and r.get('frame_selection')==list(range(241)) and r.get('actual_times_preserved_exactly')): raise RuntimeError('render report full-frame contract failed')
    if cam.get('bounds_source')!='native valid positions scanned through XdmfReader' or r.get('source_h5_sha256')!=c['typed068']['output_hdf5_sha256']: raise RuntimeError('native023 camera/H5 binding failed')
    frames=sorted((Path(c['render_output_root'])/'frames').glob('frame_*.png')); sheets=sorted(Path(c['render_output_root']).glob('all_frames_*.png'))
    if len(frames)!=241 or len(sheets)!=11: raise RuntimeError('render frame/contact-sheet count mismatch')
    outs={'case.xmf':sha(x),'manifest.json':sha(mpath),'xmf_execution_receipt.json':sha(xr),'report.json':sha(rp),'render_execution_receipt.json':sha(rr),'case.pvsm':sha(Path(c['render_output_root'])/'case.pvsm'),'full_saved_animation.gif':sha(Path(c['render_output_root'])/'full_saved_animation.gif'),'frame_pngs':[{'path':str(p),'sha256':sha(p)} for p in frames],'contact_sheets':[{'path':str(p),'sha256':sha(p)} for p in sheets]}
    return {'case_id':c['case_id'],'physical_condition_sha256':c['physical_condition_sha256'],'actual_time_first_s':times[0],'actual_time_last_s':times[-1],'camera_bounds_source':cam.get('bounds_source'),'outputs':outs,'visual_review':r.get('visual_review'),'numerical_precision_status':r.get('numerical_precision_status'),'independent_case_increment':r.get('independent_case_increment')}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--aggregate-binding',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    src=j(a.aggregate_binding)
    if src.get('launch_allowed'): raise RuntimeError('source aggregate must remain disabled')
    out={'schema':'ds02.f6.stage1.omega.full241.xmf.native023.actual-bound.v1','scope_id':src['scope_id'],'family_id':'F6','source_binding':str(a.aggregate_binding),'source_binding_sha256':sha(a.aggregate_binding),'status':'actual_outputs_bound_pending_root_visual_review','launch':False,'launch_allowed':False,'cases':[one(c) for c in src['cases']],'claim_boundary':'Actual XMF/render receipts are bound; Root visual review and numerical/production claims remain separate.'}
    a.output.write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'cases':len(out['cases']),'status':out['status']}))
if __name__=='__main__': main()
