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
EVALUATION_IDENTITY_SCHEMA = "core.f3.graph_raw.hidden16.evaluation_identity.v1"
PROCESS_PRODUCER_SCHEMA = "core.f3.graph_raw.hidden16.process_proof_producer.v1"
PROCESS_PRODUCER_ID = "f3-graph-raw-hidden16-diagnostic-runtime-proof-v1"
PROCESS_ATTESTATION_SCHEMA = "core.f3.graph_raw.hidden16.exit_attestation.v1"
SCHEDULER_ATTESTATION_SCHEMA = "core.f3.graph_raw.hidden16.external_scheduler_attestation.v1"
ONE_SHOT_CONSUME_SCHEMA = "core.f3.graph_raw.hidden16.one_shot_consume_witness.v1"
RUNTIME_IDENTITY_SCHEMA = "core.f3.graph_raw.hidden16.runtime_identity_observation.v1"

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
MAX_JSON_ARRAY_ITEMS = 4096
MAX_DECLARED_BYTES = 1 << 50
CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})
GPU_UUID_RE = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
PCI_BUS_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


# This is the one evaluator argv contract accepted by the graph_raw diagnostic
# evidence chain.  The verifier never resolves or executes these tokens; the
# exact comparison is intentional.  Checking only a basename (for example,
# ``core_learning.py``) would allow a different interpreter or script to be
# presented with a self-consistent digest.
CANONICAL_INTERPRETER = "./.venv/bin/python"
CANONICAL_CORE_LEARNING = "scripts/core_learning.py"
CANONICAL_ACTION = "evaluate"
CANONICAL_MANIFEST = "campaigns/core-v1/f3-dataset-v2.json"
CANONICAL_DATA_ROOT = "."
CANONICAL_CHUNK_SIZE = "34560"
CANONICAL_DEVICE = "cuda:0"
CANONICAL_PROGRESS_EVERY = "25"
CANONICAL_ENV = "/usr/bin/env"
CANONICAL_ENV_ASSIGNMENT = "PYTHONDONTWRITEBYTECODE=1"


def _canonical_manifest_path() -> str:
    return "/tmp/f3-graph-raw500-hidden16-20260928-manifest.json"


def _canonical_training_path(seed: int) -> str:
    return f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-training.json"


def _canonical_checkpoint_path(seed: int) -> str:
    return f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-checkpoint.pt"

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
        "authority_id",
        "trust_anchor_sha256",
        "signature_sha256",
        "resource_snapshot_sha256",
        "scheduler_attestation",
        "one_shot_consume_witness",
        "runtime_identity",
        "process_identity_sha256",
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


def _digest(value: Any) -> str:
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
        if len(value) > MAX_JSON_ARRAY_ITEMS:
            _fail(f"{name} exceeds maximum JSON array length {MAX_JSON_ARRAY_ITEMS}")
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


def _non_placeholder_sha256(value: Any, name: str) -> str:
    text = _sha256(value, name)
    if len(set(text)) == 1:
        _fail(f"{name} must not be a placeholder digest")
    return text


def _utc_timestamp(value: Any, name: str) -> str:
    text = _string(value, name)
    if UTC_TIMESTAMP_RE.fullmatch(text) is None:
        _fail(f"{name} must be an RFC3339 UTC timestamp ending in Z")
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


