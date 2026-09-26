"""Prospective synthetic stress set for the frozen F4 v5 blend.

The field is a smooth divergence-free box mode that vanishes on every box
face. The q values are audited against pinned prior calibration profiles,
candidate receipts, and the superseded unscored v1 holdout design. This is
still only a prospective synthetic stress test, not external validation,
physical F4 flow validation, or qualification.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import platform
import resource
import time
from typing import Any

import numpy as np
import scipy

from scripts import core_material
from scripts import f4_supportcap_affine_shepard_blend_heldout_v1 as heldout_v1_helpers
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import (
    CANDIDATE_ID as BASELINE_ID,
    sample_candidate as sample_v3,
)
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import sample_candidate as sample_v4
from scripts.f4_supportcap_affine_shepard_blend_candidate_v5 import (
    CANDIDATE_ID as CANDIDATE_ID_V5,
    sample_candidate as sample_v5,
)


SCHEMA = "core.material.f4.supportcap.affine_shepard_blend.heldout.v2"
RECEIPT_SCHEMA = "core.material.f4.supportcap.affine_shepard_blend.heldout_receipt.v2"
REVISION = "f4-v5-prospective-box-mode-holdout-20260926-v2-review1"
Q_CASES = (0.05, 0.975)
FIELD_ID = "closed_box_divergence_free_streamfunction_mode"
STREAMFUNCTION_AMPLITUDE_M2PS = 0.025
X_LENGTH_M = 1.2
Y_LENGTH_M = 0.4
Z_HEIGHT_M = 0.6
SOURCE_UNKNOWN_LIMIT = 0.01
FIXED_SYNTHETIC_TRUTH_ERROR_LIMIT_MPS = heldout_v1_helpers.MAXIMUM_TRUTH_ERROR_MPS
EXPECTED_QUERY_COUNT = heldout_v1_helpers.EXPECTED_QUERY_COUNT
REPO_ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_PROFILE_PATHS = {
    "f4_calibration_profile_v1": REPO_ROOT / "scripts/f4_material_calibration.py",
    "f4_calibration_profile_v2": REPO_ROOT / "scripts/f4_material_calibration_v2.py",
    "f4_calibration_profile_v3": REPO_ROOT / "scripts/f4_material_calibration_v3.py",
}
HISTORICAL_Q_JSON_PATHS = {
    "f4_v3_candidate_card_v2": REPO_ROOT / "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3/candidate-card-v2.json",
    "f4_v5_calibration_receipt_v1": REPO_ROOT / "campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/receipt.json",
    "f4_v6_calibration_receipt_v1": REPO_ROOT / "campaigns/core-v1/material/candidates/f4-supportcap-shepard-lowreg-predictor-v6/synthetic-calibration-v1/receipt.json",
    "f4_v6_calibration_receipt_v2": REPO_ROOT / "campaigns/core-v1/material/candidates/f4-supportcap-shepard-lowreg-predictor-v6/synthetic-calibration-v2/receipt.json",
    "superseded_unscored_heldout_design_v1": REPO_ROOT / "campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-design-v1.json",
}


def _code_bindings() -> dict[str, dict[str, str]]:
    paths = {
        "validation_script": Path(__file__).resolve(),
        "heldout_v1_shared_helpers": Path(heldout_v1_helpers.__file__).resolve(),
        "v3_baseline": Path(sample_v3.__code__.co_filename).resolve(),
        "v4_affine_component": Path(sample_v4.__code__.co_filename).resolve(),
        "v5_candidate": Path(sample_v5.__code__.co_filename).resolve(),
        "f4_geometry_and_gate": Path(core_material.__file__).resolve(),
        "neighbor_search": REPO_ROOT / "scripts/f3_material_neighbors.py",
        "support_gate": REPO_ROOT / "scripts/passive_tracers.py",
        "calibration_geometry_helpers": Path(heldout_v1_helpers._box_lattice.__code__.co_filename).resolve(),
        **CALIBRATION_PROFILE_PATHS,
        "requirements": REPO_ROOT / "requirements.txt",
        "validation_tests": REPO_ROOT / "tests/test_f4_supportcap_affine_shepard_blend_heldout_v2.py",
    }
    return {
        role: {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": heldout_v1_helpers._sha256_file(path),
        }
        for role, path in paths.items()
    }


def _audit_source_bindings() -> dict[str, dict[str, str]]:
    return {
        role: {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": heldout_v1_helpers._sha256_file(path),
        }
        for role, path in HISTORICAL_Q_JSON_PATHS.items()
    }


def _module_q_cases(path: Path, name: str) -> list[float]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            if isinstance(value, (tuple, list)) and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in value
            ):
                return [float(item) for item in value]
    raise ValueError(f"could not read frozen q profile {name} from {path}")


def _json_q_cases(path: Path) -> list[float]:
    document = json.loads(path.read_text(encoding="utf-8"))
    values: list[float] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, value in item.items():
                if key in {"q_cases", "original_q_cases", "supplemental_diagnostic_q_cases"}:
                    if not isinstance(value, list):
                        raise ValueError(f"invalid frozen q list {key} in {path}")
                    if any(
                        isinstance(q, bool) or not isinstance(q, (int, float))
                        for q in value
                    ):
                        raise ValueError(f"non-numeric frozen q value in {path}")
                    values.extend(float(q) for q in value)
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(document)
    if not values:
        raise ValueError(f"no frozen q values found in {path}")
    return sorted(set(values))


def _q_domain_audit() -> dict[str, Any]:
    q_sets = {
        "f4_calibration_profile_v1": _module_q_cases(CALIBRATION_PROFILE_PATHS["f4_calibration_profile_v1"], "DEFAULT_Q"),
        "f4_calibration_profile_v2": _module_q_cases(CALIBRATION_PROFILE_PATHS["f4_calibration_profile_v2"], "Q_CASES"),
        "f4_calibration_profile_v3": _module_q_cases(CALIBRATION_PROFILE_PATHS["f4_calibration_profile_v3"], "Q_CASES"),
    }
    q_sets.update({
        role: _json_q_cases(path)
        for role, path in HISTORICAL_Q_JSON_PATHS.items()
    })
    prior_q_values = {q for values in q_sets.values() for q in values}
    overlaps = sorted(set(Q_CASES) & prior_q_values)
    if overlaps:
        raise ValueError(f"heldout q values overlap pinned prior F4 records: {overlaps}")
    return {
        "q_cases": list(Q_CASES),
        "prior_q_cases_by_source": q_sets,
        "disjoint_from_pinned_prior_records": True,
        "scope": "repository-pinned profile and receipt audit only; not an external independence claim",
        "superseded_unscored_heldout_design_v1_was_included": True,
    }


def design() -> dict[str, Any]:
    """Return the exact, pre-scoring protocol and complete source closure."""
    return {
        "schema": SCHEMA,
        "revision_id": REVISION,
        "purpose": "prospective synthetic stress evaluation of unchanged F4 v5",
        "holdout_status": "prospective_unscored_synthetic_stress_set_not_external_independent_validation",
        "qualification_claim": "none",
        "credit": 0,
        "candidates": {
            "baseline": BASELINE_ID,
            "candidate": CANDIDATE_ID_V5,
            "candidate_parameters_fitted_for_this_set": False,
            "thresholds_or_candidate_parameters_may_change_after_scoring": False,
            "rmse_non_regression_required": False,
            "predictor_superiority_claim": False,
        },
        "geometry": {
            "q_cases": list(Q_CASES),
            "q_domain_audit": _q_domain_audit(),
            "support_spacing_m": heldout_v1_helpers.SUPPORT_SPACING_M,
            "source_queries": {"count": heldout_v1_helpers.SOURCE_QUERY_COUNT, "generator": "core_material.seeds_f4"},
            "interface_queries": {
                "low_m": list(heldout_v1_helpers.INTERFACE_LOW_M),
                "size_m": list(heldout_v1_helpers.INTERFACE_SIZE_M),
                "counts": list(heldout_v1_helpers.INTERFACE_COUNTS),
            },
            "destination_queries": {"counts": list(heldout_v1_helpers.DESTINATION_COUNTS)},
            "support_cloud": "union_of_destination_and_q_specific_source_cell_center_lattices",
            "expected_query_count": EXPECTED_QUERY_COUNT,
            "reuse_limitation": "same F4 geometry and sampling rules; not an independent physical case",
        },
        "held_out_field": {
            "id": FIELD_ID,
            "streamfunction": "A*sin(pi*x/Lx)^2*sin(pi*y/Ly)^2*sin(pi*z/H)^2",
            "streamfunction_amplitude_m2ps": STREAMFUNCTION_AMPLITUDE_M2PS,
            "domain_lengths_m": {"x": X_LENGTH_M, "y": Y_LENGTH_M, "z": Z_HEIGHT_M},
            "velocity": {
                "u_x": "A*(pi/H)*sin(pi*x/Lx)^2*sin(pi*y/Ly)^2*sin(2*pi*z/H)",
                "u_y": "0",
                "u_z": "-A*(pi/Lx)*sin(2*pi*x/Lx)*sin(pi*y/Ly)^2*sin(pi*z/H)^2",
            },
            "analytic_invariants": [
                "divergence_free_in_xz",
                "zero_velocity_on_x_faces",
                "zero_velocity_on_y_faces",
                "zero_velocity_on_z_faces",
            ],
            "physical_scope": "manufactured interpolation field only; not a DualSPHysics solution",
        },
        "acceptance": {
            "gate_decisions_must_match_v3_exactly": True,
            "support_distance_must_match_v3_exactly": True,
            "maximum_source_unknown_fraction": SOURCE_UNKNOWN_LIMIT,
            "source_unknown_limit_basis": "existing F4 synthetic calibration denominator policy",
            "fixed_synthetic_truth_error_screen_limit_mps": FIXED_SYNTHETIC_TRUTH_ERROR_LIMIT_MPS,
            "truth_error_limit_semantics": "hard pass condition for this synthetic screen only; not the registered gate error estimator",
            "rmse": "reported by q and region; diagnostic only; no non-regression requirement",
            "fixed_denominator": EXPECTED_QUERY_COUNT,
            "nonfinite_prediction": "fails screen; row remains in denominator",
            "screen_pass_interpretation": "mechanical synthetic screen only; not candidate superiority or preflight authorization",
        },
        "resource_gate": {
            "schema": heldout_v1_helpers.LOAD_GATE_SCHEMA,
            "maximum_one_minute_load": "process_visible_cpu_count",
            "load_gate_precedes_cloud_and_query_construction": True,
        },
        "execution_boundary": {
            "analytic_arrays_only": True,
            "native_or_tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "code_bindings": _code_bindings(),
        "audit_source_bindings": _audit_source_bindings(),
    }


def design_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(heldout_v1_helpers._canonical(value)).hexdigest()


def verify_design(value: dict[str, Any]) -> None:
    if value != design():
        raise ValueError("v2 holdout design differs from its frozen protocol or complete code closure")


def _box_mode_velocity(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("points must be finite with shape [N,3]")
    x, y, z = points.T
    kx = np.pi / X_LENGTH_M
    ky = np.pi / Y_LENGTH_M
    kz = np.pi / Z_HEIGHT_M
    sin_x = np.sin(kx * x)
    sin_y = np.sin(ky * y)
    sin_z = np.sin(kz * z)
    ux = STREAMFUNCTION_AMPLITUDE_M2PS * kz * sin_x**2 * sin_y**2 * np.sin(2.0 * kz * z)
    uz = -STREAMFUNCTION_AMPLITUDE_M2PS * kx * np.sin(2.0 * kx * x) * sin_y**2 * sin_z**2
    return np.column_stack((ux, np.zeros_like(ux), uz))


def _error_record(prediction: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    return heldout_v1_helpers._error_summary(prediction, truth)


def _evaluate(design_record: dict[str, Any], load_one: float, cpu_capacity: int) -> dict[str, Any]:
    verify_design(design_record)
    heldout_v1_helpers.check_load_gate(load_one, cpu_capacity)
    start = time.monotonic()
    rows: list[dict[str, Any]] = []
    gate_equal = True
    support_distance_equal = True
    source_coverage_pass = True
    synthetic_truth_screen_pass = True
    all_v3_errors: list[np.ndarray] = []
    all_v5_errors: list[np.ndarray] = []
    totals = {"query_count": 0, "v3_gate_pass_count": 0, "v5_gate_pass_count": 0}
    walls = core_material.f4_walls()

    for q in Q_CASES:
        cloud = heldout_v1_helpers._support_cloud(q)
        cloud_velocity = _box_mode_velocity(cloud)
        cloud_sha256 = heldout_v1_helpers._array_sha256(cloud)
        for region, query in heldout_v1_helpers._query_regions(q).items():
            truth = _box_mode_velocity(query)
            prediction_v3, support_v3, pass_v3, _ = sample_v3(cloud, cloud_velocity, query, walls)
            prediction_v5, support_v5, pass_v5, _ = sample_v5(cloud, cloud_velocity, query, walls)
            same_gate = bool(np.array_equal(pass_v3, pass_v5))
            same_support_distance = bool(np.array_equal(support_v3, support_v5))
            gate_equal &= same_gate
            support_distance_equal &= same_support_distance

            v3_error = np.linalg.norm(prediction_v3 - truth, axis=1)
            v5_error = np.linalg.norm(prediction_v5 - truth, axis=1)
            all_v3_errors.append(v3_error)
            all_v5_errors.append(v5_error)
            v3_summary = _error_record(prediction_v3, truth)
            v5_summary = _error_record(prediction_v5, truth)
            source_unknown_fraction = (1.0 - float(pass_v3.mean())) if region == "source" else None
            source_pass = (
                source_unknown_fraction <= SOURCE_UNKNOWN_LIMIT if source_unknown_fraction is not None else None
            )
            if source_pass is not None:
                source_coverage_pass &= source_pass
            synthetic_truth_screen_pass &= v5_summary["within_fixed_truth_error_limit"]
            rmse_v3 = v3_summary["truth_vector_rmse_mps"]
            rmse_v5 = v5_summary["truth_vector_rmse_mps"]
            rows.append({
                "q": q,
                "field": FIELD_ID,
                "region": region,
                "cloud_count": int(len(cloud)),
                "cloud_sha256": cloud_sha256,
                "query_count": int(len(query)),
                "query_sha256": heldout_v1_helpers._array_sha256(query),
                "truth_sha256": heldout_v1_helpers._array_sha256(truth),
                "v3_gate_pass_count": int(pass_v3.sum()),
                "v5_gate_pass_count": int(pass_v5.sum()),
                "gate_decisions_equal": same_gate,
                "support_distance_equal": same_support_distance,
                "source_unknown_fraction": source_unknown_fraction,
                "source_coverage_pass": source_pass,
                "v3": v3_summary,
                "v5": v5_summary,
                "v5_minus_v3_rmse_mps": rmse_v5 - rmse_v3 if rmse_v5 is not None and rmse_v3 is not None else None,
                "v5_relative_rmse_change_pct": (
                    100.0 * (rmse_v5 / rmse_v3 - 1.0)
                    if rmse_v3 is not None and rmse_v5 is not None and rmse_v3 > 0.0 else None
                ),
            })
            totals["query_count"] += len(query)
            totals["v3_gate_pass_count"] += int(pass_v3.sum())
            totals["v5_gate_pass_count"] += int(pass_v5.sum())

    if totals["query_count"] != EXPECTED_QUERY_COUNT:
        raise AssertionError("the fixed v2 holdout denominator changed")
    v3_all = np.concatenate(all_v3_errors)
    v5_all = np.concatenate(all_v5_errors)
    predictions_finite = bool(np.isfinite(v3_all).all() and np.isfinite(v5_all).all())
    v3_rmse = float(np.sqrt(np.mean(v3_all**2))) if predictions_finite else None
    v5_rmse = float(np.sqrt(np.mean(v5_all**2))) if predictions_finite else None
    screen_conditions_pass = bool(
        predictions_finite and gate_equal and support_distance_equal
        and source_coverage_pass and synthetic_truth_screen_pass
    )
    return {
        "schema": RECEIPT_SCHEMA,
        "design_schema": SCHEMA,
        "design_revision": REVISION,
        "design_sha256": design_sha256(design_record),
        "candidate_id": CANDIDATE_ID_V5,
        "baseline_id": BASELINE_ID,
        "design": design_record,
        "rows": rows,
        "summary": {
            **totals,
            "all_predictions_finite": predictions_finite,
            "gate_decisions_equal": gate_equal,
            "support_distance_equal": support_distance_equal,
            "source_coverage_pass": source_coverage_pass,
            "synthetic_truth_error_screen_pass": synthetic_truth_screen_pass,
            "fixed_synthetic_screen_conditions_pass": screen_conditions_pass,
            "v3_all_query_truth_vector_rmse_mps": v3_rmse,
            "v5_all_query_truth_vector_rmse_mps": v5_rmse,
            "v5_relative_rmse_change_pct": (
                float((v5_rmse / v3_rmse - 1.0) * 100.0)
                if v3_rmse is not None and v5_rmse is not None and v3_rmse > 0.0 else None
            ),
            "predictor_superiority_claim": False,
            "preflight_recommendation": (
                "requires_independent_review_before_any_authorized_preflight"
                if screen_conditions_pass else "not_justified"
            ),
        },
        "interpretation": {
            "scope": "prospective synthetic analytic-array stress set only",
            "external_independent_validation": False,
            "physical_f4_flow_validation": False,
            "native_or_event_validation": False,
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "execution": {
            "device": "CPU analytic arrays only",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "one_minute_load_at_start": float(load_one),
            "process_visible_cpu_capacity": int(cpu_capacity),
            "elapsed_seconds": float(time.monotonic() - start),
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "native_or_tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "code_bindings": design_record["code_bindings"],
        "audit_source_bindings": design_record["audit_source_bindings"],
    }


def run(design_record: dict[str, Any]) -> dict[str, Any]:
    verify_design(design_record)
    load_one, cpu_capacity = heldout_v1_helpers._load_snapshot()
    return _evaluate(design_record, load_one, cpu_capacity)


def design_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(heldout_v1_helpers._canonical(value)).hexdigest()


def verify_design(value: dict[str, Any]) -> None:
    if value != design():
        raise ValueError("v2 holdout design differs from its frozen protocol or complete code closure")


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    design_parser = subparsers.add_parser("design")
    design_parser.add_argument("--output", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--design", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "design":
        value = design()
        _write_new_json(args.output, value)
        print(json.dumps({"status": "design_frozen", "design_sha256": design_sha256(value), "path": str(args.output)}, sort_keys=True))
        return 0
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
    if not args.output.parent.is_dir():
        raise FileNotFoundError(f"parent directory does not exist: {args.output.parent}")
    try:
        result = run(json.loads(args.design.read_text(encoding="utf-8")))
    except heldout_v1_helpers.ProfileDeferred as exc:
        print(json.dumps({"status": "deferred_resource_gate", "profile_started": False, "reason": str(exc)}, sort_keys=True))
        return 2
    _write_new_json(args.output, result)
    print(json.dumps({"status": "completed_synthetic_only", "receipt": str(args.output), "summary": result["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
