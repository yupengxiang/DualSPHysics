#!/usr/bin/env python3
"""Bounded production-artifact validator capability for the F3 graph paths.

This module is the common read-only envelope around
``f3_full_rollout_receipt_hdf5_validator_v1``.  It is deliberately not an
executor: it never starts an evaluator, never calls ``Popen``/``wait``, and
never writes registry, ledger, gate, completion, or PLAN state.

The envelope has two separate responsibilities:

* inspect a bounded, production-shaped receipt and cross-bind the evaluator
  JSON, trajectory HDF5, progress JSON, and validator artifact by exact path,
  byte count, SHA-256, and the same F3 identity; and
* keep authorization closed until a separately reviewed production capability
  is installed.  A JSON claim that a process used real ``Popen``/``wait`` is
  required for the contract, but is not itself an authorization token.

The only artifact-reading mode currently available to tests is an explicit
marked child of the OS temporary directory.  That permits small synthetic
HDF5/JSON fixtures to exercise the positive structural boundary without ever
opening a real production artifact.  A synthetic-only receipt is rejected
before any evaluator, progress, validator, or HDF5 content is opened.
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
import sys
import tempfile
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

import h5py
import numpy as np

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as base_validator


LAB_ROOT = Path(__file__).resolve().parents[1]
MODEL_KINDS = ("graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

SCHEMA = "core.f3.graph.terminal.production_validator_capability.v1"
INPUT_SCHEMA = f"{SCHEMA}.input"
REPORT_SCHEMA = f"{SCHEMA}.report"
PROCESS_PROOF_SCHEMA = f"{SCHEMA}.real_popen_wait_proof"
PROGRESS_SCHEMA = f"{SCHEMA}.progress_artifact"

REPORT_ID = "f3-graph-terminal-production-validator-capability-v1"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-TERMINAL-PRODUCTION-VALIDATOR-CAPABILITY-2026-09-29.json"
)

BASE_VALIDATOR_SCHEMA = base_validator.SCHEMA
ARTIFACT_NAMES = ("evaluation", "trajectory", "progress", "validator")
ARTIFACT_SUFFIXES = {
    "evaluation": ".json",
    "trajectory": ".h5",
    "progress": ".json",
    "validator": ".json",
}
ARTIFACT_SUFFIX_NAMES = {
    "evaluation": "-evaluation.json",
    "trajectory": "-trajectory.h5",
    "progress": "-evaluation-progress.json",
    "validator": "-hdf5-validation.json",
}

MAX_RECEIPT_BYTES = 512 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_HDF5_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(
    r"^f3-(graph_raw|graph_residual)500-hidden16-currentmanifest-seed"
    r"(17|29|43)-20[0-9]{6}-v3$"
)

FIXTURE_MARKER_NAME = ".f3-graph-terminal-production-validator-fixture-v1"
FIXTURE_MARKER_CONTENT = "f3_graph_terminal_production_validator_fixture_v1\n"

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

# The capability is intentionally absent.  A future separately reviewed
# change may install a private token; no receipt field, fake object, or
# caller-supplied boolean can grant it.
_PRODUCTION_VALIDATOR_CAPABILITY: object | None = None


class ValidationError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing bounded evidence."""


def _fail(message: str) -> None:
    raise ValidationError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_STRING_BYTES:
            _fail(f"{name} contains an oversized string")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        _fail(f"{name} is oversized")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
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


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256 digest")
    return result


def _absolute_path(value: Any, name: str) -> Path:
    raw = _string(value, name)
    candidate = Path(raw)
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in raw.split(os.sep)):
        _fail(f"{name} contains a lexical path alias")
    if Path(os.path.normpath(raw)) != candidate:
        _fail(f"{name} uses a lexical path alias")
    return candidate


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(path: Path, name: str) -> None:
    current = Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _regular_stat(path: Path, name: str, *, max_bytes: int) -> os.stat_result:
    _reject_symlink_components(path.parent, f"{name} parent")
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular non-symlink file")
    if info.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link")
    if info.st_size > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    return info


