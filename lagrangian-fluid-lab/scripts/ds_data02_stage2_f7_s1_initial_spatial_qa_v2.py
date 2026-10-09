#!/usr/bin/env python3
"""Bounded frame-zero spatial/source QA for the F7-S1 CURRENT case.

The source manifest is deliberately metadata-only.  The two BI4 inputs are
``deferred_inputs`` and are opened only by this worker after the shared runner
has reserved the attempt: the prepared GenCase initial population and the
native solver ``Part_0000.bi4``.  No HDF5, full trajectory, later Part files,
solver, or GPU is touched.

This audit answers a narrow bookkeeping question.  It checks the exact
CURRENT288 source recipe, native identity/type/Mk counts, finite frame-zero
coordinates, and whether observed fluid points lie in the declared fluid
envelope (with the paddle box reported separately).  The continuum-owner
mass, discrete sample mass, and binary ``MassFluid`` are kept as separate
quantities.  An observed envelope match does not establish continuous-owner
equivalence, contact, legal flux, physical fate, or dynamics.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA = "ds02.stage2.f7.s1.initial-spatial-qa.v2"
MANIFEST_SCHEMA = "ds02.stage2.f7.s1.initial-spatial-qa.manifest.v2"
CASE_ID = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1"
RUNTIME_ALIAS = "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE"
CURRENT_INDEX = 288
FORBIDDEN_STATIC_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".obi4", ".bi2", ".bi1"}
DEFERRED_BI4_SUFFIX = ".bi4"


class SpatialQAError(ValueError):
    """Raised when the exact source or bounded frame contract is not closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, *, digest: str | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SpatialQAError(f"input is not a regular file: {path}")
    st = path.stat()
    return {
        "path": str(path),
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "sha256": digest if digest is not None else sha256_file(path),
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpatialQAError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SpatialQAError(f"{label} is not a JSON object: {path}")
    return value


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise SpatialQAError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SpatialQAError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise SpatialQAError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise SpatialQAError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _require_static_ref(entry: dict[str, Any], label: str) -> tuple[Path, dict[str, Any]]:
    path_value = entry.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise SpatialQAError(f"{label} path is missing")
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in FORBIDDEN_STATIC_SUFFIXES:
        raise SpatialQAError(f"{label} is a deferred scientific payload: {path}")
    actual = stat_record(path)
    expected = entry.get("sha256")
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != str(expected):
        raise SpatialQAError(f"{label} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if entry.get(field) is not None and actual[field] != int(entry[field]):
            raise SpatialQAError(f"{label} {field} differs: {path}")
    return path, actual


def _validate_xml(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SpatialQAError(f"F7 source XML cannot be parsed: {path}") from exc
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise SpatialQAError("F7 source XML lacks geometry definition")
    expect(definition.get("dp"), "0.02", "F7-S1 source dp")
    params: dict[str, str] = {}
    for parameter in root.findall(".//execution/parameters/parameter"):
        key = parameter.get("key")
        if key:
            params[key] = parameter.get("value", "")
    expected = {
        "SavePosDouble": "2",
        "Boundary": "1",
        "StepAlgorithm": "2",
        "Kernel": "2",
        "Visco": "0.05",
        "DensityDT": "3",
        "DensityDTvalue": "0.1",
        "TimeMax": "12",
        "TimeOut": "0.02",
        "MinFluidStop": "0",
    }
    for key, wanted in expected.items():
        expect(params.get(key), wanted, f"F7 XML parameter {key}")
    motion = root.find(".//motion//mvrotfile/file")
    if motion is None:
        raise SpatialQAError("F7 XML lacks motion file")
    expect(motion.get("name"), "motion_obstacle_quintic.dat", "F7 motion asset")
    fluid_blocks = []
    for element in root.iter():
        if element.tag.split("}")[-1].lower() == "setmkfluid":
            fluid_blocks.append({key: element.get(key) for key in ("mkfluid", "mk")})
    # GenCase's source command uses the fluid ordinal (mk=1), while the
    # generated <particles> ledger records the native Mk value (mkfluid=1,
    # mk=2).  Keep both fields explicit instead of conflating the two.
    native_fluid_blocks = []
    for element in root.iter():
        if element.tag.split("}")[-1].lower() == "fluid" and element.get("mkfluid") is not None:
            native_fluid_blocks.append({key: element.get(key) for key in ("mkfluid", "mk")})
    if fluid_blocks != [{"mkfluid": None, "mk": "1"}] or native_fluid_blocks != [{"mkfluid": "1", "mk": "2"}]:
        raise SpatialQAError(f"F7 source fluid block differs: {fluid_blocks!r}")
    massfluid = None
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if tag == "massfluid":
            massfluid = element.get("value") or element.get("v")
    if massfluid is None:
        raise SpatialQAError("F7 source XML lacks MassFluid")
    return {
        "definition_dp_m": float(definition.get("dp")),
        "parameters": expected,
        "motion_file": motion.get("name"),
        "fluid_blocks": fluid_blocks,
        "native_fluid_blocks": native_fluid_blocks,
        "massfluid_xml_kg": str(massfluid),
    }


def _find_case(current: dict[str, Any]) -> dict[str, Any]:
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise SpatialQAError("CURRENT336 must contain exactly 336 cases")
    if CURRENT_INDEX >= len(rows) or not isinstance(rows[CURRENT_INDEX], dict):
        raise SpatialQAError("CURRENT288 is missing")
    row = rows[CURRENT_INDEX]
    expect(row.get("family_id"), "F7", "CURRENT288 family")
    expect(row.get("physical_case_id"), CASE_ID, "CURRENT288 physical case")
    expect(row.get("runtime_case_alias"), RUNTIME_ALIAS, "CURRENT288 runtime alias")
    expect(row.get("frames"), 601, "CURRENT288 frame count")
    expect(row.get("particles"), 70179, "CURRENT288 particle count")
    expect(row.get("actual_time_window_s"), [0.0, 12.00001411017073], "CURRENT288 time window")
    return row


def _validate_static_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = read_json(path, "F7 initial spatial QA manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    expect(manifest.get("family_id"), "F7", "manifest family")
    expect(manifest.get("sentinel_id"), "F7-S1", "manifest sentinel")
    expect(manifest.get("physical_case_id"), CASE_ID, "manifest physical case")
    source_refs = manifest.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise SpatialQAError("manifest source_refs is empty")
    refs: dict[str, Path] = {}
    docs: dict[str, dict[str, Any]] = {}
    stats: dict[str, dict[str, Any]] = {}
    for entry in source_refs:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise SpatialQAError("malformed source reference")
        key = entry["key"]
        if key in refs:
            raise SpatialQAError(f"duplicate source key: {key}")
        ref_path, stat = _require_static_ref(entry, key)
        refs[key] = ref_path
        stats[key] = stat
        if entry.get("kind", "json") == "json":
            docs[key] = read_json(ref_path, key)
    required = {
        "current336", "owner_metadata", "initial_qa_metadata", "initial_mk_audit",
        "source_control_audit", "f7_label_proof", "f7_label_report", "f7_label_receipt",
        "source_xml", "motion_asset", "safe_decoder", "native_decoder_helper",
    }
    missing = required - set(refs)
    if missing:
        raise SpatialQAError(f"manifest source closure missing {sorted(missing)}")
    current = _find_case(docs["current336"])
    source_bindings = current.get("source_bindings", {})
    expect(source_bindings.get("generated_xml", {}).get("sha256"), stats["source_xml"]["sha256"], "CURRENT XML SHA")
    expect(source_bindings.get("owner_metadata", {}).get("sha256"), stats["owner_metadata"]["sha256"], "CURRENT owner SHA")
    owner = docs["owner_metadata"]
    binding = owner.get("physical_binding", {})
    expect(binding.get("schema"), "ds-data-02.physical-binding.v1", "owner schema")
    expect(binding.get("family_id"), "F7", "owner family")
    expect(binding.get("physical_case_id"), CASE_ID, "owner case")
    geometry = binding.get("geometry", {})
    expect(geometry.get("fluid_envelope", {}).get("low_m"), [-0.55, -0.35, 0.05], "owner fluid envelope low")
    expect(geometry.get("fluid_envelope", {}).get("size_m"), [1.1, 0.7, 0.432], "owner fluid envelope size")
    expect(geometry.get("paddle", {}).get("low_m"), [-0.07, -0.24, 0.05], "owner paddle low")
    expect(geometry.get("paddle", {}).get("size_m"), [0.06, 0.48, 0.48], "owner paddle size")
    expect(binding.get("initial_state", {}).get("initial_mass_total_kg"), 320.1984, "continuum owner mass")
    qa_cases = docs["initial_qa_metadata"].get("cases")
    if not isinstance(qa_cases, list):
        raise SpatialQAError("initial QA metadata lacks cases")
    qa = next((row for row in qa_cases if isinstance(row, dict) and row.get("role") == "coarse"), None)
    if qa is None:
        raise SpatialQAError("initial QA metadata lacks coarse case")
    expect(qa.get("case_id"), RUNTIME_ALIAS, "initial QA case")
    expect(qa.get("expected_total"), 70179, "initial QA total")
    expect(qa.get("expected_fluid"), 40700, "initial QA fluid")
    expect(qa.get("expected_types"), [0, 1, 3], "initial QA types")
    expect(qa.get("initial_bi4_sha256"), manifest["deferred_inputs"]["initial_bi4"]["sha256"], "initial BI4 manifest SHA")
    expect(qa.get("generated_xml_sha256"), stats["source_xml"]["sha256"], "initial QA XML SHA")
    xml = _validate_xml(refs["source_xml"])
    deferred = manifest.get("deferred_inputs")
    if not isinstance(deferred, dict) or set(deferred) != {"initial_bi4", "native_frame0"}:
        raise SpatialQAError("manifest must contain exactly initial_bi4 and native_frame0 deferred inputs")
    for key, entry in deferred.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SpatialQAError(f"deferred {key} is malformed")
        if not entry["path"].lower().endswith(DEFERRED_BI4_SUFFIX):
            raise SpatialQAError(f"deferred {key} is not a BI4")
        if int(entry.get("bytes", 0)) <= 0:
            raise SpatialQAError(f"deferred {key} lacks positive byte estimate")
        if entry.get("sha256") in (None, ""):
            raise SpatialQAError(f"deferred {key} lacks a frozen SHA or PARENT_GUARD_COMPUTED")
    expect(manifest.get("contract", {}).get("deferred_read_scope"), "one prepared BI4 and one native Part_0000 frame only", "read scope")
    expect(manifest.get("contract", {}).get("hdf5_read"), False, "HDF5 read policy")
    expect(manifest.get("contract", {}).get("solver_started"), False, "solver policy")
    return manifest, refs, {**docs, "_source_stats": stats, "_source_xml_parsed": xml}


def _load_scanner(refs: dict[str, Path]):
    spec = importlib.util.spec_from_file_location("f7_initial_spatial_native_helper", refs["native_decoder_helper"])
    if spec is None or spec.loader is None:
        raise SpatialQAError("cannot load safe BI4 helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    scanner = module._load_safe_decoder(refs["safe_decoder"])
    return scanner


def _dtype_for_type_code(type_code: int) -> tuple[np.dtype, bool]:
    table: dict[int, tuple[str, bool]] = {
        3: ("i1", False), 4: ("u1", False), 5: ("<i2", False), 6: ("<u2", False),
        7: ("<i4", False), 8: ("<u4", False), 9: ("<i8", False), 10: ("<u8", False),
        11: ("<f4", False), 12: ("<f8", False), 20: ("<i4", True), 21: ("<u4", True),
        22: ("<f4", True), 23: ("<f8", True),
    }
    if type_code not in table:
        raise SpatialQAError(f"unsupported BI4 array type code: {type_code}")
    dtype, vector = table[type_code]
    return np.dtype(dtype), vector


def _frame_array_map(scan: Any) -> dict[str, Any]:
    if not scan.root.children:
        raise SpatialQAError("BI4 has no PART child")
    part_name = scan.root.children[0].name
    result: dict[str, Any] = {}
    for array in scan.arrays:
        if array.item_path[-1] == part_name:
            if array.name in result:
                raise SpatialQAError(f"BI4 array name is ambiguous: {array.name}")
            result[array.name] = array
    return result


def _read_array(path: Path, record: Any) -> np.ndarray:
    dtype, vector = _dtype_for_type_code(int(record.type_code))
    expected_shape = (int(record.count), 3) if vector else (int(record.count),)
    expected_bytes = int(np.prod(expected_shape)) * dtype.itemsize
    if expected_bytes != int(record.byte_count) or expected_bytes > 32 * 1024 * 1024:
        raise SpatialQAError(f"BI4 array exceeds bounded materialization: {record.name}")
    mapped = np.memmap(path, mode="r", dtype=dtype, offset=int(record.offset), shape=expected_shape)
    try:
        value = np.array(mapped, copy=True)
    finally:
        del mapped
    return value


def _value_map(scan: Any) -> dict[str, Any]:
    return {value.name: value.value for value in scan.root.values}


def _select_array(arrays: dict[str, Any], *names: str) -> tuple[str | None, Any | None]:
    for name in names:
        if name in arrays:
            return name, arrays[name]
    return None, None


def _bounds(points: np.ndarray) -> dict[str, Any] | None:
    if len(points) == 0:
        return None
    return {"low_m": np.min(points, axis=0).astype(float).tolist(), "high_m": np.max(points, axis=0).astype(float).tolist(), "count": int(len(points))}


def _frame_summary(path: Path, scanner: Any, expected: dict[str, Any], role: str) -> dict[str, Any]:
    pre_stat = path.stat()
    pre_sha = sha256_file(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        scan = scanner.scan_bi4_fd(fd, pre_sha)
    finally:
        os.close(fd)
    # The scanner hash covers its fd walk, while the array reader later opens
    # the same file through memmaps. Keep the final full hash/stat after all
    # array payload reads; a pre/post pair before the memmaps would leave that
    # second read outside the integrity boundary.
    pre_identity = (pre_stat.st_dev, pre_stat.st_ino, pre_stat.st_size, pre_stat.st_mtime_ns, pre_stat.st_ctime_ns)
    values = _value_map(scan)
    arrays = _frame_array_map(scan)
    _, pos_rec = _select_array(arrays, "Posd", "Pos")
    _, id_rec = _select_array(arrays, "Idp", "Id")
    if pos_rec is None or id_rec is None:
        raise SpatialQAError(f"{role} lacks Posd/Idp arrays")
    positions = _read_array(path, pos_rec).astype(np.float64, copy=False)
    ids = _read_array(path, id_rec).astype(np.int64, copy=False).reshape(-1)
    type_name, type_rec = _select_array(arrays, "Type")
    mk_name, mk_rec = _select_array(arrays, "Mk")
    type_values = _read_array(path, type_rec).astype(np.int64, copy=False).reshape(-1) if type_rec is not None else None
    mk_values = _read_array(path, mk_rec).astype(np.int64, copy=False).reshape(-1) if mk_rec is not None else None
    _, mass_rec = _select_array(arrays, "Mass")
    mass_values = _read_array(path, mass_rec).astype(np.float64, copy=False).reshape(-1) if mass_rec is not None else None
    total = int(values.get("CaseNp", len(ids)))
    fluid = int(values.get("CaseNfluid", expected["expected_fluid"]))
    fixed = int(values.get("CaseNfixed", 0))
    moving = int(values.get("CaseNmoving", 0))
    if len(ids) != total or len(positions) != total:
        raise SpatialQAError(f"{role} array count does not equal CaseNp")
    id_unique = len(np.unique(ids)) == len(ids)
    if type_values is not None and len(type_values) != total:
        raise SpatialQAError(f"{role} Type length does not equal CaseNp")
    if mk_values is not None and len(mk_values) != total:
        raise SpatialQAError(f"{role} Mk length does not equal CaseNp")
    if mass_values is not None and len(mass_values) != total:
        raise SpatialQAError(f"{role} Mass length does not equal CaseNp")
    if type_values is not None:
        fluid_mask = type_values == 3
        fixed_mask = type_values == 0
        moving_mask = type_values == 1
        type_source = "native_Type_array"
    else:
        fluid_mask = ids >= total - fluid
        fixed_mask = ids < fixed
        moving_mask = (ids >= fixed) & (ids < fixed + moving)
        type_source = "header_Idp_partition_fallback"
    owner_low = np.asarray([-0.55, -0.35, 0.05], dtype=float)
    owner_high = np.asarray([0.55, 0.35, 0.482], dtype=float)
    paddle_low = np.asarray([-0.07, -0.24, 0.05], dtype=float)
    paddle_high = np.asarray([-0.01, 0.24, 0.53], dtype=float)
    tank_low = np.asarray([-0.6, -0.4, 0.0], dtype=float)
    tank_high = np.asarray([0.6, 0.4, 0.6], dtype=float)
    fluid_pos = positions[fluid_mask]
    fixed_pos = positions[fixed_mask]
    moving_pos = positions[moving_mask]
    fluid_mass = float(np.sum(mass_values[fluid_mask])) if mass_values is not None else fluid * float(values.get("MassFluid", float("nan")))
    outside = np.any((fluid_pos < owner_low) | (fluid_pos > owner_high), axis=1) if len(fluid_pos) else np.array([], dtype=bool)
    inside_paddle = np.all((fluid_pos > paddle_low) & (fluid_pos < paddle_high), axis=1) if len(fluid_pos) else np.array([], dtype=bool)
    fluid_mk_counts = None
    if mk_values is not None:
        fluid_mk_counts = {str(int(mk)): int(np.count_nonzero(mk_values[fluid_mask] == mk)) for mk in np.unique(mk_values[fluid_mask])}
    type_counts = None
    if type_values is not None:
        type_counts = {str(int(kind)): int(np.count_nonzero(type_values == kind)) for kind in np.unique(type_values)}
    # Every payload read is complete here. This post record is deliberately
    # taken after the final _read_array call, and is therefore the only
    # filesystem integrity endpoint for parser-consumed payload bytes.
    post_stat = path.stat()
    post_sha = sha256_file(path)
    post_identity = (post_stat.st_dev, post_stat.st_ino, post_stat.st_size, post_stat.st_mtime_ns, post_stat.st_ctime_ns)
    if pre_identity != post_identity or pre_sha != post_sha:
        raise SpatialQAError(f"{role} changed during bounded BI4 read")
    massfluid = values.get("MassFluid")
    return {
        "role": role,
        "path": str(path),
        "pre": {"bytes": pre_stat.st_size, "mtime_ns": pre_stat.st_mtime_ns, "ctime_ns": pre_stat.st_ctime_ns, "st_dev": pre_stat.st_dev, "st_ino": pre_stat.st_ino, "sha256": pre_sha},
        "post": {"bytes": post_stat.st_size, "mtime_ns": post_stat.st_mtime_ns, "ctime_ns": post_stat.st_ctime_ns, "st_dev": post_stat.st_dev, "st_ino": post_stat.st_ino, "sha256": post_sha},
        "safe_scan_sha256": scan.input_sha256,
        "safe_scan_bytes": scan.input_bytes,
        "safe_scan_hash_scope": "official scanner fd structural walk; scanner input hash is not a substitute for the final array-read post hash",
        "array_reader_content_sha256": "NOT_COMPUTED",
        "array_reader_hash_scope": "memmap payload reads are bracketed by pre/post full-file hashes; no independent single-fd array-reader digest is claimed",
        "post_after_all_payload_reads": True,
        "header": {key: values.get(key) for key in ("CaseNp", "CaseNfluid", "CaseNfixed", "CaseNmoving", "MassFluid", "Data2d")},
        "array_names": sorted(arrays),
        "array_type_source": type_source,
        "native_type_array": type_name,
        "native_mk_array": mk_name,
        "total_particles": total,
        "fluid_particles": int(np.count_nonzero(fluid_mask)),
        "fixed_particles": int(np.count_nonzero(fixed_mask)),
        "moving_particles": int(np.count_nonzero(moving_mask)),
        "id_unique": bool(id_unique),
        "id_min": int(ids.min()) if len(ids) else None,
        "id_max": int(ids.max()) if len(ids) else None,
        "finite_positions": bool(np.isfinite(positions).all()),
        "type_counts": type_counts,
        "mk_counts_fluid": fluid_mk_counts,
        "fluid_bounds_m": _bounds(fluid_pos),
        "fixed_bounds_m": _bounds(fixed_pos),
        "moving_bounds_m": _bounds(moving_pos),
        "fluid_mass_kg": fluid_mass,
        "massfluid_header_kg": massfluid,
        "support_diagnostics": {
            "declared_owner_fluid_envelope_m": [owner_low.tolist(), owner_high.tolist()],
            "declared_paddle_box_m": [paddle_low.tolist(), paddle_high.tolist()],
            "tank_box_m": [tank_low.tolist(), tank_high.tolist()],
            "fluid_outside_owner_envelope_count": int(np.count_nonzero(outside)),
            "fluid_inside_paddle_count": int(np.count_nonzero(inside_paddle)),
            "fixed_outside_tank_count": int(np.count_nonzero(np.any((fixed_pos < tank_low) | (fixed_pos > tank_high), axis=1))) if len(fixed_pos) else 0,
            "moving_outside_tank_count": int(np.count_nonzero(np.any((moving_pos < tank_low) | (moving_pos > tank_high), axis=1))) if len(moving_pos) else 0,
            "fluid_support_scope": "observed frame-zero coordinates against declared envelope-minus-paddle boxes; no continuous-owner or contact claim",
        },
        "_ids": ids,
        "_positions": positions,
        "_types": type_values,
        "_mks": mk_values,
    }


def _compare_frames(source: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    source_ids = source.pop("_ids")
    native_ids = native.pop("_ids")
    source_positions = source.pop("_positions")
    native_positions = native.pop("_positions")
    source_types = source.pop("_types")
    native_types = native.pop("_types")
    source_mks = source.pop("_mks")
    native_mks = native.pop("_mks")
    result: dict[str, Any] = {
        "same_particle_count": len(source_ids) == len(native_ids),
        "same_id_set": False,
        "position_max_abs_delta_m": None,
        "type_arrays_equal": None,
        "mk_arrays_equal": None,
        "massfluid_equal": source.get("massfluid_header_kg") == native.get("massfluid_header_kg"),
        "comparison_scope": "prepared source BI4 versus native Part_0000 only; no later frames",
    }
    if len(source_ids) == len(native_ids):
        source_order = np.argsort(source_ids, kind="stable")
        native_order = np.argsort(native_ids, kind="stable")
        result["same_id_set"] = bool(np.array_equal(source_ids[source_order], native_ids[native_order]))
        if result["same_id_set"]:
            result["position_max_abs_delta_m"] = float(np.max(np.abs(source_positions[source_order] - native_positions[native_order])))
            if source_types is not None and native_types is not None:
                result["type_arrays_equal"] = bool(np.array_equal(source_types[source_order], native_types[native_order]))
            if source_mks is not None and native_mks is not None:
                result["mk_arrays_equal"] = bool(np.array_equal(source_mks[source_order], native_mks[native_order]))
    return result


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, refs, docs = _validate_static_manifest(manifest_path.expanduser().resolve())
    deferred = manifest["deferred_inputs"]
    deferred_stats: dict[str, dict[str, Any]] = {}
    for key, entry in deferred.items():
        path = Path(entry["path"]).expanduser().resolve()
        if not path.is_file():
            raise SpatialQAError(f"deferred {key} is not available after reservation: {path}")
        if path.suffix.lower() != DEFERRED_BI4_SUFFIX:
            raise SpatialQAError(f"deferred {key} is not BI4: {path}")
        stat = path.stat()
        if entry.get("bytes") is not None and stat.st_size != int(entry["bytes"]):
            raise SpatialQAError(f"deferred {key} byte count differs: {path}")
        digest = sha256_file(path)
        expected = entry.get("sha256")
        if expected not in (None, "PARENT_GUARD_COMPUTED") and digest != str(expected):
            raise SpatialQAError(f"deferred {key} SHA differs: {path}")
        deferred_stats[key] = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": digest, "content_read_after_reservation": True}
    scanner = _load_scanner(refs)
    qa = next(row for row in docs["initial_qa_metadata"]["cases"] if row.get("role") == "coarse")
    source_frame = _frame_summary(Path(deferred["initial_bi4"]["path"]).expanduser().resolve(), scanner, qa, "prepared_initial_bi4")
    native_frame = _frame_summary(Path(deferred["native_frame0"]["path"]).expanduser().resolve(), scanner, qa, "native_part_0000")
    comparison = _compare_frames(source_frame, native_frame)
    owner = docs["owner_metadata"].get("physical_binding", {})
    initial_mass = float(owner["initial_state"]["initial_mass_total_kg"])
    sample_mass = float(qa["official_CSV_fluid_mass_sum_kg"])
    native_mass = float(native_frame["fluid_mass_kg"])
    base_checks = {
        "current_index_288_exact": True,
        "source_header_identity": source_frame["total_particles"] == 70179 and source_frame["fluid_particles"] == 40700,
        "native_header_identity": native_frame["total_particles"] == 70179 and native_frame["fluid_particles"] == 40700,
        "source_id_unique": source_frame["id_unique"],
        "native_id_unique": native_frame["id_unique"],
        "source_finite_positions": source_frame["finite_positions"],
        "native_finite_positions": native_frame["finite_positions"],
        "source_native_same_id_set": comparison["same_id_set"],
    }
    result = {
        "schema": SCHEMA,
        "status": "COMPLETED_F7_S1_FRAME0_SPATIAL_SOURCE_QA",
        "sentinel_id": "F7-S1",
        "family_id": "F7",
        "physical_case_id": CASE_ID,
        "current_binding": {"index": CURRENT_INDEX, "runtime_case_alias": RUNTIME_ALIAS, "frames": 601, "particles": 70179, "actual_time_window_s": [0.0, 12.00001411017073]},
        "source_recipe": {"xml": docs["_source_xml_parsed"], "source_xml": docs["_source_stats"]["source_xml"], "owner": docs["_source_stats"]["owner_metadata"], "initial_qa_metadata": docs["_source_stats"]["initial_qa_metadata"]},
        "deferred_inputs": deferred_stats,
        "frames": {"prepared_initial_bi4": source_frame, "native_part_0000": native_frame},
        "frame0_comparison": comparison,
        "checks": base_checks,
        "pass": all(base_checks.values()),
        "support_diagnostics": {
            "prepared_initial_bi4": source_frame["support_diagnostics"],
            "native_part_0000": native_frame["support_diagnostics"],
            "fixed_moving_initial_support": "observed bounds/counts only; no contact or wetted-wall qualification",
        },
        "mass_semantics": {
            "continuum_owner_mass_kg": initial_mass,
            "official_csv_sample_mass_kg": sample_mass,
            "native_part_0000_observed_fluid_mass_kg": native_mass,
            "native_part_0000_minus_continuum_owner_pct": (native_mass / initial_mass - 1.0) * 100.0,
            "sample_minus_continuum_owner_pct": (sample_mass / initial_mass - 1.0) * 100.0,
            "source_old_resolution_gates": "diagnostic only; .025/.016 mass results do not alter this frame-0 QA",
            "mass_rescale": False,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "continuous_owner": "UNKNOWN", "contact": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        "read_policy": {"hdf5_opened": False, "prepared_bi4_opened": True, "native_part_0000_opened": True, "later_native_frames_opened": 0, "solver_started": False, "gpu_started": False, "partout_opened": False, "vtk_opened": False},
        "claim_boundary": "Frame-zero source/identity/support diagnostic only. The declared envelope and observed coordinate inclusion do not prove continuous-owner equivalence, contact, legal flux, physical fate, or dynamics.",
        "old_products_unchanged": True,
    }
    atomic_json(output, result)
    print(json.dumps({"pass": result["pass"], "current_index": CURRENT_INDEX, "source_sha256": deferred_stats["initial_bi4"]["sha256"], "native_sha256": deferred_stats["native_frame0"]["sha256"], "outside_native": native_frame["support_diagnostics"]["fluid_outside_owner_envelope_count"]}, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.manifest, args.output)
    except (SpatialQAError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
