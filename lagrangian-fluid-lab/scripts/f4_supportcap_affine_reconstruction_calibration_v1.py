"""Compare the F4 v4 affine predictor with F4 v3 on registered analytic arrays.

This is a deterministic synthetic-only diagnostic. It uses no native source,
HDF5, event tracer, solver, GPU, worker, queue, registry, or ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy

from scripts.core_material import (
    GATE,
    f4_destination_region,
    f4_source_region,
    f4_walls,
)
from scripts.f4_material_calibration import _box_lattice
from scripts.f4_material_calibration_v3 import (
    FIELD_IDS,
    Q_CASES,
    SUPPORT_SPACING_M,
    manufactured_velocity_v3,
    query_regions,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import (
    CANDIDATE_ID,
    sample_candidate as sample_v4,
)


SCHEMA = "core.material.f4.supportcap.local_affine_reconstruction.calibration.v1"
FIXED_DESIGN = {
    "q_cases": list(Q_CASES),
    "fields": list(FIELD_IDS),
    "regions": ["source", "interface", "destination"],
    "support_spacing_m": SUPPORT_SPACING_M,
    "query_count": 5632,
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run() -> dict:
    rows: list[dict] = []
    total_queries = 0
    total_v3_pass = 0
    total_v4_pass = 0
    all_v4_below_error_gate = True
    per_field_squared_error: dict[str, dict[str, float]] = {
        field: {"v3_sse": 0.0, "v4_sse": 0.0, "count": 0} for field in FIELD_IDS
    }
    maximum_v4_truth_error = 0.0
    walls = f4_walls()

    for q in Q_CASES:
        destination = f4_destination_region()
        source = f4_source_region(float(q))
        cloud = np.concatenate(
            [
                _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
                _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
            ]
        )
        for field_id in FIELD_IDS:
            cloud_velocity = manufactured_velocity_v3(cloud, field_id)
            for region, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v3(query, field_id)
                v3, _, pass_v3, diag_v3 = sample_v3(cloud, cloud_velocity, query, walls)
                v4, _, pass_v4, diag_v4 = sample_v4(cloud, cloud_velocity, query, walls)
                error_v3 = np.linalg.norm(v3 - truth, axis=1)
                error_v4 = np.linalg.norm(v4 - truth, axis=1)
                np.testing.assert_array_equal(pass_v4, pass_v3)
                np.testing.assert_allclose(
                    diag_v4["estimated_interpolation_error_mps"],
                    diag_v3["estimated_interpolation_error_mps"],
                    rtol=1e-12,
                    atol=1e-14,
                )
                gate_limit = float(GATE["maximum_reconstruction_error_mps"])
                all_v4_below_error_gate &= bool(np.all(error_v4 <= gate_limit))
                maximum_v4_truth_error = max(maximum_v4_truth_error, float(error_v4.max(initial=0.0)))
                field_summary = per_field_squared_error[field_id]
                field_summary["v3_sse"] += float(np.dot(error_v3, error_v3))
                field_summary["v4_sse"] += float(np.dot(error_v4, error_v4))
                field_summary["count"] += len(query)
                rows.append(
                    {
                        "q": float(q),
                        "field": field_id,
                        "region": region,
                        "query_count": len(query),
                        "v3_gate_pass_count": int(pass_v3.sum()),
                        "v4_gate_pass_count": int(pass_v4.sum()),
                        "v3_truth_rmse_mps": float(np.sqrt(np.mean(error_v3**2))),
                        "v4_truth_rmse_mps": float(np.sqrt(np.mean(error_v4**2))),
                        "v3_truth_max_error_mps": float(error_v3.max(initial=0.0)),
                        "v4_truth_max_error_mps": float(error_v4.max(initial=0.0)),
                        "v4_fixed_gate_error_pass": bool(np.all(error_v4 <= gate_limit)),
                    }
                )
                total_queries += len(query)
                total_v3_pass += int(pass_v3.sum())
                total_v4_pass += int(pass_v4.sum())

    if total_queries != FIXED_DESIGN["query_count"]:
        raise AssertionError("held-out query denominator changed")
    summary: dict[str, dict[str, float]] = {}
    for field, value in per_field_squared_error.items():
        count = int(value["count"])
        summary[field] = {
            "query_count": count,
            "v3_truth_rmse_mps": float(np.sqrt(value["v3_sse"] / count)),
            "v4_truth_rmse_mps": float(np.sqrt(value["v4_sse"] / count)),
        }
    return {
        "schema": SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "design": FIXED_DESIGN,
        "composition": {
            "support_cap": 32,
            "regularization_m": 0.004,
            "maximum_support_distance_m": 0.03,
            "fixed_gate": dict(GATE),
            "v3_gate_decisions_preserved": total_v4_pass == total_v3_pass,
        },
        "rows": rows,
        "summary": {
            "total_queries": total_queries,
            "v3_gate_pass_count": total_v3_pass,
            "v4_gate_pass_count": total_v4_pass,
            "v4_truth_error_within_fixed_maximum_all_queries": all_v4_below_error_gate,
            "maximum_v4_truth_error_mps": maximum_v4_truth_error,
            "by_field": summary,
        },
        "interpretation": {
            "scope": "synthetic analytic-array screening only",
            "known_tradeoff": "local affine reconstruction improves the quintic shear field but is less accurate than Shepard near the Gaussian interface; both remain below the frozen maximum on these queries",
            "native_or_event_validation": False,
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
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "code_bindings": {
            "candidate": {
                "path": "scripts/f4_supportcap_affine_reconstruction_candidate_v4.py",
                "sha256": _sha(Path(__file__).with_name("f4_supportcap_affine_reconstruction_candidate_v4.py")),
            },
            "calibration_script": {"path": "scripts/f4_supportcap_affine_reconstruction_calibration_v1.py", "sha256": _sha(Path(__file__))},
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
