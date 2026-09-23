from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_core_r002_authorization_v1 as r002


def test_r002_binds_r001_failure_and_explicit_full_window() -> None:
    authorization, spec = r002.build()
    assert authorization["status"] == "authorized_one_cpu_attempt_not_started"
    assert authorization["closed_r001"]["partial_output_reuse_forbidden"] is True
    assert authorization["candidate"]["full_native_interval_count"] == 835
    assert spec["job_id"] == r002.JOB_ID
    assert spec["argv"][-4:] == ["--substeps", "4", "--stop-after", "835"]


def test_r002_write_is_immutable(tmp_path: Path) -> None:
    auth_path, spec_path = tmp_path / "authorization.json", tmp_path / "job.json"
    authorization, spec = r002.write(auth_path, spec_path)
    assert json.loads(auth_path.read_text()) == authorization
    assert json.loads(spec_path.read_text()) == spec
    with pytest.raises(FileExistsError, match="immutable F3 row30 r002 authorization"):
        r002.write(auth_path, spec_path)
