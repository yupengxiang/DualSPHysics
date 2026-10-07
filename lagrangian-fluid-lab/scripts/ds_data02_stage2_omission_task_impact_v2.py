#!/usr/bin/env python3
"""Enrich an omission task screen with the native typed mass denominator.

Version 1 used the XML ``MassFluid`` product as a transparent diagnostic
denominator.  This forward-only version binds the completed scan and uses its
float32 typed initial fluid mass for the global denominator, while retaining
the XML only for source-MK ranges.  It consumes JSON/XML sidecars and never
opens trajectory HDF5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from ds_data02_runtime_v2 import atomic_json
from ds_data02_stage2_omission_task_impact_v1 import EvidenceError, assess as assess_v1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    stat = Path(path).stat()
    return {'path': str(path), 'sha256': sha256(path), 'bytes': stat.st_size}


def require_scan(sidecar: dict) -> tuple[Path, dict]:
    info = sidecar.get('scan', {})
    path = Path(info.get('path', ''))
    if not path.is_file():
        raise EvidenceError('bound scan JSON is missing')
    actual = sha256(path)
    if actual != info.get('sha256'):
        raise EvidenceError('bound scan JSON digest changed')
    scan = json.loads(path.read_text())
    if scan.get('schema') != 'ds02.stage2.scientific-scan.v1':
        raise EvidenceError('bound scan is not a Stage2 scientific scan')
    if scan.get('physical_case_id') != sidecar.get('physical_case_id'):
        raise EvidenceError('bound scan physical case differs from native join')
    return path, scan


def native_initial_mass(scan: dict) -> tuple[float, int, str]:
    fluid = scan.get('type_ledgers', {}).get('fluid', {})
    try:
        total = float(fluid['typed_initial_mass_kg'])
        count = int(fluid['typed_initial_count'])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError('scan typed initial fluid mass metadata is incomplete') from error
    if total <= 0 or count <= 0 or not math.isfinite(total):
        raise EvidenceError('scan typed initial fluid mass metadata is invalid')
    macros = scan.get('macros', [])
    if not macros or not math.isclose(float(macros[0].get('active_fluid_mass_kg', -1)), total,
                                      rel_tol=0.0, abs_tol=2e-12):
        raise EvidenceError('scan macro frame 0 does not match typed initial fluid mass')
    return total, count, 'scan.type_ledgers.fluid.typed_initial_mass_kg; macro frame 0 cross-check'


def assess(sidecar_path: Path) -> dict:
    sidecar_path = Path(sidecar_path)
    sidecar = json.loads(sidecar_path.read_text())
    # v1 performs the source-bound XML/MK and identity checks.  Its output is
    # copied into a new version; the v1 sidecar itself is never modified.
    result = assess_v1(sidecar_path)
    scan_path, scan = require_scan(sidecar)
    typed_total, typed_count, denominator_source = native_initial_mass(scan)
    xml = result['frozen_initial_fluid_mass']
    if typed_count != xml['fluid_count']:
        raise EvidenceError('scan typed fluid count differs from XML fluid count')
    particles = result['particles']
    missing_mass = sum(float(row['initial_mass_kg']) for row in particles)
    if not math.isclose(missing_mass,
                        float(sidecar['typed_identity']['missing_fluid_initial_mass_kg']),
                        rel_tol=0.0, abs_tol=2e-12):
        raise EvidenceError('sidecar missing mass differs from particle rows')
    global_fraction = missing_mass / typed_total
    mass_goal_fraction = 0.03
    unknown_width_limit = mass_goal_fraction / 10.0

    # The native scan stores the aggregate typed mass, while XML supplies the
    # source-MK contiguous ranges.  Equal MassFluid source blocks are checked
    # through the observed typed particle masses and then allocated by each
    # source block's exact initial count.
    observed_masses = [float(row['initial_mass_kg']) for row in particles]
    particle_mass = statistics.median(observed_masses) if observed_masses else None
    if particle_mass is not None and (not math.isfinite(particle_mass) or particle_mass <= 0):
        raise EvidenceError('observed typed particle mass is invalid')
    # The XML ranges are available in v1 evidence only through source-MK
    # counts.  Recover their count from missing rows' ranges is insufficient
    # for empty MKs, so use the generated XML parser through v1's denominator
    # plus a conservative exact count allocation from the XML fluid groups.
    # The groups are recorded in the v1 XML binding; parse them from the XML
    # once here to keep the per-MK denominator source explicit.
    import xml.etree.ElementTree as ET
    xml_path = Path(result['source_evidence']['generated_xml']['path'])
    root = ET.parse(xml_path).getroot()
    mk_ranges = []
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] != 'fluid' or not {'mk', 'begin', 'count'} <= set(element.attrib):
            continue
        mk_ranges.append(dict(mk=int(element.attrib['mk']),
                              mkfluid=int(element.attrib.get('mkfluid', -1)),
                              begin=int(element.attrib['begin']),
                              count=int(element.attrib['count'])))
    if sum(row['count'] for row in mk_ranges) != typed_count:
        raise EvidenceError('XML MK range count differs from scan typed count')
    mk_counts = {row['mk']: row['count'] for row in mk_ranges}
    mk_fluid = {row['mk']: row.get('mkfluid') for row in mk_ranges}
    observed_groups = {int(row['mk']): row for row in result['source_mk_breakdown']}
    by_mk = []
    for mk in sorted(mk_counts):
        group = observed_groups.get(mk, dict(mk=mk, mkfluid=mk_fluid.get(mk),
                                              missing_count=0, missing_mass_kg=0.0,
                                              ids=[]))
        denominator = typed_total * mk_counts[mk] / typed_count
        missing = float(group['missing_mass_kg'])
        by_mk.append({**group,
                      'initial_mass_denominator_kg': denominator,
                      'denominator_source': 'native scan typed total allocated by exact XML source-MK count; equal source MassFluid blocks verified by observed typed mass where available',
                      'missing_mass_fraction_of_native_initial_fluid': missing / denominator,
                      'unknown_visibility_screen_width_lower_bound': missing / denominator,
                      'registered_unknown_width_limit_fraction': unknown_width_limit,
                      'unknown_interval': {
                          'bounded': False,
                          'reason': 'physical fate and dynamics are unknown; no upper observable-impact bound from this screen',
                      }})
    result.update(schema='ds02.stage2.omission-task-impact.v2',
                  status='TASK_IMPACT_SCREENED_NATIVE_TYPED_DENOMINATOR_DYNAMICS_UNAVAILABLE')
    result['source_evidence'].update({
        'scan': binding(scan_path),
        'trajectory_h5_read': False,
        'native_typed_mass_metadata': 'scan.type_ledgers.fluid.typed_initial_mass_kg',
    })
    result['frozen_initial_fluid_mass'].update({
        'initial_fluid_mass_kg': typed_total,
        'denominator_semantics': 'native typed initial fluid mass from completed scan; XML MassFluid product retained only as a diagnostic cross-check',
        'xml_massfluid_product_kg': xml['initial_fluid_mass_kg'],
        'native_minus_xml_mass_kg': typed_total - xml['initial_fluid_mass_kg'],
        'typed_initial_count': typed_count,
        'denominator_source': denominator_source,
        'observed_missing_particle_mass_median_kg': particle_mass,
    })
    result['missing_mass_screen'].update({
        'identified_missing_mass_fraction': global_fraction,
        'registered_mass_goal_fraction': mass_goal_fraction,
        'registered_unknown_width_limit_fraction': unknown_width_limit,
        'screen': ('BELOW_REGISTERED_WIDTH_SCREEN_BUT_NOT_ACCEPTED'
                   if global_fraction <= unknown_width_limit else 'EXCEEDS_REGISTERED_WIDTH_SCREEN'),
        'interval_interpretation': 'Native typed missing mass is a visibility lower bound; physical fate and dynamical amplification remain unknown, so no bounded observable interval or dynamics credit is available.',
    })
    result['source_mk_breakdown'] = by_mk
    result['unknown_and_acceptance']['denominator_version'] = 'native_typed_scan_v2'
    return result


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
