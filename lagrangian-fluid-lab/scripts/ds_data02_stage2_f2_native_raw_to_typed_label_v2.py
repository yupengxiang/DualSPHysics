#!/usr/bin/env python3
"""Guarded F2-S1 native BI4 -> typed -> v15/v16 label reconstruction.

This is a new reconstruction consumer.  The consumed v1 preparation module
and the producer's v1/v15/v16 artifacts are left untouched.  The worker calls
the checked-in ``ds_data02_f5_bi4`` converter once, while wrapping its decoder
and raw-tree manifest callbacks.  That gives one read of each ``Part_*.bi4``
frame for the converter and records the decoder header plus hashes of every
decoded source array.  ``PartOut_*.obi4`` and ``RunPARTs.csv`` are provenance
evidence only; they can never satisfy the frame-array contract.

The metadata-only path performs no raw/HDF5 content read.  Actual conversion
and typed-to-label reads require ``--io-slot-approved``.  All output paths are
new-only and all quality fields remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-reconstruction.v2"
REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
H5_SUFFIXES = {".h5", ".hdf5"}


class NativeReconstructionError(RuntimeError):
    """Raised when a native reconstruction binding is incomplete or unsafe."""


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any, *, drop: Sequence[str] = ()) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key not in set(drop)}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, default=_json_default).encode("utf-8")
    ).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise NativeReconstructionError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise NativeReconstructionError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise NativeReconstructionError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                      default=_json_default)
            stream.write("\n")
    except FileExistsError as error:
        raise NativeReconstructionError(f"refusing to overwrite existing output: {target}") from error


def _require_sha(value: Any, name: str, *, allow_pending: bool = False) -> str | None:
    if allow_pending and value in (None, "PENDING_PARENT_GUARD_CONTENT_SHA256"):
        return None
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise NativeReconstructionError(f"{name} must be a lowercase SHA-256")
    return value


def _stat_record(path: Path, *, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise NativeReconstructionError(f"source is missing: {path}")
    stat = path.stat()
    return {"role": role, "path": str(path.resolve()), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"user_seconds": float(usage.ru_utime),
            "system_seconds": float(usage.ru_stime),
            "max_rss_kib": float(usage.ru_maxrss)}


def _load_module(path: Path, name: str) -> Any:
    if not path.is_file():
        raise NativeReconstructionError(f"bound Python module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise NativeReconstructionError(f"cannot import bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module_binding(item: Mapping[str, Any], role: str) -> tuple[Path, str]:
    if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
        raise NativeReconstructionError(f"module binding is malformed: {role}")
    path = Path(item["path"]).expanduser().resolve()
    expected = _require_sha(item.get("sha256"), f"modules.{role}.sha256")
    assert expected is not None
    actual = sha256_file(path)
    if actual != expected:
        raise NativeReconstructionError(f"module SHA differs: {role}")
    return path, expected


def _source_binding(request: Mapping[str, Any], role: str, *, verify_hash: bool = True) -> tuple[Path, str]:
    sources = request.get("source_files")
    if not isinstance(sources, list):
        raise NativeReconstructionError("source_files list is required")
    values = [item for item in sources if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise NativeReconstructionError(f"exactly one source binding is required: {role}")
    item = values[0]
    if not isinstance(item.get("path"), str):
        raise NativeReconstructionError(f"source path is malformed: {role}")
    expected = _require_sha(item.get("sha256"), f"source_files[{role}].sha256")
    assert expected is not None
    path = Path(item["path"]).expanduser().resolve()
    if not path.is_file():
        raise NativeReconstructionError(f"source is missing: {role}: {path}")
    if verify_hash and sha256_file(path) != expected:
        raise NativeReconstructionError(f"source SHA differs: {role}")
    return path, expected


def _frame_records(request: Mapping[str, Any], *, verify_hash: bool) -> tuple[Path, list[dict[str, Any]]]:
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise NativeReconstructionError("raw_binding is required")
    data_root_value = raw.get("data_root")
    if not isinstance(data_root_value, str):
        raise NativeReconstructionError("raw_binding.data_root is required")
    data_root = Path(data_root_value).expanduser().resolve()
    if not data_root.is_dir():
        raise NativeReconstructionError(f"raw BI4 data root is missing: {data_root}")
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        raise NativeReconstructionError("raw_binding.frames must list all Part_*.bi4 frames")
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise NativeReconstructionError("raw frame records must be contiguous from frame zero")
        path_value = item.get("path")
        if not isinstance(path_value, str):
            raise NativeReconstructionError(f"raw frame {index} path is malformed")
        path = Path(path_value).expanduser().resolve()
        if path.parent != data_root or path.name != f"Part_{index:04d}.bi4":
            raise NativeReconstructionError(f"raw frame {index} is not the exact top-level Part path")
        record = _stat_record(path, role=f"raw_frame_{index:04d}")
        if int(item.get("bytes", -1)) != record["bytes"]:
            raise NativeReconstructionError(f"raw frame {index} byte stat differs")
        expected = _require_sha(item.get("sha256"), f"raw_binding.frames[{index}].sha256",
                                allow_pending=True)
        record["frame"] = index
        record["sha256"] = expected
        record["content_hash_status"] = "VERIFIED_BEFORE_RUN" if expected else "PARENT_GUARD_MUST_RECORD"
        if verify_hash and expected is not None and sha256_file(path) != expected:
            raise NativeReconstructionError(f"raw frame SHA differs: {path}")
        checked.append(record)
    observed = sorted(data_root.glob("Part_*.bi4"))
    expected_paths = [Path(item["path"]) for item in checked]
    if observed != expected_paths:
        raise NativeReconstructionError("raw frame list does not equal all top-level Part_*.bi4 files")
    return data_root, checked


def _require_request(request: Mapping[str, Any], *, verify_sources: bool) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise NativeReconstructionError(f"unsupported request schema: {request.get('schema')!r}")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise NativeReconstructionError("model/CFD invocation is forbidden")
    if request.get("qualification") != UNKNOWN_QUALIFICATION:
        raise NativeReconstructionError("QI/QN/QE must remain UNKNOWN")
    if request.get("role") != "DEVELOPMENT" or request.get("status") not in {"PENDING_IO_SLOT", "READY_FOR_PARENT_GUARD"}:
        raise NativeReconstructionError("request must remain DEVELOPMENT and pending/guard-ready")
    modules = request.get("modules")
    if not isinstance(modules, Mapping):
        raise NativeReconstructionError("modules closure is required")
    module_paths: dict[str, Path] = {}
    module_hashes: dict[str, str] = {}
    for role in ("raw_converter", "v15_operator", "v14_operator", "v16_operator"):
        path, digest = _module_binding(modules.get(role), role)
        module_paths[role], module_hashes[role] = path, digest
    parent_preverified = request.get("source_hashes_preverified_by_parent") is True
    # The shared stage2guard hashes every declared input before launching this
    # worker.  Rehashing the 3.6 GB initial CSV (and other historical evidence)
    # inside the worker would only duplicate I/O.  The request still carries
    # every SHA and the guard receipt is part of the execution closure.
    source_verify = bool(verify_sources and not parent_preverified)
    data_root, frames = _frame_records(request, verify_hash=source_verify)
    raw = request["raw_binding"]
    expected_tree = _require_sha(raw.get("expected_raw_tree_sha256"),
                                 "raw_binding.expected_raw_tree_sha256")
    assert expected_tree is not None
    # These are sources the converter actually parses.  PartOut/RunPARTs are
    # required as evidence records but never count as BI4 frame input.
    for role in ("current_catalog", "generated_xml", "motion_dat", "gencase_receipt",
                 "solver_receipt", "owner_metadata", "initial_csv", "conversion_report"):
        _source_binding(request, role, verify_hash=source_verify)
    raw_roles = {str(item.get("role")) for item in request.get("source_files", [])
                 if isinstance(item, Mapping)}
    if not {"native_partout", "native_runparts"}.issubset(raw_roles):
        raise NativeReconstructionError("PartOut and RunPARTs evidence bindings are required")
    _source_binding(request, "native_partout", verify_hash=source_verify)
    _source_binding(request, "native_runparts", verify_hash=source_verify)
    if not isinstance(request.get("typed_output_contract"), Mapping):
        raise NativeReconstructionError("typed_output_contract is required")
    if not isinstance(request.get("label_contract"), Mapping):
        raise NativeReconstructionError("label_contract is required")
    return {"module_paths": module_paths, "module_hashes": module_hashes,
            "data_root": data_root, "frames": frames, "expected_tree": expected_tree}


def _array_sha(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_default(item) if isinstance(item, (np.generic, Path)) else item
            for key, item in value.items()}


def _capture_converter(request: Mapping[str, Any], bound: Mapping[str, Any], output_dir: Path,
                       *, run_labels: bool) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Run the trusted converter once and retain decoder/raw callback evidence."""
    converter = _load_module(bound["module_paths"]["raw_converter"],
                             "_ds02_bound_converter_v2")
    data_root = bound["data_root"]
    raw = request["raw_binding"]
    actual_before: list[dict[str, Any]] = []
    actual_after: list[dict[str, Any]] = []
    original_manifest = converter.raw_tree_manifest

    def capture_manifest(root: Path) -> dict[str, Any]:
        value = original_manifest(root)
        (actual_before if not actual_before else actual_after).append(value)
        return value

    converter.raw_tree_manifest = capture_manifest
    frame_records: list[dict[str, Any]] = []
    original_decode = converter.decode_frame

    def capture_decode(frame_path: Path, decoder: Path, scratch_root: Path, index: int) -> Any:
        frame = original_decode(frame_path, decoder, scratch_root, index)
        frame_records.append({
            "frame": int(index),
            "path": str(frame_path.resolve()),
            "time_s": float(frame.time),
            "decoder_xml_sha256": str(frame.decoder_xml_sha256),
            "raw_header": {"metadata": _json_safe_mapping(frame.metadata),
                           "info": _json_safe_mapping(frame.info)},
            "decoded_source_arrays": {
                "Idp": {"dtype": str(frame.ids.dtype), "shape": list(frame.ids.shape), "sha256": _array_sha(frame.ids)},
                "Pos": {"dtype": str(frame.position.dtype), "shape": list(frame.position.shape), "sha256": _array_sha(frame.position)},
                "Vel": {"dtype": str(frame.velocity.dtype), "shape": list(frame.velocity.shape), "sha256": _array_sha(frame.velocity)},
                "Rhop": {"dtype": str(frame.density.dtype), "shape": list(frame.density.shape), "sha256": _array_sha(frame.density)},
            },
            "source_array_semantics": {
                "identity": "decoded Idp sorted by converter before typed-axis mapping",
                "position": "Pos.bin or Posd.bin in solver Cartesian metres",
                "velocity": "Vel.bin in inertial world m/s",
                "density": "Rhop.bin in kg/m^3",
            },
        })
        return frame

    converter.decode_frame = capture_decode
    generated_xml, _ = _source_binding(request, "generated_xml", verify_hash=False)
    motion_dat, _ = _source_binding(request, "motion_dat", verify_hash=False)
    solver_receipt, _ = _source_binding(request, "solver_receipt", verify_hash=False)
    gencase_receipt, _ = _source_binding(request, "gencase_receipt", verify_hash=False)
    owner_metadata, _ = _source_binding(request, "owner_metadata", verify_hash=False)
    decoder = Path(str(request["decoder"]["path"])).expanduser().resolve()
    decoder_expected = _require_sha(request["decoder"].get("sha256"), "decoder.sha256")
    assert decoder_expected is not None
    if sha256_file(decoder) != decoder_expected or not os.access(decoder, os.X_OK):
        raise NativeReconstructionError("bound BI4 decoder SHA/executable check failed")
    run_out = _resolve_run_out(request, solver_receipt)
    typed_path = output_dir / "typed-reconstructed-v2.h5"
    converter_report_path = output_dir / "raw-converter-report-v2.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    report = converter.convert_direct(
        data_root=data_root, generated_xml=generated_xml, output=typed_path,
        report_path=converter_report_path, decoder=decoder, partvtk=None,
        validation_dir=None, solver_log=run_out, solver_receipt=solver_receipt,
        gencase_receipt=gencase_receipt, owner_metadata=owner_metadata,
        reference_hdf5=None, run_partvtk=False, particle_chunk=int(request["typed_output_contract"].get("particle_chunk", 65536)),
    )
    # The converter may have called raw_tree_manifest before decode and after
    # decode.  Both are required; a single callback is not an unchanged-source
    # proof.
    if len(actual_before) != 1 or len(actual_after) != 1:
        raise NativeReconstructionError("converter raw-tree callbacks were not observed exactly twice")
    if actual_before[0]["tree_sha256"] != bound["expected_tree"]:
        raise NativeReconstructionError("raw BI4 tree SHA differs from the source-bound producer tree")
    if actual_after[0]["tree_sha256"] != actual_before[0]["tree_sha256"]:
        raise NativeReconstructionError("raw BI4 tree changed during conversion")
    by_name = {str(item["path"]): item for item in actual_before[0]["files"]}
    for item in frame_records:
        rel = Path(item["path"]).relative_to(data_root).as_posix()
        if rel not in by_name:
            raise NativeReconstructionError(f"decoded frame absent from raw manifest: {rel}")
        item["raw_frame_file_sha256"] = by_name[rel]["sha256"]
        item["raw_frame_file_bytes"] = by_name[rel]["bytes"]
    if len(frame_records) != len(bound["frames"]):
        raise NativeReconstructionError("converter did not decode every bound BI4 frame")
    for expected, observed in zip(bound["frames"], frame_records):
        if expected["frame"] != observed["frame"] or expected["path"] != observed["path"]:
            raise NativeReconstructionError("decoded frame order/path differs from bound raw frame list")
        declared = expected.get("sha256")
        if declared and declared != observed["raw_frame_file_sha256"]:
            raise NativeReconstructionError(f"raw frame content SHA differs at frame {expected['frame']}")
    raw_evidence = {
        "data_root": str(data_root),
        "expected_raw_tree_sha256": bound["expected_tree"],
        "before_tree_sha256": actual_before[0]["tree_sha256"],
        "after_tree_sha256": actual_after[0]["tree_sha256"],
        "file_count": actual_before[0]["file_count"],
        "frame_count": len(frame_records),
        "frames": frame_records,
        "header_semantics": "decoder metadata/info captured from each Part_*.bi4 invocation; TimeStep is source time",
        "partout_runparts_role": "cause/provenance evidence only; never decoded typed source",
    }
    return report, raw_evidence, typed_path


