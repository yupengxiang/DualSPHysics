#!/usr/bin/env python3
"""Run an isolated V10 -> real V3 worker -> independent V5 chain.

This command is deliberately a small orchestration layer for tests and
source-bound admission probes.  The V10 command owns the isolated temporary
ledger, reservation, input pre/post hashes, child process, and terminal
receipt.  Its child is the real V3 HDF5 audit worker from the request.  Only
after a completed V10 receipt does this wrapper invoke the independent V5
verifier on the worker report.  No model, solver, qualification, or shared
ledger is involved.

Production requests are not accepted by this fixture-oriented entrypoint
unless the caller explicitly supplies ``--allow-fixture-context`` to the V5
step.  The source/worker/verifier paths are checked against the request so a
caller cannot silently substitute a different worker after V10's closure
gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence


SCRIPT = Path(__file__).resolve()
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_RUNTIME_STDOUT_BYTES = 2 * 1024 * 1024
MAX_RUNTIME_STDERR_BYTES = 512 * 1024
MAX_WORKER_REPORT_BYTES = 4 * 1024 * 1024
MAX_VERIFIED_BYTES = 2 * 1024 * 1024


class RuntimeChainError(ValueError):
    """The bounded V10/worker/V5 chain did not complete."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded_json(path_value: Path, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise RuntimeChainError(f"{label} is not a regular file: {path}")
    if path.stat().st_size > max_bytes:
        raise RuntimeChainError(f"{label} exceeds bounded JSON size: {path}")
    before = path.stat()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeChainError(f"{label} is invalid JSON") from exc
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise RuntimeChainError(f"{label} changed while being read")
    if not isinstance(value, dict):
        raise RuntimeChainError(f"{label} must be an object")
    return value


def _regular(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, (str, os.PathLike)) or not path_value:
        raise RuntimeChainError(f"{label} lacks a path")
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise RuntimeChainError(f"{label} is not a regular non-symlink file: {path}")
    return path.resolve()


