from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f6_handoff_20261002_dp020_dp0125.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_dp020_dp0125", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_scope_uses_only_new_finer_resolutions() -> None:
    assert MODULE.MODULE.DP_LADDER == (("dp020", 0.020), ("dp0125", 0.0125))
    assert MODULE.DP_SCOPE_ROOT.name == "dp020_dp0125_cpu_001"
    assert "dp025" not in str(MODULE.DP_SCOPE_ROOT)


def test_rigid_contract_is_fixed_across_the_new_ladder() -> None:
    assert MODULE.MODULE.BODY["mass_kg"] == 128.0
    assert MODULE.BASE.RIGID_CENTER == [2.4, 1.2, 1.08]
    assert MODULE.BASE.RIGID_INERTIA == [8.533333333333335, 8.533333333333335, 13.653333333333336]


def test_scope_preserves_dp025_negative_evidence() -> None:
    assert MODULE.DP025_FAILURE.is_file()
    assert MODULE.DP025_SPATIAL.is_file()
