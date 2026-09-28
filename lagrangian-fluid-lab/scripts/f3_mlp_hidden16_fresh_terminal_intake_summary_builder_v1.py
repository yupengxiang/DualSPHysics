#!/usr/bin/env python3
"""Build bounded, per-seed identity summaries for fresh MLP rollouts.

This is an intake boundary, not a launcher and not a terminal-proof minting
service.  It consumes an already finished evaluator JSON, a trajectory
metadata/stream-hash receipt, an independent HDF5-validator JSON, the existing
training matrix/history summary, and (when available) a process-exit proof.

The evaluator JSON may be large.  It is never loaded as a Python object: the
streaming reader hashes it while extracting only the small completion fields
needed by this contract.  The trajectory HDF5 is never opened or hashed here;
its stream hash is supplied by the trajectory metadata and its path/bytes are
checked against the independent validator receipt.  The builder never starts,
stops, waits for, or otherwise controls an evaluator and never creates a
process-exit proof.  Every result is diagnostic-only and zero-credit.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, BinaryIO


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
GPU_COUNT = 8
PARTICLES = 34560
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25

SUMMARY_SCHEMA = "core.f3.mlp.hidden16.fresh_terminal_intake_summary.v1"
TRAJECTORY_METADATA_SCHEMA = "core.f3.mlp.hidden16.fresh_terminal.trajectory_metadata.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
TRAINING_MATRIX_SCHEMAS = frozenset(
    {
        "core.f3.mlp.hidden16.training_matrix.v1",
        "core.f3.mlp.hidden16.training_evidence_matrix.v1",
    }
)
PROCESS_SCHEMA_PREFIX = "core.f3.mlp.hidden16.seed"
PROCESS_SCHEMA_SUFFIX = ".process_exit_proof.v1"
HISTORY_SCHEMA_LEGACY = "core.f3.mlp.hidden16.full835.rollout_diagnostic.summary.v1"

BOUNDED_JSON_BYTES = 2 * 1024 * 1024
MAX_EVALUATION_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
MAX_DECLARED_ARTIFACT_BYTES = 1 << 50
MAX_CHECKPOINT_BYTES = 1 << 30
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^f3-mlp500-hidden16-seed(?:17|29|43)-20260928$")
PROCESS_PROOF_FILENAME = "F3-MLP-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"


class IntakeError(ValueError):
    """Malformed, unsafe, incomplete, or cross-file-inconsistent intake."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


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
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        _fail(f"{name} is oversized")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        _fail(f"{name} must be finite")
    return result


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


def _zero_credit(value: Mapping[str, Any], name: str, *, require: bool = True) -> None:
    expected = {
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
    for key, wanted in expected.items():
        if key not in value:
            if require:
                _fail(f"{name}.{key} is missing")
            continue
        _exact(value, key, wanted, name)


def _canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"cannot canonicalize digest input: {error}")
    return hashlib.sha256(encoded).hexdigest()


def _absolute_path(value: Any, name: str) -> Path:
    if isinstance(value, Path):
        text = str(value)
        if not text or "\x00" in text:
            _fail(f"{name} must be a non-empty path")
    else:
        text = _string(value, name)
    path = Path(text)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a lexical path alias")
    return path


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_nlink, info.st_size)


def _allowed_path(path: Path, root: Path, name: str) -> None:
    roots = (Path(os.path.abspath(root)), Path("/tmp"))
    candidate = Path(os.path.abspath(path))
    if not any(candidate == allowed or allowed in candidate.parents for allowed in roots):
        _fail(f"{name} escapes bounded roots")


def _assert_no_symlink_components(path: Path, name: str) -> None:
    current = path
    components: list[Path] = []
    while True:
        components.append(current)
        if current == current.parent:
            break
        current = current.parent
    for component in reversed(components):
        try:
            info = os.lstat(component)
        except OSError as error:
            _fail(f"{name} cannot inspect {component}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {component}")


def _regular_single_link(path: Path, name: str) -> os.stat_result:
    _assert_no_symlink_components(path, name)
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"{name} cannot be inspected: {error}")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} is not a regular file")
    if info.st_nlink != 1:
        _fail(f"{name} is a hardlink with {info.st_nlink} links")
    return info


