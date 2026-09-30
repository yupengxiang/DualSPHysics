#!/usr/bin/env python3
"""Evidence-bound DS-DATA-02 production-scope validator.

This module validates a *dataset scope* against frozen scope rules and actual,
hash-bound evidence files.  It deliberately does not maintain the campaign
approved index, does not assign a production approval, and does not infer a
qualification from a boolean marker.  The returned verdict says only whether
the supplied evidence is eligible for root's separate scope decision.

The input contract is intentionally explicit:

* ``ds-data-02.scope-spec.v1`` freezes the physical cases, splits, resolutions,
  recipe/schema, time domain, observations, physical scales, error budget and
  required integration/save comparisons.
* ``ds-data-02.scope-evidence.v1`` binds current full-state Q-I evidence,
  two-background three-resolution reference evidence, and independent actual
  integration/save evidence to those frozen rules.
* every referenced JSON/HDF5/log/input artifact is checked by SHA-256 at
  validation time.  A path or a self-declared ``qualified=true`` is never
  evidence by itself.

Q-E, other-family material, tracers and models are intentionally ignored by
this validator.  They cannot rescue or block the dataset-only verdict.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


SCOPE_SCHEMA = "ds-data-02.scope-spec.v1"
EVIDENCE_SCHEMA = "ds-data-02.scope-evidence.v1"
VERDICT_SCHEMA = "ds-data-02.scope-verdict.v1"
CURRENT_EVIDENCE_CLASS = "current_scope_evidence"
FULL_STATE_COVERAGE = "full_typed_state"
PASS_QI_STATUSES = {"Q-I-structure-pass", "Q-I-pass"}
PASS_REFERENCE_STATUS = {"actual_reference_pass"}
PASS_COMPARISON_STATUS = {"actual_pass", "actual_complete"}
HASH_ALGORITHM = "sha256"
REQUIRED_SCOPE_INPUT_ROLES = {
    "quality_contract",
    "event_definitions",
    "case_registry",
    "reference_matrix",
}
REQUIRED_TYPED_DATASETS = {
    "time",
    "position",
    "velocity",
    "density",
    "mass",
    "type",
    "valid",
    "particle_id",
    "particle_zone",
    "rigid_body_state",
}
FORBIDDEN_TRUE_MARKER_KEYS = {"qualified", "production_eligible"}
IGNORED_INPUT_ROOTS = {"q_e", "other_family_evidence", "material_tracer", "model", "model_or_prediction"}


class ScopeInputError(ValueError):
    """Raised when a scope or evidence document cannot be read safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScopeInputError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    """Read a JSON object and return it with the exact source hash."""

    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise ScopeInputError(f"JSON input is missing: {candidate}")
    resolved = candidate.resolve()
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScopeInputError(f"invalid JSON: {resolved}: {error}") from error
    if not isinstance(value, dict):
        raise ScopeInputError(f"JSON root must be an object: {resolved}")
    return value, resolved, hashlib.sha256(raw).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _resolve_path(path_value: Any, base_dir: Path, data_root: Path | None) -> Path | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (data_root if data_root is not None else base_dir) / path
    return path.resolve()


def _fail(errors: list[dict[str, Any]], code: str, message: str, **details: Any) -> None:
    record: dict[str, Any] = {"code": code, "message": message}
    if details:
        record["details"] = _jsonable(details)
    errors.append(record)


def _check_artifact(
    binding: Any,
    *,
    base_dir: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
    label: str,
    require_role: bool = True,
) -> dict[str, Any] | None:
    """Check one ``{role,path,sha256}`` binding and remember its actual hash."""

    if not isinstance(binding, Mapping):
        _fail(errors, "artifact_binding_not_object", f"{label} must be an object")
        return None
    role = binding.get("role")
    if require_role and not _nonempty_string(role):
        _fail(errors, "artifact_role_missing", f"{label} has no role")
    path_value = binding.get("path")
    expected = binding.get("sha256")
    if not _nonempty_string(path_value):
        _fail(errors, "artifact_path_empty", f"{label} has an empty path")
        return None
    if not _sha_string(expected):
        _fail(errors, "artifact_hash_invalid", f"{label} must carry a lowercase SHA-256 hash")
        return None
    resolved = _resolve_path(path_value, base_dir, data_root)
    if resolved is None or not resolved.is_file():
        _fail(errors, "artifact_missing", f"{label} does not point to a file", path=str(resolved or path_value))
        return None
    try:
        actual = sha256_file(resolved)
    except OSError as error:
        _fail(errors, "artifact_unreadable", f"{label} could not be hashed: {error}", path=str(resolved))
        return None
    if actual != expected:
        _fail(errors, "artifact_hash_mismatch", f"{label} hash does not match bytes on disk", path=str(resolved), expected=expected, actual=actual)
    key = str(resolved)
    previous = bound_artifacts.get(key)
    if previous is not None and previous["actual_sha256"] != actual:
        _fail(errors, "artifact_hash_inconsistent", f"artifact was bound with two different actual hashes", path=key)
    bound_artifacts[key] = {
        "path": key,
        "role": str(role or ""),
        "declared_sha256": expected,
        "actual_sha256": actual,
        "bytes": resolved.stat().st_size,
    }
    return bound_artifacts[key]


def _check_bindings(
    bindings: Any,
    *,
    base_dir: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
    label: str,
    minimum: int = 1,
) -> list[dict[str, Any]]:
    entries = _binding_entries(bindings)
    if len(entries) < minimum:
        _fail(errors, "artifact_bindings_incomplete", f"{label} needs at least {minimum} nonempty artifact bindings")
        return []
    checked: list[dict[str, Any]] = []
    for index, binding in enumerate(entries):
        result = _check_artifact(
            binding,
            base_dir=base_dir,
            data_root=data_root,
            errors=errors,
            bound_artifacts=bound_artifacts,
            label=f"{label}[{index}]",
        )
        if result is not None:
            checked.append(result)
    return checked


