from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts.r3_f4_3d_head_on import (
    OBSERVATION_POINTS,
    REQUESTED_FORCE_MK,
    RESOLUTIONS,
    _force_summary,
    _measure_summary,
    _parse_summary_count,
    _pointsdef,
    _run_tag,
    configure_definition,
    parse_generated_particle_mks,
    validate_gpu_indices,
)


LAB = Path(__file__).resolve().parents[1]


def test_configure_definition_isolates_explicit_time_window(tmp_path):
    source = tmp_path / "source.xml"
    target = tmp_path / "isolated" / "configured.xml"
    source.write_text(
        """<?xml version='1.0'?>
<case><execution><parameters>
<parameter key='TimeMax' value='0.55'/>
<parameter key='TimeOut' value='0.05'/>
</parameters></execution></case>
"""
    )

    record = configure_definition(source, target, tmax_s=0.3, tout_s=0.01)

    assert record["dimension"] == "3D"
    assert record["requested_compute_forces_mk"] == REQUESTED_FORCE_MK
    assert record["changed_parameters"] == {"TimeMax": "0.3", "TimeOut": "0.01"}
    assert "value=\"0.3\"" in target.read_text()
    assert "value=\"0.01\"" in target.read_text()
    assert "value='0.55'" in source.read_text()


def test_resolution_points_and_run_tags_are_explicit():
    assert RESOLUTIONS == {"coarse": 0.04, "medium": 0.03, "fine": 0.02}
    assert len(OBSERVATION_POINTS) == 7
    assert _pointsdef(OBSERVATION_POINTS[:2]) == (
        "pt=0.23:0.2:0.33,pt=0.97:0.2:0.33"
    )
    assert _run_tag("fine", 0.55, 0.01) == "fine__tmax-0p55__tout-0p01"
    assert _run_tag("fine", 0.3, 0.01) != _run_tag("fine", 0.55, 0.01)


def test_gpu_validation_rejects_non_allowlisted_indices():
    policy = validate_gpu_indices([4, 5])
    assert set(policy["allowed_gpu_indices"]) >= {4, 5}
    assert policy["gpu_uuids"]["4"].startswith("GPU-")
    with pytest.raises(ValueError, match="physical allowlist"):
        validate_gpu_indices([0])


def test_generated_particle_mapping_exposes_effective_mk(tmp_path):
    path = tmp_path / "generated.xml"
    path.write_text(
        """<?xml version='1.0'?>
<case><execution><particles mkboundfirst='17' mkfluidfirst='1'>
<fixed mkbound='0' mk='17' count='20'/>
<fluid mkfluid='0' mk='1' count='3'/>
<fluid mkfluid='1' mk='2' count='4'/>
</particles></execution></case>
"""
    )
    mapping = parse_generated_particle_mks(path)
    assert mapping["effective_boundary_mks"] == [17]
    assert mapping["effective_fluid_mks"] == [1, 2]
    assert _parse_summary_count("Fluid....: 2,640", "Fluid") == 2640
    assert _parse_summary_count("Total particles: 4,181", "Total particles") == 4181


def test_measure_and_force_summaries_parse_3d_outputs(tmp_path):
    pressure = tmp_path / "fixed_points_Press.csv"
    pressure.write_text(
        " ;Pos X/Y/Z [m]:;0.6;0.2;0.33\n"
        "Part;Time [s];Press_0 [Pa];Press_1 [Pa]\n"
        "0;0;0;0\n1;0.01;100;-200\n"
    )
    summary = _measure_summary(pressure, ["p0", "p1"])
    assert summary["rows"] == 2
    assert summary["issues"] == []
    assert summary["peaks"][1]["peak_signed"] == -200

    velocity = tmp_path / "fixed_points_Vel.csv"
    velocity.write_text(
        "Part;Time [s];Vel_0.x [m/s];Vel_0.y [m/s];Vel_0.z [m/s]\n"
        "0;0;0;0;0\n1;0.01;3;4;0\n"
    )
    vector = _measure_summary(velocity, ["p0"], components=3)
    assert vector["peaks"][0]["peak_speed"] == pytest.approx(5.0)

    force = tmp_path / "force.csv"
    force.write_text(
        "Part;Time [s];Np;ForceFluid.x [N];ForceFluid.y [N];ForceFluid.z [N];ForceFluid [N]\n"
        "0;0;10;0;0;0;0\n1;0.01;10;1;2;3;4\n"
    )
    force_result = _force_summary(force)
    assert force_result["peak_force_abs_n"] == pytest.approx(4.0)
    assert force_result["peak_force_vector_n"] == [1.0, 2.0, 3.0]


def test_candidate_report_contract_is_explicit(tmp_path):
    # This is intentionally a no-run report contract check.  It avoids making
    # unit tests depend on the GPU binaries while ensuring the persisted shape
    # retains candidate-only semantics and the requested force target.
    report = {
        "acceptance_status": "candidate_observations_only",
        "formal_release_authorized": False,
        "observation_contract": {"compute_forces_requested_mk": REQUESTED_FORCE_MK},
        "resolution_policy": {"candidate_ladder_m": RESOLUTIONS},
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    loaded = json.loads(path.read_text())
    assert loaded["acceptance_status"] == "candidate_observations_only"
    assert loaded["formal_release_authorized"] is False
    assert loaded["observation_contract"]["compute_forces_requested_mk"] == 10
