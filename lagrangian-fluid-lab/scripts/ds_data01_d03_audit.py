#!/usr/bin/env python3
"""Run DS-DATA-01 scope-specific Q-I/Q-N audits without any learner.

The audit deliberately separates numerical integrity from scientific
acceptance.  It checks stored trajectory files, classifies lifecycle behavior,
and emits reference cards; it does not compare against an external experiment
or qualify a production dataset.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
ATLAS_PATH = CAMPAIGN_ROOT / "D02_MECHANISM_ATLAS.json"
OUTPUT_JSON = CAMPAIGN_ROOT / "D03_SCOPE_AUDIT.json"
REFERENCE_JSON = CAMPAIGN_ROOT / "D03_REFERENCE_CARDS.json"
FAILURE_MD = CAMPAIGN_ROOT / "D03_FAILURE_MAP.md"
OUTPUT_CSV = CAMPAIGN_ROOT / "D03_SCOPE_AUDIT.csv"
REQUIRED_DATASETS = {
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
}


def h5_path(relative: str) -> Path:
    candidate = Path(relative)
    return candidate if candidate.is_absolute() else LAB_ROOT / candidate


def as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def audit_hdf5(relative: str) -> dict[str, Any]:
    path = h5_path(relative)
    if not path.is_file():
        return {
            "q_i_status": "Q-I-file-missing",
            "q_n_status": "Q-N-not-assessed",
            "failure_codes": ["FILE_MISSING"],
            "hdf5": relative,
        }
    try:
        with h5py.File(path, "r") as h5:
            missing = sorted(REQUIRED_DATASETS - set(h5.keys()))
            if missing:
                return {
                    "q_i_status": "Q-I-schema-fail",
                    "q_n_status": "Q-N-not-assessed",
                    "failure_codes": ["SCHEMA_INCOMPLETE"],
                    "missing_datasets": missing,
                    "hdf5": relative,
                }
            time = h5["time"][:]
            particle_id = h5["particle_id"][:]
            valid = h5["valid"][:].astype(bool)
            position = h5["position"][:]
            velocity = h5["velocity"][:]
            density = h5["density"][:]
            mass = h5["mass"][:]
            pressure = h5["pressure"][:]

            initial_ids = set(int(value) for value in particle_id[valid[0]])
            final_ids = set(int(value) for value in particle_id[valid[-1]])
            ever_ids = set(int(value) for value in particle_id[valid.any(axis=0)])
            common_ids = initial_ids & final_ids
            active_count = valid.sum(axis=1).astype(int)
            active_mass = np.where(valid, mass, 0.0).sum(axis=1, dtype=np.float64)
            initial_mass = float(active_mass[0]) if len(active_mass) else 0.0
            mass_relative = (active_mass / initial_mass - 1.0) if initial_mass > 0 else np.full(len(active_mass), np.nan)
            active_mask = valid
            finite = {
                "position": bool(np.isfinite(position[active_mask]).all()),
                "velocity": bool(np.isfinite(velocity[active_mask]).all()),
                "density": bool(np.isfinite(density[active_mask]).all()),
                "pressure": bool(np.isfinite(pressure[active_mask]).all()),
                "mass": bool(np.isfinite(mass[active_mask]).all()),
            }
            positive_mass = bool(np.all(mass[active_mask] > 0))
            positive_density = bool(np.all(density[active_mask] > 0))
            times_strict = bool(len(time) >= 2 and np.all(np.diff(time) > 0))
            ids_unique = len(set(int(value) for value in particle_id)) == len(particle_id)
            common_mask = np.array([int(value) in common_ids for value in particle_id])
            common_valid = common_mask & valid[0] & valid[-1]
            displacement = np.linalg.norm(position[-1, common_valid] - position[0, common_valid], axis=1)
            speed = np.linalg.norm(velocity[active_mask], axis=1)
            centroids = []
            for index in range(len(time)):
                mask = valid[index]
                centroids.append(position[index, mask].mean(axis=0).tolist() if mask.any() else [None, None, None])
            z = position[..., 2][active_mask]
            dimension = "3D" if z.size and bool(np.any(np.abs(z) > 1.0e-8)) else "2D"
            q_i_failures = []
            if not times_strict:
                q_i_failures.append("TIME_NOT_STRICTLY_INCREASING")
            if not all(finite.values()):
                q_i_failures.append("NONFINITE_ACTIVE_FIELD")
            if not positive_mass:
                q_i_failures.append("NONPOSITIVE_ACTIVE_MASS")
            if not positive_density:
                q_i_failures.append("NONPOSITIVE_ACTIVE_DENSITY")
            if not ids_unique:
                q_i_failures.append("PARTICLE_ID_NOT_UNIQUE")
            q_i_status = "Q-I-structure-pass" if not q_i_failures else "Q-I-structure-fail"
            q_n_failures = []
            if not np.isfinite(active_mass).all():
                q_n_failures.append("NONFINITE_ACTIVE_MASS_SUM")
            if initial_mass <= 0:
                q_n_failures.append("ZERO_INITIAL_ACTIVE_MASS")
            q_n_status = "Q-N-integrity-pass" if not q_n_failures else "Q-N-integrity-fail"
            mass_range = float(np.nanmax(mass_relative) - np.nanmin(mass_relative)) if len(mass_relative) else None
            closed_invariant_pass = bool(
                q_i_status == "Q-I-structure-pass"
                and q_n_status == "Q-N-integrity-pass"
                and len(ever_ids - initial_ids) == 0
                and len(initial_ids - final_ids) == 0
                and (mass_range is not None and mass_range <= 1.0e-4)
            )
            return {
                "hdf5": relative,
                "q_i_status": q_i_status,
                "q_n_status": q_n_status,
                "failure_codes": q_i_failures + q_n_failures,
                "dimension": dimension,
                "dataset_keys": sorted(h5.keys()),
                "time_count": int(len(time)),
                "time_start": as_float(time[0]) if len(time) else None,
                "time_end": as_float(time[-1]) if len(time) else None,
                "time_strictly_increasing": times_strict,
                "identity_count": int(len(particle_id)),
                "active_count_by_frame": active_count.tolist(),
                "active_initial": int(active_count[0]) if len(active_count) else 0,
                "active_final": int(active_count[-1]) if len(active_count) else 0,
                "identity_retention_initial_to_final": float(len(common_ids) / max(1, len(initial_ids))),
                "introduced_identity_count": int(len(ever_ids - initial_ids)),
                "initial_identity_missing_at_final": int(len(initial_ids - final_ids)),
                "finite_active": finite,
                "positive_active_mass": positive_mass,
                "positive_active_density": positive_density,
                "active_mass_initial": initial_mass,
                "active_mass_final": float(active_mass[-1]) if len(active_mass) else None,
                "active_mass_relative_to_initial": [as_float(value) for value in mass_relative],
                "active_mass_relative_range": mass_range,
                "density_min": as_float(np.nanmin(density[active_mask])) if active_mask.any() else None,
                "density_max": as_float(np.nanmax(density[active_mask])) if active_mask.any() else None,
                "pressure_min": as_float(np.nanmin(pressure[active_mask])) if active_mask.any() else None,
                "pressure_max": as_float(np.nanmax(pressure[active_mask])) if active_mask.any() else None,
                "max_speed": as_float(np.nanmax(speed)) if speed.size else None,
                "mean_displacement_common": as_float(displacement.mean()) if displacement.size else None,
                "max_displacement_common": as_float(displacement.max()) if displacement.size else None,
                "centroid_initial": centroids[0] if centroids else None,
                "centroid_final": centroids[-1] if centroids else None,
                "closed_invariant_pass": closed_invariant_pass,
                "closed_invariant_tolerance": 1.0e-4,
            }
    except (OSError, KeyError, ValueError, IndexError) as exc:
        return {
            "hdf5": relative,
            "q_i_status": "Q-I-audit-error",
            "q_n_status": "Q-N-not-assessed",
            "failure_codes": ["AUDIT_EXCEPTION"],
            "audit_error": repr(exc),
        }


def classify_scope(record: dict[str, Any], audit: dict[str, Any]) -> tuple[str, list[str]]:
    role = record["dataset_role"]
    status = record["status"]
    failures: list[str] = []
    if role == "exclusion_negative":
        failures.append("EXCLUSION_NEGATIVE_RETAINED_AS_NEGATIVE_CONTROL")
        return "exclude_from_core", failures
    if role == "calibration":
        failures.append("2D_CALIBRATION_ONLY")
        return "calibration_only", failures
    if "open_lifecycle" in status or record["case_id"] in {"O4_impinging_jet", "F4_shapes_inlet3d"}:
        failures.append("OPEN_LIFECYCLE_FLUX_AUDIT_REQUIRED")
        return "diagnostic_open_lifecycle", failures
    if "variable_resolution" in status or record["case_id"] == "O6_falling_wedge_vres":
        failures.append("VARIABLE_RESOLUTION_LINEAGE_AUDIT_REQUIRED")
        return "diagnostic_variable_resolution", failures
    if "missing_mass" in status:
        failures.append("MISSING_MASS_SCOPE_AUDIT_REQUIRED")
        return "diagnostic_missing_mass", failures
    if audit.get("q_i_status") != "Q-I-structure-pass":
        failures.extend(audit.get("failure_codes", []))
        return "reject_numerical_integrity", failures
    if audit.get("q_n_status") != "Q-N-integrity-pass":
        failures.extend(audit.get("failure_codes", []))
        return "reject_numerical_integrity", failures
    if role == "candidate_pending_D03" and audit.get("closed_invariant_pass"):
        return "numerically_admissible_pending_Q-E", failures
    if role == "candidate_pending_D03":
        failures.append("CLOSED_IDENTITY_OR_MASS_INVARIANT_NOT_MET")
        return "candidate_requires_repair_or_reclassification", failures
    return "diagnostic_scope_unresolved", ["UNCLASSIFIED_SCOPE"]


def reference_card(record: dict[str, Any], audit: dict[str, Any], decision: str) -> dict[str, Any]:
    return {
        "case_id": record["case_id"],
        "family": record["family"],
        "mechanism": record["mechanism"],
        "source": record["source"],
        "source_type": record["source_type"],
        "dimension": audit.get("dimension", record.get("dimension")),
        "trajectory": {
            "hdf5": record["normalized_hdf5"],
            "time_start": audit.get("time_start"),
            "time_end": audit.get("time_end"),
            "frame_count": audit.get("time_count"),
            "active_count_by_frame": audit.get("active_count_by_frame"),
        },
        "mechanism_observables": [
            "active_particle_count",
            "active_mass",
            "centroid",
            "common_identity_displacement",
            "max_speed",
            "density_range",
            "pressure_range",
        ],
        "computed_reference": {
            "active_mass_initial": audit.get("active_mass_initial"),
            "active_mass_final": audit.get("active_mass_final"),
            "active_mass_relative_range": audit.get("active_mass_relative_range"),
            "centroid_initial": audit.get("centroid_initial"),
            "centroid_final": audit.get("centroid_final"),
            "max_speed": audit.get("max_speed"),
            "density_min": audit.get("density_min"),
            "density_max": audit.get("density_max"),
            "pressure_min": audit.get("pressure_min"),
            "pressure_max": audit.get("pressure_max"),
        },
        "reference_status": "internal_mechanism_reference_only",
        "q_e_status": "not_assessed_no_external_measurement_or_ground_truth_bound",
        "scope_decision": decision,
        "scientific_acceptance": "not_assessed",
    }


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def main() -> int:
    atlas = json.loads(ATLAS_PATH.read_text(encoding="utf-8"))
    audited_cases: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    failure_map: dict[str, dict[str, Any]] = {}
    for record in atlas["cases"]:
        audit = audit_hdf5(record["normalized_hdf5"])
        decision, scope_failures = classify_scope(record, audit)
        all_failures = list(dict.fromkeys(audit.get("failure_codes", []) + scope_failures))
        result = {
            "case_id": record["case_id"],
            "family": record["family"],
            "mechanism": record["mechanism"],
            "source_type": record["source_type"],
            "dataset_role": record["dataset_role"],
            "status_before_D03": record["status"],
            "scope_decision": decision,
            "failure_codes": all_failures,
            "quality": audit,
            "scientific_acceptance": "not_assessed",
            "learning_attempts": 0,
        }
        audited_cases.append(result)
        cards.append(reference_card(record, audit, decision))
        for code in all_failures:
            failure_map.setdefault(code, {
                "code": code,
                "case_count": 0,
                "cases": [],
                "meaning": {
                    "OPEN_LIFECYCLE_FLUX_AUDIT_REQUIRED": "particle population changes because an open boundary introduces or removes particles; a closed-system mass gate is invalid without flux accounting",
                    "VARIABLE_RESOLUTION_LINEAGE_AUDIT_REQUIRED": "particle identity and/or resolution zones change; lineage and zone-aware observables are required",
                    "MISSING_MASS_SCOPE_AUDIT_REQUIRED": "the derived rotating-pour report records numerically missing particles; retain as diagnostic until the lifecycle scope is explicit",
                    "EXCLUSION_NEGATIVE_RETAINED_AS_NEGATIVE_CONTROL": "historical run is retained to document a known unsuitable scope, not as a positive dataset member",
                    "2D_CALIBRATION_ONLY": "2D contrast is useful for calibration/control tests but is not a 3D production acceptance case",
                    "CLOSED_IDENTITY_OR_MASS_INVARIANT_NOT_MET": "candidate does not satisfy the current closed-trajectory identity/mass invariant",
                }.get(code, "see per-case Q-I/Q-N audit"),
            })
            failure_map[code]["case_count"] += 1
            failure_map[code]["cases"].append(result["case_id"])

    decisions = {}
    for item in audited_cases:
        decisions[item["scope_decision"]] = decisions.get(item["scope_decision"], 0) + 1
    q_i_pass = sum(item["quality"].get("q_i_status") == "Q-I-structure-pass" for item in audited_cases)
    q_n_pass = sum(item["quality"].get("q_n_status") == "Q-N-integrity-pass" for item in audited_cases)
    payload = {
        "schema": "ds-data-01.d03.scope-audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "dataset-only; numerical integrity and scope classification; no training, inference, checkpoint replay, tuning, ranking, or model qualification",
        "learning_attempts": 0,
        "acceptance_boundary": {
            "q_i_structure_pass_count": q_i_pass,
            "q_n_integrity_pass_count": q_n_pass,
            "q_e_external_validation_assessed": False,
            "scientific_acceptance_assessed": False,
            "production_eligible_count": 0,
            "closed_invariant_tolerance": 1.0e-4,
        },
        "decision_counts": decisions,
        "failure_map": failure_map,
        "cases": audited_cases,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REFERENCE_JSON.write_text(json.dumps({
        "schema": "ds-data-01.d03.reference-cards.v1",
        "generated_at_utc": payload["generated_at_utc"],
        "q_e_status": "not_assessed_no_external_measurement_or_ground_truth_bound",
        "scientific_acceptance": "not_assessed",
        "cards": cards,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        "# DS-DATA-01 D03 failure map",
        "",
        "This map is a dataset-scope diagnostic. Q-I/Q-N checks do not constitute scientific acceptance.",
        "",
        "| Code | Cases | Meaning |",
        "|---|---:|---|",
    ]
    for code in sorted(failure_map):
        item = failure_map[code]
        meaning = item["meaning"].replace("|", "\\|")
        md_lines.append(f"| `{code}` | {item['case_count']} | {meaning} |")
    md_lines.extend([
        "",
        "## Boundary",
        "",
        "- Q-E external validation is not assessed because no external measurement/ground-truth binding was added in this dataset-only pass.",
        "- Production eligibility remains zero until a later owner-approved scope and split contract consume these audits.",
    ])
    FAILURE_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    fieldnames = [
        "case_id",
        "family",
        "mechanism",
        "source_type",
        "dataset_role",
        "status_before_D03",
        "scope_decision",
        "q_i_status",
        "q_n_status",
        "dimension",
        "time_count",
        "active_initial",
        "active_final",
        "identity_retention_initial_to_final",
        "introduced_identity_count",
        "initial_identity_missing_at_final",
        "active_mass_relative_range",
        "closed_invariant_pass",
        "failure_codes",
    ]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in audited_cases:
            quality = item["quality"]
            row = {
                "case_id": item["case_id"],
                "family": item["family"],
                "mechanism": item["mechanism"],
                "source_type": item["source_type"],
                "dataset_role": item["dataset_role"],
                "status_before_D03": item["status_before_D03"],
                "scope_decision": item["scope_decision"],
                "q_i_status": quality.get("q_i_status"),
                "q_n_status": quality.get("q_n_status"),
                "dimension": quality.get("dimension"),
                "time_count": quality.get("time_count"),
                "active_initial": quality.get("active_initial"),
                "active_final": quality.get("active_final"),
                "identity_retention_initial_to_final": quality.get("identity_retention_initial_to_final"),
                "introduced_identity_count": quality.get("introduced_identity_count"),
                "initial_identity_missing_at_final": quality.get("initial_identity_missing_at_final"),
                "active_mass_relative_range": quality.get("active_mass_relative_range"),
                "closed_invariant_pass": quality.get("closed_invariant_pass"),
                "failure_codes": item["failure_codes"],
            }
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})

    print(json.dumps({
        "scope_audit": str(OUTPUT_JSON),
        "reference_cards": str(REFERENCE_JSON),
        "failure_map": str(FAILURE_MD),
        "cases": len(audited_cases),
        "q_i_structure_pass": q_i_pass,
        "q_n_integrity_pass": q_n_pass,
        "decision_counts": decisions,
        "production_eligible": 0,
    }, ensure_ascii=False, indent=2))
    return 0 if len(audited_cases) == atlas["counts"]["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
