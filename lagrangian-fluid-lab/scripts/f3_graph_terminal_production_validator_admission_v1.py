#!/usr/bin/env python3
"""Define a diagnostic-only admission receipt for the F3 HDF5 validator.

This is an independent admission sidecar for
``f3_graph_terminal_production_validator_capability_v1``.  It binds the
installed validator source and its regression tests by exact SHA-256, repeats
the fixed graph_raw/graph_residual hidden16/update-500 and 835/836 contract,
and records the exact evaluator argv digest that a future producer would have
to prove.

The sidecar is deliberately non-authorizing.  It never opens a checkpoint,
trajectory, evaluation, progress, or validator artifact; it never creates an
output namespace; and it never imports or executes an evaluator.  In
particular, a token, a claimed PID, or a claimed Popen/wait result cannot turn
this receipt into formal authority.  The receipt remains diagnostic-only,
launch-disabled, and zero-credit until an independently reviewed runtime
capability supplies real process and artifact evidence.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
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


LAB_ROOT = Path(__file__).resolve().parents[1]
DATE_TAG = "20260929"

SCHEMA = "core.f3.graph.terminal.production_validator_admission.v1"
RECEIPT_SCHEMA = f"{SCHEMA}.receipt"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-terminal-production-validator-admission-v1"

VALIDATOR_SOURCE_RELATIVE = Path(
    "scripts/f3_graph_terminal_production_validator_capability_v1.py"
)
VALIDATOR_TEST_RELATIVE = Path(
    "tests/test_f3_graph_terminal_production_validator_capability_v1.py"
)

# These are intentionally pinned.  A future change to the wrapped validator
# or its regression tests must update this independent admission contract in
# the same review, rather than letting a mutated file self-attest by hashing
# itself at runtime.
EXPECTED_VALIDATOR_SOURCE_SHA256 = (
    "a33825cacc46650292bbe106181fd1c26d2f3b6354bfdec19302447c55a0a0ce"
)
EXPECTED_VALIDATOR_TEST_SHA256 = (
    "ddd2ec921e0836458c9a1eb53ff4f16d2b835a7afa8061c6971e73ac11a49696"
)

WRAPPED_VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
WRAPPED_CAPABILITY_SCHEMA = (
    "core.f3.graph.terminal.production_validator_capability.v1"
)
RUNTIME_EVIDENCE_BOUNDARY_SCHEMA = (
    "core.f3.graph.terminal.production_validator_runtime_evidence_boundary.v1"
)

MODEL_KINDS = ("graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACE_RE = re.compile(r"^[0-9a-f]{32}$")

SOURCE_ROLE = "wrapped_validator_source"
TEST_ROLE = "wrapped_validator_tests"
DEFAULT_NAMESPACE = hashlib.sha256(
    b"f3-graph-terminal-production-validator-admission-v1"
).hexdigest()[:32]

DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-TERMINAL-PRODUCTION-VALIDATOR-ADMISSION-2026-09-29.json"
)

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


def _planned_runtime_evidence_boundary() -> dict[str, Any]:
    """Describe evidence that must come from production, never this receipt.

    The admission sidecar is intentionally non-authorizing.  Keeping every
    observed/present flag false makes that boundary explicit and digest-bound;
    a local caller cannot turn a planned receipt into scheduler authority by
    flipping one of these fields.
    """

    return {
        "schema": RUNTIME_EVIDENCE_BOUNDARY_SCHEMA,
        "production_scheduler_trust_anchor_required": True,
        "production_scheduler_trust_anchor_present": False,
        "production_scheduler_trust_anchor_verified": False,
        "one_shot_consume_witness_required": True,
        "one_shot_consume_witness_present": False,
        "one_shot_consume_witness_verified": False,
        "runtime_identity_observation_required": True,
        "runtime_identity_observed": False,
        "gpu_uuid_pci_observed": False,
        "child_runtime_gpu_attested": False,
        "terminal_identity_observed": False,
        "local_self_attestation_accepted": False,
        "promotion_allowed": False,
    }


class AdmissionError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing admission data."""


def _fail(message: str) -> None:
    raise AdmissionError(f"fail-closed: {message}")


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
        _fail(f"{name} must be boolean")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256 digest")
    return result


def _namespace(value: Any, name: str) -> str:
    result = _string(value, name)
    if NAMESPACE_RE.fullmatch(result) is None or int(result, 16) == 0:
        _fail(f"{name} must be a non-zero lowercase 32-hex namespace")
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


