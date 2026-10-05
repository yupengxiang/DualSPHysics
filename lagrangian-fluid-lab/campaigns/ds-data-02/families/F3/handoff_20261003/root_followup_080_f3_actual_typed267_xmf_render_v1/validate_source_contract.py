#!/usr/bin/env python3
"""Validate fresh080 source contract without opening scientific payloads."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
BAD = {'.bi4','.ibi4','.csv','.h5','.hdf5','.vtk','.npy','.npz'}
CASES = ['0430','0440','0480','0520']
def sha(p: Path) -> str:
    if p.suffix.lower() in BAD: raise AssertionError('scientific payload in source validator: '+str(p))
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def check(c,m):
    if not c: raise AssertionError(m)
def closure(d,label,allow_future=False):
    files=d.get('input_files'); hashes=d.get('input_sha256')
    check(isinstance(files,list) and isinstance(hashes,dict),label+': closure types')
    check(set(files)==set(hashes),label+': closure key mismatch')
    for text in files:
        p=Path(text); check(p.suffix.lower() not in BAD,label+': raw payload '+text)
        check(p.is_file(),label+': missing '+text); check(sha(p)==hashes[text],label+': hash '+text)
def future_null(d,label):
    for k,v in d.get('future_outputs',{}).items():
        if k.endswith('_sha256') or k in {'visual_decision'}: check(v is None,label+': future '+k)
def main():
    files=[p for p in HERE.rglob('*') if p.is_file()]
    check(not any(p.suffix.lower() in BAD for p in files),'scientific payload copied')
    for p in files:
        if p.suffix=='.json': load(p)
        elif p.suffix=='.py': ast.parse(p.read_text(encoding='utf-8'))
    m=load(HERE/'manifest.json')
    check(m['fresh_id']=='fresh080' and m['family_id']=='F3' and m['case_count']==4,'manifest')
    check(m['execution_allowed'] is False and m['jobs_started'] is False and m['arrays_read'] is False,'side effects')
    check(m['all_xmf_requests_disabled'] and m['all_render_requests_disabled'],'disabled')
    check(not any('fresh079' in p.read_text(errors='ignore') for p in files if p.suffix == '.json'),'stale fresh079 runtime JSON literal')
    reg=load(HERE/'metadata/case-registry.json'); check(reg['case_count']==4,'registry count')
    prov=load(HERE/'metadata/actual-typed267-provenance.json'); check(prov['all_actual_typed_completed0'] is True,'provenance completed')
    cases={x['case_id']:x for x in reg['cases']}; check(len(cases)==4,'case identities')
    for ay in CASES:
        case='F3_STAGE1_DP006_P1000_AY'+ay; row=cases[case]
        owner=load(HERE/'owners'/f'{case}.actual-converter-scope.owner.json')
        rootreq=load(HERE/'metadata/upstream/root267'/f'{case}-typed-request.json')
        tpath=Path(row['actual_typed_receipt']['path']); rpath=Path(row['actual_conversion_report']['path'])
        tr=load(tpath); rp=load(rpath)
        check(tr['status']=='completed' and tr['returncode']==0,case+': typed status')
        check(rp['conversion_status']=='completed' and rp['frames']==836 and rp['particles']==179208,case+': report')
        check(rp['solver_dimension']['solver_dimension']==3 and rp['partvtk_validation']['all_passed'] is True,case+': typed contract')
        check(owner['actual_converter_physical_condition_scope']['schema']=='legacy-owner-scope.v0',case+': actual scope')
        check(owner['physical_condition_sha256']!=owner['source_physical_condition_sha256'],case+': source/actual collision')
        check(rootreq['case_id']==case and rootreq['physical_condition_sha256']==owner['physical_condition_sha256'],case+': root267 identity')
        physical=row['physical_case_id']
        xb=load(HERE/'requests/xmf'/f'{physical}-fresh080-xmf-binding.json')
        xr=load(HERE/'requests/xmf'/f'{physical}-fresh080-normal-xmf-request.json')
        rb=load(HERE/'requests/render'/f'{physical}-fresh080-render-binding.json')
        rr=load(HERE/'requests/render'/f'{physical}-fresh080-native023-render-request.json')
        check(xb['producer_scope_schema']=='legacy-owner-scope.v0' and xb['physical_condition_sha256']==owner['physical_condition_sha256'],case+': xmf scope')
        check(xb['source_plan_condition_sha256']==owner['source_physical_condition_sha256'],case+': source scope')
        check(xb['trajectory_h5_sha256']==rp['output_sha256'],case+': producer H5 provenance')
        check(xb['future_hashes_null'] is True and xb['future_normal_xmf']['xdmf_sha256'] is None,case+': future XMF')
        for d,label in ((xr,'xmf request'),(rr,'render request')):
            check(d['disabled'] is True and d['execution_allowed'] is False and d['launch_allowed'] is False,case+': '+label+' disabled')
            closure(d,case+': '+label); future_null(d,case+': '+label)
        check(xr['command'][-1]=='{attempt_root}/xdmf',case+': xmf output')
        check(rr['command'][-1]=='{attempt_root}/render' and '{normal_attempt_root}/xdmf/manifest.json' in rr['command'],case+': render output')
        check(rb['future_xdmf']['sha256'] is None and rb['future_manifest']['sha256'] is None,case+': render future')
        check(rb['xmf_binding']['path']==xr['binding']['path'],case+': render/xmf binding')
        check('producer_scope_schema' in xb and 'producer_scope_schema' in rb,case+': literal scope field')
        for path,digest in xb['bound_metadata_sha256'].items():
            p=Path(path); check(p.suffix.lower() not in BAD,case+': xmf raw closure'); check(p.is_file() and sha(p)==digest,case+': xmf bound metadata')
        for path,digest in rb['bound_metadata_sha256'].items():
            p=Path(path); check(p.suffix.lower() not in BAD,case+': render raw closure'); check(p.is_file() and sha(p)==digest,case+': render bound metadata')
    export=(HERE/'workers/export_xmf.py').read_text(); render=(HERE/'workers/render_native023.py').read_text()
    for token in ('producer_scope_schema','trajectory_h5','output_hdf5','partvtk_validation','xmf_shape_contract'):
        check(token in export,'export worker contract '+token)
    for token in ('load_manifest','camera_bounds','all_frames_rendered','source_h5_sha256'):
        check(token in render,'render worker contract '+token)
    print(json.dumps({'status':'pass','fresh_id':'fresh080','family_id':'F3','cases':4,'actual_typed_completed0':True,'xmf_disabled':True,'render_disabled':True,'arrays_opened':False,'jobs_started':False},indent=2))
if __name__=='__main__': main()
