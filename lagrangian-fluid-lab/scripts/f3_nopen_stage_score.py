"""Substantive, full-window v2 scores for the registered native-NoPen matrix.

This command scores existing sources; it never prepares or launches a solver.
The 0.002 s output control uses all 4,176 target times, including points between
coarse outputs. Native timestamps may exceed 8.35 slightly; the scoring grid
ends at 8.35 and is not an extrapolated control or a native rollout schedule.
Passing these gates does not qualify material paths, models or the full goal.
"""

import argparse
from collections import OrderedDict
from contextlib import ExitStack
import fcntl
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from scripts import f3_nopen_qualification as qualification
from scripts.f3_observation_v2 import observe_arrays, compare, U
from scripts.f3_reference_score import state as interpolated_state
from scripts.f3_timestep_evidence import evidence as timestep_evidence
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now

RECIPE = 'F3_CELL3_NS_visco1_native_nopen'
HORIZON = 8.35
METRICS = ('tv', 'com_l2_over_length', 'q90_over_length',
           'mean_velocity_over_U', 'energy_difference',
           'common_support_velocity_over_U', 'unmatched_support_mass')
STAGES = {'nominal': tuple(f'NP{i:02}' for i in range(1, 7)),
          'endpoints': tuple(f'NP{i:02}' for i in range(7, 13)),
          'domain': ('NP13', 'NP14')}
GATES = {'nominal': 'F3-NOPEN-NOMINAL-GATE.json',
         'endpoints': 'F3-NOPEN-ENDPOINT-GATE.json',
         'domain': 'F3-NOPEN-DOMAIN-GATE.json'}
TIME_ALIGNMENT = ('Offline reconstruction of the numerical reference by linear interpolation '
                  'of unchanged native particle identities and masses onto fixed 0..8.35 s targets; '
                  'the right native bracket may be later than the target. No control extension '
                  'or omitted final interval. This is reference reconstruction, not permission '
                  'for a predictive model to read future fluid state.')


def _read(path):
    return json.loads(Path(path).read_text())


def _relative(path):
    return str(Path(path).resolve().relative_to(LAB.resolve()))


def _path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError('evidence path must be LAB-relative')
    path = (LAB / relative).resolve()
    path.relative_to(LAB.resolve())
    return path


def _bind(bindings, path, expected=None):
    digest = sha256(Path(path))
    if expected is not None and digest != expected:
        raise ValueError('changed evidence: ' + _relative(path))
    bindings[_relative(path)] = digest
    return digest


def _verify_bindings(bindings):
    for path, digest in bindings.items():
        if sha256(_path(path)) != digest:
            raise ValueError('evidence changed during scoring: ' + path)


def target_grid(step_s):
    if step_s not in (.01, .002):
        raise ValueError('only the registered full-window scoring grids are allowed')
    # Coarse targets are an exact subset of the dense grid, avoiding two
    # different floating-point constructions of otherwise identical times.
    dense = np.arange(4176, dtype=float) * .002
    dense[-1] = HORIZON
    return dense if step_s == .002 else dense[::5]


def _common_evidence(bindings):
    for name in ('scripts/f3_nopen_stage_score.py', 'scripts/f3_nopen_qualification.py',
                 'scripts/f3_reference_score.py', 'scripts/f3_observation_v2.py',
                 'scripts/f3_timestep_evidence.py', 'scripts/l1r_branch_runner.py',
                 'scripts/l1r_q2_mdbc_bridge.py'):
        _bind(bindings, LAB / name)
    plan = OUT / 'F3-NATIVE-NOPEN-QUALIFICATION-PLAN.json'
    _bind(bindings, plan)
    plan_data = _read(plan)
    if plan_data.get('recipe_id') != RECIPE:
        raise ValueError('qualification plan names another recipe')
    for item in plan_data['source_plan_evidence']:
        _bind(bindings, _path(item['path']), item['sha256'])
    native_design = OUT / 'F3-NATIVE-NOPEN-DESIGN.json'
    _bind(bindings, native_design)
    for name, digest in _read(native_design)['native_source_hashes'].items():
        _bind(bindings, _path(name), digest)
    design = OUT / 'F3-V2-OBSERVATION-DESIGN.json'
    _bind(bindings, design)
    calibration = LAB / 'diagnostics/f3-audit/v2-calibration.json'
    _bind(bindings, calibration)
    c = _read(calibration)
    if (c.get('calibrated') is not True
            or c.get('operator_sha256') != bindings['scripts/f3_observation_v2.py']
            or c.get('design_sha256') != bindings[_relative(design)]):
        raise ValueError('v2 calibration or its frozen operator/design binding failed')


