import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser();p.add_argument('--binding', required=True);p.add_argument('--output-dir', required=True)
    args = p.parse_args();b = json.loads(Path(args.binding).read_text());out = Path(args.output_dir)
    results = []
    for case in b['cases']:
        receipt = json.loads(Path(case['receipt']).read_text())
        if receipt['status'] != 'completed' or receipt['returncode'] != 0:
            raise ValueError('Completed actual GenCase required')
        prefix = Path(case['prefix']);bi = prefix.with_suffix('.bi4');xml = prefix.with_suffix('.xml')
        tree = ET.parse(xml).getroot();constants = tree.find('./execution/constants')
        if constants.find('data2d').get('value') != 'false':
            raise ValueError('Actual generated state must be three dimensional')
        dp = float(constants.find('dp').get('value'));source_before = sha(bi)
        dst = out / (case['role'] + '-initial-all.csv')
        command = [b['partvtk'], '-filedata', str(bi), '-filexml', str(xml), '-threads:2',
                   '-savecsv', str(dst), '-onlytype:+all',
                   '-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone', '-csvsep:1']
        subprocess.run(command, check=True)
        with dst.open() as stream:
            for line in stream:
                columns = next(csv.reader([line]))
                if 'Pos.x [m]' in columns:
                    break
            else:
                raise ValueError('Official typed CSV header missing')
            required = ['Pos.x [m]', 'Pos.y [m]', 'Pos.z [m]', 'Zone', 'Idp', 'Type', 'Mk',
                        'Mass [kg]', 'Vel.x [m/s]', 'Vel.y [m/s]', 'Vel.z [m/s]', 'Rhop [kg/m^3]', 'Press [Pa]']
            rows = np.loadtxt(stream, delimiter=',', usecols=[columns.index(k) for k in required], ndmin=2)
        if rows.shape != (case['expected_total'], len(required)) or not np.isfinite(rows).all():
            raise ValueError('Missing or nonfinite native rows')
        if not (rows[:, 3] == 0).all() or not np.array_equal(np.sort(rows[:, 4]), np.arange(len(rows))):
            raise ValueError('Native Zone/Idp identity is not a unique initial partition')
        if not np.array_equal(rows[:, 3:7], np.floor(rows[:, 3:7])) or set(rows[:, 5]) != {0., 3.}:
            raise ValueError('Unexpected native typed identity')
        fluid = rows[:, 5] == 3
        if fluid.sum() != case['expected_fluid'] or not (rows[:, 7] > 0).all() or not (rows[:, 11] > 0).all():
            raise ValueError('Native population/mass/density differs')
        coords = rows[:, :3];fcoords = coords[fluid]
        low = np.array([-.45, -.09, 0]) + dp/2;high = np.array([.45, .09, .09]) - dp/2
        if not (np.abs(fcoords.min(axis=0) - low) < 1e-7).all() or not (np.abs(fcoords.max(axis=0) - high) < 1e-7).all():
            raise ValueError('Actual fluid cell-centre envelope differs from physical mother')
        if len(np.unique(coords, axis=0)) != len(coords):
            raise ValueError('Coincident initial fluid/fixed/native nodes')
        if np.any(np.abs(rows[:, 8:11]) > 1e-8) or any(len(np.unique(fcoords[:, axis])) <= 1 for axis in range(3)):
            raise ValueError('Unexpected initial velocity or degenerate 3D fill')
        if sha(bi) != source_before:
            raise ValueError('Native initial BI4 changed during official export')
        results.append({'role': case['role'], 'case_id': case['case_id'], 'passed': True,
                        'native_particles': len(rows), 'native_fluid': int(fluid.sum()),
                        'native_fixed': int((~fluid).sum()), 'actual_3d': True,
                        'native_initial_BI4_sha256': source_before, 'generated_xml_sha256': sha(xml),
                        'official_csv_sha256': sha(dst), 'actual_fluid_envelope_m': [fcoords.min(axis=0).tolist(), fcoords.max(axis=0).tolist()],
                        'official_CSV_fluid_mass_sum_kg': float(rows[fluid, 7].sum()),
                        'mass_precision': 'Official CSV printed native weights; original BI4 binary mass precision retained for full converter',
                        'continuous_reference_mass_kg': 14.58, 'mass_normalization': 'none'})
    (out / 'native-initial-qa.json').write_text(json.dumps({'schema': 'ds02.f3.adaptive-spatial-native-initial-qa.v1',
         'cases': results, 'q_n': 'not_granted', 'production_approval': 'none'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
