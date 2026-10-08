#!/usr/bin/env python3
"""Parent-owned JSON-only follow-on guard for ``v34 evaluate_existing``.

This is intentionally separate from the consumed v3 raw-to-label parent.  It
attaches to the already-created v34 fresh roots, requires a newly supplied
independent V16 proof whose hash matches the fresh V16 result, and then runs
only the copied no-model evaluator.  It never copies or opens the original
HDF5/BI4/raw source tree.  The same Stage2 ledger is used for a small
supplemental reservation and terminal charge; the existing product bytes are
measured as a baseline and are not charged a second time.
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
PARENT_V3_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
V34_DEFAULT = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v34.py"
RUNTIME_V6_DEFAULT = SCRIPT_DIR / "ds_data02_runtime_v6.py"
V21_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_external_supervisor_v21.py"
SCHEMA = "ds02.stage2.f2-portable-evaluator-parent-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-portable-evaluator-parent-report.v2"
EVALUATOR_SUCCESS_STATUS = "PASS_DEVELOPMENT_RAW_TYPED_LABEL_OPERATOR_TRIAL_V4"
STRACE_OPTIONS = ["-ff", "-e", "trace=%file,%process", "-s", "4096"]
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1
OLD_F2_PROOF_SHA256 = {
    # This is the prior native proof.  It is intentionally forbidden here;
    # the follow-on must receive a proof made against the fresh v3 product.
    "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47",
}


class EvaluatorParentError(RuntimeError):
    pass


class EvaluatorDeadline(EvaluatorParentError):
    pass


class EvaluatorCancelled(EvaluatorParentError):
    pass


def _load_parent_v3():
    spec = importlib.util.spec_from_file_location("ds02_bound_parent_v3", PARENT_V3_PATH)
    if spec is None or spec.loader is None:
        raise EvaluatorParentError(f"cannot load parent v3: {PARENT_V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT = _load_parent_v3()


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
        raise EvaluatorParentError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorParentError(f"JSON object required: {target}")
    return value


def canonical_sha(value: Mapping[str, Any]) -> str:
    return PARENT.canonical_sha(value)


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise EvaluatorParentError(f"{role} must be a lowercase SHA-256")
    return value


def _require_file(path: Any, role: str) -> Path:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise EvaluatorParentError(f"{role} path is missing")
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise EvaluatorParentError(f"{role} is missing: {target}")
    return target


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise EvaluatorParentError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _tree_bytes(root: Path) -> int:
    root = root.expanduser().resolve()
    total = 0
    if not root.is_dir():
        return 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise EvaluatorParentError(f"symlink output file is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _pdeath(parent_pid: int) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError("cannot install parent-death signal")
    if os.getppid() != int(parent_pid):
        os.kill(os.getpid(), signal.SIGTERM)


def _stop_group(proc: subprocess.Popen[Any], grace: float) -> dict[str, Any]:
    pgid = int(proc.pid)
    result = {"pgid": pgid, "sigterm_sent": False, "sigkill_sent": False,
              "reaped": False, "group_gone": False, "grace_seconds": float(grace)}

    def alive() -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    try:
        os.killpg(pgid, signal.SIGTERM)
        result["sigterm_sent"] = True
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + max(0.1, float(grace))
    while (proc.poll() is None or alive()) and time.monotonic() < deadline:
        time.sleep(0.02)
    if alive():
        try:
            os.killpg(pgid, signal.SIGKILL)
            result["sigkill_sent"] = True
        except (ProcessLookupError, PermissionError):
            pass
        kill_deadline = time.monotonic() + min(5.0, max(1.0, float(grace)))
        while alive() and time.monotonic() < kill_deadline:
            time.sleep(0.02)
    try:
        proc.wait(timeout=max(1.0, float(grace)))
        result["reaped"] = True
    except subprocess.TimeoutExpired:
        pass
    result["group_gone"] = not alive()
    return result


def _install_handlers(max_wall: float):
    previous = {signal.SIGALRM: signal.getsignal(signal.SIGALRM),
                signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}

    def deadline(_signum, _frame):
        raise EvaluatorDeadline("evaluator parent entry-to-terminal deadline exceeded")

    def cancelled(signum, _frame):
        raise EvaluatorCancelled(f"evaluator parent cancelled by signal {signum}")

    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, float(max_wall)))
    return previous


def _restore_handlers(previous: Mapping[int, Any]) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _reset_timer_to_entry_deadline(max_wall: float, entry_wall: float) -> float:
    """Reset the alarm to the remaining entry-to-terminal budget."""
    remaining = float(max_wall) - (time.monotonic() - float(entry_wall))
    if remaining <= 0:
        raise EvaluatorDeadline("evaluator entry budget expired during validation")
    signal.setitimer(signal.ITIMER_REAL, remaining)
    return remaining


def _trace_bytes(prefix: Path) -> int:
    prefix = prefix.expanduser().resolve()
    candidates = ([prefix] if prefix.exists() else []) + list(prefix.parent.glob(prefix.name + ".*"))
    total = 0
    seen: set[Path] = set()
    for item in candidates:
        item = item.resolve()
        if item in seen or item.is_symlink() or not item.is_file():
            continue
        seen.add(item)
        total += int(item.stat().st_size)
    return total


def _git_at_launch(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
        return {"root": str(root), "head": head, "capture_status": "PASS"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"root": str(root), "head": None, "capture_status": "FAILED",
                "error": f"{type(error).__name__}: {error}"}


def _proof_v16_sha(proof: Mapping[str, Any]) -> str | None:
    labels = proof.get("labels")
    if isinstance(labels, Mapping) and isinstance(labels.get("v16_sha256"), str):
        return str(labels["v16_sha256"])
    for key in ("v16_sha256", "fresh_v16_sha256"):
        if isinstance(proof.get(key), str):
            return str(proof[key])
    return None


def _validate_fresh_product(request: Mapping[str, Any], proof_path: Path,
                            *, verify_result_content: bool) -> dict[str, Any]:
    source = _require_file(request["source_request"]["path"], "v34 source request")
    if sha256_file(source) != request["source_request"]["sha256"]:
        raise EvaluatorParentError("v34 source request SHA differs")
    v34 = load_json(source)
    if v34.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise EvaluatorParentError("source request is not v34")
    if v34.get("execution", {}).get("original_path_fallback") != "FORBIDDEN":
        raise EvaluatorParentError("v34 source permits original-path fallback")
    roots = v34.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise EvaluatorParentError("v34 fresh roots are missing")
    executor_report_path = _require_file(
        Path(str(roots.get("output_root"))) / "portable-executor-report-v34.json",
        "fresh v34 executor report")
    output_root = executor_report_path.parent
    target_root = Path(str(roots.get("target_root"))).expanduser().resolve()
    if not target_root.is_dir() or not output_root.is_dir():
        raise EvaluatorParentError("fresh v34 roots are not complete")
    executor_report = load_json(executor_report_path)
    if executor_report.get("original_path_fallback") != "FORBIDDEN":
        raise EvaluatorParentError("fresh executor report permits original-path fallback")
    raw_item = executor_report.get("stages", {}).get("raw_to_typed_to_label", {})
    raw_report_path = _require_file(raw_item.get("report"), "fresh raw-to-label report")
    raw_report = load_json(raw_report_path)
    result_item = raw_report.get("typed_to_label", {}).get("v16_forward", {})
    result_path = _require_file(result_item.get("result") if isinstance(result_item, Mapping) else None,
                                "fresh v16 result")
    if not (result_path == result_path.resolve() and
            (result_path == output_root or output_root in result_path.parents or target_root in result_path.parents)):
        raise EvaluatorParentError("fresh v16 result is outside the bound product roots")
    proof_sha = sha256_file(proof_path)
    if proof_sha in OLD_F2_PROOF_SHA256 or proof_sha == request["proof"].get("forbidden_sha256"):
        raise EvaluatorParentError("historical V16 proof is forbidden")
    proof = load_json(proof_path)
    qualification = proof.get("qualification")
    if isinstance(qualification, Mapping) and qualification.get("QE") not in {None, "UNKNOWN"}:
        raise EvaluatorParentError("fresh proof must remain development/UNKNOWN")
    proof_v16 = _proof_v16_sha(proof)
    if proof_v16 is None or len(proof_v16) != 64 or any(c not in HEX64 for c in proof_v16):
        raise EvaluatorParentError("fresh proof has no valid V16 result SHA")
    # The metadata pass checks the result path and stat only.  The potentially
    # large result digest is deliberately deferred until after the same-parent
    # reservation, where its CPU/I/O cost is inside the measured phase.
    fresh_v16 = sha256_file(result_path) if verify_result_content else None
    if verify_result_content and proof_v16 != fresh_v16:
        raise EvaluatorParentError("fresh proof V16 hash does not match the bound product")
    return {"v34": v34, "output_root": output_root, "target_root": target_root,
            "executor_report": executor_report_path, "raw_report": raw_report_path,
            "result": result_path, "result_sha256": fresh_v16 or proof_v16,
            "result_sha_verified": bool(verify_result_content), "proof": proof,
            "proof_sha256": proof_sha}


def build_request(*, v34_request: Path | str, proof: Path | str,
                  provenance_sidecar: Path | str, output: Path | str,
                  parent_v3_request: Path | str,
                  home_report: Path | str | None = None,
                  max_wall_seconds: float = 300.0) -> dict[str, Any]:
    v34_path = _require_file(v34_request, "v34 source request")
    v34 = load_json(v34_path)
    if v34.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise EvaluatorParentError("v34 source request schema differs")
    proof_path = _require_file(proof, "fresh V16 proof")
    proof_sha = sha256_file(proof_path)
    if proof_sha in OLD_F2_PROOF_SHA256:
        raise EvaluatorParentError("historical V16 proof cannot build a follow-on request")
    sidecar = _require_file(provenance_sidecar, "transitive provenance sidecar")
    parent_request = _require_file(parent_v3_request, "parent v3 request")
    parent_value = load_json(parent_request)
    if parent_value.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise EvaluatorParentError("parent v3 request schema differs")
    roots = v34.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise EvaluatorParentError("v34 fresh roots are missing")
    external = Path(str(parent_value["storage_scope"]["external_filesystem"])).expanduser().resolve()
    output_root = Path(str(roots["output_root"])).expanduser().resolve()
    trace_path = output_root / "evaluator-parent-v2-os-trace"
    receipt = Path(home_report or (SCRIPT_DIR.parent /
                                   "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
                                   "f2-s1-portable-evaluator-parent-report-v2-049.json")).expanduser().resolve()
    request: dict[str, Any] = {
        "schema": SCHEMA, "status": "READY_FOR_FRESH_V16_PROOF",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": v34.get("case_id"),
        "source_request": {"path": str(v34_path), "sha256": sha256_file(v34_path),
                            "schema": v34.get("schema"), "immutable": True},
        "parent_v3_request": {"path": str(parent_request), "sha256": sha256_file(parent_request),
                               "immutable": True},
        "proof": {"path": str(proof_path), "sha256": proof_sha,
                  "forbidden_sha256": next(iter(OLD_F2_PROOF_SHA256))},
        "provenance_sidecar": {"path": str(sidecar), "sha256": sha256_file(sidecar),
                                "immutable": True},
        "fresh_roots": {"target_root": str(roots["target_root"]),
                        "output_root": str(roots["output_root"]),
                        "existing_allowed": True},
        "parent_resource_binding": {
            "ledger_path": parent_value["parent_resource_binding"]["ledger_path"],
            "external_filesystem": str(external),
            "home_path": parent_value["parent_resource_binding"]["home_path"],
            "home_min_free_bytes": parent_value["parent_resource_binding"]["home_min_free_bytes"],
            "storage_policy": parent_value["parent_resource_binding"]["storage_policy"],
            "same_parent_ledger": True, "ledger_reset": False,
            "no_new_data_root": True, "allow_missing_parent": True,
            "attempt_id": "f2-s1-portable-evaluator-v2-049",
            "reservation_id": "f2-s1-portable-evaluator-v2-049::reservation",
            "charge_id": "f2-s1-portable-evaluator-v2-049::charge",
            "deadline_utc": parent_value["parent_resource_binding"]["deadline_utc"],
        },
        "storage_scope": {
            "external_filesystem": str(external),
            "external_reservation_bytes": 512 * 1024 * 1024,
            "external_min_free_bytes": 1,
            "home_receipt_bytes": 128 * 1024,
            "home_receipt_path": str(receipt),
            "output_trace_path": str(trace_path),
            "existing_product_bytes_not_recharged": True,
            "two_filesystem_charge_required": True,
        },
        "execution": {
            "max_wall_seconds": float(max_wall_seconds),
            "cpu_reservation_seconds": float(max_wall_seconds),
            "child_cleanup_grace_seconds": 25.0,
            "entry_clock": "before metadata/product/proof validation",
            "command": ["<literal-venv-python>", "-B", "-I", str(V34_DEFAULT), "evaluate",
                         "--request", str(v34_path), "--evaluator-proof", str(proof_path),
                         "--parent-pid", "<parent_pid>", "--max-wall-seconds", str(float(max_wall_seconds))],
            "original_path_fallback": "FORBIDDEN",
            "hdf5_or_bi4_content_read": False,
            "strace": {"path": "/usr/bin/strace", "sha256": sha256_file("/usr/bin/strace"),
                       "options": list(STRACE_OPTIONS), "trace_path": str(trace_path)},
            "thread_environment": dict(THREAD_ENV),
            "existing_fresh_roots": "accepted and required; no new product namespace",
        },
        "static_bindings": [
            {"role": "evaluator_parent_v2", "path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
            {"role": "parent_v3_guard", "path": str(PARENT_V3_PATH), "sha256": sha256_file(PARENT_V3_PATH)},
            {"role": "v34_evaluator_entry", "path": str(V34_DEFAULT), "sha256": sha256_file(V34_DEFAULT)},
            {"role": "shared_runtime_v6", "path": str(RUNTIME_V6_DEFAULT), "sha256": sha256_file(RUNTIME_V6_DEFAULT)},
            {"role": "shared_v21_accounting", "path": str(V21_PATH), "sha256": sha256_file(V21_PATH)},
            {"role": "os_strace", "path": "/usr/bin/strace", "sha256": sha256_file("/usr/bin/strace")},
        ],
        "model_invoked": False, "cfd_invoked": False, "hdf5_or_bi4_content_read": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "Requires a fresh proof whose V16 SHA matches the fresh v34 result; the prior F2 proof is forbidden.",
            "Existing fresh roots are consumed in place; their pre-existing bytes are not recharged.",
            "The evaluator is a DEVELOPMENT operator trial; QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    _write_new(output, request)
    return request


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    request_path = _require_file(path, "evaluator parent request")
    request = load_json(request_path)
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_FRESH_V16_PROOF":
        raise EvaluatorParentError("unsupported or non-ready evaluator parent request")
    if request.get("sha256") != canonical_sha(request):
        raise EvaluatorParentError("evaluator parent request canonical SHA differs")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False:
        raise EvaluatorParentError("evaluator parent must remain DEVELOPMENT/UNKNOWN/model-free")
    source = request.get("source_request")
    parent = request.get("parent_resource_binding")
    parent_v3 = request.get("parent_v3_request")
    storage = request.get("storage_scope")
    execution = request.get("execution")
    if not all(isinstance(x, Mapping) for x in (source, parent, parent_v3, storage, execution)):
        raise EvaluatorParentError("evaluator parent binding is incomplete")
    source_path = _require_file(source.get("path"), "v34 source request")
    if source.get("sha256") != sha256_file(source_path):
        raise EvaluatorParentError("v34 source request SHA differs")
    parent_v3_path = _require_file(parent_v3.get("path"), "parent v3 request")
    if parent_v3.get("sha256") != sha256_file(parent_v3_path):
        raise EvaluatorParentError("parent v3 request SHA differs")
    proof = request.get("proof")
    proof_path = _require_file(proof.get("path") if isinstance(proof, Mapping) else None, "fresh V16 proof")
    if proof.get("sha256") != sha256_file(proof_path):
        raise EvaluatorParentError("fresh proof SHA differs")
    if proof.get("sha256") in OLD_F2_PROOF_SHA256:
        raise EvaluatorParentError("historical proof is forbidden")
    sidecar = request.get("provenance_sidecar")
    sidecar_path = _require_file(sidecar.get("path") if isinstance(sidecar, Mapping) else None,
                                 "provenance sidecar")
    if sidecar.get("sha256") != sha256_file(sidecar_path):
        raise EvaluatorParentError("provenance sidecar SHA differs")
    ledger = _require_file(parent.get("ledger_path"), "parent ledger")
    external = Path(str(storage.get("external_filesystem", ""))).expanduser().resolve()
    if not external.is_dir():
        raise EvaluatorParentError("external filesystem is missing")
    output_root = Path(str(request["fresh_roots"]["output_root"])).expanduser().resolve()
    target_root = Path(str(request["fresh_roots"]["target_root"])).expanduser().resolve()
    if not output_root.is_dir() or not target_root.is_dir():
        raise EvaluatorParentError("fresh product roots are missing")
    trace_path = Path(str(execution.get("strace", {}).get("trace_path", ""))).expanduser().resolve()
    if trace_path.exists():
        raise EvaluatorParentError("evaluator trace destination already exists")
    if not (output_root == trace_path.parent or output_root in trace_path.parents):
        raise EvaluatorParentError("evaluator trace must be within existing output root")
    if execution.get("strace", {}).get("options") != STRACE_OPTIONS:
        raise EvaluatorParentError("evaluator strace profile differs")
    if execution.get("thread_environment") != THREAD_ENV:
        raise EvaluatorParentError("evaluator thread environment differs")
    max_wall = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise EvaluatorParentError("evaluator max wall is invalid")
    if float(execution.get("cpu_reservation_seconds", 0.0) or 0.0) != max_wall:
        raise EvaluatorParentError("evaluator CPU reservation must equal max wall")
    if float(execution.get("child_cleanup_grace_seconds", 0.0) or 0.0) < 20:
        raise EvaluatorParentError("evaluator cleanup grace is too short")
    limits = load_json(ledger).get("limits", {})
    if str(parent.get("storage_policy")) != str(limits.get("storage_policy")):
        raise EvaluatorParentError("evaluator storage policy differs from live ledger")
    if int(parent.get("home_min_free_bytes", -1)) != int(limits.get("home_min_free_bytes", -2)):
        raise EvaluatorParentError("evaluator Home floor differs from live ledger")
    for item in request.get("static_bindings", []):
        if not isinstance(item, Mapping):
            raise EvaluatorParentError("evaluator static binding is malformed")
        bound = _require_file(item.get("path"), str(item.get("role", "static")))
        if bound.stat().st_size != int(item.get("bytes", bound.stat().st_size)):
            raise EvaluatorParentError(f"evaluator static byte stat differs: {bound}")
        if verify_static_content and sha256_file(bound) != _require_sha(item.get("sha256"), "static SHA"):
            raise EvaluatorParentError(f"evaluator static SHA differs: {bound}")
    product = _validate_fresh_product(
        request, proof_path, verify_result_content=verify_static_content)
    return {"path": request_path, "request": request, "ledger": ledger,
            "external": external, "output_root": output_root, "target_root": target_root,
            "receipt": Path(str(storage["home_receipt_path"])).expanduser().resolve(),
            "trace_path": trace_path, "proof": proof_path, "product": product,
            "runtime_path": RUNTIME_V6_DEFAULT, "runtime_sha": sha256_file(RUNTIME_V6_DEFAULT),
            "max_wall": max_wall, "cleanup_grace": float(execution["child_cleanup_grace_seconds"]),
            "external_estimate": int(storage["external_reservation_bytes"]),
            "home_estimate": int(storage["home_receipt_bytes"]), "limits": limits,
            "parent_attempt_id": str(parent["attempt_id"]),
            "reservation_id": str(parent["reservation_id"]), "charge_id": str(parent["charge_id"]),
            "allow_missing_parent": bool(parent.get("allow_missing_parent", False))}


def _bound_for_parent(request_path: Path, bound: Mapping[str, Any]) -> dict[str, Any]:
    request = bound["request"]
    return {"path": request_path, "request": request, "ledger": bound["ledger"],
            "external": bound["external"], "output_root": bound["output_root"],
            "receipt": bound["receipt"], "executor_path": request["source_request"]["path"],
            "executor": {"source_entries": [], "fresh_roots": {}},
            "runtime_path": bound["runtime_path"], "runtime_sha": bound["runtime_sha"],
            "max_wall": bound["max_wall"], "cleanup_grace": bound["cleanup_grace"],
            "external_estimate": bound["external_estimate"], "home_estimate": bound["home_estimate"],
            "limits": bound["limits"], "parent_attempt_id": bound["parent_attempt_id"],
            "reservation_id": bound["reservation_id"], "charge_id": bound["charge_id"],
            "allow_missing_parent": bound["allow_missing_parent"]}


def _child_command(bound: Mapping[str, Any], parent_pid: int) -> list[str]:
    request = bound["request"]
    v34 = Path(str(request["source_request"]["path"])).expanduser().resolve()
    proof = Path(str(request["proof"]["path"])).expanduser().resolve()
    python = next((item for item in bound["product"]["v34"].get("runtime_sources", [])
                   if isinstance(item, Mapping) and item.get("role") == "python_executable"), None)
    if not isinstance(python, Mapping):
        raise EvaluatorParentError("v34 python binding is missing")
    invocation = python.get("invocation_path") or python.get("path")
    if not isinstance(invocation, (str, os.PathLike)) or not Path(invocation).expanduser().is_file():
        raise EvaluatorParentError("literal venv Python invocation is missing")
    command = [str(Path(invocation).expanduser()), "-B", "-I", str(V34_DEFAULT), "evaluate",
               "--request", str(v34), "--evaluator-proof", str(proof),
               "--parent-pid", str(parent_pid), "--max-wall-seconds", str(float(bound["max_wall"]))]
    tracer = Path(str(request["execution"]["strace"]["path"])).expanduser()
    if not tracer.is_file():
        raise EvaluatorParentError("strace executable is missing")
    target = bound["trace_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    return [str(tracer), *STRACE_OPTIONS, "-o", str(target), "--"] + command


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None,
        max_wall_seconds: float | None = None) -> dict[str, Any]:
    """Run the evaluator with the whole validation/digest phase supervised.

    The timer is installed before the request JSON is read.  A metadata pass
    establishes the product paths and stat baseline, then the reservation is
    made, and only then are static bindings and the potentially large V16
    result content-hashed.  This ordering is part of the accounting contract.
    """
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    previous = None
    bound: dict[str, Any] | None = None
    parent_bound: dict[str, Any] | None = None
    reservation_applied = False
    child: subprocess.Popen[Any] | None = None
    cleanup: dict[str, Any] = {}
    baseline_bytes: int | None = None
    launch_git: dict[str, Any] = {"capture_status": "NOT_CAPTURED"}
    max_wall_hint = float(max_wall_seconds) if max_wall_seconds is not None else 300.0
    if not math.isfinite(max_wall_hint) or max_wall_hint <= 0:
        raise EvaluatorParentError("CLI max wall is invalid")
    if io_slot_approved:
        if parent_pid is None or int(parent_pid) <= 1 or os.getppid() != int(parent_pid):
            raise EvaluatorCancelled("evaluator parent guard is not the direct parent")
        _pdeath(int(parent_pid))
        # This alarm covers request loading and all metadata validation.  It is
        # reset below to the request's exact budget after the request is read.
        previous = _install_handlers(max_wall_hint)
    try:
        if io_slot_approved:
            launch_git = _git_at_launch(SCRIPT_DIR.parent.parent)
        raw = load_json(request_file)
        raw_execution = raw.get("execution", {})
        requested_max = float(raw_execution.get("max_wall_seconds", 0.0) or 0.0)
        if not math.isfinite(requested_max) or requested_max <= 0:
            raise EvaluatorParentError("request max wall is invalid")
        if max_wall_seconds is not None and abs(requested_max - max_wall_hint) > 1e-9:
            raise EvaluatorParentError("CLI max wall differs from request max wall")
        if io_slot_approved:
            _reset_timer_to_entry_deadline(requested_max, entry_wall)
        bound = _validate_request(request_file, verify_static_content=False)
        if not io_slot_approved:
            return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                    "metadata_only": True, "hdf5_or_bi4_content_read": False,
                    "ledger_mutated": False, "qualification": dict(UNKNOWN)}

        # The baseline is taken before reservation and is never charged.  A
        # failure before this point cannot accidentally recharge the full
        # existing product tree.
        baseline_bytes = _tree_bytes(bound["output_root"])
        parent_bound = _bound_for_parent(request_file, bound)
        PARENT._reserve(parent_bound)
        reservation_applied = True

        # All declared static content, including the fresh V16 result, is
        # checked only after the reservation and inside the same deadline.
        bound = _validate_request(request_file, verify_static_content=True)
        if bound["output_root"] != parent_bound["output_root"]:
            raise EvaluatorParentError("product output root changed after reservation")
        if bound["external"] != parent_bound["external"]:
            raise EvaluatorParentError("external filesystem changed after reservation")

        status = "FAILED_EVALUATOR_PARENT"
        child_result: dict[str, Any] | None = None
        child_returncode: int | None = None
        command = _child_command(bound, os.getpid())
        env = os.environ.copy()
        env.update(THREAD_ENV)
        log = bound["output_root"] / "evaluator-parent-v2.stdout.log"
        err = bound["output_root"] / "evaluator-parent-v2.stderr.log"
        if log.exists() or err.exists():
            raise EvaluatorParentError("evaluator parent log already exists")
        with log.open("x", encoding="utf-8") as out, err.open("x", encoding="utf-8") as error_stream:
            wrapper_pid = os.getpid()
            child = subprocess.Popen(command, cwd=str(SCRIPT_DIR.parent), stdout=out,
                                     stderr=error_stream, start_new_session=True,
                                     preexec_fn=lambda pid=wrapper_pid: _pdeath(pid), env=env)
            try:
                remaining = max(0.1, requested_max - (time.monotonic() - entry_wall))
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                cleanup = _stop_group(child, bound["cleanup_grace"])
                raise EvaluatorDeadline("private evaluator exceeded parent deadline") from error
        child_returncode = child.returncode
        for line in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                child_result = dict(value)
                break
        if child_returncode != 0:
            raise EvaluatorParentError(f"private evaluator returned {child_returncode}")
        if not isinstance(child_result, Mapping) or child_result.get("status") != EVALUATOR_SUCCESS_STATUS:
            observed = child_result.get("status") if isinstance(child_result, Mapping) else None
            raise EvaluatorParentError(f"private evaluator did not report PASS status: {observed!r}")
        status = "COMPLETED_EVALUATOR_DEVELOPMENT_UNKNOWN"

        after_bytes = _tree_bytes(bound["output_root"])
        delta = max(0, after_bytes - int(baseline_bytes))
        trace_bytes = _trace_bytes(bound["trace_path"])
        report = {
            "schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "source_v34_request": {"path": str(bound["request"]["source_request"]["path"]),
                                    "sha256": bound["request"]["source_request"]["sha256"]},
            "fresh_product": {"output_root": str(bound["output_root"]),
                               "target_root": str(bound["target_root"]),
                               "v16_result_sha256": bound["product"]["result_sha256"],
                               "v16_result_sha_verified": bound["product"].get("result_sha_verified", False)},
            "independent_proof": {"path": str(bound["proof"]),
                                   "sha256": bound["product"]["proof_sha256"]},
            "executor": {"returncode": child_returncode, "result": child_result,
                          "cleanup": cleanup},
            "execution": {"entry_wall_seconds": time.monotonic() - entry_wall,
                           "entry_cpu_core_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                           "max_rss_observed_bytes": _rss_bytes(),
                           "git_at_launch": launch_git,
                           "thread_environment": dict(THREAD_ENV),
                           "hdf5_or_bi4_content_read": False,
                           "model_invoked": False, "cfd_invoked": False,
                           "timer_scope": "request-load-through-charge-finalization"},
            "filesystem": {"external_filesystem": str(bound["external"]),
                            "existing_product_bytes_before": int(baseline_bytes),
                            "new_evaluator_bytes": delta, "trace_bytes": trace_bytes,
                            "home_receipt_path": str(bound["receipt"]),
                            "storage_filesystems": [str(bound["external"]),
                                                     str(bound["limits"].get("home_path", "/home/jade"))],
                            "existing_product_not_recharged": True},
            "accounting": {"reservation_id": bound["reservation_id"],
                           "charge_id": bound["charge_id"],
                           "same_parent_ledger": True, "ledger_reset": False,
                           "cpu_charge_scope": "entry-through-terminal-charge",
                           "external_charge_scope": "new-output-tree-delta-only",
                           "trace_is_included_in_new_output_tree": True},
            "original_path_fallback": "FORBIDDEN", "qualification": dict(UNKNOWN),
        }
        PARENT._report_size_fixed_point(report)
        _write_new(bound["receipt"], report)
        home_bytes = int(bound["receipt"].stat().st_size)
        charge_cpu = max(0.0, _cpu_seconds() - entry_cpu)
        charge = PARENT._charge(parent_bound, status="completed", cpu_seconds=charge_cpu,
                                external_bytes=delta, home_bytes=home_bytes, trace_bytes=trace_bytes,
                                copy_hash_bytes=0, allow_missing_parent=bound["allow_missing_parent"])
        if previous is not None:
            _restore_handlers(previous)
            previous = None
        return {"schema": REPORT_SCHEMA, "status": status,
                "report_path": str(bound["receipt"]), "charge": charge,
                "new_evaluator_bytes": delta, "home_bytes": home_bytes,
                "trace_bytes": trace_bytes, "cpu_charge_core_seconds": charge_cpu,
                "hdf5_or_bi4_content_read": False, "model_invoked": False,
                "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    except BaseException as error:
        if child is not None and (child.poll() is None or cleanup.get("group_gone") is not True):
            cleanup = _stop_group(child, bound["cleanup_grace"] if bound is not None else 25.0)
        failure_charge: dict[str, Any] | None = None
        failure_charge_error: str | None = None
        if reservation_applied and bound is not None and parent_bound is not None:
            try:
                ext_bytes = 0
                if baseline_bytes is not None:
                    ext_bytes = max(0, _tree_bytes(bound["output_root"]) - int(baseline_bytes))
                trace_bytes = _trace_bytes(bound["trace_path"]) if bound["trace_path"].exists() else 0
                home_bytes = int(bound["receipt"].stat().st_size) if bound["receipt"].exists() else 0
                failure_charge = PARENT._charge(
                    parent_bound, status="failed",
                    cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                    external_bytes=ext_bytes, home_bytes=home_bytes,
                    trace_bytes=trace_bytes, copy_hash_bytes=0,
                    allow_missing_parent=bound["allow_missing_parent"])
            except BaseException as charge_error:
                failure_charge_error = f"{type(charge_error).__name__}: {charge_error}"
                try:
                    PARENT._release(parent_bound)
                except BaseException as release_error:
                    failure_charge_error += f"; release failed: {release_error}"
        if previous is not None:
            _restore_handlers(previous)
        return {"schema": REPORT_SCHEMA, "status": "FAILED_EVALUATOR_PARENT",
                "error": f"{type(error).__name__}: {error}",
                "reservation_applied": reservation_applied,
                "failure_charge": failure_charge,
                "failure_charge_error": failure_charge_error,
                "hdf5_or_bi4_content_read": False, "model_invoked": False,
                "cfd_invoked": False, "qualification": dict(UNKNOWN)}

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v34-request", type=Path, required=True)
    build.add_argument("--proof", type=Path, required=True)
    build.add_argument("--provenance-sidecar", type=Path, required=True)
    build.add_argument("--parent-v3-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--home-report", type=Path)
    build.add_argument("--max-wall-seconds", type=float, default=300.0)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(v34_request=args.v34_request, proof=args.proof,
                                  provenance_sidecar=args.provenance_sidecar,
                                  parent_v3_request=args.parent_v3_request,
                                  output=args.output, home_report=args.home_report,
                                  max_wall_seconds=args.max_wall_seconds)
        elif args.command == "preflight":
            value = _validate_request(args.request, verify_static_content=False)
            value = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                     "metadata_only": True, "hdf5_or_bi4_content_read": False,
                     "ledger_mutated": False, "qualification": dict(UNKNOWN)}
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid,
                        max_wall_seconds=args.max_wall_seconds)
    except (EvaluatorParentError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"portable evaluator parent v2: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