def _reject_unknown(
    value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


def _absolute_clean_path(value: Any, name: str) -> Path:
    raw = _string(value, name)
    path = Path(raw)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a lexical path alias")
    if Path(os.path.normpath(raw)) != path:
        _fail(f"{name} is not normalized")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(
    path: Path, name: str, *, allow_missing_leaf: bool = False
) -> None:
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


def _regular_stat(path: Path, name: str, *, max_bytes: int) -> os.stat_result:
    _reject_symlink_components(path, name)
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular file")
    if info.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link")
    if info.st_size > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    return info


def _sha256_file(path: Path, name: str) -> tuple[str, int]:
    before = _regular_stat(path, name, max_bytes=MAX_SOURCE_BYTES)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name} read-only: {error}")
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        observed = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if observed != identity:
            _fail(f"{name} changed before bounded read")
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                _fail(f"{name} exceeds bounded size {MAX_SOURCE_BYTES}")
            digest.update(chunk)
        closed = os.fstat(fd)
        observed_after = (
            closed.st_dev,
            closed.st_ino,
            closed.st_size,
            closed.st_mtime_ns,
        )
        if observed_after != identity:
            _fail(f"{name} changed during bounded read")
    finally:
        os.close(fd)
    return digest.hexdigest(), before.st_size


def _source_ref(root: Path, relative: Path, role: str, expected: str) -> dict[str, Any]:
    path = root / relative
    result: dict[str, Any] = {
        "path": str(relative),
        "role": role,
        "expected_sha256": expected,
        "sha256": None,
        "bytes": None,
        "sha256_match": False,
        "symlink_components_rejected": True,
        "hardlink_count_required": 1,
    }
    try:
        observed, size = _sha256_file(path, str(relative))
    except AdmissionError as error:
        result["error"] = str(error)
        return result
    result["sha256"] = observed
    result["bytes"] = size
    result["sha256_match"] = observed == expected
    return result


def _artifact_root(namespace: str) -> Path:
    return Path(tempfile.gettempdir()) / (
        f"f3-graph-terminal-production-validator-admission-{namespace}"
    )


def _artifact_path(root: Path, model_kind: str, seed: int, name: str) -> Path:
    prefix = f"{model_kind}-hidden{HIDDEN}-updates{UPDATES}-seed{seed}"
    suffix = {
        "checkpoint": "-checkpoint.pt",
        "evaluation": "-evaluation.json",
        "trajectory": "-trajectory.h5",
        "progress": "-evaluation-progress.json",
        "validator": "-hdf5-validation.json",
    }[name]
    return root / f"{prefix}{suffix}"


def _artifact_ref(root: Path, path: Path, role: str) -> dict[str, Any]:
    relative = path.relative_to(root)
    return {
        "role": role,
        "path": str(path),
        "relative_path": str(relative),
        "root_contained": _under(path, root),
        "symlink_components_rejected": True,
        "hardlink_count_required": 1,
        "observed_hardlink_count": None,
        "content_opened": False,
        "runtime_integrity_attested": False,
    }


def _evaluator_command(root: Path, artifact_root: Path, model_kind: str, seed: int) -> dict[str, Any]:
    checkpoint = _artifact_path(artifact_root, model_kind, seed, "checkpoint")
    evaluation = _artifact_path(artifact_root, model_kind, seed, "evaluation")
    trajectory = _artifact_path(artifact_root, model_kind, seed, "trajectory")
    progress = _artifact_path(artifact_root, model_kind, seed, "progress")
    validator = _artifact_path(artifact_root, model_kind, seed, "validator")
    argv = [
        str(root / ".venv" / "bin" / "python"),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(root / "campaigns" / "core-v1" / "f3-dataset-v2.json"),
        "--data-root",
        str(root),
        "--checkpoint",
        str(checkpoint),
        "--case-id",
        CASE_ID,
        "--split",
        SPLIT,
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        "34560",
        "--device",
        "cuda:0",
        "--progress-every",
        "25",
        "--trajectory-output",
        str(trajectory),
        "--progress-output",
        str(progress),
        "--output",
        str(evaluation),
        "--diagnostic",
    ]
    env_overrides = {"PYTHONDONTWRITEBYTECODE": "1"}
    command_identity = {
        "argv": argv,
        "cwd": str(root),
        "env_overrides": env_overrides,
    }
    artifacts = {
        name: _artifact_ref(artifact_root, path, f"{model_kind}/seed{seed}/{name}")
        for name, path in (
            ("checkpoint", checkpoint),
            ("evaluation", evaluation),
            ("trajectory", trajectory),
            ("progress", progress),
            ("validator", validator),
        )
    }
    return {
        "model_kind": model_kind,
        "seed": seed,
        "argv": argv,
        "cwd": str(root),
        "env_overrides": env_overrides,
        "command_sha256": canonical_digest(command_identity),
        "exact_command_required": True,
        "artifact_binding_sha256": canonical_digest(artifacts),
        "artifacts": artifacts,
    }