def _source(plan_id, bindings):
    """Extend the shared read-only hard source guard with scoring inputs."""
    name = qualification.case_id_for(plan_id)
    entry = qualification.plan_entry(plan_id)
    record, audit, solver = qualification.verified_source(plan_id)
    for suffix in ('PREPARED', 'AUDIT', 'SOLVER', 'INPUT-PREFLIGHT'):
        _bind(bindings, OUT / f'{name}-{suffix}.json')
    # verified_source has just hashed the HDF5 and every prepared input asset.
    # Reuse those verified digests now; rehash all bindings before publishing.
    bindings[_relative(_path(audit['hdf5']))] = audit['hdf5_sha256']
    prefix = _path(record['generated_prefix'])
    for filename, digest in record['input_assets'].items():
        bindings[_relative(prefix.parent / filename)] = digest
    for field, filename in (('protocol_sha256', 'F3-CELL3-PROTOCOL.json'),
                            ('observation_design_sha256', 'F3-V2-OBSERVATION-DESIGN.json'),
                            ('boundary_bridge_sha256', 'F3-NATIVE-NOPEN-DESIGN.json')):
        if field in record:
            _bind(bindings, OUT / filename, record[field])
    if plan_id != 'NP01':
        stage_path = _path(record['qualification_stage_path'])
        _bind(bindings, stage_path, record['qualification_stage_sha256'])
        stage = _read(stage_path)
        if stage.get('recipe_id') != RECIPE or stage.get('schema') != 'f3.nopen.execution_stage.v1':
            raise ValueError('source execution registration belongs to another recipe')
        _bind(bindings, OUT / 'F3-NATIVE-NOPEN-QUALIFICATION-PLAN.json', record['conditional_plan_sha256'])
        for item in stage['evidence']:
            _bind(bindings, _path(item['path']), item['sha256'])
        initial_source = stage['initial_sources'][str(entry['dp_m'])]
        for filename, digest in initial_source['assets'].items():
            if not filename.endswith('.xml') and filename != 'CaseSloshingAccData.csv':
                if record['input_assets'].get(filename) != digest:
                    raise ValueError('native initial particles/normals changed from the registered dp source')
    preflight = _read(OUT / f'{name}-INPUT-PREFLIGHT.json')
    drive = prefix.parent / 'CaseSloshingAccData.csv'
    if (preflight.get('status') != 'passed'
            or _path(preflight['asset']['path']) != drive.resolve()
            or preflight['asset']['sha256'] != record['drive_sha256']):
        raise ValueError('current control differs from passed input preflight')
    _bind(bindings, drive, preflight['asset']['sha256'])
    nominal_path = _path(preflight['source']['path'])
    _bind(bindings, nominal_path, preflight['source']['sha256'])
    nominal = np.loadtxt(nominal_path, delimiter=';', comments='#')
    actual = np.loadtxt(drive, delimiter=';', comments='#')
    if (nominal.ndim != 2 or nominal.shape[1] != 7 or actual.shape != nominal.shape
            or not np.isfinite(nominal).all() or not np.isfinite(actual).all()
            or np.any(np.diff(actual[:, 0]) <= 0)
            or actual[0, 0] != 0 or actual[-1, 0] != HORIZON):
        raise ValueError('control must be finite and cover exactly the full registered window')
    expected = nominal.copy()
    gravity = np.array([0., 0., -9.81])
    expected[:, 1:4] = gravity + entry['amplitude'] * (nominal[:, 1:4] - gravity)
    expected[:, 4:7] *= entry['amplitude']
    if not np.allclose(actual, expected, rtol=0, atol=1e-12):
        raise ValueError('control does not implement the planned gravity-preserving amplitude')
    native_reader = preflight['native_reader']
    if (native_reader['first_time_s'] != 0 or native_reader['last_time_s'] != HORIZON
            or native_reader['rows'] != len(actual)):
        raise ValueError('native input-parser coverage/count differs from actual control')

    for xml in (prefix.with_suffix('.xml'), prefix.with_name(prefix.name + '_Def.xml')):
        root = ET.parse(xml).getroot()
        nodes = root.findall('./execution/parameters/parameter')
        parameters = {n.get('key'): n.get('value') for n in nodes}
        if len(parameters) != len(nodes):
            raise ValueError('duplicate XML execution parameter')
        fixed = dict(Boundary=2, SlipMode=2, NoPenetration=1, Visco=.05,
                     ViscoBoundFactor=1, Shifting=0, TimeMax=HORIZON,
                     TimeOut=entry['output_interval_s'], CoefDtMin=entry['coef_dt_min'])
        if any(float(parameters.get(k, 'nan')) != v for k, v in fixed.items()):
            raise ValueError('XML recipe or output/time parameters differ from plan')
        cfl = root.findall('.//cflnumber')
        if not cfl or any(float(n.get('value')) != entry['cfl_number'] for n in cfl):
            raise ValueError('XML CFL differs from registered refinement')
        definition = root.find('./casedef/geometry/definition')
        if definition is None or float(definition.get('dp')) != entry['dp_m']:
            raise ValueError('XML resolution differs from planned cell')

    attempt = Path(solver['attempt_directory'])
    _bind(bindings, Path(solver['command'][0]), solver['solver_sha256'])
    log = attempt / 'Run.out'
    _bind(bindings, log)
    text = log.read_text()
    for field, value in (('Dp', entry['dp_m']), ('CFLnumber', entry['cfl_number']), ('TimeMax', HORIZON)):
        found = re.search(r'^' + field + r'=([^\s]+)', text, re.MULTILINE)
        if not found or float(found[1]) != value:
            raise ValueError('effective native ' + field + ' differs from plan')
    native = timestep_evidence(name)
    _bind(bindings, _path(native['csv_path']), native['csv_sha256'])
    if (not all(math.isfinite(native[k]) and native[k] > 0 for k in ('dt_min_s', 'dt_max_s'))
            or native['dt_min_s'] > native['dt_max_s'] or native['total_steps'] <= 0):
        raise ValueError('missing or invalid measured native timestep evidence')
    return dict(plan_case_id=plan_id, case_id=name, record=record, audit=audit,
                native_timestep=native, hdf5_path=_path(audit['hdf5']), entry=entry)


