#!/usr/bin/env python3
"""Run an isolated F4 impinging-jet observation-path probe.

The official ``08_ImpingingJet`` example is a small two-dimensional open-
boundary jet.  It is useful for testing whether the lab can preserve three
independent observation tracks:

* interpolated impact pressure/velocity at fixed points (``MeasureTool``),
* integrated force on the fixed wall (``ComputeForces``), and
* particle crossing counts/flux through inlet and outlet boxes (``FlowTool``).

This module deliberately does not turn any of those signals into a physical
gold label.  The official example has no experimental reference file in the
checkout, and the force/flow values are two-dimensional per-depth quantities.
All generated cases and raw runs live below ignored ``campaigns`` folders;
the upstream DualSPHysics tree is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np


LAB = Path(__file__).resolve().parents[1]
OFFICIAL = LAB / "vendor" / "official" / "DualSPHysics_v5.4"
SOURCE = OFFICIAL / "examples" / "inletoutlet" / "08_ImpingingJet"
BIN = OFFICIAL / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
MEASURE = BIN / "MeasureTool_linux64"
FORCES = BIN / "ComputeForces_linux64"
FLOW = BIN / "FlowTool_linux64"
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
WORK_ROOT = LAB / "campaigns" / "v0.1-candidate" / "cases" / "r3-f4-impinging-jet"
RUN_ROOT = LAB / "campaigns" / "v0.1-candidate" / "runs" / "r3-f4-impinging-jet"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-f4-impinging-observations.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-F4-IMPINGING-OBSERVATIONS.md"

# The official dp=0.001 case is retained as the middle member because it has
# already been exercised in the first official probe.  These values form a
# new fixed-physics candidate ladder; no threshold is implied by the names.
RESOLUTIONS: dict[str, float] = {
    "coarse": 0.0015,
    "medium": 0.0010,
    "fine": 0.00075,
}
DEFAULT_TMAX_S = 0.03
DEFAULT_TOUT_S = 0.0005

# Pressure probes are just above the fixed bottom wall (z=0); centreline
# probes expose the incoming jet before and after the first wall interaction.
IMPACT_POINTS: tuple[tuple[str, float, float, float], ...] = tuple(
    (f"impact_{index:02d}", x, 0.0, 0.001)
    for index, x in enumerate((-0.12, -0.08, -0.04, 0.0, 0.04, 0.08, 0.12))
)
CENTERLINE_POINTS: tuple[tuple[str, float, float, float], ...] = tuple(
    (f"centerline_{index:02d}", 0.0, 0.0, z)
    for index, z in enumerate((0.03, 0.06, 0.09, 0.11))
)
OBSERVATION_POINTS = IMPACT_POINTS + CENTERLINE_POINTS


def sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_token(value: float) -> str:
    return f"{value:.9g}".replace("-", "m").replace(".", "p")


def _run_tag(label: str, tmax_s: float, tout_s: float) -> str:
    return f"{label}__tmax-{_run_token(tmax_s)}__tout-{_run_token(tout_s)}"


def _gpu_inventory() -> dict[str, Any]:
    """Return the physical GPU allowlist without probing or changing devices."""

    if not INVENTORY.is_file():
        return {"allowed_gpu_indices": [4, 5, 6, 7], "gpu_uuids": {}}
    payload = json.loads(INVENTORY.read_text())
    allowed = set(payload.get("execution_policy", {}).get("allowed_gpu_uuids", []))
    mapping = {
        str(item["physical_index"]): item["uuid"]
        for item in payload.get("host", {}).get("gpus", [])
        if item.get("uuid") in allowed
    }
    return {"allowed_gpu_indices": sorted(int(key) for key in mapping), "gpu_uuids": mapping}


def configure_definition(source_xml: Path, target_xml: Path, *, tmax_s: float,
                         tout_s: float) -> dict[str, Any]:
    """Create a self-contained definition with an explicit observation cadence."""

    tree = ET.parse(source_xml)
    root = tree.getroot()
    parameters = root.find("./execution/parameters")
    if parameters is None:
        raise ValueError("impinging-jet definition has no execution/parameters")
    changed: dict[str, str] = {}
    for parameter in parameters.findall("parameter"):
        key = parameter.get("key")
        if key == "TimeMax":
            parameter.set("value", f"{tmax_s:.9g}")
            changed[key] = f"{tmax_s:.9g}"
        elif key == "TimeOut":
            parameter.set("value", f"{tout_s:.9g}")
            changed[key] = f"{tout_s:.9g}"
    if set(changed) != {"TimeMax", "TimeOut"}:
        raise ValueError(f"definition is missing TimeMax/TimeOut: {changed}")
    target_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target_xml, encoding="utf-8", xml_declaration=True)
    return {
        "source_xml": str(source_xml),
        "source_sha256": sha256(source_xml),
        "configured_xml": str(target_xml),
        "configured_sha256": sha256(target_xml),
        "time_max_s": tmax_s,
        "particle_output_cadence_s": tout_s,
        "changed_parameters": changed,
        "dimension": "2D",
        "entry_velocity_m_per_s": 20.0,
        "boundary_mk": 10,
    }


def prepare_case(label: str, dp_m: float, *, tmax_s: float, tout_s: float) -> dict[str, Any]:
    if not SOURCE.is_dir() or not GENCASE.is_file():
        raise FileNotFoundError(f"official impinging-jet source or GenCase missing under {SOURCE}")
    work = WORK_ROOT / label / "generated"
    shutil.copytree(SOURCE, work, dirs_exist_ok=True)
    source_xml = work / "CaseJet2D_Def.xml"
    configured_xml = work / f"CaseJet2D_{label}_Def.xml"
    definition = configure_definition(source_xml, configured_xml, tmax_s=tmax_s, tout_s=tout_s)
    prefix = work / f"F4_impinging_jet_{label}"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    started = time.monotonic()
    proc = subprocess.run(
        [str(GENCASE), str(configured_xml.with_suffix("")), str(prefix),
         f"-dp:{dp_m:.9g}", "-save:all"],
        cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    elapsed = time.monotonic() - started
    log = work / "gencase.log"
    log.write_text(proc.stdout)
    fluid = re.search(r"Fluid\.\.\.\.:\s+([0-9,]+)", proc.stdout)
    total = re.search(r"Total particles:\s+([0-9,]+)", proc.stdout)
    generated_xml = prefix.with_suffix(".xml")
    result = {
        "label": label,
        "dp_m": dp_m,
        "status": "prepared" if proc.returncode == 0 and generated_xml.is_file() else "prepare_failed",
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 4),
        "fluid_particles": int(fluid.group(1).replace(",", "")) if fluid else None,
        "total_particles": int(total.group(1).replace(",", "")) if total else None,
        "case_prefix": str(prefix.relative_to(LAB)),
        "generated_xml": str(generated_xml.relative_to(LAB)),
        "definition": definition,
        "log": str(log.relative_to(LAB)),
    }
    return result


def run_case(prepared: dict[str, Any], gpu: int, *, tmax_s: float, tout_s: float) -> dict[str, Any]:
    if prepared.get("status") != "prepared":
        raise ValueError(f"cannot run unprepared case {prepared.get('label')}")
    prefix = LAB / str(prepared["case_prefix"])
    output = RUN_ROOT / _run_tag(str(prepared["label"]), tmax_s, tout_s)
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    command = [str(SOLVER), f"-gpu:{gpu}", str(prefix), str(output),
               f"-tmax:{tmax_s:.9g}", f"-tout:{tout_s:.9g}"]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=prefix.parent, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    log = output / "solver.stdout.log"
    log.write_text(proc.stdout)
    parts = sorted(output.glob("data*/Part_*.bi4"))
    finished = "Finished execution (code=0)" in proc.stdout
    status = "completed" if proc.returncode == 0 and finished and parts else "run_failed"
    excluded = re.search(r"Excluded particles\.+:\s*([0-9,]+)", proc.stdout)
    return {
        **prepared,
        "status": status,
        "returncode": proc.returncode,
        "gpu": gpu,
        "output_dir": str(output.relative_to(LAB)),
        "elapsed_seconds": round(elapsed, 4),
        "frames": len(parts),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "output_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        "log": str(log.relative_to(LAB)),
        "command": command,
    }


def _pointsdef(points: Iterable[tuple[str, float, float, float]]) -> str:
    return ",".join(f"pt={x:.9g}:{y:.9g}:{z:.9g}" for _, x, y, z in points)


def _write_flow_boxes(path: Path, dp_m: float) -> dict[str, Any]:
    """Write 2-D boxes around the inlet and the two open outlets.

    The y thickness is one particle spacing on each side.  FlowTool detects
    2-D data and reports particle-volume/flow values per unit depth; keeping
    the geometry explicit makes this convention auditable rather than hiding
    it in a postprocessor.
    """

    thickness = max(dp_m, 1.0e-6)
    boxes = {
        "inlet": {"point": (-0.016, -thickness, 0.117), "size": (0.032, 2 * thickness, 0.011)},
        "left_outlet": {"point": (-0.205, -thickness, -0.001), "size": (0.011, 2 * thickness, 0.008)},
        "right_outlet": {"point": (0.194, -thickness, -0.001), "size": (0.011, 2 * thickness, 0.008)},
    }
    root = ET.Element("flowtool_boxes")
    for name, box in boxes.items():
        node = ET.SubElement(root, "boxsize", {"name": name})
        ET.SubElement(node, "point", {
            "x": f"{box['point'][0]:.9g}", "y": f"{box['point'][1]:.9g}",
            "z": f"{box['point'][2]:.9g}",
        })
        ET.SubElement(node, "size", {
            "x": f"{box['size'][0]:.9g}", "y": f"{box['size'][1]:.9g}",
            "z": f"{box['size'][2]:.9g}",
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "two_dimensional_per_depth": True,
        "boxes": boxes,
    }


def _run_tool(command: list[str], log_path: Path, *, cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=env)
    elapsed = time.monotonic() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout)
    return {
        "command": command,
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 4),
        "log": str(log_path.relative_to(LAB)),
        "status": "completed" if proc.returncode == 0 else "failed",
    }


def _numeric_csv(path: Path, marker: str = "Part;Time") -> tuple[list[str], np.ndarray]:
    """Read the numeric table after a DualSPHysics tool's metadata header."""

    path = Path(path)
    if not path.is_file():
        return [], np.empty((0, 0), dtype=np.float64)
    lines = path.read_text(errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines)
                         if line.startswith(marker)), None)
    if header_index is None:
        return [], np.empty((0, 0), dtype=np.float64)
    header = [field.strip() for field in lines[header_index].split(";")]
    rows: list[list[float]] = []
    for line in lines[header_index + 1:]:
        fields = [field.strip() for field in line.split(";")]
        try:
            row = [float(field) for field in fields]
        except ValueError:
            continue
        if len(row) == len(header):
            rows.append(row)
    return header, np.asarray(rows, dtype=np.float64)


