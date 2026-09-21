import json

import h5py
import numpy as np
import pytest

from scripts.core_material import F4_SCHEMA, SCHEMA, trace, trace_f4_resting_pool
from scripts.core_material_acceptance import (
    audit_material_h5,
    evaluate_material_summary,
    validate_checkpoint_manifest,
    validate_material_binding,
    validate_source_coverage,
)


def rows(a=.005, b=.005):
    return [{'source_id': 'left', 'initial_mass_kg': 1., 'unknown_fraction_max': a},
            {'source_id': 'right', 'initial_mass_kg': 1., 'unknown_fraction_max': b}]


def test_aggregate_below_limit_does_not_hide_bad_source():
    with pytest.raises(ValueError, match='exceeds'):
        validate_source_coverage(rows(.015625, .00390625), ['left', 'right'])


def test_every_declared_source_and_positive_mass_required():
    with pytest.raises(ValueError, match='missing'):
        validate_source_coverage(rows()[:1], ['left', 'right'])
    values = rows(); values[0]['initial_mass_kg'] = 0
    with pytest.raises(ValueError, match='positive'):
        validate_source_coverage(values, ['left', 'right'])


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -.1, True])
def test_invalid_unknown_rejected(value):
    with pytest.raises(ValueError):
        validate_source_coverage(rows(value), ['left', 'right'])


def test_closed_threshold_and_no_relaxation():
    assert validate_source_coverage(rows(.01, 0), ['left', 'right'])['all_sources_pass']
    with pytest.raises(ValueError, match='no greater'):
        validate_source_coverage(rows(), ['left', 'right'], .02)


def _reference(path):
    points = np.stack(np.meshgrid(*([np.linspace(-.025, .025, 7)] * 3), indexing='ij'), axis=-1).reshape(-1, 3)
    with h5py.File(path, 'w') as handle:
        handle['time'] = [0., .01, .02]
        handle['position'] = np.tile(points, (3, 1, 1))
        handle['velocity'] = np.tile([.01, 0., 0.], (3, len(points), 1))
        handle['valid'] = np.ones((3, len(points)), dtype=bool)
        handle['type'] = np.full((3, len(points)), 3, dtype=np.int32)


def _f4_reference(path):
    rng = np.random.default_rng(3)
    clouds = []
    for z in np.arange(0.0, 0.61, 0.05):
        directions = rng.normal(size=(40, 3))
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        clouds.append(np.array([.4, .2, z]) + .01 * directions)
    points = np.vstack(clouds)
    with h5py.File(path, 'w') as handle:
        handle['time'] = [0., .1, .2]
        handle['position'] = np.tile(points, (3, 1, 1))
        velocity = np.zeros((3, len(points), 3))
        velocity[:, :, 2] = -.2
        handle['velocity'] = velocity
        handle['valid'] = np.ones((3, len(points)), dtype=bool)
        handle['type'] = np.full((3, len(points)), 3, dtype=np.int32)


def test_binding_and_checkpoint_sidecar_are_cpu_read_only_contracts(tmp_path):
    source = tmp_path / 'reference.h5'
    output = tmp_path / 'trace.h5'
    _reference(source)
    result = trace(
        source, output, np.array([[-.001, 0., 0.], [.001, 0., 0.]]),
        np.empty((0, 3, 3)), stop_after=1,
    )
    binding = result['binding']
    binding_text = json.dumps(binding, sort_keys=True, separators=(',', ':'))
    checked = validate_material_binding(binding, expected_schema=SCHEMA, source=source)
    assert checked['source_sha256'] == result['binding']['source_sha256']
    receipt = validate_checkpoint_manifest(
        output,
        binding=binding_text,
        expected_schema='core.material.checkpoint.v1',
        expected_committed=1,
    )
    assert receipt['committed'] == 1
    assert receipt['state']['position'].shape == (2, 3)
    tampered = dict(binding)
    tampered['neighbours'] = 48
    with pytest.raises(ValueError, match='backend/neighbor'):
        validate_material_binding(tampered, expected_schema=SCHEMA, source=source)


def test_checkpoint_hash_and_state_shape_fail_closed(tmp_path):
    source = tmp_path / 'reference.h5'
    output = tmp_path / 'trace.h5'
    _reference(source)
    result = trace(
        source, output, np.array([[-.001, 0., 0.], [.001, 0., 0.]]),
        np.empty((0, 3, 3)), stop_after=1,
    )
    checkpoint = output.with_name(output.name + '.checkpoint.json')
    record = json.loads(checkpoint.read_text())
    record['state_sha256'] = '0' * 64
    checkpoint.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='state hash'):
        validate_checkpoint_manifest(output, binding=result['binding'])


