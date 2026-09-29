#!/usr/bin/env python3
"""Build and verify the DS-DATA-01 D04 split and lineage contract.

This script is intentionally metadata-only.  It reads the committed D02 and
D03 JSON manifests, derives conservative lineage keys, and writes the two D04
JSON artifacts.  It never opens an HDF5 file, launches a solver, reserves a
GPU, or materializes a train/validation/test split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_D02 = ROOT / "campaigns/ds-data-01/D02_MECHANISM_ATLAS.json"
DEFAULT_D03 = ROOT / "campaigns/ds-data-01/D03_SCOPE_AUDIT.json"
DEFAULT_SPEC = ROOT / "campaigns/ds-data-01/D04_SPLIT_SPEC.json"
DEFAULT_REGISTRY = ROOT / "campaigns/ds-data-01/D04_LINEAGE_REGISTRY.json"

SCHEMA = "ds-data-01.d04.split-and-lineage.v1"
ROLE_MAP = {
    "candidate_pending_D03": "candidate",
    "diagnostic": "diagnostic",
    "calibration": "calibration",
    "exclusion_negative": "exclusion",
}

D03_REASON_MAP = {
    "MISSING_MASS_SCOPE_AUDIT_REQUIRED": "D04_MISSING_MASS_SCOPE",
    "OPEN_LIFECYCLE_FLUX_AUDIT_REQUIRED": "D04_OPEN_LIFECYCLE_FLUX",
    "CLOSED_IDENTITY_OR_MASS_INVARIANT_NOT_MET": "D04_CLOSED_INVARIANT",
    "PARTICLE_ID_NOT_UNIQUE": "D04_PARTICLE_ID_NOT_UNIQUE",
    "VARIABLE_RESOLUTION_LINEAGE_AUDIT_REQUIRED": "D04_VARIABLE_RESOLUTION_LINEAGE",
    "EXCLUSION_NEGATIVE_RETAINED_AS_NEGATIVE_CONTROL": "D04_ROLE_EXCLUSION",
    "2D_CALIBRATION_ONLY": "D04_ROLE_CALIBRATION",
}

REASON_CATALOG = {
    "D04_PRODUCTION_GATE_CLOSED": "D03 reports zero production-eligible cases; no current case may receive train/validation/test labels.",
    "D04_PENDING_QE": "The case is numerically admissible but external/scientific acceptance is not assessed; defer split assignment.",
    "D04_SCOPE_REPAIR_REQUIRED": "D03 requires repair or reclassification before the case can enter a candidate split pool.",
    "D04_ROLE_DIAGNOSTIC": "Diagnostic-only evidence is retained for debugging and audit, never as a positive production split member.",
    "D04_ROLE_CALIBRATION": "Calibration/control evidence is retained for calibration only and cannot enter the 3D production split.",
    "D04_ROLE_EXCLUSION": "The case is a retained negative control and cannot enter a positive production split.",
    "D04_MISSING_MASS_SCOPE": "Particle loss is not scoped as a closed-system invariant; retain diagnostic-only until lifecycle accounting is explicit.",
    "D04_OPEN_LIFECYCLE_FLUX": "Open-boundary particle flux is present; a closed trajectory/mass split gate is invalid without flux accounting.",
    "D04_CLOSED_INVARIANT": "The current closed identity/mass invariant failed, so the candidate is deferred for repair or reclassification.",
    "D04_PARTICLE_ID_NOT_UNIQUE": "Particle identity is not unique in the current audit; trajectory lineage cannot be treated as safe.",
    "D04_VARIABLE_RESOLUTION_LINEAGE": "Resolution zones or node identity change; zone-aware lineage is required before split use.",
    "D04_METADATA_DIMENSION_CONFLICT": "D02 and D03 report different dimensions; use the D02 dimension conservatively and block production assignment until reconciled.",
    "D04_COLLISION_SAME_FAMILY": "Cases sharing a family lineage must remain in one split for family-held-out evaluation.",
    "D04_COLLISION_SAME_GEOMETRY": "Cases sharing a geometry lineage must remain in one split for geometry-held-out evaluation.",
    "D04_COLLISION_SAME_MECHANISM": "Cases sharing a canonical mechanism lineage must remain in one split for mechanism-held-out evaluation.",
    "D04_COLLISION_SAME_TRAJECTORY": "All frames, particles, windows, labels, and derived views from one trajectory lineage must remain in one split.",
    "D04_COLLISION_SAME_SOURCE": "Cases from one source recipe/tree are conservatively kept together unless an owner-approved manifest proves independence.",
    "D04_COLLISION_SAME_PARAMETER": "Cases sharing a parameter/replicate lineage must remain in one split; unknown parameter identity is never treated as unique.",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def slug(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical_mechanism(case: dict[str, Any]) -> tuple[str, str]:
    family = case["family"]
    case_id = case["case_id"]
    raw = case["mechanism"]
    if family == "F2":
        return "mechanism:F2:rotating_cup_pour_catch", "all W06 variants share the same derived mechanism"
    if case_id in {"O5_wave_runup", "O5_wave_runup_refined"}:
        return "mechanism:F5:wave_runup_moving_piston", "refined and coarse runup variants share the same physical mechanism"
    return f"mechanism:{family}:{slug(raw)}", "canonicalized from D02 mechanism"


def lineage_keys(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case["case_id"]
    family = case["family"]
    source = str(case.get("source") or "")
    source_type = str(case.get("source_type") or "unknown")
    resolution_role = str(case.get("resolution_role") or "unknown")

    if family == "F2":
        tokens = case_id.split("_")
        width = tokens[1] if len(tokens) > 1 else "unknown_width"
        state = "_".join(tokens[2:]) if len(tokens) > 2 else "unknown_state"
        geometry_id = f"geometry:derived:w06_rotating_pour:{slug(width)}"
        geometry_basis = "W06 case-id geometry token; exact geometry parameters are not present in D02"
        source_lineage_id = "source:derived:w06_rotating_pour_exploration"
        trajectory_id = f"trajectory:derived:w06:{slug(case_id)}"
        parameter_id = f"parameter:derived:w06:{slug(case_id)}"
        physical_case_id = f"physical:derived:w06:{slug(case_id)}"
        parameter_axes = {
            "geometry_variant": width,
            "state_variant": state,
            "parameter_values_available": False,
            "parameter_evidence": "D02 case_id tokenization only; no numeric parameter vector is inferred",
        }
    else:
        geometry_id = f"geometry:source:{slug(source)}" if source else f"geometry:unknown:{slug(case_id)}"
        geometry_basis = "D02 official/custom source path; no finer geometry identifier is asserted"
        source_lineage_id = f"source:{slug(source_type)}:{slug(source or case_id)}"
        if case_id in {"O5_wave_runup", "O5_wave_runup_refined"}:
            trajectory_id = "trajectory:official:main_17_wave_runup"
            parameter_id = "parameter:official:main_17_wave_runup"
            physical_case_id = "physical:official:main_17_wave_runup"
            parameter_axes = {
                "geometry_variant": "main/17_WaveRunup",
                "state_variant": "coarse_or_refined_recorded_in_case_id",
                "parameter_values_available": False,
                "parameter_evidence": "D02 source and case id only; refined/coarse are kept in one physical lineage",
            }
        else:
            trajectory_id = f"trajectory:case:{slug(case_id)}"
            parameter_id = f"parameter:case:{slug(case_id)}"
            physical_case_id = f"physical:case:{slug(case_id)}"
            parameter_axes = {
                "geometry_variant": source or "unknown",
                "state_variant": "not_explicit_in_D02",
                "parameter_values_available": False,
                "parameter_evidence": "D02 source/case metadata only; numeric values are not guessed",
            }

    mechanism_id, mechanism_basis = canonical_mechanism(case)
    return {
        "family_id": family,
        "geometry_id": geometry_id,
        "geometry_basis": geometry_basis,
        "mechanism_id": mechanism_id,
        "mechanism_basis": mechanism_basis,
        "source_lineage_id": source_lineage_id,
        "trajectory_lineage_id": trajectory_id,
        "parameter_lineage_id": parameter_id,
        "physical_case_id": physical_case_id,
        "resolution_lineage_id": f"resolution:unresolved:{slug(case_id)}",
        "resolution_identity_complete": False,
        "parameter_axes": parameter_axes,
    }


def d04_role(case: dict[str, Any]) -> str:
    try:
        return ROLE_MAP[case["dataset_role"]]
    except KeyError as exc:
        raise ValueError(f"unsupported D02 dataset_role for {case.get('case_id')}: {case.get('dataset_role')}") from exc


def dimension_record(d02_case: dict[str, Any], d03_case: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    d02_dimension = str(d02_case.get("dimension") or "unknown")
    d03_dimension = str(d03_case.get("quality", {}).get("dimension") or "unknown")
    conflicts: list[dict[str, str]] = []
    if d02_dimension != "unknown" and d03_dimension != "unknown" and d02_dimension != d03_dimension:
        conflicts.append(
            {
                "field": "dimension",
                "d02_value": d02_dimension,
                "d03_value": d03_dimension,
                "resolution": "use D02_MECHANISM_ATLAS.dimension conservatively; block production split assignment",
            }
        )
    return d02_dimension, conflicts


def decision_and_reasons(
    d02_case: dict[str, Any], d03_case: dict[str, Any], dimension_conflicts: list[dict[str, str]]
) -> tuple[str, list[str]]:
    role = d04_role(d02_case)
    reasons: list[str] = []
    scope_decision = str(d03_case.get("scope_decision") or "")

    if role == "candidate":
        if scope_decision == "numerically_admissible_pending_Q-E":
            eligibility = "deferred_pending_qe"
            reasons.extend(["D04_PENDING_QE", "D04_PRODUCTION_GATE_CLOSED"])
        else:
            eligibility = "deferred_repair_or_reclassification"
            reasons.extend(["D04_SCOPE_REPAIR_REQUIRED", "D04_PRODUCTION_GATE_CLOSED"])
    elif role == "diagnostic":
        eligibility = "rejected_diagnostic_only"
        reasons.extend(["D04_ROLE_DIAGNOSTIC", "D04_PRODUCTION_GATE_CLOSED"])
    elif role == "calibration":
        eligibility = "rejected_calibration_only"
        reasons.extend(["D04_ROLE_CALIBRATION", "D04_PRODUCTION_GATE_CLOSED"])
    else:
        eligibility = "rejected_exclusion_negative_control"
        reasons.extend(["D04_ROLE_EXCLUSION", "D04_PRODUCTION_GATE_CLOSED"])

    for code in d03_case.get("failure_codes", []):
        mapped = D03_REASON_MAP.get(code)
        if mapped and mapped not in reasons:
            reasons.append(mapped)
    if dimension_conflicts:
        reasons.append("D04_METADATA_DIMENSION_CONFLICT")
    return eligibility, reasons


def build_case(d02_case: dict[str, Any], d03_case: dict[str, Any]) -> dict[str, Any]:
    dimension, dimension_conflicts = dimension_record(d02_case, d03_case)
    lineage = lineage_keys(d02_case)
    eligibility, reasons = decision_and_reasons(d02_case, d03_case, dimension_conflicts)
    quality = d02_case.get("quality", {})
    d03_quality = d03_case.get("quality", {})
    return {
        "case_id": d02_case["case_id"],
        "family_id": d02_case["family"],
        "mechanism_raw": d02_case["mechanism"],
        "mechanism_id": lineage["mechanism_id"],
        "d04_role": d04_role(d02_case),
        "d02_dataset_role": d02_case["dataset_role"],
        "d03_scope_decision": d03_case.get("scope_decision"),
        "d03_failure_codes": list(d03_case.get("failure_codes", [])),
        "dimension": dimension,
        "dimension_authority": "D02_MECHANISM_ATLAS.dimension",
        "dimension_metadata_conflicts": dimension_conflicts,
        "source_type": d02_case.get("source_type"),
        "source": d02_case.get("source"),
        "source_lineage_id": lineage["source_lineage_id"],
        "geometry_id": lineage["geometry_id"],
        "geometry_basis": lineage["geometry_basis"],
        "mechanism_basis": lineage["mechanism_basis"],
        "trajectory_lineage_id": lineage["trajectory_lineage_id"],
        "parameter_lineage_id": lineage["parameter_lineage_id"],
        "physical_case_id": lineage["physical_case_id"],
        "resolution_lineage_id": lineage["resolution_lineage_id"],
        "resolution_identity_complete": lineage["resolution_identity_complete"],
        "parameter_axes": lineage["parameter_axes"],
        "resolution_role": d02_case.get("resolution_role"),
        "normalized_hdf5": d02_case.get("normalized_hdf5"),
        "quality": {
            "d02_q_i_status": quality.get("q_i_status"),
            "d03_q_i_status": d03_quality.get("q_i_status"),
            "d03_q_n_status": d03_quality.get("q_n_status"),
            "d03_closed_invariant_pass": d03_quality.get("closed_invariant_pass"),
        },
        "split": {
            "assigned_split": None,
            "split_eligibility": eligibility,
            "rejection_reasons": reasons,
            "whole_case_is_atomic": True,
            "frames_particles_windows_and_derived_views_inherit_case_split": True,
        },
    }


def group_view(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record[key]].append(record)
    result: list[dict[str, Any]] = []
    reason_by_key = {
        "family_id": "D04_COLLISION_SAME_FAMILY",
        "geometry_id": "D04_COLLISION_SAME_GEOMETRY",
        "mechanism_id": "D04_COLLISION_SAME_MECHANISM",
        "trajectory_lineage_id": "D04_COLLISION_SAME_TRAJECTORY",
        "source_lineage_id": "D04_COLLISION_SAME_SOURCE",
        "parameter_lineage_id": "D04_COLLISION_SAME_PARAMETER",
    }
    for value in sorted(grouped):
        members = sorted(grouped[value], key=lambda item: item["case_id"])
        result.append(
            {
                "group_id": value,
                "group_key": key,
                "case_ids": [item["case_id"] for item in members],
                "case_count": len(members),
                "family_ids": sorted({item["family_id"] for item in members}),
                "mechanism_ids": sorted({item["mechanism_id"] for item in members}),
                "dimensions": sorted({item["dimension"] for item in members}),
                "d04_roles": dict(sorted(Counter(item["d04_role"] for item in members).items())),
                "current_split": "unassigned",
                "split_refusal_reason": reason_by_key[key],
                "current_gate": "D04_PRODUCTION_GATE_CLOSED",
            }
        )
    return result


def rejection_index(records: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for record in records:
        for reason in record["split"]["rejection_reasons"]:
            index[reason].append(record["case_id"])
    return {key: sorted(value) for key, value in sorted(index.items())}


def build_artifacts(
    d02: dict[str, Any],
    d03: dict[str, Any],
    generated_at: str,
    d02_path: Path = DEFAULT_D02,
    d03_path: Path = DEFAULT_D03,
) -> tuple[dict[str, Any], dict[str, Any]]:
    d02_cases = {case["case_id"]: case for case in d02.get("cases", [])}
    d03_cases = {case["case_id"]: case for case in d03.get("cases", [])}
    if set(d02_cases) != set(d03_cases):
        missing_d03 = sorted(set(d02_cases) - set(d03_cases))
        missing_d02 = sorted(set(d03_cases) - set(d02_cases))
        raise ValueError(f"D02/D03 case-id mismatch: missing_d03={missing_d03}, missing_d02={missing_d02}")

    records: list[dict[str, Any]] = []
    for case_id in sorted(d02_cases):
        d02_case = d02_cases[case_id]
        d03_case = d03_cases[case_id]
        for field in ("family", "mechanism"):
            if d02_case.get(field) != d03_case.get(field):
                raise ValueError(f"D02/D03 {field} mismatch for {case_id}")
        records.append(build_case(d02_case, d03_case))

    role_counts = Counter(record["d04_role"] for record in records)
    family_groups = group_view(records, "family_id")
    geometry_groups = group_view(records, "geometry_id")
    mechanism_groups = group_view(records, "mechanism_id")
    trajectory_groups = group_view(records, "trajectory_lineage_id")
    source_groups = group_view(records, "source_lineage_id")
    parameter_groups = group_view(records, "parameter_lineage_id")
    input_hashes = {
        "D02_MECHANISM_ATLAS.json": sha256_file(d02_path),
        "D03_SCOPE_AUDIT.json": sha256_file(d03_path),
    }

    split_spec = {
        "schema": SCHEMA,
        "generated_at_utc": generated_at,
        "scope": "metadata-only D04 contract; no training, inference, checkpoint replay, solver launch, GPU launch, or split materialization",
        "status": "contract_frozen_current_assignments_empty",
        "inputs": {
            "D02": relative_path(d02_path),
            "D03": relative_path(d03_path),
            "sha256": input_hashes,
        },
        "current_snapshot": {
            "case_count": len(records),
            "family_count": len({record["family_id"] for record in records}),
            "role_counts": dict(sorted(role_counts.items())),
            "d03_production_eligible_count": d03.get("acceptance_boundary", {}).get("production_eligible_count"),
            "production_split_materialized": False,
            "assigned_split_counts": {"train": 0, "validation": 0, "test": 0, "holdout": 0},
            "deferred_candidate_case_ids": sorted(record["case_id"] for record in records if record["d04_role"] == "candidate"),
            "diagnostic_case_ids": sorted(record["case_id"] for record in records if record["d04_role"] == "diagnostic"),
            "calibration_case_ids": sorted(record["case_id"] for record in records if record["d04_role"] == "calibration"),
            "exclusion_case_ids": sorted(record["case_id"] for record in records if record["d04_role"] == "exclusion"),
        },
        "role_contract": {
            "candidate": {
                "source_selector": "D02.dataset_role == candidate_pending_D03",
                "current_use": "deferred_pending_qe_or_repair",
                "future_split_gate": [
                    "D03 scope_decision is numerically_admissible_pending_Q-E or a later owner-approved accepted state",
                    "scientific/external acceptance is explicitly recorded",
                    "resolution_identity_complete is true or an owner-approved conservative lineage key exists",
                    "case passes the selected split-mode collision-component audit",
                ],
                "allowed_future_uses": ["positive candidate pool after explicit acceptance"],
                "forbidden_current_uses": ["train", "validation", "test", "ranking", "model qualification"],
            },
            "diagnostic": {
                "source_selector": "D02.dataset_role == diagnostic",
                "current_use": "diagnostic_only",
                "allowed_future_uses": ["debugging", "failure analysis", "negative/diagnostic reporting"],
                "forbidden_uses": ["positive train/validation/test member", "hyperparameter tuning target"],
            },
            "calibration": {
                "source_selector": "D02.dataset_role == calibration",
                "current_use": "calibration_only",
                "allowed_future_uses": ["calibration/control contrast with an explicit calibration label"],
                "forbidden_uses": ["3D production train/validation/test member", "positive generalization score"],
            },
            "exclusion": {
                "source_selector": "D02.dataset_role == exclusion_negative",
                "current_use": "negative_control_only",
                "allowed_future_uses": ["documented exclusion/negative-control audit"],
                "forbidden_uses": ["positive train/validation/test member", "silent removal from audit history"],
            },
        },
        "parameter_contract": {
            "required_case_fields_before_future_materialization": [
                "family_id",
                "geometry_id",
                "mechanism_id",
                "trajectory_lineage_id",
                "source_lineage_id",
                "parameter_lineage_id",
                "physical_case_id",
                "dimension",
                "resolution_signature",
                "solver_recipe_signature",
                "d04_role",
            ],
            "parameter_axes": {
                "family": "top-level physical mechanism family; family-held-out axis",
                "geometry": "canonical geometry/source geometry lineage; unknown geometry is a shared conservative bucket",
                "mechanism": "canonical mechanism, with known refined/coarse variants collapsed when they describe the same physical mechanism",
                "trajectory": "complete solver trajectory lineage; all frames, particles, windows, labels, and derived views inherit it",
                "source": "official/custom recipe and source tree lineage; shared recipe is not presumed independent",
                "parameter": "exact physical parameter/replicate signature; absent numeric values are unknown, not unique",
                "resolution": "explicit physical_case_id plus resolution_signature; current D02/D03 records do not complete this field",
            },
            "missing_value_policy": "unknown or omitted lineage metadata is mapped conservatively and blocks assignment; it is never randomized or treated as a new independent case",
            "freeze_order": [
                "freeze physical parameters and solver recipe",
                "derive and review lineage keys",
                "construct collision components",
                "assign whole components to a declared split protocol",
                "only then materialize windows or derived labels",
            ],
        },
        "leakage_rules": [
            {
                "rule_id": "D04-R01",
                "name": "complete_case_atomicity",
                "rule": "A complete simulation case is the minimum split unit; never split frames, particles, time windows, trajectory prefixes, or derived labels across split labels.",
                "rejection_code": "D04_COLLISION_SAME_TRAJECTORY",
            },
            {
                "rule_id": "D04-R02",
                "name": "family_isolation",
                "rule": "For family-held-out evaluation, all cases sharing family_id stay in one split; family is not inferred from an observed trajectory or target label.",
                "rejection_code": "D04_COLLISION_SAME_FAMILY",
            },
            {
                "rule_id": "D04-R03",
                "name": "geometry_isolation",
                "rule": "Cases sharing geometry_id stay together for geometry-held-out evaluation; source-path variants are not presumed geometrically independent.",
                "rejection_code": "D04_COLLISION_SAME_GEOMETRY",
            },
            {
                "rule_id": "D04-R04",
                "name": "mechanism_isolation",
                "rule": "Canonical mechanism variants stay together for mechanism-held-out evaluation; refined/coarse records of one mechanism cannot be separated by naming alone.",
                "rejection_code": "D04_COLLISION_SAME_MECHANISM",
            },
            {
                "rule_id": "D04-R05",
                "name": "trajectory_lineage_isolation",
                "rule": "A trajectory lineage, including all restarts, output windows, particle subsets, observables, and derived products, has exactly one split label.",
                "rejection_code": "D04_COLLISION_SAME_TRAJECTORY",
            },
            {
                "rule_id": "D04-R06",
                "name": "source_recipe_isolation",
                "rule": "Cases sharing an official/custom source recipe or source tree are kept together unless an owner-approved manifest proves independent physical and numerical lineage.",
                "rejection_code": "D04_COLLISION_SAME_SOURCE",
            },
            {
                "rule_id": "D04-R07",
                "name": "parameter_and_resolution_isolation",
                "rule": "Exact physical parameters, replicate identity, numerical resolution, and solver recipe are split keys; unknown values conservatively block assignment.",
                "rejection_code": "D04_COLLISION_SAME_PARAMETER",
            },
            {
                "rule_id": "D04-R08",
                "name": "role_gate",
                "rule": "Only explicitly accepted candidate cases may enter a positive split; diagnostic, calibration, and exclusion roles remain outside the production split.",
                "rejection_code": "D04_PRODUCTION_GATE_CLOSED",
            },
        ],
        "split_modes": [
            {
                "mode": "strict_family_holdout",
                "primary_key": "family_id",
                "hard_keys": ["family_id", "geometry_id", "mechanism_id", "source_lineage_id", "trajectory_lineage_id", "parameter_lineage_id"],
                "purpose": "test generalization to an unseen physical family",
                "current_status": "contract_only_no_assignments",
            },
            {
                "mode": "strict_geometry_holdout",
                "primary_key": "geometry_id",
                "hard_keys": ["geometry_id", "source_lineage_id", "trajectory_lineage_id", "parameter_lineage_id"],
                "purpose": "test geometry extrapolation without sharing a source/trajectory/parameter lineage",
                "current_status": "contract_only_no_assignments",
            },
            {
                "mode": "strict_mechanism_holdout",
                "primary_key": "mechanism_id",
                "hard_keys": ["mechanism_id", "geometry_id", "source_lineage_id", "trajectory_lineage_id", "parameter_lineage_id"],
                "purpose": "test mechanism extrapolation while refusing geometry or recipe collisions",
                "current_status": "contract_only_no_assignments",
            },
            {
                "mode": "strict_trajectory_holdout",
                "primary_key": "trajectory_lineage_id",
                "hard_keys": ["trajectory_lineage_id", "geometry_id", "mechanism_id", "source_lineage_id", "parameter_lineage_id"],
                "purpose": "test independent trajectory lineage without sharing a physical or recipe proxy",
                "current_status": "contract_only_no_assignments",
            },
        ],
        "assignment_algorithm": {
            "algorithm": "build connected components over the active mode hard_keys, then assign complete components only",
            "permitted_labels": ["train", "validation", "test", "holdout"],
            "required_preconditions": [
                "D03 production_eligible_count > 0",
                "role is candidate",
                "no D04 rejection reason remains",
                "all required lineage/parameter fields are present and reviewed",
                "the selected mode has a recorded owner and purpose",
            ],
            "random_case_split": "forbidden",
            "random_frame_split": "forbidden",
            "particle_level_split": "forbidden",
            "post_split_derivation": "all derived windows/labels must inherit the parent case component; re-splitting after derivation is forbidden",
        },
        "reason_catalog": REASON_CATALOG,
        "review_artifacts": {
            "lineage_registry": "campaigns/ds-data-01/D04_LINEAGE_REGISTRY.json",
            "group_views": ["family_groups", "geometry_groups", "mechanism_groups", "trajectory_groups", "source_groups", "parameter_groups"],
            "case_rejection_reasons": "D04_LINEAGE_REGISTRY.json.cases[*].split.rejection_reasons",
        },
    }

    registry = {
        "schema": SCHEMA,
        "generated_at_utc": generated_at,
        "scope": "metadata-only lineage registry; no solver/GPU/model execution and no split labels materialized",
        "inputs": {
            "D02": relative_path(d02_path),
            "D03": relative_path(d03_path),
            "sha256": input_hashes,
        },
        "status": "reviewable_unassigned_registry",
        "summary": {
            "case_count": len(records),
            "family_count": len(family_groups),
            "group_counts": {
                "family": len(family_groups),
                "geometry": len(geometry_groups),
                "mechanism": len(mechanism_groups),
                "trajectory": len(trajectory_groups),
                "source": len(source_groups),
                "parameter": len(parameter_groups),
            },
            "role_counts": dict(sorted(role_counts.items())),
            "assigned_split_counts": {"train": 0, "validation": 0, "test": 0, "holdout": 0},
            "production_eligible_count_from_D03": d03.get("acceptance_boundary", {}).get("production_eligible_count"),
            "resolution_identity_complete_count": sum(1 for record in records if record["resolution_identity_complete"]),
        },
        "grouping_policy": {
            "all_group_views_are_currently_unassigned": True,
            "same_group_key_is_not_split": True,
            "unknown_metadata_is_conservative": True,
            "group_views_are": "review projections, not train/validation/test assignments",
        },
        "family_groups": family_groups,
        "geometry_groups": geometry_groups,
        "mechanism_groups": mechanism_groups,
        "trajectory_groups": trajectory_groups,
        "source_groups": source_groups,
        "parameter_groups": parameter_groups,
        "rejection_index": rejection_index(records),
        "cases": records,
        "validation": {
            "all_cases_have_one_d02_and_d03_record": True,
            "all_cases_have_nonempty_family_geometry_mechanism_trajectory_keys": True,
            "all_current_split_assignments_are_null": True,
            "diagnostic_calibration_exclusion_roles_are_not_candidate_split_members": True,
            "scientific_acceptance": "not_assessed",
        },
    }
    return split_spec, registry


def validate_artifacts(spec: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if spec.get("schema") != SCHEMA or registry.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    records = registry.get("cases", [])
    if not isinstance(records, list) or not records:
        errors.append("registry cases are empty")
        return errors
    ids = [record.get("case_id") for record in records]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case_id in registry")
    required_keys = ["family_id", "geometry_id", "mechanism_id", "trajectory_lineage_id", "source_lineage_id", "parameter_lineage_id"]
    for record in records:
        for key in required_keys:
            if not record.get(key):
                errors.append(f"{record.get('case_id')}: empty {key}")
        if record.get("split", {}).get("assigned_split") is not None:
            errors.append(f"{record.get('case_id')}: current split assignment is not null")
        if record.get("d04_role") not in {"candidate", "diagnostic", "calibration", "exclusion"}:
            errors.append(f"{record.get('case_id')}: unsupported D04 role")
    assigned = spec.get("current_snapshot", {}).get("assigned_split_counts", {})
    if any(assigned.get(label, -1) != 0 for label in ("train", "validation", "test", "holdout")):
        errors.append("split spec reports non-empty current assignments")
    if spec.get("current_snapshot", {}).get("production_split_materialized") is not False:
        errors.append("production_split_materialized must be false")
    if registry.get("summary", {}).get("production_eligible_count_from_D03") != 0:
        errors.append("D03 production gate is not zero in the current snapshot")
    return errors


def scrub_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: scrub_generated_at(item) for key, item in value.items() if key != "generated_at_utc"}
    if isinstance(value, list):
        return [scrub_generated_at(item) for item in value]
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="build and write the two D04 JSON artifacts")
    action.add_argument("--check", action="store_true", help="rebuild in memory and verify existing artifacts without writing")
    parser.add_argument("--d02", type=Path, default=DEFAULT_D02)
    parser.add_argument("--d03", type=Path, default=DEFAULT_D03)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    d02_path = args.d02.resolve()
    d03_path = args.d03.resolve()
    spec_path = args.spec.resolve()
    registry_path = args.registry.resolve()
    d02 = load_json(d02_path)
    d03 = load_json(d03_path)
    generated_at = utc_now()
    expected_spec, expected_registry = build_artifacts(d02, d03, generated_at, d02_path, d03_path)
    errors = validate_artifacts(expected_spec, expected_registry)
    if errors:
        raise SystemExit("D04 build validation failed: " + "; ".join(errors))

    if args.write:
        write_json(spec_path, expected_spec)
        write_json(registry_path, expected_registry)
        print(f"D04 WRITE PASS: {relative_path(spec_path)}, {relative_path(registry_path)}")
        print(f"cases={expected_registry['summary']['case_count']} roles={expected_registry['summary']['role_counts']} assignments=0")
        return 0

    if not spec_path.exists() or not registry_path.exists():
        raise SystemExit("D04 CHECK FAIL: expected output artifacts do not exist")
    actual_spec = load_json(spec_path)
    actual_registry = load_json(registry_path)
    actual_errors = validate_artifacts(actual_spec, actual_registry)
    if actual_errors:
        raise SystemExit("D04 CHECK FAIL: " + "; ".join(actual_errors))
    if scrub_generated_at(actual_spec) != scrub_generated_at(expected_spec):
        raise SystemExit("D04 CHECK FAIL: split spec differs from a fresh metadata-only build")
    if scrub_generated_at(actual_registry) != scrub_generated_at(expected_registry):
        raise SystemExit("D04 CHECK FAIL: lineage registry differs from a fresh metadata-only build")
    print(f"D04 CHECK PASS: cases={len(actual_registry['cases'])} assignments=0 no_solver_or_gpu_io=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