def _measure_summary(path: Path, point_names: list[str], *, components: int = 1) -> dict[str, Any]:
    header, data = _numeric_csv(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "rows": int(len(data)),
        "columns": point_names,
        "components_per_point": components,
        "time_start_s": float(data[0, 1]) if len(data) else None,
        "time_end_s": float(data[-1, 1]) if len(data) else None,
        "dt_median_s": float(np.median(np.diff(data[:, 1]))) if len(data) > 1 else None,
        "finite_fraction": float(np.isfinite(data[:, 2:]).mean()) if len(data) else None,
        "issues": [],
    }
    if not path.is_file() or not header or len(data) < 2:
        result["issues"].append("measurement output has fewer than two numeric rows")
        return result
    expected_columns = 2 + len(point_names) * components
    if len(data[0]) != expected_columns:
        result["issues"].append("measurement column count does not match point manifest")
    if not np.all(np.diff(data[:, 1]) > 0):
        result["issues"].append("measurement time is not strictly increasing")
    values = data[:, 2:]
    peaks = []
    for index, name in enumerate(point_names):
        start = index * components
        stop = start + components
        if stop > values.shape[1]:
            continue
        point_values = values[:, start:stop]
        finite = np.all(np.isfinite(point_values), axis=1)
        if not np.any(finite):
            peaks.append({"name": name, "peak_abs": None, "peak_time_s": None})
            continue
        if components == 1:
            selected = np.where(finite, point_values[:, 0], np.nan)
            peak_index = int(np.nanargmax(np.abs(selected)))
            peaks.append({
                "name": name,
                "peak_abs": float(abs(selected[peak_index])),
                "peak_signed": float(selected[peak_index]),
                "peak_time_s": float(data[peak_index, 1]),
            })
        else:
            selected = np.where(finite[:, None], point_values, np.nan)
            magnitude = np.linalg.norm(selected, axis=1)
            peak_index = int(np.nanargmax(magnitude))
            peaks.append({
                "name": name,
                "peak_speed": float(magnitude[peak_index]),
                "peak_time_s": float(data[peak_index, 1]),
            })
    result["peaks"] = peaks
    result["issues"] = list(result["issues"])
    return result


