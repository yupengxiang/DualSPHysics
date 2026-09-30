import pytest
from scripts.ds_data02_compare_observations import bins


def test_ambiguous_bins_and_unresolved_time_shift_rejected():
    assert bins([{'time_s': 0}, {'time_s': .01005}], .01, .0002).tolist() == [0, 1]
    with pytest.raises(ValueError, match='ambiguous'):
        bins([{'time_s': 0}, {'time_s': .001}], .01, .0002)
    with pytest.raises(ValueError, match='tolerance'):
        bins([{'time_s': 0}, {'time_s': .015}], .01, .0002)
