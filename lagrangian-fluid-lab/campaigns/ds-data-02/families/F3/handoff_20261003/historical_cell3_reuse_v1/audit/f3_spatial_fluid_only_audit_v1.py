#!/usr/bin/env python3
"""Read-only provenance audit for the historical F3 fluid-only references.

The audit joins the immutable native trajectory H5 with the official GenCase
Fluid/All/Bound VTK files.  It checks the actual particle cohort (Idp, type,
mk, coordinates and native mass) without invoking GenCase, PartVTK or a
solver.  The result deliberately keeps the fluid-only scope explicit: it is
usable as a spatial/transport reference, but it is not a full typed Q-I
product because fixed-particle trajectories and initial typed arrays are
absent from the H5 files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f3.historical-spatial-fluid-only-audit.v1"
ROOT = Path("/home/jade/Projects/DualSPHysics")
LAB = ROOT / "lagrangian-fluid-lab"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role} missing: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path), "role": role}


def line_after(data: bytes, offset: int) -> tuple[bytes, int]:
    end = data.find(b"\n", offset)
    if end < 0:
        raise ValueError("unterminated VTK header")
    return data[offset:end].rstrip(b"\r"), end + 1


def vtk_field(data: bytes, pattern: bytes, count: int, dtype: str, *, lookup: bool = False) -> np.ndarray:
    offset = data.find(pattern)
    if offset < 0:
        raise ValueError(f"VTK field header not found: {pattern!r}")
    _, offset = line_after(data, offset)
    if lookup:
        lookup_line, offset = line_after(data, offset)
        if not lookup_line.startswith(b"LOOKUP_TABLE"):
            raise ValueError(f"unexpected lookup header after {pattern!r}: {lookup_line!r}")
    result = np.frombuffer(data, dtype=np.dtype(dtype), count=count, offset=offset).copy()
    if result.size != count:
        raise ValueError(f"short VTK field {pattern!r}: {result.size} != {count}")
    return result


def read_vtk(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    point_header = re.search(rb"(?:^|\n)POINTS ([0-9]+) float\r?\n", data)
    if point_header is None:
        raise ValueError(f"POINTS header missing: {path}")
    count = int(point_header.group(1))
    points_offset = point_header.end()
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=points_offset).copy().reshape(count, 3)
    ids = vtk_field(data, b"SCALARS Idp unsigned_int", count, ">u4", lookup=True)
    types = vtk_field(data, f"Type 1 {count} unsigned_char".encode(), count, "u1")
    mk_header = f"Mk 1 {count} unsigned_char".encode()
    mks = vtk_field(data, mk_header, count, "u1") if mk_header in data else None
    return {
        "count": count,
        "id_min": int(ids.min()),
        "id_max": int(ids.max()),
        "id_unique": int(np.unique(ids).size),
        "ids": ids,
        "type_values": sorted({int(value) for value in np.unique(types)}),
        "types": types,
        "mk_values": sorted({int(value) for value in np.unique(mks)}) if mks is not None else [],
        "mks": mks,
        "points": points,
    }


def bounds(points: np.ndarray) -> list[list[float]]:
    return [[float(points[:, axis].min()), float(points[:, axis].max())] for axis in range(3)]


def compare_case(case: dict[str, Any]) -> dict[str, Any]:
    h5_path = Path(case["h5"])
    fluid_path = Path(case["fluid_vtk"])
    all_path = Path(case["all_vtk"])
    bound_path = Path(case["bound_vtk"])
    fluid = read_vtk(fluid_path)
    all_vtk = read_vtk(all_path)
    bound = read_vtk(bound_path)
    with h5py.File(h5_path, "r") as handle:
        required = ["time", "particle_id", "particle_zone", "position", "mass", "type", "mk", "valid"]
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"{case['case_id']} H5 missing {missing}")
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        positions = np.asarray(handle["position"][0])
        masses = np.asarray(handle["mass"][0])
        types = np.asarray(handle["type"][0])
        mks = np.asarray(handle["mk"][0])
        valid = np.asarray(handle["valid"][:])
        time = np.asarray(handle["time"][:])
        attrs = {str(key): value.item() if isinstance(value, np.generic) else value for key, value in handle.attrs.items()}
        h5_summary = {
            "dataset_keys": sorted(str(key) for key in handle.keys()),
            "frames": int(valid.shape[0]),
            "particle_count": int(ids.size),
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "particle_id_min": int(ids.min()),
            "particle_id_max": int(ids.max()),
            "particle_id_unique": int(np.unique(ids).size),
            "zone_values": sorted({int(value) for value in np.unique(zones)}),
            "type_values_initial": sorted({int(value) for value in np.unique(types)}),
            "mk_values_initial": sorted({int(value) for value in np.unique(mks)}),
            "valid_all": bool(np.all(valid)),
            "mass_per_particle_kg": float(masses[0]),
            "initial_mass_kg": float(np.sum(masses, dtype=np.float64)),
            "attrs": {key: str(value) for key, value in attrs.items() if key in {"schema", "solver_dimension", "mass_semantics", "source_format"}},
            "has_initial_type": "initial_type" in handle,
            "has_initial_mass": "initial_mass" in handle,
        }

    fluid_h5_order = np.array_equal(ids, fluid["ids"])
    fluid_position_max = float(np.max(np.abs(positions - fluid["points"]))) if fluid_h5_order else None
    fluid_position_rms = float(np.sqrt(np.mean((positions - fluid["points"]) ** 2))) if fluid_h5_order else None
    h5_type_match = np.array_equal(types.astype(np.uint8), fluid["types"])
    h5_mk_match = np.array_equal(mks.astype(np.uint8), fluid["mks"])
    fluid_type = np.asarray(fluid["types"])
    fluid_mk = np.asarray(fluid["mks"])
    all_ids_contiguous = np.array_equal(all_vtk["ids"], np.arange(all_vtk["count"], dtype=np.uint32))
    all_fluid_suffix = np.array_equal(all_vtk["ids"][all_vtk["count"] - fluid["count"] :], fluid["ids"])
    all_fluid_type_match = np.array_equal(all_vtk["types"][all_vtk["count"] - fluid["count"] :], fluid_type)
    all_fluid_mk_match = np.array_equal(all_vtk["mks"][all_vtk["count"] - fluid["count"] :], fluid_mk)
    fluid_start = int(fluid["id_min"])
    boundary_count = int(bound["count"])
    return {
        "case_id": case["case_id"],
        "h5": binding(h5_path, "immutable native fluid-only trajectory H5"),
        "raw_gencase": {key: binding(Path(value), role) for key, value, role in case["raw_files"]},
        "h5_summary": h5_summary,
        "gencase_vtk_summary": {
            "fluid": {
                "count": fluid["count"],
                "id_range": [fluid["id_min"], fluid["id_max"]],
                "id_unique": fluid["id_unique"],
                "type_values": fluid["type_values"],
                "mk_values": fluid["mk_values"],
                "bounds_m": bounds(fluid["points"]),
            },
            "all": {
                "count": all_vtk["count"],
                "id_range": [all_vtk["id_min"], all_vtk["id_max"]],
                "id_unique": all_vtk["id_unique"],
                "type_values": all_vtk["type_values"],
                "mk_values": all_vtk["mk_values"],
            },
            "bound": {
                "count": bound["count"],
                "id_range": [bound["id_min"], bound["id_max"]],
                "id_unique": bound["id_unique"],
                "type_values": bound["type_values"],
                "mk_values": bound["mk_values"],
            },
            "cohort": {
                "total_particles": all_vtk["count"],
                "fixed_particles": boundary_count,
                "fluid_particles": fluid["count"],
                "fixed_id_range": [int(bound["ids"].min()), int(bound["ids"].max())],
                "fluid_id_range": [fluid_start, int(fluid["id_max"])],
                "fluid_suffix_of_all": bool(all_fluid_suffix),
                "fluid_type_matches_all": bool(all_fluid_type_match),
                "fluid_mk_matches_all": bool(all_fluid_mk_match),
                "all_ids_zero_based_contiguous": bool(all_ids_contiguous),
            },
        },
        "checks": {
            "h5_id_axis_equals_official_gencase_fluid_id_axis": bool(fluid_h5_order),
            "h5_initial_position_equals_official_gencase_fluid_position": bool(fluid_h5_order and fluid_position_max == 0.0),
            "h5_initial_position_max_abs_residual_m": fluid_position_max,
            "h5_initial_position_rms_residual_m": fluid_position_rms,
            "h5_type_equals_official_gencase_fluid_type": bool(h5_type_match),
            "h5_mk_equals_official_gencase_fluid_mk": bool(h5_mk_match),
            "h5_fluid_type_is_native_type3": bool(np.all(fluid_type == 3)),
            "h5_fluid_mk_is_native_mk1": bool(np.all(fluid_mk == 1)),
            "h5_zone_is_zero": bool(h5_summary["zone_values"] == [0]),
            "h5_has_no_fixed_trajectory": bool(not h5_summary["has_initial_type"] and not h5_summary["has_initial_mass"]),
            "official_gencase_cohort_closed": bool(all_ids_contiguous and all_fluid_suffix and all_fluid_type_match and all_fluid_mk_match),
        },
        "partvtk_status": {
            "official_partvtk_output_present": False,
            "status": "pending_no_partvtk_output_found",
            "action_taken": "none; no PartVTK or new conversion was invoked",
            "qualification_boundary": "GenCase Fluid/All/Bound VTK is the audited raw cohort source; this does not claim a fresh PartVTK conversion.",
        },
    }


def make_cases() -> list[dict[str, Any]]:
    r008_dir = LAB / "campaigns/l1-resume/artifacts/f3-ref0081818/R0081818-NOMINAL"
    r006_dir = LAB / "campaigns/l1-resume/artifacts/cell3/F3_CELL3_plain_0p006"
    return [
        {
            "case_id": "R0081818-NOMINAL",
            "h5": LAB / "campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5",
            "fluid_vtk": r008_dir / "F3_CELL3_plain_0p008181818181818_Fluid.vtk",
            "all_vtk": r008_dir / "F3_CELL3_plain_0p008181818181818_All.vtk",
            "bound_vtk": r008_dir / "F3_CELL3_plain_0p008181818181818_Bound.vtk",
            "raw_files": [
                ("bi4", r008_dir / "F3_CELL3_plain_0p008181818181818.bi4", "immutable GenCase BI4"),
                ("xml", r008_dir / "F3_CELL3_plain_0p008181818181818.xml", "immutable generated XML"),
                ("def_xml", r008_dir / "F3_CELL3_plain_0p008181818181818_Def.xml", "immutable generated definition XML"),
                ("gencase_log", r008_dir / "F3_CELL3_plain_0p008181818181818-GENCASE.log", "official GenCase log"),
                ("all_vtk", r008_dir / "F3_CELL3_plain_0p008181818181818_All.vtk", "official GenCase all-particle VTK"),
                ("bound_vtk", r008_dir / "F3_CELL3_plain_0p008181818181818_Bound.vtk", "official GenCase boundary VTK"),
                ("fluid_vtk", r008_dir / "F3_CELL3_plain_0p008181818181818_Fluid.vtk", "official GenCase fluid VTK"),
            ],
        },
        {
            "case_id": "REF-006",
            "h5": LAB / "campaigns/l1-resume/data/continuation/F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen.h5",
            "fluid_vtk": r006_dir / "F3_CELL3_plain_0p006_Fluid.vtk",
            "all_vtk": r006_dir / "F3_CELL3_plain_0p006_All.vtk",
            "bound_vtk": r006_dir / "F3_CELL3_plain_0p006_Bound.vtk",
            "raw_files": [
                ("bi4", r006_dir / "F3_CELL3_plain_0p006.bi4", "immutable GenCase BI4; byte-equal to qualification BI4"),
                ("xml", r006_dir / "F3_CELL3_plain_0p006.xml", "immutable source-reuse generated XML"),
                ("def_xml", r006_dir / "F3_CELL3_plain_0p006_Def.xml", "immutable source-reuse definition XML"),
                ("gencase_log", r006_dir / "gencase.log", "official GenCase log"),
                ("all_vtk", r006_dir / "F3_CELL3_plain_0p006_All.vtk", "official GenCase all-particle VTK"),
                ("bound_vtk", r006_dir / "F3_CELL3_plain_0p006_Bound.vtk", "official GenCase boundary VTK"),
                ("fluid_vtk", r006_dir / "F3_CELL3_plain_0p006_Fluid.vtk", "official GenCase fluid VTK"),
            ],
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = [compare_case(case) for case in make_cases()]
    checks = [
        check
        for case in cases
        for check, value in case["checks"].items()
        if isinstance(value, bool) and not value
    ]
    report = {
        "schema": SCHEMA,
        "scope": "Immutable historical F3 fixed-tank fluid-only cohort audit; no PartVTK/conversion/solver invocation and no transfer to dual-axis or baffle mechanisms.",
        "source_policy": "All source H5, BI4, XML, GenCase logs and VTK files are read-only; this report is additive.",
        "cases": cases,
        "overall_status": "pass_gencase_fluid_cohort_audit" if not checks else "fail_gencase_fluid_cohort_audit",
        "failed_checks": checks,
        "reader_boundary": {
            "canonical_full_typed_reader_compatibility": "not_directly_compatible",
            "fluid_only_reference_allowed": True,
            "fluid_only_adapter_contract": {
                "fluid_only_reference": True,
                "fixed_state_scope": "absent",
                "identity": "(particle_zone, particle_id)",
                "native_fields": ["type=3", "mk=1", "native per-particle mass", "position/velocity/density/pressure/time/valid"],
                "prohibited": ["synthetic fixed rows", "unknown-fate fabrication", "posthoc mass normalization", "full typed Q-I claim"],
            },
            "unchanged_full_reader_requires": "A separately named additive H5 made from original BI4 with fixed and fluid IDs plus initial_type/initial_mass; no such conversion was started by this audit.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["overall_status"], "failed_checks": checks}, sort_keys=True))
    return 0 if not checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
