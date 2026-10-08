#!/usr/bin/env python3
"""Parent-owned dual-filesystem guard for the fresh F2 v34 executor.

The v32/v33/v34 executor is deliberately a closed raw-to-label command, but
it does not own the Stage2 resource ledger.  This entry point is the small
parent boundary that was missing between that command and the shared guard:

``metadata preflight -> same-parent reservation -> source/content copy/hash
-> v34 child process group -> output/trace measurement -> same-parent charge``.

The reservation is made before any of the 443 source entries are content
hashed.  Home and the external output filesystem are represented separately
in both the reservation and terminal charge.  The wrapper never creates a
ledger or a data root, and it never changes the immutable v33 request.  A
parent PID is required for the actual run; the child receives PDEATHSIG and
stays in the wrapper's process group so cancellation reaches the nested raw
worker and evaluator.  The wrapper grants no scientific qualification.

This file is intentionally additive.  It does not route the historical V25
V15 graph and it does not read HDF5/BI4 during ``preflight``.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
RUNTIME_V6_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v6.py"
V34_DEFAULT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v34.py"
SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-report.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1
CHILD_CLEANUP_GRACE_SECONDS = 25.0


class ParentExecutorError(RuntimeError):
    """A source, accounting, or process-boundary error."""


class ParentDeadline(ParentExecutorError):
    pass


class ParentCancelled(ParentExecutorError):
    pass


def _load_v21():
    spec = importlib.util.spec_from_file_location("ds02_bound_external_supervisor_v21", V21_PATH)
    if spec is None or spec.loader is None:
        raise ParentExecutorError(f"cannot load shared V21 accounting helpers: {V21_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V21 = _load_v21()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


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
        raise ParentExecutorError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ParentExecutorError(f"JSON object required: {target}")
    return value


def _require_file(path: Any, role: str) -> Path:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise ParentExecutorError(f"{role} path is missing")
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ParentExecutorError(f"{role} is missing: {target}")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise ParentExecutorError(f"{name} must be a lowercase SHA-256")
    return value


def _under(path: Path, root: Path) -> bool:
    path = path.expanduser().resolve()
    root = root.expanduser().resolve()
    return path == root or root in path.parents


def _no_symlink_components(path: Path) -> None:
    target = path.expanduser()
    current = target if target.exists() else target.parent
    missing: list[str] = []
    while not current.exists() and current != current.parent:
        missing.append(current.name)
        current = current.parent
    if current.is_symlink():
        raise ParentExecutorError(f"symlink output component is forbidden: {current}")
    for name in reversed(missing):
        current = current / name
        if current.is_symlink():
            raise ParentExecutorError(f"symlink output component is forbidden: {current}")
    if target.exists() and target.is_symlink():
        raise ParentExecutorError(f"symlink output path is forbidden: {target}")


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ParentExecutorError(f"refusing existing output: {target}")
    _no_symlink_components(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _tree_bytes(root: Path) -> int:
    root = root.expanduser().resolve()
    total = 0
    if not root.exists():
        return 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ParentExecutorError(f"symlink output file is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _disk_free(path: Path) -> int:
    stat = os.statvfs(path.expanduser().resolve())
    return int(stat.f_bavail * stat.f_frsize)


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _deadline_epoch(value: Any) -> float | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as error:
        raise ParentExecutorError("parent deadline_utc is malformed") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _runtime(path: Path, expected_sha: str):
    path = _require_file(path, "shared runtime")
    expected_sha = _require_sha(expected_sha, "shared runtime SHA")
    if sha256_file(path) != expected_sha:
        raise ParentExecutorError(f"shared runtime SHA differs: {path}")
    spec = importlib.util.spec_from_file_location("ds02_bound_parent_runtime_v6", path)
    if spec is None or spec.loader is None:
        raise ParentExecutorError("cannot import bound shared runtime")
    module = importlib.util.module_from_spec(spec)
    # runtime_v6 imports its immutable runtime_v2 sibling by module name.
    # Loading v6 through a file spec does not automatically add that sibling's
    # directory to sys.path, so provide exactly the bound source directory for
    # this import and remove the path afterwards.  No PYTHONPATH/original
    # checkout fallback is introduced.
    source_dir = str(path.parent)
    had_dir = source_dir in sys.path
    if not had_dir:
        sys.path.insert(0, source_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if not had_dir:
            try:
                sys.path.remove(source_dir)
            except ValueError:
                pass
    if not callable(getattr(module, "ledger_locked", None)):
        raise ParentExecutorError("bound shared runtime has no ledger_locked API")
    return module


def _v34_metadata(executor_path: Path, external: Path) -> dict[str, Any]:
    """Validate the executor graph without hashing its scientific sources."""
    executor = load_json(executor_path)
    if executor.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise ParentExecutorError("parent guard requires the fresh v34 executor request")
    if executor.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise ParentExecutorError("v34 request is not ready for parent guard")
    if executor.get("sha256") != canonical_sha(executor):
        raise ParentExecutorError("v34 request canonical SHA differs")
    if executor.get("role") != "DEVELOPMENT" or executor.get("model_invoked") is not False:
        raise ParentExecutorError("v34 request must remain model-free DEVELOPMENT")
    if executor.get("cfd_invoked") is not False or executor.get("qualification") != UNKNOWN:
        raise ParentExecutorError("v34 request must keep CFD false and qualification UNKNOWN")
    execution = executor.get("execution")
    if not isinstance(execution, Mapping) or execution.get("original_path_fallback") != "FORBIDDEN":
        raise ParentExecutorError("v34 request does not forbid original source fallback")
    roots = executor.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise ParentExecutorError("v34 fresh roots are missing")
    for key in ("target_root", "output_root"):
        target = Path(str(roots.get(key, ""))).expanduser().resolve()
        if target.exists():
            raise ParentExecutorError(f"v34 {key} already exists: {target}")
        if not _under(target, external) or target == external:
            raise ParentExecutorError(f"v34 {key} is outside the bound external filesystem")
        _no_symlink_components(target)
    source_entries = executor.get("source_entries")
    if not isinstance(source_entries, list) or not source_entries:
        raise ParentExecutorError("v34 source_entries are missing")
    # Stat only.  The child performs the expensive SHA pass after reservation.
    for index, item in enumerate(source_entries):
        if not isinstance(item, Mapping):
            raise ParentExecutorError(f"v34 source_entries[{index}] is malformed")
        path = _require_file(item.get("path"), f"v34 source_entries[{index}]")
        expected_bytes = int(item.get("bytes", -1))
        if path.stat().st_size != expected_bytes:
            raise ParentExecutorError(f"v34 source byte stat differs before reservation: {path}")
    runtime_sources = executor.get("runtime_sources")
    if not isinstance(runtime_sources, list) or not runtime_sources:
        raise ParentExecutorError("v34 runtime_sources are missing")
    for index, item in enumerate(runtime_sources):
        if not isinstance(item, Mapping):
            raise ParentExecutorError(f"v34 runtime_sources[{index}] is malformed")
        path = _require_file(item.get("path"), f"v34 runtime_sources[{index}]")
        if path.stat().st_size != int(item.get("bytes", -1)):
            raise ParentExecutorError(f"v34 runtime byte stat differs before reservation: {path}")
    return executor


def _static_binding(path: Path, role: str) -> dict[str, Any]:
    path = _require_file(path, role)
    stat = path.stat()
    return {"role": role, "path": str(path), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(path)}


def build_request(*, executor_request: Path | str, output: Path | str,
                  external_filesystem: Path | str | None = None,
                  ledger_path: Path | str | None = None,
                  parent_attempt_id: str | None = None,
                  max_wall_seconds: float = 6000.0,
                  external_bytes: int | None = None,
                  home_receipt_bytes: int = 64 * 1024,
                  home_receipt_path: Path | str | None = None,
                  supervisor_output_root: Path | str | None = None,
                  home_path: Path | str = "/home/jade",
                  external_min_free_bytes: int = 1,
                  home_min_free_bytes: int | None = None,
                  runtime_v6: Path | str = RUNTIME_V6_DEFAULT,
                  executor_script: Path | str = V34_DEFAULT,
                  allow_missing_parent: bool = True) -> dict[str, Any]:
    executor_path = _require_file(executor_request, "v34 executor request")
    executor = load_json(executor_path)
    external = Path(external_filesystem or executor.get("parent_resource_binding", {}).get(
        "external_filesystem", "")).expanduser().resolve()
    if not external.is_dir():
        raise ParentExecutorError(f"external filesystem is missing: {external}")
    executor = _v34_metadata(executor_path, external)
    ledger = Path(ledger_path or executor.get("parent_resource_binding", {}).get(
        "ledger_path", "")).expanduser().resolve()
    if not ledger.is_file():
        raise ParentExecutorError(f"parent ledger is missing: {ledger}")
    runtime_path = _require_file(runtime_v6, "runtime v6")
    runtime_sha = sha256_file(runtime_path)
    executor_script_path = _require_file(executor_script, "v34 executor script")
    home = Path(home_path).expanduser().resolve()
    if not home.is_dir():
        raise ParentExecutorError(f"Home filesystem path is missing: {home}")
    limits = load_json(ledger).get("limits", {})
    declared_home_floor = int(limits.get("home_min_free_bytes", 0) or 0)
    if home_min_free_bytes is None:
        home_min_free_bytes = declared_home_floor
    if int(home_min_free_bytes) != declared_home_floor:
        raise ParentExecutorError("request cannot change the parent Home floor")
    if not math.isfinite(float(max_wall_seconds)) or float(max_wall_seconds) <= 0:
        raise ParentExecutorError("max_wall_seconds must be positive")
    source_bytes = sum(int(item.get("bytes", 0)) for item in executor.get("source_entries", []))
    if external_bytes is None:
        # Source copy plus a bounded allowance for reconstructed typed output,
        # labels, runtime logs, and the parent OS trace.  This is a real F2
        # single-case bound, not the old 14-sentinel planning proxy.
        external_bytes = source_bytes + 12 * 1024 ** 3
    if int(external_bytes) < source_bytes:
        raise ParentExecutorError("external reservation must cover the declared source copy")
    if int(home_receipt_bytes) <= 0:
        raise ParentExecutorError("home receipt reservation must be positive")
    output_root = Path(supervisor_output_root or (external / "f2-s1-portable-executor-parent-v1-041")).expanduser().resolve()
    if output_root.exists() or not _under(output_root, external) or output_root == external:
        raise ParentExecutorError("supervisor output namespace must be a new child of external")
    _no_symlink_components(output_root)
    receipt = Path(home_receipt_path or (
        SCRIPT_DIR.parent / "campaigns/ds-data-02/stage2/native-reconstruction/"
        "raw-to-label-v34-full-chain/f2-s1-portable-executor-parent-report-v1-041.json"
    )).expanduser().resolve()
    if receipt.exists():
        raise ParentExecutorError(f"Home receipt already exists: {receipt}")
    parent_id = str(parent_attempt_id or executor.get("parent_resource_binding", {}).get(
        "attempt_id", "f2-s1-portable-executor-v34-041"))
    reservation_id = parent_id + "::f2-v34-parent-reservation"
    charge_id = parent_id + "::f2-v34-parent-charge"
    deadline = str(load_json(ledger).get("deadline_utc", ""))
    bindings = [
        _static_binding(SCRIPT, "parent_executor_v1"),
        _static_binding(V21_PATH, "shared_v21_accounting"),
        _static_binding(runtime_path, "shared_runtime_v6"),
        _static_binding(executor_script_path, "executor_v34"),
        _static_binding(executor_path, "executor_v34_request"),
    ]
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": executor.get("case_id"),
        "attempt_id": parent_id + "::f2-v34-parent",
        "executor_request": {"path": str(executor_path), "sha256": sha256_file(executor_path),
                             "schema": executor.get("schema"), "immutable": True},
        "executor_script": {"path": str(executor_script_path), "sha256": sha256_file(executor_script_path),
                             "immutable": True},
        "parent_resource_binding": {
            "ledger_path": str(ledger), "attempt_id": parent_id,
            "same_parent_ledger": True, "ledger_reset": False, "no_new_data_root": True,
            "storage_policy": str(limits.get("storage_policy", "")),
            "deadline_utc": deadline, "home_path": str(home),
            "home_min_free_bytes": int(home_min_free_bytes),
            "external_filesystem": str(external),
            "reservation_id": reservation_id, "charge_id": charge_id,
            "allow_missing_parent": bool(allow_missing_parent),
        },
        "runtime_binding": {"path": str(runtime_path), "sha256": runtime_sha,
                            "role": "shared_runtime_v6", "immutable": True},
        "storage_scope": {
            "external_filesystem": str(external), "supervisor_output_root": str(output_root),
            "home_receipt_path": str(receipt), "home_receipt_bytes": int(home_receipt_bytes),
            "external_reservation_bytes": int(external_bytes),
            "source_copy_bytes": int(source_bytes),
            "external_min_free_bytes": int(external_min_free_bytes),
            "home_min_free_bytes": int(home_min_free_bytes),
            "two_filesystem_charge_required": True,
            "new_namespace_absent_before_run": True,
        },
        "execution": {
            "max_wall_seconds": float(max_wall_seconds),
            "cpu_reservation_seconds": float(max_wall_seconds),
            "child_cleanup_grace_seconds": CHILD_CLEANUP_GRACE_SECONDS,
            "entry_clock": "function entry before metadata validation/reservation",
            "reservation_order": "same-parent ledger reservation before source content SHA",
            "command": [str(executor.get("execution", {}).get("command", [str(executor_script_path)] [0]))],
            "closed_executor_command": [
                str(executor.get("execution", {}).get("command", [str(executor_script_path)])[0]),
                "-B", "-I", str(executor_script_path), "run", "--request", str(executor_path),
                "--io-slot-approved", "--parent-pid", "<parent_pid>",
                "--max-wall-seconds", str(float(max_wall_seconds)),
            ],
            "parent_death_signal": "PR_SET_PDEATHSIG=SIGTERM on wrapper and v34 child",
            "child_process_group": "v34 and nested worker/evaluator share wrapper-owned group",
            "cancel_scope": "own v34 process group only; 25s cooperative cleanup then SIGKILL",
            "os_trace": "outer shared guard must strace/openat the wrapper; trace bytes are charged if under external root",
            "hdf5_or_bi4_read": "only after --io-slot-approved and reservation",
        },
        "static_bindings": bindings,
        "accounting": {
            "owner": "existing DS-DATA-02 parent ledger",
            "reservation_id": reservation_id, "charge_id": charge_id,
            "same_parent_ledger": True, "idempotent": True,
            "charge_fields": ["cpu_core_seconds", "new_storage_bytes", "external_storage_bytes",
                               "home_storage_bytes", "trace_bytes", "copy_hash_bytes", "storage_filesystems"],
            "allow_missing_parent": bool(allow_missing_parent),
            "parent_terminal_requirement": "active parent rows are rejected; absent parent is explicit scoped fallback",
        },
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "qualification": dict(UNKNOWN),
        "limitations": [
            "This is a DEVELOPMENT parent replay and grants no QI/QN/QE.",
            "Scientific source SHA and HDF5/BI4 reads begin only after the reservation; metadata stat checks precede it.",
            "Parent OS strace is required for C-level HDF5/BI4 opens; Python audit alone is insufficient.",
            "The v34 child owns no ledger; the wrapper is the sole supplemental ledger writer.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    _write_new(output, request)
    return request


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    request_path = _require_file(path, "parent executor request")
    request = load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentExecutorError("unsupported or non-ready parent request")
    if request.get("sha256") != canonical_sha(request):
        raise ParentExecutorError("parent request canonical SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ParentExecutorError("parent request must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ParentExecutorError("parent request must keep model/CFD false")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    runtime_binding = request.get("runtime_binding")
    executor_binding = request.get("executor_request")
    script_binding = request.get("executor_script")
    if not all(isinstance(v, Mapping) for v in (parent, storage, execution, runtime_binding,
                                                 executor_binding, script_binding)):
        raise ParentExecutorError("parent request binding is incomplete")
    ledger = _require_file(parent.get("ledger_path"), "parent ledger")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if not external.is_dir():
        raise ParentExecutorError(f"external filesystem is missing: {external}")
    output_root = Path(str(storage.get("supervisor_output_root", ""))).expanduser().resolve()
    if output_root.exists() or not _under(output_root, external) or output_root == external:
        raise ParentExecutorError("supervisor output namespace is not fresh and external-bound")
    receipt = Path(str(storage.get("home_receipt_path", ""))).expanduser().resolve()
    if receipt.exists():
        raise ParentExecutorError("Home receipt already exists")
    _no_symlink_components(output_root)
    _no_symlink_components(receipt)
    executor_path = _require_file(executor_binding.get("path"), "v34 executor request")
    if executor_binding.get("sha256") != sha256_file(executor_path):
        raise ParentExecutorError("v34 executor request SHA differs")
    if executor_binding.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise ParentExecutorError("parent is not bound to v34 executor")
    executor = _v34_metadata(executor_path, external)
    if executor.get("sha256") != executor_binding.get("canonical_sha256", executor.get("sha256")):
        # canonical_sha is the request's own content identity; a missing
        # optional duplicate field is harmless, but a supplied value is strict.
        supplied = executor_binding.get("canonical_sha256")
        if supplied is not None:
            raise ParentExecutorError("v34 executor canonical binding differs")
    runtime_path = _require_file(runtime_binding.get("path"), "shared runtime")
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "shared runtime SHA")
    if runtime_path.stat().st_size <= 0:
        raise ParentExecutorError("shared runtime is empty")
    script_path = _require_file(script_binding.get("path"), "executor script")
    if script_binding.get("sha256") != sha256_file(script_path):
        raise ParentExecutorError("executor script SHA differs")
    v21_binding = next((x for x in request.get("static_bindings", [])
                        if isinstance(x, Mapping) and x.get("role") == "shared_v21_accounting"), None)
    if not isinstance(v21_binding, Mapping) or Path(str(v21_binding.get("path"))).expanduser().resolve() != V21_PATH:
        raise ParentExecutorError("shared V21 accounting binding is missing")
    for item in request.get("static_bindings", []):
        if not isinstance(item, Mapping):
            raise ParentExecutorError("static binding is malformed")
        source = _require_file(item.get("path"), str(item.get("role", "static")))
        if verify_static_content and _require_sha(item.get("sha256"), "static binding SHA") != sha256_file(source):
            raise ParentExecutorError(f"static binding content differs: {source}")
        if source.stat().st_size != int(item.get("bytes", -1)):
            raise ParentExecutorError(f"static binding byte stat differs: {source}")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    cpu_reserve = float(execution.get("cpu_reservation_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0 or abs(cpu_reserve - max_wall) > 1e-9:
        raise ParentExecutorError("one-thread CPU reservation must equal max wall")
    cleanup = float(execution.get("child_cleanup_grace_seconds", 0.0) or 0.0)
    if not math.isfinite(cleanup) or cleanup < 20.0:
        raise ParentExecutorError("child cleanup grace must be at least 20 seconds")
    source_bytes = int(storage.get("source_copy_bytes", 0) or 0)
    external_est = int(storage.get("external_reservation_bytes", 0) or 0)
    home_est = int(storage.get("home_receipt_bytes", 0) or 0)
    if source_bytes <= 0 or external_est < source_bytes or home_est <= 0:
        raise ParentExecutorError("dual-filesystem reservation fields are invalid")
    limits = load_json(ledger).get("limits", {})
    if str(parent.get("storage_policy", "")) != str(limits.get("storage_policy", "")):
        raise ParentExecutorError("parent storage policy differs from live ledger")
    if str(parent.get("deadline_utc", "")) != str(load_json(ledger).get("deadline_utc", "")):
        raise ParentExecutorError("parent deadline binding differs from live ledger")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise ParentExecutorError("Home floor differs from live ledger")
    if str(parent.get("reservation_id", "")) == str(parent.get("charge_id", "")):
        raise ParentExecutorError("reservation and charge IDs must be distinct")
    return {"path": request_path, "request": request, "ledger": ledger,
            "external": external, "output_root": output_root, "receipt": receipt,
            "executor_path": executor_path, "executor": executor,
            "runtime_path": runtime_path, "runtime_sha": runtime_sha,
            "executor_script": script_path, "max_wall": max_wall,
            "cleanup_grace": cleanup, "external_estimate": external_est,
            "home_estimate": home_est, "limits": limits,
            "parent_attempt_id": str(parent.get("attempt_id", "")),
            "reservation_id": str(parent.get("reservation_id", "")),
            "charge_id": str(parent.get("charge_id", "")),
            "allow_missing_parent": bool(parent.get("allow_missing_parent", False))}


def _reserve(bound: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _runtime(bound["runtime_path"], bound["runtime_sha"])
    ledger_path: Path = bound["ledger"]
    data_root = ledger_path.parent.parent
    external: Path = bound["external"]
    home = Path(str(bound["limits"].get("home_path", "/home/jade"))).expanduser().resolve()
    ext_bytes = int(bound["external_estimate"])
    home_bytes = int(bound["home_estimate"])
    cpu = float(bound["max_wall"])
    reservation_id = str(bound["reservation_id"])
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        reservations = ledger.setdefault("reservations", [])
        if any(isinstance(row, Mapping) and row.get("id") in {reservation_id, str(bound["charge_id"])}
               for row in charges + reservations):
            raise ParentExecutorError("parent reservation/charge ID already exists")
        deadline = _deadline_epoch(ledger.get("deadline_utc"))
        if deadline is not None and time.time() + float(bound["max_wall"]) >= deadline:
            raise ParentExecutorError("parent deadline cannot contain executor window")
        policy = str(ledger.get("limits", {}).get("storage_policy", ""))
        if not policy:
            raise ParentExecutorError("live ledger has no storage policy")
        existing_external, existing_home = V21._reservation_storage_totals(
            reservations, external=external, home_path=home)
        if _disk_free(home) - existing_home - home_bytes < int(bound["limits"].get("home_min_free_bytes", 0) or 0):
            raise ParentExecutorError("Home floor lacks reservation headroom")
        if _disk_free(external) - existing_external - ext_bytes < int(
                bound["request"]["storage_scope"].get("external_min_free_bytes", 0) or 0):
            raise ParentExecutorError("external floor lacks reservation headroom")
        used_cpu = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0)
                       for row in charges + reservations if isinstance(row, Mapping))
        max_cpu = ledger.get("limits", {}).get("cpu_core_seconds")
        if max_cpu is not None and used_cpu + cpu > float(max_cpu):
            raise ParentExecutorError("parent CPU budget lacks executor reservation")
        row = {
            "id": reservation_id, "parent_attempt_id": str(bound["parent_attempt_id"]),
            "kind": "f2_portable_executor_parent", "status": "reserved",
            "cpu_threads": 1, "cpu_core_seconds": cpu, "gpu_seconds": 0.0,
            "new_storage_bytes": ext_bytes + home_bytes,
            "external_storage_bytes": ext_bytes, "home_storage_bytes": home_bytes,
            "storage_filesystems": [str(external), str(home)],
            "storage_policy": policy,
            "external_min_free_bytes": int(bound["request"]["storage_scope"].get("external_min_free_bytes", 0) or 0),
            "home_min_free_bytes": int(bound["limits"].get("home_min_free_bytes", 0) or 0),
            "reservation_cpu_basis": "one CPU thread multiplied by max_wall_seconds",
            "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        reservations.append(row)
    return {"status": "PARENT_RESERVATION_APPLIED", "reservation": row, "ledger_mutated": True}


def _release(bound: Mapping[str, Any]) -> bool:
    runtime = _runtime(bound["runtime_path"], bound["runtime_sha"])
    with runtime.ledger_locked(bound["ledger"].parent.parent) as ledger:
        rows = ledger.setdefault("reservations", [])
        before = len(rows)
        rows[:] = [row for row in rows if not (isinstance(row, Mapping) and
                                               row.get("id") == bound["reservation_id"])]
        return before != len(rows)


def _charge(bound: Mapping[str, Any], *, status: str, cpu_seconds: float,
            external_bytes: int, home_bytes: int, trace_bytes: int,
            copy_hash_bytes: int, allow_missing_parent: bool) -> dict[str, Any]:
    runtime = _runtime(bound["runtime_path"], bound["runtime_sha"])
    external = bound["external"]
    home = Path(str(bound["limits"].get("home_path", "/home/jade"))).expanduser().resolve()
    reservation_id = str(bound["reservation_id"])
    charge_id = str(bound["charge_id"])
    with runtime.ledger_locked(bound["ledger"].parent.parent) as ledger:
        charges = ledger.setdefault("charges", [])
        reservations = ledger.setdefault("reservations", [])
        existing = [row for row in charges if isinstance(row, Mapping) and row.get("id") == charge_id]
        if existing:
            row = dict(existing[-1])
            if int(row.get("external_storage_bytes", -1)) != int(external_bytes):
                raise ParentExecutorError("idempotent parent charge has different external bytes")
            return {"status": "PARENT_CHARGE_ALREADY_APPLIED", "charge": row, "ledger_mutated": False}
        parent_rows = [row for row in charges if isinstance(row, Mapping) and
                       row.get("id") == bound["parent_attempt_id"]]
        if any(str(row.get("status")) in {"reserved", "running"} for row in parent_rows):
            raise ParentExecutorError("active parent attempt cannot be charged before terminal")
        if not parent_rows and not allow_missing_parent:
            raise ParentExecutorError("parent attempt row is absent and fallback is disabled")
        if any(isinstance(row, Mapping) and row.get("id") == reservation_id for row in reservations):
            own_reservation = True
        else:
            own_reservation = False
        other_external, other_home = V21._reservation_storage_totals(
            reservations, external=external, home_path=home, exclude_id=reservation_id)
        external_floor = int(bound["request"]["storage_scope"].get("external_min_free_bytes", 0) or 0)
        home_floor = int(bound["limits"].get("home_min_free_bytes", 0) or 0)
        if _disk_free(external) - other_external < external_floor:
            raise ParentExecutorError("external floor would be crossed by remaining parent reservations")
        if _disk_free(home) - other_home < home_floor:
            raise ParentExecutorError("Home floor would be crossed by remaining parent reservations")
        max_cpu = ledger.get("limits", {}).get("cpu_core_seconds")
        used_cpu = sum(float(row.get("cpu_core_seconds", 0.0) or 0.0)
                       for row in charges + reservations
                       if isinstance(row, Mapping) and row.get("id") != reservation_id)
        if max_cpu is not None and used_cpu + float(cpu_seconds) > float(max_cpu):
            raise ParentExecutorError("parent CPU budget would be exceeded by charge")
        if own_reservation:
            reservations[:] = [row for row in reservations if not (
                isinstance(row, Mapping) and row.get("id") == reservation_id)]
        row = {
            "id": charge_id, "parent_attempt_id": str(bound["parent_attempt_id"]),
            "kind": "f2_portable_executor_parent", "status": str(status),
            "gpu_seconds": 0.0, "cpu_core_seconds": max(0.0, float(cpu_seconds)),
            "new_storage_bytes": int(external_bytes) + int(home_bytes),
            "external_storage_bytes": int(external_bytes), "home_storage_bytes": int(home_bytes),
            "trace_bytes": int(trace_bytes), "copy_hash_bytes": int(copy_hash_bytes),
            "storage_filesystems": [str(external), str(home)],
            "parent_terminal_charge_present": bool(parent_rows),
            "parent_missing_fallback": not bool(parent_rows),
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "accounting_scope": "fresh-v34-copy-hash-child-trace-and-home-receipt",
        }
        charges.append(row)
    return {"status": "PARENT_CHARGE_APPLIED", "charge": row, "ledger_mutated": True}


def _pdeath(parent_pid: int) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError("cannot install parent-death signal")
    if os.getppid() != int(parent_pid):
        os.kill(os.getpid(), signal.SIGTERM)


def _stop_group(proc: subprocess.Popen[Any], grace: float) -> dict[str, Any]:
    result = {"sigterm_sent": False, "sigkill_sent": False, "reaped": False,
              "grace_seconds": float(grace)}
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            result["sigterm_sent"] = True
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + max(0.1, float(grace))
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                result["sigkill_sent"] = True
            except (ProcessLookupError, PermissionError):
                pass
    try:
        proc.wait(timeout=max(1.0, float(grace)))
        result["reaped"] = True
    except subprocess.TimeoutExpired:
        result["reaped"] = False
    return result


def _json_fixed_point(value: dict[str, Any], *, key: str, limit: int = 32) -> int:
    predicted = 0
    for _ in range(limit):
        value[key] = int(predicted)
        encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                              allow_nan=False, default=str) + "\n").encode("utf-8")
        if len(encoded) == predicted:
            return predicted
        predicted = len(encoded)
    raise ParentExecutorError("Home receipt size fixed point did not converge")


def _install_handlers(max_wall: float):
    previous = {signal.SIGALRM: signal.getsignal(signal.SIGALRM),
                signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}

    def deadline(_signum, _frame):
        raise ParentDeadline("parent executor entry-to-child wall deadline exceeded")

    def cancelled(signum, _frame):
        raise ParentCancelled(f"parent executor cancelled by signal {signum}")

    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, float(max_wall)))
    return previous


def _restore_handlers(previous: Mapping[int, Any]) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _child_command(bound: Mapping[str, Any], parent_pid: int) -> list[str]:
    executor = bound["executor"]
    python = next((item for item in executor.get("runtime_sources", [])
                   if isinstance(item, Mapping) and item.get("role") == "python_executable"), None)
    if not isinstance(python, Mapping):
        raise ParentExecutorError("v34 python executable binding is missing")
    invocation = python.get("invocation_path") or python.get("path")
    invocation_path = _require_file(invocation, "v34 venv Python invocation")
    return [str(invocation_path), "-B", "-I", str(bound["executor_script"]),
            "run", "--request", str(bound["executor_path"]), "--io-slot-approved",
            "--parent-pid", str(parent_pid), "--max-wall-seconds", str(float(bound["max_wall"]))]


def _preflight_report(path: Path, bound: Mapping[str, Any]) -> dict[str, Any]:
    value = {
        "schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(bound["path"]), "sha256": sha256_file(bound["path"])},
        "ledger_mutated": False, "reservation_applied": False,
        "metadata_only": True, "content_hash_read": False, "hdf5_or_bi4_read": False,
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
    }
    value["sha256"] = canonical_sha(value)
    _write_new(path, value)
    return value


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    # Metadata validation is deliberately before reservation only; it performs
    # stats and JSON reads, never the 443 source content SHA pass.
    bound = _validate_request(request_file, verify_static_content=False)
    if not io_slot_approved:
        return _preflight_report(
            Path(str(bound["request"].get("preflight_report", request_file.with_suffix(".preflight.json")))),
            bound)
    if parent_pid is None or int(parent_pid) <= 1:
        raise ParentExecutorError("actual run requires an explicit parent PID")
    if os.getppid() != int(parent_pid):
        raise ParentCancelled("parent guard is not the direct parent")
    _pdeath(int(parent_pid))
    previous = _install_handlers(float(bound["max_wall"]))
    reservation_applied = False
    child: subprocess.Popen[Any] | None = None
    cleanup: dict[str, Any] = {}
    status = "FAILED_PARENT_EXECUTOR"
    error: str | None = None
    child_returncode: int | None = None
    child_result: dict[str, Any] | None = None
    output_root = bound["output_root"]
    log_stdout = output_root / "parent-executor.stdout.log"
    log_stderr = output_root / "parent-executor.stderr.log"
    try:
        reservation = _reserve(bound)
        reservation_applied = True
        # Only after this point may the expensive v34 content validation/copy
        # begin.  Static closure bytes are rechecked under the reservation.
        _validate_request(request_file, verify_static_content=True)
        output_root.mkdir(parents=True, exist_ok=False)
        command = _child_command(bound, os.getpid())
        with log_stdout.open("x", encoding="utf-8") as stdout, log_stderr.open("x", encoding="utf-8") as stderr:
            child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parent), stdout=stdout, stderr=stderr,
                                     start_new_session=True,
                                     preexec_fn=lambda: _pdeath(os.getpid()))
            try:
                child.wait(timeout=max(0.1, float(bound["max_wall"]) - (time.monotonic() - entry_wall)))
            except subprocess.TimeoutExpired as timeout_error:
                cleanup = _stop_group(child, float(bound["cleanup_grace"]))
                raise ParentDeadline("v34 executor exceeded the parent wall deadline") from timeout_error
        child_returncode = child.returncode
        stdout_text = log_stdout.read_text(encoding="utf-8", errors="replace")
        for line in reversed(stdout_text.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                child_result = candidate
                break
        if child_returncode != 0:
            raise ParentExecutorError(f"v34 executor returned {child_returncode}: {log_stderr.read_text(errors='replace')[-1200:]}")
        if child_result is None:
            raise ParentExecutorError("v34 executor emitted no JSON result")
        child_status = str(child_result.get("status", ""))
        if child_status.startswith("FAILED"):
            raise ParentExecutorError(f"v34 executor reported {child_status}")
        status = "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN"
    except (ParentDeadline, ParentCancelled) as exc:
        error = str(exc)
        status = "FAILED_PARENT_EXECUTOR_CANCELLED" if isinstance(exc, ParentCancelled) else "FAILED_PARENT_EXECUTOR_DEADLINE"
        if child is not None:
            cleanup = _stop_group(child, float(bound["cleanup_grace"]))
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_EXECUTOR"
        if child is not None:
            cleanup = _stop_group(child, float(bound["cleanup_grace"]))
    finally:
        _restore_handlers(previous)
    # Local finalization is outside SIGALRM but is measured explicitly.  The
    # child and source-copy phase above remains covered by the parent timer.
    try:
        external_roots = [output_root]
        roots = bound["executor"].get("fresh_roots", {})
        for key in ("target_root", "output_root"):
            candidate = Path(str(roots.get(key, ""))).expanduser().resolve()
            if candidate.exists() and all(not _under(candidate, old) and not _under(old, candidate)
                                          for old in external_roots):
                external_roots.append(candidate)
        external_bytes = sum(_tree_bytes(root) for root in external_roots if root.exists())
        trace_path = bound["request"].get("execution", {}).get("trace_path")
        trace_bytes = 0
        if trace_path:
            trace = Path(str(trace_path)).expanduser().resolve()
            if trace.exists():
                trace_bytes = _tree_bytes(trace.parent) if trace.is_dir() else int(trace.stat().st_size)
                if trace.parent == bound["external"]:
                    # The external namespace itself is not included in the
                    # output-root sum, so this is an additive trace byte.
                    external_bytes += trace_bytes
        copy_bytes = int(bound["executor"].get("source_entries", [{}])[0].get("bytes", 0)) if bound["executor"].get("source_entries") else 0
        copy_bytes = sum(int(item.get("bytes", 0)) for item in bound["executor"].get("source_entries", [])
                         if isinstance(item, Mapping))
        report = {
            "schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "parent": {"ledger_path": str(bound["ledger"]), "attempt_id": bound["parent_attempt_id"],
                       "same_parent_ledger": True, "ledger_reset": False, "parent_pid": parent_pid},
            "executor": {"path": str(bound["executor_path"]), "sha256": sha256_file(bound["executor_path"]),
                         "returncode": child_returncode, "result": child_result},
            "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                           "entry_cpu_core_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                           "max_rss_observed_bytes": _rss_bytes(), "cleanup": cleanup,
                           "hard_wall_covers": ["metadata/stat preflight", "same-parent reservation",
                                                 "v34 child copy/hash/worker/evaluator"],
                           "finalization_scope": "local report/stat/ledger charge after timer; measured separately",
                           "child_cleanup_grace_seconds": float(bound["cleanup_grace"]),
                           "cancel_scope": "own v34 process group only",
                           "model_invoked": False, "cfd_invoked": False},
            "filesystem": {"external_filesystem": str(bound["external"]),
                            "external_output_root": str(output_root),
                            "external_bytes_before_parent_charge": int(external_bytes),
                            "home_receipt_path": str(bound["receipt"]),
                            "home_receipt_bytes": None, "trace_bytes": int(trace_bytes),
                            "copy_hash_bytes": int(copy_bytes),
                            "storage_filesystems": [str(bound["external"]), str(bound["limits"].get("home_path", "/home/jade"))]},
            "accounting": {"reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                           "reservation_applied": reservation_applied,
                           "charge_status_at_report_write": "pending_same_parent_charge",
                           "allow_missing_parent": bound["allow_missing_parent"]},
            "raw_opened": bool(child_result and child_result.get("status", "").startswith("COMPLETE")),
            "hdf5_opened": bool(child_result and child_result.get("status", "").startswith("COMPLETE")),
            "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
            "original_path_fallback": "FORBIDDEN",
        }
        home_bytes = _json_fixed_point(report["filesystem"], key="home_receipt_bytes")
        # _json_fixed_point above operates on the filesystem submapping only;
        # use the actual full report size as the authoritative Home byte count.
        report["filesystem"]["home_receipt_bytes"] = int(home_bytes)
        _write_new(bound["receipt"], report)
        actual_home_bytes = int(bound["receipt"].stat().st_size)
        report["filesystem"]["home_receipt_bytes"] = actual_home_bytes
        # The report is immutable; the fixed point was computed from its
        # submapping, so a changed whole-report size is recorded in the return
        # and charge, while the ledger is the authoritative terminal record.
        charge = _charge(bound, status="completed" if status.startswith("COMPLETED") else "failed",
                         cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                         external_bytes=external_bytes, home_bytes=actual_home_bytes,
                         trace_bytes=trace_bytes, copy_hash_bytes=copy_bytes,
                         allow_missing_parent=bound["allow_missing_parent"])
        return {"schema": REPORT_SCHEMA, "status": status,
                "report_path": str(bound["receipt"]), "request_sha256": sha256_file(request_file),
                "child_returncode": child_returncode, "child_result": child_result,
                "external_bytes": external_bytes, "home_bytes": actual_home_bytes,
                "trace_bytes": trace_bytes, "copy_hash_bytes": copy_bytes,
                "ledger_mutated": bool(charge.get("ledger_mutated")),
                "charge": charge, "model_invoked": False, "cfd_invoked": False,
                "qualification": dict(UNKNOWN)}
    except BaseException as final_error:
        if reservation_applied:
            try:
                _release(bound)
            except BaseException:
                pass
        return {"schema": REPORT_SCHEMA, "status": "FAILED_PARENT_EXECUTOR_FINALIZATION",
                "error": f"{type(final_error).__name__}: {final_error}",
                "report_path": str(bound["receipt"]), "ledger_mutated": False,
                "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--executor-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--external-filesystem", type=Path)
    build.add_argument("--ledger", type=Path)
    build.add_argument("--parent-attempt-id")
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    build.add_argument("--external-bytes", type=int)
    build.add_argument("--home-receipt-bytes", type=int, default=64 * 1024)
    build.add_argument("--home-receipt", type=Path)
    build.add_argument("--supervisor-output-root", type=Path)
    build.add_argument("--home", type=Path, default=Path("/home/jade"))
    build.add_argument("--runtime-v6", type=Path, default=RUNTIME_V6_DEFAULT)
    build.add_argument("--executor-script", type=Path, default=V34_DEFAULT)
    build.add_argument("--disallow-missing-parent", action="store_true")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(
                executor_request=args.executor_request, output=args.output,
                external_filesystem=args.external_filesystem, ledger_path=args.ledger,
                parent_attempt_id=args.parent_attempt_id, max_wall_seconds=args.max_wall_seconds,
                external_bytes=args.external_bytes, home_receipt_bytes=args.home_receipt_bytes,
                home_receipt_path=args.home_receipt, supervisor_output_root=args.supervisor_output_root,
                home_path=args.home, runtime_v6=args.runtime_v6, executor_script=args.executor_script,
                allow_missing_parent=not args.disallow_missing_parent)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"]}, sort_keys=True))
        elif args.command == "preflight":
            bound = _validate_request(args.request, verify_static_content=False)
            value = _preflight_report(Path(str(bound["request"].get("preflight_report", args.request.with_suffix(".preflight.json")))), bound)
            print(json.dumps(value, sort_keys=True))
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved, parent_pid=args.parent_pid)
            print(json.dumps(value, sort_keys=True, default=str))
        return 0
    except (ParentExecutorError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"portable executor parent v1: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
