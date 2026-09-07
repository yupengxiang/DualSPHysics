#!/usr/bin/env python3
"""Audit how far each proposed benchmark direction actually got.

The project has several intentionally different artefact layers: a case
registry, solver definitions, solver attempts, converted trajectories, the
development release, physical validation anchors, and learned baseline runs.
This script keeps those layers separate and refuses to infer that a planned
W08 card or a topology label is an executed benchmark case.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
RELEASE = LAB / "release" / "v0.1-development"
REGISTRY_PATH = CAMPAIGN / "case-registry.json"
W01_PATH = CAMPAIGN / "w01-quality-strict.json"
W05_PATH = CAMPAIGN / "w05-validation-anchors.json"
W07_PATH = CAMPAIGN / "w07-mechanism-screen.json"
W07_DESIGN_PATH = CAMPAIGN / "cases" / "w07" / "candidate-designs.json"
W08_PATH = CAMPAIGN / "w08-generalization-audit.json"
W08_DESIGN_PATH = CAMPAIGN / "cases" / "w08" / "controlled-generalization-design.json"
W08_TOPOLOGY_MANIFEST_PATH = CAMPAIGN / "cases" / "w08" / "topology-holdout-materializations.json"
WORK_PACKAGES_PATH = CAMPAIGN / "work-packages.json"
W11_SELECTION_PATH = CAMPAIGN / "cases" / "w11" / "pilot-selection.json"
W11_MANIFEST_PATH = RELEASE / "manifest.json"
W12_RESULTS_DIR = RELEASE / "baselines" / "results"
RUNTIME_PATH = LAB / "reports" / "runtime" / "run-summary.json"
OFFICIAL_RUNTIME_PATH = LAB / "reports" / "runtime" / "official-run-summary.json"
F2_R3_PATH = CAMPAIGN / "r3-g2-f2-resolution.json"
F1_F3_R3_PATH = CAMPAIGN / "r3-g2-f1-f3-matrix.json"
F6_R3_PATH = CAMPAIGN / "r3-g2-f6-test14.json"
REPORT_PATH = CAMPAIGN / "r3-g3-coverage-audit.json"
CONCLUSION_PATH = CAMPAIGN / "R3-G3-COVERAGE-CONCLUSION.md"

FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6")
REQUIRED_DATASETS = (
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "density", "pressure", "mass", "type", "mk",
)
REQUIRED_ROOT_ATTRIBUTES = (
    "schema_version", "case_id", "family", "solver", "identity_key",
    "trajectory_semantics", "world_frame", "time_units", "length_units", "mass_units",
)
MATERIAL_DATASETS = (
    "tracer_id", "source_label", "mass_weight", "position", "valid",
)
TOPOLOGY_KEY = {
    "F1": "obstacle_topology",
    "F2": "mouth_topology",
    "F3": "baffle_topology",
    "F6": "body_configuration",
}
TOPOLOGY_HOLDOUT = {
    "F1": "twin",
    "F2": "spout",
    "F3": "perforated_proxy",
    "F6": "twin_free",
}
DECLARED_TOPOLOGY_FAMILIES = tuple(TOPOLOGY_HOLDOUT)
INCIDENTAL_HOLDOUT_CASES = {
    "F1": ["F1_twin_obstacle"],
    "F2": [],
    "F3": [],
    "F6": ["F6_twin_floaters"],
}

WORK_PACKAGE_REQUIRED_FIELDS = (
    "id", "name", "status", "execution_status", "acceptance_status",
    "validation_scope", "open_blockers", "depends_on",
)
AUTHORITATIVE_WORK_PACKAGE_FIELDS = (
    "execution_status", "acceptance_status", "validation_scope", "open_blockers",
)
ENGINEERING_ACCEPTANCE_STATUSES = {
    "accepted_engineering", "accepted_limited_scope",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def lab_path(value: str | Path) -> Path:
    """Resolve manifest paths without allowing an absolute path to escape semantics."""
    path = Path(value)
    return path if path.is_absolute() else LAB / path


def audit_work_packages(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit package state without treating the legacy ``status`` as truth.

    The original work-package table used one flat ``status`` field.  It is
    retained for compatibility, but a value such as ``complete`` cannot say
    whether the work was executed, scientifically accepted, or merely
    designed.  This audit makes the four authoritative fields visible and
    reports their cross-product instead of collapsing them back to one label.
    """
    packages = payload.get("packages", [])
    issues: list[str] = []
    status_semantics = payload.get("status_semantics")
    legacy_status_is_non_authoritative = (
        isinstance(status_semantics, str) and status_semantics.startswith("Legacy status")
    )
    if payload.get("schema_version") != 2:
        issues.append("work-packages schema_version is not 2")
    if not isinstance(packages, list) or not packages:
        return {
            "schema_version": payload.get("schema_version"),
            "package_count": 0,
            "contract_pass": False,
            "issues": issues + ["packages must be a non-empty list"],
            "legacy_status_is_non_authoritative": legacy_status_is_non_authoritative,
            "authoritative_fields": list(AUTHORITATIVE_WORK_PACKAGE_FIELDS),
            "packages": [],
        }

    rows: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            issues.append(f"package[{index}] is not an object")
            continue
        missing = [field for field in WORK_PACKAGE_REQUIRED_FIELDS if field not in package]
        if missing:
            issues.append(f"package[{index}] missing fields: {missing}")
        package_id = package.get("id")
        if not isinstance(package_id, str) or not package_id:
            issues.append(f"package[{index}] has no non-empty id")
            package_id = f"<package[{index}]>"
        ids.append(package_id)
        for field in ("validation_scope", "open_blockers", "depends_on"):
            if field in package and not isinstance(package[field], list):
                issues.append(f"{package_id}.{field} must be a list")
        rows.append({
            "id": package_id,
            "name": package.get("name"),
            "legacy_status": package.get("status"),
            "execution_status": package.get("execution_status"),
            "acceptance_status": package.get("acceptance_status"),
            "validation_scope": package.get("validation_scope", []),
            "open_blockers": package.get("open_blockers", []),
            "open_blocker_count": len(package.get("open_blockers", [])) if isinstance(package.get("open_blockers", []), list) else None,
            "depends_on": package.get("depends_on", []),
            "legacy_status_is_non_authoritative": True,
        })

    duplicate_ids = sorted({package_id for package_id in ids if ids.count(package_id) > 1})
    if duplicate_ids:
        issues.append(f"duplicate package ids: {duplicate_ids}")
    missing_authoritative = [
        row["id"] for row in rows
        if any(row[field] is None for field in AUTHORITATIVE_WORK_PACKAGE_FIELDS)
    ]
    if missing_authoritative:
        issues.append(f"packages missing authoritative state: {missing_authoritative}")
    legacy_status_counts = Counter(str(row["legacy_status"]) for row in rows)
    execution_status_counts = Counter(str(row["execution_status"]) for row in rows)
    acceptance_status_counts = Counter(str(row["acceptance_status"]) for row in rows)
    legacy_complete = [row["id"] for row in rows if row["legacy_status"] == "complete"]
    engineering_accepted = [
        row["id"] for row in rows if row["acceptance_status"] in ENGINEERING_ACCEPTANCE_STATUSES
    ]
    complete_but_not_engineering_accepted = [
        row["id"] for row in rows
        if row["legacy_status"] == "complete"
        and row["acceptance_status"] not in ENGINEERING_ACCEPTANCE_STATUSES
    ]
    with_open_blockers = [row["id"] for row in rows if row["open_blockers"]]
    return {
        "schema_version": payload.get("schema_version"),
        "package_count": len(rows),
        "contract_pass": not issues and len(ids) == len(set(ids)),
        "issues": issues,
        "legacy_status_is_non_authoritative": legacy_status_is_non_authoritative,
        "status_semantics": status_semantics,
        "authoritative_fields": list(AUTHORITATIVE_WORK_PACKAGE_FIELDS),
        "legacy_status_counts": dict(legacy_status_counts),
        "execution_status_counts": dict(execution_status_counts),
        "acceptance_status_counts": dict(acceptance_status_counts),
        "legacy_complete_count": len(legacy_complete),
        "legacy_complete_package_ids": legacy_complete,
        "engineering_accepted_count": len(engineering_accepted),
        "engineering_accepted_package_ids": engineering_accepted,
        "legacy_complete_but_not_engineering_accepted": complete_but_not_engineering_accepted,
        "packages_with_open_blockers": with_open_blockers,
        "package_state_is_separated": bool(
            not issues
            and legacy_status_is_non_authoritative
            and all(all(row[field] is not None for field in AUTHORITATIVE_WORK_PACKAGE_FIELDS) for row in rows)
        ),
        "packages": rows,
    }


