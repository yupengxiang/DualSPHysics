#!/usr/bin/env python3
"""Strict bounded metadata verifier V5 for guarded raw-HDF5 field audit V3.

This additive V5 verifier keeps the V3 report ABI but closes the admission
boundary before an independent verifier is used by a root request.  It only
reads bounded source/control metadata, rejects scientific payload files and
static files above the 10 MiB cap, captures stable stat/SHA pairs, checks
CURRENT membership/family, and follows each case's terminal proof -> request
-> receipt -> case-manifest -> summary chain.  It does not import h5py and
never opens or hashes a deferred trajectory HDF5 file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

SCRIPT = Path(__file__).resolve()
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_STATIC_REF_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v2"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-audit.v3"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
REJECTED_HISTORICAL_ALIASES = {
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
}
REQUIRED_FIELDS = ("position", "velocity", "density", "mass", "pressure", "valid", "type")
FINITE_FIELDS = ("position", "velocity", "density", "mass", "pressure")
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
REJECTED_STATIC_SUFFIXES = {
    ".h5", ".hdf5", ".hdf", ".h5part", ".bi4", ".obi4", ".ibi4",
    ".vtk", ".vtu", ".vti", ".vtr", ".vtp", ".pvtu", ".pvd", ".xmf",
    ".xdmf", ".jsonl", ".csv", ".bin", ".npy", ".npz", ".raw", ".dat",
    ".out",
}


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded_static_path(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, (str, os.PathLike)) or not path_value:
        raise VerificationError(f"{label} lacks a path")
    unresolved = Path(path_value).expanduser()
    try:
        if unresolved.is_symlink():
            raise VerificationError(f"{label} is a symlink, not a stable bounded source file: {unresolved}")
    except OSError as exc:
        raise VerificationError(f"{label} cannot be inspected") from exc
    path = unresolved.resolve()
    if path.suffix.lower() in REJECTED_STATIC_SUFFIXES:
        raise VerificationError(f"{label} is a scientific payload, not bounded source metadata: {path}")
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    size = path.stat().st_size
    if size > MAX_STATIC_REF_BYTES:
        raise VerificationError(f"{label} exceeds the 10 MiB static-source cap: {path}")
    return path


def stable_static_sha(path: Path, label: str) -> tuple[str, dict[str, Any]]:
    before = current_stat(path, f"{label} pre-stat")
    value = sha256_file(path)
    after = current_stat(path, f"{label} post-stat")
    compare_stat(before, after, f"{label} changed during bounded read")
    return value, after


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerificationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise VerificationError(f"{label} is not hexadecimal")
    return value


def read_json(path_value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    path = bounded_static_path(path_value, label)
    before = current_stat(path, f"{label} pre-stat")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_JSON_BYTES:
            raise VerificationError(f"{label} exceeds the bounded JSON size")
        value = json.loads(raw.decode("utf-8"))
    except VerificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is invalid JSON") from exc
    after = current_stat(path, f"{label} post-stat")
    compare_stat(before, after, f"{label} changed during bounded JSON read")
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return path, value


def path_ref(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise VerificationError(f"{label} lacks a path")
    return Path(value).expanduser().resolve()


def stat_key(value: dict[str, Any], label: str) -> tuple[Any, ...]:
    try:
        return tuple(value[key] for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"))
    except KeyError as exc:
        raise VerificationError(f"{label} is missing stat field {exc.args[0]}") from exc


def current_stat(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def one_case(rows: Any, case_id: str, label: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise VerificationError(f"{label} is not a list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise VerificationError(f"{label} has non-unique case {case_id}")
    return matches[0]



def compare_stat(expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if expected.get(key) != actual.get(key):
            raise VerificationError(f"{label} differs at {key}")


def load_static_refs(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    refs = manifest.get("static_source_refs")
    if not isinstance(refs, list) or not refs:
        raise VerificationError("manifest static_source_refs is missing")
    static: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise VerificationError("static source ref is not an object")
        path = bounded_static_path(ref.get("path"), "static source ref")
        expected = digest(ref.get("sha256"), f"static source SHA {path}")
        actual, stable = stable_static_sha(path, f"static source {path}")
        if actual != expected:
            raise VerificationError(f"static source changed: {path}")
        key = str(path)
        if key in static and static[key]["sha256"] != expected:
            raise VerificationError(f"conflicting static source refs: {path}")
        static[key] = {**ref, "path": key, "sha256": expected, "stable_stat": stable}
    current = manifest.get("current_catalog")
    if not isinstance(current, dict):
        raise VerificationError("manifest current_catalog is missing")
    current_path = bounded_static_path(current.get("path"), "manifest CURRENT")
    current_sha = digest(current.get("sha256"), "manifest CURRENT SHA")
    if current_sha != CURRENT_SHA256:
        raise VerificationError("manifest CURRENT path/SHA is not the frozen CURRENT catalog")
    current_digest, current_ref = stable_static_sha(current_path, "manifest CURRENT")
    if current_digest != current_sha:
        raise VerificationError("manifest CURRENT content differs from its frozen SHA")
    _, current_document = read_json(current_path, "manifest CURRENT")
    rows = current_document.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise VerificationError("manifest CURRENT must contain exactly 336 cases")
    case_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise VerificationError("manifest CURRENT contains an invalid case row")
        case_id = row["physical_case_id"]
        if case_id in case_map:
            raise VerificationError(f"manifest CURRENT repeats case {case_id}")
        case_map[case_id] = row
    return static, {"path": str(current_path), "sha256": current_sha, "stat": current_ref, "case_count": current.get("cases"), "case_map": case_map}


def read_bound_metadata(ref: Any, static: dict[str, dict[str, Any]], label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict):
        raise VerificationError(f"{label} reference is missing")
    path = bounded_static_path(ref.get("path"), label)
    expected = digest(ref.get("sha256"), f"{label} SHA")
    bound = static.get(str(path))
    if bound is None or bound.get("sha256") != expected:
        raise VerificationError(f"{label} is not the exact bounded static reference")
    actual, _ = stable_static_sha(path, label)
    if actual != expected:
        raise VerificationError(f"{label} changed")
    _, value = read_json(path, label)
    return path, value


def read_unlisted_metadata(path_value: Any, expected_sha: Any, label: str) -> tuple[Path, dict[str, Any]]:
    path = bounded_static_path(path_value, label)
    expected = digest(expected_sha, f"{label} SHA")
    actual, _ = stable_static_sha(path, label)
    if actual != expected:
        raise VerificationError(f"{label} content differs from terminal proof")
    _, value = read_json(path, label)
    return path, value


def find_case_rows(value: Any, case_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("physical_case_id") == case_id:
            found.append(value)
        for nested in value.values():
            found.extend(find_case_rows(nested, case_id))
    elif isinstance(value, list):
        for nested in value:
            found.extend(find_case_rows(nested, case_id))
    return found


def _proof_top_ref(proof: dict[str, Any], key: str, label: str) -> tuple[Path, dict[str, Any]]:
    value = proof.get(key)
    sha_key = f"{key}_sha256"
    if not isinstance(value, str) or not isinstance(proof.get(sha_key), str):
        raise VerificationError(f"{label} terminal proof reference is incomplete")
    return read_unlisted_metadata(value, proof[sha_key], label)


def verify_terminal_identity_chain(case: dict[str, Any], static: dict[str, dict[str, Any]], current: dict[str, Any]) -> None:
    case_id = case.get("physical_case_id")
    family_id = case.get("family_id")
    if case_id in REJECTED_HISTORICAL_ALIASES:
        raise VerificationError(f"{case_id}: historical alias is excluded from canonical production admission")
    current_row = current.get("case_map", {}).get(case_id)
    if not isinstance(current_row, dict):
        raise VerificationError(f"{case_id}: case is not a member of frozen CURRENT")
    if current_row.get("family_id") != family_id:
        raise VerificationError(f"{case_id}: manifest family differs from CURRENT family")
    if current_row.get("saved_mask_status") == "HISTORICAL_ALIAS_UNRESOLVED" or current_row.get("source_join_status") == "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED":
        raise VerificationError(f"{case_id}: historical alias cannot enter production V4 verification")

    proof_path, proof = read_bound_metadata(case.get("producer_terminal_proof"), static, f"{case_id} terminal proof")
    if not isinstance(proof.get("status"), str) or not proof["status"].startswith("VERIFIED_ACTUAL_"):
        raise VerificationError(f"{case_id}: terminal proof is not an actual verified producer proof")
    counts = proof.get("counts")
    batch_proof = isinstance(counts, dict)
    if batch_proof:
        if counts.get("failed") != 0 or counts.get("completed") != counts.get("cases_requested"):
            raise VerificationError(f"{case_id}: terminal proof counts are not complete")
        rows = find_case_rows(proof.get("case_verifications"), case_id)
        if len(rows) != 1:
            raise VerificationError(f"{case_id}: terminal proof has no unique case row")
        proof_row = rows[0]
        if proof_row.get("family_id") != family_id or proof_row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise VerificationError(f"{case_id}: terminal proof case row is not the expected saved-mask result")
    else:
        if proof.get("physical_case_id") != case_id or proof.get("outer_unit_result") != "success" or proof.get("guarded_receipt_status") not in {"completed", "COMPLETED", "COMPLETED_DEVELOPMENT_UNKNOWN"} or proof.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise VerificationError(f"{case_id}: single-case terminal proof is incomplete")
        proof_row = proof

    case_manifest_path, case_manifest = read_bound_metadata(case.get("case_manifest"), static, f"{case_id} case manifest")
    receipt_path, receipt = read_bound_metadata(case.get("producer_receipt"), static, f"{case_id} case receipt")
    summary_path, summary = read_bound_metadata(case.get("typed_summary"), static, f"{case_id} typed summary")
    for label, document in (("case manifest", case_manifest), ("case receipt", receipt), ("typed summary", summary)):
        if document.get("physical_case_id") != case_id or document.get("family_id") != family_id:
            raise VerificationError(f"{case_id}: {label} identity differs from CURRENT")
    if case_manifest.get("status") != "READY_FOR_GUARDED_TYPED_LIFECYCLE":
        raise VerificationError(f"{case_id}: case manifest is not the guarded typed-lifecycle manifest")
    if receipt.get("status") != "COMPLETED":
        raise VerificationError(f"{case_id}: case receipt is not completed")
    if not isinstance(summary.get("status"), str) or not summary["status"].startswith("COMPLETED_TYPED_LIFECYCLE"):
        raise VerificationError(f"{case_id}: typed summary is not a completed lifecycle summary")
    current_catalog = case_manifest.get("current_catalog")
    if not isinstance(current_catalog, dict) or current_catalog.get("path") != current["path"] or current_catalog.get("sha256") != current["sha256"]:
        raise VerificationError(f"{case_id}: case manifest does not bind frozen CURRENT")
    trajectory = case_manifest.get("trajectory_h5")
    manifest_h5 = case.get("trajectory_h5")
    if not isinstance(trajectory, dict) or not isinstance(manifest_h5, dict) or trajectory.get("path") != manifest_h5.get("path") or trajectory.get("sha256") != manifest_h5.get("known_sha256"):
        raise VerificationError(f"{case_id}: case manifest HDF5 source differs from audit manifest")
    receipt_manifest = receipt.get("case_manifest")
    if receipt_manifest != str(case_manifest_path) or receipt.get("case_manifest_sha256") != case.get("case_manifest", {}).get("sha256"):
        raise VerificationError(f"{case_id}: case receipt does not bind its case manifest")

    expected_rows = {
        "case_manifest": (str(case_manifest_path), case.get("case_manifest", {}).get("sha256")),
        "receipt": (str(receipt_path), case.get("producer_receipt", {}).get("sha256")),
        "summary": (str(summary_path), case.get("typed_summary", {}).get("sha256")),
    }
    if batch_proof:
        for key, (path, sha) in expected_rows.items():
            if proof_row.get(key) != path or proof_row.get(f"{key}_sha256") != sha:
                raise VerificationError(f"{case_id}: terminal proof {key} edge differs from source contract")
    else:
        if proof.get("report") != str(summary_path) or proof.get("report_sha256") != case.get("typed_summary", {}).get("sha256"):
            raise VerificationError(f"{case_id}: single-case terminal proof report differs from typed summary")
    if batch_proof:
        source_row = proof_row.get("source_trajectory")
        if not isinstance(source_row, dict) or source_row.get("known_sha256") != manifest_h5.get("known_sha256") or source_row.get("path") != manifest_h5.get("path"):
            raise VerificationError(f"{case_id}: terminal proof HDF5 identity differs from source contract")

    request_path, request = _proof_top_ref(proof, "request", f"{case_id} terminal request")
    receipt_top_path, receipt_top = _proof_top_ref(proof, "receipt", f"{case_id} terminal execution receipt")
    request_ids = request.get("physical_case_ids")
    if not isinstance(request_ids, list) or case_id not in request_ids:
        raise VerificationError(f"{case_id}: terminal request does not contain the case")
    if batch_proof:
        manifest_top_path, manifest_top = _proof_top_ref(proof, "manifest", f"{case_id} terminal batch manifest")
        manifest_cases = manifest_top.get("cases")
        if not isinstance(manifest_cases, list) or not any(isinstance(row, dict) and row.get("physical_case_id") == case_id for row in manifest_cases):
            raise VerificationError(f"{case_id}: terminal batch manifest does not contain the case")
    if receipt_top.get("status") not in {"COMPLETED", "completed", "COMPLETED_DEVELOPMENT_UNKNOWN"} or receipt_top.get("returncode") != 0:
        raise VerificationError(f"{case_id}: terminal execution receipt is not completed")


def verify_case(case: dict[str, Any], result: dict[str, Any], static: dict[str, dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise VerificationError("manifest case has no physical_case_id")
    verify_terminal_identity_chain(case, static, current)
    if result.get("physical_case_id") != case_id:
        raise VerificationError(f"{case_id}: result identity mismatch")
    if result.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError(f"{case_id}: unexpected result status")
    if result.get("worker_version") != "v3_vectorized_postread_guard":
        raise VerificationError(f"{case_id}: report is not from the V3 worker")
    source = result.get("source_binding")
    if not isinstance(source, dict):
        raise VerificationError(f"{case_id}: source_binding missing")
    report_manifest = source.get("manifest")
    if not isinstance(report_manifest, dict) or report_manifest.get("path") != current.get("path") or report_manifest.get("sha256") != current.get("sha256") or report_manifest.get("manifest_path") != current.get("manifest_path"):
        raise VerificationError(f"{case_id}: manifest binding is incomplete")
    trajectory = source.get("trajectory_h5")
    manifest_h5 = case.get("trajectory_h5")
    if not isinstance(trajectory, dict) or not isinstance(manifest_h5, dict):
        raise VerificationError(f"{case_id}: HDF5 source contract missing")
    h5_path = path_ref(manifest_h5.get("path"), f"{case_id} manifest HDF5")
    if path_ref(trajectory.get("path"), f"{case_id} report HDF5") != h5_path:
        raise VerificationError(f"{case_id}: HDF5 path differs from manifest")
    known = digest(manifest_h5.get("known_sha256"), f"{case_id} manifest HDF5 SHA")
    for key in ("known_sha256", "pre_sha256", "post_sha256"):
        if digest(trajectory.get(key), f"{case_id} report HDF5 {key}") != known:
            raise VerificationError(f"{case_id}: HDF5 {key} differs from manifest")
    expected_stat = {"path": str(h5_path), **{key: manifest_h5.get(key) for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}}
    pre_stat = trajectory.get("pre_stat")
    post_stat = trajectory.get("post_stat")
    if not isinstance(pre_stat, dict) or not isinstance(post_stat, dict):
        raise VerificationError(f"{case_id}: HDF5 pre/post stat missing")
    compare_stat(expected_stat, pre_stat, f"{case_id} HDF5 pre-stat versus manifest")
    compare_stat(pre_stat, post_stat, f"{case_id} HDF5 pre/post stat")
    compare_stat(pre_stat, current_stat(h5_path, f"{case_id} HDF5"), f"{case_id} HDF5 current stat")
    if trajectory.get("deferred_manifest_stat_match") is not True or source.get("hash_passes_minimum") != 3:
        raise VerificationError(f"{case_id}: deferred HDF5 guard evidence is incomplete")
    if trajectory.get("post_capture_after_all_dataset_and_attribute_reads") is not True:
        raise VerificationError(f"{case_id}: final HDF5 guard does not bracket all reads")

    producer_refs = source.get("producer_refs")
    if not isinstance(producer_refs, list) or len(producer_refs) != 4:
        raise VerificationError(f"{case_id}: producer refs are incomplete")
    expected_fields = ("producer_terminal_proof", "case_manifest", "producer_receipt", "typed_summary")
    seen = set()
    for item in producer_refs:
        if not isinstance(item, dict) or item.get("role") not in expected_fields or item["role"] in seen:
            raise VerificationError(f"{case_id}: producer ref identity is invalid")
        seen.add(item["role"])
        manifest_ref = case.get(item["role"])
        if not isinstance(manifest_ref, dict):
            raise VerificationError(f"{case_id}: manifest producer ref missing")
        path = path_ref(item.get("path"), f"{case_id} {item['role']}")
        expected_path = path_ref(manifest_ref.get("path"), f"{case_id} manifest {item['role']}")
        if path != expected_path or digest(item.get("sha256"), f"{case_id} {item['role']} SHA") != digest(manifest_ref.get("sha256"), f"{case_id} manifest {item['role']} SHA"):
            raise VerificationError(f"{case_id}: report producer ref differs from manifest")
        static_ref = static.get(str(path))
        if static_ref is None or static_ref["sha256"] != item["sha256"] or stable_static_sha(path, f"{case_id} {item['role']}")[0] != item["sha256"]:
            raise VerificationError(f"{case_id}: producer ref is not current static evidence")

    dimensions = result.get("dimensions")
    if not isinstance(dimensions, dict):
        raise VerificationError(f"{case_id}: dimensions missing")
    for key in ("frames_expected", "frames_scanned", "particles_expected", "particles_scanned"):
        if not isinstance(dimensions.get(key), int) or dimensions[key] <= 0:
            raise VerificationError(f"{case_id}: invalid dimensions.{key}")
    if dimensions["frames_expected"] != dimensions["frames_scanned"] or dimensions["particles_expected"] != dimensions["particles_scanned"]:
        raise VerificationError(f"{case_id}: scan dimensions are incomplete")
    if dimensions["frames_expected"] != int(case.get("expected_frames", -1)) or dimensions["particles_expected"] != int(case.get("expected_particles", -1)):
        raise VerificationError(f"{case_id}: dimensions differ from manifest")

    identity = result.get("identity")
    if not isinstance(identity, dict) or identity.get("key") != "(Zone,Idp)" or identity.get("status") not in {"VALID", "NOT_EXPOSED", "DUPLICATE_ZONE_IDP", "PRESENT_INVALID_TYPE"}:
        raise VerificationError(f"{case_id}: identity status is invalid")
    if not all(isinstance(identity.get(key), bool) for key in ("unique", "integer_zone", "integer_idp")):
        raise VerificationError(f"{case_id}: identity booleans are missing")
    if identity["status"] == "VALID" and identity != {"key": "(Zone,Idp)", "status": "VALID", "unique": True, "integer_zone": True, "integer_idp": True, "initial_axis_exposed": {"particle_id": "PRESENT", "particle_zone": "PRESENT"}}:
        raise VerificationError(f"{case_id}: valid identity has inconsistent fields")

    initial_type = result.get("initial_type")
    if not isinstance(initial_type, dict) or initial_type.get("status") not in {"PRESENT_VALID_CODES", "PRESENT_UNKNOWN_CODES", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH", "NOT_EXPOSED"}:
        raise VerificationError(f"{case_id}: initial type status is invalid")
    role_counts = initial_type.get("role_counts")
    if not isinstance(role_counts, dict) or set(role_counts) != {"fixed", "moving", "floating", "fluid", "unknown_initial_type"} or sum(role_counts.values()) != dimensions["particles_expected"]:
        raise VerificationError(f"{case_id}: initial role counts do not reconcile")
    invalid_codes = initial_type.get("invalid_code_count")
    if initial_type["status"] == "PRESENT_VALID_CODES" and invalid_codes != 0:
        raise VerificationError(f"{case_id}: valid initial type has invalid codes")
    if initial_type["status"] in {"NOT_EXPOSED", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH"} and invalid_codes is not None:
        raise VerificationError(f"{case_id}: unavailable initial type has a fabricated invalid-code count")

    initial_mass = result.get("initial_mass")
    if not isinstance(initial_mass, dict) or initial_mass.get("status") not in {"PRESENT_FINITE_POSITIVE", "PRESENT_INVALID_VALUES", "PRESENT_INVALID_TYPE", "PRESENT_SHAPE_MISMATCH", "NOT_EXPOSED"}:
        raise VerificationError(f"{case_id}: initial mass status is invalid")
    if initial_mass["status"] == "PRESENT_FINITE_POSITIVE":
        if initial_mass.get("finite_positive") is not True or initial_mass.get("invalid_value_count") != 0 or not isinstance(initial_mass.get("total_kg"), (int, float)):
            raise VerificationError(f"{case_id}: finite initial mass ledger is inconsistent")
    elif initial_mass.get("finite_positive") is not False or initial_mass.get("total_kg") is not None:
        raise VerificationError(f"{case_id}: unavailable/invalid initial mass was overstated")
    if initial_mass.get("native_massfluid_binding") != "UNKNOWN_NOT_ATTEMPTED":
        raise VerificationError(f"{case_id}: native MassFluid binding was overstated")

    scan = result.get("field_scan")
    if not isinstance(scan, dict) or scan.get("frames_full_scan") is not True or scan.get("inactive_nonfinite_separate") is not True:
        raise VerificationError(f"{case_id}: full-frame scan evidence is incomplete")
    field_status = scan.get("field_status")
    observations = scan.get("observations")
    if not isinstance(field_status, dict) or set(field_status) != set(FINITE_FIELDS) | {"valid", "type"} or not isinstance(observations, dict):
        raise VerificationError(f"{case_id}: field status ledger is incomplete")
    for field in FINITE_FIELDS:
        status = field_status[field]
        value = observations.get(field)
        if status == "PRESENT":
            if not isinstance(value, dict) or value.get("observations") != dimensions["frames_expected"] * dimensions["particles_expected"]:
                raise VerificationError(f"{case_id}: {field} was not fully streamed")
        elif status not in {"NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"}:
            raise VerificationError(f"{case_id}: invalid {field} status")
    if field_status["valid"] not in {"PRESENT", "NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"} or field_status["type"] not in {"PRESENT", "NOT_EXPOSED", "PRESENT_SHAPE_MISMATCH", "PRESENT_INVALID_TYPE"}:
        raise VerificationError(f"{case_id}: invalid mask/type status")
    roles = scan.get("roles")
    if not isinstance(roles, dict) or set(roles) != {"fixed", "moving", "floating", "fluid", "unknown_initial_type"}:
        raise VerificationError(f"{case_id}: role ledger is incomplete")
    for role, ledger in roles.items():
        if not isinstance(ledger, dict) or not isinstance(ledger.get("initial_particle_count"), int) or ledger["initial_particle_count"] < 0:
            raise VerificationError(f"{case_id}: role {role} initial count is invalid")
        for bucket in ("active_nonfinite", "inactive_nonfinite"):
            values = ledger.get(bucket)
            if not isinstance(values, dict) or set(values) != set(FINITE_FIELDS) or any(not isinstance(value, int) or value < 0 for value in values.values()):
                raise VerificationError(f"{case_id}: role {role} {bucket} is invalid")
    if sum(ledger["initial_particle_count"] for ledger in roles.values()) != dimensions["particles_expected"]:
        raise VerificationError(f"{case_id}: role initial counts do not reconcile")
    role_reconciliation = scan.get("role_reconciliation")
    if not isinstance(role_reconciliation, dict):
        raise VerificationError(f"{case_id}: role reconciliation is missing")
    if role_reconciliation.get("initial_expected_particles") != dimensions["particles_expected"] or role_reconciliation.get("initial_role_count_total") != dimensions["particles_expected"] or role_reconciliation.get("initial_role_counts_reconciled") is not True:
        raise VerificationError(f"{case_id}: initial role reconciliation is inconsistent")
    mask_exposed = field_status["valid"] == "PRESENT"
    total_active = scan.get("active_nonfinite_total")
    total_inactive = scan.get("inactive_nonfinite_total")
    if mask_exposed:
        if not isinstance(total_active, int) or not isinstance(total_inactive, int):
            raise VerificationError(f"{case_id}: exposed mask lacks active/inactive totals")
        if total_active != sum(sum(ledger["active_nonfinite"].values()) for ledger in roles.values()) or total_inactive != sum(sum(ledger["inactive_nonfinite"].values()) for ledger in roles.values()):
            raise VerificationError(f"{case_id}: active/inactive nonfinite totals do not reconcile")
    elif total_active is not None or total_inactive is not None:
        raise VerificationError(f"{case_id}: missing mask has fabricated active/inactive totals")
    if mask_exposed:
        if role_reconciliation.get("frame_expected_observations") != dimensions["frames_expected"] * dimensions["particles_expected"] or role_reconciliation.get("frame_active_count_total") != sum(ledger["observed_active_count"] for ledger in roles.values()) or role_reconciliation.get("frame_inactive_count_total") != sum(ledger["observed_inactive_count"] for ledger in roles.values()) or role_reconciliation.get("frame_role_counts_reconciled") is not True:
            raise VerificationError(f"{case_id}: frame role reconciliation is inconsistent")
    elif any(role_reconciliation.get(key) is not None for key in ("frame_active_count_total", "frame_inactive_count_total", "frame_invalid_mask_count", "frame_role_counts_reconciled")):
        raise VerificationError(f"{case_id}: unavailable mask has fabricated frame reconciliation")
    status = scan.get("active_finite_status")
    if status == "ALL_ACTIVE_REQUIRED_FIELDS_FINITE" and (set(field_status.values()) != {"PRESENT"} or initial_type.get("status") != "PRESENT_VALID_CODES" or not mask_exposed or scan.get("frame_type_unknown_total") != 0 or scan.get("active_type_unknown_total") != 0 or total_active != 0 or scan.get("invalid_mask_total") != 0):
        raise VerificationError(f"{case_id}: ALL_ACTIVE status hides an unknown field/type/mask")
    if status not in {"ALL_ACTIVE_REQUIRED_FIELDS_FINITE", "INITIAL_TYPE_UNKNOWN", "REQUIRED_FIELD_NOT_EXPOSED", "ACTIVE_MASK_NOT_EXPOSED", "ACTIVE_TYPE_OR_ROLE_UNKNOWN", "ACTIVE_NONFINITE_OBSERVATIONS", "MASK_UNKNOWN_OBSERVATIONS"}:
        raise VerificationError(f"{case_id}: active finite status is invalid")
    if scan.get("vectorized_chunk_reductions") is not True:
        raise VerificationError(f"{case_id}: V3 vectorized reduction marker is missing")
    ranges = result.get("physical_ranges")
    if not isinstance(ranges, dict) or ranges.get("status") != "DIAGNOSTIC_ONLY_NO_GATE":
        raise VerificationError(f"{case_id}: physical ranges are not diagnostic-only")
    units = result.get("units")
    material = result.get("material_and_mk")
    if not isinstance(units, dict) or units.get("authority") != "UNKNOWN_UNVERIFIED" or not isinstance(material, dict) or material.get("semantic_authority") != "UNKNOWN" or material.get("material_labels_used_for_science") is not False:
        raise VerificationError(f"{case_id}: source authority was overstated")
    if result.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError(f"{case_id}: scientific qualification is not UNKNOWN")
    boundary = result.get("claim_boundary")
    if not isinstance(boundary, dict) or any(boundary.get(key) != "UNKNOWN" for key in ("continuous_event_time", "native_exit_cause", "physical_fate", "legal_flux", "dynamical_impact")):
        raise VerificationError(f"{case_id}: physical boundary was overstated")
    return {"physical_case_id": case_id, "family_id": case.get("family_id"), "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT", "active_finite_status": status, "initial_mass_status": initial_mass["status"], "missing_fields": [field for field, state in field_status.items() if state != "PRESENT"], "unit_comparison": units.get("comparison"), "physical_ranges_diagnostic": True}


def verify(manifest_path_value: Path, report_path_value: Path, output_path_value: Path, *, allow_fixture_context: bool = False) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path_value, "manifest")
    report_path, report = read_json(report_path_value, "report")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT":
        raise VerificationError("manifest schema/status is not guarded-ready V2-compatible")
    fixture_context = manifest.get("test_only_fixture_context") is True
    if fixture_context and not allow_fixture_context:
        raise VerificationError("TEST_ONLY fixture requires explicit --allow-fixture-context")
    if allow_fixture_context and not fixture_context:
        raise VerificationError("--allow-fixture-context is only valid for a TEST_ONLY manifest")
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "COMPLETED_RAW_H5_FIELD_SCAN_NO_SCIENTIFIC_CREDIT":
        raise VerificationError("report schema/status is not a complete V3 no-credit scan")
    static, current = load_static_refs(manifest)
    report_manifest = report.get("manifest")
    if not isinstance(report_manifest, dict) or path_ref(report_manifest.get("path"), "report manifest") != manifest_path:
        raise VerificationError("report does not identify the supplied manifest")
    if digest(report_manifest.get("sha256"), "report manifest SHA") != stable_static_sha(manifest_path, "report manifest")[0]:
        raise VerificationError("report manifest SHA does not match supplied manifest")
    report_binding = report_manifest.get("current_binding")
    if not isinstance(report_binding, dict) or report_binding.get("path") != current["path"] or report_binding.get("sha256") != current["sha256"] or report_binding.get("manifest_path") != str(manifest_path) or report_binding.get("static_ref_count") != len(static):
        raise VerificationError("report current/static binding differs from manifest")
    cases = manifest.get("cases")
    results = report.get("case_results")
    counts = report.get("counts")
    if not isinstance(cases, list) or not isinstance(results, list) or not isinstance(counts, dict):
        raise VerificationError("manifest/report case collections are missing")
    case_ids = [case.get("physical_case_id") for case in cases if isinstance(case, dict)]
    result_ids = [result.get("physical_case_id") for result in results if isinstance(result, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids) or case_ids != result_ids:
        raise VerificationError("manifest/report case identity sequence differs")
    if counts != {"requested": len(cases), "completed": len(cases), "failed": 0} or report.get("failed_cases") != []:
        raise VerificationError("report counts do not reconcile")
    read_policy = report.get("read_policy")
    if not isinstance(read_policy, dict) or read_policy.get("trajectory_h5_opened_after_reservation") is not True or read_policy.get("raw_bi4_opened") is not False or read_policy.get("solver_started") is not False or read_policy.get("legacy_model_fields_used") is not False:
        raise VerificationError("report read policy is unsafe or incomplete")
    if report.get("scientific_qualification") != UNKNOWN_QUALIFICATION:
        raise VerificationError("top-level scientific qualification is not UNKNOWN")
    verified = [verify_case(case, result, static, {**current, "manifest_path": str(manifest_path)}) for case, result in zip(cases, results)]
    output = {
        "schema": "ds02.stage2.verify-scientific-field-h5-audit.v5",
        "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
        "manifest": {"path": str(manifest_path), "sha256": stable_static_sha(manifest_path, "output manifest")[0]},
        "report": {"path": str(report_path), "sha256": stable_static_sha(report_path, "output report")[0]},
        "case_count": len(verified), "cases": verified,
        # The verifier reads bounded JSON/source references to check their
        # identity.  It never opens or hashes a deferred scientific payload.
        "source_content_read_by_verifier": False,
        "bounded_metadata_content_read_by_verifier": True,
        "scientific_payload_content_read_by_verifier": False,
        "production_eligible": False, "scientific_credit": 0,
        "scientific_qualification": UNKNOWN_QUALIFICATION,
        "test_only_fixture_context": fixture_context,
        "claim_boundary": {"active_field_integrity": "bounded raw-HDF5 scan only", "physical_ranges": "diagnostic only; no gate", "units": "producer declaration versus protocol; authority UNKNOWN", "material_and_mk": "presence only; authority UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    output_path = output_path_value.expanduser().resolve()
    if output_path.exists():
        raise VerificationError(f"refusing to overwrite verifier output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise VerificationError("verifier output exceeds bounded size")
    output_path.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(output_path), "case_count": len(verified), "production_eligible": False, "scientific_credit": 0}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--manifest", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path, required=True)
    verify_parser.add_argument("--allow-fixture-context", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = verify(args.manifest, args.report, args.output, allow_fixture_context=args.allow_fixture_context)
    except (VerificationError, OSError) as exc:
        print(f"verify-scientific-field-h5-audit-v5: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
