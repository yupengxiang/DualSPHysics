#!/usr/bin/env python3
"""Probe the first completed F2 BI4 frame with bounded full-content pre/post binding.

ROOT111 V4 stopped before producing a scientific stream because its decimal
XML MassFluid value was compared to the decoded BI4 value with an absolute
1e-12 gate.  This forward-only probe establishes the actual official decoder
header type and value first.  It opens only Part_0000.bi4 after the shared
guard, keeps decoder scratch in an actor-owned bounded directory, reads no
decoded arrays, and never opens the remaining 400 frames.  A type-derived
float32/binary64 expectation is recorded from the typed header value, while
raw BI4 header bytes remain unobserved; no serialization or precision credit
is granted and no tolerance is widened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2.coarse-active-stream.v6"
MANIFEST_SCHEMA = "ds02.stage2.f2.coarse-active-stream.manifest.v6"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
PHYSICAL_CASE_ID = CASE_KEY
FRAME_RE = re.compile(r"^Part_(\d{4})\.bi4$")
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".vtk", ".bi2", ".bi1"}


class StreamHeaderError(ValueError):
    """Raised when the bounded header probe cannot close its source contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, *, digest: str | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise StreamHeaderError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": digest if digest is not None else sha256(path),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise StreamHeaderError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise StreamHeaderError(f"{label} points to forbidden scientific payload: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StreamHeaderError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StreamHeaderError(f"{label} is not a JSON object: {path}")
    return value


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StreamHeaderError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise StreamHeaderError(f"{label} is not finite")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise StreamHeaderError(f"refusing to overwrite existing output: {path}")
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


