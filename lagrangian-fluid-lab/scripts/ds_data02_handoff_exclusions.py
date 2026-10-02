#!/usr/bin/env python3
"""Bind preserved native exclusion records to immutable trajectory identities.

Numerical exclusions remain unknown physical fate. This prepares new full
integrity audits, without changing trajectories, labels or numerical scope.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_handoff_inventory import binding, load, sha256
from ds_data02_handoff_contracts import UNITS


def read_runparts(path):
    # Official RunPARTs appends '# field: description' documentation.
    # Ignore only documented comments and empty lines, never malformed data.
    lines = [s for s in Path(path).read_text().splitlines()
             if s.strip() and not s.lstrip().startswith('#')]
    reader = csv.DictReader(lines, delimiter=';')
    fields = ('NpOut', 'NpOutPos', 'NpOutRho', 'NpOutMov')
    if reader.fieldnames is None or not set(('Part', 'TimeStep [s]', *fields)) <= set(reader.fieldnames):
        raise ValueError('native RunPARTs header missing')
    totals = dict.fromkeys(fields, 0)
    rows = []
    for raw in reader:
        part = int(raw['Part'].replace(',', ''))
        time = float(raw['TimeStep [s]'])
        if part != len(rows) or not math.isfinite(time) or (rows and time <= rows[-1]['time_s']):
            raise ValueError('native PART sequence/time is incomplete or invalid')
        counts = {f: int(raw[f].replace(',', '')) for f in fields}
        if any(v < 0 for v in counts.values()) or counts['NpOut'] != sum(counts[f] for f in fields[1:]):
            raise ValueError('invalid native exclusion counters')
        rows.append({'part': part, 'time_s': time, **counts})
        for f in fields:totals[f] += counts[f]
    if not rows:raise ValueError('native PART records missing')
    return {'rows': rows, 'totals': totals}


def read_partout(path):
    rows = []
    with Path(path).open() as stream:
        for raw in csv.DictReader(stream):
            row = {k.strip():v.strip() for k,v in raw.items() if k and v is not None}
            position = [float(row[f'Pos.{axis} [m]']) for axis in 'xyz']
            density = float(row['Rhop [kg/m^3]'])
            code = int(row['Motive'])
            if code not in (1,2,3) or not all(math.isfinite(v) for v in (*position,density)):
                raise ValueError('invalid native exclusion state/motive')
            rows.append({'idp':int(row['Idp']), 'part_out':int(row['PartOut']),
                         'motive_code':code, 'motive':{1:'position',2:'density',3:'movement'}[code],
                         'position_m':position, 'density_kg_m3':density})
    return rows


def bind_exclusions(ids, zones, types, first_missing, frames, records, totals):
    if not (len(ids) == len(zones) == len(types) == len(first_missing)):
        raise ValueError('identity axis length mismatch')
    keys = [(int(z), int(i)) for z, i in zip(zones, ids)]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate typed identity')
    expected = {k: int(f) for k, t, f in zip(keys, types, first_missing)
                if int(t) == 3 and int(f) >= 1}
    by_id = {}
    for key in expected:
        by_id.setdefault(key[1], []).append(key)
    observed = set()
    counts = {1: 0, 2: 0, 3: 0}
    rows = []
    for record in records:
        # Official uniform-resolution CSV has Idp but no zone. Resolve it
        # against actual H5 typed identities and reject ambiguous IDs.
        matches = by_id.get(record['idp'], [])
        if len(matches) != 1:
            raise ValueError('native Idp is absent or ambiguous in missing fluid cohort')
        key = matches[0]
        if key in observed:
            raise ValueError('duplicate native exclusion')
        observed.add(key)
        first = expected[key]
        if not 1 <= first < frames or first != record['part_out']:
            raise ValueError('native PartOut does not match actual first missing frame')
        code = record['motive_code']
        if code not in counts:
            raise ValueError('unknown native motive code')
        counts[code] += 1
        rows.append({'zone': key[0], 'idp': key[1], 'first_missing_frame': first,
                     'motive': record['motive'], 'motive_code': code,
                     'partvtkout_position_m': record['position_m'],
                     'partvtkout_density_kg_m3': record['density_kg_m3']})
    if observed != set(expected):
        raise ValueError('native exclusion set differs from missing fluid cohort')
    if totals['NpOut'] != len(expected) or any(
            totals[name] != counts[code] for name, code in
            [('NpOutPos', 1), ('NpOutRho', 2), ('NpOutMov', 3)]):
        raise ValueError('native motive counts differ from RunPARTs')
    return {'excluded_particles': rows, 'h5_full_timeline_frames': frames,
            'h5_full_timeline_checked': True,
            'runparts_counts': {name: totals[field] for name, field in
                               [('npout_sum', 'NpOut'), ('npoutpos_sum', 'NpOutPos'),
                                ('npoutrho_sum', 'NpOutRho'), ('npoutmov_sum', 'NpOutMov')]},
            'interpretation': 'Native numerical exclusions; physical fate unknown. No Q-N qualification.'}


def prepare_case(row, lab, output):
    import h5py
    trajectory = Path(row['trajectory'])
    report_path, audit_path = trajectory.parent/'conversion-report.json', trajectory.parent/'audit.json'
    report, audit = load(report_path), load(audit_path)
    life = audit['lifecycle']
    if not life['full_timeline_checked'] or any(life[k] != 0 for k in
            ('introduced_after_initial_count', 'revived_identity_count', 'type_changed_identity_count')):
        raise ValueError('unresolved lifecycle change beyond exclusions')
    if audit['structural_failures'] or report['units'] != UNITS:
        raise ValueError('structural failures or missing native units')
    source = report['source_provenance']
    for name in ('generated_xml', 'solver_receipt', 'gencase_receipt'):
        if sha256(source[name]['path']) != source[name]['sha256']:
            raise ValueError('consumed source hash changed: '+name)
    xml = Path(source['generated_xml']['path']); root = ET.parse(xml).getroot()
    if root.find('.//geometry') is None or root.find('.//inout') is not None:
        raise ValueError('finite actual source geometry required')
    solver_receipt = Path(source['solver_receipt']['path']); solver = load(solver_receipt)
    if solver.get('status') != 'completed' or solver.get('returncode') != 0:
        raise ValueError('source solver receipt did not complete')
    log = Path(audit['solver_log']['path'])
    if sha256(log) != audit['solver_log']['sha256']:
        raise ValueError('source log hash changed')
    runparts_path = Path(source['data_root']).parent/'RunPARTs.csv'
    decoded = trajectory.parents[1]/'root-native-exclusion-decode-001'
    receipt = load(decoded/'execution-receipt.json')
    if receipt.get('status') != 'completed' or receipt.get('returncode') != 0:
        raise ValueError('official native decoding did not complete')
    for path, expected in receipt['input_hashes_at_launch'].items():
        if sha256(path) != expected:
            raise ValueError('native decoder input changed')
    runparts = read_runparts(runparts_path)
    native = read_partout(decoded/'PartOut.csv')
    with h5py.File(trajectory, 'r') as handle:
        frames = len(handle['time'])
        if len(runparts['rows']) != frames:
            raise ValueError('native PART timeline length differs from H5')
        ledger = bind_exclusions(handle['particle_id'][:], handle['particle_zone'][:],
                                 handle['initial_type'][:], life['first_missing_frame_by_particle'],
                                 frames, native, runparts['totals'])
    if len(ledger['excluded_particles']) != life['initial_missing_at_final_count']:
        raise ValueError('native excluded count differs from old full timeline')
    inputs = []
    for name, expected in solver['input_hashes_at_launch'].items():
        p = Path(name)
        if p.suffix.lower() in ('.csv', '.dat'):
            if sha256(p) != expected:
                raise ValueError('forcing file changed since source launch')
            inputs.append(binding(p))
    ledger['source_evidence'] = [binding(runparts_path), binding(decoded/'PartOut.csv'),
                                 binding(decoded/'execution-receipt.json'), binding(audit_path)]
    metadata = {'schema':'ds02.native-exclusion-source-contract.v1',
                'family_id':row['family_id'], 'case_id':row['case_id'],
                'units': report['units'], 'coordinate_frame':report['coordinate_frame'],
                'geometry':{'generated_xml':binding(xml), 'geometry_xml':ET.tostring(root.find('.//geometry'), encoding='unicode')},
                'control':{'generated_xml':binding(xml), 'forcing_files':inputs,
                           'native_control_xml':[ET.tostring(n,encoding='unicode') for tag in
                                                 ('motion','special','constantsdef','parameters') for n in root.findall('.//'+tag)]},
                'boundary_mode':'open',
                'lifecycle_mode':'finite_initial_numerical_cohort_with_exclusions',
                'native_exclusion_ledger':ledger, 'source_solver_receipt':binding(solver_receipt),
                'source_gencase_receipt':source['gencase_receipt'],
                'historical_gencase_launch_input_hashes_available':bool(load(source['gencase_receipt']['path']).get('input_hashes_at_launch')),
                'trajectory_sha256_recorded':report['output_sha256'],
                'physical_fate':'unknown for numerical exclusions; no physical spill inference',
                'numerical_qualification':'not_assessed','production_eligibility':'not_evaluated'}
    folder = output/row['case_id']; folder.mkdir(exist_ok=False)
    contract = folder/'lifecycle-source-contract.json';contract.write_text(json.dumps(metadata,indent=2)+'\n')
    files = [trajectory, report_path, audit_path, contract, xml, solver_receipt, log,
             Path(source['gencase_receipt']['path']), runparts_path, decoded/'PartOut.csv',
             decoded/'execution-receipt.json', lab/'scripts/ds_data02_integrity.py']
    files += [Path(x['path']) for x in inputs]
    request = {'schema':'ds-data-02.runner.request.v1', 'family_id':row['family_id'],
               'case_id':row['case_id'], 'attempt_id':'root-integrity-native-exclusion-contract-001',
               'kind':'cpu', 'cpu_task_kind':'audit', 'cpu_threads':2, 'max_wall_seconds':3600,
               'estimated_storage_bytes':128*1024**2, 'worktree_root':str(lab.parent), 'cwd':str(lab),
               'input_files':[str(p) for p in files],
               'command':[str(lab/'.venv/bin/python'),str(lab/'scripts/ds_data02_integrity.py'),
                          str(trajectory),'--solver-log',str(log),'--metadata-json',str(contract),
                          '--particle-chunk','65536','--output','{attempt_root}/integrity.json'],
               'request_note':'Full timeline audit independently checks each native numerical exclusion. Physical fate unknown, Q-N unassessed; preserve source H5 and labels.'}
    path = folder/'audit-request.json';path.write_text(json.dumps(request,indent=2)+'\n')
    return {'case_id':row['case_id'],'family_id':row['family_id'],
            'status':'new_audit_request_ready','request':str(path),'excluded_count':len(ledger['excluded_particles'])}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--lab',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True)
    rows=[]
    for row in load(a.inventory)['cases']:
        if row.get('integrity_status')!='incomplete_contract':continue
        audit=load(Path(row['trajectory']).parent/'audit.json')
        if not audit['lifecycle']['initial_missing_at_final_count']:continue
        try: rows.append(prepare_case(row,a.lab,a.output))
        except (OSError,ValueError,KeyError) as error:
            rows.append({'case_id':row['case_id'],'status':'requires_investigation','reason':str(error)})
    (a.output/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({'ready':sum(r['status']=='new_audit_request_ready' for r in rows),'pending':sum(r['status']!='new_audit_request_ready' for r in rows)}))


if __name__=='__main__':main()
