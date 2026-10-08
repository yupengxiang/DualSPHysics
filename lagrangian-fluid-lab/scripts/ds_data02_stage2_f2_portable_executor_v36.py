#!/usr/bin/env python3
"""Forward v36 executable-permission contract for the portable F2 executor.

V35 fixed the raw-frame layout, but the consumed v34 copier used
``shutil.copyfile`` without restoring source mode bits.  The native decoder
therefore arrived at the relocated target as mode ``0644`` and failed its
own executable check after the entire source copy had completed.

This additive version preserves the v35/v34 request envelope for the existing
parent-v3 guard while binding source ``stat`` records, mode bits, executable
roles, pre/post source identity and target inode separation.  Metadata build
and preflight use ``stat`` only.  The run path is the only path that hashes or
copies content, and it records the mode contract around every copied source.
No consumed v35 request or receipt is edited.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V35_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v35.py"
V34_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v34.py"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v36-forward.v1"
PERMISSIONS_SCHEMA = "ds02.stage2.f2-portable-permissions.v1"
BOUND_V35_SHA256 = "76bb8bb07ebfa50797feeee770ae824f26eb69844635dae85d507c7b937708b2"
BOUND_V34_SHA256 = "506477a0feb24a9e6b58af82499bf242f37a3cd768bc39cd6dbaa73d1dead989"
EXECUTABLE_ROLE_HINTS = frozenset({
    "native_bi4_decoder", "native_decoder", "python_executable", "gencase_binary",
    "solver_binary", "strace", "os_strace",
})
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class PortableV36Error(RuntimeError):
    """Raised when the v36 permission/identity contract is incomplete."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV36Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV36Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableV36Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise PortableV36Error(f"{name} must be a lowercase SHA-256")
    return value


def _stat_record(path: Path | str) -> dict[str, int]:
    target = Path(path).expanduser().resolve()
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise PortableV36Error(f"bound source is not a regular file: {target}")
    # atime is deliberately excluded: source hashing can update it.  These
    # fields bind identity, ownership, mode, size and stable timestamps.
    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink),
        "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid),
        "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns),
        "st_ctime_ns": int(info.st_ctime_ns),
    }


def _stat_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = (
        "st_dev", "st_ino", "st_mode", "mode_bits", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_mtime_ns", "st_ctime_ns",
    )
    return all(int(left.get(key, -1)) == int(right.get(key, -1)) for key in keys)


