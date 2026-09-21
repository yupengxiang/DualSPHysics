#!/usr/bin/env python3
"""Read-only completion and pairing checks for the three Core preprofiles.

The training worker remains the only producer of checkpoints.  This module
only reads a portable manifest, three training receipts, their progress
sidecars, and the referenced checkpoints.  It deliberately does not open a
trajectory HDF5 file, construct a dataset reader, or submit/update a job.

The final checkpoint is a strong record of the requested configuration and of
the resulting model state, but it cannot retain every fact about execution.
The report therefore separates checks recoverable from output artifacts from
claims that require the immutable job spec/source closure.  In particular,
the number of transitions used to fit normalization is a job-spec fact; the
normalization arrays alone do not encode that count.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import torch

# Support both ``python -m scripts.core_preprofile_collector`` and direct paths.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_dataset import validate_manifest
from scripts.core_models import (
    INITIALIZATION_VERSION,
    MAX_NEIGHBORS,
    MODEL_KINDS,
    NEIGHBOR_RADIUS_OVER_H,
    Normalization,
    DualIncrementModel,
)


COLLECTOR_SCHEMA = "core.preprofile_collection.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
PROGRESS_SCHEMA = "core.training.progress.v1"
EVIDENCE_SCHEMA = "core.training.evidence.v1"
INITIALIZATION_EVIDENCE_SCHEMA = "core.training.initialization_evidence.v1"
NORMALIZATION_EVIDENCE_SCHEMA = "core.training.normalization_evidence.v1"
PRIOR_EVIDENCE_SCHEMA = "core.training.prior_evidence.v1"
DEFAULT_RUN_SEED = 17
DEFAULT_PROTOCOL: dict[str, Any] = {
    "updates": 16,
    "centers_per_update": 256,
    "hidden": 64,
    "learning_rate": 1e-3,
    "optimizer": "Adam",
    "radius_over_h": NEIGHBOR_RADIUS_OVER_H,
    "max_neighbors": MAX_NEIGHBORS,
    "history_states": 1,
    "normalization_source_split": "train",
    "target_normalization": "raw_dual_increment_train_shared",
    "initialization": INITIALIZATION_VERSION,
    "paired_seed": DEFAULT_RUN_SEED,
    "sampler_seed": DEFAULT_RUN_SEED,
    "gradient_clipping": None,
    "checkpoint_every": 16,
    "log_every": 1,
    "validation_every": 0,
    "evaluate_milestones": False,
    "milestone_evaluation_mode": "deferred",
    "normalization_transitions": 256,
}

# These are the fields emitted in ``core.training.v1`` config.  The index
# carries additional declarations (formal milestones, feature dimensions,
# halo semantics, and so on); those are checked as job/index metadata rather
# than incorrectly demanded from a final training receipt.
RECEIPT_CONFIG_KEYS = frozenset({
    "model_kind", "seed", "updates", "centers_per_update", "hidden",
    "learning_rate", "optimizer", "radius_over_h", "max_neighbors",
    "history_states", "normalization_source_split", "target_normalization",
    "initialization", "paired_seed", "sampler_seed", "gradient_clipping",
    "log_every", "checkpoint_every", "validation_every",
    "validation_transition_count", "validation_centers", "validation_case_count",
    "validation_family_counts", "validation_formal_eligible", "run_id",
    "manifest_sha256", "manifest_formal_release", "evaluate_milestones",
    "milestone_evaluation_mode",
})


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical(value).encode())


def _jsonable(value: Any) -> Any:
    """Convert numpy scalars/arrays in RNG state to canonical JSON values."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _resolve(value: str | Path, *, base: Path | None = None) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    options = []
    if base is not None:
        options.append((base / candidate).resolve())
    options.append((Path.cwd() / candidate).resolve())
    options.append((Path(__file__).resolve().parents[1] / candidate).resolve())
    for option in options:
        if option.exists():
            return option
    return options[0]


def _resolve_artifact(value: str | Path, *, receipt_path: Path) -> tuple[Path, Path | None]:
    """Resolve a receipt artifact, allowing a hash-checked local collection.

    Runtime systems commonly copy ``training.json`` and its outputs into an
    immutable collection directory while leaving the original attempt path in
    the receipt.  If that original path has been garbage-collected, a sibling
    with the same basename is a safe fallback; the checkpoint SHA-256 check
    below remains mandatory.  The second return value records the missing
    declared path for the report.
    """
    declared = _resolve(value, base=receipt_path.parent)
    if declared.is_file():
        return declared, None
    local = receipt_path.parent / Path(value).name
    if local.is_file():
        return local, declared
    return declared, None


def _read_json(source: str | Path | Mapping[str, Any], *, base: Path | None = None):
    if isinstance(source, Mapping):
        return dict(source), None
    path = _resolve(source, base=base)
    return json.loads(path.read_text()), path


def _failure(code: str, message: str, *, model_kind: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"code": str(code), "message": str(message)}
    if model_kind is not None:
        row["model_kind"] = str(model_kind)
    return row


