#!/usr/bin/env python3
"""Static fresh079 validator; JSON/source metadata only, never scientific payloads."""
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
BAD = {'.bi4','.ibi4','.csv','.h5','.hdf5','.vtk','.npy','.npz'}
def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def load(p: Path): return json.loads(p.read_text(encoding='utf-8'))
def check(cond, msg):
    if not cond: raise AssertionError(msg)
def closure(doc, label):
    files = doc.get('input_files'); hashes = doc.get('input_sha256')
    check(isinstance(files,list) and isinstance(hashes,dict), label+': closure types')
    check(set(files)==set(hashes), label+': input_files/input_sha256 key sets differ')
    for text in files:
        p=Path(text)
        check(p.suffix.lower() not in BAD, label+': raw payload in input closure '+text)
        check(p.is_file(), label+': missing input '+text)
        check(sha(p)==hashes[text], label+': input hash '+text)
def future_null(doc, label):
    for k,v in doc.get('future_outputs',{}).items():
        if k.endswith('_sha256') or k in {'visual_decision'}: check(v is None, label+': populated future '+k)
def main():
    files=[p for p in HERE.rglob('*') if p.is_file()]
    check(not any(p.suffix.lower() in BAD for p in files), 'scientific payload shipped')
    for p in files:
        if p.suffix=='.json': load(p)
        elif p.suffix=='.py': ast.parse(p.read_text(encoding='utf-8'))
    manifest=load(HERE/'manifest.json')
    check(manifest['fresh_id']=='fresh079' and manifest['family_id']=='F3', 'manifest identity')
    check(manifest['case_count']==4 and manifest['arrays_read'] is False and manifest['jobs_started'] is False, 'manifest side effects')
    check(manifest['shared_state_modified'] is False and manifest['all_xmf_requests_disabled'] is True and manifest['all_render_requests_disabled'] is True, 'manifest disabled state')
    reg=load(HERE/'metadata/case-registry.json'); check(reg['case_count']==4, 'registry count')
    cases={row['case_id']:row for row in reg['cases']}; check(len(cases)==4, 'case identities')
    for case,row in cases.items():
        owner=load(HERE/'owners'/f'{case}.actual-converter-scope.owner.json')
        check(owner['actual_converter_physical_condition_scope']['schema']=='legacy-owner-scope.v0', case+': owner scope')
        check(owner['physical_condition_sha256']!=owner['source_physical_condition_sha256'], case+': source/actual collision')
        check(owner['source_agent_did_not_read_science_payloads'] is True, case+': source payload flag')
        typ=load(HERE/'metadata/upstream'/f'{case}-typed-request.json')
        check(typ['physical_condition_sha256']==owner['physical_condition_sha256'], case+': Root267 actual scope')
        check(Path(row['actual_typed_receipt']['path']).is_file(), case+': actual typed receipt missing')
        check(Path(row['actual_conversion_report']['path']).is_file(), case+': actual report missing')
        tr=load(Path(row['actual_typed_receipt']['path'])); rp=load(Path(row['actual_conversion_report']['path']))
        check(tr['status']=='completed' and tr['returncode']==0, case+': typed status')
        check(rp['conversion_status']=='completed' and rp['frames']==836 and rp['particles']==179208, case+': typed counts')
        check(rp['solver_dimension']['solver_dimension']==3 and rp['partvtk_validation']['all_passed'] is True, case+': typed contract')
        physical=row['physical_case_id']
        xb=load(HERE/'requests/xmf'/f'{physical}-fresh079-xmf-binding.json')
        xr=load(HERE/'requests/xmf'/f'{physical}-fresh079-normal-xmf-request.json')
        rb=load(HERE/'requests/render'/f'{physical}-fresh079-render-binding.json')
        rr=load(HERE/'requests/render'/f'{physical}-fresh079-native023-render-request.json')
        check(xb['producer_scope_schema']=='legacy-owner-scope.v0', physical+': producer_scope_schema')
        check(xb['physical_condition_sha256']==owner['physical_condition_sha256'] and xb['source_plan_condition_sha256']==owner['source_physical_condition_sha256'], physical+': scope pair')
        check(xb['expected_frames']==836 and xb['expected_particles']==179208 and xb['dimension']==3, physical+': XMF count contract')
        check(xb['xmf_shape_contract']['dynamic_vector']['xmf_dimensions']=='179208 3' and xb['xmf_shape_contract']['dynamic_vector']['outshape']=='shape[1:]', physical+': N3 shape contract')
        check(xb['trajectory_h5_sha256']==rp['output_sha256'], physical+': producer H5 digest provenance')
        check(xb['future_normal_xmf']['xdmf_sha256'] is None and xb['future_render']['render_report_sha256'] is None, physical+': future hashes')
        for doc,label in [(xr,'xmf'),(rr,'render')]:
            check(doc['disabled'] is True and doc['execution_allowed'] is False and doc['launch_allowed'] is False, physical+': '+label+' disabled')
            check(doc['producer_scope_schema']=='legacy-owner-scope.v0', physical+': '+label+' scope schema')
            closure(doc, physical+': '+label); future_null(doc, physical+': '+label)
        check(xr['command'][-1]=='{attempt_root}/xdmf', physical+': xmf child output')
        check(rr['command'][-1]=='{attempt_root}/render' and '{normal_attempt_root}/xdmf/manifest.json' in rr['command'], physical+': render output/manifest binding')
        check(rb['future_xdmf']['sha256'] is None and rb['future_manifest']['sha256'] is None, physical+': render future xmf')
        check('producer_scope_schema' in xb and 'producer_scope_schema' in rb, physical+': literal producer scope')
        for p,e in xb['bound_metadata_sha256'].items():
            check(Path(p).suffix.lower() not in BAD, physical+': raw metadata bound '+p)
            check(Path(p).is_file() and sha(Path(p))==e, physical+': bound metadata hash '+p)
        for p,e in rb['bound_metadata_sha256'].items():
            check(Path(p).suffix.lower() not in BAD, physical+': raw render metadata bound '+p)
            check(Path(p).is_file() and sha(Path(p))==e, physical+': render bound metadata hash '+p)
    print(json.dumps({'status':'pass','fresh_id':'fresh079','family_id':'F3','cases':4,'actual_typed_completed0':True,'xmf_disabled':True,'render_disabled':True,'arrays_opened':False,'jobs_started':False}, indent=2))
if __name__=='__main__': main()
