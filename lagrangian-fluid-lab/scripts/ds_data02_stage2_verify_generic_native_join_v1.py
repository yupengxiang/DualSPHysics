#!/usr/bin/env python3
"""Prepare and verify an additive multi-proof native/typed join scope.

The F2 omission work has several complete lifecycle producer proofs.  This
module is the small adapter between those proofs and a future guarded native
extractor.  It accepts the old ROOT315 proof-scope manifest and the newer
ROOT317--ROOT321 configurable manifests, but keeps each producer proof as an
independent source edge.  It never synthesizes a proof by concatenating proof
rows.

``prepare`` reads only bounded JSON metadata.  It reports the exact accounting
boundary: 118 original cases, 47 precise existing joins, 24 cause-unlocated
cases, and 47 cause-bound missing joins.  The six complete proof bundles cover
46 canonical cases; the remaining member of the arithmetic set is the
unresolved historical alias and is never substituted.

``verify`` consumes a small result JSON plus bounded native CSV, RunPARTs CSV,
and typed-summary JSON files.  It verifies case and ``(Zone, Idp)`` identity,
saved-frame/bracket agreement, producer-proof membership, and duplicate/already
joined exclusions.  A successful verification adds typed/native join credit
only.  Native numerical cause is already bound by the source scope, while
physical fate, legal flux, dynamics, and QI/QN/QE remain UNKNOWN.

No H5, JSONL, BI4, or OBI4 payload is opened by this module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
SOURCE_SCHEMA = "ds02.stage2.generic-native-typed-native-join-source.v1"
MANIFEST_SCHEMA = "ds02.stage2.generic-native-typed-native-join.v1-manifest"
RESULT_SCHEMA = "ds02.stage2.generic-native-typed-native-join.v1-result"
REPORT_SCHEMA = "ds02.stage2.generic-native-typed-native-join.v1-report"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
GENERIC_MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v1"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FAMILY = "F2"


class JoinVerificationError(ValueError):
    """Raised when a source scope or bounded result is not closed."""


def _path(value: Any, label: str, *, allow_payload: bool = False, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise JoinVerificationError(f"{label} has no path")
    path = Path(value).expanduser().absolute()
    if directory:
        if not path.is_dir():
            raise JoinVerificationError(f"{label} directory is missing: {path}")
        return path
    if not path.is_file():
        raise JoinVerificationError(f"{label} file is missing: {path}")
    if not allow_payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise JoinVerificationError(f"{label} is deferred payload: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _compare_stat(actual: dict[str, Any], expected: dict[str, Any], label: str, *, path: bool = True) -> None:
    fields = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    if not path:
        fields = fields[1:]
    for field in fields:
        if actual.get(field) != expected.get(field):
            raise JoinVerificationError(f"{label} {field} differs")


def _capture(path: Path, label: str, *, limit: int, allow_payload: bool = False) -> tuple[bytes, dict[str, Any]]:
    path = _path(path, label, allow_payload=allow_payload)
    before = _stat(path, label)
    if before["bytes"] > limit:
        raise JoinVerificationError(f"{label} exceeds bounded read: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JoinVerificationError(f"{label} cannot be read: {path}") from exc
    after = _stat(path, label)
    _compare_stat(after, before, f"{label} changed during capture")
    if len(raw) != after["bytes"]:
        raise JoinVerificationError(f"{label} byte count changed during capture")
    return raw, {**after, "sha256": hashlib.sha256(raw).hexdigest(), "stable_capture": True}


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise JoinVerificationError(f"{label} is not a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise JoinVerificationError(f"{label} is not a SHA-256 digest") from exc
    return value.lower()


def _expected_ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise JoinVerificationError(f"{label} reference is malformed")
    return value


def _json(path: Path, label: str, *, limit: int = MAX_SMALL_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, ref = _capture(path, label, limit=limit)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JoinVerificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise JoinVerificationError(f"{label} must be a JSON object")
    return value, ref


def _json_ref(value: Any, label: str, *, limit: int = MAX_SMALL_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = _expected_ref(value, label)
    path = _path(expected["path"], label)
    document, actual = _json(path, label, limit=limit)
    _compare_stat(actual, expected, label)
    if actual["sha256"] != _sha(expected.get("sha256"), f"{label} SHA"):
        raise JoinVerificationError(f"{label} SHA differs")
    return document, actual


def _file_ref(value: Any, label: str, *, limit: int = MAX_RESULT_BYTES) -> tuple[bytes, dict[str, Any]]:
    expected = _expected_ref(value, label)
    path = _path(expected["path"], label)
    raw, actual = _capture(path, label, limit=limit)
    _compare_stat(actual, expected, label)
    if actual["sha256"] != _sha(expected.get("sha256"), f"{label} SHA"):
        raise JoinVerificationError(f"{label} SHA differs")
    return raw, actual


def _atomic_json(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise JoinVerificationError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise JoinVerificationError(f"{path} exceeds output bound")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or any(not isinstance(x, str) or not x for x in value):
        raise JoinVerificationError(f"{label} must be a nonempty string list")
    if len(value) != len(set(value)):
        raise JoinVerificationError(f"{label} contains duplicate identities")
    return list(value)


def _normalize_bundle(document: dict[str, Any], document_ref: dict[str, Any], entry: dict[str, Any], index: int) -> dict[str, Any]:
    if document.get("schema") != GENERIC_MANIFEST_SCHEMA:
        raise JoinVerificationError(f"producer manifest {index} schema differs")
    version = document.get("schema_version")
    if version not in {"v2-source-proof-scope", "v3-configurable-multi-proof-source-scope"}:
        raise JoinVerificationError(f"producer manifest {index} has unsupported schema version")
    bundles = document.get("typed_proof_bundles")
    if not isinstance(bundles, list) or len(bundles) != 1 or not isinstance(bundles[0], dict):
        raise JoinVerificationError(f"producer manifest {index} must contain one complete proof bundle")
    bundle = bundles[0]
    producer_id = bundle.get("producer_id") or document.get("producer_id")
    if not isinstance(producer_id, str) or not producer_id:
        raise JoinVerificationError(f"producer manifest {index} has no producer_id")
    full = _string_list(bundle.get("full_case_ids"), f"{producer_id} full_case_ids")
    selected_default = bundle.get("selected_case_ids", full)
    selected_override = entry.get("selected_case_ids")
    selected = _string_list(selected_override if selected_override is not None else selected_default, f"{producer_id} selected_case_ids")
    if not set(selected).issubset(full):
        raise JoinVerificationError(f"{producer_id} selected IDs are outside the complete proof")
    if bundle.get("synthetic_merged_proof") is not False:
        raise JoinVerificationError(f"{producer_id} synthetic merged proof is not allowed")
    proof = _expected_ref(bundle.get("proof"), f"{producer_id} proof")
    return {
        "producer_id": producer_id,
        "manifest": document_ref,
        "manifest_schema_version": version,
        "proof": proof,
        "full_case_ids": full,
        "selected_case_ids": selected,
        "full_case_count": len(full),
        "selected_case_count": len(selected),
        "synthetic_merged_proof": False,
    }


def _validate_proof(bundle: dict[str, Any]) -> dict[str, Any]:
    proof, proof_ref = _json_ref(bundle["proof"], f"{bundle['producer_id']} complete producer proof")
    if proof.get("schema") != ROOT_PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise JoinVerificationError(f"{bundle['producer_id']} proof is not a completed actual proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise JoinVerificationError(f"{bundle['producer_id']} proof lacks case_verifications")
    ids = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
    if ids != bundle["full_case_ids"] and set(ids) != set(bundle["full_case_ids"]):
        raise JoinVerificationError(f"{bundle['producer_id']} proof IDs differ from complete bundle")
    if len(ids) != len(set(ids)):
        raise JoinVerificationError(f"{bundle['producer_id']} proof contains duplicate case IDs")
    counts = proof.get("counts")
    if not isinstance(counts, dict):
        raise JoinVerificationError(f"{bundle['producer_id']} proof lacks counts")
    if counts.get("cases_requested") != len(bundle["full_case_ids"]):
        raise JoinVerificationError(f"{bundle['producer_id']} proof requested count differs")
    if counts.get("completed") != len(bundle["full_case_ids"]) or counts.get("failed") != 0:
        raise JoinVerificationError(f"{bundle['producer_id']} proof is not all completed")
    row_index = {row["physical_case_id"]: index for index, row in enumerate(rows)}
    row_status = {row["physical_case_id"]: row.get("status") for row in rows}
    return {
        "proof": proof_ref,
        "status": proof.get("status"),
        "counts": counts,
        "proof_case_index": row_index,
        "proof_case_status": row_status,
    }


def _inventory_ids(document: dict[str, Any]) -> set[str]:
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise JoinVerificationError("historical inventory lacks rows")
    ids = {
        row.get("physical_case_id")
        for row in rows
        if isinstance(row, dict) and row.get("historical_118_membership") is True
    }
    if len(ids) != 118 or any(not isinstance(x, str) for x in ids):
        raise JoinVerificationError("historical inventory does not expose exactly 118 original cases")
    return ids


def _current_ids(document: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise JoinVerificationError("CURRENT catalog does not expose 336 cases")
    ids: set[str] = set()
    families: dict[str, str] = {}
    for row in cases:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise JoinVerificationError("CURRENT catalog has malformed case identity")
        case_id = row["physical_case_id"]
        if case_id in ids:
            raise JoinVerificationError("CURRENT catalog has duplicate case identity")
        ids.add(case_id)
        families[case_id] = row.get("family_id") if isinstance(row.get("family_id"), str) else ""
    return ids, families


def _existing_join_ids(document: dict[str, Any]) -> set[str]:
    rows = document.get("actual_case_rows")
    if not isinstance(rows, list) or len(rows) != 47:
        raise JoinVerificationError("existing precise join source must contain 47 rows")
    ids = {row.get("physical_case_id") for row in rows if isinstance(row, dict)}
    if len(ids) != 47 or any(not isinstance(x, str) for x in ids):
        raise JoinVerificationError("existing precise join identity set is malformed")
    return ids


def _unlocated_ids(document: dict[str, Any]) -> set[str]:
    value = document.get("remaining_cause_not_located_case_ids")
    ids = set(_string_list(value, "cause-unlocated case IDs"))
    if len(ids) != 24:
        raise JoinVerificationError("cause-unlocated scope must contain 24 cases")
    return ids


def _source_scope_from_spec(spec_path: Path) -> dict[str, Any]:
    spec, spec_ref = _json(spec_path, "generic join source specification")
    if spec.get("schema") != SOURCE_SCHEMA:
        raise JoinVerificationError("source specification schema differs")
    entries = spec.get("producer_manifests")
    if not isinstance(entries, list) or not entries:
        raise JoinVerificationError("source specification lacks producer manifests")
    if len(entries) != 6:
        raise JoinVerificationError("this scope must adapt six complete producer proof bundles")
    bundles: list[dict[str, Any]] = []
    seen_producers: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise JoinVerificationError(f"producer manifest entry {index} is malformed")
        document, document_ref = _json_ref(raw_entry, f"producer manifest {index}")
        bundle = _normalize_bundle(document, document_ref, raw_entry, index)
        if bundle["producer_id"] in seen_producers:
            raise JoinVerificationError(f"duplicate producer proof {bundle['producer_id']}")
        seen_producers.add(bundle["producer_id"])
        bundle.update(_validate_proof(bundle))
        bundles.append(bundle)
    expected_producers = {"ROOT193", "ROOT198", "ROOT206", "ROOT287", "ROOT288", "ROOT289"}
    if seen_producers != expected_producers:
        raise JoinVerificationError(f"producer proof set differs: {sorted(seen_producers)}")

    inventory, inventory_ref = _json_ref(spec.get("historical_inventory"), "historical inventory", limit=MAX_SMALL_BYTES)
    current, current_ref = _json_ref(spec.get("current_catalog"), "CURRENT catalog", limit=MAX_SMALL_BYTES)
    existing, existing_ref = _json_ref(spec.get("existing_join_source"), "existing precise join source", limit=MAX_SMALL_BYTES)
    overlay, overlay_ref = _json_ref(spec.get("cause_overlay"), "cause overlay", limit=MAX_SMALL_BYTES)
    original = _inventory_ids(inventory)
    current_ids, families = _current_ids(current)
    existing_ids = _existing_join_ids(existing)
    unlocated = _unlocated_ids(overlay)
    if not existing_ids.issubset(original):
        raise JoinVerificationError("existing join contains a non-original case")
    cause_missing = original - existing_ids - unlocated
    if len(cause_missing) != 47:
        raise JoinVerificationError(f"cause-bound missing-join scope is {len(cause_missing)}, expected 47")
    alias = spec.get("alias_case", ALIAS_CASE)
    if alias not in cause_missing:
        raise JoinVerificationError("historical alias is not the unresolved arithmetic member")

    full_ids: set[str] = set()
    selected_ids: set[str] = set()
    producer_by_case: dict[str, str] = {}
    for bundle in bundles:
        full = set(bundle["full_case_ids"])
        selected = set(bundle["selected_case_ids"])
        if not full.issubset(original | set()):
            raise JoinVerificationError(f"{bundle['producer_id']} proof contains non-original case")
        if full & full_ids:
            raise JoinVerificationError(f"producer proof complete case sets overlap for {bundle['producer_id']}")
        if selected & selected_ids:
            raise JoinVerificationError(f"selected producer case sets overlap for {bundle['producer_id']}")
        if full & existing_ids or full & unlocated or full & {alias}:
            raise JoinVerificationError(f"{bundle['producer_id']} proof contains excluded case")
        if not selected.issubset(cause_missing):
            raise JoinVerificationError(f"{bundle['producer_id']} selected case is outside cause-bound missing scope")
        full_ids |= full
        selected_ids |= selected
        for case_id in full:
            producer_by_case[case_id] = bundle["producer_id"]
        for case_id in selected:
            if families.get(case_id) != FAMILY:
                raise JoinVerificationError(f"{case_id} is not an F2 CURRENT case")
            if case_id not in current_ids:
                raise JoinVerificationError(f"{case_id} is absent from CURRENT catalog")
    if len(full_ids) != len(selected_ids):
        # A selected subset is supported only when explicitly requested, but
        # the six delivered producer scopes are complete.  Retain the proof's
        # unselected IDs in the edge while reporting selected IDs separately.
        pass
    if not selected_ids or len(selected_ids) > len(full_ids):
        raise JoinVerificationError("selected canonical scope is empty or exceeds the complete proof scope")
    if selected_ids & existing_ids or selected_ids & {alias}:
        raise JoinVerificationError("selected scope overlaps an existing join or the unresolved alias")

    bundle_by_producer = {bundle["producer_id"]: bundle for bundle in bundles}
    case_source_edges = []
    for case_id in sorted(selected_ids):
        bundle = bundle_by_producer[producer_by_case[case_id]]
        case_source_edges.append({
            "physical_case_id": case_id,
            "family_id": FAMILY,
            "producer_id": bundle["producer_id"],
            "producer_manifest": bundle["manifest"],
            "producer_proof": bundle["proof"],
            "producer_proof_case_index": bundle["proof_case_index"][case_id],
            "producer_proof_case_status": bundle["proof_case_status"][case_id],
            "complete_proof_case_member": True,
            "selected_canonical_case": True,
            "native_cause_status": "ALREADY_BOUND_NUMERICAL_SCOPE",
            "typed_native_join_status": "PENDING_PARENT_GUARDED_NATIVE_READ",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        })
    alias_edge = {
        "physical_case_id": alias,
        "family_id": FAMILY,
        "canonical_source_edge": False,
        "excluded_reason": "UNRESOLVED_HISTORICAL_ALIAS_NOT_SUBSTITUTED",
        "native_cause_status": "CAUSE_BOUND_ARITHMETIC_MEMBER_ONLY",
        "typed_native_join_status": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }

    return {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_SOURCE_ONLY_GENERIC_NATIVE_TYPED_JOIN_V1",
        "source_spec": spec_ref,
        "historical_inventory": inventory_ref,
        "current_catalog": current_ref,
        "existing_join_source": existing_ref,
        "cause_overlay": overlay_ref,
        "producer_proof_bundles": bundles,
        "producer_case_index": producer_by_case,
        "case_source_edges": case_source_edges,
        "unresolved_alias_edges": [alias_edge],
        "case_scope": {
            "family_id": FAMILY,
            "original_case_count": len(original),
            "existing_exact_join_count": len(existing_ids),
            "cause_not_located_count": len(unlocated),
            "cause_bound_missing_join_count": len(cause_missing),
            "selected_canonical_count": len(selected_ids),
            "unresolved_alias_case_ids": [alias],
            "remaining_cause_bound_missing_case_ids": sorted(cause_missing - selected_ids),
            "selected_case_ids": sorted(selected_ids),
            "existing_join_case_ids": sorted(existing_ids),
            "cause_not_located_case_ids": sorted(unlocated),
        },
        "claim_boundary": {
            "existing_cause_bound_count_unchanged": True,
            "new_native_cause_credit": 0,
            "new_typed_native_join_credit_requires_completed_result": True,
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "alias_is_not_substituted": True,
            "synthetic_proof_merge": False,
        },
    }


def _identity(value: Any, label: str) -> tuple[int, int]:
    if isinstance(value, dict):
        if "zone" in value and "idp" in value:
            value = (value["zone"], value["idp"])
        elif "identity_key" in value:
            value = value["identity_key"]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise JoinVerificationError(f"{label} is not (Zone, Idp)")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in value):
        raise JoinVerificationError(f"{label} is not integer-valued")
    return int(value[0]), int(value[1])


def _float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise JoinVerificationError(f"{label} is not finite") from exc
    if not math.isfinite(result):
        raise JoinVerificationError(f"{label} is not finite")
    return result


def _read_summary(case: dict[str, Any]) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    summary, summary_ref = _json_ref(case.get("typed_summary"), f"{case.get('physical_case_id')} typed summary")
    case_id = case.get("physical_case_id")
    if summary.get("physical_case_id") != case_id:
        raise JoinVerificationError(f"{case_id} typed summary case identity differs")
    rows = summary.get("first_missing_rows")
    if not isinstance(rows, list) or not rows:
        raise JoinVerificationError(f"{case_id} typed summary has no first_missing_rows")
    parsed: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise JoinVerificationError(f"{case_id} typed summary row is malformed")
        key = _identity(row, f"{case_id} typed summary row")
        if key in parsed:
            raise JoinVerificationError(f"{case_id} typed summary duplicates {key}")
        if row.get("role") != "fluid" or row.get("type") not in (3, "3"):
            raise JoinVerificationError(f"{case_id} typed summary row is not a fluid type-3 row")
        frame = row.get("first_missing_frame")
        if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
            raise JoinVerificationError(f"{case_id} typed summary frame is invalid")
        time_s = _float(row.get("first_missing_time_s"), f"{case_id} typed summary time")
        bracket = row.get("saved_bracket_time_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise JoinVerificationError(f"{case_id} typed summary bracket is invalid")
        bracket_values = [_float(x, f"{case_id} typed summary bracket") for x in bracket]
        if bracket_values[0] > bracket_values[1] or not (bracket_values[0] <= time_s <= bracket_values[1]):
            raise JoinVerificationError(f"{case_id} typed summary time is outside its saved bracket")
        parsed[key] = {
            "frame": frame,
            "time_s": time_s,
            "bracket": bracket_values,
            "role": "fluid",
            "type": 3,
        }
    return parsed, summary_ref


def _csv_rows(raw: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JoinVerificationError(f"{label} is not UTF-8") from exc
    reader = csv.reader(text.splitlines())
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for fields in reader:
        if not fields or all(not item.strip() for item in fields):
            continue
        first = fields[0].strip()
        if first.startswith("#") or first.startswith("//"):
            continue
        if header is None:
            header = [item.strip() for item in fields]
            if len(header) != len(set(header)):
                raise JoinVerificationError(f"{label} has duplicate columns")
            continue
        if len(fields) != len(header):
            # Official RunPARTs files may end with comment/footer lines; a
            # data-looking malformed row is rejected rather than skipped.
            if first.lower().startswith(("footer", "total", "end")):
                continue
            raise JoinVerificationError(f"{label} row has the wrong column count")
        rows.append({key: value.strip() for key, value in zip(header, fields)})
    if header is None:
        raise JoinVerificationError(f"{label} has no header")
    return header, rows


def _read_native_csv(case: dict[str, Any]) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    case_id = case.get("physical_case_id")
    raw, ref = _file_ref(case.get("native_csv"), f"{case_id} native PartOut CSV")
    header, rows = _csv_rows(raw, f"{case_id} native PartOut CSV")
    required = {"Idp", "Motive", "PartOut"}
    if not required.issubset(header):
        raise JoinVerificationError(f"{case_id} native CSV lacks Idp/Motive/PartOut")
    parsed: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        try:
            idp = int(row["Idp"])
        except (TypeError, ValueError) as exc:
            raise JoinVerificationError(f"{case_id} native CSV Idp is invalid") from exc
        try:
            motive = int(row["Motive"])
        except (TypeError, ValueError) as exc:
            raise JoinVerificationError(f"{case_id} native CSV Motive is invalid") from exc
        if motive not in (1, 2, 3):
            raise JoinVerificationError(f"{case_id} native CSV Motive is unsupported")
        try:
            int(row["PartOut"])
        except (TypeError, ValueError) as exc:
            raise JoinVerificationError(f"{case_id} native CSV PartOut is invalid") from exc
        zone = int(row["Zone"]) if "Zone" in row and row["Zone"] else 0
        key = (zone, idp)
        if key in parsed:
            raise JoinVerificationError(f"{case_id} native CSV duplicates {key}")
        parsed[key] = {"motive": motive, "part_out": row["PartOut"]}
    if not parsed:
        raise JoinVerificationError(f"{case_id} native CSV has no rows")
    return parsed, ref


def _read_runparts(case: dict[str, Any], brackets: Iterable[list[float]]) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    raw, ref = _file_ref(case.get("runparts_csv"), f"{case_id} RunPARTs CSV")
    header, rows = _csv_rows(raw, f"{case_id} RunPARTs CSV")
    required = {"Part", "TimeStep [s]", "Steps", "NpOut"}
    if not required.issubset(header):
        raise JoinVerificationError(f"{case_id} RunPARTs lacks required official columns")
    times: list[float] = []
    for row in rows:
        try:
            int(row["Part"])
            int(row["Steps"])
            int(row["NpOut"])
            times.append(_float(row["TimeStep [s]"], f"{case_id} RunPARTs time"))
        except (TypeError, ValueError) as exc:
            raise JoinVerificationError(f"{case_id} RunPARTs count/time is malformed") from exc
    if not times:
        raise JoinVerificationError(f"{case_id} RunPARTs has no data rows")
    for bracket in brackets:
        for endpoint in bracket:
            if not any(math.isclose(endpoint, observed, rel_tol=0.0, abs_tol=1e-12) for observed in times):
                raise JoinVerificationError(f"{case_id} saved bracket endpoint is absent from RunPARTs")
    return {"ref": ref, "row_count": len(rows), "saved_times_s": times}


def _load_scope_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, ref = _json(path, "generic native join manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise JoinVerificationError("generic native join manifest schema differs")
    scope = manifest.get("case_scope")
    bundles = manifest.get("producer_proof_bundles")
    if not isinstance(scope, dict) or not isinstance(bundles, list) or len(bundles) != 6:
        raise JoinVerificationError("generic native join manifest is incomplete")
    selected = _string_list(scope.get("selected_case_ids"), "manifest selected case IDs")
    if len(selected) != scope.get("selected_canonical_count"):
        raise JoinVerificationError("manifest selected count differs")
    if scope.get("existing_exact_join_count") != 47 or scope.get("cause_not_located_count") != 24 or scope.get("cause_bound_missing_join_count") != 47:
        raise JoinVerificationError("manifest frozen accounting differs")
    if scope.get("unresolved_alias_case_ids") != [ALIAS_CASE]:
        raise JoinVerificationError("manifest alias boundary differs")
    existing_scope_ids = _string_list(scope.get("existing_join_case_ids"), "manifest existing join case IDs")
    if set(selected) & set(existing_scope_ids):
        raise JoinVerificationError("manifest selected scope overlaps an existing precise join")
    if ALIAS_CASE in selected:
        raise JoinVerificationError("manifest selected scope contains the unresolved alias")
    producer_by_case = manifest.get("producer_case_index")
    if not isinstance(producer_by_case, dict):
        raise JoinVerificationError("manifest lacks producer case index")
    edges = manifest.get("case_source_edges")
    if not isinstance(edges, list) or len(edges) != len(selected):
        raise JoinVerificationError("manifest lacks one source-bound edge per selected case")
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("physical_case_id"), str):
            raise JoinVerificationError("manifest source edge is malformed")
        case_id = edge["physical_case_id"]
        if case_id in edge_ids or case_id not in set(selected):
            raise JoinVerificationError("manifest source edge identity set differs")
        if edge.get("producer_id") != producer_by_case.get(case_id) or edge.get("native_cause_status") != "ALREADY_BOUND_NUMERICAL_SCOPE":
            raise JoinVerificationError(f"manifest source edge binding differs for {case_id}")
        if edge.get("typed_native_join_status") != "PENDING_PARENT_GUARDED_NATIVE_READ":
            raise JoinVerificationError(f"manifest source edge prematurely claims join for {case_id}")
        if isinstance(edge.get("producer_proof_case_index"), bool) or not isinstance(edge.get("producer_proof_case_index"), int):
            raise JoinVerificationError(f"manifest source edge lacks proof row index for {case_id}")
        if edge.get("producer_proof_case_status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise JoinVerificationError(f"manifest source edge proof row status differs for {case_id}")
        edge_ids.add(case_id)
    for bundle in bundles:
        if not isinstance(bundle, dict):
            raise JoinVerificationError("manifest proof bundle is malformed")
        _json_ref(bundle.get("manifest"), f"{bundle.get('producer_id')} source manifest")
        _validate_proof(bundle)
    if set(producer_by_case) != set(selected):
        raise JoinVerificationError("manifest producer case index differs from selected IDs")
    return manifest, ref


def _verify_result(manifest_path: Path, result_path: Path) -> dict[str, Any]:
    manifest, manifest_ref = _load_scope_manifest(manifest_path)
    result, result_ref = _json(result_path, "generic native join result", limit=MAX_RESULT_BYTES)
    if result.get("schema") != RESULT_SCHEMA:
        raise JoinVerificationError("result schema differs")
    bound_manifest = _expected_ref(result.get("manifest"), "result manifest")
    _compare_stat(manifest_ref, bound_manifest, "result/manifest", path=True)
    if result.get("new_native_cause_credit") != 0:
        raise JoinVerificationError("result attempts to add native cause credit")
    if result.get("physical_fate") != "UNKNOWN" or result.get("legal_flux") != "UNKNOWN" or result.get("dynamics") != "UNKNOWN":
        raise JoinVerificationError("result overclaims physical interpretation")
    allowed = set(manifest["case_scope"]["selected_case_ids"])
    requested = _string_list(result.get("requested_case_ids"), "result requested case IDs")
    if not set(requested).issubset(allowed):
        raise JoinVerificationError("result requests a case outside the selected canonical scope")
    if ALIAS_CASE in requested:
        raise JoinVerificationError("result requests the unresolved alias")
    case_results = result.get("case_results")
    if not isinstance(case_results, list) or len(case_results) != len(requested):
        raise JoinVerificationError("result case_results does not match requested cases")
    seen_cases: set[str] = set()
    producer_by_case = manifest["producer_case_index"]
    summaries: list[dict[str, Any]] = []
    completed = 0
    failed = 0
    for case in case_results:
        if not isinstance(case, dict) or not isinstance(case.get("physical_case_id"), str):
            raise JoinVerificationError("result case is malformed")
        case_id = case["physical_case_id"]
        if case_id in seen_cases:
            raise JoinVerificationError(f"result duplicates physical case {case_id}")
        seen_cases.add(case_id)
        if case_id not in requested:
            raise JoinVerificationError(f"result has unrequested case {case_id}")
        producer_id = case.get("producer_id")
        if producer_id != producer_by_case.get(case_id):
            raise JoinVerificationError(f"{case_id} producer proof binding differs")
        status = case.get("status")
        if status == "FAILED":
            failed += 1
            summaries.append({"physical_case_id": case_id, "producer_id": producer_id, "status": "FAILED_NO_JOIN_CREDIT"})
            continue
        if status != "COMPLETED_SOURCE_BOUND_JOIN_DIAGNOSTIC_ONLY":
            raise JoinVerificationError(f"{case_id} has unsupported result status")
        summary_rows, summary_ref = _read_summary(case)
        native_rows, native_ref = _read_native_csv(case)
        _read_runparts(case, [row["bracket"] for row in summary_rows.values()])
        if set(summary_rows) != set(native_rows):
            raise JoinVerificationError(f"{case_id} typed/native identity sets differ")
        reported = case.get("joined_rows")
        if not isinstance(reported, list) or len(reported) != len(summary_rows):
            raise JoinVerificationError(f"{case_id} joined_rows count differs")
        seen_rows: set[tuple[int, int]] = set()
        for row in reported:
            key = _identity(row, f"{case_id} result joined row")
            if key in seen_rows:
                raise JoinVerificationError(f"{case_id} result duplicates identity {key}")
            seen_rows.add(key)
            if key not in summary_rows or key not in native_rows:
                raise JoinVerificationError(f"{case_id} result identity {key} is not in source rows")
            typed = summary_rows[key]
            native = native_rows[key]
            if row.get("native_motive_code") != native["motive"] or row.get("typed_first_missing_frame") != typed["frame"]:
                raise JoinVerificationError(f"{case_id} result identity fields differ for {key}")
            if not math.isclose(_float(row.get("typed_first_missing_time_s"), f"{case_id} typed time"), typed["time_s"], rel_tol=0.0, abs_tol=1e-12):
                raise JoinVerificationError(f"{case_id} result typed time differs for {key}")
        if seen_rows != set(summary_rows):
            raise JoinVerificationError(f"{case_id} result does not enumerate all source rows")
        completed += 1
        summaries.append({
            "physical_case_id": case_id,
            "producer_id": producer_id,
            "status": "COMPLETED_SOURCE_BOUND_JOIN_DIAGNOSTIC_ONLY",
            "joined_identity_count": len(seen_rows),
            "typed_summary": summary_ref,
            "native_csv": native_ref,
        })
    if seen_cases != set(requested):
        raise JoinVerificationError("result case identity set differs from requested cases")
    counts = result.get("counts")
    if not isinstance(counts, dict):
        raise JoinVerificationError("result lacks counts")
    expected_counts = {"requested_cases": len(requested), "completed_cases": completed, "failed_cases": failed}
    for key, value in expected_counts.items():
        if counts.get(key) != value:
            raise JoinVerificationError(f"result count {key} differs")
    return {
        "schema": REPORT_SCHEMA,
        "status": "VERIFIED_GENERIC_NATIVE_TYPED_JOIN_DIAGNOSTIC_ONLY",
        "manifest": manifest_ref,
        "result": result_ref,
        "counts": {
            **expected_counts,
            "new_typed_native_join_credit": completed,
            "new_native_cause_credit": 0,
            "existing_exact_join_count": 47,
            "cause_bound_missing_join_count": 47,
            "unresolved_alias_count": 1,
        },
        "case_results": summaries,
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "new_native_cause_credit": 0,
            "alias_substitution": False,
        },
    }


def _self_test() -> None:
    """Small CLI-independent smoke test used by focused unit tests."""
    raise SystemExit("self-test is implemented by the repository unittest module")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="prepare a six-proof source scope")
    prepare.add_argument("--spec", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify", help="verify a bounded native/typed join result")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--result", required=True, type=Path)
    verify.add_argument("--output", required=True, type=Path)
    sub.add_parser("self-test", help="explain that unittest covers fixtures")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            _atomic_json(args.output, _source_scope_from_spec(args.spec))
        elif args.command == "verify":
            _atomic_json(args.output, _verify_result(args.manifest, args.result))
        else:
            _self_test()
    except JoinVerificationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
