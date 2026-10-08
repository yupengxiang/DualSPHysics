from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_native_source_identity_stats_correction_v2.py"
SPEC = importlib.util.spec_from_file_location("native_source_identity_stats_correction_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_numerical_cause_mapping_is_native_only():
    assert MODULE._numerical_cause("position", 1) == "NATIVE_PARTVTKOUT_POSITION_EXCLUSION"
    assert MODULE._numerical_cause("density", 2) == "NATIVE_PARTVTKOUT_DENSITY_EXCLUSION"
    with pytest.raises(MODULE.CorrectionError, match="motive/code mismatch"):
        MODULE._numerical_cause("density", 1)


def test_stale_and_corrected_family_keys_are_distinct():
    assert MODULE.STALE_FAMILY_MOTIVE == {"F6:density": 51, "F6:position": 199}
    assert MODULE.CORRECTED_FAMILY_MOTIVE == {"F2:position": 1078, "F4:density": 51, "F6:position": 199}
