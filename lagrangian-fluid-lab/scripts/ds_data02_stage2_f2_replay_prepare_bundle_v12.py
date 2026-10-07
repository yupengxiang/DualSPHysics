#!/usr/bin/env python3
"""Create a verifiable v12 relocation overlay for a source-bound request.

Small source files are copied and SHA-256 checked.  Copying trajectory HDF5
is an explicit parent-guard action and requires both ``--copy-hdf5`` and
``--io-slot-approved``; the default operation never touches HDF5 content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output-path-map", type=Path, required=True)
    parser.add_argument("--copy-hdf5", action="store_true")
    parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args()
    request: dict[str, Any] = json.loads(args.request.read_text())
    if args.copy_hdf5 and not args.io_slot_approved:
        parser.error("--copy-hdf5 requires parent --io-slot-approved")
    args.bundle_root.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    records = []
    for item in request.get("source_files", []):
        role, original = str(item["role"]), Path(item["path"])
        if original.suffix.lower() in {".h5", ".hdf5"}:
            parser.error("trajectory HDF5 must use trajectory_h5 binding, not source_files")
        expected = str(item["sha256"])
        if sha256(original) != expected:
            parser.error(f"original source SHA differs before copy: {role}")
        destination = args.bundle_root / "sources" / role / original.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        actual = sha256(destination)
        if actual != expected:
            parser.error(f"copied source SHA differs: {role}")
        mapping[role] = str(destination.resolve())
        records.append({"role": role, "original_path": str(original),
                        "relocated_path": str(destination.resolve()),
                        "sha256": expected, "bytes": destination.stat().st_size})
    h5 = request.get("trajectory_h5")
    h5_record: dict[str, Any] = {"status": "NOT_COPIED; parent HDF5 slot required"}
    if args.copy_hdf5:
        original = Path(h5["path"])
        destination = args.bundle_root / "trajectory.h5"
        if original.stat().st_size != int(h5["bytes"]):
            parser.error("original HDF5 byte size differs from request")
        shutil.copyfile(original, destination)
        if destination.stat().st_size != int(h5["bytes"]):
            parser.error("copied HDF5 byte size differs")
        mapping["trajectory_h5"] = str(destination.resolve())
        h5_record = {"status": "COPIED_PRODUCER_ATTESTED_NO_CONTENT_HASH",
                     "original_path": str(original), "relocated_path": str(destination.resolve()),
                     "bytes": destination.stat().st_size,
                     "producer_declared_sha256": h5["producer_declared_sha256"],
                     "original_mtime_ns": original.stat().st_mtime_ns,
                     "relocated_mtime_ns": destination.stat().st_mtime_ns}
    path_map = {
        "schema": "ds02.stage2.f2-s1-replay-path-map.v12",
        "request_id": request.get("request_id"),
        "request_path": str(args.request.resolve()),
        "path_map": mapping,
        "source_records": records,
        "trajectory_h5": h5_record,
        "status": "READY_FOR_STRICT_RELOCATION_VALIDATION" if not args.copy_hdf5 else "READY_FOR_STRICT_RELOCATION_AND_IO_SLOT",
        "model_invoked": False, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    args.output_path_map.parent.mkdir(parents=True, exist_ok=True)
    args.output_path_map.write_text(json.dumps(path_map, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
