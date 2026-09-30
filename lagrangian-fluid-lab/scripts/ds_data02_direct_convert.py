#!/usr/bin/env python3
"""Stream a DualSPHysics BI4 particle stream into the DS-DATA-02 HDF5 schema.

This module deliberately has no dependency on the historical CSV converter.  It
uses the checked-in/upstream ``bi4_dump`` binary for one frame at a time and
keeps the initial ``(Zone, Idp)`` axis fixed.  Production invocations also run
official PartVTK on three complete frames and can compare the result to an
independent HDF5 artifact.

The converter is a data-engineering adapter.  Its report never grants Q-N or
production eligibility; those decisions need the campaign auditors and native
scientific evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import resource
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
HDF5_SCHEMA = "ds-data-02.hdf5-schema.v1"
FRAME_RE = re.compile(r"^Part_(\d{4,})\.bi4$")
TYPE_BY_TAG = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
REQUIRED_FIELDS = ("position", "velocity", "density", "mass", "pressure")
PARTVTK_TOLERANCES = {
    "position": 1.0e-6,
    "velocity": 1.0e-6,
    "density": 1.0e-3,
    "mass": 1.0e-7,
    "pressure": 5.0e-2,
}


class DirectConversionError(RuntimeError):
    """Raised when a source violates a closed, auditable conversion contract."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _resource_snapshot() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        usage = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(usage.ru_utime)
        result[f"{label}_system_seconds"] = float(usage.ru_stime)
        result[f"{label}_max_rss_kib"] = float(usage.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _parse_scalar(element: ET.Element) -> Any:
    value = element.get("v")
    if value is None:
        return None
    tag = element.tag.lower()
    if tag in {"bool", "boolean"}:
        return value.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long"}:
        try:
            return int(value)
        except ValueError:
            return value
    if tag in {"float", "double", "real"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _named_values(node: ET.Element | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {
        item.get("name"): _parse_scalar(item)
        for item in node
        if item.tag != "item" and item.get("name")
    }


def _as_int(mapping: Mapping[str, Any], key: str, *, default: int | None = None) -> int | None:
    value = mapping.get(key, default)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DirectConversionError(f"decoder field {key!r} is not integer: {value!r}") from exc


def _as_float(mapping: Mapping[str, Any], key: str, *, default: float | None = None) -> float | None:
    value = mapping.get(key, default)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DirectConversionError(f"decoder field {key!r} is not numeric: {value!r}") from exc


def raw_tree_manifest(data_root: Path) -> dict[str, Any]:
    """Hash all files in a BI4 data directory without mutating it."""
    if not data_root.is_dir():
        raise DirectConversionError(f"BI4 data root is not a directory: {data_root}")
    files = []
    for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
        relative = path.relative_to(data_root).as_posix()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    digest = canonical_hash(files)
    frame_indices = []
    for entry in files:
        match = FRAME_RE.match(Path(entry["path"]).name)
        if match and Path(entry["path"]).parent == Path("."):
            frame_indices.append(int(match.group(1)))
    if not frame_indices:
        raise DirectConversionError(f"no top-level Part_####.bi4 frames in {data_root}")
    if sorted(frame_indices) != list(range(len(frame_indices))):
        raise DirectConversionError(
            "BI4 frame indices must be contiguous from zero; "
            f"observed {frame_indices[:5]}...{frame_indices[-5:]}"
        )
    return {"root": str(data_root), "file_count": len(files), "files": files, "tree_sha256": digest}


def frame_paths(data_root: Path) -> list[Path]:
    paths = []
    for path in sorted(data_root.glob("Part_*.bi4")):
        if not path.is_file():
            continue
        match = FRAME_RE.match(path.name)
        if match:
            paths.append((int(match.group(1)), path))
    paths.sort()
    if [index for index, _ in paths] != list(range(len(paths))):
        raise DirectConversionError("frame paths are not contiguous from Part_0000.bi4")
    if len(paths) < 2:
        raise DirectConversionError("at least two BI4 frames are required for increasing-time evidence")
    return [path for _, path in paths]


def _find_particles_node(root: ET.Element) -> ET.Element:
    node = root.find(".//execution/particles") or root.find(".//particles")
    if node is None:
        raise DirectConversionError("generated XML has no execution/particles block")
    return node


def parse_particle_blocks(generated_xml: Path) -> dict[str, Any]:
    """Parse complete typed ranges from GenCase XML, preserving all blocks."""
    root = ET.parse(generated_xml).getroot()
    particles = _find_particles_node(root)
    total = particles.get("np")
    if total is None:
        raise DirectConversionError("particles.np is missing")
    total_n = int(total)
    blocks = []
    seen = np.zeros(total_n, dtype=bool)
    for child in particles:
        if child.tag == "_summary":
            continue
        if child.tag not in TYPE_BY_TAG:
            raise DirectConversionError(f"unsupported particle block in generated XML: <{child.tag}>")
        try:
            begin = int(child.attrib["begin"])
            count = int(child.attrib["count"])
            mk = int(child.attrib["mk"])
        except (KeyError, ValueError) as exc:
            raise DirectConversionError(f"typed particle block lacks integer begin/count/mk: {ET.tostring(child)}") from exc
        if begin < 0 or count <= 0 or begin + count > total_n:
            raise DirectConversionError(f"particle block out of range: {ET.tostring(child)}")
        if seen[begin : begin + count].any():
            raise DirectConversionError("overlapping particle blocks in generated XML")
        seen[begin : begin + count] = True
        blocks.append({"tag": child.tag, "type": TYPE_BY_TAG[child.tag], "mk": mk, "begin": begin, "count": count})
    if not blocks or not seen.all():
        missing = np.flatnonzero(~seen)
        raise DirectConversionError(f"typed particle ranges do not cover np={total_n}; first missing={missing[:5].tolist()}")
    blocks.sort(key=lambda block: block["begin"])
    return {"np": total_n, "blocks": blocks, "xml_sha256": sha256_file(generated_xml)}


def _reject_dynamic_contract(generated_xml: Path, first_meta: Mapping[str, Any]) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    tags = {"inout", "inoutzone", "periodic", "adaptive", "adaptative", "birth", "inlet", "outlet"}
    found = []
    for element in root.iter():
        normalized = element.tag.lower().split("}")[-1]
        if normalized in tags:
            found.append(normalized)
    if found:
        raise DirectConversionError(f"open/birth/adaptive/inlet/outlet/periodic sources are unsupported: {sorted(set(found))}")
    for key, expected in (("Npiece", 1), ("Piece", 0), ("NpDynamic", 0), ("ReuseIds", 0), ("PeriMode", 0)):
        value = _as_int(first_meta, key)
        if value is None:
            raise DirectConversionError(f"decoder lacks closed-stream field {key}")
        if value != expected:
            raise DirectConversionError(f"unsupported multi-piece/dynamic BI4 field {key}={value}; expected {expected}")
    return {"open_birth_adaptive": "rejected", "dynamic_metadata": {key: _as_int(first_meta, key) for key in ("Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode")}}


@dataclass
class DecodedFrame:
    ids: np.ndarray
    position: np.ndarray
    velocity: np.ndarray
    density: np.ndarray
    time: float
    metadata: dict[str, Any]
    info: dict[str, Any]
    decoder_xml_sha256: str


def decode_frame(frame_path: Path, decoder: Path, scratch_root: Path, index: int) -> DecodedFrame:
    """Invoke the upstream binary decoder for exactly one frame."""
    prefix = scratch_root / f"frame_{index:04d}"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(decoder), str(frame_path), str(prefix)]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=180)
    except subprocess.CalledProcessError as exc:
        raise DirectConversionError(f"BI4 decoder failed for {frame_path}: {exc.stderr[-1000:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DirectConversionError(f"BI4 decoder timed out for {frame_path}") from exc
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.exists():
        raise DirectConversionError(f"decoder did not produce {xml_path}")
    root = ET.parse(xml_path).getroot()
    outer = root.find("item")
    node = root.find(".//item/item")
    metadata = _named_values(outer)
    info = _named_values(node)
    if node is None or node.get("name") is None:
        raise DirectConversionError(f"decoder XML has no particle item: {xml_path}")
    data_root = prefix / node.get("name")
    ids_path = data_root / "Idp.bin"
    if not ids_path.exists():
        raise DirectConversionError(f"decoder output has no Idp.bin: {data_root}")
    ids = np.fromfile(ids_path, dtype=np.uint32)
    order = np.argsort(ids, kind="mergesort")
    if ids.size == 0 or np.unique(ids).size != ids.size:
        raise DirectConversionError(f"duplicate or empty Idp axis in {frame_path}")
    n = int(ids.size)
    pos_path = data_root / "Pos.bin"
    pos_dtype = np.float32
    if not pos_path.exists():
        pos_path = data_root / "Posd.bin"
        pos_dtype = np.float64
    required = {"Pos": pos_path, "Vel": data_root / "Vel.bin", "Rhop": data_root / "Rhop.bin"}
    if any(not path.exists() for path in required.values()):
        raise DirectConversionError(f"decoder output lacks required arrays in {data_root}")
    position = np.fromfile(pos_path, dtype=pos_dtype).reshape(n, 3)[order].astype(np.float32, copy=False)
    velocity = np.fromfile(required["Vel"], dtype=np.float32).reshape(n, 3)[order]
    density = np.fromfile(required["Rhop"], dtype=np.float32)[order]
    raw_time = info.get("TimeStep")
    if raw_time is None:
        raise DirectConversionError(f"decoder frame lacks TimeStep: {frame_path}")
    try:
        frame_time = float(raw_time)
    except (TypeError, ValueError) as exc:
        raise DirectConversionError(f"invalid TimeStep {raw_time!r}") from exc
    if not math.isfinite(frame_time):
        raise DirectConversionError(f"non-finite TimeStep in {frame_path}")
    return DecodedFrame(ids[order], position, velocity, density, frame_time, metadata, info, sha256_file(xml_path))


def _dimension_evidence(generated_xml: Path, solver_log: Path | None, solver_receipt: Path | None) -> dict[str, Any]:
    xml_root = ET.parse(generated_xml).getroot()
    data2d = xml_root.find(".//data2d")
    if data2d is None or data2d.get("value") is None:
        raise DirectConversionError("generated XML lacks explicit constants/data2d")
    xml_dimension = 2 if data2d.get("value", "").lower() in {"1", "true", "yes"} else 3
    paths = []
    if solver_log:
        paths.append(solver_log)
    if solver_receipt:
        try:
            receipt = json.loads(solver_receipt.read_text())
            output_root = receipt.get("output_root")
            if output_root:
                candidate = Path(output_root) / "Run.out"
                if candidate.exists():
                    paths.append(candidate)
        except (OSError, json.JSONDecodeError):
            pass
    banner_dimensions = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        if re.search(r"\*\*\s*3D-Simulation parameters", text, re.IGNORECASE):
            banner_dimensions.append(3)
        if re.search(r"\*\*\s*2D-Simulation parameters", text, re.IGNORECASE):
            banner_dimensions.append(2)
    if not banner_dimensions:
        raise DirectConversionError("actual solver Run.out has no unambiguous 2D/3D banner")
    if len(set(banner_dimensions)) != 1 or banner_dimensions[0] != xml_dimension:
        raise DirectConversionError(f"dimension evidence conflicts: XML={xml_dimension}, Run.out={banner_dimensions}")
    return {"solver_dimension": xml_dimension, "xml_data2d": data2d.get("value"), "run_out_dimensions": banner_dimensions, "source_paths": [str(path) for path in paths if path.exists()]}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DirectConversionError(f"cannot load JSON provenance {path}") from exc
    if not isinstance(value, dict):
        raise DirectConversionError(f"provenance JSON is not an object: {path}")
    return value


def _verify_receipt(path: Path, label: str) -> dict[str, Any]:
    value = _load_json(path)
    if value.get("status") not in {"completed", "success"}:
        raise DirectConversionError(f"{label} receipt is not completed: {path}")
    return value


def _physical_condition_scope(owner: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("family_id", "physical_case_id", "lineage_group_id", "paired_background_id", "mechanism_id", "geometry_family_id", "geometry", "control_family_id", "recipe_id", "event_window", "view_id")
    return {key: owner[key] for key in keys if key in owner}


def _numerical_scope(owner: Mapping[str, Any], generated_xml: Path, first: DecodedFrame, solver_receipt: Mapping[str, Any]) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    params = []
    for element in root.findall(".//execution/parameters/parameter"):
        params.append({"key": element.get("key"), "value": element.get("value")})
    constants = {key: first.metadata.get(key) for key in ("Dp", "B", "Rhop0", "Gamma", "MassBound", "MassFluid")}
    return {"resolution": owner.get("resolution"), "solver_parameters": owner.get("solver_parameters", {}), "generated_xml_execution_parameters": params, "decoder_header_constants": constants, "solver_command": solver_receipt.get("request", {}).get("command", []), "time_source": "BI4 decoder TimeStep"}


def _xml_subtree_hash(generated_xml: Path, xpath: str) -> str:
    root = ET.parse(generated_xml).getroot()
    element = root.find(xpath)
    if element is None:
        raise DirectConversionError(f"generated XML lacks provenance subtree {xpath}")
    return hashlib.sha256(ET.tostring(element, encoding="utf-8")).hexdigest()


def _assign_types(ids: np.ndarray, blocks: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    types = np.full(ids.size, -1, dtype=np.int8)
    mks = np.full(ids.size, -1, dtype=np.int16)
    covered = np.zeros(ids.size, dtype=bool)
    for block in blocks["blocks"]:
        selected = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
        if np.any(selected):
            if np.any(covered[selected]):
                raise DirectConversionError("Idp maps to overlapping typed ranges")
            types[selected] = block["type"]
            mks[selected] = block["mk"]
            covered[selected] = True
    if not covered.all():
        raise DirectConversionError(f"typed ranges do not identify Idp values: {ids[~covered][:5].tolist()}")
    return types, mks


def _mass_for_types(types: np.ndarray, metadata: Mapping[str, Any]) -> np.ndarray:
    bound = _as_float(metadata, "MassBound")
    fluid = _as_float(metadata, "MassFluid")
    if bound is None or fluid is None or bound <= 0 or fluid <= 0:
        raise DirectConversionError("decoder lacks finite positive MassBound/MassFluid")
    mass = np.where(types == 3, fluid, bound).astype(np.float32)
    if np.any(~np.isfinite(mass)) or np.any(mass <= 0):
        raise DirectConversionError("initial typed mass is not finite and positive")
    return mass


def eos_pressure(density: np.ndarray, metadata: Mapping[str, Any]) -> np.ndarray:
    b = _as_float(metadata, "B")
    rhop0 = _as_float(metadata, "Rhop0")
    gamma = _as_float(metadata, "Gamma")
    if b is None or rhop0 is None or gamma is None or b <= 0 or rhop0 <= 0 or gamma <= 0:
        raise DirectConversionError("decoder lacks valid B/Rhop0/Gamma for EOS pressure")
    result = b * ((density.astype(np.float64) / rhop0) ** gamma - 1.0)
    return result.astype(np.float32)


def _check_frame_constants(first: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    for key in ("Dp", "B", "Rhop0", "Gamma", "Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode"):
        a, b = first.get(key), current.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1.0e-6):
                raise DirectConversionError(f"frame header constant changed: {key}={a!r}->{b!r}")
        elif a != b:
            raise DirectConversionError(f"frame header field changed: {key}={a!r}->{b!r}")


def _ensure_finite_active(frame: DecodedFrame, mass: np.ndarray, pressure: np.ndarray) -> None:
    for name, array in (("position", frame.position), ("velocity", frame.velocity), ("density", frame.density), ("mass", mass), ("pressure", pressure)):
        if not np.isfinite(array).all():
            raise DirectConversionError(f"non-finite active {name} at time {frame.time}")
    if np.any(frame.density <= 0) or np.any(mass <= 0):
        raise DirectConversionError(f"non-positive active density/mass at time {frame.time}")


def _create_h5(path: Path, frames: int, particles: int) -> h5py.File:
    path.parent.mkdir(parents=True, exist_ok=True)
    h5 = h5py.File(path, "w")
    h5.attrs["schema"] = HDF5_SCHEMA
    h5.attrs["conversion_complete"] = False
    h5.attrs["identity_key"] = "(Zone,Idp)"
    h5.attrs["lifecycle_semantics"] = "fixed initial typed identity axis; introduced IDs and adaptive/open birth are rejected"
    h5.attrs["units_json"] = _canonical_json({"time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa"})
    h5.create_dataset("time", shape=(frames,), dtype="f8")
    h5.create_dataset("particle_id", shape=(particles,), dtype="u4")
    h5.create_dataset("particle_zone", shape=(particles,), dtype="i2")
    chunks_1 = (1, min(particles, 65536))
    chunks_3 = (1, min(particles, 65536), 3)
    h5.create_dataset("valid", shape=(frames, particles), dtype="bool", chunks=chunks_1, compression="lzf", fillvalue=False)
    h5.create_dataset("position", shape=(frames, particles, 3), dtype="f4", chunks=chunks_3, compression="lzf", fillvalue=np.nan)
    h5.create_dataset("velocity", shape=(frames, particles, 3), dtype="f4", chunks=chunks_3, compression="lzf", fillvalue=np.nan)
    for name in ("density", "mass", "pressure"):
        h5.create_dataset(name, shape=(frames, particles), dtype="f4", chunks=chunks_1, compression="lzf", fillvalue=np.nan)
    h5.create_dataset("type", shape=(frames, particles), dtype="i1", chunks=chunks_1, compression="lzf", fillvalue=-1)
    h5.create_dataset("mk", shape=(frames, particles), dtype="i2", chunks=chunks_1, compression="lzf", fillvalue=-1)
    h5.create_dataset("initial_type", shape=(particles,), dtype="i1")
    h5.create_dataset("initial_mk", shape=(particles,), dtype="i2")
    h5.create_dataset("initial_mass", shape=(particles,), dtype="f4")
    return h5


def _write_frame(h5: h5py.File, index: int, frame: DecodedFrame, base_ids: np.ndarray, base_type: np.ndarray, base_mk: np.ndarray, mass_constants: np.ndarray) -> dict[str, Any]:
    positions = np.full((base_ids.size, 3), np.nan, dtype=np.float32)
    velocities = np.full((base_ids.size, 3), np.nan, dtype=np.float32)
    density = np.full(base_ids.size, np.nan, dtype=np.float32)
    mass = np.full(base_ids.size, np.nan, dtype=np.float32)
    pressure = np.full(base_ids.size, np.nan, dtype=np.float32)
    types = np.full(base_ids.size, -1, dtype=np.int8)
    mks = np.full(base_ids.size, -1, dtype=np.int16)
    valid = np.zeros(base_ids.size, dtype=bool)
    indices = np.searchsorted(base_ids, frame.ids)
    if np.any(indices >= base_ids.size) or not np.array_equal(base_ids[indices], frame.ids):
        raise DirectConversionError(f"introduced or unknown Idp values at frame {index}")
    valid[indices] = True
    if np.unique(indices).size != indices.size:
        raise DirectConversionError(f"duplicate identity at frame {index}")
    frame_mass = mass_constants.copy()
    positions[indices] = frame.position
    velocities[indices] = frame.velocity
    density[indices] = frame.density
    mass[indices] = frame_mass[indices]
    pressure[indices] = eos_pressure(frame.density, frame.metadata)
    types[indices] = base_type[indices]
    mks[indices] = base_mk[indices]
    active_mass = frame_mass[indices]
    active_pressure = pressure[indices]
    _ensure_finite_active(frame, active_mass, active_pressure)
    h5["time"][index] = frame.time
    h5["valid"][index] = valid
    h5["position"][index] = positions
    h5["velocity"][index] = velocities
    h5["density"][index] = density
    h5["mass"][index] = mass
    h5["pressure"][index] = pressure
    h5["type"][index] = types
    h5["mk"][index] = mks
    return {"frame": index, "time": frame.time, "active_particles": int(valid.sum()), "missing_particles": int((~valid).sum()), "type_counts": {str(int(kind)): int(np.sum(base_type[indices] == kind)) for kind in range(4)}}


def _csv_path_from_prefix(prefix: Path, frame: int) -> Path:
    candidate = prefix.parent / f"{prefix.name}_{frame:04d}.csv"
    if candidate.exists():
        return candidate
    candidates = sorted(prefix.parent.glob(f"{prefix.name}_*.csv"))
    if not candidates:
        raise DirectConversionError(f"PartVTK did not produce CSV for frame {frame}: {prefix}")
    return candidates[0]


def _run_partvtk_frame(partvtk: Path, data_root: Path, frame: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / f"frame_{frame:04d}"
    command = [str(partvtk), "-dirdata", str(data_root), f"-first:{frame}", f"-last:{frame}", "-threads:4", "-savecsv", str(prefix), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1"]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise DirectConversionError(f"official PartVTK failed for frame {frame}: {exc}") from exc
    return _csv_path_from_prefix(prefix, frame)


def compare_partvtk_frame(h5_path: Path, csv_path: Path, frame: int) -> dict[str, Any]:
    with h5py.File(h5_path, "r") as h5, csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        first = next(reader)
        summary = next(reader)
        next(reader, None)
        header = next(reader)
        header = [field.strip() for field in header]
        required = {"Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Mass [kg]", "Press [Pa]", "Type", "Mk"}
        missing = required.difference(header)
        if missing:
            raise DirectConversionError(f"PartVTK CSV lacks fields {sorted(missing)}")
        index = {name: header.index(name) for name in required}
        ids = h5["particle_id"][...]
        zones = h5["particle_zone"][...]
        valid = h5["valid"][frame][...]
        # A single frame is bounded (~tens of MiB for the largest expected
        # cases); loading it once avoids 100k+ compressed HDF5 point reads.
        expected_arrays = {name: h5[name][frame][...] for name in (*REQUIRED_FIELDS, "type", "mk")}
        expected_indices = np.flatnonzero(valid)
        by_identity = {(int(zone), int(pid)): int(i) for i, (zone, pid) in enumerate(zip(zones, ids))}
        seen = set()
        max_error = {name: 0.0 for name in PARTVTK_TOLERANCES}
        exact = True
        rows = 0
        counts: dict[str, int] = {}
        mass_by_type: dict[str, float] = {}
        fields = {
            "position": ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]"),
            "velocity": ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"),
            "density": ("Rhop [kg/m^3]",),
            "mass": ("Mass [kg]",),
            "pressure": ("Press [Pa]",),
        }
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            rows += 1
            identity = (int(row[index["Zone"]]), int(row[index["Idp"]]))
            if identity not in by_identity or identity in seen:
                raise DirectConversionError(f"PartVTK identity is unknown/duplicated at frame {frame}: {identity}")
            seen.add(identity)
            particle = by_identity[identity]
            if not valid[particle]:
                raise DirectConversionError(f"PartVTK emitted invalid/missing identity at frame {frame}: {identity}")
            if int(row[index["Type"]]) != int(expected_arrays["type"][particle]) or int(row[index["Mk"]]) != int(expected_arrays["mk"][particle]):
                exact = False
            kind = str(int(row[index["Type"]]))
            counts[kind] = counts.get(kind, 0) + 1
            mass_by_type[kind] = mass_by_type.get(kind, 0.0) + float(row[index["Mass [kg]"]])
            for name, columns in fields.items():
                values = np.array([float(row[index[column]]) for column in columns], dtype=np.float64)
                expected = np.asarray(expected_arrays[name][particle], dtype=np.float64)
                error = float(np.max(np.abs(values - expected)))
                max_error[name] = max(max_error[name], error)
        if rows != expected_indices.size or len(seen) != expected_indices.size:
            exact = False
        for name, tolerance in PARTVTK_TOLERANCES.items():
            if max_error[name] > tolerance:
                exact = False
        partvtk_time = float(summary[0]) if summary else float("nan")
        direct_time = float(h5["time"][frame])
        time_error = abs(partvtk_time - direct_time)
        # PartVTK prints decimal time with a short format; retain a bounded, explicit tolerance.
        time_passed = math.isfinite(time_error) and time_error <= 5.0e-5
        if not time_passed:
            exact = False
        return {"frame": frame, "csv": str(csv_path), "rows": rows, "expected_rows": int(expected_indices.size), "identity_type_mk_exact": bool(exact), "max_abs_error": max_error, "tolerances": PARTVTK_TOLERANCES, "partvtk_time": partvtk_time, "direct_time": direct_time, "time_abs_error": time_error, "time_tolerance": 5.0e-5, "passed": bool(exact), "type_counts": counts, "mass_by_type_kg": mass_by_type, "partvtk_summary": summary}


def compare_reference_hdf5(direct_path: Path, reference_path: Path, *, particle_chunk: int = 65536, pressure_tolerance: float = 5.0e-2) -> dict[str, Any]:
    names = ("time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk")
    with h5py.File(direct_path, "r") as direct, h5py.File(reference_path, "r") as reference:
        for name in names:
            if name not in direct or name not in reference:
                raise DirectConversionError(f"reference comparison lacks dataset {name}")
            if direct[name].shape != reference[name].shape:
                raise DirectConversionError(f"reference shape mismatch for {name}: {direct[name].shape} != {reference[name].shape}")
        equal = {name: True for name in names if name != "pressure"}
        pressure_max = 0.0
        pressure_nonfinite = False
        frames = direct["time"].shape[0]
        particles = direct["particle_id"].shape[0]
        for name in ("particle_id", "particle_zone"):
            equal[name] = bool(np.array_equal(direct[name][...], reference[name][...], equal_nan=True))
        for frame in range(frames):
            for start in range(0, particles, particle_chunk):
                stop = min(start + particle_chunk, particles)
                for name in ("valid", "position", "velocity", "density", "mass", "type", "mk"):
                    equal[name] = equal[name] and bool(np.array_equal(direct[name][frame, start:stop], reference[name][frame, start:stop], equal_nan=True))
                a = direct["pressure"][frame, start:stop].astype(np.float64)
                b = reference["pressure"][frame, start:stop].astype(np.float64)
                finite = np.isfinite(a) & np.isfinite(b)
                if np.any(finite):
                    pressure_max = max(pressure_max, float(np.max(np.abs(a[finite] - b[finite]))))
                if np.any(np.isfinite(a) != np.isfinite(b)):
                    pressure_nonfinite = True
            equal["time"] = bool(np.array_equal(direct["time"][...], reference["time"][...], equal_nan=True))
        pressure_passed = not pressure_nonfinite and pressure_max <= pressure_tolerance
        all_arrays_equal_except_pressure = all(equal.values())
        return {"reference": str(reference_path), "datasets": list(names), "exact_dataset_equality": equal, "all_nonpressure_arrays_equal": all_arrays_equal_except_pressure, "pressure_max_abs_error": pressure_max, "pressure_tolerance": pressure_tolerance, "pressure_passed": pressure_passed, "passed": bool(all_arrays_equal_except_pressure and pressure_passed)}


def _ensure_source_unchanged(data_root: Path, before: Mapping[str, Any]) -> dict[str, Any]:
    after = raw_tree_manifest(data_root)
    return {"before_tree_sha256": before["tree_sha256"], "after_tree_sha256": after["tree_sha256"], "unchanged": bool(before["tree_sha256"] == after["tree_sha256"] and before["files"] == after["files"]), "before_file_count": before["file_count"], "after_file_count": after["file_count"]}


def audit_conversion_contract(*, data_root: Path, generated_xml: Path, decoder: Path, solver_log: Path | None, solver_receipt: Path | None) -> dict[str, Any]:
    """Cheap preflight used by tests and callers that need no HDF5 output."""
    paths = frame_paths(data_root)
    first = decode_frame(paths[0], decoder, Path(tempfile.mkdtemp(prefix="ds02-direct-preflight-")), 0)
    blocks = parse_particle_blocks(generated_xml)
    dynamic = _reject_dynamic_contract(generated_xml, first.metadata)
    dimension = _dimension_evidence(generated_xml, solver_log, solver_receipt)
    types, mks = _assign_types(first.ids, blocks)
    mass = _mass_for_types(types, first.metadata)
    return {"frames": len(paths), "particles": int(first.ids.size), "blocks": blocks["blocks"], "observed_types": sorted(set(types.tolist())), "observed_mks": sorted(set(mks.tolist())), "initial_mass_min_kg": float(mass.min()), "initial_mass_max_kg": float(mass.max()), "dynamic_contract": dynamic, "dimension": dimension}


def convert_direct(*, data_root: Path, generated_xml: Path, output: Path, report_path: Path, decoder: Path, partvtk: Path | None = None, validation_dir: Path | None = None, solver_log: Path | None = None, solver_receipt: Path | None = None, gencase_receipt: Path | None = None, owner_metadata: Path | None = None, reference_hdf5: Path | None = None, run_partvtk: bool = True, keep_validation_csv: bool = False, particle_chunk: int = 65536) -> dict[str, Any]:
    started = time.monotonic()
    resource_before = _resource_snapshot()
    output = output.resolve()
    report_path = report_path.resolve()
    if output.exists() or output.with_suffix(output.suffix + ".partial").exists():
        raise DirectConversionError(f"refusing to overwrite existing direct conversion artifact: {output}")
    if not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise DirectConversionError(f"upstream decoder is not executable: {decoder}")
    if run_partvtk and (partvtk is None or not partvtk.is_file()):
        raise DirectConversionError("official PartVTK is required unless run_partvtk=False")
    if owner_metadata is None or solver_receipt is None or gencase_receipt is None:
        raise DirectConversionError("owner metadata, solver receipt, and GenCase receipt are required for provenance")
    owner = _load_json(owner_metadata)
    solver_receipt_value = _verify_receipt(solver_receipt, "solver")
    gencase_receipt_value = _verify_receipt(gencase_receipt, "GenCase")
    paths = frame_paths(data_root)
    before_manifest = raw_tree_manifest(data_root)
    blocks = parse_particle_blocks(generated_xml)
    scratch = Path(tempfile.mkdtemp(prefix="ds02-direct-bi4-"))
    partial = output.with_suffix(output.suffix + ".partial")
    h5: h5py.File | None = None
    validation = []
    frame_summary = []
    try:
        first = decode_frame(paths[0], decoder, scratch, 0)
        if _as_int(first.metadata, "CaseNp") not in {None, int(first.ids.size)}:
            raise DirectConversionError("decoder CaseNp does not match Idp count")
        dynamic_contract = _reject_dynamic_contract(generated_xml, first.metadata)
        dimension = _dimension_evidence(generated_xml, solver_log, solver_receipt)
        base_ids = first.ids.copy()
        base_type, base_mk = _assign_types(base_ids, blocks)
        initial_mass = _mass_for_types(base_type, first.metadata)
        physical_scope = _physical_condition_scope(owner)
        numerical_scope = _numerical_scope(owner, generated_xml, first, solver_receipt_value)
        geometry_sha256 = _xml_subtree_hash(generated_xml, ".//geometry")
        control_sha256 = canonical_hash(
            {
                "execution_parameters": numerical_scope["generated_xml_execution_parameters"],
                "motion_xml": ET.tostring(ET.parse(generated_xml).getroot().find(".//motion"), encoding="unicode") if ET.parse(generated_xml).getroot().find(".//motion") is not None else None,
            }
        )
        h5 = _create_h5(partial, len(paths), base_ids.size)
        h5["particle_id"][:] = base_ids
        h5["particle_zone"][:] = int(_as_int(first.metadata, "Piece", default=0))
        h5["initial_type"][:] = base_type
        h5["initial_mk"][:] = base_mk
        h5["initial_mass"][:] = initial_mass
        h5.attrs["solver_dimension"] = dimension["solver_dimension"]
        h5.attrs["coordinate_frame"] = "DualSPHysics case Cartesian coordinates (x,y,z)"
        h5.attrs["coordinate_frame_source"] = str(generated_xml)
        h5.attrs["pressure_semantics"] = "EOS pressure from native BI4 density and per-frame B/Rhop0/Gamma"
        h5.attrs["mass_semantics"] = "native header MassFluid for type=3; native header MassBound for types 0/1/2; PartVTK checked"
        h5.attrs["typed_identity_source"] = "GenCase execution/particles ranges plus decoder Idp; Zone=BI4 Piece"
        h5.attrs["physical_condition_sha256"] = canonical_hash(physical_scope)
        h5.attrs["numerical_parameters_sha256"] = canonical_hash(numerical_scope)
        h5.attrs["geometry_reference_sha256"] = geometry_sha256
        h5.attrs["control_reference_sha256"] = control_sha256
        h5.attrs["geometry_sha256"] = geometry_sha256
        h5.attrs["control_sha256"] = control_sha256
        h5.attrs["source_decoder_sha256"] = sha256_file(decoder)
        h5.attrs["source_raw_tree_sha256_before"] = before_manifest["tree_sha256"]
        h5.attrs["source_raw_tree_sha256_after"] = "pending"
        h5.attrs["source_tree_unchanged"] = False
        h5.attrs["q_i_status"] = "conversion_evidence_only; lifecycle and scientific qualification remain external"
        h5.attrs["q_n_status"] = "not_assessed"
        h5.attrs["production_eligibility"] = "not_evaluated"
        previous_time = None
        initial_metadata = first.metadata
        for index, path in enumerate(paths):
            frame = first if index == 0 else decode_frame(path, decoder, scratch, index)
            _check_frame_constants(initial_metadata, frame.metadata)
            if previous_time is not None and not frame.time > previous_time:
                raise DirectConversionError(f"BI4 TimeStep is not strictly increasing at frame {index}: {previous_time}->{frame.time}")
            previous_time = frame.time
            if int(_as_int(frame.metadata, "Piece", default=0)) != int(_as_int(first.metadata, "Piece", default=0)):
                raise DirectConversionError(f"Zone/Piece changed at frame {index}")
            mass = _mass_for_types(base_type, frame.metadata)
            frame_summary.append(_write_frame(h5, index, frame, base_ids, base_type, base_mk, mass))
        h5.flush()
        h5.close()
        h5 = None
        source_unchanged = _ensure_source_unchanged(data_root, before_manifest)
        if not source_unchanged["unchanged"]:
            raise DirectConversionError("raw BI4 source tree changed during read-only conversion")
        with h5py.File(partial, "r+") as completed_h5:
            completed_h5.attrs["source_raw_tree_sha256_after"] = source_unchanged["after_tree_sha256"]
            completed_h5.attrs["source_tree_unchanged"] = True
            completed_h5.attrs["conversion_complete"] = True
        if run_partvtk:
            assert partvtk is not None
            validation_dir = validation_dir or output.parent / "partvtk-validation"
            selected = sorted(set((0, len(paths) // 2, len(paths) - 1)))
            validation_workspace = validation_dir
            if validation_workspace.exists() and any(validation_workspace.iterdir()):
                raise DirectConversionError(f"refusing to overwrite validation directory: {validation_workspace}")
            validation_workspace.mkdir(parents=True, exist_ok=True)
            for index in selected:
                csv_path = _run_partvtk_frame(partvtk, data_root, index, validation_workspace)
                validation.append(compare_partvtk_frame(partial, csv_path, index))
                if not keep_validation_csv:
                    csv_path.unlink(missing_ok=True)
        reference_comparison = None
        if reference_hdf5 is not None:
            reference_comparison = compare_reference_hdf5(partial, reference_hdf5, particle_chunk=particle_chunk)
            if not reference_comparison["passed"]:
                raise DirectConversionError(f"reference HDF5 comparison failed: {reference_comparison}")
        os.replace(partial, output)
        report = {
            "schema": SCHEMA,
            "conversion_status": "completed",
            "conversion_claim": "streaming BI4 adapter evidence only; no Q-N or production claim",
            "output_hdf5": str(output),
            "output_sha256": sha256_file(output),
            "frames": len(paths),
            "particles": int(base_ids.size),
            "solver_dimension": dimension,
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "units": {"time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa"},
            "typed_identity": {"key": "(Zone,Idp)", "zone_source": "BI4 Piece", "blocks": blocks["blocks"], "observed_types": sorted(set(base_type.tolist())), "observed_mks": sorted(set(base_mk.tolist())), "initial_mass_min_kg": float(initial_mass.min()), "initial_mass_max_kg": float(initial_mass.max()), "mass_semantics": "per-frame native MassFluid/MassBound, type-aware; PartVTK cross-check"},
            "time_evidence": {"source": "BI4 decoder TimeStep", "first_s": frame_summary[0]["time"], "last_s": frame_summary[-1]["time"], "strictly_increasing": True},
            "lifecycle": {"contract": "closed fixed identity axis", "introduced_ids": "rejected", "open_birth_adaptive_multi_piece": "rejected", "frame_summary": frame_summary},
            "source_provenance": {"data_root": str(data_root), "raw_tree": source_unchanged, "decoder": {"path": str(decoder), "sha256": sha256_file(decoder)}, "generated_xml": {"path": str(generated_xml), "sha256": sha256_file(generated_xml)}, "geometry_reference_sha256": geometry_sha256, "control_reference_sha256": control_sha256, "geometry_sha256": geometry_sha256, "control_sha256": control_sha256, "solver_receipt": {"path": str(solver_receipt), "sha256": sha256_file(solver_receipt)}, "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256_file(gencase_receipt)}, "owner_metadata": {"path": str(owner_metadata), "sha256": sha256_file(owner_metadata)}, "partvtk": None if partvtk is None else {"path": str(partvtk), "sha256": sha256_file(partvtk)}},
            "hash_scopes": {"physical_condition": physical_scope, "physical_condition_sha256": canonical_hash(physical_scope), "numerical_parameters": numerical_scope, "numerical_parameters_sha256": canonical_hash(numerical_scope)},
            "unsupported_contract": dynamic_contract,
            "partvtk_validation": {"frames": validation, "all_passed": bool(all(item["passed"] for item in validation)) if validation else None},
            "reference_hdf5_comparison": reference_comparison,
            "q_i_status": "not_granted; conversion evidence only",
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
            "resource": {"wall_seconds": time.monotonic() - started, "usage": _usage_delta(resource_before, _resource_snapshot())},
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
        return report
    except Exception:
        if h5 is not None:
            h5.close()
        if partial.exists():
            partial.unlink()
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--partvtk", type=Path)
    parser.add_argument("--validation-dir", type=Path)
    parser.add_argument("--solver-log", type=Path)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--gencase-receipt", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--compare-hdf5", type=Path)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    parser.add_argument("--skip-partvtk-validation", action="store_true")
    parser.add_argument("--keep-validation-csv", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = convert_direct(data_root=args.data_root, generated_xml=args.generated_xml, output=args.output, report_path=args.report, decoder=args.decoder, partvtk=args.partvtk, validation_dir=args.validation_dir, solver_log=args.solver_log, solver_receipt=args.solver_receipt, gencase_receipt=args.gencase_receipt, owner_metadata=args.owner_metadata, reference_hdf5=args.compare_hdf5, run_partvtk=not args.skip_partvtk_validation, keep_validation_csv=args.keep_validation_csv, particle_chunk=args.particle_chunk)
    except DirectConversionError as exc:
        print(f"direct conversion rejected: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"output": report["output_hdf5"], "report": str(args.report), "frames": report["frames"], "particles": report["particles"], "partvtk_all_passed": report["partvtk_validation"]["all_passed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
