#!/usr/bin/env python3
"""Prepare and execute an exact F4-S1 full-window native lossless archive.

Preparation is metadata-only: it enumerates the one explicitly bound F4
``Part_0000.bi4`` ... ``Part_2400.bi4`` tree and records sizes without reading
the native payloads.  The CPU worker, when dispatched by the parent v4 guard,
streams every frame into one deterministic gzip member per frame, computes the
source SHA during the pass, decompresses the member as a stream, and requires
the restored byte count and SHA to match.  The source tree is never removed or
overwritten and remains the immutable scientific array source.

The request intentionally binds the small receipt/RunPARTs/Run.out and exact
frame manifest.  The worker performs the full per-frame payload SHA pass so a
request preparation does not silently claim a precomputed hash for 6.4 GB of
native data.  The resulting manifest reports actual archive bytes; no
two-frame compression ratio is used as a full-window estimate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PARENT_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_ROOT = DATA_ROOT / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001"
RAW_ROOT = SOURCE_ROOT / "solver_output/data"
RECEIPT = SOURCE_ROOT / "execution-receipt.json"
RUNPARTS = SOURCE_ROOT / "solver_output/RunPARTs.csv"
RUNOUT = SOURCE_ROOT / "solver_output/Run.out"
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
MANIFEST = REFERENCE / "stage2_f4_full_lossless_roundtrip_inputs_v1/manifest.json"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-full-lossless-roundtrip-v1"
SCHEMA = "ds02.stage2.f4-full-lossless-roundtrip.v1"
GiB = 1024 ** 3
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path), "bytes": stat.st_size,
                              "mtime_ns": stat.st_mtime_ns}
    result["sha256"] = sha256_file(path) if hash_file else "WORKER_COMPUTED"
    return result


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def exact_frames() -> list[Path]:
    frames = sorted(RAW_ROOT.glob("Part_*.bi4"))
    expected = [RAW_ROOT / f"Part_{index:04d}.bi4" for index in range(2401)]
    if frames != expected:
        raise ValueError(f"exact F4 frame set mismatch: expected 2401 named frames, found {len(frames)}")
    return frames


def prepare() -> dict[str, Any]:
    frames = exact_frames()
    if not RECEIPT.is_file() or not RUNPARTS.is_file() or not RUNOUT.is_file():
        raise FileNotFoundError("F4 receipt/RunPARTs/Run.out source binding is incomplete")
    frame_records = [file_record(path, hash_file=False) for path in frames]
    raw_bytes = sum(row["bytes"] for row in frame_records)
    tree_bytes = sum(path.stat().st_size for path in SOURCE_ROOT.rglob("*") if path.is_file())
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_METADATA_ONLY_FULL_WINDOW",
        "current_head": git_commit(),
        "source_binding": {
            "physical_case_id": "F4_DROP_CENTERED_REFERENCE_001_DP010",
            "case_id": "F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2",
            "source_role": "immutable completed F4 same-CFL SaveDt native output",
            "source_root": str(SOURCE_ROOT.resolve()),
            "raw_root": str(RAW_ROOT.resolve()),
            "receipt": file_record(RECEIPT),
            "runparts": file_record(RUNPARTS),
            "runout": file_record(RUNOUT),
            "expected_frame_count": len(frame_records),
            "expected_first_frame": frame_records[0],
            "expected_last_frame": frame_records[-1],
            "expected_raw_part_bytes": raw_bytes,
            "expected_source_tree_bytes_at_prepare": tree_bytes,
            "expected_endpoint_s": 1.200084396929538,
            "hash_policy": "worker computes and records SHA256 for every source Part, gzip member, and decompressed roundtrip; preparation records stat only for payload frames",
        },
        "frames": frame_records,
        "archive_policy": {
            "format": "one deterministic gzip file per native Part frame",
            "random_access": "per-frame gzip members plus immutable original Part tree",
            "source_preserved": True,
            "roundtrip_required": True,
            "compression_ratio": "UNKNOWN_UNTIL_WORKER",
            "full_window_archive_bytes": "UNKNOWN_UNTIL_WORKER",
            "two_frame_ratio_used_as_full_bound": False,
        },
        "resource_plan": {
            "cpu_threads": 1,
            "max_wall_seconds": 7200,
            "estimated_storage_bytes": raw_bytes + 2 * GiB,
            "storage_basis": "raw source bytes + 2GiB working/archive/receipt margin; actual terminal bytes are authoritative",
            "temporary_peak_bytes": "one streaming block plus one output gzip member; no decompressed full-frame temporary",
            "gpu": "none",
        },
        "solver_started": False,
        "hdf5_read": False,
        "native_payload_read_by_prepare": False,
    }
    atomic_json(MANIFEST, manifest)
    return manifest


def roundtrip_one(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"refuse to overwrite {destination}")
    started = time.monotonic()
    source_hash = hashlib.sha256()
    source_bytes = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as raw_out:
        with gzip.GzipFile(fileobj=raw_out, mode="wb", compresslevel=6, mtime=0) as zipped:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                source_hash.update(block)
                source_bytes += len(block)
                zipped.write(block)
    restored_hash = hashlib.sha256()
    restored_bytes = 0
    with gzip.open(destination, "rb") as zipped:
        while True:
            block = zipped.read(CHUNK)
            if not block:
                break
            restored_hash.update(block)
            restored_bytes += len(block)
    source_sha = source_hash.hexdigest()
    restored_sha = restored_hash.hexdigest()
    compressed_bytes = destination.stat().st_size
    status = "PASS_ROUNDTRIP_SHA" if source_bytes == restored_bytes and source_sha == restored_sha else "FAIL_ROUNDTRIP_SHA"
    if status != "PASS_ROUNDTRIP_SHA":
        raise ValueError(f"lossless roundtrip mismatch: {source}")
    return {
        "source_path": str(source.resolve()),
        "source_bytes": source_bytes,
        "source_sha256": source_sha,
        "archive_path": str(destination.resolve()),
        "archive_bytes": compressed_bytes,
        "archive_sha256": sha256_file(destination),
        "restored_bytes": restored_bytes,
        "restored_sha256": restored_sha,
        "elapsed_seconds": time.monotonic() - started,
        "status": status,
    }


def run(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest["source_binding"]
    frames = manifest["frames"]
    # The shared runtime may place its running receipt/stdout in the attempt
    # root before invoking this worker. Preserve those guard files while
    # refusing to reuse the archive or terminal sidecar from an older attempt.
    if output_root.exists() and ((output_root / "compressed").exists() or
                                 (output_root / "lossless-roundtrip-v1.json").exists()):
        raise FileExistsError(f"refuse to overwrite prior lossless output {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    raw_root = Path(source["raw_root"])
    actual = exact_frames()
    if [str(path.resolve()) for path in actual] != [row["path"] for row in frames]:
        raise ValueError("source frame paths changed since metadata preparation")
    if sum(path.stat().st_size for path in actual) != source["expected_raw_part_bytes"]:
        raise ValueError("source raw Part byte total changed since metadata preparation")
    results = []
    archive_root = output_root / "compressed"
    archive_root.mkdir()
    for index, row in enumerate(frames):
        source_path = Path(row["path"])
        if source_path.parent != raw_root.resolve() or source_path.stat().st_size != row["bytes"]:
            raise ValueError(f"source frame binding changed: {source_path}")
        destination = archive_root / f"Part_{index:04d}.bi4.gz"
        result = roundtrip_one(source_path, destination)
        result["frame"] = index
        results.append(result)
    raw_bytes = sum(row["source_bytes"] for row in results)
    archive_bytes = sum(row["archive_bytes"] for row in results)
    result = {
        "schema": SCHEMA,
        "status": "PASS" if all(row["status"] == "PASS_ROUNDTRIP_SHA" for row in results) else "FAIL",
        "manifest": file_record(manifest_path),
        "source": {
            "raw_root": str(raw_root),
            "expected_frame_count": len(frames),
            "actual_frame_count": len(results),
            "raw_part_bytes": raw_bytes,
            "source_deleted": False,
        },
        "archive": {
            "root": str(archive_root.resolve()),
            "frame_count": len(results),
            "compressed_bytes": archive_bytes,
            "output_tree_bytes": sum(path.stat().st_size for path in output_root.rglob("*") if path.is_file()),
            "compression_ratio_compressed_over_source": archive_bytes / raw_bytes if raw_bytes else "UNKNOWN",
            "full_window_bytes_actual": True,
        },
        "roundtrip_results": results,
        "scientific_arrays_accessible": "YES: immutable native Part tree retained; each archive member restores byte-for-byte",
        "scientific_qualification": "UNKNOWN",
        "solver_started": False,
        "hdf5_read": False,
    }
    atomic_json(output_root / "lossless-roundtrip-v1.json", result)
    return result


def build_request(request_dir: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if request_dir.exists() and any(request_dir.iterdir()):
        raise FileExistsError(request_dir)
    request_dir.mkdir(parents=True, exist_ok=True)
    # Full Part payload hashes are intentionally worker-computed. The guard
    # binds the exact stat manifest, receipt and first/last content anchors;
    # the worker then proves every intermediate frame before archiving it.
    guarded = [
        PARENT_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py",
        PARENT_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py",
        PARENT_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py",
        PARENT_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(), manifest_path.resolve(), RECEIPT, RUNPARTS, RUNOUT,
        Path(manifest["source_binding"]["expected_first_frame"]["path"]),
        Path(manifest["source_binding"]["expected_last_frame"]["path"]),
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in guarded:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    hashes = {str(path): sha256_file(path) for path in unique}
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "physical_case_id": manifest["source_binding"]["physical_case_id"],
        "case_id": "F4_S1_FULL_WINDOW_NATIVE_LOSSLESS_ROUNDTRIP",
        "attempt_id": "f4-s1-full-window-native-lossless-roundtrip-v1-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_native_lossless_archive_preparation",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": manifest["resource_plan"]["estimated_storage_bytes"],
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(Path(__file__).resolve()), "--run", "--manifest", str(manifest_path.resolve()),
            "--output-root", "{attempt_root}",
        ],
        "input_files": [str(path) for path in unique],
        "input_hashes": hashes,
        "source_tree_binding": {
            "raw_root": manifest["source_binding"]["raw_root"],
            "expected_frame_count": manifest["source_binding"]["expected_frame_count"],
            "expected_raw_part_bytes": manifest["source_binding"]["expected_raw_part_bytes"],
            "expected_source_tree_bytes_at_prepare": manifest["source_binding"]["expected_source_tree_bytes_at_prepare"],
            "frame_hashes": "WORKER_COMPUTED_PER_FRAME_AND_RECORDED",
            "guard_content_scope": "receipt/RunPARTs/Run.out/manifest/first+last frame; intermediate frame bytes are verified by worker against manifest names/sizes and source root",
        },
        "archive_contract": {
            "one_gzip_member_per_frame": True,
            "roundtrip_sha_required": True,
            "source_preserved": True,
            "full_window_archive_bytes": "WORKER_COMPUTED",
            "two_frame_ratio_used_as_full_bound": False,
            "hdf5_read": False,
            "solver_launch": False,
            "scientific_qualification": "UNKNOWN",
        },
        "resource_guard": {
            "runner": "ds_data02_stage2_dispatch_v4.py",
            "strict_guard": "ds_data02_strict_dispatch_v4.py",
            "runtime": "ds_data02_runtime_v4.py",
            "launch_commit": git_commit(),
            "cpu_only": True,
            "gpu_uuid": "NONE",
            "protected_gpu": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec/PID601689 untouched",
            "source_payload_hashing": "worker streaming pass; no precomputed intermediate frame hashes claimed",
        },
        "launch_policy": {"launch_disabled": True, "solver_started": False, "hdf5_read": False},
    }
    path = request_dir / "f4_s1_full_window_native_lossless_roundtrip_v1.json"
    atomic_json(path, request)
    return {"status": "PASS", "request": str(path), "guarded_inputs": len(unique),
            "raw_part_bytes": manifest["source_binding"]["expected_raw_part_bytes"],
            "estimated_storage_bytes": request["estimated_storage_bytes"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--request-dir", type=Path, default=REQUEST_DIR)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.prepare:
        result = prepare()
        print(json.dumps({"status": result["status"], "manifest": str(args.manifest),
                          "frames": len(result["frames"]),
                          "raw_part_bytes": result["source_binding"]["expected_raw_part_bytes"],
                          "native_payload_read": False}, ensure_ascii=False))
        return 0
    if args.build_request:
        print(json.dumps(build_request(args.request_dir, args.manifest), ensure_ascii=False))
        return 0
    if args.run:
        if args.output_root is None:
            raise SystemExit("--run requires --output-root")
        result = run(args.manifest, args.output_root)
        print(json.dumps({"status": result["status"], "output_root": str(args.output_root),
                          "frames": result["archive"]["frame_count"],
                          "compressed_bytes": result["archive"]["compressed_bytes"]}, ensure_ascii=False))
        return int(result["status"] != "PASS")
    raise SystemExit("choose --prepare, --build-request, or --run")


if __name__ == "__main__":
    raise SystemExit(main())
