#!/usr/bin/env python3
"""Build the additive ROOT207 stat-rebound request.

ROOT204 was stopped before the native decoder because its V4 manifest kept
the agent checkout's stat for ``axis_authority.source_records``.  This builder
creates a new manifest/request and leaves every ROOT204 byte untouched.  Each
axis source is read only as a small source file: the primary path must have
the same SHA256 and byte count as the old record before its fresh stat is
bound.  A changed source produces a blocked, non-runnable request when
``--allow-blocked`` is requested; it is never silently reclassified.

The 25 deferred native records are copied as metadata only.  This builder
does not open, hash, or stat a native Part/VTK/H5 payload.  The parent guard
and the immutable V4 child wrapper retain responsibility for those records.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from stage2_f1_native_selected_observer_axis_stat_rebind_v1 import (
    FORBIDDEN_SUFFIXES,
    MAX_SOURCE_BYTES,
    RebindFailure,
    _stat_dict,
    _stable_sha_stat,
    rebind_axis_source_records,
)


REQUEST_SCHEMA = "ds02.request.v1"
V4_VARIANT = "ds02.stage2.f1.native-selected-observer-request.v4"
V5_VARIANT = "ds02.stage2.f1.native-selected-observer-request.v5-root207"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
OLD_REFERENCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics")
REFERENCE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUESTS = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
WRAPPER = REFERENCE / "stage2_f1_native_selected_observer_guarded_v4.py"
V1_WORKER = REFERENCE / "stage2_f1_native_selected_observer_v1.py"
V1_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v1.py"
V1_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v1.json"
V2_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v2.py"
V2_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v2.json"
V4_BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v4.py"
V4_CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v4.json"
V4_STATUS = REFERENCE / "stage2_f1_native_selected_observer_v3_launch_status_v4.json"
BASE_OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
AXIS_REBINDER = REFERENCE / "stage2_f1_native_selected_observer_axis_stat_rebind_v1.py"
BUILDER = REFERENCE / "stage2_f1_native_selected_observer_request_v5_root207.py"
CONTRACT = REFERENCE / "stage2_f1_native_selected_observer_contract_v5_root207.json"
RUNTIME = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNNER = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_GUARD = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
DEFAULT_V4_REQUEST = REQUESTS / "f1-native-selected-observer-v4-root-forward-204-001.json"
DEFAULT_FAILURE_PROOF = PRIMARY / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "F1_NATIVE_SELECTED_OBSERVER_V4_ACTUAL_SOURCE_MTIME_FAILURE_ROOT_VERIFICATION_204.json"
)
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 10 * 1024 * 1024
DEFERRED_COUNT = 25


class BuildFailure(RuntimeError):
    pass


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _remap(value: Any) -> Any:
    if isinstance(value, str):
        old = str(OLD_REFERENCE)
        if value == old:
            return str(PRIMARY)
        prefix = old + os.sep
        if value.startswith(prefix):
            return str(PRIMARY / value[len(prefix) :])
        return value
    if isinstance(value, list):
        return [_remap(item) for item in value]
    if isinstance(value, dict):
        return {key: _remap(item) for key, item in value.items()}
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise BuildFailure(f"{label} exceeds the metadata read limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BuildFailure(f"{label} is not a SHA256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise BuildFailure(f"{label} is not hexadecimal") from exc
    return value.lower()


def _small_record(path: Path, label: str) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BuildFailure(f"{label} is a native payload: {path}")
    try:
        digest, stat_value = _stable_sha_stat(path, label)
    except RebindFailure as exc:
        raise BuildFailure(str(exc)) from exc
    return {
        "path": str(path),
        "label": label,
        "bytes": stat_value["bytes"],
        "mtime_ns": stat_value["mtime_ns"],
        "ctime_ns": stat_value["ctime_ns"],
        "device": stat_value["device"],
        "inode": stat_value["inode"],
        "sha256": digest,
        "content_scope": "small_source_hashed_by_root207_builder",
    }


def _write_once(path: Path, value: Any) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _proof_dependency(path: Path) -> dict[str, Any]:
    path = _path(path)
    result: dict[str, Any] = {"path": str(path), "available": path.is_file() and not path.is_symlink()}
    if not result["available"]:
        return result
    record = _small_record(path, "ROOT204 failure proof")
    result.update({key: record[key] for key in ("bytes", "mtime_ns", "ctime_ns", "device", "inode", "sha256")})
    result["content_scope"] = "small_failure_proof_only"
    return result


def _closure_paths(v4: dict[str, Any], v4_path: Path, v4_manifest: Path, new_manifest: Path, proof: Path) -> list[Path]:
    values: list[Path] = []
    for raw in v4.get("input_files", []):
        if not isinstance(raw, str):
            raise BuildFailure("V4 input_files contains a non-string")
        values.append(_path(_remap(raw)))
    values.extend(
        [
            v4_path,
            v4_manifest,
            new_manifest,
            proof,
            WRAPPER,
            V1_WORKER,
            V1_BUILDER,
            V1_CONTRACT,
            V2_BUILDER,
            V2_CONTRACT,
            V4_BUILDER,
            V4_CONTRACT,
            V4_STATUS,
            BASE_OBSERVER,
            AXIS_REBINDER,
            BUILDER,
            CONTRACT,
            RUNTIME,
            RUNNER,
            STRICT_GUARD,
            PYVENV,
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for value in values:
        value = _path(value)
        if str(value) in seen:
            continue
        seen.add(str(value))
        unique.append(value)
    return unique


def _expected_hashes(v4: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    raw = v4.get("input_sha256", {})
    if not isinstance(raw, dict):
        raise BuildFailure("V4 input_sha256 is not an object")
    for key, value in raw.items():
        if not isinstance(key, str):
            raise BuildFailure("V4 input_sha256 has a non-string path")
        result[str(_path(_remap(key)))] = _hex(value, f"V4 input SHA {key}")
    return result


def _collect_closure(v4: dict[str, Any], v4_path: Path, v4_manifest: Path, new_manifest: Path, proof: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    expected = _expected_hashes(v4)
    records: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    bytes_read = 0
    for path in _closure_paths(v4, v4_path, v4_manifest, new_manifest, proof):
        # The new manifest is written atomically immediately after the
        # pre-write closure check.  It cannot be fingerprinted until then.
        if path == _path(new_manifest):
            continue
        if not path.exists():
            issues.append({"kind": "missing_closure_file", "path": str(path)})
            continue
        try:
            record = _small_record(path, "ROOT207 source closure")
        except BuildFailure as exc:
            issues.append({"kind": "closure_failure", "path": str(path), "message": str(exc)})
            continue
        bytes_read += int(record["bytes"])
        expected_sha = expected.get(str(path))
        if expected_sha is not None and expected_sha != record["sha256"]:
            issues.append(
                {
                    "kind": "inherited_v4_sha_mismatch",
                    "path": str(path),
                    "expected_sha256": expected_sha,
                    "actual_sha256": record["sha256"],
                }
            )
        records[str(path)] = record
    if bytes_read > MAX_METADATA_BYTES:
        issues.append({"kind": "metadata_read_limit", "bytes": bytes_read, "limit": MAX_METADATA_BYTES})
    return records, issues, bytes_read


def _deferred_metadata(v4: dict[str, Any]) -> dict[str, Any]:
    raw = v4.get("deferred_input_records")
    if not isinstance(raw, dict) or len(raw) != DEFERRED_COUNT:
        raise BuildFailure("V4 request does not carry exactly 25 deferred native records")
    # Copy metadata only.  No existence, stat, or content operation is done
    # for these payload paths during source preparation.
    result = deepcopy(raw)
    for key, record in result.items():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise BuildFailure(f"deferred record {key!r} is malformed")
        if Path(record["path"]).suffix.lower() != ".bi4":
            raise BuildFailure(f"deferred record {key!r} is not a BI4 metadata record")
    return result


def build(
    v4_request_path: Path,
    *,
    output_request: Path,
    case_id: str,
    attempt_id: str,
    failure_proof_path: Path,
    allow_blocked: bool,
) -> dict[str, Any]:
    v4_path = _path(v4_request_path)
    v4 = _remap(_read_json(v4_path, "ROOT204 V4 request"))
    if v4.get("schema") != REQUEST_SCHEMA or v4.get("variant_schema") != V4_VARIANT:
        raise BuildFailure("input is not the immutable ROOT204 V4 request")
    manifest_obj = v4.get("manifest")
    if not isinstance(manifest_obj, dict) or not isinstance(manifest_obj.get("path"), str):
        raise BuildFailure("ROOT204 V4 request has no manifest path")
    v4_manifest_path = _path(_remap(manifest_obj["path"]))
    v4_manifest = _read_json(v4_manifest_path, "ROOT204 V4 manifest")
    if v4_manifest.get("schema") != MANIFEST_SCHEMA:
        raise BuildFailure(f"ROOT204 manifest schema is {v4_manifest.get('schema')!r}, expected V2")

    deferred = _deferred_metadata(v4)
    try:
        rebound_manifest, rebind_report = rebind_axis_source_records(
            v4_manifest,
            primary_root=PRIMARY,
            old_reference_root=OLD_REFERENCE,
            allow_blocked=allow_blocked,
        )
    except RebindFailure as exc:
        raise BuildFailure(str(exc)) from exc

    output_request = _path(output_request)
    new_manifest_path = output_request.parent / "manifest.json"
    failure_dependency = _proof_dependency(failure_proof_path)
    if not failure_dependency.get("available"):
        rebind_report.setdefault("blocking_dependencies", []).append("ROOT204 failure proof is missing")
    rebound_manifest["root207_source_binding"] = {
        "schema": "ds02.stage2.f1.native-selected-observer-root207-source-binding.v1",
        "old_root204_request": str(v4_path),
        "old_root204_manifest": str(v4_manifest_path),
        "old_root204_failure_proof": failure_dependency,
        "transition": "STAT_ONLY_AXIS_SOURCE_REBIND",
        "content_sha_and_bytes_must_match": True,
        "science_authority_replaced": False,
        "production_native_payload_read": False,
    }
    rebound_manifest["root207_axis_stat_rebind"] = rebind_report
    if failure_dependency.get("available") is not True:
        rebind_report["status"] = "BLOCKED_MISSING_ROOT204_FAILURE_PROOF"
        rebind_report["admission"] = "BLOCKED"
    if rebind_report.get("status") != "PASS_STAT_ONLY_REBIND" or failure_dependency.get("available") is not True:
        rebound_manifest["status"] = "BLOCKED_ROOT207_AXIS_STAT_REBIND_DEPENDENCY"

    records, issues, metadata_bytes = _collect_closure(v4, v4_path, v4_manifest_path, new_manifest_path, failure_proof_path)
    if not failure_dependency.get("available"):
        issues.append({"kind": "missing_root204_failure_proof", "path": str(failure_proof_path)})
    if rebind_report.get("content_mismatch_count", 0):
        issues.append({"kind": "axis_content_mismatch", "count": rebind_report["content_mismatch_count"]})
    if issues and not allow_blocked:
        raise BuildFailure(json.dumps({"root207_blockers": issues}, sort_keys=True))

    # The new manifest is the only new file that must be written before its
    # own source record can be added to the request closure.
    _write_once(new_manifest_path, rebound_manifest)
    manifest_record = _small_record(new_manifest_path, "ROOT207 manifest")
    records[str(new_manifest_path)] = manifest_record
    input_files = sorted(records)
    if any(Path(path).suffix.lower() in FORBIDDEN_SUFFIXES for path in input_files):
        raise BuildFailure("native payload leaked into ROOT207 input_files")

    blocked = bool(issues) or rebind_report.get("status") != "PASS_STAT_ONLY_REBIND"
    status = (
        "BLOCKED_ROOT207_AXIS_STAT_REBIND_DEPENDENCY"
        if blocked
        else "READY_FOR_PARENT_GUARD_SOURCE_BOUND_NATIVE_SELECTED_OBSERVER_ROOT207"
    )
    command = [
        str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")),
        str(WRAPPER),
        "--run",
        "--manifest",
        str(new_manifest_path),
        "--attempt-root",
        "{attempt_root}",
        "--output",
        "{attempt_root}/observer/f1_native_selected_observer_v4.json",
        "--v1-worker",
        str(V1_WORKER),
        "--python",
        str(PYTHON),
        "--cwd",
        str(PRIMARY),
        "--max-scratch-bytes",
        str(256 * 1024 * 1024),
        "--max-log-bytes",
        str(1024 * 1024),
        "--timeout-seconds",
        "1800",
    ]
    request = deepcopy(v4)
    request.update(
        {
            "schema": REQUEST_SCHEMA,
            "variant_schema": V5_VARIANT,
            "status": status,
            "case_id": case_id,
            "attempt_id": attempt_id,
            "cwd": str(PRIMARY),
            "worktree_root": str(PRIMARY),
            "command": command,
            "input_files": input_files,
            "input_sha256": {path: records[path]["sha256"] for path in input_files},
            "input_records": records,
            "manifest": manifest_record,
            "deferred_input_files": sorted(deferred),
            "deferred_input_records": deferred,
            "execution_allowed": False,
            "launch_disabled": True,
            "solver_started": False,
            "native_payload_read": False,
            "hdf5_read": False,
            "builder_source": str(BUILDER),
            "builder_source_sha256": records[str(BUILDER)]["sha256"]
            if str(BUILDER) in records
            else "",
        }
    )
    request["axis_authority"] = {
        "manifest": str(new_manifest_path),
        "no_axis_self_assertion": True,
        "producer_axis_orientation_metadata": "MUST_BE_PRESENT_FOR_CALIBRATION; currently UNKNOWN",
        "source_writer_parser_xml_gravity_control_bound": True,
        "stat_rebind": "ROOT207 fresh primary stat after exact SHA/bytes equality",
    }
    request["source_binding"] = {
        "root204_v4_request": str(v4_path),
        "root204_v4_manifest": str(v4_manifest_path),
        "root204_failure_proof": failure_dependency,
        "root207_axis_stat_rebind": rebind_report,
        "old_root204_bytes_immutable": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request["root207_transition"] = {
        "schema": "ds02.stage2.f1.native-selected-observer-root207-transition.v1",
        "stat_only": not blocked,
        "blocked": blocked,
        "blocking_issues": issues,
        "source_records_rebound": rebind_report.get("source_record_count", 0),
        "source_records_content_mismatches": rebind_report.get("content_mismatch_count", 0),
        "old_root204_failure_status": "PRESERVED_AND_REQUIRED",
        "native_payload_read_by_builder": False,
    }
    request["preparation_scope"] = {
        "production_native_payload_read": False,
        "production_native_sha_computed": False,
        "deferred_native_stat_only": True,
        "axis_source_small_files_hashed": True,
        "new_source_bytes_read_by_builder": metadata_bytes,
        "source_stat_transition_only": not blocked,
    }
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _write_once(output_request, request)
    return request


def _self_test() -> dict[str, Any]:
    # Import and execute the stat-rebinder's real fixture tests.  The fixture
    # creates only tiny JSON files and deliberately never enters a production
    # path or native payload.
    from stage2_f1_native_selected_observer_axis_stat_rebind_v1 import _self_test as axis_test

    axis_result = axis_test()
    assert axis_result["status"] == "PASS"
    with tempfile.TemporaryDirectory(prefix="root207-builder-") as directory:
        root = Path(directory)
        source = root / "source.json"
        source.write_text("{}", encoding="utf-8")
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "axis_authority": {"source_records": []},
            "source_inputs": [],
            "root207_axis_stat_rebind": {"status": "PASS_STAT_ONLY_REBIND"},
        }
        _write_once(root / "manifest.json", manifest)
        loaded = _read_json(root / "manifest.json", "fixture manifest")
        assert loaded["schema"] == MANIFEST_SCHEMA
        assert source.read_text(encoding="utf-8") == "{}"
    return {
        "schema": V5_VARIANT,
        "status": "PASS",
        "axis_rebinder_fixture": axis_result,
        "production_native_payload_read": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--v4-request", type=Path, default=DEFAULT_V4_REQUEST)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--failure-proof", type=Path, default=DEFAULT_FAILURE_PROOF)
    parser.add_argument("--case-id", default="F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT207")
    parser.add_argument("--attempt-id", default="f1-s1-s2-native-header-selected-root207-001")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(_self_test(), indent=2, sort_keys=True))
        return 0
    if args.output_request is None:
        parser.error("--output-request is required for --build")
    try:
        result = build(
            args.v4_request,
            output_request=args.output_request,
            case_id=args.case_id,
            attempt_id=args.attempt_id,
            failure_proof_path=args.failure_proof,
            allow_blocked=args.allow_blocked,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "request": str(_path(args.output_request)),
                    "manifest": result["manifest"]["path"],
                    "native_payload_read": False,
                    "execution_allowed": result["execution_allowed"],
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED_ROOT207_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