def _source_binding(root: Path) -> dict[str, Any]:
    return {
        "validator_source": _source_ref(
            root,
            VALIDATOR_SOURCE_RELATIVE,
            SOURCE_ROLE,
            EXPECTED_VALIDATOR_SOURCE_SHA256,
        ),
        "validator_tests": _source_ref(
            root,
            VALIDATOR_TEST_RELATIVE,
            TEST_ROLE,
            EXPECTED_VALIDATOR_TEST_SHA256,
        ),
        "wrapped_validator_schema": WRAPPED_VALIDATOR_SCHEMA,
        "wrapped_capability_schema": WRAPPED_CAPABILITY_SCHEMA,
    }


def _target_contract() -> dict[str, Any]:
    return {
        "model_kinds": list(MODEL_KINDS),
        "seeds": list(SEEDS),
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }


def _build_receipt(root: Path, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
    root = root.resolve()
    namespace = _namespace(namespace, "namespace")
    artifact_root = _artifact_root(namespace)
    commands = [
        _evaluator_command(root, artifact_root, model_kind, seed)
        for model_kind in MODEL_KINDS
        for seed in SEEDS
    ]
    command_summary = [
        {
            "model_kind": item["model_kind"],
            "seed": item["seed"],
            "command_sha256": item["command_sha256"],
        }
        for item in commands
    ]
    artifact_bindings = [
        {
            "model_kind": item["model_kind"],
            "seed": item["seed"],
            "artifacts": item["artifacts"],
            "artifact_binding_sha256": item["artifact_binding_sha256"],
        }
        for item in commands
    ]
    core: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "diagnostic_admission_receipt",
        "contract_date": DATE_TAG,
        "repository_root": str(root),
        "source_binding": _source_binding(root),
        "target_contract": _target_contract(),
        "namespace": {
            "value": namespace,
            "artifact_root": str(artifact_root),
            "fresh": True,
            "one_shot": True,
            "reuse_forbidden": True,
            "freshness_attested": False,
            "materialized": False,
            "atomic_reservation_required": True,
        },
        "evaluator_command_binding": {
            "digest_algorithm": "sha256(canonical_json(argv,cwd,env_overrides))",
            "commands": commands,
            "command_summary": command_summary,
            "bundle_sha256": canonical_digest(command_summary),
        },
        "artifact_root_policy": {
            "root": str(artifact_root),
            "root_containment_required": True,
            "symlink_components_rejected": True,
            "hardlink_count_required": 1,
            "artifact_content_opened": False,
            "runtime_integrity_attested": False,
            "artifact_bindings_sha256": canonical_digest(artifact_bindings),
        },
        "artifact_bindings": artifact_bindings,
        "independent_process_proof_requirement": {
            "required": True,
            "independent": True,
            "producer": "subprocess.Popen",
            "wait_method": "Popen.wait",
            "must_bind_command_sha256": True,
            "must_bind_namespace": True,
            "must_bind_artifact_root": True,
            "proof_present": False,
            "proof_verified": False,
            "authoritative": False,
        },
        "runtime_evidence_boundary": _planned_runtime_evidence_boundary(),
        "authority_boundary": {
            "token_present": False,
            "token_is_formal_authority": False,
            "token_can_admit": False,
            "capability_admitted": False,
            "launch_allowed": False,
            "formal_authority_present": False,
        },
        **ZERO_CREDIT,
    }
    return {**core, "receipt_binding_sha256": canonical_digest(core)}


RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "contract_date",
        "repository_root",
        "source_binding",
        "target_contract",
        "namespace",
        "evaluator_command_binding",
        "artifact_root_policy",
        "artifact_bindings",
        "independent_process_proof_requirement",
        "runtime_evidence_boundary",
        "authority_boundary",
        "receipt_binding_sha256",
        *ZERO_CREDIT,
    }
)


