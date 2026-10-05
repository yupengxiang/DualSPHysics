#!/usr/bin/env python3
"""Build fresh079 F6 XML source variants without invoking GenCase.

The only physical source path changed by this builder is
casedef.floatings.floating.angularvelini.@{x,y,z}. Time, geometry, mass,
DOF and all solver parameters remain the copied mother recipe.
"""
from __future__ import annotations
import argparse, re
from pathlib import Path
import xml.etree.ElementTree as ET
BASE = (0.08, 0.12, 0.06)
SCALES = (0.30, 0.40, 0.60, 0.90, 1.10, 1.30, 1.60, 1.90)
PAT = re.compile(r'<angularvelini x="[^"]+" y="[^"]+" z="[^"]+"')
def slug(s: float) -> str: return str(s).replace('.', 'p')
def build(template: Path, output: Path, scale: float) -> None:
    if scale not in SCALES: raise ValueError(f'unsupported scale {scale}')
    text = template.read_text(encoding='utf-8')
    omega = tuple(scale * value for value in BASE)
    replacement = f'<angularvelini x="{omega[0]:.12g}" y="{omega[1]:.12g}" z="{omega[2]:.12g}"'
    text, n = PAT.subn(replacement, text)
    if n != 1: raise ValueError(f'expected one angularvelini, found {n}')
    root = ET.fromstring(text)
    node = root.find('.//casedef/floatings/floating/angularvelini')
    assert node is not None
    assert [float(node.attrib[a]) for a in 'xyz'] == list(omega)
    assert root.find('.//execution/parameters/parameter[@key="TimeMax"]').get('value') == '12'
    assert root.find('.//execution/parameters/parameter[@key="TimeOut"]').get('value') == '0.05'
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(text, encoding='utf-8')
def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--template',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--scale',type=float,action='append',required=True); a=p.parse_args()
    for scale in a.scale:
        cid=f'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S{slug(scale).zfill(3)}_DP025'
        build(a.template, a.output_dir/f'{cid}_Def.xml', scale)
    return 0
if __name__=='__main__': raise SystemExit(main())
