import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f6_floating_spatial_compare_v1 import load_csv


def fixture(path, *, nonfinite=False):
    fields = ['part', 'time [s]', 'center.x [m]', 'center.y [m]', 'center.z [m]',
              'roll [deg]', 'pitch [deg]', 'yaw [deg]', 'heave [m]']
    times = np.linspace(0, 12, 241)
    with path.open('w') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(fields)
        for i, t in enumerate(times):
            writer.writerow([i, t, 2.4, 1.2, 1.08, 90, -180, 45,
                             float('nan') if nonfinite and i == 120 else 0.1])
    return times


def test_official_degrees_and_metres_have_correct_physical_units(tmp_path):
    path = tmp_path / 'rigid.csv'
    result = load_csv(path, fixture(path))
    np.testing.assert_allclose(result['orientation_euler_rad'][80], [np.pi/2, -np.pi, np.pi/4])
    np.testing.assert_allclose(result['position'][80], [2.4, 1.2, 1.08])
    assert result['heave'][80] == 0.1


def test_separately_shifted_native_timeline_is_rejected(tmp_path):
    path = tmp_path / 'rigid.csv'
    times = fixture(path)
    times[120] += 1e-4
    with pytest.raises(ValueError, match='timelines differ'):
        load_csv(path, times)


def test_nonfinite_saved_state_cannot_be_silently_omitted(tmp_path):
    path = tmp_path / 'rigid.csv'
    with pytest.raises(ValueError, match='Nonfinite'):
        load_csv(path, fixture(path, nonfinite=True))
