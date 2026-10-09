#!/usr/bin/env python3
"""Independently verify a completed ROOT279 pair report from metadata only.

The ROOT279 guarded worker is the only component allowed to open the ten
native Part files.  This verifier checks the resulting wrapper/child/common
JSON, the exact ten source SHA/stat records, the ROOT310 snapshot aggregate,
and the ROOT277/278 request/receipt source closure.  It never opens a native,
VTK, HDF5, or solver payload and never infers a field from XML mass.  Bracket
values at 0, .25, and .5 seconds remain observations; no interpolation,
integrator truth, or scientific qualification is assigned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f1-s2.root279-pair-report-verifier.v1"
COMMON_SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-observer.v1"
PAIR_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
REQUEST_SCHEMA = "ds02.stage2.f1-s2.root279-pair-native-observer-request.v3"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
QUERY_TIMES = (0.0, 0.25, 0.5)
MODES = ("same_cfl", "half_cfl")
EXPECTED_NATIVE_COUNT = 10
SMALL_CAP = 64 * 1024 * 1024
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
UNKNOWN = "UNKNOWN"


class VerificationFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerificationFailure("source record lacks a concrete SHA-256")
    return value.lower()


def _read_json(path: Path, label: str, *, expected: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerificationFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise VerificationFailure(f"{label} exceeds bounded JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerificationFailure(f"{label} changed during read: {path}")
    if expected is not None:
        declared = _digest(expected.get("sha256"))
        if declared != _sha(raw):
            raise VerificationFailure(f"{label} SHA differs from its bound record")
        _check_stat(after, expected.get("stat") or expected.get("stat_after"), label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after}


def _check_stat(actual: dict[str, int], declared: Any, label: str) -> None:
    if not isinstance(declared, dict):
        raise VerificationFailure(f"{label} has no complete stat record")
    aliases = {"device": ("device", "dev", "st_dev"), "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    expected: dict[str, int] = {}
    for field, names in aliases.items():
        for name in names:
            if name in declared:
                expected[field] = int(declared[name]); break
        if field not in expected:
            raise VerificationFailure(f"{label} stat misses {field}")
    if any(actual[field] != expected[field] for field in STAT_FIELDS):
        raise VerificationFailure(f"{label} current stat differs from bound stat")


def _record_from_manifest(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerificationFailure(f"{label} lacks a path record")
    path = _absolute(Path(value["path"]))
    if not path.is_file() or path.is_symlink():
        raise VerificationFailure(f"{label} path is absent or symlinked: {path}")
    current = _stat(path)
    _check_stat(current, value.get("stat") or value.get("stat_after") or value.get("stat_at_prepare"), label)
    bound_sha = value.get("sha256")
    if isinstance(bound_sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", bound_sha):
        # The verifier deliberately does not hash native payloads.  Small
        # JSON source records are checked by _read_json at their boundary.
        pass
    return {"path": str(path), "stat": current,
            "sha256": bound_sha.lower() if isinstance(bound_sha, str) and len(bound_sha) == 64 else None}


def _verify_snapshot(snapshot_path: Path, selected_paths: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    snapshot, record = _read_json(snapshot_path, "ROOT310 native source snapshot")
    if snapshot.get("schema") != SNAPSHOT_SCHEMA or snapshot.get("status") != SNAPSHOT_STATUS:
        raise VerificationFailure("snapshot schema/status is not completed v2")
    scope = snapshot.get("worker_scope")
    if not isinstance(scope, dict) or scope.get("bi4_decode") is not False or scope.get("solver_launch") is not False:
        raise VerificationFailure("snapshot scope permits decode or solver launch")
    entries = snapshot.get("requests")
    if not isinstance(entries, list) or not entries:
        raise VerificationFailure("snapshot has no request entries")
    by_path: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for entry in entries:
        files = entry.get("selected_native_files") if isinstance(entry, dict) else None
        if not isinstance(files, list):
            raise VerificationFailure("snapshot request lacks selected_native_files")
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise VerificationFailure("snapshot selected file lacks path")
            path = str(_absolute(Path(item["path"])))
            if path in by_path:
                raise VerificationFailure("snapshot contains duplicate native path")
            digest = _digest(item.get("sha256"))
            if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
                raise VerificationFailure("snapshot file lacks concrete bytes")
            before = item.get("stat_before"); after = item.get("stat_after")
            _check_stat_aliases_equal(before, after, f"snapshot {path}")
            if int(item["bytes"]) != int(after.get("bytes", after.get("size", -1))):
                raise VerificationFailure(f"snapshot {path} byte count disagrees with stat")
            if item.get("stat_consistency") != "PASS_PRE_POST_IDENTICAL":
                raise VerificationFailure(f"snapshot {path} is not pre/post stable")
            normalized = {"path": path, "frame": item.get("frame"), "sha256": digest,
                          "bytes": int(item["bytes"]), "stat_before": before, "stat_after": after}
            by_path[path] = normalized; ordered.append(normalized)
    if set(by_path) != selected_paths:
        raise VerificationFailure("snapshot path set differs from the ten pair paths")
    immutable = snapshot.get("immutable_source_sha_list")
    expected_items = [{"frame": item["frame"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in ordered]
    if immutable != expected_items:
        raise VerificationFailure("snapshot immutable source list differs from selected records")
    expected_digest = _sha(json.dumps(expected_items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    if snapshot.get("source_sha_list_digest") != expected_digest:
        raise VerificationFailure("snapshot aggregate SHA differs")
    if snapshot.get("selected_native_total_bytes") != sum(item["bytes"] for item in expected_items):
        raise VerificationFailure("snapshot aggregate byte count differs")
    return by_path, record


def _check_stat_aliases_equal(before: Any, after: Any, label: str) -> None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise VerificationFailure(f"{label} lacks stat_before/stat_after")
    aliases = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    for key in aliases:
        if key not in before or key not in after or int(before[key]) != int(after[key]):
            raise VerificationFailure(f"{label} stat {key} changed or is absent")


def _validate_pair_manifest(pair: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    if pair.get("schema") != PAIR_SCHEMA or not str(pair.get("status", "")).startswith("PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3"):
        raise VerificationFailure("ROOT279 pair manifest schema/status mismatch")
    cases = pair.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise VerificationFailure("ROOT279 pair manifest needs same/half cases")
    paths: set[str] = set()
    labels: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("label") not in MODES:
            raise VerificationFailure("ROOT279 pair case label is invalid")
        label = str(case["label"])
        if label in labels:
            raise VerificationFailure("ROOT279 pair has duplicate mode")
        labels.add(label)
        selected = case.get("selected_native_frame_metadata")
        if not isinstance(selected, list) or len(selected) != 5:
            raise VerificationFailure(f"ROOT279 {label} case does not contain five selected frames")
        for item in selected:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise VerificationFailure(f"ROOT279 {label} selected frame lacks path")
            path = str(_absolute(Path(item["path"])))
            if path in paths:
                raise VerificationFailure("ROOT279 pair selected native paths are not unique")
            paths.add(path)
            _digest(item.get("known_sha256"))
            stat = item.get("stat_at_prepare") or item.get("stat")
            if not isinstance(stat, dict):
                raise VerificationFailure(f"ROOT279 {label} selected frame lacks stat")
            if not set(STAT_FIELDS).issubset(set(stat) | {"device", "inode"}):
                # V3 records use device/inode; the alias check below is the
                # actual completeness requirement.
                raise VerificationFailure(f"ROOT279 {label} selected frame stat incomplete")
    if labels != set(MODES) or len(paths) != EXPECTED_NATIVE_COUNT:
        raise VerificationFailure("ROOT279 pair selected native cardinality is not ten")
    return pair, paths


def _verify_guard_result(guard: dict[str, Any], snapshot: dict[str, dict[str, Any]], pair_paths: set[str]) -> None:
    if not str(guard.get("status", "")).startswith("PASS"):
        raise VerificationFailure("ROOT279 guarded result is not PASS")
    if (guard.get("scope") or {}).get("deferred_native_count") != EXPECTED_NATIVE_COUNT:
        raise VerificationFailure("ROOT279 guard does not report ten native inputs")
    integrity = guard.get("source_integrity")
    pre = integrity.get("pre") if isinstance(integrity, dict) else None
    post = integrity.get("post") if isinstance(integrity, dict) else None
    if not isinstance(pre, list) or not isinstance(post, list) or pre != post or len(pre) != EXPECTED_NATIVE_COUNT:
        raise VerificationFailure("ROOT279 source pre/post integrity is incomplete")
    if not isinstance(integrity.get("pre_post_exact_sha_and_stat"), bool) or integrity["pre_post_exact_sha_and_stat"] is not True:
        raise VerificationFailure("ROOT279 guard did not close pre/post source identity")
    guard_paths: set[str] = set()
    for item in pre:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise VerificationFailure("ROOT279 guard source record lacks path")
        path = str(_absolute(Path(item["path"])))
        guard_paths.add(path); guard_sha = _digest(item.get("sha256"))
        guard_stat = item.get("stat") if isinstance(item.get("stat"), dict) else {}
        _check_stat(guard_stat, guard_stat, "ROOT279 guard source")
        source = snapshot.get(path)
        if not isinstance(source, dict) or guard_sha != source["sha256"]:
            raise VerificationFailure("ROOT279 guard SHA differs from snapshot source")
        source_stat = source["stat_after"]
        aliases = {"device": source_stat["st_dev"], "inode": source_stat["st_ino"],
                   "bytes": source_stat["bytes"], "mtime_ns": source_stat["mtime_ns"],
                   "ctime_ns": source_stat["ctime_ns"]}
        if any(int(guard_stat[field]) != int(value) for field, value in aliases.items()):
            raise VerificationFailure("ROOT279 guard stat differs from snapshot source")
    if guard_paths != pair_paths or set(snapshot) != pair_paths:
        raise VerificationFailure("ROOT279 guard source paths differ from pair/snapshot")


def _verify_child(child: dict[str, Any]) -> None:
    if not str(child.get("schema", "")).startswith("ds02.stage2.f1.native-selected-observer") or str(child.get("status", "")).startswith("FAILED"):
        raise VerificationFailure("ROOT279 child report is not a successful native observer report")
    cases = child.get("cases")
    if not isinstance(cases, list) or {row.get("label") for row in cases if isinstance(row, dict)} != set(MODES):
        raise VerificationFailure("ROOT279 child report case set is incomplete")
    for case in cases:
        observations = case.get("selected_observations")
        if not isinstance(observations, list) or len(observations) != 5:
            raise VerificationFailure("ROOT279 child selected observation count is not five")
        time = case.get("time")
        if not isinstance(time, dict) or time.get("interpolation") in (True, "INTERPOLATED", "linear"):
            raise VerificationFailure("ROOT279 child permits interpolation")
        queries = time.get("queries")
        if not isinstance(queries, list) or [float(q.get("query_time_s")) for q in queries] != list(QUERY_TIMES):
            raise VerificationFailure("ROOT279 child query times are not 0/.25/.5")
        for row in observations:
            header = row.get("native_header")
            if not isinstance(header, dict):
                raise VerificationFailure("ROOT279 observation lacks native header record")
            observables = row.get("observables")
            if observables:
                fluid = observables.get("fluid_observable_using_native_MassFluid")
                if not isinstance(fluid, dict) or "native" not in str(fluid.get("mass_semantics", "")).lower():
                    raise VerificationFailure("ROOT279 observable is not native-MassFluid weighted")


def verify(common_manifest_path: Path, common_output_path: Path, pair_manifest_path: Path,
           pair_request_path: Path, snapshot_path: Path, guard_result_path: Path,
           child_report_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    common_manifest, common_manifest_record = _read_json(common_manifest_path, "ROOT279 common manifest")
    if common_manifest.get("schema") != "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1":
        raise VerificationFailure("common manifest schema mismatch")
    if common_manifest.get("query_times_s") != list(QUERY_TIMES):
        raise VerificationFailure("common manifest query times mismatch")
    policy = common_manifest.get("query_policy") or {}
    if policy.get("interpolation") is not False or policy.get("extrapolation") is not False:
        raise VerificationFailure("common manifest permits interpolation")
    common_output, common_output_record = _read_json(common_output_path, "ROOT279 common output")
    if common_output.get("schema") != COMMON_SCHEMA or not str(common_output.get("status", "")).startswith("COMPLETE_"):
        raise VerificationFailure("common output schema/status mismatch")
    if common_output.get("queries") != list(QUERY_TIMES):
        raise VerificationFailure("common output query times mismatch")
    output_sources = common_output.get("source")
    if not isinstance(output_sources, dict):
        raise VerificationFailure("common output does not carry source report closure")
    qualification = common_output.get("scientific_qualification") or {}
    if any(qualification.get(key) != UNKNOWN for key in ("QI", "QN", "QE")) or qualification.get("credit", 0) != 0:
        raise VerificationFailure("common output advertises scientific credit")
    pair, pair_paths = _validate_pair_manifest(_read_json(pair_manifest_path, "ROOT279 pair manifest")[0])
    request, request_record = _read_json(pair_request_path, "ROOT279 pair request")
    if request.get("schema") != "ds02.request.v1" or "root279" not in str(request.get("variant_schema", "")).lower():
        raise VerificationFailure("ROOT279 pair request schema mismatch")
    input_files = request.get("input_files")
    input_records = request.get("input_records")
    input_sha = request.get("input_sha256")
    if not isinstance(input_files, list) or not isinstance(input_records, dict) or not isinstance(input_sha, dict):
        raise VerificationFailure("ROOT279 request lacks its static source closure")
    for item in input_files:
        if not isinstance(item, str) or item not in input_records or item not in input_sha:
            raise VerificationFailure("ROOT279 request static input closure is incomplete")
        record = input_records[item]
        if not isinstance(record, dict) or _digest(record.get("sha256")) != _digest(input_sha[item]):
            raise VerificationFailure("ROOT279 request static input SHA join failed")
        _record_from_manifest(record, "ROOT279 static source")
    deferred = request.get("deferred_input_records")
    if not isinstance(deferred, list) or len(deferred) != EXPECTED_NATIVE_COUNT:
        raise VerificationFailure("ROOT279 pair request does not contain ten deferred records")
    deferred_paths = set()
    for item in deferred:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise VerificationFailure("ROOT279 deferred record lacks path")
        path = str(_absolute(Path(item["path"]))); deferred_paths.add(path); _digest(item.get("known_sha256", item.get("sha256")))
        stat = item.get("stat_at_prepare") or item.get("stat")
        if not isinstance(stat, dict):
            raise VerificationFailure("ROOT279 deferred record lacks stat")
    if deferred_paths != pair_paths:
        raise VerificationFailure("ROOT279 request/manifest deferred paths differ")
    snapshot, snapshot_record = _verify_snapshot(snapshot_path, pair_paths)
    for case in pair.get("cases", []):
        for item in case["selected_native_frame_metadata"]:
            path = str(_absolute(Path(item["path"])))
            source = snapshot[path]
            if _digest(item.get("known_sha256")) != source["sha256"]:
                raise VerificationFailure("ROOT279 pair manifest SHA differs from snapshot")
            stat = item.get("stat_at_prepare") or item.get("stat")
            normalized = {"device": stat.get("device", stat.get("st_dev")),
                          "inode": stat.get("inode", stat.get("st_ino")),
                          "bytes": stat.get("bytes"), "mtime_ns": stat.get("mtime_ns"),
                          "ctime_ns": stat.get("ctime_ns")}
            source_stat = source["stat_after"]
            if any(int(normalized[field]) != int(source_stat["st_dev" if field == "device" else "st_ino" if field == "inode" else field]) for field in STAT_FIELDS):
                raise VerificationFailure("ROOT279 pair manifest stat differs from snapshot")
    guard, guard_record = _read_json(guard_result_path, "ROOT279 guarded result")
    _verify_guard_result(guard, snapshot, pair_paths)
    child, child_record = _read_json(child_report_path, "ROOT279 child report")
    _verify_child(child)
    common_sources = common_manifest.get("sources")
    if not isinstance(common_sources, dict):
        raise VerificationFailure("common manifest source records are absent")
    for key, expected_path in (("root279_manifest", pair_manifest_path), ("root279_guard_result", guard_result_path), ("root279_child_report", child_report_path)):
        source = common_sources.get(key)
        if not isinstance(source, dict) or str(_absolute(Path(source.get("path", "")))) != str(_absolute(expected_path)):
            raise VerificationFailure(f"common source record {key} does not point at actual input")
        _read_json(expected_path, f"common source {key}", expected=source)
        output_source = output_sources.get("root279_guard_result" if key == "root279_guard_result" else "root279_child_report")
        if key != "root279_manifest":
            if not isinstance(output_source, dict) or str(_absolute(Path(output_source.get("path", "")))) != str(_absolute(expected_path)):
                raise VerificationFailure(f"common output source closure {key} does not match actual input")
            if "sha256" in output_source or "stat" in output_source:
                _read_json(expected_path, f"common output source {key}", expected=output_source)
    result = {"schema": SCHEMA, "status": "VERIFIED_ROOT279_PAIR_REPORT_METADATA_ONLY",
              "sources": {"common_manifest": common_manifest_record, "common_output": common_output_record,
                          "pair_manifest": {"path": str(_absolute(pair_manifest_path))},
                          "pair_request": request_record, "snapshot": snapshot_record,
                          "guard_result": guard_record, "child_report": child_record},
              "selected_native_count": EXPECTED_NATIVE_COUNT,
              "queries_s": list(QUERY_TIMES), "interpolation": False,
              "native_mass_policy": "MassFluid-only when present; XML fallback forbidden",
              "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "credit": 0},
              "read_scope": {"native_payload_read": False, "vtk_read": False, "hdf5_read": False,
                             "native_sha_stat_source_only": True, "solver_launch": False}}
    if verification_output is not None:
        path = _absolute(verification_output)
        if path.exists() or path.is_symlink():
            raise VerificationFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """Build only tiny metadata files; no observer/decoder is executed."""
    files: list[dict[str, Any]] = []
    for mode in MODES:
        for frame in range(5):
            path = root / mode / f"Part_{frame:04d}.bi4"; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture-{mode}-{frame}".encode())
            stat = _stat(path); digest = _sha(path.read_bytes())
            snap_stat = {"bytes": stat["bytes"], "mtime_ns": stat["mtime_ns"], "ctime_ns": stat["ctime_ns"], "st_dev": stat["device"], "st_ino": stat["inode"]}
            files.append({"path": str(path), "frame": frame, "sha256": digest, "bytes": stat["bytes"], "stat_before": snap_stat, "stat_after": snap_stat, "stat_consistency": "PASS_PRE_POST_IDENTICAL"})
    immutable = [{"frame": item["frame"], "path": str(_absolute(Path(item["path"]))), "bytes": item["bytes"], "sha256": item["sha256"]} for item in files]
    snapshot = {"schema": SNAPSHOT_SCHEMA, "status": SNAPSHOT_STATUS, "worker_scope": {"bi4_decode": False, "solver_launch": False}, "requests": [{"selected_native_files": files[:5]}, {"selected_native_files": files[5:]}], "immutable_source_sha_list": immutable, "source_sha_list_digest": _sha(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()), "selected_native_total_bytes": sum(item["bytes"] for item in files)}
    snapshot_path = root / "snapshot.json"; snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    selected = [{"path": item["path"], "frame": item["frame"], "known_sha256": item["sha256"], "bytes": item["bytes"], "stat_at_prepare": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]}} for item in files]
    cases = [{"label": mode, "selected_native_frame_metadata": selected[index * 5:(index + 1) * 5]} for index, mode in enumerate(MODES)]
    pair = {"schema": PAIR_SCHEMA, "status": "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT", "cases": cases}
    pair_path = root / "pair.json"; pair_path.write_text(json.dumps(pair), encoding="utf-8")
    static_source = root / "static-source.json"; static_source.write_text("{}\n", encoding="utf-8")
    static_record = {"path": str(static_source), "sha256": _sha(static_source.read_bytes()), "stat": _stat(static_source)}
    request = {"schema": "ds02.request.v1", "variant_schema": REQUEST_SCHEMA,
               "input_files": [str(static_source)], "input_sha256": {str(static_source): static_record["sha256"]},
               "input_records": {str(static_source): static_record}, "deferred_input_records": selected}
    request_path = root / "request.json"; request_path.write_text(json.dumps(request), encoding="utf-8")
    pre = [{"path": item["path"], "frame": item["frame"], "sha256": item["sha256"], "stat": {"device": item["stat_after"]["st_dev"], "inode": item["stat_after"]["st_ino"], "bytes": item["bytes"], "mtime_ns": item["stat_after"]["mtime_ns"], "ctime_ns": item["stat_after"]["ctime_ns"]}} for item in files]
    guard = {"schema": "ds02.stage2.f1-s2.root279-native-observer-guarded.v1", "status": "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES", "scope": {"deferred_native_count": 10}, "source_integrity": {"pre": pre, "post": pre, "pre_post_exact_sha_and_stat": True}}
    guard_path = root / "guard.json"; guard_path.write_text(json.dumps(guard), encoding="utf-8")
    child_cases = []
    brackets = [{"query_time_s": time, "lower_frame": frame, "upper_frame": frame, "lower_time_s": time, "upper_time_s": time} for time, frame in zip(QUERY_TIMES, (0, 1, 2))]
    for mode in MODES:
        child_cases.append({"label": mode, "time": {"queries": brackets, "interpolation": "NOT_PERFORMED"}, "selected_observations": [{"frame": frame, "native_header": {"MassFluid": {"value": 1.0}}, "observables": {"fluid_observable_using_native_MassFluid": {"mass_semantics": "native MassFluid"}}} for frame in range(5)]})
    child = {"schema": "ds02.stage2.f1.native-selected-observer.v1", "status": "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES", "cases": child_cases}
    child_path = root / "child.json"; child_path.write_text(json.dumps(child), encoding="utf-8")
    common_manifest = {"schema": "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1", "query_times_s": list(QUERY_TIMES), "query_policy": {"interpolation": False, "extrapolation": False}, "sources": {}}
    for key, path in (("root279_manifest", pair_path), ("root279_guard_result", guard_path), ("root279_child_report", child_path)):
        raw = path.read_bytes(); common_manifest["sources"][key] = {"path": str(path), "sha256": _sha(raw), "stat": _stat(path)}
    common_manifest_path = root / "common-manifest.json"; common_manifest_path.write_text(json.dumps(common_manifest), encoding="utf-8")
    common_output = {"schema": COMMON_SCHEMA, "status": "COMPLETE_F1_S2_ROOT279_COMMON_ENDPOINT_DIAGNOSTICS_NO_SCIENTIFIC_Q", "queries": list(QUERY_TIMES), "source": {"root279_guard_result": {"path": str(guard_path), "sha256": _sha(guard_path.read_bytes()), "stat": _stat(guard_path)}, "root279_child_report": {"path": str(child_path), "sha256": _sha(child_path.read_bytes()), "stat": _stat(child_path)}}, "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "credit": 0}}
    common_output_path = root / "common-output.json"; common_output_path.write_text(json.dumps(common_output), encoding="utf-8")
    return common_manifest_path, common_output_path, pair_path, request_path, snapshot_path, guard_path, child_path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-pair-report-verify-") as directory:
        paths = _fixture(Path(directory))
        result = verify(*paths)
        assert result["selected_native_count"] == 10 and result["scientific_qualification"]["credit"] == 0
        bad = json.loads(paths[5].read_text())
        bad["scope"]["deferred_native_count"] = 9
        bad_path = Path(directory) / "bad-guard.json"; bad_path.write_text(json.dumps(bad))
        try:
            verify(paths[0], paths[1], paths[2], paths[3], paths[4], bad_path, paths[6])
        except VerificationFailure:
            pass
        else:
            raise AssertionError("guard count tamper was accepted")
    print("PASS_ROOT279_PAIR_REPORT_METADATA_VERIFIER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--verify", action="store_true")
    for name in ("common-manifest", "common-output", "pair-manifest", "pair-request", "snapshot", "guard-result", "child-report", "verification-output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try: self_test()
        except Exception as exc:
            print(f"FAILED_ROOT279_PAIR_REPORT_METADATA_VERIFIER_SELFTEST: {exc}", file=sys.stderr); return 2
        return 0
    required = (args.common_manifest, args.common_output, args.pair_manifest, args.pair_request, args.snapshot, args.guard_result, args.child_report)
    if any(item is None for item in required):
        parser.error("--verify requires all seven source/report paths")
    try:
        result = verify(*required, args.verification_output)
    except (VerificationFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_PAIR_REPORT_METADATA_VERIFIER: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "selected_native_count": result["selected_native_count"], "scientific_credit": 0}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
