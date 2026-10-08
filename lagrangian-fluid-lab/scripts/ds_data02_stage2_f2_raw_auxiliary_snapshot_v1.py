#!/usr/bin/env python3
"""Parent-guarded snapshot of the F2 raw-tree auxiliary closure.

This narrow worker exists to finish the V37 source contract without running a
converter.  The build and preflight commands read JSON and ``stat`` records
only.  The run command is the only operation that opens the 401 BI4 frames
and four auxiliary files; it requires an explicit parent I/O approval flag
and records complete pre/post stats, per-file SHA-256 values, and the exact
converter manifest digest.  It never writes a ledger, opens HDF5, invokes a
model/CFD process, or changes the frozen expected tree SHA.

The successful output is directly consumable as the V37 auxiliary manifest:
its ``entries`` contain the four fresh auxiliary hashes, while
``frozen_frame_manifest`` and ``raw_manifest.files`` preserve the 401-frame
source closure used by the parent to review the join.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import resource
import re
import stat
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
REQUEST_SCHEMA = "ds02.stage2.f2-raw-auxiliary-snapshot-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-raw-auxiliary-snapshot.v1"
AUX_SCHEMA = "ds02.stage2.f2-raw-auxiliary-binding.v1"
V2_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2"
V5_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
HEX64 = set("0123456789abcdef")
FRAME_RE = re.compile(r"^Part_(\d{4})\.bi4$")
FRAME_COUNT = 401
AUX_NAMES = ("PartInfo.ibi4", "PartMotionRef.ibi4", "PartOut_000.obi4", "Part_Head.ibi4")


class AuxiliarySnapshotError(RuntimeError):
    """Raised when the source closure or parent execution boundary is unsafe."""


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_hash(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=_json_default).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuxiliarySnapshotError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise AuxiliarySnapshotError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise AuxiliarySnapshotError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")
    return target


def _path(value: Any, name: str) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise AuxiliarySnapshotError(f"{name} must be an absolute path")
    return Path(value).expanduser().resolve()


def _sha(value: Any, name: str, *, pending: bool = False) -> str:
    if pending and value == PENDING:
        return PENDING
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise AuxiliarySnapshotError(f"{name} must be a lowercase SHA-256")
    return value


def _stat(path: Path, name: str) -> dict[str, int]:
    try:
        info = path.stat()
    except OSError as error:
        raise AuxiliarySnapshotError(f"{name} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise AuxiliarySnapshotError(f"{name} is not a regular file: {path}")
    return {
        "st_dev": int(info.st_dev), "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode), "mode_bits": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink), "st_uid": int(info.st_uid),
        "st_gid": int(info.st_gid), "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns), "st_ctime_ns": int(info.st_ctime_ns),
    }


def _same_stat(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(int(left.get(key, -1)) == int(right.get(key, -1)) for key in (
        "st_dev", "st_ino", "st_mode", "mode_bits", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_mtime_ns", "st_ctime_ns"))


def _regular_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise AuxiliarySnapshotError(f"raw source root is missing: {root}")
    return sorted(path for path in root.rglob("*") if path.is_file())


def _resource_snapshot() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _bundle_frames(bundle: Mapping[str, Any], source_root: Path,
                   frame_by_number: Mapping[int, Mapping[str, Any]]) -> list[dict[str, Any]]:
    bindings = bundle.get("source_bindings")
    if not isinstance(bindings, list):
        raise AuxiliarySnapshotError("V5 bundle source_bindings are missing")
    values = [item for item in bindings if isinstance(item, Mapping)
              and item.get("role") == "raw_frame_input"]
    if len(values) != FRAME_COUNT:
        raise AuxiliarySnapshotError(f"V5 frozen frame manifest must contain {FRAME_COUNT} entries")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in values:
        path = _path(item.get("original_path"), "V5 raw frame original_path")
        match = FRAME_RE.fullmatch(path.name)
        if match is None or path.parent != source_root:
            raise AuxiliarySnapshotError(f"V5 frame path is not top-level producer data: {path}")
        number = int(match.group(1))
        if number in seen or number not in frame_by_number:
            raise AuxiliarySnapshotError(f"V5 frame does not match V2 frame set: {path.name}")
        expected_bytes = int(item.get("bytes", -1))
        if expected_bytes != int(frame_by_number[number]["bytes"]):
            raise AuxiliarySnapshotError(f"frozen/V2 frame byte stat differs: {path.name}")
        digest = _sha(item.get("content_sha256"), f"V5 {path.name}.content_sha256")
        result.append({
            "frame": number, "relative_path": path.name, "path": str(path),
            "bytes": expected_bytes, "sha256": digest,
            "source_role": "raw_frame_input", "content_hash_status": "FROZEN_PRODUCER_SHA",
        })
        seen.add(number)
    result.sort(key=lambda item: int(item["frame"]))
    if [int(item["frame"]) for item in result] != list(range(FRAME_COUNT)):
        raise AuxiliarySnapshotError("frozen frame manifest is not contiguous from zero")
    return result


def _raw_contract(request: Mapping[str, Any]) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    if request.get("schema") != V2_SCHEMA:
        raise AuxiliarySnapshotError(f"unsupported V2 request schema: {request.get('schema')!r}")
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise AuxiliarySnapshotError("V2 raw_binding is required")
    root = _path(raw.get("data_root"), "raw_binding.data_root")
    if int(raw.get("frame_count", -1)) != FRAME_COUNT or int(raw.get("expected_file_count", -1)) != FRAME_COUNT + len(AUX_NAMES):
        raise AuxiliarySnapshotError("V2 raw frame/file counts do not match the frozen F2 scope")
    expected_tree = _sha(raw.get("expected_raw_tree_sha256"), "raw_binding.expected_raw_tree_sha256")
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) != FRAME_COUNT:
        raise AuxiliarySnapshotError("V2 raw frame list must contain all 401 frames")
    frame_records: list[dict[str, Any]] = []
    for number, item in enumerate(frames):
        if not isinstance(item, Mapping) or int(item.get("frame", -1)) != number:
            raise AuxiliarySnapshotError(f"V2 frame {number} binding is malformed")
        path = _path(item.get("path"), f"V2 frame {number}.path")
        if path.parent != root or path.name != f"Part_{number:04d}.bi4":
            raise AuxiliarySnapshotError(f"V2 frame {number} is not the exact top-level Part path")
        record = _stat(path, f"V2 frame {number}")
        if int(item.get("bytes", -1)) != record["st_size"]:
            raise AuxiliarySnapshotError(f"V2 frame {number} byte stat differs")
        frame_records.append({
            "frame": number, "relative_path": path.name, "path": str(path),
            "bytes": int(record["st_size"]), "mtime_ns": int(record["st_mtime_ns"]),
            "sha256": PENDING, "content_hash_status": "PENDING_PARENT_GUARD_CONTENT_SHA256",
            "source_stat_at_build": record,
        })
    return root, frame_records, {
        "expected_file_count": FRAME_COUNT + len(AUX_NAMES),
        "expected_raw_tree_sha256": expected_tree,
        "frame_count": FRAME_COUNT, "frame_pattern": "Part_%04d.bi4",
    }


def _aux_contract(template: Mapping[str, Any], source_root: Path) -> list[dict[str, Any]]:
    if template.get("schema") != AUX_SCHEMA:
        raise AuxiliarySnapshotError("auxiliary template schema differs")
    entries = template.get("entries")
    if not isinstance(entries, list) or len(entries) != len(AUX_NAMES):
        raise AuxiliarySnapshotError("auxiliary template must list exactly four files")
    by_name: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise AuxiliarySnapshotError("auxiliary template entry is malformed")
        name = raw.get("filename")
        if name not in AUX_NAMES or name in by_name:
            raise AuxiliarySnapshotError(f"auxiliary template filename is missing/duplicated: {name!r}")
        path = _path(raw.get("path"), f"auxiliary {name}.path")
        if path.parent != source_root or path.name != name:
            raise AuxiliarySnapshotError(f"auxiliary path is outside the producer raw root: {path}")
        record = _stat(path, f"auxiliary {name}")
        if int(raw.get("bytes", -1)) != record["st_size"]:
            raise AuxiliarySnapshotError(f"auxiliary {name} byte stat differs")
        digest = _sha(raw.get("sha256"), f"auxiliary {name}.sha256", pending=True)
        by_name[name] = {
            "filename": name, "path": str(path), "bytes": int(record["st_size"]),
            "sha256": digest, "content_hash_status": "PENDING_PARENT_GUARD_CONTENT_SHA256",
            "source_stat_at_build": record,
        }
    missing = [name for name in AUX_NAMES if name not in by_name]
    if missing:
        raise AuxiliarySnapshotError(f"auxiliary template lacks files: {missing}")
    return [by_name[name] for name in AUX_NAMES]


def build_request(*, v2_request: Path | str, v5_bundle: Path | str,
                  auxiliary_template: Path | str, output: Path | str,
                  parent_resource_binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a metadata-only request joining frozen frames and pending aux files."""
    request_path = Path(v2_request).expanduser().resolve()
    v2 = load_json(request_path)
    source_root, frames, raw = _raw_contract(v2)
    bundle_path = Path(v5_bundle).expanduser().resolve()
    bundle = load_json(bundle_path)
    if bundle.get("schema") != V5_BUNDLE_SCHEMA or bundle.get("sha256") != canonical_hash(bundle):
        raise AuxiliarySnapshotError("V5 bundle is not canonical")
    bundle_raw = bundle.get("raw_producer_binding")
    if not isinstance(bundle_raw, Mapping):
        raise AuxiliarySnapshotError("V5 raw producer binding is missing")
    if _sha(bundle_raw.get("expected_raw_tree_sha256"), "V5 expected tree") != raw["expected_raw_tree_sha256"]:
        raise AuxiliarySnapshotError("V2/V5 expected raw tree SHA differs")
    if int(bundle_raw.get("expected_file_count", -1)) != raw["expected_file_count"]:
        raise AuxiliarySnapshotError("V2/V5 raw file count differs")
    frozen = _bundle_frames(bundle, source_root, {int(x["frame"]): x for x in frames})
    template = load_json(auxiliary_template)
    aux = _aux_contract(template, source_root)
    read_bytes = sum(int(item["bytes"]) for item in frames + aux)
    parent_binding = dict(parent_resource_binding or {})
    parent_binding.setdefault("same_parent_ledger", True)
    parent_binding.setdefault("reservation_required_before_hash", True)
    parent_binding.setdefault("ledger_mutation_by_worker", False)
    value: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-raw-auxiliary-snapshot-v1-001",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "case_scope": copy_case_scope(v2),
        "v2_request": {"path": str(request_path), "sha256": sha256_file(request_path),
                        "schema": v2.get("schema")},
        "v5_bundle": {"path": str(bundle_path), "sha256": sha256_file(bundle_path),
                       "canonical_sha256": bundle.get("sha256")},
        "source_data_root": str(source_root),
        "expected_raw_tree": raw,
        "frame_bindings": frozen,
        "auxiliary_bindings": aux,
        "parent_resource_binding": parent_binding,
        "execution": {
            "command_template": ["<literal-parent-python>", str(SCRIPT), "run",
                                  "--request", "<request>", "--output", "<new-report>",
                                  "--io-slot-approved", "--parent-pid", "<parent-pid>"],
            "requires_parent_stage2guard": True,
            "reservation_before_payload_hash": True,
            "payload_read": "401 BI4 frames + 4 auxiliary files only after approval",
            "hdf5_opened": False, "converter_invoked": False,
            "model_invoked": False, "cfd_invoked": False,
            "ledger_mutation_by_worker": False,
        },
        "resource_request": {
            "raw_source_read_bytes": read_bytes,
            "raw_tree_manifest_passes": 1,
            "estimated_source_read_bytes_upper_bound": read_bytes,
            "output_bytes_estimate": 4 * 1024 * 1024,
            "max_rss_observational_bytes": 256 * 1024 * 1024,
            "max_wall_seconds": int(v2.get("resource_request", {}).get("max_wall_seconds", 3600)),
            "max_cpu_core_hours": float(v2.get("resource_request", {}).get("max_cpu_core_hours", 2.0)),
            "rss_enforcement": "parent guard records worker ru_maxrss; no RLIMIT claim",
        },
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "Build/preflight are stat-only; the four auxiliary hashes remain pending until parent approval.",
            "Run output is a source closure/manifest receipt, not a native conversion or label result.",
            "The frozen 405-file tree SHA is immutable and must match after the joined hash pass.",
        ],
    }
    value["sha256"] = canonical_hash(value)
    write_new(output, value)
    return {"status": value["status"], "path": str(Path(output).expanduser().resolve()),
            "sha256": value["sha256"], "frame_count": len(frozen),
            "auxiliary_count": len(aux), "read_bytes": read_bytes,
            "content_read": False, "qualification": dict(UNKNOWN)}


