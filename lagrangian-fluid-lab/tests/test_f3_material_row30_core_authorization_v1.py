from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_core_authorization_v1 as authorization
from scripts import core_runtime


def test_authorization_is_isolated_from_expired_historical_ledger() -> None:
    value, spec = authorization.build()
    assert value["status"] == "authorized_one_cpu_attempt_not_started"
    assert value["historical_ledger"]["must_not_modify"] is True
    assert value["resource_pool"]["max_attempts"] == 1
    assert value["resource_pool"]["gpu_peak_mib"] == 0
    assert value["invariants"]["historical_s2_output_reuse_forbidden"] is True
    assert value["execution_controls"]["worker_started"] is False
    assert spec["job_id"] == authorization.JOB_ID
    assert spec["argv"][-4:] == ["--seeds", "4096", "--substeps", "4"]
    assert core_runtime.validate_spec(dict(spec))["resources"]["gpu_peak_mib"] == 0


def test_write_is_immutable(tmp_path: Path) -> None:
    auth = tmp_path / "authorization.json"
    spec = tmp_path / "job.json"
    value, job = authorization.write(auth, spec)
    assert json.loads(auth.read_text()) == value
    assert json.loads(spec.read_text()) == job
    with pytest.raises(FileExistsError, match="immutable F3 row30 Core authorization"):
        authorization.write(auth, spec)