def _force_summary(path: Path) -> dict[str, Any]:
    header, data = _numeric_csv(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "rows": int(len(data)),
        "header": header,
        "finite_fraction": float(np.isfinite(data).mean()) if len(data) else None,
        "units": "N/m for this 2-D case",
        "issues": [],
    }
    if len(data) < 2:
        result["issues"].append("force output has fewer than two numeric rows")
        return result
    result.update({
        "time_start_s": float(data[0, 1]),
        "time_end_s": float(data[-1, 1]),
        "dt_median_s": float(np.median(np.diff(data[:, 1]))),
    })
    # Columns are Part, time, Np, Fx, Fy, Fz, |F| in the v5.4 tool.
    if data.shape[1] >= 7:
        magnitude = data[:, 6]
        index = int(np.nanargmax(magnitude))
        result.update({
            "peak_force_abs_n_per_m": float(magnitude[index]),
            "peak_force_time_s": float(data[index, 1]),
            "peak_force_z_n_per_m": float(data[int(np.nanargmax(np.abs(data[:, 5]))), 5]),
        })
    return result


def _flow_summary(path: Path) -> dict[str, Any]:
    header, data = _numeric_csv(path, marker="Time [s]")
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "rows": int(len(data)),
        "header": header,
        "two_dimensional_per_depth": True,
        "issues": [],
    }
    if len(data) < 2:
        result["issues"].append("flow output has fewer than two numeric rows")
        return result
    result.update({
        "time_start_s": float(data[0, 0]),
        "time_end_s": float(data[-1, 0]),
        "dt_median_s": float(np.median(np.diff(data[:, 0]))),
        "finite_fraction": float(np.isfinite(data).mean()),
    })
    metrics: dict[str, Any] = {}
    for index, name in enumerate(header[1:], start=1):
        if index >= data.shape[1]:
            continue
        values = data[:, index]
        if not np.any(np.isfinite(values)):
            continue
        metrics[name] = {
            "max_abs": float(np.nanmax(np.abs(values))),
            "sum": float(np.nansum(values)),
        }
    result["columns"] = metrics
    return result


