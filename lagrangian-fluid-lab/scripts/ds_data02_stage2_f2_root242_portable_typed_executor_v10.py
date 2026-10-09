#!/usr/bin/env python3
"""Execute ROOT242 V10 with a dynamic original-path open guard.

V10 is additive to V9.  The parent still owns reservation/charging; this
process copies the sealed roles after that reservation, creates the V2
overlay, and launches the copied V10 runtime worker.  The worker installs an
OS-level Python audit hook before importing the copied V2/V8/V12/scorer
modules, so a hidden original-path open cannot pass a static JSON scan.
"""
from __future__ import annotations

import argparse
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


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V9_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v9.py"
WORKER_NAME = "ds_data02_stage2_f2_root242_root_runtime_worker_v10.py"
REQUEST_SCHEMA = "ds02.request.v1"
OUTER_CONTRACT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v10-dynamic-open-guard-source-binding.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root242-portable-typed-executor-report.v10"
ENV_ROLE = "literal_project_venv_python"
MAX_METADATA_BYTES = 32 * 1024 * 1024


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V9 = _load(V9_SCRIPT, "ds02_root242_v9_executor_for_v10")
V2 = V9.V2


class Root242V10ExecutorError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    return V9._canonical(value)


def _json(path: Path, role: str) -> dict[str, Any]:
    return V9._json(path, role, maximum=MAX_METADATA_BYTES)


def _absolute(value: Any, role: str) -> Path:
    return V9._absolute(value, role)


def _safe_relative(value: Any, role: str) -> str:
    return V9._safe_relative(value, role)


def _hash(path: Path, *, maximum: int = 4 * 1024 * 1024 * 1024,
          allow_symlink: bool = False) -> tuple[str, int]:
    return V9._hash(path, maximum=maximum, allow_symlink=allow_symlink)


