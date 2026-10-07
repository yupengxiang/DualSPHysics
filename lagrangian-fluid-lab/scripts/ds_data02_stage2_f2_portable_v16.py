#!/usr/bin/env python3
"""Portable source-profile and relocation verifier for the v15 F2 replay.

The profile records original source URIs, roles, and content hashes separately
from a later path overlay.  Building the profile hashes only the bound small
inputs and reads HDF5 metadata with ``stat``; it never opens an HDF5 dataset.
Copying or verifying a relocated trajectory for full replay is an explicit
parent-guard action and requires a full content SHA-256 check.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping


PROFILE_SCHEMA = "ds02.stage2.f2-s1-portable-source-profile.v16"
REQUEST_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
SIDECAR_SCHEMA = "ds02.stage2.f2-s1-flux-forward-sidecar.v16"
H5_SUFFIXES = {".h5", ".hdf5"}


class PortableV16BindingError(ValueError):
    """Raised when a portable profile or path overlay is not source-bound."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value.lower()):
        raise PortableV16BindingError(f"{name} must be a lowercase SHA-256")
    return value.lower()


def _canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV16BindingError(f"cannot read JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV16BindingError(f"JSON root must be an object: {path}")
    return value


def _small_source(path: Path, role: str, expected: str) -> dict[str, Any]:
    if path.suffix.lower() in H5_SUFFIXES:
        raise PortableV16BindingError(f"HDF5 cannot be a small source: {role}")
    if not path.is_file():
        raise PortableV16BindingError(f"small source is missing: {role}: {path}")
    actual = sha256(path)
    if actual != expected:
        raise PortableV16BindingError(f"small source SHA differs: {role}")
    stat = path.stat()
    return {
        "role": role,
        "original_path": str(path.resolve()),
        "content_sha256": expected,
        "bytes": stat.st_size,
        "original_mtime_ns": stat.st_mtime_ns,
    }


def _validate_sidecar(sidecar_path: Path, sidecar: Mapping[str, Any]) -> dict[str, Any]:
    if sidecar.get("schema") != SIDECAR_SCHEMA:
        raise PortableV16BindingError("v16 forward sidecar schema is required")
    declared = _require_sha(sidecar.get("sha256"), "sidecar.sha256")
    if _canonical_sha(sidecar) != declared:
        raise PortableV16BindingError("v16 sidecar canonical SHA differs")
    report = sidecar.get("source_report")
    if not isinstance(report, Mapping) or not isinstance(report.get("path"), str):
        raise PortableV16BindingError("sidecar source_report path is required")
    report_path = Path(str(report["path"])).expanduser()
    expected_report = _require_sha(report.get("sha256"), "sidecar.source_report.sha256")
    if not report_path.is_file() or sha256(report_path) != expected_report:
        raise PortableV16BindingError("sidecar source report path/content SHA differs")
    return {
        "role": "completed_v15_report_json",
        "original_path": str(report_path.resolve()),
        "content_sha256": expected_report,
        "bytes": report_path.stat().st_size,
        "original_mtime_ns": report_path.stat().st_mtime_ns,
    }


def build_profile(request_path: Path | str, sidecar_path: Path | str,
                  output_path: Path | str | None = None) -> dict[str, Any]:
    """Hash small v15 inputs and emit a relocation-ready source profile."""
    request_path = Path(request_path).expanduser().resolve()
    sidecar_path = Path(sidecar_path).expanduser().resolve()
    request = _load(request_path)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PortableV16BindingError("the v15 replay request schema is required")
    sidecar = _load(sidecar_path)
    report_entry = _validate_sidecar(sidecar_path, sidecar)
    source_files = request.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise PortableV16BindingError("v15 request source_files are required")
    roles: set[str] = set()
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(source_files):
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise PortableV16BindingError(f"source_files[{index}] is malformed")
        role = str(item["role"])
        if role in roles:
            raise PortableV16BindingError(f"duplicate source role: {role}")
        roles.add(role)
        path = Path(str(item.get("path", ""))).expanduser()
        expected = _require_sha(item.get("sha256"), f"source_files[{index}].sha256")
        sources.append(_small_source(path, role, expected))
    source_binding = sidecar.get("source_binding")
    binding_files = source_binding.get("source_files") if isinstance(source_binding, Mapping) else None
    if not isinstance(binding_files, Mapping):
        raise PortableV16BindingError("sidecar source_binding.source_files is required")
    request_hashes = {item["role"]: item["sha256"] for item in source_files}
    if dict(binding_files) != request_hashes:
        raise PortableV16BindingError("sidecar and v15 request small-source hash maps differ")

    trajectory = request.get("trajectory_h5")
    migration = request.get("portable_migration")
    if not isinstance(trajectory, Mapping) or not isinstance(migration, Mapping):
        raise PortableV16BindingError("trajectory_h5 and portable_migration are required")
    h5_path = Path(str(trajectory.get("path", ""))).expanduser()
    if h5_path.suffix.lower() not in H5_SUFFIXES or not h5_path.is_file():
        raise PortableV16BindingError(f"trajectory HDF5 is missing: {h5_path}")
    h5_stat = h5_path.stat()
    h5_producer = _require_sha(trajectory.get("producer_declared_sha256"),
                                "trajectory_h5.producer_declared_sha256")
    h5_expected_content = _require_sha(
        migration.get("expected_trajectory_content_sha256"),
        "portable_migration.expected_trajectory_content_sha256")
    if h5_expected_content != h5_producer:
        raise PortableV16BindingError("portable HDF5 content contract differs from producer SHA")
    if h5_stat.st_size != int(trajectory.get("bytes", -1)):
        raise PortableV16BindingError("trajectory HDF5 byte size differs from v15 request")
    if (isinstance(source_binding, Mapping) and
            source_binding.get("trajectory_h5_producer_sha256") != h5_producer):
        raise PortableV16BindingError("sidecar and v15 request trajectory producer SHA differ")

    source_entries = [report_entry,
                      {"role": "v16_flux_forward_sidecar",
                       "original_path": str(sidecar_path),
                       "content_sha256": sha256(sidecar_path),
                       "bytes": sidecar_path.stat().st_size,
                       "original_mtime_ns": sidecar_path.stat().st_mtime_ns}]
    source_entries.extend(sources)
    profile: dict[str, Any] = {
        "schema": PROFILE_SCHEMA,
        "profile_id": "f2-s1-portable-source-profile-v16-001",
        "status": "READY_FOR_SMALL_SOURCE_RELOCATION; HDF5_FULL_HASH_PENDING",
        "request": {
            "path": str(request_path),
            "schema": request.get("schema"),
            "request_id": request.get("request_id"),
            "content_sha256": sha256(request_path),
        },
        "sidecar": {
            "path": str(sidecar_path),
            "schema": sidecar.get("schema"),
            "content_sha256": sha256(sidecar_path),
            "declared_canonical_sha256": sidecar.get("sha256"),
        },
        "source_identity": {
            "current_catalog_sha256": binding_files.get("current_catalog"),
            "trajectory_h5_producer_sha256": h5_producer,
            "small_source_hashes": request_hashes,
            "source_report_sha256": report_entry["content_sha256"],
        },
        "original_sources": source_entries,
        "trajectory_h5": {
            "role": "trajectory_h5",
            "original_path": str(h5_path.resolve()),
            "producer_declared_sha256": h5_producer,
            "expected_content_sha256": h5_expected_content,
            "bytes": h5_stat.st_size,
            "original_mtime_ns": h5_stat.st_mtime_ns,
            "content_hash_verified": False,
            "content_hash_status": "NOT_READ_BY_PROFILE_BUILDER",
        },
        "path_overlay": {
            "status": "NONE_ORIGINAL_PATHS_ONLY",
            "role_to_path": {},
            "mtime_is_provenance_not_identity": True,
        },
        "relocation_policy": {
            "small_sources": "full SHA-256 required at relocated path; path and mtime may change",
            "trajectory_h5": "full content SHA-256 required before full replay; stat-only is insufficient",
            "same_size_wrong_content": "reject",
            "hdf5_dataset_read_by_profile_builder": False,
        },
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    profile["sha256"] = _canonical_sha(profile)
    if output_path is not None:
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return profile


def verify_relocated_profile(profile: Mapping[str, Any], path_map: Mapping[str, str], *,
                             full_replay: bool = False) -> dict[str, Any]:
    """Verify a complete role overlay; HDF5 content is hashed only for full replay."""
    if not isinstance(profile, Mapping) or profile.get("schema") != PROFILE_SCHEMA:
        raise PortableV16BindingError("v16 portable source profile is required")
    if not isinstance(path_map, Mapping):
        raise PortableV16BindingError("path_map must be an object")
    mapped = {str(role): str(path) for role, path in path_map.items()}
    sources = profile.get("original_sources")
    if not isinstance(sources, list) or not sources:
        raise PortableV16BindingError("profile original_sources are required")
    records: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            raise PortableV16BindingError("profile source entry is malformed")
        role = str(source.get("role"))
        target = Path(mapped.get(role, "")).expanduser()
        if not target.is_file():
            raise PortableV16BindingError(f"relocated source is missing: {role}")
        expected = _require_sha(source.get("content_sha256"), f"{role}.content_sha256")
        actual = sha256(target)
        if actual != expected:
            raise PortableV16BindingError(f"relocated source SHA differs: {role}")
        stat = target.stat()
        records.append({
            "role": role,
            "original_path": source.get("original_path"),
            "relocated_path": str(target.resolve()),
            "content_sha256": expected,
            "original_mtime_ns": source.get("original_mtime_ns"),
            "relocated_mtime_ns": stat.st_mtime_ns,
            "bytes": stat.st_size,
        })
    h5 = profile.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise PortableV16BindingError("profile trajectory_h5 is required")
    h5_target = Path(mapped.get("trajectory_h5", "")).expanduser()
    if not h5_target.is_file() or h5_target.suffix.lower() not in H5_SUFFIXES:
        raise PortableV16BindingError("relocated trajectory HDF5 is missing")
    h5_stat = h5_target.stat()
    if h5_stat.st_size != int(h5.get("bytes", -1)):
        raise PortableV16BindingError("relocated trajectory HDF5 byte size differs")
    expected_h5 = _require_sha(h5.get("expected_content_sha256"),
                               "trajectory_h5.expected_content_sha256")
    h5_record: dict[str, Any] = {
        "role": "trajectory_h5",
        "original_path": h5.get("original_path"),
        "relocated_path": str(h5_target.resolve()),
        "bytes": h5_stat.st_size,
        "original_mtime_ns": h5.get("original_mtime_ns"),
        "relocated_mtime_ns": h5_stat.st_mtime_ns,
        "content_hash_verified": False,
    }
    if full_replay:
        actual_h5 = sha256(h5_target)
        if actual_h5 != expected_h5:
            raise PortableV16BindingError("relocated trajectory HDF5 content SHA differs")
        h5_record.update({"content_sha256": actual_h5, "content_hash_verified": True})
    else:
        h5_record.update({"content_sha256": None, "content_hash_status": "PENDING_FULL_REPLAY_HASH"})
    return {
        "schema": "ds02.stage2.f2-s1-portable-overlay-verification.v16",
        "status": "FULL_REPLAY_SOURCE_VERIFIED" if full_replay else "SMALL_SOURCE_VERIFIED_HDF5_CONTENT_PENDING",
        "path_map": mapped,
        "source_records": records,
        "trajectory_h5": h5_record,
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def copy_bundle(profile: Mapping[str, Any], bundle_root: Path | str, *,
                copy_hdf5: bool = False, io_slot_approved: bool = False) -> dict[str, Any]:
    """Copy a profile's metadata/small sources; HDF5 copy is explicitly gated."""
    if copy_hdf5 and not io_slot_approved:
        raise PortableV16BindingError("copying trajectory HDF5 requires parent --io-slot-approved")
    root = Path(bundle_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path_map: dict[str, str] = {}
    for source in profile.get("original_sources", []):
        role = str(source["role"])
        original = Path(str(source["original_path"])).expanduser()
        destination = root / "sources" / role / original.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        expected = _require_sha(source.get("content_sha256"), f"{role}.content_sha256")
        if sha256(destination) != expected:
            raise PortableV16BindingError(f"copied source SHA differs: {role}")
        path_map[role] = str(destination.resolve())
    h5 = profile.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise PortableV16BindingError("profile trajectory_h5 is required")
    if copy_hdf5:
        original = Path(str(h5["original_path"])).expanduser()
        destination = root / "trajectory.h5"
        shutil.copyfile(original, destination)
        expected = _require_sha(h5.get("expected_content_sha256"), "trajectory_h5.expected_content_sha256")
        if sha256(destination) != expected:
            raise PortableV16BindingError("copied trajectory HDF5 content SHA differs")
        path_map["trajectory_h5"] = str(destination.resolve())
    return {
        "schema": "ds02.stage2.f2-s1-portable-copy-result.v16",
        "status": "COPIED_WITH_HDF5_CONTENT_VERIFIED" if copy_hdf5 else "COPIED_SMALL_SOURCES_HDF5_PENDING",
        "path_map": path_map,
        "trajectory_h5": {"content_hash_verified": bool(copy_hdf5)},
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    import argparse
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
    args = parser.parse_args()
    try:
        if args.command == "build-profile":
            result = build_profile(args.request, args.sidecar, args.output)
        elif args.command == "verify-overlay":
            result = verify_relocated_profile(_load(args.profile), _load(args.path_map),
                                              full_replay=args.full_replay)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        else:
            result = copy_bundle(_load(args.profile), args.bundle_root,
                                 copy_hdf5=args.copy_hdf5, io_slot_approved=args.io_slot_approved)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    except (OSError, PortableV16BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
