#!/usr/bin/env python3
"""Audit the smallest external-validation path for the F4/F5 families.

This is deliberately a feasibility audit, not a solver runner and not a
physical acceptance gate.  It reads the already materialized custom probes,
official-example probes, their runtime summaries, and the reference assets
bundled with the official WaveRunup example.  The output makes the missing
observables, coordinate/time alignment work, and minimum next experiment
explicit before any large F4/F5 matrix is launched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-f45-external-feasibility.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-F45-EXTERNAL-FEASIBILITY.md"

CUSTOM_CASES = {
    "F4": ("F4_drop_onto_pool", "F4_head_on_columns", "F4_oblique_columns"),
    "F5": ("F5_low_weir", "F5_notched_weir", "F5_wet_bed_overtop"),
}
OFFICIAL_CASES = {
    "F4": ("O4_impinging_jet",),
    "F5": ("O5_solitary_wave", "O5_wave_runup", "O5_wave_runup_refined"),
}
REQUIRED_TRAJECTORY_DATASETS = (
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "density", "mass", "pressure", "type", "mk",
)


def sha256(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_fraction(values: np.ndarray, mask: np.ndarray | None = None) -> float:
    if mask is None:
        selected = values
    elif values.ndim == mask.ndim + 1 and values.shape[:-1] == mask.shape:
        # A vector field has one trailing component axis; select complete
        # vectors using the particle-validity mask.
        selected = values[mask]
    else:
        selected = values[mask]
    if selected.size == 0:
        return 1.0
    return float(np.isfinite(selected).mean())


def inspect_trajectory(path: Path, case_id: str, family: str) -> dict[str, Any]:
    """Summarize lifecycle and numerical fields without claiming physics."""

    path = Path(path)
    result: dict[str, Any] = {
        "case_id": case_id,
        "family": family,
        "path": str(path),
        "exists": path.is_file(),
        "structural_pass": False,
        "issues": [],
    }
    if not path.is_file():
        result["issues"] = ["normalized HDF5 is missing"]
        return result
    try:
        with h5py.File(path, "r") as h5:
            missing = [name for name in REQUIRED_TRAJECTORY_DATASETS if name not in h5]
            if missing:
                result["issues"] = [f"missing datasets: {missing}"]
                return result
            time = np.asarray(h5["time"][:], dtype=np.float64)
            particle_id = np.asarray(h5["particle_id"][:])
            particle_zone = np.asarray(h5["particle_zone"][:])
            valid = np.asarray(h5["valid"][:], dtype=bool)
            particle_type = np.asarray(h5["type"][:])
            issues: list[str] = []
            if time.ndim != 1 or len(time) < 2 or not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
                issues.append("time is not finite, strictly increasing, and at least two frames")
            if valid.shape != (len(time), len(particle_id)):
                issues.append("valid shape does not match time and identity axes")
            fluid = valid & (particle_type == 3)
            if particle_type.shape != valid.shape:
                issues.append("type shape does not match valid")
                fluid = valid
            field_finite = {}
            for name in ("position", "velocity", "density", "mass", "pressure"):
                values = np.asarray(h5[name][:])
                expected_shape = valid.shape + ((3,) if name in ("position", "velocity") else ())
                if values.shape != expected_shape:
                    issues.append(f"{name} shape is {values.shape}, expected {expected_shape}")
                    continue
                field_finite[name] = _finite_fraction(values, valid)
                if field_finite[name] < 1.0:
                    issues.append(f"{name} has non-finite values on valid rows")
            if len(np.unique(np.column_stack((particle_zone, particle_id)), axis=0)) != len(particle_id):
                issues.append("(particle_zone, particle_id) identity keys are not unique")
            valid_counts = valid.sum(axis=1).astype(int)
            fluid_counts = fluid.sum(axis=1).astype(int)
            initial_valid = int(valid_counts[0]) if len(valid_counts) else 0
            final_valid = int(valid_counts[-1]) if len(valid_counts) else 0
            initial_fluid = int(fluid_counts[0]) if len(fluid_counts) else 0
            final_fluid = int(fluid_counts[-1]) if len(fluid_counts) else 0
            present_any = valid.any(axis=0) if valid.ndim == 2 else np.zeros(len(particle_id), dtype=bool)
            introduced = int((~valid[0] & present_any).sum()) if valid.ndim == 2 and len(valid) else 0
            identity_mode = (
                "open_boundary_lifecycle"
                if introduced or initial_valid != final_valid or initial_fluid != final_fluid
                else "closed_fixed_identity"
            )
            result.update({
                "schema_version": str(h5.attrs.get("schema_version", "")),
                "mechanism": str(h5.attrs.get("mechanism", "")),
                "trajectory_semantics": str(h5.attrs.get("trajectory_semantics", "")),
                "frames": int(len(time)),
                "time_start_s": float(time[0]) if len(time) else None,
                "time_end_s": float(time[-1]) if len(time) else None,
                "output_dt_median_s": float(np.median(np.diff(time))) if len(time) > 1 else None,
                "identity_capacity": int(len(particle_id)),
                "initial_valid_particles": initial_valid,
                "final_valid_particles": final_valid,
                "initial_fluid_particles": initial_fluid,
                "final_fluid_particles": final_fluid,
                "introduced_identity_count": introduced,
                "final_initial_valid_retention": (
                    float(np.sum(valid[0] & valid[-1]) / initial_valid) if initial_valid else None
                ),
                "identity_mode": identity_mode,
                "valid_fraction_initial": float(valid[0].mean()) if len(valid) else None,
                "valid_fraction_final": float(valid[-1].mean()) if len(valid) else None,
                "field_finite_fraction_on_valid": field_finite,
                "structural_pass": not issues,
                "issues": issues,
            })
    except (OSError, ValueError, KeyError) as error:
        result["issues"] = [f"trajectory unreadable: {error}"]
    return result


def _numeric_rows(path: Path, *, delimiters: tuple[str, ...] = (" ", "\t")) -> tuple[list[str], np.ndarray]:
    """Read a simple whitespace/semicolon numeric table and retain its header."""

    lines = Path(path).read_text(errors="replace").splitlines()
    header = next((line.strip() for line in lines if line.strip()), "")
    rows: list[list[float]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = re.split(r"[\s;,]+", line)
        try:
            values = [float(value) for value in fields]
        except ValueError:
            continue
        if values:
            rows.append(values)
    if not rows:
        return [header], np.empty((0, 0), dtype=np.float64)
    width = len(rows[0])
    rows = [row for row in rows if len(row) == width]
    return [header], np.asarray(rows, dtype=np.float64)


def inspect_wave_reference(path: Path) -> dict[str, Any]:
    """Inspect the bundled CIEMito wave/run-up table as reference evidence."""

    path = Path(path)
    result: dict[str, Any] = {
        "path": str(path), "exists": path.is_file(), "sha256": sha256(path), "issues": [],
    }
    if not path.is_file():
        result["issues"] = ["external wave/run-up reference file is missing"]
        return result
    try:
        lines = path.read_text(errors="replace").splitlines()
        header_line = next((line.strip() for line in lines if line.strip()), "")
        header = re.split(r"[\s;,]+", header_line)
        rows = []
        for raw in lines[1:]:
            fields = re.split(r"[\s;,]+", raw.strip())
            try:
                values = [float(value) for value in fields]
            except ValueError:
                continue
            if len(values) == 6:
                rows.append(values)
        data = np.asarray(rows, dtype=np.float64)
        issues: list[str] = []
        time_non_decreasing = False
        time_strictly_increasing = False
        duplicate_time_count = 0
        duplicate_time_values: list[float] = []
        if data.ndim != 2 or data.shape[1] != 6:
            issues.append("reference table does not contain six numeric columns")
        elif len(data) < 2 or not np.all(np.isfinite(data)):
            issues.append("reference table is empty or contains non-finite values")
        else:
            dt = np.diff(data[:, 0])
            time_non_decreasing = bool(np.all(dt >= 0.0))
            time_strictly_increasing = bool(np.all(dt > 0.0))
            duplicate_mask = dt == 0.0
            duplicate_time_count = int(np.count_nonzero(duplicate_mask))
            if duplicate_time_count:
                duplicate_time_values = np.unique(data[:-1, 0][duplicate_mask]).tolist()
            if not time_non_decreasing:
                issues.append("reference time is not non-decreasing")
        if len(data) and data.shape[1] == 6:
            dt = np.diff(data[:, 0])
            wave = data[:, 1:5]
            runup = data[:, 5]
            event = np.max(np.abs(wave), axis=1) > 0.02
            runup_excursion = np.abs(runup - np.median(runup[: max(1, len(runup) // 20)])) > 0.01
            result.update({
                "header": header,
                "rows": int(len(data)),
                "columns": header,
                "time_start_s": float(data[0, 0]),
                "time_end_s": float(data[-1, 0]),
                "dt_median_s": float(np.median(dt)) if len(dt) else None,
                "dt_positive_median_s": float(np.median(dt[dt > 0.0])) if np.any(dt > 0.0) else None,
                "time_non_decreasing": time_non_decreasing,
                "time_strictly_increasing": time_strictly_increasing,
                "duplicate_time_count": duplicate_time_count,
                "duplicate_time_values_s": duplicate_time_values,
                "wave_gauge_count": 4,
                "wave_gauge_abs_max_m": np.max(np.abs(wave), axis=0).tolist(),
                "runup_min_m": float(runup.min()),
                "runup_max_m": float(runup.max()),
                "first_wave_event_abs_gt_0.02_s": float(data[event, 0][0]) if event.any() else None,
                "last_wave_event_abs_gt_0.02_s": float(data[event, 0][-1]) if event.any() else None,
                "first_runup_excursion_gt_0.01_s": float(data[runup_excursion, 0][0]) if runup_excursion.any() else None,
                "last_runup_excursion_gt_0.01_s": float(data[runup_excursion, 0][-1]) if runup_excursion.any() else None,
            })
        result["issues"] = issues
        result["structural_pass"] = not issues
    except OSError as error:
        result["issues"] = [f"reference file unreadable: {error}"]
    return result


def inspect_piston(path: Path) -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "sha256": sha256(path), "issues": []}
    if not path.is_file():
        result["issues"] = ["piston forcing file is missing"]
        return result
    _, data = _numeric_rows(path)
    if data.ndim != 2 or data.shape[1] != 2 or len(data) < 2 or not np.all(np.isfinite(data)):
        result["issues"] = ["piston forcing must be a finite two-column table"]
        return result
    dt = np.diff(data[:, 0])
    result.update({
        "rows": int(len(data)), "time_start_s": float(data[0, 0]), "time_end_s": float(data[-1, 0]),
        "dt_median_s": float(np.median(dt)) if len(dt) else None,
        "displacement_min_m": float(data[:, 1].min()), "displacement_max_m": float(data[:, 1].max()),
        "initial_duplicate_time_rows": int(np.sum(np.isclose(data[:, 0], data[0, 0]))),
        "structural_pass": bool(np.all(dt >= 0)),
    })
    if not result["structural_pass"]:
        result["issues"] = ["piston forcing time is not monotone"]
    return result


def inspect_wave_gauge_layout(path: Path) -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "sha256": sha256(path), "gauges": [], "issues": []}
    if not path.is_file():
        result["issues"] = ["wave-gauge layout file is missing"]
        return result
    current: dict[str, Any] | None = None
    try:
        lines = path.read_text(errors="replace").splitlines()
        for line in lines:
            match = re.search(r"POINTSLIST\s+#(WG\d+)", line)
            if match:
                current = {"name": match.group(1)}
                continue
            if current is not None and "point" not in current:
                values = re.split(r"\s+", line.strip())
                try:
                    if len(values) == 3:
                        current["point_m"] = [float(value) for value in values]
                        result["gauges"].append(current)
                        current = None
                except ValueError:
                    pass
        result["gauge_count"] = len(result["gauges"])
        if result["gauge_count"] != 4:
            result["issues"].append("expected four external wave-gauge points")
        result["structural_pass"] = not result["issues"]
    except OSError as error:
        result["issues"] = [f"wave-gauge layout unreadable: {error}"]
    return result


def inspect_runup_gauges(directory: Path) -> dict[str, Any]:
    directory = Path(directory)
    result: dict[str, Any] = {"directory": str(directory), "exists": directory.is_dir(), "gauges": [], "issues": []}
    if not directory.is_dir():
        result["issues"] = ["run-up gauge output directory is missing"]
        return result
    for path in sorted(directory.glob("GaugesSWL_Run-up*.csv")):
        try:
            with path.open(newline="") as stream:
                reader = csv.DictReader(stream, delimiter=";")
                rows = list(reader)
            required = {"time [s]", "swlx [m]", "swly [m]", "swlz [m]", "pos0x [m]", "pos0y [m]", "pos0z [m]", "pos2x [m]", "pos2y [m]", "pos2z [m]"}
            missing = sorted(required - set(reader.fieldnames or []))
            record: dict[str, Any] = {"path": str(path), "rows": len(rows), "issues": []}
            if missing:
                record["issues"].append(f"missing gauge columns: {missing}")
            else:
                time = np.asarray([float(row["time [s]"]) for row in rows])
                x = np.asarray([float(row["swlx [m]"]) for row in rows])
                z = np.asarray([float(row["swlz [m]"]) for row in rows])
                record.update({
                    "time_start_s": float(time[0]) if len(time) else None,
                    "time_end_s": float(time[-1]) if len(time) else None,
                    "dt_median_s": float(np.median(np.diff(time))) if len(time) > 1 else None,
                    "swl_x_min_m": float(x.min()) if len(x) else None,
                    "swl_x_max_m": float(x.max()) if len(x) else None,
                    "swl_z_min_m": float(z.min()) if len(z) else None,
                    "swl_z_max_m": float(z.max()) if len(z) else None,
                    "swl_dynamic": bool(len(z) > 1 and np.ptp(z) > 1e-6),
                })
                if len(time) < 2 or not np.all(np.diff(time) > 0):
                    record["issues"].append("gauge time is not strictly increasing")
            result["gauges"].append(record)
        except (OSError, ValueError) as error:
            result["issues"].append(f"{path.name}: unreadable gauge output: {error}")
    if len(result["gauges"]) != 7:
        result["issues"].append(f"expected seven run-up gauge outputs, found {len(result['gauges'])}")
    result["structural_pass"] = not result["issues"] and all(not item["issues"] for item in result["gauges"])
    return result


def inspect_model_runup_layout(xml_path: Path) -> dict[str, Any]:
    path = Path(xml_path)
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "gauges": [], "issues": []}
    if not path.is_file():
        result["issues"] = ["wave-runup XML definition is missing"]
        return result
    try:
        root = ET.parse(path).getroot()
        for node in root.findall(".//swl"):
            p0 = node.find("point0")
            p2 = node.find("point2")
            if p0 is None or p2 is None:
                result["issues"].append(f"{node.get('name', 'unnamed')}: missing point0/point2")
                continue
            result["gauges"].append({
                "name": node.get("name"),
                "point0_m": [float(p0.get(axis, "nan")) for axis in ("x", "y", "z")],
                "point2_m": [float(p2.get(axis, "nan")) for axis in ("x", "y", "z")],
            })
        result["gauge_count"] = len(result["gauges"])
        if result["gauge_count"] != 7:
            result["issues"].append(f"expected seven model run-up gauges, found {result['gauge_count']}")
        result["structural_pass"] = not result["issues"]
    except (OSError, ET.ParseError, ValueError) as error:
        result["issues"] = [f"run-up XML unreadable: {error}"]
    return result


def _runtime_map(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(item.get("id")): item for item in payload.get("cases", []) if item.get("id")}


def _trajectory_path(lab: Path, case_id: str, official: bool) -> Path:
    root = lab / ("data-official" if official else "data")
    return root / f"{case_id}.h5"


def _minimum_anchor(family: str) -> dict[str, Any]:
    common = {
        "track": "external_eulerian_observables; never particle-corresponded truth",
        "required_common_fields": [
            "run_id", "case_id", "source_definition_sha256", "solver_version", "dp_m",
            "time_s", "time_alignment_offset_s", "measurement_uncertainty",
        ],
        "numerical_acceptance": [
            "repeat the same physical case at three resolutions with fixed nondimensional inputs",
            "separate full-trace metrics from event-window metrics",
            "freeze observation cadence and report solver TimeOut independently",
            "retain raw solver output and exact external source checksums",
        ],
    }
    if family == "F4":
        return {
            **common,
            "status": "blocked_missing_external_reference",
            "anchor_type": "2D_or_3D_impinging_jet_impact_observable",
            "required_observables": [
                "time-resolved impact-wall pressure or integrated normal force",
                "inlet and outlet mass/volume flux",
                "jet centerline/width or impact footprint",
            ],
            "required_fields": [
                "wall_probe_id", "wall_position_m", "pressure_pa", "normal_force_n",
                "inlet_mass_flux_kg_s", "outlet_mass_flux_kg_s", "jet_centerline_m",
                "jet_width_m", "first_impact_time_s", "impact_impulse_ns",
            ],
            "execution_path": [
                "keep O4 CaseJet2D_Def as an isolated copy under lagrangian-fluid-lab",
                "add fixed wall pressure/force measurement and inlet/outlet flux extraction",
                "run a three-resolution first-impact matrix at fixed 20 m/s inlet and geometry",
                "convert fluid lifecycle plus observables; retain open-boundary birth/departure masks",
            ],
            "current_blockers": [
                "bundled O4 example has no experimental/reference measurement file",
                "current normalized O4 output contains particle pressure but no fixed wall probe or flux series",
                "O4 is a 2D open-boundary interface probe, not evidence for the custom 3D F4 family",
            ],
            "decision": "retain_custom_F4_as_mechanism_only_until_external_anchor_and_resolution_matrix_pass",
        }
    return {
        **common,
        "status": "partial_reference_but_not_aligned",
        "anchor_type": "wave_gauge_and_runup_time_series",
        "required_observables": [
            "four wave-gauge free-surface elevations",
            "run-up envelope or shoreline/run-up location",
            "piston displacement and velocity as the prescribed input",
        ],
        "required_fields": [
            "wave_gauge_id", "gauge_position_m", "time_s", "surface_elevation_m",
            "runup_height_m", "piston_displacement_m", "piston_velocity_m_s",
            "time_alignment_offset_s", "event_window_label",
        ],
        "execution_path": [
            "use O5_wave_runup_refined as the starting candidate; exclude coarse O5_wave_runup",
            "add wg1--wg4 at the external coordinates (3.10,3.20,3.34,3.63; y=0.18,z=0.075)",
            "run long enough to cover the bundled forcing/reference event (at least 16 s; 20 s preferred)",
            "set output and gauge cadence near the 0.02 s reference cadence and declare the time offset",
            "repeat three resolutions and compare full traces, first arrival, peak run-up, and return phase",
        ],
        "current_blockers": [
            "coarse O5_wave_runup loses 21,695 of 21,723 initial fluid identities and is already quality-failed",
            "current refined run stops at 4 s, before the dominant bundled wave/run-up excursion (about 5.13--15.2 s)",
            "external wg1--wg4 coordinates do not match the seven model SWL gauge lines",
            "current model gauge CSVs are only ten samples at about 0.4 s cadence; they cannot support the 0.02 s reference trace",
            "custom F5 weir probes have no external gauge or run-up observable files",
        ],
        "decision": "retain_refined_wave_runup_as_candidate_only; do_not_admit_custom_F5_until_aligned_anchor_passes",
    }


def build_report(lab_root: Path = LAB) -> dict[str, Any]:
    lab_root = Path(lab_root).resolve()
    runtime = lab_root / "reports" / "runtime"
    custom_runtime = _runtime_map(runtime / "trajectory-audit.json")
    official_runtime = _runtime_map(runtime / "official-trajectory-audit.json")
    custom_run = _runtime_map(runtime / "run-summary.json")
    official_run = _runtime_map(runtime / "official-run-summary.json")

    families: dict[str, Any] = {}
    for family in ("F4", "F5"):
        custom = []
        for case_id in CUSTOM_CASES[family]:
            item = inspect_trajectory(_trajectory_path(lab_root, case_id, False), case_id, family)
            item["runtime_audit"] = {key: custom_runtime.get(case_id, {}).get(key) for key in (
                "frames", "particles_initial", "particles_final", "identity_retention", "excluded_particles", "time_end",
            )}
            item["runtime_run"] = {key: custom_run.get(case_id, {}).get(key) for key in ("status", "frames")}
            custom.append(item)
        official = []
        for case_id in OFFICIAL_CASES[family]:
            item = inspect_trajectory(_trajectory_path(lab_root, case_id, True), case_id, family)
            item["runtime_audit"] = {key: official_runtime.get(case_id, {}).get(key) for key in (
                "frames", "particles_initial", "particles_final", "identity_retention", "excluded_particles", "time_end",
            )}
            item["runtime_run"] = {key: official_run.get(case_id, {}).get(key) for key in ("status", "frames", "excluded_particles")}
            official.append(item)
        families[family] = {"custom_probes": custom, "official_probes": official, "minimum_external_anchor": _minimum_anchor(family)}

    wave_dir = lab_root / "cases" / "official" / "O5_wave_runup" / "generated"
    refined_run_dir = lab_root / "runs-official" / "O5_wave_runup_refined"
    wave_reference = inspect_wave_reference(wave_dir / "EXP_CaseWaveRunup_CIEMito.txt")
    piston = inspect_piston(wave_dir / "Mov_piston.dat")
    external_layout = inspect_wave_gauge_layout(wave_dir / "wg1234.txt")
    model_layout = inspect_model_runup_layout(wave_dir / "CaseWaveRunup_Def.xml")
    model_gauges = {
        case_id: inspect_runup_gauges(lab_root / "runs-official" / case_id)
        for case_id in ("O5_wave_runup", "O5_wave_runup_refined")
    }
    external_points = [item.get("point_m") for item in external_layout.get("gauges", [])]
    model_points = [item.get("point0_m") for item in model_layout.get("gauges", [])]
    coordinate_match = any(
        np.allclose(external, model, atol=1e-9, rtol=0.0)
        for external in external_points for model in model_points
        if external is not None and model is not None
    )

    o4_dir = lab_root / "cases" / "official" / "O4_impinging_jet"
    o4_external_files = []
    for path in sorted(o4_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".csv", ".xls", ".xlsx", ".ods", ".pdf"}:
            continue
        if re.search(r"exp|reference|measure|gauge|pressure", path.name, flags=re.IGNORECASE):
            o4_external_files.append({"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size})
    xml_path = o4_dir / "generated" / "CaseJet2D_Def.xml"
    o4_inout_count = None
    o4_inlet_speed = None
    try:
        root = ET.parse(xml_path).getroot()
        o4_inout_count = len(root.findall(".//inoutzone"))
        speeds = [node.get("v") for node in root.findall(".//imposevelocity/velocity") if node.get("v") is not None]
        if speeds:
            raw_speed = speeds[0]
            if raw_speed.startswith("#"):
                variable = raw_speed[1:]
                # DualSPHysics stores scalar predefinitions as an attribute on
                # <newvarcte>, e.g. <newvarcte inletvel="20.0"/>.
                definitions = [
                    node.get(variable)
                    for node in root.findall(".//newvarcte")
                    if node.get(variable) is not None
                ]
                raw_speed = definitions[0] if definitions else None
            o4_inlet_speed = float(raw_speed) if raw_speed is not None else None
    except (OSError, ET.ParseError, ValueError):
        pass

    families["F4"]["official_reference_inventory"] = {
        "o4_case_definition": str(xml_path),
        "inout_zone_count": o4_inout_count,
        "configured_inlet_speed_m_s": o4_inlet_speed,
        "external_reference_files": o4_external_files,
        "external_reference_status": "missing" if not o4_external_files else "present_but_requires_mapping",
    }
    families["F5"]["official_reference_inventory"] = {
        "wave_reference": wave_reference,
        "piston_forcing": piston,
        "external_wave_gauge_layout": external_layout,
        "model_runup_gauge_layout": model_layout,
        "external_to_model_gauge_coordinate_match": bool(coordinate_match),
        "model_runup_gauge_outputs": model_gauges,
    }

    return {
        "schema_version": 1,
        "scope": "R3 F4/F5 minimum external-validation feasibility",
        "status": "candidate_only",
        "formal_release_authorized": False,
        "source_root": str(lab_root),
        "interpretation": (
            "This report establishes an executable observation/validation route. "
            "It does not promote any F4/F5 case to physical truth, Gold data, or a training/evaluation split."
        ),
        "families": families,
        "cross_family_contract": {
            "external_track_is_not_particle_corresponded": True,
            "minimum_resolution_levels": 3,
            "minimum_repeats": 2,
            "keep_open_boundary_lifecycle": True,
            "do_not_use_solver_success_as_physical_acceptance": True,
        },
        "next_gate": (
            "Only after F4 has an independently sourced impact/flux anchor and F5 has coordinate/time-aligned "
            "wave/run-up traces at a stable refined resolution may either family enter a development tranche."
        ),
    }


def conclusion(report: dict[str, Any]) -> str:
    f4 = report["families"]["F4"]
    f5 = report["families"]["F5"]
    f4_custom = f4["custom_probes"]
    f5_custom = f5["custom_probes"]
    f4_official = f4["official_probes"][0]
    f5_official = {item["case_id"]: item for item in f5["official_probes"]}
    ref = f5["official_reference_inventory"]["wave_reference"]
    return f"""# R3 F4/F5 外部验证可行性结论

