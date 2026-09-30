import pytest
import json
from scripts.ds_data02_compare_observations import bins, static_physical_control


def test_ambiguous_bins_and_unresolved_time_shift_rejected():
    assert bins([{'time_s': 0}, {'time_s': .01005}], .01, .0002).tolist() == [0, 1]
    with pytest.raises(ValueError, match='ambiguous'):
        bins([{'time_s': 0}, {'time_s': .001}], .01, .0002)
    with pytest.raises(ValueError, match='tolerance'):
        bins([{'time_s': 0}, {'time_s': .015}], .01, .0002)


def test_numerical_settings_do_not_replace_physical_motion_binding():
    attrs = {'motion_control_semantics_json': json.dumps({'element_empty': True}),
             'control_binding_json': json.dumps(dict(control_family_id='static', initial_state={},
                 parameter_values={'depth': .3}, event_window={'end_s': 1.6, 'save_interval_s': .01},
                 solver_parameters={'DtFixed': 0}))}
    baseline = static_physical_control(attrs)
    binding = json.loads(attrs['control_binding_json'])
    binding['solver_parameters']['DtFixed'] = .00001
    binding['event_window']['save_interval_s'] = .001
    attrs['control_binding_json'] = json.dumps(binding)
    assert baseline == static_physical_control(attrs)
    binding['parameter_values']['depth'] = .4
    attrs['control_binding_json'] = json.dumps(binding)
    assert baseline != static_physical_control(attrs)
    attrs['motion_control_semantics_json'] = json.dumps({'element_empty': False})
    with pytest.raises(ValueError, match='motion operator'):
        static_physical_control(attrs)
