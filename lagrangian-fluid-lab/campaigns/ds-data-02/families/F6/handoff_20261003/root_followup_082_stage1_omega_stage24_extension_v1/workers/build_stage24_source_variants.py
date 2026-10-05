#!/usr/bin/env python3
"""Build fresh082 F6 XML variants without invoking GenCase."""
from __future__ import annotations
import argparse, re
from pathlib import Path
import xml.etree.ElementTree as ET
BASE = (0.08, 0.12, 0.06)
SCALES = (0.35, 0.45, 0.55, 0.65, 0.70, 0.80, 0.85, 0.95)
PAT = re.compile(r'<angularvelini x="[^"]+" y="[^"]+" z="[^"]+"')
def slug(s: float) -> str: return f"{int(round(s * 100)):03d}"
def build(template: Path, output: Path, scale: float) -> None:
    if scale not in SCALES: raise ValueError(f"unsupported scale {scale}")
    text = template.read_text(encoding="utf-8")
    om = tuple(round(scale * value, 12) for value in BASE)
    text, n = PAT.subn(f'<angularvelini x="{om[0]:.12g}" y="{om[1]:.12g}" z="{om[2]:.12g}"', text)
    if n != 1: raise ValueError(f"expected one angularvelini, found {n}")
    root = ET.fromstring(text); node = root.find(".//casedef/floatings/floating/angularvelini")
    assert node is not None and [float(node.attrib[a]) for a in "xyz"] == list(om)
    assert root.find('.//execution/parameters/parameter[@key="TimeMax"]').get("value") == "12"
    assert root.find('.//execution/parameters/parameter[@key="TimeOut"]').get("value") == "0.05"
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(text, encoding="utf-8")
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--template", type=Path, required=True); ap.add_argument("--output-dir", type=Path, required=True); ap.add_argument("--scale", type=float, action="append", required=True); a=ap.parse_args()
    for scale in a.scale:
        case=f"F6_STAGE1_ANGULAR_RELEASE_OMEGA_S{slug(scale)}_DP025"; build(a.template, a.output_dir/f"{case}_Def.xml", scale)
    return 0
if __name__ == "__main__": raise SystemExit(main())
