from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import f3_material_row30_resource_preflight_v2 as preflight


def _inputs():
    return {
        "environment": {
            "available_cpu_count": 128,
            "load_average_1_5_15_min": [144.0, 140.0, 138.0],
            "available_ram_bytes": 200 * 1024**3,
            "filesystem_free_bytes": 8 * 1024**3,
        },
        "active_workers": [{"pid": 123, "process_state": "R"}],
        "scheduler_active_count": 1,
        "ledger": {
            "conservative_expiry_utc": "2026-09-16T00:00:00+00:00",
            "cpu_core_hours_upper_bound": 912.0,
            "material_configurations_used": 16,
        },
        "limits": {"cpu_core_hours": 896.0, "materials": 32},
        "proposed_cpu_core_hours": 11.9,
        "now": datetime(2026, 9, 23, tzinfo=timezone.utc),
    }


def test_resource_assessment_blocks_active_worker_load_and_expired_budget() -> None:
    blockers = preflight.assess_blockers(**_inputs())
    assert any("host load" in item for item in blockers)
    assert any("row-30 worker is already active" in item for item in blockers)
    assert any("scheduler has" in item for item in blockers)
    assert any("expired" in item for item in blockers)
    assert any("CPU core-hour cap" in item for item in blockers)


def test_resource_assessment_allows_only_the_preflight_when_admission_is_clear() -> None:
    inputs = _inputs()
    inputs["environment"]["load_average_1_5_15_min"] = [80.0, 81.0, 82.0]
    inputs["active_workers"] = []
    inputs["scheduler_active_count"] = 0
    inputs["ledger"]["conservative_expiry_utc"] = "2026-10-01T00:00:00+00:00"
    inputs["ledger"]["cpu_core_hours_upper_bound"] = 100.0
    assert preflight.assess_blockers(**inputs) == []


def test_current_build_short_circuits_large_source_hash_when_blocked() -> None:
    value = preflight.build(
        environment_probe=lambda: _inputs()["environment"],
        process_probe=lambda: _inputs()["active_workers"],
    )
    assert value["status"] == "blocked_no_worker_authorized"
    assert value["resource_assessment"]["source_identity"]["source_hash_revalidation_performed"] is False
    assert value["resource_assessment"]["source_identity"]["prepared_hash_revalidation_performed"] is False
    assert value["worker_launch_authorized"] is False
    assert value["execution_controls"]["material_worker_started"] is False
    assert value["execution_controls"]["queue_mutation"] == 0


def test_write_is_one_shot_and_does_not_authorize_a_worker(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    value = preflight.write(target)
    assert json.loads(target.read_text(encoding="utf-8")) == value
    assert value["worker_launch_authorized"] is False
    with pytest.raises(FileExistsError, match="immutable row30 resource preflight v2"):
        preflight.write(target)
