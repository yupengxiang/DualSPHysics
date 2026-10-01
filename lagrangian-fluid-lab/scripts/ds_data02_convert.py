#!/usr/bin/env python3
"""Convert a completed DualSPHysics BI4 trajectory to a DS-DATA-02 HDF5.

The converter is deliberately a provenance bridge.  It reads a completed
solver receipt, its GenCase inputs, and the F1 owner metadata; it then invokes
the official PartVTK binary to expose the BI4 frames and delegates the
bounded, resumable HDF5 write to :mod:`trajectory_io`.  The source solver
directory is read-only and no solver, learner, or GPU worker is started.

The resulting file carries explicit SI units, typed ``(Zone, Idp)`` identity,
the solver's actual dimension evidence, coordinate-frame semantics, and
references/hashes for geometry and control sources.  The conversion report
also records a raw BI4 tree manifest and a Q-I audit.  Conversion is not
scientific Q-N acceptance and never grants production eligibility.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.ds_data02_integrity import audit_hdf5  # noqa: E402
from scripts.trajectory_io import convert_streaming  # noqa: E402


SCHEMA = "ds-data-02.bi4-trajectory-conversion.v1"
PARTVTK_DEFAULT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux" / "PartVTK_linux64"
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FRAME_RE = re.compile(r"^Part_(\d{4})\.bi4$")
CSV_FRAME_RE = re.compile(r"^Particles_(\d{4})\.csv$")
DIMENSION_RE = re.compile(r"\*\*\s*([23])D\s*[- ]?Simulation\s+parameters", re.I)
REQUIRED_CSV_COLUMNS = (
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp",
    "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]",
    "Mass [kg]", "Press [Pa]", "Type", "Mk",
)
DATASET_UNITS = {
    "time": "s",
    "position": "m",
    "velocity": "m/s",
    "density": "kg/m^3",
    "mass": "kg",
    "pressure": "Pa",
    "particle_id": "1",
    "particle_zone": "1",
    "valid": "1",
    "type": "1",
    "mk": "1",
}


class ConversionError(RuntimeError):
    """Raised when source provenance or conversion completeness is invalid."""


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _canonical_sha256(value: Any) -> str:
    """Hash JSON semantics with stable ordering, independent of whitespace."""
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ConversionError(f"source file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ConversionError(f"{label} cannot be read as JSON: {path}") from error
    if not isinstance(value, dict):
        raise ConversionError(f"{label} must contain a JSON object: {path}")
    return value


def _existing_path(value: Any, label: str) -> Path:
    if isinstance(value, Path):
        path = value.expanduser().resolve()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser().resolve()
    else:
        raise ConversionError(f"{label} path is absent")
    if not path.is_file():
        raise ConversionError(f"{label} is missing: {path}")
    return path


def _receipt_input(receipt: Mapping[str, Any], predicate: Any, label: str) -> Path:
    request = receipt.get("request")
    values = request.get("input_files", []) if isinstance(request, Mapping) else []
    for value in values:
        path = Path(str(value)).expanduser().resolve()
        if predicate(path):
            return _existing_path(path, label)
    raise ConversionError(f"{label} was not listed in the receipt input files")


def _receipt_inputs(receipt: Mapping[str, Any], predicate: Any) -> list[Path]:
    """Return all existing receipt inputs satisfying ``predicate``.

    Qualification receipts bind the immutable completed GenCase XML/BI4 and
    the copied motion file.  Keeping this helper separate from
    :func:`_receipt_input` lets family owners bind a motion asset without
    depending on an F1-specific filename or metadata schema.
    """
    request = receipt.get("request")
    values = request.get("input_files", []) if isinstance(request, Mapping) else []
    result: list[Path] = []
    for value in values:
        path = Path(str(value)).expanduser().resolve()
        if predicate(path) and path.is_file() and path not in result:
            result.append(path)
    return result


def _motion_input(receipts: Iterable[Mapping[str, Any]], generated_xml: Path | None = None) -> Path | None:
    """Find the copied native motion control bound by one of the receipts."""
    candidates: list[Path] = []
    for receipt in receipts:
        candidates.extend(_receipt_inputs(
            receipt,
            lambda path: path.suffix.lower() in {".dat", ".csv"}
            and "motion" in path.name.lower(),
        ))
    if not candidates:
        return None
    if generated_xml is not None:
        declared = ET.parse(generated_xml).getroot().find(".//mvrotfile/file")
        declared_name = declared.get("name") if declared is not None else None
        if declared_name:
            copied = [path for path in candidates
                      if path.name == Path(declared_name).name and path.parent == generated_xml.parent]
            if copied:
                return copied[0]
    # The generated case's copied control is the most concrete binding.  A
    # duplicate entry in the GenCase and solver receipts is harmless.
    return sorted(set(candidates), key=lambda path: str(path))[0]


def _parse_motion_control(path: Path | None, generated_xml: Path) -> dict[str, Any] | None:
    """Parse a native mvrotfile control and its rotation axis, if present."""
    root = ET.parse(generated_xml).getroot()
    rotation = root.find(".//mvrotfile")
    if rotation is None:
        return None
    file_node = rotation.find("./file")
    declared_name = file_node.get("name") if file_node is not None else None
    if path is None and declared_name:
        candidate = (generated_xml.parent / declared_name).resolve()
        path = candidate if candidate.is_file() else None
    if path is None or not path.is_file():
        raise ConversionError("generated mvrotfile has no existing copied motion input")
    p1_node = rotation.find("./axisp1")
    p2_node = rotation.find("./axisp2")
    if p1_node is None or p2_node is None:
        raise ConversionError("generated mvrotfile is missing axisp1/axisp2")
    try:
        p1 = np.asarray([float(p1_node.attrib[key]) for key in ("x", "y", "z")], dtype=np.float64)
        p2 = np.asarray([float(p2_node.attrib[key]) for key in ("x", "y", "z")], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise ConversionError("generated mvrotfile contains an invalid rotation axis") from error
    axis = p2 - p1
    norm = float(np.linalg.norm(axis))
    if not np.isfinite(norm) or norm <= 0:
        raise ConversionError("generated mvrotfile rotation axis has zero length")
    axis /= norm
    times: list[float] = []
    values: list[float] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pieces = [piece.strip() for piece in re.split(r"[;,\s]+", line) if piece.strip()]
        if len(pieces) < 2:
            raise ConversionError(f"motion control row {line_number} has fewer than two columns: {path}")
        try:
            time_value, angle_value = float(pieces[0]), float(pieces[1])
        except ValueError as error:
            raise ConversionError(f"motion control row {line_number} is not numeric: {path}") from error
        if not np.isfinite(time_value) or not np.isfinite(angle_value):
            raise ConversionError(f"motion control row {line_number} is non-finite: {path}")
        times.append(time_value)
        values.append(angle_value)
    if len(times) < 2 or not np.all(np.diff(np.asarray(times)) > 0):
        raise ConversionError(f"motion control times are not strictly increasing: {path}")
    units = str(rotation.attrib.get("anglesunits", "degrees")).strip().lower()
    if units.startswith("rad"):
        angles_rad = np.asarray(values, dtype=np.float64)
    elif units.startswith("deg"):
        angles_rad = np.deg2rad(np.asarray(values, dtype=np.float64))
    else:
        raise ConversionError(f"unsupported mvrotfile angle units {units!r}: {generated_xml}")
    time_array = np.asarray(times, dtype=np.float64)
    omega = np.gradient(angles_rad, time_array, edge_order=1)
    return {
        "kind": "rotation",
        "control_path": str(path.resolve()),
        "control_sha256": _sha256(path),
        "declared_name": declared_name,
        "anglesunits": units,
        "axis_origin_m": [float(value) for value in p1],
        "axis_unit": [float(value) for value in axis],
        "control_time_s": [float(time_array[0]), float(time_array[-1])],
        "control_rows": int(len(time_array)),
        "angle_start_rad": float(angles_rad[0]),
        "angle_end_rad": float(angles_rad[-1]),
        "angle_range_rad": [float(angles_rad.min()), float(angles_rad.max())],
        "omega_min_rad_s": float(omega.min()),
        "omega_max_rad_s": float(omega.max()),
        # Arrays are intentionally retained in provenance only in memory.  A
        # converted HDF5 stores the frame-aligned values in rigid_body_state.
        "_times": time_array,
        "_angles_rad": angles_rad,
        "_omega_rad_s": omega,
    }


def _solver_population(run_out: Path, gencase: Mapping[str, Any]) -> dict[str, Any]:
    """Collect native fixed/moving/fluid population and exclusion facts."""
    text = run_out.read_text(errors="replace")
    patterns = {
        "initial_total": r"Particles of simulation\s*\(initial\)\s*:\s*([0-9,]+)",
        "excluded_particles": r"Excluded particles[^:]*:\s*([0-9,]+)",
        "case_nfixed": r"CaseNfixed\s*=\s*([0-9,]+)",
        "case_nmoving": r"CaseNmoving\s*=\s*([0-9,]+)",
        "case_nfluid": r"CaseNfluid\s*=\s*([0-9,]+)",
        "part_files": r"PART files[^:]*:\s*([0-9,]+)",
        "steps": r"Steps of simulation[^:]*:\s*([0-9,]+)",
        "dt_adjusted_to_dtmin": r"DTs adjusted to DtMin[^:]*:\s*([0-9,]+)",
    }
    result: dict[str, Any] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result[key] = int(match.group(1).replace(",", ""))
    result.update({
        "gencase_total_particles": int(gencase.get("total_particles", 0)),
        "gencase_fluid_particles": int(gencase.get("fluid_particles", 0)),
        "gencase_solver_dimension": gencase.get("solver_dimension_from_gencase"),
        "source": str(run_out),
    })
    return result


def _read_dimension(run_out: Path, generated_xml: Path, owner: Mapping[str, Any], gencase: Mapping[str, Any]) -> dict[str, Any]:
    text = run_out.read_text(errors="replace")
    matches = {int(match.group(1)) for match in DIMENSION_RE.finditer(text)}
    if len(matches) != 1:
        raise ConversionError(f"solver log has no unique explicit 2D/3D banner: {run_out}")
    dimension = next(iter(matches))
    xml_root = ET.parse(generated_xml).getroot()
    data2d = xml_root.find(".//data2d")
    xml_dimension: int | None = None
    if data2d is not None and data2d.get("value") is not None:
        raw = data2d.get("value", "").strip().lower()
        if raw in {"true", "1"}:
            xml_dimension = 2
        elif raw in {"false", "0"}:
            xml_dimension = 3
    owner_dimension = owner.get("source_mother", {}).get("solver_dimension")
    owner_dimension_number = None
    if isinstance(owner_dimension, str) and owner_dimension[:1] in {"2", "3"}:
        owner_dimension_number = int(owner_dimension[0])
    gencase_dimension = gencase.get("solver_dimension_from_gencase")
    observed = {dimension, *(x for x in (xml_dimension, owner_dimension_number, gencase_dimension) if x is not None)}
    if len(observed) != 1:
        raise ConversionError(f"conflicting actual dimension evidence: {sorted(observed)}")
    evidence_lines = [line.strip()[:400] for line in text.splitlines() if DIMENSION_RE.search(line)]
    return {
        "solver_dimension": dimension,
        "coordinate_components": 3,
        "source": "solver_run_log_explicit_banner",
        "evidence_lines": evidence_lines[:8],
        "generated_xml_data2d": data2d.get("value") if data2d is not None else None,
        "owner_metadata_dimension": owner_dimension,
        "gencase_receipt_dimension": gencase_dimension,
        "inference_from_coordinate_values": False,
    }


def _condition_bindings(owner: Mapping[str, Any], parameters: Mapping[str, Any], motion: ET.Element | None,
                        motion_control: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build resolution-independent physical condition bindings.

    The generated definition XML contains resolution-dependent ``dp``, ``h``,
    and particle mass values.  Those values belong to discretization, so the
    geometry binding is taken from the owner metadata's physical geometry.  A
    control binding retains the declared controls, event window, physical
    initial-state facts, and the generated XML motion/solver parameter
    declaration.
    """
    geometry_binding = {
        "geometry_family_id": owner.get("geometry_family_id"),
        "geometry": _json_value(owner.get("geometry")),
    }
    source_mother = owner.get("source_mother", {})
    actual = source_mother.get("actual_successful_run", {})
    if not isinstance(actual, Mapping):
        actual = {}
    initial_keys = (
        "boundary", "coordinate_components", "finite_wall_faces", "initial_flow_direction",
        "initial_fluid_extent_m", "nominal_initial_fluid_fill_box_extent_m", "open_top",
        "tank_extent_m", "solver_dimension",
    )
    initial_state = {key: _json_value(actual.get(key)) for key in initial_keys if key in actual}
    control_binding = {
        "control_family_id": owner.get("control_family_id"),
        "recipe_id": owner.get("recipe_id"),
        "solver_parameters": _json_value(owner.get("solver_parameters", {})),
        "parameter_values": _json_value(owner.get("parameter_values", {})),
        "event_window": _json_value(owner.get("event_window", {})),
        "initial_state": initial_state,
        "source_mother": _json_value(source_mother),
        "physical_case_id": owner.get("physical_case_id"),
        "lineage_group_id": owner.get("lineage_group_id"),
        "paired_background_id": owner.get("paired_background_id"),
        "view_id": owner.get("view_id"),
        "motion_control": {
            "element_present": motion is not None,
            "element_empty": motion is not None and len(motion) == 0 and not motion.attrib,
            "execution_parameters": _json_value(parameters),
            "parsed_control": _json_value({key: value for key, value in (motion_control or {}).items()
                                            if not str(key).startswith("_")}),
        },
    }
    missing = []
    if geometry_binding["geometry"] is None:
        missing.append("geometry_semantic_content")
    if not control_binding["solver_parameters"]:
        missing.append("control_semantic_content")
    parsed_motion = {
        str(key): value for key, value in (motion_control or {}).items()
        if not str(key).startswith("_") and str(key) not in {"control_path"}
    }
    # Keep the historical composite control hash for compatibility, but also
    # publish hashes with an explicit numerical/physical split.  This lets
    # independent DtFixed/save-cadence studies compare the same physical
    # condition without pretending that their numerical recipes are identical.
    physical_condition = {
        "family_id": owner.get("family_id"),
        "physical_case_id": owner.get("physical_case_id"),
        "geometry_family_id": owner.get("geometry_family_id"),
        "geometry": _json_value(owner.get("geometry", {})),
        "parameter_values": _json_value(owner.get("parameter_values", {})),
        "event_window": _json_value(owner.get("event_window", {})),
        "control_family_id": owner.get("control_family_id"),
        "motion_control": _json_value(parsed_motion),
    }
    numerical_recipe = {
        "family_id": owner.get("family_id"),
        "resolution": owner.get("resolution"),
        "solver_parameters": _json_value(owner.get("solver_parameters", {})),
        "generated_xml_execution_parameters": _json_value(parameters),
        "solver_dimension": _json_value(source_mother.get("solver_dimension")),
    }
    return {
        "geometry": geometry_binding,
        "geometry_sha256": _canonical_sha256(geometry_binding),
        "control": control_binding,
        "control_sha256": _canonical_sha256(control_binding),
        "physical_condition": physical_condition,
        "physical_condition_sha256": _canonical_sha256(physical_condition),
        "physical_condition_hash_scope": "geometry, physical case/parameter values, event window, control family, copied motion semantic content; excludes resolution and solver numerical parameters",
        "numerical_recipe": numerical_recipe,
        "numerical_recipe_sha256": _canonical_sha256(numerical_recipe),
        "numerical_recipe_hash_scope": "resolution, solver parameters, generated execution parameters, and solver dimension declaration",
        "missing_requirements": missing,
    }


