#!/usr/bin/env python3
"""Bounded raw-byte proof for the first F2 BI4 MassFluid scalar.

V6 established the typed value exposed by the official BI4 decoder, but the
decoder's XML does not expose the bytes from which that value was obtained.
This forward-only worker follows the pinned JBinaryData layout, discovers the
serialized ``MassFluid`` value offset in the first ``Part_0000.bi4`` header,
and reads exactly that scalar after the parent guard.  It does not invoke the
decoder, open any particle array, or open any of the other 400 frames.

The source contract is deliberately strict: DatDouble (enum 12), eight
little-endian bytes, and the official JBinaryData/JPartDataBi4/JSph write path
must be bound by source SHA.  The output records the discovered byte offset
and the original eight bytes.  It grants no physical, numerical, or mass-
qualification credit; it only resolves whether the typed header value agrees
with the serialized scalar.  Full-stream credit remains explicitly outside
this worker's scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f2.coarse-active-stream.v7"
MANIFEST_SCHEMA = "ds02.stage2.f2.coarse-active-stream.manifest.v7"
SOURCE_CONTRACT_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v7.massfluid-source-contract.v1"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
PHYSICAL_CASE_ID = CASE_KEY
HEADER_SIZE = 64
MAX_HEADER_PREFIX_BYTES = 1024 * 1024


class RawHeaderError(ValueError):
    """Raised when the source-bound scalar proof cannot close."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_record(path: Path, *, digest: str | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise RawHeaderError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        **({"sha256": digest} if digest is not None else {}),
    }


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RawHeaderError(f"{label} is not a regular file: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawHeaderError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RawHeaderError(f"{label} is not a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise RawHeaderError(f"refusing to overwrite existing output: {path}")
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


def bind_small_ref(ref: Any, label: str, *, digest_required: bool = True) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise RawHeaderError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    actual = stat_record(path, digest=sha256(path))
    expected = ref.get("sha256")
    if digest_required and (not expected or expected == "PARENT_GUARD_COMPUTED"):
        raise RawHeaderError(f"{label} lacks a completed content SHA")
    if expected and expected != "PARENT_GUARD_COMPUTED" and actual["sha256"] != str(expected):
        raise RawHeaderError(f"{label} SHA differs: {path}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and actual[field] != int(ref[field]):
            raise RawHeaderError(f"{label} {field} differs: {path}")
    return path, actual


def bind_frame_ref(ref: Any, label: str) -> tuple[Path, dict[str, Any]]:
    """Bind the parent-measured full SHA without hashing the frame again.

    V7 is intentionally a prefix/scalar read.  The V6 producer's full first
    frame SHA is therefore a required predecessor fact.  V7 compares the
    path/stat tuple before and after its bounded read and reports that the
    content SHA is inherited from the V6 parent guard rather than recomputed.
    """
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise RawHeaderError(f"{label} lacks a path")
    path = require_file(ref["path"], label)
    expected_sha = ref.get("parent_full_sha256", ref.get("sha256"))
    if not isinstance(expected_sha, str) or expected_sha in {"", "PARENT_GUARD_COMPUTED"}:
        raise RawHeaderError(f"{label} requires the completed V6 parent full SHA")
    stat = stat_record(path)
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if ref.get(field) is not None and stat[field] != int(ref[field]):
            raise RawHeaderError(f"{label} {field} differs: {path}")
    return path, {**stat, "parent_full_sha256": expected_sha, "content_sha256_recomputed": False}


def _require_equal(left: Any, right: Any, label: str) -> None:
    if left != right:
        raise RawHeaderError(f"{label} differs: {left!r} != {right!r}")


def _validate_v6_report(report: dict[str, Any], v6_report_path: Path, first_frame: Path, frame_ref: dict[str, Any]) -> dict[str, Any]:
    _require_equal(report.get("schema"), "ds02.stage2.f2.coarse-active-stream.v6", "V6 report schema")
    _require_equal(report.get("case_key"), CASE_KEY, "V6 case key")
    _require_equal(report.get("physical_case_id"), PHYSICAL_CASE_ID, "V6 physical case")
    _require_equal(report.get("status"), "HEADER_PROBE_COMPLETED_NO_FULL_STREAM_CREDIT", "V6 status")
    scope = report.get("probe_scope") or {}
    _require_equal(scope.get("remaining_frames_opened"), 0, "V6 remaining frame scope")
    raw = report.get("raw_source") or {}
    prior = raw.get("first_frame")
    if not isinstance(prior, dict):
        raise RawHeaderError("V6 report lacks first-frame predecessor record")
    _require_equal(Path(str(prior.get("path"))).expanduser().resolve(), first_frame, "V6 first-frame path")
    prior_sha = prior.get("sha256") or raw.get("first_frame_sha256")
    if not isinstance(prior_sha, str) or len(prior_sha) != 64:
        raise RawHeaderError("V6 report lacks completed first-frame SHA")
    _require_equal(frame_ref.get("parent_full_sha256"), prior_sha, "V7 frame predecessor SHA")
    mass = report.get("massfluid_contract") or {}
    _require_equal(mass.get("raw_header_bytes_observed"), False, "V6 raw-header state")
    header = mass.get("official_header") or {}
    _require_equal(header.get("tag"), "double", "V6 MassFluid typed tag")
    selected = (report.get("official_header") or {}).get("selected_fields") or {}
    mass_selected = selected.get("MassFluid")
    if not isinstance(mass_selected, dict) or not math.isfinite(float(mass_selected.get("value"))):
        raise RawHeaderError("V6 report lacks finite typed MassFluid")
    claim = report.get("claim_boundary") or {}
    for key in ("physical_fate", "legal_flux", "dynamical_impact", "QI", "QN", "QE"):
        if claim.get(key) != "UNKNOWN":
            raise RawHeaderError(f"V6 claim boundary widens {key}")
    return {
        "report": stat_record(v6_report_path, digest=sha256(v6_report_path)),
        "first_frame_sha256": prior_sha,
        "mass_header": mass_selected,
        "mass_contract": mass,
        "source_xml_value_kg": float(mass.get("source_xml_value_kg")),
    }


def _validate_source_contract(contract: dict[str, Any], manifest: dict[str, Any], source_contract_path: Path) -> dict[str, Any]:
    _require_equal(contract.get("schema"), SOURCE_CONTRACT_SCHEMA, "source contract schema")
    serialization = contract.get("serialization") or {}
    _require_equal(serialization.get("format"), "JBinaryData", "serialization format")
    header = serialization.get("header_layout") or {}
    _require_equal(header.get("size_bytes"), HEADER_SIZE, "JBinaryData header size")
    _require_equal(header.get("byte_order"), "little", "source byte order")
    target = serialization.get("target") or {}
    _require_equal(target.get("field_name"), "MassFluid", "source target field")
    _require_equal(target.get("type_enum"), 12, "source target type enum")
    _require_equal(target.get("type_name"), "DatDouble", "source target type name")
    _require_equal(target.get("value_bytes"), 8, "source target byte width")
    _require_equal(target.get("item_path"), ["root"], "source target item path")
    if target.get("offset_mode") != "serialized_header_discovery":
        raise RawHeaderError("source target offset is not the bounded serialized-header discovery")
    files = contract.get("source_files")
    refs = manifest.get("source_files")
    if not isinstance(files, dict) or not isinstance(refs, dict):
        raise RawHeaderError("source contract/manifest source_files are incomplete")
    bound: dict[str, Any] = {"contract": stat_record(source_contract_path, digest=sha256(source_contract_path)), "files": {}}
    for role, expected in files.items():
        if not isinstance(expected, dict) or not isinstance(expected.get("sha256"), str):
            raise RawHeaderError(f"source contract role lacks SHA: {role}")
        if role not in refs:
            raise RawHeaderError(f"manifest omits source contract role: {role}")
        path, actual = bind_small_ref(refs[role], f"source file {role}")
        _require_equal(actual["sha256"], expected["sha256"], f"source file {role} contract SHA")
        bound["files"][role] = {**actual, "source_role": role}
    return bound


class PrefixReader:
    """Read only the serialized header prefix; seek skips array payloads."""

    def __init__(self, path: Path, *, max_read_bytes: int | None = None) -> None:
        self.path = Path(path)
        self.max_read_bytes = MAX_HEADER_PREFIX_BYTES if max_read_bytes is None else max_read_bytes
        self.offset = 0
        self.physical_bytes_read = 0
        self._stream = self.path.open("rb")

    def close(self) -> None:
        self._stream.close()

    def tell(self) -> int:
        return self.offset

    def read(self, size: int) -> bytes:
        if size < 0 or self.physical_bytes_read + size > self.max_read_bytes:
            raise RawHeaderError(f"serialized header prefix exceeded {self.max_read_bytes} bytes")
        data = self._stream.read(size)
        if len(data) != size:
            raise RawHeaderError(f"short serialized header read at offset {self.offset}")
        self.offset += size
        self.physical_bytes_read += size
        return data

    def skip(self, size: int) -> None:
        if size < 0:
            raise RawHeaderError("negative serialized-header skip")
        self._stream.seek(size, os.SEEK_CUR)
        self.offset += size

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def string(self) -> str:
        size = self.u32()
        raw = self.read(size)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RawHeaderError(f"serialized header string is not UTF-8 at {self.offset - size}") from exc


TYPE_SIZES = {
    2: 4,   # DatBool is serialized by InBool -> int.
    3: 1,
    4: 1,
    5: 2,
    6: 2,
    7: 4,
    8: 4,
    9: 8,
    10: 8,
    11: 4,
    12: 8,
    20: 12,
    21: 12,
    22: 12,
    23: 24,
}


def _skip_value(reader: PrefixReader, type_enum: int) -> None:
    if type_enum == 1:
        reader.skip(reader.u32())
    elif type_enum in TYPE_SIZES:
        reader.skip(TYPE_SIZES[type_enum])
    else:
        raise RawHeaderError(f"unsupported JBinaryData value type {type_enum}")


def _skip_array(reader: PrefixReader, si64: bool) -> None:
    definition_size = reader.u32()
    definition_start = reader.tell()
    if reader.string() != "\nARRAY":
        raise RawHeaderError("serialized header array marker differs")
    reader.string()  # array name
    reader.i32()    # hide, serialized as bool/int
    reader.i32()    # type
    if si64:
        reader.u64()
        data_size = reader.u64()
    else:
        reader.u32()
        data_size = reader.u32()
    if reader.tell() != definition_start + definition_size:
        raise RawHeaderError("serialized header array definition size differs")
    reader.skip(data_size)


def _find_massfluid_in_item(reader: PrefixReader, *, si64: bool, item_path: list[str], target_path: list[str]) -> dict[str, Any] | None:
    definition_size = reader.u32()
    definition_start = reader.tell()
    if reader.string() != "\nITEM\n":
        raise RawHeaderError("serialized header item marker differs")
    item_name = reader.string()
    current_path = item_path + [item_name]
    reader.i32()  # hide
    reader.i32()  # hidevalues
    reader.string()  # fmtfloat
    reader.string()  # fmtdouble
    array_count = reader.u32()
    child_count = reader.u32()
    values_size = reader.u32()
    if reader.tell() != definition_start + definition_size:
        raise RawHeaderError("serialized header item definition size differs")
    if values_size:
        values_start = reader.tell()
        if reader.string() != "\nVALUES":
            raise RawHeaderError("serialized header values marker differs")
        value_count = reader.u32()
        found: dict[str, Any] | None = None
        for value_index in range(value_count):
            value_name = reader.string()
            type_enum = reader.i32()
            value_offset = reader.tell()
            if value_name == "MassFluid" and current_path == target_path:
                if found is not None:
                    raise RawHeaderError("serialized header MassFluid is ambiguous")
                if type_enum != 12:
                    raise RawHeaderError(f"serialized header MassFluid type is {type_enum}, expected DatDouble=12")
                raw = reader.read(TYPE_SIZES[type_enum])
                found = {
                    "item_path": current_path,
                    "field_name": value_name,
                    "value_index": value_index,
                    "type_enum": type_enum,
                    "type_name": "DatDouble",
                    "offset": value_offset,
                    "byte_count": len(raw),
                    "raw_bytes": raw,
                }
            else:
                _skip_value(reader, type_enum)
        if reader.tell() != values_start + values_size:
            raise RawHeaderError("serialized header values size differs")
        if found is not None:
            return found
    for _ in range(array_count):
        _skip_array(reader, si64)
    for _ in range(child_count):
        found = _find_massfluid_in_item(reader, si64=si64, item_path=current_path, target_path=target_path)
        if found is not None:
            return found
    return None


def discover_massfluid(path: Path, *, target_path: list[str] = ["root"]) -> dict[str, Any]:
    reader = PrefixReader(path)
    try:
        header = reader.read(HEADER_SIZE)
        title = header[:60].rstrip(b"\0 \n").decode("latin1")
        byte_order = header[60]
        si64_marker = header[61]
        if byte_order not in (0, 10):
            raise RawHeaderError(f"unsupported JBinaryData byte order marker {byte_order}")
        if byte_order == 10:
            si64 = True
        else:
            si64 = bool(si64_marker)
        if byte_order != (10 if si64 else 0):
            raise RawHeaderError("JBinaryData size/byte-order markers are inconsistent")
        found = _find_massfluid_in_item(reader, si64=si64, item_path=[], target_path=target_path)
        if found is None:
            raise RawHeaderError(f"serialized header has no MassFluid at item path {target_path}")
        raw = found.pop("raw_bytes")
        if len(raw) != 8:
            raise RawHeaderError("serialized DatDouble did not occupy eight bytes")
        found.update({
            "raw_bytes_hex": raw.hex(),
            "raw_bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "value_binary64_little": struct.unpack("<d", raw)[0],
            "serialized_header_title": title,
            "serialized_header_byte_order": "little",
            "serialized_header_byte_order_marker": byte_order,
            "serialized_header_si64": si64,
            "header_prefix_span_bytes": reader.tell(),
            "header_prefix_physical_bytes_read": reader.physical_bytes_read,
            "payload_bytes_read": 0,
        })
        return found
    finally:
        reader.close()


def _compare_raw(raw: dict[str, Any], v6: dict[str, Any]) -> dict[str, Any]:
    typed = float(v6["mass_header"]["value"])
    xml = float(v6["source_xml_value_kg"])
    float32_xml = struct.unpack("<f", struct.pack("<f", xml))[0]
    raw_bytes = bytes.fromhex(str(raw["raw_bytes_hex"]))
    typed_bytes = struct.pack("<d", typed)
    xml_bytes = struct.pack("<d", xml)
    float32_bytes = struct.pack("<d", float32_xml)
    matches_typed = raw_bytes == typed_bytes
    matches_xml = raw_bytes == xml_bytes
    matches_float32 = raw_bytes == float32_bytes
    if matches_xml:
        status = "RAW_HEADER_DOUBLE_BYTES_MATCH_XML_BINARY64"
    elif matches_float32 and matches_typed:
        status = "RAW_HEADER_DOUBLE_BYTES_MATCH_FLOAT32_WIDENED_VALUE"
    elif matches_typed:
        status = "RAW_HEADER_DOUBLE_BYTES_MATCH_TYPED_VALUE_ONLY"
    else:
        status = "RAW_HEADER_DOUBLE_BYTES_DO_NOT_MATCH_TYPED_VALUE"
    return {
        "source_xml_value_kg": xml,
        "v6_typed_value_kg": typed,
        "float32_round_value_kg": float32_xml,
        "raw_value_binary64_kg": raw["value_binary64_little"],
        "raw_bytes_hex": raw["raw_bytes_hex"],
        "raw_bytes_sha256": raw["raw_bytes_sha256"],
        "typed_binary64_bytes_hex": typed_bytes.hex(),
        "xml_binary64_bytes_hex": xml_bytes.hex(),
        "float32_widened_binary64_bytes_hex": float32_bytes.hex(),
        "matches_v6_typed_binary64": matches_typed,
        "matches_xml_binary64": matches_xml,
        "matches_float32_widened_binary64": matches_float32,
        "status": status,
        "scientific_credit": "NONE",
        "mass_qualification": "UNKNOWN_UNTIL_FULL_STREAM_AND_TASK_IMPACT_AUDIT",
    }


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "V7 manifest")
    manifest = read_json(manifest_path, "V7 manifest")
    _require_equal(manifest.get("schema"), MANIFEST_SCHEMA, "V7 manifest schema")
    _require_equal(manifest.get("case_key"), CASE_KEY, "V7 case key")
    _require_equal(manifest.get("physical_case_id"), PHYSICAL_CASE_ID, "V7 physical case")
    _require_equal(manifest.get("probe_mode"), "first_frame_raw_massfluid_scalar_only", "V7 probe mode")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise RawHeaderError("V7 manifest lacks inputs")
    v6_report_path, v6_report_stat = bind_small_ref(inputs.get("v6_report"), "V6 report")
    v6_manifest_path, v6_manifest_stat = bind_small_ref(inputs.get("v6_manifest"), "V6 manifest")
    source_contract_path, source_contract_stat = bind_small_ref(inputs.get("source_contract"), "source contract")
    v6_report = read_json(v6_report_path, "V6 report")
    source_contract = read_json(source_contract_path, "source contract")
    frame_ref = inputs.get("raw_first_frame")
    first_frame, frame_pre = bind_frame_ref(frame_ref, "first BI4 frame")
    v6 = _validate_v6_report(v6_report, v6_report_path, first_frame, frame_pre)
    if v6_manifest_stat["sha256"] != str((v6_report.get("manifest") or {}).get("sha256")):
        raise RawHeaderError("V7 V6 manifest does not bind the completed V6 report manifest")
    bound_sources = _validate_source_contract(source_contract, manifest, source_contract_path)
    raw = discover_massfluid(first_frame, target_path=(source_contract.get("serialization") or {}).get("target", {}).get("item_path", ["root"]))
    frame_post = stat_record(first_frame)
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if frame_pre[field] != frame_post[field]:
            raise RawHeaderError(f"first BI4 frame changed during raw scalar read: {field}")
    source_post = {
        role: stat_record(Path(record["path"]), digest=sha256(Path(record["path"])))
        for role, record in bound_sources["files"].items()
    }
    for role, before in bound_sources["files"].items():
        after = source_post[role]
        if before["sha256"] != after["sha256"] or any(before[field] != after[field] for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")):
            raise RawHeaderError(f"source file changed during raw scalar read: {role}")
    comparison = _compare_raw(raw, v6)
    output = {
        "schema": SCHEMA,
        "status": "RAW_HEADER_SCALAR_PROOF_COMPLETED_NO_FULL_STREAM_CREDIT",
        "case_key": CASE_KEY,
        "physical_case_id": PHYSICAL_CASE_ID,
        "probe_scope": {
            "mode": "first_frame_raw_massfluid_scalar_only",
            "frame_index": 0,
            "remaining_frames_opened": 0,
            "decoded_binary_arrays_read_by_worker": False,
            "official_decoder_invoked": False,
            "hdf5_opened": False,
        },
        "predecessor": {
            "v6_report": v6["report"],
            "v6_manifest": v6_manifest_stat,
            "v6_first_frame_full_sha256": v6["first_frame_sha256"],
        },
        "source_contract": {
            "contract": source_contract_stat,
            "serialization": source_contract.get("serialization"),
            "source_files": bound_sources["files"],
            "source_files_post": source_post,
        },
        "raw_source": {
            "first_frame": {
                "pre": frame_pre,
                "post": frame_post,
                "full_sha256": frame_pre["parent_full_sha256"],
                "full_sha256_origin": "V6 parent guard; V7 does not rehash the 23.8 MB frame",
            },
            "header_layout": {
                "format": "JBinaryData",
                "header_size_bytes": HEADER_SIZE,
                "item_path": raw["item_path"],
                "field_name": raw["field_name"],
                "value_index": raw["value_index"],
                "type_enum": raw["type_enum"],
                "type_name": raw["type_name"],
                "byte_order": raw["serialized_header_byte_order"],
                "value_offset_bytes": raw["offset"],
                "value_byte_count": raw["byte_count"],
                "prefix_span_bytes": raw["header_prefix_span_bytes"],
                "prefix_physical_bytes_read": raw["header_prefix_physical_bytes_read"],
                "payload_bytes_read": raw["payload_bytes_read"],
            },
            "massfluid_scalar": comparison,
        },
        "read_cost": {
            "first_frame_header_prefix_physical_bytes": raw["header_prefix_physical_bytes_read"],
            "first_frame_scalar_bytes": raw["byte_count"],
            "remaining_frame_bytes_read": 0,
            "scratch_peak_bytes": 0,
            "scratch_after_cleanup_bytes": 0,
            "arrays_read": False,
        },
        "input_stability": {
            "first_frame_stat_equal": all(frame_pre[field] == frame_post[field] for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")),
            "v6_report_sha256": v6_report_stat["sha256"],
            "v6_manifest_sha256": v6_manifest_stat["sha256"],
            "source_contract_sha256": source_contract_stat["sha256"],
        },
        "claim_boundary": {
            "serialization": "SOURCE_AND_RAW_BYTE_PROVEN_FOR_ONE_HEADER_SCALAR",
            "native_numerical_cause": "NOT_REASSESSED",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "manifest": stat_record(manifest_path, digest=sha256(manifest_path)),
    }
    atomic_json(output_path, output)
    return {
        "schema": output["schema"],
        "status": output["status"],
        "value_offset_bytes": raw["offset"],
        "raw_bytes_hex": raw["raw_bytes_hex"],
        "mass_status": comparison["status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.manifest, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 coarse active stream v7 failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
