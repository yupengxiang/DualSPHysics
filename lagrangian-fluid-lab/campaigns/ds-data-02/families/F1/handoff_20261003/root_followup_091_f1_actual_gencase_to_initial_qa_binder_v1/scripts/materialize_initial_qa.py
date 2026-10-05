#!/usr/bin/env python3
"""Metadata-only Root-owned GenCase -> initial-QA binder for F1 fresh091.
It reads JSON and generated XML metadata only. It never opens BI4/H5/CSV/DAT/VTK payloads,
never runs PartVTK, and leaves all future science hashes null.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
import xml.etree.ElementTree as ET
SCIENCE_SUFFIXES={'.bi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz'}
HEX64=re.compile(r'^[0-9a-fA-F]{64}$')
def load(p): return json.loads(Path(p).read_text())
def digest(p):
    p=Path(p)
    if p.suffix.lower() in SCIENCE_SUFFIXES: raise RuntimeError(f'science payload forbidden: {p}')
    return hashlib.sha256(p.read_bytes()).hexdigest()
def tag(t): return t.rsplit('}',1)[-1]
def elem(root,name):
    return next((e for e in root.iter() if tag(e.tag)==name),None)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-package',required=True); ap.add_argument('--data-root',required=True); ap.add_argument('--output-package',required=True); ap.add_argument('--check-only',action='store_true'); ap.add_argument('--write',action='store_true'); a=ap.parse_args()
    src=Path(a.source_package); out=Path(a.output_package)
    cases=sorted((src/'derived-gencase-bindings').glob('*.json'))
    rows=[]; errors=[]
    for bp in cases:
        b=load(bp); c=b['case_id']; ao=b.get('actual_output',{}); rp=Path(ao.get('execution_receipt','')); pp=Path(ao.get('prepared_input_report','')); xp=Path(ao.get('generated_xml',''))
        if not (rp.is_file() and pp.is_file() and xp.is_file()): rows.append({'case_id':c,'status':'pending_actual_gencase'}); continue
        r=load(rp); q=load(pp); xr=ET.parse(xp).getroot(); de=elem(xr,'definition')
        if r.get('status')!='completed' or r.get('returncode')!=0: errors.append(f'{c}: receipt not completed/0')
        if de is None or float(de.attrib.get('dp','nan')) != float(b['dp_m']): errors.append(f'{c}: dp mismatch')
        if q.get('xml_sha256') != digest(xp): errors.append(f'{c}: XML hash mismatch')
        rows.append({'case_id':c,'status':'actual_gencase_completed_0' if not errors else 'metadata_error','receipt':str(rp),'prepared_input_report':str(pp),'generated_xml':str(xp),'receipt_sha256':digest(rp),'prepared_input_report_sha256':digest(pp),'generated_xml_sha256':digest(xp),'generated_bi4_sha256':q.get('bi4_sha256'),'future_native_initial_qa_sha256':None})
    result={'schema':'ds02.f1.fresh091.materializer-report.v1','source_package':str(src),'case_count':len(rows),'cases':rows,'errors':errors,'arrays_read':False,'science_payloads_read_or_hashed':False,'write_requested':bool(a.write),'status':'pass' if not errors else 'fail'}
    if a.write:
        (out/'metadata').mkdir(parents=True,exist_ok=True); (out/'metadata/materializer-report.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if not errors else 2
if __name__=='__main__': raise SystemExit(main())
