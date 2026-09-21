from copy import deepcopy
import json

import h5py
import numpy as np
import pytest

from scripts.core_material import F4_SCHEMA, SCHEMA, trace, trace_f4_resting_pool
from scripts.core_material_acceptance import (
    audit_material_h5,
    evaluate_material_summary,
    evaluate_material_output_json,
    validate_checkpoint_manifest,
    validate_material_binding,
    validate_source_coverage,
)
from scripts.core_material_output_contract_v1 import MASS_CLOSURE_TOLERANCE_KG


def rows(a=.005, b=.005):
    return [{'source_id': 'left', 'initial_mass_kg': 1., 'unknown_fraction_max': a},
            {'source_id': 'right', 'initial_mass_kg': 1., 'unknown_fraction_max': b}]


JSON_SOURCE_IDS = ['source-a', 'source-b']


def _json_material_output(*, censor_type='right'):
    if censor_type == 'right':
        censor = {
            'type': 'right', 'fraction': .1,
            'policy': 'right_censored_mass_remains_in_denominator',
            'counts_as_acceptance': False,
        }
    else:
        censor = {
            'type': 'none', 'fraction': 0., 'policy': 'no_censoring',
            'counts_as_acceptance': False,
        }

    def event(name):
        return {
            'definition': f'synthetic {name}',
            'denominator_policy': 'all_initial_mass',
            'cdf': {
                'time_s': [0., 1., 2.],
                'lower': [0., .2, .5],
                'upper': [0., .25, .6],
                'denominator_policy': 'all_initial_mass',
            },
            'censor': deepcopy(censor),
        }

    return {
        'schema': 'core.material.output_contract.v1',
        'family': 'F3',
        'case_id': 'json-material-case',
        'diagnostic_only': True,
        'qualification_claim': 'none',
        'qualification_credit': 0,
        'T2_macro': False,
        'T2_path': False,
        'mass': {
            'initial_mass_kg': 100.,
            'closure_tolerance_kg': MASS_CLOSURE_TOLERANCE_KG,
            'denominator_policy': 'all_initial_mass',
            'source': {'mass_kg': 40., 'fraction': .4},
            'destination': {'mass_kg': 59.5, 'fraction': .595},
            'unknown': {'mass_kg': .5, 'fraction': .005},
        },
        'transfer_matrix': {
            'row_labels': ['source', 'destination', 'unknown'],
            'column_labels': ['source', 'destination', 'unknown'],
            'mass_kg': [[35., 14.5, .5], [5., 45., 0.], [0., 0., 0.]],
        },
        'events': {
            'first_passage': event('first passage'),
            'return': event('return'),
            'residence': event('residence'),
        },
        'unknown_bound': {
            'denominator_policy': 'all_initial_mass',
            'observed_fraction': .005,
            'worst_case_fraction': .005,
            'limit': .01,
            'includes_right_censored_mass': True,
        },
        'path_error': {
            'denominator_policy': 'all_initial_mass',
            'coverage_policy': 'common_reliable_mass_over_all_initial_mass',
            'maximum_abs_error_m': .004,
            'tolerance_m': .01,
            'common_reliable_mass_coverage': .98,
            'minimum_common_reliable_mass_coverage': .95,
        },
        'family_specific': {
            'source_definition': {'axis': 0, 'boundary': 0.},
            'trace_schema': 'core.material.f3.synthetic.trace.v1',
            'native_interval_s': .002,
            'full_window_s': 8.35,
        },
        'source_coverage': {
            'schema': 'core.material.source_summary.v1',
            'family': 'F3',
            'case_id': 'json-material-case',
            'denominator_policy': 'all_initial_mass',
            'required_source_ids': list(JSON_SOURCE_IDS),
            'rows': [
                {'source_id': 'source-a', 'initial_mass_kg': 50., 'unknown_fraction_max': .005},
                {'source_id': 'source-b', 'initial_mass_kg': 50., 'unknown_fraction_max': .005},
            ],
        },
    }


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


