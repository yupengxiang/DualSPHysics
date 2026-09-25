#!/usr/bin/env python3
"""Audit metadata for the nine formal Core learning jobs without launching.

The current Mapping/JSON-path interface has no source-bound trusted admission
capability, so it is diagnostic-only and always holds formal job emission,
even when its metadata, code bundle, environment, and resource profile appear
complete.  This module does not open trajectory HDF5 files, submit jobs,
update a ledger, or turn a qualification/canary row into a production case.
Formal specifications require a future verified admission interface.

The training command in each emitted specification is the existing
``scripts/core_learning.py train`` command.  In particular, this module does
not provide a second training implementation or a second checkpoint selector.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json as _shared_read_bounded_raw_json,
    strict_json_object as _shared_strict_json_object,
)


PLANNER_SCHEMA = "core.formal_training_plan.v1"
JOB_SCHEMA = "core.formal_training_job.v1"
MODELS = ("mlp", "graph_raw", "graph_residual")
SEEDS = (17, 29, 43)
UPDATES = 32000
MILESTONES = (8000, 16000, 24000, 32000)
CENTERS = 256
HIDDEN = 64
LEARNING_RATE = 1e-3
NORMALIZATION_TRANSITIONS = 256
VALIDATION_TRANSITIONS = 4
VALIDATION_CENTERS = 256
CHECKPOINT_EVERY = 8000
LOG_EVERY = 1000
VALIDATION_EVERY = 1000
MIN_FAMILIES = 3
CASES_PER_FAMILY = 32
VALIDATION_PER_FAMILY = 4
MAX_PLANNER_JSON_BYTES = 67_108_864

# The source snapshot warning that motivated this module is easy to re-create
# when a job copies a previous profile's argv.  These are the files whose
# hashes form the fresh source closure for every formal job.
REQUIRED_CODE_FILES = (
    "scripts/core_learning.py",
    "scripts/core_contract.py",
    "scripts/core_dataset.py",
    "scripts/core_strict_json.py",
    "scripts/core_models.py",
    "scripts/core_cfd_dataset.py",
    "scripts/core_evaluation.py",
    "scripts/core_physics.py",
    "scripts/core_formal_planner.py",
)

_QUALIFICATION_KEYS = (
    "qualification_only", "qualification_case", "is_qualification",
    "qualification", "qualification_claim",
)
_T1_KEYS = (
    "T1_numerical", "t1_numerical", "t1_registered", "t1_qualified",
    "formal_t1", "T1", "T1_pass", "t1_pass", "registered_T1",
)
_AUDIT_PASS_KEYS = (
    "hard_integrity_pass", "hard_integrity_passed", "hard_audit_pass",
    "hard_audit_passed",
)
_AUDIT_REF_KEYS = ("audit", "audit_ref", "audit_path", "source_audit")
_ROW_COLLECTION_KEYS = ("cases", "production_cases", "records", "rows", "audits")


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


def _json_hash(value: Any) -> str:
    return sha256_bytes(canonical(value).encode())


def _read_bounded_raw_json(path: Path) -> bytes:
    """Read one stable regular planner JSON file without following symlinks."""
    return _shared_read_bounded_raw_json(
        path, max_bytes=MAX_PLANNER_JSON_BYTES, label="planner JSON input")


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    """Parse path-backed planner JSON without duplicate or non-finite values."""
    return _shared_strict_json_object(
        raw, label=label, max_bytes=MAX_PLANNER_JSON_BYTES)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    return _strict_json_object(_read_bounded_raw_json(path), label=label)


def _resolve_path(value: str | Path, *, base: Path | None = None,
                  data_root: Path | None = None,
                  no_follow_leaf: bool = False) -> Path:
    """Resolve a campaign-relative path without permitting ambiguity."""
    candidate = Path(value).expanduser()
    def normalize(path: Path) -> Path:
        if not no_follow_leaf:
            return path.resolve()
        return absolute_path_without_following_leaf(path)

    if candidate.is_absolute():
        return normalize(candidate)
    options = []
    if base is not None:
        options.append(normalize(base / candidate))
    if data_root is not None:
        options.append(normalize(data_root / candidate))
    options.append(normalize(Path.cwd() / candidate))
    options.append(normalize(Path(__file__).resolve().parents[1] / candidate))
    for option in options:
        if option.exists() or (no_follow_leaf and option.is_symlink()):
            return option
    # The first candidate gives an actionable path for a missing input.
    return options[0] if options else candidate.resolve()


def _load_json(source: Any, *, data_root: Path | None = None
               ) -> tuple[Any, Path | None, str | None]:
    if isinstance(source, (str, Path)):
        path = _resolve_path(source, data_root=data_root, no_follow_leaf=True)
        raw = _read_bounded_raw_json(path)
        return (_strict_json_object(raw, label=f"planner input {path}"),
                path, sha256_bytes(raw))
    if isinstance(source, Mapping):
        return dict(source), None, None
    raise TypeError("planner input must be a JSON path or mapping")


def _ref(path: Path | None, *, supplied: str | None = None,
         payload: Any | None = None,
         raw_sha256: str | None = None) -> dict[str, Any]:
    if path is not None:
        if not isinstance(raw_sha256, str) or len(raw_sha256) != 64:
            raise ValueError("path-backed planner references require the parsed raw-byte SHA-256")
        return {"path": str(path), "sha256": raw_sha256}
    return {"path": supplied or "<in-memory>", "sha256": _json_hash(payload)}


def _iter_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract rows from the portable manifest forms used by Core adapters."""
    for key in _ROW_COLLECTION_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    families = payload.get("families")
    if isinstance(families, Mapping):
        result = []
        for family, block in families.items():
            family_rows = block if isinstance(block, list) else (
                block.get("cases", []) if isinstance(block, Mapping) else [])
            for row in family_rows:
                if isinstance(row, Mapping):
                    item = dict(row)
                    item.setdefault("family", str(family))
                    result.append(item)
        if result:
            return result
    nested = payload.get("manifest") or payload.get("dataset")
    if isinstance(nested, Mapping):
        return _iter_rows(nested)
    raise ValueError("portable manifest has no cases/records/rows collection")


