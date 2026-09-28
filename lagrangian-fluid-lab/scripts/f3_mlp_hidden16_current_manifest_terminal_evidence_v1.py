#!/usr/bin/env python3
"""Fail-closed terminal-evidence intake for current-manifest F3 MLP rollouts.

This module is deliberately independent from the historical terminal runtime
verifier, the current-manifest training intake, and the current-manifest
rollout launcher.  It consumes only explicitly supplied, bounded JSON
projections:

* one current-manifest raw/canonical identity projection;
* one current-manifest training-evidence report; and
* six projections per seed: rollout plan, terminal process proof, evaluation
  identity, trajectory metadata, HDF5-validator receipt, and artifact
  identity.

Every JSON input is read through a single-link, no-symlink, bounded descriptor
and is hashed as bytes.  Referenced checkpoint, evaluation, trajectory,
validator, manifest, and training-receipt artifacts are only ``lstat``-ed for
regular-file/single-link/declared-size metadata; their contents are never
opened or hashed here.  The verifier never starts, stops, or restarts a
process, and never writes registry, ledger, matrix, denominator, gate, or
PLAN state.  A successful result is diagnostic-only and permanently
zero-credit.

No arguments means no input: the result is blocked fail-closed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

SCHEMA = "core.f3.mlp.hidden16.current_manifest_terminal_evidence.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-terminal-evidence-v1"
MANIFEST_SCHEMA = "core.f3.mlp.hidden16.current_manifest.identity_projection.v1"
TRAINING_SCHEMA = "core.f3.mlp.hidden16.current_manifest_training_evidence.v1"
PLAN_SCHEMA = "core.f3.mlp.hidden16.current_manifest_rollout_launcher_plan.v1"
TRAJECTORY_SCHEMA = "core.f3.mlp.hidden16.current_manifest.trajectory_metadata.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
PROCESS_SCHEMA_PREFIX = "core.f3.mlp.hidden16"
ARTIFACT_SCHEMA_PREFIX = "core.f3.mlp.hidden16"
EVALUATION_SCHEMA_PREFIX = "core.f3.mlp.hidden16"

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(
    r"^f3-mlp500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-(?P<date>20[0-9]{6})$"
)
NAMESPACE_RE = re.compile(
    r"^f3-mlp500-hidden16-currentmanifest-seed(17|29|43)-full835-"
    r"(?:(?:nonce(?P<legacy_nonce>[0-9a-f]{32}))|(?:"
    r"(?P<launcher_date>20[0-9]{6})-(?P<launcher_nonce>[0-9a-f]{32})))$"
)

ZERO_CREDIT_KEYS = (
    "formal",
    "formal_eligible",
    "T1_numerical",
    "T2_macro",
    "T2_path",
    "qualification",
)
ZERO_CREDIT_INT_KEYS = ("credit", "qualification_credit")

SOURCE_KEYS = frozenset(
    {"path", "bytes", "sha256", "opened", "schema", "lstat", "canonical_sha256"}
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})
CHECKPOINT_KEYS = frozenset({"schema", "path", "sha256", "bytes", "update"})


class IntakeError(ValueError):
    """Malformed, incomplete, unsafe, or drifting evidence."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
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
    if SHA256_RE.fullmatch(text) is None:
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


def _zero_credit(value: Mapping[str, Any], name: str, *, require_diagnostic: bool = True) -> None:
    if require_diagnostic:
        _exact(value, "diagnostic_only", True, name)
    elif "diagnostic_only" in value:
        _exact(value, "diagnostic_only", True, name)
    for key in ZERO_CREDIT_KEYS:
        if key in value:
            _exact(value, key, False, name)
    for key in ZERO_CREDIT_INT_KEYS:
        if key in value:
            _exact(value, key, 0, name)


def _absolute_path(value: Any, name: str, *, root: Path | None = None) -> Path:
    if isinstance(value, Path):
        raw = os.fspath(value)
        if not raw or "\x00" in raw:
            _fail(f"{name} must be a non-empty path")
    else:
        raw = _string(value, name)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        if root is None:
            _fail(f"{name} must be absolute")
        candidate = root / candidate
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a path alias component")
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    if normalized != "/" and normalized.endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return Path(normalized)


def _root_path(value: Path | str) -> Path:
    raw = os.path.abspath(os.fspath(value))
    path = _absolute_path(raw, "root")
    _reject_symlink_components(path, "root", allow_missing=False)
    return path


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _bounded_path(root: Path, value: Any, name: str) -> Path:
    path = _absolute_path(value, name, root=root)
    allowed = (root, Path("/tmp"))
    if not any(_under(path, item) for item in allowed):
        _fail(f"{name} escapes bounded root/tmp inputs")
    return path


def _reject_symlink_components(path: Path, name: str, *, allow_missing: bool) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor or os.curdir)
    parts = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing and index == len(parts) - 1:
                return
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} has a non-directory path component: {current}")


def _empty_source(value: Any) -> dict[str, Any]:
    return {
        "path": None if value is None else str(value),
        "bytes": None,
        "sha256": None,
        "opened": False,
        "schema": None,
        "lstat": None,
    }


def _read_bounded_json(
    root: Path,
    value: Any,
    *,
    name: str,
    max_bytes: int = MAX_JSON_BYTES,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    path = _bounded_path(root, value, name)
    if path.suffix.lower() != ".json":
        _fail(f"{name} must use the .json suffix")
    _reject_symlink_components(path, name, allow_missing=False)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"{name} cannot be opened: {error}")
    raw = b""
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} is not a regular file")
        if before.st_nlink != 1:
            _fail(f"{name} is not a single-link regular file")
        if before.st_size > max_bytes:
            _fail(f"{name} exceeds bounded JSON size {max_bytes}")
        while len(raw) <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - len(raw)))
            if not block:
                break
            raw += block
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_mode, before.st_nlink, before.st_size)
        if (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size) != identity:
            _fail(f"{name} changed while being read")
    except OSError as error:
        _fail(f"{name} cannot be read: {error}")
    finally:
        os.close(fd)
    if len(raw) > max_bytes:
        _fail(f"{name} exceeds bounded JSON size {max_bytes}")
    try:
        after_path = os.lstat(path)
    except OSError as error:
        _fail(f"{name} cannot be re-stated: {error}")
    if (
        after_path.st_dev,
        after_path.st_ino,
        after_path.st_mode,
        after_path.st_nlink,
        after_path.st_size,
    ) != identity:
        _fail(f"{name} changed after being read")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, IntakeError) as error:
        _fail(f"{name} is invalid bounded JSON: {error}")
    _walk_json(payload, name)
    payload = _mapping(payload, name)
    source = {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "opened": True,
        "schema": payload.get("schema"),
        "lstat": {
            "device": before.st_dev,
            "inode": before.st_ino,
            "mode": stat.S_IFMT(before.st_mode),
            "nlink": before.st_nlink,
            "bytes": before.st_size,
        },
    }
    return payload, source