def copy_case_scope(v2: Mapping[str, Any]) -> dict[str, Any]:
    case = v2.get("case_identity")
    cohort = v2.get("cohort")
    return {"case_identity": case, "cohort": cohort,
            "identity_source": "copied from frozen V2 request; not inferred by snapshot worker"}


def _load_request(path: Path | str) -> dict[str, Any]:
    request_path = Path(path).expanduser().resolve()
    value = load_json(request_path)
    if value.get("schema") != REQUEST_SCHEMA or value.get("sha256") != canonical_hash(value):
        raise AuxiliarySnapshotError("snapshot request schema/canonical SHA differs")
    if value.get("role") != "DEVELOPMENT" or value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise AuxiliarySnapshotError("snapshot request must remain model-free DEVELOPMENT")
    if value.get("qualification") != UNKNOWN:
        raise AuxiliarySnapshotError("snapshot request must keep QI/QN/QE UNKNOWN")
    raw = value.get("expected_raw_tree")
    if not isinstance(raw, Mapping) or int(raw.get("expected_file_count", -1)) != FRAME_COUNT + len(AUX_NAMES):
        raise AuxiliarySnapshotError("snapshot expected raw scope differs")
    _sha(raw.get("expected_raw_tree_sha256"), "request expected tree SHA")
    frames = value.get("frame_bindings")
    aux = value.get("auxiliary_bindings")
    if not isinstance(frames, list) or len(frames) != FRAME_COUNT:
        raise AuxiliarySnapshotError("snapshot request must bind all 401 frames")
    if not isinstance(aux, list) or len(aux) != len(AUX_NAMES):
        raise AuxiliarySnapshotError("snapshot request must bind four auxiliary files")
    return value


