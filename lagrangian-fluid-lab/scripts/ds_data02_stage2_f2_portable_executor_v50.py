#!/usr/bin/env python3
"""Normalize a V49 executor to the exact v34 parent-guard status.

V49 deliberately used a forward-only status while its source closure and V4
scratch contract were being reviewed.  The consumed parent-v3 runner accepts
the v34 schema only when the child says exactly
``READY_FOR_PARENT_STAGE2_GUARD``.  V50 creates a fresh metadata request with
that status and preserves the V49 request as provenance.  It validates source
paths and byte stats only; it never hashes or opens BI4, HDF5, raw, typed, or
label payloads.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
V49_STATUS = "READY_FOR_PARENT_STAGE2_GUARD_V49"
V50_STATUS = "READY_FOR_PARENT_STAGE2_GUARD"
V49_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v49-forward.v1"
V50_FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v50-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 64 * 1024 * 1024


class ExecutorV50Error(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ExecutorV50Error(f"{role} path is missing")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise ExecutorV50Error(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise ExecutorV50Error(f"{role} exceeds metadata bound: {target}")
    return target


def _source_file(value: Any, role: str, *, allow_symlink: bool = False) -> Path:
    """Validate a declared source by path/stat without a size ceiling.

    Source closure rows may intentionally contain large raw/HDF5 inputs.  V50
    only reads their metadata here; applying the JSON metadata bound to those
    rows would reject a valid request before the parent guard can reserve and
    perform the required content verification.
    """
    if not isinstance(value, (str, Path)):
        raise ExecutorV50Error(f"{role} path is missing")
    target = Path(value).expanduser()
    if (target.is_symlink() and not allow_symlink) or not target.is_file():
        raise ExecutorV50Error(f"{role} is not a regular non-symlink file: {target}")
    return target


def _source_stat(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, int]:
    info = path.stat()
    if (path.is_symlink() and not allow_symlink) or not stat.S_ISREG(info.st_mode):
        raise ExecutorV50Error(f"{role} is not a regular allowed source file")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _load(path: Path | str, role: str) -> dict[str, Any]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExecutorV50Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ExecutorV50Error(f"{role} must be an object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise ExecutorV50Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    return target


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise ExecutorV50Error(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path, role: str) -> dict[str, int]:
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ExecutorV50Error(f"{role} is not a regular non-symlink file")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _full_stat(path: Path, role: str) -> dict[str, int]:
    """Return the complete small-file stat contract used by V36.

    A relocated wrapper may have a new inode/mtime while its content identity
    is unchanged.  The old stat is provenance; the current stat is the
    actionable contract.  This helper is intentionally used only for the
    small decoder wrapper, never for raw/HDF5/typed payload rows.
    """
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ExecutorV50Error(f"{role} is not a regular non-symlink file")
    return {
        "st_dev": int(info.st_dev), "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode), "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink), "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid), "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns), "st_ctime_ns": int(info.st_ctime_ns),
    }


def _refresh_actionable_wrapper(value: dict[str, Any]) -> dict[str, Any]:
    """Rebind only the V4 scratch wrapper's nested source/stat mirrors.

    V49 already retained the scientific V2 worker in ``runtime_sources``.  It
    also retained a source-entry role named ``v2_worker`` for the replacement
    V4 scratch wrapper, but its ``resolved_source_path`` and
    ``source_stat_expected`` can still describe the old V2 file.  Updating
    those fields is safe only after the wrapper's content SHA is checked.  The
    old path/stat/SHA are retained in the V50 forward marker and are never
    used as a current source fallback.
    """
    execution = value.get("execution")
    if not isinstance(execution, dict):
        raise ExecutorV50Error("V49 execution is missing")
    scratch = execution.get("decoder_scratch")
    if not isinstance(scratch, Mapping):
        raise ExecutorV50Error("V49 decoder scratch contract is missing")
    wrapper_value = scratch.get("wrapper_path")
    if not isinstance(wrapper_value, str) or not wrapper_value:
        raise ExecutorV50Error("V49 decoder scratch wrapper_path is missing")
    wrapper = _file(wrapper_value, "V4 decoder scratch wrapper")
    wrapper_sha = sha256_file(wrapper)
    wrapper_stat = _full_stat(wrapper, "V4 decoder scratch wrapper")

    rows = value.get("source_entries")
    if not isinstance(rows, list):
        raise ExecutorV50Error("V49 source_entries are missing")
    candidates = [item for item in rows
                  if isinstance(item, dict) and item.get("role") == "v2_worker"]
    if len(candidates) != 1:
        raise ExecutorV50Error("V49 actionable v2_worker wrapper is not unique")
    item = candidates[0]
    old = {
        "path": item.get("path"),
        "resolved_source_path": item.get("resolved_source_path"),
        "sha256": item.get("sha256"),
        "bytes": item.get("bytes"),
        "mtime_ns": item.get("mtime_ns"),
        "mode_bits": item.get("mode_bits"),
        "source_mode_bits": item.get("source_mode_bits"),
        "source_stat_expected": copy.deepcopy(item.get("source_stat_expected")),
        "source_stat_provenance": copy.deepcopy(item.get("source_stat_provenance")),
    }
    old_path = old.get("path")
    old_resolved = old.get("resolved_source_path")
    # The current wrapper is a new actionable source.  A stale V2 path may be
    # retained only in provenance; it must never be opened by this forward.
    item["path"] = str(wrapper)
    item["resolved_source_path"] = str(wrapper)
    item["sha256"] = wrapper_sha
    item["bytes"] = wrapper_stat["st_size"]
    item["mtime_ns"] = wrapper_stat["st_mtime_ns"]
    item["mode_bits"] = wrapper_stat["mode_bits"]
    item["source_mode_bits"] = wrapper_stat["mode_bits"]
    item["source_stat_expected"] = dict(wrapper_stat)
    item.setdefault("source_stat_provenance", old.get("source_stat_expected"))
    item["wrapper_binding_role"] = "v4_scratch_wrapper"

    scratch = dict(scratch)
    scratch.update({
        "wrapper_path": str(wrapper),
        "wrapper_sha256": wrapper_sha,
        "wrapper_bytes": wrapper_stat["st_size"],
        "wrapper_source_stat_expected": dict(wrapper_stat),
        "wrapper_source_mode_bits": wrapper_stat["mode_bits"],
    })
    execution["decoder_scratch"] = scratch
    return {
        "role": "v2_worker",
        "old_path": old_path,
        "old_resolved_source_path": old_resolved,
        "old_sha256": old.get("sha256"),
        "old_bytes": old.get("bytes"),
        "old_source_stat_expected": old.get("source_stat_expected"),
        "old_source_stat_provenance": old.get("source_stat_provenance"),
        "current_path": str(wrapper),
        "current_sha256": wrapper_sha,
        "current_bytes": wrapper_stat["st_size"],
        "current_source_stat_expected": dict(wrapper_stat),
        "content_sha_verified": True,
        "payload_content_read": False,
    }


def _closure(value: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for section in ("source_entries", "runtime_sources"):
        values = value.get(section)
        if not isinstance(values, list) or not values:
            raise ExecutorV50Error(f"V49 {section} is missing")
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise ExecutorV50Error(f"V49 {section}[{index}] is malformed")
            rows.append((section, raw))
    # V49's declared copy budget deduplicates by content identity, not source
    # pathname.  This matters for the root closure where /usr/bin/python and
    # the literal venv/python symlink expose the same executable bytes.
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    # A source and runtime row may intentionally install the same immutable
    # file at one target path.  Permit that exact duplicate, but reject a
    # target collision between different content/roles.
    target_bindings: dict[str, tuple[str, str, int]] = {}
    for section, raw in rows:
        role = str(raw.get("role", ""))
        allow_symlink = section == "runtime_sources" and role == "python_executable"
        path = _source_file(raw.get("path"), f"V49 {section}.path",
                            allow_symlink=allow_symlink)
        digest = _sha(raw.get("sha256"), f"V49 {section}.sha256")
        raw_bytes = raw.get("bytes")
        if isinstance(raw_bytes, bool):
            raise ExecutorV50Error(f"V49 {section}.bytes is malformed")
        try:
            declared_bytes = int(raw_bytes)
        except (TypeError, ValueError) as error:
            raise ExecutorV50Error(f"V49 {section}.bytes is malformed") from error
        actual = _source_stat(path, f"V49 {section}.path", allow_symlink=allow_symlink)
        if actual["bytes"] != declared_bytes:
            raise ExecutorV50Error(f"V49 {section}.bytes differs: {path}")
        relative = raw.get("target_relative_path")
        if relative is not None:
            if not isinstance(relative, str) or not relative or relative.startswith("/"):
                raise ExecutorV50Error(f"V49 {section}.target_relative_path is malformed")
            binding = (str(path), digest, declared_bytes)
            if relative in target_bindings and target_bindings[relative] != binding:
                raise ExecutorV50Error(f"duplicate target_relative_path: {relative}")
            target_bindings[relative] = binding
        unique[(digest, declared_bytes)] = {
            "section": section, "role": role,
            "path": str(path), "sha256": digest, "bytes": declared_bytes,
            "stat": actual,
        }
    forward = value.get("forward_v49")
    if not isinstance(forward, Mapping) or forward.get("schema") != V49_FORWARD_SCHEMA:
        raise ExecutorV50Error("V49 forward marker is missing")
    declared = forward.get("static_copy_bytes_after_rebind")
    if isinstance(declared, bool) or not isinstance(declared, int):
        raise ExecutorV50Error("V49 static copy byte declaration is missing")
    total = sum(item["bytes"] for item in unique.values())
    if declared != total:
        raise ExecutorV50Error(f"V49 static copy bytes differ: {declared} != {total}")
    return {"declared_item_count": len(rows), "deduplicated_item_count": len(unique),
            "deduplicated_copy_bytes": total, "target_relative_path_count": len(target_bindings),
            "content_read": False, "payload_hashes_computed": False}


def build_forward(*, v49_request: Path | str, output_request: Path | str,
                  target_root: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path = _file(v49_request, "V49 executor request")
    source = _load(source_path, "V49 executor request")
    if source.get("schema") != V34_SCHEMA or source.get("status") != V49_STATUS:
        raise ExecutorV50Error("input is not the V49 v34 request")
    if source.get("sha256") != canonical_sha(source):
        raise ExecutorV50Error("V49 executor canonical SHA differs")
    if source.get("role") != "DEVELOPMENT" or source.get("model_invoked") is not False:
        raise ExecutorV50Error("V49 executor is not model-free DEVELOPMENT")
    if source.get("cfd_invoked") is not False or source.get("qualification") != UNKNOWN:
        raise ExecutorV50Error("V49 executor qualification/CFD state is not UNKNOWN/false")
    execution = source.get("execution")
    if not isinstance(execution, Mapping) or execution.get("original_path_fallback") != "FORBIDDEN":
        raise ExecutorV50Error("V49 executor does not forbid original fallback")
    scratch = execution.get("decoder_scratch")
    if not isinstance(scratch, Mapping) or scratch.get("default_tmp_forbidden") is not True \
            or scratch.get("cleanup_after_each_frame") is not True:
        raise ExecutorV50Error("V49 V4 scratch contract is incomplete")
    roots = source.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise ExecutorV50Error("V49 fresh roots are missing")
    target = Path(str(target_root or roots.get("target_root"))).expanduser()
    output = Path(str(output_root or roots.get("output_root"))).expanduser()
    if not target.is_absolute() or not output.is_absolute() or target == output:
        raise ExecutorV50Error("V50 fresh roots must be distinct absolute paths")
    if target.exists() or output.exists():
        raise ExecutorV50Error("V50 fresh roots must not exist")
    value = copy.deepcopy(source)
    wrapper_binding = _refresh_actionable_wrapper(value)
    closure = _closure(value)
    value["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    value["status"] = V50_STATUS
    value["request_id"] = str(value.get("request_id", "f2-s1-v49")) + "-v50"
    value["forward_v50"] = {
        "schema": V50_FORWARD_SCHEMA,
        "previous_request_path": str(source_path),
        "previous_request_physical_sha256": sha256_file(source_path),
        "previous_request_canonical_sha256": source["sha256"],
        "previous_status": source["status"],
        "status_normalized_for_parent_v3": True,
        "source_closure": closure,
        "actionable_wrapper_binding": wrapper_binding,
        "historical_v2_worker_retained_as_raw_worker_v2": True,
        "target_root": str(target), "output_root": str(output),
        "content_read": False, "payload_hashes_computed": False,
        "qualification": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V50 normalizes only the v34 parent status; V49 source paths/stat/SHA declarations remain provenance.",
        "Payload SHA verification remains a same-parent post-reservation operation.",
    ]
    value["sha256"] = canonical_sha(value)
    output_path = _write_new(output_request, value)
    return {
        "schema": V50_FORWARD_SCHEMA, "status": "READY_FOR_PARENT_V50",
        "request": str(output_path), "request_sha256": sha256_file(output_path),
        "request_canonical_sha256": value["sha256"],
        "declared_static_copy_bytes": closure["deduplicated_copy_bytes"],
        "content_read": False, "payload_hashes_computed": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v49-request", type=Path, required=True)
    parser.add_argument("--output-request", type=Path, required=True)
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    try:
        value = build_forward(v49_request=args.v49_request, output_request=args.output_request,
                              target_root=args.target_root, output_root=args.output_root)
    except (ExecutorV50Error, OSError, ValueError, TypeError) as error:
        print(f"executor V50: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