def _bounded_json(path: Path | str, *, root: Path, name: str) -> tuple[Mapping[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name)
    _allowed_path(candidate, root, name)
    before = _regular_single_link(candidate, name)
    if before.st_size > BOUNDED_JSON_BYTES:
        _fail(f"{name} exceeds bounded JSON size")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"{name} cannot be opened safely: {error}")
    try:
        opened = os.fstat(fd)
        if _stat_identity(opened) != _stat_identity(before):
            _fail(f"{name} changed during open")
        chunks: list[bytes] = []
        total = 0
        while total <= BOUNDED_JSON_BYTES:
            chunk = os.read(fd, min(65536, BOUNDED_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > BOUNDED_JSON_BYTES:
            _fail(f"{name} exceeds bounded JSON size")
        closed = os.fstat(fd)
        if _stat_identity(closed) != _stat_identity(before):
            _fail(f"{name} changed while being read")
    except OSError as error:
        _fail(f"{name} cannot be read safely: {error}")
    finally:
        try:
            os.close(fd)
        except OSError as error:
            _fail(f"{name} cannot be closed safely: {error}")
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"{name} changed or disappeared after read: {error}")
    if _stat_identity(after) != _stat_identity(before):
        _fail(f"{name} changed after read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, IntakeError, RecursionError) as error:
        _fail(f"{name} is invalid JSON: {error}")
    payload = _mapping(payload, name)
    try:
        _walk(payload, name)
    except RecursionError as error:
        _fail(f"{name} exceeds bounded JSON depth: {error}")
    return payload, {"path": str(candidate), "exists": True, "opened": True,
                     "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                     "schema": payload.get("schema")}


def _artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, frozenset({"path", "sha256", "bytes"}), name)
    path = _absolute_path(item.get("path"), f"{name}.path")
    if suffix is not None and not str(path).endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    size = _int(item.get("bytes"), f"{name}.bytes", 1)
    if size > MAX_DECLARED_ARTIFACT_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    return {"path": str(path), "sha256": _sha(item.get("sha256"), f"{name}.sha256"), "bytes": size}


def _receipt_artifact(
    value: Any,
    name: str,
    *,
    suffix: str | None = None,
    maximum_bytes: int = MAX_DECLARED_ARTIFACT_BYTES,
) -> dict[str, Any]:
    """Extract identity fields from a historical receipt with extra metadata."""

    item = _mapping(value, name)
    path = _absolute_path(item.get("path"), f"{name}.path")
    if suffix is not None and not str(path).endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    size = _int(item.get("bytes"), f"{name}.bytes", 1)
    if size > maximum_bytes:
        _fail(f"{name}.bytes exceeds the declared bound")
    return {"path": str(path), "sha256": _sha(item.get("sha256"), f"{name}.sha256"), "bytes": size}


def _expected_run_id(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928"


def _expected_checkpoint_name(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt"


def _expected_checkpoint_path(seed: int) -> Path:
    return Path("/tmp") / _expected_checkpoint_name(seed)


def _expected_training_path(seed: int) -> Path:
    return Path("/tmp") / f"f3-mlp500-hidden16-seed{seed}-20260928-training.json"


def _expected_process_proof_path(root: Path, seed: int) -> Path:
    return root / "reports" / PROCESS_PROOF_FILENAME.format(seed=seed)


def _checkpoint_artifact(
    value: Any,
    seed: int,
    name: str,
    *,
    allow_missing_bytes: bool = False,
) -> dict[str, Any]:
    item = _mapping(value, name)
    path = _absolute_path(item.get("path"), f"{name}.path")
    if not str(path).endswith(".pt"):
        _fail(f"{name}.path must end with .pt")
    if "bytes" not in item and allow_missing_bytes:
        size: int | None = None
    else:
        size = _int(item.get("bytes"), f"{name}.bytes", 1)
        if size > MAX_CHECKPOINT_BYTES:
            _fail(f"{name}.bytes exceeds the checkpoint bound")
    checkpoint = {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": size,
    }
    expected_path = _expected_checkpoint_path(seed)
    if Path(checkpoint["path"]) != expected_path:
        _fail(f"{name}.path is not the canonical checkpoint path: {expected_path}")
    return checkpoint


def _expected_namespace(seed: int, nonce: str, namespace_root: Path = Path("/tmp")) -> Path:
    return namespace_root / f"f3-mlp500-hidden16-seed{seed}-full835-nonce{nonce}"


def _validate_seed(seed: int) -> int:
    if type(seed) is not int or seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    return seed


def _validate_nonce(nonce: Any, name: str) -> str:
    value = _string(nonce, name)
    if NONCE_RE.fullmatch(value) is None or value == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal nonce")
    return value


def _namespace_from_evaluation(path: Path, seed: int, namespace_root: Path) -> tuple[Path, str]:
    root = Path(os.path.abspath(namespace_root))
    expected_prefix = root / f"f3-mlp500-hidden16-seed{seed}-full835-nonce"
    text = str(path)
    prefix = str(expected_prefix)
    suffix = "-evaluation.json"
    if not text.startswith(prefix) or not text.endswith(suffix):
        _fail(f"evaluation path is not the canonical fresh seed{seed}/full835 namespace")
    nonce = text[len(prefix):-len(suffix)]
    _validate_nonce(nonce, "evaluation namespace nonce")
    namespace = _expected_namespace(seed, nonce, root)
    if text != str(namespace) + suffix:
        _fail("evaluation path has a noncanonical namespace spelling")
    return namespace, nonce


# ---------------------------------------------------------------------------
# Bounded streaming extraction for core.evaluation.v1


class _ByteStream:
    def __init__(self, handle: BinaryIO, *, maximum: int) -> None:
        self.handle = handle
        self.maximum = maximum
        self.digest = hashlib.sha256()
        self.total = 0
        self.buffer = b""
        self.eof = False

    def _fill(self) -> None:
        if self.buffer or self.eof:
            return
        chunk = self.handle.read(65536)
        if not chunk:
            self.eof = True
            return
        self.total += len(chunk)
        if self.total > self.maximum:
            _fail(f"evaluation JSON exceeds {self.maximum} bytes")
        self.digest.update(chunk)
        self.buffer = chunk

    def peek(self) -> int | None:
        self._fill()
        return self.buffer[0] if self.buffer else None

    def take(self) -> int | None:
        self._fill()
        if not self.buffer:
            return None
        value = self.buffer[0]
        self.buffer = self.buffer[1:]
        return value


class _StreamingJSON:
    def __init__(self, stream: _ByteStream) -> None:
        self.stream = stream
        self.depth = 0

    @staticmethod
    def _space(value: int | None) -> bool:
        return value in (9, 10, 13, 32)

    def _ws(self) -> None:
        while self._space(self.stream.peek()):
            self.stream.take()

    def _expect(self, expected: int) -> None:
        observed = self.stream.take()
        if observed != expected:
            _fail(f"evaluation JSON expected {chr(expected)!r}, got {observed!r}")

    def _string(self) -> str:
        self._expect(ord('"'))
        raw = bytearray(b'"')
        escaped = False
        while True:
            value = self.stream.take()
            if value is None:
                _fail("unterminated evaluation JSON string")
            raw.append(value)
            if len(raw) > MAX_STRING_BYTES:
                _fail("evaluation JSON string is oversized")
            if value == ord('"') and not escaped:
                break
            if value < 0x20 and not escaped:
                _fail("evaluation JSON string contains a control character")
            if value == ord('\\') and not escaped:
                escaped = True
            else:
                escaped = False
        try:
            value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, IntakeError) as error:
            _fail(f"invalid evaluation JSON string: {error}")
        if not isinstance(value, str):
            _fail("evaluation JSON string parser returned a non-string")
        return value

    def _scalar(self) -> Any:
        value = self.stream.peek()
        if value == ord('"'):
            return self._string()
        if value is None:
            _fail("evaluation JSON ended while reading a scalar")
        if value in (ord('t'), ord('f'), ord('n')):
            words = {ord('t'): b"true", ord('f'): b"false", ord('n'): b"null"}
            target = words[value]
            raw = bytearray()
            for expected in target:
                observed = self.stream.take()
                raw.append(observed if observed is not None else -1)
            if bytes(raw) != target:
                _fail("invalid evaluation JSON literal")
            return {b"true": True, b"false": False, b"null": None}[bytes(raw)]
        raw = bytearray()
        while True:
            observed = self.stream.peek()
            if observed is None or observed in (9, 10, 13, 32, ord(','), ord(']'), ord('}')):
                break
            raw.append(self.stream.take())  # type: ignore[arg-type]
            if len(raw) > 256:
                _fail("evaluation JSON number/token is oversized")
        if not raw:
            _fail("empty evaluation JSON scalar")
        try:
            result = json.loads(bytes(raw).decode("ascii"), parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, IntakeError) as error:
            _fail(f"invalid evaluation JSON scalar: {error}")
        if isinstance(result, float) and not math.isfinite(result):
            _fail("evaluation JSON scalar is non-finite")
        return result

    def _value(self, *, keep: bool = False) -> Any:
        self._ws()
        value = self.stream.peek()
        if value == ord('{'):
            return self._object(keep=keep)
        if value == ord('['):
            return self._array(keep=keep)
        return self._scalar()

    def _object(self, *, keep: bool = False) -> dict[str, Any] | None:
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        if self.depth > MAX_JSON_DEPTH:
            _fail("evaluation JSON exceeds maximum depth")
        result: dict[str, Any] | None = {} if keep else None
        seen: set[str] = set()
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation JSON key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            value = self._value(keep=keep)
            if result is not None:
                result[key] = value
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation JSON object requires ',' or '}'")

    def _array(self, *, keep: bool = False) -> list[Any] | None:
        self._ws()
        self._expect(ord('['))
        self.depth += 1
        if self.depth > MAX_JSON_DEPTH:
            _fail("evaluation JSON exceeds maximum depth")
        result: list[Any] | None = [] if keep else None
        self._ws()
        if self.stream.peek() == ord(']'):
            self.stream.take()
            self.depth -= 1
            return result
        count = 0
        while True:
            count += 1
            if count > MAX_ARRAY_ITEMS:
                _fail("evaluation JSON array exceeds bounded item count")
            value = self._value(keep=keep)
            if result is not None:
                result.append(value)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord(']'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation JSON array requires ',' or ']'")

    def _case(self) -> dict[str, Any] | None:
        # The case object is small around the completion fields but contains
        # metric arrays.  Keep only the fields this intake contract needs.
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        if self.depth > MAX_JSON_DEPTH:
            _fail("evaluation case exceeds maximum depth")
        wanted = {
            "case_id", "frames_expected", "expected_frames", "frames_executed",
            "frames_predicted", "executed", "failure_category",
            "first_failure_frame", "execution_complete", "finite_rollout_complete",
            "future_state_inputs", "score",
        }
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation case key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            if key in wanted:
                if key == "score":
                    result[key] = self._score()
                else:
                    result[key] = self._value(keep=False)
            else:
                self._value(keep=False)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation case requires ',' or '}'")

    def _score(self) -> dict[str, Any]:
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        wanted = {
            "expected_frames", "finite_prefix_frames", "executed", "complete",
            "failure_category", "raw_error_coverage",
        }
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation score key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            result[key] = self._value(keep=False) if key in wanted else (self._value(keep=False) or None)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation score requires ',' or '}'")

    def _case_map(self) -> dict[str, Any] | None:
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation cases key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            result[key] = self._case() if key == CASE_ID else self._value(keep=False)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation cases requires ',' or '}'")

    def _expected_frames(self) -> dict[str, Any] | None:
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        result: dict[str, Any] = {}
        seen: set[str] = set()
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation expected_frames key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            result[key] = self._value(keep=False)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                return result
            if delimiter != ord(','):
                _fail("evaluation expected_frames requires ',' or '}'")

    def _string_array(self) -> list[str]:
        value = self._array(keep=True)
        if not isinstance(value, list):
            _fail("evaluation case list is invalid")
        result: list[str] = []
        for item in value:
            result.append(_string(item, "evaluation case list item"))
        return result

    def top(self) -> dict[str, Any]:
        self._ws()
        self._expect(ord('{'))
        self.depth += 1
        result: dict[str, Any] = {}
        seen: set[str] = set()
        scalar_keys = {
            "schema", "evaluation_mode", "diagnostic", "formal_eligible", "autonomous",
            "future_state_inputs", "maximum_steps", "case_id", "split",
            "requested_transitions", "transitions_executed", "trajectory_frames_including_initial",
            "expected_full_case_transitions", "expected_full_case_frames",
            "full_registered_denominator_complete", "requested_window_complete",
            "finite_rollout_complete", "failure_category", "execution_complete",
        }
        array_keys = {"registered_case_ids", "selected_case_ids"}
        self._ws()
        if self.stream.peek() == ord('}'):
            self.stream.take()
            self.depth -= 1
            return result
        while True:
            self._ws()
            key = self._string()
            if key in seen:
                _fail(f"duplicate evaluation top-level key: {key}")
            seen.add(key)
            self._expect(ord(':'))
            if key == "cases":
                result[key] = self._case_map()
            elif key == "expected_frames":
                result[key] = self._expected_frames()
            elif key in scalar_keys:
                result[key] = self._value(keep=False)
            elif key in array_keys:
                result[key] = self._string_array()
            else:
                self._value(keep=False)
            self._ws()
            delimiter = self.stream.take()
            if delimiter == ord('}'):
                self.depth -= 1
                self._ws()
                if self.stream.peek() is not None:
                    _fail("trailing data follows evaluation JSON")
                return result
            if delimiter != ord(','):
                _fail("evaluation JSON object requires ',' or '}'")


def _stream_evaluation(path: Path, *, root: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _allowed_path(path, root, name)
    before = _regular_single_link(path, name)
    if before.st_size > MAX_EVALUATION_BYTES:
        _fail(f"{name} exceeds bounded evaluation size")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"{name} cannot be opened safely: {error}")
    try:
        opened = os.fstat(fd)
        if _stat_identity(opened) != _stat_identity(before):
            _fail(f"{name} changed during open")
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = -1
            stream = _ByteStream(handle, maximum=MAX_EVALUATION_BYTES)
            payload = _StreamingJSON(stream).top()
            if stream.total != before.st_size:
                _fail(f"{name} changed size while being streamed")
            receipt = {"path": str(path), "sha256": stream.digest.hexdigest(), "bytes": stream.total}
    except (OSError, RecursionError) as error:
        _fail(f"{name} cannot be streamed safely: {error}")
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError as error:
                _fail(f"{name} cannot be closed safely: {error}")
    try:
        after = os.lstat(path)
    except OSError as error:
        _fail(f"{name} changed or disappeared after streaming: {error}")
    if _stat_identity(after) != _stat_identity(before):
        _fail(f"{name} changed after streaming")
    return payload, receipt


def _validate_zero_claims(payload: Mapping[str, Any], name: str) -> None:
    for key, expected in (
        ("diagnostic_only", True), ("formal", False), ("formal_eligible", False),
        ("T1_numerical", False), ("T2_macro", False), ("T2_path", False),
        ("qualification_credit", 0), ("credit", 0),
    ):
        if key in payload:
            _exact(payload, key, expected, name)
    qualification = payload.get("qualification")
    if isinstance(qualification, Mapping):
        for key, expected in (("qualification", False), ("T1_numerical", False), ("T2_macro", False), ("credit", 0), ("qualification_credit", 0)):
            if key in qualification:
                _exact(qualification, key, expected, f"{name}.qualification")
    elif qualification is not None:
        _exact(payload, "qualification", False, name)


def _validate_training_matrix(payload: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    schema = _string(payload.get("schema"), f"{name}.schema")
    if schema not in TRAINING_MATRIX_SCHEMAS:
        _fail(f"{name}.schema is not an accepted MLP hidden16 training matrix")
    _validate_zero_claims(payload, name)
    _exact(payload, "diagnostic_only", True, name)
    model = payload.get("model")
    if model is not None and model != MODEL:
        _fail(f"{name}.model must be {MODEL!r}")
    shared = payload.get("shared_config")
    if isinstance(shared, Mapping):
        _exact(shared, "model_kind", MODEL, f"{name}.shared_config")
        _exact(shared, "hidden", HIDDEN, f"{name}.shared_config")
        _exact(shared, "updates", UPDATES, f"{name}.shared_config")
    runs = payload.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail(f"{name}.runs must contain exactly three rows")
    selected: dict[int, Mapping[str, Any]] = {}
    for row_value in runs:
        row = _mapping(row_value, f"{name}.run")
        row_seed = _int(row.get("seed"), f"{name}.run.seed")
        if row_seed not in SEEDS or row_seed in selected:
            _fail(f"{name}.runs contains an invalid or duplicate seed")
        if row.get("status") not in {None, "bound_complete"}:
            _fail(f"{name}.seed{row_seed}.status is not bound_complete")
        if row.get("completed_updates") is not None:
            _exact(row, "completed_updates", UPDATES, f"{name}.seed{row_seed}")
        evidence = row.get("evidence")
        if isinstance(evidence, Mapping):
            _exact(evidence, "model_kind", MODEL, f"{name}.seed{row_seed}.evidence")
            _exact(evidence, "hidden", HIDDEN, f"{name}.seed{row_seed}.evidence")
            _exact(evidence, "updates", UPDATES, f"{name}.seed{row_seed}.evidence")
            _exact(evidence, "run_id", _expected_run_id(row_seed), f"{name}.seed{row_seed}.evidence")
            _exact(evidence, "evidence_status", "complete", f"{name}.seed{row_seed}.evidence")
            checkpoint_value = evidence.get("checkpoint")
            if not isinstance(checkpoint_value, Mapping):
                _fail(f"{name}.seed{row_seed}.evidence.checkpoint is missing")
            checkpoint = _checkpoint_artifact(
                checkpoint_value,
                row_seed,
                f"{name}.seed{row_seed}.checkpoint",
                allow_missing_bytes=True,
            )
            if "update" in checkpoint_value:
                _exact(checkpoint_value, "update", UPDATES, f"{name}.seed{row_seed}.checkpoint")
            manifest_sha = _sha(
                evidence.get("manifest_sha256"),
                f"{name}.seed{row_seed}.evidence.manifest_sha256",
            )
        else:
            _exact(row, "run_id", _expected_run_id(row_seed), f"{name}.seed{row_seed}")
            _exact(row, "model_kind", MODEL, f"{name}.seed{row_seed}")
            _exact(row, "hidden", HIDDEN, f"{name}.seed{row_seed}")
            _exact(row, "completed_updates", UPDATES, f"{name}.seed{row_seed}")
            checkpoint = _checkpoint_artifact(
                {
                    "path": row.get("checkpoint_path"),
                    "sha256": row.get("checkpoint_sha256"),
                    "bytes": row.get("checkpoint_bytes"),
                },
                row_seed,
                f"{name}.seed{row_seed}.checkpoint",
                allow_missing_bytes=True,
            )
            if row.get("checkpoint_verified") is not True:
                _fail(f"{name}.seed{row_seed}.checkpoint_verified must be true")
            manifest_sha = _sha(
                row.get("manifest_sha256", payload.get("manifest_sha256")),
                f"{name}.seed{row_seed}.manifest_sha256",
            )

        source_value = row.get("source")
        if source_value is None and isinstance(evidence, Mapping):
            source_value = evidence.get("training_receipt")
        if source_value is None:
            source_value = row.get("training_receipt")
        training_receipt = _receipt_artifact(
            source_value,
            f"{name}.seed{row_seed}.training_receipt",
            suffix=".json",
        )
        if Path(training_receipt["path"]) != _expected_training_path(row_seed):
            _fail(
                f"{name}.seed{row_seed}.training_receipt.path is not the canonical training path"
            )
        selected[row_seed] = {
            "run_id": _expected_run_id(row_seed),
            "manifest_sha256": manifest_sha,
            "training_receipt": training_receipt,
            "checkpoint": checkpoint,
        }
    if sorted(selected) != list(SEEDS):
        _fail(f"{name} does not contain exactly seeds {SEEDS}")
    return dict(selected[seed])


def _validate_history(payload: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    expected_schema = f"core.f3.mlp.hidden16.seed{seed}.full835_rollout_diagnostic.summary.v1"
    observed_schema = _string(payload.get("schema"), f"{name}.schema")
    if observed_schema not in {expected_schema, HISTORY_SCHEMA_LEGACY}:
        _fail(
            f"{name}.schema must be one of "
            f"{expected_schema!r}, {HISTORY_SCHEMA_LEGACY!r}"
        )
    _exact(payload, "status", "completed", name)
    _exact(payload, "diagnostic_only", True, name)
    _validate_zero_claims(payload, name)
    protocol = _mapping(payload.get("protocol"), f"{name}.protocol")
    for key, expected in (
        ("model", MODEL), ("seed", seed), ("training_updates", UPDATES),
        ("hidden", HIDDEN), ("case_id", CASE_ID), ("split", SPLIT),
        ("diagnostic", True), ("autonomous", True), ("future_state_inputs", False),
    ):
        _exact(protocol, key, expected, f"{name}.protocol")
    if "maximum_steps" in protocol:
        _exact(protocol, "maximum_steps", TRANSITIONS, f"{name}.protocol")
    else:
        _exact(protocol, "requested_transitions", TRANSITIONS, f"{name}.protocol")
    evaluation = _mapping(payload.get("evaluation"), f"{name}.evaluation")
    for key, expected in (
        ("status", "completed"), ("transitions_executed", TRANSITIONS),
        ("trajectory_frames_including_initial", FRAMES),
        ("finite_rollout_complete", True), ("future_state_inputs", False),
    ):
        _exact(evaluation, key, expected, f"{name}.evaluation")
    source = _mapping(payload.get("source"), f"{name}.source")
    manifest = source.get("manifest")
    if isinstance(manifest, Mapping):
        manifest_sha = _sha(manifest.get("sha256"), f"{name}.source.manifest.sha256")
    else:
        manifest_sha = _sha(source.get("manifest_sha256"), f"{name}.source.manifest_sha256")
    checkpoint_payload = payload.get("checkpoint")
    if isinstance(checkpoint_payload, Mapping):
        checkpoint = _checkpoint_artifact(checkpoint_payload, seed, f"{name}.checkpoint")
    else:
        training = _mapping(payload.get("training"), f"{name}.training")
        _exact(training, "evidence_status", "complete", f"{name}.training")
        _exact(training, "completed_updates", UPDATES, f"{name}.training")
        _exact(training, "checkpoint_verified", True, f"{name}.training")
        checkpoint = _checkpoint_artifact(
            {
                "path": _expected_checkpoint_path(seed),
                "sha256": training.get("checkpoint_sha256"),
                "bytes": training.get("checkpoint_bytes"),
            },
            seed,
            f"{name}.checkpoint",
        )
    history_training_receipt = None
    if isinstance(checkpoint_payload, Mapping) and checkpoint_payload.get("training_receipt") is not None:
        history_training_receipt = _receipt_artifact(
            checkpoint_payload.get("training_receipt"),
            f"{name}.checkpoint.training_receipt",
            suffix=".json",
        )
        if Path(history_training_receipt["path"]) != _expected_training_path(seed):
            _fail(f"{name}.checkpoint.training_receipt.path is not canonical")
    return {
        "run_id": _expected_run_id(seed),
        "manifest_sha256": manifest_sha,
        "training_receipt": history_training_receipt,
        "checkpoint": checkpoint,
    }


def _validate_evaluation(payload: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _exact(payload, "schema", "core.evaluation.v1", name)
    _exact(payload, "evaluation_mode", "diagnostic", name)
    _exact(payload, "diagnostic", True, name)
    _exact(payload, "formal_eligible", False, name)
    _exact(payload, "autonomous", True, name)
    _exact(payload, "future_state_inputs", False, name)
    if "maximum_steps" in payload:
        _exact(payload, "maximum_steps", TRANSITIONS, name)
    for key in ("registered_case_ids", "selected_case_ids"):
        values = payload.get(key)
        if not isinstance(values, list) or CASE_ID not in values:
            _fail(f"{name}.{key} does not bind {CASE_ID}")
    expected_frames = _mapping(payload.get("expected_frames"), f"{name}.expected_frames")
    _exact(expected_frames, CASE_ID, TRANSITIONS, f"{name}.expected_frames")
    case_map = _mapping(payload.get("cases"), f"{name}.cases")
    case = _mapping(case_map.get(CASE_ID), f"{name}.cases.{CASE_ID}")
    for key, expected in (
        ("case_id", CASE_ID), ("frames_expected", TRANSITIONS),
        ("expected_frames", TRANSITIONS), ("frames_executed", TRANSITIONS),
        ("frames_predicted", TRANSITIONS), ("executed", True),
        ("failure_category", None), ("first_failure_frame", None),
        ("execution_complete", True), ("finite_rollout_complete", True),
        ("future_state_inputs", False),
    ):
        _exact(case, key, expected, f"{name}.cases.{CASE_ID}")
    score = _mapping(case.get("score"), f"{name}.cases.{CASE_ID}.score")
    for key, expected in (
        ("expected_frames", TRANSITIONS), ("finite_prefix_frames", TRANSITIONS),
        ("executed", True), ("complete", True), ("failure_category", None),
    ):
        _exact(score, key, expected, f"{name}.cases.{CASE_ID}.score")
    return {"case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES}


def _validate_trajectory_metadata(payload: Mapping[str, Any], seed: int, namespace: Path, nonce: str, *, root: Path) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "seed", "model", "hidden", "updates", "case_id", "split",
        "transitions", "frames", "namespace", "namespace_nonce", "trajectory",
        "stream_hash", "diagnostic_only", "source_bound", "future_state_inputs",
    })
    _unknown(payload, allowed, "trajectory_metadata")
    _exact(payload, "schema", TRAJECTORY_METADATA_SCHEMA, "trajectory_metadata")
    for key, expected in (
        ("seed", seed), ("model", MODEL), ("hidden", HIDDEN), ("updates", UPDATES),
        ("case_id", CASE_ID), ("split", SPLIT), ("transitions", TRANSITIONS),
        ("frames", FRAMES), ("namespace", str(namespace)), ("namespace_nonce", nonce),
        ("diagnostic_only", True), ("source_bound", True), ("future_state_inputs", False),
    ):
        _exact(payload, key, expected, "trajectory_metadata")
    trajectory = _artifact(payload.get("trajectory"), "trajectory_metadata.trajectory", suffix=".h5")
    expected_path = Path(str(namespace) + "-trajectory.h5")
    if Path(trajectory["path"]) != expected_path:
        _fail("trajectory metadata path is not the canonical fresh namespace")
    stream = _mapping(payload.get("stream_hash"), "trajectory_metadata.stream_hash")
    _unknown(stream, frozenset({"algorithm", "sha256", "bytes"}), "trajectory_metadata.stream_hash")
    _exact(stream, "algorithm", "sha256", "trajectory_metadata.stream_hash")
    stream_sha = _sha(stream.get("sha256"), "trajectory_metadata.stream_hash.sha256")
    stream_bytes = _int(stream.get("bytes"), "trajectory_metadata.stream_hash.bytes", 1)
    if stream_sha != trajectory["sha256"] or stream_bytes != trajectory["bytes"]:
        _fail("trajectory metadata stream hash/bytes disagree with trajectory identity")
    _allowed_path(expected_path, root, "trajectory HDF5")
    info = _regular_single_link(expected_path, "trajectory HDF5")
    if info.st_size != trajectory["bytes"]:
        _fail("trajectory HDF5 stat bytes disagree with trajectory metadata")
    return trajectory


def _validate_validator(
    payload: Mapping[str, Any],
    seed: int,
    namespace: Path,
    trajectory: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    name: str,
) -> None:
    allowed = frozenset(
        {
            "schema", "passed", "fail_closed", "diagnostic_only", "synthetic_only",
            "production_artifacts_touched", "qualification_credit", "case_id",
            "evaluation_json", "trajectory_hdf5", "expected_transitions", "frames_executed",
            "complete", "incomplete", "failure_category", "checks", "row_fields_checked",
        }
    )
    _unknown(payload, allowed, name)
    for key, expected in (
        ("schema", VALIDATOR_SCHEMA),
        ("passed", True),
        ("fail_closed", False),
        ("diagnostic_only", True),
        ("synthetic_only", False),
        ("production_artifacts_touched", False),
        ("qualification_credit", 0),
        ("case_id", CASE_ID),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("complete", True),
        ("incomplete", False),
        ("failure_category", None),
        ("evaluation_json", evaluation["path"]),
        ("trajectory_hdf5", trajectory["path"]),
    ):
        _exact(payload, key, expected, name)
    checks = _mapping(payload.get("checks"), f"{name}.checks")
    check_allowed = frozenset(
        {
            "case_binding", "shape", "time", "valid", "future_state_inputs",
            "completion_semantics", "trajectory_frames", "trajectory_transitions",
            "executed_frame_count", "tail_frame_count", "particle_count",
            "time_start", "time_end",
        }
    )
    _unknown(checks, check_allowed, f"{name}.checks")
    for key, expected in (
        ("case_binding", True),
        ("shape", True),
        ("time", True),
        ("valid", True),
        ("future_state_inputs", True),
        ("completion_semantics", True),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("executed_frame_count", FRAMES),
        ("tail_frame_count", 0),
        ("particle_count", PARTICLES),
        ("time_start", 0.0),
    ):
        _exact(checks, key, expected, f"{name}.checks")
    if type(checks.get("time_start")) is not float:
        _fail(f"{name}.checks.time_start must be a JSON float")
    _number(checks.get("time_start"), f"{name}.checks.time_start")
    time_end = _number(checks.get("time_end"), f"{name}.checks.time_end")
    if time_end <= 0.0:
        _fail(f"{name}.checks.time_end must be positive")
    rows = payload.get("row_fields_checked")
    if (
        not isinstance(rows, list)
        or not rows
        or any(not isinstance(item, str) or not item for item in rows)
    ):
        _fail(f"{name}.row_fields_checked must be a non-empty string list")
    expected_path = Path(str(namespace) + "-hdf5-validation.json")
    if Path(name) != expected_path:
        _fail(f"{name} is not the canonical validator path: {expected_path}")


def _canonical_command_digests(
    root: Path,
    seed: int,
    namespace: Path,
    checkpoint: Mapping[str, Any],
) -> frozenset[str]:
    """Return the exact launcher command digests admitted for eight GPUs.

    The launcher records only ``command_sha256`` in its current process proof.
    Recomputing the digest here prevents a proof from choosing an arbitrary
    executable, manifest, data root, checkpoint, or rollout output while still
    keeping the intake read-only.  GPU selection is the only allowed variant.
    """

    python = root / ".venv" / "bin" / "python"
    core_learning = root / "scripts" / "core_learning.py"
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    outputs = {
        "evaluation": Path(str(namespace) + "-evaluation.json"),
        "trajectory": Path(str(namespace) + "-trajectory.h5"),
        "progress": Path(str(namespace) + "-evaluation-progress.json"),
    }
    command = (
        str(python), "-u", str(core_learning), "evaluate",
        "--manifest", str(manifest), "--data-root", str(root),
        "--checkpoint", str(checkpoint["path"]), "--case-id", CASE_ID,
        "--split", SPLIT, "--maximum-steps", str(TRANSITIONS),
        "--chunk-size", str(CHUNK_SIZE), "--device", "cuda:0",
        "--progress-every", str(PROGRESS_EVERY),
        "--trajectory-output", str(outputs["trajectory"]),
        "--progress-output", str(outputs["progress"]),
        "--output", str(outputs["evaluation"]), "--diagnostic",
    )
    site_packages = (
        root / ".venv" / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    env_overrides = {
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.path.lexists(site_packages):
        env_overrides["PYTHONPATH"] = str(site_packages)
    return frozenset(
        _canonical_digest(
            {
                "argv": list(command),
                "cwd": str(root),
                "env_overrides": {
                    **env_overrides,
                    "CUDA_VISIBLE_DEVICES": str(gpu_index),
                },
            }
        )
        for gpu_index in range(GPU_COUNT)
    )


def _validate_process(
    payload: Mapping[str, Any],
    seed: int,
    namespace: Path,
    nonce: str,
    root: Path,
    training_row: Mapping[str, Any],
    history_row: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    validator_source: Mapping[str, Any],
    process_source: Mapping[str, Any],
    trusted_process_proof_sha256: str | None,
    name: str,
) -> None:
    allowed = frozenset({
        "schema", "report_id", "status", "source_bound", "diagnostic_only", "formal",
        "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification",
        "qualification_credit", "credit", "seed", "run_id", "namespace",
        "namespace_nonce", "evaluator_alive", "launcher_alive", "evaluator_returncode",
        "launcher_returncode", "returncode", "evaluator_pid_observed", "launcher_pid_observed",
        "evaluator_reaped", "launcher_reaped", "command_sha256", "exit_proof_sha256",
        "evaluator_start_identity", "evaluator_end_identity", "launcher_start_identity",
        "launcher_end_identity", "manifest_sha256", "training_manifest_sha256",
        "training_receipt_sha256", "checkpoint", "evaluation", "trajectory", "validator",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", f"{PROCESS_SCHEMA_PREFIX}{seed}{PROCESS_SCHEMA_SUFFIX}", name)
    _exact(payload, "report_id", f"f3-mlp-hidden16-seed{seed}-process-exit-proof-v1-{nonce}", name)
    _exact(payload, "status", "exited_successfully", name)
    _zero_credit(payload, name)
    _exact(payload, "source_bound", True, name)
    for key, expected in (("seed", seed), ("run_id", _expected_run_id(seed)), ("namespace", str(namespace)), ("namespace_nonce", nonce)):
        _exact(payload, key, expected, name)
    for key, expected in (("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0), ("evaluator_reaped", True), ("launcher_reaped", True)):
        _exact(payload, key, expected, name)
    command_sha = _sha(payload.get("command_sha256"), f"{name}.command_sha256")
    if command_sha not in _canonical_command_digests(root, seed, namespace, checkpoint):
        _fail(f"{name}.command_sha256 is not the canonical launcher command digest")
    identities: dict[str, Mapping[str, Any]] = {}
    for key in ("evaluator_start_identity", "evaluator_end_identity", "launcher_start_identity", "launcher_end_identity"):
        identity = _mapping(payload.get(key), f"{name}.{key}")
        _int(identity.get("pid"), f"{name}.{key}.pid", 1)
        _int(identity.get("proc_starttime_ticks"), f"{name}.{key}.proc_starttime_ticks", 0)
        _int(identity.get("observed_monotonic_ns"), f"{name}.{key}.observed_monotonic_ns", 1)
        identities[key] = identity
    if identities["evaluator_start_identity"]["pid"] != identities["evaluator_end_identity"]["pid"]:
        _fail(f"{name}.evaluator process identity PID drifted")
    if identities["evaluator_start_identity"]["proc_starttime_ticks"] != identities["evaluator_end_identity"]["proc_starttime_ticks"]:
        _fail(f"{name}.evaluator process identity starttime drifted")
    if identities["launcher_start_identity"]["pid"] != identities["launcher_end_identity"]["pid"]:
        _fail(f"{name}.launcher process identity PID drifted")
    if identities["launcher_start_identity"]["proc_starttime_ticks"] != identities["launcher_end_identity"]["proc_starttime_ticks"]:
        _fail(f"{name}.launcher process identity starttime drifted")
    _exact(payload, "manifest_sha256", history_row["manifest_sha256"], name)
    _exact(payload, "training_manifest_sha256", training_row["manifest_sha256"], name)
    _exact(payload, "training_receipt_sha256", training_row["training_receipt"]["sha256"], name)
    proof_checkpoint = _checkpoint_artifact(payload.get("checkpoint"), seed, f"{name}.checkpoint")
    if proof_checkpoint != dict(checkpoint):
        _fail(f"{name}.checkpoint identity drifts from training/history")
    for key, expected in (("evaluation", evaluation), ("trajectory", trajectory)):
        artifact = _artifact(payload.get(key), f"{name}.{key}")
        if artifact != dict(expected):
            _fail(f"{name}.{key} identity drifts from intake")
    proof_validator = _artifact(payload.get("validator"), f"{name}.validator", suffix=".json")
    if proof_validator["path"] != validator_source["path"] or proof_validator["sha256"] != validator_source["sha256"] or proof_validator["bytes"] != validator_source["bytes"]:
        _fail(f"{name}.validator identity drifts from validator receipt")
    proof_digest = _sha(payload.get("exit_proof_sha256"), f"{name}.exit_proof_sha256")
    without_digest = dict(payload)
    without_digest.pop("exit_proof_sha256", None)
    if _canonical_digest(without_digest) != proof_digest:
        _fail(f"{name}.exit_proof_sha256 does not cover the process proof")
    if trusted_process_proof_sha256 is None:
        _fail(
            f"{name} has no out-of-band trusted launcher producer attestation; "
            "a self-signed exit_proof_sha256 is not source evidence"
        )
    trusted_digest = _sha(trusted_process_proof_sha256, f"{name}.trusted_process_proof_sha256")
    if trusted_digest != process_source["sha256"]:
        _fail(f"{name}.trusted launcher attestation digest does not match the proof bytes")


@dataclass(frozen=True)
class SeedInputs:
    evaluation: Path
    trajectory_metadata: Path
    validator: Path
    history_summary: Path
    process_exit_proof: Path | None = None
    # This digest must arrive from an out-of-band trusted launcher/receipt
    # channel.  It is deliberately not read from the process-proof JSON, so a
    # proof cannot self-attest its own provenance by recomputing a digest.
    trusted_process_proof_sha256: str | None = None


def _source_missing(path: Path | None, name: str) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "opened": False, "sha256": None, "bytes": None, "schema": None, "name": name}
    return {"path": str(path), "exists": False, "opened": False, "sha256": None, "bytes": None, "schema": None, "name": name}


def _failure_text(name: str, error: BaseException) -> str:
    if isinstance(error, IntakeError):
        return str(error)
    return f"fail-closed: {name} could not be read or validated safely: {type(error).__name__}: {error}"


def _summary_base(seed: int, namespace: Path | None, nonce: str | None) -> dict[str, Any]:
    run_id = _expected_run_id(seed)
    return {
        "schema": SUMMARY_SCHEMA,
        "report_id": f"f3-mlp-hidden16-seed{seed}-fresh-terminal-intake-summary-v1",
        "status": "blocked_fail_closed",
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
        "seed": seed,
        "run_id": run_id,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(namespace) if namespace is not None else None,
        "namespace_nonce": nonce,
        "rollout_identity": None,
        "sources": {},
        "checks": {},
        "blocked_reasons": [],
        "input_boundary": {
            "bounded_json_only": True,
            "max_bounded_json_bytes": BOUNDED_JSON_BYTES,
            "max_evaluation_bytes": MAX_EVALUATION_BYTES,
            "evaluation_stream_hashed": False,
            "evaluation_full_object_loaded": False,
            "trajectory_hdf5_opened": False,
            "trajectory_hdf5_hashed": False,
            "checkpoint_opened": False,
            "process_started": False,
        },
        "side_effects": {
            "runtime_started": False,
            "evaluator_started": False,
            "evaluator_stopped": False,
            "evaluator_restarted": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
    }


def build_seed_summary(
    seed: int,
    inputs: SeedInputs,
    *,
    training_payload: Mapping[str, Any],
    training_source: Mapping[str, Any] | None = None,
    root: Path = LAB_ROOT,
    namespace_root: Path = Path("/tmp"),
) -> dict[str, Any]:
    """Build one summary without launching or controlling any process."""

    _validate_seed(seed)
    base_path = _absolute_path(inputs.evaluation, "evaluation")
    namespace: Path | None = None
    nonce: str | None = None
    try:
        namespace, nonce = _namespace_from_evaluation(base_path, seed, namespace_root)
    except IntakeError as error:
        namespace_error = str(error)
    else:
        namespace_error = None
    result = _summary_base(seed, namespace, nonce)
    reasons: list[str] = []
    if namespace_error:
        reasons.append(namespace_error)
    sources: dict[str, Any] = {}
    result["sources"] = sources
    if training_source is not None:
        sources["training_matrix"] = dict(training_source)
    else:
        sources["training_matrix"] = _source_missing(None, "training_matrix")
    process_missing = inputs.process_exit_proof is None
    process_untrusted = False
    if inputs.process_exit_proof is not None:
        try:
            process_info = os.lstat(inputs.process_exit_proof)
            # A nonexistent path is missing evidence.  A present symlink,
            # directory, or hardlink remains an invalid supplied proof and is
            # therefore reported as a generic fail-closed input violation.
            process_missing = False
        except FileNotFoundError:
            process_missing = True
        except OSError:
            process_missing = False
        process_untrusted = inputs.trusted_process_proof_sha256 is None
    if inputs.process_exit_proof is not None:
        sources["process_exit_proof"] = _source_missing(inputs.process_exit_proof, "process_exit_proof")
    else:
        sources["process_exit_proof"] = _source_missing(None, "process_exit_proof")

    training_row: dict[str, Any] | None = None
    history_row: dict[str, Any] | None = None
    evaluation_identity: dict[str, Any] | None = None
    trajectory_identity: dict[str, Any] | None = None
    validator_source: dict[str, Any] | None = None
    validator_payload: Mapping[str, Any] | None = None
    process_payload: Mapping[str, Any] | None = None

    try:
        training_row = _validate_training_matrix(training_payload, seed, "training_matrix")
        result["checks"]["training_matrix"] = True
    except (IntakeError, OSError, RecursionError) as error:
        reasons.append(_failure_text("training_matrix", error))
        result["checks"]["training_matrix"] = False

    try:
        history_payload, history_source = _bounded_json(inputs.history_summary, root=root, name="history_summary")
        sources["history_summary"] = history_source
        history_row = _validate_history(history_payload, seed, "history_summary")
        result["checks"]["history_summary"] = True
    except (IntakeError, OSError, RecursionError) as error:
        reasons.append(_failure_text("history_summary", error))
        sources.setdefault("history_summary", _source_missing(inputs.history_summary, "history_summary"))
        result["checks"]["history_summary"] = False

    try:
        evaluation_path = _absolute_path(inputs.evaluation, "evaluation")
        if namespace is None or nonce is None:
            _fail("cannot stream evaluation before canonical namespace validation")
        evaluation_payload, evaluation_source = _stream_evaluation(evaluation_path, root=root, name="evaluation")
        sources["evaluation"] = evaluation_source
        result["input_boundary"]["evaluation_stream_hashed"] = True
        _validate_evaluation(evaluation_payload, seed, "evaluation")
        evaluation_identity = dict(evaluation_source)
        result["checks"]["evaluation_terminal"] = True
    except (IntakeError, OSError, RecursionError) as error:
        reasons.append(_failure_text("evaluation", error))
        sources.setdefault("evaluation", _source_missing(inputs.evaluation, "evaluation"))
        result["checks"]["evaluation_terminal"] = False

    try:
        if namespace is None or nonce is None:
            _fail("cannot validate trajectory metadata without canonical namespace")
        trajectory_payload, trajectory_source = _bounded_json(inputs.trajectory_metadata, root=root, name="trajectory_metadata")
        sources["trajectory_metadata"] = trajectory_source
        trajectory_identity = _validate_trajectory_metadata(trajectory_payload, seed, namespace, nonce, root=root)
        result["checks"]["trajectory_metadata"] = True
    except (IntakeError, OSError, RecursionError) as error:
        reasons.append(_failure_text("trajectory_metadata", error))
        sources.setdefault("trajectory_metadata", _source_missing(inputs.trajectory_metadata, "trajectory_metadata"))
        result["checks"]["trajectory_metadata"] = False

    try:
        if namespace is None or trajectory_identity is None or evaluation_identity is None:
            _fail("validator requires valid evaluation and trajectory identities")
        validator_path = _absolute_path(inputs.validator, "validator")
        expected_validator = Path(str(namespace) + "-hdf5-validation.json")
        if validator_path != expected_validator:
            _fail("validator path is not the canonical fresh namespace")
        validator_payload, validator_source = _bounded_json(validator_path, root=root, name="validator")
        sources["validator"] = validator_source
        _validate_validator(validator_payload, seed, namespace, trajectory_identity, evaluation_identity, str(validator_path))
        result["checks"]["validator"] = True
    except (IntakeError, OSError, RecursionError) as error:
        reasons.append(_failure_text("validator", error))
        sources.setdefault("validator", _source_missing(inputs.validator, "validator"))
        result["checks"]["validator"] = False

    if training_row is not None and history_row is not None:
        # The real training-evidence matrix v1 records checkpoint path/schema/
        # sha256/update but omits checkpoint bytes.  Complete that intermediate
        # identity only from the independently supplied history checkpoint after
        # its canonical path and SHA have already been validated.  A missing or
        # divergent history tuple therefore remains fail-closed.
        training_checkpoint = training_row["checkpoint"]
        history_checkpoint = history_row["checkpoint"]
        identity_ok = True
        if training_checkpoint["bytes"] is None:
            if (
                training_checkpoint["path"] != history_checkpoint["path"]
                or training_checkpoint["sha256"] != history_checkpoint["sha256"]
            ):
                reasons.append("fail-closed: training matrix/history checkpoint identity drift")
                identity_ok = False
            else:
                training_row = dict(training_row)
                training_row["checkpoint"] = {
                    **training_checkpoint,
                    "bytes": history_checkpoint["bytes"],
                }
        if training_row["checkpoint"] != history_checkpoint:
            if identity_ok:
                reasons.append("fail-closed: training matrix/history checkpoint identity drift")
            identity_ok = False
        if training_row["manifest_sha256"] != history_row["manifest_sha256"]:
            reasons.append("fail-closed: training matrix/history manifest source drift")
            identity_ok = False
        if (
            history_row.get("training_receipt") is not None
            and training_row["training_receipt"] != history_row["training_receipt"]
        ):
            reasons.append("fail-closed: training matrix/history training receipt identity drift")
            identity_ok = False
        result["checks"]["training_history_identity"] = identity_ok
    else:
        result["checks"]["training_history_identity"] = False

    if inputs.process_exit_proof is not None:
        try:
            proof_path = _absolute_path(inputs.process_exit_proof, "process_exit_proof")
            expected_proof = _expected_process_proof_path(Path(os.path.abspath(root)), seed)
            if proof_path != expected_proof:
                _fail("process proof path is not the canonical launcher report destination")
            process_payload, process_source = _bounded_json(proof_path, root=root, name="process_exit_proof")
            sources["process_exit_proof"] = process_source
            if training_row is None or history_row is None or evaluation_identity is None or trajectory_identity is None or validator_source is None or namespace is None or nonce is None:
                _fail("process proof cannot be bound until all identity inputs validate")
            _validate_process(
                process_payload,
                seed,
                namespace,
                nonce,
                Path(os.path.abspath(root)),
                training_row,
                history_row,
                history_row["checkpoint"],
                evaluation_identity,
                trajectory_identity,
                validator_source,
                process_source,
                inputs.trusted_process_proof_sha256,
                "process_exit_proof",
            )
            result["checks"]["process_exit_proof"] = True
            result["checks"]["process_proof_trusted"] = True
        except (IntakeError, OSError, RecursionError) as error:
            reasons.append(_failure_text("process_exit_proof", error))
            result["checks"]["process_exit_proof"] = False
            result["checks"]["process_proof_trusted"] = False
    else:
        result["checks"]["process_exit_proof"] = False
        result["checks"]["process_proof_trusted"] = False
        reasons.append("fail-closed: process-exit proof is missing; progress/PID is not terminal evidence")

    if process_missing:
        status = "blocked_missing_process_proof"
    elif process_untrusted:
        status = "blocked_untrusted_process_proof"
    elif reasons:
        status = "blocked_fail_closed"
    else:
        status = "fresh_terminal_identity_bound"
    result["status"] = status
    result["source_bound"] = status == "fresh_terminal_identity_bound"
    result["blocked_reasons"] = list(dict.fromkeys(reasons))
    if result["source_bound"]:
        assert namespace is not None and nonce is not None and evaluation_identity is not None and trajectory_identity is not None and validator_source is not None and history_row is not None
        result["rollout_identity"] = {
            "namespace": str(namespace),
            "namespace_nonce": nonce,
            "evaluation": evaluation_identity,
            "trajectory": trajectory_identity,
            "validator": validator_source,
            "checkpoint": history_row["checkpoint"],
        }
    else:
        result["rollout_identity"] = None
    return result


def build_summaries(
    inputs: Mapping[int, SeedInputs],
    *,
    training_matrix: Path,
    root: Path = LAB_ROOT,
    namespace_root: Path = Path("/tmp"),
) -> dict[int, dict[str, Any]]:
    """Read the shared training matrix once and produce exactly three rows."""

    training_payload, training_source = _bounded_json(training_matrix, root=root, name="training_matrix")
    if sorted(inputs) != list(SEEDS):
        _fail(f"inputs must contain exactly seeds {SEEDS}")
    return {
        seed: build_seed_summary(
            seed,
            inputs[seed],
            training_payload=training_payload,
            training_source=training_source,
            root=root,
            namespace_root=namespace_root,
        )
        for seed in SEEDS
    }


def _parse_seed_path(values: list[str], name: str, *, optional: bool = False) -> dict[int, Path | None]:
    result: dict[int, Path | None] = {seed: None for seed in SEEDS}
    for text in values:
        if "=" not in text:
            raise argparse.ArgumentTypeError(f"{name} must use SEED=PATH")
        seed_text, path_text = text.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{name} seed is invalid") from error
        if seed not in SEEDS or result[seed] is not None:
            raise argparse.ArgumentTypeError(f"{name} contains an invalid or duplicate seed")
        if not path_text and optional:
            result[seed] = None
        else:
            result[seed] = Path(path_text)
    if not optional and any(result[seed] is None for seed in SEEDS):
        raise argparse.ArgumentTypeError(f"{name} must contain seed17/29/43")
    return result


def _parse_seed_digest(values: list[str], name: str) -> dict[int, str | None]:
    """Parse optional out-of-band proof digests without accepting ambiguity."""

    result: dict[int, str | None] = {seed: None for seed in SEEDS}
    for text in values:
        if "=" not in text:
            raise argparse.ArgumentTypeError(f"{name} must use SEED=HEX")
        seed_text, digest = text.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{name} seed is invalid") from error
        if seed not in SEEDS or result[seed] is not None:
            raise argparse.ArgumentTypeError(f"{name} contains an invalid or duplicate seed")
        if SHA_RE.fullmatch(digest) is None:
            raise argparse.ArgumentTypeError(
                f"{name} seed{seed} must be a lowercase 64-character SHA-256 digest"
            )
        result[seed] = digest
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--namespace-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--training-matrix", type=Path, required=True)
    parser.add_argument("--evaluation", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--trajectory-metadata", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--validator", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--history-summary", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--process-exit-proof", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument(
        "--trusted-process-proof-sha256",
        action="append",
        default=[],
        metavar="SEED=HEX",
        help="out-of-band trusted SHA-256 of the canonical launcher process-proof bytes",
    )
    args = parser.parse_args(argv)
    try:
        evaluations = _parse_seed_path(args.evaluation, "--evaluation")
        trajectories = _parse_seed_path(args.trajectory_metadata, "--trajectory-metadata")
        validators = _parse_seed_path(args.validator, "--validator")
        histories = _parse_seed_path(args.history_summary, "--history-summary")
        proofs = _parse_seed_path(args.process_exit_proof, "--process-exit-proof", optional=True)
        trusted_proofs = _parse_seed_digest(
            args.trusted_process_proof_sha256,
            "--trusted-process-proof-sha256",
        )
        inputs = {
            seed: SeedInputs(
                evaluation=evaluations[seed],  # type: ignore[arg-type]
                trajectory_metadata=trajectories[seed],  # type: ignore[arg-type]
                validator=validators[seed],  # type: ignore[arg-type]
                history_summary=histories[seed],  # type: ignore[arg-type]
                process_exit_proof=proofs[seed],
                trusted_process_proof_sha256=trusted_proofs[seed],
            )
            for seed in SEEDS
        }
        summaries = build_summaries(
            inputs,
            training_matrix=args.training_matrix,
            root=args.root,
            namespace_root=args.namespace_root,
        )
        output = {
            "schema": "core.f3.mlp.hidden16.fresh_terminal_intake_batch.v1",
            "status": "source_bound" if all(row["source_bound"] for row in summaries.values()) else "blocked_fail_closed",
            "source_bound": all(row["source_bound"] for row in summaries.values()),
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "credit": 0,
            "seeds": [summaries[seed] for seed in SEEDS],
            "side_effects": {"processes_started": 0, "processes_stopped": 0, "processes_restarted": 0, "registry_mutation": 0, "ledger_mutation": 0},
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0 if output["source_bound"] else 1
    except (IntakeError, OSError, RecursionError) as error:
        print(json.dumps({"schema": "core.f3.mlp.hidden16.fresh_terminal_intake_batch.v1", "status": "blocked_fail_closed", "source_bound": False, "diagnostic_only": True, "formal": False, "formal_eligible": False, "credit": 0, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
