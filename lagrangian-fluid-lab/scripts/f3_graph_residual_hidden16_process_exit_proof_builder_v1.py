#!/usr/bin/env python3
"""Normalize one post-terminal F3 residual process observation.

The input is one bounded JSON observation captured after the evaluator and
launcher have naturally exited.  The builder validates the fixed F3
graph_residual/hidden16/full835 contract, validates command bindings, and
performs metadata-only ``lstat`` checks for declared artifacts.  It never
opens an artifact file and never starts, stops, or inspects a process.

The returned object is the exact process-exit-proof envelope accepted by
``f3_graph_residual_hidden16_terminal_runtime_verifier_v1.py``.  Commands are
input evidence: the existing verifier's process schema intentionally has no
command field, so command metadata is validated and then omitted from the
strict normalized envelope rather than being smuggled in as an unknown field.

With no input, the CLI emits a blocked sample.  A positive envelope may be
printed or written outside ``reports``; the only report file this utility can
write is the fixed default blocked sample.  This prevents a normalizer from
manufacturing a checked-in terminal report before independent evidence is
available.
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
from scripts import f3_graph_residual_hidden16_terminal_runtime_verifier_v1 as verifier


LAB_ROOT = Path(__file__).resolve().parents[1]

INPUT_SCHEMA = "core.f3.graph_residual.hidden16.post_terminal_process_observation.v1"
INPUT_REPORT_ID = "f3-graph-residual-hidden16-post-terminal-process-observation-v1"
BUILDER_SCHEMA = "core.f3.graph_residual.hidden16.process_exit_proof_builder.v1"
BUILDER_REPORT_ID = "f3-graph-residual-hidden16-process-exit-proof-builder-v1"

SEEDS = verifier.SEEDS
MODEL_KIND = verifier.MODEL_KIND
HIDDEN = verifier.HIDDEN
UPDATES = verifier.UPDATES
TRANSITIONS = verifier.TRANSITIONS
FRAMES = verifier.FRAMES
CASE_ID = verifier.CASE_ID
SPLIT = verifier.SPLIT
MAX_JSON_BYTES = verifier.MAX_JSON_BYTES
MAX_JSON_DEPTH = verifier.MAX_JSON_DEPTH
MAX_DECLARED_BYTES = verifier.MAX_DECLARED_BYTES
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^f3-graph-residual500-hidden16-seed(?:17|29|43)-20260928$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})

DEFAULT_BLOCKED_FILENAME = "F3-GRAPH-RESIDUAL-HIDDEN16-PROCESS-EXIT-PROOF-BUILDER-V1-2026-09-28.json"
DEFAULT_BLOCKED_MARKDOWN_FILENAME = DEFAULT_BLOCKED_FILENAME.removesuffix(".json") + ".zh-CN.md"
DEFAULT_REPORT_FILENAMES = frozenset({DEFAULT_BLOCKED_FILENAME, DEFAULT_BLOCKED_MARKDOWN_FILENAME})

INPUT_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
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
        "training_receipt",
        "checkpoint",
        "trajectory",
        "evaluation_artifact",
        "process",
        "exit_observation",
    }
)
PROCESS_KEYS = frozenset({"evaluator", "launcher"})
PROCESS_COMPONENT_KEYS = frozenset({"alive", "returncode", "reaped", "command", "command_sha256"})
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes", "content_opened", "stat_only"})
EXIT_OBSERVATION_KEYS = frozenset({"natural_exit", "observed_after_exit"})

BLOCKED_REPORT_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "fail_closed",
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
        "process_exit_proof",
        "expected_contract",
        "blocked_reasons",
        "side_effects",
        "input_boundary",
        "observed_at_utc",
    }
)


class BuilderError(ValueError):
    """Malformed, incomplete, unsafe, or contract-drifting input."""


def _fail(message: str) -> None:
    raise BuilderError(f"fail-closed: {message}")


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
        if len(value) > 4096:
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


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown field(s): {unknown}")


def _reject_aliases(value: Any, name: str = "value", *, allow_contract_fields: bool = False) -> None:
    """Reject PID/formal/credit aliases recursively.

    The exact zero-credit fields are allowed only when validating the blocked
    sample.  Observation input has no promotion fields at all.
    """

    allowed = (
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
        }
        if allow_contract_fields
        else set()
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if ("pid" in lowered or "process_id" in lowered) or (
                "formal" in lowered and key not in allowed
            ) or ("credit" in lowered and key not in allowed):
                _fail(f"{name}.{key} is a forbidden PID/formal/credit alias")
            _reject_aliases(item, f"{name}.{key}", allow_contract_fields=allow_contract_fields)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_aliases(item, f"{name}[{index}]", allow_contract_fields=allow_contract_fields)


def _absolute_clean_path(value: Any, name: str) -> str:
    text = _string(value, name)
    path = Path(text)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if ".." in path.parts or "." in path.parts:
        _fail(f"{name} contains path traversal components")
    if os.path.normpath(text) != text:
        _fail(f"{name} must be normalized")
    if any(part == "" for part in path.parts):
        _fail(f"{name} contains an empty path component")
    return text


def _relative_components(root: Path, value: Path | str, name: str) -> tuple[Path, tuple[str, ...]]:
    if not isinstance(value, (Path, str)):
        _fail(f"{name} must be a path")
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path without NUL")
    raw_path = Path(raw)
    if ".." in raw_path.parts or "." in raw_path.parts:
        _fail(f"{name} contains path traversal components")
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
    except (OSError, BuilderError) as error:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(error, BuilderError):
            raise
        _fail(f"{name} contains a symlink or unsafe directory: {error}")


def load_observation(root: Path | str, path: Path | str) -> dict[str, Any]:
    """Read one strict, bounded observation without following filesystem links."""

    root_path = Path(os.path.abspath(os.fspath(root)))
    candidate, components = _relative_components(root_path, path, "observation path")
    if candidate.suffix.lower() != ".json":
        _fail("observation path must have a .json suffix")
    if any(token in candidate.name.lower() for token in ("evaluation", "progress", "trajectory", "hdf5", "checkpoint")):
        _fail("observation path names a live/artifact file")
    parent_fd = -1
    file_fd = -1
    opened: list[int] = []
    try:
        parent_fd, opened = _open_directory_chain(root_path, components[:-1], "observation path")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(components[-1], flags, dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EMLINK}:
                _fail("observation path is a symlink or hard link")
            _fail(f"observation path cannot be opened safely: {error}")
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            _fail("observation path must be a regular file")
        if before.st_nlink != 1:
            _fail("observation path must not be hard-linked")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"observation path exceeds bounded limit {MAX_JSON_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail(f"observation path exceeds bounded limit {MAX_JSON_BYTES} bytes")
        after = os.fstat(file_fd)
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            _fail("observation changed while it was being read (TOCTOU)")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            _fail("observation size changed while it was being read")
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except BuilderError:
            raise
        except (UnicodeError, json.JSONDecodeError) as error:
            _fail(f"observation is not strict UTF-8 JSON: {error}")
        _walk_json(payload, "observation")
        return dict(_mapping(payload, "observation"))
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


def _open_absolute_parent(path: str, name: str) -> tuple[int, list[int]]:
    path_obj = Path(path)
    if not path_obj.is_absolute() or path_obj.parent == path_obj:
        _fail(f"{name} must identify a file below an absolute directory")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        _fail("platform does not provide O_NOFOLLOW")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | nofollow
    opened: list[int] = []
    try:
        current = os.open(os.path.sep, flags)
        opened.append(current)
        for component in path_obj.parent.parts[1:]:
            current = os.open(component, flags, dir_fd=current)
            opened.append(current)
        return current, opened
    except (OSError, BuilderError) as error:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(error, BuilderError):
            raise
        _fail(f"{name} parent contains a symlink or unsafe directory: {error}")


def _stat_regular_single_link(path: str, expected_bytes: int, name: str) -> None:
    """Check only inode metadata; never open the declared artifact."""

    parent_fd, opened = _open_absolute_parent(path, name)
    try:
        try:
            info = os.stat(Path(path).name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            _fail(f"{name} cannot be metadata-checked: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} is a symlink")
        if not stat.S_ISREG(info.st_mode):
            _fail(f"{name} must be a regular file")
        if info.st_nlink != 1:
            _fail(f"{name} must not be hard-linked")
        if info.st_size != expected_bytes:
            _fail(f"{name}.bytes does not match stat size")
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _artifact(
    value: Any,
    name: str,
    *,
    expected_path: str,
    suffix: str | None = None,
) -> dict[str, Any]:
    item = _mapping(value, name)
    _reject_unknown(item, ARTIFACT_KEYS, name)
    path = _absolute_clean_path(item.get("path"), f"{name}.path")
    if path != expected_path:
        _fail(f"{name}.path is not the fixed namespace-derived path")
    if suffix is not None and Path(path).suffix.lower() != suffix.lower():
        _fail(f"{name}.path must end with {suffix}")
    byte_count = _strict_int(item.get("bytes"), f"{name}.bytes", 1)
    if byte_count > MAX_DECLARED_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    _strict_bool(item.get("content_opened"), f"{name}.content_opened")
    _check_exact(item, "content_opened", False, name)
    _strict_bool(item.get("stat_only"), f"{name}.stat_only")
    _check_exact(item, "stat_only", True, name)
    digest = _strict_sha(item.get("sha256"), f"{name}.sha256")
    _stat_regular_single_link(path, byte_count, name)
    return {"path": path, "sha256": digest, "bytes": byte_count}


def _run_id(seed: int) -> str:
    return f"f3-graph-residual500-hidden16-seed{seed}-20260928"


def _namespace(value: Mapping[str, Any], seed: int, name: str) -> tuple[str, str]:
    run_id = _string(value.get("run_id"), f"{name}.run_id")
    if run_id != _run_id(seed) or RUN_ID_RE.fullmatch(run_id) is None:
        _fail(f"{name}.run_id is not the canonical seed{seed} run id")
    namespace = _absolute_clean_path(value.get("namespace"), f"{name}.namespace")
    nonce = _string(value.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce must be a 32-character lowercase nonce")
    expected_name = f"f3-graph-residual500-hidden16-seed{seed}-full835-nonce{nonce}"
    if Path(namespace).name != expected_name:
        _fail(f"{name}.namespace does not match the fixed seed/full835/nonce contract")
    if "running" in namespace.lower() or "partial" in namespace.lower() or "legacy" in namespace.lower():
        _fail(f"{name}.namespace is not a fresh namespace")
    # This opens only the namespace's parent directories, never the prefix or
    # any artifact content.  It rejects a symlinked output directory chain.
    parent_fd, opened = _open_absolute_parent(namespace, f"{name}.namespace")
    for descriptor in reversed(opened):
        try:
            os.close(descriptor)
        except OSError:
            pass
    return run_id, namespace


def _command_sha256(command: Sequence[str]) -> str:
    return hashlib.sha256(canonical_json(list(command)).encode("utf-8")).hexdigest()


def _command(value: Any, name: str) -> tuple[list[str], str]:
    if not isinstance(value, list) or not value:
        _fail(f"{name} must be a non-empty argv array")
    if len(value) > 512:
        _fail(f"{name} contains too many argv entries")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _string(item, f"{name}[{index}]")
        if CONTROL_RE.search(text):
            _fail(f"{name}[{index}] contains control characters")
        if len(text.encode("utf-8")) > 8192:
            _fail(f"{name}[{index}] exceeds the bounded argument length")
        lowered = text.lower()
        if "pid" in lowered or "formal" in lowered or "credit" in lowered:
            _fail(f"{name}[{index}] contains a forbidden PID/formal/credit token")
        result.append(text)
    encoded = canonical_json(result).encode("utf-8")
    if len(encoded) > 128 * 1024:
        _fail(f"{name} exceeds the bounded command size")
    return result, _command_sha256(result)


def _option(argv: Sequence[str], option: str, name: str) -> str:
    positions = [index for index, item in enumerate(argv) if item == option]
    if len(positions) != 1:
        _fail(f"{name} must contain exactly one {option} option")
    index = positions[0]
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        _fail(f"{name}.{option} must have one value")
    if any(item.startswith(option + "=") for item in argv):
        _fail(f"{name} must not use {option}=value aliases")
    return argv[index + 1]


def _validate_evaluator_command(
    argv: Sequence[str],
    *,
    checkpoint: str,
    trajectory: str,
    evaluation: str,
    namespace: str,
    name: str,
) -> None:
    if sum(item == "evaluate" for item in argv) != 1:
        _fail(f"{name} must contain exactly one evaluate action")
    if not any(Path(item).name == "core_learning.py" for item in argv):
        _fail(f"{name} must invoke core_learning.py")
    expected_options = {
        "--manifest": "campaigns/core-v1/f3-dataset-v2.json",
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--checkpoint": checkpoint,
        "--trajectory-output": trajectory,
        "--progress-output": namespace + "-evaluation-progress.json",
        "--output": evaluation,
    }
    for option, expected in expected_options.items():
        observed = _option(argv, option, name)
        if observed != expected:
            _fail(f"{name}.{option} must be {expected!r}; observed {observed!r}")
    if sum(item == "--diagnostic" for item in argv) != 1:
        _fail(f"{name} must contain exactly one --diagnostic flag")


def _process_component(value: Any, name: str) -> tuple[list[str], str]:
    component = _mapping(value, name)
    _reject_unknown(component, PROCESS_COMPONENT_KEYS, name)
    _check_exact(component, "alive", False, name)
    _check_exact(component, "returncode", 0, name)
    _check_exact(component, "reaped", True, name)
    argv, digest = _command(component.get("command"), f"{name}.command")
    _check_exact(component, "command_sha256", digest, name)
    return argv, digest


def _validate_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    _walk_json(payload, "observation")
    _reject_aliases(payload, "observation")
    _reject_unknown(payload, INPUT_KEYS, "observation")
    _check_exact(payload, "schema", INPUT_SCHEMA, "observation")
    _check_exact(payload, "report_id", INPUT_REPORT_ID, "observation")
    _check_exact(payload, "status", "post_terminal_observed", "observation")
    seed = _strict_int(payload.get("seed"), "observation.seed", 0)
    if seed not in SEEDS:
        _fail(f"observation.seed must be one of {SEEDS}")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _check_exact(payload, key, expected, "observation")
    run_id, namespace = _namespace(payload, seed, "observation")
    nonce = _string(payload.get("namespace_nonce"), "observation.namespace_nonce")
    manifest_sha = _strict_sha(payload.get("manifest_sha256"), "observation.manifest_sha256")

    training_path = f"{Path(namespace).parent / (run_id + '-training.json')}"
    checkpoint_path = f"{Path(namespace).parent / (run_id + '-checkpoint.pt')}"
    trajectory_path = namespace + "-trajectory.h5"
    evaluation_path = namespace + "-evaluation.json"
    training = _artifact(payload.get("training_receipt"), "observation.training_receipt", expected_path=training_path, suffix=".json")
    checkpoint = _artifact(payload.get("checkpoint"), "observation.checkpoint", expected_path=checkpoint_path, suffix=".pt")
    trajectory = _artifact(payload.get("trajectory"), "observation.trajectory", expected_path=trajectory_path, suffix=".h5")
    evaluation = _artifact(payload.get("evaluation_artifact"), "observation.evaluation_artifact", expected_path=evaluation_path, suffix=".json")

    exit_observation = _mapping(payload.get("exit_observation"), "observation.exit_observation")
    _reject_unknown(exit_observation, EXIT_OBSERVATION_KEYS, "observation.exit_observation")
    _check_exact(exit_observation, "natural_exit", True, "observation.exit_observation")
    _check_exact(exit_observation, "observed_after_exit", True, "observation.exit_observation")

    process = _mapping(payload.get("process"), "observation.process")
    _reject_unknown(process, PROCESS_KEYS, "observation.process")
    evaluator_argv, evaluator_digest = _process_component(process.get("evaluator"), "observation.process.evaluator")
    launcher_argv, launcher_digest = _process_component(process.get("launcher"), "observation.process.launcher")
    _validate_evaluator_command(
        evaluator_argv,
        checkpoint=checkpoint["path"],
        trajectory=trajectory["path"],
        evaluation=evaluation["path"],
        namespace=namespace,
        name="observation.process.evaluator.command",
    )
    if len(launcher_argv) < len(evaluator_argv) or launcher_argv[-len(evaluator_argv) :] != evaluator_argv:
        _fail("observation.process.launcher.command must end with the evaluator argv")

    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": nonce,
        "manifest_sha256": manifest_sha,
        "training_receipt_sha256": training["sha256"],
        "checkpoint": checkpoint,
        "trajectory": trajectory,
        "command_sha256": evaluator_digest,
        "launcher_command_sha256": launcher_digest,
    }


def build_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return one verifier-compatible process proof or fail closed."""

    normalized = _validate_input(payload)
    seed = normalized["seed"]
    envelope = {
        "schema": f"core.f3.graph_residual.hidden16.seed{seed}.process_exit_proof.v1",
        "report_id": f"f3-graph-residual-hidden16-seed{seed}-process-exit-proof-v1",
        "status": "exited_successfully",
        "source_bound": True,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "seed": seed,
        "run_id": normalized["run_id"],
        "namespace": normalized["namespace"],
        "namespace_nonce": normalized["namespace_nonce"],
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "manifest_sha256": normalized["manifest_sha256"],
        "training_receipt_sha256": normalized["training_receipt_sha256"],
        "checkpoint": normalized["checkpoint"],
        "trajectory": normalized["trajectory"],
        "evaluator_alive": False,
        "launcher_alive": False,
        "evaluator_returncode": 0,
        "launcher_returncode": 0,
        "returncode": 0,
    }
    errors = validate_envelope(envelope)
    if errors:
        _fail("normalized envelope is not accepted by the residual verifier: " + "; ".join(errors))
    return envelope


