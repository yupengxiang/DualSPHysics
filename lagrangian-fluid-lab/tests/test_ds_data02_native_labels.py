import copy
import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_native_labels import materialize, validate_config


def fixture(tmp_path):
    source = tmp_path / 'native.h5'
    position = np.array([[[.25,.5,.5],[.25,1.5,.5],[.25,.5,.5],[.25,.5,.5]],
                         [[1.25,.5,.5],[1.25,1.5,.5],[1.25,.5,.5],[.25,.5,.5]],
                         [[.25,.5,.5],[.25,1.5,.5],[np.nan]*3,[.25,.5,.5]]])
    with h5py.File(source, 'w') as h:
        h.attrs['coordinate_frame'] = 'fixed_tank'
        h.create_dataset('time', data=[0.,1.,2.])
        h.create_dataset('particle_id', data=[1,2,3,1])
        h.create_dataset('particle_zone', data=[0,0,0,1])
        h.create_dataset('valid', data=[[1,1,1,1],[1,1,1,1],[1,1,0,1]])
        h.create_dataset('position', data=position)
        h.create_dataset('mass', data=[[2.,3.,5.,7.]]*3)
        h.create_dataset('type', data=[[3,3,3,2]]*3)
    left = dict(id='left', bounds=[[0.,1.],[0.,2.],[0.,1.]])
    right = dict(id='right', bounds=[[1.,2.],[0.,2.],[0.,1.]])
    config = dict(frame_kind='fixed_solver_frame', coordinate_frame='fixed_tank',
                  source_regions=[left], destination_regions=[left,right],
                  events=[dict(id='portal', axis=0, value=1., aperture_bounds=[[0.,1.],[0.,1.]])])
    return source, config


def test_finite_portal_recrossing_missing_identity_and_mass_denominator(tmp_path):
    source, config = fixture(tmp_path)
    output = tmp_path / 'labels.h5'
    report = materialize(source, output, config, particle_chunk=2)
    assert report['initial_fluid_mass_kg'] == 10
    with h5py.File(output, 'r') as h:
        np.testing.assert_allclose(h['forward_backward_mass_kg'][-1,0], [7,2])
        assert h['cumulative_net_flux_kg'][-1,0] == 5
        np.testing.assert_allclose(h['first_passage_interval'][0,0], [0,1])
        assert h['first_passage_chord_time'][0,0] == .75
        assert np.isnan(h['first_passage_interval'][1,0]).all()  # outside finite aperture
        assert h['first_passage_censor'][1,0] == 1
        np.testing.assert_allclose(h['residence_time_s'][0], [1.5,.5])
        np.testing.assert_allclose(h['residence_time_s'][2], [.75,.25])
        assert h['unresolved_interval_time_s'][2] == 1
        assert h['final_category'][2] == -1
        assert h['failure_reason'][2] == 1
        assert h['numerical_loss_mass_kg'][-1] == 5
        assert h['source_final_mass_kg'][:].sum() == 10
        assert h.attrs['q_n_status'] == 'not_assessed'


def test_births_and_variable_mass_require_explicit_lifecycle(tmp_path):
    source, config = fixture(tmp_path)
    with h5py.File(source, 'r+') as h:
        h['type'][1,3] = 3
    with pytest.raises(ValueError, match='births'):
        materialize(source, tmp_path / 'birth.h5', config)
    with h5py.File(source, 'r+') as h:
        h['type'][1,3] = 2
        h['mass'][1,0] = 1.
    with pytest.raises(ValueError, match='variable mass'):
        materialize(source, tmp_path / 'mass.h5', config)


def test_labels_reject_wrong_frame_and_overlapping_regions(tmp_path):
    source, config = fixture(tmp_path)
    wrong = copy.deepcopy(config)
    wrong['coordinate_frame'] = 'world'
    with pytest.raises(ValueError, match='differs'):
        materialize(source, tmp_path / 'wrong.h5', wrong)
    wrong = copy.deepcopy(config)
    wrong['frame_kind'] = 'moving_body_frame'
    with pytest.raises(ValueError, match='saved transforms'):
        validate_config(wrong)
    config['destination_regions'][1]['bounds'][0] = [.5,2.]
    with pytest.raises(ValueError, match='overlap'):
        validate_config(config)


def test_no_overwrite_and_duplicate_typed_identity(tmp_path):
    source, config = fixture(tmp_path)
    with pytest.raises(FileExistsError):
        materialize(source, source, config)
    with h5py.File(source, 'r+') as h:
        h['particle_zone'][3] = 0
    with pytest.raises(ValueError, match='typed identity'):
        materialize(source, tmp_path / 'duplicates.h5', config)


def test_native_mk_sources_keep_actual_identity_provenance_at_region_edges(tmp_path):
    source, config = fixture(tmp_path)
    config['source_assignment'] = 'native_initial_mk'
    config['source_regions'] = [dict(id='lower_mk', native_mk=10, bounds=[[0, 1], [0, 1], [0, 1]]),
                                dict(id='upper_mk', native_mk=11, bounds=[[0, 1], [1, 2], [0, 1]])]
    # Deliberately mismatched initial point/box is a representation diagnostic;
    # native fluid-block provenance must not be silently relabeled by position.
    with h5py.File(source, 'r+') as h:
        h.create_dataset('initial_mk', data=[11, 10, 10, 11])
    output = tmp_path / 'mk-labels.h5'
    materialize(source, output, config)
    with h5py.File(output, 'r') as h:
        np.testing.assert_array_equal(h['source_label'][:], [2, 1, 1, 0])
        assert h['source_final_mass_kg'][:].sum() == 10
    with h5py.File(source, 'r+') as h:
        h['initial_mk'][2] = 12
    with pytest.raises(ValueError, match='no registered'):
        materialize(source, tmp_path / 'unknown-mk.h5', config)


def test_native_source_assignment_rejects_duplicate_blocks(tmp_path):
    _, config = fixture(tmp_path)
    config['source_assignment'] = 'native_initial_mk'
    config['source_regions'] *= 2
    for row in config['source_regions']:
        row['native_mk'] = 10
    with pytest.raises(ValueError, match='unique integers'):
        validate_config(config)
