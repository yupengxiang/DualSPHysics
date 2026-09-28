#!/usr/bin/env python3
"""Independently verify F3 graph_raw/hidden16 terminal runtime evidence.

The verifier consumes only bounded JSON receipts.  It never opens a declared
manifest, checkpoint, evaluation artifact, progress file, trajectory/HDF5, or
solver artifact.  The declared artifact identities are cross-bound as claims;
their contents are outside this verifier's input boundary.

All three seeds must provide the following independent evidence classes:

* the three-seed graph_raw hidden16 training-evidence matrix;
* the receipt-only full835 terminal completion matrix;
* one full835 rollout-identity envelope;
* one evaluator/launcher process-exit proof; and
* one independent HDF5-validator receipt.

The result is diagnostic-only and zero-credit.  It never launches, stops, or
restarts a runtime and never mutates registry, ledger, denominator, gate,
completion, PLAN, or campaign state.
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
from scripts import f3_graph_raw_hidden16_training_evidence_matrix_v1 as training_matrix


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.terminal_runtime_verifier.v1"
REPORT_ID = "f3-graph-raw-hidden16-terminal-runtime-verifier-v1"
TRAINING_MATRIX_SCHEMA = "core.f3.graph_raw.hidden16.training_evidence_matrix.v1"
TERMINAL_MATRIX_SCHEMA = "core.f3.graph_raw.hidden16.terminal_completion_receipt_matrix.v1"
PROCESS_SCHEMA = "core.f3.graph_raw.hidden16.process_exit_proof.v1"
ROLLOUT_SCHEMA = "core.f3.graph_raw.hidden16.rollout_identity.v1"
VALIDATOR_ENVELOPE_SCHEMA = "core.f3.graph_raw.hidden16.hdf5_validator_receipt.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"

SEEDS = (17, 29, 43)
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
RUN_ID_RE = re.compile(r"^graph_raw-hidden16-seed(?P<seed>17|29|43)$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 64
MAX_DECLARED_BYTES = 1 << 50
CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})

REPORT_JSON_FILENAME = "F3-GRAPH-RAW-HIDDEN16-TERMINAL-RUNTIME-VERIFIER-V1-2026-09-28.json"
REPORT_MARKDOWN_FILENAME = REPORT_JSON_FILENAME.removesuffix(".json") + ".zh-CN.md"
REPORT_OUTPUT_FILENAMES = frozenset({REPORT_JSON_FILENAME, REPORT_MARKDOWN_FILENAME})
TRAINING_MATRIX_FILENAME = "F3-GRAPH-RAW-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"
TERMINAL_MATRIX_FILENAME = "F3-GRAPH-RAW-HIDDEN16-TERMINAL-COMPLETION-RECEIPT-MATRIX-V1-2026-09-28.json"

# These are the only authority/process aliases admitted by the input schemas.
# Every other key containing one of these words is rejected recursively.
ALLOWED_AUTHORITY_KEYS = frozenset(
    {
        "formal",
        "formal_eligible",
        "formal_training_runs_counted",
        "formal_training_runs_expected",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "training_evidence_counted_as_formal_runs",
        "t1_case_runs_counted",
        "t2_macro_families_counted",
        "zero_credit_only",
        "progress_or_pid_is_not_completion",
        "manifest_formal_release",
        "validation_formal_eligible",
    }
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})
SOURCE_KEYS = frozenset({"path", "exists", "opened", "bytes", "sha256", "schema"})


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


def _sha256(value: Any, name: str) -> str:
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
    """Reject unknown formal, credit, PID, and process aliases everywhere."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if ("pid" in lowered or "process_id" in lowered) and key not in ALLOWED_AUTHORITY_KEYS:
                _fail(f"{name}.{key} is an unknown PID/process alias")
            if "formal" in lowered and key not in ALLOWED_AUTHORITY_KEYS:
                _fail(f"{name}.{key} is an unknown formal alias")
            if "credit" in lowered and key not in ALLOWED_AUTHORITY_KEYS:
                _fail(f"{name}.{key} is an unknown credit alias")
            _reject_aliases(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_aliases(item, f"{name}[{index}]")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
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
    """Read exactly one small JSON object with no-follow and TOCTOU checks."""

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
        try:
            file_fd = os.open(
                components[-1],
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
                dir_fd=parent_fd,
            )
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
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            _fail(f"{name} changed while it was being read (TOCTOU)")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            _fail(f"{name} size changed while it was being read")
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=_reject_constant,
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
        display = candidate.relative_to(Path(os.path.abspath(os.fspath(root)))).as_posix()
    except VerifierError:
        return {"path": str(value), "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
    try:
        info = os.lstat(candidate)
    except OSError:
        info = None
    return {
        "path": display,
        "exists": info is not None and stat.S_ISREG(info.st_mode),
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
    count = _strict_int(item.get("bytes"), f"{name}.bytes", 1)
    if count > MAX_DECLARED_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    return {"path": path, "sha256": _sha256(item.get("sha256"), f"{name}.sha256"), "bytes": count}


def _source_claim(value: Any, name: str, *, absolute: bool = True) -> dict[str, Any]:
    source = _mapping(value, name)
    _reject_unknown(source, SOURCE_KEYS, name)
    _check_exact(source, "exists", True, name)
    _check_exact(source, "opened", True, name)
    raw_path = _string(source.get("path"), f"{name}.path")
    if absolute:
        path = _declared_path(raw_path, f"{name}.path", ".json")
    else:
        path_obj = Path(raw_path)
        if ".." in path_obj.parts or os.path.normpath(raw_path) != raw_path:
            _fail(f"{name}.path contains unsafe traversal or normalization")
        path = raw_path
    count = _strict_int(source.get("bytes"), f"{name}.bytes", 1)
    return {"path": path, "sha256": _sha256(source.get("sha256"), f"{name}.sha256"), "bytes": count, "schema": source.get("schema")}


def _run_id(seed: int) -> str:
    return f"graph_raw-hidden16-seed{seed}"


def _namespace(seed: int, value: Any, name: str) -> tuple[str, str]:
    namespace = _declared_path(value.get("namespace"), f"{name}.namespace")
    nonce = _string(value.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name}.namespace_nonce must be a fresh lowercase 32-hex nonce")
    expected_basename = f"f3-graph-raw500-hidden16-seed{seed}-full835-nonce{nonce}"
    if Path(namespace).name != expected_basename:
        _fail(f"{name}.namespace is not the fresh canonical seed{seed} full835 namespace")
    lowered = namespace.lower()
    if any(token in lowered for token in ("legacy", "running", "partial", "progress", "old")):
        _fail(f"{name}.namespace contains an old or non-terminal marker")
    return namespace, nonce


def _projection_namespace(seed: int, projection: Mapping[str, Any], name: str) -> tuple[str, str]:
    output_namespace = _declared_path(projection.get("output_namespace"), f"{name}.output_namespace")
    match = re.fullmatch(
        rf"f3-graph-raw500-hidden16-seed{seed}-full835-nonce(?P<nonce>[0-9a-f]{{32}})",
        Path(output_namespace).name,
    )
    if match is None:
        _fail(f"{name}.output_namespace is not a fresh canonical namespace")
    nonce = match.group("nonce")
    if projection.get("namespace_nonce") is not None and projection.get("namespace_nonce") != nonce:
        _fail(f"{name}.namespace_nonce drifts from output_namespace")
    return _namespace(seed, {"namespace": output_namespace, "namespace_nonce": nonce}, name)


def _validate_shared(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    for key, expected in (
        ("seed", seed),
        ("run_id", _run_id(seed)),
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _check_exact(value, key, expected, name)
    namespace, nonce = _namespace(seed, value, name)
    checkpoint = _artifact(value.get("checkpoint"), f"{name}.checkpoint")
    expected_checkpoint = f"f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt"
    if Path(checkpoint["path"]).name != expected_checkpoint:
        _fail(f"{name}.checkpoint.path is not the canonical graph_raw hidden16 update-500 path")
    training = _artifact(value.get("training_receipt"), f"{name}.training_receipt", suffix=".json")
    expected_training = f"f3-graph-raw500-hidden16-seed{seed}-20260928-training.json"
    if Path(training["path"]).name != expected_training:
        _fail(f"{name}.training_receipt.path is not the canonical seed training receipt")
    manifest = _artifact(value.get("manifest"), f"{name}.manifest", suffix=".json")
    if "manifest" not in Path(manifest["path"]).name.lower():
        _fail(f"{name}.manifest.path must name a manifest artifact")
    trajectory = _artifact(value.get("trajectory"), f"{name}.trajectory", suffix=".h5")
    expected_trajectory = namespace + "-trajectory.h5"
    if trajectory["path"] != expected_trajectory:
        _fail(f"{name}.trajectory.path drifts from namespace")
    return {
        "seed": seed,
        "run_id": _run_id(seed),
        "namespace": namespace,
        "namespace_nonce": nonce,
        "checkpoint": checkpoint,
        "training_receipt": training,
        "manifest": manifest,
        "trajectory": trajectory,
    }


def _validate_training_matrix(value: Mapping[str, Any], name: str) -> dict[int, dict[str, Any]]:
    _reject_aliases(value, name)
    try:
        matrix_errors = training_matrix.validate_report(value)
    except Exception as error:
        _fail(f"{name} cannot be validated by the training evidence contract: {error}")
    if matrix_errors:
        _fail(f"{name} is not a valid training evidence matrix: {'; '.join(matrix_errors)}")
    for key, expected in (
        ("schema", TRAINING_MATRIX_SCHEMA),
        ("report_id", "f3-graph-raw-hidden16-training-evidence-matrix-v1"),
        ("status", "training_evidence_bound_diagnostic_only"),
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
        ("formal_training_runs_counted", 0),
        ("training_evidence_counted_as_formal_runs", 0),
        ("t1_case_runs_counted", 0),
        ("t2_macro_families_counted", 0),
        ("errors", []),
    ):
        _check_exact(value, key, expected, name)
    contract = _mapping(value.get("expected_contract"), f"{name}.expected_contract")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("seeds", list(SEEDS)),
        ("evidence_status", "complete"),
        ("checkpoint_content_opened", False),
    ):
        _check_exact(contract, key, expected, f"{name}.expected_contract")
    reference = _mapping(value.get("reference_training_matrix"), f"{name}.reference_training_matrix")
    _check_exact(reference, "opened", True, f"{name}.reference_training_matrix")
    _check_exact(reference, "schema", "core.f3.graph_raw.hidden16.training_matrix.v1", f"{name}.reference_training_matrix")
    _source_claim(reference.get("source"), f"{name}.reference_training_matrix.source", absolute=False)
    rows = value.get("runs")
    if not isinstance(rows, list) or len(rows) != len(SEEDS):
        _fail(f"{name}.runs must contain exactly three seed rows")
    normalized: dict[int, dict[str, Any]] = {}
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, f"{name}.runs[{index}]")
        seed = row.get("seed")
        if seed not in SEEDS or seed in normalized:
            _fail(f"{name}.runs has a duplicate or unknown seed")
        _check_exact(row, "status", "bound_complete", f"{name}.runs.seed{seed}")
        if row.get("blocked_reasons") not in ([], None):
            _fail(f"{name}.runs.seed{seed} has blocked reasons")
        source = _source_claim(row.get("source"), f"{name}.runs.seed{seed}.source")
        if Path(source["path"]).name != f"f3-graph-raw500-hidden16-seed{seed}-20260928-training.json":
            _fail(f"{name}.runs.seed{seed}.source.path is not canonical")
        evidence = _mapping(row.get("evidence"), f"{name}.runs.seed{seed}.evidence")
        for key, expected in (
            ("schema", "core.training.v1"),
            ("evidence_status", "complete"),
            ("model_kind", MODEL_KIND),
            ("seed", seed),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("run_id", _run_id(seed)),
            ("formal_eligible", False),
            ("qualification_credit", 0),
        ):
            _check_exact(evidence, key, expected, f"{name}.runs.seed{seed}.evidence")
        manifest_sha = _sha256(evidence.get("manifest_sha256"), f"{name}.runs.seed{seed}.evidence.manifest_sha256")
        checkpoint = _mapping(evidence.get("checkpoint"), f"{name}.runs.seed{seed}.evidence.checkpoint")
        _check_exact(checkpoint, "schema", "core.checkpoint.v1", f"{name}.runs.seed{seed}.evidence.checkpoint")
        _check_exact(checkpoint, "update", UPDATES, f"{name}.runs.seed{seed}.evidence.checkpoint")
        checkpoint_path = _declared_path(checkpoint.get("path"), f"{name}.runs.seed{seed}.evidence.checkpoint.path")
        if Path(checkpoint_path).name != f"f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt":
            _fail(f"{name}.runs.seed{seed}.evidence.checkpoint.path is not canonical")
        normalized[seed] = {
            "seed": seed,
            "run_id": _run_id(seed),
            "manifest_sha256": manifest_sha,
            "training_receipt": source,
            "checkpoint": {
                "path": checkpoint_path,
                "sha256": _sha256(checkpoint.get("sha256"), f"{name}.runs.seed{seed}.evidence.checkpoint.sha256"),
            },
        }
    if set(normalized) != set(SEEDS):
        _fail(f"{name}.runs seed set is incomplete")
    if len({row["training_receipt"]["path"] for row in normalized.values()}) != len(SEEDS):
        _fail(f"{name} reuses a training receipt path")
    if len({row["checkpoint"]["path"] for row in normalized.values()}) != len(SEEDS):
        _fail(f"{name} reuses a checkpoint path")
    manifest_shas = {row["manifest_sha256"] for row in normalized.values()}
    if len(manifest_shas) != 1:
        _fail(f"{name} has drifted manifest SHA claims")
    return normalized


def _projection_artifact(projection: Mapping[str, Any], key: str, name: str, *, suffix: str | None = None, require_sha: bool = True) -> dict[str, Any]:
    item = _mapping(projection.get(key), f"{name}.{key}")
    path = _declared_path(item.get("path"), f"{name}.{key}.path", suffix)
    count = _strict_int(item.get("bytes"), f"{name}.{key}.bytes", 1)
    result = {"path": path, "bytes": count, "sha256": None}
    if item.get("sha256") is not None:
        result["sha256"] = _sha256(item.get("sha256"), f"{name}.{key}.sha256")
    elif require_sha:
        _fail(f"{name}.{key}.sha256 is missing")
    return result


def _validate_terminal_matrix(value: Mapping[str, Any], name: str) -> dict[int, dict[str, Any]]:
    _reject_aliases(value, name)
    for key, expected in (
        ("schema", TERMINAL_MATRIX_SCHEMA),
        ("report_id", "f3-graph-raw-hidden16-terminal-completion-receipt-matrix-v1"),
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
    contract = _mapping(value.get("expected_contract"), f"{name}.expected_contract")
    for key, expected in (
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
        _check_exact(contract, key, expected, f"{name}.expected_contract")
    rows = value.get("seed_matrix")
    if not isinstance(rows, list) or len(rows) != len(SEEDS):
        _fail(f"{name}.seed_matrix must contain exactly three rows")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(item, Mapping) or item.get("passed") is not True for item in checks):
        _fail(f"{name}.checks must contain only passed checks")
    if value.get("blocked_reasons") not in ([], None):
        _fail(f"{name}.blocked_reasons must be empty for a bound matrix")
    result: dict[int, dict[str, Any]] = {}
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, f"{name}.seed_matrix[{index}]")
        seed = row.get("seed")
        if seed not in SEEDS or seed in result:
            _fail(f"{name}.seed_matrix has a duplicate or unknown seed")
        _check_exact(row, "status", "bound_terminal_diagnostic", f"{name}.seed_matrix.seed{seed}")
        if row.get("blocked_reasons") not in ([], None):
            _fail(f"{name}.seed_matrix.seed{seed} has blocked reasons")
        projection = _mapping(row.get("projection"), f"{name}.seed_matrix.seed{seed}.projection")
        for key, expected in (
            ("seed", seed),
            ("model_kind", MODEL_KIND),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("case_id", CASE_ID),
            ("split", SPLIT),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
            ("diagnostic_only", True),
            ("formal_eligible", False),
            ("qualification_credit", 0),
            ("credit", 0),
        ):
            _check_exact(projection, key, expected, f"{name}.seed_matrix.seed{seed}.projection")
        namespace, nonce = _projection_namespace(seed, projection, f"{name}.seed_matrix.seed{seed}.projection")
        checkpoint = _projection_artifact(projection, "checkpoint", f"{name}.seed_matrix.seed{seed}.projection")
        _check_exact(_mapping(projection["checkpoint"], "checkpoint"), "update", UPDATES, f"{name}.seed_matrix.seed{seed}.projection.checkpoint")
        training = _projection_artifact(projection, "training", f"{name}.seed_matrix.seed{seed}.projection", suffix=".json")
        evaluation = _projection_artifact(projection, "evaluation", f"{name}.seed_matrix.seed{seed}.projection", suffix=".json")
        trajectory = _projection_artifact(projection, "trajectory", f"{name}.seed_matrix.seed{seed}.projection", suffix=".h5", require_sha=False)
        if Path(checkpoint["path"]).name != f"f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt":
            _fail(f"{name}.seed_matrix.seed{seed}.checkpoint path drift")
        if Path(training["path"]).name != f"f3-graph-raw500-hidden16-seed{seed}-20260928-training.json":
            _fail(f"{name}.seed_matrix.seed{seed}.training path drift")
        if evaluation["path"] != namespace + "-evaluation.json":
            _fail(f"{name}.seed_matrix.seed{seed}.evaluation path drifts from namespace")
        if trajectory["path"] != namespace + "-trajectory.h5":
            _fail(f"{name}.seed_matrix.seed{seed}.trajectory path drifts from namespace")
        markers = _mapping(projection.get("terminal_markers"), f"{name}.seed_matrix.seed{seed}.projection.terminal_markers")
        for key, expected in (("terminal", True), ("execution_complete", True), ("finite_rollout_complete", True), ("terminal_status", "completed")):
            _check_exact(markers, key, expected, f"{name}.seed_matrix.seed{seed}.projection.terminal_markers")
        validator = _mapping(projection.get("validator"), f"{name}.seed_matrix.seed{seed}.projection.validator")
        for key, expected in (("passed", True), ("complete", True), ("trajectory_transitions", TRANSITIONS), ("trajectory_frames", FRAMES)):
            _check_exact(validator, key, expected, f"{name}.seed_matrix.seed{seed}.projection.validator")
        result[seed] = {
            "seed": seed,
            "run_id": _run_id(seed),
            "namespace": namespace,
            "namespace_nonce": nonce,
            "checkpoint": checkpoint,
            "training_receipt": training,
            "evaluation_artifact": evaluation,
            "trajectory": trajectory,
        }
    if len({item["namespace"] for item in result.values()}) != len(SEEDS) or len({item["namespace_nonce"] for item in result.values()}) != len(SEEDS):
        _fail(f"{name} reuses a full835 namespace or nonce")
    return result


COMMON_ENVELOPE_KEYS = frozenset(
    {
        "source_bound", "diagnostic_only", "formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification", "qualification_credit", "credit",
        "seed", "run_id", "namespace", "namespace_nonce", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames",
        "manifest", "training_receipt", "checkpoint", "trajectory",
    }
)


def _envelope(value: Mapping[str, Any], seed: int, name: str, allowed: frozenset[str]) -> dict[str, Any]:
    _reject_aliases(value, name)
    _reject_unknown(value, allowed, name)
    _zero_credit(value, name)
    shared = _validate_shared(value, seed, name)
    return shared


def _validate_rollout(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({"schema", "report_id", "status", "evaluation_artifact", "terminal_markers"})
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.rollout_identity.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-full835-rollout-identity-v1", name)
    _check_exact(value, "status", "completed_diagnostic", name)
    evaluation = _artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", suffix=".json")
    if evaluation["path"] != shared["namespace"] + "-evaluation.json":
        _fail(f"{name}.evaluation_artifact.path drifts from namespace")
    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    for key, expected in (("terminal", True), ("execution_complete", True), ("finite_rollout_complete", True), ("terminal_status", "completed"), ("future_state_inputs", False)):
        _check_exact(markers, key, expected, f"{name}.terminal_markers")
    return {**shared, "evaluation_artifact": evaluation}


def _validate_process(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({"schema", "report_id", "status", "evaluator_alive", "launcher_alive", "evaluator_returncode", "launcher_returncode", "returncode"})
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.process_exit_proof.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-process-exit-proof-v1", name)
    _check_exact(value, "status", "exited_successfully", name)
    for key, expected in (("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0)):
        _check_exact(value, key, expected, name)
    return shared


def _validate_validator(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({"schema", "report_id", "status", "validator_schema", "passed", "complete", "expected_transitions", "frames_executed", "trajectory_transitions", "trajectory_frames", "tail_frame_count", "production_artifacts_touched", "actual_future_state_inputs", "synthetic_only"})
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.hdf5_validator_receipt.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-hdf5-validator-receipt-v1", name)
    _check_exact(value, "status", "validated", name)
    _check_exact(value, "validator_schema", VALIDATOR_SCHEMA, name)
    for key, expected in (("passed", True), ("complete", True), ("expected_transitions", TRANSITIONS), ("frames_executed", FRAMES), ("trajectory_transitions", TRANSITIONS), ("trajectory_frames", FRAMES), ("tail_frame_count", 0), ("production_artifacts_touched", False), ("actual_future_state_inputs", False), ("synthetic_only", False)):
        _check_exact(value, key, expected, name)
    return shared


def _artifact_equal(left: Mapping[str, Any], right: Mapping[str, Any], name: str, *, allow_missing_sha: bool = False) -> None:
    for key in ("path", "bytes"):
        if left.get(key) != right.get(key):
            _fail(f"{name}.{key} drifts across evidence envelopes")
    if left.get("sha256") != right.get("sha256"):
        if not (allow_missing_sha and (left.get("sha256") is None or right.get("sha256") is None)):
            _fail(f"{name}.sha256 drifts across evidence envelopes")


def _cross_bind(seed: int, training: Mapping[str, Any], terminal: Mapping[str, Any], rollout: Mapping[str, Any], process: Mapping[str, Any], validator: Mapping[str, Any]) -> None:
    name = f"seed{seed} cross-binding"
    for source_name, source in (("terminal", terminal), ("rollout", rollout), ("process", process), ("validator", validator)):
        if source["seed"] != seed or source["run_id"] != _run_id(seed):
            _fail(f"{name}: {source_name} seed/run identity drifts")
        if source["namespace"] != terminal["namespace"] or source["namespace_nonce"] != terminal["namespace_nonce"]:
            _fail(f"{name}: {source_name} namespace/nonce drifts")
    if terminal["checkpoint"]["path"] != training["checkpoint"]["path"] or terminal["checkpoint"]["sha256"] != training["checkpoint"]["sha256"]:
        _fail(f"{name}: checkpoint path/SHA drifts from training matrix")
    if terminal["training_receipt"]["path"] != training["training_receipt"]["path"] or terminal["training_receipt"]["sha256"] != training["training_receipt"]["sha256"] or terminal["training_receipt"]["bytes"] != training["training_receipt"]["bytes"]:
        _fail(f"{name}: training receipt path/SHA/bytes drifts from training matrix")
    if terminal["checkpoint"]["path"] != rollout["checkpoint"]["path"]:
        _fail(f"{name}: terminal checkpoint path differs from rollout identity")
    for source_name, source in (("rollout", rollout), ("process", process), ("validator", validator)):
        for artifact_name in ("checkpoint", "training_receipt", "manifest", "trajectory"):
            _artifact_equal(source[artifact_name], rollout[artifact_name], f"{name}.{source_name}.{artifact_name}")
    _artifact_equal(terminal["checkpoint"], rollout["checkpoint"], f"{name}.terminal.checkpoint")
    _artifact_equal(terminal["trajectory"], rollout["trajectory"], f"{name}.terminal.trajectory", allow_missing_sha=True)
    _artifact_equal(terminal["evaluation_artifact"], rollout["evaluation_artifact"], f"{name}.evaluation_artifact")
    if rollout["manifest"]["sha256"] != training["manifest_sha256"]:
        _fail(f"{name}: manifest SHA drifts from training matrix")


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _empty_side_effects() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "matrix_json_opened": False,
        "training_matrix_json_opened": False,
        "rollout_identity_json_opened": False,
        "process_json_opened": False,
        "validator_json_opened": False,
        "manifest_opened": False,
        "checkpoint_opened": False,
        "evaluation_opened": False,
        "progress_opened": False,
        "trajectory_opened": False,
        "hdf5_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
        "queue_submissions": 0,
    }


def _empty_input_boundary() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "manifest_content_opened": False,
        "checkpoint_content_opened": False,
        "evaluation_content_opened": False,
        "progress_content_opened": False,
        "trajectory_content_opened": False,
        "hdf5_content_opened": False,
        "runtime_started": False,
        "queue_submissions": 0,
    }


def _row(seed: int) -> dict[str, Any]:
    return {"seed": seed, "status": "missing", "blocked_reasons": [], "sources": {}, "evidence": None}


def _read_optional(root: Path, path: Path | str | None, name: str) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    if path is None:
        return None, _source_metadata(root, None), f"{name} is not configured"
    try:
        payload, source = _read_bounded_json(root, path, name)
        return payload, source, None
    except (VerifierError, OSError, ValueError, TypeError, RecursionError) as error:
        return None, _source_metadata(root, path), f"{name}: {error}"


def _evaluate(
    training_payload: Mapping[str, Any] | None,
    training_source: Mapping[str, Any],
    terminal_payload: Mapping[str, Any] | None,
    terminal_source: Mapping[str, Any],
    rollout_payloads: Mapping[int, Mapping[str, Any]],
    rollout_sources: Mapping[int, Mapping[str, Any]],
    process_payloads: Mapping[int, Mapping[str, Any]],
    process_sources: Mapping[int, Mapping[str, Any]],
    validator_payloads: Mapping[int, Mapping[str, Any]],
    validator_sources: Mapping[int, Mapping[str, Any]],
    errors: list[str],
    observed_at_utc: str,
) -> dict[str, Any]:
    rows = [_row(seed) for seed in SEEDS]
    training_rows: dict[int, dict[str, Any]] = {}
    terminal_rows: dict[int, dict[str, Any]] = {}
    training_bound = False
    terminal_bound = False
    try:
        if training_payload is None:
            _fail("training evidence matrix is missing")
        training_rows = _validate_training_matrix(training_payload, "training evidence matrix")
        training_bound = True
    except (VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    try:
        if terminal_payload is None:
            _fail("terminal completion receipt matrix is missing")
        terminal_rows = _validate_terminal_matrix(terminal_payload, "terminal completion receipt matrix")
        terminal_bound = True
    except (VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    for row in rows:
        seed = row["seed"]
        row["sources"] = {
            "rollout_identity": rollout_sources.get(seed),
            "process_exit_proof": process_sources.get(seed),
            "validator_receipt": validator_sources.get(seed),
        }
        if not training_bound:
            row["blocked_reasons"].append("three-seed training evidence matrix is not bound")
        if not terminal_bound or seed not in terminal_rows:
            row["blocked_reasons"].append("full835 terminal completion matrix is not bound for this seed")
            continue
        try:
            rollout = _validate_rollout(rollout_payloads[seed], seed, f"seed{seed} rollout_identity")
            process = _validate_process(process_payloads[seed], seed, f"seed{seed} process_exit_proof")
            validator = _validate_validator(validator_payloads[seed], seed, f"seed{seed} validator_receipt")
            _cross_bind(seed, training_rows[seed], terminal_rows[seed], rollout, process, validator)
        except KeyError as error:
            row["blocked_reasons"].append(f"seed{seed} missing required evidence envelope: {error}")
        except (VerifierError, TypeError, RecursionError) as error:
            row["blocked_reasons"].append(str(error))
        else:
            row["status"] = "independently_verified"
            row["evidence"] = {"rollout_identity": rollout, "process_exit_proof": process, "validator_receipt": validator}
    all_verified = all(row["status"] == "independently_verified" for row in rows)
    if not training_bound:
        errors.append("three-seed training evidence matrix is missing, invalid, or not source-bound")
    if not terminal_bound:
        errors.append("full835 terminal completion matrix is missing, invalid, or not source-bound")
    for row in rows:
        errors.extend(row["blocked_reasons"])
    errors = list(dict.fromkeys(errors))
    verified = training_bound and terminal_bound and all_verified and not errors
    checks = [
        _check("three_seed_training_matrix", training_bound, "the graph_raw hidden16 training matrix binds seeds 17, 29, and 43"),
        _check("full835_terminal_completion_matrix", terminal_bound, "the receipt-only graph_raw full835 matrix is source-bound"),
        _check("rollout_identity_envelopes", all(row["status"] == "independently_verified" or row["sources"].get("rollout_identity", {}).get("exists") is True for row in rows), "all seeds have bounded full835 rollout identities"),
        _check("process_exit_proofs", all(row["status"] == "independently_verified" or row["sources"].get("process_exit_proof", {}).get("exists") is True for row in rows), "all seeds have closed evaluator/launcher exit proofs"),
        _check("independent_hdf5_validator_receipts", all(row["status"] == "independently_verified" or row["sources"].get("validator_receipt", {}).get("exists") is True for row in rows), "all seeds have independent HDF5 validator receipts"),
        _check("cross_file_path_sha_bytes_identity", all_verified, "run, nonce, manifest, training, checkpoint, evaluation, and trajectory identities agree"),
        _check("terminal_835_transitions_836_frames", all_verified, "every seed is terminal at exactly 835 transitions and 836 frames"),
        _check("terminal_zero_credit_boundary", all_verified, "formal/T1/T2/qualification are false and credit is zero"),
    ]
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "independently_terminal_verified" if verified else "blocked_fail_closed",
        "fail_closed": not verified,
        "receipt_bound": training_bound and terminal_bound,
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
            "required_evidence_classes": ["training_matrix", "terminal_matrix", "rollout_identity", "process_exit_proof", "hdf5_validator_receipt"],
            "fresh_32_hex_nonce": True,
            "declared_artifacts_are_not_opened": True,
            "zero_credit_only": True,
        },
        "training_matrix_source": dict(training_source),
        "terminal_matrix_source": dict(terminal_source),
        "seed_matrix": rows,
        "checks": checks,
        "blocked_reasons": errors,
        "side_effects": _empty_side_effects(),
        "input_boundary": _empty_input_boundary(),
        "interpretation": (
            "This additive verifier consumes bounded JSON receipts only. It never opens "
            "manifest, checkpoint, evaluation, progress, trajectory/HDF5, solver, or "
            "runtime artifacts and never starts/stops/restarts an evaluator. A positive "
            "result remains diagnostic-only and contributes zero formal/T1/T2 credit."
        ),
        "observed_at_utc": _string(observed_at_utc, "observed_at_utc"),
    }


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    training_matrix_path: Path | str | None = None,
    terminal_matrix_path: Path | str | None = None,
    rollout_paths: Mapping[int, Path | str | None] | None = None,
    process_paths: Mapping[int, Path | str | None] | None = None,
    validator_paths: Mapping[int, Path | str | None] | None = None,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
) -> dict[str, Any]:
    root = Path(os.path.abspath(os.fspath(lab_root)))
    training_matrix_path = training_matrix_path or root / "reports" / TRAINING_MATRIX_FILENAME
    terminal_matrix_path = terminal_matrix_path or root / "reports" / TERMINAL_MATRIX_FILENAME
    rollout_paths = dict(rollout_paths or {
        seed: root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-FULL835-ROLLOUT-IDENTITY-V1-2026-09-28.json" for seed in SEEDS
    })
    process_paths = dict(process_paths or {
        seed: root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json" for seed in SEEDS
    })
    validator_paths = dict(validator_paths or {
        seed: root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-HDF5-VALIDATOR-RECEIPT-V1-2026-09-28.json" for seed in SEEDS
    })
    errors: list[str] = []
    training, training_source, error = _read_optional(root, training_matrix_path, "training evidence matrix")
    if error:
        errors.append(error)
    terminal, terminal_source, error = _read_optional(root, terminal_matrix_path, "terminal completion matrix")
    if error:
        errors.append(error)
    rollout_payloads: dict[int, Mapping[str, Any]] = {}
    rollout_sources: dict[int, dict[str, Any]] = {}
    process_payloads: dict[int, Mapping[str, Any]] = {}
    process_sources: dict[int, dict[str, Any]] = {}
    validator_payloads: dict[int, Mapping[str, Any]] = {}
    validator_sources: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        payload, source, error = _read_optional(root, rollout_paths.get(seed), f"seed{seed} rollout_identity")
        rollout_sources[seed] = source
        if payload is not None:
            rollout_payloads[seed] = payload
        if error:
            errors.append(error)
        payload, source, error = _read_optional(root, process_paths.get(seed), f"seed{seed} process_exit_proof")
        process_sources[seed] = source
        if payload is not None:
            process_payloads[seed] = payload
        if error:
            errors.append(error)
        payload, source, error = _read_optional(root, validator_paths.get(seed), f"seed{seed} validator_receipt")
        validator_sources[seed] = source
        if payload is not None:
            validator_payloads[seed] = payload
        if error:
            errors.append(error)
    return _evaluate(
        training,
        training_source,
        terminal,
        terminal_source,
        rollout_payloads,
        rollout_sources,
        process_payloads,
        process_sources,
        validator_payloads,
        validator_sources,
        errors,
        observed_at_utc,
    )


REPORT_TOP_LEVEL_KEYS = frozenset(
    {
        "schema", "report_id", "status", "fail_closed", "receipt_bound", "independently_terminal_verified", "source_bound", "diagnostic_only", "formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification", "qualification_credit", "credit", "expected_contract", "training_matrix_source", "terminal_matrix_source", "seed_matrix", "checks", "blocked_reasons", "side_effects", "input_boundary", "interpretation", "observed_at_utc",
    }
)


def _validate_source_metadata(value: Any, name: str) -> None:
    item = _mapping(value, name)
    _reject_unknown(item, SOURCE_KEYS, name)
    _string(item.get("path"), f"{name}.path") if item.get("path") is not None else None
    if type(item.get("exists")) is not bool or type(item.get("opened")) is not bool:
        _fail(f"{name}.exists/opened must be booleans")
    if item.get("bytes") is not None:
        _strict_int(item.get("bytes"), f"{name}.bytes", 0)
    if item.get("sha256") is not None:
        _sha256(item.get("sha256"), f"{name}.sha256")


def _validate_side_effects(value: Any) -> None:
    expected = _empty_side_effects()
    item = _mapping(value, "report.side_effects")
    _reject_unknown(item, set(expected), "report.side_effects")
    for key, claim in expected.items():
        _check_exact(item, key, claim, "report.side_effects")


def _validate_input_boundary(value: Any) -> None:
    expected = _empty_input_boundary()
    item = _mapping(value, "report.input_boundary")
    _reject_unknown(item, set(expected), "report.input_boundary")
    for key, claim in expected.items():
        _check_exact(item, key, claim, "report.input_boundary")


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
        for key, expected in (("diagnostic_only", True), ("formal", False), ("formal_eligible", False), ("T1_numerical", False), ("T2_macro", False), ("T2_path", False), ("qualification", False), ("qualification_credit", 0), ("credit", 0), ("fail_closed", not source_bound), ("independently_terminal_verified", source_bound), ("receipt_bound", report.get("receipt_bound"))):
            if key == "receipt_bound":
                if type(report.get(key)) is not bool:
                    _fail("report.receipt_bound must be boolean")
            else:
                _check_exact(report, key, expected, "report")
        _check_exact(report, "status", "independently_terminal_verified" if source_bound else "blocked_fail_closed", "report")
        contract = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, expected in (("model_kind", MODEL_KIND), ("hidden", HIDDEN), ("updates", UPDATES), ("seeds", list(SEEDS)), ("case_id", CASE_ID), ("split", SPLIT), ("transitions", TRANSITIONS), ("frames", FRAMES), ("fresh_32_hex_nonce", True), ("declared_artifacts_are_not_opened", True), ("zero_credit_only", True)):
            _check_exact(contract, key, expected, "report.expected_contract")
        _validate_source_metadata(report.get("training_matrix_source"), "report.training_matrix_source")
        _validate_source_metadata(report.get("terminal_matrix_source"), "report.terminal_matrix_source")
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
            _fail("report.seed_matrix must contain seeds 17, 29, and 43 in order")
        row_keys = frozenset({"seed", "status", "blocked_reasons", "sources", "evidence"})
        source_names = frozenset({"rollout_identity", "process_exit_proof", "validator_receipt"})
        for row_value in rows:
            row = _mapping(row_value, "report.seed_matrix row")
            _reject_unknown(row, row_keys, "report.seed_matrix row")
            if row.get("status") not in {"missing", "independently_verified"}:
                _fail("report.seed_matrix row has an invalid status")
            reasons = row.get("blocked_reasons")
            if not isinstance(reasons, list) or (row.get("status") == "missing" and not reasons):
                _fail("report.seed_matrix row blocker shape is invalid")
            sources = _mapping(row.get("sources"), "report.seed_matrix.sources")
            _reject_unknown(sources, source_names, "report.seed_matrix.sources")
            for source_name in source_names:
                _validate_source_metadata(sources.get(source_name), f"report.seed_matrix.sources.{source_name}")
            if row.get("status") == "independently_verified":
                evidence = _mapping(row.get("evidence"), "report.seed_matrix.evidence")
                _reject_unknown(evidence, source_names, "report.seed_matrix.evidence")
            elif row.get("evidence") is not None:
                _fail("blocked row must not carry evidence")
        checks = report.get("checks")
        expected_checks = ["three_seed_training_matrix", "full835_terminal_completion_matrix", "rollout_identity_envelopes", "process_exit_proofs", "independent_hdf5_validator_receipts", "cross_file_path_sha_bytes_identity", "terminal_835_transitions_836_frames", "terminal_zero_credit_boundary"]
        if not isinstance(checks, list) or [item.get("check") for item in checks if isinstance(item, Mapping)] != expected_checks:
            _fail("report.checks have an unexpected identity")
        if any(not isinstance(item, Mapping) or type(item.get("passed")) is not bool for item in checks):
            _fail("report.checks must contain boolean pass flags")
        if source_bound and any(item.get("passed") is not True for item in checks):
            _fail("verified report checks must all pass")
        blocked = report.get("blocked_reasons")
        if not isinstance(blocked, list) or (not source_bound and not blocked):
            _fail("report.blocked_reasons must be a non-empty list when blocked")
        _validate_side_effects(report.get("side_effects"))
        _validate_input_boundary(report.get("input_boundary"))
        _string(report.get("observed_at_utc"), "report.observed_at_utc")
    except (VerifierError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def _report_output_path(root: Path, output: Path | str, name: str) -> tuple[Path, tuple[str, ...]]:
    candidate, components = _lexical_path(root, output, name)
    if len(components) != 2 or components[0] != "reports" or candidate.name not in REPORT_OUTPUT_FILENAMES:
        _fail(f"{name} must be one of the fixed report destinations below reports")
    return candidate, components


def _write_fixed(report: Mapping[str, Any], output: Path | str, *, root: Path | str, markdown: bool) -> None:
    root_path = Path(os.path.abspath(os.fspath(root)))
    _candidate, components = _report_output_path(root_path, output, "report output")
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
        if existing is not None and (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            _fail("report output must be an unlinked regular file")
        raw_text = render_zh_cn(report) if markdown else canonical_json(report) + "\n"
        raw = raw_text.encode("utf-8")
        if len(raw) > MAX_JSON_BYTES:
            _fail("report output exceeds bounded limit")
        for _ in range(16):
            temporary_name = f".{components[-1]}.{secrets.token_hex(12)}.tmp"
            try:
                fd = os.open(temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | nofollow, 0o644, dir_fd=parent_fd)
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


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> None:
    errors = validate_report(report)
    if errors:
        raise VerifierError("refusing to write invalid report: " + "; ".join(errors))
    _write_fixed(report, output, root=root, markdown=False)


def render_zh_cn(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 terminal runtime verifier V1",
        "",
        f"- 状态：`{report.get('status')}`；source-bound：`{report.get('source_bound')}`；fail-closed：`{report.get('fail_closed')}`。",
        "- 输入：仅读取 bounded JSON receipt；不打开 manifest、checkpoint、evaluation、progress、trajectory/HDF5，也不启动、停止或重启 evaluator。",
        "- Contract：三 seed training matrix + terminal completion matrix + full835 rollout identity + evaluator/launcher exit proof + independent HDF5 validator receipt。",
        "- 绑定：graph_raw / hidden16 / 500 updates / F3_DEV_00_a0p903125 / test / 835 transitions / 836 frames / fresh 32-hex nonce；formal、T1、T2、qualification、credit 均为零授权。",
        "",
        "| seed | 状态 | blocker |",
        "|---:|---|---|",
    ]
    for row in report.get("seed_matrix", []):
        blockers = "; ".join(row.get("blocked_reasons", [])) or "—"
        lines.append(f"| {row.get('seed')} | `{row.get('status')}` | {blockers} |")
    lines.extend(["", "该报告是独立 runtime evidence verifier 的诊断性结果，不改变任何 registry、ledger、分母、gate 或 PLAN 状态。", ""])
    return "\n".join(lines)


def write_markdown(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> None:
    errors = validate_report(report)
    if errors:
        raise VerifierError("refusing to write invalid report: " + "; ".join(errors))
    _write_fixed(report, output, root=root, markdown=True)


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
    parser.add_argument("--training-matrix", type=Path, default=None)
    parser.add_argument("--terminal-matrix", type=Path, default=None)
    parser.add_argument("--rollout-identity", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--process-exit-proof", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--validator-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--observed-at-utc", default="2026-09-28T00:00:00Z")
    args = parser.parse_args(argv)
    rollout_paths = {seed: args.root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-FULL835-ROLLOUT-IDENTITY-V1-2026-09-28.json" for seed in SEEDS}
    rollout_paths.update(_parse_seed_paths(args.rollout_identity, "--rollout-identity"))
    process_paths = {seed: args.root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json" for seed in SEEDS}
    process_paths.update(_parse_seed_paths(args.process_exit_proof, "--process-exit-proof"))
    validator_paths = {seed: args.root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-HDF5-VALIDATOR-RECEIPT-V1-2026-09-28.json" for seed in SEEDS}
    validator_paths.update(_parse_seed_paths(args.validator_receipt, "--validator-receipt"))
    report = build_report(args.root, training_matrix_path=args.training_matrix, terminal_matrix_path=args.terminal_matrix, rollout_paths=rollout_paths, process_paths=process_paths, validator_paths=validator_paths, observed_at_utc=args.observed_at_utc)
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    output = args.output or args.root / "reports" / REPORT_JSON_FILENAME
    markdown_output = args.markdown_output or args.root / "reports" / REPORT_MARKDOWN_FILENAME
    write_report(report, output, root=args.root)
    write_markdown(report, markdown_output, root=args.root)
    print(canonical_json(report))
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
