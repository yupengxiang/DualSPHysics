#!/usr/bin/env python3
"""Bind fresh B metadata products for the disabled frame-zero audit.

Only JSON/XML/XDMF metadata are hashed/read. The H5 file is existence checked;
its digest must agree across the conversion report, manifest, and receipt, but
this helper never rehashes or decodes H5. It never reads BI4/CSV and never
launches any job.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = 'e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72'
CANONICAL_SHA = 'd791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f'
EXPECTED_FLUID = 40710
EXPECTED_FRAMES = 51

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def load(p: Path):
    v=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(v,dict): raise ValueError(f'JSON object required: {p}')
    return v
def require(ok,msg):
    if not ok: raise ValueError(msg)
def bound(path: Path, kind: str):
    require(path.is_file(), f'missing {kind}: {path}')
    return {'kind':kind,'path':str(path.resolve()),'sha256':None if kind=='hdf5_array' else sha(path)}
def receipt_ok(path: Path, label: str):
    d=load(path); require(d.get('status')=='completed' and d.get('returncode')==0, f'{label} is not completed/zero'); return d

def main() -> int:
    p=argparse.ArgumentParser()
    for name, kind in [('generated-xml','small_xml'),('gencase-receipt','small_json'),('initial-qa-receipt','small_json'),('initial-qa-report','small_json'),('native-receipt','small_json'),('typed-receipt','small_json'),('conversion-report','small_json'),('normal-manifest','small_json'),('normal-receipt','small_json'),('xdmf','small_xdmf'),('trajectory-h5','hdf5_array')]:
        p.add_argument('--'+name, dest=name.replace('-','_'), type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args()
    gen=receipt_ok(a.gencase_receipt,'fresh B GenCase receipt')
    require(gen.get('solver_dimension_from_gencase')==3,'fresh B GenCase is not 3-D')
    require(int(gen.get('fluid_particles',-1))==EXPECTED_FLUID,'fresh B fluid count is not 40710')
    qa_receipt=receipt_ok(a.initial_qa_receipt,'fresh B QA receipt')
    qa=load(a.initial_qa_report); require(qa.get('all_actual_checks_pass') is True,'fresh B QA report is not all_actual_checks_pass=true')
    typed=receipt_ok(a.typed_receipt,'fresh B typed receipt')
    native=receipt_ok(a.native_receipt,'fresh B native receipt')
    conv=load(a.conversion_report); require(conv.get('conversion_status')=='completed','fresh B conversion is not completed')
    h5=a.trajectory_h5; require(h5.is_file(),'fresh B trajectory H5 is missing')
    total=int(gen['total_particles']); fluid=int(gen['fluid_particles'])
    require(int(conv.get('particles',-1))==total,'conversion particle count differs from GenCase receipt')
    require(int(conv.get('frames',-1))==EXPECTED_FRAMES,'conversion frame count is not 51')
    require(Path(str(conv.get('output_hdf5',''))).resolve()==h5.resolve(),'conversion output H5 path mismatch')
    h5sha=str(conv.get('output_sha256','')); require(len(h5sha)==64,'conversion report has no H5 digest')
    manifest=load(a.normal_manifest); normal=receipt_ok(a.normal_receipt,'fresh B normal receipt')
    require(manifest.get('diagnostic_only') is True and manifest.get('full16_authorized') is False,'normal product must remain diagnostic/full16 disabled')
    for key,path in [('gencase_receipt',a.gencase_receipt),('initial_qa_receipt',a.initial_qa_receipt),('initial_qa_report',a.initial_qa_report),('typed_receipt',a.typed_receipt),('native_receipt',a.native_receipt),('conversion_report',a.conversion_report),('trajectory_h5',h5),('xdmf',a.xdmf)]:
        require(Path(str(manifest.get(key,''))).resolve()==path.resolve(),f'normal manifest {key} path mismatch')
        if key!='trajectory_h5': require(manifest.get(key+'_sha256')==sha(path),f'normal manifest {key} hash mismatch')
    require(manifest.get('trajectory_h5_sha256')==h5sha and manifest.get('source_h5_sha256')==h5sha,'normal manifest H5 declarations disagree')
    launch=(normal.get('input_hashes_at_launch') or {}).get(str(h5)); after=(normal.get('input_hashes_after_run') or {}).get(str(h5)); require(launch==h5sha and after==h5sha,'normal receipt H5 declarations disagree')
    xroot=ET.parse(a.xdmf).getroot(); times=[float(n.attrib['Value']) for n in xroot.iter() if n.tag.rsplit('}',1)[-1].lower()=='time' and 'Value' in n.attrib]; require(len(times)==EXPECTED_FRAMES,'XDMF does not contain 51 time values')
    xmlroot=ET.parse(a.generated_xml).getroot(); part=xmlroot.find('./execution/particles'); require(part is not None and int(part.attrib['np'])==total,'generated XML total mismatch')
    template=load(ROOT/'initial-bed-distribution-binding-template.json')
    args={'generated_xml':a.generated_xml,'gencase_receipt':a.gencase_receipt,'initial_qa_receipt':a.initial_qa_receipt,'initial_qa_report':a.initial_qa_report,'native_receipt':a.native_receipt,'typed_receipt':a.typed_receipt,'conversion_report':a.conversion_report,'normal_manifest':a.normal_manifest,'normal_receipt':a.normal_receipt,'xdmf':a.xdmf,'trajectory_h5':h5}
    template['status']='root_bound_actual_B_products_pending_audit'; template['actual_counts']={'total_particles':total,'fluid_particles':fluid,'frames':EXPECTED_FRAMES,'solver_dimension':3}; template['bound_by']='fresh071/scripts/bind_initial_coverage.py'; template['h5_digest_policy']['declared_h5_sha256']=h5sha
    for key,path in args.items(): template['files'][key]=bound(path,'hdf5_array' if key=='trajectory_h5' else ('small_xdmf' if key=='xdmf' else ('small_xml' if key=='generated_xml' else 'small_json')))
    # H5 is never rehashed here; bind the declared conversion/manifest/receipt digest.
    template['files']['trajectory_h5']['sha256']=h5sha
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(template,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'binding':str(a.output.resolve()),'actual_total_particles':total,'fluid_particles':fluid,'frames':EXPECTED_FRAMES,'trajectory_h5_sha256_declared_only':h5sha},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
