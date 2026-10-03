import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_f3_fluid_only_labels_v1 import FluidOnlyView, isolated_module
from ds_data02_native_labels import materialize
from ds_data02_verified_native_labels_v1 import label_closure

FRAME = 'DualSPHysics case Cartesian coordinates (x,y,z)'
CONFIG = {'frame_kind': 'fixed_solver_frame', 'coordinate_frame': FRAME,
          'source_regions': [{'id': 'all', 'bounds': [[-2, 2], [-1, 1], [-1, 1]]}],
          'destination_regions': [{'id': 'left', 'bounds': [[-2, 0], [-1, 1], [-1, 1]]},
                                  {'id': 'right', 'bounds': [[0, 2], [-1, 1], [-1, 1]]}],
          'events': [{'id': 'cross', 'axis': 0, 'value': 0, 'aperture_bounds': [[-1, 1], [-1, 1]]}]}
BINDING = {'frames': 3, 'fluid_particles': 3, 'fluid_id_range': [1, 3], 'coordinate_frame': FRAME}


def fixture(path, full=False):
    pos = np.zeros((3, 3, 3), dtype='f4')
    pos[:, :, 0] = [[-.5, .6, -.4], [.2, -.2, -.2], [.7, -.6, .1]]
    valid = np.ones((3, 3), dtype=bool)
    valid[-1, -1] = False
    mass = np.tile(np.array([.1, .2, .3], dtype='f4'), (3, 1))
    types, mks = np.full((3, 3), 3, dtype='f4'), np.ones((3, 3), dtype='f4')
    ids = np.arange(1, 4)
    if full:
        pos = np.concatenate((np.zeros((3, 1, 3)), pos), axis=1)
        valid = np.column_stack((np.ones(3, bool), valid))
        mass = np.column_stack((np.ones(3), mass))
        types = np.column_stack((np.zeros(3), types))
        mks = np.column_stack((np.full(3, 10), mks))
        ids = np.arange(4)
    with h5py.File(path, 'x') as h:
        if full:
            h.attrs['coordinate_frame'] = FRAME
        for key, value in {'position': pos, 'valid': valid, 'mass': mass, 'type': types, 'mk': mks,
                           'particle_id': ids, 'particle_zone': np.zeros(len(ids)), 'time': [0, 1, 2],
                           'velocity': np.zeros_like(pos)}.items():
            h.create_dataset(key, data=value)


def test_equivalence_to_actual_full_typed_fluid_cohort(tmp_path):
    fluid, full = tmp_path/'fluid.h5', tmp_path/'full.h5'
    fixture(fluid)
    fixture(full, full=True)
    a, b = tmp_path/'a.h5', tmp_path/'b.h5'
    module = isolated_module(Path(__file__).resolve().parents[1]/'scripts/ds_data02_native_labels.py', fluid, BINDING)
    module.materialize(fluid, a, CONFIG, particle_chunk=2)
    materialize(full, b, CONFIG, particle_chunk=2)
    with h5py.File(a, 'r') as h, h5py.File(b, 'r') as g:
        for key in ['source_label', 'final_category', 'failure_reason', 'first_passage_interval',
                    'first_passage_chord_time', 'first_passage_censor', 'residence_time_s',
                    'unresolved_interval_time_s', 'initial_fluid_mass_kg']:
            np.testing.assert_equal(h[key][:], g[key][1:])
        np.testing.assert_equal(h['destination_time_series'][:], g['destination_time_series'][:, 1:])
        for key in ['forward_backward_mass_kg', 'cumulative_net_flux_kg', 'source_final_mass_kg',
                    'unknown_mass_kg', 'numerical_loss_mass_kg', 'invalid_state_mass_kg']:
            np.testing.assert_allclose(h[key][:], g[key][:], atol=1e-12)
        ids = np.column_stack((h['particle_zone'][:], h['particle_id'][:]))
        mass = h['initial_fluid_mass_kg'][:].sum()
    assert label_closure(a, ids, mass)['passed']
    with h5py.File(a, 'r+') as h:
        h['unknown_mass_kg'][1] = 1
    assert not label_closure(a, ids, mass)['passed']


def test_actual_mass_preserved_and_initial_arrays_derived(tmp_path):
    p = tmp_path/'fluid.h5'
    fixture(p)
    with FluidOnlyView(p, BINDING) as view, h5py.File(p, 'r') as h:
        assert view['mass'] is view.h['mass'] or np.array_equal(view['mass'][:], h['mass'][:])
        np.testing.assert_equal(view['initial_mass'][:], h['mass'][0])
        assert view['mass'].dtype == h['mass'].dtype
        assert not np.isclose(view['initial_mass'][:].astype(float).sum(), .6, rtol=0, atol=1e-10)
        assert view['valid'][-1, -1] == False


@pytest.mark.parametrize('field,value', [('type', 2.5), ('mk', float('nan'))])
def test_fractional_and_nonfinite_categorical_fields_rejected(tmp_path, field, value):
    p = tmp_path/'fluid.h5'
    fixture(p)
    with h5py.File(p, 'r+') as h:
        h[field][1, 0] = value
    with FluidOnlyView(p, BINDING) as view:
        with pytest.raises(ValueError):
            view[field][:]


def test_changed_native_fluid_type_rejected_by_canonical_operator(tmp_path):
    p = tmp_path/'fluid.h5'
    fixture(p)
    with h5py.File(p, 'r+') as h:
        h['type'][1, 0] = 0
    module = isolated_module(Path(__file__).resolve().parents[1]/'scripts/ds_data02_native_labels.py', p, BINDING)
    with pytest.raises(ValueError, match='changes type'):
        module.materialize(p, tmp_path/'labels.h5', CONFIG)


def test_official_identity_range_rejected_if_changed(tmp_path):
    p = tmp_path/'fluid.h5'
    fixture(p)
    with h5py.File(p, 'r+') as h:
        h['particle_id'][1] = 1
    with pytest.raises(ValueError, match='identity'):
        FluidOnlyView(p, BINDING)
