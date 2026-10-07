#!/usr/bin/env python3
"""Compute source-bound missing-mass task screens from an immutable join.

This is a small post-join audit.  It consumes the completed native omission
sidecar and its generated XML only; it never opens the trajectory HDF5 and it
does not turn a mass screen into a Q-N/Q-E or dynamical result.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_runtime_v2 import atomic_json


class EvidenceError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    stat = Path(path).stat()
    return {'path': str(path), 'sha256': sha256(path), 'bytes': stat.st_size}


def require_file(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f'{label} is missing: {path}')
    return path


def require_digest(path: Path, expected: str, label: str) -> Path:
    require_file(path, label)
    actual = sha256(path)
    if actual != expected:
        raise EvidenceError(f'{label} digest changed: {path}')
    return path


def _first(root: ET.Element, tag: str) -> ET.Element:
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] == tag:
            return element
    raise EvidenceError(f'XML element {tag} is missing')


def _descendants(root: ET.Element, tag: str):
    return (element for element in root.iter() if element.tag.rsplit('}', 1)[-1] == tag)


def parse_fluid_mk_ranges(path: Path) -> dict:
    path = require_file(path, 'generated XML')
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise EvidenceError(f'generated XML is invalid: {path}') from error
    fluid = _first(root, 'fluid')
    try:
        fluid_count = int(fluid.attrib['count'])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError('XML fluid count is invalid') from error
    massfluid = _first(root, 'massfluid')
    try:
        mass_kg = float(massfluid.attrib['value'])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError('XML massfluid is invalid') from error
    if fluid_count <= 0 or not math.isfinite(mass_kg) or mass_kg <= 0:
        raise EvidenceError('XML frozen fluid mass basis is invalid')
    ranges = []
    for element in _descendants(root, 'fluid'):
        if not {'mkfluid', 'mk', 'begin', 'count'} <= set(element.attrib):
            continue
        try:
            row = dict(mkfluid=int(element.attrib['mkfluid']),
                       mk=int(element.attrib['mk']),
                       begin=int(element.attrib['begin']),
                       count=int(element.attrib['count']))
        except (TypeError, ValueError) as error:
            raise EvidenceError('XML fluid mk range is invalid') from error
        if row['count'] <= 0:
            raise EvidenceError('XML fluid mk range is empty')
        row['end_exclusive'] = row['begin'] + row['count']
        ranges.append(row)
    if not ranges:
        raise EvidenceError('XML has no per-mk fluid ranges')
    ranges.sort(key=lambda row: row['begin'])
    for previous, current in zip(ranges, ranges[1:]):
        if current['begin'] != previous['end_exclusive']:
            raise EvidenceError('XML fluid mk ranges are not contiguous')
    if sum(row['count'] for row in ranges) != fluid_count:
        raise EvidenceError('XML per-mk counts do not equal frozen fluid count')
    return dict(fluid_count=fluid_count, massfluid_kg=mass_kg,
                initial_fluid_mass_kg=fluid_count * mass_kg, ranges=ranges,
                xml_sha256=sha256(path), xml_path=str(path))


def _mk_for_idp(idp: int, ranges: list[dict]) -> dict:
    matches = [row for row in ranges if row['begin'] <= idp < row['end_exclusive']]
    if len(matches) != 1:
        raise EvidenceError(f'Idp {idp} does not map uniquely to an XML fluid mk range')
    return matches[0]


def assess(sidecar_path: Path) -> dict:
    sidecar_path = require_file(sidecar_path, 'native omission sidecar')
    sidecar = json.loads(sidecar_path.read_text())
    if sidecar.get('schema') != 'ds02.stage2.omission-forensics.v2':
        raise EvidenceError('task screen requires native omission-forensics.v2')
    if sidecar.get('status') != 'CAUSES_RECONCILED':
        raise EvidenceError('task screen requires a completed source-bound join')
    if sidecar.get('physical_fate') and 'UNKNOWN' not in sidecar['physical_fate']:
        raise EvidenceError('task screen cannot consume a resolved physical fate')
    if sidecar.get('dynamical_impact') and 'NOT_ASSESSED' not in sidecar['dynamical_impact']:
        raise EvidenceError('task screen cannot grant a dynamics result')
    source = sidecar.get('source_provenance', {}).get('generated_xml', {})
    xml_path = Path(source.get('path', ''))
    require_digest(xml_path, source.get('sha256'), 'generated XML')
    xml = parse_fluid_mk_ranges(xml_path)
    particles = sidecar.get('excluded_particles', [])
    typed = sidecar.get('typed_identity', {})
    if typed.get('missing_fluid_count') != len(particles):
        raise EvidenceError('typed missing count differs from excluded particle rows')
    seen = set()
    by_mk = defaultdict(lambda: dict(mk=None, mkfluid=None, missing_count=0,
                                      missing_mass_kg=0.0, ids=[]))
    particle_rows = []
    first_windows = []
    for particle in particles:
        try:
            zone = int(particle['zone'])
            idp = int(particle['idp'])
            mass = float(particle['initial_mass_kg'])
            frame = int(particle['first_missing_frame'])
            bracket = [float(x) for x in particle['first_missing_bracket_s']]
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceError('excluded particle row is incomplete') from error
        key = (zone, idp)
        if key in seen:
            raise EvidenceError(f'duplicate excluded identity: {key}')
        seen.add(key)
        if mass <= 0 or not math.isfinite(mass) or len(bracket) != 2 or bracket[0] > bracket[1]:
            raise EvidenceError(f'invalid mass or first-gap window for {key}')
        mk = _mk_for_idp(idp, xml['ranges'])
        group = by_mk[mk['mk']]
        group['mk'] = mk['mk']
        group['mkfluid'] = mk['mkfluid']
        group['missing_count'] += 1
        group['missing_mass_kg'] += mass
        group['ids'].append({'zone': zone, 'idp': idp, 'first_missing_frame': frame,
                             'first_missing_bracket_s': bracket,
                             'initial_mass_kg': mass,
                             'native_motive': particle.get('native_motive'),
                             'native_exit_cause': particle.get('native_exit_cause')})
        first_windows.append((bracket[0], bracket[1]))
        particle_rows.append({**group['ids'][-1], 'source_mk': mk['mk'],
                              'source_mkfluid': mk['mkfluid']})
    missing_mass = sum(float(row['initial_mass_kg']) for row in particle_rows)
    fraction = missing_mass / xml['initial_fluid_mass_kg']
    mass_goal_fraction = 0.03
    unknown_width_limit = mass_goal_fraction / 10.0
    by_mk_rows = []
    for mk in sorted(by_mk):
        group = by_mk[mk]
        by_mk_rows.append({**group,
                           'missing_mass_fraction_of_frozen_initial_fluid':
                               group['missing_mass_kg'] / xml['initial_fluid_mass_kg']})
    if first_windows:
        first_window = {
            'earliest_start_s': min(row[0] for row in first_windows),
            'latest_start_s': max(row[0] for row in first_windows),
            'earliest_end_s': min(row[1] for row in first_windows),
            'latest_end_s': max(row[1] for row in first_windows),
        }
    else:
        first_window = None
    if fraction <= unknown_width_limit:
        mass_screen = 'BELOW_REGISTERED_WIDTH_SCREEN_BUT_NOT_ACCEPTED'
    else:
        mass_screen = 'EXCEEDS_REGISTERED_WIDTH_SCREEN'
    return {
        'schema': 'ds02.stage2.omission-task-impact.v1',
        'status': 'TASK_IMPACT_SCREENED_DYNAMICS_UNAVAILABLE',
        'family_id': sidecar['family_id'],
        'physical_case_id': sidecar['physical_case_id'],
        'input_sidecar': binding(sidecar_path),
        'source_evidence': {
            'generated_xml': binding(xml_path),
            'trajectory_h5_read': False,
            'decoder_reused': True,
            'source_binding_statement': 'The immutable native join is the producer of particle identities, masses, motives, and first-gap states; XML supplies the frozen initial fluid denominator and mk ranges.',
        },
        'frozen_initial_fluid_mass': {
            'fluid_count': xml['fluid_count'],
            'massfluid_kg': xml['massfluid_kg'],
            'initial_fluid_mass_kg': xml['initial_fluid_mass_kg'],
            'denominator_semantics': 'XML generated-case fluid count multiplied by XML MassFluid; this is a source-bound initial mass denominator, not a fate or conservation result.',
        },
        'missing_mass_screen': {
            'identified_missing_mass_kg': missing_mass,
            'identified_missing_mass_fraction': fraction,
            'registered_mass_goal_fraction': mass_goal_fraction,
            'registered_unknown_width_limit_fraction': unknown_width_limit,
            'screen': mass_screen,
            'interval_interpretation': 'The identified mass is a visibility lower bound.  Physical fate, unobserved state, and any dynamical amplification remain unknown; no bounded observable interval is available from this screen alone.',
        },
        'source_mk_breakdown': by_mk_rows,
        'particles': particle_rows,
        'first_disappearance_window': first_window,
        'possible_observable_unknowns': [
            'fluid mass visibility and count-based occupancy',
            'center of mass and momentum-derived observables',
            'kinetic/potential energy and pressure/force coupling',
            'integrated wall or sensor load and any downstream timing',
        ],
        'unknown_and_acceptance': {
            'physical_fate': 'UNKNOWN',
            'dynamical_impact': 'NOT_ASSESSED',
            'QN': 'NOT_ASSESSED',
            'QE': 'NOT_ASSESSED',
            'mass_screen_is_not_dynamics_credit': True,
            'unavailable_reason': 'No paired reference, conserved-fate proof, or bounded observable-impact experiment was run; this post-join screen cannot supply one.',
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sidecar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve existing task-impact sidecar: ' + str(args.output))
    result = assess(args.sidecar)
    atomic_json(args.output, result)
    print(json.dumps({'status': result['status'], 'case': result['physical_case_id'],
                      'missing_fraction': result['missing_mass_screen']['identified_missing_mass_fraction'],
                      'screen': result['missing_mass_screen']['screen']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
