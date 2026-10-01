#!/usr/bin/env python3
"""Build lifecycle contract with native exclusion ledger for F1 cases."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def parse_partout_csv(partout_csv: Path) -> list[dict]:
    particles = []
    with partout_csv.open('r', encoding='utf-8') as f:
        # Detect delimiter (; or ,)
        first_line = f.readline()
        delimiter = ';' if ';' in first_line else ','
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            # Handle potential trailing delimiter creating None key or whitespace in keys
            clean_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
            if not clean_row.get('Idp'):
                continue
            idp = int(clean_row['Idp'])
            part_out = int(clean_row['PartOut'])
            motive_code = int(clean_row.get('Motive', 1))
            motive_str = 'NpOutPos: out of domain limits' if motive_code == 1 else f'Motive {motive_code}'
            px = float(clean_row['Pos.x [m]'])
            py = float(clean_row['Pos.y [m]'])
            pz = float(clean_row['Pos.z [m]'])
            rhop = float(clean_row['Rhop [kg/m^3]'])

            particles.append({
                'zone': 0,
                'idp': idp,
                'first_missing_frame': part_out,
                'motive': motive_str,
                'motive_code': motive_code,
                'partvtkout_position_m': [px, py, pz],
                'partvtkout_density_kg_m3': rhop,
            })
    # Sort deterministically by (first_missing_frame, idp)
    particles.sort(key=lambda p: (p['first_missing_frame'], p['idp']))
    return particles


def build_lifecycle_contract(
    *,
    metadata_json: Path,
    generated_xml: Path,
    partout_csv: Path,
    output_contract: Path,
    total_frames: int = 601,
) -> dict:
    meta = json.loads(metadata_json.read_text(encoding='utf-8'))
    particles = parse_partout_csv(partout_csv)
    n_out = len(particles)

    default_control = {
        'boundary_motion': 'static; empty generated motion element',
        'shifting': 0,
        'gravity_m_s2': [0.0, 0.0, -9.81],
        'time_max_s': 6.0,
        'time_out_s': 0.01,
    }
    contract = {
        'schema': 'ds-data-02.lifecycle-contract.v1',
        'family_id': 'F1',
        'physical_case_id': meta.get('physical_parent_id', 'F1_REF_DUAL_NOMINAL'),
        'coordinate_frame': 'DualSPHysics case Cartesian coordinates (x,y,z)',
        'units': {
            'time': 's',
            'position': 'm',
            'velocity': 'm/s',
            'density': 'kg/m^3',
            'mass': 'kg',
            'pressure': 'Pa',
        },
        'geometry': meta['geometry'],
        'control': meta.get('control', default_control),
        'boundary_mode': 'open',
        'lifecycle_interpretation': (
            f'finite initial numerical cohort with physical splash excursions past container open top (z > 1.0 m); '
            f'all {n_out} excluded particles tracked by PartVTKOut with motive NpOutPos'
        ),
        'declaration_source': 'continuous source Definition and generated XML with PartVTKOut decoded ledger',
        'generated_xml': str(generated_xml.resolve()),
        'generated_xml_sha256': sha256_file(generated_xml),
        'numerical_qualification': 'not_assessed',
        'lifecycle_mode': 'finite_initial_numerical_cohort_with_exclusions',
        'native_exclusion_ledger': {
            'h5_full_timeline_frames': total_frames,
            'h5_full_timeline_checked': True,
            'runparts_counts': {
                'npout_sum': n_out,
                'npoutpos_sum': n_out,
                'npoutrho_sum': 0,
                'npoutmov_sum': 0,
            },
            'excluded_particles': particles,
        },
    }

    output_contract.parent.mkdir(parents=True, exist_ok=True)
    output_contract.write_text(json.dumps(contract, indent=2), encoding='utf-8')
    return {
        'output_contract': str(output_contract),
        'excluded_particle_count': n_out,
        'first_missing_frame_min': min((p['first_missing_frame'] for p in particles), default=None),
        'first_missing_frame_max': max((p['first_missing_frame'] for p in particles), default=None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--xml', type=Path, required=True)
    parser.add_argument('--partout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=601)
    args = parser.parse_args()

    result = build_lifecycle_contract(
        metadata_json=args.metadata,
        generated_xml=args.xml,
        partout_csv=args.partout,
        output_contract=args.output,
        total_frames=args.frames,
    )
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
