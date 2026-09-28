#!/usr/bin/env python3
"""Bounded F3 evaluator/artifact readiness contract.

This module inventories the *static* evaluator boundary used by
``scripts/core_learning.py evaluate`` and defines a one-shot, fresh-namespace
diagnostic envelope for a future current-manifest rollout.  It is deliberately
additive: the existing raw/residual launchers and bridges remain unchanged.

The contract reads only bounded Python source text and its metadata.  It never
opens a checkpoint, manifest HDF5, trajectory HDF5, evaluation JSON, progress
sidecar, or validator artifact.  It never imports ``core_learning`` for
execution, starts a subprocess, touches a GPU/queue, or mutates registry,
ledger, gate, completion, or PLAN state.

The current repository has enough source-level information to describe the
exact evaluator argv and output schemas, but it does not have an admitted
production HDF5 validator or a real evaluator ``Popen``/``wait`` receipt.
Therefore every envelope and the report remain diagnostic-only,
fail-closed, launch-ineligible, and zero-credit.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
DATE_TAG = "20260929"
MODEL_KINDS = ("graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
MODEL_HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25
GPU_BY_MODEL_SEED = {
    ("graph_raw", 17): 4,
    ("graph_raw", 29): 5,
    ("graph_raw", 43): 6,
    ("graph_residual", 17): 2,
    ("graph_residual", 29): 3,
    ("graph_residual", 43): 7,
}

CONTRACT_SCHEMA = "core.f3.graph.evaluator_artifact_readiness_contract.v1"
ENVELOPE_SCHEMA = f"{CONTRACT_SCHEMA}.diagnostic_envelope"
REPORT_SCHEMA = f"{CONTRACT_SCHEMA}.report"
EVALUATION_SCHEMA = "core.evaluation.v1"
PROGRESS_SCHEMA = "core.rollout.progress.v1"
HDF5_STATE_SCHEMA = "core.state.native_velocity.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
NATURAL_EXIT_SCHEMA = f"{CONTRACT_SCHEMA}.natural_exit_proof"
ARTIFACT_IDENTITY_SCHEMA = f"{CONTRACT_SCHEMA}.artifact_identity"
REPORT_ID = "f3-graph-evaluator-artifact-readiness-contract-v1"

CORE_LEARNING_RELATIVE = Path("scripts/core_learning.py")
SYNTHETIC_VALIDATOR_RELATIVE = Path(
    "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py"
)
MANIFEST_RELATIVE = Path("campaigns/core-v1/f3-dataset-v2.json")

MAX_SOURCE_BYTES = 512 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$\Z", re.ASCII)
NONCE_RE = re.compile(r"^[0-9a-f]{32}\Z", re.ASCII)

EVALUATION_FIELDS = (
    "schema",
    "evaluation_mode",
    "diagnostic",
    "formal_eligible",
    "model_kind",
    "max_neighbors",
    "checkpoint",
    "baseline",
    "training",
    "split",
    "requested_split",
    "test_included",
    "case_splits",
    "registered_case_ids",
    "selected_case_ids",
    "registered_case_count",
    "case_count",
    "formal_capacity",
    "expected_frames",
    "fixed_denominator",
    "cases",
    "aggregate",
    "metrics",
    "execution_summary",
    "finite_summary",
    "maximum_steps",
    "autonomous",
    "future_state_inputs",
)

HDF5_ATTRIBUTES = (
    "schema_version",
    "state_schema",
    "velocity_semantics",
    "future_state_inputs",
    "autonomous_prediction",
    "identity_semantics",
)
HDF5_DATASETS = (
    "time",
    "position",
    "velocity",
    "particle_id",
    "particle_zone",
    "mass",
    "valid",
)

PROGRESS_FIELDS = (
    "schema",
    "case_id",
    "status",
    "completed_frames",
    "expected_frames",
    "frames_expected",
    "frames_executed",
    "particles",
    "elapsed_seconds",
    "time_s",
    "trajectory_output",
    "progress_every",
    "autonomous",
    "future_state_inputs",
    "execution_complete",
    "finite_rollout_complete",
)

ZERO_AUTHORITY: dict[str, Any] = {
    "diagnostic_only": True,
    "readiness_pass": False,
    "launch_allowed": False,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

ZERO_SIDE_EFFECTS: dict[str, Any] = {
    "evaluator_started": False,
    "validator_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_started": False,
    "processes_stopped": 0,
    "processes_restarted": 0,
    "registry_writes": 0,
    "ledger_writes": 0,
    "gate_writes": 0,
    "completion_writes": 0,
    "plan_writes": 0,
}


class ContractError(ValueError):
    """Malformed, drifting, or accidentally authorizing contract data."""


def _fail(message: str) -> None:
    raise ContractError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _exact_keys(value: Any, expected: Sequence[str] | set[str], name: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{name} must be an object")
    _require(set(value) == set(expected), f"{name} fields differ")
    return value


def _text(value: Any, name: str) -> str:
    _require(type(value) is str and bool(value) and "\x00" not in value,
             f"{name} must be a non-empty string")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    _require(type(value) is bool, f"{name} must be boolean")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{name} must be integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _text(value, name)
    _require(SHA256_RE.fullmatch(result) is not None and len(set(result)) > 1,
             f"{name} must be a non-placeholder SHA-256")
    return result


def _absolute(value: Any, name: str) -> Path:
    path = Path(_text(value, name))
    _require(path.is_absolute(), f"{name} must be absolute")
    _require(".." not in path.parts and "." not in path.parts,
             f"{name} contains a lexical path alias")
    _require(Path(os.path.normpath(str(path))) == path,
             f"{name} is not normalized")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _read_bounded_source(path: Path, name: str) -> tuple[str, dict[str, Any]]:
    """Read only bounded Python source, never a production artifact."""

    path = _absolute(str(path), name)
    try:
        before = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    _require(stat.S_ISREG(before.st_mode), f"{name} must be a regular file")
    _require(not stat.S_ISLNK(before.st_mode), f"{name} must not be a symlink")
    _require(before.st_nlink == 1, f"{name} must have one hard link")
    _require(before.st_size <= MAX_SOURCE_BYTES,
             f"{name} exceeds the bounded source limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    try:
        opened = os.fstat(fd)
        _require(
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            f"{name} changed before bounded read",
        )
        raw = os.read(fd, MAX_SOURCE_BYTES + 1)
        _require(len(raw) <= MAX_SOURCE_BYTES, f"{name} exceeded bounded read")
        closed = os.fstat(fd)
        _require(
            (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            f"{name} changed during bounded read",
        )
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(f"{name} is not UTF-8 source: {error}")
    metadata = {
        "path": str(path),
        "bytes": int(before.st_size),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "read_mode": "bounded_source_text_only",
        "max_bytes": MAX_SOURCE_BYTES,
        "content_opened": True,
        "production_artifact": False,
    }
    return text, metadata


def _source_literals(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        _fail(f"source does not parse: {error}")
    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    return literals


def _function_source(source: str, function_name: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        _fail(f"source does not parse: {error}")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    return ""


def audit_core_learning_source(source: str) -> dict[str, Any]:
    """Inventory the real CLI/output literals without importing or running it."""

    literals = _source_literals(source)
    evaluate_source = _function_source(source, "evaluate")
    main_source = _function_source(source, "main")
    required_cli = (
        "--manifest",
        "--data-root",
        "--checkpoint",
        "--case-id",
        "--split",
        "--maximum-steps",
        "--chunk-size",
        "--device",
        "--progress-every",
        "--trajectory-output",
        "--progress-output",
        "--output",
        "--diagnostic",
    )
    parser_checks = {
        "evaluate_subcommand": 'sub.add_parser("evaluate")' in source or 'for name in ("rollout", "evaluate")' in source,
        "evaluate_dispatch": 'args.command == "evaluate"' in main_source,
        "mutually_exclusive_checkpoint_baseline": "add_mutually_exclusive_group(required=True)" in main_source,
        "diagnostic_flag_is_evaluate_only": 'if name == "evaluate"' in main_source,
    }
    json_checks = {
        "evaluation_schema": EVALUATION_SCHEMA in evaluate_source,
        "evaluation_fields": all(field in evaluate_source for field in EVALUATION_FIELDS),
        "exclusive_atomic_output": "atomic_json(args.output, result, exclusive=True)" in main_source,
        "evaluation_mode_diagnostic_or_formal": 'evaluation_mode = "diagnostic"' in evaluate_source,
        "autonomous_no_future_state_inputs": '"autonomous": True' in evaluate_source and '"future_state_inputs": False' in evaluate_source,
    }
    hdf5_checks = {
        "atomic_hdf5_context": "_atomic_hdf5_output" in source,
        "state_schema": HDF5_STATE_SCHEMA in source,
        "attributes": all(attribute in source for attribute in HDF5_ATTRIBUTES),
        "datasets": all(dataset in source for dataset in HDF5_DATASETS),
        "expected_frame_window": "total_steps + 1" in source,
        "valid_mask": 'create_dataset("valid"' in source,
    }
    progress_checks = {
        "progress_schema": PROGRESS_SCHEMA in source,
        "progress_sidecar_atomic": "atomic_json(progress_path, payload)" in source,
        "completion_markers": all(marker in source for marker in ("execution_complete", "finite_rollout_complete")),
        "progress_not_completion": 'publish_progress("completed"' in source,
    }
    checks = {
        "has_evaluate_function": bool(evaluate_source),
        "has_main_function": bool(main_source),
        "required_cli_flags": all(flag in literals for flag in required_cli),
        "parser": all(parser_checks.values()),
        "json_output": all(json_checks.values()),
        "hdf5_output": all(hdf5_checks.values()),
        "progress_sidecar": all(progress_checks.values()),
    }
    return {
        "static_inventory_pass": all(checks.values()),
        "checks": checks,
        "parser_checks": parser_checks,
        "json_checks": json_checks,
        "hdf5_checks": hdf5_checks,
        "progress_checks": progress_checks,
        "required_cli_flags": list(required_cli),
        "evaluation_schema": EVALUATION_SCHEMA,
        "evaluation_fields": list(EVALUATION_FIELDS),
        "hdf5_state_schema": HDF5_STATE_SCHEMA,
        "hdf5_attributes": list(HDF5_ATTRIBUTES),
        "hdf5_datasets": list(HDF5_DATASETS),
        "progress_schema": PROGRESS_SCHEMA,
        "progress_fields": list(PROGRESS_FIELDS),
        "source_execution": "not_imported_not_executed",
    }


def audit_validator_source(source: str) -> dict[str, Any]:
    """Inventory the installed validator CLI and preserve its synthetic boundary."""

    literals = _source_literals(source)
    required_flags = ("--metadata", "--fixture-root", "--trajectory", "--report-output", "--verify-report")
    checks = {
        "required_cli_flags": all(flag in literals for flag in required_flags),
        "synthetic_marker": "SYNTHETIC_MARKER_NAME" in source,
        "synthetic_only_contract": "synthetic_only" in source and "production_artifact_opened" in source,
        "no_execution_authority": "launch_allowed" in source and "capability_admitted" in source,
        "bounded_hdf5_limit": "MAX_HDF5_BYTES" in source,
    }
    return {
        "static_inventory_pass": all(checks.values()),
        "checks": checks,
        "required_cli_flags": list(required_flags),
        "validator_schema": VALIDATOR_SCHEMA,
        "current_capability": "synthetic_only_not_production",
        "production_capability_admitted": False,
        "source_execution": "not_imported_not_executed",
    }


def _model_run_id(model_kind: str, seed: int) -> str:
    return f"f3-{model_kind}500-hidden16-currentmanifest-seed{seed}-{DATE_TAG}-v3"


def _planned_nonce(model_kind: str, seed: int) -> str:
    value = canonical_sha256({
        "contract": REPORT_ID,
        "date": DATE_TAG,
        "model_kind": model_kind,
        "seed": seed,
    })[:32]
    _require(NONCE_RE.fullmatch(value) is not None and int(value, 16) != 0,
             "planned nonce is invalid")
    return value


def _namespace(root: Path, model_kind: str, seed: int, nonce: str) -> Path:
    # The path is a plan-only identity.  It is intentionally not created.
    return Path("/tmp") / (
        f"f3-{model_kind}-evaluator-currentmanifest-{DATE_TAG}-"
        f"seed{seed}-full835-nonce{nonce}"
    )


def _artifact(namespace: Path, name: str, suffix: str, schema: str) -> dict[str, Any]:
    return {
        "path": str(namespace / f"{name}{suffix}"),
        "suffix": suffix,
        "schema": schema,
        "content_opened": False,
        "metadata_observed": False,
        "producer_receipt_present": False,
    }


def _build_evaluator_argv(root: Path, checkpoint: Path, manifest: Path,
                          artifacts: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [
        str(root / ".venv" / "bin" / "python"),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(manifest),
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
        str(CHUNK_SIZE),
        "--device",
        "cuda:0",
        "--progress-every",
        str(PROGRESS_EVERY),
        "--trajectory-output",
        str(artifacts["trajectory"]["path"]),
        "--progress-output",
        str(artifacts["progress"]["path"]),
        "--output",
        str(artifacts["evaluation"]["path"]),
        "--diagnostic",
    ]


def _build_validator_argv(root: Path, namespace: Path,
                          artifacts: Mapping[str, Mapping[str, Any]]) -> list[str]:
    # This is the exact installed *synthetic* validator CLI shape.  It is
    # recorded to expose the gap; it is never executed by this contract.
    return [
        str(root / ".venv" / "bin" / "python"),
        "-u",
        str(root / SYNTHETIC_VALIDATOR_RELATIVE),
        "--metadata",
        str(namespace / "validator-input.json"),
        "--fixture-root",
        str(namespace / "synthetic-fixture"),
        "--trajectory",
        str(artifacts["trajectory"]["path"]),
        "--report-output",
        str(artifacts["validator"]["path"]),
    ]


def _natural_exit_requirements(command_sha: str, namespace: Path, nonce: str,
                               artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema": NATURAL_EXIT_SCHEMA,
        "proof_present": False,
        "producer": "subprocess.Popen",
        "wait_method": "Popen.wait",
        "natural_exit": False,
        "observed_after_exit": False,
        "evaluator_alive": None,
        "evaluator_returncode": None,
        "validator_returncode": None,
        "stopped_processes": 0,
        "restarted_processes": 0,
        "command_sha256": command_sha,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "evaluation_artifact": artifacts["evaluation"]["path"],
        "trajectory_artifact": artifacts["trajectory"]["path"],
        "progress_artifact": artifacts["progress"]["path"],
        "validator_artifact": artifacts["validator"]["path"],
        "authoritative": False,
    }


def _build_envelope(root: Path, model_kind: str, seed: int) -> dict[str, Any]:
    _require(model_kind in MODEL_KINDS, f"unsupported model kind: {model_kind}")
    _require(seed in SEEDS, f"unsupported seed: {seed}")
    root = root.resolve()
    manifest = root / MANIFEST_RELATIVE
    run_id = _model_run_id(model_kind, seed)
    checkpoint = Path("/tmp") / f"{run_id}-checkpoint.pt"
    training_receipt = Path("/tmp") / f"{run_id}-training.json"
    nonce = _planned_nonce(model_kind, seed)
    namespace = _namespace(root, model_kind, seed, nonce)
    artifacts = {
        "evaluation": _artifact(namespace, "evaluation", ".json", EVALUATION_SCHEMA),
        "trajectory": _artifact(namespace, "trajectory", ".h5", HDF5_STATE_SCHEMA),
        "progress": _artifact(namespace, "evaluation-progress", ".json", PROGRESS_SCHEMA),
        "validator": _artifact(namespace, "hdf5-validation", ".json", VALIDATOR_SCHEMA),
        "artifact_identity": _artifact(namespace, "artifact-identity", ".json", ARTIFACT_IDENTITY_SCHEMA),
        "natural_exit_proof": _artifact(namespace, "process-exit-proof", ".json", NATURAL_EXIT_SCHEMA),
        "terminal_receipt": _artifact(namespace, "terminal-receipt", ".json", f"{CONTRACT_SCHEMA}.terminal_receipt"),
    }
    evaluator_argv = _build_evaluator_argv(root, checkpoint, manifest, artifacts)
    evaluator_env = {
        "CUDA_VISIBLE_DEVICES": str(GPU_BY_MODEL_SEED[(model_kind, seed)]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    evaluator_identity = {
        "argv": evaluator_argv,
        "cwd": str(root),
        "env_overrides": evaluator_env,
    }
    command_sha = canonical_sha256(evaluator_identity)
    validator_argv = _build_validator_argv(root, namespace, artifacts)
    validator_sha = canonical_sha256({
        "argv": validator_argv,
        "cwd": str(root),
        "env_overrides": evaluator_env,
    })
    progress_binding = {
        "schema": PROGRESS_SCHEMA,
        "path": artifacts["progress"]["path"],
        "expected_status_after_success": "completed",
        "expected_frames": FRAMES,
        "expected_transitions": TRANSITIONS,
        "progress_every": PROGRESS_EVERY,
        "autonomous": True,
        "future_state_inputs": False,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "progress_is_not_completion_proof": True,
        "content_opened": False,
    }
    validator = {
        "schema": f"{CONTRACT_SCHEMA}.validator_command",
        "argv": validator_argv,
        "argv_sha256": validator_sha,
        "cwd": str(root),
        "output": artifacts["validator"]["path"],
        "expected_validator_schema": VALIDATOR_SCHEMA,
        "current_validator_source": str(root / SYNTHETIC_VALIDATOR_RELATIVE),
        "synthetic_only": True,
        "production_artifacts_allowed": False,
        "production_capability_admitted": False,
        "started": False,
        "passed": False,
        "content_opened": False,
    }
    artifact_identity = {
        "schema": ARTIFACT_IDENTITY_SCHEMA,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "command_sha256": command_sha,
        "manifest": str(manifest),
        "training_receipt": str(training_receipt),
        "checkpoint": str(checkpoint),
        "artifacts": {key: value["path"] for key, value in artifacts.items()},
        "sha256_and_byte_metadata_present": False,
        "identity_receipt_present": False,
        "content_opened": False,
        "authoritative": False,
    }
    natural_exit = _natural_exit_requirements(command_sha, namespace, nonce, artifacts)
    bindings = [
        {
            "binding": "core_learning.evaluate.argv_to_artifacts",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": True,
            "authoritative": False,
            "blocker": None,
        },
        {
            "binding": "evaluation_json_schema_to_output",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": True,
            "authoritative": False,
            "blocker": "evaluation JSON was not opened",
        },
        {
            "binding": "trajectory_hdf5_schema_to_output",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": True,
            "authoritative": False,
            "blocker": "trajectory HDF5 was not opened",
        },
        {
            "binding": "progress_sidecar_to_evaluator_argv",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": True,
            "authoritative": False,
            "blocker": "progress sidecar was not opened and is not completion proof",
        },
        {
            "binding": "validator_command_to_validator_artifact",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": False,
            "authoritative": False,
            "blocker": "installed validator is synthetic-only and not admitted for production artifacts",
        },
        {
            "binding": "validator_artifact_to_artifact_identity",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": False,
            "authoritative": False,
            "blocker": "no independent artifact-identity receipt exists",
        },
        {
            "binding": "natural_exit_proof_to_exact_command_and_namespace",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": False,
            "authoritative": False,
            "blocker": "no real subprocess.Popen/wait natural-exit proof exists",
        },
        {
            "binding": "one_shot_fresh_namespace_to_attempt",
            "static_contract_observed": True,
            "runtime_receipt_observed": False,
            "bound": False,
            "authoritative": False,
            "blocker": "namespace is planned only; freshness and atomic non-reuse are unattested",
        },
    ]
    return {
        "schema": ENVELOPE_SCHEMA,
        "status": "diagnostic_envelope_defined",
        "model_kind": model_kind,
        "hidden": MODEL_HIDDEN,
        "updates": UPDATES,
        "seed": seed,
        "run_id": run_id,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "manifest": {
            "path": str(manifest),
            "content_opened": False,
            "metadata_observed": False,
        },
        "training_receipt": {
            "path": str(training_receipt),
            "content_opened": False,
            "metadata_observed": False,
        },
        "checkpoint": {
            "path": str(checkpoint),
            "content_opened": False,
            "metadata_observed": False,
        },
        "namespace": {
            "path": str(namespace),
            "nonce": nonce,
            "nonce_source": "deterministic_non_authorizing_plan",
            "one_shot": True,
            "fresh_namespace_required": True,
            "freshness_attested": False,
            "materialized": False,
            "reuse_allowed": False,
            "atomic_create_required": True,
        },
        "evaluator": {
            "argv": evaluator_argv,
            "argv_sha256": command_sha,
            "cwd": str(root),
            "env_overrides": evaluator_env,
            "model_selected_by_checkpoint": True,
            "started": False,
            "natural_exit_observed": False,
            "content_opened": False,
        },
        "artifacts": artifacts,
        "progress_sidecar": progress_binding,
        "validator": validator,
        "artifact_identity": artifact_identity,
        "natural_exit": natural_exit,
        "bindings": bindings,
        **ZERO_AUTHORITY,
        "source_bound": False,
        "side_effects": dict(ZERO_SIDE_EFFECTS),
        "input_boundary": {
            "bounded_source_code_opened": True,
            "manifest_content_opened": False,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "progress_content_opened": False,
            "validator_content_opened": False,
            "gpu_runtime_started": False,
        },
    }


def build_report(root: Path | str = LAB_ROOT) -> dict[str, Any]:
    """Build the deterministic source-inventory and blocked envelope report."""

    root = Path(root).resolve()
    core_path = root / CORE_LEARNING_RELATIVE
    validator_path = root / SYNTHETIC_VALIDATOR_RELATIVE
    core_source, core_metadata = _read_bounded_source(core_path, "core_learning.py")
    validator_source, validator_metadata = _read_bounded_source(
        validator_path, "synthetic validator source"
    )
    core_audit = audit_core_learning_source(core_source)
    validator_audit = audit_validator_source(validator_source)
    envelopes = [
        _build_envelope(root, model_kind, seed)
        for model_kind in MODEL_KINDS
        for seed in SEEDS
    ]
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "contract_mode": "bounded_static_source_inventory_and_diagnostic_envelope",
        "scope": {
            "model_kinds": list(MODEL_KINDS),
            "seeds": list(SEEDS),
            "model_hidden": MODEL_HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "manifest": str(root / MANIFEST_RELATIVE),
            "large_artifact_policy": "metadata_boundary_only; no checkpoint/HDF5/evaluation/progress content",
        },
        "source_inventory": {
            "core_learning": {
                "metadata": core_metadata,
                "audit": core_audit,
            },
            "current_validator": {
                "metadata": validator_metadata,
                "audit": validator_audit,
            },
        },
        "argv_contract": {
            "producer": "current_manifest_rollout_launcher_v1",
            "command_shape": "core_learning.py evaluate",
            "exact_option_order": [
                "--manifest", "--data-root", "--checkpoint", "--case-id", "--split",
                "--maximum-steps", "--chunk-size", "--device", "--progress-every",
                "--trajectory-output", "--progress-output", "--output", "--diagnostic",
            ],
            "model_kind_not_in_argv": True,
            "model_identity_source": "checkpoint_metadata_only",
            "diagnostic_flag_required": True,
        },
        "output_contract": {
            "evaluation_json": {
                "schema": EVALUATION_SCHEMA,
                "fields": list(EVALUATION_FIELDS),
                "atomic_publish": True,
                "content_opened": False,
            },
            "trajectory_hdf5": {
                "state_schema": HDF5_STATE_SCHEMA,
                "attributes": list(HDF5_ATTRIBUTES),
                "datasets": list(HDF5_DATASETS),
                "frames": FRAMES,
                "transitions": TRANSITIONS,
                "atomic_publish": True,
                "content_opened": False,
            },
            "progress_sidecar": {
                "schema": PROGRESS_SCHEMA,
                "fields": list(PROGRESS_FIELDS),
                "progress_is_not_completion_proof": True,
                "content_opened": False,
            },
        },
        "validator_contract": {
            "schema": f"{CONTRACT_SCHEMA}.validator_command",
            "installed_validator": str(root / SYNTHETIC_VALIDATOR_RELATIVE),
            "installed_validator_mode": "synthetic_only",
            "production_capability_admitted": False,
            "required_output_schema": VALIDATOR_SCHEMA,
            "validator_command_is_recorded_per_envelope": True,
            "content_opened": False,
        },
        "natural_exit_contract": {
            "schema": NATURAL_EXIT_SCHEMA,
            "required_producer": "subprocess.Popen",
            "required_wait_method": "Popen.wait",
            "required_returncode": 0,
            "required_alive_after_wait": False,
            "required_observed_after_exit": True,
            "exact_command_sha_binding": True,
            "fresh_namespace_binding": True,
            "proofs_observed": 0,
            "proofs_expected": len(envelopes),
        },
        "binding_summary": {
            "source_static_inventory_pass": bool(
                core_audit["static_inventory_pass"] and validator_audit["static_inventory_pass"]
            ),
            "argv_schema_binding_defined": True,
            "artifact_sidecar_binding_defined": True,
            "validator_production_binding": False,
            "artifact_identity_receipts_observed": 0,
            "natural_exit_proofs_observed": 0,
            "fresh_namespaces_attested": 0,
            "readiness_pass": False,
            "launch_allowed": False,
            "credit": 0,
        },
        "envelopes": envelopes,
        "blocked_reasons": [
            "no evaluator was started and no real evaluator JSON/HDF5/progress receipt was opened",
            "installed HDF5 validator is synthetic-only and cannot authenticate production artifacts",
            "no independent artifact-identity sidecar receipt was produced",
            "no real subprocess.Popen/wait natural-exit proof was observed",
            "fresh namespaces are planned identities only; no one-shot creation/freshness attestation exists",
        ],
        **ZERO_AUTHORITY,
        "source_bound": False,
        "side_effects": dict(ZERO_SIDE_EFFECTS),
        "input_boundary": {
            "core_learning_source_opened_bounded": True,
            "validator_source_opened_bounded": True,
            "manifest_content_opened": False,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "progress_content_opened": False,
            "validator_artifact_content_opened": False,
            "runtime_started": False,
            "gpu_started": False,
            "queue_started": False,
        },
        "prohibited_operations": [
            "evaluator_or_solver_or_worker_start",
            "GPU_or_queue_start",
            "real_checkpoint_or_HDF5_or_evaluation_open",
            "registry_ledger_gate_completion_PLAN_mutation",
            "stop_or_restart_existing_process",
        ],
    }


def _validate_artifact(value: Any, name: str, expected_suffix: str, expected_schema: str) -> None:
    row = _exact_keys(
        value,
        {"path", "suffix", "schema", "content_opened", "metadata_observed", "producer_receipt_present"},
        name,
    )
    path = _absolute(row["path"], f"{name}.path")
    _require(path.suffix == expected_suffix, f"{name}.path suffix drift")
    _require(row["suffix"] == expected_suffix, f"{name}.suffix drift")
    _require(row["schema"] == expected_schema, f"{name}.schema drift")
    _require(row["content_opened"] is False, f"{name}.content_opened was promoted")
    _require(row["metadata_observed"] is False, f"{name}.metadata_observed was promoted")
    _require(row["producer_receipt_present"] is False,
             f"{name}.producer_receipt_present was promoted")


def _validate_envelope(value: Any, root: Path) -> None:
    expected = _build_envelope(root, value.get("model_kind"), value.get("seed"))
    _require(canonical_json(value) == canonical_json(expected),
             "envelope drifted from the deterministic non-authorizing contract")


def validate_report(value: Mapping[str, Any], root: Path | str = LAB_ROOT) -> dict[str, Any]:
    """Validate the report and reject all attempts at readiness promotion."""

    root = Path(root).resolve()
    expected = build_report(root)
    _require(canonical_json(value) == canonical_json(expected),
             "report drifted from the current bounded source contract")
    _require(value["status"] == "blocked_fail_closed", "report was promoted from blocked status")
    for key, expected_value in ZERO_AUTHORITY.items():
        _require(value[key] == expected_value, f"report.{key} was promoted")
    _require(value["source_bound"] is False, "source_bound was promoted")
    _require(value["side_effects"] == ZERO_SIDE_EFFECTS, "side effects were promoted")
    envelopes = value["envelopes"]
    _require(type(envelopes) is list and len(envelopes) == len(MODEL_KINDS) * len(SEEDS),
             "envelope count drift")
    seen_namespaces: set[str] = set()
    seen_nonces: set[str] = set()
    for envelope in envelopes:
        _validate_envelope(envelope, root)
        namespace = envelope["namespace"]["path"]
        nonce = envelope["namespace"]["nonce"]
        _require(namespace not in seen_namespaces, "namespace is reused")
        _require(nonce not in seen_nonces, "namespace nonce is reused")
        seen_namespaces.add(namespace)
        seen_nonces.add(nonce)
    return json.loads(canonical_json(value))


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["binding_summary"]
    lines = [
        "# F3 evaluator artifact readiness contract",
        "",
        f"- status: `{report['status']}`",
        f"- source static inventory: `{summary['source_static_inventory_pass']}`",
        f"- readiness / launch / credit: `{report['readiness_pass']}` / `{report['launch_allowed']}` / `{report['credit']}`",
        f"- envelopes: `{len(report['envelopes'])}` (graph_raw/residual × seeds 17/29/43)",
        f"- natural-exit proofs: `{report['natural_exit_contract']['proofs_observed']}/{report['natural_exit_contract']['proofs_expected']}`",
        "",
        "This report only reads bounded Python source text. It does not open real checkpoints, HDF5, evaluation JSON, or progress sidecars, and it starts no evaluator/solver/worker/GPU/queue.",
        "",
        "## Boundaries",
        "",
    ]
    lines.extend(f"- {reason}" for reason in report["blocked_reasons"])
    lines.extend([
        "",
        "The installed validator CLI is recorded for audit but remains synthetic-only; it cannot mint production terminal evidence.",
        "",
    ])
    return "\n".join(lines)


def _load_report(path: Path) -> dict[str, Any]:
    path = _absolute(str(path), "report")
    try:
        info = os.lstat(path)
        _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode),
                 "report must be a regular non-symlink file")
        _require(info.st_size <= MAX_REPORT_BYTES, "report exceeds bounded size")
        raw = path.read_bytes()
    except OSError as error:
        _fail(f"cannot read report: {error}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"report is not valid JSON: {error}")
    _require(isinstance(value, Mapping), "report must be an object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT,
                        help="repository lab root; only bounded Python source is read")
    parser.add_argument("--report-output", type=Path,
                        default=LAB_ROOT / "reports" / "F3-GRAPH-EVALUATOR-ARTIFACT-READINESS-CONTRACT-2026-09-29.json")
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if args.verify_report is not None:
            payload = _load_report(args.verify_report)
            validate_report(payload, root)
            print(canonical_json({"status": "verified", "report": str(args.verify_report.resolve())}))
            return 0
        report = build_report(root)
        validate_report(report, root)
        _write_json(args.report_output, report)
        if args.markdown_output is not None:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(canonical_json({
            "status": report["status"],
            "report": str(args.report_output.resolve()),
            "envelopes": len(report["envelopes"]),
            "readiness_pass": report["readiness_pass"],
            "launch_allowed": report["launch_allowed"],
            "credit": report["credit"],
        }))
        return 0
    except (ContractError, OSError, TypeError, ValueError, KeyError) as error:
        print(json.dumps({
            "schema": REPORT_SCHEMA,
            "status": "blocked_fail_closed",
            "readiness_pass": False,
            "launch_allowed": False,
            "credit": 0,
            "error": str(error),
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
