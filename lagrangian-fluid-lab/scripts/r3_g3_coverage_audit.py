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
INCIDENTAL_HOLDOUT_CASES = {
    "F1": ["F1_twin_obstacle"],
    "F2": [],
    "F3": [],
    "F6": ["F6_twin_floaters"],
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


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
            result["structural_pass"] = not result["issues"]

            if "material" in h5:
                material = h5["material"]
                missing_material = [name for name in MATERIAL_DATASETS if name not in material]
                result["material_present"] = True
                result["material_missing"] = missing_material
                if not missing_material:
                    material_valid = np.asarray(material["valid"][:], dtype=bool)
                    material_position = material["position"][:]
                    if material_position.shape[:2] != material_valid.shape:
                        result["issues"].append("material position/valid shape mismatch")
                    elif not finite_under_valid(material_position, material_valid):
                        result["issues"].append("non-finite material position under valid mask")
                    weight = material["mass_weight"][:]
                    if not np.isfinite(weight).all() or np.any(weight < 0):
                        result["issues"].append("invalid material mass weights")
                    result["material_tracers"] = int(len(weight))
                    result["material_reliable_at_end"] = int(material_valid[-1].sum()) if len(material_valid) else 0
                    result["wall_visibility"] = str(material.attrs.get("wall_visibility", "missing"))
                    result["material_acceptance_status"] = str(material.attrs.get("acceptance_status", "missing"))
                else:
                    result["material_tracers"] = 0
            else:
                result["material_present"] = False
                result["material_missing"] = list(MATERIAL_DATASETS)
                result["material_tracers"] = 0

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
    return {
        "F1": {
            "status": "partial_external_anchor",
            "quality_pass": False,
            "evidence": "SPHERIC Test 02 surface gauges/pressure; pressure and H1 are non-monotonic",
        },
        "F2": {
            "status": "no_external_anchor",
            "quality_pass": False,
            "evidence": "rotating-pour matrices are numerical only",
        },
        "F3": {
            "status": "partial_external_anchor",
            "quality_pass": False,
            "evidence": "SPHERIC Test 10 pressure has unresolved impact timing/full-trace convergence",
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
            "status": "partial_2d_anchor_and_rejected_3d_test14",
            "quality_pass": False,
            "evidence": "Fekken 2-D surrogate is partial; Test 14 report rejects current DBC proxy",
            "test14_acceptance": f6["scientific_acceptance"],
        },
    }


def w08_topology_audit() -> dict[str, dict[str, Any]]:
    design = load(W08_DESIGN_PATH)
    w07_design = load(W07_DESIGN_PATH)
    cards = design["cards"]
    w07_cards = w07_design["cards"]
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
                "w08_holdout_splits": [],
                "w08_execution_statuses": [],
                "incidental_matching_registry_cases": [],
                "linked_materialized_cases": 0,
                "linked_run_cases": 0,
                "holdout_gate_pass": False,
                "decision": "not_declared_for_family",
            }
            continue
        key = TOPOLOGY_KEY[family]
        holdout = TOPOLOGY_HOLDOUT[family]
        w08_family = [card for card in cards if card["family"] == family]
        w07_family = [card for card in w07_cards if card["family"] == family]
        w08_holdout = [card for card in w08_family if card["physics"].get(key) == holdout]
        w07_holdout = [card for card in w07_family if card["physics"].get(key) == holdout]
        result[family] = {
            "declared_holdout": holdout,
            "topology_field": key,
            "w07_design_cards": len(w07_holdout),
            "w08_controlled_cards": len(w08_holdout),
            "w08_holdout_splits": sorted({card["split"] for card in w08_holdout}),
            "w08_execution_statuses": sorted({card["execution_status"] for card in w08_holdout}),
            "incidental_matching_registry_cases": INCIDENTAL_HOLDOUT_CASES[family],
            "linked_materialized_cases": 0,
            "linked_run_cases": 0,
            "holdout_gate_pass": False,
            "decision": (
                "design_only_not_materialized"
                if not w08_holdout else "not_executed"
            ),
        }
    return result


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
        t2_complete = material and h5.get("wall_visibility") not in ("False", "false", "not supplied in development pilot", "missing")
        # No current manifest record carries a destination specification or an
        # event-history group. Keep these checks explicit instead of treating
        # source labels as destination truth.
        t2_complete = t2_complete and "destination_spec" in entry and "destination_spec" in h5
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
            "material_acceptance_status": h5.get("material_acceptance_status"),
            "hdf5_issues": h5.get("issues", []),
        })
    baseline_results = [load(path) for path in sorted(W12_RESULTS_DIR.glob("*.json"))]
    baseline_routes = sorted({result["route"] for result in baseline_results})
    baseline_seeds = sorted({int(result["seed"]) for result in baseline_results})
    return {
        "pilot_manifest_case_count": len(manifest["cases"]),
        "pilot_split_counts": dict(Counter(entry["split"] for entry in manifest["cases"])),
        "task_ready_case_ids": task_cases,
        "task_ready_counts": {task: len(cases) for task, cases in task_cases.items()},
        "material_candidate_case_count": sum(row["material_candidate"] for row in release_case_rows),
        "release_case_rows": release_case_rows,
        "learned_baseline": {
            "result_files": len(baseline_results),
            "routes": baseline_routes,
            "seeds": baseline_seeds,
            "case_ids": sorted({case_id for result in baseline_results for case_id in result.get("test_rollout", {})}),
            "three_seed_gate": baseline_routes == ["deepset_context", "particle_mlp"] and baseline_seeds == [17, 29, 43],
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
    registry = load(REGISTRY_PATH)["cases"]
    w07 = load(W07_PATH)
    w06 = load(CAMPAIGN / "w06-rotating-pour.json")
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
            "development_tranche_blockers": [
                "topology holdout is not an executed W08 split",
                "reference-quality gate is not passed",
            ],
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
        "learned_baseline_evaluated_cases": len(pilot["learned_baseline"]["case_ids"]),
    }
    w08_design = load(W08_DESIGN_PATH)
    w07_design = load(W07_DESIGN_PATH)
    w08_splits = Counter(card["split"] for card in w08_design["cards"])
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
        "w08_design": {
            "declared_cards": len(w08_design["cards"]),
            "unique_execution_units": load(W08_PATH)["audit"]["unique_execution_units"],
            "execution_status_counts": dict(Counter(card["execution_status"] for card in w08_design["cards"])),
            "split_counts": dict(w08_splits),
            "executable_definitions": 0,
            "run_cases": 0,
            "trajectory_structural_cases": 0,
            "reference_quality_cases": 0,
            "training_eval_cases": 0,
            "decision": "design_only_not_run",
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
            "all_four_topology_holdouts_materialized_and_linked": all(
                value["holdout_gate_pass"] for value in topology.values()
            ),
            "all_retained_families_reference_quality_pass": all(
                references[family]["quality_pass"] for family in FAMILIES
            ),
            "three_seed_learned_baseline_gate": pilot["learned_baseline"]["three_seed_gate"],
            "any_family_formal_ready": False,
        },
        "open_blockers": [
            "W08 contains 204 controlled cards, but all are planned_not_run and no concrete definitions are linked",
            "the four declared topology holdouts have zero W08 controlled cards; W07 topology cards are design-only",
            "F2 spout and F3 perforated_proxy have no incidental materialized case; F1/F6 matching cases are not linked to W08 topology_extrapolation",
            "all six families fail the reference-quality gate (partial anchors or no anchor)",
            "W11 T2 has candidate tracer fields but no wall-aware destination specification; T3 and T4 fields are absent",
            "the development pilot has 13 cases but only 3 cases are covered by learned autonomous baseline results",
            "Test14 F6 execution exists but its current DBC proxy is scientifically rejected",
        ],
    }