状态：**candidate-only；没有任何正式数据准入**。

## 当前证据

| 家族 | 自建机制探针 | 官方/参考探针 | 当前判断 |
|---|---:|---:|---|
| F4 | {len(f4_custom)} 个，均为闭域 3D 机制探针 | O4 2D 开放边界，{f4_official['initial_fluid_particles']}→{f4_official['final_fluid_particles']} 个流体粒子 | 无外部观测文件，不能做物理验收 |
| F5 | {len(f5_custom)} 个闭域堰/越堤探针 | O5 refined {f5_official['O5_wave_runup_refined']['initial_fluid_particles']} 个初始流体粒子；粗版本已失败 | 有 CIEMito 参考文件，但坐标、时间窗和采样尚未对齐 |

## 最小可执行锚点

### F4

必须补一条与粒子不一一对应的外部观测轨道：冲击壁压力或法向合力、入口/出口通量，以及射流中心线/宽度或冲击足迹。每条观测必须带 `time_s`、测点坐标/ID、单位、测量不确定度、时间偏移、`dp_m`、solver/source checksum。当前 O4 只有 2D 开放边界求解；XML 中有 {f4['official_reference_inventory']['inout_zone_count']} 个 in/out zone、入口速度 {f4['official_reference_inventory']['configured_inlet_speed_m_s']} m/s，但仓库没有外部参考文件，也没有固定壁面测压/通量输出。