def _stat_reference(root: Path, value: Any, declared_bytes: int, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    path = _bounded_path(root, value, name)
    if suffix is not None and path.suffix.lower() != suffix:
        _fail(f"{name} must use the {suffix} suffix")
    _reject_symlink_components(path, name, allow_missing=False)
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"{name} cannot be stated: {error}")
    if stat.S_ISLNK(info.st_mode):
        _fail(f"{name} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} is not a regular file")
    if info.st_nlink != 1:
        _fail(f"{name} is not a single-link regular file")
    if info.st_size != declared_bytes:
        _fail(f"{name}.bytes does not match lstat size")
    return {
        "path": str(path),
        "bytes": info.st_size,
        "opened": False,
        "lstat": {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IFMT(info.st_mode),
            "nlink": info.st_nlink,
        },
    }


def _artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, ARTIFACT_KEYS, name)
    path = _string(item.get("path"), f"{name}.path")
    _absolute_path(path, f"{name}.path")
    if suffix is not None and not path.lower().endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    size = _int(item.get("bytes"), f"{name}.bytes", 1)
    if size > (1 << 50):
        _fail(f"{name}.bytes exceeds declared bound")
    return {"path": path, "sha256": _sha(item.get("sha256"), f"{name}.sha256"), "bytes": size}


def _checkpoint(value: Any, name: str) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, CHECKPOINT_KEYS, name)
    _exact(item, "schema", "core.checkpoint.v1", name)
    _exact(item, "update", UPDATES, name)
    artifact = _artifact(
        {"path": item.get("path"), "sha256": item.get("sha256"), "bytes": item.get("bytes")},
        name,
        suffix=".pt",
    )
    return {"schema": "core.checkpoint.v1", **artifact, "update": UPDATES}


def _checkpoint_artifact(value: Any, name: str) -> dict[str, Any]:
    """Normalize terminal receipts whose legacy identity omits checkpoint schema."""
    item = _mapping(value, name)
    _unknown(item, frozenset({"schema", "path", "sha256", "bytes", "update"}), name)
    if "schema" in item:
        _exact(item, "schema", "core.checkpoint.v1", name)
    if "update" in item:
        _exact(item, "update", UPDATES, name)
    return _artifact(
        {"path": item.get("path"), "sha256": item.get("sha256"), "bytes": item.get("bytes")},
        name,
        suffix=".pt",
    )


def _validate_run_id(value: Any, seed: int, name: str) -> str:
    run_id = _string(value, name)
    match = RUN_ID_RE.fullmatch(run_id)
    if match is None or int(match.group(1)) != seed:
        _fail(f"{name} is not a current-manifest MLP hidden16 seed{seed} run ID")
    return run_id


def _validate_nonce(value: Any, name: str) -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name} must be a 32-character lowercase hex nonce")
    return nonce


def _validate_namespace(value: Any, seed: int, nonce: str, run_id: str, name: str) -> str:
    namespace = _string(value, name)
    _absolute_path(namespace, name)
    basename = Path(namespace).name
    match = NAMESPACE_RE.fullmatch(basename)
    if match is None or int(match.group(1)) != seed:
        _fail(f"{name} is not bound to seed{seed}, full835, and namespace nonce")
    matched_nonce = match.group("legacy_nonce") or match.group("launcher_nonce")
    if matched_nonce != nonce:
        _fail(f"{name} is not bound to seed{seed}, full835, and namespace nonce")
    namespace_date = match.group("launcher_date")
    if namespace_date is not None:
        run_match = RUN_ID_RE.fullmatch(run_id)
        if run_match is None or namespace_date != run_match.group("date"):
            _fail(f"{name} date is not bound to run ID")
    if any(word in basename for word in ("running", "partial", "pending", "legacy")):
        _fail(f"{name} contains a non-terminal namespace marker")
    return namespace


def _expected_process_filename(run_id: str, nonce: str, manifest_sha256: str) -> str:
    digest = hashlib.sha256(f"{run_id}\0{nonce}\0{manifest_sha256}".encode("utf-8")).hexdigest()[:32]
    return f"F3-MLP-HIDDEN16-CURRENT-MANIFEST-{digest}-PROCESS-EXIT-PROOF-V1.json"