def _runparts_summary(path: Path) -> dict[str, Any]:
    """Summarize the solver's lifecycle bookkeeping without inferring identity."""

    lines = Path(path).read_text(errors="replace").splitlines() if Path(path).is_file() else []
    header_index = next((index for index, line in enumerate(lines)
                         if line.startswith("Part;TimeStep")), None)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "rows": 0,
        "issues": [],
        "identity_semantics": "solver numerical-node lifecycle only; not material lineage",
    }
    if header_index is None:
        result["issues"].append("RunPARTs.csv data header is missing")
        return result
    header = [field.strip() for field in lines[header_index].split(";")]
    rows: list[list[float]] = []
    for line in lines[header_index + 1:]:
        fields = [field.strip() for field in line.split(";")]
        try:
            row = [float(field.replace(",", "")) for field in fields]
        except ValueError:
            continue
        if len(row) == len(header):
            rows.append(row)
    data = np.asarray(rows, dtype=np.float64)
    result["rows"] = int(len(data))
    if len(data) < 2:
        result["issues"].append("RunPARTs.csv has fewer than two numeric rows")
        return result
    result["time_start_s"] = float(data[0, 1])
    result["time_end_s"] = float(data[-1, 1])
    result["dt_median_s"] = float(np.median(np.diff(data[:, 1])))
    indices = {name: header.index(name) for name in
               ("NpSave", "NpSim", "NpNew", "NpOut", "NpbSim", "NpfSim")
               if name in header}
    for name, index in indices.items():
        values = data[:, index]
        result[f"{name}_initial"] = int(values[0])
        result[f"{name}_final"] = int(values[-1])
        result[f"{name}_min"] = int(np.min(values))
        result[f"{name}_max"] = int(np.max(values))
        result[f"{name}_sum"] = int(np.sum(values))
    result["numerical_lifecycle_observed"] = bool(
        result.get("NpNew_sum", 0) > 0
        or result.get("NpOut_sum", 0) > 0
        or result.get("NpfSim_min") != result.get("NpfSim_max")
    )
    return result


