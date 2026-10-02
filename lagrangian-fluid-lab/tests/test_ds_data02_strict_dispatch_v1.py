import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_strict_dispatch_v1 import GUARD_PATH, check_registered_hashes


def request(extra):
    return {'input_files': [GUARD_PATH, '/tmp/ds02-particle-input'],
            'input_sha256': {GUARD_PATH: 'guard', '/tmp/ds02-particle-input': 'original'},
            **extra}


def test_rejects_changed_native_input_before_dispatch():
    actual = {GUARD_PATH: 'guard', '/tmp/ds02-particle-input': 'changed'}
    with pytest.raises(ValueError, match='differs from registered'):
        check_registered_hashes(request({}), actual)


def test_requires_complete_expectations_and_bound_guard():
    with pytest.raises(ValueError, match='Missing registered'):
        check_registered_hashes(request({'input_sha256': {GUARD_PATH: 'guard'}}),
                                {GUARD_PATH: 'guard', '/tmp/ds02-particle-input': 'original'})
    with pytest.raises(ValueError, match='guard must be'):
        check_registered_hashes(request({'input_sha256': {'/tmp/ds02-particle-input': 'original'}}),
                                {GUARD_PATH: 'guard', '/tmp/ds02-particle-input': 'original'})


def test_conflicting_maps_rejected_and_matching_maps_accepted():
    actual = {GUARD_PATH: 'guard', '/tmp/ds02-particle-input': 'original'}
    check_registered_hashes(request({'input_hashes': actual}), actual)
    with pytest.raises(ValueError, match='Conflicting'):
        check_registered_hashes(request({'input_hashes': {'/tmp/ds02-particle-input': 'other'}}), actual)
