#!/usr/bin/env python3
"""Build a parent-v8-ready ROOT182 native-audit request.

The consumed V2 binder is intentionally immutable.  This forward builder
adapts its ready manifest to the strict Stage2 runtime-v8 contract:

* ``cwd``/``worktree_root`` and the complete v8/v6/v2/dispatch closure are
  explicit and digest-bound;
* every small source, terminal, proof, adapter, tool, and worker file is an
  input with a real SHA;
* the native ``PartOut_000.obi4`` is deliberately absent from parent
  ``input_files``/``input_sha256``.  Only its already-recorded stat is carried
  in the manifest and ``guarded_payload_binding``.  The child worker obtains
  the first content SHA after reservation and verifies the post-read SHA;
* the light validator performs only bounded stat/SHA checks on declared small
  inputs and never opens the native payload.

This module does not bind a live ROOT170 receipt, launch a runner, or read
PartOut/H5/BI4 content.  It is a forward-only request builder; the parent
process may call it after the V2 binder has produced the final manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
V1_WORKER = SCRIPT.with_name("ds_data02_stage2_f3_s2_fine_native_motive_audit_v1.py")
V2_WORKER = SCRIPT.with_name("ds_data02_stage2_f3_s2_fine_native_motive_audit_v2.py")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PARENT_GUARD_COMPUTED = "PARENT_GUARD_COMPUTED"
SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-parent-request.v3"
REQUEST_SCHEMA = "ds02.request.v1"
RUNTIME6_CLOSURE_SCHEMA = "ds02.stage2.runtime6-closure.v1"
CPU_KINDS = {"gencase", "conversion", "audit", "labels", "evaluator", "preview", "tests"}
RAW_NAME = "PartOut_000.obi4"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ParentRequestError(ValueError):
    """Raised when a parent-v8 request cannot be source-bound."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ParentRequestError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParentRequestError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ParentRequestError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise ParentRequestError(f"refusing to overwrite output: {path}")
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


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ParentRequestError(f"{label} lacks an absolute path")
    return Path(value).expanduser().resolve()


