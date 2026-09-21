"""Pure, read-only contract checks for a future Core formal-run receipt.

This module deliberately sits below the formal planner/readiness/completion
layers.  It does not create a job, launch anything, update a ledger or grant
qualification.  A receipt built by :func:`build_synthetic_receipt` is a
proposal for one member of the future 3-model by 3-seed matrix; it is not a
formal execution record.

The verifier reads only the files named by a receipt and compares their
SHA-256 digests.  It never writes to those files or to any campaign state.
Structural or provenance violations raise :class:`ReceiptContractError`.
Successful validation returns a normalized diagnostic report whose credit and
launch permissions are always zero/false.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA = "core.formal_training_run_receipt.v1"
RECEIPT_KIND = "formal_training_run_receipt"
CONTRACT_SCOPE = "future_3_model_x_3_seed_formal_protocol"

MODELS = ("mlp", "graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
MILESTONES = (8000, 16000, 24000, 32000)
TOTAL_UPDATES = MILESTONES[-1]

# These values are intentionally fixed for the current proposal-only layer.
STATUS = "proposal_only"
MODE = "diagnostic_only"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PROVENANCE_MARKERS = {
    "preprofile",
    "diagnostic",
    "diagnostic_preprofile",
    "pre_profile",
}
_PROVENANCE_ALIAS_FIELDS = (
    "run_type",
    "stage",
    "training_stage",
    "phase",
    "execution_stage",
    "training_phase",
)
_SAFE_PROVENANCE_ALIAS_VALUES = frozenset({STATUS, MODE})
_NEGATIVE_JSON_STATUS_VALUES = frozenset(
    {"false", "fail", "failed", "invalid", "error", "rejected", "unsuccessful"}
)


class ReceiptContractError(ValueError):
    """Raised when a formal-run receipt violates this contract."""


def sha256_file(path: str | Path) -> str:
    """Hash *path* by reading it in bounded chunks; never modify the file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_run_ids() -> tuple[str, ...]:
    """Return the canonical future 3-model by 3-seed run-id matrix."""

    return tuple(f"{model}-seed{seed}" for model in MODELS for seed in SEEDS)


def _error(message: str) -> ReceiptContractError:
    return ReceiptContractError(message)


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{name} must be an object")
    return value


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(f"{name} must be an integer")
    if positive and value <= 0:
        raise _error(f"{name} must be positive")
    return value


def _boolean(value: Any, name: str, expected: bool | None = None) -> bool:
    if not isinstance(value, bool):
        raise _error(f"{name} must be boolean")
    if expected is not None and value is not expected:
        raise _error(f"{name} must be {str(expected).lower()}")
    return value