def _binding_entries(bindings: Any) -> list[Any]:
    """Normalize list bindings and role-keyed source-binding maps.

    Campaign manifests commonly use a list, while the converter/Q-I reports
    use ``{"trajectory_h5": {"path": ..., "sha256": ...}}``.  Both forms
    are accepted, but every entry still has to carry an explicit hash before
    it can contribute evidence.
    """

    if isinstance(bindings, list):
        return list(bindings)
    if isinstance(bindings, Mapping):
        normalized: list[Any] = []
        for role, item in bindings.items():
            if isinstance(item, Mapping):
                entry = dict(item)
                entry.setdefault("role", str(role))
                normalized.append(entry)
            else:
                # Keep a malformed item visible to _check_artifact so it is
                # reported as a binding error rather than silently omitted.
                normalized.append({"role": str(role), "path": item})
        return normalized
    return []


def _require_binding_roles(
    bindings: Any,
    roles: set[str],
    *,
    label: str,
    errors: list[dict[str, Any]],
) -> None:
    present = {str(item.get("role")) for item in _binding_entries(bindings)}
    missing = sorted(roles - present)
    if missing:
        _fail(errors, "artifact_roles_missing", f"{label} is missing required source roles", missing_roles=missing)


def _mapping(value: Any, label: str, errors: list[dict[str, Any]]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        _fail(errors, "mapping_required", f"{label} must be a nonempty object")
        return None
    if not value:
        _fail(errors, "mapping_empty", f"{label} must not be empty")
    return value


def _list(value: Any, label: str, errors: list[dict[str, Any]], minimum: int = 1) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        _fail(errors, "list_incomplete", f"{label} must contain at least {minimum} entries")
        return []
    return value


def _check_true_fields(mapping: Mapping[str, Any], fields: Sequence[str], label: str, errors: list[dict[str, Any]]) -> None:
    for field in fields:
        if mapping.get(field) is not True:
            _fail(errors, "required_evidence_check_failed", f"{label}.{field} is not true")


def _check_finite_positive(mapping: Mapping[str, Any], field: str, label: str, errors: list[dict[str, Any]], *, allow_zero: bool = False) -> None:
    value = mapping.get(field)
    if not _finite_number(value) or (float(value) < 0 if allow_zero else float(value) <= 0):
        _fail(errors, "numeric_evidence_invalid", f"{label}.{field} must be finite and positive", value=value)


def _find_forbidden_markers(value: Any, path: str = "", *, ignored_roots: set[str] | None = None) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if not path and str(key) in (ignored_roots or set()):
                continue
            if key in FORBIDDEN_TRUE_MARKER_KEYS and item is True:
                found.append(item_path)
            found.extend(_find_forbidden_markers(item, item_path, ignored_roots=ignored_roots))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_markers(item, f"{path}[{index}]", ignored_roots=ignored_roots))
    return found


def _case_identity(case: Mapping[str, Any]) -> tuple[str, str]:
    return str(case.get("case_id", "")), str(case.get("physical_case_id", ""))


