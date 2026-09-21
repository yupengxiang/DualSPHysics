"""Build the bounded F4 reconstruction diagnosis and canary registrations.

This report generator consumes the immutable v1/v2 manufactured receipts and
repeats only the small constant-field support probe used to separate ESS
geometry from reconstruction-error calibration.  It never launches CFD or a
material canary and never touches the campaign ledger.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.core_material import (
    F4_AFFINE_BACKEND,
    F4_AFFINE_NEIGHBOURS,
    F4_ESS32_BACKEND,
    F4_ESS32_NEIGHBOURS,
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    REGULARIZATION_M,
    CurrentField,
    f4_destination_region,
    f4_resting_pool_definition,
    f4_source_region,
    f4_walls,
    seeds_f4,
)
from scripts.f4_material_calibration import _box_lattice, _hash_array


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
SOURCE = LAB / (
    "campaigns/core-v1/runtime/attempts/"
    "f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5/"
    "20260919T185855-d91665790347/product/trajectory.h5"
)
SOURCE_RESULT = SOURCE.parent / "result.json"
SOURCE_PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F4_resting_pool_center_native_dense_002_canary/prepared.json"
DIAGNOSTIC = EVIDENCE / "f4-dense-short-diagnostic-results.json"
CORE_MATERIAL = LAB / "scripts/core_material.py"
NEIGHBOUR_CODE = LAB / "scripts/f3_material_neighbors.py"
PASSIVE_CODE = LAB / "scripts/passive_tracers.py"
CALIBRATION_V1 = LAB / "scripts/f4_material_calibration.py"
CALIBRATION_V2 = LAB / "scripts/f4_material_calibration_v2.py"
V1_RESULT = EVIDENCE / "f4-reconstruction-calibration-result.json"
V1_EXECUTION = EVIDENCE / "f4-reconstruction-calibration-execution.json"
V2_DESIGN = EVIDENCE / "f4-reconstruction-calibration-v2-20260919-design.json"
V2_RESULT = EVIDENCE / "f4-reconstruction-calibration-v2-20260919-result.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def row_classification(row):
    failures = row["gate_failure_counts"]
    unknown = int(row["unknown_count"])
    if (
        row["diagnostic_false_alarm_mass_fraction"] > 0
        and row["diagnostic_false_safe_mass_fraction"] == 0
        and row["true_error_over_gate_fraction"] == 0
        and failures["effective_sample_size"] == unknown
        and all(failures[name] == 0 for name in ("geometry_rank", "anisotropy", "reconstruction_error"))
    ):
        return "ess_only_false_alarm"
    if row["diagnostic_false_safe_mass_fraction"] > 0:
        return "false_safe"
    if row["true_error_over_gate_fraction"] > 0 and unknown == 0:
        return "missed_reconstruction_gate"
    if unknown == 0 and row["true_error_over_gate_fraction"] == 0:
        return "fully_observed"
    return "mixed_gate_outcome"


def v1_row_table(result):
    table = []
    for index, row in enumerate(result["rows"]):
        table.append({
            "row_index": index,
            "q": row["q"], "field": row["field"], "region": row["region"],
            "query_count": row["query_count"], "reliable_count": row["reliable_count"],
            "unknown_count": row["unknown_count"], "unknown_mass_fraction": row["unknown_mass_fraction"],
            "unknown_budget_max": row["unknown_budget_max"], "unknown_budget_pass": row["unknown_budget_pass"],
            "mass_closure": row["mass_closure"],
            "true_error_p95_mps": row["true_error_p95_mps"],
            "true_error_max_mps": row["true_error_max_mps"],
            "true_error_over_gate_fraction": row["true_error_over_gate_fraction"],
            "diagnostic_reconstruction_p95_mps": row["diagnostic_reconstruction_p95_mps"],
            "diagnostic_false_alarm_mass_fraction": row["diagnostic_false_alarm_mass_fraction"],
            "diagnostic_false_safe_mass_fraction": row["diagnostic_false_safe_mass_fraction"],
            "gate_failure_counts": dict(row["gate_failure_counts"]),
            "classification": row_classification(row),
            "cloud_count": row["cloud_count"], "cloud_hash": row["cloud_hash"],
            "query_hash": row["query_hash"], "truth_hash": row["truth_hash"],
        })
    return table


def field_region_table(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["field"], row["region"])].append(row)
    table = []
    for (field, region), group in sorted(groups.items()):
        table.append({
            "field": field, "region": region,
            "q_values": sorted({row["q"] for row in group}),
            "rows": len(group), "query_count": sum(row["query_count"] for row in group),
            "unknown_count": sum(row["unknown_count"] for row in group),
            "unknown_mass_fraction_max": max(row["unknown_mass_fraction"] for row in group),
            "false_alarm_mass_fraction_max": max(row["diagnostic_false_alarm_mass_fraction"] for row in group),
            "false_safe_mass_fraction_max": max(row["diagnostic_false_safe_mass_fraction"] for row in group),
            "true_error_p95_mps_max": max(row["true_error_p95_mps"] for row in group),
            "diagnostic_p95_mps_max": max(row["diagnostic_reconstruction_p95_mps"] for row in group),
            "true_error_over_gate_fraction_max": max(row["true_error_over_gate_fraction"] for row in group),
            "gate_failure_totals": {
                name: sum(row["gate_failure_counts"][name] for row in group)
                for name in ("effective_sample_size", "geometry_rank", "anisotropy", "reconstruction_error")
            },
            "mass_closure_all": all(abs(row["mass_closure"] - 1.0) <= 1e-12 for row in group),
        })
    return table


def support_probe(q):
    destination = f4_destination_region()
    source = f4_source_region(q)
    cloud = np.concatenate([
        _box_lattice(destination["box_low_m"], destination["box_size_m"], 0.015),
        _box_lattice(source["box_low_m"], source["box_size_m"], 0.015),
    ])
    query = seeds_f4(512, q)
    field = CurrentField(cloud, np.broadcast_to([1.0, 2.0, 3.0], cloud.shape).copy())
    _, distance, passed, diagnostics = field.sample(
        query, f4_walls(), neighbours=24, regularization=REGULARIZATION_M,
        gate=GATE, error_estimator="local_residual", return_diagnostics=True,
    )
    _, distance32, passed32, diagnostics32 = field.sample(
        query, f4_walls(), neighbours=32, regularization=REGULARIZATION_M,
        gate=GATE, error_estimator="local_residual", return_diagnostics=True,
    )
    bad = np.flatnonzero(~passed)
    return {
        "q": float(q), "cloud_count": int(len(cloud)), "cloud_hash": _hash_array(cloud),
        "query_count": int(len(query)), "query_hash": _hash_array(query),
        "baseline_neighbours": 24, "baseline_bad_count": int(len(bad)),
        "baseline_bad_indices": bad.tolist(), "baseline_bad_coordinates_m": query[bad].tolist(),
        "baseline_bad_coordinate_unique_rounded_m": {
            axis: sorted({round(float(value), 8) for value in query[bad, i]})
            for i, axis in enumerate(("x", "y", "z"))
        },
        "baseline_support_distance_unique_m": sorted({round(float(value), 12) for value in distance[bad]}),
        "baseline_visible_neighbours_unique": sorted({int(value) for value in diagnostics["visible_neighbours"][bad]}),
        "baseline_selected_visible_neighbours_unique": sorted({int(value) for value in diagnostics["selected_visible_neighbours"][bad]}),
        "baseline_visibility_search_width_unique": sorted({int(value) for value in diagnostics["visibility_search_width"][bad]}),
        "baseline_ess_min": float(np.min(diagnostics["effective_sample_size"][bad])),
        "baseline_ess_max": float(np.max(diagnostics["effective_sample_size"][bad])),
        "baseline_rank_unique": sorted({int(value) for value in diagnostics["geometry_rank"][bad]}),
        "baseline_anisotropy_min": float(np.min(diagnostics["anisotropy"][bad])),
        "baseline_anisotropy_max": float(np.max(diagnostics["anisotropy"][bad])),
        "baseline_estimated_error_max_mps": float(np.max(diagnostics["estimated_interpolation_error_mps"][bad])),
        "k32_neighbours": 32, "k32_reliable_count": int(passed32.sum()),
        "k32_unknown_count": int((~passed32).sum()),
        "k32_ess_min": float(np.min(diagnostics32["effective_sample_size"])),
        "k32_support_distance_p95_m": float(np.percentile(distance32, 95)),
    }


def v2_row_table(result):
    fields = (
        "backend", "neighbours", "error_estimator", "reliable_count", "unknown_count",
        "unknown_mass_fraction", "unknown_budget_pass", "diagnostic_false_alarm_mass_fraction",
        "diagnostic_false_safe_mass_fraction", "true_error_p95_mps", "true_error_max_mps",
        "true_error_over_gate_fraction", "diagnostic_reconstruction_p95_mps", "ess_p05", "rank_min",
        "anisotropy_p05", "support_distance_p95_m", "gate_failure_counts", "mass_closure",
    )
    table = []
    for index, row in enumerate(result["rows"]):
        table.append({
            "row_index": index, "q": row["q"], "field": row["field"], "region": row["region"],
            "query_count": row["query_count"], "cloud_count": row["cloud_count"],
            "query_hash": row["query_hash"], "cloud_hash": row["cloud_hash"], "truth_hash": row["truth_hash"],
            "variants": {
                name: {key: report[key] for key in fields}
                for name, report in row["variants"].items()
            },
        })
    return table


def v2_summary(result):
    groups = defaultdict(list)
    for row in result["rows"]:
        groups[row["region"]].append(row)
    summary = {}
    for name, binding in result["backend_candidates"].items():
        regions = {}
        for region, rows in sorted(groups.items()):
            reports = [row["variants"][name] for row in rows]
            regions[region] = {
                "rows": len(reports), "query_count": sum(row["query_count"] for row in reports),
                "reliable_count": sum(row["reliable_count"] for row in reports),
                "unknown_count": sum(row["unknown_count"] for row in reports),
                "unknown_mass_fraction_max": max(row["unknown_mass_fraction"] for row in reports),
                "unknown_budget_pass_all": all(row["unknown_budget_pass"] for row in reports),
                "false_alarm_mass_fraction_max": max(row["diagnostic_false_alarm_mass_fraction"] for row in reports),
                "false_safe_mass_fraction_max": max(row["diagnostic_false_safe_mass_fraction"] for row in reports),
                "true_error_p95_mps_max": max(row["true_error_p95_mps"] for row in reports),
                "diagnostic_p95_mps_max": max(row["diagnostic_reconstruction_p95_mps"] for row in reports),
                "true_error_over_gate_fraction_max": max(row["true_error_over_gate_fraction"] for row in reports),
                "gate_failure_totals": {
                    key: sum(row["gate_failure_counts"][key] for row in reports)
                    for key in ("effective_sample_size", "geometry_rank", "anisotropy", "reconstruction_error")
                },
                "mass_closure_all": all(abs(row["mass_closure"] - 1.0) <= 1e-12 for row in reports),
            }
        summary[name] = {
            "backend_binding": binding,
            "source_macro_budget_pass": result["source_macro_budget_pass_by_variant"][name],
            "by_region": regions,
        }
    return summary


def file_record(path: Path, **extra):
    record = {"path": str(path.resolve()), "sha256": sha256(path)}
    record.update(extra)
    return record


def build_analysis():
    v1 = load(V1_RESULT)
    v1_execution = load(V1_EXECUTION)
    v2_design = load(V2_DESIGN)
    v2 = load(V2_RESULT)
    rows = v1_row_table(v1)
    source_rows = [row for row in rows if row["region"] == "source"]
    non_source_rows = [row for row in rows if row["region"] != "source"]
    return {
        "schema": "core.material.f4.reconstruction_calibration.diagnosis.v1",
        "revision_id": "F4_reconstruction_calibration_diagnosis_20260919",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none",
        "lineage_policy": {
            "dev00_failure_data_used_for_selection": False,
            "f3_production_failures_used_for_selection": False,
            "source": "F4 qualification-only manufactured calibration and held-out analytic validation",
            "real_cfd_canary_role": "canary design only; no T2 inference from .3 s dense source",
        },
        "fixed_acceptance": {
            "unknown_fraction_max": 0.01,
            "mass_closure_abs_error_max": 1e-12,
            "support_gate": dict(GATE),
            "regularization_m": REGULARIZATION_M,
            "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
            "weighting": "1/(d^2+eps^2)",
            "gate_changed": False,
        },
        "inputs": {
            "v1_result": file_record(V1_RESULT, schema=v1["schema"], design_hash=v1["design_hash"], script_sha256=v1["execution"]["script_sha256"]),
            "v1_execution": file_record(V1_EXECUTION, receipt=v1_execution),
            "v2_design": file_record(V2_DESIGN, schema=v2_design["schema"], revision_id=v2_design["revision_id"]),
            "v2_result": file_record(V2_RESULT, schema=v2["schema"], design_hash=v2["design_hash"], script_sha256=v2["execution"]["script_sha256"]),
            "current_candidate_implementation": file_record(CORE_MATERIAL),
            "support_code": file_record(NEIGHBOUR_CODE),
            "passive_gate_code": file_record(PASSIVE_CODE),
            "calibration_v1_code": file_record(CALIBRATION_V1),
            "calibration_v2_code": file_record(CALIBRATION_V2),
            "diagnosis_generator": file_record(Path(__file__)),
            "real_dense_source": file_record(SOURCE, role="completed native .002 s F4 center q=.5 source"),
            "real_dense_source_result": file_record(SOURCE_RESULT),
            "real_dense_prepared": file_record(SOURCE_PREPARED),
            "dense_baseline_diagnostic": file_record(DIAGNOSTIC),
        },
        "v1_32_row_analysis": {
            "row_count": len(rows), "source_row_count": len(source_rows),
            "non_source_row_count": len(non_source_rows),
            "source_unknown_observations": sum(row["unknown_count"] for row in source_rows),
            "source_query_observations": sum(row["query_count"] for row in source_rows),
            "false_alarm_rows": sum(row["classification"] == "ess_only_false_alarm" for row in rows),
            "false_safe_rows": sum(row["diagnostic_false_safe_mass_fraction"] > 0 for row in rows),
            "true_error_over_gate_rows": sum(row["true_error_over_gate_fraction"] > 0 for row in rows),
            "unknown_budget_pass_rows": sum(row["unknown_budget_pass"] for row in rows),
            "unknown_budget_fail_rows": sum(not row["unknown_budget_pass"] for row in rows),
            "all_mass_closure": all(abs(row["mass_closure"] - 1.0) <= 1e-12 for row in rows),
            "gate_failure_totals": {
                name: sum(row["gate_failure_counts"][name] for row in rows)
                for name in ("effective_sample_size", "geometry_rank", "anisotropy", "reconstruction_error")
            },
            "row_table": rows,
            "field_region_table": field_region_table(rows),
        },
        "geometry_support_diagnosis": {
            "method": "exact v1 cloud/query construction with constant velocity; fixed k=24 versus one pre-registered k=32 candidate check",
            "cloud_construction": "destination box plus q-dependent source box, lattice spacing 0.015 m; same F4 walls and 512 source seeds",
            "checks": [support_probe(0.5), support_probe(1.0)],
            "interpretation": {
                "support_gate_failure": "ESS only; all failing samples retain rank=3, anisotropy above .005, finite tiny residual, visible=96 and support distance below .03 m",
                "geometry_validity": "failure is a finite-support ESS threshold artefact at k=24, repeated at q=.5 and q=1.0; it is not missing visibility or rank deficiency",
                "k32_evidence": "fixed k=32 clears all 16 exact failing source locations for both q values with minimum ESS just above 4; this is a candidate check, not a threshold sweep",
            },
        },
        "independent_v2_validation": {
            "scope": "12 rows: held-out q=.25/.75 x 3 new analytic fields x source/interface; no CFD failure locations and no dev00 data",
            "fields": v2_design["manufactured_fields"],
            "backend_candidates": v2["backend_candidates"],
            "source_macro_budget_pass_by_variant": v2["source_macro_budget_pass_by_variant"],
            "variant_summary": v2_summary(v2),
            "row_table": v2_row_table(v2),
            "all_mass_closure_pass": v2["all_mass_closure_pass"],
            "interpretation": {
                "f4_ess32_v2": "passes the unchanged .01 source unknown budget on all six held-out source rows; no false-safe mass and no gate component failures",
                "f4_affine_bound_v2": "does not repair source ESS false alarms because it keeps k=24; it is retained only as an error-estimator calibration candidate",
                "reconstruction_calibration": "held-out interface vortex rows show affine estimation closer to true p95 while leaving the reconstruction gate unchanged",
            },
        },
        "hypotheses_max_two": [
            {
                "id": "F4-H1-ess32-support-cap-v2", "candidate": "f4_ess32_v2", "claim": "geometry-support repair",
                "implementation": {"backend": F4_ESS32_BACKEND, "neighbours": F4_ESS32_NEIGHBOURS, "error_estimator": "local_residual", "weights": "1/(d^2+eps^2)"},
                "evidence": [
                    "v1 has 8 source rows with 16/512 ESS-only false alarms each; failed geometry has rank=3 and anisotropy=.4638-.5997",
                    "same geometry with fixed k=32 gives 512/512 reliable and minimum ESS=4.013091367745095",
                    "held-out v2 source rows pass the unknown budget for all six q/field rows with no false-safe mass",
                ],
                "canary_decision_rule": "same real dense .002 s, .3 s q=.5 source with seeds=512 and substeps=4; every source unknown_fraction_max <= .01, mass closure <=1e-12, and all gate components reported; no T2 claim",
            },
            {
                "id": "F4-H2-affine-query-bound-v2", "candidate": "f4_affine_bound_v2", "claim": "reconstruction-error calibration",
                "implementation": {"backend": F4_AFFINE_BACKEND, "neighbours": F4_AFFINE_NEIGHBOURS, "error_estimator": "residual_plus_local_affine_query_bias", "weights": "1/(d^2+eps^2)"},
                "evidence": [
                    "v1 interface true p95 reaches .0146407268 m/s while local residual p95 is .0000813796 m/s for the quadratic field; all remain below the fixed cap",
                    "held-out v2 vortex interface true p95=.0139701905 m/s, baseline diagnostic p95=.0012773616, affine diagnostic p95=.0093341759",
                    "it leaves k=24 ESS false alarms unchanged, so it is not a substitute for H1",
                ],
                "canary_decision_rule": "same real dense source independently; require unchanged unknown<=.01 and mass closure, then compare error estimates to baseline/H1; reject if gate semantics change or false-safe mass appears",
            },
        ],
        "execution_limits": {
            "v1_device": "CPU", "v1_gpu_started": False, "v1_ledger_touched": False, "v1_slot_acquired": False,
            "v1_elapsed_seconds": v1["execution"]["elapsed_seconds"], "v1_max_rss_kib": v1["execution"]["max_rss_kib"],
            "v2_device": "CPU", "v2_gpu_started": False, "v2_ledger_touched": False, "v2_slot_acquired": False,
            "v2_elapsed_seconds": v2["execution"]["elapsed_seconds"], "v2_max_rss_kib": v2["execution"]["max_rss_kib"],
            "real_canary_status": "prepared_only; no material candidate canary launched by this analysis",
            "scientific_limit": "manufactured fields validate support/error diagnostics only; neither v1 nor v2 qualifies F4 T2",
        },
    }


def canary_spec(candidate, variant, backend, neighbours, estimator):
    source_hash = sha256(SOURCE)
    definition = f4_resting_pool_definition(0.5, dp_m=0.0075)
    return {
        "schema": "core.material.job.v1", "job_id": candidate,
        "logical_id": candidate.upper(), "attempt_role": "initial", "category": "repair_canary",
        "family": "F4", "scope_id": definition["scope_id"], "revision_id": definition["revision_id"],
        "host": "ada", "cwd": str(LAB), "depends_on": [],
        "argv": [
            str(LAB / ".venv/bin/python"), str(CORE_MATERIAL), "--family", "f4",
            "--source", str(SOURCE), "--output", "{attempt_dir}/material.h5",
            "--q", "0.5", "--dp-m", "0.0075", "--seeds", "512", "--substeps", "4",
            "--neighbour-variant", variant,
        ],
        "required_outputs": ["material.h5", "material.json", "material.h5.checkpoint.npz", "material.h5.checkpoint.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 8192, "gpu_peak_mib": 0, "io_weight": 0.25},
        "timeout_seconds": 3600, "gpu_started": False, "central_ledger_mutation": 0,
        "execution_status": "prepared_only", "stage": "canary",
        "qualification_claim": "none; real native dense .3 s overlay only; event window is right-censored",
        "input_files": [
            file_record(SOURCE, role="real_native_f4_dense_002s_trajectory"),
            file_record(SOURCE_PREPARED, role="prepared_native_dense_source_definition"),
            file_record(SOURCE_RESULT, role="native_dense_integrity_receipt"),
            file_record(EVIDENCE / "f4-reconstruction-calibration-diagnosis-20260919.json", role="candidate_diagnosis"),
            file_record(V2_DESIGN, role="held_out_manufactured_validation_design"),
            file_record(V2_RESULT, role="held_out_manufactured_validation_receipt"),
            file_record(CORE_MATERIAL, role="material_tracer_candidate_backend"),
            file_record(NEIGHBOUR_CODE, role="visible_support_backend"),
            file_record(PASSIVE_CODE, role="wall_and_gate_helpers"),
            file_record(EVIDENCE / "f4-resting-pool-migration-spec-2026-09-19.json", role="F4_event_definition"),
        ],
        "source_dependency": {
            "cfd_job_id": "f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5",
            "source_path": str(SOURCE), "source_sha256": source_hash,
            "source_role": "completed native output at .002 s; direct reference rows; no interpolation",
            "native_frame_count": 151, "time_start_s": 0.0, "time_end_s": 0.3000032376922204,
            "native_output_interval_s": 0.002, "q": 0.5, "dp_m": 0.0075,
            "source_qualification": "none; one short case cannot establish F4 T2",
        },
        "material_backend": {
            "neighbour_variant": variant, "backend": backend, "neighbours": neighbours,
            "error_estimator": estimator, "weighting": "1/(d^2+eps^2)",
            "regularization_m": REGULARIZATION_M, "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
            "unknown_gate_fraction_max": 0.01, "support_gate": dict(GATE),
            "seed_identity": "independent seed-XXXXXX ids; never native particle_id",
        },
        "material_definition": definition,
        "event_policy": {
            "contact": "first downward crossing z=0.18 after t=0",
            "upward": "first later upward crossing z=0.18",
            "return": "first later downward crossing z=0.18 after upward",
            "residence": "continuous destination-box time after contact",
            "unobserved_event_policy": "NaN/right-censored; never impute from saved-frame chord or synthetic output",
            "canary_window_s": 0.3000032376922204, "event_window_status": "right_censored_or_unresolved",
            "registered_scope_initial_horizon_s": 4.34, "registered_scope_maximum_extended_horizon_s": 8.68,
        },
        "acceptance": {
            "must_not_report_T2_qualification": True, "must_preserve_mass_closure": True,
            "must_preserve_source_hash_binding": True, "must_report_unknown_fraction_per_source": True,
            "must_report_first_failure_frame_time": True, "must_report_gate_failure_components": True,
            "must_support_atomic_checkpoint_resume": True, "unknown_gate_remains_1_percent": True,
            "comparison": "compare against baseline24 on the same dense source; candidate is an independent overlay",
        },
        "comparison_control": {
            "baseline_variant": "baseline24", "baseline_gate_unchanged": True,
            "dense_short_diagnostic_path": str(DIAGNOSTIC.resolve()), "dense_short_diagnostic_sha256": sha256(DIAGNOSTIC),
            "baseline_unknown_fraction_s2_s4": 0.896484375,
        },
    }


def write_markdown(report_path: Path, canaries):
    report = [
        "# F4 reconstruction calibration diagnosis (2026-09-19)", "",
        "Qualification claim: none. The unknown budget remains 1%; support and reconstruction gates are unchanged.", "",
        "## 32-row v1 result", "",
        "| group | rows | unknown / queries | false alarms | false safe | true error over gate | gate failure totals |",
        "|---|---:|---:|---:|---:|---:|---|",
        "| source (q=.5,1 × 4 fields) | 8 | 128 / 4096 = 3.125% per row | 8 rows | 0 | 0 | ESS 128; rank 0; anisotropy 0; reconstruction 0 |",
        "| destination/interface/closed wall | 24 | 0 / 7936 | 0 | 0 | 0 | all zero |", "",
        "Every source failure is an ESS-only false alarm. True analytic error stays below the fixed 0.0469813793 m/s cap and no sample is false safe; all rows close mass.", "",
        "The same 16 source locations fail at q=.5 and q=1.0. They have 96 visible neighbours, 24 retained neighbours, rank 3, anisotropy 0.4638–0.5997, support distance 0.00242052 m, and ESS 3.52067 or 3.94615. A fixed k=32 check on that geometry gives 512/512 reliable and minimum ESS 4.01309137.", "",
        "## Held-out v2 validation", "",
        "| candidate | held-out source rows | source unknown budget | false safe | result |",
        "|---|---:|---:|---:|---|",
        "| baseline24 | 6 | fails: 3.125% each | 0 | reproduces ESS false alarms |",
        "| f4_ess32_v2 | 6 | passes: 0% each | 0 | supports H1 |",
        "| f4_affine_bound_v2 | 6 | fails: 3.125% each | 0 | estimator calibration only; does not repair ESS |", "",
        "The independent v2 set uses held-out q=.25/.75 and new constant_offset, cubic_shear, and vortex_interface fields. On held-out vortex interface queries, true p95 is 0.0139702 m/s; baseline residual p95 is 0.00127736 m/s and affine-bound p95 is 0.00933418 m/s. This supports H2 as an estimator calibration canary while retaining the same gate.", "",
        "## Prepared real canaries", "",
        "Both candidates bind the completed native .002 s, .3 s center q=.5 trajectory (151 frames), use 512 independent seeds and four tracer substeps, and remain CPU-only read-only overlays. They retain the 1% unknown gate, mass closure, checkpoint/resume, and right-censored event policy.", "",
    ]
    for path, purpose in canaries:
        report.append(f"- `{path.name}`: {purpose}.")
    report += ["", "## Provenance", "", f"Diagnosis JSON: `{report_path.resolve()}`", "", "- v1/v2 receipts, source and implementation hashes are recorded in the JSON artifact.", "- v1 and v2 manufactured runs used CPU only; GPU, ledger, and scheduler slots were not used; real repair canaries are prepared only.", ""]
    report_path.with_suffix(".md").write_text("\n".join(report))


def main():
    report = build_analysis()
    report_path = EVIDENCE / "f4-reconstruction-calibration-diagnosis-20260919.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    canary_dir = LAB / "campaigns/core-v1/material/jobs/f4-reconstruction-repair-canaries-20260919"
    canary_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        canary_spec(
            "f4-material-repair-ess32-v2-canary-s0p3-center-q0p5",
            "f4_ess32_v2", F4_ESS32_BACKEND, F4_ESS32_NEIGHBOURS, "local_residual",
        ),
        canary_spec(
            "f4-material-repair-affine-bound-v2-canary-s0p3-center-q0p5",
            "f4_affine_bound_v2", F4_AFFINE_BACKEND, F4_AFFINE_NEIGHBOURS,
            "residual_plus_local_affine_query_bias",
        ),
    ]
    paths = []
    for spec in specs:
        path = canary_dir / (spec["job_id"] + ".json")
        path.write_text(json.dumps(spec, indent=2, sort_keys=True, allow_nan=False) + "\n")
        paths.append(path)
    manifest = {
        "schema": "core.material.repair_canary_manifest.v1",
        "status": "prepared_only",
        "qualification_claim": "none",
        "source_sha256": sha256(SOURCE),
        "diagnosis_path": str(report_path.resolve()),
        "diagnosis_sha256": sha256(report_path),
        "candidates": [
            {"job_id": spec["job_id"], "path": str(path.resolve()), "sha256": sha256(path), "variant": spec["material_backend"]["neighbour_variant"]}
            for spec, path in zip(specs, paths)
        ],
        "execution_limits": {"gpu_started": False, "central_ledger_mutation": 0, "solver_started": False},
    }
    manifest_path = canary_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    write_markdown(report_path, [(path, "fixed support-cap candidate" if "ess32" in path.name else "fixed affine query-bias estimator candidate") for path in paths])
    print(json.dumps({
        "report": {"path": str(report_path), "sha256": sha256(report_path)},
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "canaries": [{"path": str(path), "sha256": sha256(path)} for path in paths],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