def _stat(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ParentRequestError(f"{label} is missing: {path}")
    value = path.stat()
    return {
        "path": str(path),
        "bytes": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "st_dev": value.st_dev,
        "st_ino": value.st_ino,
    }


def _small_ref(ref: dict[str, Any], label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict):
        raise ParentRequestError(f"{label} is malformed")
    path = _path(ref.get("path"), f"{label}.path")
    stat = _stat(path, label)
    expected = ref.get("sha256")
    if not isinstance(expected, str) or expected in {"", PARENT_GUARD_COMPUTED}:
        raise ParentRequestError(f"{label} must have a concrete SHA")
    actual = sha256_file(path)
    if actual != expected:
        raise ParentRequestError(f"{label} SHA differs: {path}")
    result = {"role": ref.get("role", label), **stat, "sha256": actual}
    return path, result


def _add_input(
    inputs: dict[str, dict[str, Any]],
    path: Path,
    *,
    expected_sha: str | None = None,
    role: str,
) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.name == RAW_NAME:
        raise ParentRequestError(f"raw native payload cannot be a parent input: {path}")
    stat = _stat(path, role)
    actual = sha256_file(path)
    if expected_sha is not None:
        if expected_sha == PARENT_GUARD_COMPUTED:
            raise ParentRequestError(f"deferred SHA is not allowed for parent input: {path}")
        if actual != expected_sha:
            raise ParentRequestError(f"{role} SHA differs: {path}")
    key = str(path)
    existing = inputs.get(key)
    if existing is not None and existing["sha256"] != actual:
        raise ParentRequestError(f"conflicting input SHA for {path}")
    value = {"role": role, **stat, "sha256": actual}
    inputs[key] = value
    return value


def _manifest_inputs(manifest_path: Path, manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if manifest.get("status") != "READY_FOR_GUARDED_AUDIT":
        raise ParentRequestError("final manifest is not READY_FOR_GUARDED_AUDIT")
    terminal = manifest.get("terminal_binding")
    if not isinstance(terminal, dict):
        raise ParentRequestError("final manifest lacks terminal_binding")
    refs = terminal.get("refs")
    if not isinstance(refs, dict):
        raise ParentRequestError("final manifest lacks terminal refs")
    raw_ref = refs.get("raw_partout")
    if not isinstance(raw_ref, dict):
        raise ParentRequestError("final manifest lacks raw_partout ref")
    raw_path = _path(raw_ref.get("path"), "raw_partout.path")
    if raw_path.name != RAW_NAME:
        raise ParentRequestError("raw_partout is not PartOut_000.obi4")
    raw_stat = _stat(raw_path, "raw_partout")
    if raw_ref.get("sha256") != PARENT_GUARD_COMPUTED:
        raise ParentRequestError("raw_partout must remain deferred to the guarded worker")
    if raw_ref.get("content_opened_by_binder") is not False:
        raise ParentRequestError("raw_partout binder provenance is not stat-only")
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if raw_ref.get(key) is not None and int(raw_ref[key]) != raw_stat[key]:
            raise ParentRequestError(f"raw_partout stat changed before parent request: {key}")

    inputs: dict[str, dict[str, Any]] = {}
    _add_input(inputs, manifest_path, role="final_manifest")

    source_refs = manifest.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise ParentRequestError("final manifest source_refs are missing")
    for index, ref in enumerate(source_refs):
        path, normalized = _small_ref(ref, f"source_refs[{index}]")
        _add_input(inputs, path, expected_sha=normalized["sha256"], role=str(ref.get("role", f"source_ref_{index}")))

    for role, ref in refs.items():
        if role == "raw_partout":
            continue
        path, normalized = _small_ref(ref, f"terminal_binding.refs.{role}")
        _add_input(inputs, path, expected_sha=normalized["sha256"], role=str(ref.get("role", role)))

    binder = manifest.get("binder")
    if isinstance(binder, dict):
        pending_ref = binder.get("pending_manifest")
        if isinstance(pending_ref, dict):
            path, normalized = _small_ref(pending_ref, "binder.pending_manifest")
            _add_input(inputs, path, expected_sha=normalized["sha256"], role="pending_manifest")

    return inputs, {"path": str(raw_path), **raw_stat, "sha256": PARENT_GUARD_COMPUTED, "role": "raw_partout"}


def _runtime_closure(
    *,
    runtime_v8: Path,
    runtime_v6: Path,
    runtime_v2: Path,
    dispatch_v8: Path,
    strict_v8: Path,
) -> dict[str, dict[str, Any]]:
    files = {
        "runtime_v2_base": runtime_v2,
        "runtime_v6_root": runtime_v6,
        "runtime_v8": runtime_v8,
        "dispatch_v8": dispatch_v8,
        "strict_v8": strict_v8,
    }
    result: dict[str, dict[str, Any]] = {}
    for role, path in files.items():
        path = Path(path).expanduser().resolve()
        stat = _stat(path, role)
        result[role] = {"path": str(path), **stat, "sha256": sha256_file(path)}
    return result


def _check_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ParentRequestError(f"unsafe identity: {label}")


def light_validate(request: dict[str, Any]) -> dict[str, Any]:
    """Validate parent-v8 request structure without opening the deferred raw payload."""
    required = ("schema", "family_id", "case_id", "attempt_id", "kind", "cpu_task_kind", "command", "cwd", "worktree_root", "input_files", "input_sha256", "runtime_binding", "dispatch_binding", "strict_dispatch_binding", "runtime6_closure", "guarded_payload_binding")
    for key in required:
        if key not in request:
            raise ParentRequestError(f"parent-v8 request lacks {key}")
    if request["schema"] != REQUEST_SCHEMA or request.get("shared_runtime_version") != "v8":
        raise ParentRequestError("request is not ds02.request.v1 shared runtime v8")
    if request["family_id"] not in {"infra", *[f"F{i}" for i in range(1, 8)]}:
        raise ParentRequestError("unknown family_id")
    _check_id(request["case_id"], "case_id")
    _check_id(request["attempt_id"], "attempt_id")
    if request["kind"] != "cpu" or request["cpu_task_kind"] not in CPU_KINDS:
        raise ParentRequestError("request is outside CPU dataset allowlist")
    command = request["command"]
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ParentRequestError("command must be an argv list")
    cwd = _path(request["cwd"], "cwd")
    worktree = _path(request["worktree_root"], "worktree_root")
    if not cwd.is_dir() or not worktree.is_dir():
        raise ParentRequestError("cwd/worktree_root must be existing directories")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise ParentRequestError("cwd must be inside worktree_root") from exc
    input_files = request["input_files"]
    input_hashes = request["input_sha256"]
    if not isinstance(input_files, list) or not input_files or not isinstance(input_hashes, dict):
        raise ParentRequestError("parent input files/hashes are malformed")
    seen: set[str] = set()
    for value in input_files:
        path = _path(value, "input_files entry")
        key = str(path)
        if key in seen:
            raise ParentRequestError(f"duplicate parent input: {path}")
        seen.add(key)
        if path.name == RAW_NAME:
            raise ParentRequestError("raw PartOut must not be parent-hashed")
        expected = input_hashes.get(key)
        if expected is None:
            raise ParentRequestError(f"missing input SHA: {path}")
        if expected == PARENT_GUARD_COMPUTED:
            raise ParentRequestError(f"deferred input SHA is not parent-valid: {path}")
        if sha256_file(path) != expected:
            raise ParentRequestError(f"input SHA differs: {path}")
    if set(str(_path(value, "input_files entry")) for value in input_files) != set(input_hashes):
        raise ParentRequestError("input_sha256 has undeclared or missing paths")

    closure = request["runtime6_closure"]
    if closure.get("schema") != RUNTIME6_CLOSURE_SCHEMA:
        raise ParentRequestError("runtime6_closure schema is missing")
    for role in ("runtime_v2_base", "runtime_v6_root", "runtime_v8", "dispatch_v8", "strict_v8"):
        ref = closure.get(role)
        if not isinstance(ref, dict) or str(_path(ref.get("path"), role)) not in seen or ref.get("sha256") != input_hashes[str(_path(ref["path"], role))]:
            raise ParentRequestError(f"runtime6 closure is not input-bound: {role}")
    for binding_key in ("runtime_binding", "dispatch_binding", "strict_dispatch_binding"):
        binding = request[binding_key]
        if not isinstance(binding, dict) or not binding:
            raise ParentRequestError(f"{binding_key} is missing")
        for ref in binding.values():
            if not isinstance(ref, dict):
                raise ParentRequestError(f"{binding_key} entry is malformed")
            normalized = str(_path(ref.get("path"), binding_key))
            if normalized not in seen or ref.get("sha256") != input_hashes[normalized]:
                raise ParentRequestError(f"{binding_key} entry is not input-bound")

    payload = request["guarded_payload_binding"]
    if not isinstance(payload, dict) or payload.get("sha256") != PARENT_GUARD_COMPUTED:
        raise ParentRequestError("guarded payload SHA policy is not deferred")
    raw_path = _path(payload.get("path"), "guarded_payload_binding.path")
    if raw_path.name != RAW_NAME or str(raw_path) in seen:
        raise ParentRequestError("guarded raw payload must be stat-only and absent from parent inputs")
    raw_actual = _stat(raw_path, "guarded_payload_binding.path")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if payload.get(field) is not None and int(payload[field]) != raw_actual[field]:
            raise ParentRequestError(f"guarded raw payload stat differs: {field}")
    if payload.get("content_opened_by_parent") is not False:
        raise ParentRequestError("parent payload policy claims content was opened")
    return {"status": "LIGHT_VALIDATED_PARENT_V8_NO_RAW_CONTENT", "input_count": len(input_files), "raw_partout_parent_hashed": False}


def build_parent_request(
    *,
    final_manifest: Path,
    output_request: Path,
    worker_v2: Path = V2_WORKER,
    worker_v1: Path = V1_WORKER,
    runtime_v8: Path,
    runtime_v6: Path,
    runtime_v2: Path,
    dispatch_v8: Path,
    strict_v8: Path,
    interpreter: Path = VENV,
    cwd: Path = LAB_ROOT / "scripts",
    worktree_root: Path = WORKTREE_ROOT,
    attempt_id: str = "f3-s2-fine-native-motive-audit-v3-root-forward-parent-001",
    case_id: str = "F3_S2_FINE_NATIVE_MOTIVE_AUDIT_ROOT182",
    max_wall_seconds: int = 900,
    estimated_storage_bytes: int = 256 * 1024 * 1024,
) -> dict[str, Any]:
    final_manifest = Path(final_manifest).expanduser().resolve()
    manifest = read_json(final_manifest, "final ROOT182 manifest")
    inputs, raw_ref = _manifest_inputs(final_manifest, manifest)
    closure = _runtime_closure(runtime_v8=runtime_v8, runtime_v6=runtime_v6, runtime_v2=runtime_v2, dispatch_v8=dispatch_v8, strict_v8=strict_v8)
    for role, ref in closure.items():
        _add_input(inputs, Path(ref["path"]), expected_sha=ref["sha256"], role=role)
    for role, path in (("worker_v2", worker_v2), ("worker_v1", worker_v1), ("parent_builder", SCRIPT), ("interpreter", interpreter)):
        _add_input(inputs, Path(path), role=role)

    input_paths = sorted(inputs)
    input_sha256 = {path: inputs[path]["sha256"] for path in input_paths}
    _check_id(case_id, "case_id")
    _check_id(attempt_id, "attempt_id")
    worktree_root = Path(worktree_root).expanduser().resolve()
    cwd = Path(cwd).expanduser().resolve()
    # V1 hashes the payload once before invoking PartVTKOut and once after it;
    # the official decoder necessarily reads it at least once in between.
    # Extra decoder passes are implementation-dependent and remain UNKNOWN.
    raw_estimate = int(raw_ref["bytes"]) * 3
    runtime_binding = {
        "runtime_v2_base": closure["runtime_v2_base"],
        "runtime_v6_root": closure["runtime_v6_root"],
        "runtime_v8": closure["runtime_v8"],
    }
    dispatch_binding = {"dispatch_v8": closure["dispatch_v8"]}
    strict_binding = {"strict_v8": closure["strict_v8"]}
    request = {
        "schema": REQUEST_SCHEMA,
        "request_schema": SCHEMA,
        "family_id": "infra",
        "case_id": case_id,
        "physical_case_id": manifest.get("case", {}).get("physical_case_id", "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"),
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": max_wall_seconds,
        "estimated_storage_bytes": estimated_storage_bytes,
        "estimated_native_read_bytes": raw_estimate,
        "estimated_hdf5_read_bytes": 0,
        "estimated_part_frame_read_bytes": 0,
        "cwd": str(cwd),
        "worktree_root": str(worktree_root),
        "command": [str(interpreter), str(Path(worker_v2).expanduser().resolve()), "audit", "--manifest", str(final_manifest), "--output", "{attempt_root}/f3-s2-fine-native-motive-v3.json"],
        "input_files": input_paths,
        "input_sha256": input_sha256,
        "shared_runtime_version": "v8",
        "runtime_binding": runtime_binding,
        "dispatch_binding": dispatch_binding,
        "strict_dispatch_binding": strict_binding,
        "runtime6_closure": {"schema": RUNTIME6_CLOSURE_SCHEMA, **closure},
        "guarded_payload_binding": {**raw_ref, "sha256": PARENT_GUARD_COMPUTED, "content_opened_by_parent": False, "first_content_sha_owner": "guarded_worker_after_reservation", "post_content_sha_required": True},
        "manifest_contract": {"path": str(final_manifest), "sha256": sha256_file(final_manifest), "raw_partout_sha256": PARENT_GUARD_COMPUTED, "raw_partout_excluded_from_parent_inputs": True, "raw_pre_post_sha_required": True},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "part_frame_bytes_read": 0, "raw_partout_content_read_by_parent": 0, "raw_partout_stat_bytes": raw_ref["bytes"], "raw_partout_estimate_bytes": raw_estimate, "raw_partout_estimate_minimum_passes": 3, "raw_partout_estimate_basis": "stat_size_times_two_guarded_sha_passes_plus_one_official_decoder_pass; extra decoder reads UNKNOWN; actual worker receipt is authoritative", "raw_partout_additional_decoder_reads": "UNKNOWN", "small_source_bytes_read": sum(inputs[path]["bytes"] for path in input_paths), "runtime_pre_post_hash_bytes": 2 * sum(inputs[path]["bytes"] for path in input_paths), "estimated_output_bytes": estimated_storage_bytes},
        "source_scope": {"terminal_and_source_refs_explicit": True, "raw_partout_parent_content_read": False, "h5_content_read": False, "part_frames_opened": False, "solver_started": False, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "status": "prepared_parent_v8_guard_pending_native_decoder",
        "canonical_ready": True,
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "primary_launch_owner": "root",
        "launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "solver_launch_forbidden": True,
        "request_note": "Forward ROOT182 parent-v8 request. All terminal/source/tool/runtime refs are digest-bound small inputs. PartOut_000.obi4 remains stat-only in the manifest and is excluded from parent input hashing; the guarded V2 worker owns pre/post content SHA after reservation. No H5/BI4/solver/CFD/model and all physical fate/dynamics/QI/QN/QE remain UNKNOWN.",
    }
    checked = light_validate(request)
    output_request = Path(output_request).expanduser().resolve()
    atomic_json(output_request, request)
    return {"request": request, "request_path": str(output_request), "request_sha256": sha256_file(output_request), "light_validation": checked, "raw_partout_parent_hashed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--final-manifest", required=True, type=Path)
    build.add_argument("--output-request", required=True, type=Path)
    build.add_argument("--worker-v2", type=Path, default=V2_WORKER)
    build.add_argument("--worker-v1", type=Path, default=V1_WORKER)
    build.add_argument("--runtime-v8", required=True, type=Path)
    build.add_argument("--runtime-v6", required=True, type=Path)
    build.add_argument("--runtime-v2", required=True, type=Path)
    build.add_argument("--dispatch-v8", required=True, type=Path)
    build.add_argument("--strict-v8", required=True, type=Path)
    build.add_argument("--interpreter", type=Path, default=VENV)
    build.add_argument("--cwd", type=Path, default=LAB_ROOT / "scripts")
    build.add_argument("--worktree-root", type=Path, default=WORKTREE_ROOT)
    build.add_argument("--attempt-id", default="f3-s2-fine-native-motive-audit-v3-root-forward-parent-001")
    build.add_argument("--case-id", default="F3_S2_FINE_NATIVE_MOTIVE_AUDIT_ROOT182")
    validate = sub.add_parser("light-validate")
    validate.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build_kwargs = vars(args).copy()
            build_kwargs.pop("command", None)
            result = build_parent_request(**build_kwargs)
            print(json.dumps({"schema": SCHEMA, "status": result["request"]["status"], "request": result["request_path"], "request_sha256": result["request_sha256"], "raw_partout_parent_hashed": False}, sort_keys=True))
        else:
            result = light_validate(read_json(args.request, "parent-v8 request"))
            print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"F3-S2 parent-v8 request builder failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
