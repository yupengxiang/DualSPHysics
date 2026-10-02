"""Tests for the actual floor-safe native exclusion CPU evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "handoff_20261003/rv4_floorsafe_postprocess_v2/rv4-floorsafe-result-sidecar-v1.json"


def test_sidecar_binds_terminal_official_partvtkout_and_preserves_unknown_fate():
    result = json.loads(SIDECAR.read_text(encoding="utf-8"))
    assert result["runtime_receipt"]["status"] == "completed"
    assert result["runtime_receipt"]["returncode"] == 0
    assert result["verdict"]["official_partvtkout_completed"] is True
    assert result["verdict"]["all_native_exclusions_remain_unknown"] is True
    assert result["verdict"]["moving_boundary_exclusion_sum_zero"] is True
    assert result["verdict"]["physical_spill_claim"] == "none"
    assert result["verdict"]["q_n_status"] == "not_assessed"
    by_background = {case["background"]: case for case in result["cases"]}
    assert by_background["CENTER"]["timeline"]["NpOut_sum"] == 2185
    assert by_background["CENTER"]["motive_totals"] == {"1": 2184, "2": 1}
    assert by_background["OFFSET"]["timeline"]["NpOut_sum"] == 2158
    assert by_background["OFFSET"]["motive_totals"] == {"1": 2158}
    assert all(case["record_count"] == case["timeline"]["NpOut_sum"] for case in by_background.values())
