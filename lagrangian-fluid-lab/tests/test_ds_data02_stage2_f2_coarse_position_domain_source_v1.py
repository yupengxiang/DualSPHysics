from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_position_domain_source_v1.py"


def module():
    spec = importlib.util.spec_from_file_location("f2_position_domain_source_v1_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _xml():
    return {
        "drawboxes": [
            {"role": {"kind": "bound", "mk": "2"}, "boxfill": "bottom", "low_m": [-1.0, -1.0, -0.2], "high_m": [0.5, 1.0, 0.0]},
        ],
        "static_bottom_reference_z_m": -0.2,
    }


def _run_out():
    return {
        "map_real_pos": {
            "border": {"min": [-0.9, -0.9, -0.1], "max": [0.9, 0.9, 0.9]},
            "final": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
        },
        "rhop_out": {"RhopOutMin": 700.0, "RhopOutMax": 1300.0},
    }


def _row(idp, position, *, density=1000.0, mk=1):
    return {
        "idp": idp,
        "motive": "position",
        "position_m": list(position),
        "density_kg_m3": density,
        "mk": mk,
        "saved_record_time_s": 1.0,
        "saved_record_bracket_s": [0.9, 1.0],
    }


def test_classify_rows_uses_source_inclusive_upper_and_strict_lower_predicates():
    loaded = module()
    result = loaded.classify_rows(
        [
            _row(1, [1.0, 0.0, 0.0]),  # exact upper face: x >= max is excluded
            _row(2, [-1.0001, 0.0, 0.0]),  # below lower face: x < min is excluded
        ],
        _run_out(),
        _xml(),
    )
    assert result["map_final_violation_count"] == 2
    assert result["map_side_counts"] == {"x_high": 1, "x_low": 1}
    assert result["geometry_aabb_inside_count"] == 0
    assert result["physical_fate"] == "UNKNOWN"
    assert result["particles"][0]["map_final_violations"][0]["predicate"] == "x >= MapRealPosMax.x"


def test_classify_rows_keeps_exact_lower_face_inside_map():
    loaded = module()
    with pytest.raises(loaded.EvidenceError, match="does not violate MapRealPos"):
        loaded.classify_rows([_row(1, [-1.0, 0.0, 0.0])], _run_out(), _xml())


def test_classify_rows_rejects_density_outside_rhop_window():
    loaded = module()
    with pytest.raises(loaded.EvidenceError, match="outside density window"):
        loaded.classify_rows([_row(1, [1.01, 0.0, 0.0], density=699.9)], _run_out(), _xml())


def test_repair_plan_is_numerical_only_and_preserves_mass_gate():
    loaded = module()
    diagnostic = {
        "map_max_excursion_m": {
            "x_low": 0.0002,
            "x_high": 0.0003,
            "y_low": 0.0,
            "y_high": 0.00001,
            "z_low": 0.00004,
            "z_high": 0.0,
        }
    }
    result = loaded.repair_plan(_run_out(), diagnostic, {"simulationdomain": {"numeric": "unchanged"}})
    assert result["status"] == "PREREGISTERED_NOT_RUN"
    assert result["margin_by_axis_m"] == {"x": 0.0006, "y": 0.0001, "z": 0.0001}
    assert "initial generated BI4 and motion file" in result["hold_fixed"]
    assert "whole-initial XML mass screen remains frozen at 0.003" in result["readout"]
    assert result["scientific_qualification"] == {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_source_evidence_binds_official_predicate_files():
    loaded = module()
    evidence = loaded.source_evidence(Path("/home/jade/Projects/DualSPHysics"))
    assert evidence["repository_commit"]
    assert evidence["compiled_binary_source_link"] == "UNKNOWN_UNPROVEN"
    assert evidence["files"]["position_predicate"]["binding"]["sha256"]
    assert any(item["needle"] == "dx>=MapRealSize.x" for item in evidence["files"]["position_predicate"]["locations"])
