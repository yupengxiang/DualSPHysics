#!/usr/bin/env python3
"""Independent V5 admission verifier for seven V10 H5 pilot requests.

This verifier is intentionally independent of the preparer.  It re-reads
bounded JSON and source references, computes their SHA/stat pairs, and checks
the request/manifest/cost/closure contracts.  It performs ``stat(2)`` only on
the deferred HDF5 path: the HDF5 content SHA is a producer-known value and is
validated by the future parent/worker after reservation.  Therefore a PASS
from this command is metadata readiness only, with zero scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
INDEX_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-request-index.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-manifest.v10"
REQUEST_SCHEMA = "ds02.request.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-v5-verification.v1"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_STATIC_BYTES = 10 * 1024 * 1024
H5_SUFFIXES = {".h5", ".hdf5"}
PAYLOAD_SUFFIXES = H5_SUFFIXES | {
    ".bi4", ".obi4", ".ibi4", ".vtk", ".vtu", ".vtp", ".xmf",
    ".xdmf", ".csv", ".jsonl", ".npy", ".npz", ".raw", ".bin",
}
FAMILIES = {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
REQUIRED_RUNTIME_ROLES = {"runtime_v10_git_bound", "dispatch_v9", "strict_dispatch_v9", "official_config"}


class PilotVerificationError(ValueError):
    """An independent pilot request admission check failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PilotVerificationError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise PilotVerificationError(f"{label} is not hexadecimal")
    return value


