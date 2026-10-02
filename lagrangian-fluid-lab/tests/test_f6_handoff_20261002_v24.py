from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v24.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v24_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v24_scopes_four_domain_xy_coarse_fine_cases():
    rows = [(mechanism, resolution, MODULE._cid(mechanism, resolution)) for mechanism in MODULE.MECHANISMS for resolution in MODULE.RESOLUTIONS]
    assert len(rows) == 4
    assert all("DOMAIN_XY_REPAIR_02" in case_id for _, _, case_id in rows)
    assert {resolution for _, resolution, _ in rows} == {"coarse", "fine"}


def test_v24_preserves_medium_as_reuse_only():
    assert "medium" not in MODULE.RESOLUTIONS
    assert "medium" not in [MODULE._cid(mechanism, resolution) for mechanism in MODULE.MECHANISMS for resolution in MODULE.RESOLUTIONS]


def test_v24_rotation_to_xyzw_and_native_fit_contract():
    rotation = np.eye(3)
    assert np.allclose(MODULE._quat_from_rotation(rotation), [0.0, 0.0, 0.0, 1.0])
    angle = np.pi / 2.0
    rotation = np.asarray([[1.0, 0.0, 0.0], [0.0, np.cos(angle), -np.sin(angle)], [0.0, np.sin(angle), np.cos(angle)]])
    quaternion = MODULE._quat_from_rotation(rotation)
    assert np.allclose(np.abs(quaternion), [np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)], atol=1.0e-12)


def test_v24_request_policy_has_no_gpu_launch():
    assert MODULE.VENV_PYTHON.as_posix().endswith(".venv/bin/python")
    assert MODULE.POST_ROOT.name == "postprocessing_007"

