#!/usr/bin/env python3
"""Parent supervisor for the v14/v20 external-output path.

This additive entry point is deliberately a separate owner from the consumed
v10 bridge, v14 launcher, and v20 trace helper.  It starts the bound v14 CLI
with the supervisor PID, keeps all supervisor products in a new NVMe
namespace, runs the bound v20 build/apply commands, and charges only its own
new log/report bytes and the residual wrapper CPU under the existing parent
ledger.  The v10 and v20 CPU rows are explicitly subtracted from the wrapper
RUSAGE delta; if a bound row is absent the request fails closed instead of
pretending that the residual is known.

The supervisor never creates a ledger, data root, GPU lease, or symlinked
output namespace.  It terminates only the v14 process group it created.  A
successful strace exit is not enough: the v14 JSON status and terminal parent
charge/lease checks remain prerequisites for a completed supervisor report.
All scientific work and HDF5/BI4 access stay in the parent-approved v14
child slot; ``preflight`` is metadata/stat-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
V14_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v14.py"
V20_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_supplemental_charge_v20.py"
SCHEMA = "ds02.stage2.f2-external-supervisor-request.v20"
REPORT_SCHEMA = "ds02.stage2.f2-external-supervisor-report.v20"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1


class SupervisorError(RuntimeError):
    pass


class SupervisorDeadline(SupervisorError):
    pass


class SupervisorCancelled(SupervisorError):
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
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SupervisorError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise SupervisorError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise SupervisorError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise SupervisorError(f"{name} must be a lowercase SHA-256")
    return value


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _self_cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    return float(own.ru_utime + own.ru_stime)


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _no_symlink_components(path: Path) -> None:
    target = path.expanduser()
    current = target if target.exists() else target.parent
    missing: list[str] = []
    while not current.exists() and current != current.parent:
        missing.append(current.name)
        current = current.parent
    if current.is_symlink():
        raise SupervisorError(f"symlink output component is forbidden: {current}")
    for component in reversed(missing):
        current = current / component
        if current.is_symlink():
            raise SupervisorError(f"symlink output component is forbidden: {current}")
    if target.exists() and target.is_symlink():
        raise SupervisorError(f"symlink output path is forbidden: {target}")


def _tree_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise SupervisorError(f"symlink output file is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _disk_probe(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_dir():
        raise SupervisorError(f"external filesystem is not a directory: {target}")
    stat = os.statvfs(target)
    return {"path": str(target), "free_bytes": int(stat.f_bavail * stat.f_frsize),
            "total_bytes": int(stat.f_blocks * stat.f_frsize),
            "device_id": int(target.stat().st_dev)}


def _v14_ref(path: Path) -> dict[str, Any]:
    request = load_json(path)
    if request.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v14":
        raise SupervisorError("v14 request schema differs")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise SupervisorError("v14 request is not ready")
    if request.get("sha256") != canonical_sha(request):
        raise SupervisorError("v14 request canonical SHA differs")
    storage = request.get("storage_scope")
    accounting = request.get("accounting")
    execution = request.get("execution")
    if not isinstance(storage, Mapping) or not isinstance(accounting, Mapping) or not isinstance(execution, Mapping):
        raise SupervisorError("v14 storage/accounting/execution binding is incomplete")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if not external.is_dir():
        raise SupervisorError(f"v14 external filesystem is missing: {external}")
    trace = Path(str(request.get("trace", {}).get("path", ""))).expanduser().resolve()
    sidecar = Path(str(execution.get("trace_finalization_sidecar", ""))).expanduser().resolve()
    if not _under(trace, external) or not _under(sidecar, external):
        raise SupervisorError("v14 trace and sidecar must remain on the bound external filesystem")
    for key in ("python", "bridge", "strace"):
        path_value = Path(str(execution.get(key, ""))).expanduser().resolve()
        if not path_value.is_file():
            raise SupervisorError(f"v14 execution source is missing: {key}")
    ledger = Path(str(accounting.get("ledger_path", ""))).expanduser().resolve()
    if not ledger.is_file():
        raise SupervisorError("v14 parent ledger is missing")
    v11_path = Path(str(request.get("v11_launch", {}).get("path", ""))).expanduser().resolve()
    if not v11_path.is_file():
        raise SupervisorError("v14 v11-launch source is missing")
    v11 = load_json(v11_path)
    bridge_path = Path(str(v11.get("bridge_request", {}).get("path", ""))).expanduser().resolve()
    if not bridge_path.is_file():
        raise SupervisorError("v14 transitive bridge request is missing")
    bridge = load_json(bridge_path)
    runtime_binding = next((item for item in bridge.get("guard_bindings", [])
                            if isinstance(item, Mapping) and item.get("role") == "shared_runtime_v6"), None)
    if not isinstance(runtime_binding, Mapping):
        raise SupervisorError("v14 transitive shared_runtime_v6 binding is missing")
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "shared_runtime_v6.sha256")
    if not runtime_path.is_file():
        raise SupervisorError("v14 transitive shared runtime is missing")
    ledger_value = load_json(ledger)
    limits = ledger_value.get("limits", {})
    storage_policy = str(limits.get("storage_policy", ""))
    if not storage_policy:
        raise SupervisorError("parent ledger has no declared storage policy")
    return {"request": request, "external": external, "ledger": ledger,
            "trace": trace, "sidecar": sidecar, "accounting": dict(accounting),
            "execution": dict(execution), "attempt_id": str(accounting.get("attempt_id", "")),
            "v11_path": v11_path, "bridge_path": bridge_path,
            "runtime_path": runtime_path, "runtime_sha256": runtime_sha,
            "storage_policy": storage_policy, "ledger_limits": dict(limits),
            "deadline_utc": str(ledger_value.get("deadline_utc", ""))}


def _static_bindings(v14_path: Path, bound: Mapping[str, Any], supervisor_python: Path) -> list[dict[str, Any]]:
    values = [
        ("v14_request", v14_path),
        ("v14_launcher_v14", V14_PATH),
        ("v20_helper_v20", V20_PATH),
        ("supervisor_python", supervisor_python),
    ]
    for key in ("python", "bridge", "strace"):
        values.append((f"v14_{key}", Path(str(bound["execution"][key])).expanduser().resolve()))
    values.append(("shared_runtime_v6", Path(str(bound["runtime_path"])).expanduser().resolve()))
    result = []
    for role, path in values:
        if not path.is_file():
            raise SupervisorError(f"bound static source is missing: {path}")
        stat = path.stat()
        result.append({"role": role, "path": str(path), "sha256": sha256_file(path),
                       "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
    return result


def build_request(v14_path: Path | str, output_path: Path | str, *, output_root: Path | str,
                  max_wall_seconds: float = 6000.0, supervisor_python: Path | str | None = None) -> dict[str, Any]:
    v14_path = Path(v14_path).expanduser().resolve()
    bound = _v14_ref(v14_path)
    output_root = Path(output_root).expanduser().resolve()
    _no_symlink_components(output_root)
    if output_root.exists():
        raise SupervisorError(f"supervisor output namespace already exists: {output_root}")
    if not _under(output_root, bound["external"]):
        raise SupervisorError("supervisor output must be under v14 external filesystem")
    if output_root == bound["external"]:
        raise SupervisorError("supervisor output must be a new child namespace")
    if output_root == bound["ledger"].parent.parent or _under(output_root, bound["ledger"].parent.parent):
        raise SupervisorError("supervisor output must not be inside parent data root")
    if not math.isfinite(float(max_wall_seconds)) or float(max_wall_seconds) <= 0:
        raise SupervisorError("max_wall_seconds must be positive")
    python = Path(supervisor_python or "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python").expanduser()
    bindings = _static_bindings(v14_path, bound, python)
    output = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": str(bound["request"].get("case_id", "")),
        "attempt_id": str(bound["attempt_id"]) + "-supervisor-v20",
        "forward_of": {"v14_request": str(v14_path), "v14_sha256": bound["request"].get("sha256"),
                        "immutable": True},
        "v14_request": {"path": str(v14_path), "sha256": bound["request"].get("sha256"), "immutable": True},
        "v20": {"script": str(V20_PATH), "script_sha256": sha256_file(V20_PATH),
                "request_path": str(output_root / "v20-supplemental-request.json"),
                "report_path": str(output_root / "v20-supplemental-report.json")},
        "paths": {"output_root": str(output_root),
                  "stdout": str(output_root / "supervisor.stdout.log"),
                  "stderr": str(output_root / "supervisor.stderr.log"),
                  "report": str(output_root / "supervisor-report.json")},
        "parent_resource_binding": {
            "ledger_path": str(bound["ledger"]), "same_parent_ledger": True,
            "ledger_reset": False, "no_new_data_root": True,
            "attempt_id": str(bound["attempt_id"]),
            "external_filesystem": str(bound["external"]),
            "home_min_free_bytes": bound["request"].get("storage_scope", {}).get("home_min_free_bytes"),
                       "deadline_utc": bound.get("deadline_utc"),
                       "cpu_reservation_seconds": float(max_wall_seconds),
                       "supplemental_charge_id": str(bound["attempt_id"]) + "::supervisor-v20",
                       "reservation_id": str(bound["attempt_id"]) + "::supervisor-v20-reservation",
                       "storage_policy": bound["storage_policy"],
        },
        "runtime_binding": {"path": str(bound["runtime_path"]), "sha256": bound["runtime_sha256"],
                            "role": "shared_runtime_v6", "immutable": True},
        "storage_scope": {"external_filesystem": str(bound["external"]),
                          "new_namespace_absent_before_run": True,
                          "home_receipt_bytes": 0,
                          "estimated_output_bytes": 16 * 1024 * 1024,
                          "external_min_free_bytes": 1},
        "execution": {"max_wall_seconds": float(max_wall_seconds),
                       "start_clock": "supervisor function entry",
                       "parent_deadline_utc": bound.get("deadline_utc"),
                       "v14_cli": [str(Path(str(bound["execution"]["python"]))), "-B", str(V14_PATH),
                                   "run", "--request", str(v14_path), "--parent-pid", "<supervisor_pid>"],
                       "v20_build_apply": True, "child_process_group": "v14 group created by supervisor",
                       "cancel_scope": "own v14 group only; v14 owns its strace/bridge group",
                       "wait_policy": "communicate with remaining deadline; bounded group cleanup; never trust strace exit alone"},
        "static_bindings": bindings,
        "accounting": {"ledger_owner": "existing DS-DATA-02 parent ledger",
                       "v10_cpu_subtracted": True, "v20_cpu_subtracted": True,
                       "supplemental_scope": "supervisor residual CPU plus supervisor output namespace bytes",
                       "reservation_scope": "same-parent ledger reservation covers supervisor namespace estimate",
                       "cpu_reservation_seconds": float(max_wall_seconds),
                       "supplemental_charge_id": str(bound["attempt_id"]) + "::supervisor-v20",
                       "reservation_id": str(bound["attempt_id"]) + "::supervisor-v20-reservation",
                       "idempotent": True, "no_ledger_reset": True},
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "raw_opened": False, "hdf5_opened": False,
        "limitations": [
            "This request is a parent-scheduled development replay; it grants no QI/QN/QE.",
            "v14/v10 scientific output and trace bytes remain bound to their original immutable requests.",
            "The supervisor charge excludes CPU already recorded by the v10 terminal row and v20 helper row; absent terminal parent rows are charged only with an explicit failure scope.",
            "The parent storage policy is immutable for this request; home_free_floor does not apply the historical cumulative byte field as a cap.",
        ],
    }
    output["sha256"] = canonical_sha(output)
    write_new(output_path, output)
    return output


def _validate_request(request: Mapping[str, Any], *, verify_content: bool = False) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise SupervisorError("unsupported or non-ready supervisor request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise SupervisorError("supervisor must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise SupervisorError("model/CFD invocation is forbidden")
    if request.get("sha256") != canonical_sha(request):
        raise SupervisorError("supervisor request canonical SHA differs")
    v14_ref = request.get("v14_request")
    if not isinstance(v14_ref, Mapping):
        raise SupervisorError("v14 request binding is missing")
    v14_path = Path(str(v14_ref.get("path", ""))).expanduser().resolve()
    bound = _v14_ref(v14_path)
    if v14_ref.get("sha256") != bound["request"].get("sha256"):
        raise SupervisorError("v14 request SHA differs")
    paths = request.get("paths")
    v20 = request.get("v20")
    if not isinstance(paths, Mapping) or not isinstance(v20, Mapping):
        raise SupervisorError("supervisor output/v20 paths are incomplete")
    output_root = Path(str(paths.get("output_root", ""))).expanduser().resolve()
    if output_root.exists():
        raise SupervisorError("supervisor output namespace already exists")
    if not _under(output_root, bound["external"]) or output_root == bound["external"]:
        raise SupervisorError("supervisor output is outside bound external filesystem")
    if _under(output_root, bound["ledger"].parent.parent):
        raise SupervisorError("supervisor output is inside parent data root")
    for key in ("stdout", "stderr", "report"):
        path = Path(str(paths.get(key, ""))).expanduser().resolve()
        if not _under(path, output_root):
            raise SupervisorError(f"supervisor {key} path is outside output namespace")
        if path.exists():
            raise SupervisorError(f"supervisor {key} already exists")
    for key in ("request_path", "report_path"):
        path = Path(str(v20.get(key, ""))).expanduser().resolve()
        if not _under(path, output_root):
            raise SupervisorError(f"v20 {key} is outside output namespace")
        if path.exists():
            raise SupervisorError(f"v20 {key} already exists")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise SupervisorError("static source closure is missing")
    for item in bindings:
        if not isinstance(item, Mapping):
            raise SupervisorError("static binding is malformed")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        expected = _require_sha(item.get("sha256"), "static_binding.sha256")
        if not path.is_file():
            raise SupervisorError(f"static source is missing: {path}")
        if verify_content and sha256_file(path) != expected:
            raise SupervisorError(f"static source SHA differs: {path}")
    supervisor_python = next((Path(str(item["path"])).expanduser().resolve()
                              for item in bindings if item.get("role") == "supervisor_python"), None)
    if supervisor_python is None or not supervisor_python.is_file():
        raise SupervisorError("bound supervisor Python is missing")
    runtime_binding = request.get("runtime_binding")
    if not isinstance(runtime_binding, Mapping):
        raise SupervisorError("shared runtime binding is missing")
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    if runtime_path != bound["runtime_path"] or runtime_binding.get("sha256") != bound["runtime_sha256"]:
        raise SupervisorError("shared runtime binding differs from v14 transitive source")
    scope = request.get("storage_scope")
    if not isinstance(scope, Mapping):
        raise SupervisorError("storage_scope is missing")
    external = Path(str(scope.get("external_filesystem", ""))).expanduser().resolve()
    if external != bound["external"]:
        raise SupervisorError("external filesystem differs from v14")
    if int(scope.get("estimated_output_bytes", 0)) <= 0:
        raise SupervisorError("estimated output bytes must be positive")
    parent_binding = request.get("parent_resource_binding")
    if not isinstance(parent_binding, Mapping):
        raise SupervisorError("parent resource binding is missing")
    if str(parent_binding.get("storage_policy", "")) != bound["storage_policy"]:
        raise SupervisorError("parent storage policy differs from immutable ledger")
    if str(parent_binding.get("deadline_utc", "")) != str(bound.get("deadline_utc", "")):
        raise SupervisorError("parent deadline binding differs from immutable ledger")
    accounting = request.get("accounting")
    if not isinstance(accounting, Mapping):
        raise SupervisorError("accounting binding is missing")
    if str(accounting.get("reservation_id", "")) != str(bound["attempt_id"]) + "::supervisor-v20-reservation":
        raise SupervisorError("supervisor reservation binding differs")
    execution = request.get("execution")
    if not isinstance(execution, Mapping):
        raise SupervisorError("supervisor execution binding is missing")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    cpu_reserve = float(accounting.get("cpu_reservation_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise SupervisorError("supervisor max wall must be positive")
    if not math.isfinite(cpu_reserve) or cpu_reserve <= 0 or abs(cpu_reserve - max_wall) > 1e-9:
        raise SupervisorError("supervisor CPU reservation must equal max_wall_seconds for one thread")
    if abs(float(parent_binding.get("cpu_reservation_seconds", 0.0) or 0.0) - cpu_reserve) > 1e-9:
        raise SupervisorError("parent CPU reservation binding differs from accounting")
    return {"bound": bound, "v14_path": v14_path, "output_root": output_root,
            "paths": {key: Path(str(paths[key])).expanduser().resolve() for key in ("stdout", "stderr", "report")},
            "v20_request": Path(str(v20["request_path"])).expanduser().resolve(),
            "v20_report": Path(str(v20["report_path"])).expanduser().resolve(),
            "supervisor_python": supervisor_python,
            "max_wall_seconds": max_wall, "cpu_reservation_seconds": cpu_reserve,
            "external_min_free_bytes": int(scope.get("external_min_free_bytes", 1) or 0)}


def _install_signals(max_wall: float):
    previous = {signal.SIGALRM: signal.getsignal(signal.SIGALRM),
                signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}
    def deadline(_signum, _frame):
        raise SupervisorDeadline("supervisor entry-to-terminal wall deadline exceeded")
    def cancelled(signum, _frame):
        raise SupervisorCancelled(f"supervisor cancelled by signal {signum}")
    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, max_wall))
    return previous


def _restore_signals(previous: Mapping[int, Any]) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _parent_death(parent_pid: int) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError("cannot install supervisor parent-death signal")
    if os.getppid() != int(parent_pid):
        os.kill(os.getpid(), signal.SIGTERM)


def _stop_group(child: subprocess.Popen[str], grace: float = 5.0) -> dict[str, Any]:
    result: dict[str, Any] = {"sigterm_sent": False, "sigkill_sent": False, "reaped": False,
                              "grace_seconds": float(grace)}
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            result["sigterm_sent"] = True
        except (ProcessLookupError, PermissionError):
            pass
        until = time.monotonic() + max(0.1, grace)
        while child.poll() is None and time.monotonic() < until:
            time.sleep(0.02)
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
                result["sigkill_sent"] = True
            except (ProcessLookupError, PermissionError):
                pass
    try:
        child.wait(timeout=max(1.0, grace))
        result["reaped"] = True
    except subprocess.TimeoutExpired:
        result["reaped"] = False
    return result


def _parse_last_json(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _v10_cpu(ledger_path: Path, attempt_id: str) -> float:
    ledger = load_json(ledger_path)
    rows = [row for row in ledger.get("charges", [])
            if isinstance(row, Mapping) and row.get("id") == attempt_id]
    if not rows:
        raise SupervisorError("v10 terminal parent charge is missing; residual CPU cannot be attributed")
    if any(str(row.get("status")) in {"reserved", "running"} for row in rows):
        raise SupervisorError("v10 parent charge is not terminal")
    return float(rows[-1].get("cpu_core_seconds", 0.0) or 0.0)


def _bound_runtime(runtime_path: Path, expected_runtime_sha: str):
    spec = importlib.util.spec_from_file_location("ds02_supervisor_bound_runtime_v20", runtime_path)
    if spec is None or spec.loader is None:
        raise SupervisorError("cannot import bound runtime for supervisor accounting")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    if sha256_file(runtime_path) != expected_runtime_sha:
        raise SupervisorError("shared runtime changed before supervisor accounting")
    if not callable(getattr(runtime, "ledger_locked", None)):
        raise SupervisorError("bound runtime lacks ledger_locked")
    return runtime


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _reservation_storage_totals(rows: Sequence[Any], *, external: Path,
                                home_path: Path, exclude_id: str | None = None) -> tuple[int, int]:
    """Return reserved external/Home bytes for active parent reservations.

    Newer rows carry explicit per-filesystem fields.  Older parent rows can
    carry only ``new_storage_bytes``; when no filesystem declaration exists we
    conservatively count that unknown reservation against both floors instead
    of treating it as free space.  This is deliberately reservation-only:
    already charged bytes are reflected in statvfs and are not subtracted a
    second time.
    """
    external = external.expanduser().resolve()
    home_path = home_path.expanduser().resolve()
    external_reserved = 0
    home_reserved = 0
    for row in rows:
        if not isinstance(row, Mapping) or row.get("id") == exclude_id:
            continue
        new_bytes = _nonnegative_int(row.get("new_storage_bytes"))
        filesystems = row.get("storage_filesystems")
        fs_paths: list[Path] = []
        if isinstance(filesystems, Sequence) and not isinstance(filesystems, (str, bytes)):
            for item in filesystems:
                try:
                    fs_paths.append(Path(str(item)).expanduser().resolve())
                except (OSError, RuntimeError, ValueError):
                    continue
        if "external_storage_bytes" in row:
            external_reserved += _nonnegative_int(row.get("external_storage_bytes"))
        elif fs_paths:
            if any(path == external or _under(external, path) or _under(path, external)
                   for path in fs_paths):
                external_reserved += new_bytes
        else:
            # An old row without a role split is unsafe to assign to one FS.
            external_reserved += new_bytes
        if "home_storage_bytes" in row:
            home_reserved += _nonnegative_int(row.get("home_storage_bytes"))
        elif fs_paths:
            if any(path == home_path or _under(home_path, path) or _under(path, home_path)
                   for path in fs_paths):
                home_reserved += new_bytes
        else:
            home_reserved += new_bytes
    return external_reserved, home_reserved


def _deadline_epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        raise SupervisorError("parent deadline_utc is malformed")


def _reserve_wrapper(runtime_path: Path, expected_runtime_sha: str, ledger_path: Path,
                     reservation_id: str, attempt_id: str, *, external: Path,
                     bytes_count: int, home_path: Path, home_floor: int,
                     external_floor: int, cpu_reserve_seconds: float,
                     max_wall_seconds: float, deadline_utc: str,
                     max_storage: int | None = None, max_cpu: float | None = None) -> dict[str, Any]:
    """Reserve supervisor output under the existing parent ledger."""
    if int(bytes_count) <= 0:
        raise SupervisorError("supervisor reservation bytes must be positive")
    if not math.isfinite(float(cpu_reserve_seconds)) or float(cpu_reserve_seconds) <= 0:
        raise SupervisorError("supervisor CPU reservation must be positive")
    if not math.isfinite(float(max_wall_seconds)) or float(max_wall_seconds) <= 0:
        raise SupervisorError("supervisor max wall must be positive")
    runtime = _bound_runtime(runtime_path, expected_runtime_sha)
    data_root = ledger_path.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        reservations = ledger.setdefault("reservations", [])
        if any(isinstance(row, Mapping) and row.get("id") == reservation_id for row in charges):
            raise SupervisorError("supervisor reservation id is already charged")
        existing = [row for row in reservations if isinstance(row, Mapping) and row.get("id") == reservation_id]
        if existing:
            row = existing[-1]
            if (int(row.get("external_storage_bytes", -1)) != int(bytes_count)
                    or abs(float(row.get("cpu_core_seconds", -1.0)) - float(cpu_reserve_seconds)) > 1e-9):
                raise SupervisorError("supervisor reservation id has different accounting")
            return {"status": "IDEMPOTENT_RESERVATION", "reservation": dict(row), "ledger_mutated": False}
        limits = ledger.get("limits", {})
        policy = str(limits.get("storage_policy", ""))
        if not policy:
            raise SupervisorError("parent ledger has no declared storage policy")
        deadline = _deadline_epoch(ledger.get("deadline_utc") or deadline_utc)
        now = datetime.now(timezone.utc).timestamp()
        if deadline is not None and (now >= deadline or now + float(max_wall_seconds) > deadline):
            raise SupervisorError("parent deadline cannot contain supervisor reservation window")
        home_stat = os.statvfs(home_path)
        external_stat = os.statvfs(external)
        home_free = int(home_stat.f_bavail * home_stat.f_frsize)
        external_free = int(external_stat.f_bavail * external_stat.f_frsize)
        existing_external, existing_home = _reservation_storage_totals(
            reservations, external=external, home_path=home_path)
        if home_free - existing_home < int(home_floor):
            raise SupervisorError("Home free floor is not satisfied for supervisor reservation")
        if external_free - existing_external - int(bytes_count) < int(external_floor):
            raise SupervisorError("external filesystem lacks supervisor reservation headroom after parent reservations")
        used_cpu = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0)
                       for row in charges + reservations)
        if max_cpu is not None and used_cpu + float(cpu_reserve_seconds) > float(max_cpu):
            raise SupervisorError("parent CPU budget lacks the supervisor reservation")
        if policy != "home_free_floor" and max_storage is not None:
            used_bytes = sum(int(row.get("new_storage_bytes", 0) or 0)
                             for row in charges + reservations)
            if used_bytes + int(bytes_count) > int(max_storage):
                raise SupervisorError("parent new-storage limit would be exceeded by supervisor reservation")
        row = {
            "id": reservation_id, "parent_attempt_id": attempt_id,
            "kind": "external_supervisor_v20_reservation", "status": "reserved",
            "gpu_seconds": 0.0, "cpu_threads": 1,
            "cpu_task_kind": "supervisor",
            "cpu_core_seconds": float(cpu_reserve_seconds),
            "new_storage_bytes": int(bytes_count),
            "external_storage_bytes": int(bytes_count), "home_storage_bytes": 0,
            "storage_filesystems": [str(external)],
            "storage_policy": policy,
            "external_min_free_bytes": int(external_floor),
            "home_min_free_bytes": int(home_floor),
            "reservation_cpu_basis": "one CPU thread multiplied by max_wall_seconds",
            "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        reservations.append(row)
    return {"status": "SUPERVISOR_RESERVATION_APPLIED", "reservation": row, "ledger_mutated": True}


def _charge_wrapper(runtime_path: Path, expected_runtime_sha: str, ledger_path: Path, charge_id: str, attempt_id: str,
                    *, external: Path, bytes_count: int, cpu_seconds: float,
                    status: str, max_storage: int | None = None,
                    max_cpu: float | None = None, reservation_id: str | None = None,
                    allow_missing_parent: bool = False, home_path: Path | None = None,
                    home_floor: int = 0, external_floor: int = 0) -> dict[str, Any]:
    # Import the exact v6/v2 runtime bound by the parent request.  It only
    # supplies ledger_locked; this helper does not create a second ledger.
    runtime = _bound_runtime(runtime_path, expected_runtime_sha)
    data_root = ledger_path.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        existing = [row for row in charges if isinstance(row, Mapping) and row.get("id") == charge_id]
        if existing:
            row = existing[-1]
            if (int(row.get("new_storage_bytes", -1)) != int(bytes_count)
                    or row.get("status") != status):
                raise SupervisorError("supervisor charge ID already has different accounting")
            if reservation_id is not None:
                reservations = ledger.setdefault("reservations", [])
                reservations[:] = [item for item in reservations
                                   if not (isinstance(item, Mapping) and item.get("id") == reservation_id)]
            return {"status": "IDEMPOTENT_ALREADY_CHARGED", "charge": dict(row), "ledger_mutated": False}
        parent = [row for row in charges if isinstance(row, Mapping) and row.get("id") == attempt_id]
        parent_terminal = bool(parent) and not any(str(row.get("status")) in {"reserved", "running"} for row in parent)
        if not parent_terminal and not allow_missing_parent:
            raise SupervisorError("parent attempt is not terminal before supervisor charge")
        if any(str(row.get("status")) in {"reserved", "running"} for row in parent):
            raise SupervisorError("parent attempt is still active before supervisor charge")
        if any(row.get("id") == attempt_id for row in ledger.get("reservations", [])):
            raise SupervisorError("parent reservation remains active")
        leases_root = data_root / "leases"
        for path in leases_root.glob("*.json") if leases_root.is_dir() else []:
            try:
                lease = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if lease.get("attempt_id") == attempt_id:
                raise SupervisorError("parent GPU lease remains active")
        # The adopted Stage2 parent uses ``home_free_floor``.  Its historical
        # cumulative ``new_storage_bytes`` field is not a second Home quota;
        # the live Home floor and the external filesystem floor are the
        # governing storage checks.  Preserve the legacy cumulative cap only
        # for parents that explicitly use a byte-budget policy.
        storage_policy = str(ledger.get("limits", {}).get("storage_policy", ""))
        if max_storage is not None and storage_policy != "home_free_floor":
            used = sum(int(row.get("new_storage_bytes", 0) or 0) for row in charges)
            if used + int(bytes_count) > int(max_storage):
                raise SupervisorError("parent new-storage limit would be exceeded")
        reservations = ledger.setdefault("reservations", [])
        other_external, other_home = _reservation_storage_totals(
            reservations, external=external,
            home_path=home_path or data_root, exclude_id=reservation_id)
        if max_cpu is not None:
            used = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0)
                       for row in charges + reservations if row.get("id") != reservation_id)
            if used + float(cpu_seconds) > float(max_cpu):
                raise SupervisorError("parent CPU limit would be exceeded")
        stat = os.statvfs(external)
        external_free = int(stat.f_bavail * stat.f_frsize)
        if external_free - other_external < int(external_floor):
            raise SupervisorError("external output filesystem would cross floor after parent reservations")
        if home_path is not None:
            home_stat = os.statvfs(home_path)
            home_free = int(home_stat.f_bavail * home_stat.f_frsize)
            if home_free - other_home < int(home_floor):
                raise SupervisorError("Home free floor is not satisfied after parent reservations")
        if reservation_id is not None:
            reservations[:] = [item for item in reservations
                               if not (isinstance(item, Mapping) and item.get("id") == reservation_id)]
        row = {"id": charge_id, "parent_attempt_id": attempt_id,
               "kind": "external_supervisor_v20", "gpu_seconds": 0.0,
               "cpu_core_seconds": float(cpu_seconds), "new_storage_bytes": int(bytes_count),
               "external_storage_bytes": int(bytes_count), "home_storage_bytes": 0,
               "storage_filesystems": [str(external), str(data_root)], "status": status,
               "parent_terminal_charge_present": parent_terminal,
               "failure_scope": "supervisor_only_when_parent_terminal_missing" if not parent_terminal else None,
               "finished_at_utc": datetime.now(timezone.utc).isoformat(),
               "accounting_scope": "same_parent_supervisor_residual_cpu_and_new_nvme_logs_reports"}
        charges.append(row)
    return {"status": "SUPERVISOR_CHARGE_APPLIED", "charge": row, "ledger_mutated": True}


def _release_reservation(runtime_path: Path, expected_runtime_sha: str, ledger_path: Path,
                         reservation_id: str) -> bool:
    runtime = _bound_runtime(runtime_path, expected_runtime_sha)
    data_root = ledger_path.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        reservations = ledger.setdefault("reservations", [])
        before = len(reservations)
        reservations[:] = [row for row in reservations
                           if not (isinstance(row, Mapping) and row.get("id") == reservation_id)]
        return len(reservations) != before


def _run_process_group(command: Sequence[str], *, cwd: Path, timeout: float) -> dict[str, Any]:
    """Run a helper in its own group and bound timeout cleanup to that group."""
    proc = subprocess.Popen(list(command), cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    cleanup: dict[str, Any] = {}
    try:
        stdout, stderr = proc.communicate(timeout=max(0.001, float(timeout)))
    except subprocess.TimeoutExpired as error:
        cleanup = _stop_group(proc, grace=2.0)
        raise SupervisorDeadline(f"bound helper deadline exceeded: {command[0]}") from error
    return {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr,
            "cleanup": cleanup}


def _minimal_failure_context(request: Mapping[str, Any]) -> dict[str, Any]:
    """Recover only safe output/accounting paths after prelaunch validation fails."""
    paths = request.get("paths")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    runtime_binding = request.get("runtime_binding")
    if not all(isinstance(value, Mapping) for value in (paths, parent, storage, runtime_binding)):
        raise SupervisorError("prelaunch failure has no safe accounting bindings")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    ledger = Path(str(parent.get("ledger_path", ""))).expanduser().resolve()
    output_root = Path(str(paths.get("output_root", ""))).expanduser().resolve()
    if not external.is_dir() or not ledger.is_file() or output_root.exists():
        raise SupervisorError("prelaunch failure output/accounting paths are not safely available")
    if not _under(output_root, external) or _under(output_root, ledger.parent.parent):
        raise SupervisorError("prelaunch failure output path is unsafe")
    _no_symlink_components(output_root)
    runtime = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    expected_runtime = _require_sha(runtime_binding.get("sha256"), "runtime_binding.sha256")
    if not runtime.is_file():
        raise SupervisorError("prelaunch failure runtime is missing")
    return {"external": external, "ledger": ledger, "output_root": output_root,
            "paths": {key: Path(str(paths[key])).expanduser().resolve()
                      for key in ("stdout", "stderr", "report")},
            "runtime": runtime, "runtime_sha256": expected_runtime,
            "attempt_id": str(parent.get("attempt_id", "")),
            "charge_id": str(parent.get("supplemental_charge_id", "")) or
                         str(parent.get("attempt_id", "")) + "::supervisor-v20",
            "reservation_id": str(parent.get("reservation_id", "")),
            "external_floor": int(storage.get("external_min_free_bytes", 1) or 0)}


def _record_prelaunch_failure(request_file: Path, request: Mapping[str, Any], error: BaseException,
                              *, entry_wall: float, entry_cpu: float) -> dict[str, Any]:
    context = _minimal_failure_context(request)
    context["output_root"].mkdir(parents=False, exist_ok=False)
    stdout_path = context["paths"]["stdout"]
    stderr_path = context["paths"]["stderr"]
    report_path = context["paths"]["report"]
    stdout_path.write_text("")
    stderr_path.write_text(f"{type(error).__name__}: {error}\n")
    report = {
        "schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "validation_error": f"{type(error).__name__}: {error}",
        "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                       "supervisor_self_cpu_core_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                       "child_cpu_included": False, "finalization_deadline_scope": "bounded local write/stat only",
                       "model_invoked": False, "cfd_invoked": False},
        "accounting": {"same_parent_ledger": True, "ledger_mutated_by_supervisor": "deferred_after_immutable_report_write",
                       "parent_terminal_charge_present": False, "failure_scope": "supervisor_only",
                       "charge_id": context["charge_id"]},
        "filesystem": {"output_root": str(context["output_root"]),
                        "external_filesystem": str(context["external"]),
                        "new_logs_and_reports_bytes": None},
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
    }
    write_new(report_path, report)
    output_bytes = _tree_bytes(context["output_root"])
    limits = load_json(context["ledger"]).get("limits", {})
    home_path = Path(str(limits.get("home_path", context["ledger"].parent.parent))).expanduser()
    charged = False
    try:
        charge = _charge_wrapper(
            context["runtime"], context["runtime_sha256"], context["ledger"], context["charge_id"],
            context["attempt_id"], external=context["external"], bytes_count=output_bytes,
            cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu), status="failed",
            max_storage=int(limits["new_storage_bytes"]) if limits.get("new_storage_bytes") is not None else None,
            max_cpu=float(limits["cpu_core_seconds"]) if limits.get("cpu_core_seconds") is not None else None,
            allow_missing_parent=True, home_path=home_path,
            home_floor=int(limits.get("home_min_free_bytes", 0) or 0),
            external_floor=int(context["external_floor"]),
            reservation_id=context["reservation_id"] or None)
        report["accounting"]["ledger_mutated_by_supervisor"] = bool(charge.get("ledger_mutated"))
        report["accounting"]["charge"] = charge
        charged = bool(charge.get("ledger_mutated"))
    except BaseException as charge_error:
        report["accounting"]["charge_error"] = f"{type(charge_error).__name__}: {charge_error}"
        # A prelaunch failure may occur after the reservation was acquired but
        # before the output namespace exists.  Never leave that reservation
        # live merely because the failure charge itself was rejected.
        if context["reservation_id"]:
            try:
                _release_reservation(context["runtime"], context["runtime_sha256"],
                                     context["ledger"], context["reservation_id"])
            except BaseException:
                report["accounting"]["reservation_cleanup_error"] = "reservation cleanup failed"
    return {"schema": REPORT_SCHEMA, "status": report["status"],
            "report_path": str(report_path), "output_root": str(context["output_root"]),
            "new_logs_and_reports_bytes": output_bytes,
            "ledger_mutated": charged,
            "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    """Run v20 with policy-aware reservation and failure accounting.

    The older v14 implementation remains above for byte-history only; this
    definition is the v20 entry used by the CLI and tests.  It keeps the
    expensive child/content phase under the entry timer, then labels the
    small local log/report/ledger finalization phase explicitly rather than
    claiming the timer covers an already-restored signal.
    """
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    entry_self_cpu = _self_cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if not io_slot_approved:
        checked = _validate_request(request, verify_content=False)
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                "request_sha256": sha256_file(request_file), "ledger_mutated": False,
                "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
                "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    try:
        checked = _validate_request(request, verify_content=False)
    except BaseException as error:
        try:
            return _record_prelaunch_failure(request_file, request, error,
                                             entry_wall=entry_wall, entry_cpu=entry_cpu)
        except BaseException as record_error:
            return {"schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT",
                    "error": f"{type(error).__name__}: {error}; accounting: {type(record_error).__name__}: {record_error}",
                    "ledger_mutated": False, "model_invoked": False, "cfd_invoked": False,
                    "qualification": dict(UNKNOWN)}
    max_wall = checked["max_wall_seconds"]
    previous = _install_signals(max_wall)
    output_root: Path = checked["output_root"]
    paths = checked["paths"]
    bound = checked["bound"]
    reservation_id = str(request["accounting"]["reservation_id"])
    reservation_applied = False
    child: subprocess.Popen[str] | None = None
    v14_stdout = ""
    v14_stderr = ""
    v14_result: dict[str, Any] | None = None
    v20_result: dict[str, Any] | None = None
    cleanup: dict[str, Any] = {}
    status = "FAILED_EXTERNAL_SUPERVISOR"
    error: str | None = None
    child_returncode: int | None = None
    v20_subprocess_cleanup: list[dict[str, Any]] = []
    try:
        # Full static hashes are part of this same parent-supervised interval.
        checked = _validate_request(request, verify_content=True)
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise SupervisorCancelled("supervising parent already exited")
        limits = bound["ledger_limits"]
        home_path = Path(str(limits.get("home_path", bound["ledger"].parent.parent))).expanduser().resolve()
        estimated = int(request["storage_scope"]["estimated_output_bytes"])
        reservation = _reserve_wrapper(
            Path(str(request["runtime_binding"]["path"])), str(request["runtime_binding"]["sha256"]),
            bound["ledger"], reservation_id, bound["attempt_id"], external=bound["external"],
            bytes_count=estimated, home_path=home_path,
            home_floor=int(limits.get("home_min_free_bytes", 0) or 0),
            external_floor=int(checked["external_min_free_bytes"]),
            cpu_reserve_seconds=float(checked["cpu_reservation_seconds"]),
            max_wall_seconds=float(checked["max_wall_seconds"]),
            deadline_utc=str(bound.get("deadline_utc", "")),
            max_storage=int(limits["new_storage_bytes"]) if limits.get("new_storage_bytes") is not None else None,
            max_cpu=float(limits["cpu_core_seconds"]) if limits.get("cpu_core_seconds") is not None else None)
        reservation_applied = True
        live = _disk_probe(bound["external"])
        min_free = int(request["storage_scope"].get("external_min_free_bytes", 1))
        if live["free_bytes"] - estimated < min_free:
            raise SupervisorError("external output headroom estimate would cross floor")
        output_root.mkdir(parents=True, exist_ok=False)
        python = Path(str(bound["execution"]["python"])).expanduser()
        command = [str(python), "-B", str(V14_PATH), "run", "--request", str(checked["v14_path"]),
                   "--parent-pid", str(os.getpid())]
        launcher_pid = os.getpid()
        child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parents[1]), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True,
                                 preexec_fn=(lambda: _parent_death(launcher_pid)) if parent_pid is not None else None)
        try:
            v14_stdout, v14_stderr = child.communicate(
                timeout=max(0.001, max_wall - (time.monotonic() - entry_wall)))
        except subprocess.TimeoutExpired as timeout_error:
            cleanup = _stop_group(child, grace=2.0)
            error = "supervisor wall deadline exceeded while v14 was active"
            raise SupervisorDeadline(error) from timeout_error
        child_returncode = child.returncode
        v14_result = _parse_last_json(v14_stdout)
        if v14_result is None:
            raise SupervisorError("v14 did not emit a JSON report")
        # The v20 helper has its own child group, so a timeout cannot orphan a
        # build/apply process under the supervisor's process group.
        remaining = max(0.001, max_wall - (time.monotonic() - entry_wall))
        v20_request = checked["v20_request"]
        v20_report = checked["v20_report"]
        supervisor_python = checked["supervisor_python"]
        build_cmd = [str(supervisor_python), "-B", str(V20_PATH), "build-request",
                     "--v14-request", str(checked["v14_path"]), "--output", str(v20_request)]
        build = _run_process_group(build_cmd, cwd=SCRIPT_DIR.parents[1], timeout=remaining)
        v20_subprocess_cleanup.append(build["cleanup"])
        if build["returncode"] != 0:
            raise SupervisorError(f"v20 build failed: {build['stderr'][-1000:]}")
        apply_cmd = [str(supervisor_python), "-B", str(V20_PATH), "apply", "--request", str(v20_request)]
        apply = _run_process_group(apply_cmd, cwd=SCRIPT_DIR.parents[1],
                                   timeout=max(0.001, max_wall - (time.monotonic() - entry_wall)))
        v20_subprocess_cleanup.append(apply["cleanup"])
        v20_result = _parse_last_json(apply["stdout"])
        v20_report.write_text(json.dumps(v20_result or {
            "status": "V20_NO_JSON", "stdout": apply["stdout"], "stderr": apply["stderr"]},
            indent=2, sort_keys=True) + "\n")
        if apply["returncode"] != 0 or not isinstance(v20_result, Mapping):
            raise SupervisorError(f"v20 apply failed: {apply['stderr'][-1000:]}")
        if (v14_result.get("status") == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
                and str(v20_result.get("status")) in {"SUPPLEMENTAL_CHARGE_APPLIED", "IDEMPOTENT_ALREADY_CHARGED"}):
            status = "COMPLETED_EXTERNAL_SUPERVISOR_DEVELOPMENT_UNKNOWN"
        else:
            status = "FAILED_EXTERNAL_SUPERVISOR_CHILD"
            error = error or str(v14_result.get("error") or "v14/v20 did not complete")
    except (SupervisorDeadline, SupervisorCancelled, subprocess.TimeoutExpired) as exc:
        status = "FAILED_EXTERNAL_SUPERVISOR_DEADLINE" if isinstance(exc, (SupervisorDeadline, subprocess.TimeoutExpired)) else "FAILED_EXTERNAL_SUPERVISOR_CANCELLED"
        error = str(exc)
        if child is not None:
            cleanup = _stop_group(child, grace=2.0)
    except BaseException as exc:
        status = "FAILED_EXTERNAL_SUPERVISOR"
        error = f"{type(exc).__name__}: {exc}"
        if child is not None:
            cleanup = _stop_group(child, grace=2.0)
    finally:
        # The child/validation deadline ends here.  The remaining local
        # report/stat/ledger operations are bounded separately and are named
        # as such in the report; they are not falsely claimed under SIGALRM.
        _restore_signals(previous)
    if not output_root.exists():
        try:
            return _record_prelaunch_failure(request_file, request,
                                             SupervisorError(error or "supervisor failed before output namespace"),
                                             entry_wall=entry_wall, entry_cpu=entry_cpu)
        except BaseException as record_error:
            return {"schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT",
                    "error": f"{error or 'prelaunch failure'}; accounting: {type(record_error).__name__}: {record_error}",
                    "ledger_mutated": False, "model_invoked": False, "cfd_invoked": False,
                    "qualification": dict(UNKNOWN)}
    try:
        paths["stdout"].write_text(v14_stdout)
        paths["stderr"].write_text(v14_stderr)
    except BaseException as exc:
        status = "FAILED_EXTERNAL_SUPERVISOR_FINALIZATION"
        error = error or f"log finalization: {type(exc).__name__}: {exc}"
    total_cpu = max(0.0, _cpu_seconds() - entry_cpu)
    own_cpu = max(0.0, _self_cpu_seconds() - entry_self_cpu)
    try:
        v10_cpu = _v10_cpu(bound["ledger"], bound["attempt_id"])
    except SupervisorError:
        v10_cpu = None
        error = error or "v10 terminal CPU row is unavailable; supervisor-only failure charge used"
    v20_cpu = float(v20_result.get("cpu_core_seconds", 0.0)) if isinstance(v20_result, Mapping) else 0.0
    residual = max(0.0, total_cpu - float(v10_cpu or 0.0) - v20_cpu) if v10_cpu is not None else own_cpu
    report = {
        "schema": REPORT_SCHEMA, "status": status,
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "parent": {"ledger_path": str(bound["ledger"]), "attempt_id": bound["attempt_id"],
                   "same_parent_ledger": True, "ledger_reset": False, "parent_pid": parent_pid,
                   "storage_policy": bound["storage_policy"]},
        "v14": {"returncode": child_returncode, "result": v14_result,
                "stdout_tail": v14_stdout[-4000:], "stderr_tail": v14_stderr[-4000:]},
        "v20": {"result": v20_result, "request_path": str(checked["v20_request"]),
                "report_path": str(checked["v20_report"])},
        "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                       "entry_cpu_core_seconds": total_cpu,
                       "supervisor_self_cpu_core_seconds": own_cpu,
                       "residual_supervisor_cpu_core_seconds": residual,
                       "max_rss_observed_bytes": _max_rss_bytes(),
                       "cleanup": cleanup, "v20_subprocess_cleanup": v20_subprocess_cleanup,
                       "model_invoked": False, "cfd_invoked": False,
                       "hard_wall_covers": ["static content validation", "v14 launch/wait", "v20 build/apply"],
                       "finalization_deadline_scope": "timer restored before local log/report/stat/ledger finalization; local operations bounded and reported",
                       "cancel_scope": "own v14 and v20 child process groups only"},
        "accounting": {"v10_cpu_subtracted": float(v10_cpu or 0.0),
                       "v20_cpu_subtracted": v20_cpu,
                       "supervisor_cpu_total_before_subtraction": total_cpu,
                       "supervisor_self_cpu": own_cpu,
                       "residual_cpu_to_charge": residual,
                       "parent_terminal_charge_present": v10_cpu is not None,
                       "reservation_id": reservation_id,
                       "supplemental_charge_id": str(bound["attempt_id"]) + "::supervisor-v20",
                       "external_product_bytes_measured_after_log_finalization": None,
                       "ledger_mutated_by_supervisor": "deferred_after_immutable_report_write",
                       "v20_helper_owns_trace_sidecar_charge": True},
        "filesystem": {"output_root": str(output_root), "new_logs_and_reports_bytes": None,
                        "external_filesystem": str(bound["external"]), "home_receipt_bytes": 0},
        "error": error, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN), "raw_opened": False, "hdf5_opened": False,
        "original_path_fallback": "FORBIDDEN",
    }
    try:
        write_new(paths["report"], report)
        output_bytes = _tree_bytes(output_root)
        report["filesystem"]["new_logs_and_reports_bytes"] = output_bytes
        limits = bound["ledger_limits"]
        charge_status = "completed" if status.startswith("COMPLETED_") else "failed"
        charge_result = _charge_wrapper(
            Path(str(request["runtime_binding"]["path"])), str(request["runtime_binding"]["sha256"]),
            bound["ledger"], str(bound["attempt_id"]) + "::supervisor-v20", bound["attempt_id"],
            external=bound["external"], bytes_count=output_bytes, cpu_seconds=residual,
            status=charge_status,
            max_storage=int(limits["new_storage_bytes"]) if limits.get("new_storage_bytes") is not None else None,
            max_cpu=float(limits["cpu_core_seconds"]) if limits.get("cpu_core_seconds") is not None else None,
            reservation_id=reservation_id if reservation_applied else None,
            allow_missing_parent=v10_cpu is None,
            home_path=Path(str(limits.get("home_path", bound["ledger"].parent.parent))).expanduser(),
            home_floor=int(limits.get("home_min_free_bytes", 0) or 0),
            external_floor=int(checked["external_min_free_bytes"]))
        report["accounting"]["ledger_mutated_by_supervisor"] = bool(charge_result.get("ledger_mutated"))
        report["accounting"]["charge_result"] = charge_result
        return {"schema": REPORT_SCHEMA, "status": status,
                "report_path": str(paths["report"]), "output_root": str(output_root),
                "new_logs_and_reports_bytes": output_bytes,
                "residual_supervisor_cpu_core_seconds": residual,
                "v10_cpu_subtracted": float(v10_cpu or 0.0), "v20_cpu_subtracted": v20_cpu,
                "v14_returncode": child_returncode,
                "v20_status": v20_result.get("status") if isinstance(v20_result, Mapping) else None,
                "ledger_mutated": bool(charge_result.get("ledger_mutated")),
                "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    except BaseException as exc:
        if reservation_applied:
            try:
                _release_reservation(Path(str(request["runtime_binding"]["path"])),
                                     str(request["runtime_binding"]["sha256"]), bound["ledger"], reservation_id)
            except BaseException:
                pass
        return {"schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_FINALIZATION",
                "error": f"{type(exc).__name__}: {exc}", "report_path": str(paths["report"]),
                "output_root": str(output_root), "ledger_mutated": False,
                "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v14-request", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    build.add_argument("--python", type=Path)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v14_request, args.output, output_root=args.output_root,
                                  max_wall_seconds=args.max_wall_seconds, supervisor_python=args.python)
            result = {"status": value["status"], "sha256": value["sha256"]}
            code = 0
        elif args.command == "preflight":
            value = run(args.request, io_slot_approved=False)
            result = value
            code = 0
        else:
            if not args.io_slot_approved:
                parser.error("approved supervisor run requires --io-slot-approved")
            result = run(args.request, io_slot_approved=True, parent_pid=args.parent_pid)
            code = 0 if str(result.get("status", "")).startswith("COMPLETED_") else 2
    except (SupervisorError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
