import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def export(prefix, name, out, binary):
    xml, bi4 = Path(prefix + '.xml'), Path(prefix + '.bi4')
    before = sha(bi4)
    dst = out / (name + '-initial-all.csv')
    assert not dst.exists()
    subprocess.run([binary, '-filedata', str(bi4), '-filexml', str(xml), '-threads:2',
                    '-savecsv', str(dst), '-onlytype:+all',
                    '-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone', '-csvsep:1'], check=True)
    with dst.open() as f:
        for line in f:
            cols = next(csv.reader([line]))
            if 'Pos.x [m]' in cols:
                break
        else:
            raise ValueError('Missing official CSV header')
        keys = ['Pos.x [m]', 'Pos.y [m]', 'Pos.z [m]', 'Zone', 'Idp', 'Type', 'Mk',
                'Mass [kg]', 'Vel.x [m/s]', 'Vel.y [m/s]', 'Vel.z [m/s]', 'Rhop [kg/m^3]', 'Press [Pa]']
        rows = np.loadtxt(f, delimiter=',', usecols=[cols.index(k) for k in keys], ndmin=2)
    assert sha(bi4) == before
    return rows, {'initial_bi4_sha256': before, 'generated_xml_sha256': sha(xml),
                  'official_csv_sha256': sha(dst), 'official_csv': str(dst)}


p = argparse.ArgumentParser()
p.add_argument('--binding', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
b = json.loads(Path(a.binding).read_text())
out = Path(a.output_dir)
results = []
for c in b['cases']:
    rec = json.loads(Path(c['receipt']).read_text())
    assert rec['status'] == 'completed' and rec['returncode'] == 0
    rows, provenance = export(c['prefix'], c['role'], out, b['partvtk'])
    assert rows.shape == (c['expected_total'], 13) and np.isfinite(rows).all()
    assert np.array_equal(rows[:, 3:7], np.floor(rows[:, 3:7]))
    assert np.all(rows[:, 3] == 0) and np.array_equal(np.sort(rows[:, 4]), np.arange(len(rows)))
    assert set(rows[:, 5]) == set(c['expected_types'])
    fluid = rows[:, 5] == 3
    assert fluid.sum() == c['expected_fluid']
    assert np.all(rows[:, 7] > 0) and np.all(rows[:, 11] > 0)
    assert np.max(np.abs(rows[:, 8:11])) <= 1e-8
    assert len(np.unique(rows[:, :3], axis=0)) == len(rows)
    coords = rows[fluid, :3]
    assert all(len(np.unique(coords[:, axis])) > 1 for axis in range(3))
    if 'expected_fluid_envelope_m' in c:
        assert np.max(np.abs(np.stack([coords.min(axis=0), coords.max(axis=0)]) - np.asarray(c['expected_fluid_envelope_m'], dtype=np.float32).astype(np.float64))) < 1e-7
    reference_evidence = None
    if c.get('reference_prefix'):
        ref, ref_provenance = export(c['reference_prefix'], c['role'] + '-original-reference', out, b['partvtk'])
        assert np.array_equal(rows, ref)
        reference_evidence = {'all_13_official_CSV_columns_exactly_equal': True, 'provenance': ref_provenance,
                              'scope': 'Official text-export equality; binary source hashes also recorded, no claim binary mass precision from CSV'}
    tree = ET.parse(c['prefix'] + '.xml').getroot()
    assert tree.find('./execution/constants/data2d').get('value') == 'false'
    result = {**c, **provenance, 'passed': True, 'native_particles': len(rows),
              'native_fluid': int(fluid.sum()), 'actual_3d': True,
              'native_type_counts': {str(int(k)): int((rows[:, 5] == k).sum()) for k in np.unique(rows[:, 5])},
              'actual_fluid_envelope_m': [coords.min(axis=0).tolist(), coords.max(axis=0).tolist()],
              'official_CSV_fluid_mass_sum_kg': float(rows[fluid, 7].sum()),
              'mass_precision': 'Official CSV rounded export; original BI4 binary native weights remain authority for full converter',
              'original_reference_comparison': reference_evidence}
    results.append(result)
with (out / 'native-initial-qa.json').open('x') as f:
    json.dump({'schema':'ds02.root.actual-initial-native-QA.v1','cases':results,
               'q_n':'not_granted','production_approval':'none','independent_case_count_increment':0},f,indent=2)
    f.write('\n')
