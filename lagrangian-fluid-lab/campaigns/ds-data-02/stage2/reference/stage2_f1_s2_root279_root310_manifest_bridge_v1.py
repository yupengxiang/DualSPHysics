#!/usr/bin/env python3
"""Bridge the ROOT310 v3 source manifest to the consumed ROOT279 v2 guard.

ROOT279 v6 deliberately uses the newer ``v3-root310`` manifest.  The
consumed ROOT279 guard still accepts only
``native-selected-observer-manifest.v2`` and its V1 observer has an additional
axis-contract precondition.  This additive bridge checks both boundaries
without touching either consumed source artifact:

* it validates the ten ROOT310 records using metadata from the manifest only;
* it projects the records to a temporary v2 manifest, normalising the
  ``st_dev/st_ino`` names used by ROOT310 to the ``device/inode`` names the
  old guard checks; and
* it refuses to invoke the old guard until the V1 axis contract is actually
  present.  The current ROOT279 v6 package therefore reports WAITING rather
  than converting ``UNKNOWN`` into a world-axis claim.

``--self-test`` runs the real consumed guard against ten manufactured files
through the v3-to-v2 projection.  ``--validate`` reads only bounded JSON and
writes a small metadata report.  ``--build-request`` creates a new source
request and manifest around an existing v6 request; it never reads a BI4,
VTK, H5, solver output, or RunPARTs payload.  Every result keeps QI/QN/QE and
production credit at UNKNOWN/zero.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_GUARD = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
V4_GUARD = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
V1_WORKER = HERE / "stage2_f1_native_selected_observer_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V3_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v3-root310"
V2_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
V1_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
BRIDGE_SCHEMA = "ds02.stage2.f1-s2.root279-root310-v3-to-v2-bridge.v1"
BUILDER_VARIANT = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v7-root310-bridge"
MAX_JSON_BYTES = 10 * 1024 * 1024
EXPECTED_LABELS = ("same_cfl", "half_cfl")
EXPECTED_FRAMES = (0, 49, 50, 99, 100)
EXPECTED_QUERIES = (0.0, 0.25, 0.5)
EXPECTED_DEFERRED = 10


class BridgeFailure(RuntimeError):
    """A source, ABI, or request-contract failure."""


def _absolute(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _canonical(value: str) -> str:
    # resolve(strict=False) performs no payload read and gives stable path
    # comparison for the absolute paths recorded by ROOT310.
    return str(Path(value).expanduser().resolve(strict=False))


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BridgeFailure(f"{label} is not a 64-character SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise BridgeFailure(f"{label} is not hexadecimal") from exc
    return value.lower()


def _bounded_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    try:
        stat_before = path.stat()
    except OSError as exc:
        raise BridgeFailure(f"{label} cannot be stat'ed: {path}: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise BridgeFailure(f"{label} is not a regular file: {path}")
    if stat_before.st_size > MAX_JSON_BYTES:
        raise BridgeFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeFailure(f"cannot read {label}: {path}: {exc}") from exc
    stat_after = path.stat()
    if stat_before != stat_after:
        raise BridgeFailure(f"{label} changed during bounded read: {path}")
    if not isinstance(value, dict):
        raise BridgeFailure(f"{label} is not a JSON object: {path}")
    return value, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat": {
            "bytes": int(stat_after.st_size),
            "mtime_ns": int(stat_after.st_mtime_ns),
            "ctime_ns": int(stat_after.st_ctime_ns),
            "device": int(stat_after.st_dev),
            "inode": int(stat_after.st_ino),
        },
        "payload_read_by_bridge": False,
    }


def _small_record(path: Path, label: str) -> dict[str, Any]:
    """Record code/JSON closure only; never use this for native payloads."""
    value = _absolute(path)
    if value.suffix.lower() in {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"}:
        raise BridgeFailure(f"refusing to read native/VTK/H5 source as bounded metadata: {value}")
    _, record = _bounded_json(value, label) if value.suffix.lower() == ".json" else _bounded_file(value, label)
    return record


def _bounded_file(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    path = _absolute(path)
    try:
        before = path.stat()
    except OSError as exc:
        raise BridgeFailure(f"{label} cannot be stat'ed: {path}: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise BridgeFailure(f"{label} is not a regular file: {path}")
    if before.st_size > MAX_JSON_BYTES:
        raise BridgeFailure(f"{label} exceeds the 10 MiB source cap: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BridgeFailure(f"cannot read {label}: {path}: {exc}") from exc
    after = path.stat()
    if before != after:
        raise BridgeFailure(f"{label} changed during bounded read: {path}")
    return raw, {
        "path": str(path),
        "label": label,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat": {
            "bytes": int(after.st_size),
            "mtime_ns": int(after.st_mtime_ns),
            "ctime_ns": int(after.st_ctime_ns),
            "device": int(after.st_dev),
            "inode": int(after.st_ino),
        },
        "payload_read_by_bridge": False,
    }


def _stat_aliases(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise BridgeFailure(f"{label} is not a stat object")

    def get(*keys: str) -> int:
        for key in keys:
            if key in value:
                try:
                    return int(value[key])
                except (TypeError, ValueError) as exc:
                    raise BridgeFailure(f"{label}.{key} is not an integer") from exc
        raise BridgeFailure(f"{label} lacks one of {keys}")

    return {
        "bytes": get("bytes", "size"),
        "mtime_ns": get("mtime_ns"),
        "ctime_ns": get("ctime_ns"),
        "device": get("device", "st_dev", "dev"),
        "inode": get("inode", "st_ino"),
    }


def _record_path(value: Any, label: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BridgeFailure(f"{label} lacks a path")
    path = _canonical(value["path"])
    if Path(path).suffix.lower() != ".bi4":
        raise BridgeFailure(f"{label} is not a selected BI4 path: {path}")
    return path


def _record_sha(value: dict[str, Any], label: str) -> str:
    return _hex(value.get("known_sha256", value.get("sha256")), f"{label}.known_sha256")


def _validate_record(value: Any, label: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise BridgeFailure(f"{label} is not an object")
    path = _record_path(value, label)
    sha = _record_sha(value, label)
    if value.get("source_basis") != "ROOT310_PARENT_AFTER_RESERVATION_SINGLE_STREAM":
        raise BridgeFailure(f"{label} is not bound to the ROOT310 after-reservation source")
    before = _stat_aliases(value.get("stat_before"), f"{label}.stat_before")
    after = _stat_aliases(value.get("stat_after"), f"{label}.stat_after")
    if before != after:
        raise BridgeFailure(f"{label} stat_before/stat_after differ")
    if value.get("stat_consistency") != "PASS_PRE_POST_IDENTICAL":
        raise BridgeFailure(f"{label} has no pre/post stat consistency result")
    if int(value.get("bytes", -1)) != before["bytes"]:
        raise BridgeFailure(f"{label}.bytes disagrees with the deferred stat")
    if "frame" not in value:
        raise BridgeFailure(f"{label} has no frame")
    return path, {
        "bytes": before["bytes"],
        "frame": int(value["frame"]),
        "known_sha256": sha,
        "path": path,
        "source_basis": value["source_basis"],
        "stat_before": before,
        "stat_after": after,
        "stat_consistency": "PASS_PRE_POST_IDENTICAL",
        "time_s": value.get("time_s"),
    }


def _axis_gate(axis: Any) -> dict[str, Any]:
    if not isinstance(axis, dict):
        return {"status": "WAITING_V1_AXIS_CONTRACT", "reason": "axis_authority is absent"}
    coordinate = axis.get("coordinate_contract")
    if not isinstance(coordinate, dict):
        return {"status": "WAITING_V1_AXIS_CONTRACT", "reason": "coordinate_contract is absent"}
    required = ("frame", "axis_labels", "position_unit", "velocity_unit", "mass_unit", "time_unit", "rotation_to_world")
    missing = [key for key in required if key not in coordinate]
    records = axis.get("source_records")
    if not isinstance(records, list) or not records:
        missing.append("source_records")
    if missing:
        return {"status": "WAITING_V1_AXIS_CONTRACT", "reason": "missing " + ", ".join(missing)}
    if axis.get("producer_axis_orientation_metadata") == "UNKNOWN":
        # The old observer can technically consume a complete source contract,
        # but no world-axis scientific claim is granted by this bridge.
        return {"status": "READY_TECHNICAL_AXIS_UNKNOWN", "reason": "technical V1 fields are present; producer orientation remains UNKNOWN"}
    return {"status": "READY_TECHNICAL_AXIS_BOUND", "reason": "V1 axis fields are structurally complete"}


def validate_v3_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != V3_SCHEMA:
        raise BridgeFailure(f"expected ROOT310 manifest schema {V3_SCHEMA!r}, got {manifest.get('schema')!r}")
    if not str(manifest.get("status", "")).startswith("PREPARED_ROOT279_ROOT310_SNAPSHOT_BOUND"):
        raise BridgeFailure("ROOT310 manifest is not a prepared snapshot-bound status")
    if manifest.get("native_deferred_policy", {}).get("count") != EXPECTED_DEFERRED:
        raise BridgeFailure("ROOT310 manifest policy does not declare ten deferred records")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or [case.get("label") for case in cases if isinstance(case, dict)] != list(EXPECTED_LABELS):
        raise BridgeFailure("ROOT310 manifest must contain same_cfl followed by half_cfl")

    top = manifest.get("native_deferred_records")
    if not isinstance(top, dict) or len(top) != EXPECTED_DEFERRED:
        raise BridgeFailure("ROOT310 manifest must contain exactly ten deferred records")
    top_records: dict[str, dict[str, Any]] = {}
    for raw_key, raw_record in top.items():
        path, normalized = _validate_record(raw_record, f"native_deferred_records[{raw_key!r}]")
        if _canonical(str(raw_key)) != path:
            raise BridgeFailure(f"deferred key/path mismatch: {raw_key!r} vs {path}")
        if path in top_records:
            raise BridgeFailure(f"duplicate deferred path: {path}")
        top_records[path] = normalized

    case_paths: set[str] = set()
    case_summaries: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise BridgeFailure("ROOT310 case is not an object")
        label = case["label"]
        identity = case.get("identity")
        if not isinstance(identity, dict) or identity.get("family_id") != "F1" or identity.get("sentinel_id") != "F1-S2" or identity.get("grid") != "medium":
            raise BridgeFailure(f"{label} identity is not the F1-S2 medium case")
        if not isinstance(identity.get("physical_case_id"), str) or not identity["physical_case_id"]:
            raise BridgeFailure(f"{label} lacks a physical_case_id")
        if tuple(case.get("selected_frames", ())) != EXPECTED_FRAMES:
            raise BridgeFailure(f"{label} selected_frames do not match ROOT310's five-frame contract")
        if tuple(float(x) for x in case.get("query_times", ())) != EXPECTED_QUERIES:
            raise BridgeFailure(f"{label} query_times do not match [0,.25,.5]")
        selected = case.get("selected_native_frame_metadata")
        if not isinstance(selected, list) or len(selected) != len(EXPECTED_FRAMES):
            raise BridgeFailure(f"{label} lacks five selected-native metadata records")
        selected_paths: set[str] = set()
        for index, raw in enumerate(selected):
            path, normalized = _validate_record(raw, f"{label}.selected_native_frame_metadata[{index}]")
            if normalized["frame"] != EXPECTED_FRAMES[index]:
                raise BridgeFailure(f"{label} frame order is not {EXPECTED_FRAMES}")
            if path in selected_paths or path in case_paths:
                raise BridgeFailure(f"duplicate selected path across ROOT310 cases: {path}")
            if path not in top_records or top_records[path]["known_sha256"] != normalized["known_sha256"]:
                raise BridgeFailure(f"{label} selected record is not exactly bound by the top deferred map")
            selected_paths.add(path)
        case_paths.update(selected_paths)
        snapshot = case.get("native_source_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("selected_file_count") != 5:
            raise BridgeFailure(f"{label} lacks the ROOT310 selected-source snapshot count")
        for key in ("proof_sha256", "report_sha256"):
            _hex(snapshot.get(key), f"{label}.native_source_snapshot.{key}")
        case_summaries.append({
            "label": label,
            "physical_case_id": identity["physical_case_id"],
            "selected_paths": sorted(selected_paths),
            "expected_frame_count": case.get("expected_frame_count"),
            "expected_final_time_s": case.get("expected_final_time_s"),
        })
    if set(top_records) != case_paths:
        raise BridgeFailure("top deferred map contains paths not represented by the two cases")
    pair = manifest.get("source_pair")
    if not isinstance(pair, dict):
        raise BridgeFailure("ROOT310 source_pair is absent")
    for key, value in pair.items():
        if key.endswith("sha256"):
            _hex(value, f"source_pair.{key}")
    qualification = manifest.get("scientific_qualification", {})
    if isinstance(qualification, dict) and any(qualification.get(key) not in (None, "UNKNOWN") for key in ("QI", "QN", "QE")):
        raise BridgeFailure("ROOT310 manifest carries an unsupported scientific qualification")
    return {
        "schema": V3_SCHEMA,
        "deferred_count": len(top_records),
        "cases": case_summaries,
        "records": top_records,
        "axis_gate": _axis_gate(manifest.get("axis_authority")),
        "producer_axis_orientation": manifest.get("axis_authority", {}).get("producer_axis_orientation_metadata", "UNKNOWN") if isinstance(manifest.get("axis_authority"), dict) else "UNKNOWN",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }


def project_v3_to_v2(manifest: dict[str, Any], output_path: Path | None = None) -> dict[str, Any]:
    checked = validate_v3_manifest(manifest)
    value = copy.deepcopy(manifest)
    value["schema"] = V2_SCHEMA
    records: dict[str, dict[str, Any]] = {}
    for path, record in checked["records"].items():
        projected = copy.deepcopy(record)
        # V4's _expected_stat checks device/inode and does not know the
        # ROOT310 st_dev/st_ino spelling.  Keep the original metadata and add
        # the exact normalized contract used by the consumed guard.
        projected["stat_at_prepare"] = {
            "bytes": record["stat_before"]["bytes"],
            "mtime_ns": record["stat_before"]["mtime_ns"],
            "ctime_ns": record["stat_before"]["ctime_ns"],
            "device": record["stat_before"]["device"],
            "inode": record["stat_before"]["inode"],
        }
        records[path] = projected
    value["native_deferred_records"] = records
    value["bridge_projection"] = {
        "schema": BRIDGE_SCHEMA,
        "source_schema": V3_SCHEMA,
        "target_schema": V2_SCHEMA,
        "payload_read_by_bridge": False,
        "stat_alias_normalization": "ROOT310 st_dev/st_ino -> consumed V4 device/inode",
        "axis_gate": checked["axis_gate"],
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    if output_path is not None:
        _write_once(output_path, value)
    return value


def _load_module(path: Path, name: str) -> Any:
    path = _absolute(path)
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BridgeFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_guard_abi(projected: dict[str, Any], root: Path) -> dict[str, Any]:
    guard = _load_module(V2_GUARD, "root279_guard_bridge_old_v1")
    guard._configure()
    loaded = guard.V4._load_deferred(projected)
    if len(loaded) != EXPECTED_DEFERRED:
        raise BridgeFailure("consumed ROOT279 guard did not accept exactly ten projected records")
    attempt = root / "abi-attempt"
    v1_manifest = guard.V4._make_v1_manifest(projected, attempt)
    v1_doc = json.loads(v1_manifest.read_text(encoding="utf-8"))
    if v1_doc.get("schema") != V1_SCHEMA:
        raise BridgeFailure("consumed guard did not produce its V1 child manifest")
    v1 = _load_module(V1_WORKER, "root279_bridge_old_v1_worker")
    try:
        v1._axis_contract(projected.get("axis_authority", {}))
    except Exception as exc:
        return {
            "projected_v2_record_count": len(loaded),
            "v1_manifest_schema": v1_doc.get("schema"),
            "v1_axis_status": "WAITING_ROOT279_V1_AXIS_CONTRACT",
            "v1_axis_reason": str(exc),
            "native_payload_read": False,
            "production_credit": 0,
        }
    return {
        "projected_v2_record_count": len(loaded),
        "v1_manifest_schema": v1_doc.get("schema"),
        "v1_axis_status": "READY_TECHNICAL_AXIS_CONTRACT",
        "native_payload_read": False,
        "production_credit": 0,
    }


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BridgeFailure(f"refusing to overwrite immutable bridge output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _fixture_v3(v2_doc: dict[str, Any], worker: Path) -> dict[str, Any]:
    """Convert the consumed guard's ten-file fixture into a v3 fixture."""
    raw_records = list(v2_doc["native_deferred_records"].values())
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_records):
        stat_value = raw["stat_at_prepare"]
        normalized.append({
            "path": raw["path"], "frame": EXPECTED_FRAMES[index % 5], "bytes": raw["bytes"],
            "known_sha256": raw["known_sha256"], "source_basis": "ROOT310_PARENT_AFTER_RESERVATION_SINGLE_STREAM",
            "stat_before": {"bytes": stat_value["bytes"], "mtime_ns": stat_value["mtime_ns"], "ctime_ns": stat_value["ctime_ns"], "st_dev": stat_value["device"], "st_ino": stat_value["inode"]},
            "stat_after": {"bytes": stat_value["bytes"], "mtime_ns": stat_value["mtime_ns"], "ctime_ns": stat_value["ctime_ns"], "st_dev": stat_value["device"], "st_ino": stat_value["inode"]},
            "stat_consistency": "PASS_PRE_POST_IDENTICAL", "time_s": float(index),
        })
    axis_record = {"path": str(worker), "bytes": worker.stat().st_size, "mtime_ns": worker.stat().st_mtime_ns, "sha256": hashlib.sha256(worker.read_bytes()).hexdigest()}
    cases: list[dict[str, Any]] = []
    for case_index, label in enumerate(EXPECTED_LABELS):
        chunk = normalized[case_index * 5:(case_index + 1) * 5]
        cases.append({
            "label": label,
            "identity": {"family_id": "F1", "sentinel_id": "F1-S2", "grid": "medium", "physical_case_id": "fixture"},
            "raw_root": v2_doc["cases"][0]["raw_root"], "runparts": str(worker), "generated_xml": str(worker), "decoder": str(worker), "decoder_source": str(worker),
            "scratch_root": "{attempt_root}/scratch/" + label,
            "selected_frames": list(EXPECTED_FRAMES), "query_times": list(EXPECTED_QUERIES), "expected_frame_count": 101, "expected_final_time_s": 0.5,
            "selected_native_frame_metadata": copy.deepcopy(chunk), "native_source_snapshot": {"selected_file_count": 5, "proof_sha256": "a" * 64, "report_sha256": "b" * 64},
        })
    return {
        "schema": V3_SCHEMA, "status": "PREPARED_ROOT279_ROOT310_SNAPSHOT_BOUND_WAITING_PARENT_NATIVE_DECODE",
        "axis_authority": {"coordinate_contract": {"frame": "world_cartesian_right_handed", "axis_labels": ["x", "y", "z"], "position_unit": "m", "velocity_unit": "m/s", "mass_unit": "kg", "time_unit": "s", "rotation_to_world": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}, "producer_axis_orientation_metadata": "UNKNOWN", "source_records": [axis_record]},
        "cases": cases,
        "native_deferred_policy": {"count": EXPECTED_DEFERRED, "known_sha_required_before_child": True},
        "native_deferred_records": {item["path"]: item for item in normalized},
        "source_pair": {"fixture_sha256": "c" * 64}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }


