#!/usr/bin/env python3
"""Run a bounded v24 metadata preflight on the immutable v22 bundle.

The v22 primary already copied and content-hashed the F2-S1 HDF5 and all
small source roles.  Repeating that 1.2 GiB copy is unnecessary for a
metadata-only regression probe, and opening an HDF5 dataset would make the
probe a scientific I/O run.  This helper therefore constructs a *new* v24
runtime overlay from the v22 source profile and existing copied role paths,
inherits the v22 full-copy HDF5 receipt by exact SHA, and runs the copied v24
runner without ``--io-slot-approved``.

The source files are not rewritten.  The v22 profile, copy receipt, replay
receipt, CURRENT row, scan, native reconciliation ledger/receipt, XML, motion
file, and producer receipts remain immutable provenance.  Receipt input keys
are checked as aliases: a copied consumer path may differ from an original
producer URI, but the input hash must be the exact role hash.  An unresolved
receipt key is retained as provenance-only and never becomes an actionable
fallback path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-s1-portable-metadata-probe.v24"
V24_PROFILE_SCHEMA = "ds02.stage2.f2-s1-portable-source-profile.v24"
V24_OVERLAY_SCHEMA = "ds02.stage2.f2-s1-portable-replay-input.v24"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
REQUIRED_METADATA_ROLES = {
    "current_catalog", "manifest", "xmf", "generated_xml", "motion_dat",
    "conversion_report", "scientific_scan_sidecar", "initial_qa", "initial_stats",
    "gencase_receipt", "solver_receipt", "owner_metadata", "native_reconciliation",
    "native_reconciliation_receipt", "source_metadata",
}
RECEIPT_ROLES = ("gencase_receipt", "solver_receipt", "native_reconciliation_receipt")
V24_REPLACEMENTS = {
    "portable_v22_worker": ("portable_v24_worker", "runtime/portable/ds_data02_stage2_f2_portable_v24.py"),
    "replay_runner_v22": ("replay_runner_v24", "runtime/replay/ds_data02_stage2_f2_replay_runner_v24.py"),
}


class MetadataProbeError(ValueError):
    """Raised when the inherited bundle cannot be source-bound for v24."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode()).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise MetadataProbeError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise MetadataProbeError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    path = Path(path).expanduser()
    if path.exists():
        raise MetadataProbeError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def _role_map(profile: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for collection_name in ("original_sources", "supporting_sources"):
        collection = profile.get(collection_name, [])
        if not isinstance(collection, list):
            raise MetadataProbeError(f"v22 profile {collection_name} is malformed")
        for entry in collection:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("role"), str):
                raise MetadataProbeError(f"v22 profile {collection_name} entry is malformed")
            role = str(entry["role"])
            if role in result:
                raise MetadataProbeError(f"duplicate inherited role: {role}")
            result[role] = dict(entry)
    trajectory = profile.get("trajectory_h5")
    if not isinstance(trajectory, Mapping):
        raise MetadataProbeError("v22 profile trajectory_h5 is missing")
    if "trajectory_h5" in result:
        raise MetadataProbeError("trajectory_h5 role is duplicated")
    result["trajectory_h5"] = dict(trajectory)
    return result


def _v22_receipt_records(replay_input: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = replay_input.get("source_records")
    if not isinstance(records, list):
        raise MetadataProbeError("v22 replay input source_records are required")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("role"), str):
            raise MetadataProbeError("v22 replay source record is malformed")
        role = str(record["role"])
        if role in result:
            raise MetadataProbeError(f"duplicate v22 replay source role: {role}")
        result[role] = dict(record)
    h5 = result.get("trajectory_h5")
    if not isinstance(h5, Mapping) or h5.get("content_hash_verified") is not True:
        raise MetadataProbeError("v22 full-copy HDF5 content receipt is required")
    if h5.get("content_sha256") != h5.get("expected_sha256"):
        raise MetadataProbeError("v22 HDF5 receipt has inconsistent content SHA")
    return result


def _target_path(path_map: Mapping[str, Any], role: str) -> Path:
    value = path_map.get(role)
    if not isinstance(value, str) or not value:
        raise MetadataProbeError(f"v22 copy path is missing role: {role}")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MetadataProbeError(f"v22 copied source is missing: {role}: {path}")
    return path