def _resolve_run_out(request: Mapping[str, Any], solver_receipt: Path) -> Path:
    """Resolve the exact solver Run.out from receipt command/output scope."""
    receipt = _load_json(solver_receipt)
    command = receipt.get("command")
    if not isinstance(command, list) or not command:
        raise NativeReconstructionError("solver receipt command is required for Run.out binding")
    output_root_value = receipt.get("output_root")
    if not isinstance(output_root_value, str):
        raise NativeReconstructionError("solver receipt output_root is required")
    output_root = Path(output_root_value).expanduser().resolve()
    candidates: list[Path] = []
    # Native DualSPHysics receives the solver output directory as the fourth
    # positional command argument.  Only that directory and the receipt root
    # are admissible; no neighbouring Run.out fallback is allowed.
    for value in command:
        if isinstance(value, str) and ("solver_output" in value or value.endswith("output")):
            candidate = Path(value).expanduser()
            if candidate.is_dir():
                candidates.append(candidate / "Run.out")
    candidates.append(output_root / "solver_output" / "Run.out")
    candidates.append(output_root / "Run.out")
    unique: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in unique:
            unique.append(candidate)
    present = [candidate for candidate in unique if candidate.is_file()]
    if len(present) != 1:
        raise NativeReconstructionError(
            "exact solver command output Run.out is missing or ambiguous; "
            f"checked {[str(item) for item in unique]}"
        )
    return present[0]


