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

This additive V5 keeps decoder failures distinct from integrity-finalization
failures.  When the decoder raises, the BI4 post-SHA/stat check and scratch
cleanup still run, but the original decoder exception remains the primary
failure.  It also has an explicit ``POSITION_ONLY_INITIAL_SUPPORT`` mode for
GenCase products whose initial BI4 exposes Idp and position but no dynamic
Vel/Rhop/Mass fields.  Missing optional fields are reported as UNKNOWN and
are never filled with zeros or XML-derived values.

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
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

import stage2_native_physical_observer_v2 as native
import stage2_f1_native_selected_observer_v1 as calibrated


SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v5"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v5"
PASS_STATUS = "COMPLETE_F6_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_V5_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V5"
POSITION_ONLY_INITIAL_SUPPORT = "POSITION_ONLY_INITIAL_SUPPORT"
FULL_DYNAMIC_SUPPORT = "FULL_DYNAMIC_SUPPORT"
DECODER_SOURCE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_VTK_BYTES = 512 * 1024 * 1024


class AuditFailure(RuntimeError):
    pass


def _note(exc: BaseException, message: str) -> None:
    """Attach context on Python versions with or without ``BaseException.add_note``."""
    add_note = getattr(exc, "add_note", None)
    if callable(add_note):
        add_note(message)
        return
    notes = getattr(exc, "__notes__", None)
    if notes is None:
        notes = []
        try:
            setattr(exc, "__notes__", notes)
        except Exception:
            return
    notes.append(message)


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
    actual read.  V3 keeps the pre state open until the decoder returns.
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


def _decoder_saved_file(frame: dict[str, Any] | None, label: str) -> dict[str, Any]:
    """Extract the official decoder's real ``frame['saved_file']`` contract.

    The V2 worker accidentally looked for ``source_file``.  The production
    ``stage2_native_physical_observer_v2.decode_frame`` returns a ``saved_file``
    object containing the absolute path, byte count, and SHA-256.  Requiring
    this exact shape prevents a permissive fallback from turning a missing
    decoder integrity field into credit.
    """
    if not isinstance(frame, dict):
        raise AuditFailure(f"{label} decoder did not return a frame object")
    saved = frame.get("saved_file")
    if not isinstance(saved, dict):
        raise AuditFailure(f"{label} decoder frame is missing saved_file")
    missing = [key for key in ("path", "bytes", "sha256") if key not in saved]
    if missing:
        raise AuditFailure(f"{label} decoder saved_file missing {missing}")
    try:
        path = Path(str(saved["path"])).expanduser().absolute()
        byte_count = int(saved["bytes"])
    except (TypeError, ValueError) as exc:
        raise AuditFailure(f"{label} decoder saved_file path/bytes are malformed") from exc
    digest = str(saved["sha256"]).lower()
    if byte_count < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AuditFailure(f"{label} decoder saved_file bytes/SHA are malformed")
    return {"path": str(path), "bytes": byte_count, "sha256": digest}


def _deferred_bi4_post(pre: dict[str, Any], record: dict[str, Any], label: str,
                       frame_source: dict[str, Any] | None,
                       *, require_saved_file: bool = True) -> dict[str, Any]:
    """Hash/stat the BI4 after decoder return and optionally compare ``saved_file``.

    A decoder exception has no frame object by definition.  In that path the
    source boundary is still useful, but demanding a decoder-returned
    ``saved_file`` would replace the real decoder exception with a misleading
    API-shape error.  ``require_saved_file=False`` therefore records only the
    source post-check; successful decodes retain the strict saved-file check.
    """
    path = Path(pre["path"])
    post_sha, post_bytes = _sha(path)
    after = _stat(path)
    if pre["stat_before"] != after or pre["pre_sha256"] != post_sha or pre["pre_bytes"] != post_bytes:
        raise AuditFailure(f"{label} changed during decoder read")
    expected = pre.get("expected_sha256")
    if expected and str(expected).lower() != post_sha:
        raise AuditFailure(f"{label} known SHA differs after decoder")
    _verify_record_stat(path, record, label, after)
    if not isinstance(frame_source, dict):
        if require_saved_file:
            raise AuditFailure(f"{label} decoder did not expose saved_file SHA and bytes")
        return {"path": str(path), "sha256": post_sha, "bytes": post_bytes,
                "stat_before": pre["stat_before"], "stat_after": after,
                "stable_read": True, "pre_post_sha_equal": True,
                "pre_sha256": pre["pre_sha256"], "post_sha256": post_sha,
                "decoder_frame_sha256": None, "decoder_frame_bytes": None,
                "decoder_frame_sha_matches_post": None,
                "content_scope": "bi4_post_integrity_after_decoder_failure",
                "decoder_saved_file": "NOT_AVAILABLE_BECAUSE_DECODER_RAISED"}
    decoder_path = Path(str(frame_source["path"])).expanduser().absolute()
    if decoder_path != path.absolute():
        raise AuditFailure(f"{label} decoder saved_file path differs from guarded BI4 path")
    decoder_sha = str(frame_source["sha256"]).lower()
    decoder_bytes = int(frame_source["bytes"])
    if decoder_sha != post_sha:
        raise AuditFailure(f"{label} decoder frame SHA differs from guarded post SHA")
    if decoder_bytes != post_bytes:
        raise AuditFailure(f"{label} decoder frame bytes differ from guarded post bytes")
    return {"path": str(path), "sha256": post_sha, "bytes": post_bytes,
            "stat_before": pre["stat_before"], "stat_after": after,
            "stable_read": True, "pre_post_sha_equal": True,
            "pre_sha256": pre["pre_sha256"], "post_sha256": post_sha,
            "decoder_frame_sha256": decoder_sha, "decoder_frame_bytes": decoder_bytes,
            "decoder_frame_sha_matches_post": bool(decoder_sha) and str(decoder_sha).lower() == post_sha,
            "content_scope": "bi4_frame_decoder_bounded"}


