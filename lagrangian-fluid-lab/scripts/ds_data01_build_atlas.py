#!/usr/bin/env python3
"""Build the DS-DATA-01 mechanism atlas from rebound and canary receipts.

This is a dataset bookkeeping step only.  It does not launch GenCase,
DualSPHysics, PartVTK, a learner, or a checkpoint evaluation.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
OUTPUT_JSON = CAMPAIGN_ROOT / "D02_MECHANISM_ATLAS.json"
OUTPUT_CSV = CAMPAIGN_ROOT / "D02_MECHANISM_ATLAS.csv"
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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative_path(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(LAB_ROOT))
        except ValueError:
            return str(candidate)
    return str(candidate)


def hdf5_path(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = LAB_ROOT / candidate
    return candidate


def infer_dimension(path: str | None) -> str:
    """Infer 2D/3D from the stored z coordinate, conservatively."""
    candidate = hdf5_path(path)
    if candidate is None or not candidate.is_file():
        return "unknown"
    try:
        with h5py.File(candidate, "r") as h5:
            if "position" not in h5 or "valid" not in h5:
                return "unknown"
            position = h5["position"][:]
            valid = h5["valid"][:]
            z = position[..., 2][valid]
            if z.size == 0:
                return "unknown"
            return "3D" if bool(np.any(np.abs(z) > 1.0e-8)) else "2D"
    except (OSError, KeyError, ValueError):
        return "unknown"


def compact_quality(
    audit: dict[str, Any],
    path: str | None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = fallback or {}
    valid_shape = audit.get("valid_shape")
    active_initial = audit.get("active_initial", audit.get("active_count_initial"))
    active_final = audit.get("active_final", audit.get("active_count_final"))
    identity_count = audit.get("identity_count")
    if active_initial is None:
        active_initial = audit.get("particles_initial")
    if active_final is None:
        active_final = audit.get("particles_final")
    retention = audit.get("identity_retention", fallback.get("identity_retention"))
    retention_basis = "stored_identity_audit" if audit.get("identity_retention") is not None else (
        "prior_trajectory_audit" if fallback.get("identity_retention") is not None else None
    )
    if retention is None and active_initial is not None and active_final is not None:
        retention = float(active_final) / max(1, int(active_initial))
        retention_basis = "active_count_ratio_fallback"
    return {
        "quality_level": "Q-I",
        "q_i_status": audit.get("status", "not_audited"),
        "hdf5": relative_path(path),
        "time_count": audit.get("time_count"),
        "time_start": audit.get("time_start"),
        "time_end": audit.get("time_end"),
        "valid_shape": valid_shape,
        "identity_count": identity_count,
        "active_initial": active_initial,
        "active_final": active_final,
        "identity_retention": retention,
        "identity_retention_basis": retention_basis,
        "introduced_after_initial": audit.get("introduced_after_initial", audit.get("identities_introduced_after_initial")),
        "initial_missing_at_final": audit.get("initial_missing_at_final"),
        "finite_active": audit.get("finite_active", {
            "position": audit.get("finite_active_position"),
            "velocity": audit.get("finite_active_velocity"),
            "density": audit.get("finite_active_density"),
            "pressure": audit.get("finite_active_pressure"),
        }),
        "positive_active_mass": audit.get("positive_active_mass", audit.get("mass_positive_active")),
        "source_sha256": audit.get("sha256"),
    }


def role_from_status(status: str) -> tuple[str, str]:
    if "exclusion" in status:
        return "exclusion_negative", "retained as an explicit negative boundary/lifecycle result"
    if "diagnostic" in status:
        return "diagnostic", "requires a scope-specific flux, lineage, or missing-mass audit"
    if "calibration" in status:
        return "calibration", "2D/control contrast retained for calibration, not 3D production qualification"
    return "candidate_pending_D03", "eligible for D03 scope audit only; no scientific acceptance yet"


def official_records() -> list[dict[str, Any]]:
    receipt = read_json(CAMPAIGN_ROOT / "D02_OFFICIAL_REUSE_RECEIPT.json")
    records: list[dict[str, Any]] = []
    for item in receipt["cases"]:
        status = item.get("scope_status", "historical_reuse_candidate_pending_D03")
        role, role_reason = role_from_status(status)
        h5 = item.get("normalized_hdf5", {}).get("path")
        audit = item.get("normalized_hdf5", {})
        records.append({
            "case_id": item["case_id"],
            "family": item["family"],
            "mechanism": item["mechanism"],
            "source_type": "official_historical_reuse",
            "source": item.get("source"),
            "derivation_status": "official_example_historical_solver_run_rebound_without_reexecution",
            "dimension": infer_dimension(h5),
            "resolution_role": "historical_reuse",
            "status": status,
            "dataset_role": role,
            "role_reason": role_reason,
            "scientific_acceptance": "not_assessed",
            "learning_attempts": item.get("learning_attempts", 0),
            "official_source_tree_sha256": item.get("source_tree_sha256"),
            "generated_xml_sha256": item.get("generated_xml_sha256"),
            "run_tree_sha256": item.get("run_tree_sha256"),
            "raw_output": relative_path(item.get("generated_case_prefix")),
            "normalized_hdf5": relative_path(h5),
            "quality": compact_quality(audit, h5, item.get("prior_trajectory_audit")),
            "scope_audit_note": item.get("provenance_status"),
        })
    return records


def w06_records() -> list[dict[str, Any]]:
    receipt = read_json(CAMPAIGN_ROOT / "D02_F2_W06_REUSE_RECEIPT.json")
    records: list[dict[str, Any]] = []
    for item in receipt["cases"]:
        status = item.get("status", "candidate_reuse_pending_D03")
        role, role_reason = role_from_status(status)
        h5 = item.get("hdf5")
        records.append({
            "case_id": item["case_id"],
            "family": item["family"],
            "mechanism": item["mechanism"],
            "source_type": "custom_derived_historical_reuse",
            "source": "custom W06 rotating-pour derivation",
            "derivation_status": item.get("derivation_status"),
            "dimension": infer_dimension(h5),
            "resolution_role": "12-case mechanism exploration",
            "status": status,
            "dataset_role": role,
            "role_reason": role_reason,
            "scientific_acceptance": "not_assessed",
            "learning_attempts": item.get("learning_attempts", 0),
            "official_source_tree_sha256": None,
            "generated_xml_sha256": item.get("definition_sha256"),
            "run_tree_sha256": item.get("latest_run_receipt_sha256"),
            "raw_output": relative_path(item.get("attempt_directory")),
            "normalized_hdf5": relative_path(h5),
            "quality": compact_quality(item.get("hdf5_audit", {}), h5),
            "scope_audit_note": "; ".join([
                f"geometry={item.get('geometry')}",
                f"state={item.get('state')}",
                "custom-derived, not an official raw example",
            ]),
            "control": item.get("control"),
            "mechanism_audit": item.get("mechanism_audit"),
        })
    return records


def canary_records() -> list[dict[str, Any]]:
    run = read_json(CAMPAIGN_ROOT / "d02" / "canaries" / "run-summary.json")
    conversion = read_json(CAMPAIGN_ROOT / "d02" / "canaries" / "conversion-summary.json")
    converted = {item["case_id"]: item for item in conversion["cases"]}
    records: list[dict[str, Any]] = []
    for item in run["cases"]:
        case_id = item["case_id"]
        converted_item = converted.get(case_id)
        if converted_item is None:
            continue
        if item.get("family") == "F4":
            status = "diagnostic_open_lifecycle_requires_flux_audit"
            role = "diagnostic"
            role_reason = "initial liquid count is nonzero only after open-boundary introduction; not a closed-system anchor"
        elif item.get("resolution_role") == "2D_calibration_contrast":
            status = "calibration_2d_anchor_pending_D03"
            role = "calibration"
            role_reason = "2D control contrast retained for calibration and evaluator tests"
        else:
            status = "candidate_pending_D03"
            role = "candidate_pending_D03"
            role_reason = "official recipe reproduced at a recorded coarse canary resolution; D03 scope audit remains"
        h5 = converted_item.get("normalized_hdf5")
        records.append({
            "case_id": case_id,
            "family": item["family"],
            "mechanism": item["mechanism"],
            "source_type": "official_canary_reproduction",
            "source": item.get("source"),
            "derivation_status": item.get("source_reproduction"),
            "dimension": item.get("dimension", infer_dimension(h5)),
            "resolution_role": item.get("resolution_role"),
            "status": status,
            "dataset_role": role,
            "role_reason": role_reason,
            "scientific_acceptance": "not_assessed",
            "learning_attempts": item.get("learning_attempts", 0),
            "official_source_tree_sha256": None,
            "generated_xml_sha256": None,
            "run_tree_sha256": item.get("raw_tree_sha256"),
            "raw_output": relative_path(item.get("raw_output_root")),
            "normalized_hdf5": relative_path(h5),
            "quality": compact_quality(converted_item.get("audit", {}), h5),
            "scope_audit_note": "; ".join([
                f"dp={item.get('dp')}",
                f"tmax={item.get('tmax')}",
                f"gpu={item.get('gpu')}",
                "solver/reproduction completed; no learner invoked",
            ]),
            "canary": {
                "base": item.get("base"),
                "dp": item.get("dp"),
                "tmax": item.get("tmax"),
                "tout": item.get("tout"),
                "gpu": item.get("gpu"),
                "frames": item.get("frames"),
                "returncode": item.get("returncode"),
                "raw_tree_sha256": item.get("raw_tree_sha256"),
                "normalized_sha256": converted_item.get("audit", {}).get("sha256"),
            },
        })
    return records


def family_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["family"]].append(record)
    result = []
    for family in [f"F{i}" for i in range(1, 8)]:
        items = grouped.get(family, [])
        result.append({
            "family": family,
            "actual_case_count": len(items),
            "source_type_counts": dict(sorted(Counter(item["source_type"] for item in items).items())),
            "dataset_role_counts": dict(sorted(Counter(item["dataset_role"] for item in items).items())),
            "dimensions": sorted({item["dimension"] for item in items}),
            "q_i_structure_pass_count": sum(item["quality"]["q_i_status"] == "Q-I-structure-pass" for item in items),
            "observed_mechanisms": sorted({item["mechanism"] for item in items}),
            "represented_by_actual_trace": bool(items),
            "production_eligible_count": 0,
            "scientific_acceptance": "not_assessed",
        })
    return result


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def main() -> int:
    records = official_records() + w06_records() + canary_records()
    records.sort(key=lambda item: (item["family"], item["case_id"]))
    families = family_summaries(records)
    q_i_pass = sum(item["quality"]["q_i_status"] == "Q-I-structure-pass" for item in records)
    payload = {
        "schema": "ds-data-01.d02.mechanism-atlas.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "dataset-only; official examples and bounded derived exploration; no training, inference, checkpoint replay, tuning, ranking, or model qualification",
        "learning_attempts": 0,
        "counts": {
            "families": len([item for item in families if item["represented_by_actual_trace"]]),
            "families_expected": 7,
            "cases": len(records),
            "q_i_structure_pass": q_i_pass,
            "candidate_pending_D03": sum(item["dataset_role"] == "candidate_pending_D03" for item in records),
            "diagnostic": sum(item["dataset_role"] == "diagnostic" for item in records),
            "calibration": sum(item["dataset_role"] == "calibration" for item in records),
            "exclusion_negative": sum(item["dataset_role"] == "exclusion_negative" for item in records),
            "production_eligible": 0,
        },
        "acceptance_boundary": {
            "q_i_structure_pass_is_not_scientific_acceptance": True,
            "scientific_acceptance_assessed": False,
            "production_eligible": False,
            "d03_required_before_any_dataset_split_or_batch_reuse": True,
        },
        "families": families,
        "cases": records,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fieldnames = [
        "case_id",
        "family",
        "mechanism",
        "source_type",
        "source",
        "derivation_status",
        "dimension",
        "resolution_role",
        "status",
        "dataset_role",
        "role_reason",
        "scientific_acceptance",
        "normalized_hdf5",
        "raw_output",
        "q_i_status",
        "time_count",
        "time_start",
        "time_end",
        "valid_shape",
        "identity_count",
        "active_initial",
        "active_final",
        "identity_retention",
        "introduced_after_initial",
        "initial_missing_at_final",
        "positive_active_mass",
        "source_sha256",
        "scope_audit_note",
    ]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in records:
            quality = item["quality"]
            row = {key: item.get(key) for key in fieldnames}
            row.update({
                "q_i_status": quality.get("q_i_status"),
                "time_count": quality.get("time_count"),
                "time_start": quality.get("time_start"),
                "time_end": quality.get("time_end"),
                "valid_shape": quality.get("valid_shape"),
                "identity_count": quality.get("identity_count"),
                "active_initial": quality.get("active_initial"),
                "active_final": quality.get("active_final"),
                "identity_retention": quality.get("identity_retention"),
                "introduced_after_initial": quality.get("introduced_after_initial"),
                "initial_missing_at_final": quality.get("initial_missing_at_final"),
                "positive_active_mass": quality.get("positive_active_mass"),
                "source_sha256": quality.get("source_sha256"),
            })
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})

    print(json.dumps({
        "output_json": str(OUTPUT_JSON),
        "output_csv": str(OUTPUT_CSV),
        "cases": len(records),
        "families": len([item for item in families if item["represented_by_actual_trace"]]),
        "q_i_structure_pass": q_i_pass,
    }, ensure_ascii=False, indent=2))
    return 0 if len(records) == 26 and q_i_pass == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
