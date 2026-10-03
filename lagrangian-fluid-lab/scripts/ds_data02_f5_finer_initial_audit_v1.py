"""Official F5 finer initialization with strict full typed-row validation."""
import argparse
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from ds_data02_f5_commensurate_dp_reference_010 import audit_partvtk
from ds_data02_native_labels import digest


def run(manifest_path, output):
    m = json.loads(manifest_path.read_text())
    receipt_path = Path(m['gencase_receipt'])
    receipt = json.loads(receipt_path.read_text())
    if digest(receipt_path) != m['gencase_receipt_sha256'] or receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Actual completed GenCase required')
    if receipt.get('solver_dimension_from_gencase') != 3 or receipt.get('fluid_particles') != 2352000:
        raise ValueError('Unexpected actual native initialization')
    prefix = Path(m['generated_prefix'])
    report = audit_partvtk(prefix.with_suffix('.bi4'), prefix.with_suffix('.xml'),
                          output/'commensurate-grid-audit.json', output/'initial-all.csv')
    path = output/'initial-all.csv'
    with path.open() as stream:
        for lines, line in enumerate(stream, 1):
            header = [x.strip() for x in next(csv.reader([line]))]
            if 'Pos.x [m]' in header and 'Idp' in header:
                break
            if lines > 64:
                raise ValueError('Official CSV header absent')
    fields = ['Pos.x [m]', 'Pos.y [m]', 'Pos.z [m]', 'Idp', 'Type', 'Mk', 'Mass [kg]',
              'Vel.x [m/s]', 'Vel.y [m/s]', 'Vel.z [m/s]', 'Rhop [kg/m^3]', 'Zone']
    rows = np.loadtxt(path, delimiter=',', skiprows=lines, usecols=[header.index(k) for k in fields])
    root = ET.parse(prefix.with_suffix('.xml')).getroot()
    particles = root.find('.//execution/particles')
    n = int(particles.get('np'))
    if len(rows) != n or not np.isfinite(rows).all():
        raise ValueError('Missing or nonfinite official native rows')
    if not (rows[:, 6] > 0).all() or not (rows[:, 10] > 0).all():
        raise ValueError('Nonpositive native initial mass/density')
    if not np.equal(rows[:, [3, 4, 5, 11]], np.rint(rows[:, [3, 4, 5, 11]])).all() or not (rows[:, 11] == 0).all():
        raise ValueError('Invalid native categorical identity')
    order = np.argsort(rows[:, 3]); rows = rows[order]
    if not np.array_equal(rows[:, 3], np.arange(n)):
        raise ValueError('Official typed particle identities incomplete or duplicated')
    blocks = []
    mapping = {'fixed': 0, 'moving': 1, 'floating': 2, 'fluid': 3}
    covered = np.zeros(n, bool)
    for node in particles:
        if node.tag not in mapping:
            continue
        begin, count = int(node.get('begin')), int(node.get('count'))
        sl = slice(begin, begin+count)
        if covered[sl].any() or not (rows[sl, 4] == mapping[node.tag]).all() or not (rows[sl, 5] == int(node.get('mk'))).all():
            raise ValueError('Native typed block differs from generated XML')
        covered[sl] = True
        blocks.append({'type': mapping[node.tag], 'mk': int(node.get('mk')), 'count': count})
    if not covered.all():
        raise ValueError('Native XML typed blocks leave missing identities')
    moving = rows[rows[:, 4] == 1]
    fluid = rows[rows[:, 4] == 3]
    max_velocity = float(np.abs(rows[:, 7:10]).max())
    checks = dict(report['checks'], finite_all_native_rows=True, exact_all_native_typed_identity=True,
                  moving_piston_present=len(moving) > 0, initial_velocity_zero=max_velocity <= 1e-8,
                  exact_expected_total=n == m['total_particles'])
    result = {'schema': 'ds02.f5.finer-strict-initial-audit.v1', 'checks': checks,
              'all_actual_checks_pass': all(checks.values()), 'total_particles': n,
              'actual_typed_blocks': blocks, 'moving_piston_particles': len(moving),
              'native_csv_fluid_mass_kg': float(fluid[:, 6].sum()),
              'maximum_initial_velocity_m_s': max_velocity,
              'partvtk_csv_sha256': digest(path), 'gencase_receipt_sha256': digest(receipt_path),
              'generated_xml_sha256': digest(prefix.with_suffix('.xml')),
              'generated_bi4_sha256': digest(prefix.with_suffix('.bi4')),
              'boundary_coverage_scope': 'Every recorded initial fixed/moving typed block validated. Geometry-marker presence alone does not prove continuous bed/wall support completeness.',
              'q_n_granted': False, 'production_granted': False, 'gpu_request_created': False}
    (output/'strict-initial-audit.json').write_text(json.dumps(result, indent=2)+'\n')
    if not result['all_actual_checks_pass']:
        raise ValueError('Finer native initialization failed checks')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    run(a.manifest, a.output_dir)
