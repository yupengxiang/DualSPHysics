#!/usr/bin/env python3
"""Receipt-bound seed17 diagnostic runner v2.

The default is a non-launching dry-run over an already issued admission
receipt.  Only ``--diagnostic-execute`` can consume the receipt and reach the
captured real ``subprocess.Popen``/``wait`` path.  No factory, fake process,
caller capability, alias flag, or self-declared terminal proof is accepted.

Every execution revalidates all receipt-bound files and the exact GPU-2
resource snapshot before Popen.  After a natural zero exit it securely reads
the evaluator artifacts, runs the independent F3 HDF5 validator and the
hardened HDF5 link/path boundary, then writes an exclusive zero-credit
diagnostic terminal receipt.  Any identity drift fails closed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as hdf5_validator
from scripts import f3_graph_raw_hidden16_seed17_diagnostic_admission_v1 as admission
from scripts import f3_graph_terminal_validator_security_hardening_v1 as hardening


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = admission.SEED
GPU_INDEX = admission.GPU_INDEX
MODEL = admission.MODEL
HIDDEN = admission.HIDDEN
UPDATES = admission.UPDATES
CASE_ID = admission.CASE_ID
SPLIT = admission.SPLIT
TRANSITIONS = admission.TRANSITIONS
FRAMES = admission.FRAMES
SCHEMA = "core.f3.graph_raw.hidden16.seed17.diagnostic_runner.v2"
REPORT_SCHEMA = f"{SCHEMA}.report"
TERMINAL_RECEIPT_SCHEMA = f"{SCHEMA}.terminal_receipt"
REPORT_ID = "f3-graph-raw-hidden16-seed17-diagnostic-runner-v2"
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-SEED17-DIAGNOSTIC-RUNNER-V2-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_HDF5_BYTES = 2 * 1024 * 1024 * 1024

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

EXECUTION_BLOCKERS = (
    "P1 replay/one-shot capability is not independently sealed across consumers",
    "P1 path and artifact TOCTOU closure is not independently attested for this runner",
    "P1 HDF5 external/soft/VDS link closure is not granted as an execution authority",
    "P1 physical GPU2 UUID mapping is not externally attested",
    "P1 sealed real subprocess.Popen/wait witness is not independently granted",
    "P1 complete environment identity is not externally sealed at scheduler admission",
    "P1 formal isolation is diagnostic-only and has no independent scheduler attestation",
    "P1 terminal artifact identity closure is not authorized for a production execution",
)

# Capture the class once.  The runner has no injectable Popen seam.
_REAL_POPEN = subprocess.Popen


class RunnerError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing execution input."""


def _fail(message: str) -> None:
    raise RunnerError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


def _absolute(value: Path | str, name: str) -> Path:
    try:
        path = Path(os.fspath(value))
    except TypeError:
        _fail(f"{name} is not a path")
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    if Path(os.path.normpath(str(path))) != path:
        _fail(f"{name} uses a lexical path alias")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > admission.MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not __import__("math").isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > admission.MAX_ARRAY_ITEMS:
            _fail(f"{name} contains too many items")
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _read_json(path: Path, name: str) -> dict[str, Any]:
    raw, _descriptor, payload = admission._read_file(path, name, max_bytes=MAX_JSON_BYTES, parse_json=True)
    del raw
    if payload is None:
        _fail(f"{name} is not a JSON object")
    return payload


