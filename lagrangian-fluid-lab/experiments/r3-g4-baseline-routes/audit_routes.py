#!/usr/bin/env python3
"""Audit the R3 G4 route/input contract without changing the trainer.

The corrected trainer already contains the direct Particle MLP, global
DeepSets, local-neighbour, and physics-residual routes.  This sidecar audit
keeps the audit independent from the trainer's generated aggregate files: it
loads the release manifest, checks the feature contract at runtime, and
indexes the existing sidecar-aware result matrix.  It is intentionally a
development/candidate diagnostic, not a leaderboard or physical acceptance
gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import torch


LAB = Path(__file__).resolve().parents[2]
BASELINE = LAB / "experiments" / "r3_g4_baselines.py"
RELEASE_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
EXISTING_RESULTS = LAB / "experiments" / "r3_g4_sidecar_results"
EXISTING_RUN_MANIFEST = LAB / "experiments" / "r3_g4_sidecar_run_manifest.json"
ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
SEEDS = (17, 29, 43)


def load_baseline_module():
    """Load the trainer by path so this script is cwd-independent."""

    spec = importlib.util.spec_from_file_location("r3_g4_baselines_route_audit", BASELINE)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load baseline trainer: {BASELINE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result_index() -> dict[str, Any]:
    """Index the already committed sidecar-aware matrix by route and seed."""

    records: dict[str, Any] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for route in ROUTES:
        for seed in SEEDS:
            key = f"{route}_seed{seed}"
            path = EXISTING_RESULTS / f"{key}.json"
            if not path.is_file():
                missing.append(str(path.relative_to(LAB)))
                continue
            try:
                payload = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                invalid.append(str(path.relative_to(LAB)))
                continue
            expected = {
                "route": route,
                "seed": seed,
                "feature_width": 43,
                "scope": "R3-G4 corrected development baseline",
            }
            if any(payload.get(field) != value for field, value in expected.items()):
                invalid.append(str(path.relative_to(LAB)))
            test_rollout = payload.get("test_rollout", {})
            if not test_rollout or any(
                value.get("status") != "completed" for value in test_rollout.values()
            ):
                invalid.append(f"{path.relative_to(LAB)}:incomplete_test_rollout")
            records[key] = {
                "path": str(path.relative_to(LAB)),
                "route": route,
                "seed": seed,
                "device": payload.get("device"),
                "feature_width": payload.get("feature_width"),
                "epochs_run": payload.get("epochs_run"),
                "test_cases": len(test_rollout),
                "test_rollout_statuses": {
                    case_id: rollout.get("status")
                    for case_id, rollout in test_rollout.items()
                },
            }
    return {
        "expected_count": len(ROUTES) * len(SEEDS),
        "found_count": len(records),
        "missing": missing,
        "invalid": invalid,
        "records": records,
    }


def audit_contract(
    manifest_path: Path = RELEASE_MANIFEST,
    results_dir: Path = EXISTING_RESULTS,
    run_manifest_path: Path = EXISTING_RUN_MANIFEST,
) -> dict[str, Any]:
    """Return a JSON-safe audit of routes, inputs, and seed coverage."""

    module = load_baseline_module()
    manifest_path = manifest_path.resolve()
    cases = module.load_cases(manifest_path)
    case_by_id = {case["case_id"]: case for case in cases}
    split_counts = Counter(case["split"] for case in cases)
    required_case_fields = {
        "position",
        "velocity",
        "density0",
        "pressure0",
        "mass0",
        "time",
        "dp",
        "length_scale",
        "time_scale",
        "gravity",
        "physics",
        "controls",
        "boundary_by_frame",
        "boundary_source",
        "boundary_available",
    }
    field_failures = {
        case_id: sorted(required_case_fields.difference(case))
        for case_id, case in case_by_id.items()
        if required_case_fields.difference(case)
    }

    route_widths: dict[str, dict[str, int]] = {}
    for route in ROUTES:
        model = module.model_for(route, module.feature_width(), 8)
        with torch.no_grad():
            features = torch.zeros((2, module.feature_width()))
            local = (
                torch.zeros((2, module.LOCAL_WIDTH))
                if route == "local_interaction"
                else None
            )
            output = module.predict(model, route, features, local)
        route_widths[route] = {
            "input_width": module.feature_width(),
            "local_width": module.LOCAL_WIDTH if route == "local_interaction" else 0,
            "output_width": int(output.shape[-1]),
            "parameter_count": int(sum(p.numel() for p in model.parameters())),
        }

    control_sources = Counter(case["control_source"] for case in cases)
    boundary_sources = Counter(case["boundary_source"] for case in cases)
    physics_widths = sorted({int(case["physics"].shape[-1]) for case in cases})
    control_widths = sorted({int(case["controls"].shape[-1]) for case in cases})
    boundary_widths = sorted({int(case["boundary_by_frame"].shape[-1]) for case in cases})
    sidecar_schema = sorted(
        {
            str(case["boundary_provenance"].get("schema_version"))
            for case in cases
            if case.get("boundary_provenance")
        }
    )
    all_boundary_frames_match = all(
        case["boundary_by_frame"].shape[0] == case["position"].shape[0]
        for case in cases
    )
    all_finite = all(
        np.isfinite(case[field]).all()
        for case in cases
        for field in ("position", "velocity", "density0", "pressure0", "mass0", "time", "physics", "controls", "boundary_by_frame")
    )
    # The release loader intentionally filters cases without fluid slots.  Keep
    # the excluded body-only case visible as an explicit audit finding.
    manifest_records = json.loads(manifest_path.read_text()).get("cases", [])
    manifest_case_ids = {record["case_id"] for record in manifest_records}
    excluded_case_ids = sorted(manifest_case_ids.difference(case_by_id))

    results = _result_index()
    # The argument is useful for tests and for callers that point at a copied
    # result directory; recompute only the paths, not the semantics.
    if results_dir.resolve() != EXISTING_RESULTS.resolve():
        old_results = EXISTING_RESULTS
        try:
            globals()["EXISTING_RESULTS"] = results_dir.resolve()
            results = _result_index()
        finally:
            globals()["EXISTING_RESULTS"] = old_results

    execution_manifest: dict[str, Any] | None = None
    if run_manifest_path.is_file():
        try:
            execution_manifest = json.loads(run_manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            execution_manifest = None

    checks = {
        "four_routes_construct_and_emit_xyz": all(
            value["input_width"] == 43
            and value["output_width"] == 3
            and (value["local_width"] == 8) == (route == "local_interaction")
            for route, value in route_widths.items()
        ),
        "shared_feature_width": len({value["input_width"] for value in route_widths.values()}) == 1,
        "canonical_state_fields_present": not field_failures,
        "control_width_and_boundary_width_stable": control_widths == [10] and boundary_widths == [7],
        "physics_width_stable": physics_widths == [3],
        "boundary_sidecars_current_frame_aligned": bool(
            cases and all_boundary_frames_match and all(case["boundary_available"] for case in cases)
        ),
        "all_loaded_values_finite": all_finite,
        "three_seed_matrix_complete": not results["missing"]
        and not results["invalid"]
        and results["found_count"] == results["expected_count"],
        "body_only_case_explicitly_excluded": "W05_F6_fine" in excluded_case_ids,
        "candidate_only_not_formal": True,
    }

    return {
        "schema_version": 1,
        "scope": "R3-G4 candidate-only baseline route and input-contract audit",
        "status": "complete" if all(checks.values()) else "failed",
        "formal_ready": False,
        "baseline_source": str(BASELINE.relative_to(LAB)),
        "release_manifest": str(manifest_path.relative_to(LAB))
        if manifest_path.is_relative_to(LAB)
        else str(manifest_path),
        "routes": list(ROUTES),
        "route_roles": {
            "particle_mlp": "direct per-particle predictor",
            "deepset_context": "global permutation-invariant set context",
            "local_interaction": "direct predictor plus inverse-distance local neighbour summary",
            "physics_residual": "normalized acceleration residual integrated with current velocity",
        },
        "seeds": list(SEEDS),
        "cases": {
            "loaded_fluid_case_count": len(cases),
            "split_counts": dict(sorted(split_counts.items())),
            "excluded_manifest_case_ids": excluded_case_ids,
            "field_failures": field_failures,
        },
        "feature_contract": {
            "feature_width": module.feature_width(),
            "slices": {
                "centered_xyz": [0, 3],
                "target_velocity_scaled": [3, 6],
                "context_com_velocity_scaled": [6, 9],
                "initial_density_pressure_mass": [9, 12],
                "gravity": [12, 15],
                "static_physics": [15, 18],
                "current_prescribed_control": [18, 28],
                "current_boundary_summary": [28, 35],
                "family_one_hot": [35, 41],
                "elapsed_time_and_dt": [41, 43],
            },
            "state_semantics": {
                "density_pressure_mass": "initial-only; no future reference fields in rollout",
                "velocity": "solver velocity under teacher forcing; own predicted next velocity in rollout",
                "control": "current prescribed schedule; frame-zero transform velocity is zero",
                "boundary": "current frame finite-triangle world-space AABB plus availability bit",
                "free_body": "not exposed; body-only F6 fluid-less case excluded",
            },
            "route_widths": route_widths,
            "control_sources": dict(sorted(control_sources.items())),
            "boundary_sources": dict(sorted(boundary_sources.items())),
            "boundary_sidecar_schemas": sidecar_schema,
            "physics_widths": physics_widths,
        },
        "existing_matrix": results,
        "existing_run_manifest": {
            "path": str(run_manifest_path.relative_to(LAB))
            if run_manifest_path.is_relative_to(LAB)
            else str(run_manifest_path),
            "status": execution_manifest.get("status") if execution_manifest else "unavailable",
            "allowed_gpu_indices": execution_manifest.get("allowed_gpu_indices")
            if execution_manifest
            else None,
        },
        "checks": checks,
        "limitations": [
            "candidate-only diagnostic; no leaderboard or physical-scene acceptance claim",
            "material transport, density/pressure prediction, free-body coupling, and T2/T3/T4 scoring are not included",
            "boundary input is an AABB summary, not a learned wall-contact operator",
            "existing matrix is indexed for contract coverage; independent small reruns are recorded separately",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=RELEASE_MANIFEST)
    parser.add_argument("--results-dir", type=Path, default=EXISTING_RESULTS)
    parser.add_argument("--run-manifest", type=Path, default=EXISTING_RUN_MANIFEST)
    args = parser.parse_args()
    report = audit_contract(args.manifest, args.results_dir, args.run_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "checks": report["checks"]}, indent=2))
    if report["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
