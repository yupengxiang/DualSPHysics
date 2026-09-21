from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-cell0-v2/prepared.json"


def test_h1_mdbc_cpu_preflight_is_passed_but_unqualified() -> None:
    value = json.loads(ARTIFACT.read_text())
    assert value["schema"] == "core.f2.static_full_cup.boundary_repair_prepared.v1"
    assert value["repair_id"] == "F2_static_full_cup_boundary_mdbc_h1_v1"
    assert value["preflight_pass"] is True
    assert value["qualified"] is False
    assert value["qualification_claim"].startswith("none;")
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated"):
        assert value[key] is False
    assert value["checks"] == {
        "generated_fluid_particle_count_unchanged": True,
        "native_fluid_particle_count_unchanged": True,
        "native_ids_unique": True,
        "native_arrays_finite": True,
        "mdbc_normals_present": True,
        "mdbc_normals_shape_matches_boundary": True,
        "mdbc_normals_nonzero_finite": True,
        "mass_representation_gate": True,
    }


def test_h1_definition_binds_single_boundary_hypothesis() -> None:
    value = json.loads(ARTIFACT.read_text())
    audit = value["definition_audit"]
    assert audit["fluid_and_continuum_geometry_unchanged"] is True
    assert audit["mass_rescaling"] is False
    assert audit["changed_numeric_boundary"]["Boundary"] == 2
    assert audit["normal_geometry"]["boundary_box_count"] == 3
    assert audit["normal_geometry"]["shapeout"] == "hdp"
    assert Path(audit["definition"]).is_file()
    assert value["native_initial"]["normal_count"] == value["native_initial"]["boundary_particles"]
    assert value["native_initial"]["zero_boundary_normals"] == 0
