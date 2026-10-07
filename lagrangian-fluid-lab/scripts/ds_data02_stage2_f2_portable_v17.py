#!/usr/bin/env python3
"""Fail-closed portable overlay and replay preparation for the F2-S1 product.

The v16 metadata relocation helper can overwrite destinations and does not
bind a role overlay to the replay consumer.  This version keeps the original
source identity (URI, role, SHA, and producer binding) separate from a new
path overlay and refuses every existing output or bundle root.  Small files
are always content-hashed.  The trajectory is hashed only for an explicitly
parent-approved full replay.  No HDF5 dataset is opened by profile or
overlay preparation.

``prepare-replay`` emits a path-map document accepted by the v12 replay
runner.  The emitted consumer command names that document explicitly, so the
consumer cannot fall back to an original absolute path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import ds_data02_stage2_f2_portable_v16 as v16


PROFILE_SCHEMA = "ds02.stage2.f2-s1-portable-source-profile.v17"
OVERLAY_SCHEMA = "ds02.stage2.f2-s1-portable-overlay-verification.v17"
COPY_SCHEMA = "ds02.stage2.f2-s1-portable-copy-result.v17"
REPLAY_SCHEMA = "ds02.stage2.f2-s1-portable-replay-input.v17"
REQUEST_SCHEMA = v16.REQUEST_SCHEMA
H5_SUFFIXES = {".h5", ".hdf5"}
PROFILE_SCHEMAS = {PROFILE_SCHEMA, v16.PROFILE_SCHEMA}
SAFE_ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RESERVED_ROLES = {".", ".."}


class PortableV17BindingError(ValueError):
    """Raised when a portable v17 binding would be ambiguous or destructive."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PortableV17BindingError(f"{name} must be a lowercase SHA-256")
    return value


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    path = Path(path).expanduser()
    duplicates: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(), object_pairs_hook=pairs)
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV17BindingError(f"cannot read JSON: {path}: {error}") from error
    if duplicates:
        raise PortableV17BindingError(f"duplicate JSON key(s): {sorted(set(duplicates))}")
    if not isinstance(value, dict):
        raise PortableV17BindingError(f"JSON root must be an object: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    path = Path(path).expanduser()
    if path.exists():
        raise PortableV17BindingError(f"refusing to overwrite existing destination: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise PortableV17BindingError(f"refusing to overwrite existing destination: {path}") from error


def _safe_role(role: Any, name: str = "role") -> str:
    if not isinstance(role, str) or not SAFE_ROLE_RE.fullmatch(role) or role in RESERVED_ROLES:
        raise PortableV17BindingError(f"{name} is not a safe unique role: {role!r}")
    if "/" in role or "\\" in role or Path(role).is_absolute():
        raise PortableV17BindingError(f"{name} must not contain path separators: {role!r}")
    return role


def _safe_relative(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableV17BindingError(f"{name} must be a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableV17BindingError(f"{name} must not escape its bundle: {value!r}")
    # A colon is a Windows drive/path escape even when checked on POSIX.
    if re.match(r"^[A-Za-z]:", value):
        raise PortableV17BindingError(f"{name} must not contain a drive prefix")
    return "/".join(path.parts)


def _profile_roles(profile: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources = profile.get("original_sources")
    if not isinstance(sources, list) or not sources:
        raise PortableV17BindingError("profile original_sources are required")
    normalized: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_relative: set[str] = set()
    for index, raw in enumerate(sources):
        if not isinstance(raw, Mapping):
            raise PortableV17BindingError(f"original_sources[{index}] is malformed")
        role = _safe_role(raw.get("role"), f"original_sources[{index}].role")
        if role in seen_roles or role == "trajectory_h5":
            raise PortableV17BindingError(f"duplicate or reserved source role: {role}")
        seen_roles.add(role)
        expected = _require_sha(raw.get("content_sha256"), f"{role}.content_sha256")
        original = raw.get("original_path")
        if not isinstance(original, str) or not original:
            raise PortableV17BindingError(f"{role}.original_path is required")
        relative = raw.get("bundle_relative_path", f"sources/{role}/{Path(original).name}")
        relative = _safe_relative(relative, f"{role}.bundle_relative_path")
        if relative in seen_relative:
            raise PortableV17BindingError(f"duplicate bundle relative path: {relative}")
        seen_relative.add(relative)
        normalized.append({
            **dict(raw),
            "role": role,
            "content_sha256": expected,
            "original_path": original,
            "bundle_relative_path": relative,
        })
    h5 = profile.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise PortableV17BindingError("profile trajectory_h5 is required")
    h5_role = _safe_role(h5.get("role", "trajectory_h5"), "trajectory_h5.role")
    if h5_role != "trajectory_h5" or h5_role in seen_roles:
        raise PortableV17BindingError("trajectory_h5 role must be unique and exactly trajectory_h5")
    h5_path = h5.get("original_path")
    if not isinstance(h5_path, str) or not h5_path:
        raise PortableV17BindingError("trajectory_h5.original_path is required")
    h5_relative = _safe_relative(h5.get("bundle_relative_path", "trajectory/trajectory.h5"),
                                 "trajectory_h5.bundle_relative_path")
    if h5_relative in seen_relative:
        raise PortableV17BindingError(f"duplicate bundle relative path: {h5_relative}")
    h5_entry = {**dict(h5), "role": "trajectory_h5", "original_path": h5_path,
                "bundle_relative_path": h5_relative,
                "expected_content_sha256": _require_sha(h5.get("expected_content_sha256"),
                                                          "trajectory_h5.expected_content_sha256")}
    return normalized, h5_entry


def validate_profile(profile: Mapping[str, Any]) -> str:
    if not isinstance(profile, Mapping) or profile.get("schema") not in PROFILE_SCHEMAS:
        raise PortableV17BindingError("v17 or immutable v16 portable source profile is required")
    declared = _require_sha(profile.get("sha256"), "profile.sha256")
    if canonical_sha(profile) != declared:
        raise PortableV17BindingError("profile canonical SHA differs")
    sources, h5 = _profile_roles(profile)
    if profile.get("schema") == PROFILE_SCHEMA and any("bundle_relative_path" not in item for item in sources):
        raise PortableV17BindingError("v17 source entries require bundle_relative_path")
    overlay = profile.get("path_overlay")
    if isinstance(overlay, Mapping):
        role_to_path = overlay.get("role_to_path", {})
        if role_to_path is not None and not isinstance(role_to_path, Mapping):
            raise PortableV17BindingError("profile path_overlay.role_to_path must be an object")
        if isinstance(role_to_path, Mapping):
            for role in role_to_path:
                _safe_role(role, "path_overlay role")
    _require_sha(h5["expected_content_sha256"], "trajectory_h5.expected_content_sha256")
    return declared


def _entries(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources, h5 = _profile_roles(profile)
    return sources + [h5]


def _target_path(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PortableV17BindingError(f"path_map is missing role: {role}")
    if "\\" in value:
        raise PortableV17BindingError(f"path_map contains unsafe path for role: {role}")
    target = Path(value).expanduser()
    if not target.is_absolute() and any(part == ".." for part in target.parts):
        raise PortableV17BindingError(f"path_map escapes its working directory: {role}")
    return target


def _validate_map(profile: Mapping[str, Any], path_map: Mapping[str, Any], *, full_replay: bool,
                  reject_original_fallback: bool = True) -> dict[str, Any]:
    validate_profile(profile)
    if not isinstance(path_map, Mapping):
        raise PortableV17BindingError("path_map must be an object")
    entries = _entries(profile)
    expected_roles = {str(item["role"]) for item in entries}
    mapped_roles = {str(role) for role in path_map}
    if mapped_roles != expected_roles:
        missing = sorted(expected_roles - mapped_roles)
        extra = sorted(mapped_roles - expected_roles)
        raise PortableV17BindingError(f"path_map role set differs; missing={missing}, extra={extra}")
    records: list[dict[str, Any]] = []
    consumer_paths: dict[str, str] = {}
    original_paths: set[str] = set()
    for entry in entries:
        role = str(entry["role"])
        original = Path(str(entry["original_path"])).expanduser()
        original_paths.add(str(original.resolve()))
    for entry in entries:
        role = str(entry["role"])
        target = _target_path(path_map[role], role)
        if not target.is_file():
            raise PortableV17BindingError(f"relocated source is missing: {role}")
        resolved = target.resolve()
        if reject_original_fallback and str(resolved) in original_paths:
            raise PortableV17BindingError(f"path_map falls back to original source: {role}")
        expected = (_require_sha(entry.get("expected_content_sha256"), f"{role}.expected_content_sha256")
                    if role == "trajectory_h5" else _require_sha(entry.get("content_sha256"), f"{role}.content_sha256"))
        if role == "trajectory_h5":
            if target.suffix.lower() not in H5_SUFFIXES:
                raise PortableV17BindingError("trajectory_h5 overlay must be HDF5")
        actual_size = target.stat().st_size
        if actual_size != int(entry.get("bytes", -1)):
            raise PortableV17BindingError(f"relocated source byte size differs: {role}")
        actual: str | None = None
        if role != "trajectory_h5" or full_replay:
            actual = sha256(target)
            if actual != expected:
                raise PortableV17BindingError(f"relocated source SHA differs: {role}")
        consumer_paths[role] = str(resolved)
        record = {
            "role": role,
            "original_path": entry.get("original_path"),
            "relocated_path": str(resolved),
            "bytes": actual_size,
            "expected_sha256": expected,
            "original_mtime_ns": entry.get("original_mtime_ns"),
            "relocated_mtime_ns": target.stat().st_mtime_ns,
            "content_hash_verified": actual is not None,
        }
        if actual is not None:
            record["content_sha256"] = actual
        else:
            record["content_hash_status"] = "PENDING_PARENT_APPROVED_FULL_REPLAY_HASH"
        records.append(record)
    return {"records": records, "consumer_paths": consumer_paths}


def build_profile(request_path: Path | str, sidecar_path: Path | str,
                  output_path: Path | str) -> dict[str, Any]:
    """Build a new v17 profile without replacing any existing profile."""
    output = Path(output_path).expanduser()
    if output.exists():
        raise PortableV17BindingError(f"refusing to overwrite existing destination: {output}")
    profile = v16.build_profile(request_path, sidecar_path, output_path=None)
    profile = json.loads(json.dumps(profile))
    profile["schema"] = PROFILE_SCHEMA
    profile["profile_id"] = "f2-s1-portable-source-profile-v17-001"
    profile["status"] = "READY_FOR_SMALL_SOURCE_RELOCATION; HDF5_FULL_HASH_PENDING"
    for entry in profile.get("original_sources", []):
        role = _safe_role(entry.get("role"), "original_sources.role")
        entry["bundle_relative_path"] = f"sources/{role}/{Path(str(entry['original_path'])).name}"
    profile["trajectory_h5"]["bundle_relative_path"] = "trajectory/trajectory.h5"
    profile["relocation_policy"] = {
        "existing_profile_or_bundle": "reject; never overwrite",
        "small_sources": "full SHA-256 required at relocated path; path and mtime may change",
        "trajectory_h5": "full content SHA-256 required before full replay; stat-only is insufficient",
        "same_size_wrong_content": "reject",
        "original_absolute_paths": "identity only; replay consumer receives relocated role overlay",
        "hdf5_dataset_read_by_profile_builder": False,
    }
    profile["role_overlay"] = {
        "consumer": "ds_data02_stage2_f2_replay_runner_v12.run",
        "argument": "--path-map",
        "original_path_fallback": "forbidden",
    }
    profile["sha256"] = canonical_sha(profile)
    validate_profile(profile)
    _write_new(output, profile)
    return profile


def verify_relocated_profile(profile: Mapping[str, Any], path_map: Mapping[str, Any], *,
                             full_replay: bool = False) -> dict[str, Any]:
    """Verify a role-complete overlay; the returned consumer input has no originals."""
    declared = validate_profile(profile)
    checked = _validate_map(profile, path_map, full_replay=full_replay)
    return {
        "schema": OVERLAY_SCHEMA,
        "status": "FULL_REPLAY_SOURCE_VERIFIED" if full_replay else "SMALL_SOURCE_VERIFIED_HDF5_CONTENT_PENDING",
        "profile_schema": profile.get("schema"),
        "profile_sha256": declared,
        "path_map": checked["consumer_paths"],
        "source_records": checked["records"],
        "consumer_input": {
            "role_to_relocated_path": checked["consumer_paths"],
            "original_path_fallback": "FORBIDDEN",
            "trajectory_h5_role": "trajectory_h5",
        },
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _copy_new(source: Path, destination: Path) -> None:
    if destination.exists():
        raise PortableV17BindingError(f"refusing to overwrite copied source: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(source, destination)
    except FileExistsError as error:
        raise PortableV17BindingError(f"refusing to overwrite copied source: {destination}") from error


def copy_bundle(profile: Mapping[str, Any], bundle_root: Path | str, *,
                copy_hdf5: bool = False, io_slot_approved: bool = False) -> dict[str, Any]:
    """Copy to a new root only; an existing root is always a hard error."""
    validate_profile(profile)
    if copy_hdf5 and not io_slot_approved:
        raise PortableV17BindingError("copying trajectory HDF5 requires parent --io-slot-approved")
    root = Path(bundle_root).expanduser()
    if root.exists():
        raise PortableV17BindingError(f"refusing to use existing bundle root: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    path_map: dict[str, str] = {}
    for entry in _entries(profile):
        role = str(entry["role"])
        if role == "trajectory_h5" and not copy_hdf5:
            continue
        original = Path(str(entry["original_path"])).expanduser()
        if not original.is_file():
            raise PortableV17BindingError(f"source is missing: {role}")
        relative = _safe_relative(entry["bundle_relative_path"], f"{role}.bundle_relative_path")
        destination = root / PurePosixPath(relative)
        _copy_new(original, destination)
        expected = (entry["expected_content_sha256"] if role == "trajectory_h5" else entry["content_sha256"])
        expected = _require_sha(expected, f"{role}.expected_sha256")
        if sha256(destination) != expected:
            raise PortableV17BindingError(f"copied source SHA differs: {role}")
        path_map[role] = str(destination.resolve())
    return {
        "schema": COPY_SCHEMA,
        "status": "COPIED_WITH_HDF5_CONTENT_VERIFIED" if copy_hdf5 else "COPIED_SMALL_SOURCES_HDF5_PENDING",
        "bundle_root": str(root.resolve()),
        "path_map": path_map,
        "trajectory_h5": {"content_hash_verified": bool(copy_hdf5)},
        "output_overwrite_policy": "REJECT_EXISTING_DESTINATIONS",
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def prepare_replay(profile: Mapping[str, Any], path_map: Mapping[str, Any], request_path: Path | str,
                   output_path: Path | str, *, full_replay: bool = False) -> dict[str, Any]:
    """Emit the role overlay that is explicitly passed to the v12 consumer."""
    output = Path(output_path).expanduser()
    if output.exists():
        raise PortableV17BindingError(f"refusing to overwrite existing destination: {output}")
    request_file = Path(request_path).expanduser().resolve()
    request = _load(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PortableV17BindingError("the v15 replay request schema is required")
    profile_request = profile.get("request") if isinstance(profile, Mapping) else None
    if isinstance(profile_request, Mapping):
        expected_request = profile_request.get("content_sha256")
        if expected_request and sha256(request_file) != expected_request:
            raise PortableV17BindingError("replay request content differs from profile binding")
    verification = verify_relocated_profile(profile, path_map, full_replay=full_replay)
    runner = Path(__file__).resolve().with_name("ds_data02_stage2_f2_replay_runner_v12.py")
    payload = {
        "schema": REPLAY_SCHEMA,
        "status": "READY_FOR_FULL_REPLAY_CONSUMER" if full_replay else "OVERLAY_READY_HDF5_HASH_PENDING",
        "profile_sha256": verification["profile_sha256"],
        "request": {"path": str(request_file), "content_sha256": sha256(request_file),
                     "schema": request.get("schema")},
        # This exact role map is the input consumed by v12 --path-map.  No
        # original absolute path is inserted into the consumer input.
        "path_map": verification["path_map"],
        "consumer_input": verification["consumer_input"],
        "consumer_command": [
            sys.executable, str(runner), "--request", str(request_file),
            "--path-map", str(output.resolve()), "--output", "{replay_result_output}",
        ],
        "source_records": verification["source_records"],
        "full_replay_content_hash_verified": full_replay,
        "module": {"runner": str(runner), "runner_sha256": sha256(runner) if runner.is_file() else None},
        "dependency_license": "v13 READER_DEPENDENCY_LICENSE_INDEX; profile/runner/source hashes remain bound",
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _write_new(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-profile")
    build.add_argument("--request", type=Path, required=True)
    build.add_argument("--sidecar", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-overlay")
    verify.add_argument("--profile", type=Path, required=True)
    verify.add_argument("--path-map", type=Path, required=True)
    verify.add_argument("--full-replay", action="store_true")
    verify.add_argument("--output", type=Path, required=True)
    copy = sub.add_parser("copy-bundle")
    copy.add_argument("--profile", type=Path, required=True)
    copy.add_argument("--bundle-root", type=Path, required=True)
    copy.add_argument("--copy-hdf5", action="store_true")
    copy.add_argument("--io-slot-approved", action="store_true")
    copy.add_argument("--output", type=Path, required=True)
    replay = sub.add_parser("prepare-replay")
    replay.add_argument("--profile", type=Path, required=True)
    replay.add_argument("--path-map", type=Path, required=True)
    replay.add_argument("--request", type=Path, required=True)
    replay.add_argument("--full-replay", action="store_true")
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-profile":
            result = build_profile(args.request, args.sidecar, args.output)
        elif args.command == "verify-overlay":
            result = verify_relocated_profile(_load(args.profile), _load(args.path_map),
                                              full_replay=args.full_replay)
            _write_new(args.output, result)
        elif args.command == "copy-bundle":
            result = copy_bundle(_load(args.profile), args.bundle_root,
                                 copy_hdf5=args.copy_hdf5, io_slot_approved=args.io_slot_approved)
            _write_new(args.output, result)
        else:
            result = prepare_replay(_load(args.profile), _load(args.path_map), args.request,
                                    args.output, full_replay=args.full_replay)
    except (OSError, PortableV17BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