def _raw_manifest(data_root: Path) -> tuple[list[Path], dict[str, Any]]:
    if not data_root.is_dir():
        raise ConversionError(f"solver BI4 directory is missing: {data_root}")
    files = sorted(path for path in data_root.rglob("*") if path.is_file())
    frame_paths = []
    frame_indices = []
    entries = []
    for path in files:
        relative = path.relative_to(data_root).as_posix()
        digest = _sha256(path)
        entries.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
        match = FRAME_RE.fullmatch(path.name)
        if match:
            frame_paths.append(path)
            frame_indices.append(int(match.group(1)))
    expected = list(range(len(frame_paths)))
    if sorted(frame_indices) != expected:
        raise ConversionError(
            f"BI4 frame indices are not contiguous from zero: {sorted(frame_indices)[:4]} ... {sorted(frame_indices)[-4:]}"
        )
    manifest_bytes = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return sorted(frame_paths), {
        "root": str(data_root),
        "file_count": len(entries),
        "total_bytes": int(sum(int(item["bytes"]) for item in entries)),
        "files": entries,
        "tree_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "frame_count": len(frame_paths),
        "frame_paths": [str(path) for path in sorted(frame_paths)],
    }


def _source_inputs(solver: Mapping[str, Any], gencase: Mapping[str, Any], owner_path: Path,
                  generated_xml: Path, definition_xml: Path, solver_receipt_path: Path,
                  gencase_receipt_path: Path) -> dict[str, str]:
    paths: list[Path] = [solver_receipt_path, gencase_receipt_path, owner_path, generated_xml, definition_xml]
    for receipt in (solver, gencase):
        request = receipt.get("request")
        values = request.get("input_files", []) if isinstance(request, Mapping) else []
        for value in values:
            path = Path(str(value)).expanduser().resolve()
            if path.is_file() and path not in paths:
                paths.append(path)
    return {str(path): _sha256(path) for path in paths}


