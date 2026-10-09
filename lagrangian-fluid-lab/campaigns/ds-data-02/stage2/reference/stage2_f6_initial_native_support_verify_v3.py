#!/usr/bin/env python3
"""Strict additive verifier for the ROOT276 initial-support worker.

The consumed V2 verifier checks that the worker's pre/post records agree with
one another.  This V3 bridge also joins every successful native/VTK record to
the corresponding manifest deferred record: all five stat fields and a
manifest known SHA (when present) must agree.  A successful row without a
known manifest SHA is rejected instead of being silently treated as a source
match.  VTK point counts are recomputed from the typed role counts and the
generated XML; the worker's boolean comparison flags are not trusted alone.

This module never opens a BI4 or VTK payload.  Its self-test invokes the real
V8 worker on its existing tiny fixture and then applies the stricter bridge.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f6_initial_native_support_verify_v2.py"
RESULT_SCHEMA = "ds02.stage2.f6-initial-native-support-verifier.v3"
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_PATH, "stage2_f6_initial_native_support_verify_v2_for_v3")


class VerifyFailure(RuntimeError):
    pass


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(value: Any, label: str) -> dict[str, int]:
    try:
        result = V2._stat_variants(value, label)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    if set(result) != set(STAT_FIELDS):
        raise VerifyFailure(f"{label} is not a complete five-field stat")
    return result


def _path_stat(path: Path, label: str) -> dict[str, int]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file")
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _path(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise VerifyFailure(f"{label} path is missing")
    return str(Path(value).expanduser().absolute())


def _expected_source(case: dict[str, Any], role: str, key: tuple[str, str]) -> tuple[str, dict[str, int], str | None]:
    deferred = case.get("deferred")
    if not isinstance(deferred, dict) or not isinstance(deferred.get(role), dict):
        raise VerifyFailure(f"{key}/{role} manifest deferred record is missing")
    record = deferred[role]
    expected_path = _path(record.get("path"), f"{key}/{role} manifest")
    expected_stat_value = record.get("stat_at_prepare", record.get("stat"))
    expected_stat = _stat(expected_stat_value, f"{key}/{role} manifest stat")
    known = record.get("known_sha256", record.get("sha256"))
    if known in (None, ""):
        known_sha = None
    else:
        known_sha = _digest(known, f"{key}/{role} manifest known SHA")
    return expected_path, expected_stat, known_sha


def _manifest_bridge(manifest: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    top = manifest.get("deferred_input_records")
    if not isinstance(top, list):
        raise VerifyFailure("manifest deferred_input_records is missing")
    top_by_path: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(top):
        if not isinstance(item, dict):
            raise VerifyFailure(f"manifest deferred record {index} is malformed")
        path = _path(item.get("path"), f"manifest deferred record {index}")
        if path in top_by_path:
            raise VerifyFailure(f"manifest deferred path is duplicated: {path}")
        top_by_path[path] = item
    cases = summary["cases"]
    known = 0
    records = 0
    for key, case in cases.items():
        for role in ("native_bi4", "fluid_vtk", "bound_vtk"):
            expected_path, expected_stat, known_sha = _expected_source(case, role, key)
            top_record = top_by_path.get(expected_path)
            if top_record is None:
                raise VerifyFailure(f"{key}/{role} is absent from top-level manifest deferred records")
            top_stat = _stat(top_record.get("stat_at_prepare", top_record.get("stat")),
                             f"{key}/{role} top-level manifest stat")
            if top_stat != expected_stat:
                raise VerifyFailure(f"{key}/{role} top-level stat differs from case manifest stat")
            top_known = top_record.get("known_sha256", top_record.get("sha256"))
            if known_sha is None:
                if top_known not in (None, ""):
                    raise VerifyFailure(f"{key}/{role} top-level known SHA is not mirrored in the case record")
            elif _digest(top_known, f"{key}/{role} top-level known SHA") != known_sha:
                raise VerifyFailure(f"{key}/{role} top-level known SHA differs from case manifest")
            records += 1
            known += int(known_sha is not None)
    if set(top_by_path) != { _path(case["deferred"][role]["path"], f"{key}/{role}")
                             for key, case in cases.items()
                             for role in ("native_bi4", "fluid_vtk", "bound_vtk") }:
        raise VerifyFailure("top-level manifest deferred paths do not exactly match case records")
    return {"deferred_records": records, "deferred_records_with_known_sha": known,
            "all_deferred_stats_complete": True,
            "pass_rows_require_known_sha": True}


def _strict_guard_record(record: dict[str, Any], case: dict[str, Any], role: str,
                        key: tuple[str, str], *, source_record: bool = False) -> None:
    expected_path, expected_stat, known_sha = _expected_source(case, role, key)
    actual_path = _path(record.get("path"), f"{key}/{role} worker")
    if actual_path != expected_path:
        raise VerifyFailure(f"{key}/{role} worker path is not the manifest source")
    if known_sha is None:
        raise VerifyFailure(f"{key}/{role} PASS row has no manifest known SHA")
    actual_sha = _digest(record.get("sha256"), f"{key}/{role} worker SHA")
    if actual_sha != known_sha:
        raise VerifyFailure(f"{key}/{role} worker SHA differs from manifest known SHA")
    before = _stat(record.get("stat_before"), f"{key}/{role} worker stat_before")
    after = _stat(record.get("stat_after"), f"{key}/{role} worker stat_after")
    if before != after:
        raise VerifyFailure(f"{key}/{role} worker pre/post stat differs")
    current = record.get("current_stat", record.get("stat_after"))
    if _stat(current, f"{key}/{role} worker current stat") != after:
        raise VerifyFailure(f"{key}/{role} worker current stat differs from post stat")
    if after != expected_stat:
        raise VerifyFailure(f"{key}/{role} worker full stat differs from manifest")
    source_path = Path(expected_path)
    if _path_stat(source_path, f"{key}/{role} current source") != expected_stat:
        raise VerifyFailure(f"{key}/{role} current source stat differs from manifest")
    if int(record.get("bytes", after["bytes"])) != after["bytes"]:
        raise VerifyFailure(f"{key}/{role} worker byte count differs from full stat")
    if source_record and record.get("pre_sha256") is not None and _digest(record["pre_sha256"], f"{key}/{role} worker pre SHA") != actual_sha:
        raise VerifyFailure(f"{key}/{role} worker pre SHA differs from post SHA")
    if source_record and record.get("post_sha256") is not None and _digest(record["post_sha256"], f"{key}/{role} worker post SHA") != actual_sha:
        raise VerifyFailure(f"{key}/{role} worker post SHA differs from output SHA")


def _strict_output(output: dict[str, Any], summary: dict[str, Any]) -> dict[str, int]:
    rows = V2._result_map(output)
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for key, row in rows.items():
        status = row.get("status")
        if isinstance(status, str) and status.startswith("PASS_CASE_INITIAL_SUPPORT"):
            counts["PASS"] += 1
            case = summary["cases"][key]
            producer = row.get("producer")
            if not isinstance(producer, dict):
                raise VerifyFailure(f"{key} PASS row lacks producer record")
            native = producer.get("native_bi4")
            if not isinstance(native, dict):
                raise VerifyFailure(f"{key} PASS row lacks native BI4 record")
            _strict_guard_record(native, case, "native_bi4", key, source_record=True)
            vtk = row.get("vtk")
            if not isinstance(vtk, dict):
                raise VerifyFailure(f"{key} PASS row lacks VTK record")
            for role in ("fluid_vtk", "bound_vtk"):
                entry = vtk.get(role)
                if not isinstance(entry, dict) or not isinstance(entry.get("source_record"), dict):
                    raise VerifyFailure(f"{key}/{role} PASS row lacks source record")
                _strict_guard_record(entry["source_record"], case, role, key, source_record=True)
            role_counts = row.get("typed_role_counts")
            if not isinstance(role_counts, dict):
                raise VerifyFailure(f"{key} PASS row lacks typed role counts")
            fluid = int(role_counts.get("fluid", -1))
            bound = sum(int(role_counts.get(name, 0)) for name in ("fixed", "moving", "floating"))
            if fluid < 0 or bound < 0:
                raise VerifyFailure(f"{key} typed role counts are invalid")
            receipt, _ = V2._verify_receipt(case, key)
            xml_root, _ = V2._verify_xml_record(case, receipt, key)
            xml_counts = V2._xml_role_counts(xml_root, key)
            if fluid != xml_counts["fluid"] or bound != xml_counts["bound"]:
                raise VerifyFailure(f"{key} typed role counts do not match generated XML counts")
            if not isinstance(vtk["fluid_vtk"].get("point_count"), int) or vtk["fluid_vtk"]["point_count"] != fluid:
                raise VerifyFailure(f"{key} Fluid.vtk point count is not the typed fluid count")
            if not isinstance(vtk["bound_vtk"].get("point_count"), int) or vtk["bound_vtk"]["point_count"] != bound:
                raise VerifyFailure(f"{key} Bound.vtk point count is not the typed bound count")
            comparison = row.get("vtk_comparison")
            if not isinstance(comparison, dict):
                raise VerifyFailure(f"{key} VTK comparison is missing")
            if comparison.get("fluid_count_matches_native") is not (vtk["fluid_vtk"]["point_count"] == fluid):
                raise VerifyFailure(f"{key} Fluid.vtk comparison flag is inconsistent")
            if comparison.get("bound_count_matches_native_nonfluid") is not (vtk["bound_vtk"]["point_count"] == bound):
                raise VerifyFailure(f"{key} Bound.vtk comparison flag is inconsistent")
        elif isinstance(status, str) and status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
        elif isinstance(status, str) and status.startswith("FAILED"):
            counts["FAILED"] += 1
        else:
            raise VerifyFailure(f"{key} has unclassified status {status!r}")
    declared = output.get("case_counts")
    if not isinstance(declared, dict) or {name: int(declared.get(name, -1)) for name in counts} != counts:
        raise VerifyFailure(f"worker case_counts do not preserve strict outcomes: {declared}")
    return counts


def verify(manifest_path: Path, output_path: Path | None = None, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, _ = V2._stable_json(manifest_path, "ROOT276 V8 manifest")
    try:
        summary = V2._verify_manifest(manifest)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    bridge = _manifest_bridge(manifest, summary)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED_ROOT276_V8_MANIFEST_STRICT_V3",
        "manifest": {"path": str(Path(manifest_path).expanduser().absolute())},
        "manifest_summary": {"cases": len(summary["cases"]), "direct": summary["direct"], "bridge": summary["bridge"], "deferred": summary["deferred"]},
        "strict_source_bridge": bridge,
        "worker_output": None,
        "scientific_qualification": V2.QUALIFICATION,
        "read_scope": {"manifest_output_json_only": True, "native_bi4_read": False, "vtk_read": False, "solver_launch": False},
    }
    if output_path is not None:
        output, output_record = V2._stable_json(output_path, "ROOT276 V8 worker output")
        # Run the consumed V2 checks first; V3 is an additive stricter layer.
        try:
            V2._verify_output(output, summary)
        except Exception as exc:
            raise VerifyFailure(str(exc)) from exc
        result["worker_output"] = {"record": output_record, "case_counts": _strict_output(output, summary)}
        result["status"] = "VERIFIED_ROOT276_V8_MANIFEST_AND_WORKER_RECORDS_STRICT_V3"
    if verification_output is not None:
        V2._write_once(verification_output, result)
    return result


def self_test() -> None:
    v5 = V2._load(V2.V5_WORKER, "root276_v5_fixture_v3")
    v8 = V2._load(V2.V8_WORKER, "root276_v8_worker_v3")
    with tempfile.TemporaryDirectory(prefix="root276-v3-e2e-") as directory:
        root = Path(directory)
        source_manifest, attempt, _ = v5._fixture_manifest(root / "v5")
        manifest = V2._v8_fixture_manifest(v5, root, source_manifest)
        output = root / "attempt" / "observer" / "v8.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        v8.run(manifest, root / "attempt", output)
        result = verify(manifest, output)
        assert result["worker_output"]["case_counts"] == {"PASS": 6, "UNKNOWN": 0, "FAILED": 0}
        broken_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        broken_manifest["cases"][0]["deferred"]["fluid_vtk"]["stat_at_prepare"]["bytes"] += 1
        broken_manifest_path = root / "broken-manifest.json"
        broken_manifest_path.write_text(json.dumps(broken_manifest), encoding="utf-8")
        try:
            verify(broken_manifest_path, output)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("manifest full-stat mutation was accepted")
        broken_output = json.loads(output.read_text(encoding="utf-8"))
        broken_output["cases"][0]["vtk"]["fluid_vtk"]["point_count"] += 1
        broken_output_path = root / "broken-output.json"
        broken_output_path.write_text(json.dumps(broken_output), encoding="utf-8")
        try:
            verify(manifest, broken_output_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("VTK point-count mutation was accepted")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V3_STRICT_E2E_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V3_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None:
        parser.error("--verify requires --manifest")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V3: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "scientific_credit": 0,
                      "manifest_summary": result["manifest_summary"],
                      "worker_output": result["worker_output"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
