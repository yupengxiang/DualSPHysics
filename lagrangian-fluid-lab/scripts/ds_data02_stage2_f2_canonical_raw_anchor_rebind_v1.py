#!/usr/bin/env python3
"""Rebind the V3 F2 raw request to a parent-owned copied namespace.

The V3 planner is intentionally stat-only: it selects the canonical CURRENT
row and leaves raw-tree/frame content hashes for the parent guard.  This
adapter is the next boundary.  A parent supplies an explicit post-reservation
binding manifest containing the copied modules, decoder, source files, raw
frame paths, and the rebuilt V15 request.  The adapter never searches an old
worktree, resolves a historical alias, or silently carries an actionable path
from the V3 template.

The adapter does not hash scientific payloads.  It checks the role graph,
target namespace, declared SHA/stat contract, and the literal interpreter
binding.  Content SHA verification belongs to the same parent reservation
that produced the binding manifest.  The output is therefore marked pending
unless every binding explicitly says ``VERIFIED_AFTER_RESERVATION``.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-rebound.v1"
BINDING_SCHEMA = "ds02.stage2.f2-parent-source-binding.v1"
PLAN_SCHEMA = "ds02.stage2.f2-canonical-raw-anchor-plan.v3"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
HEX64 = frozenset("0123456789abcdef")
MAX_JSON_BYTES = 8 * 1024 * 1024
MODULE_ROLES = ("raw_converter", "v14_operator", "v15_operator", "v16_operator", "worker")
REQUIRED_SOURCE_ROLES = (
    "current_catalog", "manifest", "xmf", "generated_xml", "motion_dat",
    "gencase_receipt", "solver_receipt", "owner_metadata", "conversion_report",
    "initial_csv", "native_partout", "native_runparts",
)
ACTIONABLE_KEYS = frozenset({
    "path", "output_root", "cwd", "worktree_root", "data_root", "source_root",
    "target_root", "trajectory_h5", "input_files", "source_files", "motion_engine_sources",
    "producer_receipts", "current_binding", "source_code_binding", "copy_roles",
})
PROVENANCE_KEYS = frozenset({"historical", "provenance", "original_roots", "history"})


class RebindError(RuntimeError):
    """Raised when a parent binding cannot be safely joined to the V3 plan."""


def _json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise RebindError(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise RebindError(f"{role} exceeds the bounded JSON input limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise RebindError(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RebindError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _sha(value: Any, role: str, *, pending: bool = False) -> str | None:
    if pending and value in (None, PENDING):
        return None
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise RebindError(f"{role} must be a lowercase SHA-256")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _target(value: Any, role: str, namespace: Path, *, must_exist: bool = False) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RebindError(f"{role} path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RebindError(f"{role} path must be absolute")
    resolved = path.resolve(strict=False)
    if not _inside(resolved, namespace) or resolved == namespace:
        raise RebindError(f"{role} escapes the copied namespace: {path}")
    if path.is_symlink():
        raise RebindError(f"{role} is a symlink")
    if must_exist and not resolved.is_file():
        raise RebindError(f"{role} target is not a regular file: {resolved}")
    return resolved


def _directory(value: Any, role: str, namespace: Path) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RebindError(f"{role} path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RebindError(f"{role} path must be absolute")
    resolved = path.resolve(strict=False)
    if not _inside(resolved, namespace) or resolved == namespace:
        raise RebindError(f"{role} escapes the copied namespace: {path}")
    if path.is_symlink():
        raise RebindError(f"{role} is a symlink")
    if not resolved.is_dir():
        raise RebindError(f"{role} target is not an existing directory: {resolved}")
    return resolved


def _stat(value: Any, role: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or not isinstance(value.get("target_stat"), Mapping):
        raise RebindError(f"{role}.target_stat is required")
    value = value["target_stat"]
    result: dict[str, int] = {}
    for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "mode_bits"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise RebindError(f"{role}.target_stat.{key} is invalid")
        result[key] = item
    return result


def _actual_stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
            "st_size": int(value.st_size), "st_mtime_ns": int(value.st_mtime_ns),
            "st_ctime_ns": int(value.st_ctime_ns),
            "mode_bits": int(stat.S_IMODE(value.st_mode))}


def _canonical(value: Mapping[str, Any], *, drop: str = "sha256") -> str:
    body = {key: item for key, item in value.items() if key != drop}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _role_map(value: Any, role: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise RebindError(f"{role} must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise RebindError(f"{role} contains a malformed role")
        name = str(item["role"])
        if name in result:
            raise RebindError(f"{role} repeats {name}")
        result[name] = item
    return result


def _old_actionable_paths(value: Any, *, key: str = "") -> list[Path]:
    found: list[Path] = []
    if isinstance(value, Mapping):
        for name, item in value.items():
            found.extend(_old_actionable_paths(item, key=str(name)))
    elif isinstance(value, list):
        for item in value:
            found.extend(_old_actionable_paths(item, key=key))
    elif isinstance(value, str) and key in ACTIONABLE_KEYS and value.startswith("/"):
        found.append(Path(value).expanduser().resolve(strict=False))
    return found


def _assert_no_old_actionable(value: Any, namespace: Path, role: str) -> None:
    for path in _old_actionable_paths(value):
        if not _inside(path, namespace):
            raise RebindError(f"{role} retains an actionable path outside copied namespace: {path}")


def _validate_plan(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise RebindError("input plan is not the canonical V3 plan")
    selection = plan.get("selection")
    if not isinstance(selection, Mapping) or selection.get("current_index") != 65:
        raise RebindError("plan does not select canonical CURRENT row 65")
    if plan.get("raw_binding", {}).get("expected_raw_tree_sha256") != PENDING:
        raise RebindError("input V3 plan must still defer raw-tree content")
    request = plan.get("request_overlay", {}).get("request")
    if not isinstance(request, Mapping) or request.get("schema") != REQUEST_SCHEMA:
        raise RebindError("V3 worker request overlay is missing")
    if request.get("source_hashes_preverified_by_parent") is not False:
        raise RebindError("V3 request must begin with parent content verification disabled")
    return request


def _module_entry(item: Mapping[str, Any], role: str, namespace: Path,
                  old: Mapping[str, Any]) -> dict[str, Any]:
    path = _target(item.get("path"), f"modules.{role}", namespace, must_exist=True)
    digest = _sha(item.get("sha256"), f"modules.{role}.sha256")
    old_digest = _sha(old.get("sha256"), f"plan.modules.{role}.sha256", pending=True)
    if old_digest is not None and digest != old_digest:
        raise RebindError(f"module content SHA differs from V3 plan: {role}")
    target_stat = _stat(item, f"modules.{role}")
    actual = _actual_stat(path)
    if actual != target_stat:
        raise RebindError(f"modules.{role} target stat differs from binding")
    if not (target_stat["mode_bits"] & 0o400):
        raise RebindError(f"modules.{role} is not readable")
    return {"role": role, "path": str(path), "sha256": digest,
            "target_stat": target_stat, "content_status": item.get("content_status")}


def _source_entry(item: Mapping[str, Any], role: str, namespace: Path,
                  old: Mapping[str, Any]) -> dict[str, Any]:
    path = _target(item.get("path"), f"source_files.{role}", namespace, must_exist=True)
    digest = _sha(item.get("sha256"), f"source_files.{role}.sha256", pending=True)
    old_digest = _sha(old.get("sha256"), f"plan.source_files.{role}.sha256", pending=True)
    if old_digest is not None and digest is not None and old_digest != digest:
        raise RebindError(f"source content SHA differs from V3 plan: {role}")
    target_stat = _stat(item, f"source_files.{role}")
    if _actual_stat(path) != target_stat:
        raise RebindError(f"source_files.{role} target stat differs from binding")
    result = {"role": role, "path": str(path), "sha256": digest or PENDING,
              "bytes": target_stat["st_size"], "target_stat": target_stat,
              "content_sha_status": item.get("content_status", "PARENT_GUARD_REQUIRED"),
              "content_read_by_planner": False, "scientific_payload_stat_only": True}
    return result


def _raw_binding(binding: Mapping[str, Any], old: Mapping[str, Any], namespace: Path) -> tuple[dict[str, Any], bool]:
    data_root = _directory(binding.get("data_root"), "raw_binding.data_root", namespace)
    old_frames = old.get("frames")
    frames = binding.get("frames")
    if not isinstance(old_frames, list) or not isinstance(frames, list) or len(old_frames) != len(frames):
        raise RebindError("raw frame count differs from V3 plan")
    ready = True
    result_frames: list[dict[str, Any]] = []
    for index, (old_item, item) in enumerate(zip(old_frames, frames)):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise RebindError("raw frames must be contiguous from frame zero")
        path = _target(item.get("path"), f"raw_binding.frames[{index}]", namespace, must_exist=True)
        if path.parent != data_root or path.name != f"Part_{index:04d}.bi4":
            raise RebindError(f"raw frame {index} is not the exact top-level Part path")
        target_stat = _stat(item, f"raw_binding.frames[{index}]")
        if _actual_stat(path) != target_stat:
            raise RebindError(f"raw frame {index} target stat differs from binding")
        expected_bytes = old_item.get("bytes") if isinstance(old_item, Mapping) else None
        if isinstance(expected_bytes, int) and target_stat["st_size"] != expected_bytes:
            raise RebindError(f"raw frame {index} byte count differs from V3 plan")
        digest = _sha(item.get("sha256"), f"raw_binding.frames[{index}].sha256", pending=True)
        if digest is None or item.get("content_status") != "VERIFIED_AFTER_RESERVATION":
            ready = False
        result_frames.append({"frame": index, "path": str(path), "bytes": target_stat["st_size"],
                              "mtime_ns": target_stat["st_mtime_ns"], "sha256": digest or PENDING,
                              "content_sha_status": item.get("content_status", "PARENT_GUARD_REQUIRED"),
                              "target_stat": target_stat})
    tree = _sha(binding.get("expected_raw_tree_sha256"), "raw_binding.expected_raw_tree_sha256", pending=True)
    if tree is None or binding.get("tree_content_status") != "VERIFIED_AFTER_RESERVATION":
        ready = False
    result = {"data_root": str(data_root), "frame_count": len(result_frames),
              "expected_file_count": int(binding.get("expected_file_count", old.get("expected_file_count", 0))),
              "frame_pattern": "Part_%04d.bi4", "frames": result_frames,
              "expected_raw_tree_sha256": tree or PENDING,
              "source_tree_hash_basis": "all copied top-level raw files; parent hashes after reservation",
              "content_hash_status": "VERIFIED_AFTER_RESERVATION" if ready else "PARENT_GUARD_REQUIRED"}
    return result, ready


def _validate_v15(value: Any, namespace: Path) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RebindError("parent binding must include a rebuilt v15_request")
    result = copy.deepcopy(dict(value))
    if result.get("source_fallback") not in {"REJECT", "FORBIDDEN"}:
        raise RebindError("rebuilt v15_request must reject source fallback")
    _assert_no_old_actionable(result, namespace, "v15_request")
    return result


def rebind(*, plan_path: Path | str, binding_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    plan = _json(plan_path, "V3 plan")
    old_request = _validate_plan(plan)
    binding = _json(binding_path, "parent source binding")
    if binding.get("schema") != BINDING_SCHEMA:
        raise RebindError("unsupported parent source binding schema")
    namespace_value = binding.get("namespace_root")
    if not isinstance(namespace_value, str):
        raise RebindError("namespace_root is required")
    namespace = Path(namespace_value).expanduser().resolve(strict=False)
    if not namespace.is_absolute():
        raise RebindError("namespace_root must be absolute")
    modules = binding.get("modules")
    old_modules = old_request.get("modules")
    if not isinstance(modules, Mapping) or not isinstance(old_modules, Mapping):
        raise RebindError("module closure is missing")
    rebound_modules = {}
    for role in MODULE_ROLES:
        if role not in modules or role not in old_modules:
            raise RebindError(f"module role missing: {role}")
        rebound_modules[role] = _module_entry(modules[role], role, namespace, old_modules[role])

    old_sources = _role_map(old_request.get("source_files"), "plan.source_files")
    source_items = _role_map(binding.get("source_files"), "binding.source_files")
    if set(source_items) != set(REQUIRED_SOURCE_ROLES) or not set(REQUIRED_SOURCE_ROLES).issubset(old_sources):
        raise RebindError("binding must contain the complete F2 source role set")
    rebound_sources = [_source_entry(source_items[role], role, namespace, old_sources[role])
                       for role in REQUIRED_SOURCE_ROLES]
    rebound_raw, raw_ready = _raw_binding(binding.get("raw_binding", {}), old_request["raw_binding"], namespace)
    decoder_value = binding.get("decoder")
    if not isinstance(decoder_value, Mapping):
        raise RebindError("decoder binding is missing")
    decoder_path = _target(decoder_value.get("path"), "decoder", namespace, must_exist=True)
    decoder_sha = _sha(decoder_value.get("sha256"), "decoder.sha256")
    decoder_stat = _stat(decoder_value, "decoder")
    if _actual_stat(decoder_path) != decoder_stat:
        raise RebindError("decoder target stat differs from binding")
    if not os.access(decoder_path, os.X_OK):
        raise RebindError("decoder target is not executable")
    python_value = binding.get("python_executable")
    if not isinstance(python_value, str) or not python_value.startswith("/"):
        raise RebindError("literal pinned python_executable is required")
    if "python3" in Path(python_value).name and ".venv" not in python_value:
        raise RebindError("system Python cannot replace the literal pinned venv")
    result_request = copy.deepcopy(dict(old_request))
    result_request.update({
        "status": "READY_FOR_PARENT_GUARD" if raw_ready and all(
            item["content_sha_status"] == "VERIFIED_AFTER_RESERVATION" for item in rebound_sources
        ) else "PENDING_PARENT_GUARD",
        "request_id": str(binding.get("request_id", "f2-s1-canonical-rebound-v1")),
        "modules": rebound_modules,
        "source_files": rebound_sources,
        "raw_binding": rebound_raw,
        "decoder": {"role": "raw_bi4_decoder", "path": str(decoder_path),
                     "sha256": decoder_sha, "target_stat": decoder_stat,
                     "content_status": decoder_value.get("content_status")},
        "source_hashes_preverified_by_parent": bool(raw_ready and all(
            item["content_sha_status"] == "VERIFIED_AFTER_RESERVATION" for item in rebound_sources
        )),
        "execution": {
            **dict(result_request.get("execution", {})),
            "python": python_value,
            "python_argv0_policy": "literal_pinned_interpreter",
            "bound_namespace_root": str(namespace),
            "source_content_read_phase": "after_parent_reservation",
            "old_root_open": "FORBIDDEN",
            "no_original_path_fallback": True,
        },
        "v15_request": _validate_v15(binding.get("v15_request"), namespace),
    })
    current_entry = next(item for item in rebound_sources if item["role"] == "current_catalog")
    result_request["current_binding"] = {
        **dict(result_request.get("current_binding", {})),
        "path": current_entry["path"],
        "sha256": current_entry["sha256"],
        "target_stat": current_entry["target_stat"],
        "binding_status": "COPIED_TARGET_PARENT_GUARD_BOUND",
    }
    _assert_no_old_actionable(result_request, namespace, "rebound request")
    result_request["sha256"] = _canonical(result_request)
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    request_path = _write_new(output / "f2-s1-canonical-rebound-request-v1.json", result_request)
    report = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARD" if result_request["status"] == "READY_FOR_PARENT_GUARD" else "PENDING_PARENT_GUARD",
        "metadata_only": True,
        "plan": {"path": str(Path(plan_path).expanduser().resolve()),
                  "schema": PLAN_SCHEMA, "selection": plan["selection"]},
        "binding": {"path": str(Path(binding_path).expanduser().resolve()),
                     "schema": BINDING_SCHEMA, "namespace_root": str(namespace)},
        "request": {"path": str(request_path), "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                    "schema": REQUEST_SCHEMA},
        "roles": {"modules": sorted(rebound_modules), "source_files": [item["role"] for item in rebound_sources],
                   "raw_frame_count": len(rebound_raw["frames"])},
        "content_contract": {
            "source_hashes_preverified_by_parent": result_request["source_hashes_preverified_by_parent"],
            "raw_tree_status": rebound_raw["content_hash_status"],
            "scientific_payload_read_by_rebinder": False,
            "verification_mode": "declared post-reservation SHA/stat join; no rebinder payload hash",
        },
        "fallback_policy": {"old_actionable_paths": "REJECT", "historical_alias": "REJECT",
                             "worktree_fallback": "REJECT", "literal_python_exception": python_value},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    report["sha256"] = _canonical(report)
    _write_new(output / "f2-s1-canonical-rebound-report-v1.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = rebind(plan_path=args.plan, binding_path=args.binding, output_dir=args.output_dir)
    except (OSError, RebindError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "request_path": result["request"]["path"], "request_sha256": result["request"]["sha256"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
