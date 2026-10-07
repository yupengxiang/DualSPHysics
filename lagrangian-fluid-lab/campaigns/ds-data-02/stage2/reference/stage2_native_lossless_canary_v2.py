#!/usr/bin/env python3
"""Bounded native BI4 lossless archive canary for the 14 exact sentinels.

The canary reads exactly two native ``Part_*.bi4`` files per CURRENT336
sentinel: frame zero and the recorded last frame.  It never reads H5, scans a
family directory, deletes a source, or launches a solver.  Each compressed
file is decompressed immediately into a temporary output file and SHA-checked
against the immutable source before that temporary file is removed.

The resulting compression bytes and a clearly labelled six-cell planning
proxy (three spatial candidates x same/half-CFL temporal pairs) are evidence
for archive planning only.  They do not establish full-time output cost or
scientific equivalence.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
INPUT_ROOT = Path(__file__).with_name("stage2_native_lossless_canary_inputs_v1")
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-native-lossless-canary-v2"
SCHEMA = "ds02.stage2.native-lossless-canary.v2"
REQUEST_SCHEMA = "ds02.request.v1"
TARGET_SENTINELS = tuple(f"F{i}-S{j}" for i in range(1, 8) for j in (1, 2))
GiB = 1024 ** 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def load_catalog() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')}")
    reviews = {row["sentinel_id"]: row for row in review.get("sentinels", [])}
    missing = [sid for sid in TARGET_SENTINELS if sid not in reviews]
    if missing:
        raise ValueError(f"missing exact review rows: {missing}")
    return current, reviews


def current_row(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    matches = [row for row in current.get("cases", []) if row.get("physical_case_id") == physical_case_id]
    if len(matches) != 1:
        raise ValueError(f"expected one exact CURRENT row for {physical_case_id}, found {len(matches)}")
    return matches[0]


def prepare() -> dict[str, Any]:
    current, reviews = load_catalog()
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    records = []
    source_total = 0
    for sid in TARGET_SENTINELS:
        review = reviews[sid]
        row = current_row(current, review["source_physical_case_id"])
        raw_root = Path(row["raw_root"]["path"]).resolve()
        frames = int(row["frames"])
        if frames < 1:
            raise ValueError(f"invalid frame count for {sid}: {frames}")
        selected = [(0, raw_root / "Part_0000.bi4"), (frames - 1, raw_root / f"Part_{frames - 1:04d}.bi4")]
        entries = []
        for frame, path in selected:
            record = file_record(path)
            source_total += record["bytes"]
            entries.append({"frame": frame, "path": record})
        records.append({
            "sentinel_id": sid,
            "family_id": review["family"],
            "physical_case_id": review["source_physical_case_id"],
            "current_identity": {
                "runtime_case_alias": row["runtime_case_alias"],
                "frames": frames,
                "actual_time_window_s": row["actual_time_window_s"],
                "trajectory_producer_sha256": row["trajectory"]["producer_declared_sha256"],
                "trajectory_mtime_ns": row["trajectory"]["mtime_ns"],
                "raw_root": row["raw_root"],
            },
            "selected_native_frames": entries,
            "selected_source_bytes": sum(item["path"]["bytes"] for item in entries),
            "full_time_archive_status": "NOT_TESTED_BY_BOUNDED_CANARY",
        })
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_NOT_RUN",
        "current_catalog": file_record(CURRENT_PATH),
        "review_matrix": file_record(REVIEW_PATH),
        "quality_label_split": file_record(QUALITY_PATH),
        "target_sentinels": list(TARGET_SENTINELS),
        "selected_frame_policy": "exact CURRENT row frame 0 and frame frames-1; no directory scan or H5 read",
        "sentinels": records,
        "source_total_bytes": source_total,
        "source_total_mib": source_total / 1024**2,
        "guard_storage_reservation_bytes": 2 * GiB,
        "guard_storage_reservation_policy": "at least 2GiB for compressed output plus one temporary decompressed frame, receipt and logs",
        "planning_proxy": {
            "spatial_candidate_count": 3,
            "temporal_control_pair_count": 2,
            "cells_per_sentinel": 6,
            "formula": "observed two-frame compressed bytes x 3 spatial candidates x 2 same/half-CFL temporal pairs",
            "status": "planning proxy only; full-time output bytes, typed multiplier and solver runtime remain UNKNOWN",
        },
        "solver_started": False,
        "full_time_hdf5_read": False,
    }
    atomic_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def compress_roundtrip(source: Path, destination: Path, temporary: Path) -> dict[str, Any]:
    started = time.monotonic()
    if destination.exists() or temporary.exists():
        raise FileExistsError(destination)
    source_sha = hashlib.sha256()
    source_bytes = 0
    with source.open("rb") as src, destination.open("wb") as raw_out:
        with gzip.GzipFile(fileobj=raw_out, mode="wb", compresslevel=6, mtime=0) as zipped:
            while True:
                block = src.read(1024 * 1024)
                if not block:
                    break
                source_sha.update(block)
                source_bytes += len(block)
                zipped.write(block)
    roundtrip_sha = hashlib.sha256()
    roundtrip_bytes = 0
    with gzip.open(destination, "rb") as zipped, temporary.open("wb") as roundtrip:
        while True:
            block = zipped.read(1024 * 1024)
            if not block:
                break
            roundtrip_sha.update(block)
            roundtrip_bytes += len(block)
            roundtrip.write(block)
    if roundtrip_sha.hexdigest() != source_sha.hexdigest() or roundtrip_bytes != source_bytes:
        raise ValueError(f"lossless roundtrip mismatch for {source}")
    temporary.unlink()
    compressed_bytes = destination.stat().st_size
    return {
        "source": file_record(source),
        "compressed": file_record(destination),
        "roundtrip_sha256": roundtrip_sha.hexdigest(),
        "roundtrip_bytes": roundtrip_bytes,
        "compression_ratio_compressed_over_source": compressed_bytes / source_bytes if source_bytes else "UNKNOWN",
        "elapsed_seconds": time.monotonic() - started,
        "status": "PASS_ROUNDTRIP_SHA",
    }


def run(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # The shared runtime creates the attempt root before launching this
    # worker and places its running receipt/stdout there.  Preserve those
    # guard files while refusing to reuse a prior archive/sidecar.
    output_root.mkdir(parents=True, exist_ok=True)
    compressed_root = output_root / "compressed"
    if compressed_root.exists() or (output_root / "lossless-canary-v1.json").exists() or (output_root / "lossless-canary-v2.json").exists():
        raise FileExistsError(f"refuse to overwrite an existing canary output: {output_root}")
    compressed_root.mkdir()
    results = []
    for sentinel in manifest["sentinels"]:
        sid = sentinel["sentinel_id"]
        sid_root = compressed_root / sid.replace("-", "_")
        sid_root.mkdir()
        for item in sentinel["selected_native_frames"]:
            frame = int(item["frame"])
            source = Path(item["path"]["path"])
            destination = sid_root / f"Part_{frame:04d}.bi4.gz"
            temporary = output_root / f".roundtrip_{sid.replace('-', '_')}_{frame:04d}.bi4"
            result = compress_roundtrip(source, destination, temporary)
            result.update({"sentinel_id": sid, "physical_case_id": sentinel["physical_case_id"], "frame": frame})
            results.append(result)
    by_sentinel = {}
    for sid in manifest["target_sentinels"]:
        entries = [row for row in results if row["sentinel_id"] == sid]
        source_bytes = sum(row["source"]["bytes"] for row in entries)
        compressed_bytes = sum(row["compressed"]["bytes"] for row in entries)
        by_sentinel[sid] = {
            "source_pair_bytes": source_bytes,
            "compressed_pair_bytes": compressed_bytes,
            "pair_ratio": compressed_bytes / source_bytes if source_bytes else "UNKNOWN",
            "six_cell_spatial_temporal_proxy_bytes": compressed_bytes * 3 * 2,
            "proxy_policy": "pair compressed bytes x 3 spatial candidates x 2 same/half-CFL controls; not full-time storage",
        }
    source_total = sum(row["source"]["bytes"] for row in results)
    compressed_total = sum(row["compressed"]["bytes"] for row in results)
    result = {
        "schema": SCHEMA,
        "status": "PASS" if all(row["status"] == "PASS_ROUNDTRIP_SHA" for row in results) else "FAIL",
        "manifest": file_record(manifest_path),
        "current_head": git_commit(),
        "selected_file_count": len(results),
        "selected_source_bytes": source_total,
        "compressed_bytes": compressed_total,
        "compression_ratio_compressed_over_source": compressed_total / source_total if source_total else "UNKNOWN",
        "actual_output_tree_bytes": sum(path.stat().st_size for path in output_root.rglob("*") if path.is_file()),
        "per_sentinel": by_sentinel,
        "planning_proxy_total_bytes": sum(row["six_cell_spatial_temporal_proxy_bytes"] for row in by_sentinel.values()),
        "planning_proxy_policy": "lossless pair observation x 3 spatial candidates x 2 temporal control pairs; full-time/native/typed campaign cost UNKNOWN",
        "roundtrip_results": results,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "source_deleted": False,
        "scientific_qualification": "UNKNOWN",
    }
    result["schema"] = "ds02.stage2.native-lossless-canary.v2"
    atomic_json(output_root / "lossless-canary-v2.json", result)
    return result


def build_request(output_dir: Path, manifest_path: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        CURRENT_PATH,
        REVIEW_PATH,
        QUALITY_PATH,
        manifest_path,
    ]
    for sentinel in manifest["sentinels"]:
        inputs.extend(Path(item["path"]["path"]) for item in sentinel["selected_native_frames"])
    unique = []
    seen = set()
    for path in inputs:
        path = path.resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise FileNotFoundError(path)
            unique.append(path)
            seen.add(str(path))
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "infra",
        "case_id": "STAGE2_NATIVE_LOSSLESS_CANARY_V2",
        "attempt_id": "stage2-native-lossless-canary-v2-001",
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 2 * GiB,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")), str(Path(__file__).resolve()), "--run", "--manifest", str(manifest_path), "--output-root", "{attempt_root}"],
        "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256_file(path) for path in unique},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 1800 / 3600,
            "estimated_new_storage_bytes": 2 * GiB,
        },
        "scope": {
            "selected_sentinels": manifest["target_sentinels"],
            "selected_frames": "frame0 and exact CURRENT last frame only",
            "source_total_bytes": manifest["source_total_bytes"],
            "lossless_roundtrip_required": True,
            "gencase_or_solver_launch": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
            "scientific_qualification": "UNKNOWN",
        },
    }
    atomic_json(output_dir / "stage2-native-lossless-canary-v2.json", request)
    print(json.dumps({"status": "PASS", "request": str(output_dir / "stage2-native-lossless-canary-v2.json"), "inputs": len(unique), "source_bytes": manifest["source_total_bytes"]}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--build-request-dir", type=Path)
    args = parser.parse_args()
    if args.prepare:
        manifest = prepare()
        print(json.dumps({"status": "PASS", "manifest": str(INPUT_ROOT / "manifest.json"), "source_bytes": manifest["source_total_bytes"]}, ensure_ascii=False))
        return 0
    if args.run:
        if args.manifest is None or args.output_root is None:
            raise SystemExit("--run requires --manifest and --output-root")
        result = run(args.manifest, args.output_root)
        print(json.dumps({"status": result["status"], "output": str(args.output_root / "lossless-canary-v2.json"), "selected_file_count": result["selected_file_count"], "compressed_bytes": result["compressed_bytes"]}, ensure_ascii=False))
        return int(result["status"] != "PASS")
    if args.build_request_dir is None:
        raise SystemExit("choose --prepare, --run, or --build-request-dir")
    manifest = args.manifest or (INPUT_ROOT / "manifest.json")
    build_request(args.build_request_dir, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