def load_provenance(solver_receipt_path: Path, gencase_receipt_path: Path,
                    owner_metadata_path: Path) -> dict[str, Any]:
    solver = _load_json(solver_receipt_path, "solver receipt")
    gencase = _load_json(gencase_receipt_path, "GenCase receipt")
    owner = _load_json(owner_metadata_path, "family owner metadata")
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed":
        raise ConversionError("solver receipt is not a completed shared-runner receipt")
    if gencase.get("schema") != "ds02.execution-receipt.v1" or gencase.get("status") != "completed":
        raise ConversionError("GenCase receipt is not a completed shared-runner receipt")
    if solver.get("request", {}).get("kind") != "qualification":
        raise ConversionError("source solver receipt is not a qualification attempt")
    solver_request = solver.get("request", {})
    gencase_request = gencase.get("request", {})
    owner_case_id = str(owner.get("case_id", ""))
    case_id = str(solver_request.get("case_id", owner_case_id))
    if not CASE_ID_RE.fullmatch(case_id):
        raise ConversionError(f"invalid case id in solver receipt: {case_id!r}")
    if owner_case_id and owner_case_id != case_id:
        raise ConversionError(f"family owner metadata case_id differs from solver receipt: {owner_case_id!r} != {case_id!r}")
    owner_schema = str(owner.get("schema", ""))
    if not owner_schema.startswith("ds-data-02.") or not owner_schema.endswith("generator.v1"):
        raise ConversionError(f"owner metadata is not a DS-DATA-02 generator record: {owner_schema!r}")
    raw_solver_root = solver.get("output_root")
    if not isinstance(raw_solver_root, str) or not raw_solver_root:
        raise ConversionError("solver receipt has no output_root directory")
    solver_root = Path(raw_solver_root).expanduser().resolve()
    if not solver_root.is_dir():
        raise ConversionError(f"solver output root is missing: {solver_root}")
    solver_dir_candidates = [
        solver_root / "solver",
        solver_root / "solver_output",
        solver_root / case_id,
        solver_root,
        *[p for p in solver_root.iterdir() if p.is_dir()],
    ]
    solver_dir = next((candidate for candidate in solver_dir_candidates
                       if (candidate / "Run.out").is_file() and (candidate / "RunPARTs.csv").is_file()), None)
    if solver_dir is None:
        raise ConversionError(f"solver output has no Run.out/RunPARTs.csv directory: {solver_root}")
    run_out = _existing_path(solver_dir / "Run.out", "solver Run.out")
    run_csv = _existing_path(solver_dir / "Run.csv", "solver Run.csv")
    run_parts_csv = _existing_path(solver_dir / "RunPARTs.csv", "solver RunPARTs.csv")
    data_root = solver_dir / "data"
    solver_inputs = solver_request.get("input_files", [])
    listed_generated_xml = next((Path(str(value)).expanduser().resolve() for value in solver_inputs
                                 if Path(str(value)).suffix.lower() == ".xml"
                                 and not Path(str(value)).name.endswith("_Def.xml")), None)
    generated_xml = _existing_path(listed_generated_xml, "generated case XML") if listed_generated_xml else None
    if generated_xml is None:
        raise ConversionError("solver receipt did not list generated case XML")
    gencase_receipt_from_solver = next((Path(str(value)).expanduser().resolve() for value in solver_inputs
                                       if Path(str(value)).name == "execution-receipt.json"), None)
    if gencase_receipt_from_solver is not None and gencase_receipt_from_solver != gencase_receipt_path.resolve():
        raise ConversionError("explicit GenCase receipt differs from the solver receipt binding")
    definition_xml = _receipt_input(gencase, lambda path: path.name.endswith("_Def.xml"), "GenCase definition XML")
    owner_from_inputs = _receipt_input(gencase, lambda path: path.name.endswith(".metadata.json"), "family owner metadata")
    if owner_from_inputs != owner_metadata_path.resolve():
        raise ConversionError("explicit family owner metadata differs from the GenCase receipt binding")
    frame_paths, raw = _raw_manifest(data_root)
    if not frame_paths:
        raise ConversionError("solver output has no Part_XXXX.bi4 frames")
    dimension = _read_dimension(run_out, generated_xml, owner, gencase)
    xml_root = ET.parse(generated_xml).getroot()
    motion = xml_root.find(".//motion")
    parameters = {
        str(node.get("key")): node.get("value")
        for node in xml_root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    copied_motion = _motion_input((solver, gencase), generated_xml)
    motion_control = _parse_motion_control(copied_motion, generated_xml)
    bindings = _condition_bindings(owner, parameters, motion, motion_control)
    geometry = owner.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ConversionError("owner metadata has no structured geometry")
    population = _solver_population(run_out, gencase)
    # A completed solver receipt is not itself numerical qualification.  The
    # population and native exclusion facts remain raw evidence for later
    # Q-I/Q-N scope checks.
    boundary_geometry = owner.get("geometry", {})
    if not isinstance(boundary_geometry, Mapping):
        boundary_geometry = {}
    q_i = owner.get("quality_contract", {}).get("q_i", {})
    boundary = {
        "boundary_mode": "open" if boundary_geometry.get("open_boundary_faces") else "closed",
        "physical_boundary_faces": _json_value(boundary_geometry.get("finite_wall_faces", [])),
        "open_boundary_faces": _json_value(boundary_geometry.get("open_boundary_faces", [])),
        "source_mother_boundary": owner.get("source_mother", {}).get("boundary"),
        "lifecycle_semantics": "initial native fluid cohort; valid=false records native solver exclusion; no births are inferred",
        "lifecycle_contract": _json_value(q_i),
        "native_exclusion_classification": "solver-reported Excluded particles are retained as unknown_mass until event audit classifies them",
    }
    source_inputs = _source_inputs(
        solver, gencase, owner_metadata_path.resolve(), generated_xml, definition_xml,
        solver_receipt_path.resolve(), gencase_receipt_path.resolve(),
    )
    return {
        "case_id": case_id,
        "family_id": str(owner.get("family_id", solver_request.get("family_id", "unknown"))),
        "mechanism_id": owner.get("mechanism_id"),
        "recipe_id": owner.get("recipe_id"),
        "resolution": owner.get("resolution"),
        "solver_receipt": solver,
        "gencase_receipt": gencase,
        "owner_metadata": owner,
        "solver_receipt_path": str(solver_receipt_path.resolve()),
        "gencase_receipt_path": str(gencase_receipt_path.resolve()),
        "owner_metadata_path": str(owner_metadata_path.resolve()),
        "generated_xml_path": str(generated_xml),
        "definition_xml_path": str(definition_xml),
        "run_out_path": str(run_out),
        "run_csv_path": str(run_csv),
        "run_parts_csv_path": str(run_parts_csv),
        "data_root": str(data_root),
        "raw_manifest": raw,
        "dimension_evidence": dimension,
        "geometry": _json_value(geometry),
        "source_provenance_kind": owner_schema,
        "population": population,
        "control": {
            "control_family_id": owner.get("control_family_id"),
            "recipe_id": owner.get("recipe_id"),
            "solver_parameters": _json_value(owner.get("solver_parameters", {})),
            "generated_xml_execution_parameters": parameters,
        },
        "motion_control": {
            "source": str(generated_xml),
            "sha256": _sha256(generated_xml),
            "copied_control_path": str(copied_motion) if copied_motion else None,
            "copied_control_sha256": _sha256(copied_motion) if copied_motion else None,
            "element_present": motion is not None,
            "element_empty": motion is not None and len(motion) == 0 and not motion.attrib,
            "semantics": "empty motion element in generated case XML" if motion is not None and len(motion) == 0 and not motion.attrib else "declared by generated case XML",
            "parsed_control": _json_value({key: value for key, value in (motion_control or {}).items()
                                            if not str(key).startswith("_")}),
        },
        "motion_control_spec": motion_control,
        "condition_bindings": bindings,
        "boundary": boundary,
        "source_input_hashes": source_inputs,
        "source_receipt_sha256": {
            "solver_receipt": _sha256(solver_receipt_path),
            "gencase_receipt": _sha256(gencase_receipt_path),
            "owner_metadata": _sha256(owner_metadata_path),
            "generated_xml": _sha256(generated_xml),
            "definition_xml": _sha256(definition_xml),
            "solver_run_out": _sha256(run_out),
            "solver_run_csv": _sha256(run_csv),
            "solver_run_parts_csv": _sha256(run_parts_csv),
        },
    }


def _validate_csv_header(path: Path) -> None:
    with path.open(encoding="utf-8", errors="replace") as stream:
        lines = [next(stream, "") for _ in range(4)]
    header = lines[3].strip().rstrip(",") if len(lines) >= 4 else ""
    columns = [column.strip() for column in header.split(",") if column.strip()]
    missing = [column for column in REQUIRED_CSV_COLUMNS if column not in columns]
    if missing:
        raise ConversionError(f"PartVTK CSV is missing required unit-labelled columns: {missing}")


def _csv_frames(csv_root: Path, expected_frames: int) -> list[Path]:
    paths = sorted(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    indices = [int(CSV_FRAME_RE.fullmatch(path.name).group(1)) for path in paths]
    if indices != list(range(expected_frames)):
        raise ConversionError(f"PartVTK CSV frame set is incomplete: {indices[:4]} ... {indices[-4:]}")
    for path in paths:
        _validate_csv_header(path)
    return paths


def _run_partvtk(partvtk: Path, data_root: Path, csv_root: Path, frame_count: int, threads: int) -> dict[str, Any]:
    if not partvtk.is_file():
        raise ConversionError(f"official PartVTK binary is missing: {partvtk}")
    csv_root.mkdir(parents=True, exist_ok=True)
    command = [
        str(partvtk), "-dirdata", str(data_root), f"-first:0", f"-last:{frame_count - 1}",
        f"-threads:{threads}", "-savecsv", str(csv_root / "Particles"),
        "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    log_path = csv_root.parent / "partvtk.stdout.log"
    existing_frames = list(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if len(existing_frames) == frame_count and log_path.is_file():
        return {
            "path": str(partvtk),
            "sha256": _sha256(partvtk),
            "command": command,
            "returncode": 0,
            "stdout_log": str(log_path),
            "stdout_sha256": _sha256(log_path),
        }
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{partvtk.parent}:{env.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=LAB_ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace", check=False)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise ConversionError(f"PartVTK failed with return code {completed.returncode}: {completed.stdout[-1200:]}")
    return {
        "path": str(partvtk),
        "sha256": _sha256(partvtk),
        "command": command,
        "returncode": completed.returncode,
        "stdout_log": str(log_path),
        "stdout_sha256": _sha256(log_path),
    }


def _csv_manifest(paths: Iterable[Path], csv_root: Path) -> dict[str, Any]:
    entries = [{"path": path.relative_to(csv_root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
               for path in sorted(paths)]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "root": str(csv_root),
        "file_count": len(entries),
        "total_bytes": int(sum(int(entry["bytes"]) for entry in entries)),
        "tree_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": entries,
    }


RIGID_BODY_DTYPE = np.dtype([
    ("time_s", "<f8"),
    ("body_id", "<i4"),
    ("valid", "u1"),
    ("actual_angle_rad", "<f8"),
    ("prescribed_angle_rad", "<f8"),
    ("angle_residual_rad", "<f8"),
    ("actual_omega_rad_s", "<f8"),
    ("prescribed_omega_rad_s", "<f8"),
    ("omega_residual_rad_s", "<f8"),
    ("actual_com_x_m", "<f8"),
    ("actual_com_y_m", "<f8"),
    ("actual_com_z_m", "<f8"),
    ("expected_com_x_m", "<f8"),
    ("expected_com_y_m", "<f8"),
    ("expected_com_z_m", "<f8"),
    ("position_rms_m", "<f8"),
    ("position_max_m", "<f8"),
    ("velocity_rms_m_s", "<f8"),
    ("velocity_max_m_s", "<f8"),
    ("moving_node_count", "<i8"),
    ("expected_node_count", "<i8"),
])


def _rotate_points(points: np.ndarray, origin: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotate points about a fixed axis using Rodrigues' formula."""
    shifted = np.asarray(points, dtype=np.float64) - origin
    cosine, sine = float(np.cos(angle)), float(np.sin(angle))
    cross = np.cross(axis, shifted)
    parallel = shifted @ axis
    return origin + cosine * shifted + sine * cross + (1.0 - cosine) * parallel[:, None] * axis


def _fit_axis_angle(points0: np.ndarray, points: np.ndarray, origin: np.ndarray,
                    axis: np.ndarray) -> float:
    """Fit the signed rotation angle of actual moving nodes around the axis."""
    q = np.asarray(points0, dtype=np.float64) - origin
    r = np.asarray(points, dtype=np.float64) - origin
    q_perp = q - (q @ axis)[:, None] * axis
    r_perp = r - (r @ axis)[:, None] * axis
    denominator = np.sum(q_perp * q_perp, axis=1)
    usable = denominator > 1.0e-18
    if not np.any(usable):
        raise ConversionError("moving boundary nodes do not span the declared rotation axis")
    denom = denominator[usable]
    cosine = np.sum(q_perp[usable] * r_perp[usable], axis=1) / denom
    sine = np.sum(axis * np.cross(q_perp[usable], r_perp[usable]), axis=1) / denom
    return float(np.arctan2(np.sum(sine), np.sum(cosine)))


def _write_rigid_body_state(path: Path, provenance: Mapping[str, Any], run_times: list[float]) -> dict[str, Any]:
    """Persist pose/velocity reconstructed from the actual moving nodes.

    DualSPHysics emits per-node moving-boundary positions and velocities (the
    PartVTK native Type=1 code; Type=2 is reserved for floating bodies) in
    every BI4 frame.  The fitted angle and residuals below are therefore an observation
    of the saved moving boundary, while the prescribed values come from the
    copied ``mvrotfile``.  No kinematic state is filled by a model or by a
    filename convention.
    """
    spec = provenance.get("motion_control_spec")
    if not isinstance(spec, Mapping) or spec.get("kind") != "rotation":
        return {"status": "not_applicable", "reason": "no_rotational_motion_control"}
    control_times = np.asarray(spec.get("_times"), dtype=np.float64)
    control_angles = np.asarray(spec.get("_angles_rad"), dtype=np.float64)
    control_omega = np.asarray(spec.get("_omega_rad_s"), dtype=np.float64)
    if control_times.ndim != 1 or len(control_times) < 2:
        raise ConversionError("parsed motion control has no usable time axis")
    origin = np.asarray(spec["axis_origin_m"], dtype=np.float64)
    axis = np.asarray(spec["axis_unit"], dtype=np.float64)
    with h5py.File(path, "r+") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        type_values = np.asarray(handle["type"][0, :], dtype=np.int64)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        # PartVTK's native type code is 1 for moving boundary nodes and 2 for
        # floating bodies.  A family with a declared CaseNmoving population
        # must use Type=1; Type=2 remains a separate floating-body ledger.
        population = provenance.get("population", {})
        moving_type_code = 1 if int(population.get("case_nmoving", 0) or 0) > 0 else 2
        initial_moving = (type_values == moving_type_code) & valid[0]
        if not np.any(initial_moving):
            return {"status": "missing", "reason": f"no_type{moving_type_code}_moving_nodes_in_initial_frame"}
        initial_position = np.asarray(handle["position"][0, initial_moving, :], dtype=np.float64)
        # First fit the saved moving-node pose without assuming that the
        # signed axis convention in the generated XML is the same convention
        # used by PartVTK.  DualSPHysics versions/case recipes can reverse the
        # native mvrotfile sign while preserving the same physical motion.
        # Choose between the two explicitly auditable candidates from the
        # actual saved nodes; never hide the convention in a filename or
        # family-specific constant.
        actual_angles = np.full(len(times), np.nan, dtype=np.float64)
        for frame, time_value in enumerate(times):
            active = initial_moving & valid[frame]
            current_position = np.asarray(handle["position"][frame, active, :], dtype=np.float64)
            if len(current_position):
                actual_angles[frame] = _fit_axis_angle(initial_position[active[initial_moving]], current_position, origin, axis)
        finite_angles = np.isfinite(actual_angles)
        if not finite_angles.all():
            raise ConversionError("moving boundary is absent in one or more saved frames")
        actual_angles = np.unwrap(actual_angles)
        actual_omega = np.gradient(actual_angles, times, edge_order=1)
        prescribed_angle_base = np.interp(times, control_times, control_angles)
        prescribed_omega_base = np.interp(times, control_times, control_omega)
        sign_residuals = {}
        for sign in (1.0, -1.0):
            angular_residual = np.arctan2(
                np.sin(actual_angles - sign * prescribed_angle_base),
                np.cos(actual_angles - sign * prescribed_angle_base),
            )
            sign_residuals[str(int(sign))] = {
                "angle_rms_rad": float(np.sqrt(np.mean(angular_residual ** 2))),
                "angle_max_rad": float(np.max(np.abs(angular_residual))),
            }
        control_sign = min(sign_residuals, key=lambda key: sign_residuals[key]["angle_rms_rad"])
        control_sign_applied = float(control_sign)
        expected_angles = control_sign_applied * prescribed_angle_base
        expected_omega = control_sign_applied * prescribed_omega_base
        rows = np.zeros(len(times), dtype=RIGID_BODY_DTYPE)
        for frame, time_value in enumerate(times):
            active = initial_moving & valid[frame]
            current_position = np.asarray(handle["position"][frame, active, :], dtype=np.float64)
            current_velocity = np.asarray(handle["velocity"][frame, active, :], dtype=np.float64)
            expected_position = _rotate_points(initial_position, origin, axis, float(expected_angles[frame]))
            expected_velocity = np.cross(
                expected_omega[frame] * axis,
                expected_position - origin,
            )
            if len(current_position):
                expected_current_position = expected_position[active[initial_moving]]
                expected_current_velocity = expected_velocity[active[initial_moving]]
                position_delta = current_position - expected_current_position
                velocity_delta = current_velocity - expected_current_velocity
                actual_com = current_position.mean(axis=0)
                expected_com = expected_current_position.mean(axis=0)
                position_norm = np.linalg.norm(position_delta, axis=1)
                velocity_norm = np.linalg.norm(velocity_delta, axis=1)
                rows[frame]["actual_com_x_m"] = actual_com[0]
                rows[frame]["actual_com_y_m"] = actual_com[1]
                rows[frame]["actual_com_z_m"] = actual_com[2]
                rows[frame]["expected_com_x_m"] = expected_com[0]
                rows[frame]["expected_com_y_m"] = expected_com[1]
                rows[frame]["expected_com_z_m"] = expected_com[2]
                rows[frame]["position_rms_m"] = float(np.sqrt(np.mean(position_norm ** 2)))
                rows[frame]["position_max_m"] = float(position_norm.max())
                rows[frame]["velocity_rms_m_s"] = float(np.sqrt(np.mean(velocity_norm ** 2)))
                rows[frame]["velocity_max_m_s"] = float(velocity_norm.max())
            rows[frame]["time_s"] = float(time_value)
            rows[frame]["body_id"] = 1
            rows[frame]["valid"] = 1 if len(current_position) == len(initial_position) else 0
            rows[frame]["prescribed_angle_rad"] = float(expected_angles[frame])
            rows[frame]["prescribed_omega_rad_s"] = float(expected_omega[frame])
            rows[frame]["moving_node_count"] = int(len(current_position))
            rows[frame]["expected_node_count"] = int(len(initial_position))
        rows["actual_angle_rad"] = actual_angles
        rows["angle_residual_rad"] = np.arctan2(
            np.sin(actual_angles - expected_angles), np.cos(actual_angles - expected_angles),
        )
        rows["actual_omega_rad_s"] = actual_omega
        rows["omega_residual_rad_s"] = actual_omega - expected_omega
        if "rigid_body_state" in handle:
            del handle["rigid_body_state"]
        dataset = handle.create_dataset("rigid_body_state", data=rows, compression="gzip")
        dataset.attrs["schema"] = "ds-data-02.rigid-body-state.v1"
        dataset.attrs["fields_json"] = json.dumps({name: str(dtype) for name, (dtype, _) in rows.dtype.fields.items()}, sort_keys=True)
        dataset.attrs["units_json"] = json.dumps({
            "time_s": "s", "actual_angle_rad": "rad", "prescribed_angle_rad": "rad",
            "angle_residual_rad": "rad", "actual_omega_rad_s": "rad/s",
            "prescribed_omega_rad_s": "rad/s", "omega_residual_rad_s": "rad/s",
            "actual_com_*_m": "m", "expected_com_*_m": "m", "position_rms_m": "m",
            "position_max_m": "m", "velocity_rms_m_s": "m/s", "velocity_max_m_s": "m/s",
            "moving_node_count": "1", "expected_node_count": "1",
        }, sort_keys=True)
        dataset.attrs["pose_source"] = f"actual PartVTK Type={moving_type_code} moving-node positions; axis-fit Rodrigues pose"
        dataset.attrs["velocity_source"] = f"actual PartVTK Type={moving_type_code} moving-node velocities; prescribed omega cross radius comparison"
        dataset.attrs["control_reference"] = str(spec["control_path"])
        dataset.attrs["control_reference_sha256"] = str(spec["control_sha256"])
        dataset.attrs["control_sign_applied"] = control_sign_applied
        dataset.attrs["sign_selection_method"] = "minimum actual moving-node angular residual over +/- copied mvrotfile control"
        dataset.attrs["sign_selection_residuals_json"] = json.dumps(sign_residuals, sort_keys=True)
        dataset.attrs["axis_origin_m"] = origin
        dataset.attrs["axis_unit"] = axis
        handle.attrs["rigid_body_state_source"] = "actual_saved_moving_nodes_fit_to_copied_mvrotfile"
        handle.attrs["rigid_body_state_control_sha256"] = str(spec["control_sha256"])
        handle.attrs["rigid_body_state_control_sign_applied"] = control_sign_applied
        handle.attrs["rigid_body_state_axis_origin_m"] = origin
        handle.attrs["rigid_body_state_axis_unit"] = axis
    return {
        "status": "pass",
        "dataset": "rigid_body_state",
        "frames": int(len(rows)),
        "moving_node_count": int(len(initial_position)),
        "moving_type_code": moving_type_code,
        "control_sign_applied": control_sign_applied,
        "sign_selection_method": "minimum actual moving-node angular residual over +/- copied mvrotfile control",
        "sign_selection_residuals": sign_residuals,
        "max_position_rms_m": float(np.nanmax(rows["position_rms_m"])),
        "max_position_max_m": float(np.nanmax(rows["position_max_m"])),
        "max_velocity_rms_m_s": float(np.nanmax(rows["velocity_rms_m_s"])),
        "max_velocity_max_m_s": float(np.nanmax(rows["velocity_max_m_s"])),
        "max_abs_angle_residual_rad": float(np.nanmax(np.abs(rows["angle_residual_rad"]))),
        "max_abs_omega_residual_rad_s": float(np.nanmax(np.abs(rows["omega_residual_rad_s"]))),
        "all_moving_nodes_present": bool(np.all(rows["valid"] == 1)),
    }


def _run_times(run_parts_csv: Path) -> list[float]:
    with run_parts_csv.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = reader.fieldnames or []
        time_field = next((field for field in fields if field.strip().lower().startswith("timestep")), None)
        if time_field is None:
            time_field = next((field for field in fields if field.strip().lower() == "physicaltime"), None)
        if time_field is None:
            raise ConversionError(f"solver per-frame CSV has no TimeStep/PhysicalTime column: {run_parts_csv}")
        values = []
        for row in reader:
            value = row.get(time_field)
            if value not in (None, ""):
                values.append(float(value.replace(",", "")))
    if not values:
        raise ConversionError(f"solver per-frame CSV has no time values: {run_parts_csv}")
    values_array = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values_array).all() or len(values_array) < 2 or not np.all(np.diff(values_array) > 0):
        raise ConversionError(f"solver RunPARTs.csv TimeStep values are not finite and strictly increasing: {run_parts_csv}")
    return values


def _set_hdf5_metadata(path: Path, provenance: Mapping[str, Any], partvtk: Mapping[str, Any],
                       csv_manifest: Mapping[str, Any], run_times: list[float]) -> None:
    owner = provenance["owner_metadata"]
    source_hashes = provenance["source_receipt_sha256"]
    root_attrs = {
        "schema": SCHEMA,
        "schema_version": 1,
        "case_id": provenance["case_id"],
        "family_id": provenance["family_id"],
        "mechanism_id": provenance.get("mechanism_id") or "",
        "recipe_id": provenance.get("recipe_id") or "",
        "resolution": provenance.get("resolution") or "",
        "source_format": "DualSPHysics Part_XXXX.bi4 via official PartVTK",
        "identity_key": "(Zone,Idp)",
        "identity_key_fields": "Zone,Idp",
        "solver_dimension": int(provenance["dimension_evidence"]["solver_dimension"]),
        "solver_dimension_evidence": json.dumps(provenance["dimension_evidence"], ensure_ascii=False, sort_keys=True),
        "solver_dimension_inference_from_coordinate_values": False,
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "coordinate_frame_source": "PartVTK Pos.x/Pos.y/Pos.z columns and generated GenCase XML x/y/z axes",
        "coordinate_frame_inference_from_coordinate_values": False,
        "units_json": json.dumps(DATASET_UNITS, ensure_ascii=False, sort_keys=True),
        "geometry_sha256": provenance["condition_bindings"]["geometry_sha256"],
        "geometry_hash_scope": "owner metadata physical geometry and geometry_family_id; excludes resolution dp and particle mesh",
        "geometry_binding_json": json.dumps(provenance["condition_bindings"]["geometry"], ensure_ascii=False, sort_keys=True),
        "geometry_reference": provenance["definition_xml_path"],
        "geometry_reference_sha256": source_hashes["definition_xml"],
        "geometry_family_id": owner.get("geometry_family_id") or "",
        "source_provenance_kind": provenance.get("source_provenance_kind", ""),
        "physical_case_id": owner.get("physical_case_id") or "",
        "lineage_group_id": owner.get("lineage_group_id") or "",
        "paired_background_id": owner.get("paired_background_id") or "",
        "view_id": owner.get("view_id") or "",
        "geometry_semantics_json": json.dumps(provenance["geometry"], ensure_ascii=False, sort_keys=True),
        "control_reference": provenance["owner_metadata_path"],
        "control_reference_sha256": source_hashes["owner_metadata"],
        "control_sha256": provenance["condition_bindings"]["control_sha256"],
        "control_hash_scope": "owner solver parameters, parameter values, event window, physical initial state, and generated XML motion/execution declarations",
        "control_binding_json": json.dumps(provenance["condition_bindings"]["control"], ensure_ascii=False, sort_keys=True),
        "physical_condition_sha256": provenance["condition_bindings"]["physical_condition_sha256"],
        "physical_condition_hash_scope": provenance["condition_bindings"]["physical_condition_hash_scope"],
        "physical_condition_binding_json": json.dumps(
            provenance["condition_bindings"]["physical_condition"], ensure_ascii=False, sort_keys=True),
        "numerical_recipe_sha256": provenance["condition_bindings"]["numerical_recipe_sha256"],
        "numerical_recipe_hash_scope": provenance["condition_bindings"]["numerical_recipe_hash_scope"],
        "numerical_recipe_binding_json": json.dumps(
            provenance["condition_bindings"]["numerical_recipe"], ensure_ascii=False, sort_keys=True),
        "condition_binding_missing_requirements": json.dumps(
            provenance["condition_bindings"]["missing_requirements"], ensure_ascii=False),
        "control_family_id": owner.get("control_family_id") or "",
        "control_semantics_json": json.dumps(provenance["control"], ensure_ascii=False, sort_keys=True),
        "motion_control_reference": provenance["generated_xml_path"],
        "motion_control_reference_sha256": source_hashes["generated_xml"],
        "motion_control_copied_path": provenance["motion_control"].get("copied_control_path") or "",
        "motion_control_copied_sha256": provenance["motion_control"].get("copied_control_sha256") or "",
        "motion_control_semantics_json": json.dumps(provenance["motion_control"], ensure_ascii=False, sort_keys=True),
        "boundary_semantics_json": json.dumps(provenance["boundary"], ensure_ascii=False, sort_keys=True),
        "population_json": json.dumps(provenance.get("population", {}), ensure_ascii=False, sort_keys=True),
        "lifecycle_semantics": provenance["boundary"].get("lifecycle_semantics", ""),
        "native_exclusion_classification": provenance["boundary"].get("native_exclusion_classification", ""),
        "source_solver_receipt_sha256": source_hashes["solver_receipt"],
        "source_gencase_receipt_sha256": source_hashes["gencase_receipt"],
        "source_raw_data_tree_sha256": provenance["raw_manifest"]["tree_sha256"],
        "source_raw_frame_count": int(provenance["raw_manifest"]["frame_count"]),
        "source_partvtk_binary_sha256": partvtk["sha256"],
        "partvtk_command_json": json.dumps(partvtk["command"], ensure_ascii=False),
        "csv_tree_sha256": csv_manifest["tree_sha256"],
        "csv_frame_count": int(csv_manifest["file_count"]),
        "time_source": "solver RunPARTs.csv TimeStep [s] (PartVTK CSV time labels are rounded)",
        "time_precision_preserved": True,
        "source_run_time_count": len(run_times),
        "source_run_time_start_s": float(run_times[0]),
        "source_run_time_end_s": float(run_times[-1]),
        "conversion_complete": True,
        "q_n_status": "not_assessed",
        "scientific_acceptance": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    with h5py.File(path, "r+") as handle:
        # PartVTK's CSV header rounds TimeStep to a short display value.  The
        # solver's per-frame RunPARTs.csv is the authoritative full-precision
        # time source, while all particle fields still come from PartVTK.
        if handle["time"].shape != (len(run_times),):
            raise ConversionError("converted time axis does not match solver RunPARTs.csv frame count")
        handle["time"][:] = np.asarray(run_times, dtype=np.float64)
        for key, value in root_attrs.items():
            handle.attrs[key] = value
        for name, unit in DATASET_UNITS.items():
            if name in handle:
                handle[name].attrs["units"] = unit
                handle[name].attrs["unit_source"] = "PartVTK column label" if name in {"time", "position", "velocity", "density", "mass", "pressure"} else "DS-DATA-02 identity/flag semantics"
        handle["position"].attrs["coordinate_frame"] = root_attrs["coordinate_frame"]
        handle["position"].attrs["coordinate_frame_source"] = root_attrs["coordinate_frame_source"]


def _verify_output(path: Path, provenance: Mapping[str, Any], run_times: list[float], expected_frames: int,
                   expected_particles: int, expected_fluid: int) -> dict[str, Any]:
    with h5py.File(path, "r") as handle:
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk"}
        missing = sorted(required - set(handle.keys()))
        if missing:
            raise ConversionError(f"converted HDF5 is missing datasets: {missing}")
        shapes = {name: list(handle[name].shape) for name in sorted(required)}
        if handle["time"].shape != (expected_frames,):
            raise ConversionError(f"converted frame count differs from BI4 count: {handle['time'].shape}")
        if handle["particle_id"].shape != (expected_particles,) or handle["particle_zone"].shape != (expected_particles,):
            raise ConversionError("converted particle identity axis differs from GenCase total particle count")
        expected_shapes = {
            "valid": (expected_frames, expected_particles), "type": (expected_frames, expected_particles),
            "position": (expected_frames, expected_particles, 3), "velocity": (expected_frames, expected_particles, 3),
            "density": (expected_frames, expected_particles), "mass": (expected_frames, expected_particles),
            "pressure": (expected_frames, expected_particles), "mk": (expected_frames, expected_particles),
        }
        for name, shape in expected_shapes.items():
            if handle[name].shape != shape:
                raise ConversionError(f"converted dataset {name} has shape {handle[name].shape}, expected {shape}")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        if len(run_times) != expected_frames or not np.allclose(times, run_times, rtol=0.0, atol=2e-6):
            raise ConversionError("converted times do not match solver RunPARTs.csv TimeStep values")
        valid_raw = np.asarray(handle["valid"][:])
        valid = np.asarray(valid_raw, dtype=bool)
        valid_binary = bool(valid_raw.dtype.kind in "?biuf" and
                            np.isfinite(valid_raw).all() and
                            np.all((valid_raw == 0) | (valid_raw == 1)))
        if not valid_binary:
            raise ConversionError("converted valid matrix is not binary and finite")
        type_values = np.asarray(handle["type"][:])
        initial_fluid = int(np.count_nonzero(type_values[0] == 3))
        if initial_fluid != expected_fluid:
            raise ConversionError(f"initial fluid count {initial_fluid} differs from GenCase receipt {expected_fluid}")
        mass = np.asarray(handle["mass"][:], dtype=np.float64)
        active_mass_finite = bool(np.isfinite(mass[valid]).all())
        active_mass_positive = bool(np.all(mass[valid] > 0))
        if not active_mass_finite or not active_mass_positive:
            raise ConversionError("converted active mass is not finite and positive")
        initial_active = valid[0]
        final_active = valid[-1]
        missing_any = np.any(initial_active[None, :] & ~valid, axis=0)
        introduced = np.any(~initial_active[None, :] & valid, axis=0)
        return {
            "required_datasets": sorted(required),
            "shapes": shapes,
            "frames": int(expected_frames),
            "particles": int(expected_particles),
            "valid_complete": bool(valid.all()),
            "valid_binary": valid_binary,
            "active_count_by_frame": [int(row.sum()) for row in valid],
            "initial_active_count": int(initial_active.sum()),
            "final_active_count": int(final_active.sum()),
            "initial_missing_at_final_count": int(np.count_nonzero(initial_active & ~final_active)),
            "missing_at_any_later_frame_count": int(missing_any.sum()),
            "introduced_after_initial_count": int(introduced.sum()),
            "initial_fluid_type3": initial_fluid,
            "expected_fluid_type3": int(expected_fluid),
            "mass_dataset_complete": int(mass.size) == expected_frames * expected_particles,
            "mass_finite_active": active_mass_finite,
            "mass_positive_active": active_mass_positive,
            "mass_initial_total_kg": float(mass[0].sum()),
            "mass_final_total_kg": float(mass[-1].sum()),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "run_time_start_s": float(run_times[0]),
            "run_time_end_s": float(run_times[-1]),
            "typed_identity_rows": int(len(handle["particle_id"])),
            "typed_identity_key": "(Zone,Idp)",
        }


def _resource_snapshot() -> dict[str, Any]:
    def one(which: int) -> dict[str, Any]:
        usage = resource.getrusage(which)
        return {
            "user_cpu_seconds": float(usage.ru_utime),
            "system_cpu_seconds": float(usage.ru_stime),
            "max_rss_kib": int(usage.ru_maxrss),
            "minor_page_faults": int(usage.ru_minflt),
            "major_page_faults": int(usage.ru_majflt),
            "in_block": int(usage.ru_inblock),
            "out_block": int(usage.ru_oublock),
            "voluntary_context_switches": int(usage.ru_nvcsw),
            "involuntary_context_switches": int(usage.ru_nivcsw),
        }
    return {"self": one(resource.RUSAGE_SELF), "children": one(resource.RUSAGE_CHILDREN)}


def convert_bi4(*, solver_receipt: Path, gencase_receipt: Path, owner_metadata: Path,
                output: Path, work_dir: Path, partvtk: Path = PARTVTK_DEFAULT,
                partvtk_threads: int = 4, report_path: Path | None = None,
                csv_root: Path | None = None, keep_csv: bool = False) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    before = _resource_snapshot()
    if not isinstance(partvtk_threads, int) or not 1 <= partvtk_threads <= 4:
        raise ConversionError("partvtk_threads must be between 1 and 4")
    provenance = load_provenance(solver_receipt.resolve(), gencase_receipt.resolve(), owner_metadata.resolve())
    raw_before = _raw_manifest(Path(provenance["data_root"]))[1]
    frame_count = int(raw_before["frame_count"])
    gencase = provenance["gencase_receipt"]
    expected_particles = int(gencase.get("total_particles", 0))
    expected_fluid = int(gencase.get("fluid_particles", 0))
    if expected_particles <= 0 or expected_fluid <= 0:
        raise ConversionError("GenCase receipt lacks positive total/fluid particle counts")
    if output.exists():
        raise ConversionError(f"refusing to overwrite conversion output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = csv_root.resolve() if csv_root is not None else work_dir.resolve() / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    partvtk_result: dict[str, Any]
    if csv_root is None:
        partvtk_result = _run_partvtk(partvtk.resolve(), Path(provenance["data_root"]), csv_dir, frame_count, partvtk_threads)
    else:
        partvtk_result = {"path": str(partvtk.resolve()), "sha256": _sha256(partvtk.resolve()), "command": [], "returncode": 0, "stdout_log": None, "stdout_sha256": None}
    frames = _csv_frames(csv_dir, frame_count)
    csv_manifest = _csv_manifest(frames, csv_dir)
    run_times = _run_times(Path(provenance["run_parts_csv_path"]))
    if len(run_times) != frame_count:
        raise ConversionError(f"RunPARTs.csv has {len(run_times)} TimeStep rows, expected {frame_count}")
    record = {
        "id": provenance["case_id"], "family": provenance["family_id"],
        "mechanism": provenance.get("mechanism_id") or "unknown",
        "shifting": provenance["control"].get("solver_parameters", {}).get("Shifting", 0),
    }
    convert_streaming(record, frames, output, resume=False)
    _set_hdf5_metadata(output, provenance, partvtk_result, csv_manifest, run_times)
    rigid_body_state = _write_rigid_body_state(output, provenance, run_times)
    verification = _verify_output(output, provenance, run_times, frame_count, expected_particles, expected_fluid)
    audit_metadata = {
        "units": DATASET_UNITS,
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "geometry": provenance["geometry"],
        "control": provenance["control"],
        "boundary_mode": provenance["boundary"].get("boundary_mode"),
        "boundary": provenance["boundary"],
        "solver_dimension": provenance["dimension_evidence"]["solver_dimension"],
        "rigid_body_state": rigid_body_state,
    }
    audit = audit_hdf5(output, solver_log=Path(provenance["run_out_path"]), metadata=audit_metadata, particle_chunk=65536)
    raw_after = _raw_manifest(Path(provenance["data_root"]))[1]
    if raw_after["tree_sha256"] != raw_before["tree_sha256"]:
        raise ConversionError("raw solver BI4 tree changed during conversion")
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "conversion_status": "completed",
        "converted_at_utc": started.isoformat(),
        "case_id": provenance["case_id"],
        "family_id": provenance["family_id"],
        "resolution": provenance.get("resolution"),
        "output_hdf5": str(output.resolve()),
        "output_hdf5_bytes": output.stat().st_size,
        "output_hdf5_sha256": _sha256(output),
        "source_provenance": provenance,
        "partvtk": partvtk_result,
        "partvtk_csv_manifest": csv_manifest,
        "partvtk_csv_retained": bool(keep_csv),
        "rigid_body_state": rigid_body_state,
        "verification": verification,
        "q_i_audit": audit,
        "q_n_status": "not_assessed",
        "scientific_acceptance": "not_assessed",
        "production_eligibility": "not_evaluated",
        "raw_source_unchanged": True,
        "raw_source_tree_sha256_before": raw_before["tree_sha256"],
        "raw_source_tree_sha256_after": raw_after["tree_sha256"],
    }
    after = _resource_snapshot()
    report["resource_usage"] = {"before": before, "after": after}
    if not keep_csv and csv_root is None:
        shutil.rmtree(csv_dir, ignore_errors=True)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(_json_value(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _json_value(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--partvtk", type=Path, default=PARTVTK_DEFAULT)
    parser.add_argument("--partvtk-threads", type=int, default=4)
    parser.add_argument("--csv-root", type=Path, help="Use existing PartVTK CSV frames; tests only, no PartVTK invocation")
    parser.add_argument("--keep-csv", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = convert_bi4(
            solver_receipt=args.solver_receipt,
            gencase_receipt=args.gencase_receipt,
            owner_metadata=args.owner_metadata,
            output=args.output,
            work_dir=args.work_dir,
            partvtk=args.partvtk,
            partvtk_threads=args.partvtk_threads,
            report_path=args.report,
            csv_root=args.csv_root,
            keep_csv=args.keep_csv,
        )
    except (ConversionError, OSError, ValueError, RuntimeError, ET.ParseError) as error:
        print(json.dumps({"schema": SCHEMA, "conversion_status": "failed", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    if args.report is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
