#!/usr/bin/env python3
"""Metadata-only ROOT179C V66 launch and terminal contract.

V66 keeps the V64 request/report schemas so the already validated V65 proof
consumer remains usable.  Its only execution-protocol change is explicit:
the parent reserves the fresh namespace and the strict child atomically creates
the product directory.  This module performs the real bound V66 preflight and
prints the direct parent command plus the isolated terminal-adapter commands;
it never reserves, launches, hashes raw/H5, or mutates the ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-root179c-v66-launch-contract.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
V66_NAME = "ds_data02_stage2_f2_portable_executor_v66.py"
ADAPTER_NAME = "ds_data02_stage2_f2_v64_terminal_cpu_delta_adapter_v3.py"
BOOTSTRAP_NAME = "ds_data02_stage2_f2_v64_terminal_adapter_bootstrap_v1.py"
PINNED_VENV = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
RESOLVED_SYSTEM_PYTHON = "/usr/bin/python3.10"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN"}
UNKNOWN["QE"] = "UNKNOWN"
HEX64 = set("0123456789abcdef")


class LaunchContractError(ValueError):
    pass


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser().resolve()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise LaunchContractError(f"{target} exceeds metadata bound")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
        raise LaunchContractError(f"{role} must be a bounded regular metadata file: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LaunchContractError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise LaunchContractError(f"{role} must be an object")
    return target, value


def _load_bound_v66(request: Mapping[str, Any]) -> tuple[Any, Path]:
    worktree = request.get("worktree_root")
    if not isinstance(worktree, str) or not Path(worktree).is_absolute():
        raise LaunchContractError("request worktree_root is missing")
    script = Path(worktree).expanduser().resolve() / "lagrangian-fluid-lab" / "scripts" / V66_NAME
    if script.is_symlink() or not script.is_file():
        raise LaunchContractError(f"bound V66 implementation is missing: {script}")
    spec = importlib.util.spec_from_file_location("ds02_bound_root179c_v66", script)
    if spec is None or spec.loader is None:
        raise LaunchContractError(f"cannot load bound V66 implementation: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, script


def _role(request: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    rows = [item for item in request.get("static_bindings", [])
            if isinstance(item, Mapping) and item.get("role") == role]
    if len(rows) != 1:
        raise LaunchContractError(f"static role {role} must occur once")
    return rows[0]


def inspect_request(request_path: Path | str, *, expected_file_sha: str | None = None,
                    expected_canonical_sha: str | None = None) -> dict[str, Any]:
    request_file, request = _json(request_path, "ROOT179C V66 request")
    file_sha = sha256_file(request_file, max_bytes=8 * 1024 * 1024)
    if request.get("schema") != REQUEST_SCHEMA:
        raise LaunchContractError("request schema is not V64-compatible")
    if request.get("sha256") != canonical_sha(request):
        raise LaunchContractError("request canonical SHA differs")
    if expected_file_sha is not None and file_sha != expected_file_sha:
        raise LaunchContractError("request file SHA differs from expected source")
    if expected_canonical_sha is not None and request.get("sha256") != expected_canonical_sha:
        raise LaunchContractError("request canonical SHA differs from expected source")
    bound_v66, v66_script = _load_bound_v66(request)
    try:
        bound_v66._validate_request(request_file, verify_static=False)
    except Exception as error:
        raise LaunchContractError(f"bound V66 metadata preflight rejected request: {error}") from error

    execution = request.get("execution")
    runtime = request.get("runtime")
    storage = request.get("storage_scope")
    parent = request.get("parent_resource_binding")
    python = request.get("python_binding")
    if not all(isinstance(value, Mapping) for value in (execution, runtime, storage, parent, python)):
        raise LaunchContractError("V66 binding sections are incomplete")
    attempt = request.get("attempt_id")
    attempt_lower = attempt.lower() if isinstance(attempt, str) else ""
    if not isinstance(attempt, str) or "179c" not in attempt_lower or "179b" in attempt_lower:
        raise LaunchContractError("ROOT179C attempt must be a fresh 179C namespace")
    if parent.get("reservation_id") != attempt + "::reservation" or parent.get("charge_id") != attempt + "::charge":
        raise LaunchContractError("same-parent reservation/charge IDs are not request-scoped")
    if parent.get("same_parent_ledger") is not True or parent.get("ledger_reset") is not False:
        raise LaunchContractError("request is not same-parent ledger bound")
    if runtime.get("output_creation_protocol") != "WORKER_ATOMIC_MKDIR_V66":
        raise LaunchContractError("worker-owned output protocol is missing")
    if storage.get("output_creator") != "copied_worker_atomic_mkdir":
        raise LaunchContractError("storage output creator is missing")
    command = execution.get("command")
    if not isinstance(command, list) or not command or command[0] != PINNED_VENV:
        raise LaunchContractError("V66 child command must preserve literal venv argv[0]")
    if "-I" not in command or "--io-slot-approved" not in command or "--run-labels" not in command:
        raise LaunchContractError("V66 child command lacks isolation/io-slot/labels flags")
    output = Path(str(storage.get("external_output_root"))).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise LaunchContractError("V66 output root must still be absent before primary launch")
    worker = Path(str(runtime.get("worker_target"))).expanduser().resolve()
    bootstrap = Path(str(runtime.get("bootstrap_target"))).expanduser().resolve()
    if command[command.index("--worker") + 1] != str(worker) or str(bootstrap) not in command:
        raise LaunchContractError("V66 child paths do not match runtime binding")
    if python.get("argv_path") != PINNED_VENV or python.get("resolved_path") != RESOLVED_SYSTEM_PYTHON:
        raise LaunchContractError("literal/resolved Python provenance differs")
    if float(execution.get("max_wall_seconds", 0)) != 6000.0 or int(execution.get("memory_max_bytes", 0)) != 16 * 1024**3:
        raise LaunchContractError("V66 child budget differs from ROOT179C scope")
    if int(storage.get("external_reservation_bytes", 0)) != 12 * 1024**3 or int(storage.get("external_min_free_bytes", 0)) != 20 * 1024**3:
        raise LaunchContractError("V66 external two-filesystem budget differs")
    if int(storage.get("home_receipt_bytes", 0)) < 1024 * 1024:
        raise LaunchContractError("V66 Home receipt allowance is below 1 MiB")
    adapter_contract = request.get("terminal_cpu_delta_contract", {}).get("adapter", {})
    adapter = Path(str(adapter_contract.get("path"))).expanduser().resolve()
    bootstrap_adapter = Path(str(adapter_contract.get("bootstrap_path"))).expanduser().resolve()
    if adapter.name != ADAPTER_NAME or bootstrap_adapter.name != BOOTSTRAP_NAME:
        raise LaunchContractError("V66 terminal adapter bootstrap binding is incomplete")
    if _role(request, "terminal_adapter_bootstrap_v1").get("path") != str(bootstrap_adapter):
        raise LaunchContractError("terminal adapter bootstrap is not statically bound")
    receipt = Path(str(storage["home_receipt_path"])).expanduser().resolve()
    returned = receipt.with_name("actual-returned-parent-report.json")
    evidence = receipt.with_name("actual-terminal-systemd-cpu-evidence.json")
    sidecar = receipt.with_name("terminal-cpu-delta-reconciliation-v3.json")
    scripts_root = adapter.parent
    adapter_args = ["--request", str(request_file), "--report", str(returned),
                    "--receipt", str(receipt), "--evidence", str(evidence),
                    "--ledger", str(parent["ledger_path"])]
    inspect_command = [PINNED_VENV, "-B", "-I", str(bootstrap_adapter),
                       "--scripts-root", str(scripts_root), "--adapter", str(adapter), "--",
                       "inspect", *adapter_args]
    apply_command = [PINNED_VENV, "-B", "-I", str(bootstrap_adapter),
                     "--scripts-root", str(scripts_root), "--adapter", str(adapter), "--",
                     "apply", *adapter_args, "--output", str(sidecar), "--allow-ledger-mutation"]
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_PRIMARY_V66_GUARDED_RUN",
        "request": {"path": str(request_file), "file_sha256": file_sha,
                     "canonical_sha256": request["sha256"], "attempt_id": attempt},
        "bound_v66": {"path": str(v66_script), "sha256": sha256_file(v66_script),
                      "preflight": "_validate_request(verify_static=False) PASS"},
        "output_protocol": {"name": "WORKER_ATOMIC_MKDIR_V66",
                             "parent_precreates_output": False,
                             "child_creates_output": True,
                             "existing_or_nonempty_rejected": True},
        "parent_entry": {"command": [PINNED_VENV, "-B", "-I", str(v66_script), "run",
                                        "--request", str(request_file), "--io-slot-approved",
                                        "--parent-pid", "<DIRECT_PARENT_PID>"],
                          "same_parent_ledger": True,
                          "reservation_id": parent["reservation_id"], "charge_id": parent["charge_id"]},
        "child_entry": {"command": command, "literal_python": PINNED_VENV,
                         "output_root": str(output), "output_creation_owner": "strict worker"},
        "cleanup": {"owned_process_group": True, "parent_death_signal": "PR_SET_PDEATHSIG=SIGTERM",
                     "term_then_kill": float(execution.get("child_cleanup_grace_seconds", 0)),
                     "bounded_pipe_drain": True, "leader_exit_pipe_holder_cleanup": True},
        "terminal": {"home_receipt": str(receipt), "returned_report": str(returned),
                      "systemd_evidence": str(evidence), "delta_sidecar": str(sidecar),
                      "adapter_inspect": inspect_command, "adapter_apply": apply_command,
                      "apply_requires_explicit_flag": True, "no_reservation": True},
        "fresh_v65": {"status": "DEFERRED_UNTIL_V66_SUCCESS", "old_ROOT060_reuse": False},
        "payload_read": False, "ledger_mutated": False,
        "qualification": dict(UNKNOWN),
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
        print(f"ROOT179C V66 launch contract: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
