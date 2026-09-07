#!/usr/bin/env python3
"""Run an isolated 3-D F4 head-on liquid-column observation probe.

The source case is a small, closed 3-D collision of two finite liquid columns.
This module copies its definition into the candidate campaign area, generates
three explicit particle resolutions, runs the GPU solver when requested, and
records two independent observation paths:

* fixed-point ``MeasureTool`` histories for pressure, velocity, density and
  kernel correction (Kcorr); and
* ``ComputeForces`` for the explicitly requested ``mk=10`` target.

The current source definition maps ``mkbound=0`` to generated physical
``Mk=17`` under DualSPHysics v5.4.  The requested ``mk=10`` command is still
run verbatim so this mismatch is visible.  If it fails because no Mk=10
particles exist, an effective generated boundary Mk is run as a clearly
labelled diagnostic fallback; the fallback never upgrades the candidate to
physical acceptance.

All generated definitions, solver output, and postprocessor output are below
``campaigns/v0.1-candidate``.  The upstream ``cases/F4`` source is read only.
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
SOURCE = LAB / "cases" / "F4" / "F4_head_on_columns" / "F4_head_on_columns_Def.xml"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
MEASURE = BIN / "MeasureTool_linux64"
FORCES = BIN / "ComputeForces_linux64"
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
WORK_ROOT = LAB / "campaigns" / "v0.1-candidate" / "cases" / "r3-f4-3d-head-on"
RUN_ROOT = LAB / "campaigns" / "v0.1-candidate" / "runs" / "r3-f4-3d-head-on"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-f4-3d-head-on.json"
DEFAULT_CONCLUSION = LAB / "campaigns" / "v0.1-candidate" / "R3-F4-3D-HEAD-ON.md"

RESOLUTIONS: dict[str, float] = {
    "coarse": 0.04,
    "medium": 0.03,
    "fine": 0.02,
}
DEFAULT_TMAX_S = 0.55
DEFAULT_TOUT_S = 0.01
REQUESTED_FORCE_MK = 10

# Fixed world points span the two initial columns, the first collision region,
# and two off-centre collision samples.  They are probes, not truth labels.
OBSERVATION_POINTS: tuple[tuple[str, float, float, float], ...] = (
    ("left_column_center", 0.23, 0.20, 0.33),
    ("right_column_center", 0.97, 0.20, 0.33),
    ("left_leading_face", 0.33, 0.20, 0.33),
    ("right_leading_face", 0.87, 0.20, 0.33),
    ("collision_center", 0.60, 0.20, 0.33),
    ("collision_lower", 0.60, 0.20, 0.27),
    ("collision_upper", 0.60, 0.20, 0.39),
)


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
    """Read the immutable campaign allowlist and retain physical indices/UUIDs."""

    if not INVENTORY.is_file():
        return {"allowed_gpu_indices": [4, 5, 6, 7], "gpu_uuids": {}, "source": None}
    payload = json.loads(INVENTORY.read_text())
    allowed = set(payload.get("execution_policy", {}).get("allowed_gpu_uuids", []))
    mapping = {
        str(item["physical_index"]): item["uuid"]
        for item in payload.get("host", {}).get("gpus", [])
        if item.get("uuid") in allowed
    }
    return {
        "allowed_gpu_indices": sorted(int(key) for key in mapping),
        "gpu_uuids": mapping,
        "source": str(INVENTORY.relative_to(LAB)),
    }


def validate_gpu_indices(gpus: Iterable[int]) -> dict[str, Any]:
    requested = [int(gpu) for gpu in gpus]
    if not requested:
        raise ValueError("at least one GPU must be provided")
    policy = _gpu_inventory()
    disallowed = sorted(set(requested) - set(policy["allowed_gpu_indices"]))
    if disallowed:
        raise ValueError(
            f"GPU indices are outside the physical allowlist: {disallowed}; "
            f"allowed={policy['allowed_gpu_indices']}"
        )
    return policy


def _definition_parameters(root: ET.Element) -> dict[str, ET.Element]:
    parameters = root.findall("./execution/parameters/parameter")
    return {str(parameter.get("key")): parameter for parameter in parameters}


def configure_definition(
    source_xml: Path,
    target_xml: Path,
    *,
    tmax_s: float,
    tout_s: float,
) -> dict[str, Any]:
    """Copy a definition and make solver/output times explicit."""

    if tmax_s <= 0 or tout_s <= 0:
        raise ValueError("tmax and tout must be positive")
    source_xml = Path(source_xml)
    tree = ET.parse(source_xml)
    root = tree.getroot()
    parameters = _definition_parameters(root)
    changed: dict[str, str] = {}
    for key, value in (("TimeMax", tmax_s), ("TimeOut", tout_s)):
        parameter = parameters.get(key)
        if parameter is None:
            raise ValueError(f"definition is missing execution parameter {key}")
        rendered = f"{value:.9g}"
        parameter.set("value", rendered)
        changed[key] = rendered
    target_xml = Path(target_xml)
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
        "dimension": "3D",
        "fluid_initial_velocities_m_per_s": {
            "mkfluid:0": [1.0, 0.0, 0.0],
            "mkfluid:1": [-1.0, 0.0, 0.0],
        },
        "requested_compute_forces_mk": REQUESTED_FORCE_MK,
    }


def _parse_summary_count(output: str, label: str) -> int | None:
    match = re.search(rf"{re.escape(label)}\.*:\s*([0-9,]+)", output)
    return int(match.group(1).replace(",", "")) if match else None


def parse_generated_particle_mks(path: Path) -> dict[str, Any]:
    """Extract generated physical Mk values and source mkbound mappings."""

    root = ET.parse(Path(path)).getroot()
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError(f"generated XML has no execution/particles: {path}")
    fixed = []
    fluid = []
    for item in particles:
        if item.tag == "fixed":
            fixed.append({
                "mkbound": int(item.attrib["mkbound"]),
                "mk": int(item.attrib["mk"]),
                "count": int(item.attrib.get("count", 0)),
            })
        elif item.tag == "fluid":
            fluid.append({
                "mkfluid": int(item.attrib["mkfluid"]),
                "mk": int(item.attrib["mk"]),
                "count": int(item.attrib.get("count", 0)),
            })
    if not fixed or not fluid:
        raise ValueError(f"generated XML lacks fixed/fluid blocks: {path}")
    return {
        "mkboundfirst": int(particles.attrib.get("mkboundfirst", fixed[0]["mk"])),
        "mkfluidfirst": int(particles.attrib.get("mkfluidfirst", fluid[0]["mk"])),
        "fixed": fixed,
        "fluid": fluid,
        "effective_boundary_mks": sorted({item["mk"] for item in fixed}),
        "effective_fluid_mks": sorted({item["mk"] for item in fluid}),
    }


def prepare_case(label: str, dp_m: float, *, tmax_s: float, tout_s: float) -> dict[str, Any]:
    """Generate one resolution in a fresh, isolated candidate directory."""

    if not SOURCE.is_file():
        raise FileNotFoundError(f"F4 head-on source definition is missing: {SOURCE}")
    if not GENCASE.is_file():
        raise FileNotFoundError(f"GenCase binary is missing: {GENCASE}")
    if dp_m <= 0:
        raise ValueError("dp must be positive")
    case_tag = f"{label}__dp-{_run_token(dp_m)}__tmax-{_run_token(tmax_s)}__tout-{_run_token(tout_s)}"
    work = WORK_ROOT / case_tag
    input_dir = work / "input"
    configured_dir = work / "configured"
    generated_dir = work / "generated"
    input_dir.mkdir(parents=True, exist_ok=True)
    configured_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    isolated_source = input_dir / SOURCE.name
    shutil.copy2(SOURCE, isolated_source)
    # Keep the configured definition and GenCase log in reviewable, non-ignored
    # provenance directories; only generated particle files belong below the
    # campaign's ignored ``generated`` directory.
    configured_xml = configured_dir / f"F4_head_on_columns_{label}_Def.xml"
    definition = configure_definition(isolated_source, configured_xml, tmax_s=tmax_s, tout_s=tout_s)
    prefix = generated_dir / f"F4_head_on_columns_{label}"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    command = [
        str(GENCASE), str(configured_xml.with_suffix("")), str(prefix),
        f"-dp:{dp_m:.9g}", "-save:all",
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=generated_dir, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = proc.stdout
        returncode = proc.returncode
    except OSError as error:
        output = f"{type(error).__name__}: {error}"
        returncode = -1
    elapsed = time.monotonic() - started
    log = work / "gencase.stdout.log"
    log.write_text(output)
    generated_xml = prefix.with_suffix(".xml")
    status = "prepared" if returncode == 0 and generated_xml.is_file() else "prepare_failed"
    mks = None
    issues: list[str] = []
    if status == "prepared":
        try:
            mks = parse_generated_particle_mks(generated_xml)
        except (OSError, ValueError, ET.ParseError) as error:
            issues.append(f"generated Mk mapping unreadable: {error}")
            status = "prepare_failed"
    if REQUESTED_FORCE_MK not in (mks or {}).get("effective_boundary_mks", []):
        issues.append(
            f"requested ComputeForces Mk={REQUESTED_FORCE_MK} is absent from generated "
            f"boundary Mks={(mks or {}).get('effective_boundary_mks', [])}"
        )
    return {
        "label": label,
        "dp_m": dp_m,
        "status": status,
        "returncode": returncode,
        "elapsed_seconds": round(elapsed, 4),
        "fluid_particles": _parse_summary_count(output, "Fluid"),
        "total_particles": _parse_summary_count(output, "Total particles"),
        "case_prefix": str(prefix.relative_to(LAB)),
        "isolated_source": str(isolated_source.relative_to(LAB)),
        "generated_xml": str(generated_xml.relative_to(LAB)),
        "definition": definition,
        "generated_particle_mks": mks,
        "log": str(log.relative_to(LAB)),
        "command": command,
        "issues": issues,
    }


def run_case(prepared: dict[str, Any], gpu: int, *, tmax_s: float, tout_s: float) -> dict[str, Any]:
    """Run one prepared case on an explicitly allowlisted physical GPU."""

    if prepared.get("status") != "prepared":
        raise ValueError(f"cannot run unprepared case {prepared.get('label')}")
    policy = validate_gpu_indices([gpu])
    prefix = LAB / str(prepared["case_prefix"])
    output = RUN_ROOT / _run_tag(str(prepared["label"]), tmax_s, tout_s)
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    command = [str(SOLVER), f"-gpu:{gpu}", str(prefix), str(output),
               f"-tmax:{tmax_s:.9g}", f"-tout:{tout_s:.9g}"]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=prefix.parent, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output_text = proc.stdout
        returncode = proc.returncode
    except OSError as error:
        output_text = f"{type(error).__name__}: {error}"
        returncode = -1
    elapsed = time.monotonic() - started
    log = output / "solver.stdout.log"
    log.write_text(output_text)
    parts = sorted(output.glob("data*/Part_*.bi4"))
    finished = "Finished execution (code=0)" in output_text
    status = "completed" if returncode == 0 and finished and parts else "run_failed"
    return {
        **prepared,
        "status": status,
        "returncode": returncode,
        "gpu": gpu,
        "gpu_uuid": policy["gpu_uuids"].get(str(gpu)),
        "output_dir": str(output.relative_to(LAB)),
        "elapsed_seconds": round(elapsed, 4),
        "frames": len(parts),
        "excluded_particles": _parse_summary_count(output_text, "Excluded particles"),
        "output_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        "log": str(log.relative_to(LAB)),
        "command": command,
    }


def _pointsdef(points: Iterable[tuple[str, float, float, float]]) -> str:
    return ",".join(f"pt={x:.9g}:{y:.9g}:{z:.9g}" for _, x, y, z in points)


def _run_tool(command: list[str], log_path: Path, *, cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    try:
        proc = subprocess.run(
            command, cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=env,
        )
        output = proc.stdout
        returncode = proc.returncode
    except OSError as error:
        output = f"{type(error).__name__}: {error}"
        returncode = -1
    elapsed = time.monotonic() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output)
    return {
        "command": command,
        "returncode": returncode,
        "elapsed_seconds": round(elapsed, 4),
        "log": str(log_path.relative_to(LAB)),
        "status": "completed" if returncode == 0 else "failed",
        "stdout_tail": output[-1200:],
    }


def _numeric_csv(path: Path) -> tuple[list[str], np.ndarray]:
    """Read a DualSPHysics semicolon/comma table after its metadata header."""

    path = Path(path)
    if not path.is_file():
        return [], np.empty((0, 0), dtype=np.float64)
    lines = path.read_text(errors="replace").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines)
         if line.startswith("Part;") or line.startswith("Part,")),
        None,
    )
    if header_index is None:
        return [], np.empty((0, 0), dtype=np.float64)
    delimiter = ";" if ";" in lines[header_index] else ","
    header = [field.strip() for field in lines[header_index].split(delimiter)]
    rows: list[list[float]] = []
    for line in lines[header_index + 1:]:
        fields = [field.strip() for field in line.split(delimiter)]
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
    if data.shape[1] != expected_columns:
        result["issues"].append("measurement column count does not match point manifest")
    if not np.all(np.isfinite(data[:, :2])):
        result["issues"].append("measurement part/time columns are non-finite")
    if not np.all(np.diff(data[:, 1]) > 0):
        result["issues"].append("measurement time is not strictly increasing")
    values = data[:, 2:]
    peaks: list[dict[str, Any]] = []
    for index, name in enumerate(point_names):
        start, stop = index * components, (index + 1) * components
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
    return result


def _force_summary(path: Path) -> dict[str, Any]:
    header, data = _numeric_csv(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "rows": int(len(data)),
        "header": header,
        "finite_fraction": float(np.isfinite(data).mean()) if len(data) else None,
        "units": "N (3-D force)",
        "issues": [],
    }
    if len(data) < 2:
        result["issues"].append("force output has fewer than two numeric rows")
        return result
    if data.shape[1] < 7:
        result["issues"].append("force output lacks ForceFluid vector/magnitude columns")
        return result
    if not np.all(np.isfinite(data)):
        result["issues"].append("force output contains non-finite values")
    if not np.all(np.diff(data[:, 1]) > 0):
        result["issues"].append("force time is not strictly increasing")
    magnitude = data[:, 6]
    index = int(np.nanargmax(np.abs(magnitude)))
    result.update({
        "time_start_s": float(data[0, 1]),
        "time_end_s": float(data[-1, 1]),
        "dt_median_s": float(np.median(np.diff(data[:, 1]))),
        "peak_force_abs_n": float(abs(magnitude[index])),
        "peak_force_signed_n": float(magnitude[index]),
        "peak_force_time_s": float(data[index, 1]),
        "peak_force_vector_n": data[index, 3:6].tolist(),
    })
    return result


def _data_directory(output: Path) -> Path | None:
    candidates = [path for path in sorted(output.glob("data*")) if path.is_dir()]
    return candidates[0] if candidates else None


def postprocess_case(run: dict[str, Any]) -> dict[str, Any]:
    """Run MeasureTool and requested/effective ComputeForces diagnostics."""

    if run.get("status") != "completed":
        return {"status": "skipped", "issues": ["solver run is not completed"]}
    output = LAB / str(run["output_dir"])
    data_dir = _data_directory(output)
    if data_dir is None:
        return {"status": "failed", "issues": ["solver data directory is missing"]}
    observations = output / "observations"
    observations.mkdir(parents=True, exist_ok=True)
    point_names = [item[0] for item in OBSERVATION_POINTS]
    measure_prefix = observations / "fixed_points"
    measure_command = [
        str(MEASURE), "-dirdata", str(data_dir), "-filexml", "AUTO",
        f"-pointsdef:{_pointsdef(OBSERVATION_POINTS)}",
        "-onlytype:-all,+fluid", "-vars:-all,+vel,+press,+rhop,+kcorr",
        "-savecsv", str(measure_prefix),
    ]
    measure = _run_tool(measure_command, observations / "measure.stdout.log", cwd=output)
    pressure = _measure_summary(observations / "fixed_points_Press.csv", point_names)
    velocity = _measure_summary(observations / "fixed_points_Vel.csv", point_names, components=3)
    density = _measure_summary(observations / "fixed_points_Rhop.csv", point_names)
    kcorr = _measure_summary(observations / "fixed_points_Kcorr.csv", point_names)
    if kcorr["rows"]:
        _, kcorr_data = _numeric_csv(observations / "fixed_points_Kcorr.csv")
        values = kcorr_data[:, 2:]
        kcorr.update({
            "minimum": float(np.nanmin(values)),
            "maximum": float(np.nanmax(values)),
            "zero_fraction": float(np.mean(np.isclose(values, 0.0))),
            "support_interpretation": (
                "Kcorr=0 may be an interpolation dummy when support is insufficient; "
                "it is not a physical zero."
            ),
        })
    measure_outputs_ok = all(
        item["rows"] >= 2 and not item["issues"]
        for item in (pressure, velocity, density, kcorr)
    )

    effective_mks = (run.get("generated_particle_mks") or {}).get("effective_boundary_mks", [])
    requested_prefix = observations / "wall_force_requested_mk10"
    requested_command = [
        str(FORCES), "-dirdata", str(data_dir), "-filexml", "AUTO",
        f"-onlymk:{REQUESTED_FORCE_MK}", "-viscoauto", "-savecsv", str(requested_prefix),
    ]
    requested = _run_tool(requested_command, observations / "forces_requested_mk10.stdout.log", cwd=output)
    requested_summary = _force_summary(observations / "wall_force_requested_mk10.csv")
    fallback = None
    fallback_summary: dict[str, Any] | None = None
    if requested["status"] != "completed" and effective_mks:
        effective_mk = int(effective_mks[0])
        fallback_prefix = observations / f"wall_force_effective_mk{effective_mk}"
        fallback_command = [
            str(FORCES), "-dirdata", str(data_dir), "-filexml", "AUTO",
            f"-onlymk:{effective_mk}", "-viscoauto", "-savecsv", str(fallback_prefix),
        ]
        fallback = _run_tool(
            fallback_command, observations / f"forces_effective_mk{effective_mk}.stdout.log", cwd=output
        )
        fallback_summary = _force_summary(observations / f"wall_force_effective_mk{effective_mk}.csv")
    force_contract_status = "requested_target_completed" if requested_summary["rows"] >= 2 else (
        "requested_target_failed_effective_mk_completed"
        if fallback_summary and fallback_summary["rows"] >= 2
        else "requested_target_failed"
    )
    observation_status = "completed" if measure_outputs_ok and force_contract_status == "requested_target_completed" else (
        "completed_with_force_target_mismatch" if measure_outputs_ok and fallback_summary and fallback_summary["rows"] >= 2
        else "partial"
    )
    return {
        "status": observation_status,
        "data_dir": str(data_dir.relative_to(LAB)),
        "tools": {
            "measure": {**measure, "binary_sha256": sha256(MEASURE)},
            "compute_forces_requested_mk10": {**requested, "binary_sha256": sha256(FORCES)},
            "compute_forces_effective_fallback": fallback,
        },
        "fixed_points": {
            "points": [
                {"name": name, "position_m": [x, y, z]}
                for name, x, y, z in OBSERVATION_POINTS
            ],
            "pressure": pressure,
            "velocity": velocity,
            "density": density,
            "kernel_correction": kcorr,
        },
        "wall_force": {
            "requested_mk": REQUESTED_FORCE_MK,
            "requested": requested_summary,
            "effective_fallback_mk": int(effective_mks[0]) if effective_mks else None,
            "effective_fallback": fallback_summary,
            "contract_status": force_contract_status,
            "interpretation": (
                "The requested Mk=10 target is the explicit contract.  An effective-Mk "
                "fallback is diagnostic only and does not rewrite the requested target."
            ),
        },
        "issues": (
            ["ComputeForces requested Mk=10 is absent from the generated Mk mapping."]
            if REQUESTED_FORCE_MK not in effective_mks else []
        ) + (["MeasureTool did not produce four structurally valid field histories."] if not measure_outputs_ok else []),
    }


def _align_error(left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
    if left.ndim != 2 or right.ndim != 2 or len(left) < 2 or len(right) < 2:
        return {"status": "insufficient_rows"}
    start, end = max(float(left[0, 0]), float(right[0, 0])), min(float(left[-1, 0]), float(right[-1, 0]))
    if end <= start:
        return {"status": "no_overlap"}
    width = min(left.shape[1], right.shape[1]) - 1
    if width < 1:
        return {"status": "no_value_columns"}
    samples = max(2, min(400, len(left), len(right)))
    grid = np.linspace(start, end, samples)
    left_values = np.column_stack([np.interp(grid, left[:, 0], left[:, i]) for i in range(1, width + 1)])
    right_values = np.column_stack([np.interp(grid, right[:, 0], right[:, i]) for i in range(1, width + 1)])
    delta = left_values - right_values
    rmse = np.sqrt(np.mean(delta ** 2, axis=0))
    return {
        "status": "computed",
        "overlap_start_s": start,
        "overlap_end_s": end,
        "samples": samples,
        "rmse": rmse.tolist(),
        "max_rmse": float(np.max(rmse)),
    }


def compare_resolution_matrix(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare collision-centre pressure and available force histories descriptively."""

    records = [
        item for item in runs
        if item.get("status") == "completed"
        and item.get("observations", {}).get("fixed_points", {}).get("pressure", {}).get("rows", 0) >= 2
    ]
    records.sort(key=lambda item: float(item.get("dp_m", 0.0)), reverse=True)
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            left_obs = LAB / str(left["output_dir"]) / "observations"
            right_obs = LAB / str(right["output_dir"]) / "observations"
            left_pressure = _numeric_csv(left_obs / "fixed_points_Press.csv")[1]
            right_pressure = _numeric_csv(right_obs / "fixed_points_Press.csv")[1]
            # Part/time plus the lower collision probe (point index 5).  The
            # geometric centre can remain unsupported for a coarse saved
            # frame, so keep that known interpolation diagnostic separate.
            pressure_error = _align_error(left_pressure[:, [1, 7]], right_pressure[:, [1, 7]])
            left_force_path = left_obs / str(
                left.get("observations", {}).get("wall_force", {}).get("effective_fallback", {}).get("path", "")
            )
            right_force_path = right_obs / str(
                right.get("observations", {}).get("wall_force", {}).get("effective_fallback", {}).get("path", "")
            )
            # The summary stores an absolute tool-output path; when the
            # report was assembled by a caller that supplied only a basename,
            # retain the conventional candidate output location.
            if not left_force_path.is_file():
                left_force_path = left_obs / "wall_force_effective_mk17.csv"
            if not right_force_path.is_file():
                right_force_path = right_obs / "wall_force_effective_mk17.csv"
            left_force = _numeric_csv(left_force_path)[1]
            right_force = _numeric_csv(right_force_path)[1]
            force_error = _align_error(left_force[:, [1, 6]], right_force[:, [1, 6]])
            pairs.append({
                "left": {"label": left["label"], "dp_m": left["dp_m"]},
                "right": {"label": right["label"], "dp_m": right["dp_m"]},
                "collision_lower_pressure": pressure_error,
                "effective_mk17_force_magnitude": force_error,
            })
    return {
        "status": "diagnostic_only",
        "acceptance_threshold_declared": False,
        "pair_count": len(pairs),
        "pairs": pairs,
    }


