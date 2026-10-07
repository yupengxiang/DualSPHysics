import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_stage2_scan import scan


@pytest.fixture
def state(tmp_path):
    p = tmp_path / 'trajectory.h5'
    with h5py.File(p, 'w') as h:
        h['time'] = [0., 1., 2., 3.]
        h['particle_id'] = np.array([100, 101, 102, 103], dtype='uint32')
        h['particle_zone'] = np.array([0, 0, 0, 1], dtype='int16')
        h['initial_type'] = np.array([0, 2, 3, 3], dtype='int8')
        h['initial_mass'] = [100., 50., 2., 3.]
        h['valid'] = np.ones((4, 4), dtype=bool)
        h['type'] = np.tile(h['initial_type'][:], (4, 1))
        h['mass'] = np.tile(h['initial_mass'][:], (4, 1))
        h['density'] = np.full((4, 4), 1000.)
        h['pressure'] = np.zeros((4, 4))
        h['position'] = np.tile(np.arange(4)[:, None, None], (1, 4, 3)).astype(float)
        h['velocity'] = np.ones((4, 4, 3))
        h.attrs['units_json'] = json.dumps(dict(time='s', position='m', velocity='m/s', density='kg/m^3', mass='kg', pressure='Pa'))
    return p


def test_missing_denominators_and_revival_use_fluid_cohort(state):
    with h5py.File(state, 'r+') as h:
        h['valid'][1, 2] = False
        h['valid'][3, 3] = False
        h['position'][1, 2] = np.nan  # invalid placeholders are allowed
    r = scan(state, chunk=2)
    fluid = r['type_ledgers']['fluid']
    assert fluid['typed_initial_mass_kg'] == 5.
    assert fluid['cumulative_unique_missing'] == 2
    assert fluid['maximum_instantaneous_missing'] == 1
    assert fluid['missing_at_final'] == 1
    assert fluid['missing_particle_frames'] == 2
    assert fluid['revived_unique_ids'] == 1
    assert fluid['missing_initial_mass_kg'] == [0., 2., 0., 3.]
    assert not any(fluid['active_nonfinite'].values())
    missing = next(row for row in r['missing_id_records'] if row['idp'] == 102)
    assert missing['first_missing_bracket_s'] == [0., 1.]
    assert missing['first_gap_previous_state']['frame'] == 0
    assert missing['first_gap_previous_state']['position_m'] == [0., 0., 0.]
    assert missing['last_known_frame'] == 3
    assert missing['native_exit_cause'] == 'EVIDENCE_UNKNOWN'
    assert r['QN'] == 'NOT_ASSESSED'


@pytest.mark.parametrize('field,value', [('mass', -1.), ('mass', np.nan), ('density', 0.), ('velocity', np.nan)])
def test_active_scientific_errors_are_recorded(state, field, value):
    with h5py.File(state, 'r+') as h:
        h[field][1, 2] = value
    r = scan(state)
    assert r['scan_status'] == 'SCANNED_FIELD_FAILURE'
    assert 'fluid_active_field_failure' in r['failures']


def test_shuffle_with_all_identity_bound_fields_preserves_metrics(state, tmp_path):
    first = scan(state)
    p = tmp_path / 'shuffled.h5'
    permutation = [3, 1, 0, 2]
    with h5py.File(state, 'r') as src, h5py.File(p, 'w') as dst:
        for key, dataset in src.items():
            value = dataset[:]
            if key != 'time':
                value = value[permutation] if value.ndim == 1 else value[:, permutation]
            dst[key] = value
        dst.attrs.update(src.attrs)
    second = scan(p)
    assert first['type_ledgers'] == second['type_ledgers']
    assert first['macros'] == second['macros']


def test_duplicate_identity_is_rejected(state):
    with h5py.File(state, 'r+') as h:
        h['particle_id'][2] = h['particle_id'][1]
    with pytest.raises(ValueError, match='Duplicate'):
        scan(state)


def test_initially_invalid_mass_is_retained_in_source_denominator(state):
    with h5py.File(state, 'r+') as h:
        h['valid'][:, 2] = False
    r = scan(state)
    fluid = r['type_ledgers']['fluid']
    assert fluid['typed_initial_mass_kg'] == 5.
    assert fluid['initially_absent_count'] == 1
    assert fluid['active_mass_kg'][0] == 3.
    missing = r['missing_id_records'][0]
    assert missing['first_missing_frame'] == 0
    assert missing['first_gap_previous_state']['frame'] == -1


def test_time_disorder_is_not_silently_sorted(state):
    with h5py.File(state, 'r+') as h:
        h['time'][2] = 0.5
    assert 'time_nonfinite_or_nonmonotonic' in scan(state)['failures']
