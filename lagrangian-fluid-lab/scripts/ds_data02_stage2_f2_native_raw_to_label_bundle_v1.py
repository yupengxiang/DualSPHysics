#!/usr/bin/env python3
"""Build a portable, source-bound F2 native raw-to-label replay bundle.

The v4 worker produces a typed HDF5 plus v15/v16 labels after reading every
native ``Part_*.bi4`` frame.  This module packages the *raw input binding*,
typed comparison evidence, label result bindings, imported-code closure, and
seven-family anchor index into a new overlay manifest.  It never copies or
opens HDF5/BI4 content.  A later parent-approved copy/replay supplies a path
map and performs the full content checks.

The bundle is deliberately marked ``PORTABLE_RAW_TO_LABEL_OVERLAY_REQUIRED``:
the source identities and every observed raw-frame SHA are retained, while
original absolute paths remain provenance and cannot be used as a fallback.
A typed-output-only report is rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v1"
PATH_MAP_SCHEMA = "ds02.stage2.f2-native-raw-to-label-path-map.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-request.v4"
REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-report.v4"
V2_REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
H5_SUFFIXES = {".h5", ".hdf5"}


class RawToLabelBundleError(ValueError):
    """Raised when the replay bundle cannot be source-bound or portable."""


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
    path = Path(path).expanduser().resolve()
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RawToLabelBundleError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RawToLabelBundleError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RawToLabelBundleError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise RawToLabelBundleError(f"refusing to overwrite existing output: {target}") from error


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise RawToLabelBundleError(f"{name} must be a lowercase SHA-256")
    return value


def _require_file_binding(item: Mapping[str, Any], role: str, *, stat_only: bool = False) -> dict[str, Any]:
    path_value = item.get("path") or item.get("original_path")
    if not isinstance(path_value, str) or not path_value:
        raise RawToLabelBundleError(f"{role}.path is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise RawToLabelBundleError(f"{role} source is missing: {path}")
    expected = _require_sha(item.get("sha256") or item.get("content_sha256") or item.get("expected_content_sha256"),
                           f"{role}.sha256")
    stat = path.stat()
    declared_bytes = item.get("bytes")
    if declared_bytes is not None and int(declared_bytes) != stat.st_size:
        raise RawToLabelBundleError(f"{role} byte stat differs")
    result = {
        "role": role,
        "original_path": str(path),
        "bytes": int(stat.st_size),
        "original_mtime_ns": int(stat.st_mtime_ns),
        "content_sha256": expected,
        "content_hash_status": "RECORDED_FROM_REQUEST" if stat_only else "VERIFIED_NOW",
    }
    if not stat_only and sha256_file(path) != expected:
        raise RawToLabelBundleError(f"{role} content SHA differs")
    return result


def _request_canonical(request: Mapping[str, Any]) -> str:
    declared = _require_sha(request.get("sha256"), "request.sha256")
    if canonical_sha(request) != declared:
        raise RawToLabelBundleError("request canonical SHA differs")
    return declared


def _resolve_report_ref(value: Any, role: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        raise RawToLabelBundleError(f"{role} report binding is malformed")
    path = Path(str(value["path"])).expanduser().resolve()
    if not path.is_file():
        raise RawToLabelBundleError(f"{role} report is missing: {path}")
    expected = _require_sha(value.get("report_sha256") or value.get("sha256"), f"{role}.sha256")
    actual = sha256_file(path)
    if actual != expected:
        raise RawToLabelBundleError(f"{role} report SHA differs")
    return path, expected


def _load_bound_reports(request_path: Path, report_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request = _load(request_path)
    if request.get("schema") != REQUEST_SCHEMA:
        raise RawToLabelBundleError("v4 native compare request schema is required")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN_QUALIFICATION:
        raise RawToLabelBundleError("request must remain DEVELOPMENT with UNKNOWN qualification")
    request_sha = _request_canonical(request)
    report = _load(report_path)
    if report.get("schema") != REPORT_SCHEMA:
        raise RawToLabelBundleError("v4 native compare report schema is required")
    if report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RawToLabelBundleError("raw-to-label bundle requires a completed v4 development report")
    report_request = report.get("request")
    if not isinstance(report_request, Mapping):
        raise RawToLabelBundleError("v4 report request binding is missing")
    if Path(str(report_request.get("path", ""))).expanduser().resolve() != request_path:
        raise RawToLabelBundleError("v4 report is bound to a different request path")
    if report_request.get("sha256") != sha256_file(request_path):
        raise RawToLabelBundleError("v4 report request file SHA differs")
    base_ref = report.get("base_v2")
    base_path, base_sha = _resolve_report_ref(base_ref, "base_v2")
    base_report = _load(base_path)
    if base_report.get("schema") != V2_REPORT_SCHEMA or base_report.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise RawToLabelBundleError("v2 report is not a completed raw-to-typed-to-label report")
    base_request_ref = base_report.get("request")
    if not isinstance(base_request_ref, Mapping):
        raise RawToLabelBundleError("v2 report request binding is missing")
    raw_to_typed = base_report.get("raw_to_typed")
    evidence = raw_to_typed.get("raw_evidence") if isinstance(raw_to_typed, Mapping) else None
    if not isinstance(evidence, Mapping):
        raise RawToLabelBundleError("v2 report does not contain native raw evidence")
    labels = base_report.get("typed_to_label")
    if not isinstance(labels, Mapping) or not isinstance(labels.get("result"), str):
        raise RawToLabelBundleError("v2 report has no v15 label result; typed-only bundle is rejected")
    return request, report, base_report, {"request_sha": request_sha, "base_path": base_path,
                                           "base_sha": base_sha, "evidence": dict(evidence),
                                           "labels": dict(labels)}


def _frame_bindings(request: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = request.get("source_closure", {}).get("raw_frame_binding", {})
    expected_root = raw.get("data_root")
    expected_tree = _require_sha(raw.get("expected_raw_tree_sha256"), "raw expected tree SHA")
    expected_count = int(raw.get("frame_count", -1))
    frames = evidence.get("frames")
    if not isinstance(frames, list) or len(frames) != expected_count:
        raise RawToLabelBundleError("raw evidence does not cover every bound frame")
    if evidence.get("before_tree_sha256") != expected_tree or evidence.get("after_tree_sha256") != expected_tree:
        raise RawToLabelBundleError("raw evidence tree SHA differs or changed during conversion")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise RawToLabelBundleError(f"raw evidence frame order is malformed at {index}")
        path = item.get("path")
        frame_sha = item.get("raw_frame_file_sha256")
        if not isinstance(path, str) or not isinstance(expected_root, str) or not isinstance(frame_sha, str):
            raise RawToLabelBundleError(f"raw evidence frame binding is incomplete at {index}")
        _require_sha(frame_sha, f"raw frame {index} SHA")
        resolved = Path(path).expanduser().resolve()
        if resolved.parent != Path(expected_root).expanduser().resolve() or resolved.name != f"Part_{index:04d}.bi4":
            raise RawToLabelBundleError(f"raw evidence frame path is outside exact producer root at {index}")
        bytes_value = int(item.get("raw_frame_file_bytes", -1))
        if bytes_value <= 0:
            raise RawToLabelBundleError(f"raw evidence frame byte count is invalid at {index}")
        result.append({
            "role": f"raw_frame_{index:04d}",
            "original_path": str(resolved),
            "bundle_relative_path": f"raw/Part_{index:04d}.bi4",
            "bytes": bytes_value,
            "content_sha256": frame_sha,
            "content_hash_status": "VERIFIED_BY_PARENT_WORKER_REPORT",
            "frame": index,
        })
    return result


def _artifact_binding(path_value: Any, expected_sha: Any, role: str, *, h5: bool = False,
                      expected_bytes: Any = None) -> dict[str, Any]:
    if not isinstance(path_value, str):
        raise RawToLabelBundleError(f"{role}.path is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise RawToLabelBundleError(f"derived artifact is missing: {role}: {path}")
    expected = _require_sha(expected_sha, f"{role}.sha256")
    stat = path.stat()
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise RawToLabelBundleError(f"{role} byte stat differs")
    # HDF5 is a derived artifact here.  Its content SHA is already bound by
    # the v4 worker/parent receipt; this packager intentionally does not reread
    # a 1.2 GiB file.
    return {
        "role": role,
        "original_path": str(path),
        "bundle_relative_path": f"derived/{path.name}",
        "bytes": int(stat.st_size),
        "content_sha256": expected,
        "content_hash_status": "PARENT_REPORT_BOUND_NO_REREAD" if h5 else "PARENT_REPORT_BOUND",
        "read_policy": "reference_artifact_only" if h5 else "copyable_json_artifact",
    }


def _label_bindings(base_report: Mapping[str, Any], labels: Mapping[str, Any], *,
                    expected_raw_tree_sha: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    v15 = _artifact_binding(labels.get("result"), labels.get("result_sha256"),
                            "v15_label_result")
    # A label JSON that happens to exist is not enough.  The v15 result must
    # carry the reconstruction binding written by the raw worker, including
    # the producer tree digest.  This prevents packaging a typed/H5 result
    # produced from a different raw source under the current request.
    if expected_raw_tree_sha is not None:
        label_doc = _load(v15["original_path"])
        reconstruction = label_doc.get("reconstruction_binding")
        if (not isinstance(reconstruction, Mapping) or
                reconstruction.get("raw_tree_sha256") != expected_raw_tree_sha):
            raise RawToLabelBundleError("v15 label result is not bound to the v4 raw producer tree")
    result.append(v15)
    forward = labels.get("v16_forward")
    if isinstance(forward, Mapping) and isinstance(forward.get("result"), str):
        result.append(_artifact_binding(forward.get("result"), forward.get("result_sha256"),
                                        "v16_forward_result"))
    evaluator = labels.get("manual_evaluator")
    if isinstance(evaluator, Mapping) and isinstance(evaluator.get("result"), str):
        result.append(_artifact_binding(evaluator.get("result"), evaluator.get("result_sha256"),
                                        "v15_manual_evaluation"))
    if not result:
        raise RawToLabelBundleError("no label artifact was bound")
    return result


def _source_records(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    closure = request.get("source_closure")
    if not isinstance(closure, Mapping):
        raise RawToLabelBundleError("request source closure is missing")
    records: list[dict[str, Any]] = []
    for item in closure.get("raw_v2_source_roles", []):
        if not isinstance(item, Mapping):
            raise RawToLabelBundleError("raw source role is malformed")
        role = str(item.get("role", "source"))
        records.append(_require_file_binding(item, f"source:{role}", stat_only=True) | {
            "role": role,
            "replay_actionable": role not in {"v2:native_partout", "v2:native_runparts"},
        })
    wrapper = request.get("root_canonical_wrapper")
    if not isinstance(wrapper, Mapping):
        raise RawToLabelBundleError("root canonical wrapper binding is required")
    # The wrapper's explicit immutable list includes the complete private
    # import/guard closure.  De-duplicate by role+path while preserving roles
    # with different provenance prefixes.
    seen: set[tuple[str, str]] = {(str(item["role"]), str(item["original_path"])) for item in records}
    for item in wrapper.get("immutable_file_bindings", []):
        if not isinstance(item, Mapping):
            raise RawToLabelBundleError("immutable wrapper binding is malformed")
        path = item.get("path") or item.get("original_path")
        role = str(item.get("role", "immutable_source"))
        if not isinstance(path, str):
            raise RawToLabelBundleError(f"immutable binding path is missing: {role}")
        key = (role, str(Path(path).expanduser().resolve()))
        if key in seen:
            continue
        seen.add(key)
        # Keep the H5 source as a parent-bound content identity without a
        # second full read; all small code/JSON bindings are independently
        # stat-checked and their declared SHA retained.
        records.append(_require_file_binding(item, f"wrapper:{role}", stat_only=True) | {
            "role": role,
            "replay_actionable": True,
        })
    return records


def _anchor_bindings(anchor_index_path: Path, *, current_case_index: int, family_id: str) -> dict[str, Any]:
    if not anchor_index_path.is_file():
        raise RawToLabelBundleError(f"seven-family anchor index is missing: {anchor_index_path}")
    index = _load(anchor_index_path)
    if index.get("schema") != "ds02.stage2.family-raw-anchor-plan-index.v1" or index.get("seven_family_coverage") is not True:
        raise RawToLabelBundleError("seven-family raw anchor index schema/coverage is invalid")
    families = index.get("families")
    if not isinstance(families, list) or len(families) != 7:
        raise RawToLabelBundleError("seven-family raw anchor index must enumerate seven families")
    rows: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for row in families:
        if not isinstance(row, Mapping):
            raise RawToLabelBundleError("seven-family anchor row is malformed")
        path = Path(str(row.get("path", ""))).expanduser().resolve()
        if not path.is_file():
            raise RawToLabelBundleError(f"family anchor plan is missing: {path}")
        plan_sha = sha256_file(path)
        record = {
            "family_id": row.get("family_id"),
            "anchor_current_index": row.get("anchor_current_index"),
            "anchor_physical_case_id": row.get("anchor_physical_case_id"),
            "plan_original_path": str(path),
            "plan_sha256": plan_sha,
            "raw_root": row.get("raw_root"),
            "status": row.get("status"),
        }
        rows.append(record)
        if row.get("family_id") == family_id:
            if selected is not None:
                raise RawToLabelBundleError(f"duplicate family anchor: {family_id}")
            selected = record
    if selected is None or selected.get("anchor_current_index") != current_case_index:
        raise RawToLabelBundleError("selected family anchor does not bind the exact CURRENT case index")
    return {
        "index_original_path": str(anchor_index_path.resolve()),
        "index_sha256": sha256_file(anchor_index_path),
        "case_count": index.get("case_count"),
        "families": rows,
        "selected_anchor": selected,
        "status": "SEVEN_FAMILY_PLAN_CONNECTED_F2_CASE_78",
    }


def _path_map_template(manifest: Mapping[str, Any]) -> dict[str, Any]:
    entries = manifest.get("source_bindings", [])
    if not isinstance(entries, list):
        raise RawToLabelBundleError("manifest source_bindings are required")
    paths: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise RawToLabelBundleError("manifest source binding role is malformed")
        role = str(item["role"])
        if role in paths:
            raise RawToLabelBundleError(f"duplicate source role in path map: {role}")
        paths[role] = f"OVERLAY_REQUIRED/{item.get('bundle_relative_path', role)}"
    return {
        "schema": PATH_MAP_SCHEMA,
        "status": "TEMPLATE_ONLY_PARENT_OVERLAY_REQUIRED",
        "original_path_fallback": "FORBIDDEN",
        "role_to_path": paths,
        "raw_frame_sha256": "must be recomputed/verified by parent guard before replay",
        "reference_hdf5_sha256": "must be full-hash verified by parent copy worker before HDF5 replay",
    }


def build_bundle_manifest(request_path: Path | str, report_path: Path | str,
                          anchor_index_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    report_file = Path(report_path).expanduser().resolve()
    anchor_file = Path(anchor_index_path).expanduser().resolve()
    request, report, base, context = _load_bound_reports(request_file, report_file)
    evidence = context["evidence"]
    raw_frames = _frame_bindings(request, evidence)
    typed = base.get("typed_output")
    if not isinstance(typed, Mapping):
        raise RawToLabelBundleError("typed output binding is missing")
    typed_artifact = _artifact_binding(typed.get("path"), typed.get("sha256"), "typed_reconstruction_hdf5",
                                       h5=True, expected_bytes=typed.get("bytes"))
    labels = context["labels"]
    raw_binding = request["root_canonical_wrapper"]["raw_producer_binding"]
    expected_raw_tree = _require_sha(raw_binding.get("expected_raw_tree_sha256"), "raw tree SHA")
    label_artifacts = _label_bindings(base, labels, expected_raw_tree_sha=expected_raw_tree)
    current = report.get("current_reference")
    if not isinstance(current, Mapping) or current.get("case_index") != 78:
        raise RawToLabelBundleError("v4 report is not bound to CURRENT case 78")
    reference = request.get("reference_typed_hdf5")
    if not isinstance(reference, Mapping):
        raise RawToLabelBundleError("reference HDF5 request binding is missing")
    report_reference = report.get("reference_typed_hdf5")
    if (not isinstance(report_reference, Mapping) or
            report_reference.get("path") != reference.get("path") or
            report_reference.get("sha256") != reference.get("sha256")):
        raise RawToLabelBundleError("v4 report reference HDF5 binding differs from the request")
    current_sources = [item for item in request.get("source_closure", {}).get("raw_v2_source_roles", [])
                       if isinstance(item, Mapping) and item.get("role") == "v2:current_catalog"]
    if (len(current_sources) != 1 or
            current.get("catalog_sha256") != current_sources[0].get("sha256")):
        raise RawToLabelBundleError("v4 report CURRENT catalog binding differs from the request")
    source_records = _source_records(request)
    # Raw frames are part of source_bindings even though the v4 request keeps
    # their individual content hashes pending until the parent worker report.
    source_records.extend(raw_frames)
    reference_record = {
        "role": "reference_typed_hdf5",
        "original_path": str(Path(str(reference["path"])).expanduser().resolve()),
        "bundle_relative_path": "reference/trajectory.h5",
        "bytes": int(reference["bytes"]),
        "original_mtime_ns": int(reference["mtime_ns"]),
        "content_sha256": _require_sha(reference["sha256"], "reference HDF5 SHA"),
        "content_hash_status": "PARENT_GUARD_BOUND_NO_REREAD",
        "replay_actionable": True,
        "h5_suffix_required": True,
    }
    # v4 source_closure already carries this HDF5 role.  Enrich that one
    # binding instead of adding a duplicate role that would make a path map
    # ambiguous.
    existing_reference = next((item for item in source_records
                               if item.get("role") in {"reference_typed_hdf5", "v2:reference_typed_hdf5"}
                               and item.get("content_sha256") == reference_record["content_sha256"]), None)
    if existing_reference is None:
        source_records.append(reference_record)
    else:
        existing_reference.update(reference_record)
    # Ensure every source role has a deterministic overlay path.  Existing
    # source records from the request get a role-specific namespace so a pair
    # of same-basename receipts cannot collide in a relocated bundle.
    for item in source_records:
        if "bundle_relative_path" not in item:
            role = str(item["role"]).replace(":", "_")
            item["bundle_relative_path"] = f"sources/{role}/{Path(item['original_path']).name}"
    anchor = _anchor_bindings(anchor_file, current_case_index=78, family_id="F2")
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "bundle_version": 1,
        "status": "PORTABLE_RAW_TO_LABEL_OVERLAY_REQUIRED",
        "bundle_kind": "RAW_TO_TYPED_TO_LABEL_REPLAY_BUNDLE",
        "typed_only": False,
        "role": "DEVELOPMENT",
        "qualification": UNKNOWN_QUALIFICATION,
        "case_scope": "SINGLE_EXACT_F2_S1_CURRENT_ROW_ONLY",
        "request_binding": {
            "path_provenance": str(request_file),
            "file_sha256": sha256_file(request_file),
            "canonical_sha256": context["request_sha"],
            "schema": request.get("schema"),
        },
        "report_binding": {
            "path_provenance": str(report_file),
            "file_sha256": sha256_file(report_file),
            "schema": report.get("schema"),
            "status": report.get("status"),
        },
        "current_binding": {
            "catalog_path_provenance": current.get("catalog_path"),
            "catalog_sha256": current.get("catalog_sha256"),
            "case_index": current.get("case_index"),
            "family_id": current.get("family_id"),
            "physical_case_id": current.get("physical_case_id"),
            "runtime_case_alias": current.get("runtime_case_alias"),
            "frames": current.get("frames"),
            "particles": current.get("particles"),
            "identity_key": "(Zone,Idp)",
        },
        "raw_producer_binding": {
            "data_root_path_provenance": raw_binding.get("data_root"),
            "frame_pattern": "Part_%04d.bi4",
            "frame_count": raw_binding.get("frame_count"),
            "expected_file_count": raw_binding.get("expected_file_count"),
            "raw_source_bytes": raw_binding.get("raw_source_bytes"),
            "expected_raw_tree_sha256": _require_sha(raw_binding.get("expected_raw_tree_sha256"), "raw tree SHA"),
            "observed_before_tree_sha256": evidence.get("before_tree_sha256"),
            "observed_after_tree_sha256": evidence.get("after_tree_sha256"),
            "per_frame_sha256_status": "VERIFIED_BY_PARENT_WORKER_REPORT",
            "frame_bindings": raw_frames,
            "partout_runparts_substitute": False,
            "reconstruction_input": "all native Part_*.bi4 frames; no HDF5 copy is a reconstruction input",
        },
        "derived_artifacts": {
            "typed_reconstruction": typed_artifact,
            "labels": label_artifacts,
        },
        "source_bindings": source_records,
        "import_closure": request["root_canonical_wrapper"].get("import_closure"),
        "shared_four_guard_sources": request["root_canonical_wrapper"].get("shared_four_guard_sources"),
        "seven_family_anchor_index": anchor,
        "replay_contract": {
            "consumer": "ds_data02_stage2_f2_native_raw_to_typed_compare_v4.py",
            "argv": ["run", "--request", "<relocated-v4-request>", "--output-dir", "<new-attempt-dir>", "--io-slot-approved"],
            "requires_parent_stage2guard": True,
            "raw_input_roles": ["raw_frame_%04d.bi4" % index for index in range(len(raw_frames))],
            "reference_hdf5_role": "reference_typed_hdf5",
            "labels": ["v15", "v16"],
            "original_path_fallback": "FORBIDDEN",
            "target_mtime_policy": "record relocated stat separately; never fake producer mtime",
            "content_policy": "full raw-frame SHA and reference-HDF5 SHA must be verified by parent before replay",
            "no_model": True,
            "no_cfd": True,
            "no_solver": True,
        },
        "limitations": [
            "bundle is source-bound DEVELOPMENT evidence; QI/QN/QE remain UNKNOWN",
            "raw/HDF5 external overlay is required; this command intentionally does not copy or open those datasets",
            "typed HDF5 is retained as a parent-bound comparison artifact and is not a substitute for raw reconstruction",
            "all original absolute paths are provenance only; replay must use a complete role path map",
        ],
    }
    manifest["sha256"] = canonical_sha(manifest)
    return manifest


def prepare_bundle(request_path: Path | str, report_path: Path | str,
                   anchor_index_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise RawToLabelBundleError(f"refusing to overwrite existing bundle root: {target}")
    manifest = build_bundle_manifest(request_path, report_path, anchor_index_path)
    target.mkdir(parents=True, exist_ok=False)
    _write_new(target / "bundle-manifest.json", manifest)
    _write_new(target / "path-map-template.json", _path_map_template(manifest))
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise RawToLabelBundleError("raw-to-label bundle schema is required")
    if manifest.get("typed_only") is not False or manifest.get("bundle_kind") != "RAW_TO_TYPED_TO_LABEL_REPLAY_BUNDLE":
        raise RawToLabelBundleError("typed-only artifact cannot satisfy raw-to-label bundle")
    _require_sha(manifest.get("sha256"), "bundle.sha256")
    if canonical_sha(manifest) != manifest["sha256"]:
        raise RawToLabelBundleError("bundle canonical SHA differs")
    raw = manifest.get("raw_producer_binding")
    if not isinstance(raw, Mapping) or int(raw.get("frame_count", 0)) != len(raw.get("frame_bindings", [])):
        raise RawToLabelBundleError("bundle raw frame binding is incomplete")
    labels = manifest.get("derived_artifacts", {}).get("labels") if isinstance(manifest.get("derived_artifacts"), Mapping) else None
    if not isinstance(labels, list) or not labels:
        raise RawToLabelBundleError("bundle must include label artifacts")
    if not isinstance(manifest.get("seven_family_anchor_index"), Mapping):
        raise RawToLabelBundleError("seven-family anchor connection is required")
    if manifest.get("replay_contract", {}).get("original_path_fallback") != "FORBIDDEN":
        raise RawToLabelBundleError("original path fallback must be forbidden")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    prep = parser.add_subparsers(dest="command", required=True).add_parser("prepare")
    prep.add_argument("--request", type=Path, required=True)
    prep.add_argument("--report", type=Path, required=True)
    prep.add_argument("--anchor-index", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = prepare_bundle(args.request, args.report, args.anchor_index, args.output_dir)
    except (OSError, RawToLabelBundleError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": manifest["schema"], "status": manifest["status"],
                      "sha256": manifest["sha256"], "qualification": manifest["qualification"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