def _validate_source_binding(
    value: Any, root: Path, *, verify_files: bool = True
) -> None:
    source = _mapping(value, "source_binding")
    _reject_unknown(
        source,
        {
            "validator_source",
            "validator_tests",
            "wrapped_validator_schema",
            "wrapped_capability_schema",
        },
        "source_binding",
    )
    _exact(source, "wrapped_validator_schema", WRAPPED_VALIDATOR_SCHEMA, "source_binding")
    _exact(source, "wrapped_capability_schema", WRAPPED_CAPABILITY_SCHEMA, "source_binding")
    expected_rows = (
        ("validator_source", VALIDATOR_SOURCE_RELATIVE, SOURCE_ROLE, EXPECTED_VALIDATOR_SOURCE_SHA256),
        ("validator_tests", VALIDATOR_TEST_RELATIVE, TEST_ROLE, EXPECTED_VALIDATOR_TEST_SHA256),
    )
    for key, relative, role, expected in expected_rows:
        ref = _mapping(source.get(key), f"source_binding.{key}")
        _reject_unknown(
            ref,
            {
                "path",
                "role",
                "expected_sha256",
                "sha256",
                "bytes",
                "sha256_match",
                "symlink_components_rejected",
                "hardlink_count_required",
                "error",
            },
            f"source_binding.{key}",
        )
        _exact(ref, "path", str(relative), f"source_binding.{key}")
        _exact(ref, "role", role, f"source_binding.{key}")
        _exact(ref, "expected_sha256", expected, f"source_binding.{key}")
        _exact(ref, "symlink_components_rejected", True, f"source_binding.{key}")
        _exact(ref, "hardlink_count_required", 1, f"source_binding.{key}")
        observed_sha = ref.get("sha256")
        _sha(observed_sha, f"source_binding.{key}.sha256")
        _exact(ref, "sha256", expected, f"source_binding.{key}")
        _strict_int(ref.get("bytes"), f"source_binding.{key}.bytes", minimum=1)
        _exact(ref, "sha256_match", True, f"source_binding.{key}")
        if verify_files:
            observed, size = _sha256_file(root / relative, str(relative))
            if observed != expected or size != ref["bytes"]:
                _fail(f"source_binding.{key} does not match the pinned repository bytes")


