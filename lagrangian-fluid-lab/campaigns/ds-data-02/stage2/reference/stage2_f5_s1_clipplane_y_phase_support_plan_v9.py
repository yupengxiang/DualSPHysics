#!/usr/bin/env python3
"""Build a forward-only F5 y-phase support plan from the V8 reports.

The V8 reports already contain the guarded Fluid/Bound VTK diagnostics.  This
builder reads only those small JSON reports and does not open VTK, BI4, HDF5,
or invoke GenCase.  It records the observed half-cell phase and an additive
candidate that changes only the fluid selector's y lattice phase to zero.
The candidate remains unqualified until a parent-guarded GenCase and support
audit prove its actual count, containment, clip relation, and mass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f5-s1.clipplane-y-phase-support-plan.v9"
ROOT = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REPORTS = {
    "dp010": DATA_ROOT / (
        "families/F5/F5_S1_YHALF_DP010_GEOMETRY_DIAGNOSTIC_V8_ROOT_116/"
        "f5-s1-yhalf-dp010-geometry-v8-root-116-001-root-forward-030-001/"
        "report/stage2_f5_s1_clipplane_geometry_diagnostic_v8.json"
    ),
    "dp005": DATA_ROOT / (
        "families/F5/F5_S1_YHALF_DP005_GEOMETRY_DIAGNOSTIC_V8_ROOT_117/"
        "f5-s1-yhalf-dp005-geometry-v8-root-117-001-root-forward-030-001/"
        "report/stage2_f5_s1_clipplane_geometry_diagnostic_v8.json"
    ),
}
OUTPUT = Path(__file__).with_name("stage2_f5_s1_clipplane_y_phase_support_plan_v9.json")

OWNER_LOW = [0.01, -0.14, 0.01]
OWNER_SIZE = [3.42, 0.28, 0.38]
OWNER_HIGH = [3.43, 0.14, 0.39]
CONTINUOUS_MASS_KG = 287.736
CLIP_POINT = [2.0, 0.0, 0.0]
CLIP_VECTOR = [0.28, 0.0, -1.0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def write_immutable(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def require_report(path: Path, grid: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8":
        raise ValueError(f"{grid}: unexpected report schema")
    if report.get("family_id") != "F5" or report.get("sentinel_id") != "F5-S1":
        raise ValueError(f"{grid}: wrong physical identity")
    if report.get("grid") != grid:
        raise ValueError(f"{grid}: report grid mismatch")
    contract = report.get("candidate_contract") or {}
    def same_vector(actual: Any, expected: list[float], label: str, tol: float = 1e-12) -> bool:
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(abs(float(a) - b) <= tol for a, b in zip(actual, expected))
        )

    if not same_vector(contract.get("continuous_owner_box_low_m"), OWNER_LOW, "owner low"):
        raise ValueError(f"{grid}: owner lower box changed")
    if not same_vector(contract.get("continuous_owner_box_high_m"), OWNER_HIGH, "owner high"):
        raise ValueError(f"{grid}: owner upper box changed")
    if contract.get("continuous_mass_kg") != CONTINUOUS_MASS_KG:
        raise ValueError(f"{grid}: continuous mass changed")
    if contract.get("official_clip_point_m") != CLIP_POINT or contract.get("official_clip_vector") != CLIP_VECTOR:
        raise ValueError(f"{grid}: clip plane changed")
    if contract.get("box_and_clip_frozen") is not True or contract.get("mass_rescale") is not False:
        raise ValueError(f"{grid}: frozen contract flags are not strict")
    control = report.get("control_audit") or {}
    if control.get("motion_byte_identical") is not True:
        raise ValueError(f"{grid}: motion is not byte-identical")
    geometry = report.get("geometry_diagnostic") or {}
    relation = geometry.get("fluid_box_relation") or {}
    if not same_vector(relation.get("box_low_m"), OWNER_LOW, "box low") or not same_vector(relation.get("box_high_m"), OWNER_HIGH, "box high"):
        raise ValueError(f"{grid}: generated fluid box changed")
    if (relation.get("axis_outside_count") or {}).get("x") != 0 or (relation.get("axis_outside_count") or {}).get("z") != 0:
        raise ValueError(f"{grid}: observed non-y outside points are unexpected")
    overlap = geometry.get("exact_float32_coordinate_overlap") or {}
    if overlap.get("unique_exact_tuple_count") != 0:
        raise ValueError(f"{grid}: exact boundary tuple overlap is nonzero")
    axes = geometry.get("generated_fluid_axis_summary") or {}
    y = axes.get("y") or {}
    if grid == "dp010":
        expected = {"min_m": -0.14499999582767487, "max_m": 0.14499999582767487, "unique_count": 30}
    else:
        expected = {"min_m": -0.13750000298023224, "max_m": 0.14249999821186066, "unique_count": 57}
    for key, value in expected.items():
        if y.get(key) != value:
            raise ValueError(f"{grid}: observed y {key} differs")
    return report


def grid_summary(report_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    grid = report["grid"]
    relation = report["geometry_diagnostic"]["fluid_box_relation"]
    y = report["geometry_diagnostic"]["generated_fluid_axis_summary"]["y"]
    mass = report["mass_audit"]
    dynamic = report["source_closure"]
    return {
        "report": stat_record(report_path),
        "dp_m": report["generated"]["dp_m"],
        "fluid_count": report["generated"]["fluid_count"],
        "sample_mass_kg": report["mass_audit"]["generated_sample_mass_kg"],
        "relative_error_percent": mass["relative_error_percent"],
        "y_phase_observed": {
            "pointref_y_m": 0.005 if grid == "dp010" else 0.0025,
            "min_m": y["min_m"],
            "max_m": y["max_m"],
            "unique_count": y["unique_count"],
            "outside_count": relation["axis_outside_count"]["y"],
            "max_positive_excess_m": max(
                float(example["positive_excess_m"][1])
                for example in relation.get("examples", [])
            ) if relation.get("examples") else None,
        },
        "clip_outside_count": report["support"]["clip_plane_relation"].get("outside_count"),
        "exact_float32_boundary_tuple_count": report["geometry_diagnostic"]["exact_float32_coordinate_overlap"]["unique_exact_tuple_count"],
        "worker_dynamic_payload_scope": {
            "pre_post_sha_stat_equal": dynamic.get("worker_dynamic_pre_post_sha_stat_equal"),
            "first_payload_hash_after_parent_reservation": dynamic.get("worker_first_payload_hash_after_parent_reservation"),
            "parent_full_hash_of_vtk": False,
            "note": "Generated XML is in the parent receipt closure; Fluid/Bound VTK content SHA/stat is worker-owned after reservation.",
        },
    }


def build() -> dict[str, Any]:
    reports = {grid: require_report(path, grid) for grid, path in REPORTS.items()}
    summaries = {grid: grid_summary(REPORTS[grid], reports[grid]) for grid in REPORTS}
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_PHASE_SUPPORT_QA_ONLY",
        "identity": {
            "family_id": "F5",
            "sentinel_id": "F5-S1",
            "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        },
        "source_evidence": summaries,
        "frozen_continuous_contract": {
            "box_low_m": OWNER_LOW,
            "box_size_m": OWNER_SIZE,
            "box_high_m": OWNER_HIGH,
            "mass_kg": CONTINUOUS_MASS_KG,
            "clip_point_m": CLIP_POINT,
            "clip_vector": CLIP_VECTOR,
            "clip_equation": "0.28*(x-2.0)-z <= 0",
            "motion_and_controls_unchanged": True,
            "mass_rescale": False,
            "old_discrete_sample_is_not_continuous_truth": True,
        },
        "diagnosis": {
            "cause_supported_by_v8": "The two candidates use a half-cell y phase while retaining the frozen y drawbox [-0.14,0.14]. The only observed outside axis is y, with excess dp/2; x and z have zero outside points.",
            "not_proven": [
                "No contact, penetration, flux, or physical-fate conclusion follows from the AABB/clip diagnostics.",
                "No new candidate mass or support result exists yet.",
            ],
        },
        "forward_candidate": {
            "representation": "source-preserving y-zero lattice phase",
            "change_only": "Set pointref.y=0.0 for the fluid selector; retain the frozen fluid box, clip primitive, x/z pointref, motion, controls, density, and source identity.",
            "candidate_pointref_y_m": {"dp010": 0.0, "dp005": 0.0},
            "candidate_expected_y_lattice": {
                "dp010": {"forecast_only": True, "min_m": -0.14, "max_m": 0.14, "axis_count": 29},
                "dp005": {"forecast_only": True, "min_m": -0.14, "max_m": 0.14, "axis_count": 57},
            },
            "forecast_limit": "These counts are lattice arithmetic only; official GenCase must determine actual points, clipping, support, and mass.",
            "priority": "Run a single parent-guarded dp005 GenCase/support QA first. The dp010 y-zero phase is a diagnostic only because fitting 30 layers into the frozen 0.28 m y width is impossible without changing the owner box or dropping a layer; do not silently alter either.",
        },
        "required_parent_guarded_qa": {
            "execution": "GenCase only; no solver, CFD, BI4/HDF5, or native trajectory read.",
            "input_closure": [
                "New candidate XML and exact source/control/motion/clip evidence are parent-bound after reservation.",
                "Generated XML must join the actual receipt and remain in the attempt root.",
                "Fluid/Bound VTK must be hashed/stat-checked by the worker before and after parsing; parent must not claim VTK parent-input hashing.",
            ],
            "gates": [
                "All fluid y coordinates within frozen [-0.14,0.14] under the recorded float32 policy.",
                "x/z containment, Idp/type mapping, and clip-plane relation remain explicit.",
                "Actual MassFluid and whole-initial mass error preferred <=1%, hard >2%; no rescale.",
                "Record exact boundary tuples and clip-side counts without physical contact/flux credit.",
                "If dp005 remains outside, mass-hardfail, or support-unknown, stop this repair branch; no blind finer grid or CFD.",
            ],
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scope": {
            "vtk_read_by_builder": False,
            "bi4_read": False,
            "hdf5_read": False,
            "gencase_started": False,
            "solver_started": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not args.build:
        parser.error("--build is required")
    plan = build()
    write_immutable(args.output, plan)
    print(json.dumps({"output": str(args.output.resolve()), "status": plan["status"], "gencase_started": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
