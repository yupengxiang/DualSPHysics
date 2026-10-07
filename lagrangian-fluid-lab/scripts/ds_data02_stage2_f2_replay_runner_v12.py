#!/usr/bin/env python3
"""Guarded v12 F2-S1 replay entrypoint.

The runner verifies every source hash and HDF5 stat before producing a
pending report.  It opens trajectory HDF5 only when the parent stage2guard
passes ``--io-slot-approved``; validation by itself never reads HDF5 content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ds_data02_stage2_f2_replay_v12 import (  # noqa: E402
    ReplayV12BindingError,
    read_hdf5_window,
    relocate_source_bound_request,
    validate_replay_request,
)


def _read_path_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    value = json.loads(path.read_text())
    if isinstance(value, Mapping) and isinstance(value.get("path_map"), Mapping):
        value = value["path_map"]
    if not isinstance(value, Mapping):
        raise ReplayV12BindingError("path-map must be an object or {path_map: object}")
    result = {str(key): str(item) for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise ReplayV12BindingError("path-map contains an empty key or path")
    return result


def run(request: Mapping[str, Any], *, path_map: Mapping[str, str] | None = None,
        io_slot_approved: bool = False) -> dict[str, Any]:
    bound_request = (relocate_source_bound_request(request, path_map)
                     if path_map else dict(request))
    # This is intentionally strict: a pending report may be source-bound only
    # after small-file hashes and HDF5 bytes/mtime have been checked.  No HDF5
    # dataset is opened by validate_replay_request.
    bound = validate_replay_request(bound_request, verify_sources=True,
                                    verify_hdf5_stat=True)
    if io_slot_approved:
        result = read_hdf5_window(bound_request, io_slot_approved=True)
        result["runner_status"] = "COMPLETE_PROVISIONAL_H5_READ"
        result["trajectory_read"] = True
        result["source_validation"] = "STRICT_HASH_AND_STAT_BEFORE_READ"
        return result
    return {
        "schema": "ds02.stage2.f2-s1-replay-runner-report.v12",
        "status": "VALIDATED_PENDING_IO_SLOT",
        "request_id": bound_request.get("request_id"),
        "request_schema": bound_request.get("schema"),
        "source_validation": "STRICT_HASH_AND_STAT_NO_HDF5_CONTENT_READ",
        "verified_source_count": len(bound.get("_verified_sources", [])),
        "hdf5_content_sha256": bound["_verified_hdf5"].get("content_sha256"),
        "trajectory_read": False,
        "io_slot_approved": False,
        "relocation": bound_request.get("relocation"),
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--path-map", type=Path)
    parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text())
        report = run(request, path_map=_read_path_map(args.path_map),
                     io_slot_approved=args.io_slot_approved)
    except (OSError, json.JSONDecodeError, ReplayV12BindingError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False,
                                      default=lambda value: value.tolist() if hasattr(value, "tolist") else str(value)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
