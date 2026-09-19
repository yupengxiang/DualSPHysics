#!/usr/bin/env python3
"""Read-only, artifact-driven entry point for the L2-R F3 extension.

The historical F3 starter is a narrow registered numerical reference.  It is
not silently promoted to the F3R off-axis/multi-axis scope.  This module
audits that distinction and accepts an optional candidate evidence bundle for
the next controlled study.  It never launches GenCase, DualSPHysics,
conversion, or a training job, and it never emits a qualification receipt.

The command is intentionally useful before a GPU dispatch::

    .venv/bin/python scripts/l2_f3r_research.py preflight

The optional ``--candidate`` bundle is a future, source-hash-bound F3R
evidence package.  Its schema is documented by ``candidate_contract()`` and
is validated fail-closed rather than inferred from file names.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
LAB = REPO / "lagrangian-fluid-lab"
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"

DEFAULT_CANONICAL = CAMPAIGN / "evidence" / "f3-canonical-manifest.json"
DEFAULT_GATE = LAB / "campaigns" / "l1-resume" / "continuation" / "F3-075-REF0081818-GATE.json"
DEFAULT_C2_REPORT = CAMPAIGN / "reports" / "c2-f3-canary.json"

SCHEMA = "l2r.f3r.research_entry.v1"
CANDIDATE_SCHEMA = "l2r.f3r.candidate.v1"
FAMILY = "F3"
MIN_BACKGROUND_COUNT = 2
REQUIRED_RESOLUTIONS_M = (0.00818181818181818, 0.0075, 0.006)
REQUIRED_REFERENCE_CASE_COUNT = 32
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# These fields are deliberately explicit.  ``visco1`` and other labels are
# not physics semantics and therefore cannot substitute for the recipe card.
REQUIRED_RECIPE_FIELDS = (
    "recipe_id",
    "production_resolution_m",
    "reference_resolutions_m",
    "solver_mode",
    "boundary",
    "slip_mode",
    "no_penetration",
    "visco",
    "visco_bound_factor",
    "shifting",
    "native_velocity_displacement_correction",
    "posthoc_particle_projection",
    "time_window_s",
    "output_interval_s",
    "control_domain",
    "coordinate_frame",
    "trajectory_semantics",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def file_ref(path: Path) -> dict[str, Any]:
    path = path.resolve()
    result: dict[str, Any] = {
        "path": repo_relative(path),
        "absolute_path": str(path),
        "exists": path.is_file(),
    }
    if path.is_file():
        result["bytes"] = path.stat().st_size
        result["sha256"] = sha256_file(path)
    else:
        result["bytes"] = None
        result["sha256"] = None
    return result


def candidate_contract() -> dict[str, Any]:
    """Return the machine-readable contract for an optional F3R bundle."""

    return {
        "schema": CANDIDATE_SCHEMA,
        "recipe": {
            "recipe_card": "all fields in REQUIRED_RECIPE_FIELDS",
            "hard_audit_passed": True,
            "source_hashes": "one or more 64-hex source hashes",
        },
        "cases": {
            "required_fields": [
                "case_id", "background_id", "resolution_m", "geometry_id",
                "control_id", "hard_audit_passed", "source_hashes",
            ],
            "required_matrix": "at least two backgrounds, each at all three declared reference resolutions",
            "duplicate_policy": "duplicate case_id or duplicate (background_id, resolution_m) is rejected",
        },
        "control_geometry": {
            "required_fields": [
                "new_geometry", "topology_evidence", "new_control",
                "control_semantics_evidence", "hard_audit_passed", "source_hashes",
            ],
            "topology_policy": "preserve connected passage/opening semantics; an AABB proxy is insufficient",
        },
        "receipt_policy": "this entry only audits evidence; receipt_emitted is always false",
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _valid_hashes(values: Any) -> bool:
    return (
        isinstance(values, list)
        and bool(values)
        and all(isinstance(value, str) and HASH_RE.fullmatch(value) for value in values)
    )


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _resolution_key(value: Any) -> float | None:
    if not _finite_number(value) or float(value) <= 0:
        return None
    return round(float(value), 12)


def _required_resolution_keys(values: Iterable[Any] = REQUIRED_RESOLUTIONS_M) -> list[float]:
    keys = [_resolution_key(value) for value in values]
    return [value for value in keys if value is not None]


def _recipe_card_errors(card: Any) -> list[str]:
    if not isinstance(card, dict):
        return ["recipe_card_missing_or_not_object"]
    errors = [f"recipe_card_missing:{field}" for field in REQUIRED_RECIPE_FIELDS if field not in card]
    if "recipe_id" in card and (not isinstance(card["recipe_id"], str) or not card["recipe_id"]):
        errors.append("recipe_card_recipe_id_invalid")
    if "production_resolution_m" in card and _resolution_key(card["production_resolution_m"]) is None:
        errors.append("recipe_card_production_resolution_invalid")
    if "reference_resolutions_m" in card:
        refs = card["reference_resolutions_m"]
        if not isinstance(refs, list) or not refs or any(_resolution_key(value) is None for value in refs):
            errors.append("recipe_card_reference_resolutions_invalid")
    for field in ("time_window_s", "control_domain"):
        if field in card:
            value = card[field]
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(not _finite_number(item) for item in value)
                or float(value[0]) >= float(value[1])
            ):
                errors.append(f"recipe_card_{field}_invalid")
    if "output_interval_s" in card and (
        _resolution_key(card["output_interval_s"]) is None
    ):
        errors.append("recipe_card_output_interval_invalid")
    return errors


def _source_record_errors(source_records: Any) -> list[str]:
    if not isinstance(source_records, dict) or not source_records:
        return ["source_records_missing_or_empty"]
    errors: list[str] = []
    for name, record in source_records.items():
        if not isinstance(record, dict):
            errors.append(f"source_record_not_object:{name}")
            continue
        if not record.get("path"):
            errors.append(f"source_record_path_missing:{name}")
        if not isinstance(record.get("sha256"), str) or not HASH_RE.fullmatch(record["sha256"]):
            errors.append(f"source_record_hash_invalid:{name}")
    return errors


def _case_passed(case: dict[str, Any], *, legacy: bool = False) -> bool:
    if legacy:
        axes = case.get("qualification_axes", {})
        return bool(axes.get("structural") and axes.get("T1_registered_numerical"))
    return case.get("hard_audit_passed") is True


def assess_reference_recipe(canonical: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Audit the already registered F3 recipe without widening its scope."""

    errors: list[str] = []
    recipe = canonical.get("recipe")
    errors.extend(_recipe_card_errors(recipe))
    errors.extend(_source_record_errors(canonical.get("source_records")))
    if canonical.get("schema") != "l2.f3.canonical_manifest.v1":
        errors.append("canonical_manifest_schema_mismatch")
    if canonical.get("status") != "registered_T1_preserved; independent_A0_audit_recorded":
        errors.append("canonical_manifest_status_not_registered_reference")
    if gate.get("schema") != "f3.revision075.ref0081818.gate.v1":
        errors.append("recipe_gate_schema_mismatch")
    if gate.get("status") != "passed":
        errors.append("recipe_gate_not_passed")
    if isinstance(recipe, dict) and isinstance(gate, dict):
        if gate.get("recipe_id") != recipe.get("recipe_id"):
            errors.append("recipe_id_mismatch_between_manifest_and_gate")
        if _resolution_key(gate.get("production_resolution_m")) != _resolution_key(recipe.get("production_resolution_m")):
            errors.append("production_resolution_mismatch_between_manifest_and_gate")
        gate_refs = _required_resolution_keys(gate.get("reference_resolutions_m", []))
        card_refs = _required_resolution_keys(recipe.get("reference_resolutions_m", []))
        if gate_refs != card_refs:
            errors.append("reference_resolution_ladder_mismatch_between_manifest_and_gate")
    cases = canonical.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("canonical_cases_missing_or_empty")
        cases = []
    case_ids: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            errors.append("canonical_case_not_object")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append("canonical_case_id_missing")
        else:
            case_ids.append(case_id)
        if case.get("recipe_id") != (recipe or {}).get("recipe_id"):
            errors.append(f"canonical_case_recipe_mismatch:{case_id}")
        if not _case_passed(case, legacy=True):
            errors.append(f"canonical_case_not_structural_and_T1:{case_id}")
    if len(case_ids) != len(set(case_ids)):
        errors.append("canonical_case_ids_not_unique")
    if len(cases) != REQUIRED_REFERENCE_CASE_COUNT:
        errors.append(f"canonical_reference_case_count:{len(cases)};expected:{REQUIRED_REFERENCE_CASE_COUNT}")
    return {
        "status": "qualified_reference" if not errors else "bounded_rejection",
        "scope": "legacy_registered_numerical_F3_starter_only",
        "recipe_id": (recipe or {}).get("recipe_id") if isinstance(recipe, dict) else None,
        "case_count": len(cases),
        "required_case_count": REQUIRED_REFERENCE_CASE_COUNT,
        "reference_resolutions_m": (recipe or {}).get("reference_resolutions_m") if isinstance(recipe, dict) else [],
        "errors": _unique(errors),
        "claim": (
            "registered numerical reference; does not qualify the F3R geometry/control extension"
            if not errors else "historical F3 reference card failed its source contract"
        ),
    }


