#!/usr/bin/env python3
"""Preregister and audit F4 centered finite boxes from consumed mother bindings."""
import argparse
import copy
import importlib.util
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ds_data02_native_labels import digest
from ds_data02_f7_initial_native_audit_v1 import canonical, face_coverage

LAB = Path(__file__).resolve().parents[1]
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
OFFICIAL = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux')


def write(path, value):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2) + '\n')


def sources_from_artifact(artifact):
    trajectory = Path(artifact['trajectory_hdf5']['path'])
    receipt = trajectory.parent / 'execution-receipt.json'
    conversion = json.loads(receipt.read_text())
    args = conversion['request']['command']
    owner = Path(args[args.index('--owner-metadata') + 1])
    generated = Path(args[args.index('--generated-xml') + 1])
    for path in (owner, generated):
        assert digest(path) == conversion['input_hashes_at_launch'][str(path)]
    meta = json.loads(owner.read_text())
    original = Path(meta['source_binding']['definition_xml']['path'])
    assert digest(original) == meta['source_binding']['definition_xml']['sha256']
    return owner, generated, original, receipt, meta


def prepare(pack):
    pack.mkdir(parents=True, exist_ok=False)
    evidence = LAB / 'campaigns/ds-data-02/families/F4/evidence/f4-actual-evidence-v1.json'
    artifacts = [a for a in json.loads(evidence.read_text())['artifacts']
                 if a['resolution'] == 'fine' and a['time_variant'] == 'native']
    assert len(artifacts) == 2
    rows = []
    for artifact in artifacts:
        owner, generated, original, receipt, old = sources_from_artifact(artifact)
        binding = old['physical_binding']
        regions = {name: box for name, box in binding['geometry'].items() if 'mkfluid' in box}
        root = ET.parse(original).getroot()
        label = 'DROP' if 'drop' in artifact['artifact_id'] else 'COL'
        # The native draw sizes intentionally count centers; physical volumes
        # are the original consumed continuum binding, not drawbox size cubed.
        original_sources = [owner, generated, original, receipt, evidence]
        for dp, tag in ((.01, 'DP010'), (.005, 'DP005'), (.0025, 'DP0025')):
            cid = f'F4_{label}_CENTERED_REFERENCE_001_{tag}'
            definition = copy.deepcopy(root)
            numeric = definition.find('casedef/geometry/definition')
            numeric.set('dp', format(dp, '.17g'))
            ref = numeric.find('pointref')
            if ref is None:
                ref = ET.SubElement(numeric, 'pointref')
            ref.attrib.update({axis: format(dp / 2, '.17g') for axis in 'xyz'})
            main = definition.find('casedef/geometry/commands/mainlist')
            mk = None
            counts = {}
            for element in main:
                if element.tag == 'setmkfluid':
                    mk = int(element.attrib['mk'])
                elif element.tag == 'setmkbound':
                    mk = None
                elif element.tag == 'drawbox' and mk is not None:
                    name, box = next((n, b) for n, b in regions.items() if b['mkfluid'] == mk)
                    low, size = np.asarray(box['low_m']), np.asarray(box['size_m'])
                    count = np.rint(size / dp).astype(int)
                    if not np.allclose(size / dp, count, rtol=0, atol=1e-9):
                        raise ValueError('unregistered noncommensurate source size')
                    if not np.allclose(low / dp, np.rint(low / dp), rtol=0, atol=1e-9):
                        raise ValueError('source does not share registered global center phase')
                    element.find('point').attrib.update({axis: format(v, '.17g') for axis, v in zip('xyz', low + dp / 2)})
                    element.find('size').attrib.update({axis: format(v, '.17g') for axis, v in zip('xyz', size - dp + 1e-9)})
                    counts[name] = int(np.prod(count))
            # Keep the native numeric fields, constants, velocities, walls,
            # complete 0-1.2s window and .001s save cadence unchanged.
            path = pack / (cid + '_Def.xml')
            ET.ElementTree(definition).write(path, encoding='utf-8', xml_declaration=True)
            meta = {'schema': 'ds02.f4.centered-reference-preregistration.v1', 'case_id': cid,
                    'physical_case_id': binding['physical_case_id'], 'dp_m': dp,
                    'physical_binding': binding, 'physical_binding_sha256': old['physical_binding_sha256'],
                    'source_regions': regions, 'expected_counts_by_source': counts,
                    'continuous_mass_by_source_kg': {n: float(np.prod(b['size_m']) * binding['density_kg_m3']) for n, b in regions.items()},
                    'definition_sha256': digest(path), 'original_source_sha256': {str(p): digest(p) for p in original_sources},
                    'original_definition': str(original), 'original_owner_metadata': str(owner),
                    'numeric_changes': 'dp and shared half-dp lattice phase; centered finite population in original declared source regions. Walls/initial velocities/constants/execution unchanged.',
                    'repair_class': 'first explicit centered initialization recipe; three-resolution reference matrix preregistered before solver results',
                    'comparison_budget': {'macro_relative': .05, 'event_relative': .02, 'temporal_share': .2},
                    'old_extreme_spread_retained': True, 'independent_case_count_increment': 0,
                    'q_n_status': 'not_assessed', 'production_approval': 'none'}
            mp = pack / (cid + '.metadata.json')
            write(mp, meta)
            inputs = original_sources + [path, mp, Path(__file__).resolve(),
                        LAB / 'scripts/ds_data02_runtime_v2.py', OFFICIAL / 'GenCase_linux64']
            request = {'schema': 'ds02.runner-request.v2', 'family_id': 'F4', 'case_id': cid,
                       'attempt_id': 'gencase-centered-reference-001', 'kind': 'cpu', 'cpu_task_kind': 'gencase',
                       'cpu_threads': 4, 'max_wall_seconds': 300, 'estimated_storage_bytes': 2**30,
                       'cwd': str(pack), 'worktree_root': str(LAB),
                       'command': [str(OFFICIAL / 'GenCase_linux64'), str(path.with_suffix('')), '{attempt_root}/' + cid, '-save:all'],
                       'input_files': [str(p) for p in inputs], 'input_sha256': {str(p): digest(p) for p in inputs},
                       'qualification_claim': 'none; actual strict continuum population QA required before GPU'}
            qp = pack / (cid + '_gencase_request.json')
            write(qp, request)
            rows.append({'case_id': cid, 'metadata': str(mp), 'gencase_request': str(qp), 'expected_fluid_count': sum(counts.values())})
    write(pack / 'preregistered_reference_matrix_001.json', {'schema': 'ds02.f4.centered-reference-matrix.v1',
          'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'rows': rows,
          'scope': 'Both original mechanism mothers; full1.2s with .001s saves, no production or independent-case credit. Preserve full extrema and existing thresholds; no percentile substitution.'})
    print(json.dumps(rows, indent=2))


