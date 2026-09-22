#!/usr/bin/env python3
"""Audit the read-only Core formal-training admission boundary.

This module joins the currently released F3/F4 reader manifests without
creating a merged training manifest, opening an HDF5 trajectory, launching a
worker, or touching a registry/ledger.  It checks the small JSON audit receipts
that are already bound by the manifests (and the versioned F3 legacy adapter),
keeps every production row in its denominator, and emits explicit blocker
codes for the remaining formal gate dependencies.

The output is an admission observation.  It intentionally emits zero formal
job specifications even when all metadata checks pass.  A later planner run
must bind the final three-family manifest and a fresh source closure before
any optimizer can be admitted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "core.formal_admission_audit.v1"
FORMAL_MODELS = ("mlp", "graph_raw", "graph_residual")
FORMAL_SEEDS = (17, 29, 43)
FORMAL_JOB_COUNT = len(FORMAL_MODELS) * len(FORMAL_SEEDS)
REQUIRED_FAMILIES = 3
CASES_PER_FAMILY = 32
TRAIN_CASES_PER_FAMILY = 16
VALIDATION_CASES_PER_FAMILY = 4
TEST_CASES_PER_FAMILY = 12
REQUIRED_VALIDATION_CASES = REQUIRED_FAMILIES * VALIDATION_CASES_PER_FAMILY
DIAGNOSTIC_JOB_COUNT = 3
FORMAL_UPDATES = 32000
ADAPTER_SCHEMAS = {
    "core.f3.legacy_hard_audit_adapter.v1",
    "core.f3.structural_audit_adapter.v1",
}

# Keep this closure equal to the closure used by core_formal_planner.py.  The
# admission auditor itself is deliberately outside the learning source
# closure: changing an audit report must not silently change a training job.
REQUIRED_CODE_FILES = (
    "scripts/core_learning.py",
    "scripts/core_contract.py",
    "scripts/core_dataset.py",
    "scripts/core_models.py",
    "scripts/core_cfd_dataset.py",
    "scripts/core_evaluation.py",
    "scripts/core_physics.py",
    "scripts/core_formal_planner.py",
)


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


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


def _resolve(value: str | Path, *, root: Path, base: Path | None = None) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    options = []
    if base is not None:
        options.append((base / candidate).resolve())
    options.append((root / candidate).resolve())
    for option in options:
        if option.exists():
            return option
    return options[0]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_json(source: str | Path | Mapping[str, Any], *, root: Path) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, Mapping):
        return dict(source), None
    path = _resolve(source, root=root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return dict(payload), path


def _ref(path: Path, root: Path) -> dict[str, Any]:
    return {"path": _relative(path, root), "sha256": sha256_file(path),
            "bytes": path.stat().st_size}


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("cases", "production_cases", "records", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _case_id(row: Mapping[str, Any]) -> str | None:
    for key in ("case_id", "id", "case"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _family(row: Mapping[str, Any]) -> str | None:
    for key in ("family", "family_id", "family_code"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _scope(row: Mapping[str, Any]) -> str | None:
    value = row.get("scope_id", row.get("scope"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _recipe(row: Mapping[str, Any]) -> str | None:
    for key in ("recipe_id", "recipe"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("known_inputs_ref", "known_inputs", "numerics", "physics"):
        block = row.get(key)
        if isinstance(block, Mapping):
            nested = _recipe(block)
            if nested:
                return nested
    return None


def _physical(row: Mapping[str, Any]) -> str | None:
    value = row.get("physical_case_id", row.get("physical_id"))
    return str(value) if value is not None else None


def _lineage(row: Mapping[str, Any]) -> str | None:
    value = row.get("lineage_group_id", row.get("lineage_id"))
    return str(value) if value is not None else None


def _is_qualification(row: Mapping[str, Any]) -> bool:
    if row.get("qualification_case") is True or row.get("qualification_only") is True:
        return True
    if str(row.get("split", "")).lower() in {"qualification", "qualification_only"}:
        return True
    if str(row.get("stage", "")).lower() in {
        "qualification", "qualification_only", "canary", "repair_canary",
        "calibration", "diagnostic", "repair", "qualification_canary",
    }:
        return True
    claim = row.get("qualification_claim")
    if isinstance(claim, str):
        normalized = claim.strip().lower()
        if normalized in {"", "none"} or normalized.startswith(("none;", "none:")):
            return False
    return claim not in (None, "", "none", False)


def _audit_ref(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("audit", "audit_ref", "audit_path", "source_audit"):
        value = row.get(key)
        if isinstance(value, Mapping):
            return value
    for block_key in ("provenance", "source_evidence", "evidence"):
        block = row.get(block_key)
        if isinstance(block, Mapping):
            for key in ("audit", "audit_ref", "audit_path", "source_audit"):
                value = block.get(key)
                if isinstance(value, Mapping):
                    return value
    return None


def _load_bound_json(reference: Mapping[str, Any], *, root: Path,
                     base: Path | None, role: str) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    path_value = reference.get("path")
    declared = reference.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        return None, {"role": role}, f"{role} has no path"
    path = _resolve(path_value, root=root, base=base)
    ref = {"role": role, "path": _relative(path, root), "declared_sha256": declared}
    if not path.is_file():
        return None, ref, f"{role} is missing: {path}"
    observed = sha256_file(path)
    ref["sha256"] = observed
    if not isinstance(declared, str) or len(declared) != 64:
        return None, ref, f"{role} has no declared SHA-256: {path}"
    if observed.lower() != declared.lower():
        return None, ref, f"{role} SHA-256 mismatch: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, ref, f"{role} is invalid JSON: {path}: {error}"
    if not isinstance(payload, Mapping):
        return None, ref, f"{role} JSON is not an object: {path}"
    return payload, ref, None


def _evidence_rows(payload: Mapping[str, Any]) -> tuple[dict[str, list[Mapping[str, Any]]], list[Mapping[str, Any]]]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    global_rows: list[Mapping[str, Any]] = [payload]
    for row in _rows(payload):
        case_id = _case_id(row)
        if case_id:
            by_case[case_id].append(row)
    return by_case, global_rows


def _bound_adapter_cases(
    loaded_evidence: Sequence[tuple[dict[str, Any], Path | None]],
    *, manifest_hashes: set[str], root: Path,
) -> tuple[dict[str, Mapping[str, Any]], bool, list[str]]:
    """Resolve adapter case rows and recheck structural receipt references.

    The top-level adapter hash binds the receipt set to a reader manifest.  A
    structural adapter then binds each case row to an immutable receipt file;
    checking only the aggregate marker would allow a case-id-only assertion to
    mask a missing or changed receipt.
    """
    bound: dict[str, Mapping[str, Any]] = {}
    adapter_present = False
    errors: list[str] = []
    for payload, evidence_path in loaded_evidence:
        if payload.get("schema") not in ADAPTER_SCHEMAS:
            continue
        if payload.get("manifest_sha256") not in manifest_hashes:
            continue
        adapter_present = True
        schema = payload.get("schema")
        if schema == "core.f3.legacy_hard_audit_adapter.v1":
            for row in _rows(payload):
                case_id = _case_id(row)
                if case_id:
                    merged = dict(bound.get(case_id, {}))
                    merged.update(row)
                    bound[case_id] = merged
            continue
        for reference in _rows(payload):
            case_id = _case_id(reference)
            if case_id is None:
                errors.append("structural adapter row has no case_id")
                continue
            receipt, _, error = _load_bound_json(
                reference, root=root,
                base=evidence_path.parent if evidence_path is not None else None,
                role=f"{case_id} structural receipt")
            if error is not None or receipt is None:
                errors.append(error or f"{case_id} structural receipt is missing")
                continue
            binding = receipt.get("manifest_binding")
            if not isinstance(binding, Mapping) or binding.get("sha256") not in manifest_hashes:
                errors.append(f"{case_id} structural receipt manifest binding mismatch")
                continue
            if (_case_id(receipt) != case_id
                    or receipt.get("schema") != "core.f3.structural_audit_receipt.v1"
                    or receipt.get("structural_pass") is not True):
                errors.append(f"{case_id} structural receipt identity/schema/pass mismatch")
                continue
            merged = dict(bound.get(case_id, {}))
            merged.update(receipt)
            bound[case_id] = merged
    return bound, adapter_present, errors


def _audit_markers(payload: Mapping[str, Any]) -> tuple[bool | None, bool | None]:
    hard = payload.get("hard_integrity_pass")
    structural = payload.get("structural_pass")
    nested = payload.get("structural")
    if isinstance(nested, Mapping):
        if structural is None:
            structural = nested.get("structural_pass")
    return (hard if isinstance(hard, bool) else None,
            structural if isinstance(structural, bool) else None)


def _audit_identity(payload: Mapping[str, Any], case: Mapping[str, Any]) -> bool:
    """Check every identity field that the audit explicitly declares."""
    case_id = _case_id(case)
    declared_case = _case_id(payload)
    if declared_case is not None and declared_case != case_id:
        return False
    declared_family = _family(payload)
    if declared_family is None and isinstance(payload.get("structural"), Mapping):
        attrs = payload["structural"].get("attrs")
        if isinstance(attrs, Mapping):
            declared_family = _family(attrs)
    if declared_family is not None and declared_family != _family(case):
        return False
    for field, getter in (("physical_case_id", _physical), ("lineage_group_id", _lineage),
                          ("recipe_id", _recipe), ("scope_id", _scope)):
        declared = getter(payload)
        if declared is None and isinstance(payload.get("structural"), Mapping):
            attrs = payload["structural"].get("attrs")
            if isinstance(attrs, Mapping):
                declared = getter(attrs)
        expected = getter(case)
        if declared is not None and expected is not None and declared != expected:
            return False
    return declared_case == case_id


def _portable_relative_path(value: Any) -> bool:
    """Match ``core_dataset``'s portable asset-path contract."""
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _validate_manifest(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") not in {"core.dataset.v1", "core.dataset.v2"}:
        errors.append(f"unsupported reader manifest schema: {payload.get('schema')}")
    if not isinstance(payload.get("formal_release"), bool):
        errors.append("formal_release must be boolean")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows:
        errors.append("reader manifest has no cases")
        return errors
    seen: set[str] = set()
    physical: dict[str, str] = {}
    lineages: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"case {index} is not an object")
            continue
        case_id = _case_id(row)
        for name, value in (("case_id", case_id), ("physical_case_id", _physical(row)),
                            ("lineage_group_id", _lineage(row)), ("family", _family(row)),
                            ("split", row.get("split"))):
            if value in (None, ""):
                errors.append(f"case {index} has no {name}")
        if not _portable_relative_path(row.get("hdf5")):
            errors.append(f"case {case_id} has nonportable hdf5 path")
        if case_id and case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        if case_id:
            seen.add(case_id)
        split = str(row.get("split", ""))
        physical_id = _physical(row)
        lineage_id = _lineage(row)
        if physical_id:
            prior = physical.setdefault(physical_id, split)
            if prior != split:
                errors.append(f"physical case crosses splits: {physical_id}")
        if lineage_id:
            prior = lineages.setdefault(lineage_id, split)
            if prior != split:
                errors.append(f"lineage crosses splits: {lineage_id}")
        if payload.get("schema") == "core.dataset.v2":
            refs = row.get("known_inputs_ref")
            if not isinstance(refs, Mapping):
                errors.append(f"case {case_id} has no known_inputs_ref")
            else:
                for key in ("geometry", "control"):
                    ref = refs.get(key)
                    if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
                        errors.append(f"case {case_id} has no portable {key} reference")
                    elif not _portable_relative_path(ref.get("path")):
                        errors.append(f"case {case_id} has nonportable {key} reference")
    return sorted(set(errors))


