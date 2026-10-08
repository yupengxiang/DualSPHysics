#!/usr/bin/env python3
"""V4 parent for the current-bound typed-only evaluator.

This version keeps the V2/V1 parent and the same Stage2 ledger owner, but
fixes three concrete failures in the consumed V2 path:

* the actual CURRENT336/frozen/proof content is verified only after the
  reservation (the old current-bound wrapper hashed it in preflight);
* the typed request is a plain request object, so report construction reads
  ``typed["result"]`` rather than a nonexistent ``typed["request"]``;
* the charge CPU is selected conservatively from both process rusage and the
  enclosing cgroup's ``cpu.stat`` delta.  This captures child/tracer CPU that
  can be absent from ``RUSAGE_CHILDREN`` after a managed-service boundary.

The traced child is a small direct-parent shim.  It keeps the evaluator's
strict parent check valid under ``strace`` without disabling ownership
checks.  No HDF5, BI4, or raw scientific payload is read by this module.
The V2/V3 requests, runners, and failed 061/066 receipts remain immutable.
"""
from __future__ import annotations

# Capture the cgroup/process baseline before importing the evaluator closure.
# The consumed V3 took its first snapshot inside ``run``; that omits Python
# bootstrap and module-import CPU in a managed service.  This raw helper uses
# only builtins and procfs so its own import overhead is not hidden behind a
# normal module import.
def _raw_bootstrap_cgroup_usage() -> float | None:
    try:
        with open("/proc/self/cgroup", "r", encoding="ascii") as stream:
            relative = next((line[3:].strip() for line in stream if line.startswith("0::")), None)
        if relative is None:
            return None
        with open("/sys/fs/cgroup" + relative + "/cpu.stat", "r", encoding="ascii") as stream:
            for line in stream:
                key, _, value = line.partition(" ")
                if key == "usage_usec":
                    return float(value.strip()) / 1_000_000.0
    except (OSError, ValueError, StopIteration):
        return None
    return None


def _raw_bootstrap_proc_ticks() -> int | None:
    try:
        with open("/proc/self/stat", "r", encoding="ascii") as stream:
            text = stream.read()
        tail = text[text.rfind(")") + 2:].split()
        return int(tail[11]) + int(tail[12])
    except (OSError, ValueError, IndexError):
        return None


_BOOTSTRAP_CGROUP_SECONDS = _raw_bootstrap_cgroup_usage()
_BOOTSTRAP_PROC_TICKS = _raw_bootstrap_proc_ticks()

import argparse
import copy
import importlib.util
import json
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
BASE_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v3_current_bound.py"
CHILD_SHIM = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_child_shim_v1.py"
CURRENT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_current_catalog_binding_v1.py"
EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v3_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-report.v4-current-bound"
FORWARD_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-v4-current-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
STRACE = Path("/usr/bin/strace")
STRACE_OPTIONS = ["-ff", "-e", "trace=%file,%process", "-s", "4096"]
THREAD_ENV = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}