def _bindings(request: Mapping[str, Any]) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    root = _path(request.get("source_data_root"), "request.source_data_root")
    frames = [dict(item) for item in request["frame_bindings"]]
    aux = [dict(item) for item in request["auxiliary_bindings"]]
    paths: set[str] = set()
    for number, item in enumerate(frames):
        path = _path(item.get("path"), f"frame {number}.path")
        if path.parent != root or path.name != f"Part_{number:04d}.bi4":
            raise AuxiliarySnapshotError(f"frame {number} path is not top-level producer data")
        record = _stat(path, f"frame {number}")
        if int(item.get("bytes", -1)) != record["st_size"]:
            raise AuxiliarySnapshotError(f"frame {number} byte stat differs")
        item["path"] = str(path); item["bytes"] = int(record["st_size"])
        paths.add(path.name)
    names: set[str] = set()
    for item in aux:
        name = item.get("filename")
        if name not in AUX_NAMES or name in names:
            raise AuxiliarySnapshotError(f"auxiliary binding filename is missing/duplicated: {name!r}")
        path = _path(item.get("path"), f"auxiliary {name}.path")
        if path.parent != root or path.name != name:
            raise AuxiliarySnapshotError(f"auxiliary {name} path is outside source root")
        record = _stat(path, f"auxiliary {name}")
        if int(item.get("bytes", -1)) != record["st_size"]:
            raise AuxiliarySnapshotError(f"auxiliary {name} byte stat differs")
        item["path"] = str(path); item["bytes"] = int(record["st_size"])
        names.add(name); paths.add(name)
    expected = {f"Part_{number:04d}.bi4" for number in range(FRAME_COUNT)} | set(AUX_NAMES)
    if paths != expected:
        raise AuxiliarySnapshotError("bound file names do not equal the 405-file producer scope")
    return root, frames, aux


