#!/usr/bin/env python3
"""Bind F3 launch, training, evaluation, and progress JSON receipts.

This adapter is the JSON-only boundary between the VRAM launch receipt, one
``core.training.v1`` receipt, independent ``core.evaluation.v1`` outputs and
the existing F3 batch reducer.  It deliberately does not open a manifest,
checkpoint, trajectory, case HDF5, or progress path.  The progress path is a
declared string inside the small JSON sidecar and is compared only as data.

The adapter creates short-lived ``core.f3.rollout_batch_item.v1`` envelopes in
a private temporary directory so that it can call the existing
``aggregate_rollout_files`` API without changing that reducer.  Those
envelopes are not production artifacts and are removed before return.

Successful results are source-bound diagnostic JSON closure only.  They never
mint qualification, T1/T2 credit, execution authority, or any registry,
ledger, denominator, or gate mutation.  A missing or conflicting input is
always fail-closed.
"""
from __future__ import annotations

import argparse
import copy
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from scripts import f3_rollout_batch_receipt_v1 as aggregator


SCHEMA = "core.f3.rollout_batch_closure_binding.v1"
REPORT_SCHEMA = "core.f3.rollout_batch_closure_binding_report.v1"
REPORT_ID = "f3-rollout-batch-closure-binding-report-v1"
LAUNCH_SCHEMA = "core.f3.vram_batch_launch_receipt.v1"
TRAINING_SCHEMA = "core.training.v1"
EVALUATION_SCHEMA = "core.evaluation.v1"
PROGRESS_SCHEMA = "core.rollout.progress.v1"
ITEM_SCHEMA = aggregator.ITEM_SCHEMA
EXPECTED_TRANSITIONS = aggregator.EXPECTED_TRANSITIONS
STATUSES = frozenset({"completed", "failed", "running"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO_CREDIT_FIELDS = (
    "qualification_credit", "credit", "T1_credit", "T2_credit", "T2_macro_credit"
)
FALSE_FORMAL_FIELDS = ("T1_numerical", "T2_macro", "T2_path", "qualification")
OUTPUT_SUFFIXES = {
    "evaluation": "-evaluation.json",
    "progress": "-evaluation-progress.json",
    "trajectory": "-trajectory.h5",
}


class ClosureBindingError(ValueError):
    """A malformed, conflicting, or unsafe closure input."""


def _fail(message: str) -> None:
    raise ClosureBindingError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _check_finite_json(value: Any, *, name: str = "value") -> None:
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
            _check_finite_json(item, name=f"{name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_finite_json(item, name=f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic JSON while rejecting non-finite values."""
    _check_finite_json(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum or (
            maximum is not None and value > maximum):
        bound = f" in [{minimum}, {maximum}]" if maximum is not None else f" >= {minimum}"
        _fail(f"{name} must be an integer{bound}")
    return value


def _string(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value or (nonempty and not value):
        _fail(f"{name} must be a {'non-empty ' if nonempty else ''}string without NUL")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _declared_path(value: Any, name: str) -> str:
    path = _string(value, name)
    if any(part == ".." for part in Path(path).parts):
        _fail(f"{name} must not contain parent traversal")
    return path


def _absolute_fresh_prefix(value: Any, name: str, case_id: str) -> str:
    prefix = _declared_path(value, name)
    path = Path(prefix)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if path.name in {"", ".", ".."}:
        _fail(f"{name} must identify a fresh output prefix")
    if case_id not in path.name:
        _fail(f"{name} must contain its case_id for namespace binding")
    return prefix


def _identifier(value: Any, name: str) -> str:
    text = _string(value, name)
    if "/" in text or "\\" in text:
        _fail(f"{name} must not contain path separators")
    return text


def _validate_zero_formal_claims(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in ZERO_CREDIT_FIELDS:
                if type(item) is not int or item != 0:
                    _fail(f"{name}.{key} must remain integer zero")
            if key in FALSE_FORMAL_FIELDS:
                if type(item) is not bool or item is not False:
                    _fail(f"{name}.{key} must remain false")
            if key == "formal_eligible" and (type(item) is not bool or item is not False):
                _fail(f"{name}.formal_eligible must remain false")
            _validate_zero_formal_claims(item, name=f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_zero_formal_claims(item, name=f"{name}[{index}]")


def _validate_diagnostic_envelope(value: Mapping[str, Any], *, name: str) -> None:
    _validate_zero_formal_claims(value, name=name)
    if value.get("diagnostic_only") is not True:
        _fail(f"{name}.diagnostic_only must be true")
    if value.get("formal") is not False:
        _fail(f"{name}.formal must be false")
    if value.get("formal_eligible") is not False:
        _fail(f"{name}.formal_eligible must be false")
    if value.get("qualification") is not False:
        _fail(f"{name}.qualification must be false")
    if value.get("qualification_credit") != 0 or value.get("credit") != 0:
        _fail(f"{name} credit must remain zero")


def _read_json(path: str | Path) -> tuple[Path, dict[str, Any], bytes]:
    report_path = Path(path).expanduser()
    if not report_path.is_file():
        _fail(f"missing JSON input: {report_path}")
    try:
        raw = report_path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ClosureBindingError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read strict UTF-8 JSON {report_path}: {error}")
    _check_finite_json(value, name=f"{report_path}")
    return report_path.resolve(), dict(_mapping(value, f"{report_path}")), raw


def _expected_binding(
    launch: Mapping[str, Any],
    case_id: str,
    case_binding: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    return {
        "manifest": {
            "path": launch["manifest_path"],
            "sha256": launch["manifest_sha256"],
        },
        "checkpoint": {
            "path": launch["checkpoint_path"],
            "sha256": launch["checkpoint_sha256"],
        },
        "case": {
            "case_id": case_id,
            "path": case_binding["path"],
            "sha256": case_binding["sha256"],
        },
    }


def _output_paths(prefix: str) -> dict[str, str]:
    return {name: prefix + suffix for name, suffix in OUTPUT_SUFFIXES.items()}


def validate_launch_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the launch-side JSON contract only."""
    value = _mapping(receipt, "launch_receipt")
    if value.get("schema") != LAUNCH_SCHEMA:
        _fail(f"launch_receipt.schema must be {LAUNCH_SCHEMA}")
    _validate_diagnostic_envelope(value, name="launch_receipt")
    status = _string(value.get("status"), "launch_receipt.status")
    if not status.startswith("diagnostic_launch_verified"):
        _fail("launch_receipt.status is not a verified diagnostic launch state")

    model = _identifier(value.get("model"), "launch_receipt.model")
    seed = _strict_int(value.get("seed"), "launch_receipt.seed")
    manifest_path = _declared_path(value.get("manifest_path"), "launch_receipt.manifest_path")
    manifest_sha256 = _sha256(value.get("manifest_sha256"), "launch_receipt.manifest_sha256")
    checkpoint_path = _declared_path(value.get("checkpoint_path"), "launch_receipt.checkpoint_path")
    checkpoint_sha256 = _sha256(value.get("checkpoint_sha256"), "launch_receipt.checkpoint_sha256")

    argv = _mapping(value.get("argv_contract"), "launch_receipt.argv_contract")
    if _strict_int(argv.get("maximum_steps"), "launch_receipt.argv_contract.maximum_steps") != EXPECTED_TRANSITIONS:
        _fail(f"launch_receipt.argv_contract.maximum_steps must be {EXPECTED_TRANSITIONS}")
    if _strict_bool(argv.get("diagnostic"), "launch_receipt.argv_contract.diagnostic") is not True:
        _fail("launch_receipt.argv_contract.diagnostic must be true")
    if argv.get("split") != "test":
        _fail("launch_receipt.argv_contract.split must be test")

    jobs_value = value.get("jobs")
    if not isinstance(jobs_value, Sequence) or isinstance(jobs_value, (str, bytes)) or not jobs_value:
        _fail("launch_receipt.jobs must be a non-empty array")
    jobs: dict[str, dict[str, Any]] = {}
    output_prefixes: set[str] = set()
    output_paths: dict[str, str] = {}
    for index, raw_job in enumerate(jobs_value):
        job = _mapping(raw_job, f"launch_receipt.jobs[{index}]")
        case_id = _identifier(job.get("case_id"), f"launch_receipt.jobs[{index}].case_id")
        if case_id in jobs:
            _fail(f"duplicate launch case_id: {case_id}")
        prefix = _absolute_fresh_prefix(
            job.get("output_prefix"),
            f"launch_receipt.jobs[{index}].output_prefix",
            case_id,
        )
        if prefix in output_prefixes:
            _fail(f"duplicate launch output prefix: {prefix}")
        output_prefixes.add(prefix)
        paths = _output_paths(prefix)
        for path_kind, path in paths.items():
            if path in output_paths:
                _fail(f"launch output path collision: {path}")
            output_paths[path] = f"{case_id}.{path_kind}"
        gpu_index = _strict_int(job.get("gpu_index"), f"launch_receipt.jobs[{index}].gpu_index")
        pid = _strict_int(job.get("pid"), f"launch_receipt.jobs[{index}].pid", minimum=1)
        if "model" in job and _identifier(job["model"], f"launch_receipt.jobs[{index}].model") != model:
            _fail(f"launch job {case_id} model drifts from launch receipt")
        if "seed" in job and _strict_int(job["seed"], f"launch_receipt.jobs[{index}].seed") != seed:
            _fail(f"launch job {case_id} seed drifts from launch receipt")
        jobs[case_id] = {
            "case_id": case_id,
            "output_prefix": prefix,
            "output_paths": paths,
            "gpu_index": gpu_index,
            "pid": pid,
            "checkpoint_path": checkpoint_path,
        }

    verification = value.get("launch_verification")
    if verification is not None:
        verification = _mapping(verification, "launch_receipt.launch_verification")
        for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
            if key in verification and _strict_int(
                    verification[key], f"launch_receipt.launch_verification.{key}") != 0:
                _fail(f"launch verification {key} must remain zero")
        for key in ("all_eight_processes_observed", "all_eight_progress_files_created"):
            if key in verification and _strict_bool(
                    verification[key], f"launch_receipt.launch_verification.{key}") is not True:
                _fail(f"launch verification {key} must be true when declared")

    return {
        "schema": LAUNCH_SCHEMA,
        "status": status,
        "model": model,
        "seed": seed,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": checkpoint_sha256,
        "argv_contract": {
            "maximum_steps": EXPECTED_TRANSITIONS,
            "diagnostic": True,
            "split": "test",
        },
        "jobs": jobs,
        "case_ids": tuple(sorted(jobs)),
        "output_prefixes": tuple(sorted(output_prefixes)),
        "fresh_namespace_binding": True,
    }


def validate_training_receipt(
    receipt: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate training provenance without opening the checkpoint."""
    value = _mapping(receipt, "training_receipt")
    if value.get("schema") != TRAINING_SCHEMA:
        _fail(f"training_receipt.schema must be {TRAINING_SCHEMA}")
    if value.get("evidence_status") != "complete":
        _fail("training_receipt.evidence_status must be complete")
    model_kind = _identifier(value.get("model_kind"), "training_receipt.model_kind")
    seed = _strict_int(value.get("seed"), "training_receipt.seed")
    if model_kind != launch["model"] or seed != launch["seed"]:
        _fail("training model/seed does not match launch receipt")
    completed_updates = _strict_int(
        value.get("completed_updates"), "training_receipt.completed_updates", minimum=1)
    config = _mapping(value.get("config"), "training_receipt.config")
    config_model = _identifier(config.get("model_kind"), "training_receipt.config.model_kind")
    config_seed = _strict_int(config.get("seed"), "training_receipt.config.seed")
    hidden = _strict_int(config.get("hidden"), "training_receipt.config.hidden", minimum=1)
    configured_updates = _strict_int(config.get("updates"), "training_receipt.config.updates", minimum=1)
    if config_model != model_kind or config_seed != seed:
        _fail("training config model/seed does not match training receipt")
    if configured_updates != completed_updates:
        _fail("training config updates disagree with completed_updates")

    evidence = _mapping(value.get("evidence"), "training_receipt.evidence")
    if evidence.get("status") != "complete":
        _fail("training_receipt.evidence.status must be complete")
    initialization = _mapping(
        evidence.get("initialization"), "training_receipt.evidence.initialization")
    if initialization.get("schema") != "core.training.initialization_evidence.v1":
        _fail(
            "training_receipt.evidence.initialization.schema must be "
            "core.training.initialization_evidence.v1"
        )
    if initialization.get("status") != "captured":
        _fail("training_receipt.evidence.initialization.status must be captured")
    initialization_model = _identifier(
        initialization.get("model_kind"),
        "training_receipt.evidence.initialization.model_kind",
    )
    initialization_seed = _strict_int(
        initialization.get("seed"),
        "training_receipt.evidence.initialization.seed",
    )
    initialization_hidden = _strict_int(
        initialization.get("hidden"),
        "training_receipt.evidence.initialization.hidden",
        minimum=1,
    )
    initialization_parameter_count = _strict_int(
        initialization.get("parameter_count"),
        "training_receipt.evidence.initialization.parameter_count",
        minimum=1,
    )
    if (initialization_model != model_kind or initialization_seed != seed or
            initialization_hidden != hidden):
        _fail("training initialization evidence disagrees with training config")

    checkpoint = _mapping(value.get("checkpoint"), "training_receipt.checkpoint")
    if checkpoint.get("schema") != "core.checkpoint.v1":
        _fail("training_receipt.checkpoint.schema must be core.checkpoint.v1")
    checkpoint_path = _declared_path(checkpoint.get("path"), "training_receipt.checkpoint.path")
    checkpoint_sha256 = _sha256(checkpoint.get("sha256"), "training_receipt.checkpoint.sha256")
    checkpoint_update = _strict_int(
        checkpoint.get("update"), "training_receipt.checkpoint.update", minimum=1)
    if checkpoint_path != launch["checkpoint_path"] or checkpoint_sha256 != launch["checkpoint_sha256"]:
        _fail("training checkpoint path/SHA disagrees with launch receipt")
    if checkpoint_update != completed_updates:
        _fail("training checkpoint update disagrees with completed_updates")
    if "checkpoint_verified" in value and value["checkpoint_verified"] is not True:
        _fail("training_receipt.checkpoint_verified must be true when declared")
    parameter_count = _strict_int(
        value.get("parameter_count"), "training_receipt.parameter_count", minimum=1)
    if initialization_parameter_count != parameter_count:
        _fail("training initialization parameter_count disagrees with training receipt")
    run_id = _identifier(value.get("run_id"), "training_receipt.run_id")
    training_manifest_sha256 = config.get("manifest_sha256")
    if training_manifest_sha256 is not None:
        training_manifest_sha256 = _sha256(
            training_manifest_sha256, "training_receipt.config.manifest_sha256")

    return {
        "schema": TRAINING_SCHEMA,
        "run_id": run_id,
        "model_kind": model_kind,
        "seed": seed,
        "hidden": hidden,
        "completed_updates": completed_updates,
        "parameter_count": parameter_count,
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_update": checkpoint_update,
        "training_manifest_sha256": training_manifest_sha256,
    }


def _normalize_case_bindings(
    case_bindings: Mapping[str, Mapping[str, Any]],
    expected_case_ids: Sequence[str],
) -> dict[str, dict[str, str]]:
    value = _mapping(case_bindings, "case_bindings")
    expected = set(expected_case_ids)
    observed = set(value)
    if observed != expected:
        _fail("case_bindings case set does not exactly match launch jobs")
    result: dict[str, dict[str, str]] = {}
    for case_id in sorted(expected):
        raw = _mapping(value[case_id], f"case_bindings[{case_id!r}]")
        result[case_id] = {
            "path": _declared_path(raw.get("path"), f"case_bindings[{case_id!r}].path"),
            "sha256": _sha256(raw.get("sha256"), f"case_bindings[{case_id!r}].sha256"),
        }
    return result


def _path_value_consensus(
    locations: Sequence[Mapping[str, Any]],
    key: str,
    expected: str,
    name: str,
) -> None:
    observed = [location[key] for location in locations if key in location]
    if not observed:
        _fail(f"{name}.{key} is missing")
    if any(value != observed[0] for value in observed[1:]):
        _fail(f"{name}.{key} disagrees between evaluation views")
    if _declared_path(observed[0], f"{name}.{key}") != expected:
        _fail(f"{name}.{key} does not match the launch output prefix")


def validate_evaluation_progress_pair(
    evaluation: Mapping[str, Any],
    progress: Mapping[str, Any],
    *,
    case_id: str,
    job: Mapping[str, Any],
) -> str:
    """Validate the independent pair before the existing aggregator sees it."""
    evaluation = _mapping(evaluation, f"evaluation[{case_id}]")
    progress = _mapping(progress, f"progress[{case_id}]")
    if evaluation.get("schema") != EVALUATION_SCHEMA:
        _fail(f"evaluation[{case_id}].schema must be {EVALUATION_SCHEMA}")
    if evaluation.get("evaluation_mode") != "diagnostic":
        _fail(f"evaluation[{case_id}] must be diagnostic")
    if evaluation.get("diagnostic") is not True:
        _fail(f"evaluation[{case_id}].diagnostic must be true")
    if evaluation.get("formal_eligible") is not False:
        _fail(f"evaluation[{case_id}].formal_eligible must be false")
    if evaluation.get("autonomous") is not True:
        _fail(f"evaluation[{case_id}].autonomous must be true")
    if evaluation.get("future_state_inputs") is not False:
        _fail(f"evaluation[{case_id}].future_state_inputs must be false")
    _validate_zero_formal_claims(evaluation, name=f"evaluation[{case_id}]")

    expected_paths = job["output_paths"]
    cases = _mapping(evaluation.get("cases"), f"evaluation[{case_id}].cases")
    if list(cases) != [case_id]:
        _fail(f"evaluation[{case_id}].cases must contain exactly the launch case")
    row = _mapping(cases[case_id], f"evaluation[{case_id}].cases[{case_id!r}]")
    nested_value = row.get("rollout")
    locations: list[Mapping[str, Any]] = [row]
    if nested_value is not None:
        locations.insert(0, _mapping(nested_value, f"evaluation[{case_id}].rollout"))
    _path_value_consensus(locations, "trajectory_output", expected_paths["trajectory"], f"evaluation[{case_id}]")
    _path_value_consensus(locations, "progress_output", expected_paths["progress"], f"evaluation[{case_id}]")
    if evaluation.get("checkpoint") != job["checkpoint_path"]:
        _fail(f"evaluation[{case_id}].checkpoint does not match launch checkpoint")
    for list_name in ("registered_case_ids", "selected_case_ids"):
        if evaluation.get(list_name) != [case_id]:
            _fail(f"evaluation[{case_id}].{list_name} must contain exactly the launch case")

    if progress.get("schema") != PROGRESS_SCHEMA:
        _fail(f"progress[{case_id}].schema must be {PROGRESS_SCHEMA}")
    if progress.get("case_id") != case_id:
        _fail(f"progress[{case_id}].case_id disagrees with launch case")
    status = progress.get("status")
    if status not in STATUSES:
        _fail(f"progress[{case_id}].status is invalid")
    if progress.get("autonomous") is not True:
        _fail(f"progress[{case_id}].autonomous must be true")
    if progress.get("future_state_inputs") is not False:
        _fail(f"progress[{case_id}].future_state_inputs must be false")
    for name in ("expected_frames", "frames_expected"):
        if _strict_int(progress.get(name), f"progress[{case_id}].{name}", minimum=1) != EXPECTED_TRANSITIONS:
            _fail(f"progress[{case_id}].{name} must be {EXPECTED_TRANSITIONS}")
    for name in ("completed_frames", "frames_executed"):
        _strict_int(progress.get(name), f"progress[{case_id}].{name}", maximum=EXPECTED_TRANSITIONS)
    if progress.get("trajectory_output") != expected_paths["trajectory"]:
        _fail(f"progress[{case_id}].trajectory_output does not match launch output prefix")
    _validate_zero_formal_claims(progress, name=f"progress[{case_id}]")
    if evaluation.get("status") is not None and evaluation.get("status") != status:
        _fail(f"evaluation[{case_id}].status disagrees with progress status")
    return status


def _compose_item(
    evaluation: Mapping[str, Any],
    progress: Mapping[str, Any],
    *,
    status: str,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    evaluation_copy = copy.deepcopy(dict(evaluation))
    embedded_binding = evaluation_copy.get("binding")
    if embedded_binding is not None and embedded_binding != binding:
        _fail("evaluation embedded binding disagrees with launch/case binding")
    return {
        "schema": ITEM_SCHEMA,
        "status": status,
        "binding": copy.deepcopy(dict(binding)),
        "evaluation": evaluation_copy,
        "progress": copy.deepcopy(dict(progress)),
    }


def _source_ref(
    value: Mapping[str, Any],
    *,
    path: str,
    raw: bytes | None,
) -> dict[str, Any]:
    if raw is None:
        raw = canonical_json(value).encode("utf-8")
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _project_cases(
    aggregate: Mapping[str, Any],
    *,
    evaluation_sources: Mapping[str, Mapping[str, Any]],
    progress_sources: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for item in aggregate["cases"]:
        case_id = item["case_id"]
        cases.append({
            "case_id": case_id,
            "status": item["status"],
            "expected_transitions": item["expected_transitions"],
            "executed_transitions": item["executed_transitions"],
            "raw_error_coverage": item["raw_error_coverage"],
            "complete_over_registered_denominator": item["complete_over_registered_denominator"],
            "failure_category": item["failure_category"],
            "first_failure_frame": item["first_failure_frame"],
            "paths": item["paths"],
            "evaluation_json": evaluation_sources[case_id],
            "progress_json": progress_sources[case_id],
        })
    return cases


def _result(
    *,
    launch: Mapping[str, Any],
    training: Mapping[str, Any],
    aggregate: Mapping[str, Any],
    evaluation_sources: Mapping[str, Mapping[str, Any]],
    progress_sources: Mapping[str, Mapping[str, Any]],
    synthetic_only: bool,
) -> dict[str, Any]:
    terminal_states = aggregate["status_counts"].get("running", 0) == 0
    return {
        "schema": SCHEMA,
        "status": "json_bound_terminal_states" if terminal_states else "json_bound_diagnostic_batch",
        "source_bound": True,
        "synthetic_only": bool(synthetic_only),
        "diagnostic_only": True,
        "formal_eligible": False,
        "formal": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "fail_closed": False,
        "launch": {
            "schema": launch["schema"],
            "status": launch["status"],
            "model": launch["model"],
            "seed": launch["seed"],
            "manifest_path": launch["manifest_path"],
            "manifest_sha256": launch["manifest_sha256"],
            "checkpoint_path": launch["checkpoint_path"],
            "checkpoint_sha256": launch["checkpoint_sha256"],
            "argv_contract": launch["argv_contract"],
            "case_ids": list(launch["case_ids"]),
            "jobs": [
                {
                    "case_id": launch["jobs"][case_id]["case_id"],
                    "output_prefix": launch["jobs"][case_id]["output_prefix"],
                    "output_paths": launch["jobs"][case_id]["output_paths"],
                    "gpu_index": launch["jobs"][case_id]["gpu_index"],
                    "pid": launch["jobs"][case_id]["pid"],
                }
                for case_id in launch["case_ids"]
            ],
            "fresh_namespace_binding": launch["fresh_namespace_binding"],
        },
        "training": training,
        "aggregate": {
            "schema": aggregate["schema"],
            "status": aggregate["status"],
            "source_bound": aggregate["source_bound"],
            "denominator": aggregate["denominator"],
            "status_counts": aggregate["status_counts"],
            "cases": _project_cases(
                aggregate,
                evaluation_sources=evaluation_sources,
                progress_sources=progress_sources,
            ),
        },
        "checks": {
            "launch_receipt_schema": True,
            "training_receipt_schema": True,
            "model_seed_binding": True,
            "hidden_binding": True,
            "updates_binding": True,
            "checkpoint_path_binding": True,
            "checkpoint_sha256_binding": True,
            "expected_transition_denominator": True,
            "case_set_binding": True,
            "output_prefix_binding": True,
            "fresh_namespace_binding": True,
            "evaluation_progress_pair_binding": True,
            "existing_batch_aggregator_reused": True,
            "diagnostic_flags": True,
            "zero_credit": True,
        },
        "side_effects": {
            "manifest_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_path_opened": False,
            "live_jobs_required": False,
            "runtime_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
        "interpretation": (
            "This receipt binds launch, training, evaluation, progress, and the existing "
            "JSON-only batch aggregator. It is not HDF5 validation, scientific qualification, "
            "T1/T2 evidence, or formal credit."
        ),
    }


def verify_payloads(
    launch_receipt: Mapping[str, Any],
    training_receipt: Mapping[str, Any],
    evaluations: Mapping[str, Mapping[str, Any]],
    progresses: Mapping[str, Mapping[str, Any]],
    case_bindings: Mapping[str, Mapping[str, Any]],
    *,
    evaluation_sources: Mapping[str, Mapping[str, Any]] | None = None,
    progress_sources: Mapping[str, Mapping[str, Any]] | None = None,
    synthetic_only: bool = False,
) -> dict[str, Any]:
    """Bind in-memory JSON payloads and delegate validation to the reducer."""
    launch = validate_launch_receipt(launch_receipt)
    training = validate_training_receipt(training_receipt, launch)
    expected_case_ids = launch["case_ids"]
    expected_case_set = set(expected_case_ids)
    if set(evaluations) != expected_case_set or set(progresses) != expected_case_set:
        _fail("evaluation/progress case sets must exactly match launch jobs")
    normalized_bindings = _normalize_case_bindings(case_bindings, expected_case_ids)
    evaluation_sources = dict(evaluation_sources or {
        case_id: _source_ref(evaluations[case_id], path=f"synthetic://evaluation/{case_id}.json", raw=None)
        for case_id in expected_case_ids
    })
    progress_sources = dict(progress_sources or {
        case_id: _source_ref(progresses[case_id], path=f"synthetic://progress/{case_id}.json", raw=None)
        for case_id in expected_case_ids
    })
    if set(evaluation_sources) != expected_case_set or set(progress_sources) != expected_case_set:
        _fail("evaluation/progress source maps must exactly match launch jobs")

    items: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    for case_id in expected_case_ids:
        job = launch["jobs"][case_id]
        status = validate_evaluation_progress_pair(
            evaluations[case_id], progresses[case_id], case_id=case_id, job=job)
        statuses[case_id] = status
        binding = _expected_binding(launch, case_id, normalized_bindings[case_id])
        items.append(_compose_item(
            evaluations[case_id], progresses[case_id], status=status, binding=binding))

    with tempfile.TemporaryDirectory(prefix="f3-rollout-batch-closure-") as temporary:
        item_paths: list[Path] = []
        for index, case_id in enumerate(expected_case_ids):
            item_path = Path(temporary) / f"{index:04d}-{case_id}.json"
            item_path.write_text(canonical_json(items[index]) + "\n", encoding="utf-8")
            item_paths.append(item_path)
        aggregate = aggregator.aggregate_rollout_files(
            item_paths,
            manifest_path=launch["manifest_path"],
            manifest_sha256=launch["manifest_sha256"],
            checkpoint_path=launch["checkpoint_path"],
            checkpoint_sha256=launch["checkpoint_sha256"],
            case_bindings=normalized_bindings,
            expected_transitions=EXPECTED_TRANSITIONS,
        )
    if list(statuses) != list(launch["case_ids"]):
        _fail("internal case ordering drift")
    return _result(
        launch=launch,
        training=training,
        aggregate=aggregate,
        evaluation_sources=evaluation_sources,
        progress_sources=progress_sources,
        synthetic_only=synthetic_only,
    )


def verify_files(
    launch_path: str | Path,
    training_path: str | Path,
    evaluation_paths: Mapping[str, str | Path],
    progress_paths: Mapping[str, str | Path],
    case_bindings: Mapping[str, Mapping[str, Any]],
    *,
    synthetic_only: bool = False,
) -> dict[str, Any]:
    """Read only the supplied JSON files and return a bound diagnostic result."""
    launch_file, launch, _ = _read_json(launch_path)
    training_file, training, _ = _read_json(training_path)
    if not evaluation_paths or set(evaluation_paths) != set(progress_paths):
        _fail("evaluation/progress path maps must have the same non-empty case set")
    evaluations: dict[str, Mapping[str, Any]] = {}
    progresses: dict[str, Mapping[str, Any]] = {}
    evaluation_sources: dict[str, Mapping[str, Any]] = {}
    progress_sources: dict[str, Mapping[str, Any]] = {}
    for case_id in sorted(evaluation_paths):
        evaluation_file, evaluation, evaluation_raw = _read_json(evaluation_paths[case_id])
        progress_file, progress, progress_raw = _read_json(progress_paths[case_id])
        evaluations[case_id] = evaluation
        progresses[case_id] = progress
        evaluation_sources[case_id] = _source_ref(
            evaluation, path=str(evaluation_file), raw=evaluation_raw)
        progress_sources[case_id] = _source_ref(
            progress, path=str(progress_file), raw=progress_raw)
    result = verify_payloads(
        launch,
        training,
        evaluations,
        progresses,
        case_bindings,
        evaluation_sources=evaluation_sources,
        progress_sources=progress_sources,
        synthetic_only=synthetic_only,
    )
    result["input_receipts"] = {
        "launch": _source_ref(launch, path=str(launch_file), raw=None),
        "training": _source_ref(training, path=str(training_file), raw=None),
    }
    return result


def run_closure(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return a JSON-safe result; every validation error remains fail-closed."""
    try:
        return verify_payloads(*args, **kwargs)
    except Exception as error:
        return {
            "schema": SCHEMA,
            "status": "fail_closed",
            "source_bound": False,
            "synthetic_only": bool(kwargs.get("synthetic_only", False)),
            "diagnostic_only": True,
            "formal_eligible": False,
            "formal": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
            "fail_closed": True,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "error": str(error),
        }


def _synthetic_launch() -> dict[str, Any]:
    manifest_sha = "a" * 64
    checkpoint_sha = "b" * 64
    jobs = []
    for index in range(3):
        case_id = f"F3_SYNTHETIC_{index:02d}"
        jobs.append({
            "case_id": case_id,
            "gpu_index": index,
            "output_prefix": f"/synthetic/f3-batch/{case_id}-v1",
            "pid": 41000 + index,
        })
    return {
        "schema": LAUNCH_SCHEMA,
        "status": "diagnostic_launch_verified_running",
        "model": "graph_raw",
        "seed": 17,
        "manifest_path": "campaigns/core-v1/f3-dataset-v2.json",
        "manifest_sha256": manifest_sha,
        "checkpoint_path": "/synthetic/checkpoints/graph-raw-seed17.pt",
        "checkpoint_sha256": checkpoint_sha,
        "argv_contract": {
            "chunk_size": 34560,
            "device_in_process": "cuda:0",
            "diagnostic": True,
            "maximum_steps": EXPECTED_TRANSITIONS,
            "progress_every": 25,
            "split": "test",
        },
        "jobs": jobs,
        "launch_verification": {
            "all_eight_processes_observed": True,
            "all_eight_progress_files_created": True,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
    }


def _synthetic_training(launch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": TRAINING_SCHEMA,
        "run_id": "graph_raw-seed17-synthetic",
        "model_kind": launch["model"],
        "seed": launch["seed"],
        "completed_updates": 500,
        "evidence_status": "complete",
        "checkpoint_verified": True,
        "parameter_count": 1766,
        "evidence": {
            "schema": "core.training.evidence.v1",
            "status": "complete",
            "initialization": {
                "schema": "core.training.initialization_evidence.v1",
                "status": "captured",
                "model_kind": launch["model"],
                "seed": launch["seed"],
                "hidden": 8,
                "parameter_count": 1766,
            },
        },
        "checkpoint": {
            "schema": "core.checkpoint.v1",
            "path": launch["checkpoint_path"],
            "sha256": launch["checkpoint_sha256"],
            "update": 500,
        },
        "config": {
            "model_kind": launch["model"],
            "seed": launch["seed"],
            "hidden": 8,
            "updates": 500,
            "manifest_sha256": "c" * 64,
        },
    }


def _metric_values(executed: int) -> list[float | None]:
    return [0.001 * (index + 1) if index < executed else None
            for index in range(EXPECTED_TRANSITIONS)]


def _synthetic_job(launch: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    for job in launch["jobs"]:
        if job["case_id"] == case_id:
            return job
    raise KeyError(case_id)


def _synthetic_evaluation(
    launch: Mapping[str, Any],
    case_id: str,
    *,
    executed: int,
    status: str,
    failure_category: str | None = None,
) -> dict[str, Any]:
    job = _synthetic_job(launch, case_id)
    paths = _output_paths(job["output_prefix"])
    complete = status == "completed"
    row = {
        "case_id": case_id,
        "frames_predicted": executed,
        "frames_expected": EXPECTED_TRANSITIONS,
        "frames_executed": executed,
        "expected_frames": EXPECTED_TRANSITIONS,
        "executed": True,
        "position_rmse": _metric_values(executed),
        "velocity_rmse": _metric_values(executed),
        "position_ade": _metric_values(executed),
        "velocity_ade": _metric_values(executed),
        "failure_category": failure_category,
        "first_failure_frame": None if failure_category is None else executed + 1,
        "execution_complete": complete,
        "finite_rollout_complete": complete,
        "future_state_inputs": False,
        "trajectory_output": paths["trajectory"],
        "progress_output": paths["progress"],
        "score": {
            "expected_frames": EXPECTED_TRANSITIONS,
            "finite_prefix_frames": executed,
            "executed": True,
            "complete": complete,
            "failure_category": failure_category,
            "raw_error_coverage": executed / EXPECTED_TRANSITIONS,
        },
    }
    row["rollout"] = copy.deepcopy({key: value for key, value in row.items()
                                    if key != "score"})
    return {
        "schema": EVALUATION_SCHEMA,
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "autonomous": True,
        "future_state_inputs": False,
        "checkpoint": launch["checkpoint_path"],
        "registered_case_ids": [case_id],
        "selected_case_ids": [case_id],
        "expected_frames": {case_id: EXPECTED_TRANSITIONS},
        "cases": {case_id: row},
    }


def _synthetic_progress(
    launch: Mapping[str, Any],
    case_id: str,
    *,
    executed: int,
    status: str,
) -> dict[str, Any]:
    return {
        "schema": PROGRESS_SCHEMA,
        "case_id": case_id,
        "status": status,
        "completed_frames": executed,
        "expected_frames": EXPECTED_TRANSITIONS,
        "frames_expected": EXPECTED_TRANSITIONS,
        "frames_executed": executed,
        "autonomous": True,
        "future_state_inputs": False,
        "execution_complete": status == "completed",
        "finite_rollout_complete": status == "completed",
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "trajectory_output": _synthetic_job(launch, case_id)["output_prefix"] + OUTPUT_SUFFIXES["trajectory"],
    }


def build_report() -> dict[str, Any]:
    """Build the committed synthetic-only machine report."""
    launch = _synthetic_launch()
    training = _synthetic_training(launch)
    case_ids = list(sorted(job["case_id"] for job in launch["jobs"]))
    statuses = {
        case_ids[0]: (EXPECTED_TRANSITIONS, "completed", None),
        case_ids[1]: (23, "running", None),
        case_ids[2]: (17, "failed", "model_execution_error"),
    }
    evaluations = {
        case_id: _synthetic_evaluation(
            launch, case_id, executed=statuses[case_id][0],
            status=statuses[case_id][1], failure_category=statuses[case_id][2])
        for case_id in case_ids
    }
    progresses = {
        case_id: _synthetic_progress(
            launch, case_id, executed=statuses[case_id][0], status=statuses[case_id][1])
        for case_id in case_ids
    }
    bindings = {
        case_id: {
            "path": f"cases/{case_id}/source.h5",
            "sha256": ("d" + "0" * 63) if index == 1 else (
                "e" + "0" * 63 if index == 2 else "c" + "0" * 63),
        }
        for index, case_id in enumerate(case_ids)
    }
    for case_id in case_ids:
        evaluations[case_id]["binding"] = _expected_binding(
            validate_launch_receipt(launch), case_id, bindings[case_id])
    result = verify_payloads(
        launch,
        training,
        evaluations,
        progresses,
        bindings,
        synthetic_only=True,
    )
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "synthetic_only_json_batch_closure_binding",
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "closure_result": result,
        "contract": {
            "launch_schema": LAUNCH_SCHEMA,
            "training_schema": TRAINING_SCHEMA,
            "evaluation_schema": EVALUATION_SCHEMA,
            "progress_schema": PROGRESS_SCHEMA,
            "aggregator_schema": aggregator.SCHEMA,
            "expected_transitions": EXPECTED_TRANSITIONS,
            "independent_evaluation_and_progress_inputs": True,
            "hdf5_access": "forbidden",
            "live_job_dependency": False,
        },
        "qualification": {
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
        },
        "verification": {
            "synthetic_cases": len(case_ids),
            "status_mix": {"completed": 1, "failed": 1, "running": 1},
            "existing_aggregator_reused": True,
            "hdf5_opened": False,
            "checkpoint_opened": False,
            "manifest_opened": False,
            "live_jobs_required": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
    }


def _write_canonical(path: str | Path, value: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-receipt", required=True, type=Path)
    parser.add_argument("--training-receipt", required=True, type=Path)
    parser.add_argument(
        "--evaluation", action="append", nargs=2, metavar=("CASE_ID", "PATH"), required=True)
    parser.add_argument(
        "--progress", action="append", nargs=2, metavar=("CASE_ID", "PATH"), required=True)
    parser.add_argument(
        "--case-binding", action="append", nargs=3,
        metavar=("CASE_ID", "CASE_PATH", "CASE_SHA256"), required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        evaluation_paths: dict[str, str] = {}
        for case_id, path in args.evaluation:
            case_id = _identifier(case_id, "--evaluation CASE_ID")
            if case_id in evaluation_paths:
                _fail(f"duplicate --evaluation case_id: {case_id}")
            evaluation_paths[case_id] = path
        progress_paths: dict[str, str] = {}
        for case_id, path in args.progress:
            case_id = _identifier(case_id, "--progress CASE_ID")
            if case_id in progress_paths:
                _fail(f"duplicate --progress case_id: {case_id}")
            progress_paths[case_id] = path
        case_bindings: dict[str, dict[str, str]] = {}
        for case_id, case_path, case_sha256 in args.case_binding:
            case_id = _identifier(case_id, "--case-binding CASE_ID")
            if case_id in case_bindings:
                _fail(f"duplicate --case-binding case_id: {case_id}")
            case_bindings[case_id] = {"path": case_path, "sha256": case_sha256}
        result = verify_files(
            args.launch_receipt,
            args.training_receipt,
            evaluation_paths,
            progress_paths,
            case_bindings,
        )
    except Exception as error:
        result = {
            "schema": SCHEMA,
            "status": "fail_closed",
            "source_bound": False,
            "synthetic_only": False,
            "diagnostic_only": True,
            "formal_eligible": False,
            "formal": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
            "fail_closed": True,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "error": str(error),
        }
    if args.output is None:
        sys.stdout.write(canonical_json(result) + "\n")
    else:
        _write_canonical(args.output, result)
    return 0 if result.get("fail_closed") is False else 1


__all__ = [
    "ClosureBindingError",
    "EXPECTED_TRANSITIONS",
    "REPORT_ID",
    "REPORT_SCHEMA",
    "SCHEMA",
    "build_report",
    "canonical_json",
    "main",
    "run_closure",
    "validate_evaluation_progress_pair",
    "validate_launch_receipt",
    "validate_training_receipt",
    "verify_files",
    "verify_payloads",
]


if __name__ == "__main__":
    raise SystemExit(main())
