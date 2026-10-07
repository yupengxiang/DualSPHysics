#!/usr/bin/env python3
"""Fail-closed portable overlay and replay preparation for the F2-S1 product.

The v16 metadata relocation helper can overwrite destinations and does not
bind a role overlay to the replay consumer.  This version keeps the original
source identity (URI, role, SHA, and producer binding) separate from a new
path overlay and refuses every existing output or bundle root.  Small files
are always content-hashed.  The trajectory is hashed only for an explicitly
parent-approved full replay.  No HDF5 dataset is opened by profile or
overlay preparation.

``prepare-replay`` emits a path-map document accepted by the v15 replay
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


PROFILE_SCHEMA = "ds02.stage2.f2-s1-portable-source-profile.v24"
OVERLAY_SCHEMA = "ds02.stage2.f2-s1-portable-overlay-verification.v24"
COPY_SCHEMA = "ds02.stage2.f2-s1-portable-copy-result.v24"
REPLAY_SCHEMA = "ds02.stage2.f2-s1-portable-replay-input.v24"
REQUEST_SCHEMA = v16.REQUEST_SCHEMA
H5_SUFFIXES = {".h5", ".hdf5"}
PROFILE_SCHEMAS = {PROFILE_SCHEMA, v16.PROFILE_SCHEMA}
SAFE_ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RESERVED_ROLES = {".", ".."}


class PortableV24BindingError(ValueError):
    """Raised when a portable v24 binding would be ambiguous or destructive."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PortableV24BindingError(f"{name} must be a lowercase SHA-256")
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
        raise PortableV24BindingError(f"cannot read JSON: {path}: {error}") from error
    if duplicates:
        raise PortableV24BindingError(f"duplicate JSON key(s): {sorted(set(duplicates))}")
    if not isinstance(value, dict):
        raise PortableV24BindingError(f"JSON root must be an object: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    path = Path(path).expanduser()
    if path.exists():
        raise PortableV24BindingError(f"refusing to overwrite existing destination: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise PortableV24BindingError(f"refusing to overwrite existing destination: {path}") from error


def _safe_role(role: Any, name: str = "role") -> str:
    if not isinstance(role, str) or not SAFE_ROLE_RE.fullmatch(role) or role in RESERVED_ROLES:
        raise PortableV24BindingError(f"{name} is not a safe unique role: {role!r}")
    if "/" in role or "\\" in role or Path(role).is_absolute():
        raise PortableV24BindingError(f"{name} must not contain path separators: {role!r}")
    return role


def _safe_relative(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableV24BindingError(f"{name} must be a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableV24BindingError(f"{name} must not escape its bundle: {value!r}")
    # A colon is a Windows drive/path escape even when checked on POSIX.
    if re.match(r"^[A-Za-z]:", value):
        raise PortableV24BindingError(f"{name} must not contain a drive prefix")
    return "/".join(path.parts)


def _profile_roles(profile: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources = profile.get("original_sources")
    if not isinstance(sources, list) or not sources:
        raise PortableV24BindingError("profile original_sources are required")
    normalized: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_relative: set[str] = set()
    for index, raw in enumerate(sources):
        if not isinstance(raw, Mapping):
            raise PortableV24BindingError(f"original_sources[{index}] is malformed")
        role = _safe_role(raw.get("role"), f"original_sources[{index}].role")
        if role in seen_roles or role == "trajectory_h5":
            raise PortableV24BindingError(f"duplicate or reserved source role: {role}")
        seen_roles.add(role)
        expected = _require_sha(raw.get("content_sha256"), f"{role}.content_sha256")
        original = raw.get("original_path")
        if not isinstance(original, str) or not original:
            raise PortableV24BindingError(f"{role}.original_path is required")
        relative = raw.get("bundle_relative_path", f"sources/{role}/{Path(original).name}")
        relative = _safe_relative(relative, f"{role}.bundle_relative_path")
        if relative in seen_relative:
            raise PortableV24BindingError(f"duplicate bundle relative path: {relative}")
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
        raise PortableV24BindingError("profile trajectory_h5 is required")
    h5_role = _safe_role(h5.get("role", "trajectory_h5"), "trajectory_h5.role")
    if h5_role != "trajectory_h5" or h5_role in seen_roles:
        raise PortableV24BindingError("trajectory_h5 role must be unique and exactly trajectory_h5")
    h5_path = h5.get("original_path")
    if not isinstance(h5_path, str) or not h5_path:
        raise PortableV24BindingError("trajectory_h5.original_path is required")
    h5_relative = _safe_relative(h5.get("bundle_relative_path", "trajectory/trajectory.h5"),
                                 "trajectory_h5.bundle_relative_path")
    if h5_relative in seen_relative:
        raise PortableV24BindingError(f"duplicate bundle relative path: {h5_relative}")
    h5_entry = {**dict(h5), "role": "trajectory_h5", "original_path": h5_path,
                "bundle_relative_path": h5_relative,
                "expected_content_sha256": _require_sha(h5.get("expected_content_sha256"),
                                                          "trajectory_h5.expected_content_sha256")}
    return normalized, h5_entry


def _supporting_sources(profile: Mapping[str, Any], used_roles: set[str],
                        used_relative: set[str]) -> list[dict[str, Any]]:
    """Validate code/consumer/license files that make the replay entry portable."""
    raw_sources = profile.get("supporting_sources", [])
    if raw_sources is None:
        return []
    if not isinstance(raw_sources, list):
        raise PortableV24BindingError("profile supporting_sources must be a list")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sources):
        if not isinstance(raw, Mapping):
            raise PortableV24BindingError(f"supporting_sources[{index}] is malformed")
        role = _safe_role(raw.get("role"), f"supporting_sources[{index}].role")
        if role in used_roles:
            raise PortableV24BindingError(f"duplicate supporting source role: {role}")
        used_roles.add(role)
        original = raw.get("original_path")
        if not isinstance(original, str) or not original:
            raise PortableV24BindingError(f"{role}.original_path is required")
        relative = _safe_relative(raw.get("bundle_relative_path", f"runtime/{role}/{Path(original).name}"),
                                  f"{role}.bundle_relative_path")
        if relative in used_relative:
            raise PortableV24BindingError(f"duplicate bundle relative path: {relative}")
        used_relative.add(relative)
        result.append({
            **dict(raw),
            "role": role,
            "original_path": original,
            "content_sha256": _require_sha(raw.get("content_sha256"), f"{role}.content_sha256"),
            "bundle_relative_path": relative,
        })
    return result


def validate_profile(profile: Mapping[str, Any]) -> str:
    if not isinstance(profile, Mapping) or profile.get("schema") not in PROFILE_SCHEMAS:
        raise PortableV24BindingError("v24 or immutable v16 portable source profile is required")
    declared = _require_sha(profile.get("sha256"), "profile.sha256")
    if canonical_sha(profile) != declared:
        raise PortableV24BindingError("profile canonical SHA differs")
    sources, h5 = _profile_roles(profile)
    used_roles = {str(item["role"]) for item in sources} | {"trajectory_h5"}
    used_relative = {str(item["bundle_relative_path"]) for item in sources} | {str(h5["bundle_relative_path"])}
    _supporting_sources(profile, used_roles, used_relative)
    if profile.get("schema") == PROFILE_SCHEMA and any("bundle_relative_path" not in item for item in sources):
        raise PortableV24BindingError("v24 source entries require bundle_relative_path")
    overlay = profile.get("path_overlay")
    if isinstance(overlay, Mapping):
        role_to_path = overlay.get("role_to_path", {})
        if role_to_path is not None and not isinstance(role_to_path, Mapping):
            raise PortableV24BindingError("profile path_overlay.role_to_path must be an object")
        if isinstance(role_to_path, Mapping):
            for role in role_to_path:
                _safe_role(role, "path_overlay role")
    _require_sha(h5["expected_content_sha256"], "trajectory_h5.expected_content_sha256")
    return declared


def _entries(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources, h5 = _profile_roles(profile)
    used_roles = {str(item["role"]) for item in sources} | {"trajectory_h5"}
    used_relative = {str(item["bundle_relative_path"]) for item in sources} | {str(h5["bundle_relative_path"])}
    supporting = _supporting_sources(profile, used_roles, used_relative)
    return sources + supporting + [h5]


def _target_path(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PortableV24BindingError(f"path_map is missing role: {role}")
    if "\\" in value:
        raise PortableV24BindingError(f"path_map contains unsafe path for role: {role}")
    target = Path(value).expanduser()
    if not target.is_absolute() and any(part == ".." for part in target.parts):
        raise PortableV24BindingError(f"path_map escapes its working directory: {role}")
    return target


def _path_map_document(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept either a bare role map or a copy/overlay receipt containing one."""
    nested = value.get("path_map")
    if isinstance(nested, Mapping):
        return nested
    return value


def _validate_map(profile: Mapping[str, Any], path_map: Mapping[str, Any], *, full_replay: bool,
                  reject_original_fallback: bool = True) -> dict[str, Any]:
    validate_profile(profile)
    if not isinstance(path_map, Mapping):
        raise PortableV24BindingError("path_map must be an object")
    entries = _entries(profile)
    expected_roles = {str(item["role"]) for item in entries}
    mapped_roles = {str(role) for role in path_map}
    if mapped_roles != expected_roles:
        missing = sorted(expected_roles - mapped_roles)
        extra = sorted(mapped_roles - expected_roles)
        raise PortableV24BindingError(f"path_map role set differs; missing={missing}, extra={extra}")
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
            raise PortableV24BindingError(f"relocated source is missing: {role}")
        resolved = target.resolve()
        if reject_original_fallback and str(resolved) in original_paths:
            raise PortableV24BindingError(f"path_map falls back to original source: {role}")
        expected = (_require_sha(entry.get("expected_content_sha256"), f"{role}.expected_content_sha256")
                    if role == "trajectory_h5" else _require_sha(entry.get("content_sha256"), f"{role}.content_sha256"))
        if role == "trajectory_h5":
            if target.suffix.lower() not in H5_SUFFIXES:
                raise PortableV24BindingError("trajectory_h5 overlay must be HDF5")
        actual_size = target.stat().st_size
        if actual_size != int(entry.get("bytes", -1)):
            raise PortableV24BindingError(f"relocated source byte size differs: {role}")
        actual: str | None = None
        if role != "trajectory_h5" or full_replay:
            actual = sha256(target)
            if actual != expected:
                raise PortableV24BindingError(f"relocated source SHA differs: {role}")
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


def _path_role_aliases(profile: Mapping[str, Any], path_map: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return exact/suffix aliases for every source that a consumer can open."""
    entries = _entries(profile)
    mapped = _validate_map(profile, path_map, full_replay=False)["consumer_paths"]
    exact: dict[str, str] = {}
    suffix: dict[str, str] = {}
    suffix_collisions: set[str] = set()
    for entry in entries:
        role = str(entry["role"])
        original = str(entry["original_path"])
        exact[original] = mapped[role]
        try:
            exact[str(Path(original).expanduser().resolve())] = mapped[role]
        except OSError:
            pass
        # v15 source_code_binding carries repository-relative paths while the
        # source_files table carries absolute paths.  Match a full suffix,
        # never an ambiguous basename such as execution-receipt.json.
        normalized = original.replace("\\", "/")
        for marker in ("/lagrangian-fluid-lab/", "/src/source/"):
            if marker in normalized:
                suffix_key = normalized.split(marker, 1)[1]
                if suffix_key in suffix and suffix[suffix_key] != mapped[role]:
                    suffix_collisions.add(suffix_key)
                else:
                    suffix[suffix_key] = mapped[role]
    for key in suffix_collisions:
        suffix.pop(key, None)
    return exact, suffix


def _replace_bound_paths(value: Any, exact: Mapping[str, str], suffix: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        return {key: _replace_bound_paths(item, exact, suffix) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_bound_paths(item, exact, suffix) for item in value]
    if isinstance(value, str):
        if value in exact:
            return exact[value]
        normalized = value.replace("\\", "/")
        candidates = [mapped for source, mapped in suffix.items()
                      if normalized == source or normalized.endswith("/" + source)]
        if len(set(candidates)) == 1:
            return candidates[0]
        if len(set(candidates)) > 1:
            raise PortableV24BindingError(f"ambiguous actionable source path: {value}")
    return value


def _original_path_strings(value: Any, exact: Mapping[str, str], suffix: Mapping[str, str]) -> list[str]:
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_original_path_strings(item, exact, suffix))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_original_path_strings(item, exact, suffix))
        return result
    if not isinstance(value, str):
        return []
    normalized = value.replace("\\", "/")
    # Relocated targets are absolute paths too, so suffix matching is only
    # valid for repository-relative provenance strings.  Exact matching still
    # catches every original absolute URI.
    if value in exact or (not Path(value).is_absolute() and
                          any(normalized == source or normalized.endswith("/" + source) for source in suffix)):
        return [value]
    return []


def _validate_current_alias(request: Mapping[str, Any], profile: Mapping[str, Any],
                            role_paths: Mapping[str, str]) -> dict[str, Any] | None:
    """Bind a copied CURRENT byte image without rewriting its provenance.

    v14's historical cross-check distinguishes a migrated request by its
    legacy migration status, then checks the CURRENT row's case identity and
    producer HDF5 SHA while allowing the copied path/stat to differ.  Keep
    that compatibility status in the v24 overlay, but perform the stronger
    check here before the consumer starts: the copied CURRENT must have the
    exact declared bytes, exact case-78 identity/shape, and the original
    producer path/SHA in its JSON row.  A changed target mtime is accepted as
    a relocation fact and recorded separately.
    """
    target_value = role_paths.get("current_catalog")
    current_binding = request.get("current_binding")
    identity = request.get("case_identity")
    if target_value is None or not isinstance(current_binding, Mapping) or not isinstance(identity, Mapping):
        return None
    target = Path(target_value).expanduser().resolve()
    if not target.is_file():
        raise PortableV24BindingError("relocated CURRENT catalog is missing")
    profile_entry = next((item for item in _entries(profile)
                          if str(item.get("role")) == "current_catalog"), None)
    if not isinstance(profile_entry, Mapping):
        raise PortableV24BindingError("current_catalog profile role is required for CURRENT alias binding")
    expected = _require_sha(profile_entry.get("content_sha256"), "current_catalog.content_sha256")
    actual = sha256(target)
    if actual != expected:
        raise PortableV24BindingError("relocated CURRENT catalog content SHA-256 differs")
    try:
        catalog = _load(target)
    except PortableV24BindingError:
        raise
    cases = catalog.get("cases")
    case_index = current_binding.get("case_index")
    if isinstance(case_index, bool) or not isinstance(case_index, int) or not isinstance(cases, list) or case_index < 0 or case_index >= len(cases):
        raise PortableV24BindingError("relocated CURRENT case index is malformed")
    row = cases[case_index]
    if not isinstance(row, Mapping):
        raise PortableV24BindingError("relocated CURRENT case row is malformed")
    if (row.get("family_id") != identity.get("family_id") or
            row.get("physical_case_id") != identity.get("physical_case_id") or
            row.get("runtime_case_alias") != identity.get("runtime_case_alias") or
            row.get("frames") != current_binding.get("frames") or
            row.get("particles") != current_binding.get("particles")):
        raise PortableV24BindingError("relocated CURRENT case identity/shape differs")
    old_h5 = request.get("trajectory_h5")
    if not isinstance(old_h5, Mapping):
        raise PortableV24BindingError("original trajectory_h5 binding is required for CURRENT alias")
    producer_sha = _require_sha(old_h5.get("producer_declared_sha256"),
                                 "trajectory_h5.producer_declared_sha256")
    trajectory = row.get("trajectory")
    if not isinstance(trajectory, Mapping) or trajectory.get("producer_declared_sha256") != producer_sha:
        raise PortableV24BindingError("relocated CURRENT producer SHA differs")
    return {
        "role": "current_catalog",
        "original_path": str(profile_entry.get("original_path")),
        "relocated_path": str(target),
        "content_sha256": actual,
        "original_mtime_ns": profile_entry.get("original_mtime_ns"),
        "relocated_mtime_ns": target.stat().st_mtime_ns,
        "target_mtime_may_differ": True,
        "case_index": case_index,
        "physical_case_id": row.get("physical_case_id"),
        "runtime_case_alias": row.get("runtime_case_alias"),
        "frames": row.get("frames"),
        "particles": row.get("particles"),
        "producer_path_provenance": trajectory.get("path"),
        "producer_declared_sha256": producer_sha,
        "current_bytes_unchanged": True,
    }


def relocate_request_for_consumer(request: Mapping[str, Any], profile: Mapping[str, Any],
                                  path_map: Mapping[str, Any], *,
                                  overlay_receipt: Mapping[str, Any] | None = None,
                                  io_slot_approved: bool = False) -> dict[str, Any]:
    """Rebind every actionable v15 path, including nested motion engine paths.

    The inherited v14 mapper only rewrites ``source_files`` and the HDF5
    entry.  v15 independently opens ``motion_engine_sources`` and the
    official-motion entries in ``source_code_binding``.  Leaving those paths
    untouched would make a copied bundle silently read the original checkout.
    """
    validate_profile(profile)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PortableV24BindingError("v24 consumer requires the v15 replay request schema")
    exact, suffix = _path_role_aliases(profile, path_map)
    bound = json.loads(json.dumps(request))
    source_files = bound.get("source_files")
    if not isinstance(source_files, list):
        raise PortableV24BindingError("v15 request source_files are required")
    role_paths = {str(entry["role"]): str(path_map[str(entry["role"])])
                  for entry in _entries(profile) if str(entry["role"]) in path_map}
    for index, item in enumerate(source_files):
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise PortableV24BindingError(f"source_files[{index}] is malformed")
        role = str(item["role"])
        if role not in role_paths:
            raise PortableV24BindingError(f"source_files role lacks relocated overlay: {role}")
        item["path"] = role_paths[role]
    trajectory = bound.get("trajectory_h5")
    if not isinstance(trajectory, Mapping) or "trajectory_h5" not in role_paths:
        raise PortableV24BindingError("trajectory_h5 relocation is required")
    trajectory["path"] = role_paths["trajectory_h5"]
    bound = _replace_bound_paths(bound, exact, suffix)
    # Explicitly require the two nested structures used by the v15 validator.
    engine = bound.get("motion_engine_sources")
    if not isinstance(engine, Mapping):
        raise PortableV24BindingError("motion_engine_sources is required")
    for role, item in engine.items():
        if not isinstance(item, Mapping) or role not in role_paths:
            raise PortableV24BindingError(f"motion engine role lacks relocated overlay: {role}")
        item["path"] = role_paths[role]
    source_binding = bound.get("source_code_binding")
    if isinstance(source_binding, Mapping):
        official = source_binding.get("official_motion_engine")
        if not isinstance(official, Mapping):
            raise PortableV24BindingError("source_code_binding.official_motion_engine is required")
        for role, item in official.items():
            if isinstance(item, Mapping) and role in role_paths:
                item["path"] = role_paths[role]
    leftovers = _original_path_strings(bound, exact, suffix)
    if leftovers:
        raise PortableV24BindingError(
            "relocated consumer still contains original actionable path(s): " + ", ".join(sorted(set(leftovers))[:3])
        )
    # Keep every original-to-relocated alias, including the receipt and scan
    # roles.  The immutable v14 validator accepts the producer URI as a
    # receipt input key during migration.  A role map by itself loses that
    # alias and incorrectly rejects an otherwise byte-identical copied
    # reconciliation receipt.
    relocation_entries: list[dict[str, Any]] = []
    for entry in _entries(profile):
        role = str(entry["role"])
        if role not in role_paths:
            raise PortableV24BindingError(f"role lacks relocated overlay: {role}")
        target = Path(role_paths[role]).expanduser().resolve()
        original = Path(str(entry["original_path"])).expanduser()
        target_stat = target.stat()
        expected = (entry.get("expected_content_sha256") if role == "trajectory_h5"
                    else entry.get("content_sha256"))
        relocation_entries.append({
            "role": role,
            "original_path": str(original),
            "relocated_path": str(target),
            "bytes": int(target_stat.st_size),
            "expected_sha256": _require_sha(expected, f"{role}.expected_sha256"),
            "original_mtime_ns": entry.get("original_mtime_ns"),
            "relocated_mtime_ns": int(target_stat.st_mtime_ns),
            "content_hash_verified": role != "trajectory_h5",
        })
    bound["relocation"] = {
        "schema": "ds02.stage2.f2-s1-replay-relocation.v24",
        "role_to_path": dict(sorted(role_paths.items())),
        "entries": relocation_entries,
        "receipt_input_key_policy": {
            "accepted_aliases": "relocated absolute path or original producer path",
            "scientific_scan_role": "scientific_scan_sidecar",
            "content_sha256_must_match": True,
        },
        "original_paths_are_provenance_only": True,
        "original_path_fallback": "FORBIDDEN",
    }
    # The v15 consumer still performs its producer-stat check.  A copied
    # HDF5 file normally has a different mtime, so the overlay must bind the
    # *target* stat after a full content hash.  Keep the producer stat only as
    # provenance; never fake it on the relocated file and never accept a
    # same-size copy without the declared migration digest.
    h5_binding = bound.get("trajectory_h5")
    h5_target_value = role_paths.get("trajectory_h5")
    if not isinstance(h5_binding, dict) or h5_target_value is None:
        raise PortableV24BindingError("trajectory_h5 relocation is required")
    h5_target = Path(h5_target_value).expanduser()
    if not h5_target.is_file() or h5_target.suffix.lower() not in H5_SUFFIXES:
        raise PortableV24BindingError("relocated trajectory HDF5 is missing or not HDF5")
    producer_sha = _require_sha(h5_binding.get("producer_declared_sha256"),
                                 "trajectory_h5.producer_declared_sha256")
    migration = bound.get("portable_migration")
    if not isinstance(migration, Mapping):
        raise PortableV24BindingError("HDF5 relocation requires portable_migration")
    expected_content = _require_sha(
        migration.get("expected_trajectory_content_sha256"),
        "portable_migration.expected_trajectory_content_sha256")
    # A full overlay receipt is produced by ``prepare_replay`` after the
    # parent-approved copy worker has hashed the target.  Metadata preflight
    # consumes that receipt and only stats the target.  If no such receipt is
    # available, content hashing is allowed only for the explicit full replay
    # slot; metadata validation must fail closed without opening HDF5 bytes.
    receipt_hash: str | None = None
    if isinstance(overlay_receipt, Mapping):
        records = overlay_receipt.get("source_records", [])
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, Mapping) or record.get("role") != "trajectory_h5":
                    continue
                if record.get("content_hash_verified") is True:
                    candidate = record.get("content_sha256")
                    if isinstance(candidate, str) and HASH_RE.fullmatch(candidate):
                        receipt_hash = candidate
                        break
        if receipt_hash is None and overlay_receipt.get("full_replay_content_hash_verified") is True:
            candidate = overlay_receipt.get("trajectory_h5_content_sha256")
            if isinstance(candidate, str) and HASH_RE.fullmatch(candidate):
                receipt_hash = candidate
    if receipt_hash is not None:
        actual_content = receipt_hash
        content_hash_source = "FULL_OVERLAY_RECEIPT"
    elif io_slot_approved:
        actual_content = sha256(h5_target)
        content_hash_source = "PARENT_APPROVED_CURRENT_TARGET_FULL_HASH"
    else:
        raise PortableV24BindingError(
            "metadata relocation requires a full overlay content-SHA receipt; HDF5 content was not read")
    if actual_content != expected_content:
        raise PortableV24BindingError("relocated trajectory HDF5 content SHA-256 differs")
    old_h5 = Path(str(request.get("trajectory_h5", {}).get("path", ""))).expanduser()
    old_stat = old_h5.stat() if old_h5.is_file() else None
    new_stat = h5_target.stat()
    if new_stat.st_size != int(h5_binding.get("bytes", -1)):
        raise PortableV24BindingError("relocated trajectory HDF5 byte size differs")
    h5_binding["path"] = str(h5_target.resolve())
    h5_binding["bytes"] = new_stat.st_size
    h5_binding["mtime_ns"] = new_stat.st_mtime_ns
    h5_binding["content_sha256"] = actual_content
    # v14's immutable validator recognizes this legacy migration status.  The
    # v24 fields below carry the stronger content/target-stat evidence; the
    # original CURRENT and producer paths stay provenance only.
    bound["relocation"]["status"] = (
        "PORTABLE_STAT_MIGRATION_VERIFIED_SMALL_HASHES_HDF5_PRODUCER_ATTESTED")
    bound["relocation"]["v24_status"] = (
        "PORTABLE_FULL_CONTENT_HASH_MIGRATION_VERIFIED_TARGET_STAT_BOUND")
    bound["relocation"]["trajectory_h5"] = {
        "original_path": str(old_h5),
        "relocated_path": str(h5_target.resolve()),
        "bytes": new_stat.st_size,
        "producer_declared_sha256": producer_sha,
        "content_sha256": actual_content,
        "content_hash_verified": True,
        "original_mtime_ns": None if old_stat is None else old_stat.st_mtime_ns,
        "relocated_mtime_ns": new_stat.st_mtime_ns,
        "producer_mtime_is_provenance_only": True,
        "content_hash_source": content_hash_source,
    }
    for entry in relocation_entries:
        if entry["role"] == "trajectory_h5":
            entry["content_hash_verified"] = True
            entry["content_sha256"] = actual_content
            entry["relocated_mtime_ns"] = new_stat.st_mtime_ns
    current_alias = _validate_current_alias(request, profile, role_paths)
    if current_alias is not None:
        bound["relocation"]["current_catalog"] = current_alias
    bound["relocation"]["source_identity_policy"] = {
        "current_catalog_bytes": "exact profile SHA; copied path/stat overlay only",
        "current_case_identity": "validated from copied CURRENT row; case_id/family/shape remain frozen",
        "producer_h5_path": "original CURRENT trajectory.path retained as provenance",
        "producer_h5_sha256": "must equal frozen producer_declared_sha256",
        "target_mtime": "accepted only as copied target stat after full content SHA",
    }
    return bound


def build_profile(request_path: Path | str, sidecar_path: Path | str,
                  output_path: Path | str) -> dict[str, Any]:
    """Build a new v24 profile without replacing any existing profile."""
    output = Path(output_path).expanduser()
    if output.exists():
        raise PortableV24BindingError(f"refusing to overwrite existing destination: {output}")
    profile = v16.build_profile(request_path, sidecar_path, output_path=None)
    profile = json.loads(json.dumps(profile))
    profile["schema"] = PROFILE_SCHEMA
    profile["profile_id"] = "f2-s1-portable-source-profile-v24-001"
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
        "consumer": "ds_data02_stage2_f2_replay_runner_v15.run",
        "argument": "--path-map",
        "original_path_fallback": "forbidden",
    }
    source_request = _load(Path(str(profile["request"]["path"])))
    support_specs = [
        ("portable_v24_worker", Path(__file__), "runtime/portable/ds_data02_stage2_f2_portable_v24.py"),
        ("portable_v16_dependency", Path(__file__).with_name("ds_data02_stage2_f2_portable_v16.py"),
         "runtime/portable/ds_data02_stage2_f2_portable_v16.py"),
        ("replay_runner_v24", Path(__file__).with_name("ds_data02_stage2_f2_replay_runner_v24.py"),
         "runtime/replay/ds_data02_stage2_f2_replay_runner_v24.py"),
        ("replay_runner_v15", Path(__file__).with_name("ds_data02_stage2_f2_replay_runner_v15.py"),
         "runtime/replay/ds_data02_stage2_f2_replay_runner_v15.py"),
        ("replay_module_v15", Path(__file__).with_name("ds_data02_stage2_f2_replay_v15.py"),
         "runtime/replay/ds_data02_stage2_f2_replay_v15.py"),
        ("replay_module_v14", Path(__file__).with_name("ds_data02_stage2_f2_replay_v14.py"),
         "runtime/replay/ds_data02_stage2_f2_replay_v14.py"),
        ("replay_contract_tests_v15", Path(__file__).resolve().parents[1] /
         "tests/test_ds_data02_stage2_f2_replay_v15.py",
         "runtime/replay/test_ds_data02_stage2_f2_replay_v15.py"),
        ("dependency_license_index", Path(__file__).resolve().parents[1] /
         "campaigns/ds-data-02/stage2/replay/v13/READER_DEPENDENCY_LICENSE_INDEX_v13.json",
         "runtime/dependencies/READER_DEPENDENCY_LICENSE_INDEX_v13.json"),
        ("v15_replay_request", Path(str(profile["request"]["path"])),
         "runtime/request/f2-s1-replay-request-v15-001.json"),
    ]
    engine_sources = source_request.get("motion_engine_sources", {})
    if not isinstance(engine_sources, Mapping):
        raise PortableV24BindingError("v15 request motion_engine_sources are required")
    for role, item in sorted(engine_sources.items()):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise PortableV24BindingError(f"motion engine source is malformed: {role}")
        support_specs.append((str(role), Path(str(item["path"])),
                              f"runtime/engine/{Path(str(item['path'])).name}"))
    supporting: list[dict[str, Any]] = []
    for role, source, relative in support_specs:
        if not source.is_file():
            raise PortableV24BindingError(f"portable execution support is missing: {source}")
        supporting.append({
            "role": role,
            "original_path": str(source.resolve()),
            "content_sha256": sha256(source),
            "bytes": source.stat().st_size,
            "original_mtime_ns": source.stat().st_mtime_ns,
            "bundle_relative_path": relative,
        })
    profile["supporting_sources"] = supporting
    profile["execution_closure"] = {
        "consumer": "ds_data02_stage2_f2_replay_runner_v24.py -> ds_data02_stage2_f2_replay_v15.py",
        "modules": ["ds_data02_stage2_f2_replay_v15.py", "ds_data02_stage2_f2_replay_v14.py"],
        "portable_worker": "ds_data02_stage2_f2_portable_v24.py",
        "license_index_role": "dependency_license_index",
        "supporting_sources_are_copied_and_hash_verified": True,
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
    # The bundle root is new and immutable, but several roles intentionally
    # share a directory (for example runtime/portable/*.py).  Requiring every
    # parent mkdir to be ``exist_ok=False`` makes the second sibling fail even
    # though no destination file exists.  Allow only an existing directory
    # created inside this new bundle; preserve the hard refusal for a target
    # file, directory, or symlink.
    if destination.exists() or destination.is_symlink():
        raise PortableV24BindingError(f"refusing to overwrite copied source: {destination}")
    parent = destination.parent
    if parent.exists():
        if not parent.is_dir() or parent.is_symlink():
            raise PortableV24BindingError(f"copied source parent is not a real directory: {parent}")
    else:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError as error:
            raise PortableV24BindingError(f"copied source parent is not a directory: {parent}") from error
    try:
        shutil.copyfile(source, destination)
    except FileExistsError as error:
        raise PortableV24BindingError(f"refusing to overwrite copied source: {destination}") from error


def copy_bundle(profile: Mapping[str, Any], bundle_root: Path | str, *,
                copy_hdf5: bool = False, io_slot_approved: bool = False) -> dict[str, Any]:
    """Copy to a new root only; an existing root is always a hard error."""
    validate_profile(profile)
    if copy_hdf5 and not io_slot_approved:
        raise PortableV24BindingError("copying trajectory HDF5 requires parent --io-slot-approved")
    root = Path(bundle_root).expanduser()
    if root.exists():
        raise PortableV24BindingError(f"refusing to use existing bundle root: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    path_map: dict[str, str] = {}
    for entry in _entries(profile):
        role = str(entry["role"])
        if role == "trajectory_h5" and not copy_hdf5:
            continue
        original = Path(str(entry["original_path"])).expanduser()
        if not original.is_file():
            raise PortableV24BindingError(f"source is missing: {role}")
        relative = _safe_relative(entry["bundle_relative_path"], f"{role}.bundle_relative_path")
        destination = root / PurePosixPath(relative)
        _copy_new(original, destination)
        expected = (entry["expected_content_sha256"] if role == "trajectory_h5" else entry["content_sha256"])
        expected = _require_sha(expected, f"{role}.expected_sha256")
        if sha256(destination) != expected:
            raise PortableV24BindingError(f"copied source SHA differs: {role}")
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
                   output_path: Path | str, *, full_replay: bool = False,
                   profile_path: Path | str | None = None) -> dict[str, Any]:
    """Emit the role overlay that is explicitly passed to the v24/v15 consumer."""
    output = Path(output_path).expanduser()
    if output.exists():
        raise PortableV24BindingError(f"refusing to overwrite existing destination: {output}")
    request_file = Path(request_path).expanduser().resolve()
    request = _load(request_file)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PortableV24BindingError("the v15 replay request schema is required")
    profile_request = profile.get("request") if isinstance(profile, Mapping) else None
    if isinstance(profile_request, Mapping):
        expected_request = profile_request.get("content_sha256")
        if expected_request and sha256(request_file) != expected_request:
            raise PortableV24BindingError("replay request content differs from profile binding")
    verification = verify_relocated_profile(profile, path_map, full_replay=full_replay)
    runner = Path(__file__).resolve().with_name("ds_data02_stage2_f2_replay_runner_v24.py")
    runner_target = verification["path_map"].get("replay_runner_v24", str(runner.resolve()))
    request_target = verification["path_map"].get("v15_replay_request", str(request_file))
    profile_target = str(Path(profile_path).expanduser().resolve()) if profile_path is not None else "{profile_path}"
    payload = {
        "schema": REPLAY_SCHEMA,
        "status": "READY_FOR_FULL_REPLAY_CONSUMER" if full_replay else "OVERLAY_READY_HDF5_HASH_PENDING",
        "profile_sha256": verification["profile_sha256"],
        "request": {"path": str(request_file), "consumer_path": request_target,
                     "content_sha256": sha256(request_file), "schema": request.get("schema")},
        "profile_path": profile_target,
        # This exact role map is the input consumed by the v24 runner.  No
        # original absolute path is inserted into the consumer input.
        "path_map": verification["path_map"],
        "consumer_input": verification["consumer_input"],
        "consumer_command": [
            sys.executable, str(runner_target), "--profile", profile_target,
            "--request", str(request_target), "--path-map", str(output.resolve()),
            "--io-slot-approved", "--output", "{replay_result_output}",
        ],
        "source_records": verification["source_records"],
        "full_replay_content_hash_verified": full_replay,
        "module": {"runner": str(runner), "runner_target": str(runner_target),
                   "runner_sha256": sha256(runner) if runner.is_file() else None},
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
            result = verify_relocated_profile(_load(args.profile), _path_map_document(_load(args.path_map)),
                                              full_replay=args.full_replay)
            _write_new(args.output, result)
        elif args.command == "copy-bundle":
            result = copy_bundle(_load(args.profile), args.bundle_root,
                                 copy_hdf5=args.copy_hdf5, io_slot_approved=args.io_slot_approved)
            _write_new(args.output, result)
        else:
            result = prepare_replay(_load(args.profile), _path_map_document(_load(args.path_map)), args.request,
                                    args.output, full_replay=args.full_replay, profile_path=args.profile)
    except (OSError, PortableV24BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
