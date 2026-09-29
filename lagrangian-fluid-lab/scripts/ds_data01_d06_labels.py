#!/usr/bin/env python3
"""Read-only D06 native-label and optional-tracer contract audit.

This script audits the D06 JSON contracts against the D03 reference cards,
scope audit, and normalized trajectory HDF5 files.  It never launches a
solver, touches a GPU, writes an artifact, or interprets native particle
identity as material identity.  The report is printed to stdout so a caller
can redirect it outside the DS-DATA-01 write scope if desired.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
LABEL_SCHEMA_PATH = CAMPAIGN_ROOT / "D06_LABEL_SCHEMA.json"
TRACER_SPEC_PATH = CAMPAIGN_ROOT / "D06_TRACER_SUBSET_SPEC.json"
D03_AUDIT_PATH = CAMPAIGN_ROOT / "D03_SCOPE_AUDIT.json"
D03_REFERENCE_PATH = CAMPAIGN_ROOT / "D03_REFERENCE_CARDS.json"

REQUIRED_NATIVE_FIELDS = {
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
SCALAR_FIELDS = {"density", "mass", "pressure", "type", "mk"}
VECTOR_FIELDS = {"position", "velocity"}
LIFECYCLE_BY_FAILURE = {
    "OPEN_LIFECYCLE_FLUX_AUDIT_REQUIRED": "open",
    "VARIABLE_RESOLUTION_LINEAGE_AUDIT_REQUIRED": "variable_resolution",
    "2D_CALIBRATION_ONLY": "calibration_2d",
    "MISSING_MASS_SCOPE_AUDIT_REQUIRED": "unknown",
    "CLOSED_IDENTITY_OR_MASS_INVARIANT_NOT_MET": "unknown",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def relative_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else LAB_ROOT / path


def check_contracts(label_schema: dict[str, Any], tracer_spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    native = label_schema.get("native_sph_fields", {})
    missing_contract_fields = sorted(REQUIRED_NATIVE_FIELDS - set(native))
    if missing_contract_fields:
        errors.append(f"label schema omits native fields: {missing_contract_fields}")
    for field in sorted(REQUIRED_NATIVE_FIELDS):
        if field in native and native[field].get("required") is not True:
            errors.append(f"native field is not required in contract: {field}")
    core = label_schema.get("core_production_boundary", {})
    if core.get("material_tracer_required") is not False:
        errors.append("label schema must keep material_tracer_required=false")
    if core.get("material_tracer_failure_blocks_core") is not False:
        errors.append("label schema must keep tracer failure non-blocking")
    tracer_core = tracer_spec.get("core_gate", {})
    for key in ("required_for_core_dataset", "absence_is_core_failure", "failure_or_unknown_blocks_native_trajectory"):
        if tracer_core.get(key) is not False:
            errors.append(f"tracer spec must keep {key}=false")
    if tracer_spec.get("status") != "optional_diagnostic_only":
        errors.append("tracer spec status is not optional_diagnostic_only")
    if tracer_spec.get("tracer_audit_outputs", {}).get("core_gate_impact") != "always diagnostic_only; never changes native production eligibility":
        errors.append("tracer audit must declare diagnostic-only core impact")
    return errors


def infer_lifecycle(case: dict[str, Any]) -> tuple[str, list[str]]:
    failures = set(case.get("failure_codes", []))
    for code, lifecycle in LIFECYCLE_BY_FAILURE.items():
        if code in failures:
            return lifecycle, sorted(failures)
    if case.get("scope_decision") == "calibration_only":
        return "calibration_2d", sorted(failures)
    if case.get("scope_decision") in {
        "diagnostic_missing_mass",
        "candidate_requires_repair_or_reclassification",
        "reject_numerical_integrity",
        "exclude_from_core",
    }:
        return "unknown", sorted(failures)
    return "closed", sorted(failures)


def audit_hdf5(case: dict[str, Any], lifecycle: str) -> dict[str, Any]:
    quality = case.get("quality", {})
    relative_hdf5 = quality.get("hdf5")
    if not isinstance(relative_hdf5, str):
        return {"status": "fail", "errors": ["D03 case has no HDF5 path"]}
    path = relative_path(relative_hdf5)
    if not path.is_file():
        return {"status": "fail", "hdf5": relative_hdf5, "errors": ["HDF5 file is missing"]}

    errors: list[str] = []
    warnings: list[str] = []
    with h5py.File(path, "r") as h5:
        keys = set(h5.keys())
        missing = sorted(REQUIRED_NATIVE_FIELDS - keys)
        if missing:
            return {
                "status": "fail",
                "hdf5": relative_hdf5,
                "errors": [f"missing native datasets: {missing}"],
            }

        time = np.asarray(h5["time"][:])
        particle_id = np.asarray(h5["particle_id"][:])
        particle_zone = np.asarray(h5["particle_zone"][:])
        valid = np.asarray(h5["valid"][:], dtype=bool)
        if time.ndim != 1:
            errors.append(f"time shape is {time.shape}, expected [T]")
        if particle_id.ndim != 1 or particle_zone.ndim != 1:
            errors.append("particle_id and particle_zone must be one-dimensional")
        if particle_id.ndim == 1 and particle_zone.ndim == 1 and len(particle_id) != len(particle_zone):
            errors.append("particle_id and particle_zone lengths differ")
        if valid.ndim != 2:
            errors.append(f"valid shape is {valid.shape}, expected [T,N]")
        if time.ndim == 1 and valid.ndim == 2 and len(time) != valid.shape[0]:
            errors.append("time frame count differs from valid frame count")
        if valid.ndim == 2 and particle_id.ndim == 1 and len(particle_id) != valid.shape[1]:
            errors.append("particle axis differs between valid and particle_id")
        if len(time) < 2 or not np.isfinite(time).all() or not np.all(np.diff(time) > 0):
            errors.append("time is not finite and strictly increasing with at least two frames")

        if particle_id.ndim == 1 and particle_zone.ndim == 1:
            compound = np.column_stack((particle_zone.astype(np.int64), particle_id.astype(np.int64)))
            if len(np.unique(compound, axis=0)) != len(compound):
                errors.append("compound (particle_zone, particle_id) key is not unique")

        active_counts: list[int] = []
        finite_active: dict[str, bool] = {}
        positive_active: dict[str, bool] = {}
        if valid.ndim == 2:
            for field in sorted(SCALAR_FIELDS | VECTOR_FIELDS):
                values = np.asarray(h5[field][:])
                expected = (valid.shape[0], valid.shape[1], 3) if field in VECTOR_FIELDS else valid.shape
                if values.shape != expected:
                    errors.append(f"{field} shape is {values.shape}, expected {expected}")
                    continue
                active_values = values[valid] if field in SCALAR_FIELDS else values[valid, :]
                finite_active[field] = bool(np.isfinite(active_values).all())
                if not finite_active[field]:
                    errors.append(f"{field} has non-finite values on valid rows")
                if field in {"mass", "density"}:
                    positive_active[field] = bool(np.all(active_values > 0))
                    if not positive_active[field]:
                        errors.append(f"{field} is not positive on all valid rows")
            active_counts = valid.sum(axis=1).astype(int).tolist()

        if lifecycle == "open":
            warnings.append("closed mass/identity invariant intentionally not applied to open lifecycle")
        elif lifecycle == "variable_resolution":
            warnings.append("compound numerical identity and zone-aware diagnostics required; material lineage not inferred")
        elif lifecycle == "calibration_2d":
            warnings.append("2D calibration role is retained; no 3D production gate applied")
        elif lifecycle == "unknown":
            warnings.append("lifecycle is unresolved or excluded; closed mass/identity invariant intentionally not applied")
        else:
            initial = set(zip(particle_zone[valid[0]].astype(int), particle_id[valid[0]].astype(int)))
            final = set(zip(particle_zone[valid[-1]].astype(int), particle_id[valid[-1]].astype(int)))
            ever = set(zip(particle_zone[valid.any(axis=0)].astype(int), particle_id[valid.any(axis=0)].astype(int)))
            active_mass = np.where(valid, h5["mass"][:], 0.0).sum(axis=1, dtype=np.float64)
            initial_mass = float(active_mass[0]) if len(active_mass) else 0.0
            relative_mass = active_mass / initial_mass - 1.0 if initial_mass > 0 else np.array([np.nan])
            if len(ever - initial) or len(initial - final):
                warnings.append("closed candidate has numerical identity birth/death; D03 scope result remains authoritative")
            if not np.isfinite(relative_mass).all():
                errors.append("closed candidate has non-finite active-mass relative diagnostic")

        declared_dimension = case.get("quality", {}).get("dimension")
        if declared_dimension == "2D" or case.get("scope_decision") == "calibration_only":
            warnings.append("2D/calibration boundary is metadata-led, not inferred from stored z coordinates")

    return {
        "status": "pass" if not errors else "fail",
        "hdf5": relative_hdf5,
        "native_keys": sorted(keys),
        "active_count_by_frame": active_counts,
        "finite_active": finite_active,
        "positive_active": positive_active,
        "lifecycle_boundary": lifecycle,
        "closed_gate_applied": lifecycle == "closed",
        "material_tracer_required": False,
        "material_identity_inferred": False,
        "warnings": warnings,
        "errors": errors,
    }


def audit_cases(case_filter: set[str] | None) -> dict[str, Any]:
    label_schema = load_json(LABEL_SCHEMA_PATH)
    tracer_spec = load_json(TRACER_SPEC_PATH)
    d03_audit = load_json(D03_AUDIT_PATH)
    d03_reference = load_json(D03_REFERENCE_PATH)
    contract_errors = check_contracts(label_schema, tracer_spec)
    audit_cases_by_id = {case["case_id"]: case for case in d03_audit.get("cases", [])}
    reference_ids = {card.get("case_id") for card in d03_reference.get("cards", [])}
    selected = sorted(audit_cases_by_id if case_filter is None else case_filter)
    results: list[dict[str, Any]] = []
    for case_id in selected:
        case = audit_cases_by_id.get(case_id)
        if case is None:
            results.append({"case_id": case_id, "status": "fail", "errors": ["case_id not present in D03 scope audit"]})
            continue
        lifecycle, failure_codes = infer_lifecycle(case)
        result = audit_hdf5(case, lifecycle)
        result.update({
            "case_id": case_id,
            "family": case.get("family"),
            "scope_decision": case.get("scope_decision"),
            "failure_codes": failure_codes,
            "d03_reference_card_present": case_id in reference_ids,
            "material_tracer_required": False,
        })
        if case_id not in reference_ids:
            result.setdefault("errors", []).append("D03 reference card is missing")
            result["status"] = "fail"
        results.append(result)

    case_failures = sum(item.get("status") != "pass" for item in results)
    status = "pass" if not contract_errors and case_failures == 0 else "fail"
    return {
        "schema": "ds-data-01.d06.audit-report.v1",
        "status": status,
        "read_only": True,
        "solver_started": False,
        "gpu_requested": False,
        "training_or_inference_started": False,
        "contracts_checked": {
            "label_schema": str(LABEL_SCHEMA_PATH.relative_to(LAB_ROOT)),
            "tracer_spec": str(TRACER_SPEC_PATH.relative_to(LAB_ROOT)),
            "contract_errors": contract_errors,
        },
        "d03_inputs": {
            "scope_audit": str(D03_AUDIT_PATH.relative_to(LAB_ROOT)),
            "reference_cards": str(D03_REFERENCE_PATH.relative_to(LAB_ROOT)),
            "case_count": len(audit_cases_by_id),
        },
        "summary": {
            "selected_cases": len(results),
            "passed_cases": sum(item.get("status") == "pass" for item in results),
            "failed_cases": case_failures,
            "material_tracer_required_for_core": False,
            "material_tracer_failures_block_core": False,
        },
        "cases": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="audit one or more D03 case IDs; omit to audit every D03 case",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_cases(set(args.case_ids) if args.case_ids else None)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