def _same_float(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _digest_state(state: Mapping[str, Any]) -> str:
    """Hash a torch state dict without relying on pickle ordering."""
    digest = hashlib.sha256()
    for key in sorted(state):
        value = state[key]
        if not torch.is_tensor(value):
            raise TypeError(f"state entry {key!r} is not a tensor")
        tensor = value.detach().cpu().contiguous()
        digest.update(str(key).encode())
        digest.update(b"\0")
        digest.update(str(tensor.dtype).encode())
        digest.update(b"\0")
        digest.update(canonical(list(tensor.shape)).encode())
        digest.update(b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _state_summary(state: Any, *, model_kind: str, hidden: int,
                   failures: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(state, Mapping) or not state:
        failures.append(_failure("missing_model_state", "checkpoint model_state is empty", model_kind=model_kind))
        return {"tensor_count": 0, "finite": False, "sha256": None, "keys": []}
    finite = True
    keys = []
    for key, value in state.items():
        keys.append(str(key))
        if not torch.is_tensor(value):
            finite = False
            failures.append(_failure("non_tensor_model_state", f"state entry {key!r} is not a tensor", model_kind=model_kind))
            continue
        if (value.is_floating_point() or value.is_complex()) and not bool(torch.isfinite(value).all()):
            finite = False
            failures.append(_failure("nonfinite_model_state", f"state entry {key!r} contains a non-finite value", model_kind=model_kind))
    try:
        state_sha = _digest_state(state)
    except (TypeError, ValueError, RuntimeError) as error:
        state_sha = None
        finite = False
        failures.append(_failure("model_state_digest_error", str(error), model_kind=model_kind))
    try:
        reference = DualIncrementModel(model_kind, hidden=int(hidden)).state_dict()
        expected_shapes = {key: (tuple(value.shape), str(value.dtype)) for key, value in reference.items()}
        observed_shapes = {key: (tuple(value.shape), str(value.dtype)) for key, value in state.items()
                           if torch.is_tensor(value)}
        if expected_shapes != observed_shapes:
            failures.append(_failure("model_state_topology_mismatch",
                                     "checkpoint state keys/shapes/dtypes do not match the declared model",
                                     model_kind=model_kind))
    except (TypeError, ValueError, RuntimeError) as error:
        failures.append(_failure("model_state_topology_error", str(error), model_kind=model_kind))
    return {"tensor_count": len(keys), "finite": bool(finite), "sha256": state_sha,
            "keys": sorted(keys)}


def _fresh_initial_state(model_kind: str, hidden: int, seed: int) -> tuple[dict[str, Any], str]:
    # fork_rng makes this diagnostic construction side-effect free for a
    # caller that is embedding the collector in another process.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(int(seed))
        model = DualIncrementModel(model_kind, hidden=int(hidden))
        state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    return state, _digest_state(state)


def _compare_config(receipt: Mapping[str, Any], *, model_kind: str,
                    expected: Mapping[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    config = receipt.get("config")
    if not isinstance(config, Mapping):
        failures.append(_failure("missing_config", "training receipt has no config object", model_kind=model_kind))
        return {}
    observed = dict(config)
    checks = {}
    for key, expected_value in expected.items():
        if key == "normalization_transitions" or key not in RECEIPT_CONFIG_KEYS:
            # This value is intentionally not in the training receipt config.
            # It is checked against the job spec/index in _protocol_binding.
            # Other index-only declarations are represented in the protocol
            # binding and are not receipt fields.
            continue
        if key == "model_kind":
            continue
        if key not in observed:
            failures.append(_failure("missing_config_field", f"config field {key!r} is missing", model_kind=model_kind))
            checks[key] = False
            continue
        actual = observed[key]
        equal = (actual == expected_value)
        if isinstance(expected_value, float):
            equal = _same_float(actual, expected_value)
        checks[key] = bool(equal)
        if not equal:
            failures.append(_failure("config_mismatch",
                                     f"config {key!r}={actual!r} does not match {expected_value!r}",
                                     model_kind=model_kind))
    # The worker config must identify the specific paired member even though
    # model_kind is already present at receipt top-level.
    if observed.get("model_kind") != model_kind:
        failures.append(_failure("model_kind_mismatch", "receipt config model_kind differs from requested member",
                                 model_kind=model_kind))
    return {"observed": observed, "checks": checks}


def _manifest_binding(source: str | Path | Mapping[str, Any]):
    payload, path = _read_json(source)
    try:
        validated = validate_manifest(dict(payload))
    except (TypeError, ValueError, KeyError) as error:
        return None, path, None, [_failure("invalid_manifest", str(error))]
    train_ids = [str(row["case_id"]) for row in validated["cases"] if row.get("split") == "train"]
    qualification_ids = [str(row["case_id"]) for row in validated["cases"] if row.get("split") == "qualification"]
    if not train_ids:
        return validated, path, train_ids, [_failure("empty_train_split", "manifest has no train cases")]
    return validated, path, train_ids, [{"code": "manifest_loaded", "message": "manifest validated without opening HDF5 assets"}]


def _parse_argv(argv: Any) -> dict[str, Any]:
    if not isinstance(argv, list):
        return {}
    result: dict[str, Any] = {}
    index = 0
    while index < len(argv):
        item = argv[index]
        if isinstance(item, str) and item.startswith("--"):
            key = item[2:].replace("-", "_")
            if key.startswith("no_"):
                result[key[3:]] = False
            elif index + 1 < len(argv) and not str(argv[index + 1]).startswith("--"):
                value: Any = argv[index + 1]
                if isinstance(value, str):
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                result[key] = value
                index += 1
            else:
                result[key] = True
        index += 1
    return result


def _protocol_binding(index_source: str | Path | Mapping[str, Any] | None,
                      *, manifest_path: Path | None,
                      expected_protocol: Mapping[str, Any] | None,
                      model_paths: Mapping[str, Path],
                      failures: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind protocol declarations to read-only index/spec artifacts."""
    expected = dict(DEFAULT_PROTOCOL)
    if expected_protocol:
        expected.update(dict(expected_protocol))
    binding: dict[str, Any] = {
        "expected": expected,
        "source": None,
        "job_specs": {},
        "normalization_transition_count": {
            "expected": expected.get("normalization_transitions"),
            "attested_by_checkpoint": False,
            "attested_by_receipt_config": False,
            "attested_by_job_spec": False,
        },
    }
    if index_source is None:
        binding["source"] = "caller_protocol"
        # In-memory protocol overrides are useful for unit tests, but they do
        # not independently prove what a worker was launched with.
        binding["attestation_limit"] = "no index/job spec supplied"
        return binding
    index, index_path = _read_json(index_source)
    if not isinstance(index, Mapping):
        failures.append(_failure("invalid_index", "preprofile index is not a JSON object"))
        return binding
    binding["source"] = {"path": str(index_path) if index_path else "<in-memory>",
                          "sha256": sha256_file(index_path) if index_path else _canonical_hash(index)}
    declared = index.get("training_protocol")
    if isinstance(declared, Mapping):
        expected.update(dict(declared))
        binding["expected"] = expected
    dataset_ref = index.get("dataset", {}).get("manifest") if isinstance(index.get("dataset"), Mapping) else None
    if manifest_path is not None and isinstance(dataset_ref, Mapping):
        declared_path = dataset_ref.get("path")
        declared_sha = dataset_ref.get("sha256")
        if isinstance(declared_path, str):
            resolved_declared = _resolve(declared_path, base=index_path.parent if index_path else None)
            if resolved_declared.resolve() != manifest_path.resolve():
                failures.append(_failure("manifest_index_path_mismatch",
                                         f"manifest {manifest_path} differs from index binding {resolved_declared}"))
            if isinstance(declared_sha, str) and resolved_declared.is_file() and sha256_file(resolved_declared) != declared_sha:
                failures.append(_failure("manifest_index_hash_mismatch", "index manifest SHA-256 does not match file"))
    jobs = index.get("jobs")
    jobs_by_model = {}
    if isinstance(jobs, list):
        for job in jobs:
            if not isinstance(job, Mapping):
                continue
            kind = str(job.get("model_kind", ""))
            spec_path = job.get("path")
            if kind not in MODEL_KINDS or not isinstance(spec_path, str):
                continue
            spec = None
            resolved = _resolve(spec_path, base=index_path.parent if index_path else None)
            try:
                spec = json.loads(resolved.read_text())
            except (OSError, ValueError) as error:
                failures.append(_failure("missing_job_spec", f"cannot read {resolved}: {error}", model_kind=kind))
                continue
            if not isinstance(spec, Mapping):
                failures.append(_failure("invalid_job_spec", f"job spec {resolved} is not an object", model_kind=kind))
                continue
            args = _parse_argv(spec.get("argv"))
            jobs_by_model[kind] = {"path": str(resolved), "sha256": sha256_file(resolved),
                                   "job_id": job.get("job_id"), "argv": args}
            declared_job_sha = job.get("sha256")
            if not isinstance(declared_job_sha, str) or len(declared_job_sha) != 64:
                failures.append(_failure("job_spec_sha_missing", "index job has no declared SHA-256", model_kind=kind))
            elif declared_job_sha != jobs_by_model[kind]["sha256"]:
                failures.append(_failure("job_spec_sha_mismatch", "index job SHA-256 differs from spec", model_kind=kind))
            for arg_name, protocol_key in (
                    ("model", "model_kind"), ("seed", "paired_seed"), ("updates", "updates"),
                    ("centers", "centers_per_update"), ("hidden", "hidden"),
                    ("learning_rate", "learning_rate"), ("normalization_transitions", "normalization_transitions"),
                    ("checkpoint_every", "checkpoint_every"), ("log_every", "log_every"),
                    ("validation_every", "validation_every")):
                if arg_name not in args:
                    failures.append(_failure("job_arg_missing", f"job spec lacks --{arg_name.replace('_', '-')}", model_kind=kind))
                    continue
                expected_value = expected.get(protocol_key)
                actual = args[arg_name]
                if arg_name == "model":
                    equal = actual == kind
                elif isinstance(expected_value, float):
                    equal = _same_float(actual, expected_value)
                else:
                    equal = actual == expected_value
                if not equal:
                    failures.append(_failure("job_protocol_mismatch",
                                             f"job --{arg_name.replace('_', '-')}={actual!r} does not match {expected_value!r}",
                                             model_kind=kind))
            if args.get("evaluate_milestones", None) is not expected.get("evaluate_milestones"):
                failures.append(_failure("job_protocol_mismatch", "job milestone evaluation flag differs", model_kind=kind))
            if not isinstance(args.get("no_evaluate_milestones"), (bool, type(None))):
                pass
        binding["normalization_transition_count"]["attested_by_job_spec"] = all(
            kind in jobs_by_model for kind in MODEL_KINDS
        ) and not any(row.get("code") == "job_protocol_mismatch" and row.get("model_kind") in MODEL_KINDS
                      for row in failures)
    else:
        failures.append(_failure("index_jobs_missing", "preprofile index has no jobs list"))
    for kind in MODEL_KINDS:
        if kind not in jobs_by_model:
            failures.append(_failure("job_missing", "index has no job for model kind", model_kind=kind))
    binding["job_specs"] = jobs_by_model
    return binding


def _validate_training_evidence(evidence: Any, *, model_kind: str,
                                expected: Mapping[str, Any], train_ids: Sequence[str],
                                failures: list[dict[str, Any]], require_evidence: bool) -> dict[str, Any] | None:
    """Validate provenance emitted by the current training entrypoint.

    A legacy checkpoint remains loadable by ``core_learning``.  The collector
    reports it as ``missing_legacy`` and, in strict mode, rejects it as a
    formal preprofile artifact rather than fabricating a construction digest.
    """
    if not isinstance(evidence, Mapping):
        if require_evidence:
            failures.append(_failure("evidence_missing_legacy",
                                     "checkpoint predates core.training.evidence.v1; no initial digest or prior history is available",
                                     model_kind=model_kind))
        return None
    evidence = dict(evidence)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        failures.append(_failure("evidence_schema_mismatch", "unsupported training evidence schema", model_kind=model_kind))
    if evidence.get("status") != "complete":
        failures.append(_failure("evidence_incomplete", "training evidence is explicitly incomplete", model_kind=model_kind))
    initialization = evidence.get("initialization")
    if not isinstance(initialization, Mapping):
        failures.append(_failure("initialization_evidence_missing", "construction-time parameter evidence is missing", model_kind=model_kind))
    else:
        if initialization.get("schema") != INITIALIZATION_EVIDENCE_SCHEMA:
            failures.append(_failure("initialization_evidence_schema_mismatch", "unsupported initialization evidence schema", model_kind=model_kind))
        for key, value in (("status", "captured"), ("model_kind", model_kind),
                           ("seed", expected.get("paired_seed", DEFAULT_RUN_SEED)),
                           ("hidden", expected.get("hidden")), ("constructed_before_first_update", True),
                           ("construction_update", 0)):
            if initialization.get(key) != value:
                failures.append(_failure("initialization_evidence_mismatch",
                                         f"initialization evidence {key} does not match protocol", model_kind=model_kind))
        if not _valid_sha(initialization.get("parameter_digest")):
            failures.append(_failure("initialization_digest_missing", "construction-time parameter digest is absent or malformed", model_kind=model_kind))
    normalization = evidence.get("normalization")
    if not isinstance(normalization, Mapping):
        failures.append(_failure("normalization_evidence_missing", "normalization sampling evidence is missing", model_kind=model_kind))
    else:
        if normalization.get("schema") != NORMALIZATION_EVIDENCE_SCHEMA:
            failures.append(_failure("normalization_evidence_schema_mismatch", "unsupported normalization evidence schema", model_kind=model_kind))
        if normalization.get("source_split") != "train" or normalization.get("target_reference") != "raw_dual_increment_train_shared":
            failures.append(_failure("normalization_evidence_binding_mismatch", "normalization evidence is not the shared train raw-target scale", model_kind=model_kind))
        expected_transitions = expected.get("normalization_transitions")
        if expected_transitions is not None and normalization.get("requested_maximum_transitions") != expected_transitions:
            failures.append(_failure("normalization_transition_budget_mismatch", "normalization evidence budget differs from protocol", model_kind=model_kind))
        selected = normalization.get("selected_transition_bindings")
        if not isinstance(selected, list) or normalization.get("selected_transition_count") != len(selected) or len(selected) < 1:
            failures.append(_failure("normalization_transition_count_mismatch", "normalization evidence does not contain its exact selected transition count", model_kind=model_kind))
        try:
            available_count = int(normalization.get("available_transition_count", -1))
            selected_count = int(normalization.get("selected_transition_count", -1))
            if available_count < selected_count:
                raise ValueError
        except (TypeError, ValueError):
            failures.append(_failure("normalization_available_count_mismatch", "normalization evidence has no valid available transition count", model_kind=model_kind))
        if list(normalization.get("train_case_ids", [])) != list(train_ids):
            failures.append(_failure("normalization_case_binding_mismatch", "normalization evidence train cases differ from manifest", model_kind=model_kind))
        selected_ids = [str(item.get("case_id")) for item in selected or [] if isinstance(item, Mapping)]
        if any(case_id not in set(train_ids) for case_id in selected_ids):
            failures.append(_failure("normalization_future_case_binding", "normalization evidence names a non-train case", model_kind=model_kind))
        expected_selected_ids = list(dict.fromkeys(selected_ids))
        if list(normalization.get("selected_case_ids", [])) != expected_selected_ids:
            failures.append(_failure("normalization_selected_case_mismatch", "normalization selected_case_ids disagrees with transition bindings", model_kind=model_kind))
        counts = normalization.get("selected_transition_counts")
        try:
            counts_match = isinstance(counts, Mapping) and sum(int(value) for value in counts.values()) == len(selected or [])
        except (TypeError, ValueError):
            counts_match = False
        if isinstance(counts, Mapping) and set(str(key) for key in counts) != set(str(case_id) for case_id in train_ids):
            counts_match = False
        if not counts_match:
            failures.append(_failure("normalization_transition_counts_mismatch", "normalization per-case counts disagree with bindings", model_kind=model_kind))
    prior = evidence.get("residual_prior")
    if not isinstance(prior, Mapping):
        failures.append(_failure("prior_evidence_missing", "residual prior execution evidence is missing", model_kind=model_kind))
    else:
        residual = model_kind == "graph_residual"
        if prior.get("schema") != PRIOR_EVIDENCE_SCHEMA:
            failures.append(_failure("prior_evidence_schema_mismatch", "unsupported residual prior evidence schema", model_kind=model_kind))
        if bool(prior.get("enabled")) != residual:
            failures.append(_failure("prior_evidence_enabled_mismatch", "residual prior enabled flag differs from model kind", model_kind=model_kind))
        if residual:
            if prior.get("history_complete") is not True or prior.get("execution_calls") != int(expected.get("updates", -1)):
                failures.append(_failure("prior_evidence_execution_count_mismatch", "residual prior evidence does not cover every training update", model_kind=model_kind))
            if prior.get("finite") is not True or int(prior.get("rows", 0)) < 1:
                failures.append(_failure("prior_evidence_nonfinite", "residual prior evidence is non-finite or empty", model_kind=model_kind))
        elif prior.get("execution_calls", 0) != 0:
            failures.append(_failure("prior_evidence_unexpected_execution", "raw/MLP checkpoint reports residual prior executions", model_kind=model_kind))
    return evidence


def _load_checkpoint(receipt: Mapping[str, Any], receipt_path: Path, *, model_kind: str,
                     expected: Mapping[str, Any], train_ids: Sequence[str],
                     failures: list[dict[str, Any]], require_evidence: bool) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    checkpoint_ref = receipt.get("checkpoint")
    if not isinstance(checkpoint_ref, Mapping):
        failures.append(_failure("missing_checkpoint_ref", "receipt has no checkpoint reference", model_kind=model_kind))
        return None, {}
    path_value = checkpoint_ref.get("path")
    if not isinstance(path_value, str):
        failures.append(_failure("missing_checkpoint_path", "checkpoint reference has no path", model_kind=model_kind))
        return None, {}
    path, rebound_from = _resolve_artifact(path_value, receipt_path=receipt_path)
    expected_sha = checkpoint_ref.get("sha256")
    expected_bytes = checkpoint_ref.get("bytes")
    if not path.is_file():
        failures.append(_failure("checkpoint_missing", f"checkpoint does not exist: {path}", model_kind=model_kind))
        return None, {"path": str(path), "sha256": None, "bytes": None}
    actual_sha = sha256_file(path)
    actual_bytes = path.stat().st_size
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or actual_sha != expected_sha:
        failures.append(_failure("checkpoint_hash_mismatch", f"checkpoint SHA-256 mismatch: {path}", model_kind=model_kind))
    if expected_bytes is not None and int(expected_bytes) != actual_bytes:
        failures.append(_failure("checkpoint_size_mismatch", f"checkpoint byte count mismatch: {path}", model_kind=model_kind))
    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as error:  # pragma: no cover - defensive
        failures.append(_failure("checkpoint_unreadable", f"cannot load checkpoint {path}: {error}", model_kind=model_kind))
        return None, {"path": str(path), "sha256": actual_sha, "bytes": actual_bytes}
    if not isinstance(payload, Mapping):
        failures.append(_failure("invalid_checkpoint", "checkpoint payload is not a mapping", model_kind=model_kind))
        return None, {"path": str(path), "sha256": actual_sha, "bytes": actual_bytes}
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        failures.append(_failure("checkpoint_schema_mismatch", "unsupported checkpoint schema", model_kind=model_kind))
    if payload.get("model_kind") != model_kind or int(payload.get("seed", -1)) != int(expected.get("paired_seed", DEFAULT_RUN_SEED)):
        failures.append(_failure("checkpoint_identity_mismatch", "checkpoint model kind or seed differs", model_kind=model_kind))
    if int(payload.get("update", -1)) != int(expected.get("updates", -1)):
        failures.append(_failure("checkpoint_update_mismatch", "checkpoint update differs from protocol", model_kind=model_kind))
    evidence = _validate_training_evidence(
        payload.get("evidence"), model_kind=model_kind, expected=expected,
        train_ids=train_ids, failures=failures, require_evidence=require_evidence,
    )
    sampler_state = payload.get("sampler_state")
    sampler_report = receipt.get("sampler")
    if not isinstance(sampler_state, Mapping):
        failures.append(_failure("missing_sampler_state", "checkpoint has no sampler_state", model_kind=model_kind))
    else:
        if sampler_state.get("version") != "core.sampler.v1":
            failures.append(_failure("sampler_schema_mismatch", "unsupported sampler state schema", model_kind=model_kind))
        if int(sampler_state.get("seed", -1)) != int(expected.get("sampler_seed", DEFAULT_RUN_SEED)):
            failures.append(_failure("sampler_seed_mismatch", "sampler state seed differs", model_kind=model_kind))
        if list(sampler_state.get("case_ids", [])) != list(train_ids):
            failures.append(_failure("sampler_case_binding_mismatch", "sampler cases differ from manifest train split", model_kind=model_kind))
        if int(sampler_state.get("centers_per_update", -1)) != int(expected.get("centers_per_update", -1)):
            failures.append(_failure("sampler_centers_mismatch", "sampler center count differs", model_kind=model_kind))
        if int(sampler_state.get("draws", -1)) != int(expected.get("updates", -1)):
            failures.append(_failure("sampler_draw_count_mismatch", "sampler draw count differs from updates", model_kind=model_kind))
        if not isinstance(sampler_state.get("rng_state"), Mapping):
            failures.append(_failure("missing_sampler_rng", "sampler state has no RNG state", model_kind=model_kind))
    if not isinstance(payload.get("rng_state"), Mapping) or not {"python", "numpy", "torch"} <= set(payload["rng_state"]):
        failures.append(_failure("missing_rng_state", "checkpoint does not contain python/numpy/torch RNG state", model_kind=model_kind))
    if not isinstance(sampler_report, Mapping):
        failures.append(_failure("missing_sampler_report", "receipt has no sampler summary", model_kind=model_kind))
    else:
        for key, expected_value in (("centers_per_update", expected.get("centers_per_update")),
                                    ("draws", expected.get("updates"))):
            if int(sampler_report.get(key, -1)) != int(expected_value):
                failures.append(_failure("sampler_report_mismatch", f"receipt sampler {key} differs", model_kind=model_kind))
        if list(sampler_state.get("case_ids", [])) != list(train_ids):
            failures.append(_failure("sampler_report_case_binding_mismatch", "receipt/checkpoint sampler case mismatch", model_kind=model_kind))
    norm = payload.get("normalization")
    try:
        normalized = Normalization.from_dict(norm)
    except (TypeError, KeyError, ValueError) as error:
        normalized = None
        failures.append(_failure("invalid_normalization", str(error), model_kind=model_kind))
    if normalized is not None:
        if normalized.source_split != "train" or normalized.target_reference != "raw_dual_increment_train_shared":
            failures.append(_failure("normalization_binding_mismatch", "normalization is not the shared train raw-target scale", model_kind=model_kind))
        if receipt.get("normalization") != normalized.as_dict():
            failures.append(_failure("receipt_checkpoint_normalization_mismatch", "receipt normalization differs from checkpoint", model_kind=model_kind))
    if payload.get("config") != receipt.get("config"):
        failures.append(_failure("receipt_checkpoint_config_mismatch", "receipt config differs from checkpoint config", model_kind=model_kind))
    state_summary = _state_summary(payload.get("model_state", payload.get("state_dict")),
                                   model_kind=model_kind, hidden=int(expected.get("hidden", -1)),
                                   failures=failures)
    return payload, {"path": str(path), "declared_path": str(path_value),
                     "rebound_from_missing_path": str(rebound_from) if rebound_from else None,
                     "sha256": actual_sha, "bytes": actual_bytes,
                     "update": int(payload.get("update", -1)), "state": state_summary,
                     "normalization": normalized.as_dict() if normalized is not None else None,
                     "evidence": evidence,
                     "evidence_status": "complete" if evidence is not None else "missing_legacy",
                     "sampler_state": sampler_state}


def _inspect_member(source: str | Path, *, model_kind: str, expected: Mapping[str, Any],
                    train_ids: Sequence[str], require_evidence: bool) -> tuple[dict[str, Any], list[dict[str, Any]], Mapping[str, Any] | None]:
    failures: list[dict[str, Any]] = []
    receipt_path = _resolve(source)
    member: dict[str, Any] = {"receipt_path": str(receipt_path), "model_kind": model_kind}
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError) as error:
        failures.append(_failure("receipt_unreadable", str(error), model_kind=model_kind))
        return member | {"status": "fail", "failures": failures}, failures, None
    if not isinstance(receipt, Mapping):
        failures.append(_failure("invalid_receipt", "training receipt is not a JSON object", model_kind=model_kind))
        return member | {"status": "fail", "failures": failures}, failures, None
    member["receipt_sha256"] = sha256_file(receipt_path)
    member["receipt_schema"] = receipt.get("schema")
    if receipt.get("schema") != TRAINING_SCHEMA:
        failures.append(_failure("receipt_schema_mismatch", "unsupported training receipt schema", model_kind=model_kind))
    for key, expected_value in (("model_kind", model_kind), ("seed", expected.get("paired_seed", DEFAULT_RUN_SEED)),
                                ("run_id", f"{model_kind}-seed{expected.get('paired_seed', DEFAULT_RUN_SEED)}"),
                                ("completed_updates", expected.get("updates"))):
        if receipt.get(key) != expected_value:
            failures.append(_failure("receipt_identity_mismatch", f"receipt {key} differs from protocol", model_kind=model_kind))
    if receipt.get("checkpoint_verified") is not True:
        failures.append(_failure("checkpoint_not_verified", "receipt does not mark checkpoint_verified=true", model_kind=model_kind))
    receipt_evidence = receipt.get("evidence")
    if not isinstance(receipt_evidence, Mapping):
        if require_evidence:
            failures.append(_failure("receipt_evidence_missing", "training receipt predates evidence.v1", model_kind=model_kind))
    elif receipt.get("evidence_status") != "complete" or receipt_evidence.get("status") != "complete":
        failures.append(_failure("receipt_evidence_incomplete", "training receipt evidence is incomplete", model_kind=model_kind))
    member["config"] = _compare_config(receipt, model_kind=model_kind, expected=expected, failures=failures)
    progress_value = receipt.get("progress_path")
    progress = None
    if not isinstance(progress_value, str):
        failures.append(_failure("missing_progress_path", "receipt has no progress sidecar path", model_kind=model_kind))
    else:
        progress_path, progress_rebound = _resolve_artifact(progress_value, receipt_path=receipt_path)
        member["progress_path"] = str(progress_path)
        member["progress_declared_path"] = progress_value
        member["progress_rebound_from_missing_path"] = str(progress_rebound) if progress_rebound else None
        try:
            progress = json.loads(progress_path.read_text())
        except (OSError, ValueError) as error:
            failures.append(_failure("progress_unreadable", str(error), model_kind=model_kind))
        if isinstance(progress, Mapping):
            if progress.get("schema") != PROGRESS_SCHEMA or progress.get("status") != "completed":
                failures.append(_failure("progress_incomplete", "progress sidecar is not a completed core.training.progress.v1 record", model_kind=model_kind))
            for key, expected_value in (("run_id", f"{model_kind}-seed{expected.get('paired_seed', DEFAULT_RUN_SEED)}"),
                                        ("model_kind", model_kind), ("seed", expected.get("paired_seed", DEFAULT_RUN_SEED)),
                                        ("update", expected.get("updates")), ("requested_updates", expected.get("updates"))):
                if progress.get(key) != expected_value:
                    failures.append(_failure("progress_identity_mismatch", f"progress {key} differs from protocol", model_kind=model_kind))
        else:
            failures.append(_failure("invalid_progress", "progress sidecar is not a JSON object", model_kind=model_kind))
    payload, checkpoint_info = _load_checkpoint(receipt, receipt_path, model_kind=model_kind,
                                                 expected=expected, train_ids=train_ids,
                                                 failures=failures, require_evidence=require_evidence)
    if payload is not None:
        checkpoint_evidence = payload.get("evidence")
        if isinstance(receipt_evidence, Mapping) and isinstance(checkpoint_evidence, Mapping):
            if dict(receipt_evidence) != dict(checkpoint_evidence):
                failures.append(_failure("receipt_checkpoint_evidence_mismatch",
                                         "receipt evidence differs from checkpoint evidence", model_kind=model_kind))
    member["checkpoint"] = checkpoint_info
    member["evidence"] = receipt_evidence if isinstance(receipt_evidence, Mapping) else None
    member["progress"] = progress
    member["status"] = "pass" if not failures else "fail"
    member["failures"] = failures
    return member, failures, payload


def collect_preprofile(receipts: Mapping[str, str | Path] | Sequence[str | Path], *, manifest: str | Path | Mapping[str, Any],
                       index: str | Path | Mapping[str, Any] | None = None,
                       expected_protocol: Mapping[str, Any] | None = None,
                       output: str | Path | None = None,
                       require_evidence: bool = True) -> dict[str, Any]:
    """Collect and compare all three completed preprofile artifacts.

    The function returns a report even when artifacts are missing or invalid;
    the CLI uses exit code 2 for a failed report.  No input is modified.
    """
    failures: list[dict[str, Any]] = []
    manifest_payload, manifest_path, train_ids, manifest_notes = _manifest_binding(manifest)
    for note in manifest_notes:
        if note.get("code") != "manifest_loaded":
            failures.append(note)
    if manifest_payload is None:
        manifest_payload = {}
    manifest_ref = {"path": str(manifest_path) if manifest_path else "<in-memory>",
                    "sha256": sha256_file(manifest_path) if manifest_path and manifest_path.is_file() else _canonical_hash(manifest_payload),
                    "canonical_sha256": _canonical_hash(manifest_payload) if manifest_payload else None,
                    "train_case_ids": list(train_ids or [])}
    expected = dict(DEFAULT_PROTOCOL)
    if expected_protocol:
        expected.update(dict(expected_protocol))
    # An index is authoritative for the production protocol.  It may update
    # the default expected map and emits binding failures for bad specs.
    protocol_binding = _protocol_binding(index, manifest_path=manifest_path,
                                         expected_protocol=expected_protocol,
                                         model_paths={}, failures=failures)
    expected = dict(protocol_binding.get("expected", expected))
    if manifest_ref["canonical_sha256"] is not None:
        expected["manifest_sha256"] = manifest_ref["canonical_sha256"]
        expected["manifest_formal_release"] = bool(manifest_payload.get("formal_release") is True)
        protocol_binding["expected"] = expected
    if manifest_path is not None and isinstance(index, (str, Path)):
        # The index helper already compares the index manifest path/hash when
        # it is provided; this branch intentionally performs no extra I/O.
        pass
    if isinstance(receipts, Mapping):
        receipt_map = {str(kind): value for kind, value in receipts.items()}
    else:
        receipt_map = {}
        for source in receipts:
            try:
                payload = json.loads(_resolve(source).read_text())
                kind = str(payload.get("model_kind", ""))
            except (OSError, ValueError):
                kind = ""
            if kind in MODEL_KINDS and kind not in receipt_map:
                receipt_map[kind] = source
    models: dict[str, Any] = {}
    payloads: dict[str, Mapping[str, Any]] = {}
    for kind in MODEL_KINDS:
        source = receipt_map.get(kind)
        if source is None:
            row = {"model_kind": kind, "status": "fail", "failures": [_failure("receipt_missing", "no receipt supplied", model_kind=kind)]}
            models[kind] = row
            failures.extend(row["failures"])
            continue
        row, member_failures, payload = _inspect_member(source, model_kind=kind, expected=expected,
                                                         train_ids=train_ids or [], require_evidence=require_evidence)
        models[kind] = row
        failures.extend(member_failures)
        if payload is not None:
            payloads[kind] = payload
    # Cross-member checks only run when all three payloads are loadable.  A
    # missing member remains a direct failure above and never gets inferred.
    cross: dict[str, Any] = {
        "all_members_present": all(kind in payloads for kind in MODEL_KINDS),
        "shared_normalization": False,
        "shared_normalization_evidence": False,
        "shared_target_scale": False,
        "paired_sampler_state": False,
        "paired_model_initialization_reconstruction": False,
        "initialization_digest_matches_fresh": False,
        "raw_residual_topology": False,
        "residual_prior": {
            "declared_by_model_kind": "graph_residual",
            "checkpoint_runtime_attested": False,
            "evidence_limit": "final checkpoint does not prove prior subtraction/addition was exercised",
        },
    }
    if all(kind in payloads for kind in MODEL_KINDS):
        norm_values = [payloads[kind].get("normalization") for kind in MODEL_KINDS]
        cross["shared_normalization"] = all(value == norm_values[0] for value in norm_values[1:])
        if not cross["shared_normalization"]:
            failures.append(_failure("normalization_not_shared", "the three checkpoints do not carry identical normalization arrays"))
        evidence_values = [payloads[kind].get("evidence", {}).get("normalization")
                           if isinstance(payloads[kind].get("evidence"), Mapping) else None
                           for kind in MODEL_KINDS]
        cross["shared_normalization_evidence"] = (
            all(value is not None for value in evidence_values)
            and all(value == evidence_values[0] for value in evidence_values[1:])
        )
        if require_evidence and all(value is not None for value in evidence_values) and not cross["shared_normalization_evidence"]:
            failures.append(_failure("normalization_evidence_not_shared",
                                     "the three checkpoints do not carry identical normalization sampling evidence"))
        state_values = [payloads[kind].get("model_state", payloads[kind].get("state_dict", {}))
                        for kind in MODEL_KINDS]
        target_scales = [state.get("target_scale") for state in state_values]
        cross["shared_target_scale"] = (
            all(torch.is_tensor(value) for value in target_scales)
            and all(torch.equal(target_scales[0], value) for value in target_scales[1:])
            and bool(torch.equal(target_scales[0], torch.ones_like(target_scales[0])))
        )
        if not cross["shared_target_scale"]:
            failures.append(_failure("target_scale_not_shared", "checkpoint target_scale buffers are not identical unit scales"))
        sampler_values = [payloads[kind].get("sampler_state") for kind in MODEL_KINDS]
        # RNG state is expected to be exactly equal for paired runs after the
        # same number of draws.  Convert numpy values before canonicalizing.
        comparable = [_jsonable(value) if isinstance(value, Mapping) else None
                      for value in sampler_values]
        cross["paired_sampler_state"] = all(value == comparable[0] for value in comparable[1:])
        if not cross["paired_sampler_state"]:
            failures.append(_failure("sampler_not_paired", "the three checkpoints do not carry the same sampler stream identity"))
        fresh_states = {}
        fresh_digests = {}
        for kind in MODEL_KINDS:
            try:
                state, digest = _fresh_initial_state(kind, int(expected.get("hidden", -1)),
                                                     int(expected.get("paired_seed", DEFAULT_RUN_SEED)))
                fresh_states[kind] = state
                fresh_digests[kind] = digest
            except (TypeError, ValueError, RuntimeError) as error:
                failures.append(_failure("initialization_reconstruction_error", str(error), model_kind=kind))
        common_equal = False
        graph_equal = False
        if len(fresh_states) == 3:
            common_keys = set(fresh_states["mlp"]) & set(fresh_states["graph_raw"]) & set(fresh_states["graph_residual"])
            common_keys = {key for key in common_keys
                           if key.startswith("encoder.") or key.startswith("head.")}
            common_equal = bool(common_keys) and all(
                torch.equal(fresh_states["mlp"][key], fresh_states["graph_raw"][key]) and
                torch.equal(fresh_states["mlp"][key], fresh_states["graph_residual"][key])
                for key in common_keys)
            graph_equal = set(fresh_states["graph_raw"]) == set(fresh_states["graph_residual"]) and all(
                torch.equal(fresh_states["graph_raw"][key], fresh_states["graph_residual"][key])
                for key in fresh_states["graph_raw"]
            )
        cross["paired_model_initialization_reconstruction"] = bool(common_equal and graph_equal)
        if not cross["paired_model_initialization_reconstruction"]:
            failures.append(_failure("initialization_pair_mismatch", "fresh seed reconstruction did not produce the paired common modules/topology"))
        initialization_digest_matches = True
        initialization_digest_available = True
        for kind in MODEL_KINDS:
            evidence = payloads[kind].get("evidence")
            digest = evidence.get("initialization", {}).get("parameter_digest") if isinstance(evidence, Mapping) else None
            initialization_digest_available = bool(initialization_digest_available and _valid_sha(digest))
            initialization_digest_matches = bool(initialization_digest_matches and digest == fresh_digests.get(kind))
        cross["initialization_digest_matches_fresh"] = (
            initialization_digest_matches if initialization_digest_available else None
        )
        if require_evidence and initialization_digest_available and not initialization_digest_matches:
            failures.append(_failure("initialization_digest_mismatch",
                                     "reported construction digest does not match deterministic seeded construction"))
        raw_state = payloads["graph_raw"].get("model_state", payloads["graph_raw"].get("state_dict", {}))
        residual_state = payloads["graph_residual"].get("model_state", payloads["graph_residual"].get("state_dict", {}))
        cross["raw_residual_topology"] = set(raw_state) == set(residual_state) and all(
            tuple(raw_state[key].shape) == tuple(residual_state[key].shape) and str(raw_state[key].dtype) == str(residual_state[key].dtype)
            for key in raw_state if torch.is_tensor(raw_state[key]) and torch.is_tensor(residual_state.get(key))
        )
        if not cross["raw_residual_topology"]:
            failures.append(_failure("raw_residual_topology_mismatch", "raw and residual checkpoint state topologies differ"))
        residual_evidence = payloads["graph_residual"].get("evidence")
        residual_prior = residual_evidence.get("residual_prior") if isinstance(residual_evidence, Mapping) else None
        if isinstance(residual_prior, Mapping):
            cross["residual_prior"] = {
                "declared_by_model_kind": "graph_residual",
                "checkpoint_runtime_attested": bool(
                    residual_prior.get("schema") == PRIOR_EVIDENCE_SCHEMA
                    and residual_prior.get("enabled") is True
                    and residual_prior.get("history_complete") is True
                    and residual_prior.get("finite") is True
                    and int(residual_prior.get("execution_calls", -1)) == int(expected.get("updates", -1))
                ),
                "execution_calls": residual_prior.get("execution_calls"),
                "rows": residual_prior.get("rows"),
                "finite": residual_prior.get("finite"),
                "evidence_limit": "execution statistics are output attestations and remain bound to checkpoint/receipt hashes",
            }
        cross["fresh_initial_state_digests"] = fresh_digests
    else:
        cross["fresh_initial_state_digests"] = {}
    limitations = [
        "the evidence is an output attestation and is hash-bound by the checkpoint/receipt; this collector does not execute a second training pass",
        "resume evidence keeps the original construction digest and records the loaded trained-state digest separately",
        "this collector validates train case IDs from the manifest but intentionally does not open HDF5 files to recount transitions",
    ]
    protocol_binding["normalization_transition_count"]["attested_by_checkpoint"] = bool(
        all(isinstance(payloads.get(kind, {}).get("evidence"), Mapping)
            and isinstance(payloads.get(kind, {}).get("evidence", {}).get("normalization"), Mapping)
            for kind in MODEL_KINDS)
    )
    protocol_binding["normalization_transition_count"]["attested_by_receipt_config"] = False
    report = {
        "schema": COLLECTOR_SCHEMA,
        "status": "pass" if not failures else "fail",
        "failure_count": len(failures),
        "failures": failures,
        "manifest": manifest_ref,
        "protocol": protocol_binding,
        "models": models,
        "cross_model": cross,
        "evidence_limits": limitations,
        "require_evidence": bool(require_evidence),
        "read_only": True,
        "hdf5_opened": False,
    }
    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collect", nargs="?", default="collect")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--index")
    parser.add_argument("--mlp", required=True)
    parser.add_argument("--graph-raw", required=True)
    parser.add_argument("--graph-residual", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-legacy-evidence", action="store_true",
                        help="report old checkpoints as missing_legacy instead of failing strict evidence checks")
    args = parser.parse_args(argv)
    report = collect_preprofile(
        {"mlp": args.mlp, "graph_raw": args.graph_raw, "graph_residual": args.graph_residual},
        manifest=args.manifest, index=args.index, output=args.output,
        require_evidence=not args.allow_legacy_evidence,
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
