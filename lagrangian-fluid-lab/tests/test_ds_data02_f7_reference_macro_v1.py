import sys
import json
from pathlib import Path

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f7_reference_macro_v1 import frame_macro, compare


def test_inactive_nan_does_not_poison_fluid_macro(tmp_path):
    with h5py.File(tmp_path / 'native.h5', 'w') as h:
        h['valid'] = [[True, False, True]]
        h['mass'] = [[2., np.nan, 999.]]
        h['position'] = [[[1., 2., 3.], [np.nan] * 3, [100.] * 3]]
        h['velocity'] = [[[3., 0., 0.], [np.nan] * 3, [100.] * 3]]
        assert frame_macro(h, 0, np.array([True, True, False]), chunk=2) == [2., 1., 2., 3., 9.]


def test_same_filename_retains_both_resolution_comparisons(tmp_path):
    paths = []
    for name, mass in [('fine', 10.), ('medium', 9.9), ('coarse', 9.8)]:
        directory = tmp_path / name;directory.mkdir()
        path = directory / 'macro-series.json'
        d = {'source': name, 'source_sha256': name, 'physical_condition_sha256': 'same',
             'time_s': [0., 12.], 'operators': ['mass', 'com_x', 'com_y', 'com_z', 'ke'],
             'values': [[mass, 0., 0., 1., 1.], [mass, 1., 1., 1., 2.]]}
        path.write_text(json.dumps(d));paths.append(path)
    norm = tmp_path / 'normalizers.json'
    norm.write_text(json.dumps({'continuous_initial_mass_kg': 10., 'com_axis_scales_m': [1., 1., 1.], 'macro_relative_budget': .05}))
    report = compare(paths[0], paths[1:], norm, tmp_path / 'comparison.json')
    assert set(report['comparisons']) == {str(paths[1]), str(paths[2])}
    assert report['comparisons'][str(paths[2])]['metrics']['mass']['max_scaled_error'] > report['comparisons'][str(paths[1])]['metrics']['mass']['max_scaled_error']
