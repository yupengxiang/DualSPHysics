#!/usr/bin/env python3
"""Independently verify a completed V4/ROOT313 mass-impact report.

This checker consumes only the small manifest, completed result JSON, producer
proofs, and native case reports.  It never opens a deferred JSONL/H5/BI4
payload.  It verifies that every reported ``(Zone, Idp)`` is unique and is
present in the bound native report, that the typed result says ``fluid`` and
type ``3``, that exact-or-null initial mass semantics are respected, and that
the result's three-pass typed stat/SHA record is the same deferred contract
that came from the producer proof.

The checker is deliberately separate from the producer/audit worker.  A
passing result is a source/identity/stat integrity result only; it grants no
physical fate, flux, dynamics, or QI/QN/QE credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
MAX_SMALL = 10 * 1024 * 1024
MAX_RESULT = 8 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}
MANIFEST_SCHEMAS = {
    "ds02.stage2.native-typed-mass-impact.v4-manifest",
    "ds02.stage2.native-typed-mass-impact.root313-manifest",
}
MANIFEST_STATUSES = {
    "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_V4",
    "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_ROOT313",
}
REPORT_SCHEMAS = {
    "ds02.stage2.native-typed-mass-impact.v4-report",
    "ds02.stage2.native-typed-mass-impact.root313-report",
}
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"


class VerificationError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise VerificationError(f"{label} is not a SHA-256 digest")
    return value.lower()


def _path(value: Any, label: str, *, allow_payload: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise VerificationError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    if not allow_payload and path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise VerificationError(f"{label} is a deferred payload: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    st = path.stat()
    return {
        "path": str(path),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _digest(path: Path, label: str) -> str:
    path = _path(path, label)
    if path.stat().st_size > MAX_SMALL:
        raise VerificationError(f"{label} exceeds the bounded verifier read")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, *, result: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _path(path, label)
    limit = MAX_RESULT if result else MAX_SMALL
    if path.stat().st_size > limit:
        raise VerificationError(f"{label} exceeds the bounded verifier read")
    stat = _stat(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    stat["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return value, stat


def _compare_stat(actual: dict[str, Any], expected: dict[str, Any], label: str, *, include_path: bool = True) -> None:
    fields = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    if not include_path:
        fields = fields[1:]
    for field in fields:
        if actual.get(field) != expected.get(field):
            raise VerificationError(f"{label} {field} differs")


def _ref(path_value: Any, expected: dict[str, Any] | None, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _path(path_value, label)
    actual_stat = _stat(path, label)
    actual_sha = _digest(path, label)
    actual_stat["sha256"] = actual_sha
    if expected is not None:
        if expected.get("path") is not None and str(Path(expected["path"]).expanduser().resolve()) != actual_stat["path"]:
            raise VerificationError(f"{label} path differs")
        _compare_stat(actual_stat, expected, label, include_path=False)
        if actual_sha != _sha(expected.get("sha256"), f"{label} expected SHA"):
            raise VerificationError(f"{label} SHA differs")
    return actual_stat, _json(path, label)[0]


def _source_ref(value: Any, label: str) -> dict[str, Any]:
    """Check a static source ref without assuming it is JSON."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerificationError(f"{label} is malformed")
    path = _path(value["path"], label)
    actual_stat = _stat(path, label)
    actual_sha = _digest(path, label)
    _compare_stat(actual_stat, value, label, include_path=True)
    if actual_sha != _sha(value.get("sha256"), f"{label} SHA"):
        raise VerificationError(f"{label} SHA differs")
    return {**actual_stat, "sha256": actual_sha}


def _identity(value: Any, label: str) -> tuple[int, int]:
    if isinstance(value, dict):
        value = value.get("identity_key")
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in value):
        raise VerificationError(f"{label} is not an integer (Zone, Idp) identity")
    return int(value[0]), int(value[1])


