from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_f1_eccentric_thick_boundary_v3_1 as thick_v31  # noqa: E402


@pytest.mark.parametrize("token", ["DP005", "DP003333333333333333"])
def test_domain_bound_includes_internal_obstacle_top_support(token):
    spec = thick_v31._resolution(token)
    low, high = thick_v31._native_support_bounds(spec.dp)
    assert low == pytest.approx(np.asarray([-2.5 * spec.dp] * 3))
    assert high[0] == pytest.approx(1.6 + 2.5 * spec.dp)
    assert high[1] == pytest.approx(0.67 + 2.5 * spec.dp)
    # The internal obstacle top support is inside z=.45 and its nearest row
    # is half a dp below the physical top, so it controls the global z max.
    assert high[2] == pytest.approx(0.45 - 0.5 * spec.dp)
    assert high[2] > 0.4 + 2.5 * spec.dp


@pytest.mark.parametrize("token", ["DP005", "DP003333333333333333"])
def test_design_preserves_physical_hash_and_v31_identity(tmp_path, token):
    manifest = thick_v31.design(tmp_path, token, thick_v31.DEFAULT_TEMPLATE)
    spec = thick_v31._resolution(token)
    case = manifest["case"]
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))
    assert case["case_id"] == spec.case_id
    assert manifest["variant_id"] == "003-domain-bound-fix"
    assert metadata["physical_binding"]["physical_hash"] == "bb449a2c1d34c75ea6f94d6f5e9124c4eedf0f5b1667ec5225700e6bf11495b5"
    assert metadata["numeric_binding"]["native_expected_support_bounds_m"][1] == pytest.approx(thick_v31._native_support_bounds(spec.dp)[1].tolist())
    assert manifest["no_execution_performed_at_design"] is True
