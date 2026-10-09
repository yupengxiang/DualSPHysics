#!/usr/bin/env python3
"""Verify the real generic-native-extract worker output shape.

The first join verifier used a private result schema.  The production worker
already has a stable interface: a bound ``ds02.request.v1`` request, a
``ds02.stage2.generic-native-extract.v1`` manifest, one batch report with
``COMPLETED_ALL_CASES`` or ``COMPLETED_WITH_CASE_FAILURES``, and one case
report per successful case.  This additive verifier consumes that interface
directly.

The verifier also accepts a small multi-proof scope manifest.  Its accounting
is read from that scope at runtime; no launch-era count such as 47 is baked
into this implementation.  A completed case adds one typed/native physical
case join only.  It never adds native-cause credit and never infers physical
fate, flux, dynamics, or QI/QN/QE.

The worker's typed JSONL remains stat-only here.  The verifier opens only the
small typed summary, the completed per-case report, PartOut CSV, RunPARTs CSV,
and proof/request/manifest JSON.  It never opens H5, JSONL, BI4, or OBI4.
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
from typing import Any


SCRIPT = Path(__file__).resolve()
MAX_SMALL = 10 * 1024 * 1024
MAX_REPORT = 8 * 1024 * 1024
MAX_CSV = 64 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}
REQUEST_SCHEMA = "ds02.request.v1"
WORKER_MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v1"
WORKER_REPORT_SCHEMA = "ds02.stage2.generic-native-extract-report.v1"
WORKER_CASE_SCHEMA = WORKER_REPORT_SCHEMA
SCOPE_SCHEMA = "ds02.stage2.generic-native-typed-native-join.v1-manifest"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
REPORT_SCHEMA = "ds02.stage2.generic-native-typed-native-join-v2-report"


class GenericJoinV2Error(ValueError):
    """Raised for a stale bound worker output or an unsafe claim."""


def _path(value: Any, label: str, *, allow_payload: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise GenericJoinV2Error(f"{label} has no path")
    path = Path(value).expanduser().absolute()
    if not path.is_file():
        raise GenericJoinV2Error(f"{label} is missing: {path}")
    if not allow_payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise GenericJoinV2Error(f"{label} is deferred payload: {path}")
    return path


def _stat(path: Path, label: str, *, allow_payload: bool = False) -> dict[str, Any]:
    path = _path(path, label, allow_payload=allow_payload)
    st = path.stat()
    return {
        "path": str(path),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _compare_stat(actual: dict[str, Any], expected: dict[str, Any], label: str, *, include_path: bool = True) -> None:
    fields = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    if not include_path:
        fields = fields[1:]
    for field in fields:
        if expected.get(field) is not None and actual.get(field) != expected.get(field):
            raise GenericJoinV2Error(f"{label} {field} differs")


def _capture(path: Path, label: str, *, limit: int, allow_payload: bool = False) -> tuple[bytes, dict[str, Any]]:
    path = _path(path, label, allow_payload=allow_payload)
    before = _stat(path, label, allow_payload=allow_payload)
    if before["bytes"] > limit:
        raise GenericJoinV2Error(f"{label} exceeds bounded read: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GenericJoinV2Error(f"{label} cannot be read: {path}") from exc
    after = _stat(path, label, allow_payload=allow_payload)
    _compare_stat(after, before, f"{label} changed during capture")
    if len(raw) != after["bytes"]:
        raise GenericJoinV2Error(f"{label} byte count changed during capture")
    return raw, {**after, "sha256": hashlib.sha256(raw).hexdigest(), "stable_capture": True}


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise GenericJoinV2Error(f"{label} is not a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise GenericJoinV2Error(f"{label} is not a SHA-256 digest") from exc
    return value.lower()


def _json(path: Path, label: str, *, limit: int = MAX_SMALL) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, ref = _capture(path, label, limit=limit)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenericJoinV2Error(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise GenericJoinV2Error(f"{label} must be an object")
    return value, ref


def _json_ref(value: Any, label: str, *, limit: int = MAX_SMALL) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise GenericJoinV2Error(f"{label} reference is malformed")
    document, actual = _json(_path(value["path"], label), label, limit=limit)
    _compare_stat(actual, value, label)
    expected = value.get("sha256")
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != _sha(expected, f"{label} SHA"):
        raise GenericJoinV2Error(f"{label} SHA differs")
    return document, actual


def _static_ref(value: Any, label: str, *, limit: int = MAX_SMALL) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise GenericJoinV2Error(f"{label} reference is malformed")
    raw, actual = _capture(_path(value["path"], label), label, limit=limit)
    del raw
    _compare_stat(actual, value, label)
    expected = value.get("sha256")
    if expected not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != _sha(expected, f"{label} SHA"):
        raise GenericJoinV2Error(f"{label} SHA differs")
    return actual


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or any(not isinstance(item, str) or not item for item in value):
        raise GenericJoinV2Error(f"{label} must be a nonempty string list")
    if len(value) != len(set(value)):
        raise GenericJoinV2Error(f"{label} contains duplicate identities")
    return list(value)


def _validate_proof_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, ref = _json_ref(value, label)
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GenericJoinV2Error(f"{label} is not a completed actual proof")
    rows = []
    for key in ("case_verifications", "case_results", "cases"):
        candidate = proof.get(key)
        if isinstance(candidate, list):
            rows.extend(item for item in candidate if isinstance(item, dict))
    ids = [row.get("physical_case_id") for row in rows]
    if len(ids) != len(set(ids)):
        raise GenericJoinV2Error(f"{label} contains duplicate physical cases")
    return proof, ref


def _load_scope(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    scope, scope_ref = _json(path, "native/typed join scope")
    if scope.get("schema") != SCOPE_SCHEMA:
        raise GenericJoinV2Error("native/typed join scope schema differs")
    case_scope = scope.get("case_scope")
    if not isinstance(case_scope, dict):
        raise GenericJoinV2Error("native/typed join scope lacks case_scope")
    selected = _string_list(case_scope.get("selected_case_ids"), "scope selected case IDs")
    existing = _string_list(case_scope.get("existing_join_case_ids"), "scope existing join case IDs")
    if case_scope.get("selected_canonical_count") != len(selected):
        raise GenericJoinV2Error("scope selected count differs")
    existing_count = case_scope.get("existing_exact_join_count")
    if isinstance(existing_count, bool) or not isinstance(existing_count, int) or existing_count != len(existing):
        raise GenericJoinV2Error("scope existing join count differs")
    if case_scope.get("unresolved_alias_case_ids") is None:
        raise GenericJoinV2Error("scope lacks unresolved alias boundary")
    aliases = _string_list(case_scope.get("unresolved_alias_case_ids"), "scope unresolved aliases")
    if set(selected) & set(existing) or set(selected) & set(aliases):
        raise GenericJoinV2Error("scope selected cases overlap existing join or alias")
    for key in ("original_case_count", "cause_not_located_count", "cause_bound_missing_join_count"):
        value = case_scope.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GenericJoinV2Error(f"scope {key} is not a nonnegative integer")
    producer_by_case = scope.get("producer_case_index")
    if not isinstance(producer_by_case, dict) or set(producer_by_case) != set(selected):
        raise GenericJoinV2Error("scope producer case index differs from selected IDs")
    bundles = scope.get("producer_proof_bundles")
    if not isinstance(bundles, list) or not bundles:
        raise GenericJoinV2Error("scope lacks producer proof bundles")
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            raise GenericJoinV2Error(f"scope proof bundle {index} is malformed")
        proof_ref = bundle.get("proof")
        _validate_proof_ref(proof_ref, f"scope producer proof {bundle.get('producer_id', index)}")
    actual_join_proofs = scope.get("actual_join_proofs")
    if actual_join_proofs is None:
        existing_ref = scope.get("existing_join_source")
        if isinstance(existing_ref, dict):
            existing_doc, _ = _json_ref(existing_ref, "scope existing join source")
            actual_join_proofs = []
            for item in existing_doc.get("actual_producer_proof_bundles", []):
                if isinstance(item, dict):
                    proof_ref = item.get("producer_proof")
                    if isinstance(proof_ref, dict):
                        actual_join_proofs.append(proof_ref)
    if not isinstance(actual_join_proofs, list) or not actual_join_proofs:
        raise GenericJoinV2Error("scope lacks actual_join_proofs, including historical single-case proofs")
    proof_paths: set[str] = set()
    for index, proof_ref in enumerate(actual_join_proofs):
        _, actual = _validate_proof_ref(proof_ref, f"scope actual_join_proofs[{index}]")
        if actual["path"] in proof_paths:
            raise GenericJoinV2Error("scope actual_join_proofs contains duplicate proof path")
        proof_paths.add(actual["path"])
    return {
        "document": scope,
        "ref": scope_ref,
        "selected": set(selected),
        "existing": set(existing),
        "aliases": set(aliases),
        "producer_by_case": producer_by_case,
        "actual_join_proof_count": len(actual_join_proofs),
        "case_scope": case_scope,
    }, scope_ref


def _load_worker_manifest(path: Path, scope: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifest, manifest_ref = _json(path, "generic worker manifest")
    if manifest.get("schema") != WORKER_MANIFEST_SCHEMA or manifest.get("family_id") != "F2":
        raise GenericJoinV2Error("generic worker manifest schema/family differs")
    case_ids = _string_list(manifest.get("physical_case_ids"), "generic worker case IDs")
    if not set(case_ids).issubset(scope["selected"]):
        raise GenericJoinV2Error("generic worker case set is outside the bound selected scope")
    if set(case_ids) & scope["existing"] or set(case_ids) & scope["aliases"]:
        raise GenericJoinV2Error("generic worker case set overlaps existing join or alias")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != len(case_ids):
        raise GenericJoinV2Error("generic worker manifest contracts do not cover its cases")
    by_case: dict[str, dict[str, Any]] = {}
    for entry in contracts:
        if not isinstance(entry, dict) or not isinstance(entry.get("physical_case_id"), str):
            raise GenericJoinV2Error("generic worker contract edge is malformed")
        case_id = entry["physical_case_id"]
        if case_id in by_case or case_id not in case_ids:
            raise GenericJoinV2Error("generic worker contract identity set differs")
        contract, contract_ref = _json_ref(entry, f"{case_id} generic worker contract")
        if contract.get("physical_case_id") != case_id or contract.get("family_id") != "F2":
            raise GenericJoinV2Error(f"{case_id} contract identity differs")
        by_case[case_id] = {"document": contract, "ref": contract_ref, "edge": entry}
    if set(by_case) != set(case_ids):
        raise GenericJoinV2Error("generic worker contracts do not exactly cover cases")
    terminal = manifest.get("terminal_proof")
    if isinstance(terminal, dict):
        _validate_proof_ref(terminal, "generic worker terminal proof")
    bundles = manifest.get("typed_proof_bundles")
    if not isinstance(bundles, list) or not bundles:
        raise GenericJoinV2Error("generic worker manifest lacks proof bundles")
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict) or not isinstance(bundle.get("proof"), dict):
            raise GenericJoinV2Error(f"generic worker proof bundle {index} is malformed")
        _validate_proof_ref(bundle["proof"], f"generic worker proof bundle {index}")
        full = set(bundle.get("full_case_ids", []))
        if not set(case_ids).issubset(full):
            raise GenericJoinV2Error("generic worker cases are outside the complete proof edge")
    claim = manifest.get("claim_boundary")
    if not isinstance(claim, dict) or claim.get("physical_fate") != "UNKNOWN" or claim.get("legal_flux") != "UNKNOWN" or claim.get("dynamics") != "UNKNOWN":
        raise GenericJoinV2Error("generic worker manifest overclaims physical interpretation")
    return manifest, manifest_ref, by_case


def _load_request(path: Path, manifest_path: Path, manifest_ref: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    request, request_ref = _json(path, "generic worker request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != manifest.get("family_id"):
        raise GenericJoinV2Error("generic worker request schema/family differs")
    if request.get("physical_case_ids") != manifest.get("physical_case_ids"):
        raise GenericJoinV2Error("generic worker request case IDs differ")
    contract = request.get("manifest_contract")
    if not isinstance(contract, dict) or Path(contract.get("path", "")).expanduser().absolute() != manifest_path.absolute():
        raise GenericJoinV2Error("generic worker request does not bind the supplied manifest")
    if contract.get("sha256") != manifest_ref["sha256"]:
        raise GenericJoinV2Error("generic worker request manifest SHA differs")
    command = request.get("command")
    if not isinstance(command, list) or "audit" not in command or "--manifest" not in command:
        raise GenericJoinV2Error("generic worker request command is not an audit command")
    manifest_argument = command[command.index("--manifest") + 1] if command.index("--manifest") + 1 < len(command) else None
    if Path(str(manifest_argument)).expanduser().absolute() != manifest_path.absolute():
        raise GenericJoinV2Error("generic worker command manifest differs")
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or not isinstance(input_sha, dict) or len(input_files) != len(set(input_files)):
        raise GenericJoinV2Error("generic worker static input closure is malformed")
    for value in input_files:
        if not isinstance(value, str) or Path(value).suffix.lower() in PAYLOAD_SUFFIXES:
            raise GenericJoinV2Error("payload entered generic worker static input closure")
        if value not in input_sha:
            raise GenericJoinV2Error(f"generic worker input SHA missing: {value}")
        _static_ref({"path": value, "sha256": input_sha[value]}, f"generic worker static input {value}", limit=64 * 1024 * 1024)
    deferred = request.get("deferred_input_files", [])
    if not isinstance(deferred, list) or any(not isinstance(value, str) for value in deferred):
        raise GenericJoinV2Error("generic worker deferred input closure is malformed")
    return request, request_ref


def _identity(value: Any, label: str) -> tuple[int, int]:
    if isinstance(value, dict):
        if "identity_key" in value:
            value = value["identity_key"]
        elif "zone" in value and "idp" in value:
            value = [value["zone"], value["idp"]]
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise GenericJoinV2Error(f"{label} is not an integer (Zone, Idp) identity")
    return int(value[0]), int(value[1])


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GenericJoinV2Error(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise GenericJoinV2Error(f"{label} is not finite")
    return result


def _read_summary(contract: dict[str, Any], case_id: str) -> dict[str, Any]:
    typed = contract.get("typed_deferred")
    if not isinstance(typed, dict) or not isinstance(typed.get("summary"), dict) or not isinstance(typed.get("records"), dict):
        raise GenericJoinV2Error(f"{case_id} contract lacks typed summary/records refs")
    summary, summary_ref = _json_ref(typed["summary"], f"{case_id} typed summary")
    if summary.get("physical_case_id") not in (None, case_id):
        raise GenericJoinV2Error(f"{case_id} typed summary identity differs")
    records_ref = typed["records"]
    if Path(str(records_ref.get("path", ""))).suffix.lower() != ".jsonl":
        raise GenericJoinV2Error(f"{case_id} typed records are not JSONL")
    records_path = _path(records_ref.get("path"), f"{case_id} typed records", allow_payload=True)
    records_stat = _stat(records_path, f"{case_id} typed records", allow_payload=True)
    _compare_stat(records_stat, records_ref, f"{case_id} typed records")
    if records_ref.get("sha256") not in (None, "PARENT_GUARD_COMPUTED"):
        # The producer proof may bind a known hash; do not recompute it here.
        _sha(records_ref["sha256"], f"{case_id} typed records expected SHA")
    return {"summary": summary_ref, "records_stat": records_stat, "records_contract": records_ref}


def _read_csv(path_ref: dict[str, Any], label: str) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    raw, actual = _capture(_path(path_ref.get("path"), label), label, limit=MAX_CSV)
    _compare_stat(actual, path_ref, label)
    expected_sha = path_ref.get("sha256")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != _sha(expected_sha, f"{label} SHA"):
        raise GenericJoinV2Error(f"{label} SHA differs")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenericJoinV2Error(f"{label} is not UTF-8") from exc
    reader = csv.DictReader(text.splitlines())
    fields = [field.strip() for field in (reader.fieldnames or [])]
    if not {"Idp", "Motive", "PartOut"}.issubset(fields):
        raise GenericJoinV2Error(f"{label} lacks Idp/Motive/PartOut columns")
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for line_no, row in enumerate(reader, 2):
        if not row or all(not str(value or "").strip() for value in row.values()):
            continue
        try:
            idp = int(str(row.get("Idp", "")).strip())
            motive = int(str(row.get("Motive", "")).strip())
            part_out = int(str(row.get("PartOut", "")).strip())
        except ValueError as exc:
            raise GenericJoinV2Error(f"{label} row {line_no} has invalid identity/count") from exc
        zone = int(str(row.get("Zone", "0")).strip() or "0")
        key = (zone, idp)
        if key in rows:
            raise GenericJoinV2Error(f"{label} duplicates identity {key}")
        rows[key] = {"motive_code": motive, "part_out": part_out}
    if not rows:
        raise GenericJoinV2Error(f"{label} has no rows")
    return rows, actual


def _read_runparts(evidence: dict[str, Any], brackets: list[list[float]], case_id: str) -> dict[str, Any]:
    pre = evidence.get("pre_stat") if isinstance(evidence, dict) else None
    post = evidence.get("post_stat") if isinstance(evidence, dict) else None
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise GenericJoinV2Error(f"{case_id} RunPARTs evidence lacks pre/post stat")
    _compare_stat(post, pre, f"{case_id} RunPARTs pre/post")
    raw, actual = _capture(_path(pre.get("path"), f"{case_id} RunPARTs"), f"{case_id} RunPARTs", limit=MAX_CSV)
    _compare_stat(actual, pre, f"{case_id} RunPARTs")
    if evidence.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and actual["sha256"] != _sha(evidence["sha256"], f"{case_id} RunPARTs SHA"):
        raise GenericJoinV2Error(f"{case_id} RunPARTs SHA differs")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenericJoinV2Error(f"{case_id} RunPARTs is not UTF-8") from exc
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise GenericJoinV2Error(f"{case_id} RunPARTs is empty")
    delimiter = ";" if ";" in lines[0] else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    fields = [field.strip() for field in (reader.fieldnames or [])]
    required = {"Part", "TimeStep [s]", "Steps", "NpOut"}
    if not required.issubset(fields):
        raise GenericJoinV2Error(f"{case_id} RunPARTs lacks required official fields")
    times: list[float] = []
    for line_no, row in enumerate(reader, 2):
        if not row or all(not str(value or "").strip() for value in row.values()):
            continue
        try:
            int(str(row["Part"]).strip())
            int(str(row["Steps"]).strip())
            int(str(row["NpOut"]).strip())
            times.append(_number(row["TimeStep [s]"], f"{case_id} RunPARTs row {line_no} time"))
        except (KeyError, ValueError) as exc:
            raise GenericJoinV2Error(f"{case_id} RunPARTs row {line_no} is malformed") from exc
    if not times:
        raise GenericJoinV2Error(f"{case_id} RunPARTs has no data rows")
    for bracket in brackets:
        for endpoint in bracket:
            if not any(math.isclose(endpoint, observed, rel_tol=0.0, abs_tol=1e-12) for observed in times):
                raise GenericJoinV2Error(f"{case_id} saved bracket endpoint is absent from RunPARTs")
    reported_times = evidence.get("saved_times_s")
    if isinstance(reported_times, list) and [float(x) for x in reported_times] != times:
        raise GenericJoinV2Error(f"{case_id} RunPARTs saved times differ from worker report")
    return {"stat": actual, "rows": len(times), "saved_times_s": times}


def _verify_case(case_id: str, entry: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    case_report, case_ref = _json(_path(entry["output"], f"{case_id} generic case output"), f"{case_id} generic case output", limit=MAX_REPORT)
    if case_report.get("schema") != WORKER_CASE_SCHEMA or case_report.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
        raise GenericJoinV2Error(f"{case_id} generic case report schema/status differs")
    if case_report.get("physical_case_id") != case_id or case_report.get("family_id") != "F2":
        raise GenericJoinV2Error(f"{case_id} generic case report identity differs")
    counts = case_report.get("counts")
    rows = case_report.get("rows")
    if not isinstance(counts, dict) or not isinstance(rows, list) or not rows:
        raise GenericJoinV2Error(f"{case_id} generic case report lacks rows/counts")
    if counts.get("joined") != len(rows) or counts.get("typed_targets") != len(rows) or counts.get("native_rows") != len(rows):
        raise GenericJoinV2Error(f"{case_id} generic case report counts differ")
    keys: set[tuple[int, int]] = set()
    brackets: list[list[float]] = []
    row_summary: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = _identity(row, f"{case_id} generic case row")
        if key in keys:
            raise GenericJoinV2Error(f"{case_id} generic case report duplicates {key}")
        keys.add(key)
        motive_code = row.get("motive_code", row.get("native_motive_code"))
        if motive_code not in (1, 2, 3):
            raise GenericJoinV2Error(f"{case_id} generic case row motive is unsupported")
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise GenericJoinV2Error(f"{case_id} generic case row lacks saved bracket")
        bracket_values = [_number(x, f"{case_id} bracket") for x in bracket]
        if bracket_values[0] > bracket_values[1]:
            raise GenericJoinV2Error(f"{case_id} generic case bracket is reversed")
        first_time = _number(row.get("first_missing_time_s"), f"{case_id} first missing time")
        if not bracket_values[0] <= first_time <= bracket_values[1]:
            raise GenericJoinV2Error(f"{case_id} first missing time is outside saved bracket")
        brackets.append(bracket_values)
        row_summary[key] = {**row, "motive_code": motive_code}
    typed_evidence = case_report.get("typed")
    typed_data = _read_summary(contract, case_id)
    if not isinstance(typed_evidence, dict):
        raise GenericJoinV2Error(f"{case_id} generic case report lacks typed evidence")
    records_stat = typed_data["records_stat"]
    for edge in (typed_evidence.get("pre_stat"), typed_evidence.get("post_stat")):
        if not isinstance(edge, dict):
            raise GenericJoinV2Error(f"{case_id} typed evidence lacks pre/post stat")
        _compare_stat(edge, records_stat, f"{case_id} typed report/contract stat")
    if typed_evidence.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and typed_data["records_contract"].get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and typed_evidence["sha256"] != typed_data["records_contract"]["sha256"]:
        raise GenericJoinV2Error(f"{case_id} typed JSONL known SHA differs")
    native = case_report.get("native")
    if not isinstance(native, dict) or not isinstance(native.get("partout_csv"), dict) or not isinstance(native.get("runparts"), dict):
        raise GenericJoinV2Error(f"{case_id} generic case report lacks native CSV/RunPARTs evidence")
    partout = native["partout_csv"]
    pre = partout.get("pre_stat")
    post = partout.get("post_stat")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise GenericJoinV2Error(f"{case_id} PartOut CSV evidence lacks pre/post stat")
    _compare_stat(post, pre, f"{case_id} PartOut CSV pre/post")
    native_rows, native_stat = _read_csv(pre, f"{case_id} PartOut CSV")
    if partout.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and native_stat["sha256"] != _sha(partout["sha256"], f"{case_id} PartOut CSV SHA"):
        raise GenericJoinV2Error(f"{case_id} PartOut CSV report SHA differs")
    if set(native_rows) != keys:
        raise GenericJoinV2Error(f"{case_id} PartOut/native identity set differs")
    for key, value in native_rows.items():
        if value["motive_code"] != row_summary[key].get("motive_code") or value["part_out"] != row_summary[key].get("part_out"):
            raise GenericJoinV2Error(f"{case_id} PartOut row differs for {key}")
    runparts = _read_runparts(native["runparts"], brackets, case_id)
    return {
        "physical_case_id": case_id,
        "status": "COMPLETED",
        "joined_identity_count": len(keys),
        "case_output": case_ref,
        "typed_summary": typed_data["summary"],
        "typed_records_stat_only": records_stat,
        "native_csv": native_stat,
        "runparts": runparts,
    }


def verify(scope_path: Path, manifest_path: Path, request_path: Path, report_path: Path) -> dict[str, Any]:
    scope, scope_ref = _load_scope(scope_path)
    manifest, manifest_ref, contracts = _load_worker_manifest(manifest_path, scope)
    request, request_ref = _load_request(request_path, manifest_path, manifest_ref, manifest)
    report, report_ref = _json(report_path, "generic worker batch report", limit=MAX_REPORT)
    if report.get("schema") != WORKER_REPORT_SCHEMA or report.get("family_id") != manifest.get("family_id"):
        raise GenericJoinV2Error("generic worker batch report schema/family differs")
    if report.get("status") not in {"COMPLETED_ALL_CASES", "COMPLETED_WITH_CASE_FAILURES"}:
        raise GenericJoinV2Error("generic worker batch report status differs")
    for field in ("physical_fate", "legal_flux", "dynamics", "QI", "QN", "QE"):
        if report.get(field) != "UNKNOWN":
            raise GenericJoinV2Error(f"generic worker batch report overclaims {field}")
    results = report.get("case_results")
    counts = report.get("counts")
    if not isinstance(results, list) or not isinstance(counts, dict):
        raise GenericJoinV2Error("generic worker batch report lacks case results/counts")
    result_ids = []
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("physical_case_id"), str):
            raise GenericJoinV2Error("generic worker case result is malformed")
        result_ids.append(result["physical_case_id"])
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(manifest["physical_case_ids"]):
        raise GenericJoinV2Error("generic worker report case identity set differs from manifest")
    if counts.get("requested") != len(results):
        raise GenericJoinV2Error("generic worker requested count differs")
    completed = 0
    failed = 0
    verified_cases = []
    failures = []
    for result in results:
        case_id = result["physical_case_id"]
        status = result.get("status")
        if status == "FAILED":
            failed += 1
            failures.append({"physical_case_id": case_id, "status": "FAILED_NO_JOIN_CREDIT", "error_type": result.get("error_type"), "error_message": result.get("error_message")})
            continue
        if status != "COMPLETED" or not isinstance(result.get("output"), str):
            raise GenericJoinV2Error(f"{case_id} generic worker result status/output differs")
        verified = _verify_case(case_id, result, contracts[case_id]["document"])
        if result.get("joined") != verified["joined_identity_count"]:
            raise GenericJoinV2Error(f"{case_id} generic worker joined count differs")
        completed += 1
        verified_cases.append(verified)
    failed = len(results) - completed
    if counts.get("completed") != completed or counts.get("failed") != failed:
        raise GenericJoinV2Error("generic worker completed/failed counts differ")
    if report.get("claim_boundary", {}).get("native_cause") not in (None, "exact official PartOut Motive only", "old source-bound cause remains unchanged; future guarded Motive join may add per-ID diagnostic evidence"):
        raise GenericJoinV2Error("generic worker claim boundary does not preserve cause scope")
    scope_counts = scope["case_scope"]
    return {
        "schema": REPORT_SCHEMA,
        "status": "VERIFIED_GENERIC_WORKER_OUTPUT_WITH_CASE_FAILURES" if failed else "VERIFIED_GENERIC_WORKER_OUTPUT_ALL_CASES",
        "scope": scope_ref,
        "worker_manifest": manifest_ref,
        "worker_request": request_ref,
        "worker_report": report_ref,
        "counts": {
            "worker_requested_cases": len(results),
            "worker_completed_cases": completed,
            "worker_failed_cases": failed,
            "new_typed_native_join_physical_cases": completed,
            "new_native_cause_credit": 0,
            "scope_existing_exact_join_count": scope_counts["existing_exact_join_count"],
            "scope_cause_not_located_count": scope_counts["cause_not_located_count"],
            "scope_cause_bound_missing_join_count": scope_counts["cause_bound_missing_join_count"],
            "scope_selected_canonical_count": scope_counts["selected_canonical_count"],
            "scope_actual_join_proof_count": scope["actual_join_proof_count"],
        },
        "completed_cases": verified_cases,
        "failed_cases": failures,
        "claim_boundary": {
            "new_native_cause_credit": 0,
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "alias_substitution": False,
            "dynamic_scope_counts_used": True,
        },
        "read_policy": {
            "h5_opened": False,
            "jsonl_content_opened": False,
            "bi4_opened": False,
            "obi4_opened": False,
            "small_summary_csv_runparts_opened": True,
        },
    }


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise GenericJoinV2Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_REPORT:
            raise GenericJoinV2Error("output exceeds bounded size")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--scope", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--request", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command != "verify":
            parser.error("only verify is available; production output is supplied by generic-native-extract")
        _atomic(args.output, verify(args.scope, args.manifest, args.request, args.report))
    except GenericJoinV2Error as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