def _nested_values(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for key in ("qualification", "audit", "result", "record", "evidence"):
            child = value.get(key)
            if isinstance(child, Mapping):
                yield from _nested_values(child)


def _extract_evidence_rows(payload: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Return case records and global/family records from an evidence JSON."""
    case_rows: list[Mapping[str, Any]] = []
    global_rows: list[Mapping[str, Any]] = [payload]
    for key in _ROW_COLLECTION_KEYS:
        rows = payload.get(key)
        if isinstance(rows, list):
            case_rows.extend(row for row in rows if isinstance(row, Mapping))
    families = payload.get("families")
    if isinstance(families, Mapping):
        for family, block in families.items():
            if isinstance(block, Mapping):
                row = dict(block)
                row.setdefault("family", family)
                global_rows.append(row)
                nested_rows = block.get("cases") or block.get("records") or []
                case_rows.extend(item for item in nested_rows if isinstance(item, Mapping))
    if payload.get("case_id"):
        case_rows.append(payload)
    return case_rows, global_rows


def _bool_marker(values: Iterable[Mapping[str, Any]], keys: Sequence[str]) -> bool | None:
    seen = False
    saw_true = False
    saw_false = False
    for value in values:
        for key in keys:
            if key in value and value[key] is not None:
                seen = True
                marker = value[key]
                if isinstance(marker, str):
                    normalized = marker.strip().lower()
                    # Do not turn an explicit ``fail`` status into a pass just
                    # because nonempty strings are truthy in Python.  The
                    # diagnostic F3 audit uses ``pass_diagnostic`` and still
                    # provides a valid structural audit; formal release is
                    # gated separately by the manifest/qualification record.
                    if normalized in {"false", "fail", "failed", "error", "invalid",
                                      "rejected", "not_passed", "not_assessed",
                                      "candidate_unqualified", "blocked", "pending"}:
                        saw_false = True
                        continue
                    if normalized in {"true", "pass", "passed", "ok", "complete",
                                      "succeeded", "pass_diagnostic"}:
                        saw_true = True
                    continue
                if bool(marker):
                    saw_true = True
                else:
                    saw_false = True
                # Keep scanning so an explicit false in another nested field
                # cannot be hidden by a preceding positive marker.
    # An explicit negative anywhere in one evidence set is authoritative.  A
    # positive marker from another scope or nested block must not mask it.
    if saw_false:
        return False
    return True if saw_true else (False if seen else None)


def _family_of(row: Mapping[str, Any]) -> str | None:
    for key in ("t1_family", "family", "family_id", "family_code"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for block_key in ("qualification", "audit", "provenance"):
        block = row.get(block_key)
        if isinstance(block, Mapping):
            value = _family_of(block)
            if value:
                return value
    return None


def _case_id(row: Mapping[str, Any]) -> str | None:
    for key in ("case_id", "id", "case"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _physical_id(row: Mapping[str, Any], case_id: str | None) -> str | None:
    value = row.get("physical_case_id", row.get("physical_id"))
    return str(value) if value is not None else None


def _lineage_id(row: Mapping[str, Any], physical_id: str | None) -> str | None:
    value = row.get("lineage_group_id", row.get("lineage_id"))
    return str(value) if value is not None else None


def _scope_of(row: Mapping[str, Any]) -> str | None:
    """Return the registered qualification scope without guessing one."""
    for key in ("scope_id", "scope", "qualification_scope_id", "scopeId"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("qualification", "provenance", "source_evidence", "known_inputs",
                "known_inputs_ref", "numerics", "recipe"):
        block = row.get(key)
        if isinstance(block, Mapping):
            value = _scope_of(block)
            if value:
                return value
    return None


def _recipe_of(row: Mapping[str, Any]) -> str | None:
    """Return the declared numerical recipe identity without fabricating it."""
    for key in ("recipe_id", "recipe", "qualification_recipe_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = _recipe_of(value)
            if nested:
                return nested
    for key in ("qualification", "provenance", "source_evidence", "known_inputs",
                "known_inputs_ref", "numerics"):
        block = row.get(key)
        if isinstance(block, Mapping):
            value = _recipe_of(block)
            if value:
                return value
    # Compact F3 records put the recipe in scope_id and the same identity is
    # used by its qualification report.  This is an explicit field fallback,
    # not a case-id fabrication.
    return _scope_of(row)


def _binding_matches(case_row: Mapping[str, Any], evidence_row: Mapping[str, Any]) -> bool:
    """Require exact scope and recipe agreement for qualification evidence."""
    case_scope, case_recipe = _scope_of(case_row), _recipe_of(case_row)
    evidence_scope, evidence_recipe = _scope_of(evidence_row), _recipe_of(evidence_row)
    if not case_scope or not case_recipe or not evidence_scope or not evidence_recipe:
        return False
    return case_scope == evidence_scope and case_recipe == evidence_recipe


def _split_of(row: Mapping[str, Any]) -> str:
    value = row.get("split", row.get("role", ""))
    return str(value).lower() if value is not None else ""


def _qualification_marker(values: Iterable[Mapping[str, Any]]) -> bool:
    for value in values:
        if bool(value.get("qualification_only")) or bool(value.get("qualification_case")):
            return True
        if str(value.get("split", "")).lower() in {"qualification", "qualification_only"}:
            return True
        if str(value.get("stage", "")).lower() in {
            "qualification", "qualification_only", "canary", "repair_canary",
            "calibration", "diagnostic", "repair", "qualification_canary",
        }:
            return True
        if str(value.get("evaluation_role", "")).lower() in {"qualification", "canary"}:
            return True
        claim = value.get("qualification_claim")
        # F4 production audits carry an explanatory marker such as
        # ``none; one case cannot establish range/temporal/reference
        # qualification``.  That sentence explicitly says that no
        # qualification is claimed; treating every non-empty string as a
        # claim would remove all 32 production rows from the denominator.
        if isinstance(claim, str):
            normalized_claim = claim.strip().lower()
            if normalized_claim in {"", "none"} or normalized_claim.startswith(("none;", "none:")):
                continue
        if claim not in (None, "", "none", False):
            return True
    return False


def _audit_reference(row: Mapping[str, Any]) -> Any:
    for key in _AUDIT_REF_KEYS:
        if key in row:
            return row[key]
    for block_key in ("provenance", "source_evidence", "evidence"):
        block = row.get(block_key)
        if isinstance(block, Mapping):
            for key in _AUDIT_REF_KEYS:
                if key in block:
                    return block[key]
    return None


def _load_referenced_audit(reference: Any, *, base: Path | None,
                           data_root: Path | None
                           ) -> tuple[Mapping[str, Any] | None, Path | None, str | None, str | None]:
    if isinstance(reference, Mapping):
        path_value = reference.get("path")
        if path_value is None:
            return reference, None, None, None
        path = _resolve_path(path_value, base=base, data_root=data_root,
                             no_follow_leaf=True)
        declared = reference.get("sha256")
        if not isinstance(declared, str) or len(declared) != 64:
            return None, path, f"audit reference has no declared SHA-256: {path}", None
        try:
            raw = _read_bounded_raw_json(path)
        except (OSError, ValueError) as error:
            return None, path, f"invalid audit JSON: {path}: {error}", None
        observed = sha256_bytes(raw)
        if observed != declared:
            return None, path, f"audit SHA-256 mismatch: {path}", observed
        try:
            payload = _strict_json_object(raw, label=f"audit JSON {path}")
        except (OSError, ValueError) as error:
            return None, path, f"invalid audit JSON: {path}: {error}", observed
        if not isinstance(payload, Mapping):
            return None, path, f"audit JSON is not an object: {path}", observed
        return payload, path, None, observed
    if isinstance(reference, (str, Path)):
        path = _resolve_path(reference, base=base, data_root=data_root,
                             no_follow_leaf=True)
        return None, path, f"audit path has no declared SHA-256: {path}", None
    return None, None, "unsupported audit reference", None


def _profile_resources(profile: Mapping[str, Any], model: str) -> dict[str, Any]:
    """Normalize the measured profile/resource-plan shapes in this campaign."""
    resources: dict[str, Any] = {}
    block = profile.get("resources")
    if isinstance(block, Mapping):
        model_block = block.get(model) or block.get("model")
        if isinstance(model_block, Mapping):
            resources.update(model_block)
        else:
            resources.update(block)
    declarations = profile.get("gpu_peak_mib_declarations")
    if isinstance(declarations, Mapping) and model in declarations:
        resources.setdefault("gpu_peak_mib", declarations[model])
    if "ram_mib_per_worker" in profile:
        resources.setdefault("ram_mib", profile["ram_mib_per_worker"])
    if "cpu_cores_per_worker" in profile:
        resources.setdefault("cpu_cores", profile["cpu_cores_per_worker"])
    if not resources and isinstance(profile.get("resource"), Mapping):
        resources.update(profile["resource"])
    # A measured configuration row can be selected by model name or job id.
    configurations = profile.get("configurations")
    if isinstance(configurations, list):
        candidates = [item for item in configurations if isinstance(item, Mapping)
                      and model in str(item.get("model", item.get("job_id", ""))).lower()]
        if candidates:
            selected = candidates[0]
            for source, target in (("gpu_peak_mib_measured", "gpu_peak_mib"),
                                   ("future_gpu_peak_mib_declaration", "gpu_peak_mib"),
                                   ("ram_peak_mib", "ram_mib")):
                if source in selected:
                    resources.setdefault(target, selected[source])
    required = {"gpu_peak_mib", "ram_mib"}
    missing = sorted(key for key in required if key not in resources)
    if missing:
        raise ValueError(f"resource profile has no {', '.join(missing)} for {model}")
    resources.setdefault("cpu_cores", 4)
    resources.setdefault("io_weight", 0.1)
    for key in ("gpu_peak_mib", "ram_mib", "cpu_cores"):
        value = resources.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"resource profile has invalid positive {key} for {model}")
    io_weight = resources.get("io_weight")
    if (isinstance(io_weight, bool) or not isinstance(io_weight, (int, float))
            or not math.isfinite(float(io_weight)) or float(io_weight) < 0):
        raise ValueError(f"resource profile has invalid nonnegative io_weight for {model}")
    return resources


def _environment_binding(environment: Any, *, data_root: Path | None,
                          python_executable: str | Path | None
                          ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if environment is None:
        return None, None
    if isinstance(environment, (str, Path)):
        payload, path, raw_sha256 = _load_json(environment, data_root=data_root)
    else:
        payload, path, raw_sha256 = environment, None, None
    if isinstance(payload, Mapping):
        result = dict(payload)
        if path is not None:
            source_ref = _ref(path, raw_sha256=raw_sha256)
        else:
            source_ref = _ref(None, payload=payload)
        result["source"] = source_ref
    else:
        source_ref = _ref(None, payload=payload)
        result = {"id": str(payload), "source": source_ref}
    executable = python_executable or result.get("python_executable") or result.get("python")
    if executable is None:
        return None, None
    resolved = _resolve_path(executable, data_root=data_root)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        result["python_executable"] = str(resolved)
        result["python_exists"] = False
    else:
        result["python_executable"] = str(resolved)
        result["python_exists"] = True
    result.setdefault("id", result.get("environment_id", "unidentified-environment"))
    return result, source_ref


def _code_bundle(code_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files, missing = [], []
    for relative in REQUIRED_CODE_FILES:
        path = (code_root / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        files.append({"path": str(path), "relative_path": relative,
                      "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return files, missing


def _snapshot_check(snapshot: Any, *, code_root: Path, required: Sequence[str]) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate an explicitly supplied source snapshot, if one is requested."""
    if snapshot is None:
        return None, []
    errors: list[str] = []
    if isinstance(snapshot, (str, Path)):
        path = _resolve_path(snapshot, base=code_root, data_root=code_root,
                             no_follow_leaf=True)
        if path.is_dir():
            for relative in required:
                snapshot_file = (path / relative).resolve()
                current_file = (code_root / relative).resolve()
                if not snapshot_file.is_file():
                    errors.append(f"source snapshot missing {relative}")
                    continue
                if not current_file.is_file():
                    errors.append(f"source snapshot current file missing {relative}")
                    continue
                if sha256_file(snapshot_file).lower() != sha256_file(current_file).lower():
                    errors.append(f"source snapshot hash mismatch for {relative}")
                if snapshot_file.stat().st_size != current_file.stat().st_size:
                    errors.append(f"source snapshot byte count mismatch for {relative}")
            return {"path": str(path), "sha256": None,
                    "required_files": sorted(required), "verified": not errors}, errors
        if path.is_file():
            try:
                raw = _read_bounded_raw_json(path)
                payload = _strict_json_object(raw, label=f"source snapshot {path}")
            except (OSError, ValueError) as error:
                return {"path": str(path), "sha256": None}, [f"invalid source snapshot: {error}"]
            snapshot = payload
            snapshot_ref = {"path": str(path), "sha256": sha256_bytes(raw)}
        else:
            return None, [f"source snapshot does not exist: {path}"]
    else:
        snapshot_ref = {"path": "<in-memory>", "sha256": _json_hash(snapshot)}
    files = snapshot.get("files", snapshot.get("input_files", snapshot)) if isinstance(snapshot, Mapping) else {}
    rows: dict[str, dict[str, Any]] = {}
    if isinstance(files, Mapping):
        for key, value in files.items():
            if isinstance(value, Mapping):
                name = value.get("relative_path", value.get("path", key))
                row = dict(value)
            else:
                name = key
                row = {"sha256": value}
            rows[str(name)] = row
    elif isinstance(files, list):
        for item in files:
            if isinstance(item, Mapping):
                name = item.get("relative_path", item.get("path"))
                if name is not None:
                    rows[str(name)] = dict(item)
            else:
                rows[str(item)] = {}

    required_set = set(required)
    for relative in required:
        row = rows.get(relative)
        if row is None:
            errors.append(f"source snapshot missing {relative}")
            continue
        current = (code_root / relative).resolve()
        if not current.is_file():
            errors.append(f"source snapshot current file missing {relative}")
            continue
        declared_sha = row.get("sha256")
        if not isinstance(declared_sha, str) or len(declared_sha) != 64:
            errors.append(f"source snapshot missing SHA-256 for {relative}")
        elif declared_sha.lower() != sha256_file(current).lower():
            errors.append(f"source snapshot hash mismatch for {relative}")
        declared_bytes = row.get("bytes")
        if declared_bytes is not None and (
                isinstance(declared_bytes, bool)
                or not isinstance(declared_bytes, int)
                or declared_bytes != current.stat().st_size):
            errors.append(f"source snapshot byte count mismatch for {relative}")
    extras = sorted(set(rows) - required_set)
    errors.extend(f"source snapshot has unexpected file {relative}" for relative in extras)
    return {**snapshot_ref, "required_files": sorted(required), "verified": not errors}, errors


def _family_global_markers(family: str, global_rows: Iterable[Mapping[str, Any]],
                          *, case_row: Mapping[str, Any] | None = None) -> list[Mapping[str, Any]]:
    result = []
    for row in global_rows:
        row_family = _family_of(row)
        # A global record without a family label is intentionally not
        # broadcast across T1 families.  The caller must provide an explicit
        # per-family qualification record; otherwise one scope could silently
        # qualify unrelated families.
        if row_family is None or row_family != family:
            continue
        if case_row is None or _binding_matches(case_row, row):
            result.append(row)
        # Qualification reports often put T1 status below a named
        # ``qualification_axes``/``checks`` block.  Preserve the family label
        # while exposing those markers to the same strict boolean parser.
        for key in ("qualification_axes", "qualification", "checks", "gate"):
            block = row.get(key)
            if isinstance(block, Mapping):
                nested = dict(block)
                nested.setdefault("family", row_family or family)
                if ((row_family is None or row_family == family)
                        and (case_row is None or _binding_matches(case_row, nested))):
                    result.append(nested)
    return result


def inspect_inputs(manifest: Any, *, evidence: Sequence[Any] | Any | None = None,
                   data_root: str | Path | None = None) -> dict[str, Any]:
    """Audit metadata diagnostically; it cannot authorize formal jobs.

    The current Mapping/JSON-path inputs are not accompanied by a verified
    source-bound admission capability.  Until that capability exists, keep a
    permanent hold even when all descriptive metadata claims a pass.
    """
    root = Path(data_root).expanduser().resolve() if data_root is not None else None
    payload, manifest_path, manifest_raw_sha256 = _load_json(manifest, data_root=root)
    if not isinstance(payload, Mapping):
        raise ValueError("formal manifest must be a JSON object")
    hold_reasons: list[str] = [
        "trusted formal admission capability is unavailable; Mapping/path metadata is diagnostic-only"
    ]
    rows = _iter_rows(payload)
    evidence_sources = [] if evidence is None else (list(evidence) if isinstance(evidence, (list, tuple)) else [evidence])
    evidence_case_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    evidence_global_rows: list[Mapping[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    for source in evidence_sources:
        evidence_payload, evidence_path, evidence_raw_sha256 = _load_json(source, data_root=root)
        if not isinstance(evidence_payload, Mapping):
            raise ValueError("qualification evidence must be a JSON object")
        case_items, global_items = _extract_evidence_rows(evidence_payload)
        evidence_global_rows.extend(global_items)
        for item in case_items:
            case_id = _case_id(item)
            if case_id:
                evidence_case_rows[case_id].append(item)
        evidence_refs.append(_ref(
            evidence_path,
            supplied="<in-memory-evidence>" if evidence_path is None else None,
            payload=evidence_payload, raw_sha256=evidence_raw_sha256))

    # Attach inline or referenced per-case audits.  Referenced audit files are
    # hashed as metadata inputs; trajectories themselves are intentionally not
    # opened or re-hashed by this planner.
    audit_refs: dict[str, dict[str, Any]] = {}
    audit_hash_errors: list[str] = []
    audit_payloads: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        case_id = _case_id(row)
        if not case_id:
            continue
        reference = _audit_reference(row)
        if isinstance(reference, Mapping) and not reference.get("path"):
            audit_payloads[case_id].append(reference)
        elif isinstance(reference, Mapping) or isinstance(reference, (str, Path)):
            audit_payload, audit_path, audit_error, audit_raw_sha256 = _load_referenced_audit(
                reference, base=manifest_path.parent if manifest_path else None,
                data_root=root)
            if audit_payload is not None:
                audit_payloads[case_id].append(audit_payload)
            if audit_error is not None:
                audit_hash_errors.append(f"{case_id}: {audit_error}")
            if audit_path is not None and audit_raw_sha256 is not None:
                audit_refs[str(audit_path)] = _ref(
                    audit_path, raw_sha256=audit_raw_sha256)

    all_case_ids = [_case_id(row) for row in rows]
    duplicate_case_ids = sorted(case_id for case_id, count in Counter(all_case_ids).items()
                                 if case_id is not None and count > 1)
    if duplicate_case_ids:
        hold_reasons.append("duplicate case_id: " + ", ".join(duplicate_case_ids))

    normalized = []
    for row in rows:
        case_id = _case_id(row)
        physical_id = _physical_id(row, case_id)
        lineage_id = _lineage_id(row, physical_id)
        family = _family_of(row)
        split = _split_of(row)
        scope_id = _scope_of(row)
        recipe_id = _recipe_of(row)
        case_evidence = list(evidence_case_rows.get(case_id or "", ()))
        case_evidence.extend(audit_payloads.get(case_id or "", ()))
        # Direct status fields are accepted as inline per-case evidence only
        # when the row declares them explicitly.  A plain manifest metadata
        # row is not silently promoted to an audit record.
        if any(key in row for key in (*_T1_KEYS, *_AUDIT_PASS_KEYS)):
            case_evidence.append(row)
        normalized.append({"row": row, "case_id": case_id, "physical_case_id": physical_id,
                           "lineage_group_id": lineage_id, "family": family, "split": split,
                           "scope_id": scope_id, "recipe_id": recipe_id,
                           "evidence": case_evidence})

    # Any explicit qualification row is a gate violation even if a wrapper
    # incorrectly labels it train/validation.  It is excluded from production
    # counts so it cannot inflate a family's 32-case denominator.
    qualification_leaks = [item["case_id"] for item in normalized
                           if item["case_id"] and _qualification_marker(
                               [item["row"], *item["evidence"]])]
    if qualification_leaks:
        hold_reasons.append("qualification_only case appears in production rows: " + ", ".join(sorted(qualification_leaks)))

    production = [item for item in normalized
                  if item["case_id"] and not _qualification_marker(
                      [item["row"], *item["evidence"]])
                  and item["split"] != "qualification"]
    if any(item["family"] is None for item in production):
        missing = sorted(item["case_id"] for item in production if item["family"] is None)
        hold_reasons.append("production case has no T1 family: " + ", ".join(missing))
    if any(item["lineage_group_id"] is None for item in production):
        missing = sorted(item["case_id"] for item in production if item["lineage_group_id"] is None)
        hold_reasons.append("production case has no lineage_group_id: " + ", ".join(missing))
    if any(item["physical_case_id"] is None for item in production):
        missing = sorted(item["case_id"] for item in production if item["physical_case_id"] is None)
        hold_reasons.append("production case has no physical_case_id: " + ", ".join(missing))
    if any(item["scope_id"] is None or item["recipe_id"] is None for item in production):
        missing = sorted(item["case_id"] for item in production
                         if item["scope_id"] is None or item["recipe_id"] is None)
        hold_reasons.append("production case has no explicit scope/recipe identity: " + ", ".join(missing))
    if audit_hash_errors:
        hold_reasons.append("audit evidence hash/format failure: " + "; ".join(sorted(audit_hash_errors)))

    physical_counts = Counter(item["physical_case_id"] for item in production if item["physical_case_id"])
    duplicate_physical = sorted(key for key, count in physical_counts.items() if count > 1)
    if duplicate_physical:
        hold_reasons.append("duplicate physical_case_id in production: " + ", ".join(duplicate_physical))
    physical_splits: dict[str, set[str]] = defaultdict(set)
    for item in normalized:
        physical = item["physical_case_id"]
        if physical is not None:
            physical_splits[physical].add(item["split"])
    physical_split_violations = {
        key: sorted(value) for key, value in physical_splits.items() if len(value) > 1
    }
    if physical_split_violations:
        hold_reasons.append("physical case crosses splits: " +
                            ", ".join(sorted(physical_split_violations)))

    family_counts = Counter(item["family"] for item in production if item["family"])
    validation_counts = Counter(item["family"] for item in production if item["family"] and item["split"] == "validation")
    split_counts = Counter(item["split"] for item in production)
    families = sorted(family_counts)
    if len(families) < MIN_FAMILIES:
        hold_reasons.append(f"requires at least {MIN_FAMILIES} distinct T1 families; found {families}")
    for family in families:
        family_splits = Counter(item['split'] for item in production if item['family'] == family)
        train_count = family_splits['train']
        test_count = sum(family_splits[name] for name in ('test', 'id_test', 'ood_test'))
        if train_count < 16:
            hold_reasons.append(f"family {family} has {train_count} train cases; requires 16")
        if test_count < 12:
            hold_reasons.append(f"family {family} has {test_count} test cases; requires 12")
        unknown_splits = set(family_splits) - {'train', 'validation', 'test', 'id_test', 'ood_test'}
        if unknown_splits:
            hold_reasons.append(f"family {family} has unrecognized production splits: {sorted(unknown_splits)}")
        if family_counts[family] < CASES_PER_FAMILY:
            hold_reasons.append(f"family {family} has {family_counts[family]} production cases; requires {CASES_PER_FAMILY}")
        if validation_counts[family] < VALIDATION_PER_FAMILY:
            hold_reasons.append(f"family {family} has {validation_counts[family]} validation cases; requires {VALIDATION_PER_FAMILY}")

    lineage_splits: dict[str, set[str]] = defaultdict(set)
    lineage_families: dict[str, set[str]] = defaultdict(set)
    for item in normalized:
        lineage = item["lineage_group_id"]
        if lineage is not None:
            lineage_splits[lineage].add(item["split"])
            if item["family"]:
                lineage_families[lineage].add(item["family"])
    lineage_split_violations = {key: sorted(value) for key, value in lineage_splits.items() if len(value) > 1}
    lineage_family_violations = {key: sorted(value) for key, value in lineage_families.items() if len(value) > 1}
    if lineage_split_violations:
        hold_reasons.append("lineage crosses splits: " + ", ".join(sorted(lineage_split_violations)))
    if lineage_family_violations:
        hold_reasons.append("lineage crosses families: " + ", ".join(sorted(lineage_family_violations)))

    # Per-case evidence must establish T1 and a hard/structural audit.  A
    # family-level qualification record may supply T1 status, while the audit
    # still has to be present for every production row.  These marker checks
    # are diagnostic only; without a trusted admission capability, no family
    # T1 result is exported as verified.
    missing_evidence, t1_failures, audit_failures = [], [], []
    t1_binding_failures = []
    for item in production:
        family = item["family"]
        values = item["evidence"]
        if not values:
            missing_evidence.append(item["case_id"])
            continue
        row = item["row"]
        bound_values = [value for value in values if _binding_matches(row, value)]
        unbound_t1 = [value for value in values
                      if _bool_marker([value], _T1_KEYS) is not None
                      and not _binding_matches(row, value)]
        if unbound_t1:
            t1_binding_failures.append(item["case_id"])
        t1 = _bool_marker(bound_values, _T1_KEYS)
        if t1 is None:
            t1 = _bool_marker(_family_global_markers(
                family, evidence_global_rows, case_row=row), _T1_KEYS)
        if t1 is not True:
            t1_failures.append(item["case_id"])
        # Audit payloads are linked through the manifest's case-specific
        # reference, so they need not repeat scope/recipe fields.  An inline
        # row audit is also accepted only because it is nested under this row.
        audit = _bool_marker(values, _AUDIT_PASS_KEYS)
        # A manifest row with a declared audit reference but no loaded payload
        # remains unresolved; never treat a path string as a pass marker.
        if audit is not True:
            audit_failures.append(item["case_id"])
    if missing_evidence:
        hold_reasons.append("missing per-case qualification/audit evidence: " + ", ".join(sorted(missing_evidence)))
    if t1_failures:
        hold_reasons.append("T1 qualification is not passed for cases: " + ", ".join(sorted(t1_failures)))
    if t1_binding_failures:
        hold_reasons.append("T1 evidence scope/recipe mismatch: " + ", ".join(sorted(t1_binding_failures)))
    if audit_failures:
        hold_reasons.append("hard/structural audit is not passed for cases (explicit hard audit required): " + ", ".join(sorted(audit_failures)))

    if payload.get("formal_release") is not True:
        hold_reasons.append("manifest does not declare formal_release=true")
    evidence_refs.extend(audit_refs.values())
    # De-duplicate evidence refs while keeping stable order.
    unique_evidence_refs = []
    seen_refs = set()
    for ref in evidence_refs:
        key = (ref.get("path"), ref.get("sha256"))
        if key not in seen_refs:
            seen_refs.add(key)
            unique_evidence_refs.append(ref)

    return {
        "schema": "core.formal_input_audit.v1",
        "manifest": _ref(
            manifest_path,
            supplied="<in-memory-manifest>" if manifest_path is None else None,
            payload=payload, raw_sha256=manifest_raw_sha256),
        "manifest_schema": payload.get("schema"),
        "manifest_formal_release": payload.get("formal_release"),
        "case_count": len(rows),
        "production_case_count": len(production),
        "family_counts": dict(sorted(family_counts.items())),
        "validation_family_counts": dict(sorted(validation_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "families": families,
        "family_t1": {family: None for family in families},
        "lineage_isolation": {
            "passed": not lineage_split_violations and not lineage_family_violations,
            "split_violations": lineage_split_violations,
            "family_violations": lineage_family_violations,
        },
        "duplicate_case_ids": duplicate_case_ids,
        "duplicate_physical_case_ids": duplicate_physical,
        "physical_split_violations": physical_split_violations,
        "qualification_leaks": sorted(qualification_leaks),
        "evidence": unique_evidence_refs,
        "admission_basis": "metadata_only_untrusted",
        "hold_reasons": sorted(set(hold_reasons)),
        "formal_eligible": not hold_reasons,
    }


def _argument_list(*, python: str, script: str, manifest: str, data_root: str,
                   model: str, seed: int, run_id: str, device: str,
                   checkpoint: str, output: str, progress: str,
                   resume: str | None = None) -> list[str]:
    argv = [python, script, "train", "--manifest", manifest, "--data-root", data_root,
            "--model", model, "--seed", str(seed), "--updates", str(UPDATES),
            "--centers", str(CENTERS), "--hidden", str(HIDDEN),
            "--learning-rate", str(LEARNING_RATE),
            "--normalization-transitions", str(NORMALIZATION_TRANSITIONS),
            "--checkpoint", checkpoint, "--output", output, "--run-id", run_id,
            "--checkpoint-every", str(CHECKPOINT_EVERY), "--log-every", str(LOG_EVERY),
            "--validation-every", str(VALIDATION_EVERY),
            "--validation-transitions", str(VALIDATION_TRANSITIONS),
            "--validation-centers", str(VALIDATION_CENTERS),
            "--progress-output", progress, "--evaluate-milestones", "--device", device]
    if resume is not None:
        argv.extend(("--resume", resume))
    return argv


def _input_file_refs(code_files: Sequence[Mapping[str, Any]], audit: Mapping[str, Any],
                     profile_ref: Mapping[str, Any], environment_ref: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    refs = [dict(audit["manifest"]), *[dict(item) for item in audit.get("evidence", [])], dict(profile_ref)]
    if environment_ref and environment_ref.get("path") not in (None, "<in-memory>"):
        refs.append(dict(environment_ref))
    refs.extend({"path": item["path"], "sha256": item["sha256"]} for item in code_files)
    seen, result = set(), []
    for ref in refs:
        key = (ref.get("path"), ref.get("sha256"))
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _build_job(*, model: str, seed: int, audit: Mapping[str, Any],
               profile: Mapping[str, Any], profile_ref: Mapping[str, Any],
               code_files: Sequence[Mapping[str, Any]], code_root: Path,
               data_root: Path, environment: Mapping[str, Any],
               environment_ref: Mapping[str, Any] | None, device: str,
               run_prefix: str) -> dict[str, Any]:
    run_id = f"{run_prefix}-{model}-seed{seed}"
    manifest = str(audit["manifest"]["path"])
    python = str(environment["python_executable"])
    script = str((code_root / "scripts/core_learning.py").resolve())
    checkpoint = "{attempt_dir}/checkpoints/model.pt"
    output = "{attempt_dir}/training.json"
    progress = "{attempt_dir}/training-progress.json"
    resources = _profile_resources(profile, model)
    resource_block = dict(resources)
    resource_block["profile_sha256"] = profile_ref["sha256"]
    resource_block["profile_path"] = profile_ref["path"]
    validation_cases = sum(audit.get("validation_family_counts", {}).values())
    argv = _argument_list(python=python, script=script, manifest=manifest,
                          data_root=str(data_root), model=model, seed=seed,
                          run_id=run_id, device=device, checkpoint=checkpoint,
                          output=output, progress=progress)
    resume_argv = _argument_list(python=python, script=script, manifest=manifest,
                                 data_root=str(data_root), model=model, seed=seed,
                                 run_id=run_id, device=device, checkpoint=checkpoint,
                                 output=output, progress=progress,
                                 resume="{resume_checkpoint}")
    input_refs = _input_file_refs(code_files, audit, profile_ref, environment_ref)
    return {
        "schema": JOB_SCHEMA,
        "job_id": run_id,
        "logical_id": run_id,
        "host": profile.get("host", "unassigned"),
        "cwd": str(code_root),
        "argv": argv,
        "resume_argv": resume_argv,
        "resources": resource_block,
        "input_files": input_refs,
        "required_outputs": ["training.json", "training-progress.json",
                              "checkpoints/model.step-00008000.pt",
                              "checkpoints/model.step-00016000.pt",
                              "checkpoints/model.step-00024000.pt",
                              "checkpoints/model.step-00032000.pt"],
        "formal_core_case_run": True,
        "formal_training": True,
        "test_included": False,
        "qualification_only": False,
        "training_protocol": {
            "schema": "core.training.v1",
            "updates": UPDATES, "checkpoint_milestones": list(MILESTONES),
            "centers_per_update": CENTERS, "hidden": HIDDEN,
            "learning_rate": LEARNING_RATE,
            "normalization_transitions": NORMALIZATION_TRANSITIONS,
            "normalization_split": "train",
            "training_split": "train", "validation_split": "validation",
            "validation_case_count": validation_cases,
            "validation_family_counts": audit.get("validation_family_counts", {}),
            "evaluate_milestones": True,
            "full_validation_rollout_at_each_milestone": True,
            "test_included": False,
        },
        "checkpoint_selection": {
            "module": "scripts/core_evaluation.py",
            "function": "select_checkpoint",
            "updates": list(MILESTONES), "split": "validation",
            "fixed_denominator": True, "requires_all_milestones": True,
        },
        "resume": {
            "supported": True,
            "argument": "--resume {resume_checkpoint}",
            "checkpoint_source": "{resume_checkpoint}",
            "same_run_id_required": True,
            "restores": ["optimizer_state", "sampler_state", "rng_state",
                         "validation_history", "milestone_evaluations",
                         "milestone_evaluation_plan"],
            "resume_equivalence_contract": "core.training.resume.v1",
        },
        "source_snapshot_policy": {
            "mode": "fresh_code_closure",
            "required_files": [item["relative_path"] for item in code_files],
            "reject_missing_or_mismatched": True,
            "inherited_profile_argv": False,
        },
        "bindings": {
            "manifest": dict(audit["manifest"]),
            "code_root": str(code_root), "code_files": list(code_files),
            "environment": dict(environment), "profile": dict(profile_ref),
            "audit_evidence": list(audit.get("evidence", [])),
        },
        "resource_profile": profile_ref["path"],
        "manifest_sha256": audit["manifest"]["sha256"],
        "profile_sha256": profile_ref["sha256"],
        "environment_sha256": environment_ref["sha256"] if environment_ref else None,
        "code_closure_sha256": _json_hash(
            [{"relative_path": item["relative_path"], "sha256": item["sha256"]}
             for item in code_files]),
        "scientific_claim": "formal three-family Core training job specification; execution pending central admission",
        "launch_allowed_by_planner": True,
    }


def build_plan(manifest: Any, *, evidence: Sequence[Any] | Any | None = None,
               profile: Any | None = None, environment: Any | None = None,
               data_root: str | Path | None = None,
               code_root: str | Path | None = None,
               python_executable: str | Path | None = None,
               source_snapshot: Any | None = None,
               output_dir: str | Path | None = None,
               run_prefix: str = "core-v1-formal", device: str = "cuda",
               write_specs: bool = True) -> dict[str, Any]:
    """Create a hold report or nine immutable job specifications.

    A hold always returns ``jobs: []`` and never creates spec files.  The
    caller may still write the returned report for scheduler inspection.
    """
    root = Path(data_root).expanduser().resolve() if data_root is not None else Path.cwd().resolve()
    code = Path(code_root).expanduser().resolve() if code_root is not None else Path(__file__).resolve().parents[1]
    audit = inspect_inputs(manifest, evidence=evidence, data_root=root)
    hold_reasons = list(audit["hold_reasons"])

    profile_payload, profile_path = (None, None)
    if profile is None:
        hold_reasons.append("a measured profile resource is required")
        profile_ref = {"path": "<missing-profile>", "sha256": None}
    else:
        profile_payload, profile_path, profile_raw_sha256 = _load_json(profile, data_root=root)
        if not isinstance(profile_payload, Mapping):
            hold_reasons.append("profile resource must be a JSON object")
            profile_payload = {}
        profile_ref = _ref(
            profile_path,
            supplied="<in-memory-profile>" if profile_path is None else None,
            payload=profile_payload, raw_sha256=profile_raw_sha256)

    environment_payload, environment_ref = _environment_binding(
        environment, data_root=root, python_executable=python_executable)
    if environment_payload is None:
        hold_reasons.append("an explicit execution environment and python executable are required")
        environment_ref = None
    elif not environment_payload.get("python_exists", False):
        # The planner may run on a controller while the bound interpreter is
        # present only on the declared host.  Keep the explicit path in the
        # spec and defer its existence check to launch admission; an absent
        # environment record or an absent executable declaration still holds.
        environment_payload["python_verification"] = "deferred_to_declared_host"

    code_files, missing_code = _code_bundle(code)
    if missing_code:
        hold_reasons.append("code closure is missing: " + ", ".join(missing_code))
    snapshot_info, snapshot_errors = _snapshot_check(source_snapshot, code_root=code,
                                                     required=REQUIRED_CODE_FILES)
    hold_reasons.extend(snapshot_errors)
    if profile_payload:
        for model in MODELS:
            try:
                _profile_resources(profile_payload, model)
            except ValueError as error:
                hold_reasons.append(str(error))

    jobs = []
    if not hold_reasons and profile_payload and environment_payload:
        for model in MODELS:
            for seed in SEEDS:
                jobs.append(_build_job(model=model, seed=seed, audit=audit,
                                       profile=profile_payload, profile_ref=profile_ref,
                                       code_files=code_files, code_root=code,
                                       data_root=root, environment=environment_payload,
                                       environment_ref=environment_ref, device=device,
                                       run_prefix=run_prefix))

    result = {
        "schema": PLANNER_SCHEMA,
        "status": "ready" if jobs and not hold_reasons else "hold",
        "launch_allowed": bool(jobs and not hold_reasons),
        "formal_job_count": len(jobs),
        "required_job_count": len(MODELS) * len(SEEDS),
        "models": list(MODELS), "seeds": list(SEEDS),
        "audit": audit,
        "hold_reasons": sorted(set(hold_reasons)),
        "code": {"root": str(code), "files": code_files, "missing": missing_code},
        "environment": environment_payload,
        "environment_ref": environment_ref,
        "profile": profile_ref,
        "source_snapshot": snapshot_info,
        "jobs": jobs,
        "writes_ledger": False, "submitted": False, "gpu_started": False,
    }
    if output_dir is not None and write_specs and result["status"] == "ready":
        target = Path(output_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        for job in jobs:
            path = target / f"{job['job_id']}.json"
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(job, indent=2, sort_keys=True, allow_nan=False) + "\n")
            os.replace(temporary, path)
        result["spec_directory"] = str(target)
        result["spec_paths"] = [str(target / f"{job['job_id']}.json") for job in jobs]
    else:
        result["spec_directory"] = None
        result["spec_paths"] = []
    return result


# Descriptive aliases for scheduler/test callers.
plan_formal_jobs = build_plan
audit_formal_inputs = inspect_inputs


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    plan = sub.add_parser("plan", help="audit inputs and write a nine-job plan/spec directory")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--data-root", type=Path, default=Path.cwd())
    plan.add_argument("--evidence", "--qualification-evidence", dest="evidence",
                      type=Path, action="append", default=[])
    plan.add_argument("--profile-resource", "--profile", dest="profile_resource",
                      type=Path, required=True)
    plan.add_argument("--environment", "--environment-record", dest="environment",
                      type=Path)
    plan.add_argument("--python-executable", type=Path)
    plan.add_argument("--source-snapshot", type=Path)
    plan.add_argument("--code-root", type=Path, default=Path(__file__).resolve().parents[1])
    plan.add_argument("--output", type=Path, required=True,
                      help="JSON audit/hold report")
    plan.add_argument("--spec-dir", type=Path,
                      help="directory for specs; created only when status is ready")
    plan.add_argument("--run-prefix", default="core-v1-formal")
    plan.add_argument("--device", default="cuda")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command not in (None, "plan"):
        parser.error(f"unknown command {args.command}")
    if args.command is None:
        parser.error("the plan subcommand is required")
    result = build_plan(args.manifest, evidence=args.evidence,
                        profile=args.profile_resource, environment=args.environment,
                        data_root=args.data_root, code_root=args.code_root,
                        python_executable=args.python_executable,
                        source_snapshot=args.source_snapshot,
                        output_dir=args.spec_dir, run_prefix=args.run_prefix,
                        device=args.device)
    _write_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "formal_job_count": result["formal_job_count"],
                      "hold_reasons": result["hold_reasons"]}, sort_keys=True))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
