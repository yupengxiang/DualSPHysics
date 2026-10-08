#!/usr/bin/env python3
"""Forward V37 raw-tree scope repair for the F2 portable executor.

The consumed V36 request put ``Part_*.bi4`` at the target root while the
relocation bundle also put metadata and runtime files below ``sources/``.
The native converter hashes every regular file below ``raw_binding.data_root``
and therefore saw the whole bundle (456 files), rather than the producer's
405-file solver data directory.  V37 keeps the producer manifest unchanged,
puts all 405 raw files below a dedicated ``raw/`` directory, and leaves the
small source/runtime closure beside it.

This module is metadata-only.  It reads JSON and file stat records while
building a request; it never hashes or opens BI4/HDF5 payloads.  A runnable
request requires a parent-guard supplied SHA-256 for each of the four raw
auxiliary files.  The old V36 request, overlay, and receipts remain
immutable.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
OVERLAY_SCHEMA = "ds02.stage2.f2-native-raw-portable-overlay.v5"
FORWARD_SCHEMA = "ds02.stage2.f2-portable-executor-v37-forward.v1"
AUX_SCHEMA = "ds02.stage2.f2-raw-auxiliary-binding.v1"
DIAGNOSTIC_SCHEMA = "ds02.stage2.f2-raw-tree-scope-diagnostic.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
RAW_FRAME_ROLE = "raw_frame_input"
NATIVE_PARTOUT_ROLE = "v2:native_partout"
RAW_AUX_NAMES = ("PartInfo.ibi4", "PartMotionRef.ibi4", "PartOut_000.obi4", "Part_Head.ibi4")
RAW_AUX_ROLES = {
    "PartInfo.ibi4": "raw_aux_partinfo",
    "PartMotionRef.ibi4": "raw_aux_partmotionref",
    "PartOut_000.obi4": NATIVE_PARTOUT_ROLE,
    "Part_Head.ibi4": "raw_aux_part_head",
}
RAW_FRAME_NAME = re.compile(r"^Part_\d{4}\.bi4$")


class PortableV37Error(RuntimeError):
    """Raised when a V37 source/scope contract is unsafe or incomplete."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Hash JSON/small metadata only; callers must not use this on raw payloads."""
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableV37Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise PortableV37Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise PortableV37Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise PortableV37Error(f"{name} must be a lowercase SHA-256")
    return value