def test_json_output_acceptance_is_diagnostic_and_read_only():
    payload = _json_material_output()
    before = deepcopy(payload)
    result = evaluate_material_output_json(
        payload,
        required_source_ids=JSON_SOURCE_IDS,
        expected_family='F3',
        expected_case_id='json-material-case',
    )

    assert result['schema'] == 'core.material.acceptance.v1'
    assert result['input_schema'] == 'core.material.output_contract.v1'
    assert result['status'] == 'diagnostic_only'
    assert result['passed'] is True
    assert result['qualification_claim'] == 'none'
    assert result['qualification_credit'] == 0
    assert result['T2_macro'] is False and result['T2_path'] is False
    assert result['qualified_T2_macro'] is False
    assert result['execution_constraints']['hdf5_opened'] is False
    assert result['execution_constraints']['registry_written'] is False
    assert payload == before


def test_json_output_acceptance_requires_external_registered_sources():
    payload = _json_material_output()
    with pytest.raises(ValueError, match='required_source_ids'):
        evaluate_material_output_json(payload, required_source_ids=None)

    payload['source_coverage']['required_source_ids'] = ['merged']
    with pytest.raises(ValueError, match='required_source_ids'):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)

    payload = _json_material_output()
    payload['source_coverage']['rows'] = [
        {'source_id': 'merged', 'initial_mass_kg': 100., 'unknown_fraction_max': .005},
    ]
    with pytest.raises(ValueError, match='duplicate or undeclared material source'):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)


def test_json_output_acceptance_rejects_old_bridge_shape_and_missing_coverage():
    with pytest.raises(ValueError, match='schema'):
        evaluate_material_output_json(
            {'by_source': [], 'mass_closed': True},
            required_source_ids=JSON_SOURCE_IDS,
        )

    payload = _json_material_output()
    del payload['source_coverage']
    with pytest.raises(ValueError, match='source_coverage'):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)


def test_json_output_acceptance_checks_family_and_case_identity():
    payload = _json_material_output()
    with pytest.raises(ValueError, match='family'):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS, expected_family='F4')
    with pytest.raises(ValueError, match='case_id'):
        evaluate_material_output_json(
            payload, required_source_ids=JSON_SOURCE_IDS, expected_case_id='other-case'
        )


def test_json_output_right_censor_never_counts_as_complete_window_acceptance():
    result = evaluate_material_output_json(
        _json_material_output(censor_type='right'),
        required_source_ids=JSON_SOURCE_IDS,
        require_complete_window=True,
    )
    assert result['passed'] is False
    assert result['event_window_pass'] is False
    assert 'complete_event_window' in result['failure_reasons']
    assert result['qualification_credit'] == 0


def test_json_output_no_censor_can_pass_complete_window_gate():
    result = evaluate_material_output_json(
        _json_material_output(censor_type='none'),
        required_source_ids=JSON_SOURCE_IDS,
        require_complete_window=True,
        cdf_sup_abs_difference=.01,
        cdf_limit=.02,
    )
    assert result['passed'] is True
    assert result['event_window_pass'] is True
    assert result['cdf_gate_pass'] is True


def test_json_output_cdf_failure_is_preserved_as_diagnostic_negative():
    result = evaluate_material_output_json(
        _json_material_output(censor_type='none'),
        required_source_ids=JSON_SOURCE_IDS,
        cdf_sup_abs_difference=.03,
        cdf_limit=.02,
    )
    assert result['passed'] is False
    assert result['cdf_gate_pass'] is False
    assert 'cdf_comparison' in result['failure_reasons']
    assert result['execution_constraints']['qualification_credit_registered'] == 0


def test_json_output_per_source_unknown_failure_does_not_renormalize_survivors():
    payload = _json_material_output(censor_type='none')
    payload['source_coverage']['rows'][0]['unknown_fraction_max'] = .02
    result = evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)

    assert result['passed'] is False
    assert result['source_coverage']['all_sources_pass'] is False
    assert result['gates']['unknown_bound'] is False
    assert result['qualification_claim'] == 'none'
    assert result['T2_path'] is False


@pytest.mark.parametrize(
    ('field', 'value'),
    [('qualification_claim', 'T2_macro'), ('qualification_credit', 1), ('T2_macro', True)],
)
def test_json_output_claim_or_credit_mutations_fail_closed(field, value):
    payload = _json_material_output()
    payload[field] = value
    with pytest.raises(ValueError):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)


def test_json_output_source_denominator_mismatch_is_structural_error():
    payload = _json_material_output()
    payload['source_coverage']['rows'][0]['initial_mass_kg'] = 49.
    with pytest.raises(ValueError, match='denominator'):
        evaluate_material_output_json(payload, required_source_ids=JSON_SOURCE_IDS)
