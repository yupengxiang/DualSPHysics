#!/usr/bin/env python3
"""Enforce immutable selected-native inputs around one observer decode.

This is a forward-only successor to the consumed v1 wrapper.  It keeps the
same bounded source scope and child observer, but closes the v1 gap by
comparing the complete pre-hash ``stat`` record after the pre-check with the
complete post-check ``stat`` record before the post-hash.  A source replace or
touch therefore fails even when its content SHA is unchanged.  The child
must also publish the exact successful observer status; an UNKNOWN payload or
zero return code without a successful artifact is a failure.

The wrapper reads only the selected ``Part_*.bi4`` files named by the source
manifest.  It does not read HDF5, launch a solver, scan the raw tree, or
modify the consumed v1 worker/requests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import stage2_native_physical_observer_enforcer_v1 as v1


SCHEMA = "ds02.stage2.native-physical-observer-enforcer.v2"
MANIFEST_SCHEMA = v1.MANIFEST_SCHEMA
EXPECTED_CHILD_STATUS = "PASS_DECODED_SELECTED_NATIVE_FIELDS"


SourceIntegrityError = v1.SourceIntegrityError
atomic_json = v1.atomic_json
load_manifest = v1.load_manifest
observer_child_command = v1.observer_child_command
stat_record = v1.stat_record
sha256_file = v1.sha256_file


def checked_record(path: Path, frame: int, expected: dict[str, Any], phase: str) -> dict[str, Any]:
    """Hash one expected source while rejecting a mutation during that hash."""

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
    return {
        "frame": int(frame),
        "path": str(path.resolve()),
        "bytes": size,
        "sha256": digest,
        "stat_before": before,
        "stat_after": after,
        "stat_consistency": "PASS_PRE_HASH_IDENTICAL",
    }


def compare_cross_decode(pre: list[dict[str, Any]], post: list[dict[str, Any]]) -> None:
    """Require bytes, SHA, and every stat field to remain stable across decode."""

    if len(pre) != len(post):
        raise SourceIntegrityError(f"cross_decode: selected record count changed: {len(pre)} != {len(post)}")
    for before, after in zip(pre, post):
        if before.get("frame") != after.get("frame") or before.get("path") != after.get("path"):
            raise SourceIntegrityError(
                f"cross_decode: selected source identity changed: {before.get('path')} != {after.get('path')}"
            )
        if before.get("sha256") != after.get("sha256") or before.get("bytes") != after.get("bytes"):
            raise SourceIntegrityError(f"cross_decode: content changed for frame {before.get('frame')}")
        # The pre record's stat_after is the exact state at the hand-off to
        # the child; post stat_before is the exact state at return.  Compare
        # both boundaries, not merely the two content hashes.
        if before.get("stat_after") != after.get("stat_before"):
            raise SourceIntegrityError(
                f"cross_decode: stat changed across child for frame {before.get('frame')}: "
                f"pre_after={before.get('stat_after')} post_before={after.get('stat_before')}"
            )
        if before.get("stat_before") != after.get("stat_after"):
            raise SourceIntegrityError(
                f"cross_decode: source stat was not stable for frame {before.get('frame')}: "
                f"pre_before={before.get('stat_before')} post_after={after.get('stat_after')}"
            )


def validate_child_payload(payload: Any) -> dict[str, Any]:
    """Reject an UNKNOWN/partial child result even when the process exits 0."""

    if not isinstance(payload, dict):
        raise SourceIntegrityError("observer child output is not a JSON object")
    if payload.get("status") != EXPECTED_CHILD_STATUS:
        raise SourceIntegrityError(
            f"observer child did not publish {EXPECTED_CHILD_STATUS}; "
            f"status={payload.get('status')!r}"
        )
    return payload


def failure_artifact(output: Path, reason: str, manifest_path: Path, phase: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "FAIL_SOURCE_INTEGRITY",
        "reason": reason,
        "failure_phase": phase,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_integrity": {
            "expected_manifest": str(manifest_path.resolve()),
            "scope": "selected native frames only",
            "hdf5_read": False,
            "solver_launch": False,
            "full_raw_tree_scan": False,
            "cross_decode_stat_policy": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    manifest_path = args.expected_source_manifest.expanduser().resolve()
    _manifest, expected = load_manifest(manifest_path)
    if output.exists():
        raise FileExistsError(f"refuse to overwrite immutable observer output: {output}")
    if str(args.raw_root.expanduser().resolve()) != str(_manifest["raw_root"]):
        raise SourceIntegrityError("command raw-root differs from expected source manifest")
    requested_frames = sorted(set(int(frame) for frame in args.frames))
    expected_frames = [int(item["frame"]) for item in expected]
    if requested_frames != expected_frames:
        raise SourceIntegrityError(
            f"command selected frames differ from expected manifest: {requested_frames} != {expected_frames}"
        )

    child_output = output.with_name(output.name + f".inner-{os.getpid()}.json")
    child = observer_child_command(args, child_output)
    try:
        pre_records = [checked_record(Path(item["path"]), item["frame"], item, "pre_decode") for item in expected]
        completed = subprocess.run(child, cwd=args.cwd, capture_output=True, text=True, check=False)
        if not child_output.is_file():
            raise SourceIntegrityError(
                f"observer child did not produce its private output (returncode={completed.returncode})"
            )
        try:
            child_payload = json.loads(child_output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceIntegrityError(f"observer child output is not valid JSON: {exc}") from exc
        child_payload = validate_child_payload(child_payload)
        post_records = [checked_record(Path(item["path"]), item["frame"], item, "post_decode") for item in expected]
        compare_cross_decode(pre_records, post_records)
        if completed.returncode != 0:
            raise SourceIntegrityError(
                f"observer child failed with returncode={completed.returncode}: {completed.stderr[-1000:]}"
            )
        reported = child_payload.get("source", {}).get("selected_part_records", [])
        if not isinstance(reported, list) or len(reported) != len(expected):
            raise SourceIntegrityError("observer child reported an unexpected selected_part_records length")
        reported_by_path = {
            str(Path(str(item.get("path"))).resolve()): item for item in reported if isinstance(item, dict)
        }
        for item in expected:
            report = reported_by_path.get(str(Path(item["path"]).resolve()))
            if report is None or report.get("sha256") != item["sha256"] or report.get("bytes") != item["bytes"]:
                raise SourceIntegrityError(f"observer child source record disagrees with snapshot: {item['path']}")
        child_payload["source_integrity"] = {
            "schema": SCHEMA,
            "status": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT",
            "expected_manifest": str(manifest_path),
            "pre_decode_records": pre_records,
            "post_decode_records": post_records,
            "pre_post_sha_and_stat_equal": True,
            "cross_decode_stat_boundaries_equal": True,
            "selected_frame_count": len(expected),
            "full_raw_tree_scan": False,
            "hdf5_read": False,
            "solver_launch": False,
        }
        child_payload["enforcer"] = {
            "schema": SCHEMA,
            "child_observer": str(args.observer_worker),
            "child_returncode": completed.returncode,
            "child_status_required": EXPECTED_CHILD_STATUS,
            "child_stdout_tail": completed.stdout[-1000:],
        }
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
    with tempfile.TemporaryDirectory(prefix="ds02-observer-enforcer-v2-") as root_text:
        root = Path(root_text)
        native = root / "Part_0000.bi4"
        native.write_bytes(b"native-self-test")
        digest, size = sha256_file(native)
        expected = {"frame": 0, "path": str(native), "bytes": size, "sha256": digest}

        pre = [checked_record(native, 0, expected, "self_test_pre")]
        post = [checked_record(native, 0, expected, "self_test_post")]
        compare_cross_decode(pre, post)

        os.utime(native, ns=(pre[0]["stat_after"]["mtime_ns"] + 1_000_000,
                             pre[0]["stat_after"]["mtime_ns"] + 1_000_000))
        touched = [checked_record(native, 0, expected, "self_test_touch")]
        try:
            compare_cross_decode(pre, touched)
        except SourceIntegrityError:
            touch_rejected = True
        else:
            touch_rejected = False
        assert touch_rejected

        native.write_bytes(b"native-self-test")
        pre_replace = [checked_record(native, 0, expected, "self_test_replace_pre")]
        replacement = root / "Part_0000.replacement"
        replacement.write_bytes(b"native-self-test")
        os.replace(replacement, native)
        replaced = [checked_record(native, 0, expected, "self_test_replace_post")]
        try:
            compare_cross_decode(pre_replace, replaced)
        except SourceIntegrityError:
            replace_rejected = True
        else:
            replace_rejected = False
        assert replace_rejected

        try:
            validate_child_payload({"status": "UNKNOWN"})
        except SourceIntegrityError:
            unknown_rejected = True
        else:
            unknown_rejected = False
        assert unknown_rejected
        return {
            "status": "PASS",
            "cross_decode_stat_boundaries_checked": True,
            "touch_rejected": touch_rejected,
            "replace_rejected": replace_rejected,
            "unknown_child_status_rejected": unknown_rejected,
            "decoder_launch": False,
            "hdf5_read": False,
        }


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
                      "selected_frames": result.get("source_integrity", {}).get("selected_frame_count", 0),
                      "source_integrity": result.get("source_integrity", {}).get("status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