def _outer(request_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    request = _json(request_path, "ROOT242 V10 outer request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != _canonical(request):
        raise Root242V10ExecutorError("outer request schema/canonical SHA differs")
    binding = request.get("root242_v10_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != HANDOFF_SCHEMA:
        raise Root242V10ExecutorError("V10 source binding is missing")
    contract_binding = request.get("root213_metadata_contract")
    if not isinstance(contract_binding, Mapping):
        raise Root242V10ExecutorError("outer contract binding is missing")
    contract_path = _absolute(contract_binding.get("path"), "outer contract path")
    contract = _json(contract_path, "ROOT242 V10 outer contract")
    if contract.get("schema") != OUTER_CONTRACT_SCHEMA:
        raise Root242V10ExecutorError("outer contract schema differs")
    if contract.get("sha256") != _canonical(contract):
        raise Root242V10ExecutorError("outer contract canonical SHA differs")
    if contract_binding.get("sha256") != contract.get("sha256"):
        raise Root242V10ExecutorError("outer request does not bind contract canonical SHA")
    source_binding = contract.get("root242_source_binding")
    if not isinstance(source_binding, Mapping) or source_binding.get("schema") != HANDOFF_SCHEMA:
        raise Root242V10ExecutorError("outer contract V10 binding is missing")
    roles = source_binding.get("roles")
    if not isinstance(roles, list) or len(roles) < 40:
        raise Root242V10ExecutorError("outer V10 role table is incomplete")
    digest = hashlib.sha256(json.dumps(
        roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if digest != source_binding.get("selected_roles_sha256") or digest != binding.get("selected_roles_sha256"):
        raise Root242V10ExecutorError("outer V10 role digest differs")
    if request.get("scope", {}).get("original_path_fallback") != "REJECT":
        raise Root242V10ExecutorError("outer request permits source fallback")
    policy = source_binding.get("dynamic_open_policy")
    if not isinstance(policy, Mapping) or policy.get("audit_hook") != "sys.addaudithook":
        raise Root242V10ExecutorError("dynamic open policy is missing")
    return request, contract, contract_path


def _roles(contract: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
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
            raise Root242V10ExecutorError(f"duplicate/missing V10 logical role: {name}")
        if target in targets:
            raise Root242V10ExecutorError(f"duplicate V10 target path: {target}")
        if not isinstance(source, str) or not source.startswith("/"):
            raise Root242V10ExecutorError(f"{name} lacks source provenance")
        if not isinstance(sha, str) or len(sha) != 64:
            raise Root242V10ExecutorError(f"{name} lacks expected SHA")
        by_name[name] = role
        targets.add(target)
    required = {
        "root200_inner_request", "portable_rebind_v2_core", "portable_rebind_v2_entrypoint",
        "typed_only_portable_rebind_v1", "literal_project_venv_python", "pinned_project_pyvenv_cfg",
        "fresh_v16_proof_consumer_v8", "fresh_v16_proof_consumer_v12", "typed_only_evaluator_v1",
        "typed_only_evaluator_v2", "typed_only_evaluator_v3", "v12_semantic_sidecar",
        "frozen_v15_request", "producer_nested_report_v2", "v10_executor", "v10_runtime_worker",
    }
    missing = sorted(required - set(by_name))
    if missing:
        raise Root242V10ExecutorError(f"V10 runtime/source closure is incomplete: {missing}")
    return roles, by_name


def _copy_role(role: Mapping[str, Any], root: Path, *, deadline: float) -> dict[str, Any]:
    try:
        return V9._copy_role(role, root, deadline=deadline)
    except Exception as error:
        raise Root242V10ExecutorError(str(error)) from error


def _policy_roots(roles: Sequence[Mapping[str, Any]], root: Path,
                  literal: Path) -> tuple[list[str], list[str]]:
    allowed: set[str] = {str(root.absolute())}
    literal_abs = Path(os.path.abspath(str(literal)))
    literal_real = Path(os.path.realpath(str(literal)))
    allowed.add(str(literal_abs.parent))
    allowed.add(str(literal_real.parent))
    # The runtime can read standard-library/loader files, but no user data or
    # source checkout.  These roots are explicit policy entries, not a broad
    # "anything outside DATA" exception.
    allowed.update({"/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/dev", "/proc", "/sys"})
    forbidden: set[str] = set()
    for role in roles:
        if role.get("logical_role") == ENV_ROLE:
            continue
        source = Path(str(role["source_path_provenance"])).expanduser()
        forbidden.add(str(source.parent))
        parts = source.parts
        for marker in ("/home", "/tmp", "/var/tmp", "/data"):
            if str(source).startswith(marker + os.sep) or str(source) == marker:
                forbidden.add(marker)
    # The target root is explicitly allowed before these deny roots.  This
    # lets a fresh /tmp target work while blocking old /tmp namespaces.
    forbidden.discard(str(root.absolute()))
    return sorted(allowed), sorted(forbidden)


def _write_policy(root: Path, roles: Sequence[Mapping[str, Any]], literal: Path) -> Path:
    allowed, forbidden = _policy_roots(roles, root, literal)
    path = root / "metadata" / "v10-runtime-open-policy.json"
    if path.exists() or path.is_symlink():
        raise Root242V10ExecutorError(f"refusing existing V10 policy: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema": "ds02.stage2.f2-runtime-open-policy.v1",
        "target_root": str(root.absolute()),
        "allowed_roots": allowed,
        "forbidden_roots": forbidden,
        "events": ["open", "os.chdir"],
        "original_path_fallback": "REJECT",
        "environment_exception": "EXPLICIT_PINNED_PROJECT_VENV_AND_SYSTEM_RUNTIME",
        "source_roles": len(roles),
    }
    value["sha256"] = _canonical(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8")
    return path


def _run_child(*, root: Path, worker: Path, policy: Path, v2_entry: Path,
               overlay: Path, output: Path, literal: Path, parent_pid: int,
               deadline: float) -> tuple[int, dict[str, Any]]:
    stdout = root / "logs" / "v10-runtime-worker.stdout.log"
    stderr = root / "logs" / "v10-runtime-worker.stderr.log"
    for path in (stdout, stderr):
        if path.exists() or path.is_symlink():
            raise Root242V10ExecutorError(f"refusing existing V10 runtime log: {path}")
    if not literal.is_file() or not os.access(literal, os.X_OK):
        raise Root242V10ExecutorError("sealed literal interpreter is unavailable")
    command = [str(literal), "-B", "-I", str(worker), "worker",
               "--root", str(root), "--policy", str(policy),
               "--v2-entrypoint", str(v2_entry), "--overlay", str(overlay),
               "--output", str(output), "--parent-pid", str(os.getpid())]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    child = subprocess.Popen(command, cwd=str(root), env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, close_fds=True)
    try:
        return V9._drain_child(child, deadline=deadline,
                                stdout_path=stdout, stderr_path=stderr)
    except BaseException:
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


def run(*, request: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    if os.getppid() != int(parent_pid):
        raise Root242V10ExecutorError("V10 executor is not directly owned by declared parent")
    _set_pdeathsig = getattr(V9, "_set_pdeathsig")
    _set_pdeathsig()
    started = time.monotonic()
    deadline = started + float(max_wall_seconds)
    request_path = Path(request).expanduser().absolute()
    outer, contract, contract_path = _outer(request_path)
    root = Path(output_root).expanduser().absolute()
    expected_root = _absolute(outer.get("storage_scope", {}).get("external_filesystem"),
                              "outer external filesystem")
    if root != expected_root:
        raise Root242V10ExecutorError("output root differs from parent-bound external filesystem")
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise Root242V10ExecutorError("refusing non-empty or symlink fresh output root")
    root.mkdir(parents=True, exist_ok=True)
    roles, by_name = _roles(contract)
    interpreter_binding = outer.get("interpreter_binding")
    if not isinstance(interpreter_binding, Mapping) or interpreter_binding.get("argv0_literal") is not True or interpreter_binding.get("do_not_resolve_argv0") is not True:
        raise Root242V10ExecutorError("literal interpreter binding is not explicit")
    literal = _absolute(interpreter_binding.get("invocation_path"), "literal interpreter invocation")
    if str(literal) != str(by_name[ENV_ROLE].get("source_path_provenance")):
        raise Root242V10ExecutorError("literal interpreter is not the sealed environment role")
    audits: dict[str, Mapping[str, Any]] = {}
    for role in roles:
        audit = _copy_role(role, root, deadline=deadline)
        audits[str(audit["logical_role"])] = audit
    manifest_path, inner_contract_path = V9._make_inner_manifest(roles, root, audits)
    overlay_path = root / "requests" / "root200-v10-rebound-overlay.json"
    V2.build_request_overlay(contract_path=inner_contract_path,
                             request_role="root200_inner_request", output=overlay_path,
                             request_target_relative="requests/root200-v10-rebased-inner.json",
                             request_id=str(outer.get("attempt_id", "root242-v10")))
    V2.validate_request_overlay(overlay_path)
    output = root / "reports" / "v2-worker-report.json"
    policy = _write_policy(root, roles, literal)
    worker = root / _safe_relative(by_name["v10_runtime_worker"]["target_relative_path"], "V10 worker")
    v2_entry = root / _safe_relative(by_name["portable_rebind_v2_entrypoint"]["target_relative_path"], "V2 entrypoint")
    copied = _target = lambda role: root / _safe_relative(audits[role]["target_relative_path"], role)
    returncode, stream = _run_child(root=root, worker=worker, policy=policy,
                                    v2_entry=v2_entry, overlay=overlay_path,
                                    output=output, literal=literal,
                                    parent_pid=parent_pid, deadline=deadline)
    if stream.get("timed_out"):
        raise Root242V10ExecutorError("V10 copied runtime worker exceeded deadline")
    if returncode != 0:
        error_tail = (root / "logs" / "v10-runtime-worker.stderr.log").read_text(
            encoding="utf-8", errors="replace") if (root / "logs" / "v10-runtime-worker.stderr.log").exists() else ""
        raise Root242V10ExecutorError(f"V10 copied runtime worker failed ({returncode}): {error_tail[-3000:]}")
    child_report = _json(output, "V10 copied V2 report")
    if child_report.get("status") != "PASS_RELOCATED_V8_V12_TYPED_SCORER":
        raise Root242V10ExecutorError("copied V2 report did not pass V8/V12/scorer")
    open_audit = child_report.get("runtime_open_audit")
    if not isinstance(open_audit, Mapping) or open_audit.get("hook_installed") is not True:
        raise Root242V10ExecutorError("copied worker did not return dynamic open-audit evidence")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_RELOCATED_V10_DYNAMIC_OPEN_GUARD_V8_V12_TYPED_SCORER",
        "request": {"path": str(request_path), "file_sha256": _hash(request_path)[0],
                    "canonical_sha256": outer["sha256"]},
        "contract": {"path": str(contract_path), "canonical_sha256": contract["sha256"]},
        "attempt_id": outer.get("attempt_id"), "case_id": outer.get("case_id"),
        "parent_pid": int(parent_pid),
        "copy_audits": audits, "role_count": len(audits),
        "copy_bytes": sum(int(item["bytes"]) for item in audits.values()),
        "manifest": {"path": str(manifest_path.relative_to(root)), "sha256": _hash(manifest_path)[0]},
        "inner_contract": {"path": str(inner_contract_path.relative_to(root)), "sha256": _hash(inner_contract_path)[0]},
        "overlay": {"path": str(overlay_path.relative_to(root)), "sha256": _hash(overlay_path)[0]},
        "runtime_open_policy": {"path": str(policy.relative_to(root)), "sha256": _hash(policy)[0],
                                "source_fallback": "REJECT", "environment_exception": "EXPLICIT_PINNED_PROJECT_VENV_AND_SYSTEM_RUNTIME"},
        "child_report": {"path": str(output.relative_to(root)), "sha256": _hash(output)[0]},
        "child_runtime_open_audit": dict(open_audit),
        "child_stream_accounting": stream, "child_returncode": returncode,
        "execution": {
            "source_copy_after_parent_reservation": True,
            "source_posthash_and_stat": True,
            "dynamic_os_open_guard": True,
            "v8_validator": True, "v12_validator": True, "typed_scorer": True,
            "model_invoked": False, "cfd_invoked": False,
            "raw_opened": False, "hdf5_or_bi4_content_read": False,
            "original_path_fallback": "REJECT", "parent_death_signal": "SIGTERM",
            "bounded_wall_seconds": float(max_wall_seconds),
            "elapsed_wall_seconds": time.monotonic() - started,
        },
        "source_fallback": "REJECT", "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    report["sha256"] = _canonical(report)
    report_path = root / "reports" / "root242-v10-executor-report.json"
    if report_path.exists() or report_path.is_symlink():
        raise Root242V10ExecutorError("refusing existing V10 report")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def validate_request(request: Path | str, contract: Path | str) -> dict[str, Any]:
    builder = _load(SCRIPT_DIR / "ds_data02_stage2_f2_root242_v10_source_request.py",
                    "ds02_root242_v10_builder_runtime")
    return builder.validate_request(request=request, contract=contract)


def _set_pdeathsig() -> None:
    try:
        libc = ctypes.CDLL(None)
        if int(libc.prctl(1, signal.SIGTERM, 0, 0, 0)) != 0:
            raise OSError("prctl failed")
    except (AttributeError, OSError) as error:
        raise Root242V10ExecutorError(f"parent-death signal unavailable: {error}") from error


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
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V10ExecutorError, V9.V1.PortableRebindError,
            V2.PortableRebindV2Error, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"ROOT242 V10 executor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
