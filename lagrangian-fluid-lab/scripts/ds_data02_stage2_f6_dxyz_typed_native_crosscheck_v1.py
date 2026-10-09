#!/usr/bin/env python3
"""Guarded typed/native first-missing crosscheck for one F6 DXYZ case.

Prepare opens only bounded source-bound JSON and records stat metadata for the
large typed JSONL and native CSV files.  Audit is the post-reservation worker:
it streams the typed records once, then reads the small native PartOut/RunPARTs
CSV inputs, and joins exact (Zone, Idp) identities and saved brackets.  The
historical native numerical-exclusion report and this new typed/native join are
separate evidence layers.  A saved-frame join does not establish continuous
event time, physical fate, legal flux, or dynamics; those remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, BinaryIO, Iterable


SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

SCHEMA = "ds02.stage2.f6-dxyz-typed-native-crosscheck.v1"
CONTRACT_SCHEMA = "ds02.stage2.f6-dxyz-typed-native-crosscheck-contract.v1"
REQUEST_SCHEMA = "ds02.request.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
SCOPE_SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v2"
OMISSION_SCHEMA = "ds02.stage2.omission-forensics.v2"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v4"
RECORD_SCHEMA = "ds02.stage2.typed-lifecycle-records.v4"
EXPECTED_RECORD_FIELDS = "one row per static (Zone, Idp); saved-frame lifecycle only"

CASE_ID = "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025"
FAMILY_ID = "F6"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT203_PROOF_SHA256 = "e146f0a378f56eccc59c5052aa27703322c40712192f38e9c5edce7acb87793c"
ROOT203_SUMMARY_SHA256 = "9bad57edd08f6013b27029b8ce446093b395496029087ad557991fa2e47e3fc3"
NATIVE_REPORT_SHA256 = "c685de5a59051dab934b1a621efe61bedbd54eec4ef8ebb00366b7db56acbe9b"
SCAN_SHA256 = "303a5d4305c4b522132c16f6f379d79eb6a39e43d37d5f25323ae7e5c39ffb12"
CONVERSION_SHA256 = "c00a5f9831ec17b618ba10a391ac698d8e588f2c5e910cab673b170f7d4830dd"
GENERATED_XML_SHA256 = "b6e82d64bd52b5179d03fc925d42463087da729599e9f32e351c0c6cf183a645"
PARTOUT_SHA256 = "7498584ac99cab89e4507eb75a94c25b781f816d671de67d8a9b8d08c7806d5e"
RUNPARTS_SHA256 = "ec7f6adb1e6baa30575c04394b5a847e6b416a386f92bae8dfcf84135adeddde"
RECORDS_SHA256 = "a3e48a0d297068e03167e12da745613f3a38db3eed84303f6fdad8b8f2d461e3"

MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
FORBIDDEN_DEFERRED_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}


class CrosscheckError(ValueError):
    """Raised when the source or typed/native identity contract is open."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CrosscheckError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise CrosscheckError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, allow_deferred: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise CrosscheckError(f"{label} lacks a path")
    result = Path(value).expanduser().resolve()
    if not allow_deferred and result.suffix.lower() in FORBIDDEN_DEFERRED_SUFFIXES:
        raise CrosscheckError(f"{label} is deferred payload content: {result}")
    if not result.is_file():
        raise CrosscheckError(f"{label} is missing: {result}")
    return result


