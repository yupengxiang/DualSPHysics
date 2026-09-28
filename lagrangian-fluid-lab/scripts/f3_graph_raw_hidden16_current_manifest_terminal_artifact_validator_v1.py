#!/usr/bin/env python3
"""Bounded synthetic terminal HDF5/artifact validator capability contract.

This contract is deliberately independent from the existing rollout validator,
terminal runtime verifier, and audited executor.  It is a diagnostic sidecar,
not a producer of terminal evidence and not an execution authority.

Only a temporary synthetic fixture is allowed to be opened as HDF5.  The
fixture must live below the operating-system temporary directory, contain an
exact marker file, contain no symlink path component, and remain a bounded
single-link regular file while it is read.  Manifest, training receipt,
checkpoint, and evaluation identities are checked only as bounded metadata;
their contents are never opened here.

The structural observation can therefore say that a synthetic 835-transition /
836-frame artifact is internally consistent, but the capability remains
``blocked_fail_closed`` unless independently produced metadata includes real
producer and terminal proofs.  Synthetic proof claims are explicitly
non-authorizing.  This module never starts, stops, or restarts a process and
never touches a solver, worker, GPU, queue, registry, ledger, gate, or PLAN.
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

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import h5py
import numpy as np


MODEL_KIND = "graph_raw"
HIDDEN = 16
SEEDS = (17, 29, 43)
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.terminal_artifact_validator.v1"
INPUT_SCHEMA = f"{SCHEMA}.input"
REPORT_SCHEMA = f"{SCHEMA}.report"
TERMINAL_IDENTITY_SCHEMA = f"{SCHEMA}.terminal_identity"
PROOF_SCHEMA = f"{SCHEMA}.proof"
VALIDATOR_METADATA_SCHEMA = f"{SCHEMA}.independent_validator_metadata"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-terminal-artifact-validator-v1"

REPORT_JSON_FILENAME = (
    "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TERMINAL-ARTIFACT-"
    "VALIDATOR-CANARY-2026-09-29.json"
)
REPORT_MARKDOWN_FILENAME = REPORT_JSON_FILENAME.removesuffix(".json") + ".zh-CN.md"

SYNTHETIC_MARKER_NAME = ".f3-graph-raw-terminal-hdf5-synthetic-v1"
SYNTHETIC_MARKER_CONTENT = (
    "f3_graph_raw_hidden16_terminal_hdf5_synthetic_fixture_v1\n"
)
MAX_METADATA_BYTES = 512 * 1024
MAX_HDF5_BYTES = 32 * 1024 * 1024
MAX_HDF5_ELEMENTS = 8_000_000
MAX_PARTICLES = 8192
MAX_STRING_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_TEMPLATE = (
    "f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3"
)
NAMESPACE_TEMPLATE = (
    "f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
)
ARTIFACT_NAMES = (
    "manifest",
    "training_receipt",
    "checkpoint",
    "evaluation_artifact",
    "trajectory",
)
ARTIFACT_SUFFIXES = {
    "manifest": ".json",
    "training_receipt": ".json",
    "checkpoint": ".pt",
    "evaluation_artifact": ".json",
    "trajectory": ".h5",
}

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "synthetic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}


class ValidationError(ValueError):
    """Malformed, unsafe, or non-authorizing bounded evidence."""


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


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256 digest")
    return result


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown keys: {unknown}")


def _absolute_path(value: Any, name: str) -> Path:
    if isinstance(value, Path):
        raw = str(value)
        if not raw or "\x00" in raw:
            _fail(f"{name} must be a non-empty path")
    else:
        raw = _string(value, name)
    candidate = Path(raw)
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in raw.split(os.sep)):
        _fail(f"{name} contains a lexical path alias")
    normalized = Path(os.path.normpath(raw))
    if normalized != candidate:
        _fail(f"{name} uses a lexical path alias")
    return candidate


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool = False) -> None:
    current = Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _regular_stat(path: Path, name: str, *, max_bytes: int | None = None) -> os.stat_result:
    _reject_symlink_components(path.parent, f"{name} parent")
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular non-symlink file")
    if info.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link")
    if max_bytes is not None and info.st_size > max_bytes:
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
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
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
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
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


def _load_json(path: Path, name: str, *, max_bytes: int) -> dict[str, Any]:
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


def _synthetic_fixture_root(value: Any) -> Path:
    root = _absolute_path(value, "fixture_root")
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
    marker = root / SYNTHETIC_MARKER_NAME
    marker_raw = _read_bounded_bytes(marker, "synthetic fixture marker", max_bytes=256)
    if marker_raw.decode("utf-8", errors="replace") != SYNTHETIC_MARKER_CONTENT:
        _fail("synthetic fixture marker does not match the bounded contract")
    return root


def _validate_artifact(value: Any, name: str, *, expected_suffix: str) -> dict[str, Any]:
    artifact = _mapping(value, name)
    _reject_unknown(artifact, frozenset({"path", "sha256", "bytes"}), name)
    path = _absolute_path(artifact.get("path"), f"{name}.path")
    if path.suffix != expected_suffix:
        _fail(f"{name}.path must use suffix {expected_suffix!r}")
    digest = _sha(artifact.get("sha256"), f"{name}.sha256")
    size = _strict_int(artifact.get("bytes"), f"{name}.bytes", minimum=1)
    if size > MAX_HDF5_BYTES * 16:
        _fail(f"{name}.bytes exceeds the bounded identity limit")
    return {"path": str(path), "sha256": digest, "bytes": size}


def _validate_identity(value: Any, name: str) -> dict[str, Any]:
    identity = _mapping(value, name)
    allowed = frozenset(
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
        }
    )
    _reject_unknown(identity, allowed, name)
    _exact(identity, "model_kind", MODEL_KIND, name)
    _exact(identity, "hidden", HIDDEN, name)
    seed = _strict_int(identity.get("seed"), f"{name}.seed", minimum=0)
    if seed not in SEEDS:
        _fail(f"{name}.seed must be one of {SEEDS}")
    _exact(identity, "case_id", CASE_ID, name)
    _exact(identity, "split", SPLIT, name)
    _exact(identity, "transitions", TRANSITIONS, name)
    _exact(identity, "frames", FRAMES, name)
    nonce = _string(identity.get("nonce"), f"{name}.nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name}.nonce must be a non-zero 32-character lowercase hexadecimal value")
    run_id = _string(identity.get("run_id"), f"{name}.run_id")
    expected_run_id = RUN_ID_TEMPLATE.format(seed=seed)
    if run_id != expected_run_id:
        _fail(f"{name}.run_id is not bound to the current graph_raw seed receipt")
    namespace = _absolute_path(identity.get("namespace"), f"{name}.namespace")
    if namespace.name != NAMESPACE_TEMPLATE.format(seed=seed, nonce=nonce):
        _fail(f"{name}.namespace is not bound to seed/full835/nonce")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not _under(namespace, temp_root):
        _fail(f"{name}.namespace must remain under the temporary boundary")
    return {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "seed": seed,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "nonce": nonce,
        "run_id": run_id,
        "namespace": str(namespace),
    }


def _validate_proof(value: Any, name: str, *, kind: str) -> dict[str, Any]:
    proof = _mapping(value, name)
    allowed = frozenset(
        {"schema", "kind", "status", "source_bound", "synthetic_only", "real_proof", "proof_sha256"}
    )
    _reject_unknown(proof, allowed, name)
    _exact(proof, "schema", PROOF_SCHEMA, name)
    _exact(proof, "kind", kind, name)
    _exact(proof, "status", "synthetic_fixture_only", name)
    _exact(proof, "source_bound", True, name)
    _exact(proof, "synthetic_only", True, name)
    _exact(proof, "real_proof", False, name)
    digest = _sha(proof.get("proof_sha256"), f"{name}.proof_sha256")
    core = dict(proof)
    core.pop("proof_sha256")
    if digest != canonical_digest(core):
        _fail(f"{name}.proof_sha256 does not bind the proof metadata")
    return dict(proof)


def _validate_terminal_identity(value: Any, identity: Mapping[str, Any]) -> dict[str, Any]:
    name = "terminal_identity"
    terminal = _mapping(value, name)
    allowed = frozenset(
        {
            "schema",
            "status",
            "model_kind",
            "hidden",
            "seed",
            "case_id",
            "split",
            "transitions",
            "frames",
            "frames_executed",
            "trajectory_transitions",
            "trajectory_frames",
            "terminal",
            "execution_complete",
            "finite_rollout_complete",
            "future_state_inputs",
            "source_bound",
            "synthetic_only",
            "producer_proof",
            "terminal_proof",
            "identity_sha256",
        }
    )
    _reject_unknown(terminal, allowed, name)
    _exact(terminal, "schema", TERMINAL_IDENTITY_SCHEMA, name)
    _exact(terminal, "status", "completed", name)
    for key in ("model_kind", "case_id", "split", "seed", "hidden", "transitions", "frames"):
        _exact(terminal, key, identity[key], name)
    for key, expected in (
        ("frames_executed", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("trajectory_frames", FRAMES),
        ("terminal", True),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("future_state_inputs", False),
        ("source_bound", True),
        ("synthetic_only", True),
    ):
        _exact(terminal, key, expected, name)
    producer = _validate_proof(terminal.get("producer_proof"), f"{name}.producer_proof", kind="producer")
    terminal_proof = _validate_proof(terminal.get("terminal_proof"), f"{name}.terminal_proof", kind="terminal")
    digest = _sha(terminal.get("identity_sha256"), f"{name}.identity_sha256")
    core = dict(terminal)
    core.pop("identity_sha256")
    if digest != canonical_digest(core):
        _fail(f"{name}.identity_sha256 does not bind terminal identity")
    return {
        **{key: terminal[key] for key in allowed if key in terminal and key not in {"identity_sha256"}},
        "producer_proof": producer,
        "terminal_proof": terminal_proof,
        "identity_sha256": digest,
    }


def _validate_validator_metadata(
    value: Any,
    identity: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    name = "validator_metadata"
    metadata = _mapping(value, name)
    allowed = frozenset(
        {
            "schema",
            "producer_id",
            "producer_version",
            "independent",
            "source_bound",
            "synthetic_only",
            "artifact",
            "observed",
            "metadata_sha256",
        }
    )
    _reject_unknown(metadata, allowed, name)
    _exact(metadata, "schema", VALIDATOR_METADATA_SCHEMA, name)
    producer_id = _string(metadata.get("producer_id"), f"{name}.producer_id")
    if producer_id == REPORT_ID or producer_id == SCHEMA:
        _fail(f"{name}.producer_id must be independent from this contract")
    _exact(metadata, "producer_version", "synthetic-bounded-v1", name)
    _exact(metadata, "independent", True, name)
    _exact(metadata, "source_bound", True, name)
    _exact(metadata, "synthetic_only", True, name)
    artifact = _validate_artifact(metadata.get("artifact"), f"{name}.artifact", expected_suffix=".h5")
    if artifact != dict(trajectory):
        _fail(f"{name}.artifact does not equal artifacts.trajectory")
    observed = _mapping(metadata.get("observed"), f"{name}.observed")
    _reject_unknown(
        observed,
        frozenset(
            {
                "model_kind",
                "hidden",
                "seed",
                "case_id",
                "split",
                "transitions",
                "frames",
                "nonce",
                "trajectory_sha256",
                "trajectory_bytes",
                "terminal_identity_sha256",
            }
        ),
        f"{name}.observed",
    )
    for key in ("model_kind", "hidden", "seed", "case_id", "split", "transitions", "frames", "nonce"):
        _exact(observed, key, identity[key], f"{name}.observed")
    _exact(observed, "trajectory_sha256", trajectory["sha256"], f"{name}.observed")
    _exact(observed, "trajectory_bytes", trajectory["bytes"], f"{name}.observed")
    _exact(observed, "terminal_identity_sha256", terminal["identity_sha256"], f"{name}.observed")
    digest = _sha(metadata.get("metadata_sha256"), f"{name}.metadata_sha256")
    core = dict(metadata)
    core.pop("metadata_sha256")
    if digest != canonical_digest(core):
        _fail(f"{name}.metadata_sha256 does not bind independent validator metadata")
    return {**dict(metadata), "artifact": artifact, "observed": dict(observed), "metadata_sha256": digest}


def _validate_input(value: Any) -> dict[str, Any]:
    input_value = _mapping(value, "validator_input")
    _reject_unknown(
        input_value,
        frozenset({"schema", "identity", "artifacts", "terminal_identity", "validator_metadata"}),
        "validator_input",
    )
    _exact(input_value, "schema", INPUT_SCHEMA, "validator_input")
    identity = _validate_identity(input_value.get("identity"), "identity")
    artifacts_value = _mapping(input_value.get("artifacts"), "artifacts")
    _reject_unknown(artifacts_value, frozenset(ARTIFACT_NAMES), "artifacts")
    artifacts = {
        name: _validate_artifact(
            artifacts_value.get(name),
            f"artifacts.{name}",
            expected_suffix=ARTIFACT_SUFFIXES[name],
        )
        for name in ARTIFACT_NAMES
    }
    paths = [artifact["path"] for artifact in artifacts.values()]
    if len(paths) != len(set(paths)):
        _fail("artifacts must not alias one another")
    terminal = _validate_terminal_identity(input_value.get("terminal_identity"), identity)
    validator_metadata = _validate_validator_metadata(
        input_value.get("validator_metadata"), identity, artifacts["trajectory"], terminal
    )
    return {
        "schema": INPUT_SCHEMA,
        "identity": identity,
        "artifacts": artifacts,
        "terminal_identity": terminal,
        "validator_metadata": validator_metadata,
    }


def _h5_attr_text(handle: h5py.File, key: str) -> str:
    if key not in handle.attrs:
        _fail(f"HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        _fail(f"HDF5 attribute {key} must be text")
    return value


def _h5_attr_bool(handle: h5py.File, key: str, expected: bool) -> None:
    if key not in handle.attrs:
        _fail(f"HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, np.bool_):
        value = bool(value)
    if type(value) is not bool or value is not expected:
        _fail(f"HDF5 attribute {key} must be {expected!r}")


def _h5_attr_int(handle: h5py.File, key: str, expected: int) -> None:
    if key not in handle.attrs:
        _fail(f"HDF5 attribute {key} is missing")
    value = handle.attrs[key]
    if isinstance(value, np.integer):
        value = int(value)
    if type(value) is not int or value != expected:
        _fail(f"HDF5 attribute {key} must be {expected}")


def _read_identity_dataset(handle: h5py.File, key: str, particles: int) -> np.ndarray:
    if key not in handle:
        _fail(f"HDF5 dataset {key} is missing")
    dataset = handle[key]
    if dataset.shape != (particles,) or dataset.dtype.kind not in "iu":
        _fail(f"HDF5 {key} must be a one-dimensional integer identity axis")
    values = np.asarray(dataset[...])
    if values.dtype.kind == "u" and values.size and int(values.max()) > np.iinfo(np.int64).max:
        _fail(f"HDF5 {key} exceeds int64 identity range")
    return values.astype(np.int64, copy=False)


def _validate_synthetic_hdf5(
    path_value: Any,
    fixture_root_value: Any,
    identity: Mapping[str, Any],
    trajectory_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    root = _synthetic_fixture_root(fixture_root_value)
    path = _absolute_path(path_value, "trajectory_hdf5")
    if path.suffix != ".h5":
        _fail("trajectory_hdf5 must use the .h5 suffix")
    if not _under(path, root) or path == root:
        _fail("trajectory_hdf5 must remain inside the marked synthetic fixture root")
    _reject_symlink_components(path, "trajectory_hdf5")
    info = _regular_stat(path, "trajectory_hdf5", max_bytes=MAX_HDF5_BYTES)
    if int(info.st_size) != trajectory_artifact["bytes"]:
        _fail("trajectory_hdf5 bytes disagree with the bound artifact identity")
    raw = _read_bounded_bytes(path, "trajectory_hdf5", max_bytes=MAX_HDF5_BYTES)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != trajectory_artifact["sha256"]:
        _fail("trajectory_hdf5 SHA-256 disagrees with the bound artifact identity")

    try:
        with h5py.File(path, "r") as handle:
            required = {
                "time",
                "position",
                "velocity",
                "particle_id",
                "particle_zone",
                "mass",
                "valid",
            }
            missing = required - set(handle)
            if missing:
                _fail(f"HDF5 is missing datasets: {sorted(missing)}")
            _h5_attr_text(handle, "model_kind")
            if _h5_attr_text(handle, "model_kind") != identity["model_kind"]:
                _fail("HDF5 model_kind disagrees with identity")
            if _h5_attr_text(handle, "case_id") != identity["case_id"]:
                _fail("HDF5 case_id disagrees with identity")
            if _h5_attr_text(handle, "split") != identity["split"]:
                _fail("HDF5 split disagrees with identity")
            _h5_attr_int(handle, "seed", identity["seed"])
            _h5_attr_int(handle, "transitions", TRANSITIONS)
            _h5_attr_int(handle, "frames", FRAMES)
            if _h5_attr_text(handle, "nonce") != identity["nonce"]:
                _fail("HDF5 nonce disagrees with identity")
            _h5_attr_bool(handle, "future_state_inputs", False)
            _h5_attr_bool(handle, "autonomous_prediction", True)
            _h5_attr_bool(handle, "synthetic_fixture", True)
            _h5_attr_bool(handle, "terminal", True)
            _h5_attr_bool(handle, "execution_complete", True)
            _h5_attr_bool(handle, "finite_rollout_complete", True)

            time_dataset = handle["time"]
            if time_dataset.shape != (FRAMES,) or time_dataset.dtype.kind not in "fiu":
                _fail("HDF5 time must have exactly 836 finite numeric frames")
            times = np.asarray(time_dataset[...], dtype=np.float64)
            if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
                _fail("HDF5 time must be finite and strictly increasing")

            position = handle["position"]
            velocity = handle["velocity"]
            if len(position.shape) != 3 or position.shape[0] != FRAMES or position.shape[2] != 3:
                _fail("HDF5 position must have shape [836, particles, 3]")
            if velocity.shape != position.shape:
                _fail("HDF5 velocity shape must equal position shape")
            particles = int(position.shape[1])
            if not 1 <= particles <= MAX_PARTICLES:
                _fail("HDF5 particle count is outside the bounded range")
            if int(position.size) > MAX_HDF5_ELEMENTS:
                _fail("HDF5 position exceeds the bounded element count")
            if position.dtype.kind not in "fiu" or velocity.dtype.kind not in "fiu":
                _fail("HDF5 position and velocity must use numeric dtypes")
            particle_id = _read_identity_dataset(handle, "particle_id", particles)
            particle_zone = _read_identity_dataset(handle, "particle_zone", particles)
            composite = np.column_stack((particle_zone, particle_id))
            if len(np.unique(composite, axis=0)) != particles:
                _fail("HDF5 composite particle identities are not unique")

            valid_dataset = handle["valid"]
            if valid_dataset.shape != (FRAMES, particles) or valid_dataset.dtype.kind not in "biu":
                _fail("HDF5 valid must have shape [836, particles] and binary dtype")
            valid_raw = np.asarray(valid_dataset[...])
            if not np.isin(valid_raw, (0, 1)).all():
                _fail("HDF5 valid must contain only 0/1 values")
            valid = valid_raw.astype(bool, copy=False)
            initial_valid = np.array(valid[0], dtype=bool, copy=True)
            if not initial_valid.any() or not np.all(valid == initial_valid[None, :]):
                _fail("HDF5 valid lifecycle must remain constant through terminal frames")

            position_values = np.asarray(position[...], dtype=np.float64)
            velocity_values = np.asarray(velocity[...], dtype=np.float64)
            active = valid[:, :, None]
            if not np.isfinite(position_values[active.repeat(3, axis=2)]).all():
                _fail("HDF5 active position values are not finite")
            if not np.isfinite(velocity_values[active.repeat(3, axis=2)]).all():
                _fail("HDF5 active velocity values are not finite")

            mass = handle["mass"]
            if mass.shape not in ((particles,), (FRAMES, particles)):
                _fail("HDF5 mass must have shape [particles] or [836, particles]")
            mass_values = np.asarray(mass[...], dtype=np.float64)
            if not np.isfinite(mass_values).all() or np.any(mass_values <= 0):
                _fail("HDF5 mass must be finite and positive")
            if mass.ndim == 2 and not np.array_equal(
                mass_values,
                np.broadcast_to(mass_values[0], mass_values.shape),
            ):
                _fail("HDF5 temporal mass must remain constant")
    except OSError as error:
        _fail(f"cannot read bounded synthetic HDF5: {error}")

    after = _regular_stat(path, "trajectory_hdf5", max_bytes=MAX_HDF5_BYTES)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    ):
        _fail("trajectory_hdf5 changed during bounded validation")
    return {
        "status": "validated_bounded_synthetic",
        "passed": True,
        "path": str(path),
        "sha256": digest,
        "bytes": int(info.st_size),
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "particle_count": particles,
        "time_start": float(times[0]),
        "time_end": float(times[-1]),
        "datasets_checked": sorted(required),
        "future_state_inputs": False,
        "synthetic_fixture": True,
    }


def _empty_hdf5_result() -> dict[str, Any]:
    return {
        "status": "not_run",
        "passed": False,
        "synthetic_fixture": True,
        "production_artifact_opened": False,
    }


def _blocked_report(*, reasons: Sequence[str], metadata: Mapping[str, Any] | None = None,
                    hdf5: Mapping[str, Any] | None = None,
                    input_boundary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    identity = metadata.get("identity") if isinstance(metadata, Mapping) else None
    artifacts = metadata.get("artifacts") if isinstance(metadata, Mapping) else None
    terminal = metadata.get("terminal_identity") if isinstance(metadata, Mapping) else None
    validator_metadata = metadata.get("validator_metadata") if isinstance(metadata, Mapping) else None
    identity_bound = isinstance(identity, Mapping)
    terminal_bound = isinstance(terminal, Mapping)
    validator_bound = isinstance(validator_metadata, Mapping)
    artifact_bindings = dict(artifacts) if isinstance(artifacts, Mapping) else {}
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "capability_admitted": False,
        "launch_allowed": False,
        "source_bound": identity_bound and terminal_bound and validator_bound,
        "identity_bound": identity_bound,
        "terminal_identity_bound": terminal_bound,
        "independent_validator_metadata_bound": validator_bound,
        "real_producer_proof": False,
        "real_terminal_proof": False,
        "hdf5_validation": dict(hdf5 or _empty_hdf5_result()),
        "artifact_bindings": artifact_bindings,
        "expected_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seeds": list(SEEDS),
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "nonce": "fresh-nonzero-32-hex-required",
            "path_sha256_bytes": True,
            "temporary_synthetic_hdf5_only": True,
            "real_producer_and_terminal_proof_required_for_admission": True,
        },
        "proof_status": {
            "producer_proof_present": bool(
                isinstance(terminal, Mapping) and "producer_proof" in terminal
            ),
            "terminal_proof_present": bool(
                isinstance(terminal, Mapping) and "terminal_proof" in terminal
            ),
            "real_producer_proof": False,
            "real_terminal_proof": False,
            "synthetic_proof_authorizes": False,
        },
        "input_boundary": {
            "metadata_mode": "bounded_json_only",
            "trajectory_mode": "temporary_synthetic_fixture_only",
            "production_trajectory_opened": False,
            "production_checkpoint_opened": False,
            "production_evaluation_opened": False,
            "production_manifest_opened": False,
            "temporary_synthetic_hdf5_opened": bool(
                isinstance(hdf5, Mapping) and hdf5.get("status") == "validated_bounded_synthetic"
            ),
            **dict(input_boundary or {}),
        },
        "side_effects": {
            "runtime_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
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
        "blocked_reasons": sorted(set(str(reason) for reason in reasons if reason)),
        **ZERO_CREDIT,
    }
    return report


def build_report(
    metadata: Mapping[str, Any] | None = None,
    *,
    trajectory_hdf5: Path | str | None = None,
    fixture_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a bounded diagnostic report without admitting execution."""
    if metadata is None:
        return _blocked_report(
            reasons=(
                "no bounded validator metadata was supplied",
                "real producer proof is absent",
                "real terminal proof is absent",
                "terminal artifact capability is diagnostic-only and not admitted",
            )
        )
    try:
        normalized = _validate_input(metadata)
        identity = normalized["identity"]
        if fixture_root is None:
            _fail("fixture_root is required for every HDF5 read")
        if trajectory_hdf5 is None:
            trajectory_hdf5 = normalized["artifacts"]["trajectory"]["path"]
        if str(trajectory_hdf5) != normalized["artifacts"]["trajectory"]["path"]:
            _fail("trajectory_hdf5 path differs from the bound trajectory artifact")
        hdf5 = _validate_synthetic_hdf5(
            trajectory_hdf5,
            fixture_root,
            identity,
            normalized["artifacts"]["trajectory"],
        )
        reasons = (
            "real producer proof is absent; synthetic producer proof cannot authorize execution",
            "real terminal proof is absent; synthetic terminal proof cannot authorize execution",
            "terminal artifact capability remains diagnostic-only and launch is not admitted",
        )
        return _blocked_report(
            reasons=reasons,
            metadata=normalized,
            hdf5=hdf5,
            input_boundary={
                "metadata_path_opened": False,
                "checkpoint_content_opened": False,
                "evaluation_content_opened": False,
                "manifest_content_opened": False,
            },
        )
    except (ValidationError, OSError, TypeError, ValueError) as error:
        return _blocked_report(
            reasons=(
                str(error),
                "real producer proof is absent or not independently established",
                "real terminal proof is absent or not independently established",
                "terminal artifact capability remains diagnostic-only and launch is not admitted",
            )
        )