def _manifest_projection(payload: Mapping[str, Any], root: Path, name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "source_bound", "diagnostic_only", "formal",
        "formal_eligible", "T1_numerical", "T2_macro", "T2_path",
        "qualification", "qualification_credit", "credit", "manifest",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", MANIFEST_SCHEMA, name)
    _exact(payload, "status", "bound", name)
    _exact(payload, "source_bound", True, name)
    _zero_credit(payload, name)
    manifest = _mapping(payload.get("manifest"), f"{name}.manifest")
    _unknown(manifest, frozenset({"raw", "canonical"}), f"{name}.manifest")
    raw = _mapping(manifest.get("raw"), f"{name}.manifest.raw")
    _unknown(raw, frozenset({"path", "sha256", "bytes"}), f"{name}.manifest.raw")
    raw_path = _string(raw.get("path"), f"{name}.manifest.raw.path")
    raw_bytes = _int(raw.get("bytes"), f"{name}.manifest.raw.bytes", 1)
    raw_sha = _sha(raw.get("sha256"), f"{name}.manifest.raw.sha256")
    _stat_reference(root, raw_path, raw_bytes, f"{name}.manifest.raw", suffix=".json")
    canonical = _mapping(manifest.get("canonical"), f"{name}.manifest.canonical")
    _unknown(canonical, frozenset({"sha256"}), f"{name}.manifest.canonical")
    canonical_sha = _sha(canonical.get("sha256"), f"{name}.manifest.canonical.sha256")
    return {
        "raw": {"path": raw_path, "sha256": raw_sha, "bytes": raw_bytes},
        "canonical": {"sha256": canonical_sha},
    }


def _source_identity(value: Any, name: str, *, suffix: str = ".json") -> dict[str, Any]:
    source = _mapping(value, name)
    _unknown(source, SOURCE_KEYS, name)
    path = _string(source.get("path"), f"{name}.path")
    _absolute_path(path, f"{name}.path")
    if not path.lower().endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    return {
        "path": path,
        "bytes": _int(source.get("bytes"), f"{name}.bytes", 1),
        "sha256": _sha(source.get("sha256"), f"{name}.sha256"),
    }


def _validate_training(
    payload: Mapping[str, Any],
    root: Path,
    manifest: Mapping[str, Any],
    name: str,
) -> dict[int, dict[str, Any]]:
    allowed = frozenset({
        "schema", "report_id", "observed_at_utc", "status", "fail_closed",
        "source_bound", "diagnostic_only", "formal", "formal_eligible",
        "T1_numerical", "T2_macro", "T2_path", "qualification", "credit",
        "qualification_credit", "formal_training_runs_counted",
        "t1_case_runs_counted", "t2_macro_families_counted", "model", "hidden",
        "updates", "seeds", "manifest", "runs", "checks", "errors", "authorization",
        "input_boundary", "side_effects", "scope_note",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "status", "diagnostic_bound", name)
    _exact(payload, "fail_closed", False, name)
    _exact(payload, "source_bound", True, name)
    _zero_credit(payload, name)
    _exact(payload, "model", MODEL, name)
    _exact(payload, "hidden", HIDDEN, name)
    _exact(payload, "updates", UPDATES, name)
    _exact(payload, "seeds", list(SEEDS), name)
    # The current training intake emits ``errors: []``; older diagnostic
    # fixtures may omit the optional envelope field. If present, it must be
    # empty so a rejected training report can never be promoted here.
    if "errors" in payload:
        _exact(payload, "errors", [], name)
    training_manifest = _mapping(payload.get("manifest"), f"{name}.manifest")
    _unknown(training_manifest, frozenset({"path", "bytes", "sha256", "opened", "schema", "canonical_sha256"}), f"{name}.manifest")
    training_raw = _source_identity(training_manifest, f"{name}.manifest", suffix=".json")
    _exact(training_manifest, "opened", True, f"{name}.manifest")
    training_canonical = _sha(training_manifest.get("canonical_sha256"), f"{name}.manifest.canonical_sha256")
    if training_raw["path"] != manifest["raw"]["path"] or training_raw["sha256"] != manifest["raw"]["sha256"] or training_raw["bytes"] != manifest["raw"]["bytes"]:
        _fail(f"{name}.manifest raw identity drifts from current-manifest identity")
    if training_canonical != manifest["canonical"]["sha256"]:
        _fail(f"{name}.manifest canonical identity drifts from current-manifest identity")
    _stat_reference(root, training_raw["path"], training_raw["bytes"], f"{name}.manifest")
    authorization = _mapping(payload.get("authorization"), f"{name}.authorization")
    _unknown(authorization, frozenset({*ZERO_CREDIT_KEYS, *ZERO_CREDIT_INT_KEYS}), f"{name}.authorization")
    _zero_credit(authorization, f"{name}.authorization", require_diagnostic=False)
    for key in ZERO_CREDIT_KEYS:
        _exact(authorization, key, False, f"{name}.authorization")
    for key in ZERO_CREDIT_INT_KEYS:
        _exact(authorization, key, 0, f"{name}.authorization")
    rows = payload.get("runs")
    if not isinstance(rows, list) or len(rows) != len(SEEDS):
        _fail(f"{name}.runs must contain exactly three rows")
    result: dict[int, dict[str, Any]] = {}
    for row_value in rows:
        row = _mapping(row_value, f"{name}.run")
        _unknown(row, frozenset({"seed", "status", "source", "blocked_reasons", "evidence"}), f"{name}.run")
        seed = _int(row.get("seed"), f"{name}.run.seed")
        if seed not in SEEDS or seed in result:
            _fail(f"{name}.runs contains an invalid or duplicate seed")
        _exact(row, "status", "bound", f"{name}.seed{seed}")
        if row.get("blocked_reasons") != []:
            _fail(f"{name}.seed{seed}.blocked_reasons must be empty")
        source = _source_identity(row.get("source"), f"{name}.seed{seed}.source")
        _exact(row["source"], "opened", True, f"{name}.seed{seed}.source")
        _exact(row["source"], "schema", "core.training.v1", f"{name}.seed{seed}.source")
        _stat_reference(root, source["path"], source["bytes"], f"{name}.seed{seed}.source")
        evidence = _mapping(row.get("evidence"), f"{name}.seed{seed}.evidence")
        _unknown(evidence, frozenset({
            "seed", "run_id", "schema", "model", "hidden", "updates", "completed",
            "manifest_sha256", "receipt_identity", "checkpoint_identity", "zero_credit",
        }), f"{name}.seed{seed}.evidence")
        _exact(evidence, "seed", seed, f"{name}.seed{seed}.evidence")
        _exact(evidence, "schema", "core.training.v1", f"{name}.seed{seed}.evidence")
        _exact(evidence, "model", MODEL, f"{name}.seed{seed}.evidence")
        _exact(evidence, "hidden", HIDDEN, f"{name}.seed{seed}.evidence")
        _exact(evidence, "updates", UPDATES, f"{name}.seed{seed}.evidence")
        _exact(evidence, "completed", True, f"{name}.seed{seed}.evidence")
        run_id = _validate_run_id(evidence.get("run_id"), seed, f"{name}.seed{seed}.run_id")
        _exact(evidence, "manifest_sha256", manifest["canonical"]["sha256"], f"{name}.seed{seed}.evidence")
        receipt = _source_identity(evidence.get("receipt_identity"), f"{name}.seed{seed}.receipt_identity")
        checkpoint = _checkpoint(evidence.get("checkpoint_identity"), f"{name}.seed{seed}.checkpoint_identity")
        zero = _mapping(evidence.get("zero_credit"), f"{name}.seed{seed}.zero_credit")
        _unknown(zero, frozenset({"diagnostic_only", *ZERO_CREDIT_KEYS, "credit"}), f"{name}.seed{seed}.zero_credit")
        _zero_credit(zero, f"{name}.seed{seed}.zero_credit")
        _exact(zero, "credit", 0, f"{name}.seed{seed}.zero_credit")
        if source != receipt:
            _fail(f"{name}.seed{seed}.receipt identity drifts from row source")
        _stat_reference(root, receipt["path"], receipt["bytes"], f"{name}.seed{seed}.training_receipt")
        _stat_reference(root, checkpoint["path"], checkpoint["bytes"], f"{name}.seed{seed}.checkpoint", suffix=".pt")
        result[seed] = {
            "seed": seed,
            "run_id": run_id,
            "manifest_sha256": manifest["canonical"]["sha256"],
            "training_receipt": receipt,
            "checkpoint": checkpoint,
        }
    if set(result) != set(SEEDS):
        _fail(f"{name}.runs does not contain the exact seed set")
    if len({item["run_id"] for item in result.values()}) != len(SEEDS):
        _fail(f"{name} contains duplicate run IDs")
    if len({(item["training_receipt"]["path"], item["training_receipt"]["sha256"]) for item in result.values()}) != len(SEEDS):
        _fail(f"{name} contains duplicate training receipt identities")
    if len({(item["checkpoint"]["path"], item["checkpoint"]["sha256"]) for item in result.values()}) != len(SEEDS):
        _fail(f"{name} contains duplicate checkpoint identities")
    return result


def _command_value(command: list[str], flag: str, name: str) -> str:
    positions = [index for index, item in enumerate(command) if item == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        _fail(f"{name} must contain exactly one {flag} value")
    return _string(command[positions[0] + 1], f"{name}.{flag}")


def _validate_plan(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    root: Path,
    manifest: Mapping[str, Any],
    training: Mapping[str, Any],
    seed: int,
    name: str,
) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "mode", "launched", "seed", "run_id", "model", "hidden",
        "updates", "case_id", "split", "transitions", "frames", "gpu_index", "manifest",
        "manifest_sha256", "manifest_file_sha256", "checkpoint", "training_receipt",
        "training_receipt_sha256", "output_namespace", "namespace_nonce", "command", "cwd",
        "env_overrides", "command_sha256", "outputs", "trajectory_metadata",
        "process_proof_filename", "diagnostic_only", *ZERO_CREDIT_KEYS, *ZERO_CREDIT_INT_KEYS,
        "zero_credit_only", "side_effects", "input_boundary",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", PLAN_SCHEMA, name)
    _exact(payload, "status", "dry_run_ready", name)
    _exact(payload, "mode", "dry_run", name)
    _exact(payload, "launched", False, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "model", MODEL, name)
    _exact(payload, "hidden", HIDDEN, name)
    _exact(payload, "updates", UPDATES, name)
    _exact(payload, "case_id", CASE_ID, name)
    _exact(payload, "split", SPLIT, name)
    _exact(payload, "transitions", TRANSITIONS, name)
    _exact(payload, "frames", FRAMES, name)
    run_id = _validate_run_id(payload.get("run_id"), seed, f"{name}.run_id")
    if run_id != training["run_id"]:
        _fail(f"{name}.run_id drifts from training evidence")
    nonce = _validate_nonce(payload.get("namespace_nonce"), f"{name}.namespace_nonce")
    namespace = _validate_namespace(payload.get("output_namespace"), seed, nonce, run_id, f"{name}.output_namespace")
    _exact(payload, "manifest", manifest["raw"]["path"], name)
    _exact(payload, "manifest_sha256", manifest["canonical"]["sha256"], name)
    _exact(payload, "manifest_file_sha256", manifest["raw"]["sha256"], name)
    checkpoint = _checkpoint(payload.get("checkpoint"), f"{name}.checkpoint")
    if checkpoint != training["checkpoint"]:
        _fail(f"{name}.checkpoint identity drifts from training evidence")
    _exact(payload, "training_receipt", training["training_receipt"]["path"], name)
    _exact(payload, "training_receipt_sha256", training["training_receipt"]["sha256"], name)
    outputs = _mapping(payload.get("outputs"), f"{name}.outputs")
    _unknown(outputs, frozenset({"namespace", "evaluation", "trajectory", "progress", "log", "artifact_identity", "validator", "process_proof"}), f"{name}.outputs")
    expected_outputs = {
        "namespace": namespace,
        "evaluation": namespace + "-evaluation.json",
        "trajectory": namespace + "-trajectory.h5",
        "progress": namespace + "-evaluation-progress.json",
        "log": namespace + "-evaluation.log",
        "artifact_identity": namespace + "-artifact-identity.json",
        "validator": namespace + "-hdf5-validation.json",
        "process_proof": str(root / "reports" / _string(payload.get("process_proof_filename"), f"{name}.process_proof_filename")),
    }
    for key, expected in expected_outputs.items():
        _exact(outputs, key, expected, f"{name}.outputs")
    trajectory_metadata = namespace + "-trajectory-metadata.json"
    _exact(payload, "trajectory_metadata", trajectory_metadata, name)
    process_filename = Path(expected_outputs["process_proof"]).name
    expected_process_filename = _expected_process_filename(run_id, nonce, manifest["canonical"]["sha256"])
    if process_filename != expected_process_filename:
        _fail(f"{name}.process_proof_filename is not bound to run ID, nonce, and manifest identity")
    command_value = payload.get("command")
    if not isinstance(command_value, list) or not command_value or len(command_value) > 128:
        _fail(f"{name}.command must be a bounded non-empty array")
    command = [_string(item, f"{name}.command[{index}]") for index, item in enumerate(command_value)]
    if "--diagnostic" not in command or "--execute" in command:
        _fail(f"{name}.command must be diagnostic-only and non-executing")
    expected_flags = {
        "--manifest": manifest["raw"]["path"],
        "--data-root": str(root),
        "--checkpoint": checkpoint["path"],
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--trajectory-output": expected_outputs["trajectory"],
        "--progress-output": expected_outputs["progress"],
        "--output": expected_outputs["evaluation"],
    }
    for flag, expected in expected_flags.items():
        if _command_value(command, flag, f"{name}.command") != expected:
            _fail(f"{name}.command {flag} drifts from the bound plan")
    cwd = _absolute_path(payload.get("cwd"), f"{name}.cwd")
    if cwd != root:
        _fail(f"{name}.cwd drifts from root")
    env = _mapping(payload.get("env_overrides"), f"{name}.env_overrides")
    for key, value in env.items():
        _string(key, f"{name}.env_overrides.key")
        _string(value, f"{name}.env_overrides.{key}")
    if env.get("PYTHONDONTWRITEBYTECODE") != "1" or not re.fullmatch(r"[0-7]", env.get("CUDA_VISIBLE_DEVICES", "")):
        _fail(f"{name}.env_overrides is not the bounded diagnostic environment")
    command_identity = {"argv": command, "cwd": str(cwd), "env_overrides": dict(env)}
    expected_command_sha = hashlib.sha256(json.dumps(command_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    if _sha(payload.get("command_sha256"), f"{name}.command_sha256") != expected_command_sha:
        _fail(f"{name}.command_sha256 does not match command identity")
    _zero_credit(payload, name)
    _exact(payload, "zero_credit_only", True, name)
    side_effects = _mapping(payload.get("side_effects"), f"{name}.side_effects")
    _unknown(side_effects, frozenset({"processes_started", "processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "plan_writes"}), f"{name}.side_effects")
    for key in side_effects:
        _exact(side_effects, key, 0, f"{name}.side_effects")
    boundary = _mapping(payload.get("input_boundary"), f"{name}.input_boundary")
    _unknown(boundary, frozenset({"bounded_training_receipt_opened", "manifest_content_opened", "checkpoint_content_opened", "evaluation_content_opened", "trajectory_hdf5_opened", "runtime_started", "queue_submissions"}), f"{name}.input_boundary")
    _exact(boundary, "bounded_training_receipt_opened", True, f"{name}.input_boundary")
    # The launcher must read the manifest to bind its raw and canonical
    # identities into the dry-run plan. The terminal intake itself remains
    # projection/lstat-only; all heavyweight/runtime inputs stay unopened.
    _exact(boundary, "manifest_content_opened", True, f"{name}.input_boundary")
    for key in ("checkpoint_content_opened", "evaluation_content_opened", "trajectory_hdf5_opened", "runtime_started"):
        _exact(boundary, key, False, f"{name}.input_boundary")
    _exact(boundary, "queue_submissions", 0, f"{name}.input_boundary")
    _stat_reference(root, checkpoint["path"], checkpoint["bytes"], f"{name}.checkpoint", suffix=".pt")
    _stat_reference(root, training["training_receipt"]["path"], training["training_receipt"]["bytes"], f"{name}.training_receipt")
    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": nonce,
        "manifest_sha256": manifest["canonical"]["sha256"],
        "training_receipt_sha256": training["training_receipt"]["sha256"],
        "checkpoint": checkpoint,
        "outputs": expected_outputs,
        "trajectory_metadata": trajectory_metadata,
        "command_sha256": expected_command_sha,
        "source_path": source.get("path"),
    }


def _validate_common_terminal_fields(payload: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> None:
    _exact(payload, "seed", plan["seed"], name)
    _exact(payload, "run_id", plan["run_id"], name)
    _exact(payload, "model", MODEL, name)
    _exact(payload, "hidden", HIDDEN, name)
    _exact(payload, "updates", UPDATES, name)
    _exact(payload, "case_id", CASE_ID, name)
    _exact(payload, "split", SPLIT, name)
    _exact(payload, "transitions", TRANSITIONS, name)
    _exact(payload, "frames", FRAMES, name)
    _exact(payload, "manifest_sha256", plan["manifest_sha256"], name)
    _exact(payload, "training_manifest_sha256", plan["manifest_sha256"], name)
    _exact(payload, "training_receipt_sha256", plan["training_receipt_sha256"], name)
    _exact(payload, "namespace", plan["namespace"], name)
    _exact(payload, "namespace_nonce", plan["namespace_nonce"], name)
    _zero_credit(payload, name)


def _validate_evaluation_identity(payload: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "source_bound", "diagnostic_only", "formal", "formal_eligible",
        "T1_numerical", "T2_macro", "T2_path", "qualification", "credit", "qualification_credit",
        "seed", "run_id", "model", "hidden", "updates", "case_id", "split", "transitions", "frames",
        "manifest_sha256", "training_manifest_sha256", "training_receipt_sha256", "namespace", "namespace_nonce",
        "checkpoint", "evaluation", "result",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", f"{EVALUATION_SCHEMA_PREFIX}.seed{plan['seed']}.evaluation_identity.v1", name)
    _exact(payload, "status", "completed", name)
    _exact(payload, "source_bound", True, name)
    _validate_common_terminal_fields(payload, plan, name)
    checkpoint = _checkpoint(payload.get("checkpoint"), f"{name}.checkpoint")
    if checkpoint != plan["checkpoint"]:
        _fail(f"{name}.checkpoint identity drifts from rollout plan")
    evaluation = _artifact(payload.get("evaluation"), f"{name}.evaluation", suffix=".json")
    if evaluation["path"] != plan["outputs"]["evaluation"]:
        _fail(f"{name}.evaluation path drifts from rollout plan")
    result = _mapping(payload.get("result"), f"{name}.result")
    _unknown(result, frozenset({"status", "finite_rollout_complete", "execution_complete", "requested_window_complete", "transitions_executed", "trajectory_frames_including_initial", "future_state_inputs", "failure_category"}), f"{name}.result")
    for key, expected in (("status", "completed"), ("finite_rollout_complete", True), ("execution_complete", True), ("requested_window_complete", True), ("transitions_executed", TRANSITIONS), ("trajectory_frames_including_initial", FRAMES), ("future_state_inputs", False), ("failure_category", None)):
        _exact(result, key, expected, f"{name}.result")
    _stat_reference(Path(plan["source_root"]), evaluation["path"], evaluation["bytes"], f"{name}.evaluation", suffix=".json")
    return {"checkpoint": checkpoint, "evaluation": evaluation}


def _validate_trajectory_metadata(payload: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "status", "source_bound", "seed", "run_id", "model", "hidden", "updates",
        "case_id", "split", "transitions", "frames", "namespace", "namespace_nonce", "trajectory",
        "stream_hash", "future_state_inputs", "diagnostic_only", *ZERO_CREDIT_KEYS, *ZERO_CREDIT_INT_KEYS,
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", TRAJECTORY_SCHEMA, name)
    if "status" in payload:
        _exact(payload, "status", "completed", name)
    _exact(payload, "source_bound", True, name)
    for key, expected in (
        ("seed", plan["seed"]),
        ("run_id", plan["run_id"]),
        ("model", MODEL),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("namespace", plan["namespace"]),
        ("namespace_nonce", plan["namespace_nonce"]),
    ):
        _exact(payload, key, expected, name)
    _zero_credit(payload, name)
    _exact(payload, "future_state_inputs", False, name)
    trajectory = _artifact(payload.get("trajectory"), f"{name}.trajectory", suffix=".h5")
    if trajectory["path"] != plan["outputs"]["trajectory"]:
        _fail(f"{name}.trajectory path drifts from rollout plan")
    stream = _mapping(payload.get("stream_hash"), f"{name}.stream_hash")
    _unknown(stream, frozenset({"algorithm", "sha256", "bytes"}), f"{name}.stream_hash")
    _exact(stream, "algorithm", "sha256", f"{name}.stream_hash")
    _exact(stream, "sha256", trajectory["sha256"], f"{name}.stream_hash")
    _exact(stream, "bytes", trajectory["bytes"], f"{name}.stream_hash")
    _stat_reference(Path(plan["source_root"]), trajectory["path"], trajectory["bytes"], f"{name}.trajectory", suffix=".h5")
    return {"trajectory": trajectory}


def _validate_validator(payload: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "passed", "fail_closed", "diagnostic_only", "synthetic_only",
        "production_artifacts_touched", "qualification_credit", "case_id", "evaluation_json",
        "trajectory_hdf5", "expected_transitions", "frames_executed", "complete", "incomplete",
        "failure_category", "checks", "row_fields_checked",
    })
    _unknown(payload, allowed, name)
    _exact(payload, "schema", VALIDATOR_SCHEMA, name)
    for key, expected in (("passed", True), ("fail_closed", False), ("diagnostic_only", True), ("synthetic_only", False), ("production_artifacts_touched", False), ("qualification_credit", 0), ("case_id", CASE_ID), ("expected_transitions", TRANSITIONS), ("frames_executed", TRANSITIONS), ("complete", True), ("incomplete", False), ("failure_category", None)):
        _exact(payload, key, expected, name)
    _exact(payload, "evaluation_json", plan["outputs"]["evaluation"], name)
    _exact(payload, "trajectory_hdf5", plan["outputs"]["trajectory"], name)
    checks = _mapping(payload.get("checks"), f"{name}.checks")
    _unknown(checks, frozenset({"case_binding", "shape", "time", "valid", "future_state_inputs", "completion_semantics", "trajectory_frames", "trajectory_transitions", "particle_count", "time_start", "time_end", "executed_frame_count", "tail_frame_count"}), f"{name}.checks")
    for key, expected in (("case_binding", True), ("shape", True), ("time", True), ("valid", True), ("future_state_inputs", True), ("completion_semantics", True), ("trajectory_frames", FRAMES), ("trajectory_transitions", TRANSITIONS), ("executed_frame_count", FRAMES), ("tail_frame_count", 0)):
        _exact(checks, key, expected, f"{name}.checks")
    rows = payload.get("row_fields_checked")
    if not isinstance(rows, list) or not rows or any(not isinstance(item, str) or not item for item in rows):
        _fail(f"{name}.row_fields_checked must be a non-empty string list")
    return {"evaluation": plan["outputs"]["evaluation"], "trajectory": plan["outputs"]["trajectory"]}


def _validate_process(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    plan: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    allowed = frozenset({
        "schema", "report_id", "status", "source_bound", "diagnostic_only", *ZERO_CREDIT_KEYS,
        *ZERO_CREDIT_INT_KEYS, "seed", "run_id", "namespace", "namespace_nonce", "evaluator_alive",
        "launcher_alive", "evaluator_returncode", "launcher_returncode", "returncode",
        "evaluator_pid_observed", "launcher_pid_observed", "evaluator_reaped", "launcher_reaped",
        "command_sha256", "exit_proof_sha256", "evaluator_start_identity", "evaluator_end_identity",
        "launcher_start_identity", "launcher_end_identity", "manifest_sha256", "training_manifest_sha256",
        "training_receipt_sha256", "checkpoint", "evaluation", "trajectory", "validator",
    })
    _unknown(payload, allowed, name)
    expected_schema = f"{PROCESS_SCHEMA_PREFIX}.seed{plan['seed']}.process_exit_proof.v1"
    current_schema = f"{PROCESS_SCHEMA_PREFIX}.current_manifest.seed{plan['seed']}.process_exit_proof.v1"
    if payload.get("schema") not in {expected_schema, current_schema}:
        _fail(f"{name}.schema is not a supported current-manifest process proof")
    report_id = _string(payload.get("report_id"), f"{name}.report_id")
    if f"seed{plan['seed']}" not in report_id or plan["namespace_nonce"] not in report_id:
        _fail(f"{name}.report_id is not bound to seed and namespace nonce")
    _exact(payload, "status", "exited_successfully", name)
    _exact(payload, "source_bound", True, name)
    _validate_common_terminal_fields({**payload, "model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES}, plan, name)
    if source.get("path") != plan["outputs"]["process_proof"]:
        _fail(f"{name} source path drifts from rollout plan")
    for key, expected in (("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0), ("evaluator_reaped", True), ("launcher_reaped", True)):
        _exact(payload, key, expected, name)
    evaluator_pid = _int(payload.get("evaluator_pid_observed"), f"{name}.evaluator_pid_observed", 1)
    launcher_pid = _int(payload.get("launcher_pid_observed"), f"{name}.launcher_pid_observed", 1)
    _sha(payload.get("command_sha256"), f"{name}.command_sha256")
    if payload["command_sha256"] != plan["command_sha256"]:
        _fail(f"{name}.command_sha256 drifts from rollout plan")
    without_digest = dict(payload)
    proof_digest = without_digest.pop("exit_proof_sha256", None)
    if _sha(proof_digest, f"{name}.exit_proof_sha256") != hashlib.sha256(json.dumps(without_digest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest():
        _fail(f"{name}.exit_proof_sha256 does not match proof identity")
    for field, expected_phase, expected_pid in (("evaluator_start_identity", "start", evaluator_pid), ("evaluator_end_identity", "end", evaluator_pid), ("launcher_start_identity", "start", launcher_pid), ("launcher_end_identity", "end", launcher_pid)):
        identity = _mapping(payload.get(field), f"{name}.{field}")
        _unknown(identity, frozenset({"phase", "pid", "proc_starttime_ticks", "observed_monotonic_ns", "returncode", "reaped"}), f"{name}.{field}")
        _exact(identity, "phase", expected_phase, f"{name}.{field}")
        _exact(identity, "pid", expected_pid, f"{name}.{field}")
        _int(identity.get("proc_starttime_ticks"), f"{name}.{field}.proc_starttime_ticks")
        _int(identity.get("observed_monotonic_ns"), f"{name}.{field}.observed_monotonic_ns")
    for field in ("evaluator_end_identity", "launcher_end_identity"):
        _exact(payload[field], "returncode", 0, f"{name}.{field}")
        _exact(payload[field], "reaped", True, f"{name}.{field}")
    _exact(payload["evaluator_start_identity"], "returncode", None, f"{name}.evaluator_start_identity") if "returncode" in payload["evaluator_start_identity"] else None
    _exact(payload["launcher_start_identity"], "returncode", None, f"{name}.launcher_start_identity") if "returncode" in payload["launcher_start_identity"] else None
    for key, expected in (("manifest_sha256", plan["manifest_sha256"]), ("training_manifest_sha256", plan["manifest_sha256"]), ("training_receipt_sha256", plan["training_receipt_sha256"])):
        _exact(payload, key, expected, name)
    checkpoint = _checkpoint_artifact(payload.get("checkpoint"), f"{name}.checkpoint")
    expected_checkpoint = {key: plan["checkpoint"][key] for key in ("path", "sha256", "bytes")}
    if checkpoint != expected_checkpoint:
        _fail(f"{name}.checkpoint identity drifts from rollout plan")
    identities: dict[str, dict[str, Any]] = {}
    for key, suffix, expected_path in (("evaluation", ".json", plan["outputs"]["evaluation"]), ("trajectory", ".h5", plan["outputs"]["trajectory"]), ("validator", ".json", plan["outputs"]["validator"])):
        artifact = _artifact(payload.get(key), f"{name}.{key}", suffix=suffix)
        if artifact["path"] != expected_path:
            _fail(f"{name}.{key} path drifts from rollout plan")
        identities[key] = artifact
    return {"evaluator_pid": evaluator_pid, "launcher_pid": launcher_pid, "checkpoint": checkpoint, **identities}


def _validate_artifact_identity(payload: Mapping[str, Any], source: Mapping[str, Any], plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    allowed = frozenset({"schema", "status", "seed", "run_id", "namespace", "namespace_nonce", "manifest_sha256", "training_manifest_sha256", "training_receipt_sha256", "checkpoint", "evaluation", "trajectory", "validator", "diagnostic_only", *ZERO_CREDIT_KEYS, *ZERO_CREDIT_INT_KEYS})
    _unknown(payload, allowed, name)
    expected_schema = f"{ARTIFACT_SCHEMA_PREFIX}.seed{plan['seed']}.evaluator_artifact_identity.v1"
    _exact(payload, "schema", expected_schema, name)
    _exact(payload, "status", "completed_diagnostic", name)
    _validate_common_terminal_fields({**payload, "model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES}, plan, name)
    if source.get("path") != plan["outputs"]["artifact_identity"]:
        _fail(f"{name} source path drifts from rollout plan")
    checkpoint = _checkpoint_artifact(payload.get("checkpoint"), f"{name}.checkpoint")
    expected_checkpoint = {key: plan["checkpoint"][key] for key in ("path", "sha256", "bytes")}
    if checkpoint != expected_checkpoint:
        _fail(f"{name}.checkpoint identity drifts from rollout plan")
    normalized: dict[str, Any] = {"checkpoint": checkpoint}
    for key, suffix, expected_path in (("evaluation", ".json", plan["outputs"]["evaluation"]), ("trajectory", ".h5", plan["outputs"]["trajectory"]), ("validator", ".json", plan["outputs"]["validator"])):
        artifact = _artifact(payload.get(key), f"{name}.{key}", suffix=suffix)
        if artifact["path"] != expected_path:
            _fail(f"{name}.{key} path drifts from rollout plan")
        normalized[key] = artifact
    return normalized


def _source_error(value: Any, error: str | None) -> str:
    if error:
        return error
    return f"fail-closed: missing projection: {value}"


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _zero_side_effects() -> dict[str, Any]:
    return {
        "processes_started": 0,
        "processes_stopped": 0,
        "processes_restarted": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "matrix_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
    }


def _input_boundary() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "projection_json_opened": True,
        "manifest_content_opened": False,
        "checkpoint_content_opened": False,
        "evaluation_content_opened": False,
        "trajectory_hdf5_opened": False,
        "artifact_content_opened": False,
        "runtime_started": False,
        "runtime_stopped": False,
        "runtime_restarted": False,
        "registry_read": False,
        "ledger_read": False,
        "matrix_read": False,
        "denominator_read": False,
        "gate_read": False,
        "plan_read": False,
    }


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest_identity_path: Path | str | None = None,
    training_evidence_path: Path | str | None = None,
    rollout_plan_paths: Mapping[int, Path | str] | None = None,
    process_proof_paths: Mapping[int, Path | str] | None = None,
    evaluation_identity_paths: Mapping[int, Path | str] | None = None,
    trajectory_metadata_paths: Mapping[int, Path | str] | None = None,
    validator_paths: Mapping[int, Path | str] | None = None,
    artifact_identity_paths: Mapping[int, Path | str] | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Read and bind all explicit projections without opening binary artifacts."""

    root_path = _root_path(root)
    errors: list[str] = []

    manifest_payload: Mapping[str, Any] | None = None
    manifest_source = _empty_source(manifest_identity_path)
    manifest_binding: dict[str, Any] | None = None
    if manifest_identity_path is None:
        errors.append("fail-closed: current-manifest identity projection is missing")
    else:
        try:
            manifest_payload, manifest_source = _read_bounded_json(root_path, manifest_identity_path, name="manifest identity")
            manifest_binding = _manifest_projection(manifest_payload, root_path, "manifest identity")
        except IntakeError as error:
            errors.append(str(error))

    training_payload: Mapping[str, Any] | None = None
    training_source = _empty_source(training_evidence_path)
    training_binding: dict[int, dict[str, Any]] = {}
    if training_evidence_path is None:
        errors.append("fail-closed: current-manifest training evidence report is missing")
    elif manifest_binding is None:
        errors.append("fail-closed: training evidence cannot bind without current-manifest identity")
    else:
        try:
            training_payload, training_source = _read_bounded_json(root_path, training_evidence_path, name="training evidence")
            training_binding = _validate_training(training_payload, root_path, manifest_binding, "training evidence")
        except IntakeError as error:
            errors.append(str(error))

    path_maps = {
        "rollout_plan": rollout_plan_paths or {},
        "process_exit_proof": process_proof_paths or {},
        "evaluation_identity": evaluation_identity_paths or {},
        "trajectory_metadata": trajectory_metadata_paths or {},
        "hdf5_validator": validator_paths or {},
        "artifact_identity": artifact_identity_paths or {},
    }
    for kind, mapping in path_maps.items():
        extra = set(mapping) - set(SEEDS)
        if extra:
            errors.append(f"fail-closed: {kind} contains invalid seed slots: {sorted(extra)}")

    loaded: dict[int, dict[str, tuple[Mapping[str, Any] | None, dict[str, Any], str | None]]] = {}
    for seed in SEEDS:
        loaded[seed] = {}
        for kind, mapping in path_maps.items():
            value = mapping.get(seed)
            if value is None:
                loaded[seed][kind] = (None, _empty_source(None), f"fail-closed: missing {kind} projection for seed{seed}")
                continue
            try:
                payload, source = _read_bounded_json(root_path, value, name=f"seed{seed} {kind}")
                loaded[seed][kind] = (payload, source, None)
            except IntakeError as error:
                loaded[seed][kind] = (None, _empty_source(value), str(error))

    rows: list[dict[str, Any]] = []
    valid_evidence: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "blocked",
            "blocked_reasons": [],
            "sources": {kind: source for kind, (_, source, _) in loaded[seed].items()},
            "evidence": None,
        }
        row_errors: list[str] = []
        if manifest_binding is None:
            row_errors.append("fail-closed: current-manifest identity is unavailable")
        if seed not in training_binding:
            row_errors.append(f"fail-closed: current-manifest training evidence for seed{seed} is unavailable")
        for kind, (_, _, error) in loaded[seed].items():
            if error:
                row_errors.append(error)
        try:
            if row_errors:
                raise IntakeError(row_errors[0])
            assert manifest_binding is not None
            training = training_binding[seed]
            plan_payload, plan_source, _ = loaded[seed]["rollout_plan"]
            process_payload, process_source, _ = loaded[seed]["process_exit_proof"]
            evaluation_payload, _, _ = loaded[seed]["evaluation_identity"]
            trajectory_payload, _, _ = loaded[seed]["trajectory_metadata"]
            validator_payload, validator_source, _ = loaded[seed]["hdf5_validator"]
            artifact_payload, artifact_source, _ = loaded[seed]["artifact_identity"]
            if any(item is None for item in (plan_payload, process_payload, evaluation_payload, trajectory_payload, validator_payload, artifact_payload)):
                _fail(f"seed{seed} terminal evidence is incomplete")
            assert plan_payload is not None and process_payload is not None and evaluation_payload is not None and trajectory_payload is not None and validator_payload is not None and artifact_payload is not None
            plan = _validate_plan(plan_payload, plan_source, root_path, manifest_binding, training, seed, f"seed{seed} rollout plan")
            plan["source_root"] = root_path
            process = _validate_process(process_payload, process_source, plan, f"seed{seed} process proof")
            evaluation = _validate_evaluation_identity(evaluation_payload, plan, f"seed{seed} evaluation identity")
            trajectory = _validate_trajectory_metadata(trajectory_payload, plan, f"seed{seed} trajectory metadata")
            validator = _validate_validator(validator_payload, plan, f"seed{seed} HDF5 validator")
            artifacts = _validate_artifact_identity(artifact_payload, artifact_source, plan, f"seed{seed} artifact identity")
            if loaded[seed]["trajectory_metadata"][1].get("path") != plan["trajectory_metadata"]:
                _fail(f"seed{seed} trajectory metadata source path drifts from rollout plan")
            if validator_source.get("path") != plan["outputs"]["validator"]:
                _fail(f"seed{seed} HDF5 validator source path drifts from rollout plan")
            if process["evaluation"] != evaluation["evaluation"] or process["trajectory"] != trajectory["trajectory"] or process["validator"] != artifacts["validator"]:
                _fail(f"seed{seed} process proof artifact identity drifts from terminal projections")
            if artifacts["evaluation"] != evaluation["evaluation"] or artifacts["trajectory"] != trajectory["trajectory"]:
                _fail(f"seed{seed} artifact identity drifts from evaluation or trajectory projection")
            if artifacts["validator"]["sha256"] != validator_source.get("sha256") or artifacts["validator"]["bytes"] != validator_source.get("bytes"):
                _fail(f"seed{seed} validator identity drifts from bounded validator projection bytes")
            _stat_reference(root_path, plan["outputs"]["evaluation"], evaluation["evaluation"]["bytes"], f"seed{seed} evaluation")
            _stat_reference(root_path, plan["outputs"]["trajectory"], trajectory["trajectory"]["bytes"], f"seed{seed} trajectory", suffix=".h5")
            _stat_reference(root_path, plan["outputs"]["validator"], artifacts["validator"]["bytes"], f"seed{seed} validator")
            if validator["evaluation"] != plan["outputs"]["evaluation"] or validator["trajectory"] != plan["outputs"]["trajectory"]:
                _fail(f"seed{seed} validator artifact paths drift from terminal identities")
            valid_evidence[seed] = {
                "seed": seed,
                "run_id": plan["run_id"],
                "namespace": plan["namespace"],
                "namespace_nonce": plan["namespace_nonce"],
                "checkpoint": plan["checkpoint"],
                "training_receipt": training["training_receipt"],
                "evaluation": evaluation["evaluation"],
                "trajectory": trajectory["trajectory"],
                "validator": artifacts["validator"],
                "artifact_identity": {"path": artifact_source["path"], "sha256": artifact_source["sha256"], "bytes": artifact_source["bytes"]},
                "process_proof": {"path": process_source["path"], "sha256": process_source["sha256"], "bytes": process_source["bytes"]},
            }
        except (IntakeError, AssertionError, KeyError, TypeError) as error:
            row_errors.append(str(error))
        if not row_errors:
            row["status"] = "terminal_verified"
            row["evidence"] = valid_evidence[seed]
        row["blocked_reasons"] = list(dict.fromkeys(row_errors))
        rows.append(row)
        errors.extend(row["blocked_reasons"])

    identity_unique = False
    if len(valid_evidence) == len(SEEDS):
        identity_unique = all(
            len({valid_evidence[seed][key] if key in {"run_id", "namespace", "namespace_nonce"} else (valid_evidence[seed][key]["path"], valid_evidence[seed][key]["sha256"]) for seed in SEEDS}) == len(SEEDS)
            for key in ("run_id", "namespace", "namespace_nonce", "checkpoint", "training_receipt", "evaluation", "trajectory", "validator")
        )
        if not identity_unique:
            errors.append("fail-closed: cross-seed terminal identities are duplicated")
    errors = list(dict.fromkeys(errors))
    verified = bool(manifest_binding) and len(training_binding) == len(SEEDS) and len(valid_evidence) == len(SEEDS) and identity_unique and not errors
    if not verified:
        for row in rows:
            if row["status"] == "terminal_verified":
                row["status"] = "blocked"
                row["blocked_reasons"].append("fail-closed: terminal evidence set did not bind as one complete set")
                row["blocked_reasons"] = list(dict.fromkeys(row["blocked_reasons"]))
        errors = list(dict.fromkeys(errors + [reason for row in rows for reason in row["blocked_reasons"]]))
    return {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": "terminal_diagnostic_verified" if verified else "blocked_fail_closed",
        "fail_closed": not verified,
        "source_bound": verified,
        "terminal_evidence_verified": verified,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seeds": list(SEEDS),
        "manifest_identity": {"source": manifest_source, "binding": manifest_binding},
        "training_evidence": {"source": training_source, "binding": bool(training_binding)},
        "seed_matrix": rows,
        "checks": [
            _check("manifest_identity_bound", manifest_binding is not None, "current-manifest raw/canonical identity is bound"),
            _check("training_evidence_bound", len(training_binding) == len(SEEDS), "all three current-manifest training rows are bound"),
            _check("exact_seed_set", len(rows) == len(SEEDS) and [row["seed"] for row in rows] == list(SEEDS), "exact seed set is 17, 29, 43", [row["seed"] for row in rows], list(SEEDS)),
            _check("terminal_projection_set", all(row["status"] == "terminal_verified" for row in rows), "every seed has six terminal projections"),
            _check("cross_seed_identity_unique", identity_unique, "run, nonce, checkpoint, receipt, and output identities are unique"),
            _check("zero_credit", True, "all accepted evidence remains diagnostic-only and zero-credit"),
            _check("content_boundary", True, "only bounded projection JSON and lstat metadata are used"),
        ],
        "blocked_reasons": errors,
        "input_boundary": _input_boundary(),
        "side_effects": _zero_side_effects(),
        "expected_contract": {
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "required_projections": ["manifest_identity", "training_evidence", "rollout_plan", "process_exit_proof", "evaluation_identity", "trajectory_metadata", "hdf5_validator", "artifact_identity"],
            "bounded_json_only": True,
            "zero_credit_only": True,
        },
        "interpretation": "This independent intake consumes explicit bounded JSON projections and lstat metadata only. It never opens checkpoint, evaluation, trajectory, or HDF5 content and never grants formal/T1/T2/qualification credit.",
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate the report envelope without opening any source file."""

    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _unknown(report, frozenset({
            "schema", "report_id", "observed_at_utc", "status", "fail_closed", "source_bound",
            "terminal_evidence_verified", "diagnostic_only", *ZERO_CREDIT_KEYS, *ZERO_CREDIT_INT_KEYS,
            "model", "hidden", "updates", "seeds", "manifest_identity", "training_evidence",
            "seed_matrix", "checks", "blocked_reasons", "input_boundary", "side_effects",
            "expected_contract", "interpretation",
        }), "report")
        _exact(report, "schema", SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "diagnostic_only", True, "report")
        _exact(report, "model", MODEL, "report")
        _exact(report, "hidden", HIDDEN, "report")
        _exact(report, "updates", UPDATES, "report")
        _exact(report, "seeds", list(SEEDS), "report")
        _zero_credit(report, "report")
        source_bound = report.get("source_bound") is True
        _exact(report, "terminal_evidence_verified", source_bound, "report")
        _exact(report, "status", "terminal_diagnostic_verified" if source_bound else "blocked_fail_closed", "report")
        _exact(report, "fail_closed", not source_bound, "report")
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or len(rows) != len(SEEDS) or [row.get("seed") for row in rows] != list(SEEDS):
            _fail("report.seed_matrix is not the exact ordered seed set")
        for row in rows:
            _mapping(row, "report.seed_matrix row")
            expected_status = "terminal_verified" if source_bound else "blocked"
            if row.get("status") != expected_status:
                _fail("report.seed_matrix status is inconsistent with report source_bound")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key in ("bounded_json_only", "projection_json_opened"):
            _exact(boundary, key, True, "report.input_boundary")
        for key in ("manifest_content_opened", "checkpoint_content_opened", "evaluation_content_opened", "trajectory_hdf5_opened", "artifact_content_opened", "runtime_started", "runtime_stopped", "runtime_restarted", "registry_read", "ledger_read", "matrix_read", "denominator_read", "gate_read", "plan_read"):
            _exact(boundary, key, False, "report.input_boundary")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in side_effects:
            _exact(side_effects, key, 0, "report.side_effects")
    except (IntakeError, KeyError, TypeError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def _write_new_report(report: Mapping[str, Any], root: Path, output: Path | str) -> Path:
    target = _bounded_path(root, output, "output")
    if target.parent != root / "reports":
        _fail("output must be a new file directly under root/reports")
    _reject_symlink_components(target.parent, "output parent", allow_missing=False)
    if os.path.lexists(target):
        _fail("output refuses overwrite")
    encoded = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags, 0o644)
    except OSError as error:
        _fail(f"output cannot be created: {error}")
    try:
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def _parse_seed_paths(values: Sequence[str], option: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} expects SEED=PATH")
        seed_text, path = value.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise ValueError(f"{option} has an invalid seed: {seed_text!r}") from error
        if seed not in SEEDS or seed in result:
            raise ValueError(f"{option} has an invalid or duplicate seed: {seed}")
        result[seed] = Path(path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest-identity", type=Path, default=None)
    parser.add_argument("--training-evidence", type=Path, default=None)
    parser.add_argument("--rollout-plan", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--process-exit-proof", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--evaluation-identity", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--trajectory-metadata", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--hdf5-validator", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--artifact-identity", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        maps = {
            "rollout_plan_paths": _parse_seed_paths(args.rollout_plan, "--rollout-plan"),
            "process_proof_paths": _parse_seed_paths(args.process_exit_proof, "--process-exit-proof"),
            "evaluation_identity_paths": _parse_seed_paths(args.evaluation_identity, "--evaluation-identity"),
            "trajectory_metadata_paths": _parse_seed_paths(args.trajectory_metadata, "--trajectory-metadata"),
            "validator_paths": _parse_seed_paths(args.hdf5_validator, "--hdf5-validator"),
            "artifact_identity_paths": _parse_seed_paths(args.artifact_identity, "--artifact-identity"),
        }
        report = build_report(
            args.root,
            manifest_identity_path=args.manifest_identity,
            training_evidence_path=args.training_evidence,
            **maps,
        )
        validation_errors = validate_report(report)
        if validation_errors:
            report["status"] = "blocked_fail_closed"
            report["fail_closed"] = True
            report["source_bound"] = False
            report["terminal_evidence_verified"] = False
            report["blocked_reasons"] = list(dict.fromkeys(list(report.get("blocked_reasons", [])) + validation_errors))
        output = None
        if args.output is not None:
            output = str(_write_new_report(report, _root_path(args.root), args.output))
        print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "credit": 0, "output": output}, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "terminal_diagnostic_verified" else 2
    except (IntakeError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "source_bound": False, "credit": 0, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
