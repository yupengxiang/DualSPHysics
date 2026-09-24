#!/usr/bin/env python3
"""Prepare an evidence-gated production proposal for the F4 tall-wall scope.

The qualification matrix and its v2 evaluator are immutable inputs to this
module.  The connector deliberately does not use ``core_production_runner``:
that runner has the old 0.6 m F4 protocols.  This module registers the fresh
1.2 m scope in memory, derives production configurations from a hash-checked
tall-wall qualification template, and reports the fixed 32-case 8 -> 24
batch decision.  It never calls GenCase, the solver, a scheduler, or a
ledger.

The current v2 receipt is incomplete, so the checked-in proposal contains the
32-case design and a blocked batch decision but no prepared production input
or job submission.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping


# Keep source imports frozen to this checkout.  An asset/lab root is passed as
# data to callers; it must never replace this source root on sys.path.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_production import (
    FIRST_EIGHT,
    QUALIFICATION_SCHEMA,
    next_batch,
    register_scope,
)


SCHEMA = "core.f4.tallwall120.production_connector.v1"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
QUALIFICATION_REVISION_ID = "F4_tallwall120_13plus2_v2"
CONNECTOR_REVISION_ID = "F4_tallwall120_production_8to32_v1"
QUALIFICATION_EVALUATION_SCHEMA = "core.f4.tallwall120.qualification_evaluation.v2"
QUALIFICATION_BINDING_SCHEMA = "core.f4.tallwall120.production_qualification_binding.v1"
RECIPE_ID = "F4_mdbc_laminar_nu1e6_tallwall120_v1"
RECIPE = "mdbc_native"
PARAMETER_NAME = "drop_left_x_m"
PARAMETER_RANGE = (0.25, 0.47)
# These are the five preregistered qualification coordinates from the frozen
# tall-wall design.  Production registration must be reconstructed from this
# set; accepting a caller-supplied replacement would let a changed matrix
# silently change the fixed 32-point scope.
QUALIFICATION_POINTS = (0.25, 0.305, 0.36, 0.415, 0.47)
HEIGHT_M = 1.2
OBSERVER_VERSION = "fixed_015m_vertical_reference060_v2"
QUALIFICATION_CELL_COUNT = 15
PRODUCTION_CASE_COUNT = 32
TEMPLATE_INDEX = 4  # q=.5, dp=.0075, spatial; the production-resolution template
OUTPUT_INTERVAL_S = 0.02
EXECUTION_WINDOW_S = 4.34
MAXIMUM_EXTENSION_S = 8.68


class ConnectorError(ValueError):
    """Raised when a scope identity or hash contract fails closed."""


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ConnectorError(f"required JSON is missing: {path}")
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConnectorError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def path_ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ConnectorError(f"{role} is missing: {path}")
    return {"path": str(path), "sha256": digest(path), "role": role}


def verify_ref(path: Path, expected: str, role: str) -> dict[str, Any]:
    ref = path_ref(path, role)
    if ref["sha256"] != expected:
        raise ConnectorError(
            f"{role} hash mismatch: {path}: {ref['sha256']} != {expected}"
        )
    return ref


def _almost(value: Any, expected: float, *, tolerance: float = 1e-12) -> bool:
    try:
        return math.isfinite(float(value)) and abs(float(value) - expected) <= tolerance
    except (TypeError, ValueError):
        return False


def _same(value: Any, expected: Any) -> bool:
    return value == expected


def _scope_error(label: str, value: Any, expected: Any) -> ConnectorError:
    return ConnectorError(f"{label} mismatch: {value!r} != {expected!r}")


def _require_evaluation_schema(evaluation: Mapping[str, Any]) -> None:
    schema = evaluation.get("schema")
    if type(schema) is not str or schema != QUALIFICATION_EVALUATION_SCHEMA:
        raise ConnectorError("qualification evaluation schema mismatch")


def validate_design(design: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the 15-cell physical design and return its scalar points."""
    if design.get("schema") != "core.f4.tallwall120.qualification_design.v1":
        raise ConnectorError("qualification design schema is not tallwall120 v1")
    for key, expected in (
        ("family", FAMILY),
        ("scope_id", SCOPE_ID),
        ("revision_id", QUALIFICATION_REVISION_ID),
        ("qualification_claim", "none"),
    ):
        if design.get(key) != expected:
            raise _scope_error(f"qualification design {key}", design.get(key), expected)
    if design.get("qualification_only") is not True:
        raise ConnectorError("qualification design is not qualification-only")
    if design.get("qualification_inheritance") is not False:
        raise ConnectorError("qualification inheritance is not explicitly false")
    if design.get("cell_count") != QUALIFICATION_CELL_COUNT or len(design.get("cells", [])) != 15:
        raise ConnectorError("qualification design is not the complete 15-cell denominator")
    geometry = design.get("continuum_geometry", {})
    if not _almost(geometry.get("container_height_m"), HEIGHT_M):
        raise ConnectorError("qualification design is not the 1.2 m tall-wall geometry")
    if geometry.get("pool") != {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18]}:
        raise ConnectorError("qualification design pool geometry changed")
    observer = design.get("observer", {})
    if observer.get("version") != OBSERVER_VERSION:
        raise ConnectorError("qualification design observer version mismatch")
    registered_window = design.get("registered_window", {})
    if not _almost(registered_window.get("initial_time_max_s"), EXECUTION_WINDOW_S):
        raise ConnectorError("qualification design execution window mismatch")
    if not _almost(registered_window.get("maximum_extended_time_max_s"), MAXIMUM_EXTENSION_S):
        raise ConnectorError("qualification design extension window mismatch")

    values: list[float] = []
    ranges: set[tuple[float, float]] = set()
    for row in design["cells"]:
        if not isinstance(row, Mapping):
            raise ConnectorError("qualification design cell is not an object")
        cfg = row
        if cfg.get("family") != FAMILY or cfg.get("scope_id") != SCOPE_ID:
            raise ConnectorError("qualification design cell belongs to another scope")
        if cfg.get("stage") != "qualification" or cfg.get("qualification_only") is not True:
            raise ConnectorError("qualification design cell is not qualification-only")
        parameter = cfg.get("parameter", {})
        if parameter.get("name") != PARAMETER_NAME:
            raise ConnectorError("qualification parameter name mismatch")
        try:
            value = float(parameter["value"])
            lower, upper = (float(x) for x in parameter["candidate_range"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError("qualification scalar parameter is malformed") from exc
        if not all(math.isfinite(x) for x in (value, lower, upper)) or lower >= upper:
            raise ConnectorError("qualification scalar range is not finite and ordered")
        values.append(value)
        ranges.add((lower, upper))
    if ranges != {PARAMETER_RANGE}:
        raise ConnectorError(f"qualification scalar range mismatch: {ranges!r}")
    qualification_points = sorted(set(values))
    if len(qualification_points) != 5:
        raise ConnectorError("qualification design must expose five physical points")
    if len(qualification_points) != len(QUALIFICATION_POINTS) or any(
        not _almost(actual, expected) for actual, expected in zip(qualification_points, QUALIFICATION_POINTS)
    ):
        raise ConnectorError(
            f"qualification design points do not match the frozen registration: {qualification_points!r}"
        )
    return {
        "scope_id": SCOPE_ID,
        "revision_id": QUALIFICATION_REVISION_ID,
        "parameter_name": PARAMETER_NAME,
        "parameter_range": list(PARAMETER_RANGE),
        "qualification_points": qualification_points,
        "height_m": HEIGHT_M,
        "observer_version": OBSERVER_VERSION,
        "registered_window_s": EXECUTION_WINDOW_S,
        "maximum_extension_s": MAXIMUM_EXTENSION_S,
    }


def _canonical_production_registration() -> dict[str, Any]:
    """Rebuild the immutable 32-point registration from frozen constants."""
    registered = register_scope(
        FAMILY,
        SCOPE_ID,
        PARAMETER_NAME,
        PARAMETER_RANGE[0],
        PARAMETER_RANGE[1],
        list(QUALIFICATION_POINTS),
    )
    for row in registered["cases"]:
        row.update(
            parameter_range=list(PARAMETER_RANGE),
            qualification_points=list(QUALIFICATION_POINTS),
            revision_id=QUALIFICATION_REVISION_ID,
            recipe_id=RECIPE_ID,
            recipe=RECIPE,
            container_height_m=HEIGHT_M,
            observer_version=OBSERVER_VERSION,
            production_connector_revision=CONNECTOR_REVISION_ID,
            qualification_inheritance=False,
        )
    registered.update(
        {
            "scope_id": SCOPE_ID,
            "revision_id": QUALIFICATION_REVISION_ID,
            "recipe_id": RECIPE_ID,
            "recipe": RECIPE,
            "production_connector_revision": CONNECTOR_REVISION_ID,
            "production_resolution_m": 0.0075,
            "container_height_m": HEIGHT_M,
            "observer_version": OBSERVER_VERSION,
            "registered_window_s": EXECUTION_WINDOW_S,
            "maximum_extended_window_s": MAXIMUM_EXTENSION_S,
            "qualification_inheritance": False,
        }
    )
    return registered


def _validate_canonical_production_row(row: Mapping[str, Any]) -> None:
    """Reject a row whose scalar/index/split/lineage identity was edited."""
    index = row.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < PRODUCTION_CASE_COUNT:
        raise ConnectorError(f"production row index is outside the fixed 0..31 denominator: {index!r}")
    expected = _canonical_production_registration()["cases"][index]
    required_equal = (
        "index",
        "split",
        "case_id",
        "family",
        "scope_id",
        "stage",
        "qualification_only",
        "first_batch",
        "revision_id",
        "recipe_id",
        "recipe",
        "container_height_m",
        "observer_version",
        "production_connector_revision",
        "qualification_inheritance",
    )
    for key in required_equal:
        if row.get(key) != expected.get(key):
            raise ConnectorError(
                f"production row {index} {key} differs from frozen registration: "
                f"{row.get(key)!r} != {expected.get(key)!r}"
            )
    if not _almost(row.get("parameter"), expected["parameter"]):
        raise ConnectorError(f"production row {index} parameter differs from frozen registration")
    if row.get("parameter_range") != list(PARAMETER_RANGE):
        raise ConnectorError(f"production row {index} parameter range differs from frozen registration")
    supplied_points = row.get("qualification_points")
    if not isinstance(supplied_points, list) or len(supplied_points) != len(QUALIFICATION_POINTS) or any(
        not _almost(actual, expected_point)
        for actual, expected_point in zip(supplied_points, QUALIFICATION_POINTS)
    ):
        raise ConnectorError(f"production row {index} qualification points differ from frozen registration")


def validate_production_design(production: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild and compare the entire fixed 32-case production registration."""
    expected = _canonical_production_registration()
    for key, expected_value in (
        ("schema", "core.production_design.v1"),
        ("family", FAMILY),
        ("scope_id", SCOPE_ID),
        ("parameter_name", PARAMETER_NAME),
        ("parameter_range", list(PARAMETER_RANGE)),
        ("case_count", PRODUCTION_CASE_COUNT),
        ("first_batch_indices", list(FIRST_EIGHT)),
        ("qualification_parameters", list(QUALIFICATION_POINTS)),
        ("revision_id", QUALIFICATION_REVISION_ID),
        ("recipe_id", RECIPE_ID),
        ("recipe", RECIPE),
        ("production_connector_revision", CONNECTOR_REVISION_ID),
        ("production_resolution_m", 0.0075),
        ("container_height_m", HEIGHT_M),
        ("observer_version", OBSERVER_VERSION),
        ("registered_window_s", EXECUTION_WINDOW_S),
        ("maximum_extended_window_s", MAXIMUM_EXTENSION_S),
        ("qualification_inheritance", False),
    ):
        actual = production.get(key)
        if isinstance(expected_value, float):
            same = _almost(actual, expected_value)
        elif key == "qualification_parameters":
            same = isinstance(actual, list) and len(actual) == len(expected_value) and all(
                _almost(value, target) for value, target in zip(actual, expected_value)
            )
        else:
            same = actual == expected_value
        if not same:
            raise ConnectorError(f"production design {key} differs from frozen registration: {actual!r} != {expected_value!r}")
    rows = production.get("cases")
    if not isinstance(rows, list) or len(rows) != PRODUCTION_CASE_COUNT:
        raise ConnectorError("production design must contain exactly 32 cases")
    indices = [row.get("index") for row in rows if isinstance(row, Mapping)]
    if len(indices) != PRODUCTION_CASE_COUNT or sorted(indices) != list(range(PRODUCTION_CASE_COUNT)):
        raise ConnectorError("production design indices are not the fixed 0..31 sequence")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ConnectorError("production design case is not an object")
        _validate_canonical_production_row(row)
    # Compare the generated canonical rows for fields that define identity;
    # derived lineage fields are checked again when a production config is made.
    return {
        "case_count": PRODUCTION_CASE_COUNT,
        "first_batch_indices": list(FIRST_EIGHT),
        "qualification_parameters": list(QUALIFICATION_POINTS),
        "case_ids": [row["case_id"] for row in expected["cases"]],
    }


def validate_manifest(manifest: Mapping[str, Any], design: Mapping[str, Any]) -> None:
    """Check the evaluator v2 accounting and current cell12 reuse contract."""
    for key, expected in (
        ("schema", "core.f4.tallwall120.qualification_evaluator.v2"),
        ("family", FAMILY),
        ("scope_id", SCOPE_ID),
        ("revision_id", QUALIFICATION_REVISION_ID),
        ("qualification_claim", "none"),
    ):
        if manifest.get(key) != expected:
            raise _scope_error(f"evaluator manifest {key}", manifest.get(key), expected)
    if manifest.get("qualification_only") is not True:
        raise ConnectorError("evaluator manifest is not qualification-only")
    if manifest.get("matrix_denominator") != QUALIFICATION_CELL_COUNT:
        raise ConnectorError("evaluator denominator is not 15")
    accounting = manifest.get("cell_accounting", {})
    if set(accounting.get("scheduled_solver_cells", [])) | set(accounting.get("reused_canary_cells", [])) != set(range(15)):
        raise ConnectorError("evaluator cell accounting does not cover 15 cells")
    if set(accounting.get("reused_canary_cells", [])) != {12} or len(accounting.get("scheduled_solver_cells", [])) != 14:
        raise ConnectorError("evaluator must have fourteen scheduled cells and reused cell12")
    if len(manifest.get("cells", [])) != QUALIFICATION_CELL_COUNT:
        raise ConnectorError("evaluator cell list is not complete")

    observer = manifest.get("observer", {})
    if observer.get("version") != OBSERVER_VERSION:
        raise ConnectorError("evaluator observer version mismatch")
    if observer.get("legacy_event_rows_unchanged") is not True:
        raise ConnectorError("evaluator observer legacy event contract is not bound")

    reuse = manifest.get("cell12_reuse", {})
    for key, expected in (
        ("index", 12),
        ("new_candidate_bi4_executed", False),
        ("solver_rerun", False),
        ("reuse_qualifies_range", False),
        ("range_qualification_inherited", False),
    ):
        if reuse.get(key) != expected:
            raise ConnectorError(f"cell12 reuse contract {key} mismatch")
    equivalence = reuse.get("equivalence_contract", {})
    for key in ("semantic_config_all_equal", "native_ids_positions_velocities_density_exact", "mdbc_normal_arrays_exact"):
        if equivalence.get(key) is not True:
            raise ConnectorError(f"cell12 equivalence contract {key} is not exact")
    eq_v2 = reuse.get("evidence_bindings", {}).get("cell12_equivalence_v2")
    if not isinstance(eq_v2, Mapping) or not isinstance(eq_v2.get("sha256"), str):
        raise ConnectorError("cell12 v2 equivalence binding is missing")


REQUIRED_EVALUATOR_CHECKS = (
    "static_contract",
    "matrix_complete",
    "all_case_hard_mass_event_gates",
    "spatial",
    "independent_checks",
    "time_and_output",
    "cell12_reuse_verified",
    "cell12_reuse_does_not_inherit_qualification",
)


def _verify_product_ref(ref: Any, label: str) -> bool:
    """Verify one evaluator result artifact binding on the local filesystem."""
    if not isinstance(ref, Mapping):
        raise ConnectorError(f"{label} binding is missing")
    path_value, expected = ref.get("path"), ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(expected, str) or len(expected) != 64:
        raise ConnectorError(f"{label} binding has no path/sha256")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ConnectorError(f"{label} artifact is missing: {path}")
    actual = digest(path)
    if actual != expected:
        raise ConnectorError(f"{label} artifact hash mismatch: {actual} != {expected}")
    return True


def _load_bound_json(ref: Any, label: str) -> tuple[dict[str, Any], Path]:
    """Verify a hash-bound JSON artifact and return its decoded object."""
    _verify_product_ref(ref, label)
    path = Path(ref["path"]).expanduser().resolve()
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ConnectorError(f"{label} must contain a JSON object: {path}")
    return value, path


def _verify_output_index(
    execution: Mapping[str, Any],
    artifact_refs: Mapping[str, Mapping[str, Any]],
    label: str,
) -> None:
    """Bind product hashes to a succeeded native/archive execution receipt."""
    outputs = execution.get("outputs")
    if not isinstance(outputs, list):
        raise ConnectorError(f"{label} has no output index")
    by_path = {
        str(row.get("path")): row.get("sha256")
        for row in outputs
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    for name, ref in artifact_refs.items():
        expected = ref.get("sha256")
        candidates = {name, f"product/{name}"}
        if name == "trajectory.h5":
            candidates.add("product/trajectory.h5")
        if not any(by_path.get(candidate) == expected for candidate in candidates):
            raise ConnectorError(
                f"{label} does not bind {name} to its observed hash {expected}"
            )


def _verify_native_receipt(
    ref: Any,
    artifact_refs: Mapping[str, Mapping[str, Any]],
    label: str,
) -> tuple[dict[str, Any], Path]:
    """Verify a succeeded archive or core-runtime execution receipt."""
    payload, path = _load_bound_json(ref, label)
    _verify_native_payload(payload, artifact_refs, label)
    return payload, path


def _verify_native_payload(
    payload: Mapping[str, Any],
    artifact_refs: Mapping[str, Mapping[str, Any]],
    label: str,
) -> None:
    """Verify the decoded portion of a native/archive execution receipt."""
    if payload.get("schema") not in {"core.verified_archive.v1", "core.execution_receipt.v1"}:
        raise ConnectorError(f"{label} has an unsupported execution schema")
    if payload.get("execution_status") != "succeeded":
        raise ConnectorError(f"{label} is not a succeeded execution")
    _verify_output_index(payload, artifact_refs, label)


def _receipt_summary(evaluation: Mapping[str, Any], manifest_path: Path) -> dict[str, Any]:
    """Derive gates from every evaluator cell and its bound product files."""
    _require_evaluation_schema(evaluation)
    for key, expected in (
        ("scope_id", SCOPE_ID),
        ("revision_id", QUALIFICATION_REVISION_ID),
    ):
        if evaluation.get(key) != expected:
            raise _scope_error(f"qualification evaluation {key}", evaluation.get(key), expected)
    if evaluation.get("static_contract_pass") is not True:
        raise ConnectorError("qualification evaluator static contract is not passing")
    if evaluation.get("qualification_claim") != "none":
        raise ConnectorError("qualification evaluator claim policy changed")
    expected_manifest_hash = digest(manifest_path)
    if evaluation.get("static_manifest_sha256") != expected_manifest_hash:
        raise ConnectorError("qualification evaluation is not bound to this evaluator manifest")
    manifest = load_json(manifest_path)
    manifest_cells = {
        int(row["index"]): row
        for row in manifest.get("cells", [])
        if isinstance(row, Mapping) and isinstance(row.get("index"), int)
    }
    if set(manifest_cells) != set(range(QUALIFICATION_CELL_COUNT)):
        raise ConnectorError("qualification evaluator manifest cell denominator is not 15")
    cells = evaluation.get("cells")
    if not isinstance(cells, list):
        raise ConnectorError("qualification evaluator cells are not a list")
    indices = [cell.get("index") for cell in cells if isinstance(cell, Mapping)]
    if len(indices) != len(cells) or len(set(indices)) != len(indices):
        raise ConnectorError("qualification evaluator cell indices are not unique")
    # The v2 evaluator already checked these hashes before emitting a result;
    # recheck every product and execution binding here so a hand-edited result
    # cannot open production.
    artifact_bindings_verified = True
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise ConnectorError("qualification evaluator cell is not an object")
        index = cell.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index not in manifest_cells:
            raise ConnectorError(f"qualification evaluator cell index is outside the 15-cell denominator: {index!r}")
        expected_case_id = manifest_cells[index].get("case_id")
        if cell.get("case_id") != expected_case_id:
            raise ConnectorError(f"qualification evaluator cell {index} case identity mismatch")
        audit_ref = cell.get("audit")
        observations_ref = cell.get("observations")
        if not isinstance(audit_ref, Mapping) or not isinstance(observations_ref, Mapping):
            raise ConnectorError(f"cell {index} is missing bound audit/observations artifacts")
        audit, audit_path = _load_bound_json(audit_ref, f"cell {index} audit")
        observations, observations_path = _load_bound_json(
            observations_ref, f"cell {index} observations"
        )
        if not isinstance(observations.get("time_s"), list) or len(observations["time_s"]) < 2:
            raise ConnectorError(f"cell {index} observations lack a complete time axis")

        if index == 12:
            # Cell12 is a deliberate reuse of the executed q=.75/fine canary;
            # its physical case_id predates the 15-cell matrix case_id.  Bind
            # it exactly to the manifest evidence instead of silently
            # accepting any passing audit.
            evidence = manifest.get("cell12_reuse", {}).get("evidence_bindings", {})
            expected_audit = evidence.get("canary_audit")
            expected_obs = evidence.get("canary_observations_v2")
            expected_result = evidence.get("canary_result")
            for actual, expected, label in (
                (audit_ref, expected_audit, "cell 12 canary audit"),
                (observations_ref, expected_obs, "cell 12 canary observations"),
            ):
                if not isinstance(expected, Mapping) or actual.get("path") != expected.get("path") or actual.get("sha256") != expected.get("sha256"):
                    raise ConnectorError(f"{label} binding changed")
            result, result_path = _load_bound_json(expected_result, "cell 12 canary result")
            product_case_id = audit.get("case_id")
            if product_case_id is None or result.get("case_id") != product_case_id:
                raise ConnectorError("cell 12 canary product identity mismatch")
        else:
            if audit.get("case_id") != expected_case_id:
                raise ConnectorError(f"cell {index} audit case identity mismatch")
            result_path = audit_path.parent / "result.json"
            result_ref = path_ref(result_path, f"cell {index} result")
            result = load_json(result_path)
            if result.get("case_id") != expected_case_id:
                raise ConnectorError(f"cell {index} result case identity mismatch")
            conversion = result.get("conversion")
            if not isinstance(conversion, Mapping):
                raise ConnectorError(f"cell {index} result lacks trajectory hash binding")
            external = manifest.get("external_result_bindings", {}).get(str(index))
            external_trajectory = external.get("trajectory") if isinstance(external, Mapping) else None
            if isinstance(external_trajectory, Mapping):
                _verify_product_ref(external_trajectory, f"cell {index} external trajectory")
                trajectory_ref = dict(external_trajectory)
            else:
                trajectory_path = Path(str(conversion.get("hdf5", ""))).expanduser().resolve()
                if not trajectory_path.is_file():
                    # Archive and results-v2 products retain the solver's
                    # original absolute conversion path; the sibling product
                    # is the authoritative transferred copy.
                    trajectory_path = audit_path.parent / "trajectory.h5"
                trajectory_ref = path_ref(trajectory_path, f"cell {index} trajectory")
            if conversion.get("sha256") != trajectory_ref["sha256"]:
                raise ConnectorError(f"cell {index} result/trajectory hash mismatch")
            actual_refs = {
                "result": result_ref,
                "audit": dict(audit_ref),
                "observations": dict(observations_ref),
                "trajectory": trajectory_ref,
            }
            if isinstance(external, Mapping):
                for name, actual in actual_refs.items():
                    expected = external.get(name)
                    if not isinstance(expected, Mapping) or actual.get("path") != expected.get("path") or actual.get("sha256") != expected.get("sha256"):
                        raise ConnectorError(f"cell {index} {name} binding changed")
                execution_binding = external.get("archive_receipt")
                if isinstance(execution_binding, Mapping):
                    _verify_native_receipt(
                        execution_binding,
                        {
                            "product/result.json": actual_refs["result"],
                            "product/audit.json": actual_refs["audit"],
                            "product/observations.json": actual_refs["observations"],
                            "product/trajectory.h5": actual_refs["trajectory"],
                        },
                        f"cell {index} archive receipt",
                    )
                else:
                    integration_binding = external.get("root_integration")
                    if not isinstance(integration_binding, Mapping):
                        raise ConnectorError(f"cell {index} has no native execution receipt binding")
                    integration, _ = _load_bound_json(
                        integration_binding, f"cell {index} root integration receipt"
                    )
                    execution = integration.get("receipt")
                    if not isinstance(execution, Mapping):
                        raise ConnectorError(f"cell {index} root integration lacks native receipt")
                    _verify_native_payload(
                        execution,
                        {
                            "product/result.json": actual_refs["result"],
                            "product/audit.json": actual_refs["audit"],
                            "product/observations.json": actual_refs["observations"],
                            "product/trajectory.h5": actual_refs["trajectory"],
                        },
                        f"cell {index} root execution receipt",
                    )
            else:
                execution_binding = cell.get("archive_receipt")
                if not isinstance(execution_binding, Mapping):
                    raise ConnectorError(f"cell {index} has no native execution receipt binding")
                _verify_native_receipt(
                    execution_binding,
                    {
                        "product/result.json": result_ref,
                        "product/audit.json": dict(audit_ref),
                        "product/observations.json": dict(observations_ref),
                        "product/trajectory.h5": trajectory_ref,
                    },
                    f"cell {index} archive receipt",
                )
        actual_gate = all(
            audit.get(field) is True and result.get(field) is True
            for field in ("hard_integrity_pass", "source_mass_gate_pass", "event_window_complete")
        )
        if cell.get("passed") is not actual_gate:
            raise ConnectorError(f"cell {index} passed flag does not match product gates")
        if index != 12 and cell.get("artifact_hash_gate") is not True:
            raise ConnectorError(f"cell {index} output hash gate is not passing")
    expected_indices = set(range(QUALIFICATION_CELL_COUNT))
    complete_cells = set(indices) == expected_indices
    missing = evaluation.get("missing", [])
    failures = evaluation.get("failures", [])
    if not isinstance(missing, list) or not isinstance(failures, list):
        raise ConnectorError("qualification evaluator missing/failures are not lists")
    all_cells_passed = all(cell.get("passed") is True for cell in cells)
    derived_matrix_complete = complete_cells and not missing and not failures and all_cells_passed
    checks = evaluation.get("checks", {})
    if not isinstance(checks, Mapping):
        checks = {}
    normalized_checks = {key: checks.get(key) is True for key in REQUIRED_EVALUATOR_CHECKS}
    derived_t1 = derived_matrix_complete and all(normalized_checks.values())
    declared_matrix = evaluation.get("matrix_complete")
    declared_t1 = evaluation.get("T1_numerical")
    declaration_consistent = declared_matrix is derived_matrix_complete and declared_t1 is derived_t1
    if not declaration_consistent:
        raise ConnectorError(
            "qualification evaluator booleans do not match its cell/audit/check evidence"
        )
    return {
        "schema": QUALIFICATION_SCHEMA,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "matrix_complete": derived_matrix_complete,
        "T1_numerical": derived_t1,
        "static_contract_pass": True,
        "missing": missing,
        "failures": failures,
        "cell_indices": sorted(indices),
        "cell_count": len(cells),
        "all_cells_passed": all_cells_passed,
        "checks": normalized_checks,
        "artifact_bindings_verified": artifact_bindings_verified,
        "declaration_consistent": declaration_consistent,
        "promotion_status": evaluation.get("promotion_status"),
    }


def validate_evaluation(
    evaluation: Mapping[str, Any],
    manifest_path: Path,
    *,
    recomputed_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a v2 result and optionally compare it with a fresh evaluator tick.

    The recomputed result is authoritative.  A stale or hand-edited supplied
    result is retained as provenance but cannot become a production binding.
    """
    declared = _receipt_summary(evaluation, manifest_path)
    if recomputed_result is None:
        declared["reevaluation_match"] = True
        declared["binding_ready"] = True
        return declared
    recomputed = _receipt_summary(recomputed_result, manifest_path)
    same = (
        declared["matrix_complete"] == recomputed["matrix_complete"]
        and declared["T1_numerical"] == recomputed["T1_numerical"]
        and declared["cell_indices"] == recomputed["cell_indices"]
        and declared["missing"] == recomputed["missing"]
        and declared["failures"] == recomputed["failures"]
        and declared["checks"] == recomputed["checks"]
    )
    result = dict(recomputed)
    result["supplied_receipt"] = declared
    result["reevaluation_match"] = same
    result["binding_ready"] = True
    return result


def tick_qualification(
    *, manifest_path: Path, runtime_root: Path, archive_root: Path
) -> dict[str, Any]:
    """Re-run the frozen v2 evaluator against current runtime/archive receipts.

    This is the root-owned, read-only tick.  It performs no queue or ledger
    action and is safe to repeat after more archives arrive.
    """
    from scripts.f4_tallwall_qualification_evaluator_v2 import evaluate

    manifest_path = Path(manifest_path).resolve()
    runtime_root = Path(runtime_root).resolve()
    archive_root = Path(archive_root).resolve()
    result = evaluate(manifest_path, runtime_root=runtime_root, archive_root=archive_root)
    summary = _receipt_summary(result, manifest_path)
    binding = {
        "schema": QUALIFICATION_BINDING_SCHEMA,
        "manifest_path": str(manifest_path),
        "manifest_sha256": digest(manifest_path),
        "runtime_root": str(runtime_root),
        "archive_root": str(archive_root),
        "reevaluation_sha256": canonical_digest(result),
        "matrix_complete": summary["matrix_complete"],
        "T1_numerical": summary["T1_numerical"],
        "cell_indices": summary["cell_indices"],
        "missing": summary["missing"],
        "failures": summary["failures"],
        "checks": summary["checks"],
        "artifact_bindings_verified": summary["artifact_bindings_verified"],
        "verified": True,
    }
    summary["binding"] = binding
    summary["reevaluated_result"] = result
    return {"result": result, "summary": summary, "binding": binding}


def validate_template_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure a production template really is the qualified 1.2 m recipe."""
    for key, expected in (
        ("schema", "core.cfd.v1"),
        ("family", FAMILY),
        ("scope_id", SCOPE_ID),
        ("revision_id", QUALIFICATION_REVISION_ID),
        ("recipe_id", RECIPE_ID),
        ("recipe", RECIPE),
        ("stage", "qualification"),
        ("qualification_claim", "none"),
        ("qualification_only", True),
        ("split", "qualification_only"),
        ("viscosity_formulation", "laminar"),
    ):
        if config.get(key) != expected:
            raise _scope_error(f"template {key}", config.get(key), expected)
    if config.get("observation_version") != OBSERVER_VERSION:
        raise _scope_error(
            "template observer version", config.get("observation_version"), OBSERVER_VERSION
        )
    if not _almost(config.get("container_height_m"), HEIGHT_M):
        raise ConnectorError("template container height is not 1.2 m")
    bounds = config.get("wall_bounds", {})
    if not _almost(bounds.get("zmax"), HEIGHT_M):
        raise ConnectorError("template wall zmax is not 1.2 m")
    if config.get("open_faces") != ["top"] or set(config.get("closed_faces", [])) != {"bottom", "left", "right", "front", "back"}:
        raise ConnectorError("template wall face contract is not tallwall120")
    if config.get("pool") != {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18], "mkfluid": 0}:
        raise ConnectorError("template pool geometry is not the qualified resting pool")
    if config.get("qualification_inheritance") is not False:
        raise ConnectorError("template permits inherited qualification")
    return {
        "scope_id": SCOPE_ID,
        "revision_id": QUALIFICATION_REVISION_ID,
        "recipe_id": RECIPE_ID,
        "dp_m": config.get("dp_m"),
        "container_height_m": config.get("container_height_m"),
        "wall_zmax_m": bounds.get("zmax"),
        "observer_version": config.get("observation_version"),
        "qualification_only": True,
    }


def build_production_design(design: Mapping[str, Any]) -> dict[str, Any]:
    """Create the immutable in-memory 32-point scalar registration."""
    validate_design(design)
    registered = _canonical_production_registration()
    registered["qualification_status"] = "requires_hash_verified_T1_receipt"
    validate_production_design(registered)
    return registered


def derive_production_config(
    template_config: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    qualification_receipt_sha256: str,
    template_prepared_sha256: str,
) -> dict[str, Any]:
    """Derive one production config while retaining the 1.2 m template."""
    validate_template_config(template_config)
    _validate_canonical_production_row(row)
    if row.get("scope_id") != SCOPE_ID or row.get("family") != FAMILY:
        raise ConnectorError("production row belongs to another scope")
    if row.get("stage") != "production" or row.get("qualification_only") is not False:
        raise ConnectorError("production row is still qualification-only")
    lower, upper = (float(x) for x in row.get("parameter_range", PARAMETER_RANGE))
    parameter = float(row["parameter"])
    if not lower < parameter < upper:
        raise ConnectorError("production parameter is outside the registered open interval")
    q = (parameter - lower) / (upper - lower)
    config = deepcopy(dict(template_config))
    config.update(
        {
            "scope_id": SCOPE_ID,
            "revision_id": QUALIFICATION_REVISION_ID,
            "case_id": str(row["case_id"]),
            "stage": "production",
            "qualification_claim": "none",
            "qualified": False,
            "qualification_only": False,
            "split": row["split"],
            "design_cell": "production",
            "physical_case_id": f"{SCOPE_ID}_DEV_{int(row['index']):02d}",
            "lineage_group_id": f"{SCOPE_ID}_DEV_{int(row['index']):02d}",
            "source_scope_qualification_inherited": False,
            "qualification_receipt_sha256": qualification_receipt_sha256,
            "source_template_prepared_sha256": template_prepared_sha256,
            "production_connector_revision": CONNECTOR_REVISION_ID,
            "container_height_m": HEIGHT_M,
            "observation_version": OBSERVER_VERSION,
            "parameter": {
                "name": PARAMETER_NAME,
                "value": parameter,
                "q": q,
                "candidate_range": [lower, upper],
            },
        }
    )
    drop = deepcopy(config.get("drop", {}))
    low = list(drop.get("low", []))
    if len(low) != 3:
        raise ConnectorError("template drop geometry is malformed")
    low[0] = parameter
    drop["low"] = low
    config["drop"] = drop
    bounds = deepcopy(config.get("wall_bounds", {}))
    bounds["zmax"] = HEIGHT_M
    config["wall_bounds"] = bounds
    return config


def _job_input_closure(prepared_path: Path, prepared: Mapping[str, Any], lab_root: Path) -> list[dict[str, str]]:
    """Expand the prepared input closure for a future core_runtime job."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw: Any, role: str) -> None:
        path = Path(str(raw)).expanduser().resolve()
        if not path.is_file():
            raise ConnectorError(f"production job input is missing ({role}): {path}")
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        entries.append({"path": key, "sha256": digest(path), "role": role})

    add(prepared_path, "prepared production case")
    add(prepared.get("solver_binary"), "solver binary")
    if prepared.get("decoder"):
        add(prepared["decoder"], "native decoder")
    add(Path(lab_root) / "scripts/core_cfd.py", "frozen CFD source")
    for path in prepared.get("inputs", []):
        add(path, "prepared CFD input")
    return entries


def production_job_spec(
    prepared_path: Path,
    row: Mapping[str, Any],
    *,
    lab_root: Path,
    batch_status: str,
    qualification_receipt_sha256: str,
    production_design_sha256: str,
) -> dict[str, Any]:
    """Build one scheduler-neutral job spec from an already prepared case."""
    _validate_canonical_production_row(row)
    prepared_path = Path(prepared_path).resolve()
    prepared = load_json(prepared_path)
    config = prepared.get("config", {})
    if config.get("scope_id") != SCOPE_ID or config.get("stage") != "production":
        raise ConnectorError("prepared production case has wrong scope or stage")
    if config.get("qualification_only") is not False or config.get("container_height_m") != HEIGHT_M:
        raise ConnectorError("prepared production case is not the 1.2 m production lineage")
    python = Path(lab_root).resolve() / ".venv/bin/python"
    job_id = f"f4-tallwall120-production-dev-{int(row['index']):02d}"
    return {
        "schema": "core.cfd.job.v1",
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "production",
        "category": "production_first_8" if batch_status == "first_8" else "production_remaining_24",
        "host": "scheduler-selected",
        "source_lab": str(Path(lab_root).resolve()),
        "cwd": str(Path(lab_root).resolve()),
        "argv": [
            str(python),
            str((Path(lab_root).resolve() / "scripts/core_cfd.py").resolve()),
            "--lab-root",
            str(Path(lab_root).resolve()),
            "run",
            "--prepared",
            str(prepared_path),
            "--output",
            "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json",
            "product/trajectory.h5",
            "product/audit.json",
            "product/observations.json",
        ],
        "resources": {
            "cpu_cores": 2,
            "ram_mib": 24576,
            "gpu_peak_mib": 6144,
            "io_weight": 2,
        },
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none; production evidence pending",
        "qualification_only": False,
        "split": row["split"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "input_files": _job_input_closure(prepared_path, prepared, lab_root),
        "prepared_case_id": config.get("case_id"),
        "scope_id": SCOPE_ID,
        "revision_id": QUALIFICATION_REVISION_ID,
        "family": FAMILY,
        "production_index": int(row["index"]),
        "registered_parameter_name": PARAMETER_NAME,
        "registered_parameter": float(row["parameter"]),
        "first_batch": bool(row["first_batch"]),
        "batch_status": batch_status,
        "container_height_m": HEIGHT_M,
        "observer_version": OBSERVER_VERSION,
        "qualification_receipt_sha256": qualification_receipt_sha256,
        "production_design_sha256": production_design_sha256,
    }


def prepare_production_batch(
    *,
    production_design: Mapping[str, Any],
    template_config: Mapping[str, Any],
    qualification: Mapping[str, Any],
    batch_status: str,
    lab_root: Path,
    output_root: Path,
    qualification_receipt_sha256: str,
    template_prepared_sha256: str,
    manifest_path: Path,
    runtime_root: Path,
    archive_root: Path,
    audits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare one admitted batch and write only under a fresh proposal root.

    This is the future execution hand-off used after the evaluator turns
    ``T1_numerical`` true.  Calling it with the current receipt fails before
    importing GenCase or writing any production case.
    """
    validate_production_design(production_design)
    supplied_binding = qualification.get("binding")
    if not isinstance(supplied_binding, Mapping) or supplied_binding.get("schema") != QUALIFICATION_BINDING_SCHEMA:
        raise ConnectorError("qualification binding is missing; call the root tick first")
    tick = tick_qualification(
        manifest_path=manifest_path,
        runtime_root=runtime_root,
        archive_root=archive_root,
    )
    fresh_summary = tick["summary"]
    fresh_qualification = {
        **fresh_summary,
        "manifest_sha256": tick["binding"]["manifest_sha256"],
        "binding": tick["binding"],
    }
    if canonical_digest(supplied_binding) != canonical_digest(tick["binding"]):
        raise ConnectorError("qualification binding is stale or was not produced by the root tick")
    decision = batch_decision(production_design, fresh_qualification, audits)
    if decision.get("status") != batch_status or batch_status not in {"first_8", "remaining_24"}:
        raise ConnectorError(
            f"production batch is not admitted: requested={batch_status!r}, decision={decision.get('status')!r}"
        )
    output_root = Path(output_root).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ConnectorError(f"production batch output is not fresh: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    # Delayed import keeps the blocked receipt path CPU/read-only and avoids a
    # GenCase dependency until root explicitly requests preparation.
    from scripts import core_cfd

    rows_by_id = {row["case_id"]: row for row in production_design["cases"]}
    design_hash = canonical_digest(production_design)
    prepared_rows: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for case_id in decision["ready"]:
        row = rows_by_id[case_id]
        target = output_root / f"case-{int(row['index']):02d}"
        config = derive_production_config(
            template_config,
            row,
            qualification_receipt_sha256=qualification_receipt_sha256,
            template_prepared_sha256=template_prepared_sha256,
        )
        prepared = core_cfd.prepare(config, Path(lab_root).resolve(), target)
        prepared_path = target / "prepared.json"
        if prepared.get("preflight_pass") is not True:
            raise ConnectorError(f"production CPU preflight failed: {prepared_path}")
        prepared_rows.append(
            {
                "index": row["index"],
                "case_id": row["case_id"],
                "prepared": str(prepared_path.resolve()),
                "prepared_sha256": digest(prepared_path),
            }
        )
        jobs.append(
            production_job_spec(
                prepared_path,
                row,
                lab_root=Path(lab_root),
                batch_status=batch_status,
                qualification_receipt_sha256=qualification_receipt_sha256,
                production_design_sha256=design_hash,
            )
        )
    manifest = {
        "schema": "core.f4.tallwall120.production_batch.v1",
        "created_at": stamp(),
        "scope_id": SCOPE_ID,
        "revision_id": QUALIFICATION_REVISION_ID,
        "connector_revision_id": CONNECTOR_REVISION_ID,
        "batch_status": batch_status,
        "registered_denominator": PRODUCTION_CASE_COUNT,
        "qualification_receipt_sha256": qualification_receipt_sha256,
        "production_design_sha256": design_hash,
        "template_prepared_sha256": template_prepared_sha256,
        "prepared": prepared_rows,
        "jobs": jobs,
        "gpu_launched": False,
        "ledger_written": False,
        "dispatch_owner": "root/core_runtime",
    }
    write_json(output_root / "manifest.json", manifest)
    for job in jobs:
        write_json(output_root / f"{job['job_id']}.json", job)
    return manifest


def verify_bound_audits(
    production_design: Mapping[str, Any], audits: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Verify per-case production audit receipts and their product hashes.

    A plain ``hard_integrity_pass`` boolean is not an audit receipt.  Each
    supplied case must carry hash bindings for the product result, audit,
    observations, trajectory, and native/archive execution receipt.  The
    product audit and result are checked directly, while the temporal and
    particle-axis flags are derived from the trajectory metadata and compared
    with the wrapper.  This prevents a caller from opening the 8 -> 24 gate
    with an unbound JSON assertion.
    """
    cases = {row["case_id"] for row in production_design["cases"]}
    normalized: dict[str, dict[str, Any]] = {}
    for case_id, receipt in dict(audits).items():
        if case_id not in cases or not isinstance(receipt, Mapping):
            raise ConnectorError(f"production audit is outside the fixed 32-case denominator: {case_id}")
        if receipt.get("schema") != "core.case_audit.v1" or receipt.get("case_id") != case_id:
            raise ConnectorError(f"production audit identity/schema mismatch: {case_id}")
        audit_ref = receipt.get("audit_artifact") or receipt.get("audit")
        result_ref = receipt.get("result_artifact") or receipt.get("result")
        observations_ref = receipt.get("observations_artifact") or receipt.get("observations")
        trajectory_ref = receipt.get("trajectory_artifact") or receipt.get("trajectory")
        execution_ref = (
            receipt.get("execution_receipt")
            or receipt.get("archive_receipt")
            or receipt.get("native_execution_receipt")
        )
        refs = {
            "product/result.json": result_ref,
            "product/audit.json": audit_ref,
            "product/observations.json": observations_ref,
            "product/trajectory.h5": trajectory_ref,
        }
        if any(not isinstance(ref, Mapping) for ref in refs.values()):
            raise ConnectorError(f"production case {case_id} has incomplete product bindings")
        for name, ref in refs.items():
            _verify_product_ref(ref, f"production case {case_id} {name}")
        execution, execution_path = _load_bound_json(
            execution_ref, f"production case {case_id} execution receipt"
        )
        # Ada workers publish core.execution_receipt.v1 while the cross-host
        # archive collector publishes core.verified_archive.v1.  Both are
        # accepted only after the same succeeded/output-index hash checks.
        _verify_native_payload(
            execution,
            refs,
            f"production case {case_id} execution receipt",
        )

        product_result, result_path = _load_bound_json(
            result_ref, f"production case {case_id} result"
        )
        product_audit, audit_path = _load_bound_json(
            audit_ref, f"production case {case_id} audit"
        )
        observations, observations_path = _load_bound_json(
            observations_ref, f"production case {case_id} observations"
        )
        if product_result.get("case_id") != case_id or product_audit.get("case_id") != case_id:
            raise ConnectorError(f"production case {case_id} product identity mismatch")
        if any(
            product_result.get(field) is not True
            for field in ("hard_integrity_pass", "source_mass_gate_pass", "event_window_complete")
        ):
            raise ConnectorError(f"production case {case_id} result gate failed")
        if any(
            product_audit.get(field) is not True
            for field in ("hard_integrity_pass", "source_mass_gate_pass", "event_window_complete")
        ):
            raise ConnectorError(f"production case {case_id} audit gate failed")
        conversion = product_result.get("conversion")
        if not isinstance(conversion, Mapping):
            raise ConnectorError(f"production case {case_id} result lacks trajectory conversion binding")
        if conversion.get("sha256") != trajectory_ref.get("sha256"):
            raise ConnectorError(f"production case {case_id} result/trajectory hash mismatch")
        if Path(str(conversion.get("hdf5", ""))).name != Path(trajectory_ref["path"]).name:
            raise ConnectorError(f"production case {case_id} result/trajectory filename mismatch")
        structural = product_audit.get("structural")
        if not isinstance(structural, Mapping):
            raise ConnectorError(f"production case {case_id} audit lacks structural scan")
        if Path(str(structural.get("path", ""))).name != Path(trajectory_ref["path"]).name:
            raise ConnectorError(f"production case {case_id} audit/trajectory filename mismatch")
        if not isinstance(observations.get("time_s"), list) or len(observations["time_s"]) < 2:
            raise ConnectorError(f"production case {case_id} observations lack a full time axis")

        datasets = structural.get("datasets")
        if not isinstance(datasets, Mapping):
            raise ConnectorError(f"production case {case_id} structural datasets are missing")
        structural_attrs = structural.get("attrs", {})
        if not isinstance(structural_attrs, Mapping):
            structural_attrs = {}
        required_datasets = {"particle_id", "position", "velocity", "mass", "time", "valid"}
        if not required_datasets.issubset(datasets):
            raise ConnectorError(f"production case {case_id} particle-axis datasets are incomplete")
        frame_count = structural.get("frame_count")
        particle_count = structural.get("particle_count")
        shapes_ok = (
            isinstance(frame_count, int)
            and frame_count >= 2
            and isinstance(particle_count, int)
            and particle_count > 0
            and datasets.get("time") == [frame_count]
            and datasets.get("particle_id") == [particle_count]
            and datasets.get("valid") == [frame_count, particle_count]
        )
        temporal_scan = bool(
            structural.get("full_scan") is True
            and structural.get("finite_active", {}).get("position") is True
            and structural.get("finite_active", {}).get("velocity") is True
            and structural.get("finite_active", {}).get("mass") is True
            and product_audit.get("requested_horizon_reached") is True
            and shapes_ok
        )
        particle_axis = bool(
            temporal_scan
            and structural_attrs.get("identity_key") == "particle_id"
            and structural.get("initial_valid_count") == particle_count
            and structural.get("identities_ever_valid") == particle_count
            and structural.get("death_count") == 0
            and structural.get("birth_count") == 0
        )
        if not temporal_scan or not particle_axis:
            raise ConnectorError(
                f"production case {case_id} product is not a complete temporal/particle-axis scan"
            )
        if receipt.get("full_temporal_scan") is not temporal_scan:
            raise ConnectorError(f"production case {case_id} temporal scan flag is unbound")
        if receipt.get("full_particle_axis") is not particle_axis:
            raise ConnectorError(f"production case {case_id} particle-axis flag is unbound")
        for field in ("hard_integrity_pass", "source_mass_gate_pass", "event_window_complete"):
            if receipt.get(field) is not True:
                raise ConnectorError(f"production case {case_id} wrapper {field} is unbound")
        normalized[case_id] = {
            **dict(receipt),
            "hard_integrity_pass": True,
            "source_mass_gate_pass": True,
            "event_window_complete": True,
            "artifacts": {
                "result": dict(result_ref),
                "audit": dict(audit_ref),
                "observations": dict(observations_ref),
                "trajectory": dict(trajectory_ref),
                "execution_receipt": dict(execution_ref),
            },
            "derived_checks": {
                "full_temporal_scan": temporal_scan,
                "full_particle_axis": particle_axis,
                "result_path": str(result_path),
                "audit_path": str(audit_path),
                "observations_path": str(observations_path),
                "execution_receipt_path": str(execution_path),
            },
        }
    return normalized


def batch_decision(
    production_design: Mapping[str, Any],
    qualification: Mapping[str, Any],
    audits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the fail-closed 8 -> 24 decision without writing state."""
    qualification_schema = qualification.get("schema")
    if type(qualification_schema) is not str or qualification_schema != QUALIFICATION_SCHEMA:
        validate_production_design(production_design)
        return {
            "status": "scope_review_required",
            "ready": [],
            "failed": ["qualification:schema_mismatch"],
            "missing": [row["case_id"] for row in production_design["cases"]],
            "registered_denominator": PRODUCTION_CASE_COUNT,
        }
    validate_production_design(production_design)
    audits = {} if audits is None else dict(audits)
    binding = qualification.get("binding")
    binding_valid = (
        isinstance(binding, Mapping)
        and binding.get("schema") == QUALIFICATION_BINDING_SCHEMA
        and binding.get("verified") is True
        and binding.get("artifact_bindings_verified") is True
        and binding.get("manifest_sha256") == qualification.get("manifest_sha256")
        and binding.get("matrix_complete") == qualification.get("matrix_complete")
        and binding.get("T1_numerical") == qualification.get("T1_numerical")
    )
    if not binding_valid:
        return {
            "status": "scope_review_required",
            "ready": [],
            "failed": ["qualification:unbound_or_unverified_tick"],
            "missing": [row["case_id"] for row in production_design["cases"]],
            "registered_denominator": PRODUCTION_CASE_COUNT,
        }
    if not qualification.get("matrix_complete"):
        return {
            "status": "awaiting_qualification",
            "ready": [],
            "failed": ["qualification:matrix_incomplete"],
            "missing": [row["case_id"] for row in production_design["cases"]],
            "registered_denominator": PRODUCTION_CASE_COUNT,
        }
    if not qualification.get("T1_numerical"):
        return {
            "status": "scope_review_required",
            "ready": [],
            "failed": ["qualification:T1_numerical"],
            "missing": [row["case_id"] for row in production_design["cases"]],
            "registered_denominator": PRODUCTION_CASE_COUNT,
        }
    if audits:
        audits = verify_bound_audits(production_design, audits)
    decision = next_batch(dict(production_design), dict(qualification), audits)
    decision.setdefault("registered_denominator", PRODUCTION_CASE_COUNT)
    return decision


def _resource_summary(resource: Mapping[str, Any]) -> dict[str, Any]:
    if resource.get("schema") != "core.milestone_resource_estimate.v1":
        raise ConnectorError("resource evidence schema mismatch")
    for key in ("new_attempts", "conservative_new_attempt_disk_bytes", "available_remote_GB_at_review"):
        if not isinstance(resource.get(key), (int, float)) or float(resource[key]) <= 0:
            raise ConnectorError(f"resource evidence field is invalid: {key}")
    per_attempt = float(resource["conservative_new_attempt_disk_bytes"]) / float(resource["new_attempts"])
    available_bytes = float(resource["available_remote_GB_at_review"]) * 1_000_000_000
    return {
        "basis_job": resource.get("basis_job"),
        "measured_peak_gpu_mib": resource.get("measured_peak_gpu_mib"),
        "measured_wall_seconds": resource.get("measured_wall_seconds"),
        "measured_cpu_seconds": resource.get("measured_cpu_seconds"),
        "conservative_attempt_disk_bytes": resource["conservative_new_attempt_disk_bytes"],
        "conservative_per_attempt_disk_bytes": per_attempt,
        "available_remote_GB_at_review": resource["available_remote_GB_at_review"],
        "staged_first_8_disk_bytes": per_attempt * 8,
        "staged_remaining_24_disk_bytes": per_attempt * 24,
        "first_8_fits_available_disk": per_attempt * 8 <= available_bytes,
        "all_32_fit_without_archival": per_attempt * 32 <= available_bytes,
        "production_resource_contract": {
            "cpu_cores": 2,
            "ram_mib": 24576,
            "gpu_peak_mib": 6144,
            "io_weight": 2,
            "timeout_seconds": 14400,
            "basis": "qualified cell04 dp=.0075 job resources; root may reschedule after receipt",
        },
    }


def negative_contract_checks(
    manifest: Mapping[str, Any],
    design: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    template_config: Mapping[str, Any],
    production_design: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Exercise the four required fail-closed admission mutations in memory."""
    results: list[dict[str, Any]] = []

    partial_qualification = {
        "schema": QUALIFICATION_SCHEMA,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "matrix_complete": False,
        "T1_numerical": True,
        "manifest_sha256": "synthetic",
        "binding": {
            "schema": QUALIFICATION_BINDING_SCHEMA,
            "verified": True,
            "artifact_bindings_verified": True,
            "manifest_sha256": "synthetic",
            "matrix_complete": False,
            "T1_numerical": True,
        },
    }
    partial_decision = batch_decision(production_design, partial_qualification)
    results.append(
        {
            "name": "partial_matrix",
            "rejected": partial_decision["status"] == "awaiting_qualification" and not partial_decision["ready"],
            "observed": partial_decision["status"],
            "reason": "matrix_incomplete blocks first_8",
        }
    )

    old_manifest = deepcopy(dict(manifest))
    old_manifest["scope_id"] = "F4_drop_resting_pool_x_v2"
    try:
        validate_manifest(old_manifest, design)
    except ConnectorError as exc:
        results.append({"name": "old_scope_receipt", "rejected": True, "reason": str(exc)})
    else:
        results.append({"name": "old_scope_receipt", "rejected": False, "reason": "mutation accepted"})

    short_template = deepcopy(dict(template_config))
    short_template["container_height_m"] = 0.6
    short_template.setdefault("wall_bounds", {})["zmax"] = 0.6
    try:
        validate_template_config(short_template)
    except ConnectorError as exc:
        results.append({"name": "changed_wall_height", "rejected": True, "reason": str(exc)})
    else:
        results.append({"name": "changed_wall_height", "rejected": False, "reason": "mutation accepted"})

    old_observer = deepcopy(dict(template_config))
    old_observer["observation_version"] = "legacy_060m_wall_observer_v1"
    try:
        validate_template_config(old_observer)
    except ConnectorError as exc:
        results.append({"name": "changed_observer", "rejected": True, "reason": str(exc)})
    else:
        results.append({"name": "changed_observer", "rejected": False, "reason": "mutation accepted"})

    # The production registration is a fixed 32-row denominator.  These
    # mutations exercise the admission path itself, rather than relying on a
    # caller to use the object returned by build_production_design().
    for name, mutate in (
        ("production_parameter", lambda row: row.__setitem__("parameter", float(row["parameter"]) + 0.001)),
        ("production_index", lambda row: row.__setitem__("index", 32)),
        ("production_split", lambda row: row.__setitem__("split", "tampered_split")),
        ("production_case_identity", lambda row: row.__setitem__("case_id", "tampered_case")),
        ("production_lineage", lambda row: row.__setitem__("qualification_inheritance", True)),
    ):
        mutated = deepcopy(dict(production_design))
        mutate(mutated["cases"][0])
        try:
            validate_production_design(mutated)
        except ConnectorError as exc:
            results.append({"name": name, "rejected": True, "reason": str(exc)})
        else:
            results.append({"name": name, "rejected": False, "reason": "mutation accepted"})
    return results


def build_proposal(
    *,
    manifest_path: Path,
    evaluation_path: Path,
    integration_review_path: Path,
    design_path: Path,
    reuse_path: Path,
    resource_path: Path,
    template_path: Path,
    runtime_root: Path,
    archive_root: Path,
) -> dict[str, Any]:
    """Build a reviewable proposal from explicit, hash-checked evidence."""
    manifest_path = Path(manifest_path).resolve()
    evaluation_path = Path(evaluation_path).resolve()
    integration_review_path = Path(integration_review_path).resolve()
    design_path = Path(design_path).resolve()
    reuse_path = Path(reuse_path).resolve()
    resource_path = Path(resource_path).resolve()
    template_path = Path(template_path).resolve()
    runtime_root = Path(runtime_root).resolve()
    archive_root = Path(archive_root).resolve()

    manifest = load_json(manifest_path)
    design = load_json(design_path)
    evaluation = load_json(evaluation_path)
    integration_review = load_json(integration_review_path)
    reuse = load_json(reuse_path)
    resource = load_json(resource_path)
    template = load_json(template_path)
    template_config = template.get("config", template)

    summary = validate_design(design)
    validate_manifest(manifest, design)
    tick = tick_qualification(
        manifest_path=manifest_path,
        runtime_root=runtime_root,
        archive_root=archive_root,
    )
    evaluation_summary = validate_evaluation(
        evaluation,
        manifest_path,
        recomputed_result=tick["result"],
    )
    evaluation_summary["binding"] = tick["binding"]
    template_summary = validate_template_config(template_config)
    resource_summary = _resource_summary(resource)

    # The evaluator manifest explicitly binds the v2 equivalence record and
    # resource plan.  Resolve those two bindings against the current checkout
    # and fail if a later metadata rewrite silently changed them.
    manifest_resource = manifest["resource_reference"]
    resource_ref = verify_ref(resource_path, manifest_resource["sha256"], "resource plan")
    manifest_eq = manifest["cell12_reuse"]["evidence_bindings"]["cell12_equivalence_v2"]
    reuse_ref = verify_ref(reuse_path, manifest_eq["sha256"], "cell12 v2 equivalence")
    if reuse.get("schema") != "core.f4.tallwall120.canary_cell12_equivalence.v2":
        raise ConnectorError("cell12 reuse evidence schema mismatch")
    if reuse.get("scope_id") != SCOPE_ID or reuse.get("revision_id") != QUALIFICATION_REVISION_ID:
        raise ConnectorError("cell12 reuse evidence scope mismatch")
    if reuse.get("solver_launched") is not False or reuse.get("matrix_cell_new_bi4_executed") is not False:
        raise ConnectorError("cell12 reuse evidence claims an unapproved solver execution")

    design_ref = verify_ref(
        design_path,
        manifest["source_bindings"]["design"]["sha256"],
        "qualification design",
    )
    template_row = manifest["cells"][TEMPLATE_INDEX]
    template_ref = verify_ref(template_path, template_row["prepared_sha256"], "tall-wall template")
    evaluation_ref = path_ref(evaluation_path, "qualification evaluation")
    review_ref = path_ref(integration_review_path, "root integration review")
    if integration_review.get("schema") != "core.root_qualification_integration.v1":
        raise ConnectorError("root integration review schema mismatch")
    if integration_review.get("evaluation_sha256") != evaluation_ref["sha256"]:
        raise ConnectorError("root integration review is not bound to evaluator receipt")
    if integration_review.get("static_contract_pass") is not True:
        raise ConnectorError("root integration review static contract is not passing")

    production = build_production_design(design)
    # Derive all configs in memory to exercise the 1.2 m wall contract.  No
    # generated input, job, or runtime output is written by this operation.
    previews = [
        derive_production_config(
            template_config,
            row,
            qualification_receipt_sha256=evaluation_ref["sha256"],
            template_prepared_sha256=template_ref["sha256"],
        )
        for row in production["cases"]
    ]

    qualification = {
        **evaluation_summary,
        "_receipt_sha256": evaluation_ref["sha256"],
        "design_sha256": design_ref["sha256"],
        "manifest_sha256": tick["binding"]["manifest_sha256"],
        "_matrix_sha256": manifest["source_bindings"]["prepared_matrix"]["sha256"],
    }
    decision = batch_decision(production, qualification)
    negative_checks = negative_contract_checks(
        manifest, design, evaluation, template_config, production
    )
    if decision["status"] == "awaiting_qualification":
        status = "awaiting_qualification"
    elif decision["status"] == "scope_review_required":
        status = "scope_review_required"
    else:
        status = "production_batch_ready_for_root_review"

    return {
        "schema": SCHEMA,
        "created_at": stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "qualification_revision_id": QUALIFICATION_REVISION_ID,
        "connector_revision_id": CONNECTOR_REVISION_ID,
        "recipe_id": RECIPE_ID,
        "recipe": RECIPE,
        "status": status,
        "qualification_admission": {
            "static_contract_pass": evaluation_summary["static_contract_pass"],
            "matrix_complete": evaluation_summary["matrix_complete"],
            "T1_numerical": evaluation_summary["T1_numerical"],
            "qualification_claim": evaluation.get("qualification_claim"),
            "promotion_status": evaluation_summary["promotion_status"],
            "reevaluation_match": evaluation_summary["reevaluation_match"],
            "artifact_bindings_verified": evaluation_summary["artifact_bindings_verified"],
            "missing_cell_count": len(evaluation_summary["missing"]),
            "failure_cell_count": len(evaluation_summary["failures"]),
            "claim_limit": "current receipt is not range-qualified; no 8 or 32 production case is ready",
        },
        "evidence": {
            "integration_gap": path_ref(
                SOURCE_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-production-integration-gap-root-v1.json",
                "production integration gap",
            ),
            "integration_review": review_ref,
            "qualification_manifest": path_ref(manifest_path, "v2 evaluator manifest"),
            "qualification_evaluation": evaluation_ref,
            "qualification_tick": {
                "schema": QUALIFICATION_BINDING_SCHEMA,
                "manifest_path": tick["binding"]["manifest_path"],
                "manifest_sha256": tick["binding"]["manifest_sha256"],
                "runtime_root": tick["binding"]["runtime_root"],
                "archive_root": tick["binding"]["archive_root"],
                "reevaluation_sha256": tick["binding"]["reevaluation_sha256"],
                "matrix_complete": tick["binding"]["matrix_complete"],
                "T1_numerical": tick["binding"]["T1_numerical"],
                "cell_indices": tick["binding"]["cell_indices"],
                "missing": tick["binding"]["missing"],
                "failures": tick["binding"]["failures"],
                "checks": tick["binding"]["checks"],
            },
            "qualification_design": design_ref,
            "cell12_equivalence_v2": reuse_ref,
            "resource_plan": resource_ref,
            "tallwall_template": template_ref,
            "evaluator_code": dict(manifest["source_bindings"]["evaluator_code"]),
        },
        "cell12_reuse_contract": {
            "matrix_denominator_includes_reused_cell": True,
            "new_candidate_bi4_executed": False,
            "solver_rerun": False,
            "range_qualification_inherited": False,
            "equivalence_sha256": reuse_ref["sha256"],
        },
        "production_contract": {
            "parameter_name": PARAMETER_NAME,
            "parameter_range": list(PARAMETER_RANGE),
            "qualification_points": production["qualification_parameters"],
            "case_count": PRODUCTION_CASE_COUNT,
            "first_batch_indices": list(FIRST_EIGHT),
            "first_batch_size": 8,
            "remaining_batch_size": 24,
            "batch_order": ["first_8", "remaining_24"],
            "geometry": {
                "container_height_m": HEIGHT_M,
                "wall_bounds_zmax_m": HEIGHT_M,
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "pool": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18]},
            },
            "observer_version": OBSERVER_VERSION,
            "window_s": EXECUTION_WINDOW_S,
            "maximum_extension_s": MAXIMUM_EXTENSION_S,
            "qualification_inheritance": False,
        },
        "production_design": production,
        "template_derivation": {
            "template_index": TEMPLATE_INDEX,
            "template_case_id": template_config.get("case_id"),
            "template_prepared_sha256": template_ref["sha256"],
            "all_32_configs_derived_in_memory": True,
            "derived_container_heights_m": sorted({cfg["container_height_m"] for cfg in previews}),
            "derived_observer_versions": sorted({cfg["observation_version"] for cfg in previews}),
            "prepared_inputs_written": False,
            "solver_launched": False,
        },
        "batches": {
            "decision": decision,
            "first_8_case_ids": [production["cases"][i]["case_id"] for i in FIRST_EIGHT],
            "remaining_24_case_ids": [
                row["case_id"] for i, row in enumerate(production["cases"]) if i not in FIRST_EIGHT
            ],
            "job_specs": [],
            "dispatch_owner": "root/core_runtime",
        },
        "resources": {
            "evidence": resource_summary,
            "resource_plan_sha256": resource_ref["sha256"],
            "staging_policy": "stage first_8, archive/monitor, then remaining_24; do not assume all 32 fit concurrently",
        },
        "negative_tests_required": [
            "partial matrix or T1=false blocks production",
            "old F4 scope receipt is rejected by identity",
            "template wall height != 1.2 m is rejected",
            "template/evaluator observer revision != fixed_015m_vertical_reference060_v2 is rejected",
        ],
        "negative_tests": negative_checks,
        "execution": {
            "gpu_launched": False,
            "job_specs_submitted": False,
            "ledger_written": False,
            "central_registry_written": False,
            "production_prepared_assets_written": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tick", action="store_true", help="run one read-only root qualification tick")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--integration-review", type=Path)
    parser.add_argument("--design", type=Path)
    parser.add_argument("--reuse", type=Path)
    parser.add_argument("--resource", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.tick:
        required = {
            "manifest": args.manifest,
            "runtime-root": args.runtime_root,
            "archive-root": args.archive_root,
            "output": args.output,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            parser.error("--tick requires " + ", ".join("--" + name for name in missing))
        tick = tick_qualification(
            manifest_path=args.manifest,
            runtime_root=args.runtime_root,
            archive_root=args.archive_root,
        )
        write_json(
            args.output,
            {
                "schema": QUALIFICATION_BINDING_SCHEMA,
                "binding": tick["binding"],
                "result": tick["result"],
            },
        )
        print(json.dumps({key: tick["binding"][key] for key in ("matrix_complete", "T1_numerical", "missing", "failures")}, indent=2))
        return 0
    required = {
        "manifest": args.manifest,
        "evaluation": args.evaluation,
        "integration-review": args.integration_review,
        "design": args.design,
        "reuse": args.reuse,
        "resource": args.resource,
        "template": args.template,
        "runtime-root": args.runtime_root,
        "archive-root": args.archive_root,
        "output": args.output,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error("proposal mode requires " + ", ".join("--" + name for name in missing))
    result = build_proposal(
        manifest_path=args.manifest,
        evaluation_path=args.evaluation,
        integration_review_path=args.integration_review,
        design_path=args.design,
        reuse_path=args.reuse,
        resource_path=args.resource,
        template_path=args.template,
        runtime_root=args.runtime_root,
        archive_root=args.archive_root,
    )
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "qualification_matrix_complete": result["qualification_admission"]["matrix_complete"],
                "T1_numerical": result["qualification_admission"]["T1_numerical"],
                "case_count": result["production_contract"]["case_count"],
                "gpu_launched": result["execution"]["gpu_launched"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