def _scope_files(root: Path) -> list[Path]:
    values = _regular_files(root)
    expected = {f"Part_{number:04d}.bi4" for number in range(FRAME_COUNT)} | set(AUX_NAMES)
    observed = {path.relative_to(root).as_posix() for path in values}
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise AuxiliarySnapshotError(f"producer file scope differs; missing={missing[:4]} extra={extra[:4]}")
    return values


def _manifest_entry(path: Path, root: Path, digest: str) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "bytes": int(path.stat().st_size), "sha256": digest}


def _failure_report(request_path: Path, request: Mapping[str, Any], error: str,
                    *, started: float, before: Mapping[str, float], output: Path,
                    parent_pid: int | None) -> dict[str, Any]:
    after = _resource_snapshot()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "status": "FAILED_PARENT_GUARDED_SNAPSHOT",
        "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
        "source_data_root": request.get("source_data_root"),
        "expected_raw_tree": request.get("expected_raw_tree"),
        "parent_guard": {"io_slot_approved": True, "parent_pid": parent_pid,
                          "reservation_required_before_hash": True},
        "execution_boundary": {"bi4_opened": True, "hdf5_opened": False,
                                "converter_invoked": False, "model_invoked": False,
                                "cfd_invoked": False, "ledger_mutation_by_worker": False},
        "error": error, "qualification": dict(UNKNOWN),
        "resource": {"wall_seconds": time.monotonic() - started,
                      "usage": {"before": dict(before), "after": after,
                                 "delta": _usage_delta(before, after)}},
    }
    report["sha256"] = canonical_hash(report)
    write_new(output, report)
    return report


