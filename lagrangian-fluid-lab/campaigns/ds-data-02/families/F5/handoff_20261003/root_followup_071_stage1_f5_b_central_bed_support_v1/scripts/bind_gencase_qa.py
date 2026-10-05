#!/usr/bin/env python3
"""Bind a fresh B GenCase receipt/XML into the disabled F5 QA manifest.

This helper reads only small JSON/XML metadata. It never opens BI4/H5/CSV and
never launches GenCase, PartVTK, a converter, or a solver.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET

EXPECTED_FLUID = 40710

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def load(path: Path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict): raise ValueError(f'JSON object required: {path}')
    return value

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--gencase-receipt', type=Path, required=True)
    p.add_argument('--generated-xml', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--manifest-template', type=Path, default=Path(__file__).resolve().parents[1]/'initial-qa-manifest.json')
    a = p.parse_args()
    r = load(a.gencase_receipt)
    if r.get('status') != 'completed' or r.get('returncode') != 0: raise ValueError('fresh B GenCase receipt is not completed/zero')
    if r.get('solver_dimension_from_gencase') != 3: raise ValueError('fresh B GenCase is not 3-D')
    if r.get('fluid_particles') != EXPECTED_FLUID: raise ValueError(f'fresh B fluid count {r.get("fluid_particles")} != {EXPECTED_FLUID}')
    root = ET.parse(a.generated_xml).getroot()
    particles = root.find('./execution/particles')
    if particles is None: raise ValueError('generated XML has no execution/particles')
    total = int(particles.attrib['np'])
    if total != int(r['total_particles']): raise ValueError('generated XML total differs from fresh B receipt')
    manifest = load(a.manifest_template)
    manifest.update({'status':'root_bound_actual_B_gencase_pending_initial_qa','gencase_receipt':str(a.gencase_receipt.resolve()),'gencase_receipt_sha256':sha(a.gencase_receipt),'generated_prefix':str(a.generated_xml.with_suffix('').resolve()),'total_particles':total,'actual_total_source':'fresh B receipt and generated XML','source_definition_sha256':'e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72','bound_by':'fresh071/scripts/bind_gencase_qa.py'})
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({'manifest':str(a.output.resolve()),'gencase_receipt_sha256':manifest['gencase_receipt_sha256'],'actual_total_particles':total,'fluid_particles':EXPECTED_FLUID}, sort_keys=True))
    return 0
if __name__ == '__main__': raise SystemExit(main())
