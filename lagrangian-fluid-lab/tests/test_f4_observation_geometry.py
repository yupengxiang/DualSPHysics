import numpy as np
import pytest
from scripts.core_cfd import observation_geometry


def test_legacy_geometry_keeps_original_grid_and_scale():
    edges, scale, version = observation_geometry({})
    np.testing.assert_array_equal(edges[2], np.linspace(0, .6, 5))
    assert scale == [1.2, .4, .6]
    assert version == 'legacy_tank_scaled_v1'


def test_taller_wall_preserves_old_observation_planes_and_sensitivity():
    cfg = {'container_height_m': 1.2,
           'observation_version': 'fixed_015m_vertical_reference060_v2'}
    edges, scale, _ = observation_geometry(cfg)
    np.testing.assert_allclose(edges[2], np.arange(9) * .15)
    assert scale == [1.2, .4, .6]
    # A low-altitude rearrangement distinguishable before remains distinguishable.
    points = np.array([[.1, .1, .10], [.1, .1, .20]])
    counts = np.histogramdd(points, bins=edges)[0]
    assert counts[0, 0, 0] == counts[0, 0, 1] == 1


def test_nonintegral_height_gets_a_short_final_bin():
    edges, _, _ = observation_geometry({'container_height_m': 1.21,
        'observation_version': 'fixed_015m_vertical_reference060_v2'})
    assert edges[2][-1] == 1.21
    assert np.all(np.diff(edges[2]) > 0)
    assert np.max(np.diff(edges[2])) <= .15 + 1e-12


@pytest.mark.parametrize('cfg', [{'container_height_m': float('nan')},
    {'container_height_m': 0}, {'observation_version': 'unknown'}])
def test_invalid_observer_rejected(cfg):
    with pytest.raises(ValueError):
        observation_geometry(cfg)