def write_conclusion(report: dict[str, Any]) -> None:
    family = report["family_summary"]
    text = f'''# R3 G3 结论：覆盖度与 topology holdout 审计

状态：**审计完成；工程覆盖已经能逐级量化，但 W08 受控泛化设计尚未进入可执行/可评测阶段，四个 topology holdout 也没有形成正式留出。**

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

W08 的 204 张卡和 196 个唯一 execution unit 全部仍是 `planned_not_run`；它们没有定义、solver attempt、轨迹或训练/评测产物。W07 虽然为每族写出了 topology 候选卡（每个 holdout 6 或 8 张），这些也只是设计卡，不能算生成数据。

四个 topology holdout 的实际审计结果都是 `holdout_gate_pass=false`：F1 的 twin obstacle 和 F6 的 twin floaters 只有未链接的旧探针，F2 的 spout、F3 的 perforated proxy 连这样的偶然案例都没有。当前 W08 卡的拓扑字段全部保持 baseline（single/straight/center/single_free），没有 `topology_extrapolation` split。

## 训练/评测覆盖

W11 development pilot 为 13 例（train 6、validation 3、test 4）。T1 粒子 rollout 所需字段在 13 例都有；T2 只有 12 例具备候选 material 组，但仍缺 wall-aware destination specification，不能作为完整材料输运任务；T3 的外部 observable reference 和 T4 的 terminal destination/event history 均为 0 例。W12 真实 autonomous baseline 有两个路线、三种子，但实际测试案例只有 3 个，不能代表 13 例 pilot 或六个家族。

## 判定和下一步

“每族至少三个背景”在现有探针层面满足，但这是 breadth gate，不是 acceptance gate。所有家族的 reference-quality gate 仍未通过，因此当前没有任何 family 可以直接进入正式 v0.1 或 20–30 例生产 tranche。

下一步应先为每个 topology holdout 建立可执行 definition、独立 lineage 和 `topology_extrapolation` split，至少生成并结构审计一个 case；随后补齐 wall-aware destination sidecar、T3/T4 任务字段，再按通过 reference/resolution 门的家族运行小规模 development tranche。不要把 W08 204 张卡一次性提交给 GPU。

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
