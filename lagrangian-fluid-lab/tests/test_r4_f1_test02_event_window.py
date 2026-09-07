"""Contract tests for the bounded Test 02 event-window follow-up."""

from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts" / "r4_f1_test02_event_window.py"
SPEC = importlib.util.spec_from_file_location("r4_f1_event_window", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_event_window_is_explicitly_separate_from_full_anchor():
    assert MODULE.TMAX_S == 2.2
    assert MODULE.TOUT_S == 0.005
    assert list(MODULE.RESOLUTIONS) == ["coarse", "medium", "fine"]
    assert [record["dp_m"] for record in MODULE.records()] == [0.04, 0.03, 0.02]


def test_records_use_disjoint_allowed_gpu_assignments():
    records = MODULE.records()
    assert [record["gpu"] for record in records] == [4, 5, 6]
    assert len({record["gpu"] for record in records}) == len(records)
    assert all(record["case_id"].startswith("R4_F1_Test02_event_") for record in records)


def test_peak_uses_absolute_value_but_preserves_signed_value():
    import numpy as np

    result = MODULE._peak(np.asarray([0.0, 0.1]), np.asarray([-3.0, 2.0]))
    assert result == {"value_pa": -3.0, "time_s": 0.0}