def _run_old_guard_fixture(v3_doc: dict[str, Any], root: Path) -> None:
    guard = _load_module(V2_GUARD, "root279_bridge_fixture_guard")
    guard._configure()
    projected = project_v3_to_v2(v3_doc)
    projected_path = root / "fixture-v2.json"
    _write_once(projected_path, projected)
    worker = root / "seed" / "fixture_v1.py"
    args = argparse.Namespace(
        manifest=projected_path, attempt_root=root / "attempt", output=root / "attempt" / "observer" / "result.json",
        log_path=root / "attempt" / "observer" / "child.log", v1_worker=worker, python=Path(guard.V4.PYTHON), cwd=root,
        max_scratch_bytes=guard.V4.SCRATCH_CAP_BYTES, max_log_bytes=guard.V4.DEFAULT_MAX_LOG_BYTES, timeout_seconds=10.0,
    )
    result = guard.V4.run_guard(args)
    if not str(result.get("status", "")).startswith("PASS"):
        raise BridgeFailure(f"manufactured projected v2 guard failed: {result}")


def _validate_v6(manifest_path: Path, request_path: Path, report_path: Path | None) -> dict[str, Any]:
    manifest, manifest_record = _bounded_json(manifest_path, "ROOT310 v3 manifest")
    request, request_record = _bounded_json(request_path, "ROOT279 v6 request")
    checked = validate_v3_manifest(manifest)
    if request.get("schema") != REQUEST_SCHEMA:
        raise BridgeFailure("ROOT279 source request is not ds02.request.v1")
    request_manifest = request.get("manifest")
    if not isinstance(request_manifest, dict) or _canonical(str(request_manifest.get("path"))) != _canonical(str(manifest_path)):
        raise BridgeFailure("ROOT279 request manifest path does not bind the supplied ROOT310 manifest")
    if request_manifest.get("sha256") != manifest_record["sha256"]:
        raise BridgeFailure("ROOT279 request manifest SHA does not match the supplied v3 manifest")
    command = request.get("command")
    direct_old_guard = isinstance(command, list) and any(Path(str(item)).name == V2_GUARD.name for item in command)
    projected = project_v3_to_v2(manifest)
    with tempfile.TemporaryDirectory(prefix="root279-bridge-abi-") as directory:
        abi = _old_guard_abi(projected, Path(directory))
    result = {
        "schema": BRIDGE_SCHEMA, "status": "WAITING_ROOT279_V3_TO_V2_AXIS_PREFLIGHT" if checked["axis_gate"]["status"].startswith("WAITING") else "READY_TECHNICAL_ROOT279_V3_TO_V2_BRIDGE",
        "manifest": manifest_record, "request": request_record, "v3_validation": {k: v for k, v in checked.items() if k != "records"},
        "old_guard_abi": abi, "old_v6_command_direct_old_guard": direct_old_guard,
        "projection_schema": V2_SCHEMA, "projection_deferred_count": len(projected["native_deferred_records"]),
        "native_payload_read": False, "production_credit": 0,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "source_scope": "bounded manifest/request JSON only; no BI4/VTK/H5/RunPARTs read",
    }
    if report_path is not None:
        _write_once(report_path, result)
    return result


