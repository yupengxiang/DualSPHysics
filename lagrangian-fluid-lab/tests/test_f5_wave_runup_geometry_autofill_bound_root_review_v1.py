from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_root_review_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_autofill_bound_root_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v4_review_binds_v3_failure_and_official_autofill_example():
    proposal, prior, official = MODULE._verify_prior()
    assert prior["geometry_repair"]["blocks_endpoint_inside_count"] == 1
    assert official["chrono"]["sha256"]
    assert proposal["qualification_claim"] == "none"


def test_v4_review_is_preflight_only_and_zero_credit():
    review = MODULE.verify(MODULE.OUTPUT)
    decision = review["review_decision"]
    assert decision["authorized_cpu_native_preflight"] is True
    assert decision["exactly_one_preflight"] is True
    assert decision["authorized_solver"] is False
    assert decision["authorized_gpu"] is False
    assert review["matrix_credit"] == 0
    assert review["fresh_identity"]["case_id"].endswith("geomrepair_v4")


def test_v4_recipe_keeps_fixed_time_and_geometry():
    recipe = MODULE.verify(MODULE.OUTPUT)["recipe"]
    assert recipe["preserved_parameters"]["time_max_s"] == 16.0
    assert recipe["preserved_parameters"]["output_dt_s"] == 0.02
    assert any("autofill=true" in command for command in recipe["commands_in_order"])
    assert recipe["physical_boundary_policy"].startswith("one official autofill draw")