def _verify_inherited_bundle(profile: Mapping[str, Any], copy_result: Mapping[str, Any],
                             replay_input: Mapping[str, Any]) -> dict[str, Any]:
    """Check the old bundle's identity and transitive metadata without H5 I/O."""
    if not str(profile.get("schema", "")).endswith(".v22"):
        raise MetadataProbeError("metadata probe requires the immutable v22 source profile")
    if not str(copy_result.get("schema", "")).endswith(".v22"):
        raise MetadataProbeError("metadata probe requires the immutable v22 copy result")
    path_map = copy_result.get("path_map")
    if not isinstance(path_map, Mapping):
        raise MetadataProbeError("v22 copy result path_map is required")
    roles = _role_map(profile)
    records = _v22_receipt_records(replay_input)
    missing = sorted(set(roles) - set(path_map))
    if missing:
        raise MetadataProbeError(f"v22 copy path_map lacks roles: {missing}")
    for role in roles:
        target = _target_path(path_map, role)
        original = Path(str(roles[role].get("original_path", ""))).expanduser().resolve()
        if target == original:
            raise MetadataProbeError(f"v22 role falls back to original path: {role}")
        if role in records:
            record_sha = records[role].get("content_sha256") or records[role].get("expected_sha256")
            if isinstance(record_sha, str) and role != "trajectory_h5":
                # The v22 receipt is the content proof for the inherited
                # bundle.  Hash only the bounded metadata roles below; large
                # payload roles retain their immutable v22 receipt credit.
                if role in REQUIRED_METADATA_ROLES and sha256(target) != record_sha:
                    raise MetadataProbeError(f"copied metadata role SHA differs: {role}")

    current_path = _target_path(path_map, "current_catalog")
    current = _load(current_path)
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) <= 78 or not isinstance(cases[78], Mapping):
        raise MetadataProbeError("copied CURRENT does not contain case index 78")
    row = cases[78]
    expected_identity = {
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "runtime_case_alias": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
        "frames": 401,
        "particles": 418104,
    }
    if any(row.get(key) != value for key, value in expected_identity.items()):
        raise MetadataProbeError("copied CURRENT case-78 identity/shape differs")
    trajectory = row.get("trajectory")
    h5_record = records["trajectory_h5"]
    if (not isinstance(trajectory, Mapping) or
            trajectory.get("producer_declared_sha256") != h5_record.get("expected_sha256")):
        raise MetadataProbeError("copied CURRENT producer SHA differs from inherited HDF5 receipt")

    # Verify the source/receipt relationships that the v14/v15 validators
    # consume.  Every original key is recorded as an alias if it is one of the
    # profiled roles; other producer paths are explicitly provenance-only.
    original_to_role = {
        str(Path(str(item.get("original_path"))).expanduser().resolve()): role
        for role, item in roles.items() if role != "trajectory_h5"
    }
    aliases: list[dict[str, Any]] = []
    receipt_checks: list[dict[str, Any]] = []
    for receipt_role in RECEIPT_ROLES:
        receipt_path = _target_path(path_map, receipt_role)
        receipt = _load(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise MetadataProbeError(f"{receipt_role} is not a completed receipt")
        maps: dict[str, Mapping[str, Any]] = {}
        for map_name in ("input_hashes_at_launch", "input_hashes_after_run"):
            mapping = receipt.get(map_name)
            if not isinstance(mapping, Mapping):
                raise MetadataProbeError(f"{receipt_role}.{map_name} is missing")
            maps[map_name] = mapping
            for key, value in mapping.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise MetadataProbeError(f"{receipt_role}.{map_name} contains malformed input hash")
                role = original_to_role.get(str(Path(key).expanduser().resolve()))
                target = None if role is None else str(_target_path(path_map, role))
                aliases.append({
                    "receipt_role": receipt_role,
                    "receipt_phase": map_name,
                    "original_input_path": key,
                    "input_sha256": value,
                    "bound_role": role,
                    "relocated_input_path": target,
                    "path_semantics": "ACTIONABLE_ROLE_ALIAS" if role else "PROVENANCE_ONLY_EXTERNAL_RECEIPT_PATH",
                })
        receipt_checks.append({
            "role": receipt_role,
            "launch_input_count": len(maps["input_hashes_at_launch"]),
            "finish_input_count": len(maps["input_hashes_after_run"]),
        })

    scan_record = records.get("scientific_scan_sidecar")
    scan_sha = scan_record.get("content_sha256") if isinstance(scan_record, Mapping) else None
    if not isinstance(scan_sha, str):
        raise MetadataProbeError("scientific scan source SHA is missing from v22 receipt")
    scan_path = _target_path(path_map, "scientific_scan_sidecar")
    scan = _load(scan_path)
    if scan.get("family_id") != "F2" or scan.get("full_saved_timeline_scanned") is not True:
        raise MetadataProbeError("copied scientific scan is not the exact complete F2 timeline")
    native_receipt_aliases = [item for item in aliases
                              if item["receipt_role"] == "native_reconciliation_receipt"
                              and item["receipt_phase"] == "input_hashes_after_run"
                              and item["input_sha256"] == scan_sha]
    if not native_receipt_aliases:
        raise MetadataProbeError("native reconciliation receipt lacks the scientific-scan SHA alias")
    gencase_solver_support: dict[str, Any] = {}
    motion_sha = records["motion_dat"].get("content_sha256")
    metadata_sha = records["source_metadata"].get("content_sha256")
    for role in ("gencase_receipt", "solver_receipt"):
        receipt = _load(_target_path(path_map, role))
        launch = receipt.get("input_hashes_at_launch", {})
        finish = receipt.get("input_hashes_after_run", {})
        if (not isinstance(launch, Mapping) or not isinstance(finish, Mapping) or
                not isinstance(motion_sha, str) or not isinstance(metadata_sha, str) or
                motion_sha not in launch.values() or motion_sha not in finish.values() or
                metadata_sha not in launch.values() or metadata_sha not in finish.values()):
            raise MetadataProbeError(f"{role} does not support motion/metadata hashes at launch and finish")
        gencase_solver_support[role] = {
            "motion_sha256": motion_sha,
            "source_metadata_sha256": metadata_sha,
            "launch_and_finish_supported": True,
        }
    return {
        "case_index": 78,
        "identity": expected_identity,
        "current_catalog_sha256": records["current_catalog"].get("content_sha256"),
        "trajectory_h5_content_sha256": h5_record.get("content_sha256"),
        "trajectory_h5_read_by_probe": False,
        "metadata_roles_hashed_by_probe": sorted(REQUIRED_METADATA_ROLES),
        "receipt_checks": receipt_checks,
        "receipt_aliases": aliases,
        "native_reconciliation_scan_aliases": native_receipt_aliases,
        "gencase_solver_control_support": gencase_solver_support,
        "scan_identity": {
            "sha256": scan_sha,
            "family_id": scan.get("family_id"),
            "physical_case_id": scan.get("physical_case_id"),
            "full_saved_timeline_scanned": scan.get("full_saved_timeline_scanned"),
        },
    }


def _copy_runtime(source: Path, target: Path) -> dict[str, Any]:
    if target.exists() or target.is_symlink():
        raise MetadataProbeError(f"refusing to overwrite v24 runtime target: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {"path": str(target.resolve()), "sha256": sha256(target), "bytes": target.stat().st_size}


def _copy_inherited_support(profile_entry: Mapping[str, Any], old_path_map: Mapping[str, Any],
                            output_dir: Path) -> dict[str, Any]:
    """Copy one v22 small support role into the v24 runtime overlay.

    The v22 role identity remains the provenance record in the new profile;
    only the actionable path moves into the new bundle.  The HDF5 trajectory
    is deliberately excluded by the caller, so this helper can be used by a
    metadata-only probe without a second large copy or dataset read.
    """
    role = str(profile_entry.get("role", ""))
    old_value = old_path_map.get(role)
    if not isinstance(old_value, str):
        raise MetadataProbeError(f"v22 copied path is missing inherited support role: {role}")
    source = Path(old_value).expanduser().resolve()
    if not source.is_file():
        raise MetadataProbeError(f"v22 copied support source is missing: {role}: {source}")
    relative = str(profile_entry.get("bundle_relative_path", ""))
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise MetadataProbeError(f"inherited support role has unsafe relative path: {role}")
    target = output_dir / "bundle-v24-runtime" / relative
    copied = _copy_runtime(source, target)
    expected = profile_entry.get("content_sha256")
    if isinstance(expected, str) and copied["sha256"] != expected:
        raise MetadataProbeError(f"v22 inherited support SHA differs: {role}")
    return {
        "role": role,
        "original_path": str(profile_entry.get("original_path", "")),
        "content_sha256": copied["sha256"],
        "bytes": copied["bytes"],
        "original_mtime_ns": profile_entry.get("original_mtime_ns"),
        "bundle_relative_path": relative,
        "inherited_v22_content": True,
    }


def prepare_probe(v22_profile_path: Path, v22_copy_path: Path, v22_replay_path: Path,
                  output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise MetadataProbeError(f"refusing to use existing probe output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    profile_v22 = _load(v22_profile_path)
    copy_result = _load(v22_copy_path)
    replay_input = _load(v22_replay_path)
    inherited = _verify_inherited_bundle(profile_v22, copy_result, replay_input)
    inherited_roles = _role_map(profile_v22)
    old_path_map = copy_result["path_map"]
    profile = copy.deepcopy(profile_v22)
    profile["schema"] = V24_PROFILE_SCHEMA
    profile["profile_id"] = "f2-s1-portable-source-profile-v24-from-v22-bundle-001"
    profile["status"] = "READY_FOR_METADATA_PREFLIGHT; HDF5_CONTENT_INHERITED_FROM_V22_FULLCOPY"
    profile["inherited_v22_bundle"] = {
        "profile_path": str(v22_profile_path.resolve()),
        "profile_sha256": sha256(v22_profile_path),
        "copy_result_path": str(v22_copy_path.resolve()),
        "copy_result_sha256": sha256(v22_copy_path),
        "replay_input_path": str(v22_replay_path.resolve()),
        "replay_input_sha256": sha256(v22_replay_path),
        "trajectory_h5_content_sha256": inherited["trajectory_h5_content_sha256"],
        "trajectory_h5_not_recopied_or_opened_by_probe": True,
    }
    support = [item for item in profile.get("supporting_sources", [])
               if item.get("role") not in V24_REPLACEMENTS]
    if len(support) + len(V24_REPLACEMENTS) != len(profile.get("supporting_sources", [])):
        raise MetadataProbeError("v22 profile does not have both v22 runtime roles")
    runtime_sources = {
        "portable_v24_worker": Path(__file__).with_name("ds_data02_stage2_f2_portable_v24.py"),
        "replay_runner_v24": Path(__file__).with_name("ds_data02_stage2_f2_replay_runner_v24.py"),
    }
    runtime_relatives = {
        "portable_v24_worker": "runtime/portable/ds_data02_stage2_f2_portable_v24.py",
        "replay_runner_v24": "runtime/replay/ds_data02_stage2_f2_replay_runner_v24.py",
    }
    runtime_records: dict[str, dict[str, Any]] = {}
    path_map = {str(role): str(path) for role, path in old_path_map.items()
                if str(role) not in V24_REPLACEMENTS}
    # v22's profile already describes the transitive small closure, but its
    # path map points at the old bundle.  Copy every such role into the new
    # overlay so the v24 runner never imports v16/v15/v14 or the engine files
    # from the old bundle or the original checkout.  Keep trajectory_h5 at
    # the inherited v22 target; it is content-credited and never recopied.
    inherited_support_records: list[dict[str, Any]] = []
    for entry in support:
        role = str(entry.get("role", ""))
        if role in V24_REPLACEMENTS:
            continue
        copied = _copy_inherited_support(entry, old_path_map, output_dir)
        inherited_support_records.append(copied)
        path_map[role] = copied["path"]
    for role, source in runtime_sources.items():
        if not source.is_file():
            raise MetadataProbeError(f"v24 runtime source is missing: {source}")
        target = output_dir / "bundle-v24-runtime" / runtime_relatives[role]
        copied = _copy_runtime(source, target)
        runtime_records[role] = {
            "role": role, "original_path": str(source.resolve()),
            "content_sha256": copied["sha256"], "bytes": copied["bytes"],
            "original_mtime_ns": source.stat().st_mtime_ns,
            "bundle_relative_path": runtime_relatives[role],
        }
        path_map[role] = copied["path"]
    support = inherited_support_records + list(runtime_records.values())
    profile["supporting_sources"] = support
    profile["execution_closure"] = {
        "consumer": "v24 metadata probe -> copied v24 runner -> v15 -> v14",
        "v24_runtime_roles": sorted(runtime_sources),
        "inherited_small_runtime_roles_copied": sorted(item["role"] for item in inherited_support_records),
        "inherited_v22_source_roles": sorted(inherited_roles),
        "hdf5_dataset_read_by_profile_or_probe": False,
        "native_hdf5_c_open_audit": "not applicable; no HDF5 dataset read",
    }
    profile["sha256"] = canonical_sha(profile)
    profile_path = output_dir / "f2-s1-portable-source-profile-v24-metadata.json"
    _write_new(profile_path, profile)

    # Use the already copied v22 request and all existing source role paths.
    request_target = Path(path_map["v15_replay_request"]).resolve()
    if not request_target.is_file():
        raise MetadataProbeError("inherited copied v15 request is missing")
    # Let the v24 portable module validate role completeness and stat-only H5
    # relocation.  This hashes small target files; the inherited H5 record is
    # supplied separately and is never opened by this helper.
    scripts_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(scripts_dir))
    import ds_data02_stage2_f2_portable_v24 as portable  # type: ignore
    verification = portable.verify_relocated_profile(profile, path_map, full_replay=False)
    inherited_h5 = next(item for item in replay_input["source_records"]
                        if isinstance(item, Mapping) and item.get("role") == "trajectory_h5")
    source_records = [record for record in verification["source_records"]
                      if record.get("role") != "trajectory_h5"]
    source_records.append({
        **dict(inherited_h5),
        "content_hash_source": "INHERITED_IMMUTABLE_V22_FULLCOPY_RECEIPT",
        "trajectory_h5_read_by_v24_probe": False,
    })
    overlay = {
        "schema": V24_OVERLAY_SCHEMA,
        "status": "READY_FOR_V15_METADATA_PREFLIGHT; HDF5_HASH_INHERITED",
        "profile_sha256": profile["sha256"],
        "path_map": path_map,
        "consumer_input": {
            "role_to_relocated_path": path_map,
            "original_path_fallback": "FORBIDDEN",
            "trajectory_h5_role": "trajectory_h5",
        },
        "source_records": source_records,
        "full_replay_content_hash_verified": True,
        "trajectory_h5_content_sha256": inherited["trajectory_h5_content_sha256"],
        "trajectory_h5_content_hash_source": "INHERITED_IMMUTABLE_V22_FULLCOPY_RECEIPT",
        "trajectory_h5_read_by_v24_probe": False,
        "qualification": UNKNOWN,
    }
    overlay_path = output_dir / "replay-input-v24-metadata.json"
    _write_new(overlay_path, overlay)
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_METADATA_PREFLIGHT",
        "profile": {"path": str(profile_path), "sha256": sha256(profile_path)},
        "overlay": {"path": str(overlay_path), "sha256": sha256(overlay_path)},
        "request": {"path": str(request_target), "sha256": sha256(request_target)},
        "runner": {"path": path_map["replay_runner_v24"],
                    "sha256": sha256(path_map["replay_runner_v24"])},
        "inherited_v22": inherited,
        "path_map_role_count": len(path_map),
        "trajectory_h5_content_sha256": inherited["trajectory_h5_content_sha256"],
        "trajectory_h5_read": False,
        "trajectory_h5_recopied": False,
        "model_invoked": False,
        "qualification": UNKNOWN,
    }


def run_probe(v22_profile_path: Path, v22_copy_path: Path, v22_replay_path: Path,
              output_dir: Path) -> dict[str, Any]:
    prepared = prepare_probe(v22_profile_path, v22_copy_path, v22_replay_path, output_dir)
    output = output_dir / "metadata-preflight-v24.json"
    command = [
        sys.executable, prepared["runner"]["path"],
        "--profile", prepared["profile"]["path"],
        "--request", prepared["request"]["path"],
        "--path-map", prepared["overlay"]["path"],
        "--output", str(output),
    ]
    completed = subprocess.run(command, cwd=str(output_dir), text=True,
                               capture_output=True, check=False)
    prepared["metadata_preflight_command"] = command
    prepared["metadata_preflight_returncode"] = completed.returncode
    prepared["metadata_preflight_stdout"] = completed.stdout[-4000:]
    prepared["metadata_preflight_stderr"] = completed.stderr[-4000:]
    if output.is_file():
        prepared["metadata_preflight"] = {"path": str(output), "sha256": sha256(output)}
    prepared["status"] = "METADATA_PREFLIGHT_COMPLETE" if completed.returncode == 0 else "METADATA_PREFLIGHT_FAILED"
    receipt_path = output_dir / "metadata-probe-receipt-v24.json"
    _write_new(receipt_path, prepared)
    if completed.returncode != 0:
        raise MetadataProbeError(f"metadata preflight failed; receipt: {receipt_path}: {completed.stderr[-2000:]}")
    return prepared


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = sub.add_parser(name)
        command.add_argument("--v22-profile", type=Path, required=True)
        command.add_argument("--v22-copy-result", type=Path, required=True)
        command.add_argument("--v22-replay-input", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_probe(args.v22_profile.resolve(), args.v22_copy_result.resolve(),
                                   args.v22_replay_input.resolve(), args.output_dir.resolve())
            _write_new(args.output_dir.resolve() / "metadata-probe-prepare-receipt-v24.json", result)
        else:
            result = run_probe(args.v22_profile.resolve(), args.v22_copy_result.resolve(),
                               args.v22_replay_input.resolve(), args.output_dir.resolve())
    except (OSError, MetadataProbeError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result["schema"], "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
