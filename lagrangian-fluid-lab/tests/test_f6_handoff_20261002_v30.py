from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v30.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v30_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_domain_failure_is_moving_minus_x_only():
    evidence = json.loads(MODULE.OUTPUT.read_text(encoding="utf-8"))
    failure = evidence["failure"]
    assert failure["returncode"] == 1
    assert failure["moving_count"] == failure["boundary_count"] == 3135
    assert failure["fixed_count"] == failure["floating_count"] == 0
    assert failure["error_vtk"]["all_x_equal"] is True
    assert failure["error_vtk"]["bounds_m"]["max"][0] < 0.0


def test_repair_bounds_cover_measured_sweep_and_preserve_recipe():
    evidence = json.loads(MODULE.OUTPUT.read_text(encoding="utf-8"))
    envelope = evidence["motion_envelope"]
    repair = evidence["repair"]
    assert envelope["displacement_m"] == [-0.043782, 0.043782]
    assert envelope["moving_swept_x_m"] == [-0.043782, 0.363782]
    assert repair["candidate_domain_x_m"] == {"x_min_m": -0.2, "x_max_m": 5.0}
    assert repair["candidate_margin_to_moving_sweep_m"][0] > 0.15
    assert repair["candidate_margin_to_initial_generated_bounds_m"] == [0.2, 0.20000000000000018]
    assert "change_only" in repair
    assert evidence["qualification_claim"] == "none"