class _Dataset:
    def __init__(self, source, key):
        self.source, self.key = source, key

    def __getitem__(self, index):
        return self.source.frame(int(index))[self.key]


class CachedSource:
    """HDF5 facade for the unchanged same-ID interpolation implementation.

    Two native frames suffice for monotone target queries. Every loaded frame
    is checked before the interpolation helper can apply a validity mask.
    """

    def __init__(self, source):
        self.source = source
        self.h5 = h5py.File(source['hdf5_path'], 'r')
        self.cache = OrderedDict()
        self.frame_loads = 0
        try:
            self.times = self.h5['time'][:]
            self.ids = self.h5['particle_id'][:]
            audit, entry = source['audit'], source['entry']
            if (self.times.ndim != 1 or len(self.times) != audit['frames']
                    or len(self.times) != round(HORIZON / entry['output_interval_s']) + 1
                    or not np.isfinite(self.times).all() or np.any(np.diff(self.times) <= 0)
                    or self.times[0] != 0 or self.times[-1] != audit['time_end_s']
                    or self.times[-1] < HORIZON):
                raise ValueError('HDF5 does not provide the complete audited native time axis')
            if (self.ids.ndim != 1 or len(self.ids) != audit['particle_axis_count']
                    or len(np.unique(self.ids)) != len(self.ids)):
                raise ValueError('HDF5 identity axis differs from the complete source audit')
            slack = source['native_timestep']['dt_max_s'] * 1.001 + 1e-9
            expected_times = target_grid(entry['output_interval_s'])
            if np.any(np.abs(self.times - expected_times) > slack):
                raise ValueError('native outputs are missing or displaced beyond one integration step')
            if abs(source['native_timestep']['last_time_s'] - self.times[-1]) > slack:
                raise ValueError('native timestep log does not cover the same full window')
            self.mass = self.h5['mass'][0].astype(float)
            if (not np.isfinite(self.mass).all() or np.any(self.mass <= 0)
                    or not np.isclose(self.mass.sum(), audit['initial_fluid_mass_kg'], rtol=1e-12, atol=1e-12)):
                raise ValueError('initial mass denominator changed')
            self.initial_mass = float(self.mass.sum())
            self.frame(0)
        except BaseException:
            self.h5.close()
            raise

    def frame(self, index):
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        if not 0 <= index < len(self.times):
            raise ValueError('native frame index outside the source')
        h = self.h5
        if not h['valid'][index].all() or not (h['type'][index] == 3).all():
            raise ValueError('source contains an invalid/nonfluid identity; filtering is forbidden')
        p, v, m = h['position'][index], h['velocity'][index], h['mass'][index].astype(float)
        if (p.shape != (len(self.ids), 3) or v.shape != p.shape
                or not np.isfinite(p).all() or not np.isfinite(v).all()
                or not np.array_equal(m, self.mass)):
            raise ValueError('native state is nonfinite or its identity mass changed')
        row = dict(position=p, velocity=v, mass=m, valid=np.ones(len(self.ids), dtype=bool))
        self.cache[index] = row
        self.frame_loads += 1
        while len(self.cache) > 2:
            self.cache.popitem(last=False)
        return row

    def __getitem__(self, key):
        return self.times if key == 'time' else _Dataset(self, key)

    def state(self, time_s):
        return interpolated_state(self, float(time_s))

    def close(self):
        self.h5.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _row(time_s, first, second):
    metrics = compare(first, second)
    if set(metrics) != set(METRICS) or not all(math.isfinite(v) for v in metrics.values()):
        raise ValueError('v2 comparison returned incomplete or nonfinite metrics')
    return dict(time_s=float(time_s), **{k: float(metrics[k]) for k in METRICS})


