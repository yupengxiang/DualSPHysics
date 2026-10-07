#!/usr/bin/env python3
"""Build a source-bound v26 request for the relocated F2 typed replay.

The v25 metadata attempt is immutable evidence.  This forward request consumes
its profile, overlay, and preflight receipt and points the v25 runner at the
already copied v22 HDF5 target.  It never copies or opens the HDF5 dataset while
building or validating the request.  The parent guard must rehash that target
before the runner opens it and must wrap the runner in an OS-level ``strace``;
the Python audit hook in v25 cannot see every native HDF5 C open.

The request is typed-only: the v25/v15 consumer reads the typed HDF5 arrays and
computes the existing development labels/observers.  No BI4/raw
reconstruction, model, CFD, or scientific qualification is claimed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


REQUEST_SCHEMA = "ds02.request.v1"
ORCHESTRATION_SCHEMA = "ds02.stage2.f2-s1-typed-only-full401-replay.v26"
V25_METADATA_SCHEMA = "ds02.stage2.f2-s1-portable-metadata-probe.v25"
V25_PROFILE_SCHEMA = "ds02.stage2.f2-s1-portable-source-profile.v25"
V25_OVERLAY_SCHEMA = "ds02.stage2.f2-s1-portable-replay-input.v25"
V25_REPORT_SCHEMA = "ds02.stage2.f2-s1-replay-runner-report.v25"
V15_REQUEST_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
H5_SUFFIXES = {".h5", ".hdf5"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class TypedReplayV26Error(ValueError):
    """Raised when the v25-to-v26 typed replay binding is unsafe."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    duplicates: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                duplicates.append(key)
            result[key] = item
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, json.JSONDecodeError) as error:
        raise TypedReplayV26Error(f"cannot read JSON: {path}: {error}") from error
    if duplicates:
        raise TypedReplayV26Error(f"duplicate JSON keys in {path}: {sorted(set(duplicates))}")
    if not isinstance(value, dict):
        raise TypedReplayV26Error(f"JSON object required: {path}")
    return value


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise TypedReplayV26Error(f"refusing to overwrite immutable v26 sidecar: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise TypedReplayV26Error(f"{name} must be a lowercase SHA-256")
    return value


def _path(value: Any, name: str, *, suffixes: set[str] | None = None) -> Path:
    if isinstance(value, Path):
        raw_value = value
    elif isinstance(value, str) and value:
        raw_value = value
    else:
        raise TypedReplayV26Error(f"{name} path is missing")
    path = Path(raw_value).expanduser().resolve(strict=False)
    if not path.is_file():
        raise TypedReplayV26Error(f"{name} is missing: {path}")
    if suffixes is not None and path.suffix.lower() not in suffixes:
        raise TypedReplayV26Error(f"{name} has an unexpected suffix: {path}")
    return path


def _file_binding(path: Path, role: str, expected: str, *, hash_mode: str,
                  verify: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise TypedReplayV26Error(f"input is missing: {role}: {path}")
    expected = _require_sha(expected, f"{role}.sha256")
    stat = path.stat()
    actual = sha256_file(path) if verify else None
    if actual is not None and actual != expected:
        raise TypedReplayV26Error(f"input SHA differs: {role}")
    item: dict[str, Any] = {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": expected,
        "hash_mode": hash_mode,
    }
    if actual is not None:
        item["verified_sha256"] = actual
    return item


def _metadata_ref(receipt: Mapping[str, Any], key: str, name: str) -> tuple[Path, str]:
    raw = receipt.get(key)
    if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
        raise TypedReplayV26Error(f"metadata receipt lacks {name} reference")
    return _path(raw["path"], name), _require_sha(raw.get("sha256"), f"{name}.sha256")


def _check_profile(profile: Mapping[str, Any], profile_path: Path,
                   receipt_sha: str) -> tuple[str, str]:
    if profile.get("schema") != V25_PROFILE_SCHEMA:
        raise TypedReplayV26Error("v25 metadata profile schema differs")
    declared = _require_sha(profile.get("sha256"), "profile.sha256")
    if canonical_sha(profile) != declared:
        raise TypedReplayV26Error("v25 profile canonical SHA differs")
    actual_file_sha = sha256_file(profile_path)
    if actual_file_sha != receipt_sha:
        raise TypedReplayV26Error("v25 profile file SHA differs from metadata receipt")
    return declared, actual_file_sha


def _check_metadata_receipt(receipt: Mapping[str, Any], receipt_path: Path,
                            profile_path: Path, overlay_path: Path,
                            preflight_path: Path, v15_path: Path) -> None:
    if receipt.get("schema") != V25_METADATA_SCHEMA or receipt.get("status") != "METADATA_PREFLIGHT_COMPLETE":
        raise TypedReplayV26Error("v25 metadata receipt is not a completed immutable preflight")
    if receipt.get("metadata_preflight_returncode") != 0:
        raise TypedReplayV26Error("v25 metadata preflight return code is not zero")
    if receipt.get("trajectory_h5_read") is not False or receipt.get("trajectory_h5_recopied") is not False:
        raise TypedReplayV26Error("v25 metadata receipt claims an HDF5 read or recopy")
    for key, path in (("profile", profile_path), ("overlay", overlay_path),
                      ("metadata_preflight", preflight_path), ("request", v15_path)):
        ref = receipt.get(key)
        if not isinstance(ref, Mapping) or Path(str(ref.get("path"))).expanduser().resolve() != path:
            raise TypedReplayV26Error(f"v25 receipt {key} path is not the supplied immutable path")
        if sha256_file(path) != _require_sha(ref.get("sha256"), f"receipt.{key}.sha256"):
            raise TypedReplayV26Error(f"v25 receipt {key} SHA differs")


def _check_preflight(preflight: Mapping[str, Any], expected_h5_sha: str) -> None:
    if preflight.get("schema") != V25_REPORT_SCHEMA or preflight.get("status") != "VALIDATED_PENDING_IO_SLOT":
        raise TypedReplayV26Error("v25 metadata report is not VALIDATED_PENDING_IO_SLOT")
    if preflight.get("trajectory_read") is not False:
        raise TypedReplayV26Error("v25 metadata report claims trajectory_read")
    if preflight.get("original_path_fallback") != "FORBIDDEN":
        raise TypedReplayV26Error("v25 metadata report does not forbid original fallback")
    scope = preflight.get("typed_replay_scope")
    if not isinstance(scope, Mapping) or scope.get("raw_to_typed_reconstruction_invoked") is not False:
        raise TypedReplayV26Error("v25 typed-only scope is missing raw reconstruction boundary")
    # The metadata runner deliberately reports no content digest because it
    # did not read HDF5 bytes.  The immutable v22 overlay carries the digest
    # as a parent-verified provenance fact; the v26 parent guard must rehash
    # the target before the approved dataset read.
    if preflight.get("hdf5_content_sha256") is not None:
        raise TypedReplayV26Error("v25 metadata report unexpectedly claims an HDF5 content read")


def _check_overlay(overlay: Mapping[str, Any], profile_declared_sha: str) -> dict[str, str]:
    if overlay.get("schema") != V25_OVERLAY_SCHEMA:
        raise TypedReplayV26Error("v25 overlay schema differs")
    if overlay.get("status") != "READY_FOR_V15_METADATA_PREFLIGHT; HDF5_HASH_INHERITED":
        raise TypedReplayV26Error("v25 overlay status is not the consumed metadata status")
    if overlay.get("profile_sha256") != profile_declared_sha:
        raise TypedReplayV26Error("overlay profile canonical SHA differs")
    if overlay.get("full_replay_content_hash_verified") is not True:
        raise TypedReplayV26Error("overlay does not carry full HDF5 content verification")
    if overlay.get("trajectory_h5_content_hash_source") != "INHERITED_IMMUTABLE_V22_FULLCOPY_RECEIPT":
        raise TypedReplayV26Error("overlay HDF5 content source is not immutable v22 evidence")
    if overlay.get("trajectory_h5_read_by_v25_probe") is not False:
        raise TypedReplayV26Error("overlay claims HDF5 was read by v25 metadata probe")
    path_map = overlay.get("path_map")
    if not isinstance(path_map, Mapping) or not path_map:
        raise TypedReplayV26Error("v25 overlay role map is missing")
    role_map = {str(role): str(path) for role, path in path_map.items()}
    if any(not role or not path for role, path in role_map.items()):
        raise TypedReplayV26Error("v25 overlay contains an empty role/path")
    if role_map.get("trajectory_h5") is None:
        raise TypedReplayV26Error("v25 overlay has no trajectory_h5 target")
    return role_map


def _check_v22_ancestry(profile: Mapping[str, Any], h5_path: Path,
                        expected_h5_sha: str) -> dict[str, Any]:
    inherited = profile.get("inherited_v22_bundle")
    if not isinstance(inherited, Mapping):
        raise TypedReplayV26Error("v25 profile lacks immutable v22 ancestry")
    result: dict[str, Any] = {}
    for key, role in (("profile_path", "v22_profile"), ("copy_result_path", "v22_copy_result"),
                      ("replay_input_path", "v22_replay_input")):
        path = _path(inherited.get(key), f"inherited.{key}")
        expected = _require_sha(inherited.get(key.replace("_path", "_sha256")), f"inherited.{key} SHA")
        result[role] = _file_binding(path, role, expected, hash_mode="sha256_content", verify=True)
    if inherited.get("trajectory_h5_content_sha256") != expected_h5_sha:
        raise TypedReplayV26Error("v25 inherited v22 HDF5 SHA differs")
    v22_replay = _load_json(result["v22_replay_input"]["path"])
    if v22_replay.get("full_replay_content_hash_verified") is not True:
        raise TypedReplayV26Error("v22 replay input lacks full HDF5 content credit")
    v22_h5 = v22_replay.get("path_map", {}).get("trajectory_h5")
    if Path(str(v22_h5)).expanduser().resolve() != h5_path:
        raise TypedReplayV26Error("v25 HDF5 target is not the immutable v22 trajectory target")
    return result


def _check_v15_request(request: Mapping[str, Any], request_path: Path,
                       role_map: Mapping[str, str], expected_h5_sha: str) -> dict[str, Any]:
    if request.get("schema") != V15_REQUEST_SCHEMA:
        raise TypedReplayV26Error("relocated consumer request is not v15")
    if request.get("request_id") != "f2-s1-all-fluid-full401-v15-001":
        raise TypedReplayV26Error("unexpected v15 request identity")
    h5 = request.get("trajectory_h5")
    if not isinstance(h5, Mapping) or h5.get("producer_declared_sha256") != expected_h5_sha:
        raise TypedReplayV26Error("v15 producer HDF5 SHA differs")
    if h5.get("hash_mode") != "producer_attested_only_no_content_hash":
        raise TypedReplayV26Error("v15 HDF5 binding hash mode differs")
    if request.get("portable_migration", {}).get("expected_trajectory_content_sha256") != expected_h5_sha:
        raise TypedReplayV26Error("v15 portable migration SHA differs")
    cohort = request.get("cohort")
    if (not isinstance(cohort, Mapping) or cohort.get("expected_initial_fluid_count") != 21114 or
            cohort.get("source_identity_set_sha256") != "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70" or
            cohort.get("max_particles") is not None):
        raise TypedReplayV26Error("v15 cohort is not the exact 21114 identity cohort")
    window = request.get("window")
    if (not isinstance(window, Mapping) or window.get("frame_start") != 0 or
            window.get("frame_stop") != 400 or len(window.get("expected_times_s", [])) != 401):
        raise TypedReplayV26Error("v15 request is not the full 401-frame window")
    if request.get("current_binding", {}).get("frames") != 401:
        raise TypedReplayV26Error("v15 CURRENT binding is not 401 frames")
    if role_map.get("v15_replay_request") != str(request_path):
        raise TypedReplayV26Error("overlay v15 request target differs")
    return {
        "request_id": request["request_id"],
        "case_identity": request.get("case_identity"),
        "current_binding": request.get("current_binding"),
        "cohort": cohort,
        "window": {
            "frame_start": 0,
            "frame_stop": 400,
            "query_count": 401,
            "expected_first_s": float(window["expected_times_s"][0]),
            "expected_last_s": float(window["expected_times_s"][-1]),
        },
        "observer_profile": request.get("observer_profile"),
        "trajectory_h5": {
            "bytes": int(h5.get("bytes", -1)),
            "producer_declared_sha256": expected_h5_sha,
            "hash_mode": h5["hash_mode"],
        },
    }


def _overlay_source_bindings(overlay: Mapping[str, Any], role_map: Mapping[str, str],
                             h5_path: Path, expected_h5_sha: str) -> list[dict[str, Any]]:
    records = overlay.get("source_records")
    if not isinstance(records, list) or len(records) != len(role_map):
        raise TypedReplayV26Error("overlay source records do not cover the role map")
    by_role: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("role"), str):
            raise TypedReplayV26Error("overlay source record is malformed")
        role = str(record["role"])
        if role in by_role:
            raise TypedReplayV26Error(f"duplicate overlay source role: {role}")
        by_role[role] = record
    if set(by_role) != set(role_map):
        raise TypedReplayV26Error("overlay source records and role map differ")
    bindings: list[dict[str, Any]] = []
    for role in sorted(role_map):
        target = _path(role_map[role], f"overlay.{role}")
        record = by_role[role]
        expected = _require_sha(record.get("expected_sha256"), f"overlay.{role}.expected_sha256")
        if role == "trajectory_h5":
            if target != h5_path or expected != expected_h5_sha:
                raise TypedReplayV26Error("overlay HDF5 target or SHA differs")
            if target.stat().st_size != int(record.get("bytes", -1)):
                raise TypedReplayV26Error("overlay HDF5 target byte size differs")
            if record.get("content_hash_verified") is not True or record.get("content_sha256") != expected_h5_sha:
                raise TypedReplayV26Error("overlay HDF5 record lacks inherited full content SHA")
            bindings.append({
                "role": role,
                "path": str(target),
                "bytes": target.stat().st_size,
                "mtime_ns": target.stat().st_mtime_ns,
                "sha256": expected_h5_sha,
                "hash_mode": "parent_full_sha_before_native_C_open",
                "content_hash_source": "INHERITED_V22_FULLCOPY_RECEIPT; PARENT_MUST_REVERIFY",
                "producer_mtime_is_provenance_only": True,
            })
            continue
        if record.get("content_hash_verified") is not True or record.get("content_sha256") != expected:
            raise TypedReplayV26Error(f"overlay source {role} lacks verified content SHA")
        if target.stat().st_size != int(record.get("bytes", -1)):
            raise TypedReplayV26Error(f"overlay source byte size differs: {role}")
        bindings.append({
            "role": f"relocated_source:{role}",
            "source_role": role,
            "path": str(target),
            "bytes": target.stat().st_size,
            "mtime_ns": target.stat().st_mtime_ns,
            "sha256": expected,
            "hash_mode": "INHERITED_V25_OVERLAY_CONTENT_SHA; PARENT_REVERIFY_BEFORE_RUN",
        })
    return bindings


def _dedupe_bindings(bindings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in bindings:
        path = str(raw["path"])
        current = result.get(path)
        if current is None:
            result[path] = dict(raw)
            continue
        if current.get("sha256") != raw.get("sha256") or current.get("bytes") != raw.get("bytes"):
            raise TypedReplayV26Error(f"same path has conflicting input binding: {path}")
        roles = list(current.get("roles", [current.get("role")]))
        role = raw.get("role")
        if role not in roles:
            roles.append(role)
        current["roles"] = sorted(str(item) for item in roles if item)
        current["role"] = current["roles"][0]
    return [result[path] for path in sorted(result)]


def _runtime_binding(path: Path, role: str, *, verify: bool = True) -> dict[str, Any]:
    return _file_binding(path, role, sha256_file(path), hash_mode="sha256_content", verify=verify)


def build_request(metadata_receipt_path: Path | str, output_path: Path | str,
                  *, v25_request_path: Path | str | None = None,
                  profile_output: Path | str | None = None,
                  overlay_output: Path | str | None = None,
                  v26_preflight_path: Path | str | None = None) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise TypedReplayV26Error(f"refusing to overwrite request: {output}")
    v26_profile_path = (Path(profile_output).expanduser().resolve() if profile_output is not None
                        else output.with_name("f2-s1-typed-only-full401-profile-v26-001.json"))
    v26_overlay_path = (Path(overlay_output).expanduser().resolve() if overlay_output is not None
                        else output.with_name("f2-s1-typed-only-full401-overlay-v26-001.json"))
    if v26_profile_path.exists() or v26_overlay_path.exists():
        raise TypedReplayV26Error("refusing to overwrite an existing v26 profile or overlay")
    receipt_path = Path(metadata_receipt_path).expanduser().resolve()
    receipt = _load_json(receipt_path)
    profile_path, profile_receipt_sha = _metadata_ref(receipt, "profile", "v25 profile")
    overlay_path, overlay_receipt_sha = _metadata_ref(receipt, "overlay", "v25 overlay")
    preflight_path, preflight_receipt_sha = _metadata_ref(receipt, "metadata_preflight", "v25 preflight")
    v15_path, v15_receipt_sha = _metadata_ref(receipt, "request", "v15 request")
    _check_metadata_receipt(receipt, receipt_path, profile_path, overlay_path, preflight_path, v15_path)
    profile = _load_json(profile_path)
    profile_declared_sha, profile_file_sha = _check_profile(profile, profile_path, profile_receipt_sha)
    overlay = _load_json(overlay_path)
    role_map = _check_overlay(overlay, profile_declared_sha)
    expected_h5_sha = _require_sha(overlay.get("trajectory_h5_content_sha256"), "overlay HDF5 content SHA")
    h5_path = _path(role_map.get("trajectory_h5"), "relocated trajectory_h5", suffixes=H5_SUFFIXES)
    _check_preflight(_load_json(preflight_path), expected_h5_sha)
    v15_request = _load_json(v15_path)
    v15_view = _check_v15_request(v15_request, v15_path, role_map, expected_h5_sha)
    overlay_sources = _overlay_source_bindings(overlay, role_map, h5_path, expected_h5_sha)
    h5_entry = next(item for item in overlay_sources if item.get("role") == "trajectory_h5")
    if h5_entry["bytes"] != int(v15_view["trajectory_h5"]["bytes"]):
        raise TypedReplayV26Error("relocated HDF5 bytes differ from v15 producer binding")
    ancestry = _check_v22_ancestry(profile, h5_path, expected_h5_sha)

    inherited = profile.get("inherited_v22_bundle")
    assert isinstance(inherited, Mapping)
    v22_profile_path = Path(ancestry["v22_profile"]["path"])
    v22_copy_path = Path(ancestry["v22_copy_result"]["path"])
    v22_replay_path = Path(ancestry["v22_replay_input"]["path"])

    v26_preflight_binding: dict[str, Any] | None = None
    if v26_preflight_path is not None:
        probe_path = _path(v26_preflight_path, "v26 metadata probe report")
        probe = _load_json(probe_path)
        if (probe.get("schema") != V25_REPORT_SCHEMA or
                probe.get("status") != "VALIDATED_PENDING_IO_SLOT" or
                probe.get("trajectory_read") is not False or
                probe.get("hdf5_content_sha256") is not None or
                probe.get("original_path_fallback") != "FORBIDDEN"):
            raise TypedReplayV26Error("v26 metadata probe report is not a no-HDF5 preflight")
        v26_preflight_binding = _runtime_binding(probe_path, "v26_metadata_probe_report")

    # Freeze a new profile/overlay pair as metadata-only forward artifacts.
    # The profile keeps the complete v25 role closure so the existing v25
    # verifier can consume it; the overlay keeps the exact target paths and
    # inherited H5 receipt. Neither artifact copies or opens H5 bytes.
    v26_profile = json.loads(json.dumps(profile))
    v26_profile["profile_id"] = "f2-s1-typed-only-full401-profile-v26-001"
    v26_profile["status"] = "READY_FOR_TYPED_ONLY_FULL401; HDF5_CONTENT_INHERITED_FROM_V22"
    v26_profile["forward_binding"] = {
        "upstream_profile_path": str(profile_path),
        "upstream_profile_file_sha256": profile_file_sha,
        "upstream_profile_canonical_sha256": profile_declared_sha,
        "upstream_overlay_path": str(overlay_path),
        "upstream_overlay_file_sha256": sha256_file(overlay_path),
        "dataset_read_by_v26_builder": False,
        "original_path_fallback": "FORBIDDEN",
        "qualification": "UNKNOWN",
    }
    v26_profile["sha256"] = canonical_sha(v26_profile)
    _write_new_json(v26_profile_path, v26_profile)
    if canonical_sha(v26_profile) != v26_profile["sha256"]:
        raise TypedReplayV26Error("v26 profile canonical SHA failed immediately after write")
    v26_overlay = {
        "schema": "ds02.stage2.f2-s1-portable-overlay-verification.v26",
        "status": "READY_FOR_PARENT_FULL_REPLAY; HDF5_HASH_INHERITED",
        "profile_sha256": v26_profile["sha256"],
        "profile_file_sha256": sha256_file(v26_profile_path),
        "upstream_v25_profile": {
            "path": str(profile_path), "file_sha256": profile_file_sha,
            "canonical_sha256": profile_declared_sha,
        },
        "upstream_v25_overlay": {
            "path": str(overlay_path), "file_sha256": sha256_file(overlay_path),
        },
        "path_map": role_map,
        "consumer_input": {
            "role_to_relocated_path": role_map,
            "original_path_fallback": "FORBIDDEN",
            "trajectory_h5_role": "trajectory_h5",
        },
        "source_records": [dict(item) for item in overlay.get("source_records", [])],
        "full_replay_content_hash_verified": True,
        "trajectory_h5_content_sha256": expected_h5_sha,
        "trajectory_h5_content_hash_source": "INHERITED_IMMUTABLE_V22_FULLCOPY_RECEIPT",
        "trajectory_h5_read_by_v26_builder": False,
        "raw_to_typed_reconstruction_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    v26_overlay["sha256"] = canonical_sha(v26_overlay)
    _write_new_json(v26_overlay_path, v26_overlay)

    canonical_root = Path(__file__).resolve().parents[1]
    if v25_request_path is None:
        v25_request_path = canonical_root / "campaigns/ds-data-02/stage2/replay/v25/f2-s1-portable-metadata-probe-request-v25-001-root-canonical.json"
    v25_request_path = Path(v25_request_path).expanduser().resolve()
    v25_request_binding = _runtime_binding(v25_request_path, "v25_metadata_request")

    runner = _path(role_map.get("replay_runner_v25"), "relocated v25 replay runner")
    # Keep the venv symlink in the actionable command.  It is the declared
    # interpreter for this worktree; resolving it to /usr/bin/python3.10 can
    # silently bypass the venv's h5py/numpy installation in a parent guard.
    python_path = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    strace_path = Path("/usr/bin/strace").resolve()
    python_binding = _runtime_binding(python_path, "python_interpreter")
    strace_binding = _runtime_binding(strace_path, "os_strace")
    builder_binding = _runtime_binding(Path(__file__).resolve(), "v26_request_builder")
    receipt_binding = _file_binding(receipt_path, "v25_metadata_receipt", sha256_file(receipt_path),
                                    hash_mode="sha256_content", verify=True)
    profile_binding = _file_binding(profile_path, "v25_metadata_profile", profile_file_sha,
                                    hash_mode="sha256_content", verify=False)
    overlay_binding = _file_binding(overlay_path, "v25_metadata_overlay", overlay_receipt_sha,
                                    hash_mode="sha256_content", verify=False)
    preflight_binding = _file_binding(preflight_path, "v25_metadata_preflight", preflight_receipt_sha,
                                      hash_mode="sha256_content", verify=False)
    v15_binding = _file_binding(v15_path, "v15_consumer_request", v15_receipt_sha,
                                hash_mode="sha256_content", verify=False)
    v26_profile_binding = _runtime_binding(v26_profile_path, "v26_profile_sidecar")
    v26_overlay_binding = _runtime_binding(v26_overlay_path, "v26_overlay_sidecar")

    source_bindings = _dedupe_bindings([
        *overlay_sources,
        receipt_binding, profile_binding, overlay_binding, preflight_binding,
        v15_binding, v25_request_binding,
        v26_profile_binding, v26_overlay_binding,
        ancestry["v22_profile"], ancestry["v22_copy_result"], ancestry["v22_replay_input"],
        python_binding, strace_binding, builder_binding,
    ])
    if v26_preflight_binding is not None:
        source_bindings = _dedupe_bindings([*source_bindings, v26_preflight_binding])
    target_output = "{attempt_root}/typed-replay-v26/f2-s1-typed-only-full401-result-v26.json"
    trace_output = "{attempt_root}/typed-replay-v26/os-trace/openat.log"
    command = [
        strace_path.as_posix(), "-f", "-yy", "-e", "trace=open,openat,openat2,creat",
        "-o", trace_output,
        str(python_path), str(runner),
        "--profile", str(v26_profile_path), "--request", str(v15_path),
        "--path-map", str(v26_overlay_path), "--io-slot-approved", "--output", target_output,
    ]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "orchestration_schema": ORCHESTRATION_SCHEMA,
        "request_id": "f2-s1-portable-typed-only-full401-v26-001",
        "attempt_id": "portable-typed-only-full401-v26-001",
        "status": "READY_FOR_PARENT_IO_SLOT",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_identity": v15_view["case_identity"],
        "current_binding": v15_view["current_binding"],
        "cohort": v15_view["cohort"],
        "window": v15_view["window"],
        "observer_profile": v15_view["observer_profile"],
        "typed_replay_scope": {
            "status": "TYPED_ONLY_FULL401_PENDING_PARENT_IO",
            "input": "relocated v22 HDF5 typed arrays through v25/v15 reader",
            "frames": 401,
            "source_particle_shape": [401, 418104],
            "logical_fluid_cohort": 21114,
            "raw_to_typed_reconstruction_invoked": False,
            "raw_to_label_complete": False,
            "native_partout_is_provenance_only": True,
            "labels_and_observers": "v15 typed-array operators only; DEVELOPMENT; QI/QN/QE UNKNOWN",
            "scientific_qualification": "UNKNOWN",
        },
        "source_identity": {
            "v25_metadata_receipt": {
                "path": str(receipt_path), "sha256": sha256_file(receipt_path),
                "status": receipt["status"],
            },
            "v25_profile": {
                "path": str(profile_path), "file_sha256": profile_file_sha,
                "canonical_sha256": profile_declared_sha,
            },
            "v25_overlay": {
                "path": str(overlay_path), "file_sha256": sha256_file(overlay_path),
                "profile_canonical_sha256": profile_declared_sha,
            },
            "v25_preflight": {
                "path": str(preflight_path), "sha256": sha256_file(preflight_path),
                "status": "VALIDATED_PENDING_IO_SLOT",
            },
            "v15_request": {"path": str(v15_path), "sha256": sha256_file(v15_path)},
            "v26_profile": {
                "path": str(v26_profile_path), "file_sha256": sha256_file(v26_profile_path),
                "canonical_sha256": v26_profile["sha256"],
            },
            "v26_overlay": {
                "path": str(v26_overlay_path), "file_sha256": sha256_file(v26_overlay_path),
                "canonical_sha256": v26_overlay["sha256"],
            },
            "v26_metadata_probe": (None if v26_preflight_binding is None else {
                "path": v26_preflight_binding["path"],
                "sha256": v26_preflight_binding["sha256"],
                "status": "VALIDATED_PENDING_IO_SLOT",
            }),
            "immutable_v22": {
                "profile": ancestry["v22_profile"],
                "copy_result": ancestry["v22_copy_result"],
                "replay_input": ancestry["v22_replay_input"],
            },
        },
        "trajectory_h5": {
            "path": str(h5_path),
            "bytes": h5_entry["bytes"],
            "relocated_mtime_ns": h5_entry["mtime_ns"],
            "producer_declared_sha256": expected_h5_sha,
            "content_sha256": expected_h5_sha,
            "content_hash_source": "INHERITED_IMMUTABLE_V22_FULLCOPY_RECEIPT",
            "content_hash_verified_by_v26_builder": False,
            "parent_must_rehash_before_native_C_open": True,
            "producer_path_is_provenance_only": True,
            "copy_performed_by_v26": False,
            "dataset_read_by_v26_builder": False,
        },
        "relocation": {
            "path_overlay": str(v26_overlay_path),
            "upstream_v25_path_overlay": str(overlay_path),
            "original_path_fallback": "FORBIDDEN",
            "original_uris_are_provenance_only": True,
            "target_stat_may_differ_from_producer": True,
            "small_source_sha_scope": "V25 overlay receipt; parent guard rechecks all target bytes",
            "hdf5_sha_scope": "V22 full-copy receipt inherited; parent guard must rehash target",
        },
        "command": command,
        "cwd": str(runner.parent),
        "input_files": [item["path"] for item in source_bindings],
        "input_bindings": source_bindings,
        "runtime": {
            "runner": {"path": str(runner), "sha256": sha256_file(runner)},
            "python": python_binding,
            "strace": strace_binding,
            "pythonpath": "",
            "original_path_fallback": "FORBIDDEN",
            "native_hdf5_c_open_audit": "OS strace open/openat/openat2/creat required",
        },
        "access_audit": {
            "python_hook": "v25 sys.addaudithook records/rejects Python open and os.open original paths",
            "os_trace": "parent must retain openat trace covering h5py/native HDF5 C opens",
            "unexpected_data_path": "reject",
            "original_source_path": "reject",
            "trace_output": trace_output,
        },
        "execution_closure": {
            "v25_metadata_preflight": "consumed immutable output; status complete",
            "v26_profile_overlay": "new immutable metadata sidecars; no HDF5 copy or read",
            "v26_metadata_probe": ("not supplied" if v26_preflight_binding is None else
                                    "actual copied-runtime subprocess; no HDF5 content read"),
            "consumer_chain": "copied v25 runner -> copied v25 portable verifier -> copied v15 -> copied v14",
            "all_actionable_overlay_roles": len(role_map),
            "immutable_v22_h5_target": True,
            "v15_transitive_modules": ["replay_module_v15", "replay_module_v14", "replay_runner_v25", "portable_v25_worker"],
            "raw_converter_imported": False,
            "raw_bi4_read": False,
            "model_or_cfd": False,
        },
        "resource_request": {
            "cpu_cores": 1,
            "max_wall_seconds": 5400,
            "max_rss_mib_estimate": 2304,
            "rss_limit_enforced": False,
            "estimated_peak_memory_bytes": 1954047113,
            "estimated_storage_bytes": 1200000000,
            "hdf5_dataset_read": "full bound 401-frame window through exact 21114 fluid identity spans",
            "hdf5_copy": False,
            "new_hdf5_storage_bytes": 0,
            "guard_enforcement": "CPU/wall/storage/source checks; RSS observational only",
        },
        "limitations": [
            "metadata evidence and v22 HDF5 content SHA are inherited; v26 builder does not hash or open H5",
            "parent guard must full-hash the relocated H5 target before any h5py/native C open",
            "OS strace receipt is required because Python audit cannot guarantee native HDF5 C-open visibility",
            "typed-only replay does not reconstruct native raw BI4 and does not provide raw-to-label completeness",
            "v15 labels/observers remain development outputs; QI/QN/QE and scientific qualification UNKNOWN",
            "no receiver or material qualification is granted by a successful replay",
        ],
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    request["sha256"] = canonical_sha(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(request, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return request


def validate_request(request: Mapping[str, Any], *, verify_small_sources: bool = False,
                     verify_hdf5: bool = False) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("orchestration_schema") != ORCHESTRATION_SCHEMA:
        raise TypedReplayV26Error("unsupported v26 request schema")
    if request.get("status") != "READY_FOR_PARENT_IO_SLOT":
        raise TypedReplayV26Error("v26 request is not ready for a parent I/O slot")
    if request.get("original_path_fallback") == "ALLOWED":
        raise TypedReplayV26Error("original path fallback is forbidden")
    scope = request.get("typed_replay_scope")
    if not isinstance(scope, Mapping) or scope.get("raw_to_typed_reconstruction_invoked") is not False:
        raise TypedReplayV26Error("typed-only boundary is missing")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise TypedReplayV26Error("model/CFD invocation is not allowed")
    command = request.get("command")
    if not isinstance(command, list) or "--io-slot-approved" not in command:
        raise TypedReplayV26Error("command lacks explicit parent I/O grant flag")
    if "/usr/bin/strace" not in command or "openat" not in " ".join(str(item) for item in command):
        raise TypedReplayV26Error("command lacks OS openat trace")
    identity = request.get("source_identity")
    if not isinstance(identity, Mapping):
        raise TypedReplayV26Error("source_identity is required")
    v26_profile_ref = identity.get("v26_profile")
    v26_overlay_ref = identity.get("v26_overlay")
    if not isinstance(v26_profile_ref, Mapping) or not isinstance(v26_overlay_ref, Mapping):
        raise TypedReplayV26Error("v26 immutable profile/overlay references are required")
    v26_profile_path = _path(v26_profile_ref.get("path"), "v26 profile sidecar")
    v26_overlay_path = _path(v26_overlay_ref.get("path"), "v26 overlay sidecar")
    v26_profile = _load_json(v26_profile_path)
    if v26_profile.get("schema") != V25_PROFILE_SCHEMA:
        raise TypedReplayV26Error("v26 profile must remain v25-consumer compatible")
    declared_profile_sha = _require_sha(v26_profile.get("sha256"), "v26 profile.sha256")
    if canonical_sha(v26_profile) != declared_profile_sha:
        raise TypedReplayV26Error("v26 profile canonical SHA differs")
    if v26_profile_ref.get("canonical_sha256") != declared_profile_sha:
        raise TypedReplayV26Error("v26 profile reference canonical SHA differs")
    if sha256_file(v26_profile_path) != _require_sha(v26_profile_ref.get("file_sha256"),
                                                     "v26 profile file SHA"):
        raise TypedReplayV26Error("v26 profile file SHA differs")
    v26_overlay = _load_json(v26_overlay_path)
    if v26_overlay.get("schema") != "ds02.stage2.f2-s1-portable-overlay-verification.v26":
        raise TypedReplayV26Error("v26 overlay schema differs")
    if v26_overlay.get("profile_sha256") != declared_profile_sha:
        raise TypedReplayV26Error("v26 overlay profile SHA differs")
    if canonical_sha(v26_overlay) != _require_sha(v26_overlay.get("sha256"), "v26 overlay.sha256"):
        raise TypedReplayV26Error("v26 overlay canonical SHA differs")
    if sha256_file(v26_overlay_path) != _require_sha(v26_overlay_ref.get("file_sha256"),
                                                     "v26 overlay file SHA"):
        raise TypedReplayV26Error("v26 overlay file SHA differs")
    if v26_overlay.get("consumer_input", {}).get("original_path_fallback") != "FORBIDDEN":
        raise TypedReplayV26Error("v26 overlay permits original path fallback")
    if "--profile" not in command or command[command.index("--profile") + 1] != str(v26_profile_path):
        raise TypedReplayV26Error("command does not use the immutable v26 profile")
    if "--path-map" not in command or command[command.index("--path-map") + 1] != str(v26_overlay_path):
        raise TypedReplayV26Error("command does not use the immutable v26 overlay")
    bindings = request.get("input_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise TypedReplayV26Error("input_bindings are required")
    seen_paths: set[str] = set()
    for index, item in enumerate(bindings):
        if not isinstance(item, Mapping):
            raise TypedReplayV26Error(f"input_bindings[{index}] is malformed")
        path = _path(item.get("path"), f"input_bindings[{index}]")
        if str(path) in seen_paths:
            raise TypedReplayV26Error(f"duplicate input path: {path}")
        seen_paths.add(str(path))
        expected = _require_sha(item.get("sha256"), f"input_bindings[{index}].sha256")
        stat = path.stat()
        if stat.st_size != int(item.get("bytes", -1)):
            raise TypedReplayV26Error(f"input byte size differs: {path}")
        if path.suffix.lower() in H5_SUFFIXES:
            if request.get("trajectory_h5", {}).get("content_sha256") != expected:
                raise TypedReplayV26Error("H5 input binding SHA differs from request content SHA")
            if verify_hdf5 and sha256_file(path) != expected:
                raise TypedReplayV26Error("H5 target content SHA differs")
        elif verify_small_sources or item.get("hash_mode") == "sha256_content_verified_runtime":
            if sha256_file(path) != expected:
                raise TypedReplayV26Error(f"small input SHA differs: {path}")
    h5 = request.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise TypedReplayV26Error("trajectory_h5 binding is missing")
    h5_path = _path(h5.get("path"), "request trajectory_h5", suffixes=H5_SUFFIXES)
    if h5_path.stat().st_size != int(h5.get("bytes", -1)):
        raise TypedReplayV26Error("request H5 stat differs")
    if h5.get("parent_must_rehash_before_native_C_open") is not True:
        raise TypedReplayV26Error("request does not require parent H5 full hash")
    if request.get("relocation", {}).get("original_path_fallback") != "FORBIDDEN":
        raise TypedReplayV26Error("relocation original fallback is not forbidden")
    if canonical_sha(request) != _require_sha(request.get("sha256"), "request.sha256"):
        raise TypedReplayV26Error("request canonical SHA differs")
    return {
        "schema": ORCHESTRATION_SCHEMA,
        "status": "VALIDATED_NO_HDF5_CONTENT_READ" if not verify_hdf5 else "VALIDATED_HDF5_FULL_HASH",
        "input_count": len(bindings),
        "hdf5_stat_checked": True,
        "hdf5_content_read_by_validator": bool(verify_hdf5),
        "original_path_fallback": "FORBIDDEN",
        "qualification": request.get("qualification"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--metadata-receipt", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--v25-request", type=Path)
    build.add_argument("--profile-output", type=Path)
    build.add_argument("--overlay-output", type=Path)
    build.add_argument("--v26-preflight", type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--verify-small-sources", action="store_true")
    validate.add_argument("--verify-hdf5", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            request = build_request(
                args.metadata_receipt, args.output, v25_request_path=args.v25_request,
                profile_output=args.profile_output, overlay_output=args.overlay_output,
                v26_preflight_path=args.v26_preflight,
            )
            result = {"schema": request["orchestration_schema"], "status": request["status"],
                      "request_id": request["request_id"], "sha256": request["sha256"]}
        else:
            request = _load_json(args.request)
            result = validate_request(request, verify_small_sources=args.verify_small_sources,
                                      verify_hdf5=args.verify_hdf5)
    except (OSError, TypedReplayV26Error) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
