"""Compare F4 v3, v4 and adaptive blend v5 on registered analytic arrays only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy

from scripts.core_material import GATE, f4_destination_region, f4_source_region, f4_walls
from scripts.f4_material_calibration import _box_lattice
from scripts.f4_material_calibration_v3 import (
    FIELD_IDS,
    Q_CASES,
    SUPPORT_SPACING_M,
    manufactured_velocity_v3,
    query_regions,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import sample_candidate as sample_v4
from scripts.f4_supportcap_affine_shepard_blend_candidate_v5 import (
    CANDIDATE_ID,
    sample_candidate as sample_v5,
)


SCHEMA = "core.material.f4.supportcap.affine_shepard_blend.calibration.v1"
QUERY_COUNT = 5632


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run() -> dict:
    rows: list[dict] = []
    sums = {
        field: {name: 0.0 for name in ("v3_sse", "v4_sse", "v5_sse", "count")}
        for field in FIELD_IDS
    }
    totals = {"queries": 0, "v3_pass": 0, "v4_pass": 0, "v5_pass": 0}
    maxima = {"v3": 0.0, "v4": 0.0, "v5": 0.0}
    alphas: list[np.ndarray] = []
    walls = f4_walls()
    limit = float(GATE["maximum_reconstruction_error_mps"])

    for q in Q_CASES:
        destination = f4_destination_region()
        source = f4_source_region(float(q))
        cloud = np.concatenate([
            _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
            _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
        ])
        for field_id in FIELD_IDS:
            cloud_velocity = manufactured_velocity_v3(cloud, field_id)
            for region, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v3(query, field_id)
                pred3, _, pass3, _ = sample_v3(cloud, cloud_velocity, query, walls)
                pred4, _, pass4, _ = sample_v4(cloud, cloud_velocity, query, walls)
                pred5, _, pass5, diag5 = sample_v5(cloud, cloud_velocity, query, walls)
                np.testing.assert_array_equal(pass3, pass4)
                np.testing.assert_array_equal(pass3, pass5)
                errors = {
                    "v3": np.linalg.norm(pred3 - truth, axis=1),
                    "v4": np.linalg.norm(pred4 - truth, axis=1),
                    "v5": np.linalg.norm(pred5 - truth, axis=1),
                }
                for name, error in errors.items():
                    maxima[name] = max(maxima[name], float(error.max(initial=0.0)))
                summary = sums[field_id]
                for name, error in errors.items():
                    summary[f"{name}_sse"] += float(np.dot(error, error))
                summary["count"] += len(query)
                alphas.append(np.asarray(diag5["blend_alpha"], dtype=np.float64))
                rows.append({
                    "q": float(q),
                    "field": field_id,
                    "region": region,
                    "query_count": len(query),
                    "v3_gate_pass_count": int(pass3.sum()),
                    "v4_gate_pass_count": int(pass4.sum()),
                    "v5_gate_pass_count": int(pass5.sum()),
                    **{f"{name}_truth_rmse_mps": float(np.sqrt(np.mean(error**2))) for name, error in errors.items()},
                    **{f"{name}_truth_max_error_mps": float(error.max(initial=0.0)) for name, error in errors.items()},
                    "v5_fixed_max_error_pass": bool(np.all(errors["v5"] <= limit)),
                    "v5_mean_blend_alpha": float(np.mean(diag5["blend_alpha"])) if len(query) else 0.0,
                })
                totals["queries"] += len(query)
                for name, passed in (("v3_pass", pass3), ("v4_pass", pass4), ("v5_pass", pass5)):
                    totals[name] += int(passed.sum())

    if totals["queries"] != QUERY_COUNT:
        raise AssertionError("held-out query denominator changed")
    by_field = {}
    for field, values in sums.items():
        count = int(values["count"])
        by_field[field] = {
            "query_count": count,
            **{f"{name}_truth_rmse_mps": float(np.sqrt(values[f"{name}_sse"] / count)) for name in ("v3", "v4", "v5")},
        }
    alpha_all = np.concatenate(alphas) if alphas else np.empty(0)
    return {
        "schema": SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "design": {"q_cases": list(Q_CASES), "fields": list(FIELD_IDS), "regions": ["source", "interface", "destination"], "query_count": QUERY_COUNT},
        "composition": {"fixed_gate": dict(GATE), "threshold_policy": "unchanged_registered_f4_gate", "v3_v4_v5_gate_decisions_equal": totals["v3_pass"] == totals["v4_pass"] == totals["v5_pass"]},
        "rows": rows,
        "summary": {
            **totals,
            "maximum_truth_error_mps": maxima,
            "v5_truth_error_within_fixed_maximum_all_queries": maxima["v5"] <= limit,
            "mean_blend_alpha": float(np.mean(alpha_all)) if alpha_all.size else 0.0,
            "by_field": by_field,
        },
        "interpretation": {
            "scope": "synthetic analytic-array screening only",
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
            "candidate": {"path": "scripts/f4_supportcap_affine_shepard_blend_candidate_v5.py", "sha256": _sha(Path(__file__).with_name("f4_supportcap_affine_shepard_blend_candidate_v5.py"))},
            "calibration_script": {"path": "scripts/f4_supportcap_affine_shepard_blend_calibration_v1.py", "sha256": _sha(Path(__file__))},
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
