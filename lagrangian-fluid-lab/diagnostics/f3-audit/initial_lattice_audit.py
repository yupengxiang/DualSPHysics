"""Inspect immutable generated F3 definitions; no solver launches."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

LAB = Path(__file__).resolve().parents[2]
rows = []
for token, name in [('01','F3_3D_CELL2_plain_dp0p01_Def.xml'), ('0075','F3_3D_CELL2_plain_dp0p0075_INPUTFIX_Def.xml'), ('006','F3_3D_CELL2_plain_dp0p006_Def.xml')]:
    path = LAB / 'campaigns/l1-resume/artifacts/branches' / f'F3_3D_CELL2_plain_dp0p{token}_INPUTFIX' / name
    root = ET.parse(path).getroot()
    definition = root.find('.//geometry/definition')
    fluid = root.find('.//mainlist/drawbox')
    rows.append(dict(path=str(path.relative_to(LAB)), dp=float(definition.get('dp')), pointref=definition.find('pointref').attrib, fluid_point=fluid.find('point').attrib, fluid_size=fluid.find('size').attrib))
report = {'definitions':rows, 'finding':'Only dp changed; lattice origin and fluid box retain the 0.010 m half-spacing offsets. These definitions do not enforce equal represented water volume across resolutions.', 'next_required_check':'Regenerate cell-centred geometry at each dp and verify native initial mass against 14.58 kg before any solver launch.', 'qualification':'not_granted'}
print(json.dumps(report, indent=2))