最小执行路径是复制 O4 定义到 lab 自有目录，加入壁面测量与通量导出，做三档分辨率和首撞击高频窗口；开放边界仍必须保留 `valid` 生命周期，不能用初末粒子保留率替代通量验证。

### F5

仓库已包含官方 WaveRunup 的 `EXP_CaseWaveRunup_CIEMito.txt`：{ref.get('rows')} 行、时间 {ref.get('time_start_s')}–{ref.get('time_end_s')} s、参考采样约 {ref.get('dt_median_s')} s，四个波高计和一列 run-up。`Mov_piston.dat` 还提供 0–15.6 s 的规定活塞位移。它是可复用的候选参考资产，但不是当前输出的 Gold 标签。

当前阻塞项：粗 O5 版本丢失 21,695/21,723 个初始流体身份；refined 只跑到 4 s，而参考的显著波动约从 {ref.get('first_wave_event_abs_gt_0.02_s')} s 开始并延续到约 {ref.get('last_wave_event_abs_gt_0.02_s')} s；外部 wg1–wg4 坐标与 XML 的七条 SWL 线不重合；现有模型 gauge CSV 约 0.4 s 采样，不能直接对齐 0.02 s 参考轨道。

参考时间列本身是有限且非递减的，但不是严格递增：检测到 {ref.get('duplicate_time_count')} 个重复时间戳（约从 10 s 起因按 0.1 s 舍入）。这不否定参考文件的结构可读性，但正式对齐前必须冻结策略：按原始行序列保留重复样本，或按时间戳明确聚合/去重；不能静默丢行或将其当作严格等间隔序列。

