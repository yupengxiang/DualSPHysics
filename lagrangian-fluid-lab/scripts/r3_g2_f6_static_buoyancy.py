#!/usr/bin/env python3
"""CPU-only static buoyancy pre-diagnostic for the R3 F6 Test 14 route.

The preceding R3 F6 route is a real three-dimensional Float1/Test 14 run, but
its DBC result is scientifically rejected.  This module tests one narrow
hypothesis without launching another solver job:

* the mass and transformed outer hull should predict a near-zero heave at the
  published equilibrium waterline; and
* if the late DBC body state is far from that static equilibrium while the
  recorded fluid force remains close to body weight, the observation is
  consistent with a boundary-pressure/effective-buoyancy artifact.

The submerged volume is evaluated from the closed triangular outer hull.  Each
surface triangle is decomposed into a signed tetrahedron with a reference point
below the hull.  The fraction of a tetrahedron below a horizontal plane is the
CDF of a linear form over a 3-simplex; repeated vertex heights are handled by
the corresponding repeated-knot derivative.  No GPU or solver launch is used.

This is a static geometry/force consistency diagnostic, not physical validation
of Test 14 and not evidence that mDBC will pass.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

try:
    from scripts.r3_g2_f6_test14 import (
        EQUILIBRIUM_BASE_Z_M,
        EQUILIBRIUM_COG_Z_M,
        EXTRACTED,
        FLOAT_MASS_KG,
        OFFSETS,
        WATER_DEPTH_M,
        connected_triangle_components,
        fetch_external,
        read_binary_stl,
        records,
        signed_mesh_volume,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from r3_g2_f6_test14 import (
        EQUILIBRIUM_BASE_Z_M,
        EQUILIBRIUM_COG_Z_M,
        EXTRACTED,
        FLOAT_MASS_KG,
        OFFSETS,
        WATER_DEPTH_M,
        connected_triangle_components,
        fetch_external,
        read_binary_stl,
        records,
        signed_mesh_volume,
    )


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
DEFAULT_SOURCE = EXTRACTED / "Float1.STL"
DEFAULT_RUN_ROOT = CAMPAIGN / "runs"
DEFAULT_INPUT_REPORT = CAMPAIGN / "r3-g2-f6-test14.json"
DEFAULT_REPORT = CAMPAIGN / "r3-g2-f6-static-buoyancy.json"
RHO_WATER_KG_M3 = 1000.0
GRAVITY_M_S2 = 9.81
FREE_SURFACE_Z_M = WATER_DEPTH_M
TAIL_WINDOW_S = 1.0
TIE_TOLERANCE_M = 1.0e-12


def _relative_path(path: Path) -> str:
    """Keep report paths portable while retaining external paths when needed."""
    try:
        return str(Path(path).resolve().relative_to(LAB))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transform_outer_hull(source: Path, base_z_m: float = EQUILIBRIUM_BASE_Z_M) -> tuple[np.ndarray, dict[str, Any]]:
    """Read the official binary STL and return the largest closed component in world axes."""
    normals, triangles_mm = read_binary_stl(Path(source))
    del normals
    components = connected_triangle_components(triangles_mm)
    signed_components_m3 = [signed_mesh_volume(triangles_mm[index]) / 1.0e9 for index in components]
    selected_index = int(np.argmax(np.abs(signed_components_m3)))
    selected = triangles_mm[components[selected_index]]

    world = np.empty_like(selected, dtype=float)
    # The source convention is millimetres with Y vertical.  The R3 route
    # explicitly maps it to world X/Y/Z before generating the case.
    world[:, :, 0] = (selected[:, :, 0] - 150.0) / 1000.0
    world[:, :, 1] = (150.0 - selected[:, :, 2]) / 1000.0
    world[:, :, 2] = base_z_m + selected[:, :, 1] / 1000.0
    selected_volume_m3 = float(abs(signed_mesh_volume(world)))
    audit = {
        "source_path": _relative_path(Path(source)),
        "source_sha256": sha256(Path(source)),
        "source_triangles": int(len(triangles_mm)),
        "source_connected_components": int(len(components)),
        "source_component_signed_volumes_m3": signed_components_m3,
        "selected_component_index": selected_index,
        "selected_outer_triangles": int(len(selected)),
        "selected_outer_volume_m3": selected_volume_m3,
        "world_base_z_m": float(base_z_m),
        "world_bbox_min_m": world.reshape(-1, 3).min(axis=0).tolist(),
        "world_bbox_max_m": world.reshape(-1, 3).max(axis=0).tolist(),
    }
    return world, audit


def _group_heights(heights: np.ndarray) -> list[tuple[np.longdouble, int]]:
    """Group equal (within STL precision) heights for repeated-knot evaluation."""
    span = np.ptp(heights)
    tolerance = np.longdouble(TIE_TOLERANCE_M) * max(np.longdouble(1.0), span)
    groups: list[list[Any]] = []
    for value in sorted(np.asarray(heights, dtype=np.longdouble)):
        if not groups or abs(value - groups[-1][0]) > tolerance:
            groups.append([value, 1])
        else:
            groups[-1][1] += 1
    return [(np.longdouble(value), int(count)) for value, count in groups]


def tetra_fraction_below(heights: np.ndarray, plane_z_m: float) -> float:
    """Return the volume fraction of a tetrahedron below a horizontal plane.

    For distinct heights this is the standard truncated-simplex CDF.  If a
    triangle has a horizontal edge/face, the repeated-knot residue is used so
    no arbitrary height jitter is introduced.
    """
    values = np.asarray(heights, dtype=np.longdouble)
    if values.shape != (4,):
        raise ValueError(f"tetrahedron must have four vertex heights, got {values.shape}")
    plane = np.longdouble(plane_z_m)
    minimum, maximum = values.min(), values.max()
    tolerance = np.longdouble(TIE_TOLERANCE_M) * max(np.longdouble(1.0), maximum - minimum)
    if plane <= minimum + tolerance:
        return 0.0
    if plane >= maximum - tolerance:
        return 1.0

    groups = _group_heights(values)
    if len(groups) == 1:
        return float(plane >= groups[0][0])

    residue_sum = np.longdouble(0.0)
    for height, multiplicity in groups:
        if height <= plane:
            continue
        numerator = (height - plane) ** 3
        denominator = np.longdouble(1.0)
        log_derivative = np.longdouble(3.0) / (height - plane)
        log_derivative_prime = -np.longdouble(3.0) / (height - plane) ** 2
        for other, other_multiplicity in groups:
            if other == height:
                continue
            denominator *= (height - other) ** other_multiplicity
            log_derivative -= other_multiplicity / (height - other)
            log_derivative_prime += other_multiplicity / (height - other) ** 2
        base = numerator / denominator
        if multiplicity == 1:
            residue = base
        elif multiplicity == 2:
            residue = base * log_derivative
        elif multiplicity == 3:
            residue = base * (log_derivative ** 2 + log_derivative_prime) / 2.0
        else:
            # A valid non-degenerate tetrahedron with a reference point below
            # the body cannot need this branch.  Keep a clear failure for an
            # accidentally collapsed input rather than silently guessing.
            raise ValueError(f"unsupported repeated height multiplicity {multiplicity}")
        residue_sum += residue
    return float(np.clip(np.longdouble(1.0) - residue_sum, 0.0, 1.0))


@dataclass(frozen=True)
class StaticVolumeModel:
    """Signed tetrahedral decomposition of a closed triangular hull."""

    tetra_heights: np.ndarray
    signed_tetra_volumes_m3: np.ndarray
    orientation_sign: float
    total_volume_m3: float

    @classmethod
    def from_triangles(cls, triangles: np.ndarray) -> "StaticVolumeModel":
        triangles = np.asarray(triangles, dtype=float)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
            raise ValueError(f"triangles must have shape (N, 3, 3), got {triangles.shape}")
        reference_z = float(triangles[:, :, 2].min() - 1.0)
        reference = np.zeros((len(triangles), 3), dtype=float)
        reference[:, 2] = reference_z
        vectors = triangles - reference[:, None, :]
        signed = np.linalg.det(vectors) / 6.0
        total_signed = float(np.sum(signed, dtype=np.float64))
        if abs(total_signed) <= 1.0e-16:
            raise ValueError("triangles do not form a non-zero oriented closed hull")
        orientation_sign = 1.0 if total_signed > 0.0 else -1.0
        tetra_heights = np.column_stack((
            np.full(len(triangles), reference_z, dtype=float),
            triangles[:, :, 2],
        ))
        return cls(
            tetra_heights=tetra_heights,
            signed_tetra_volumes_m3=signed,
            orientation_sign=orientation_sign,
            total_volume_m3=abs(total_signed),
        )

    def volume_below(self, plane_z_m: float) -> float:
        """Return the positive volume of the hull below ``plane_z_m``."""
        fractions = np.asarray(
            [tetra_fraction_below(heights, plane_z_m) for heights in self.tetra_heights],
            dtype=np.longdouble,
        )
        value = np.sum(
            self.signed_tetra_volumes_m3.astype(np.longdouble) * fractions,
            dtype=np.longdouble,
        ) * np.longdouble(self.orientation_sign)
        return float(max(np.longdouble(0.0), value))

    def volume_for_heave(self, heave_m: float, waterline_z_m: float = FREE_SURFACE_Z_M) -> float:
        """Displaced volume when the equilibrium-reference hull moves by ``heave_m``."""
        return self.volume_below(waterline_z_m - heave_m)


def solve_static_equilibrium(
    model: StaticVolumeModel,
    target_volume_m3: float,
    waterline_z_m: float = FREE_SURFACE_Z_M,
    base_z_m: float = EQUILIBRIUM_BASE_Z_M,
    cog_above_base_m: float = EQUILIBRIUM_COG_Z_M - EQUILIBRIUM_BASE_Z_M,
) -> dict[str, float]:
    """Solve the geometric equilibrium level where rho*V equals body mass."""
    if not 0.0 < target_volume_m3 < model.total_volume_m3:
        raise ValueError("target displaced volume must lie strictly inside the hull volume")
    lower, upper = model.tetra_heights[:, 1:].min(), model.tetra_heights[:, 1:].max()
    for _ in range(60):
        midpoint = (lower + upper) / 2.0
        if model.volume_below(midpoint) < target_volume_m3:
            lower = midpoint
        else:
            upper = midpoint
    local_waterline = (lower + upper) / 2.0
    heave = waterline_z_m - local_waterline
    return {
        "target_displaced_volume_m3": float(target_volume_m3),
        "equilibrium_local_waterline_m": float(local_waterline),
        "predicted_heave_from_reference_m": float(heave),
        "predicted_base_z_m": float(base_z_m + heave),
        "predicted_cog_z_m": float(base_z_m + cog_above_base_m + heave),
        "equilibrium_volume_m3": float(model.volume_for_heave(heave, waterline_z_m)),
    }


def static_probe(model: StaticVolumeModel, heave_m: float) -> dict[str, float]:
    """Evaluate the static force balance at one reference-relative heave."""
    displaced = model.volume_for_heave(heave_m)
    buoyancy = RHO_WATER_KG_M3 * GRAVITY_M_S2 * displaced
    weight = FLOAT_MASS_KG * GRAVITY_M_S2
    return {
        "heave_from_reference_m": float(heave_m),
        "center_z_m": float(EQUILIBRIUM_COG_Z_M + heave_m),
        "local_waterline_m": float(FREE_SURFACE_Z_M - heave_m),
        "displaced_volume_m3": float(displaced),
        "buoyant_force_z_N": float(buoyancy),
        "weight_N": float(weight),
        "force_balance_buoyancy_minus_weight_N": float(buoyancy - weight),
    }


def _mean(values: list[float]) -> float:
    return float(np.mean(np.asarray(values, dtype=float)))


def _std(values: list[float]) -> float:
    return float(np.std(np.asarray(values, dtype=float)))


def dynamic_tail_crosscheck(
    model: StaticVolumeModel,
    run_root: Path = DEFAULT_RUN_ROOT,
    tail_window_s: float = TAIL_WINDOW_S,
) -> list[dict[str, Any]]:
    """Read existing FloatingInfo CSVs; never launches or schedules a solver."""
    output: list[dict[str, Any]] = []
    for record in records():
        case_id = record["case_id"]
        latest_path = Path(run_root) / case_id / "latest.json"
        common = {
            "case_id": case_id,
            "offset_name": record["offset_name"],
            "offset_m": float(record["offset_m"]),
            "level": record["level"],
            "source_latest_json": _relative_path(latest_path),
        }
        if not latest_path.is_file():
            output.append(common | {"input_status": "missing_latest_run"})
            continue
        summary = json.loads(latest_path.read_text())
        attempt = Path(summary.get("attempt_directory", ""))
        csvs = sorted((attempt / "floating").glob("Float1_mk*.csv"))
        if summary.get("status") != "completed" or len(csvs) != 1:
            output.append(common | {
                "input_status": "run_not_completed_or_floating_csv_missing",
                "run_status": summary.get("status"),
                "attempt_id": summary.get("attempt_id"),
            })
            continue
        with csvs[0].open(newline="") as stream:
            rows = list(csv.DictReader(stream, skipinitialspace=True))
        if not rows:
            output.append(common | {"input_status": "floating_csv_empty"})
            continue
        time = np.asarray([float(row["time [s]"]) for row in rows], dtype=float)
        centers = np.asarray([float(row["center.z [m]"]) for row in rows], dtype=float)
        fluid_forces = np.asarray([float(row["fluidforcelin.z [N]"]) for row in rows], dtype=float)
        if not np.all(np.isfinite(np.column_stack((time, centers, fluid_forces)))):
            output.append(common | {"input_status": "nonfinite_dynamic_fields"})
            continue
        tail = time >= time[-1] - tail_window_s
        tail_centers = centers[tail]
        tail_forces = fluid_forces[tail]
        center_mean = _mean(tail_centers.tolist())
        heave_mean = center_mean - EQUILIBRIUM_COG_Z_M
        geometric_volume = model.volume_for_heave(heave_mean)
        geometric_force = RHO_WATER_KG_M3 * GRAVITY_M_S2 * geometric_volume
        force_mean = _mean(tail_forces.tolist())
        implied_volume = force_mean / (RHO_WATER_KG_M3 * GRAVITY_M_S2)
        output.append(common | {
            "input_status": "completed_existing_dbc_output",
            "attempt_id": summary.get("attempt_id"),
            "tail_window_s": float(tail_window_s),
            "tail_samples": int(np.count_nonzero(tail)),
            "tail_end_time_s": float(time[-1]),
            "tail_center_z_mean_m": center_mean,
            "tail_center_z_std_m": _std(tail_centers.tolist()),
            "tail_heave_from_reference_mean_m": float(heave_mean),
            "tail_fluid_force_z_mean_N": force_mean,
            "tail_fluid_force_z_std_N": _std(tail_forces.tolist()),
            "geometric_displaced_volume_at_tail_mean_m3": float(geometric_volume),
            "geometric_hydrostatic_force_at_tail_mean_N": float(geometric_force),
            "force_implied_displaced_volume_m3": float(implied_volume),
            "force_implied_minus_geometric_volume_m3": float(implied_volume - geometric_volume),
            "force_implied_to_geometric_volume_ratio": (
                float(implied_volume / geometric_volume) if geometric_volume > 0.0 else None
            ),
            "recorded_force_minus_body_weight_N": float(force_mean - FLOAT_MASS_KG * GRAVITY_M_S2),
            "source_floating_csv": _relative_path(csvs[0]),
        })
    return output


def analyze(
    source: Path = DEFAULT_SOURCE,
    run_root: Path = DEFAULT_RUN_ROOT,
    input_report: Path = DEFAULT_INPUT_REPORT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    """Run the CPU static diagnostic and write a machine-readable report."""
    source = Path(source)
    if not source.is_file():
        # Reuse the verified Test 14 archive acquisition from the preceding
        # route.  This only prepares a small STL/data archive and never starts
        # GenCase or a solver.
        fetch_external()
    if not source.is_file():
        raise FileNotFoundError(f"official Float1 STL is unavailable: {source}")

    triangles, mesh_audit = transform_outer_hull(source)
    model = StaticVolumeModel.from_triangles(triangles)
    target_volume = FLOAT_MASS_KG / RHO_WATER_KG_M3
    nominal_volume = model.volume_for_heave(0.0)
    nominal_force = nominal_volume * RHO_WATER_KG_M3 * GRAVITY_M_S2
    equilibrium = solve_static_equilibrium(model, target_volume)
    probes = [static_probe(model, heave) for heave in (-0.12, -0.074, 0.0, 0.076, 0.12)]
    dynamic = dynamic_tail_crosscheck(model, run_root)
    completed_dynamic = [item for item in dynamic if item["input_status"] == "completed_existing_dbc_output"]
    if completed_dynamic:
        geometric_gap = [item["force_implied_minus_geometric_volume_m3"] for item in completed_dynamic]
        ratios = [item["force_implied_to_geometric_volume_ratio"] for item in completed_dynamic if item["force_implied_to_geometric_volume_ratio"] is not None]
        dynamic_summary: dict[str, Any] = {
            "completed_case_count": len(completed_dynamic),
            "case_count": len(dynamic),
            "geometric_gap_volume_range_m3": [float(min(geometric_gap)), float(max(geometric_gap))],
            "force_implied_to_geometric_volume_ratio_range": [float(min(ratios)), float(max(ratios))] if ratios else None,
            "all_recorded_tail_forces_within_1N_of_body_weight": all(
                abs(item["recorded_force_minus_body_weight_N"]) <= 1.0 for item in completed_dynamic
            ),
        }
    else:
        dynamic_summary = {
            "completed_case_count": 0,
            "case_count": len(dynamic),
            "geometric_gap_volume_range_m3": None,
            "force_implied_to_geometric_volume_ratio_range": None,
            "all_recorded_tail_forces_within_1N_of_body_weight": None,
        }

    previous_report = None
    if Path(input_report).is_file():
        previous = json.loads(Path(input_report).read_text())
        previous_report = {
            "path": _relative_path(Path(input_report)),
            "sha256": sha256(Path(input_report)),
            "scientific_acceptance": previous.get("scientific_acceptance"),
            "scope": previous.get("scope"),
        }

    nominal_relative_volume_error = (nominal_volume - target_volume) / target_volume
    payload: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic_id": "R3_F6_test14_static_buoyancy_preflight",
        "scope": "CPU-only static outer-hull displacement and existing six-case 3-D DBC tail-force cross-check",
        "execution_status": "completed_cpu_only_existing_data_crosscheck",
        "acceptance_status": "diagnostic_only_not_physical_acceptance",
        "scientific_acceptance": "not_accepted_physical_validation",
        "acceptance_reason": (
            "The static outer-hull/mass check is near equilibrium at the published waterline, "
            "but existing DBC tail forces imply near-weight displaced volume at body states whose "
            "geometric submerged volume is much smaller. This localizes a DBC/effective-pressure "
            "hypothesis; it does not prove causality or mDBC acceptance."
        ),
        "resource_policy": {
            "execution_kind": "CPU-only post-processing; no GenCase, solver, or GPU launch",
            "gpu_indices_used": [],
            "gpu_indices_forbidden": [0, 1, 2, 3],
            "allowed_physical_gpu_indices_if_future_solver_run": [4, 5, 6, 7],
            "inventory_ref": "campaigns/v0.1-candidate/w00-inventory.json",
        },
        "hypotheses": [
            {
                "id": "H1_geometry_mass_equilibrium",
                "statement": "A gross outer-hull transform, mass, or equilibrium placement error explains the positive DBC late-time bias.",
                "prediction": "The closed outer hull should miss m/rho at the nominal waterline or predict a large static heave.",
                "result": "not_supported_by_static_check",
                "evidence": {
                    "nominal_displaced_volume_m3": float(nominal_volume),
                    "target_displaced_volume_m3": float(target_volume),
                    "nominal_relative_volume_error": float(nominal_relative_volume_error),
                    "predicted_static_heave_m": equilibrium["predicted_heave_from_reference_m"],
                },
            },
            {
                "id": "H2_dbc_effective_buoyancy",
                "statement": "The rejected DBC route has an effective upward pressure/force bias that is not represented by geometric static displacement at its late body state.",
                "prediction": "Existing tail fluid force remains near body weight while geometric submerged volume at the recorded center is substantially lower.",
                "result": "consistent_with_existing_data_but_not_causal_proof",
                "evidence": dynamic_summary,
            },
            {
                "id": "H3_mdbc_remedy",
                "statement": "Changing DBC to mDBC will resolve the bias.",
                "prediction": "A verified mDBC normal/ghost setup would need a matched rerun before this can be assessed.",
                "result": "untested_blocked",
                "evidence": {"mdbc_solver_run": False, "mdbc_normals_verified_for_f6": False},
            },
        ],
        "inputs": {
            "official_stl": mesh_audit,
            "prior_r3_report": previous_report,
            "existing_dbc_tail_window_s": TAIL_WINDOW_S,
        },
        "static_model": {
            "waterline_z_m": FREE_SURFACE_Z_M,
            "water_depth_m": WATER_DEPTH_M,
            "water_density_kg_m3": RHO_WATER_KG_M3,
            "gravity_m_s2": GRAVITY_M_S2,
            "body_mass_kg": FLOAT_MASS_KG,
            "body_weight_N": FLOAT_MASS_KG * GRAVITY_M_S2,
            "equilibrium_reference_base_z_m": EQUILIBRIUM_BASE_Z_M,
            "equilibrium_reference_cog_z_m": EQUILIBRIUM_COG_Z_M,
            "nominal_displaced_volume_m3": float(nominal_volume),
            "nominal_buoyant_force_z_N": float(nominal_force),
            "target_displaced_volume_m3": float(target_volume),
            "nominal_relative_volume_error": float(nominal_relative_volume_error),
            "predicted_equilibrium": equilibrium,
            "static_probes": probes,
        },
        "existing_dbc_tail_crosscheck": dynamic,
        "diagnostic_summary": dynamic_summary,
        "conclusion": {
            "finding": (
                "The static outer-hull/mass model predicts a near-zero reference equilibrium "
                "(about 1 mm), while the existing DBC tails sit 70-120 mm above it and still "
                "report approximately body-weight upward force."
            ),
            "interpretation": "A boundary-pressure/effective-buoyancy issue is a prioritized next hypothesis; geometry/mass gross error is not the leading explanation from this preflight.",
            "physical_acceptance_claim": False,
            "mdbc_claim": False,
        },
        "open_blockers": [
            "Current 3-D Test 14 DBC proxy remains scientifically rejected; this diagnostic cannot promote it.",
            "Build and verify complete mDBC normals/ghost geometry for the transformed Float1 outer hull before any mDBC attribution.",
            "Run a matched static or hydrostatic-relaxation DBC-versus-mDBC comparison with force decomposition.",
            "Repeat a larger-basin/damping sensitivity because the existing 2 m tank is a computational proxy.",
            "Repeat body-surface resolution and release-height lattice-phase controls at dp <= 0.02 m.",
            "Confirm the free-surface level and outer-hull/mass convention in the matched solver setup.",
        ],
    }
    Path(report_path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    payload = analyze(args.source, args.run_root, args.input_report, args.report)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
