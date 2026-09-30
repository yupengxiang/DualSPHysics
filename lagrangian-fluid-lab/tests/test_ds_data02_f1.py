"""CPU-only tests for the DS-DATA-02 F1 input contract."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import ds_data02_f1 as f1


def test_official_mothers_are_real_3d_finite_wall_canaries():
    evidence = f1.mother_evidence(strict=True)
    assert len(evidence["mother_cases"]) == 2
    for row in evidence["mother_cases"]:
        actual = row["actual_successful_run"]
        assert actual["solver_dimension"] == "3D"
        assert actual["coordinate_components"] == 3
        assert actual["total_particles"] == actual["fluid_particles"] + actual["fixed_particles"]
        assert actual["finite_wall_faces"] == ["bottom", "left", "right", "front", "back"]
        assert actual["open_top"] is True
        assert actual["frame_count"] == 7
        assert actual["complete_event_evidence"] is False
        assert row["source_definition_sha256"]
        assert row["gencase_log_sha256"]
        assert row["solver_log_sha256"]


def test_reference_definitions_have_two_mechanisms_and_nonuniform_scales(tmp_path: Path):
    result = f1.reference_matrix(tmp_path, strict_source=True)
    assert result["all_preflight"] is True
    assert len(result["matrix"]) == 6
    by_background = {}
    for row in result["matrix"]:
        by_background.setdefault(row["background"], []).append(row)
        assert row["solver_status"] == "not_run"
        assert row["native_evidence"] is None
        assert row["definition_sha256"]
    assert set(by_background) == {"eccentric_obstacle", "asymmetric_dual_channel"}
    assert [row["dp_m"] for row in by_background["eccentric_obstacle"]] == [0.02, 0.015, 0.01]
    assert [row["dp_m"] for row in by_background["asymmetric_dual_channel"]] == [0.02, 0.012, 0.008]
    assert {row["complete_event_window_s"] for row in by_background["eccentric_obstacle"]} == {1.6}
    assert {row["complete_event_window_s"] for row in by_background["asymmetric_dual_channel"]} == {6.0}
    for report in result["preflight"]:
        assert report["status"] == "pass", report
        assert report["solver_invoked"] is False
        assert report["gencase_invoked"] is False
    dual_report = next(
        report
        for report in result["preflight"]
        if "DUAL_NOMINAL_COARSE_Def.xml" in report["definition_path"]
    )
    assert dual_report["checks"]["dual_fillbox_crosses_right_wall"] is True


def test_candidate_registry_is_preregistered_and_resolution_is_not_new_physics(tmp_path: Path):
    result = f1.preregister(tmp_path)
    assert result["independent_physical_case_count"] == 48
    assert result["background_counts"] == {"eccentric_obstacle": 24, "asymmetric_dual_channel": 24}
    assert result["resolution_views_are_not_independent_cases"] is True
    rows = [json.loads(line) for line in Path(result["path"]).read_text().splitlines()]
    assert len(rows) == 48
    assert all(row["status"] == "pre_registered" for row in rows)
    assert all(row["production"] is False for row in rows)
    assert all(row["attempt_id"] is None for row in rows)
    assert all(row["native_hdf5"] is None for row in rows)
    assert {row["paired_background_id"] for row in rows if row["mechanism_id"] == "eccentric_obstacle"} == {
        f"F1_PAIR_{index:02d}" for index in range(1, 25)
    }
    assert {row["paired_background_id"] for row in rows if row["mechanism_id"] == "asymmetric_dual_channel"} == {
        f"F1_PAIR_{index:02d}" for index in range(1, 25)
    }


def test_design_and_shared_runner_requests_remain_unexecuted(tmp_path: Path):
    family = tmp_path / "F1"
    f1.write_family_design(family, strict_source=True)
    request = f1.write_runner_request(family, data_attempt_root=tmp_path / "attempt")
    assert request["resource_guard"]["solver_invoked_by_generator"] is False
    assert request["resource_guard"]["gpu_launch_allowed_here"] is False
    assert request["qualification_claim"] == "none_until_actual_native_receipts"
    cpu = json.loads((family / "gencase_request.json").read_text())
    for key in (
        "family_id",
        "case_id",
        "attempt_id",
        "kind",
        "cpu_task_kind",
        "command",
        "cwd",
        "max_wall_seconds",
        "cpu_threads",
        "estimated_storage_bytes",
        "input_files",
        "worktree_root",
    ):
        assert key in cpu
    assert cpu["kind"] == "cpu"
    assert cpu["cpu_task_kind"] == "gencase"
    assert "{attempt_root}" in cpu["command"][2]
    assert all(Path(path).is_file() for path in cpu["input_files"])
    assert cpu["solver_launch_forbidden"] is True
    dual_cpu = json.loads((family / "gencase_dual_request.json").read_text())
    assert dual_cpu["case_id"] == "F1_REF_DUAL_NOMINAL_COARSE"
    assert dual_cpu["cpu_threads"] == 4
    assert dual_cpu["estimated_storage_bytes"] == 256 * 1024 * 1024
    assert "{attempt_root}" in dual_cpu["command"][2]
    assert all(Path(path).is_file() for path in dual_cpu["input_files"])
    assert dual_cpu["solver_launch_forbidden"] is True