def _decode_frame_with_guard(record: dict[str, Any], decoder: Path, scratch: Path,
                             label: str, decode_frame: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep the source integrity boundary open across the real decoder call.

    The decoder exception is captured only long enough to finish the source
    post-check and scratch cleanup.  Any finalization error is attached as a
    note to the original exception; it never masks that original cause.
    """
    pre = _deferred_bi4_pre(record, label)
    decode_error: BaseException | None = None
    frame: dict[str, Any] | None = None
    post: dict[str, Any] | None = None
    post_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        frame = decode_frame()
    except BaseException as exc:
        decode_error = exc
    finally:
        try:
            frame_source = _decoder_saved_file(frame, label) if frame is not None and decode_error is None else None
            post = _deferred_bi4_post(pre, record, label, frame_source,
                                      require_saved_file=decode_error is None)
        except BaseException as exc:
            post_error = exc
        finally:
            try:
                if scratch.exists():
                    shutil.rmtree(scratch, ignore_errors=False)
            except BaseException as exc:
                cleanup_error = exc
    if decode_error is not None:
        if post_error is not None:
            _note(decode_error, f"decoder post-integrity check also failed: {post_error!r}")
        elif post is not None:
            _note(decode_error,
                "decoder post-integrity check completed: "
                f"stable={post.get('stable_read')} sha={post.get('pre_post_sha_equal')}"
            )
        if cleanup_error is not None:
            _note(decode_error, f"decoder scratch cleanup also failed: {cleanup_error!r}")
        raise decode_error
    if post_error is not None:
        if cleanup_error is not None:
            _note(post_error, f"scratch cleanup also failed: {cleanup_error!r}")
        raise post_error
    if cleanup_error is not None:
        raise cleanup_error
    if frame is None or post is None:
        raise AuditFailure(f"{label} decoder returned no frame")
    return frame, post


def _decoder_xml_and_particle_root(prefix: Path, frame_path: Path, scratch_root: Path) -> tuple[Path, ET.Element, Path, dict[str, Any], dict[str, Any]]:
    """Locate the official dump XML and its particle directory.

    GenCase's initial BI4 dump has a different output tree from the dynamic
    selected-frame path used by ``native.decode_frame``: the XML is commonly
    ``<prefix>/<input-stem>.xml`` and the arrays are below
    ``<prefix>/<input-stem>/PART_0000``.  This resolver accepts only the
    bounded, decoder-created scratch candidates; it does not search the
    production data tree.
    """
    candidates = [Path(str(prefix) + ".xml"), prefix.with_suffix(".xml"),
                  prefix / f"{frame_path.stem}.xml", scratch_root / f"{frame_path.stem}.xml"]
    xml_path = next((candidate for candidate in candidates if candidate.is_file() and not candidate.is_symlink()), None)
    if xml_path is None:
        raise native.UnsupportedSemantics(f"official BI4 decoder produced no XML under bounded scratch: {candidates}")
    try:
        root = ET.fromstring(xml_path.read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise native.UnsupportedSemantics(f"official BI4 decoder XML could not be parsed: {xml_path}") from exc
    items = [node for node in root.iter() if _tag(node) == "item"]
    particle = next((node for node in items if str(node.get("name", "")).upper().startswith("PART_")), None)
    if particle is None:
        particle = next((node for node in items if any(_tag(child) == "item" for child in node)), None)
    if particle is None or not particle.get("name"):
        raise native.UnsupportedSemantics(f"official BI4 XML has no particle item: {xml_path}")
    particle_name = str(particle.get("name"))
    roots = [prefix / particle_name, prefix / frame_path.stem / particle_name,
             prefix.parent / particle_name, prefix.parent / frame_path.stem / particle_name,
             scratch_root / particle_name, scratch_root / frame_path.stem / particle_name]
    particle_root = next((candidate for candidate in roots if candidate.is_dir() and not candidate.is_symlink()), None)
    if particle_root is None:
        raise native.UnsupportedSemantics(f"official BI4 XML particle directory is missing: {particle_name}")
    metadata = native.named_values(next((node for node in items if str(node.get("name", "")) == "JPartDataBi4"), None))
    info = native.named_values(particle)
    return xml_path, root, particle_root, metadata, info


def _array_path(root: Path, *names: str) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _read_array(path: Path, dtype: np.dtype[Any], label: str) -> np.ndarray:
    try:
        value = np.fromfile(path, dtype=dtype)
    except OSError as exc:
        raise native.UnsupportedSemantics(f"cannot read decoder array {label}: {path}") from exc
    if value.size == 0:
        raise native.UnsupportedSemantics(f"decoder array {label} is empty: {path}")
    if not np.isfinite(value).all() and dtype.kind in "fc":
        raise native.UnsupportedSemantics(f"decoder array {label} contains non-finite values")
    return value


def _decode_position_only_frame(frame_path: Path, decoder: Path, scratch_root: Path, frame: int) -> dict[str, Any]:
    """Decode a GenCase initial BI4 without inventing dynamic fields.

    The official dump is still the sole producer.  This adapter reads Idp and
    Pos/Posd when present, and records Vel/Rhop/Mass as UNKNOWN when the
    initial product does not contain them.  It deliberately does not call
    ``native.decode_frame`` because that dynamic observer requires Vel/Rhop and
    would turn an otherwise valid position-only initial product into a
    misleading interface failure.
    """
    frame_path = _regular(frame_path, f"initial frame {frame}")
    decoder = _regular(decoder, "official BI4 decoder")
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"position-only-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / frame_path.stem
        try:
            subprocess.run([str(decoder), str(frame_path), str(prefix)],
                           check=True, capture_output=True, text=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or ""
            raise native.UnsupportedSemantics(
                f"official BI4 position-only decoder failed for frame {frame}: {detail[-1000:]}"
            ) from exc
        xml_path, _root, particle_root, metadata, info = _decoder_xml_and_particle_root(prefix, frame_path, Path(temporary))
        ids_path = _array_path(particle_root, "Idp.bin", "Idp")
        pos_path = _array_path(particle_root, "Posd.bin", "Posd.bin.raw", "Pos.bin", "Pos")
        if ids_path is None or pos_path is None:
            raise native.UnsupportedSemantics(
                f"position-only initial decoder lacks Idp/Pos for frame {frame}: "
                f"Idp={ids_path!s} Pos={pos_path!s}"
            )
        ids = _read_array(ids_path, np.dtype("<u4"), "Idp")
        if np.unique(ids).size != ids.size:
            raise native.UnsupportedSemantics(f"position-only initial decoder has duplicate Idp for frame {frame}")
        if pos_path.name.startswith("Posd"):
            position_dtype = np.dtype("<f8")
        else:
            position_dtype = np.dtype("<f4")
        position = _read_array(pos_path, position_dtype, "Pos/Posd")
        try:
            position = position.reshape(int(ids.size), 3)
        except ValueError as exc:
            raise native.UnsupportedSemantics(
                f"position-only decoder Pos length does not match Idp for frame {frame}"
            ) from exc
        optional: dict[str, Any] = {}
        optional_arrays: dict[str, np.ndarray | None] = {}
        for name, aliases, dtype, shape in (
            ("Vel", ("Vel.bin", "Vel"), np.dtype("<f4"), "vector"),
            ("Rhop", ("Rhop.bin", "Rhop"), np.dtype("<f4"), "scalar"),
        ):
            candidate = _array_path(particle_root, *aliases)
            if candidate is None:
                optional[name] = {"status": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4", "path": None}
                optional_arrays[name] = None
                continue
            array = _read_array(candidate, dtype, name)
            expected_size = int(ids.size) * (3 if shape == "vector" else 1)
            if array.size != expected_size:
                raise native.UnsupportedSemantics(
                    f"decoder optional {name} length {array.size} != expected {expected_size}"
                )
            optional[name] = {"status": "MEASURED_INITIAL_ARRAY", "path": str(candidate), "bytes": int(candidate.stat().st_size)}
            optional_arrays[name] = array.reshape(int(ids.size), 3) if shape == "vector" else array
        digest, byte_count = _sha(frame_path)
        raw_time = info.get("TimeStep")
        try:
            decoded_time = float(raw_time) if raw_time is not None else None
        except (TypeError, ValueError):
            decoded_time = None
        if decoded_time is not None and not math.isfinite(decoded_time):
            decoded_time = None
        return {"frame": frame, "saved_file": {"path": str(frame_path.resolve()), "bytes": byte_count, "sha256": digest},
                "decoder_xml_path": str(xml_path), "decoded_time_s": decoded_time,
                "ids": ids, "position": position,
                "velocity": optional_arrays["Vel"], "density": optional_arrays["Rhop"],
                "optional_fields": optional, "metadata": metadata, "info": info,
                "field_scope": POSITION_ONLY_INITIAL_SUPPORT, "position_dtype": str(position_dtype),
                "mass_fields": {"MassFluid": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4",
                                "MassBound": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4"}}


def _optional_scalar_from_frame(frame: dict[str, Any], name: str) -> dict[str, Any]:
    value = _scalar({**frame.get("metadata", {}), **frame.get("info", {})}, name)
    if value is None:
        return {"status": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4", "value": None}
    return {"status": "MEASURED_INITIAL_DECODER_HEADER", "value": value}


def _position_only_case(case: dict[str, Any], source: dict[str, Any], frame: dict[str, Any],
                        bi4_record: dict[str, Any], scratch: Path) -> dict[str, Any]:
    sid = str(case["sentinel_id"]); grid = str(case["grid"]); label = f"{sid}/{grid}"
    ids = np.asarray(frame["ids"]); position = np.asarray(frame["position"])
    source_info = source["typed_source"]
    kinds, relative, absolute = native.assign_particle_ranges(ids, source_info["blocks"])
    native_counts, _, _, _ = calibrated._role_counts(ids, source_info)
    counts = {kind: int(native_counts.get(kind, 0)) for kind in ("fluid", "fixed", "moving", "floating", "unknown")}
    counts["UNKNOWN"] = counts.pop("unknown"); counts["total"] = int(native_counts.get("total", ids.size))
    fluid_mask = kinds == "fluid"
    if not np.any(fluid_mask):
        raise AuditFailure(f"{label} position-only initial product has no decoded fluid particles")
    fluid_positions = position[fluid_mask]
    low = np.asarray(source["fluid_drawbox"]["low_m"], dtype=np.float64)
    high = np.asarray(source["fluid_drawbox"]["high_m"], dtype=np.float64)
    outside = np.any((fluid_positions < low - 1.0e-6) | (fluid_positions > high + 1.0e-6), axis=1)
    velocity = frame.get("velocity")
    density = frame.get("density")
    fluid_velocity = velocity[fluid_mask] if isinstance(velocity, np.ndarray) else None
    massfluid = _optional_scalar_from_frame(frame, "MassFluid")
    massbound = _optional_scalar_from_frame(frame, "MassBound")
    optional_status = {key: value.get("status") for key, value in frame.get("optional_fields", {}).items()}
    return {"sentinel_id": sid, "grid": grid, "field_scope": POSITION_ONLY_INITIAL_SUPPORT,
            "producer": {"xml": case["xml"], "receipt": case["producer_receipt"], "native_bi4": bi4_record},
            "native_header": {"MassFluid": massfluid, "MassBound": massbound,
                              "Dp": _optional_scalar_from_frame(frame, "Dp"),
                              "decoded_time_s": frame.get("decoded_time_s"),
                              "frame_native_sha256": bi4_record["sha256"], "frame_native_bytes": bi4_record["bytes"],
                              "frame_native_sha_matches_guarded_post": bi4_record["decoder_frame_sha_matches_post"],
                              "decoder_field_scope": POSITION_ONLY_INITIAL_SUPPORT,
                              "optional_field_status": optional_status,
                              "velocity_unit": "UNKNOWN_UNREGISTERED_IF_MISSING",
                              "mass_unit": "UNKNOWN_UNREGISTERED_IF_MISSING"},
            "typed_role_counts": counts,
            "mk_semantics": {"relative_mkfluid_values": sorted(set(int(value) for value in relative[fluid_mask])),
                             "absolute_mk_values": sorted(set(int(value) for value in absolute)),
                             "fluid_relative_is_not_absolute": True},
            "support": {"fluid_inside_explicit_owner_box": bool(not np.any(outside)),
                        "fluid_outside_count": int(np.count_nonzero(outside)), "tolerance_m": 1.0e-6,
                        "position_tolerance_is_not_scientific_task_tolerance": True,
                        "centroid_m": np.mean(fluid_positions, axis=0, dtype=np.float64).tolist(),
                        "velocity_m_per_s": np.mean(fluid_velocity, axis=0, dtype=np.float64).tolist() if fluid_velocity is not None else None,
                        "velocity_status": "MEASURED_INITIAL_ARRAY" if fluid_velocity is not None else "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4",
                        "density_status": "MEASURED_INITIAL_ARRAY" if isinstance(density, np.ndarray) else "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4"},
            "mass_separation": {"continuous_owner_mass_kg": source["continuous_owner_mass_kg"],
                                "continuous_owner_volume_m3": source["continuous_owner_volume_m3"],
                                "native_fluid_sample_mass_kg": None,
                                "native_floating_sample_mass_kg": None,
                                "physical_massbody_kg": source["massbody_kg"],
                                "native_mass_status": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4",
                                "no_rescale": True},
            # Keep the result shape identical for position-only and dynamic
            # producers. V4 returned no container here, while its shared VTK
            # stage writes result["vtk"][role]. V5 initializes it before the
            # Fluid/Bound VTK pass.
            "vtk": {},
            "read_scope": {"native_frame": 0, "native_fields": ["Idp", "Pos/Posd", "Vel if present", "Rhop if present"],
                           "hdf5_read": False, "solver_launch": False, "world_axis_calibration": "UNKNOWN",
                           "dynamic_decoder_not_used": True, "initial_position_only": True},
            "scratch": {"path": str(scratch), "clean_after_decode": not scratch.exists()},
            "scientific_qualification": QUALIFICATION}


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
    decoder = Path(str(case["decoder"]["path"])).expanduser().absolute()
    decoder_source = Path(str(case["decoder_source"]["path"])).expanduser().absolute()
    if not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise AuditFailure(f"{label} decoder is not executable")
    contract = native.decoder_source_contract(decoder_source)
    if not contract.get("status", "").startswith("PASS_"):
        raise AuditFailure(f"{label} decoder source contract is not proven")
    scratch = attempt_root / "scratch" / f"{sid}-{grid}"
    scratch.mkdir(parents=True, exist_ok=True)
    field_scope = str(case.get("field_scope", POSITION_ONLY_INITIAL_SUPPORT))
    if field_scope not in {POSITION_ONLY_INITIAL_SUPPORT, FULL_DYNAMIC_SUPPORT}:
        raise AuditFailure(f"{label} has unknown decoder field_scope {field_scope!r}")
    decode = (lambda: _decode_position_only_frame(Path(str(bi4["path"])), decoder, scratch, 0)
              if field_scope == POSITION_ONLY_INITIAL_SUPPORT else
              native.decode_frame(Path(str(bi4["path"])), decoder, scratch, 0))
    frame, bi4_record = _decode_frame_with_guard(
        bi4, decoder, scratch, f"{label} native frame-0 BI4", decode,
    )
    if field_scope == POSITION_ONLY_INITIAL_SUPPORT:
        return _position_only_case(case, source, frame, bi4_record, scratch)
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
    manifest, manifest_record = _stable_json({"path": str(manifest_path)}, "ROOT272 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT272_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V5":
        raise AuditFailure("ROOT272 manifest schema/status mismatch")
    proof, proof_record = _stable_json(manifest["proof"], "ROOT244 proof")
    report, report_record = _stable_json(manifest["report"], "ROOT244 report")
    if proof.get("report") != report_record["path"] or proof.get("report_sha256") != report_record["sha256"]:
        raise AuditFailure("ROOT244 proof/report join failed")
    if report.get("schema") != "ds02.stage2.f6-owner-rigid-metadata-audit.v1":
        raise AuditFailure("ROOT244 report schema mismatch")
    owner_proof, owner_proof_record = _stable_json(manifest["owner_proof"], "ROOT252 continuous-owner proof")
    owner_report, owner_report_record = _stable_json(manifest["owner_report"], "ROOT252 continuous-owner report")
    if owner_proof.get("report") != owner_report_record["path"] or owner_proof.get("report_sha256") != owner_report_record["sha256"]:
        raise AuditFailure("ROOT252 proof/report join failed")
    if owner_report.get("schema") != "ds02.stage2.f6-continuous-owner-geometry-audit.v1":
        raise AuditFailure("ROOT252 continuous-owner report schema mismatch")
    prior_failure, prior_failure_record = _stable_json(
        manifest["prior_v4_failure_proof"], "ROOT267 V4 failure proof"
    )
    prior_request, prior_request_record = _stable_json(
        manifest["prior_v4_failure_request"], "ROOT267 V4 consumed request"
    )
    if prior_failure.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise AuditFailure("ROOT267 prior proof schema mismatch")
    if "FAIL" not in str(prior_failure.get("status", "")):
        raise AuditFailure("ROOT267 prior proof is not a failure record")
    if int(prior_failure.get("actual_returncode", 2)) == 0:
        raise AuditFailure("ROOT267 prior proof unexpectedly has returncode zero")
    if "vtk" not in str(prior_failure.get("failure", "")).lower():
        raise AuditFailure("ROOT267 prior proof is not the positional VTK interface failure")
    if prior_failure.get("request") != prior_request_record["path"]:
        raise AuditFailure("ROOT267 failure proof/request path join failed")
    if prior_failure.get("request_sha256") != prior_request_record["sha256"]:
        raise AuditFailure("ROOT267 failure proof/request SHA join failed")
    if prior_request.get("schema") != "ds02.request.v1" or ".v4" not in str(prior_request.get("variant_schema", "")):
        raise AuditFailure("ROOT267 consumed request schema mismatch")
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
        raise AuditFailure(f"ROOT272 expected six sentinel/grid cases, got {len(outputs)}")
    result = {"schema": SCHEMA, "status": PASS_STATUS, "manifest": manifest_record,
              "root244_proof": proof_record, "root244_report": report_record,
              "root252_owner_proof": owner_proof_record, "root252_owner_report": owner_report_record,
              "prior_v4_failure_proof": prior_failure_record, "prior_v4_failure_request": prior_request_record,
              "cases": outputs, "mass_semantics": {"continuous_owner_mass_kg": 4851.988676250775,
              "physical_rigid_massbody_kg": 128.0, "legacy_source_fluid_sample_mass_kg": 5120.0,
              "legacy_sample_mass_is_not_continuous_owner": True, "no_rescale": True},
              "scientific_qualification": QUALIFICATION,
              "interpretation": ["initial GenCase products only; no CFD or dynamic truth", "component-space native fields only; world-axis calibration UNKNOWN", "VTK count/support is an initial representation diagnostic, not a no-penetration or flux proof", "continuous owner and every native sample mass remain separate"],
              "read_scope": {"native_frame_count": 6, "vtk_file_count": 12, "hdf5_read": False, "solver_launch": False, "full_native_tree_scan": False,
                             "native_integrity": "pre SHA/stat before decoder; on success saved_file.path/bytes/sha256 plus post SHA/stat; on decoder failure post SHA/stat and cleanup are checked while the original exception is preserved",
                             "initial_field_scope": POSITION_ONLY_INITIAL_SUPPORT,
                             "missing_initial_fields": "Vel/Rhop/Mass remain UNKNOWN; no fabricated zero or XML-derived value"}}
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


def _fixture_stat(path: Path) -> dict[str, int]:
    """Small fixture-only stat helper used by the end-to-end CLI test."""
    value = path.stat()
    return {"dev": int(value.st_dev), "ino": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _fixture_record(path: Path, *, label: str, role: str | None = None) -> dict[str, Any]:
    digest, size = _sha(path)
    result: dict[str, Any] = {"path": str(path.absolute()), "label": label,
                              "bytes": size, "known_sha256": digest,
                              "sha256": digest, "stat_at_prepare": _fixture_stat(path)}
    if role is not None:
        result["role"] = role
    return result


def _fixture_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _fixture_record(path, label=path.name)


def _fixture_source_xml() -> str:
    # The owner volume is deliberately the frozen F6 XML owner volume.  The
    # four Idp values in the manufactured dump cover every typed role, while
    # the initial product intentionally omits Vel/Rhop/Mass.
    return """<?xml version="1.0" encoding="UTF-8"?>
<case>
  <execution>
    <particles>
      <fixed begin="0" count="1" mk="10" />
      <fluid begin="1" count="2" mkfluid="0" mk="1" />
      <floating begin="3" count="1" mk="50" refmotion="fixture_motion" />
    </particles>
    <constants>
      <rhop0 value="1000.0" />
      <massfluid value="0.125" />
      <massbound value="1.0" />
    </constants>
  </execution>
  <mainlist>
    <setmkfluid mk="1" />
    <drawbox cmt="fixture fluid owner">
      <boxfill>solid</boxfill>
      <point x="0.0" y="0.0" z="0.0" />
      <size x="1.0" y="1.0" z="4.851988676250775" />
    </drawbox>
    <setmkbound mk="50" />
    <drawbox cmt="fixture floating role">
      <boxfill>solid</boxfill>
      <point x="0.1" y="0.1" z="0.1" />
      <size x="0.2" y="0.2" z="0.2" />
    </drawbox>
  </mainlist>
  <massbody value="128.0" />
</case>
"""


def _write_fixture_decoder(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, struct, sys\n"
        "frame = pathlib.Path(sys.argv[1])\n"
        "prefix = pathlib.Path(sys.argv[2])\n"
        "particle = prefix / 'PART_0000'\n"
        "particle.mkdir(parents=True, exist_ok=True)\n"
        "(prefix.with_suffix('.xml')).write_text(\n"
        "    '<data><item name=\"JPartDataBi4\"/><item name=\"PART_0000\"/></data>',\n"
        "    encoding='utf-8')\n"
        "particle.joinpath('Idp.bin').write_bytes(struct.pack('<4I', 0, 1, 2, 3))\n"
        "particle.joinpath('Posd.bin').write_bytes(struct.pack('<12d',\n"
        "    0.10, 0.10, 0.10, 0.25, 0.25, 0.25,\n"
        "    0.75, 0.75, 0.75, 0.50, 0.50, 1.00))\n"
        "# The input is intentionally consumed only as a named fixture source.\n"
        "if not frame.is_file():\n"
        "    raise SystemExit(3)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _fixture_vtk(points: list[tuple[float, float, float]]) -> bytes:
    header = (b"# vtk DataFile Version 3.0\nfixture\nbinary\n"
              b"DATASET POLYDATA\nPOINTS " + str(len(points)).encode("ascii") + b" float\n")
    values = np.asarray(points, dtype=">f4")
    return header + values.tobytes()


def _fixture_manifest(root: Path) -> tuple[Path, Path, Path]:
    """Create a completely synthetic six-case producer graph in a temp dir."""
    root.mkdir(parents=True, exist_ok=True)
    decoder = root / "fixture-bi4-dump.py"
    _write_fixture_decoder(decoder)
    source_xml_text = _fixture_source_xml()
    cases: list[dict[str, Any]] = []
    all_grids = (("F6-S1", "source_current"), ("F6-S1", "coarse"),
                 ("F6-S1", "fine"), ("F6-S2", "source_current"),
                 ("F6-S2", "coarse"), ("F6-S2", "fine"))
    for index, (sentinel, grid) in enumerate(all_grids):
        case_root = root / f"case-{index:02d}-{sentinel}-{grid}"
        case_root.mkdir()
        xml_path = case_root / "generated.xml"
        xml_path.write_text(source_xml_text, encoding="utf-8")
        bi4_path = case_root / "generated.bi4"
        bi4_path.write_bytes(f"manufactured-position-only-{index}".encode("ascii"))
        fluid_vtk = case_root / "generated_Fluid.vtk"
        fluid_vtk.write_bytes(_fixture_vtk([(0.25, 0.25, 0.25), (0.75, 0.75, 0.75)]))
        bound_vtk = case_root / "generated_Bound.vtk"
        bound_vtk.write_bytes(_fixture_vtk([(0.10, 0.10, 0.10), (0.50, 0.50, 1.00)]))
        physical = f"fixture-{sentinel}-{grid}"
        producer_case = f"producer-{index:02d}"
        receipt_path = case_root / "execution-receipt.json"
        receipt = {"status": "completed", "returncode": 0,
                   "output_root": str(case_root.absolute()),
                   "request": {"physical_case_id": physical, "case_id": producer_case}}
        receipt_record = _fixture_json(receipt_path, receipt)
        xml_record = _fixture_record(xml_path, label=f"{sentinel}/{grid} XML")
        deferred = {}
        for role, path in (("native_bi4", bi4_path), ("fluid_vtk", fluid_vtk), ("bound_vtk", bound_vtk)):
            deferred[role] = _fixture_record(path, label=f"{sentinel}/{grid} {role}", role=role)
            deferred[role].update({"sentinel_id": sentinel, "grid": grid, "frame": 0,
                                   "worker_must_full_sha_pre_and_post": True})
        cases.append({"sentinel_id": sentinel, "grid": grid,
                      "physical_case_id": physical, "producer_case_id": producer_case,
                      "xml": xml_record, "producer_receipt": receipt_record,
                      "deferred": deferred,
                      "decoder": {"path": str(decoder.absolute())},
                      "decoder_source": {"path": str(DECODER_SOURCE.absolute())},
                      "field_scope": POSITION_ONLY_INITIAL_SUPPORT})

    rigid_report_path = root / "root244-report.json"
    rigid_report = _fixture_json(rigid_report_path,
                                 {"schema": "ds02.stage2.f6-owner-rigid-metadata-audit.v1",
                                  "status": "ACTUAL_FIXTURE_METADATA"})
    rigid_proof_path = root / "root244-proof.json"
    rigid_proof_data = {"schema": "ds02.stage2.root-actual-verification.v1",
                        "status": "VERIFIED_ACTUAL_FIXTURE_ROOT244",
                        "report": str(rigid_report_path.absolute()),
                        "report_sha256": rigid_report["sha256"]}
    rigid_proof = _fixture_json(rigid_proof_path, rigid_proof_data)
    owner_report_path = root / "root252-report.json"
    owner_report = _fixture_json(owner_report_path,
                                 {"schema": "ds02.stage2.f6-continuous-owner-geometry-audit.v1",
                                  "status": "ACTUAL_FIXTURE_OWNER"})
    owner_proof_path = root / "root252-proof.json"
    owner_proof = _fixture_json(owner_proof_path,
                                {"schema": "ds02.stage2.root-actual-verification.v1",
                                 "status": "VERIFIED_ACTUAL_FIXTURE_ROOT252",
                                 "report": str(owner_report_path.absolute()),
                                 "report_sha256": owner_report["sha256"]})
    prior_request_path = root / "root267-request.json"
    prior_request = _fixture_json(prior_request_path,
                                  {"schema": "ds02.request.v1",
                                   "variant_schema": "ds02.stage2.f6-initial-native-support-request.v4",
                                   "status": "FAILED_FIXTURE_ROOT267_V4",
                                   "request_id": "fixture-root267"})
    prior_proof_path = root / "root267-proof.json"
    prior_proof = _fixture_json(prior_proof_path,
                                {"schema": "ds02.stage2.root-actual-verification.v1",
                                 "status": "VERIFIED_ACTUAL_ROOT267_FAILURE_NO_CREDIT",
                                 "request": str(prior_request_path.absolute()),
                                 "request_sha256": prior_request["sha256"],
                                 "failure": "KeyError vtk"})
    def ref(path: Path, label: str) -> dict[str, Any]:
        return _fixture_record(path, label=label)
    manifest_data = {"schema": MANIFEST_SCHEMA,
                     "status": "PREPARED_NOT_RUN_ROOT272_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V5",
                     "proof": ref(rigid_proof_path, "ROOT244 proof"),
                     "report": ref(rigid_report_path, "ROOT244 report"),
                     "owner_proof": ref(owner_proof_path, "ROOT252 continuous-owner proof"),
                     "owner_report": ref(owner_report_path, "ROOT252 continuous-owner report"),
                     "prior_v4_failure_proof": ref(prior_proof_path, "ROOT267 V4 failure proof"),
                     "prior_v4_failure_request": ref(prior_request_path, "ROOT267 V4 failure request"),
                     "cases": cases,
                     "source_binding": {"continuous_owner_mass_kg": 4851.988676250775,
                                        "physical_massbody_kg": 128.0,
                                        "world_axis_calibration": "UNKNOWN",
                                        "fixture_scope": "manufactured_nonproduction_only"}}
    manifest_path = root / "f6_initial_native_support_manifest_v5.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path = root / "f6_initial_native_support_audit_v5.json"
    return manifest_path, root / "attempt", output_path


def _run_fixture_cli() -> None:
    """Exercise the complete worker CLI, not only its internal helpers."""
    with tempfile.TemporaryDirectory(prefix="root272-v5-cli-") as directory:
        root = Path(directory)
        manifest, attempt, output = _fixture_manifest(root)
        command = [sys.executable, str(Path(__file__).absolute()), "--manifest", str(manifest),
                   "--attempt-root", str(attempt), "--output", str(output)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["schema"] == SCHEMA and result["status"] == PASS_STATUS
        assert len(result["cases"]) == 6
        for case in result["cases"]:
            assert case["field_scope"] == POSITION_ONLY_INITIAL_SUPPORT
            assert set(case["vtk"]) == {"fluid_vtk", "bound_vtk"}
            assert case["vtk_comparison"]["fluid_count_matches_native"]
            assert case["vtk_comparison"]["bound_count_matches_native_nonfluid"]
            assert case["scientific_qualification"]["QI"] == "UNKNOWN"
            assert case["scratch"]["clean_after_decode"]
        # A real CLI negative: the Fluid VTK payload is truncated after its
        # prepared stat.  This must fail in the bounded VTK reader.
        vtk_path = Path(result["cases"][1]["producer"]["xml"]["path"]).parent / "generated_Fluid.vtk"
        vtk_bytes = vtk_path.read_bytes()
        vtk_path.write_bytes(vtk_bytes[:-1])
        bad_vtk_output = root / "bad-vtk.json"
        failed = subprocess.run([*command[:-1], str(bad_vtk_output)], capture_output=True, text=True, timeout=300)
        assert failed.returncode != 0 and "fluid_vtk" in (failed.stdout + failed.stderr)
        vtk_path.write_bytes(vtk_bytes)
        # A real CLI negative: the producer receipt is altered after its
        # manifest SHA/stat binding.  The worker must reject it before any
        # native decode rather than silently accepting a different producer.
        receipt_path = Path(result["cases"][0]["producer"]["receipt"]["path"])
        original_receipt = receipt_path.read_text(encoding="utf-8")
        receipt_path.write_text(original_receipt.replace('"returncode": 0', '"returncode": 1'), encoding="utf-8")
        bad_output = root / "bad-receipt.json"
        failed = subprocess.run([*command[:-1], str(bad_output)], capture_output=True, text=True, timeout=300)
        assert failed.returncode != 0 and "changed" in (failed.stdout + failed.stderr)
        receipt_path.write_text(original_receipt, encoding="utf-8")


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
    with tempfile.TemporaryDirectory(prefix="root267-v3-integrity-") as directory:
        path = Path(directory) / "frame.bi4"
        path.write_bytes(b"fixture-bi4")
        digest, size = _sha(path)
        record = {"path": str(path), "bytes": size, "known_sha256": digest, "stat_at_prepare": _stat(path)}
        scratch = Path(directory) / "scratch"
        def real_shape_decode_frame() -> dict[str, Any]:
            return {"saved_file": {"path": str(path.resolve()), "bytes": size, "sha256": digest}}
        frame, post = _decode_frame_with_guard(
            record, Path("/unused/decoder"), scratch, "fixture BI4", real_shape_decode_frame
        )
        assert frame["saved_file"]["path"] == str(path.resolve())
        assert post["decoder_frame_sha_matches_post"] and post["pre_post_sha_equal"]
        def wrong_legacy_shape() -> dict[str, Any]:
            return {"source_file": {"path": str(path.resolve()), "bytes": size, "sha256": digest}}
        try:
            _decode_frame_with_guard(record, Path("/unused/decoder"), Path(directory) / "scratch-legacy",
                                     "legacy source_file fixture", wrong_legacy_shape)
        except AuditFailure as exc:
            assert "saved_file" in str(exc)
        else:
            raise AssertionError("legacy source_file decoder shape was accepted")
        def mutate_during_decode() -> dict[str, Any]:
            path.write_bytes(b"changed-during-decoder")
            return {"saved_file": {"path": str(path.resolve()), "bytes": size, "sha256": digest}}
        # Rebind the expected source record for the mutation test because the
        # decoder boundary must fail on the content/stat change itself.
        path.write_bytes(b"fixture-bi4")
        digest2, size2 = _sha(path)
        record2 = {"path": str(path), "bytes": size2, "known_sha256": digest2, "stat_at_prepare": _stat(path)}
        try:
            _decode_frame_with_guard(record2, Path("/unused/decoder"), Path(directory) / "scratch-mutated",
                                     "changed fixture BI4", mutate_during_decode)
        except AuditFailure: pass
        else: raise AssertionError("native change during decoder was accepted")
        # A real decoder failure must remain the primary exception.  The
        # post-integrity check is still run and the decoder-created scratch is
        # still removed.  This exercises the exact ROOT267 failure shape.
        path.write_bytes(b"fixture-bi4")
        digest4, size4 = _sha(path)
        record4 = {"path": str(path), "bytes": size4, "known_sha256": digest4, "stat_at_prepare": _stat(path)}
        failure_scratch = Path(directory) / "scratch-unsupported"
        def unsupported_decoder() -> dict[str, Any]:
            failure_scratch.mkdir(parents=True, exist_ok=True)
            (failure_scratch / "partial.xml").write_text("partial", encoding="utf-8")
            raise native.UnsupportedSemantics("fixture lacks Vel/Rhop: original decoder cause")
        try:
            _decode_frame_with_guard(record4, Path("/unused/decoder"), failure_scratch,
                                     "unsupported GenCase BI4", unsupported_decoder)
        except native.UnsupportedSemantics as exc:
            assert "original decoder cause" in str(exc)
            assert any("post-integrity check completed" in note for note in getattr(exc, "__notes__", []))
            assert not failure_scratch.exists()
        else:
            raise AssertionError("original UnsupportedSemantics was not preserved")
        # A source mutation during a decoder exception must likewise preserve
        # the decoder's type/message while attaching the integrity failure.
        def unsupported_after_mutation() -> dict[str, Any]:
            path.write_bytes(b"mutated-before-error")
            raise native.UnsupportedSemantics("decoder semantic error before post check")
        path.write_bytes(b"fixture-bi4")
        digest3, size3 = _sha(path)
        record3 = {"path": str(path), "bytes": size3, "known_sha256": digest3, "stat_at_prepare": _stat(path)}
        try:
            _decode_frame_with_guard(record3, Path("/unused/decoder"), Path(directory) / "scratch-mutated-error",
                                     "mutated unsupported BI4", unsupported_after_mutation)
        except native.UnsupportedSemantics as exc:
            assert "decoder semantic error before post check" in str(exc)
            assert any("post-integrity check also failed" in note for note in getattr(exc, "__notes__", []))
        else:
            raise AssertionError("decoder exception was replaced by post-integrity failure")
        # Exercise the real subprocess caller with a tiny manufactured
        # official-dump-shaped output.  It intentionally contains only Idp and
        # Posd; the position-only adapter must retain UNKNOWN for Vel/Rhop.
        decoder_fixture = Path(directory) / "manufactured-bi4-dump.py"
        decoder_fixture.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, struct, sys\n"
            "input_path, prefix = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])\n"
            "(prefix / 'PART_0000').mkdir(parents=True, exist_ok=True)\n"
            "(prefix.with_suffix('.xml')).write_text('<data><item name=\"JPartDataBi4\"/><item name=\"PART_0000\"/></data>', encoding='utf-8')\n"
            "(prefix / 'PART_0000' / 'Idp.bin').write_bytes(struct.pack('<2I', 0, 1))\n"
            "(prefix / 'PART_0000' / 'Posd.bin').write_bytes(struct.pack('<6d', .25, .25, .25, .75, .75, .75))\n",
            encoding="utf-8",
        )
        decoder_fixture.chmod(0o755)
        path.write_bytes(b"position-only-bi4")
        digest5, size5 = _sha(path)
        record5 = {"path": str(path), "bytes": size5, "known_sha256": digest5, "stat_at_prepare": _stat(path)}
        position_scratch = Path(directory) / "scratch-position-only"
        frame5, post5 = _decode_frame_with_guard(
            record5, decoder_fixture, position_scratch, "position-only manufactured BI4",
            lambda: _decode_position_only_frame(path, decoder_fixture, position_scratch, 0),
        )
        assert frame5["field_scope"] == POSITION_ONLY_INITIAL_SUPPORT
        assert frame5["velocity"] is None and frame5["density"] is None
        assert frame5["optional_fields"]["Vel"]["status"].startswith("UNKNOWN_")
        assert post5["decoder_frame_sha_matches_post"] and not position_scratch.exists()
    # Position-only initial products may expose Idp/Pos but no dynamic fields.
    source = {"typed_source": {"blocks": [{"begin": 0, "end_exclusive": 2, "kind": "fluid",
                                              "mkfluid_relative": 0, "mk_absolute": 1}]},
              "fluid_drawbox": {"low_m": [0.0, 0.0, 0.0], "high_m": [1.0, 1.0, 1.0]},
              "continuous_owner_mass_kg": 1.0, "continuous_owner_volume_m3": 1.0,
              "massbody_kg": 2.0}
    case = {"sentinel_id": "F6-S1", "grid": "fixture", "xml": {}, "producer_receipt": {}}
    frame = {"ids": np.asarray([0, 1], dtype=np.uint32),
             "position": np.asarray([[0.25, 0.25, 0.25], [0.75, 0.75, 0.75]], dtype=np.float32),
             "velocity": None, "density": None, "optional_fields": {
                 "Vel": {"status": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4"},
                 "Rhop": {"status": "UNKNOWN_MISSING_FROM_INITIAL_Gencase_BI4"}},
             "metadata": {}, "info": {}, "decoded_time_s": None}
    result = _position_only_case(case, source, frame,
                                 {"path": "/fixture/initial.bi4", "sha256": "0" * 64, "bytes": 1,
                                  "decoder_frame_sha_matches_post": True}, Path("/fixture/scratch"))
    assert result["field_scope"] == POSITION_ONLY_INITIAL_SUPPORT
    assert result["support"]["velocity_m_per_s"] is None
    assert result["support"]["velocity_status"].startswith("UNKNOWN_")
    assert result["mass_separation"]["native_fluid_sample_mass_kg"] is None
    # The helper tests above are intentionally small; this subprocess test
    # exercises the complete manifest -> producer join -> position-only
    # decoder -> Fluid/Bound VTK -> report path over all six fixture cases.
    _run_fixture_cli()
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_AUDIT_V5_SELFTEST")


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
