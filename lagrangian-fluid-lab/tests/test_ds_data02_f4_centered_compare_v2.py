import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_f4_centered_compare_v2 import source_mass_by_label


def test_native_source_label_maps_to_registered_continuum_mass():
    initial = {'continuum_mass_by_source_kg': {'drop': 5.824, 'pool': 53.248}, 'source_regions': {'drop': {'label': 'falling_drop'}, 'pool': {'label': 'pool'}}, 'source_labels': {'mkfluid:0': 'pool', 'mkfluid:1': 'falling_drop'}}
    assert source_mass_by_label(initial) == {'falling_drop': 5.824, 'pool': 53.248}


def test_ambiguous_labels_cannot_silently_merge_mass():
    initial = {'continuum_mass_by_source_kg': {'left': 1, 'right': 2}, 'source_regions': {'left': {'label': 'same'}, 'right': {'label': 'same'}}, 'source_labels': {'mkfluid:0': 'same'}}
    with pytest.raises(ValueError, match='Ambiguous'):
        source_mass_by_label(initial)