def _check_scope_shape(
    scope: Mapping[str, Any],
    *,
    scope_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if scope.get("schema") != SCOPE_SCHEMA:
        _fail(errors, "scope_schema_invalid", f"scope schema must be {SCOPE_SCHEMA}")
    if scope.get("family_id") != "F2":
        _fail(errors, "scope_family_invalid", "scope family_id must be F2")
    if not _nonempty_string(scope.get("scope_id")):
        _fail(errors, "scope_id_missing", "scope_id must be nonempty")

    recipe = _mapping(scope.get("recipe"), "scope.recipe", errors)
    if recipe is not None:
        for field in ("recipe_id", "schema", "state_schema", "view_id"):
            if not _nonempty_string(recipe.get(field)):
                _fail(errors, "recipe_field_missing", f"scope.recipe.{field} must be nonempty")
        if recipe.get("solver_dimension") != 3:
            _fail(errors, "recipe_dimension_invalid", "scope recipe must freeze solver_dimension=3")

    time_domain = _mapping(scope.get("time_domain"), "scope.time_domain", errors)
    if time_domain is not None:
        start = time_domain.get("start_s")
        end = time_domain.get("end_s")
        if not _finite_number(start) or not _finite_number(end) or float(end) <= float(start):
            _fail(errors, "time_domain_invalid", "scope time domain must have finite end_s > start_s")
        if time_domain.get("complete_event_window") is not True:
            _fail(errors, "time_domain_incomplete", "scope must freeze a complete event window")
        if not isinstance(time_domain.get("minimum_frames"), int) or time_domain["minimum_frames"] < 2:
            _fail(errors, "time_frame_floor_invalid", "scope minimum_frames must be at least 2")

    observations = _mapping(scope.get("observations"), "scope.observations", errors)
    if observations is not None:
        event_names = _list(observations.get("required_event_names"), "scope.observations.required_event_names", errors)
        if any(not _nonempty_string(item) for item in event_names):
            _fail(errors, "observation_name_invalid", "observation event names must be nonempty strings")
        units = _mapping(observations.get("units"), "scope.observations.units", errors)
        if units is not None and any(not _nonempty_string(value) for value in units.values()):
            _fail(errors, "observation_units_invalid", "observation units must be nonempty")
        scales = _mapping(observations.get("physical_scale"), "scope.observations.physical_scale", errors)
        if scales is not None:
            for key in ("characteristic_length_m", "characteristic_time_s", "characteristic_velocity_m_s"):
                _check_finite_positive(scales, key, "scope.observations.physical_scale", errors)
        budget = _mapping(observations.get("error_budget"), "scope.observations.error_budget", errors)
        if budget is not None:
            for key in ("event_time_absolute_s", "macro_relative", "integration_fraction", "save_fraction"):
                _check_finite_positive(budget, key, "scope.observations.error_budget", errors)

    domain = _mapping(scope.get("physical_domain"), "scope.physical_domain", errors)
    expected_cases: list[Mapping[str, Any]] = []
    case_by_id: dict[str, Mapping[str, Any]] = {}
    physical_by_id: dict[str, Mapping[str, Any]] = {}
    parent_splits: dict[str, str] = {}
    if domain is not None:
        expected_cases = [item for item in _list(domain.get("cases"), "scope.physical_domain.cases", errors) if isinstance(item, Mapping)]
        for index, case in enumerate(expected_cases):
            case_id, physical_id = _case_identity(case)
            if not case_id or not physical_id:
                _fail(errors, "scope_case_identity_missing", f"scope physical case {index} needs case_id and physical_case_id")
            if case_id in case_by_id:
                _fail(errors, "scope_case_duplicate", f"duplicate scope case_id: {case_id}")
            case_by_id[case_id] = case
            if physical_id in physical_by_id:
                _fail(errors, "scope_physical_case_duplicate", f"duplicate physical_case_id: {physical_id}")
            physical_by_id[physical_id] = case
            parent = case.get("parent_group_id")
            split = case.get("split")
            if not _nonempty_string(parent) or not _nonempty_string(split):
                _fail(errors, "scope_split_identity_missing", f"scope case {case_id} needs parent_group_id and split")
            elif parent in parent_splits and parent_splits[parent] != split:
                _fail(errors, "scope_parent_split_leak", f"parent group {parent} spans multiple splits")
            else:
                parent_splits[str(parent)] = str(split)
            for field in ("background", "mechanism_id", "geometry_family_id", "control_family_id", "physical_condition_hash"):
                if not _nonempty_string(case.get(field)):
                    _fail(errors, "scope_case_field_missing", f"scope case {case_id}.{field} is missing")
            if not _sha_string(case.get("physical_condition_hash")):
                _fail(errors, "scope_physical_hash_invalid", f"scope case {case_id} physical_condition_hash is invalid")
            settings = _mapping(case.get("numeric_settings_by_resolution"), f"scope case {case_id}.numeric_settings_by_resolution", errors)
            resolutions = case.get("resolution_views")
            if not isinstance(resolutions, list) or not resolutions:
                _fail(errors, "scope_resolution_views_missing", f"scope case {case_id} needs resolution_views")
            else:
                if settings is not None and set(settings) != set(resolutions):
                    _fail(errors, "scope_resolution_settings_mismatch", f"scope case {case_id} settings must cover exactly its resolution_views")
                for resolution in resolutions:
                    if not _nonempty_string(resolution):
                        _fail(errors, "scope_resolution_invalid", f"scope case {case_id} has an empty resolution")
                    elif settings is not None and not isinstance(settings.get(resolution), Mapping):
                        _fail(errors, "scope_numeric_settings_empty", f"scope case {case_id} resolution {resolution} lacks numeric settings")
                    recipe_hashes = case.get("numerical_recipe_hash_by_resolution", {})
                    if not isinstance(recipe_hashes, Mapping) or not _sha_string(recipe_hashes.get(resolution)):
                        _fail(errors, "scope_numerical_hash_missing", f"scope case {case_id} resolution {resolution} lacks numerical_recipe_hash")
            if not isinstance(resolutions, list) or case.get("qi_resolution") not in resolutions:
                _fail(errors, "scope_qi_resolution_invalid", f"scope case {case_id} qi_resolution must be one of its resolution_views")
            for field in ("geometry", "control", "parameter_values"):
                if not isinstance(case.get(field), Mapping) or not case[field]:
                    _fail(errors, "scope_case_semantics_missing", f"scope case {case_id}.{field} must be nonempty")
            _check_bindings(
                case.get("input_bindings"),
                base_dir=scope_path.parent,
                data_root=data_root,
                errors=errors,
                bound_artifacts=bound_artifacts,
                label=f"scope case {case_id}.input_bindings",
                minimum=2,
            )

    reference = _mapping(scope.get("reference_requirements"), "scope.reference_requirements", errors)
    reference_backgrounds: list[str] = []
    reference_resolutions: list[str] = []
    reference_case_ids: dict[str, str] = {}
    if reference is not None:
        reference_backgrounds = [str(x) for x in _list(reference.get("backgrounds"), "scope.reference_requirements.backgrounds", errors)]
        reference_resolutions = [str(x) for x in _list(reference.get("resolutions"), "scope.reference_requirements.resolutions", errors)]
        if len(set(reference_backgrounds)) != len(reference_backgrounds) or len(set(reference_resolutions)) != len(reference_resolutions):
            _fail(errors, "reference_domain_duplicate", "reference backgrounds/resolutions must be unique")
        expected_count = len(reference_backgrounds) * len(reference_resolutions)
        if reference.get("expected_view_count") != expected_count:
            _fail(errors, "reference_count_invalid", "reference expected_view_count must equal backgrounds x resolutions")
        if len(reference_backgrounds) != 2 or set(reference_backgrounds) != {"center_catch", "offset_spill"}:
            _fail(errors, "reference_background_domain_invalid", "F2 scope requires center_catch and offset_spill references")
        if len(reference_resolutions) != 3:
            _fail(errors, "reference_resolution_domain_invalid", "F2 scope requires three spatial reference resolutions")
        declared_reference_cases = reference.get("reference_case_ids")
        if isinstance(declared_reference_cases, Mapping):
            reference_case_ids = {str(key): str(value) for key, value in declared_reference_cases.items()}
            if set(reference_case_ids) != set(reference_backgrounds):
                _fail(errors, "reference_case_domain_invalid", "reference_case_ids must cover every required background exactly")
            for background, case_id in reference_case_ids.items():
                if case_id not in case_by_id or case_by_id[case_id].get("background") != background:
                    _fail(errors, "reference_case_domain_invalid", f"reference case {case_id} does not belong to background {background}")
        else:
            for background in reference_backgrounds:
                matches = [case for case in expected_cases if case.get("background") == background]
                if len(matches) != 1:
                    _fail(errors, "reference_case_domain_ambiguous", "scope must declare reference_case_ids when a background has multiple production cases")
                elif matches:
                    reference_case_ids[background] = str(matches[0].get("case_id"))

    comparison_requirements = _list(scope.get("comparison_requirements"), "scope.comparison_requirements", errors)
    comparison_ids: set[str] = set()
    comparison_kinds: set[str] = set()
    comparison_kinds_by_background: dict[str, set[str]] = {}
    for index, requirement in enumerate(comparison_requirements):
        if not isinstance(requirement, Mapping):
            _fail(errors, "comparison_requirement_invalid", f"scope comparison requirement {index} must be an object")
            continue
        comparison_id = requirement.get("comparison_id")
        if not _nonempty_string(comparison_id) or comparison_id in comparison_ids:
            _fail(errors, "comparison_requirement_duplicate", f"comparison requirement {index} has a duplicate/empty comparison_id")
        comparison_ids.add(str(comparison_id))
        kind = requirement.get("kind")
        if kind not in {"integration", "save"}:
            _fail(errors, "comparison_kind_invalid", f"comparison {comparison_id} kind must be integration or save")
        comparison_kinds.add(str(kind))
        for field in ("case_id", "physical_case_id", "background"):
            if not _nonempty_string(requirement.get(field)):
                _fail(errors, "comparison_identity_missing", f"comparison {comparison_id}.{field} is missing")
        expected_case = case_by_id.get(str(requirement.get("case_id")))
        if expected_case is None:
            _fail(errors, "comparison_case_missing", f"comparison {comparison_id} references a case outside physical_domain")
        else:
            for field in ("physical_case_id", "background"):
                if requirement.get(field) != expected_case.get(field):
                    _fail(errors, "comparison_case_binding_invalid", f"comparison {comparison_id}.{field} differs from its frozen case")
        if not _nonempty_string(requirement.get("baseline_resolution")):
            _fail(errors, "comparison_baseline_resolution_missing", f"comparison {comparison_id} needs baseline_resolution")
        elif expected_case is not None and requirement.get("baseline_resolution") not in expected_case.get("resolution_views", []):
            _fail(errors, "comparison_baseline_resolution_invalid", f"comparison {comparison_id} baseline_resolution is outside its case views")
        if not isinstance(requirement.get("required_changed_numeric_fields"), list) or not requirement["required_changed_numeric_fields"]:
            _fail(errors, "comparison_changed_fields_missing", f"comparison {comparison_id} needs required_changed_numeric_fields")
        if not isinstance(requirement.get("required_statistic_fields"), list) or not requirement["required_statistic_fields"]:
            _fail(errors, "comparison_statistics_missing", f"comparison {comparison_id} needs required_statistic_fields")
        if not isinstance(requirement.get("required_observation_points"), list) or set(requirement.get("required_observation_points", [])) != {"endpoint", "internal"}:
            _fail(errors, "comparison_observation_points_invalid", f"comparison {comparison_id} must require endpoint and internal observations")
        if _nonempty_string(requirement.get("background")) and kind in {"integration", "save"}:
            comparison_kinds_by_background.setdefault(str(requirement["background"]), set()).add(str(kind))
    if comparison_kinds != {"integration", "save"}:
        _fail(errors, "comparison_kinds_incomplete", "scope must require both integration and save comparisons")
    for background in reference_backgrounds:
        if comparison_kinds_by_background.get(background) != {"integration", "save"}:
            _fail(errors, "comparison_background_incomplete", f"scope must require independent integration and save comparisons for {background}")

    declared_scope_bindings = scope.get("input_bindings")
    scope_bindings = _check_bindings(
        declared_scope_bindings,
        base_dir=scope_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="scope.input_bindings",
        minimum=len(REQUIRED_SCOPE_INPUT_ROLES),
    )
    roles = {item.get("role") for item in _binding_entries(declared_scope_bindings) if isinstance(item, Mapping)}
    missing_roles = sorted(REQUIRED_SCOPE_INPUT_ROLES - roles)
    if missing_roles:
        _fail(errors, "scope_input_roles_missing", "scope input bindings do not include required frozen contracts", missing_roles=missing_roles)

    return {
        "recipe": recipe or {},
        "time_domain": time_domain or {},
        "observations": observations or {},
        "physical_domain": domain or {},
        "cases": expected_cases,
        "case_by_id": case_by_id,
        "physical_by_id": physical_by_id,
        "reference_backgrounds": reference_backgrounds,
        "reference_resolutions": reference_resolutions,
        "reference_case_ids": reference_case_ids,
        "reference_requirements": reference or {},
        "comparison_requirements": comparison_requirements,
        "comparison_ids": comparison_ids,
        "scope_bindings": scope_bindings,
    }


def _check_scope_binding(
    evidence: Mapping[str, Any],
    *,
    scope_path: Path,
    scope_sha256: str,
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> None:
    binding = evidence.get("scope_binding")
    checked = _check_artifact(
        binding,
        base_dir=evidence_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="evidence.scope_binding",
    )
    if checked is None:
        return
    if checked["path"] != str(scope_path.resolve()):
        _fail(errors, "scope_binding_path_mismatch", "evidence.scope_binding must point to the supplied scope file")
    if checked["actual_sha256"] != scope_sha256:
        _fail(errors, "scope_binding_hash_mismatch", "evidence.scope_binding does not match supplied scope bytes")


def _validate_recipe_identity(
    record: Mapping[str, Any],
    expected_recipe: Mapping[str, Any],
    label: str,
    errors: list[dict[str, Any]],
) -> None:
    recipe = record.get("recipe")
    if not isinstance(recipe, Mapping) or _canonical(recipe) != _canonical(expected_recipe):
        _fail(errors, "recipe_identity_mismatch", f"{label}.recipe differs from frozen scope recipe")


def _validate_reuse_equivalence(
    reuse: Any,
    *,
    scope: Mapping[str, Any],
    scope_info: Mapping[str, Any],
    scope_sha256: str,
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> None:
    """Validate explicit equivalence before allowing an old result to be reused.

    A strict flag alone is a self-assertion.  The reusable result must bind the
    exact current scope bytes, recipe, time domain and physical case IDs, and
    provide a separately hashed equivalence report.  This keeps an old
    qualified label from silently carrying a different geometry or population
    into the current dataset.
    """

    if not isinstance(reuse, Mapping) or reuse.get("strict_scope_equivalence") is not True:
        _fail(errors, "reuse_equivalence_missing", "reused evidence needs an explicit strict_scope_equivalence declaration")
        return
    if reuse.get("source_state_coverage") != FULL_STATE_COVERAGE:
        _fail(errors, "reuse_fluid_only_forbidden", "old fluid-only HDF5 cannot be reused as full-state delivery")
    expected_case_ids = sorted(str(case.get("case_id")) for case in scope_info["cases"])
    if reuse.get("scope_id") != scope.get("scope_id"):
        _fail(errors, "reuse_scope_identity_mismatch", "reused evidence scope_id differs from the supplied frozen scope")
    if reuse.get("scope_sha256") != scope_sha256:
        _fail(errors, "reuse_scope_hash_mismatch", "reused evidence does not bind the supplied frozen scope bytes")
    if _canonical(reuse.get("recipe")) != _canonical(scope_info["recipe"]):
        _fail(errors, "reuse_recipe_mismatch", "reused evidence recipe differs from the frozen scope recipe")
    if _canonical(reuse.get("time_domain")) != _canonical(scope_info["time_domain"]):
        _fail(errors, "reuse_time_domain_mismatch", "reused evidence time domain differs from the frozen scope")
    if sorted(str(item) for item in reuse.get("physical_case_ids", [])) != expected_case_ids:
        _fail(errors, "reuse_case_domain_mismatch", "reused evidence physical_case_ids differ from the frozen scope")
    _check_bindings(
        reuse.get("equivalence_evidence"),
        base_dir=evidence_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="evidence.reuse.equivalence_evidence",
        minimum=1,
    )


def _validate_full_state_qi(
    qi: Any,
    *,
    expected_case: Mapping[str, Any],
    scope_info: Mapping[str, Any],
    base_dir: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
    label: str,
) -> None:
    if not isinstance(qi, Mapping):
        _fail(errors, "qi_missing", f"{label} must be an object")
        return
    if qi.get("evidence_class") != CURRENT_EVIDENCE_CLASS:
        _fail(errors, "qi_evidence_class_invalid", f"{label} is not current scope evidence")
    if qi.get("state_coverage") != FULL_STATE_COVERAGE:
        _fail(errors, "qi_state_coverage_invalid", f"{label} must cover full typed state")
    if qi.get("status") not in PASS_QI_STATUSES:
        _fail(errors, "qi_status_invalid", f"{label}.status is not an actual Q-I pass")
    if qi.get("resolution") != expected_case.get("qi_resolution"):
        _fail(errors, "qi_resolution_mismatch", f"{label}.resolution differs from the frozen Q-I resolution")
    _check_artifact(qi.get("evidence_file"), base_dir=base_dir, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.evidence_file")
    _check_bindings(qi.get("source_bindings"), base_dir=base_dir, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.source_bindings", minimum=1)
    if qi.get("solver_dimension") != 3 or qi.get("coordinate_components") != 3:
        _fail(errors, "qi_dimension_invalid", f"{label} must bind actual 3-D solver and coordinates")
    _check_finite_positive(qi, "fluid_count", label, errors)
    _check_finite_positive(qi, "active_mass_kg", label, errors)
    checks = qi.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        _fail(errors, "qi_checks_empty", f"{label}.checks must contain actual checks")
    else:
        _check_true_fields(checks, (
            "solver_log_explicit_3d", "nonzero_fluid", "positive_active_mass",
            "time_axis", "active_state_finite", "typed_ids", "moving_boundary_pose",
            "boundary_mass_separated", "event_ids_typed", "physical_spill_separated_from_unknown",
        ), f"{label}.checks", errors)
    timeline = _mapping(qi.get("full_timeline"), f"{label}.full_timeline", errors)
    expected_time = scope_info["time_domain"]
    if timeline is not None:
        if timeline.get("complete") is not True or timeline.get("time_axis_strictly_increasing") is not True:
            _fail(errors, "qi_timeline_incomplete", f"{label} does not prove a complete increasing timeline")
        if not isinstance(timeline.get("frames"), int) or timeline["frames"] < expected_time.get("minimum_frames", 2):
            _fail(errors, "qi_timeline_frame_floor", f"{label} has fewer than the frozen minimum frames")
        for field in ("start_s", "end_s"):
            if not _finite_number(timeline.get(field)) or float(timeline[field]) != float(expected_time.get(field)):
                _fail(errors, "qi_timeline_bound_mismatch", f"{label}.full_timeline.{field} differs from frozen scope")
    typed = _mapping(qi.get("typed_identity"), f"{label}.typed_identity", errors)
    if typed is not None:
        if typed.get("axis") != "(Zone,Idp)" or typed.get("introduced_count") != 0 or typed.get("revived_count") != 0 or typed.get("type_changed_count") != 0:
            _fail(errors, "qi_typed_lifecycle_invalid", f"{label} has an incomplete typed lifecycle")
        datasets = set(typed.get("datasets", [])) if isinstance(typed.get("datasets"), list) else set()
        missing = sorted(REQUIRED_TYPED_DATASETS - datasets)
        if missing:
            _fail(errors, "qi_full_state_datasets_missing", f"{label} is not full typed state", missing=missing)
    moving = _mapping(qi.get("moving_boundary"), f"{label}.moving_boundary", errors)
    if moving is not None:
        _check_finite_positive(moving, "node_count", f"{label}.moving_boundary", errors)
        if moving.get("pose_saved") is not True or moving.get("control_bound") is not True:
            _fail(errors, "qi_moving_boundary_unbound", f"{label} lacks actual saved moving-boundary pose/control")
        _check_finite_positive(moving, "position_rms_max_m", f"{label}.moving_boundary", errors, allow_zero=True)
    mass = _mapping(qi.get("mass_audit"), f"{label}.mass_audit", errors)
    if mass is not None:
        _check_finite_positive(mass, "initial_fluid_mass_kg", f"{label}.mass_audit", errors)
        if mass.get("boundary_mass_separated") is not True or mass.get("unknown_separate_from_spill") is not True:
            _fail(errors, "qi_mass_semantics_invalid", f"{label} mixes boundary, unknown and physical spill mass")
    observations = scope_info["observations"]
    observed_names = qi.get("observed_event_names")
    required_names = observations.get("required_event_names", [])
    if not isinstance(observed_names, list) or set(observed_names) != set(required_names):
        _fail(errors, "qi_observations_incomplete", f"{label} does not bind every frozen observation definition")


def _expected_case_for_background(scope_info: Mapping[str, Any], background: str) -> Mapping[str, Any] | None:
    matches = [case for case in scope_info["cases"] if case.get("background") == background]
    return matches[0] if len(matches) == 1 else None


def _validate_case_rows(
    evidence: Mapping[str, Any],
    *,
    scope_info: Mapping[str, Any],
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    rows = _list(evidence.get("cases"), "evidence.cases", errors)
    expected_by_id = scope_info["case_by_id"]
    seen: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        label = f"evidence.cases[{index}]"
        if not isinstance(row, Mapping):
            _fail(errors, "case_evidence_invalid", f"{label} must be an object")
            continue
        case_id = row.get("case_id")
        if not _nonempty_string(case_id) or case_id in seen:
            _fail(errors, "case_evidence_duplicate", f"{label} has a duplicate/empty case_id")
            continue
        seen[str(case_id)] = row
        expected = expected_by_id.get(str(case_id))
        if expected is None:
            _fail(errors, "case_outside_scope", f"{label} is outside the frozen physical domain", case_id=case_id)
            continue
        for field in ("physical_case_id", "parent_group_id", "background", "mechanism_id", "split", "geometry_family_id", "control_family_id", "physical_condition_hash"):
            if row.get(field) != expected.get(field):
                _fail(errors, "case_domain_mismatch", f"{label}.{field} differs from frozen scope", expected=expected.get(field), actual=row.get(field))
        if row.get("parameter_values") != expected.get("parameter_values") or row.get("geometry") != expected.get("geometry") or row.get("control") != expected.get("control"):
            _fail(errors, "case_semantics_mismatch", f"{label} geometry/control/parameter values differ from frozen scope")
        expected_bindings = {
            str(item.get("role")): item.get("sha256")
            for item in _binding_entries(expected.get("input_bindings"))
            if isinstance(item, Mapping)
        }
        actual_bindings = {
            str(item.get("role")): item.get("sha256")
            for item in _binding_entries(row.get("input_bindings"))
            if isinstance(item, Mapping)
        }
        _check_bindings(row.get("input_bindings"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.input_bindings", minimum=2)
        for role, expected_hash in expected_bindings.items():
            if actual_bindings.get(role) != expected_hash:
                _fail(errors, "case_input_hash_mismatch", f"{label} input hash for {role} differs from frozen scope")
        settings = row.get("numeric_settings_by_resolution")
        if _canonical(settings) != _canonical(expected.get("numeric_settings_by_resolution")):
            _fail(errors, "case_numeric_settings_mismatch", f"{label}.numeric_settings_by_resolution differs from frozen scope")
        if _canonical(row.get("numerical_recipe_hash_by_resolution")) != _canonical(expected.get("numerical_recipe_hash_by_resolution")):
            _fail(errors, "case_numerical_hash_mismatch", f"{label}.numerical_recipe_hash_by_resolution differs from frozen scope")
        _validate_recipe_identity(row, scope_info["recipe"], label, errors)
        _validate_full_state_qi(
            row.get("qi"), expected_case=expected, scope_info=scope_info,
            base_dir=evidence_path.parent, data_root=data_root, errors=errors,
            bound_artifacts=bound_artifacts, label=f"{label}.qi",
        )
    missing = sorted(set(expected_by_id) - set(seen))
    if missing:
        _fail(errors, "case_evidence_missing", "scope cases lack Q-I evidence", case_ids=missing)
    return seen


def _validate_reference_views(
    evidence: Mapping[str, Any],
    *,
    scope_info: Mapping[str, Any],
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> None:
    rows = _list(evidence.get("reference_views"), "evidence.reference_views", errors)
    reference_cases = {
        background: scope_info["case_by_id"].get(case_id)
        for background, case_id in scope_info.get("reference_case_ids", {}).items()
    }
    expected_keys = {
        (background, resolution): case
        for background, case in reference_cases.items()
        if isinstance(case, Mapping)
        for resolution in case.get("resolution_views", [])
    }
    required_keys = {(background, resolution) for background in scope_info["reference_backgrounds"] for resolution in scope_info["reference_resolutions"]}
    if set(expected_keys) != required_keys:
        _fail(errors, "reference_scope_case_matrix_invalid", "scope cases do not provide exactly one physical case per required background")
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        label = f"evidence.reference_views[{index}]"
        if not isinstance(row, Mapping):
            _fail(errors, "reference_view_invalid", f"{label} must be an object")
            continue
        key = (row.get("background"), row.get("resolution"))
        if key in seen:
            _fail(errors, "reference_view_duplicate", f"duplicate reference view: {key}")
        seen.add(key)
        expected = expected_keys.get(key)
        if expected is None:
            _fail(errors, "reference_view_outside_scope", f"reference view {key} is outside frozen background/resolution domain")
            continue
        for field in ("physical_case_id", "parent_group_id", "split", "physical_condition_hash", "geometry_family_id", "control_family_id"):
            if row.get(field) != expected.get(field):
                _fail(errors, "reference_domain_mismatch", f"{label}.{field} differs from frozen scope")
        if row.get("evidence_class") != CURRENT_EVIDENCE_CLASS or row.get("state_coverage") != FULL_STATE_COVERAGE:
            _fail(errors, "reference_evidence_class_invalid", f"{label} is not current full-state evidence")
        if row.get("status") not in PASS_REFERENCE_STATUS:
            _fail(errors, "reference_status_invalid", f"{label}.status is not an actual reference pass")
        _validate_recipe_identity(row, scope_info["recipe"], label, errors)
        _check_artifact(row.get("evidence_file"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.evidence_file")
        _check_bindings(row.get("source_bindings"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.source_bindings", minimum=4)
        _require_binding_roles(
            row.get("source_bindings"),
            {"geometry_xml", "gencase_bi4", "copied_motion", "solver_log"},
            label=f"{label}.source_bindings",
            errors=errors,
        )
        expected_settings = expected.get("numeric_settings_by_resolution", {}).get(row.get("resolution"))
        if _canonical(row.get("numeric_settings")) != _canonical(expected_settings):
            _fail(errors, "reference_numeric_settings_mismatch", f"{label}.numeric_settings differs from frozen scope")
        expected_recipe_hash = expected.get("numerical_recipe_hash_by_resolution", {}).get(row.get("resolution"))
        if row.get("numerical_recipe_hash") != expected_recipe_hash:
            _fail(errors, "reference_numerical_hash_mismatch", f"{label}.numerical_recipe_hash differs from frozen scope")
        solver = _mapping(row.get("solver"), f"{label}.solver", errors)
        if solver is not None:
            if solver.get("completed") is not True or solver.get("solver_dimension") != 3:
                _fail(errors, "reference_solver_incomplete", f"{label} lacks completed 3-D solver evidence")
            _check_finite_positive(solver, "total_particles", f"{label}.solver", errors)
            _check_finite_positive(solver, "fluid_count", f"{label}.solver", errors)
            if solver.get("data2d") is not False:
                _fail(errors, "reference_not_3d", f"{label}.solver.data2d must be false")
            if solver.get("motion_control_covered") is not True or solver.get("finite_boundary_covered") is not True:
                _fail(errors, "reference_geometry_control_incomplete", f"{label} lacks finite boundary or motion coverage")
            timeline = _mapping(solver.get("time_domain"), f"{label}.solver.time_domain", errors)
            if timeline is not None:
                if timeline.get("complete") is not True or timeline.get("start_s") != scope_info["time_domain"].get("start_s") or timeline.get("end_s") != scope_info["time_domain"].get("end_s"):
                    _fail(errors, "reference_time_domain_mismatch", f"{label} does not cover the frozen complete event window")
        checks = row.get("checks")
        if isinstance(checks, Mapping):
            _check_true_fields(checks, ("three_dimensional", "nonzero_fluid", "population_bound", "geometry_bound", "control_bound"), f"{label}.checks", errors)
        else:
            _fail(errors, "reference_checks_empty", f"{label}.checks must contain actual checks")
    if seen != required_keys:
        _fail(errors, "reference_matrix_incomplete", "two-background three-resolution reference matrix is incomplete", missing=sorted(required_keys - seen), extra=sorted(seen - required_keys))


def _validate_comparisons(
    evidence: Mapping[str, Any],
    *,
    scope_info: Mapping[str, Any],
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> None:
    rows = _list(evidence.get("comparisons"), "evidence.comparisons", errors)
    requirements = {str(row.get("comparison_id")): row for row in scope_info["comparison_requirements"] if isinstance(row, Mapping)}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        label = f"evidence.comparisons[{index}]"
        if not isinstance(row, Mapping):
            _fail(errors, "comparison_evidence_invalid", f"{label} must be an object")
            continue
        comparison_id = str(row.get("comparison_id", ""))
        if comparison_id in seen:
            _fail(errors, "comparison_evidence_duplicate", f"duplicate comparison_id: {comparison_id}")
        seen.add(comparison_id)
        requirement = requirements.get(comparison_id)
        if requirement is None:
            _fail(errors, "comparison_outside_scope", f"comparison {comparison_id} is not required by frozen scope")
            continue
        for field in ("kind", "case_id", "physical_case_id", "background"):
            if row.get(field) != requirement.get(field):
                _fail(errors, "comparison_domain_mismatch", f"{label}.{field} differs from frozen requirement")
        expected_case = scope_info["case_by_id"].get(str(row.get("case_id")))
        if expected_case is None:
            _fail(errors, "comparison_case_missing", f"{label} case is outside scope")
            continue
        for field in ("parent_group_id", "split", "physical_condition_hash"):
            if row.get(field) != expected_case.get(field):
                _fail(errors, "comparison_physical_binding_mismatch", f"{label}.{field} differs from frozen case")
        if row.get("evidence_class") != CURRENT_EVIDENCE_CLASS or row.get("state_coverage") != FULL_STATE_COVERAGE:
            _fail(errors, "comparison_evidence_class_invalid", f"{label} is not current full-state evidence")
        if row.get("status") not in PASS_COMPARISON_STATUS or row.get("independent") is not True:
            _fail(errors, "comparison_status_invalid", f"{label} is not an actual independent comparison pass")
        _validate_recipe_identity(row, scope_info["recipe"], label, errors)
        _check_artifact(row.get("evidence_file"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.evidence_file")
        _check_bindings(row.get("source_bindings"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.source_bindings", minimum=1)
        baseline_hash = row.get("baseline_numerical_recipe_hash")
        comparison_hash = row.get("comparison_numerical_recipe_hash")
        if not _sha_string(baseline_hash) or not _sha_string(comparison_hash) or baseline_hash == comparison_hash:
            _fail(errors, "comparison_recipe_not_independent", f"{label} baseline/comparison numerical recipe hashes must be distinct")
        baseline_resolution = requirement.get("baseline_resolution")
        expected_baseline_hash = expected_case.get("numerical_recipe_hash_by_resolution", {}).get(baseline_resolution)
        if baseline_resolution not in expected_case.get("resolution_views", []) or baseline_hash != expected_baseline_hash:
            _fail(errors, "comparison_baseline_binding_mismatch", f"{label} baseline recipe is not bound to the frozen baseline resolution")
        changed_fields = row.get("changed_numeric_fields")
        required_fields = requirement.get("required_changed_numeric_fields", [])
        if not isinstance(changed_fields, list) or not set(required_fields).issubset(set(changed_fields)):
            _fail(errors, "comparison_changed_fields_missing", f"{label} does not prove the required numerical change", required=required_fields)
        stats = _mapping(row.get("actual_statistics"), f"{label}.actual_statistics", errors)
        if stats is not None:
            _check_finite_positive(stats, "sample_count", f"{label}.actual_statistics", errors)
            for field in requirement.get("required_statistic_fields", []):
                value = stats.get(field)
                if not _finite_number(value) and not (isinstance(value, Mapping) and value):
                    _fail(errors, "comparison_statistic_missing", f"{label}.actual_statistics.{field} is empty or nonnumeric")
        points = row.get("observations")
        if not isinstance(points, Mapping):
            _fail(errors, "comparison_observations_missing", f"{label}.observations is missing")
        else:
            for point in requirement.get("required_observation_points", []):
                point_value = points.get(point)
                if not isinstance(point_value, Mapping) or not point_value:
                    _fail(errors, "comparison_observation_point_empty", f"{label}.observations.{point} is empty")
                    continue
                _check_finite_positive(point_value, "sample_count", f"{label}.observations.{point}", errors)
                if not isinstance(point_value.get("metrics"), Mapping) or not point_value["metrics"]:
                    _fail(errors, "comparison_observation_metrics_empty", f"{label}.observations.{point}.metrics is empty")
        timeline = _mapping(row.get("time_domain"), f"{label}.time_domain", errors)
        if timeline is not None:
            if timeline.get("complete") is not True or timeline.get("start_s") != scope_info["time_domain"].get("start_s") or timeline.get("end_s") != scope_info["time_domain"].get("end_s"):
                _fail(errors, "comparison_time_domain_mismatch", f"{label} does not cover the frozen complete event window")
    missing = sorted(set(requirements) - seen)
    if missing:
        _fail(errors, "comparison_evidence_missing", "required independent integration/save evidence is incomplete", comparison_ids=missing)


def validate_scope_documents(
    scope: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    scope_path: str | Path,
    evidence_path: str | Path,
    scope_sha256: str | None = None,
    evidence_sha256: str | None = None,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return an evidence-bound eligibility verdict without approving a scope."""

    scope_file = Path(scope_path).expanduser().resolve()
    evidence_file = Path(evidence_path).expanduser().resolve()
    actual_scope_digest = sha256_file(scope_file)
    actual_evidence_digest = sha256_file(evidence_file)
    scope_digest = scope_sha256 or actual_scope_digest
    evidence_digest = evidence_sha256 or actual_evidence_digest
    root = Path(data_root).expanduser().resolve() if data_root is not None else None
    errors: list[dict[str, Any]] = []
    bound_artifacts: dict[str, dict[str, Any]] = {}

    if scope_digest != actual_scope_digest:
        _fail(errors, "scope_input_hash_mismatch", "caller-supplied scope_sha256 does not match scope bytes on disk", expected=scope_digest, actual=actual_scope_digest)
    if evidence_digest != actual_evidence_digest:
        _fail(errors, "evidence_input_hash_mismatch", "caller-supplied evidence_sha256 does not match evidence bytes on disk", expected=evidence_digest, actual=actual_evidence_digest)

    forbidden = _find_forbidden_markers(scope, ignored_roots=IGNORED_INPUT_ROOTS)
    forbidden.extend(_find_forbidden_markers(evidence, ignored_roots=IGNORED_INPUT_ROOTS))
    for marker in forbidden:
        _fail(errors, "self_declared_qualification_forbidden", "evidence cannot self-declare qualified or production eligibility", path=marker)

    scope_info = _check_scope_shape(scope, scope_path=scope_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        _fail(errors, "evidence_schema_invalid", f"evidence schema must be {EVIDENCE_SCHEMA}")
    if evidence.get("family_id") != "F2" or evidence.get("scope_id") != scope.get("scope_id"):
        _fail(errors, "evidence_scope_identity_invalid", "evidence family_id/scope_id does not match scope")
    if evidence.get("evidence_class") != CURRENT_EVIDENCE_CLASS:
        _fail(errors, "evidence_class_invalid", "evidence root must be current scope evidence")
    if evidence.get("state_coverage") != FULL_STATE_COVERAGE:
        _fail(errors, "evidence_state_coverage_invalid", "evidence root must declare full typed state coverage")
    _check_scope_binding(evidence, scope_path=scope_file, scope_sha256=scope_digest, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_recipe_identity(evidence, scope_info["recipe"], "evidence", errors)
    if _canonical(evidence.get("observations")) != _canonical(scope_info["observations"]):
        _fail(errors, "observation_contract_mismatch", "evidence observations differ from frozen physical scales/error budget/definitions")

    reuse = evidence.get("reuse")
    if reuse is not None:
        _validate_reuse_equivalence(
            reuse,
            scope=scope,
            scope_info=scope_info,
            scope_sha256=scope_digest,
            evidence_path=evidence_file,
            data_root=root,
            errors=errors,
            bound_artifacts=bound_artifacts,
        )

    _validate_case_rows(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_reference_views(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_comparisons(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)

    # The artifact hash list is part of the verdict itself.  The root process
    # can bind this exact verdict to its separate approved index later.
    implementation_path = Path(__file__).resolve()
    implementation_hash = sha256_file(implementation_path)
    eligible = not errors
    return {
        "schema": VERDICT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F2",
        "scope_id": scope.get("scope_id"),
        "status": "evidence-bound-eligible" if eligible else "evidence-bound-ineligible",
        "evidence_bound_eligible": eligible,
        "approval_authority": "root-approved-index-only",
        "validator_role": "dataset-only-evidence-bound-eligibility; does not approve, run GPU, or replace Q-N acceptance",
        "scope_binding": {"path": str(scope_file), "sha256": scope_digest},
        "evidence_binding": {"path": str(evidence_file), "sha256": evidence_digest},
        "validator_binding": {
            "path": str(implementation_path),
            "sha256": implementation_hash,
            "schema": VERDICT_SCHEMA,
        },
        "bound_artifacts": sorted(bound_artifacts.values(), key=lambda item: item["path"]),
        "checks": {
            "recipe_schema_and_inputs": not any(item["code"].startswith(("scope_schema", "scope_family", "recipe", "scope_input", "artifact_", "case_input")) for item in errors),
            "physical_domain_time_observations": not any(item["code"].startswith(("scope_case", "scope_physical", "scope_split", "scope_resolution", "time_", "observation", "qi_", "reference_", "case_domain", "case_semantics", "case_numeric")) for item in errors),
            "reference_matrix": not any(item["code"].startswith("reference_") for item in errors),
            "independent_comparisons": not any(item["code"].startswith("comparison_") for item in errors),
            "split_and_view_leakage": not any(item["code"] in {"scope_parent_split_leak", "case_outside_scope", "reference_view_outside_scope", "comparison_outside_scope", "comparison_physical_binding_mismatch"} for item in errors),
            "current_full_state_evidence": not any(item["code"] in {"evidence_class_invalid", "evidence_state_coverage_invalid", "qi_state_coverage_invalid", "reference_evidence_class_invalid", "comparison_evidence_class_invalid", "reuse_fluid_only_forbidden"} for item in errors),
        },
        "errors": errors,
        "ignored_inputs": ["Q-E", "other_family_evidence", "material_tracer", "model_or_prediction"],
        "approval_index_write": "not_performed",
    }


def validate_scope_files(
    scope_path: str | Path,
    evidence_path: str | Path,
    *,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    scope, resolved_scope, scope_hash = load_json(scope_path)
    evidence, resolved_evidence, evidence_hash = load_json(evidence_path)
    return validate_scope_documents(
        scope,
        evidence,
        scope_path=resolved_scope,
        evidence_path=resolved_evidence,
        scope_sha256=scope_hash,
        evidence_sha256=evidence_hash,
        data_root=data_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        verdict = validate_scope_files(args.scope, args.evidence, data_root=args.data_root)
    except (OSError, ScopeInputError, ValueError) as error:
        print(f"ds_data02_scope: input error: {error}", file=sys.stderr)
        return 2
    serialized = json.dumps(verdict, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if verdict["evidence_bound_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