最小执行路径是以 refined 为起点，在 XML 中增加外部四个波高计位置，至少运行到 16 s（建议 20 s），将输出/测量 cadence 降到约 0.02 s，声明时间偏移，并以三分辨率报告全时程、首达、峰值 run-up 和返回阶段。自建 F5 堰案例在获得对应外部观测前只能保留为机制探针。

## 准入决策

- F4：`provisional_mechanism_only`；外部冲击/通量锚点和三分辨率矩阵通过前不进入 development tranche。
- F5：`provisional_high_risk`；只保留 refined WaveRunup 作为候选路线，粗版本作为失败对照，不把现有 gauge CSV 当作外部验证。
- F4/F5 的外部观测指标独立于粒子 rollout 指标，不能合并成一个排行榜分数。

机器可读证据见 `r3-f45-external-feasibility.json`；脚本为 `scripts/r3_f45_external_feasibility.py`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(conclusion(report))
    print(json.dumps({
        "status": report["status"],
        "formal_release_authorized": report["formal_release_authorized"],
        "F4_custom_structural": [item["structural_pass"] for item in report["families"]["F4"]["custom_probes"]],
        "F4_official_identity_mode": report["families"]["F4"]["official_probes"][0]["identity_mode"],
        "F5_external_reference_rows": report["families"]["F5"]["official_reference_inventory"]["wave_reference"].get("rows"),
        "F5_gauge_coordinate_match": report["families"]["F5"]["official_reference_inventory"]["external_to_model_gauge_coordinate_match"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
