#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Guarded frame-0 support audit for the six existing F6 GenCase products.

The request builder records only small XML/receipt/proof metadata.  The
native BI4 and Fluid/Bound VTK files remain deferred until the parent runtime
has reserved the task.  This worker then checks the source file before and
after every read, uses the official ``bi4_dump`` adapter for one frame, and
keeps four different masses separate:

* the explicit XML continuous fluid owner volume times density;
* the decoded native fluid sample mass;
* the decoded floating-particle sample mass; and
* the XML rigid ``massbody``.

It is an initial-condition diagnostic only.  It does not run a solver,
infer a world-axis calibration, or grant QI/QN/QE credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

import stage2_native_physical_observer_v2 as native
import stage2_f1_native_selected_observer_v1 as calibrated


SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v2"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v2"
PASS_STATUS = "COMPLETE_F6_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_V2_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V2"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_VTK_BYTES = 512 * 1024 * 1024


class AuditFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _expected_stat(record: dict[str, Any], label: str) -> dict[str, int] | None:
    value = record.get("stat_at_prepare", record.get("stat"))
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} stat_at_prepare is not an object")
    missing = [key for key in STAT_FIELDS if key not in value]
    if missing:
        raise AuditFailure(f"{label} stat_at_prepare missing {missing}")
    return {key: int(value[key]) for key in STAT_FIELDS}


def _verify_record_stat(path: Path, record: dict[str, Any], label: str, actual: dict[str, int]) -> None:
    expected = _expected_stat(record, label)
    if expected is not None and expected != actual:
        raise AuditFailure(f"{label} changed from prepared stat: expected {expected}, got {actual}")
    if record.get("bytes") is not None and int(record["bytes"]) != actual["bytes"]:
        raise AuditFailure(f"{label} byte count differs from manifest")