def _validate_target_contract(value: Any) -> None:
    target = _mapping(value, "target_contract")
    _reject_unknown(
        target,
        {"model_kinds", "seeds", "hidden", "updates", "case_id", "split", "transitions", "frames"},
        "target_contract",
    )
    _exact(target, "model_kinds", list(MODEL_KINDS), "target_contract")
    _exact(target, "seeds", list(SEEDS), "target_contract")
    for key, expected in (
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _exact(target, key, expected, "target_contract")


def _validate_namespace(value: Any) -> tuple[str, Path]:
    namespace = _mapping(value, "namespace")
    _reject_unknown(
        namespace,
        {
            "value",
            "artifact_root",
            "fresh",
            "one_shot",
            "reuse_forbidden",
            "freshness_attested",
            "materialized",
            "atomic_reservation_required",
        },
        "namespace",
    )
    value_text = _namespace(namespace.get("value"), "namespace.value")
    root = _absolute_clean_path(namespace.get("artifact_root"), "namespace.artifact_root")
    expected_root = _artifact_root(value_text)
    if root != expected_root:
        _fail("namespace.artifact_root is not derived from the one-shot namespace")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not _under(root, temp_root) or root == temp_root:
        _fail("namespace.artifact_root must remain under the OS temporary root")
    _reject_symlink_components(root, "namespace.artifact_root", allow_missing_leaf=True)
    if root.exists() and not root.is_dir():
        _fail("namespace.artifact_root must be a directory when materialized")
    for key, expected in (
        ("fresh", True),
        ("one_shot", True),
        ("reuse_forbidden", True),
        ("freshness_attested", False),
        ("materialized", False),
        ("atomic_reservation_required", True),
    ):
        _exact(namespace, key, expected, "namespace")
    return value_text, root


def _validate_artifact_ref(value: Any, root: Path, name: str) -> None:
    ref = _mapping(value, name)
    _reject_unknown(
        ref,
        {
            "role",
            "path",
            "relative_path",
            "root_contained",
            "symlink_components_rejected",
            "hardlink_count_required",
            "observed_hardlink_count",
            "content_opened",
            "runtime_integrity_attested",
        },
        name,
    )
    relative = _string(ref.get("relative_path"), f"{name}.relative_path")
    relative_path = Path(relative)
    if relative_path.is_absolute() or any(part in {".", ".."} for part in relative_path.parts):
        _fail(f"{name}.relative_path must be a clean relative artifact name")
    path = _absolute_clean_path(ref.get("path"), f"{name}.path")
    if path != root / relative_path or not _under(path, root):
        _fail(f"{name}.path escapes the declared artifact root")
    _exact(ref, "root_contained", True, name)
    _exact(ref, "symlink_components_rejected", True, name)
    _exact(ref, "hardlink_count_required", 1, name)
    if ref.get("observed_hardlink_count") is not None:
        _fail(f"{name}.observed_hardlink_count must remain unattested")
    _exact(ref, "content_opened", False, name)
    _exact(ref, "runtime_integrity_attested", False, name)


def _validate_commands(
    value: Any, root: Path, artifact_root: Path
) -> tuple[list[Mapping[str, Any]], str]:
    binding = _mapping(value, "evaluator_command_binding")
    _reject_unknown(
        binding,
        {"digest_algorithm", "commands", "command_summary", "bundle_sha256"},
        "evaluator_command_binding",
    )
    _exact(
        binding,
        "digest_algorithm",
        "sha256(canonical_json(argv,cwd,env_overrides))",
        "evaluator_command_binding",
    )
    commands = binding.get("commands")
    if not isinstance(commands, list) or len(commands) != len(MODEL_KINDS) * len(SEEDS):
        _fail("evaluator_command_binding.commands must cover both models and all seeds")
    observed_rows: list[Mapping[str, Any]] = []
    observed_summary: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for index, item in enumerate(commands):
        row = _mapping(item, f"evaluator_command_binding.commands[{index}]")
        _reject_unknown(
            row,
            {
                "model_kind",
                "seed",
                "argv",
                "cwd",
                "env_overrides",
                "command_sha256",
                "exact_command_required",
                "artifact_binding_sha256",
                "artifacts",
            },
            f"evaluator_command_binding.commands[{index}]",
        )
        model_kind = _string(row.get("model_kind"), f"commands[{index}].model_kind")
        seed = _strict_int(row.get("seed"), f"commands[{index}].seed", minimum=0)
        if model_kind not in MODEL_KINDS or seed not in SEEDS or (model_kind, seed) in seen:
            _fail("evaluator command rows must contain each fixed model/seed pair once")
        seen.add((model_kind, seed))
        expected = _evaluator_command(root, artifact_root, model_kind, seed)
        for key in ("model_kind", "seed", "argv", "cwd", "env_overrides", "command_sha256", "exact_command_required", "artifact_binding_sha256"):
            _exact(row, key, expected[key], f"commands[{index}]")
        artifacts = _mapping(row.get("artifacts"), f"commands[{index}].artifacts")
        if set(artifacts) != set(expected["artifacts"]):
            _fail(f"commands[{index}].artifacts must contain the fixed five artifact roles")
        for name, expected_ref in expected["artifacts"].items():
            _validate_artifact_ref(artifacts.get(name), artifact_root, f"commands[{index}].artifacts.{name}")
            if dict(artifacts[name]) != dict(expected_ref):
                _fail(f"commands[{index}].artifacts.{name} drifted from the exact root binding")
        observed_rows.append(row)
        observed_summary.append(
            {"model_kind": model_kind, "seed": seed, "command_sha256": row["command_sha256"]}
        )
    expected_pairs = {(model, seed) for model in MODEL_KINDS for seed in SEEDS}
    if seen != expected_pairs:
        _fail("evaluator command rows do not cover the complete fixed model/seed matrix")
    _exact(binding, "command_summary", observed_summary, "evaluator_command_binding")
    _exact(binding, "bundle_sha256", canonical_digest(observed_summary), "evaluator_command_binding")
    return observed_rows, binding["bundle_sha256"]


def _validate_artifact_policy(
    value: Any, namespace_root: Path, artifact_bindings: Sequence[Mapping[str, Any]]
) -> None:
    policy = _mapping(value, "artifact_root_policy")
    _reject_unknown(
        policy,
        {
            "root",
            "root_containment_required",
            "symlink_components_rejected",
            "hardlink_count_required",
            "artifact_content_opened",
            "runtime_integrity_attested",
            "artifact_bindings_sha256",
        },
        "artifact_root_policy",
    )
    _exact(policy, "root", str(namespace_root), "artifact_root_policy")
    _exact(policy, "root_containment_required", True, "artifact_root_policy")
    _exact(policy, "symlink_components_rejected", True, "artifact_root_policy")
    _exact(policy, "hardlink_count_required", 1, "artifact_root_policy")
    _exact(policy, "artifact_content_opened", False, "artifact_root_policy")
    _exact(policy, "runtime_integrity_attested", False, "artifact_root_policy")
    normalized = [dict(item) for item in artifact_bindings]
    _exact(
        policy,
        "artifact_bindings_sha256",
        canonical_digest(normalized),
        "artifact_root_policy",
    )


def _validate_process_requirement(value: Any) -> None:
    proof = _mapping(value, "independent_process_proof_requirement")
    _reject_unknown(
        proof,
        {
            "required",
            "independent",
            "producer",
            "wait_method",
            "must_bind_command_sha256",
            "must_bind_namespace",
            "must_bind_artifact_root",
            "proof_present",
            "proof_verified",
            "authoritative",
        },
        "independent_process_proof_requirement",
    )
    for key, expected in (
        ("required", True),
        ("independent", True),
        ("producer", "subprocess.Popen"),
        ("wait_method", "Popen.wait"),
        ("must_bind_command_sha256", True),
        ("must_bind_namespace", True),
        ("must_bind_artifact_root", True),
        ("proof_present", False),
        ("proof_verified", False),
        ("authoritative", False),
    ):
        _exact(proof, key, expected, "independent_process_proof_requirement")


def _validate_runtime_evidence_boundary(value: Any) -> None:
    observed = _mapping(value, "runtime_evidence_boundary")
    expected = _planned_runtime_evidence_boundary()
    _reject_unknown(observed, set(expected), "runtime_evidence_boundary")
    for key, claim in expected.items():
        _exact(observed, key, claim, "runtime_evidence_boundary")


def _validate_authority(value: Any) -> None:
    authority = _mapping(value, "authority_boundary")
    _reject_unknown(
        authority,
        {
            "token_present",
            "token_is_formal_authority",
            "token_can_admit",
            "capability_admitted",
            "launch_allowed",
            "formal_authority_present",
        },
        "authority_boundary",
    )
    for key in authority:
        _exact(authority, key, False, "authority_boundary")


def validate_receipt(
    receipt: Mapping[str, Any], *, root: Path | str = LAB_ROOT, verify_files: bool = True
) -> list[str]:
    """Validate receipt shape and source bindings without granting authority."""

    errors: list[str] = []
    try:
        _reject_unknown(receipt, RECEIPT_KEYS, "receipt")
        _exact(receipt, "schema", RECEIPT_SCHEMA, "receipt")
        _exact(receipt, "status", "diagnostic_admission_receipt", "receipt")
        _exact(receipt, "contract_date", DATE_TAG, "receipt")
        root_path = Path(root).resolve()
        _exact(receipt, "repository_root", str(root_path), "receipt")
        _validate_source_binding(receipt.get("source_binding"), root_path, verify_files=verify_files)
        _validate_target_contract(receipt.get("target_contract"))
        _, namespace_root = _validate_namespace(receipt.get("namespace"))
        rows, _ = _validate_commands(
            receipt.get("evaluator_command_binding"), root_path, namespace_root
        )
        artifact_bindings = receipt.get("artifact_bindings")
        if not isinstance(artifact_bindings, list) or len(artifact_bindings) != len(rows):
            _fail("artifact_bindings must contain one row for each evaluator command")
        for index, binding in enumerate(artifact_bindings):
            row = _mapping(binding, f"artifact_bindings[{index}]")
            _reject_unknown(
                row,
                {"model_kind", "seed", "artifacts", "artifact_binding_sha256"},
                f"artifact_bindings[{index}]",
            )
            _exact(row, "model_kind", rows[index]["model_kind"], f"artifact_bindings[{index}]")
            _exact(row, "seed", rows[index]["seed"], f"artifact_bindings[{index}]")
            _exact(row, "artifacts", rows[index]["artifacts"], f"artifact_bindings[{index}]")
            _exact(
                row,
                "artifact_binding_sha256",
                rows[index]["artifact_binding_sha256"],
                f"artifact_bindings[{index}]",
            )
        _validate_artifact_policy(receipt.get("artifact_root_policy"), namespace_root, artifact_bindings)
        _validate_process_requirement(receipt.get("independent_process_proof_requirement"))
        _validate_runtime_evidence_boundary(receipt.get("runtime_evidence_boundary"))
        _validate_authority(receipt.get("authority_boundary"))
        for key, expected in ZERO_CREDIT.items():
            _exact(receipt, key, expected, "receipt")
        digest = _sha(receipt.get("receipt_binding_sha256"), "receipt.receipt_binding_sha256")
        core = dict(receipt)
        core.pop("receipt_binding_sha256", None)
        if digest != canonical_digest(core):
            _fail("receipt.receipt_binding_sha256 does not bind the complete receipt")
    except (AdmissionError, TypeError, ValueError, OSError) as error:
        errors.append(str(error))
    return errors


def _source_bound(receipt: Mapping[str, Any], root: Path) -> bool:
    try:
        _validate_source_binding(receipt.get("source_binding"), root, verify_files=True)
        return True
    except (AdmissionError, TypeError, ValueError, OSError):
        return False


def build_receipt(root: Path | str = LAB_ROOT, *, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
    """Build a planned receipt; never materialize its namespace or artifacts."""

    return _build_receipt(Path(root), namespace=namespace)


def _blocked_report(
    root: Path,
    receipt: Mapping[str, Any] | None,
    receipt_errors: Sequence[str],
) -> dict[str, Any]:
    receipt_valid = not receipt_errors and receipt is not None
    source_bound = bool(receipt is not None and _source_bound(receipt, root))
    base_blockers = [
        "production validator capability token is not installed",
        "independent real Popen/wait proof is absent and cannot be self-authorized",
        "production HDF5 artifact identity/validator receipt is absent",
        "fresh one-time namespace reservation is not externally attested",
        "production scheduler trust anchor is absent; this local receipt is not a scheduler authority",
        "external one-shot consume witness is absent; receipt replay cannot be promoted",
        "runtime GPU UUID/PCI, child logical-device, and terminal identity observation is absent",
        "token claims are not formal authority; admission remains zero-credit",
    ]
    reasons = list(receipt_errors) + base_blockers
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "admission_granted": False,
        "capability_admitted": False,
        "production_validator_capability_installed": False,
        "launch_allowed": False,
        "receipt_valid": receipt_valid,
        "source_bound": source_bound,
        "admission_receipt": dict(receipt) if receipt_valid else None,
        "checks": {
            "validator_source_sha256": source_bound,
            "validator_tests_sha256": source_bound,
            "wrapped_validator_schema": receipt_valid,
            "fixed_graph_contract": receipt_valid,
            "fresh_namespace_shape": receipt_valid,
            "exact_evaluator_command_digest": receipt_valid,
            "independent_popen_wait_requirement": receipt_valid,
            "artifact_root_containment_policy": receipt_valid,
            "production_scheduler_trust_anchor_requirement": receipt_valid,
            "one_shot_consume_witness_requirement": receipt_valid,
            "runtime_identity_observation_requirement": receipt_valid,
        },
        "runtime_evidence": {
            "independent_process_proof_present": False,
            "independent_process_proof_verified": False,
            "production_artifact_receipt_present": False,
            "production_hdf5_validator_passed": False,
            "fresh_namespace_reservation_attested": False,
            "production_scheduler_trust_anchor_present": False,
            "production_scheduler_trust_anchor_verified": False,
            "one_shot_consume_witness_present": False,
            "one_shot_consume_witness_verified": False,
            "runtime_identity_observed": False,
            "gpu_uuid_pci_observed": False,
            "child_runtime_gpu_attested": False,
            "terminal_identity_observed": False,
        },
        "authority_boundary": {
            "token_present": False,
            "token_is_formal_authority": False,
            "capability_admitted": False,
            "launch_allowed": False,
            "formal_authority_present": False,
        },
        "expected_contract": {
            "wrapped_validator_schema": WRAPPED_VALIDATOR_SCHEMA,
            "wrapped_capability_schema": WRAPPED_CAPABILITY_SCHEMA,
            "model_kinds": list(MODEL_KINDS),
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "fresh_namespace": "non-zero-lowercase-32-hex-one-shot",
            "exact_evaluator_command_digest": True,
            "independent_popen_wait_proof": True,
            "artifact_root_containment": True,
            "symlink_free_required": True,
            "hardlink_count_required": 1,
            "production_scheduler_trust_anchor": "required_external_and_not_self_attested",
            "one_shot_consume_witness": "required_external_atomic_replay_free_consume",
            "runtime_identity_observation": "required_live_gpu_uuid_pci_child_and_terminal_binding",
        },
        "input_boundary": {
            "validator_source_opened": source_bound,
            "validator_tests_opened": source_bound,
            "checkpoint_opened": False,
            "evaluation_json_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_json_opened": False,
            "validator_artifact_opened": False,
            "artifact_root_materialized": False,
            "popen_attempted": False,
            "wait_attempted": False,
        },
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "evaluator_started": False,
            "validator_started": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "blocked_reasons": sorted(set(str(item) for item in reasons if item)),
        **ZERO_CREDIT,
    }


def build_report(root: Path | str = LAB_ROOT) -> dict[str, Any]:
    """Build a source-bound but permanently blocked admission report."""

    root_path = Path(root).resolve()
    receipt = build_receipt(root_path)
    errors = validate_receipt(receipt, root=root_path, verify_files=True)
    return _blocked_report(root_path, receipt, errors)


REPORT_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "admission_granted",
        "capability_admitted",
        "production_validator_capability_installed",
        "launch_allowed",
        "receipt_valid",
        "source_bound",
        "admission_receipt",
        "checks",
        "runtime_evidence",
        "authority_boundary",
        "expected_contract",
        "input_boundary",
        "side_effects",
        "blocked_reasons",
        *ZERO_CREDIT,
    }
)