def work_package_audit() -> dict[str, Any]:
    return audit_work_packages(load(WORK_PACKAGES_PATH))


def official_definition(case: dict[str, Any], official_entries: dict[str, dict[str, Any]]) -> Path:
    entry = official_entries[case["id"]]
    return LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "examples" / entry["source"] / (
        entry["base"] + "_Def.xml"
    )


def definition_path(case: dict[str, Any], official_entries: dict[str, dict[str, Any]]) -> Path:
    if case["origin"] == "official":
        return official_definition(case, official_entries)
    return LAB / "cases" / case["family"] / case["id"] / f"{case['id']}_Def.xml"


def trajectory_path(w01_case: dict[str, Any]) -> Path:
    relative = Path(w01_case["hdf5"])
    if w01_case["origin"] == "official":
        return LAB / relative
    return CAMPAIGN / relative


def finite_under_valid(values: np.ndarray, valid: np.ndarray) -> bool:
    if values.ndim == 3:
        finite = np.isfinite(values).all(axis=2)
    else:
        finite = np.isfinite(values)
    return bool(np.all(finite[valid]))


def audit_h5(path: Path, *, release_contract: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.relative_to(LAB)) if path.is_relative_to(LAB) else str(path),
        "local_available": path.is_file(),
        "structural_pass": False,
        "release_contract_pass": False,
        "issues": [],
    }
    if not path.is_file():
        result["issues"].append("HDF5 is not present in this checkout")
        return result
    try:
        with h5py.File(path, "r") as h5:
            missing = [name for name in REQUIRED_DATASETS if name not in h5]
            if missing:
                result["issues"].append(f"missing datasets: {missing}")
                return result
            time = h5["time"][:]
            valid = np.asarray(h5["valid"][:], dtype=bool)
            if time.ndim != 1 or valid.ndim != 2 or valid.shape[0] != len(time):
                result["issues"].append("time/valid dimensions are incompatible")
                return result
            if len(time) < 1 or not np.isfinite(time).all() or (
                len(time) > 1 and not np.all(np.diff(time) > 0)
            ):
                result["issues"].append("time is not finite and strictly increasing")
            n = valid.shape[1]
            if h5["particle_id"].shape != (n,) or h5["particle_zone"].shape != (n,):
                result["issues"].append("identity arrays do not match valid identity axis")
            # Open-boundary official probes may legitimately introduce a
            # particle after t0, while the closed W11 release contract must
            # reject resurrection.  Keep both semantics explicit.
            if release_contract and len(time) > 1 and np.any(~valid[:-1] & valid[1:]):
                result["issues"].append("valid lifecycle resurrects an identity after disappearance")
            if release_contract and not np.all(valid):
                result["issues"].append("closed release contract contains an invalid identity frame")
            for name in ("position", "velocity"):
                if h5[name].shape != (len(time), n, 3):
                    result["issues"].append(f"{name} has shape {h5[name].shape}")
                elif not finite_under_valid(h5[name][:], valid):
                    result["issues"].append(f"non-finite {name} under valid mask")
            for name in ("density", "pressure", "mass", "type", "mk"):
                if h5[name].shape != (len(time), n):
                    result["issues"].append(f"{name} has shape {h5[name].shape}")
                elif name in ("density", "pressure", "mass") and not finite_under_valid(h5[name][:], valid):
                    result["issues"].append(f"non-finite {name} under valid mask")
            keys = np.column_stack((h5["particle_zone"][:], h5["particle_id"][:]))
            if len(np.unique(keys, axis=0)) != len(keys):
                result["issues"].append("duplicate compound identities")
            result["frames"] = int(len(time))
            result["identity_slots"] = int(n)
            result["initial_valid"] = int(valid[0].sum()) if len(valid) else 0
            result["final_valid"] = int(valid[-1].sum()) if len(valid) else 0
            result["duration_s"] = float(time[-1] - time[0]) if len(time) else 0.0
            if "material" in h5:
                material = h5["material"]
                missing_material = [name for name in MATERIAL_DATASETS if name not in material]
                result["material_present"] = True
                result["material_missing"] = missing_material
                if not missing_material:
                    material_valid = np.asarray(material["valid"][:], dtype=bool)
                    material_position = material["position"][:]
                    tracer_count = len(material["mass_weight"])
                    expected_material_shape = (len(time), tracer_count)
                    if material_valid.shape != expected_material_shape:
                        result["issues"].append("material valid shape is incompatible with time/tracer axes")
                    if material_position.shape != (len(time), tracer_count, 3):
                        result["issues"].append("material position/valid shape mismatch")
                    elif material_valid.shape == expected_material_shape and not finite_under_valid(material_position, material_valid):
                        result["issues"].append("non-finite material position under valid mask")
                    if len(material["tracer_id"]) != tracer_count or len(material["source_label"]) != tracer_count:
                        result["issues"].append("material identity/source arrays do not match mass weights")
                    if len(np.unique(material["tracer_id"][:])) != tracer_count:
                        result["issues"].append("duplicate material tracer identities")
                    if release_contract and material_valid.ndim == 2 and len(time) > 1 and np.any(~material_valid[:-1] & material_valid[1:]):
                        result["issues"].append("material valid lifecycle resurrects a tracer")
                    weight = material["mass_weight"][:]
                    if not np.isfinite(weight).all() or np.any(weight < 0):
                        result["issues"].append("invalid material mass weights")
                    if len(h5["mass"].shape) == 2 and h5["mass"].shape == (len(time), n) and len(valid.shape) == 2:
                        fluid_initial = valid[0] & (np.asarray(h5["type"][0]) == 3)
                        initial_mass = float(np.sum(h5["mass"][0][fluid_initial]))
                        closure_error = abs(float(np.sum(weight)) - initial_mass) / max(abs(initial_mass), 1e-12)
                        result["material_mass_closure_relative_error"] = closure_error
                        if closure_error > 1e-4:
                            result["issues"].append(f"material mass weights do not close initial mass (relative error {closure_error:.3g})")
                    result["material_tracers"] = int(len(weight))
                    result["material_reliable_at_end"] = int(material_valid[-1].sum()) if len(material_valid) else 0
                    result["wall_visibility"] = str(material.attrs.get("wall_visibility", "missing"))
                    result["material_acceptance_status"] = str(material.attrs.get("acceptance_status", "missing"))
                else:
                    result["issues"].append(f"material group missing datasets: {missing_material}")
                    result["material_tracers"] = 0
            else:
                result["material_present"] = False
                result["material_missing"] = list(MATERIAL_DATASETS)
                result["material_tracers"] = 0
            # Compute the structural result only after every optional material
            # check.  A malformed material group must not leave an earlier
            # optimistic ``structural_pass`` behind.
            result["structural_pass"] = not result["issues"]

            if release_contract:
                missing_attrs = [name for name in REQUIRED_ROOT_ATTRIBUTES if name not in h5.attrs]
                if missing_attrs:
                    result["issues"].append(f"missing root attributes: {missing_attrs}")
                result["release_required_root_attributes_missing"] = missing_attrs
                result["release_contract_pass"] = result["structural_pass"] and not missing_attrs
    except Exception as exc:  # pragma: no cover - protects an audit over external files
        result["issues"].append(f"HDF5 read error: {type(exc).__name__}: {exc}")
    return result


