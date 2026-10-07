#!/usr/bin/env python3
"""Build metadata-only runnable raw-anchor bundles for the six non-F2 families.

F1/F3/F5/F7 use the guarded generic v2 worker and F4/F6 use the generic v1
worker.  This index does not read HDF5 or BI4 content and does not invent a
raw-tree digest.  It records the exact request, source paths, frame spans,
decoder/worker closure, mass semantics, and parent command so each family
can later receive its own CPU/I/O slot.  Typed comparison and family labels
remain pending until that request actually runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
REQUEST_SCHEMA_PREFIX = "ds02.stage2.family-native-raw-to-typed-compare-request."
BUNDLE_SCHEMA = "ds02.stage2.family-native-raw-anchor-bundle.v1"
INDEX_SCHEMA = "ds02.stage2.family-native-raw-anchor-index.v1"
HEX64 = set("0123456789abcdef")


class FamilyAnchorError(RuntimeError):
    """Raised when a family request is not safe to expose as a raw anchor."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FamilyAnchorError(f"cannot read request {path}: {error}") from error
    if not isinstance(value, dict):
        raise FamilyAnchorError(f"request JSON object required: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FamilyAnchorError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        stream.write("\n")


def _path(path: Any, role: str) -> Path:
    if not isinstance(path, str):
        raise FamilyAnchorError(f"{role}.path is missing")
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FamilyAnchorError(f"{role} source is missing: {target}")
    return target


def _directory(path: Any, role: str) -> Path:
    if not isinstance(path, str):
        raise FamilyAnchorError(f"{role}.path is missing")
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise FamilyAnchorError(f"{role} directory is missing: {target}")
    return target


def _sha_or_pending(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 64 and all(char in HEX64 for char in value):
        return value
    return None


def _stat_record(item: Mapping[str, Any], role: str, *, content_read: bool = False) -> dict[str, Any]:
    target = _path(item.get("path"), role)
    stat = target.stat()
    declared_bytes = item.get("bytes")
    if declared_bytes is not None and int(declared_bytes) != stat.st_size:
        raise FamilyAnchorError(f"{role} declared bytes differ")
    declared_mtime = item.get("mtime_ns")
    if declared_mtime is not None and int(declared_mtime) != stat.st_mtime_ns:
        raise FamilyAnchorError(f"{role} declared mtime differs")
    declared_sha = _sha_or_pending(item.get("sha256"))
    if content_read and declared_sha is not None and sha256_file(target) != declared_sha:
        raise FamilyAnchorError(f"{role} content SHA differs")
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "declared_sha256": declared_sha,
            "content_read": content_read}


def _source_closure(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool, int]:
    values: list[dict[str, Any]] = []
    for item in request.get("source_files", []):
        if not isinstance(item, Mapping):
            raise FamilyAnchorError("source_files entry is malformed")
        values.append(_stat_record(item, str(item.get("role", "source"))))
    if not values:
        raise FamilyAnchorError("source_files are required")
    # input_files are included in the parent request closure.  Checking their
    # existence is metadata-only and catches stale worktree aliases before a
    # slot is reserved.  Their content hashes remain request/guard evidence;
    # this builder does not hash these files.
    missing: list[str] = []
    input_count = 0
    for item in request.get("input_files", []):
        raw = item.get("path") if isinstance(item, Mapping) else item
        if not isinstance(raw, str):
            continue
        input_count += 1
        if not Path(raw).expanduser().is_file():
            missing.append(raw)
    if missing:
        raise FamilyAnchorError(f"request input closure has missing paths: {missing[:3]}")
    return values, len(missing) == 0, input_count


def _frames(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise FamilyAnchorError("raw_binding is required")
    root = _directory(raw.get("data_root"), "raw_binding.data_root")
    frames = raw.get("frames")
    expected_count = raw.get("frame_count")
    if not isinstance(frames, list) or not isinstance(expected_count, int) or len(frames) != expected_count:
        raise FamilyAnchorError("raw frame list/count are incomplete")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise FamilyAnchorError("raw frames must be contiguous from zero")
        target = _path(item.get("path"), f"raw frame {index}")
        if target.parent != root or target.name != f"Part_{index:04d}.bi4":
            raise FamilyAnchorError(f"raw frame {index} is not the expected Part path")
        stat = target.stat()
        if item.get("bytes") is not None and int(item["bytes"]) != stat.st_size:
            raise FamilyAnchorError(f"raw frame {index} byte stat differs")
        records.append({"frame": index, "path": str(target), "bytes": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns),
                        "declared_sha256": _sha_or_pending(item.get("sha256")),
                        "content_read": False})
    tree = _sha_or_pending(raw.get("expected_raw_tree_sha256"))
    return records, {
        "data_root": str(Path(str(raw["data_root"])).expanduser().resolve()),
        "frame_count": len(records),
        "frame_pattern": raw.get("frame_pattern"),
        "expected_raw_tree_sha256": tree,
        "expected_raw_tree_status": raw.get("expected_raw_tree_status", "UNKNOWN_PENDING_PARENT_WORKER"),
        "producer_tree_digest_invented": raw.get("producer_tree_digest_invented") is True,
        "first_frame": records[0], "last_frame": records[-1],
        "raw_source_bytes_stat": sum(item["bytes"] for item in records),
        "per_frame_content_sha256": "PENDING_PARENT_WORKER" if tree is None else "REQUEST_DECLARED_ONLY",
    }


def build_family_bundle(request_path: Path, output_path: Path) -> dict[str, Any]:
    request = load_json(request_path)
    schema = request.get("schema")
    if not isinstance(schema, str) or not schema.startswith(REQUEST_SCHEMA_PREFIX):
        raise FamilyAnchorError(f"unsupported family request schema: {schema!r}")
    family = request.get("family_id")
    if family not in {"F1", "F3", "F4", "F5", "F6", "F7"}:
        raise FamilyAnchorError(f"raw anchor index only handles the six non-F2 families: {family!r}")
    if request.get("role") != "DEVELOPMENT" or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise FamilyAnchorError(f"{family} request is not parent-guard ready")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise FamilyAnchorError(f"{family} model/CFD flags are unsafe")
    if request.get("qualification") != UNKNOWN:
        raise FamilyAnchorError(f"{family} qualification must remain UNKNOWN")
    current = request.get("current_binding")
    if not isinstance(current, Mapping):
        raise FamilyAnchorError(f"{family} current binding is missing")
    current_catalog = current.get("catalog")
    catalog_stat = _stat_record(current_catalog, f"{family}.current_catalog") if isinstance(current_catalog, Mapping) else None
    if catalog_stat is None:
        raise FamilyAnchorError(f"{family} current catalog binding is malformed")
    source_records, closure_complete, input_count = _source_closure(request)
    frames, raw = _frames(request)
    typed_ref = request.get("typed_reference_hdf5")
    if not isinstance(typed_ref, Mapping):
        raise FamilyAnchorError(f"{family} typed_reference_hdf5 is missing")
    h5_stat = _stat_record(typed_ref, f"{family}.typed_reference_hdf5")
    modules = request.get("modules", {})
    module_records = []
    if isinstance(modules, Mapping):
        for role, item in modules.items():
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                module_records.append(_stat_record(item, f"{family}.module.{role}"))
    decoder = request.get("decoder")
    decoder_record = _stat_record(decoder, f"{family}.decoder") if isinstance(decoder, Mapping) else None
    command = request.get("execution", {}).get("full_parent_guard_command") if isinstance(request.get("execution"), Mapping) else None
    if not isinstance(command, list) or not command:
        raise FamilyAnchorError(f"{family} full parent guard command is missing")
    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": f"{family.lower()}-s1-native-raw-anchor-v1-001",
        "status": "READY_FOR_PARENT_GUARD; TYPED_COMPARE_PENDING; LABELS_PENDING; DEVELOPMENT_UNKNOWN",
        "role": "DEVELOPMENT",
        "family_id": family,
        "source_request": {"path": str(request_path.resolve()), "sha256": sha256_file(request_path),
                            "schema": schema, "request_id": request.get("request_id")},
        "current_binding": {
            "family_id": current.get("family_id", family),
            "case_index": current.get("case_index"),
            "physical_case_id": current.get("physical_case_id"),
            "runtime_case_alias": current.get("runtime_case_alias"),
            "frames": current.get("frames"),
            "particles": current.get("particles"),
            "identity_key": current.get("identity_key"),
            "catalog": catalog_stat,
            "trajectory_h5_producer_sha256": current.get("trajectory_h5", {}).get("sha256") if isinstance(current.get("trajectory_h5"), Mapping) else None,
            "producer_sha_scope": current.get("producer_sha_scope"),
        },
        "raw_anchor": raw,
        "typed_reference_binding": h5_stat,
        "source_closure": {
            "complete_stat_only": closure_complete,
            "input_file_count": input_count,
            "source_files": source_records,
            "modules": module_records,
            "decoder": decoder_record,
            "content_hash_execution": "parent guard must verify declared hashes; this builder only stats paths",
        },
        "execution": {
            "command": command,
            "entrypoint": request.get("execution", {}).get("entrypoint") if isinstance(request.get("execution"), Mapping) else None,
            "requires_parent_stage2guard": True,
            "io_slot": "CPU1",
            "raw_bi4_read": True,
            "typed_reference_hdf5_read": True,
            "solver_model_cfd": False,
            "output_new_only": True,
        },
        "typed_output_contract": request.get("typed_output_contract", {}),
        "mass_semantics": request.get("mass_semantics", {}),
        "label_scope": request.get("labels", {}),
        "identity_lifecycle": {
            "identity_key": request.get("typed_output_contract", {}).get("identity_key") if isinstance(request.get("typed_output_contract"), Mapping) else None,
            "valid_mask_source": request.get("typed_output_contract", {}).get("lifecycle") if isinstance(request.get("typed_output_contract"), Mapping) else None,
            "invalid_state_credit": "UNKNOWN until actual converter/typed comparison",
        },
        "qualification": UNKNOWN,
        "model_invoked": False,
        "cfd_invoked": False,
        "limitations": [
            "No raw frame content, HDF5 content, or solver output was read by this index builder.",
            "No expected raw-tree SHA is invented when the family request leaves it pending.",
            "Typed comparison, invalid/missing lifecycle, pressure, body-mass separation, and family labels remain pending until the exact request runs.",
        ],
    }
    bundle["sha256"] = canonical_sha(bundle)
    write_new(output_path, bundle)
    return {"path": str(output_path.resolve()), "sha256": bundle["sha256"],
            "family_id": family, "frame_count": raw["frame_count"],
            "raw_source_bytes_stat": raw["raw_source_bytes_stat"]}


