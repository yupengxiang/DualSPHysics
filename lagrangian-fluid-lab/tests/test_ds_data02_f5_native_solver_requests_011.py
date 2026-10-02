from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_native_solver_requests_011.py"
SPEC = importlib.util.spec_from_file_location("f5_native_solver_requests_011", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_domain_repair_changes_only_execution_domain() -> None:
    source = MODULE.DATA_ROOT / (
        "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-runup_return-"
        "dp005-cellcentre-commensurate-010/F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010.xml"
    )
    original = source.read_text(encoding="utf-8")
    repaired = MODULE.replace_domain(original)
    assert MODULE.canonical_without_domain(original) == MODULE.canonical_without_domain(repaired)
    assert MODULE._domain_from_xml(source) == ((-1.15, -0.84, -0.30), (11.0, 0.84, 1.45))
    assert all(f'{axis}="{MODULE.q(value)}"' in repaired for axis, value in zip("xyz", MODULE.DOMAIN_MIN))
    assert all(f'{axis}="{MODULE.q(value)}"' in repaired for axis, value in zip("xyz", MODULE.DOMAIN_MAX))


@pytest.mark.parametrize(
    ("key", "total", "fluid", "threads", "wall", "storage_gib"),
    [
        ("runup_dp005", 94790, 18816, 2, 1800, 7),
        ("weir_dp005", 96558, 18816, 2, 1800, 7),
        ("runup_dp00125", 4040985, 1204224, 4, 14400, 195),
        ("weir_dp00125", 4070667, 1204224, 4, 14400, 197),
    ],
)
def test_request_cost_contract_is_based_on_actual_native_particle_count(
    key: str, total: int, fluid: int, threads: int, wall: int, storage_gib: int
) -> None:
    spec = MODULE.CASE_SPECS[key]
    assert spec["total_particles"] == total
    assert spec["fluid_particles"] == fluid
    assert spec["cpu_threads"] == threads
    assert spec["max_wall_seconds"] == wall
    estimate = MODULE._estimated_storage(total)
    assert estimate["expected_native_frames"] == 801
    assert estimate["rounded_storage_bytes"] == storage_gib * 1024**3


def test_control_is_full_16_second_641_row_input() -> None:
    for spec in MODULE.CASE_SPECS.values():
        motion = MODULE.FAMILY_ROOT / "definitions" / spec["motion"]
        stats = MODULE._motion_stats(motion)
        assert stats["row_count"] == 641
        assert stats["time_start_s"] == pytest.approx(0.0)
        assert stats["time_end_s"] == pytest.approx(16.0)
        assert stats["full_window"] is True


def test_case_matrix_is_two_mechanisms_at_two_new_resolutions() -> None:
    assert set(MODULE.CASE_SPECS) == {"runup_dp005", "weir_dp005", "runup_dp00125", "weir_dp00125"}
    assert {spec["mechanism_id"] for spec in MODULE.CASE_SPECS.values()} == {"runup_return", "weir_pair"}
    assert {spec["resolution_id"] for spec in MODULE.CASE_SPECS.values()} == {"dp005", "dp00125"}


def test_source_generated_and_domain_reference_are_external_immutable_assets() -> None:
    for key, spec in MODULE.CASE_SPECS.items():
        paths = MODULE.case_paths(key, spec)
        assert paths["generated_bi4"].is_file()
        assert paths["generated_xml"].is_file()
        assert paths["gencase_receipt"].is_file()
        assert paths["partvtk_report"].is_file()
        assert paths["domain_reference_xml"].is_file()
        assert paths["union_coverage"].is_file()
