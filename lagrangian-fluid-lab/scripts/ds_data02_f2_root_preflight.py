"""Independent read-only review of the six actual COMM4 initial particle files.

Reference permission is structural only. Float serialization comparisons never
replace the continuous physical mass denominator or grant Q-N.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def review(handoff_path, report_path):
    handoff = json.loads(Path(handoff_path).read_text())
    report = json.loads(Path(report_path).read_text())
    cases = []
    for initial in handoff['gencase_cases']:
        entry = next(row for row in report['cases'] if row['case_id'] == initial['case_id'])
        source = entry['partvtk']['csv']
        assert binding(source['path'])['sha256'] == source['sha256']
        with Path(source['path']).open() as stream:
            for line in stream:
                if line.startswith('Pos.x'):
                    columns = next(csv.reader([line])); break
            rows = list(csv.DictReader(stream, fieldnames=columns))
        xyz = lambda row: tuple(float(row[f'Pos.{axis} [m]']) for axis in 'xyz')
        fluid = [row for row in rows if int(row['Type']) == 3]
        fixed = [row for row in rows if int(row['Type']) != 3]
        positions = [xyz(row) for row in fluid]
        native_mass = math.fsum(float(row['Mass [kg]']) for row in fluid)
        definition = ET.parse(initial['definition']['path'])
        dp = float(definition.find('./casedef/geometry/definition').attrib['dp'])
        gen_binding = initial['gencase_receipt']
        assert binding(gen_binding['path'])['sha256'] == gen_binding['sha256']
        gen = json.loads(Path(gen_binding['path']).read_text())
        generated = ET.parse(str(Path(gen['command'][2]))+'.xml')
        header_mass = float(generated.find('./execution/constants/massfluid').attrib['value'])*len(fluid)
        expected_count = handoff['design_contract']['resolutions'][initial['resolution']]['fluid_particles']
        target_mass = handoff['design_contract']['continuous_mass_kg']
        continuous_budget = handoff['design_contract']['mass_budget_fraction']
        low = handoff['design_contract']['continuous_fluid_low_m']
        size = handoff['design_contract']['continuous_fluid_size_m']
        checks = dict(actual_3d=gen['solver_dimension_from_gencase'] == 3,
                      expected_fluid_count=len(fluid) == expected_count,
                      finite_positive_native=all(math.isfinite(float(row[key])) for row in rows for key in
                          ['Pos.x [m]', 'Pos.y [m]', 'Pos.z [m]', 'Rhop [kg/m^3]', 'Mass [kg]']) and
                          all(float(row['Mass [kg]']) > 0 and float(row['Rhop [kg/m^3]']) > 0 for row in rows),
                      unique_typed_ids=len({(int(r['Zone']),int(r['Idp'])) for r in rows}) == len(rows),
                      fluid_position_unique=len(set(positions)) == len(fluid),
                      no_fluid_boundary_overlap=not set(positions).intersection(xyz(r) for r in fixed),
                      same_continuous_support=all(low[a]+dp/2-1e-6 <= p[a] <= low[a]+size[a]-dp/2+1e-6 for p in positions for a in range(3)),
                      exact_transverse_layers=len({round(p[1],7) for p in positions}) == round(size[1]/dp),
                      equal_source_bands=all(sum(int(r['Mk']) == mk for r in fluid) == expected_count//3 for mk in [1,2,3]))
        faces = []
        boxes = definition.findall('./casedef/geometry/commands/mainlist/drawbox')[:3]
        for box, native_type, native_mk in zip(boxes,[1,0,0],[17,18,19]):
            origin = [float(box.find('point').attrib[a]) for a in 'xyz']
            extent = [float(box.find('size').attrib[a]) for a in 'xyz']
            group = [xyz(r) for r in rows if int(r['Type']) == native_type and int(r['Mk']) == native_mk]
            axes = dict(left=(0,0),right=(0,1),front=(1,0),back=(1,1),bottom=(2,0),top=(2,1))
            for name in box.find('boxfill').text.split('|'):
                axis, side = axes[name.strip()]
                target = origin[axis]+side*extent[axis]
                tangents = [a for a in range(3) if a != axis]
                # Discard edges: a missing physical face cannot be rescued by
                # neighboring orthogonal faces or the outer boundary layers.
                interior = [p for p in group if all(origin[a]+.25*dp < p[a] < origin[a]+extent[a]-.25*dp for a in tangents)]
                distance = min((abs(p[axis]-target) for p in interior),default=math.inf)
                plane = [p for p in interior if abs(p[axis]-target) <= distance+1e-6]
                spans = [(max(p[a] for p in plane)-min(p[a] for p in plane)) if plane else 0 for a in tangents]
                # The .25 dp inset removes edge points. An arbitrary lattice
                # phase adds up to one dp at each end, hence 2*(1+.25) dp.
                covered = bool(plane) and distance <= .55*dp+1e-6 and all(span >= extent[a]-2.5*dp-1e-6 for span,a in zip(spans,tangents))
                faces.append(dict(type=native_type,mk=native_mk,face=name.strip(),nearest_plane_distance_m=distance,
                                  interior_particles=len(plane),tangent_span_m=spans,pass_structural=covered))
        checks['interior_face_support'] = all(f['pass_structural'] for f in faces)
        cases.append(dict(case_id=initial['case_id'],checks=checks,faces=faces,
                          native_csv_mass_kg=native_mass,continuous_mass_kg=target_mass,
                          native_csv_relative_mass_error=native_mass/target_mass-1,
                          native_header_mass_kg=header_mass,header_relative_mass_error=header_mass/target_mass-1,
                          frozen_continuous_mass_budget=continuous_budget,
                          csv_mass_within_continuous_budget=abs(native_mass/target_mass-1)<=continuous_budget,
                          header_mass_within_continuous_budget=abs(header_mass/target_mass-1)<=continuous_budget,
                          source_bindings=[source,gen_binding,initial['definition']]))
    return dict(schema='ds02.f2.root-reference-preflight.v1',cases=cases,
                source_bindings=[binding(handoff_path),binding(report_path)],
                structural_references_permitted=all(all(row['checks'].values()) for row in cases),
                claim='Actual initialization review only; neither Q-N nor production approval',
                mass_semantics='Native and continuous mass remain distinct; no rescaling or denominator replacement')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff',required=True); parser.add_argument('--report',required=True); parser.add_argument('--out',required=True)
    args=parser.parse_args(); value=review(args.handoff,args.report)
    output=Path(args.out); output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as stream: json.dump(value,stream,indent=2); stream.write('\n')
    print(json.dumps({k:v for k,v in value.items() if k != 'cases'}))