def build_report(
    prepared: Iterable[dict[str, Any]],
    runs: Iterable[dict[str, Any]],
    *,
    tmax_s: float,
    tout_s: float,
) -> dict[str, Any]:
    prepared = list(prepared)
    report_runs: list[dict[str, Any]] = []
    for run in runs:
        item = dict(run)
        item["observations"] = postprocess_case(run)
        report_runs.append(item)
    completed = sum(item.get("status") == "completed" for item in report_runs)
    observation_complete = sum(
        item.get("observations", {}).get("status") in {"completed", "completed_with_force_target_mismatch"}
        for item in report_runs
    )
    policy = _gpu_inventory()
    return {
        "schema_version": 1,
        "scope": "R3 F4 isolated 3-D head-on liquid-column observation-path probe",
        "execution_status": "complete" if report_runs and completed == len(report_runs) else "partial",
        "acceptance_status": "candidate_observations_only",
        "formal_release_authorized": False,
        "upstream_source": {
            "case_definition": str(SOURCE.relative_to(LAB)),
            "case_definition_sha256": sha256(SOURCE),
            "solver_binary": str(SOLVER.relative_to(LAB)),
            "solver_binary_sha256": sha256(SOLVER),
            "gencase_binary": str(GENCASE.relative_to(LAB)),
            "gencase_binary_sha256": sha256(GENCASE),
            "measuretool_binary": str(MEASURE.relative_to(LAB)),
            "measuretool_binary_sha256": sha256(MEASURE),
            "computeforces_binary": str(FORCES.relative_to(LAB)),
            "computeforces_binary_sha256": sha256(FORCES),
        },
        "observation_contract": {
            "dimension": "3D",
            "particle_output_cadence_s": tout_s,
            "requested_time_end_s": tmax_s,
            "fixed_point_count": len(OBSERVATION_POINTS),
            "fixed_point_fields": ["pressure", "velocity", "density", "kernel_correction"],
            "pressure_units": "Pa",
            "velocity_units": "m/s",
            "density_units": "kg/m^3",
            "kernel_correction_units": "dimensionless kernel sum",
            "compute_forces_requested_mk": REQUESTED_FORCE_MK,
            "force_units": "N",
            "force_mk_semantics": "physical generated Mk passed to ComputeForces; source mkbound is recorded separately",
        },
        "resolution_policy": {
            "candidate_ladder_m": dict(RESOLUTIONS),
            "fixed_physics_required": True,
            "no_admission_threshold_declared": True,
        },
        "gpu_policy": policy,
        "prepared_cases": prepared,
        "runs": report_runs,
        "summary": {
            "prepared_count": len(prepared),
            "solver_completed_count": completed,
            "observation_complete_or_fallback_count": observation_complete,
            "requested_force_mk10_completed_count": sum(
                item.get("observations", {}).get("wall_force", {}).get("contract_status") == "requested_target_completed"
                for item in report_runs
            ),
            "effective_force_fallback_count": sum(
                item.get("observations", {}).get("wall_force", {}).get("contract_status") == "requested_target_failed_effective_mk_completed"
                for item in report_runs
            ),
        },
        "resolution_comparison": compare_resolution_matrix(report_runs),
        "open_blockers": [
            "The source definition generates physical boundary Mk=17, so the requested ComputeForces Mk=10 target is absent; effective-Mk force is diagnostic only.",
            "No external pressure, velocity, density, or force reference is bundled for this custom F4 case.",
            "Fixed-point interpolation in initially empty collision locations can produce Kcorr dummies and must not be treated as truth.",
            "Three resolutions expose numerical sensitivity but do not establish convergence or formal family admission.",
            "Material particle lineage and collision mixing targets remain outside this observation-path probe.",
        ],
    }


