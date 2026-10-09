#!/usr/bin/env python3
"""Verify the ROOT316 request with an additive static input closure.

The consumed ROOT316 verifier required ``input_records`` and ``input_files``
to be identical.  The root-forward normalizer legitimately adds eleven small
runtime/admission source files to ``input_files`` and ``input_sha256`` without
putting them in the producer's twenty-record ``input_records`` map.  This
version accepts that strict superset, verifies every added file's concrete
SHA/stat, and keeps all twelve native records deferred.  It never reads a VTK,
BI4, HDF5, or solver payload.  The original v1 verifier remains immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_four_sentinel_gencase_geometry_support_verify_v1.py"
V1_SPEC = importlib.util.spec_from_file_location("root316_geometry_support_verify_v1", V1_PATH)
if V1_SPEC is None or V1_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load ROOT316 v1 verifier: {V1_PATH}")
V1 = importlib.util.module_from_spec(V1_SPEC)
V1_SPEC.loader.exec_module(V1)

SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-output-verifier.v2"
STATIC_BYTES_CAP = 32 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu", ".hdf"}


class VerifyFailure(RuntimeError):
    pass


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerifyFailure(f"{label} is not a SHA-256 digest")
    lowered = value.lower()
    if any(char not in "0123456789abcdef" for char in lowered):
        raise VerifyFailure(f"{label} is not a hexadecimal SHA-256 digest")
    return lowered


def _stable_static(path: Path, expected_sha: str, label: str) -> dict[str, Any]:
    """Hash only an added bounded static closure entry, never a deferred payload."""
    path = V1._regular(path, label)
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise VerifyFailure(f"{label} is a deferred payload and cannot be added to static input_files")
    before = V1._stat(path)
    if before["bytes"] > STATIC_BYTES_CAP:
        raise VerifyFailure(f"{label} exceeds the bounded static closure cap")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = V1._stat(path)
    if before != after:
        raise VerifyFailure(f"{label} changed while hashing")
    actual_sha = digest.hexdigest()
    if actual_sha != _hex(expected_sha, f"{label} declared SHA"):
        raise VerifyFailure(f"{label} SHA differs from input_sha256")
    return {"path": str(path), "sha256": actual_sha, "stat": after, "payload_read": False}


def _verify_request_v2(
    request: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    manifest_record: dict[str, Any],
    deferred: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Verify v1's contract plus a strict static-input superset."""
    if request.get("schema") != V1.REQUEST_SCHEMA or request.get("variant_schema") != V1.WORKER_SCHEMA:
        raise VerifyFailure("request schema/variant mismatch")
    if request.get("status") != "READY_FOR_PARENT_GUARDED_VTK_SUPPORT" or request.get("parent_wrapper_required") is not True:
        raise VerifyFailure("request does not require the parent deferred-payload wrapper")
    if request.get("parent_v8_deferred_fields_not_credit") is not True:
        raise VerifyFailure("request does not disclose v8 deferred-field limits")
    command = request.get("command")
    if not isinstance(command, list) or "--run" not in command or "--manifest" not in command:
        raise VerifyFailure("request command is not an executable worker command")
    if not any(Path(str(item)).name == manifest_path.name for item in command):
        raise VerifyFailure("request command does not bind the supplied manifest")

    input_files = request.get("input_files")
    input_records = request.get("input_records")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or len(input_files) != len(set(input_files)):
        raise VerifyFailure("input_files must be a unique list")
    if not isinstance(input_records, dict) or not isinstance(input_sha, dict):
        raise VerifyFailure("request static input contract is incomplete")
    file_set = {str(item) for item in input_files}
    record_set = set(input_records)
    sha_set = set(input_sha)
    if not record_set <= file_set:
        raise VerifyFailure("input_records contains a path absent from input_files")
    if sha_set != file_set:
        raise VerifyFailure("input_sha256 must cover every input_files path exactly")

    manifest_key = str(V1._absolute(manifest_path))
    manifest_input = input_records.get(manifest_key)
    if not isinstance(manifest_input, dict) or manifest_input.get("sha256") != manifest_record.get("sha256"):
        raise VerifyFailure("request does not bind the exact supplied manifest SHA")
    for path, record in input_records.items():
        if not isinstance(record, dict) or record.get("path") != path:
            raise VerifyFailure(f"request input record path mismatch: {path}")
        declared = record.get("sha256")
        if isinstance(declared, str) and input_sha.get(path) != declared:
            raise VerifyFailure(f"request input SHA mismatch: {path}")

    deferred_rows = request.get("deferred_input_records")
    if not isinstance(deferred_rows, list) or len(deferred_rows) != 12:
        raise VerifyFailure("request must expose exactly 12 deferred payload records")
    deferred_paths = {str(record.get("path")) for record in deferred_rows if isinstance(record, dict)}
    if len(deferred_paths) != 12:
        raise VerifyFailure("deferred payload records must have twelve unique paths")
    if deferred_paths & file_set:
        raise VerifyFailure("deferred payload was promoted to parent input_files")
    observed: set[tuple[str, str]] = set()
    for record in deferred_rows:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise VerifyFailure("malformed deferred payload record")
        path = record["path"]
        matches = [(key, expected) for key, expected in deferred.items() if expected.get("path") == path]
        if len(matches) != 1:
            raise VerifyFailure(f"deferred record is not bound to the manifest: {path}")
        key, expected = matches[0]
        if key in observed:
            raise VerifyFailure(f"duplicate deferred record: {key}")
        observed.add(key)
        if V1._expected_stat(record) != V1._expected_stat(expected):
            raise VerifyFailure(f"deferred stat mismatch for {key}")
    if observed != set(deferred):
        raise VerifyFailure("request deferred records do not cover all VTK/BI4 bindings")

    # The eleven normalized additions are not trusted merely because their
    # digest appears in a JSON map.  They must be bounded non-payload files
    # and their current bytes must match the declared digest.
    extra = sorted(file_set - record_set)
    added: list[dict[str, Any]] = []
    for path in extra:
        added.append(_stable_static(Path(path), input_sha[path], f"added static input {path}"))

    request_cases = V1._case_map(request)
    manifest_cases = V1._case_map(manifest)
    for sid in V1.CASES:
        if request_cases[sid].get("continuous_owner") != manifest_cases[sid].get("continuous_owner"):
            raise VerifyFailure(f"request/manifest owner policy differs for {sid}")
    return {"recorded_static_inputs": len(record_set), "normalized_static_additions": added, "deferred_payloads": 12}