def stat_signature(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PilotVerificationError(f"{label} is not a regular non-symlink file: {path}")
    value = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _same_stat(expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    for key in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if expected.get(key) != actual.get(key):
            raise PilotVerificationError(f"{label} differs at {key}")


def bounded_path(value: Any, label: str, *, max_bytes: int = MAX_STATIC_BYTES) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise PilotVerificationError(f"{label} lacks a path")
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise PilotVerificationError(f"{label} must not be a symlink: {raw}")
    path = raw.resolve()
    if not path.is_file():
        raise PilotVerificationError(f"{label} is missing: {path}")
    if path.stat().st_size > max_bytes:
        raise PilotVerificationError(f"{label} exceeds bounded size: {path}")
    return path


def read_json(value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    path = bounded_path(value, label, max_bytes=MAX_JSON_BYTES)
    before = stat_signature(path, label)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotVerificationError(f"{label} is invalid JSON") from exc
    after = stat_signature(path, label)
    _same_stat(before, after, f"{label} changed during read")
    if not isinstance(document, dict):
        raise PilotVerificationError(f"{label} must be an object")
    return path, document


def check_static_ref(ref: Any, label: str) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise PilotVerificationError(f"{label} is not an object")
    path = bounded_path(ref.get("path"), label)
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise PilotVerificationError(f"{label} is scientific payload input: {path}")
    expected = digest(ref.get("sha256"), f"{label} SHA")
    before = stat_signature(path, label)
    actual = sha256_file(path)
    after = stat_signature(path, label)
    _same_stat(before, after, f"{label} changed during hash")
    if actual != expected:
        raise PilotVerificationError(f"{label} content SHA differs")
    if ref.get("content_read_by_preparer") is not True:
        raise PilotVerificationError(f"{label} lacks bounded source-read attestation")
    return {**before, "sha256": expected, "role": ref.get("role")}


def check_deferred_h5(ref: Any, case_id: str) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise PilotVerificationError(f"{case_id}: deferred HDF5 record is missing")
    path = Path(ref.get("path", "")).expanduser()
    if path.is_symlink() or not path.is_file():
        raise PilotVerificationError(f"{case_id}: deferred HDF5 is not a regular non-symlink file")
    path = path.resolve()
    if path.suffix.lower() not in H5_SUFFIXES:
        raise PilotVerificationError(f"{case_id}: deferred source is not HDF5")
    actual = stat_signature(path, f"{case_id} deferred HDF5")
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if int(ref.get(key, -1)) != int(actual[key]):
            raise PilotVerificationError(f"{case_id}: deferred HDF5 stat differs at {key}")
    known = digest(ref.get("known_sha256"), f"{case_id} deferred known HDF5 SHA")
    if ref.get("content_read_by_preparer") is not False or ref.get("deferred_after_parent_reservation") is not True:
        raise PilotVerificationError(f"{case_id}: deferred HDF5 read policy is unsafe")
    # Deliberately no sha256_file(path) here.  The path may be multi-gigabyte.
    return {**actual, "known_sha256": known, "content_read_by_preparer": False}


def _ref_index(refs: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(refs, list) or not refs:
        raise PilotVerificationError(f"{label} is empty")
    result: dict[str, dict[str, Any]] = {}
    for index, ref in enumerate(refs):
        checked = check_static_ref(ref, f"{label}[{index}]")
        path = checked["path"]
        old = result.get(path)
        if old is not None and old["sha256"] != checked["sha256"]:
            raise PilotVerificationError(f"{label} contains conflicting SHA for {path}")
        result[path] = checked
    return result


def _require_ref_in_request(request: dict[str, Any], ref: dict[str, Any], label: str) -> None:
    path = str(Path(ref["path"]).resolve())
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or path not in input_files:
        raise PilotVerificationError(f"{label} is absent from request input_files")
    if not isinstance(input_sha, dict) or input_sha.get(path) != ref["sha256"]:
        raise PilotVerificationError(f"{label} SHA is absent or differs in request input_sha256")


def _verify_manifest(request_path: Path, request: dict[str, Any], manifest_path: Path, manifest: dict[str, Any], index_current: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_SINGLE_CASE_RAW_H5_FIELD_AUDIT":
        raise PilotVerificationError(f"{request_path}: manifest schema/status differs")
    scope = manifest.get("pilot_scope")
    if not isinstance(scope, dict) or scope.get("one_case_only") is not True:
        raise PilotVerificationError(f"{request_path}: manifest is not single-case")
    family = scope.get("family_id")
    case_id = scope.get("physical_case_id")
    if family not in FAMILIES or not isinstance(case_id, str):
        raise PilotVerificationError(f"{request_path}: manifest identity is incomplete")
    if request.get("family_id") != family or request.get("case_id") != case_id or request.get("physical_case_ids") != [case_id]:
        raise PilotVerificationError(f"{request_path}: request/manifest identity differs")
    current = manifest.get("current_catalog")
    if not isinstance(current, dict) or current.get("sha256") != CURRENT_SHA256:
        raise PilotVerificationError(f"{request_path}: manifest CURRENT is not the frozen catalog")
    if current.get("path") != index_current.get("path"):
        raise PilotVerificationError(f"{request_path}: manifest CURRENT path differs from index")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict) or cases[0].get("physical_case_id") != case_id:
        raise PilotVerificationError(f"{request_path}: manifest case collection is not one exact case")
    case = cases[0]
    h5 = check_deferred_h5(case.get("trajectory_h5"), case_id)
    status = case.get("case_manifest_status")
    if status not in {"BOUND", "UNKNOWN_MISSING_MANIFEST", "NOT_EXPOSED_BY_PRODUCER"}:
        raise PilotVerificationError(f"{case_id}: invalid case manifest status")
    if status == "BOUND" and not isinstance(case.get("case_manifest"), dict):
        raise PilotVerificationError(f"{case_id}: BOUND case lacks case_manifest")
    if status != "BOUND" and case.get("case_manifest") is not None:
        raise PilotVerificationError(f"{case_id}: unknown case manifest must not bind an actionable file")
    refs = _ref_index(manifest.get("static_source_refs"), f"{case_id} manifest static refs")
    for ref in refs.values():
        _require_ref_in_request(request, ref, f"{case_id} static source {ref['path']}")
    manifest_ref = request.get("manifest_contract")
    if not isinstance(manifest_ref, dict) or Path(manifest_ref.get("path", "")).resolve() != manifest_path:
        raise PilotVerificationError(f"{case_id}: manifest_contract path differs")
    if digest(manifest_ref.get("sha256"), f"{case_id} manifest contract SHA") != sha256_file(manifest_path):
        raise PilotVerificationError(f"{case_id}: manifest_contract SHA differs")
    return {"family_id": family, "physical_case_id": case_id, "case_manifest_status": status, "deferred_h5": h5, "static_ref_count": len(refs)}


def _verify_request(request_path: Path, index_current: dict[str, Any]) -> dict[str, Any]:
    _, request = read_json(request_path, f"pilot request {request_path}")
    if request.get("schema") != REQUEST_SCHEMA or request.get("status") != "SOURCE_PREPARED_SINGLE_CASE_V10_NOT_RUN":
        raise PilotVerificationError(f"{request_path}: request schema/status differs")
    if request.get("scientific_credit") != 0 or request.get("launch_owner") != "root" or request.get("shared_lease_required") is not True:
        raise PilotVerificationError(f"{request_path}: claim/ownership boundary differs")
    command = request.get("command")
    binding = request.get("interpreter_binding")
    if not isinstance(command, list) or len(command) < 8 or not isinstance(binding, dict):
        raise PilotVerificationError(f"{request_path}: executable command/binding is incomplete")
    literal = binding.get("literal_path")
    if not isinstance(literal, str) or not literal.endswith("/.venv/bin/python") or command[0] != literal:
        raise PilotVerificationError(f"{request_path}: literal pinned venv argv[0] differs")
    resolved = Path(binding.get("resolved_path", "")).expanduser()
    if not resolved.is_file() or digest(binding.get("sha256"), f"{request_path} Python SHA") != sha256_file(resolved):
        raise PilotVerificationError(f"{request_path}: interpreter binding is not stable")
    if command[1:2] != ["-B"] or command[3] != "audit" or "--manifest" not in command or "--output" not in command:
        raise PilotVerificationError(f"{request_path}: command does not use the bounded audit entrypoint")
    deferred = request.get("deferred_input_files")
    if not isinstance(deferred, list) or len(deferred) != 1:
        raise PilotVerificationError(f"{request_path}: request must defer exactly one HDF5")
    for value in request.get("input_files", []):
        if Path(value).suffix.lower() in PAYLOAD_SUFFIXES:
            raise PilotVerificationError(f"{request_path}: payload leaked into static input_files")
    runtime = request.get("runtime_binding")
    if not isinstance(runtime, dict) or set(runtime) != REQUIRED_RUNTIME_ROLES:
        raise PilotVerificationError(f"{request_path}: V10 runtime closure is incomplete")
    for role, ref in runtime.items():
        checked = check_static_ref(ref, f"{request_path} runtime {role}")
        _require_ref_in_request(request, checked, f"{request_path} runtime {role}")
    storage = request.get("storage_scope")
    cost = request.get("source_read_cost")
    if not isinstance(storage, dict) or not isinstance(cost, dict):
        raise PilotVerificationError(f"{request_path}: storage/read cost contract is missing")
    h5_bytes = int(cost.get("deferred_h5_bytes", -1))
    if h5_bytes <= 0 or int(cost.get("minimum_h5_passes", 0)) < 3:
        raise PilotVerificationError(f"{request_path}: deferred HDF5 cost is underdeclared")
    if int(cost.get("estimated_h5_read_bytes", 0)) < h5_bytes * 3:
        raise PilotVerificationError(f"{request_path}: HDF5 read estimate is underdeclared")
    if int(storage.get("estimated_storage_bytes", 0)) != int(storage.get("home_storage_bytes", -1)) + int(storage.get("external_storage_bytes", -1)):
        raise PilotVerificationError(f"{request_path}: split storage does not reconcile")
    if int(storage.get("external_storage_bytes", 0)) < int(cost["estimated_h5_read_bytes"]) + 512 * 1024 * 1024:
        raise PilotVerificationError(f"{request_path}: external HDF5/scratch storage is underdeclared")
    if not isinstance(request.get("max_wall_seconds"), int) or request["max_wall_seconds"] <= 0:
        raise PilotVerificationError(f"{request_path}: wall deadline is not finite")
    if not isinstance(request.get("max_memory_bytes"), int) or request["max_memory_bytes"] <= 0:
        raise PilotVerificationError(f"{request_path}: memory budget is invalid")
    manifest_path = Path(request["manifest_contract"]["path"]).expanduser().resolve()
    _, manifest = read_json(manifest_path, f"{request_path} manifest")
    result = _verify_manifest(request_path, request, manifest_path, manifest, index_current)
    result.update({"request_path": str(request_path), "request_sha256": sha256_file(request_path), "max_wall_seconds": request["max_wall_seconds"], "max_memory_bytes": request["max_memory_bytes"], "estimated_storage_bytes": storage["estimated_storage_bytes"]})
    return result


def verify(index_path_value: Path, output_path_value: Path) -> dict[str, Any]:
    index_path, index = read_json(index_path_value, "pilot V10 request index")
    if index.get("schema") != INDEX_SCHEMA or index.get("status") != "SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10_NOT_RUN":
        raise PilotVerificationError("pilot index schema/status differs")
    current = index.get("current_binding")
    if not isinstance(current, dict) or current.get("sha256") != CURRENT_SHA256:
        raise PilotVerificationError("pilot index CURRENT binding differs")
    current_path = bounded_path(current.get("path"), "index CURRENT")
    if sha256_file(current_path) != CURRENT_SHA256:
        raise PilotVerificationError("index CURRENT content differs")
    rows = index.get("requests")
    if not isinstance(rows, list) or len(rows) != 7:
        raise PilotVerificationError("pilot index must contain seven request rows")
    seen: set[str] = set()
    verified: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("family_id") not in FAMILIES or row["family_id"] in seen:
            raise PilotVerificationError("pilot index has duplicate or invalid family")
        seen.add(row["family_id"])
        request_ref = row.get("request")
        if not isinstance(request_ref, dict):
            raise PilotVerificationError(f"{row['family_id']}: request ref missing")
        request_path = bounded_path(request_ref.get("path"), f"{row['family_id']} request")
        expected_request_sha = digest(request_ref.get("sha256"), f"{row['family_id']} request SHA")
        if sha256_file(request_path) != expected_request_sha:
            raise PilotVerificationError(f"{row['family_id']}: request file SHA differs")
        item = _verify_request(request_path, {**current, "path": str(current_path)})
        if item["family_id"] != row["family_id"] or item["physical_case_id"] != row.get("physical_case_id"):
            raise PilotVerificationError(f"{row['family_id']}: index/request identity differs")
        verified.append(item)
    if seen != FAMILIES:
        raise PilotVerificationError("pilot index does not cover F1..F7")
    output = {
        "schema": REPORT_SCHEMA,
        "status": "VERIFIED_SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10",
        "index": {"path": str(index_path), "sha256": sha256_file(index_path)},
        "case_count": len(verified), "cases": verified,
        "runtime_version": "v10_git_bound",
        "source_content_read_by_verifier": True,
        "trajectory_h5_content_read_by_verifier": False,
        "production_eligible": False, "scientific_credit": 0,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "claim_boundary": {"single_case_request_contract": "metadata only", "deferred_h5": "parent reservation and post-read SHA/stat required", "F2_H10_missing_manifest": "isolated UNKNOWN when present", "scientific_product": "not produced"},
    }
    output_path = output_path_value.expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise PilotVerificationError(f"refusing to overwrite verifier output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
        raise PilotVerificationError("verification output exceeds bounded size")
    output_path.write_text(encoded, encoding="utf-8")
    return {"status": output["status"], "output": str(output_path), "output_sha256": sha256_file(output_path), "case_count": 7, "production_eligible": False, "scientific_credit": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.index, args.output)
    except (PilotVerificationError, OSError) as exc:
        print(f"scientific-field-h5-pilot-v10-verify-v5: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
