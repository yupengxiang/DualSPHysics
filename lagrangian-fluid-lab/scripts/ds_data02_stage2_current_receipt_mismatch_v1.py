#!/usr/bin/env python3
"""Reconcile one CURRENT336 receipt mismatch using JSON metadata only.

ROOT183 found one completed scan whose producer receipt was launched with a
historical ``CURRENT336.json`` alias.  This module records that fact without
rewriting either catalog, the scan receipt, or the ROOT183 report.  It reads
only explicitly declared JSON files and never opens a trajectory, BI4/OBI4,
VTK, or native payload.  A target row that is equal in the two catalogs is
reported as row-level agreement, while catalog-level identity differences
remain a source-closure mismatch and receive no scientific credit.

``build`` validates the known producer/report chain and writes a small,
immutable manifest plus sidecar.  ``audit`` revalidates a previously written
manifest and writes a new sidecar.  ``request`` emits an optional shared v8
CPU request when the caller supplies the runtime closure; it is intentionally
metadata-only and has no H5/raw/native inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.current-receipt-mismatch.v1"
MANIFEST_SCHEMA = "ds02.stage2.current-receipt-mismatch-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
DEFERRED = "PARENT_GUARD_COMPUTED"
TARGET_CASE_KEY = "F2/F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
TARGET_PHYSICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
BLOCKED_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".vtk", ".vtu"}


class MismatchError(ValueError):
    """Raised when the immutable JSON evidence does not match its binding."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        raise MismatchError(f"refusing non-JSON scientific payload: {path}")
    if not path.is_file():
        raise MismatchError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MismatchError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MismatchError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise MismatchError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise MismatchError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        raise MismatchError(f"{label} points at a blocked scientific payload: {path}")
    return path


def _stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise MismatchError(f"{label} is missing: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "st_dev": value.st_dev,
        "st_ino": value.st_ino,
    }


def _ref(path: Path, role: str, expected_sha: str | None = None) -> dict[str, Any]:
    path = _path(str(path), role)
    stat = _stat(path, role)
    actual = sha256_file(path)
    if expected_sha is not None and actual != expected_sha:
        raise MismatchError(f"{role} SHA differs: {path}")
    return {"role": role, **stat, "sha256": actual}


def _source_refs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise MismatchError("manifest source_refs are missing")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(refs):
        if not isinstance(item, dict):
            raise MismatchError(f"source_refs[{index}] is malformed")
        path = _path(item.get("path"), f"source_refs[{index}]")
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise MismatchError(f"source_refs[{index}] lacks role")
        if str(path) in seen:
            raise MismatchError(f"duplicate source reference: {path}")
        seen.add(str(path))
        expected = item.get("sha256")
        if not isinstance(expected, str) or not expected or expected == DEFERRED:
            raise MismatchError(f"source_refs[{index}] needs a concrete SHA")
        normalized.append(_ref(path, role, expected))
    return normalized


def _case_key(row: dict[str, Any]) -> str:
    value = row.get("case_key")
    if not isinstance(value, str) or not value:
        family = row.get("family_id")
        physical = row.get("physical_case_id")
        if isinstance(family, str) and isinstance(physical, str):
            return f"{family}/{physical}"
    return value if isinstance(value, str) else ""


