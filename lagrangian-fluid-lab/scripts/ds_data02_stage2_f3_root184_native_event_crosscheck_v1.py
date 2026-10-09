#!/usr/bin/env python3
"""Cross-check ROOT182 PartOut brackets against a future ROOT178 full stream.

ROOT182 is a bounded official-PartVTKOut audit with 512 Idp rows.  ROOT178
is a separate full-window observer whose report contains per-frame identity
events.  This forward-only consumer compares the two products after ROOT178
has a terminal proof.  It derives each first missing frame from the first
``disappeared_idp`` event in the frame sequence and deliberately ignores any
legacy ``first_missing_frame`` field in an identity record.

The output is a small operational diagnostic (maximum 2 MiB).  ``MATCH``,
``OFFSET``, and ``UNKNOWN`` describe source-record agreement only.  They do
not establish physical fate, legal flux, dynamics, QI, QN, QE, or recovery of
the original CURRENT336/118 omission product.  ``prepare`` may be used now:
it records ROOT182 and future ROOT178 paths without opening future output.
``finalize``/``audit`` must only be used after ROOT178 proof, receipt, and
full report are immutable and source-bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f3.root184-native-event-crosscheck.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3.root184-native-event-crosscheck-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
DEFERRED = "PARENT_GUARD_COMPUTED"
ROOT182_CASE = "F3_S2_MATCHED_FINE_SAME_CFL_ROOT_170"
ROOT182_PHYSICAL = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
ROOT182_REPORT_SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-audit.v1"
ROOT178_REPORT_SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v3"
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_FULL_REPORT_BYTES = 900 * 1024 * 1024
BLOCKED_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".vtk", ".vtu"}


class Root184Error(ValueError):
    """Raised for a source, schema, or semantic-contract mismatch."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, label: str, *, allow_missing: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise Root184Error(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        raise Root184Error(f"{label} points at a blocked scientific payload: {path}")
    if not allow_missing and not path.is_file():
        raise Root184Error(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise Root184Error(f"{label} is missing: {path}")
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _stable_ref(path: Path, label: str, *, expected_sha: str | None = None, max_bytes: int | None = None) -> dict[str, Any]:
    path = _path(path, label)
    before = _stat(path, label)
    if max_bytes is not None and before["bytes"] > max_bytes:
        raise Root184Error(f"{label} exceeds bounded source size {max_bytes}: {before['bytes']}")
    actual = sha256_file(path)
    after = _stat(path, label)
    if before != after:
        raise Root184Error(f"{label} changed while being hashed: {path}")
    if expected_sha is not None and actual != expected_sha:
        raise Root184Error(f"{label} SHA differs: {path}")
    return {**before, "sha256": actual, "stable_read": True, "role": label}


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Root184Error(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Root184Error(f"{label} must be a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int | None = None) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise Root184Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        size = temporary.stat().st_size
        if max_bytes is not None and size > max_bytes:
            raise Root184Error(f"output exceeds bounded size {max_bytes}: {size}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result == value or isinstance(value, int) else None


def _same_number(left: Any, right: Any) -> bool:
    # Deliberately no scientific tolerance: source records either carry the
    # same saved value or they are reported as an offset.
    return _num(left) is not None and _num(right) is not None and float(left) == float(right)


def _bracket(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    left, right = (_num(value[0]), _num(value[1]))
    if left is None or right is None:
        return None
    return [left, right]


def _root182_inputs(proof_path: Path, report_path: Path, receipt_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof_path = _path(proof_path, "ROOT182 proof")
    report_path = _path(report_path, "ROOT182 report")
    receipt_path = _path(receipt_path, "ROOT182 receipt")
    proof = _json(proof_path, "ROOT182 proof")
    report_sha = sha256_file(report_path)
    receipt_sha = sha256_file(receipt_path)
    if proof.get("report") != str(report_path) or proof.get("report_sha256") != report_sha:
        raise Root184Error("ROOT182 proof/report binding differs")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != receipt_sha:
        raise Root184Error("ROOT182 proof/receipt binding differs")
    if "ACTUAL" not in str(proof.get("status", "")):
        raise Root184Error("ROOT182 proof is not an actual terminal proof")
    report = _json(report_path, "ROOT182 report")
    if report.get("schema") != ROOT182_REPORT_SCHEMA:
        raise Root184Error(f"unexpected ROOT182 report schema: {report.get('schema')!r}")
    case = report.get("case")
    if not isinstance(case, dict) or case.get("case_id") != ROOT182_CASE or case.get("physical_case_id") != ROOT182_PHYSICAL:
        raise Root184Error("ROOT182 report case identity differs")
    rows = report.get("native_identity", {}).get("rows") if isinstance(report.get("native_identity"), dict) else None
    if not isinstance(rows, list) or len(rows) != 512:
        raise Root184Error("ROOT182 native identity row count is not exactly 512")
    idps: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise Root184Error(f"ROOT182 row {index} is not an object")
        idp = _int(row.get("idp"))
        part = _int(row.get("part_out"))
        bracket = _bracket(row.get("saved_record_bracket_s"))
        if idp is None or part is None or bracket is None:
            raise Root184Error(f"ROOT182 row {index} lacks Idp/PartOut/bracket")
        if idp in idps:
            raise Root184Error(f"ROOT182 duplicate Idp: {idp}")
        idps.add(idp)
    receipt = _json(receipt_path, "ROOT182 receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise Root184Error("ROOT182 receipt is not completed")
    return proof, report, receipt, {
        "path": str(report_path), "sha256": report_sha, "bytes": report_path.stat().st_size,
        "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha,
        "proof_path": str(proof_path), "proof_sha256": sha256_file(proof_path),
    }


def _root178_inputs(proof_path: Path, report_path: Path, receipt_path: Path, *, max_report_bytes: int = MAX_FULL_REPORT_BYTES) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load the future full report once, bracketed by stable SHA/stat reads."""
    proof_path = _path(proof_path, "ROOT178 proof")
    report_path = _path(report_path, "ROOT178 full report")
    receipt_path = _path(receipt_path, "ROOT178 receipt")
    proof = _json(proof_path, "ROOT178 proof")
    report_ref = _stable_ref(report_path, "ROOT178 full report", expected_sha=proof.get("report_sha256"), max_bytes=max_report_bytes)
    report = _json(report_path, "ROOT178 full report")
    after = _stable_ref(report_path, "ROOT178 full report post-read", expected_sha=report_ref["sha256"], max_bytes=max_report_bytes)
    receipt = _json(receipt_path, "ROOT178 receipt")
    receipt_ref = _stable_ref(receipt_path, "ROOT178 receipt")
    if proof.get("report") != str(report_path) or proof.get("report_sha256") != report_ref["sha256"]:
        raise Root184Error("ROOT178 proof/report binding differs")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != receipt_ref["sha256"]:
        raise Root184Error("ROOT178 proof/receipt binding differs")
    if "ACTUAL" not in str(proof.get("status", "")):
        raise Root184Error("ROOT178 proof is not an actual terminal proof")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise Root184Error("ROOT178 receipt is not completed")
    if report.get("schema") != ROOT178_REPORT_SCHEMA:
        raise Root184Error(f"unexpected ROOT178 report schema: {report.get('schema')!r}")
    observations = report.get("observations")
    if not isinstance(observations, list) or not observations:
        raise Root184Error("ROOT178 report has no observations")
    case_id = receipt.get("request", {}).get("physical_case_id") if isinstance(receipt.get("request"), dict) else None
    if case_id is not None and case_id != ROOT182_PHYSICAL:
        raise Root184Error("ROOT178 terminal request physical case differs")
    return proof, report, receipt, {
        "path": str(report_path), "sha256": report_ref["sha256"], "bytes": report_ref["bytes"],
        "post_read": after, "receipt_path": str(receipt_path), "receipt_sha256": receipt_ref["sha256"],
        "proof_path": str(proof_path), "proof_sha256": sha256_file(proof_path),
        "read_passes": 3,
    }


def _event_index(report: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    observations = report.get("observations")
    if not isinstance(observations, list) or not observations:
        raise Root184Error("ROOT178 observations are missing")
    events: dict[int, dict[str, Any]] = {}
    unknown_rows = 0
    previous_frame: int | None = None
    previous_time: float | None = None
    frames: list[int] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            unknown_rows += 1
            continue
        frame = _int(observation.get("frame"))
        if frame is None:
            unknown_rows += 1
            continue
        if previous_frame is not None and frame <= previous_frame:
            raise Root184Error("ROOT178 observations are not strictly increasing by frame")
        frames.append(frame)
        time = _num(observation.get("runparts_time_s"))
        if time is None:
            time = _num(observation.get("decoded_time_s"))
        lifecycle = observation.get("identity_lifecycle")
        if not isinstance(lifecycle, dict):
            unknown_rows += 1
            previous_frame, previous_time = frame, time
            continue
        disappeared = lifecycle.get("disappeared_idp")
        appeared = lifecycle.get("appeared_idp")
        if not isinstance(disappeared, list) or not isinstance(appeared, list):
            unknown_rows += 1
            previous_frame, previous_time = frame, time
            continue
        try:
            disappeared_ids = [_int(value) for value in disappeared]
        except TypeError:
            disappeared_ids = []
        if any(value is None for value in disappeared_ids):
            unknown_rows += 1
            previous_frame, previous_time = frame, time
            continue
        for idp in dict.fromkeys(disappeared_ids):
            if idp in events:
                # The first event remains authoritative for first-missing;
                # later disappearances are counted separately in metadata.
                events[idp]["repeat_disappearance_count"] += 1
                continue
            events[idp] = {
                "idp": idp,
                "event_frame": frame,
                "event_time_s": time,
                "lower_frame": previous_frame,
                "lower_time_s": previous_time,
                "upper_frame": frame,
                "upper_time_s": time,
                "observation_index": index,
                "repeat_disappearance_count": 0,
            }
        previous_frame, previous_time = frame, time
    return events, {
        "observation_count": len(observations),
        "first_frame": frames[0] if frames else "UNKNOWN",
        "last_frame": frames[-1] if frames else "UNKNOWN",
        "unknown_event_rows": unknown_rows,
        "first_missing_source": "first per-frame disappeared_idp event",
        "legacy_first_missing_fields_used": False,
        "continuous_event_time": "UNKNOWN",
    }


def _compare_rows(root182_rows: list[dict[str, Any]], events: dict[int, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    result: list[dict[str, Any]] = []
    counts = {"MATCH": 0, "OFFSET": 0, "UNKNOWN": 0}
    for row in root182_rows:
        idp = _int(row.get("idp"))
        part = _int(row.get("part_out"))
        expected = _bracket(row.get("saved_record_bracket_s"))
        event = events.get(idp) if idp is not None else None
        derived = None
        reasons: list[str] = []
        if event is None:
            classification = "UNKNOWN"
            reasons.append("NO_DISAPPEARANCE_EVENT_IN_ROOT178_WINDOW")
        else:
            if event.get("lower_time_s") is None or event.get("upper_time_s") is None:
                reasons.append("EVENT_BRACKET_TIME_UNKNOWN")
            else:
                derived = [float(event["lower_time_s"]), float(event["upper_time_s"])]
            if part != event.get("event_frame"):
                reasons.append("PARTOUT_FRAME_DIFFERS_FROM_FIRST_EVENT_FRAME")
            if derived is None or expected != derived:
                reasons.append("SAVED_BRACKET_DIFFERS_FROM_EVENT_BRACKET")
            classification = "MATCH" if not reasons else "OFFSET"
        counts[classification] += 1
        result.append({
            "idp": idp,
            "motive": row.get("motive"),
            "motive_code": row.get("motive_code"),
            "root182_part_out": part,
            "root182_saved_record_bracket_s": expected,
            "root178_event_frame": event.get("event_frame") if event else None,
            "root178_event_bracket_s": derived,
            "root178_event_observation_index": event.get("observation_index") if event else None,
            "repeat_disappearance_count_after_first": event.get("repeat_disappearance_count") if event else None,
            "classification": classification,
            "reason": reasons,
        })
    return result, counts


def crosscheck(root182_proof: dict[str, Any], root182_report: dict[str, Any], root182_binding: dict[str, Any], root178_proof: dict[str, Any], root178_report: dict[str, Any], root178_receipt: dict[str, Any], root178_binding: dict[str, Any]) -> dict[str, Any]:
    rows = root182_report["native_identity"]["rows"]
    events, event_scope = _event_index(root178_report)
    per_id, counts = _compare_rows(rows, events)
    root_ids = {int(row["idp"]) for row in rows}
    extra_event_ids = sorted(set(events) - root_ids)
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_ROOT184_EVENT_BRACKET_CROSSCHECK_NO_PHYSICAL_CREDIT",
        "summary_scope": "bounded_native_identity_and_saved_bracket_diagnostic",
        "root182_binding": {"proof": root182_binding["proof_path"], "proof_sha256": root182_binding["proof_sha256"], "report": root182_binding["path"], "report_sha256": root182_binding["sha256"], "receipt": root182_binding["receipt_path"], "receipt_sha256": root182_binding["receipt_sha256"], "row_count": len(rows), "native_payload_reopened_by_root184": False},
        "root178_binding": {"proof": root178_binding["proof_path"], "proof_sha256": root178_binding["proof_sha256"], "report": root178_binding["path"], "report_sha256": root178_binding["sha256"], "report_bytes": root178_binding["bytes"], "report_post_read_sha256": root178_binding["post_read"]["sha256"], "receipt": root178_binding["receipt_path"], "receipt_sha256": root178_binding["receipt_sha256"], "full_report_read_passes_minimum": root178_binding["read_passes"], "native_payload_reopened_by_root184": False},
        "event_derivation": event_scope,
        "comparison": {
            "root182_id_count": len(rows),
            "root178_first_disappearance_id_count": len(events),
            "root178_event_ids_not_in_root182": extra_event_ids[:64],
            "root178_event_ids_not_in_root182_count": len(extra_event_ids),
            "classification_counts": counts,
            "per_id": per_id,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "scope_limits": [
            "First missing is derived only from the first saved-frame disappeared_idp event; continuous event time is UNKNOWN.",
            "ROOT182 legacy first_missing fields are not read or trusted.",
            "MATCH/OFFSET/UNKNOWN describes native product bracket agreement only.",
            "Disappearance does not prove physical outflow, legal flux, deletion, or fate.",
            "This ROOT178/ROOT182 comparison is a new F3 reference diagnostic and cannot restore original CURRENT336/118 credit.",
        ],
        "read_policy": {"json_reports_only": True, "root184_opened_h5_raw_bi4_obi4_vtk": False, "solver_started": False, "cfd_or_model_started": False},
        "resource_accounting": {"max_output_bytes": MAX_OUTPUT_BYTES, "full_report_max_bytes": MAX_FULL_REPORT_BYTES, "planned_peak_memory_bytes": 4 * 1024 * 1024 * 1024, "full_report_hash_parse_hash_minimum_passes": 3},
    }


def _manifest_ref(path: Path, role: str, *, deferred: bool = False) -> dict[str, Any]:
    path = _path(path, role, allow_missing=deferred)
    if deferred:
        return {"role": role, "path": str(path), "sha256": DEFERRED, "content_read_by_preparer": False, "status": "WAITING_ROOT178_TERMINAL"}
    return {**_stable_ref(path, role, max_bytes=MAX_FULL_REPORT_BYTES if "report" in role else None), "role": role}


def _deferred_manifest_ref(path: Path, role: str, expected_sha: str) -> dict[str, Any]:
    """Record a large future report by stat/SHA declaration without reading it."""
    path = _path(path, role)
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or any(char not in "0123456789abcdef" for char in expected_sha.lower()):
        raise Root184Error(f"{role} needs a concrete proof SHA")
    return {**_stat(path, role), "role": role, "sha256": expected_sha.lower(), "content_read_by_builder": False, "read_after_reservation": True, "minimum_read_passes": 3}


def prepare_manifest(args: argparse.Namespace) -> Path:
    output = Path(args.output).expanduser().resolve()
    root182_proof = _path(args.root182_proof, "ROOT182 proof")
    root182_report = _path(args.root182_report, "ROOT182 report")
    root182_receipt = _path(args.root182_receipt, "ROOT182 receipt")
    # This validates and hashes only ROOT182 small metadata.  Future ROOT178
    # files may not exist yet and are intentionally not opened here.
    _root182_inputs(root182_proof, root182_report, root182_receipt)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "WAITING_ROOT178_TERMINAL",
        "case_id": ROOT182_CASE,
        "physical_case_id": ROOT182_PHYSICAL,
        "source_refs": [
            _manifest_ref(root182_proof, "root182_proof"),
            _manifest_ref(root182_report, "root182_report"),
            _manifest_ref(root182_receipt, "root182_receipt"),
            _manifest_ref(Path(args.root178_proof), "root178_proof", deferred=True),
            _manifest_ref(Path(args.root178_report), "root178_report", deferred=True),
            _manifest_ref(Path(args.root178_receipt), "root178_receipt", deferred=True),
        ],
        "read_policy": {"prepare_json_only": True, "future_root178_opened_by_preparer": False, "root184_scientific_credit": "NONE", "root182_original_current118_credit": "NONE"},
        "future_guard": {"max_output_bytes": MAX_OUTPUT_BYTES, "planned_peak_memory_bytes": 4 * 1024 * 1024 * 1024, "full_report_hash_parse_hash_minimum_passes": 3, "deferred_input_after_reservation": True},
        "semantic_contract": {"first_missing_source": "ROOT178 observations[].identity_lifecycle.disappeared_idp first event", "legacy_first_missing_field": "ignored", "classification": ["MATCH", "OFFSET", "UNKNOWN"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "QI_QN_QE": "UNKNOWN"},
    }
    _atomic_json(output, manifest, max_bytes=256 * 1024)
    return output


def build_final_manifest(args: argparse.Namespace) -> Path:
    output = Path(args.output).expanduser().resolve()
    root182_proof = _path(args.root182_proof, "ROOT182 proof")
    root182_report = _path(args.root182_report, "ROOT182 report")
    root182_receipt = _path(args.root182_receipt, "ROOT182 receipt")
    root178_proof = _path(args.root178_proof, "ROOT178 proof")
    root178_report = _path(args.root178_report, "ROOT178 report")
    root178_receipt = _path(args.root178_receipt, "ROOT178 receipt")
    _root182_inputs(root182_proof, root182_report, root182_receipt)
    # ROOT178 is terminal, but the full report can be hundreds of MiB.  The
    # final manifest builder consumes only its small proof/receipt and the
    # proof-declared report SHA/stat; full content is deferred to the guarded
    # worker's hash -> parse -> hash sequence.
    root178_proof_value = _json(root178_proof, "ROOT178 proof")
    root178_receipt_value = _json(root178_receipt, "ROOT178 receipt")
    expected_report_sha = root178_proof_value.get("report_sha256")
    if root178_proof_value.get("report") != str(root178_report) or not isinstance(expected_report_sha, str):
        raise Root184Error("ROOT178 proof does not bind the requested report")
    if root178_proof_value.get("receipt") != str(root178_receipt) or "ACTUAL" not in str(root178_proof_value.get("status", "")):
        raise Root184Error("ROOT178 proof/receipt terminal binding is not actual")
    if root178_receipt_value.get("status") != "completed" or root178_receipt_value.get("returncode") != 0:
        raise Root184Error("ROOT178 receipt is not completed")
    if isinstance(root178_receipt_value.get("request"), dict) and root178_receipt_value["request"].get("physical_case_id") not in {None, ROOT182_PHYSICAL}:
        raise Root184Error("ROOT178 receipt physical case differs")
    _stat(root178_report, "ROOT178 full report deferred source")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_ROOT184_GUARDED_AUDIT",
        "case_id": ROOT182_CASE,
        "physical_case_id": ROOT182_PHYSICAL,
        "source_refs": [
            _manifest_ref(root182_proof, "root182_proof"),
            _manifest_ref(root182_report, "root182_report"),
            _manifest_ref(root182_receipt, "root182_receipt"),
            _manifest_ref(root178_proof, "root178_proof"),
            _deferred_manifest_ref(root178_report, "root178_report", expected_report_sha),
            _manifest_ref(root178_receipt, "root178_receipt"),
        ],
        "deferred_full_report": {"path": str(root178_report), "sha256": sha256_file(root178_report), "read_after_reservation": True, "hash_parse_hash_minimum_passes": 3, "max_memory_bytes": 4 * 1024 * 1024 * 1024},
        "output_contract": {"max_bytes": MAX_OUTPUT_BYTES, "per_id_rows": 512, "scientific_credit": "NONE"},
        "semantic_contract": {"first_missing_source": "ROOT178 observations[].identity_lifecycle.disappeared_idp first event", "legacy_first_missing_field": "ignored", "classification": ["MATCH", "OFFSET", "UNKNOWN"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "QI_QN_QE": "UNKNOWN"},
    }
    _atomic_json(output, manifest, max_bytes=256 * 1024)
    return output


def build_request(args: argparse.Namespace) -> Path:
    """Build a v8 request with the ROOT178 report as deferred input."""
    manifest_path = _path(args.manifest, "ROOT184 final manifest")
    manifest = _json(manifest_path, "ROOT184 final manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_ROOT184_GUARDED_AUDIT":
        raise Root184Error("manifest is not ROOT184 guarded-ready")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list):
        raise Root184Error("ROOT184 manifest source_refs are missing")
    refs_by_role = {ref.get("role"): ref for ref in refs if isinstance(ref, dict)}
    required_roles = {"root182_proof", "root182_report", "root182_receipt", "root178_proof", "root178_report", "root178_receipt"}
    if set(refs_by_role) < required_roles:
        raise Root184Error("ROOT184 manifest lacks terminal source roles")
    deferred = refs_by_role["root178_report"]
    if deferred.get("sha256") in {None, DEFERRED} or deferred.get("read_after_reservation") is not True:
        raise Root184Error("ROOT178 full report is not a concrete deferred source")
    output = Path(args.output).expanduser().resolve()
    worktree = Path(args.worktree_root).expanduser().resolve()
    cwd = Path(args.cwd).expanduser().resolve()
    worker = _path(args.worker, "ROOT184 worker")
    python = _path(args.python, "interpreter")
    runtime_v2 = _path(args.runtime_v2, "runtime v2")
    runtime_v6 = _path(args.runtime_v6, "runtime v6")
    runtime_v8 = _path(args.runtime_v8, "runtime v8")
    dispatch_v8 = _path(args.dispatch_v8, "dispatch v8")
    strict_v8 = _path(args.strict_v8, "strict dispatch v8")
    if not worktree.is_dir() or not cwd.is_dir():
        raise Root184Error("cwd/worktree_root must be existing directories")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise Root184Error("cwd must be inside worktree_root") from exc
    small_paths: list[tuple[Path, str]] = [(manifest_path, "root184_manifest"), (worker, "root184_worker"), (python, "interpreter"), (runtime_v2, "runtime_v2_base"), (runtime_v6, "runtime_v6_root"), (runtime_v8, "runtime_v8"), (dispatch_v8, "dispatch_v8"), (strict_v8, "strict_v8")]
    for role in ("root182_proof", "root182_report", "root182_receipt", "root178_proof", "root178_receipt"):
        ref = refs_by_role[role]
        small_paths.append((_path(ref.get("path"), role), role))
    input_refs = [_stable_ref(path, role) for path, role in small_paths]
    inputs = {ref["path"]: ref["sha256"] for ref in input_refs}
    deferred_path = str(Path(deferred["path"]).expanduser().resolve())
    command = [str(python), str(worker), "audit", "--root182-proof", refs_by_role["root182_proof"]["path"], "--root182-report", refs_by_role["root182_report"]["path"], "--root182-receipt", refs_by_role["root182_receipt"]["path"], "--root178-proof", refs_by_role["root178_proof"]["path"], "--root178-report", deferred_path, "--root178-receipt", refs_by_role["root178_receipt"]["path"], "--output", "{attempt_root}/root184-native-event-crosscheck.json", "--max-report-bytes", str(MAX_FULL_REPORT_BYTES)]
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": "F3",
        "case_id": "STAGE2_F3_ROOT184_NATIVE_EVENT_CROSSCHECK",
        "physical_case_id": ROOT182_PHYSICAL,
        "attempt_id": "f3-root184-native-event-crosscheck-v1-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 3600,
        "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT_BYTES,
        "estimated_cpu_core_hours": 1.0,
        "estimated_gpu_seconds": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_native_read_bytes": 0,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in input_refs),
        "estimated_deferred_source_bytes": int(deferred.get("bytes", 0)),
        "estimated_deferred_read_passes": 3,
        "estimated_deferred_read_bytes": int(deferred.get("bytes", 0)) * 3,
        "cwd": str(cwd),
        "worktree_root": str(worktree),
        "command": command,
        "input_files": [ref["path"] for ref in input_refs],
        "input_sha256": inputs,
        "deferred_input_files": [deferred_path],
        "deferred_input_policy": "after_reservation_sha_parse_sha; worker owns stable full-report read",
        "deferred_input_records": [{"path": deferred_path, "expected_sha256": deferred["sha256"], "bytes": deferred["bytes"], "read_after_reservation": True, "minimum_read_passes": 3, "content_read_by_builder": False}],
        "runtime_binding": {"runtime_v2_base": {"path": str(runtime_v2), "sha256": inputs[str(runtime_v2)]}, "runtime_v6_root": {"path": str(runtime_v6), "sha256": inputs[str(runtime_v6)]}, "runtime_v8": {"path": str(runtime_v8), "sha256": inputs[str(runtime_v8)]}},
        "dispatch_binding": {"dispatch_v8": {"path": str(dispatch_v8), "sha256": inputs[str(dispatch_v8)]}},
        "strict_dispatch_binding": {"strict_v8": {"path": str(strict_v8), "sha256": inputs[str(strict_v8)]}},
        "manifest_contract": {"path": str(manifest_path), "sha256": inputs[str(manifest_path)]},
        "guarded_payload_binding": {"root178_full_report": "deferred_after_reservation", "h5_content_read": False, "raw_partout_content_read": False, "native_array_read": False, "solver_started": False, "scientific_credit": "NONE"},
        "claim_boundary": {"event_bracket_comparison": "MATCH/OFFSET/UNKNOWN only", "first_missing_continuous_time": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "original_current118_credit": "NONE"},
        "launch_allowed": True,
        "execution_allowed": True,
        "request_note": "ROOT184 deferred full JSON report consumer; output <=2MiB; first missing derived from per-frame disappeared events; preserve ROOT182/ROOT178 and no physical credit.",
    }
    _atomic_json(output, request, max_bytes=256 * 1024)
    return output


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise Root184Error(f"refusing to overwrite output: {output}")
    root182_proof, root182_report, root182_receipt, root182_binding = _root182_inputs(args.root182_proof, args.root182_report, args.root182_receipt)
    root178_proof, root178_report, root178_receipt, root178_binding = _root178_inputs(args.root178_proof, args.root178_report, args.root178_receipt, max_report_bytes=int(args.max_report_bytes))
    result = crosscheck(root182_proof, root182_report, root182_binding, root178_proof, root178_report, root178_receipt, root178_binding)
    _atomic_json(output, result, max_bytes=MAX_OUTPUT_BYTES)
    return result


def self_test() -> dict[str, Any]:
    full = {
        "schema": ROOT178_REPORT_SCHEMA,
        "observations": [
            {"frame": 0, "runparts_time_s": 0.0, "identity_lifecycle": {"appeared_idp": [10, 11], "disappeared_idp": []}},
            {"frame": 10, "runparts_time_s": 1.0, "identity_lifecycle": {"appeared_idp": [], "disappeared_idp": [10, 12]}},
            {"frame": 20, "runparts_time_s": 2.0, "identity_lifecycle": {"appeared_idp": [10], "disappeared_idp": [10, 11]}},
        ],
    }
    events, scope = _event_index(full)
    if events[10]["event_frame"] != 10 or events[10]["lower_time_s"] != 0.0 or events[10]["repeat_disappearance_count"] != 1:
        raise AssertionError("event-derived first missing self-test failed")
    rows = [
        {"idp": 10, "motive": "position", "motive_code": 1, "part_out": 10, "saved_record_bracket_s": [0.0, 1.0]},
        {"idp": 11, "motive": "position", "motive_code": 1, "part_out": 20, "saved_record_bracket_s": [1.0, 2.0]},
        {"idp": 12, "motive": "position", "motive_code": 1, "part_out": 11, "saved_record_bracket_s": [0.0, 1.0]},
        {"idp": 13, "motive": "position", "motive_code": 1, "part_out": 30, "saved_record_bracket_s": [2.0, 3.0]},
    ]
    compared, counts = _compare_rows(rows, events)
    if counts != {"MATCH": 2, "OFFSET": 1, "UNKNOWN": 1}:
        raise AssertionError(f"unexpected comparison counts: {counts}")
    if compared[3]["classification"] != "UNKNOWN":
        raise AssertionError("missing event was not classified UNKNOWN")
    legacy = {"id_lifecycle": {"records": [{"idp": 10, "first_missing_frame": 999}]}}
    if "first_missing_frame" in legacy["id_lifecycle"]["records"][0] and events[10]["event_frame"] == 999:
        raise AssertionError("legacy first_missing field was trusted")
    return {"status": "PASS", "schema": SCHEMA, "classification": ["MATCH", "OFFSET", "UNKNOWN"], "first_missing_from_disappeared_events": True, "max_output_bytes": MAX_OUTPUT_BYTES, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    self_parser = sub.add_parser("self-test")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--root182-proof", required=True, type=Path)
    prepare.add_argument("--root182-report", required=True, type=Path)
    prepare.add_argument("--root182-receipt", required=True, type=Path)
    prepare.add_argument("--root178-proof", required=True)
    prepare.add_argument("--root178-report", required=True)
    prepare.add_argument("--root178-receipt", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    final = sub.add_parser("finalize")
    for name in ("root182-proof", "root182-report", "root182-receipt", "root178-proof", "root178-report", "root178-receipt"):
        final.add_argument(f"--{name}", required=True, type=Path)
    final.add_argument("--output", required=True, type=Path)
    request = sub.add_parser("request")
    request.add_argument("--manifest", required=True, type=Path)
    request.add_argument("--output", required=True, type=Path)
    request.add_argument("--worker", type=Path, default=SCRIPT)
    request.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    request.add_argument("--runtime-v2", required=True, type=Path)
    request.add_argument("--runtime-v6", required=True, type=Path)
    request.add_argument("--runtime-v8", required=True, type=Path)
    request.add_argument("--dispatch-v8", required=True, type=Path)
    request.add_argument("--strict-v8", required=True, type=Path)
    request.add_argument("--cwd", required=True, type=Path)
    request.add_argument("--worktree-root", required=True, type=Path)
    audit = sub.add_parser("audit")
    for name in ("root182-proof", "root182-report", "root182-receipt", "root178-proof", "root178-report", "root178-receipt"):
        audit.add_argument(f"--{name}", required=True, type=Path)
    audit.add_argument("--output", required=True, type=Path)
    audit.add_argument("--max-report-bytes", default=MAX_FULL_REPORT_BYTES, type=int)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "prepare":
        print(json.dumps({"manifest": str(prepare_manifest(args))}, sort_keys=True))
        return 0
    if args.action == "finalize":
        print(json.dumps({"manifest": str(build_final_manifest(args))}, sort_keys=True))
        return 0
    if args.action == "request":
        print(json.dumps({"request": str(build_request(args))}, sort_keys=True))
        return 0
    if args.action == "audit":
        result = run_audit(args)
        print(json.dumps({"status": result["status"], "output": str(Path(args.output).resolve()), "classification_counts": result["comparison"]["classification_counts"]}, sort_keys=True))
        return 0
    raise AssertionError(args.action)


if __name__ == "__main__":
    raise SystemExit(main())