def _safe_relative(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableV37Error(f"{name} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableV37Error(f"{name} is unsafe: {value!r}")
    return str(path)


def _path(path_value: Any, name: str) -> Path:
    if isinstance(path_value, Path):
        path_value = str(path_value)
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise PortableV37Error(f"{name} must be an absolute path")
    return Path(path_value).expanduser().resolve()


def _stat_record(path: Path, name: str) -> dict[str, int]:
    try:
        info = path.stat()
    except OSError as error:
        raise PortableV37Error(f"{name} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise PortableV37Error(f"{name} is not a regular file: {path}")
    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink),
        "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid),
        "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns),
        "st_ctime_ns": int(info.st_ctime_ns),
    }


def _mode_contract(path: Path, role: str) -> dict[str, Any]:
    record = _stat_record(path, role)
    return {
        "source_stat_expected": record,
        "source_mode_bits": record["mode_bits"],
        "preserve_mode": True,
        "required_executable": bool(record["mode_bits"] & 0o111),
    }


def _load_v36(request_path: Path | str, overlay_path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    request = load_json(request_path)
    overlay = load_json(overlay_path)
    if request.get("schema") != V34_SCHEMA:
        raise PortableV37Error(f"V36 request schema differs: {request.get('schema')!r}")
    if request.get("sha256") != canonical_sha(request):
        raise PortableV37Error("V36 request canonical SHA differs")
    if overlay.get("schema") != OVERLAY_SCHEMA:
        raise PortableV37Error("V36 overlay schema differs")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise PortableV37Error("V36 overlay canonical SHA differs")
    if overlay.get("bundle", {}).get("canonical_sha256") != request.get("v5_bundle", {}).get("canonical_sha256"):
        raise PortableV37Error("V36 overlay and bundle binding differs")
    if not isinstance(request.get("forward_v36"), Mapping):
        raise PortableV37Error("V36 forward marker is missing")
    entries = request.get("source_entries")
    overlay_entries = overlay.get("entries")
    if not isinstance(entries, list) or not isinstance(overlay_entries, list):
        raise PortableV37Error("V36 source/overlay entries are required")
    if len(entries) != len(overlay_entries):
        raise PortableV37Error("V36 source and overlay entry counts differ")
    return request, overlay


def _bundle_raw_binding(request: Mapping[str, Any]) -> dict[str, Any]:
    binding = request.get("v5_bundle")
    if not isinstance(binding, Mapping):
        raise PortableV37Error("v5_bundle binding is missing")
    bundle_path = _path(binding.get("path"), "v5_bundle.path")
    bundle = load_json(bundle_path)
    if bundle.get("sha256") != canonical_sha(bundle):
        raise PortableV37Error("bound V5 bundle canonical SHA differs")
    if binding.get("canonical_sha256") != bundle.get("sha256"):
        raise PortableV37Error("request V5 bundle canonical SHA differs")
    raw = bundle.get("raw_producer_binding")
    if not isinstance(raw, Mapping):
        raise PortableV37Error("V5 raw_producer_binding is missing")
    count = int(raw.get("expected_file_count", -1))
    tree_sha = _require_sha(raw.get("expected_raw_tree_sha256"), "raw_producer_binding.expected_raw_tree_sha256")
    frame_count = int(raw.get("frame_count", -1))
    if frame_count <= 0 or count != frame_count + len(RAW_AUX_NAMES):
        raise PortableV37Error(
            f"producer raw file count {count} is not frame_count+{len(RAW_AUX_NAMES)}")
    return {"expected_file_count": count, "expected_raw_tree_sha256": tree_sha,
            "frame_count": frame_count,
            "frame_pattern": raw.get("frame_pattern"),
            "original_data_root": raw.get("original_data_root"),
            "bundle_path": str(bundle_path), "bundle_sha256": bundle.get("sha256")}


def _load_auxiliary_manifest(path: Path | str, *, producer: Mapping[str, Any],
                             source_root: Path) -> list[dict[str, Any]]:
    manifest = load_json(path)
    if manifest.get("schema") != AUX_SCHEMA:
        raise PortableV37Error(f"auxiliary manifest schema differs: {manifest.get('schema')!r}")
    if manifest.get("content_read_during_build") is not False:
        raise PortableV37Error("auxiliary manifest must state content_read_during_build=false")
    if manifest.get("source_data_root") != str(source_root):
        raise PortableV37Error("auxiliary manifest source_data_root differs from raw frame root")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise PortableV37Error("auxiliary manifest entries are required")
    by_name: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise PortableV37Error(f"auxiliary entry {index} is malformed")
        name = raw.get("filename")
        if name not in RAW_AUX_NAMES or name in by_name:
            raise PortableV37Error(f"auxiliary filename is missing/duplicated: {name!r}")
        source = _path(raw.get("path"), f"auxiliary[{name}].path")
        if source.parent != source_root or source.name != name:
            raise PortableV37Error(f"auxiliary path is outside the producer raw root: {source}")
        stat_record = _stat_record(source, f"auxiliary[{name}]")
        bytes_value = int(raw.get("bytes", -1))
        if bytes_value != stat_record["st_size"]:
            raise PortableV37Error(f"auxiliary byte stat differs: {name}")
        digest = _require_sha(raw.get("sha256"), f"auxiliary[{name}].sha256")
        by_name[name] = {
            "filename": name, "path": str(source), "bytes": bytes_value,
            "sha256": digest, "stat": stat_record,
            "content_hash_status": "PARENT_GUARD_CONTENT_SHA_BOUND",
        }
    missing = [name for name in RAW_AUX_NAMES if name not in by_name]
    if missing:
        raise PortableV37Error(f"auxiliary manifest lacks producer files: {missing}")
    expected = manifest.get("expected_raw_tree")
    if not isinstance(expected, Mapping):
        raise PortableV37Error("auxiliary manifest expected_raw_tree is missing")
    if int(expected.get("file_count", -1)) != int(producer["expected_file_count"]):
        raise PortableV37Error("auxiliary manifest file count differs from frozen producer binding")
    if _require_sha(expected.get("tree_sha256"), "auxiliary.expected_raw_tree.tree_sha256") != producer["expected_raw_tree_sha256"]:
        raise PortableV37Error("auxiliary manifest tree SHA differs from frozen producer binding")
    return [by_name[name] for name in RAW_AUX_NAMES]


def _raw_source_entries(request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    values = request.get("source_entries")
    if not isinstance(values, list):
        raise PortableV37Error("V36 source_entries are missing")
    frames = [dict(item) for item in values if isinstance(item, Mapping) and item.get("role") == RAW_FRAME_ROLE]
    if not frames:
        raise PortableV37Error("V36 raw frame entries are missing")
    frames.sort(key=lambda item: Path(str(item.get("path", ""))).name)
    for index, item in enumerate(frames):
        source = _path(item.get("path"), f"raw frame {index}.path")
        if source.name != f"Part_{index:04d}.bi4":
            raise PortableV37Error(f"raw frame {index} is not Part_{index:04d}.bi4")
        if item.get("target_relative_path") not in {f"Part_{index:04d}.bi4", f"sources/{index:04d}-Part_{index:04d}.bi4"}:
            raise PortableV37Error(f"unexpected V36 raw frame target path: {item.get('target_relative_path')!r}")
    by_role = {str(item.get("role")): dict(item) for item in values if isinstance(item, Mapping)}
    if NATIVE_PARTOUT_ROLE not in by_role:
        raise PortableV37Error("V36 native PartOut binding is missing")
    return frames, by_role


def _raw_overlay_entries(overlay: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = overlay.get("entries")
    if not isinstance(values, list):
        raise PortableV37Error("V36 overlay entries are missing")
    by_path: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PortableV37Error("V36 overlay entry is malformed")
        original = _path(raw.get("original_path"), "overlay.original_path")
        by_path[str(original)] = dict(raw)
    if len(by_path) != len(values):
        raise PortableV37Error("V36 overlay has duplicate original paths")
    return by_path


def _new_aux_source(aux: Mapping[str, Any], role: str) -> dict[str, Any]:
    source = Path(str(aux["path"]))
    value: dict[str, Any] = {
        "role": role, "path": str(source), "target_relative_path": f"raw/{aux['filename']}",
        "bytes": int(aux["bytes"]), "mtime_ns": int(aux["stat"]["st_mtime_ns"]),
        "sha256": str(aux["sha256"]),
        "content_hash_status": "PARENT_GUARD_CONTENT_SHA_BOUND",
    }
    value.update(_mode_contract(source, role))
    return value


def _new_aux_overlay(aux: Mapping[str, Any], role: str) -> dict[str, Any]:
    source = Path(str(aux["path"]))
    value: dict[str, Any] = {
        "role": role, "bundle_relative_path": f"raw/{aux['filename']}",
        "original_path": str(source), "expected_sha256": str(aux["sha256"]),
        "expected_bytes": int(aux["bytes"]),
        "original_mtime_ns": int(aux["stat"]["st_mtime_ns"]),
        "content_hash_status": "PENDING_PARENT_COPY",
        "source_content_hash_status": "PARENT_GUARD_CONTENT_SHA_BOUND",
        "target_inode_must_differ": True, "preserve_mode": True,
    }
    value.update(_mode_contract(source, role))
    value["target_mode_bits"] = value["source_mode_bits"]
    value["required_executable"] = False
    return value


def build_forward(*, v36_request: Path | str, v36_overlay: Path | str,
                  auxiliary_manifest: Path | str, output_request: Path | str,
                  output_overlay: Path | str, target_root: Path | str,
                  output_root: Path | str) -> dict[str, Any]:
    """Build a V37 request/overlay from V36 metadata and a parent SHA sidecar."""
    request, overlay = _load_v36(v36_request, v36_overlay)
    producer = _bundle_raw_binding(request)
    frames, by_role = _raw_source_entries(request)
    if len(frames) != int(producer["frame_count"]):
        raise PortableV37Error("V36 frame count differs from frozen producer binding")
    overlay_by_path = _raw_overlay_entries(overlay)
    source_root = _path(frames[0]["path"], "raw frame 0.path").parent
    aux = _load_auxiliary_manifest(auxiliary_manifest, producer=producer, source_root=source_root)
    target = _path(target_root, "target_root")
    output = _path(output_root, "output_root")
    if target == output or target == source_root or output == source_root:
        raise PortableV37Error("fresh target/output roots must be distinct from source root")
    if target == Path(str(request.get("fresh_roots", {}).get("target_root", ""))).expanduser().resolve():
        raise PortableV37Error("V37 target root must be a fresh path, not the consumed V36 target")
    if output == Path(str(request.get("fresh_roots", {}).get("output_root", ""))).expanduser().resolve():
        raise PortableV37Error("V37 output root must be a fresh path, not the consumed V36 output")

    new_request = copy.deepcopy(request)
    new_overlay = copy.deepcopy(overlay)
    source_entries = [dict(item) for item in new_request["source_entries"]]
    overlay_entries = [dict(item) for item in new_overlay["entries"]]
    source_by_path = {str(_path(item["path"], f"source {item.get('role')}.path")): item for item in source_entries}
    overlay_by_original = {str(_path(item["original_path"], "overlay.original_path")): item for item in overlay_entries}

    # Isolate exactly the native raw directory.  The four producer auxiliary
    # files are part of this directory even though only PartOut was previously
    # represented by a bundle role.
    for item in source_entries:
        if item.get("role") == RAW_FRAME_ROLE:
            frame_name = Path(str(item.get("path", ""))).name
            if not frame_name.startswith("Part_") or not frame_name.endswith(".bi4"):
                raise PortableV37Error(f"raw frame source name is malformed: {frame_name!r}")
            item["target_relative_path"] = f"raw/{frame_name}"
        elif item.get("role") == NATIVE_PARTOUT_ROLE:
            item["target_relative_path"] = "raw/PartOut_000.obi4"
    for item in overlay_entries:
        role = item.get("role")
        if role == RAW_FRAME_ROLE:
            source = Path(str(item["original_path"]))
            item["bundle_relative_path"] = f"raw/{source.name}"
        elif role == NATIVE_PARTOUT_ROLE:
            source = Path(str(item["original_path"]))
            if source.name != "PartOut_000.obi4":
                raise PortableV37Error("native PartOut binding has an unexpected filename")
            item["bundle_relative_path"] = "raw/PartOut_000.obi4"
        item.pop("target_path", None)
        item.pop("target_bytes", None)
        item.pop("target_mtime_ns", None)
        item.pop("target_sha256", None)
        if role in {RAW_FRAME_ROLE, NATIVE_PARTOUT_ROLE}:
            item["content_hash_status"] = "PENDING_PARENT_COPY"

    # The existing PartOut binding is reused, so the manifest must agree with
    # its frozen SHA.  Only the other three names add source/overlay roles.
    existing_partout = source_by_path.get(str(aux[2]["path"]))
    if existing_partout is None or existing_partout.get("role") != NATIVE_PARTOUT_ROLE:
        raise PortableV37Error("V36 native PartOut source binding does not match auxiliary manifest")
    if str(existing_partout.get("sha256")) != aux[2]["sha256"] or int(existing_partout.get("bytes", -1)) != aux[2]["bytes"]:
        raise PortableV37Error("auxiliary PartOut SHA/bytes differ from frozen V36 binding")

    for item in aux:
        name, role = item["filename"], RAW_AUX_ROLES[item["filename"]]
        if name == "PartOut_000.obi4":
            continue
        if str(Path(item["path"])) in source_by_path:
            raise PortableV37Error(f"auxiliary source is already bound: {name}")
        source_entries.append(_new_aux_source(item, role))
        overlay_entries.append(_new_aux_overlay(item, role))

    raw_original_root = str(source_root)
    forbidden = {str(_path(item["original_path"], "overlay.original_path")) for item in overlay_entries}
    forbidden.add(raw_original_root)
    new_overlay["entries"] = overlay_entries
    new_overlay["target_root"] = str(target)
    new_overlay["forbidden_original_prefixes"] = sorted(forbidden)
    new_overlay["forward_v37"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "raw_data_root_relative": "raw",
        "raw_data_root_scope": "only 401 Part frames plus PartInfo, PartMotionRef, PartOut_000, Part_Head",
        "expected_file_count": int(producer["expected_file_count"]),
        "expected_raw_tree_sha256": producer["expected_raw_tree_sha256"],
        "auxiliary_roles": [RAW_AUX_ROLES[name] for name in RAW_AUX_NAMES],
        "content_read_during_build": False,
        "source_stat_read_during_build": True,
        "payload_hashes_computed_during_build": False,
        "sources_directory_is_outside_raw_manifest": True,
        "original_path_fallback": "FORBIDDEN",
        "scientific_scope": "raw-tree path/closure repair only; all qualification UNKNOWN",
    }
    new_overlay["status"] = "READY_FOR_PARENT_COPY; V37_ISOLATED_RAW_SCOPE_AND_AUXILIARIES"
    new_overlay["content_hash_verified"] = False
    new_overlay["sha256"] = canonical_sha(new_overlay)
    overlay_path = write_new(output_overlay, new_overlay)

    new_request["source_entries"] = source_entries
    new_request["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    new_request["v5_overlay_template"] = {
        "canonical_sha256": new_overlay["sha256"],
        "path": str(overlay_path), "sha256": sha256_file(overlay_path),
    }
    new_request["raw_opened"] = False
    new_request["hdf5_opened"] = False
    new_request["forward_v37"] = {
        "schema": FORWARD_SCHEMA,
        "compatibility_envelope": V34_SCHEMA,
        "previous_forward_schema": request.get("forward_v36", {}).get("schema"),
        "overlay_sha256": new_overlay["sha256"],
        "raw_data_root_relative": "raw",
        "expected_file_count": int(producer["expected_file_count"]),
        "expected_raw_tree_sha256": producer["expected_raw_tree_sha256"],
        "frame_count": len(frames),
        "auxiliary_files": [
            {"filename": item["filename"], "role": RAW_AUX_ROLES[item["filename"]],
             "bytes": item["bytes"], "sha256": item["sha256"],
             "content_hash_status": item["content_hash_status"]}
            for item in aux
        ],
        "content_read_during_build": False,
        "payload_hashes_computed_during_build": False,
        "sources_directory_excluded_from_raw_manifest": True,
        "original_path_fallback": "FORBIDDEN",
        "qualification": dict(UNKNOWN),
    }
    new_request["status"] = "READY_FOR_PARENT_STAGE2_GUARD"
    new_request["limitations"] = list(new_request.get("limitations", [])) + [
        "V37 isolates the converter data_root to raw/; the sibling sources/ closure is not part of raw_tree_manifest.",
        "Auxiliary BI4 SHA values are parent-guard attestations; this builder reads no BI4/HDF5 payload.",
        "The frozen expected raw tree SHA and 405-file scope are unchanged.",
    ]
    new_request["sha256"] = canonical_sha(new_request)
    request_path = write_new(output_request, new_request)
    return {
        "status": "READY_FOR_PARENT_V37_METADATA_GUARD",
        "request": str(request_path), "request_sha256": sha256_file(request_path),
        "overlay": str(overlay_path), "overlay_sha256": sha256_file(overlay_path),
        "source_entry_count": len(source_entries), "raw_file_count": int(producer["expected_file_count"]),
        "raw_data_root_relative": "raw", "content_read": False,
        "payload_hashes_computed": False, "qualification": dict(UNKNOWN),
    }


def _stat_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise PortableV37Error(f"manifest root is missing: {root}")
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        info = path.stat()
        records.append({"relative_path": path.relative_to(root).as_posix(), "bytes": int(info.st_size)})
    return records


def diagnose_raw_tree_scope(*, frozen_report: Path | str, copied_report: Path | str,
                            frozen_data_root: Path | str, copied_data_root: Path | str,
                            output: Path | str) -> dict[str, Any]:
    """Join frozen/copied JSON reports with stat-only file lists.

    The output explains scope contamination and missing auxiliary files without
    reading any raw payload or computing a payload SHA.
    """
    frozen = load_json(frozen_report)
    copied = load_json(copied_report)
    frozen_raw = frozen.get("source_provenance", {}).get("raw_tree", {})
    copied_raw = copied.get("source_provenance", {}).get("raw_tree", {})
    if not isinstance(frozen_raw, Mapping) or not isinstance(copied_raw, Mapping):
        raise PortableV37Error("reports lack source_provenance.raw_tree")
    frozen_root = _path(frozen_data_root, "frozen_data_root")
    copied_root = _path(copied_data_root, "copied_data_root")
    source_files = _stat_manifest(frozen_root)
    copied_files = _stat_manifest(copied_root)
    source_names = {item["relative_path"] for item in source_files}
    copied_names = {item["relative_path"] for item in copied_files}
    aux = [item for item in source_files
           if not RAW_FRAME_NAME.fullmatch(item["relative_path"])]
    target_extra = sorted(copied_names - source_names)
    missing = sorted(source_names - copied_names)
    target_nested = [item for item in copied_files if "/" in item["relative_path"]]
    result: dict[str, Any] = {
        "schema": DIAGNOSTIC_SCHEMA,
        "status": "RAW_SCOPE_MISMATCH_AUXILIARY_CLOSURE_PENDING",
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "frozen_report": {"path": str(Path(frozen_report).expanduser().resolve()), "sha256": sha256_file(frozen_report)},
        "copied_report": {"path": str(Path(copied_report).expanduser().resolve()), "sha256": sha256_file(copied_report)},
        "frozen_report_raw_tree": {
            "file_count": int(frozen_raw.get("after_file_count", -1)),
            "tree_sha256": frozen_raw.get("after_tree_sha256"),
        },
        "copied_report_raw_tree": {
            "file_count": int(copied_raw.get("after_file_count", -1)),
            "tree_sha256": copied_raw.get("after_tree_sha256"),
        },
        "stat_only_scope": {
            "payload_read": False, "payload_sha256_computed": False,
            "frozen_data_root": str(frozen_root), "copied_data_root": str(copied_root),
            "frozen_file_count": len(source_files), "copied_file_count": len(copied_files),
            "copied_top_level_part_count": sum(
                1 for item in copied_files if "/" not in item["relative_path"]
                and item["relative_path"].startswith("Part_")
            ),
            "copied_nested_file_count": len(target_nested),
        },
        "frozen_raw_file_list": source_files,
        "copied_file_list": copied_files,
        "missing_from_copied_scope": missing,
        "unexpected_in_copied_scope": target_extra,
        "producer_auxiliary_files": aux,
        "required_repair": {
            "raw_data_root_relative": "raw",
            "raw_manifest_scope": "raw/ only",
            "expected_file_count": int(frozen_raw.get("after_file_count", -1)),
            "expected_tree_sha256_unchanged": frozen_raw.get("after_tree_sha256"),
            "auxiliary_files_to_bind": [item["relative_path"] for item in aux],
            "sources_sibling_excluded": True,
        },
    }
    result["sha256"] = canonical_sha(result)
    write_new(output, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward")
    build.add_argument("--v36-request", type=Path, required=True)
    build.add_argument("--v36-overlay", type=Path, required=True)
    build.add_argument("--auxiliary-manifest", type=Path, required=True)
    build.add_argument("--output-request", type=Path, required=True)
    build.add_argument("--output-overlay", type=Path, required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    diagnose = sub.add_parser("diagnose-scope")
    diagnose.add_argument("--frozen-report", type=Path, required=True)
    diagnose.add_argument("--copied-report", type=Path, required=True)
    diagnose.add_argument("--frozen-data-root", type=Path, required=True)
    diagnose.add_argument("--copied-data-root", type=Path, required=True)
    diagnose.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward":
            value = build_forward(v36_request=args.v36_request, v36_overlay=args.v36_overlay,
                                  auxiliary_manifest=args.auxiliary_manifest,
                                  output_request=args.output_request, output_overlay=args.output_overlay,
                                  target_root=args.target_root, output_root=args.output_root)
        else:
            value = diagnose_raw_tree_scope(
                frozen_report=args.frozen_report, copied_report=args.copied_report,
                frozen_data_root=args.frozen_data_root, copied_data_root=args.copied_data_root,
                output=args.output)
    except (PortableV37Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 portable executor v37: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
