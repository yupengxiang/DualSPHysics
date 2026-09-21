import numpy as np
import pytest
from scripts.core_qualification import aligned_difference


def test_native_cadence_alignment_and_error_not_point_identity():
    dense=np.arange(0,1.001,.01); coarse=np.arange(0,1.001,.02)
    a={"time_s":dense,"normalized_values":np.column_stack((dense,2*dense))}
    b={"time_s":coarse,"normalized_values":np.column_stack((coarse,2*coarse+.03))}
    result=aligned_difference(a,b)
    assert result["maximum"]==pytest.approx(.03)
    assert result["score_frames"]==51
    assert result["common_end_s"]==1


def test_nonfinite_missing_and_disordered_observations_cannot_pass():
    a={"time_s":[0,1],"normalized_values":[[0],[1]]}
    with pytest.raises(ValueError): aligned_difference(a,{"time_s":[1,0],"normalized_values":[[0],[1]]})
    with pytest.raises(ValueError): aligned_difference(a,{"time_s":[0,1],"normalized_values":[[0],[float('nan')]]})
    with pytest.raises(ValueError): aligned_difference(a,{"time_s":[0],"normalized_values":[[0]]})


def test_cfl_change_without_actual_time_refinement_is_rejected():
    from scripts.core_qualification import time_step_evidence
    original='DtMin=1.7e-5\nSteps of simulation..............: 250,934\n'
    assert not time_step_evidence(original,original)['passed']
    assert not time_step_evidence(original,'')['passed']
    refined='DtMin=8.5e-6\nSteps of simulation..............: 501,868\n'
    assert time_step_evidence(original,refined)['passed']


@pytest.mark.parametrize('key,value', [
    ('observation_version', 'fixed_015m_vertical_reference060_v2'),
    ('observation_geometry', {'com_scale_m': [1.2, .4, 1.2]}),
    ('observable_layout', 'different physical quantity')])
def test_equal_values_cannot_hide_different_observation_contract(key, value):
    a = {'time_s': [0, 1], 'normalized_values': [[0], [1]]}
    b = dict(a, **{key: value})
    with pytest.raises(ValueError, match='contract mismatch'):
        aligned_difference(a, b)
    assert aligned_difference(b, b)['maximum'] == 0


@pytest.mark.parametrize('cadence', [0, -1, float('nan'), float('inf')])
def test_invalid_alignment_cadence_rejected(cadence):
    a = {'time_s': [0, 1], 'normalized_values': [[0], [1]]}
    with pytest.raises(ValueError, match='cadence'):
        aligned_difference(a, a, cadence)


def test_malformed_time_value_axis_rejected():
    a = {'time_s': [0, 1], 'normalized_values': [[0]]}
    with pytest.raises(ValueError, match='axes'):
        aligned_difference(a, a)


@pytest.mark.parametrize('tallwall', [False, True])
def test_manufactured_observer_calibration(tmp_path, tallwall):
    from scripts.core_qualification import calibrate_f4
    report = calibrate_f4(tmp_path / 'calibration.json', tallwall=tallwall)
    assert report['passed']
    assert report['max_absolute_error'] < 1e-12
    assert len(report['observation_geometry']['bin_edges_m'][2]) == (9 if tallwall else 5)
    assert report['observation_geometry']['com_scale_m'] == [1.2, .4, .6]
