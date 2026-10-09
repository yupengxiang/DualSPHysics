#!/usr/bin/env python3
"""ROOT276 V4 verifier with parent-established source SHA semantics.

V3 deliberately requires a historically pre-bound manifest SHA.  A parent
reservation can instead establish the first source SHA while the worker reads
the deferred file.  This additive V4 keeps V3 unchanged and accepts that
case only when the manifest has no historical SHA, the worker emits concrete
64-hex pre/post and decoder hashes, and every complete stat (manifest,
worker, current path) is equal.  The result records this distinction as
``sourceSHA_basis``; it grants no scientific credit.

The self-test runs the real ROOT276 V8 worker on its tiny fixture with all
deferred historical SHAs removed, then checks missing and placeholder worker
digests.  It does not open production BI4/VTK payloads.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V3_PATH = HERE / "stage2_f6_initial_native_support_verify_v3.py"
RESULT_SCHEMA = "ds02.stage2.f6-initial-native-support-verifier.v4"
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
UNKNOWN_SHA_MARKERS = {None, "", "PARENT_AFTER_RESERVATION_REQUIRED", "PARENT_ESTABLISHED_AFTER_RESERVATION"}
FIRST_ESTABLISHED = "FIRST_ESTABLISHED_IN_THIS_PARENT_NOT_HISTORICALLY_PREBOUND"
HISTORICALLY_PREBOUND = "HISTORICALLY_PREBOUND_MANIFEST_SHA"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load(V3_PATH, "stage2_f6_initial_native_support_verify_v3_for_v4")
V2 = V3.V2


class VerifyFailure(RuntimeError):
    pass


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a concrete SHA-256 digest")
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


def _known_sha(record: dict[str, Any], label: str) -> str | None:
    values = [record.get("known_sha256"), record.get("sha256")]
    concrete = [value for value in values if value not in UNKNOWN_SHA_MARKERS]
    if not concrete:
        return None
    digests = [_digest(value, f"{label} SHA") for value in concrete]
    if len(set(digests)) != 1:
        raise VerifyFailure(f"{label} known SHA fields disagree")
    return digests[0]


def _expected_source(case: dict[str, Any], role: str, key: tuple[str, str]) -> tuple[str, dict[str, int], str | None]:
    deferred = case.get("deferred")
    if not isinstance(deferred, dict) or not isinstance(deferred.get(role), dict):
        raise VerifyFailure(f"{key}/{role} manifest deferred record is missing")
    record = deferred[role]
    expected_path = _path(record.get("path"), f"{key}/{role} manifest")
    expected_stat = _stat(record.get("stat_at_prepare", record.get("stat")), f"{key}/{role} manifest stat")
    return expected_path, expected_stat, _known_sha(record, f"{key}/{role} manifest")


def _normalize_for_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    """Let the consumed V2 structural checks see unknown SHA as absent."""
    value = copy.deepcopy(manifest)
    records: list[dict[str, Any]] = []
    for case in value.get("cases", []):
        if not isinstance(case, dict):
            continue
        deferred = case.get("deferred")
        if isinstance(deferred, dict):
            records.extend(item for item in deferred.values() if isinstance(item, dict))
    top = value.get("deferred_input_records")
    if isinstance(top, list):
        records.extend(item for item in top if isinstance(item, dict))
    for record in records:
        for field in ("known_sha256", "sha256"):
            if record.get(field) in UNKNOWN_SHA_MARKERS:
                record[field] = None
    return value


def _manifest_bridge(manifest: dict[str, Any], summary: dict[str, Any]) -> tuple[dict[str, Any], bool]:
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
    expected_paths: set[str] = set()
    records = known = 0
    any_unknown = False
    for key, case in summary["cases"].items():
        for role in ("native_bi4", "fluid_vtk", "bound_vtk"):
            expected_path, expected_stat, known_sha = _expected_source(case, role, key)
            expected_paths.add(expected_path)
            top_record = top_by_path.get(expected_path)
            if top_record is None:
                raise VerifyFailure(f"{key}/{role} is absent from top-level deferred records")
            top_stat = _stat(top_record.get("stat_at_prepare", top_record.get("stat")), f"{key}/{role} top-level stat")
            if top_stat != expected_stat:
                raise VerifyFailure(f"{key}/{role} top-level stat differs from case manifest")
            top_known = _known_sha(top_record, f"{key}/{role} top-level manifest")
            if top_known != known_sha:
                raise VerifyFailure(f"{key}/{role} top-level SHA differs from case manifest")
            records += 1
            known += int(known_sha is not None)
            any_unknown |= known_sha is None
    if set(top_by_path) != expected_paths:
        raise VerifyFailure("top-level deferred paths do not exactly match case records")
    return {"deferred_records": records, "deferred_records_with_known_sha": known,
            "all_deferred_stats_complete": True,
            "first_parent_established_sha_allowed": any_unknown}, any_unknown


def _strict_guard_record(record: dict[str, Any], case: dict[str, Any], role: str,
                         key: tuple[str, str]) -> None:
    expected_path, expected_stat, known_sha = _expected_source(case, role, key)
    actual_path = _path(record.get("path"), f"{key}/{role} worker")
    if actual_path != expected_path:
        raise VerifyFailure(f"{key}/{role} worker path is not the manifest source")
    actual_sha = _digest(record.get("sha256"), f"{key}/{role} worker SHA")
    if known_sha is not None and actual_sha != known_sha:
        raise VerifyFailure(f"{key}/{role} worker SHA differs from manifest known SHA")
    before = _stat(record.get("stat_before"), f"{key}/{role} worker stat_before")
    after = _stat(record.get("stat_after"), f"{key}/{role} worker stat_after")
    current = _stat(record.get("current_stat", record.get("stat_after")), f"{key}/{role} worker current stat")
    if before != after or current != after or after != expected_stat:
        raise VerifyFailure(f"{key}/{role} worker/manifest full stats do not close")
    if _path_stat(Path(expected_path), f"{key}/{role} current source") != expected_stat:
        raise VerifyFailure(f"{key}/{role} current source stat differs from manifest")
    if int(record.get("bytes", after["bytes"])) != after["bytes"]:
        raise VerifyFailure(f"{key}/{role} worker byte count differs from full stat")
    if role == "native_bi4":
        pre_sha = _digest(record.get("pre_sha256"), f"{key}/{role} worker pre SHA")
        post_sha = _digest(record.get("post_sha256"), f"{key}/{role} worker post SHA")
        decoder_sha = _digest(record.get("decoder_frame_sha256"), f"{key}/{role} decoder SHA")
        if pre_sha != post_sha or post_sha != actual_sha or decoder_sha != actual_sha:
            raise VerifyFailure(f"{key}/{role} decoder/pre/post SHA chain is not closed")
        if int(record.get("decoder_frame_bytes", -1)) != after["bytes"]:
            raise VerifyFailure(f"{key}/{role} decoder byte count differs from source")
    else:
        if record.get("pre_post_sha_equal") is not True:
            raise VerifyFailure(f"{key}/{role} worker did not prove pre/post SHA equality")
        if record.get("pre_sha256") is not None and _digest(record["pre_sha256"], f"{key}/{role} worker pre SHA") != actual_sha:
            raise VerifyFailure(f"{key}/{role} worker pre SHA differs from source SHA")
        if record.get("post_sha256") is not None and _digest(record["post_sha256"], f"{key}/{role} worker post SHA") != actual_sha:
            raise VerifyFailure(f"{key}/{role} worker post SHA differs from source SHA")


def _strict_output(output: dict[str, Any], summary: dict[str, Any], original_manifest: dict[str, Any]) -> tuple[dict[str, int], bool]:
    rows = V2._result_map(output)
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    any_unknown = False
    original_cases = {(case["sentinel_id"], case["grid"]): case for case in original_manifest["cases"]}
    for key, row in rows.items():
        status = row.get("status")
        if isinstance(status, str) and status.startswith("PASS_CASE_INITIAL_SUPPORT"):
            counts["PASS"] += 1
            case = original_cases[key]
            producer = row.get("producer")
            if not isinstance(producer, dict) or not isinstance(producer.get("native_bi4"), dict):
                raise VerifyFailure(f"{key} PASS row lacks native producer record")
            _strict_guard_record(producer["native_bi4"], case, "native_bi4", key)
            vtk = row.get("vtk")
            if not isinstance(vtk, dict):
                raise VerifyFailure(f"{key} PASS row lacks VTK records")
            for role in ("fluid_vtk", "bound_vtk"):
                entry = vtk.get(role)
                if not isinstance(entry, dict) or not isinstance(entry.get("source_record"), dict):
                    raise VerifyFailure(f"{key}/{role} PASS row lacks source record")
                _strict_guard_record(entry["source_record"], case, role, key)
            role_counts = row.get("typed_role_counts")
            if not isinstance(role_counts, dict):
                raise VerifyFailure(f"{key} PASS row lacks typed role counts")
            fluid = int(role_counts.get("fluid", -1))
            bound = sum(int(role_counts.get(name, 0)) for name in ("fixed", "moving", "floating"))
            receipt, _ = V2._verify_receipt(summary["cases"][key], key)
            xml_root, _ = V2._verify_xml_record(summary["cases"][key], receipt, key)
            xml_counts = V2._xml_role_counts(xml_root, key)
            if fluid != xml_counts["fluid"] or bound != xml_counts["bound"]:
                raise VerifyFailure(f"{key} typed role counts do not match generated XML counts")
            if vtk["fluid_vtk"].get("point_count") != fluid or vtk["bound_vtk"].get("point_count") != bound:
                raise VerifyFailure(f"{key} VTK point counts do not match typed/XML role counts")
            comparison = row.get("vtk_comparison")
            if not isinstance(comparison, dict) or comparison.get("fluid_count_matches_native") is not True or comparison.get("bound_count_matches_native_nonfluid") is not True:
                raise VerifyFailure(f"{key} VTK comparison flags are not closed")
            any_unknown |= any(_known_sha(summary["cases"][key]["deferred"][role], f"{key}/{role}") is None for role in ("native_bi4", "fluid_vtk", "bound_vtk"))
        elif isinstance(status, str) and status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
        elif isinstance(status, str) and status.startswith("FAILED"):
            counts["FAILED"] += 1
        else:
            raise VerifyFailure(f"{key} has unclassified status {status!r}")
    declared = output.get("case_counts")
    if not isinstance(declared, dict) or {name: int(declared.get(name, -1)) for name in counts} != counts:
        raise VerifyFailure(f"worker case_counts do not preserve strict outcomes: {declared}")
    return counts, any_unknown


def verify(manifest_path: Path, output_path: Path | None = None, verification_output: Path | None = None) -> dict[str, Any]:
    original_manifest, _ = V2._stable_json(manifest_path, "ROOT276 V8 manifest")
    normalized = _normalize_for_v2(original_manifest)
    try:
        summary = V2._verify_manifest(normalized)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    bridge, manifest_unknown = _manifest_bridge(original_manifest, summary)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED_ROOT276_V8_MANIFEST_PARENT_SHA_BRIDGE_V4",
        "manifest": {"path": str(Path(manifest_path).expanduser().absolute())},
        "manifest_summary": {"cases": len(summary["cases"]), "direct": summary["direct"], "bridge": summary["bridge"], "deferred": summary["deferred"]},
        "strict_source_bridge": bridge,
        "sourceSHA_basis": FIRST_ESTABLISHED if manifest_unknown else HISTORICALLY_PREBOUND,
        "worker_output": None,
        "scientific_qualification": V2.QUALIFICATION,
        "read_scope": {"manifest_output_json_only": True, "native_bi4_read": False, "vtk_read": False, "solver_launch": False},
    }
    if output_path is not None:
        output, output_record = V2._stable_json(output_path, "ROOT276 V8 worker output")
        try:
            V2._verify_output(output, summary)
        except Exception as exc:
            raise VerifyFailure(str(exc)) from exc
        counts, output_unknown = _strict_output(output, summary, original_manifest)
        result["worker_output"] = {"record": output_record, "case_counts": counts}
        result["sourceSHA_basis"] = FIRST_ESTABLISHED if manifest_unknown or output_unknown else HISTORICALLY_PREBOUND
        result["status"] = "VERIFIED_ROOT276_V8_WORKER_PARENT_SHA_BRIDGE_V4"
    if verification_output is not None:
        V2._write_once(verification_output, result)
    return result


def _unknown_manifest(manifest_path: Path) -> None:
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in value["cases"]:
        for record in case["deferred"].values():
            record["known_sha256"] = None
            record["sha256"] = None
    for record in value["deferred_input_records"]:
        record["known_sha256"] = "PARENT_AFTER_RESERVATION_REQUIRED"
        record["sha256"] = "PARENT_AFTER_RESERVATION_REQUIRED"
    manifest_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    v5 = V2._load(V2.V5_WORKER, "root276_v5_fixture_v4")
    v8 = V2._load(V2.V8_WORKER, "root276_v8_worker_v4")
    with tempfile.TemporaryDirectory(prefix="root276-v4-e2e-") as directory:
        root = Path(directory)
        source_manifest, _, _ = v5._fixture_manifest(root / "v5")
        manifest = V2._v8_fixture_manifest(v5, root, source_manifest)
        known_output = root / "known-attempt" / "observer" / "v8.json"
        known_output.parent.mkdir(parents=True, exist_ok=True)
        v8.run(manifest, root / "known-attempt", known_output)
        known_result = verify(manifest, known_output)
        assert known_result["sourceSHA_basis"] == HISTORICALLY_PREBOUND
        _unknown_manifest(manifest)
        output = root / "attempt" / "observer" / "v8.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        v8.run(manifest, root / "attempt", output)
        result = verify(manifest, output)
        assert result["sourceSHA_basis"] == FIRST_ESTABLISHED
        assert result["worker_output"]["case_counts"] == {"PASS": 6, "UNKNOWN": 0, "FAILED": 0}
        for label, replacement in (("missing", None), ("placeholder", "PARENT_AFTER_RESERVATION_REQUIRED")):
            broken = json.loads(output.read_text(encoding="utf-8"))
            broken["cases"][0]["producer"]["native_bi4"]["sha256"] = replacement
            broken_path = root / f"broken-{label}.json"
            broken_path.write_text(json.dumps(broken), encoding="utf-8")
            try:
                verify(manifest, broken_path)
            except VerifyFailure:
                pass
            else:
                raise AssertionError(f"{label} worker digest was accepted")
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V4_PARENT_SHA_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    import argparse
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
            print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V4_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None:
        parser.error("--verify requires --manifest")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V4: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "sourceSHA_basis": result["sourceSHA_basis"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