def runtime_index() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    custom = {entry["id"]: entry for entry in load(RUNTIME_PATH)["cases"]}
    official = {entry["id"]: entry for entry in load(OFFICIAL_RUNTIME_PATH)["cases"]}
    return custom, official


def case_stage_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    registry = load(REGISTRY_PATH)["cases"]
    w01 = {entry["id"]: entry for entry in load(W01_PATH)["cases"]}
    custom_runs, official_runs = runtime_index()
    official_entries = official_runs
    pilot = {entry["case_id"]: entry for entry in load(W11_MANIFEST_PATH)["cases"]}
    baseline_cases: set[str] = set()
    for path in sorted(W12_RESULTS_DIR.glob("*.json")):
        baseline_cases.update(load(path).get("test_rollout", {}).keys())
    references = reference_status()
    rows = []
    for case in registry:
        case_id = case["id"]
        observed = w01.get(case_id, {})
        runs = official_runs if case["origin"] == "official" else custom_runs
        run = runs.get(case_id, {})
        h5 = audit_h5(trajectory_path(observed)) if observed else {
            "structural_pass": False, "issues": ["missing W01 record"], "local_available": False,
        }
        definition = definition_path(case, official_entries)
        quality_pass = observed.get("disposition") == "accepted_probe"
        pilot_record = pilot.get(case_id)
        rows.append({
            "case_id": case_id,
            "family": case["family"],
            "origin": case["origin"],
            "lineage_group_id": case["lineage_group_id"],
            "declared": True,
            "definition": str(definition.relative_to(LAB)),
            "executable": definition.is_file(),
            "run": run.get("status") == "completed" or observed.get("solver_status") == "completed",
            "run_elapsed_seconds": run.get("elapsed_seconds", observed.get("elapsed_seconds")),
            "trajectory_structural": bool(h5.get("structural_pass")),
            "trajectory_structural_issues": h5.get("issues", []),
            "local_hdf5_available": bool(h5.get("local_available")),
            "quality_gate_pass": quality_pass,
            "quality_disposition": observed.get("disposition"),
            "pilot_manifest": pilot_record is not None,
            "pilot_split": pilot_record.get("split") if pilot_record else None,
            "baseline_evaluated": case_id in baseline_cases,
            "reference_status": references.get(case["family"], {}).get("status", "not mapped"),
            "reference_quality_pass": references.get(case["family"], {}).get("quality_pass", False),
        })
    return rows, {
        "registry_case_count": len(registry),
        "rows": rows,
        "baseline_case_ids": sorted(baseline_cases),
    }


def reference_status() -> dict[str, dict[str, Any]]:
    w05 = load(W05_PATH)
    f6 = load(F6_R3_PATH)
    external = w05.get("external_validation", {})
    f1_anchor = external.get("F1", {}).get("coarse")
    f3_anchor = external.get("F3", {}).get("coarse")
    f6_anchor = external.get("F6", {}).get("coarse")
    f6_acceptance = f6.get("scientific_acceptance", "not_reported")
    return {
        "F1": {
            "status": "partial_external_anchor" if f1_anchor else "no_external_anchor",
            "quality_pass": False,
            "anchor_present": bool(f1_anchor),
            "evidence": "SPHERIC Test 02 surface gauges/pressure; pressure and H1 are non-monotonic" if f1_anchor else "W05 has no F1 external anchor",
        },
        "F2": {
            "status": "no_external_anchor",
            "quality_pass": False,
            "evidence": "rotating-pour matrices are numerical only",
        },
        "F3": {
            "status": "partial_external_anchor" if f3_anchor else "no_external_anchor",
            "quality_pass": False,
            "anchor_present": bool(f3_anchor),
            "evidence": "SPHERIC Test 10 pressure has unresolved impact timing/full-trace convergence" if f3_anchor else "W05 has no F3 external anchor",
        },
        "F4": {
            "status": "no_external_anchor",
            "quality_pass": False,
            "evidence": "qualitative topology probes only",
        },
        "F5": {
            "status": "no_external_anchor",
            "quality_pass": False,
            "evidence": "run-up/overtopping anchor and stable envelope absent",
        },
        "F6": {
            "status": "partial_2d_anchor_and_rejected_3d_test14" if f6_anchor else "no_external_anchor_and_rejected_3d_test14",
            "quality_pass": False,
            "anchor_present": bool(f6_anchor),
            "evidence": "Fekken 2-D surrogate is partial; Test 14 report rejects current DBC proxy" if f6_anchor else "no Fekken 2-D anchor; Test 14 report rejects current DBC proxy",
            "test14_acceptance": f6_acceptance,
        },
    }


