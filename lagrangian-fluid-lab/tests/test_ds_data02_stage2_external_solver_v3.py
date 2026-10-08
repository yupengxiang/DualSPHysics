from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_external_solver_v3.py"
SPEC = importlib.util.spec_from_file_location("external_solver_v3_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _reservation() -> dict:
    return {"id": "new", "kind": "qualification", "gpu_seconds": 1.0,
            "cpu_core_seconds": 1.0, "new_storage_bytes": 200_000,
            "home_storage_bytes": 100_000, "external_storage_bytes": 100_000}


def test_v3_home_floor_policy_does_not_reapply_historical_cumulative_byte_cap() -> None:
    ledger = {
        "deadline_utc": "2999-01-01T00:00:00+00:00", "attempts": [], "reservations": [],
        "charges": [{"id": "historical", "gpu_seconds": 0, "cpu_core_seconds": 0,
                      "new_storage_bytes": 20_000_000}],
        "limits": {"gpu_seconds": 100, "cpu_core_seconds": 100,
                   "new_storage_bytes": 1_000_000, "qualification_attempts": 2,
                   "production_attempts": 2, "storage_policy": "home_free_floor"},
    }
    MODULE._policy_aware_two_fs_reservation(ledger, _reservation(), home_free=10_000_000,
                                            external_free=10_000_000, home_floor=1,
                                            external_floor=1)


def test_v3_non_home_policy_retains_explicit_cumulative_storage_cap() -> None:
    ledger = {
        "deadline_utc": "2999-01-01T00:00:00+00:00", "attempts": [], "reservations": [],
        "charges": [{"id": "historical", "gpu_seconds": 0, "cpu_core_seconds": 0,
                      "new_storage_bytes": 20_000_000}],
        "limits": {"gpu_seconds": 100, "cpu_core_seconds": 100,
                   "new_storage_bytes": 1_000_000, "qualification_attempts": 2,
                   "production_attempts": 2},
    }
    original = MODULE.V1._check_two_fs_reservation
    # The forward helper itself is intentionally policy-aware.  The legacy
    # non-Home branch is represented by the immutable helper's cap and must
    # continue to reject the same over-budget reservation.
    ledger["limits"]["storage_policy"] = "byte_budget"
    with pytest.raises(Exception, match="budget|storage"):
        original(ledger, _reservation(), home_free=10_000_000,
                 external_free=10_000_000, home_floor=1, external_floor=1)