def _panel(kind, names, rows, threshold, **extra):
    maxima = {k: max(r[k] for r in rows) for k in METRICS}
    return dict(kind=kind, case_ids=names, time_window_s=[0., HORIZON],
                target_count=len(rows), threshold=threshold, maxima=maxima,
                peak_times_s={k: max(rows, key=lambda r: r[k])['time_s'] for k in METRICS},
                status='passed' if all(v <= threshold for v in maxima.values()) else 'failed',
                rows=rows, **extra)


def _same_initial(first, second):
    if not np.array_equal(first.ids, second.ids) or not np.array_equal(first.mass, second.mass):
        raise ValueError('same-ID control comparison has different identities/order/masses')
    a0, b0 = first.state(0.), second.state(0.)
    if not np.array_equal(a0[0], b0[0]) or not np.array_equal(a0[1], b0[1]):
        raise ValueError('control comparison changed the initial particle state')


def score_pair(first, second, *, kind, step_s, threshold, same_ids=False, retain_coarse=None):
    rows, diagnostics = [], []
    names = [first.source['case_id'], second.source['case_id']]
    if same_ids:
        _same_initial(first, second)
    for index, t in enumerate(target_grid(step_s)):
        p, v, m, bracket_a = first.state(t)
        q, w, n, bracket_b = second.state(t)
        a = observe_arrays(p, v, m, first.initial_mass)
        b = observe_arrays(q, w, n, second.initial_mass)
        rows.append(_row(t, a, b))
        if retain_coarse is not None and (step_s == .01 or index % 5 == 0):
            retain_coarse.append(a)
        if same_ids:
            dx, dv = np.linalg.norm(p - q, axis=1), np.linalg.norm(v - w, axis=1)
            diagnostics.append(dict(time_s=float(t), position_max_m=float(dx.max()),
                position_mass_rms_m=float(np.sqrt(np.sum(m * dx**2) / first.initial_mass)),
                velocity_max_mps=float(dv.max()),
                velocity_mass_rms_mps=float(np.sqrt(np.sum(m * dv**2) / first.initial_mass)),
                first_native_bracket_s=bracket_a, second_native_bracket_s=bracket_b))
        if index % 500 == 0:
            print(kind, names, index, '/', len(target_grid(step_s)), flush=True)
    extra = dict(grid_step_s=step_s, time_alignment='same-ID native linear interpolation at fixed requested times; no extrapolation')
    if diagnostics:
        keys = ('position_max_m', 'position_mass_rms_m', 'velocity_max_mps', 'velocity_mass_rms_mps')
        extra['same_identity_interpolation_diagnostic'] = dict(
            scope='additional diagnostics; no pointwise or material-path qualification threshold',
            maxima={k: max(r[k] for r in diagnostics) for k in keys}, rows=diagnostics)
    return _panel(kind, names, rows, threshold, **extra)


