import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f3_nvme_input_audit_v1 import verified_copy


def test_copied_bytes_match_registered_source_and_original_is_preserved(tmp_path):
    source = tmp_path / 'source.h5'; source.write_bytes(b'native-typed-state' * 700)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    target = tmp_path / 'copy.h5'
    assert verified_copy(source, target, expected) == expected
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & 0o222 == 0


def test_stale_registered_digest_rejected_before_audit(tmp_path):
    source = tmp_path / 'source.h5'; source.write_bytes(b'changed-input')
    with pytest.raises(ValueError, match='differs from registered'):
        verified_copy(source, tmp_path / 'copy.h5', '0' * 64)
