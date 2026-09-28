#!/usr/bin/env python3
"""Fail-closed terminal evidence verifier for the F3 MLP hidden16 diagnostic.

The verifier consumes bounded JSON summaries and receipts only.  It never
opens a checkpoint, trajectory/HDF5, evaluation JSON, progress file, or
manifest.  A positive result requires all three seeds to have an independent
process-exit proof and an independently-produced HDF5-validator receipt.  The
result is diagnostic-only and can never grant Core, T1, T2, or credit.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f3.mlp.hidden16.terminal_runtime_verifier.v1"
REPORT_ID = "f3-mlp-hidden16-terminal-runtime-verifier-v1"
TRAINING_SCHEMA = "core.f3.mlp.hidden16.training_evidence_matrix.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
SEEDS = (17, 29, 43)
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^f3-mlp500-hidden16-seed(?:17|29|43)-20260928$")
REPORT_JSON_FILENAME = "F3-MLP-HIDDEN16-TERMINAL-RUNTIME-VERIFIER-V1-2026-09-28.json"
REPORT_MD_FILENAME = REPORT_JSON_FILENAME.removesuffix(".json") + ".zh-CN.md"

DEFAULT_TRAINING = LAB_ROOT / "reports/F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"
DEFAULT_ROLLOUTS = {
    seed: LAB_ROOT / f"reports/F3-MLP-HIDDEN16-SEED{seed}-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
    for seed in SEEDS
}
DEFAULT_PROOFS = {
    seed: LAB_ROOT / f"reports/F3-MLP-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"
    for seed in SEEDS
}
DEFAULT_VALIDATORS = {
    seed: Path(f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-20260928-hdf5-validation.json")
    for seed in SEEDS
}

REPORT_KEYS = frozenset(
    {
        "schema", "report_id", "status", "fail_closed", "receipt_bound",
        "independently_terminal_verified", "source_bound", "diagnostic_only",
        "formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path",
        "qualification", "qualification_credit", "credit", "expected_contract",
        "seed_matrix", "checks", "blocked_reasons", "side_effects",
        "input_boundary", "interpretation", "observed_at_utc",
    }
)
PROCESS_KEYS = frozenset(
    {
        "schema", "report_id", "status", "source_bound", "diagnostic_only",
        "formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path",
        "qualification", "qualification_credit", "credit", "seed", "run_id",
        "namespace", "namespace_nonce", "evaluator_alive", "launcher_alive",
        "evaluator_returncode", "launcher_returncode", "returncode",
        "evaluator_pid_observed", "launcher_pid_observed", "evaluator_reaped",
        "launcher_reaped", "command_sha256", "exit_proof_sha256",
        "manifest_sha256", "training_manifest_sha256", "training_receipt_sha256",
        "checkpoint", "evaluation", "trajectory", "validator",
    }
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})


class VerifierError(ValueError):
    """Malformed, incomplete, unsafe, or drifting evidence."""


def _fail(message: str) -> None:
    raise VerifierError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _walk(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in (
        ("source_bound", True), ("diagnostic_only", True), ("formal", False),
        ("formal_eligible", False), ("T1_numerical", False), ("T2_macro", False),
        ("T2_path", False), ("qualification", False),
        ("qualification_credit", 0), ("credit", 0),
    ):
        _exact(value, key, expected, name)


def _path_text(value: Any, name: str) -> str:
    text = _string(value, name)
    path = Path(text)
    if ".." in path.parts:
        _fail(f"{name} contains parent traversal")
    return text


def _artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, ARTIFACT_KEYS, name)
    path = _path_text(item.get("path"), f"{name}.path")
    if suffix is not None and not path.endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    size = _int(item.get("bytes"), f"{name}.bytes", 1)
    if size > (1 << 50):
        _fail(f"{name}.bytes exceeds declared bound")
    return {"path": path, "sha256": _sha(item.get("sha256"), f"{name}.sha256"), "bytes": size}


def _expected_run_id(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928"


def _namespace(seed: int, value: Mapping[str, Any], name: str) -> tuple[str, str]:
    namespace = _string(value.get("namespace"), f"{name}.namespace")
    nonce = _string(value.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce must be a 32-character lowercase nonce")
    if f"seed{seed}" not in namespace or "full835" not in namespace or f"nonce{nonce}" not in namespace:
        _fail(f"{name}.namespace is not bound to seed{seed}, full835, and nonce")
    if any(word in namespace.lower() for word in ("legacy", "running", "partial", "pending")):
        _fail(f"{name}.namespace is not fresh")
    return namespace, nonce


def _safe_json(path: Path | str | None, *, root: Path, name: str, allow_tmp: bool = False) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    if path is None:
        return None, {"path": None, "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}, f"{name} is missing"
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    reports = Path(os.path.abspath(root / "reports"))
    allowed = False
    try:
        candidate.relative_to(reports)
        allowed = True
    except ValueError:
        pass
    if allow_tmp:
        try:
            candidate.relative_to(Path("/tmp"))
            allowed = True
        except ValueError:
            pass
    source = {"path": str(candidate), "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
    if not allowed:
        return None, source, f"{name} escapes bounded report/tmp roots"
    try:
        before = os.lstat(candidate)
        source["exists"] = True
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None, source, f"{name} is not a single-link regular file"
        if before.st_size > MAX_JSON_BYTES:
            return None, source, f"{name} exceeds bounded JSON size"
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(candidate, flags)
        try:
            after_open = os.fstat(fd)
            if (after_open.st_dev, after_open.st_ino, after_open.st_nlink, after_open.st_size) != (before.st_dev, before.st_ino, before.st_nlink, before.st_size):
                return None, source, f"{name} changed during open"
            data = b""
            while len(data) <= MAX_JSON_BYTES:
                chunk = os.read(fd, min(65536, MAX_JSON_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
            if len(data) > MAX_JSON_BYTES:
                return None, source, f"{name} exceeds bounded JSON size"
        finally:
            os.close(fd)
        after = os.lstat(candidate)
        if (after.st_dev, after.st_ino, after.st_nlink, after.st_size) != (before.st_dev, before.st_ino, before.st_nlink, before.st_size):
            return None, source, f"{name} changed after read"
        digest = hashlib.sha256(data).hexdigest()
        source.update({"opened": True, "bytes": len(data), "sha256": digest})
        try:
            payload = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, VerifierError) as error:
            return None, source, f"{name} is invalid JSON: {error}"
        _walk(payload, name)
        payload = _mapping(payload, name)
        source["schema"] = payload.get("schema")
        return payload, source, None
    except (OSError, VerifierError) as error:
        return None, source, f"{name}: {error}"


def _validate_training(payload: Mapping[str, Any], name: str) -> dict[int, dict[str, Any]]:
    _unknown(payload, frozenset({"schema", "report_id", "status", "fail_closed", "source_bound", "diagnostic_only", "formal", "formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path", "qualification_credit", "credit", "runs", "shared_config", "checks", "errors", "reference_training_matrix", "expected_contract", "authorization", "input_boundary", "side_effects", "scope_note", "observed_at_utc", "training_evidence_counted_as_formal_runs", "formal_training_runs_expected", "formal_training_runs_counted", "t1_case_runs_counted", "t2_macro_families_counted"}), name)
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "source_bound", True, name)
    _exact(payload, "diagnostic_only", True, name)
    for key, expected in (("formal", False), ("formal_eligible", False), ("qualification", False), ("T1_numerical", False), ("T2_macro", False), ("T2_path", False), ("qualification_credit", 0), ("credit", 0)):
        _exact(payload, key, expected, name)
    shared = _mapping(payload.get("shared_config"), f"{name}.shared_config")
    _exact(shared, "model_kind", MODEL, f"{name}.shared_config")
    _exact(shared, "hidden", HIDDEN, f"{name}.shared_config")
    _exact(shared, "updates", UPDATES, f"{name}.shared_config")
    runs = payload.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail(f"{name}.runs must contain exactly three rows")
    result: dict[int, dict[str, Any]] = {}
    for row in runs:
        item = _mapping(row, f"{name}.run")
        seed = _int(item.get("seed"), f"{name}.run.seed")
        if seed not in SEEDS or seed in result:
            _fail(f"{name}.runs contains an invalid or duplicate seed")
        _exact(item, "status", "bound_complete", f"{name}.seed{seed}")
        evidence = _mapping(item.get("evidence"), f"{name}.seed{seed}.evidence")
        _exact(evidence, "model_kind", MODEL, f"{name}.seed{seed}.evidence")
        _exact(evidence, "hidden", HIDDEN, f"{name}.seed{seed}.evidence")
        _exact(evidence, "updates", UPDATES, f"{name}.seed{seed}.evidence")
        _exact(evidence, "run_id", _expected_run_id(seed), f"{name}.seed{seed}.evidence")
        _exact(evidence, "evidence_status", "complete", f"{name}.seed{seed}.evidence")
        checkpoint_payload = _mapping(evidence.get("checkpoint"), f"{name}.seed{seed}.checkpoint")
        checkpoint = {
            "path": _path_text(checkpoint_payload.get("path"), f"{name}.seed{seed}.checkpoint.path"),
            "sha256": _sha(checkpoint_payload.get("sha256"), f"{name}.seed{seed}.checkpoint.sha256"),
            "bytes": _int(checkpoint_payload.get("bytes", 1), f"{name}.seed{seed}.checkpoint.bytes", 1),
        }
        if not checkpoint["path"].endswith(".pt"):
            _fail(f"{name}.seed{seed}.checkpoint.path must be a checkpoint")
        _exact(checkpoint_payload, "schema", "core.checkpoint.v1", f"{name}.seed{seed}.checkpoint")
        _exact(checkpoint_payload, "update", UPDATES, f"{name}.seed{seed}.checkpoint")
        source = _mapping(item.get("source"), f"{name}.seed{seed}.source")
        training = {
            "path": _path_text(source.get("path"), f"{name}.seed{seed}.source.path"),
            "sha256": _sha(source.get("sha256"), f"{name}.seed{seed}.source.sha256"),
            "bytes": _int(source.get("bytes"), f"{name}.seed{seed}.source.bytes", 1),
        }
        if not training["path"].endswith(".json"):
            _fail(f"{name}.seed{seed}.source.path must be JSON")
        _exact(source, "schema", "core.training.v1", f"{name}.seed{seed}.source")
        manifest = _sha(evidence.get("manifest_sha256"), f"{name}.seed{seed}.manifest_sha256")
        if training["sha256"] != item.get("source", {}).get("sha256"):
            _fail(f"{name}.seed{seed}.training source SHA drift")
        result[seed] = {"run_id": _expected_run_id(seed), "checkpoint": checkpoint, "training_receipt": training, "training_manifest_sha256": manifest, "model": MODEL, "hidden": HIDDEN, "updates": UPDATES}
    return result


def _validate_rollout(payload: Mapping[str, Any], seed: int, training: Mapping[str, Any], name: str) -> dict[str, Any]:
    schema = _string(payload.get("schema"), f"{name}.schema")
    if not schema.startswith("core.f3.mlp.hidden16.") or not (f"seed{seed}" in schema or schema == "core.f3.mlp.hidden16.full835.rollout_diagnostic.summary.v1"):
        _fail(f"{name}.schema is not the seed-bound MLP summary schema")
    _exact(payload, "status", "completed", name)
    _exact(payload, "diagnostic_only", True, name)
    protocol = _mapping(payload.get("protocol"), f"{name}.protocol")
    for key, expected in (("model", MODEL), ("seed", seed), ("hidden", HIDDEN), ("training_updates", UPDATES), ("case_id", CASE_ID), ("split", SPLIT), ("diagnostic", True), ("autonomous", True), ("future_state_inputs", False)):
        _exact(protocol, key, expected, f"{name}.protocol")
    if "maximum_steps" in protocol:
        _exact(protocol, "maximum_steps", TRANSITIONS, f"{name}.protocol")
    else:
        _exact(protocol, "requested_transitions", TRANSITIONS, f"{name}.protocol")
        _exact(protocol, "trajectory_frames", FRAMES, f"{name}.protocol")
    evaluation = _mapping(payload.get("evaluation"), f"{name}.evaluation")
    for key, expected in (("status", "completed"), ("finite_rollout_complete", True), ("transitions_executed", TRANSITIONS), ("trajectory_frames_including_initial", FRAMES), ("full_registered_denominator_complete", True), ("future_state_inputs", False)):
        _exact(evaluation, key, expected, f"{name}.evaluation")
    if "expected_transitions" in evaluation:
        _exact(evaluation, "expected_transitions", TRANSITIONS, f"{name}.evaluation")
    else:
        _exact(evaluation, "expected_full_case_transitions", TRANSITIONS, f"{name}.evaluation")
    if "execution_complete" in evaluation:
        _exact(evaluation, "execution_complete", True, f"{name}.evaluation")
    else:
        _exact(evaluation, "requested_window_complete", True, f"{name}.evaluation")
    if evaluation.get("failure_category") is not None:
        _fail(f"{name}.evaluation.failure_category must be null")
    source = _mapping(payload.get("source"), f"{name}.source")
    manifest_obj = source.get("manifest")
    manifest_sha = _sha(manifest_obj.get("sha256") if isinstance(manifest_obj, Mapping) else source.get("manifest_sha256"), f"{name}.manifest_sha256")
    if manifest_sha != manifest_sha.lower():
        _fail(f"{name}.manifest SHA is not canonical")
    namespace = protocol.get("namespace")
    nonce = protocol.get("namespace_nonce")
    if namespace is not None or nonce is not None:
        namespace, nonce = _namespace(seed, protocol, f"{name}.protocol")
    checkpoint_payload = payload.get("checkpoint")
    if not isinstance(checkpoint_payload, Mapping):
        checkpoint = training["checkpoint"]
    else:
        checkpoint = {
            "path": _path_text(checkpoint_payload.get("path"), f"{name}.checkpoint.path"),
            "sha256": _sha(checkpoint_payload.get("sha256"), f"{name}.checkpoint.sha256"),
            "bytes": _int(checkpoint_payload.get("bytes"), f"{name}.checkpoint.bytes", 1),
        }
        _exact(checkpoint_payload, "schema", "core.checkpoint.v1", f"{name}.checkpoint")
    if checkpoint["sha256"] != training["checkpoint"]["sha256"] or checkpoint["path"] != training["checkpoint"]["path"]:
        _fail(f"{name}.checkpoint identity drifts from training evidence")
    artifacts = _mapping(payload.get("artifacts"), f"{name}.artifacts")
    eval_receipt = _mapping(evaluation.get("receipt"), f"{name}.evaluation.receipt") if isinstance(evaluation.get("receipt"), Mapping) else None
    if eval_receipt is not None:
        evaluation_artifact = _artifact(eval_receipt, f"{name}.evaluation.receipt", suffix=".json")
    else:
        evaluation_artifact = {"path": f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-20260928-evaluation.json", "sha256": _sha(artifacts.get("evaluation_receipt_sha256"), f"{name}.artifacts.evaluation_receipt_sha256"), "bytes": _int(artifacts.get("bytes", {}).get("evaluation_receipt", 1) if isinstance(artifacts.get("bytes"), Mapping) else 1, f"{name}.evaluation.bytes", 1)}
    trajectory_payload = payload.get("trajectory")
    if isinstance(trajectory_payload, Mapping) and "path" in trajectory_payload:
        trajectory = {
            "path": _path_text(trajectory_payload.get("path"), f"{name}.trajectory.path"),
            "sha256": _sha(trajectory_payload.get("sha256"), f"{name}.trajectory.sha256"),
            "bytes": _int(trajectory_payload.get("bytes"), f"{name}.trajectory.bytes", 1),
        }
        if not trajectory["path"].endswith(".h5"):
            _fail(f"{name}.trajectory.path must be HDF5")
    else:
        trajectory = {"path": f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-20260928-trajectory.h5", "sha256": _sha(artifacts.get("trajectory_sha256"), f"{name}.artifacts.trajectory_sha256"), "bytes": _int(artifacts.get("bytes", {}).get("trajectory", 1) if isinstance(artifacts.get("bytes"), Mapping) else 1, f"{name}.trajectory.bytes", 1)}
    return {"seed": seed, "run_id": training["run_id"], "manifest_sha256": manifest_sha, "training_manifest_sha256": training["training_manifest_sha256"], "training_receipt": training["training_receipt"], "checkpoint": checkpoint, "evaluation": evaluation_artifact, "trajectory": trajectory, "case_id": CASE_ID, "split": SPLIT, "model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "transitions": TRANSITIONS, "frames": FRAMES, "namespace": namespace, "namespace_nonce": nonce}


def _validate_validator(payload: Mapping[str, Any], seed: int, identity: Mapping[str, Any], name: str) -> dict[str, Any]:
    _exact(payload, "schema", VALIDATOR_SCHEMA, name)
    for key, expected in (("passed", True), ("complete", True), ("case_id", CASE_ID), ("expected_transitions", TRANSITIONS), ("frames_executed", TRANSITIONS), ("qualification_credit", 0), ("production_artifacts_touched", False)):
        _exact(payload, key, expected, name)
    _exact(payload.get("checks", {}), "trajectory_frames", FRAMES, f"{name}.checks")
    _exact(payload.get("checks", {}), "trajectory_transitions", TRANSITIONS, f"{name}.checks")
    _exact(payload.get("checks", {}), "tail_frame_count", 0, f"{name}.checks")
    _exact(payload, "diagnostic_only", True, name)
    _exact(payload, "fail_closed", False, name)
    if payload.get("evaluation_json") != identity["evaluation"]["path"] or payload.get("trajectory_hdf5") != identity["trajectory"]["path"]:
        _fail(f"{name} artifact paths drift from evaluation identity")
    return {"seed": seed, "schema": VALIDATOR_SCHEMA, "passed": True, "complete": True}


def _validate_process(payload: Mapping[str, Any], seed: int, identity: Mapping[str, Any], validator_source: Mapping[str, Any], validator_payload: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    _unknown(payload, PROCESS_KEYS, name)
    _zero_credit(payload, name)
    _exact(payload, "schema", f"core.f3.mlp.hidden16.seed{seed}.process_exit_proof.v1", name)
    _exact(payload, "status", "exited_successfully", name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "run_id", identity["run_id"], name)
    namespace, nonce = _namespace(seed, payload, name)
    if identity.get("namespace") not in (None, namespace) or identity.get("namespace_nonce") not in (None, nonce):
        _fail(f"{name} namespace drifts from rollout identity")
    for key, expected in (("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0), ("evaluator_reaped", True), ("launcher_reaped", True)):
        _exact(payload, key, expected, name)
    _int(payload.get("evaluator_pid_observed"), f"{name}.evaluator_pid_observed", 1)
    _int(payload.get("launcher_pid_observed"), f"{name}.launcher_pid_observed", 1)
    _sha(payload.get("command_sha256"), f"{name}.command_sha256")
    _sha(payload.get("exit_proof_sha256"), f"{name}.exit_proof_sha256")
    _exact(payload, "manifest_sha256", identity["manifest_sha256"], name)
    _exact(payload, "training_manifest_sha256", identity["training_manifest_sha256"], name)
    _exact(payload, "training_receipt_sha256", identity["training_receipt"]["sha256"], name)
    for key in ("checkpoint", "evaluation", "trajectory", "validator"):
        expected = identity["checkpoint"] if key == "checkpoint" else identity[key] if key != "validator" else None
        actual = _artifact(payload.get(key), f"{name}.{key}", suffix=".h5" if key == "trajectory" else ".json" if key in ("evaluation", "validator") else ".pt")
        if key != "validator" and actual != expected:
            _fail(f"{name}.{key} drifts from evaluation identity")
        if key == "validator" and validator_source.get("path") != actual["path"]:
            _fail(f"{name}.validator path differs from loaded validator receipt")
    if validator_payload is None:
        _fail(f"{name} independent validator receipt is missing")
    _validate_validator(validator_payload, seed, identity, f"{name}.validator_receipt")
    return {"seed": seed, "namespace": namespace, "namespace_nonce": nonce, "status": "independently_verified"}


def _source_error(path: Path | str | None, exists: bool = False) -> dict[str, Any]:
    return {"path": None if path is None else str(path), "exists": exists, "opened": False, "bytes": None, "sha256": None, "schema": None}


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _empty_side_effects() -> dict[str, Any]:
    return {"bounded_json_opened": True, "large_evaluation_opened": False, "trajectory_hdf5_opened": False, "checkpoint_opened": False, "manifest_opened": False, "runtime_started": False, "solver_started": False, "worker_started": False, "gpu_started": False, "queue_started": False, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0, "gate_mutation": 0, "completion_mutation": 0}


def build_report(root: Path | str = LAB_ROOT, *, training_path: Path | str | None = DEFAULT_TRAINING, rollout_paths: Mapping[int, Path | str | None] = DEFAULT_ROLLOUTS, process_paths: Mapping[int, Path | str | None] = DEFAULT_PROOFS, validator_paths: Mapping[int, Path | str | None] = DEFAULT_VALIDATORS, observed_at_utc: str = "2026-09-28T00:00:00Z") -> dict[str, Any]:
    root = Path(os.path.abspath(root))
    errors: list[str] = []
    training_payload, training_source, error = _safe_json(training_path, root=root, name="training matrix")
    training: dict[int, dict[str, Any]] = {}
    if training_payload is not None:
        try:
            training = _validate_training(training_payload, "training matrix")
        except (VerifierError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    elif error:
        errors.append(error)
    rows: list[dict[str, Any]] = []
    verified = True and bool(training) and not errors
    for seed in SEEDS:
        row: dict[str, Any] = {"seed": seed, "status": "blocked", "blocked_reasons": [], "sources": {}, "evidence": None}
        rollout_payload, rollout_source, rollout_error = _safe_json(rollout_paths.get(seed), root=root, name=f"seed{seed} rollout summary")
        proof_payload, proof_source, proof_error = _safe_json(process_paths.get(seed), root=root, name=f"seed{seed} process proof")
        validator_payload, validator_source, validator_error = _safe_json(validator_paths.get(seed), root=root, name=f"seed{seed} validator receipt", allow_tmp=True)
        row["sources"] = {"rollout_summary": rollout_source, "process_exit_proof": proof_source, "validator_receipt": validator_source}
        row_errors: list[str] = []
        identity: dict[str, Any] | None = None
        try:
            if seed not in training:
                _fail(f"seed{seed} training evidence is missing")
            if rollout_payload is None:
                _fail(rollout_error or "rollout summary is missing")
            identity = _validate_rollout(rollout_payload, seed, training[seed], f"seed{seed} rollout summary")
            if proof_payload is None:
                _fail(proof_error or "independent process-exit proof is missing")
            if validator_payload is None:
                _fail(validator_error or "independent validator receipt is missing")
            process_result = _validate_process(proof_payload, seed, identity, validator_source, validator_payload, f"seed{seed} process proof")
        except (VerifierError, KeyError, TypeError) as exc:
            row_errors.append(str(exc))
        else:
            row["status"] = "independently_verified"
            row["evidence"] = {"run_id": identity["run_id"], "model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES, "namespace": process_result["namespace"], "namespace_nonce": process_result["namespace_nonce"], "checkpoint": identity["checkpoint"], "evaluation": identity["evaluation"], "trajectory": identity["trajectory"], "validator": validator_source}
        row["blocked_reasons"] = row_errors
        rows.append(row)
        if row_errors:
            verified = False
            errors.extend(row_errors)
        elif row["status"] != "independently_verified":
            verified = False
    verified = verified and all(row["status"] == "independently_verified" for row in rows + [])
    # The loop above deliberately records all rows before evaluating the final gate.
    verified = bool(training) and len(errors) == 0 and len(rows) == 3 and all(row["status"] == "independently_verified" for row in rows)
    for row in rows:
        if row["status"] == "blocked":
            row["blocked_reasons"] = list(dict.fromkeys(row["blocked_reasons"]))
    errors = list(dict.fromkeys(errors))
    return {"schema": REPORT_SCHEMA, "report_id": REPORT_ID, "status": "independently_terminal_verified" if verified else "blocked_fail_closed", "fail_closed": not verified, "receipt_bound": bool(training), "independently_terminal_verified": verified, "source_bound": verified, "diagnostic_only": True, "formal": False, "formal_eligible": False, "T1_numerical": False, "T2_macro": False, "T2_path": False, "qualification": False, "qualification_credit": 0, "credit": 0, "expected_contract": {"model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "seeds": list(SEEDS), "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES, "required_evidence": ["training_matrix", "rollout_identity", "process_exit_proof", "hdf5_validator_receipt"], "bounded_json_only": True, "zero_credit_only": True}, "seed_matrix": rows, "checks": [_check("training_matrix_bound", bool(training), "the three-seed MLP training matrix is source-bound"), _check("exact_seed_set", len(rows) == 3, "exact seed set is 17, 29, 43", sorted(row["seed"] for row in rows), list(SEEDS)), _check("full835_rollout_identity", all(row["status"] == "independently_verified" for row in rows), "every seed has completed MLP full835 identity"), _check("process_exit_proofs", all(row["status"] == "independently_verified" for row in rows), "every seed has evaluator/launcher exit proof"), _check("independent_hdf5_receipts", all(row["status"] == "independently_verified" for row in rows), "every seed has an independent complete validator receipt"), _check("zero_credit", True, "all positive evidence remains diagnostic-only and zero-credit")], "blocked_reasons": errors, "side_effects": _empty_side_effects(), "input_boundary": {"bounded_json_only": True, "large_evaluation_opened": False, "trajectory_hdf5_opened": False, "checkpoint_opened": False, "manifest_opened": False, "runtime_started": False, "queue_submissions": 0}, "interpretation": "This verifier consumes bounded JSON summaries and receipts only. It does not open evaluation, progress, manifest, checkpoint, trajectory, or HDF5 content. A positive result is independently terminal-verified for the diagnostic chain only and contributes zero Core/T1/T2/qualification credit.", "observed_at_utc": _string(observed_at_utc, "observed_at_utc")}


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _unknown(report, REPORT_KEYS, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "diagnostic_only", True, "report")
        for key, expected in (("formal", False), ("formal_eligible", False), ("T1_numerical", False), ("T2_macro", False), ("T2_path", False), ("qualification", False), ("qualification_credit", 0), ("credit", 0)):
            _exact(report, key, expected, "report")
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or len(rows) != 3 or [row.get("seed") for row in rows] != list(SEEDS):
            _fail("report.seed_matrix is not the exact ordered seed set")
        for row in rows:
            _mapping(row, "report.seed_matrix row")
            if row.get("status") not in {"blocked", "independently_verified"}:
                _fail("report.seed_matrix row has an invalid status")
    except (VerifierError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return errors


def _fixed_output(path: Path, root: Path, filename: str, data: bytes) -> None:
    expected = (root / "reports" / filename).resolve()
    target = Path(os.path.abspath(path))
    if target != expected:
        raise VerifierError("output path is not the fixed report destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        info = os.lstat(target)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VerifierError("existing report target is not a single-link regular file")
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, target)


def _parse_seed_paths(values: Sequence[str], option: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{option} expects SEED=PATH")
        seed_text, path = value.split("=", 1)
        seed = int(seed_text)
        if seed not in SEEDS or seed in result:
            raise SystemExit(f"{option} has invalid or duplicate seed")
        result[seed] = Path(path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--training-matrix", type=Path, default=None)
    parser.add_argument("--rollout-report", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--process-exit-proof", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--validator-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(os.path.abspath(args.root))
    rollout = dict(DEFAULT_ROLLOUTS)
    rollout.update(_parse_seed_paths(args.rollout_report, "--rollout-report"))
    proofs = dict(DEFAULT_PROOFS)
    proofs.update(_parse_seed_paths(args.process_exit_proof, "--process-exit-proof"))
    validators = dict(DEFAULT_VALIDATORS)
    validators.update(_parse_seed_paths(args.validator_receipt, "--validator-receipt"))
    report = build_report(root, training_path=args.training_matrix or DEFAULT_TRAINING, rollout_paths=rollout, process_paths=proofs, validator_paths=validators)
    validation_errors = validate_report(report)
    if validation_errors:
        report["status"] = "blocked_fail_closed"
        report["fail_closed"] = True
        report["source_bound"] = False
        report["independently_terminal_verified"] = False
        report["blocked_reasons"] = list(dict.fromkeys(list(report.get("blocked_reasons", [])) + validation_errors))
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    output = args.output or (root / "reports" / REPORT_JSON_FILENAME)
    _fixed_output(output, root, REPORT_JSON_FILENAME, encoded)
    if args.markdown_output is not None:
        markdown = "# F3 MLP hidden16 terminal runtime verifier V1\n\n" + f"- status: `{report['status']}`\n- source_bound: `{report['source_bound']}`\n- independently_terminal_verified: `{report['independently_terminal_verified']}`\n- credit: `0`\n\n该回执只消费 bounded JSON；MLP diagnostic evidence 不进入 Core formal/T1/T2。\n"
        _fixed_output(args.markdown_output, root, REPORT_MD_FILENAME, markdown.encode("utf-8"))
    print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "credit": 0}, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "independently_terminal_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
