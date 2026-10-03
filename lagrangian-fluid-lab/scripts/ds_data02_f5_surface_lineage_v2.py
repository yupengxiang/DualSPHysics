"""Verify actual F5 surface repair preserves fluid, piston and physical XML."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_f6_body_cellcenter_native_v1 import _vtk_points_payload
from ds_data02_native_labels import digest


def projection(node):
    return [node.tag, sorted(node.attrib.items()), (node.text or '').strip(),
            [projection(child) for child in node]]


def run(manifest, output):
    if output.exists():
        raise FileExistsError(output)
    m = json.loads(manifest.read_text())
    old, new = Path(m['old_prefix']), Path(m['new_prefix'])
    for name in ['old_receipt', 'new_receipt']:
        r = json.loads(Path(m[name]).read_text())
        if r['status'] != 'completed' or r['returncode'] != 0 or r.get('fluid_particles') != 2352000:
            raise ValueError('Actual complete native initialization required')
    old_tree, new_tree = ET.parse(m['old_definition']).getroot(), ET.parse(m['new_definition']).getroot()
    main = new_tree.find('.//geometry/commands/mainlist')
    surface = next(n for n in main if n.tag == 'drawtriangles')
    nodes = [n for n in main if n.get('cmt', '').startswith('root_numeric_bed_surface_support')]
    if len(nodes) != 4 or [n.tag for n in nodes] != ['setmkbound', 'setdrawmode', 'drawtriangles', 'setdrawmode']:
        raise ValueError('Unexpected surface-first repair command sequence')
    if len(surface.find('triangles')) != 60:
        raise ValueError('Full original mesh surface expected')
    vertices = []
    for line in Path(m['old_bed']).read_text().splitlines():
        fields = line.strip().split()
        if fields and fields[0] == 'vertex':
            vertices.append(tuple(float(x) for x in fields[1:]))
    actual = [tuple(float(n.get(k)) for k in 'xyz') for n in surface.find('points')]
    triangles = [tuple(int(n.get(k)) for k in 'xyz') for n in surface.find('triangles')]
    mesh_same = actual == vertices and triangles == [(3*i, 3*i+1, 3*i+2) for i in range(60)]
    for n in nodes:
        main.remove(n)
    physical_same = projection(old_tree) == projection(new_tree)
    old_fluid = _vtk_points_payload(old.with_name(old.name+'_Fluid.vtk'))
    new_fluid = _vtk_points_payload(new.with_name(new.name+'_Fluid.vtk'))
    fluid_same = old_fluid == new_fluid and old_fluid[0] == 2352000
    moving = []
    for prefix in [old, new]:
        blocks = ET.parse(prefix.with_suffix('.xml')).getroot().find('.//execution/particles')
        node = blocks.find('moving')
        count = int(node.get('count'))
        bound_count, payload = _vtk_points_payload(prefix.with_name(prefix.name+'_Bound.vtk'))
        if count != 169817 or bound_count != int(blocks.get('nb')):
            raise ValueError('Unexpected original or current prescribed piston cohort')
        moving.append(payload[-count*3*4:])
    checks = {'original_physical_definition_projection_equal': physical_same,
              'all_original_mesh_triangle_vertices_equal': mesh_same,
              'actual_complete_fluid_coordinate_payload_equal': fluid_same,
              'actual_prescribed_piston_coordinate_payload_equal': moving[0] == moving[1],
              'motion_bytes_equal': digest(m['old_motion']) == digest(m['new_motion']),
              'bed_mesh_bytes_equal': digest(m['old_bed']) == digest(m['new_bed'])}
    result = {'schema': 'ds02.f5.actual-surface-discretization-lineage.v2', 'checks': checks,
              'passed': all(checks.values()), 'fluid_particles': 2352000,
              'moving_particles': 169817, 'native_fluid_mass_kg': 2352.0,
              'q_n_granted': False, 'production_granted': False,
              'claim_boundary': 'Initialization byte lineage only; fixed boundary particle discretization changes deliberately; no claim to numerical convergence',
              'source_sha256': {k: digest(v) for k, v in m.items() if k not in ['old_prefix', 'new_prefix']}}
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return result['passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.manifest, a.output) else 1)