def validate_envelope(envelope: Mapping[str, Any]) -> list[str]:
    """Validate a normalized envelope before any optional publication."""

    errors: list[str] = []
    try:
        _walk_json(envelope, "process_exit_proof")
        _reject_aliases(envelope, "process_exit_proof", allow_contract_fields=True)
        seed = _strict_int(envelope.get("seed"), "process_exit_proof.seed", 0)
        if seed not in SEEDS:
            _fail(f"process_exit_proof.seed must be one of {SEEDS}")
        verifier._validate_process(envelope, seed, "process_exit_proof")
    except (BuilderError, verifier.VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def build_default_blocked_report(observed_at_utc: str = "2026-09-28T00:00:00Z") -> dict[str, Any]:
    report = {
        "schema": BUILDER_SCHEMA,
        "report_id": BUILDER_REPORT_ID,
        "status": "blocked_fail_closed",
        "fail_closed": True,
        "source_bound": False,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "process_exit_proof": None,
        "expected_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "process_envelope_schema": verifier.PROCESS_SCHEMA,
            "bounded_json_only": True,
            "declared_artifacts_are_not_opened": True,
            "zero_credit_only": True,
        },
        "blocked_reasons": [
            "no post-terminal observation was supplied",
            "no process-exit proof envelope was constructed",
            "default report is blocked and carries zero credit",
        ],
        "side_effects": {
            "bounded_json_opened": False,
            "artifact_metadata_stat_only": False,
            "checkpoint_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "evaluation_content_opened": False,
            "process_started": False,
            "reports_positive_write": False,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "post_terminal_observation_supplied": False,
            "checkpoint_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "evaluation_content_opened": False,
            "runtime_identity_fields_accepted": False,
            "promotion_aliases_accepted": False,
        },
        "observed_at_utc": _string(observed_at_utc, "observed_at_utc"),
    }
    errors = validate_blocked_report(report)
    if errors:
        _fail("internal default blocked report is invalid: " + "; ".join(errors))
    return report


