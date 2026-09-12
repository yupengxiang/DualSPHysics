import json

import h5py
import numpy as np
import pytest

from scripts import f3_nopen_stage_score as score
from scripts.l1r_q2_mdbc_bridge import sha256


def source_fixture(tmp_path, plan_id, *, bump=False):
    step = .002 if plan_id == 'NP04' else .01
    times = score.target_grid(step)
    path = tmp_path / (plan_id + '.h5')
    p = np.broadcast_to(np.array([[.1, 0., .03], [.2, 0., .04]]), (len(times), 2, 3)).copy()
    if bump:
        p[1, 0, 0] += .04  # A peak strictly between two coarse 0.01 s outputs.
    with h5py.File(path, 'w') as h:
        h['time'] = times
        h['particle_id'] = np.array([41, 42])
        h['position'] = p
        h['velocity'] = np.zeros_like(p)
        h['mass'] = np.full((len(times), 2), .5)
        h['valid'] = np.ones((len(times), 2), dtype=bool)
        h['type'] = np.full((len(times), 2), 3)
    dt = .00001 if plan_id == 'NP03' else .00002
    return dict(plan_case_id=plan_id, case_id='case_' + plan_id, hdf5_path=path,
                entry=dict(output_interval_s=step),
                native_timestep=dict(dt_min_s=dt, dt_max_s=dt, total_steps=round(score.HORIZON / dt),
                                     last_time_s=score.HORIZON),
                audit=dict(frames=len(times), time_end_s=score.HORIZON,
                           particle_axis_count=2, initial_fluid_mass_kg=1.))


def cheap_operator(monkeypatch):
    # Isolate the grid/aggregation contract from the separately calibrated v2
    # operator. The real interpolation and HDF5 integrity checks still run.
    monkeypatch.setattr(score, 'observe_arrays', lambda p, v, m, initial: {'x': float(np.mean(p[:, 0]))})
    monkeypatch.setattr(score, 'compare', lambda a, b: {
        key: abs(a['x'] - b['x']) if key == 'tv' else 0. for key in score.METRICS
    })


def test_output_control_scores_every_dense_point_and_reuses_native_frames(tmp_path, monkeypatch):
    cheap_operator(monkeypatch)
    first = source_fixture(tmp_path, 'NP01')
    second = source_fixture(tmp_path, 'NP04', bump=True)
    with score.CachedSource(first) as a, score.CachedSource(second) as b:
        retained = []
        panel = score.score_pair(a, b, kind='output_interpolation', step_s=.002,
                                 threshold=.01, same_ids=True, retain_coarse=retained)
        assert panel['target_count'] == 4176 and len(retained) == 836
        assert panel['status'] == 'failed'
        assert panel['maxima']['tv'] == pytest.approx(.02)
        assert panel['peak_times_s']['tv'] == .002
        assert panel['rows'][0]['time_s'] == 0 and panel['rows'][-1]['time_s'] == 8.35
        assert max(row['tv'] for row in panel['rows'][::5]) == 0
        extra = panel['same_identity_interpolation_diagnostic']
        assert extra['maxima']['position_max_m'] == pytest.approx(.04)
        assert a.frame_loads == 836 and b.frame_loads == 4176
        assert len(a.cache) <= 2 and len(b.cache) <= 2


def test_cached_state_reuses_same_id_linear_interpolation_without_extrapolation(tmp_path):
    source = source_fixture(tmp_path, 'NP01')
    with h5py.File(source['hdf5_path'], 'r+') as h:
        h['position'][1, :, 0] += .02
    with score.CachedSource(source) as cached:
        p, v, mass, bracket = cached.state(.002)
        np.testing.assert_allclose(p[:, 0], [.104, .204])
        np.testing.assert_allclose(mass, [.5, .5])
        assert bracket == [0., .01]
        assert cached.frame_loads == 2
        for t in (.003, .004, .006):
            cached.state(t)
        assert cached.frame_loads == 2
        with pytest.raises(ValueError, match='outside'):
            cached.state(8.36)


@pytest.mark.parametrize('failure', ['invalid', 'mass', 'nonfinite', 'cadence'])
def test_false_passing_audit_cannot_hide_native_frame_failure(tmp_path, failure):
    source = source_fixture(tmp_path, 'NP01')
    with h5py.File(source['hdf5_path'], 'r+') as h:
        if failure == 'invalid':
            h['valid'][1, 1] = False
        elif failure == 'mass':
            h['mass'][1, 1] = .25
        elif failure == 'nonfinite':
            h['velocity'][1, 1, 0] = float('nan')
        else:
            h['time'][1] += .0001
    with pytest.raises(ValueError):
        with score.CachedSource(source) as cached:
            cached.state(.002)


def test_temporal_halving_requires_both_measured_ranges():
    first = dict(dt_min_s=.00002, dt_max_s=.00004)
    assert score._native_halving(first, dict(dt_min_s=.00001, dt_max_s=.00002))['status'] == 'passed'
    assert score._native_halving(first, dict(dt_min_s=.00001, dt_max_s=.00004))['status'] == 'failed'