def _read_bounded_bytes(path: Path, name: str, *, max_bytes: int) -> bytes:
    before = _regular_stat(path, name, max_bytes=max_bytes)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name} read-only: {error}")
    chunks: list[bytes] = []
    total = 0
    try:
        opened = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            _fail(f"{name} changed before bounded read")
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                _fail(f"{name} exceeds bounded size {max_bytes}")
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != identity:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    after = _regular_stat(path, name, max_bytes=max_bytes)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ):
        _fail(f"{name} changed after bounded read")
    return b"".join(chunks)


def _load_json_file(path: Path, name: str, *, max_bytes: int) -> dict[str, Any]:
    # CLI receipt/report paths may be relative.  Make only this external
    # input path absolute; artifact paths remain strict absolute identities.
    if not path.is_absolute():
        path = Path(os.path.abspath(path))
    raw = _read_bounded_bytes(path, name, max_bytes=max_bytes)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    _walk_json(value, name)
    return dict(_mapping(value, name))


def _identity_namespace_name(model_kind: str, seed: int, nonce: str) -> str:
    model_segment = "graph_raw" if model_kind == "graph_raw" else "graph-residual"
    return f"f3-{model_segment}500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"


IDENTITY_FIELDS = frozenset(
    {
        "model_kind",
        "hidden",
        "seed",
        "case_id",
        "split",
        "transitions",
        "frames",
        "nonce",
        "run_id",
        "namespace",
        "fresh_namespace",
    }
)