def _directory(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise RuntimeChainError(f"{label} lacks a path")
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise RuntimeChainError(f"{label} is not a regular non-symlink directory: {path}")
    return path.resolve()


def _bounded_tail(value: bytes, limit: int) -> str:
    if len(value) <= limit:
        return value.decode("utf-8", errors="replace")
    return "[truncated; bytes=%d]\n%s" % (len(value), value[-limit:].decode("utf-8", errors="replace"))


def _run_bounded(argv: list[str], *, timeout: float, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeChainError(f"bounded subprocess timeout: {argv[0]}") from exc
    if len(result.stdout) > MAX_RUNTIME_STDOUT_BYTES or len(result.stderr) > MAX_RUNTIME_STDERR_BYTES:
        raise RuntimeChainError(
            "bounded subprocess output exceeded limits: "
            + json.dumps({"stdout_bytes": len(result.stdout), "stderr_bytes": len(result.stderr)})
        )
    return result


def _json_stdout(result: subprocess.CompletedProcess[bytes], label: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeChainError(
            f"{label} did not emit one JSON object; stderr={_bounded_tail(result.stderr, 8192)}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeChainError(f"{label} JSON result is not an object")
    return value


def _replace_attempt_root(value: str, attempt_root: Path) -> Path:
    marker = "{attempt_root}"
    if marker not in value:
        return Path(value).expanduser().resolve()
    replaced = value.replace(marker, str(attempt_root))
    return Path(replaced).expanduser().resolve()


def _inside(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeChainError(f"{label} escapes attempt root: {path}") from exc


def run_chain(
    request_path: Path,
    *,
    data_root: Path,
    runtime_v10: Path,
    worker: Path,
    verifier: Path,
    output: Path,
    allow_fixture_context: bool = False,
    parent_pid: int | None = None,
) -> dict[str, Any]:
    request_path = _regular(request_path, "request")
    runtime_v10 = _regular(runtime_v10, "V10 runtime")
    worker = _regular(worker, "V3 worker")
    verifier = _regular(verifier, "V5 verifier")
    request = bounded_json(request_path, "request")
    if request.get("schema") != "ds02.request.v1":
        raise RuntimeChainError("request schema is not ds02.request.v1")
    command = request.get("command")
    binding = request.get("interpreter_binding")
    if not isinstance(command, list) or len(command) < 8 or not all(isinstance(item, str) for item in command):
        raise RuntimeChainError("request command is incomplete")
    if not isinstance(binding, dict) or command[0] != binding.get("literal_path"):
        raise RuntimeChainError("request literal interpreter binding differs from command")
    if not command[0].endswith("/.venv/bin/python"):
        raise RuntimeChainError("chain requires the literal pinned venv interpreter")
    command_worker = _regular(command[2], "request worker")
    if command_worker != worker:
        raise RuntimeChainError("request worker is not the explicitly supplied V3 worker")
    if command[3] != "audit" or "--manifest" not in command or "--output" not in command:
        raise RuntimeChainError("request is not the V3 audit command")
    manifest_arg = command[command.index("--manifest") + 1]
    manifest = _regular(manifest_arg, "request manifest")
    output_arg = command[command.index("--output") + 1]
    requested_report_name = _replace_attempt_root(output_arg, data_root / "families" / request["family_id"] / request["case_id"] / request["attempt_id"])

    # The V10 executable is the only owner of the isolated reservation and
    # terminal receipt.  Its argv is source-bound and receives the parent PID
    # so a test cannot leave a detached child behind.
    timeout = float(request.get("max_wall_seconds", 0)) + 30.0
    if timeout <= 30.0:
        raise RuntimeChainError("request max_wall_seconds is not positive")
    runtime_result = _run_bounded(
        [
            command[0], "-B", str(runtime_v10), "run",
            "--request", str(request_path), "--data-root", str(data_root),
            "--parent-pid", str(os.getpid() if parent_pid is None else parent_pid),
        ],
        timeout=timeout,
        cwd=Path(request["cwd"]).expanduser().resolve(),
    )
    runtime_value = _json_stdout(runtime_result, "V10 runtime")
    if runtime_result.returncode != 0 or runtime_value.get("status") != "completed":
        raise RuntimeChainError(
            "V10 runtime failed: "
            + json.dumps({"returncode": runtime_result.returncode, "result": runtime_value, "stderr": _bounded_tail(runtime_result.stderr, 8192)}, sort_keys=True)
        )
    output_root = _directory(runtime_value.get("output_root"), "V10 output_root") if runtime_value.get("output_root") else None
    if output_root is None:
        raise RuntimeChainError("V10 receipt does not expose output_root")
    data_root = data_root.expanduser().resolve()
    _inside(output_root, data_root, "V10 output_root")
    report = requested_report_name
    _inside(report, output_root, "worker report")
    if not report.is_file() or report.is_symlink():
        raise RuntimeChainError(f"V3 worker report is missing: {report}")
    if report.stat().st_size > MAX_WORKER_REPORT_BYTES:
        raise RuntimeChainError("V3 worker report exceeds bounded output size")
    report_sha = sha256_file(report)

    verifier_output = output_root / "scientific-field-h5-v5-verified.json"
    verifier_argv = [
        command[0], "-B", str(verifier), "verify",
        "--manifest", str(manifest), "--report", str(report), "--output", str(verifier_output),
    ]
    if allow_fixture_context:
        verifier_argv.append("--allow-fixture-context")
    verify_result = _run_bounded(verifier_argv, timeout=30.0, cwd=Path(request["cwd"]).expanduser().resolve())
    verified_value = _json_stdout(verify_result, "V5 verifier") if verify_result.stdout.strip() else None
    if verify_result.returncode != 0 or verified_value is None:
        raise RuntimeChainError(
            "independent V5 verifier failed: "
            + json.dumps({"returncode": verify_result.returncode, "stderr": _bounded_tail(verify_result.stderr, 8192)}, sort_keys=True)
        )
    if not verifier_output.is_file() or verifier_output.is_symlink() or verifier_output.stat().st_size > MAX_VERIFIED_BYTES:
        raise RuntimeChainError("V5 verifier output is missing or exceeds bound")
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise RuntimeChainError(f"refusing to overwrite chain result: {output}")
    result = {
        "schema": "ds02.stage2.scientific-field-h5-runtime-v10-chain.v1",
        "status": "COMPLETED_TINY_V10_WORKER_V3_V5_CHAIN_NO_SCIENTIFIC_CREDIT",
        "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
        "runtime_v10": {
            "path": str(runtime_v10),
            "sha256": sha256_file(runtime_v10),
            "status": runtime_value.get("status"),
            "receipt_path": str(output_root / "execution-receipt.json"),
            "receipt_sha256": sha256_file(output_root / "execution-receipt.json"),
        },
        "worker_v3": {"path": str(worker), "sha256": sha256_file(worker), "report": str(report), "report_sha256": report_sha},
        "verifier_v5": {"path": str(verifier), "sha256": sha256_file(verifier), "output": str(verifier_output), "output_sha256": sha256_file(verifier_output), "result": verified_value},
        "production_eligible": False,
        "scientific_credit": 0,
        "model_invoked": False,
        "cfd_invoked": False,
        "read_policy": {"tiny_fixture_only": bool(allow_fixture_context), "production_payload_read": False, "shared_ledger_used": False},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": result["status"], "output": str(output), "output_sha256": sha256_file(output), "scientific_credit": 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--runtime-v10", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fixture-context", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        result = run_chain(
            args.request, data_root=args.data_root, runtime_v10=args.runtime_v10,
            worker=args.worker, verifier=args.verifier, output=args.output,
            allow_fixture_context=args.allow_fixture_context, parent_pid=args.parent_pid,
        )
    except (RuntimeChainError, OSError, subprocess.SubprocessError) as exc:
        print(f"scientific-field-h5-runtime-v10-chain-v1: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