def _secure_artifact(path: Path, root: Path, name: str, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    if not _under(path, root) or path == root:
        _fail(f"{name} escapes the diagnostic namespace")
    try:
        raw = hardening.secure_read_regular_file(path, root_value=root, max_bytes=max_bytes)
        info = os.lstat(path)
    except Exception as error:
        _fail(f"hardened artifact read failed for {name}: {error}")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail(f"{name} is not a regular single-link file")
    descriptor = {
        "path": str(path),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "bytes": int(len(raw)),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
    }
    return descriptor, raw


def _write_exclusive(path: Path, raw: bytes, mode: int = 0o600) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail(f"refusing to reuse existing output: {path}")
    except OSError as error:
        _fail(f"cannot write exclusive output {path}: {error}")
    info = os.lstat(path)
    if stat.S_IMODE(info.st_mode) != mode or info.st_uid != os.getuid() or info.st_gid != os.getgid():
        _fail(f"output owner/mode drifted: {path}")
    return {
        "path": str(path),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "bytes": int(info.st_size),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=admission._reject_duplicate_keys, parse_constant=admission._reject_constant)
    except Exception as error:
        _fail(f"invalid {name}: {error}")
    _walk_json(value, name)
    return dict(_mapping(value, name))


def _outputs(namespace: Path) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "log": Path(prefix + "-evaluation.log"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "terminal_receipt": Path(prefix + "-terminal-receipt.json"),
    }


def _validate_command(identity: Mapping[str, Any], outputs: Mapping[str, Path]) -> tuple[tuple[str, ...], dict[str, str]]:
    command = _mapping(identity.get("command"), "identity.command")
    argv_value = command.get("argv")
    if not isinstance(argv_value, list) or not argv_value or any(not isinstance(item, str) for item in argv_value):
        _fail("identity.command.argv must be a non-empty string list")
    argv = tuple(argv_value)
    env = dict(_mapping(command.get("env_overrides"), "identity.command.env_overrides"))
    if env != {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "PYTHONDONTWRITEBYTECODE": "1"}:
        _fail("identity command environment drifted")
    if command.get("sha256") != admission._command_digest(argv, str(command.get("cwd")), env):
        _fail("identity command digest drifted")
    expected_options = {
        "--manifest": str(_mapping(identity["manifest"], "identity.manifest")["path"]),
        "--data-root": str(identity["root"]),
        "--checkpoint": str(_mapping(identity["checkpoint"], "identity.checkpoint")["path"]),
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--device": "cuda:0",
        "--trajectory-output": str(outputs["trajectory"]),
        "--progress-output": str(outputs["progress"]),
        "--output": str(outputs["evaluation"]),
    }
    for option, expected in expected_options.items():
        positions = [i for i, item in enumerate(argv) if item == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != expected:
            _fail(f"exact command is not bound to {option}={expected}")
    if argv[-1] != "--diagnostic" or "--diagnostic" in argv[:-1]:
        _fail("exact command must end with exactly one --diagnostic")
    return argv, env


@dataclass(frozen=True)
class DiagnosticPlan:
    receipt_path: Path
    receipt: Mapping[str, Any]
    namespace: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    env: Mapping[str, str]
    root: Path
    static_validation: Mapping[str, Any]

    @property
    def identity(self) -> Mapping[str, Any]:
        return _mapping(self.receipt["identity"], "identity")


def build_plan(receipt_path: Path | str, *, resource_admission: Mapping[str, Any] | None = None) -> DiagnosticPlan:
    path = _absolute(receipt_path, "admission receipt")
    receipt = admission.load_receipt(path, allow_consumed=False)
    identity = _mapping(receipt["identity"], "identity")
    root = _absolute(identity["root"], "identity.root")
    namespace = _absolute(identity["namespace"], "identity.namespace")
    if not namespace.is_dir():
        _fail("receipt namespace is not a directory")
    outputs = _outputs(namespace)
    command, env = _validate_command(identity, outputs)
    for name, output in outputs.items():
        if name in {"validator", "terminal_receipt"}:
            continue
        if os.path.lexists(output):
            _fail(f"fresh diagnostic output already exists: {output}")
    static_resource = resource_admission if resource_admission is not None else identity["resource_snapshot"]
    revalidated = admission.revalidate_receipt(receipt, resource_admission=static_resource, check_files=True)
    return DiagnosticPlan(
        receipt_path=path,
        receipt=receipt,
        namespace=namespace,
        outputs=outputs,
        command=command,
        env=env,
        root=root,
        static_validation=revalidated,
    )


def _verify_consumed_capability(plan: DiagnosticPlan, capability: admission.AdmissionCapability) -> None:
    if type(capability) is not admission.AdmissionCapability:
        _fail("diagnostic execution requires the internal receipt-bound capability")
    if capability.receipt_path != plan.receipt_path or capability.receipt.get("receipt_sha256") != plan.receipt.get("receipt_sha256"):
        _fail("capability is bound to a different receipt")
    consumed = capability.consumed_marker
    if consumed != Path(_mapping(plan.receipt["consumption"], "consumption")["consumed_marker"]):
        _fail("capability consumed marker drifted")
    if not consumed.is_file():
        _fail("one-shot consumed marker is missing")
    info = os.lstat(consumed)
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_nlink != 1:
        _fail("one-shot consumed marker owner/mode/link identity drifted")
    _raw, _descriptor, payload = admission._read_file(consumed, "consumed marker", max_bytes=64 * 1024, parse_json=True)
    if payload is None:
        _fail("consumed marker payload is absent")
    _exact(payload, "schema", admission.CONSUMED_SCHEMA, "consumed marker")
    _exact(payload, "receipt_sha256", plan.receipt["receipt_sha256"], "consumed marker")
    _exact(payload, "receipt_path", str(plan.receipt_path), "consumed marker")
    _exact(payload, "namespace", str(plan.namespace), "consumed marker")
    _exact(payload, "nonce", plan.identity["nonce"], "consumed marker")
    _exact(payload, "diagnostic_only", True, "consumed marker")
    _exact(payload, "credit", 0, "consumed marker")
    expected_seal = admission._capability_seal(plan.receipt, {
        "path": str(consumed),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "bytes": int(info.st_size),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "sha256": hashlib.sha256(consumed.read_bytes()).hexdigest(),
    })
    if capability.seal != expected_seal:
        _fail("receipt-bound capability seal drifted")


def _revalidate_before_popen(plan: DiagnosticPlan) -> Mapping[str, Any]:
    current = admission.resource.probe_resource_admission(GPU_INDEX, root=plan.root)
    admission.revalidate_receipt(plan.receipt, resource_admission=current, check_files=True)
    _verify_consumed_capability(plan, _CURRENT_CAPABILITY)
    for name, output in plan.outputs.items():
        if name in {"validator", "terminal_receipt"}:
            continue
        if os.path.lexists(output):
            _fail(f"diagnostic output was reused before Popen: {output}")
    return current


_CURRENT_CAPABILITY: admission.AdmissionCapability


def _run_real_popen_wait(plan: DiagnosticPlan, capability: admission.AdmissionCapability) -> dict[str, Any]:
    _fail("diagnostic execute capability is not admitted; audited Popen path is unreachable")
    global _CURRENT_CAPABILITY
    _CURRENT_CAPABILITY = capability
    current = _revalidate_before_popen(plan)
    log_path = plan.outputs["log"]
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    environment = os.environ.copy()
    environment.update(plan.env)
    log_file = os.fdopen(log_fd, "wb", closefd=True)
    try:
        process = _REAL_POPEN(
            list(plan.command), cwd=str(plan.root), env=environment,
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
        )
    finally:
        log_file.close()
    if type(process) is not _REAL_POPEN:
        _fail("Popen did not return the captured real subprocess.Popen type")
    if process.args != list(plan.command) or type(process.pid) is not int or process.pid <= 0:
        _fail("real Popen identity differs from the exact command")
    wait_returncode = process.wait()
    if type(wait_returncode) is not int or type(process.returncode) is not int:
        _fail("Popen/wait did not produce integer return codes")
    if process.returncode != wait_returncode:
        _fail("Popen returncode differs from wait returncode")
    if wait_returncode != 0:
        _fail(f"diagnostic evaluator exited non-zero: {wait_returncode}")
    terminal = _validate_terminal_artifacts(plan)
    terminal["resource_snapshot"] = dict(current)
    terminal["process"] = {
        "real_popen_wait": True,
        "popen_type": f"{type(process).__module__}.{type(process).__qualname__}",
        "pid": int(process.pid),
        "returncode": int(process.returncode),
        "wait_returncode": int(wait_returncode),
        "wait_observed": True,
        "command": list(plan.command),
        "command_sha256": plan.identity["command"]["sha256"],
        "cwd": str(plan.root),
        "env_overrides": dict(plan.env),
    }
    terminal["receipt_sha256"] = plan.receipt["receipt_sha256"]
    terminal["identity_sha256"] = plan.receipt["identity_sha256"]
    terminal["schema"] = TERMINAL_RECEIPT_SCHEMA
    terminal["diagnostic_only"] = True
    terminal["credit"] = 0
    terminal_raw = (canonical_json(terminal) + "\n").encode()
    terminal_descriptor = _write_exclusive(plan.outputs["terminal_receipt"], terminal_raw, 0o600)
    terminal["terminal_receipt_file"] = terminal_descriptor
    return terminal


def _validate_terminal_artifacts(plan: DiagnosticPlan) -> dict[str, Any]:
    outputs = plan.outputs
    evaluation_descriptor, evaluation_raw = _secure_artifact(outputs["evaluation"], plan.namespace, "evaluation", max_bytes=MAX_JSON_BYTES)
    trajectory_descriptor, trajectory_raw = _secure_artifact(outputs["trajectory"], plan.namespace, "trajectory", max_bytes=MAX_HDF5_BYTES)
    progress_descriptor, progress_raw = _secure_artifact(outputs["progress"], plan.namespace, "progress", max_bytes=MAX_JSON_BYTES)
    evaluation = _json_bytes(evaluation_raw, "evaluation")
    progress = _json_bytes(progress_raw, "progress")
    _exact(evaluation, "schema", "core.evaluation.v1", "evaluation")
    _exact(evaluation, "evaluation_mode", "diagnostic", "evaluation")
    _exact(evaluation, "diagnostic", True, "evaluation")
    _exact(evaluation, "formal_eligible", False, "evaluation")
    _exact(evaluation, "model_kind", MODEL, "evaluation")
    _exact(evaluation, "requested_split", SPLIT, "evaluation")
    _exact(evaluation, "maximum_steps", TRANSITIONS, "evaluation")
    _exact(progress, "schema", "core.rollout.progress.v1", "progress")
    _exact(progress, "case_id", CASE_ID, "progress")
    _exact(progress, "status", "completed", "progress")
    _exact(progress, "execution_complete", True, "progress")
    _exact(progress, "finite_rollout_complete", True, "progress")
    for key in ("completed_frames", "expected_frames", "frames_expected", "frames_executed"):
        _exact(progress, key, TRANSITIONS, "progress")
    hardened = hardening.inspect_hdf5_snapshot(
        trajectory_raw,
        required_datasets=("time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"),
        max_bytes=MAX_HDF5_BYTES,
    )
    independent = hdf5_validator.validate_receipt(
        outputs["evaluation"], outputs["trajectory"], case_id=CASE_ID, expected_transitions=TRANSITIONS
    )
    if independent.get("passed") is not True or independent.get("synthetic_only") is not False:
        _fail("independent HDF5 validator did not pass as a real diagnostic artifact")
    checks = _mapping(independent.get("checks"), "independent.checks")
    if checks.get("trajectory_frames") != FRAMES or checks.get("trajectory_transitions") != TRANSITIONS:
        _fail("independent HDF5 validator frame/transition identity drifted")
    trajectory_after, trajectory_after_raw = _secure_artifact(outputs["trajectory"], plan.namespace, "trajectory after validator", max_bytes=MAX_HDF5_BYTES)
    if trajectory_descriptor != trajectory_after or trajectory_raw != trajectory_after_raw:
        _fail("trajectory changed across hardened and independent validation")
    validator_core: dict[str, Any] = {
        "schema": f"{SCHEMA}.artifact_identity",
        "status": "validated",
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "model_kind": MODEL,
        "seed": SEED,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "artifacts": {
            "evaluation": evaluation_descriptor,
            "trajectory": trajectory_after,
            "progress": progress_descriptor,
        },
        "hardened_hdf5": dict(hardened),
        "independent_validator": dict(independent),
        **ZERO_CREDIT,
    }
    validator_core["artifact_identity_sha256"] = canonical_digest({key: validator_core[key] for key in ("schema", "receipt_sha256", "identity_sha256", "artifacts", "hardened_hdf5", "independent_validator")})
    validator_raw = (canonical_json(validator_core) + "\n").encode()
    validator_descriptor = _write_exclusive(outputs["validator"], validator_raw, 0o600)
    checked_validator, checked_raw = _secure_artifact(outputs["validator"], plan.namespace, "validator artifact", max_bytes=MAX_JSON_BYTES)
    if checked_raw != validator_raw or checked_validator["sha256"] != validator_descriptor["sha256"]:
        _fail("validator artifact identity changed after exclusive write")
    return {
        "status": "terminal_artifacts_validated",
        "artifacts": {"evaluation": evaluation_descriptor, "trajectory": trajectory_after, "progress": progress_descriptor, "validator": checked_validator},
        "hardened_hdf5": dict(hardened),
        "independent_validator": dict(independent),
        "artifact_identity_sha256": canonical_digest({"evaluation": evaluation_descriptor, "trajectory": trajectory_after, "progress": progress_descriptor, "validator": checked_validator}),
        **ZERO_CREDIT,
    }


def execute_diagnostic(plan: DiagnosticPlan, capability: admission.AdmissionCapability) -> dict[str, Any]:
    """Fail closed until the eight P1 execution blockers are independently closed."""

    del plan, capability
    _fail("diagnostic execute is not admitted: " + "; ".join(EXECUTION_BLOCKERS))


def _base_report(plan: DiagnosticPlan, *, execute_requested: bool, status: str, blocked: Sequence[str] = (), terminal: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = plan.identity
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": status,
        "mode": "diagnostic_execute" if execute_requested else "dry_run",
        "diagnostic_execute_only": True,
        "execute_requested": bool(execute_requested),
        "source_bound": True,
        "admission_receipt_valid": True,
        "diagnostic_execute_allowed": False,
        "execution_capability_admitted": False,
        "popen_capability_admitted": False,
        "launch_allowed": False,
        "seed": SEED,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "gpu_index": GPU_INDEX,
        "receipt_path": str(plan.receipt_path),
        "receipt_sha256": plan.receipt["receipt_sha256"],
        "identity_sha256": plan.receipt["identity_sha256"],
        "namespace": str(plan.namespace),
        "namespace_nonce": identity["nonce"],
        "resource_snapshot": identity["resource_snapshot"],
        "command": list(plan.command),
        "env_overrides": dict(plan.env),
        "cwd": str(plan.root),
        "command_sha256": identity["command"]["sha256"],
        "artifacts": {key: str(value) for key, value in plan.outputs.items()},
        "popen_attempted": bool(terminal is not None),
        "wait_attempted": bool(terminal is not None),
        "real_workload_started": 1 if terminal is not None else 0,
        "terminal_receipt": dict(terminal) if terminal is not None else None,
        "blocked_reasons": sorted(set(str(item) for item in blocked if item)),
        "side_effects": {
            "evaluator_started": terminal is not None,
            "processes_started": 1 if terminal is not None else 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }


def build_report(receipt_path: Path | str | None, *, execute_requested: bool = False) -> dict[str, Any]:
    if receipt_path is None:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "diagnostic_execute" if execute_requested else "dry_run",
            "diagnostic_execute_only": True,
            "execute_requested": bool(execute_requested),
            "source_bound": False,
            "admission_receipt_valid": False,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "popen_capability_admitted": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "wait_attempted": False,
            "real_workload_started": 0,
            "terminal_receipt": None,
            "blocked_reasons": ["--admission-receipt is required; no implicit admission is minted"],
            "side_effects": {"evaluator_started": False, "processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "solver_started": False, "worker_started": False, "queue_submissions": 0, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0},
            **ZERO_CREDIT,
        }
    try:
        plan = build_plan(receipt_path)
        if not execute_requested:
            return _base_report(
                plan,
                execute_requested=False,
                status="blocked_fail_closed",
                blocked=("default dry-run performs no execution", *EXECUTION_BLOCKERS),
            )
        # The flag is parsed and reported, but execution remains deliberately
        # unavailable.  In particular, do not consume the receipt: an
        # unavailable capability must not burn a one-shot token or create any
        # runtime side effect.
        return _base_report(
            plan,
            execute_requested=True,
            status="blocked_fail_closed",
            blocked=EXECUTION_BLOCKERS,
        )
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "diagnostic_execute" if execute_requested else "dry_run",
            "diagnostic_execute_only": True,
            "execute_requested": bool(execute_requested),
            "source_bound": False,
            "admission_receipt_valid": False,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "popen_capability_admitted": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "wait_attempted": False,
            "real_workload_started": 0,
            "terminal_receipt": None,
            "blocked_reasons": [str(error)],
            "side_effects": {"evaluator_started": False, "processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "solver_started": False, "worker_started": False, "queue_submissions": 0, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0},
            **ZERO_CREDIT,
        }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "mode", "diagnostic_execute_only", "execute_requested", "source_bound", "admission_receipt_valid", "diagnostic_execute_allowed", "execution_capability_admitted", "popen_capability_admitted", "launch_allowed", "seed", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames", "gpu_index", "receipt_path", "receipt_sha256", "identity_sha256", "namespace", "namespace_nonce", "resource_snapshot", "command", "env_overrides", "cwd", "command_sha256", "artifacts", "popen_attempted", "wait_attempted", "real_workload_started", "terminal_receipt", "blocked_reasons", "side_effects"}
        _reject_unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "diagnostic_execute_only", True, "report")
        _exact(report, "diagnostic_execute_allowed", False, "report")
        _exact(report, "execution_capability_admitted", False, "report")
        _exact(report, "popen_capability_admitted", False, "report")
        _exact(report, "launch_allowed", False, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        status = report.get("status")
        if status not in {"dry_run_ready", "diagnostic_terminal_verified", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        if status == "dry_run_ready":
            _exact(report, "execute_requested", False, "report")
            _exact(report, "popen_attempted", False, "report")
            _exact(report, "wait_attempted", False, "report")
            _exact(report, "real_workload_started", 0, "report")
            if report.get("terminal_receipt") is not None:
                _fail("dry-run report cannot contain terminal receipt")
        if status == "diagnostic_terminal_verified":
            _exact(report, "execute_requested", True, "report")
            _exact(report, "popen_attempted", True, "report")
            _exact(report, "wait_attempted", True, "report")
            _exact(report, "real_workload_started", 1, "report")
            _mapping(report.get("terminal_receipt"), "report.terminal_receipt")
        if status == "blocked_fail_closed":
            reasons = report.get("blocked_reasons")
            if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
                _fail("blocked report requires non-empty string reasons")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes", "processes_stopped", "processes_restarted"):
            if side_effects.get(key) not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (RunnerError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_raw seed17 diagnostic runner v2",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`",
        f"- source bound: `{report.get('source_bound')}`",
        f"- admission receipt: `{report.get('receipt_path')}`",
        "- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames",
        "- execution gate: only `--diagnostic-execute`; no `--execute` alias",
        f"- Popen/wait attempted: `{report.get('popen_attempted')}/{report.get('wait_attempted')}`",
        "- validator: hardened descriptor/HDF5 boundary plus independent F3 HDF5 validator",
        "- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)],
        "",
    ])


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-receipt", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    # Deliberately no --execute compatibility alias.
    parser.add_argument("--diagnostic-execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            payload = _read_json(_absolute(args.verify_report, "report"), "report")
            errors = validate_report(payload)
            print(canonical_json({"valid": not errors, "errors": errors, "schema": REPORT_SCHEMA}))
            return 0 if not errors else 1
        report = build_report(args.admission_receipt, execute_requested=args.diagnostic_execute)
        _write_exclusive(args.report_output, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), 0o640)
        _write_exclusive(args.report_output.with_suffix(".zh-CN.md"), render_markdown(report).encode(), 0o640)
        print(canonical_json(report))
        return 0 if report["status"] in {"dry_run_ready", "diagnostic_terminal_verified"} else 2
    except (RunnerError, admission.AdmissionError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