def verify_request_only(manifest_path: Path, request_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = V1._read_json(manifest_path, "support manifest")
    request, _ = V1._read_json(request_path, "support request")
    deferred = V1._verify_manifest(manifest, manifest_record)
    request_summary = _verify_request_v2(request, manifest, V1._absolute(manifest_path), manifest_record, deferred)
    result = {
        "schema": SCHEMA,
        "status": "VERIFIED_ROOT316_REQUEST_STATIC_SUPERSET_ONLY",
        "manifest": manifest_record,
        "request": {"path": str(V1._absolute(request_path)), "sha256": V1._read_json(request_path, "support request")[1]["sha256"]},
        "request_summary": request_summary,
        "payload_bindings": {"deferred_vtk": 8, "deferred_bi4": 4, "static_input_records": request_summary["recorded_static_inputs"], "production_payload_reopened_by_verifier": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "scope": {"vtk_bytes_read": False, "bi4_bytes_read": False, "hdf5_read": False, "solver_launch": False},
    }
    if verification_output is not None:
        _write_once(verification_output, result)
    return result


def verify(manifest_path: Path, request_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = V1._read_json(manifest_path, "support manifest")
    request, _ = V1._read_json(request_path, "support request")
    output, output_record = V1._read_json(output_path, "support worker output")
    deferred = V1._verify_manifest(manifest, manifest_record)
    request_summary = _verify_request_v2(request, manifest, V1._absolute(manifest_path), manifest_record, deferred)
    V1._verify_output(output, manifest, deferred)
    result = {
        "schema": SCHEMA,
        "status": "VERIFIED_ROOT316_WORKER_AND_STATIC_REQUEST_CONTRACT",
        "manifest": manifest_record,
        "request": {"path": str(V1._absolute(request_path)), "sha256": V1._read_json(request_path, "support request")[1]["sha256"]},
        "worker_output": output_record,
        "request_summary": request_summary,
        "payload_bindings": {"vtk": 8, "bi4_stat_only": 4, "static_input_records": request_summary["recorded_static_inputs"], "production_payload_reopened_by_verifier": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "scope": {"vtk_bytes_read": False, "bi4_bytes_read": False, "hdf5_read": False, "solver_launch": False},
    }
    if verification_output is not None:
        _write_once(verification_output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = V1._absolute(path)
    if path.exists() or path.is_symlink():
        raise VerifyFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def self_test() -> None:
    worker = V1._load_worker(HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py")
    with tempfile.TemporaryDirectory(prefix="root316-v2-verifier-") as td:
        root = Path(td)
        manifest_path, request_path, output_path = V1._fixture_request(root, worker)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        extra = root / "normalized-runtime.json"
        extra.write_text('{"runtime":"tiny"}\n', encoding="utf-8")
        extra_path = str(extra)
        extra_sha = hashlib.sha256(extra.read_bytes()).hexdigest()
        request["input_files"].append(extra_path)
        request["input_files"] = sorted(set(request["input_files"]))
        request["input_sha256"][extra_path] = extra_sha
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = verify(manifest_path, request_path, output_path)
        assert result["status"] == "VERIFIED_ROOT316_WORKER_AND_STATIC_REQUEST_CONTRACT"
        assert result["request_summary"]["normalized_static_additions"]

        missing = json.loads(request_path.read_text(encoding="utf-8"))
        missing["input_sha256"].pop(extra_path)
        bad_missing = root / "bad-missing.json"; bad_missing.write_text(json.dumps(missing), encoding="utf-8")
        try:
            verify_request_only(manifest_path, bad_missing)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("unbound added static input was accepted")

        promoted = json.loads(request_path.read_text(encoding="utf-8"))
        promoted["input_files"].append(promoted["deferred_input_records"][0]["path"])
        promoted["input_sha256"][promoted["deferred_input_records"][0]["path"]] = "0" * 64
        bad_promoted = root / "bad-promoted.json"; bad_promoted.write_text(json.dumps(promoted), encoding="utf-8")
        try:
            verify_request_only(manifest_path, bad_promoted)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("deferred payload was promoted to static input_files")
    print("PASS_FOUR_SENTINEL_GENCASE_SUPPORT_VERIFIER_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--verify-request", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.request is None:
        parser.error("--manifest and --request are required")
    try:
        if args.verify_request:
            result = verify_request_only(args.manifest, args.request, args.verification_output)
        else:
            if args.output is None:
                parser.error("--verify requires --output")
            result = verify(args.manifest, args.request, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_SUPPORT_VERIFIER_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "scientific_credit": 0, "scope": result["scope"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