def _source_closure(code_root: Path, preprofile_index: Path | None,
                    root: Path) -> dict[str, Any]:
    current: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in REQUIRED_CODE_FILES:
        path = (code_root / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        current.append({"relative_path": relative, "sha256": sha256_file(path),
                        "bytes": path.stat().st_size})
    current_digest = canonical_sha256([
        {"relative_path": row["relative_path"], "sha256": row["sha256"]}
        for row in current
    ])
    previous: dict[str, Any] | None = None
    mismatches: list[str] = []
    if preprofile_index is not None and preprofile_index.is_file():
        payload = json.loads(preprofile_index.read_text(encoding="utf-8"))
        closure = payload.get("planner_closure", {}) if isinstance(payload, Mapping) else {}
        files = closure.get("files", []) if isinstance(closure, Mapping) else []
        previous_by_name = {
            str(item.get("relative_path", item.get("path", ""))): item.get("sha256")
            for item in files if isinstance(item, Mapping)
        }
        current_by_name = {item["relative_path"]: item["sha256"] for item in current}
        names = sorted(set(previous_by_name) | set(current_by_name))
        mismatches = [name for name in names if previous_by_name.get(name) != current_by_name.get(name)]
        previous = {
            "path": _relative(preprofile_index, root),
            "sha256": sha256_file(preprofile_index),
            "closure_sha256": closure.get("sha256") if isinstance(closure, Mapping) else None,
            "file_count": len(files),
            "mismatch_files": mismatches,
        }
    return {
        "hash_algorithm": "sha256",
        "required_files": list(REQUIRED_CODE_FILES),
        "current_files": current,
        "missing_files": missing,
        "current_closure_sha256": current_digest,
        "preprofile": previous,
        "preprofile_source_closure_match": bool(previous is not None and not mismatches),
        "preprofile_mismatch_count": len(mismatches),
        "fresh_admission_closure_complete": not missing,
    }


def _capacity_evidence_observation(source: Path | Mapping[str, Any] | None, *, root: Path,
                                   manifest_hashes: set[str]) -> dict[str, Any]:
    """Bind the output of the real-capacity adapter without re-running it.

    The adapter is intentionally a separate read-only boundary: this audit
    only rechecks its schema, no-side-effect constraints, exact update
    frontier, and manifest/checkpoint/source-closure references.  A synthetic
    dry run or a short graph probe therefore cannot be promoted by passing a
    different flag to this auditor.
    """
    if source is None:
        return {
            "bound": False, "valid": False, "formal_capacity_evidence": False,
            "formal_runs_counted": 0,
        }
    try:
        path = _resolve(source, root=root) if isinstance(source, (str, Path)) else None
        payload = (json.loads(path.read_text(encoding="utf-8")) if path is not None
                   else dict(source))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return {
            "bound": True, "valid": False, "formal_capacity_evidence": False,
            "formal_runs_counted": 0, "error": str(error),
        }
    if not isinstance(payload, Mapping):
        return {
            "bound": True, "valid": False, "formal_capacity_evidence": False,
            "formal_runs_counted": 0, "error": "capacity evidence is not a JSON object",
        }
    constraints = payload.get("execution_constraints", {})
    manifest = payload.get("manifest", {})
    closure = payload.get("source_closure", {})
    checkpoints = payload.get("checkpoints", [])
    receipt = payload.get("receipt", {})
    execution = payload.get("execution", {})
    required_constraints = {
        "read_only": True,
        "formal_runs_started": 0,
        "central_registry_mutation": 0,
        "central_ledger_mutation": 0,
        "solver_started": False,
        "submitted": False,
    }
    valid = bool(
        payload.get("schema") == "core.formal_capacity_evidence.v1"
        and payload.get("status") == "ready"
        and payload.get("valid") is True
        and payload.get("formal_capacity_evidence") is True
        and payload.get("formal_training") is False
        and payload.get("formal_job_count") == 0
        and payload.get("formal_runs_counted") == 0
        and payload.get("observed_update_frontier") == FORMAL_UPDATES
        and manifest.get("valid") is True
        and closure.get("valid") is True
        and isinstance(checkpoints, list)
        and {item.get("update") for item in checkpoints if isinstance(item, Mapping)} == {
            8000, 16000, 24000, 32000
        }
        and isinstance(receipt, Mapping) and isinstance(receipt.get("sha256"), str)
        and isinstance(execution, Mapping) and isinstance(execution.get("sha256"), str)
        and all(constraints.get(key) == value for key, value in required_constraints.items())
    )
    manifest_sha = manifest.get("sha256")
    if manifest_sha not in manifest_hashes:
        valid = False
    refs: list[dict[str, Any]] = []
    for name, reference in (("receipt", receipt), ("execution", execution)):
        if not isinstance(reference, Mapping):
            valid = False
            continue
        path_value = reference.get("path")
        declared = reference.get("sha256")
        if not isinstance(path_value, str) or not isinstance(declared, str):
            valid = False
            continue
        resolved = _resolve(path_value, root=root)
        observed = sha256_file(resolved) if resolved.is_file() else None
        if observed != declared:
            valid = False
        refs.append({"name": name, "path": _relative(resolved, root),
                     "sha256": observed, "declared_sha256": declared})
    return {
        "bound": True,
        "valid": valid,
        "path": _relative(path, root) if path is not None else "<in-memory>",
        "sha256": sha256_file(path) if path is not None and path.is_file() else canonical_sha256(payload),
        "schema": payload.get("schema"),
        "formal_capacity_evidence": bool(payload.get("formal_capacity_evidence")),
        "formal_runs_counted": payload.get("formal_runs_counted", 0),
        "observed_update_frontier": payload.get("observed_update_frontier"),
        "manifest": dict(manifest) if isinstance(manifest, Mapping) else manifest,
        "source_closure": dict(closure) if isinstance(closure, Mapping) else closure,
        "checkpoints": list(checkpoints) if isinstance(checkpoints, list) else checkpoints,
        "references": refs,
        "execution_constraints": dict(constraints) if isinstance(constraints, Mapping) else constraints,
    }


def _resource_observation(profile: Path | None, *, root: Path,
                          capacity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if profile is None:
        result = {"bound": False, "formal_capacity_evidence": False, "diagnostic_only": True}
        if capacity and capacity.get("valid"):
            result.update({
                "bound": True,
                "formal_capacity_evidence": True,
                "diagnostic_only": True,
                "capacity_evidence_only": True,
                "observed_update_frontier": capacity.get("observed_update_frontier"),
                "capacity_evidence": dict(capacity),
            })
        return result
    payload = json.loads(profile.read_text(encoding="utf-8"))
    configurations = payload.get("configurations", []) if isinstance(payload, Mapping) else []
    updates = [item.get("optimizer_updates") for item in configurations
               if isinstance(item, Mapping) and isinstance(item.get("optimizer_updates"), int)]
    frontier = max(updates, default=0)
    result = {
        "bound": True,
        "path": _relative(profile, root),
        "sha256": sha256_file(profile),
        "observed_update_frontier": frontier,
        "formal_update_target": FORMAL_UPDATES,
        # A resource profile is observational metadata only.  Even a
        # 32000-update CPU/synthetic profile cannot prove the real full-field
        # CUDA frontier; that promotion requires the hash-bound adapter below.
        "formal_capacity_evidence": False,
        "diagnostic_only": True,
        "limits": payload.get("limits"),
    }
    if capacity and capacity.get("valid"):
        result.update({
            "formal_capacity_evidence": True,
            "capacity_evidence_only": True,
            "capacity_evidence": dict(capacity),
            "observed_update_frontier": FORMAL_UPDATES,
        })
    return result


def _resource_dryrun_observation(path: Path | None, *, root: Path) -> dict[str, Any]:
    """Bind a completed synthetic frontier probe without treating it as formal."""
    if path is None:
        return {
            "bound": False,
            "valid": False,
            "formal_capacity_evidence": False,
            "formal_runs_counted": 0,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    constraints = payload.get("execution_constraints", {})
    protocol = payload.get("protocol", {})
    valid = bool(
        payload.get("schema") == "core.formal_resource_dryrun.v1"
        and payload.get("status") == "completed"
        and payload.get("dry_run") is True
        and payload.get("formal_release") is False
        and payload.get("formal_training") is False
        and payload.get("formal_job_count") == 0
        and protocol.get("updates_completed") == FORMAL_UPDATES
        and constraints.get("formal_runs_started") == 0
        and constraints.get("gpu_started") is False
        and constraints.get("central_registry_mutation") == 0
        and constraints.get("central_ledger_mutation") == 0
    )
    return {
        "bound": True,
        "valid": valid,
        "path": _relative(path, root),
        "sha256": sha256_file(path),
        "schema": payload.get("schema"),
        "dry_run": payload.get("dry_run"),
        "formal_capacity_evidence": False,
        "formal_runs_counted": 0,
        "updates_completed": protocol.get("updates_completed"),
        "resource": payload.get("resource"),
        "execution_constraints": constraints,
    }


def _graph_probe_observation(path: Path | None, *, root: Path) -> dict[str, Any]:
    """Bind a bounded full-field graph probe without treating its estimate as capacity proof."""
    if path is None:
        return {
            "bound": False,
            "valid": False,
            "formal_capacity_evidence": False,
            "formal_runs_counted": 0,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    constraints = payload.get("execution_constraints", {})
    protocol = payload.get("protocol", {})
    updates = payload.get("updates", {})
    io_and_graph = payload.get("io_and_graph", {})
    neighbor_diagnostics = io_and_graph.get("neighbor_diagnostics", {})
    case = payload.get("case", {})
    full_pipeline_seconds = updates.get("estimated_32000_full_pipeline_seconds")
    full_pipeline_hours = updates.get("estimated_32000_full_pipeline_hours")
    valid = bool(
        payload.get("schema") == "core.formal_graph_capacity_probe.v1"
        and payload.get("status") == "completed"
        and payload.get("diagnostic_only") is True
        and payload.get("formal_release") is False
        and payload.get("formal_training") is False
        and payload.get("formal_job_count") == 0
        and protocol.get("model_kind") in {"graph_raw", "graph_residual"}
        and protocol.get("full_particle_axis") is True
        and protocol.get("target_updates") == FORMAL_UPDATES
        and isinstance(updates.get("completed"), int)
        and updates.get("completed", 0) >= 1
        and protocol.get("probe_updates") == updates.get("completed")
        and case.get("family") == "F4"
        and isinstance(case.get("particles"), int)
        and case.get("particles", 0) > 0
        and io_and_graph.get("hdf5_opened_for_diagnostic") is True
        and neighbor_diagnostics.get("field_particle_count") == case.get("particles")
        # The estimate deliberately charges one representative transition read
        # and one neighbor rebuild to every update.  Keeping this assertion in
        # the audit makes a semantic shortcut fail closed instead of silently
        # becoming a capacity claim.
        and updates.get("estimate_is_extrapolation") is True
        and updates.get("full_pipeline_basis") == (
            "one representative HDF5 transition plus neighbor rebuild per optimizer update"
        )
        and isinstance(full_pipeline_seconds, (int, float))
        and math.isfinite(float(full_pipeline_seconds))
        and full_pipeline_seconds > 0
        and isinstance(full_pipeline_hours, (int, float))
        and math.isfinite(float(full_pipeline_hours))
        and full_pipeline_hours > 0
        and constraints.get("formal_runs_started") == 0
        and constraints.get("trajectory_files_opened") is True
        and constraints.get("central_registry_mutation") == 0
        and constraints.get("central_ledger_mutation") == 0
        and constraints.get("checkpoint_written") is False
        and constraints.get("training_receipt_written") is False
    )
    return {
        "bound": True,
        "valid": valid,
        "path": _relative(path, root),
        "sha256": sha256_file(path),
        "schema": payload.get("schema"),
        "diagnostic_only": payload.get("diagnostic_only"),
        "formal_capacity_evidence": False,
        "formal_runs_counted": 0,
        "protocol": protocol,
        "case": payload.get("case"),
        "io_and_graph": io_and_graph,
        "updates": updates,
        "resource": payload.get("resource"),
        "execution_constraints": constraints,
    }


def _blocker(code: str, message: str, *, observed: Any = None,
             required: Any = None, scope: str = "formal",
             cases: Sequence[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "scope": scope, "message": message}
    if observed is not None:
        result["observed"] = observed
    if required is not None:
        result["required"] = required
    if cases is not None:
        result["case_count"] = len(cases)
        result["case_ids"] = list(cases)
    return result


def audit_admission(
    manifests: Sequence[str | Path | Mapping[str, Any]], *,
    data_root: str | Path,
    evidence: Sequence[str | Path | Mapping[str, Any]] = (),
    code_root: str | Path | None = None,
    preprofile_index: str | Path | None = None,
    resource_profile: str | Path | None = None,
    resource_dryrun: str | Path | None = None,
    graph_probe: str | Path | None = None,
    capacity_evidence: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic, read-only admission observation."""
    root = Path(data_root).expanduser().resolve()
    code = Path(code_root).expanduser().resolve() if code_root is not None else root
    manifest_errors: list[str] = []
    source_records: list[dict[str, Any]] = []
    all_rows: list[tuple[dict[str, Any], Path | None, dict[str, Any]]] = []
    for source in manifests:
        try:
            payload, path = _load_json(source, root=root)
            errors = _validate_manifest(payload)
            source_record = {
                "path": _relative(path, root) if path is not None else "<in-memory>",
                "sha256": sha256_file(path) if path is not None else canonical_sha256(payload),
                "schema": payload.get("schema"),
                "dataset_id": payload.get("dataset_id"),
                "formal_release": payload.get("formal_release"),
                "case_count": len(_rows(payload)),
                "manifest_errors": errors,
                "read_only": True,
            }
            source_records.append(source_record)
            manifest_errors.extend(f"{source_record['path']}: {error}" for error in errors)
            for row in _rows(payload):
                all_rows.append((row, path, source_record))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            manifest_errors.append(str(error))

    evidence_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    evidence_global: list[Mapping[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    loaded_evidence: list[tuple[dict[str, Any], Path | None]] = []
    for source in evidence:
        payload, path = _load_json(source, root=root)
        loaded_evidence.append((payload, path))
        by_case, global_rows = _evidence_rows(payload)
        # Adapter rows are only admissible through their top-level manifest
        # binding below.  Keeping them out of the generic evidence channel
        # prevents an unbound adapter row from qualifying by case_id alone.
        if payload.get("schema") in ADAPTER_SCHEMAS:
            by_case = {}
        for case_id, rows in by_case.items():
            evidence_by_case[case_id].extend(rows)
        evidence_global.extend(global_rows)
        evidence_records.append({
            "path": _relative(path, root) if path is not None else "<in-memory>",
            "sha256": sha256_file(path) if path is not None else canonical_sha256(payload),
            "schema": payload.get("schema"),
            "case_count": len(_rows(payload)),
            "read_only": True,
        })

    duplicate_case_ids = sorted(case_id for case_id, count in Counter(
        _case_id(row) for row, _, _ in all_rows).items()
        if case_id is not None and count > 1)
    physical_owner: dict[str, tuple[str, str]] = {}
    lineage_owner: dict[str, tuple[str, str]] = {}
    duplicate_physical: list[str] = []
    duplicate_lineage: list[str] = []
    family_summaries: dict[str, dict[str, Any]] = {}
    case_observations: list[dict[str, Any]] = []

    # Validate an evidence adapter's manifest and per-receipt binding once. A
    # case-level marker from an unrelated adapter must never qualify a row
    # merely because its case_id happens to match.
    manifest_hashes = {record["sha256"] for record in source_records}
    bound_adapter_cases, adapter_present, adapter_binding_errors = _bound_adapter_cases(
        loaded_evidence, manifest_hashes=manifest_hashes, root=root)

    for row, manifest_path, source_record in all_rows:
        case_id = _case_id(row) or "<missing-case-id>"
        family = _family(row) or "<missing-family>"
        split = str(row.get("split", ""))
        physical_id = _physical(row)
        lineage_id = _lineage(row)
        if physical_id is not None:
            prior = physical_owner.get(physical_id)
            owner = (family, split)
            if prior is not None and prior != owner:
                duplicate_physical.append(physical_id)
            physical_owner[physical_id] = owner
        if lineage_id is not None:
            prior = lineage_owner.get(lineage_id)
            owner = (family, split)
            if prior is not None and prior != owner:
                duplicate_lineage.append(lineage_id)
            lineage_owner[lineage_id] = owner

        direct_payload: Mapping[str, Any] | None = None
        direct_ref: dict[str, Any] | None = None
        direct_error: str | None = None
        audit_reference = _audit_ref(row)
        if audit_reference is not None:
            direct_payload, direct_ref, direct_error = _load_bound_json(
                audit_reference, root=root,
                base=manifest_path.parent if manifest_path is not None else None,
                role=f"{case_id} manifest audit")
        external_candidates = evidence_by_case.get(case_id, [])
        external_payload: Mapping[str, Any] | None = None
        for candidate in external_candidates:
            candidate_schema = str(candidate.get("schema", ""))
            if candidate_schema == "core.f3.legacy_hard_audit_adapter.v1":
                continue
            if _family(candidate) == family or _family(candidate) is None:
                external_payload = candidate
                break
        # Adapter rows were resolved only after their top-level manifest hash
        # and, for structural receipts, their referenced receipt hash passed.
        adapter_payload = bound_adapter_cases.get(case_id)
        external_payload = adapter_payload or external_payload

        hard_direct, structural_direct = _audit_markers(direct_payload or {})
        hard_external, structural_external = _audit_markers(external_payload or {})
        hash_verified = direct_error is None if audit_reference is not None else False
        identity_direct = _audit_identity(direct_payload, row) if direct_payload else False
        identity_external = _audit_identity(external_payload, row) if external_payload else False
        hard_bound = hard_direct is True or hard_external is True
        structural_bound = structural_direct is True or structural_external is True
        identity_bound = identity_direct or identity_external
        if external_payload is not None and adapter_payload is not None:
            # The adapter is already bound to the manifest by its top-level
            # hash.  It remains an external receipt, not a rewritten row.
            hash_verified = hash_verified or (adapter_present and identity_external)
        formal_audit_pass = bool(hash_verified and identity_bound and hard_bound and structural_bound)
        status = "passed" if formal_audit_pass else "audit_gap"
        if direct_error is not None:
            status = "audit_binding_error"
        if _is_qualification(row):
            status = "qualification_excluded"
        case_observations.append({
            "case_id": case_id,
            "family": family,
            "split": split,
            "denominator_included": not _is_qualification(row),
            "manifest_path": source_record["path"],
            "direct_audit": {
                "reference_present": audit_reference is not None,
                "hash_verified": bool(hash_verified if direct_payload else False),
                "hard_integrity_pass": hard_direct,
                "structural_pass": structural_direct,
                "identity_bound": identity_direct,
                "reference": direct_ref,
                "error": direct_error,
            },
            "external_audit": {
                "reference_present": external_payload is not None,
                "adapter_bound": bool(adapter_payload is not None and adapter_present),
                "hard_integrity_pass": hard_external,
                "structural_pass": structural_external,
                "identity_bound": identity_external,
            },
            "hard_integrity_pass_bound": hard_bound,
            "structural_pass_bound": structural_bound,
            "formal_audit_pass": formal_audit_pass,
            "status": status,
        })

    denominator_rows = [item for item in case_observations if item["denominator_included"]]
    families = sorted({item["family"] for item in denominator_rows})
    family_counts = Counter(item["family"] for item in denominator_rows)
    validation_counts = Counter(item["family"] for item in denominator_rows
                                if item["split"] == "validation")
    raw_split_counts = {
        family: Counter(item["split"] for item in denominator_rows
                        if item["family"] == family)
        for family in families
    }
    split_counts: dict[str, dict[str, int]] = {}
    split_shape_mismatches: dict[str, dict[str, Any]] = {}
    for family in families:
        raw = raw_split_counts[family]
        test_count = sum(raw.get(name, 0) for name in ("test", "id_test", "ood_test"))
        split_counts[family] = {
            "train": raw.get("train", 0),
            "validation": raw.get("validation", 0),
            "test": test_count,
            **{name: raw[name] for name in sorted(raw)
               if name not in {"train", "validation", "test", "id_test", "ood_test"}},
        }
        observed_shape = split_counts[family]
        required_shape = {
            "total": CASES_PER_FAMILY,
            "train": TRAIN_CASES_PER_FAMILY,
            "validation": VALIDATION_CASES_PER_FAMILY,
            "test": TEST_CASES_PER_FAMILY,
        }
        if (family_counts[family] != CASES_PER_FAMILY
                or any(observed_shape.get(key, 0) != value
                       for key, value in required_shape.items()
                       if key != "total")):
            split_shape_mismatches[family] = {
                "observed": {"total": family_counts[family], **observed_shape},
                "required": required_shape,
            }
    hard_count = sum(item["hard_integrity_pass_bound"] for item in denominator_rows)
    structural_count = sum(item["structural_pass_bound"] for item in denominator_rows)
    formal_audit_count = sum(item["formal_audit_pass"] for item in denominator_rows)
    audit_gap_cases = sorted(item["case_id"] for item in denominator_rows
                             if not item["formal_audit_pass"])
    hard_gap_cases = sorted(item["case_id"] for item in denominator_rows
                            if not item["hard_integrity_pass_bound"])
    structural_gap_cases = sorted(item["case_id"] for item in denominator_rows
                                  if not item["structural_pass_bound"])

    # Family-level T1 records are intentionally separate from per-case audit
    # receipts.  They may qualify a family only when the family and scope are
    # explicit; no success is inferred from a manifest's formal_release bit.
    t1_families: dict[str, bool] = {family: False for family in families}
    for evidence_row in evidence_global:
        family = _family(evidence_row)
        if family not in t1_families or evidence_row.get("T1_numerical") is not True:
            continue
        scope = _scope(evidence_row)
        family_scopes = {_scope(row) for row, _, _ in all_rows if _family(row) == family}
        if scope is not None and scope in family_scopes:
            t1_families[family] = True

    closure = _source_closure(
        code, _resolve(preprofile_index, root=root) if preprofile_index is not None else None, root)
    capacity = _capacity_evidence_observation(
        _resolve(capacity_evidence, root=root)
        if isinstance(capacity_evidence, (str, Path)) else capacity_evidence,
        root=root, manifest_hashes=manifest_hashes)
    resource = _resource_observation(
        _resolve(resource_profile, root=root) if resource_profile is not None else None,
        root=root, capacity=capacity)
    dryrun = _resource_dryrun_observation(
        _resolve(resource_dryrun, root=root) if resource_dryrun is not None else None, root=root)
    graph = _graph_probe_observation(
        _resolve(graph_probe, root=root) if graph_probe is not None else None, root=root)
    formal_release_sources = [record["path"] for record in source_records
                              if record.get("formal_release") is not True]
    blockers: list[dict[str, Any]] = []
    if manifest_errors:
        blockers.append(_blocker("MANIFEST_CONTRACT_INVALID", "one or more reader manifests failed the JSON contract",
                                 observed=manifest_errors))
    if formal_release_sources:
        blockers.append(_blocker(
            "FORMAL_RELEASE_REQUIRED",
            "every source reader manifest must declare formal_release=true; this audit never upgrades it",
            observed=formal_release_sources, required="all source manifests formal_release=true"))
    if duplicate_case_ids:
        blockers.append(_blocker(
            "MANIFEST_DUPLICATE_CASE_ID",
            "the formal production denominator requires each case_id exactly once across all source manifests",
            observed=duplicate_case_ids,
            required="unique case_id across the complete manifest set",
            scope="manifest"))
    t1_family_count = sum(value is True for value in t1_families.values())
    if t1_family_count < REQUIRED_FAMILIES:
        blockers.append(_blocker(
            "THIRD_FAMILY_REQUIRED",
            "formal training requires three distinct T1 families with validation cases",
            observed=t1_family_count, required=REQUIRED_FAMILIES))
    if split_shape_mismatches:
        blockers.append(_blocker(
            "SPLIT_SHAPE_REQUIRED",
            "every production family must contain 16 train, 4 validation, and 12 test cases",
            observed=split_shape_mismatches,
            required={"train": TRAIN_CASES_PER_FAMILY,
                      "validation": VALIDATION_CASES_PER_FAMILY,
                      "test": TEST_CASES_PER_FAMILY,
                      "total": CASES_PER_FAMILY}))
    if sum(validation_counts.values()) < REQUIRED_VALIDATION_CASES:
        blockers.append(_blocker(
            "VALIDATION_DENOMINATOR",
            "formal validation requires twelve cases, four per family",
            observed=sum(validation_counts.values()), required=REQUIRED_VALIDATION_CASES))
    undersized = {
        family: validation_counts.get(family, 0)
        for family in families
        if validation_counts.get(family, 0) < VALIDATION_CASES_PER_FAMILY
    }
    if undersized:
        blockers.append(_blocker(
            "VALIDATION_PER_FAMILY",
            "every formal family needs four validation cases",
            observed=undersized, required=VALIDATION_CASES_PER_FAMILY))
    if hard_gap_cases:
        blockers.append(_blocker(
            "HARD_AUDIT_GAP",
            "production rows lack an explicit bound hard_integrity_pass=true receipt",
            observed=hard_count, required=len(denominator_rows), cases=hard_gap_cases))
    if structural_gap_cases:
        blockers.append(_blocker(
            "STRUCTURAL_AUDIT_GAP",
            "production rows lack an explicit bound structural_pass=true receipt",
            observed=structural_count, required=len(denominator_rows), cases=structural_gap_cases))
    if adapter_binding_errors:
        blockers.append(_blocker(
            "STRUCTURAL_RECEIPT_BINDING_GAP",
            "one or more bound structural receipt references failed path/hash/schema checks",
            observed=adapter_binding_errors, required="every structural receipt reference verifies",
            scope="evidence"))
    if audit_gap_cases and not hard_gap_cases and not structural_gap_cases:
        blockers.append(_blocker(
            "AUDIT_BINDING_GAP",
            "production audit receipts are not identity/hash bound to their manifest rows",
            observed=formal_audit_count, required=len(denominator_rows), cases=audit_gap_cases))
    if closure.get("missing_files"):
        blockers.append(_blocker(
            "SOURCE_CLOSURE_INCOMPLETE",
            "the current eight-file learning source closure is incomplete",
            observed=closure["missing_files"], required=list(REQUIRED_CODE_FILES)))
    if closure.get("preprofile") is not None and not closure.get("preprofile_source_closure_match"):
        blockers.append(_blocker(
            "STALE_SOURCE_CLOSURE",
            "existing diagnostic preprofile evidence was produced under a different source closure",
            observed=closure.get("preprofile_mismatch_count"), required=0,
            scope="evidence"))
    if not (
        resource.get("formal_capacity_evidence") is True
        and capacity.get("valid") is True
    ):
        blockers.append(_blocker(
            "RESOURCE_FRONTIER_UNPROVEN",
            "formal admission requires explicit valid full-field 32000-update capacity evidence",
            observed={
                "resource_profile_bound": resource.get("bound") is True,
                "resource_formal_capacity_evidence": resource.get("formal_capacity_evidence"),
                "capacity_evidence_bound": capacity.get("bound") is True,
                "capacity_evidence_valid": capacity.get("valid") is True,
                "observed_update_frontier": capacity.get("observed_update_frontier"),
            },
            required={
                "resource_formal_capacity_evidence": True,
                "capacity_evidence_valid": True,
                "observed_update_frontier": FORMAL_UPDATES,
            },
            scope="resource"))
    if capacity.get("bound") and not capacity.get("valid"):
        blockers.append(_blocker(
            "RESOURCE_CAPACITY_EVIDENCE_INVALID",
            "the supplied real-capacity adapter record failed its hash, checkpoint, or execution contract",
            observed=capacity.get("path"),
            required="valid core.formal_capacity_evidence.v1",
            scope="resource"))
    if dryrun.get("bound") and not dryrun.get("valid"):
        blockers.append(_blocker(
            "RESOURCE_DRYRUN_INVALID",
            "the supplied resource frontier dry-run is not a valid non-formal 32000-update receipt",
            observed=dryrun.get("path"), required="valid core.formal_resource_dryrun.v1",
            scope="resource"))
    if graph.get("bound") and not graph.get("valid"):
        blockers.append(_blocker(
            "GRAPH_PROBE_INVALID",
            "the supplied full-field graph capacity probe is not a valid non-formal diagnostic receipt",
            observed=graph.get("path"), required="valid core.formal_graph_capacity_probe.v1",
            scope="resource"))

    return {
        "schema": SCHEMA,
        "record_id": "core-formal-admission-f3-f4-20260920",
        "purpose": "Read-only cross-manifest admission audit; no formal jobs are emitted.",
        "qualification_claim": "none",
        "status": "ready" if not blockers else "blocked",
        "formal_admission": not blockers,
        "formal_job_count": 0,
        "required_formal_job_count": FORMAL_JOB_COUNT,
        "formal_protocol": {
            "models": list(FORMAL_MODELS),
            "seeds": list(FORMAL_SEEDS),
            "model_seed_product_count": FORMAL_JOB_COUNT,
            "updates": FORMAL_UPDATES,
            "validation_cases_required": REQUIRED_VALIDATION_CASES,
            "validation_cases_per_family_required": VALIDATION_CASES_PER_FAMILY,
            "test_included": False,
        },
        "diagnostic_exclusion": {
            "diagnostic_job_count": DIAGNOSTIC_JOB_COUNT,
            "diagnostic_runs_counted_as_formal": False,
            "formal_job_count": 0,
            "profile_is_diagnostic_only": bool(resource.get("diagnostic_only", True)),
        },
        "manifests": source_records,
        "evidence": evidence_records,
        "evidence_binding_errors": adapter_binding_errors,
        "family_summary": {
            "families": families,
            "family_counts": dict(sorted(family_counts.items())),
            "validation_counts": dict(sorted(validation_counts.items())),
            "split_counts": dict(sorted(split_counts.items())),
            "split_shape_mismatches": split_shape_mismatches,
            "t1_families": dict(sorted(t1_families.items())),
            "t1_family_count": t1_family_count,
        },
        "production_denominator": {
            "included_case_count": len(denominator_rows),
            "manifest_case_count": len(all_rows),
            "qualification_excluded_case_count": len(all_rows) - len(denominator_rows),
            "failed_or_unresolved_case_count": len(audit_gap_cases),
            "hard_integrity_pass_bound_count": hard_count,
            "structural_pass_bound_count": structural_count,
            "formal_audit_pass_count": formal_audit_count,
            "audit_gap_case_ids": audit_gap_cases,
            "hard_gap_case_ids": hard_gap_cases,
            "structural_gap_case_ids": structural_gap_cases,
            "failure_denominator_preserved": True,
        },
        "case_observations": case_observations,
        "source_closure": closure,
        "resource_profile": resource,
        "capacity_evidence": capacity,
        "resource_dryrun": dryrun,
        "graph_probe": graph,
        "blockers": sorted(blockers, key=lambda item: (item["scope"], item["code"])),
        "execution_constraints": {
            "read_only": True,
            "trajectory_files_opened": False,
            "future_state_inputs": False,
            "formal_runs_started": 0,
            "gpu_started": False,
            "solver_started": False,
            "submitted": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "manifest_written": False,
            "formal_specs_written": False,
        },
        "duplicate_case_ids": duplicate_case_ids,
        "physical_split_violations": sorted(set(duplicate_physical)),
        "lineage_split_violations": sorted(set(duplicate_lineage)),
        "admission_next_dependency": (
            "release a third independently qualified T1 family, publish formal_release=true for every source, "
            "regenerate stale diagnostic preprofile evidence under the current source closure, and produce "
            "real 32000-update full-field graph checkpoint/IO evidence before re-running the planner"
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path) -> None:
    """Write a conventional sidecar digest without changing the report."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", required=True,
                        help="reader manifest; repeat for each family")
    parser.add_argument("--evidence", action="append", default=[],
                        help="hash-bound qualification or per-case audit evidence")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--code-root", type=Path)
    parser.add_argument("--preprofile-index", type=Path)
    parser.add_argument("--resource-profile", type=Path)
    parser.add_argument("--resource-dryrun", type=Path,
                        help="optional completed non-formal resource frontier probe")
    parser.add_argument("--graph-probe", type=Path,
                        help="optional bounded full-field graph capacity probe")
    parser.add_argument("--capacity-evidence", type=Path,
                        help="optional real 32000-update capacity adapter record")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256-output", type=Path,
                        help="optional sidecar SHA-256 file for --output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_admission(
        args.manifest, data_root=args.data_root, evidence=args.evidence,
        code_root=args.code_root, preprofile_index=args.preprofile_index,
        resource_profile=args.resource_profile, resource_dryrun=args.resource_dryrun,
        graph_probe=args.graph_probe, capacity_evidence=args.capacity_evidence)
    write_json(args.output, report)
    if args.sha256_output is not None:
        write_sha256(args.sha256_output, source=args.output)
    print(json.dumps({"status": report["status"],
                      "formal_job_count": report["formal_job_count"],
                      "required_formal_job_count": report["required_formal_job_count"],
                      "blocker_codes": [item["code"] for item in report["blockers"]]},
                     sort_keys=True))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