def observations(source):
    result = []
    for t in target_grid(.01):
        p, v, m, _ = source.state(t)
        result.append(observe_arrays(p, v, m, source.initial_mass))
    return result


def series_pair(first_name, first, second_name, second, *, kind, threshold):
    if len(first) != 836 or len(second) != 836:
        raise ValueError('coarse scoring series is incomplete')
    return _panel(kind, [first_name, second_name],
                  [_row(t, a, b) for t, a, b in zip(target_grid(.01), first, second)], threshold,
                  grid_step_s=.01)


def _native_halving(first, second):
    ratios = {key: second[key] / first[key] for key in ('dt_min_s', 'dt_max_s')}
    passed = all(np.isclose(value, .5, rtol=1e-10, atol=0) for value in ratios.values())
    return dict(status='passed' if passed else 'failed', actual_ratios=ratios,
                expected_ratio=.5, relative_tolerance=1e-10,
                first=first, second=second,
                interpretation='measured refinement prerequisite; not an accuracy result by itself')


def _score(stage, report, bindings):
    _common_evidence(bindings)
    previous = {'endpoints': 'nominal', 'domain': 'endpoints'}.get(stage)
    if previous:
        prerequisite = qualification.verify_stage_gate(previous)
        bindings.update(prerequisite['evidence_sha256'])
        _bind(bindings, OUT / GATES[previous])
    sources = {key: _source(key, bindings) for key in STAGES[stage]}
    report['sources'] = [{k: s[k] for k in ('plan_case_id', 'case_id', 'entry', 'native_timestep')}
                         for s in sources.values()]
    panels = report['panels']
    with ExitStack() as stack:
        handles = {key: stack.enter_context(CachedSource(value)) for key, value in sources.items()}
        series = {}
        if stage == 'nominal':
            _same_initial(handles['NP01'], handles['NP02'])
            _same_initial(handles['NP01'], handles['NP03'])
            series['NP01'] = []
            panels.append(score_pair(handles['NP01'], handles['NP04'], kind='output_interpolation',
                                     step_s=.002, threshold=.01, same_ids=True,
                                     retain_coarse=series['NP01']))
            zero = observations(handles['NP02'])
            panels.append(series_pair(sources['NP02']['case_id'], zero,
                                      sources['NP02']['case_id'], [zero[0]] * len(zero),
                                      kind='zero_drive_vs_initial', threshold=.01))
            time = observations(handles['NP03'])
            temporal = series_pair(sources['NP01']['case_id'], series['NP01'],
                                   sources['NP03']['case_id'], time, kind='temporal', threshold=.01)
            temporal['native_halving'] = _native_halving(sources['NP01']['native_timestep'],
                                                        sources['NP03']['native_timestep'])
            if temporal['native_halving']['status'] != 'passed':
                temporal['status'] = 'failed'
            panels.append(temporal)
            groups = [('NP01', 'NP05', 'NP06')]
        elif stage == 'endpoints':
            groups = [('NP07', 'NP08', 'NP09'), ('NP10', 'NP11', 'NP12')]
        else:
            groups = [('NP13', 'NP14')]
        for group in groups:
            for key in group:
                if key not in series:
                    series[key] = observations(handles[key])
            for a, b in combinations(group, 2):
                panels.append(series_pair(sources[a]['case_id'], series[a], sources[b]['case_id'], series[b],
                                          kind='spatial', threshold=.05))
        report['native_frame_loads'] = {sources[k]['case_id']: h.frame_loads for k, h in handles.items()}
    _verify_bindings(bindings)
    report['status'] = 'passed' if all(p['status'] == 'passed' for p in panels) else 'failed'


