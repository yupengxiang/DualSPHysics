#!/usr/bin/env python3
"""Join the Core formal-training release/root admission inputs read-only.

The existing formal release candidate, source-closure v6 admission, and
readiness matrix each verify a different boundary.  This module is the
missing *join* between those boundaries: it binds a dataset release manifest,
a trusted-root input, the source closure, terminal-evidence inventory, and the
fixed 3-model x 3-seed matrix by bounded JSON references and SHA-256 digests.

This is a non-authorizing adapter.  It never opens HDF5/checkpoints, imports a
trainer, verifies a cryptographic root signature, starts a process, or writes
campaign state.  A caller-provided root claim is never promoted to
``trusted_root_authenticated``.  Consequently every result has
``launch_allowed=false``, ``formal_eligible=false``, and zero credit, even
when a synthetic fixture is structurally complete.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_REL = Path("reports/CORE-FORMAL-TRAINING-RELEASE-ROOT-ADMISSION-GAP-2026-09-29.json")
SCHEMA = "core.formal_training_release_root_admission_report.v1"
CONTRACT_SCHEMA = "core.formal_training_release_root_admission_contract.v1"
TRUSTED_ROOT_SCHEMA = "core.formal_training_trusted_root_attestation.v1"
TERMINAL_EVIDENCE_SCHEMA = "core.formal_training_terminal_evidence_matrix.v1"
MATRIX_SCHEMA = "core.formal_training_readiness_matrix.v1"
MAX_JSON_BYTES = 2 * 1024 * 1024

MODELS = ("graph_raw", "graph_residual", "mlp")
SEEDS = (17, 29, 43)
RUN_IDS = tuple(f"{model}-seed{seed}" for model in MODELS for seed in SEEDS)

DEFAULT_INPUT_PATHS = {
    "formal_dataset_release_manifest": "campaigns/core-v1/f3-dataset-v2.json",
    "trusted_root": (
        "campaigns/core-v1/learning/formal-source-closure-v7-20260929/receipt.json"
    ),
    "source_closure": (
        "campaigns/core-v1/learning/formal-source-closure-v7-20260929/source-closure.json"
    ),
    "terminal_evidence": "campaigns/core-v1/registry.json",
    "model_seed_matrix": "reports/CORE-FORMAL-TRAINING-READINESS-MATRIX-2026-09-29.json",
}


class AdmissionContractError(ValueError):
    """Raised when a bounded input or report violates this contract."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_constant(token: str) -> None:
    raise AdmissionContractError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk(value: Any, *, depth: int = 0) -> None:
    if depth > 64:
        raise AdmissionContractError("JSON nesting exceeds the bounded depth")
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_JSON_BYTES:
            raise AdmissionContractError("JSON string exceeds the bounded size")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AdmissionContractError("JSON contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AdmissionContractError("JSON object key is not a string")
            _walk(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 8192:
            raise AdmissionContractError("JSON array exceeds the bounded item count")
        for item in value:
            _walk(item, depth=depth + 1)
        return
    raise AdmissionContractError(f"unsupported JSON value: {type(value).__name__}")


def _read_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AdmissionContractError(f"input must be a single-link regular file: {path}")
        if before.st_size > MAX_JSON_BYTES:
            raise AdmissionContractError(f"input exceeds bounded size: {path}")
        chunks: list[bytes] = []
        remaining = MAX_JSON_BYTES + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        raw = b"".join(chunks)
        if identity_before != identity_after or len(raw) != before.st_size:
            raise AdmissionContractError(f"input changed during bounded read: {path}")
        if len(raw) > MAX_JSON_BYTES:
            raise AdmissionContractError(f"input exceeds bounded size: {path}")
        return raw
    finally:
        os.close(descriptor)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_input(value: str | Path, *, root: Path, label: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AdmissionContractError(f"{label} path must be relative to root")
    path = (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise AdmissionContractError(f"{label} path escapes root") from error
    if not path.is_file():
        raise AdmissionContractError(f"{label} path is not a regular file: {candidate}")
    return path


def _load_json(
    source: str | Path | Mapping[str, Any], *, root: Path, label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(source, Mapping):
        payload = dict(source)
        raw = _canonical(payload).encode("utf-8")
        reference = {
            "path": "<in-memory>",
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
        return payload, reference
    path = _resolve_input(source, root=root, label=label)
    raw = _read_bytes(path)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, AdmissionContractError) as error:
        raise AdmissionContractError(f"invalid JSON input for {label}: {error}") from error
    _walk(value)
    if not isinstance(value, dict):
        raise AdmissionContractError(f"{label} JSON root must be an object")
    return value, {
        "path": _relative(path, root),
        "bytes": len(raw),
        "sha256": _sha256(raw),
    }


def _reference_matches(left: Any, right: Mapping[str, Any]) -> bool:
    return isinstance(left, Mapping) and all(
        left.get(key) == right.get(key) for key in ("path", "bytes", "sha256")
    )


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool:
    return type(value) is bool


def _int(value: Any) -> bool:
    return type(value) is int


def _dataset_observation(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema_supported": payload.get("schema") == "core.dataset.v2",
        "dataset_id_present": isinstance(payload.get("dataset_id"), str)
        and bool(payload.get("dataset_id")),
        "case_count_bounded": _int(payload.get("case_count"))
        and payload.get("case_count") > 0,
        "source_manifest_digest_present": _valid_sha256(payload.get("source_manifest_sha256")),
        "formal_release": payload.get("formal_release") is True,
    }
    return {
        "schema": payload.get("schema"),
        "dataset_id": payload.get("dataset_id"),
        "case_count": payload.get("case_count"),
        "formal_release": payload.get("formal_release"),
        "checks": checks,
        "release_ready": all(checks.values()),
    }


def _source_closure_observation(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema_supported": isinstance(payload.get("schema"), str)
        and payload.get("schema", "").startswith("core.formal_source_closure."),
        "closure_digest_present": _valid_sha256(payload.get("closure_sha256")),
        "complete": payload.get("complete") is True,
        "missing_files_empty": payload.get("missing_files") == [],
        "formal_release": payload.get("formal_release") is True,
        "formal_training_allowed": payload.get("formal_training_allowed") is True,
        "formal_training_ready": payload.get("formal_training_ready") is True,
        "launch_allowed": payload.get("launch_allowed") is True,
        "root_admission_granted": payload.get("root_admission_granted") is True,
    }
    return {
        "schema": payload.get("schema"),
        "closure_version": payload.get("closure_version"),
        "closure_sha256": payload.get("closure_sha256"),
        "complete": payload.get("complete"),
        "formal_release": payload.get("formal_release"),
        "formal_training_allowed": payload.get("formal_training_allowed"),
        "formal_training_ready": payload.get("formal_training_ready"),
        "launch_allowed": payload.get("launch_allowed"),
        "root_admission_granted": payload.get("root_admission_granted"),
        "checks": checks,
        "release_ready": all(checks.values()),
    }


def _expected_root_subject(
    *, dataset_ref: Mapping[str, Any], closure_ref: Mapping[str, Any],
    terminal_ref: Mapping[str, Any], matrix_ref: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "dataset_manifest_sha256": dataset_ref["sha256"],
        "source_closure_file_sha256": closure_ref["sha256"],
        "source_closure_sha256": closure.get("closure_sha256"),
        "terminal_evidence_sha256": terminal_ref["sha256"],
        "model_seed_matrix_sha256": matrix_ref["sha256"],
    }


def _root_observation(
    payload: Mapping[str, Any], *, expected_subject: Mapping[str, Any],
) -> dict[str, Any]:
    root = _object(payload.get("trusted_root"))
    decision = _object(payload.get("decision"))
    subject = _object(decision.get("subject"))
    subject_bound = bool(subject) and all(
        subject.get(key) == value for key, value in expected_subject.items()
    )
    checks = {
        "schema_supported": payload.get("schema") == TRUSTED_ROOT_SCHEMA,
        "status_verified": payload.get("status") == "verified",
        "external_authority_declared": root.get("authority") == "external_root",
        "decision_granted": decision.get("granted") is True,
        "subject_bound": subject_bound,
        "attestation_reference_present": isinstance(root.get("attestation"), Mapping),
    }
    # No cryptographic root verifier is part of this synthetic-only adapter.
    # A caller's ``authenticated``/``signature_verified`` booleans are not
    # consumed as authority.
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "decision_granted": decision.get("granted"),
        "checks": checks,
        "trusted_root_authenticated": False,
        "authentication_boundary": "external verifier not integrated",
        "structurally_bound": all(checks.values()),
        "admission_ready": False,
    }


def _run_id_set(rows: Any) -> set[str]:
    if not isinstance(rows, list):
        return set()
    return {
        row.get("run_id") for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("run_id"), str)
    }


def _matrix_observation(payload: Mapping[str, Any]) -> dict[str, Any]:
    scope = _object(payload.get("scope"))
    rows = payload.get("runs")
    scope_checks = {
        "models_exact": scope.get("models") == list(MODELS),
        "seeds_exact": scope.get("seeds") == list(SEEDS),
        "run_count_exact": scope.get("run_count") == len(RUN_IDS),
        "run_ids_exact": scope.get("run_ids") == list(RUN_IDS),
    }
    row_checks: list[bool] = []
    normalized_rows: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for expected, row in zip(RUN_IDS, rows):
            model, seed_text = expected.rsplit("-seed", 1)
            seed = int(seed_text)
            valid = (
                isinstance(row, Mapping)
                and row.get("run_id") == expected
                and row.get("model") == model
                and row.get("seed") == seed
            )
            row_checks.append(valid)
            if isinstance(row, Mapping):
                normalized_rows.append({
                    "run_id": row.get("run_id"),
                    "status": row.get("status"),
                    "formal_spec": row.get("formal_spec"),
                    "formal_release": row.get("formal_release"),
                    "root_trust": row.get("root_trust"),
                    "terminal_evidence": row.get("terminal_evidence"),
                    "credit": row.get("credit"),
                })
    rows_exact = isinstance(rows, list) and len(rows) == len(RUN_IDS) and all(row_checks)
    decision = _object(payload.get("decision"))
    return {
        "schema": payload.get("schema"),
        "report_id": payload.get("report_id"),
        "scope_checks": scope_checks,
        "rows_exact": rows_exact,
        "decision_closed": decision.get("launch_allowed") is False,
        "decision_status": decision.get("status"),
        "matrix_valid": payload.get("schema") == MATRIX_SCHEMA
        and all(scope_checks.values())
        and rows_exact,
        "rows": normalized_rows,
        "run_ids": sorted(_run_id_set(rows)),
    }


def _terminal_observation(
    payload: Mapping[str, Any], *, dataset_ref: Mapping[str, Any],
    closure_ref: Mapping[str, Any], root_ref: Mapping[str, Any],
    matrix_ref: Mapping[str, Any], matrix_payload: Mapping[str, Any],
) -> dict[str, Any]:
    checks = {
        "schema_supported": payload.get("schema") == TERMINAL_EVIDENCE_SCHEMA,
        "dataset_manifest_bound": payload.get("dataset_manifest_sha256") == dataset_ref["sha256"],
        "source_closure_bound": payload.get("source_closure_file_sha256") == closure_ref["sha256"],
        "trusted_root_bound": payload.get("trusted_root_sha256") == root_ref["sha256"],
        "model_seed_matrix_bound": payload.get("model_seed_matrix_sha256") == matrix_ref["sha256"],
    }
    rows = payload.get("runs")
    row_checks: list[bool] = []
    if isinstance(rows, list):
        for expected, row in zip(RUN_IDS, rows):
            model, seed_text = expected.rsplit("-seed", 1)
            row_checks.append(
                isinstance(row, Mapping)
                and row.get("run_id") == expected
                and row.get("model") == model
                and row.get("seed") == int(seed_text)
                and row.get("status") == "terminal"
                and row.get("terminal_evidence") is True
                and isinstance(row.get("evidence"), Mapping)
            )
    checks["run_rows_exact"] = isinstance(rows, list) and len(rows) == len(RUN_IDS) and all(row_checks)
    matrix_inputs = _object(matrix_payload.get("inputs"))
    checks["matrix_scope_declares_all_runs"] = (
        _object(matrix_payload.get("scope")).get("run_ids") == list(RUN_IDS)
    )
    complete = all(checks.values())
    # Artifact contents are owned by the terminal verifier.  This join only
    # checks the bounded matrix shape and does not re-open those artifacts.
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "checks": checks,
        "matrix_inputs_present": sorted(matrix_inputs),
        "complete": complete,
        "terminal_artifacts_reverified": False,
        "admission_ready": False,
    }


def _matrix_input_bindings(
    matrix_payload: Mapping[str, Any], *, dataset_ref: Mapping[str, Any],
    root_ref: Mapping[str, Any], closure_ref: Mapping[str, Any],
    terminal_ref: Mapping[str, Any], matrix_ref: Mapping[str, Any],
) -> dict[str, Any]:
    inputs = _object(matrix_payload.get("inputs"))
    return {
        "dataset_manifest_to_matrix": _reference_matches(
            inputs.get("current_manifest"), dataset_ref),
        "source_closure_to_matrix": _reference_matches(
            inputs.get("source_closure"), closure_ref),
        "legacy_root_receipt_to_matrix": _reference_matches(
            inputs.get("source_closure_receipt"), root_ref),
        "trusted_root_role_to_matrix": _reference_matches(
            inputs.get("trusted_root"), root_ref),
        "terminal_evidence_role_to_matrix": _reference_matches(
            inputs.get("terminal_evidence"), terminal_ref),
        "matrix_reference_self_consistent": bool(matrix_ref.get("sha256")),
    }


def build_report(
    root: str | Path = LAB_ROOT, *,
    input_paths: Mapping[str, str | Path] | None = None,
    observed_at_utc: str = "2026-09-29T00:00:00Z",
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    paths = dict(DEFAULT_INPUT_PATHS)
    if input_paths is not None:
        paths.update({key: value for key, value in input_paths.items()})
    if set(paths) != set(DEFAULT_INPUT_PATHS):
        raise AdmissionContractError("input roles must be the fixed five-role set")

    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    for role in (
        "formal_dataset_release_manifest",
        "trusted_root",
        "source_closure",
        "terminal_evidence",
        "model_seed_matrix",
    ):
        payloads[role], references[role] = _load_json(
            paths[role], root=root_path, label=role,
        )

    dataset = _dataset_observation(payloads["formal_dataset_release_manifest"])
    closure = _source_closure_observation(payloads["source_closure"])
    matrix = _matrix_observation(payloads["model_seed_matrix"])
    expected_subject = _expected_root_subject(
        dataset_ref=references["formal_dataset_release_manifest"],
        closure_ref=references["source_closure"],
        terminal_ref=references["terminal_evidence"],
        matrix_ref=references["model_seed_matrix"],
        closure=closure,
    )
    root_observation = _root_observation(
        payloads["trusted_root"], expected_subject=expected_subject,
    )
    terminal = _terminal_observation(
        payloads["terminal_evidence"],
        dataset_ref=references["formal_dataset_release_manifest"],
        closure_ref=references["source_closure"],
        root_ref=references["trusted_root"],
        matrix_ref=references["model_seed_matrix"],
        matrix_payload=payloads["model_seed_matrix"],
    )
    cross_bindings = _matrix_input_bindings(
        payloads["model_seed_matrix"],
        dataset_ref=references["formal_dataset_release_manifest"],
        root_ref=references["trusted_root"],
        closure_ref=references["source_closure"],
        terminal_ref=references["terminal_evidence"],
        matrix_ref=references["model_seed_matrix"],
    )

    missing: list[str] = []
    if not dataset["release_ready"]:
        missing.append("FORMAL_DATASET_RELEASE_NOT_GRANTED")
    if not root_observation["checks"]["schema_supported"]:
        missing.append("TRUSTED_ROOT_ATTESTATION_MISSING")
    if not root_observation["trusted_root_authenticated"]:
        missing.append("TRUSTED_ROOT_AUTHENTICATION_NOT_INTEGRATED")
    if not closure["release_ready"]:
        missing.append("SOURCE_CLOSURE_RELEASE_OR_ROOT_GATE_MISSING")
    if not terminal["checks"]["schema_supported"]:
        missing.append("TERMINAL_EVIDENCE_MATRIX_MISSING")
    elif not terminal["complete"]:
        missing.append("TERMINAL_EVIDENCE_MATRIX_INCOMPLETE")
    if not terminal["terminal_artifacts_reverified"]:
        missing.append("TERMINAL_ARTIFACT_REVERIFICATION_NOT_INTEGRATED")
    if not matrix["matrix_valid"]:
        missing.append("MODEL_SEED_MATRIX_INVALID")
    if matrix["decision_closed"] is not True:
        missing.append("MODEL_SEED_MATRIX_LAUNCH_NOT_CLOSED")
    if not cross_bindings["trusted_root_role_to_matrix"]:
        missing.append("MATRIX_TRUSTED_ROOT_ROLE_REFERENCE_MISSING")
    if not cross_bindings["terminal_evidence_role_to_matrix"]:
        missing.append("MATRIX_TERMINAL_EVIDENCE_ROLE_REFERENCE_MISSING")

    missing = list(dict.fromkeys(missing))
    return {
        "schema": SCHEMA,
        "contract_schema": CONTRACT_SCHEMA,
        "report_id": "core-formal-training-release-root-admission-gap-v1",
        "observed_at_utc": observed_at_utc,
        "purpose": (
            "bounded read-only join of formal dataset release, trusted root, source closure, "
            "terminal evidence, and the fixed model/seed matrix"
        ),
        "scope": {
            "models": list(MODELS),
            "seeds": list(SEEDS),
            "run_count": len(RUN_IDS),
            "run_ids": list(RUN_IDS),
        },
        "input_paths": {key: str(value) for key, value in paths.items()},
        "inputs": {
            role: {
                "reference": references[role],
                "schema": payloads[role].get("schema"),
            }
            for role in (
                "formal_dataset_release_manifest",
                "trusted_root",
                "source_closure",
                "terminal_evidence",
                "model_seed_matrix",
            )
        },
        "observations": {
            "dataset_release": dataset,
            "trusted_root": root_observation,
            "source_closure": closure,
            "terminal_evidence": terminal,
            "model_seed_matrix": matrix,
        },
        "cross_bindings": cross_bindings,
        "missing_blockers": missing,
        "decision": {
            "status": "blocked_fail_closed",
            "launch_allowed": False,
            "formal_eligible": False,
            "qualification_credit": 0,
            "credit": 0,
            "non_authorizing_adapter": True,
            "reason": (
                "no synthetic input or caller self-claim can mint trusted-root authentication, "
                "formal terminal evidence, launch authority, or credit"
            ),
        },
        "execution_constraints": {
            "read_only": True,
            "bounded_json_only": True,
            "dataset_payload_only": True,
            "hdf5_opened": False,
            "checkpoint_opened": False,
            "trainer_imported": False,
            "training_started": False,
            "gpu_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "registry_written": False,
            "ledger_written": False,
            "denominator_written": False,
            "gate_written": False,
            "completion_written": False,
            "plan_written": False,
            "historical_receipt_written": False,
        },
        "implementation_boundary": {
            "composes_existing_local_verifiers": False,
            "duplicates_case_or_checkpoint_verification": False,
            "cryptographic_root_verification": False,
            "terminal_artifact_reverification": False,
            "matrix_scope_join_only": True,
        },
    }


def _reference_error(reference: Any, *, root: Path, label: str) -> str | None:
    if not isinstance(reference, Mapping):
        return f"{label} reference is not an object"
    try:
        payload, actual = _load_json(
            reference.get("path", ""), root=root, label=label,
        )
    except (AdmissionContractError, OSError, TypeError, ValueError) as error:
        return f"{label} reference cannot be read: {error}"
    del payload
    if not _reference_matches(reference, actual):
        return f"{label} reference digest or byte count mismatch"
    return None


def validate_report(report: Mapping[str, Any], root: str | Path = LAB_ROOT) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report root is not an object"]
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    if report.get("contract_schema") != CONTRACT_SCHEMA:
        errors.append("contract_schema mismatch")
    if report.get("scope") != {
        "models": list(MODELS),
        "seeds": list(SEEDS),
        "run_count": len(RUN_IDS),
        "run_ids": list(RUN_IDS),
    }:
        errors.append("fixed model/seed scope mismatch")
    decision = _object(report.get("decision"))
    for field, expected in (
        ("launch_allowed", False),
        ("formal_eligible", False),
        ("qualification_credit", 0),
        ("credit", 0),
        ("non_authorizing_adapter", True),
    ):
        if decision.get(field) != expected:
            errors.append(f"decision {field} is not fail-closed")
    constraints = _object(report.get("execution_constraints"))
    for field, expected in (
        ("read_only", True),
        ("bounded_json_only", True),
        ("hdf5_opened", False),
        ("checkpoint_opened", False),
        ("training_started", False),
        ("gpu_started", False),
        ("worker_started", False),
        ("queue_submitted", False),
        ("registry_written", False),
        ("ledger_written", False),
        ("denominator_written", False),
        ("gate_written", False),
        ("completion_written", False),
        ("plan_written", False),
        ("historical_receipt_written", False),
    ):
        if constraints.get(field) != expected:
            errors.append(f"execution constraint {field} is not closed")

    paths = report.get("input_paths")
    inputs = report.get("inputs")
    if not isinstance(paths, Mapping) or set(paths) != set(DEFAULT_INPUT_PATHS):
        errors.append("input_paths do not contain the fixed five roles")
    if not isinstance(inputs, Mapping) or set(inputs) != set(DEFAULT_INPUT_PATHS):
        errors.append("inputs do not contain the fixed five roles")
    if isinstance(inputs, Mapping):
        root_path = Path(root).expanduser().resolve()
        for role in DEFAULT_INPUT_PATHS:
            entry = inputs.get(role)
            reference = entry.get("reference") if isinstance(entry, Mapping) else None
            error = _reference_error(reference, root=root_path, label=role)
            if error:
                errors.append(error)

    blockers = report.get("missing_blockers")
    if not isinstance(blockers, list) or not blockers or len(blockers) != len(set(blockers)):
        errors.append("missing_blockers must be a unique non-empty list")
    implementation = _object(report.get("implementation_boundary"))
    for field, expected in (
        ("cryptographic_root_verification", False),
        ("terminal_artifact_reverification", False),
        ("matrix_scope_join_only", True),
    ):
        if implementation.get(field) != expected:
            errors.append(f"implementation boundary {field} is inconsistent")
    return errors


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.write is not None:
        output = args.write if args.write.is_absolute() else root / args.write
        report = build_report(root)
        _write_json(output, report)
        errors = validate_report(report, root)
        print(json.dumps({"valid": not errors, "output": str(output), "errors": errors}))
        return 0 if not errors else 1
    target = args.verify if args.verify.is_absolute() else root / args.verify
    payload, _ = _load_json(target.relative_to(root), root=root, label="report")
    errors = validate_report(payload, root)
    print(json.dumps({"valid": not errors, "errors": errors}))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