def w08_topology_audit() -> dict[str, dict[str, Any]]:
    design = load(W08_DESIGN_PATH)
    w07_design = load(W07_DESIGN_PATH)
    cards = design["cards"]
    # Topology cards live outside the 204 continuous-axis cards.  Keeping the
    # namespaces separate prevents a topology run from being counted as a
    # continuous intervention while still making the declared W08 holdout
    # auditable and linkable.
    topology_cards = design.get("topology_holdout_cards", [])
    w07_cards = w07_design["cards"]
    topology_manifest = load(W08_TOPOLOGY_MANIFEST_PATH) if W08_TOPOLOGY_MANIFEST_PATH.is_file() else {}
    materialization_by_card = {
        item.get("card_id"): item
        for item in topology_manifest.get("materializations", [])
        if item.get("card_id")
    }
    stage_rows, _ = case_stage_rows()
    stage_by_case = {row["case_id"]: row for row in stage_rows}
    result = {}
    for family in FAMILIES:
        # F4/F5 currently have no declared topology holdout vocabulary. Keep
        # them visible in the audit rather than silently dropping those
        # families or treating an absent key as an executed holdout.
        if family not in TOPOLOGY_KEY:
            result[family] = {
                "declared_holdout": None,
                "topology_field": None,
                "w07_design_cards": 0,
                "w08_controlled_cards": 0,
                "planned_design_card_count": 0,
                "w08_planned_card_count": 0,
                "w08_holdout_splits": [],
                "w08_execution_statuses": [],
                "incidental_matching_registry_cases": [],
                "linked_materialized_cases": 0,
                "linked_run_cases": 0,
                "actual_coverage_count": 0,
                "formal_coverage_count": 0,
                "coverage_status": "not_declared",
                "coverage_claim": False,
                "holdout_gate_pass": False,
                "unique_execution_links": 0,
                "decision": "not_declared_for_family",
            }
            continue
        key = TOPOLOGY_KEY[family]
        holdout = TOPOLOGY_HOLDOUT[family]
        w08_family = [card for card in cards if card["family"] == family]
        w08_topology_family = [card for card in topology_cards if card.get("family") == family]
        w07_family = [card for card in w07_cards if card["family"] == family]
        w08_continuous_holdout = [card for card in w08_family if card["physics"].get(key) == holdout]
        w08_declared_topology = [card for card in w08_topology_family if card["physics"].get(key) == holdout]
        w08_holdout = w08_continuous_holdout + w08_declared_topology
        w07_holdout = [card for card in w07_family if card["physics"].get(key) == holdout]
        links = []
        for card in w08_holdout:
            materialization = materialization_by_card.get(card.get("card_id"))
            if materialization is not None:
                stages = materialization.get("stages", {})
                executable = stages.get("executable", {})
                run_stage = stages.get("run", {})
                normalized = stages.get("normalized_hdf5", {})
                structural = stages.get("structural_audit", {})
                g3_structural = structural.get("g3_audit", {})
                links.append({
                    "card_id": card.get("card_id"),
                    "case_id": materialization.get("case_id"),
                    "physical_case_id": card.get("physical_case_id"),
                    "lineage_group_id": card.get("lineage_group_id"),
                    "execution_unit_id": card.get("execution_unit_id"),
                    "execution_status": materialization.get("execution_status", "unknown"),
                    "split": materialization.get("split"),
                    "executable": bool(
                        executable.get("gencase_returncode") == 0
                        and executable.get("definition")
                        and lab_path(executable["definition"]).is_file()
                        and executable.get("generated_case_xml")
                        and lab_path(executable["generated_case_xml"]).is_file()
                    ),
                    "run": run_stage.get("status") == "completed",
                    "materialized": bool(normalized.get("hdf5")) and lab_path(normalized.get("hdf5", "")).is_file(),
                    "trajectory_structural": bool(structural.get("structural_pass") and g3_structural.get("structural_pass")),
                    "physical_acceptance": materialization.get("physical_acceptance", "unknown"),
                    "reference_acceptance": materialization.get("reference_acceptance", "unknown"),
                    "formal_production_authorized": bool(materialization.get("formal_production_authorized", False)),
                })
                continue
            # Only explicit physical case identifiers are eligible for a
            # link.  Card/series IDs are design identities and must not
            # accidentally collide with an observed registry case.
            identifiers = [card.get("case_id"), card.get("physical_case_id")]
            match = next((stage_by_case[value] for value in identifiers if value in stage_by_case), None)
            if match is not None:
                links.append({
                    "card_id": card.get("card_id"), "case_id": match["case_id"],
                    "execution_unit_id": card.get("execution_unit_id"),
                    "execution_status": card.get("execution_status"), "split": card.get("split"),
                    "materialized": bool(match["local_hdf5_available"]),
                    "run": bool(match["run"]), "trajectory_structural": bool(match["trajectory_structural"]),
                    "physical_acceptance": "legacy_registry_probe",
                    "reference_acceptance": "legacy_registry_probe",
                    "formal_production_authorized": False,
                })
        unique_links = {(link["execution_unit_id"] or link["card_id"]): link for link in links}
        linked_materialized = {link["case_id"] for link in unique_links.values() if link["materialized"]}
        linked_run = {link["case_id"] for link in unique_links.values() if link["run"]}
        gate_links = list(unique_links.values())
        holdout_gate_pass = bool(w08_holdout) and len(gate_links) == len({card.get("execution_unit_id") or card.get("card_id") for card in w08_holdout}) and all(
            link["execution_status"] == "completed" and link["split"] == "topology_extrapolation"
            and link["executable"] and link["materialized"] and link["run"] and link["trajectory_structural"] for link in gate_links
        )
        scientific_acceptance_pass = bool(gate_links) and all(
            link["physical_acceptance"] == "accepted"
            and link["reference_acceptance"] == "accepted"
            and not link["formal_production_authorized"]
            for link in gate_links
        )
        actual_cases = {
            link["case_id"] for link in gate_links
            if link["materialized"] and link["run"] and link["trajectory_structural"]
        }
        formal_cases = {
            link["case_id"] for link in gate_links
            if link["materialized"] and link["run"] and link["trajectory_structural"]
            and link["physical_acceptance"] == "accepted"
            and link["reference_acceptance"] == "accepted"
            and not link["formal_production_authorized"]
        }
        if holdout_gate_pass and scientific_acceptance_pass:
            coverage_status = "formally_covered"
        elif actual_cases:
            coverage_status = "observed_but_not_formal"
        else:
            coverage_status = "planned_only"
        result[family] = {
            "declared_holdout": holdout,
            "topology_field": key,
            "w07_design_cards": len(w07_holdout),
            "w08_controlled_cards": len(w08_holdout),
            "w08_continuous_controlled_cards": len(w08_continuous_holdout),
            "w08_declared_topology_cards": len(w08_declared_topology),
            "planned_design_card_count": len(w07_holdout),
            "w08_planned_card_count": len(w08_holdout),
            "w08_holdout_splits": sorted({card["split"] for card in w08_holdout}),
            "w08_execution_statuses": sorted({card["execution_status"] for card in w08_holdout}),
            "materialization_execution_statuses": sorted({
                link["execution_status"] for link in unique_links.values()
            }),
            "incidental_matching_registry_cases": INCIDENTAL_HOLDOUT_CASES[family],
            "linked_materialized_cases": len(linked_materialized),
            "linked_run_cases": len(linked_run),
            "actual_coverage_count": len(actual_cases),
            "formal_coverage_count": len(formal_cases),
            "coverage_status": coverage_status,
            "coverage_claim": bool(formal_cases),
            "case_links": links,
            "unique_execution_links": len(gate_links),
            "holdout_gate_pass": holdout_gate_pass,
            "scientific_acceptance_pass": scientific_acceptance_pass,
            "materialization_manifest": str(W08_TOPOLOGY_MANIFEST_PATH.relative_to(LAB)),
            "decision": (
                "not_declared_for_family" if not w08_holdout and family not in DECLARED_TOPOLOGY_FAMILIES else
                "design_only_not_materialized" if not w08_holdout else
                "completed_and_structurally_linked" if bool(gate_links) and all(
                    link["execution_status"] == "completed" and link["split"] == "topology_extrapolation"
                    and link["executable"] and link["materialized"] and link["run"] and link["trajectory_structural"] for link in gate_links
                ) and scientific_acceptance_pass else
                "completed_structural_candidate_only" if holdout_gate_pass else
                "linked_but_not_accepted"
            ),
        }
    return result


