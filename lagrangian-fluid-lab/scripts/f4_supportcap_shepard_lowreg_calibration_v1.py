"""Synthetic analytic-array comparison for F4 low-regularization v6.

The original two-q corpus is preserved, with three supplemental q values for
diagnostic coverage. Since the predictor parameter was selected after prior
corpus inspection, none of these results is labeled independent validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy

from scripts.core_material import CurrentField, f4_destination_region, f4_source_region, f4_walls
from scripts.f3_material_neighbors import _visible_support
from scripts.f4_material_calibration import _box_lattice
from scripts.f4_material_calibration_v3 import (
    FIELD_IDS,
    Q_CASES as ORIGINAL_Q_CASES,
    SUPPORT_SPACING_M,
    manufactured_velocity_v3,
    query_regions,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_shepard_lowreg_candidate_v6 import (
    CANDIDATE_ID,
    PREDICTOR_REGULARIZATION_M,
    sample_candidate as sample_v6,
)


SCHEMA = "core.material.f4.supportcap.shepard_lowreg.calibration.v2"
SUPPLEMENTAL_Q_CASES = (0.125, 0.25, 0.625)
CALIBRATION_Q_CASES = tuple(ORIGINAL_Q_CASES) + SUPPLEMENTAL_Q_CASES
QUERIES_PER_FIELD_Q = 512 + (16 * 8 * 3) + (16 * 8 * 4)
QUERY_COUNT = len(CALIBRATION_Q_CASES) * len(FIELD_IDS) * QUERIES_PER_FIELD_Q
assert QUERY_COUNT == 14080


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run() -> dict:
    rows: list[dict] = []
    totals = {
        "queries": 0,
        "v3_gate_pass": 0,
        "v6_gate_pass": 0,
        "v3_pass_v6_fail": 0,
        "v3_fail_v6_pass": 0,
    }
    sums = {
        field: {
            name: 0.0
            for name in (
                "v3_sse", "v6_sse", "count", "v3_gate_pass", "v6_gate_pass",
                "v3_pass_v6_fail", "v3_fail_v6_pass",
            )
        }
        for field in FIELD_IDS
    }
    maxima = {field: {name: 0.0 for name in ("v3", "v6")} for field in FIELD_IDS}
    q_summaries: dict[str, dict] = {}
    walls = f4_walls()

    for q in CALIBRATION_Q_CASES:
        destination = f4_destination_region()
        source = f4_source_region(float(q))
        cloud = np.concatenate([
            _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
            _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
        ])
        q_summaries[str(q)] = {field: {"v3_sse": 0.0, "v6_sse": 0.0, "count": 0} for field in FIELD_IDS}
        for field in FIELD_IDS:
            cloud_velocity = manufactured_velocity_v3(cloud, field)
            field_index = CurrentField(cloud, cloud_velocity)
            for region, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v3(query, field)
                pred3, support3, pass3, _ = sample_v3(cloud, cloud_velocity, query, walls)
                pred6, support6, pass6, diag6 = sample_v6(cloud, cloud_velocity, query, walls)
                np.testing.assert_array_equal(support6, support3)
                selected3, distance2_3, _, _, _ = _visible_support(
                    field_index.tree,
                    query,
                    field_index.position,
                    walls,
                    min(32, field_index.valid_count),
                )
                np.testing.assert_array_equal(diag6["selected_support_indices"], selected3)
                np.testing.assert_array_equal(
                    diag6["selected_visible_neighbours"], np.isfinite(distance2_3).sum(axis=1)
                )
                errors = {
                    "v3": np.linalg.norm(pred3 - truth, axis=1),
                    "v6": np.linalg.norm(pred6 - truth, axis=1),
                }
                for name, error in errors.items():
                    maxima[field][name] = max(maxima[field][name], float(error.max(initial=0.0)))
                    q_summaries[str(q)][field][f"{name}_sse"] += float(error @ error)
                count = len(query)
                sums[field]["v3_sse"] += float(errors["v3"] @ errors["v3"])
                sums[field]["v6_sse"] += float(errors["v6"] @ errors["v6"])
                sums[field]["count"] += count
                regression_count = int(np.count_nonzero(pass3 & ~pass6))
                improvement_count = int(np.count_nonzero(~pass3 & pass6))
                sums[field]["v3_gate_pass"] += int(pass3.sum())
                sums[field]["v6_gate_pass"] += int(pass6.sum())
                sums[field]["v3_pass_v6_fail"] += regression_count
                sums[field]["v3_fail_v6_pass"] += improvement_count
                q_summaries[str(q)][field]["count"] += count
                totals["queries"] += count
                totals["v3_gate_pass"] += int(pass3.sum())
                totals["v6_gate_pass"] += int(pass6.sum())
                totals["v3_pass_v6_fail"] += regression_count
                totals["v3_fail_v6_pass"] += improvement_count
                rows.append({
                    "q": float(q),
                    "field": field,
                    "region": region,
                    "query_count": count,
                    "v3_gate_pass_count": int(pass3.sum()),
                    "v6_gate_pass_count": int(pass6.sum()),
                    "v3_pass_v6_fail_count": regression_count,
                    "v3_fail_v6_pass_count": improvement_count,
                    "selected_support_indices_sha256": hashlib.sha256(
                        np.ascontiguousarray(selected3, dtype="<i8").tobytes()
                    ).hexdigest(),
                    "v3_truth_rmse_mps": float(np.sqrt(np.mean(errors["v3"] ** 2))),
                    "v6_truth_rmse_mps": float(np.sqrt(np.mean(errors["v6"] ** 2))),
                    "v3_truth_max_error_mps": float(errors["v3"].max(initial=0.0)),
                    "v6_truth_max_error_mps": float(errors["v6"].max(initial=0.0)),
                })

    if totals["queries"] != QUERY_COUNT:
        raise AssertionError("analytic-array query denominator changed")
    by_field = {
        field: {
            "query_count": int(values["count"]),
            "v3_gate_pass_count": int(values["v3_gate_pass"]),
            "v6_gate_pass_count": int(values["v6_gate_pass"]),
            "v3_pass_v6_fail_count": int(values["v3_pass_v6_fail"]),
            "v3_fail_v6_pass_count": int(values["v3_fail_v6_pass"]),
            "v3_truth_rmse_mps": float(np.sqrt(values["v3_sse"] / values["count"])),
            "v6_truth_rmse_mps": float(np.sqrt(values["v6_sse"] / values["count"])),
            "v3_truth_max_error_mps": maxima[field]["v3"],
            "v6_truth_max_error_mps": maxima[field]["v6"],
        }
        for field, values in sums.items()
    }
    by_q = {
        q: {
            field: {
                "query_count": int(values["count"]),
                "v3_truth_rmse_mps": float(np.sqrt(values["v3_sse"] / values["count"])),
                "v6_truth_rmse_mps": float(np.sqrt(values["v6_sse"] / values["count"])),
            }
            for field, values in field_values.items()
        }
        for q, field_values in q_summaries.items()
    }
    regional_rmse_non_regression = all(
        row["v6_truth_rmse_mps"] <= row["v3_truth_rmse_mps"] for row in rows
    )
    exploratory_screen = {
        "regional_rmse_non_regression": regional_rmse_non_regression,
        "candidate_gate_regression_count": totals["v3_pass_v6_fail"],
        "preflight_recommendation": (
            "not_justified"
            if not regional_rmse_non_regression or totals["v3_pass_v6_fail"] > 0
            else "requires_independent_review"
        ),
    }
    return {
        "schema": SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "design": {
            "original_q_cases": list(ORIGINAL_Q_CASES),
            "supplemental_diagnostic_q_cases": list(SUPPLEMENTAL_Q_CASES),
            "fields": list(FIELD_IDS),
            "regions": ["source", "interface", "destination"],
            "queries_per_field_per_q": QUERIES_PER_FIELD_Q,
            "original_query_count": len(ORIGINAL_Q_CASES) * len(FIELD_IDS) * QUERIES_PER_FIELD_Q,
            "supplemental_query_count": len(SUPPLEMENTAL_Q_CASES) * len(FIELD_IDS) * QUERIES_PER_FIELD_Q,
            "query_count": QUERY_COUNT,
            "independent_validation": False,
            "selection_note": "predictor regularization selected after prior analytic corpus inspection; all scores are diagnostic screens",
        },
        "composition": {
            "predictor_regularization_m": PREDICTOR_REGULARIZATION_M,
            "support_and_gate": "F4 v3 exact deterministic k=32 visible selection; fixed registered thresholds and estimator recomputed using candidate weights/prediction",
            "threshold_policy": "unchanged_registered_f4_gate",
            "gate_decisions_equal": totals["v3_pass_v6_fail"] == 0 and totals["v3_fail_v6_pass"] == 0,
        },
        "rows": rows,
        "by_q": by_q,
        "summary": {
            **totals,
            "gate_decisions_equal": totals["v3_pass_v6_fail"] == 0 and totals["v3_fail_v6_pass"] == 0,
            "by_field": by_field,
        },
        "exploratory_screen": exploratory_screen,
        "interpretation": {
            "scope": "synthetic analytic arrays only",
            "not_independent_validation": True,
            "not_native_or_event_validation": True,
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "execution": {
            "device": "CPU analytic arrays only",
            "numpy_version": np.__version__,
            "scipy_version": scipy.__version__,
            "native_started": False,
            "tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "code_bindings": {
            "candidate": {"path": "scripts/f4_supportcap_shepard_lowreg_candidate_v6.py", "sha256": _sha(Path(__file__).with_name("f4_supportcap_shepard_lowreg_candidate_v6.py"))},
            "calibration_script": {"path": "scripts/f4_supportcap_shepard_lowreg_calibration_v1.py", "sha256": _sha(Path(__file__))},
            "v3_candidate": {"path": "scripts/f4_supportcap_affine_query_bound_candidate_v3.py", "sha256": _sha(Path(__file__).with_name("f4_supportcap_affine_query_bound_candidate_v3.py"))},
            "core_material": {"path": "scripts/core_material.py", "sha256": _sha(Path(__file__).with_name("core_material.py"))},
            "visible_support": {"path": "scripts/f3_material_neighbors.py", "sha256": _sha(Path(__file__).with_name("f3_material_neighbors.py"))},
            "support_gate_metrics": {"path": "scripts/passive_tracers.py", "sha256": _sha(Path(__file__).with_name("passive_tracers.py"))},
            "calibration_helpers": {"path": "scripts/f4_material_calibration.py", "sha256": _sha(Path(__file__).with_name("f4_material_calibration.py"))},
            "calibration_definition": {"path": "scripts/f4_material_calibration_v3.py", "sha256": _sha(Path(__file__).with_name("f4_material_calibration_v3.py"))},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".partial")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
