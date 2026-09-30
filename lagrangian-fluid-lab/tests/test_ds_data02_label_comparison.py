import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_native_labels import materialize
from ds_data02_label_comparison import compare, _label_binding


def labels(tmp_path, name, times, x):
    source, output = tmp_path/(name+'.h5'), tmp_path/(name+'-labels.h5')
    with h5py.File(source, 'w') as h:
        h.attrs['coordinate_frame'] = 'tank'
        fields = dict(time=times, particle_id=[1], particle_zone=[3],
                      position=np.array([[[v, .5, .5]] for v in x]),
                      valid=np.ones((len(times), 1)), mass=np.full((len(times), 1), 2.),
                      type=np.full((len(times), 1), 3))
        for key, data in fields.items():
            h.create_dataset(key, data=data)
    left = dict(id='left', bounds=[[0, 1], [0, 1], [0, 1]])
    right = dict(id='right', bounds=[[1, 2], [0, 1], [0, 1]])
    config = dict(frame_kind='fixed_solver_frame', coordinate_frame='tank',
                  source_regions=[left], destination_regions=[left, right],
                  events=[dict(id='portal', axis=0, value=1., aperture_bounds=[[0, 1], [0, 1]])])
    materialize(source, output, config)
    return output


def test_dense_saves_reveal_hidden_recrossing_even_when_final_destination_and_net_flux_match(tmp_path):
    coarse = labels(tmp_path, 'coarse', [0., 2.], [.25, .25])
    dense = labels(tmp_path, 'dense', [0., 1., 2.], [.25, 1.25, .25])
    report = compare(coarse, dense)
    event = report['events'][0]
    assert event['reference_only_observed_mass_kg'] == 2
    assert event['terminal_forward_backward_difference_kg'] == [-2, -2]
    assert event['both_observed_mass_kg'] == 0
    assert event['chord_time_max_absolute_difference_s'] is None
    assert report['final_destination_disagreement_mass_kg'] == 0
    assert report['residence'][1]['max_absolute_difference_s'] == .5
    assert report['q_n_status'] == 'not_granted'


def test_self_comparison_retains_saved_interval_uncertainty(tmp_path):
    path = labels(tmp_path, 'native', [0., 1., 2.], [.25, 1.25, .25])
    event = compare(path, path)['events'][0]
    assert event['chord_time_max_absolute_difference_s'] == 0
    assert event['saved_interval_minimum_required_max_difference_s'] == 0
    assert event['saved_interval_worst_possible_max_difference_s'] == 1


@pytest.mark.parametrize('field,value,error', [('particle_zone', [4], 'typed cohort'),
                                             ('initial_fluid_mass_kg', [3], 'physical mass')])
def test_rejects_mismatched_cohort_or_mass(tmp_path, field, value, error):
    a = labels(tmp_path, 'a', [0., 2.], [.25, .25])
    b = labels(tmp_path, 'b', [0., 2.], [.25, .25])
    with h5py.File(b, 'r+') as h:
        h[field][:] = value
    with pytest.raises(ValueError, match=error):
        compare(a, b)


def test_rejects_changed_finite_event_aperture(tmp_path):
    a = labels(tmp_path, 'a', [0., 2.], [.25, .25])
    b = labels(tmp_path, 'b', [0., 2.], [.25, .25])
    with h5py.File(b, 'r+') as h:
        config = json.loads(h.attrs['config_json'])
        config['events'][0]['aperture_bounds'][0][1] = .25
        h.attrs['config_json'] = json.dumps(config)
    with pytest.raises(ValueError, match='operators'):
        compare(a, b)


def test_failed_receipt_cannot_supply_actual_evidence(tmp_path):
    receipt = tmp_path/'receipt.json'
    receipt.write_text(json.dumps(dict(status='failed', returncode=1)))
    with pytest.raises(ValueError, match='terminal and successful'):
        _label_binding(tmp_path/'missing.h5', receipt)


def test_adaptive_save_overshoot_retains_actual_alignment_uncertainty(tmp_path):
    a = labels(tmp_path, 'a', [0., 1.2, 2.], [.25, 1.25, .25])
    b = labels(tmp_path, 'b', [0., .9, 2.], [.25, 1.25, .25])
    report = compare(a, b)
    assert report['max_actual_timestamp_alignment_difference_s'] == pytest.approx(.3)
    assert report['events'][0]['saved_interval_worst_possible_max_difference_s'] >= 1
    assert report['q_n_status'] == 'not_granted'
