#!/usr/bin/env python3
"""Independently verify closed F3 graph_residual/hidden16 terminal evidence.

This is an additive runtime-evidence verifier.  It consumes only bounded JSON
envelopes; it never opens an HDF5 file, trajectory, checkpoint, evaluation
output, progress file, manifest, solver artifact, or runtime output.  The
declared artifact paths and digests are compared as evidence, not dereferenced.

Four independent bounded JSON sources are required for each of seeds 17, 29,
and 43:

* the existing receipt-only terminal matrix report;
* a process-exit proof for the evaluator and launcher;
* an evaluation-identity envelope;
* an independent HDF5-validator receipt.

Only the conjunction of all four sources for all three seeds can produce
``independently_terminal_verified=true`` and ``source_bound=true``.  The
result remains diagnostic-only and zero-credit.  No campaign state is changed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import f3_graph_residual_hidden16_terminal_completion_receipt_matrix_v1 as terminal_matrix


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f3.graph_residual.hidden16.terminal_runtime_verifier.v1"
REPORT_ID = "f3-graph-residual-hidden16-terminal-runtime-verifier-v1"
MATRIX_SCHEMA = "core.f3.graph_residual.hidden16.terminal_completion_receipt_matrix.v1"
PROCESS_SCHEMA = "core.f3.graph_residual.hidden16.process_exit_proof.v1"
EVALUATION_IDENTITY_SCHEMA = "core.f3.graph_residual.hidden16.evaluation_identity.v1"
VALIDATOR_ENVELOPE_SCHEMA = "core.f3.graph_residual.hidden16.hdf5_validator_receipt.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"

SEEDS = (17, 29, 43)
MODEL_KIND = "graph_residual"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 64
MAX_DECLARED_BYTES = 1 << 50
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(
    r"^f3-graph-residual500-hidden16-seed(?P<seed>17|29|43)-20260928$"
)
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})

REPORT_JSON_FILENAME = "F3-GRAPH-RESIDUAL-HIDDEN16-TERMINAL-RUNTIME-VERIFIER-V1-2026-09-28.json"
REPORT_MARKDOWN_FILENAME = REPORT_JSON_FILENAME.removesuffix(".json") + ".zh-CN.md"
REPORT_OUTPUT_FILENAMES = frozenset({REPORT_JSON_FILENAME, REPORT_MARKDOWN_FILENAME})
MATRIX_FILENAME = "F3-GRAPH-RESIDUAL-HIDDEN16-TERMINAL-COMPLETION-RECEIPT-MATRIX-V1-2026-09-28.json"

DEFAULT_MATRIX_PATH = LAB_ROOT / "reports" / MATRIX_FILENAME
DEFAULT_PROCESS_PATHS = {
    seed: LAB_ROOT
    / "reports"
    / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"
    for seed in SEEDS
}
DEFAULT_EVALUATION_PATHS = {
    seed: LAB_ROOT
    / "reports"
    / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-EVALUATION-IDENTITY-V1-2026-09-28.json"
    for seed in SEEDS
}
DEFAULT_VALIDATOR_PATHS = {
    seed: LAB_ROOT
    / "reports"
    / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-HDF5-VALIDATOR-RECEIPT-V1-2026-09-28.json"
    for seed in SEEDS
}

REPORT_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "fail_closed",
        "receipt_bound",
        "independently_terminal_verified",
        "source_bound",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "expected_contract",
        "matrix_source",
        "seed_matrix",
        "checks",
        "blocked_reasons",
        "side_effects",
        "input_boundary",
        "interpretation",
        "observed_at_utc",
    }
)

EVIDENCE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "source_bound",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "seed",
        "run_id",
        "namespace",
        "namespace_nonce",
        "model_kind",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint",
        "trajectory",
        "evaluation_artifact",
        "evaluator_alive",
        "launcher_alive",
        "evaluator_returncode",
        "launcher_returncode",
        "returncode",
        "validator_schema",
        "passed",
        "complete",
        "expected_transitions",
        "frames_executed",
        "trajectory_transitions",
        "trajectory_frames",
        "tail_frame_count",
        "production_artifacts_touched",
        "actual_future_state_inputs",
    }
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})
ALLOWED_ALIAS_KEYS = frozenset(
    {
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "credit",
        "qualification_credit",
        "zero_credit_only",
        "progress_or_pid_is_not_completion",
    }
)


class VerifierError(ValueError):
    """Malformed, incomplete, unsafe, or conflicting evidence."""


def _fail(message: str) -> None:
    raise VerifierError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_json_constant(token: str) -> None:
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
        _fail(f"{name} exceeds maximum JSON nesting depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string object key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
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
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 hexadecimal digest")
    return text


def _check_exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be a boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be an integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown field(s): {unknown}")


def _reject_aliases(value: Any, name: str = "value") -> None:
    """Reject unrecognized promotion/process aliases at every JSON level."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if ("pid" in lowered or "process_id" in lowered) and key not in ALLOWED_ALIAS_KEYS:
                _fail(f"{name}.{key} is an unknown PID/process alias")
            if "formal" in lowered and key not in ALLOWED_ALIAS_KEYS:
                _fail(f"{name}.{key} is an unknown formal alias")
            if "credit" in lowered and key not in ALLOWED_ALIAS_KEYS:
                _fail(f"{name}.{key} is an unknown credit alias")
            _reject_aliases(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_aliases(item, f"{name}[{index}]")


def _zero_credit_contract(value: Mapping[str, Any], name: str) -> None:
    for key, expected in (
        ("source_bound", True),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("T2_path", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        _check_exact(value, key, expected, name)


def _lexical_path(root: Path, value: Path | str, name: str) -> tuple[Path, tuple[str, ...]]:
    if not isinstance(value, (Path, str)):
        _fail(f"{name} must be a path")
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path without NUL")
    raw_path = Path(raw)
    if ".." in raw_path.parts:
        _fail(f"{name} contains parent traversal")
    root_abs = Path(os.path.abspath(os.fspath(root)))
    candidate = Path(os.path.abspath(raw if raw_path.is_absolute() else root_abs / raw))
    try:
        relative = candidate.relative_to(root_abs)
    except ValueError:
        _fail(f"{name} escapes the bounded root")
    components = relative.parts
    if not components or any(component in {"", ".", ".."} for component in components):
        _fail(f"{name} contains unsafe path components")
    return candidate, components


def _open_directory_chain(root: Path, components: Sequence[str], name: str) -> tuple[int, list[int]]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("platform does not provide O_NOFOLLOW")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | nofollow
    opened: list[int] = []
    try:
        current = os.open(os.fspath(root), flags)
        opened.append(current)
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            _fail(f"{name} root is not a directory")
        for component in components:
            current = os.open(component, flags, dir_fd=current)
            opened.append(current)
        return current, opened
    except (OSError, VerifierError) as error:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(error, VerifierError):
            raise
        _fail(f"{name} contains a symlink or unsafe directory: {error}")


def _read_bounded_json(root: Path, value: Path | str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one bounded JSON file with descriptor-relative no-follow checks."""

    candidate, components = _lexical_path(root, value, name)
    if candidate.suffix.lower() != ".json":
        _fail(f"{name} must have a .json suffix")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("platform does not provide O_NOFOLLOW")
    parent_fd = -1
    file_fd = -1
    opened: list[int] = []
    try:
        parent_fd, opened = _open_directory_chain(root, components[:-1], name)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
        try:
            file_fd = os.open(components[-1], flags, dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EMLINK}:
                _fail(f"{name} is a symlink and cannot be consumed")
            _fail(f"{name} cannot be opened safely: {error}")
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} must be a regular file")
        if before.st_nlink != 1:
            _fail(f"{name} must not be hard-linked")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{name} exceeds bounded limit {MAX_JSON_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail(f"{name} exceeds bounded limit {MAX_JSON_BYTES} bytes")
        after = os.fstat(file_fd)
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            _fail(f"{name} changed while it was being read (TOCTOU)")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            _fail(f"{name} size changed while it was being read")
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except VerifierError:
            raise
        except (UnicodeError, json.JSONDecodeError) as error:
            _fail(f"{name} is not strict UTF-8 JSON: {error}")
        _walk_json(payload, name)
        payload_map = dict(_mapping(payload, name))
        return payload_map, {
            "path": candidate.relative_to(Path(os.path.abspath(os.fspath(root)))).as_posix(),
            "exists": True,
            "opened": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "schema": payload_map.get("schema"),
        }
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _source_metadata(root: Path, value: Path | str | None) -> dict[str, Any]:
    if value is None:
        return {"path": None, "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
    try:
        candidate, _ = _lexical_path(root, value, "source path")
    except VerifierError:
        return {"path": str(value), "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        info = None
    except OSError:
        info = None
    return {
        "path": candidate.relative_to(Path(os.path.abspath(os.fspath(root)))).as_posix(),
        "exists": info is not None,
        "opened": False,
        "bytes": int(info.st_size) if info is not None and stat.S_ISREG(info.st_mode) else None,
        "sha256": None,
        "schema": None,
    }


def _declared_path(value: Any, name: str, suffix: str | None = None) -> str:
    path = _string(value, name)
    path_obj = Path(path)
    if not path_obj.is_absolute() or ".." in path_obj.parts or "." in path_obj.parts:
        _fail(f"{name} must be absolute and contain no traversal components")
    if os.path.normpath(path) != path:
        _fail(f"{name} must be normalized")
    if suffix is not None and path_obj.suffix.lower() != suffix.lower():
        _fail(f"{name} must end with {suffix}")
    return path


def _artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    item = _mapping(value, name)
    _reject_unknown(item, ARTIFACT_KEYS, name)
    path = _declared_path(item.get("path"), f"{name}.path", suffix)
    byte_count = _strict_int(item.get("bytes"), f"{name}.bytes", 1)
    if byte_count > MAX_DECLARED_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    return {"path": path, "sha256": _strict_sha(item.get("sha256"), f"{name}.sha256"), "bytes": byte_count}


def _run_id(seed: int) -> str:
    return f"f3-graph-residual500-hidden16-seed{seed}-20260928"


def _namespace_fields(value: Mapping[str, Any], seed: int, name: str) -> tuple[str, str]:
    run_id = _string(value.get("run_id"), f"{name}.run_id")
    if run_id != _run_id(seed) or RUN_ID_RE.fullmatch(run_id) is None:
        _fail(f"{name}.run_id is not the canonical seed{seed} run id")
    namespace = _string(value.get("namespace"), f"{name}.namespace")
    nonce = _string(value.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce must be a 32-character lowercase nonce")
    if f"seed{seed}" not in namespace or "full835" not in namespace or f"nonce{nonce}" not in namespace:
        _fail(f"{name}.namespace is not bound to seed{seed}, full835, and its nonce")
    if "running" in namespace.lower() or "partial" in namespace.lower() or "legacy" in namespace.lower():
        _fail(f"{name}.namespace is not fresh")
    return run_id, namespace


def _validate_shared_fields(value: Mapping[str, Any], seed: int, name: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    _check_exact(value, "seed", seed, name)
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _check_exact(value, key, expected, name)
    run_id, namespace = _namespace_fields(value, seed, name)
    checkpoint = _artifact(value.get("checkpoint"), f"{name}.checkpoint")
    if Path(checkpoint["path"]).suffix.lower() not in CHECKPOINT_SUFFIXES:
        _fail(f"{name}.checkpoint.path must use a checkpoint suffix")
    if f"seed{seed}" not in Path(checkpoint["path"]).name or "hidden16" not in Path(checkpoint["path"]).name or "500" not in Path(checkpoint["path"]).name:
        _fail(f"{name}.checkpoint.path is not seed-bound to hidden16 update-500")
    trajectory = _artifact(value.get("trajectory"), f"{name}.trajectory", suffix=".h5")
    if f"seed{seed}" not in Path(trajectory["path"]).name or "full835" not in Path(trajectory["path"]).name:
        _fail(f"{name}.trajectory.path is not seed-bound to full835")
    return run_id, namespace, checkpoint, trajectory


def _validate_process(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _reject_unknown(value, EVIDENCE_TOP_LEVEL_KEYS, name)
    _zero_credit_contract(value, name)
    _check_exact(value, "schema", f"core.f3.graph_residual.hidden16.seed{seed}.process_exit_proof.v1", name)
    _check_exact(value, "status", "exited_successfully", name)
    run_id, namespace, checkpoint, trajectory = _validate_shared_fields(value, seed, name)
    for key, expected in (
        ("evaluator_alive", False),
        ("launcher_alive", False),
        ("evaluator_returncode", 0),
        ("launcher_returncode", 0),
        ("returncode", 0),
    ):
        _check_exact(value, key, expected, name)
    manifest_sha = _strict_sha(value.get("manifest_sha256"), f"{name}.manifest_sha256")
    training_sha = _strict_sha(value.get("training_receipt_sha256"), f"{name}.training_receipt_sha256")
    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": value["namespace_nonce"],
        "manifest_sha256": manifest_sha,
        "training_receipt_sha256": training_sha,
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "evaluator_alive": False,
        "launcher_alive": False,
        "evaluator_returncode": 0,
        "launcher_returncode": 0,
        "returncode": 0,
    }


def _validate_evaluation_identity(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _reject_unknown(value, EVIDENCE_TOP_LEVEL_KEYS, name)
    _zero_credit_contract(value, name)
    _check_exact(value, "schema", f"core.f3.graph_residual.hidden16.seed{seed}.evaluation_identity.v1", name)
    _check_exact(value, "status", "completed_diagnostic", name)
    run_id, namespace, checkpoint, trajectory = _validate_shared_fields(value, seed, name)
    evaluation = _artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", suffix=".json")
    if not Path(evaluation["path"]).name.endswith("-evaluation.json"):
        _fail(f"{name}.evaluation_artifact.path must end with -evaluation.json")
    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": value["namespace_nonce"],
        "manifest_sha256": _strict_sha(value.get("manifest_sha256"), f"{name}.manifest_sha256"),
        "training_receipt_sha256": _strict_sha(value.get("training_receipt_sha256"), f"{name}.training_receipt_sha256"),
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "evaluation_artifact": evaluation,
    }


def _validate_validator(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _reject_unknown(value, EVIDENCE_TOP_LEVEL_KEYS, name)
    _zero_credit_contract(value, name)
    _check_exact(value, "schema", f"core.f3.graph_residual.hidden16.seed{seed}.hdf5_validator_receipt.v1", name)
    _check_exact(value, "status", "validated", name)
    _check_exact(value, "validator_schema", VALIDATOR_SCHEMA, name)
    run_id, namespace, checkpoint, trajectory = _validate_shared_fields(value, seed, name)
    for key, expected in (
        ("passed", True),
        ("complete", True),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("trajectory_frames", FRAMES),
        ("tail_frame_count", 0),
        ("production_artifacts_touched", False),
        ("actual_future_state_inputs", False),
    ):
        _check_exact(value, key, expected, name)
    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": value["namespace_nonce"],
        "manifest_sha256": _strict_sha(value.get("manifest_sha256"), f"{name}.manifest_sha256"),
        "training_receipt_sha256": _strict_sha(value.get("training_receipt_sha256"), f"{name}.training_receipt_sha256"),
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "passed": True,
        "complete": True,
        "expected_transitions": TRANSITIONS,
        "frames_executed": FRAMES,
        "trajectory_transitions": TRANSITIONS,
        "trajectory_frames": FRAMES,
        "tail_frame_count": 0,
    }


def _projection_artifact(projection: Mapping[str, Any], key: str, seed: int, name: str, suffix: str | None = None) -> dict[str, Any]:
    value = _mapping(projection.get(key), f"{name}.{key}")
    # The existing receipt matrix projection carries provenance fields next to
    # path/SHA/bytes (for example checkpoint schema and update).  Those fields
    # are validated by the matrix contract; this verifier extracts only the
    # bounded artifact identity and never dereferences it.
    item = {
        "path": _declared_path(value.get("path"), f"{name}.{key}.path", suffix),
        "sha256": _strict_sha(value.get("sha256"), f"{name}.{key}.sha256"),
        "bytes": _strict_int(value.get("bytes"), f"{name}.{key}.bytes", 1),
    }
    if item["bytes"] > MAX_DECLARED_BYTES:
        _fail(f"{name}.{key}.bytes exceeds the declared bound")
    if f"seed{seed}" not in Path(item["path"]).name:
        _fail(f"{name}.{key}.path is not bound to seed{seed}")
    return item


def _validate_matrix(value: Mapping[str, Any], name: str) -> dict[int, dict[str, Any]]:
    _reject_aliases(value, name)
    _reject_unknown(value, terminal_matrix.REPORT_TOP_LEVEL_KEYS, name)
    errors = terminal_matrix.validate_report(value)
    if errors:
        _fail(f"{name} is not a valid receipt-only terminal matrix: {'; '.join(errors)}")
    for key, expected in (
        ("schema", MATRIX_SCHEMA),
        ("report_id", terminal_matrix.REPORT_ID),
        ("status", "bound_terminal_diagnostic"),
        ("fail_closed", False),
        ("source_bound", True),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("T2_path", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        _check_exact(value, key, expected, name)
    expected = _mapping(value.get("expected_contract"), f"{name}.expected_contract")
    for key, expected_value in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("seeds", list(SEEDS)),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("terminal_status", "completed"),
        ("progress_or_pid_is_not_completion", True),
    ):
        _check_exact(expected, key, expected_value, f"{name}.expected_contract")
    rows = value.get("seed_matrix")
    if not isinstance(rows, list) or len(rows) != len(SEEDS):
        _fail(f"{name}.seed_matrix must contain exactly three rows")
    projections: dict[int, dict[str, Any]] = {}
    for row, seed in zip(rows, SEEDS, strict=True):
        row_map = _mapping(row, f"{name}.seed_matrix.seed{seed}")
        _check_exact(row_map, "seed", seed, f"{name}.seed_matrix.seed{seed}")
        _check_exact(row_map, "status", "bound_terminal_diagnostic", f"{name}.seed_matrix.seed{seed}")
        projection = _mapping(row_map.get("projection"), f"{name}.seed_matrix.seed{seed}.projection")
        for key, expected_value in (
            ("seed", seed),
            ("model_kind", MODEL_KIND),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("case_id", CASE_ID),
            ("split", SPLIT),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
            ("diagnostic_only", True),
            ("formal", False),
            ("formal_eligible", False),
            ("qualification_credit", 0),
            ("credit", 0),
        ):
            _check_exact(projection, key, expected_value, f"{name}.seed_matrix.seed{seed}.projection")
        _reject_aliases(projection, f"{name}.seed_matrix.seed{seed}.projection")
        for key in ("checkpoint", "training_receipt", "evaluation", "trajectory"):
            if key not in projection:
                _fail(f"{name}.seed_matrix.seed{seed}.projection.{key} is missing")
        checkpoint = _projection_artifact(projection, "checkpoint", seed, f"{name}.seed_matrix.seed{seed}.projection")
        training = _projection_artifact(projection, "training_receipt", seed, f"{name}.seed_matrix.seed{seed}.projection", ".json")
        evaluation = _projection_artifact(projection, "evaluation", seed, f"{name}.seed_matrix.seed{seed}.projection", ".json")
        trajectory = _projection_artifact(projection, "trajectory", seed, f"{name}.seed_matrix.seed{seed}.projection", ".h5")
        namespace = _string(projection.get("output_namespace"), f"{name}.seed_matrix.seed{seed}.projection.output_namespace")
        nonce = _string(projection.get("namespace_nonce"), f"{name}.seed_matrix.seed{seed}.projection.namespace_nonce")
        if NONCE_RE.fullmatch(nonce) is None or f"seed{seed}" not in namespace or "full835" not in namespace or f"nonce{nonce}" not in namespace:
            _fail(f"{name}.seed_matrix.seed{seed}.projection namespace is not exact")
        eval_map = _mapping(projection["evaluation"], f"{name}.seed_matrix.seed{seed}.projection.evaluation")
        _check_exact(eval_map, "namespace", namespace, f"{name}.seed_matrix.seed{seed}.projection.evaluation")
        _check_exact(eval_map, "namespace_nonce", nonce, f"{name}.seed_matrix.seed{seed}.projection.evaluation")
        _check_exact(eval_map, "namespace_fresh", True, f"{name}.seed_matrix.seed{seed}.projection.evaluation")
        projections[seed] = {
            "seed": seed,
            "run_id": _run_id(seed),
            "namespace": namespace,
            "namespace_nonce": nonce,
            "checkpoint": checkpoint,
            "training_receipt": training,
            "evaluation_artifact": evaluation,
            "trajectory": trajectory,
        }
    paths = [item["checkpoint"]["path"] for item in projections.values()]
    shas = [item["checkpoint"]["sha256"] for item in projections.values()]
    training_paths = [item["training_receipt"]["path"] for item in projections.values()]
    training_shas = [item["training_receipt"]["sha256"] for item in projections.values()]
    trajectories = [item["trajectory"]["path"] for item in projections.values()]
    if len(set(paths)) != len(paths) or len(set(shas)) != len(shas) or len(set(training_paths)) != len(training_paths) or len(set(training_shas)) != len(training_shas) or len(set(trajectories)) != len(trajectories):
        _fail(f"{name} reuses a path or SHA across seeds")
    return projections


def _artifact_equal(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> None:
    for key in ("path", "sha256", "bytes"):
        if left.get(key) != right.get(key):
            _fail(f"{name}.{key} drifts across evidence envelopes")


def _cross_bind(seed: int, projection: Mapping[str, Any], process: Mapping[str, Any], evaluation: Mapping[str, Any], validator: Mapping[str, Any]) -> None:
    name = f"seed{seed} cross-binding"
    for source_name, source in (("process", process), ("evaluation", evaluation), ("validator", validator)):
        if source["seed"] != seed or source["run_id"] != projection["run_id"] or source["namespace"] != projection["namespace"] or source["namespace_nonce"] != projection["namespace_nonce"]:
            _fail(f"{name}: {source_name} seed/run/namespace identity drifts")
    for source_name, source in (("process", process), ("validator", validator)):
        if source["manifest_sha256"] != evaluation["manifest_sha256"] or source["training_receipt_sha256"] != evaluation["training_receipt_sha256"]:
            _fail(f"{name}: {source_name} manifest/training identity drifts")
    for source_name, source in (("process", process), ("evaluation", evaluation), ("validator", validator)):
        _artifact_equal(source["checkpoint"], projection["checkpoint"], f"{name}.{source_name}.checkpoint")
        _artifact_equal(source["trajectory"], projection["trajectory"], f"{name}.{source_name}.trajectory")
    _artifact_equal(evaluation["evaluation_artifact"], projection["evaluation_artifact"], f"{name}.evaluation_artifact")


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _empty_side_effects() -> dict[str, Any]:
    return {
        "matrix_json_opened": False,
        "process_json_opened": False,
        "evaluation_identity_json_opened": False,
        "validator_json_opened": False,
        "hdf5_opened": False,
        "trajectory_opened": False,
        "checkpoint_opened": False,
        "evaluation_artifact_opened": False,
        "progress_opened": False,
        "manifest_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def _empty_input_boundary() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "canonical_reports_or_explicit_receipts_only": True,
        "hdf5_content_opened": False,
        "trajectory_content_opened": False,
        "checkpoint_content_opened": False,
        "evaluation_content_opened": False,
        "progress_content_opened": False,
        "manifest_content_opened": False,
        "runtime_started": False,
        "queue_submissions": 0,
    }


def _row(seed: int) -> dict[str, Any]:
    return {"seed": seed, "status": "missing", "blocked_reasons": [], "sources": {}, "evidence": None}


def _evaluate(
    matrix_payload: Mapping[str, Any] | None,
    matrix_source: Mapping[str, Any],
    process_payloads: Mapping[int, Mapping[str, Any]],
    process_sources: Mapping[int, Mapping[str, Any]],
    evaluation_payloads: Mapping[int, Mapping[str, Any]],
    evaluation_sources: Mapping[int, Mapping[str, Any]],
    validator_payloads: Mapping[int, Mapping[str, Any]],
    validator_sources: Mapping[int, Mapping[str, Any]],
    errors: list[str],
    observed_at_utc: str,
) -> dict[str, Any]:
    rows = [_row(seed) for seed in SEEDS]
    projections: dict[int, dict[str, Any]] = {}
    receipt_bound = False
    try:
        if matrix_payload is None:
            _fail("terminal matrix report is missing")
        projections = _validate_matrix(matrix_payload, "terminal matrix report")
        receipt_bound = True
    except (VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    for row in rows:
        seed = row["seed"]
        row["sources"] = {
            "process_exit_proof": process_sources.get(seed),
            "evaluation_identity": evaluation_sources.get(seed),
            "validator_receipt": validator_sources.get(seed),
        }
        if seed not in projections:
            row["blocked_reasons"].append("receipt-only terminal matrix is not independently bound for this seed")
            continue
        try:
            process = _validate_process(process_payloads[seed], seed, f"seed{seed} process_exit_proof")
            evaluation = _validate_evaluation_identity(evaluation_payloads[seed], seed, f"seed{seed} evaluation_identity")
            validator = _validate_validator(validator_payloads[seed], seed, f"seed{seed} validator_receipt")
            _cross_bind(seed, projections[seed], process, evaluation, validator)
        except KeyError as error:
            row["blocked_reasons"].append(f"seed{seed} missing required evidence envelope: {error}")
        except (VerifierError, TypeError, RecursionError) as error:
            row["blocked_reasons"].append(str(error))
        else:
            row["status"] = "independently_verified"
            row["evidence"] = {"process_exit_proof": process, "evaluation_identity": evaluation, "validator_receipt": validator}
    all_verified = all(row["status"] == "independently_verified" for row in rows)
    if not receipt_bound:
        errors.append("receipt-only terminal matrix report is missing, invalid, or not source-bound")
    for row in rows:
        errors.extend(row["blocked_reasons"])
    errors = list(dict.fromkeys(errors))
    checks = [
        _check("receipt_only_terminal_matrix", receipt_bound, "the existing terminal matrix is source-bound and receipt-only"),
        _check("exact_seed_set", receipt_bound and len(rows) == 3, "seed set is exactly 17, 29, and 43", sorted(projections), list(SEEDS)),
        _check("process_exit_proofs", all(row["status"] == "independently_verified" or row["sources"]["process_exit_proof"]["exists"] if row["sources"].get("process_exit_proof") else False for row in rows), "all seeds have closed evaluator/launcher exit proofs"),
        _check("evaluation_identity_envelopes", all(row["status"] == "independently_verified" or row["sources"]["evaluation_identity"]["exists"] if row["sources"].get("evaluation_identity") else False for row in rows), "all seeds have bounded evaluation identity envelopes"),
        _check("independent_hdf5_validator_receipts", all(row["status"] == "independently_verified" or row["sources"]["validator_receipt"]["exists"] if row["sources"].get("validator_receipt") else False for row in rows), "all seeds have independent validator receipts"),
        _check("cross_file_path_sha_bytes_identity", all_verified, "run, namespace, checkpoint, trajectory, and all declared path/SHA/bytes fields agree across files"),
        _check("terminal_zero_credit_boundary", all_verified, "all evidence is diagnostic-only and zero-credit"),
    ]
    verified = receipt_bound and all_verified and not errors
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "independently_terminal_verified" if verified else "blocked_fail_closed",
        "fail_closed": not verified,
        "receipt_bound": receipt_bound,
        "independently_terminal_verified": verified,
        "source_bound": verified,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "expected_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "required_evidence_classes": ["terminal_matrix", "process_exit_proof", "evaluation_identity", "hdf5_validator_receipt"],
            "declared_artifacts_are_not_opened": True,
            "zero_credit_only": True,
        },
        "matrix_source": dict(matrix_source),
        "seed_matrix": rows,
        "checks": checks,
        "blocked_reasons": errors,
        "side_effects": _empty_side_effects(),
        "input_boundary": _empty_input_boundary(),
        "interpretation": (
            "This additive verifier consumes bounded JSON envelopes only. It does not "
            "open HDF5, trajectory, checkpoint, evaluation, progress, manifest, "
            "solver, GPU, worker, queue, registry, ledger, gate, completion, or PLAN "
            "artifacts. A positive result is independently terminal-verified but remains "
            "diagnostic-only and contributes zero formal/T1/T2 credit."
        ),
        "observed_at_utc": _string(observed_at_utc, "observed_at_utc"),
    }


def _read_optional(root: Path, path: Path | str | None, name: str) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    if path is None:
        return None, _source_metadata(root, None), f"{name} is not configured"
    try:
        payload, source = _read_bounded_json(root, path, name)
        return payload, source, None
    except (VerifierError, OSError, ValueError, TypeError, RecursionError) as error:
        return None, _source_metadata(root, path), f"{name}: {error}"


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    matrix_path: Path | str | None = None,
    process_paths: Mapping[int, Path | str | None] | None = None,
    evaluation_paths: Mapping[int, Path | str | None] | None = None,
    validator_paths: Mapping[int, Path | str | None] | None = None,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
) -> dict[str, Any]:
    root = Path(os.path.abspath(os.fspath(lab_root)))
    if matrix_path is None:
        matrix_path = root / "reports" / MATRIX_FILENAME
    if process_paths is None:
        process_paths = {
            seed: root
            / "reports"
            / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"
            for seed in SEEDS
        }
    if evaluation_paths is None:
        evaluation_paths = {
            seed: root
            / "reports"
            / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-EVALUATION-IDENTITY-V1-2026-09-28.json"
            for seed in SEEDS
        }
    if validator_paths is None:
        validator_paths = {
            seed: root
            / "reports"
            / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-HDF5-VALIDATOR-RECEIPT-V1-2026-09-28.json"
            for seed in SEEDS
        }
    errors: list[str] = []
    matrix, matrix_source, error = _read_optional(root, matrix_path, "terminal matrix report")
    if error:
        errors.append(error)
    process_payloads: dict[int, Mapping[str, Any]] = {}
    process_sources: dict[int, dict[str, Any]] = {}
    evaluation_payloads: dict[int, Mapping[str, Any]] = {}
    evaluation_sources: dict[int, dict[str, Any]] = {}
    validator_payloads: dict[int, Mapping[str, Any]] = {}
    validator_sources: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        payload, source, error = _read_optional(root, process_paths.get(seed), f"seed{seed} process_exit_proof")
        process_sources[seed] = source
        if payload is not None:
            process_payloads[seed] = payload
        if error:
            errors.append(error)
        payload, source, error = _read_optional(root, evaluation_paths.get(seed), f"seed{seed} evaluation_identity")
        evaluation_sources[seed] = source
        if payload is not None:
            evaluation_payloads[seed] = payload
        if error:
            errors.append(error)
        payload, source, error = _read_optional(root, validator_paths.get(seed), f"seed{seed} validator_receipt")
        validator_sources[seed] = source
        if payload is not None:
            validator_payloads[seed] = payload
        if error:
            errors.append(error)
    return _evaluate(
        matrix,
        matrix_source,
        process_payloads,
        process_sources,
        evaluation_payloads,
        evaluation_sources,
        validator_payloads,
        validator_sources,
        errors,
        observed_at_utc,
    )


def _validate_side_effects(value: Any, name: str) -> None:
    item = _mapping(value, name)
    _reject_unknown(item, set(_empty_side_effects()), name)
    for key, expected in _empty_side_effects().items():
        _check_exact(item, key, expected, name)


def _validate_input_boundary(value: Any, name: str) -> None:
    item = _mapping(value, name)
    _reject_unknown(item, set(_empty_input_boundary()), name)
    for key, expected in _empty_input_boundary().items():
        _check_exact(item, key, expected, name)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_aliases(report, "report")
        _reject_unknown(report, REPORT_TOP_LEVEL_KEYS, "report")
        _check_exact(report, "schema", REPORT_SCHEMA, "report")
        _check_exact(report, "report_id", REPORT_ID, "report")
        source_bound = report.get("source_bound")
        if type(source_bound) is not bool:
            _fail("report.source_bound must be boolean")
        _strict_bool(report.get("receipt_bound"), "report.receipt_bound")
        for key, expected in (
            ("diagnostic_only", True),
            ("formal", False),
            ("formal_eligible", False),
            ("T1_numerical", False),
            ("T2_macro", False),
            ("T2_path", False),
            ("qualification", False),
            ("qualification_credit", 0),
            ("credit", 0),
        ):
            _check_exact(report, key, expected, "report")
        _check_exact(report, "fail_closed", not source_bound, "report")
        _check_exact(report, "independently_terminal_verified", source_bound, "report")
        _check_exact(report, "status", "independently_terminal_verified" if source_bound else "blocked_fail_closed", "report")
        expected_contract = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, expected in (
            ("model_kind", MODEL_KIND),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("seeds", list(SEEDS)),
            ("case_id", CASE_ID),
            ("split", SPLIT),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
            ("declared_artifacts_are_not_opened", True),
            ("zero_credit_only", True),
        ):
            _check_exact(expected_contract, key, expected, "report.expected_contract")
        matrix_source = _mapping(report.get("matrix_source"), "report.matrix_source")
        _reject_unknown(
            matrix_source,
            frozenset({"path", "exists", "opened", "bytes", "sha256", "schema"}),
            "report.matrix_source",
        )
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
            _fail("report.seed_matrix must contain seeds 17, 29, and 43 in order")
        row_keys = frozenset({"seed", "status", "blocked_reasons", "sources", "evidence"})
        source_keys = frozenset({"process_exit_proof", "evaluation_identity", "validator_receipt"})
        source_metadata_keys = frozenset({"path", "exists", "opened", "bytes", "sha256", "schema"})
        for row in rows:
            row_map = _mapping(row, "report.seed_matrix row")
            _reject_unknown(row_map, row_keys, "report.seed_matrix row")
            if row_map.get("status") not in {"missing", "independently_verified"}:
                _fail("report.seed_matrix row has an invalid status")
            sources = _mapping(row_map.get("sources"), "report.seed_matrix.sources")
            _reject_unknown(sources, source_keys, "report.seed_matrix.sources")
            for source_name, source in sources.items():
                source_map = _mapping(source, f"report.seed_matrix.sources.{source_name}")
                _reject_unknown(source_map, source_metadata_keys, f"report.seed_matrix.sources.{source_name}")
            if row_map.get("status") == "independently_verified":
                evidence = _mapping(row_map.get("evidence"), "report.seed_matrix.evidence")
                _reject_unknown(evidence, source_keys, "report.seed_matrix.evidence")
            elif not isinstance(row_map.get("blocked_reasons"), list) or not row_map["blocked_reasons"]:
                _fail("blocked seed row lacks a blocker")
        checks = report.get("checks")
        if not isinstance(checks, list) or len(checks) != 7:
            _fail("report.checks must contain seven checks")
        expected_check_names = [
            "receipt_only_terminal_matrix",
            "exact_seed_set",
            "process_exit_proofs",
            "evaluation_identity_envelopes",
            "independent_hdf5_validator_receipts",
            "cross_file_path_sha_bytes_identity",
            "terminal_zero_credit_boundary",
        ]
        if [item.get("check") for item in checks if isinstance(item, Mapping)] != expected_check_names:
            _fail("report.checks have an unexpected identity")
        if any(not isinstance(item, Mapping) or type(item.get("passed")) is not bool for item in checks):
            _fail("report.checks must contain boolean pass flags")
        if source_bound:
            if any(not isinstance(item, Mapping) or item.get("passed") is not True for item in checks):
                _fail("verified report checks must all pass")
            if any(row.get("status") != "independently_verified" for row in rows):
                _fail("verified report must have three verified rows")
        _validate_side_effects(report.get("side_effects"), "report.side_effects")
        _validate_input_boundary(report.get("input_boundary"), "report.input_boundary")
        if not isinstance(report.get("blocked_reasons"), list):
            _fail("report.blocked_reasons must be a list")
        if not source_bound and not report["blocked_reasons"]:
            _fail("blocked report must include at least one blocker")
        _string(report.get("observed_at_utc"), "report.observed_at_utc")
    except (VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def _report_output_components(root: Path, output: Path | str, name: str) -> tuple[Path, tuple[str, ...]]:
    candidate, components = _lexical_path(root, output, name)
    if len(components) != 2 or components[0] != "reports" or candidate.name not in REPORT_OUTPUT_FILENAMES:
        _fail(f"{name} must be one of the fixed report destinations below reports")
    return candidate, components


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> None:
    errors = validate_report(report)
    if errors:
        raise VerifierError("refusing to write invalid report: " + "; ".join(errors))
    root_path = Path(os.path.abspath(os.fspath(root)))
    _candidate, components = _report_output_components(root_path, output, "report output")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("platform does not provide O_NOFOLLOW")
    parent_fd, opened = _open_directory_chain(root_path, components[:-1], "report output")
    temporary_name: str | None = None
    try:
        try:
            existing = os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                _fail("report output is not a regular file")
            if existing.st_nlink != 1:
                _fail("report output is hard-linked")
        raw = (
            "# F3 graph_residual hidden16 terminal runtime verifier V1\n\n```json\n"
            + canonical_json(report)
            + "\n```\n"
            if components[-1].endswith(".md")
            else canonical_json(report) + "\n"
        ).encode("utf-8")
        if len(raw) > MAX_JSON_BYTES:
            _fail("report output exceeds bounded limit")
        for _ in range(16):
            temporary_name = f".{components[-1]}.{secrets.token_hex(12)}.tmp"
            try:
                fd = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | nofollow,
                    0o644,
                    dir_fd=parent_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            _fail("could not allocate a temporary report path")
        try:
            if os.write(fd, raw) != len(raw):
                _fail("short report write")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary_name, components[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _parse_seed_paths(values: Sequence[str], option: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"{option} must use SEED=PATH: {raw}")
        seed_text, path_text = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise SystemExit(f"invalid seed in {option}: {raw}") from error
        if seed not in SEEDS or seed in result:
            raise SystemExit(f"invalid or duplicate seed in {option}: {raw}")
        result[seed] = Path(path_text)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--matrix-report", type=Path, default=None)
    parser.add_argument("--process-exit-proof", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--evaluation-identity", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--validator-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--observed-at-utc", default="2026-09-28T00:00:00Z")
    args = parser.parse_args(argv)
    process_paths = {
        seed: args.root
        / "reports"
        / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"
        for seed in SEEDS
    }
    process_paths.update(_parse_seed_paths(args.process_exit_proof, "--process-exit-proof"))
    evaluation_paths = {
        seed: args.root
        / "reports"
        / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-EVALUATION-IDENTITY-V1-2026-09-28.json"
        for seed in SEEDS
    }
    evaluation_paths.update(_parse_seed_paths(args.evaluation_identity, "--evaluation-identity"))
    validator_paths = {
        seed: args.root
        / "reports"
        / f"F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-HDF5-VALIDATOR-RECEIPT-V1-2026-09-28.json"
        for seed in SEEDS
    }
    validator_paths.update(_parse_seed_paths(args.validator_receipt, "--validator-receipt"))
    report = build_report(
        args.root,
        matrix_path=args.matrix_report,
        process_paths=process_paths,
        evaluation_paths=evaluation_paths,
        validator_paths=validator_paths,
        observed_at_utc=args.observed_at_utc,
    )
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    if args.output is not None:
        write_report(report, args.output, root=args.root)
    if args.markdown_output is not None:
        write_report(report, args.markdown_output, root=args.root)
    print(canonical_json(report))
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
