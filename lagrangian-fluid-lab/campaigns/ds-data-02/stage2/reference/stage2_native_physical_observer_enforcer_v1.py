#!/usr/bin/env python3
"""Enforce snapshot SHA and source stat stability around native decoding.

The consumed observer v2 remains immutable and is executed as the child
decoder.  This wrapper performs a bounded pre-decode SHA/stat check against an
immutable snapshot manifest, runs observer v2 into a private temporary JSON,
then performs the same bounded post-decode check.  A mismatch writes an
explicit failure artifact and exits non-zero; no successful observer artifact
is published.  Only the selected ``Part_*.bi4`` files listed in the manifest
are read.  No solver, HDF5, full-tree scan, or particle interpolation is
performed here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.native-physical-observer-enforcer.v1"
MANIFEST_SCHEMA = "ds02.stage2.native-observer-source-manifest.v1"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")
CHUNK = 1024 * 1024


class SourceIntegrityError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable observer output: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def stat_record(path: Path) -> dict[str, int]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise SourceIntegrityError(f"selected native input is missing or symlinked: {path}")
    stat = path.stat()
    return {"bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
            "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino)}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def checked_record(path: Path, frame: int, expected: dict[str, Any], phase: str) -> dict[str, Any]:
    before = stat_record(path)
    digest, size = sha256_file(path)
    after = stat_record(path)
    if before != after:
        raise SourceIntegrityError(f"{phase}: source changed while hashing {path}: before={before} after={after}")
    if size != int(expected["bytes"]) or digest != str(expected["sha256"]):
        raise SourceIntegrityError(
            f"{phase}: snapshot mismatch for frame {frame} {path}: "
            f"expected bytes/sha={expected['bytes']}/{expected['sha256']} actual={size}/{digest}"
        )
    return {"frame": int(frame), "path": str(path.resolve()), "bytes": size, "sha256": digest,
            "stat_before": before, "stat_after": after, "stat_consistency": "PASS_PRE_HASH_IDENTICAL"}


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise SourceIntegrityError(f"expected source manifest is missing or symlinked: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != MANIFEST_SCHEMA:
        raise SourceIntegrityError(f"wrong expected source manifest schema: {path}")
    raw_root = value.get("raw_root")
    records = value.get("selected_native_files")
    if not isinstance(raw_root, str) or not isinstance(records, list) or not records:
        raise SourceIntegrityError("expected source manifest lacks raw_root/selected_native_files")
    root = Path(raw_root).expanduser().resolve()
    frames: list[int] = []
    normalized: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            raise SourceIntegrityError("expected source manifest has a non-object file record")
        path_text = item.get("path")
        frame = item.get("frame")
        if not isinstance(path_text, str) or not isinstance(frame, int) or frame < 0:
            raise SourceIntegrityError("expected source manifest has invalid frame/path")
        path = Path(path_text).expanduser().resolve()
        match = PART_RE.fullmatch(path.name)
        if match is None or int(match.group(1)) != frame or path.parent != root:
            raise SourceIntegrityError(f"expected source manifest frame/path outside raw root: {path}")
        if frame in frames:
            raise SourceIntegrityError(f"expected source manifest repeats frame: {frame}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SourceIntegrityError(f"expected source manifest has invalid SHA for frame {frame}")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise SourceIntegrityError(f"expected source manifest has invalid byte count for frame {frame}")
        frames.append(frame)
        normalized.append({"frame": frame, "path": str(path), "bytes": int(item["bytes"]), "sha256": digest})
    if frames != sorted(frames):
        raise SourceIntegrityError("expected source manifest frames must be sorted")
    value["raw_root"] = str(root)
    return value, normalized


def observer_child_command(args: argparse.Namespace, child_output: Path) -> list[str]:
    return [sys.executable, str(args.observer_worker), "--raw-root", str(args.raw_root),
            "--runparts", str(args.runparts), "--generated-xml", str(args.generated_xml),
            "--decoder", str(args.decoder), "--decoder-source", str(args.decoder_source),
            "--output", str(child_output), "--scratch-root", str(args.scratch_root),
            "--expected-frame-count", str(args.expected_frame_count),
            "--expected-final-time-s", str(args.expected_final_time_s),
            "--final-time-tolerance-s", str(args.final_time_tolerance_s), "--frames",
            *[str(frame) for frame in args.frames], "--query-times",
            *[str(query) for query in args.query_times]]


def failure_artifact(output: Path, reason: str, manifest_path: Path, phase: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "FAIL_SOURCE_INTEGRITY",
        "reason": reason,
        "failure_phase": phase,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_integrity": {"expected_manifest": str(manifest_path.resolve()), "scope": "selected native frames only",
                              "hdf5_read": False, "solver_launch": False, "full_raw_tree_scan": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    manifest_path = args.expected_source_manifest.expanduser().resolve()
    manifest, expected = load_manifest(manifest_path)
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable observer output: {output}")
    if str(args.raw_root.expanduser().resolve()) != str(manifest["raw_root"]):
        raise SourceIntegrityError("command raw-root differs from expected source manifest")
    requested_frames = sorted(set(int(frame) for frame in args.frames))
    expected_frames = [int(item["frame"]) for item in expected]
    if requested_frames != expected_frames:
        raise SourceIntegrityError(f"command selected frames differ from expected manifest: {requested_frames} != {expected_frames}")

    child_output = output.with_name(output.name + f".inner-{os.getpid()}.json")
    child = observer_child_command(args, child_output)
    try:
        pre_records = [checked_record(Path(item["path"]), item["frame"], item, "pre_decode") for item in expected]
        completed = subprocess.run(child, cwd=args.cwd, capture_output=True, text=True, check=False)
        if not child_output.is_file():
            raise SourceIntegrityError(f"observer child did not produce its private output (returncode={completed.returncode})")
        child_payload = json.loads(child_output.read_text(encoding="utf-8"))
        if not isinstance(child_payload, dict):
            raise SourceIntegrityError("observer child output is not a JSON object")
        post_records = [checked_record(Path(item["path"]), item["frame"], item, "post_decode") for item in expected]
        for pre, post in zip(pre_records, post_records):
            if pre["sha256"] != post["sha256"] or pre["bytes"] != post["bytes"]:
                raise SourceIntegrityError(f"source changed across decode for frame {pre['frame']}")
        if completed.returncode != 0:
            raise SourceIntegrityError(f"observer child failed with returncode={completed.returncode}: {completed.stderr[-1000:]}")
        reported = child_payload.get("source", {}).get("selected_part_records", [])
        if child_payload.get("status") == "PASS_DECODED_SELECTED_NATIVE_FIELDS":
            if not isinstance(reported, list) or len(reported) != len(expected):
                raise SourceIntegrityError("observer child reported an unexpected selected_part_records length")
            reported_by_path = {str(Path(str(item.get("path"))).resolve()): item for item in reported if isinstance(item, dict)}
            for item in expected:
                report = reported_by_path.get(str(Path(item["path"]).resolve()))
                if report is None or report.get("sha256") != item["sha256"] or report.get("bytes") != item["bytes"]:
                    raise SourceIntegrityError(f"observer child source record disagrees with snapshot: {item['path']}")
        child_payload["source_integrity"] = {
            "schema": SCHEMA,
            "status": "PASS_PRE_POST_EXPECTED_SOURCE",
            "expected_manifest": str(manifest_path),
            "pre_decode_records": pre_records,
            "post_decode_records": post_records,
            "pre_post_sha_and_stat_equal": True,
            "selected_frame_count": len(expected),
            "full_raw_tree_scan": False,
            "hdf5_read": False,
            "solver_launch": False,
        }
        child_payload["enforcer"] = {"schema": SCHEMA, "child_observer": str(args.observer_worker),
                                      "child_returncode": completed.returncode,
                                      "child_stdout_tail": completed.stdout[-1000:]}
        atomic_json(output, child_payload)
        return child_payload
    except SourceIntegrityError as exc:
        if output.exists():
            raise
        failure = failure_artifact(output, str(exc), manifest_path, "pre_decode_or_decode_or_post_decode")
        raise RuntimeError(json.dumps(failure, ensure_ascii=False)) from exc
    finally:
        child_output.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-observer-enforcer-") as root_text:
        root = Path(root_text)
        native = root / "Part_0000.bi4"
        native.write_bytes(b"native-self-test")
        digest, size = sha256_file(native)
        expected = {"frame": 0, "path": str(native), "bytes": size, "sha256": digest}
        checked = checked_record(native, 0, expected, "self_test")
        assert checked["stat_consistency"] == "PASS_PRE_HASH_IDENTICAL"
        bad = dict(expected); bad["sha256"] = "0" * 64
        try:
            checked_record(native, 0, bad, "self_test_bad")
        except SourceIntegrityError:
            mismatch_rejected = True
        else:
            mismatch_rejected = False
        assert mismatch_rejected
        return {"status": "PASS", "pre_post_stat_checked": True, "sha_mismatch_rejected": True,
                "decoder_launch": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-worker", type=Path)
    parser.add_argument("--expected-source-manifest", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--frames", type=int, nargs="+")
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    required = (args.observer_worker, args.expected_source_manifest, args.raw_root, args.runparts,
                args.generated_xml, args.decoder, args.decoder_source, args.output, args.scratch_root,
                args.expected_frame_count, args.expected_final_time_s, args.frames, args.query_times)
    if any(value is None for value in required):
        parser.error("all observer/enforcer arguments are required unless --self-test is used")
    try:
        result = run(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": result.get("status"), "output": str(args.output.resolve()),
                      "selected_frames": result.get("scope", {}).get("selected_frame_count", 0),
                      "source_integrity": result.get("source_integrity", {}).get("status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
