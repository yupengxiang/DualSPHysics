#!/usr/bin/env python3
"""Verify the real V3 seven-family H5 audit requests.

This is an additive successor to ``verify_v6``.  V6 remains immutable and
continues to describe the old four-role pilot contract.  The V3 preparer uses
the real ``scientific-field-h5-audit-manifest.v2`` worker contract and binds
the complete eleven-role runtime closure.  This verifier delegates the
bounded JSON/stat, deferred-HDF5, cost, and serial-reservation checks to V6
with those constants changed, then adds the V3-specific worker and source
closure checks.  A successful result is still metadata readiness only: it
does not read or hash a scientific HDF5 and grants no scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
_BASE_PATH = SCRIPT.with_name("ds_data02_stage2_scientific_field_h5_pilot_v10_verify_v6.py")
_BASE_SPEC = importlib.util.spec_from_file_location("ds02_h5_pilot_verify_v6_for_v7", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:  # pragma: no cover - import failure is fatal
    raise ImportError(f"cannot load immutable V6 verifier: {_BASE_PATH}")
BASE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(BASE)


INDEX_SCHEMA = BASE.INDEX_SCHEMA
REQUEST_SCHEMA = BASE.REQUEST_SCHEMA
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-h5-audit-manifest.v2"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-v7-verification.v1"
INDEX_STATUS = "SOURCE_PREPARED_SEVEN_SINGLE_CASE_V10_NOT_RUN"
REQUEST_STATUS = "SOURCE_PREPARED_SINGLE_CASE_V10_NOT_RUN"
MANIFEST_STATUS = "READY_FOR_GUARDED_RAW_H5_FIELD_AUDIT"
REQUIRED_RUNTIME_ROLES = frozenset(
    {
        "runtime_v10_git_bound",
        "runtime_v9_git_bound",
        "runtime_v8",
        "runtime_v6",
        "runtime_v2",
        "git_snapshot_v1",
        "git_snapshot_v2",
        "git_snapshot_v3",
        "dispatch_v9",
        "strict_dispatch_v9",
        "official_runtime_config",
    }
)
REQUIRED_SOURCE_CONTRACT_ROLES = ("source_manifest", "pilot_index", "plan", "registry")
V3_WORKER_CONTRACT = {
    "worker_version": "v3_vectorized_postread_guard",
    "sequential_cases": True,
    "bounded_memory": True,
    "required_static_datasets": ("time", "particle_id", "particle_zone", "initial_type", "initial_mass"),
    "required_frame_datasets": ("position", "velocity", "density", "mass", "pressure", "valid", "type"),
    "post_guard": "final HDF5 stat/hash after all deferred datasets are read",
    "source_h5_storage": "reused_in_place; no source copy in attempt namespace",
    "temporary_copy_bytes": 0,
    "persistent_scratch_bytes": 0,
    "aggregate_output_only": True,
}


class PilotVerificationV7Error(ValueError):
    """The real V3 pilot source contract is not admissible."""


def _digest(value: Any, label: str) -> str:
    try:
        return BASE.digest(value, label)
    except Exception as exc:
        raise PilotVerificationV7Error(str(exc)) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, label: str) -> Path:
    try:
        return BASE.bounded_path(value, label)
    except Exception as exc:
        raise PilotVerificationV7Error(str(exc)) from exc


def _read_request(request_path: Path) -> dict[str, Any]:
    try:
        _, value = BASE.read_json(request_path, f"pilot V7 request {request_path}")
    except Exception as exc:
        raise PilotVerificationV7Error(str(exc)) from exc
    return value


def _require_bound_ref(request: dict[str, Any], ref: Any, label: str) -> None:
    if not isinstance(ref, dict):
        raise PilotVerificationV7Error(f"{label} is not an object")
    try:
        ref_path = str(Path(ref["path"]).expanduser().resolve())
    except (KeyError, OSError, TypeError) as exc:
        raise PilotVerificationV7Error(f"{label} lacks a usable path") from exc
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or ref_path not in input_files:
        raise PilotVerificationV7Error(f"{label} is absent from input_files")
    if not isinstance(input_sha, dict) or input_sha.get(ref_path) != ref.get("sha256"):
        raise PilotVerificationV7Error(f"{label} SHA is absent or differs in input_sha256")
    if ref.get("content_read_by_preparer") is not True:
        raise PilotVerificationV7Error(f"{label} lacks bounded source-read attestation")


def _verify_v3_manifest(
    request_path: Path,
    request: dict[str, Any],
    manifest_path: Path,
    manifest: dict[str, Any],
    index_current: dict[str, Any],
) -> dict[str, Any]:
    # BASE._verify_manifest is run with V7 constants below.  It supplies all
    # of the immutable identity, CURRENT, deferred-HDF5, static-ref and
    # manifest-file checks from the consumed V6 verifier.
    # V6 hard-coded the obsolete manifest status inside its immutable helper.
    # Give that helper an equivalent private view for the checks it owns, then
    # validate the real V3 status below.  The on-disk manifest is never
    # modified and the V3-specific checks still see the original document.
    base_manifest = dict(manifest)
    base_manifest["status"] = "READY_FOR_GUARDED_SINGLE_CASE_RAW_H5_FIELD_AUDIT"
    result = _ORIGINAL_MANIFEST(request_path, request, manifest_path, base_manifest, index_current)

    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != MANIFEST_STATUS:
        raise PilotVerificationV7Error(f"{request_path}: manifest schema/status differs")

    source_contract = manifest.get("source_contract")
    if not isinstance(source_contract, dict):
        raise PilotVerificationV7Error(f"{request_path}: V3 source_contract is missing")
    for role in REQUIRED_SOURCE_CONTRACT_ROLES:
        _require_bound_ref(request, source_contract.get(role), f"{request_path} source_contract.{role}")

    worker_contract = manifest.get("worker_contract")
    if not isinstance(worker_contract, dict):
        raise PilotVerificationV7Error(f"{request_path}: V3 worker_contract is missing")
    for key, expected in V3_WORKER_CONTRACT.items():
        actual = worker_contract.get(key)
        if isinstance(expected, tuple):
            if tuple(actual or ()) != expected:
                raise PilotVerificationV7Error(f"{request_path}: worker_contract.{key} differs")
        elif actual != expected:
            raise PilotVerificationV7Error(f"{request_path}: worker_contract.{key} differs")

    read_policy = manifest.get("read_policy")
    if not isinstance(read_policy, dict):
        raise PilotVerificationV7Error(f"{request_path}: V3 read_policy is missing")
    expected_policy = {
        "prepare_json_and_stat_only": True,
        "trajectory_h5_opened_by_preparer": False,
        "trajectory_h5_hashed_by_preparer": False,
        "trajectory_h5_opened_after_parent_reservation": True,
        "raw_bi4_opened": False,
        "solver_started": False,
    }
    for key, expected in expected_policy.items():
        if read_policy.get(key) is not expected:
            raise PilotVerificationV7Error(f"{request_path}: read_policy.{key} is unsafe")

    scope = manifest.get("pilot_scope")
    if not isinstance(scope, dict) or scope.get("historical_alias_excluded") is not True:
        raise PilotVerificationV7Error(f"{request_path}: historical aliases are not excluded")
    return result


def _verify_v3_request(request_path: Path, index_current: dict[str, Any]) -> dict[str, Any]:
    result = _ORIGINAL_REQUEST(request_path, index_current)
    request = _read_request(request_path)
    if request.get("cpu_task_kind") != "audit":
        raise PilotVerificationV7Error(f"{request_path}: real V3 cpu_task_kind must be audit")
    runtime = request.get("runtime_binding")
    if not isinstance(runtime, dict) or frozenset(runtime) != REQUIRED_RUNTIME_ROLES:
        raise PilotVerificationV7Error(f"{request_path}: complete V3 runtime closure is not bound")
    for role in sorted(REQUIRED_RUNTIME_ROLES):
        ref = runtime.get(role)
        _require_bound_ref(request, ref, f"{request_path} runtime {role}")
        if ref.get("role") != role:
            raise PilotVerificationV7Error(f"{request_path}: runtime role label mismatch for {role}")

    manifest_contract = request.get("manifest_contract")
    if not isinstance(manifest_contract, dict):
        raise PilotVerificationV7Error(f"{request_path}: manifest_contract is missing")
    manifest_path = _path(manifest_contract.get("path"), f"{request_path} manifest")
    try:
        _, manifest = BASE.read_json(manifest_path, f"{request_path} manifest")
    except Exception as exc:
        raise PilotVerificationV7Error(str(exc)) from exc
    source_contract = manifest.get("source_contract")
    if not isinstance(source_contract, dict):
        raise PilotVerificationV7Error(f"{request_path}: manifest source_contract is missing")
    for role in REQUIRED_SOURCE_CONTRACT_ROLES:
        _require_bound_ref(request, source_contract.get(role), f"{request_path} source_contract.{role}")
    if request.get("execution_allowed") is not True or request.get("launch_allowed") is not True:
        raise PilotVerificationV7Error(f"{request_path}: launch/execution boundary is not explicit")
    if request.get("claim_boundary", {}).get("scientific_credit") != 0:
        raise PilotVerificationV7Error(f"{request_path}: V3 request carries scientific credit")
    result["runtime_role_count"] = len(runtime)
    result["runtime_roles"] = sorted(runtime)
    result["worker_manifest_schema"] = manifest.get("schema")
    result["worker_manifest_status"] = manifest.get("status")
    return result


# The immutable V6 implementation calls these functions through its module
# globals.  Save the originals and install the strict V7 adapters only while a
# verification is running; this keeps the imported V6 source byte-for-byte
# unchanged and avoids a recursive call from the adapters.
_ORIGINAL_MANIFEST = BASE._verify_manifest
_ORIGINAL_REQUEST = BASE._verify_request


def verify(index_path: Path, output_path: Path) -> dict[str, Any]:
    old_values = {
        "MANIFEST_SCHEMA": BASE.MANIFEST_SCHEMA,
        "REPORT_SCHEMA": BASE.REPORT_SCHEMA,
        "REQUIRED_RUNTIME_ROLES": BASE.REQUIRED_RUNTIME_ROLES,
        "_verify_manifest": BASE._verify_manifest,
        "_verify_request": BASE._verify_request,
    }
    temporary = output_path.with_name(f".{output_path.name}.{__import__('os').getpid()}.v6-base")
    try:
        BASE.MANIFEST_SCHEMA = MANIFEST_SCHEMA
        BASE.REPORT_SCHEMA = REPORT_SCHEMA
        BASE.REQUIRED_RUNTIME_ROLES = set(REQUIRED_RUNTIME_ROLES)
        BASE._verify_manifest = _verify_v3_manifest
        BASE._verify_request = _verify_v3_request
        try:
            BASE.verify(index_path, temporary)
        except Exception as exc:
            if isinstance(exc, PilotVerificationV7Error):
                raise
            raise PilotVerificationV7Error(str(exc)) from exc
        try:
            report = json.loads(temporary.read_text(encoding="utf-8"))
        finally:
            temporary.unlink(missing_ok=True)
        report["schema"] = REPORT_SCHEMA
        report["status"] = "VERIFIED_SOURCE_PREPARED_SEVEN_SINGLE_CASE_V3_NOT_RUN"
        report["runtime_version"] = "v10_git_bound_v3_worker_contract"
        report["runtime_roles"] = sorted(REQUIRED_RUNTIME_ROLES)
        report["worker_manifest_schema"] = MANIFEST_SCHEMA
        report["worker_manifest_status"] = MANIFEST_STATUS
        report["production_eligible"] = False
        report["scientific_credit"] = 0
        report["claim_boundary"] = {
            **dict(report.get("claim_boundary") or {}),
            "real_v3_manifest_and_runtime_closure": "verified metadata only",
            "deferred_h5": "parent reservation and post-read SHA/stat required",
            "scientific_product": "not produced",
        }
        output_path = output_path.expanduser().resolve()
        if output_path.exists() or output_path.is_symlink():
            raise PilotVerificationV7Error(f"refusing to overwrite verifier output: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise PilotVerificationV7Error("V7 verification output exceeds bounded size")
        output_path.write_text(encoded, encoding="utf-8")
        return {
            "status": report["status"],
            "output": str(output_path),
            "output_sha256": _sha256(output_path),
            "case_count": 7,
            "runtime_role_count": len(REQUIRED_RUNTIME_ROLES),
            "production_eligible": False,
            "scientific_credit": 0,
        }
    finally:
        temporary.unlink(missing_ok=True)
        for key, value in old_values.items():
            setattr(BASE, key, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify(args.index, args.output)
    except (PilotVerificationV7Error, OSError) as exc:
        print(f"scientific-field-h5-pilot-v10-verify-v7: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
