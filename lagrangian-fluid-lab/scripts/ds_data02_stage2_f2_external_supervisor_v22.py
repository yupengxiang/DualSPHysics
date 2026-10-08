#!/usr/bin/env python3
"""Forward v21 with a real cold-helper cleanup grace binding.

The consumed v21 supervisor gives the v14 child its configured 25 second
cleanup window, but its v20 build/apply helper path still used a hard-coded
two second TERM→KILL interval.  This wrapper keeps the v21 request schema and
accounting implementation, while replacing only that helper process-group
stop with the request's 25 second cold cleanup allowance.  It does not create
a second ledger or bypass v21's parent charge, source checks, strace, or
terminal predicate.

The wrapper is itself bound into a fresh request.  A parent must invoke this
file in a fresh subprocess with the v22 request; importing an already-loaded
v21 module from an original checkout is not a valid portable run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V21_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v21.py")
V21_SPEC = importlib.util.spec_from_file_location("ds02_external_supervisor_v21_for_v22", V21_PATH)
if V21_SPEC is None or V21_SPEC.loader is None:  # pragma: no cover - packaging failure
    raise RuntimeError(f"cannot import immutable v21 supervisor: {V21_PATH}")
V21 = importlib.util.module_from_spec(V21_SPEC)
V21_SPEC.loader.exec_module(V21)

SCHEMA = V21.SCHEMA
UNKNOWN = V21.UNKNOWN
V22Error = V21.SupervisorError
HELPER_CLEANUP_GRACE_SECONDS = 25.0


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V21.canonical_sha(value)


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise V22Error(f"v22 source binding is missing: {target}")
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(target),
            "source_kind": "static", "content_scope": "content_sha256"}


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V22Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise V22Error(f"refusing existing v22 request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def build_request(v14_path: Path | str, output_path: Path | str, *,
                  output_root: Path | str, max_wall_seconds: float = 6000.0) -> dict[str, Any]:
    """Build a v21-compatible request with v22 helper cleanup binding."""
    value = V21.build_request(v14_path, output_path, output_root=output_root,
                              max_wall_seconds=max_wall_seconds)
    request = load_json(output_path)
    bindings = list(request.get("static_bindings", []))
    bindings.append(_binding(SCRIPT, "external_supervisor_v22"))
    request["static_bindings"] = bindings
    request["forward_runtime"] = {
        "schema": "ds02.stage2.f2-external-supervisor-runtime.v22",
        "path": str(SCRIPT),
        "sha256": sha256_file(SCRIPT),
        "immutable": True,
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
        "cold_terminal_scope": "v20 build/apply helper groups receive the same 25 s TERM→KILL allowance as v14 child cleanup",
    }
    execution = dict(request.get("execution", {}))
    execution["outer_entrypoint"] = str(SCRIPT)
    execution["outer_entrypoint_sha256"] = sha256_file(SCRIPT)
    execution["outer_command"] = [str(request.get("parent_resource_binding", {}).get("python", "<venv-python>")),
                                   str(SCRIPT), "run", "--request", "<v22-request>",
                                   "--parent-pid", "<supervising-parent-pid>"]
    execution["helper_cleanup_grace_seconds"] = HELPER_CLEANUP_GRACE_SECONDS
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "v22 forwards the v21 accounting/terminal implementation and only replaces its hard-coded helper cleanup grace.",
        "The parent deadline still bounds child/helper execution; cleanup and ledger finalization are reported separately when the OS delays them.",
    ]
    request["sha256"] = canonical_sha(request)
    # v21 wrote the initial file; it is still an unconsumed output owned by
    # this builder, so replace only that newly-created file after all fields
    # are sealed.  Existing requests are rejected by v21 and _write_new.
    output = Path(output_path).expanduser().resolve()
    output.unlink()
    _write_new(output, request)
    return request


def _run_process_group(command: Sequence[str], *, cwd: Path, timeout: float) -> dict[str, Any]:
    """Run a v20 helper with the v22 cold cleanup interval."""
    proc = subprocess.Popen(list(command), cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    cleanup: dict[str, Any] = {}
    try:
        stdout, stderr = proc.communicate(timeout=max(0.001, float(timeout)))
    except subprocess.TimeoutExpired as error:
        cleanup = V21._stop_group(proc, grace=HELPER_CLEANUP_GRACE_SECONDS)
        raise V21.SupervisorDeadline(f"bound helper deadline exceeded: {command[0]}") from error
    return {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr,
            "cleanup": cleanup}


def _install_forward_helpers() -> None:
    V21._run_process_group = _run_process_group


def validate_request(request_path: Path | str, *, verify_content: bool = False) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA:
        raise V22Error("v22 accepts only the v21 supervisor schema")
    forward = request.get("forward_runtime")
    if not isinstance(forward, Mapping) or forward.get("path") != str(SCRIPT):
        raise V22Error("v22 forward runtime binding is missing")
    if forward.get("sha256") != sha256_file(SCRIPT):
        raise V22Error("v22 forward runtime SHA differs")
    if float(forward.get("helper_cleanup_grace_seconds", 0.0) or 0.0) < HELPER_CLEANUP_GRACE_SECONDS:
        raise V22Error("v22 helper cleanup grace is less than 25 seconds")
    if not isinstance(request.get("static_bindings"), list) or not any(
            isinstance(item, Mapping) and item.get("role") == "external_supervisor_v22"
            for item in request["static_bindings"]):
        raise V22Error("v22 static source binding is missing")
    # V21's validator checks the immutable v14 graph, ledger, output paths,
    # source hashes, policy, and 25 second child grace.  It does not open H5.
    return V21._validate_request(request, verify_content=verify_content)


def run(request_path: Path | str, *, parent_pid: int | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    checked = validate_request(request_file, verify_content=True)
    _install_forward_helpers()
    return V21.run(request_file, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v14-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--verify-content", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v14_request, args.output,
                                  output_root=args.output_root,
                                  max_wall_seconds=args.max_wall_seconds)
            result = {"status": value.get("status"), "sha256": value["sha256"],
                      "path": str(args.output.expanduser().resolve()),
                      "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS}
        elif args.command == "validate":
            checked = validate_request(args.request, verify_content=args.verify_content)
            result = {"status": "VALIDATED_V22", "v14": str(checked["v14_path"]),
                      "helper_cleanup_grace_seconds": checked["child_cleanup_grace_seconds"]}
        else:
            value = run(args.request, parent_pid=args.parent_pid)
            result = value
    except (V22Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith(("READY_", "VALIDATED_", "COMPLETED_")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
