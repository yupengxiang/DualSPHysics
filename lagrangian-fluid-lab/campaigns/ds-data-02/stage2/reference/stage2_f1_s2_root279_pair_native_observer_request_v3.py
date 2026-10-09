#!/usr/bin/env python3
"""Build the source-bound ROOT279 F1-S2 matched native observer request v3.

This additive version consumes the actual ``ds02.stage2.native-source-snapshot.v2``
wrapper emitted by ROOT310.  That wrapper stores records under
``requests[].selected_native_files`` and exposes ``stat_before``/``stat_after``;
it does not have a top-level ``records`` array.  The observer manifest schema
remains v2 because the guarded V4 consumer accepts that schema; only this
request builder variant is v3.

The builder consumes the completed ROOT277/278 receipts, proof records,
RunPARTs metadata, and the ROOT271 pair intake.  It hashes only those small
metadata files plus the copied XML and source/runtime files.  The ten native
Part files remain deferred.  A parent may pass a separate ten-record source
snapshot after reservation; without that snapshot this builder emits an
    explicit pending request and never pretends that a native SHA/stat is known.

    This additive version fixes v1's snapshot propagation and receipt identity
    joins.  It also freezes the manifest as an absolute source path because
    runtime v8 does not materialize ``{attempt_root}/inputs`` placeholders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
WORKER = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
V4_WRAPPER = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
V1_WORKER = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")
CONTRACT = HERE / "stage2_f1_s2_root279_pair_native_observer_contract_v1.json"
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3"
INTAKE_SCHEMA = "ds02.stage2.f1-s2.root271-pair-native-intake.v1"
MAX_SMALL_BYTES = 16 * 1024 * 1024
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
QUERY_TIMES = (0.0, 0.25, 0.5)
EXPECTED_DEFERRED_COUNT = 10
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
SNAPSHOT_STAT_FIELDS = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")


class BuildError(RuntimeError):
    pass


def _path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().absolute()
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BuildError(f"{label} is a deferred native payload: {path}")
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular file: {path}")
    return path


def _record_literal_venv_python(path: Path, label: str) -> dict[str, Any]:
    """Bind a literal venv argv0 while hashing only its resolved target.

    ``.venv/bin/python`` is intentionally a symlink.  The command must retain
    that literal path so the venv environment is selected, while the resolved
    interpreter and ``pyvenv.cfg`` provide the immutable executable/config
    evidence.  This is the same closure used by the guarded observer; the
    ordinary regular-file rule must not silently replace argv[0].
    """
    path = path.expanduser().absolute()
    if not path.is_symlink():
        raise BuildError(f"{label} must be the literal venv symlink: {path}")
    target = path.resolve(strict=True)
    if target == path or target.is_symlink() or not target.is_file():
        raise BuildError(f"{label} resolved target is not a regular file: {path} -> {target}")
    link_before = path.lstat()
    target_before = target.stat()
    if target_before.st_size > MAX_SMALL_BYTES:
        raise BuildError(f"{label} resolved target exceeds bounded metadata read: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    target_after = target.stat()
    link_after = path.lstat()
    if (link_before.st_dev, link_before.st_ino, link_before.st_size, link_before.st_mtime_ns, link_before.st_ctime_ns) != (link_after.st_dev, link_after.st_ino, link_after.st_size, link_after.st_mtime_ns, link_after.st_ctime_ns):
        raise BuildError(f"{label} symlink changed during bounded read: {path}")
    if (target_before.st_dev, target_before.st_ino, target_before.st_size, target_before.st_mtime_ns, target_before.st_ctime_ns) != (target_after.st_dev, target_after.st_ino, target_after.st_size, target_after.st_mtime_ns, target_after.st_ctime_ns):
        raise BuildError(f"{label} target changed during bounded read: {target}")
    return {
        "path": str(path), "label": label, "bytes": int(target_after.st_size),
        "sha256": digest.hexdigest(), "stat": {"dev": int(target_after.st_dev), "ino": int(target_after.st_ino), "bytes": int(target_after.st_size), "mtime_ns": int(target_after.st_mtime_ns), "ctime_ns": int(target_after.st_ctime_ns)},
        "literal_argv0": True, "resolved_target": str(target),
        "symlink_stat": {"dev": int(link_after.st_dev), "ino": int(link_after.st_ino), "bytes": int(link_after.st_size), "mtime_ns": int(link_after.st_mtime_ns), "ctime_ns": int(link_after.st_ctime_ns)},
        "payload_read_by_builder": False,
    }


def _record(path: Path, label: str) -> dict[str, Any]:
    if path.expanduser().absolute() == PYTHON:
        return _record_literal_venv_python(path, label)
    path = _path(path, label)
    before = path.stat()
    if before.st_size > MAX_SMALL_BYTES:
        raise BuildError(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig:
        raise BuildError(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "label": label, "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)},
        "payload_read_by_builder": False,
    }


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"{label} root is not an object")
    return value, record


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _proof_request_join(proof: dict[str, Any], proof_path: Path, request_path: Path) -> dict[str, Any]:
    declared = proof.get("request")
    if declared != str(request_path):
        raise BuildError(f"proof/request path join failed: {proof_path}")
    request_sha = proof.get("request_sha256")
    actual_request_sha = _record(request_path, "terminal source request")["sha256"]
    if request_sha != actual_request_sha:
        raise BuildError(f"proof/request SHA join failed: {proof_path}")
    receipt = proof.get("receipt")
    receipt_sha = proof.get("receipt_sha256")
    if not isinstance(receipt, str) or not isinstance(receipt_sha, str):
        raise BuildError(f"terminal proof lacks receipt identity: {proof_path}")
    receipt_path = _path(receipt, "terminal execution receipt")
    receipt_record = _record(receipt_path, "terminal execution receipt")
    if receipt_record["sha256"] != receipt_sha:
        raise BuildError(f"proof/receipt SHA join failed: {proof_path}")
    return {"proof": str(proof_path), "proof_sha256": _record(proof_path, "terminal proof")["sha256"], "request": str(request_path), "request_sha256": request_sha, "receipt": receipt_record}


def _assert_receipt_identity(request: dict[str, Any], receipt: dict[str, Any], mode: str,
                             request_path: Path, request_sha: str) -> None:
    """Require the nested receipt to identify this exact producer request."""
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict) or receipt_request.get("path") != str(request_path):
        raise BuildError(f"{mode} receipt/request path identity differs")
    if receipt_request.get("sha256") != request_sha:
        raise BuildError(f"{mode} receipt/request SHA identity differs")
    request_identity = (request.get("family_id"), request.get("case_id"), request.get("attempt_id"))
    receipt_attempt = receipt.get("attempt_id")
    receipt_identity = tuple(receipt_attempt.split("/")) if isinstance(receipt_attempt, str) else ()
    if len(receipt_identity) != 3 or receipt_identity != request_identity:
        raise BuildError(f"{mode} receipt/request attempt identity differs")
    if int(receipt.get("returncode", receipt.get("execution", {}).get("returncode", -1))) != 0:
        raise BuildError(f"{mode} terminal receipt does not explicitly report returncode 0")


def _snapshot_stat(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or any(field not in value for field in SNAPSHOT_STAT_FIELDS):
        raise BuildError(f"{label} lacks complete stat_before/stat_after")
    result: dict[str, int] = {}
    for field in SNAPSHOT_STAT_FIELDS:
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise BuildError(f"{label} has malformed {field}")
        result[field] = int(item)
    if result["bytes"] < 0:
        raise BuildError(f"{label} has negative size")
    return result


def _snapshot_records(path: Path | None, selected: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Consume the actual ROOT310 snapshot-v2 wrapper.

    Snapshot-v2 deliberately has no top-level ``records`` field.  The only
    accepted payload records are the entries in
    ``requests[].selected_native_files``.  The aggregate SHA list is checked
    against those entries before they are mapped to the v2 observer manifest.
    """
    if path is None:
        return {}, None
    value, record = _json(path, "ROOT279 selected native source snapshot")
    if value.get("schema") != SNAPSHOT_SCHEMA or value.get("status") != SNAPSHOT_STATUS:
        raise BuildError("ROOT279 snapshot is not the completed native-source-snapshot-v2 schema")
    scope = value.get("worker_scope")
    if not isinstance(scope, dict) or scope.get("bi4_decode") is not False or scope.get("solver_launch") is not False:
        raise BuildError("ROOT279 snapshot scope permits decode or solver execution")
    entries = value.get("requests")
    if not isinstance(entries, list) or not entries:
        raise BuildError("ROOT279 snapshot-v2 must contain request entries")
    raw: list[dict[str, Any]] = []
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise BuildError(f"ROOT279 snapshot request entry {entry_index} is malformed")
        files = entry.get("selected_native_files")
        if not isinstance(files, list):
            raise BuildError(f"ROOT279 snapshot request entry {entry_index} lacks selected_native_files")
        raw.extend(files)
    by_path: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BuildError("ROOT279 snapshot record lacks path")
        item_path = str(Path(item["path"]).expanduser().absolute())
        if item_path in by_path:
            raise BuildError("ROOT279 snapshot contains duplicate path")
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise BuildError("ROOT279 snapshot record lacks concrete SHA")
        if isinstance(item.get("bytes"), bool) or not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise BuildError("ROOT279 snapshot record lacks concrete bytes")
        stat_before = _snapshot_stat(item.get("stat_before"), f"snapshot {item_path} stat_before")
        stat_after = _snapshot_stat(item.get("stat_after"), f"snapshot {item_path} stat_after")
        if stat_before != stat_after or item.get("stat_consistency") != "PASS_PRE_POST_IDENTICAL":
            raise BuildError(f"ROOT279 snapshot record is not pre/post stable: {item_path}")
        if stat_after["bytes"] != item["bytes"]:
            raise BuildError(f"ROOT279 snapshot record size disagrees with stat: {item_path}")
        if item.get("mtime_ns") != stat_after["mtime_ns"]:
            raise BuildError(f"ROOT279 snapshot record mtime disagrees with stat: {item_path}")
        by_path[item_path] = {
            **item,
            "path": item_path,
            "sha256": digest.lower(),
            "stat_before": stat_before,
            "stat_after": stat_after,
        }
    required = {str(Path(item["path"]).expanduser().absolute()) for item in selected}
    if set(by_path) != required:
        raise BuildError("ROOT279 snapshot path set does not exactly match selected frames")
    expected_items: list[dict[str, Any]] = []
    for entry in entries:
        for item in entry["selected_native_files"]:
            path_key = str(Path(item["path"]).expanduser().absolute())
            actual = by_path[path_key]
            if item.get("frame") != actual.get("frame"):
                raise BuildError(f"ROOT279 snapshot frame identity disagrees: {path_key}")
            expected_items.append({"frame": actual["frame"], "path": path_key, "bytes": actual["bytes"], "sha256": actual["sha256"]})
    expected_digest = hashlib.sha256(json.dumps(expected_items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if value.get("source_sha_list_digest") != expected_digest:
        raise BuildError("ROOT279 snapshot aggregate source_sha_list_digest mismatch")
    if value.get("selected_native_total_bytes") != sum(item["bytes"] for item in expected_items):
        raise BuildError("ROOT279 snapshot aggregate byte count mismatch")
    immutable = value.get("immutable_source_sha_list")
    if not isinstance(immutable, list) or immutable != expected_items:
        raise BuildError("ROOT279 snapshot immutable_source_sha_list mismatch")
    converted: dict[str, dict[str, Any]] = {}
    for path_key, item in by_path.items():
        converted[path_key] = {
            "path": path_key,
            "frame": int(item["frame"]),
            "sha256": item["sha256"],
            "bytes": int(item["bytes"]),
            "stat_at_prepare": {
                "dev": item["stat_after"]["st_dev"],
                "ino": item["stat_after"]["st_ino"],
                "bytes": item["stat_after"]["bytes"],
                "mtime_ns": item["stat_after"]["mtime_ns"],
                "ctime_ns": item["stat_after"]["ctime_ns"],
            },
            "snapshot_stat_before": item["stat_before"],
            "snapshot_stat_after": item["stat_after"],
            "snapshot_schema": SNAPSHOT_SCHEMA,
        }
    return converted, record


def _member(mode: str, intake: dict[str, Any], request: dict[str, Any], proof: dict[str, Any], request_record: dict[str, Any], proof_path: Path, receipt_path: Path, snapshot: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key = "same_cfl" if mode == "same_cfl" else "half_cfl"
    member = intake.get(key)
    if not isinstance(member, dict):
        raise BuildError(f"intake lacks {key}")
    raw_root = member.get("raw_root")
    runparts = member.get("runparts", {}).get("path") if isinstance(member.get("runparts"), dict) else None
    if not isinstance(raw_root, str) or not isinstance(runparts, str):
        raise BuildError(f"{key} intake lacks raw_root/RunPARTs")
    if request.get("case_id") != member.get("terminal_status", {}).get("case_id", request.get("case_id")):
        # Actual receipt joins below are authoritative; intake does not need
        # to duplicate case_id in its compact terminal status.
        pass
    output_root = request.get("storage_scope", {}).get("output_root")
    terminal_root = member.get("terminal_status", {}).get("output_root")
    if isinstance(output_root, str) and isinstance(terminal_root, str) and output_root != terminal_root:
        raise BuildError(f"{key} actual output root differs from source request")
    copy_binding = request.get("actual_copy_binding", {})
    destinations = copy_binding.get("destinations", []) if isinstance(copy_binding, dict) else []
    xml = next((item for item in destinations if isinstance(item, dict) and item.get("role") == "overlay_xml"), None)
    bi4 = next((item for item in destinations if isinstance(item, dict) and item.get("role") == "overlay_bi4"), None)
    if not isinstance(xml, dict) or not isinstance(xml.get("path"), str) or not isinstance(bi4, dict) or not isinstance(bi4.get("path"), str):
        raise BuildError(f"{key} source copy binding lacks XML/BI4")
    xml_record = _record(Path(xml["path"]), f"{key} copied XML")
    if xml_record["sha256"] != xml.get("sha256"):
        raise BuildError(f"{key} copied XML SHA changed")
    selected = []
    # ROOT271 stores the actual lower/upper times in query_brackets while
    # selected_native_frames intentionally carries only frame/path identity.
    # Reconstruct the time map from that bounded intake metadata; never infer
    # times from frame numbers or the planned query time.
    time_by_frame: dict[int, float] = {}
    for bracket in member.get("query_brackets", []):
        if not isinstance(bracket, dict):
            raise BuildError(f"{key} query bracket is malformed")
        for frame_key, time_key in (("lower_frame", "lower_time_s"), ("upper_frame", "upper_time_s")):
            frame_value = bracket.get(frame_key)
            time_value = bracket.get(time_key)
            if isinstance(frame_value, int) and isinstance(time_value, (int, float)):
                time_by_frame[frame_value] = float(time_value)
    for item in member.get("selected_native_frames", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BuildError(f"{key} selected frame is malformed")
        path = str(Path(item["path"]).expanduser().absolute())
        if not path.startswith(str(Path(raw_root).expanduser().absolute()) + "/"):
            raise BuildError(f"{key} selected frame escapes raw root")
        frame = int(item["native_frame_id"])
        if frame not in time_by_frame:
            raise BuildError(f"{key} selected frame {frame} has no actual intake time")
        selected.append({"path": path, "frame": frame, "time_s": time_by_frame[frame], "known_sha256": item.get("sha256", "PARENT_AFTER_RESERVATION_REQUIRED"), "bytes": item.get("bytes", "UNKNOWN_UNTIL_PARENT_SNAPSHOT"), "stat": item.get("stat", "PARENT_PRE_DECODE_AND_POST_DECODE_FULL_STAT_REQUIRED")})
    if len(selected) != 5:
        raise BuildError(f"{key} must contain exactly five selected native frames")
    deferred: dict[str, dict[str, Any]] = {}
    selected_with_snapshot: list[dict[str, Any]] = []
    for item in selected:
        if snapshot:
            snap = snapshot.get(item["path"])
            if not isinstance(snap, dict):
                raise BuildError(f"{key} missing snapshot record")
            concrete_sha = snap.get("sha256")
            concrete_bytes = snap.get("bytes", snap.get("stat", {}).get("bytes"))
            concrete_stat = snap.get("stat_at_prepare", snap.get("stat"))
            if not isinstance(concrete_sha, str) or len(concrete_sha) != 64:
                raise BuildError(f"{key} snapshot record lacks concrete SHA")
            if not isinstance(concrete_bytes, int) or not isinstance(concrete_stat, dict):
                raise BuildError(f"{key} snapshot record lacks concrete bytes/stat")
            item = {**item, "known_sha256": concrete_sha, "bytes": concrete_bytes, "stat_at_prepare": concrete_stat}
        selected_with_snapshot.append(item)
        deferred[item["path"]] = item
    case = {
        "label": mode,
        "identity": {"family_id": "F1", "sentinel_id": "F1-S2", "physical_case_id": request.get("physical_case_id"), "grid": "medium", "cfl_mode": mode},
        "raw_root": str(Path(raw_root).expanduser().absolute()),
        "runparts": str(Path(runparts).expanduser().absolute()),
        "generated_xml": xml_record["path"],
        "decoder": str(DECODER),
        "decoder_source": str(DECODER_SOURCE),
        "expected_frame_count": int(member["runparts"].get("rows", 101)),
        "expected_final_time_s": float(member["runparts_last_time_s"]),
        "selected_frames": [item["frame"] for item in selected],
        "query_times": list(QUERY_TIMES),
        "scratch_root": "{attempt_root}/scratch/root279/" + mode,
        "selected_native_frame_metadata": selected_with_snapshot,
        "terminal_binding": _proof_request_join(proof, proof_path, request_path=Path(request_record["path"])),
    }
    records = [request_record, _record(proof_path, f"{mode} terminal proof"), _record(receipt_path, f"{mode} terminal receipt"), _record(Path(runparts), f"{mode} RunPARTs"), xml_record, _record(DECODER, "official BI4 decoder"), _record(DECODER_SOURCE, "official BI4 decoder source")]
    return case, records


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    intake, intake_record = _json(args.intake, "ROOT271 actual pair intake")
    if intake.get("schema") != INTAKE_SCHEMA or intake.get("status") != "SOURCE_PREPARED_PARENT_NATIVE_SNAPSHOT_REQUIRED":
        raise BuildError("ROOT271 intake is not the expected source-only terminal status")
    same_request, same_request_record = _json(args.same_request, "ROOT277 request")
    half_request, half_request_record = _json(args.half_request, "ROOT278 request")
    same_proof, _ = _json(args.same_proof, "ROOT277 proof")
    half_proof, _ = _json(args.half_proof, "ROOT278 proof")
    same_receipt, same_receipt_record = _json(args.same_receipt, "ROOT277 receipt")
    half_receipt, half_receipt_record = _json(args.half_receipt, "ROOT278 receipt")
    if same_proof.get("status", "").find("VERIFIED_ACTUAL_F1_S2_DP020_SAME_CFL") < 0 or half_proof.get("status", "").find("VERIFIED_ACTUAL_F1_S2_DP020_HALF_CFL") < 0:
        raise BuildError("ROOT277/278 proof status is not the actual terminal pair")
    # The receipt's nested request identity is authoritative.  Keep the
    # source request object untouched and compare it with the exact path/SHA
    # records that were just read; labels and attempt names are not a join.
    request_receipt_joins = (
        (same_request, same_receipt, "same_cfl", Path(args.same_request).expanduser().absolute(), same_request_record["sha256"]),
        (half_request, half_receipt, "half_cfl", Path(args.half_request).expanduser().absolute(), half_request_record["sha256"]),
    )
    for request, receipt, mode, request_path, request_sha in request_receipt_joins:
        _assert_receipt_identity(request, receipt, mode, request_path, request_sha)
    snapshot, snapshot_record = _snapshot_records(args.snapshot, [item for mode in ("same_cfl", "half_cfl") for item in (intake[mode].get("selected_native_frames") or [])])
    same_case, same_records = _member("same_cfl", intake, same_request, same_proof, same_request_record, args.same_proof, args.same_receipt, snapshot)
    half_case, half_records = _member("half_cfl", intake, half_request, half_proof, half_request_record, args.half_proof, args.half_receipt, snapshot)
    cases = [same_case, half_case]
    deferred = {}
    for case in cases:
        for rec in case["selected_native_frame_metadata"]:
            deferred[rec["path"]] = rec
    source_records: dict[str, dict[str, Any]] = {}
    for record in [intake_record, same_request_record, half_request_record, _record(args.same_proof, "ROOT277 terminal proof"), _record(args.half_proof, "ROOT278 terminal proof"), same_receipt_record, half_receipt_record, *same_records, *half_records, _record(Path(__file__), "ROOT279 V3 request builder"), _record(WORKER, "ROOT279 guarded worker"), _record(V4_WRAPPER, "ROOT204 V4 guard dependency"), _record(V1_WORKER, "ROOT204 V1 worker"), _record(BASE_OBSERVER, "native observer dependency"), _record(CONTRACT, "ROOT279 contract"), _record(PYVENV_CFG, "literal venv configuration")]:
        source_records[record["path"]] = record
    if snapshot_record:
        source_records[snapshot_record["path"]] = snapshot_record
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_PENDING_PARENT_SNAPSHOT" if not snapshot else "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT",
        "axis_authority": {"coordinate_contract": {"frame": "producer component/world mapping remains UNKNOWN", "position_unit": "m", "velocity_unit": "m/s", "mass_unit": "kg", "time_unit": "s"}, "source_records": [_record(PYTHON, "literal venv python"), _record(PYTHON_TARGET, "resolved Python target")], "status_reason": "ROOT207/217 storage calibration is bound; producer world-axis orientation remains UNKNOWN", "producer_axis_orientation_metadata": "UNKNOWN"},
        "cases": cases,
        "native_deferred_records": deferred,
        "native_deferred_policy": {"count": 10, "parent_after_reservation_first_sha_and_stat": True, "parent_after_child_post_sha_and_stat": True, "known_sha_required_before_child": True, "source_replace_or_stat_change": "FAIL", "full_native_tree_hash": "NOT_REQUESTED"},
        "source_pair": {"same_request_sha256": same_request_record["sha256"], "half_request_sha256": half_request_record["sha256"], "same_proof_sha256": source_records[str(args.same_proof.absolute())]["sha256"], "half_proof_sha256": source_records[str(args.half_proof.absolute())]["sha256"], "intake_sha256": intake_record["sha256"]},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    manifest_path = args.manifest_output.absolute()
    request_path = args.request_output.absolute()
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "ROOT279 manifest")
    source_records[manifest_record["path"]] = manifest_record
    input_files = sorted(source_records)
    ready = bool(snapshot)
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_ROOT279_PAIR_NATIVE_OBSERVER_V3" if ready else "WAITING_PARENT_SELECTED_NATIVE_SNAPSHOT_ROOT279_V3",
        "kind": "cpu", "cpu_task_kind": "audit", "request_id": "f1-s2-root279-pair-native-observer-v3-001", "family_id": "F1", "sentinel_id": "F1-S2", "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1", "case_id": "F1_S2_DP020_ROOT279_PAIR_NATIVE_OBSERVER_V3", "attempt_id": "f1-s2-root279-pair-native-observer-v3-001", "cwd": str(PRIMARY), "worktree_root": str(PRIMARY),
        "command": [str(PYTHON), str(WORKER), "--run", "--manifest", manifest_record["path"], "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_root279_pair_native_observer_v2.json", "--v1-worker", str(V1_WORKER), "--python", str(PYTHON), "--cwd", str(PRIMARY), "--max-scratch-bytes", str(256 * 1024 * 1024), "--max-log-bytes", str(1024 * 1024), "--timeout-seconds", "1800"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": input_files, "input_sha256": {path: source_records[path]["sha256"] for path in input_files}, "input_records": source_records, "manifest": manifest_record,
        "deferred_input_files": sorted(deferred), "deferred_input_records": list(deferred.values()), "deferred_input_policy": manifest["native_deferred_policy"],
        "estimated_native_read_passes": 4, "estimated_native_read_bytes": sum(int(item.get("bytes", 0)) for item in deferred.values() if isinstance(item.get("bytes"), int)) * 4, "estimated_native_read_bytes_scope": "ten selected Part files; actual bytes require parent snapshot", "estimated_hdf5_read_bytes": 0, "estimated_storage_bytes": 128 * 1024 * 1024, "estimated_peak_memory_bytes": 2 * 1024 * 1024 * 1024,
        "runtime_closure": {"request_builder_v3": str(Path(__file__)), "guarded_worker": str(WORKER), "v4_guard_dependency": str(V4_WRAPPER), "v1_worker": str(V1_WORKER), "native_observer": str(BASE_OBSERVER), "literal_python": str(PYTHON), "pyvenv_cfg": str(PYVENV_CFG), "parent_v8_deferred_sha_stat_gate": False, "child_wrapper_deferred_sha_stat_gate": True},
        "storage_scope": {"output_root": "{attempt_root}", "selected_native_frames": 10, "full_native_tree_scan": False, "h5_vtk_allowed": False, "solver_launch": False}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}, "launch_disabled": not ready, "execution_allowed": False, "solver_started": False, "native_payload_read": False, "hdf5_read": False, "ledger_mutation": False,
        "source_binding": {"root271_intake": intake_record, "root277_terminal": _proof_request_join(same_proof, args.same_proof, args.same_request), "root278_terminal": _proof_request_join(half_proof, args.half_proof, args.half_request), "queries_s": list(QUERY_TIMES), "interpolation": "FORBIDDEN", "async_alignment": "UNKNOWN", "native_mass_only": True, "continuum_owner_mass_kg": 340.0, "world_axis": "UNKNOWN", "manifest_path_frozen_absolute": manifest_record["path"]},
    }
    _write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    assert EXPECTED_DEFERRED_COUNT == 10
    assert all(value not in FORBIDDEN_SUFFIXES for value in (WORKER.suffix, V4_WRAPPER.suffix, V1_WORKER.suffix))
    request = {"family_id": "F1", "case_id": "case", "attempt_id": "attempt"}
    receipt = {"request": {"path": "/tmp/request.json", "sha256": "a" * 64}, "attempt_id": "F1/case/attempt", "returncode": 0}
    _assert_receipt_identity(request, receipt, "selftest", Path("/tmp/request.json"), "a" * 64)
    bad = dict(receipt, attempt_id="F1/case/wrong-attempt")
    try:
        _assert_receipt_identity(request, bad, "selftest", Path("/tmp/request.json"), "a" * 64)
    except BuildError:
        pass
    else:
        raise AssertionError("receipt attempt identity mismatch was accepted")
    # Rehearse the actual ROOT310 snapshot-v2 shape with ten metadata records:
    # requests[].selected_native_files, stat_before/stat_after, and the
    # immutable aggregate list.  No fixture payload is opened or hashed.
    with tempfile.TemporaryDirectory(prefix="root279-v3-snapshot-") as td:
        root = Path(td); files = []
        for mode in ("same", "half"):
            entry_files = []
            for index, frame in enumerate((0, 49, 50, 99, 100)):
                path = root / mode / f"Part_{frame:04d}.bi4"; path.parent.mkdir(parents=True, exist_ok=True)
                stat = {"bytes": 100 + index, "mtime_ns": 10 + index, "ctime_ns": 20 + index, "st_dev": 1, "st_ino": 1000 + len(files)}
                item = {"path": str(path), "bytes": stat["bytes"], "mtime_ns": stat["mtime_ns"], "sha256": f"{len(files) + 1:064x}", "stat_before": stat, "stat_after": dict(stat), "stat_consistency": "PASS_PRE_POST_IDENTICAL", "frame": frame}
                entry_files.append(item); files.append(item)
            # Keep one request entry per ROOT310 template.
            if mode == "same":
                same_entry = entry_files
            else:
                half_entry = entry_files
        immutable = [{"frame": item["frame"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in files]
        snapshot = {"schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS, "worker_scope": {"bi4_decode": False, "solver_launch": False}, "requests": [{"selected_native_files": same_entry}, {"selected_native_files": half_entry}], "immutable_source_sha_list": immutable, "selected_native_total_bytes": sum(item["bytes"] for item in files), "source_sha_list_digest": hashlib.sha256(json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()}
        snapshot_path = root / "native_selected_source_snapshot_v2.json"; snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        parsed, _ = _snapshot_records(snapshot_path, [{"path": item["path"]} for item in files])
        assert len(parsed) == EXPECTED_DEFERRED_COUNT and all("stat_at_prepare" in item for item in parsed.values())
    print("PASS_F1_S2_ROOT279_REQUEST_V3_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--intake", type=Path)
    parser.add_argument("--same-request", type=Path)
    parser.add_argument("--half-request", type=Path)
    parser.add_argument("--same-proof", type=Path)
    parser.add_argument("--half-proof", type=Path)
    parser.add_argument("--same-receipt", type=Path)
    parser.add_argument("--half-receipt", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    required = (args.intake, args.same_request, args.half_request, args.same_proof, args.half_proof, args.same_receipt, args.half_receipt, args.manifest_output, args.request_output)
    if any(item is None for item in required):
        parser.error("--build requires intake, both requests/proofs/receipts, and manifest/request outputs")
    try:
        _, request = build(args)
    except Exception as exc:
        print(f"ROOT279 V3 builder failed: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output.absolute()), "request": str(args.request_output.absolute()), "native_payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
