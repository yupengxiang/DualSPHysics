#!/usr/bin/env python3
"""Audit A8 checkpoint/model-reproduction readiness without opening payloads.

This is deliberately different from the coarse A8 product bridge.  It
compares the real checkpoint-free core.reader_bundle.v2 index with a
historical checkpoint-bearing bundle and its checkpoint registry.  Inputs are
bounded, strict JSON objects.  Every non-JSON package artifact is inspected
with lstat only; checkpoint, HDF5, NPZ, source, and model bytes are never
opened or hashed by this module.

The result is an audit, not an admission.  A checkpoint count, a historical
diagnostic receipt, a registry SHA claim, or a successful lstat can never mint
independent reproduction, T1/T2 qualification, formal training credit, or
completion state.  The next trusted step is an independently attested
checkpoint binding for the current v2 package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from collections import Counter
from collections.abc import Mapping

if __name__ == "__main__":
    sys.dont_write_bytecode = True

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from scripts.core_strict_json import read_bounded_json_object  # noqa: E402


MAX_JSON_BYTES = 1_048_576
MAX_BUNDLE_FILES = 4096
MAX_STRING_BYTES = 4096
SHA256_HEX_LENGTH = 64
CURRENT_BUNDLE_SCHEMA = "core.reader_bundle.v2"
CHECKPOINT_REGISTRY_SCHEMA = "core.bundled_checkpoints.v1"
REPORT_SCHEMA = "core.a8.checkpoint_model_reproduction_readiness_audit.v1"
REPORT_ID = "a8-checkpoint-model-reproduction-readiness-audit-v1"
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"

DEFAULT_CURRENT_BUNDLE = (
    LAB_ROOT / "campaigns/core-v1/reproduction/a8-full-reproduce-v2/bundle.json"
)
DEFAULT_HISTORICAL_BUNDLE = (
    LAB_ROOT / "campaigns/core-v1/reproduction/a8-full-reproduce-v1/bundle/bundle.json"
)
DEFAULT_HISTORICAL_REGISTRY = (
    LAB_ROOT / "campaigns/core-v1/reproduction/a8-full-reproduce-v1/bundle/checkpoints.json"
)
DEFAULT_HISTORICAL_PROVENANCE = (
    LAB_ROOT
    / "campaigns/core-v1/reproduction/a8-full-reproduce-v1/checkpoint-provenance.json"
)
DEFAULT_REPORT = (
    LAB_ROOT / "reports/A8-CHECKPOINT-MODEL-REPRODUCTION-READINESS-AUDIT-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = (
    LAB_ROOT
    / "reports/A8-CHECKPOINT-MODEL-REPRODUCTION-READINESS-AUDIT-V1-2026-09-28.zh-CN.md"
)

FALSE_CLAIMS = {
    "independent_reproduction": False,
    "formal_training": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "credit": 0,
}
ZERO_MUTATIONS = {
    "registry": 0,
    "ledger": 0,
    "denominator": 0,
    "gate": 0,
    "completion": 0,
    "plan": 0,
}


class AuditContractError(ValueError):
    """Raised when a bounded A8 identity cannot be reconciled safely."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_HEX_LENGTH:
        raise AuditContractError(f"{label} must be a SHA-256 hex claim")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise AuditContractError(f"{label} must be a SHA-256 hex claim")
    return value.lower()


