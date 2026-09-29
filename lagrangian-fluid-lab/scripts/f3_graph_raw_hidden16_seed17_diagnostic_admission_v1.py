#!/usr/bin/env python3
"""Receipt-bound, diagnostic-only admission for the graph_raw seed17 canary.

This module is deliberately narrower than a production scheduler.  It can
mint one bounded, zero-credit receipt and consume it once.  The receipt binds
the current manifest, training receipt, checkpoint bytes, core-learning
source, validator sources, GPU-2 resource snapshot, exact evaluator argv,
the full835 identity, and an exclusive namespace marker.  Consumption is an
atomic filesystem event; a second consumer is rejected.

No solver, worker, queue, registry, ledger, denominator, gate, completion,
or PLAN state is read or written.  This contract never starts a process.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_current_manifest_audited_executor_v1 as resource
from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as launcher


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 17
GPU_INDEX = 2
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA

SCHEMA = "core.f3.graph_raw.hidden16.seed17.diagnostic_admission.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
CONSUMED_SCHEMA = f"{SCHEMA}.consumed"
REPORT_ID = "f3-graph-raw-hidden16-seed17-diagnostic-admission-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING = Path(
    "/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
)
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-SEED17-DIAGNOSTIC-ADMISSION-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

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

SOURCE_RELATIVE_PATHS = {
    "core_learning": Path("scripts/core_learning.py"),
    "hdf5_validator": Path("scripts/f3_full_rollout_receipt_hdf5_validator_v1.py"),
    "hardened_validator": Path("scripts/f3_graph_terminal_validator_security_hardening_v1.py"),
    "terminal_artifact_validator": Path(
        "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py"
    ),
}


class AdmissionError(ValueError):
    """Malformed, drifting, reused, or unsafe diagnostic admission."""


def _fail(message: str) -> None:
    raise AdmissionError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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
        _fail(f"{name} must be boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256")
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
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


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
        _fail(f"{name} exceeds maximum depth")
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


def _absolute(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    normalized = Path(os.path.normpath(str(path)))
    if normalized != path:
        _fail(f"{name} uses a lexical path alias")
    return path


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
            _fail(f"{name} has a missing component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _read_file(path: Path | str, name: str, *, max_bytes: int, parse_json: bool = False) -> tuple[bytes, dict[str, Any], dict[str, Any] | None]:
    candidate = _absolute(path, name)
    _reject_symlink_components(candidate, name)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if before.st_size < 1 or before.st_size > max_bytes:
        _fail(f"{name} is outside the bounded size")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name} without following links: {error}")
    chunks: list[bytes] = []
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            _fail(f"{name} changed before read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != identity or total != before.st_size:
            _fail(f"{name} changed during read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after read: {error}")
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity:
        _fail(f"{name} changed after read")
    raw = b"".join(chunks)
    descriptor = {
        "path": str(candidate),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": int(len(raw)),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "uid": int(before.st_uid),
        "gid": int(before.st_gid),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
    }
    payload: dict[str, Any] | None = None
    if parse_json:
        try:
            loaded = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, AdmissionError, RecursionError) as error:
            _fail(f"invalid {name}: {error}")
        _walk_json(loaded, name)
        payload = dict(_mapping(loaded, name))
    return raw, descriptor, payload


def _write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> dict[str, Any]:
    path = _absolute(path, "exclusive output")
    _reject_symlink_components(path.parent, "exclusive output parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail(f"refusing to overwrite existing file: {path}")
    except OSError as error:
        _fail(f"cannot write exclusive file {path}: {error}")
    info = os.lstat(path)
    if stat.S_IMODE(info.st_mode) != mode or info.st_uid != os.getuid() or info.st_gid != os.getgid():
        _fail(f"exclusive file {path} owner/mode drifted")
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


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("nonce must be a non-zero lowercase 32-hex value")
    return nonce


def _namespace(output_root: Path | str, nonce: str) -> Path:
    root = _absolute(output_root, "output_root")
    temp = Path(tempfile.gettempdir()).resolve()
    if not _under(root, temp):
        _fail("output_root must remain under /tmp")
    return root / f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{nonce}"


def _source_descriptor(root: Path, relative: Path, name: str) -> dict[str, Any]:
    path = root / relative
    if not _under(path, root):
        _fail(f"{name} escapes the lab root")
    _raw, descriptor, _ = _read_file(path, name, max_bytes=MAX_SOURCE_BYTES)
    return descriptor


def _checkpoint_descriptor(path: Path) -> dict[str, Any]:
    _raw, descriptor, _ = _read_file(path, "checkpoint", max_bytes=MAX_CHECKPOINT_BYTES)
    return descriptor


def _validate_resource(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    _exact(payload, "schema", resource.ADMISSION_SCHEMA, "resource_admission")
    _exact(payload, "gpu_index", GPU_INDEX, "resource_admission")
    _bool(payload.get("admitted"), "resource_admission.admitted")
    if not payload["admitted"]:
        _fail("GPU2 resource snapshot is not admitted")
    gpu = _mapping(payload.get("gpu"), "resource_admission.gpu")
    for key in ("total_mib", "used_mib", "free_mib"):
        _int(gpu.get(key), f"resource_admission.gpu.{key}")
    if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"]:
        _fail("GPU2 used/free VRAM exceeds total VRAM")
    return payload


def _command_digest(argv: Sequence[str], cwd: str, env: Mapping[str, str]) -> str:
    return canonical_digest({"argv": list(argv), "cwd": cwd, "env_overrides": dict(env), "gpu_index": GPU_INDEX, "seed": SEED, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES})


def _identity_core(
    *,
    root: Path,
    plan: launcher.RolloutPlan,
    manifest_descriptor: Mapping[str, Any],
    training_descriptor: Mapping[str, Any],
    checkpoint_descriptor: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    resource_snapshot: Mapping[str, Any],
    namespace: Path,
    nonce: str,
) -> dict[str, Any]:
    env = dict(plan.env)
    command = list(plan.command)
    return {
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed": SEED,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "run_id": plan.run_id,
        "root": str(root),
        "manifest": {
            "path": str(plan.manifest),
            "canonical_sha256": plan.manifest_sha256,
            "file": dict(manifest_descriptor),
        },
        "training_receipt": {
            "path": str(plan.training_receipt),
            "file": dict(training_descriptor),
        },
        "checkpoint": {
            "path": str(plan.checkpoint["path"]),
            "declared_sha256": str(plan.checkpoint["sha256"]),
            "sha256": str(checkpoint_descriptor["sha256"]),
            "bytes": int(checkpoint_descriptor["bytes"]),
            "file": dict(checkpoint_descriptor),
        },
        "source_sha256": {key: dict(value) for key, value in sources.items()},
        "resource_snapshot": dict(resource_snapshot),
        "command": {
            "argv": command,
            "cwd": str(root),
            "env_overrides": env,
            "sha256": _command_digest(command, str(root), env),
        },
        "namespace": str(namespace),
        "nonce": nonce,
    }


def _marker_core(identity_digest: str, namespace: Path, nonce: str) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.namespace_marker",
        "namespace": str(namespace),
        "nonce": nonce,
        "identity_sha256": identity_digest,
        "diagnostic_only": True,
        "one_shot": True,
    }


@dataclass(frozen=True)
class AdmissionCapability:
    receipt: Mapping[str, Any]
    receipt_path: Path
    consumed_marker: Path
    seal: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_path": str(self.receipt_path),
            "consumed_marker": str(self.consumed_marker),
            "receipt_sha256": self.receipt.get("receipt_sha256"),
            "seal": self.seal,
            "diagnostic_only": True,
            "credit": 0,
        }


def mint_admission(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint one strict, zero-credit receipt without starting a process."""

    root_path = _absolute(root, "root")
    if not root_path.is_dir():
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    namespace = _namespace(output_root, selected_nonce)
    if os.path.lexists(namespace):
        _fail("fresh namespace already exists")
    _reject_symlink_components(namespace.parent, "namespace parent")

    if resource_admission is None:
        resource_admission = resource.probe_resource_admission(GPU_INDEX, root=root_path)
    resource_snapshot = _validate_resource(resource_admission)

    # launcher is the existing identity authority for current-manifest v3,
    # exact command construction, and seed17/checkpoint cross-binding.
    plan = launcher.build_plan(
        root_path,
        seed=SEED,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        nonce=selected_nonce,
        output_namespace=namespace,
        gpu_index=GPU_INDEX,
    )
    manifest_raw, manifest_descriptor, manifest_payload = _read_file(plan.manifest, "current manifest", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del manifest_raw
    if manifest_payload is None:
        _fail("manifest payload was not opened")
    training_raw, training_descriptor, training_payload = _read_file(plan.training_receipt, "training receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del training_raw
    if training_payload is None:
        _fail("training receipt payload was not opened")
    checkpoint_path = Path(str(plan.checkpoint["path"]))
    checkpoint_descriptor = _checkpoint_descriptor(checkpoint_path)
    if checkpoint_descriptor["sha256"] != str(plan.checkpoint["sha256"]):
        _fail("checkpoint content SHA-256 differs from the training receipt declaration")
    if checkpoint_descriptor["bytes"] != int(plan.checkpoint["bytes"]):
        _fail("checkpoint bytes differ from the training receipt declaration")
    sources = {key: _source_descriptor(root_path, relative, key) for key, relative in SOURCE_RELATIVE_PATHS.items()}
    identity = _identity_core(
        root=root_path,
        plan=plan,
        manifest_descriptor=manifest_descriptor,
        training_descriptor=training_descriptor,
        checkpoint_descriptor=checkpoint_descriptor,
        sources=sources,
        resource_snapshot=resource_snapshot,
        namespace=namespace,
        nonce=selected_nonce,
    )
    identity_digest = canonical_digest(identity)
    try:
        os.mkdir(namespace, 0o700)
    except OSError as error:
        _fail(f"cannot reserve fresh namespace: {error}")
    marker_core = _marker_core(identity_digest, namespace, selected_nonce)
    marker_raw = (canonical_json(marker_core) + "\n").encode("utf-8")
    marker_path = namespace / ".diagnostic-admission-marker.json"
    marker_descriptor = _write_exclusive(marker_path, marker_raw, mode=0o600)
    receipt_path = namespace / ".diagnostic-admission-receipt.json"
    receipt_core: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "issued",
        "receipt_version": 1,
        "report_id": REPORT_ID,
        "identity": identity,
        "identity_sha256": identity_digest,
        "namespace_marker": {
            **marker_descriptor,
            "path": str(marker_path),
            "payload_sha256": hashlib.sha256(marker_raw).hexdigest(),
        },
        "receipt_path": str(receipt_path),
        "consumption": {
            "one_shot": True,
            "state": "issued",
            "consumed": False,
            "consumed_marker": str(namespace / ".diagnostic-admission-consumed"),
        },
        "diagnostic_execute_only": True,
        **ZERO_CREDIT,
    }
    receipt_core["receipt_sha256"] = canonical_digest(receipt_core)
    receipt_raw = (canonical_json(receipt_core) + "\n").encode("utf-8")
    receipt_descriptor = _write_exclusive(receipt_path, receipt_raw, mode=0o600)
    result = dict(receipt_core)
    result["receipt_file"] = receipt_descriptor
    validate_receipt(result, check_files=True, allow_consumed=False)
    return result


def _validate_identity_shape(identity: Mapping[str, Any]) -> None:
    _exact(identity, "model_kind", MODEL, "identity")
    _exact(identity, "hidden", HIDDEN, "identity")
    _exact(identity, "updates", UPDATES, "identity")
    _exact(identity, "seed", SEED, "identity")
    _exact(identity, "case_id", CASE_ID, "identity")
    _exact(identity, "split", SPLIT, "identity")
    _exact(identity, "transitions", TRANSITIONS, "identity")
    _exact(identity, "frames", FRAMES, "identity")
    _validate_nonce(identity.get("nonce"))
    namespace = _absolute(identity.get("namespace"), "identity.namespace")
    expected_name = f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{identity['nonce']}"
    if namespace.name != expected_name or not _under(namespace, Path(tempfile.gettempdir()).resolve()):
        _fail("identity.namespace is not the fresh seed17/full835 nonce namespace")
    source_sha = _mapping(identity.get("source_sha256"), "identity.source_sha256")
    if set(source_sha) != set(SOURCE_RELATIVE_PATHS):
        _fail("identity.source_sha256 does not cover every pinned source")
    for key, value in source_sha.items():
        item = _mapping(value, f"identity.source_sha256.{key}")
        _sha(item.get("sha256"), f"identity.source_sha256.{key}.sha256")
        _int(item.get("dev"), f"identity.source_sha256.{key}.dev")
        _int(item.get("ino"), f"identity.source_sha256.{key}.ino")
        _exact(item, "nlink", 1, f"identity.source_sha256.{key}")
    command = _mapping(identity.get("command"), "identity.command")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
        _fail("identity.command.argv must be a non-empty string list")
    _exact(command, "cwd", identity.get("root"), "identity.command")
    env = _mapping(command.get("env_overrides"), "identity.command.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(GPU_INDEX), "identity.command.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", "identity.command.env_overrides")
    _sha(command.get("sha256"), "identity.command.sha256")
    if command["sha256"] != _command_digest(argv, command["cwd"], env):
        _fail("identity exact command digest mismatch")
    expected = {
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--device": "cuda:0",
    }
    for option, value in expected.items():
        positions = [i for i, item in enumerate(argv) if item == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != value:
            _fail(f"identity command is not bound to {option}={value}")
    if argv[-1] != "--diagnostic" or "--diagnostic" in argv[:-1]:
        _fail("identity command must end with one --diagnostic flag")


def _validate_marker(receipt: Mapping[str, Any]) -> dict[str, Any]:
    marker = _mapping(receipt.get("namespace_marker"), "namespace_marker")
    marker_path = _absolute(marker.get("path"), "namespace_marker.path")
    namespace = _absolute(_mapping(receipt.get("identity"), "identity").get("namespace"), "identity.namespace")
    if marker_path.parent != namespace or marker_path.name != ".diagnostic-admission-marker.json":
        _fail("namespace marker is not inside the bound namespace")
    _exact(marker, "mode", 0o600, "namespace_marker")
    _exact(marker, "uid", os.getuid(), "namespace_marker")
    _exact(marker, "gid", os.getgid(), "namespace_marker")
    _exact(marker, "nlink", 1, "namespace_marker")
    raw, descriptor, payload = _read_file(marker_path, "namespace marker", max_bytes=64 * 1024, parse_json=True)
    if payload is None:
        _fail("namespace marker payload is absent")
    for key in ("dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "sha256"):
        if key in marker and key != "sha256" and descriptor.get(key) != marker[key]:
            _fail(f"namespace marker {key} drifted")
    expected_payload_sha = marker.get("payload_sha256")
    if expected_payload_sha != hashlib.sha256(raw).hexdigest():
        _fail("namespace marker payload SHA drifted")
    _exact(payload, "schema", f"{SCHEMA}.namespace_marker", "namespace marker")
    _exact(payload, "namespace", str(namespace), "namespace marker")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "namespace marker")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "namespace marker")
    _exact(payload, "diagnostic_only", True, "namespace marker")
    _exact(payload, "one_shot", True, "namespace marker")
    return descriptor


def validate_receipt(
    receipt: Mapping[str, Any],
    *,
    check_files: bool = True,
    allow_consumed: bool = False,
) -> list[str]:
    """Return strict validation errors; never grants formal credit."""

    errors: list[str] = []
    try:
        _walk_json(receipt, "receipt")
        allowed = set(ZERO_CREDIT) | {
            "schema", "status", "receipt_version", "report_id", "identity", "identity_sha256",
            "namespace_marker", "receipt_path", "consumption", "diagnostic_execute_only",
            "receipt_sha256", "receipt_file",
        }
        _reject_unknown(receipt, allowed, "receipt")
        _exact(receipt, "schema", SCHEMA, "receipt")
        _exact(receipt, "status", "issued", "receipt")
        _exact(receipt, "receipt_version", 1, "receipt")
        _exact(receipt, "report_id", REPORT_ID, "receipt")
        _exact(receipt, "diagnostic_execute_only", True, "receipt")
        for key, expected in ZERO_CREDIT.items():
            _exact(receipt, key, expected, "receipt")
        identity = _mapping(receipt.get("identity"), "identity")
        _validate_identity_shape(identity)
        identity_digest = _sha(receipt.get("identity_sha256"), "receipt.identity_sha256")
        if identity_digest != canonical_digest(identity):
            _fail("receipt.identity_sha256 does not bind identity")
        consumption = _mapping(receipt.get("consumption"), "consumption")
        _exact(consumption, "one_shot", True, "consumption")
        _exact(consumption, "state", "issued", "consumption")
        _exact(consumption, "consumed", False, "consumption")
        consumed_marker = _absolute(consumption.get("consumed_marker"), "consumption.consumed_marker")
        if consumed_marker.parent != _absolute(identity["namespace"], "identity.namespace"):
            _fail("consumed marker escapes namespace")
        marker_descriptor = _validate_marker(receipt) if check_files else None
        receipt_digest = _sha(receipt.get("receipt_sha256"), "receipt.receipt_sha256")
        core = {key: value for key, value in receipt.items() if key not in {"receipt_sha256", "receipt_file"}}
        if receipt_digest != canonical_digest(core):
            _fail("receipt.receipt_sha256 does not bind receipt bytes")
        if check_files:
            receipt_path = _absolute(receipt.get("receipt_path"), "receipt_path")
            if not receipt_path.is_file() or receipt_path.parent != _absolute(identity["namespace"], "identity.namespace"):
                _fail("receipt_path is not the bound namespace receipt")
            raw, descriptor, file_payload = _read_file(receipt_path, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
            del raw
            expected_file_payload = {key: value for key, value in receipt.items() if key != "receipt_file"}
            if file_payload != expected_file_payload:
                _fail("admission receipt file payload drifted")
            if stat.S_IMODE(os.lstat(receipt_path).st_mode) != 0o600:
                _fail("admission receipt must be mode 0600")
            if marker_descriptor is None:
                _fail("namespace marker was not checked")
            if os.path.lexists(consumed_marker) and not allow_consumed:
                _fail("single-use admission has already been consumed")
    except (AdmissionError, TypeError, AttributeError, KeyError, OSError) as error:
        errors.append(str(error))
    return errors


def load_receipt(path: Path | str, *, allow_consumed: bool = False) -> dict[str, Any]:
    receipt_path = _absolute(path, "admission receipt")
    _raw, descriptor, payload = _read_file(receipt_path, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del descriptor
    if payload is None:
        _fail("admission receipt is not a JSON object")
    if str(payload.get("receipt_path")) != str(receipt_path):
        _fail("admission receipt path is not bound to the loaded path")
    errors = validate_receipt(payload, check_files=True, allow_consumed=allow_consumed)
    if errors:
        _fail("; ".join(errors))
    return payload


def _capability_seal(receipt: Mapping[str, Any], consumed_descriptor: Mapping[str, Any]) -> str:
    return canonical_digest({
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_path": receipt["receipt_path"],
        "consumed_marker": consumed_descriptor,
        "diagnostic_only": True,
        "credit": 0,
    })


def consume_receipt(path: Path | str) -> AdmissionCapability:
    """Atomically consume an issued receipt exactly once."""

    receipt_path = _absolute(path, "admission receipt")
    receipt = load_receipt(receipt_path, allow_consumed=False)
    identity = _mapping(receipt["identity"], "identity")
    namespace = _absolute(identity["namespace"], "identity.namespace")
    consumed_path = _absolute(_mapping(receipt["consumption"], "consumption")["consumed_marker"], "consumed marker")
    raw = (canonical_json({
        "schema": CONSUMED_SCHEMA,
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_path": str(receipt_path),
        "namespace": str(namespace),
        "nonce": identity["nonce"],
        "consumed_at_ns": time.time_ns(),
        "diagnostic_only": True,
        "credit": 0,
    }) + "\n").encode()
    descriptor = _write_exclusive(consumed_path, raw, mode=0o600)
    if consumed_path.parent != namespace:
        _fail("consumed marker escaped namespace")
    seal = _capability_seal(receipt, descriptor)
    return AdmissionCapability(receipt=receipt, receipt_path=receipt_path, consumed_marker=consumed_path, seal=seal)


def revalidate_receipt(
    receipt: Mapping[str, Any],
    *,
    resource_admission: Mapping[str, Any] | None = None,
    check_files: bool = True,
) -> dict[str, Any]:
    """Re-read every bound source and require exact identity equality."""

    errors = validate_receipt(receipt, check_files=check_files, allow_consumed=True)
    if errors:
        _fail("receipt validation failed: " + "; ".join(errors))
    identity = _mapping(receipt["identity"], "identity")
    root = _absolute(identity["root"], "identity.root")
    manifest = _absolute(_mapping(identity["manifest"], "identity.manifest")["path"], "manifest")
    training = _absolute(_mapping(identity["training_receipt"], "identity.training_receipt")["path"], "training receipt")
    checkpoint = _absolute(_mapping(identity["checkpoint"], "identity.checkpoint")["path"], "checkpoint")
    for path, name in ((manifest, "manifest"), (training, "training receipt"), (checkpoint, "checkpoint")):
        if not _under(path, root) and not _under(path, Path("/tmp")):
            _fail(f"{name} escapes bounded roots")
    _, manifest_descriptor, manifest_payload = _read_file(manifest, "current manifest", max_bytes=MAX_JSON_BYTES, parse_json=True)
    _, training_descriptor, training_payload = _read_file(training, "training receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    checkpoint_descriptor = _checkpoint_descriptor(checkpoint)
    if manifest_payload is None or training_payload is None:
        _fail("bound JSON payload is absent")
    expected_manifest = _mapping(identity["manifest"], "identity.manifest")
    expected_training = _mapping(identity["training_receipt"], "identity.training_receipt")
    expected_checkpoint = _mapping(identity["checkpoint"], "identity.checkpoint")
    if manifest_descriptor != expected_manifest["file"]:
        _fail("current manifest file identity drifted")
    if hashlib.sha256(canonical_json(manifest_payload).encode()).hexdigest() != expected_manifest["canonical_sha256"]:
        _fail("current manifest canonical SHA drifted")
    if training_descriptor != expected_training["file"]:
        _fail("training receipt file identity drifted")
    if checkpoint_descriptor != expected_checkpoint["file"] or checkpoint_descriptor["sha256"] != expected_checkpoint["sha256"]:
        _fail("checkpoint identity drifted")
    sources = _mapping(identity["source_sha256"], "identity.source_sha256")
    for key, relative in SOURCE_RELATIVE_PATHS.items():
        current = _source_descriptor(root, relative, key)
        if current != sources[key]:
            _fail(f"{key} source identity drifted")
    current_resource = _validate_resource(resource_admission if resource_admission is not None else resource.probe_resource_admission(GPU_INDEX, root=root))
    if canonical_json(current_resource) != canonical_json(identity["resource_snapshot"]):
        _fail("GPU2 resource snapshot drifted from the receipt")
    command = _mapping(identity["command"], "identity.command")
    argv = command["argv"]
    if command["sha256"] != _command_digest(argv, command["cwd"], command["env_overrides"]):
        _fail("exact command digest drifted")
    return {"status": "revalidated", "resource_snapshot": current_resource, "identity_sha256": receipt["identity_sha256"], "receipt_sha256": receipt["receipt_sha256"], **ZERO_CREDIT}


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        receipt = mint_admission(root, manifest=manifest, training_receipt=training_receipt, checkpoint=checkpoint, nonce=nonce, output_root=output_root, resource_admission=resource_admission)
        identity = dict(receipt["identity"])
        report = {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "receipt_bound_admission_ready",
            "admission_granted": True,
            "receipt_bound_capability_issued": True,
            "diagnostic_execute_only": True,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "launch_allowed": False,
            "source_bound": True,
            "receipt_path": receipt["receipt_path"],
            "receipt_sha256": receipt["receipt_sha256"],
            "namespace": identity["namespace"],
            "namespace_nonce": identity["nonce"],
            "namespace_marker": receipt["namespace_marker"],
            "resource_snapshot": identity["resource_snapshot"],
            "identity": identity,
            "single_use": True,
            "receipt_mode": 0o600,
            "namespace_mode": 0o700,
            "popen_attempted": False,
            "processes_started": 0,
            "formal_state_touched": False,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
            "blocked_reasons": [],
            **ZERO_CREDIT,
        }
        return report
    except (AdmissionError, launcher.ContractError, OSError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "admission_granted": False,
            "receipt_bound_capability_issued": False,
            "diagnostic_execute_only": True,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "launch_allowed": False,
            "source_bound": False,
            "popen_attempted": False,
            "processes_started": 0,
            "formal_state_touched": False,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
            "blocked_reasons": [str(error)],
            **ZERO_CREDIT,
        }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {
            "schema", "report_id", "status", "admission_granted", "receipt_bound_capability_issued",
            "diagnostic_execute_only", "diagnostic_execute_allowed", "execution_capability_admitted",
            "launch_allowed", "source_bound", "receipt_path",
            "receipt_sha256", "namespace", "namespace_nonce", "namespace_marker", "resource_snapshot",
            "identity", "single_use", "receipt_mode", "namespace_mode", "popen_attempted",
            "processes_started", "formal_state_touched", "registry_writes", "ledger_writes",
            "denominator_writes", "gate_writes", "completion_writes", "plan_writes", "blocked_reasons",
        }
        _reject_unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        status = report.get("status")
        if status not in {"receipt_bound_admission_ready", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        for key in ("diagnostic_execute_only", "launch_allowed", "formal_state_touched"):
            _exact(report, key, True if key == "diagnostic_execute_only" else False, "report")
        _exact(report, "diagnostic_execute_allowed", False, "report")
        _exact(report, "execution_capability_admitted", False, "report")
        _exact(report, "popen_attempted", False, "report")
        _exact(report, "processes_started", 0, "report")
        for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
            _exact(report, key, 0, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a string list")
        if status == "receipt_bound_admission_ready":
            _exact(report, "admission_granted", True, "report")
            _exact(report, "receipt_bound_capability_issued", True, "report")
            _exact(report, "diagnostic_execute_allowed", False, "report")
            _exact(report, "source_bound", True, "report")
            _exact(report, "single_use", True, "report")
            _exact(report, "receipt_mode", 0o600, "report")
            _exact(report, "namespace_mode", 0o700, "report")
            _sha(report.get("receipt_sha256"), "report.receipt_sha256")
            _validate_nonce(report.get("namespace_nonce"))
            _validate_identity_shape(_mapping(report.get("identity"), "report.identity"))
    except (AdmissionError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_raw seed17 diagnostic admission",
        "",
        f"- status: `{report.get('status')}`",
        f"- admission granted: `{report.get('admission_granted')}`",
        f"- diagnostic execute only: `{report.get('diagnostic_execute_only')}`",
        f"- namespace: `{report.get('namespace')}`",
        f"- receipt: `{report.get('receipt_path')}`",
        "- identity: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames",
        "- GPU: physical GPU2 exposed as logical cuda:0; exact resource snapshot bound",
        "- source pins: manifest, training receipt, checkpoint, core_learning, validators",
        "- one-shot mode: receipt-bound token issued; execution capability not admitted; receipt/markers use 0600; namespace uses 0700",
        "- subprocess/Popen: not attempted; formal/registry/ledger/gate/completion/PLAN: untouched",
        "- credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", [])],
        "",
    ])


def _write_report(path: Path, payload: Mapping[str, Any], text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), mode=0o640)
    _write_exclusive(path.with_suffix(".zh-CN.md"), text.encode(), mode=0o640)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--nonce", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            _raw, _descriptor, payload = _read_file(args.verify_report, "report", max_bytes=MAX_JSON_BYTES, parse_json=True)
            if payload is None:
                _fail("report is not a JSON object")
            errors = validate_report(payload)
            if errors:
                print(canonical_json({"valid": False, "errors": errors}))
                return 1
            print(canonical_json({"valid": True, "schema": REPORT_SCHEMA}))
            return 0
        report = build_report(root=args.root, manifest=args.manifest, training_receipt=args.training_receipt, checkpoint=args.checkpoint, nonce=args.nonce, output_root=args.output_root)
        _write_report(args.report_output, report, render_markdown(report))
        print(canonical_json(report))
        return 0 if report["status"] == "receipt_bound_admission_ready" else 2
    except (AdmissionError, launcher.ContractError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
