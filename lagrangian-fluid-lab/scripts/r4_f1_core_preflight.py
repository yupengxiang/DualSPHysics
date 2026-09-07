#!/usr/bin/env python3
"""CPU-only GenCase preflight for the R4 F1 core mother-case ladder.

This module materialises exactly the nine R4 F1 A1/A2 definitions and runs
only the vendored ``GenCase_linux64`` executable.  It intentionally has no
solver path, no CUDA import, no GPU selection, and no dependency on an old R3
run.  The generated definitions and GenCase products live in a private R4
namespace; the source F1 definitions and the vendor tree are read-only.

The result is structural evidence for a later solver gate.  A successful
GenCase return code is not a physical acceptance result and this script never
writes a GO/production decision.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import struct
import xml.etree.ElementTree as ET
from typing import Any, Iterable


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
CASE_ROOT = CAMPAIGN / "cases" / "r4-f1-core-preflight"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r4-f1-core-preflight"
REPORT_JSON = CAMPAIGN / "r4-f1-core-preflight.json"
REPORT_MD = CAMPAIGN / "R4-F1-CORE-PREFLIGHT.md"

BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"

LEVELS = ("coarse", "medium", "fine")
BACKGROUNDS = (
    {
        "background_id": "plain_dam_break",
        "source_definition": LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml",
        "mechanism": "collapse-runup-return",
    },
    {
        "background_id": "center_obstacle",
        "source_definition": LAB / "cases" / "F1" / "F1_center_obstacle" / "F1_center_obstacle_Def.xml",
        "mechanism": "split-around-obstacle",
    },
    {
        "background_id": "twin_obstacle_split_remerge",
        "source_definition": LAB / "cases" / "F1" / "F1_twin_obstacle" / "F1_twin_obstacle_Def.xml",
        "mechanism": "multi-path-split-remerge",
    },
)
RESOLUTION_DP_M = {"coarse": 0.035, "medium": 0.024, "fine": 0.014}

# These are the controls requested by the R4 core-mother-case audit.  Boundary
# is explicit even though older local definitions relied on the solver's DBC
# default.  SavePosDouble follows the existing R3 preparation convention and
# does not change GenCase geometry; it is recorded so a later solver launch
# cannot silently inherit an unspecified output precision.
PROTOCOL: dict[str, Any] = {
    "family": "F1",
    "time_max_s": 1.5,
    "time_out_s": 0.001,
    "integrator": "Verlet",
    "step_algorithm": 1,
    "verlet_steps": 40,
    "boundary_formulation": "DBC",
    "boundary_parameter": 1,
    "save_pos_double": 2,
    "shifting": 0,
    "spatial_resolution_m": RESOLUTION_DP_M,
}

EXPECTED_GENERATED_SUFFIXES = (
    ".xml",
    ".bi4",
    ".out",
    "_All.vtk",
    "_Bound.vtk",
    "_Fluid.vtk",
    "_MkCells.vtk",
)

NUMBER_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def relpath(path: Path | str, root: Path = LAB) -> str:
    """Return a stable repository-relative path for reports."""

    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": relpath(path),
        "exists": path.is_file(),
    }
    if path.is_file():
        result.update({"bytes": path.stat().st_size, "sha256": sha256(path)})
    else:
        result.update({"bytes": None, "sha256": None})
    return result


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(text)
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def case_records() -> list[dict[str, Any]]:
    """Return the fixed, ordered nine-cell R4 F1 matrix."""

    records: list[dict[str, Any]] = []
    for background in BACKGROUNDS:
        for level in LEVELS:
            records.append(
                {
                    "case_id": f"R4_F1_{background['background_id']}_{level}",
                    "family": "F1",
                    "background_id": background["background_id"],
                    "mechanism": background["mechanism"],
                    "level": level,
                    "dp_m": RESOLUTION_DP_M[level],
                    "time_max_s": PROTOCOL["time_max_s"],
                    "time_out_s": PROTOCOL["time_out_s"],
                    "source_definition": background["source_definition"],
                }
            )
    return records


def _parameter_parent(root: ET.Element) -> ET.Element:
    parent = root.find(".//execution/parameters")
    if parent is None:
        raise ValueError("definition has no execution/parameters section")
    return parent


def set_parameter(root: ET.Element, key: str, value: Any, *, comment: str | None = None) -> None:
    parent = _parameter_parent(root)
    node = parent.find(f"./parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parent, "parameter", key=key)
    node.set("value", str(value))
    if comment is not None:
        node.set("comment", comment)


def source_geometry_signature(root: ET.Element) -> dict[str, Any]:
    """Summarise source geometry without changing or executing it."""

    commands = root.find(".//geometry/commands")
    drawboxes = list(commands.iter("drawbox")) if commands is not None else []
    fill_texts = [
        (node.findtext("./boxfill") or "").strip()
        for node in drawboxes
    ]
    return {
        "drawbox_count": len(drawboxes),
        "boxfill_values": fill_texts,
        "setmkfluid_count": len(commands.findall(".//setmkfluid")) if commands is not None else 0,
        "setmkbound_count": len(commands.findall(".//setmkbound")) if commands is not None else 0,
        "setmkvoid_count": len(commands.findall(".//setmkvoid")) if commands is not None else 0,
        "floating_section_present": root.find(".//floatings") is not None,
        "moving_section_present": root.find(".//moving") is not None,
        "file_references": sorted(
            element.get("file")
            for element in root.iter()
            if element.get("file")
        ),
    }


def parse_controls(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find(".//geometry/definition")
    params = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    boundary_value = integer(params.get("Boundary"))
    return {
        "dp_m": number(definition.get("dp")) if definition is not None else None,
        "time_max_s": number(params.get("TimeMax")),
        "time_out_s": number(params.get("TimeOut")),
        "step_algorithm": integer(params.get("StepAlgorithm")),
        "integrator": {1: "Verlet", 2: "Symplectic"}.get(
            integer(params.get("StepAlgorithm")), params.get("StepAlgorithm")
        ),
        "verlet_steps": integer(params.get("VerletSteps")),
        "boundary_parameter": boundary_value,
        "boundary_formulation": {1: "DBC", 2: "mDBC"}.get(boundary_value, "unknown"),
        "save_pos_double": integer(params.get("SavePosDouble")),
        "shifting": integer(params.get("Shifting")),
        "raw_parameters": params,
    }


def materialize_definition(record: dict[str, Any]) -> dict[str, Any]:
    """Create one isolated candidate definition from its F1 source template."""

    source = Path(record["source_definition"])
    if not source.is_file():
        raise FileNotFoundError(source)
    if not source.resolve().is_relative_to(LAB.resolve()):
        raise ValueError(f"source is outside lab: {source}")

    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError(f"source has no geometry definition: {source}")
    definition.set("dp", str(record["dp_m"]))
    set_parameter(root, "SavePosDouble", PROTOCOL["save_pos_double"])
    set_parameter(root, "StepAlgorithm", PROTOCOL["step_algorithm"])
    set_parameter(root, "VerletSteps", PROTOCOL["verlet_steps"])
    set_parameter(root, "TimeMax", PROTOCOL["time_max_s"])
    set_parameter(root, "TimeOut", PROTOCOL["time_out_s"])
    set_parameter(
        root,
        "Boundary",
        PROTOCOL["boundary_parameter"],
        comment="Boundary method 1:DBC, 2:mDBC (R4 F1 preflight requires DBC)",
    )
    set_parameter(root, "Shifting", PROTOCOL["shifting"])

    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = CASE_ROOT / f"{record['case_id']}_Def.xml"
    ET.indent(tree, space="    ")
    xml_text = ET.tostring(root, encoding="unicode")
    atomic_write_text(candidate, "<?xml version='1.0' encoding='utf-8'?>\n" + xml_text)
    controls = parse_controls(candidate)
    return {
        "source_definition": fingerprint(source),
        "source_geometry_signature": source_geometry_signature(ET.parse(source).getroot()),
        "candidate_definition": fingerprint(candidate),
        "candidate_controls": controls,
        "candidate_path": candidate,
    }


def cpu_environment() -> dict[str, str]:
    """Return an environment that makes accidental CUDA visibility explicit."""

    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = f"{BIN}:{environment.get('LD_LIBRARY_PATH', '')}"
    environment["CUDA_VISIBLE_DEVICES"] = ""
    environment["NVIDIA_VISIBLE_DEVICES"] = "void"
    return environment


def assert_gencase_only(command: Iterable[str]) -> None:
    values = [str(item) for item in command]
    if not values or Path(values[0]).resolve() != GENCASE.resolve():
        raise AssertionError(f"non-GenCase command rejected: {values}")
    forbidden_executables = {
        "DualSPHysics5.4_linux64",
        "DualSPHysics5.4CPU_linux64",
        "nvidia-smi",
        "nvcc",
    }
    for value in values[1:]:
        # Candidate/output paths legitimately contain the vendor directory
        # name ``DualSPHysics_v5.4``.  Only reject an executable basename or
        # an explicit CUDA/GPU option, not an incidental path component.
        if Path(value).name in forbidden_executables:
            raise AssertionError(f"forbidden executable in command: {values}")
        if value.lower() in {"cuda", "gpu", "-gpu", "--gpu"} or value.lower().startswith(("cuda=", "gpu=")):
            raise AssertionError(f"forbidden GPU option in command: {values}")


def run_gencase(record: dict[str, Any], candidate: Path) -> dict[str, Any]:
    """Run exactly one vendored GenCase process and capture its immutable log."""

    generated = ARTIFACT_ROOT / record["case_id"] / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    prefix = generated / record["case_id"]
    command = [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"]
    assert_gencase_only(command)
    environment = cpu_environment()
    started = datetime.now(timezone.utc).isoformat()
    try:
        process = subprocess.run(
            command,
            cwd=generated,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return_code: int | None = process.returncode
        stdout = process.stdout
        error = None
    except OSError as exc:
        return_code = None
        stdout = f"{type(exc).__name__}: {exc}\n"
        error = repr(exc)
    log = generated / "gencase.stdout.log"
    atomic_write_text(log, stdout)
    command_record = {
        "command": command,
        "started_at_utc": started,
        "return_code": return_code,
        "error": error,
        "stdout_log": fingerprint(log),
        "environment_policy": {
            "CUDA_VISIBLE_DEVICES": "",
            "NVIDIA_VISIBLE_DEVICES": "void",
            "solver_invocations": 0,
            "gpu_indices_used": [],
        },
    }
    atomic_write_json(generated / "gencase.command.json", command_record)
    command_record["command_log"] = fingerprint(generated / "gencase.command.json")
    return command_record


def parse_gencase_log(path: Path) -> dict[str, Any]:
    """Parse counts and limits printed by GenCase without trusting old runs."""

    if not path.is_file():
        return {"log_present": False}
    text = path.read_text(errors="replace")
    result: dict[str, Any] = {"log_present": True}
    total = re.search(
        r"Total particles:\s*([0-9,]+)\s*\(bound=([0-9,]+)\s*"
        r"\(fx=([0-9,]+)\s*mv=([0-9,]+)\s*ft=([0-9,]+)\)\s*fluid=([0-9,]+)\)",
        text,
    )
    if total:
        labels = (
            "total_particles",
            "boundary_particles",
            "fixed_particles",
            "moving_particles",
            "floating_particles",
            "fluid_particles",
        )
        result.update({key: integer(value) for key, value in zip(labels, total.groups())})
    for label, key in (
        ("Fixed", "fixed_particles_line"),
        ("Moving", "moving_particles_line"),
        ("Floating", "floating_particles_line"),
        ("Fluid", "fluid_particles_line"),
        ("Points loaded", "points_loaded"),
    ):
        match = re.search(rf"{re.escape(label)}(?:\.{3,})?\s*:\s*([0-9,]+)", text)
        if match:
            result[key] = integer(match.group(1))
    for axis in "XYZ":
        match = re.search(
            rf"{axis}\s+range:\s*({NUMBER_RE})\s+to\s+({NUMBER_RE})",
            text,
        )
        if match:
            result[f"{axis.lower()}_range_m"] = [number(match.group(1)), number(match.group(2))]
    result["finished_code_0"] = "Finished execution (code=0)" in text
    result["warning_lines"] = [
        line.strip()
        for line in text.splitlines()
        if "warning" in line.lower() or "error" in line.lower()
    ]
    return result


def parse_generated_xml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"generated_xml_present": False}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"generated_xml_present": True, "parse_error": str(exc)}
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    summary = particles.find("./_summary") if particles is not None else None
    fixed = summary.find("./fixed") if summary is not None else None
    fluid = summary.find("./fluid") if summary is not None else None

    def attr(node: ET.Element | None, name: str) -> Any:
        return node.get(name) if node is not None else None

    return {
        "generated_xml_present": True,
        "case_app": root.get("app"),
        "particles": {
            "total_particles": integer(attr(particles, "np")),
            "boundary_particles": integer(attr(particles, "nb")),
            "fixed_particles": integer(attr(fixed, "count")),
            "fluid_particles": integer(attr(fluid, "count")),
            "fixed_id_range": attr(fixed, "id"),
            "fluid_id_range": attr(fluid, "id"),
            "mkboundfirst": integer(attr(particles, "mkboundfirst")),
            "mkfluidfirst": integer(attr(particles, "mkfluidfirst")),
        },
        "constants": {
            "dp_m": number(attr(constants.find("./dp") if constants is not None else None, "value")),
            "rhop0_kg_m3": number(attr(constants.find("./rhop0") if constants is not None else None, "value")),
            "massbound_kg": number(attr(constants.find("./massbound") if constants is not None else None, "value")),
            "massfluid_kg": number(attr(constants.find("./massfluid") if constants is not None else None, "value")),
        },
        "controls": parse_controls(path),
    }


def read_vtk_points(path: Path) -> dict[str, Any]:
    """Read the ASCII or binary POINTS section emitted by GenCase."""

    if not path.is_file():
        return {"present": False, "points": []}
    raw = path.read_bytes()
    match = re.search(rb"(?:^|\n)POINTS\s+(\d+)\s+(\S+)\s*\n", raw)
    if match is None:
        return {"present": True, "parse_error": "POINTS header missing", "points": []}
    expected = int(match.group(1))
    vtk_type = match.group(2).decode("ascii", errors="replace").lower()
    header = raw[: match.end()].upper()
    if b"ASCII" in header:
        text = raw[match.end():].decode("ascii", errors="replace")
        tokens = re.findall(NUMBER_RE, text)
        values = [number(token) for token in tokens[: 3 * expected]]
        if len(values) != 3 * expected or any(value is None for value in values):
            return {
                "present": True,
                "parse_error": f"expected {3 * expected} coordinate values, found {len(values)}",
                "declared_points": expected,
                "points": [],
            }
        values = [float(value) for value in values]  # type: ignore[arg-type]
        encoding = "ascii"
    else:
        width_by_type = {"float": 4, "double": 8}
        width = width_by_type.get(vtk_type)
        if width is None:
            return {
                "present": True,
                "parse_error": f"unsupported binary VTK point type: {vtk_type}",
                "declared_points": expected,
                "points": [],
            }
        end = match.end() + expected * 3 * width
        payload = raw[match.end():end]
        if len(payload) != expected * 3 * width:
            return {
                "present": True,
                "parse_error": f"expected {expected * 3 * width} binary point bytes, found {len(payload)}",
                "declared_points": expected,
                "points": [],
            }
        try:
            values = list(struct.unpack(">" + ("f" if width == 4 else "d") * expected * 3, payload))
        except struct.error as exc:
            return {
                "present": True,
                "parse_error": str(exc),
                "declared_points": expected,
                "points": [],
            }
        encoding = "binary_big_endian"
    points = [
        (float(values[index]), float(values[index + 1]), float(values[index + 2]))
        for index in range(0, len(values), 3)
    ]
    return {
        "present": True,
        "declared_points": expected,
        "encoding": encoding,
        "points": points,
    }


def parse_declared_bounds(path: Path) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    root = ET.parse(path).getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        return None
    low = definition.find("./pointmin")
    high = definition.find("./pointmax")
    if low is None or high is None:
        return None
    low_values = tuple(number(low.get(axis)) for axis in "xyz")
    high_values = tuple(number(high.get(axis)) for axis in "xyz")
    if any(value is None for value in low_values + high_values):
        return None
    return (
        tuple(float(value) for value in low_values),  # type: ignore[arg-type]
        tuple(float(value) for value in high_values),  # type: ignore[arg-type]
    )


def _bbox(points: list[tuple[float, float, float]]) -> dict[str, Any]:
    if not points:
        return {"count": 0, "finite": True, "min_m": None, "max_m": None}
    finite = all(math.isfinite(value) for point in points for value in point)
    return {
        "count": len(points),
        "finite": finite,
        "min_m": [min(point[index] for point in points) for index in range(3)],
        "max_m": [max(point[index] for point in points) for index in range(3)],
    }


def audit_geometry(candidate: Path, generated: Path, generated_xml: dict[str, Any]) -> dict[str, Any]:
    expected_particles = generated_xml.get("particles", {})
    vtk_paths = {
        "all": generated.with_name(generated.name + "_All.vtk"),
        "bound": generated.with_name(generated.name + "_Bound.vtk"),
        "fluid": generated.with_name(generated.name + "_Fluid.vtk"),
    }
    vtk = {name: read_vtk_points(path) for name, path in vtk_paths.items()}
    anomalies: list[str] = []
    for name, expected_key in (
        ("all", "total_particles"),
        ("bound", "boundary_particles"),
        ("fluid", "fluid_particles"),
    ):
        data = vtk[name]
        if data.get("parse_error"):
            anomalies.append(f"{name}_vtk:{data['parse_error']}")
        expected = expected_particles.get(expected_key)
        actual = data.get("declared_points")
        if expected is not None and actual is not None and expected != actual:
            anomalies.append(f"{name}_vtk_count_mismatch:{actual}!={expected}")

    all_points = vtk["all"].get("points", [])
    bound_points = vtk["bound"].get("points", [])
    fluid_points = vtk["fluid"].get("points", [])
    bboxes = {name: _bbox(data.get("points", [])) for name, data in vtk.items()}
    if any(not data["finite"] for data in bboxes.values()):
        anomalies.append("non_finite_geometry_coordinate")

    bounds = parse_declared_bounds(candidate)
    out_of_bounds = {"all": None, "bound": None, "fluid": None}
    if bounds is not None:
        low, high = bounds
        for name, points in (
            ("all", all_points),
            ("bound", bound_points),
            ("fluid", fluid_points),
        ):
            count = sum(
                any(value < low[index] - 1e-9 or value > high[index] + 1e-9 for index, value in enumerate(point))
                for point in points
            )
            out_of_bounds[name] = count
            if count:
                anomalies.append(f"{name}_points_outside_definition_bounds:{count}")

    duplicate_count: int | None = None
    if bound_points and fluid_points:
        boundary_keys = {
            tuple(round(value, 12) for value in point)
            for point in bound_points
        }
        duplicate_count = sum(
            tuple(round(value, 12) for value in point) in boundary_keys
            for point in fluid_points
        )
        if duplicate_count:
            anomalies.append(f"fluid_boundary_duplicate_positions:{duplicate_count}")

    if not fluid_points:
        anomalies.append("fluid_vtk_empty_or_unreadable")
    if not bound_points:
        anomalies.append("bound_vtk_empty_or_unreadable")
    if expected_particles.get("fluid_particles", 0) <= 0:
        anomalies.append("generated_fluid_particle_count_nonpositive")
    if expected_particles.get("boundary_particles", 0) <= 0:
        anomalies.append("generated_boundary_particle_count_nonpositive")

    return {
        "declared_definition_bounds_m": {
            "min": list(bounds[0]),
            "max": list(bounds[1]),
        } if bounds is not None else None,
        "vtk": {
            name: {
                key: value
                for key, value in data.items()
                if key != "points"
            } | {"bbox": bboxes[name]}
            for name, data in vtk.items()
        },
        "out_of_definition_bounds_counts": out_of_bounds,
        "fluid_boundary_duplicate_positions": duplicate_count,
        "anomalies": anomalies,
        "geometry_clean_for_structural_preflight": not anomalies,
    }


def audit_mass(generated_xml: dict[str, Any]) -> dict[str, Any]:
    particles = generated_xml.get("particles", {})
    constants = generated_xml.get("constants", {})
    fluid_count = particles.get("fluid_particles")
    boundary_count = particles.get("boundary_particles")
    dp_m = constants.get("dp_m")
    rhop0 = constants.get("rhop0_kg_m3")
    massfluid = constants.get("massfluid_kg")
    massbound = constants.get("massbound_kg")
    anomalies: list[str] = []
    expected_particle_mass = rhop0 * dp_m**3 if rhop0 is not None and dp_m is not None else None
    fluid_mass = fluid_count * massfluid if fluid_count is not None and massfluid is not None else None
    boundary_mass = boundary_count * massbound if boundary_count is not None and massbound is not None else None
    discrete_fluid_mass = (
        fluid_count * expected_particle_mass
        if fluid_count is not None and expected_particle_mass is not None
        else None
    )
    relative_mass_error = (
        abs(massfluid - expected_particle_mass) / expected_particle_mass
        if massfluid is not None and expected_particle_mass not in (None, 0)
        else None
    )
    if relative_mass_error is None:
        anomalies.append("fluid_particle_mass_not_reconstructable")
    elif relative_mass_error > 1e-8:
        anomalies.append(f"fluid_particle_mass_mismatch:{relative_mass_error:.3e}")
    if fluid_mass is None or fluid_mass <= 0:
        anomalies.append("fluid_total_mass_nonpositive_or_missing")
    if boundary_mass is None or boundary_mass <= 0:
        anomalies.append("boundary_total_mass_nonpositive_or_missing")
    return {
        "fluid_particles": fluid_count,
        "boundary_particles": boundary_count,
        "rhop0_kg_m3": rhop0,
        "dp_m": dp_m,
        "massfluid_per_particle_kg": massfluid,
        "massbound_per_particle_kg": massbound,
        "expected_particle_mass_kg": expected_particle_mass,
        "initial_fluid_mass_kg": fluid_mass,
        "initial_boundary_mass_kg": boundary_mass,
        "initial_fluid_mass_from_discrete_volume_kg": discrete_fluid_mass,
        "relative_fluid_particle_mass_error": relative_mass_error,
        "anomalies": anomalies,
        "mass_clean_for_structural_preflight": not anomalies,
    }


def artifact_fingerprints(generated: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for suffix in EXPECTED_GENERATED_SUFFIXES:
        path = generated.with_suffix(suffix) if suffix.startswith(".") else generated.with_name(generated.name + suffix)
        result[suffix] = fingerprint(path)
    return result


def controls_match_protocol(controls: dict[str, Any]) -> dict[str, bool]:
    return {
        "dp": math.isclose(float(controls.get("dp_m")), float(controls.get("_expected_dp_m")), rel_tol=0, abs_tol=1e-12)
        if controls.get("dp_m") is not None and controls.get("_expected_dp_m") is not None else False,
        "time_max": math.isclose(float(controls.get("time_max_s")), PROTOCOL["time_max_s"], rel_tol=0, abs_tol=1e-12)
        if controls.get("time_max_s") is not None else False,
        "time_out": math.isclose(float(controls.get("time_out_s")), PROTOCOL["time_out_s"], rel_tol=0, abs_tol=1e-12)
        if controls.get("time_out_s") is not None else False,
        "step_algorithm": controls.get("step_algorithm") == PROTOCOL["step_algorithm"],
        "verlet_steps": controls.get("verlet_steps") == PROTOCOL["verlet_steps"],
        "boundary": controls.get("boundary_formulation") == PROTOCOL["boundary_formulation"] and controls.get("boundary_parameter") == PROTOCOL["boundary_parameter"],
    }


def audit_case(record: dict[str, Any], prepared: dict[str, Any], run_info: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = Path(prepared["candidate_path"])
    generated_directory = ARTIFACT_ROOT / record["case_id"] / "generated"
    generated = generated_directory / record["case_id"]
    generated_xml = parse_generated_xml(generated.with_suffix(".xml"))
    generated_controls = dict(generated_xml.get("controls", {}))
    generated_controls["_expected_dp_m"] = record["dp_m"]
    control_match = controls_match_protocol(generated_controls)
    # GenCase's prefix is ``generated/<case_id>`` but its process log and
    # command record live one level above that prefix.
    gencase_log = generated_directory / "gencase.stdout.log"
    log_summary = parse_gencase_log(gencase_log)
    geometry = audit_geometry(candidate, generated, generated_xml)
    mass = audit_mass(generated_xml)
    artifacts = artifact_fingerprints(generated)
    return_code = run_info.get("return_code") if run_info else None
    if run_info is None and gencase_log.is_file():
        command_file = generated_directory / "gencase.command.json"
        if command_file.is_file():
            run_info = json.loads(command_file.read_text())
            return_code = run_info.get("return_code")
    completed = return_code == 0 and generated_xml.get("generated_xml_present", False) and not generated_xml.get("parse_error")
    all_controls_match = all(control_match.values())
    structural_anomalies = list(geometry["anomalies"]) + list(mass["anomalies"])
    if not all_controls_match:
        structural_anomalies.append("generated_controls_do_not_match_requested_protocol")
    if log_summary.get("total_particles") is not None and generated_xml.get("particles", {}).get("total_particles") is not None:
        if log_summary["total_particles"] != generated_xml["particles"]["total_particles"]:
            structural_anomalies.append("gencase_log_vs_generated_xml_total_particle_mismatch")
    return {
        **record,
        "source_definition": prepared["source_definition"],
        "source_geometry_signature": prepared["source_geometry_signature"],
        "definition": {
            "candidate": prepared["candidate_definition"],
            "candidate_controls": prepared["candidate_controls"],
        },
        "execution_status": "completed" if completed else "failed_or_missing_output",
        "acceptance_status": "preflight_only_not_physical_acceptance",
        "validation_scope": "CPU GenCase structural evidence only; no solver trajectory or physical observable",
        "run": run_info or {
            "command": None,
            "return_code": return_code,
            "stdout_log": fingerprint(gencase_log),
            "environment_policy": {
                "CUDA_VISIBLE_DEVICES": "",
                "NVIDIA_VISIBLE_DEVICES": "void",
                "solver_invocations": 0,
                "gpu_indices_used": [],
            },
        },
        "gencase_log_summary": log_summary,
        "generated_case": generated_xml,
        "controls_match_requested_protocol": control_match,
        "particle_counts": generated_xml.get("particles", {}),
        "mass_audit": mass,
        "geometry_audit": geometry,
        "artifacts": artifacts,
        "structural_anomalies": sorted(set(structural_anomalies)),
        "formal_production_authorized": False,
    }


def resolution_mass_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for background in (item["background_id"] for item in BACKGROUNDS):
        selected = [item for item in cases if item["background_id"] == background]
        masses = {
            item["level"]: item["mass_audit"].get("initial_fluid_mass_kg")
            for item in selected
        }
        values = [float(value) for value in masses.values() if value is not None]
        mean = sum(values) / len(values) if values else None
        spread = (max(values) - min(values)) / mean if values and mean else None
        result[background] = {
            "initial_fluid_mass_kg_by_level": masses,
            "mean_initial_fluid_mass_kg": mean,
            "relative_resolution_mass_spread": spread,
            "diagnostic_note": "reported for review; not an acceptance threshold in this GenCase-only preflight",
        }
    return result


def build_report(cases: list[dict[str, Any]], *, selected_case_ids: list[str] | None = None) -> dict[str, Any]:
    completed = sum(item["execution_status"] == "completed" for item in cases)
    anomaly_cases = [item["case_id"] for item in cases if item["structural_anomalies"]]
    return {
        "schema_version": 1,
        "audit_id": "R4_F1_CORE_PREFLIGHT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "R4 reviewer F1 core mother case A1/A2 CPU GenCase-only preflight",
        "matrix": {
            "required_case_count": 9,
            "selected_case_count": len(cases),
            "selected_case_ids": selected_case_ids or [item["case_id"] for item in cases],
            "backgrounds": [item["background_id"] for item in BACKGROUNDS],
            "levels": list(LEVELS),
            "cell_order": "background-major then coarse/medium/fine",
        },
        "protocol": PROTOCOL,
        "resource_policy": {
            "execution_kind": "CPU GenCase-only",
            "gencase_invocations": len(cases),
            "solver_invocations": 0,
            "cuda_launches": 0,
            "gpu_indices_used": [],
            "environment_policy": {
                "CUDA_VISIBLE_DEVICES": "",
                "NVIDIA_VISIBLE_DEVICES": "void",
            },
            "protected_scopes_untouched": [
                "vendor/official/DualSPHysics_v5.4",
                "upstream source trees",
            ],
        },
        "provenance": {
            "source_templates": "existing local F1 definitions under cases/F1",
            "r3_matrix_reference": "scripts/r3_g2_f1_f3_matrix.py",
            "r4_core_audit_reference": "campaigns/v0.1-candidate/R4-CORE-MOTHER-CASE-AUDIT.md",
            "old_r3_runs_reused_as_new_execution": False,
            "each_case_has_independent_definition_prefix_and_log": True,
        },
        "summary": {
            "gencase_completed_cells": completed,
            "gencase_failed_or_missing_cells": len(cases) - completed,
            "structural_anomaly_cases": anomaly_cases,
            "all_requested_controls_match": all(
                all(item["controls_match_requested_protocol"].values()) for item in cases
            ),
            "resolution_mass_summary": resolution_mass_summary(cases),
        },
        "cases": cases,
        "acceptance_boundary": {
            "acceptance_status": "preflight_structural_evidence_only",
            "physical_acceptance_performed": False,
            "reference_acceptance_performed": False,
            "solver_trajectory_available": False,
            "formal_production_authorized": False,
            "promotion_decision": "not_performed_by_this_preflight",
            "required_next_evidence": [
                "same-protocol solver execution under an explicitly approved resource plan",
                "identity/time/finite-state and unexplained-loss audit",
                "T1 resolution and external-observable evaluation",
                "T2 destination/wall/open-face and mass closure evidence",
            ],
        },
    }


def markdown_report(payload: dict[str, Any]) -> str:
    protocol = payload["protocol"]
    lines = [
        "# R4 F1 core preflight",
        "",
        "状态：**CPU GenCase-only structural evidence；不是 solver 运行、物理验收或生产准入。**",
        "",
        "本报告严格覆盖 `plain_dam_break`、`center_obstacle`、"
        "`twin_obstacle_split_remerge` × `coarse/medium/fine` 九个独立工况。",
        "每个工况均从现有 F1 定义复制到 R4 私有目录后单独改写；旧 R3 运行不计作本次执行。",
        "",
        "## 固定控制",
        "",
        f"- `dp`：`{protocol['spatial_resolution_m']}` m；`TimeMax={protocol['time_max_s']}` s；`TimeOut={protocol['time_out_s']}` s。",
        f"- `StepAlgorithm={protocol['step_algorithm']}`，`VerletSteps={protocol['verlet_steps']}`，`Boundary=1 (DBC)`。",
        f"- `SavePosDouble={protocol['save_pos_double']}`，`Shifting={protocol['shifting']}`。",
        "- 进程环境强制 `CUDA_VISIBLE_DEVICES=''`、`NVIDIA_VISIBLE_DEVICES='void'`；本脚本没有 solver 命令路径。",
        "",
        "## 九个工况结果",
        "",
        "| case | dp (m) | return code | total / bound / fluid | fluid mass (kg) | controls | anomalies |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for item in payload["cases"]:
        particles = item.get("particle_counts", {})
        mass = item.get("mass_audit", {})
        controls = "yes" if all(item.get("controls_match_requested_protocol", {}).values()) else "NO"
        anomalies = ", ".join(item.get("structural_anomalies", [])) or "none observed"
        return_code = item.get("run", {}).get("return_code")
        lines.append(
            f"| `{item['case_id']}` | {item['dp_m']:.3f} | `{return_code}` | "
            f"{particles.get('total_particles')} / {particles.get('boundary_particles')} / {particles.get('fluid_particles')} | "
            f"{mass.get('initial_fluid_mass_kg')} | {controls} | {anomalies} |"
        )
    lines.extend(
        [
            "",
            "## 结构与质量记录",
            "",
            f"- GenCase 完成：`{payload['summary']['gencase_completed_cells']}/{payload['matrix']['selected_case_count']}`；结构异常工况：`{len(payload['summary']['structural_anomaly_cases'])}`。",
            "- 每个工况记录了源定义、独立候选定义、GenCase 命令日志、`.xml/.bi4/.out` 与四类 VTK 产物的大小和 SHA-256。",
            "- 几何审计检查了 VTK 点数、有限坐标、定义域外点、流体—边界重复位置和非正粒子数；质量审计检查了 `rhop0·dp³` 与 GenCase `massfluid` 的一致性，并报告跨分辨率质量 spread。",
            "- 跨分辨率质量 spread 仅为诊断记录，不在本预检中设物理验收阈值。",
            "",
            "## 边界声明",
            "",
            "本产物的 `acceptance_status` 固定为 `preflight_structural_evidence_only`；未执行物理或参考验收，未提供 solver trajectory，也不作生产准入判断。下一步仍需在明确资源授权下运行同一协议的 solver，并完成 T1/T2 与外部观测门禁。",
            "",
            "私有生成物：`campaigns/v0.1-candidate/artifacts/r4-f1-core-preflight/`；独立候选定义：`campaigns/v0.1-candidate/cases/r4-f1-core-preflight/`。",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(payload: dict[str, Any]) -> None:
    atomic_write_json(REPORT_JSON, payload)
    atomic_write_text(REPORT_MD, markdown_report(payload))


def execute_preflight(selected: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for record in selected:
        prepared = materialize_definition(record)
        run_info = run_gencase(record, Path(prepared["candidate_path"]))
        results.append(audit_case(record, prepared, run_info))
    payload = build_report(results, selected_case_ids=[item["case_id"] for item in selected])
    write_reports(payload)
    return payload


def prepare_only(selected: list[dict[str, Any]]) -> dict[str, Any]:
    prepared_records = []
    for record in selected:
        prepared = materialize_definition(record)
        prepared_records.append(
            {
                **record,
                "source_definition": prepared["source_definition"],
                "source_geometry_signature": prepared["source_geometry_signature"],
                "definition": {
                    "candidate": prepared["candidate_definition"],
                    "candidate_controls": prepared["candidate_controls"],
                },
                "execution_status": "not_run",
                "acceptance_status": "preflight_only_not_physical_acceptance",
                "validation_scope": "definition-only preparation; GenCase not invoked",
                "formal_production_authorized": False,
                "structural_anomalies": [],
                "controls_match_requested_protocol": controls_match_protocol(
                    {**prepared["candidate_controls"], "_expected_dp_m": record["dp_m"]}
                ),
                "particle_counts": {},
                "mass_audit": {},
                "geometry_audit": {},
                "artifacts": {},
                "run": {"return_code": None, "command": None},
                "gencase_log_summary": {},
                "generated_case": {},
            }
        )
    payload = build_report(prepared_records, selected_case_ids=[item["case_id"] for item in selected])
    payload["resource_policy"]["gencase_invocations"] = 0
    payload["acceptance_boundary"]["promotion_decision"] = "not_performed_by_definition_preparation"
    write_reports(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "preflight", "all"),
        nargs="?",
        default="all",
        help="prepare definitions only, or run CPU GenCase preflight (default: all)",
    )
    parser.add_argument("--cases", nargs="*", help="optional subset of exact R4 case IDs")
    args = parser.parse_args(argv)
    known = {item["case_id"]: item for item in case_records()}
    selected_ids = args.cases or list(known)
    unknown = sorted(set(selected_ids) - set(known))
    if unknown:
        parser.error(f"unknown case IDs: {unknown}")
    selected = [known[item] for item in selected_ids]
    payload = prepare_only(selected) if args.action == "prepare" else execute_preflight(selected)
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    return 0 if payload["summary"]["gencase_failed_or_missing_cells"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
