#!/usr/bin/env python3
"""Exercise the real snapshot-v2 to ROOT279/V4 stat boundary on tiny files.

This is a source/contract fixture only.  It creates ten tiny ``Part_*.bi4``
files in a temporary directory and invokes the actual snapshot-v2 worker
functions.  The produced wrapper is then consumed by ROOT279 request-v3's
``_snapshot_records`` and each normalized record is checked with the
consumed V4 guard's ``_expected_stat``/SHA boundary.  No production BI4,
solver output, HDF5, or VTK file is opened.

The fixture deliberately checks the failure modes that are easy to hide in a
metadata-only self-test: aggregate digest tampering, source byte/stat
mutation, and a receipt whose request path/SHA/attempt identity is wrong.
It does not change the consumed ROOT279/V4 modules.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SNAPSHOT_WORKER_PATH = HERE / "stage2_native_source_snapshot_v2.py"
ROOT279_V3_PATH = HERE / "stage2_f1_s2_root279_pair_native_observer_request_v3.py"
V4_PATH = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import fixture dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SNAPSHOT = _load(SNAPSHOT_WORKER_PATH, "stage2_root279_fixture_snapshot_v2")
ROOT279 = _load(ROOT279_V3_PATH, "stage2_root279_fixture_request_v3")
V4 = _load(V4_PATH, "stage2_root279_fixture_guarded_v4")


def _expect_failure(fn: Any, label: str) -> None:
    try:
        fn()
    except Exception:
        return
    raise AssertionError(f"{label} was accepted")


def _write_request(path: Path, raw_root: Path, files: list[tuple[int, Path]], case_id: str) -> None:
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "FIXTURE",
        "case_id": case_id,
        "attempt_id": case_id.lower(),
        "source_binding": {"raw_root": str(raw_root)},
        "selected_native_frame_ids": [frame for frame, _ in files],
        "deferred_input_files": [str(file_path) for _, file_path in files],
        "command": ["fixture", "--raw-root", str(raw_root)],
    }
    path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")


def _make_snapshot(root: Path) -> tuple[Path, list[Path]]:
    same_root = root / "raw-same"
    half_root = root / "raw-half"
    same_root.mkdir()
    half_root.mkdir()
    same: list[tuple[int, Path]] = []
    half: list[tuple[int, Path]] = []
    for index, frame in enumerate((0, 1, 2, 3, 4)):
        path = same_root / f"Part_{frame:04d}.bi4"
        path.write_bytes(f"same-frame-{frame}-payload".encode("ascii"))
        same.append((frame, path))
    for index, frame in enumerate((0, 1, 2, 3, 4)):
        # Keep the frame IDs repeated across the two producer entries, as the
        # real same/half pair does, while using distinct source roots.
        path = half_root / f"Part_{frame:04d}.bi4"
        path.write_bytes(f"half-frame-{frame}-payload".encode("ascii"))
        half.append((frame, path))
    same_request = root / "same-request.json"
    half_request = root / "half-request.json"
    _write_request(same_request, same_root, same, "SAME")
    _write_request(half_request, half_root, half, "HALF")
    snapshot_path = root / "native_selected_source_snapshot_v2.json"
    result = SNAPSHOT.build_snapshot([same_request, half_request], snapshot_path)
    assert result["schema"] == SNAPSHOT.SCHEMA
    assert result["status"] == "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
    selected = [
        item["path"]
        for entry in result["requests"]
        for item in entry["selected_native_files"]
    ]
    assert len(selected) == 10 and len(set(selected)) == 10
    return snapshot_path, [Path(path) for path in selected]


def _check_receipt_join(root: Path) -> None:
    request_path = root / "producer-request.json"
    request_path.write_text(json.dumps({"schema": "ds02.request.v1"}, sort_keys=True), encoding="utf-8")
    request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
    request = {"family_id": "F1", "case_id": "CASE", "attempt_id": "ATTEMPT"}
    receipt = {
        "request": {"path": str(request_path), "sha256": request_sha},
        "attempt_id": "F1/CASE/ATTEMPT",
        "returncode": 0,
    }
    ROOT279._assert_receipt_identity(request, receipt, "tiny fixture", request_path, request_sha)
    bad_sha = dict(receipt, request={"path": str(request_path), "sha256": "0" * 64})
    _expect_failure(
        lambda: ROOT279._assert_receipt_identity(request, bad_sha, "tiny fixture", request_path, request_sha),
        "receipt request SHA mismatch",
    )
    bad_attempt = dict(receipt, attempt_id="F1/CASE/OTHER")
    _expect_failure(
        lambda: ROOT279._assert_receipt_identity(request, bad_attempt, "tiny fixture", request_path, request_sha),
        "receipt attempt mismatch",
    )


def run_fixture() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-root279-snapshot-v3-v4-") as directory:
        root = Path(directory)
        snapshot_path, selected_paths = _make_snapshot(root)
        selected = [{"path": str(path)} for path in selected_paths]

        # This is the real chain: snapshot-v2 worker output -> ROOT279 v3
        # parser -> consumed V4 expected-stat representation.
        converted, snapshot_record = ROOT279._snapshot_records(snapshot_path, selected)
        assert snapshot_record is not None
        assert len(converted) == 10
        for path_text, record in converted.items():
            stat_at_prepare = record["stat_at_prepare"]
            assert set(("device", "inode", "bytes", "mtime_ns", "ctime_ns")) <= set(stat_at_prepare)
            assert "st_dev" not in stat_at_prepare and "st_ino" not in stat_at_prepare
            expected = V4._expected_stat(record)
            actual = V4._stat_record(Path(path_text), "tiny ROOT279 fixture")
            assert expected == actual
            digest, guarded_stat = V4._sha_and_stat(Path(path_text), "tiny ROOT279 fixture")
            assert digest == record["sha256"]
            assert guarded_stat == expected

        snapshot_value = json.loads(snapshot_path.read_text(encoding="utf-8"))
        immutable = snapshot_value["immutable_source_sha_list"]
        expected_aggregate = hashlib.sha256(
            json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert snapshot_value["source_sha_list_digest"] == expected_aggregate
        assert snapshot_value["selected_native_total_bytes"] == sum(item["bytes"] for item in immutable)

        # A changed aggregate digest must be rejected by ROOT279 before V4
        # sees a record, even though the ten source files remain untouched.
        bad_aggregate = json.loads(json.dumps(snapshot_value))
        bad_aggregate["source_sha_list_digest"] = "f" * 64
        bad_aggregate_path = root / "snapshot-bad-aggregate.json"
        bad_aggregate_path.write_text(json.dumps(bad_aggregate), encoding="utf-8")
        _expect_failure(
            lambda: ROOT279._snapshot_records(bad_aggregate_path, selected),
            "snapshot aggregate SHA tamper",
        )

        # A source byte mutation must be rejected by the V4 pre-decode
        # boundary: the snapshot metadata still has the old SHA/stat.
        tampered = selected_paths[0]
        original = tampered.read_bytes()
        tampered.write_bytes(bytes((original[0] ^ 0x01,)) + original[1:])
        expected_tamper = V4._expected_stat(converted[str(tampered.absolute())])
        _expect_failure(
            lambda: V4._validate_expected(
                tampered,
                converted[str(tampered.absolute())],
                V4._sha_and_stat(tampered, "tampered tiny source")[0],
                V4._stat_record(tampered, "tampered tiny source"),
            ),
            "source byte tamper",
        )
        tampered.write_bytes(original)
        assert V4._sha_and_stat(tampered, "restored tiny source")[0] == converted[str(tampered.absolute())]["sha256"]
        assert V4._expected_stat(converted[str(tampered.absolute())]) == expected_tamper

        # A touch-only mutation is independently rejected through the full
        # stat contract, including device/inode and ctime/mtime where the OS
        # changes them.
        touched = selected_paths[1]
        old_mtime = touched.stat().st_mtime_ns
        touched.touch()
        _expect_failure(
            lambda: V4._validate_expected(
                touched,
                converted[str(touched.absolute())],
                V4._sha_and_stat(touched, "touched tiny source")[0],
                V4._stat_record(touched, "touched tiny source"),
            ),
            "source stat tamper",
        )
        # Restore the exact mtime for completeness before the temporary tree
        # is removed; ctime remains a changed identity signal and is expected.
        os_utime = __import__("os").utime
        os_utime(touched, ns=(old_mtime, old_mtime))

        _check_receipt_join(root)
        return {
            "status": "PASS_ROOT279_SNAPSHOT_V2_TO_V3_TO_V4_TINY_FIXTURE",
            "selected_file_count": len(converted),
            "aggregate_sha_checked": True,
            "full_stat_fields_checked": ["device", "inode", "bytes", "mtime_ns", "ctime_ns"],
            "tamper_rejections": ["aggregate_sha", "source_bytes", "source_stat"],
            "receipt_identity_rejections": ["request_sha256", "attempt_id"],
            "production_payload_read": False,
            "solver_launch": False,
        }


def main() -> int:
    result = run_fixture()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
