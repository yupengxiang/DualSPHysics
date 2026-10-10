#!/usr/bin/env python3
"""V9 source wrapper for the bounded Git launch provenance contract.

The consumed V8 runner owns reservation ordering, content pre/post hashing,
child cancellation, and terminal ledger accounting.  This additive wrapper
leaves that implementation unchanged and replaces only its unbounded Git
provenance call with :mod:`ds_data02_git_launch_state_v1`.

The Git report is always ``INPUT_SCOPE_ONLY``: the scope is the exact subset
of ``request.input_files`` that lies under ``request.worktree_root``.  Inputs
outside the repository remain part of V8's strict content hash gates and are
listed as external inputs in the receipt; they are never silently represented
by a full-worktree clean claim.  A missing HEAD, timeout, output limit, or Git
error fails the attempt after reservation and is preserved in the terminal
receipt as explicit unknown provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import ds_data02_git_launch_state_v2 as git_snapshot  # noqa: E402
import ds_data02_runtime_v8 as v8  # noqa: E402


RUNTIME_PATH = str(Path(__file__).resolve())
V8_RUNTIME_PATH = str(Path(v8.__file__).resolve())
V6_RUNTIME_PATH = str(Path(v8.V6_RUNTIME_PATH).resolve())
V2_RUNTIME_PATH = str(Path(v8.v6.base.__file__).resolve())
GIT_HELPER_PATH = str(Path(git_snapshot.__file__).resolve())
SCHEMA = "ds02.stage2.runtime-v9-git-bound.v1"


class RuntimeV9GitProvenanceError(RuntimeError):
    """The bounded Git snapshot did not produce mandatory HEAD evidence."""


_active_snapshots: list[dict[str, Any]] = []
_active_request: dict[str, Any] | None = None
_original_validate = v8.validate_request


def _sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_input_files(request: Mapping[str, Any]) -> list[Path]:
    values = request.get("input_files")
    if not isinstance(values, list) or not values:
        raise ValueError("input_files must be a non-empty list")
    result: list[Path] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("input_files must contain paths")
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError("input file missing: " + str(path))
        result.append(path)
    return result


def _scoped_paths(root: Path, input_files: Sequence[Path]) -> tuple[list[str], list[str]]:
    """Split exact repository-relative Git paths from external strict inputs."""
    root = root.expanduser().resolve()
    inside: list[str] = []
    outside: list[str] = []
    for path in input_files:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            outside.append(str(path))
        else:
            if not relative or relative == ".":
                raise ValueError("repository root itself cannot be an input file")
            inside.append(relative)
    if len(set(inside)) != len(inside):
        raise ValueError("input_files contains duplicate repository paths")
    return inside, outside


def _request_scope(request: Mapping[str, Any], root: Path) -> dict[str, Any]:
    input_files = _resolve_input_files(request)
    inside, outside = _scoped_paths(root, input_files)
    if not inside:
        raise ValueError("at least one bound input_file must be inside worktree_root for Git scope")
    return {
        "mode": "INPUT_SCOPE_ONLY",
        "input_paths": inside,
        "full_worktree_claim": False,
        "external_inputs_excluded_from_git_scope": outside,
    }


def _git_timeout(request: Mapping[str, Any]) -> float:
    value = request.get("git_snapshot_timeout_seconds", 2.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("git_snapshot_timeout_seconds must be positive")
    max_wall = request.get("max_wall_seconds")
    if isinstance(max_wall, (int, float)) and value > max_wall:
        raise ValueError("Git snapshot timeout cannot exceed request max_wall_seconds")
    return float(value)


def _git_executable(request: Mapping[str, Any]) -> str:
    executable = request.get("git_snapshot_executable", "git")
    if not isinstance(executable, str) or not executable:
        raise ValueError("git_snapshot_executable must be a non-empty string")
    # A non-system executable is only allowed in an explicitly manufactured
    # timeout test.  Production requests use the host Git binary and bind its
    # repository-relative sources through input_files.
    if executable != "git" and not bool(request.get("git_snapshot_test_only", False)):
        raise ValueError("custom git_snapshot_executable requires git_snapshot_test_only")
    return executable


def _scoped_git_launch_state(root: str | os.PathLike[str]) -> dict[str, Any]:
    request = _active_request
    if request is None:
        raise RuntimeV9GitProvenanceError("Git snapshot requested outside an active V9 request")
    root_path = Path(root).expanduser().resolve()
    scope = _request_scope(request, root_path)
    report = git_snapshot.bounded_git_launch_state(
        root_path,
        timeout_seconds=_git_timeout(request),
        input_paths=scope["input_paths"],
        git_executable=_git_executable(request),
    )
    report["scope"] = scope
    report["contract"] = {
        "head_mandatory": True,
        "status_and_diff_timeout_is_unknown": True,
        "full_worktree_clean_claim": False,
        "external_inputs_are_v8_hash_bound": True,
    }
    _active_snapshots.append(report)
    if report.get("status") != "OK" or not report.get("commit"):
        raise RuntimeV9GitProvenanceError(
            "bounded Git launch provenance unavailable: " + json.dumps(report, sort_keys=True)
        )
    return report


def _validate_with_closure(request: dict[str, Any], *, approval_context: dict[str, Any] | None = None):
    actual = _original_validate(request, approval_context=approval_context)
    required = {
        RUNTIME_PATH: "runtime_v9_git_bound",
        V8_RUNTIME_PATH: "runtime_v8",
        V6_RUNTIME_PATH: "runtime_v6",
        V2_RUNTIME_PATH: "runtime_v2",
        GIT_HELPER_PATH: "git_snapshot_helper",
    }
    missing = [role for path, role in required.items() if path not in actual]
    if missing:
        raise ValueError("V9 runtime closure missing bound files: " + ", ".join(missing))
    return actual


def _write_v9_receipt(path: Path, value: dict[str, Any]) -> None:
    value["schema"] = "ds02.execution-receipt.v1"
    value["runner_source"] = RUNTIME_PATH
    value["runner_sha256"] = _sha256(RUNTIME_PATH)
    value["runtime_v9_git_bound"] = {
        "schema": SCHEMA,
        "wrapper_path": RUNTIME_PATH,
        "wrapper_sha256": _sha256(RUNTIME_PATH),
        "v8_path": V8_RUNTIME_PATH,
        "v8_sha256": _sha256(V8_RUNTIME_PATH),
        "v6_path": V6_RUNTIME_PATH,
        "v6_sha256": _sha256(V6_RUNTIME_PATH),
        "v2_path": V2_RUNTIME_PATH,
        "v2_sha256": _sha256(V2_RUNTIME_PATH),
        "git_helper_path": GIT_HELPER_PATH,
        "git_helper_sha256": _sha256(GIT_HELPER_PATH),
        "snapshots": list(_active_snapshots),
        "snapshot_count": len(_active_snapshots),
        "scope_contract": "INPUT_SCOPE_ONLY; external input files remain V8 pre/post SHA bound",
    }
    # V8's fixed-point writer is the consumed accounting implementation.  Do
    # not write a second receipt or mutate the shared ledger here.
    v8.v6._write_terminal_receipt(path, value)


def run_request(request_path: str | os.PathLike[str], *, data_root=None,
                parent_pid: int | None = None) -> dict[str, Any]:
    """Run the immutable V8 flow with bounded Git provenance."""
    global _active_request, _active_snapshots
    request_path = Path(request_path).expanduser().resolve()
    request = json.loads(request_path.read_text())
    if not isinstance(request, dict):
        raise ValueError("request JSON must be an object")
    # Validate the scope before entering V8, while the request is still cheap;
    # V8 repeats all content hashes only after the same-parent reservation.
    _request_scope(request, Path(str(request["worktree_root"])).expanduser().resolve())
    _active_request = request
    _active_snapshots = []
    originals = {
        "git_launch_state": v8.base.git_launch_state,
        "validate_request": v8.validate_request,
        "write_terminal_receipt": v8._write_terminal_receipt,
        "runtime_path": v8.RUNTIME_PATH,
    }
    global _original_validate
    _original_validate = originals["validate_request"]
    v8.base.git_launch_state = _scoped_git_launch_state
    v8.validate_request = _validate_with_closure
    v8._write_terminal_receipt = _write_v9_receipt
    v8.RUNTIME_PATH = RUNTIME_PATH
    try:
        return v8.run_request(request_path, data_root=data_root or v8.DATA_ROOT, parent_pid=parent_pid)
    finally:
        v8.base.git_launch_state = originals["git_launch_state"]
        v8.validate_request = originals["validate_request"]
        v8._write_terminal_receipt = originals["write_terminal_receipt"]
        v8.RUNTIME_PATH = originals["runtime_path"]
        _active_request = None
        _active_snapshots = []


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
