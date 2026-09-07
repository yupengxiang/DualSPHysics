from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.r4_f1_core_preflight import (
    GENCASE,
    LAB,
    PROTOCOL,
    assert_gencase_only,
    case_records,
    controls_match_protocol,
    materialize_definition,
    parse_gencase_log,
)


def test_matrix_is_exactly_the_r4_f1_nine_cell_ladder():
    records = case_records()
    assert len(records) == 9
    assert [item["background_id"] for item in records] == [
        "plain_dam_break",
        "plain_dam_break",
        "plain_dam_break",
        "center_obstacle",
        "center_obstacle",
        "center_obstacle",
        "twin_obstacle_split_remerge",
        "twin_obstacle_split_remerge",
        "twin_obstacle_split_remerge",
    ]
    assert [item["level"] for item in records] == [
        "coarse", "medium", "fine",
        "coarse", "medium", "fine",
        "coarse", "medium", "fine",
    ]
    assert [item["dp_m"] for item in records[:3]] == [0.035, 0.024, 0.014]
    assert all(item["time_max_s"] == 1.5 for item in records)
    assert all(item["time_out_s"] == 0.001 for item in records)


def test_materialized_definition_is_isolated_and_has_explicit_dbc_protocol(tmp_path, monkeypatch):
    # Redirect only the private definition root used by this module; source
    # files under cases/F1 must remain byte-identical.
    import scripts.r4_f1_core_preflight as module

    monkeypatch.setattr(module, "CASE_ROOT", tmp_path / "cases")
    record = case_records()[0]
    source = Path(record["source_definition"])
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    prepared = materialize_definition(record)
    controls = prepared["candidate_controls"]
    assert controls["dp_m"] == 0.035
    assert controls["time_max_s"] == 1.5
    assert controls["time_out_s"] == 0.001
    assert controls["step_algorithm"] == 1
    assert controls["verlet_steps"] == 40
    assert controls["boundary_parameter"] == 1
    assert controls["boundary_formulation"] == "DBC"
    assert Path(prepared["candidate_path"]).is_file()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_before
    assert Path(prepared["candidate_path"]).resolve() != source.resolve()


def test_gencase_guard_rejects_solver_and_gpu_commands():
    valid = [str(GENCASE), "/tmp/candidate", "/tmp/prefix", "-save:all"]
    assert_gencase_only(valid)
    for forbidden in ("DualSPHysics5.4_linux64", "nvidia-smi", "nvcc"):
        try:
            assert_gencase_only([str(GENCASE), forbidden])
        except AssertionError:
            pass
        else:
            raise AssertionError(f"forbidden command was accepted: {forbidden}")


def test_gencase_log_parser_records_particle_counts_and_finite_completion(tmp_path):
    log = tmp_path / "gencase.stdout.log"
    log.write_text(
        "Points loaded: 123\n"
        "Fixed....: 80\n"
        "Fluid....: 43\n"
        "Total particles: 123 (bound=80 (fx=80 mv=0 ft=0) fluid=43)\n"
        "X range: 0 to 1.2 [m]\n"
        "Finished execution (code=0).\n"
    )
    parsed = parse_gencase_log(log)
    assert parsed["total_particles"] == 123
    assert parsed["boundary_particles"] == 80
    assert parsed["fluid_particles"] == 43
    assert parsed["finished_code_0"] is True
    assert parsed["x_range_m"] == [0.0, 1.2]


def test_protocol_declares_only_structural_preflight():
    assert PROTOCOL["boundary_formulation"] == "DBC"
    assert PROTOCOL["step_algorithm"] == 1
    assert PROTOCOL["verlet_steps"] == 40
    assert PROTOCOL["time_out_s"] == 0.001
    assert controls_match_protocol(
        {
            "_expected_dp_m": 0.035,
            "dp_m": 0.035,
            "time_max_s": 1.5,
            "time_out_s": 0.001,
            "step_algorithm": 1,
            "verlet_steps": 40,
            "boundary_parameter": 1,
            "boundary_formulation": "DBC",
        }
    ) == {
        "dp": True,
        "time_max": True,
        "time_out": True,
        "step_algorithm": True,
        "verlet_steps": True,
        "boundary": True,
    }
