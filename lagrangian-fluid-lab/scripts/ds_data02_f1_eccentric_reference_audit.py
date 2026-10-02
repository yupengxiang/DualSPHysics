#!/usr/bin/env python3
"""Read-only audit of the existing F1 eccentric-obstacle references.

The audit deliberately separates reference-input consistency from numerical
qualification.  It reads generated GenCase products, solver receipts/log
summaries, the complete Q-I reports, and only the first HDF5 frame for the
natural type-3 mass/identity check.  Large trajectory files are therefore
metadata/first-frame inputs; their conversion-report SHA is carried through
instead of silently rehashing the whole file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import resource
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import h5py
import numpy as np


SCHEMA = "ds02.f1.eccentric-reference-audit.v1"
GEOMETRY = {
    "tank_length_m": 1.6,
    "tank_width_m": 0.67,
    "tank_height_m": 0.4,
    "fluid_length_m": 0.4,
    "initial_depth_m": 0.3,
    "obstacle_x_m": 0.9,
    "obstacle_y_m": 0.24,
    "obstacle_length_m": 0.12,
    "obstacle_width_m": 0.12,
    "obstacle_height_m": 0.45,
}
CONTINUOUS_FLUID_MASS_KG = 80.4
OUTER_FACES = {
    "outer_x_low": (0, 0.0, ((0.0, 0.67), (0.0, 0.4))),
    "outer_x_high": (0, 1.6, ((0.0, 0.67), (0.0, 0.4))),
    "outer_y_low": (1, 0.0, ((0.0, 1.6), (0.0, 0.4))),
    "outer_y_high": (1, 0.67, ((0.0, 1.6), (0.0, 0.4))),
    "outer_z_low": (2, 0.0, ((0.0, 1.6), (0.0, 0.67))),
}
OBSTACLE_FACES = {
    "obstacle_x_low": (0, 0.9, ((0.24, 0.36), (0.0, 0.45))),
    "obstacle_x_high": (0, 1.02, ((0.24, 0.36), (0.0, 0.45))),
    "obstacle_y_low": (1, 0.24, ((0.9, 1.02), (0.0, 0.45))),
    "obstacle_y_high": (1, 0.36, ((0.9, 1.02), (0.0, 0.45))),
    "obstacle_z_high": (2, 0.45, ((0.9, 1.02), (0.24, 0.36))),
}


def _json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resource_snapshot() -> dict[str, Any]:
    def usage(which: int) -> dict[str, Any]:
        value = resource.getrusage(which)
        return {
            "user_cpu_seconds": value.ru_utime,
            "system_cpu_seconds": value.ru_stime,
            "max_rss_kib": value.ru_maxrss,
            "minor_page_faults": value.ru_minflt,
            "major_page_faults": value.ru_majflt,
            "in_block": value.ru_inblock,
            "out_block": value.ru_oublock,
            "voluntary_context_switches": value.ru_nvcsw,
            "involuntary_context_switches": value.ru_nivcsw,
        }

    return {"self": usage(resource.RUSAGE_SELF), "children": usage(resource.RUSAGE_CHILDREN)}


def _canonical_xml(path: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    root = ET.parse(path).getroot()
    definition = root.find(".//definition")
    if definition is None:
        raise ValueError(f"missing geometry definition: {path}")

    def attrs(node: ET.Element) -> dict[str, str]:
        return {str(key): str(value) for key, value in sorted(node.attrib.items())}

    commands: list[dict[str, Any]] = []
    mainlist = root.find(".//mainlist")
    if mainlist is None:
        raise ValueError(f"missing mainlist: {path}")
    for node in mainlist:
        item: dict[str, Any] = {"tag": node.tag, "attrs": attrs(node)}
        children: list[dict[str, Any]] = []
        for child in node:
            children.append({"tag": child.tag, "attrs": attrs(child)})
        if children:
            item["children"] = children
        commands.append(item)

    parameters = {
        str(node.attrib["key"]): str(node.attrib["value"])
        for node in root.findall(".//execution/parameters/parameter")
        if "key" in node.attrib and "value" in node.attrib
    }
    physical_definition = {
        "pointmin": attrs(definition.find("pointmin")) if definition.find("pointmin") is not None else {},
        "pointmax": attrs(definition.find("pointmax")) if definition.find("pointmax") is not None else {},
    }
    # dp is numerical/discretization metadata and is intentionally excluded
    # from the continuous geometry signature.
    geometry_signature = {
        "physical_definition": physical_definition,
        "commands": commands,
        "constants": [
            {"tag": node.tag, "attrs": attrs(node)}
            for node in root.findall(".//constantsdef/*")
        ],
    }
    control_signature = {
        "constants": geometry_signature["constants"],
        "parameters": parameters,
        "motion": [
            {"tag": node.tag, "attrs": attrs(node)}
            for node in root.findall(".//motion")
        ],
    }
    data2d = root.find(".//data2d")
    flags = {
        "data2d": None if data2d is None else data2d.attrib.get("value"),
        "dp_m": float(definition.attrib["dp"]),
        "time_max_s": float(parameters.get("TimeMax", "nan")),
        "time_out_s": float(parameters.get("TimeOut", "nan")),
        "dt_fixed": float(parameters.get("DtFixed", "nan")),
    }
    return geometry_signature, control_signature, flags


def _normalise_box(node: ET.Element) -> tuple[str, tuple[float, ...], tuple[float, ...]]:
    fill_node = node.find("boxfill")
    point_node = node.find("point")
    size_node = node.find("size")
    if fill_node is None or point_node is None or size_node is None:
        raise ValueError("drawbox without boxfill/point/size")
    fill = (fill_node.text or "").strip()
    point = tuple(float(point_node.attrib[axis]) for axis in "xyz")
    size = tuple(float(size_node.attrib[axis]) for axis in "xyz")
    return fill, point, size


def _geometry_checks(xml_path: str | Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    geometry_signature, control_signature, flags = _canonical_xml(xml_path)
    mainlist = root.find(".//mainlist")
    assert mainlist is not None
    draws = [_normalise_box(node) for node in mainlist.findall("drawbox")]
    expected = [
        ("solid", (0.0, 0.0, 0.0), (0.4, 0.67, 0.3)),
        ("bottom | left | right | front | back", (0.0, 0.0, 0.0), (1.6, 0.67, 0.4)),
        ("solid", (0.9, 0.24, 0.0), (0.12, 0.12, 0.45)),
        ("top | left | right | front | back", (0.9, 0.24, 0.0), (0.12, 0.12, 0.45)),
    ]
    draw_checks: list[bool] = []
    for actual, wanted in zip(draws, expected):
        fill, point, size = actual
        draw_checks.append(
            fill == wanted[0]
            and all(math.isclose(x, y, abs_tol=1e-12) for x, y in zip(point, wanted[1]))
            and all(math.isclose(x, y, abs_tol=1e-12) for x, y in zip(size, wanted[2]))
        )
    return {
        "xml_sha256": _sha256(xml_path),
        "drawbox_count": len(draws),
        "expected_continuous_draws_match": bool(draw_checks == [True] * len(expected)),
        "drawbox_checks": draw_checks,
        "geometry_signature_sha256": hashlib.sha256(
            json.dumps(geometry_signature, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "control_signature_sha256": hashlib.sha256(
            json.dumps(control_signature, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "flags": flags,
    }


def _read_vtk_points(path: str | Path) -> np.ndarray:
    data = Path(path).read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\s*\n", data)
    if match is None:
        raise ValueError(f"binary VTK POINTS header not found: {path}")
    count = int(match.group(1))
    start = match.end()
    count_bytes = 3 * count * 4
    if len(data) < start + count_bytes:
        raise ValueError(f"truncated VTK point array: {path}")
    values = np.frombuffer(data, dtype=">f4", count=3 * count, offset=start).astype(np.float64)
    points = values.reshape((count, 3))
    if not np.isfinite(points).all():
        raise ValueError(f"nonfinite VTK point array: {path}")
    return points


def _face_metric(
    points: np.ndarray,
    name: str,
    axis: int,
    value: float,
    tangential_bounds: tuple[tuple[float, float], tuple[float, float]],
    dp: float,
) -> dict[str, Any]:
    tolerance = 0.51 * dp + 1e-8
    normal_distance = np.abs(points[:, axis] - value)
    near = normal_distance <= tolerance
    tangential = [index for index in range(3) if index != axis]
    inside = near.copy()
    strict = near.copy()
    for coordinate, (low, high) in zip(tangential, tangential_bounds):
        inside &= points[:, coordinate] >= low - tolerance
        inside &= points[:, coordinate] <= high + tolerance
        strict &= points[:, coordinate] >= low + tolerance
        strict &= points[:, coordinate] <= high - tolerance
    selected = points[inside]
    interior = points[strict]
    projected_ranges: list[list[float] | None] = []
    for coordinate in tangential:
        projected_ranges.append(
            None
            if len(selected) == 0
            else [float(selected[:, coordinate].min()), float(selected[:, coordinate].max())]
        )
    spans_ok = bool(
        len(selected) > 0
        and all(
            projected_ranges[index] is not None
            and projected_ranges[index][0] <= bounds[0] + dp + tolerance
            and projected_ranges[index][1] >= bounds[1] - dp - tolerance
            for index, bounds in enumerate(tangential_bounds)
        )
    )
    return {
        "axis": axis,
        "physical_value": value,
        "normal_tolerance_m": tolerance,
        "native_count_within_face": int(len(selected)),
        "native_interior_count": int(len(interior)),
        "projected_ranges_m": projected_ranges,
        "normal_distance_max_m": float(normal_distance[near].max()) if near.any() else None,
        "span_ok": spans_ok,
        "pass": bool(len(interior) > 0 and spans_ok),
    }


def _coverage(bound_vtk: str | Path, dp: float) -> dict[str, Any]:
    points = _read_vtk_points(bound_vtk)
    outer = {
        name: _face_metric(points, name, axis, value, bounds, dp)
        for name, (axis, value, bounds) in OUTER_FACES.items()
    }
    obstacle = {
        name: _face_metric(points, name, axis, value, bounds, dp)
        for name, (axis, value, bounds) in OBSTACLE_FACES.items()
    }
    return {
        "bound_vtk_sha256": _sha256(bound_vtk),
        "bound_point_count": int(len(points)),
        "finite_outer_faces": outer,
        "obstacle_wall_faces": obstacle,
        "all_five_outer_faces_pass": all(item["pass"] for item in outer.values()),
        "all_five_obstacle_faces_pass": all(item["pass"] for item in obstacle.values()),
        "static_particle_support_pass": all(item["pass"] for item in (*outer.values(), *obstacle.values())),
        "normal_vectors_checked": False,
        "normal_vectors_note": "Bound.vtk particle support only; solver normal vectors require a separate runtime/native audit.",
    }


def _gencase_receipt(path: str | Path) -> dict[str, Any]:
    value = _json(path)
    return {
        "sha256": _sha256(path),
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "fluid_particles": value.get("fluid_particles"),
        "total_particles": value.get("total_particles"),
        "solver_dimension_from_gencase": value.get("solver_dimension_from_gencase"),
        "input_hashes_at_launch": value.get("input_hashes_at_launch", {}),
    }


def _solver_run(path: str | Path, run_parts: str | Path) -> dict[str, Any]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    rows = [line.split(";") for line in lines if line and not line.startswith("#")]
    if len(lines) < 2:
        raise ValueError(f"solver Run.csv has no data row: {path}")
    header = lines[0].split(";")
    values = rows[0]
    row = dict(zip(header, values))
    part_lines = Path(run_parts).read_text(encoding="utf-8", errors="replace").splitlines()
    part_rows = [line.split(";") for line in part_lines if line and not line.startswith("#")]
    part_header = part_rows[0] if part_rows else []
    part_data = [dict(zip(part_header, value)) for value in part_rows[1:]]
    def number(key: str, default: float = float("nan")) -> float:
        raw = row.get(key, "")
        try:
            return float(raw.replace(",", ""))
        except (AttributeError, ValueError):
            return default

    out_values = []
    new_values = []
    for item in part_data:
        try:
            out_values.append(int(item.get("NpOut", "0").replace(",", "")))
            new_values.append(int(item.get("NpNew", "0").replace(",", "")))
        except ValueError:
            out_values.append(-1)
            new_values.append(-1)
    return {
        "run_csv_sha256": _sha256(path),
        "run_parts_sha256": _sha256(run_parts),
        "np": int(number("Np")),
        "steps": int(number("Steps")),
        "physical_time_s": number("PhysicalTime"),
        "part_files": int(number("PartFiles")),
        "parts_out": int(number("PartsOut")),
        "dp_m": number("Dp"),
        "n_bound": int(number("Nbound")),
        "n_fixed": int(number("Nfixed")),
        "configuration": row.get("Configuration"),
        "run_part_rows": len(part_data),
        "run_part_first_time_s": float(part_data[0].get("TimeStep [s]", "nan")) if part_data else None,
        "run_part_last_time_s": float(part_data[-1].get("TimeStep [s]", "nan")) if part_data else None,
        "npout_unique": sorted(set(out_values)),
        "npnew_unique": sorted(set(new_values)),
        "all_partsout_zero": bool(out_values) and all(value == 0 for value in out_values),
        "all_new_particles_zero": bool(new_values) and all(value == 0 for value in new_values),
        "explicit_3d_configuration": "3D" in (row.get("Configuration") or ""),
    }


def _hdf5_first_frame(path: str | Path, expected: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)
    with h5py.File(path, "r") as handle:
        required = [
            "density",
            "mass",
            "mk",
            "particle_id",
            "particle_zone",
            "position",
            "pressure",
            "time",
            "type",
            "valid",
            "velocity",
        ]
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"HDF5 missing datasets {missing}: {path}")
        shapes = {name: list(handle[name].shape) for name in required}
        valid = np.asarray(handle["valid"][0], dtype=bool)
        type_code = np.asarray(handle["type"][0])
        mass = np.asarray(handle["mass"][0], dtype=np.float64)
        density = np.asarray(handle["density"][0], dtype=np.float64)
        fluid = valid & (type_code == 3)
        zone = np.asarray(handle["particle_zone"][...])
        particle_id = np.asarray(handle["particle_id"][...])
        identity = np.stack((zone, particle_id), axis=1)
        unique_identity_count = int(np.unique(identity, axis=0).shape[0])
        initial_mass = float(mass[fluid].sum())
        active_mass = mass[valid]
        active_density = density[valid]
        attrs = {
            key: handle.attrs.get(key)
            for key in [
                "case_id",
                "resolution",
                "solver_dimension",
                "coordinate_frame",
                "geometry_sha256",
                "control_sha256",
                "conversion_complete",
                "conversion_complete_frames",
                "source_run_time_count",
                "source_run_time_end_s",
                "q_n_status",
            ]
        }
        frame_count = int(handle["time"].shape[0])
        particle_count = int(handle["particle_id"].shape[0])
        time_start = float(handle["time"][0])
        time_end = float(handle["time"][-1])
    expected_sha = expected.get("source_hdf5_sha256")
    expected_bytes = expected.get("source_hdf5_bytes")
    return {
        "path": str(path),
        "metadata_only_hash_policy": "whole HDF5 not rehashed by this audit; conversion-report SHA is recorded and checked for presence",
        "source_hdf5_sha256_from_conversion_report": expected_sha,
        "source_hdf5_bytes": path.stat().st_size,
        "source_hdf5_bytes_expected": expected_bytes,
        "source_hdf5_bytes_match": expected_bytes is None or path.stat().st_size == expected_bytes,
        "frames": frame_count,
        "particles": particle_count,
        "shapes": shapes,
        "time_start_s": time_start,
        "time_end_s": time_end,
        "initial_valid_count": int(valid.sum()),
        "initial_fluid_type3_count": int(fluid.sum()),
        "initial_type2_count": int((valid & (type_code == 2)).sum()),
        "initial_fluid_mass_kg": initial_mass,
        "initial_mass_per_fluid_particle_kg_min": float(mass[fluid].min()) if fluid.any() else None,
        "initial_mass_per_fluid_particle_kg_max": float(mass[fluid].max()) if fluid.any() else None,
        "active_mass_finite": bool(np.isfinite(active_mass).all()),
        "active_mass_positive": bool((active_mass > 0).all()),
        "active_density_finite": bool(np.isfinite(active_density).all()),
        "active_density_positive": bool((active_density > 0).all()),
        "typed_identity_unique": unique_identity_count == particle_count,
        "typed_identity_unique_count": unique_identity_count,
        "attrs": {
            key: (value.item() if isinstance(value, np.generic) else value)
            for key, value in attrs.items()
        },
    }


def _reference_case(case: dict[str, Any]) -> dict[str, Any]:
    xml_check = _geometry_checks(case["generated_xml"])
    flags = xml_check["flags"]
    receipt = _gencase_receipt(case["gencase_receipt"])
    run = _solver_run(case["run_csv"], case["run_parts_csv"])
    coverage = _coverage(case["bound_vtk"], flags["dp_m"])
    integrity = _json(case["integrity_report"])
    conversion = _json(case["conversion_report"])
    h5 = _hdf5_first_frame(
        case["trajectory_h5"],
        {
            "source_hdf5_sha256": conversion.get("output_hdf5_sha256"),
            "source_hdf5_bytes": conversion.get("output_hdf5_bytes"),
        },
    )
    initial_mass = h5["initial_fluid_mass_kg"]
    mass_error = (initial_mass - CONTINUOUS_FLUID_MASS_KG) / CONTINUOUS_FLUID_MASS_KG
    qi_lifecycle = integrity.get("lifecycle", {})
    ledger = integrity.get("fluid_mass_ledger", {})
    dimension = integrity.get("dimension_evidence", {})
    return {
        "case_id": case["case_id"],
        "resolution": case["resolution"],
        "declared_dp_m": case["dp_m"],
        "xml": xml_check,
        "gencase": receipt,
        "solver": run,
        "coverage": coverage,
        "integrity": {
            "q_i_status": integrity.get("q_i_status"),
            "q_n_status": integrity.get("q_n_status"),
            "missing_requirements": integrity.get("missing_requirements", []),
            "structural_failures": integrity.get("structural_failures", []),
            "dimension_evidence": dimension,
            "lifecycle": {
                key: qi_lifecycle.get(key)
                for key in [
                    "identity_axis",
                    "initial_active_count",
                    "final_active_count",
                    "ever_seen_count",
                    "introduced_after_initial_count",
                    "missing_at_any_later_frame_count",
                    "revived_identity_count",
                    "initial_missing_at_final_count",
                    "initial_to_final_retention",
                    "full_timeline_checked",
                ]
            },
            "fluid_mass_ledger": {
                key: ledger.get(key)
                for key in [
                    "status",
                    "type_code",
                    "initial_count",
                    "initial_mass_kg",
                    "final_initial_cohort_retained_count",
                    "initial_cohort_missing_at_final_count",
                    "solver_excluded_particles",
                    "separate_from_type2",
                ]
            },
            "closed_lifecycle_check": integrity.get("closed_lifecycle_check"),
        },
        "trajectory": h5,
        "natural_initial_mass": {
            "continuous_initial_mass_kg": CONTINUOUS_FLUID_MASS_KG,
            "native_type3_initial_mass_kg": initial_mass,
            "relative_error": mass_error,
            "mass_is_not_normalized": True,
        },
        "conversion": {
            "conversion_status": conversion.get("conversion_status"),
            "output_hdf5_sha256": conversion.get("output_hdf5_sha256"),
            "output_hdf5_bytes": conversion.get("output_hdf5_bytes"),
            "raw_source_unchanged": conversion.get("raw_source_unchanged"),
            "raw_source_tree_sha256_before": conversion.get("raw_source_tree_sha256_before"),
            "raw_source_tree_sha256_after": conversion.get("raw_source_tree_sha256_after"),
            "verification": conversion.get("verification"),
        },
    }


def _dense_event_reference(event: dict[str, Any]) -> dict[str, Any]:
    xml = _geometry_checks(event["generated_xml"])
    run = _solver_run(event["run_csv"], event["run_parts_csv"])
    coverage = _coverage(event["bound_vtk"], xml["flags"]["dp_m"])
    integrity = _json(event["integrity_report"])
    conversion = _json(event["conversion_report"])
    trajectory = _hdf5_first_frame(
        event["trajectory_h5"],
        {
            "source_hdf5_sha256": conversion.get("output_hdf5_sha256"),
            "source_hdf5_bytes": conversion.get("output_hdf5_bytes"),
        },
    )
    return {
        "case_id": event["case_id"],
        "event_window_s": 1.6,
        "save_interval_s": xml["flags"]["time_out_s"],
        "frames": run["part_files"],
        "physical_time_s": run["physical_time_s"],
        "run_parts_rows": run["run_part_rows"],
        "full_window_and_save_pass": bool(
            math.isclose(xml["flags"]["time_max_s"], 1.6, abs_tol=1e-9)
            and math.isclose(xml["flags"]["time_out_s"], 0.001, abs_tol=1e-12)
            and run["part_files"] == 1601
            and run["run_part_rows"] == 1601
            and run["parts_out"] == 0
            and run["all_partsout_zero"]
            and trajectory["frames"] == 1601
            and coverage["static_particle_support_pass"]
            and integrity.get("q_i_status") == "Q-I-structure-pass"
            and not integrity.get("missing_requirements")
            and not integrity.get("structural_failures")
        ),
        "generated_xml_sha256": xml["xml_sha256"],
        "coverage": coverage,
        "conversion_report_sha256": _sha256(event["conversion_report"]),
        "trajectory": trajectory,
        "q_i_status": integrity.get("q_i_status"),
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "source_hdf5_sha256": conversion.get("output_hdf5_sha256"),
        "source_hdf5_bytes": conversion.get("output_hdf5_bytes"),
        "conversion_status": conversion.get("conversion_status"),
        "source_raw_tree_sha256_before": conversion.get("raw_source_tree_sha256_before"),
        "source_raw_tree_sha256_after": conversion.get("raw_source_tree_sha256_after"),
        "limitations": [
            "dense reference is a root-reviewable complete-window input, not a Q-N result",
            "static Bound.vtk support is audited separately; solver normal vectors are not inferred",
            "trajectory HDF5 whole-file SHA is taken from the immutable conversion report and not recomputed by this audit",
        ],
    }


def audit_manifest(manifest_path: str | Path) -> dict[str, Any]:
    started = time.monotonic()
    resource_before = _resource_snapshot()
    manifest = _json(manifest_path)
    cases = [_reference_case(case) for case in manifest["reference_cases"]]
    event = _dense_event_reference(manifest["event_reference"])
    geometry_hashes = [item["trajectory"]["attrs"].get("geometry_sha256") for item in cases]
    control_hashes = [item["trajectory"]["attrs"].get("control_sha256") for item in cases]
    xml_geometry_hashes = [item["xml"]["geometry_signature_sha256"] for item in cases]
    xml_control_hashes = [item["xml"]["control_signature_sha256"] for item in cases]
    all_static_pass = all(
        item["coverage"]["static_particle_support_pass"]
        and item["xml"]["expected_continuous_draws_match"]
        and item["gencase"]["status"] == "completed"
        and item["gencase"]["returncode"] == 0
        and item["gencase"]["solver_dimension_from_gencase"] == 3
        and item["solver"]["explicit_3d_configuration"]
        and item["solver"]["parts_out"] == 0
        and item["solver"]["all_partsout_zero"]
        and item["trajectory"]["attrs"].get("solver_dimension") == 3
        and item["trajectory"]["attrs"].get("coordinate_frame")
        and item["trajectory"]["attrs"].get("conversion_complete_frames") == 161
        and item["trajectory"]["typed_identity_unique"]
        and item["trajectory"]["active_mass_finite"]
        and item["trajectory"]["active_mass_positive"]
        and item["trajectory"]["initial_type2_count"] == 0
        and item["integrity"]["q_i_status"] == "Q-I-structure-pass"
        and not item["integrity"]["missing_requirements"]
        and not item["integrity"]["structural_failures"]
        and item["integrity"]["dimension_evidence"].get("solver_dimension") == 3
        and item["integrity"]["lifecycle"].get("full_timeline_checked") is True
        and item["integrity"]["lifecycle"].get("missing_at_any_later_frame_count") == 0
        and item["integrity"]["lifecycle"].get("revived_identity_count") == 0
        for item in cases
    )
    continuous_binding_same = (
        len(set(geometry_hashes)) == 1
        and len(set(control_hashes)) == 1
        and len(set(xml_geometry_hashes)) == 1
        and len(set(xml_control_hashes)) == 1
    )
    source_unchanged = all(
        item["conversion"]["raw_source_unchanged"] is True
        and item["conversion"]["raw_source_tree_sha256_before"]
        == item["conversion"]["raw_source_tree_sha256_after"]
        for item in cases
    )
    result = {
        "schema": SCHEMA,
        "manifest": str(Path(manifest_path)),
        "family_id": "F1",
        "mechanism_id": "eccentric_obstacle",
        "audit_scope": "existing nominal coarse/medium/fine references plus existing fine dense event reference",
        "audit_status": "reuse_ready_for_root_review" if all_static_pass and event["full_window_and_save_pass"] else "blocked_by_input_audit",
        "q_i_status": "Q-I-structure-pass" if all_static_pass and event["full_window_and_save_pass"] else "Q-I-incomplete",
        "q_n_status": "not_assessed",
        "scientific_qualification_claim": "none",
        "production_eligibility": "not_evaluated",
        "continuous_binding": {
            "geometry_hashes": geometry_hashes,
            "control_hashes": control_hashes,
            "xml_geometry_signature_hashes": xml_geometry_hashes,
            "xml_control_signature_hashes": xml_control_hashes,
            "same_continuous_geometry_and_control": continuous_binding_same,
            "dp_is_numeric_only_in_comparison": True,
            "source_geometry": GEOMETRY,
            "boundary": "DBC",
            "motion": "static empty motion element",
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "open_top": True,
            "closed_outer_faces": ["x=0", "x=1.6", "y=0", "y=0.67", "z=0"],
            "obstacle_faces": ["x=0.9", "x=1.02", "y=0.24", "y=0.36", "z=0.45"],
        },
        "reference_cases": cases,
        "event_reference": event,
        "source_immutability": {
            "all_conversion_reports_source_unchanged": source_unchanged,
            "hdf5_hash_policy": "metadata-only read of HDF5; no whole-file rehash",
        },
        "root_action": {
            "reuse_existing_three_resolution_matrix": True,
            "reuse_existing_dense_event_reference": event["full_window_and_save_pass"],
            "new_gencase_required": False,
            "new_solver_required": False,
            "root_launch_authority": "root-only if a future rerun is explicitly scheduled",
        },
        "limitations": [
            "The three resolutions are structurally and physically bound to the same continuous recipe; this does not establish numerical Q-N convergence.",
            "Initial type-3 masses are retained at their native quadrature values; no mass normalization is applied.",
            "Static Bound.vtk particle support covers the five closed outer faces and five obstacle faces, but this audit does not infer or certify solver normal-vector quality.",
            "Existing .01 s spatial runs are reference-matrix evidence; the .001 s dense run is the complete-window event reference, and neither grants Q-N by itself.",
        ],
        "resource_usage": {
            "elapsed_wall_seconds": time.monotonic() - started,
            "before": resource_before,
            "after": _resource_snapshot(),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_manifest(args.manifest)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "audit_status": result["audit_status"],
        "q_i_status": result["q_i_status"],
        "q_n_status": result["q_n_status"],
        "reference_cases": len(result["reference_cases"]),
        "event_reference_ready": result["event_reference"]["full_window_and_save_pass"],
        "output": str(output),
    }, sort_keys=True))
    return 0 if result["audit_status"] == "reuse_ready_for_root_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