def _identity_hash(zones: np.ndarray, ids: np.ndarray) -> str:
    order = np.lexsort((ids.astype("<i8"), zones.astype("<i8")))
    return hashlib.sha256(np.stack([zones[order].astype("<i8"), ids[order].astype("<i8")], axis=1).tobytes()).hexdigest()


def _spans(indices: np.ndarray) -> list[tuple[int, int, int, int]]:
    if len(indices) == 0:
        return []
    starts = [0]
    starts.extend((np.flatnonzero(np.diff(indices) != 1) + 1).tolist())
    return [(local_start, local_stop, int(indices[local_start]), int(indices[local_stop - 1]) + 1)
            for local_start, local_stop in zip(starts, starts[1:] + [len(indices)])]


def _selected_read(dataset: Any, frame: int, indices: np.ndarray, *, width: int | None = None) -> np.ndarray:
    result_shape = (len(indices),) if width is None else (len(indices), width)
    result = np.empty(result_shape, dtype=dataset.dtype)
    for local_start, local_stop, source_start, source_stop in _spans(indices):
        result[local_start:local_stop] = dataset[frame, source_start:source_stop]
    return result


def _validate_and_load_typed(path: Path, request: Mapping[str, Any], converter_report: Mapping[str, Any],
                             raw_evidence: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = request["typed_output_contract"]
    frames = int(contract["frames"])
    particles = int(contract["particles"])
    current = request["current_binding"]
    expected_times = np.asarray(contract["expected_times_s"], dtype="f8")
    if len(expected_times) != frames:
        raise NativeReconstructionError("typed expected time vector length is wrong")
    cohort = request["cohort"]
    declared_ids = contract.get("fluid_identity_ids")
    declared_zones = contract.get("fluid_identity_zones")
    declared_mks = contract.get("fluid_identity_mks")
    if (declared_ids is None) != (declared_zones is None) or (declared_ids is None) != (declared_mks is None):
        raise NativeReconstructionError("typed fluid identity vectors must be all present or all omitted")
    selected_ids = np.asarray(declared_ids, dtype="<u4") if declared_ids is not None else None
    selected_zones = np.asarray(declared_zones, dtype="<i2") if declared_zones is not None else None
    selected_mks = np.asarray(declared_mks, dtype="<i2") if declared_mks is not None else None
    if selected_ids is not None:
        assert selected_zones is not None and selected_mks is not None
        if selected_ids.shape != selected_zones.shape or selected_ids.shape != selected_mks.shape:
            raise NativeReconstructionError("typed fluid identity vectors have inconsistent shapes")
        if len(selected_ids) != int(cohort["expected_initial_fluid_count"]):
            raise NativeReconstructionError("typed fluid identity count differs from frozen cohort")
    expected_identity_sha = str(cohort["source_identity_set_sha256"])
    if selected_ids is not None:
        assert selected_zones is not None and selected_mks is not None
        if _identity_hash(selected_zones, selected_ids) != expected_identity_sha:
            raise NativeReconstructionError("request fluid identity vectors do not match frozen CSV identity hash")
        selected_order = np.lexsort((selected_ids, selected_zones))
        selected_ids = selected_ids[selected_order]
        selected_zones = selected_zones[selected_order]
        selected_mks = selected_mks[selected_order]
    raw_frames = raw_evidence.get("frames")
    if not isinstance(raw_frames, list) or len(raw_frames) != frames:
        raise NativeReconstructionError("raw decoder evidence does not cover every expected frame")
    for frame_index, raw_frame in enumerate(raw_frames):
        if not isinstance(raw_frame, Mapping) or raw_frame.get("frame") != frame_index:
            raise NativeReconstructionError("raw decoder evidence frame order is not contiguous")
        try:
            raw_time = float(raw_frame["time_s"])
            raw_id_shape = raw_frame["decoded_source_arrays"]["Idp"]["shape"]
            raw_id_count = int(raw_id_shape[0])
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise NativeReconstructionError(f"raw decoder header/Idp evidence is incomplete at frame {frame_index}") from error
        if not math.isclose(raw_time, float(expected_times[frame_index]), rel_tol=0.0, abs_tol=2e-8):
            raise NativeReconstructionError(f"raw decoder TimeStep differs from frozen timeline at frame {frame_index}")
        summary = converter_report.get("lifecycle", {}).get("frame_summary", [])
        if isinstance(summary, list) and len(summary) == frames:
            if raw_id_count != int(summary[frame_index].get("active_particles", -1)):
                raise NativeReconstructionError(f"raw decoded Idp count differs from lifecycle at frame {frame_index}")
    # The HDF5 output is read only after conversion and only under the parent
    # I/O grant.  This validation is frame-by-frame/chunked; no full particle
    # wall/boundary arrays are materialized.
    if path.suffix.lower() not in H5_SUFFIXES or not path.is_file():
        raise NativeReconstructionError("typed reconstruction output is missing/not HDF5")
    trajectory: dict[str, Any] = {}
    lifecycle: list[dict[str, Any]] = []
    selected_indices: np.ndarray
    with h5py.File(path, "r") as h5:
        required = ("time", "particle_id", "particle_zone", "valid", "position", "velocity",
                    "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass")
        missing = [name for name in required if name not in h5]
        if missing:
            raise NativeReconstructionError(f"typed HDF5 is missing datasets: {missing}")
        if h5["time"].shape != (frames,) or h5["particle_id"].shape != (particles,) or h5["particle_zone"].shape != (particles,):
            raise NativeReconstructionError("typed HDF5 identity/time shapes differ from CURRENT")
        for name in ("valid", "type", "mk", "density", "mass", "pressure"):
            if h5[name].shape != (frames, particles):
                raise NativeReconstructionError(f"typed HDF5 shape differs for {name}")
        for name in ("position", "velocity"):
            if h5[name].shape != (frames, particles, 3):
                raise NativeReconstructionError(f"typed HDF5 shape differs for {name}")
        if h5["initial_type"].shape != (particles,) or h5["initial_mk"].shape != (particles,) or h5["initial_mass"].shape != (particles,):
            raise NativeReconstructionError("typed initial identity/mass shapes differ from CURRENT")
        if h5.attrs.get("identity_key") != "(Zone,Idp)" or not bool(h5.attrs.get("conversion_complete")):
            raise NativeReconstructionError("typed HDF5 identity/conversion attributes are not closed")
        times = np.asarray(h5["time"][...], dtype="f8")
        if not np.allclose(times, expected_times, rtol=0.0, atol=2e-8):
            raise NativeReconstructionError("typed HDF5 times differ from CURRENT saved timeline")
        if not np.all(np.diff(times) > 0) or times[0] != 0.0 or times[-1] <= 4.0:
            raise NativeReconstructionError("typed HDF5 time axis is not strictly increasing/complete")
        ids = np.asarray(h5["particle_id"][...], dtype="<u4")
        zones = np.asarray(h5["particle_zone"][...], dtype="<i2")
        if not np.array_equal(ids, np.arange(particles, dtype="<u4")):
            raise NativeReconstructionError("typed particle_id axis is not the GenCase initial axis")
        initial_type = np.asarray(h5["initial_type"][...], dtype="i1")
        initial_mk = np.asarray(h5["initial_mk"][...], dtype="<i2")
        initial_mass = np.asarray(h5["initial_mass"][...], dtype="f4")
        selected_mask = (initial_type == int(cohort["initial_type_code"])) & np.isin(initial_mk, np.asarray(cohort["initial_mk_codes"], dtype="i2"))
        selected_indices = np.flatnonzero(selected_mask)
        if len(selected_indices) != int(cohort["expected_initial_fluid_count"]):
            raise NativeReconstructionError("typed Type/MK cohort count differs from frozen initial CSV")
        selected_ids_from_h5 = ids[selected_indices]
        selected_zones_from_h5 = zones[selected_indices]
        selected_mks_from_h5 = initial_mk[selected_indices]
        if _identity_hash(selected_zones_from_h5, selected_ids_from_h5) != expected_identity_sha:
            raise NativeReconstructionError("typed Type/MK identity axis differs from frozen CSV identity hash")
        if selected_ids is not None:
            assert selected_zones is not None and selected_mks is not None
            if (not np.array_equal(selected_ids_from_h5, selected_ids) or
                    not np.array_equal(selected_zones_from_h5, selected_zones) or
                    not np.array_equal(selected_mks_from_h5, selected_mks)):
                raise NativeReconstructionError("typed Type/MK identity axis differs from declared cohort vectors")
        selected_ids = selected_ids_from_h5
        selected_zones = selected_zones_from_h5
        selected_mks = selected_mks_from_h5
        selected_mass = initial_mass[selected_indices].astype("f8")
        if not np.isfinite(selected_mass).all() or np.any(selected_mass <= 0):
            raise NativeReconstructionError("typed initial fluid masses are not finite positive")
        if not math.isclose(float(selected_mass.sum()), float(request["initial_mass_denominator"]["denominator_kg"]), rel_tol=0.0, abs_tol=5e-8):
            raise NativeReconstructionError("typed initial fluid mass does not match frozen denominator")
        expected_mk_counts = {str(mk): int(np.sum(selected_mks == mk)) for mk in (1, 2, 3)}
        if expected_mk_counts != {str(k): int(v) for k, v in contract["fluid_mk_counts"].items()}:
            raise NativeReconstructionError("typed MK counts differ from frozen source cohort")
        initial_position = np.empty((len(selected_indices), 3), dtype="f4")
        trajectory_position = np.empty((frames, len(selected_indices), 3), dtype="f4")
        trajectory_velocity = np.empty_like(trajectory_position)
        trajectory_mass = np.empty((frames, len(selected_indices)), dtype="f4")
        trajectory_valid = np.empty((frames, len(selected_indices)), dtype=bool)
        # Read every full valid mask to prove lifecycle/missing IDs; selected
        # fields are loaded through contiguous spans for the v15 operator.
        report_frames = converter_report.get("lifecycle", {}).get("frame_summary")
        if not isinstance(report_frames, list) or len(report_frames) != frames:
            raise NativeReconstructionError("converter lifecycle frame summary is incomplete")
        for frame in range(frames):
            valid_full = np.asarray(h5["valid"][frame, ...], dtype=bool)
            missing_ids = ids[~valid_full]
            expected_summary = report_frames[frame]
            if int(expected_summary.get("active_particles", -1)) != int(valid_full.sum()) or int(expected_summary.get("missing_particles", -1)) != len(missing_ids):
                raise NativeReconstructionError(f"typed lifecycle count differs at frame {frame}")
            if hashlib.sha256(missing_ids.tobytes()).hexdigest() != expected_summary.get("missing_ids_sha256"):
                raise NativeReconstructionError(f"typed missing-ID lifecycle differs at frame {frame}")
            type_frame = np.asarray(h5["type"][frame, ...], dtype="i1")
            mk_frame = np.asarray(h5["mk"][frame, ...], dtype="<i2")
            if not np.array_equal(type_frame[valid_full], initial_type[valid_full]) or not np.array_equal(mk_frame[valid_full], initial_mk[valid_full]):
                raise NativeReconstructionError(f"typed frame identity fields changed at frame {frame}")
            if np.any(type_frame[~valid_full] != -1) or np.any(mk_frame[~valid_full] != -1):
                raise NativeReconstructionError(f"typed inactive type/MK fields are not explicit unknown at frame {frame}")
            for start in range(0, particles, 65536):
                stop = min(start + 65536, particles)
                active = valid_full[start:stop]
                for name in ("position", "velocity", "density", "mass", "pressure"):
                    value = np.asarray(h5[name][frame, start:stop])
                    if not np.isfinite(value[active]).all():
                        raise NativeReconstructionError(f"typed active {name} is nonfinite at frame {frame}")
                    if np.isfinite(value[~active]).any():
                        raise NativeReconstructionError(f"typed inactive {name} is falsely observed at frame {frame}")
            trajectory_valid[frame] = np.asarray(h5["valid"][frame, selected_indices], dtype=bool)
            trajectory_position[frame] = _selected_read(h5["position"], frame, selected_indices, width=3)
            trajectory_velocity[frame] = _selected_read(h5["velocity"], frame, selected_indices, width=3)
            trajectory_mass[frame] = _selected_read(h5["mass"], frame, selected_indices)
            if frame == 0:
                initial_position[:] = trajectory_position[0]
        trajectory = {
            "time": times,
            "position": trajectory_position,
            "velocity": trajectory_velocity,
            "mass": trajectory_mass,
            "valid": trajectory_valid,
            "initial_position": initial_position,
            "initial_type": initial_type[selected_indices],
            "initial_mk": initial_mk[selected_indices],
            "particle_zone": zones[selected_indices],
            "particle_id": ids[selected_indices],
            "initial_mass": selected_mass.astype("f4"),
        }
        for frame in range(frames):
            valid = trajectory_valid[frame]
            lifecycle.append({"frame": frame, "time_s": float(times[frame]),
                              "selected_active": int(valid.sum()),
                              "selected_missing": int((~valid).sum()),
                              "selected_missing_mass_kg": float(selected_mass[~valid].sum())})
    validation = {
        "schema": "ds02.stage2.f2-typed-output-validation.v2",
        "status": "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT",
        "source_current": {"path": current["path"], "sha256": current["sha256"],
                            "case_index": current["case_index"], "frames": frames,
                            "particles": particles},
        "identity_key": "(Zone,Idp)",
        "typed_shape": {"frames": frames, "particles": particles},
        "fluid_cohort": {"count": len(selected_indices), "type": int(cohort["initial_type_code"]),
                          "mks": [int(value) for value in cohort["initial_mk_codes"]],
                          "identity_sha256": expected_identity_sha,
                          "mass_sum_kg": float(selected_mass.sum()),
                          "mk_counts": {str(mk): int(np.sum(selected_mks == mk)) for mk in (1, 2, 3)}},
        "time": {"first_s": float(expected_times[0]), "last_s": float(expected_times[-1]),
                 "frame_count": frames, "strictly_increasing": True},
        "lifecycle": {"frame_count": frames, "selected_frame_summary": lifecycle,
                       "valid_mask_semantics": "inactive coordinate/velocity/mass/density/pressure are unknown NaN; ID/MK/type are retained only for active rows"},
        "raw_source_arrays_verified": len(raw_evidence["frames"]) == frames,
        "qualification": UNKNOWN_QUALIFICATION,
    }
    return trajectory, validation


def _run_labels(trajectory: Mapping[str, Any], request: Mapping[str, Any], output_dir: Path,
                *, run_evaluator: bool, predictions_path: Path | None) -> dict[str, Any]:
    modules = request["modules"]
    v15 = _load_module(Path(modules["v15_operator"]["path"]).expanduser().resolve(),
                       "_ds02_bound_v15_v2")
    v16 = _load_module(Path(modules["v16_operator"]["path"]).expanduser().resolve(),
                       "_ds02_bound_v16_v2")
    result = v15.replay_trajectory_v15(trajectory, request["v15_request"])
    reconstruction = {
        "schema": SCHEMA,
        "raw_tree_sha256": request["raw_binding"]["expected_raw_tree_sha256"],
        "typed_output_role": "raw_to_typed_reconstruction_output",
        "source_identity": "validated from raw decoder arrays, GenCase blocks, and CURRENT-bound CSV cohort",
        "typed_to_label_operator": "v15.replay_trajectory_v15",
        "v16_forward_operator": "pending_until_v15_result_has_F2_endpoint_scope"}
    result["reconstruction_binding"] = reconstruction
    # v15 keeps source binding to the frozen producer HDF5 for profile
    # compatibility.  The independent reconstruction proof is an additional
    # binding and never overwrites that historical producer identity.
    output_path = output_dir / "v15-reconstructed-label-result-v2.json"
    _write_new(output_path, result)
    report: dict[str, Any] = {"status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN",
                              "result": str(output_path), "result_sha256": sha256_file(output_path),
                              "operator": "v15.replay_trajectory_v15",
                              "qualification": UNKNOWN_QUALIFICATION}
    try:
        corrected = v16.forward_result(
            result,
            unknown_endpoint_mass_kg=float(request["initial_mass_denominator"]["later_missing_mass_kg"]),
            endpoint_scope="F2_S1_INITIAL_OUTSIDE_HALFSPACE_LATER_MISSING_ENDPOINTS_ONLY",
        )
    except Exception as error:  # v16 deliberately rejects unsupported scopes
        report["v16_forward"] = {"status": "PENDING_OR_REJECTED", "error": str(error)}
    else:
        corrected_path = output_dir / "v16-reconstructed-label-result-v2.json"
        _write_new(corrected_path, corrected)
        report["v16_forward"] = {"status": "COMPLETE_DEVELOPMENT_UNKNOWN", "result": str(corrected_path),
                                  "result_sha256": sha256_file(corrected_path),
                                  "gross_flux": "UNKNOWN_HIDDEN_WITHIN_SAVED_BRACKET_RECROSSINGS"}
    if run_evaluator:
        if predictions_path is None or not predictions_path.is_file():
            raise NativeReconstructionError("--run-evaluator requires a predictions JSON path")
        predictions = _load_json(predictions_path)
        profile = request["v15_request"].get("observer_profile")
        if not isinstance(profile, Mapping):
            raise NativeReconstructionError("v15 observer profile is required for evaluator")
        score = v15.evaluate_receiver_manual_predictions_v15(
            result, predictions, profile, frozen_request=request["v15_request"])
        score_path = output_dir / "v15-manual-evaluation-v2.json"
        _write_new(score_path, score)
        report["manual_evaluator"] = {"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                                      "result": str(score_path), "result_sha256": sha256_file(score_path)}
    else:
        report["manual_evaluator"] = {"status": "PENDING_PREDICTIONS", "scope": "v15 receiver evaluator is wired but no prediction file was supplied"}
    return report


def prepare_report(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _require_request(request, verify_sources=True)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file),
                     "request_schema": request.get("schema")},
        "source_closure": {"modules": bound["module_hashes"], "raw_data_root": str(bound["data_root"]),
                            "frame_count": len(bound["frames"]), "expected_raw_tree_sha256": bound["expected_tree"]},
        "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                "converter_invoked": False, "label_operator_invoked": False,
                                "model_invoked": False, "cfd_invoked": False,
                                "parent_stage2guard_required": True},
        "raw_to_typed": {"status": "PENDING_PARENT_IO_SLOT", "source_arrays": "all Part_*.bi4 required",
                         "partout_runparts_substitute": False},
        "typed_to_label": {"status": "PENDING_PARENT_IO_SLOT", "operator": "v15/v16 bound in request"},
        "resource_request": request.get("resource_request"),
        "qualification": UNKNOWN_QUALIFICATION,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def run(request_path: Path | str, output_dir: Path | str, *, io_slot_approved: bool = False,
        run_labels: bool = False, run_evaluator: bool = False,
        predictions_path: Path | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _require_request(request, verify_sources=io_slot_approved)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise NativeReconstructionError(f"refusing to use existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    if not io_slot_approved:
        report = {
            "schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "execution_boundary": {"raw_opened": False, "hdf5_opened": False, "converter_invoked": False,
                                    "label_operator_invoked": False, "model_invoked": False, "cfd_invoked": False},
            "source_closure": {"modules": bound["module_hashes"], "frame_count": len(bound["frames"]),
                                "expected_raw_tree_sha256": bound["expected_tree"]},
            "qualification": UNKNOWN_QUALIFICATION,
        }
        _write_new(target / "metadata-preflight-v2.json", report)
        return report
    started = time.monotonic()
    before = _resource_snapshot()
    converter_report, raw_evidence, typed_path = _capture_converter(request, bound, target, run_labels=run_labels)
    trajectory, typed_validation = _validate_and_load_typed(typed_path, request, converter_report, raw_evidence)
    label = None
    if run_labels:
        label = _run_labels(trajectory, request, target, run_evaluator=run_evaluator,
                             predictions_path=predictions_path)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "raw_to_typed": {"status": "COMPLETE", "converter_report": str(target / "raw-converter-report-v2.json"),
                         "converter_report_sha256": sha256_file(target / "raw-converter-report-v2.json"),
                         "raw_evidence": raw_evidence},
        "typed_output": {"path": str(typed_path), "bytes": typed_path.stat().st_size,
                          "sha256": sha256_file(typed_path), "validation": typed_validation},
        "typed_to_label": label or {"status": "NOT_RUN", "operator": "v15/v16 entrypoint is available via --run-labels"},
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "converter_invoked": True, "label_operator_invoked": bool(run_labels),
                                "model_invoked": False, "cfd_invoked": False,
                                "parent_stage2guard_required": True},
        "resource": {"wall_seconds": time.monotonic() - started,
                      "usage": {"before": before, "after": _resource_snapshot()}},
        "qualification": UNKNOWN_QUALIFICATION,
        "limitations": [
            "conversion and label evidence is development only; QI/QN/QE remain UNKNOWN",
            "raw PartOut/RunPARTs are cause evidence and are not typed array input",
            "v15 result retains the historical producer HDF5 source binding; reconstruction proof is an additional binding",
            "hidden recrossings and physical fate of later missing IDs remain UNKNOWN",
        ],
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(target / "raw-to-typed-to-label-report-v2.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--request", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--run-labels", action="store_true")
    run_parser.add_argument("--run-evaluator", action="store_true")
    run_parser.add_argument("--predictions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_report(args.request, args.output)
        else:
            result = run(args.request, args.output_dir, io_slot_approved=args.io_slot_approved,
                         run_labels=args.run_labels, run_evaluator=args.run_evaluator,
                         predictions_path=args.predictions)
    except (OSError, NativeReconstructionError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result.get("schema"), "status": result.get("status"),
                      "qualification": result.get("qualification")}, sort_keys=True,
                     default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
