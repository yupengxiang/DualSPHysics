#!/usr/bin/env python3
"""ROOT314 V4 verifier with parent-established source SHA semantics.

V3 requires a historical frame-0 SHA.  This additive layer permits an
explicitly unknown manifest SHA (including ``PARENT_AFTER_RESERVATION_REQUIRED``)
when the real frame-zero worker establishes a concrete digest in this parent.
It still requires the worker's concrete SHA, pre/post-equal guard flag,
complete manifest/worker/current-path stats, decoder array records, and the
existing XML/receipt joins.  No scientific credit is assigned.
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
V3_PATH = HERE / "stage2_four_sentinel_frame0_support_verify_v3.py"
RESULT_SCHEMA = "ds02.stage2.four-sentinel.frame0-support-verifier.v4"
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


V3 = _load(V3_PATH, "stage2_four_sentinel_frame0_support_verify_v3_for_v4")
V2 = V3.V2


class VerifyFailure(RuntimeError):
    pass


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a concrete SHA-256 digest")
    return value.lower()


def _stat(value: Any, label: str) -> dict[str, int]:
    try:
        result = V2._normalize_stat(value, label)
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


def _manifest_source(case: dict[str, Any], sid: str) -> tuple[str, dict[str, int], str | None]:
    frame = case.get("frame0")
    if not isinstance(frame, dict):
        raise VerifyFailure(f"{sid} manifest frame-0 record is missing")
    path = _path(frame.get("path"), f"{sid} manifest frame-0")
    expected = frame.get("stat", frame.get("stat_at_prepare", frame.get("stat_at_build")))
    expected_stat = _stat(expected, f"{sid} manifest frame-0 stat")
    return path, expected_stat, _known_sha(frame, f"{sid} manifest frame-0")


def _strict_native(row: dict[str, Any], case: dict[str, Any], sid: str) -> None:
    native = row.get("native")
    if not isinstance(native, dict):
        raise VerifyFailure(f"{sid} PASS row lacks native guard record")
    expected_path, expected_stat, known_sha = _manifest_source(case, sid)
    if _path(native.get("path"), f"{sid} worker native") != expected_path:
        raise VerifyFailure(f"{sid} worker native path differs from manifest")
    digest = _digest(native.get("sha256"), f"{sid} worker native SHA")
    if known_sha is not None and digest != known_sha:
        raise VerifyFailure(f"{sid} worker native SHA differs from manifest known SHA")
    if native.get("post_equal") is not True:
        raise VerifyFailure(f"{sid} worker did not prove native pre/post SHA equality")
    pre = _stat(native.get("stat_pre"), f"{sid} worker native stat_pre")
    post = _stat(native.get("stat_post"), f"{sid} worker native stat_post")
    current = _stat(native.get("current_stat", native.get("stat_post")), f"{sid} worker native current stat")
    if pre != post or current != post or post != expected_stat:
        raise VerifyFailure(f"{sid} worker/manifest native full stats do not close")
    if _path_stat(Path(expected_path), f"{sid} current native path") != expected_stat:
        raise VerifyFailure(f"{sid} current native path stat differs from manifest")
    arrays = row.get("decoder_array_records")
    if not isinstance(arrays, dict) or not arrays:
        raise VerifyFailure(f"{sid} decoder array records are missing")
    for name, record in arrays.items():
        if not isinstance(record, dict) or record.get("stable") is not True:
            raise VerifyFailure(f"{sid} decoder {name} is not stable")
        _digest(record.get("sha256"), f"{sid} decoder {name} SHA")
        array_pre = _stat(record.get("stat_pre"), f"{sid} decoder {name} stat_pre")
        array_post = _stat(record.get("stat_post"), f"{sid} decoder {name} stat_post")
        if array_pre != array_post:
            raise VerifyFailure(f"{sid} decoder {name} pre/post stat differs")


def _strict_output(summary: dict[str, Any], output: dict[str, Any], original_manifest: dict[str, Any]) -> tuple[dict[str, int], bool]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("frame-zero output cases is not a list")
    by_sid: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise VerifyFailure("frame-zero output identity is malformed")
        sid = row["sentinel_id"]
        if sid in by_sid:
            raise VerifyFailure(f"duplicate frame-zero output row {sid}")
        by_sid[sid] = row
    if set(by_sid) != set(summary["cases"]):
        raise VerifyFailure("frame-zero output case set differs from manifest")
    original_cases = {case["sentinel_id"]: case for case in original_manifest["cases"]}
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    any_unknown = False
    for sid, row in by_sid.items():
        status = str(row.get("status", ""))
        if status.startswith("PASS_FRAME0_POSITION_IDENTITY"):
            counts["PASS"] += 1
            case = original_cases[sid]
            _strict_native(row, case, sid)
            any_unknown |= _known_sha(case["frame0"], f"{sid} manifest frame-0") is None
        elif status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
        elif status.startswith("FAILED"):
            counts["FAILED"] += 1
        else:
            raise VerifyFailure(f"{sid} has unclassified status {status!r}")
    declared = output.get("case_counts")
    for name, value in counts.items():
        if name == "UNKNOWN" and value == 0 and isinstance(declared, dict) and name not in declared:
            continue
        if not isinstance(declared, dict) or int(declared.get(name, -1)) != value:
            raise VerifyFailure(f"frame-zero {name} count is wrong: {declared}")
    return counts, any_unknown


def verify(manifest_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    original_manifest, _ = V2._stable_json(manifest_path, "ROOT314 frame-zero manifest")
    try:
        summary = V2._verify_manifest(original_manifest)
        output, output_record = V2._stable_json(output_path, "ROOT314 frame-zero worker output")
        V2._verify_output(summary, output)
    except Exception as exc:
        raise VerifyFailure(str(exc)) from exc
    counts, output_unknown = _strict_output(summary, output, original_manifest)
    result = {
        "schema": RESULT_SCHEMA,
        "status": "VERIFIED_ROOT314_FRAME0_WORKER_PARENT_SHA_BRIDGE_V4",
        "manifest": {"path": str(Path(manifest_path).expanduser().absolute())},
        "worker_output": output_record,
        "case_counts": counts,
        "sourceSHA_basis": FIRST_ESTABLISHED if output_unknown else HISTORICALLY_PREBOUND,
        "strict_source_bridge": {"manifest_bound_full_stat": True, "manifest_known_sha_optional_only_when_unknown": True, "current_native_stat_checked_without_payload_read": True},
        "scientific_qualification": V2.QUALIFICATION,
        "read_scope": {"manifest_receipt_xml_json_stat_only": True, "native_payload_reopened": False, "vtk_read": False, "hdf5_read": False, "solver_launch": False, "f7_identity_fallback": False},
    }
    if verification_output is not None:
        V2._write_once(verification_output, result)
    return result


def _unknown_manifest(manifest_path: Path) -> None:
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in value["cases"]:
        frame = case["frame0"]
        frame["known_sha256"] = None
        frame["sha256"] = "PARENT_AFTER_RESERVATION_REQUIRED"
    manifest_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> None:
    worker = V2._load_worker()
    with tempfile.TemporaryDirectory(prefix="root314-frame0-v4-") as directory:
        root = Path(directory)
        manifest, attempt, output = V2._fixture_manifest(root)
        known_output = root / "known-output.json"
        worker.run(manifest, attempt, known_output)
        known_result = verify(manifest, known_output)
        assert known_result["sourceSHA_basis"] == HISTORICALLY_PREBOUND
        _unknown_manifest(manifest)
        output = root / "unknown-output.json"
        worker.run(manifest, attempt, output)
        result = verify(manifest, output)
        assert result["sourceSHA_basis"] == FIRST_ESTABLISHED
        assert result["case_counts"] == {"PASS": 4, "UNKNOWN": 0, "FAILED": 0}
        for label, replacement in (("missing", None), ("placeholder", "PARENT_AFTER_RESERVATION_REQUIRED")):
            broken = json.loads(output.read_text(encoding="utf-8"))
            broken["cases"][0]["native"]["sha256"] = replacement
            broken_path = root / f"broken-{label}.json"
            broken_path.write_text(json.dumps(broken), encoding="utf-8")
            try:
                verify(manifest, broken_path)
            except VerifyFailure:
                pass
            else:
                raise AssertionError(f"{label} worker digest was accepted")
    print("PASS_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V4_PARENT_SHA_FIXTURE")


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
            print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V4_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--verify requires --manifest and --output")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT_VERIFIER_V4: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "sourceSHA_basis": result["sourceSHA_basis"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
