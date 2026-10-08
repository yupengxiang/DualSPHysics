#!/usr/bin/env python3
"""Parent-guarded follow-on for an existing typed-only V16 result.

This is an additive evaluator path for the already completed typed-only
labels product.  It binds a fresh V8 proof and the exact V16 result, then
executes only :mod:`ds_data02_stage2_f2_typed_only_evaluator_v1` after a
same-parent reservation.  It deliberately has no raw BI4/HDF5 source entry,
converter, or cold-replay stage: ``raw_to_typed_credit`` and
``portable_cold_replay_credit`` are always ``NOT_CLAIMED`` and QI/QN/QE stay
UNKNOWN.

The parent owns the supplemental Stage2 ledger reservation and charge.  The
V16 result is stat-checked while building/preflighting, but its content SHA
is read only by the child after reservation.  A literal virtual-environment
argv[0] is retained so the ABI-compatible interpreter is not replaced by
its ``/usr/bin/python3.10`` realpath.
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


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
TE_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"
PARENT_V3_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V3_EVALUATOR = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v3.py"
V2_EVALUATOR = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v2.py"
V14_OPERATOR = SCRIPT_DIR / "ds_data02_stage2_f2_replay_v14.py"
V15_OPERATOR = SCRIPT_DIR / "ds_data02_stage2_f2_replay_v15.py"
V2_BUILDER = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v2.py"
V1_BUILDER = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v1.py"
RUNTIME_V6 = SCRIPT_DIR / "ds_data02_runtime_v6.py"
V21_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
STRACE = Path("/usr/bin/strace")

SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-report.v1"
TE_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
STRACE_OPTIONS = ["-ff", "-e", "trace=%file,%process", "-s", "4096"]
THREAD_ENV = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
CHILD_GRACE_SECONDS = 25.0


class TypedParentError(RuntimeError):
    pass


class ParentDeadline(TypedParentError):
    pass


class ParentCancelled(TypedParentError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TE = _load(TE_SCRIPT, "ds02_bound_typed_only_evaluator_parent_worker")
PARENT = _load(PARENT_V3_SCRIPT, "ds02_bound_parent_v3_for_typed_only")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return PARENT.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise TypedParentError(f"{name} must be a lowercase SHA-256")
    return value


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise TypedParentError(f"{role} path is missing")
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise TypedParentError(f"{role} is not a regular non-symlink file: {path}")
    return path


def _json(path: Path | str, role: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    target = _file(path, role)
    if target.stat().st_size > max_bytes:
        raise TypedParentError(f"{role} exceeds metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedParentError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise TypedParentError(f"{role} must be a JSON object")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise TypedParentError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _stat(path: Path, role: str) -> dict[str, Any]:
    info = path.stat()
    if not path.is_file():
        raise TypedParentError(f"{role} is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(info.st_mode & 0o777)}


def _static(path: Path, role: str) -> dict[str, Any]:
    info = _stat(path, role)
    return {"role": role, "path": str(path), **info, "sha256": sha256_file(path)}


def _load_parent_resource(path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    parent = _json(path, "parent-v3 request")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise TypedParentError("parent-v3 request schema differs")
    if parent.get("sha256") != canonical_sha(parent):
        raise TypedParentError("parent-v3 request canonical SHA differs")
    binding = parent.get("parent_resource_binding")
    storage = parent.get("storage_scope")
    if not isinstance(binding, Mapping) or not isinstance(storage, Mapping):
        raise TypedParentError("parent-v3 resource/storage bindings are missing")
    ledger = _file(binding.get("ledger_path"), "parent ledger")
    live = _json(ledger, "parent ledger", max_bytes=128 * 1024 * 1024)
    limits = live.get("limits")
    if not isinstance(limits, Mapping):
        raise TypedParentError("live ledger limits are missing")
    external = Path(str(binding.get("external_filesystem") or storage.get("external_filesystem"))).expanduser().resolve()
    if not external.is_dir():
        raise TypedParentError(f"external filesystem is missing: {external}")
    home = Path(str(binding.get("home_path") or limits.get("home_path", "/home/jade"))).expanduser().resolve()
    if not home.is_dir():
        raise TypedParentError(f"Home filesystem is missing: {home}")
    if str(binding.get("storage_policy")) != str(limits.get("storage_policy")):
        raise TypedParentError("parent storage policy differs from live ledger")
    if int(binding.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise TypedParentError("parent Home floor differs from live ledger")
    return parent, ledger, {"binding": dict(binding), "storage": dict(storage),
                            "limits": dict(limits), "external": external, "home": home,
                            "live": live}


def _load_typed_request(path: Path) -> dict[str, Any]:
    request = _json(path, "typed-only evaluator request")
    if request.get("schema") != TE_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TypedParentError("typed-only evaluator request schema/SHA differs")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("product_mode") != "TYPED_ONLY_LABELS":
        raise TypedParentError("typed-only request is not parent-ready TYPED_ONLY_LABELS")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise TypedParentError("typed-only request is not model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN or request.get("raw_opened", False) is True:
        raise TypedParentError("typed-only request quality/raw boundary is not conservative")
    result = request.get("result")
    if not isinstance(result, Mapping):
        raise TypedParentError("typed-only result binding is missing")
    result_path = _file(result.get("path"), "typed-only V16 result")
    result_stat = _stat(result_path, "typed-only V16 result")
    if int(result.get("bytes", -1)) != result_stat["bytes"]:
        raise TypedParentError("typed-only V16 result byte stat differs")
    _sha(result.get("sha256"), "typed-only V16 result SHA")
    # V8 request, proof, source contract, frozen V15, and producer report are
    # small JSON dependencies; validating their declared hashes here does not
    # read the result payload.  The result content hash is deferred to child.
    for role in ("producer_report", "proof_request", "proof", "source_contract", "frozen_request"):
        item = request.get(role)
        if not isinstance(item, Mapping):
            raise TypedParentError(f"typed-only {role} binding is missing")
        bound = _file(item.get("path"), f"typed-only {role}")
        if item.get("sha256") != sha256_file(bound):
            raise TypedParentError(f"typed-only {role} SHA differs")
    return request


def _python_literal(path: Path | str) -> Path:
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink() and not path.exists():
        raise TypedParentError(f"literal Python invocation is missing: {path}")
    if not (_stat(path, "python executable")["mode_bits"] & 0o111):
        raise TypedParentError("literal Python invocation is not executable")
    return path


def _python_binding(path: Path) -> dict[str, Any]:
    info = _stat(path, "python executable")
    return {"literal_invocation_path": str(path),
            "resolved_provenance_path": str(path.resolve()),
            "bytes": info["bytes"], "mtime_ns": info["mtime_ns"],
            "mode_bits": info["mode_bits"], "sha256": sha256_file(path),
            "preserve_literal_argv0": True}


def _git_at_launch(root: Path) -> dict[str, Any]:
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
        return {"root": str(root), "head": head, "capture_status": "PASS"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"root": str(root), "head": None, "capture_status": "FAILED",
                "error": f"{type(error).__name__}: {error}"}


def _binding_paths() -> list[tuple[Path, str]]:
    return [
        (SCRIPT, "typed_only_parent_v1"),
        (TE_SCRIPT, "typed_only_evaluator_v1"),
        (PARENT_V3_SCRIPT, "parent_executor_v3"),
        (V8_SCRIPT, "fresh_v16_proof_consumer_v8"),
        (V3_EVALUATOR, "no_model_evaluator_v3"),
        (V2_EVALUATOR, "no_model_evaluator_v2"),
        (V14_OPERATOR, "replay_operator_v14"),
        (V15_OPERATOR, "replay_operator_v15"),
        (V2_BUILDER, "fresh_v16_request_builder_v2"),
        (V1_BUILDER, "fresh_v16_request_builder_v1"),
        (RUNTIME_V6, "shared_runtime_v6"),
        (V21_SCRIPT, "shared_v21_accounting"),
        (STRACE, "os_strace"),
    ]


def build_request(*, typed_request: Path | str, parent_v3_request: Path | str,
                  output: Path | str, external_filesystem: Path | str,
                  ledger: Path | str, parent_attempt_id: str,
                  supervisor_output_root: Path | str, home_receipt: Path | str,
                  python_executable: Path | str,
                  max_wall_seconds: float = 300.0,
                  external_bytes: int = 256 * 1024 * 1024,
                  home_receipt_bytes: int = 256 * 1024,
                  allow_missing_parent: bool = True) -> dict[str, Any]:
    typed_path = _file(typed_request, "typed-only evaluator request")
    typed = _load_typed_request(typed_path)
    parent_path = _file(parent_v3_request, "parent-v3 request")
    parent, ledger_path, resource_info = _load_parent_resource(parent_path)
    if ledger_path != Path(ledger).expanduser().resolve():
        raise TypedParentError("explicit ledger differs from parent-v3 binding")
    external = Path(external_filesystem).expanduser().resolve()
    if external != resource_info["external"]:
        raise TypedParentError("explicit external filesystem differs from parent-v3 binding")
    if external == Path("/") or not external.is_dir():
        raise TypedParentError("external filesystem is invalid")
    if not isinstance(parent_attempt_id, str) or not parent_attempt_id:
        raise TypedParentError("parent_attempt_id is required")
    try:
        wall = float(max_wall_seconds)
    except (TypeError, ValueError) as error:
        raise TypedParentError("max_wall_seconds is malformed") from error
    if not math.isfinite(wall) or wall <= 0:
        raise TypedParentError("max_wall_seconds must be finite and positive")
    if int(external_bytes) <= 0 or int(home_receipt_bytes) <= 0:
        raise TypedParentError("storage reservation bytes must be positive")
    output_root = Path(supervisor_output_root).expanduser().resolve()
    receipt = Path(home_receipt).expanduser().resolve()
    if output_root.exists() or not _under(output_root, external) or output_root == external:
        raise TypedParentError("typed evaluator output root must be a fresh child of external")
    if receipt.exists():
        raise TypedParentError("typed evaluator Home receipt already exists")
    python = _python_literal(python_executable)
    if not STRACE.is_file():
        raise TypedParentError("/usr/bin/strace is required")
    for path, role in _binding_paths():
        _file(path, role)
    parent_binding = resource_info["binding"]
    reservation_id = parent_attempt_id + "::typed-only-evaluator-v1-reservation"
    charge_id = parent_attempt_id + "::typed-only-evaluator-v1-charge"
    trace = output_root / "typed-only-evaluator-v1-os-trace"
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "product_mode": "TYPED_ONLY_LABELS",
        "typed_request": {"path": str(typed_path), "sha256": sha256_file(typed_path),
                           "schema": TE_SCHEMA, "immutable": True},
        "parent_v3_request": {"path": str(parent_path), "sha256": sha256_file(parent_path),
                               "schema": parent.get("schema"), "immutable": True},
        "worktree_root": str(SCRIPT_DIR.parent.parent),
        "python_binding": _python_binding(python),
        "parent_resource_binding": {
            "ledger_path": str(ledger_path), "attempt_id": parent_attempt_id,
            "same_parent_ledger": True, "ledger_reset": False, "no_new_data_root": True,
            "storage_policy": str(resource_info["limits"].get("storage_policy", "")),
            "deadline_utc": str(resource_info["live"].get("deadline_utc", "")),
            "home_path": str(resource_info["home"]),
            "home_min_free_bytes": int(resource_info["limits"].get("home_min_free_bytes", 0)),
            "external_filesystem": str(external), "reservation_id": reservation_id,
            "charge_id": charge_id, "allow_missing_parent": bool(allow_missing_parent),
        },
        "storage_scope": {
            "external_filesystem": str(external), "supervisor_output_root": str(output_root),
            "home_receipt_path": str(receipt), "home_receipt_bytes": int(home_receipt_bytes),
            "external_reservation_bytes": int(external_bytes),
            "external_min_free_bytes": 1, "home_min_free_bytes": int(resource_info["limits"].get("home_min_free_bytes", 0)),
            "two_filesystem_charge_required": True, "existing_result_bytes_not_recharged": True,
        },
        "execution": {
            "max_wall_seconds": wall, "cpu_reservation_seconds": wall,
            "child_cleanup_grace_seconds": CHILD_GRACE_SECONDS,
            "entry_clock": "before metadata validation/reservation",
            "reservation_order": "same-parent reservation before V16 result content SHA",
            "python_executable": str(python), "preserve_literal_argv0": True,
            "command": [str(python), "-B", "-I", str(TE_SCRIPT), "run"],
            "closed_command": [str(python), "-B", "-I", str(TE_SCRIPT), "run",
                               "--request", str(typed_path), "--parent-pid", "<parent_pid>"],
            "original_path_fallback": "FORBIDDEN", "read_hdf5_or_bi4": False,
            "raw_opened": False, "model_invoked": False, "cfd_invoked": False,
            "strace": {"path": str(STRACE), "sha256": sha256_file(STRACE),
                       "options": list(STRACE_OPTIONS), "trace_path": str(trace)},
            "thread_environment": dict(THREAD_ENV),
            "execution_scope": "typed V16 JSON result + V8 proof/evaluator JSON only",
        },
        "static_bindings": [_static(path, role) for path, role in _binding_paths()] + [
            _static(typed_path, "typed_evaluator_request"),
            _static(parent_path, "parent_v3_request"),
        ],
        "model_invoked": False, "cfd_invoked": False, "raw_opened": False,
        "hdf5_opened": False, "qualification": dict(UNKNOWN),
        "accounting": {"owner": "existing DS-DATA-02 parent ledger", "reservation_id": reservation_id,
                       "charge_id": charge_id, "same_parent_ledger": True, "idempotent": True,
                       "allow_missing_parent": bool(allow_missing_parent),
                       "existing_product_bytes_not_recharged": True},
        "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                             "portable_cold_replay_credit": "NOT_CLAIMED",
                             "scientific_qualification": "UNKNOWN"},
        "limitations": [
            "This request validates an existing typed-only V16 result; it has no raw BI4/HDF5 input.",
            "The V16 result content hash is deferred until after reservation and is charged to this child.",
            "The fresh V8 proof must already bind this exact result; no historical proof is accepted.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    path = _write_new(output, request)
    return {"status": request["status"], "request": str(path), "sha256": request["sha256"],
            "typed_request_sha256": sha256_file(typed_path), "external_bytes": int(external_bytes),
            "home_receipt_bytes": int(home_receipt_bytes), "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    request_path = _file(path, "typed-only parent request")
    request = _json(request_path, "typed-only parent request")
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise TypedParentError("typed-only parent request is not ready")
    if request.get("sha256") != canonical_sha(request):
        raise TypedParentError("typed-only parent request canonical SHA differs")
    if request.get("role") != "DEVELOPMENT" or request.get("product_mode") != "TYPED_ONLY_LABELS":
        raise TypedParentError("parent request product mode differs")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False:
        raise TypedParentError("parent request must remain UNKNOWN/model-free")
    worktree_root = Path(str(request.get("worktree_root", ""))).expanduser().resolve()
    if not worktree_root.is_dir():
        raise TypedParentError("parent worktree root is missing")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    typed_item = request.get("typed_request")
    if not all(isinstance(value, Mapping) for value in (parent, storage, execution, typed_item)):
        raise TypedParentError("typed-only parent bindings are incomplete")
    typed_path = _file(typed_item.get("path"), "typed evaluator request")
    if typed_item.get("sha256") != sha256_file(typed_path):
        raise TypedParentError("typed evaluator request SHA differs")
    typed = _load_typed_request(typed_path)
    ledger = _file(parent.get("ledger_path"), "parent ledger")
    live = _json(ledger, "parent ledger", max_bytes=128 * 1024 * 1024)
    limits = live.get("limits")
    if not isinstance(limits, Mapping):
        raise TypedParentError("live ledger limits are missing")
    if str(parent.get("storage_policy")) != str(limits.get("storage_policy")):
        raise TypedParentError("live storage policy differs")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise TypedParentError("live Home floor differs")
    if str(parent.get("deadline_utc", "")) != str(live.get("deadline_utc", "")):
        raise TypedParentError("parent deadline differs")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if not external.is_dir():
        raise TypedParentError("external filesystem is missing")
    output_root = Path(str(storage.get("supervisor_output_root", ""))).expanduser().resolve()
    if output_root.exists() or not _under(output_root, external) or output_root == external:
        raise TypedParentError("typed-only output root is not a fresh external child")
    receipt = Path(str(storage.get("home_receipt_path", ""))).expanduser().resolve()
    if receipt.exists():
        raise TypedParentError("typed-only Home receipt already exists")
    trace = Path(str(execution.get("strace", {}).get("trace_path", ""))).expanduser().resolve()
    if trace.exists() or not _under(trace, output_root):
        raise TypedParentError("typed-only trace path is not fresh/output-bound")
    if execution.get("strace", {}).get("options") != STRACE_OPTIONS:
        raise TypedParentError("typed-only strace profile differs")
    if execution.get("thread_environment") != THREAD_ENV:
        raise TypedParentError("typed-only thread environment differs")
    python = _python_literal(execution.get("python_executable"))
    if str(python) != str(execution.get("command", [None])[0]):
        raise TypedParentError("typed-only literal Python command differs")
    py_binding = request.get("python_binding")
    if not isinstance(py_binding, Mapping) or str(py_binding.get("literal_invocation_path")) != str(python):
        raise TypedParentError("literal Python binding is missing or changed")
    py_info = _stat(python, "python executable")
    if py_info["bytes"] != int(py_binding.get("bytes", -1)) or py_info["mtime_ns"] != int(py_binding.get("mtime_ns", -1)):
        raise TypedParentError("literal Python stat differs")
    if _sha(py_binding.get("sha256"), "python executable SHA") != sha256_file(python):
        raise TypedParentError("literal Python content differs")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise TypedParentError("typed-only max wall is invalid")
    if float(execution.get("cpu_reservation_seconds", 0.0) or 0.0) != max_wall:
        raise TypedParentError("typed-only CPU reservation differs")
    if float(execution.get("child_cleanup_grace_seconds", 0.0) or 0.0) < 20.0:
        raise TypedParentError("typed-only cleanup grace is too short")
    external_est = int(storage.get("external_reservation_bytes", 0) or 0)
    home_est = int(storage.get("home_receipt_bytes", 0) or 0)
    if external_est <= 0 or home_est <= 0:
        raise TypedParentError("typed-only storage reservation is invalid")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise TypedParentError("typed-only static bindings are missing")
    for item in bindings:
        if not isinstance(item, Mapping):
            raise TypedParentError("typed-only static binding is malformed")
        bound = _file(item.get("path"), str(item.get("role", "static")))
        info = _stat(bound, str(item.get("role", "static")))
        if info["bytes"] != int(item.get("bytes", -1)):
            raise TypedParentError(f"static byte stat differs: {bound}")
        if verify_static_content and _sha(item.get("sha256"), "static SHA") != sha256_file(bound):
            raise TypedParentError(f"static content SHA differs: {bound}")
    # Keep the result in a separate binding so metadata validation never reads
    # its contents.  The child does the full SHA after reservation.
    result = typed["result"]
    result_path = _file(result["path"], "typed V16 result")
    if _stat(result_path, "typed V16 result")["bytes"] != int(result["bytes"]):
        raise TypedParentError("typed V16 result changed before parent launch")
    return {"path": request_path, "request": request, "typed": typed,
            "ledger": ledger, "limits": dict(limits), "external": external,
            "output_root": output_root, "receipt": receipt, "trace_path": trace,
            "runtime_path": _file(next((x["path"] for x in bindings if x.get("role") == "shared_runtime_v6"), None), "runtime v6"),
            "max_wall": max_wall, "cleanup_grace": float(execution["child_cleanup_grace_seconds"]),
            "external_estimate": external_est, "home_estimate": home_est,
            "parent_attempt_id": str(parent.get("attempt_id", "")),
            "reservation_id": str(parent.get("reservation_id", "")),
            "charge_id": str(parent.get("charge_id", "")),
            "allow_missing_parent": bool(parent.get("allow_missing_parent", False)),
            "python": python, "worktree_root": worktree_root,
            "python_binding": dict(py_binding)}


def _bound_for_parent(bound: Mapping[str, Any]) -> dict[str, Any]:
    request = bound["request"]
    return {"path": bound["path"], "request": request, "ledger": bound["ledger"],
            "external": bound["external"], "output_root": bound["output_root"],
            "receipt": bound["receipt"], "executor_path": request["typed_request"]["path"],
            "executor": {"source_entries": [], "fresh_roots": {}},
            "runtime_path": bound["runtime_path"], "runtime_sha": sha256_file(bound["runtime_path"]),
            "max_wall": bound["max_wall"], "cleanup_grace": bound["cleanup_grace"],
            "external_estimate": bound["external_estimate"], "home_estimate": bound["home_estimate"],
            "limits": bound["limits"], "parent_attempt_id": bound["parent_attempt_id"],
            "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
            "allow_missing_parent": bound["allow_missing_parent"]}


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise TypedParentError(f"symlink output is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _trace_bytes(prefix: Path) -> int:
    values = [prefix] if prefix.exists() else []
    values += list(prefix.parent.glob(prefix.name + ".*"))
    seen: set[Path] = set()
    total = 0
    for item in values:
        item = item.resolve()
        if item in seen or item.is_symlink() or not item.is_file():
            continue
        seen.add(item)
        total += int(item.stat().st_size)
    return total


def _install(parent_pid: int, max_wall: float) -> Mapping[int, Any]:
    if os.getppid() != int(parent_pid):
        raise ParentCancelled("typed-only parent is not the direct parent")
    PARENT._pdeath(int(parent_pid))
    old = {signal.SIGALRM: signal.getsignal(signal.SIGALRM),
           signal.SIGTERM: signal.getsignal(signal.SIGTERM),
           signal.SIGINT: signal.getsignal(signal.SIGINT)}
    def alarm(_signum: int, _frame: Any) -> None:
        raise ParentDeadline("typed-only parent entry-to-child deadline exceeded")
    def cancel(signum: int, _frame: Any) -> None:
        raise ParentCancelled(f"typed-only parent cancelled by signal {signum}")
    signal.signal(signal.SIGALRM, alarm)
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, max_wall))
    return old


def _restore(old: Mapping[int, Any] | None) -> None:
    if old is None:
        return
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in old.items():
        signal.signal(signum, handler)


def _child_command(bound: Mapping[str, Any], parent_pid: int) -> list[str]:
    request = bound["request"]
    typed_path = Path(str(request["typed_request"]["path"])).expanduser().resolve()
    output = bound["output_root"] / "typed-only-evaluator-report.json"
    if output.exists():
        raise TypedParentError("typed-only child output already exists")
    tracer = Path(str(request["execution"]["strace"]["path"])).expanduser()
    if tracer.resolve() != STRACE.resolve() or not tracer.is_file():
        raise TypedParentError("bound strace executable differs")
    return [str(tracer), *STRACE_OPTIONS, "-o", str(bound["trace_path"]), "--",
            str(bound["python"]), "-B", "-I", str(TE_SCRIPT), "run",
            "--request", str(typed_path), "--output", str(output),
            "--parent-pid", str(parent_pid), "--max-wall-seconds", str(float(bound["max_wall"]))]


def _last_json(path: Path) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _report_size_fixed_point(report: dict[str, Any]) -> int:
    return PARENT._report_size_fixed_point(report)


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    old: Mapping[int, Any] | None = None
    reservation_applied = False
    child: subprocess.Popen[Any] | None = None
    cleanup: dict[str, Any] = {}
    bound: dict[str, Any] | None = None
    parent_bound: dict[str, Any] | None = None
    before_bytes = 0
    status = "FAILED_TYPED_ONLY_EVALUATOR_PARENT"
    error: str | None = None
    child_returncode: int | None = None
    child_result: dict[str, Any] | None = None
    if io_slot_approved:
        raw = _json(path, "typed-only parent request")
        max_wall = float(raw.get("execution", {}).get("max_wall_seconds", 0.0) or 0.0)
        if parent_pid is None or int(parent_pid) <= 1:
            raise ParentCancelled("actual typed-only run requires parent PID")
        old = _install(int(parent_pid), max_wall)
    try:
        bound = _validate_request(path, verify_static_content=False)
        if not io_slot_approved:
            return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                    "metadata_only": True, "ledger_mutated": False,
                    "hdf5_or_bi4_read": False, "raw_opened": False,
                    "qualification": dict(UNKNOWN)}
        parent_bound = _bound_for_parent(bound)
        PARENT._reserve(parent_bound)
        reservation_applied = True
        # Static source/code hashes are small.  The 62 MB V16 content remains
        # the child responsibility and is not read by this preflight.
        _validate_request(path, verify_static_content=True)
        bound["output_root"].mkdir(parents=True, exist_ok=False)
        before_bytes = _tree_bytes(bound["output_root"])
        stdout_path = bound["output_root"] / "typed-only-parent.stdout.log"
        stderr_path = bound["output_root"] / "typed-only-parent.stderr.log"
        command = _child_command(bound, os.getpid())
        env = os.environ.copy(); env.update(THREAD_ENV)
        wrapper_pid = os.getpid()
        with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open("x", encoding="utf-8") as stderr:
            child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parent), stdout=stdout, stderr=stderr,
                                     start_new_session=True,
                                     preexec_fn=lambda pid=wrapper_pid: PARENT._pdeath(pid), env=env)
            try:
                remaining = float(bound["max_wall"]) - (time.monotonic() - entry_wall)
                child.wait(timeout=max(0.1, remaining))
            except subprocess.TimeoutExpired as exc:
                cleanup = PARENT._stop_group(child, bound["cleanup_grace"])
                raise ParentDeadline("typed-only evaluator exceeded parent wall") from exc
        child_returncode = child.returncode
        child_result = _last_json(stdout_path)
        if child_returncode != 0:
            raise TypedParentError(f"typed-only evaluator returned {child_returncode}: {stderr_path}")
        if not isinstance(child_result, Mapping) or child_result.get("status") != "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V1":
            raise TypedParentError("typed-only evaluator did not report its exact PASS status")
        status = "COMPLETED_PARENT_TYPED_ONLY_OPERATOR_UNKNOWN"
    except (ParentDeadline, ParentCancelled) as exc:
        error = str(exc)
        status = "FAILED_TYPED_ONLY_EVALUATOR_CANCELLED" if isinstance(exc, ParentCancelled) else "FAILED_TYPED_ONLY_EVALUATOR_DEADLINE"
        if child is not None:
            cleanup = PARENT._stop_group(child, bound["cleanup_grace"] if bound else CHILD_GRACE_SECONDS)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        if child is not None:
            cleanup = PARENT._stop_group(child, bound["cleanup_grace"] if bound else CHILD_GRACE_SECONDS)
    finally:
        _restore(old)

    if bound is None or parent_bound is None:
        return {"schema": REPORT_SCHEMA, "status": status, "error": error,
                "reservation_applied": reservation_applied, "ledger_mutated": False,
                "hdf5_or_bi4_read": False, "raw_opened": False,
                "qualification": dict(UNKNOWN)}
    try:
        external_bytes = _tree_bytes(bound["output_root"]) if bound["output_root"].exists() else 0
        trace_bytes = _trace_bytes(bound["trace_path"])
        report: dict[str, Any] = {
            "schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(bound["path"]), "sha256": sha256_file(bound["path"])},
            "typed_only_product": {
                "request_path": str(bound["typed"]["request"].get("result", {}).get("path")),
                "result_sha256": bound["typed"]["request"].get("result", {}).get("sha256"),
                "content_sha_verified_by_child": bool(status.startswith("COMPLETED")),
                "raw_to_typed_credit": "NOT_CLAIMED", "portable_cold_replay_credit": "NOT_CLAIMED",
            },
            "proof": bound["typed"]["request"].get("proof"),
            "executor": {"returncode": child_returncode, "result": child_result,
                          "cleanup": cleanup},
            "execution": {
                "entry_wall_seconds": time.monotonic() - entry_wall,
                "entry_cpu_core_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                "max_rss_observed_bytes": _rss_bytes(),
                "thread_environment": dict(THREAD_ENV),
                "git_at_launch": _git_at_launch(bound["worktree_root"]),
                "hard_wall_covers": ["metadata/stat preflight", "same-parent reservation", "typed V16 result hash/evaluator"],
                "finalization_scope": "local report/stat/ledger charge after child deadline; measured in receipt",
                "model_invoked": False, "cfd_invoked": False, "hdf5_or_bi4_content_read": False,
                "raw_opened": False, "original_path_fallback": "FORBIDDEN",
            },
            "filesystem": {"external_filesystem": str(bound["external"]),
                            "external_bytes": external_bytes, "trace_bytes": trace_bytes,
                            "home_receipt_path": str(bound["receipt"]),
                            "storage_filesystems": [str(bound["external"]), str(bound["limits"].get("home_path", "/home/jade"))]},
            "accounting": {"reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
                           "same_parent_ledger": True, "ledger_reset": False,
                           "allow_missing_parent": bound["allow_missing_parent"]},
            "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
            "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                                 "portable_cold_replay_credit": "NOT_CLAIMED",
                                 "scientific_qualification": "UNKNOWN"},
        }
        if error:
            report["error"] = error
        _report_size_fixed_point(report)
        _write_new(bound["receipt"], report)
        home_bytes = int(bound["receipt"].stat().st_size)
        cpu = max(0.0, _cpu_seconds() - entry_cpu)
        charge = PARENT._charge(parent_bound, status="completed" if status.startswith("COMPLETED") else "failed",
                                cpu_seconds=cpu, external_bytes=external_bytes, home_bytes=home_bytes,
                                trace_bytes=trace_bytes, copy_hash_bytes=0,
                                allow_missing_parent=bound["allow_missing_parent"])
        return {"schema": REPORT_SCHEMA, "status": status, "report_path": str(bound["receipt"]),
                "charge": charge, "external_bytes": external_bytes, "home_bytes": home_bytes,
                "trace_bytes": trace_bytes, "child_result": child_result,
                "raw_opened": False, "hdf5_or_bi4_read": False,
                "qualification": dict(UNKNOWN)}
    except BaseException as final_error:
        charge = None
        charge_error = None
        if reservation_applied:
            try:
                ext = _tree_bytes(bound["output_root"]) if bound["output_root"].exists() else 0
                trace = _trace_bytes(bound["trace_path"])
                home = int(bound["receipt"].stat().st_size) if bound["receipt"].exists() else 0
                charge = PARENT._charge(parent_bound, status="failed",
                                        cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                                        external_bytes=ext, home_bytes=home, trace_bytes=trace,
                                        copy_hash_bytes=0,
                                        allow_missing_parent=bound["allow_missing_parent"])
            except BaseException as charge_exc:
                charge_error = f"{type(charge_exc).__name__}: {charge_exc}"
                try:
                    PARENT._release(parent_bound)
                except BaseException as release_exc:
                    charge_error += f"; release failed: {release_exc}"
        return {"schema": REPORT_SCHEMA, "status": "FAILED_TYPED_ONLY_EVALUATOR_FINALIZATION",
                "error": f"{type(final_error).__name__}: {final_error}",
                "failure_charge": charge, "failure_charge_error": charge_error,
                "reservation_applied": reservation_applied, "hdf5_or_bi4_read": False,
                "raw_opened": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--typed-request", type=Path, required=True)
    build.add_argument("--parent-v3-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--external-filesystem", type=Path, required=True)
    build.add_argument("--ledger", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--supervisor-output-root", type=Path, required=True)
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--python-executable", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=300.0)
    build.add_argument("--external-bytes", type=int, default=256 * 1024 * 1024)
    build.add_argument("--home-receipt-bytes", type=int, default=256 * 1024)
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
            value = build_request(typed_request=args.typed_request, parent_v3_request=args.parent_v3_request,
                                  output=args.output, external_filesystem=args.external_filesystem,
                                  ledger=args.ledger, parent_attempt_id=args.parent_attempt_id,
                                  supervisor_output_root=args.supervisor_output_root,
                                  home_receipt=args.home_receipt, python_executable=args.python_executable,
                                  max_wall_seconds=args.max_wall_seconds, external_bytes=args.external_bytes,
                                  home_receipt_bytes=args.home_receipt_bytes,
                                  allow_missing_parent=not args.disallow_missing_parent)
        elif args.command == "preflight":
            _validate_request(args.request, verify_static_content=False)
            value = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                     "metadata_only": True, "ledger_mutated": False,
                     "hdf5_or_bi4_read": False, "raw_opened": False,
                     "qualification": dict(UNKNOWN)}
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    if str(value.get("status", "")).startswith("FAILED"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
