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
    owner = _load_json(owner_metadata_path, "F1 owner metadata")
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed":
        raise ConversionError("solver receipt is not a completed shared-runner receipt")
    if gencase.get("schema") != "ds02.execution-receipt.v1" or gencase.get("status") != "completed":
        raise ConversionError("GenCase receipt is not a completed shared-runner receipt")
    if solver.get("request", {}).get("kind") != "qualification":
        raise ConversionError("source solver receipt is not a qualification attempt")
    case_id = str(solver.get("request", {}).get("case_id", ""))
    if not CASE_ID_RE.fullmatch(case_id):
        raise ConversionError(f"invalid case id in solver receipt: {case_id!r}")
    raw_solver_root = solver.get("output_root")
    if not isinstance(raw_solver_root, str) or not raw_solver_root:
        raise ConversionError("solver receipt has no output_root directory")
    solver_root = Path(raw_solver_root).expanduser().resolve()
    if not solver_root.is_dir():
        raise ConversionError(f"solver output root is missing: {solver_root}")
    solver_dir = solver_root / "solver"
    run_out = _existing_path(solver_dir / "Run.out", "solver Run.out")
    run_csv = _existing_path(solver_dir / "Run.csv", "solver Run.csv")
    data_root = solver_dir / "data"
    solver_inputs = solver.get("request", {}).get("input_files", [])
    listed_generated_xml = next((Path(str(value)).expanduser().resolve() for value in solver_inputs
                                 if Path(str(value)).suffix.lower() == ".xml"), None)
    generated_xml = _existing_path(listed_generated_xml, "generated case XML") if listed_generated_xml else None
    if generated_xml is None:
        raise ConversionError("solver receipt did not list generated case XML")
    gencase_receipt_from_solver = next((Path(str(value)).expanduser().resolve() for value in solver_inputs
                                       if Path(str(value)).name == "execution-receipt.json"), None)
    if gencase_receipt_from_solver is not None and gencase_receipt_from_solver != gencase_receipt_path.resolve():
        raise ConversionError("explicit GenCase receipt differs from the solver receipt binding")
    definition_xml = _receipt_input(gencase, lambda path: path.name.endswith("_Def.xml"), "GenCase definition XML")
    owner_from_inputs = _receipt_input(gencase, lambda path: path.name.endswith(".metadata.json"), "F1 owner metadata")
    if owner_from_inputs != owner_metadata_path.resolve():
        raise ConversionError("explicit F1 owner metadata differs from the GenCase receipt binding")
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
    geometry = owner.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ConversionError("owner metadata has no structured geometry")
    solver_request = solver.get("request", {})
    gencase_request = gencase.get("request", {})
    source_inputs = _source_inputs(
        solver, gencase, owner_metadata_path.resolve(), generated_xml, definition_xml,
        solver_receipt_path.resolve(), gencase_receipt_path.resolve(),
    )
    return {
        "case_id": case_id,
        "family_id": str(owner.get("family_id", solver_request.get("family_id", "F1"))),
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
        "data_root": str(data_root),
        "raw_manifest": raw,
        "dimension_evidence": dimension,
        "geometry": _json_value(geometry),
        "control": {
            "control_family_id": owner.get("control_family_id"),
            "recipe_id": owner.get("recipe_id"),
            "solver_parameters": _json_value(owner.get("solver_parameters", {})),
            "generated_xml_execution_parameters": parameters,
        },
        "motion_control": {
            "source": str(generated_xml),
            "sha256": _sha256(generated_xml),
            "element_present": motion is not None,
            "element_empty": motion is not None and len(motion) == 0 and not motion.attrib,
            "semantics": "empty motion element in generated case XML" if motion is not None and len(motion) == 0 and not motion.attrib else "declared by generated case XML",
        },
        "boundary": {
            "source_mother_boundary": owner.get("source_mother", {}).get("boundary"),
            "open_top": owner.get("geometry", {}).get("open_top"),
            "lifecycle_semantics": "not declared by source metadata",
        },
        "source_input_hashes": source_inputs,
        "source_receipt_sha256": {
            "solver_receipt": _sha256(solver_receipt_path),
            "gencase_receipt": _sha256(gencase_receipt_path),
            "owner_metadata": _sha256(owner_metadata_path),
            "generated_xml": _sha256(generated_xml),
            "definition_xml": _sha256(definition_xml),
            "solver_run_out": _sha256(run_out),
            "solver_run_csv": _sha256(run_csv),
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
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{partvtk.parent}:{env.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=LAB_ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace", check=False)
    log_path = csv_root.parent / "partvtk.stdout.log"
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


def _run_times(run_csv: Path) -> list[float]:
    with run_csv.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        values = []
        for row in reader:
            value = row.get("PhysicalTime")
            if value not in (None, ""):
                values.append(float(value.replace(",", "")))
    if not values:
        raise ConversionError(f"Run.csv has no PhysicalTime values: {run_csv}")
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
        "geometry_reference": provenance["definition_xml_path"],
        "geometry_reference_sha256": source_hashes["definition_xml"],
        "geometry_family_id": owner.get("geometry_family_id") or "",
        "geometry_semantics_json": json.dumps(provenance["geometry"], ensure_ascii=False, sort_keys=True),
        "control_reference": provenance["owner_metadata_path"],
        "control_reference_sha256": source_hashes["owner_metadata"],
        "control_family_id": owner.get("control_family_id") or "",
        "control_semantics_json": json.dumps(provenance["control"], ensure_ascii=False, sort_keys=True),
        "motion_control_reference": provenance["generated_xml_path"],
        "motion_control_reference_sha256": source_hashes["generated_xml"],
        "motion_control_semantics_json": json.dumps(provenance["motion_control"], ensure_ascii=False, sort_keys=True),
        "boundary_semantics_json": json.dumps(provenance["boundary"], ensure_ascii=False, sort_keys=True),
        "source_solver_receipt_sha256": source_hashes["solver_receipt"],
        "source_gencase_receipt_sha256": source_hashes["gencase_receipt"],
        "source_raw_data_tree_sha256": provenance["raw_manifest"]["tree_sha256"],
        "source_raw_frame_count": int(provenance["raw_manifest"]["frame_count"]),
        "source_partvtk_binary_sha256": partvtk["sha256"],
        "partvtk_command_json": json.dumps(partvtk["command"], ensure_ascii=False),
        "csv_tree_sha256": csv_manifest["tree_sha256"],
        "csv_frame_count": int(csv_manifest["file_count"]),
        "source_run_time_count": len(run_times),
        "source_run_time_start_s": float(run_times[0]),
        "source_run_time_end_s": float(run_times[-1]),
        "conversion_complete": True,
        "q_n_status": "not_assessed",
        "scientific_acceptance": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    with h5py.File(path, "r+") as handle:
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
            raise ConversionError("converted times do not match solver Run.csv PhysicalTime values")
        valid = np.asarray(handle["valid"][:], dtype=bool)
        complete = bool(valid.shape == (expected_frames, expected_particles) and valid.all())
        if not complete:
            raise ConversionError("converted valid matrix is not complete for every BI4 frame and particle")
        type_values = np.asarray(handle["type"][:])
        initial_fluid = int(np.count_nonzero(type_values[0] == 3))
        if initial_fluid != expected_fluid:
            raise ConversionError(f"initial fluid count {initial_fluid} differs from GenCase receipt {expected_fluid}")
        mass = np.asarray(handle["mass"][:], dtype=np.float64)
        active_mass_finite = bool(np.isfinite(mass[valid]).all())
        active_mass_positive = bool(np.all(mass[valid] > 0))
        if not active_mass_finite or not active_mass_positive:
            raise ConversionError("converted active mass is not finite and positive")
        return {
            "required_datasets": sorted(required),
            "shapes": shapes,
            "frames": int(expected_frames),
            "particles": int(expected_particles),
            "valid_complete": complete,
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
    run_times = _run_times(Path(provenance["run_csv_path"]))
    if len(run_times) != frame_count:
        raise ConversionError(f"Run.csv has {len(run_times)} physical-time rows, expected {frame_count}")
    record = {
        "id": provenance["case_id"], "family": provenance["family_id"],
        "mechanism": provenance.get("mechanism_id") or "unknown",
        "shifting": provenance["control"].get("solver_parameters", {}).get("Shifting", 0),
    }
    convert_streaming(record, frames, output, resume=False)
    _set_hdf5_metadata(output, provenance, partvtk_result, csv_manifest, run_times)
    verification = _verify_output(output, provenance, run_times, frame_count, expected_particles, expected_fluid)
    audit_metadata = {
        "units": DATASET_UNITS,
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "geometry": provenance["geometry"],
        "control": provenance["control"],
        "solver_dimension": provenance["dimension_evidence"]["solver_dimension"],
        # Lifecycle semantics remain intentionally absent: open top and DBC
        # are source facts, not a closed/open particle ledger declaration.
        "rigid_body_state": None,
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
