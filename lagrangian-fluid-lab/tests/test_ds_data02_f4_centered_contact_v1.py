import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f4_centered_contact_v1 import frame_support
from ds_data02_f4_science import _event_from_flags, _recontact_from_flags

PROTOCOL = {'support_radius_m': .02, 'minimum_cross_support_pairs': 3,
            'minimum_support_mass_fraction_of_smaller_source': .01}


def test_native_support_is_translation_invariant_and_censors_absence():
    a = np.array([[0., y, 0.] for y in (.0, .1, .2)])
    pos = np.concatenate((a, a + [.015, 0, 0]))
    def observe(p, valid=np.ones(6, bool)):
        return frame_support(p, np.ones(6), valid, np.ones(6, bool),
                             np.array([10] * 3 + [11] * 3), [10, 11], PROTOCOL, 3.)
    native = observe(pos)
    shifted = observe(pos + [2., -7., 4.])
    assert native['contact'] and shifted['contact']
    assert native['support_pairs'] == shifted['support_pairs'] == 3
    assert native['support_mass_kg'] == shifted['support_mass_kg'] == 3
    assert not observe(pos, np.array([True] * 3 + [False] * 3))['contact']
    assert _event_from_flags(np.array([0., .1]), [False, False])['status'] == 'right_censored'


def test_actual_time_brackets_and_active_invalid_state():
    times = np.array([0., .011, .025, .042])
    first = _event_from_flags(times, [False, True, False, True])
    again = _recontact_from_flags(times, [False, True, False, True], first)
    assert first['bracket_s'] == [0., .011]
    assert again['bracket_s'] == [.025, .042]
    pos = np.zeros((6, 3)); pos[0, 0] = np.nan
    with pytest.raises(ValueError, match='Active native fluid'):
        frame_support(pos, np.ones(6), np.ones(6, bool), np.ones(6, bool),
                      np.array([10] * 3 + [11] * 3), [10, 11], PROTOCOL, 3.)