def preflight(request_path: Path | str, output: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_request(request_file)
    root, frames, aux = _bindings(request)
    _scope_files(root)
    report = {
        "schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "source_data_root": str(root),
        "expected_raw_tree": request["expected_raw_tree"],
        "frame_count": len(frames), "auxiliary_count": len(aux),
        "stat_only": True, "payload_read": False, "payload_hashes_computed": False,
        "hdf5_opened": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }
    report["sha256"] = canonical_hash(report)
    write_new(output, report)
    return report


def run(request_path: Path | str, output: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_request(request_file)
    if not io_slot_approved:
        raise AuxiliarySnapshotError("run requires explicit --io-slot-approved after parent reservation")
    if parent_pid is not None and (parent_pid <= 1 or not Path(f"/proc/{parent_pid}").exists()):
        raise AuxiliarySnapshotError("parent guard process is not alive")
    root, frames, aux = _bindings(request)
    output_file = Path(output).expanduser().resolve()
    if output_file.exists():
        raise AuxiliarySnapshotError(f"refusing existing output: {output_file}")
    started = time.monotonic()
    before_usage = _resource_snapshot()
    try:
        # The approval check above is intentionally before this first payload
        # hash.  Stat/name checks are metadata safeguards; SHA opens payload.
        paths = _scope_files(root)
        pre_stats = {path.relative_to(root).as_posix(): _stat(path, "pre-hash") for path in paths}
        frozen_by_path = {item["relative_path"]: item for item in request["frame_bindings"]}
        records: list[dict[str, Any]] = []
        bytes_read = 0
        for path in paths:
            relative = path.relative_to(root).as_posix()
            digest = sha256_file(path)
            info = _stat(path, "post-hash")
            if not _same_stat(pre_stats[relative], info):
                raise AuxiliarySnapshotError(f"source stat changed during hash: {relative}")
            entry = {"path": relative, "bytes": int(info["st_size"]), "sha256": digest}
            records.append(entry)
            bytes_read += int(info["st_size"])
            frozen = frozen_by_path.get(relative)
            if frozen is not None and digest != frozen.get("sha256"):
                raise AuxiliarySnapshotError(f"frozen producer frame SHA differs: {relative}")
        # A second name/stat pass catches additions/deletions after the hash
        # loop without reading the bytes a second time.
        after_paths = _scope_files(root)
        post_stats = {path.relative_to(root).as_posix(): _stat(path, "post-pass") for path in after_paths}
        if set(post_stats) != set(pre_stats):
            raise AuxiliarySnapshotError("producer file names changed after hash")
        if any(not _same_stat(pre_stats[name], post_stats[name]) for name in pre_stats):
            raise AuxiliarySnapshotError("producer stat changed after hash")
        records.sort(key=lambda item: item["path"])
        tree_sha = canonical_hash(records)
        expected_tree = request["expected_raw_tree"]["expected_raw_tree_sha256"]
        if tree_sha != expected_tree:
            raise AuxiliarySnapshotError(
                f"joined raw tree SHA differs: expected {expected_tree}, observed {tree_sha}")
        aux_by_name = {item["filename"]: item for item in aux}
        actual_aux = []
        for entry in records:
            if entry["path"] in aux_by_name:
                actual_aux.append({
                    "filename": entry["path"], "path": str(root / entry["path"]),
                    "bytes": entry["bytes"], "sha256": entry["sha256"],
                    "content_hash_status": "PARENT_GUARDED_CONTENT_SHA256",
                })
        frozen_frames = []
        for entry in records:
            frozen = frozen_by_path.get(entry["path"])
            if frozen is not None:
                frozen_frames.append({
                    "frame": int(frozen["frame"]), "relative_path": entry["path"],
                    "path": str(root / entry["path"]), "bytes": entry["bytes"],
                    "sha256": entry["sha256"], "frozen_sha256": frozen["sha256"],
                    "content_hash_status": "FROZEN_AND_PARENT_GUARDED_SHA_MATCH",
                })
        after_usage = _resource_snapshot()
        report: dict[str, Any] = {
            # V37 consumes a successful snapshot as an auxiliary-binding
            # sidecar.  Keep the narrow worker report schema separately so
            # stat-only/failure reports remain distinguishable, while the
            # successful payload passes V37's strict AUX_SCHEMA gate.
            "schema": AUX_SCHEMA, "snapshot_schema": REPORT_SCHEMA,
            "status": "COMPLETE_PARENT_GUARDED",
            "role": "DEVELOPMENT", "qualification": dict(UNKNOWN),
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "source_data_root": str(root),
            "expected_raw_tree": {
                "file_count": int(request["expected_raw_tree"]["expected_file_count"]),
                "tree_sha256": tree_sha,
            },
            "request_expected_raw_tree": request["expected_raw_tree"],
            "raw_manifest": {"file_count": len(records), "tree_sha256": tree_sha, "files": records},
            "frozen_frame_manifest": frozen_frames,
            "entries": actual_aux,
            "content_read_during_build": False,
            "snapshot_content_read": True,
            "payload_hashes_computed": True,
            "stat_pre_post": {"files": pre_stats, "stable": True,
                               "post_hash_files": post_stats},
            "parent_guard": {"io_slot_approved": True, "parent_pid": parent_pid,
                              "reservation_required_before_hash": True,
                              "ledger_mutation_by_worker": False},
            "execution_boundary": {"bi4_opened": True, "hdf5_opened": False,
                                    "converter_invoked": False, "model_invoked": False,
                                    "cfd_invoked": False, "ledger_mutation_by_worker": False},
            "resource": {"wall_seconds": time.monotonic() - started,
                          "bytes_read": bytes_read,
                          "usage": {"before": before_usage, "after": after_usage,
                                     "delta": _usage_delta(before_usage, after_usage)}},
        }
        report["sha256"] = canonical_hash(report)
        write_new(output_file, report)
        return report
    except (AuxiliarySnapshotError, OSError, ValueError, TypeError) as error:
        return _failure_report(request_file, request, str(error), started=started,
                               before=before_usage, output=output_file, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v2-request", type=Path, required=True)
    build.add_argument("--v5-bundle", type=Path, required=True)
    build.add_argument("--auxiliary-template", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(v2_request=args.v2_request, v5_bundle=args.v5_bundle,
                                  auxiliary_template=args.auxiliary_template, output=args.output)
        elif args.command == "preflight":
            value = preflight(args.request, args.output)
        else:
            value = run(args.request, args.output, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (AuxiliarySnapshotError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 raw auxiliary snapshot: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=_json_default))
    return 0 if value.get("status") not in {"FAILED_PARENT_GUARDED_SNAPSHOT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
