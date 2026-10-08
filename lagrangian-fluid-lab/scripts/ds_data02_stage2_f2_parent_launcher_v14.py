#!/usr/bin/env python3
"""Forward F2 parent launcher with real nested-child cancellation.

The consumed v13 launcher remains immutable.  This v14 entry point validates
its v13 closure through an alias, starts strace as its own process group, sets
PDEATHSIG on that group leader, and handles SIGTERM/SIGINT by giving the
bridge a bounded cooperative cleanup window before killing only that group.
It does not read HDF5/BI4 and remains DEVELOPMENT/UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
V13_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v13.py"
V12_SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v12"
V13_SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v13"
SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v14"
REPORT_SCHEMA = "ds02.stage2.f2-parent-supervised-launch-report.v14"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1
V14_CLEANUP_MIN_SECONDS = 20.0

class ParentLaunchError(RuntimeError):
    pass

class ParentLaunchCancelled(ParentLaunchError):
    pass

def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()

def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParentLaunchError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ParentLaunchError(f"JSON object required: {target}")
    return value

def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ParentLaunchError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target

def _load_v13_module():
    spec = importlib.util.spec_from_file_location("ds02_parent_launcher_v13_for_v14", V13_PATH)
    if spec is None or spec.loader is None:
        raise ParentLaunchError(f"cannot import v13 launcher: {V13_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

V13 = _load_v13_module()

def _source_binding(role: str, path: Path | str) -> dict[str, Any]:
    spelling = Path(path).expanduser()
    resolved = spelling.resolve()
    if not resolved.is_file():
        raise ParentLaunchError(f"bound source is missing: {resolved}")
    stat = resolved.stat()
    return {"role": role, "path": str(spelling), "resolved_path": str(resolved),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": sha256_file(resolved), "source_kind": "static"}

def _alias_as_v13(request: Mapping[str, Any]) -> dict[str, Any]:
    alias = copy.deepcopy(dict(request))
    alias["schema"] = V13_SCHEMA
    alias["sha256"] = V13.canonical_sha(alias)
    return alias

def _validate_launch(request: Mapping[str, Any], *, verify_content: bool) -> tuple[dict[str, Any], Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("unsupported or non-ready v14 launch request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ParentLaunchError("v14 launch must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ParentLaunchError("v14 launch cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v14 launch canonical SHA differs")
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list):
        raise ParentLaunchError("v14 source closure is incomplete")
    own = next((item for item in bindings if isinstance(item, Mapping) and
                item.get("role") == "parent_launcher_v14"), None)
    if not isinstance(own, Mapping):
        raise ParentLaunchError("v14 source closure lacks parent_launcher_v14")
    own_path = Path(str(own.get("path", ""))).expanduser().resolve()
    if own_path != Path(__file__).resolve():
        raise ParentLaunchError("v14 launcher source binding differs")
    if verify_content and sha256_file(own_path) != str(own.get("sha256")):
        raise ParentLaunchError("v14 launcher SHA differs")
    alias = _alias_as_v13(request)
    # The old validator checks all inherited v13/v12 source bindings and the
    # immutable v12/v11 closure.  The v14-only binding is harmless there.
    v11, module = V13._validate_launch(alias, verify_content=verify_content)
    trace = request.get("trace")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    if not isinstance(trace, Mapping) or not isinstance(storage, Mapping) or not isinstance(execution, Mapping):
        raise ParentLaunchError("v14 trace/storage/execution binding is incomplete")
    trace_path = Path(str(trace.get("path", ""))).expanduser().resolve()
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if trace_path.parent != external:
        raise ParentLaunchError("v14 parent OS trace must be directly under external filesystem")
    sidecar = Path(str(storage.get("finalization_sidecar", ""))).expanduser().resolve()
    if sidecar.exists() or trace_path.exists():
        raise ParentLaunchError("v14 trace or sidecar already exists")
    grace = execution.get("cleanup_grace_seconds")
    if isinstance(grace, bool) or not isinstance(grace, (int, float)) or float(grace) < V14_CLEANUP_MIN_SECONDS:
        raise ParentLaunchError("v14 cleanup grace must be at least 20 seconds")
    return v11, module

def _set_parent_death_signal(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install parent-death signal")
    if os.getppid() != int(parent_pid):
        raise ParentLaunchCancelled("supervising parent already exited")

def _terminate_child_group_bounded(child: subprocess.Popen[str], grace: float) -> dict[str, Any]:
    result: dict[str, Any] = {"sigterm_sent": False, "grace_seconds": float(grace),
                              "forced_sigkill": False, "exited_after_cleanup": False,
                              "owned_process_group": None}
    try:
        pgid = os.getpgid(child.pid)
        result["owned_process_group"] = pgid
        os.killpg(pgid, signal.SIGTERM)
        result["sigterm_sent"] = True
    except (ProcessLookupError, PermissionError):
        result["exited_after_cleanup"] = child.poll() is not None
        return result
    deadline = time.monotonic() + max(V14_CLEANUP_MIN_SECONDS, float(grace))
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if child.poll() is None:
        result["forced_sigkill"] = True
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        child.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        result["reap_timeout"] = True
    result["exited_after_cleanup"] = child.poll() is not None
    return result

def _parse_child_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None

def _trace_record(request: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(request["trace"]["path"])).expanduser().resolve()
    return {"path": str(path), "exists": path.is_file(),
            "bytes": int(path.stat().st_size) if path.is_file() else 0,
            "sha256": sha256_file(path) if path.is_file() else None,
            "single_file_follow_fork": True}

def _write_sidecar(request: Mapping[str, Any], cleanup: Mapping[str, Any],
                   trace: Mapping[str, Any], accounting: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(request["storage_scope"]["finalization_sidecar"])).expanduser().resolve()
    value: dict[str, Any] = {
        "schema": "ds02.stage2.f2-parent-trace-finalization.v14",
        "request_sha256": request.get("sha256"), "attempt_id": request.get("attempt_id"),
        "trace": dict(trace), "cleanup": dict(cleanup),
        "terminal_accounting": dict(accounting),
        "cooperative_cancel_scope": "SIGTERM grace then SIGKILL to this launcher's own strace process group",
        "pdeathsig": "SIGTERM installed on strace group leader; bridge descendants are group-owned",
        "supplemental_charge_required": True,
        "model_invoked": False, "cfd_invoked": False, "qualification": copy.deepcopy(UNKNOWN),
    }
    value["sha256"] = canonical_sha(value)
    written = write_new(path, value)
    value["sidecar_path"] = str(written)
    value["sidecar_bytes"] = written.stat().st_size
    return value

def run(request_path: Path | str, *, parent_pid: int) -> dict[str, Any]:
    entry = time.monotonic()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    max_wall = int(request.get("parent_boundary", {}).get("max_wall_seconds", 0))
    cleanup_grace = float(request.get("execution", {}).get("cleanup_grace_seconds", 0))
    if max_wall <= 0 or cleanup_grace < V14_CLEANUP_MIN_SECONDS:
        raise ParentLaunchError("v14 max wall and cleanup grace are invalid")
    previous = {signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}
    child: subprocess.Popen[str] | None = None
    status = "FAILED_PARENT_SUPERVISED_LAUNCH"
    error: str | None = None
    stdout = stderr = ""
    cleanup: dict[str, Any] = {"attempted": False}
    child_timed_out = False
    storage: dict[str, Any] | None = None
    child_result: dict[str, Any] | None = None
    def cancelled(signum, _frame):
        raise ParentLaunchCancelled(f"v14 launcher cancelled by signal {signum}")
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        v11, _module = _validate_launch(request, verify_content=True)
        storage = V13.V12._storage_preflight(v11)
        _set_parent_death_signal(parent_pid)
        python_literal = str(request["execution"]["python"])
        strace = str(Path(str(request["execution"]["strace"])).expanduser().resolve())
        bridge = str(Path(str(request["execution"]["bridge"])).expanduser().resolve())
        trace_path = Path(str(request["trace"]["path"])).expanduser().resolve()
        command = [strace, "-f", "-e", "trace=openat,openat2,creat,truncate,rename,unlink,statx",
                   "-o", str(trace_path), python_literal, "-B", bridge, "run",
                   "--request", str(v11["bridge_request"]["path"]), "--io-slot-approved"]
        launcher_pid = os.getpid()
        child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parents[1]), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True,
                                 preexec_fn=lambda: _set_parent_death_signal(launcher_pid))
        try:
            stdout, stderr = child.communicate(timeout=max(0.001, float(max_wall) - (time.monotonic() - entry)))
        except subprocess.TimeoutExpired:
            child_timed_out = True
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
            try:
                stdout, stderr = child.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "child did not become reapable after bounded cleanup"
            error = "v14 parent launcher wall deadline exceeded"
        child_result = _parse_child_json(stdout)
        if not child_timed_out and child.returncode == 0:
            status = "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
        elif not child_timed_out and error is None:
            status = "FAILED_PARENT_SUPERVISED_CHILD"
            error = f"bridge child returned {child.returncode}: {stderr[-1000:]}"
        elif child_timed_out:
            status = "FAILED_PARENT_SUPERVISED_DEADLINE"
    except ParentLaunchCancelled as exc:
        status = "FAILED_PARENT_SUPERVISED_CANCELLED"
        error = str(exc)
        if child is not None:
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
    except BaseException as exc:
        status = "FAILED_PARENT_SUPERVISED_LAUNCH"
        error = f"{type(exc).__name__}: {exc}"
        if child is not None:
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    trace = _trace_record(request)
    accounting = V13._terminal_accounting_status(request)
    if accounting.get("status") != "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP" and error is None:
        status = "FAILED_PARENT_ACCOUNTING_UNCONFIRMED"
        error = accounting.get("reason") or "terminal accounting was not observed"
    sidecar = None
    try:
        sidecar = _write_sidecar(request, cleanup, trace, accounting)
    except BaseException as exc:
        status = "FAILED_PARENT_FINALIZATION"
        error = error or f"sidecar: {type(exc).__name__}: {exc}"
    return {"schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(request_file), "sha256": request.get("sha256")},
            "parent": {"pid": int(parent_pid), "launcher_pid": os.getpid(),
                       "same_parent_ledger": True, "ledger_mutated_by_launcher": False},
            "storage_preflight": storage, "deadline": {"max_wall_seconds": max_wall,
                "started_at_entry": True, "elapsed_seconds": time.monotonic() - entry,
                "timed_out": child_timed_out, "cleanup_grace_seconds": cleanup_grace,
                "cleanup_may_extend_observed_wall": True},
            "cleanup": cleanup, "child": {"returncode": child.returncode if child else None,
                "argv": command if "command" in locals() else [], "bridge_result": child_result,
                "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]},
            "trace": trace, "terminal_accounting": accounting,
            "trace_finalization_sidecar": sidecar, "error": error,
            "cancellation": "SIGTERM cooperative grace (>=20s), then SIGKILL to owned strace group only",
            "model_invoked": False, "cfd_invoked": False, "qualification": copy.deepcopy(UNKNOWN),
            "development_only": True}

def build_request(v13_request_path: Path | str, output_path: Path | str,
                  *, cleanup_grace_seconds: float = V14_CLEANUP_MIN_SECONDS) -> dict[str, Any]:
    source = Path(v13_request_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise ParentLaunchError(f"refusing to overwrite output: {output}")
    old = load_json(source)
    if old.get("schema") != V13_SCHEMA or old.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("source must be a ready v13 request")
    if old.get("sha256") != canonical_sha(old):
        raise ParentLaunchError("source v13 canonical SHA differs")
    if cleanup_grace_seconds < V14_CLEANUP_MIN_SECONDS:
        raise ParentLaunchError("cleanup grace must be at least 20 seconds")
    value = copy.deepcopy(old)
    value["schema"] = SCHEMA
    value["forward_of"] = {"schema": V13_SCHEMA, "path": str(source),
                           "sha256": old["sha256"], "immutable": True,
                           "revision": "nested-process-group-pdeathsig-and-cooperative-cancel-v14"}
    value["trace"] = copy.deepcopy(value["trace"])
    old_trace = Path(str(value["trace"]["path"])).expanduser().resolve()
    new_trace = old_trace.with_name("os-open-trace-v14.log")
    value["trace"] = {"role": "parent_os_open_trace", "path": str(new_trace),
                       "required_for_completion": True}
    value["storage_scope"] = copy.deepcopy(value["storage_scope"])
    value["storage_scope"]["trace_path"] = str(new_trace)
    value["storage_scope"]["finalization_sidecar"] = str(new_trace.with_name("os-open-trace-v14-finalization-v14.json"))
    value["execution"] = copy.deepcopy(value["execution"])
    value["execution"]["parent_supervised"] = [str(value["execution"]["python"]), "-B", str(Path(__file__).resolve()),
                                                   "run", "--request", "<request>", "--parent-pid", "<supervisor_pid>"]
    value["execution"]["trace_finalization_sidecar"] = value["storage_scope"]["finalization_sidecar"]
    value["execution"]["cleanup_grace_seconds"] = float(cleanup_grace_seconds)
    bindings = [dict(item) for item in value.get("source_bindings", [])]
    bindings.append(_source_binding("parent_launcher_v14", Path(__file__).resolve()))
    value["source_bindings"] = bindings
    value["input_files"] = [item["path"] for item in bindings]
    value["input_sha256"] = {item["path"]: item["sha256"] for item in bindings}
    value["limitations"] = list(value.get("limitations", [])) + [
        "v14 is a forward launcher; v13/v12/v11/v10 bytes remain immutable provenance.",
        "SIGTERM reaches the owned strace group; PDEATHSIG is installed on its group leader and cleanup grace is at least 20 seconds.",
        "A cancelled child is terminal only when the parent receipt/charge/lease check is observed; otherwise the report remains FAILED/UNCONFIRMED.",
    ]
    value["sha256"] = canonical_sha(value)
    write_new(output, value)
    return value

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v13-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cleanup-grace-seconds", type=float, default=V14_CLEANUP_MIN_SECONDS)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_request(args.v13_request, args.output,
                               cleanup_grace_seconds=args.cleanup_grace_seconds) if args.command == "build-request" else run(args.request, parent_pid=args.parent_pid)
    except (ParentLaunchError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result if isinstance(result, Mapping) else {"status": "UNKNOWN"}, sort_keys=True,
                     ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith("COMPLETED_") else 2

if __name__ == "__main__":
    raise SystemExit(main())