def _bridge_run(args: argparse.Namespace) -> int:
    manifest, _ = _bounded_json(args.manifest_v3, "ROOT310 v3 manifest")
    checked = validate_v3_manifest(manifest)
    projected = project_v3_to_v2(manifest)
    with tempfile.TemporaryDirectory(prefix="root279-bridge-preflight-") as directory:
        abi = _old_guard_abi(projected, Path(directory))
    if abi["v1_axis_status"] == "WAITING_ROOT279_V1_AXIS_CONTRACT":
        print(json.dumps({"schema": BRIDGE_SCHEMA, "status": "WAITING_ROOT279_V1_AXIS_CONTRACT", "reason": abi["v1_axis_reason"], "native_payload_read": False, "production_credit": 0}, sort_keys=True))
        return 2
    attempt_root = _absolute(args.attempt_root)
    attempt_root.mkdir(parents=True, exist_ok=True)
    projected_path = attempt_root / "guarded-inputs" / "root310-v2-manifest.json"
    _write_once(projected_path, projected)
    output = _absolute(args.output)
    guard = _load_module(_absolute(args.guard), "root279_bridge_runtime_guard")
    guard._configure()
    guard_args = argparse.Namespace(
        manifest=projected_path,
        attempt_root=attempt_root,
        output=output,
        log_path=attempt_root / "observer" / "root279-v2-guard-child.log",
        v1_worker=_absolute(args.v1_worker),
        python=_absolute(args.python),
        cwd=_absolute(args.cwd),
        max_scratch_bytes=int(args.max_scratch_bytes),
        max_log_bytes=int(args.max_log_bytes),
        timeout_seconds=float(args.timeout_seconds),
    )
    # Execute the consumed guard in-process.  Its own bounded process-group
    # child runner remains the cancellation boundary, so the bridge cannot
    # orphan a second guard process when the parent runtime cancels it.
    result = guard.V4.run_guard(guard_args)
    print(json.dumps({"schema": BRIDGE_SCHEMA, "status": result.get("status"), "projected_manifest": str(projected_path), "native_payload_read": "delegated_to_consumed_guard_after_parent_reservation", "production_credit": 0}, sort_keys=True))
    return 0 if str(result.get("status", "")).startswith("PASS") else 2


