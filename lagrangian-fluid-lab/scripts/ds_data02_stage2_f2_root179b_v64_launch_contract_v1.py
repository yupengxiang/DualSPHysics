#!/usr/bin/env python3
"""Source-only launch and terminal contract for the ROOT179B V64 request.

This adapter does not reserve a ledger, copy a source, open a BI4/HDF5/raw
payload, or start V64.  It loads the V64 implementation from the request's
bound worktree and runs its existing ``_validate_request(..., verify_static=
False)`` preflight, then checks the direct literal-venv entry command and the
same-parent two-filesystem accounting fields.  The returned plan gives the
primary supervisor the exact command and the post-terminal V64 delta-adapter
arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-root179b-v64-launch-contract.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
ROOT179B_FILE_SHA = "d83e5aaabdf9a8863a10abf654995ea868364ca1d0f171f9b2e676241cf73570"
ROOT179B_CANONICAL_SHA = "ccddfb549a33eab8178a5f1c859e1dea7938008a300d8c784396586816d7129f"
PINNED_VENV = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
RESOLVED_SYSTEM_PYTHON = "/usr/bin/python3.10"
V64_NAME = "ds_data02_stage2_f2_portable_executor_v64.py"
ADAPTER_NAME = "ds_data02_stage2_f2_v64_terminal_cpu_delta_adapter_v3.py"


class LaunchContractError(ValueError):
    pass


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise LaunchContractError(f"{role} must be a lowercase SHA-256")
    return value


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    total = 0
    with target.open("rb") as stream:
        while True:
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise LaunchContractError(f"{target} exceeds metadata bound")
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")).hexdigest()


def _json(path: Path | str, role: str, *, max_bytes: int = 8 * 1024 * 1024) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise LaunchContractError(f"{role} must be a regular file: {target}")
    if target.stat().st_size > max_bytes:
        raise LaunchContractError(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LaunchContractError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise LaunchContractError(f"{role} must contain an object")
    return target, value


def _under(path: Path | str, root: Path | str) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except ValueError:
        return False


def _load_bound_v64(request: Mapping[str, Any]) -> tuple[Any, Path]:
    worktree = request.get("worktree_root")
    if not isinstance(worktree, str) or not Path(worktree).is_absolute():
        raise LaunchContractError("worktree_root is required for the bound V64 implementation")
    script = Path(worktree).expanduser().resolve() / "lagrangian-fluid-lab" / "scripts" / V64_NAME
    if script.is_symlink() or not script.is_file():
        raise LaunchContractError(f"bound V64 implementation is missing: {script}")
    spec = importlib.util.spec_from_file_location("ds02_bound_root179b_v64", script)
    if spec is None or spec.loader is None:
        raise LaunchContractError(f"cannot load bound V64 implementation: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, script


def _static_role(request: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    values = [item for item in request.get("static_bindings", [])
              if isinstance(item, Mapping) and item.get("role") == role]
    if len(values) != 1:
        raise LaunchContractError(f"static binding role {role} must occur exactly once")
    return values[0]


def inspect_request(request_path: Path | str, *, expected_file_sha: str | None = None,
                    expected_canonical_sha: str | None = None) -> dict[str, Any]:
    request_file, request = _json(request_path, "ROOT179B V64 request")
    file_sha = sha256_file(request_file, max_bytes=8 * 1024 * 1024)
    canonical = request.get("sha256")
    if request.get("schema") != REQUEST_SCHEMA:
        raise LaunchContractError("request schema is not V64")
    if canonical != canonical_sha(request):
        raise LaunchContractError("request canonical SHA differs")
    if expected_file_sha is not None and file_sha != expected_file_sha:
        raise LaunchContractError("request file SHA differs from the expected candidate")
    if expected_canonical_sha is not None and canonical != expected_canonical_sha:
        raise LaunchContractError("request canonical SHA differs from the expected candidate")

    bound_v64, v64_script = _load_bound_v64(request)
    # This is the real V64 source preflight.  verify_static=False avoids
    # content hashing, while the V64 validator still checks the exact request
    # schema, source paths/stat contracts, and resource/accounting fields.
    try:
        bound = bound_v64._validate_request(request_file, verify_static=False)
    except Exception as error:
        raise LaunchContractError(f"bound V64 metadata preflight rejected request: {error}") from error

    execution = request.get("execution")
    storage = request.get("storage_scope")
    parent = request.get("parent_resource_binding")
    runtime = request.get("runtime")
    python = request.get("python_binding")
    if not all(isinstance(item, Mapping) for item in (execution, storage, parent, runtime, python)):
        raise LaunchContractError("V64 execution/storage/parent/runtime/python bindings are incomplete")
    attempt = request.get("attempt_id")
    if not isinstance(attempt, str) or not attempt:
        raise LaunchContractError("attempt_id is missing")
    if parent.get("attempt_id") != attempt:
        raise LaunchContractError("parent attempt differs from request attempt")
    if parent.get("reservation_id") != attempt + "::reservation":
        raise LaunchContractError("reservation ID is not the request-scoped parent reservation")
    if parent.get("charge_id") != attempt + "::charge":
        raise LaunchContractError("charge ID is not the request-scoped parent charge")
    if parent.get("same_parent_ledger") is not True or parent.get("ledger_reset") is not False:
        raise LaunchContractError("request is not bound to the same parent ledger")
    if parent.get("storage_policy") != "home_free_floor" or parent.get("allow_missing_parent") is not True:
        raise LaunchContractError("parent storage/allow-missing policy differs from the authorized V64 scope")

    command = execution.get("command")
    if not isinstance(command, list) or not command:
        raise LaunchContractError("V64 child command is missing")
    command = [str(item) for item in command]
    if command[0] != PINNED_VENV or command[0] == RESOLVED_SYSTEM_PYTHON:
        raise LaunchContractError("child command must preserve literal venv argv[0]")
    if "-I" not in command or "--io-slot-approved" not in command or "--run-labels" not in command:
        raise LaunchContractError("child command lacks isolated bootstrap/io-slot/label flags")
    runtime_root = Path(str(runtime.get("canonical_sibling_root"))).expanduser().resolve()
    bootstrap = Path(str(runtime.get("bootstrap_target"))).expanduser().resolve()
    worker = Path(str(runtime.get("worker_target"))).expanduser().resolve()
    if command[command.index("--runtime-root") + 1] != str(runtime_root):
        raise LaunchContractError("child --runtime-root differs from runtime contract")
    if command[command.index("--worker") + 1] != str(worker):
        raise LaunchContractError("child --worker differs from runtime contract")
    if str(bootstrap) not in command:
        raise LaunchContractError("child command does not invoke the bound bootstrap")
    request_arg = command[command.index("--request") + 1]
    output_arg = command[command.index("--output-dir") + 1]
    if request_arg != str(runtime.get("worker_request_target")):
        raise LaunchContractError("child request path differs from worker_request_target")
    if output_arg != str(storage.get("external_output_root")):
        raise LaunchContractError("child output path differs from external_output_root")
    if any(marker in " ".join(command) for marker in ("ROOT060", "root060", "candidate-001")):
        raise LaunchContractError("stale actionable namespace remains in child command")

    if float(execution.get("max_wall_seconds", 0)) != 6000.0:
        raise LaunchContractError("V64 child max wall must be 6000 seconds")
    if int(execution.get("memory_max_bytes", 0)) != 16 * 1024**3:
        raise LaunchContractError("V64 child memory cap must be 16 GiB")
    if int(storage.get("external_reservation_bytes", 0)) != 12 * 1024**3:
        raise LaunchContractError("V64 external reservation must be 12 GiB")
    if int(storage.get("external_min_free_bytes", 0)) != 20 * 1024**3:
        raise LaunchContractError("V64 external free-floor must be 20 GiB")
    if int(storage.get("home_min_free_bytes", 0)) != 500 * 1024**3:
        raise LaunchContractError("V64 Home floor must be 500 GiB")
    if int(storage.get("home_receipt_bytes", 0)) < 1024**2:
        raise LaunchContractError("V64 Home receipt allowance must be at least 1 MiB")
    if int(storage.get("source_copy_bytes", -1)) != 0 or storage.get("two_filesystem_charge_required") is not True:
        raise LaunchContractError("V64 source-copy/two-filesystem accounting differs")
    if float(execution.get("child_cleanup_grace_seconds", 0)) < 25.0:
        raise LaunchContractError("V64 child cleanup grace is shorter than 25 seconds")
    if execution.get("parent_death_signal") != "PR_SET_PDEATHSIG=SIGTERM":
        raise LaunchContractError("V64 parent-death signal is not bound")
    if execution.get("process_group") != "owned child PGID; TERM grace then KILL":
        raise LaunchContractError("V64 owned process-group cleanup is not bound")
    env = execution.get("env")
    if not isinstance(env, Mapping) or any(str(env.get(key)) != "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")):
        raise LaunchContractError("V64 single-thread environment is incomplete")
    if python.get("argv_path") != PINNED_VENV or python.get("resolved_path") != RESOLVED_SYSTEM_PYTHON:
        raise LaunchContractError("literal venv/resolved interpreter provenance differs")

    required_roles = {"parent_executor_v3", "shared_runtime_v2", "shared_runtime_v6",
                      "pinned_python_resolved_binary", "pinned_python_pyvenv_cfg",
                      "terminal_cpu_delta_adapter_v3"}
    present = {str(item.get("role")) for item in request.get("static_bindings", []) if isinstance(item, Mapping)}
    missing = sorted(required_roles - present)
    if missing:
        raise LaunchContractError(f"V64 static closure misses roles: {missing}")
    adapter = request.get("terminal_cpu_delta_contract", {}).get("adapter", {})
    if adapter.get("path") != _static_role(request, "terminal_cpu_delta_adapter_v3").get("path"):
        raise LaunchContractError("terminal adapter path differs from static closure")

    receipt = Path(str(storage["home_receipt_path"])).expanduser().resolve()
    returned = receipt.with_name("actual-returned-parent-report.json")
    evidence = receipt.with_name("actual-terminal-systemd-cpu-evidence.json")
    sidecar = receipt.with_name("terminal-cpu-delta-reconciliation-v3.json")
    parent_command = [PINNED_VENV, "-B", "-I", str(v64_script), "run",
                      "--request", str(request_file), "--io-slot-approved",
                      "--parent-pid", "<DIRECT_PARENT_PID>"]
    adapter_path = Path(str(adapter["path"])).expanduser().resolve()
    inspect_command = [PINNED_VENV, "-B", "-I", str(adapter_path), "inspect",
                       "--request", str(request_file), "--report", str(returned),
                       "--receipt", str(receipt), "--evidence", str(evidence),
                       "--ledger", str(parent["ledger_path"])]
    apply_command = [PINNED_VENV, "-B", "-I", str(adapter_path), "apply",
                     "--request", str(request_file), "--report", str(returned),
                     "--receipt", str(receipt), "--evidence", str(evidence),
                     "--ledger", str(parent["ledger_path"]), "--output", str(sidecar),
                     "--allow-ledger-mutation"]
    return {
        "schema": SCHEMA, "status": "READY_FOR_PRIMARY_V64_GUARDED_RUN",
        "request": {"path": str(request_file), "file_sha256": file_sha,
                     "canonical_sha256": canonical, "schema": request["schema"]},
        "bound_v64": {"path": str(v64_script), "sha256": sha256_file(v64_script),
                      "preflight": "_validate_request(verify_static=False) PASS",
                      "payload_read": False, "ledger_mutated": False},
        "parent_entry": {"command": parent_command, "direct_parent_pid_required": True,
                          "same_parent_ledger": True, "reservation_id": parent["reservation_id"],
                          "charge_id": parent["charge_id"]},
        "child_entry": {"command": command, "literal_python": PINNED_VENV,
                         "resolved_python_provenance": RESOLVED_SYSTEM_PYTHON,
                         "isolated_bootstrap": str(bootstrap), "output_root": output_arg},
        "resources": {"max_wall_seconds": 6000.0, "outer_wall_seconds": 6030.0,
                      "memory_max_bytes": 16 * 1024**3,
                      "external_reservation_bytes": int(storage["external_reservation_bytes"]),
                      "external_min_free_bytes": int(storage["external_min_free_bytes"]),
                      "home_min_free_bytes": int(storage["home_min_free_bytes"]),
                      "home_receipt_bytes": int(storage["home_receipt_bytes"])},
        "cleanup": {"owned_process_group": True, "parent_death_signal": execution["parent_death_signal"],
                     "term_then_kill_grace_seconds": float(execution["child_cleanup_grace_seconds"]),
                     "pipes": "nonblocking drain with bounded rolling tails; leader-exit pipe holders still trigger group cleanup"},
        "terminal": {
            "home_receipt": str(receipt), "returned_report": str(returned),
            "systemd_evidence": str(evidence), "delta_sidecar": str(sidecar),
            "adapter_path": str(adapter_path), "inspect_command": inspect_command,
            "apply_command": apply_command,
            "apply_scope": "same-parent CPU/storage metadata delta only; no reservation; explicit --allow-ledger-mutation required",
            "required_checks": ["request file SHA", "request canonical SHA", "charge_id/reservation_id", "terminal status", "CPUUsageNSec equality", "ExecStart exact request", "reservation released", "original charge unchanged"],
        },
        "fresh_v65": {"status": "DEFERRED_UNTIL_V64_SUCCESS", "old_ROOT060_reuse": False,
                      "next": "run V65 builder only from successful V64 report; no V8/evaluator before then"},
        "payload_read": False, "hdf5_or_bi4_content_read": False,
        "ledger_mutated": False, "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--expected-file-sha")
    parser.add_argument("--expected-canonical-sha")
    args = parser.parse_args(argv)
    try:
        value = inspect_request(args.request, expected_file_sha=args.expected_file_sha,
                                expected_canonical_sha=args.expected_canonical_sha)
    except (LaunchContractError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ROOT179B V64 launch contract: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