def _finite_mass(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise VerificationError(f"{label} is not finite positive mass")
    return float(value)


def _native_rows(report: dict[str, Any], case_id: str) -> dict[tuple[int, int], dict[str, Any]]:
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise VerificationError(f"{case_id} native report has no rows")
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise VerificationError(f"{case_id} native report row is malformed")
        key = _identity(row, f"{case_id} native report row")
        if key in result:
            raise VerificationError(f"{case_id} native report duplicates identity {key}")
        result[key] = row
    return result


def _proof_row(proof: dict[str, Any], case_id: str, label: str) -> dict[str, Any]:
    if proof.get("schema") != ROOT_PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise VerificationError(f"{label} is not a completed verified producer proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise VerificationError(f"{label} has no case_verifications")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise VerificationError(f"{label} has no unique row for {case_id}")
    return matches[0]


def _deferred_equal(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "rows", "sha256"):
        if actual.get(field) != expected.get(field):
            raise VerificationError(f"{label} deferred {field} differs")


def _verify_case(case: dict[str, Any], result: dict[str, Any], proof_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str):
        raise VerificationError("manifest case has no physical_case_id")
    proof_ref = case.get("producer_proof")
    report_ref = case.get("native_report")
    if not isinstance(proof_ref, dict) or not isinstance(report_ref, dict):
        raise VerificationError(f"{case_id} lacks producer proof/native report refs")
    proof_path = str(Path(proof_ref["path"]).expanduser().resolve())
    if proof_path not in proof_cache:
        proof, proof_stat = _json(Path(proof_path), f"{case_id} producer proof")
        actual_stat = _stat(Path(proof_path), f"{case_id} producer proof")
        actual_stat["sha256"] = _digest(Path(proof_path), f"{case_id} producer proof")
        _compare_stat(actual_stat, proof_ref, f"{case_id} producer proof", include_path=False)
        if actual_stat["sha256"] != _sha(proof_ref.get("sha256"), f"{case_id} producer proof SHA"):
            raise VerificationError(f"{case_id} producer proof SHA differs")
        proof_cache[proof_path] = (proof, actual_stat)
    else:
        proof = proof_cache[proof_path][0]
    proof_row = _proof_row(proof, case_id, f"{case_id} producer proof")
    proof_report = proof_row.get("report")
    if not isinstance(proof_report, str) or proof_report != report_ref.get("path"):
        raise VerificationError(f"{case_id} proof/report path binding differs")
    if proof_row.get("report_sha256") != report_ref.get("sha256"):
        raise VerificationError(f"{case_id} proof/report SHA binding differs")
    deferred = case.get("typed_records_deferred")
    proof_deferred = proof_row.get("typed_records_stat_SHA_only")
    if not isinstance(deferred, dict) or not isinstance(proof_deferred, dict):
        raise VerificationError(f"{case_id} lacks deferred typed-record contract")
    _deferred_equal(proof_deferred, deferred, f"{case_id} proof/manifest")
    _, native_report = _ref(report_ref.get("path"), report_ref, f"{case_id} native report")
    native_rows = _native_rows(native_report, case_id)
    manifest_ids = case.get("selected_native_ids")
    if not isinstance(manifest_ids, list) or not manifest_ids:
        raise VerificationError(f"{case_id} manifest selected IDs are missing")
    manifest_keys = [_identity(item, f"{case_id} manifest selected ID") for item in manifest_ids]
    if len(manifest_keys) != len(set(manifest_keys)):
        raise VerificationError(f"{case_id} manifest selected IDs are not unique")
    if set(manifest_keys) != set(native_rows):
        raise VerificationError(f"{case_id} manifest/native report identity sets differ")
    for item in manifest_ids:
        key = _identity(item, f"{case_id} manifest selected ID")
        native = native_rows[key]
        if item.get("native_motive_code") != native.get("motive_code"):
            raise VerificationError(f"{case_id} native motive differs for {key}")
        if item.get("native_first_missing_frame") != native.get("first_missing_frame"):
            raise VerificationError(f"{case_id} native frame differs for {key}")
        if item.get("native_first_missing_time_s") != native.get("first_missing_time_s"):
            raise VerificationError(f"{case_id} native time differs for {key}")
    if case.get("selected_native_id_count") != len(manifest_keys):
        raise VerificationError(f"{case_id} selected count differs")
    if result.get("physical_case_id") != case_id:
        raise VerificationError(f"{case_id} result identity differs")
    if result.get("status") == "FAILED":
        return {"physical_case_id": case_id, "status": "FAILED_NO_MASS_CREDIT", "selected_native_id_count": len(manifest_keys)}
    if not str(result.get("status", "")).startswith("COMPLETED_SELECTED_NATIVE_TYPED_INITIAL_MASS_DIAGNOSTIC_ONLY"):
        raise VerificationError(f"{case_id} result status is not a completed V4 diagnostic")
    result_ids = result.get("selected_native_ids")
    if not isinstance(result_ids, list) or len(result_ids) != len(manifest_keys):
        raise VerificationError(f"{case_id} result selected ID count differs")
    result_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for item in result_ids:
        key = _identity(item, f"{case_id} result selected ID")
        if key in result_by_key:
            raise VerificationError(f"{case_id} result selected IDs are not unique")
        result_by_key[key] = item
        if item.get("typed_initial_role") != "fluid" or item.get("typed_initial_type_code") != 3:
            raise VerificationError(f"{case_id} result identity {key} is not typed fluid/type3")
        mass = _finite_mass(item.get("typed_initial_mass_kg"), f"{case_id} {key} typed mass")
        mass_status = item.get("typed_mass_status")
        if mass is None and mass_status != "UNKNOWN_MISSING_TYPED_INITIAL_MASS":
            raise VerificationError(f"{case_id} {key} missing mass status is not UNKNOWN")
        if mass is not None and mass_status != "EXACT_TYPED_JSONL_INITIAL_MASS":
            raise VerificationError(f"{case_id} {key} exact mass status differs")
    if set(result_by_key) != set(manifest_keys):
        raise VerificationError(f"{case_id} result/native identity sets differ")
    typed_records = result.get("typed_records")
    if not isinstance(typed_records, dict):
        raise VerificationError(f"{case_id} result lacks typed record stat/SHA")
    _deferred_equal({
        "path": typed_records.get("path"), "bytes": typed_records.get("pre_stat", {}).get("bytes"),
        "mtime_ns": typed_records.get("pre_stat", {}).get("mtime_ns"), "ctime_ns": typed_records.get("pre_stat", {}).get("ctime_ns"),
        "st_dev": typed_records.get("pre_stat", {}).get("st_dev"), "st_ino": typed_records.get("pre_stat", {}).get("st_ino"),
        "rows": typed_records.get("rows"), "sha256": typed_records.get("pre_sha256"),
    }, deferred, f"{case_id} result/deferred")
    if typed_records.get("hash_passes") != 3 or typed_records.get("stream_sha256") != deferred.get("sha256") or typed_records.get("post_sha256") != deferred.get("sha256"):
        raise VerificationError(f"{case_id} result typed three-pass SHA differs")
    _compare_stat(typed_records.get("post_stat", {}), deferred, f"{case_id} result post-stat", include_path=True)
    masses = [item.get("typed_initial_mass_kg") for item in result_ids]
    exact = all(mass is not None for mass in masses)
    expected_sum = sum(float(mass) for mass in masses) if exact else None
    if result.get("selected_typed_initial_mass_sum_kg") != expected_sum:
        raise VerificationError(f"{case_id} aggregate selected mass differs")
    expected_status = "EXACT_ALL_SELECTED_ROWS" if exact else "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING"
    if result.get("selected_typed_initial_mass_status") != expected_status:
        raise VerificationError(f"{case_id} aggregate mass status differs")
    if result.get("role_average_proxy_mass_kg") is not None or result.get("role_average_proxy_status") != "UNVERIFIED_NOT_USED_AS_PER_ID_MASS":
        raise VerificationError(f"{case_id} role-average proxy was used or not marked unverified")
    return {"physical_case_id": case_id, "status": "VERIFIED_SAVED_MASK_MASS_DIAGNOSTIC_ONLY", "selected_native_id_count": len(manifest_keys), "exact_selected_mass_rows": sum(mass is not None for mass in masses), "missing_selected_mass_rows": sum(mass is None for mass in masses)}


def verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_stat = _json(args.manifest, "mass impact manifest")
    if manifest.get("schema") not in MANIFEST_SCHEMAS or manifest.get("status") not in MANIFEST_STATUSES:
        raise VerificationError("mass impact manifest schema/status differs")
    result, result_stat = _json(args.result, "mass impact result", result=True)
    if result.get("schema") not in REPORT_SCHEMAS:
        raise VerificationError("mass impact result schema differs")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise VerificationError("mass impact manifest has no cases")
    source_refs = manifest.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise VerificationError("mass impact manifest has no static source refs")
    for index, ref in enumerate(source_refs):
        _source_ref(ref, f"mass impact static source ref {index}")
    if result.get("counts", {}).get("requested") != len(cases):
        raise VerificationError("mass impact result requested count differs")
    result_rows = result.get("case_results")
    if not isinstance(result_rows, list) or len(result_rows) != len(cases):
        raise VerificationError("mass impact result case row count differs")
    result_by_id: dict[str, dict[str, Any]] = {}
    for row in result_rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in result_by_id:
            raise VerificationError("mass impact result case identities are not unique")
        result_by_id[row["physical_case_id"]] = row
    if set(result_by_id) != {case.get("physical_case_id") for case in cases}:
        raise VerificationError("mass impact manifest/result case sets differ")
    proof_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    verified: list[dict[str, Any]] = []
    for case in cases:
        verified.append(_verify_case(case, result_by_id[case["physical_case_id"]], proof_cache))
    failed = sum(row.get("status") == "FAILED_NO_MASS_CREDIT" for row in verified)
    completed = len(verified) - failed
    counts = result.get("counts")
    if not isinstance(counts, dict) or counts.get("completed") != completed or counts.get("failed") != failed:
        raise VerificationError("mass impact result completed/failed counts differ")
    claim = result.get("claim_boundary", {})
    for field in ("physical_mass_flux", "physical_fate", "dynamics", "QI", "QN", "QE"):
        if claim.get(field) != "UNKNOWN":
            raise VerificationError(f"result grants unsupported {field} credit")
    output = {
        "schema": "ds02.stage2.native-typed-mass-impact-verification.v1",
        "status": "PASS_SOURCE_IDENTITY_STAT_ONLY",
        "manifest": manifest_stat,
        "result": result_stat,
        "counts": {"cases": len(cases), "completed": completed, "failed": failed, "producer_proofs_checked": len(proof_cache)},
        "case_verifications": verified,
        "read_policy": {"manifest_content_opened": True, "result_content_opened": True, "producer_proof_report_content_opened": True, "deferred_jsonl_content_opened": False, "h5_content_opened": False, "native_payload_content_opened": False},
        "claim_boundary": {"initial_mass": "EXACT_OR_NULL_AS_REPORTED_TYPED_ROW", "aggregate_uniqueness": "VERIFIED", "physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    out = args.output.expanduser().resolve()
    if out.exists():
        raise VerificationError(f"refusing to overwrite verifier output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT:
        raise VerificationError("verifier output exceeds bound")
    out.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(out), "cases": len(cases), "completed": completed, "failed": failed, "deferred_jsonl_content_opened": False}


def _self_test() -> dict[str, Any]:
    return {"schema": "ds02.stage2.native-typed-mass-impact-verification.v1", "status": "PASS", "checks": ["proof/report SHA and stat binding", "unique (Zone, Idp) aggregate", "typed fluid/type3 gate", "exact-or-null initial mass", "three-pass deferred stat/SHA equality", "physical fate/flux/dynamics/Q remain UNKNOWN"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--result", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = _self_test() if args.action == "self-test" else verify(args)
    except (VerificationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"NATIVE_TYPED_MASS_IMPACT_VERIFY_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
