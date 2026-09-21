from pathlib import Path
import pytest
from scripts.core_runtime import digest, input_inventory, publish_inputs


def fixture(tmp_path):
    staging = tmp_path / 'stage'
    staging.mkdir()
    source = tmp_path / 'source'
    source.write_bytes(b'input bytes')
    sha = digest(source)
    source.rename(staging / sha)
    (staging / sha).chmod(0o755)
    target = tmp_path / 'destination' / 'binary'
    return staging, target, {'input_files': [{'path': str(target), 'sha256': sha}]}


def test_publish_missing_and_idempotent(tmp_path):
    staging, target, spec = fixture(tmp_path)
    assert not input_inventory(spec)[0]['exists']
    assert publish_inputs(spec, staging)[0]['matches']
    assert target.stat().st_mode & 0o111
    original_inode = target.stat().st_ino
    assert publish_inputs(spec, staging)[0]['matches']
    assert target.stat().st_ino == original_inode


def test_existing_conflict_preserved(tmp_path):
    staging, target, spec = fixture(tmp_path)
    target.parent.mkdir()
    target.write_bytes(b'existing running input')
    with pytest.raises(ValueError, match='existing input hash mismatch'):
        publish_inputs(spec, staging)
    assert target.read_bytes() == b'existing running input'


def test_corrupt_staging_never_published(tmp_path):
    staging, target, spec = fixture(tmp_path)
    next(staging.iterdir()).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='staged input hash mismatch'):
        publish_inputs(spec, staging)
    assert not target.exists()
