#!/usr/bin/env python3
"""Audit immutable F7 initial BI4 population and finite physical solids."""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from ds_data02_native_labels import digest


def canonical(element):
    return [element.tag, sorted(element.attrib.items()), (element.text or '').strip(),
            [canonical(child) for child in element]]


def physical_parts(path):
    root = ET.parse(path).getroot()
    main = root.find('casedef/geometry/commands/mainlist')
    solids = []
    for item in main:
        if item.tag == 'setmkfluid':
            break
        solids.append(canonical(item))
    return {'solids': solids, 'motion': canonical(root.find('casedef/motion')),
            'constants': canonical(root.find('casedef/constantsdef')),
            'execution': canonical(root.find('execution'))}


def face_coverage(points, low, high, faces, dp):
    low, high = np.asarray(low), np.asarray(high)
    tolerance = dp / 2 + 1e-9
    result = {}
    for axis, side in faces:
        value = (low if side == 0 else high)[axis]
        tangents = [i for i in range(3) if i != axis]
        selected = np.abs(points[:, axis] - value) <= tolerance
        for tangent in tangents:
            selected &= (points[:, tangent] >= low[tangent] - tolerance)
            selected &= (points[:, tangent] <= high[tangent] + tolerance)
        cloud = points[selected]
        covered = len(cloud) > 0
        if covered:
            covered = all(cloud[:, i].min() <= low[i] + tolerance and
                          cloud[:, i].max() >= high[i] - tolerance for i in tangents)
        result[f'{axis}_{side}'] = {'count': len(cloud), 'covered': bool(covered),
                                   'bounds_m': [cloud.min(axis=0).tolist(), cloud.max(axis=0).tolist()] if len(cloud) else None}
    return result


def audit(metadata, prefix, output):
    if output.exists():
        raise FileExistsError(output)
    lab = Path(__file__).resolve().parents[1]
    helper = lab / 'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py'
    spec = importlib.util.spec_from_file_location('f7_readonly_native_helper', helper)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    decoder = lab / 'scripts/f8_r008_safe_bi4_decoder_v1.py'
    scanner = module._load_safe_decoder(decoder)
    meta = json.loads(metadata.read_text())
    native = prefix.with_suffix('.bi4')
    generated = prefix.with_suffix('.xml')
    receipt = prefix.parent / 'execution-receipt.json'
    definition = metadata.parent / (meta['case_id'] + '_Def.xml')
    mother = Path(meta['source_definition'])
    sources = [metadata, definition, mother, native, generated, receipt, helper, decoder, Path(__file__).resolve()]
    hashes = {str(p): digest(p) for p in sources}
    assert hashes[str(definition)] == meta['definition_sha256']
    assert hashes[str(mother)] == meta['source_definition_sha256']
    launch = json.loads(receipt.read_text())
    fd = os.open(native, os.O_RDONLY)
    try:
        scanned = scanner.scan_bi4_fd(fd, hashes[str(native)])
    finally:
        os.close(fd)
    values = {v.name: v.value for v in scanned.root.values}
    arrays = {a.name: a for a in scanned.arrays if a.item_path[-1] == scanned.root.children[0].name}
    assert arrays['Posd'].type_code == 23
    pos = np.memmap(native, mode='r', dtype='<f8', offset=arrays['Posd'].offset, shape=(arrays['Posd'].count, 3))
    ids = np.memmap(native, mode='r', dtype='<u4', offset=arrays['Idp'].offset, shape=(arrays['Idp'].count,))
    total, fluid, fixed, moving = [int(values[k]) for k in ('CaseNp', 'CaseNfluid', 'CaseNfixed', 'CaseNmoving')]
    fluid_pos = pos[ids >= total - fluid]
    fixed_pos = pos[ids < fixed]
    moving_pos = pos[(ids >= fixed) & (ids < fixed + moving)]
    dp = float(meta['dp_m'])
    actual_mass = fluid * float(values['MassFluid'])
    solid_faces = [(axis, side) for axis in range(3) for side in (0, 1)]
    coverage = {'tank': face_coverage(fixed_pos, [-.6, -.4, 0], [.6, .4, .6], solid_faces[:-1], dp),
                'paddle': face_coverage(moving_pos, [-.07, -.24, .05], [-.01, .24, .53], solid_faces, dp)}
    inside_paddle = np.all((fluid_pos > [-.07, -.24, .05]) & (fluid_pos < [-.01, .24, .53]), axis=1)
    checks = {
        'gencase_completed': launch['status'] == 'completed' and launch['returncode'] == 0,
        'unique_complete_native_identity': len(ids) == total and np.array_equal(np.sort(ids), np.arange(total)),
        'complete_type_partition': total == fluid + fixed + moving and len(fluid_pos) == fluid,
        'finite_positions': bool(np.isfinite(pos).all()),
        'true_3d': not bool(values.get('Data2d', False)) and len(np.unique(fluid_pos[:, 1])) > 1,
        'registered_count': fluid == meta['expected_fluid_count'],
        'native_mass_matches_predicted_quadrature': bool(np.isclose(actual_mass, meta['expected_quadrature_mass_kg'], rtol=1e-12, atol=1e-12)),
        'strict_physical_fluid_bounds': bool(np.all(fluid_pos > [-.55, -.35, .05]) and np.all(fluid_pos < [.55, .35, .482])),
        'no_fluid_inside_physical_paddle': not bool(inside_paddle.any()),
        'all_finite_solid_faces_cover_tangential_extent': all(f['covered'] for solid in coverage.values() for f in solid.values()),
        'same_frozen_solids_motion_constants_execution': physical_parts(definition) == physical_parts(mother),
        'sources_unchanged': all(digest(Path(p)) == h for p, h in hashes.items()),
    }
    result = {'schema': 'ds02.f7.initial-native-audit.v1', 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'case_id': meta['case_id'], 'checks': checks, 'pass': all(checks.values()),
              'source_sha256': hashes, 'total_particles': total, 'fluid_particles': fluid,
              'fixed_particles': fixed, 'moving_particles': moving, 'native_massfluid_kg': values['MassFluid'],
              'actual_initial_fluid_mass_kg': actual_mass, 'continuous_wetted_mass_kg': meta['continuous_wetted_mass_kg'],
              'relative_initial_quadrature_mass_error': actual_mass / meta['continuous_wetted_mass_kg'] - 1,
              'fluid_bounds_m': [fluid_pos.min(axis=0).tolist(), fluid_pos.max(axis=0).tolist()],
              'finite_face_coverage': coverage, 'q_n_status': 'not_assessed', 'independent_case_count_increment': 0}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'pass': result['pass'], 'checks': checks, 'total': total, 'fluid': fluid, 'mass_kg': actual_mass}))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--prefix', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    sys.exit(0 if audit(a.metadata, a.prefix, a.output)['pass'] else 1)