def _candidate_cases(candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("cases"), list):
        return []
    return [case for case in candidate["cases"] if isinstance(case, dict)]


def assess_candidate_recipe(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Check a future F3R recipe bundle; no result here creates a receipt."""

    errors: list[str] = []
    if candidate is None:
        return {
            "status": "bounded_rejection",
            "errors": ["no_f3r_candidate_bundle_supplied"],
            "recipe_id": None,
            "claim": "no new F3R recipe evidence was supplied",
        }
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        errors.append("candidate_schema_mismatch")
    recipe_section = candidate.get("recipe")
    if not isinstance(recipe_section, dict):
        errors.append("candidate_recipe_section_missing")
        recipe_section = {}
    card = recipe_section.get("recipe_card")
    errors.extend(_recipe_card_errors(card))
    if recipe_section.get("hard_audit_passed") is not True:
        errors.append("candidate_recipe_hard_audit_not_passed")
    if not _valid_hashes(recipe_section.get("source_hashes")):
        errors.append("candidate_recipe_source_hashes_invalid")
    recipe_id = card.get("recipe_id") if isinstance(card, dict) else None
    cases = _candidate_cases(candidate)
    if not cases:
        errors.append("candidate_cases_missing_or_empty")
    case_ids: list[str] = []
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append("candidate_case_id_missing")
        else:
            case_ids.append(case_id)
        if case.get("recipe_id", recipe_id) != recipe_id:
            errors.append(f"candidate_case_recipe_mismatch:{case_id}")
        for field in ("background_id", "geometry_id", "control_id"):
            if not isinstance(case.get(field), str) or not case[field]:
                errors.append(f"candidate_case_{field}_missing:{case_id}")
        if not _case_passed(case):
            errors.append(f"candidate_case_hard_audit_not_passed:{case_id}")
        if not _valid_hashes(case.get("source_hashes")):
            errors.append(f"candidate_case_source_hashes_invalid:{case_id}")
    if len(case_ids) != len(set(case_ids)):
        errors.append("candidate_case_ids_not_unique")
    return {
        "status": "qualified_recipe" if not errors else "bounded_rejection",
        "recipe_id": recipe_id,
        "case_count": len(cases),
        "errors": _unique(errors),
        "claim": (
            "candidate recipe evidence satisfies the local F3R recipe contract; receipt still withheld"
            if not errors else "candidate recipe evidence is incomplete or failed a hard contract"
        ),
    }


def _explicit_candidate_matrix(candidate: dict[str, Any] | None) -> bool:
    return candidate is not None and isinstance(candidate.get("cases"), list)


def assess_background_resolution_coverage(
    canonical: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check explicit two-background by three-resolution coverage.

    The legacy manifest has no per-case background or resolution fields.  Its
    production resolution is therefore reported as a fallback observation,
    while the declared ladder is retained separately.  This distinction is
    what prevents the old amplitude-only dataset from becoming a new matrix.
    """

    recipe = canonical.get("recipe") if isinstance(canonical.get("recipe"), dict) else {}
    if isinstance(candidate, dict):
        candidate_recipe = candidate.get("recipe", {}).get("recipe_card")
        if isinstance(candidate_recipe, dict):
            recipe = candidate_recipe
    declared = _required_resolution_keys(recipe.get("reference_resolutions_m", REQUIRED_RESOLUTIONS_M))
    if not declared:
        declared = _required_resolution_keys()
    cases = _candidate_cases(candidate)
    fallback_used = False
    source = "candidate_bundle"
    if not _explicit_candidate_matrix(candidate):
        source = "legacy_manifest_fallback"
        fallback_used = True
        production = _resolution_key(recipe.get("production_resolution_m"))
        cases = []
        for index, case in enumerate(canonical.get("cases", []) if isinstance(canonical.get("cases"), list) else []):
            if not isinstance(case, dict):
                continue
            cases.append({
                "case_id": case.get("case_id", f"legacy_case_{index}"),
                "background_id": case.get("background_id", "legacy_single_slot_unlabelled"),
                "resolution_m": case.get("resolution_m", production),
                "hard_audit_passed": _case_passed(case, legacy=True),
            })
    backgrounds: dict[str, set[float]] = {}
    invalid_cases: list[str] = []
    duplicate_cells: list[str] = []
    seen_cells: set[tuple[str, float]] = set()
    seen_ids: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id", "<missing>"))
        background_id = case.get("background_id")
        resolution = _resolution_key(case.get("resolution_m"))
        if not isinstance(background_id, str) or not background_id or resolution is None:
            invalid_cases.append(case_id)
            continue
        if case_id in seen_ids and not fallback_used:
            invalid_cases.append(f"duplicate_case_id:{case_id}")
        seen_ids.add(case_id)
        cell = (background_id, resolution)
        if cell in seen_cells and not fallback_used:
            duplicate_cells.append(f"{background_id}@{resolution:g}")
        seen_cells.add(cell)
        backgrounds.setdefault(background_id, set()).add(resolution)
    background_rows = []
    missing_cells: list[dict[str, Any]] = []
    for background_id in sorted(backgrounds):
        observed = sorted(backgrounds[background_id])
        missing = [value for value in declared if value not in observed]
        background_rows.append({
            "background_id": background_id,
            "observed_resolutions_m": observed,
            "missing_declared_resolutions_m": missing,
            "complete": not missing,
        })
        missing_cells.extend({"background_id": background_id, "resolution_m": value} for value in missing)
    required_cells = MIN_BACKGROUND_COUNT * len(declared)
    complete_background_count = sum(row["complete"] for row in background_rows)
    errors: list[str] = []
    if fallback_used:
        errors.append("legacy_manifest_has_no_explicit_background_resolution_matrix")
    if len(backgrounds) < MIN_BACKGROUND_COUNT:
        errors.append(f"background_count:{len(backgrounds)};minimum:{MIN_BACKGROUND_COUNT}")
    if complete_background_count < MIN_BACKGROUND_COUNT:
        errors.append(
            f"complete_background_count:{complete_background_count};minimum:{MIN_BACKGROUND_COUNT}"
        )
    if invalid_cases:
        errors.append("invalid_matrix_cases:" + ",".join(sorted(invalid_cases)))
    if duplicate_cells:
        errors.append("duplicate_background_resolution_cells:" + ",".join(sorted(duplicate_cells)))
    if not cases:
        errors.append("background_resolution_cases_missing")
    return {
        "status": "passed" if not errors else "bounded_rejection",
        "source": source,
        "required_background_count": MIN_BACKGROUND_COUNT,
        "required_resolutions_m": declared,
        "required_cell_count": required_cells,
        "observed_background_count": len(backgrounds),
        "complete_background_count": complete_background_count,
        "observed_cell_count": len(seen_cells),
        "backgrounds": background_rows,
        "missing_cells": missing_cells,
        "fallback_observation_used": fallback_used,
        "errors": _unique(errors),
        "claim": (
            "explicit two-background by three-resolution coverage is present"
            if not errors else "coverage is bounded to the observed cells; no missing cells are promoted"
        ),
    }


def _candidate_control_geometry(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    value = candidate.get("control_geometry")
    return value if isinstance(value, dict) else None


def assess_control_geometry_evidence(
    c2_report: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit explicit topology/control evidence, including the failed C2 canary."""

    supplied = _candidate_control_geometry(candidate)
    if supplied is not None:
        errors: list[str] = []
        checks = {
            "new_geometry": supplied.get("new_geometry") is True,
            "topology_evidence": supplied.get("topology_evidence") is True,
            "new_control": supplied.get("new_control") is True,
            "control_semantics_evidence": supplied.get("control_semantics_evidence") is True,
            "hard_audit_passed": supplied.get("hard_audit_passed") is True,
            "source_hashes": _valid_hashes(supplied.get("source_hashes")),
        }
        errors.extend(f"candidate_control_geometry_{name}_missing" for name, okay in checks.items() if not okay)
        return {
            "status": "passed" if not errors else "bounded_rejection",
            "source": "candidate_bundle",
            "checks": checks,
            "errors": _unique(errors),
            "claim": (
                "new geometry topology and control semantics are hard-audited"
                if not errors else "candidate control/geometry evidence is not sufficient for promotion"
            ),
        }

    design = c2_report.get("design", {}) if isinstance(c2_report, dict) else {}
    input_record = c2_report.get("input", {}) if isinstance(c2_report, dict) else {}
    audit = c2_report.get("audit", {}) if isinstance(c2_report, dict) else {}
    independent = audit.get("independent_audit", {}) if isinstance(audit, dict) else {}
    semantic = audit.get("semantic_audit", {}) if isinstance(audit, dict) else {}
    acceptance = c2_report.get("acceptance", {}) if isinstance(c2_report, dict) else {}
    topology_text = str(design.get("connected_passage_semantics", "")).strip().lower()
    errors: list[str] = []
    checks = {
        "new_geometry": bool(acceptance.get("offaxis_geometry_template_recorded")),
        "topology_evidence": bool(topology_text and "passage" in topology_text),
        "new_control": bool(input_record.get("recipe_id")) and "offaxis" in str(input_record.get("recipe_id", "")).lower(),
        "control_semantics_evidence": semantic.get("control_semantics_present") is True,
        "hard_audit_passed": bool(
            acceptance.get("hard_canary_pass")
            and audit.get("canary_hard_integrity_pass")
            and independent.get("structural_pass")
        ),
        "finite_state": all(value is True for value in (independent.get("finite") or {}).values())
        and bool(independent.get("finite")),
        "finite_wall": independent.get("wall_violation_count") == 0,
        "source_semantics": semantic.get("source_semantics_present") is True,
    }
    if not checks["new_geometry"]:
        errors.append("historical_c2_new_geometry_not_recorded")
    if not checks["topology_evidence"]:
        errors.append("historical_c2_topology_evidence_missing_or_ambiguous")
    if not checks["control_semantics_evidence"]:
        errors.append("historical_c2_control_semantics_not_proven")
    if not checks["hard_audit_passed"]:
        errors.append("historical_c2_hard_integrity_failed")
    if not checks["finite_state"]:
        errors.append("historical_c2_active_state_nonfinite")
    if not checks["finite_wall"]:
        errors.append(f"historical_c2_finite_wall_violation_count:{independent.get('wall_violation_count')}")
    if not checks["source_semantics"]:
        errors.append("historical_c2_source_semantics_missing")
    return {
        "status": "passed" if not errors else "bounded_rejection",
        "source": "historical_c2_canary",
        "checks": checks,
        "case_id": audit.get("case_id"),
        "recipe_id": input_record.get("recipe_id"),
        "errors": _unique(errors),
        "claim": (
            "new geometry/control evidence passes the hard canary contract"
            if not errors else "C2 remains a bounded canary finding and is not F3R qualification evidence"
        ),
    }


def _source_refs(
    canonical_path: Path,
    gate_path: Path,
    c2_path: Path,
    candidate_path: Path | None = None,
) -> list[dict[str, Any]]:
    paths = [
        ("canonical_manifest", canonical_path),
        ("reference_recipe_gate", gate_path),
        ("historical_control_geometry_canary", c2_path),
    ]
    if candidate_path is not None:
        paths.append(("f3r_candidate_bundle", candidate_path))
    return [{"role": role, **file_ref(path)} for role, path in paths]


def _blocker_records(
    recipe: dict[str, Any],
    coverage: dict[str, Any],
    control: dict[str, Any],
    candidate_recipe: dict[str, Any],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for section_name, section in (
        ("reference_recipe", recipe),
        ("candidate_recipe", candidate_recipe),
        ("background_resolution", coverage),
        ("control_geometry", control),
    ):
        for error in section.get("errors", []):
            records.append({"section": section_name, "code": str(error)})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for record in records:
        unique[(record["section"], record["code"])] = record
    return list(unique.values())


def build_report(
    canonical: dict[str, Any],
    gate: dict[str, Any],
    c2_report: dict[str, Any],
    *,
    candidate: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """Build an auditable report without changing campaign state."""

    reference_recipe = assess_reference_recipe(canonical, gate)
    candidate_recipe = assess_candidate_recipe(candidate)
    coverage = assess_background_resolution_coverage(canonical, candidate)
    control = assess_control_geometry_evidence(c2_report, candidate)
    blockers = _blocker_records(reference_recipe, coverage, control, candidate_recipe)
    # A legacy reference passing its own gate is not enough.  Only an explicit
    # new candidate bundle can satisfy the F3R decision, and all three axes
    # must pass together.
    qualified = bool(
        candidate is not None
        and candidate_recipe["status"] == "qualified_recipe"
        and coverage["status"] == "passed"
        and control["status"] == "passed"
    )
    return {
        "schema": SCHEMA,
        "task_id": "F3R",
        "family": FAMILY,
        "created_at_utc": utc_now(),
        "commit": commit if commit is not None else git_head(),
        "scope": {
            "legacy_reference": "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818",
            "new_subdomains": [
                "off_axis_baffle_connected_passage",
                "multi_axis_prescribed_drive",
            ],
            "unit": "family x geometry/control subdomain x recipe x task x observation scale",
        },
        "source_evidence": sources or [],
        "candidate_contract": candidate_contract(),
        "reference_recipe": reference_recipe,
        "candidate_recipe": candidate_recipe,
        "background_resolution_coverage": coverage,
        "new_control_geometry_evidence": control,
        "decision": "qualified_recipe" if qualified else "bounded_rejection",
        "blockers": blockers,
        "receipt_policy": {
            "receipt_emitted": False,
            "reason": "F3R research entry is not the downstream scoped receipt writer",
            "legacy_canary_promotion_forbidden": True,
        },
        "experiment_plan": {
            "solver_matrix_launched": False,
            "gpu_dispatch_required": not qualified,
            "recommended_resources": {
                "canary": "one idle physical A6000; keep the GPU index explicit in the attempt record",
                "reference_matrix": "two backgrounds x three resolutions; at most one heavy solver per selected A6000 until measured safe",
                "suggested_local_pool": "owner selects idle physical GPU from 0..7; this entry does not assume an index",
            },
            "read_only_commands": [
                "cd /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab && .venv/bin/python scripts/l2_f3r_research.py preflight",
                "cd /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab && .venv/bin/python scripts/l2_f3r_research.py preflight --candidate /absolute/path/to/F3R_BUNDLE.json",
            ],
            "historical_canary_command": {
                "command": "cd /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab && .venv/bin/python scripts/l2_c2_canary.py --gpu <idle_physical_a6000_index>",
                "status": "reference_only; do not rerun from this entry until a fresh F3R namespace/runner and repaired input contract are approved",
            },
        },
        "next_actions": [
            "Keep the existing 32-case F3 starter read-only and label it reference-only.",
            "Repair and re-audit the off-axis canary before spending the two-background by three-resolution budget.",
            "Add a paired multi-axis prescribed-drive background with explicit control semantics and source hashes.",
            "Only after every F3R axis passes may a downstream controller consider a scoped receipt; this entry never creates one.",
        ],
    }


def load_default_report(candidate_path: Path | None = None) -> dict[str, Any]:
    candidate = read_json(candidate_path) if candidate_path is not None else None
    return build_report(
        read_json(DEFAULT_CANONICAL),
        read_json(DEFAULT_GATE),
        read_json(DEFAULT_C2_REPORT),
        candidate=candidate,
        sources=_source_refs(DEFAULT_CANONICAL, DEFAULT_GATE, DEFAULT_C2_REPORT, candidate_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight",), help="read-only F3R evidence audit")
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--c2-report", type=Path, default=DEFAULT_C2_REPORT)
    parser.add_argument("--candidate", type=Path, help="optional l2r.f3r.candidate.v1 evidence bundle")
    parser.add_argument("--output", type=Path, help="optional JSON report path; no receipt is ever written")
    args = parser.parse_args(argv)
    candidate = read_json(args.candidate) if args.candidate else None
    report = build_report(
        read_json(args.canonical),
        read_json(args.gate),
        read_json(args.c2_report),
        candidate=candidate,
        sources=_source_refs(args.canonical, args.gate, args.c2_report, args.candidate),
    )
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["decision"] == "qualified_recipe" else 2


if __name__ == "__main__":
    raise SystemExit(main())
