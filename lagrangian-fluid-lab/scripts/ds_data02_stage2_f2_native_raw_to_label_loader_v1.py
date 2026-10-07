#!/usr/bin/env python3
"""Prepare a relocated native raw-to-label replay from a completed bundle.

The v4 native worker owns the raw BI4 -> typed HDF5 -> v15/v16 label
execution.  This loader supplies the missing portable boundary after that
worker has produced a completed report: it verifies that every actionable
bundle role has a relocated path, creates a new v2 request and a new v4
request whose nested source paths point only at the overlay, and writes an
execution/access plan for the parent stage2 guard.

``prepare`` is metadata-only.  It reads JSON and file statistics, but never
opens BI4/HDF5 content and never hashes a large file.  ``verify`` is the
parent-approved content gate; it may hash all raw frames and the reference
HDF5 only when the caller explicitly supplies ``--io-slot-approved``.  The
loader never falls back to an original absolute source path.  Original URIs
remain in provenance fields while actionable request fields use the overlay.

The generated request is an execution input, not a scientific qualification
result.  QI/QN/QE stay UNKNOWN and the optional evaluator is only a
source/profile-bound development diagnostic.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Any, Mapping, Sequence


LOADER_SCHEMA = "ds02.stage2.f2-native-raw-to-label-loader.v1"
PLAN_SCHEMA = "ds02.stage2.f2-native-raw-to-label-execution-plan.v1"
BUNDLE_SCHEMAS = {
    "ds02.stage2.f2-native-raw-to-label-bundle.v1",
    "ds02.stage2.f2-native-raw-to-label-bundle.v2",
}
PATH_MAP_SCHEMA = "ds02.stage2.f2-native-raw-to-label-path-map.v1"
V4_REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-request.v4"
V2_REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# These values deliberately preserve producer provenance.  All other exact
# absolute path values in a request are actionable and are replaced by the
# role overlay when a matching source binding exists.
PROVENANCE_KEYS = {
    "path_provenance", "original_path", "producer_path", "original_input_path",
    "original_uri", "source_uri", "producer_uri",
}


class NativeRawToLabelLoaderError(ValueError):
    """Raised when a relocated raw-to-label overlay is incomplete."""


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise NativeRawToLabelLoaderError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise NativeRawToLabelLoaderError(f"JSON object required: {target}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise NativeRawToLabelLoaderError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise NativeRawToLabelLoaderError(f"refusing to overwrite existing output: {target}") from error


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise NativeRawToLabelLoaderError(f"{name} must be a lowercase SHA-256")
    return value


def _safe_rel(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise NativeRawToLabelLoaderError(f"{name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise NativeRawToLabelLoaderError(f"{name} must not escape the bundle")
    return path.as_posix()


def _manifest_roles(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") not in BUNDLE_SCHEMAS:
        raise NativeRawToLabelLoaderError("raw-to-label bundle schema is required")
    if manifest.get("typed_only") is not False or manifest.get("bundle_kind") != "RAW_TO_TYPED_TO_LABEL_REPLAY_BUNDLE":
        raise NativeRawToLabelLoaderError("typed-only bundle cannot be used for raw replay")
    if manifest.get("qualification") != UNKNOWN:
        raise NativeRawToLabelLoaderError("bundle qualification must remain UNKNOWN")
    if not str(manifest.get("status", "")).startswith("PORTABLE_RAW_TO_LABEL"):
        raise NativeRawToLabelLoaderError("bundle is not marked as an overlay-required raw package")
    values = manifest.get("source_bindings")
    if not isinstance(values, list) or not values:
        raise NativeRawToLabelLoaderError("bundle source_bindings are required")
    roles: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise NativeRawToLabelLoaderError("bundle source role is malformed")
        role = str(item["role"])
        if role in roles:
            raise NativeRawToLabelLoaderError(f"duplicate bundle source role: {role}")
        original = item.get("original_path")
        if not isinstance(original, str) or not Path(original).is_absolute():
            raise NativeRawToLabelLoaderError(f"{role}.original_path must be absolute provenance")
        item_copy = dict(item)
        item_copy["original_path"] = str(Path(original).expanduser().resolve())
        item_copy["bundle_relative_path"] = _safe_rel(item.get("bundle_relative_path"), f"{role}.bundle_relative_path")
        item_copy["content_sha256"] = _sha(item.get("content_sha256"), f"{role}.content_sha256")
        try:
            item_copy["bytes"] = int(item.get("bytes"))
        except (TypeError, ValueError) as error:
            raise NativeRawToLabelLoaderError(f"{role}.bytes is invalid") from error
        if item_copy["bytes"] <= 0:
            raise NativeRawToLabelLoaderError(f"{role}.bytes must be positive")
        roles[role] = item_copy

    raw = manifest.get("raw_producer_binding")
    if not isinstance(raw, Mapping):
        raise NativeRawToLabelLoaderError("raw_producer_binding is required")
    expected_tree = _sha(raw.get("expected_raw_tree_sha256"), "expected raw tree SHA")
    frames = raw.get("frame_bindings")
    frame_roles = sorted((role for role in roles if role.startswith("raw_frame_")))
    if not isinstance(frames, list) or len(frames) != len(frame_roles):
        raise NativeRawToLabelLoaderError("bundle raw frame bindings are incomplete")
    expected_names = [f"raw_frame_{index:04d}" for index in range(len(frames))]
    if frame_roles != expected_names:
        raise NativeRawToLabelLoaderError("raw frame roles are not contiguous from frame zero")
    if raw.get("per_frame_sha256_status") != "VERIFIED_BY_PARENT_WORKER_REPORT":
        raise NativeRawToLabelLoaderError("raw frame SHA evidence is not parent-worker verified")
    return roles


def _load_path_map(path_map_path: Path | str, roles: Mapping[str, Mapping[str, Any]], *,
                   verify_content: bool) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    path_map_file = Path(path_map_path).expanduser().resolve()
    path_map = _load(path_map_file)
    if path_map.get("schema") not in {PATH_MAP_SCHEMA, "ds02.stage2.f2-native-raw-to-label-path-map.v2"}:
        raise NativeRawToLabelLoaderError("path map schema is required")
    if path_map.get("original_path_fallback") != "FORBIDDEN":
        raise NativeRawToLabelLoaderError("path map must forbid original-path fallback")
    if path_map.get("status") in {"TEMPLATE_ONLY_PARENT_OVERLAY_REQUIRED", "TEMPLATE_ONLY"}:
        raise NativeRawToLabelLoaderError("template path map is not an executable overlay")
    mapping = path_map.get("role_to_path")
    if not isinstance(mapping, Mapping):
        raise NativeRawToLabelLoaderError("path map role_to_path is required")
    missing = sorted(set(roles) - set(mapping))
    if missing:
        raise NativeRawToLabelLoaderError(f"path map lacks bundle roles: {missing[:8]}")
    extra = sorted(set(mapping) - set(roles))
    if extra:
        raise NativeRawToLabelLoaderError(f"path map has unknown source roles: {extra[:8]}")
    result: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    for role, item in roles.items():
        target_value = mapping.get(role)
        if not isinstance(target_value, str) or not target_value:
            raise NativeRawToLabelLoaderError(f"path map target is malformed: {role}")
        if target_value.startswith("OVERLAY_REQUIRED/"):
            raise NativeRawToLabelLoaderError(f"path map target remains unresolved: {role}")
        target = Path(target_value).expanduser().resolve()
        if not target.is_file():
            raise NativeRawToLabelLoaderError(f"relocated source is missing: {role}: {target}")
        original = Path(str(item["original_path"])).resolve()
        if target == original:
            raise NativeRawToLabelLoaderError(f"relocated source falls back to original path: {role}")
        stat = target.stat()
        if stat.st_size != int(item["bytes"]):
            raise NativeRawToLabelLoaderError(f"relocated source byte stat differs: {role}")
        expected = str(item["content_sha256"])
        verified = False
        if verify_content:
            if sha256_file(target) != expected:
                raise NativeRawToLabelLoaderError(f"relocated source SHA differs: {role}")
            verified = True
        result[role] = str(target)
        records[role] = {
            "role": role,
            "original_path": str(original),
            "relocated_path": str(target),
            "bytes": int(stat.st_size),
            "content_sha256": expected,
            "content_hash_status": "VERIFIED_NOW" if verified else "PARENT_GUARD_REQUIRED",
            "relocated_mtime_ns": int(stat.st_mtime_ns),
        }
    return result, records


def _path_index(roles: Mapping[str, Mapping[str, Any]], mapped: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role, item in roles.items():
        original = str(Path(str(item["original_path"])).resolve())
        target = str(Path(mapped[role]).resolve())
        prior = result.get(original)
        if prior is not None and prior != target:
            raise NativeRawToLabelLoaderError(
                f"same original source maps to multiple overlay paths: {original}")
        result[original] = target
    return result


def _replace_paths(value: Any, path_index: Mapping[str, str], *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(name): value_item if str(name) in PROVENANCE_KEYS else
            _replace_paths(value_item, path_index, key=str(name))
            for name, value_item in value.items()
        }
    if isinstance(value, list):
        return [_replace_paths(item, path_index, key=key) for item in value]
    if isinstance(value, str) and value.startswith("/"):
        original = str(Path(value).expanduser().resolve())
        return path_index.get(original, value)
    return value


def _update_canonical(value: dict[str, Any]) -> dict[str, Any]:
    if "sha256" in value:
        value["sha256"] = canonical_sha(value)
    return value


def _find_role(roles: Mapping[str, Mapping[str, Any]], suffix: str) -> tuple[str, dict[str, Any]]:
    matches = [(role, dict(item)) for role, item in roles.items()
               if role == suffix or role.endswith(f":{suffix}") or role.endswith(f"_{suffix}")]
    if len(matches) != 1:
        raise NativeRawToLabelLoaderError(f"expected one source role ending in {suffix!r}, found {len(matches)}")
    return matches[0]


def _solver_run_out_role(manifest: Mapping[str, Any], roles: Mapping[str, Mapping[str, Any]],
                         mapped: Mapping[str, str]) -> dict[str, Any]:
    """Resolve the exact producer Run.out without neighbor fallback.

    The source bundle has a solver receipt but intentionally does not treat an
    arbitrary nearby Run.out as evidence.  The producer receipt command and
    output_root define one admissible path.  A portable overlay must register
    that path under the explicit ``solver_run_out`` role before a run plan can
    be emitted.
    """
    solver_role, solver_item = _find_role(roles, "solver_receipt")
    solver_path = Path(mapped[solver_role])
    receipt = _load(solver_path)
    command = receipt.get("command")
    output_root_value = receipt.get("output_root")
    if not isinstance(command, list) or not command or not isinstance(output_root_value, str):
        raise NativeRawToLabelLoaderError("solver receipt command/output_root is required")
    candidates: list[Path] = []
    for value in command:
        if isinstance(value, str) and ("solver_output" in value or value.endswith("output")):
            candidate = Path(value).expanduser()
            if candidate.is_dir():
                candidates.append(candidate / "Run.out")
    root = Path(output_root_value).expanduser()
    candidates.extend([root / "solver_output" / "Run.out", root / "Run.out"])
    unique: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate not in unique:
            unique.append(candidate)
    present = [candidate for candidate in unique if candidate.is_file()]
    if len(present) != 1:
        raise NativeRawToLabelLoaderError(
            "exact solver command output Run.out is missing or ambiguous; "
            f"checked {[str(item) for item in unique]}")
    original_run_out = present[0]
    run_roles = [role for role, item in roles.items()
                 if Path(str(item["original_path"])).resolve() == original_run_out]
    if len(run_roles) != 1:
        raise NativeRawToLabelLoaderError(
            "bundle must contain an explicit solver_run_out source role bound to receipt output")
    return {
        "role": "solver_run_out",
        "producer_receipt_role": solver_role,
        "producer_path": str(original_run_out),
        "relocated_path": mapped[run_roles[0]],
        "source_role": run_roles[0],
        "status": "EXACT_RECEIPT_COMMAND_OUTPUT_BOUND",
    }


def _build_relocated_requests(manifest: Mapping[str, Any], roles: Mapping[str, Mapping[str, Any]],
                              mapped: Mapping[str, str], output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    request_binding = manifest.get("request_binding")
    if not isinstance(request_binding, Mapping) or not isinstance(request_binding.get("path_provenance"), str):
        raise NativeRawToLabelLoaderError("bundle request provenance is missing")
    original_v4_path = Path(str(request_binding["path_provenance"])).expanduser().resolve()
    if not original_v4_path.is_file() or sha256_file(original_v4_path) != request_binding.get("file_sha256"):
        raise NativeRawToLabelLoaderError("original v4 request provenance SHA differs")
    v4_request = _load(original_v4_path)
    if v4_request.get("schema") != V4_REQUEST_SCHEMA:
        raise NativeRawToLabelLoaderError("bundle request is not the v4 native compare schema")
    path_index = _path_index(roles, mapped)

    base_role, base_item = _find_role(roles, "immutable_base_v2_request")
    original_base_path = Path(str(base_item["original_path"])).expanduser().resolve()
    base_request = _load(original_base_path)
    if base_request.get("schema") != V2_REQUEST_SCHEMA:
        raise NativeRawToLabelLoaderError("immutable base request is not the v2 native schema")
    relocated_base = _replace_paths(copy.deepcopy(base_request), path_index)
    # The generated base request is new output.  It must be referenced by the
    # relocated v4 request rather than the copied immutable source bytes.
    relocated_base["portable_overlay_binding"] = {
        "schema": LOADER_SCHEMA,
        "source_request_sha256": sha256_file(original_base_path),
        "original_path_fallback": "FORBIDDEN",
        "run_out_role": "solver_run_out",
    }
    _update_canonical(relocated_base)
    base_output = output_dir / "relocated-base-v2-request.json"
    _write_new(base_output, relocated_base)

    relocated_v4 = _replace_paths(copy.deepcopy(v4_request), path_index)
    relocated_v4["base_v2_request"] = {
        "bytes": base_output.stat().st_size,
        "mtime_ns": base_output.stat().st_mtime_ns,
        "path": str(base_output),
        "role": "generated_relocated_base_v2_request",
        "sha256": sha256_file(base_output),
    }
    relocated_v4["portable_overlay_binding"] = {
        "schema": LOADER_SCHEMA,
        "source_bundle_sha256": canonical_sha(manifest),
        "source_request_sha256": sha256_file(original_v4_path),
        "path_map_roles": len(mapped),
        "original_path_fallback": "FORBIDDEN",
        "solver_run_out_role": "solver_run_out",
        "reference_hdf5_read_policy": "parent_guard_full_hash_then_v4_compare",
        "raw_input_policy": "all bound Part_*.bi4 frames exactly once",
    }
    _update_canonical(relocated_v4)
    v4_output = output_dir / "relocated-v4-request.json"
    _write_new(v4_output, relocated_v4)
    return base_output, v4_output, {
        "original_v4_request": str(original_v4_path),
        "relocated_v4_request": str(v4_output),
        "original_base_v2_request": str(original_base_path),
        "relocated_base_v2_request": str(base_output),
        "base_role": base_role,
    }


def _command(v4_request: Path, output_dir: Path, *, run_evaluator: bool,
             predictions_path: Path | None) -> list[str]:
    compare = output_dir / "../runtime/ds_data02_stage2_f2_native_raw_to_typed_compare_v4.py"
    command = [
        "<bound-python>", str(compare.resolve()), "run", "--request", str(v4_request),
        "--output-dir", str(output_dir / "execution"), "--io-slot-approved",
    ]
    if run_evaluator:
        if predictions_path is None:
            raise NativeRawToLabelLoaderError("evaluator requested without predictions path")
        command.extend(["--run-evaluator", "--predictions", str(predictions_path)])
    return command


def prepare_plan(bundle_path: Path | str, path_map_path: Path | str, output_dir: Path | str,
                 *, io_slot_approved: bool = False, run_evaluator: bool = False,
                 predictions_path: Path | None = None) -> dict[str, Any]:
    bundle_file = Path(bundle_path).expanduser().resolve()
    path_map_file = Path(path_map_path).expanduser().resolve()
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise NativeRawToLabelLoaderError(f"refusing to use existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    manifest = _load(bundle_file)
    roles = _manifest_roles(manifest)
    mapped, records = _load_path_map(path_map_file, roles, verify_content=io_slot_approved)
    # The solver receipt is a small JSON; resolving its declared output path
    # does not inspect BI4/HDF5.  It intentionally requires Run.out to be an
    # explicit bundle role instead of accepting a neighboring log.
    run_out = _solver_run_out_role(manifest, roles, mapped)
    base_output, v4_output, request_info = _build_relocated_requests(
        manifest, roles, mapped, target)
    anchor = manifest.get("seven_family_anchor_index")
    if not isinstance(anchor, Mapping) or anchor.get("status") != "SEVEN_FAMILY_PLAN_CONNECTED_F2_CASE_78":
        raise NativeRawToLabelLoaderError("seven-family anchor index is not connected to F2 CURRENT case 78")
    access = {
        "schema": "ds02.stage2.f2-native-raw-to-label-access-index.v1",
        "status": "CONTENT_VERIFIED_PARENT_GUARD" if io_slot_approved else "METADATA_ONLY_PARENT_GUARD_REQUIRED",
        "source_roles": list(records.values()),
        "solver_run_out": run_out,
        "seven_family_anchor_index": {
            "status": anchor.get("status"),
            "families": [item.get("family_id") for item in anchor.get("families", [])
                         if isinstance(item, Mapping)],
            "selected": anchor.get("selected_anchor"),
            "raw_reads": "NONE; anchor plans are source-bound plan metadata only",
        },
        "read_access_policy": {
            "raw_bi4": "all bound Part_*.bi4 once; PartOut/RunPARTs provenance only",
            "new_typed": "write generated typed-reconstructed-v2.h5 under new execution directory",
            "reference_hdf5": "parent full-hash then v4 frame/chunk comparison; no copy as reconstruction input",
            "labels": "v15 then v16 only after typed validation and exact source binding",
            "evaluator": "optional v15 frozen-profile manual predictions; DEVELOPMENT only",
            "strace": "parent OS-level openat audit required because Python audit hooks miss HDF5 C opens",
            "original_path_fallback": "FORBIDDEN",
        },
        "runtime_closure": manifest.get("import_closure"),
        "license_closure": {
            "dependency_index_roles": [role for role in roles if "license" in role.lower() or "dependency" in role.lower()],
            "all_loaded_python_and_native_library_paths": "parent guard records actual __file__/strace paths",
        },
    }
    access_path = target / "raw-to-label-access-index-v1.json"
    _write_new(access_path, access)
    command = _command(v4_output, target, run_evaluator=run_evaluator,
                       predictions_path=predictions_path)
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "READY_FOR_PARENT_IO_SLOT" if not io_slot_approved else "CONTENT_VERIFIED_READY_FOR_PARENT_EXECUTION",
        "role": "DEVELOPMENT",
        "qualification": UNKNOWN,
        "bundle": {"path": str(bundle_file), "sha256": sha256_file(bundle_file)},
        "path_map": {"path": str(path_map_file), "sha256": sha256_file(path_map_file),
                     "content_verification": "FULL" if io_slot_approved else "STAT_ONLY"},
        "requests": request_info,
        "access_index": {"path": str(access_path), "sha256": sha256_file(access_path)},
        "command": command,
        "evaluator": {
            "requested": bool(run_evaluator),
            "predictions_path": str(predictions_path) if predictions_path else None,
            "status": "PENDING_PARENT_EXECUTION" if run_evaluator else "NOT_REQUESTED",
        },
        "resource_boundary": {
            "raw_frame_count": len([role for role in roles if role.startswith("raw_frame_")]),
            "read_mode": "parent-approved full content" if io_slot_approved else "metadata/stat only",
            "new_output_only": True,
            "no_model": True,
            "no_cfd": True,
            "no_solver": True,
        },
        "limitations": [
            "This plan does not itself read BI4/HDF5; parent stage2 guard owns content verification and execution.",
            "The seven family anchors are connected plan metadata, not seven completed raw reconstructions.",
            "Raw/typed/label results remain DEVELOPMENT evidence and QI/QN/QE stay UNKNOWN.",
        ],
    }
    plan["sha256"] = canonical_sha(plan)
    plan_path = target / "raw-to-label-execution-plan-v1.json"
    _write_new(plan_path, plan)
    plan["plan_path"] = str(plan_path)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("prepare")
    plan.add_argument("--bundle", type=Path, required=True)
    plan.add_argument("--path-map", type=Path, required=True)
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--io-slot-approved", action="store_true")
    plan.add_argument("--run-evaluator", action="store_true")
    plan.add_argument("--predictions", type=Path)
    args = parser.parse_args(argv)
    try:
        result = prepare_plan(args.bundle, args.path_map, args.output_dir,
                              io_slot_approved=args.io_slot_approved,
                              run_evaluator=args.run_evaluator,
                              predictions_path=args.predictions)
    except (OSError, NativeRawToLabelLoaderError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result.get("schema"), "status": result.get("status"),
                      "qualification": result.get("qualification")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
