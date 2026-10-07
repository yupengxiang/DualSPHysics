#!/usr/bin/env python3
"""Offline v15 replay runner with a complete relocated source overlay.

The v15 runner's inherited mapper rewrites ``source_files`` and HDF5 only.
This entrypoint first applies the v18 recursive mapper, which also rewrites
the nested motion-engine and source-code bindings, then imports the copied
v15/v14 modules from the bundle runtime directory.  Original absolute paths
are retained only as profile provenance and are rejected if they remain in
the request that reaches the consumer.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping


class ReplayV18BindingError(ValueError):
    """Raised when the relocated full-window consumer cannot be bound."""


def _runtime_roots() -> tuple[Path, Path]:
    replay_root = Path(__file__).resolve().parent
    portable_root = replay_root.parent / "portable"
    return replay_root, portable_root


def _load_portable() -> Any:
    _, portable_root = _runtime_roots()
    sys.path.insert(0, str(portable_root))
    path = portable_root / "ds_data02_stage2_f2_portable_v18.py"
    spec = importlib.util.spec_from_file_location("ds_data02_stage2_f2_portable_v18_runtime", path)
    if spec is None or spec.loader is None:
        raise ReplayV18BindingError(f"portable v18 worker is unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_replay() -> Any:
    replay_root, _ = _runtime_roots()
    sys.path.insert(0, str(replay_root))
    try:
        import ds_data02_stage2_f2_replay_v15 as replay  # type: ignore
    except ImportError as error:
        raise ReplayV18BindingError("copied v15 replay module is unavailable") from error
    return replay


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayV18BindingError(f"cannot read JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReplayV18BindingError(f"JSON object required: {path}")
    return value


def _path_map(path: Path) -> dict[str, str]:
    value = _load_json(path)
    if isinstance(value.get("path_map"), Mapping):
        value = value["path_map"]
    if not isinstance(value, Mapping):
        raise ReplayV18BindingError("path map must be an object or a receipt containing path_map")
    result = {str(key): str(item) for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise ReplayV18BindingError("path map contains an empty role or path")
    return result


def run(profile: Mapping[str, Any], request: Mapping[str, Any], path_map: Mapping[str, str], *,
        io_slot_approved: bool = False, initial_frame_only: bool = False) -> dict[str, Any]:
    portable = _load_portable()
    try:
        portable.verify_relocated_profile(profile, path_map, full_replay=io_slot_approved)
        bound_request = portable.relocate_request_for_consumer(request, profile, path_map)
    except (OSError, portable.PortableV18BindingError) as error:
        raise ReplayV18BindingError(str(error)) from error
    replay = _load_replay()
    try:
        bound = replay.validate_request_v15(bound_request, verify_sources=True, verify_hdf5_stat=True)
    except Exception as error:  # v15 has its own binding exception class
        raise ReplayV18BindingError(f"v15 preflight rejected relocated request: {error}") from error
    if io_slot_approved:
        try:
            result = (replay.read_hdf5_initial_frame_v15(bound_request, io_slot_approved=True)
                      if initial_frame_only else replay.read_hdf5_window_v15(bound_request, io_slot_approved=True))
        except Exception as error:  # preserve the v15 operator's detailed failure
            raise ReplayV18BindingError(f"v15 relocated replay failed: {error}") from error
        result["runner_status"] = "COMPLETE_PROVISIONAL_H5_READ"
        result["trajectory_read"] = True
        result["source_validation"] = "V18_RECURSIVE_ROLE_OVERLAY_AND_STRICT_HASH_STAT_BEFORE_READ"
        result["original_path_fallback"] = "FORBIDDEN"
        return result
    return {
        "schema": "ds02.stage2.f2-s1-replay-runner-report.v18",
        "status": "VALIDATED_PENDING_IO_SLOT",
        "request_id": bound_request.get("request_id"),
        "request_schema": bound_request.get("schema"),
        "source_validation": "V18_RECURSIVE_ROLE_OVERLAY_STRICT_HASH_STAT_NO_HDF5_CONTENT_READ",
        "verified_source_count": len(bound.get("_verified_sources", [])),
        "hdf5_content_sha256": bound.get("_verified_hdf5", {}).get("content_sha256"),
        "trajectory_read": False,
        "io_slot_approved": False,
        "original_path_fallback": "FORBIDDEN",
        "relocation": bound_request.get("relocation"),
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--io-slot-approved", action="store_true")
    parser.add_argument("--initial-frame-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing replay output: {args.output}")
    try:
        result = run(_load_json(args.profile), _load_json(args.request), _path_map(args.path_map),
                     io_slot_approved=args.io_slot_approved, initial_frame_only=args.initial_frame_only)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False,
                      default=lambda value: value.tolist() if hasattr(value, "tolist") else str(value))
            stream.write("\n")
    except (OSError, ReplayV18BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