def _stat(path: Path, label: str, *, allow_deferred: bool = False) -> dict[str, Any]:
    path = _path(path, label, allow_deferred=allow_deferred)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _sha256_file(path: Path, *, max_bytes: int | None = None) -> str:
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise CrosscheckError(f"refusing to hash {size} bytes above bound {max_bytes}: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_small_json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise CrosscheckError(f"{label} exceeds bounded JSON read size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CrosscheckError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CrosscheckError(f"{label} must be a JSON object")
    return value


def _hash_small_json(path: Path, label: str, expected: str) -> dict[str, Any]:
    path = _path(path, label)
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise CrosscheckError(f"{label} exceeds bounded hash size")
    expected = _sha(expected, f"{label} expected SHA")
    actual = _sha256_file(path, max_bytes=MAX_SMALL_BYTES)
    if actual != expected:
        raise CrosscheckError(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred_ref(path: Path, label: str, expected: str, expected_bytes: int, expected_rows: int | None = None) -> dict[str, Any]:
    """Stat a JSONL only; this function intentionally never opens it."""
    if path.suffix.lower() != ".jsonl":
        raise CrosscheckError(f"{label} must be JSONL: {path}")
    stat = _stat(path, label, allow_deferred=True)
    expected = _sha(expected, f"{label} expected SHA")
    if stat["bytes"] != int(expected_bytes):
        raise CrosscheckError(f"{label} bytes differ: expected {expected_bytes}, got {stat['bytes']}")
    result: dict[str, Any] = {
        **stat,
        "sha256": expected,
        "rows": int(expected_rows) if expected_rows is not None else None,
        "content_opened": False,
        "hash_checked": False,
        "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS",
    }
    return result


def _same_path(value: Any, path: Path) -> bool:
    try:
        return Path(value).expanduser().resolve() == path.resolve()
    except (TypeError, ValueError, OSError):
        return False


_STAT_FIELDS = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")


def _require_same_stat(actual: dict[str, Any], declared: dict[str, Any], label: str) -> None:
    """Require the exact deferred-file identity captured by prepare.

    A same-size replacement is still a different input: inode and both time
    fields are part of the producer edge.  ``content_opened`` and
    ``hash_checked`` are policy annotations and are deliberately excluded.
    """
    if not isinstance(declared, dict):
        raise CrosscheckError(f"{label} declared stat is missing")
    for field in _STAT_FIELDS:
        if actual.get(field) != declared.get(field):
            raise CrosscheckError(f"{label} stat differs at {field}")


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CrosscheckError(f"{label} must be a finite number")
    return float(value)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CrosscheckError(f"{label} must be an integer")
    return int(value)


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise CrosscheckError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise CrosscheckError(f"output exceeds {max_bytes} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _current_case(current: dict[str, Any], case_id: str) -> dict[str, Any]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise CrosscheckError("CURRENT schema differs")
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise CrosscheckError("CURRENT must contain exactly 336 cases")
    matches = [row for row in cases if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise CrosscheckError(f"CURRENT case is not unique: {case_id}")
    row = matches[0]
    if row.get("family_id") != FAMILY_ID:
        raise CrosscheckError("CURRENT family differs")
    trajectory = row.get("trajectory")
    if not isinstance(trajectory, dict):
        raise CrosscheckError("CURRENT trajectory metadata is missing")
    return row


def _validate_native_report(native: dict[str, Any], current_row: dict[str, Any], case_id: str) -> dict[str, Any]:
    if native.get("schema") != OMISSION_SCHEMA or native.get("status") != "CAUSES_RECONCILED":
        raise CrosscheckError("native omission report schema/status differs")
    if native.get("physical_case_id") != case_id or native.get("family_id") != FAMILY_ID:
        raise CrosscheckError("native omission report identity differs")
    trajectory = native.get("trajectory")
    current_trajectory = current_row.get("trajectory")
    if not isinstance(trajectory, dict) or not isinstance(current_trajectory, dict):
        raise CrosscheckError("native/current trajectory metadata is missing")
    if not _same_path(trajectory.get("path"), Path(str(current_trajectory.get("path")))):
        raise CrosscheckError("native report trajectory path differs from CURRENT")
    if _sha(trajectory.get("sha256"), "native trajectory SHA") != _sha(current_trajectory.get("producer_declared_sha256"), "CURRENT trajectory SHA"):
        raise CrosscheckError("native report trajectory SHA differs from CURRENT")
    if native.get("physical_fate") != "UNKNOWN; native numerical exclusion is not proof of physical spill":
        raise CrosscheckError("native report must preserve UNKNOWN physical fate")
    typed = native.get("typed_identity")
    ids = typed.get("ids") if isinstance(typed, dict) else None
    excluded = native.get("excluded_particles")
    if not isinstance(typed, dict) or typed.get("identity_key") != "(Zone,Idp)" or not isinstance(ids, list):
        raise CrosscheckError("native typed identity evidence is missing")
    if not isinstance(excluded, list):
        raise CrosscheckError("native excluded particle evidence is missing")
    typed_rows: dict[tuple[int, int], dict[str, Any]] = {}
    for index, item in enumerate(ids):
        if not isinstance(item, dict):
            raise CrosscheckError(f"native typed identity row {index} is malformed")
        key = (_integer(item.get("zone"), f"native id {index} zone"), _integer(item.get("idp"), f"native id {index} Idp"))
        if key in typed_rows:
            raise CrosscheckError(f"duplicate native typed identity: {key}")
        typed_rows[key] = item
    excluded_rows: dict[tuple[int, int], dict[str, Any]] = {}
    for index, item in enumerate(excluded):
        if not isinstance(item, dict):
            raise CrosscheckError(f"native excluded row {index} is malformed")
        key = (_integer(item.get("zone"), f"native excluded {index} zone"), _integer(item.get("idp"), f"native excluded {index} Idp"))
        if key in excluded_rows:
            raise CrosscheckError(f"duplicate native excluded identity: {key}")
        excluded_rows[key] = item
        frame_value = item.get("first_missing_frame")
        if frame_value is not None:
            frame = _integer(frame_value, f"native {key} first_missing_frame")
            if frame < 0:
                raise CrosscheckError(f"native {key} first_missing_frame is negative")
        bracket = item.get("first_missing_bracket_s")
        if bracket is not None:
            if not isinstance(bracket, list) or len(bracket) != 2:
                raise CrosscheckError(f"native {key} saved bracket is malformed")
            _finite(bracket[0], f"native {key} bracket lower")
            _finite(bracket[1], f"native {key} bracket upper")
    if set(typed_rows) != set(excluded_rows):
        raise CrosscheckError("native typed IDs and excluded IDs differ")
    return {"ids": typed_rows, "excluded": excluded_rows}


def _validate_summary(summary: dict[str, Any], summary_path: Path, current_row: dict[str, Any], case_id: str, current_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if summary.get("schema") != SUMMARY_SCHEMA or summary.get("status") != "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT":
        raise CrosscheckError("typed summary schema/status differs")
    if summary.get("physical_case_id") != case_id or summary.get("family_id") != FAMILY_ID:
        raise CrosscheckError("typed summary identity differs")
    source = summary.get("source")
    trajectory = source.get("trajectory_h5") if isinstance(source, dict) else None
    current_trajectory = current_row.get("trajectory")
    if not isinstance(source, dict) or not isinstance(trajectory, dict) or source.get("current336_sha256") != current_sha:
        raise CrosscheckError("typed summary CURRENT/source closure differs")
    if not _same_path(trajectory.get("path"), Path(str(current_trajectory.get("path")))):
        raise CrosscheckError("typed summary trajectory path differs")
    if _sha(trajectory.get("known_sha256"), "typed summary trajectory SHA") != _sha(current_trajectory.get("producer_declared_sha256"), "CURRENT trajectory SHA"):
        raise CrosscheckError("typed summary trajectory SHA differs")
    timeline = summary.get("timeline")
    if not isinstance(timeline, dict) or int(timeline.get("frames", -1)) != int(current_row.get("frames", -2)) or int(timeline.get("particles", -1)) != int(current_row.get("particles", -2)):
        raise CrosscheckError("typed summary timeline differs from CURRENT")
    timeline_times = timeline.get("time_s")
    if not isinstance(timeline_times, list) or len(timeline_times) != int(current_row.get("frames", -2)):
        raise CrosscheckError("typed summary timeline.time_s is missing or has the wrong frame count")
    previous_time: float | None = None
    for index, value in enumerate(timeline_times):
        checked_time = _finite(value, f"typed summary timeline.time_s[{index}]")
        if previous_time is not None and checked_time < previous_time:
            raise CrosscheckError("typed summary timeline.time_s is not monotone")
        previous_time = checked_time
    records = summary.get("records")
    if not isinstance(records, dict):
        raise CrosscheckError("typed summary records reference missing")
    record_path = _path(records.get("path"), "typed records", allow_deferred=True)
    record_ref = _deferred_ref(record_path, "typed records", records.get("sha256"), int(records.get("bytes", -1)), int(records.get("rows", -1)))
    if int(records.get("rows", -1)) != int(current_row.get("particles", -2)):
        raise CrosscheckError("typed records rows differ from CURRENT particles")
    return trajectory, record_ref


def _validate_proof(proof: dict[str, Any], proof_path: Path, summary_path: Path, summary_sha: str, records_ref: dict[str, Any], case_id: str, current_sha: str) -> dict[str, Any]:
    if proof.get("schema") != PROOF_SCHEMA or proof.get("status") != "VERIFIED_ACTUAL_F6_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT":
        raise CrosscheckError("ROOT203 proof schema/status differs")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or counts.get("completed") != 7 or counts.get("failed") != 0:
        raise CrosscheckError("ROOT203 proof batch counts are not the completed seven-case batch")
    cases = proof.get("case_verifications")
    if not isinstance(cases, list):
        raise CrosscheckError("ROOT203 proof case_verifications is missing")
    matches = [item for item in cases if isinstance(item, dict) and item.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise CrosscheckError("ROOT203 proof does not contain exactly one target case")
    case = matches[0]
    if case.get("family_id") != FAMILY_ID or case.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise CrosscheckError("ROOT203 target case status/family differs")
    if case.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise CrosscheckError("ROOT203 target H5 source closure is not proven")
    if case.get("native_cause_fate_legal_flux_dynamics") != "UNKNOWN":
        raise CrosscheckError("ROOT203 target must preserve physical cause/fate UNKNOWN")
    if not _same_path(case.get("summary"), summary_path) or _sha(case.get("summary_sha256"), "ROOT203 summary SHA") != summary_sha:
        raise CrosscheckError("ROOT203 proof does not bind the typed summary")
    stat_only = case.get("records_stat_only")
    if not isinstance(stat_only, dict) or not _same_path(stat_only.get("path"), Path(records_ref["path"])):
        raise CrosscheckError("ROOT203 proof does not bind deferred records")
    if stat_only.get("sha256") != records_ref["sha256"] or int(stat_only.get("bytes", -1)) != records_ref["bytes"] or int(stat_only.get("rows", -1)) != records_ref["rows"]:
        raise CrosscheckError("ROOT203 proof records stat differs")
    fresh = proof.get("fresh_small_inputs")
    if not isinstance(fresh, list) or not any(isinstance(item, dict) and item.get("sha256") == current_sha for item in fresh):
        raise CrosscheckError("ROOT203 proof does not include exact CURRENT SHA")
    return case


def _validate_scope(scope: dict[str, Any], scope_path: Path, case_id: str, native_path: Path, native_sha: str) -> dict[str, Any]:
    if scope.get("schema") != SCOPE_SCHEMA or scope.get("status") != "SOURCE_ONLY_SCOPE_REFINED_NO_LAUNCH":
        raise CrosscheckError("native scope V2 schema/status differs")
    rows = scope.get("case_rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise CrosscheckError("native scope V2 must contain 118 physical rows")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise CrosscheckError("native scope V2 target row is not unique")
    row = matches[0]
    if row.get("family_id") != FAMILY_ID:
        raise CrosscheckError("native scope V2 target family differs")
    if row.get("classification") not in {"NATIVE_CAUSE_BOUND_PER_FLUID_ID", "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN", "SCAN_COMPLETED_NO_NATIVE_TARGETS", "UNKNOWN_SOURCE_OR_IDENTITY"}:
        raise CrosscheckError("native scope V2 target classification is invalid")
    if row.get("physical_fate_legal_flux_dynamics") != "UNKNOWN" or any(row.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        raise CrosscheckError("native scope V2 target must preserve unknown qualification boundary")
    report_refs = [item for item in scope.get("input_bindings", []) if isinstance(item, dict) and item.get("role") == "historical_omission_audit"]
    return {"row": row, "input_bindings": report_refs, "scope_path": str(scope_path), "native_path": str(native_path), "native_sha256": native_sha}
def _validate_union(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise CrosscheckError("historical union is not an input to the F6 DXYZ contract")

def _deferred_csv_ref(path: Path, label: str, expected_sha: str, expected_bytes: int, expected_rows: int | None = None) -> dict[str, Any]:
    if path.suffix.lower() != ".csv":
        raise CrosscheckError(f"{label} must be CSV: {path}")
    stat = _stat(path, label)
    if stat["bytes"] != int(expected_bytes):
        raise CrosscheckError(f"{label} bytes differ: expected {expected_bytes}, got {stat['bytes']}")
    return {**stat, "sha256": _sha(expected_sha, f"{label} expected SHA"), "rows": expected_rows, "content_opened": False, "hash_checked": False, "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS"}


def _validate_scan(scan: dict[str, Any], current_row: dict[str, Any], native_ids: dict[str, Any]) -> None:
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED":
        raise CrosscheckError("scientific scan schema/status differs")
    if scan.get("physical_case_id") != CASE_ID or scan.get("family_id") != FAMILY_ID:
        raise CrosscheckError("scientific scan identity differs")
    trajectory = current_row.get("trajectory", {})
    if not _same_path(scan.get("trajectory"), Path(str(trajectory.get("path")))):
        raise CrosscheckError("scientific scan trajectory path differs")
    if int(scan.get("frames", -1)) != int(current_row.get("frames", -2)) or int(scan.get("particles", -1)) != int(current_row.get("particles", -2)):
        raise CrosscheckError("scientific scan shape differs from CURRENT")
    rows = scan.get("missing_id_records")
    if not isinstance(rows, list):
        raise CrosscheckError("scientific scan missing_id_records is missing")
    scan_keys = {(int(row.get("zone")), int(row.get("idp"))) for row in rows if isinstance(row, dict)}
    if scan_keys != set(native_ids["excluded"]):
        raise CrosscheckError("scientific scan IDs differ from historical native report")
    for row in rows:
        if not isinstance(row, dict) or row.get("native_exit_cause") != "EVIDENCE_UNKNOWN":
            raise CrosscheckError("scientific scan must preserve its unresolved native-cause label")


def _validate_conversion(conversion: dict[str, Any], current_row: dict[str, Any], generated_xml: Path, generated_xml_sha: str, data_root: Path) -> None:
    if conversion.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or conversion.get("conversion_status") != "completed":
        raise CrosscheckError("conversion report schema/status differs")
    trajectory = current_row.get("trajectory", {})
    if not _same_path(conversion.get("output_hdf5"), Path(str(trajectory.get("path")))) or conversion.get("output_sha256") != trajectory.get("producer_declared_sha256"):
        raise CrosscheckError("conversion output H5 does not bind CURRENT producer identity")
    provenance = conversion.get("source_provenance")
    if not isinstance(provenance, dict) or not _same_path(provenance.get("data_root"), data_root):
        raise CrosscheckError("conversion data_root does not bind native solver output")
    xml = provenance.get("generated_xml")
    if not isinstance(xml, dict) or not _same_path(xml.get("path"), generated_xml) or xml.get("sha256") != generated_xml_sha:
        raise CrosscheckError("conversion generated XML does not bind the exact source")
    if int(conversion.get("frames", -1)) != int(current_row.get("frames", -2)) or int(conversion.get("particles", -1)) != int(current_row.get("particles", -2)):
        raise CrosscheckError("conversion shape differs from CURRENT")
    blocks = conversion.get("typed_identity", {}).get("blocks") if isinstance(conversion.get("typed_identity"), dict) else None
    fluid = [item for item in blocks or [] if isinstance(item, dict) and item.get("type") == 3 and item.get("tag") == "fluid"]
    if len(fluid) != 1 or int(fluid[0].get("count", -1)) != 327680 or int(fluid[0].get("mkfluid", -1)) != 0:
        raise CrosscheckError("conversion fluid type/MK partition differs from ROOT203 source")


def _load_static_contract(contract_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _read_small_json(contract_path, "F6 DXYZ crosscheck contract")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED":
        raise CrosscheckError("F6 DXYZ contract is not guarded-ready")
    inputs = contract.get("inputs")
    if not isinstance(inputs, dict):
        raise CrosscheckError("F6 DXYZ input map is missing")
    def ref(role: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        item = inputs.get(role)
        if not isinstance(item, dict):
            raise CrosscheckError(f"F6 DXYZ input role missing: {role}")
        path = _path(item.get("path"), role)
        checked = _hash_small_json(path, role, item.get("sha256"))
        if checked["bytes"] != int(item.get("bytes", -1)):
            raise CrosscheckError(f"F6 DXYZ input stat differs: {role}")
        return path, checked, item
    current_path, current_ref, _ = ref("current336")
    proof_path, proof_ref, _ = ref("root203_proof")
    summary_path, summary_ref, _ = ref("root203_summary")
    native_path, native_ref, _ = ref("native_omission_report")
    scan_path, scan_ref, _ = ref("scientific_scan")
    scan_receipt_path, scan_receipt_ref, _ = ref("scientific_scan_receipt")
    conversion_path, conversion_ref, _ = ref("conversion_report")
    xml_path, xml_ref, _ = ref("generated_xml")
    gencase_path, gencase_ref, _ = ref("gencase_receipt")
    solver_path, solver_ref, _ = ref("solver_receipt")
    decoder_path, decoder_ref, _ = ref("native_decoder_receipt")
    scope_path, scope_ref, _ = ref("scope_v2")
    current = _read_small_json(current_path, "CURRENT336")
    if current_ref["sha256"] != contract.get("expected_current_sha256"):
        raise CrosscheckError("F6 DXYZ CURRENT SHA differs")
    row = _current_case(current, CASE_ID)
    summary = _read_small_json(summary_path, "ROOT203 typed summary")
    trajectory, records_ref = _validate_summary(summary, summary_path, row, CASE_ID, current_ref["sha256"])
    if int(summary.get("role_ledgers", {}).get("fluid", {}).get("initial_count", -1)) != 327680 or int(summary.get("role_ledgers", {}).get("fluid", {}).get("first_disappearance_count", -1)) != 3 or int(summary.get("role_ledgers", {}).get("fluid", {}).get("active_count_by_frame", [-1])[-1]) != 327677:
        raise CrosscheckError("ROOT203 summary fluid ledger differs")
    proof = _read_small_json(proof_path, "ROOT203 proof")
    proof_case = _validate_proof(proof, proof_path, summary_path, summary_ref["sha256"], records_ref, CASE_ID, current_ref["sha256"])
    native = _read_small_json(native_path, "historical native omission report")
    native_ids = _validate_native_report(native, row, CASE_ID)
    native_decode = native.get("native_decode") if isinstance(native.get("native_decode"), dict) else {}
    native_receipt_edge = native_decode.get("receipt") if isinstance(native_decode.get("receipt"), dict) else {}
    if not _same_path(native_receipt_edge.get("path"), decoder_path) or native_receipt_edge.get("sha256") != decoder_ref["sha256"]:
        raise CrosscheckError("native decoder receipt edge differs")
    scan = _read_small_json(scan_path, "scientific scan")
    _validate_scan(scan, row, native_ids)
    conversion = _read_small_json(conversion_path, "conversion report")
    data_root = Path(str(native.get("source_provenance", {}).get("data_root"))).expanduser().resolve()
    _validate_conversion(conversion, row, xml_path, xml_ref["sha256"], data_root)
    scope = _read_small_json(scope_path, "native scope V2")
    scope_info = _validate_scope(scope, scope_path, CASE_ID, native_path, native_ref["sha256"])
    source_provenance = native.get("source_provenance")
    if not isinstance(source_provenance, dict):
        raise CrosscheckError("native source_provenance is missing")
    if not _same_path(source_provenance.get("generated_xml", {}).get("path"), xml_path) or source_provenance.get("generated_xml", {}).get("sha256") != xml_ref["sha256"]:
        raise CrosscheckError("native generated XML edge differs")
    if not _same_path(source_provenance.get("solver_receipt", {}).get("path"), solver_path) or source_provenance.get("solver_receipt", {}).get("sha256") != solver_ref["sha256"]:
        raise CrosscheckError("native solver receipt edge differs")
    deferred = contract.get("deferred_inputs")
    if not isinstance(deferred, dict):
        raise CrosscheckError("F6 DXYZ deferred input map is missing")
    for role, expected in (("typed_records", records_ref), ("partout_csv", None), ("runparts_csv", None)):
        item = deferred.get(role)
        if not isinstance(item, dict):
            raise CrosscheckError(f"F6 DXYZ deferred role missing: {role}")
        if not _same_path(item.get("path"), Path(str(item.get("path")))):
            raise CrosscheckError(f"F6 DXYZ deferred path malformed: {role}")
        if role == "typed_records":
            _require_same_stat(expected, item, "typed records deferred")
        else:
            actual = _stat(Path(item["path"]), role, allow_deferred=(role == "typed_records"))
            _require_same_stat(actual, item, f"{role} deferred")
    native_decode_edge = contract.get("source_edges", {}).get("native_decode", {})
    for role, edge_key in (("partout_csv", "partout_csv"), ("runparts_csv", "runparts_csv")):
        edge = native_decode_edge.get(edge_key)
        item = deferred[role]
        if not isinstance(edge, dict) or not _same_path(edge.get("path"), Path(item["path"])) or edge.get("sha256") != item.get("sha256"):
            raise CrosscheckError(f"{role} deferred path is not bound to native decoder evidence")
    return contract, current, summary, native, native_ids

def _build_contract(args: argparse.Namespace) -> dict[str, Any]:
    def small(path: Path, label: str, expected: str) -> dict[str, Any]:
        return _hash_small_json(path, label, expected)
    current_ref = small(args.current, "CURRENT336", args.current_sha256)
    proof_ref = small(args.root203_proof, "ROOT203 proof", args.root203_proof_sha256)
    summary_ref = small(args.root203_summary, "ROOT203 summary", args.root203_summary_sha256)
    native_ref = small(args.native_report, "historical native omission report", args.native_report_sha256)
    scan_ref = small(args.scan, "scientific scan", args.scan_sha256)
    scan_receipt_ref = small(args.scan_receipt, "scientific scan receipt", args.scan_receipt_sha256)
    conversion_ref = small(args.conversion, "conversion report", args.conversion_sha256)
    xml_ref = small(args.generated_xml, "generated XML", args.generated_xml_sha256)
    gencase_ref = small(args.gencase_receipt, "GenCase receipt", args.gencase_receipt_sha256)
    solver_ref = small(args.solver_receipt, "solver receipt", args.solver_receipt_sha256)
    decoder_ref = small(args.native_decoder_receipt, "native decoder receipt", args.native_decoder_receipt_sha256)
    scope_ref = small(args.scope_v2, "native scope V2", args.scope_v2_sha256)
    current = _read_small_json(args.current, "CURRENT336")
    current_row = _current_case(current, CASE_ID)
    native = _read_small_json(args.native_report, "historical native omission report")
    native_ids = _validate_native_report(native, current_row, CASE_ID)
    summary = _read_small_json(args.root203_summary, "ROOT203 typed summary")
    trajectory, records_ref = _validate_summary(summary, args.root203_summary, current_row, CASE_ID, current_ref["sha256"])
    if int(summary.get("role_ledgers", {}).get("fluid", {}).get("initial_count", -1)) != 327680 or int(summary.get("role_ledgers", {}).get("fluid", {}).get("first_disappearance_count", -1)) != 3 or int(summary.get("role_ledgers", {}).get("fluid", {}).get("active_count_by_frame", [-1])[-1]) != 327677:
        raise CrosscheckError("ROOT203 summary fluid ledger differs")
    proof = _read_small_json(args.root203_proof, "ROOT203 proof")
    proof_case = _validate_proof(proof, args.root203_proof, args.root203_summary, summary_ref["sha256"], records_ref, CASE_ID, current_ref["sha256"])
    scan = _read_small_json(args.scan, "scientific scan")
    _validate_scan(scan, current_row, native_ids)
    conversion = _read_small_json(args.conversion, "conversion report")
    source_provenance = native.get("source_provenance")
    data_root = Path(str(source_provenance.get("data_root"))).expanduser().resolve() if isinstance(source_provenance, dict) else Path("")
    _validate_conversion(conversion, current_row, args.generated_xml, xml_ref["sha256"], data_root)
    scope = _read_small_json(args.scope_v2, "native scope V2")
    scope_info = _validate_scope(scope, args.scope_v2, CASE_ID, args.native_report, native_ref["sha256"])
    if not isinstance(source_provenance, dict):
        raise CrosscheckError("native source_provenance is missing")
    generated = source_provenance.get("generated_xml")
    if not isinstance(generated, dict) or not _same_path(generated.get("path"), args.generated_xml) or generated.get("sha256") != xml_ref["sha256"]:
        raise CrosscheckError("native generated XML edge differs")
    solver_edge = source_provenance.get("solver_receipt")
    if not isinstance(solver_edge, dict) or not _same_path(solver_edge.get("path"), args.solver_receipt) or solver_edge.get("sha256") != solver_ref["sha256"]:
        raise CrosscheckError("native solver receipt edge differs")
    records_path = Path(records_ref["path"])
    records_ref = {**records_ref, "rows": int(args.records_rows)}
    if int(records_ref["bytes"]) != int(args.records_bytes) or records_ref["sha256"] != args.records_sha256:
        raise CrosscheckError("ROOT203 records arguments differ from summary/proof")
    partout_ref = _deferred_csv_ref(args.partout, "native PartOut.csv", args.partout_sha256, int(args.partout_bytes), expected_rows=3)
    runparts_ref = _deferred_csv_ref(args.runparts, "native RunPARTs.csv", args.runparts_sha256, int(args.runparts_bytes), expected_rows=int(args.runparts_rows))
    h5_path = Path(str(current_row["trajectory"]["path"])).expanduser().resolve()
    h5_stat = _stat(h5_path, "source trajectory", allow_deferred=True)
    if h5_stat["bytes"] != int(current_row["trajectory"]["bytes"]):
        raise CrosscheckError("source trajectory stat differs from CURRENT")
    data_root_stat = {"path": str(data_root), "bytes": int(data_root.stat().st_size), "mtime_ns": int(data_root.stat().st_mtime_ns), "ctime_ns": int(data_root.stat().st_ctime_ns), "st_dev": int(data_root.stat().st_dev), "st_ino": int(data_root.stat().st_ino)}
    native_decode = native.get("native_decode") if isinstance(native.get("native_decode"), dict) else {}
    output_root = native_decode.get("output_root") if isinstance(native_decode.get("output_root"), dict) else {}
    native_receipt_edge = native_decode.get("receipt") if isinstance(native_decode.get("receipt"), dict) else {}
    if not _same_path(native_receipt_edge.get("path"), args.native_decoder_receipt) or native_receipt_edge.get("sha256") != decoder_ref["sha256"]:
        raise CrosscheckError("native decoder receipt edge differs")
    native_partout_edge = native_decode.get("partout") if isinstance(native_decode.get("partout"), dict) else {}
    native_runparts_edge = native_decode.get("runparts") if isinstance(native_decode.get("runparts"), dict) else {}
    if not _same_path(native_partout_edge.get("path"), args.partout) or native_partout_edge.get("sha256") != partout_ref["sha256"] or int(native_partout_edge.get("bytes", -1)) != partout_ref["bytes"]:
        raise CrosscheckError("native PartOut edge differs from decoder receipt")
    if not _same_path(native_runparts_edge.get("path"), args.runparts) or native_runparts_edge.get("sha256") != runparts_ref["sha256"] or int(native_runparts_edge.get("bytes", -1)) != runparts_ref["bytes"]:
        raise CrosscheckError("native RunPARTs edge differs from decoder receipt")
    scope_row = scope_info["row"]
    target_ids = [dict(row) for row in sorted(native.get("excluded_particles", []), key=lambda item: int(item["idp"]))]
    contract = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "physical_case_id": CASE_ID,
        "family_id": FAMILY_ID,
        "expected_current_sha256": current_ref["sha256"],
        "inputs": {
            "current336": current_ref,
            "root203_proof": proof_ref,
            "root203_summary": summary_ref,
            "native_omission_report": native_ref,
            "scientific_scan": scan_ref,
            "scientific_scan_receipt": scan_receipt_ref,
            "conversion_report": conversion_ref,
            "generated_xml": xml_ref,
            "gencase_receipt": gencase_ref,
            "solver_receipt": solver_ref,
            "native_decoder_receipt": decoder_ref,
            "scope_v2": scope_ref,
        },
        "deferred_inputs": {"typed_records": records_ref, "partout_csv": partout_ref, "runparts_csv": runparts_ref},
        "source_edges": {
            "current_row": {"frames": int(current_row["frames"]), "particles": int(current_row["particles"]), "trajectory_path": current_row["trajectory"]["path"], "trajectory_sha256": current_row["trajectory"]["producer_declared_sha256"], "trajectory_stat": h5_stat},
            "root203_case": {"proof_case_status": proof_case["status"], "summary_path": str(args.root203_summary), "summary_sha256": summary_ref["sha256"], "records_stat_only": records_ref},
            "historical_scope_v2": {"classification": scope_row.get("classification"), "credit_reason": scope_row.get("credit_reason"), "typed_native_first_missing_join_scope": scope_row.get("typed_native_first_missing_join_scope")},
            "native_report": {"path": str(args.native_report), "sha256": native_ref["sha256"], "identity_key": "(Zone,Idp)", "excluded_ids": [[int(item["zone"]), int(item["idp"])] for item in target_ids], "native_exit_cause_counts": scope_row.get("report_native_exit_cause_counts"), "physical_fate": native.get("physical_fate"), "legal_outflow_proven": False},
            "scan": {"path": str(args.scan), "sha256": scan_ref["sha256"], "missing_id_count": len(native_ids["excluded"]), "native_cause_label": "EVIDENCE_UNKNOWN"},
            "conversion": {"path": str(args.conversion), "sha256": conversion_ref["sha256"], "output_hdf5": conversion.get("output_hdf5"), "output_sha256": conversion.get("output_sha256"), "data_root": str(data_root), "data_root_stat": data_root_stat, "generated_xml": generated, "fluid_partition": {"count": 327680, "type": 3, "mkfluid": 0}},
            "native_decode": {"receipt": decoder_ref, "output_root": output_root, "tool": native_decode.get("tool"), "partout_csv": partout_ref, "runparts_csv": runparts_ref, "content_opened_during_prepare": False},
        },
        "comparison": {"identity_key": "(Zone,Idp)", "typed_key_source": "ROOT203 V4 JSONL after parent reservation", "native_key_source": "historical PartOut-bound omission report and PartOut.csv after parent reservation", "native_zone_scope": "Zone=0 is report-bound; PartOut.csv has no Zone column", "typed_first_missing_semantics": "first saved frame valid-mask active-to-inactive", "native_first_missing_semantics": "saved PartVTKOut/RunPARTs bracket", "saved_frame_or_bracket_match": "bounded evidence only", "continuous_event_time": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        "target_ids": target_ids,
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 1024 * 1024 * 1024, "output_cap_bytes": MAX_OUTPUT_BYTES, "typed_records_passes_minimum": 1, "typed_records_bytes": int(records_ref["bytes"]), "partout_bytes": int(partout_ref["bytes"]), "runparts_bytes": int(runparts_ref["bytes"]), "estimated_input_read_bytes": int(records_ref["bytes"] + partout_ref["bytes"] + runparts_ref["bytes"]), "h5_content_read": False, "native_bi4_read": False, "solver_launch": False},
        "claim_boundary": {"historical_native_cause": "SOURCE_BOUND_HISTORICAL_REPORT_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "native_category_counts": "not an ID-level substitute", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": False,
        "launch_owner": "root",
        "request_note": "Parent must create a new guarded request. Prepare opens only bounded metadata/stat; typed JSONL, PartOut.csv, and RunPARTs.csv are deferred until reservation.",
    }
    return contract


def _default_stage2_root() -> Path:
    return SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"


def _request_from_contract(contract_path: Path, output_path: Path, worker: Path | None, python: Path | None) -> dict[str, Any]:
    contract = _read_small_json(contract_path, "F6 DXYZ crosscheck contract")
    if worker is None:
        worker = SCRIPT
    worker = _path(worker, "worker")
    python_declared = VENV if python is None else Path(python).expanduser()
    python_resolved = python_declared.resolve()
    if not python_resolved.is_file():
        raise CrosscheckError(f"python interpreter is missing: {python_declared}")
    stage2 = _default_stage2_root()
    primary_scripts = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts")
    runtime_paths = [primary_scripts / name for name in ("ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py")]
    config = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
    # The production root may rebind these source paths into its checkout, but the
    # declared literal roles and digests stay explicit in this source request.
    input_paths = [Path(contract_path).resolve(), worker, python_resolved, config]
    for item in contract.get("inputs", {}).values():
        if isinstance(item, dict):
            input_paths.append(Path(item["path"]).expanduser().resolve())
    input_paths.extend(path.resolve() for path in runtime_paths if path.is_file())
    input_paths = sorted({path for path in input_paths if path.is_file()})
    input_hashes = {str(path): _sha256_file(path, max_bytes=MAX_SMALL_BYTES) for path in input_paths}
    deferred_paths = [str(Path(contract["deferred_inputs"][role]["path"]).expanduser().resolve()) for role in ("typed_records", "partout_csv", "runparts_csv")]
    return {"schema": REQUEST_SCHEMA, "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED", "task_kind": "audit", "physical_case_id": CASE_ID, "family_id": FAMILY_ID, "command": [str(python_declared), str(worker), "audit", "--contract", "{attempt_root}/f6-dxyz-crosscheck-contract-v1.json", "--output", "{attempt_root}/f6-dxyz-crosscheck-v1.json"], "input_files": [str(path) for path in input_paths], "input_sha256": input_hashes, "deferred_input_files": deferred_paths, "deferred_input_sha256": {str(Path(contract["deferred_inputs"][role]["path"]).expanduser().resolve()): contract["deferred_inputs"][role]["sha256"] for role in ("typed_records", "partout_csv", "runparts_csv")}, "contract": {"path": str(Path(contract_path).resolve()), "sha256": _sha256_file(contract_path, max_bytes=MAX_OUTPUT_BYTES)}, "interpreter_binding": {"literal_path": str(python_declared), "resolved_path": str(python_resolved), "sha256": _sha256_file(python_resolved, max_bytes=MAX_SMALL_BYTES)}, "resource_policy": contract["resource_policy"], "claim_boundary": contract["claim_boundary"], "launch_allowed": False, "launch_owner": "root"}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    contract = _build_contract(args)
    output = Path(args.output).expanduser().resolve()
    _atomic_json(output, contract, max_bytes=MAX_OUTPUT_BYTES)
    result: dict[str, Any] = {"status": contract["status"], "contract": str(output), "contract_sha256": _sha256_file(output, max_bytes=MAX_OUTPUT_BYTES)}
    if args.request_output:
        request_output = Path(args.request_output).expanduser().resolve()
        request = _request_from_contract(output, request_output, Path(args.worker).expanduser() if args.worker else None, Path(args.python).expanduser() if args.python else None)
        _atomic_json(request_output, request, max_bytes=MAX_OUTPUT_BYTES)
        result.update({"request": str(request_output), "request_sha256": _sha256_file(request_output, max_bytes=MAX_OUTPUT_BYTES)})
    return result


def _record_from_line(raw: bytes, line_no: int) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CrosscheckError(f"typed records line {line_no} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CrosscheckError(f"typed records line {line_no} is not an object")
    return value


def _native_rows(native: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    rows = native.get("excluded_particles")
    if not isinstance(rows, list):
        raise CrosscheckError("native excluded rows are missing")
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CrosscheckError(f"native excluded row {index} is malformed")
        key = (_integer(row.get("zone"), f"native row {index} zone"), _integer(row.get("idp"), f"native row {index} Idp"))
        if key in result:
            raise CrosscheckError(f"duplicate native excluded identity: {key}")
        result[key] = row
    return result


def _read_partout(path: Path, expected: dict[str, Any], native_rows: dict[tuple[int, int], dict[str, Any]]) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    before = _stat(path, "native PartOut.csv")
    _require_same_stat(before, expected, "native PartOut.csv before pass")
    digest = hashlib.sha256()
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    with path.open("rb") as stream:
        raw = stream.read()
        digest.update(raw)
    try:
        text = raw.decode("utf-8")
        import csv
        parsed = csv.DictReader(text.splitlines())
        required = {"PartOut", "Motive", "Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]"}
        if not parsed.fieldnames or not required.issubset(set(parsed.fieldnames)):
            raise CrosscheckError("PartOut.csv header does not match official PartVTKOut fields")
        for line_no, item in enumerate(parsed, 2):
            if not isinstance(item, dict):
                raise CrosscheckError(f"PartOut.csv row {line_no} is malformed")
            try:
                part = int(item["PartOut"])
                motive = int(item["Motive"])
                idp = int(item["Idp"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CrosscheckError(f"PartOut.csv row {line_no} identity fields are invalid") from exc
            if part < 0 or motive < 0 or idp < 0:
                raise CrosscheckError(f"PartOut.csv row {line_no} has negative identity")
            key = (0, idp)
            if key in rows:
                raise CrosscheckError(f"duplicate PartOut.csv identity: {key}")
            if key not in native_rows:
                raise CrosscheckError(f"PartOut.csv contains a non-target Idp: {idp}")
            values = {name: _finite(float(item[name]), f"PartOut.csv row {line_no} {name}") for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]")}
            expected_motive = native_rows[key].get("native_motive_code")
            if expected_motive is not None and motive != int(expected_motive):
                raise CrosscheckError(f"PartOut.csv motive differs for {key}")
            rows[key] = {"zone": 0, "idp": idp, "part_out": part, "motive_code": motive, **values}
    except UnicodeError as exc:
        raise CrosscheckError("PartOut.csv is not UTF-8") from exc
    after = _stat(path, "native PartOut.csv after pass")
    _require_same_stat(after, expected, "native PartOut.csv after pass")
    if before != after or digest.hexdigest() != expected["sha256"]:
        raise CrosscheckError("PartOut.csv changed or SHA differs during pass")
    if set(rows) != set(native_rows):
        raise CrosscheckError("PartOut.csv target identity set differs from historical report")
    return rows, {"pre_stat": before, "post_stat": after, "sha256": digest.hexdigest(), "rows": len(rows), "single_pass": True, "zone_scope": "Zone=0 inferred from source-bound report; CSV has no Zone column"}


def _read_runparts(path: Path, expected: dict[str, Any], summary: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    before = _stat(path, "native RunPARTs.csv")
    _require_same_stat(before, expected, "native RunPARTs.csv before pass")
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        raw = stream.read()
        digest.update(raw)
    try:
        text = raw.decode("utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("part;"):
                continue
            pieces = [part.strip() for part in stripped.split(";")]
            if len(pieces) < 6:
                raise CrosscheckError(f"RunPARTs.csv row {line_no} has too few fields")
            try:
                part, time_s, npout, nppos, nprho, npm = int(pieces[0]), float(pieces[1]), int(pieces[2]), int(pieces[3]), int(pieces[4]), int(pieces[5])
            except ValueError as exc:
                raise CrosscheckError(f"RunPARTs.csv row {line_no} has invalid numeric fields") from exc
            if part != len(rows):
                raise CrosscheckError(f"RunPARTs.csv Part sequence is not contiguous at row {line_no}")
            if not math.isfinite(time_s) or min(npout, nppos, nprho, npm) < 0:
                raise CrosscheckError(f"RunPARTs.csv row {line_no} has invalid finite/count values")
            rows.append({"part": part, "time_s": time_s, "NpOut": npout, "NpOutPos": nppos, "NpOutRho": nprho, "NpOutMov": npm})
    except UnicodeError as exc:
        raise CrosscheckError("RunPARTs.csv is not UTF-8") from exc
    after = _stat(path, "native RunPARTs.csv after pass")
    _require_same_stat(after, expected, "native RunPARTs.csv after pass")
    if before != after or digest.hexdigest() != expected["sha256"]:
        raise CrosscheckError("RunPARTs.csv changed or SHA differs during pass")
    timeline = summary.get("timeline", {}).get("time_s")
    if not isinstance(timeline, list) or len(rows) != len(timeline):
        raise CrosscheckError("RunPARTs.csv row count differs from typed timeline")
    max_delta = 0.0
    for row, value in zip(rows, timeline):
        max_delta = max(max_delta, abs(row["time_s"] - _finite(value, "summary timeline time")))
    if max_delta > 1e-9:
        raise CrosscheckError(f"RunPARTs saved time differs from typed timeline: {max_delta}")
    totals = {name: sum(row[name] for row in rows) for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    expected_totals = native.get("native_decode", {}).get("runparts_totals") if isinstance(native.get("native_decode"), dict) else None
    if isinstance(expected_totals, dict) and {name: int(expected_totals.get(name, -1)) for name in totals} != totals:
        raise CrosscheckError("RunPARTs cumulative totals differ from the source-bound native report")
    return {"pre_stat": before, "post_stat": after, "sha256": digest.hexdigest(), "rows": len(rows), "single_pass": True, "max_saved_time_delta_s": max_delta, "totals": totals}


def audit(contract_path: Path, output_path: Path) -> dict[str, Any]:
    """Perform the post-reservation typed JSONL and native CSV comparison."""
    contract, current, summary, native, native_ids = _load_static_contract(Path(contract_path).expanduser().resolve())
    records_ref = contract["deferred_inputs"]["typed_records"]
    records_path = _path(records_ref["path"], "typed records", allow_deferred=True)
    before = _stat(records_path, "typed records", allow_deferred=True)
    _require_same_stat(before, records_ref, "typed records before pass")
    expected_rows = int(records_ref["rows"])
    expected_sha = _sha(records_ref["sha256"], "typed records expected SHA")
    timeline = summary.get("timeline")
    timeline_times = timeline.get("time_s") if isinstance(timeline, dict) else None
    if not isinstance(timeline_times, list):
        raise CrosscheckError("typed summary timeline.time_s is unavailable for exact frame/time join")
    native_rows = _native_rows(native)
    comparisons: dict[tuple[int, int], dict[str, Any]] = {}
    seen_records: set[tuple[int, int]] = set()
    record_count = 0
    non_target_record_count = 0
    digest = hashlib.sha256()
    header: dict[str, Any] | None = None
    declared_population: int | None = None
    with records_path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                raise CrosscheckError(f"typed records line {line_no} is blank")
            row = _record_from_line(raw, line_no)
            if line_no == 1:
                header = row
                if header.get("schema") != RECORD_SCHEMA or header.get("physical_case_id") != contract["physical_case_id"]:
                    raise CrosscheckError("typed records header schema/case differs")
                if header.get("family_id") is not None and header.get("family_id") != contract["family_id"]:
                    raise CrosscheckError("typed records header family differs")
                if header.get("source_trajectory_sha256") != summary["source"]["trajectory_h5"]["known_sha256"]:
                    raise CrosscheckError("typed records header trajectory SHA differs")
                header_fields = header.get("record_fields")
                if header_fields != EXPECTED_RECORD_FIELDS:
                    raise CrosscheckError("typed records header record_fields differs from the V4 producer contract")
                raw_population = header.get("record_population")
                if raw_population is not None:
                    declared_population = _integer(raw_population, "typed records header record_population")
                    if declared_population < 0:
                        raise CrosscheckError("typed records header record_population is negative")
                continue
            record_count += 1
            zone = _integer(row.get("zone"), f"typed record line {line_no} zone")
            idp = _integer(row.get("idp"), f"typed record line {line_no} Idp")
            key = (zone, idp)
            if key in seen_records:
                raise CrosscheckError(f"duplicate typed record identity: {key}")
            seen_records.add(key)
            # The typed JSONL contains every static identity.  Native
            # omission evidence covers only the three source-bound F6 target IDs,
            # so non-target rows are validated for whole-record
            # identity uniqueness and counted but are not joined/output.
            if key not in native_rows:
                non_target_record_count += 1
                continue
            frame = row.get("first_disappeared_frame")
            time_value = row.get("first_disappeared_time_s")
            bracket = row.get("first_disappeared_bracket_s")
            if frame is not None:
                frame = _integer(frame, f"typed {key} first_disappeared_frame")
                if frame < 0:
                    raise CrosscheckError(f"typed {key} first_disappeared_frame is negative")
                if frame >= len(timeline_times):
                    raise CrosscheckError(f"typed {key} disappeared frame exceeds summary timeline")
                if time_value is None:
                    raise CrosscheckError(f"typed {key} disappeared frame lacks saved time")
                time_value = _finite(time_value, f"typed {key} first_disappeared_time_s")
            elif time_value is not None:
                raise CrosscheckError(f"typed {key} has time without disappeared frame")
            if bracket is not None:
                if not isinstance(bracket, list) or len(bracket) != 2:
                    raise CrosscheckError(f"typed {key} saved bracket is malformed")
                bracket = [_finite(bracket[0], f"typed {key} bracket lower"), _finite(bracket[1], f"typed {key} bracket upper")]
                if bracket[0] > bracket[1]:
                    raise CrosscheckError(f"typed {key} saved bracket is reversed")
                if time_value is not None and not bracket[0] <= time_value <= bracket[1]:
                    raise CrosscheckError(f"typed {key} disappeared time is outside its saved bracket")
            timeline_time = _finite(timeline_times[frame], f"typed {key} summary timeline frame time") if frame is not None else None
            if frame is not None and time_value != timeline_time:
                raise CrosscheckError(f"typed {key} disappeared time does not exactly match summary timeline frame")
            native_row = native_rows[key]
            native_frame = _integer(native_row.get("first_missing_frame"), f"native {key} first_missing_frame") if native_row.get("first_missing_frame") is not None else None
            native_bracket = native_row.get("first_missing_bracket_s")
            if native_bracket is not None:
                native_bracket = [_finite(native_bracket[0], f"native {key} bracket lower"), _finite(native_bracket[1], f"native {key} bracket upper")]
                if native_bracket[0] > native_bracket[1]:
                    raise CrosscheckError(f"native {key} saved bracket is reversed")
            in_bracket = None
            if time_value is not None and native_bracket is not None:
                in_bracket = native_bracket[0] <= time_value <= native_bracket[1]
            comparisons[key] = {
                "zone": zone,
                "idp": idp,
                "native_first_missing_frame": native_frame,
                "native_first_missing_bracket_s": native_bracket,
                "native_first_missing_time_scope": "SAVED_BRACKET_ONLY" if native_bracket is not None else "UNKNOWN",
                "typed_first_disappeared_frame": frame,
                "typed_first_disappeared_time_s": time_value,
                "typed_summary_timeline_frame_time_s": timeline_time,
                "typed_time_matches_summary_timeline": None if frame is None else time_value == timeline_time,
                "typed_first_disappeared_bracket_s": bracket,
                "saved_frame_match": None if native_frame is None or frame is None else native_frame == frame,
                "typed_time_in_native_bracket": in_bracket,
                "continuous_event_time": "UNKNOWN",
                "physical_fate": "UNKNOWN",
                "legal_flux": "UNKNOWN",
                "dynamical_impact": "UNKNOWN",
            }
    if header is None:
        raise CrosscheckError("typed records are empty")
    after = _stat(records_path, "typed records after pass", allow_deferred=True)
    _require_same_stat(after, records_ref, "typed records after pass")
    actual_sha = digest.hexdigest()
    if before != after:
        raise CrosscheckError("typed records changed during single pass")
    if actual_sha != expected_sha:
        raise CrosscheckError(f"typed records SHA differs: expected {expected_sha}, got {actual_sha}")
    if record_count != expected_rows:
        raise CrosscheckError(f"typed records row count differs: expected {expected_rows}, got {record_count}")
    if declared_population is not None and declared_population != record_count:
        raise CrosscheckError(f"typed records header record_population differs: expected {record_count}, got {declared_population}")
    if not set(native_rows).issubset(seen_records):
        missing = sorted(set(native_rows) - seen_records)
        raise CrosscheckError(f"typed records omit native IDs: {missing[:4]}")
    deferred = contract["deferred_inputs"]
    partout_rows, partout_evidence = _read_partout(_path(deferred["partout_csv"]["path"], "native PartOut.csv"), deferred["partout_csv"], native_rows)
    runparts_evidence = _read_runparts(_path(deferred["runparts_csv"]["path"], "native RunPARTs.csv"), deferred["runparts_csv"], summary, native)
    for key, row in comparisons.items():
        row["partout_row"] = partout_rows[key]
    ordered = [comparisons[key] for key in sorted(comparisons)]
    output = {
        "schema": SCHEMA,
        "status": "COMPLETED_TYPED_NATIVE_SAVED_FRAME_CROSSCHECK_NO_PHYSICAL_CREDIT",
        "physical_case_id": contract["physical_case_id"],
        "family_id": contract["family_id"],
        "source_contract": str(Path(contract_path).resolve()),
        "source_contract_sha256": _sha256_file(Path(contract_path), max_bytes=MAX_SMALL_BYTES),
        "record_header": {"schema": header.get("schema"), "status": header.get("status"), "family_id": header.get("family_id"), "physical_case_id": header.get("physical_case_id"), "source_trajectory_sha256": header.get("source_trajectory_sha256"), "record_fields": header.get("record_fields"), "record_population": declared_population},
        "records": {"path": str(records_path), "bytes": after["bytes"], "rows": record_count, "sha256": actual_sha, "pre_stat": before, "post_stat": after, "single_pass": True},
        "native_evidence": {"id_count": len(native_rows), "first_missing_frame_count": sum(value.get("native_first_missing_frame") is not None for value in ordered), "first_missing_bracket_count": sum(value.get("native_first_missing_bracket_s") is not None for value in ordered), "partout": partout_evidence, "runparts": runparts_evidence, "historical_cause_scope": "prior source-bound report only"},
        "typed_evidence": {"record_count": record_count, "non_target_record_count": non_target_record_count, "native_key_join_count": len(ordered), "first_disappearance_count": sum(value.get("typed_first_disappeared_frame") is not None for value in ordered)},
        "comparison_counts": {"saved_frame_matches": sum(value["saved_frame_match"] is True for value in ordered), "saved_frame_mismatches": sum(value["saved_frame_match"] is False for value in ordered), "saved_frame_unknown": sum(value["saved_frame_match"] is None for value in ordered), "typed_times_matching_summary_timeline": sum(value["typed_time_matches_summary_timeline"] is True for value in ordered), "typed_times_in_native_brackets": sum(value["typed_time_in_native_bracket"] is True for value in ordered), "typed_times_outside_or_unknown_brackets": sum(value["typed_time_in_native_bracket"] is not True for value in ordered)},
        "rows": ordered,
        "claim_boundary": {"native_cause": "source-bound prior report only", "continuous_event_time": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_read_cost": {"records_minimum_passes": 1, "records_bytes": after["bytes"], "partout_passes": 1, "partout_bytes": partout_evidence["post_stat"]["bytes"], "runparts_passes": 1, "runparts_bytes": runparts_evidence["post_stat"]["bytes"], "output_cap_bytes": MAX_OUTPUT_BYTES},
    }
    _atomic_json(Path(output_path), output)
    return {"status": output["status"], "output": str(Path(output_path).resolve()), "record_count": record_count, "saved_frame_matches": output["comparison_counts"]["saved_frame_matches"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare", help="build metadata-only F6 DXYZ source contract")
    for name, sha_name in (("current", "current_sha256"), ("root203-proof", "root203_proof_sha256"), ("root203-summary", "root203_summary_sha256"), ("native-report", "native_report_sha256"), ("scan", "scan_sha256"), ("scan-receipt", "scan_receipt_sha256"), ("conversion", "conversion_sha256"), ("generated-xml", "generated_xml_sha256"), ("gencase-receipt", "gencase_receipt_sha256"), ("solver-receipt", "solver_receipt_sha256"), ("native-decoder-receipt", "native_decoder_receipt_sha256"), ("scope-v2", "scope_v2_sha256")):
        prep.add_argument(f"--{name}", type=Path, required=True)
        prep.add_argument(f"--{name}-sha256", dest=sha_name, required=True)
    prep.add_argument("--records", type=Path, required=True)
    prep.add_argument("--records-sha256", required=True)
    prep.add_argument("--records-bytes", type=int, required=True)
    prep.add_argument("--records-rows", type=int, required=True)
    prep.add_argument("--partout", type=Path, required=True)
    prep.add_argument("--partout-sha256", required=True)
    prep.add_argument("--partout-bytes", type=int, required=True)
    prep.add_argument("--runparts", type=Path, required=True)
    prep.add_argument("--runparts-sha256", required=True)
    prep.add_argument("--runparts-bytes", type=int, required=True)
    prep.add_argument("--runparts-rows", type=int, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--worker", type=Path)
    prep.add_argument("--python", type=Path)
    audit_parser = subparsers.add_parser("audit", help="read deferred typed/native CSV after parent reservation")
    audit_parser.add_argument("--contract", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    return parser

def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args)
        else:
            result = audit(args.contract, args.output)
    except (CrosscheckError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", flush=True)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
