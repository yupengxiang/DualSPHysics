"""Tests for the additive RV4 same-mother spacing feasibility and requests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "handoff_20261003/rv4_matched_three_dp_init_v1/f2_rv4_matched_three_dp_init_v1.py"
ARTIFACTS = ROOT / "handoff_20261003/rv4_matched_three_dp_init_v1/artifacts"
SPEC = importlib.util.spec_from_file_location("f2_matched_three_dp", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_requested_dp0064_is_blocked_without_changing_frozen_mother():
    record = MODULE.blocked_medium_record()
    assert record["status"] == "blocked_same_mother_integer_grid_incompatible"
    assert record["same_mother_valid"] is False
    assert record["same_continuous_box_integer_lattice"] is False
    assert record["same_three_source_band_integer_lattice"] is False
    assert record["target_particle_count_for_exact_continuum_volume"] == 93750
    assert record["exact_rectangular_population_triples_inside_cup"] == []
    assert record["request_registered"] is False


def test_lawful_candidates_are_exact_three_source_lattices():
    for dp, expected_count, expected_band_count in ((MODULE.Decimal("0.01"), 24576, 8192), (MODULE.Decimal("0.008"), 48000, 16000)):
        result = MODULE.feasibility(dp)
        assert result["same_mother_valid"] is True
        population = MODULE.expected_population(dp)
        assert population["total_particle_count"] == expected_count
        assert population["source_band_particle_count"] == expected_band_count
        assert population["relative_mass_error"] == 0.0


def test_materialized_cases_preserve_rv4_physical_projection_and_controls():
    manifest = json.loads((ARTIFACTS / "rv4-matched-three-dp-init-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "same_mother_cpu_gencase_requests_registered_not_run"
    assert len(manifest["cases"]) == 4
    for case in manifest["cases"]:
        metadata = json.loads(Path(case["metadata"]["path"]).read_text(encoding="utf-8"))
        equality = metadata["rv4_binding"]["physical_projection_equality"]
        assert equality["physical_solids_controls_window_equal"] is True
        assert metadata["physical_geometry_is_unchanged"] is True
        assert metadata["motion_and_control"]["curve_copied_byte_for_byte"] is True
        assert metadata["expected_population"]["expected_lattice_mass_kg"] == 24.576
        request = json.loads(Path(case["request"]["path"]).read_text(encoding="utf-8"))
        assert request["cpu_task_kind"] == "gencase"
        assert request["solver_launch_forbidden"] is True
        assert request["max_wall_seconds"] == 300
        assert request["estimated_storage_bytes"] <= 256 * 1024 * 1024
        assert request["physical_condition_hash"] == metadata["rv4_binding"]["physical_condition_hash"]
        assert request["input_sha256"]


def test_offset_and_center_keep_distinct_finite_receiver_projection():
    rows = {}
    manifest = json.loads((ARTIFACTS / "rv4-matched-three-dp-init-manifest.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        metadata = json.loads(Path(case["metadata"]["path"]).read_text(encoding="utf-8"))
        rows.setdefault(case["background"], metadata["finite_solids"])
    assert rows["CENTER"][1]["low_m"][1] == -0.3
    assert rows["OFFSET"][1]["low_m"][1] == -0.16