def audit(metadata, prefix, output):
    meta = json.loads(metadata.read_text())
    native = prefix.with_suffix('.bi4')
    generated = prefix.with_suffix('.xml')
    receipt = prefix.parent / 'execution-receipt.json'
    definition = metadata.parent / (meta['case_id'] + '_Def.xml')
    helper = LAB / 'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py'
    decoder = LAB / 'scripts/f8_r008_safe_bi4_decoder_v1.py'
    spec = importlib.util.spec_from_file_location('f4_readonly_initial_helper', helper)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    scanner = module._load_safe_decoder(decoder)
    inputs = [metadata, definition, native, generated, receipt, helper, decoder, Path(__file__).resolve()]
    hashes = {str(p): digest(p) for p in inputs}
    assert hashes[str(definition)] == meta['definition_sha256']
    assert all(digest(Path(p)) == h for p, h in meta['original_source_sha256'].items())
    fd = os.open(native, os.O_RDONLY)
    try:
        scan = scanner.scan_bi4_fd(fd, hashes[str(native)])
    finally:
        os.close(fd)
    values = {v.name: v.value for v in scan.root.values}
    arrays = {a.name: a for a in scan.arrays if a.item_path[-1] == scan.root.children[0].name}
    assert arrays['Posd'].type_code == 23
    pos = np.memmap(native, mode='r', dtype='<f8', offset=arrays['Posd'].offset, shape=(arrays['Posd'].count, 3))
    ids = np.memmap(native, mode='r', dtype='<u4', offset=arrays['Idp'].offset, shape=(arrays['Idp'].count,))
    total, fixed, fluid = [int(values[k]) for k in ('CaseNp', 'CaseNfixed', 'CaseNfluid')]
    xml = ET.parse(generated).getroot()
    rows = []
    for name, box in meta['source_regions'].items():
        block = next(b for b in xml.findall('execution/particles/fluid') if int(b.attrib['mkfluid']) == box['mkfluid'])
        begin, count = int(block.attrib['begin']), int(block.attrib['count'])
        cloud = pos[(ids >= begin) & (ids < begin + count)]
        low, size, dp = np.asarray(box['low_m']), np.asarray(box['size_m']), meta['dp_m']
        normalized = (cloud - low) / dp - .5
        lattice = np.rint(normalized).astype(int)
        axis_counts = np.rint(size / dp).astype(int)
        checks = {'registered_count': count == meta['expected_counts_by_source'][name],
                  'native_mass_matches_continuum': bool(np.isclose(count * values['MassFluid'], meta['continuous_mass_by_source_kg'][name], rtol=1e-12, atol=1e-12)),
                  'strict_continuum_center_bounds': bool(np.all(cloud > low) and np.all(cloud < low + size)),
                  'exact_center_lattice': bool(np.allclose(normalized, lattice, rtol=0, atol=1e-7)),
                  'complete_cell_population': bool(np.all(lattice >= 0) and np.all(lattice < axis_counts) and len(np.unique(lattice, axis=0)) == np.prod(axis_counts))}
        rows.append({'source': name, 'fluid_count': count, 'native_mass_kg': count * values['MassFluid'],
                     'bounds_m': [cloud.min(axis=0).tolist(), cloud.max(axis=0).tolist()], 'checks': checks})
    tank = meta['physical_binding']['geometry']['tank']
    low, high = np.asarray(tank['low_m']), np.asarray(tank['low_m']) + tank['size_m']
    coverage = face_coverage(pos[ids < fixed], low, high, [(0,0),(0,1),(1,0),(1,1),(2,0)], meta['dp_m'])
    new, old = ET.parse(definition).getroot(), ET.parse(meta['original_definition']).getroot()
    invariant_paths = ['casedef/constantsdef', 'casedef/initials', 'execution']
    checks = {'same_constants_initial_velocities_execution': all(canonical(new.find(p)) == canonical(old.find(p)) for p in invariant_paths),
              'true_3d': not bool(values.get('Data2d', False)) and len(np.unique(pos[ids >= fixed, 1])) > 1,
              'finite_unique_complete_ids': bool(np.isfinite(pos).all() and len(ids) == total and np.array_equal(np.sort(ids), np.arange(total))),
              'complete_type_partition': total == fixed + fluid and fluid == sum(r['fluid_count'] for r in rows),
              'all_source_population_checks': all(all(r['checks'].values()) for r in rows),
              'finite_tank_face_coverage': all(f['covered'] for f in coverage.values()),
              'sources_unchanged': all(digest(Path(p)) == h for p, h in hashes.items()),
              'gencase_completed': json.loads(receipt.read_text())['status'] == 'completed'}
    result = {'schema': 'ds02.f4.centered-reference-native-audit.v1', 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'case_id': meta['case_id'], 'checks': checks, 'pass': all(checks.values()), 'total_particles': total,
              'fluid_particles': fluid, 'source_rows': rows, 'finite_tank_face_coverage': coverage,
              'source_sha256': hashes, 'q_n_status': 'not_assessed', 'production_approval': 'none'}
    write(output, result)
    print(json.dumps({'case_id': meta['case_id'], 'pass': result['pass'], 'checks': checks, 'total_particles': total, 'fluid_particles': fluid}))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--pack', type=Path, required=True)
    aud = sub.add_parser('audit')
    aud.add_argument('--metadata', type=Path, required=True)
    aud.add_argument('--prefix', type=Path, required=True)
    aud.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.mode == 'prepare':
        prepare(args.pack)
    else:
        sys.exit(0 if audit(args.metadata, args.prefix, args.output)['pass'] else 1)