def _build_request(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_record = _bounded_json(args.manifest_v3, "ROOT310 v3 source manifest")
    request, request_record = _bounded_json(args.request_v6, "ROOT279 v6 source request")
    checked = validate_v3_manifest(manifest)
    if request.get("schema") != REQUEST_SCHEMA:
        raise BridgeFailure("source request is not ds02.request.v1")
    if request.get("manifest", {}).get("sha256") != manifest_record["sha256"] or _canonical(str(request.get("manifest", {}).get("path"))) != _canonical(str(args.manifest_v3)):
        raise BridgeFailure("source request does not exactly bind the supplied v3 manifest")
    bridge_path = _absolute(args.bridge_path or Path(__file__))
    bridge_record = _small_record(bridge_path, "ROOT279 v3-to-v2 bridge")
    output_manifest = _absolute(args.manifest_output)
    output_request = _absolute(args.request_output)
    bridged_manifest = copy.deepcopy(manifest)
    bridged_manifest["bridge_source_v6_manifest"] = manifest_record
    bridged_manifest["bridge_source_v6_request"] = request_record
    bridged_manifest["bridge_projection"] = {"schema": BRIDGE_SCHEMA, "target_schema": V2_SCHEMA, "axis_gate": checked["axis_gate"], "payload_read_by_bridge": False, "production_credit": 0}
    bridged_manifest["status"] = "WAITING_ROOT279_V3_TO_V2_AXIS_PREFLIGHT"
    _write_once(output_manifest, bridged_manifest)
    output_manifest_record = _small_record(output_manifest, "ROOT279 v7 stable v3 manifest")
    value = copy.deepcopy(request)
    value["status"] = "WAITING_ROOT279_V3_TO_V2_AXIS_PREFLIGHT"
    value["variant_schema"] = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v7-root310-bridge"
    value["request_builder_variant"] = BUILDER_VARIANT
    value["execution_allowed"] = False
    value["launch_disabled"] = True
    value["solver_started"] = False
    value["native_payload_read"] = False
    value["ledger_mutation"] = False
    value["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
    value["manifest"] = output_manifest_record
    value["command"] = [str(PYTHON), str(bridge_path), "--run", "--manifest-v3", str(output_manifest), "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_root279_root310_native_observer_v7.json", "--guard", str(V2_GUARD), "--v1-worker", str(V1_WORKER), "--python", str(PYTHON), "--cwd", str(_absolute(args.cwd)), "--max-scratch-bytes", "268435456", "--max-log-bytes", "1048576", "--timeout-seconds", "1800"]
    value["input_files"] = list(dict.fromkeys([*value.get("input_files", []), str(output_manifest), str(bridge_path), str(request_record["path"])]))
    records = dict(value.get("input_records") or {})
    records[str(output_manifest)] = output_manifest_record
    records[str(bridge_path)] = bridge_record
    records[str(request_record["path"])] = request_record
    value["input_records"] = records
    value["input_sha256"] = dict(value.get("input_sha256") or {})
    value["input_sha256"].update({str(output_manifest): output_manifest_record["sha256"], str(bridge_path): bridge_record["sha256"], str(request_record["path"]): request_record["sha256"]})
    value.setdefault("runtime_closure", {})["v3_to_v2_bridge"] = str(bridge_path)
    value["runtime_closure"]["v3_manifest_source"] = str(output_manifest)
    value["runtime_closure"]["old_guard_schema"] = V2_SCHEMA
    value["source_binding"] = dict(value.get("source_binding") or {})
    value["source_binding"]["root279_v6_source_request"] = request_record
    value["source_binding"]["root310_v3_to_v2_axis_gate"] = checked["axis_gate"]
    value["source_binding"]["interpolation"] = "FORBIDDEN"
    value["source_binding"]["world_axis"] = "UNKNOWN"
    _write_once(output_request, value)
    return {"schema": BRIDGE_SCHEMA, "status": value["status"], "manifest": output_manifest_record, "request": _small_record(output_request, "ROOT279 v7 request"), "source_v6_manifest": manifest_record, "source_v6_request": request_record, "axis_gate": checked["axis_gate"], "input_file_count": len(value["input_files"]), "native_payload_read": False, "production_credit": 0, "scientific_qualification": value["scientific_qualification"]}


def _self_test() -> None:
    guard = _load_module(V2_GUARD, "root279_bridge_selftest_guard")
    guard._configure()
    with tempfile.TemporaryDirectory(prefix="root279-v3-bridge-selftest-") as directory:
        root = Path(directory)
        v2_path, worker = guard.V4._fixture_manifest(root / "seed")
        v2_doc = json.loads(v2_path.read_text(encoding="utf-8"))
        v3_doc = _fixture_v3(v2_doc, worker)
        checked = validate_v3_manifest(v3_doc)
        if checked["deferred_count"] != EXPECTED_DEFERRED or not checked["axis_gate"]["status"].startswith("READY"):
            raise BridgeFailure("v3 fixture did not validate")
        projected = project_v3_to_v2(v3_doc)
        if projected["schema"] != V2_SCHEMA:
            raise BridgeFailure("projection did not produce V2 schema")
        guard._configure()
        if len(guard.V4._load_deferred(projected)) != EXPECTED_DEFERRED:
            raise BridgeFailure("old guard did not consume projected ten-record manifest")
        _run_old_guard_fixture(v3_doc, root)
        try:
            guard.V4._load_deferred(v3_doc)
        except Exception:
            pass
        else:
            raise BridgeFailure("old guard unexpectedly accepted v3 directly")
        bad = copy.deepcopy(v3_doc)
        bad["native_deferred_records"].pop(next(iter(bad["native_deferred_records"])))
        try:
            validate_v3_manifest(bad)
        except BridgeFailure:
            pass
        else:
            raise BridgeFailure("missing deferred record negative fixture was accepted")
    print("PASS_ROOT279_ROOT310_V3_TO_V2_REAL_GUARD_FIXTURE_NO_PRODUCTION_CREDIT")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest-v3", type=Path)
    parser.add_argument("--request-v6", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--bridge-path", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--guard", type=Path, default=V2_GUARD)
    parser.add_argument("--v1-worker", type=Path, default=V1_WORKER)
    parser.add_argument("--python", type=Path, default=PYTHON)
    parser.add_argument("--cwd", type=Path, default=HERE.parents[4])
    parser.add_argument("--max-scratch-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-log-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    args = parser.parse_args()
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.validate:
            if args.manifest_v3 is None or args.request_v6 is None:
                parser.error("--validate requires --manifest-v3 and --request-v6")
            result = _validate_v6(args.manifest_v3, args.request_v6, args.report)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.build_request:
            required = (args.manifest_v3, args.request_v6, args.manifest_output, args.request_output)
            if any(item is None for item in required):
                parser.error("--build-request requires --manifest-v3 --request-v6 --manifest-output --request-output")
            result = _build_request(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.run:
            required = (args.manifest_v3, args.attempt_root, args.output)
            if any(item is None for item in required):
                parser.error("--run requires --manifest-v3 --attempt-root --output")
            return _bridge_run(args)
    except BridgeFailure as exc:
        print(json.dumps({"schema": BRIDGE_SCHEMA, "status": "REJECTED_SOURCE_OR_ABI", "error": str(exc), "native_payload_read": False, "production_credit": 0}, sort_keys=True), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
