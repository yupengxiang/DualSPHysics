"""Compare actual official rigid CSVs with the unchanged frozen F6 operator.

This produces rigid-state evidence only. It does not synthesize particle
trajectories or grant numerical qualification from a successful process exit.
"""
import argparse
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from ds_data02_f6_spatial_compare_v1 import compare, sha256, BUDGET
from ds_data02_f6_terminal_floating_request_v1 import native_window


def terminal(path):
    receipt = json.loads(path.read_text())
    if (receipt.get('status'), receipt.get('returncode')) != ('completed', 0):
        raise ValueError('Actual successful terminal receipt required: ' + str(path))
    if receipt['input_hashes_at_launch'] != receipt['input_hashes_after_run']:
        raise ValueError('Consumed execution inputs changed')
    return receipt


def load_csv(path, native_times):
    with path.open() as stream:
        rows = list(csv.DictReader(stream, delimiter=';'))
    if len(rows) != 241 or [int(r['part']) for r in rows] != list(range(241)):
        raise ValueError('Complete consecutive 241-frame rigid trajectory required')
    fields = list(rows[0])
    values = np.array([[float(r[k]) for k in fields] for r in rows])
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite official rigid state')
    times = np.array([float(r['time [s]']) for r in rows])
    if times[0] != 0 or times[-1] < 12 or not (np.diff(times) > 0).all():
        raise ValueError('Full increasing 0..12 s rigid timeline required')
    if not np.allclose(times, native_times, rtol=1e-11, atol=1e-10):
        raise ValueError('Official rigid and native particle saved timelines differ')
    def columns(names):
        return np.array([[float(r[k]) for k in names] for r in rows])
    return dict(time=times,
                position=columns(['center.' + a + ' [m]' for a in 'xyz']),
                orientation_euler_rad=np.deg2rad(columns([a + ' [deg]' for a in ['roll', 'pitch', 'yaw']])),
                heave=columns(['heave [m]'])[:, 0])


def load(entry):
    native_path = Path(entry['native_receipt'])
    floating_path = Path(entry['floating_receipt'])
    native, floating = terminal(native_path), terminal(floating_path)
    if native['request']['family_id'] != 'F6' or native['request']['kind'] != 'qualification':
        raise ValueError('F6 native qualification source required')
    request = floating['request']
    if request['case_id'] != native['request']['case_id'] or request['source_solver_receipt'] != str(native_path):
        raise ValueError('Official FloatingInfo is bound to a different native case')
    if request['source_solver_receipt_sha256'] != sha256(native_path):
        raise ValueError('Terminal native receipt binding differs')
    actual_argv = native['command'][:]
    if actual_argv[1].startswith('-gpu:'):
        actual_argv.pop(1)
    if actual_argv != native['request']['command']:
        raise ValueError('Actual solver command differs from registered source')
    source = native_path.parent / 'solver_output'
    parts = source / 'RunPARTs.csv'
    window = native_window(parts)
    with parts.open() as stream:
        native_times = np.array([float(r['TimeStep [s]']) for r in csv.DictReader(stream, delimiter=';')
                                 if str(r['Part']).isdigit()])
    xml = Path(actual_argv[1]).with_suffix('.xml')
    if sha256(xml) != native['input_hashes_after_run'][str(xml)]:
        raise ValueError('Generated native XML changed')
    root = ET.parse(xml).getroot()
    body = root.find('./execution/particles/floating')
    constants = root.find('./execution/constants')
    parameters = {p.get('key'): p.get('value') for p in root.findall('./execution/parameters/parameter')}
    center = [float(body.find('center').get(a)) for a in 'xyz']
    inertia = [float(body.find('inertia').get(a)) for a in 'xyz']
    massbody = float(body.find('massbody').get('value'))
    fluid_mass = float(constants.find('massfluid').get('value')) * sum(int(p.get('count')) for p in root.findall('./execution/particles/fluid'))
    if massbody != 128 or not np.allclose(center, [2.4, 1.2, 1.08], rtol=0, atol=1e-12):
        raise ValueError('Frozen physical rigid mass/center differ')
    if not np.allclose(inertia, [8.53333, 8.53333, 13.6533], rtol=0, atol=1e-12) or abs(fluid_mass - 5120) > 1e-8:
        raise ValueError('Frozen generated inertia or initial fluid mass differ')
    if constants.find('data2d').get('value') != 'false':
        raise ValueError('Actual 3D required')
    path = floating_path.parent / request['required_output']
    state = load_csv(path, native_times)
    if not np.allclose(state['position'][0], center, rtol=0, atol=1e-10):
        raise ValueError('Official initial rigid center differs from generated source')
    state.update(path=str(path), sha256=sha256(path), case_id=request['case_id'],
                 frames=len(state['time']), time_first_s=float(state['time'][0]),
                 time_last_s=float(state['time'][-1]), massbody_kg=massbody, inertia=inertia)
    contract = dict(parameters=parameters,
                    constants={p.tag: dict(p.attrib) for p in constants if p.tag not in ['dp', 'h', 'b', 'massfluid', 'massbound']},
                    center=center, inertia=inertia, massbody_kg=massbody, initial_fluid_mass_kg=fluid_mass)
    evidence = dict(native_receipt=str(native_path), native_receipt_sha256=sha256(native_path),
                    floating_receipt=str(floating_path), floating_receipt_sha256=sha256(floating_path),
                    csv=str(path), csv_sha256=state['sha256'], xml=str(xml), xml_sha256=sha256(xml),
                    native_window=window, dp_m=float(constants.find('dp').get('value')),
                    native_eos_b_pa=float(constants.find('b').get('value')),
                    native_body_particle_count=int(body.get('count')),
                    native_body_masspart_kg=float(body.find('masspart').get('value')),
                    physical_and_parameter_contract=contract)
    return state, evidence


def run(config, output):
    if output.exists():
        raise FileExistsError('Preserve existing comparison')
    binding = json.loads(config.read_text())
    loaded = {role: load(binding[role]) for role in ['coarse', 'medium', 'fine']}
    contracts = [v[1]['physical_and_parameter_contract'] for v in loaded.values()]
    if any(c != contracts[0] for c in contracts[1:]):
        raise ValueError('Generated physical and integrator/save contracts differ')
    pairs = [('coarse', 'medium'), ('coarse', 'fine'), ('fine', 'medium')]
    comparisons = {candidate + '_vs_' + reference: compare(loaded[reference][0], loaded[candidate][0])
                   for reference, candidate in pairs}
    result = dict(schema='ds02.f6.official-floating-spatial-comparison.v1',
                  window_s=[0, 12], macro_budget_relative_rmse=BUDGET,
                  evidence={role: value[1] for role, value in loaded.items()}, comparisons=comparisons,
                  physical_contract_scope='Generated mass, center, inertia, constants and parameters; separate existing geometry lineage QA remains required',
                  orientation_units='Official roll/pitch/yaw degrees converted to radians',
                  scientific_operator='Unchanged ds_data02_f6_spatial_compare_v1.compare, including reference peak and 1e-12 floor',
                  q_n_status='not_assessed', production_approval='none', independent_case_count_increment=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.open('x').write(json.dumps(result, indent=2) + '\n')
    return {k: v['max_macro_relative_rmse'] for k, v in comparisons.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output)))
