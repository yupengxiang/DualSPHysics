#!/usr/bin/env python3
"""Parent supervisor for the v12/v13 external-output path.

This additive entry point is deliberately a separate owner from the consumed
v10 bridge, v12 launcher, and v13 trace helper.  It starts the bound v12 CLI
with the supervisor PID, keeps all supervisor products in a new NVMe
namespace, runs the bound v13 build/apply commands, and charges only its own
new log/report bytes and the residual wrapper CPU under the existing parent
ledger.  The v10 and v13 CPU rows are explicitly subtracted from the wrapper
RUSAGE delta; if a bound row is absent the request fails closed instead of
pretending that the residual is known.

The supervisor never creates a ledger, data root, GPU lease, or symlinked
output namespace.  It terminates only the v12 process group it created.  A
successful strace exit is not enough: the v12 JSON status and terminal parent
charge/lease checks remain prerequisites for a completed supervisor report.
All scientific work and HDF5/BI4 access stay in the parent-approved v12
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
V12_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v12.py"
V13_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_supplemental_charge_v13.py"
SCHEMA = "ds02.stage2.f2-external-supervisor-request.v14"
REPORT_SCHEMA = "ds02.stage2.f2-external-supervisor-report.v14"
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


def _v12_ref(path: Path) -> dict[str, Any]:
    request = load_json(path)
    if request.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v12":
        raise SupervisorError("v12 request schema differs")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise SupervisorError("v12 request is not ready")
    if request.get("sha256") != canonical_sha(request):
        raise SupervisorError("v12 request canonical SHA differs")
    storage = request.get("storage_scope")
    accounting = request.get("accounting")
    execution = request.get("execution")
    if not isinstance(storage, Mapping) or not isinstance(accounting, Mapping) or not isinstance(execution, Mapping):
        raise SupervisorError("v12 storage/accounting/execution binding is incomplete")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if not external.is_dir():
        raise SupervisorError(f"v12 external filesystem is missing: {external}")
    trace = Path(str(request.get("trace", {}).get("path", ""))).expanduser().resolve()
    sidecar = Path(str(execution.get("trace_finalization_sidecar", ""))).expanduser().resolve()
    if not _under(trace, external) or not _under(sidecar, external):
        raise SupervisorError("v12 trace and sidecar must remain on the bound external filesystem")
    for key in ("python", "bridge", "strace"):
        path_value = Path(str(execution.get(key, ""))).expanduser().resolve()
        if not path_value.is_file():
            raise SupervisorError(f"v12 execution source is missing: {key}")
    ledger = Path(str(accounting.get("ledger_path", ""))).expanduser().resolve()
    if not ledger.is_file():
        raise SupervisorError("v12 parent ledger is missing")
    v11_path = Path(str(request.get("v11_launch", {}).get("path", ""))).expanduser().resolve()
    if not v11_path.is_file():
        raise SupervisorError("v12 v11-launch source is missing")
    v11 = load_json(v11_path)
    bridge_path = Path(str(v11.get("bridge_request", {}).get("path", ""))).expanduser().resolve()
    if not bridge_path.is_file():
        raise SupervisorError("v12 transitive bridge request is missing")
    bridge = load_json(bridge_path)
    runtime_binding = next((item for item in bridge.get("guard_bindings", [])
                            if isinstance(item, Mapping) and item.get("role") == "shared_runtime_v6"), None)
    if not isinstance(runtime_binding, Mapping):
        raise SupervisorError("v12 transitive shared_runtime_v6 binding is missing")
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "shared_runtime_v6.sha256")
    if not runtime_path.is_file():
        raise SupervisorError("v12 transitive shared runtime is missing")
    return {"request": request, "external": external, "ledger": ledger,
            "trace": trace, "sidecar": sidecar, "accounting": dict(accounting),
            "execution": dict(execution), "attempt_id": str(accounting.get("attempt_id", "")),
            "v11_path": v11_path, "bridge_path": bridge_path,
            "runtime_path": runtime_path, "runtime_sha256": runtime_sha}


def _static_bindings(v12_path: Path, bound: Mapping[str, Any], supervisor_python: Path) -> list[dict[str, Any]]:
    values = [
        ("v12_request", v12_path),
        ("v12_launcher_v12", V12_PATH),
        ("v13_helper_v13", V13_PATH),
        ("supervisor_python", supervisor_python),
    ]
    for key in ("python", "bridge", "strace"):
        values.append((f"v12_{key}", Path(str(bound["execution"][key])).expanduser().resolve()))
    values.append(("shared_runtime_v6", Path(str(bound["runtime_path"])).expanduser().resolve()))
    result = []
    for role, path in values:
        if not path.is_file():
            raise SupervisorError(f"bound static source is missing: {path}")
        stat = path.stat()
        result.append({"role": role, "path": str(path), "sha256": sha256_file(path),
                       "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
    return result


def build_request(v12_path: Path | str, output_path: Path | str, *, output_root: Path | str,
                  max_wall_seconds: float = 6000.0, supervisor_python: Path | str | None = None) -> dict[str, Any]:
    v12_path = Path(v12_path).expanduser().resolve()
    bound = _v12_ref(v12_path)
    output_root = Path(output_root).expanduser().resolve()
    _no_symlink_components(output_root)
    if output_root.exists():
        raise SupervisorError(f"supervisor output namespace already exists: {output_root}")
    if not _under(output_root, bound["external"]):
        raise SupervisorError("supervisor output must be under v12 external filesystem")
    if output_root == bound["external"]:
        raise SupervisorError("supervisor output must be a new child namespace")
    if output_root == bound["ledger"].parent.parent or _under(output_root, bound["ledger"].parent.parent):
        raise SupervisorError("supervisor output must not be inside parent data root")
    if not math.isfinite(float(max_wall_seconds)) or float(max_wall_seconds) <= 0:
        raise SupervisorError("max_wall_seconds must be positive")
    python = Path(supervisor_python or sys.executable).expanduser().resolve()
    bindings = _static_bindings(v12_path, bound, python)
    output = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": str(bound["request"].get("case_id", "")),
        "attempt_id": str(bound["attempt_id"]) + "-supervisor-v14",
        "forward_of": {"v12_request": str(v12_path), "v12_sha256": bound["request"].get("sha256"),
                        "immutable": True},
        "v12_request": {"path": str(v12_path), "sha256": bound["request"].get("sha256"), "immutable": True},
        "v13": {"script": str(V13_PATH), "script_sha256": sha256_file(V13_PATH),
                "request_path": str(output_root / "v13-supplemental-request.json"),
                "report_path": str(output_root / "v13-supplemental-report.json")},
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
                       "supplemental_charge_id": str(bound["attempt_id"]) + "::supervisor-v14",
        },
        "runtime_binding": {"path": str(bound["runtime_path"]), "sha256": bound["runtime_sha256"],
                            "role": "shared_runtime_v6", "immutable": True},
        "storage_scope": {"external_filesystem": str(bound["external"]),
                          "new_namespace_absent_before_run": True,
                          "home_receipt_bytes": 0,
                          "estimated_output_bytes": 4 * 1024 * 1024,
                          "external_min_free_bytes": 1},
        "execution": {"max_wall_seconds": float(max_wall_seconds),
                       "start_clock": "supervisor function entry",
                       "v12_cli": [str(Path(str(bound["execution"]["python"]))), "-B", str(V12_PATH),
                                   "run", "--request", str(v12_path), "--parent-pid", "<supervisor_pid>"],
                       "v13_build_apply": True, "child_process_group": "v12 group created by supervisor",
                       "cancel_scope": "own v12 group only; v12 owns its strace/bridge group",
                       "wait_policy": "communicate with remaining deadline; bounded group cleanup; never trust strace exit alone"},
        "static_bindings": bindings,
        "accounting": {"ledger_owner": "existing DS-DATA-02 parent ledger",
                       "v10_cpu_subtracted": True, "v13_cpu_subtracted": True,
                       "supplemental_scope": "supervisor residual CPU plus supervisor output namespace bytes",
                       "idempotent": True, "no_ledger_reset": True},
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "raw_opened": False, "hdf5_opened": False,
        "limitations": [
            "This request is a parent-scheduled development replay; it grants no QI/QN/QE.",
            "v12/v10 scientific output and trace bytes remain bound to their original immutable requests.",
            "The supervisor charge excludes CPU already recorded by the v10 terminal row and v13 helper row; missing rows fail closed.",
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
    v12_ref = request.get("v12_request")
    if not isinstance(v12_ref, Mapping):
        raise SupervisorError("v12 request binding is missing")
    v12_path = Path(str(v12_ref.get("path", ""))).expanduser().resolve()
    bound = _v12_ref(v12_path)
    if v12_ref.get("sha256") != bound["request"].get("sha256"):
        raise SupervisorError("v12 request SHA differs")
    paths = request.get("paths")
    v13 = request.get("v13")
    if not isinstance(paths, Mapping) or not isinstance(v13, Mapping):
        raise SupervisorError("supervisor output/v13 paths are incomplete")
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
        path = Path(str(v13.get(key, ""))).expanduser().resolve()
        if not _under(path, output_root):
            raise SupervisorError(f"v13 {key} is outside output namespace")
        if path.exists():
            raise SupervisorError(f"v13 {key} already exists")
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
        raise SupervisorError("shared runtime binding differs from v12 transitive source")
    scope = request.get("storage_scope")
    if not isinstance(scope, Mapping):
        raise SupervisorError("storage_scope is missing")
    external = Path(str(scope.get("external_filesystem", ""))).expanduser().resolve()
    if external != bound["external"]:
        raise SupervisorError("external filesystem differs from v12")
    if int(scope.get("estimated_output_bytes", 0)) <= 0:
        raise SupervisorError("estimated output bytes must be positive")
    return {"bound": bound, "v12_path": v12_path, "output_root": output_root,
            "paths": {key: Path(str(paths[key])).expanduser().resolve() for key in ("stdout", "stderr", "report")},
            "v13_request": Path(str(v13["request_path"])).expanduser().resolve(),
            "v13_report": Path(str(v13["report_path"])).expanduser().resolve(),
            "supervisor_python": supervisor_python,
            "max_wall_seconds": float(request.get("execution", {}).get("max_wall_seconds", 0))}


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


def _charge_wrapper(runtime_path: Path, expected_runtime_sha: str, ledger_path: Path, charge_id: str, attempt_id: str,
                    *, external: Path, bytes_count: int, cpu_seconds: float,
                    status: str, max_storage: int | None = None,
                    max_cpu: float | None = None) -> dict[str, Any]:
    # Import the exact v6/v2 runtime bound by the parent request.  It only
    # supplies ledger_locked; this helper does not create a second ledger.
    spec = importlib.util.spec_from_file_location("ds02_supervisor_bound_runtime_v14", runtime_path)
    if spec is None or spec.loader is None:
        raise SupervisorError("cannot import bound runtime for supplemental charge")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    if sha256_file(runtime_path) != expected_runtime_sha:
        raise SupervisorError("shared runtime changed before supervisor charge")
    data_root = ledger_path.parent.parent
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        existing = [row for row in charges if isinstance(row, Mapping) and row.get("id") == charge_id]
        if existing:
            row = existing[-1]
            if (int(row.get("new_storage_bytes", -1)) != int(bytes_count)
                    or row.get("status") != status):
                raise SupervisorError("supervisor charge ID already has different accounting")
            return {"status": "IDEMPOTENT_ALREADY_CHARGED", "charge": dict(row), "ledger_mutated": False}
        parent = [row for row in charges if isinstance(row, Mapping) and row.get("id") == attempt_id]
        if not parent or any(str(row.get("status")) in {"reserved", "running"} for row in parent):
            raise SupervisorError("parent attempt is not terminal before supervisor charge")
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
        if max_cpu is not None:
            used = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0) for row in charges)
            if used + float(cpu_seconds) > float(max_cpu):
                raise SupervisorError("parent CPU limit would be exceeded")
        stat = os.statvfs(external)
        if int(stat.f_bavail * stat.f_frsize) < int(bytes_count):
            raise SupervisorError("external output filesystem lacks final product headroom")
        row = {"id": charge_id, "parent_attempt_id": attempt_id,
               "kind": "external_supervisor_v14", "gpu_seconds": 0.0,
               "cpu_core_seconds": float(cpu_seconds), "new_storage_bytes": int(bytes_count),
               "external_storage_bytes": int(bytes_count), "home_storage_bytes": 0,
               "storage_filesystems": [str(external), str(data_root)], "status": status,
               "finished_at_utc": datetime.now(timezone.utc).isoformat(),
               "accounting_scope": "same_parent_supervisor_residual_cpu_and_new_nvme_logs_reports"}
        charges.append(row)
    return {"status": "SUPERVISOR_CHARGE_APPLIED", "charge": row, "ledger_mutated": True}


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if not io_slot_approved:
        checked = _validate_request(request, verify_content=False)
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                "request_sha256": sha256_file(request_file), "ledger_mutated": False,
                "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
                "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    # The stat-only pass binds the deadline before any static source hashing.
    # The second pass therefore charges/limits the actual content verification
    # as part of the same supervisor entry-to-terminal interval.
    checked = _validate_request(request, verify_content=False)
    max_wall = checked["max_wall_seconds"]
    previous = _install_signals(max_wall)
    try:
        checked = _validate_request(request, verify_content=True)
    except BaseException:
        _restore_signals(previous)
        raise
    output_root: Path = checked["output_root"]
    paths = checked["paths"]
    bound = checked["bound"]
    child: subprocess.Popen[str] | None = None
    v12_stdout = ""
    v12_stderr = ""
    v12_result: dict[str, Any] | None = None
    v13_result: dict[str, Any] | None = None
    cleanup: dict[str, Any] = {}
    status = "FAILED_EXTERNAL_SUPERVISOR"
    error: str | None = None
    child_returncode: int | None = None
    try:
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise SupervisorCancelled("supervising parent already exited")
        live = _disk_probe(bound["external"])
        estimated = int(request["storage_scope"]["estimated_output_bytes"])
        min_free = int(request["storage_scope"].get("external_min_free_bytes", 1))
        if live["free_bytes"] - estimated < min_free:
            raise SupervisorError("external output headroom estimate would cross floor")
        output_root.mkdir(parents=True, exist_ok=False)
        python = Path(str(bound["execution"]["python"])).expanduser().resolve()
        command = [str(python), "-B", str(V12_PATH), "run", "--request", str(checked["v12_path"]),
                   "--parent-pid", str(os.getpid())]
        launcher_pid = os.getpid()
        child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parents[1]), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True,
                                 preexec_fn=(lambda: _parent_death(launcher_pid)) if parent_pid is not None else None)
        remaining = max(0.001, max_wall - (time.monotonic() - entry_wall))
        try:
            v12_stdout, v12_stderr = child.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            cleanup = _stop_group(child)
            error = "supervisor wall deadline exceeded while v12 was active"
        child_returncode = child.returncode
        v12_result = _parse_last_json(v12_stdout)
        if v12_result is None:
            raise SupervisorError("v12 did not emit a JSON report")
        # The v12 report, not strace's return code, is the accounting/bridge
        # result that gates completion.  v13 still runs after a terminal v12
        # failure so its idempotent parent-side trace accounting is preserved.
        remaining = max(0.001, max_wall - (time.monotonic() - entry_wall))
        v13_request = checked["v13_request"]
        v13_report = checked["v13_report"]
        supervisor_python = checked["supervisor_python"]
        build_cmd = [str(supervisor_python), "-B", str(V13_PATH), "build-request",
                     "--v12-request", str(checked["v12_path"]), "--output", str(v13_request)]
        build = subprocess.run(build_cmd, cwd=str(SCRIPT_DIR.parents[1]), capture_output=True,
                               text=True, timeout=remaining, check=False)
        if build.returncode != 0:
            raise SupervisorError(f"v13 build failed: {build.stderr[-1000:]}")
        apply_cmd = [str(supervisor_python), "-B", str(V13_PATH), "apply", "--request", str(v13_request)]
        apply = subprocess.run(apply_cmd, cwd=str(SCRIPT_DIR.parents[1]), capture_output=True,
                               text=True, timeout=max(0.001, max_wall - (time.monotonic() - entry_wall)), check=False)
        v13_result = _parse_last_json(apply.stdout)
        v13_report.write_text(json.dumps(v13_result or {"status": "V13_NO_JSON", "stdout": apply.stdout,
                                                         "stderr": apply.stderr}, indent=2, sort_keys=True) + "\n")
        if apply.returncode != 0 or not isinstance(v13_result, Mapping):
            raise SupervisorError(f"v13 apply failed: {apply.stderr[-1000:]}")
        if v12_result.get("status") == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN" and apply.returncode == 0:
            status = "COMPLETED_EXTERNAL_SUPERVISOR_DEVELOPMENT_UNKNOWN"
        else:
            status = "FAILED_EXTERNAL_SUPERVISOR_CHILD"
            if error is None:
                error = str(v12_result.get("error") or "v12 did not complete")
    except (SupervisorDeadline, SupervisorCancelled, subprocess.TimeoutExpired) as exc:
        status = "FAILED_EXTERNAL_SUPERVISOR_DEADLINE" if isinstance(exc, (SupervisorDeadline, subprocess.TimeoutExpired)) else "FAILED_EXTERNAL_SUPERVISOR_CANCELLED"
        error = str(exc)
        if child is not None:
            cleanup = _stop_group(child)
    except BaseException as exc:
        status = "FAILED_EXTERNAL_SUPERVISOR"
        error = f"{type(exc).__name__}: {exc}"
        if child is not None:
            cleanup = _stop_group(child)
    finally:
        _restore_signals(previous)
    # Persist child logs before measuring the supervisor namespace.  These are
    # actual new NVMe bytes and are charged under the parent lock below.
    try:
        paths["stdout"].write_text(v12_stdout)
        paths["stderr"].write_text(v12_stderr)
    except BaseException as exc:
        if error is None:
            error = f"log finalization: {type(exc).__name__}: {exc}"
        status = "FAILED_EXTERNAL_SUPERVISOR_FINALIZATION"
    total_cpu = max(0.0, _cpu_seconds() - entry_cpu)
    try:
        v10_cpu = _v10_cpu(bound["ledger"], bound["attempt_id"])
    except SupervisorError:
        v10_cpu = None
        if error is None:
            error = "v10 terminal CPU row is unavailable; residual charge not applied"
        status = "FAILED_EXTERNAL_SUPERVISOR_ACCOUNTING_UNCONFIRMED"
    v13_cpu = float(v13_result.get("cpu_core_seconds", 0.0)) if isinstance(v13_result, Mapping) else 0.0
    residual = max(0.0, total_cpu - float(v10_cpu or 0.0) - v13_cpu) if v10_cpu is not None else 0.0
    report = {
        "schema": REPORT_SCHEMA, "status": status,
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "parent": {"ledger_path": str(bound["ledger"]), "attempt_id": bound["attempt_id"],
                   "same_parent_ledger": True, "ledger_reset": False, "parent_pid": parent_pid},
        "v12": {"returncode": child_returncode, "result": v12_result,
                "stdout_tail": v12_stdout[-4000:], "stderr_tail": v12_stderr[-4000:]},
        "v13": {"result": v13_result, "request_path": str(checked["v13_request"]),
                "report_path": str(checked["v13_report"])},
        "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                       "entry_cpu_core_seconds": total_cpu,
                       "residual_supervisor_cpu_core_seconds": residual,
                       "max_rss_observed_bytes": _max_rss_bytes(),
                       "cleanup": cleanup, "model_invoked": False, "cfd_invoked": False,
                       "hard_wall_covers": ["v12 launch", "v12 wait", "v13 build/apply", "log/report finalization"],
                       "cancel_scope": "own v12 process group only"},
        "accounting": {"v10_cpu_subtracted": float(v10_cpu or 0.0),
                       "v13_cpu_subtracted": v13_cpu,
                       "supervisor_cpu_total_before_subtraction": total_cpu,
                       "residual_cpu_to_charge": residual,
                       "v10_row_required": True,
                       "supplemental_charge_id": str(bound["attempt_id"]) + "::supervisor-v14",
                       "external_product_bytes_measured_after_log_finalization": None,
                       "ledger_mutated_by_supervisor": False,
                       "v13_helper_owns_trace_sidecar_charge": True},
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
        # Keep the report itself immutable after its first write; exact bytes
        # used for the parent charge are returned in the supervisor result and
        # in the ledger row.  Rewriting it would make an unbounded fixed-point
        # receipt unnecessary for this small supervisor namespace.
        charge_result = None
        if v10_cpu is not None:
            limits = load_json(bound["ledger"]).get("limits", {})
            limits = load_json(bound["ledger"]).get("limits", {})
            charge_result = _charge_wrapper(
                Path(str(request["runtime_binding"]["path"])), str(request["runtime_binding"]["sha256"]), bound["ledger"],
                str(bound["attempt_id"]) + "::supervisor-v14", bound["attempt_id"],
                external=bound["external"], bytes_count=output_bytes,
                cpu_seconds=residual, status="completed",
                max_storage=int(limits["new_storage_bytes"]) if limits.get("new_storage_bytes") is not None else None,
                max_cpu=float(limits["cpu_core_seconds"]) if limits.get("cpu_core_seconds") is not None else None)
            report["accounting"]["ledger_mutated_by_supervisor"] = bool(charge_result.get("ledger_mutated"))
            report["accounting"]["charge_result"] = charge_result
        return {"schema": REPORT_SCHEMA, "status": status,
                "report_path": str(paths["report"]), "output_root": str(output_root),
                "new_logs_and_reports_bytes": output_bytes,
                "residual_supervisor_cpu_core_seconds": residual,
                "v10_cpu_subtracted": float(v10_cpu or 0.0), "v13_cpu_subtracted": v13_cpu,
                "v12_returncode": child_returncode, "v13_status": v13_result.get("status") if isinstance(v13_result, Mapping) else None,
                "ledger_mutated": bool(charge_result and charge_result.get("ledger_mutated")), "model_invoked": False, "cfd_invoked": False,
                "qualification": dict(UNKNOWN)}
    except BaseException as exc:
        return {"schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_FINALIZATION",
                "error": f"{type(exc).__name__}: {exc}", "report_path": str(paths["report"]),
                "output_root": str(output_root), "ledger_mutated": False,
                "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v12-request", type=Path, required=True)
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
            value = build_request(args.v12_request, args.output, output_root=args.output_root,
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