def run_stage(stage):
    """Publish immutable scores, then a gate binding their exact contents."""
    if stage not in STAGES:
        raise ValueError('unknown qualification scoring stage')
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f'F3-NOPEN-{stage.upper()}-SCORING.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gate = dict(schema='f3.nopen.domain_gate.v1' if stage == 'domain' else 'f3.nopen.stage_gate.v1',
                    stage=stage, status='failed', recipe_id=RECIPE, case_ids=[],
                    reason='evaluation_in_progress_or_interrupted', evidence_sha256={},
                    scoring_evidence_paths=[], full_goal_complete=False, material_qualified=False)
        # Invalidate before reading any prerequisite or source; an exception or
        # process interruption cannot leave this stage's previous pass usable.
        atomic_json(OUT / GATES[stage], gate)
        report = dict(schema='f3.nopen.stage_scores.v1', stage=stage, recipe_id=RECIPE,
                      created_at_utc=utc_now(), status='failed', case_ids=[], plan_case_ids=list(STAGES[stage]),
                      time_window_s=[0., HORIZON], time_alignment=TIME_ALIGNMENT, panels=[], errors=[],
                      scope='fixed-scale v2 numerical comparisons; no material, learned-model or full-goal completion claim')
        bindings = {}
        try:
            report['case_ids'] = [qualification.case_id_for(i) for i in STAGES[stage]]
            _score(stage, report, bindings)
        except Exception as error:
            report['errors'].append(dict(type=type(error).__name__, message=str(error)))
            report['status'] = 'failed'
        report['evidence_sha256'] = dict(bindings)
        data = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
        digest = hashlib.sha256(data).hexdigest()
        score_path = OUT / f'F3-NOPEN-{stage.upper()}-SCORES-{digest}.json'
        if score_path.exists() and score_path.read_bytes() != data:
            raise ValueError('content-addressed scoring report collision')
        if not score_path.exists():
            temporary = score_path.with_suffix('.partial')
            temporary.write_bytes(data)
            temporary.replace(score_path)
        bindings[_relative(score_path)] = digest
        gate.update(status=report['status'], reason='substantive_scoring_complete' if report['status'] == 'passed' else 'substantive_scoring_failed',
                    case_ids=report['case_ids'], evidence_sha256=bindings,
                    scoring_evidence_paths=[_relative(score_path)], errors=report['errors'])
        if stage == 'domain' and report['status'] == 'passed':
            gate.update(production_resolution_m=.01, time_window_s=[0., HORIZON],
                        scoring_interval_s=.01, time_alignment=TIME_ALIGNMENT,
                        control_domain=[.9, 1.1], independent_internal_amplitude=.97,
                        coordinate_frame='fixed tank computational coordinates',
                        qualification_scope='registered fixed-scale v2 numerical reference; no pointwise physical truth or material-path qualification')
        atomic_json(OUT / GATES[stage], gate)
        return gate


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True, choices=tuple(STAGES))
    args = parser.parse_args(argv)
    gate = run_stage(args.stage)
    print(json.dumps({k: gate[k] for k in ('stage', 'status', 'scoring_evidence_paths', 'errors')}, indent=2))
    return 0 if gate['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
