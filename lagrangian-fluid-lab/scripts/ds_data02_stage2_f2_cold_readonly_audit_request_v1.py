#!/usr/bin/env python3
"""Build a real ``strace -ff`` role/ancestry audit request.

The request is a metadata contract for the existing cold-read audit v4.  It
binds the executor, source-copy, converter, decoder, private-worker and
evaluator roles, preserves the literal virtual-environment argv[0], and
requires a parent guard to supply actual PID ancestry and scratch ownership.
The builder reads JSON and ``stat`` records only.  It does not read H5/BI4
payloads, parse trace files, start strace, or assign PID lists itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
AUDIT_V4_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_cold_readonly_audit_v4.py"
SCHEMA = "ds02.stage2.f2-cold-readonly-audit-request.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
REQUIRED_ROLE_BINDINGS = {
    "executor": {"kind": "private", "request_roles": ("executor_v34", "executor_v35", "executor_v36")},
    "source_copy": {"kind": "source", "request_roles": ("raw_frame_input", "v2:native_partout")},
    "converter": {"kind": "private", "request_roles": ("raw_converter", "raw_worker_v2")},
    "decoder": {"kind": "private", "request_roles": ("native_bi4_decoder", "native_decoder")},
    "evaluator": {"kind": "private", "request_roles": ("evaluator_v4", "no_model_evaluator_v1", "evaluator_v3", "evaluator_v2")},
}


class AuditRequestError(RuntimeError):
    """Raised when the real trace audit contract is incomplete."""


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_json(path: Path | str) -> str:
    return hashlib.sha256(Path(path).expanduser().resolve().read_bytes()).hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditRequestError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise AuditRequestError(f"JSON object required: {target}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise AuditRequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise AuditRequestError(f"{name} must be an absolute path")
    return Path(value).expanduser()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise AuditRequestError(f"{name} must be a lowercase SHA-256")
    return value


def _stat(path: Path, name: str) -> dict[str, Any]:
    try:
        info = path.stat()
    except OSError as error:
        raise AuditRequestError(f"{name} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise AuditRequestError(f"{name} is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode)),
            "resolved_path": str(path.resolve())}


def _bind_json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    info = _stat(target, role)
    return {"path": str(target), "sha256": sha256_json(target),
            "bytes": info["bytes"], "mtime_ns": info["mtime_ns"], "role": role}


def _load_v34(path: Path | str) -> tuple[Path, dict[str, Any]]:
    request_path = Path(path).expanduser().resolve()
    request = _load_json(request_path)
    if request.get("schema") != V34_SCHEMA:
        raise AuditRequestError("executor request schema differs from v34")
    if request.get("sha256") != canonical_sha(request):
        raise AuditRequestError("executor request canonical SHA differs")
    if request.get("original_path_fallback") not in {None, "FORBIDDEN"}:
        raise AuditRequestError("executor permits original-path fallback")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("original_path_fallback") != "FORBIDDEN":
        raise AuditRequestError("executor execution contract does not forbid original fallback")
    if execution.get("os_open_audit_required") is not True:
        raise AuditRequestError("executor request does not require OS-level open audit")
    if execution.get("fresh_subprocess") is not True or execution.get("isolated_python") != "-I":
        raise AuditRequestError("executor is not a private isolated subprocess")
    return request_path, request


def _role_entries(request: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    runtime_entries: list[Mapping[str, Any]] = []
    for key in ("source_entries", "runtime_sources"):
        values = request.get(key)
        if not isinstance(values, list):
            raise AuditRequestError(f"executor {key} are missing")
        if key == "runtime_sources":
            runtime_entries.extend(item for item in values if isinstance(item, Mapping))
        entries.extend(item for item in values if isinstance(item, Mapping))
    by_role: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise AuditRequestError("executor role entry is malformed")
        path = _path(item.get("path"), f"role {role}.path")
        info = _stat(path, f"role {role}")
        expected = item.get("source_stat_expected")
        if isinstance(expected, Mapping):
            for key in ("bytes", "mtime_ns", "mode_bits"):
                if key in expected and int(expected[key]) != int(info[key]):
                    raise AuditRequestError(f"role {role} stat differs from bound source metadata")
        required = bool(item.get("required_executable", False))
        if required != bool(info["mode_bits"] & 0o111):
            raise AuditRequestError(f"role {role} executable mode differs from bound metadata")
        if item.get("preserve_mode") is not True:
            raise AuditRequestError(f"role {role} does not preserve executable mode contract")
        by_role.setdefault(role, []).append({
            "role": role, "path": str(path), "resolved_source_path": str(path.resolve()),
            "target_relative_path": item.get("target_relative_path"),
            "bytes": int(info["bytes"]), "mtime_ns": int(info["mtime_ns"]),
            "mode_bits": int(info["mode_bits"]), "required_executable": required,
            "preserve_mode": True, "invocation_path": item.get("invocation_path"),
        })
    # V34 retains a source-copy python record for provenance and a runtime
    # record with the literal .venv invocation.  The latter is authoritative
    # for argv[0]; duplicate source provenance must not force a system-python
    # choice or be mistaken for two executable roles.
    python = [item for item in runtime_entries if item.get("role") == "python_executable"]
    if not python:
        python = [item for item in entries if item.get("role") == "python_executable"]
    if len(python) != 1:
        raise AuditRequestError("exactly one python_executable role is required")
    invocation = python[0].get("invocation_path")
    if not isinstance(invocation, str) or not Path(invocation).is_absolute():
        raise AuditRequestError("python_executable invocation_path must be literal absolute argv[0]")
    return by_role, {"literal_invocation_path": invocation,
                     "resolved_provenance_path": str(Path(invocation).expanduser().resolve()),
                     "preserve_literal_argv0": True}


def _role_binding(by_role: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name, spec in REQUIRED_ROLE_BINDINGS.items():
        present: list[str] = []
        for role in spec["request_roles"]:
            if role in by_role:
                present.append(role)
        if not present:
            raise AuditRequestError(f"required trace role {name} has no bound source/runtime role")
        result.append({
            "role_id": name, "kind": spec["kind"], "request_roles": present,
            "pid_source": "PARENT_GUARD_PROCESS_RECORD_ONLY",
            "pid_values": "PENDING_PARENT_GUARD; builder never invents PID lists",
            "source_access": "ORIGINAL_ALLOWED_DURING_SOURCE_COPY" if spec["kind"] == "source" else "ORIGINAL_FORBIDDEN_TARGET_AND_REGISTERED_ENV_ONLY",
        })
    result.append({"role_id": "strace", "kind": "parent_trace",
                   "request_roles": ["os_strace"],
                   "pid_source": "PARENT_GUARD_PROCESS_RECORD_ONLY",
                   "pid_values": "PENDING_PARENT_GUARD"})
    return result


def build_request(*, v34_request: Path | str, provenance_sidecar: Path | str,
                  target_root: Path | str, output_root: Path | str,
                  trace_prefix: Path | str, output: Path | str,
                  parent_guard_record: Path | str | None = None,
                  v16_proof: Path | str | None = None,
                  v16_result: Path | str | None = None,
                  evaluator_report: Path | str | None = None) -> dict[str, Any]:
    request_path, request = _load_v34(v34_request)
    provenance_path = Path(provenance_sidecar).expanduser().resolve()
    provenance = _load_json(provenance_path)
    if provenance.get("sha256") is not None and provenance.get("sha256") != canonical_sha(provenance):
        raise AuditRequestError("provenance sidecar canonical SHA differs")
    target = _path(str(target_root), "target_root")
    relocated_output = _path(str(output_root), "output_root")
    trace = _path(str(trace_prefix), "trace_prefix")
    if not (trace == relocated_output or str(trace).startswith(str(relocated_output).rstrip("/") + "/")):
        raise AuditRequestError("trace prefix must be under the fresh output root")
    by_role, python = _role_entries(request)
    roles = _role_binding(by_role)
    strace_candidates = by_role.get("os_strace", [])
    if len(strace_candidates) != 1:
        raise AuditRequestError("exactly one os_strace binding is required")
    strace = strace_candidates[0]
    if not strace["required_executable"]:
        raise AuditRequestError("bound strace role is not executable")

    optional: dict[str, Any] = {}
    for key, value in (("v16_proof", v16_proof), ("v16_result", v16_result),
                       ("evaluator_report", evaluator_report),
                       ("parent_guard_record", parent_guard_record)):
        if value is None:
            optional[key] = {"status": "PENDING_PARENT_GUARD"}
        else:
            optional[key] = _bind_json(value, key)

    command = request.get("execution", {}).get("command")
    if not isinstance(command, list) or not command:
        raise AuditRequestError("executor execution.command is missing")
    command = [str(item) for item in command]
    if command[0] != python["literal_invocation_path"]:
        raise AuditRequestError("executor command does not preserve literal python argv[0]")
    trace_command = [str(strace["path"]), "-ff", "-yy", "-s", "4096",
                     "-e", "trace=%file,%process", "-o", str(trace), "--", *command]
    audit_command = [python["literal_invocation_path"], "-B", "-I", str(AUDIT_V4_SCRIPT),
                     "--executor-report", "<executor-report>", "--v34-request", str(request_path),
                     "--provenance-sidecar", str(provenance_path), "--trace-prefix", str(trace),
                     "--parent-guard-record", "<parent-guard-record>",
                     "--source-pids", "<guard-source-pids>", "--private-pids", "<guard-private-pids>",
                     "--target-root", str(target), "--output-root", str(relocated_output),
                     "--output", "<audit-report>"]
    value: dict[str, Any] = {
        "schema": SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_TRACE_GUARD", "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False, "hdf5_or_bi4_content_read": False,
        "ledger_mutated": False,
        "inputs": {"v34_request": _bind_json(request_path, "v34_request"),
                   "provenance_sidecar": _bind_json(provenance_path, "provenance_sidecar"),
                   "audit_v4_source": _bind_json(AUDIT_V4_SCRIPT, "audit_v4_source")},
        "fresh_roots": {"target_root": str(target), "output_root": str(relocated_output)},
        "runtime_binding": python,
        "role_bindings": roles,
        "trace": {
            "executable": strace,
            "command_template": trace_command,
            "mode": "strace -ff filtered file/process syscalls with C-level opens",
            "syscalls": ["%file", "%process"], "follows_forks": True,
            "trace_prefix": str(trace), "file_pattern": f"{trace}.<pid>",
            "relative_or_dirfd_access": "UNKNOWN_UNLESS_GUARD_TRACE_RECONSTRUCTS_IT",
            "source_original_access": "ALLOWED_ONLY_FOR_REGISTERED_SOURCE_COPY_ROLES",
            "private_original_access": "FORBIDDEN",
            "unbound_absolute_access": "FAIL_CLOSED",
        },
        "executor_command_template": command,
        "audit_v4_command_template": audit_command,
        "optional_evidence": optional,
        "scratch_policy": {
            "allowed_prefix": "/tmp/ds02-direct-bi4-",
            "requires_parent_creator_pid": True,
            "requires_trace_mkdir_event": True,
            "whole_tmp_whitelist": False,
        },
        "limitations": [
            "This is a trace/audit request only; it does not start strace or the executor.",
            "Parent guard must supply actual PID/process ancestry and source/private PID role records.",
            "The registered virtual environment is a shared environment scope; standalone environment portability is not claimed.",
            "QI/QN/QE remain UNKNOWN and no native/replay/evaluator credit is granted by this request.",
        ],
    }
    value["sha256"] = canonical_sha(value)
    output_path = _write_new(output, value)
    return {"schema": SCHEMA, "status": value["status"], "request_path": str(output_path),
            "request_sha256": value["sha256"], "trace_command": trace_command,
            "role_count": len(roles), "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build-request", nargs="?")
    parser.add_argument("--v34-request", type=Path, required=True)
    parser.add_argument("--provenance-sidecar", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--trace-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--v16-proof", type=Path)
    parser.add_argument("--v16-result", type=Path)
    parser.add_argument("--evaluator-report", type=Path)
    args = parser.parse_args(argv)
    if args.build_request not in {None, "build-request"}:
        parser.error("the only command is build-request")
    try:
        value = build_request(v34_request=args.v34_request, provenance_sidecar=args.provenance_sidecar,
                              target_root=args.target_root, output_root=args.output_root,
                              trace_prefix=args.trace_prefix, output=args.output,
                              parent_guard_record=args.parent_guard_record,
                              v16_proof=args.v16_proof, v16_result=args.v16_result,
                              evaluator_report=args.evaluator_report)
    except (AuditRequestError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"cold readonly audit request builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
