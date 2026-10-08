#!/usr/bin/env python3
"""Close continuous-owner scales for the F2-S1, F3-S2 and F6-S2 observers.

This is a forward, metadata-only sidecar.  It consumes the already frozen v1
observer contracts and the small owner JSONs that those contracts reference;
it does not open the generated XML, BI4, native Part, H5 or solver output.

The sidecar keeps three quantities separate when they differ:

* the continuous owner geometry and its density-derived mass,
* the source drawbox/cell-centre geometry, and
* the discrete particle sample mass.

F6 is special: its floating particles are an SPH sample while ``massbody``
and inertia define the rigid body.  The surface-speed scale is therefore
computed from the physical COM and all eight floating-box corners.  The old
box-half-diagonal scalar is retained as a diagnostic only.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.owner-scale-closure.v2"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DEFAULT_OUTPUT = REFERENCE / "stage2_f2_f3_f6_owner_scale_closure_v2.json"

F2_CONTRACT = REFERENCE / "stage2_f2_s1_observer_calibration_contract_v1.json"
F3_CONTRACT = REFERENCE / "stage2_f3_s2_observer_calibration_contract_v1.json"
F6_CONTRACT = REFERENCE / "stage2_f6_s2_observer_calibration_contract_v1.json"
F2_OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_140_f2_actual_native_typed157_home4gib_v1/owners/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010-actual-native-typed157-owner.json"
)
F3_OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/"
    "root_followup_066_f3_four_corner_native706_typed_nvme_source_v1/owners/"
    "F3_STAGE1_DP006_P1200_AY0750.json"
)

EXPECTED_SOURCE_SHA = {
    "F2-S1": "a239edb63e803a5d77f8bbe4e5dfbeef658351488343e286bdf86e11579d439e",
    "F3-S2": "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406",
    "F6-S2": "89c594899f1aa88deaddf775ad084e7560d4291a074975e8a17be58055c8eb18",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def load_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    record = file_record(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value, record


def close(actual: float, expected: float, *, tol: float = 1e-12) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual - expected) > tol:
        raise ValueError(f"value mismatch: actual={actual!r}, expected={expected!r}")


def close_vec(actual: list[float], expected: list[float], *, tol: float = 1e-12) -> None:
    if len(actual) != len(expected):
        raise ValueError(f"vector length mismatch: {actual!r} vs {expected!r}")
    for a, e in zip(actual, expected):
        close(float(a), float(e), tol=tol)


def product(values: list[float]) -> float:
    result = 1.0
    for value in values:
        result *= float(value)
    return result


def finite_vec(values: list[float], label: str) -> list[float]:
    result = [float(value) for value in values]
    if len(result) != 3 or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must be three finite values: {values!r}")
    return result


def source_contract_checks(contract: dict[str, Any], sentinel: str) -> None:
    if contract.get("schema") != f"ds02.stage2.{sentinel.lower().replace('-', '-')}.observer-calibration-contract.v1":
        # The F2/F3/F6 schema names contain the sentinel spelling in lower
        # case, but retain a direct guard below for readability and future
        # schema changes.
        expected = {
            "F2-S1": "ds02.stage2.f2-s1.observer-calibration-contract.v1",
            "F3-S2": "ds02.stage2.f3-s2.observer-calibration-contract.v1",
            "F6-S2": "ds02.stage2.f6-s2.observer-calibration-contract.v1",
        }[sentinel]
        if contract.get("schema") != expected:
            raise ValueError(f"unexpected {sentinel} contract schema")
    if contract.get("sentinel_id") != sentinel:
        raise ValueError(f"wrong sentinel in contract: {contract.get('sentinel_id')!r}")
    generated = contract.get("source_inputs", {}).get("generated_xml", {})
    if generated.get("sha256") != EXPECTED_SOURCE_SHA[sentinel]:
        raise ValueError(f"unexpected generated XML binding for {sentinel}")
    if contract.get("comparison_gate", {}).get("qualification") != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise ValueError(f"{sentinel} v1 contract is no longer UNKNOWN-gated")


def owner_record(record: dict[str, Any], *, family: str, physical_case: str) -> None:
    if record.get("family_id") != family:
        raise ValueError(f"owner family mismatch: {record.get('family_id')!r}")
    if record.get("physical_case_id") != physical_case:
        raise ValueError(f"owner physical identity mismatch: {record.get('physical_case_id')!r}")


def frozen_budget() -> dict[str, Any]:
    return {
        "position_fraction_of_registered_L": 0.02,
        "velocity_and_ke_fraction_of_registered_nonzero_scale": 0.05,
        "event_time_fraction_of_characteristic_T": 0.01,
        "time_and_output_each_max_fraction_of_task_budget": 0.25,
        "event_time_status": "UNKNOWN_UNTIL_SOURCE_EVENT_DEFINITION",
        "mass_gate": {
            "whole_initial_fluid_mass_fraction": 0.03,
            "diagnostic_per_source_or_material_fraction": 0.03,
            "diagnostic_is_not_a_replacement_for_whole_initial_gate": True,
        },
    }


def f2_entry(contract: dict[str, Any], owner: dict[str, Any], owner_input: dict[str, Any]) -> dict[str, Any]:
    sentinel = "F2-S1"
    source_contract_checks(contract, sentinel)
    owner_record(owner, family="F2", physical_case=contract["physical_case_id"])
    geometry = contract["source_geometry"]
    owner_geometry = owner["geometry"]
    owner_low = finite_vec(owner_geometry["fluid_low_m"], "F2 owner fluid_low_m")
    owner_size = finite_vec(owner_geometry["fluid_source_size_m"], "F2 owner fluid_source_size_m")
    close_vec(owner_low, geometry["fluid_union_bounds_m"]["min"])
    close_vec(owner_size, geometry["fluid_union_extent_m"])
    if owner.get("density_kg_m3") != 1000:
        raise ValueError("F2 owner density is not rho0=1000")
    canonical = owner.get("source_canonical_condition", {})
    if canonical.get("motion_file_sha256") != contract["source_inputs"]["motion_table"]["sha256"]:
        raise ValueError("F2 owner motion source is not the v1 motion binding")
    volume = product(owner_size)
    continuous_mass = volume * float(owner["density_kg_m3"])
    sample_mass = float(contract["source_particles"]["reference_initial_sample_mass_target_kg"])
    registered_l = float(geometry["L_position_reference_scalar_m"])
    return {
        "sentinel_id": sentinel,
        "family_id": contract["family_id"],
        "physical_case_id": contract["physical_case_id"],
        "status": "OWNER_GEOMETRY_CONTROL_CLOSED_MASS_SEMANTICS_EXPLICIT",
        "source_binding": {
            "v1_contract_sha256": owner_input["v1_contract"]["sha256"],
            "owner_json": owner_input["owner_json"],
            "owner_physical_case_id": owner["physical_case_id"],
            "owner_physical_condition_sha256": owner.get("physical_condition_sha256"),
            "generated_xml_sha256": contract["source_inputs"]["generated_xml"]["sha256"],
            "motion_table_sha256": contract["source_inputs"]["motion_table"]["sha256"],
        },
        "continuous_owner": {
            "authority": "F2 owner geometry fluid_source_size_m plus owner density; owner JSON has no explicit fluid mass field",
            "density_kg_m3": owner["density_kg_m3"],
            "low_m": owner_low,
            "extent_m": owner_size,
            "volume_m3": volume,
            "mass_kg": continuous_mass,
            "mass_status": "DERIVED_FROM_OWNER_GEOMETRY_AND_DENSITY",
        },
        "source_drawbox": {
            "extent_m": list(geometry["fluid_union_extent_m"]),
            "volume_m3": float(contract["source_particles"]["continuous_box_volume_m3"]),
            "mass_kg": float(contract["source_particles"]["continuous_box_mass_at_rho0_kg"]),
            "status": "SAME_EXTENT_AS_OWNER_GEOMETRY",
        },
        "discrete_initial_sample": {
            "counts_by_mkfluid": list(contract["source_particles"]["fluid_counts_by_mkfluid"]),
            "particle_mass_kg": contract["source_particles"]["fluid_particle_mass_kg"],
            "mass_kg": sample_mass,
            "sample_minus_continuous_mass_kg": sample_mass - continuous_mass,
            "sample_minus_continuous_fraction": (sample_mass - continuous_mass) / continuous_mass,
            "status": "DIAGNOSTIC_SEPARATE_FROM_CONTINUOUS_OWNER_MASS",
        },
        "registered_scales": {
            "position": {
                "L_m": registered_l,
                "definition": "longest exact three-layer source/owner fluid union extent",
                "owner_geometry_L_m": registered_l,
                "reuse_across_candidate_dp": True,
                "candidate_dp_scaling_forbidden": True,
            },
            "velocity": {
                "value_m_per_s": contract["reference_scales"]["velocity_scale_m_per_s"],
                "definition": contract["reference_scales"]["velocity_scale_definition"],
                "source": "inherited from frozen F2 v1 motion/body geometry",
            },
            "kinetic_energy": {
                "sample_j": contract["reference_scales"]["sample_mass_kinetic_energy_scale_j"],
                "continuous_owner_j": contract["reference_scales"]["continuous_box_kinetic_energy_scale_j"],
                "mass_substitution_forbidden": True,
            },
        },
        "control_binding": {
            "control_family_id": owner.get("control_family_id"),
            "rotation_duration_s": canonical.get("rotation_duration_s"),
            "rotation_hold_start_s": canonical.get("rotation_hold_start_s"),
            "rotation_final_angle_deg": canonical.get("rotation_final_angle_deg"),
            "table_coverage_s": contract["event_time"]["motion_table_coverage_s"],
        },
        "qualification": {"source_geometry": "PASS", "owner_to_source_geometry": "PASS", "scientific_QI": "UNKNOWN", "scientific_QN": "UNKNOWN", "scientific_QE": "UNKNOWN"},
    }


def f3_entry(contract: dict[str, Any], owner: dict[str, Any], owner_input: dict[str, Any]) -> dict[str, Any]:
    sentinel = "F3-S2"
    source_contract_checks(contract, sentinel)
    owner_record(owner, family="F3", physical_case=contract["physical_case_id"])
    binding = owner["physical_binding"]
    owner_initial = binding["geometry"]["initial_fluid"]
    owner_low = finite_vec(owner_initial["low_m"], "F3 owner initial fluid low_m")
    owner_size = finite_vec(owner_initial["size_m"], "F3 owner initial fluid size_m")
    source_extent = finite_vec(contract["source_geometry"]["fluid_extent_m"], "F3 source drawbox extent")
    source_low = finite_vec(contract["source_geometry"]["fluid_drawbox"]["point_m"], "F3 source drawbox point")
    if owner_initial.get("mkfluid") != 0:
        raise ValueError("F3 owner fluid identity is not mkfluid=0")
    if float(binding["density_kg_m3"]) != 1000.0:
        raise ValueError("F3 owner density is not rho0=1000")
    if contract["source_inputs"]["acceleration_table"]["sha256"] != binding["parameters"]["actual_forcing_sha256"]:
        raise ValueError("F3 forcing table differs between v1 and owner")
    owner_volume = product(owner_size)
    owner_mass = float(binding["initial_state"]["continuum_mass_by_source_kg"]["fluid"])
    derived_owner_mass = owner_volume * float(binding["density_kg_m3"])
    close(derived_owner_mass, owner_mass)
    source_volume = product(source_extent)
    source_mass = source_volume * float(binding["density_kg_m3"])
    sample_mass = float(contract["source_particles"]["fluid_sample_mass_kg"])
    registered_l = float(contract["source_geometry"]["L_position_reference_scalar_m"])
    owner_l = max(owner_size)
    close(owner_l, 0.9)
    return {
        "sentinel_id": sentinel,
        "family_id": contract["family_id"],
        "physical_case_id": contract["physical_case_id"],
        "status": "OWNER_MASS_CLOSED_SOURCE_CELL_CENTRE_EXTENT_DIFFERENCE_EXPLICIT",
        "source_binding": {
            "v1_contract_sha256": owner_input["v1_contract"]["sha256"],
            "owner_json": owner_input["owner_json"],
            "owner_physical_case_id": owner["physical_case_id"],
            "owner_physical_condition_sha256": owner.get("physical_condition_sha256"),
            "generated_xml_sha256": contract["source_inputs"]["generated_xml"]["sha256"],
            "acceleration_table_sha256": contract["source_inputs"]["acceleration_table"]["sha256"],
        },
        "continuous_owner": {
            "authority": "F3 physical_binding.geometry.initial_fluid and initial_state.continuum_mass_by_source_kg",
            "density_kg_m3": binding["density_kg_m3"],
            "low_m": owner_low,
            "extent_m": owner_size,
            "volume_m3": owner_volume,
            "mass_kg": owner_mass,
            "derived_mass_kg": derived_owner_mass,
            "mass_status": "EXPLICIT_OWNER_MASS_AND_DENSITY_GEOMETRY_AGREE",
        },
        "source_drawbox_cell_centre": {
            "low_m": source_low,
            "extent_m": source_extent,
            "volume_m3": source_volume,
            "density_derived_mass_kg": source_mass,
            "owner_extent_minus_source_extent_m": [owner_size[i] - source_extent[i] for i in range(3)],
            "owner_mass_minus_source_drawbox_density_mass_kg": owner_mass - source_mass,
            "status": "SOURCE_DP006_DRAWBOX_DIAGNOSTIC_NOT_CONTINUOUS_OWNER",
        },
        "discrete_initial_sample": {
            "count": contract["source_particles"]["fluid_particle_count"],
            "particle_mass_kg": contract["source_particles"]["particle_mass_kg"],
            "mass_kg": sample_mass,
            "sample_minus_owner_mass_kg": sample_mass - owner_mass,
            "sample_minus_owner_fraction": (sample_mass - owner_mass) / owner_mass,
            "status": "DIAGNOSTIC_NATIVE_MASS_NO_RESCALE",
        },
        "registered_scales": {
            "position": {
                "L_m": registered_l,
                "definition": "exact dp006 source XML drawbox/cell-centre extent; retained as fixed observer registration",
                "owner_geometry_L_m": owner_l,
                "owner_geometry_extent_m": owner_size,
                "source_extent_m": source_extent,
                "reuse_across_candidate_dp": True,
                "candidate_dp_scaling_forbidden": True,
                "continuous_owner_mass_target_is_independent_of_registered_L": True,
            },
            "velocity": {
                "value_m_per_s": contract["reference_scales"]["velocity_scale_m_per_s"],
                "definition": contract["reference_scales"]["velocity_scale_definition"],
                "source": "owner depth and frozen source gravity; forcing integral is not treated as field velocity",
            },
            "kinetic_energy": {
                "value_j": contract["reference_scales"]["kinetic_energy_scale_j"],
                "mass_basis": "discrete source sample in v1 diagnostic; owner mass remains separate",
            },
            "transport_time": {
                "value_s": contract["reference_scales"]["transport_time_scale_s"],
                "event_time_status": "UNKNOWN",
            },
        },
        "control_binding": {
            "control_family_id": binding.get("control_family_id"),
            "physical_condition_sha256": owner.get("physical_condition_sha256"),
            "forcing_sha256": binding["parameters"]["actual_forcing_sha256"],
            "forcing_coverage_s": contract["event_time"]["control_table_coverage_s"],
        },
        "qualification": {
            "source_owner_geometry": "EXPLICIT_DIFFERENCE_RETAINED",
            "source_control": "PASS",
            "scientific_QI": "UNKNOWN",
            "scientific_QN": "UNKNOWN",
            "scientific_QE": "UNKNOWN",
        },
    }


def cross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def f6_corner_scale(box: dict[str, Any], center: list[float], omega: list[float]) -> dict[str, Any]:
    low = finite_vec(box["point_m"], "F6 floating box point")
    size = finite_vec(box["size_m"], "F6 floating box size")
    center = finite_vec(center, "F6 physical COM")
    omega = finite_vec(omega, "F6 angular velocity")
    corners: list[dict[str, Any]] = []
    for point in itertools.product(*[(low[i], low[i] + size[i]) for i in range(3)]):
        point_vec = [float(value) for value in point]
        radius = [point_vec[i] - center[i] for i in range(3)]
        velocity = cross(omega, radius)
        corners.append({"point_m": point_vec, "r_from_physical_com_m": radius, "velocity_m_per_s": velocity, "speed_m_per_s": norm(velocity)})
    maximum = max(corners, key=lambda value: value["speed_m_per_s"])
    box_center = [low[i] + 0.5 * size[i] for i in range(3)]
    half_diagonal = norm([0.5 * value for value in size])
    legacy = norm(omega) * half_diagonal
    return {
        "physical_com_m": center,
        "geometric_box_center_m": box_center,
        "physical_com_minus_box_center_m": [center[i] - box_center[i] for i in range(3)],
        "corner_count": len(corners),
        "corner_evaluations": corners,
        "maximum_corner_speed_m_per_s": maximum["speed_m_per_s"],
        "maximum_corner_point_m": maximum["point_m"],
        "maximum_corner_velocity_m_per_s": maximum["velocity_m_per_s"],
        "formula": "max over floating-box corners of norm(cross(omega, corner - physical_COM))",
        "legacy_v1_box_half_diagonal_speed_m_per_s": legacy,
        "legacy_v1_scalar_status": "DIAGNOSTIC_ONLY_NOT_PHYSICAL_COM_BOUND",
    }


def f6_entry(contract: dict[str, Any], contract_input: dict[str, Any]) -> dict[str, Any]:
    sentinel = "F6-S2"
    source_contract_checks(contract, sentinel)
    geometry = contract["source_geometry"]
    particles = contract["source_particles"]
    rigid = contract["rigid_body"]
    extent = finite_vec(geometry["fluid_extent_m"], "F6 fluid extent")
    fluid_volume = product(extent)
    density = 1000.0
    fluid_owner_mass = fluid_volume * density
    corner = f6_corner_scale(geometry["floating_box"], rigid["physical_center_m"], rigid["initial_angular_velocity_rad_per_s"])
    return {
        "sentinel_id": sentinel,
        "family_id": contract["family_id"],
        "physical_case_id": contract["physical_case_id"],
        "status": "SOURCE_GEOMETRY_RIGID_COM_SCALE_CLOSED_MASS_SEMANTICS_EXPLICIT",
        "source_binding": {
            "v1_contract_sha256": contract_input["v1_contract"]["sha256"],
            "generated_xml_sha256": contract["source_inputs"]["generated_xml"]["sha256"],
            "owner_json": None,
            "owner_status": "NO_SEPARATE_OWNER_JSON_IN_THIS_SCOPE_SOURCE_XML_IS_AUTHORITY",
        },
        "continuous_owner": {
            "authority": "exact F6 source XML fluid drawbox recorded by frozen v1 contract",
            "density_kg_m3": density,
            "low_m": list(geometry["fluid_box"]["point_m"]),
            "extent_m": extent,
            "volume_m3": fluid_volume,
            "mass_kg": fluid_owner_mass,
            "mass_status": "DERIVED_FROM_SOURCE_BOX_AND_RHO0",
        },
        "discrete_initial_sample": {
            "fluid_count": particles["fluid_particle_count"],
            "fluid_particle_mass_kg": particles["fluid_particle_mass_kg"],
            "fluid_sample_mass_kg": particles["fluid_sample_mass_kg"],
            "floating_sample_count": particles["floating_sample_particle_count"],
            "floating_sample_mass_kg": particles["floating_sample_mass_kg_diagnostic"],
            "status": "SPH_SAMPLE_MASS_IS_NOT_RIGID_BODY_MASS",
        },
        "rigid_body_binding": {
            "physical_massbody_kg": rigid["physical_massbody_kg"],
            "physical_center_m": list(rigid["physical_center_m"]),
            "physical_inertia_kg_m2": list(rigid["physical_inertia_kg_m2"]),
            "initial_angular_velocity_rad_per_s": list(rigid["initial_angular_velocity_rad_per_s"]),
            "sample_floating_mass_substitution_forbidden": True,
        },
        "registered_scales": {
            "position": {
                "L_m": geometry["L_position_reference_scalar_m"],
                "definition": "longest exact source fluid-box extent",
                "reuse_across_candidate_dp": True,
                "candidate_dp_scaling_forbidden": True,
            },
            "fluid_gravity_velocity": {
                "value_m_per_s": contract["reference_scales"]["fluid_gravity_velocity_scale_m_per_s"],
                "definition": "sqrt(abs(g_z) * source fluid depth)",
            },
            "rigid_body_surface_velocity": corner,
            "rigid_body_angular_velocity": {
                "value_rad_per_s": contract["reference_scales"]["rigid_body_angular_velocity_scale_rad_per_s"],
                "definition": "norm(initial angular velocity)",
            },
            "kinetic_energy": {
                "fluid_gravity_j": contract["reference_scales"]["fluid_gravity_kinetic_energy_scale_j"],
                "rigid_rotational_j": contract["reference_scales"]["rigid_body_rotational_kinetic_energy_scale_j"],
                "mass_substitution_forbidden": True,
            },
        },
        "qualification": {
            "source_geometry": "PASS",
            "rigid_center_binding": "PASS",
            "scientific_QI": "UNKNOWN",
            "scientific_QN": "UNKNOWN",
            "scientific_QE": "UNKNOWN",
        },
    }


def build() -> dict[str, Any]:
    f2, f2_record = load_json(F2_CONTRACT)
    f3, f3_record = load_json(F3_CONTRACT)
    f6, f6_record = load_json(F6_CONTRACT)
    f2_owner, f2_owner_record = load_json(F2_OWNER)
    f3_owner, f3_owner_record = load_json(F3_OWNER)
    inputs = {
        "F2-S1": {"v1_contract": f2_record, "owner_json": f2_owner_record},
        "F3-S2": {"v1_contract": f3_record, "owner_json": f3_owner_record},
        "F6-S2": {"v1_contract": f6_record, "owner_json": None},
    }
    return {
        "schema": SCHEMA,
        "status": "PREPARED_OWNER_SCALE_CLOSURE_SCIENTIFIC_QUALIFICATION_UNKNOWN",
        "scope": ["F2-S1", "F3-S2", "F6-S2"],
        "read_policy": {
            "metadata_only": True,
            "source_arrays_read": False,
            "bi4_read": False,
            "native_part_read": False,
            "h5_read": False,
            "solver_started": False,
            "source_xml_rehashed_by_v2": False,
            "source_xml_sha256_reused_from_v1_contract": True,
        },
        "frozen_error_budget": frozen_budget(),
        "input_files": inputs,
        "sentinels": {
            "F2-S1": f2_entry(f2, f2_owner, inputs["F2-S1"]),
            "F3-S2": f3_entry(f3, f3_owner, inputs["F3-S2"]),
            "F6-S2": f6_entry(f6, inputs["F6-S2"]),
        },
        "candidate_grid_rule": {
            "continuous_owner_geometry_and_mass_are_fixed_across_dp": True,
            "registered_position_L_is_reused_across_candidate_dp": True,
            "registered_velocity_and_ke_scales_are_reused_across_candidate_dp": True,
            "particle_sample_mass_is_diagnostic_and_must_not_be_rescaled": True,
            "same_count_is_not_geometry_or_physical_equivalence": True,
        },
        "next_use": {
            "allowed": "prepare source-bound observer/evaluator requests after parent guard validates input closure",
            "blocked_until": ["event definition and characteristic T", "actual field comparison and time bracket evidence", "consumer calibration"],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite of existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def self_test() -> None:
    speed = f6_corner_scale(
        {"point_m": [2.0, 0.8, 0.9], "size_m": [0.775, 0.775, 0.375]},
        [2.4, 1.2, 1.08],
        [0.16, 0.24, 0.12],
    )
    assert speed["corner_count"] == 8
    assert math.isclose(speed["maximum_corner_speed_m_per_s"], 0.1813655976198352, rel_tol=0, abs_tol=1e-15)
    assert math.isclose(speed["legacy_v1_box_half_diagonal_speed_m_per_s"], 0.18094681539060034, rel_tol=0, abs_tol=1e-15)
    assert speed["maximum_corner_speed_m_per_s"] != speed["legacy_v1_box_half_diagonal_speed_m_per_s"]
    assert math.isclose(product([0.9, 0.18, 0.09]) * 1000.0, 14.58)
    assert math.isclose(product([0.894, 0.174, 0.084]) * 1000.0, 13.066704)
    try:
        f6_corner_scale({"point_m": [2.0, 0.8, 0.9], "size_m": [math.nan, 0.775, 0.375]}, [2.4, 1.2, 1.08], [0.16, 0.24, 0.12])
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite floating geometry was accepted")
    print("stage2 F2/F3/F6 owner-scale closure v2 self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    atomic_json(args.output, build())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
