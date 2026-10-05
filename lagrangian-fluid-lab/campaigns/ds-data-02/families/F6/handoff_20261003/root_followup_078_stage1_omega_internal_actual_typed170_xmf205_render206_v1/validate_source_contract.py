#!/usr/bin/env python3
"""Verify F6 fresh078 JSON/XML/source metadata only.

Scientific H5/BI4/CSV/IBI4 payloads are registered but remain opaque here.
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET
RAW={'.h5','.bi4','.ibi4','.csv'}
BLOCKS=[{'begin':0,'count':73441,'mk':30,'mkfluid':None,'tag':'fixed','type':0},{'begin':73441,'count':16384,'mk':60,'mkfluid':None,'tag':'floating','type':2},{'begin':89825,'count':327680,'mk':1,'mkfluid':0,'tag':'fluid','type':3}]

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    p=Path(p)
    if p.suffix.lower() in RAW: raise ValueError(f'raw hash forbidden: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def ok(v,msg):
    if not v: raise AssertionError(msg)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parent); a=ap.parse_args(); pkg=a.package.resolve(); idx=load(pkg/'metadata/five-case-index.json'); ok(len(idx['cases'])==5,'five cases required')
    exp=pkg/'workers/export_xmf.py'; et=exp.read_text(encoding='utf-8'); ast.parse(et); ok('outshape = shape[1:]' in et,'outshape particle-axis contract missing'); ok('shape[2:]' not in et,'historical shape[2:] bug found'); ren=pkg/'workers/render_native023.py'; ast.parse(ren.read_text(encoding='utf-8')); ren_sha=sha(ren); rows=[]
    for row in idx['cases']:
        cid=row['case_id']; xb=load(pkg/'bindings'/f'{cid}.root205-xmf-binding.json'); rb=load(pkg/'bindings'/f'{cid}.root206-render-binding.json'); xr=load(pkg/'requests'/f'{cid}.root205-xmf-request.json'); rr=load(pkg/'requests'/f'{cid}.root206-render-request.json')
        ok(xr['cpu_task_kind']==rr['cpu_task_kind']=='audit',f'{cid}: audit kind'); ok(xr['launch'] is False and rr['launch'] is False and xr['execution_allowed'] is False and rr['execution_allowed'] is False,f'{cid}: disabled'); ok(xr['command'][-1]=='{attempt_root}/xdmf',f'{cid}: XMF output'); ok(rr['command'][-1]=='{attempt_root}/render',f'{cid}: render output')
        ok(set(xr['input_files'])==set(xr['input_sha256']),f'{cid}: XMF closure'); ok(set(rr['input_files'])==set(rr['input_sha256']),f'{cid}: render closure'); ok(set(rr['future_input_files'])==set(rr['future_input_sha256']),f'{cid}: future closure'); ok(all(v is None for v in rr['future_input_sha256'].values()),f'{cid}: future hash')
        raw_expected={row['typed']['trajectory_h5']:row['typed']['trajectory_h5_sha256'],row['gencase']['bi4']:row['gencase']['bi4_sha256'],row['native']['partfloatinfo']:row['native']['partfloatinfo_sha256']}
        for request,label in ((xr,'XMF'),(rr,'render')):
            for path_text,expected in request['input_sha256'].items():
                path=Path(path_text)
                if path.suffix.lower() in RAW:
                    ok(raw_expected.get(path_text)==expected,f'{cid}: {label} raw producer hash {path}')
                else:
                    ok(path.is_file() and sha(path)==expected,f'{cid}: {label} input hash {path}')
        for d,label in ((xr,'XMF'),(rr,'render')): ok(all(not k.endswith('sha256') or v is None for k,v in d['future_outputs'].items()),f'{cid}: {label} output hash')
        ok(xb['physical_condition_sha256']==row['physical_condition_sha256'],f'{cid}: condition'); ok(xb['source_plan_condition_sha256'] is None,f'{cid}: source plan hash'); ok(xb['xmf_shape_contract']['dynamic_vector_dimensions']=='417505 3',f'{cid}: vector dimensions'); ok(xb['xmf_shape_contract']['dynamic_scalar_dimensions']=='417505',f'{cid}: scalar dimensions'); ok(xb['xmf_shape_contract']['particle_axis_preserved'] is True,f'{cid}: particle axis'); ok(rb['camera_policy']['camera_bounds_in_manifest'] is False and rb['camera_policy']['domain_bounds_in_manifest'] is False,f'{cid}: camera bounds'); ok(rr['renderer_source']['sha256']==ren_sha,f'{cid}: renderer sha')
        side=load(pkg/'metadata/legacy-canonical-scope'/f'{cid}.legacy-canonical-scope.json'); rel=side['semantic_relation']; ok(rel['roles_distinct'] is True and rel['digest_equal_as_recorded'] is True and rel['legacy_owner_scope_v0'] is False,f'{cid}: scope relation')
        owner=load(row['canonical_owner']); report=load(row['typed']['report']); tr=load(row['typed']['receipt']); nr=load(row['native']['receipt']); gr=load(row['gencase']['receipt']); ok((tr.get('status'),tr.get('returncode'))==('completed',0),f'{cid}: typed receipt'); ok((nr.get('status'),nr.get('returncode'))==('completed',0),f'{cid}: native receipt'); ok((gr.get('status'),gr.get('returncode'))==('completed',0),f'{cid}: GenCase receipt'); ok(report['conversion_status']=='completed' and report['partvtk_validation']['all_passed'] is True,f'{cid}: typed report'); ok(report['frames']==241 and report['particles']==417505 and report['solver_dimension']['solver_dimension']==3,f'{cid}: typed counts/dimension'); ok(report['typed_identity']['blocks']==BLOCKS,f'{cid}: typed blocks'); ok(report['hash_scopes']['physical_condition']['schema']=='ds-data-02.physical-binding.v1',f'{cid}: producer schema'); ok(report['hash_scopes']['physical_condition_sha256']==row['physical_condition_sha256'],f'{cid}: producer digest'); ok(report['source_provenance']['owner_metadata']['path']==row['canonical_owner'],f'{cid}: owner provenance path'); ok(report['source_provenance']['owner_metadata']['sha256']==row['canonical_owner_sha256'],f'{cid}: owner provenance sha'); ok(owner['physical_condition_sha256']==row['physical_condition_sha256'],f'{cid}: owner condition'); ok(owner['source_definition']==row['source_definition'],f'{cid}: source def')
        for p,expected in xb['bound_metadata_sha256'].items(): ok(Path(p).suffix.lower() not in RAW and Path(p).is_file() and sha(p)==expected,f'{cid}: metadata hash {p}')
        root=ET.parse(row['gencase']['xml']).getroot(); ang=root.find('.//angularvelini'); cen=root.find('.//center'); mass=root.find('.//massbody'); ok(ang is not None and cen is not None and mass is not None,f'{cid}: XML declarations'); ok([float(ang.attrib[a]) for a in ('x','y','z')]==row['omega_corrobation']['expected_initial_angular_velocity_rad_s'],f'{cid}: XML omega'); ok([float(cen.attrib[a]) for a in ('x','y','z')]==[2.4,1.2,1.08],f'{cid}: XML center'); ok(float(mass.attrib['value'])==128.0,f'{cid}: XML mass'); ok(row['mass_semantics']['physical_rigid_mass_kg']==128.0 and row['mass_semantics']['native_lattice_support_mass_kg']==256.0,f'{cid}: mass semantics'); ok(row['omega_corrobation']['particle_linear_velocity_zero_is_not_angular_proof'] is True,f'{cid}: V0 boundary'); rows.append({'case_id':cid,'metadata_pass':True,'xmf_attempt':xr['attempt_id'],'render_attempt':rr['attempt_id']})
    report={'schema':'ds02.f6.fresh078.source-validation.v1','fresh_id':'fresh078','package':str(pkg),'pass':True,'case_count':len(rows),'cases':rows,'checks':['actual Root170/146/137/168 JSON closure','canonical/producer scope role closure','outshape=shape[1:]','N-by-3 vector/N scalar dimensions','child xdmf/render output dirs','future hashes null','generated XML omega/center/mass','separate 128/256 kg semantics'],'read_policy':'No BI4/H5/CSV/IBI4 scientific arrays opened or rehashed by source validator.','claim_boundary':'Source contract only; no solver, conversion, visual acceptance, Q-N or precision result.'}
    (pkg/'source-validation-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
