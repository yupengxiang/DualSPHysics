#!/usr/bin/env python3
"""V10 runtime wrapper binding the complete Git-helper closure.

V9 remains immutable.  This forward wrapper uses V3's whole-lifecycle
bounded subprocess cleanup and records all three Git helper source files:
V1 report assembly, V2 compatibility adapter, and V3 cleanup primitive.
The consumed V8 reservation, source pre/post hash, child cleanup and ledger
accounting remain the single implementation of those contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import ds_data02_git_launch_state_v1 as git_v1  # noqa: E402
import ds_data02_git_launch_state_v2 as git_v2  # noqa: E402
import ds_data02_git_launch_state_v3 as git_v3  # noqa: E402
import ds_data02_runtime_v9_git_bound as runtime_v9  # noqa: E402


v8 = runtime_v9.v8
V10_RUNTIME_PATH = str(Path(__file__).resolve())
V9_RUNTIME_PATH = str(Path(runtime_v9.__file__).resolve())
V8_RUNTIME_PATH = str(Path(v8.__file__).resolve())
V6_RUNTIME_PATH = str(Path(v8.V6_RUNTIME_PATH).resolve())
V2_RUNTIME_PATH = str(Path(v8.v6.base.__file__).resolve())
V1_HELPER_PATH = str(Path(git_v1.__file__).resolve())
V2_HELPER_PATH = str(Path(git_v2.__file__).resolve())
V3_HELPER_PATH = str(Path(git_v3.__file__).resolve())
SCHEMA = "ds02.stage2.runtime-v10-git-bound.v1"


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_with_closure(request: dict[str, Any], *, approval_context: dict[str, Any] | None = None):
    actual = runtime_v9._original_validate(request, approval_context=approval_context)
    required = {
        V10_RUNTIME_PATH: "runtime_v10_git_bound",
        V9_RUNTIME_PATH: "runtime_v9_git_bound",
        V8_RUNTIME_PATH: "runtime_v8",
        V6_RUNTIME_PATH: "runtime_v6",
        V2_RUNTIME_PATH: "runtime_v2",
        V1_HELPER_PATH: "git_snapshot_v1",
        V2_HELPER_PATH: "git_snapshot_v2",
        V3_HELPER_PATH: "git_snapshot_v3",
    }
    missing = [role for path, role in required.items() if path not in actual]
    if missing:
        raise ValueError("V10 runtime closure missing bound files: " + ", ".join(missing))
    return actual


def _write_v10_receipt(path: Path, value: dict[str, Any]) -> None:
    """Write one V8 receipt with V9 compatibility and V10 source closure."""
    value["schema"] = "ds02.execution-receipt.v1"
    value["runner_source"] = V10_RUNTIME_PATH
    value["runner_sha256"] = _sha256(V10_RUNTIME_PATH)
    snapshots = list(runtime_v9._active_snapshots)
    value["runtime_v9_git_bound"] = {
        "schema": runtime_v9.SCHEMA,
        "wrapper_path": V10_RUNTIME_PATH,
        "wrapper_sha256": _sha256(V10_RUNTIME_PATH),
        "v9_compatibility_path": V9_RUNTIME_PATH,
        "v9_compatibility_sha256": _sha256(V9_RUNTIME_PATH),
        "v8_path": V8_RUNTIME_PATH,
        "v8_sha256": _sha256(V8_RUNTIME_PATH),
        "v6_path": V6_RUNTIME_PATH,
        "v6_sha256": _sha256(V6_RUNTIME_PATH),
        "v2_path": V2_RUNTIME_PATH,
        "v2_sha256": _sha256(V2_RUNTIME_PATH),
        "git_helper_path": V3_HELPER_PATH,
        "git_helper_sha256": _sha256(V3_HELPER_PATH),
        "snapshots": snapshots,
        "snapshot_count": len(snapshots),
        "scope_contract": "INPUT_SCOPE_ONLY; external input files remain V8 pre/post SHA bound",
    }
    value["runtime_v10_git_bound"] = {
        "schema": SCHEMA,
        "wrapper_path": V10_RUNTIME_PATH,
        "wrapper_sha256": _sha256(V10_RUNTIME_PATH),
        "compatibility_v9_path": V9_RUNTIME_PATH,
        "compatibility_v9_sha256": _sha256(V9_RUNTIME_PATH),
        "git_helpers": [
            {"role": "git_snapshot_v1", "path": V1_HELPER_PATH, "sha256": _sha256(V1_HELPER_PATH)},
            {"role": "git_snapshot_v2", "path": V2_HELPER_PATH, "sha256": _sha256(V2_HELPER_PATH)},
            {"role": "git_snapshot_v3", "path": V3_HELPER_PATH, "sha256": _sha256(V3_HELPER_PATH)},
        ],
        "cleanup_contract": {
            "owned_group_cleanup_on_timeout": True,
            "owned_group_cleanup_on_signal": True,
            "leader_exit_descendant_cleanup": True,
            "failed_git_observation_is_not_clean_claim": True,
        },
        "snapshot_count": len(snapshots),
    }
    # This is the consumed V8 terminal writer.  No second ledger owner or
    # receipt is introduced.
    v8.v6._write_terminal_receipt(path, value)


def run_request(request_path: str | Path, *, data_root=None,
                parent_pid: int | None = None) -> dict[str, Any]:
    """Run V9/V8 with V3 and a complete V1/V2/V3 closure check."""
    old_snapshot = runtime_v9.git_snapshot
    old_validate = runtime_v9._validate_with_closure
    old_writer = runtime_v9._write_v9_receipt
    old_runtime_path = runtime_v9.RUNTIME_PATH
    runtime_v9.git_snapshot = git_v3
    runtime_v9._validate_with_closure = _validate_with_closure
    runtime_v9._write_v9_receipt = _write_v10_receipt
    runtime_v9.RUNTIME_PATH = V10_RUNTIME_PATH
    try:
        return runtime_v9.run_request(request_path, data_root=data_root, parent_pid=parent_pid)
    finally:
        runtime_v9.git_snapshot = old_snapshot
        runtime_v9._validate_with_closure = old_validate
        runtime_v9._write_v9_receipt = old_writer
        runtime_v9.RUNTIME_PATH = old_runtime_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=v8.DATA_ROOT)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    result = run_request(args.request, data_root=args.data_root, parent_pid=args.parent_pid)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return int(result.get("status") != "completed")


if __name__ == "__main__":
    raise SystemExit(main())