def _source_mode_contract(item: Mapping[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    role = str(item.get("role", ""))
    source = path or Path(str(item.get("path", ""))).expanduser().resolve()
    if not source.is_file():
        raise PortableV36Error(f"source for {role} is unavailable: {source}")
    source_stat = _stat_record(source)
    required_executable = role in EXECUTABLE_ROLE_HINTS or bool(source_stat["mode_bits"] & 0o111)
    if role in EXECUTABLE_ROLE_HINTS and not source_stat["mode_bits"] & 0o111:
        raise PortableV36Error(f"bound executable role lacks execute permission: {role}")
    return {
        "role": role,
        # Keep the caller's literal path in the request.  In particular a
        # venv invocation path may be a symlink whose resolved target is the
        # system interpreter; replacing it here would recreate the ABI bug
        # that this forward version is meant to prevent.  The resolved path
        # is provenance/stat evidence only.
        "resolved_source_path": str(source),
        "source_stat_expected": source_stat,
        "source_mode_bits": source_stat["mode_bits"],
        "preserve_mode": True,
        "required_executable": bool(required_executable),
    }


def _validate_mode_contract(request: Mapping[str, Any], *, check_current_stat: bool) -> dict[str, Any]:
    if request.get("schema") != V34_SCHEMA:
        raise PortableV36Error("v36 request must retain the parent-v3 v34 schema")
    if request.get("sha256") != canonical_sha(request):
        raise PortableV36Error("v36 request canonical SHA differs")
    forward = request.get("forward_v36")
    if not isinstance(forward, Mapping) or forward.get("schema") != FORWARD_SCHEMA:
        raise PortableV36Error("v36 forward marker is missing")
    contract = request.get("permissions_contract")
    if not isinstance(contract, Mapping) or contract.get("schema") != PERMISSIONS_SCHEMA:
        raise PortableV36Error("v36 permissions contract is missing")
    if contract.get("preserve_mode") is not True or contract.get("target_inode_must_differ") is not True:
        raise PortableV36Error("v36 permissions contract does not preserve mode/distinct inode")
    entries: list[Mapping[str, Any]] = []
    for key in ("source_entries", "runtime_sources"):
        value = request.get(key)
        if not isinstance(value, list):
            raise PortableV36Error(f"{key} are missing")
        entries.extend(item for item in value if isinstance(item, Mapping))
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(entries):
        role = str(item.get("role", ""))
        expected = item.get("source_stat_expected")
        if not isinstance(expected, Mapping):
            raise PortableV36Error(f"{role or index} has no source_stat_expected")
        mode_bits = int(item.get("source_mode_bits", -1))
        if int(expected.get("mode_bits", -1)) != mode_bits:
            raise PortableV36Error(f"{role} mode_bits differ from source stat contract")
        required = bool(item.get("required_executable"))
        if required and not mode_bits & 0o111:
            raise PortableV36Error(f"{role} is marked executable but mode is {mode_bits:o}")
        source = Path(str(item.get("path", ""))).expanduser().resolve()
        if check_current_stat:
            actual = _stat_record(source)
            if not _stat_equal(actual, expected):
                raise PortableV36Error(f"source stat differs for {role}: {source}")
            if actual["mode_bits"] != mode_bits:
                raise PortableV36Error(f"source mode differs for {role}: {source}")
        checked.append({"role": role, "path": str(source), "source_stat": dict(expected),
                        "mode_bits": mode_bits, "required_executable": required})
    return {"schema": PERMISSIONS_SCHEMA, "checked_entries": checked,
            "entry_count": len(checked), "stat_only": not check_current_stat,
            "content_read": False}


def _load_module(path: Path, name: str):
    if not path.is_file():
        raise PortableV36Error(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PortableV36Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_v35():
    if sha256_file(V35_SCRIPT) != BOUND_V35_SHA256:
        raise PortableV36Error("immutable v35 executor SHA differs from forward binding")
    return _load_module(V35_SCRIPT, "ds02_bound_f2_executor_v35")


def _load_v34():
    if sha256_file(V34_SCRIPT) != BOUND_V34_SHA256:
        raise PortableV36Error("immutable v34 executor SHA differs from forward binding")
    return _load_module(V34_SCRIPT, "ds02_bound_f2_executor_v34_v36")


def _annotate_collection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        value = dict(item)
        contract = _source_mode_contract(value)
        # ``path`` remains the exact invocation/source URI supplied by the
        # previous request.  Only the resolved path is recorded separately.
        contract.pop("path", None)
        value.update(contract)
        result.append(value)
    return result


def _required_roles(source_entries: Sequence[Mapping[str, Any]],
                    runtime_sources: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted({
        str(item["role"])
        for item in list(source_entries) + list(runtime_sources)
        if item.get("required_executable")
    })


def build_forward(*, v35_request: Path | str, v35_overlay: Path | str,
                  output_request: Path | str, output_overlay: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    """Create the v36 permission contract using JSON and ``stat`` only."""
    v35 = _load_v35()
    request = load_json(v35_request)
    overlay = load_json(v35_overlay)
    if request.get("schema") != V34_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise PortableV36Error("v35 request is not a canonical v34 compatibility envelope")
    if not isinstance(request.get("forward_v35"), Mapping):
        raise PortableV36Error("v35 forward marker is missing")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise PortableV36Error("v35 overlay canonical SHA differs")

    # Reuse the already-tested path rewrite in a private temporary JSON pair;
    # no scientific source is opened or hashed by this phase.  The output
    # files are re-emitted under the v36 names below.
    with tempfile.TemporaryDirectory(prefix="ds02-v36-build-") as temp:
        temp_request = Path(temp) / "request.json"
        temp_overlay = Path(temp) / "overlay.json"
        v35.build_forward(v34_request=v35_request, v5_overlay=v35_overlay,
                          output_request=temp_request, output_overlay=temp_overlay,
                          target_root=target_root, output_root=output_root)
        new_request = load_json(temp_request)
        new_overlay = load_json(temp_overlay)

    source_entries = new_request.get("source_entries")
    runtime_sources = new_request.get("runtime_sources")
    if not isinstance(source_entries, list) or not isinstance(runtime_sources, list):
        raise PortableV36Error("v35 request lacks source/runtime entries")

    # V35 itself is retained as a compatibility runtime.  The parent can bind
    # this V36 shim as the actual executor script in a fresh request.
    if not any(isinstance(item, Mapping) and item.get("role") == "executor_v36"
               for item in runtime_sources):
        current = SCRIPT.stat()
        runtime_sources.append({
            "role": "executor_v36", "path": str(SCRIPT),
            "bytes": int(current.st_size), "mtime_ns": int(current.st_mtime_ns),
            "sha256": sha256_file(SCRIPT),
            "target_relative_path": "runtime/executor/ds_data02_stage2_f2_portable_executor_v36.py",
            "forward_only": True,
        })
    new_request["source_entries"] = _annotate_collection([dict(item) for item in source_entries])
    new_request["runtime_sources"] = _annotate_collection([dict(item) for item in runtime_sources])

    source_by_path = {
        str(Path(item["path"]).expanduser().resolve()): item
        for item in new_request["source_entries"]
    }
    overlay_entries = new_overlay.get("entries")
    if not isinstance(overlay_entries, list):
        raise PortableV36Error("v35 overlay entries are missing")
    rewritten_overlay: list[dict[str, Any]] = []
    for raw in overlay_entries:
        item = dict(raw)
        original = str(Path(str(item.get("original_path", ""))).expanduser().resolve())
        source = source_by_path.get(original)
        if source is None:
            raise PortableV36Error(f"overlay entry has no source stat binding: {original}")
        item.update({
            "source_stat_expected": source["source_stat_expected"],
            "source_mode_bits": source["source_mode_bits"],
            "target_mode_bits": source["source_mode_bits"],
            "preserve_mode": True,
            "required_executable": source["required_executable"],
            "target_inode_must_differ": True,
        })
        rewritten_overlay.append(item)
    new_overlay["entries"] = rewritten_overlay
    new_overlay["forward_v36"] = {
        "schema": FORWARD_SCHEMA,
        "parent_compatibility_envelope": V34_SCHEMA,
        "source_stat_read_during_build": True,
        "content_read_during_build": False,
        "preserve_mode": True,
        "target_inode_must_differ": True,
        "required_executable_roles": _required_roles(
            new_request["source_entries"], new_request["runtime_sources"]),
        "scientific_scope": "permission/path contract only; no raw/H5 content read",
        "original_path_fallback": "FORBIDDEN",
    }
    permission_contract = {
        "schema": PERMISSIONS_SCHEMA,
        "preserve_mode": True,
        "target_inode_must_differ": True,
        "source_stat_read_during_build": True,
        "content_read_during_build": False,
        "executable_roles": _required_roles(
            new_request["source_entries"], new_request["runtime_sources"]),
        "pre_post_source_stat_required": True,
        "expected_sha_required": True,
    }
    new_request["permissions_contract"] = permission_contract
    new_overlay["permissions_contract"] = permission_contract
    new_overlay["status"] = "READY_FOR_PARENT_COPY; V36_MODE_AND_INODE_CONTRACT"
    new_overlay["sha256"] = canonical_sha(new_overlay)

    overlay_path = Path(output_overlay).expanduser().resolve()
    request_path = Path(output_request).expanduser().resolve()
    write_new(overlay_path, new_overlay)
    new_request["v5_overlay_template"] = {
        "canonical_sha256": new_overlay["sha256"],
        "path": str(overlay_path),
        "sha256": sha256_file(overlay_path),
    }
    old_target = str(new_request.get("fresh_roots", {}).get("target_root", ""))
    old_output = str(new_request.get("fresh_roots", {}).get("output_root", ""))
    derived_target = old_target.replace("v35-executor-051", "v36-executor-052")
    derived_output = old_output.replace("v35-executor-051", "v36-executor-052")
    target = str(Path(target_root or derived_target).expanduser())
    output = str(Path(output_root or derived_output).expanduser())
    if not target or not output or target == output:
        raise PortableV36Error("fresh target/output roots must be distinct")
    new_request["fresh_roots"] = {"target_root": target, "output_root": output}
    new_request["storage_scope"] = dict(new_request.get("storage_scope", {}),
                                         new_namespace_absent_before_run=True,
                                         external_output_root=output)
    new_request["forward_v36"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "previous_forward_schema": "ds02.stage2.f2-portable-executor-v35-forward.v1",
        "previous_executor_sha256": BOUND_V35_SHA256,
        "overlay_sha256": new_overlay["sha256"],
        "permissions_contract": PERMISSIONS_SCHEMA,
        "content_read_during_build": False,
        "source_stat_read_during_build": True,
        "original_path_fallback": "FORBIDDEN",
    }
    new_request["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    new_request["sha256"] = canonical_sha(new_request)
    request_path = write_new(request_path, new_request)
    return {
        "status": "READY_FOR_PARENT_V36_METADATA_ONLY",
        "request": str(request_path), "request_sha256": sha256_file(request_path),
        "overlay": str(overlay_path), "overlay_sha256": sha256_file(overlay_path),
        "source_stat_count": len(new_request["source_entries"]),
        "runtime_stat_count": len(new_request["runtime_sources"]),
        "executable_roles": permission_contract["executable_roles"],
        "content_read": False, "qualification": dict(UNKNOWN),
    }


def _contract_by_source(request: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for key in ("source_entries", "runtime_sources"):
        for item in request.get(key, []):
            if isinstance(item, Mapping):
                result[str(Path(str(item.get("path", ""))).expanduser().resolve())] = item
    return result


def copy_one_preserving_mode(source: Path | str, target: Path | str,
                             expected_sha: str, expected_bytes: int,
                             contract: Mapping[str, Any]) -> dict[str, Any]:
    """Copy one bound source and enforce pre/post identity and target mode."""
    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    if target_path.exists():
        raise PortableV36Error(f"refusing existing copied target: {target_path}")
    expected_stat = contract.get("source_stat_expected")
    if not isinstance(expected_stat, Mapping):
        raise PortableV36Error(f"missing source stat contract: {source_path}")
    source_pre = _stat_record(source_path)
    if not _stat_equal(source_pre, expected_stat):
        raise PortableV36Error(f"source pre-stat differs: {source_path}")
    if source_pre["st_size"] != int(expected_bytes):
        raise PortableV36Error(f"source byte stat differs: {source_path}")
    source_sha_pre = sha256_file(source_path)
    if source_sha_pre != expected_sha:
        raise PortableV36Error(f"source SHA differs: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)
    os.chmod(target_path, stat.S_IMODE(source_pre["st_mode"]))
    target_stat = _stat_record(target_path)
    if (target_stat["st_dev"], target_stat["st_ino"]) == (source_pre["st_dev"], source_pre["st_ino"]):
        raise PortableV36Error(f"target inode is not distinct: {target_path}")
    if target_stat["mode_bits"] != source_pre["mode_bits"]:
        raise PortableV36Error(f"target mode differs: {target_path}")
    required = bool(contract.get("required_executable"))
    if required and not target_stat["mode_bits"] & 0o111:
        raise PortableV36Error(f"target executable permission is missing: {target_path}")
    target_sha = sha256_file(target_path)
    if target_stat["st_size"] != int(expected_bytes) or target_sha != expected_sha:
        raise PortableV36Error(f"copied target content differs: {target_path}")
    source_post = _stat_record(source_path)
    source_sha_post = sha256_file(source_path)
    if not _stat_equal(source_pre, source_post) or source_sha_post != source_sha_pre:
        raise PortableV36Error(f"source changed during copy: {source_path}")
    return {
        "path": str(target_path), "bytes": int(target_stat["st_size"]),
        "sha256": target_sha, "source_sha256_pre": source_sha_pre,
        "source_sha256_post": source_sha_post,
        "source_stat_pre": source_pre, "source_stat_post": source_post,
        "target_stat": target_stat, "target_inode_distinct": True,
        "target_mode_bits": target_stat["mode_bits"],
        "required_executable": required,
    }


def _run_with_mode_contract(module: Any, request_path: Path, *, io_slot_approved: bool,
                            parent_pid: int | None, evaluator_proof: Path | None,
                            max_wall_seconds: float | None) -> dict[str, Any]:
    request = load_json(request_path)
    _validate_mode_contract(request, check_current_stat=True)
    contracts = _contract_by_source(request)
    records: list[dict[str, Any]] = []
    original_copy = module._copy_one

    def wrapped_copy(source: Path, target: Path, expected_sha: str, expected_bytes: int):
        key = str(Path(source).expanduser().resolve())
        contract = contracts.get(key)
        if contract is None:
            raise PortableV36Error(f"copied source is absent from v36 contract: {source}")
        record = copy_one_preserving_mode(source, target, expected_sha, expected_bytes, contract)
        records.append(record)
        return record

    module._copy_one = wrapped_copy
    try:
        result = module.run(request_path, io_slot_approved=io_slot_approved,
                            parent_pid=parent_pid, evaluator_proof=evaluator_proof,
                            max_wall_seconds=max_wall_seconds)
    finally:
        module._copy_one = original_copy
    report_path = Path(str(result.get("report", ""))).expanduser().resolve()
    if report_path.is_file():
        report = load_json(report_path)
        report["v36_permissions"] = {
            "schema": PERMISSIONS_SCHEMA, "status": "VERIFIED_PRE_POST_COPY",
            "copy_count": len(records), "records": records,
            "source_stat_pre_post_required": True, "target_inode_must_differ": True,
        }
        report["sha256"] = canonical_sha(report)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["report_sha256"] = sha256_file(report_path)
    result["v36_permissions"] = {"copy_count": len(records), "status": "VERIFIED_PRE_POST_COPY"}
    return result


def preflight(request_path: Path, output: Path) -> dict[str, Any]:
    request = load_json(request_path)
    checked = _validate_mode_contract(request, check_current_stat=True)
    module = _load_v34()
    result = module.preflight(request_path, output)
    report = load_json(output)
    report["v36_permissions"] = {
        "schema": PERMISSIONS_SCHEMA, "status": "READY_FOR_COPY_MODE_VALIDATION",
        "checked_entries": checked["entry_count"], "source_stat_only": True,
        "content_read": False, "target_inode_must_differ": True,
    }
    report["sha256"] = canonical_sha(report)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.update({"v36_permissions": report["v36_permissions"], "sha256": report["sha256"]})
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v35-request", type=Path, required=True)
    build.add_argument("--v35-overlay", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--output-overlay", type=Path, required=True)
    build.add_argument("--target-root", type=Path)
    build.add_argument("--output-root", type=Path)
    prep = sub.add_parser("preflight")
    prep.add_argument("--request", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--evaluator-proof", type=Path)
    run_parser.add_argument("--max-wall-seconds", type=float)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--request", type=Path, required=True)
    evaluate.add_argument("--evaluator-proof", type=Path, required=True)
    evaluate.add_argument("--parent-pid", type=int)
    evaluate.add_argument("--max-wall-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            value = build_forward(v35_request=args.v35_request, v35_overlay=args.v35_overlay,
                                  output_request=args.output_request, output_overlay=args.output_overlay,
                                  target_root=args.target_root, output_root=args.output_root)
        elif args.command == "preflight":
            value = preflight(args.request, args.output)
        else:
            module = _load_v34()
            if args.command == "run":
                value = _run_with_mode_contract(
                    module, args.request, io_slot_approved=args.io_slot_approved,
                    parent_pid=args.parent_pid, evaluator_proof=args.evaluator_proof,
                    max_wall_seconds=args.max_wall_seconds)
            else:
                request = load_json(args.request)
                if request.get("schema") != V34_SCHEMA or request.get("sha256") != canonical_sha(request):
                    raise PortableV36Error("evaluate request canonical v34 binding differs")
                value = module.evaluate_existing(args.request, evaluator_proof=args.evaluator_proof,
                                                 parent_pid=args.parent_pid,
                                                 max_wall_seconds=args.max_wall_seconds)
    except (PortableV36Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v36: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
