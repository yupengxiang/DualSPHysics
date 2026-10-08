from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_runtime_v9.py"
SPEC = importlib.util.spec_from_file_location("runtime_v9_split_storage_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _ledger(*rows: dict) -> dict:
    return {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "limits": {
            "gpu_seconds": 0.0,
            "cpu_core_seconds": 10_000.0,
            "new_storage_bytes": 10_000,
            "qualification_attempts": 2,
            "production_attempts": 2,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 500,
            "home_path": "/home/jade",
        },
        "charges": [],
        "reservations": list(rows),
        "attempts": [],
    }


def _reservation(*, home: int, external: int, external_path: str = "/var/tmp") -> dict:
    return {
        "id": "F7/manufactured-v9/split",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "cpu_core_seconds": 1,
        "gpu_seconds": 0,
        "new_storage_bytes": home + external,
        "home_storage_bytes": home,
        "external_storage_bytes": external,
        "external_filesystem": external_path,
    }


def test_explicit_external_reservation_does_not_consume_home_floor() -> None:
    # The old v6/base check would subtract 200 external bytes from Home and
    # reject: 600 - 200 - 100 < 500.  v9 checks only the explicit Home 100.
    ledger = _ledger({"id": "old-f1", "kind": "cpu", "cpu_threads": 1,
                      "cpu_core_seconds": 1, "gpu_seconds": 0,
                      "new_storage_bytes": 200, "home_storage_bytes": 0,
                      "external_storage_bytes": 200})
    MODULE._active_storage_scope = {
        "home_path": "/home/jade", "external_filesystem": "/var/tmp",
        "external_min_free_bytes": 1,
    }
    reservation = _reservation(home=100, external=20)
    MODULE._check_split_reservation(ledger, reservation, 0, available_bytes=600)
    assert reservation["storage_accounting"]["existing_reservations_home_bytes"] == 0
    assert reservation["storage_accounting"]["existing_reservations_external_bytes"] == 200


def test_legacy_unsplit_reservation_is_conservative_home_and_can_reject() -> None:
    ledger = _ledger({"id": "old-legacy", "kind": "cpu", "cpu_threads": 1,
                      "cpu_core_seconds": 1, "gpu_seconds": 0,
                      "new_storage_bytes": 200})
    MODULE._active_storage_scope = {"home_path": "/home/jade"}
    with pytest.raises(RuntimeError, match="Home free-space floor"):
        MODULE._check_split_reservation(ledger, _reservation(home=100, external=0), 0,
                                        available_bytes=600)


def test_external_storage_requires_distinct_device_and_matching_total() -> None:
    ledger = _ledger()
    MODULE._active_storage_scope = {"home_path": "/home/jade", "external_filesystem": "/home/jade"}
    with pytest.raises(RuntimeError, match="distinct device"):
        MODULE._check_split_reservation(ledger, _reservation(home=10, external=20,
                                                              external_path="/home/jade"),
                                        0, available_bytes=600)
    with pytest.raises(ValueError, match="must sum"):
        MODULE._storage_scope({"estimated_storage_bytes": 100,
                               "storage_scope": {"home_storage_bytes": 90,
                                                  "external_storage_bytes": 20,
                                                  "external_filesystem": "/var/tmp"}})


def test_default_scope_preserves_legacy_home_semantics() -> None:
    scope = MODULE._storage_scope({"estimated_storage_bytes": 17})
    assert scope["home_storage_bytes"] == 17
    assert scope["external_storage_bytes"] == 0
    assert scope["legacy_scope_defaulted"] is True
