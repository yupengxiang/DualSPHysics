#!/usr/bin/env python3
"""Cross-check one guarded typed-lifecycle JSONL against native omissions.

This is a forward-only consumer for the ROOT192 F2H10V2 pilot.  ``prepare``
reads and hashes only bounded JSON metadata and stats the large typed-record
JSONL; it never opens or hashes the JSONL, HDF5, native PartOut, or solver
payload.  ``audit`` is the post-reservation worker: it reads the records
JSONL exactly once, hashes the bytes during that same pass, and joins only the
native ``(Zone, Idp)`` keys in the small, source-bound omission report.

The typed value is the first *saved-frame* valid-mask disappearance.  The
native value is the first saved bracket reported by the prior PartVTKOut
consumer.  A frame match or mismatch does not identify a continuous event,
physical fate, legal flux, or dynamics.  Those fields remain ``UNKNOWN``.
The ROOT192 pilot is one physical CURRENT case and never expands the
historical 118-case registry.
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

SCHEMA = "ds02.stage2.typed-native-first-missing-crosscheck.v2"
CONTRACT_SCHEMA = "ds02.stage2.typed-native-first-missing-contract.v2"
REQUEST_SCHEMA = "ds02.request.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
UNION_SCHEMA = "ds02.stage2.historical118-native-coverage-union.v3"
OMISSION_SCHEMA = "ds02.stage2.omission-forensics.v2"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v4"
RECORD_SCHEMA = "ds02.stage2.typed-lifecycle-records.v4"

CASE_ID = "F2H10V2_OFFSET_V1"
FAMILY_ID = "F2"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
UNION_SHA256 = "fee25570cca35e9a6ffdf025f8c68e0f4f0fa3e8fb99f4993b612f80fb9db241"
ROOT192_PROOF_SHA256 = "bdf1570bf1d1fd8fe81b9e8e9ae5f116285eb226d193555ecc359d5fdaa57887"
ROOT192_SUMMARY_SHA256 = "0b15882ea3b80bdb8fa38241509a066c4416ea222fc8296358891fd0b2431fe1"
NATIVE_REPORT_SHA256 = "1bed06460b6a17af258d3ad02cd2c55588b0f097374f3944e4fdaad7b9a6f3b3"
RECORDS_SHA256 = "2c632af79303299a8b0d90e24dc26930d57ee45c3912869cf11c4078f9fc6d9f"

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
    records = summary.get("records")
    if not isinstance(records, dict):
        raise CrosscheckError("typed summary records reference missing")
    record_path = _path(records.get("path"), "typed records", allow_deferred=True)
    record_ref = _deferred_ref(record_path, "typed records", records.get("sha256"), int(records.get("bytes", -1)), int(records.get("rows", -1)))
    if int(records.get("rows", -1)) != int(current_row.get("particles", -2)):
        raise CrosscheckError("typed records rows differ from CURRENT particles")
    return trajectory, record_ref


def _validate_proof(proof: dict[str, Any], proof_path: Path, summary_path: Path, summary_sha: str, records_ref: dict[str, Any], case_id: str, current_sha: str) -> None:
    if proof.get("schema") != PROOF_SCHEMA or proof.get("status") != "VERIFIED_ACTUAL_TYPED_LIFECYCLE_V4_SINGLE_CASE_118_SAVED_MASK_DISAPPEARANCES_NO_PHYSICAL_CREDIT":
        raise CrosscheckError("ROOT192 proof schema/status differs")
    if proof.get("physical_case_id") != case_id or proof.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise CrosscheckError("ROOT192 proof identity/source closure differs")
    if proof.get("H5_or_large_records_content_read_by_root") is not False:
        raise CrosscheckError("ROOT192 proof must preserve large records stat-only scope")
    if not _same_path(proof.get("report"), summary_path) or _sha(proof.get("report_sha256"), "ROOT192 proof summary SHA") != summary_sha:
        raise CrosscheckError("ROOT192 proof does not bind typed summary")
    fresh = proof.get("fresh_small_inputs")
    if not isinstance(fresh, list):
        raise CrosscheckError("ROOT192 proof fresh inputs are missing")
    current_refs = [item for item in fresh if isinstance(item, dict) and _same_path(item.get("path"), Path(proof.get("request", "")))]
    # The proof's CURRENT path is found by digest, not by assuming a worktree.
    if not any(isinstance(item, dict) and item.get("sha256") == current_sha for item in fresh):
        raise CrosscheckError("ROOT192 proof does not include exact CURRENT SHA")
    stat_only = proof.get("records_stat_only")
    if isinstance(stat_only, dict):
        stat_rows = [stat_only]
    elif isinstance(stat_only, list):
        stat_rows = stat_only
    else:
        raise CrosscheckError("ROOT192 proof records_stat_only is missing")
    rows = [item for item in stat_rows if isinstance(item, dict) and _same_path(item.get("path"), Path(records_ref["path"]))]
    if len(rows) != 1:
        raise CrosscheckError("ROOT192 proof does not bind typed records path")
    item = rows[0]
    if item.get("sha256") != records_ref["sha256"] or int(item.get("bytes", -1)) != records_ref["bytes"] or int(item.get("rows", -1)) != records_ref["rows"]:
        raise CrosscheckError("ROOT192 proof records stat differs from summary")


def _validate_union(union: dict[str, Any], native_path: Path, native_sha: str, case_id: str) -> dict[str, Any]:
    if union.get("schema") != UNION_SCHEMA or union.get("status") != "PASS_EXACT_118_OF118_SOURCE_CASE_UNION":
        raise CrosscheckError("historical union schema/status differs")
    evidence = union.get("native_evidence")
    if not isinstance(evidence, list) or len(evidence) != 118:
        raise CrosscheckError("historical union must contain exactly 118 native evidence rows")
    seen: set[str] = set()
    family_counts = {"F2": 0, "F4": 0, "F6": 0}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str):
            raise CrosscheckError("historical union evidence row is malformed")
        item_id = item["physical_case_id"]
        if item_id in seen:
            raise CrosscheckError(f"historical union duplicate case: {item_id}")
        seen.add(item_id)
        family = item.get("family_id")
        if family not in family_counts:
            raise CrosscheckError(f"historical union family is outside F2/F4/F6: {family}")
        family_counts[family] += 1
    if family_counts != {"F2": 48, "F4": 22, "F6": 48}:
        raise CrosscheckError(f"historical union family counts differ: {family_counts}")
    rows = [item for item in union.get("native_evidence", []) if isinstance(item, dict) and item.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise CrosscheckError("historical union does not contain exactly one pilot row")
    report = rows[0].get("report")
    if not isinstance(report, dict) or not _same_path(report.get("path"), native_path) or _sha(report.get("sha256"), "union native report SHA") != native_sha:
        raise CrosscheckError("historical union/native report edge differs")
    return rows[0]


def _load_static_contract(contract_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _read_small_json(contract_path, "ROOT199 V2 contract")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED":
        raise CrosscheckError("ROOT199 V2 contract is not guarded-ready")
    inputs = contract.get("inputs")
    if not isinstance(inputs, dict):
        raise CrosscheckError("ROOT199 V2 contract input map is missing")
    def ref(role: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        item = inputs.get(role)
        if not isinstance(item, dict):
            raise CrosscheckError(f"ROOT199 input role missing: {role}")
        path = _path(item.get("path"), role)
        checked = _hash_small_json(path, role, item.get("sha256"))
        if checked["bytes"] != int(item.get("bytes", -1)):
            raise CrosscheckError(f"ROOT199 input stat differs: {role}")
        return path, checked, item
    current_path, current_ref, _ = ref("current336")
    union_path, union_ref, _ = ref("historical_union")
    proof_path, proof_ref, _ = ref("root192_proof")
    summary_path, summary_ref, _ = ref("root192_summary")
    native_path, native_ref, _ = ref("native_omission_report")
    current = _read_small_json(current_path, "CURRENT336")
    current_sha = current_ref["sha256"]
    if current_sha != contract.get("expected_current_sha256"):
        raise CrosscheckError("ROOT199 V2 contract CURRENT SHA differs")
    row = _current_case(current, str(contract.get("physical_case_id")))
    summary = _read_small_json(summary_path, "typed summary")
    trajectory, record_ref = _validate_summary(summary, summary_path, row, str(contract.get("physical_case_id")), current_sha)
    proof = _read_small_json(proof_path, "ROOT192 proof")
    _validate_proof(proof, proof_path, summary_path, summary_ref["sha256"], record_ref, str(contract.get("physical_case_id")), current_sha)
    native = _read_small_json(native_path, "native omission report")
    native_ids = _validate_native_report(native, row, str(contract.get("physical_case_id")))
    union = _read_small_json(union_path, "historical union")
    _validate_union(union, native_path, native_ref["sha256"], str(contract.get("physical_case_id")))
    if record_ref["path"] != str(Path(contract["deferred_records"]["path"]).expanduser().resolve()):
        raise CrosscheckError("ROOT199 deferred records path differs")
    if record_ref["sha256"] != _sha(contract["deferred_records"]["sha256"], "contract deferred records SHA"):
        raise CrosscheckError("ROOT199 deferred records SHA differs")
    return contract, current, summary, native, native_ids


def _build_contract(
    *, current_path: Path, current_sha: str, union_path: Path, union_sha: str,
    proof_path: Path, proof_sha: str, summary_path: Path, summary_sha: str,
    native_path: Path, native_sha: str,
) -> dict[str, Any]:
    current_ref = _hash_small_json(current_path, "CURRENT336", current_sha)
    union_ref = _hash_small_json(union_path, "historical union", union_sha)
    proof_ref = _hash_small_json(proof_path, "ROOT192 proof", proof_sha)
    summary_ref = _hash_small_json(summary_path, "ROOT192 summary", summary_sha)
    native_ref = _hash_small_json(native_path, "native omission report", native_sha)
    current = _read_small_json(current_path, "CURRENT336")
    current_row = _current_case(current, CASE_ID)
    native = _read_small_json(native_path, "native omission report")
    native_ids = _validate_native_report(native, current_row, CASE_ID)
    summary = _read_small_json(summary_path, "typed summary")
    trajectory, records_ref = _validate_summary(summary, summary_path, current_row, CASE_ID, current_ref["sha256"])
    proof = _read_small_json(proof_path, "ROOT192 proof")
    _validate_proof(proof, proof_path, summary_path, summary_ref["sha256"], records_ref, CASE_ID, current_ref["sha256"])
    union = _read_small_json(union_path, "historical union")
    union_row = _validate_union(union, native_path, native_ref["sha256"], CASE_ID)
    native_first_count = sum("first_missing_frame" in item for item in native_ids["excluded"].values())
    native_bracket_count = sum(item.get("first_missing_bracket_s") is not None for item in native_ids["excluded"].values())
    contract = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "physical_case_id": CASE_ID,
        "family_id": FAMILY_ID,
        "expected_current_sha256": current_ref["sha256"],
        "inputs": {
            "current336": current_ref,
            "historical_union": union_ref,
            "root192_proof": proof_ref,
            "root192_summary": summary_ref,
            "native_omission_report": native_ref,
        },
        "deferred_records": records_ref,
        "source_edges": {
            "current_row": {
                "frames": int(current_row["frames"]), "particles": int(current_row["particles"]),
                "trajectory_path": current_row["trajectory"]["path"],
                "trajectory_sha256": current_row["trajectory"]["producer_declared_sha256"],
            },
            "native_union_row": union_row,
            "typed_trajectory": trajectory,
            "native_first_missing_evidence": native_first_count,
            "native_saved_bracket_evidence": native_bracket_count,
            "native_missing_first_evidence_scope": "per-ID only where report has first_missing_frame; no count inference",
        },
        "comparison": {
            "identity_key": "(Zone,Idp)",
            "native_key_source": "small source-bound omission report excluded_particles",
            "typed_key_source": "ROOT192 records JSONL after parent reservation",
            "typed_first_missing_semantics": "first saved frame valid-mask active-to-inactive",
            "native_first_missing_semantics": "saved frame/bracket from PartVTKOut/RunPARTs reconciliation",
            "native_exact_event_time": "UNKNOWN",
            "continuous_crossing_or_hidden_event": "UNKNOWN",
            "missing_native_first_frame": "UNKNOWN; do not infer from missing count",
        },
        "resource_policy": {
            "cpu_threads": 1,
            "max_wall_seconds": 900,
            "memory_max_bytes": 1024 * 1024 * 1024,
            "output_cap_bytes": MAX_OUTPUT_BYTES,
            "records_passes_minimum": 1,
            "records_read_policy": "single binary pass with SHA and JSONL parse after parent reservation",
            "h5_read": False,
            "native_partout_read": False,
            "solver_launch": False,
        },
        "claim_boundary": {
            "saved_frame_identity_join": "bounded diagnostic only",
            "native_numerical_cause": "prior report evidence only",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "launch_allowed": False,
        "launch_owner": "root",
        "request_note": "Parent must create a new guarded request; this contract never opens ROOT192 JSONL or H5 during prepare.",
    }
    return contract


def _request_from_contract(contract_path: Path, output_path: Path, worker: Path | None, python: Path | None) -> dict[str, Any]:
    contract = _read_small_json(contract_path, "ROOT199 V2 contract")
    inputs = contract.get("inputs", {})
    input_files = [str(contract_path.resolve())]
    for role in ("current336", "historical_union", "root192_proof", "root192_summary", "native_omission_report"):
        input_files.append(str(Path(inputs[role]["path"]).resolve()))
    if worker is None:
        worker = SCRIPT
    python_declared = VENV if python is None else Path(python).expanduser()
    python_resolved = python_declared.resolve()
    worker = _path(worker, "worker")
    if not python_resolved.is_file():
        raise CrosscheckError(f"python interpreter is missing: {python_declared}")
    input_files.append(str(worker))
    input_files = sorted(set(input_files))
    deferred = [str(Path(contract["deferred_records"]["path"]).resolve())]
    return {
        "schema": REQUEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "task_kind": "audit",
        "physical_case_id": contract["physical_case_id"],
        "family_id": contract["family_id"],
        "command": [str(python_declared), str(worker), "audit", "--contract", "{attempt_root}/root199-contract-v2.json", "--output", "{attempt_root}/root199-crosscheck-v2.json"],
        "input_files": input_files,
        "deferred_input_files": deferred,
        "input_sha256": {path: _sha256_file(Path(path), max_bytes=MAX_SMALL_BYTES) for path in input_files},
        "deferred_input_sha256": {deferred[0]: contract["deferred_records"]["sha256"]},
        "contract": {"path": str(contract_path.resolve()), "sha256": _sha256_file(contract_path, max_bytes=MAX_SMALL_BYTES)},
        "interpreter_binding": {"literal_path": str(python_declared), "resolved_path": str(python_resolved), "sha256": _sha256_file(python_resolved, max_bytes=MAX_SMALL_BYTES)},
        "resource_policy": contract["resource_policy"],
        "claim_boundary": contract["claim_boundary"],
        "launch_allowed": False,
        "launch_owner": "root",
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    contract = _build_contract(
        current_path=_path(args.current, "CURRENT336"), current_sha=args.current_sha256,
        union_path=_path(args.union, "historical union"), union_sha=args.union_sha256,
        proof_path=_path(args.root192_proof, "ROOT192 proof"), proof_sha=args.root192_proof_sha256,
        summary_path=_path(args.root192_summary, "ROOT192 summary"), summary_sha=args.root192_summary_sha256,
        native_path=_path(args.native_report, "native omission report"), native_sha=args.native_report_sha256,
    )
    output = Path(args.output).expanduser().resolve()
    _atomic_json(output, contract)
    result: dict[str, Any] = {"status": contract["status"], "contract": str(output), "contract_sha256": _sha256_file(output, max_bytes=MAX_OUTPUT_BYTES)}
    if args.request_output:
        request = _request_from_contract(output, Path(args.request_output).expanduser().resolve(), Path(args.worker).expanduser() if args.worker else None, Path(args.python).expanduser() if args.python else None)
        request_output = Path(args.request_output).expanduser().resolve()
        _atomic_json(request_output, request)
        result["request"] = str(request_output)
        result["request_sha256"] = _sha256_file(request_output, max_bytes=MAX_OUTPUT_BYTES)
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


def audit(contract_path: Path, output_path: Path) -> dict[str, Any]:
    """Perform the post-reservation one-pass JSONL comparison."""
    contract, current, summary, native, native_ids = _load_static_contract(Path(contract_path).expanduser().resolve())
    records_ref = contract["deferred_records"]
    records_path = _path(records_ref["path"], "typed records", allow_deferred=True)
    before = _stat(records_path, "typed records", allow_deferred=True)
    expected_rows = int(records_ref["rows"])
    expected_sha = _sha(records_ref["sha256"], "typed records expected SHA")
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
                raw_population = header.get("record_population")
                if raw_population is not None:
                    declared_population = _integer(raw_population, "typed records header record_population")
                    if declared_population < 0:
                        raise CrosscheckError("typed records header record_population is negative")
                header_fields = header.get("record_fields")
                if header_fields is not None:
                    if not isinstance(header_fields, list) or any(not isinstance(field, str) for field in header_fields) or len(set(header_fields)) != len(header_fields):
                        raise CrosscheckError("typed records header record_fields must be a unique string list")
                continue
            record_count += 1
            zone = _integer(row.get("zone"), f"typed record line {line_no} zone")
            idp = _integer(row.get("idp"), f"typed record line {line_no} Idp")
            key = (zone, idp)
            if key in seen_records:
                raise CrosscheckError(f"duplicate typed record identity: {key}")
            seen_records.add(key)
            # The typed JSONL contains every static identity.  Native
            # omission evidence covers only a subset (118 in the ROOT192
            # pilot), so non-target rows are validated for whole-record
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
    actual_sha = digest.hexdigest()
    if before != after:
        raise CrosscheckError("typed records changed during single pass")
    if actual_sha != expected_sha:
        raise CrosscheckError(f"typed records SHA differs: expected {expected_sha}, got {actual_sha}")
    if record_count != expected_rows:
        raise CrosscheckError(f"typed records row count differs: expected {expected_rows}, got {record_count}")
    if not set(native_rows).issubset(seen_records):
        missing = sorted(set(native_rows) - seen_records)
        raise CrosscheckError(f"typed records omit native IDs: {missing[:4]}")
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
        "native_evidence": {"id_count": len(native_rows), "first_missing_frame_count": sum(value.get("native_first_missing_frame") is not None for value in ordered), "first_missing_bracket_count": sum(value.get("native_first_missing_bracket_s") is not None for value in ordered)},
        "typed_evidence": {"record_count": record_count, "non_target_record_count": non_target_record_count, "native_key_join_count": len(ordered), "first_disappearance_count": sum(value.get("typed_first_disappeared_frame") is not None for value in ordered)},
        "comparison_counts": {"saved_frame_matches": sum(value["saved_frame_match"] is True for value in ordered), "saved_frame_mismatches": sum(value["saved_frame_match"] is False for value in ordered), "saved_frame_unknown": sum(value["saved_frame_match"] is None for value in ordered), "typed_times_in_native_brackets": sum(value["typed_time_in_native_bracket"] is True for value in ordered), "typed_times_outside_or_unknown_brackets": sum(value["typed_time_in_native_bracket"] is not True for value in ordered)},
        "rows": ordered,
        "claim_boundary": {"native_cause": "source-bound prior report only", "continuous_event_time": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_read_cost": {"records_minimum_passes": 1, "records_bytes": after["bytes"], "output_cap_bytes": MAX_OUTPUT_BYTES},
    }
    _atomic_json(Path(output_path), output)
    return {"status": output["status"], "output": str(Path(output_path).resolve()), "record_count": record_count, "saved_frame_matches": output["comparison_counts"]["saved_frame_matches"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare", help="build metadata-only ROOT199 V2 contract")
    prep.add_argument("--current", type=Path, required=True)
    prep.add_argument("--current-sha256", required=True)
    prep.add_argument("--union", type=Path, required=True)
    prep.add_argument("--union-sha256", required=True)
    prep.add_argument("--root192-proof", type=Path, required=True)
    prep.add_argument("--root192-proof-sha256", required=True)
    prep.add_argument("--root192-summary", type=Path, required=True)
    prep.add_argument("--root192-summary-sha256", required=True)
    prep.add_argument("--native-report", type=Path, required=True)
    prep.add_argument("--native-report-sha256", required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--worker", type=Path)
    prep.add_argument("--python", type=Path)
    audit_parser = subparsers.add_parser("audit", help="read deferred JSONL after parent reservation")
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