class TypedParentV3CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV3CurrentError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load(BASE_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v3_current_bound_for_v4")
P2 = BASE.P2
P1 = P2.P1
CURRENT = BASE.CURRENT
PARENT = P1.PARENT
EVALUATOR = _load(EVALUATOR_SCRIPT, "ds02_bound_typed_only_evaluator_v3_current_bound_for_parent_v4")

# Keep the immutable V2 evaluator closure, while registering this forward
# module and its direct-parent shim as new static sources in V3 requests.
P1.SCRIPT = SCRIPT
P1.SCRIPT_DIR = SCRIPT_DIR
P1.TE_SCRIPT = EVALUATOR_SCRIPT
P1.TE_SCHEMA = EVALUATOR.REQUEST_SCHEMA
P1.TE = EVALUATOR
CHILD_PASS_STATUS = "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V3_DUAL_CURRENT"


def canonical_sha(value: Mapping[str, Any]) -> str:
    return P2.canonical_sha(value)


def _file(value: Any, role: str) -> Path:
    return P1._file(value, role)


def _json(path: Path | str, role: str, *, max_bytes: int = 32 * 1024 * 1024) -> dict[str, Any]:
    return P1._json(path, role, max_bytes=max_bytes)


def _sha_file(path: Path | str) -> str:
    return P1.sha256_file(path)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return P2._write_new(path, value)


def _stat_declared(path: Path, role: str, sha256: str) -> dict[str, Any]:
    """Declare a source using its known SHA without hashing it at build time."""
    info = P1._stat(path, role)
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise TypedParentV3CurrentError(f"{role} declared SHA is malformed")
    return {"role": role, "path": str(path), **info, "sha256": sha256,
            "content_hash_phase": "AFTER_PARENT_RESERVATION"}


def _sidecar_sources(sidecar: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    sidecar_value = CURRENT._json(sidecar, "CURRENT catalog binding sidecar")[1]
    current_item = sidecar_value.get("current_catalog")
    frozen_item = sidecar_value.get("frozen_v15_request")
    proof_item = sidecar_value.get("historical_v10_proof")
    if not all(isinstance(item, Mapping) for item in (current_item, frozen_item, proof_item)):
        raise TypedParentV3CurrentError("CURRENT sidecar source declarations are incomplete")
    current = _file(current_item.get("path"), "CURRENT336 source")
    frozen = _file(frozen_item.get("path"), "frozen V15 source")
    proof = _file(proof_item.get("path"), "historical V10 proof source")
    for item, path, role in ((current_item, current, "CURRENT336 source"),
                             (frozen_item, frozen, "frozen V15 source"),
                             (proof_item, proof, "historical V10 proof source")):
        if item.get("path") != str(path) or not isinstance(item.get("sha256"), str):
            raise TypedParentV3CurrentError(f"{role} sidecar declaration is malformed")
    return sidecar_value, current, frozen, proof


def build_forward_request(*, base_request: Path | str, current_binding: Path | str,
                          output: Path | str, parent_attempt_id: str,
                          supervisor_output_root: Path | str, home_receipt: Path | str,
                          max_wall_seconds: float | None = None,
                          trace_path: Path | str | None = None,
                          allow_missing_parent: bool | None = None) -> dict[str, Any]:
    """Create a new V3 request from an immutable V2 request.

    This builder reads only JSON/stat metadata.  In particular, the three
    scientific sources named by the CURRENT sidecar get declared SHA values;
    their bytes are verified by :func:`run` after the same-parent reservation.
    """
    base_path = _file(base_request, "V2 current-bound parent request")
    request = _json(base_path, "V2 current-bound parent request")
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TypedParentV3CurrentError("base V2 current-bound request schema/SHA differs")
    sidecar = _file(current_binding, "CURRENT catalog binding sidecar")
    sidecar_sha = _sha_file(sidecar)
    sidecar_value, current_path, frozen_path, proof_path = _sidecar_sources(sidecar)
    current_sha = str(sidecar_value["current_catalog"]["sha256"])
    frozen_sha = str(sidecar_value["frozen_v15_request"]["sha256"])
    proof_sha = str(sidecar_value["historical_v10_proof"]["sha256"])
    historical_catalog_sha = str(
        sidecar_value["historical_v10_proof"].get("declared_current_catalog_sha256", "")
    )
    for name, value in (("CURRENT336", current_sha), ("frozen V15", frozen_sha),
                        ("historical proof", proof_sha),
                        ("historical result CURRENT", historical_catalog_sha)):
        if len(value) != 64:
            raise TypedParentV3CurrentError(f"{name} declared SHA is malformed")

    value = copy.deepcopy(request)
    parent = value.get("parent_resource_binding")
    accounting = value.get("accounting")
    storage = value.get("storage_scope")
    execution = value.get("execution")
    if not all(isinstance(item, dict) for item in (parent, accounting, storage, execution)):
        raise TypedParentV3CurrentError("base V2 parent bindings are incomplete")
    attempt = str(parent_attempt_id)
    if not attempt:
        raise TypedParentV3CurrentError("parent_attempt_id is required")
    ext_root = Path(str(storage["external_filesystem"])).expanduser().resolve()
    output_root = Path(supervisor_output_root).expanduser().resolve()
    if output_root.exists() or output_root == ext_root:
        raise TypedParentV3CurrentError("V3 output root must be fresh")
    if not BASE.P2.P1._under(output_root, ext_root):
        raise TypedParentV3CurrentError("V3 output root must remain under external filesystem")
    receipt = Path(home_receipt).expanduser().resolve()
    if receipt.exists():
        raise TypedParentV3CurrentError("V3 Home receipt must be fresh")
    trace = (Path(trace_path).expanduser().resolve() if trace_path is not None
             else output_root / "typed-only-evaluator-v3-os-trace")
    if not BASE.P2.P1._under(trace, output_root):
        raise TypedParentV3CurrentError("V3 trace must remain under output root")
    old_wall = float(execution.get("max_wall_seconds", 300.0) or 0.0)
    wall = old_wall if max_wall_seconds is None else float(max_wall_seconds)
    if not (wall > 0):
        raise TypedParentV3CurrentError("max_wall_seconds must be positive")
    allow_missing = (bool(parent.get("allow_missing_parent")) if allow_missing_parent is None
                     else bool(allow_missing_parent))

    parent.update({
        "attempt_id": attempt,
        "reservation_id": attempt + "::typed-only-evaluator-v3-reservation",
        "charge_id": attempt + "::typed-only-evaluator-v3-charge",
        "allow_missing_parent": allow_missing,
    })
    accounting.update({
        "reservation_id": parent["reservation_id"],
        "charge_id": parent["charge_id"],
        "allow_missing_parent": allow_missing,
    })
    storage["supervisor_output_root"] = str(output_root)
    storage["home_receipt_path"] = str(receipt)
    execution.update({
        "max_wall_seconds": wall,
        "cpu_reservation_seconds": wall,
        "entry_clock": "before metadata validation/reservation",
        "reservation_order": "same-parent reservation before CURRENT/frozen/proof content SHA",
        "current_source_validation_phase": "AFTER_PARENT_RESERVATION",
        "pre_reservation_scientific_content_hash": False,
        "child_shim": {"path": str(CHILD_SHIM), "direct_parent_contract": "strace_process"},
        "strace": {"path": str(STRACE), "sha256": _sha_file(STRACE),
                   "options": list(STRACE_OPTIONS), "trace_path": str(trace)},
        "closed_command": [str(value["python_binding"]["literal_invocation_path"]), "-B", "-I",
                           str(CHILD_SHIM), "run", "--evaluator", str(P1.TE_SCRIPT),
                           "--request", str(value["typed_request"]["path"]),
                           "--parent-pid", "<strace_pid>"],
    })
    value["current_catalog_binding"] = {
        "path": str(sidecar), "sha256": sidecar_sha,
        "schema": CURRENT.SCHEMA, "content_read_during_build": False,
        "current_catalog_sha256": current_sha,
        "historical_result_current_catalog_sha256": historical_catalog_sha,
        "case_join_status": "DEFERRED_UNTIL_PARENT_RESERVATION",
    }
    existing = value.get("static_bindings")
    if not isinstance(existing, list):
        raise TypedParentV3CurrentError("base V2 static bindings are missing")
    replace_roles = {
        "typed_only_parent_v2", "typed_only_parent_v3_current_bound",
        "current_catalog_binding", "current_catalog_source",
        "frozen_v15_source", "historical_v10_proof_source",
        "typed_only_evaluator_child_shim_v1",
    }
    bindings = [item for item in existing
                if isinstance(item, Mapping) and item.get("role") not in replace_roles]
    bindings.extend([
        BASE.P2.P1._static(sidecar, "current_catalog_binding"),
        _stat_declared(current_path, "current_catalog_source", current_sha),
        _stat_declared(frozen_path, "frozen_v15_source", frozen_sha),
        _stat_declared(proof_path, "historical_v10_proof_source", proof_sha),
        BASE.P2.P1._static(CURRENT_SCRIPT, "current_catalog_binding_module"),
        BASE.P2.P1._static(SCRIPT, "typed_only_parent_v3_current_bound"),
        BASE.P2.P1._static(EVALUATOR_SCRIPT, "typed_only_evaluator_v3_current_bound"),
        BASE.P2.P1._static(CHILD_SHIM, "typed_only_evaluator_child_shim_v1"),
    ])
    value["static_bindings"] = bindings
    value["v4_current_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_request": {"path": str(base_path), "sha256": request["sha256"]},
        "current_binding": {"path": str(sidecar), "sha256": sidecar_sha},
        "actual_current_catalog_sha256": current_sha,
        "frozen_v15_sha256": frozen_sha,
        "historical_result_catalog_sha256": historical_catalog_sha,
        "same_parent_ledger": True, "new_ledger_owner": False,
        "scientific_source_validation": "AFTER_PARENT_RESERVATION",
        "original_path_fallback": "FORBIDDEN",
        "hdf5_or_bi4_content_read_during_build": False,
        "old_v2_failure_preserved": True,
        "dual_current_binding": {
            "actual_current_catalog_sha256": current_sha,
            "historical_result_current_catalog_sha256": historical_catalog_sha,
            "child_evaluator": "v3_current_bound",
            "historical_hash_is_runtime_result_provenance_only": True,
        },
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V4 is a forward development evaluator; QI/QN/QE remain UNKNOWN.",
        "The historical V10/V16 catalog alias remains provenance-only and is not relabeled as exact CURRENT.",
        "CURRENT/frozen/proof bytes are verified after same-parent reservation, not in build/preflight.",
    ]
    value["sha256"] = canonical_sha(value)
    target = _write_new(output, value)
    return {"status": value["status"], "schema": value["schema"],
            "request": str(target), "sha256": value["sha256"],
            "current_catalog_sha256": current_sha,
            "hdf5_or_bi4_read": False, "payload_read": False,
            "qualification": dict(UNKNOWN)}


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    # Deliberately do not call BASE._validate_request: that wrapper invokes
    # CURRENT.validate_binding before the parent reservation.  P1 validates
    # the request/static stats and, on the post-reservation call, all static
    # content.  CURRENT identity is checked by _current_after_reservation.
    return P1._validate_request(path, verify_static_content=verify_static_content)


def _current_after_reservation(bound: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    sidecar, info = BASE._current_item(bound["request"])
    if info.get("current_catalog_sha256") != bound["request"].get("current_catalog_binding", {}).get("current_catalog_sha256"):
        raise TypedParentV3CurrentError("post-reservation CURRENT SHA differs from request binding")
    return sidecar, info


def _child_command(bound: Mapping[str, Any], parent_pid: int) -> list[str]:
    request = bound["request"]
    typed_path = Path(str(request["typed_request"]["path"])).expanduser().resolve()
    output = bound["output_root"] / "typed-only-evaluator-report.json"
    if output.exists():
        raise TypedParentV3CurrentError("typed-only child output already exists")
    tracer = Path(str(request["execution"]["strace"]["path"])).expanduser()
    if tracer.resolve() != STRACE.resolve() or not tracer.is_file():
        raise TypedParentV3CurrentError("bound strace executable differs")
    return [str(tracer), *STRACE_OPTIONS, "-o", str(bound["trace_path"]), "--",
            str(bound["python"]), "-B", "-I", str(CHILD_SHIM), "run",
            "--evaluator", str(P1.TE_SCRIPT), "--request", str(typed_path),
            "--output", str(output), "--python", str(bound["python"]),
            "--max-wall-seconds", str(float(bound["max_wall"]))]


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


def _typed_product(typed: Mapping[str, Any], *, completed: bool,
                   typed_request_path: str) -> dict[str, Any]:
    """Build the report product binding from the plain typed request object.

    V1/V2's ``typed`` value is the request itself.  It has ``result`` and
    ``proof`` at its top level; it is not an envelope containing ``request``.
    Keeping this tiny adapter explicit prevents the consumed V2
    ``KeyError: 'request'`` finalization failure from returning with an
    unaccounted reservation.
    """
    result = typed.get("result", {}) if isinstance(typed, Mapping) else {}
    result_path = result.get("path")
    return {
        "request_path": str(typed_request_path),
        "result_path": str(result_path),
        "result_sha256": result.get("sha256"),
        "content_sha_verified_by_child": bool(completed),
        "raw_to_typed_credit": "NOT_CLAIMED",
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }


def _cgroup_cpu_stat_path() -> Path | None:
    try:
        entries = Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    relative = None
    for line in entries:
        if line.startswith("0::"):
            relative = line[3:].strip()
            break
    if relative is None:
        return None
    path = Path("/sys/fs/cgroup") / relative.lstrip("/") / "cpu.stat"
    return path if path.is_file() else None


def _cgroup_cpu_usage_seconds(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            key, _, value = line.partition(" ")
            if key == "usage_usec":
                return float(value.strip()) / 1_000_000.0
    except (OSError, ValueError):
        return None
    return None


def _cpu_snapshot() -> dict[str, Any]:
    cgroup_path = _cgroup_cpu_stat_path()
    return {"process_seconds": P1._cpu_seconds(),
            "children_seconds": float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime +
                                       resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime),
            "cgroup_cpu_stat_path": str(cgroup_path) if cgroup_path else None,
            "cgroup_usage_seconds": _cgroup_cpu_usage_seconds(cgroup_path)}


def _bootstrap_cpu_snapshot() -> dict[str, Any]:
    """Return the first executable-line baseline, before module imports."""
    ticks = _BOOTSTRAP_PROC_TICKS
    try:
        process = (float(ticks) / float(os.sysconf("SC_CLK_TCK"))) if ticks is not None else 0.0
    except (OSError, ValueError, TypeError):
        process = 0.0
    return {
        "process_seconds": process,
        "children_seconds": 0.0,
        "cgroup_cpu_stat_path": _cgroup_cpu_stat_path(),
        "cgroup_usage_seconds": _BOOTSTRAP_CGROUP_SECONDS,
        "capture_phase": "FIRST_SCRIPT_LINE_BEFORE_EVALUATOR_CLOSURE_IMPORT",
    }


def _cpu_delta(start: Mapping[str, Any], end: Mapping[str, Any]) -> dict[str, Any]:
    process = max(0.0, float(end.get("process_seconds", 0.0)) - float(start.get("process_seconds", 0.0)))
    children = max(0.0, float(end.get("children_seconds", 0.0)) - float(start.get("children_seconds", 0.0)))
    cg_start = start.get("cgroup_usage_seconds")
    cg_end = end.get("cgroup_usage_seconds")
    cgroup = None
    if isinstance(cg_start, (int, float)) and isinstance(cg_end, (int, float)):
        cgroup = max(0.0, float(cg_end) - float(cg_start))
    candidates = [process, children]
    if cgroup is not None:
        candidates.append(cgroup)
    return {"process_rusage_delta_seconds": process,
            "children_rusage_delta_seconds": children,
            "cgroup_usage_delta_seconds": cgroup,
            "charge_cpu_seconds": max(candidates),
            "selection": "max_process_children_cgroup",
            "cgroup_cpu_stat_path": end.get("cgroup_cpu_stat_path")}


def _run_fixed(path: Path | str, *, io_slot_approved: bool = False,
               parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _bootstrap_cpu_snapshot()
    old: Mapping[int, Any] | None = None
    reservation_applied = False
    child: subprocess.Popen[Any] | None = None
    cleanup: dict[str, Any] = {}
    bound: dict[str, Any] | None = None
    parent_bound: dict[str, Any] | None = None
    status = "FAILED_TYPED_ONLY_EVALUATOR_PARENT_V3"
    error: str | None = None
    child_returncode: int | None = None
    child_result: dict[str, Any] | None = None
    launch_git: dict[str, Any] | None = None
    if io_slot_approved:
        raw = _json(path, "typed-only V3 parent request")
        max_wall = float(raw.get("execution", {}).get("max_wall_seconds", 0.0) or 0.0)
        if parent_pid is None or int(parent_pid) <= 1:
            raise P1.ParentCancelled("actual typed-only V3 run requires parent PID")
        old = P1._install(int(parent_pid), max_wall)
    try:
        # This metadata path reads no CURRENT/frozen/proof content.  Their
        # static entries are only stat-checked until after _reserve.
        bound = _validate_request(path, verify_static_content=False)
        if not io_slot_approved:
            return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                    "metadata_only": True, "ledger_mutated": False,
                    "source_content_validation_phase": "AFTER_PARENT_RESERVATION",
                    "hdf5_or_bi4_read": False, "raw_opened": False,
                    "qualification": dict(UNKNOWN)}
        parent_bound = P1._bound_for_parent(bound)
        PARENT._reserve(parent_bound)
        reservation_applied = True
        # All scientific source bytes, including the actual CURRENT336 file,
        # are verified only after the same-parent reservation.
        bound = _validate_request(path, verify_static_content=True)
        sidecar, current_info = _current_after_reservation(bound)
        bound["current_binding_path"] = sidecar
        bound["current_binding_info"] = current_info
        bound["output_root"].mkdir(parents=True, exist_ok=False)
        stdout_path = bound["output_root"] / "typed-only-parent-v3.stdout.log"
        stderr_path = bound["output_root"] / "typed-only-parent-v3.stderr.log"
        command = _child_command(bound, os.getpid())
        launch_git = P1._git_at_launch(bound["worktree_root"])
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
                raise P1.ParentDeadline("typed-only V3 evaluator exceeded parent wall") from exc
        child_returncode = child.returncode
        child_result = _last_json(stdout_path)
        if child_returncode != 0:
            raise P1.TypedParentError(f"typed-only V3 evaluator returned {child_returncode}: {stderr_path}")
        if not isinstance(child_result, Mapping) or child_result.get("status") != CHILD_PASS_STATUS:
            raise P1.TypedParentError("typed-only V3 evaluator did not report its exact PASS status")
        status = "COMPLETED_PARENT_TYPED_ONLY_OPERATOR_UNKNOWN"
    except (P1.ParentDeadline, P1.ParentCancelled) as exc:
        error = str(exc)
        status = "FAILED_TYPED_ONLY_EVALUATOR_CANCELLED" if isinstance(exc, P1.ParentCancelled) else "FAILED_TYPED_ONLY_EVALUATOR_DEADLINE"
        if child is not None:
            cleanup = PARENT._stop_group(child, bound["cleanup_grace"] if bound else 25.0)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        if child is not None:
            cleanup = PARENT._stop_group(child, bound["cleanup_grace"] if bound else 25.0)
    finally:
        P1._restore(old)

    if bound is None or parent_bound is None:
        return {"schema": REPORT_SCHEMA, "status": status, "error": error,
                "reservation_applied": reservation_applied, "ledger_mutated": False,
                "hdf5_or_bi4_read": False, "raw_opened": False,
                "qualification": dict(UNKNOWN)}
    try:
        external_bytes = P1._tree_bytes(bound["output_root"]) if bound["output_root"].exists() else 0
        trace_bytes = P1._trace_bytes(bound["trace_path"])
        typed = bound["typed"]
        report: dict[str, Any] = {
            "schema": REPORT_SCHEMA, "status": status,
            "request": {"path": str(bound["path"]), "sha256": _sha_file(bound["path"])},
            "typed_only_product": _typed_product(
                typed, completed=status.startswith("COMPLETED"),
                typed_request_path=str(bound["request"]["typed_request"]["path"])),
            "proof": typed.get("proof") if isinstance(typed, Mapping) else None,
            "current_source_binding": {
                "phase": "AFTER_PARENT_RESERVATION",
                "sidecar": str(bound.get("current_binding_path", "")),
                "actual_current_catalog_sha256": bound.get("current_binding_info", {}).get("current_catalog_sha256"),
                "historical_result_current_catalog_sha256": bound.get("current_binding_info", {}).get("historical_result_current_catalog_sha256"),
            },
            "executor": {"returncode": child_returncode, "result": child_result,
                          "cleanup": cleanup},
            "execution": {
                "entry_wall_seconds": time.monotonic() - entry_wall,
                "entry_cpu_evidence": _cpu_delta(entry_cpu, _cpu_snapshot()),
                "cpu_baseline_capture": "FIRST_SCRIPT_LINE_BEFORE_EVALUATOR_CLOSURE_IMPORT",
                "max_rss_observed_bytes": P1._rss_bytes(),
                "thread_environment": dict(THREAD_ENV),
                "git_at_launch": launch_git,
                "hard_wall_covers": ["metadata/stat preflight", "same-parent reservation",
                                     "post-reservation CURRENT/frozen/proof hash", "typed V16 result hash/evaluator"],
                "finalization_scope": "local report/stat/ledger charge after child deadline; CPU charge uses process/cgroup evidence",
                "model_invoked": False, "cfd_invoked": False,
                "hdf5_or_bi4_content_read": False, "raw_opened": False,
                "original_path_fallback": "FORBIDDEN",
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
        PARENT._report_size_fixed_point(report)
        _write_new(bound["receipt"], report)
        home_bytes = int(bound["receipt"].stat().st_size)
        cpu_evidence = _cpu_delta(entry_cpu, _cpu_snapshot())
        charge = PARENT._charge(parent_bound, status="completed" if status.startswith("COMPLETED") else "failed",
                                cpu_seconds=cpu_evidence["charge_cpu_seconds"], external_bytes=external_bytes,
                                home_bytes=home_bytes, trace_bytes=trace_bytes, copy_hash_bytes=0,
                                allow_missing_parent=bound["allow_missing_parent"])
        return {"schema": REPORT_SCHEMA, "status": status, "report_path": str(bound["receipt"]),
                "charge": charge, "cpu_evidence": cpu_evidence,
                "external_bytes": external_bytes, "home_bytes": home_bytes,
                "trace_bytes": trace_bytes, "child_result": child_result,
                "raw_opened": False, "hdf5_or_bi4_read": False,
                "qualification": dict(UNKNOWN)}
    except BaseException as final_error:
        charge = None
        charge_error = None
        if reservation_applied:
            try:
                ext = P1._tree_bytes(bound["output_root"]) if bound["output_root"].exists() else 0
                trace = P1._trace_bytes(bound["trace_path"])
                home = int(bound["receipt"].stat().st_size) if bound["receipt"].exists() else 0
                cpu_evidence = _cpu_delta(entry_cpu, _cpu_snapshot())
                charge = PARENT._charge(parent_bound, status="failed",
                                        cpu_seconds=cpu_evidence["charge_cpu_seconds"],
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


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    return _run_fixed(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward-request")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--current-binding", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--supervisor-output-root", type=Path, required=True)
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float)
    build.add_argument("--trace-path", type=Path)
    build.add_argument("--allow-missing-parent", action="store_true")
    build.add_argument("--disallow-missing-parent", action="store_true",
                       help="require an existing same-parent ledger attempt")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward-request":
            value = build_forward_request(
                base_request=args.base_request, current_binding=args.current_binding,
                output=args.output, parent_attempt_id=args.parent_attempt_id,
                supervisor_output_root=args.supervisor_output_root,
                home_receipt=args.home_receipt, max_wall_seconds=args.max_wall_seconds,
                trace_path=args.trace_path,
                allow_missing_parent=(False if args.disallow_missing_parent else
                                      (True if args.allow_missing_parent else None)))
        elif args.command == "preflight":
            _validate_request(args.request, verify_static_content=False)
            value = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                     "metadata_only": True, "ledger_mutated": False,
                     "source_content_validation_phase": "AFTER_PARENT_RESERVATION",
                     "hdf5_or_bi4_read": False, "raw_opened": False,
                     "qualification": dict(UNKNOWN)}
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentV3CurrentError, P1.TypedParentError, P1.ParentDeadline,
            P1.ParentCancelled, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V3 current-bound: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(value.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