def _fixed_artifact(value: Any, name: str, expected_path: str, *, suffix: str | None = None) -> dict[str, Any]:
    artifact = _artifact(value, name, suffix=suffix)
    if artifact["path"] != expected_path:
        _fail(f"{name}.path must be the fixed identity path {expected_path!r}")
    return artifact


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
    return {
        "path": path,
        "exists": True,
        "opened": True,
        "sha256": _sha256(source.get("sha256"), f"{name}.sha256"),
        "bytes": count,
        "schema": source.get("schema"),
    }


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
    checkpoint = _fixed_artifact(
        value.get("checkpoint"),
        f"{name}.checkpoint",
        _canonical_checkpoint_path(seed),
        suffix=".pt",
    )
    training = _fixed_artifact(
        value.get("training_receipt"),
        f"{name}.training_receipt",
        _canonical_training_path(seed),
        suffix=".json",
    )
    manifest = _fixed_artifact(
        value.get("manifest"),
        f"{name}.manifest",
        _canonical_manifest_path(),
        suffix=".json",
    )
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
        if source["path"] != _canonical_training_path(seed):
            _fail(f"{name}.runs.seed{seed}.source.path is not the fixed training identity path")
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
        if checkpoint_path != _canonical_checkpoint_path(seed):
            _fail(f"{name}.runs.seed{seed}.evidence.checkpoint.path is not the fixed checkpoint identity path")
        normalized[seed] = {
            "schema": "core.training.v1",
            "evidence_status": "complete",
            "model_kind": MODEL_KIND,
            "seed": seed,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "run_id": _run_id(seed),
            "formal_eligible": False,
            "qualification_credit": 0,
            "manifest_sha256": manifest_sha,
            "manifest": {"path": _canonical_manifest_path(), "sha256": manifest_sha},
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
    if count > MAX_DECLARED_BYTES:
        _fail(f"{name}.{key}.bytes exceeds the declared bound")
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
        manifest = _projection_artifact(projection, "manifest", f"{name}.seed_matrix.seed{seed}.projection", suffix=".json")
        evaluation = _projection_artifact(projection, "evaluation", f"{name}.seed_matrix.seed{seed}.projection", suffix=".json")
        trajectory = _projection_artifact(projection, "trajectory", f"{name}.seed_matrix.seed{seed}.projection", suffix=".h5")
        if checkpoint["path"] != _canonical_checkpoint_path(seed):
            _fail(f"{name}.seed_matrix.seed{seed}.checkpoint path drift")
        if training["path"] != _canonical_training_path(seed):
            _fail(f"{name}.seed_matrix.seed{seed}.training path drift")
        if manifest["path"] != _canonical_manifest_path():
            _fail(f"{name}.seed_matrix.seed{seed}.manifest path drift")
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
            "schema": f"core.f3.graph_raw.hidden16.seed{seed}.terminal_matrix_evidence.v1",
            "status": "bound_terminal_diagnostic",
            "seed": seed,
            "run_id": _run_id(seed),
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "namespace": namespace,
            "namespace_nonce": nonce,
            "checkpoint": checkpoint,
            "training_receipt": training,
            "manifest": manifest,
            "evaluation_artifact": evaluation,
            "trajectory": trajectory,
            "terminal_markers": {
                "terminal": markers["terminal"],
                "execution_complete": markers["execution_complete"],
                "finite_rollout_complete": markers["finite_rollout_complete"],
                "terminal_status": markers["terminal_status"],
            },
            "validator": {
                "passed": validator["passed"],
                "complete": validator["complete"],
                "trajectory_transitions": validator["trajectory_transitions"],
                "trajectory_frames": validator["trajectory_frames"],
            },
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


def _command_sha256(command: Sequence[str]) -> str:
    return _digest(list(command))


def _command(value: Any, name: str) -> tuple[list[str], str]:
    if not isinstance(value, list) or not value:
        _fail(f"{name} must be a non-empty argv array")
    if len(value) > 512:
        _fail(f"{name} contains too many argv entries")
    result: list[str] = []
    for index, item in enumerate(value):
        token = _string(item, f"{name}[{index}]")
        if any(ord(character) < 0x20 for character in token):
            _fail(f"{name}[{index}] contains a control character")
        lowered = token.lower()
        if any(forbidden in lowered for forbidden in ("pid", "formal", "credit", "synthetic")):
            _fail(f"{name}[{index}] contains a forbidden process/authority token")
        if len(token.encode("utf-8")) > 8192:
            _fail(f"{name}[{index}] exceeds the bounded argument length")
        result.append(token)
    if len(canonical_json(result).encode("utf-8")) > 128 * 1024:
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


def _expected_evaluator_command(
    *,
    checkpoint: str,
    trajectory: str,
    evaluation: str,
    namespace: str,
) -> list[str]:
    """Build the complete canonical evaluator argv for one nonce namespace."""

    return [
        CANONICAL_INTERPRETER,
        CANONICAL_CORE_LEARNING,
        CANONICAL_ACTION,
        "--manifest",
        CANONICAL_MANIFEST,
        "--data-root",
        CANONICAL_DATA_ROOT,
        "--checkpoint",
        checkpoint,
        "--case-id",
        CASE_ID,
        "--split",
        SPLIT,
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        CANONICAL_CHUNK_SIZE,
        "--device",
        CANONICAL_DEVICE,
        "--progress-every",
        CANONICAL_PROGRESS_EVERY,
        "--trajectory-output",
        trajectory,
        "--progress-output",
        namespace + "-evaluation-progress.json",
        "--output",
        evaluation,
        "--diagnostic",
    ]


def _validate_evaluator_command(
    argv: Sequence[str],
    *,
    checkpoint: str,
    trajectory: str,
    evaluation: str,
    namespace: str,
    name: str,
) -> tuple[list[str], str]:
    expected = _expected_evaluator_command(
        checkpoint=checkpoint,
        trajectory=trajectory,
        evaluation=evaluation,
        namespace=namespace,
    )
    observed = list(argv)
    if observed != expected:
        _fail(f"{name} must equal the complete canonical evaluator argv; token/flag/path drift detected")
    return expected, _command_sha256(expected)


def _validate_launcher_command(
    argv: Sequence[str],
    *,
    evaluator: Sequence[str],
    name: str,
) -> tuple[list[str], str]:
    """Accept only the direct evaluator or the fixed no-shell env wrapper."""

    evaluator_argv = list(evaluator)
    allowed = [evaluator_argv]
    allowed.append([CANONICAL_ENV, CANONICAL_ENV_ASSIGNMENT, *evaluator_argv])
    for device_index in range(8):
        allowed.append(
            [
                CANONICAL_ENV,
                CANONICAL_ENV_ASSIGNMENT,
                f"CUDA_VISIBLE_DEVICES={device_index}",
                *evaluator_argv,
            ]
        )
    observed = list(argv)
    if observed not in allowed:
        _fail(f"{name} must be the evaluator or the fixed /usr/bin/env wrapper; launcher drift detected")
    return observed, _command_sha256(observed)


def _launcher_physical_index(argv: Sequence[str], name: str) -> int:
    """Return the physical GPU selector from the sealed launcher argv.

    A direct evaluator argv leaves ``cuda:0``'s physical mapping implicit, so
    it is intentionally insufficient for a positive runtime observation.  The
    fixed no-shell ``env`` wrapper must carry exactly one numeric
    ``CUDA_VISIBLE_DEVICES`` assignment.
    """

    if len(argv) < 3 or list(argv[:2]) != [CANONICAL_ENV, CANONICAL_ENV_ASSIGNMENT]:
        _fail(f"{name} must use the fixed /usr/bin/env wrapper for physical GPU binding")
    selectors = [item for item in argv[2:] if item.startswith("CUDA_VISIBLE_DEVICES=")]
    if len(selectors) != 1:
        _fail(f"{name} must contain exactly one CUDA_VISIBLE_DEVICES assignment")
    value = selectors[0].removeprefix("CUDA_VISIBLE_DEVICES=")
    if not value.isdigit():
        _fail(f"{name}.CUDA_VISIBLE_DEVICES must be a decimal physical index")
    physical_index = int(value)
    if not 0 <= physical_index < 8:
        _fail(f"{name}.CUDA_VISIBLE_DEVICES is outside the fixed eight-device bound")
    return physical_index


def _runtime_gpu_identity(value: Any, name: str) -> dict[str, Any]:
    gpu = _mapping(value, name)
    _reject_unknown(
        gpu,
        {
            "physical_index",
            "uuid",
            "pci_bus_id",
            "logical_device",
            "cuda_visible_devices",
            "cuda_device_order",
            "memory_total_mib",
            "memory_used_mib",
            "memory_free_mib",
            "identity_sha256",
        },
        name,
    )
    physical_index = _strict_int(gpu.get("physical_index"), f"{name}.physical_index")
    if physical_index >= 8:
        _fail(f"{name}.physical_index is outside the fixed eight-device bound")
    uuid = _string(gpu.get("uuid"), f"{name}.uuid")
    if GPU_UUID_RE.fullmatch(uuid) is None or len(set(uuid[4:].lower())) <= 2:
        _fail(f"{name}.uuid is not a stable non-placeholder GPU UUID")
    pci_bus_id = _string(gpu.get("pci_bus_id"), f"{name}.pci_bus_id")
    if PCI_BUS_RE.fullmatch(pci_bus_id) is None:
        _fail(f"{name}.pci_bus_id is not a canonical PCI bus identity")
    _check_exact(gpu, "logical_device", CANONICAL_DEVICE, name)
    _check_exact(gpu, "cuda_visible_devices", str(physical_index), name)
    _check_exact(gpu, "cuda_device_order", "PCI_BUS_ID", name)
    total = _strict_int(gpu.get("memory_total_mib"), f"{name}.memory_total_mib", 1)
    used = _strict_int(gpu.get("memory_used_mib"), f"{name}.memory_used_mib")
    free = _strict_int(gpu.get("memory_free_mib"), f"{name}.memory_free_mib")
    if used + free > total:
        _fail(f"{name} memory used/free exceeds the observed total")
    core = {
        "physical_index": physical_index,
        "uuid": uuid,
        "pci_bus_id": pci_bus_id,
        "logical_device": CANONICAL_DEVICE,
        "cuda_visible_devices": str(physical_index),
        "cuda_device_order": "PCI_BUS_ID",
        "memory_total_mib": total,
        "memory_used_mib": used,
        "memory_free_mib": free,
    }
    identity_sha256 = _non_placeholder_sha256(gpu.get("identity_sha256"), f"{name}.identity_sha256")
    if identity_sha256 != _digest(core):
        _fail(f"{name}.identity_sha256 does not bind the observed UUID/PCI/memory identity")
    return {**core, "identity_sha256": identity_sha256}


def _process_plan_digest(
    shared: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    evaluator_command_sha256: str,
    launcher_command_sha256: str,
) -> str:
    return _digest(
        {
            "seed": shared["seed"],
            "run_id": shared["run_id"],
            "namespace": shared["namespace"],
            "namespace_nonce": shared["namespace_nonce"],
            "checkpoint": shared["checkpoint"],
            "training_receipt": shared["training_receipt"],
            "manifest": shared["manifest"],
            "evaluation_artifact": evaluation,
            "trajectory": shared["trajectory"],
            "evaluator_command_sha256": evaluator_command_sha256,
            "launcher_command_sha256": launcher_command_sha256,
        }
    )


def _validate_runtime_identity(
    value: Any,
    *,
    seed: int,
    shared: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    plan_sha256: str,
    launcher_physical_index: int,
    name: str,
) -> dict[str, Any]:
    runtime = _mapping(value, name)
    _reject_unknown(
        runtime,
        {
            "schema",
            "status",
            "source",
            "external_observation",
            "scheduler_owned",
            "observed_during_execution",
            "observed_after_exit",
            "plan_sha256",
            "namespace",
            "namespace_nonce",
            "gpu",
            "child",
            "terminal",
            "observed_at_utc",
            "identity_sha256",
        },
        name,
    )
    for key, expected in (
        ("schema", RUNTIME_IDENTITY_SCHEMA),
        ("status", "observed"),
        ("source", "scheduler_owned_live_probe"),
        ("external_observation", True),
        ("scheduler_owned", True),
        ("observed_during_execution", True),
        ("observed_after_exit", True),
        ("plan_sha256", plan_sha256),
        ("namespace", shared["namespace"]),
        ("namespace_nonce", shared["namespace_nonce"]),
    ):
        _check_exact(runtime, key, expected, name)
    gpu = _runtime_gpu_identity(runtime.get("gpu"), f"{name}.gpu")
    if gpu["physical_index"] != launcher_physical_index:
        _fail(f"{name}.gpu physical index drifts from CUDA_VISIBLE_DEVICES")
    child = _mapping(runtime.get("child"), f"{name}.child")
    _reject_unknown(
        child,
        {
            "observed",
            "child_runtime_attested",
            "gpu_uuid",
            "logical_device",
            "probe_tool",
            "process_identity_sha256",
        },
        f"{name}.child",
    )
    for key, expected in (
        ("observed", True),
        ("child_runtime_attested", True),
        ("gpu_uuid", gpu["uuid"]),
        ("logical_device", CANONICAL_DEVICE),
        ("probe_tool", "nvidia-smi"),
    ):
        _check_exact(child, key, expected, f"{name}.child")
    process_identity_sha256 = _non_placeholder_sha256(
        child.get("process_identity_sha256"), f"{name}.child.process_identity_sha256"
    )
    terminal = _mapping(runtime.get("terminal"), f"{name}.terminal")
    _reject_unknown(
        terminal,
        {
            "observed",
            "status",
            "transitions",
            "frames",
            "namespace",
            "namespace_nonce",
            "evaluation_sha256",
            "trajectory_sha256",
        },
        f"{name}.terminal",
    )
    for key, expected in (
        ("observed", True),
        ("status", "completed"),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("namespace", shared["namespace"]),
        ("namespace_nonce", shared["namespace_nonce"]),
        ("evaluation_sha256", evaluation["sha256"]),
        ("trajectory_sha256", shared["trajectory"]["sha256"]),
    ):
        _check_exact(terminal, key, expected, f"{name}.terminal")
    observed_at_utc = _utc_timestamp(runtime.get("observed_at_utc"), f"{name}.observed_at_utc")
    core = {
        "schema": RUNTIME_IDENTITY_SCHEMA,
        "status": "observed",
        "source": "scheduler_owned_live_probe",
        "external_observation": True,
        "scheduler_owned": True,
        "observed_during_execution": True,
        "observed_after_exit": True,
        "plan_sha256": plan_sha256,
        "namespace": shared["namespace"],
        "namespace_nonce": shared["namespace_nonce"],
        "gpu": gpu,
        "child": {
            "observed": True,
            "child_runtime_attested": True,
            "gpu_uuid": gpu["uuid"],
            "logical_device": CANONICAL_DEVICE,
            "probe_tool": "nvidia-smi",
            "process_identity_sha256": process_identity_sha256,
        },
        "terminal": {
            "observed": True,
            "status": "completed",
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "namespace": shared["namespace"],
            "namespace_nonce": shared["namespace_nonce"],
            "evaluation_sha256": evaluation["sha256"],
            "trajectory_sha256": shared["trajectory"]["sha256"],
        },
        "observed_at_utc": observed_at_utc,
    }
    identity_sha256 = _non_placeholder_sha256(runtime.get("identity_sha256"), f"{name}.identity_sha256")
    if identity_sha256 != _digest(core):
        _fail(f"{name}.identity_sha256 does not bind the live GPU and terminal observation")
    return {**core, "identity_sha256": identity_sha256}


def _validate_scheduler_attestation(
    value: Any,
    *,
    shared: Mapping[str, Any],
    plan_sha256: str,
    runtime_identity: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    attestation = _mapping(value, name)
    _reject_unknown(
        attestation,
        {
            "schema",
            "status",
            "external_scheduler",
            "one_shot",
            "authority_id",
            "trust_anchor_sha256",
            "signature_algorithm",
            "signature_sha256",
            "signature_verified",
            "plan_sha256",
            "namespace",
            "namespace_nonce",
            "resource_snapshot_sha256",
            "gpu_identity_sha256",
            "observed_at_utc",
            "local_self_attestation_accepted",
            "digest",
        },
        name,
    )
    for key, expected in (
        ("schema", SCHEDULER_ATTESTATION_SCHEMA),
        ("status", "authorized"),
        ("external_scheduler", True),
        ("one_shot", True),
        ("signature_algorithm", "ed25519"),
        ("signature_verified", True),
        ("plan_sha256", plan_sha256),
        ("namespace", shared["namespace"]),
        ("namespace_nonce", shared["namespace_nonce"]),
        ("gpu_identity_sha256", runtime_identity["gpu"]["identity_sha256"]),
        ("local_self_attestation_accepted", False),
    ):
        _check_exact(attestation, key, expected, name)
    authority_id = _non_placeholder_sha256(attestation.get("authority_id"), f"{name}.authority_id")
    trust_anchor_sha256 = _non_placeholder_sha256(attestation.get("trust_anchor_sha256"), f"{name}.trust_anchor_sha256")
    signature_sha256 = _non_placeholder_sha256(attestation.get("signature_sha256"), f"{name}.signature_sha256")
    resource_snapshot_sha256 = _non_placeholder_sha256(
        attestation.get("resource_snapshot_sha256"), f"{name}.resource_snapshot_sha256"
    )
    observed_at_utc = _utc_timestamp(attestation.get("observed_at_utc"), f"{name}.observed_at_utc")
    core = {
        "schema": SCHEDULER_ATTESTATION_SCHEMA,
        "status": "authorized",
        "external_scheduler": True,
        "one_shot": True,
        "authority_id": authority_id,
        "trust_anchor_sha256": trust_anchor_sha256,
        "signature_algorithm": "ed25519",
        "signature_sha256": signature_sha256,
        "signature_verified": True,
        "plan_sha256": plan_sha256,
        "namespace": shared["namespace"],
        "namespace_nonce": shared["namespace_nonce"],
        "resource_snapshot_sha256": resource_snapshot_sha256,
        "gpu_identity_sha256": runtime_identity["gpu"]["identity_sha256"],
        "observed_at_utc": observed_at_utc,
        "local_self_attestation_accepted": False,
    }
    digest = _non_placeholder_sha256(attestation.get("digest"), f"{name}.digest")
    if digest != _digest(core):
        _fail(f"{name}.digest does not bind the external scheduler attestation")
    return {**core, "digest": digest}


def _validate_one_shot_consume_witness(
    value: Any,
    *,
    shared: Mapping[str, Any],
    plan_sha256: str,
    runtime_identity: Mapping[str, Any],
    scheduler_attestation: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    witness = _mapping(value, name)
    _reject_unknown(
        witness,
        {
            "schema",
            "status",
            "external_scheduler",
            "one_shot",
            "replay_free",
            "atomic_compare_and_swap",
            "authority_id",
            "trust_anchor_sha256",
            "scheduler_attestation_sha256",
            "plan_sha256",
            "namespace",
            "namespace_nonce",
            "gpu_identity_sha256",
            "consume_id",
            "reservation_sha256",
            "previous_state",
            "new_state",
            "observed_at_utc",
            "local_self_attestation_accepted",
            "digest",
        },
        name,
    )
    for key, expected in (
        ("schema", ONE_SHOT_CONSUME_SCHEMA),
        ("status", "consumed"),
        ("external_scheduler", True),
        ("one_shot", True),
        ("replay_free", True),
        ("atomic_compare_and_swap", True),
        ("authority_id", scheduler_attestation["authority_id"]),
        ("trust_anchor_sha256", scheduler_attestation["trust_anchor_sha256"]),
        ("scheduler_attestation_sha256", scheduler_attestation["digest"]),
        ("plan_sha256", plan_sha256),
        ("namespace", shared["namespace"]),
        ("namespace_nonce", shared["namespace_nonce"]),
        ("gpu_identity_sha256", runtime_identity["gpu"]["identity_sha256"]),
        ("previous_state", "reserved"),
        ("new_state", "consumed"),
        ("local_self_attestation_accepted", False),
    ):
        _check_exact(witness, key, expected, name)
    consume_id = _non_placeholder_sha256(witness.get("consume_id"), f"{name}.consume_id")
    reservation_sha256 = _non_placeholder_sha256(witness.get("reservation_sha256"), f"{name}.reservation_sha256")
    observed_at_utc = _utc_timestamp(witness.get("observed_at_utc"), f"{name}.observed_at_utc")
    core = {
        "schema": ONE_SHOT_CONSUME_SCHEMA,
        "status": "consumed",
        "external_scheduler": True,
        "one_shot": True,
        "replay_free": True,
        "atomic_compare_and_swap": True,
        "authority_id": scheduler_attestation["authority_id"],
        "trust_anchor_sha256": scheduler_attestation["trust_anchor_sha256"],
        "scheduler_attestation_sha256": scheduler_attestation["digest"],
        "plan_sha256": plan_sha256,
        "namespace": shared["namespace"],
        "namespace_nonce": shared["namespace_nonce"],
        "gpu_identity_sha256": runtime_identity["gpu"]["identity_sha256"],
        "consume_id": consume_id,
        "reservation_sha256": reservation_sha256,
        "previous_state": "reserved",
        "new_state": "consumed",
        "observed_at_utc": observed_at_utc,
        "local_self_attestation_accepted": False,
    }
    digest = _non_placeholder_sha256(witness.get("digest"), f"{name}.digest")
    if digest != _digest(core):
        _fail(f"{name}.digest does not bind the external one-shot consume witness")
    return {**core, "digest": digest}


PROCESS_PRODUCER_KEYS = frozenset({"schema", "id", "version", "source_bound", "synthetic_only", "digest"})
PROCESS_COMPONENT_KEYS = frozenset({"alive", "returncode", "reaped", "command", "command_sha256"})
PROCESS_ARTIFACT_BINDING_KEYS = frozenset({"seed", "run_id", "namespace", "namespace_nonce", "checkpoint", "training_receipt", "manifest", "evaluation_artifact", "trajectory"})
PROCESS_ATTESTATION_KEYS = frozenset({"schema", "status", "source_bound", "synthetic_only", "natural_exit", "observed_after_exit", "producer_digest", "evaluator", "launcher", "artifact_bindings", "artifact_bindings_sha256", "scheduler_attestation", "one_shot_consume_witness", "runtime_identity", "digest"})


def _validate_process_component(value: Any, name: str) -> tuple[dict[str, Any], list[str], str]:
    component = _mapping(value, name)
    _reject_unknown(component, PROCESS_COMPONENT_KEYS, name)
    _check_exact(component, "alive", False, name)
    _check_exact(component, "returncode", 0, name)
    _check_exact(component, "reaped", True, name)
    command, command_sha256 = _command(component.get("command"), f"{name}.command")
    _check_exact(component, "command_sha256", command_sha256, name)
    return {
        "alive": False,
        "returncode": 0,
        "reaped": True,
        "command": command,
        "command_sha256": command_sha256,
    }, command, command_sha256


def _validate_evaluation_identity(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "source_bound", "diagnostic_only", "formal", "formal_eligible",
        "T1_numerical", "T2_macro", "T2_path", "qualification", "qualification_credit", "credit",
        "seed", "run_id", "namespace", "namespace_nonce", "model_kind", "hidden", "updates",
        "case_id", "split", "transitions", "frames", "evaluation_artifact", "terminal_markers", "digest",
    })
    _reject_aliases(value, name)
    _reject_unknown(value, allowed, name)
    _zero_credit(value, name)
    for key, expected in (
        ("schema", EVALUATION_IDENTITY_SCHEMA),
        ("status", "completed_diagnostic"),
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
    evaluation = _fixed_artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", namespace + "-evaluation.json", suffix=".json")
    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    _reject_unknown(markers, frozenset({"terminal", "execution_complete", "finite_rollout_complete", "terminal_status", "future_state_inputs"}), f"{name}.terminal_markers")
    for key, expected in (("terminal", True), ("execution_complete", True), ("finite_rollout_complete", True), ("terminal_status", "completed"), ("future_state_inputs", False)):
        _check_exact(markers, key, expected, f"{name}.terminal_markers")
    normalized_core = {
        "schema": EVALUATION_IDENTITY_SCHEMA,
        "status": "completed_diagnostic",
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
        "run_id": _run_id(seed),
        "namespace": namespace,
        "namespace_nonce": nonce,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "evaluation_artifact": evaluation,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "future_state_inputs": False,
        },
    }
    _check_exact(value, "digest", _digest(normalized_core), name)
    return {**normalized_core, "digest": _digest(normalized_core)}


def _validate_rollout(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({"schema", "report_id", "status", "evaluation_artifact", "terminal_markers"})
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.rollout_identity.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-full835-rollout-identity-v1", name)
    _check_exact(value, "status", "completed_diagnostic", name)
    evaluation = _fixed_artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", shared["namespace"] + "-evaluation.json", suffix=".json")
    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    _reject_unknown(markers, frozenset({"terminal", "execution_complete", "finite_rollout_complete", "terminal_status", "future_state_inputs"}), f"{name}.terminal_markers")
    for key, expected in (("terminal", True), ("execution_complete", True), ("finite_rollout_complete", True), ("terminal_status", "completed"), ("future_state_inputs", False)):
        _check_exact(markers, key, expected, f"{name}.terminal_markers")
    return {
        **dict(value),
        **shared,
        "evaluation_artifact": evaluation,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "future_state_inputs": False,
        },
    }


def _validate_process(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({
        "schema", "report_id", "status", "evaluation_artifact", "evaluator_alive", "launcher_alive",
        "evaluator_returncode", "launcher_returncode", "returncode", "producer", "exit_attestation",
    })
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.process_exit_proof.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-process-exit-proof-v1", name)
    _check_exact(value, "status", "exited_successfully", name)
    for key, expected in (("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0)):
        _check_exact(value, key, expected, name)
    evaluation = _fixed_artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", shared["namespace"] + "-evaluation.json", suffix=".json")

    producer = _mapping(value.get("producer"), f"{name}.producer")
    _reject_unknown(producer, PROCESS_PRODUCER_KEYS, f"{name}.producer")
    for key, expected in (("schema", PROCESS_PRODUCER_SCHEMA), ("id", PROCESS_PRODUCER_ID), ("version", 1), ("source_bound", True), ("synthetic_only", False)):
        _check_exact(producer, key, expected, f"{name}.producer")
    producer_core = {key: producer[key] for key in PROCESS_PRODUCER_KEYS if key != "digest"}
    producer_digest = _digest(producer_core)
    _check_exact(producer, "digest", producer_digest, f"{name}.producer")
    normalized_producer = {**producer_core, "digest": producer_digest}

    attestation = _mapping(value.get("exit_attestation"), f"{name}.exit_attestation")
    _reject_unknown(attestation, PROCESS_ATTESTATION_KEYS, f"{name}.exit_attestation")
    for key, expected in (("schema", PROCESS_ATTESTATION_SCHEMA), ("status", "exited_successfully"), ("source_bound", True), ("synthetic_only", False), ("natural_exit", True), ("observed_after_exit", True), ("producer_digest", producer_digest)):
        _check_exact(attestation, key, expected, f"{name}.exit_attestation")
    evaluator, evaluator_command, evaluator_command_sha256 = _validate_process_component(attestation.get("evaluator"), f"{name}.exit_attestation.evaluator")
    launcher, launcher_command, launcher_command_sha256 = _validate_process_component(attestation.get("launcher"), f"{name}.exit_attestation.launcher")
    canonical_evaluator, canonical_evaluator_sha256 = _validate_evaluator_command(
        evaluator_command,
        checkpoint=shared["checkpoint"]["path"],
        trajectory=shared["trajectory"]["path"],
        evaluation=evaluation["path"],
        namespace=shared["namespace"],
        name=f"{name}.exit_attestation.evaluator.command",
    )
    if evaluator_command_sha256 != canonical_evaluator_sha256:
        _fail(f"{name}.exit_attestation.evaluator.command_sha256 is not the canonical argv digest")
    canonical_launcher, canonical_launcher_sha256 = _validate_launcher_command(
        launcher_command,
        evaluator=canonical_evaluator,
        name=f"{name}.exit_attestation.launcher.command",
    )
    if launcher_command_sha256 != canonical_launcher_sha256:
        _fail(f"{name}.exit_attestation.launcher.command_sha256 is not the canonical argv digest")
    evaluator = {
        **evaluator,
        "command": canonical_evaluator,
        "command_sha256": canonical_evaluator_sha256,
    }
    launcher = {
        **launcher,
        "command": canonical_launcher,
        "command_sha256": canonical_launcher_sha256,
    }
    launcher_physical_index = _launcher_physical_index(
        canonical_launcher,
        f"{name}.exit_attestation.launcher.command",
    )
    plan_sha256 = _process_plan_digest(
        shared,
        evaluation,
        canonical_evaluator_sha256,
        canonical_launcher_sha256,
    )
    runtime_identity = _validate_runtime_identity(
        attestation.get("runtime_identity"),
        seed=seed,
        shared=shared,
        evaluation=evaluation,
        plan_sha256=plan_sha256,
        launcher_physical_index=launcher_physical_index,
        name=f"{name}.exit_attestation.runtime_identity",
    )
    scheduler_attestation = _validate_scheduler_attestation(
        attestation.get("scheduler_attestation"),
        shared=shared,
        plan_sha256=plan_sha256,
        runtime_identity=runtime_identity,
        name=f"{name}.exit_attestation.scheduler_attestation",
    )
    one_shot_consume_witness = _validate_one_shot_consume_witness(
        attestation.get("one_shot_consume_witness"),
        shared=shared,
        plan_sha256=plan_sha256,
        runtime_identity=runtime_identity,
        scheduler_attestation=scheduler_attestation,
        name=f"{name}.exit_attestation.one_shot_consume_witness",
    )

    bindings = _mapping(attestation.get("artifact_bindings"), f"{name}.exit_attestation.artifact_bindings")
    _reject_unknown(bindings, PROCESS_ARTIFACT_BINDING_KEYS, f"{name}.exit_attestation.artifact_bindings")
    for key, expected in (("seed", seed), ("run_id", _run_id(seed)), ("namespace", shared["namespace"]), ("namespace_nonce", shared["namespace_nonce"])):
        _check_exact(bindings, key, expected, f"{name}.exit_attestation.artifact_bindings")
    normalized_bindings = {
        "seed": seed,
        "run_id": _run_id(seed),
        "namespace": shared["namespace"],
        "namespace_nonce": shared["namespace_nonce"],
        "checkpoint": _fixed_artifact(bindings.get("checkpoint"), f"{name}.exit_attestation.artifact_bindings.checkpoint", shared["checkpoint"]["path"], suffix=".pt"),
        "training_receipt": _fixed_artifact(bindings.get("training_receipt"), f"{name}.exit_attestation.artifact_bindings.training_receipt", shared["training_receipt"]["path"], suffix=".json"),
        "manifest": _fixed_artifact(bindings.get("manifest"), f"{name}.exit_attestation.artifact_bindings.manifest", shared["manifest"]["path"], suffix=".json"),
        "evaluation_artifact": _fixed_artifact(bindings.get("evaluation_artifact"), f"{name}.exit_attestation.artifact_bindings.evaluation_artifact", evaluation["path"], suffix=".json"),
        "trajectory": _fixed_artifact(bindings.get("trajectory"), f"{name}.exit_attestation.artifact_bindings.trajectory", shared["trajectory"]["path"], suffix=".h5"),
    }
    for artifact_name in ("checkpoint", "training_receipt", "manifest", "trajectory"):
        _artifact_equal(normalized_bindings[artifact_name], shared[artifact_name], f"{name}.exit_attestation.artifact_bindings.{artifact_name}")
    _artifact_equal(normalized_bindings["evaluation_artifact"], evaluation, f"{name}.exit_attestation.artifact_bindings.evaluation_artifact")
    bindings_digest = _digest(normalized_bindings)
    _check_exact(attestation, "artifact_bindings_sha256", bindings_digest, f"{name}.exit_attestation")
    normalized_attestation_core = {
        "schema": PROCESS_ATTESTATION_SCHEMA,
        "status": "exited_successfully",
        "source_bound": True,
        "synthetic_only": False,
        "natural_exit": True,
        "observed_after_exit": True,
        "producer_digest": producer_digest,
        "evaluator": evaluator,
        "launcher": launcher,
        "artifact_bindings": normalized_bindings,
        "artifact_bindings_sha256": bindings_digest,
        "runtime_identity": runtime_identity,
        "scheduler_attestation": scheduler_attestation,
        "one_shot_consume_witness": one_shot_consume_witness,
    }
    attestation_digest = _digest(normalized_attestation_core)
    _check_exact(attestation, "digest", attestation_digest, f"{name}.exit_attestation")
    normalized_attestation = {**normalized_attestation_core, "digest": attestation_digest}
    normalized = {
        **dict(value),
        **shared,
        "evaluation_artifact": evaluation,
        "producer": normalized_producer,
        "exit_attestation": normalized_attestation,
        "evaluator_alive": False,
        "launcher_alive": False,
        "evaluator_returncode": 0,
        "launcher_returncode": 0,
        "returncode": 0,
    }
    # Keep these names live in the normalized shape so command identity cannot
    # be silently dropped when the envelope is embedded in a report.
    _check_exact(normalized_attestation["evaluator"], "command_sha256", evaluator_command_sha256, f"{name}.exit_attestation.evaluator")
    _check_exact(normalized_attestation["launcher"], "command_sha256", launcher_command_sha256, f"{name}.exit_attestation.launcher")
    return normalized


def _validate_validator(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = COMMON_ENVELOPE_KEYS | frozenset({"schema", "report_id", "status", "validator_schema", "passed", "complete", "expected_transitions", "frames_executed", "trajectory_transitions", "trajectory_frames", "tail_frame_count", "production_artifacts_touched", "actual_future_state_inputs", "synthetic_only"})
    shared = _envelope(value, seed, name, allowed)
    _check_exact(value, "schema", f"core.f3.graph_raw.hidden16.seed{seed}.hdf5_validator_receipt.v1", name)
    _check_exact(value, "report_id", f"f3-graph-raw-hidden16-seed{seed}-hdf5-validator-receipt-v1", name)
    _check_exact(value, "status", "validated", name)
    _check_exact(value, "validator_schema", VALIDATOR_SCHEMA, name)
    for key, expected in (("passed", True), ("complete", True), ("expected_transitions", TRANSITIONS), ("frames_executed", FRAMES), ("trajectory_transitions", TRANSITIONS), ("trajectory_frames", FRAMES), ("tail_frame_count", 0), ("production_artifacts_touched", False), ("actual_future_state_inputs", False), ("synthetic_only", False)):
        _check_exact(value, key, expected, name)
    return {**dict(value), **shared}


def _validate_training_evidence(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "evidence_status", "model_kind", "seed", "hidden", "updates", "run_id",
        "formal_eligible", "qualification_credit", "manifest_sha256", "manifest", "training_receipt", "checkpoint",
    })
    _reject_aliases(value, name)
    _reject_unknown(value, allowed, name)
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
        _check_exact(value, key, expected, name)
    manifest_sha = _sha256(value.get("manifest_sha256"), f"{name}.manifest_sha256")
    manifest_value = _mapping(value.get("manifest"), f"{name}.manifest")
    _reject_unknown(manifest_value, frozenset({"path", "sha256"}), f"{name}.manifest")
    manifest_path = _declared_path(manifest_value.get("path"), f"{name}.manifest.path", ".json")
    if manifest_path != _canonical_manifest_path():
        _fail(f"{name}.manifest.path is not the fixed manifest identity path")
    manifest = {"path": manifest_path, "sha256": _sha256(manifest_value.get("sha256"), f"{name}.manifest.sha256")}
    if manifest["sha256"] != manifest_sha:
        _fail(f"{name}.manifest.sha256 drifts from manifest_sha256")
    training = _source_claim(value.get("training_receipt"), f"{name}.training_receipt")
    if training["path"] != _canonical_training_path(seed):
        _fail(f"{name}.training_receipt.path is not the fixed training identity path")
    checkpoint = _mapping(value.get("checkpoint"), f"{name}.checkpoint")
    _reject_unknown(checkpoint, frozenset({"path", "sha256"}), f"{name}.checkpoint")
    checkpoint_path = _declared_path(checkpoint.get("path"), f"{name}.checkpoint.path", ".pt")
    if checkpoint_path != _canonical_checkpoint_path(seed):
        _fail(f"{name}.checkpoint.path is not the fixed checkpoint identity path")
    normalized = {
        "schema": "core.training.v1",
        "evidence_status": "complete",
        "model_kind": MODEL_KIND,
        "seed": seed,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "run_id": _run_id(seed),
        "formal_eligible": False,
        "qualification_credit": 0,
        "manifest_sha256": manifest_sha,
        "manifest": manifest,
        "training_receipt": training,
        "checkpoint": {"path": checkpoint_path, "sha256": _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")},
    }
    return normalized


def _validate_terminal_evidence(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "seed", "run_id", "model_kind", "hidden", "updates", "case_id", "split", "transitions", "frames",
        "namespace", "namespace_nonce", "checkpoint", "training_receipt", "manifest", "evaluation_artifact", "trajectory",
        "terminal_markers", "validator",
    })
    _reject_aliases(value, name)
    _reject_unknown(value, allowed, name)
    for key, expected in (
        ("schema", f"core.f3.graph_raw.hidden16.seed{seed}.terminal_matrix_evidence.v1"),
        ("status", "bound_terminal_diagnostic"),
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
    checkpoint = _fixed_artifact(value.get("checkpoint"), f"{name}.checkpoint", _canonical_checkpoint_path(seed), suffix=".pt")
    training = _fixed_artifact(value.get("training_receipt"), f"{name}.training_receipt", _canonical_training_path(seed), suffix=".json")
    manifest = _fixed_artifact(value.get("manifest"), f"{name}.manifest", _canonical_manifest_path(), suffix=".json")
    evaluation = _fixed_artifact(value.get("evaluation_artifact"), f"{name}.evaluation_artifact", namespace + "-evaluation.json", suffix=".json")
    trajectory = _fixed_artifact(value.get("trajectory"), f"{name}.trajectory", namespace + "-trajectory.h5", suffix=".h5")
    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    _reject_unknown(markers, frozenset({"terminal", "execution_complete", "finite_rollout_complete", "terminal_status"}), f"{name}.terminal_markers")
    for key, expected in (("terminal", True), ("execution_complete", True), ("finite_rollout_complete", True), ("terminal_status", "completed")):
        _check_exact(markers, key, expected, f"{name}.terminal_markers")
    validator = _mapping(value.get("validator"), f"{name}.validator")
    _reject_unknown(validator, frozenset({"passed", "complete", "trajectory_transitions", "trajectory_frames"}), f"{name}.validator")
    for key, expected in (("passed", True), ("complete", True), ("trajectory_transitions", TRANSITIONS), ("trajectory_frames", FRAMES)):
        _check_exact(validator, key, expected, f"{name}.validator")
    return {
        "schema": f"core.f3.graph_raw.hidden16.seed{seed}.terminal_matrix_evidence.v1",
        "status": "bound_terminal_diagnostic",
        "seed": seed,
        "run_id": _run_id(seed),
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": namespace,
        "namespace_nonce": nonce,
        "checkpoint": checkpoint,
        "training_receipt": training,
        "manifest": manifest,
        "evaluation_artifact": evaluation,
        "trajectory": trajectory,
        "terminal_markers": {"terminal": True, "execution_complete": True, "finite_rollout_complete": True, "terminal_status": "completed"},
        "validator": {"passed": True, "complete": True, "trajectory_transitions": TRANSITIONS, "trajectory_frames": FRAMES},
    }


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
    if terminal["manifest"]["path"] != training["manifest"]["path"] or terminal["manifest"]["sha256"] != training["manifest"]["sha256"]:
        _fail(f"{name}: manifest path/SHA drifts from training matrix")
    if terminal["checkpoint"]["path"] != rollout["checkpoint"]["path"]:
        _fail(f"{name}: terminal checkpoint path differs from rollout identity")
    for source_name, source in (("rollout", rollout), ("process", process), ("validator", validator)):
        for artifact_name in ("checkpoint", "training_receipt", "manifest", "trajectory"):
            _artifact_equal(source[artifact_name], rollout[artifact_name], f"{name}.{source_name}.{artifact_name}")
    _artifact_equal(terminal["checkpoint"], rollout["checkpoint"], f"{name}.terminal.checkpoint")
    _artifact_equal(terminal["manifest"], rollout["manifest"], f"{name}.terminal.manifest")
    _artifact_equal(terminal["trajectory"], rollout["trajectory"], f"{name}.terminal.trajectory", allow_missing_sha=True)
    _artifact_equal(terminal["evaluation_artifact"], rollout["evaluation_artifact"], f"{name}.evaluation_artifact")
    _artifact_equal(process["evaluation_artifact"], rollout["evaluation_artifact"], f"{name}.process.evaluation_artifact")
    if rollout["manifest"]["sha256"] != training["manifest_sha256"] or rollout["manifest"]["path"] != training["manifest"]["path"]:
        _fail(f"{name}: manifest path/SHA drifts from training matrix")


def _evaluation_identity_from_rollout(rollout: Mapping[str, Any], seed: int) -> dict[str, Any]:
    core = {
        "schema": EVALUATION_IDENTITY_SCHEMA,
        "status": "completed_diagnostic",
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
        "run_id": _run_id(seed),
        "namespace": rollout["namespace"],
        "namespace_nonce": rollout["namespace_nonce"],
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "evaluation_artifact": rollout["evaluation_artifact"],
        "terminal_markers": rollout["terminal_markers"],
    }
    return _validate_evaluation_identity({**core, "digest": _digest(core)}, seed, f"seed{seed} evaluation_identity")


REPORT_EVIDENCE_KEYS = frozenset({
    "source_metadata", "training_matrix", "terminal_matrix", "rollout_identity", "process_exit_proof",
    "evaluation_identity", "validator_receipt",
})


def _validate_report_seed_evidence(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _reject_unknown(value, REPORT_EVIDENCE_KEYS, name)
    source_metadata = _mapping(value.get("source_metadata"), f"{name}.source_metadata")
    source_names = frozenset({"training_matrix", "terminal_matrix", "rollout_identity", "process_exit_proof", "validator_receipt"})
    _reject_unknown(source_metadata, source_names, f"{name}.source_metadata")
    expected_schemas = {
        "training_matrix": TRAINING_MATRIX_SCHEMA,
        "terminal_matrix": TERMINAL_MATRIX_SCHEMA,
        "rollout_identity": f"core.f3.graph_raw.hidden16.seed{seed}.rollout_identity.v1",
        "process_exit_proof": f"core.f3.graph_raw.hidden16.seed{seed}.process_exit_proof.v1",
        "validator_receipt": f"core.f3.graph_raw.hidden16.seed{seed}.hdf5_validator_receipt.v1",
    }
    for source_name in source_names:
        metadata = _mapping(source_metadata.get(source_name), f"{name}.source_metadata.{source_name}")
        _validate_source_metadata(metadata, f"{name}.source_metadata.{source_name}", require_opened=True)
        if metadata.get("schema") != expected_schemas[source_name]:
            _fail(f"{name}.source_metadata.{source_name}.schema is not the expected evidence schema")

    training = _validate_training_evidence(_mapping(value.get("training_matrix"), f"{name}.training_matrix"), seed, f"{name}.training_matrix")
    terminal = _validate_terminal_evidence(_mapping(value.get("terminal_matrix"), f"{name}.terminal_matrix"), seed, f"{name}.terminal_matrix")
    rollout = _validate_rollout(_mapping(value.get("rollout_identity"), f"{name}.rollout_identity"), seed, f"{name}.rollout_identity")
    process = _validate_process(_mapping(value.get("process_exit_proof"), f"{name}.process_exit_proof"), seed, f"{name}.process_exit_proof")
    evaluation = _validate_evaluation_identity(_mapping(value.get("evaluation_identity"), f"{name}.evaluation_identity"), seed, f"{name}.evaluation_identity")
    validator = _validate_validator(_mapping(value.get("validator_receipt"), f"{name}.validator_receipt"), seed, f"{name}.validator_receipt")
    _cross_bind(seed, training, terminal, rollout, process, validator)
    if evaluation["seed"] != seed or evaluation["run_id"] != _run_id(seed):
        _fail(f"{name}.evaluation_identity seed/run identity drifts")
    if evaluation["namespace"] != rollout["namespace"] or evaluation["namespace_nonce"] != rollout["namespace_nonce"]:
        _fail(f"{name}.evaluation_identity namespace/nonce drifts")
    _artifact_equal(evaluation["evaluation_artifact"], rollout["evaluation_artifact"], f"{name}.evaluation_identity.evaluation_artifact")
    _artifact_equal(evaluation["evaluation_artifact"], terminal["evaluation_artifact"], f"{name}.evaluation_identity.terminal.evaluation_artifact")
    return {
        "source_metadata": {source_name: dict(source_metadata[source_name]) for source_name in source_names},
        "training_matrix": training,
        "terminal_matrix": terminal,
        "rollout_identity": rollout,
        "process_exit_proof": process,
        "evaluation_identity": evaluation,
        "validator_receipt": validator,
    }


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
            evaluation_identity = _evaluation_identity_from_rollout(rollout, seed)
        except KeyError as error:
            row["blocked_reasons"].append(f"seed{seed} missing required evidence envelope: {error}")
        except (VerifierError, TypeError, RecursionError) as error:
            row["blocked_reasons"].append(str(error))
        else:
            row["status"] = "independently_verified"
            row["evidence"] = {
                "source_metadata": {
                    "training_matrix": dict(training_source),
                    "terminal_matrix": dict(terminal_source),
                    "rollout_identity": dict(rollout_sources[seed]),
                    "process_exit_proof": dict(process_sources[seed]),
                    "validator_receipt": dict(validator_sources[seed]),
                },
                "training_matrix": training_rows[seed],
                "terminal_matrix": terminal_rows[seed],
                "rollout_identity": rollout,
                "process_exit_proof": process,
                "evaluation_identity": evaluation_identity,
                "validator_receipt": validator,
            }
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
        _check("external_scheduler_trust_anchor_witnesses", all_verified, "every seed has an externally attested scheduler trust-anchor witness bound to its plan"),
        _check("one_shot_consume_witnesses", all_verified, "every seed has an externally consumed, replay-free one-shot witness"),
        _check("runtime_gpu_terminal_identity_observations", all_verified, "every seed binds live GPU UUID/PCI, child logical device, and terminal artifact identity"),
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
            "required_evidence_classes": ["training_matrix", "terminal_matrix", "rollout_identity", "process_exit_proof", "hdf5_validator_receipt", "external_scheduler_attestation", "one_shot_consume_witness", "runtime_identity_observation"],
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
            "This additive verifier consumes bounded JSON receipts only. It requires "
            "external scheduler trust-anchor/one-shot-consume witnesses and a live "
            "GPU/terminal identity observation in every positive process envelope. It never opens "
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


def _validate_source_metadata(value: Any, name: str, *, require_opened: bool = False) -> None:
    item = _mapping(value, name)
    _reject_unknown(item, SOURCE_KEYS, name)
    _string(item.get("path"), f"{name}.path") if item.get("path") is not None else None
    if type(item.get("exists")) is not bool or type(item.get("opened")) is not bool:
        _fail(f"{name}.exists/opened must be booleans")
    if require_opened:
        _check_exact(item, "exists", True, name)
        _check_exact(item, "opened", True, name)
        _strict_int(item.get("bytes"), f"{name}.bytes", 1)
        _sha256(item.get("sha256"), f"{name}.sha256")
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
        for key, expected in (("diagnostic_only", True), ("formal", False), ("formal_eligible", False), ("T1_numerical", False), ("T2_macro", False), ("T2_path", False), ("qualification", False), ("qualification_credit", 0), ("credit", 0), ("fail_closed", not source_bound), ("independently_terminal_verified", source_bound)):
            _check_exact(report, key, expected, "report")
        if type(report.get("receipt_bound")) is not bool:
            _fail("report.receipt_bound must be boolean")
        _check_exact(report, "status", "independently_terminal_verified" if source_bound else "blocked_fail_closed", "report")
        contract = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, expected in (("model_kind", MODEL_KIND), ("hidden", HIDDEN), ("updates", UPDATES), ("seeds", list(SEEDS)), ("case_id", CASE_ID), ("split", SPLIT), ("transitions", TRANSITIONS), ("frames", FRAMES), ("fresh_32_hex_nonce", True), ("declared_artifacts_are_not_opened", True), ("zero_credit_only", True)):
            _check_exact(contract, key, expected, "report.expected_contract")
        _validate_source_metadata(report.get("training_matrix_source"), "report.training_matrix_source", require_opened=source_bound)
        _validate_source_metadata(report.get("terminal_matrix_source"), "report.terminal_matrix_source", require_opened=source_bound)
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or len(rows) != len(SEEDS) or [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
            _fail("report.seed_matrix must contain seeds 17, 29, and 43 in order")
        row_keys = frozenset({"seed", "status", "blocked_reasons", "sources", "evidence"})
        source_names = frozenset({"rollout_identity", "process_exit_proof", "validator_receipt"})
        all_verified = True
        for row_value in rows:
            row = _mapping(row_value, "report.seed_matrix row")
            _reject_unknown(row, row_keys, "report.seed_matrix row")
            if row.get("status") not in {"missing", "independently_verified"}:
                _fail("report.seed_matrix row has an invalid status")
            reasons = row.get("blocked_reasons")
            if not isinstance(reasons, list) or any(not isinstance(reason, str) or not reason for reason in reasons):
                _fail("report.seed_matrix row blocker shape is invalid")
            sources = _mapping(row.get("sources"), "report.seed_matrix.sources")
            _reject_unknown(sources, source_names, "report.seed_matrix.sources")
            for source_name in source_names:
                _validate_source_metadata(sources.get(source_name), f"report.seed_matrix.sources.{source_name}", require_opened=row.get("status") == "independently_verified")
            if row.get("status") == "independently_verified":
                if reasons:
                    _fail("verified seed row must not carry blocked reasons")
                evidence = _mapping(row.get("evidence"), "report.seed_matrix.evidence")
                normalized = _validate_report_seed_evidence(evidence, int(row["seed"]), "report.seed_matrix.evidence")
                nested_sources = normalized["source_metadata"]
                for source_name in source_names:
                    if dict(sources[source_name]) != dict(nested_sources[source_name]):
                        _fail(f"report.seed_matrix.sources.{source_name} drifts from nested evidence source metadata")
                if dict(report["training_matrix_source"]) != dict(nested_sources["training_matrix"]):
                    _fail("report.training_matrix_source drifts from nested evidence source metadata")
                if dict(report["terminal_matrix_source"]) != dict(nested_sources["terminal_matrix"]):
                    _fail("report.terminal_matrix_source drifts from nested evidence source metadata")
            else:
                all_verified = False
                if not reasons:
                    _fail("missing seed row must carry blocked reasons")
                if row.get("evidence") is not None:
                    _fail("blocked row must not carry evidence")
        if source_bound != all_verified:
            _fail("report.source_bound does not match the deeply validated three-seed evidence chain")
        checks = report.get("checks")
        expected_checks = ["three_seed_training_matrix", "full835_terminal_completion_matrix", "rollout_identity_envelopes", "process_exit_proofs", "independent_hdf5_validator_receipts", "external_scheduler_trust_anchor_witnesses", "one_shot_consume_witnesses", "runtime_gpu_terminal_identity_observations", "cross_file_path_sha_bytes_identity", "terminal_835_transitions_836_frames", "terminal_zero_credit_boundary"]
        if not isinstance(checks, list) or len(checks) != len(expected_checks) or [item.get("check") for item in checks if isinstance(item, Mapping)] != expected_checks:
            _fail("report.checks have an unexpected identity")
        for item in checks:
            check = _mapping(item, "report.check")
            _reject_unknown(check, frozenset({"check", "passed", "reason", "observed", "expected"}), "report.check")
            if type(check.get("passed")) is not bool:
                _fail("report.checks must contain boolean pass flags")
        if source_bound and any(item.get("passed") is not True for item in checks):
            _fail("verified report checks must all pass after evidence revalidation")
        blocked = report.get("blocked_reasons")
        if not isinstance(blocked, list) or any(not isinstance(reason, str) or not reason for reason in blocked):
            _fail("report.blocked_reasons must be a list of non-empty strings")
        if source_bound and blocked:
            _fail("verified report must not carry blocked reasons")
        if not source_bound and not blocked:
            _fail("report.blocked_reasons must be non-empty when blocked")
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