def run_validation(
    metadata: Mapping[str, Any] | None = None,
    *,
    trajectory_hdf5: Path | str | None = None,
    fixture_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe, always-zero-credit fail-closed report."""
    return build_report(metadata, trajectory_hdf5=trajectory_hdf5, fixture_root=fixture_root)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_unknown(
            report,
            frozenset(
                {
                    "schema",
                    "report_id",
                    "status",
                    "capability_admitted",
                    "launch_allowed",
                    "source_bound",
                    "identity_bound",
                    "terminal_identity_bound",
                    "independent_validator_metadata_bound",
                    "real_producer_proof",
                    "real_terminal_proof",
                    "hdf5_validation",
                    "artifact_bindings",
                    "expected_contract",
                    "proof_status",
                    "input_boundary",
                    "side_effects",
                    "blocked_reasons",
                    *ZERO_CREDIT.keys(),
                }
            ),
            "report",
        )
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        for key in (
            "capability_admitted",
            "launch_allowed",
            "real_producer_proof",
            "real_terminal_proof",
        ):
            _exact(report, key, False, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key in (
            "production_trajectory_opened",
            "production_checkpoint_opened",
            "production_evaluation_opened",
            "production_manifest_opened",
        ):
            _exact(boundary, key, False, "report.input_boundary")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in (
            "runtime_started",
            "solver_started",
            "worker_started",
            "gpu_used_for_execution",
            "registry_writes",
            "ledger_writes",
            "gate_writes",
            "completion_writes",
            "plan_writes",
            "synthetic_receipts_minted",
        ):
            value = side_effects.get(key)
            if value not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (ValidationError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    hdf5 = report.get("hdf5_validation", {})
    lines = [
        "# F3 graph_raw hidden16 terminal artifact validator/canary",
        "",
        f"- status: `{report.get('status')}`",
        f"- capability_admitted: `{report.get('capability_admitted')}`",
        f"- launch_allowed: `{report.get('launch_allowed')}`",
        f"- bounded HDF5 observation: `{hdf5.get('status')}`",
        "- contract: graph_raw / hidden16 / test / 835 transitions / 836 frames",
        "- boundary: temporary synthetic HDF5 only; metadata-only checkpoint/evaluation identity",
        "- real producer proof: `false`; real terminal proof: `false`; credit: `0`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {reason}" for reason in report.get("blocked_reasons", []))
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=None,
                        help="bounded metadata JSON below --fixture-root")
    parser.add_argument("--fixture-root", type=Path, default=None,
                        help="private temporary synthetic fixture root")
    parser.add_argument("--trajectory", type=Path, default=None,
                        help="synthetic .h5 trajectory below --fixture-root")
    parser.add_argument("--report-output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "reports" / REPORT_JSON_FILENAME)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report_path = _absolute_path(args.verify_report, "report")
            payload = _load_json(report_path, "report", max_bytes=MAX_METADATA_BYTES)
            errors = validate_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(canonical_json({"status": "verified", "report": str(report_path)}))
            return 0

        metadata: Mapping[str, Any] | None = None
        if args.metadata is not None:
            if args.fixture_root is None:
                _fail("--fixture-root is required with --metadata")
            fixture_root = _synthetic_fixture_root(args.fixture_root)
            metadata_path = _absolute_path(args.metadata, "metadata")
            if not _under(metadata_path, fixture_root):
                _fail("metadata must remain inside fixture_root")
            metadata = _load_json(metadata_path, "metadata", max_bytes=MAX_METADATA_BYTES)
        report = run_validation(
            metadata,
            trajectory_hdf5=args.trajectory,
            fixture_root=args.fixture_root,
        )
        _write_json(args.report_output, report)
        markdown_output = args.markdown_output
        if markdown_output is not None:
            markdown_output.parent.mkdir(parents=True, exist_ok=True)
            markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(canonical_json(report))
        return 0
    except (ValidationError, OSError, TypeError, ValueError) as error:
        report = _blocked_report(reasons=(str(error), "terminal artifact capability remains blocked"))
        _write_json(args.report_output, report)
        print(canonical_json(report))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