def _case_map(current: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    rows = current.get("cases")
    if not isinstance(rows, list):
        raise MismatchError(f"{label}.cases is not a list")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MismatchError(f"{label}.cases[{index}] is not an object")
        key = _case_key(row)
        if not key:
            raise MismatchError(f"{label}.cases[{index}] has no case key")
        if key in result:
            raise MismatchError(f"{label} contains duplicate case key: {key}")
        result[key] = row
    return result


def _report_case(report: dict[str, Any], case_key: str) -> dict[str, Any]:
    rows = report.get("cases")
    if not isinstance(rows, list):
        raise MismatchError("ROOT183 report cases is not a list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("case_key") == case_key]
    if len(matches) != 1:
        raise MismatchError(f"ROOT183 report case count is {len(matches)} for {case_key}")
    return matches[0]


def _find_input_sha(receipt: dict[str, Any], path: Path) -> str | None:
    target = str(Path(path).expanduser().resolve())
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        mapping = receipt.get(key)
        if isinstance(mapping, dict):
            for name, value in mapping.items():
                if str(Path(name).expanduser().resolve()) == target and isinstance(value, str):
                    return value
    request = receipt.get("request")
    if isinstance(request, dict):
        mapping = request.get("input_sha256")
        if isinstance(mapping, dict):
            for name, value in mapping.items():
                if str(Path(name).expanduser().resolve()) == target and isinstance(value, str):
                    return value
    return None


def _target_ref(report_case: dict[str, Any], kind: str) -> tuple[Path, str]:
    binding = report_case.get("scan_binding")
    if not isinstance(binding, dict):
        raise MismatchError("report target lacks scan_binding")
    entry = binding.get(kind)
    if not isinstance(entry, dict):
        raise MismatchError(f"report target lacks scan_binding.{kind}")
    path = _path(entry.get("path"), f"scan_binding.{kind}.path")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not sha:
        raise MismatchError(f"scan_binding.{kind}.sha256 is missing")
    return path, sha


def _validate_manifest_sources(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise MismatchError("unexpected mismatch manifest schema")
    refs = _source_refs(manifest)
    return {str(Path(row["path"]).resolve()): row for row in refs}


def reconcile(manifest: dict[str, Any]) -> dict[str, Any]:
    refs = _validate_manifest_sources(manifest)
    by_role = {row["role"]: row for row in refs.values()}

    def source(role: str) -> tuple[Path, dict[str, Any]]:
        row = by_role.get(role)
        if row is None:
            raise MismatchError(f"manifest lacks source role {role}")
        return Path(row["path"]), row

    proof_path, proof_ref = source("root183_proof")
    report_path, report_ref = source("root183_report")
    root_receipt_path, root_receipt_ref = source("root183_execution_receipt")
    exact_path, exact_ref = source("current_exact")
    alias_path, alias_ref = source("current_alias")
    scan_path, scan_ref = source("target_scientific_scan")
    scan_receipt_path, scan_receipt_ref = source("target_scan_receipt")
    detail_path, detail_ref = source("target_detail_card")

    proof = read_json(proof_path, "ROOT183 proof")
    report = read_json(report_path, "ROOT183 report")
    root_receipt = read_json(root_receipt_path, "ROOT183 execution receipt")
    exact = read_json(exact_path, "exact CURRENT336")
    alias = read_json(alias_path, "alias CURRENT336")
    scan = read_json(scan_path, "target scientific scan")
    scan_receipt = read_json(scan_receipt_path, "target scan receipt")
    detail = read_json(detail_path, "target detail card")

    target = _report_case(report, TARGET_CASE_KEY)
    if target.get("physical_case_id") != TARGET_PHYSICAL_ID or target.get("family_id") != "F2":
        raise MismatchError("ROOT183 target identity is not the expected F2 case")
    if target.get("receipt", {}).get("status") != "completed":
        raise MismatchError("target producer receipt is not completed")
    current_binding = target.get("receipt", {}).get("current_binding", {})
    if current_binding.get("exact") is not False:
        raise MismatchError("target is no longer the expected mismatch row")
    observed = current_binding.get("observed")
    if not isinstance(observed, list) or len(observed) != 1:
        raise MismatchError("target mismatch observed binding is not singleton")
    observed_row = observed[0]
    if observed_row.get("path") != str(alias_path) or observed_row.get("sha256") != alias_ref["sha256"]:
        raise MismatchError("target report mismatch does not bind the declared alias")
    if current_binding.get("expected_sha256") != manifest["target"]["exact_current_sha256"]:
        raise MismatchError("target report expected CURRENT SHA differs")

    if proof.get("report") != str(report_path) or proof.get("report_sha256") != report_ref["sha256"]:
        raise MismatchError("ROOT183 proof/report binding differs")
    if TARGET_CASE_KEY not in proof.get("current_receipt_mismatch_case_keys", []):
        raise MismatchError("ROOT183 proof does not list the target mismatch")
    if root_receipt.get("status") != "completed" or root_receipt.get("returncode") != 0:
        raise MismatchError("ROOT183 metadata producer receipt is not completed")
    if root_receipt.get("output_root") != manifest["target"]["root183_output_root"]:
        raise MismatchError("ROOT183 output root differs")

    if scan.get("family_id") != "F2" or scan.get("physical_case_id") != TARGET_PHYSICAL_ID:
        raise MismatchError("target scan identity differs")
    scan_request = scan_receipt.get("request")
    if not isinstance(scan_request, dict):
        raise MismatchError("target scan receipt request is missing")
    if scan_receipt.get("status") != "completed" or scan_receipt.get("returncode") != 0:
        raise MismatchError("target scan producer receipt is not completed")
    if scan_request.get("attempt_id") != "scan-F2-S1-001":
        raise MismatchError("target scan attempt differs")
    if scan_request.get("case_id") != "STAGE2_F2_S1_SCIENCE":
        raise MismatchError("target scan case differs")
    input_alias_sha = _find_input_sha(scan_receipt, alias_path)
    if input_alias_sha != alias_ref["sha256"]:
        raise MismatchError("producer receipt does not bind alias CURRENT SHA")
    input_exact_sha = _find_input_sha(scan_receipt, exact_path)
    if input_exact_sha is not None:
        raise MismatchError("historical producer receipt unexpectedly binds exact CURRENT")
    if detail.get("case_key") != TARGET_CASE_KEY or detail.get("physical_case_id") != TARGET_PHYSICAL_ID:
        raise MismatchError("detail card identity differs")
    if detail.get("scan_provenance", {}).get("path") != str(scan_path) or detail.get("scan_provenance", {}).get("observed_sha256") != scan_ref["sha256"]:
        raise MismatchError("detail card does not bind target scan")
    if detail.get("receipt_provenance", {}).get("path") != str(scan_receipt_path) or detail.get("receipt_provenance", {}).get("observed_sha256") != scan_receipt_ref["sha256"]:
        raise MismatchError("detail card does not bind target receipt")

    exact_map = _case_map(exact, "exact CURRENT336")
    alias_map = _case_map(alias, "alias CURRENT336")
    if TARGET_CASE_KEY not in exact_map or TARGET_CASE_KEY not in alias_map:
        raise MismatchError("target case absent from one CURRENT catalog")
    exact_row = exact_map[TARGET_CASE_KEY]
    alias_row = alias_map[TARGET_CASE_KEY]
    exact_row_sha = _canonical_sha(exact_row)
    alias_row_sha = _canonical_sha(alias_row)
    if exact_row_sha != alias_row_sha:
        raise MismatchError("target row itself differs between exact and alias catalogs")
    common_keys = sorted(set(exact_map) & set(alias_map))
    equal_keys = [key for key in common_keys if _canonical_sha(exact_map[key]) == _canonical_sha(alias_map[key])]
    differing_keys = [key for key in common_keys if key not in set(equal_keys)]
    exact_only = sorted(set(exact_map) - set(alias_map))
    alias_only = sorted(set(alias_map) - set(exact_map))
    top_level_differences: dict[str, dict[str, Any]] = {}
    for key in sorted(set(exact) | set(alias)):
        if key == "cases":
            continue
        left = exact.get(key)
        right = alias.get(key)
        if _canonical(left) != _canonical(right):
            top_level_differences[key] = {
                "exact_summary": _summary(left),
                "alias_summary": _summary(right),
            }

    sidecar = {
        "schema": SCHEMA,
        "status": "RECONCILED_HISTORICAL_ALIAS_MISMATCH_NO_SCIENTIFIC_CREDIT",
        "case_key": TARGET_CASE_KEY,
        "family_id": "F2",
        "physical_case_id": TARGET_PHYSICAL_ID,
        "read_policy": {
            "json_only": True,
            "opened_paths": sorted(str(path) for path in (proof_path, report_path, root_receipt_path, exact_path, alias_path, scan_path, scan_receipt_path, detail_path)),
            "h5_raw_bi4_obi4_vtk_opened": False,
            "scientific_arrays_read": False,
        },
        "root183_binding": {
            "proof": {"path": str(proof_path), "sha256": proof_ref["sha256"]},
            "report": {"path": str(report_path), "sha256": report_ref["sha256"]},
            "execution_receipt": {"path": str(root_receipt_path), "sha256": root_receipt_ref["sha256"]},
            "report_status": report.get("status"),
            "producer_status": root_receipt.get("status"),
        },
        "historical_producer": {
            "scan": {"path": str(scan_path), "sha256": scan_ref["sha256"]},
            "receipt": {"path": str(scan_receipt_path), "sha256": scan_receipt_ref["sha256"]},
            "detail_card": {"path": str(detail_path), "sha256": detail_ref["sha256"]},
            "attempt_id": scan_request.get("attempt_id"),
            "output_root": scan_receipt.get("output_root"),
            "receipt_current_binding": current_binding,
            "input_alias_sha256": input_alias_sha,
            "input_exact_sha256_observed": input_exact_sha,
        },
        "current_catalogs": {
            "exact": {
                "path": str(exact_path),
                "sha256": exact_ref["sha256"],
                "bytes": exact_ref["bytes"],
                "schema": exact.get("schema"),
                "case_count": len(exact_map),
                "target_row_sha256": exact_row_sha,
            },
            "historical_alias": {
                "path": str(alias_path),
                "sha256": alias_ref["sha256"],
                "bytes": alias_ref["bytes"],
                "schema": alias.get("schema"),
                "case_count": len(alias_map),
                "target_row_sha256": alias_row_sha,
            },
            "target_row_equal": True,
            "catalog_level_identity_equal": exact_ref["sha256"] == alias_ref["sha256"],
            "common_case_count": len(common_keys),
            "equal_row_count": len(equal_keys),
            "different_row_count": len(differing_keys),
            "exact_only_case_count": len(exact_only),
            "alias_only_case_count": len(alias_only),
            "different_row_examples": differing_keys[:10],
            "exact_only_examples": exact_only[:10],
            "alias_only_examples": alias_only[:10],
            "top_level_differences": top_level_differences,
        },
        "classification": {
            "historical_receipt_missing": "UNKNOWN",
            "migration_path_proven": False,
            "catalog_content_difference": "CONFIRMED_AT_CATALOG_LEVEL",
            "target_row_content_difference": "NOT_OBSERVED_TARGET_ROW_CANONICAL_EQUAL",
            "current_receipt_identity": "HISTORICAL_ALIAS_INPUT_IDENTITY_MISMATCH",
            "source_closure": "MISMATCH_REMAINS_NO_EXACT_CURRENT_RECEIPT_CREDIT",
            "scientific_credit": "NONE",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "limits": [
            "Equal target rows do not repair the producer receipt's alias path/SHA identity.",
            "Catalog-wide differences prevent treating the alias as the exact CURRENT336 producer input.",
            "No missing-original-receipt or migration provenance was found in the declared JSON evidence.",
            "This sidecar does not infer physical fate, legal flux, dynamics, or qualification.",
        ],
    }
    return sidecar


def validate_sidecar(sidecar: dict[str, Any]) -> dict[str, Any]:
    """Validate the already-produced sidecar without reopening its sources.

    This is deliberately a weaker, metadata-only consumer.  The source
    hashes and catalog comparison were established by ``build``/``audit``;
    this bounded consumer records an index patch from that immutable sidecar
    and cannot upgrade the historical receipt or scientific qualification.
    """
    if sidecar.get("schema") != SCHEMA:
        raise MismatchError("unexpected mismatch sidecar schema")
    if sidecar.get("status") != "RECONCILED_HISTORICAL_ALIAS_MISMATCH_NO_SCIENTIFIC_CREDIT":
        raise MismatchError("sidecar is not the expected reconciled mismatch")
    if sidecar.get("case_key") != TARGET_CASE_KEY or sidecar.get("physical_case_id") != TARGET_PHYSICAL_ID:
        raise MismatchError("sidecar target identity differs")
    classification = sidecar.get("classification")
    if not isinstance(classification, dict):
        raise MismatchError("sidecar classification is missing")
    for key in ("QI", "QN", "QE", "physical_fate", "dynamical_impact"):
        if classification.get(key) != "UNKNOWN":
            raise MismatchError(f"sidecar grants unsupported {key} status")
    if classification.get("scientific_credit") != "NONE":
        raise MismatchError("sidecar grants scientific credit")
    catalogs = sidecar.get("current_catalogs")
    if not isinstance(catalogs, dict) or catalogs.get("target_row_equal") is not True:
        raise MismatchError("sidecar lacks target row equality evidence")
    if catalogs.get("catalog_level_identity_equal") is not False:
        raise MismatchError("sidecar does not retain catalog-level mismatch")
    producer = sidecar.get("historical_producer")
    if not isinstance(producer, dict) or producer.get("input_exact_sha256_observed") is not None:
        raise MismatchError("sidecar historical input unexpectedly became exact CURRENT")
    return {
        "schema": "ds02.stage2.current-receipt-mismatch-index-patch.v1",
        "status": "INDEX_MISMATCH_RECORDED_NO_SCIENTIFIC_CREDIT",
        "case_key": sidecar["case_key"],
        "family_id": sidecar["family_id"],
        "physical_case_id": sidecar["physical_case_id"],
        "receipt_identity": "HISTORICAL_ALIAS_INPUT_IDENTITY_MISMATCH",
        "target_row": "CURRENT_AND_ALIAS_CANONICAL_ROW_EQUAL",
        "catalog_identity": "CATALOG_LEVEL_DIFFERENCE_RETAINED",
        "source_closure": "NO_EXACT_CURRENT_RECEIPT_CREDIT",
        "scientific_credit": "NONE",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "exact_current": catalogs["exact"],
        "historical_alias": catalogs["historical_alias"],
        "historical_receipt": producer["receipt"],
        "provenance": {
            "root183": sidecar["root183_binding"],
            "sidecar_read_only": True,
            "h5_raw_bi4_obi4_vtk_opened": False,
        },
    }


def _summary(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(value)}
    if isinstance(value, list):
        return {"type": "array", "length": len(value), "sha256": _canonical_sha(value)}
    return value


def build_manifest(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    exact = _path(args.exact_current, "exact CURRENT")
    alias = _path(args.alias_current, "alias CURRENT")
    report = _path(args.report, "ROOT183 report")
    proof = _path(args.proof, "ROOT183 proof")
    root_receipt = _path(args.root_receipt, "ROOT183 receipt")
    scan = _path(args.scan, "target scan")
    scan_receipt = _path(args.scan_receipt, "target scan receipt")
    detail = _path(args.detail, "target detail card")
    sources = [
        _ref(proof, "root183_proof"),
        _ref(report, "root183_report"),
        _ref(root_receipt, "root183_execution_receipt"),
        _ref(exact, "current_exact"),
        _ref(alias, "current_alias"),
        _ref(scan, "target_scientific_scan"),
        _ref(scan_receipt, "target_scan_receipt"),
        _ref(detail, "target_detail_card"),
    ]
    report_value = read_json(report, "ROOT183 report")
    target = _report_case(report_value, TARGET_CASE_KEY)
    root_receipt_value = read_json(root_receipt, "ROOT183 receipt")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_JSON_ONLY",
        "target": {
            "case_key": TARGET_CASE_KEY,
            "family_id": "F2",
            "physical_case_id": TARGET_PHYSICAL_ID,
            "exact_current_path": str(exact),
            "exact_current_sha256": sha256_file(exact),
            "alias_current_path": str(alias),
            "alias_current_sha256": sha256_file(alias),
            "root183_output_root": root_receipt_value.get("output_root"),
            "root183_report_sha256": sha256_file(report),
            "root183_proof_sha256": sha256_file(proof),
            "producer_attempt_id": target.get("receipt", {}).get("attempt_id"),
        },
        "source_refs": sources,
        "read_policy": {
            "json_only": True,
            "content_read_exclusions": ["H5", "raw", "BI4", "OBI4", "VTK", "native arrays"],
            "scientific_credit": "NONE",
        },
        "request_scope": "repair_metadata_index_only; no scientific qualification or physical-fate credit",
    }
    manifest_path = output_dir / "current-receipt-mismatch-v1-manifest.json"
    sidecar_path = output_dir / "current-receipt-mismatch-v1.json"
    atomic_json(manifest_path, manifest)
    sidecar = reconcile(manifest)
    sidecar["manifest"] = {"path": str(manifest_path), "sha256": sha256_file(manifest_path)}
    atomic_json(sidecar_path, sidecar)
    return manifest, manifest_path, sidecar_path


def _runtime_ref(path: Path, role: str) -> dict[str, Any]:
    return _ref(path, role)


def build_request(args: argparse.Namespace) -> Path:
    manifest_path = _path(args.manifest, "mismatch manifest")
    manifest = read_json(manifest_path, "mismatch manifest")
    _validate_manifest_sources(manifest)
    output = Path(args.output).expanduser().resolve()
    worktree = Path(args.worktree_root).expanduser().resolve()
    cwd = Path(args.cwd).expanduser().resolve()
    worker = _path(args.worker, "mismatch worker")
    python = _path(args.python, "interpreter")
    runtime_v2 = _path(args.runtime_v2, "runtime v2")
    runtime_v6 = _path(args.runtime_v6, "runtime v6")
    runtime_v8 = _path(args.runtime_v8, "runtime v8")
    dispatch_v8 = _path(args.dispatch_v8, "dispatch v8")
    strict_v8 = _path(args.strict_v8, "strict dispatch v8")
    if not worktree.is_dir() or not cwd.is_dir():
        raise MismatchError("cwd/worktree_root must be existing directories")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise MismatchError("cwd must be inside worktree_root") from exc
    sources = _source_refs(manifest)
    all_refs = list(sources)
    by_path = {str(Path(row["path"]).resolve()): row for row in all_refs}
    for path, role in ((manifest_path, "mismatch_manifest"), (SCRIPT, "mismatch_worker"), (python, "interpreter"), (runtime_v2, "runtime_v2_base"), (runtime_v6, "runtime_v6_root"), (runtime_v8, "runtime_v8"), (dispatch_v8, "dispatch_v8"), (strict_v8, "strict_v8")):
        ref = _runtime_ref(path, role)
        by_path[str(path.resolve())] = ref
    ordered = [by_path[key] for key in sorted(by_path)]
    input_files = [row["path"] for row in ordered]
    input_sha = {row["path"]: row["sha256"] for row in ordered}
    command = [str(python), str(worker), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/current-receipt-mismatch-v1.json"]
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": "infra",
        "case_id": "STAGE2_CURRENT_RECEIPT_MISMATCH_F2_S1",
        "physical_case_id": TARGET_PHYSICAL_ID,
        "attempt_id": "current-receipt-mismatch-v1-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "estimated_cpu_core_hours": 0.05,
        "estimated_gpu_seconds": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_native_read_bytes": 0,
        "estimated_input_read_bytes": sum(int(row["bytes"]) for row in ordered),
        "cwd": str(cwd),
        "worktree_root": str(worktree),
        "command": command,
        "input_files": input_files,
        "input_sha256": input_sha,
        "runtime_binding": {
            "runtime_v2_base": {"path": str(runtime_v2), "sha256": input_sha[str(runtime_v2)]},
            "runtime_v6_root": {"path": str(runtime_v6), "sha256": input_sha[str(runtime_v6)]},
            "runtime_v8": {"path": str(runtime_v8), "sha256": input_sha[str(runtime_v8)]},
        },
        "dispatch_binding": {"dispatch_v8": {"path": str(dispatch_v8), "sha256": input_sha[str(dispatch_v8)]}},
        "strict_dispatch_binding": {"strict_v8": {"path": str(strict_v8), "sha256": input_sha[str(strict_v8)]}},
        "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]},
        "guarded_payload_binding": {
            "json_only": True,
            "h5_content_read": False,
            "raw_partout_content_read": False,
            "native_array_read": False,
            "scientific_credit": "NONE",
        },
        "claim_boundary": {
            "source_closure": "historical alias mismatch classified only",
            "scientific_qualification": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "launch_allowed": True,
        "execution_allowed": True,
        "request_note": "JSON-only source mismatch index repair; preserve original CURRENT and receipts; no H5/raw/native input.",
    }
    atomic_json(output, request)
    return output


def build_index_request(args: argparse.Namespace) -> Path:
    """Build the small sidecar-only consumer request.

    Unlike the full ``request`` action, this request does not re-open the
    eight source JSON files.  It consumes the immutable sidecar and its ROOT
    proof reference only, so the declared metadata payload stays well below
    10 MiB while retaining the no-credit boundary.
    """
    sidecar_path = _path(args.sidecar, "mismatch sidecar")
    proof_path = _path(args.proof, "ROOT183 proof")
    sidecar = read_json(sidecar_path, "mismatch sidecar")
    validate_sidecar(sidecar)
    proof = read_json(proof_path, "ROOT183 proof")
    if proof.get("report_sha256") != sidecar.get("root183_binding", {}).get("report", {}).get("sha256"):
        raise MismatchError("ROOT183 proof/report binding differs from sidecar")
    output = Path(args.output).expanduser().resolve()
    worktree = Path(args.worktree_root).expanduser().resolve()
    cwd = Path(args.cwd).expanduser().resolve()
    worker = _path(args.worker, "mismatch worker")
    python = _path(args.python, "interpreter")
    runtime_v2 = _path(args.runtime_v2, "runtime v2")
    runtime_v6 = _path(args.runtime_v6, "runtime v6")
    runtime_v8 = _path(args.runtime_v8, "runtime v8")
    dispatch_v8 = _path(args.dispatch_v8, "dispatch v8")
    strict_v8 = _path(args.strict_v8, "strict dispatch v8")
    if not worktree.is_dir() or not cwd.is_dir():
        raise MismatchError("cwd/worktree_root must be existing directories")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise MismatchError("cwd must be inside worktree_root") from exc
    paths = [
        (sidecar_path, "mismatch_sidecar"),
        (proof_path, "root183_proof"),
        (SCRIPT, "mismatch_worker"),
        (python, "interpreter"),
        (runtime_v2, "runtime_v2_base"),
        (runtime_v6, "runtime_v6_root"),
        (runtime_v8, "runtime_v8"),
        (dispatch_v8, "dispatch_v8"),
        (strict_v8, "strict_v8"),
    ]
    refs = [_runtime_ref(path, role) for path, role in paths]
    input_files = [row["path"] for row in refs]
    input_sha = {row["path"]: row["sha256"] for row in refs}
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": "infra",
        "case_id": "STAGE2_CURRENT_RECEIPT_MISMATCH_INDEX",
        "physical_case_id": TARGET_PHYSICAL_ID,
        "attempt_id": "current-receipt-mismatch-index-v1-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_cpu_core_hours": 0.02,
        "estimated_gpu_seconds": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_native_read_bytes": 0,
        "estimated_input_read_bytes": sum(int(row["bytes"]) for row in refs),
        "cwd": str(cwd),
        "worktree_root": str(worktree),
        "command": [str(python), str(worker), "validate-sidecar", "--sidecar", str(sidecar_path), "--proof", str(proof_path), "--output", "{attempt_root}/current-receipt-mismatch-index-patch.json"],
        "input_files": input_files,
        "input_sha256": input_sha,
        "runtime_binding": {
            "runtime_v2_base": {"path": str(runtime_v2), "sha256": input_sha[str(runtime_v2)]},
            "runtime_v6_root": {"path": str(runtime_v6), "sha256": input_sha[str(runtime_v6)]},
            "runtime_v8": {"path": str(runtime_v8), "sha256": input_sha[str(runtime_v8)]},
        },
        "dispatch_binding": {"dispatch_v8": {"path": str(dispatch_v8), "sha256": input_sha[str(dispatch_v8)]}},
        "strict_dispatch_binding": {"strict_v8": {"path": str(strict_v8), "sha256": input_sha[str(strict_v8)]}},
        "manifest_contract": {"path": str(sidecar_path), "sha256": input_sha[str(sidecar_path)]},
        "guarded_payload_binding": {
            "json_only": True,
            "h5_content_read": False,
            "raw_partout_content_read": False,
            "native_array_read": False,
            "scientific_credit": "NONE",
        },
        "claim_boundary": {
            "source_closure": "historical alias mismatch indexed only",
            "scientific_qualification": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "launch_allowed": True,
        "execution_allowed": True,
        "request_note": "Small JSON-only index sidecar consumer; original CURRENT/receipts remain immutable; no scientific credit.",
    }
    atomic_json(output, request)
    return output


def _default_paths() -> dict[str, str]:
    data = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    infra = data / "families/infra"
    scan = data / "families/F2/STAGE2_F2_S1_SCIENCE/scan-F2-S1-001"
    detail = infra / "DS02_STAGE2_SCIENTIFIC_SCAN_DETAIL_336/scientific-scan-detail-v2-forward-001-root-forward-030-001/details/078-F2-F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090.json"
    root183 = infra / "DS02_STAGE2_SCIENTIFIC_SCAN_ENRICHED_AUDIT_V3_ROOT_183/scientific-scan-enriched-audit-v3-root-183-001-root-forward-030-001"
    return {
        "proof": str(primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_ENRICHED_TYPED_SCAN_METADATA_ACTUAL_ROOT_VERIFICATION_183.json"),
        "report": str(root183 / "scientific-scan-enriched-audit-v3.json"),
        "root_receipt": str(root183 / "execution-receipt.json"),
        "exact_current": str(primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"),
        "alias_current": str(infra / "STAGE2_CURRENT336_CATALOG/catalog-002/CURRENT336.json"),
        "scan": str(scan / "scientific-scan.json"),
        "scan_receipt": str(scan / "execution-receipt.json"),
        "detail": str(detail),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build", help="build and audit the immutable JSON sidecar")
    defaults = _default_paths()
    for name in ("proof", "report", "root_receipt", "exact_current", "alias_current", "scan", "scan_receipt", "detail"):
        build.add_argument(f"--{name.replace('_', '-')}", default=defaults[name])
    build.add_argument("--output-dir", required=True, type=Path)
    audit = sub.add_parser("audit", help="revalidate an immutable sidecar manifest")
    audit.add_argument("--manifest", required=True, type=Path)
    audit.add_argument("--output", required=True, type=Path)
    request = sub.add_parser("request", help="build a strict v8 metadata-only request")
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
    index = sub.add_parser("index-request", help="build the small sidecar-only v8 request")
    index.add_argument("--sidecar", required=True, type=Path)
    index.add_argument("--proof", required=True, type=Path)
    index.add_argument("--output", required=True, type=Path)
    index.add_argument("--worker", type=Path, default=SCRIPT)
    index.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    index.add_argument("--runtime-v2", required=True, type=Path)
    index.add_argument("--runtime-v6", required=True, type=Path)
    index.add_argument("--runtime-v8", required=True, type=Path)
    index.add_argument("--dispatch-v8", required=True, type=Path)
    index.add_argument("--strict-v8", required=True, type=Path)
    index.add_argument("--cwd", required=True, type=Path)
    index.add_argument("--worktree-root", required=True, type=Path)
    validate = sub.add_parser("validate-sidecar", help="validate and consume only an immutable sidecar")
    validate.add_argument("--sidecar", required=True, type=Path)
    validate.add_argument("--proof", required=True, type=Path)
    validate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == "build":
        _manifest, manifest_path, sidecar_path = build_manifest(args)
        print(json.dumps({"manifest": str(manifest_path), "sidecar": str(sidecar_path)}, sort_keys=True))
        return 0
    if args.action == "audit":
        manifest = read_json(args.manifest, "mismatch manifest")
        sidecar = reconcile(manifest)
        sidecar["manifest"] = {"path": str(Path(args.manifest).resolve()), "sha256": sha256_file(Path(args.manifest))}
        atomic_json(args.output, sidecar)
        print(json.dumps({"sidecar": str(Path(args.output).resolve())}, sort_keys=True))
        return 0
    if args.action == "request":
        output = build_request(args)
        print(json.dumps({"request": str(output)}, sort_keys=True))
        return 0
    if args.action == "index-request":
        output = build_index_request(args)
        print(json.dumps({"request": str(output)}, sort_keys=True))
        return 0
    if args.action == "validate-sidecar":
        sidecar_path = _path(args.sidecar, "mismatch sidecar")
        proof_path = _path(args.proof, "ROOT183 proof")
        sidecar = read_json(sidecar_path, "mismatch sidecar")
        proof = read_json(proof_path, "ROOT183 proof")
        validate_sidecar(sidecar)
        if proof.get("report_sha256") != sidecar.get("root183_binding", {}).get("report", {}).get("sha256"):
            raise MismatchError("ROOT183 proof/report binding differs from sidecar")
        patch = validate_sidecar(sidecar)
        patch["input_sidecar"] = {"path": str(sidecar_path), "sha256": sha256_file(sidecar_path)}
        patch["input_proof"] = {"path": str(proof_path), "sha256": sha256_file(proof_path)}
        atomic_json(args.output, patch)
        print(json.dumps({"output": str(Path(args.output).resolve())}, sort_keys=True))
        return 0
    raise AssertionError(args.action)


if __name__ == "__main__":
    raise SystemExit(main())
