#!/usr/bin/env python3
"""Bind F7 native exclusions to every saved typed identity before full Q-I."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from ds_data02_integrity import audit_hdf5, FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS
from ds_data02_native_labels import digest


def inspect(source, solver_output, generated_xml, helper_path, partvtkout, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('f7_native_tool_primitives', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    # Only generic official-tool and CSV primitives are reused. The F2 audit,
    # its family declaration, cup pose assumptions and motion files are unused.
    native = helper.run_partvtkout(binary=partvtkout, solver_output=solver_output, output_dir=output_dir)
    parts = helper.parse_runparts(solver_output / 'RunPARTs.csv')
    source_hash = digest(source)
    expected = {}
    with h5py.File(source, 'r') as h:
        times = h['time'][:]
        n = len(h['particle_id'])
        for lo in range(0, n, 8192):
            sl = slice(lo, min(n, lo + 8192))
            ids, zones = h['particle_id'][sl], h['particle_zone'][sl]
            fluid = h['initial_type'][sl] == 3
            valid = h['valid'][:, sl].astype(bool)
            masses = h['initial_mass'][sl]
            for i in np.flatnonzero(fluid & ~np.all(valid, axis=0)):
                first = int(np.flatnonzero(~valid[:, i])[0])
                key = (int(zones[i]), int(ids[i]))
                expected[key] = {'first_missing_frame': first,
                                 'first_missing_time_s': float(times[first]),
                                 'initial_mass_kg': float(masses[i])}
        with (solver_output / 'RunPARTs.csv').open() as f:
            saved = [r for r in csv.DictReader(f, delimiter=';') if (r.get('Part') or '').isdigit()]
        native_times = np.array([float(r['TimeStep [s]']) for r in saved])
        if len(times) != len(saved) or not np.allclose(times, native_times, rtol=0, atol=1e-12):
            raise ValueError('RunPARTs and full trajectory saved timelines disagree')
    records = []
    for r in native.get('csv', {}).get('records', []):
        matches = [k for k in expected if k[1] == r['idp']]
        if len(matches) != 1:
            raise ValueError('native excluded Idp does not uniquely match missing typed identity')
        key = matches[0]
        records.append({'zone': key[0], 'idp': key[1], **expected[key],
                        'motive_code': r['motive_code'],
                        'motive': 'native_solver_excluded_numerical_unknown',
                        'part_out': r['part_out'],
                        'partvtkout_position_m': r['position_m'],
                        'partvtkout_density_kg_m3': r['density_kg_m3']})
    if {(r['zone'], r['idp']) for r in records} != set(expected):
        raise ValueError('native excluded typed identities differ from full trajectory')
    root = ET.parse(generated_xml).getroot()
    ledger = {'excluded_particles': records, 'h5_full_timeline_frames': len(times),
              'h5_full_timeline_checked': True,
              'runparts_counts': {target: int(round(parts['counters'][native_name]['sum']))
                                 for native_name, target in [('NpOut', 'npout_sum'), ('NpOutPos', 'npoutpos_sum'),
                                                             ('NpOutRho', 'npoutrho_sum'), ('NpOutMov', 'npoutmov_sum')]},
              'partvtkout': native, 'physical_fate': 'unknown; separate finite event evidence required'}
    metadata = {
        'schema': 'ds02.f7-native-integrity-source-contract.v1',
        'family_id': 'F7', 'source_hdf5': str(source), 'source_hdf5_sha256': source_hash,
        'units': {'time': 's', 'position': 'm', 'velocity': 'm/s', 'density': 'kg/m^3', 'mass': 'kg', 'pressure': 'Pa'},
        'coordinate_frame': 'DualSPHysics case Cartesian coordinates (x,y,z)',
        'solver_dimension': 3,
        'boundary_mode': 'open',
        'lifecycle_mode': FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
        'lifecycle_interpretation': 'Finite initial numerical cohort; native excluded IDs retained as unknown. Physical open top does not imply injection or measured outflow.',
        'native_exclusion_ledger': ledger,
        'geometry': {'generated_xml': str(generated_xml), 'sha256': digest(generated_xml),
                     'geometry_xml': ET.tostring(root.find('.//geometry'), encoding='unicode')},
        'control': {'generated_xml': str(generated_xml), 'sha256': digest(generated_xml),
                    'motion_xml': ET.tostring(root.find('.//motion'), encoding='unicode')},
        'source_bindings': {str(p): digest(p) for p in [helper_path, partvtkout, solver_output / 'Run.out', solver_output / 'RunPARTs.csv']},
        'q_n_status': 'not_assessed',
    }
    (output_dir / 'source-contract.json').write_text(json.dumps(metadata, indent=2) + '\n')
    report = audit_hdf5(source, solver_log=solver_output / 'Run.out', metadata=metadata, particle_chunk=32768)
    report['source_contract'] = {'path': str(output_dir / 'source-contract.json'), 'sha256': digest(output_dir / 'source-contract.json')}
    report['source_immutable'] = digest(source) == source_hash
    (output_dir / 'full-integrity-report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['source_immutable']:
        raise RuntimeError('source changed during full integrity audit')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'solver-output', 'generated-xml', 'native-ledger-helper', 'partvtkout', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    r = inspect(a.source, a.solver_output, a.generated_xml, a.native_ledger_helper, a.partvtkout, a.output_dir)
    print(json.dumps({'q_i_status': r['q_i_status'], 'missing_requirements': r['missing_requirements'],
                      'structural_failures': r['structural_failures']}))
    return 0 if r['q_i_status'] == 'Q-I-structure-pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