def _validate_identity(value: Any) -> dict[str, Any]:
    identity = _mapping(value, "identity")
    _reject_unknown(identity, IDENTITY_FIELDS | {"identity_sha256"}, "identity")
    model_kind = _string(identity.get("model_kind"), "identity.model_kind")
    if model_kind not in MODEL_KINDS:
        _fail(f"identity.model_kind must be one of {MODEL_KINDS}")
    _exact(identity, "hidden", HIDDEN, "identity")
    seed = _strict_int(identity.get("seed"), "identity.seed", minimum=0)
    if seed not in SEEDS:
        _fail(f"identity.seed must be one of {SEEDS}")
    _exact(identity, "case_id", CASE_ID, "identity")
    _exact(identity, "split", SPLIT, "identity")
    _exact(identity, "transitions", TRANSITIONS, "identity")
    _exact(identity, "frames", FRAMES, "identity")
    nonce = _string(identity.get("nonce"), "identity.nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("identity.nonce must be a non-zero fresh 32-character lowercase hexadecimal value")
    run_id = _string(identity.get("run_id"), "identity.run_id")
    match = RUN_ID_RE.fullmatch(run_id)
    if match is None or match.group(1) != model_kind or int(match.group(2)) != seed:
        _fail("identity.run_id is not bound to the current graph model and seed")
    namespace = _absolute_path(identity.get("namespace"), "identity.namespace")
    if namespace.name != _identity_namespace_name(model_kind, seed, nonce):
        _fail("identity.namespace is not bound to model/seed/full835/nonce")
    temp_root = Path(tempfile.gettempdir()).resolve()
    report_root = (LAB_ROOT / "reports").resolve()
    if not (_under(namespace, temp_root) or _under(namespace, report_root)):
        _fail("identity.namespace must remain under /tmp or the lab reports root")
    _reject_symlink_components(namespace.parent, "identity.namespace parent")
    if not namespace.parent.is_dir():
        _fail("identity.namespace parent must exist")
    _exact(identity, "fresh_namespace", True, "identity")
    core = {key: identity[key] for key in sorted(IDENTITY_FIELDS)}
    digest = _sha(identity.get("identity_sha256"), "identity.identity_sha256")
    if digest != canonical_digest(core):
        _fail("identity.identity_sha256 does not bind the complete identity")
    return {**core, "identity_sha256": digest}


def _expected_artifact_path(namespace: str, name: str) -> Path:
    return Path(namespace + ARTIFACT_SUFFIX_NAMES[name])


def _validate_artifacts(
    value: Any,
    identity: Mapping[str, Any],
    binding_digest_value: Any,
) -> tuple[dict[str, Any], str]:
    artifacts_value = _mapping(value, "artifacts")
    _reject_unknown(artifacts_value, frozenset(ARTIFACT_NAMES), "artifacts")
    normalized: dict[str, Any] = {}
    for name in ARTIFACT_NAMES:
        item = _mapping(artifacts_value.get(name), f"artifacts.{name}")
        _reject_unknown(item, {"path", "sha256", "bytes", "identity_sha256"}, f"artifacts.{name}")
        path = _absolute_path(item.get("path"), f"artifacts.{name}.path")
        expected_path = _expected_artifact_path(str(identity["namespace"]), name)
        if path != expected_path:
            _fail(f"artifacts.{name}.path is not the exact fresh namespace output")
        if path.suffix != ARTIFACT_SUFFIXES[name]:
            _fail(f"artifacts.{name}.path has the wrong suffix")
        digest = _sha(item.get("sha256"), f"artifacts.{name}.sha256")
        size = _strict_int(item.get("bytes"), f"artifacts.{name}.bytes", minimum=1)
        maximum = MAX_HDF5_BYTES if name == "trajectory" else MAX_JSON_BYTES
        if size > maximum:
            _fail(f"artifacts.{name}.bytes exceeds its bounded limit")
        _exact(item, "identity_sha256", identity["identity_sha256"], f"artifacts.{name}")
        normalized[name] = {
            "path": str(path),
            "sha256": digest,
            "bytes": size,
            "identity_sha256": identity["identity_sha256"],
        }
    if len({item["path"] for item in normalized.values()}) != len(ARTIFACT_NAMES):
        _fail("artifacts must not alias one another")
    binding_digest = _sha(binding_digest_value, "artifact_binding_sha256")
    if binding_digest != canonical_digest(normalized):
        _fail("artifact_binding_sha256 does not bind all artifact path/SHA/bytes/identity refs")
    return normalized, binding_digest


PROCESS_PROOF_FIELDS = frozenset(
    {
        "schema",
        "status",
        "source",
        "synthetic_only",
        "real_popen_wait",
        "real_popen_type",
        "popen_type",
        "wait_observed",
        "natural_exit",
        "evaluator_pid",
        "evaluator_returncode",
        "wait_returncode",
        "model_kind",
        "hidden",
        "seed",
        "case_id",
        "split",
        "transitions",
        "frames",
        "nonce",
        "namespace",
        "identity_sha256",
        "artifact_binding_sha256",
        "namespace_fresh",
        "reuse_forbidden",
        "command",
        "command_sha256",
        "proof_sha256",
    }
)


def _validate_process_proof(value: Any, identity: Mapping[str, Any], binding_digest: str) -> dict[str, Any]:
    proof = _mapping(value, "process_proof")
    _reject_unknown(proof, PROCESS_PROOF_FIELDS, "process_proof")
    _exact(proof, "schema", PROCESS_PROOF_SCHEMA, "process_proof")
    _exact(proof, "status", "natural_exit_verified", "process_proof")
    _exact(proof, "source", "audited_executor", "process_proof")
    _exact(proof, "synthetic_only", False, "process_proof")
    for key, expected in (
        ("real_popen_wait", True),
        ("real_popen_type", True),
        ("wait_observed", True),
        ("natural_exit", True),
        ("evaluator_returncode", 0),
        ("wait_returncode", 0),
        ("namespace_fresh", True),
        ("reuse_forbidden", True),
    ):
        _exact(proof, key, expected, "process_proof")
    _exact(proof, "popen_type", "subprocess.Popen", "process_proof")
    _strict_int(proof.get("evaluator_pid"), "process_proof.evaluator_pid", minimum=1)
    for key in ("model_kind", "hidden", "seed", "case_id", "split", "transitions", "frames", "nonce", "namespace"):
        _exact(proof, key, identity[key], "process_proof")
    _exact(proof, "identity_sha256", identity["identity_sha256"], "process_proof")
    _exact(proof, "artifact_binding_sha256", binding_digest, "process_proof")
    command = proof.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        _fail("process_proof.command must be a non-empty string list")
    _exact(proof, "command_sha256", canonical_digest(command), "process_proof")
    proof_digest = _sha(proof.get("proof_sha256"), "process_proof.proof_sha256")
    core = dict(proof)
    core.pop("proof_sha256")
    if proof_digest != canonical_digest(core):
        _fail("process_proof.proof_sha256 does not bind the Popen/wait proof")
    return {**dict(proof), "proof_sha256": proof_digest}


def _validate_receipt(value: Any) -> dict[str, Any]:
    receipt = _mapping(value, "receipt")
    _reject_unknown(
        receipt,
        {"schema", "synthetic_only", "identity", "artifacts", "artifact_binding_sha256", "process_proof"},
        "receipt",
    )
    _exact(receipt, "schema", INPUT_SCHEMA, "receipt")
    # This check intentionally happens before any artifact stat/open operation.
    _exact(receipt, "synthetic_only", False, "receipt")
    identity = _validate_identity(receipt.get("identity"))
    artifacts, binding_digest = _validate_artifacts(
        receipt.get("artifacts"), identity, receipt.get("artifact_binding_sha256")
    )
    process_proof = _validate_process_proof(receipt.get("process_proof"), identity, binding_digest)
    return {
        "schema": INPUT_SCHEMA,
        "synthetic_only": False,
        "identity": identity,
        "artifacts": artifacts,
        "artifact_binding_sha256": binding_digest,
        "process_proof": process_proof,
    }


def _validate_fixture_root(value: Path | str) -> Path:
    root = _absolute_path(str(value), "fixture_root")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if root == temp_root or not _under(root, temp_root):
        _fail("fixture_root must be a private child of the OS temporary directory")
    _reject_symlink_components(root, "fixture_root")
    try:
        info = os.stat(root)
    except OSError as error:
        _fail(f"cannot inspect fixture_root: {error}")
    if not stat.S_ISDIR(info.st_mode):
        _fail("fixture_root must be a directory")
    marker = root / FIXTURE_MARKER_NAME
    raw = _read_bounded_bytes(marker, "fixture_root marker", max_bytes=256)
    if raw.decode("utf-8", errors="replace") != FIXTURE_MARKER_CONTENT:
        _fail("fixture_root marker does not match the bounded test-fixture contract")
    return root


def _load_artifact_bytes(ref: Mapping[str, Any], name: str, fixture_root: Path) -> bytes:
    path = Path(str(ref["path"]))
    if not _under(path, fixture_root) or path == fixture_root:
        _fail(f"{name} is outside the marked bounded fixture root")
    maximum = MAX_HDF5_BYTES if name == "trajectory" else MAX_JSON_BYTES
    raw = _read_bounded_bytes(path, name, max_bytes=maximum)
    if len(raw) != ref["bytes"]:
        _fail(f"{name} bytes disagree with the bound artifact identity")
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        _fail(f"{name} SHA-256 disagrees with the bound artifact identity")
    return raw


def _payload_identity(payload: Mapping[str, Any], identity: Mapping[str, Any], name: str) -> None:
    observed = _mapping(payload.get("f3_identity"), f"{name}.f3_identity")
    if dict(observed) != dict(identity):
        _fail(f"{name}.f3_identity is not exactly cross-bound to the receipt identity")
    _exact(payload, "identity_sha256", identity["identity_sha256"], name)


def _validate_evaluation_payload(
    payload: Mapping[str, Any], identity: Mapping[str, Any], artifacts: Mapping[str, Any]
) -> None:
    _payload_identity(payload, identity, "evaluation")
    cases = _mapping(payload.get("cases"), "evaluation.cases")
    row = _mapping(cases.get(CASE_ID), "evaluation.cases[selected]")
    _exact(row, "case_id", CASE_ID, "evaluation.cases[selected]")
    _exact(row, "trajectory_output", artifacts["trajectory"]["path"], "evaluation.cases[selected]")
    _exact(payload, "model_kind", identity["model_kind"], "evaluation")
    _exact(payload, "hidden", HIDDEN, "evaluation")
    _exact(payload, "seed", identity["seed"], "evaluation")
    _exact(payload, "split", SPLIT, "evaluation")
    _exact(payload, "transitions", TRANSITIONS, "evaluation")
    _exact(payload, "frames", FRAMES, "evaluation")
    _exact(payload, "nonce", identity["nonce"], "evaluation")
    _exact(payload, "synthetic_only", False, "evaluation")


def _validate_progress_payload(
    payload: Mapping[str, Any], identity: Mapping[str, Any], artifacts: Mapping[str, Any]
) -> None:
    allowed = {
        "schema", "status", "synthetic_only", "f3_identity", "identity_sha256",
        "model_kind", "hidden", "seed", "case_id", "split", "transitions", "frames", "nonce",
        "evaluation_path", "trajectory_path", "progress_path", "validator_path",
        "frames_executed", "trajectory_transitions", "trajectory_frames", "terminal",
        "execution_complete", "finite_rollout_complete", "future_state_inputs",
    }
    _reject_unknown(payload, allowed, "progress")
    _exact(payload, "schema", PROGRESS_SCHEMA, "progress")
    _exact(payload, "status", "completed", "progress")
    _exact(payload, "synthetic_only", False, "progress")
    _payload_identity(payload, identity, "progress")
    for key in ("model_kind", "hidden", "seed", "case_id", "split", "transitions", "frames", "nonce"):
        _exact(payload, key, identity[key], "progress")
    for key, artifact_name in (
        ("evaluation_path", "evaluation"),
        ("trajectory_path", "trajectory"),
        ("progress_path", "progress"),
        ("validator_path", "validator"),
    ):
        _exact(payload, key, artifacts[artifact_name]["path"], "progress")
    for key, expected in (
        ("frames_executed", TRANSITIONS),
        ("trajectory_transitions", TRANSITIONS),
        ("trajectory_frames", FRAMES),
        ("terminal", True),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("future_state_inputs", False),
    ):
        _exact(payload, key, expected, "progress")


def _validate_validator_payload(
    payload: Mapping[str, Any], identity: Mapping[str, Any], artifacts: Mapping[str, Any]
) -> None:
    _exact(payload, "schema", BASE_VALIDATOR_SCHEMA, "validator_artifact")
    _exact(payload, "passed", True, "validator_artifact")
    _exact(payload, "synthetic_only", False, "validator_artifact")
    _exact(payload, "diagnostic_only", True, "validator_artifact")
    _exact(payload, "qualification_credit", 0, "validator_artifact")
    _payload_identity(payload, identity, "validator_artifact")
    _exact(payload, "evaluation_json", artifacts["evaluation"]["path"], "validator_artifact")
    _exact(payload, "trajectory_hdf5", artifacts["trajectory"]["path"], "validator_artifact")
    _exact(payload, "progress_path", artifacts["progress"]["path"], "validator_artifact")
    _exact(payload, "validator_artifact_path", artifacts["validator"]["path"], "validator_artifact")
    _exact(payload, "case_id", CASE_ID, "validator_artifact")
    _exact(payload, "expected_transitions", TRANSITIONS, "validator_artifact")
    _exact(payload, "complete", True, "validator_artifact")
    checks = _mapping(payload.get("checks"), "validator_artifact.checks")
    _exact(checks, "trajectory_frames", FRAMES, "validator_artifact.checks")
    _exact(checks, "trajectory_transitions", TRANSITIONS, "validator_artifact.checks")


def _h5_attr_text(handle: h5py.File, key: str) -> str:
    if key not in handle.attrs:
        _fail(f"trajectory HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        _fail(f"trajectory HDF5 attribute {key} must be text")
    return value


def _h5_attr_int(handle: h5py.File, key: str, expected: int) -> None:
    if key not in handle.attrs:
        _fail(f"trajectory HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, np.integer):
        value = int(value)
    if type(value) is not int or value != expected:
        _fail(f"trajectory HDF5 attribute {key} must be {expected}")


def _h5_attr_bool(handle: h5py.File, key: str, expected: bool) -> None:
    if key not in handle.attrs:
        _fail(f"trajectory HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, np.bool_):
        value = bool(value)
    if type(value) is not bool or value is not expected:
        _fail(f"trajectory HDF5 attribute {key} must be {expected!r}")


def _validate_hdf5_identity(path: Path, identity: Mapping[str, Any]) -> None:
    # This is a read-only identity preflight.  The existing validator below
    # remains responsible for trajectory shape/time/finite/lifecycle checks.
    with h5py.File(path, "r") as handle:
        _exact(
            {
                "model_kind": _h5_attr_text(handle, "model_kind"),
                "case_id": _h5_attr_text(handle, "case_id"),
                "split": _h5_attr_text(handle, "split"),
                "nonce": _h5_attr_text(handle, "nonce"),
            },
            "model_kind",
            identity["model_kind"],
            "trajectory HDF5",
        )
        _exact({"case_id": _h5_attr_text(handle, "case_id")}, "case_id", CASE_ID, "trajectory HDF5")
        _exact({"split": _h5_attr_text(handle, "split")}, "split", SPLIT, "trajectory HDF5")
        _exact({"nonce": _h5_attr_text(handle, "nonce")}, "nonce", identity["nonce"], "trajectory HDF5")
        _h5_attr_int(handle, "hidden", HIDDEN)
        _h5_attr_int(handle, "seed", identity["seed"])
        _h5_attr_int(handle, "transitions", TRANSITIONS)
        _h5_attr_int(handle, "frames", FRAMES)
        _h5_attr_bool(handle, "future_state_inputs", False)
        _h5_attr_bool(handle, "autonomous_prediction", True)
        if "synthetic_fixture" in handle.attrs:
            _h5_attr_bool(handle, "synthetic_fixture", False)


def _inspect_bounded_fixture(
    normalized: Mapping[str, Any], fixture_root_value: Path | str
) -> dict[str, Any]:
    identity = normalized["identity"]
    artifacts = normalized["artifacts"]
    fixture_root = _validate_fixture_root(fixture_root_value)
    raw = {
        name: _load_artifact_bytes(ref, name, fixture_root)
        for name, ref in artifacts.items()
    }
    evaluation = _load_json_file(Path(artifacts["evaluation"]["path"]), "evaluation", max_bytes=MAX_JSON_BYTES)
    progress = _load_json_file(Path(artifacts["progress"]["path"]), "progress", max_bytes=MAX_JSON_BYTES)
    validator_payload = _load_json_file(Path(artifacts["validator"]["path"]), "validator_artifact", max_bytes=MAX_JSON_BYTES)
    _validate_evaluation_payload(evaluation, identity, artifacts)
    _validate_progress_payload(progress, identity, artifacts)
    _validate_validator_payload(validator_payload, identity, artifacts)

    trajectory_path = Path(artifacts["trajectory"]["path"])
    _validate_hdf5_identity(trajectory_path, identity)
    base_result = base_validator.run_validation(
        Path(artifacts["evaluation"]["path"]),
        trajectory_path,
        case_id=identity["case_id"],
        expected_transitions=TRANSITIONS,
    )
    if not isinstance(base_result, Mapping) or base_result.get("passed") is not True:
        _fail(f"wrapped read-only HDF5 validator did not pass: {base_result}")
    if base_result.get("case_id") != CASE_ID or base_result.get("complete") is not True:
        _fail("wrapped validator result is not a complete fixed-case result")
    if base_result.get("expected_transitions") != TRANSITIONS:
        _fail("wrapped validator result has the wrong transition denominator")
    # A second bounded digest read closes the small TOCTOU window introduced by
    # the wrapped validator's independent read-only HDF5 open.
    _load_artifact_bytes(artifacts["trajectory"], "trajectory", fixture_root)
    return {
        "status": "structurally_validated_bounded_fixture",
        "passed": True,
        "base_validator_schema": BASE_VALIDATOR_SCHEMA,
        "base_validator_result": dict(base_result),
        "trajectory_sha256": artifacts["trajectory"]["sha256"],
        "trajectory_bytes": artifacts["trajectory"]["bytes"],
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "case_id": CASE_ID,
        "fixture_root": str(fixture_root),
        "bytes_loaded": {name: len(value) for name, value in raw.items()},
    }


def _empty_hdf5_result() -> dict[str, Any]:
    return {
        "status": "not_run",
        "passed": False,
        "production_artifact_opened": False,
    }


def _default_boundary() -> dict[str, Any]:
    return {
        "receipt_json_opened": False,
        "evaluation_json_opened": False,
        "trajectory_hdf5_opened": False,
        "progress_json_opened": False,
        "validator_artifact_opened": False,
        "temporary_fixture_artifacts_opened": False,
        "production_artifacts_opened": False,
        "bounded_read_only": True,
        "popen_attempted": False,
        "wait_attempted": False,
    }


def _blocked_report(
    reasons: Sequence[str],
    *,
    normalized: Mapping[str, Any] | None = None,
    structural: Mapping[str, Any] | None = None,
    boundary: Mapping[str, Any] | None = None,
    synthetic_rejected: bool = False,
) -> dict[str, Any]:
    identity = normalized.get("identity") if isinstance(normalized, Mapping) else None
    artifacts = normalized.get("artifacts") if isinstance(normalized, Mapping) else None
    process_proof = normalized.get("process_proof") if isinstance(normalized, Mapping) else None
    base_validation = (
        dict(structural["base_validator_result"])
        if isinstance(structural, Mapping) and "base_validator_result" in structural
        else None
    )
    if isinstance(base_validation, Mapping):
        checks = base_validation.get("checks")
        checks = checks if isinstance(checks, Mapping) else {}
        hdf5_validation: dict[str, Any] = {
            "status": "wrapped_read_only_validator_passed",
            "passed": True,
            "schema": BASE_VALIDATOR_SCHEMA,
            "case_id": base_validation.get("case_id"),
            "expected_transitions": base_validation.get("expected_transitions"),
            "trajectory_frames": checks.get("trajectory_frames"),
            "trajectory_transitions": checks.get("trajectory_transitions"),
            "production_artifact_opened": False,
        }
    else:
        hdf5_validation = _empty_hdf5_result()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "capability_admitted": False,
        "production_validator_capability_installed": _PRODUCTION_VALIDATOR_CAPABILITY is not None,
        "launch_allowed": False,
        "source_bound": bool(normalized is not None and structural is not None),
        "structural_validation": dict(structural or {"status": "not_run", "passed": False}),
        "identity": dict(identity or {}),
        "artifact_bindings": dict(artifacts or {}),
        "real_popen_wait_proof_required": True,
        "real_popen_wait_proof_present": bool(process_proof is not None),
        "real_popen_wait_verified": False,
        "synthetic_only_receipt_rejected": synthetic_rejected,
        "hdf5_validation": hdf5_validation,
        "expected_contract": {
            "model_kinds": list(MODEL_KINDS),
            "hidden": HIDDEN,
            "seeds": list(SEEDS),
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "fresh_nonce": "non-zero-lowercase-32-hex",
            "artifacts": list(ARTIFACT_NAMES),
            "path_sha256_bytes_identity_cross_binding": True,
            "real_popen_wait_proof_required": True,
            "synthetic_only_receipt_admitted": False,
            "wrapped_validator_schema": BASE_VALIDATOR_SCHEMA,
        },
        "proof_status": {
            "synthetic_only_receipt_admitted": False,
            "real_popen_wait_claimed": bool(
                isinstance(process_proof, Mapping) and process_proof.get("real_popen_wait") is True
            ),
            "real_popen_wait_verified": False,
            "popen_started_by_validator": False,
            "wait_called_by_validator": False,
            "capability_token_required": True,
        },
        "input_boundary": {**_default_boundary(), **dict(boundary or {})},
        "side_effects": {
            "runtime_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "evaluator_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
            "synthetic_receipts_minted": 0,
        },
        "blocked_reasons": sorted({str(reason) for reason in reasons if reason}),
        **ZERO_CREDIT,
    }
    return report


def build_report(
    receipt: Mapping[str, Any] | None = None,
    *,
    fixture_root: Path | str | None = None,
) -> dict[str, Any]:
    """Inspect bounded test fixtures and always return a zero-credit report."""
    if receipt is None:
        return _blocked_report(
            (
                "no production receipt was supplied",
                "production validator capability is not installed",
                "real Popen/wait proof is required and cannot be self-authorized",
            )
        )
    try:
        normalized = _validate_receipt(receipt)
        if fixture_root is None:
            return _blocked_report(
                (
                    "production artifact reads are denied while the capability is ungranted",
                    "an explicit marked temporary fixture root is required for bounded tests",
                    "production validator capability is not installed",
                    "real Popen/wait proof is required and cannot be self-authorized",
                ),
                normalized=normalized,
            )
        structural = _inspect_bounded_fixture(normalized, fixture_root)
        return _blocked_report(
            (
                "production validator capability is not installed",
                "real Popen/wait proof is a required input but is not an authorization token",
                "capability admission remains fail-closed and credit is zero",
            ),
            normalized=normalized,
            structural=structural,
            boundary={
                "evaluation_json_opened": True,
                "trajectory_hdf5_opened": True,
                "progress_json_opened": True,
                "validator_artifact_opened": True,
                "temporary_fixture_artifacts_opened": True,
                "production_artifacts_opened": False,
            },
        )
    except (ValidationError, OSError, TypeError, ValueError) as error:
        message = str(error)
        return _blocked_report(
            (
                message,
                "synthetic-only receipts are rejected before artifact reads",
                "production validator capability is not installed",
                "real Popen/wait proof is required and cannot be self-authorized",
            ),
            synthetic_rejected="synthetic_only" in message,
        )


def run_validation(
    receipt: Mapping[str, Any] | None = None,
    *,
    fixture_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe, read-only, fail-closed capability report."""
    return build_report(receipt, fixture_root=fixture_root)


REPORT_KEYS = frozenset(
    {
        "schema", "report_id", "status", "capability_admitted",
        "production_validator_capability_installed", "launch_allowed", "source_bound",
        "structural_validation", "identity", "artifact_bindings", "real_popen_wait_proof_required",
        "real_popen_wait_proof_present", "real_popen_wait_verified", "synthetic_only_receipt_rejected",
        "hdf5_validation", "expected_contract", "proof_status", "input_boundary", "side_effects",
        "blocked_reasons", *ZERO_CREDIT.keys(),
    }
)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_unknown(report, REPORT_KEYS, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        for key, expected in (
            ("capability_admitted", False),
            ("production_validator_capability_installed", False),
            ("launch_allowed", False),
            ("real_popen_wait_proof_required", True),
            ("real_popen_wait_verified", False),
        ):
            _exact(report, key, expected, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key in ("production_artifacts_opened", "popen_attempted", "wait_attempted"):
            _exact(boundary, key, False, "report.input_boundary")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in (
            "runtime_started", "evaluator_started", "solver_started", "worker_started",
            "gpu_used_for_execution", "registry_writes", "ledger_writes", "gate_writes",
            "completion_writes", "plan_writes", "synthetic_receipts_minted",
        ):
            value = side_effects.get(key)
            if value not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (ValidationError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    structural = report.get("structural_validation", {})
    return "\n".join(
        [
            "# F3 graph terminal production-validator capability",
            "",
            f"- status: `{report.get('status')}`",
            f"- capability_admitted: `{report.get('capability_admitted')}`",
            f"- structural_validation: `{structural.get('status')}`",
            f"- real Popen/wait verified: `{report.get('real_popen_wait_verified')}`",
            "- contract: hidden16 / fixed case / test split / 835 transitions / 836 frames",
            "- artifacts: evaluator JSON + trajectory HDF5 + progress JSON + validator artifact",
            "- synthetic-only receipt: rejected; production capability: not installed",
            "- credit: `0`; no evaluator/solver/worker/GPU/queue or ledger/gate mutation",
            "",
            "## Blockers",
            "",
            *[f"- {item}" for item in report.get("blocked_reasons", [])],
            "",
        ]
    )


def _load_receipt_path(path: Path) -> dict[str, Any]:
    return _load_json_file(path, "receipt", max_bytes=MAX_RECEIPT_BYTES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--fixture-root", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.verify_report is not None:
        report = _load_json_file(args.verify_report, "report", max_bytes=MAX_RECEIPT_BYTES)
        errors = validate_report(report)
        if errors:
            print(canonical_json({"valid": False, "errors": errors}))
            return 1
        print(canonical_json({"valid": True, "schema": REPORT_SCHEMA}))
        return 0

    receipt = _load_receipt_path(args.receipt) if args.receipt is not None else None
    report = build_report(receipt, fixture_root=args.fixture_root)
    if args.report_output is not None:
        args.report_output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
