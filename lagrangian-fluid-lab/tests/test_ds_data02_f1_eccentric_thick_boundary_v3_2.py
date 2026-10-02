from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_thick_boundary_v3_2 as thick_v32  # noqa: E402


@pytest.mark.parametrize("token", ["DP005", "DP003333333333333333"])
def test_v32_preserves_complete_support_bounds(token):
    spec = thick_v32._resolution(token)
    low, high = thick_v32._native_support_bounds(spec.dp)
    assert low.tolist() == pytest.approx([-2.5 * spec.dp] * 3)
    assert high[2] == pytest.approx(0.45 - 0.5 * spec.dp)


def test_v32_summary_tolerance_covers_known_fine_xml_rounding():
    # GenCase's fine _summary prints .44833 for the decoded .4483333333 bound.
    tolerance = 0.5e-5 + 2e-8
    assert abs(0.4483333333333333 - 0.44833) <= tolerance
    assert tolerance < 1e-4
