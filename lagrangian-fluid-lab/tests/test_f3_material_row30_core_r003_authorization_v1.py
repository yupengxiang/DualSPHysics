from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_core_r003_authorization_v1 as r003


def test_r003_uses_closed_r002_throughput_for_full_window_budget() -> None:
    authorization, spec = r003.build()
    measure = authorization["closed_r002_throughput_evidence"]
    assert measure["measured_completed_intervals"] == 5
    assert measure["linear_full_835_estimate_seconds"] > 12 * 3600
    assert authorization["resource_pool"]["cpu_cores"] == 1
    assert authorization["resource_pool"]["timeout_seconds"] == 16 * 3600
    assert spec["resources"]["cpu_cores"] == 1
    assert spec["argv"][-2:] == ["--stop-after", "835"]


def test_r003_write_is_immutable(tmp_path: Path) -> None:
    auth_path, spec_path = tmp_path / "authorization.json", tmp_path / "job.json"
    authorization, spec = r003.write(auth_path, spec_path)
    assert json.loads(auth_path.read_text()) == authorization
    assert json.loads(spec_path.read_text()) == spec
    with pytest.raises(FileExistsError, match="immutable F3 row30 r003 authorization"):
        r003.write(auth_path, spec_path)