def render_conclusion(report: dict[str, Any]) -> str:
    runs = report.get("runs", [])
    summary = report.get("summary", {})
    comparison = report.get("resolution_comparison", {})
    return f"""# R3 F4 3-D head-on liquid-column observation probe

状态：**candidate-only；不授权正式数据发布**。

本探针从 `cases/F4/F4_head_on_columns/F4_head_on_columns_Def.xml` 复制隔离定义，
使用显式 `tmax={report.get('observation_contract', {}).get('requested_time_end_s')} s`、
`tout={report.get('observation_contract', {}).get('particle_output_cadence_s')} s`，并验证
三档 `dp=0.04/0.03/0.02 m` 的 3-D 双液柱正碰路径。固定点 `MeasureTool` 同时记录
pressure、velocity、rhop 和 Kcorr；`ComputeForces` 按契约先执行 `mk=10`。

当前 solver 完成 {summary.get('solver_completed_count', 0)}/{len(runs)} 个运行，
其中 {summary.get('observation_complete_or_fallback_count', 0)} 个完成固定点观测，
{summary.get('requested_force_mk10_completed_count', 0)} 个真正完成 requested Mk=10，
{summary.get('effective_force_fallback_count', 0)} 个只完成了 effective-Mk fallback；
跨分辨率比较形成 {comparison.get('pair_count', 0)} 对，全部仅为 diagnostic。

一个关键可复现问题已经暴露：该 XML 的 `mkbound=0` 在 GenCase v5.4 中映射为
物理 `Mk=17`，因此 `ComputeForces -onlymk:10` 没有边界粒子。报告保留原始
Mk=10 请求，并把 Mk=17 结果标为 fallback，不能把 fallback 改写成 Mk=10 或
当作外部物理验证。

本轮只证明“隔离复制、三档求解、固定点观测和力后处理链路可执行/可追溯”。
原始 solver BI4、CSV 和运行日志留在 campaign 的 ignored 运行目录；提交内容只保留
定义/GenCase provenance、结构化摘要和 candidate-only 结论。
没有外部参考、没有收敛阈值，也没有材料谱系/混合界面真值；因此 F4 仍不能
进入正式数据发布或 family admission。

机器可读详情见 `r3-f4-3d-head-on.json`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolutions", nargs="+", choices=sorted(RESOLUTIONS), default=list(RESOLUTIONS))
    parser.add_argument("--gpus", nargs="+", type=int, default=[4, 5, 6])
    parser.add_argument("--tmax", type=float, default=DEFAULT_TMAX_S)
    parser.add_argument("--tout", type=float, default=DEFAULT_TOUT_S)
    parser.add_argument("--run", action="store_true", help="run prepared cases on listed physical GPUs")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--conclusion", type=Path, default=DEFAULT_CONCLUSION)
    args = parser.parse_args()
    if args.tmax <= 0 or args.tout <= 0:
        parser.error("tmax and tout must be positive")
    try:
        validate_gpu_indices(args.gpus)
    except ValueError as error:
        parser.error(str(error))
    prepared = [
        prepare_case(label, RESOLUTIONS[label], tmax_s=args.tmax, tout_s=args.tout)
        for label in args.resolutions
    ]
    runs: list[dict[str, Any]] = []
    if args.run:
        for index, item in enumerate(prepared):
            runs.append(run_case(item, args.gpus[index % len(args.gpus)], tmax_s=args.tmax, tout_s=args.tout))
    report = build_report(prepared, runs, tmax_s=args.tmax, tout_s=args.tout)
    args.output = Path(args.output)
    args.conclusion = Path(args.conclusion)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.conclusion.parent.mkdir(parents=True, exist_ok=True)
    args.conclusion.write_text(render_conclusion(report))
    print(json.dumps({
        "execution_status": report["execution_status"],
        "acceptance_status": report["acceptance_status"],
        "prepared": len(prepared),
        "run_count": len(runs),
        "solver_completed": report["summary"]["solver_completed_count"],
        "allowed_gpu_indices": report["gpu_policy"]["allowed_gpu_indices"],
        "report": str(args.output.resolve()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
