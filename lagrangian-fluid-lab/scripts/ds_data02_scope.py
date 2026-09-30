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
  the scope-declared background-by-three-resolution reference views, and
  independent actual integration/save evidence to those frozen rules.
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


def _validate_state_requirements(
    scope: Mapping[str, Any],
    *,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate the scope-owned typed-state contract.

    Dataset names and body-state requirements are deliberately declared by the
    scope.  A static family can omit a moving-body dataset; a scope containing
    native type-1/type-2 particles can make that dataset conditional or
    required.  No family-specific list is used here.
    """

    state = _mapping(scope.get("state_requirements"), "scope.state_requirements", errors)
    if state is None:
        return {"dataset_specs": {}, "required_datasets": [], "moving_boundary": {}, "qi_report": {}}
    specs = _mapping(state.get("dataset_specs"), "scope.state_requirements.dataset_specs", errors)
    required_value = state.get("required_datasets")
    if not isinstance(required_value, list) or not required_value:
        _fail(errors, "state_required_datasets_missing", "scope.state_requirements.required_datasets must be nonempty")
        required = list(specs or {})
    else:
        if any(not _nonempty_string(item) for item in required_value):
            _fail(errors, "state_required_datasets_invalid", "scope state required_datasets must contain nonempty names")
        required = [str(item) for item in required_value if _nonempty_string(item)]
        if len(set(required)) != len(required):
            _fail(errors, "state_required_datasets_duplicate", "scope state required_datasets must be unique")
    if specs is None:
        specs = {}
    for name in required:
        spec = specs.get(name)
        if not isinstance(spec, Mapping):
            _fail(errors, "state_dataset_spec_missing", f"scope state dataset {name} lacks a declared path/shape/units spec")
            continue
        if not _nonempty_string(spec.get("path")):
            _fail(errors, "state_dataset_path_missing", f"scope state dataset {name} lacks a path")
        if not isinstance(spec.get("rank"), int) or isinstance(spec.get("rank"), bool) or spec["rank"] < 1:
            _fail(errors, "state_dataset_rank_missing", f"scope state dataset {name} lacks a positive rank")
        if not (_nonempty_string(spec.get("units")) or (isinstance(spec.get("units"), Mapping) and bool(spec["units"]))):
            _fail(errors, "state_dataset_units_missing", f"scope state dataset {name} lacks declared units")
    identity = _mapping(state.get("identity"), "scope.state_requirements.identity", errors)
    if identity is not None:
        if not _nonempty_string(identity.get("axis")):
            _fail(errors, "state_identity_axis_missing", "scope state identity axis must be explicit")
        for field in ("particle_id", "particle_zone", "type", "valid"):
            if field not in identity and field in required:
                _fail(errors, "state_identity_field_missing", f"scope identity lacks {field} mapping")
    type_semantics = _mapping(state.get("type_semantics"), "scope.state_requirements.type_semantics", errors)
    fluid_types: list[int] = []
    if type_semantics is not None:
        values = type_semantics.get("fluid_values")
        if not isinstance(values, list) or not values:
            _fail(errors, "state_fluid_type_values_missing", "scope must declare native fluid type values")
        else:
            fluid_types = [int(value) for value in values if isinstance(value, int) and not isinstance(value, bool)]
            if len(fluid_types) != len(values):
                _fail(errors, "state_fluid_type_values_invalid", "scope fluid type values must be integers")
        for key in ("moving_values", "boundary_values"):
            values = type_semantics.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, int) or isinstance(value, bool) for value in values):
                _fail(errors, "state_type_values_invalid", f"scope {key} must be an integer list")
    moving = state.get("moving_boundary", {})
    if not isinstance(moving, Mapping):
        _fail(errors, "state_moving_boundary_invalid", "scope moving_boundary must be an object")
        moving = {}
    mode = moving.get("mode", "not_applicable")
    if mode not in {"required", "conditional", "not_applicable"}:
        _fail(errors, "state_moving_boundary_mode_invalid", "scope moving_boundary.mode must be required, conditional, or not_applicable")
    if mode in {"required", "conditional"}:
        dataset_name = moving.get("dataset")
        if not _nonempty_string(dataset_name) or dataset_name not in specs:
            _fail(errors, "state_moving_boundary_dataset_missing", "moving boundary mode requires a declared state dataset")
    qi_report = state.get("qi_report", {})
    if not isinstance(qi_report, Mapping):
        _fail(errors, "state_qi_report_invalid", "scope qi_report must be an object")
        qi_report = {}
    accepted_statuses = qi_report.get("accepted_statuses", ["Q-I-structure-pass", "Q-I-pass"])
    if not isinstance(accepted_statuses, list) or not accepted_statuses or any(not _nonempty_string(item) for item in accepted_statuses):
        _fail(errors, "state_qi_statuses_invalid", "scope qi_report.accepted_statuses must be nonempty strings")
        accepted_statuses = []
    return {
        "raw": state,
        "dataset_specs": specs,
        "required_datasets": required,
        "identity": identity or {},
        "type_semantics": type_semantics or {},
        "fluid_values": fluid_types,
        "moving_boundary": dict(moving),
        "qi_report": dict(qi_report),
        "accepted_qi_statuses": set(str(item) for item in accepted_statuses),
    }


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
    if not _nonempty_string(scope.get("family_id")):
        _fail(errors, "scope_family_invalid", "scope family_id must be a nonempty frozen family identifier")
    if not _nonempty_string(scope.get("scope_id")):
        _fail(errors, "scope_id_missing", "scope_id must be nonempty")

    recipe = _mapping(scope.get("recipe"), "scope.recipe", errors)
    if recipe is not None:
        for field in ("recipe_id", "schema", "state_schema", "view_id"):
            if not _nonempty_string(recipe.get(field)):
                _fail(errors, "recipe_field_missing", f"scope.recipe.{field} must be nonempty")
        if recipe.get("solver_dimension") != 3 or isinstance(recipe.get("solver_dimension"), bool):
            _fail(errors, "recipe_dimension_invalid", "DS-DATA-02 requires an actual 3D recipe")

    state_info = _validate_state_requirements(scope, errors=errors)

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
                minimum=1,
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
        if len(reference_resolutions) != 3:
            _fail(errors, "reference_resolution_domain_invalid", "scope requires exactly three spatial reference resolutions")
        coverage_mode = reference.get("coverage_mode")
        if not _nonempty_string(coverage_mode):
            _fail(errors, "reference_coverage_mode_missing", "scope must explicitly declare reference coverage_mode")
        elif len(reference_backgrounds) == 1 and coverage_mode != "single_background_explicit":
            _fail(errors, "reference_single_background_unscoped", "a one-background scope must explicitly declare single_background_explicit")
        elif len(reference_backgrounds) > 1 and coverage_mode not in {"full_family_default", "declared_multi_background"}:
            _fail(errors, "reference_coverage_mode_invalid", "multi-background scopes need an explicit multi-background coverage_mode")
        required_source_roles = reference.get("required_source_roles", [])
        if not isinstance(required_source_roles, list) or not required_source_roles or any(not _nonempty_string(item) for item in required_source_roles):
            _fail(errors, "reference_source_roles_missing", "scope must declare required reference source roles")
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

    parameter_domains = _mapping(scope.get("physical_parameter_domains"), "scope.physical_parameter_domains", errors)
    if parameter_domains is not None:
        for parameter, domain_spec in parameter_domains.items():
            if not _nonempty_string(parameter) or not isinstance(domain_spec, Mapping):
                _fail(errors, "parameter_domain_invalid", f"physical parameter domain {parameter} must be an object")
                continue
            lower = domain_spec.get("min")
            upper = domain_spec.get("max")
            if not _finite_number(lower) or not _finite_number(upper) or float(upper) <= float(lower):
                _fail(errors, "parameter_domain_bounds_invalid", f"physical parameter domain {parameter} needs finite max > min")
            if not _nonempty_string(domain_spec.get("units")):
                _fail(errors, "parameter_domain_units_missing", f"physical parameter domain {parameter} needs units")

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
        parameter_points = requirement.get("parameter_points")
        if not isinstance(parameter_points, Mapping) or set(parameter_points) != {"endpoint", "internal"}:
            _fail(errors, "comparison_parameter_points_invalid", f"comparison {comparison_id} must require physical endpoint and internal points")
        else:
            for point_name, point_spec in parameter_points.items():
                if not isinstance(point_spec, Mapping) or not _nonempty_string(point_spec.get("parameter")):
                    _fail(errors, "comparison_parameter_point_invalid", f"comparison {comparison_id}.{point_name} lacks parameter mapping")
                elif parameter_domains is not None and point_spec.get("parameter") not in parameter_domains:
                    _fail(errors, "comparison_parameter_outside_scope", f"comparison {comparison_id}.{point_name} references an undeclared physical parameter")
                if point_name == "endpoint" and point_spec.get("side") not in {"min", "max"}:
                    _fail(errors, "comparison_endpoint_side_invalid", f"comparison {comparison_id} endpoint must declare side=min or side=max")
                if point_name == "internal" and point_spec.get("side") is not None:
                    _fail(errors, "comparison_internal_side_invalid", f"comparison {comparison_id} internal point must be strictly inside the physical parameter domain")
        required_error_metrics = requirement.get("required_error_metrics")
        if not isinstance(required_error_metrics, list) or not required_error_metrics or any(not _nonempty_string(item) for item in required_error_metrics):
            _fail(errors, "comparison_error_metrics_missing", f"comparison {comparison_id} must declare frozen error metrics")
        if _nonempty_string(requirement.get("background")) and kind in {"integration", "save"}:
            comparison_kinds_by_background.setdefault(str(requirement["background"]), set()).add(str(kind))
    if comparison_kinds != {"integration", "save"}:
        _fail(errors, "comparison_kinds_incomplete", "scope must require both integration and save comparisons")
    for background in reference_backgrounds:
        if comparison_kinds_by_background.get(background) != {"integration", "save"}:
            _fail(errors, "comparison_background_incomplete", f"scope must require independent integration and save comparisons for {background}")

    required_scope_roles_value = scope.get("required_input_roles")
    if not isinstance(required_scope_roles_value, list) or not required_scope_roles_value or any(not _nonempty_string(item) for item in required_scope_roles_value):
        _fail(errors, "scope_input_roles_declaration_missing", "scope must declare nonempty required_input_roles")
        required_scope_roles: set[str] = set()
    else:
        required_scope_roles = {str(item) for item in required_scope_roles_value}
    declared_scope_bindings = scope.get("input_bindings")
    scope_bindings = _check_bindings(
        declared_scope_bindings,
        base_dir=scope_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="scope.input_bindings",
        minimum=max(1, len(required_scope_roles)),
    )
    roles = {item.get("role") for item in _binding_entries(declared_scope_bindings) if isinstance(item, Mapping)}
    missing_roles = sorted(required_scope_roles - roles)
    if missing_roles:
        _fail(errors, "scope_input_roles_missing", "scope input bindings do not include required frozen contracts", missing_roles=missing_roles)

    # A reference/domain study precedes production. Planned cases need input
    # membership evidence, not a trajectory from a solver not yet launched.
    evidence_ids = domain.get("evidence_case_ids", list(case_by_id)) if domain is not None else []
    if not isinstance(evidence_ids, list) or not evidence_ids or len(set(evidence_ids)) != len(evidence_ids) or any(case_id not in case_by_id for case_id in evidence_ids):
        _fail(errors, "scope_evidence_cases_invalid", "evidence_case_ids must name unique cases in the frozen domain")
        evidence_ids = list(case_by_id)
    if not set(reference_case_ids.values()).issubset(evidence_ids):
        _fail(errors, "scope_reference_evidence_missing", "every reference mother requires actual full-state Q-I evidence")
    spatial_acceptance = scope.get("spatial_acceptance")
    if not isinstance(spatial_acceptance, Mapping) or not spatial_acceptance:
        _fail(errors, "spatial_acceptance_missing", "freeze spatial metric thresholds; three solver runs alone do not prove convergence")
        spatial_acceptance = {}
    for metric, threshold in spatial_acceptance.items():
        if not _nonempty_string(metric) or not _finite_number(threshold) or threshold <= 0:
            _fail(errors, "spatial_threshold_invalid", "spatial metric thresholds must be finite and positive", metric=metric)
    budget = (observations or {}).get("error_budget", {})
    for metric in ("macro_relative", "event_time_absolute_s"):
        value = spatial_acceptance.get(metric)
        if not _finite_number(value) or not _finite_number(budget.get(metric)) or value > budget[metric]:
            _fail(errors, "spatial_budget_invalid", "spatial thresholds must cover frozen macro and event budgets without relaxation", metric=metric)

    return {
        "recipe": recipe or {},
        "family_id": str(scope.get("family_id", "")),
        "state": state_info,
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
        "reference_source_roles": set(str(item) for item in (reference.get("required_source_roles", []) if reference is not None else [])),
        "parameter_domains": parameter_domains or {},
        "comparison_requirements": comparison_requirements,
        "comparison_ids": comparison_ids,
        "scope_bindings": scope_bindings,
        "required_scope_roles": required_scope_roles,
        "evidence_case_ids": evidence_ids,
        "spatial_acceptance": spatial_acceptance,
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
    evidence_path: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
) -> None:
    """Validate an old qualified scope through an actual semantic projection."""

    if not isinstance(reuse, Mapping) or reuse.get("strict_scope_equivalence") is not True:
        _fail(errors, "reuse_equivalence_missing", "reused evidence needs an explicit strict_scope_equivalence declaration")
        return
    if reuse.get("source_state_coverage") != FULL_STATE_COVERAGE:
        _fail(errors, "reuse_fluid_only_forbidden", "old fluid-only HDF5 cannot be reused as full-state delivery")
    old_scope, old_scope_binding = _load_json_artifact(
        reuse.get("equivalent_scope_binding"),
        base_dir=evidence_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="evidence.reuse.equivalent_scope_binding",
    )
    if old_scope is None or old_scope_binding is None:
        _fail(errors, "reuse_scope_binding_missing", "strict reuse requires a hash-bound source scope document")
    else:
        projection_keys = (
            "schema", "family_id", "recipe", "time_domain", "observations",
            "state_requirements", "physical_parameter_domains", "physical_domain",
            "reference_requirements", "comparison_requirements", "required_input_roles",
        )
        current_projection = {key: scope.get(key) for key in projection_keys}
        old_projection = {key: old_scope.get(key) for key in projection_keys}
        if _canonical(old_projection) != _canonical(current_projection):
            _fail(errors, "reuse_scope_semantics_mismatch", "old qualified scope is not strictly equivalent to the supplied scope")
        if old_scope.get("family_id") != scope.get("family_id"):
            _fail(errors, "reuse_scope_family_mismatch", "old qualified scope belongs to a different family")
    _check_bindings(
        reuse.get("equivalence_evidence"),
        base_dir=evidence_path.parent,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label="evidence.reuse.equivalence_evidence",
        minimum=1,
    )


def _decode_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _state_dataset_key(state_info: Mapping[str, Any], semantic_name: str) -> str:
    """Return the logical dataset key for a semantic state field.

    Scope authors may name datasets after the semantic field or map the field
    to a logical key/path under ``state_requirements.identity``.  H5 auditing
    uses this helper so a static family with a different naming convention is
    not forced through one family's fixture names.
    """

    identity = state_info.get("identity", {})
    candidate = identity.get(semantic_name, semantic_name) if isinstance(identity, Mapping) else semantic_name
    candidate = str(candidate)
    specs = state_info.get("dataset_specs", {})
    if candidate in specs:
        return candidate
    for key, spec in (specs.items() if isinstance(specs, Mapping) else ()):
        if isinstance(spec, Mapping) and str(spec.get("path")) == candidate:
            return str(key)
    return candidate


def _load_json_artifact(
    binding: Any,
    *,
    base_dir: Path,
    data_root: Path | None,
    errors: list[dict[str, Any]],
    bound_artifacts: dict[str, dict[str, Any]],
    label: str,
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None]:
    checked = _check_artifact(binding, base_dir=base_dir, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=label)
    if checked is None:
        return None, None
    try:
        value, _, _ = load_json(checked["path"])
    except (OSError, ScopeInputError) as error:
        _fail(errors, "artifact_json_invalid", f"{label} is not a valid JSON artifact: {error}")
        return None, checked
    return value, checked


def _h5_state_audit(
    h5_binding: dict[str, Any] | None,
    *,
    state_info: Mapping[str, Any],
    recipe: Mapping[str, Any],
    time_domain: Mapping[str, Any],
    label: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read and verify the actual hash-bound H5 shape/type/valid/units data."""

    audit: dict[str, Any] = {"h5_path": h5_binding.get("path") if h5_binding else None}
    if h5_binding is None:
        _fail(errors, "state_h5_missing", f"{label} has no hash-bound full-state H5 source")
        return audit
    try:
        import h5py  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as error:
        _fail(errors, "state_h5_reader_missing", f"cannot read full-state H5 for {label}: {error}")
        return audit
    specs = state_info.get("dataset_specs", {})
    required = state_info.get("required_datasets", [])
    try:
        with h5py.File(h5_binding["path"], "r") as handle:
            root_units: dict[str, Any] = {}
            units_raw = _decode_attr(handle.attrs.get("units_json"))
            if isinstance(units_raw, str):
                try:
                    parsed_units = json.loads(units_raw)
                    if isinstance(parsed_units, Mapping):
                        root_units = dict(parsed_units)
                except json.JSONDecodeError:
                    _fail(errors, "state_units_json_invalid", f"{label} root units_json is invalid")
            solver_dimension = _decode_attr(handle.attrs.get("solver_dimension"))
            if solver_dimension is None:
                solver_evidence = _decode_attr(handle.attrs.get("solver_dimension_evidence"))
                if isinstance(solver_evidence, str):
                    try:
                        solver_dimension = json.loads(solver_evidence).get("solver_dimension")
                    except json.JSONDecodeError:
                        solver_dimension = None
            if solver_dimension is not None and int(solver_dimension) != int(recipe.get("solver_dimension")):
                _fail(errors, "state_solver_dimension_mismatch", f"{label} H5 solver_dimension differs from frozen recipe")

            datasets: dict[str, Any] = {}
            moving_spec = state_info.get("moving_boundary", {})
            moving_dataset_key = _state_dataset_key(state_info, str(moving_spec.get("dataset", ""))) if isinstance(moving_spec, Mapping) and moving_spec.get("dataset") else ""
            for name in required:
                spec = specs.get(name, {})
                path = str(spec.get("path", name))
                if path not in handle:
                    _fail(errors, "state_dataset_missing", f"{label} H5 lacks required dataset {path}", dataset=name)
                    continue
                dataset = handle[path]
                if not isinstance(dataset, h5py.Dataset):
                    _fail(errors, "state_dataset_not_dataset", f"{label} H5 path {path} is not a dataset")
                    continue
                datasets[name] = dataset
                rank = spec.get("rank")
                if isinstance(rank, int) and dataset.ndim != rank:
                    _fail(errors, "state_dataset_shape_mismatch", f"{label}.{name} rank differs from frozen state spec", expected=rank, actual=dataset.ndim)
                last_dim = spec.get("last_dim")
                if isinstance(last_dim, int) and (dataset.ndim == 0 or dataset.shape[-1] != last_dim):
                    _fail(errors, "state_dataset_components_mismatch", f"{label}.{name} coordinate components differ from frozen state spec")
                actual_units = dataset.attrs.get("units", dataset.attrs.get("unit", root_units.get(name, root_units.get(path))))
                actual_units = _decode_attr(actual_units)
                if actual_units is None:
                    dataset_units_json = _decode_attr(dataset.attrs.get("units_json"))
                    if isinstance(dataset_units_json, str):
                        try:
                            actual_units = json.loads(dataset_units_json)
                        except json.JSONDecodeError:
                            actual_units = None
                expected_units = spec.get("units")
                units_match = _canonical(actual_units) == _canonical(expected_units) if isinstance(expected_units, Mapping) else (_nonempty_string(actual_units) and str(actual_units) == str(expected_units))
                if not units_match:
                    _fail(errors, "state_dataset_units_mismatch", f"{label}.{name} units do not match frozen state units", expected=spec.get("units"), actual=actual_units)
            time_ds = datasets.get(_state_dataset_key(state_info, "time"))
            frames = int(time_ds.shape[0]) if time_ds is not None and time_ds.ndim == 1 else 0
            if frames < int(time_domain.get("minimum_frames", 2)):
                _fail(errors, "state_time_frame_floor", f"{label} H5 has fewer than the frozen minimum frames")
            times = np.asarray(time_ds[:], dtype=float) if time_ds is not None and time_ds.ndim == 1 else np.asarray([])
            if times.size and (not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0)):
                _fail(errors, "state_time_axis_invalid", f"{label} H5 time axis is not finite and strictly increasing")
            if times.size:
                duration = max(float(time_domain.get("end_s", 1.0)) - float(time_domain.get("start_s", 0.0)), 1.0)
                tolerance = max(1e-8, duration * 1e-4)
                if float(times[0]) > float(time_domain.get("start_s", 0.0)) + tolerance or float(times[-1]) < float(time_domain.get("end_s", 0.0)) - tolerance:
                    _fail(errors, "state_time_domain_incomplete", f"{label} H5 does not cover the frozen event window")
            particle_count = 0
            id_ds = datasets.get(_state_dataset_key(state_info, "particle_id"))
            if id_ds is not None and id_ds.ndim == 1:
                particle_count = int(id_ds.shape[0])
                if id_ds.dtype.kind not in "iu":
                    _fail(errors, "state_particle_id_type_invalid", f"{label} particle_id is not an integer dataset")
                else:
                    ids = np.asarray(id_ds[:])
                    if np.unique(ids).size != ids.size:
                        _fail(errors, "state_particle_id_duplicate", f"{label} particle_id values are not unique")
            zone_ds = datasets.get(_state_dataset_key(state_info, "particle_zone"))
            if zone_ds is not None and zone_ds.dtype.kind not in "iu":
                _fail(errors, "state_particle_zone_type_invalid", f"{label} particle_zone is not an integer dataset")
            elif zone_ds is not None and zone_ds.ndim == 1 and particle_count and zone_ds.shape[0] != particle_count:
                _fail(errors, "state_particle_zone_shape_mismatch", f"{label} particle_zone does not share the particle axis")
            non_time_indexed = {
                _state_dataset_key(state_info, "particle_id"),
                _state_dataset_key(state_info, "particle_zone"),
            }
            for name, dataset in datasets.items():
                spec = specs.get(name, {})
                time_indexed = spec.get("time_indexed", name not in non_time_indexed)
                if time_indexed and spec.get("particle_indexed", name != moving_dataset_key):
                    if particle_count and (dataset.ndim < 2 or dataset.shape[1] != particle_count):
                        _fail(errors, "state_particle_shape_mismatch", f"{label}.{name} does not share the actual particle axis")
            type_ds = datasets.get(_state_dataset_key(state_info, "type"))
            valid_ds = datasets.get(_state_dataset_key(state_info, "valid"))
            fluid_count = 0
            moving_count = 0
            moving_any_count = 0
            if type_ds is not None:
                if type_ds.dtype.kind not in "iu":
                    _fail(errors, "state_type_dtype_invalid", f"{label} type is not an integer dataset")
                if type_ds.ndim >= 2 and type_ds.shape[0] == frames and frames:
                    first_type = np.asarray(type_ds[0, :])
                    last_type = np.asarray(type_ds[-1, :])
                else:
                    first_type = np.asarray(type_ds[:])
                    last_type = first_type
                fluid_values = set(int(value) for value in state_info.get("fluid_values", []))
                moving_values = set(int(value) for value in state_info.get("type_semantics", {}).get("moving_values", []))
                boundary_values = set(int(value) for value in state_info.get("type_semantics", {}).get("boundary_values", []))
                known_values = fluid_values | moving_values | boundary_values
                fluid_count = int(np.isin(first_type, list(fluid_values)).sum()) if fluid_values else 0
                moving_count = int(np.isin(first_type, list(moving_values)).sum()) if moving_values else 0
                unknown_type_seen = False
                if moving_values and type_ds.ndim >= 2 and type_ds.shape[0] == frames:
                    for start in range(0, frames, 64):
                        chunk = np.asarray(type_ds[start:min(start + 64, frames), :])
                        if known_values and not np.all(np.isin(chunk, list(known_values))):
                            unknown_type_seen = True
                        moving_any_count = max(moving_any_count, int(np.isin(chunk, list(moving_values)).sum()))
                else:
                    moving_any_count = moving_count
                    if known_values and not np.all(np.isin(np.asarray(type_ds[:]), list(known_values))):
                        unknown_type_seen = True
                if unknown_type_seen:
                    _fail(errors, "state_type_values_invalid", f"{label} type contains values outside the scope native type semantics")
                if fluid_count <= 0:
                    _fail(errors, "state_fluid_population_zero", f"{label} H5 has no native fluid particles in its initial type frame")
                moving_count = max(moving_count, moving_any_count, int(np.isin(last_type, list(moving_values)).sum()))
            if valid_ds is not None:
                if valid_ds.dtype.kind not in "biu":
                    _fail(errors, "state_valid_dtype_invalid", f"{label} valid is not boolean/integer")
                sample = np.asarray(valid_ds[0, :] if valid_ds.ndim >= 2 and valid_ds.shape[0] == frames and frames else valid_ds[:])
                if sample.size and not np.all(np.isin(sample, [0, 1, False, True])):
                    _fail(errors, "state_valid_values_invalid", f"{label} valid contains values outside false/true")
                if valid_ds.ndim >= 2 and valid_ds.shape[0] == frames:
                    for start in range(0, frames, 64):
                        chunk = np.asarray(valid_ds[start:min(start + 64, frames), :])
                        if chunk.size and not np.all(np.isin(chunk, [0, 1, False, True])):
                            _fail(errors, "state_valid_values_invalid", f"{label} valid contains values outside false/true")
                            break
            for name, dataset in datasets.items():
                spec = specs.get(name, {})
                time_indexed = spec.get("time_indexed", name not in non_time_indexed)
                if time_indexed and frames and dataset.ndim > 0 and dataset.shape[0] != frames:
                    _fail(errors, "state_frame_shape_mismatch", f"{label}.{name} does not share the H5 time axis")
                if dataset.dtype.kind == "f":
                    try:
                        if time_indexed and frames:
                            samples = [np.asarray(dataset[0]), np.asarray(dataset[-1])]
                        else:
                            samples = [np.asarray(dataset[:])]
                        if any(sample.size and not np.all(np.isfinite(sample)) for sample in samples):
                            _fail(errors, "state_nonfinite_values", f"{label}.{name} contains nonfinite values")
                    except (OSError, ValueError) as error:
                        _fail(errors, "state_dataset_read_failed", f"{label}.{name} could not be sampled: {error}")
            moving_mode = moving_spec.get("mode", "not_applicable")
            moving_dataset = moving_dataset_key
            if moving_count > 0 and moving_mode == "not_applicable":
                _fail(errors, "state_moving_body_undeclared", f"{label} contains native moving type values but scope declares no moving state")
            if moving_count > 0 and moving_mode in {"required", "conditional"} and moving_dataset not in datasets:
                _fail(errors, "state_moving_body_missing", f"{label} native moving type values lack the declared body-state dataset")
            if moving_mode == "required" and moving_count <= 0:
                _fail(errors, "state_required_body_absent", f"{label} scope requires a moving body but actual native type values contain none")
            identity_axis = str(state_info.get("identity", {}).get("axis", ""))
            actual_identity = _decode_attr(handle.attrs.get("identity_key"))
            if identity_axis and (not _nonempty_string(actual_identity) or str(actual_identity) != identity_axis):
                _fail(errors, "state_identity_axis_mismatch", f"{label} H5 identity_key does not match the frozen identity axis", expected=identity_axis, actual=actual_identity)
            audit.update({"frames": frames, "particles": particle_count, "fluid_count": fluid_count, "moving_count": moving_count, "solver_dimension": solver_dimension})
    except (OSError, ValueError, TypeError) as error:
        _fail(errors, "state_h5_read_failed", f"{label} H5 could not be read: {error}")
    return audit


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
    expected_resolution: str | None = None,
) -> None:
    if not isinstance(qi, Mapping):
        _fail(errors, "qi_missing", f"{label} must be an object")
        return
    if expected_resolution is not None and qi.get("resolution") != expected_resolution:
        _fail(errors, "qi_resolution_mismatch", f"{label}.resolution differs from the frozen view")
    report, report_binding = _load_json_artifact(
        qi.get("evidence_file"),
        base_dir=base_dir,
        data_root=data_root,
        errors=errors,
        bound_artifacts=bound_artifacts,
        label=f"{label}.qi_report",
    )
    if report is not None:
        if report.get("family_id") not in {None, scope_info.get("family_id")}:
            _fail(errors, "qi_report_family_mismatch", f"{label} report family_id differs from frozen scope")
        report_case_id = report.get("case_id")
        allowed_report_ids = {expected_case.get("case_id"), expected_case.get("physical_case_id")}
        if report_case_id is not None and report_case_id not in allowed_report_ids:
            _fail(errors, "qi_report_case_mismatch", f"{label} report case_id differs from frozen case")
        report_qi = report.get("q_i") or report.get("qi") or report
        if not isinstance(report_qi, Mapping):
            _fail(errors, "qi_report_conclusion_missing", f"{label} report has no actual Q-I conclusion")
        else:
            status = report_qi.get("status")
            if status not in scope_info["state"].get("accepted_qi_statuses", set()):
                _fail(errors, "qi_report_status_invalid", f"{label} actual Q-I report conclusion is not accepted", status=status)
            failed_checks = report_qi.get("failed_checks")
            if isinstance(failed_checks, list) and failed_checks:
                _fail(errors, "qi_report_failed_checks", f"{label} actual Q-I report contains failed checks", failed_checks=failed_checks)
            checks = report_qi.get("checks")
            if isinstance(checks, Mapping) and any(value is False for value in checks.values()):
                _fail(errors, "qi_report_failed_checks", f"{label} actual Q-I report contains a false check")
    source_checked = _check_bindings(qi.get("source_bindings"), base_dir=base_dir, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.source_bindings", minimum=1)
    h5_candidates = [item for item in source_checked if item.get("path", "").lower().endswith((".h5", ".hdf5"))]
    if len(h5_candidates) != 1:
        _fail(errors, "state_h5_binding_ambiguous", f"{label} must bind exactly one full-state H5", count=len(h5_candidates))
        h5_binding = h5_candidates[0] if h5_candidates else None
    else:
        h5_binding = h5_candidates[0]
    h5_audit = _h5_state_audit(
        h5_binding,
        state_info=scope_info["state"],
        recipe=scope_info["recipe"],
        time_domain=scope_info["time_domain"],
        label=label,
        errors=errors,
    )
    expected_time = scope_info["time_domain"]
    timeline = qi.get("full_timeline")
    if isinstance(timeline, Mapping) and h5_audit.get("frames"):
        if timeline.get("frames") is not None and int(timeline["frames"]) != int(h5_audit["frames"]):
            _fail(errors, "qi_timeline_frame_mismatch", f"{label}.full_timeline.frames differs from actual H5 shape")
        for field in ("start_s", "end_s"):
            if field in timeline and not _finite_number(timeline.get(field)):
                _fail(errors, "qi_timeline_value_invalid", f"{label}.full_timeline.{field} is not finite")
    if scope_info["state"].get("fluid_values") and h5_audit.get("fluid_count", 0) <= 0:
        _fail(errors, "qi_fluid_population_invalid", f"{label} has no actual H5 fluid population")
    if not report_binding:
        _fail(errors, "qi_report_binding_missing", f"{label} lacks a hash-bound actual Q-I report")
    observations = scope_info["observations"]
    observed_names = qi.get("observed_event_names")
    required_names = observations.get("required_event_names", [])
    if required_names and (not isinstance(observed_names, list) or set(observed_names) != set(required_names)):
        _fail(errors, "qi_observations_incomplete", f"{label} does not bind every frozen observation definition")


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
    expected_by_id = {case_id: scope_info["case_by_id"][case_id] for case_id in scope_info["evidence_case_ids"]}
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
            expected_resolution=str(expected.get("qi_resolution")),
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
        _validate_recipe_identity(row, scope_info["recipe"], label, errors)
        _validate_full_state_qi(
            row.get("qi"), expected_case=expected, scope_info=scope_info,
            base_dir=evidence_path.parent, data_root=data_root, errors=errors,
            bound_artifacts=bound_artifacts, label=f"{label}.qi",
            expected_resolution=str(row.get("resolution")),
        )
        _check_artifact(row.get("evidence_file"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label=f"{label}.evidence_file")
        _check_bindings(
            row.get("source_bindings"),
            base_dir=evidence_path.parent,
            data_root=data_root,
            errors=errors,
            bound_artifacts=bound_artifacts,
            label=f"{label}.source_bindings",
            minimum=max(1, len(scope_info.get("reference_source_roles", set()))),
        )
        _require_binding_roles(
            row.get("source_bindings"),
            set(scope_info.get("reference_source_roles", set())),
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
            if solver.get("completed") is not True or solver.get("solver_dimension") != scope_info["recipe"].get("solver_dimension"):
                _fail(errors, "reference_solver_incomplete", f"{label} lacks completed solver evidence for the frozen dimension")
            _check_finite_positive(solver, "total_particles", f"{label}.solver", errors)
            _check_finite_positive(solver, "fluid_count", f"{label}.solver", errors)
            if scope_info["recipe"].get("solver_dimension") == 3 and solver.get("data2d") is True:
                _fail(errors, "reference_not_3d", f"{label}.solver declares 2-D output for a 3-D scope")
            timeline = _mapping(solver.get("time_domain"), f"{label}.solver.time_domain", errors)
            if timeline is not None:
                if timeline.get("complete") is not True or timeline.get("start_s") != scope_info["time_domain"].get("start_s") or timeline.get("end_s") != scope_info["time_domain"].get("end_s"):
                    _fail(errors, "reference_time_domain_mismatch", f"{label} does not cover the frozen complete event window")
    if seen != required_keys:
        _fail(errors, "reference_matrix_incomplete", "declared background-by-three-resolution reference matrix is incomplete", missing=sorted(required_keys - seen), extra=sorted(seen - required_keys))


def _validate_spatial_comparisons(evidence, *, scope_info, evidence_path, data_root, errors, bound_artifacts):
    """Require actual accepted comparisons, not just three completed solves."""
    levels = scope_info["reference_resolutions"]
    if len(levels) != 3:
        return
    expected = {(bg, level, levels[-1]) for bg in scope_info["reference_backgrounds"] for level in levels[:-1]}
    seen = set()
    views = {(row.get("background"), row.get("resolution")): row for row in evidence.get("reference_views", []) if isinstance(row, Mapping)}
    rows = _list(evidence.get("spatial_comparisons"), "evidence.spatial_comparisons", errors)
    for row in rows:
        if not isinstance(row, Mapping):
            _fail(errors, "spatial_comparison_invalid", "spatial comparison must be an object")
            continue
        key = (row.get("background"), row.get("baseline_resolution"), row.get("reference_resolution"))
        if key not in expected or key in seen:
            _fail(errors, "spatial_pair_invalid", "duplicate or out-of-domain spatial comparison")
            continue
        seen.add(key)
        mother = scope_info["case_by_id"].get(scope_info["reference_case_ids"].get(key[0]), {})
        if row.get("physical_condition_hash") != mother.get("physical_condition_hash"):
            _fail(errors, "spatial_physical_binding_mismatch", "spatial views must share the frozen continuous condition")
        hashes = mother.get("numerical_recipe_hash_by_resolution", {})
        for field, level in (("baseline_numerical_recipe_hash", key[1]), ("reference_numerical_recipe_hash", key[2])):
            if row.get(field) != hashes.get(level):
                _fail(errors, "spatial_recipe_binding_mismatch", "spatial comparison recipe differs from actual reference matrix")
        report, artifact = _load_json_artifact(row.get("evidence_file"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label="spatial.comparison_report")
        metrics = row.get("actual_error_metrics")
        if report is None or report.get("actual_error_metrics") != metrics:
            _fail(errors, "spatial_report_metrics_unbound", "spatial metrics must match the actual hash-bound report")
        if not isinstance(metrics, Mapping):
            metrics = {}
        for metric, threshold in scope_info["spatial_acceptance"].items():
            value = metrics.get(metric)
            if not _finite_number(value) or value < 0:
                _fail(errors, "spatial_metric_missing", "each frozen spatial metric needs a finite measured error", metric=metric)
            elif _finite_number(threshold) and value > threshold:
                _fail(errors, "spatial_budget_exceeded", "spatial error exceeds the frozen threshold", metric=metric, value=value, threshold=threshold)
        bound = _check_bindings(row.get("source_bindings"), base_dir=evidence_path.parent, data_root=data_root, errors=errors, bound_artifacts=bound_artifacts, label="spatial.source_bindings", minimum=2)
        supplied = {(item["path"], item["actual_sha256"]) for item in bound}
        for level in key[1:]:
            view = views.get((key[0], level), {})
            sources = _binding_entries(view.get("qi", {}).get("source_bindings"))
            native = [item for item in sources if str(item.get("path", "")).lower().endswith((".h5", ".hdf5"))]
            if len(native) != 1 or (str(_resolve_path(native[0]["path"], evidence_path.parent, data_root)), native[0].get("sha256")) not in supplied:
                _fail(errors, "spatial_state_binding_missing", "spatial comparison must bind the actual baseline and reference full-state H5")
    if seen != expected:
        _fail(errors, "spatial_comparisons_incomplete", "each declared background needs both coarser levels compared with its finest reference")


def _has_finite_numeric(value: Any) -> bool:
    if _finite_number(value):
        return True
    if isinstance(value, Mapping):
        return any(_has_finite_numeric(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_finite_numeric(item) for item in value)
    return False


def _validate_parameter_points(
    row: Mapping[str, Any],
    requirement: Mapping[str, Any],
    *,
    scope_info: Mapping[str, Any],
    label: str,
    errors: list[dict[str, Any]],
) -> None:
    required_points = requirement.get("parameter_points", {})
    actual_points = row.get("physical_parameter_points")
    if not isinstance(actual_points, Mapping):
        _fail(errors, "comparison_parameter_points_missing", f"{label}.physical_parameter_points is missing")
        return
    for point_name, point_spec in required_points.items():
        point = actual_points.get(point_name)
        if not isinstance(point, Mapping):
            _fail(errors, "comparison_parameter_point_empty", f"{label}.physical_parameter_points.{point_name} is empty")
            continue
        parameter = point_spec.get("parameter")
        domain = scope_info["parameter_domains"].get(parameter)
        if not isinstance(domain, Mapping) or point.get("parameter") != parameter:
            _fail(errors, "comparison_parameter_binding_mismatch", f"{label}.{point_name} is not bound to the frozen physical parameter")
            continue
        value = point.get("value")
        if not _finite_number(value):
            _fail(errors, "comparison_parameter_value_invalid", f"{label}.{point_name}.value must be finite")
            continue
        lower = float(domain["min"])
        upper = float(domain["max"])
        tolerance = max(1e-12, abs(upper - lower) * 1e-9)
        if point_name == "endpoint":
            expected = upper if point_spec.get("side") == "max" else lower
            if abs(float(value) - expected) > tolerance:
                _fail(errors, "comparison_endpoint_not_domain_boundary", f"{label}.endpoint is not the frozen physical domain boundary")
        elif not lower + tolerance < float(value) < upper - tolerance:
            _fail(errors, "comparison_internal_not_domain_interior", f"{label}.internal is not strictly inside the frozen physical parameter domain")
        if not _finite_number(point.get("sample_count")) or float(point["sample_count"]) <= 0:
            _fail(errors, "comparison_parameter_samples_invalid", f"{label}.{point_name}.sample_count must be positive")
        if not _has_finite_numeric(point.get("metrics")):
            _fail(errors, "comparison_parameter_metrics_empty", f"{label}.{point_name}.metrics must contain actual numeric evidence")


def _validate_error_metrics(
    row: Mapping[str, Any],
    requirement: Mapping[str, Any],
    *,
    scope_info: Mapping[str, Any],
    label: str,
    errors: list[dict[str, Any]],
) -> None:
    actual = row.get("actual_error_metrics")
    if not isinstance(actual, Mapping):
        _fail(errors, "comparison_error_metrics_missing", f"{label}.actual_error_metrics is missing")
        return
    budget = scope_info["observations"].get("error_budget", {})
    for metric in requirement.get("required_error_metrics", []):
        value = actual.get(metric)
        threshold = budget.get(metric)
        if not _finite_number(value) or not _finite_number(threshold) or float(value) < 0:
            _fail(errors, "comparison_error_metric_invalid", f"{label}.actual_error_metrics.{metric} must be a finite nonnegative value")
        elif float(value) > float(threshold):
            _fail(errors, "comparison_error_budget_exceeded", f"{label}.actual_error_metrics.{metric} exceeds the frozen error budget", value=value, threshold=threshold)


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
        _validate_error_metrics(row, requirement, scope_info=scope_info, label=label, errors=errors)
        _validate_parameter_points(row, requirement, scope_info=scope_info, label=label, errors=errors)
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
    if evidence.get("family_id") != scope.get("family_id") or evidence.get("scope_id") != scope.get("scope_id"):
        _fail(errors, "evidence_scope_identity_invalid", "evidence family_id/scope_id does not match the frozen scope")
    _check_scope_binding(evidence, scope_path=scope_file, scope_sha256=scope_digest, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_recipe_identity(evidence, scope_info["recipe"], "evidence", errors)
    if _canonical(evidence.get("observations")) != _canonical(scope_info["observations"]):
        _fail(errors, "observation_contract_mismatch", "evidence observations differ from frozen physical scales/error budget/definitions")

    reuse = evidence.get("reuse")
    if reuse is not None:
        _validate_reuse_equivalence(
            reuse,
            scope=scope,
            evidence_path=evidence_file,
            data_root=root,
            errors=errors,
            bound_artifacts=bound_artifacts,
        )

    _validate_case_rows(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_reference_views(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_spatial_comparisons(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)
    _validate_comparisons(evidence, scope_info=scope_info, evidence_path=evidence_file, data_root=root, errors=errors, bound_artifacts=bound_artifacts)

    # The artifact hash list is part of the verdict itself.  The root process
    # can bind this exact verdict to its separate approved index later.
    implementation_path = Path(__file__).resolve()
    implementation_hash = sha256_file(implementation_path)
    eligible = not errors
    return {
        "schema": VERDICT_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": scope.get("family_id"),
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
            "spatial_error_acceptance": not any(item["code"].startswith("spatial_") for item in errors),
            "independent_comparisons": not any(item["code"].startswith("comparison_") for item in errors),
            "split_and_view_leakage": not any(item["code"] in {"scope_parent_split_leak", "case_outside_scope", "reference_view_outside_scope", "comparison_outside_scope", "comparison_physical_binding_mismatch"} for item in errors),
            "current_full_state_evidence": not any(item["code"].startswith(("state_", "qi_report_", "qi_fluid_", "qi_h5_")) or item["code"] == "reuse_fluid_only_forbidden" for item in errors),
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
