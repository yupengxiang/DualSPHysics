#!/usr/bin/env python3
"""Metadata-only F4 initial-native QA binder.

Root supplies the completed GenCase report and a JSON native frame-0 audit.
This worker reads XML/JSON metadata only. It never opens BI4, H5, CSV, or
particle arrays and it makes no Q-N, precision, visual, or production claim.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import xml.etree.ElementTree as ET

SCHEMA = "ds02.f4.internal-gap.initial-native-qa-metadata.v3"

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def load(p: Path):
    v=json.loads(p.read_text())
    if not isinstance(v, dict): raise ValueError(f"expected JSON object: {p}")
    return v

def parameter(root, key):
    for e in root.iter('parameter'):
        if e.attrib.get('key') == key: return e.attrib.get('value')
    return None

def check_xml(path: Path, ep: dict):
    root=ET.parse(path).getroot()
    definition=root.find('.//definition')
    if definition is None or not math.isclose(float(definition.attrib['dp']), .01, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"{ep['endpoint_id']}: dp mismatch")
    if not math.isclose(float(parameter(root,'TimeMax')), 1.2, rel_tol=0, abs_tol=1e-12): raise ValueError('TimeMax mismatch')
    if not math.isclose(float(parameter(root,'TimeOut')), .001, rel_tol=0, abs_tol=1e-12): raise ValueError('TimeOut mismatch')
    particles=root.find('.//particles')
    if particles is None: raise ValueError('generated XML lacks particles metadata')
    counts={k:int(particles.attrib[k]) for k in ('np','nb','nbf')}
    if counts != {'np':83233,'nb':24161,'nbf':24161}: raise ValueError(f"particle count mismatch: {counts}")
    fluid=next((e for e in particles.iter('fluid') if e.attrib.get('count')=='59072'), None)
    if fluid is None: raise ValueError('generated XML lacks total fluid range')
    return {'path':str(path),'sha256':sha(path),'counts':{'total':83233,'fixed':24161,'fluid':59072},'dp_m':.01,'time_max_s':1.2,'time_out_s':.001}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--plan',required=True,type=Path)
    ap.add_argument('--gencase-result',required=True,type=Path)
    ap.add_argument('--runtime-manifest',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    a=ap.parse_args(); plan=load(a.plan); result=load(a.gencase_result); audit=load(a.runtime_manifest)
    if result.get('status') != 'completed' or result.get('gencase_returncode_failures', 1) != 0: raise SystemExit('GenCase is not completed0')
    rows={r['endpoint_id']:r for r in result.get('commands',[])}
    reports=audit.get('cases', audit.get('endpoints', []))
    by_id={r.get('endpoint_id',r.get('case_id')):r for r in reports if isinstance(r,dict)}
    out=[]
    for ep in plan['endpoints']:
        eid=ep['endpoint_id']; row=rows.get(eid)
        if not row or row.get('returncode') != 0 or not row.get('generated_xml'): raise SystemExit(f'{eid}: missing GenCase 0 row')
        qa=by_id.get(eid)
        if not qa or qa.get('pass') is not True: raise SystemExit(f'{eid}: native frame-0 audit is not pass')
        out.append({'endpoint_id':eid,'generated_xml':check_xml(Path(row['generated_xml']),ep),'native_audit':qa})
    payload={'schema':SCHEMA,'scope_id':plan['scope_id'],'status':'pass','cases':out,'input_gencase_result':str(a.gencase_result),'input_gencase_result_sha256':sha(a.gencase_result),'input_native_audit':str(a.runtime_manifest),'input_native_audit_sha256':sha(a.runtime_manifest),'arrays_read':False,'bi4_read':False,'h5_read':False,'csv_read':False,'q_n_status':'not_assessed','precision_status':'not_accepted','visual_status':'pending','production_approval':'none'}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')

if __name__ == '__main__': main()