def build_index(request_paths: Sequence[Path], output_dir: Path, *, f2_bundle: Path | None = None,
                f2_request: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for request_path in request_paths:
        request = load_json(request_path)
        family = str(request.get("family_id"))
        bundle_path = output_dir / f"{family.lower()}-s1-native-raw-anchor-bundle-v1-001.json"
        built = build_family_bundle(request_path.expanduser().resolve(), bundle_path)
        entries.append({"family_id": family, "status": "READY_FOR_PARENT_GUARD; DEVELOPMENT_UNKNOWN",
                        "bundle": built, "request": {"path": str(request_path.resolve()),
                                                       "sha256": sha256_file(request_path)},
                        "actual_or_pending": "PLANNED_REQUEST; NO_NATIVE_EXECUTION_CREDIT"})
    index: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "index_id": "six-family-native-raw-anchor-index-v1-001",
        "status": "SIX_NON_F2_RAW_ANCHORS_READY_FOR_INDEPENDENT_PARENT_SLOTS",
        "families": sorted(entries, key=lambda item: item["family_id"]),
        "f2_reference": {
            "status": "F2_NATIVE_V4_TERMINAL_VERIFIED; EXECUTABLE_PORTABLE_V4_FORWARD",
            "bundle": {"path": str(f2_bundle.resolve()), "sha256": sha256_file(f2_bundle)} if f2_bundle else None,
            "request": {"path": str(f2_request.resolve()), "sha256": sha256_file(f2_request)} if f2_request else None,
            "receiver_scope": "F2 finite receiver volume/top aperture only; not applied to other families",
        },
        "common_policy": {
            "raw_to_typed_first": True,
            "partout_runparts_substitute": False,
            "typed_id_key": "(Zone,Idp) where request binds it",
            "rigid_body_mass_from_particle_sum": False,
            "unknown_tree_digest": "preserve request pending state",
            "model_invoked": False,
            "cfd_invoked": False,
            "qualification": UNKNOWN,
        },
        "limitations": [
            "This is an executable request/index closure, not evidence that the six native jobs have run.",
            "Family-specific labels and geometry semantics stay UNKNOWN until each parent guard executes the bound worker.",
            "All source paths are provenance plus parent-copy inputs; no source content was read here.",
        ],
        "qualification": UNKNOWN,
    }
    index["sha256"] = canonical_sha(index)
    index_path = output_dir / "six-family-native-raw-anchor-index-v1-001.json"
    write_new(index_path, index)
    return {"path": str(index_path), "sha256": index["sha256"], "families": [item["family_id"] for item in index["families"]]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--f2-bundle", type=Path)
    parser.add_argument("--f2-request", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_index(args.requests, args.output_dir,
                             f2_bundle=args.f2_bundle, f2_request=args.f2_request)
    except (FamilyAnchorError, OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
