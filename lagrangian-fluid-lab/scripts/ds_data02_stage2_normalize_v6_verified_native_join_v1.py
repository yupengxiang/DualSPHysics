#!/usr/bin/env python3
"""Normalize V6-verified case outputs into root-proof case rows.

The V6 verifier owns the scientific per-case checks.  Its output rows use
consumer names (``case_output``, ``native_csv``, and
``typed_records_stat_only``), while a root actual proof requires the
producer-proof names (``report``/SHA, typed references, native evidence,
saved-frame counts, and exact identity rows).  This adapter performs that
mechanical, source-bound mapping only after V6 has completed a case check.

It reads bounded JSON metadata and case reports produced by the V6 worker.
It does not open typed JSONL, H5, BI4, OBI4, PartOut CSV, or RunPARTs
payloads.  It never assigns physical-cause or qualification credit; the
root terminal wrapper remains responsible for fee/resource closure and the
rolling scope admission.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ds_data02_stage2_build_native_overlay_adapter_v5 as v5
import ds_data02_stage2_verify_generic_native_join_v6 as v6


SCHEMA = "ds02.stage2.root-actual-verification.v1"
NORMALIZER_SCHEMA = "ds02.stage2.v6-verified-native-join-row-normalizer.v1"
MAX_JSON = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = frozenset(v6.PAYLOAD_SUFFIXES)


class NormalizationError(ValueError):
    pass


def _fail(message: str) -> None:
    raise NormalizationError(message)


def _capture(path_value: Any, label: str, *, expected_sha: str | None = None) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(path_value, (str, Path)) or not str(path_value):
        _fail(f"{label} path is malformed")
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        _fail(f"{label} payload entered the metadata normalizer: {path}")
    if not path.is_file():
        _fail(f"{label} is missing: {path}")
    before = path.stat()
    if before.st_size > MAX_JSON:
        _fail(f"{label} exceeds the bounded JSON limit: {path}")
    raw = path.read_bytes()
    after = path.stat()
    stat_fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_dev", "st_ino")
    if any(getattr(before, field) != getattr(after, field) for field in stat_fields):
        _fail(f"{label} changed during capture: {path}")
    if len(raw) != after.st_size:
        _fail(f"{label} byte count changed during capture: {path}")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and digest != expected_sha:
        _fail(f"{label} SHA differs: {path}")
    return raw, {
        "path": str(path),
        "bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "st_dev": int(after.st_dev),
        "st_ino": int(after.st_ino),
        "sha256": digest,
        "stable_capture": True,
    }


def _json_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        _fail(f"{label} reference is malformed")
    expected = value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        _fail(f"{label} requires a concrete SHA-256")
    raw, actual = _capture(value["path"], label, expected_sha=expected)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"{label} is not valid bounded JSON") from exc
    if not isinstance(document, dict):
        _fail(f"{label} must be a JSON object")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if field in value and value[field] != actual[field]:
            _fail(f"{label} {field} differs from the captured source")
    return document, actual


def _copy_ref(value: Any, label: str, *, require_sha: bool = True) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        _fail(f"{label} reference is malformed")
    sha = value.get("sha256")
    if require_sha and (not isinstance(sha, str) or len(sha) != 64):
        _fail(f"{label} requires a concrete SHA-256")
    copied = dict(value)
    if require_sha:
        copied["sha256"] = str(sha)
    return copied


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _fail(f"{label} is not a finite number")
    return float(value)


def _identity(row: Mapping[str, Any], label: str) -> tuple[int, int]:
    key = row.get("identity_key")
    if not isinstance(key, list) or len(key) != 2 or any(isinstance(value, bool) or not isinstance(value, int) for value in key):
        _fail(f"{label} identity_key is malformed")
    return int(key[0]), int(key[1])


def _normalize_case(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str) or not case_id:
        _fail(f"V6 case row {index} lacks physical_case_id")
    if case.get("status") != "COMPLETED":
        _fail(f"V6 case {case_id} is not COMPLETED")

    output_value = case.get("case_output")
    output, output_ref = _json_ref(output_value, f"V6 case output {case_id}")
    if output.get("physical_case_id") != case_id:
        _fail(f"V6 case output identity differs: {case_id}")
    if output.get("status") != "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY":
        _fail(f"V6 case output status differs: {case_id}")
    rows = output.get("rows")
    counts = output.get("counts")
    if not isinstance(rows, list) or not rows or not isinstance(counts, Mapping):
        _fail(f"V6 case output lacks exact joined rows: {case_id}")
    if any(not isinstance(row, Mapping) for row in rows):
        _fail(f"V6 case output has malformed joined rows: {case_id}")
    identities = [_identity(row, f"{case_id} joined row") for row in rows]
    if len(identities) != len(set(identities)):
        _fail(f"V6 case output repeats an identity: {case_id}")
    for name in ("typed_targets", "native_rows", "joined"):
        if counts.get(name) != len(rows):
            _fail(f"V6 case output {name} count is not the exact row count: {case_id}")
    if case.get("joined_identity_count") != len(rows):
        _fail(f"V6 verifier identity count differs from case output rows: {case_id}")

    native = output.get("native")
    typed = output.get("typed")
    if not isinstance(native, Mapping) or not isinstance(typed, Mapping):
        _fail(f"V6 case output lacks typed/native evidence: {case_id}")
    native_csv = native.get("partout_csv")
    if not isinstance(native_csv, Mapping):
        _fail(f"V6 case output lacks PartOut CSV evidence: {case_id}")
    v6_native_ref = case.get("native_csv")
    if not isinstance(v6_native_ref, Mapping):
        _fail(f"V6 verifier row lacks native_csv reference: {case_id}")
    native_csv_stat = native_csv.get("post_stat")
    if not isinstance(native_csv_stat, Mapping):
        _fail(f"V6 case output lacks native CSV post stat: {case_id}")
    for field in ("path", "bytes"):
        if v6_native_ref.get(field) != native_csv_stat.get(field):
            _fail(f"V6 native CSV reference disagrees with case output: {case_id}/{field}")
    if v6_native_ref.get("sha256") != native_csv.get("sha256"):
        _fail(f"V6 native CSV reference disagrees with case output: {case_id}/sha256")
    native_csv_ref = {
        **dict(native_csv_stat),
        "sha256": native_csv.get("sha256"),
        "rows": native_csv.get("rows"),
        "single_pass": native_csv.get("single_pass"),
        "v6_verified": True,
    }
    if not isinstance(native_csv_ref.get("sha256"), str) or len(native_csv_ref["sha256"]) != 64:
        _fail(f"{case_id} native CSV evidence lacks a concrete SHA")

    typed_summary_ref = _copy_ref(case.get("typed_summary"), f"{case_id} typed summary")
    records_ref = _copy_ref(case.get("typed_records_stat_only"), f"{case_id} typed records", require_sha=False)
    typed_sha = typed.get("sha256")
    if not isinstance(typed_sha, str) or len(typed_sha) != 64:
        _fail(f"{case_id} case output does not expose typed records SHA")
    # V6 emits the records SHA in the checked case report, while its compact
    # consumer row intentionally stores stat-only metadata.  Add the producer
    # SHA here; do not hash or open the JSONL a second time.
    records_ref["sha256"] = typed_sha
    for edge in (typed.get("pre_stat"), typed.get("post_stat")):
        if not isinstance(edge, Mapping):
            _fail(f"{case_id} typed records lack pre/post stat")
        for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if records_ref.get(field) != edge.get(field):
                _fail(f"{case_id} typed records {field} differs from case output")
    if case.get("typed_records_stat_only", {}).get("rows") not in (None, typed.get("rows")):
        _fail(f"{case_id} typed records row count differs from case output")

    runparts = case.get("runparts")
    if not isinstance(runparts, Mapping):
        runparts = native.get("runparts")
    saved_times = runparts.get("saved_times_s") if isinstance(runparts, Mapping) else None
    if not isinstance(saved_times, list) or not saved_times:
        _fail(f"{case_id} native saved-time evidence is missing")
    categories: set[str] = set()
    exact_rows: list[dict[str, Any]] = []
    for row_index, source_row in enumerate(rows):
        row = dict(source_row)
        cause = row.get("native_exit_cause")
        if not isinstance(cause, str) or not cause:
            _fail(f"{case_id} joined row {row_index} lacks native cause")
        categories.add(cause)
        bracket = row.get("bracket_s")
        if not isinstance(bracket, list) or len(bracket) != 2:
            _fail(f"{case_id} joined row {row_index} lacks saved bracket")
        lo, hi = (_number(bracket[0], f"{case_id} bracket low"), _number(bracket[1], f"{case_id} bracket high"))
        if lo > hi:
            _fail(f"{case_id} joined row {row_index} has reversed saved bracket")
        first_time = _number(row.get("first_missing_time_s"), f"{case_id} first missing time")
        if not any(math.isclose(first_time, _number(value, f"{case_id} saved time"), rel_tol=0.0, abs_tol=1e-12) for value in saved_times):
            _fail(f"{case_id} joined row {row_index} first missing time is absent from V6 saved times")
        _identity(row, f"{case_id} joined row {row_index}")
        exact_rows.append(row)
    if not categories:
        _fail(f"{case_id} has no native cause categories")

    native_obi4 = case.get("native_obi4")
    if not isinstance(native_obi4, Mapping):
        _fail(f"{case_id} V6 row lacks OBI4 source closure")
    official_decoder = case.get("official_decoder")
    if not isinstance(official_decoder, Mapping):
        _fail(f"{case_id} V6 row lacks official decoder source closure")
    return {
        "physical_case_id": case_id,
        "family_id": output.get("family_id", case.get("family_id")),
        "status": "COMPLETED",
        "report": output_ref["path"],
        "report_sha256": output_ref["sha256"],
        "typed_summary": typed_summary_ref,
        "typed_records_stat_SHA_only": records_ref,
        "native_csv_evidence": native_csv_ref,
        "native_cause_categories": sorted(categories),
        "target_fluid_identity_count": len(exact_rows),
        "saved_frame_matches": len(exact_rows),
        "exact_join_rows": exact_rows,
        "native_OBI4_stat_SHA_only": copy.deepcopy(native_obi4),
        "official_decoder": copy.deepcopy(official_decoder),
        "independent_CSV_RunPARTs_identity_motive_brackets_arithmetic_verified": True,
        "new_original118_cause_bound_physical_case": False,
        "physical_fate_legal_flux_dynamics_Q": "UNKNOWN",
        "normalization_basis": "V6_VERIFIED_CASE_OUTPUT_EXACT_ROWS",
    }


def normalize_rows(v6_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    if v6_document.get("schema") != v6.OUTPUT_SCHEMA:
        _fail("input is not a V6 verification output")
    if not isinstance(v6_document.get("status"), str) or not v6_document["status"].startswith("VERIFIED_"):
        _fail("V6 output is not verified")
    failures = v6_document.get("failures")
    if isinstance(failures, list) and failures:
        _fail("V6 output contains failed cases; normalize successful cases separately")
    cases = v6_document.get("case_verifications")
    if not isinstance(cases, list) or not cases:
        _fail("V6 output lacks case_verifications")
    case_ids = [case.get("physical_case_id") for case in cases if isinstance(case, Mapping)]
    if len(case_ids) != len(cases) or any(not isinstance(case_id, str) or not case_id for case_id in case_ids) or len(case_ids) != len(set(case_ids)):
        _fail("V6 output case identities are not unique")
    counts = v6_document.get("counts")
    if not isinstance(counts, Mapping) or counts.get("worker_completed") != len(cases) or counts.get("worker_failed", 0) != 0:
        _fail("V6 output counts do not prove all normalized cases completed")
    return [_normalize_case(case, index) for index, case in enumerate(cases)]


def normalize(v6_result_path: Path, terminal_identity_path: Path, output_path: Path) -> dict[str, Any]:
    v6_document, v6_ref = _json_ref({"path": str(v6_result_path.expanduser().resolve()), "sha256": _sha_file(v6_result_path, "V6 verification output")}, "V6 verification output")
    terminal, terminal_ref = _json_ref({"path": str(terminal_identity_path.expanduser().resolve()), "sha256": _sha_file(terminal_identity_path, "root terminal identity")}, "root terminal identity")
    if v5._terminal_state(terminal) != "COMPLETED":
        _fail("root terminal identity is not completed")
    v5._require_completed_accounting(terminal)
    rows = normalize_rows(v6_document)
    if output_path.exists() or output_path.is_symlink():
        _fail(f"refusing to overwrite normalized proof: {output_path}")
    proof = copy.deepcopy(terminal)
    for key in (
        "actual_join_proof", "native_join_proof", "join_proof", "selected_case_ids",
        "case_verifications", "failed_cases", "failed_physical_cases",
        "actual_completed_physical_cases", "new_original118_cause_bound_physical_cases",
        "new_original118_typed_native_joins", "newly_bound_case_ids", "target_fluid_identity_count",
        "actual_typed_native_saved_frame_join_physical_cases",
    ):
        proof.pop(key, None)
    proof["schema"] = SCHEMA
    proof["case_verifications"] = rows
    proof["actual_completed_physical_cases"] = len(rows)
    proof["failed_physical_cases"] = 0
    proof["failed_cases"] = []
    if isinstance(proof.get("counts"), Mapping):
        proof["counts"] = {
            **dict(proof["counts"]),
            "cases_requested": len(rows),
            "completed": len(rows),
            "failed": 0,
        }
    proof["new_original118_cause_bound_physical_cases"] = 0
    proof["new_original118_typed_native_joins"] = len(rows)
    proof["newly_bound_case_ids"] = []
    proof["target_fluid_identity_count"] = sum(row["target_fluid_identity_count"] for row in rows)
    proof["actual_typed_native_saved_frame_join_physical_cases"] = len(rows)
    proof["v6_verification_output"] = v6_ref
    proof["v6_terminal_identity_input"] = terminal_ref
    proof["normalization_schema"] = NORMALIZER_SCHEMA
    proof["claim_boundary"] = {
        "native_id_join": "VERIFIED_PER_V6_CASE_OUTPUT_EXACT_ROWS",
        "new_native_cause_credit": "DEFERRED_TO_ROOT_ROLLING_SCOPE",
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }
    encoded = (json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_JSON:
        _fail("normalized root proof exceeds the bounded metadata size")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    output_ref = _ref_after_write(output_path, "normalized root proof")
    return {"schema": NORMALIZER_SCHEMA, "status": "NORMALIZED_V6_VERIFIED_CASE_ROWS", "output": output_ref, "case_ids": [row["physical_case_id"] for row in rows], "new_native_cause_credit": 0, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _sha_file(path: Path, label: str) -> str:
    path = path.expanduser().resolve()
    if not path.is_file():
        _fail(f"{label} is missing: {path}")
    if path.stat().st_size > MAX_JSON:
        _fail(f"{label} exceeds bounded size: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref_after_write(path: Path, label: str) -> dict[str, Any]:
    _, ref = _capture(path, label)
    return ref


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v6-result", type=Path, required=True)
    parser.add_argument("--terminal-identity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = normalize(args.v6_result, args.terminal_identity, args.output)
    except (NormalizationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"V6_NATIVE_JOIN_NORMALIZER_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