def _stable_json(record: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_JSON_BYTES:
        raise AuditFailure(f"{label} exceeds bounded JSON read")
    digest, size = _sha(path)
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or digest != hashlib.sha256(raw).hexdigest() or size != len(raw):
        raise AuditFailure(f"{label} was not stable across its read")
    _verify_record_stat(path, record, label, after)
    if record.get("sha256") and str(record["sha256"]).lower() != digest:
        raise AuditFailure(f"{label} SHA differs from manifest")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": digest, "bytes": size, "stat": after, "stable_read": True}


def _stable_xml(record: dict[str, Any], label: str) -> tuple[ET.Element, dict[str, Any]]:
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_XML_BYTES:
        raise AuditFailure(f"{label} exceeds bounded XML read")
    digest, size = _sha(path)
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or digest != hashlib.sha256(raw).hexdigest() or size != len(raw):
        raise AuditFailure(f"{label} was not stable across its read")
    _verify_record_stat(path, record, label, after)
    if record.get("sha256") and str(record["sha256"]).lower() != digest:
        raise AuditFailure(f"{label} SHA differs from manifest")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AuditFailure(f"{label} XML parse failed") from exc
    return root, {"path": str(path), "sha256": digest, "bytes": size, "stat": after, "stable_read": True}


def _deferred_read(record: dict[str, Any], label: str, *, parse: str) -> tuple[Any, dict[str, Any]]:
    """Read one deferred payload with pre-SHA, content read, and post-SHA."""
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_VTK_BYTES and parse == "vtk":
        raise AuditFailure(f"{label} exceeds bounded VTK read")
    if record.get("bytes") is not None and int(record["bytes"]) != before["bytes"]:
        raise AuditFailure(f"{label} bytes differ before worker read")
    expected = record.get("known_sha256") or record.get("sha256")
    pre_sha, pre_bytes = _sha(path)
    if expected and str(expected).lower() != pre_sha:
        raise AuditFailure(f"{label} known SHA differs before read")
    if parse == "vtk":
        payload = path.read_bytes()
    elif parse == "bi4":
        payload = None
    else:
        raise AuditFailure(f"unknown deferred parser {parse}")
    post_sha, post_bytes = _sha(path)
    after = _stat(path)
    if before != after or pre_sha != post_sha or pre_bytes != post_bytes:
        raise AuditFailure(f"{label} changed during worker read")
    if expected and str(expected).lower() != post_sha:
        raise AuditFailure(f"{label} known SHA differs after read")
    _verify_record_stat(path, record, label, after)
    return payload, {"path": str(path), "sha256": post_sha, "bytes": post_bytes,
                     "stat_before": before, "stat_after": after,
                     "stable_read": True, "pre_post_sha_equal": True,
                     "content_scope": parse}


def _deferred_bi4_pre(record: dict[str, Any], label: str) -> dict[str, Any]:
    """Take the guarded BI4 hash/stat immediately before decoder entry.

    V1 performed a pre and post hash before calling the decoder.  That proves
    only that the file was unchanged during hashing, not during the decoder's
    actual read.  V2 keeps the pre state open until the decoder returns.
    """
    path = _regular(Path(str(record.get("path", ""))), label)
    before = _stat(path)
    if before["bytes"] > MAX_VTK_BYTES:
        raise AuditFailure(f"{label} exceeds bounded native read")
    if record.get("bytes") is not None and int(record["bytes"]) != before["bytes"]:
        raise AuditFailure(f"{label} bytes differ before decoder")
    expected = record.get("known_sha256") or record.get("sha256")
    pre_sha, pre_bytes = _sha(path)
    if expected and str(expected).lower() != pre_sha:
        raise AuditFailure(f"{label} known SHA differs before decoder")
    _verify_record_stat(path, record, label, before)
    return {"path": str(path), "pre_sha256": pre_sha, "pre_bytes": pre_bytes,
            "stat_before": before, "expected_sha256": expected}


def _deferred_bi4_post(pre: dict[str, Any], record: dict[str, Any], label: str,
                       frame_source: dict[str, Any] | None) -> dict[str, Any]:
    """Hash/stat the BI4 after decoder return and compare decoder's own file SHA."""
    path = Path(pre["path"])
    post_sha, post_bytes = _sha(path)
    after = _stat(path)
    if pre["stat_before"] != after or pre["pre_sha256"] != post_sha or pre["pre_bytes"] != post_bytes:
        raise AuditFailure(f"{label} changed during decoder read")
    expected = pre.get("expected_sha256")
    if expected and str(expected).lower() != post_sha:
        raise AuditFailure(f"{label} known SHA differs after decoder")
    _verify_record_stat(path, record, label, after)
    decoder_sha = frame_source.get("sha256") if isinstance(frame_source, dict) else None
    decoder_bytes = frame_source.get("bytes") if isinstance(frame_source, dict) else None
    if not decoder_sha or decoder_bytes is None:
        raise AuditFailure(f"{label} decoder did not expose source-file SHA and bytes")
    if decoder_sha and str(decoder_sha).lower() != post_sha:
        raise AuditFailure(f"{label} decoder frame SHA differs from guarded post SHA")
    if decoder_bytes is not None and int(decoder_bytes) != post_bytes:
        raise AuditFailure(f"{label} decoder frame bytes differ from guarded post bytes")
    return {"path": str(path), "sha256": post_sha, "bytes": post_bytes,
            "stat_before": pre["stat_before"], "stat_after": after,
            "stable_read": True, "pre_post_sha_equal": True,
            "pre_sha256": pre["pre_sha256"], "post_sha256": post_sha,
            "decoder_frame_sha256": decoder_sha, "decoder_frame_bytes": decoder_bytes,
            "decoder_frame_sha_matches_post": bool(decoder_sha) and str(decoder_sha).lower() == post_sha,
            "content_scope": "bi4_frame_decoder_bounded"}


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def _float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise AuditFailure(f"{label} is non-finite")
    return result


def _vec(node: ET.Element | None, label: str, required: bool = True) -> list[float] | None:
    if node is None:
        if required:
            raise AuditFailure(f"{label} is missing")
        return None
    return [_float(node.get(axis), f"{label}.{axis}") for axis in ("x", "y", "z")]


def _xml_geometry(root: ET.Element, xml_path: Path, label: str) -> dict[str, Any]:
    # Reuse the official observer's typed particle-range parser.  The XML is a
    # bounded small input and has already passed the stable hash check; the
    # second read is intentional and remains inside the guarded worker.
    try:
        source = native.parse_source_xml(xml_path)
    except Exception as exc:
        raise AuditFailure(f"{label} typed XML ranges are unsupported: {exc}") from exc
    main = next((x for x in root.iter() if _tag(x) == "mainlist"), None)
    if main is None:
        raise AuditFailure(f"{label} has no geometry mainlist")
    active_fluid: int | None = None
    active_bound: int | None = None
    fluid_boxes: list[dict[str, Any]] = []
    floating_boxes: list[dict[str, Any]] = []
    for node in main:
        kind = _tag(node)
        if kind == "setmkfluid":
            active_fluid = int(node.get("mk", "-1")); active_bound = None
        elif kind == "setmkbound":
            active_bound = int(node.get("mk", "-1")); active_fluid = None
        elif kind == "drawbox":
            fill = next((child.text or "" for child in node if _tag(child) == "boxfill"), "").strip()
            if fill != "solid":
                continue
            point = next((child for child in node if _tag(child) == "point"), None)
            size = next((child for child in node if _tag(child) == "size"), None)
            if point is None or size is None:
                continue
            low = _vec(point, f"{label}.drawbox.point")
            extent = _vec(size, f"{label}.drawbox.size")
            assert low is not None and extent is not None
            if any(value <= 0 for value in extent):
                raise AuditFailure(f"{label} has non-positive drawbox size")
            box = {"mk": active_fluid if active_fluid is not None else active_bound,
                   "low_m": low, "size_m": extent,
                   "high_m": [low[i] + extent[i] for i in range(3)],
                   "volume_m3": extent[0] * extent[1] * extent[2],
                   "comment": node.get("cmt")}
            if active_fluid is not None:
                fluid_boxes.append(box)
            if active_bound == 50:
                floating_boxes.append(box)
    if len(fluid_boxes) != 1:
        raise AuditFailure(f"{label} expected one solid fluid drawbox, got {len(fluid_boxes)}")
    if len(floating_boxes) != 1:
        raise AuditFailure(f"{label} expected one solid floating drawbox, got {len(floating_boxes)}")
    fluid = fluid_boxes[0]
    density = next((node.get("value") for node in root.iter() if _tag(node) == "rhop0"), None)
    body_mass = next((node.get("value") for node in root.iter() if _tag(node) == "massbody"), None)
    return {"fluid_drawbox": fluid, "floating_drawbox": floating_boxes[0],
            "continuous_owner_mass_kg": _float(density, f"{label}.rhop0") * fluid["volume_m3"],
            "continuous_owner_volume_m3": fluid["volume_m3"],
            "rhop0_kg_m3": _float(density, f"{label}.rhop0"),
            "massbody_kg": _float(body_mass, f"{label}.massbody") if body_mass is not None else None,
            "typed_source": source}


def _parse_vtk(payload: bytes, label: str) -> dict[str, Any]:
    match = re.search(rb"\bPOINTS\s+(\d+)\s+(float|double)\s*\n", payload)
    if not match:
        raise AuditFailure(f"{label} VTK has no binary POINTS header")
    count = int(match.group(1)); dtype_name = match.group(2).decode("ascii")
    dtype = np.dtype(">f4" if dtype_name == "float" else ">f8")
    start = match.end(); needed = count * 3 * dtype.itemsize
    if start + needed > len(payload):
        raise AuditFailure(f"{label} VTK POINTS payload is truncated")
    raw = np.frombuffer(payload, dtype=dtype, count=count * 3, offset=start)
    if not np.isfinite(raw).all():
        raise AuditFailure(f"{label} VTK POINTS contains non-finite values")
    # Official VTK is big-endian.  Keep only a bounded summary; no payload is
    # copied into the result and no assumption about a continuous boundary is
    # made from the VTK envelope.
    positions = raw.reshape(count, 3).astype(np.float64, copy=False)
    return {"point_count": count, "dtype": dtype_name, "finite": True,
            "min_m": np.min(positions, axis=0).tolist() if count else None,
            "max_m": np.max(positions, axis=0).tolist() if count else None}


def _scalar(info: dict[str, Any], name: str, required: bool = False) -> float | None:
    norm = name.replace("_", "").lower()
    for key, value in info.items():
        if str(key).replace("_", "").lower() == norm:
            try:
                result = float(value)
            except (TypeError, ValueError):
                break
            if not math.isfinite(result):
                break
            return result
    if required:
        raise AuditFailure(f"decoder did not expose finite {name}")
    return None


def _native_case(case: dict[str, Any], source_xml: ET.Element, xml_path: Path, attempt_root: Path) -> dict[str, Any]:
    sid = str(case["sentinel_id"]); grid = str(case["grid"])
    label = f"{sid}/{grid}"
    source = _xml_geometry(source_xml, xml_path, label)
    source_info = source["typed_source"]
    if abs(source["continuous_owner_mass_kg"] - 4851.988676250775) > 1.0e-9:
        raise AuditFailure(f"{label} continuous owner XML mass differs from frozen F6 owner")
    if source["massbody_kg"] is not None and abs(source["massbody_kg"] - 128.0) > 1.0e-9:
        raise AuditFailure(f"{label} XML massbody differs from frozen physical rigid mass")
    # Verify the exact XML path is also the XML used to derive the typed ranges.
    bi4 = case["deferred"]["native_bi4"]
    bi4_pre = _deferred_bi4_pre(bi4, f"{label} native frame-0 BI4")
    decoder = Path(str(case["decoder"]["path"])).expanduser().absolute()
    decoder_source = Path(str(case["decoder_source"]["path"])).expanduser().absolute()
    if not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise AuditFailure(f"{label} decoder is not executable")
    contract = native.decoder_source_contract(decoder_source)
    if not contract.get("status", "").startswith("PASS_"):
        raise AuditFailure(f"{label} decoder source contract is not proven")
    scratch = attempt_root / "scratch" / f"{sid}-{grid}"
    scratch.mkdir(parents=True, exist_ok=True)
    decode_error: BaseException | None = None
    frame: dict[str, Any] | None = None
    try:
        frame = native.decode_frame(Path(str(bi4["path"])), decoder, scratch, 0)
    except BaseException as exc:
        decode_error = exc
    finally:
        # This post check deliberately runs after decoder return (or failure),
        # while the pre state remains live.  It is the V2 integrity boundary.
        try:
            bi4_record = _deferred_bi4_post(bi4_pre, bi4, f"{label} native frame-0 BI4",
                                            frame.get("source_file") if isinstance(frame, dict) else None)
        finally:
            # The official observer removes its per-frame directory, but keep
            # the worker-owned parent bounded even when the post-check fails.
            shutil.rmtree(scratch, ignore_errors=True)
    if decode_error is not None:
        raise decode_error
    assert frame is not None
    ids = frame["ids"]; position = frame["position"]; velocity = frame["velocity"]
    kinds, relative, absolute = native.assign_particle_ranges(ids, source_info["blocks"])
    field_metadata = {**frame.get("metadata", {}), **frame.get("info", {})}
    native_massfluid = calibrated._native_scalar("MassFluid", frame.get("metadata", {}), frame.get("info", {}), required=True)
    native_massbound = calibrated._native_scalar("MassBound", frame.get("metadata", {}), frame.get("info", {}), required=False)
    native_dp = calibrated._native_scalar("Dp", frame.get("metadata", {}), frame.get("info", {}), required=True)
    mf = float(native_massfluid["value"]); mb_value = native_massbound.get("value")
    mb = float(mb_value) if isinstance(mb_value, (int, float)) else None
    native_counts, _, _, _ = calibrated._role_counts(ids, source_info)
    counts = {kind: int(native_counts.get(kind, 0)) for kind in ("fluid", "fixed", "moving", "floating", "unknown")}
    counts["UNKNOWN"] = counts.pop("unknown")
    counts["total"] = int(native_counts.get("total", ids.size))
    fluid_mask = kinds == "fluid"; floating_mask = kinds == "floating"
    if not np.any(fluid_mask):
        raise AuditFailure(f"{label} has no decoded fluid particles")
    fluid_positions = position[fluid_mask]; fluid_velocity = velocity[fluid_mask]
    low = np.asarray(source["fluid_drawbox"]["low_m"], dtype=np.float64)
    high = np.asarray(source["fluid_drawbox"]["high_m"], dtype=np.float64)
    outside = np.any((fluid_positions < low - 1.0e-6) | (fluid_positions > high + 1.0e-6), axis=1)
    weighted_com = np.mean(fluid_positions, axis=0, dtype=np.float64)
    weighted_velocity = np.mean(fluid_velocity, axis=0, dtype=np.float64)
    fluid_mass = float(counts["fluid"] * mf)
    fluid_ke = float(0.5 * mf * np.sum(np.square(fluid_velocity.astype(np.float64)), dtype=np.float64))
    gap: dict[str, Any]
    if np.any(floating_mask):
        nearest = cKDTree(position[floating_mask]).query(fluid_positions, k=1, workers=1)[0]
        gap = {"status": "MEASURED_COMPONENT_SPACE_NEAREST_PARTICLE", "min_m": float(np.min(nearest)),
               "mean_nearest_m": float(np.mean(nearest, dtype=np.float64))}
    else:
        gap = {"status": "UNKNOWN_NO_DECODED_FLOATING_PARTICLES"}
    field_info = {**frame.get("metadata", {}), **frame.get("info", {})}
    return {"sentinel_id": sid, "grid": grid,
            "producer": {"xml": case["xml"], "receipt": case["producer_receipt"], "native_bi4": bi4_record},
            "native_header": {"MassFluid": native_massfluid, "MassBound": native_massbound, "Dp": native_dp,
                              "decoded_time_s": float(frame["decoded_time_s"]),
                              "frame_native_sha256": bi4_record["sha256"],
                              "frame_native_bytes": bi4_record["bytes"],
                              "frame_native_sha_matches_guarded_post": bi4_record["decoder_frame_sha_matches_post"],
                              "decoder_dynamic_semantics": frame.get("dynamic_semantics"),
                              "decoder_field_metadata": {key: field_metadata[key] for key in field_metadata if key in {"MassFluid", "MassBound", "Dp", "TimeStep"}}},
            "typed_role_counts": counts,
            "mk_semantics": {"relative_mkfluid_values": sorted(set(int(value) for value in relative[fluid_mask])),
                             "absolute_mk_values": sorted(set(int(value) for value in absolute)),
                             "fluid_relative_is_not_absolute": True},
            "support": {"fluid_inside_explicit_owner_box": bool(not np.any(outside)),
                        "fluid_outside_count": int(np.count_nonzero(outside)),
                        "tolerance_m": 1.0e-6,
                        "position_tolerance_is_not_scientific_task_tolerance": True,
                        "fluid_velocity_m_per_s": weighted_velocity.tolist(),
                        "floating_velocity_m_per_s": np.mean(velocity[floating_mask], axis=0, dtype=np.float64).tolist() if np.any(floating_mask) else None,
                        "fluid_velocity_norm_max_m_per_s": float(np.max(np.linalg.norm(fluid_velocity, axis=1))),
                        "fluid_floating_gap": gap},
            "mass_separation": {"continuous_owner_mass_kg": source["continuous_owner_mass_kg"],
                                "continuous_owner_volume_m3": source["continuous_owner_volume_m3"],
                                "native_fluid_sample_mass_kg": fluid_mass,
                                "native_floating_sample_mass_kg": float(counts["floating"] * mb) if mb is not None else None,
                                "physical_massbody_kg": source["massbody_kg"],
                                "native_fluid_ke_J": fluid_ke,
                                "no_rescale": True},
            "weighted_fluid_observable_component_space": {"centroid_m": weighted_com.tolist(),
                                                          "velocity_m_per_s": weighted_velocity.tolist(),
                                                          "kinetic_energy_J": fluid_ke},
            "vtk": {},
            "read_scope": {"native_frame": 0, "native_fields": ["Idp", "Pos/Posd", "Vel", "Rhop"], "hdf5_read": False,
                            "solver_launch": False, "world_axis_calibration": "UNKNOWN"},
            "scratch": {"path": str(scratch), "clean_after_decode": not scratch.exists()}}


def _vtk_case(case: dict[str, Any], result: dict[str, Any]) -> None:
    for role in ("fluid_vtk", "bound_vtk"):
        payload, record = _deferred_read(case["deferred"][role], f"{case['sentinel_id']}/{case['grid']} {role}", parse="vtk")
        summary = _parse_vtk(payload, f"{case['sentinel_id']}/{case['grid']} {role}")
        summary["source_record"] = record
        result["vtk"][role] = summary
    native_fluid = int(result["typed_role_counts"]["fluid"])
    native_bound = sum(int(result["typed_role_counts"][kind]) for kind in ("fixed", "moving", "floating"))
    result["vtk_comparison"] = {"fluid_count_matches_native": result["vtk"]["fluid_vtk"]["point_count"] == native_fluid,
                                 "bound_count_matches_native_nonfluid": result["vtk"]["bound_vtk"]["point_count"] == native_bound,
                                 "comparison_scope": "header/count diagnostic; no boundary no-penetration or flux proof"}


def _verify_producer(case: dict[str, Any]) -> dict[str, Any]:
    receipt, receipt_record = _stable_json(case["producer_receipt"], f"{case['sentinel_id']}/{case['grid']} producer receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} producer is not completed rc=0")
    xml_path = str(Path(str(case["xml"]["path"])).expanduser().absolute())
    output_root = str(Path(str(receipt.get("output_root", ""))).expanduser().absolute())
    if not output_root or Path(xml_path).parent != Path(output_root):
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} receipt output_root/XML parent mismatch")
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    expected_physical = str(case.get("physical_case_id", ""))
    expected_case = str(case.get("producer_case_id", ""))
    actual_physical = request.get("physical_case_id")
    actual_case = request.get("case_id")
    if expected_physical and actual_physical and str(actual_physical) != expected_physical:
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} producer physical case identity mismatch")
    if expected_case and actual_case and str(actual_case) != expected_case:
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} producer case identity mismatch")
    if expected_physical and not actual_physical:
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} receipt omitted physical_case_id")
    if expected_case and not actual_case:
        raise AuditFailure(f"{case['sentinel_id']}/{case['grid']} receipt omitted producer case_id")
    return {"receipt": receipt_record, "status": receipt.get("status"), "returncode": receipt.get("returncode"),
            "output_root": output_root, "request_case_id": actual_case,
            "request_physical_case_id": actual_physical,
            "expected_case_id": expected_case, "expected_physical_case_id": expected_physical}


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _stable_json({"path": str(manifest_path)}, "ROOT255 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT255_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V2":
        raise AuditFailure("ROOT255 manifest schema/status mismatch")
    proof, proof_record = _stable_json(manifest["proof"], "ROOT244 proof")
    report, report_record = _stable_json(manifest["report"], "ROOT244 report")
    if proof.get("report") != report_record["path"] or proof.get("report_sha256") != report_record["sha256"]:
        raise AuditFailure("ROOT244 proof/report join failed")
    if report.get("schema") != "ds02.stage2.f6-owner-rigid-metadata-audit.v1":
        raise AuditFailure("ROOT244 report schema mismatch")
    outputs: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        if not isinstance(case, dict) or not isinstance(case.get("deferred"), dict):
            raise AuditFailure("manifest case/deferred records are malformed")
        producer = _verify_producer(case)
        xml_root, xml_record = _stable_xml(case["xml"], f"{case['sentinel_id']}/{case['grid']} XML")
        item = _native_case(case, xml_root, Path(str(case["xml"]["path"])).expanduser().absolute(), attempt_root)
        item["producer_join"] = producer
        item["producer_join"]["xml"] = xml_record
        _vtk_case(case, item)
        item["scientific_qualification"] = QUALIFICATION
        outputs.append(item)
    if len(outputs) != 6:
        raise AuditFailure(f"ROOT255 expected six sentinel/grid cases, got {len(outputs)}")
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record,
              "root244_proof": proof_record, "root244_report": report_record,
              "cases": outputs, "mass_semantics": {"continuous_owner_mass_kg": 4851.988676250775,
              "physical_rigid_massbody_kg": 128.0, "legacy_source_fluid_sample_mass_kg": 5120.0,
              "legacy_sample_mass_is_not_continuous_owner": True, "no_rescale": True},
              "scientific_qualification": QUALIFICATION,
              "interpretation": ["initial GenCase products only; no CFD or dynamic truth", "component-space native fields only; world-axis calibration UNKNOWN", "VTK count/support is an initial representation diagnostic, not a no-penetration or flux proof", "continuous owner and every native sample mass remain separate"],
              "read_scope": {"native_frame_count": 6, "vtk_file_count": 12, "hdf5_read": False, "solver_launch": False, "full_native_tree_scan": False,
                             "native_integrity": "pre SHA/stat before decoder; decoder source-file SHA; post SHA/stat after decoder"}}
    _write_once(output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise AuditFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _self_test() -> None:
    header = b"# vtk DataFile Version 3.0\nfixture\nbinary\nDATASET POLYDATA\nPOINTS 2 float\n"
    points = np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=">f4").tobytes()
    parsed = _parse_vtk(header + points, "fixture")
    assert parsed["point_count"] == 2 and parsed["finite"]
    try:
        _parse_vtk(header + points[:-1], "truncated")
    except AuditFailure:
        pass
    else:
        raise AssertionError("truncated VTK accepted")
    try:
        bad = np.asarray([[float("nan"), 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=">f4").tobytes()
        _parse_vtk(header + bad, "nonfinite")
    except AuditFailure:
        pass
    else:
        raise AssertionError("nonfinite VTK accepted")
    with tempfile.TemporaryDirectory(prefix="root255-v2-integrity-") as directory:
        path = Path(directory) / "frame.bi4"
        path.write_bytes(b"fixture-bi4")
        digest, size = _sha(path)
        record = {"path": str(path), "bytes": size, "known_sha256": digest, "stat_at_prepare": _stat(path)}
        pre = _deferred_bi4_pre(record, "fixture BI4")
        post = _deferred_bi4_post(pre, record, "fixture BI4", {"sha256": digest, "bytes": size})
        assert post["decoder_frame_sha_matches_post"] and post["pre_post_sha_equal"]
        path.write_bytes(b"changed-after-pre")
        try: _deferred_bi4_post(pre, record, "changed fixture BI4", {"sha256": digest, "bytes": size})
        except AuditFailure: pass
        else: raise AssertionError("native change during decoder was accepted")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root, and --output are required unless --self-test")
    try:
        result = run(args.manifest, args.attempt_root, args.output)
    except Exception as exc:
        print(f"{FAIL_STATUS}: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "cases": len(result["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
