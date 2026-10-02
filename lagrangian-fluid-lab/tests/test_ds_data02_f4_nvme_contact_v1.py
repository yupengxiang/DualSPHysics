import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import ds_data02_f4_nvme_contact_v1 as reader


def setup_config(tmp_path, expected=None):
    source = tmp_path / 'original.h5'
    source.write_bytes(b'immutable source fixture')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'source_hdf5': str(source),
        'source_hdf5_sha256': expected or digest, 'owner': 'owner.json',
        'frozen': 'frozen.json', 'mechanism': 'DROP'}))
    return source, digest, config


def test_verified_copy_report_has_no_deleted_private_paths(tmp_path, monkeypatch):
    source, digest, config = setup_config(tmp_path)
    def scientific_reader(copy, owner, frozen, mechanism, output):
        assert copy.read_bytes() == source.read_bytes()
        output.write_text(json.dumps({'source': str(copy),
            'source_sha256': {str(copy): digest}, 'first_contact': {'status': 'right_censored'},
            'q_n_status': 'not_assessed'}))
    monkeypatch.setattr(reader, 'series', scientific_reader)
    output = tmp_path / 'report.json'
    scratch = tmp_path / 'scratch'
    reader.run(config, output, scratch)
    result = json.loads(output.read_text())
    assert result['source'] == str(source)
    assert result['source_sha256'] == {str(source): digest}
    assert result['first_contact']['status'] == 'right_censored'
    assert list(scratch.iterdir()) == []
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_copy_mismatch_rejects_before_reader_and_cleans_scratch(tmp_path, monkeypatch):
    source, digest, config = setup_config(tmp_path, '0' * 64)
    def forbidden(*_):
        pytest.fail('Scientific reader must not run before digest verification')
    monkeypatch.setattr(reader, 'series', forbidden)
    output, scratch = tmp_path / 'report.json', tmp_path / 'scratch'
    with pytest.raises(ValueError, match='differs from registered digest'):
        reader.run(config, output, scratch)
    assert not output.exists()
    assert list(scratch.iterdir()) == []
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
