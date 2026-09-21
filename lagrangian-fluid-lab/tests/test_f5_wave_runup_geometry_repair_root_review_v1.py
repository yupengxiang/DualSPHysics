from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_geometry_repair_root_review_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_geometry_repair_root_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_static_review_binds_official_void_and_autofill_syntax():
    syntax = MODULE._verify_syntax_and_prior_definition()
    assert syntax["template"]["sha256"]
    assert syntax["chrono_example"]["sha256"]
    assert syntax["void_literal"] == "<setmkvoid /> before each transformed autofill STL draw"
    assert MODULE.OUTPUT.exists()


def test_review_authorizes_only_one_zero_credit_cpu_native_preflight(tmp_path):
    checked = MODULE.verify(MODULE.OUTPUT)
    decision = checked["review_decision"]
    assert decision["authorized_definition_materialization"] is True
    assert decision["authorized_cpu_native_preflight"] is True
    assert decision["exactly_one_preflight"] is True
    for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_matrix"):
        assert decision[key] is False
    assert checked["denominator_rows"] == 15
    assert checked["matrix_credit"] == 0


def test_recipe_preserves_geometry_and_closes_retry_policy():
    recipe = MODULE._recipe()
    assert recipe["identity"] == "F5_geomrepair_v3_explicit_void_precursor"
    assert recipe["preserved_parameters"]["dp_m"] == 0.0075
    assert recipe["preserved_parameters"]["time_max_s"] == 16.0
    assert recipe["preserved_parameters"]["output_dt_s"] == 0.02
    assert any("autofill=true" in command for command in recipe["commands_in_order"])
    review = MODULE.verify(MODULE.OUTPUT)
    assert review["fixed_denominator"]["same_input_retry"] is False
    assert review["execution_controls"]["qualification_credit"] == 0