def bind_ref(ref: dict[str, Any], label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise StreamHeaderError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    expected = ref.get("sha256")
    actual = stat_record(path, digest=sha256(path))
    if expected and expected != "PARENT_GUARD_COMPUTED" and actual["sha256"] != str(expected):
        raise StreamHeaderError(f"{label} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and actual[field] != int(ref[field]):
            raise StreamHeaderError(f"{label} {field} differs: {path}")
    return path, actual


def bind_frame_stat(ref: dict[str, Any], raw_root: Path, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise StreamHeaderError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    if path.parent != raw_root:
        raise StreamHeaderError(f"{label} is outside the exact raw data root: {path}")
    match = FRAME_RE.fullmatch(path.name)
    if match is None:
        raise StreamHeaderError(f"{label} is not Part_####.bi4: {path}")
    stat = path.stat()
    for field, stat_field in (("bytes", "st_size"), ("mtime_ns", "st_mtime_ns"), ("ctime_ns", "st_ctime_ns"), ("st_dev", "st_dev"), ("st_ino", "st_ino")):
        if ref.get(field) is not None and getattr(stat, stat_field) != int(ref[field]):
            raise StreamHeaderError(f"{label} {field} differs: {path}")
    # V6 closes the content boundary itself after the parent reservation.  The
    # first frame is the only native payload opened by this worker; all other
    # frame references remain metadata-only inventory entries.
    content_sha = sha256(path)
    return path, {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": content_sha,
    }


def directory_bytes(path: Path) -> int:
    return sum(child.stat().st_size for child in Path(path).rglob("*") if child.is_file() and not child.is_symlink())


def _parse_scalar(tag: str, raw: str | None) -> Any:
    if raw is None:
        return None
    normalized = tag.lower().split("}")[-1]
    if normalized in {"int", "uint", "int32", "uint32", "int64", "uint64", "long", "ullong"}:
        try:
            return int(raw)
        except ValueError:
            return raw
    if normalized in {"float", "double", "real"}:
        try:
            return float(raw)
        except ValueError:
            return raw
    if normalized in {"bool", "boolean"}:
        return raw.lower() in {"1", "true", "yes"}
    return raw


def _named_fields(root: ET.Element) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for element in root.iter():
        name = element.get("name")
        if not name or element.tag.lower().split("}")[-1] == "item":
            continue
        if name in fields:
            raise StreamHeaderError(f"decoder header field is ambiguous: {name}")
        raw = element.get("v")
        fields[name] = {
            "name": name,
            "tag": element.tag.lower().split("}")[-1],
            "raw": raw,
            "value": _parse_scalar(element.tag, raw),
        }
    return fields


def _source_mass(generated_xml: Path, expected: dict[str, Any]) -> dict[str, Any]:
    try:
        root = ET.parse(generated_xml).getroot()
    except (OSError, ET.ParseError) as exc:
        raise StreamHeaderError(f"generated XML is not parseable: {generated_xml}") from exc
    constants = {}
    for element in root.iter():
        tag = element.tag.lower().split("}")[-1]
        if tag in {"massfluid", "massbound"} and element.get("value") is not None:
            constants[tag] = element.get("value")
    if "massfluid" not in constants:
        raise StreamHeaderError("generated XML has no massfluid source constant")
    try:
        xml_decimal = Decimal(str(constants["massfluid"]))
    except (InvalidOperation, TypeError) as exc:
        raise StreamHeaderError("generated XML massfluid is not decimal") from exc
    xml_value = float(xml_decimal)
    manifest_value = finite(expected.get("massfluid_kg"), "manifest MassFluid")
    if xml_value != manifest_value:
        raise StreamHeaderError(f"generated XML/manifest MassFluid differs: {xml_value!r}!={manifest_value!r}")
    return {
        "xml_text": str(constants["massfluid"]),
        "xml_decimal": str(xml_decimal),
        "xml_value_kg": xml_value,
        "manifest_value_kg": manifest_value,
        "massbound_xml_text": constants.get("massbound"),
        "generated_xml_sha256": sha256(generated_xml),
    }


def _encoding_bits(value: float, tag: str) -> tuple[str, str]:
    normalized = tag.lower()
    if normalized == "float":
        packed = struct.pack("<f", value)
        return "float32", packed.hex()
    if normalized == "double":
        packed = struct.pack("<d", value)
        return "binary64", packed.hex()
    if normalized == "real":
        raise StreamHeaderError("MassFluid decoder uses ambiguous 'real' type; official bit width is not bound")
    raise StreamHeaderError(f"MassFluid decoder type is not a supported floating type: {tag!r}")


def _mass_contract(source: dict[str, Any], fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    header = fields.get("MassFluid")
    if not isinstance(header, dict) or header.get("tag") not in {"float", "double", "real"}:
        raise StreamHeaderError("official first-frame header lacks typed MassFluid")
    observed = finite(header.get("value"), "official BI4 MassFluid")
    encoding, observed_bits = _encoding_bits(observed, str(header["tag"]))
    _, expected_bits = _encoding_bits(source["xml_value_kg"], str(header["tag"]))
    float32_value = struct.unpack("<f", struct.pack("<f", source["xml_value_kg"]))[0]
    float64_value = struct.unpack("<d", struct.pack("<d", source["xml_value_kg"]))[0]
    bits_match = observed_bits == expected_bits
    return {
        "status": "TYPED_HEADER_MATCHES_EXPECTED_ENCODING_NO_RAW_SERIALIZATION_PROOF" if bits_match else "MASS_SERIALIZATION_MISMATCH_NO_FULL_STREAM",
        "source_xml_value_kg": source["xml_value_kg"],
        "manifest_value_kg": source["manifest_value_kg"],
        "official_header": {key: header.get(key) for key in ("name", "tag", "raw", "value")},
        "observed_encoding": encoding,
        "observed_little_endian_bits_hex": observed_bits,
        "expected_type_derived_bits_hex": expected_bits,
        "float32_round_value_kg": float32_value,
        "float64_round_value_kg": float64_value,
        "absolute_difference_from_xml_kg": abs(observed - source["xml_value_kg"]),
        "bits_match": bits_match,
        "raw_header_bytes_observed": False,
        "serialization_proof": "typed official decoder value only; raw BI4 header bytes are not exposed by this header XML",
        "float32_precision_correction": "NOT_APPLIED",
        "gate": "binary type-derived equality only; no decimal tolerance widening; no precision correction without raw-byte proof",
        "scientific_credit": "NONE",
    }


def _validate_dynamic_contract(fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Require the official header's closed single-piece/dynamic contract."""
    values: dict[str, int] = {}
    for name, expected in (("Npiece", 1), ("Piece", 0), ("NpDynamic", 0), ("ReuseIds", 0), ("PeriMode", 0)):
        field = fields.get(name)
        if not isinstance(field, dict):
            raise StreamHeaderError(f"official first-frame header lacks closed-stream field {name}")
        try:
            value = int(field.get("value"))
        except (TypeError, ValueError) as exc:
            raise StreamHeaderError(f"official first-frame header field {name} is not integer") from exc
        if value != expected:
            raise StreamHeaderError(f"unsupported dynamic BI4 field {name}={value}; expected {expected}")
        values[name] = value
    return {
        "values": values,
        "status": "SINGLE_PIECE_STATIC_ID_AXIS_CONFIRMED",
        "source": "official first-frame BI4 header",
    }


def _frame_inventory(manifest: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    refs = manifest.get("frames")
    expected_count = (manifest.get("expected") or {}).get("frame_count")
    if not isinstance(refs, list) or not refs or expected_count != len(refs):
        raise StreamHeaderError("manifest frame inventory is not complete")
    names = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise StreamHeaderError(f"manifest frame[{index}] lacks a path")
        path = Path(ref["path"]).expanduser().resolve()
        if path.parent != raw_root:
            raise StreamHeaderError(f"manifest frame[{index}] is outside raw root")
        match = FRAME_RE.fullmatch(path.name)
        if match is None or int(match.group(1)) != index:
            raise StreamHeaderError(f"manifest frame[{index}] is not contiguous")
        names.append(path.name)
    return {"declared_count": len(refs), "first_frame_name": names[0], "last_frame_name": names[-1], "contiguous": True}


def _source_paths(manifest: dict[str, Any]) -> dict[str, Path]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise StreamHeaderError("active stream manifest lacks inputs")
    keys = ("native_qa_report", "native_qa_manifest", "native_qa_request", "runparts", "generated_xml", "solver_receipt", "solver_request", "direct_converter", "bi4_dump", "timing_contract")
    paths: dict[str, Path] = {}
    for key in keys:
        if key not in inputs:
            raise StreamHeaderError(f"active stream manifest lacks {key}")
        paths[key], _ = bind_ref(inputs[key], key)
    return paths


def _same_path_or_explicit_alias(ref: Any, target: Path, label: str) -> dict[str, Any]:
    """Close a producer link without treating a same-case path as enough.

    Historical ROOT receipts sometimes retain the forensic worktree path while
    the consumer manifest is copied into the primary worktree.  A different
    path is accepted only when the referenced file is byte-identical and the
    reference carries a real SHA; ``PARENT_GUARD_COMPUTED`` cannot authorize an
    alias before the parent guard has measured its content.
    """
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise StreamHeaderError(f"{label} lacks a path")
    source = require_file(ref["path"], label)
    target = Path(target).expanduser().resolve()
    source_digest = sha256(source)
    target_digest = sha256(target)
    expected = ref.get("sha256")
    if expected and expected != "PARENT_GUARD_COMPUTED" and source_digest != str(expected):
        raise StreamHeaderError(f"{label} reference SHA differs: {source}")
    if source != target:
        if expected in (None, "PARENT_GUARD_COMPUTED") or source_digest != target_digest:
            raise StreamHeaderError(f"{label} is not the target or an explicitly byte-identical alias")
        alias = True
    else:
        alias = False
    return {
        "reference_path": str(source),
        "target_path": str(target),
        "sha256": source_digest,
        "byte_identical_alias": alias,
    }


def _validate_native_request(request: dict[str, Any], qa_manifest_path: Path, qa_manifest: dict[str, Any]) -> dict[str, Any]:
    if request.get("case_id") != "STAGE2_F2_COARSE_CANARY_NATIVE_QA_V1" or request.get("family_id") != "F2":
        raise StreamHeaderError("native QA request identity differs")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise StreamHeaderError("native QA request physical case differs")
    command = request.get("command")
    if not isinstance(command, list) or "--manifest" not in command:
        raise StreamHeaderError("native QA request has no manifest command binding")
    manifest_index = command.index("--manifest")
    if manifest_index + 1 >= len(command):
        raise StreamHeaderError("native QA request has no manifest path")
    request_manifest = require_file(command[manifest_index + 1], "native QA request manifest")
    if str(request_manifest) not in [str(path) for path in request.get("input_files", [])]:
        raise StreamHeaderError("native QA request input files omit its manifest")
    if sha256(request_manifest) != sha256(qa_manifest_path):
        raise StreamHeaderError("native QA request manifest is not byte-identical to producer manifest")
    manifest_hash = (request.get("input_hashes") or {}).get(str(request_manifest))
    if manifest_hash and manifest_hash != sha256(qa_manifest_path):
        raise StreamHeaderError("native QA request manifest input hash differs")
    for key in ("hdf5_read", "solver_launch", "gencase_launch", "gpu_launch"):
        if request.get(key) is True:
            raise StreamHeaderError(f"native QA request enables forbidden {key}")
    if request.get("execution_allowed") is not True:
        raise StreamHeaderError("native QA request was not an executable producer request")
    return {
        "schema": request.get("schema"),
        "attempt_id": request.get("attempt_id"),
        "manifest_binding": _same_path_or_explicit_alias(
            {"path": str(request_manifest), "sha256": sha256(request_manifest)},
            qa_manifest_path,
            "native QA request manifest",
        ),
        "read_policy": {
            "hdf5_read": request.get("hdf5_read"),
            "solver_launch": request.get("solver_launch"),
            "gencase_launch": request.get("gencase_launch"),
            "gpu_launch": request.get("gpu_launch"),
        },
    }


def _validate_native_source_contract(paths: dict[str, Path], manifest: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    """Validate producer identity before the official one-frame decoder opens data."""
    qa_manifest = read_json(paths["native_qa_manifest"], "native QA manifest")
    qa_report = read_json(paths["native_qa_report"], "native QA report")
    qa_request = read_json(paths["native_qa_request"], "native QA request")
    if qa_manifest.get("schema") != "ds02.stage2.f2.coarse-canary-native-qa.manifest.v1":
        raise StreamHeaderError("native QA manifest schema differs")
    if qa_manifest.get("case_id") != CASE_KEY or qa_manifest.get("family_id") != "F2" or qa_manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise StreamHeaderError("native QA manifest physical identity differs")
    source_scope = qa_manifest.get("source_scope") or {}
    if source_scope.get("old_1078_identity_rows_reused") is not False:
        raise StreamHeaderError("native QA manifest does not reject old 1078 identity reuse")
    if source_scope.get("raw_data_root") != str(raw_root):
        raise StreamHeaderError("native QA raw data root differs from active stream raw root")
    if source_scope.get("part_frames_are_forbidden") is not True:
        raise StreamHeaderError("native QA source scope does not forbid Part frames")
    report_manifest = qa_report.get("manifest")
    if not isinstance(report_manifest, dict) or report_manifest.get("path") != str(paths["native_qa_manifest"]):
        raise StreamHeaderError("native QA report does not bind exact producer manifest")
    if report_manifest.get("sha256") != sha256(paths["native_qa_manifest"]):
        raise StreamHeaderError("native QA report manifest SHA differs")
    report_solver = qa_report.get("solver_receipt")
    if not isinstance(report_solver, dict) or report_solver.get("path") != str(paths["solver_receipt"]):
        raise StreamHeaderError("native QA report does not bind exact solver receipt")
    if report_solver.get("sha256") != sha256(paths["solver_receipt"]):
        raise StreamHeaderError("native QA report solver receipt SHA differs")
    if qa_report.get("schema") != "ds02.stage2.f2.coarse-canary-native-qa.v1" or qa_report.get("status") != "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA":
        raise StreamHeaderError("native QA report is not the completed producer product")
    policy = qa_report.get("read_policy") or {}
    for key in ("trajectory_h5_opened", "part_frames_opened", "generated_bi4_decoded", "solver_started", "gencase_started", "model_or_cfd_started", "old_products_modified"):
        if policy.get(key) is not False:
            raise StreamHeaderError(f"native QA read policy is not closed for {key}")
    cause = qa_report.get("source_cause") or {}
    for key in ("physical_fate", "legal_outflow_or_spill", "dynamical_impact"):
        if cause.get(key) not in {"UNKNOWN", "UNKNOWN_NOT_PROVEN", "UNKNOWN; saved record brackets only"}:
            raise StreamHeaderError(f"native QA report widens physical claim boundary for {key}")
    rows = (qa_report.get("native_identity") or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise StreamHeaderError("native QA report has no native identity rows")
    qa_inputs = qa_manifest.get("inputs") or {}
    qa_xml_link = _same_path_or_explicit_alias(qa_inputs.get("generated_xml"), paths["generated_xml"], "native QA generated XML")
    qa_receipt_link = _same_path_or_explicit_alias(qa_inputs.get("solver_receipt"), paths["solver_receipt"], "native QA solver receipt")
    qa_solver_request_link = _same_path_or_explicit_alias(qa_inputs.get("solver_request"), paths["solver_request"], "native QA solver request")
    qa_request_contract = _validate_native_request(qa_request, paths["native_qa_manifest"], qa_manifest)
    solver_request = read_json(paths["solver_request"], "solver request")
    solver_receipt = read_json(paths["solver_receipt"], "solver receipt")
    if solver_request.get("schema") != "ds02.stage2.external-solver-request.v5" or solver_request.get("case_id") != CASE_KEY or solver_request.get("family_id") != "F2":
        raise StreamHeaderError("solver request identity differs")
    if solver_receipt.get("schema") != "ds02.stage2.external-solver-report.v5" or solver_receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise StreamHeaderError("solver receipt is not the completed external v5 product")
    receipt_request = solver_receipt.get("request") or {}
    if receipt_request.get("path") != str(paths["solver_request"]) or receipt_request.get("sha256") != sha256(paths["solver_request"]):
        raise StreamHeaderError("solver receipt does not bind exact solver request")
    command = solver_request.get("command")
    launch = (solver_receipt.get("execution") or {}).get("launch_argv")
    if not isinstance(command, list) or not isinstance(launch, list) or len(command) < 4 or len(launch) < 4:
        raise StreamHeaderError("solver request/receipt command binding is incomplete")
    generated_from_request = Path(str(command[2])).expanduser().resolve().with_suffix(".xml")
    generated_from_receipt = Path(str(launch[2])).expanduser().resolve().with_suffix(".xml")
    if generated_from_request != paths["generated_xml"] or generated_from_receipt != paths["generated_xml"]:
        raise StreamHeaderError("solver request/receipt generated source differs")
    output_root = Path(str(launch[3])).expanduser().resolve()
    if output_root != paths["runparts"].parent.resolve() or output_root != raw_root.parent.resolve():
        raise StreamHeaderError("solver receipt output root differs from active raw root")
    expected = manifest.get("expected") or {}
    generated = qa_report.get("generated_particles") or {}
    if generated.get("particles") != expected.get("initial_particles_total") or generated.get("fluid_count") != expected.get("initial_fluid_count"):
        raise StreamHeaderError("native QA generated particle counts differ from V6 manifest")
    if float(generated.get("massfluid_kg")) != float(expected.get("massfluid_kg")):
        raise StreamHeaderError("native QA generated MassFluid differs from V6 manifest")
    return {
        "native_qa": {
            "report_status": qa_report.get("status"),
            "row_count": (qa_report.get("native_identity") or {}).get("row_count"),
            "manifest": _same_path_or_explicit_alias(report_manifest, paths["native_qa_manifest"], "native QA report manifest"),
            "solver_receipt": _same_path_or_explicit_alias(report_solver, paths["solver_receipt"], "native QA report solver receipt"),
            "request": qa_request_contract,
        },
        "qa_manifest_inputs": {
            "generated_xml": qa_xml_link,
            "solver_receipt": qa_receipt_link,
            "solver_request": qa_solver_request_link,
        },
        "solver": {
            "request_schema": solver_request.get("schema"),
            "receipt_schema": solver_receipt.get("schema"),
            "receipt_status": solver_receipt.get("status"),
            "output_root": str(output_root),
            "generated_xml_path": str(paths["generated_xml"]),
        },
        "source_scope": {
            "raw_data_root": str(raw_root),
            "all_links_exact_or_byte_identical": True,
            "arrays_opened_by_header_probe": False,
        },
    }


def _probe_decoder(decoder: Path, frame: Path, scratch_parent: Path, max_scratch_bytes: int, max_seconds: float, poll_interval: float) -> tuple[dict[str, dict[str, Any]], dict[str, Any], int]:
    prefix = scratch_parent / "frame_0000"
    command = [str(decoder), str(frame), str(prefix)]
    process: subprocess.Popen[str] | None = None
    stderr = ""
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        raise StreamHeaderError(f"cannot launch official BI4 decoder: {decoder}") from exc
    peak = 0
    deadline = time.monotonic() + max_seconds

    def reap_bounded(*, kill: bool) -> str:
        if process is None:
            return ""
        if kill and process.poll() is None:
            process.kill()
        try:
            _out, err = process.communicate(timeout=10)
            return (err or "")[-1000:]
        except subprocess.TimeoutExpired:
            # A decoder that ignores SIGKILL is still not allowed to escape the
            # actor.  One bounded retry records the cleanup failure and returns.
            try:
                process.kill()
                _out, err = process.communicate(timeout=2)
                return (err or "")[-1000:]
            except subprocess.TimeoutExpired:
                return "decoder process did not reap within bounded cleanup"

    try:
        while process.poll() is None:
            peak = max(peak, directory_bytes(scratch_parent))
            if peak > max_scratch_bytes:
                stderr = reap_bounded(kill=True)
                raise StreamHeaderError(f"header probe scratch exceeded {max_scratch_bytes} bytes: {stderr[-500:]}")
            if time.monotonic() > deadline:
                stderr = reap_bounded(kill=True)
                raise StreamHeaderError(f"header probe exceeded {max_seconds}s")
            time.sleep(poll_interval)
        stderr = reap_bounded(kill=False)
        peak = max(peak, directory_bytes(scratch_parent))
        if peak > max_scratch_bytes:
            raise StreamHeaderError(f"header probe scratch exceeded final limit {max_scratch_bytes}: {peak}")
    finally:
        # Covers directory polling, XML parsing, and any unexpected exception
        # while the official child is still alive.  Cleanup is finite and only
        # targets this decoder process.
        if process is not None and process.poll() is None:
            cleanup_stderr = reap_bounded(kill=True)
            if not stderr:
                stderr = cleanup_stderr
    if process.returncode != 0:
        raise StreamHeaderError(f"official BI4 decoder failed for first frame: {stderr[-1000:]}")
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.is_file():
        raise StreamHeaderError("official BI4 decoder produced no header XML")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise StreamHeaderError("official BI4 header XML is malformed") from exc
    fields = _named_fields(root)
    xml_record = {
        "path": str(xml_path),
        "bytes": xml_path.stat().st_size,
        "sha256": sha256(xml_path),
        "fields_seen": sorted(fields),
    }
    return fields, xml_record, peak


def _atomic_probe(manifest: dict[str, Any], manifest_path: Path, paths: dict[str, Path], source_contract: dict[str, Any], first_frame: Path, first_frame_stat: dict[str, Any], output_path: Path) -> dict[str, Any]:
    expected = manifest.get("expected") or {}
    source = _source_mass(paths["generated_xml"], expected)
    pre = {
        "small_inputs": {key: stat_record(path) for key, path in paths.items()},
        "first_frame": first_frame_stat,
    }
    scratch_limit = int((manifest.get("runtime") or {}).get("max_scratch_bytes", 128 * 1024 * 1024))
    scratch_parent = Path(output_path).expanduser().resolve().parent
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ds02-f2-coarse-header-v6-", dir=str(scratch_parent)) as scratch:
        fields, decoder_xml, scratch_peak = _probe_decoder(
            paths["bi4_dump"],
            first_frame,
            Path(scratch),
            scratch_limit,
            float((manifest.get("runtime") or {}).get("max_decoder_seconds_per_frame", 180.0)),
            float((manifest.get("runtime") or {}).get("scratch_poll_interval_s", 0.01)),
        )
    post = {
        "small_inputs": {key: stat_record(path) for key, path in paths.items()},
        "first_frame": stat_record(first_frame),
    }
    mass = _mass_contract(source, fields)
    dynamic = _validate_dynamic_contract(fields)
    output = {
        "schema": SCHEMA,
        "status": "HEADER_PROBE_COMPLETED_NO_FULL_STREAM_CREDIT",
        "case_key": CASE_KEY,
        "physical_case_id": PHYSICAL_CASE_ID,
        "probe_scope": {
            "mode": "first_frame_header_only",
            "frame_index": 0,
            "declared_frame_count": int(expected.get("frame_count", 0)),
            "remaining_frames_opened": 0,
            "full_stream_credit": "NONE_UNTIL_SEPARATE_V6_FULL_STREAM_RECEIPT",
        },
        "source": {key: stat_record(path) for key, path in paths.items()},
        "source_contract": source_contract,
        "raw_source": {
            "root": str(Path(manifest["raw_data_root"]["path"]).expanduser().resolve()),
            "first_frame": first_frame_stat,
            "first_frame_sha256": first_frame_stat["sha256"],
            "content_binding": "full SHA/stat pre-decoder and full SHA/stat post-decoder; only Part_0000.bi4 is opened",
        },
        "frame_inventory": _frame_inventory(manifest, Path(manifest["raw_data_root"]["path"]).expanduser().resolve()),
        "generated_xml_source_mass": source,
        "official_header": {
            "decoder_xml": decoder_xml,
            "selected_fields": {key: fields[key] for key in ("CaseNp", "CaseNfluid", "MassFluid", "MassBound", "TimeStep") if key in fields},
            "all_field_names": sorted(fields),
            "dynamic_contract": dynamic,
        },
        "massfluid_contract": mass,
        "decoder_cost": {
            "frames_decoded": 1,
            "decoder_input_bytes": first_frame.stat().st_size,
            "minimum_first_frame_content_reads": 3,
            "scratch_limit_bytes": scratch_limit,
            "scratch_peak_bytes": scratch_peak,
            "scratch_after_cleanup_bytes": 0,
            "arrays_read_by_worker": False,
            "hdf5_written": False,
        },
        "input_stability": {"pre": pre, "post": post, "small_inputs_equal": pre["small_inputs"] == post["small_inputs"], "first_frame_stat_equal": pre["first_frame"] == post["first_frame"]},
        "read_policy": {
            "first_bi4_frame_opened_by_official_decoder": True,
            "remaining_bi4_frames_opened": False,
            "decoded_binary_arrays_read_by_worker": False,
            "trajectory_h5_opened": False,
            "solver_started": False,
            "model_or_cfd_started": False,
            "old_products_modified": False,
        },
        "claim_boundary": {
            "header_type_and_serialization": "OBSERVED_SOURCE_CONTRACT_ONLY",
            "native_numerical_cause": "NOT_REASSESSED_BY_HEADER_PROBE",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "manifest": stat_record(manifest_path),
    }
    if not output["input_stability"]["small_inputs_equal"] or not output["input_stability"]["first_frame_stat_equal"]:
        raise StreamHeaderError("source changed during first-frame header probe")
    return output


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "active stream manifest")
    manifest = read_json(manifest_path, "active stream manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise StreamHeaderError("unsupported active stream manifest schema")
    if manifest.get("case_key") != CASE_KEY or manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise StreamHeaderError("active stream case identity differs")
    if manifest.get("probe_mode") != "first_frame_header_only":
        raise StreamHeaderError("V6 only accepts first_frame_header_only mode")
    paths = _source_paths(manifest)
    raw_root = Path((manifest.get("raw_data_root") or {}).get("path", "")).expanduser().resolve()
    if not raw_root.is_dir():
        raise StreamHeaderError(f"raw data root is not a directory: {raw_root}")
    source_contract = _validate_native_source_contract(paths, manifest, raw_root)
    _frame_inventory(manifest, raw_root)
    refs = manifest.get("frames")
    if not isinstance(refs, list) or not refs:
        raise StreamHeaderError("manifest lacks first-frame reference")
    first_frame, first_stat = bind_frame_stat(refs[0], raw_root, "frame[0]")
    report = _atomic_probe(manifest, manifest_path, paths, source_contract, first_frame, first_stat, output_path)
    atomic_json(output_path, report)
    return {"schema": report["schema"], "status": report["status"], "frame_index": 0, "mass_contract_status": report["massfluid_contract"]["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 coarse active stream v5 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
