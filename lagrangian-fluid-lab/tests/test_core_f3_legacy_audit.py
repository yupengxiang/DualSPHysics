import copy
import json
from pathlib import Path

import pytest

from scripts.core_f3_legacy_audit import adapt_case
from scripts.core_runtime import digest


def fixture_row(tmp_path):
    audit = {'case_id': 'case', 'hdf5': 'case.h5', 'hdf5_sha256': 'a' * 64}
    prepared = {'id': 'case'}
    refs = {}
    for name, payload in [('audit', audit), ('prepared', prepared)]:
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(payload))
        refs[name] = {'path': path.name, 'sha256': digest(path)}
    return {'case_id': 'case', 'hdf5': 'case.h5', 'sha256': 'a' * 64, 'provenance': refs}


@pytest.mark.parametrize('role', ['audit', 'prepared'])
def test_changed_legacy_evidence_rejected_before_trajectory_read(tmp_path, role):
    row = fixture_row(tmp_path)
    (tmp_path / row['provenance'][role]['path']).write_text('{}')
    with pytest.raises(ValueError, match='source hash mismatch'):
        adapt_case(row, tmp_path)


def test_wrong_trajectory_binding_rejected(tmp_path):
    row = fixture_row(tmp_path)
    row['sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='identity mismatch'):
        adapt_case(row, tmp_path)


def test_other_trajectory_path_rejected(tmp_path):
    row = fixture_row(tmp_path)
    row['hdf5'] = 'other.h5'
    with pytest.raises(ValueError, match='paths differ'):
        adapt_case(row, tmp_path)
