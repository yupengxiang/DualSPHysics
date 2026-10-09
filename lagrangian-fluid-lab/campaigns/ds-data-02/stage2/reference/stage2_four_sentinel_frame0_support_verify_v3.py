#!/usr/bin/env python3
"""Strict additive ROOT314 frame-zero verifier.

V2 already checks worker pre/post consistency.  This version adds an explicit
manifest bridge for every PASS row: the native path, complete five-field
stat, and known SHA are compared with the manifest frame-0 record and with a
stat-only check of the currently bound path.  Source XML/receipt output rows
are also joined back to their manifest records.  Decoder scratch arrays stay
outside the manifest payload scope; their own pre/post stats remain required.

The self-test runs the real ROOT314 frame-zero worker on its tiny manufactured
decoder fixture and then exercises a manifest-stat and current-path negative.
No production BI4, VTK, HDF5, or native payload is opened.
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
V2_PATH = HERE / "stage2_four_sentinel_frame0_support_verify_v2.py"
RESULT_SCHEMA = "ds02.stage2.four-sentinel.frame0-support-verifier.v3"
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_PATH, "stage2_four_sentinel_frame0_support_verify_v2_for_v3")


class VerifyFailure(RuntimeError):
    pass


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(value: Any, label: str) -> dict[str, int]:
    try:
        result = V2._normalize_stat(value, label)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    if set(result) != set(STAT_FIELDS):
        raise VerifyFailure(f"{label} is not a complete five-field stat")
    return result


def _absolute_path(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise VerifyFailure(f"{label} path is missing")
    return str(Path(value).expanduser().absolute())


def _manifest_source(case: dict[str, Any], sid: str) -> tuple[str, dict[str, int], str | None]:
    frame = case.get("frame0")
    if not isinstance(frame, dict):
        raise VerifyFailure(f"{sid} manifest frame-0 record is missing")
    path = _absolute_path(frame.get("path"), f"{sid} manifest frame-0")
    expected_stat = _stat(frame.get("stat", frame.get("stat_at_prepare", frame.get("stat_at_build"))), f"{sid} manifest frame-0 stat")
    known = frame.get("known_sha256", frame.get("sha256"))
    if known in (None, "", "PARENT_AFTER_RESERVATION_REQUIRED"):
        known_sha = None
    else:
        known_sha = _digest(known, f"{sid} manifest frame-0 SHA")
    return path, expected_stat, known_sha


def _strict_native(row: dict[str, Any], case: dict[str, Any], sid: str) -> None:
    native = row.get("native")
    if not isinstance(native, dict):
        raise VerifyFailure(f"{sid} PASS row lacks native record")
    expected_path, expected_stat, known_sha = _manifest_source(case, sid)
    if _absolute_path(native.get("path"), f"{sid} worker native") != expected_path:
        raise VerifyFailure(f"{sid} worker native path differs from manifest")
    if known_sha is None:
        raise VerifyFailure(f"{sid} PASS row has no manifest known native SHA")
    digest = _digest(native.get("sha256"), f"{sid} worker native SHA")
    if digest != known_sha:
        raise VerifyFailure(f"{sid} worker native SHA differs from manifest")
    pre = _stat(native.get("stat_pre"), f"{sid} worker native stat_pre")
    post = _stat(native.get("stat_post"), f"{sid} worker native stat_post")
    if pre != post or pre != expected_stat:
        raise VerifyFailure(f"{sid} worker native full stat is not manifest-bound")
    current = _stat(native.get("current_stat", native.get("stat_post")), f"{sid} worker native current stat")
    if current != post:
        raise VerifyFailure(f"{sid} worker native current stat differs from post stat")
    # Stat-only current-path check: do not reopen production payload bytes.
    path_stat = _stat(V2._stat(Path(expected_path)), f"{sid} current native path stat")
    if path_stat != expected_stat:
        raise VerifyFailure(f"{sid} current native path stat differs from manifest")
    arrays = row.get("decoder_array_records")
    if not isinstance(arrays, dict) or not arrays:
        raise VerifyFailure(f"{sid} decoder array records are missing")
    for name, record in arrays.items():
        if not isinstance(record, dict) or record.get("stable") is not True:
            raise VerifyFailure(f"{sid} decoder {name} is not stable")
        _digest(record.get("sha256"), f"{sid} decoder {name} SHA")
        if _stat(record.get("stat_pre"), f"{sid} decoder {name} stat_pre") != _stat(record.get("stat_post"), f"{sid} decoder {name} stat_post"):
            raise VerifyFailure(f"{sid} decoder {name} pre/post stat differs")


def _strict_source_joins(row: dict[str, Any], case: dict[str, Any], sid: str) -> None:
    source_xml = row.get("source_xml")
    expected_xml = case.get("source_xml")
    receipt = row.get("receipt")
    expected_receipt = case.get("receipt")
    for actual, expected, label in ((source_xml, expected_xml, "source XML"), (receipt, expected_receipt, "receipt")):
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            raise VerifyFailure(f"{sid} {label} output/manifest record is incomplete")
        if _absolute_path(actual.get("path"), f"{sid} {label}") != _absolute_path(expected.get("path"), f"{sid} manifest {label}"):
            raise VerifyFailure(f"{sid} {label} path differs from manifest")
        if _digest(actual.get("sha256"), f"{sid} {label} output SHA") != _digest(expected.get("sha256"), f"{sid} {label} manifest SHA"):
            raise VerifyFailure(f"{sid} {label} SHA differs from manifest")
    join = row.get("source_xml_receipt_join")
    if not isinstance(join, dict) or _absolute_path(join.get("path"), f"{sid} source XML join") != _absolute_path(expected_xml.get("path"), f"{sid} manifest source XML"):
        raise VerifyFailure(f"{sid} source XML/receipt join path is not manifest-bound")
    if _digest(join.get("sha256"), f"{sid} source XML join SHA") != _digest(expected_xml.get("sha256"), f"{sid} manifest source XML SHA"):
        raise VerifyFailure(f"{sid} source XML/receipt join SHA is not manifest-bound")


def _strict_output(summary: dict[str, Any], output: dict[str, Any]) -> dict[str, int]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("frame-zero output cases is not a list")
    by_sid = {str(row.get("sentinel_id")): row for row in rows if isinstance(row, dict)}
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for sid, row in by_sid.items():
        status = str(row.get("status", ""))
        if status.startswith("PASS_FRAME0_POSITION_IDENTITY"):
            counts["PASS"] += 1
            case = summary["cases"][sid]
            _strict_source_joins(row, case, sid)
            _strict_native(row, case, sid)
        elif status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
        elif status.startswith("FAILED"):
            counts["FAILED"] += 1
        else:
            raise VerifyFailure(f"{sid} has unclassified status {status!r}")
    declared = output.get("case_counts")
    if not isinstance(declared, dict) or int(declared.get("PASS", -1)) != counts["PASS"] or int(declared.get("FAILED", -1)) != counts["FAILED"] or ("UNKNOWN" in declared and int(declared.get("UNKNOWN", -1)) != counts["UNKNOWN"]) or (counts["UNKNOWN"] and "UNKNOWN" not in declared):
        raise VerifyFailure(f"frame-zero case counts do not preserve strict outcomes: {declared}")
    return counts


def verify(manifest_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, _ = V2._stable_json(manifest_path, "ROOT314 frame-zero manifest")
    try:
        summary = V2._verify_manifest(manifest)
        output, output_record = V2._stable_json(output_path, "ROOT314 frame-zero worker output")
        V2._verify_output(summary, output)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    counts = _strict_output(summary, output)
    result = {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED_ROOT314_FRAME0_WORKER_OUTPUT_STRICT_V3",
        "manifest": {"path": str(Path(manifest_path).expanduser().absolute())},
        "worker_output": output_record,
        "case_counts": counts,
        "strict_source_bridge": {"manifest_bound_full_stat": True, "manifest_known_sha_required_for_pass": True, "current_native_stat_checked_without_payload_read": True},
        "scientific_qualification": V2.QUALIFICATION,
        "read_scope": {"manifest_receipt_xml_json_stat_only": True, "native_payload_reopened": False, "vtk_read": False, "hdf5_read": False, "solver_launch": False, "f7_identity_fallback": False},
    }
    if verification_output is not None:
        V2._write_once(verification_output, result)
    return result


def self_test() -> None:
    worker = V2._load_worker()
    with tempfile.TemporaryDirectory(prefix="root314-frame0-v3-") as directory:
        root = Path(directory)
        manifest, attempt, output = V2._fixture_manifest(root)
        worker.run(manifest, attempt, output)
        result = verify(manifest, output)
        assert result["case_counts"] == {"PASS": 4, "UNKNOWN": 0, "FAILED": 0}
        broken_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        broken_manifest["cases"][0]["frame0"]["stat"]["bytes"] += 1
        broken_manifest_path = root / "broken-manifest.json"
        broken_manifest_path.write_text(json.dumps(broken_manifest), encoding="utf-8")
        try:
            verify(broken_manifest_path, output)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("frame-zero manifest full-stat mutation was accepted")
        native_path = Path(json.loads(manifest.read_text(encoding="utf-8"))["cases"][0]["frame0"]["path"])
        native_path.write_bytes(b"changed-size")
        try:
            verify(manifest, output)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("current native stat mutation was accepted")
    print("PASS_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V3_STRICT_E2E_SELFTEST")


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
            print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V3_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--verify requires --manifest and --output")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V3: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "case_counts": result["case_counts"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