def _bounded_string(value: object, *, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AuditContractError(f"{label} must be a string")
    if not allow_empty and not value:
        raise AuditContractError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise AuditContractError(f"{label} exceeds the bounded string limit")
    return value


def _safe_relative(value: object, *, label: str) -> str:
    value = _bounded_string(value, label=label)
    if "\\" in value:
        raise AuditContractError(f"{label} uses a non-portable backslash path")
    candidate = Path(value)
    if candidate.is_absolute() or value.startswith("/"):
        raise AuditContractError(f"{label} must be relative")
    if value in {"", "."} or ".." in candidate.parts:
        raise AuditContractError(f"{label} escapes its package root")
    if candidate.as_posix() != value:
        raise AuditContractError(f"{label} is not normalized")
    return value


def _display_path(path: Path, lab_root: Path) -> tuple[str, bool]:
    """Return a stable display path and whether it is portable in lab scope."""
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    root = Path(os.path.abspath(lab_root))
    try:
        return absolute.relative_to(root).as_posix(), True
    except ValueError:
        return str(absolute), False


def _json_ref(
    path: Path, *, lab_root: Path, label: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Read exactly one bounded strict JSON object and return public metadata."""
    candidate = Path(path).expanduser()
    if candidate.suffix.lower() != ".json":
        raise AuditContractError(f"{label} must be a JSON input")
    try:
        payload, safe_path, raw_sha256 = read_bounded_json_object(
            candidate, max_bytes=MAX_JSON_BYTES, label=label
        )
        metadata = os.lstat(safe_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AuditContractError(
            f"{label} cannot be read within the JSON boundary: {error}"
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AuditContractError(f"{label} is not a regular non-symlink JSON file")
    shown, portable = _display_path(safe_path, lab_root)
    public = {
        "path": shown,
        "portable_path": portable,
        "bytes": int(metadata.st_size),
        "sha256": raw_sha256,
        "schema": payload.get("schema"),
        "opened": True,
        "read_policy": "strict_bounded_json_only",
    }
    return public, payload


def _artifact_row_map(
    payload: Mapping[str, object], *, label: str
) -> tuple[dict[str, dict[str, object]], list[str]]:
    rows = payload.get("files")
    if not isinstance(rows, list):
        raise AuditContractError(f"{label}.files must be a list")
    if len(rows) > MAX_BUNDLE_FILES:
        raise AuditContractError(f"{label}.files exceeds the bounded row limit")
    mapped: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"{label}.files[{index}] is not an object")
            continue
        try:
            relative = _safe_relative(
                row.get("path"), label=f"{label}.files[{index}].path"
            )
            digest = _sha256(
                row.get("sha256"), label=f"{label}.files[{index}].sha256"
            )
            bytes_value = row.get("bytes")
            if (
                isinstance(bytes_value, bool)
                or not isinstance(bytes_value, int)
                or bytes_value < 0
            ):
                raise AuditContractError(
                    f"{label}.files[{index}].bytes must be non-negative"
                )
        except AuditContractError as error:
            errors.append(str(error))
            continue
        if relative in mapped:
            errors.append(f"{label}.files has duplicate path: {relative}")
            continue
        normalized = dict(row)
        normalized["path"] = relative
        normalized["sha256"] = digest
        normalized["bytes"] = bytes_value
        mapped[relative] = normalized
    return mapped, errors


def _lstat_artifact(
    root: Path, row: Mapping[str, object], *, label: str
) -> tuple[dict[str, object], str | None]:
    relative = _safe_relative(row.get("path"), label=f"{label}.path")
    target = root / relative
    try:
        metadata = os.lstat(target)
    except OSError as error:
        return (
            {
                "path": relative,
                "exists": False,
                "lstat_only": True,
                "content_opened": False,
                "declared_bytes": row.get("bytes"),
                "declared_sha256": row.get("sha256"),
            },
            f"{label}_missing:{relative}:{error.__class__.__name__}",
        )
    is_regular = stat.S_ISREG(metadata.st_mode)
    is_symlink = stat.S_ISLNK(metadata.st_mode)
    record = {
        "path": relative,
        "exists": True,
        "regular": is_regular,
        "symlink": is_symlink,
        "lstat_only": True,
        "content_opened": False,
        "declared_bytes": row.get("bytes"),
        "lstat_bytes": int(metadata.st_size),
        "declared_sha256": row.get("sha256"),
        "content_hash_verified": False,
    }
    if is_symlink:
        return record, f"{label}_symlink_forbidden:{relative}"
    if not is_regular:
        return record, f"{label}_not_regular:{relative}"
    declared_bytes = row.get("bytes")
    if isinstance(declared_bytes, int) and metadata.st_size != declared_bytes:
        return (
            record,
            f"{label}_byte_drift:{relative}:{declared_bytes}!={metadata.st_size}",
        )
    return record, None


def _inventory(
    payload: Mapping[str, object], *, root: Path, label: str
) -> tuple[dict[str, object], dict[str, dict[str, object]], list[str]]:
    rows, row_errors = _artifact_row_map(payload, label=label)
    blockers = list(row_errors)
    suffix_counts: Counter[str] = Counter()
    absolute_reuse_sources: list[str] = []
    malformed_reuse_sources: list[str] = []
    lstat_records: list[dict[str, object]] = []
    for relative, row in rows.items():
        suffix_counts[Path(relative).suffix.lower() or "<none>"] += 1
        reused_from = row.get("reused_from")
        if reused_from is not None:
            if not isinstance(reused_from, str):
                malformed_reuse_sources.append(relative)
            elif Path(reused_from).is_absolute():
                absolute_reuse_sources.append(relative)
            else:
                try:
                    _safe_relative(
                        reused_from, label=f"{label}.{relative}.reused_from"
                    )
                except AuditContractError:
                    malformed_reuse_sources.append(relative)
        record, error = _lstat_artifact(
            root, row, label=f"{label}.artifact[{relative}]"
        )
        lstat_records.append(record)
        if error:
            blockers.append(error)
    if absolute_reuse_sources:
        blockers.append(
            f"{label}_absolute_reused_from:{len(absolute_reuse_sources)}"
        )
    if malformed_reuse_sources:
        blockers.append(
            f"{label}_malformed_reused_from:{len(malformed_reuse_sources)}"
        )
    missing = sorted(
        record["path"] for record in lstat_records if not record.get("exists")
    )
    byte_drift = sorted(
        record["path"]
        for record in lstat_records
        if record.get("exists")
        and isinstance(record.get("declared_bytes"), int)
        and record.get("lstat_bytes") != record.get("declared_bytes")
    )
    checkpoint_paths = sorted(
        path for path in rows if path.startswith("models/")
    )
    json_paths = sorted(
        path for path in rows if Path(path).suffix.lower() == ".json"
    )
    inventory = {
        "declared_artifact_count": len(rows),
        "lstat_artifact_count": len(lstat_records),
        "regular_artifact_count": sum(
            bool(record.get("regular")) for record in lstat_records
        ),
        "missing_paths": missing,
        "byte_drift_paths": byte_drift,
        "checkpoint_artifact_paths": checkpoint_paths,
        "json_artifact_paths": json_paths,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "absolute_reuse_source_count": len(absolute_reuse_sources),
        "absolute_reuse_source_artifacts": absolute_reuse_sources,
        "malformed_reuse_source_artifacts": malformed_reuse_sources,
        "all_declared_paths_relative": not row_errors,
        "all_assets_lstat_only": all(
            not record.get("content_opened") for record in lstat_records
        ),
        "any_non_json_content_opened": False,
        "content_hashes_verified": False,
        "records": lstat_records,
    }
    return inventory, rows, sorted(set(blockers))


def _dataset_projection(
    payload: Mapping[str, object],
    rows: Mapping[str, Mapping[str, object]],
    *,
    root: Path,
    lab_root: Path,
    label: str,
) -> tuple[dict[str, object], dict[str, object] | None, list[str]]:
    blockers: list[str] = []
    row = rows.get("dataset.json")
    if row is None:
        return {"registered": False}, None, [
            f"{label}_dataset_json_not_registered"
        ]
    dataset_path = root / "dataset.json"
    try:
        ref, dataset = _json_ref(
            dataset_path, lab_root=lab_root, label=f"{label}.dataset.json"
        )
    except AuditContractError as error:
        return {"registered": True, "json_read": False}, None, [str(error)]
    declared_sha = row.get("sha256")
    if declared_sha != ref["sha256"]:
        blockers.append(f"{label}_dataset_bundle_sha_drift")
    if dataset.get("schema") is None:
        blockers.append(f"{label}_dataset_schema_missing")
    cases = dataset.get("cases")
    case_count = len(cases) if isinstance(cases, list) else None
    declared_case_count = payload.get("case_count")
    if (
        isinstance(declared_case_count, int)
        and case_count is not None
        and declared_case_count != case_count
    ):
        blockers.append(
            f"{label}_dataset_case_count_drift:{declared_case_count}!={case_count}"
        )
    projection = {
        "registered": True,
        "ref": ref,
        "schema": dataset.get("schema"),
        "case_count": case_count,
        "declared_bundle_case_count": declared_case_count,
        "raw_sha256_matches_bundle_claim": declared_sha == ref["sha256"],
        "referenced_asset_contents_opened": False,
        "referenced_hdf5_or_npz_opened": False,
    }
    return projection, dataset, blockers


def _checkpoint_entrypoint(
    value: object, *, label: str
) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    text = _bounded_string(value, label=label)
    try:
        tokens = shlex.split(text)
    except ValueError as error:
        return None, f"{label}_shell_parse_error:{error.__class__.__name__}"
    try:
        index = tokens.index("--checkpoint")
    except ValueError:
        return None, f"{label}_checkpoint_argument_missing"
    if index + 1 >= len(tokens):
        return None, f"{label}_checkpoint_argument_value_missing"
    try:
        return _safe_relative(
            tokens[index + 1], label=f"{label}.checkpoint"
        ), None
    except AuditContractError as error:
        return None, str(error)


def _bundle_projection(
    payload: Mapping[str, object],
    *,
    bundle_ref: Mapping[str, object],
    bundle_root: Path,
    lab_root: Path,
    label: str,
) -> tuple[
    dict[str, object],
    dict[str, dict[str, object]],
    dict[str, object] | None,
    list[str],
]:
    blockers: list[str] = []
    schema = payload.get("schema")
    if not isinstance(schema, str):
        blockers.append(f"{label}_schema_missing")
    checkpoint_count = payload.get("checkpoint_count")
    if (
        isinstance(checkpoint_count, bool)
        or not isinstance(checkpoint_count, int)
        or checkpoint_count < 0
    ):
        blockers.append(f"{label}_checkpoint_count_malformed")
        checkpoint_count_value: int | None = None
    else:
        checkpoint_count_value = checkpoint_count
    case_count = payload.get("case_count")
    if (
        isinstance(case_count, bool)
        or not isinstance(case_count, int)
        or case_count < 0
    ):
        blockers.append(f"{label}_case_count_malformed")
    files_inventory, rows, inventory_blockers = _inventory(
        payload, root=bundle_root, label=label
    )
    blockers.extend(inventory_blockers)
    dataset, dataset_payload, dataset_blockers = _dataset_projection(
        payload, rows, root=bundle_root, lab_root=lab_root, label=label
    )
    blockers.extend(dataset_blockers)
    model_supported = payload.get("model_reproduction_supported")
    if model_supported is not None and not isinstance(model_supported, bool):
        blockers.append(f"{label}_model_reproduction_supported_malformed")
    model_entrypoint = payload.get("model_entrypoint")
    checkpoint_entrypoint_path, entrypoint_error = _checkpoint_entrypoint(
        model_entrypoint, label=f"{label}.model_entrypoint"
    )
    if entrypoint_error:
        blockers.append(entrypoint_error)
    entrypoint_lstat = None
    if checkpoint_entrypoint_path is not None:
        entrypoint_row = rows.get(checkpoint_entrypoint_path)
        if entrypoint_row is None:
            blockers.append(
                f"{label}_model_entrypoint_checkpoint_unregistered:{checkpoint_entrypoint_path}"
            )
        entrypoint_lstat, entrypoint_lstat_error = _lstat_artifact(
            bundle_root,
            entrypoint_row or {"path": checkpoint_entrypoint_path},
            label=f"{label}.model_entrypoint_checkpoint",
        )
        if entrypoint_lstat_error:
            blockers.append(entrypoint_lstat_error)
    code_rows = {
        path: row
        for path, row in rows.items()
        if path.startswith("code/scripts/")
    }
    reuse_contract = {
        "schema": schema,
        "current_v2_schema": CURRENT_BUNDLE_SCHEMA,
        "is_current_v2": schema == CURRENT_BUNDLE_SCHEMA,
        "full_core_release": payload.get("full_core_release"),
        "physical_storage": payload.get("physical_storage"),
        "entrypoint": payload.get("entrypoint"),
        "model_entrypoint": model_entrypoint,
        "model_entrypoint_checkpoint_path": checkpoint_entrypoint_path,
        "model_entrypoint_lstat": entrypoint_lstat,
        "model_reproduction_supported": model_supported,
        "checkpoint_count": checkpoint_count_value,
        "all_package_paths_relative": bool(
            files_inventory["all_declared_paths_relative"]
        ),
        "absolute_reuse_source_count": files_inventory[
            "absolute_reuse_source_count"
        ],
        "portable_path_contract": bool(
            files_inventory["all_declared_paths_relative"]
            and files_inventory["absolute_reuse_source_count"] == 0
        ),
    }
    projection = {
        "bundle_ref": dict(bundle_ref),
        "bundle_root": _display_path(bundle_root, lab_root)[0],
        "schema": schema,
        "case_count": case_count,
        "checkpoint_count": checkpoint_count_value,
        "model_reproduction_supported": model_supported,
        "artifact_count": files_inventory["declared_artifact_count"],
        "dataset": dataset,
        "code_paths": sorted(code_rows),
        "code_sha256": {
            path: row.get("sha256") for path, row in sorted(code_rows.items())
        },
        "inventory": {
            key: value for key, value in files_inventory.items() if key != "records"
        },
        "reuse_contract": reuse_contract,
        "raw_payload_canonical_sha256": _canonical_sha256(payload),
    }
    return projection, rows, dataset_payload, sorted(set(blockers))


def _checkpoint_registry_projection(
    payload: Mapping[str, object],
    *,
    registry_ref: Mapping[str, object],
    bundle_root: Path,
    bundle_rows: Mapping[str, Mapping[str, object]],
    label: str,
) -> tuple[dict[str, object], list[str]]:
    blockers: list[str] = []
    schema = payload.get("schema")
    if schema != CHECKPOINT_REGISTRY_SCHEMA:
        blockers.append(f"{label}_schema_unsupported:{schema!r}")
    raw_rows = payload.get("checkpoints")
    if not isinstance(raw_rows, list):
        blockers.append(f"{label}_checkpoints_missing")
        raw_rows = []
    if len(raw_rows) > MAX_BUNDLE_FILES:
        raise AuditContractError(
            f"{label}.checkpoints exceeds the bounded row limit"
        )
    identities: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(raw_rows):
        if not isinstance(item, Mapping):
            blockers.append(f"{label}_row_not_object:{index}")
            continue
        try:
            model_kind = _bounded_string(
                item.get("model_kind"),
                label=f"{label}[{index}].model_kind",
            )
            relative = _safe_relative(
                item.get("path"), label=f"{label}[{index}].path"
            )
            digest = _sha256(
                item.get("sha256"), label=f"{label}[{index}].sha256"
            )
            seed = item.get("seed")
            update = item.get("update")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise AuditContractError(
                    f"{label}[{index}].seed must be an integer"
                )
            if (
                isinstance(update, bool)
                or not isinstance(update, int)
                or update < 0
            ):
                raise AuditContractError(
                    f"{label}[{index}].update must be a non-negative integer"
                )
        except AuditContractError as error:
            blockers.append(str(error))
            continue
        if relative in seen_paths:
            blockers.append(f"{label}_duplicate_path:{relative}")
        seen_paths.add(relative)
        bundle_row = bundle_rows.get(relative)
        if bundle_row is None:
            blockers.append(
                f"{label}_path_not_registered_in_bundle:{relative}"
            )
        elif bundle_row.get("sha256") != digest:
            blockers.append(f"{label}_bundle_sha_drift:{relative}")
        record, error = _lstat_artifact(
            bundle_root,
            bundle_row or {"path": relative, "sha256": digest},
            label=f"{label}.artifact[{relative}]",
        )
        if error:
            blockers.append(error)
        identities.append(
            {
                "model_kind": model_kind,
                "path": relative,
                "seed": seed,
                "update": update,
                "sha256_claim": digest,
                "bundle_registered": bundle_row is not None,
                "lstat": record,
                "content_hash_verified": False,
            }
        )
    projection = {
        "registry_ref": dict(registry_ref),
        "schema": schema,
        "declared_count": len(raw_rows),
        "identities": identities,
        "formal_training_qualification": payload.get(
            "formal_training_qualification"
        ),
        "content_hashes_verified": False,
        "checkpoint_contents_opened": False,
        "registry_sha_claim_bound_to_bundle": registry_ref.get("sha256")
        == bundle_rows.get("checkpoints.json", {}).get("sha256"),
        "raw_payload_canonical_sha256": _canonical_sha256(payload),
    }
    return projection, sorted(set(blockers))


def _provenance_projection(
    payload: Mapping[str, object],
    *,
    provenance_ref: Mapping[str, object],
    registry: Mapping[str, object],
    label: str,
) -> tuple[dict[str, object], list[str]]:
    blockers: list[str] = []
    checkpoint = payload.get("checkpoint")
    training = payload.get("training")
    dataset_binding = payload.get("dataset_binding")
    if not isinstance(checkpoint, Mapping):
        blockers.append(f"{label}_checkpoint_missing")
        checkpoint = {}
    if not isinstance(training, Mapping):
        blockers.append(f"{label}_training_missing")
        training = {}
    if not isinstance(dataset_binding, Mapping):
        blockers.append(f"{label}_dataset_binding_missing")
        dataset_binding = {}
    checkpoint_sha = checkpoint.get("sha256")
    if checkpoint_sha is not None:
        try:
            checkpoint_sha = _sha256(
                checkpoint_sha, label=f"{label}.checkpoint.sha256"
            )
        except AuditContractError as error:
            blockers.append(str(error))
    checkpoint_path = checkpoint.get("path")
    checkpoint_path_kind = None
    checkpoint_path_exists = False
    checkpoint_lstat = None
    if isinstance(checkpoint_path, str):
        path_value = Path(checkpoint_path)
        checkpoint_path_kind = (
            "absolute" if path_value.is_absolute() else "relative"
        )
        try:
            checkpoint_lstat = os.lstat(path_value)
            checkpoint_path_exists = True
        except OSError:
            checkpoint_path_exists = False
        if path_value.is_absolute():
            blockers.append(f"{label}_absolute_checkpoint_source_path")
    else:
        blockers.append(f"{label}_checkpoint_path_missing")
    provenance_dataset_path = dataset_binding.get("path")
    provenance_dataset_path_kind = None
    if isinstance(provenance_dataset_path, str):
        provenance_dataset_path_kind = (
            "absolute"
            if Path(provenance_dataset_path).is_absolute()
            else "relative"
        )
        if provenance_dataset_path_kind == "absolute":
            blockers.append(f"{label}_absolute_dataset_source_path")
    diagnostic_only = payload.get("diagnostic_only") is True
    formal_count = payload.get("formal_training_count")
    if not diagnostic_only:
        blockers.append(f"{label}_not_marked_diagnostic_only")
    if formal_count != 0:
        blockers.append(f"{label}_formal_training_count_not_zero")
    registry_identities = registry.get("identities", [])
    registry_match = None
    if isinstance(registry_identities, list) and checkpoint_sha:
        registry_match = next(
            (
                item
                for item in registry_identities
                if isinstance(item, Mapping)
                and item.get("sha256_claim") == checkpoint_sha
            ),
            None,
        )
    if checkpoint_sha and registry_match is None:
        blockers.append(f"{label}_checkpoint_sha_not_in_registry")
    initialization = training.get("initialization_evidence")
    if not isinstance(initialization, Mapping):
        initialization = {}
    training_identity = {
        "model_kind": checkpoint.get("model_kind")
        or payload.get("model_kind"),
        "seed": payload.get("seed"),
        "update": payload.get("update"),
        "completed_updates": training.get("completed_updates"),
        "hidden": initialization.get("hidden"),
        "run_id": training.get("run_id"),
    }
    projection = {
        "provenance_ref": dict(provenance_ref),
        "schema": payload.get("schema"),
        "diagnostic_only": diagnostic_only,
        "formal_training_count": formal_count,
        "qualification_note": payload.get("qualification_note"),
        "checkpoint": {
            "model_kind": checkpoint.get("model_kind")
            or payload.get("model_kind"),
            "path": checkpoint_path,
            "path_kind": checkpoint_path_kind,
            "path_exists_by_lstat": checkpoint_path_exists,
            "lstat_regular": bool(
                checkpoint_lstat
                and stat.S_ISREG(checkpoint_lstat.st_mode)
            ),
            "sha256_claim": checkpoint_sha,
            "content_opened": False,
            "content_hash_verified": False,
        },
        "dataset_binding": {
            "dataset_id": dataset_binding.get("dataset_id"),
            "path": dataset_binding.get("path"),
            "path_kind": provenance_dataset_path_kind,
            "sha256": dataset_binding.get("sha256"),
            "canonical_sha256": dataset_binding.get("canonical_sha256"),
        },
        "training_identity": training_identity,
        "registry_sha_match": registry_match is not None,
        "raw_payload_canonical_sha256": _canonical_sha256(payload),
    }
    return projection, sorted(set(blockers))


def _code_comparison(
    current: Mapping[str, object], historical: Mapping[str, object]
) -> dict[str, object]:
    current_code = current.get("code_sha256", {})
    historical_code = historical.get("code_sha256", {})
    if not isinstance(current_code, Mapping) or not isinstance(
        historical_code, Mapping
    ):
        return {
            "common_paths": [],
            "same_sha_paths": [],
            "different_sha_paths": [],
            "current_only_paths": [],
            "historical_only_paths": [],
        }
    current_paths = set(current_code)
    historical_paths = set(historical_code)
    common = sorted(current_paths & historical_paths)
    return {
        "common_paths": common,
        "same_sha_paths": sorted(
            path for path in common if current_code[path] == historical_code[path]
        ),
        "different_sha_paths": sorted(
            path
            for path in common
            if current_code[path] != historical_code[path]
        ),
        "current_only_paths": sorted(current_paths - historical_paths),
        "historical_only_paths": sorted(historical_paths - current_paths),
    }


def build_audit(
    *,
    lab_root: Path = LAB_ROOT,
    current_bundle: Path = DEFAULT_CURRENT_BUNDLE,
    historical_bundle: Path = DEFAULT_HISTORICAL_BUNDLE,
    historical_registry: Path = DEFAULT_HISTORICAL_REGISTRY,
    historical_provenance: Path | None = DEFAULT_HISTORICAL_PROVENANCE,
) -> dict[str, object]:
    """Build the fail-closed audit from bounded JSON and lstat-only evidence."""
    lab_root = Path(lab_root).expanduser().resolve()
    current_bundle = Path(current_bundle).expanduser()
    historical_bundle = Path(historical_bundle).expanduser()
    historical_registry = Path(historical_registry).expanduser()
    current_ref, current_payload = _json_ref(
        current_bundle, lab_root=lab_root, label="current bundle.json"
    )
    historical_ref, historical_payload = _json_ref(
        historical_bundle, lab_root=lab_root, label="historical bundle.json"
    )
    current_root = current_bundle.absolute().parent
    historical_root = historical_bundle.absolute().parent
    current, current_rows, _, current_blockers = _bundle_projection(
        current_payload,
        bundle_ref=current_ref,
        bundle_root=current_root,
        lab_root=lab_root,
        label="current_bundle",
    )
    historical, historical_rows, _, historical_blockers = _bundle_projection(
        historical_payload,
        bundle_ref=historical_ref,
        bundle_root=historical_root,
        lab_root=lab_root,
        label="historical_bundle",
    )
    registry_ref, registry_payload = _json_ref(
        historical_registry,
        lab_root=lab_root,
        label="historical checkpoint registry",
    )
    historical_registry_projection, registry_blockers = (
        _checkpoint_registry_projection(
            registry_payload,
            registry_ref=registry_ref,
            bundle_root=historical_root,
            bundle_rows=historical_rows,
            label="historical_checkpoint_registry",
        )
    )
    provenance_projection = None
    provenance_blockers: list[str] = []
    if historical_provenance is not None:
        provenance_ref, provenance_payload = _json_ref(
            Path(historical_provenance),
            lab_root=lab_root,
            label="historical checkpoint provenance",
        )
        provenance_projection, provenance_blockers = _provenance_projection(
            provenance_payload,
            provenance_ref=provenance_ref,
            registry=historical_registry_projection,
            label="historical_checkpoint_provenance",
        )

    blockers = list(
        dict.fromkeys(
            current_blockers
            + historical_blockers
            + registry_blockers
            + provenance_blockers
        )
    )
    if current.get("schema") != CURRENT_BUNDLE_SCHEMA:
        blockers.append(
            "current_bundle_schema_not_v2:"
            f"{current.get('schema')!r}:expected={CURRENT_BUNDLE_SCHEMA!r}"
        )
    if current.get("checkpoint_count") != 0:
        blockers.append("current_bundle_is_not_checkpoint_free_v2_baseline")
    else:
        blockers.append("current_checkpoint_count_zero")
    if current.get("model_reproduction_supported") is not False:
        blockers.append("current_model_reproduction_support_not_explicitly_false")
    if current.get("inventory", {}).get("checkpoint_artifact_paths") != []:
        blockers.append("current_bundle_contains_checkpoint_artifact_rows")
    current_checkpoint_path = current.get("reuse_contract", {}).get(
        "model_entrypoint_checkpoint_path"
    )
    if current_checkpoint_path and current_checkpoint_path not in current_rows:
        blockers.append(
            "current_model_entrypoint_has_no_trusted_registry_row:"
            f"{current_checkpoint_path}"
        )
    if historical.get("schema") == CURRENT_BUNDLE_SCHEMA:
        blockers.append("historical_bundle_unexpectedly_current_v2")
    else:
        blockers.append(
            "historical_bundle_schema_legacy_or_different:"
            f"{historical.get('schema')!r}"
        )
    if historical.get("checkpoint_count") in (None, 0):
        blockers.append("historical_checkpoint_bearing_bundle_missing")
    if (
        historical_registry_projection.get("declared_count")
        != historical.get("checkpoint_count")
    ):
        blockers.append("historical_bundle_registry_count_drift")
    current_dataset_ref = current.get("dataset", {}).get("ref", {})
    historical_dataset_ref = historical.get("dataset", {}).get("ref", {})
    if current_dataset_ref.get("sha256") != historical_dataset_ref.get(
        "sha256"
    ):
        blockers.append("dataset_source_raw_sha_mismatch_current_vs_historical")
    if current.get("dataset", {}).get("schema") != historical.get(
        "dataset", {}
    ).get("schema"):
        blockers.append("dataset_source_schema_mismatch_current_vs_historical")
    code_comparison = _code_comparison(current, historical)
    if code_comparison["different_sha_paths"]:
        blockers.append(
            "code_identity_sha_mismatch_common_paths:"
            f"{len(code_comparison['different_sha_paths'])}"
        )
    if historical.get("reuse_contract", {}).get(
        "absolute_reuse_source_count", 0
    ):
        blockers.append("historical_portable_package_has_absolute_reused_from_paths")
    if (
        provenance_projection is not None
        and provenance_projection.get("diagnostic_only") is True
    ):
        blockers.append("historical_checkpoint_provenance_is_diagnostic_only")
    if provenance_projection is not None:
        provenance_dataset = provenance_projection.get("dataset_binding", {})
        if (
            isinstance(provenance_dataset, Mapping)
            and provenance_dataset.get("sha256")
            != historical.get("dataset", {}).get("ref", {}).get("sha256")
        ):
            blockers.append(
                "historical_provenance_dataset_sha_mismatch_historical_bundle"
            )
        provenance_identity = provenance_projection.get(
            "training_identity", {}
        )
        registry_identity = next(
            (
                item
                for item in historical_registry_projection.get("identities", [])
                if isinstance(item, Mapping)
                and item.get("sha256_claim")
                == provenance_projection.get("checkpoint", {}).get(
                    "sha256_claim"
                )
            ),
            None,
        )
        if isinstance(registry_identity, Mapping):
            for field in ("model_kind", "seed", "update"):
                if provenance_identity.get(field) != registry_identity.get(
                    field
                ):
                    blockers.append(
                        "historical_provenance_registry_identity_drift:"
                        f"{field}"
                    )
    blockers.extend(
        [
            "current_trusted_checkpoint_binding_missing",
            "checkpoint_content_hash_not_verified_by_this_boundary",
            "independent_reproduction_requires_fresh_current_v2_binding_and_distinct_host_receipt",
        ]
    )
    blockers = sorted(set(blockers))

    current_models: list[dict[str, object]] = []
    historical_models = historical_registry_projection.get("identities", [])
    if not isinstance(historical_models, list):
        historical_models = []
    source_identity = {
        "current": {
            "dataset_path": current_dataset_ref.get("path"),
            "dataset_sha256": current_dataset_ref.get("sha256"),
            "dataset_schema": current.get("dataset", {}).get("schema"),
            "case_count": current.get("dataset", {}).get("case_count"),
            "bundle_schema": current.get("schema"),
        },
        "historical": {
            "dataset_path": historical_dataset_ref.get("path"),
            "dataset_sha256": historical_dataset_ref.get("sha256"),
            "dataset_schema": historical.get("dataset", {}).get("schema"),
            "case_count": historical.get("dataset", {}).get("case_count"),
            "bundle_schema": historical.get("schema"),
        },
        "dataset_relative_path_equal": current_dataset_ref.get("path")
        == historical_dataset_ref.get("path"),
        "dataset_raw_sha_equal": current_dataset_ref.get("sha256")
        == historical_dataset_ref.get("sha256"),
        "dataset_schema_equal": current.get("dataset", {}).get("schema")
        == historical.get("dataset", {}).get("schema"),
    }
    hash_identity = {
        "current_bundle_json_sha256": current.get("bundle_ref", {}).get("sha256"),
        "historical_bundle_json_sha256": historical.get("bundle_ref", {}).get(
            "sha256"
        ),
        "bundle_json_sha_equal": current.get("bundle_ref", {}).get("sha256")
        == historical.get("bundle_ref", {}).get("sha256"),
        "current_dataset_json_sha256": current_dataset_ref.get("sha256"),
        "historical_dataset_json_sha256": historical_dataset_ref.get("sha256"),
        "historical_checkpoint_registry_json_sha256": registry_ref.get(
            "sha256"
        ),
        "historical_checkpoint_sha_claims_only": True,
        "checkpoint_or_non_json_content_hashes_verified": False,
    }
    path_identity = {
        "current_all_package_paths_relative": current.get(
            "reuse_contract", {}
        ).get("all_package_paths_relative"),
        "historical_all_package_paths_relative": historical.get(
            "reuse_contract", {}
        ).get("all_package_paths_relative"),
        "current_absolute_reuse_source_count": current.get(
            "reuse_contract", {}
        ).get("absolute_reuse_source_count"),
        "historical_absolute_reuse_source_count": historical.get(
            "reuse_contract", {}
        ).get("absolute_reuse_source_count"),
        "current_model_entrypoint_checkpoint_path": current.get(
            "reuse_contract", {}
        ).get("model_entrypoint_checkpoint_path"),
        "current_model_entrypoint_registered": (
            current.get("reuse_contract", {}).get(
                "model_entrypoint_checkpoint_path"
            )
            in current_rows
            if current.get("reuse_contract", {}).get(
                "model_entrypoint_checkpoint_path"
            )
            else False
        ),
        "historical_checkpoint_registry_paths": [
            item.get("path")
            for item in historical_models
            if isinstance(item, Mapping)
        ],
        "lstat_only": True,
    }
    model_identity = {
        "current_checkpoint_count": current.get("checkpoint_count"),
        "current_models": current_models,
        "historical_checkpoint_count": historical.get("checkpoint_count"),
        "historical_models": historical_models,
        "historical_provenance": provenance_projection,
        "current_identity_bound": False,
        "historical_identity_is_not_current_trusted_binding": True,
    }
    portable_package_contract = {
        "current": {
            "schema": current.get("schema"),
            "v2_contract": current.get("reuse_contract", {}).get("is_current_v2"),
            "portable_paths": current.get("reuse_contract", {}).get(
                "portable_path_contract"
            ),
            "model_reproduction_supported": current.get(
                "model_reproduction_supported"
            ),
            "checkpoint_count": current.get("checkpoint_count"),
        },
        "historical": {
            "schema": historical.get("schema"),
            "v2_contract": historical.get("reuse_contract", {}).get(
                "is_current_v2"
            ),
            "portable_paths": historical.get("reuse_contract", {}).get(
                "portable_path_contract"
            ),
            "model_reproduction_supported": historical.get(
                "model_reproduction_supported"
            ),
            "checkpoint_count": historical.get("checkpoint_count"),
        },
        "current_ready_for_trusted_model_package": False,
        "reason": (
            "current v2 has no checkpoint registry/artifact binding and "
            "historical package is not an authority"
        ),
    }
    trusted_checkpoint_binding = {
        "ready": False,
        "status": "missing",
        "required_next_step": (
            "bind a current-v2 checkpoint registry and independently attest "
            "each checkpoint before any model reproduction"
        ),
        "required_evidence": [
            "current v2 bundle.json and dataset.json source/code/environment identities",
            "current v2 checkpoints.json with model_kind, seed, update, normalized relative path and SHA-256 claim",
            "bundle artifact row and lstat/byte agreement for every checkpoint",
            "trusted training receipt linking checkpoint to model/config/seed/update and formal-vs-diagnostic status",
            "content-hash attestation performed by an authorized producer outside this metadata-only auditor",
            "portable package contract with no absolute source/reuse paths",
            "fresh independent reproduction receipt from a distinct host using the newly bound current package",
        ],
        "historical_checkpoint_rows_cannot_satisfy_current_binding": True,
        "checkpoint_count_does_not_imply_ready": True,
    }
    read_boundary = {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "json_inputs_opened": 6 if provenance_projection is not None else 5,
        "non_json_files_opened": False,
        "checkpoint_opened": False,
        "hdf5_opened": False,
        "npz_opened": False,
        "source_or_model_bytes_opened": False,
        "non_json_hashes_computed": False,
        "assets_lstat_only": True,
        "training_started": False,
        "rollout_started": False,
        "gpu_started": False,
        "solver_started": False,
        "worker_started": False,
        "queue_started": False,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": "blocked_missing_trusted_checkpoint_binding",
        "passed": False,
        "audit_scope": (
            "current A8 reader_bundle.v2 checkpoint-free index versus "
            "historical checkpoint-bearing bundle/registry"
        ),
        "current_bundle": current,
        "historical_bundle": historical,
        "historical_checkpoint_registry": historical_registry_projection,
        "comparisons": {
            "source_identity": source_identity,
            "hash_identity": hash_identity,
            "path_identity": path_identity,
            "model_identity": model_identity,
            "portable_package_contract": portable_package_contract,
            "code_identity": code_comparison,
        },
        "trusted_checkpoint_binding": trusted_checkpoint_binding,
        "blockers": blockers,
        "claims": dict(FALSE_CLAIMS),
        "mutations": dict(ZERO_MUTATIONS),
        "read_boundary": read_boundary,
        "interpretation": (
            "Metadata and lstat reconciliation only; historical checkpoint "
            "presence and diagnostic receipts are not current independent "
            "reproduction or T1/T2 evidence."
        ),
        "next_action": (
            "Obtain trusted current-v2 checkpoint binding, then run an "
            "independently attested reproduction on a distinct host; do not "
            "promote this audit itself."
        ),
    }
    return report


def validate_report(report: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("report.schema mismatch")
    if report.get("status") != "blocked_missing_trusted_checkpoint_binding":
        errors.append("report.status must remain blocked")
    if report.get("passed") is not False:
        errors.append("report.passed must be false")
    if report.get("claims") != FALSE_CLAIMS:
        errors.append("report.claims drift")
    if report.get("mutations") != ZERO_MUTATIONS:
        errors.append("report.mutations drift")
    boundary = report.get("read_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("report.read_boundary missing")
    else:
        for field in (
            "non_json_files_opened",
            "checkpoint_opened",
            "hdf5_opened",
            "npz_opened",
            "source_or_model_bytes_opened",
            "non_json_hashes_computed",
            "training_started",
            "rollout_started",
            "gpu_started",
            "solver_started",
            "worker_started",
            "queue_started",
        ):
            if boundary.get(field) is not False:
                errors.append(f"read_boundary.{field} must be false")
        if (
            boundary.get("bounded_json_only") is not True
            or boundary.get("assets_lstat_only") is not True
        ):
            errors.append("read_boundary policy flags drift")
    current = report.get("current_bundle")
    if not isinstance(current, Mapping):
        errors.append("current_bundle missing")
    else:
        if current.get("schema") != CURRENT_BUNDLE_SCHEMA:
            errors.append("current_bundle.schema is not v2")
        if current.get("checkpoint_count") != 0:
            errors.append("current_bundle.checkpoint_count is not zero")
    binding = report.get("trusted_checkpoint_binding")
    if not isinstance(binding, Mapping) or binding.get("ready") is not False:
        errors.append("trusted checkpoint binding must remain missing")
    blockers = report.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        errors.append("report.blockers must be non-empty")
    return errors


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def render_zh_cn(report: Mapping[str, object]) -> str:
    current = report.get("current_bundle", {})
    historical = report.get("historical_bundle", {})
    comparisons = report.get("comparisons", {})
    source = (
        comparisons.get("source_identity", {})
        if isinstance(comparisons, Mapping)
        else {}
    )
    model = (
        comparisons.get("model_identity", {})
        if isinstance(comparisons, Mapping)
        else {}
    )
    blockers = report.get("blockers", [])
    lines = [
        "# A8 checkpoint/model reproduction readiness bounded audit V1",
        "",
        f"- 状态：{report.get('status')}",
        "- 结论：passed=false；本回执不是 independent reproduction、T1/T2、formal training 或 credit 证据。",
        "",
        "## 比较对象",
        "",
        f"- 当前包：{current.get('schema')}，checkpoint_count={current.get('checkpoint_count')}，model support={current.get('model_reproduction_supported')}。",
        f"- 历史包：{historical.get('schema')}，checkpoint_count={historical.get('checkpoint_count')}；历史 registry 身份不会转移成当前绑定。",
        f"- dataset raw SHA 相同：{source.get('dataset_raw_sha_equal')}；相对路径相同：{source.get('dataset_relative_path_equal')}。",
        f"- 当前模型身份已绑定：{model.get('current_identity_bound')}。",
        "",
        "## 关键阻塞",
        "",
    ]
    for item in blockers:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 下一步需要的 trusted checkpoint binding",
            "",
            "1. 为当前 v2 bundle 提供 bounded checkpoints.json，逐项绑定 model_kind、seed、update、规范化相对路径与 SHA-256 claim。",
            "2. 将 checkpoint registry 行、bundle artifact row、lstat/bytes、训练 receipt、model/config identity 和 formal/diagnostic 状态由可信生产者闭合；本审计不验证 checkpoint 内容。",
            "3. 清除 portable package 中的绝对 source/reuse 路径，并在 distinct host 上生成新的 independent reproduction receipt。",
            "",
            "## 读取边界",
            "",
            "仅读取有界 strict JSON；所有 checkpoint、HDF5、NPZ、source/model bytes 均未打开或重哈希，只做 lstat。未训练、rollout、占用 GPU、启动 solver/worker/queue，也未修改 registry、ledger、denominator、gate 或 completion。",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit", help="build the fail-closed bounded audit"
    )
    audit.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    audit.add_argument(
        "--current-bundle", type=Path, default=DEFAULT_CURRENT_BUNDLE
    )
    audit.add_argument(
        "--historical-bundle", type=Path, default=DEFAULT_HISTORICAL_BUNDLE
    )
    audit.add_argument(
        "--historical-registry",
        type=Path,
        default=DEFAULT_HISTORICAL_REGISTRY,
    )
    audit.add_argument(
        "--historical-provenance",
        type=Path,
        default=DEFAULT_HISTORICAL_PROVENANCE,
    )
    audit.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    audit.add_argument("--zh-report", type=Path, default=DEFAULT_ZH_REPORT)
    validate = subparsers.add_parser(
        "validate", help="validate one generated audit"
    )
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "audit":
        report = build_audit(
            lab_root=args.lab_root,
            current_bundle=args.current_bundle,
            historical_bundle=args.historical_bundle,
            historical_registry=args.historical_registry,
            historical_provenance=args.historical_provenance,
        )
        errors = validate_report(report)
        if errors:
            raise AuditContractError(
                "generated audit failed self-validation: " + "; ".join(errors)
            )
        _atomic_json(args.report, report)
        args.zh_report.parent.mkdir(parents=True, exist_ok=True)
        args.zh_report.write_text(
            render_zh_cn(report), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "blocker_count": len(report["blockers"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    _, report = _json_ref(
        args.report, lab_root=args.lab_root, label="audit report"
    )
    errors = validate_report(report)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"valid": True, "status": report["status"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
