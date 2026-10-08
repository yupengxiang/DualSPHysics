#!/usr/bin/env python3
"""Parent-supervised entry for the v10 F2 portable ledger bridge.

The v10 bridge is the only process that owns the Stage2 ledger reservation and
charge.  This entrypoint is deliberately a supervisor boundary, not another
runtime wrapper: it binds the immutable v10 request and bridge, checks the
Home/NVMe filesystem budgets, starts one ``strace -f`` file for native opens,
and terminates only its own bridge process group on cancellation or deadline.

The command is development-only.  It never opens HDF5/BI4 itself, creates a
new ledger/data root, or grants QI/QN/QE.  ``preflight`` is metadata/stat/hash
only; ``run`` is the parent-approved bridge launch and must receive the actual
supervising parent PID.
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
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v11"
REPORT_SCHEMA = "ds02.stage2.f2-parent-supervised-launch-report.v11"
V10_SCHEMA = "ds02.stage2.f2-portable-ledger-bridge-request.v10"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1
_ACTIVE_CHILD: subprocess.Popen[str] | None = None


class ParentLaunchError(RuntimeError):
    """The parent launch contract cannot be safely executed."""


class ParentLaunchCancelled(ParentLaunchError):
    """The supervising parent cancelled this launcher."""


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
        value = json.loads(target.read_text())
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


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ParentLaunchError(f"{name} must be a lowercase SHA-256")
    return value


def _file_ref(item: Mapping[str, Any], *, verify_content: bool) -> dict[str, Any]:
    path = Path(str(item.get("path"))).expanduser().resolve()
    if not path.is_file():
        raise ParentLaunchError(f"bound source is missing: {path}")
    stat = path.stat()
    expected_bytes = item.get("bytes")
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise ParentLaunchError(f"bound source byte stat differs: {path}")
    expected_mtime = item.get("mtime_ns")
    if expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise ParentLaunchError(f"bound source mtime differs: {path}")
    expected = _sha(item.get("sha256"), str(item.get("role", "source")))
    if verify_content and sha256_file(path) != expected:
        raise ParentLaunchError(f"bound source SHA differs: {path}")
    return {"role": str(item.get("role", "source")), "path": str(path),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": expected}


def _load_v10_module(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_bridge_v10_for_parent_v11", path)
    if spec is None or spec.loader is None:
        raise ParentLaunchError(f"cannot import v10 bridge: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_v10(request_path: Path | str, *, verify_sources: bool = False) -> tuple[dict[str, Any], Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if request.get("schema") != V10_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("bound request is not a ready v10 bridge request")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v10 bridge request canonical SHA differs")
    bridge_path = Path(str(request.get("execution", {}).get("entrypoint"))).expanduser().resolve()
    binding = next((item for item in request.get("source_bindings", [])
                    if item.get("role") == "portable_ledger_bridge_v10"), None)
    if not isinstance(binding, Mapping) or Path(str(binding.get("path"))).expanduser().resolve() != bridge_path:
        raise ParentLaunchError("v10 entrypoint is not its digest-bound bridge source")
    _file_ref(binding, verify_content=verify_sources)
    module = _load_v10_module(bridge_path)
    # This semantic/stat preflight does not open H5/BI4 payloads.  The v10
    # bridge repeats the authoritative content checks after parent reservation.
    module._validate(request, verify_content=False)
    return request, module


def _trace_binding(request: Mapping[str, Any]) -> dict[str, Any]:
    values = request.get("external_storage_scope", {}).get("expected_artifacts", [])
    item = next((item for item in values if item.get("role") == "parent_os_open_trace"), None)
    if not isinstance(item, Mapping) or item.get("parent_owned") is not True:
        raise ParentLaunchError("v10 request lacks a parent-owned OS trace artifact")
    path = Path(str(item.get("path"))).expanduser().resolve()
    filesystem = Path(str(request["external_storage_scope"]["filesystem"])).expanduser().resolve()
    if path.parent != filesystem:
        raise ParentLaunchError("parent OS trace must be in the declared external filesystem root")
    if path.exists():
        raise ParentLaunchError(f"parent OS trace already exists: {path}")
    return {"role": "parent_os_open_trace", "path": str(path),
            "required_for_completion": bool(item.get("required_for_completion", False))}


def _python_path() -> Path:
    path = Path(sys.executable).expanduser().resolve()
    if not path.is_file():
        raise ParentLaunchError(f"Python executable is missing: {path}")
    return path


def build_request(bridge_request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    bridge_file = Path(bridge_request_path).expanduser().resolve()
    bridge, module = _load_v10(bridge_file, verify_sources=False)
    trace = _trace_binding(bridge)
    launcher_path = Path(__file__).resolve()
    bridge_path = Path(str(bridge["execution"]["entrypoint"])).expanduser().resolve()
    strace_path = Path(str(next(item for item in bridge["source_bindings"]
                                if item.get("role") == "v7:os_strace")["path"])).expanduser().resolve()
    if not strace_path.is_file():
        raise ParentLaunchError(f"bound strace executable is missing: {strace_path}")
    python_path = _python_path()
    bindings = [
        _file_ref({"role": "parent_launcher_v11", "path": str(launcher_path),
                   "bytes": launcher_path.stat().st_size, "mtime_ns": launcher_path.stat().st_mtime_ns,
                   "sha256": sha256_file(launcher_path)}, verify_content=False),
        _file_ref({"role": "v10_bridge_request", "path": str(bridge_file),
                   "bytes": bridge_file.stat().st_size, "mtime_ns": bridge_file.stat().st_mtime_ns,
                   "sha256": sha256_file(bridge_file)}, verify_content=False),
        _file_ref({"role": "portable_ledger_bridge_v10", "path": str(bridge_path),
                   "bytes": bridge_path.stat().st_size, "mtime_ns": bridge_path.stat().st_mtime_ns,
                   "sha256": sha256_file(bridge_path)}, verify_content=False),
        _file_ref({"role": "os_strace", "path": str(strace_path),
                   "bytes": strace_path.stat().st_size, "mtime_ns": strace_path.stat().st_mtime_ns,
                   "sha256": sha256_file(strace_path)}, verify_content=False),
        _file_ref({"role": "python_executable", "path": str(python_path),
                   "bytes": python_path.stat().st_size, "mtime_ns": python_path.stat().st_mtime_ns,
                   "sha256": sha256_file(python_path)}, verify_content=False),
    ]
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "forward_of": {"schema": V10_SCHEMA, "path": str(bridge_file),
                       "sha256": bridge["sha256"], "immutable": True,
                       "revision": "parent-supervised-v11"},
        "bridge_request": {"path": str(bridge_file), "sha256": bridge["sha256"],
                           "schema": V10_SCHEMA, "attempt_id": bridge["attempt_id"]},
        "parent_resource_binding": copy.deepcopy(bridge["parent_resource_binding"]),
        "storage_scope": {
            "home_path": str(bridge["parent_resource_binding"]["limits"]["home_path"]),
            "home_min_free_bytes": int(bridge["parent_resource_binding"]["limits"]["home_min_free_bytes"]),
            "home_receipt_reserved_bytes": int(bridge["reservation"]["home_receipt_reserved_bytes"]),
            "external_filesystem": bridge["external_storage_scope"]["filesystem"],
            "external_reserved_bytes": int(bridge["reservation"]["external_product_reserved_bytes"]),
            "two_filesystem_headroom_required": True,
            "external_roots": copy.deepcopy(bridge["external_storage_scope"]["roots"]),
        },
        "trace": trace,
        "source_bindings": bindings,
        "input_files": [item["path"] for item in bindings],
        "input_sha256": {item["path"]: item["sha256"] for item in bindings},
        "execution": {
            "python": str(python_path),
            "bridge": str(bridge_path),
            "strace": str(strace_path),
            "metadata_preflight": [str(python_path), "-B", str(launcher_path), "preflight",
                                    "--request", "<request>"],
            "parent_supervised": [str(python_path), "-B", str(launcher_path), "run",
                                   "--request", "<request>", "--parent-pid", "<supervisor_pid>"],
            "traced_bridge_template": [str(strace_path), "-f", "-e",
                                        "trace=openat,openat2,creat,truncate,rename,unlink,statx",
                                        "-o", trace["path"], str(python_path), "-B",
                                        str(bridge_path), "run", "--request", str(bridge_file),
                                        "--io-slot-approved"],
            "bridge_owns_ledger": True,
            "nested_runtime_wrapper": False,
            "parent_entry_owns": ["parent_pid_death", "outer_wall", "child_process_group",
                                  "native_open_trace", "Home_external_headroom_preflight"],
        },
        "parent_boundary": {
            "max_wall_seconds": int(bridge["reservation"]["max_wall_seconds"]),
            "clock_starts": "parent launcher function entry before source checks and child launch",
            "parent_pid_required": True,
            "parent_death_signal": "SIGTERM",
            "child_process_group": "launcher-created strace/bridge group only",
            "cancellation": "SIGTERM/SIGINT or deadline terminates only the launcher-created child group",
            "inner_bridge_wall": "v10 bridge entry-to-finalization timer remains authoritative for ledger cleanup",
            "ledger_owner": "v10 bridge only; launcher never imports or mutates runtime ledger",
            "native_open_trace": "single -f strace output at exact parent-owned artifact path",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "limitations": [
            "Metadata preflight does not read HDF5/BI4 and grants no replay credit.",
            "The parent supervisor must create the declared external filesystem namespace while keeping both output roots absent.",
            "The v10 bridge remains responsible for all source posthash, artifact, receipt, and ledger charging.",
            "QI/QN/QE remain UNKNOWN; this launcher is not a solver or scientific approval.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def _validate_launch(request: Mapping[str, Any], *, verify_content: bool) -> tuple[dict[str, Any], Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("unsupported or non-ready v11 launch request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ParentLaunchError("v11 launch must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ParentLaunchError("v11 launch cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v11 launch canonical SHA differs")
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list) or {item.get("role") for item in bindings} != {
        "parent_launcher_v11", "v10_bridge_request", "portable_ledger_bridge_v10",
        "os_strace", "python_executable",
    }:
        raise ParentLaunchError("v11 source closure is incomplete")
    checked = {item["role"]: _file_ref(item, verify_content=verify_content)
               for item in bindings}
    bridge_path = Path(checked["v10_bridge_request"]["path"])
    bridge, module = _load_v10(bridge_path, verify_sources=False)
    if bridge.get("sha256") != request["bridge_request"].get("sha256"):
        raise ParentLaunchError("v10 bridge request SHA differs")
    if Path(checked["portable_ledger_bridge_v10"]["path"]) != Path(str(bridge["execution"]["entrypoint"])).resolve():
        raise ParentLaunchError("v10 entrypoint differs from v11 binding")
    trace = _trace_binding(bridge)
    if trace != request.get("trace"):
        raise ParentLaunchError("parent trace binding differs from v10 expected artifact")
    if not isinstance(request.get("parent_boundary"), Mapping):
        raise ParentLaunchError("parent boundary is required")
    return bridge, module


def _existing_dir(path: Path) -> Path:
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir():
        raise ParentLaunchError(f"no existing filesystem anchor for {path}")
    return current


def _storage_preflight(bridge: Mapping[str, Any]) -> dict[str, Any]:
    storage = bridge["external_storage_scope"]
    filesystem = Path(str(storage["filesystem"])).expanduser().resolve()
    if not filesystem.is_dir():
        raise ParentLaunchError(f"external filesystem namespace is not prepared: {filesystem}")
    home = Path(str(bridge["parent_resource_binding"]["limits"]["home_path"])).expanduser().resolve()
    home_anchor = _existing_dir(home)
    external_usage = shutil.disk_usage(filesystem)
    home_usage = shutil.disk_usage(home_anchor)
    home_floor = int(bridge["parent_resource_binding"]["limits"]["home_min_free_bytes"])
    home_receipt = int(bridge["reservation"]["home_receipt_reserved_bytes"])
    external_reserve = int(bridge["reservation"]["external_product_reserved_bytes"])
    if home_usage.free - home_receipt < home_floor:
        raise ParentLaunchError("Home free-space floor does not cover the bridge receipt reservation")
    if external_usage.free < external_reserve:
        raise ParentLaunchError("external filesystem lacks its declared product reservation")
    return {
        "home": {"path": str(home_anchor), "free_bytes": int(home_usage.free),
                 "floor_bytes": home_floor, "receipt_reserve_bytes": home_receipt},
        "external": {"path": str(filesystem), "free_bytes": int(external_usage.free),
                      "product_reserve_bytes": external_reserve},
        "status": "PASS_TWO_FILESYSTEM_HEADROOM_STATVFS",
    }


def _set_parent_death_signal(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install parent-death signal")
    if os.getppid() != parent_pid:
        raise ParentLaunchCancelled("supervising parent already exited")


def _kill_child_group(child: subprocess.Popen[str]) -> None:
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + 0.25
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if child.poll() is None:
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        child.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        # A D-state process cannot be synchronously reaped; do not wait for an
        # unbounded grace period or claim the hard wall was enforced locally.
        pass


def _child_parent_death(parent_pid: int):
    def callback() -> None:
        _set_parent_death_signal(parent_pid)
    return callback


def _parse_child_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run(request_path: Path | str, *, parent_pid: int) -> dict[str, Any]:
    global _ACTIVE_CHILD
    entry = time.monotonic()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    max_wall = int(request.get("parent_boundary", {}).get("max_wall_seconds", 0))
    if max_wall <= 0:
        raise ParentLaunchError("parent boundary max_wall_seconds must be positive")
    previous = {signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}

    def cancelled(signum, _frame):
        raise ParentLaunchCancelled(f"launcher cancelled by signal {signum}")

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    child: subprocess.Popen[str] | None = None
    status = "FAILED_PARENT_SUPERVISED_LAUNCH"
    error: str | None = None
    stdout = ""
    stderr = ""
    bridge_result: dict[str, Any] | None = None
    storage: dict[str, Any] | None = None
    timed_out = False
    try:
        bridge, _module = _validate_launch(request, verify_content=True)
        storage = _storage_preflight(bridge)
        trace_path = Path(str(request["trace"]["path"])).expanduser().resolve()
        if trace_path.exists():
            raise ParentLaunchError(f"parent trace already exists: {trace_path}")
        parent_exe = Path(request["execution"]["python"]).expanduser().resolve()
        strace = Path(request["execution"]["strace"]).expanduser().resolve()
        bridge_path = Path(request["execution"]["bridge"]).expanduser().resolve()
        _set_parent_death_signal(parent_pid)
        # Keep request path explicit and independent of an optional v10
        # execution metadata field; this avoids any latest/glob fallback.
        command = [str(strace), "-f", "-e",
                   "trace=openat,openat2,creat,truncate,rename,unlink,statx",
                   "-o", str(trace_path), str(parent_exe), "-B", str(bridge_path),
                   "run", "--request", str(request["bridge_request"]["path"]),
                   "--io-slot-approved"]
        child = subprocess.Popen(
            command, cwd=str(Path(__file__).resolve().parents[2]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True, preexec_fn=_child_parent_death(os.getpid()),
        )
        _ACTIVE_CHILD = child
        remaining = max(0.001, float(max_wall) - (time.monotonic() - entry))
        try:
            stdout, stderr = child.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_child_group(child)
            stdout, stderr = child.communicate(timeout=0.5)
            error = "parent launcher wall deadline exceeded"
        bridge_result = _parse_child_json(stdout)
        if not timed_out and child.returncode == 0:
            status = "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
        elif not timed_out and error is None:
            error = f"bridge child returned {child.returncode}: {stderr[-1000:]}"
        if timed_out:
            status = "FAILED_PARENT_SUPERVISED_DEADLINE"
    except ParentLaunchCancelled as exc:
        error = str(exc)
        status = "FAILED_PARENT_SUPERVISED_CANCELLED"
        if child is not None:
            _kill_child_group(child)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_SUPERVISED_LAUNCH"
        if child is not None:
            _kill_child_group(child)
    finally:
        _ACTIVE_CHILD = None
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    trace_path = Path(str(request.get("trace", {}).get("path", ""))).expanduser().resolve()
    trace_record = {"path": str(trace_path), "exists": trace_path.is_file(),
                    "bytes": int(trace_path.stat().st_size) if trace_path.is_file() else 0,
                    "sha256": sha256_file(trace_path) if trace_path.is_file() else None,
                    "single_file_follow_fork": True}
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "request": {"path": str(request_file), "sha256": request.get("sha256"),
                     "bridge_request_sha256": request.get("bridge_request", {}).get("sha256")},
        "parent": {"pid": int(parent_pid), "launcher_pid": os.getpid(),
                    "same_parent_ledger": True, "ledger_mutated_by_launcher": False},
        "storage_preflight": storage,
        "deadline": {"max_wall_seconds": max_wall, "started_at_entry": True,
                      "elapsed_seconds": time.monotonic() - entry,
                      "timed_out": timed_out,
                      "child_group_terminated_by_launcher": timed_out or error is not None},
        "child": {"returncode": child.returncode if child is not None else None,
                  "bridge_result": bridge_result, "stdout_tail": stdout[-2000:],
                  "stderr_tail": stderr[-2000:]},
        "trace": trace_record,
        "error": error,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "development_only": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--bridge-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.bridge_request, args.output)
            result = {"status": value["status"], "sha256": value["sha256"]}
            code = 0
        elif args.command == "preflight":
            request = load_json(args.request)
            _validate_launch(request, verify_content=True)
            result = {"status": "READY_FOR_PARENT_IO_SLOT", "request_sha256": request["sha256"],
                      "ledger_mutated": False, "raw_opened": False, "hdf5_opened": False}
            code = 0
        else:
            value = run(args.request, parent_pid=args.parent_pid)
            result = value
            code = 0 if value["status"] == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN" else 2
    except (ParentLaunchError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
