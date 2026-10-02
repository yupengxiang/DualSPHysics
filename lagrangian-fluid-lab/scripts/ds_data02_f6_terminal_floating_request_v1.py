"""Bind official FloatingInfo to its actual input, after native solver completion.

FloatingInfo's shipped help identifies PartFloatInfo.ibi4 as the input. This
request audits that complete file before and after execution through runtime v2;
it makes no claim to audit particle trajectories or the entire native tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_window(path):
    lines = path.read_text().splitlines()
    header = next(line for line in lines if line.startswith('Part;')).split(';')
    rows = [dict(zip(header, line.split(';'))) for line in lines
            if line.split(';')[0].isdigit()]
    times = [float(row['TimeStep [s]']) for row in rows]
    if (len(rows) != 241 or times[0] != 0 or times[-1] < 12 or
            any(b <= a for a, b in zip(times, times[1:])) or
            [int(row['Part']) for row in rows] != list(range(241))):
        raise ValueError('Complete consecutive native 241-frame 0..12 s window required')
    return {'frames': len(rows), 'last_time_s': times[-1],
            'all_NpOut': sum(int(row['NpOut'].replace(',', '')) for row in rows)}


def register(receipt_path, destination, attempt_id):
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('status'), receipt.get('returncode')) != ('completed', 0):
        raise ValueError('Actual terminal successful native solver receipt required')
    source_request = receipt['request']
    if source_request['family_id'] != 'F6' or source_request['kind'] != 'qualification':
        raise ValueError('F6 native qualification source required')
    source = receipt_path.parent / 'solver_output'
    window = native_window(source / 'RunPARTs.csv')
    xml = Path(source_request['command'][1]).with_suffix('.xml')
    floating = ET.parse(xml).getroot().find('./execution/particles/floating')
    if floating is None or int(floating.get('count', '0')) <= 0:
        raise ValueError('Actual native floating body identity required')
    mk = int(floating.get('mk'))
    lab = Path(__file__).resolve().parents[1]
    binary_root = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux')
    binary = binary_root / 'FloatingInfo_linux64'
    inputs = [Path(__file__).resolve(), receipt_path, xml,
              source / 'RunPARTs.csv', source / 'Run.out',
              source / 'data/PartFloatInfo.ibi4', binary,
              binary_root / 'DsphConfig.xml',
              binary_root.parents[1] / 'doc/help/FloatingInfo_Help.out',
              lab / 'scripts/ds_data02_runtime_v2.py',
              lab / 'scripts/ds_data02_strict_dispatch_v1.py']
    request = {'schema': 'ds02.runner-request.v2', 'family_id': 'F6',
               'case_id': source_request['case_id'], 'attempt_id': attempt_id,
               'kind': 'cpu', 'cpu_task_kind': 'audit', 'cpu_threads': 2,
               'max_wall_seconds': 300, 'estimated_storage_bytes': 2**26,
               'cwd': str(lab), 'worktree_root': str(lab.parent),
               'command': [str(binary), '-dirdata', str(source / 'data'),
                           '-onlymk:' + str(mk), '-savedata',
                           '{attempt_root}/floating/FloatingInfo',
                           '-savemotion:1', '-csvsep:0', '-createdirs:1'],
               'input_files': list(map(str, inputs)),
               'input_sha256': {str(p.resolve()): digest(p) for p in inputs},
               'native_window': window, 'floating_native_mk': mk,
               'source_solver_receipt': str(receipt_path),
               'source_solver_receipt_sha256': digest(receipt_path),
               'required_output': 'floating/FloatingInfo_mk' + str(mk) + '.csv',
               'hash_scope': 'Exact official floating input and terminal source provenance; no whole-particle-tree claim',
               'qualification_claim': 'none; complete saved rigid state only',
               'production_approval': 'none', 'independent_case_count_increment': 0}
    from ds_data02_strict_dispatch_v1 import validate_request
    validate_request(request)
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / 'request.json'
    target.write_text(json.dumps(request, indent=2) + '\n')
    return {'request': str(target), 'sha256': digest(target), 'native_window': window}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solver-receipt', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--attempt-id', required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.solver_receipt, args.destination, args.attempt_id)))