def _aligned_series_error(left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
    """Compare two ``[time, value...]`` arrays on their common time interval."""

    if left.ndim != 2 or right.ndim != 2 or len(left) < 2 or len(right) < 2:
        return {"status": "insufficient_rows"}
    overlap_start = max(float(left[0, 0]), float(right[0, 0]))
    overlap_end = min(float(left[-1, 0]), float(right[-1, 0]))
    width = min(left.shape[1], right.shape[1]) - 1
    if width < 1 or overlap_end <= overlap_start:
        return {"status": "no_overlap"}
    samples = max(2, min(400, len(left), len(right)))
    grid = np.linspace(overlap_start, overlap_end, samples)
    left_values = np.column_stack([
        np.interp(grid, left[:, 0], left[:, index]) for index in range(1, width + 1)
    ])
    right_values = np.column_stack([
        np.interp(grid, right[:, 0], right[:, index]) for index in range(1, width + 1)
    ])
    delta = left_values - right_values
    rmse = np.sqrt(np.mean(delta ** 2, axis=0))
    max_abs = np.max(np.abs(delta), axis=0)
    scale = np.maximum(np.max(np.abs(right_values), axis=0), 1.0e-12)
    return {
        "status": "computed",
        "overlap_start_s": overlap_start,
        "overlap_end_s": overlap_end,
        "samples": samples,
        "rmse": rmse.tolist(),
        "max_abs": max_abs.tolist(),
        "relative_rmse": (rmse / scale).tolist(),
        "max_rmse": float(np.max(rmse)),
        "max_relative_rmse": float(np.max(rmse / scale)),
    }


def compare_resolution_matrix(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Expose cross-resolution sensitivity for the three observation tracks.

    The comparison is intentionally descriptive: no error threshold or
    convergence claim is encoded.  Pressure and wall-force columns are
    compared directly; flow columns use the common prefix so that a future
    tool-version change cannot silently fabricate a matching metric.
    """

    records = [run for run in runs
               if run.get("status") == "completed"
               and run.get("observations", {}).get("status") == "completed"]
    records.sort(key=lambda run: float(run.get("dp_m", 0.0)), reverse=True)
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(records):
        for right in records[left_index + 1:]:
            left_obs = LAB / str(left["output_dir"]) / "observations"
            right_obs = LAB / str(right["output_dir"]) / "observations"
            left_pressure = _numeric_csv(left_obs / "fixed_points_Press.csv")[1]
            right_pressure = _numeric_csv(right_obs / "fixed_points_Press.csv")[1]
            left_force = _numeric_csv(left_obs / "wall_force.csv")[1]
            right_force = _numeric_csv(right_obs / "wall_force.csv")[1]
            left_flow_header, left_flow = _numeric_csv(left_obs / "flow.csv", marker="Time [s]")
            right_flow_header, right_flow = _numeric_csv(right_obs / "flow.csv", marker="Time [s]")
            flow_names = [name for name in left_flow_header[1:] if name in right_flow_header[1:]]

            def select_flow(data: np.ndarray, header: list[str]) -> np.ndarray:
                if data.ndim != 2 or data.shape[1] == 0:
                    return np.empty((0, 0))
                indices = [header.index(name) for name in flow_names]
                return np.column_stack([data[:, 0], data[:, indices]]) if indices else np.empty((0, 0))

            pressure_error = _aligned_series_error(left_pressure[:, [1, *range(2, min(9, left_pressure.shape[1]))]]
                                                    if left_pressure.ndim == 2 and left_pressure.shape[1] > 2
                                                    else left_pressure,
                                                    right_pressure[:, [1, *range(2, min(9, right_pressure.shape[1]))]]
                                                    if right_pressure.ndim == 2 and right_pressure.shape[1] > 2
                                                    else right_pressure)
            force_error = _aligned_series_error(left_force[:, [1, 6]]
                                                 if left_force.ndim == 2 and left_force.shape[1] > 6
                                                 else left_force,
                                                 right_force[:, [1, 6]]
                                                 if right_force.ndim == 2 and right_force.shape[1] > 6
                                                 else right_force)
            flow_error = _aligned_series_error(select_flow(left_flow, left_flow_header),
                                                select_flow(right_flow, right_flow_header))
            pairs.append({
                "left": {"label": left["label"], "dp_m": left["dp_m"]},
                "right": {"label": right["label"], "dp_m": right["dp_m"]},
                "excluded_particles": {
                    "left": left.get("excluded_particles"),
                    "right": right.get("excluded_particles"),
                },
                "pressure_impact_points": pressure_error,
                "wall_force_magnitude": force_error,
                "flow_common_columns": flow_names,
                "flow": flow_error,
            })
    computed = [pair for pair in pairs if pair["pressure_impact_points"].get("status") == "computed"]
    return {
        "status": "diagnostic_only",
        "acceptance_threshold_declared": False,
        "pair_count": len(pairs),
        "computed_pair_count": len(computed),
        "pairs": pairs,
    }


def postprocess_case(run: dict[str, Any]) -> dict[str, Any]:
    """Run all three official postprocessors and summarize their CSV outputs."""

    if run.get("status") != "completed":
        return {"status": "skipped", "issues": ["solver run is not completed"]}
    output = LAB / str(run["output_dir"])
    data_dir = next((path for path in sorted(output.glob("data*")) if path.is_dir()), None)
    if data_dir is None:
        return {"status": "failed", "issues": ["solver data directory is missing"]}
    obs = output / "observations"
    obs.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    point_prefix = obs / "fixed_points"
    measure_command = [str(MEASURE), "-dirdata", str(data_dir), "-filexml", "AUTO",
                       f"-pointsdef:{_pointsdef(OBSERVATION_POINTS)}",
                       "-onlytype:-all,+fluid",
                       "-vars:-all,+vel,+press,+rhop,+kcorr",
                       "-savecsv", str(point_prefix)]
    measure = _run_tool(measure_command, obs / "measure.stdout.log", cwd=output)
    point_names = [point[0] for point in OBSERVATION_POINTS]
    pressure = _measure_summary(obs / "fixed_points_Press.csv", point_names)
    velocity = _measure_summary(obs / "fixed_points_Vel.csv", point_names, components=3)
    density = _measure_summary(obs / "fixed_points_Rhop.csv", point_names)
    kernel_correction = _measure_summary(obs / "fixed_points_Kcorr.csv", point_names)
    if kernel_correction["rows"]:
        _, kernel_data = _numeric_csv(obs / "fixed_points_Kcorr.csv")
        values = kernel_data[:, 2:]
        kernel_correction["minimum"] = float(np.nanmin(values))
        kernel_correction["maximum"] = float(np.nanmax(values))
        kernel_correction["zero_fraction"] = float(np.mean(np.isclose(values, 0.0)))
        kernel_correction["support_interpretation"] = (
            "Kcorr=0 can be an interpolation dummy when kernel support is insufficient; "
            "it must not be interpreted as a physical zero."
        )

    force_prefix = obs / "wall_force"
    force_command = [str(FORCES), "-dirdata", str(data_dir), "-filexml", "AUTO",
                     "-onlymk:10", "-viscoauto", "-savecsv", str(force_prefix)]
    forces = _run_tool(force_command, obs / "forces.stdout.log", cwd=output)
    force_summary = _force_summary(obs / "wall_force.csv")

    boxes = obs / "flow_boxes.xml"
    box_manifest = _write_flow_boxes(boxes, float(run["dp_m"]))
    flow_prefix = obs / "flow"
    flow_command = [str(FLOW), "-dirdata", str(data_dir), "-fileboxes", str(boxes),
                    "-savecsv", str(flow_prefix)]
    flow = _run_tool(flow_command, obs / "flow.stdout.log", cwd=output)
    flow_summary = _flow_summary(obs / "flow.csv")
    lifecycle = _runparts_summary(output / "RunPARTs.csv")
    return {
        "status": "completed" if all(item["status"] == "completed"
                                      for item in (measure, forces, flow)) else "partial",
        "data_dir": str(data_dir.relative_to(LAB)),
        "tools": {
            "measure": {**measure, "binary_sha256": sha256(MEASURE)},
            "compute_forces": {**forces, "binary_sha256": sha256(FORCES)},
            "flow": {**flow, "binary_sha256": sha256(FLOW)},
        },
        "fixed_points": {
            "points": [{"name": name, "position_m": [x, y, z]}
                       for name, x, y, z in OBSERVATION_POINTS],
            "pressure": pressure,
            "velocity": velocity,
            "density": density,
            "kernel_correction": kernel_correction,
        },
        "wall_force": force_summary,
        "flow_boxes": box_manifest,
        "flow": flow_summary,
        "lifecycle": lifecycle,
        "limitations": [
            "The force CSV is a two-dimensional per-depth wall integral, not a 3-D load.",
            "FlowTool counts numerical particles crossing boxes; it is not an external flow meter.",
            "No experimental pressure, force, or flux reference is bundled with O4.",
        ],
    }


def build_report(prepared: Iterable[dict[str, Any]], runs: Iterable[dict[str, Any]], *,
                 tmax_s: float, tout_s: float) -> dict[str, Any]:
    prepared = list(prepared)
    report_runs = []
    for run in runs:
        item = dict(run)
        item["observations"] = postprocess_case(run)
        report_runs.append(item)
    completed = sum(item.get("status") == "completed" for item in report_runs)
    return {
        "schema_version": 1,
        "scope": "R3 F4 official impinging-jet observation-path probe",
        "execution_status": "complete" if completed == len(report_runs) and report_runs else "partial",
        "acceptance_status": "candidate_observations_only",
        "validation_scope": [
            "fixed-point impact pressure/velocity interpolation",
            "two-dimensional wall-force postprocessing",
            "open-boundary inlet/outlet particle-flow bookkeeping",
            "three-resolution cadence smoke matrix",
        ],
        "formal_release_authorized": False,
        "upstream_source": {
            "case_definition": str((SOURCE / "CaseJet2D_Def.xml").relative_to(LAB)),
            "case_definition_sha256": sha256(SOURCE / "CaseJet2D_Def.xml"),
            "solver_binary_sha256": sha256(SOLVER),
            "gencase_binary_sha256": sha256(GENCASE),
        },
        "observation_contract": {
            "dimension": "2D",
            "entry_velocity_m_per_s": 20.0,
            "wall_force_units": "N/m",
            "flow_units": "per-depth particle-volume/flow; FlowTool header may be unspecified for 2D",
            "pressure_units": "Pa",
            "kernel_correction_required": True,
            "particle_output_cadence_s": tout_s,
            "requested_time_end_s": tmax_s,
            "fixed_point_count": len(OBSERVATION_POINTS),
            "open_boundary_lifecycle_required": True,
        },
        "resolution_policy": {
            "candidate_ladder_m": dict(RESOLUTIONS),
            "fixed_physics_required": True,
            "no_admission_threshold_declared": True,
        },
        "gpu_policy": _gpu_inventory(),
        "prepared_cases": prepared,
        "runs": report_runs,
        "resolution_comparison": compare_resolution_matrix(report_runs),
        "open_blockers": [
            "No external pressure, force, or flux anchor is present for O4.",
            "A 3-D F4 case is still needed before a 3-D family admission decision.",
            "Force and flow conventions require an independently declared uncertainty model.",
            "Particle crossing counts cannot replace material-lineage validation.",
        ],
    }


def render_conclusion(report: dict[str, Any]) -> str:
    runs = report.get("runs", [])
    completed = sum(run.get("status") == "completed" for run in runs)
    postprocessed = sum(run.get("observations", {}).get("status") == "completed" for run in runs)
    comparison = report.get("resolution_comparison", {})
    pair_count = comparison.get("pair_count", 0)
    return f"""# R3 F4 撞击射流观测链路探针

状态：**candidate-only；不授权正式数据发布**。

本探针隔离复制官方 `inletoutlet/08_ImpingingJet`，固定入口速度 20 m/s，
并验证三种彼此独立的观测输出：固定点冲击压力/速度/密度（同时记录 Kcorr 支持度）、底壁二维合力、
以及入口和左右出口的粒子通量。当前完成 {completed}/{len(runs)} 个 solver 运行，
其中 {postprocessed}/{len(runs)} 个完成三条后处理链，形成 {pair_count} 个跨分辨率比较对。

分辨率候选为 {', '.join(f'{k}={v:g} m' for k, v in RESOLUTIONS.items())}，
输出 cadence 为 {report.get('observation_contract', {}).get('particle_output_cadence_s')} s。
这些数值用于验证数据路径和暴露离散敏感性，不是收敛阈值；壁面合力是二维 N/m，
FlowTool 流量是每单位深度的粒子体积/流量。

官方 O4 没有配套实验压力、合力或流量文件，因此本轮只能证明“可观测、可记录、
可追溯”，不能证明物理正确性。F4 正式准入仍阻塞于外部锚点、三维实现、
不确定度/时间对齐规则，以及独立于节点生命周期的材料谱系验证。

机器可读详情见 `r3-f4-impinging-observations.json`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolutions", nargs="+", choices=sorted(RESOLUTIONS),
                        default=list(RESOLUTIONS))
    parser.add_argument("--gpus", nargs="+", type=int, default=[4, 5, 6])
    parser.add_argument("--tmax", type=float, default=DEFAULT_TMAX_S)
    parser.add_argument("--tout", type=float, default=DEFAULT_TOUT_S)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--postprocess-existing", type=Path,
                        help="refresh observations for runs in an existing report")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    if args.tmax <= 0 or args.tout <= 0:
        parser.error("tmax and tout must be positive")
    policy = _gpu_inventory()
    disallowed = sorted(set(args.gpus) - set(policy["allowed_gpu_indices"]))
    if disallowed:
        parser.error(f"GPU indices are outside the physical allowlist: {disallowed}")
    if args.postprocess_existing:
        source_report = args.postprocess_existing
        if not source_report.is_file():
            parser.error(f"existing report not found: {source_report}")
        report = json.loads(source_report.read_text())
        for run in report.get("runs", []):
            run["observations"] = postprocess_case(run)
        report["resolution_comparison"] = compare_resolution_matrix(report.get("runs", []))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        args.conclusion.parent.mkdir(parents=True, exist_ok=True)
        args.conclusion.write_text(render_conclusion(report))
        return 0

    prepared = [prepare_case(label, RESOLUTIONS[label], tmax_s=args.tmax, tout_s=args.tout)
                for label in args.resolutions]
    runs: list[dict[str, Any]] = []
    if args.run:
        for index, item in enumerate(prepared):
            runs.append(run_case(item, args.gpus[index % len(args.gpus)],
                                 tmax_s=args.tmax, tout_s=args.tout))
    report = build_report(prepared, runs, tmax_s=args.tmax, tout_s=args.tout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(render_conclusion(report))
    print(json.dumps({
        "execution_status": report["execution_status"],
        "acceptance_status": report["acceptance_status"],
        "prepared": len(prepared),
        "run_count": len(runs),
        "completed": sum(item.get("status") == "completed" for item in runs),
        "allowed_gpu_indices": policy["allowed_gpu_indices"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
