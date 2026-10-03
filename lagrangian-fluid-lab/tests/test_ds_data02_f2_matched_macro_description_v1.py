import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f2_matched_macro_description_v1 import observe


def fixture(path, *, invalid_velocity=False, type_change=False):
    nt, npart = 401, 3
    with h5py.File(path, 'w') as h:
        h['time'] = np.linspace(0, 4, nt)
        h['initial_type'] = [0, 3, 3]
        h['type'] = np.tile([0, 3, 3], (nt, 1))
        h['valid'] = np.ones((nt, npart), dtype=bool)
        h['valid'][200:, 2] = False
        h['mass'] = np.tile(np.array([12.288] * npart, dtype=np.float32), (nt, 1))
        h['position'] = np.tile(np.array([[0, 0, 0], [1, 2, 3], [3, 2, 3]], dtype=float), (nt, 1, 1))
        h['velocity'] = np.tile(np.array([[0, 0, 0], [2, 0, 0], [2, 0, 0]], dtype=float), (nt, 1, 1))
        if invalid_velocity:
            h['velocity'][50, 1, 0] = np.nan
        if type_change:
            h['type'][50, 1] = 1


def test_missing_cohort_is_retained_in_independent_mass_ledger(tmp_path):
    path = tmp_path / 'source.h5'
    fixture(path)
    r = observe(path, {'fluid_particles': 2})
    native_mass = float(np.float32(12.288))
    np.testing.assert_allclose(r['values'][0], [2*native_mass, 2, 2, 3, 4*native_mass])
    np.testing.assert_allclose(r['values'][200], [native_mass, 1, 2, 3, 2*native_mass])
    assert r['missing_initial_cohort_mass_kg'][200] == native_mass
    assert r['initial_native_float_mass_kg'] == 2*native_mass


def test_invalid_active_velocity_cannot_disappear_from_macros(tmp_path):
    path = tmp_path / 'source.h5'
    fixture(path, invalid_velocity=True)
    with pytest.raises(ValueError, match='active fluid state invalid'):
        observe(path, {'fluid_particles': 2})


def test_native_type_change_is_rejected(tmp_path):
    path = tmp_path / 'source.h5'
    fixture(path, type_change=True)
    with pytest.raises(ValueError, match='changes native type'):
        observe(path, {'fluid_particles': 2})