def validate_blocked_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "blocked_report")
        _reject_aliases(report, "blocked_report", allow_contract_fields=True)
        _reject_unknown(report, BLOCKED_REPORT_KEYS, "blocked_report")
        for key, expected in (
            ("schema", BUILDER_SCHEMA),
            ("report_id", BUILDER_REPORT_ID),
            ("status", "blocked_fail_closed"),
            ("fail_closed", True),
            ("source_bound", False),
            ("diagnostic_only", True),
            ("formal", False),
            ("formal_eligible", False),
            ("T1_numerical", False),
            ("T2_macro", False),
            ("T2_path", False),
            ("qualification", False),
            ("qualification_credit", 0),
            ("credit", 0),
            ("process_exit_proof", None),
        ):
            _check_exact(report, key, expected, "blocked_report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) or not item for item in reasons):
            _fail("blocked_report.blocked_reasons must be a non-empty string list")
        contract = _mapping(report.get("expected_contract"), "blocked_report.expected_contract")
        _check_exact(contract, "process_envelope_schema", verifier.PROCESS_SCHEMA, "blocked_report.expected_contract")
        _check_exact(contract, "bounded_json_only", True, "blocked_report.expected_contract")
        _check_exact(contract, "declared_artifacts_are_not_opened", True, "blocked_report.expected_contract")
        _check_exact(contract, "zero_credit_only", True, "blocked_report.expected_contract")
        _mapping(report.get("side_effects"), "blocked_report.side_effects")
        _mapping(report.get("input_boundary"), "blocked_report.input_boundary")
        _string(report.get("observed_at_utc"), "blocked_report.observed_at_utc")
    except (BuilderError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def _is_reports_path(root: Path, output: Path | str) -> bool:
    candidate = Path(os.path.abspath(os.fspath(output)))
    reports = Path(os.path.abspath(os.fspath(root))) / "reports"
    try:
        candidate.relative_to(reports)
    except ValueError:
        return False
    return True


def _open_output_parent(path: str, name: str) -> tuple[int, list[int]]:
    return _open_absolute_parent(path, name)


def _write_new_json(path: Path | str, payload: Mapping[str, Any], *, markdown: bool = False) -> None:
    output = _absolute_clean_path(os.fspath(path), "output path")
    if Path(output).suffix.lower() != ".json" and not (markdown and output.endswith(".zh-CN.md")):
        _fail("output path must be JSON or the fixed markdown sample")
    raw = (canonical_json(payload) + "\n").encode("utf-8")
    if len(raw) > MAX_JSON_BYTES:
        _fail("output exceeds bounded JSON limit")
    parent_fd, opened = _open_output_parent(output, "output path")
    temporary_name: str | None = None
    try:
        try:
            existing = os.stat(Path(output).name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                _fail("output path is a symlink")
            if not stat.S_ISREG(existing.st_mode):
                _fail("output path is not a regular file")
            if existing.st_nlink != 1:
                _fail("output path is hard-linked")
            _fail("refusing to overwrite an existing output")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow:
            _fail("platform does not provide O_NOFOLLOW")
        for _ in range(16):
            temporary_name = f".{Path(output).name}.{secrets.token_hex(12)}.tmp"
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | nofollow,
                    0o644,
                    dir_fd=parent_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            _fail("could not allocate a temporary output path")
        try:
            if os.write(descriptor, raw) != len(raw):
                _fail("short output write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        published_temp = temporary_name
        try:
            os.link(
                published_temp,
                Path(output).name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            _fail("output path appeared during atomic publication")
        os.unlink(published_temp, dir_fd=parent_fd)
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


def write_default_blocked_report(root: Path | str = LAB_ROOT, output: Path | str | None = None) -> Path:
    root_path = Path(os.path.abspath(os.fspath(root)))
    target = root_path / "reports" / DEFAULT_BLOCKED_FILENAME if output is None else Path(os.path.abspath(os.fspath(output)))
    expected = root_path / "reports" / DEFAULT_BLOCKED_FILENAME
    if target != expected:
        _fail("the only reports output is the fixed default blocked JSON sample")
    report = build_default_blocked_report()
    _write_new_json(target, report)
    return target


def write_normalized_envelope(root: Path | str, output: Path | str, envelope: Mapping[str, Any]) -> Path:
    root_path = Path(os.path.abspath(os.fspath(root)))
    if _is_reports_path(root_path, output):
        _fail("positive normalized envelopes cannot be written below reports")
    errors = validate_envelope(envelope)
    if errors:
        _fail("refusing to write invalid normalized envelope: " + "; ".join(errors))
    _write_new_json(output, envelope)
    return Path(os.path.abspath(os.fspath(output)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--input", type=Path, default=None, help="bounded post-terminal observation JSON")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    root = Path(os.path.abspath(os.fspath(args.root)))
    if args.input is None:
        report = build_default_blocked_report()
        if args.output is not None:
            write_default_blocked_report(root, args.output)
        print(canonical_json(report))
        return 2
    payload = load_observation(root, args.input)
    envelope = build_envelope(payload)
    if args.output is not None:
        write_normalized_envelope(root, args.output, envelope)
    print(canonical_json(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