def _zero_credit(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(f"{name} must be numeric zero")
    if not math.isfinite(float(value)) or float(value) != 0.0:
        raise _error(f"{name} must be numeric zero")


def _validate_finite_values(value: Any, name: str, *, _seen: set[int] | None = None) -> None:
    """Reject non-finite numeric values anywhere in JSON-like metadata."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(f"{name} contains a non-finite numeric value")
        return
    if not isinstance(value, (Mapping, list, tuple)):
        return
    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_finite_values(item, f"{name}.{key}", _seen=seen)
    else:
        for index, item in enumerate(value):
            _validate_finite_values(item, f"{name}[{index}]", _seen=seen)


def _reject_nonfinite_json_constant(value: str, *, name: str) -> Any:
    raise _error(f"{name} contains non-finite JSON constant {value!r}")


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _error(f"{name} must be a lowercase SHA-256 digest")
    return value


def _resolve_file(path_value: Any, *, artifact_root: str | Path | None, name: str) -> Path:
    path_text = _non_empty_string(path_value, f"{name}.path")
    path = Path(path_text).expanduser()
    if path.is_absolute():
        raise _error(f"{name}.path must be relative to artifact_root")
    if artifact_root is None:
        raise _error(f"{name}.path is relative but artifact_root was not supplied")
    root = Path(artifact_root).expanduser().resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise _error(f"{name}.path escapes artifact_root") from exc
    if not resolved.is_file():
        raise _error(f"{name}.path does not name a readable file: {resolved}")
    return resolved


def _reference_path(path: Path, *, artifact_root: str | Path | None) -> str:
    resolved = path.resolve()
    if artifact_root is not None:
        root = Path(artifact_root).expanduser().resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(resolved)


def _file_binding(
    value: Any,
    *,
    name: str,
    artifact_root: str | Path | None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify a path/hash binding and return its read-only normalized form."""

    binding = _object(value, name)
    path = _resolve_file(binding.get("path"), artifact_root=artifact_root, name=name)
    declared = _sha256(binding.get("sha256"), f"{name}.sha256")
    actual = sha256_file(path)
    if declared != actual:
        raise _error(f"{name}.sha256 does not match file contents")
    if expected_sha256 is not None and declared != _sha256(expected_sha256, f"expected {name}.sha256"):
        raise _error(f"{name}.sha256 does not match the expected binding")
    if "bytes" not in binding:
        raise _error(f"{name}.bytes is required")
    declared_bytes = _integer(binding.get("bytes"), f"{name}.bytes", positive=True)
    actual_bytes = path.stat().st_size
    if declared_bytes != actual_bytes:
        raise _error(f"{name}.bytes does not match the file")
    return {
        "path": _reference_path(path, artifact_root=artifact_root),
        "sha256": actual,
        "bytes": actual_bytes,
    }


def _validate_provenance(receipt: Mapping[str, Any]) -> None:
    provenance = _object(receipt.get("provenance"), "provenance")
    kind = _non_empty_string(provenance.get("kind"), "provenance.kind")
    lowered_kind = kind.lower()
    if lowered_kind in _FORBIDDEN_PROVENANCE_MARKERS:
        raise _error("preprofile/diagnostic provenance cannot masquerade as a formal receipt")
    if kind != "formal_run_proposal":
        raise _error("provenance.kind must be 'formal_run_proposal'")
    _boolean(provenance.get("preprofile"), "provenance.preprofile", False)
    _boolean(provenance.get("diagnostic"), "provenance.diagnostic", True)
    _boolean(provenance.get("formal_execution"), "provenance.formal_execution", False)

    # Optional aliases are intentionally allow-listed.  Free-form values such
    # as "formal", "qualification", or "formal_run_proposal" can be
    # misread by downstream consumers even when the envelope is proposal-only.
    for field in _PROVENANCE_ALIAS_FIELDS:
        if field not in receipt:
            continue
        marker = receipt[field]
        if not isinstance(marker, str) or marker not in _SAFE_PROVENANCE_ALIAS_VALUES:
            raise _error(
                f"{field} must be one of {sorted(_SAFE_PROVENANCE_ALIAS_VALUES)} "
                "when present"
            )


def _validate_envelope(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != SCHEMA:
        raise _error(f"receipt schema must be {SCHEMA}")
    if receipt.get("receipt_kind") != RECEIPT_KIND:
        raise _error("receipt_kind is not a formal training run receipt")
    if receipt.get("contract_scope") != CONTRACT_SCOPE:
        raise _error("receipt contract_scope is not the 3-model by 3-seed protocol")
    if receipt.get("status") != STATUS:
        raise _error("current synthetic receipts must have status='proposal_only'")
    if receipt.get("mode") != MODE:
        raise _error("current synthetic receipts must have mode='diagnostic_only'")
    _boolean(receipt.get("diagnostic_only"), "diagnostic_only", True)
    _boolean(receipt.get("proposal_only"), "proposal_only", True)
    _boolean(receipt.get("formal_training"), "formal_training", False)
    _boolean(receipt.get("launch_allowed"), "launch_allowed", False)
    _zero_credit(receipt.get("formal_credit"), "formal_credit")
    if receipt.get("qualification_claim") != "none":
        raise _error("qualification_claim must be 'none'")
    _zero_credit(receipt.get("qualification_credit"), "qualification_credit")
    _boolean(receipt.get("no_future_state"), "no_future_state", True)
    _boolean(receipt.get("no_qualification"), "no_qualification", True)
    _boolean(receipt.get("preprofile"), "preprofile", False)

    future_state = _object(receipt.get("future_state_guards"), "future_state_guards")
    for field in (
        "future_state_inputs",
        "predictor_future_state_inputs",
        "future_observations",
        "future_checkpoints",
    ):
        _boolean(future_state.get(field), f"future_state_guards.{field}", False)

    qualification = _object(receipt.get("qualification_guards"), "qualification_guards")
    for field in ("qualification_admissible", "counts_as_qualification", "counts_as_formal"):
        _boolean(qualification.get(field), f"qualification_guards.{field}", False)

    _validate_provenance(receipt)
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "mode": MODE,
        "diagnostic_only": True,
        "proposal_only": True,
        "formal_training": False,
        "formal_credit": 0,
        "launch_allowed": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "no_future_state": True,
        "no_qualification": True,
    }


def _validate_identity(
    receipt: Mapping[str, Any],
    *,
    seen_run_ids: Iterable[str],
    expected_run_id: str | None,
    expected_model: str | None,
    expected_seed: int | None,
) -> dict[str, Any]:
    run_id = _non_empty_string(receipt.get("run_id"), "run_id")
    model = _non_empty_string(receipt.get("model"), "model")
    seed = _integer(receipt.get("seed"), "seed", positive=True)
    if model not in MODELS:
        raise _error(f"model must be one of {MODELS}")
    if seed not in SEEDS:
        raise _error(f"seed must be one of {SEEDS}")
    canonical_id = f"{model}-seed{seed}"
    if run_id != canonical_id:
        raise _error("run_id is not bound to the declared model and seed")
    if expected_run_id is not None and run_id != _non_empty_string(expected_run_id, "expected_run_id"):
        raise _error("run_id does not match the expected run")
    if expected_model is not None and model != _non_empty_string(expected_model, "expected_model"):
        raise _error("model does not match the expected model")
    if expected_seed is not None and seed != _integer(expected_seed, "expected_seed", positive=True):
        raise _error("seed does not match the expected seed")
    already_seen = {item for item in seen_run_ids}
    if run_id in already_seen:
        raise _error(f"duplicate run_id: {run_id}")
    return {"run_id": run_id, "model": model, "seed": seed}


def _validate_milestones(receipt: Mapping[str, Any]) -> dict[str, Any]:
    milestones = receipt.get("update_milestones")
    if not isinstance(milestones, list) or tuple(milestones) != MILESTONES:
        raise _error(f"update_milestones must be exactly {list(MILESTONES)}")
    training = _object(receipt.get("training"), "training")
    if _integer(training.get("total_updates"), "training.total_updates", positive=True) != TOTAL_UPDATES:
        raise _error("training.total_updates does not match the protocol")
    training_milestones = training.get("update_milestones")
    if not isinstance(training_milestones, list) or tuple(training_milestones) != MILESTONES:
        raise _error("training.update_milestones does not match update_milestones")
    _boolean(training.get("test_included"), "training.test_included", False)
    return {
        "total_updates": TOTAL_UPDATES,
        "update_milestones": list(MILESTONES),
        "test_included": False,
    }


def _validate_json_artifact_metadata(
    path: Path,
    *,
    name: str,
    milestone: int,
    run_id: str,
    model: str,
    seed: int,
) -> None:
    """Check only explicit, auditable metadata in a declared JSON artifact.

    Binary checkpoints are deliberately not inspected.  JSON is inspected
    only when the declaration names a ``.json`` file; metadata is optional so
    generic fixtures remain diagnostic fixtures rather than being promoted to
    training evidence.
    """

    if path.suffix.lower() != ".json":
        return
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(
                stream,
                parse_constant=lambda value: _reject_nonfinite_json_constant(
                    value, name=name
                ),
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(f"{name} declares a JSON artifact with invalid JSON") from exc
    _validate_finite_values(payload, name)
    if not isinstance(payload, Mapping):
        return

    mappings: list[tuple[str, Mapping[str, Any]]] = [("", payload)]
    nested_metadata = payload.get("metadata")
    if isinstance(nested_metadata, Mapping):
        mappings.append((".metadata", nested_metadata))

    for suffix, metadata in mappings:
        field_name = lambda field: f"{name}{suffix}.{field}"
        for field in ("milestone", "update", "step"):
            if field in metadata:
                declared = _integer(metadata[field], field_name(field), positive=True)
                if declared != milestone:
                    raise _error(
                        f"{field_name(field)}={declared} does not match milestone {milestone}"
                    )
        if "run_id" in metadata:
            declared_run_id = _non_empty_string(metadata["run_id"], field_name("run_id"))
            if declared_run_id != run_id:
                raise _error(f"{field_name('run_id')} does not match receipt run_id")
        if "model" in metadata:
            declared_model = _non_empty_string(metadata["model"], field_name("model"))
            if declared_model != model:
                raise _error(f"{field_name('model')} does not match receipt model")
        if "seed" in metadata:
            declared_seed = _integer(metadata["seed"], field_name("seed"), positive=True)
            if declared_seed != seed:
                raise _error(f"{field_name('seed')} does not match receipt seed")

        for field in ("ok", "valid", "success", "passed", "is_valid"):
            if field not in metadata:
                continue
            value = metadata[field]
            if not isinstance(value, bool):
                raise _error(f"{field_name(field)} must be boolean when declared")
            if not value:
                raise _error(f"{field_name(field)} declares a false artifact status")
        for field in ("status", "state"):
            if field not in metadata:
                continue
            value = metadata[field]
            if isinstance(value, bool) and not value:
                raise _error(f"{field_name(field)} declares a false artifact status")
            if isinstance(value, str) and value.strip().lower() in _NEGATIVE_JSON_STATUS_VALUES:
                raise _error(f"{field_name(field)} declares a failed artifact status")


def _validate_artifacts(
    receipt: Mapping[str, Any],
    *,
    artifact_root: str | Path | None,
    identity: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    artifacts = _object(receipt.get("artifacts"), "artifacts")
    normalized: dict[str, list[dict[str, Any]]] = {}
    artifact_identities: dict[tuple[str, str], tuple[str, int]] = {}
    for category in ("checkpoints", "validation"):
        rows = artifacts.get(category)
        if not isinstance(rows, list):
            raise _error(f"artifacts.{category} must be a list")
        if len(rows) != len(MILESTONES):
            raise _error(f"artifacts.{category} must contain every required milestone")
        by_milestone: dict[int, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            item = _object(row, f"artifacts.{category}[{index}]")
            milestone = _integer(item.get("milestone"), f"artifacts.{category}[{index}].milestone", positive=True)
            if milestone in by_milestone:
                raise _error(f"artifacts.{category} contains duplicate milestone {milestone}")
            if milestone not in MILESTONES:
                raise _error(f"artifacts.{category} contains unsupported milestone {milestone}")
            path = _resolve_file(
                item.get("path"),
                artifact_root=artifact_root,
                name=f"artifacts.{category}[{index}]",
            )
            _validate_json_artifact_metadata(
                path,
                name=f"artifacts.{category}[{index}]",
                milestone=milestone,
                run_id=identity["run_id"],
                model=identity["model"],
                seed=identity["seed"],
            )
            normalized_row = _file_binding(
                item,
                name=f"artifacts.{category}[{index}]",
                artifact_root=artifact_root,
            ) | {"milestone": milestone}
            for identity_kind in ("path", "sha256"):
                previous = artifact_identities.get(
                    (identity_kind, normalized_row[identity_kind])
                )
                if previous is not None:
                    previous_category, previous_milestone = previous
                    raise _error(
                        "artifact identity reuse within run: "
                        f"artifacts {identity_kind}={normalized_row[identity_kind]!r} "
                        f"is declared at {previous_category}[{previous_milestone}] "
                        f"and {category}[{milestone}] for {identity['run_id']}"
                    )
                artifact_identities[(identity_kind, normalized_row[identity_kind])] = (
                    category,
                    milestone,
                )
            by_milestone[milestone] = normalized_row
        if set(by_milestone) != set(MILESTONES):
            missing = sorted(set(MILESTONES) - set(by_milestone))
            raise _error(f"artifacts.{category} is missing milestone(s): {missing}")
        normalized[category] = [by_milestone[milestone] for milestone in MILESTONES]
    return normalized


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
    seen_run_ids: Iterable[str] = (),
    expected_run_id: str | None = None,
    expected_model: str | None = None,
    expected_seed: int | None = None,
    expected_dataset_manifest_sha256: str | None = None,
    expected_source_closure_sha256: str | None = None,
    expected_training_config_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify one proposal-only receipt and return a diagnostic report.

    ``artifact_root`` is used only to resolve relative paths.  Every declared
    path is opened read-only and its actual SHA-256 is compared with the
    receipt.  The optional expected hashes provide an external binding for a
    caller that already knows the active manifest/source/config closure.
    """

    if not isinstance(receipt, Mapping):
        raise _error("receipt must be an object")
    _validate_finite_values(receipt, "receipt")
    envelope = _validate_envelope(receipt)
    identity = _validate_identity(
        receipt,
        seen_run_ids=seen_run_ids,
        expected_run_id=expected_run_id,
        expected_model=expected_model,
        expected_seed=expected_seed,
    )
    training = _validate_milestones(receipt)
    bindings = _object(receipt.get("bindings"), "bindings")
    dataset = _file_binding(
        bindings.get("dataset_manifest"),
        name="bindings.dataset_manifest",
        artifact_root=artifact_root,
        expected_sha256=expected_dataset_manifest_sha256,
    )
    source = _file_binding(
        bindings.get("source_closure"),
        name="bindings.source_closure",
        artifact_root=artifact_root,
        expected_sha256=expected_source_closure_sha256,
    )
    config = _file_binding(
        bindings.get("training_config"),
        name="bindings.training_config",
        artifact_root=artifact_root,
        expected_sha256=expected_training_config_sha256,
    )
    artifacts = _validate_artifacts(
        receipt,
        artifact_root=artifact_root,
        identity=identity,
    )
    return {
        **envelope,
        **identity,
        "training": training,
        "bindings": {
            "dataset_manifest": dataset,
            "source_closure": source,
            "training_config": config,
        },
        "artifacts": artifacts,
        "valid": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "no_future_state": True,
        "no_qualification": True,
    }


def _check_cross_run_independence(
    reports: Sequence[Mapping[str, Any]],
    *,
    expected_dataset_manifest_sha256: str | None,
    expected_source_closure_sha256: str | None,
    expected_training_config_sha256: str | None,
) -> None:
    """Reject reused file identities or hashes between distinct run IDs.

    Checkpoint and validation artifacts are always run-specific.  The three
    input bindings may be shared only when the caller supplies the matching
    external SHA-256 anchor; that makes shared inputs explicit and keeps an
    unanchored copied receipt fail-closed.
    """

    shared_binding_anchors = {
        "dataset_manifest": expected_dataset_manifest_sha256,
        "source_closure": expected_source_closure_sha256,
        "training_config": expected_training_config_sha256,
    }
    seen: dict[tuple[str, str, str], tuple[str, str, str, int | None]] = {}

    def claim(
        scope: str,
        binding: Mapping[str, Any],
        run_id: str,
        *,
        category: str,
        milestone: int | None,
    ) -> None:
        location = (run_id, category, milestone)
        for identity_kind in ("path", "sha256"):
            key = (scope, identity_kind, str(binding[identity_kind]))
            previous = seen.get(key)
            if previous is not None and previous != location:
                previous_run_id, previous_category, previous_milestone = previous
                if previous_run_id == run_id:
                    raise _error(
                        "artifact identity reuse within run: "
                        f"{scope} {identity_kind}={binding[identity_kind]!r} "
                        f"is declared at {previous_category}[{previous_milestone}] "
                        f"and {category}[{milestone}] for {run_id}"
                    )
                raise _error(
                    "cross-run independence violation: "
                    f"{scope} {identity_kind}={binding[identity_kind]!r} "
                    f"is reused by {previous_run_id} and {run_id}"
                )
            seen[key] = location

    for report in reports:
        run_id = report["run_id"]
        for category in ("checkpoints", "validation"):
            for row in report["artifacts"][category]:
                claim(
                    "artifacts",
                    row,
                    run_id,
                    category=category,
                    milestone=row["milestone"],
                )
        for category, expected in shared_binding_anchors.items():
            if expected is not None:
                continue
            claim(
                "bindings." + category,
                report["bindings"][category],
                run_id,
                category=category,
                milestone=None,
            )


def verify_receipt_set(
    receipts: Sequence[Mapping[str, Any]],
    *,
    artifact_root: str | Path | None = None,
    require_complete: bool = False,
    expected_dataset_manifest_sha256: str | None = None,
    expected_source_closure_sha256: str | None = None,
    expected_training_config_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify a collection, rejecting duplicate IDs and reused file bindings.

    Optional external input hashes are forwarded to every receipt.  When
    supplied, they explicitly authorize the corresponding input binding to be
    shared by otherwise independent runs.
    """

    if isinstance(receipts, (str, bytes)) or not isinstance(receipts, Sequence):
        raise _error("receipts must be a sequence of receipt objects")
    if not receipts:
        raise _error("receipts must not be empty")
    reports: list[dict[str, Any]] = []
    seen: list[str] = []
    for index, receipt in enumerate(receipts):
        try:
            report = verify_receipt(
                receipt,
                artifact_root=artifact_root,
                seen_run_ids=seen,
                expected_dataset_manifest_sha256=expected_dataset_manifest_sha256,
                expected_source_closure_sha256=expected_source_closure_sha256,
                expected_training_config_sha256=expected_training_config_sha256,
            )
        except ReceiptContractError as exc:
            raise _error(f"receipt[{index}] is invalid: {exc}") from exc
        reports.append(report)
        seen.append(report["run_id"])
    expected = set(expected_run_ids())
    actual = set(seen)
    if require_complete and actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise _error(f"3x3 run matrix is incomplete; missing={missing}, extra={extra}")
    _check_cross_run_independence(
        reports,
        expected_dataset_manifest_sha256=expected_dataset_manifest_sha256,
        expected_source_closure_sha256=expected_source_closure_sha256,
        expected_training_config_sha256=expected_training_config_sha256,
    )
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "mode": MODE,
        "diagnostic_only": True,
        "proposal_only": True,
        "valid": True,
        "receipt_count": len(reports),
        "run_ids": seen,
        "matrix_complete": actual == expected,
        "formal_training": False,
        "formal_credit": 0,
        "launch_allowed": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "no_future_state": True,
        "no_qualification": True,
        "receipts": reports,
    }


def verify_formal_run_matrix(
    receipts: Sequence[Mapping[str, Any]],
    *,
    artifact_root: str | Path | None = None,
    expected_dataset_manifest_sha256: str | None = None,
    expected_source_closure_sha256: str | None = None,
    expected_training_config_sha256: str | None = None,
) -> dict[str, Any]:
    """Strict alias for validating all future 3-model by 3-seed receipts."""

    return verify_receipt_set(
        receipts,
        artifact_root=artifact_root,
        require_complete=True,
        expected_dataset_manifest_sha256=expected_dataset_manifest_sha256,
        expected_source_closure_sha256=expected_source_closure_sha256,
        expected_training_config_sha256=expected_training_config_sha256,
    )


def _display_path(path: Path, *, artifact_root: str | Path | None) -> str:
    return _reference_path(path, artifact_root=artifact_root)


def _synthetic_binding(path_value: str | Path, *, artifact_root: str | Path | None, name: str) -> dict[str, Any]:
    # Receipt paths are strings, while the Python factory intentionally also
    # accepts ``Path`` objects for callers constructing synthetic fixtures.
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        if artifact_root is None:
            raise _error(f"{name}.path is absolute but artifact_root was not supplied")
        root = Path(artifact_root).expanduser().resolve()
        try:
            path_value = candidate.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise _error(f"{name}.path is outside artifact_root") from exc
    path = _resolve_file(str(path_value), artifact_root=artifact_root, name=name)
    return {
        "path": _display_path(path, artifact_root=artifact_root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def build_synthetic_receipt(
    *,
    run_id: str,
    model: str,
    seed: int,
    dataset_manifest: str | Path,
    source_closure: str | Path,
    training_config: str | Path,
    checkpoints: Mapping[int, str | Path],
    validation: Mapping[int, str | Path],
    artifact_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build one read-only synthetic proposal receipt from existing files.

    The helper computes hashes but does not create, alter, or delete any
    artifact.  It is intentionally explicit about all four checkpoint and
    validation milestones so missing evidence cannot be silently filled in.
    """

    checkpoint_rows = []
    validation_rows = []
    for milestone in MILESTONES:
        if milestone not in checkpoints:
            raise _error(f"checkpoints is missing milestone {milestone}")
        if milestone not in validation:
            raise _error(f"validation is missing milestone {milestone}")
        checkpoint_rows.append(
            {"milestone": milestone, **_synthetic_binding(
                checkpoints[milestone], artifact_root=artifact_root,
                name=f"checkpoints[{milestone}]"
            )}
        )
        validation_rows.append(
            {"milestone": milestone, **_synthetic_binding(
                validation[milestone], artifact_root=artifact_root,
                name=f"validation[{milestone}]"
            )}
        )
    return {
        "schema": SCHEMA,
        "receipt_kind": RECEIPT_KIND,
        "contract_scope": CONTRACT_SCOPE,
        "status": STATUS,
        "mode": MODE,
        "diagnostic_only": True,
        "proposal_only": True,
        "formal_training": False,
        "formal_credit": 0,
        "launch_allowed": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "no_future_state": True,
        "no_qualification": True,
        "preprofile": False,
        "run_id": run_id,
        "model": model,
        "seed": seed,
        "provenance": {
            "kind": "formal_run_proposal",
            "preprofile": False,
            "diagnostic": True,
            "formal_execution": False,
        },
        "future_state_guards": {
            "future_state_inputs": False,
            "predictor_future_state_inputs": False,
            "future_observations": False,
            "future_checkpoints": False,
        },
        "qualification_guards": {
            "qualification_admissible": False,
            "counts_as_qualification": False,
            "counts_as_formal": False,
        },
        "update_milestones": list(MILESTONES),
        "training": {
            "total_updates": TOTAL_UPDATES,
            "update_milestones": list(MILESTONES),
            "test_included": False,
        },
        "bindings": {
            "dataset_manifest": _synthetic_binding(
                dataset_manifest, artifact_root=artifact_root, name="dataset_manifest"
            ),
            "source_closure": _synthetic_binding(
                source_closure, artifact_root=artifact_root, name="source_closure"
            ),
            "training_config": _synthetic_binding(
                training_config, artifact_root=artifact_root, name="training_config"
            ),
        },
        "artifacts": {
            "checkpoints": checkpoint_rows,
            "validation": validation_rows,
        },
    }


# A concise alias for callers that prefer a factory-style name.
make_synthetic_receipt = build_synthetic_receipt


__all__ = [
    "CONTRACT_SCOPE",
    "MILESTONES",
    "MODELS",
    "RECEIPT_KIND",
    "SCHEMA",
    "SEEDS",
    "STATUS",
    "TOTAL_UPDATES",
    "ReceiptContractError",
    "build_synthetic_receipt",
    "expected_run_ids",
    "make_synthetic_receipt",
    "sha256_file",
    "verify_formal_run_matrix",
    "verify_receipt",
    "verify_receipt_set",
]