def validate_report(report: Mapping[str, Any], *, root: Path | str = LAB_ROOT) -> list[str]:
    errors: list[str] = []
    try:
        _reject_unknown(report, REPORT_KEYS, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        for key, expected in (
            ("admission_granted", False),
            ("capability_admitted", False),
            ("production_validator_capability_installed", False),
            ("launch_allowed", False),
        ):
            _exact(report, key, expected, "report")
        receipt = report.get("admission_receipt")
        if report.get("receipt_valid") is not True or not isinstance(receipt, Mapping):
            _fail("report must contain a structurally valid admission receipt")
        receipt_errors = validate_receipt(receipt, root=root, verify_files=True)
        if receipt_errors:
            _fail(f"embedded admission receipt is invalid: {receipt_errors}")
        _exact(report, "source_bound", True, "report")
        checks = _mapping(report.get("checks"), "report.checks")
        for key in (
            "validator_source_sha256",
            "validator_tests_sha256",
            "wrapped_validator_schema",
            "fixed_graph_contract",
            "fresh_namespace_shape",
            "exact_evaluator_command_digest",
            "independent_popen_wait_requirement",
            "artifact_root_containment_policy",
            "production_scheduler_trust_anchor_requirement",
            "one_shot_consume_witness_requirement",
            "runtime_identity_observation_requirement",
        ):
            _exact(checks, key, True, "report.checks")
        runtime = _mapping(report.get("runtime_evidence"), "report.runtime_evidence")
        for key in runtime:
            _exact(runtime, key, False, "report.runtime_evidence")
        authority = _mapping(report.get("authority_boundary"), "report.authority_boundary")
        for key in authority:
            _exact(authority, key, False, "report.authority_boundary")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key in (
            "checkpoint_opened",
            "evaluation_json_opened",
            "trajectory_hdf5_opened",
            "progress_json_opened",
            "validator_artifact_opened",
            "artifact_root_materialized",
            "popen_attempted",
            "wait_attempted",
        ):
            _exact(boundary, key, False, "report.input_boundary")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, value in side_effects.items():
            expected = False if isinstance(value, bool) else 0
            _exact(side_effects, key, expected, "report.side_effects")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
    except (AdmissionError, TypeError, ValueError, OSError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# F3 graph terminal production-validator admission",
            "",
            f"- status: `{report.get('status')}`",
            f"- receipt_valid: `{report.get('receipt_valid')}`",
            f"- source_bound: `{report.get('source_bound')}`",
            f"- admission_granted: `{report.get('admission_granted')}`",
            "- contract: graph_raw/graph_residual, hidden16, update-500, test, 835 transitions / 836 frames",
            "- process proof: independent real Popen/wait required but absent",
            "- artifact policy: root-contained, symlink-free, single-hardlink required",
            "- production boundary: external scheduler trust anchor and one-shot consume witness are required but absent",
            "- runtime identity: live GPU UUID/PCI, child logical device, and terminal artifact observation are required but absent",
            "- authority: token is not formal authority; credit is `0`",
            "",
            "## Blockers",
            "",
            *[f"- {item}" for item in report.get("blocked_reasons", [])],
            "",
        ]
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        info = _regular_stat(path, "JSON report", max_bytes=MAX_REPORT_BYTES)
        del info
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdmissionError(f"cannot read JSON report: {error}") from error
    if not isinstance(value, dict):
        raise AdmissionError("JSON report must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.verify_report is not None:
        report = _load_json(args.verify_report)
        errors = validate_report(report, root=root)
        if errors:
            print(canonical_json({"valid": False, "errors": errors}))
            return 1
        print(canonical_json({"valid": True, "schema": REPORT_SCHEMA}))
        return 0

    report = build_report(root)
    if args.report_output is not None:
        args.report_output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    if args.markdown_output is not None:
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