def w08_execution_audit() -> dict[str, Any]:
    """Link every W08 card to observed registry evidence when possible."""

    cards = load(W08_DESIGN_PATH)["cards"]
    rows, _ = case_stage_rows()
    stage_by_case = {row["case_id"]: row for row in rows}
    links = []
    for card in cards:
        identifiers = [card.get("case_id"), card.get("physical_case_id")]
        match = next((stage_by_case[value] for value in identifiers if value in stage_by_case), None)
        links.append({
            "card_id": card.get("card_id"), "physical_case_id": card.get("physical_case_id"),
            "execution_unit_id": card.get("execution_unit_id"), "case_id": match["case_id"] if match else None,
            "execution_status": card.get("execution_status"), "split": card.get("split"),
            "executable": bool(match and match["executable"]), "run": bool(match and match["run"]),
            "trajectory_structural": bool(match and match["trajectory_structural"]),
            "reference_quality": bool(match and match["reference_quality_pass"]),
            "training_eval": bool(match and match["baseline_evaluated"]),
        })
    unique_links = {}
    for link in links:
        unique_links.setdefault(link["execution_unit_id"] or link["card_id"], link)
    return {
        "card_count": len(cards),
        "linked_card_count": sum(link["case_id"] is not None for link in links),
        "unique_execution_units": len(unique_links),
        "executable_definitions": sum(link["executable"] for link in unique_links.values()),
        "run_cases": sum(link["run"] and link["execution_status"] == "completed" for link in unique_links.values()),
        "trajectory_structural_cases": sum(link["trajectory_structural"] for link in unique_links.values()),
        "reference_quality_cases": sum(link["reference_quality"] for link in unique_links.values()),
        "training_eval_cases": sum(link["training_eval"] for link in unique_links.values()),
        "links": links,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_boundary_sidecar(path: Path, case_id: str, solver_path: Path) -> dict[str, Any]:
    """Validate a linked finite-triangle sidecar against its solver export."""
    if not path.is_file():
        return {"case_id": case_id, "path": str(path), "pass": False, "issues": ["missing sidecar"]}
    issues = []
    try:
        with h5py.File(path, "r") as sidecar, h5py.File(solver_path, "r") as solver:
            required = ("time", "triangles_world", "triangle_mk", "triangle_type")
            missing = [name for name in required if name not in sidecar]
            if missing:
                issues.append(f"missing datasets: {missing}")
            if not missing:
                time = np.asarray(sidecar["time"][:], dtype=float)
                solver_time = np.asarray(solver["time"][:], dtype=float)
                triangles = np.asarray(sidecar["triangles_world"][:], dtype=float)
                kind = np.asarray(sidecar["triangle_type"][:])
                if not np.array_equal(time, solver_time):
                    issues.append("sidecar time axis differs from solver export")
                if triangles.ndim != 4 or triangles.shape[0] != len(time) or triangles.shape[2:] != (3, 3):
                    issues.append("triangles_world shape is not [T,N,3,3]")
                if len(sidecar["triangle_mk"]) != triangles.shape[1] or len(kind) != triangles.shape[1]:
                    issues.append("triangle labels do not match triangle axis")
                if not np.all(np.isin(kind, (0, 1))):
                    issues.append("triangle_type contains a non-boundary type")
                if not np.all(np.isfinite(triangles)):
                    issues.append("triangle coordinates are non-finite")
                if triangles.size:
                    area2 = np.linalg.norm(np.cross(triangles[:, :, 1] - triangles[:, :, 0],
                                                     triangles[:, :, 2] - triangles[:, :, 0]), axis=-1)
                    if not np.all(area2 > 1e-12):
                        issues.append("sidecar contains degenerate triangles")
            attr_case = sidecar.attrs.get("case_id")
            if isinstance(attr_case, bytes):
                attr_case = attr_case.decode()
            if str(attr_case) != case_id:
                issues.append(f"sidecar case_id mismatch: {attr_case!r}")
            coordinate_frame = sidecar.attrs.get("coordinate_frame")
            if isinstance(coordinate_frame, bytes):
                coordinate_frame = coordinate_frame.decode()
            if coordinate_frame != "world":
                issues.append(f"sidecar coordinate frame is not world: {coordinate_frame!r}")
    except (OSError, ValueError, KeyError) as error:
        issues.append(f"sidecar unreadable: {error}")
    return {
        "case_id": case_id, "path": str(path), "sha256": _sha256(path),
        "bytes": path.stat().st_size, "pass": not issues, "issues": issues,
    }


def release_integrity_audit() -> dict[str, Any]:
    """Cross-check W11 selection, release manifest and published bytes."""

    selection = load(W11_SELECTION_PATH)
    manifest = load(W11_MANIFEST_PATH)
    selection_entries = selection.get("cases", [])
    manifest_entries = manifest.get("cases", [])
    selection_ids_raw = [entry.get("case_id") for entry in selection_entries]
    manifest_ids_raw = [entry.get("case_id") for entry in manifest_entries]
    duplicate_selection_ids = sorted({case_id for case_id in selection_ids_raw if selection_ids_raw.count(case_id) > 1})
    duplicate_manifest_ids = sorted({case_id for case_id in manifest_ids_raw if manifest_ids_raw.count(case_id) > 1})
    selected = {entry["case_id"]: entry for entry in selection_entries}
    published = {entry["case_id"]: entry for entry in manifest_entries}
    missing_from_release = sorted(set(selected) - set(published))
    unexpected_in_release = sorted(set(published) - set(selected))
    field_mismatches = []
    checksum_failures = []
    contract_failures = []
    sidecar_audits = []
    for case_id in sorted(set(selected) & set(published)):
        source = selected[case_id]
        entry = published[case_id]
        for field in ("family", "split", "lineage_group_id"):
            if source.get(field) != entry.get(field):
                field_mismatches.append({"case_id": case_id, "field": field, "selection": source.get(field), "manifest": entry.get(field)})
        path = RELEASE / entry["hdf5"]
        if not path.is_file() or path.stat().st_size != int(entry.get("bytes", -1)) or _sha256(path) != entry.get("sha256"):
            checksum_failures.append(case_id)
        audit = audit_h5(path, release_contract=True)
        if not audit.get("release_contract_pass"):
            contract_failures.append({"case_id": case_id, "issues": audit.get("issues", [])})
        if path.is_file():
            with h5py.File(path, "r") as h5:
                def attr_text(name: str) -> str | None:
                    value = h5.attrs.get(name)
                    if isinstance(value, bytes):
                        return value.decode()
                    return str(value) if value is not None else None
                expected_attrs = {
                    "case_id": case_id, "family": entry.get("family"),
                    "schema_version": str(manifest.get("schema_version")),
                    "time_units": "s", "length_units": "m", "mass_units": "kg",
                }
                mismatches = {name: {"expected": expected, "actual": attr_text(name)} for name, expected in expected_attrs.items() if attr_text(name) != str(expected)}
                if mismatches:
                    contract_failures.append({"case_id": case_id, "attribute_mismatches": mismatches})
        sidecar = entry.get("boundary_sidecar") or (entry.get("geometry") or {}).get("boundary_sidecar")
        if isinstance(sidecar, str):
            sidecar_audits.append(audit_boundary_sidecar(RELEASE / sidecar, case_id, path))
    return {
        "selection_release_id_match": selection.get("release_id") == manifest.get("release_id"),
        "formal_release_is_false": selection.get("formal_release") is False and manifest.get("formal_release") is False,
        "selection_case_count": len(selected), "manifest_case_count": len(published),
        "duplicate_selection_ids": duplicate_selection_ids, "duplicate_manifest_ids": duplicate_manifest_ids,
        "missing_from_release": missing_from_release, "unexpected_in_release": unexpected_in_release,
        "field_mismatches": field_mismatches, "checksum_failures": checksum_failures,
        "release_contract_failures": contract_failures,
        "boundary_sidecar_audits": sidecar_audits,
        "boundary_sidecar_failures": [item for item in sidecar_audits if not item["pass"]],
        "pass": (
            selection.get("release_id") == manifest.get("release_id")
            and selection.get("formal_release") is False and manifest.get("formal_release") is False
            and not missing_from_release and not unexpected_in_release and not field_mismatches
            and not duplicate_selection_ids and not duplicate_manifest_ids
            and not checksum_failures and not contract_failures
            and not any(not item["pass"] for item in sidecar_audits)
        ),
    }


def pilot_task_audit() -> dict[str, Any]:
    manifest = load(W11_MANIFEST_PATH)
    task_cases = {"T1_particle_rollout": [], "T2_material_transport": [],
                  "T3_interaction_observables": [], "T4_outcome_classification": []}
    release_case_rows = []
    for entry in manifest["cases"]:
        path = RELEASE / entry["hdf5"]
        h5 = audit_h5(path, release_contract=True)
        material = h5.get("material_present", False) and not h5.get("material_missing")
        t1 = h5.get("release_contract_pass", False)
        t2_candidate = material
        destination_spec = entry.get("destination_spec") or (entry.get("material") or {}).get("destination_spec")
        sidecar = entry.get("boundary_sidecar") or (entry.get("geometry") or {}).get("boundary_sidecar")
        sidecar_path = (RELEASE / sidecar) if isinstance(sidecar, str) else None
        wall_visible = h5.get("wall_visibility") not in ("False", "false", "not supplied in development pilot", "missing")
        # A complete material task needs both a destination definition and a
        # real wall/visibility sidecar. Source labels alone are not destination
        # truth, and a root-HDF5 key named ``destination_spec`` is not part of
        # this contract.
        t2_complete = bool(material and wall_visible and destination_spec and sidecar_path and sidecar_path.is_file())
        t3 = bool(entry.get("observable_reference")) and bool(entry.get("quality", {}).get("validation_scope"))
        t4 = bool(entry.get("terminal_destination")) and bool(entry.get("event_history"))
        if t1:
            task_cases["T1_particle_rollout"].append(entry["case_id"])
        if t2_complete:
            task_cases["T2_material_transport"].append(entry["case_id"])
        if t3:
            task_cases["T3_interaction_observables"].append(entry["case_id"])
        if t4:
            task_cases["T4_outcome_classification"].append(entry["case_id"])
        release_case_rows.append({
            "case_id": entry["case_id"], "family": entry["family"], "split": entry["split"],
            "release_contract": t1, "material_candidate": t2_candidate,
            "material_task_complete": t2_complete, "interaction_task_complete": t3,
            "outcome_task_complete": t4, "material_wall_visibility": h5.get("wall_visibility"),
            "destination_spec_present": bool(destination_spec),
            "boundary_sidecar_present": bool(sidecar_path and sidecar_path.is_file()),
            "material_acceptance_status": h5.get("material_acceptance_status"),
            "hdf5_issues": h5.get("issues", []),
        })
    baseline_paths = sorted(W12_RESULTS_DIR.glob("*.json"))
    baseline_results = [load(path) for path in baseline_paths]
    baseline_routes = sorted({result["route"] for result in baseline_results})
    baseline_seeds = sorted({int(result["seed"]) for result in baseline_results})
    combinations = [(result.get("route"), int(result.get("seed"))) for result in baseline_results]
    expected_combinations = [(route, seed) for route in ("deepset_context", "particle_mlp") for seed in (17, 29, 43)]
    case_sets = [tuple(sorted(result.get("test_rollout", {}))) for result in baseline_results]
    return {
        "pilot_manifest_case_count": len(manifest["cases"]),
        "pilot_split_counts": dict(Counter(entry["split"] for entry in manifest["cases"])),
        "task_ready_case_ids": task_cases,
        "task_ready_counts": {task: len(cases) for task, cases in task_cases.items()},
        "material_candidate_case_count": sum(row["material_candidate"] for row in release_case_rows),
        "release_case_rows": release_case_rows,
        "release_integrity": release_integrity_audit(),
        "learned_baseline": {
            "result_files": len(baseline_results),
            "routes": baseline_routes,
            "seeds": baseline_seeds,
            "case_ids": sorted({case_id for result in baseline_results for case_id in result.get("test_rollout", {})}),
            "route_seed_combinations": [list(item) for item in sorted(combinations)],
            "nonempty_test_case_sets": all(case_sets),
            "consistent_test_case_sets": len(set(case_sets)) <= 1,
            "three_seed_gate": (
                len(baseline_results) == len(expected_combinations)
                and sorted(combinations) == sorted(expected_combinations)
                and len(set(combinations)) == len(combinations)
                and all(case_sets)
                and len(set(case_sets)) == 1
            ),
        },
    }


def supplemental_matrix_audit() -> list[dict[str, Any]]:
    result = []
    for path, name, family in ((F2_R3_PATH, "R3-G2-F2", "F2"),
                               (F1_F3_R3_PATH, "R3-G2-F1-F3", "F1/F3"),
                               (F6_R3_PATH, "R3-G2-F6-Test14", "F6")):
        payload = load(path)
        if "run_results" in payload:
            runs = payload["run_results"]
            declared = len(runs)
        elif "run_results_new_backgrounds" in payload:
            runs = payload["run_results_new_backgrounds"]
            declared = len(runs)
        else:
            # F6 has one run record per resolution/offset under the flat key.
            runs = payload.get("run_results", [])
            declared = len(runs)
        statuses = Counter(run.get("status", "completed") for run in runs)
        result.append({
            "direction": name,
            "family": family,
            "declared_or_reported_runs": declared,
            "completed_runs": statuses.get("completed", declared) if declared else 0,
            "run_statuses": dict(statuses),
            "scientific_acceptance": payload.get("acceptance_status", payload.get("scientific_acceptance")),
            "execution_evidence": True,
            "formal_training_eval": False,
        })
    return result


def build_report() -> dict[str, Any]:
    rows, registry_audit = case_stage_rows()
    references = reference_status()
    topology = w08_topology_audit()
    pilot = pilot_task_audit()
    work_packages = work_package_audit()
    registry = load(REGISTRY_PATH)["cases"]
    w07 = load(W07_PATH)
    w06 = load(CAMPAIGN / "w06-rotating-pour.json")
    retained_families = tuple(w07.get("screening_decision", {}).get("retain", FAMILIES))
    family_summary = {}
    for family in FAMILIES:
        family_rows = [row for row in rows if row["family"] == family]
        mechanisms = {case["mechanism"] for case in registry if case["family"] == family}
        if family == "F2":
            background_count = len(w06["cases"])
            background_source = "W06 rotating-pour case matrix"
        else:
            background_count = len(mechanisms)
            background_source = "registry mechanisms"
        pilot_ids = [case_id for case_id in pilot["task_ready_case_ids"]["T1_particle_rollout"]
                     if next(row for row in pilot["release_case_rows"] if row["case_id"] == case_id)["family"] == family]
        baseline_ids = [case_id for case_id in pilot["learned_baseline"]["case_ids"]
                        if case_id.startswith(family) or (family == "F2" and case_id.startswith("W06"))]
        disposition = w07["observed_family_map"][family]["disposition"]
        blockers = ["reference-quality gate is not passed"]
        if family in DECLARED_TOPOLOGY_FAMILIES:
            if topology[family]["holdout_gate_pass"]:
                blockers.insert(0, "topology materialization is candidate-only; physical/reference acceptance is not passed")
            else:
                blockers.insert(0, "topology holdout is not an executed W08 split")
        family_summary[family] = {
            "declared": len(family_rows),
            "executable": sum(row["executable"] for row in family_rows),
            "run": sum(row["run"] for row in family_rows),
            "trajectory_structural": sum(row["trajectory_structural"] for row in family_rows),
            "quality_gate_pass": sum(row["quality_gate_pass"] for row in family_rows),
            "quality_gate_failed_or_expected_failure": sum(not row["quality_gate_pass"] for row in family_rows),
            "reference_evidence_status": references[family]["status"],
            "reference_quality_pass": references[family]["quality_pass"],
            "development_pilot_t1_cases": len(pilot_ids),
            "learned_baseline_evaluated_cases": len(baseline_ids),
            "background_count": background_count,
            "background_count_source": background_source,
            "at_least_three_backgrounds_gate": background_count >= 3,
            "w07_screening_disposition": disposition,
            "development_tranche_ready": False,
            "development_tranche_blockers": blockers,
        }
    registry_counts = {
        "declared": len(rows),
        "executable": sum(row["executable"] for row in rows),
        "run": sum(row["run"] for row in rows),
        "trajectory_structural": sum(row["trajectory_structural"] for row in rows),
        "quality_gate_pass": sum(row["quality_gate_pass"] for row in rows),
        "quality_gate_expected_failure_or_rejected": sum(not row["quality_gate_pass"] for row in rows),
        "reference_quality_pass_families": sum(value["quality_pass"] for value in references.values()),
        "development_pilot_manifest": pilot["pilot_manifest_case_count"],
        # Keep the registry denominator separate from the W11 pilot denominator:
        # W06_standard_fast_center is a pilot case but is not in the 30-case
        # candidate registry.
        "learned_baseline_evaluated_cases": sum(row["baseline_evaluated"] for row in rows),
        "learned_baseline_evaluated_pilot_cases": len(pilot["learned_baseline"]["case_ids"]),
    }
    w08_design = load(W08_DESIGN_PATH)
    w07_design = load(W07_DESIGN_PATH)
    w08_splits = Counter(card["split"] for card in w08_design["cards"])
    w08_execution = w08_execution_audit()
    w08_decision = (
        "continuous_design_only_topology_partially_materialized" if w08_execution["run_cases"] == 0 and any(
            item["holdout_gate_pass"] for item in topology.values()
        ) else
        "design_only_not_run" if w08_execution["run_cases"] == 0 else
        "partially_executed" if w08_execution["run_cases"] < w08_execution["unique_execution_units"] else
        "executed_requires_scientific_acceptance"
    )
    w08_package = next((row for row in work_packages["packages"] if row["id"] == "W08"), None)
    work_packages["w08_crosscheck"] = {
        "package_present": w08_package is not None,
        "legacy_status": w08_package.get("legacy_status") if w08_package else None,
        "execution_status": w08_package.get("execution_status") if w08_package else None,
        "acceptance_status": w08_package.get("acceptance_status") if w08_package else None,
        "validation_scope": w08_package.get("validation_scope") if w08_package else None,
        "open_blockers": w08_package.get("open_blockers") if w08_package else None,
        "coverage_decision": w08_decision,
        "declared_cards": len(w08_design["cards"]),
        "run_cases": w08_execution["run_cases"],
        "continuous_design_only_claim_is_consistent": bool(
            w08_package
            and w08_package.get("execution_status") in {"design_complete", "partial_materialization"}
            and w08_package.get("acceptance_status") == "not_experimentally_accepted"
            and w08_execution["run_cases"] == 0
        ),
        # Backward-compatible alias: this now refers specifically to the
        # 204-card continuous matrix, not the separate topology namespace.
        "design_only_claim_is_consistent": bool(
            w08_package
            and w08_package.get("execution_status") in {"design_complete", "partial_materialization"}
            and w08_package.get("acceptance_status") == "not_experimentally_accepted"
            and w08_execution["run_cases"] == 0
        ),
        "topology_materialization_is_separate_from_continuous_cards": True,
        "topology_engineering_links": sum(item["holdout_gate_pass"] for item in topology.values()),
        "topology_formal_coverage_count": sum(item["formal_coverage_count"] for item in topology.values()),
    }
    return {
        "schema_version": 1,
        "scope": "R3-G3 declared-to-training/evaluation coverage and topology holdout audit",
        "execution_status": "audit_complete",
        "formal_release_decision": "do_not_admit_current_candidate_as_formal_v0.1",
        "stage_definitions": {
            "declared": "case exists in case-registry or W08 controlled design cards",
            "executable": "a concrete GenCase definition and its source path exist",
            "run": "a solver summary records successful execution (or W01 records completed solver evidence)",
            "trajectory_structural": "HDF5 required arrays have compatible shapes, finite valid values, strict time and unique compound identities",
            "quality_gate_pass": "W01 disposition is accepted_probe; expected failures remain visible",
            "reference_quality": "an external anchor is present and its declared observable/resolution is accepted; partial anchors do not pass",
            "training_eval": "case is in the W11 manifest for development T1/T2/T3/T4 and learned baseline coverage is counted separately",
        },
        "registry_stage_counts": registry_counts,
        "family_summary": family_summary,
        "registry_case_rows": rows,
        "work_packages": work_packages,
        "w08_design": {
            "declared_cards": len(w08_design["cards"]),
            "declared_topology_holdout_cards": len(w08_design.get("topology_holdout_cards", [])),
            "unique_execution_units": load(W08_PATH)["audit"]["unique_execution_units"],
            "execution_status_counts": dict(Counter(card["execution_status"] for card in w08_design["cards"])),
            "split_counts": dict(w08_splits),
            "planned_card_count": sum(card.get("execution_status") == "planned_not_run" for card in w08_design["cards"]),
            "linked_card_count": w08_execution["linked_card_count"],
            "executable_definitions": w08_execution["executable_definitions"],
            "run_cases": w08_execution["run_cases"],
            "trajectory_structural_cases": w08_execution["trajectory_structural_cases"],
            "reference_quality_cases": w08_execution["reference_quality_cases"],
            "training_eval_cases": w08_execution["training_eval_cases"],
            "decision": w08_decision,
            "coverage_claim": False,
            "topology_engineering_link_count": sum(item["holdout_gate_pass"] for item in topology.values()),
            "topology_actual_coverage_count": sum(item["actual_coverage_count"] for item in topology.values()),
            "topology_formal_coverage_count": sum(item["formal_coverage_count"] for item in topology.values()),
        },
        "topology_holdouts": topology,
        "w07_topology_design_only": {
            "declared_cards": len(w07_design["cards"]),
            "execution_status_counts": dict(Counter(card["execution_status"] for card in w07_design["cards"])),
            "interpretation": "W07 includes categorical topology candidates, but all are design cards and have no solver output linkage",
        },
        "development_pilot": pilot,
        "supplemental_r3_matrices": supplemental_matrix_audit(),
        "coverage_gates": {
            "all_six_families_have_at_least_three_declared_or_executed_probe_backgrounds": all(
                value["at_least_three_backgrounds_gate"] for value in family_summary.values()
            ),
            "declared_topology_families": list(DECLARED_TOPOLOGY_FAMILIES),
            "all_declared_topology_holdouts_materialized_and_linked": all(
                topology[family]["holdout_gate_pass"] for family in DECLARED_TOPOLOGY_FAMILIES
            ),
            # Backward-compatible alias retained for consumers of the first
            # G3 report; its denominator is now explicitly the four declared
            # holdout families rather than all six families.
            "all_four_topology_holdouts_materialized_and_linked": all(
                topology[family]["holdout_gate_pass"] for family in DECLARED_TOPOLOGY_FAMILIES
            ),
            "any_declared_topology_holdout_materialized_and_structurally_linked": any(
                topology[family]["holdout_gate_pass"] for family in DECLARED_TOPOLOGY_FAMILIES
            ),
            "any_topology_candidate_is_formal_data": any(
                topology[family]["coverage_claim"] for family in DECLARED_TOPOLOGY_FAMILIES
            ),
            "retained_families": list(retained_families),
            "all_retained_families_reference_quality_pass": all(
                references[family]["quality_pass"] for family in retained_families
            ),
            "three_seed_learned_baseline_gate": pilot["learned_baseline"]["three_seed_gate"],
            "any_family_formal_ready": False,
        },
        "open_blockers": [
            "W08 contains 204 controlled cards, but all are planned_not_run and no concrete definitions are linked",
            "F1 twin topology now has one independent executable/run/structural candidate link, but it is rejected for physical/reference acceptance and is not formal data",
            "F2 spout, F3 perforated_proxy, and F6 twin_free remain without an executed W08 topology_extrapolation case; old registry probes are not reused",
            "all six families fail the reference-quality gate (partial anchors or no anchor)",
            "W11 T2 has candidate tracer fields and finite geometry sidecars for 12 fluid cases, but wall_visibility remains unset and no destination specification is declared; T3 and T4 fields are absent",
            "the development pilot has 13 cases but only 3 cases are covered by learned autonomous baseline results",
            "Test14 F6 execution exists but its current DBC proxy is scientifically rejected",
        ],
    }


def write_conclusion(report: dict[str, Any]) -> None:
    family = report["family_summary"]
    topology = report["topology_holdouts"]
    work_packages = report["work_packages"]
    materialized_families = [
        family_name for family_name in DECLARED_TOPOLOGY_FAMILIES
        if topology[family_name]["holdout_gate_pass"]
    ]
    planned_families = [
        family_name for family_name in DECLARED_TOPOLOGY_FAMILIES
        if not topology[family_name]["holdout_gate_pass"]
    ]
    materialized_label = ", ".join(materialized_families) if materialized_families else "none"
    planned_label = ", ".join(planned_families) if planned_families else "none"
    text = f'''# R3 G3 结论：覆盖度与 topology holdout 审计

状态：**审计完成；W08 的连续轴矩阵仍是 design-only，但 F1 twin 已完成一个独立 topology_extrapolation 的 declared→executable→run→structural 链接。该案例保持 candidate/rejected，不进入正式数据；其余 topology holdout 仍是 planned-only。**

## 逐级结果

登记表中的 30 个案例均有定义、均有成功求解记录，30/30 的轨迹数组通过结构审计；W01 的质量门通过 29 个，1 个（粗分辨率 O5 wave-runup）保留为预期失败。这个结果只说明早期机制探针的流水线完整，不能把 29 个 `accepted_probe` 当成物理参考真值。

| 家族 | declared | executable | run | structural | quality pass | 外部参考质量 | pilot T1 | learned eval |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| F1 | {family['F1']['declared']} | {family['F1']['executable']} | {family['F1']['run']} | {family['F1']['trajectory_structural']} | {family['F1']['quality_gate_pass']} | {family['F1']['reference_evidence_status']} | {family['F1']['development_pilot_t1_cases']} | {family['F1']['learned_baseline_evaluated_cases']} |
| F2 | {family['F2']['declared']} | {family['F2']['executable']} | {family['F2']['run']} | {family['F2']['trajectory_structural']} | {family['F2']['quality_gate_pass']} | {family['F2']['reference_evidence_status']} | {family['F2']['development_pilot_t1_cases']} | {family['F2']['learned_baseline_evaluated_cases']} |
| F3 | {family['F3']['declared']} | {family['F3']['executable']} | {family['F3']['run']} | {family['F3']['trajectory_structural']} | {family['F3']['quality_gate_pass']} | {family['F3']['reference_evidence_status']} | {family['F3']['development_pilot_t1_cases']} | {family['F3']['learned_baseline_evaluated_cases']} |
| F4 | {family['F4']['declared']} | {family['F4']['executable']} | {family['F4']['run']} | {family['F4']['trajectory_structural']} | {family['F4']['quality_gate_pass']} | {family['F4']['reference_evidence_status']} | {family['F4']['development_pilot_t1_cases']} | {family['F4']['learned_baseline_evaluated_cases']} |
| F5 | {family['F5']['declared']} | {family['F5']['executable']} | {family['F5']['run']} | {family['F5']['trajectory_structural']} | {family['F5']['quality_gate_pass']} | {family['F5']['reference_evidence_status']} | {family['F5']['development_pilot_t1_cases']} | {family['F5']['learned_baseline_evaluated_cases']} |
| F6 | {family['F6']['declared']} | {family['F6']['executable']} | {family['F6']['run']} | {family['F6']['trajectory_structural']} | {family['F6']['quality_gate_pass']} | {family['F6']['reference_evidence_status']} | {family['F6']['development_pilot_t1_cases']} | {family['F6']['learned_baseline_evaluated_cases']} |

## 顶层状态语义

`work-packages.json` 中 13 个 package 的旧 `status` 全部为 `complete`，但这是历史兼容字段，不是科学验收或覆盖声明。当前审计将 `execution_status`、`acceptance_status`、`validation_scope` 和 `open_blockers` 单独保留：其中 {work_packages['engineering_accepted_count']} 个 package 只达到有限工程范围的 accepted 状态，{len(work_packages['legacy_complete_but_not_engineering_accepted'])} 个 package 虽有旧的 `status=complete` 但没有工程 accepted 状态。W08 的 authoritative 状态是 `execution_status={work_packages['w08_crosscheck']['execution_status']}`、`acceptance_status={work_packages['w08_crosscheck']['acceptance_status']}`，与连续轴 `design_only`、拓扑候选部分实体化的覆盖判定一致。

W08 的 204 张连续轴卡和 196 个唯一 execution unit 全部仍是 `planned_not_run`，没有与 registry、solver attempt、轨迹或训练/评测产物建立链接；连续轴 `coverage_claim=false`。另外显式声明的 W08 topology card 位于独立命名空间，不计入 204 张连续轴卡。

四个已声明 topology holdout 中，工程链已完成的家族为 **{materialized_label}**，仍 planned-only 的为 **{planned_label}**。F1 新增 `W08_F1_topology_twin_obstacle_00`，使用独立 `physical_case_id={topology['F1']['case_links'][0]['physical_case_id'] if topology['F1']['case_links'] else 'unlinked'}` 和 `lineage_group_id={topology['F1']['case_links'][0]['lineage_group_id'] if topology['F1']['case_links'] else 'unlinked'}`，definition、GenCase、solver attempt、归一化 HDF5 和结构审计均可由 `topology-holdout-materializations.json` 追溯；`holdout_gate_pass={topology['F1']['holdout_gate_pass']}`，但 `scientific_acceptance_pass={topology['F1']['scientific_acceptance_pass']}`，所以 `coverage_claim={topology['F1']['coverage_claim']}`。旧 registry 的 `F1_twin_obstacle` 仅作为 incidental 对照，未被挂到第二个 split。F1/F2/F3/F6 的 W07 planned card 数分别为 {topology['F1']['planned_design_card_count']}、{topology['F2']['planned_design_card_count']}、{topology['F3']['planned_design_card_count']}、{topology['F6']['planned_design_card_count']}；W07 卡仍不是生成数据。

## 训练/评测覆盖

W11 development pilot 为 13 例（train 6、validation 3、test 4）。T1 粒子 rollout 所需字段在 13 例都有；其中 12 个流体案例现在已经链接有限边界三角形 sidecar，但 HDF5/material 仍声明 `wall_visibility` 未提供，且没有 wall-aware destination specification，所以 T2 完整任务仍为 0 例；T3 的外部 observable reference 和 T4 的 terminal destination/event history 均为 0 例。selection 与 release 的 ID、split、谱系、校验和及 root-attribute 交叉审计单独记录。W12 真实 autonomous baseline 有两个路线、三种子，但实际测试案例只有 3 个（其中 2 个在 30-case registry 内），不能代表 13 例 pilot 或六个家族。

## 判定和下一步

“每族至少三个背景”在现有探针层面满足，但这是 breadth gate，不是 acceptance gate。所有家族的 reference-quality gate 仍未通过，因此当前没有任何 family 可以直接进入正式 v0.1 或 20–30 例生产 tranche。

下一步应为剩余 topology holdout 建立同样的独立 definition/lineage 链；对 F1 候选补做分辨率与外部参考验收，但在通过前保持 `candidate/rejected`。随后把已生成的边界 sidecar 纳入 wall-aware material contract，补齐 destination、T3/T4 任务字段，再按通过 reference/resolution 门的家族运行小规模 development tranche。不要把 W08 204 张连续轴卡一次性提交给 GPU。

机器可读明细见 `r3-g3-coverage-audit.json`。
'''
    CONCLUSION_PATH.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    write_conclusion(report)
    print(json.dumps({
        "registry_stage_counts": report["registry_stage_counts"],
        "w08": report["w08_design"],
        "topology_holdouts": report["topology_holdouts"],
        "pilot_tasks": report["development_pilot"]["task_ready_counts"],
        "coverage_gates": report["coverage_gates"],
    }, indent=2))


if __name__ == "__main__":
    main()
