#!/usr/bin/env python3
"""Run the ROOT242 selected typed-only bundle under one outer guard.

V8 deliberately stopped at a source table and a rejected V7 sparse executor.
This additive entry point is the first executable handoff for that table.  It
copies exactly the roles sealed by the outer request after the parent has
reserved storage, creates a V1/V2 target-relative overlay, and invokes the
copied V5/V2 worker.  The worker reads only the relocated JSON result and
small contracts; raw, BI4, native, HDF5, model, and CFD inputs are outside
this consumer.

The outer parent owns resource-ledger reservation and terminal charging.  This
process owns only its child process group and writes bounded reports/log tails;
it never creates or mutates a ledger.  The project virtualenv is an explicit
sealed environment dependency: its literal invocation path is declared by the
outer request, while the copied executable is checked as a regular target.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V1_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "ds02_root242_v9_v1")
V2 = _load(V2_SCRIPT, "ds02_root242_v9_v2")

REQUEST_SCHEMA = "ds02.request.v1"
OUTER_CONTRACT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v9-single-case-source-binding.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root242-portable-typed-executor-report.v9"
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
ROLLING_TAIL_BYTES = 64 * 1024
MAX_ROLE_BYTES = 4 * 1024 * 1024 * 1024
ENV_ROLE = "literal_project_venv_python"


class Root242V9ExecutorError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root242V9ExecutorError(f"{role} must be absolute")
    return Path(value).expanduser()


def _safe_relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise Root242V9ExecutorError(f"{role} target path is missing")
    relative = Path(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise Root242V9ExecutorError(f"{role} target path is not safely relative: {value}")
    return relative.as_posix()


def _json(path: Path, role: str, maximum: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Root242V9ExecutorError(f"{role} is not a regular non-symlink file: {path}")
    if path.stat().st_size > maximum:
        raise Root242V9ExecutorError(f"{role} exceeds bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root242V9ExecutorError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Root242V9ExecutorError(f"{role} must be a JSON object")
    return value


def _stat(path: Path, *, follow: bool = False) -> dict[str, int]:
    if path.is_symlink() and not follow:
        raise Root242V9ExecutorError(f"unexpected source symlink: {path}")
    value = path.stat() if follow else path.lstat()
    if not path.is_file():
        raise Root242V9ExecutorError(f"source is not a regular file: {path}")
    return {
        "bytes": int(value.st_size),
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _hash(path: Path, *, maximum: int = MAX_ROLE_BYTES,
          allow_symlink: bool = False) -> tuple[str, int]:
    if (path.is_symlink() and not allow_symlink) or not path.is_file():
        raise Root242V9ExecutorError(f"hash target is not a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > maximum:
                raise Root242V9ExecutorError(f"file exceeds bounded role size: {path}")
            digest.update(block)
    return digest.hexdigest(), total


def _reject_symlink_components(path: Path, root: Path) -> None:
    if root.is_symlink():
        raise Root242V9ExecutorError(f"target root is a symlink: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise Root242V9ExecutorError(f"target escapes relocated root: {path}") from error
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise Root242V9ExecutorError(f"target contains a symlink component: {current}")


def _target(root: Path, relative: Any, *, required: bool = False) -> Path:
    target = root / _safe_relative(relative, "target")
    _reject_symlink_components(target, root)
    if required and (not target.is_file() or target.is_symlink()):
        raise Root242V9ExecutorError(f"required target is missing: {target}")
    return target


def _set_pdeathsig() -> None:
    try:
        libc = ctypes.CDLL(None)
        if int(libc.prctl(1, signal.SIGTERM, 0, 0, 0)) != 0:
            raise OSError("prctl(PR_SET_PDEATHSIG) failed")
    except (AttributeError, OSError) as error:
        raise Root242V9ExecutorError(f"parent-death signal unavailable: {error}") from error


def _outer(request_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    request = _json(request_path, "ROOT242 V9 outer request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != _canonical(request):
        raise Root242V9ExecutorError("outer request schema/canonical SHA differs")
    binding = request.get("root242_v9_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != HANDOFF_SCHEMA:
        raise Root242V9ExecutorError("V9 source binding is missing")
    contract_binding = request.get("root213_metadata_contract")
    if not isinstance(contract_binding, Mapping):
        raise Root242V9ExecutorError("outer contract binding is missing")
    contract_path = _absolute(contract_binding.get("path"), "outer contract path")
    contract = _json(contract_path, "ROOT242 V9 outer contract")
    if contract.get("schema") != OUTER_CONTRACT_SCHEMA:
        raise Root242V9ExecutorError("outer contract schema differs")
    if contract.get("sha256") != _canonical(contract):
        raise Root242V9ExecutorError("outer contract canonical SHA differs")
    if contract_binding.get("sha256") != contract.get("sha256"):
        raise Root242V9ExecutorError("outer request does not bind contract canonical SHA")
    source_binding = contract.get("root242_source_binding")
    if not isinstance(source_binding, Mapping) or source_binding.get("schema") != HANDOFF_SCHEMA:
        raise Root242V9ExecutorError("outer contract V9 binding is missing")
    roles = source_binding.get("roles")
    if not isinstance(roles, list) or len(roles) < 40:
        raise Root242V9ExecutorError("outer V9 role table is incomplete")
    digest = hashlib.sha256(json.dumps(
        roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if digest != source_binding.get("selected_roles_sha256") or digest != binding.get("selected_roles_sha256"):
        raise Root242V9ExecutorError("outer V9 role digest differs")
    if request.get("scope", {}).get("original_path_fallback") != "REJECT":
        raise Root242V9ExecutorError("outer request permits source fallback")
    return request, contract, contract_path


def _role_table(contract: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    binding = contract["root242_source_binding"]
    roles = [item for item in binding["roles"] if isinstance(item, Mapping)]
    by_name: dict[str, Mapping[str, Any]] = {}
    targets: set[str] = set()
    for role in roles:
        name = role.get("logical_role")
        target = _safe_relative(role.get("target_relative_path"), f"{name}.target")
        source = role.get("source_path_provenance")
        sha = role.get("source_sha256")
        if not isinstance(name, str) or not name or name in by_name:
            raise Root242V9ExecutorError(f"duplicate/missing V9 logical role: {name}")
        if target in targets:
            raise Root242V9ExecutorError(f"duplicate V9 target path: {target}")
        if not isinstance(source, str) or not source.startswith("/"):
            raise Root242V9ExecutorError(f"{name} lacks absolute source provenance")
        if not isinstance(sha, str) or len(sha) != 64:
            raise Root242V9ExecutorError(f"{name} lacks expected SHA")
        by_name[name] = role
        targets.add(target)
    required = {
        "root200_inner_request", "portable_rebind_v2_core", "portable_rebind_v2_entrypoint",
        "typed_only_portable_rebind_v1", "literal_project_venv_python", "pinned_project_pyvenv_cfg",
        "fresh_v16_proof_consumer_v8", "fresh_v16_proof_consumer_v12", "typed_only_evaluator_v1",
        "typed_only_evaluator_v2", "typed_only_evaluator_v3", "v12_semantic_sidecar",
        "frozen_v15_request", "producer_nested_report_v2", "v9_executor",
    }
    missing = sorted(required - set(by_name))
    if missing:
        raise Root242V9ExecutorError(f"V9 runtime/source closure is incomplete: {missing}")
    return roles, by_name


def _expected_stat(role: Mapping[str, Any]) -> Mapping[str, Any]:
    value = role.get("source_stat_provenance")
    if not isinstance(value, Mapping) or "bytes" not in value or "mode_bits" not in value:
        raise Root242V9ExecutorError(f"role lacks source stat: {role.get('logical_role')}")
    return value


def _copy_role(role: Mapping[str, Any], root: Path, *, deadline: float) -> dict[str, Any]:
    name = str(role["logical_role"])
    source = _absolute(role["source_path_provenance"], f"{name}.source")
    env_role = name == ENV_ROLE
    if source.is_symlink() and not env_role:
        raise Root242V9ExecutorError(f"scientific/runtime source is a symlink: {name}")
    if source.is_symlink() and env_role:
        source_stat = _stat(source, follow=True)
    else:
        source_stat = _stat(source)
    expected = _expected_stat(role)
    if source_stat["bytes"] != int(expected["bytes"]):
        raise Root242V9ExecutorError(f"source byte stat differs before copy: {name}")
    if source_stat["mode_bits"] != int(expected["mode_bits"]):
        raise Root242V9ExecutorError(f"source mode stat differs before copy: {name}")
    if source_stat["bytes"] > MAX_ROLE_BYTES:
        raise Root242V9ExecutorError(f"source role exceeds role size budget: {name}")
    target = _target(root, role["target_relative_path"])
    if target.exists() or target.is_symlink():
        raise Root242V9ExecutorError(f"refusing existing copied role: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as in_stream, target.open("xb") as out_stream:
        while True:
            if time.monotonic() >= deadline:
                raise Root242V9ExecutorError(f"copy deadline exceeded at {name}")
            block = in_stream.read(4 * 1024 * 1024)
            if not block:
                break
            copied += len(block)
            if copied > MAX_ROLE_BYTES:
                raise Root242V9ExecutorError(f"copy role exceeds role size budget: {name}")
            digest.update(block)
            out_stream.write(block)
    os.chmod(target, source_stat["mode_bits"])
    copied_sha = digest.hexdigest()
    if copied != int(expected["bytes"]) or copied_sha != str(role["source_sha256"]):
        raise Root242V9ExecutorError(f"copied role SHA/bytes differ: {name}")
    target_stat = _stat(target)
    # A second source digest closes the source-side post-copy content check.
    source_post_stat = _stat(source, follow=env_role)
    source_post_sha, source_post_bytes = _hash(source, allow_symlink=env_role)
    if source_post_bytes != copied or source_post_sha != copied_sha:
        raise Root242V9ExecutorError(f"source changed during copy: {name}")
    if source_post_stat["bytes"] != source_stat["bytes"] or source_post_stat["mode_bits"] != source_stat["mode_bits"]:
        raise Root242V9ExecutorError(f"source stat changed during copy: {name}")
    if target_stat["bytes"] != copied or target_stat["mode_bits"] != source_stat["mode_bits"]:
        raise Root242V9ExecutorError(f"target stat differs after copy: {name}")
    return {
        "logical_role": name, "source_path": str(source),
        "target_relative_path": str(target.relative_to(root)),
        "source_pre_stat": source_stat, "source_post_stat": source_post_stat,
        "target_stat": target_stat, "source_sha256": source_post_sha,
        "target_sha256": _hash(target)[0], "bytes": copied,
        "deferred_content": bool(role.get("deferred_content")),
        "source_is_environment_exception": env_role,
        "inode_distinct": (source_stat["st_dev"], source_stat["st_ino"]) !=
                           (target_stat["st_dev"], target_stat["st_ino"]),
        "content_phase": "AFTER_PARENT_RESERVATION",
    }


def _make_inner_manifest(roles: Sequence[Mapping[str, Any]], root: Path,
                         copied: Mapping[str, Mapping[str, Any]]) -> tuple[Path, Path]:
    artifacts: list[dict[str, Any]] = []
    for role in roles:
        name = str(role["logical_role"])
        copied_info = copied[name]
        deferred = bool(role.get("deferred_content"))
        artifacts.append({
            "logical_role": name,
            "source_kind": "deferred_json" if deferred else "relocated_v9_source",
            "actionable": True, "content_read_by_manifest": not deferred,
            "source_sha256": str(role["source_sha256"]),
            "source_sha256_basis": "OUTER_V9_DECLARED_AFTER_RESERVATION_COPY",
            "source_stat_provenance": dict(role.get("source_stat_provenance") or {}),
            "source_path_provenance": str(role["source_path_provenance"]),
            "target_relative_path": copied_info["target_relative_path"],
        })
    by_name = {item["logical_role"]: item for item in artifacts}
    def target(name: str) -> str:
        return str(by_name[name]["target_relative_path"])
    loading = {
        "entrypoint_logical_role": "portable_rebind_v2_entrypoint",
        "entrypoint_target_relative_path": target("portable_rebind_v2_entrypoint"),
        "request_target_relative_path": target("root200_inner_request"),
        "frozen_v15_target_relative_path": target("frozen_v15_request"),
        "current_target_relative_path": target("current336_actionable_metadata"),
        "result_target_relative_path": target("root179c_v16_result_deferred"),
        "typed_h5_target_relative_path": target("closure_271d0ebcb1b99437"),
        "fresh_proof_target_relative_path": target("root200_fresh_v12_proof"),
        "operator_report_target_relative_path": target("producer_nested_report_v2"),
        "runtime_sibling_directory": "runtime",
        "argv0_policy": "COPIED_VENV_ENVIRONMENT_EXCEPTION",
        "source_fallback": "REJECT", "no_model": True,
        "model_invoked": False,
    }
    manifest: dict[str, Any] = {
        "schema": V1.MANIFEST_SCHEMA,
        "status": "PENDING_PARENT_RELOCATION_TARGETS",
        "manifest_id": "root242-v9-inner-copy-manifest",
        "relocated_root": str(root), "artifacts": artifacts,
        "portable_loading_entry": loading,
        "source_fallback": "REJECT", "metadata_only": False,
        "payload_read": False,
    }
    manifest["sha256"] = V1._canonical(manifest)
    manifest_path = root / "metadata" / "v9-inner-copy-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise Root242V9ExecutorError(f"refusing existing inner manifest: {manifest_path}")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True,
                                        ensure_ascii=True, allow_nan=False) + "\n",
                             encoding="utf-8")
    contract_path = root / "metadata" / "v9-inner-rebind-contract.json"
    contract = V1.build_contract(manifest_path=manifest_path, relocated_root=root,
                                 output=contract_path, contract_id="root242-v9-inner")
    return manifest_path, contract_path


def _drain_child(child: subprocess.Popen[bytes], *, deadline: float,
                 stdout_path: Path, stderr_path: Path) -> tuple[int, dict[str, Any]]:
    """Selector drain with bounded rolling tails and owned-group cleanup."""
    selector = selectors.DefaultSelector()
    live: dict[int, tuple[Any, bytearray, int, Path]] = {}
    closed: list[tuple[bytearray, int, Path]] = []
    for stream, path in ((child.stdout, stdout_path), (child.stderr, stderr_path)):
        if stream is not None:
            selector.register(stream, selectors.EVENT_READ)
            live[stream.fileno()] = (stream, bytearray(), 0, path)
    timed_out = False
    while live:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        events = selector.select(min(0.2, remaining))
        for key, _ in events:
            stream = key.fileobj
            fd = stream.fileno()
            current, tail, total, path = live[fd]
            chunk = stream.read1(64 * 1024) if hasattr(stream, "read1") else stream.read(64 * 1024)
            if not chunk:
                try:
                    selector.unregister(stream)
                except Exception:
                    pass
                stream.close()
                closed.append((tail, total, path))
                del live[fd]
                continue
            total += len(chunk)
            tail.extend(chunk)
            if len(tail) > ROLLING_TAIL_BYTES:
                del tail[:-ROLLING_TAIL_BYTES]
            live[fd] = (stream, tail, total, path)
    if timed_out or child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5.0)
    for fd, (stream, tail, total, path) in list(live.items()):
        try:
            selector.unregister(stream)
        except Exception:
            pass
        stream.close()
        closed.append((tail, total, path))
    selector.close()
    info: dict[str, Any] = {"timed_out": timed_out, "rolling_tail_bytes": ROLLING_TAIL_BYTES,
                             "stdout_bytes": 0, "stderr_bytes": 0,
                             "stdout_tail_bytes": 0, "stderr_tail_bytes": 0}
    for tail, total, path in closed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(tail))
        key = "stdout" if path == stdout_path else "stderr"
        info[f"{key}_bytes"] = int(total)
        info[f"{key}_tail_bytes"] = int(len(tail))
    return child.returncode if child.returncode is not None else 1, info


def _run_child(*, root: Path, overlay: Path, output: Path,
               runtime: Mapping[str, Mapping[str, Any]], literal_python: Path,
               parent_pid: int, deadline: float) -> tuple[int, dict[str, Any]]:
    entry = _target(root, runtime["portable_rebind_v2_entrypoint"]["target_relative_path"], required=True)
    stdout = root / "logs" / "v2-worker.stdout.log"
    stderr = root / "logs" / "v2-worker.stderr.log"
    for path in (stdout, stderr):
        _reject_symlink_components(path, root)
        if path.exists() or path.is_symlink():
            raise Root242V9ExecutorError(f"refusing existing worker log: {path}")
    # The project virtualenv is the one explicitly allowed environment
    # exception.  Its literal argv0 may be a symlink; resolving it here would
    # silently select the system ABI and reproduce the earlier NumPy/h5py
    # mismatch.  The copied regular target was already SHA/stat checked by
    # _copy_role; execution deliberately uses the sealed literal invocation
    # path supplied by the parent request.
    if not literal_python.is_file() or not os.access(literal_python, os.X_OK):
        raise Root242V9ExecutorError("sealed literal project interpreter is unavailable")
    command = [str(literal_python), "-B", "-I", str(entry), "worker",
               "--request", str(overlay), "--output", str(output),
               "--parent-pid", str(os.getpid())]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    child = subprocess.Popen(command, cwd=str(root), env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, close_fds=True)
    old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    def cancel(signum: int, _frame: Any) -> None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise Root242V9ExecutorError(f"V9 child cancelled by signal {signum}")
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        result = _drain_child(child, deadline=deadline, stdout_path=stdout, stderr_path=stderr)
    except BaseException:
        # A signal can interrupt selector.select before _drain_child reaches
        # its normal deadline cleanup.  The handler has sent TERM, but the
        # leader may have exited while a descendant still owns a pipe; finish
        # the owned process-group cleanup here and never leave that group
        # behind for a later attempt.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
        raise
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    return result


def run(*, request: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise Root242V9ExecutorError("V9 executor is not directly owned by declared parent")
    _set_pdeathsig()
    started = time.monotonic()
    deadline = started + float(max_wall_seconds)
    request_path = Path(request).expanduser()
    outer, contract, contract_path = _outer(request_path)
    root = Path(output_root).expanduser()
    expected_root = _absolute(outer.get("storage_scope", {}).get("external_filesystem"),
                              "outer external filesystem")
    if root != expected_root:
        raise Root242V9ExecutorError("output root differs from parent-bound external filesystem")
    if root.exists() and root.is_symlink():
        raise Root242V9ExecutorError("output root is a symlink")
    if root.exists() and any(root.iterdir()):
        raise Root242V9ExecutorError("refusing non-empty fresh output root")
    root.mkdir(parents=True, exist_ok=True)
    roles, by_name = _role_table(contract)
    interpreter_binding = outer.get("interpreter_binding")
    if not isinstance(interpreter_binding, Mapping) or interpreter_binding.get("argv0_literal") is not True or interpreter_binding.get("do_not_resolve_argv0") is not True:
        raise Root242V9ExecutorError("literal interpreter binding is not explicit")
    literal_invocation = _absolute(interpreter_binding.get("invocation_path"),
                                   "literal interpreter invocation")
    if str(literal_invocation) != str(by_name[ENV_ROLE].get("source_path_provenance")):
        raise Root242V9ExecutorError("literal interpreter invocation is not the sealed environment role")
    if literal_invocation.is_file() is False:
        raise Root242V9ExecutorError("literal interpreter invocation is unavailable")
    copied: dict[str, Mapping[str, Any]] = {}
    audits: dict[str, Mapping[str, Any]] = {}
    for role in roles:
        audit = _copy_role(role, root, deadline=deadline)
        audits[audit["logical_role"]] = audit
        copied[audit["logical_role"]] = role
    manifest_path, inner_contract_path = _make_inner_manifest(roles, root, audits)
    overlay_path = root / "requests" / "root200-v9-rebound-overlay.json"
    V2.build_request_overlay(contract_path=inner_contract_path,
                             request_role="root200_inner_request",
                             output=overlay_path,
                             request_target_relative="requests/root200-v9-rebased-inner.json",
                             request_id=str(outer.get("attempt_id", "root242-v9")))
    V2.validate_request_overlay(overlay_path)
    child_output = root / "reports" / "v2-worker-report.json"
    copied_python = _target(root, by_name[ENV_ROLE]["target_relative_path"], required=True)
    runtime_bindings = {}
    for name in ("portable_rebind_v2_entrypoint", "fresh_v16_proof_consumer_v8",
                 "fresh_v16_proof_consumer_v12", "typed_only_evaluator_v1",
                 "typed_only_evaluator_v2", "typed_only_evaluator_v3", "replay_v14",
                 "replay_v15", "frozen_v15_request", "v12_semantic_sidecar",
                 "producer_nested_report_v2", "literal_project_venv_python", "pinned_project_pyvenv_cfg"):
        runtime_bindings[name] = {"logical_role": name,
                                  "target_relative_path": audits[name]["target_relative_path"],
                                  "source_sha256": audits[name]["source_sha256"]}
    returncode, stream = _run_child(root=root, overlay=overlay_path, output=child_output,
                                     runtime=runtime_bindings, literal_python=literal_invocation,
                                     parent_pid=parent_pid, deadline=deadline)
    if stream["timed_out"]:
        raise Root242V9ExecutorError("V9 copied V2 worker exceeded bounded deadline")
    if returncode != 0:
        stderr_tail = (root / "logs" / "v2-worker.stderr.log").read_text(
            encoding="utf-8", errors="replace") if (root / "logs" / "v2-worker.stderr.log").exists() else ""
        raise Root242V9ExecutorError(f"V9 copied V2 worker failed ({returncode}): {stderr_tail[-2000:]}")
    child_report = _json(child_output, "V2 worker report")
    if child_report.get("status") != "PASS_RELOCATED_V8_V12_TYPED_SCORER":
        raise Root242V9ExecutorError("copied V2 worker did not produce a successful semantic report")
    report = {
        "schema": REPORT_SCHEMA, "status": "COMPLETE_RELOCATED_V9_V8_V12_TYPED_SCORER",
        "request": {"path": str(request_path), "file_sha256": _hash(request_path)[0],
                    "canonical_sha256": outer["sha256"]},
        "contract": {"path": str(contract_path), "canonical_sha256": contract["sha256"]},
        "attempt_id": outer.get("attempt_id"), "case_id": outer.get("case_id"),
        "parent_pid": int(parent_pid),
        "copy_audits": audits, "role_count": len(audits),
        "copy_bytes": sum(int(item["bytes"]) for item in audits.values()),
        "deferred_roles": [name for name, item in audits.items() if item["deferred_content"]],
        "manifest": {"path": str(manifest_path.relative_to(root)), "sha256": _hash(manifest_path)[0]},
        "inner_contract": {"path": str(inner_contract_path.relative_to(root)), "sha256": _hash(inner_contract_path)[0]},
        "overlay": {"path": str(overlay_path.relative_to(root)), "sha256": _hash(overlay_path)[0]},
        "child_report": {"path": str(child_output.relative_to(root)), "sha256": _hash(child_output)[0]},
        "child_stream_accounting": stream, "child_returncode": returncode,
        "interpreter": {"literal_invocation_path": str(literal_invocation),
                         "copied_target_relative_path": audits[ENV_ROLE]["target_relative_path"],
                         "copied_target_sha256": audits[ENV_ROLE]["target_sha256"],
                         "policy": "EXPLICIT_PINNED_PROJECT_VENV_ENVIRONMENT_EXCEPTION"},
        "execution": {"source_copy_after_parent_reservation": True,
                       "source_posthash_and_stat": True, "v8_validator": True,
                       "v12_validator": True, "typed_scorer": True,
                       "model_invoked": False, "cfd_invoked": False,
                       "raw_opened": False, "hdf5_or_bi4_content_read": False,
                       "original_path_fallback": "REJECT", "parent_death_signal": "SIGTERM",
                       "bounded_wall_seconds": float(max_wall_seconds),
                       "elapsed_wall_seconds": time.monotonic() - started},
        "source_fallback": "REJECT", "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    report["sha256"] = _canonical(report)
    report_path = root / "reports" / "root242-v9-executor-report.json"
    if report_path.exists() or report_path.is_symlink():
        raise Root242V9ExecutorError(f"refusing existing V9 report: {report_path}")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def validate_request(request: Path | str, contract: Path | str) -> dict[str, Any]:
    # Keep the source builder as the single metadata validator; importing it
    # here avoids a second, subtly different interpretation of the V9 role
    # digest.  This command remains payload-free.
    builder_path = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v9_source_request.py"
    builder = _load(builder_path, "ds02_root242_v9_builder_runtime")
    try:
        return builder.validate_request(request=Path(request).expanduser().absolute(),
                                        contract=Path(contract).expanduser().absolute())
    except Exception as error:
        raise Root242V9ExecutorError(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--contract", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            value = validate_request(args.request, args.contract)
        else:
            value = run(request=args.request, output_root=args.output_root,
                        parent_pid=args.parent_pid,
                        max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V9ExecutorError, V1.PortableRebindError, V2.PortableRebindV2Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V9 executor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