def test_h5_audit_closes_terminal_frame_checkpoint_and_source_denominator(tmp_path):
    source = tmp_path / 'reference.h5'
    output = tmp_path / 'trace.h5'
    _reference(source)
    trace(
        source, output, np.array([[-.001, 0., 0.], [.001, 0., 0.]]),
        np.empty((0, 3, 3)), stop_after=1,
    )
    receipt = audit_material_h5(output, required_source_ids=['0', '1'], source=source)
    assert receipt['passed'] is True
    assert receipt['frame_count'] == 2
    assert receipt['mass_closed'] is True
    assert receipt['checkpoint']['committed'] == 1
    assert receipt['qualified_T2_macro'] is False


def test_h5_audit_reports_source_gate_failure_without_t2_claim(tmp_path):
    source = tmp_path / 'reference.h5'
    output = tmp_path / 'trace.h5'
    _reference(source)
    trace(
        source, output,
        np.array([[.2, 0., 0.], [.001, 0., 0.], [.002, 0., 0.]]),
        np.empty((0, 3, 3)), stop_after=1,
        weights=np.array([.98, .01, .01]), source_labels=np.array([0, 0, 1]),
    )
    receipt = audit_material_h5(output, required_source_ids=['0', '1'], source=source)
    assert receipt['passed'] is False
    assert receipt['source_coverage']['all_sources_pass'] is False
    assert receipt['T2_macro'] is False


def test_f4_h5_audit_uses_f4_binding_and_checkpoint_schema(tmp_path):
    source = tmp_path / 'f4-reference.h5'
    output = tmp_path / 'f4-trace.h5'
    _f4_reference(source)
    trace_f4_resting_pool(
        source, output, np.array([[.4, .2, .5]]), q=.5, dp_m=.0075,
        walls=np.empty((0, 3, 3)), stop_after=1,
    )
    receipt = audit_material_h5(output, required_source_ids=['1'], source=source)
    assert receipt['trace_schema'] == F4_SCHEMA
    assert receipt['checkpoint']['schema'] == 'core.material.f4.checkpoint.v1'
    assert receipt['source_coverage']['source_count'] == 1
    assert receipt['qualified_T2_macro'] is False


def test_f4_h5_audit_rejects_tampered_bound_membership_metadata(tmp_path):
    source = tmp_path / 'f4-reference.h5'
    output = tmp_path / 'f4-trace.h5'
    _f4_reference(source)
    trace_f4_resting_pool(
        source, output, np.array([[.4, .2, .5]]), q=.5, dp_m=.0075,
        walls=np.empty((0, 3, 3)), stop_after=1,
    )
    with h5py.File(output, 'r+') as handle:
        handle['source_membership'][0] = False
    with pytest.raises(ValueError, match='source_membership.*bound geometry'):
        audit_material_h5(output, required_source_ids=['1'], source=source)


def test_summary_evaluation_preserves_negative_source_and_t2_state():
    summary = {
        'qualification_claim': 'none',
        'T2_macro': False,
        'mass_closed': True,
        'by_source': [
            {'source': 0, 'initial_mass_fraction': .5, 'unknown_fraction_max': .015},
            {'source': 1, 'initial_mass_fraction': .5, 'unknown_fraction_max': .002},
        ],
    }
    result = evaluate_material_summary(summary, ['0', '1'])
    assert result['passed'] is False
    assert result['unknown_gate_pass'] is False
    assert result['source_coverage']['source_count'] == 2
    assert result['qualification_claim'] == 'none'
    assert result['T2_macro'] is False and result['T2_path'] is False
    with pytest.raises(ValueError, match='acceptance gate failed'):
        from scripts.core_material_acceptance import validate_material_summary
        validate_material_summary(summary, ['0', '1'])


def test_summary_evaluation_requires_complete_f4_window_without_granting_t2():
    summary = {
        'qualification_claim': 'none',
        'mass_closed': True,
        'event_window_complete': False,
        'event_window_status': 'right_censored_or_unresolved',
        'by_source': [{'source': 1, 'initial_mass_fraction': 1., 'unknown_fraction_max': 0.}],
    }
    result = evaluate_material_summary(summary, ['1'], require_complete_window=True)
    assert result['passed'] is False
    assert result['event_window_pass'] is False
    assert result['T2_macro'] is False
