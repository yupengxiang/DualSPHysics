#!/usr/bin/env python3
"""Bounded, source-preserving F5 fluid/boundary geometry diagnostic (V8).

This is a forward-only diagnostic after the consumed V7 support audits.  It
does not run GenCase or a solver and does not read BI4/HDF5.  The generated
XML, Fluid VTK and Bound VTK are worker-owned payloads: after the parent guard
has reserved the attempt, this worker hashes/stat-checks those files before
parsing them.  The report therefore distinguishes the worker's first payload
hash from the older V7 report; it does not claim that the parent hashed the
VTK payloads.

The report is deliberately diagnostic.  It records exact out-of-box fluid
coordinates, Idp mapping, axis/lattice summaries, clip-side counts, XML
fluid/bound selectors, AABB overlap, and exact float32 coordinate duplicates.
The latter is only a byte-level tuple diagnostic; it is not a contact,
penetration, or flux proof.  QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v4.py"
V7_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v7.py"
SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8"
REQUEST_SCHEMA = "ds02.request.v1"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic-contract.v8"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572
SOURCE_BOX_LOW = (0.01, -0.14, 0.01)
SOURCE_BOX_HIGH = (3.43, 0.14, 0.39)
SOURCE_CLIP_POINT = (2.0, 0.0, 0.0)
SOURCE_CLIP_VECTOR = (0.28, 0.0, -1.0)
MAX_EXAMPLES = 64


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    # Some imported helpers use dataclasses and require their module to be in
    # sys.modules while exec_module runs.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V4 = load_module("stage2_f5_geometry_v4_for_v8", V4_PATH)
V7 = load_module("stage2_f5_geometry_v7_for_v8", V7_PATH)
V3 = V4.V3
CLIP = V4.CLIP


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, scope: str = "small_input_hashed_by_worker") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": scope,
    }


def first_payload_record(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    """Hash a dynamic payload as the worker's first post-reservation action."""
    path = regular(path, label)
    before = path.stat()
    with path.open("rb") as handle:
        data = handle.read()
    after_read = path.stat()
    before_dict = {
        "bytes": int(before.st_size), "mtime_ns": int(before.st_mtime_ns),
        "ctime_ns": int(before.st_ctime_ns), "st_dev": int(before.st_dev),
        "st_ino": int(before.st_ino),
    }
    after_dict = {
        "bytes": int(after_read.st_size), "mtime_ns": int(after_read.st_mtime_ns),
        "ctime_ns": int(after_read.st_ctime_ns), "st_dev": int(after_read.st_dev),
        "st_ino": int(after_read.st_ino),
    }
    if before_dict != after_dict or len(data) != int(before.st_size):
        raise RuntimeError(f"dynamic payload changed while first-hashing: {path}")
    return data, {
        "path": str(path), "label": label, "bytes": len(data),
        "mtime_ns": before_dict["mtime_ns"], "ctime_ns": before_dict["ctime_ns"],
        "st_dev": before_dict["st_dev"], "st_ino": before_dict["st_ino"],
        "sha256": sha256_bytes(data),
        "content_scope": "worker_first_payload_hash_after_parent_reservation",
        "stat_before_read": before_dict, "stat_after_read": after_dict,
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V8 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"refuse to reuse temporary report: {temporary}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def _close(a: Any, b: Any, tol: float = 1e-12) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def validate_contract(contract: dict[str, Any], contract_path: Path, expected_sha: str,
                      q_path: Path, receipt_path: Path, q: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != SUPPORT_CONTRACT_SCHEMA:
        raise ValueError("V8 support contract schema mismatch")
    contract_record = record(contract_path, "V8 support contract")
    if expected_sha and contract_record["sha256"] != expected_sha:
        raise ValueError("V8 support contract SHA mismatch")
    for key, path in (("gencase_request", q_path), ("gencase_receipt", receipt_path)):
        item = contract.get(key)
        if not isinstance(item, dict) or Path(str(item.get("path", ""))).expanduser().resolve() != path.resolve():
            raise ValueError(f"V8 contract {key} path mismatch")
        if item.get("sha256") != sha256(path):
            raise ValueError(f"V8 contract {key} SHA mismatch")
    binding = contract.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("V8 support contract has no source_binding")
    q_binding = q.get("source_binding")
    if not isinstance(q_binding, dict):
        raise ValueError("GenCase request has no source_binding")
    for key in ("grid", "dp_m", "pointref_m", "continuous_region_mass_kg", "old_sample_mass_kg",
                "continuous_box_and_clip_unchanged", "controls_and_motion_unchanged", "mass_rescale"):
        if binding.get(key) != q_binding.get(key):
            raise ValueError(f"V8 source binding mismatch: {key}")
    closure = contract.get("parent_v8_input_closure")
    if not isinstance(closure, dict):
        raise ValueError("V8 contract has no parent_v8_input_closure")
    if closure.get("deferred_input_files_used") is not False:
        raise ValueError("V8 contract cannot use deferred input files")
    if closure.get("parent_v8_does_not_hash_worker_owned_vtk") is not True:
        raise ValueError("V8 contract must state parent does not hash worker VTK")
    if closure.get("worker_first_payload_hash_after_parent_reservation") is not True:
        raise ValueError("V8 contract lacks first worker payload hash claim")
    if closure.get("vtk_sha_authority") != "V8 worker first payload full SHA/stat after parent reservation":
        raise ValueError("V8 VTK SHA authority is not explicit")
    worker_hashes = contract.get("worker_owned_input_hashes")
    if not isinstance(worker_hashes, dict) or worker_hashes.get("hash_status") != "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES":
        raise ValueError("V8 worker-owned payload hash scope is invalid")
    return {
        "path": contract_record["path"], "sha256": contract_record["sha256"],
        "bytes": contract_record["bytes"], "pre_post_stat_checked": True,
        "deferred_input_files_used": False,
        "parent_v8_does_not_hash_worker_owned_vtk": True,
        "worker_first_payload_hash_after_parent_reservation": True,
        "vtk_sha_authority": closure["vtk_sha_authority"],
    }


def _aabb(points: np.ndarray) -> dict[str, Any]:
    if points.size == 0:
        return {"count": 0, "low_m": None, "high_m": None}
    return {"count": int(points.shape[0]), "low_m": [float(v) for v in points.min(axis=0)], "high_m": [float(v) for v in points.max(axis=0)]}


def _aabb_overlap(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if not a.get("low_m") or not b.get("low_m"):
        return {"intersects": False, "status": "UNKNOWN_EMPTY_AABB"}
    low = np.maximum(np.asarray(a["low_m"], dtype=float), np.asarray(b["low_m"], dtype=float))
    high = np.minimum(np.asarray(a["high_m"], dtype=float), np.asarray(b["high_m"], dtype=float))
    extent = high - low
    return {"intersects": bool(np.all(extent >= 0.0)), "overlap_low_m": low.tolist(), "overlap_high_m": high.tolist(), "overlap_extent_m": extent.tolist(), "scope": "AABB_ONLY_NO_CONTACT_OR_FLUX_CREDIT"}


def _box_overlap_pairs(fluid_boxes: list[dict[str, Any]], bound_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for fi, fluid in enumerate(fluid_boxes):
        fa = {"low_m": fluid["low_m"], "high_m": fluid["high_m"]}
        for bi, bound in enumerate(bound_boxes):
            ba = {"low_m": bound["low_m"], "high_m": bound["high_m"]}
            pairs.append({"fluid_box_index": fi, "boundary_box_index": bi, **_aabb_overlap(fa, ba)})
    return pairs


def _float32_keys(points: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(points, dtype=np.float32)
    words = values.view(np.uint32).reshape((-1, 3))
    keys = np.empty(values.shape[0], dtype=[("x", "<u4"), ("y", "<u4"), ("z", "<u4")])
    keys["x"], keys["y"], keys["z"] = words[:, 0], words[:, 1], words[:, 2]
    return keys


def exact_float32_overlap(fluid: np.ndarray, bound: np.ndarray, fluid_ids: np.ndarray) -> dict[str, Any]:
    """Find equal float32 coordinate tuples without claiming physical contact."""
    try:
        bkeys = np.sort(_float32_keys(bound), order=("x", "y", "z"))
        fkeys = _float32_keys(fluid)
        match_mask = np.zeros(fkeys.shape[0], dtype=bool)
        chunk_size = 250_000
        for start in range(0, fkeys.shape[0], chunk_size):
            stop = min(start + chunk_size, fkeys.shape[0])
            chunk = fkeys[start:stop]
            positions = np.searchsorted(bkeys, chunk)
            valid = positions < bkeys.shape[0]
            if np.any(valid):
                valid_indices = np.flatnonzero(valid)
                candidates = bkeys[positions[valid]]
                wanted = chunk[valid]
                equal = ((candidates["x"] == wanted["x"]) &
                         (candidates["y"] == wanted["y"]) &
                         (candidates["z"] == wanted["z"]))
                match_mask[start + valid_indices] = equal
        matched = np.flatnonzero(match_mask)
        unique_matched = np.unique(fkeys[matched]).size if matched.size else 0
        examples = [{"fluid_index": int(index), "idp": int(fluid_ids[index]), "point_m": [float(v) for v in fluid[index]]} for index in matched[:MAX_EXAMPLES]]
        return {
            "status": "COMPUTED_EXACT_FLOAT32_TUPLE_ONLY",
            "fluid_point_count_with_exact_boundary_tuple": int(matched.size),
            "unique_exact_tuple_count": int(unique_matched),
            "examples": examples,
            "scope": "byte-equal float32 XYZ only; no contact, penetration, ownership, or flux inference",
        }
    except Exception as exc:  # bounded diagnostic must make inability explicit
        return {"status": "UNKNOWN_EXACT_FLOAT32_TUPLE_CHECK_ERROR", "reason": f"{type(exc).__name__}: {exc}", "scope": "no physical overlap credit"}


def _outliers(points: np.ndarray, ids: np.ndarray, box: dict[str, Any], dp: float) -> dict[str, Any]:
    low = np.asarray(box["low_m"], dtype=np.float64)
    high = np.asarray(box["high_m"], dtype=np.float64)
    tol = max(1e-7, float(dp) * 1e-5)
    violation = np.maximum(low - points, 0.0) + np.maximum(points - high, 0.0)
    out = np.any(violation > tol, axis=1)
    axis_names = "xyz"
    axis_counts = {axis_names[i]: int((violation[:, i] > tol).sum()) for i in range(3)}
    max_delta = {axis_names[i]: float(violation[:, i].max()) for i in range(3)}
    indices = np.flatnonzero(out)
    examples = []
    for index in indices[:MAX_EXAMPLES]:
        examples.append({"fluid_index": int(index), "idp": int(ids[index]), "point_m": [float(v) for v in points[index]], "outside_axes": [axis_names[i] for i in range(3) if violation[index, i] > tol], "positive_excess_m": [float(v) for v in violation[index]]})
    return {"box_low_m": box["low_m"], "box_high_m": box["high_m"], "tolerance_m": tol, "outside_count": int(indices.size), "axis_outside_count": axis_counts, "max_positive_excess_m": max_delta, "examples": examples}


def _clip_relation(points: np.ndarray, ids: np.ndarray, point: tuple[float, float, float], vector: tuple[float, float, float], dp: float) -> dict[str, Any]:
    values = (points - np.asarray(point, dtype=float)) @ np.asarray(vector, dtype=float)
    tol = max(1e-7, float(dp) * 1e-5)
    outside = np.flatnonzero(values > tol)
    near = np.flatnonzero(np.abs(values) <= tol)
    return {
        "predicate": "n.(x-point)<=0", "point_m": list(point), "vector": list(vector), "tolerance_m": tol,
        "outside_count": int(outside.size), "near_count": int(near.size), "min_value": float(values.min()), "max_value": float(values.max()),
        "outside_examples": [{"fluid_index": int(i), "idp": int(ids[i]), "value": float(values[i]), "point_m": [float(v) for v in points[i]]} for i in outside[:MAX_EXAMPLES]],
        "near_examples": [{"fluid_index": int(i), "idp": int(ids[i]), "value": float(values[i])} for i in near[:MAX_EXAMPLES]],
        "scope": "plane-side diagnostic only; no flow/flux inference",
    }


def _block_diagnostics(points: np.ndarray, ids: np.ndarray, blocks: list[dict[str, Any]], box: dict[str, Any], dp: float, clip_point: tuple[float, float, float], clip_vector: tuple[float, float, float]) -> list[dict[str, Any]]:
    result = []
    for block in blocks:
        mask = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
        subset = points[mask]
        subset_ids = ids[mask]
        relation = _outliers(subset, subset_ids, box, dp)
        plane = _clip_relation(subset, subset_ids, clip_point, clip_vector, dp)
        result.append({**block, "mapped_point_count": int(subset.shape[0]), "axis_summary": V3.axis_summary(subset), "box_relation": relation, "clip_relation": plane})
    return result


def _selector_snapshot(xml: dict[str, Any]) -> dict[str, Any]:
    return {
        "fluid_boxes": xml.get("fluid_boxes", []), "boundary_boxes": xml.get("boundary_boxes", []),
        "operations": xml.get("operations", []), "particles_summary": xml.get("particles_summary"),
        "fluid_blocks": xml.get("fluid_blocks", []), "fluid_count": xml.get("fluid_count"),
    }


def _validate_frozen_source(source: dict[str, Any], candidate: dict[str, Any], clip: dict[str, Any]) -> None:
    if source.get("fluid_boxes") != candidate.get("fluid_boxes") or source.get("boundary_boxes") != candidate.get("boundary_boxes"):
        raise ValueError("candidate changed source fluid/boundary selector geometry")
    fluid_boxes = source.get("fluid_boxes") or []
    if not fluid_boxes:
        raise ValueError("source has no fluid selector box")
    box = fluid_boxes[0]
    if tuple(round(float(v), 12) for v in box.get("low_m", [])) != tuple(round(v, 12) for v in SOURCE_BOX_LOW) or tuple(round(float(v), 12) for v in box.get("high_m", [])) != tuple(round(v, 12) for v in SOURCE_BOX_HIGH):
        raise ValueError("source fluid box differs from frozen F5 owner box")
    if tuple(round(float(v), 12) for v in clip.get("point", [])) != SOURCE_CLIP_POINT or tuple(round(float(v), 12) for v in clip.get("vector", [])) != SOURCE_CLIP_VECTOR:
        raise ValueError("source official clip differs from frozen point/vector")


def _point_cloud_overlap(fluid: np.ndarray, bound: np.ndarray) -> dict[str, Any]:
    return {"fluid_aabb": _aabb(fluid), "boundary_aabb": _aabb(bound), "aabb_intersection": _aabb_overlap(_aabb(fluid), _aabb(bound))}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    q_path = regular(args.gencase_request, "F5 GenCase request")
    receipt_path = regular(args.receipt, "F5 GenCase receipt")
    contract_path = regular(args.support_contract, "F5 V8 support contract")
    q = load_json(q_path, "F5 GenCase request")
    receipt = load_json(receipt_path, "F5 GenCase receipt")
    identity = V7.validate_gencase_request(q, receipt)
    contract_info = validate_contract(load_json(contract_path, "F5 V8 support contract"), contract_path, args.expected_support_contract_sha or "", q_path, receipt_path, q)
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    dynamic_paths = {"generated_xml": regular(args.generated_xml, "generated XML"), "fluid_vtk": regular(args.fluid_vtk, "generated Fluid VTK"), "bound_vtk": regular(args.bound_vtk, "generated Bound VTK")}
    for label, path in dynamic_paths.items():
        if path.parent != output_root:
            raise ValueError(f"{label} is outside the terminal receipt output_root")
    # This block is intentionally before any dynamic XML/VTK parser call.
    first_payload = {}
    payload_bytes = {}
    for label, path in dynamic_paths.items():
        payload_bytes[label], first_payload[label] = first_payload_record(path, label)
    expected_dynamic = {"generated_xml": args.expected_generated_xml_sha}
    for key, expected in expected_dynamic.items():
        if expected and first_payload[key]["sha256"] != expected:
            raise ValueError(f"{key} SHA mismatch after worker reservation")
    # V4 preserves the existing control/mass checks and qualification limits;
    # this call is deliberately after the first payload hash block.
    base = V4.build_report(args)
    generated = V3.parse_xml(dynamic_paths["generated_xml"])
    source = V3.parse_xml(args.source_def.resolve())
    candidate = V3.parse_xml(args.candidate_def.resolve())
    clip = CLIP.parse_clip(args.source_def.resolve())
    _validate_frozen_source(source, candidate, clip)
    points, fluid_meta = V3.read_vtk_fluid(dynamic_paths["fluid_vtk"], int(generated["fluid_count"]), generated["fluid_blocks"])
    bound_points, bound_meta = V3.read_vtk_points(dynamic_paths["bound_vtk"])
    fluid_box = generated.get("fluid_boxes", [])[0] if generated.get("fluid_boxes") else source["fluid_boxes"][0]
    dp = float(generated["dp_m"])
    mapped_ids = fluid_meta["mapped_ids"]
    box_diag = _outliers(points, mapped_ids, fluid_box, dp)
    clip_diag = _clip_relation(points, mapped_ids, tuple(clip["point"]), tuple(clip["vector"]), dp)
    block_diag = _block_diagnostics(points, mapped_ids, generated["fluid_blocks"], fluid_box, dp, tuple(clip["point"]), tuple(clip["vector"]))
    generated_fluid_boxes = generated.get("fluid_boxes", [])
    generated_bound_boxes = generated.get("boundary_boxes", [])
    final_paths = {**dynamic_paths, "receipt": receipt_path}
    dynamic_post = {key: record(path, label, scope="worker_post_parse_full_sha_stat") for key, (label, path) in {"generated_xml": ("generated XML", dynamic_paths["generated_xml"]), "fluid_vtk": ("generated Fluid VTK", dynamic_paths["fluid_vtk"]), "bound_vtk": ("generated Bound VTK", dynamic_paths["bound_vtk"]), "receipt": ("GenCase receipt", receipt_path)}.items()}
    for key in dynamic_paths:
        if first_payload[key]["sha256"] != dynamic_post[key]["sha256"] or any(first_payload[key].get(field) != dynamic_post[key].get(field) for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")):
            raise RuntimeError(f"dynamic payload changed during V8 diagnostic: {key}")
    # The V3 path parser rereads files; keep this honest rather than claiming
    # that the first in-memory payload buffer was the parser's byte source.
    base["schema"] = SCHEMA
    base["status"] = "COMPLETED_F5_YHALF_GEOMETRY_IDP_OVERLAP_DIAGNOSTIC_V8"
    base["inputs"]["dynamic_pre"] = {**first_payload, "receipt": record(receipt_path, "GenCase receipt", scope="small_input_hashed_by_worker")}
    base["inputs"]["dynamic_post"] = dynamic_post
    base["inputs"]["dynamic_first_payload_hash_order"] = list(dynamic_paths)
    base["inputs"]["pre_post_equal"] = True
    base["geometry_diagnostic"] = {
        "generated_fluid_axis_summary": V3.axis_summary(points),
        "generated_bound_axis_summary": V3.axis_summary(bound_points),
        "fluid_vtk_idp_mapping": fluid_meta.get("idp_mapping"),
        "fluid_vtk_idp_scalar": fluid_meta.get("idp_scalar"),
        "bound_vtk_idp": "UNKNOWN_NOT_PRESENT_IN_BOUND_READER",
        "fluid_box_relation": box_diag,
        "clip_plane_relation": clip_diag,
        "per_mkfluid_blocks": block_diag,
        "fluid_boundary_xml_aabb_pairs": _box_overlap_pairs(generated_fluid_boxes, generated_bound_boxes),
        "fluid_boundary_point_cloud": _point_cloud_overlap(points, bound_points),
        "exact_float32_coordinate_overlap": exact_float32_overlap(points, bound_points, mapped_ids),
        "selector_and_operation_trace": {
            "source": _selector_snapshot(source), "candidate": _selector_snapshot(candidate), "generated": _selector_snapshot(generated),
            "source_candidate_controls_equal": source.get("parameters") == candidate.get("parameters"),
            "source_candidate_boundary_boxes_equal": source.get("boundary_boxes") == candidate.get("boundary_boxes"),
        },
        "interpretation": {
            "out_of_box_points_are_not_silently_dropped": True,
            "outside_points_do_not_prove_flux_or_contact": True,
            "aabb_and_exact_tuple_overlap_do_not_prove_physical_contact": True,
            "bound_idp_mapping": "UNKNOWN_NOT_PRESENT_IN_BOUND_READER",
        },
    }
    base["source_closure"] = {
        "parent_v8_does_not_hash_dynamic_payload": True,
        "worker_first_payload_hash_after_parent_reservation": True,
        "worker_first_payload_hash_scope": "generated XML then Fluid VTK then Bound VTK, before V3 parser",
        "worker_dynamic_pre_post_sha_stat_equal": True,
        "exact_parser_consumed_byte_hash": "NOT_COMPUTED_BY_V8_READER; parser rereads stable paths after first hash",
        "dynamic_payload_paths_contained_in_receipt_output_root": True,
        "support_contract": contract_info,
    }
    base["candidate_contract"] = {
        "continuous_owner_box_low_m": list(SOURCE_BOX_LOW), "continuous_owner_box_high_m": list(SOURCE_BOX_HIGH),
        "official_clip_point_m": list(SOURCE_CLIP_POINT), "official_clip_vector": list(SOURCE_CLIP_VECTOR),
        "box_and_clip_frozen": True, "mass_rescale": False, "continuous_mass_kg": CONTINUOUS_MASS_KG,
        "old_discrete_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG, "old_discrete_sample_is_diagnostic_only": True,
    }
    base["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "bounded geometry/Idp/selector diagnostic only; no physical contact, flux, solver, or scientific qualification"}
    return base


def self_test() -> dict[str, Any]:
    # Tiny in-memory tuple overlap catches endian/structured-key regressions
    # without touching any campaign payload.
    fluid = np.asarray([[1.0, 0.0, 0.0], [1.1, 0.0, 0.0]], dtype=np.float32)
    bound = np.asarray([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32)
    result = exact_float32_overlap(fluid, bound, np.asarray([10, 11], dtype=np.uint32))
    if result.get("fluid_point_count_with_exact_boundary_tuple") != 1:
        raise AssertionError(result)
    box = {"low_m": [0.0, 0.0, 0.0], "high_m": [1.0, 1.0, 1.0]}
    out = _outliers(fluid, np.asarray([10, 11], dtype=np.uint32), box, 0.01)
    if out["outside_count"] != 1 or out["axis_outside_count"]["x"] != 1:
        raise AssertionError(out)
    return {"status": "PASS", "schema": SCHEMA, "tiny_exact_float32_overlap": "PASS", "tiny_outlier_axis_diagnostic": "PASS", "solver_started": False, "bi4_read": False, "hdf5_read": False, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt", "support-contract"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all terminal/static paths, --support-contract and --output are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "grid": report["grid"], "output": str(args.output.resolve()), "fluid_outside": report["geometry_diagnostic"]["fluid_box_relation"]["outside_count"], "exact_tuple_overlap": report["geometry_diagnostic"]["exact_float32_coordinate_overlap"]["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