def stage_fixture(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(score, 'LAB', tmp_path)
    monkeypatch.setattr(score, 'OUT', tmp_path)
    monkeypatch.setattr(score.qualification, 'case_id_for', lambda key: 'case_' + key)
    cheap_operator(monkeypatch)
    bound = tmp_path / 'calibration_fixture.json'
    bound.write_text('{"fixture": true}')
    monkeypatch.setattr(score, '_common_evidence', lambda bindings: score._bind(bindings, bound))
    sources = {key: source_fixture(tmp_path, key) for key in score.STAGES[stage]}
    for key in sources:
        (tmp_path / f'case_{key}-AUDIT.json').write_text('{"fixture_audit": true}')
    def source(key, bindings):
        score._bind(bindings, sources[key]['hdf5_path'])
        score._bind(bindings, tmp_path / f'case_{key}-AUDIT.json')
        return sources[key]
    monkeypatch.setattr(score, '_source', source)
    prerequisite_calls = []
    def prerequisite(stage_name):
        prerequisite_calls.append(stage_name)
        path = tmp_path / score.GATES[stage_name]
        path.write_text(json.dumps({'status': 'passed', 'stage': stage_name}))
        return {'evidence_sha256': {'calibration_fixture.json': sha256(bound)}}
    monkeypatch.setattr(score.qualification, 'verify_stage_gate', prerequisite)
    return sources, prerequisite_calls


@pytest.mark.parametrize('stage,panels,previous', [('nominal', 6, []), ('endpoints', 6, ['nominal']), ('domain', 1, ['endpoints'])])
def test_stage_runs_all_registered_comparisons_and_binds_separate_scores(tmp_path, monkeypatch, stage, panels, previous):
    sources, prerequisite_calls = stage_fixture(tmp_path, monkeypatch, stage)
    gate = score.run_stage(stage)
    assert gate['status'] == 'passed'
    assert prerequisite_calls == previous
    assert set(gate['case_ids']) == {row['case_id'] for row in sources.values()}
    assert gate['full_goal_complete'] is False and gate['material_qualified'] is False
    [report_name] = gate['scoring_evidence_paths']
    assert not report_name.endswith('-GATE.json')
    assert sha256(tmp_path / report_name) == gate['evidence_sha256'][report_name]
    report = json.loads((tmp_path / report_name).read_text())
    assert len(report['panels']) == panels and report['status'] == 'passed'
    assert report['case_ids'] == gate['case_ids']
    assert all(row['status'] == 'passed' for row in report['panels'])
    assert all(f'case_{key}-AUDIT.json' in gate['evidence_sha256'] for key in sources)
    if stage == 'nominal':
        assert {tuple(row['case_ids']) for row in report['panels'] if row['kind'] == 'spatial'} == {
            ('case_NP01', 'case_NP05'), ('case_NP01', 'case_NP06'), ('case_NP05', 'case_NP06')}
    if stage == 'domain':
        assert gate['schema'] == 'f3.nopen.domain_gate.v1'
        assert gate['production_resolution_m'] == .01
        assert gate['time_window_s'] == [0., 8.35] and gate['scoring_interval_s'] == .01
        assert 'Offline reconstruction' in gate['time_alignment']


def test_failure_invalidates_an_existing_pass_and_does_not_unlock_production(tmp_path, monkeypatch):
    stage_fixture(tmp_path, monkeypatch, 'domain')
    path = tmp_path / score.GATES['domain']
    path.write_text(json.dumps({'status': 'passed', 'production_resolution_m': .01}))
    def reject_source(*args):
        assert json.loads(path.read_text())['status'] == 'failed'
        raise ValueError('hard source gate rejected')
    monkeypatch.setattr(score, '_source', reject_source)
    gate = score.run_stage('domain')
    assert gate['status'] == 'failed' and 'production_resolution_m' not in gate
    assert json.loads(path.read_text()) == gate
    assert gate['errors'][0]['message'] == 'hard source gate rejected'


def test_changed_evidence_is_rejected_before_gate_publication(tmp_path, monkeypatch):
    sources, _ = stage_fixture(tmp_path, monkeypatch, 'domain')
    original = score.series_pair
    def mutate_source(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / 'calibration_fixture.json').write_text('{"fixture": "changed"}')
        return result
    monkeypatch.setattr(score, 'series_pair', mutate_source)
    gate = score.run_stage('domain')
    assert gate['status'] == 'failed'
    assert 'evidence changed during scoring' in gate['errors'][0]['message']


def test_score_source_always_calls_shared_hard_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(score.qualification, 'case_id_for', lambda key: 'case_' + key)
    monkeypatch.setattr(score.qualification, 'plan_entry', lambda key: {})
    called = []
    def reject(key):
        called.append(key)
        raise ValueError('hard source failed')
    monkeypatch.setattr(score.qualification, 'verified_source', reject)
    with pytest.raises(ValueError, match='hard source failed'):
        score._source('NP01', {})
    assert called == ['NP01']
