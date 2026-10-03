import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ds_data02_native_stage_retire_v1 as retirement


def fixture(tmp_path, monkeypatch):
    stage = tmp_path / 'staging'
    source = stage / 'f1-ecc-test'
    target = tmp_path / 'native' / 'solver_output'
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    for root in (source, target):
        (root / 'Part.bi4').write_bytes(b'actual unchanged native bytes')
    (target / 'Part.bi4').chmod(0o400)
    monkeypatch.setattr(retirement, 'STAGING_ROOT', stage)
    native = tmp_path / 'native.json'
    native.write_text(json.dumps(dict(status='completed', returncode=0,
        command=['solver', '-gpu:0', 'prefix', str(source)], output_root=str(target.parent),
        input_hashes_at_launch={'source':'same'}, input_hashes_after_run={'source':'same'})))
    publication = tmp_path / 'publication.json'
    publication.write_text(json.dumps(dict(schema='ds02.native-storage-publication.v1', status='completed',
        terminal_receipt=str(native), terminal_receipt_sha256=retirement.digest(native),
        immutable_staging_source=str(source), home_native_source=str(target),
        files=[dict(relative_path='Part.bi4', bytes=(source/'Part.bi4').stat().st_size,
                    sha256=retirement.digest(source/'Part.bi4'))])))
    cpu = tmp_path / 'cpu.json'
    cpu.write_text(json.dumps(dict(status='completed', returncode=0,
        input_hashes_at_launch={'a':'same'}, input_hashes_after_run={'a':'same'},
        request=dict(command=['python','publish','--report',str(publication)]))))
    return source, target, publication, cpu, tmp_path / 'transition.json'


def test_only_temporary_duplicate_removed(tmp_path, monkeypatch):
    source, target, publication, cpu, report = fixture(tmp_path, monkeypatch)
    result = retirement.retire(publication, cpu, report)
    assert result['status'] == 'completed'
    assert not source.exists()
    assert (target / 'Part.bi4').read_bytes() == b'actual unchanged native bytes'
    assert json.loads(report.read_text())['full_sha256_verified_both_copies']


def test_canonical_corruption_preserves_source(tmp_path, monkeypatch):
    source, target, publication, cpu, report = fixture(tmp_path, monkeypatch)
    path = target / 'Part.bi4'
    path.chmod(0o600)
    path.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='Copy bytes differ'):
        retirement.retire(publication, cpu, report)
    assert (source / 'Part.bi4').exists()
    assert not report.exists()


def test_unfinished_publication_preserves_source(tmp_path, monkeypatch):
    source, target, publication, cpu, report = fixture(tmp_path, monkeypatch)
    receipt = json.loads(cpu.read_text())
    receipt['status'] = 'running'
    cpu.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='Actual successful'):
        retirement.retire(publication, cpu, report)
    assert (source / 'Part.bi4').exists()


def test_extra_unpublished_file_preserves_both_copies(tmp_path, monkeypatch):
    source, target, publication, cpu, report = fixture(tmp_path, monkeypatch)
    (source / 'other.bin').write_bytes(b'preserve')
    with pytest.raises(ValueError, match='inventories'):
        retirement.retire(publication, cpu, report)
    assert (source / 'Part.bi4').exists()
    assert (source / 'other.bin').exists()
