#!/usr/bin/env python3
"""Read-only terminal forensics and pair comparison for the F2 DBC canary.

The comparison pair is the original full-cup CFL=.20 mDBC run.  The earlier
CFL=.10 mDBC run is recorded as negative evidence and is deliberately rejected
as the pair baseline.  This script reads solver products only; it never starts
a solver, edits a product, or changes qualification gates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.dbc_boundary_result_forensics.v1"
PAIR_CONFIG_KEYS = (
    "dp_m",
    "time_max_s",
    "maximum_extended_time_s",
    "output_interval_s",
    "angle_degrees",
    "motion_start_s",
    "runtime_domain",
    "wall_bounds",
    "cup",
    "receiver",
    "tray",
    "catchment",
    "catchment_wall_spec",
    "parameter",
    "event_window",
    "initial_condition",
    "fluid_boxes",
    "sampling_rule",
    "static_hold",
    "source_geometry_contract",
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _product(product: Path) -> dict[str, Any]:
    product = Path(product).resolve()
    result_path = product / "result.json"
    audit_path = product / "audit.json"
    observations_path = product / "observations.json"
    result = _json(result_path)
    audit = _json(audit_path)
    observations = _json(observations_path)
    return {
        "product": str(product),
        "result_path": str(result_path),
        "audit_path": str(audit_path),
        "observations_path": str(observations_path),
        "result_sha256": _sha256(result_path),
        "audit_sha256": _sha256(audit_path),
        "observations_sha256": _sha256(observations_path),
        "result": result,
        "audit": audit,
        "observations": observations,
    }


def _failed_checks(audit: dict[str, Any]) -> list[str]:
    return sorted(key for key, value in audit.get("hard_checks", {}).items() if value is not True)


def _geometry_summary(audit: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, value in audit.get("geometry_audit", {}).items():
        if not isinstance(value, dict):
            continue
        summary[name] = {
            key: value.get(key)
            for key in (
                "endpoint_particle_frames",
                "endpoint_mass_kg",
                "saved_chord_crossings",
                "saved_chord_closed_face_entries",
                "first_endpoint_violation",
                "first_saved_chord_crossing",
                "first_saved_chord_closed_face_entry",
            )
            if key in value
        }
    return summary


def _terminal_observations(observations: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "time_s",
        "cup_mass_fraction",
        "receiver_mass_fraction",
        "tray_mass_fraction",
        "outside_observation_mass_fraction",
        "kinetic_energy_over_initial_potential",
        "speed_p95_m_s",
    ):
        values = observations.get(key)
        if isinstance(values, list) and values:
            result[key] = values[-1]
    result["event_times_s"] = observations.get("event_times_s")
    result["requested_horizon_reached"] = observations.get("requested_horizon_reached")
    result["event_window_complete"] = observations.get("event_window_complete")
    return result


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    result = case["result"]
    audit = case["audit"]
    observations = case["observations"]
    identity = audit.get("identity_audit", result.get("identity_audit", {}))
    return {
        "product": case["product"],
        "result_sha256": case["result_sha256"],
        "audit_sha256": case["audit_sha256"],
        "observations_sha256": case["observations_sha256"],
        "case_id": result.get("case_id", audit.get("case_id")),
        "prepared_sha256": result.get("prepared_sha256", audit.get("prepared_sha256")),
        "hard_integrity_pass": result.get("hard_integrity_pass", audit.get("hard_integrity_pass")),
        "event_window_complete": result.get("event_window_complete", audit.get("event_window_complete")),
        "requested_horizon_reached": result.get("requested_horizon_reached", audit.get("requested_horizon_reached")),
        "qualification_claim": result.get("qualification_claim", audit.get("qualification_claim")),
        "qualified": result.get("qualified", audit.get("qualified")),
        "failed_hard_checks": _failed_checks(audit),
        "identity": {
            key: identity.get(key)
            for key in (
                "particle_count",
                "initial_valid_particle_count",
                "expected_initial_fluid_particles",
                "missing_native_fluid_id_count",
                "minimum_active_mass_fraction",
                "native_mass_policy",
            )
            if key in identity
        },
        "geometry": _geometry_summary(audit),
        "terminal_observations": _terminal_observations(observations),
    }


def _pair_config(prepared: dict[str, Any], baseline_prepared: dict[str, Any]) -> dict[str, Any]:
    config = prepared.get("config", {})
    baseline_config = baseline_prepared.get("config", {})
    mismatches = {}
    for key in PAIR_CONFIG_KEYS:
        left, right = config.get(key), baseline_config.get(key)
        if left != right:
            mismatches[key] = {"dbc": left, "mdbc": right}
    sampling_mismatches = {}
    for key in ("fluid_boxes", "expected_fluid_particles", "continuous_mass_kg", "sampled_mass_kg", "mass_policy"):
        left, right = prepared.get("sampling", {}).get(key), baseline_prepared.get("sampling", {}).get(key)
        if left != right:
            sampling_mismatches[key] = {"dbc": left, "mdbc": right}
    return {
        "pair_contract_pass": not mismatches and not sampling_mismatches,
        "geometry_and_initial_mismatches": mismatches,
        "sampling_mismatches": sampling_mismatches,
        "dbc": {
            "boundary_method": config.get("boundary_method"),
            "recipe": config.get("recipe"),
            "cfl": config.get("cfl"),
            "prepared_sha256": _sha256(Path(prepared["_path"])),
        },
        "mdbc": {
            "boundary_method": baseline_config.get("boundary_method"),
            "recipe": baseline_config.get("recipe"),
            "cfl": baseline_config.get("cfl"),
            "prepared_sha256": _sha256(Path(baseline_prepared["_path"])),
        },
        "expected_single_variable_change": {
            "boundary_method": [baseline_config.get("boundary_method"), config.get("boundary_method")],
            "recipe": [baseline_config.get("recipe"), config.get("recipe")],
            "solver_arguments": [baseline_prepared.get("solver_arguments"), prepared.get("solver_arguments")],
            "cfl_unchanged": baseline_config.get("cfl") == config.get("cfl") == 0.2,
        },
    }


def _numeric_observation_comparison(dbc: dict[str, Any], mdbc: dict[str, Any]) -> dict[str, Any]:
    left_time = np.asarray(dbc.get("time_s", []), dtype=float)
    right_time = np.asarray(mdbc.get("time_s", []), dtype=float)
    same_grid = bool(left_time.shape == right_time.shape and np.allclose(left_time, right_time, rtol=0.0, atol=1e-8))
    fields = {}
    if not same_grid:
        return {
            "same_saved_time_grid": False,
            "compared_fields": fields,
            "reason": "DBC and mDBC products do not have the same saved time grid; no interpolation was introduced.",
        }
    candidates = sorted(set(dbc) & set(mdbc))
    for key in candidates:
        if key in {"time_s", "event_times_s", "observable_names", "normalized_observable_names", "normalization"}:
            continue
        try:
            left = np.asarray(dbc[key], dtype=float)
            right = np.asarray(mdbc[key], dtype=float)
        except (TypeError, ValueError):
            continue
        if left.shape != right.shape or left.ndim == 0 or not np.isfinite(left).all() or not np.isfinite(right).all():
            continue
        delta = np.abs(left - right)
        fields[key] = {
            "shape": list(left.shape),
            "max_abs_difference": float(np.max(delta, initial=0.0)),
            "final_abs_difference": float(np.max(np.abs(left[-1] - right[-1]))) if left.ndim > 0 else 0.0,
        }
    return {"same_saved_time_grid": True, "compared_fields": fields}


def compare(
    prepared_path: Path,
    product_path: Path,
    baseline_prepared_path: Path,
    baseline_product_path: Path,
    cfl010_result_path: Path,
    cfl010_prepared_path: Path,
    output: Path,
) -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    baseline_prepared_path = Path(baseline_prepared_path).resolve()
    prepared = _json(prepared_path)
    baseline_prepared = _json(baseline_prepared_path)
    prepared["_path"] = str(prepared_path)
    baseline_prepared["_path"] = str(baseline_prepared_path)
    dbc = _product(product_path)
    mdbc = _product(baseline_product_path)
    cfl010 = _json(Path(cfl010_result_path).resolve())
    cfl010_prepared_doc = _json(Path(cfl010_prepared_path).resolve())
    cfl010_prepared_sha256 = cfl010.get("prepared_sha256")
    candidate_config = prepared.get("config", {})
    baseline_config = baseline_prepared.get("config", {})
    cfl010_guard = {
        "path": str(Path(cfl010_result_path).resolve()),
        "sha256": _sha256(Path(cfl010_result_path).resolve()),
        "prepared_sha256": cfl010_prepared_sha256,
        "prepared_path": str(Path(cfl010_prepared_path).resolve()),
        "prepared_file_sha256": _sha256(Path(cfl010_prepared_path).resolve()),
        "prepared_cfl": cfl010_prepared_doc.get("config", {}).get("cfl"),
        "prepared_boundary_method": cfl010_prepared_doc.get("config", {}).get("boundary_method"),
        "result_prepared_hash_matches": cfl010.get("prepared_sha256") == _sha256(Path(cfl010_prepared_path).resolve()),
        "is_excluded_from_pair": cfl010_prepared_sha256 not in {
            _sha256(prepared_path),
            _sha256(baseline_prepared_path),
        },
        "recorded_as": "negative CFL=.10 mDBC evidence, not the single-variable pair baseline",
        "cfl": cfl010_prepared_doc.get("config", {}).get("cfl"),
    }
    pair = _pair_config(prepared, baseline_prepared)
    pair["prepared_hash_matches_product"] = {
        "dbc": dbc["result"].get("prepared_sha256") == _sha256(prepared_path),
        "mdbc": mdbc["result"].get("prepared_sha256") == _sha256(baseline_prepared_path),
    }
    pair["pair_contract_pass"] = bool(
        pair["pair_contract_pass"]
        and pair["prepared_hash_matches_product"]["dbc"]
        and pair["prepared_hash_matches_product"]["mdbc"]
        and candidate_config.get("boundary_method") == 1
        and baseline_config.get("boundary_method") == 2
        and candidate_config.get("cfl") == baseline_config.get("cfl") == 0.2
    )
    report = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "read_only": True,
        "solver_relaunched": False,
        "qualification_claim": "none; terminal boundary comparison only",
        "dbc": _case_summary(dbc),
        "mdbc_cfl020_pair_baseline": _case_summary(mdbc),
        "pair_contract": pair,
        "cfl010_negative_guard": cfl010_guard,
        "observable_comparison": _numeric_observation_comparison(
            dbc["observations"], mdbc["observations"]
        ),
        "decision": {
            "t1_numerical": False,
            "t1_requires_external_qualification_evaluator": True,
            "gates_changed": False,
            "interpretation": "Boundary-only comparison; a DBC pass can justify reviewing this candidate lineage, never range or T1 qualification by itself.",
        },
    }
    _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True, help="DBC prepared.json")
    parser.add_argument("--product", type=Path, required=True, help="DBC product directory")
    parser.add_argument("--baseline-prepared", type=Path, required=True, help="original CFL=.20 mDBC prepared.json")
    parser.add_argument("--baseline-product", type=Path, required=True, help="original CFL=.20 mDBC product directory")
    parser.add_argument("--cfl010-result", type=Path, required=True, help="negative CFL=.10 result.json, excluded from pair")
    parser.add_argument("--cfl010-prepared", type=Path, required=True, help="negative CFL=.10 prepared.json, excluded from pair")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        args.prepared,
        args.product,
        args.baseline_prepared,
        args.baseline_product,
        args.cfl010_result,
        args.cfl010_prepared,
        args.output,
    )
    print(json.dumps({
        "pair_contract_pass": report["pair_contract"]["pair_contract_pass"],
        "dbc_hard_integrity_pass": report["dbc"]["hard_integrity_pass"],
        "dbc_event_window_complete": report["dbc"]["event_window_complete"],
        "mdbc_cfl020_hard_integrity_pass": report["mdbc_cfl020_pair_baseline"]["hard_integrity_pass"],
        "mdbc_cfl020_event_window_complete": report["mdbc_cfl020_pair_baseline"]["event_window_complete"],
        "cfl010_excluded_from_pair": report["cfl010_negative_guard"]["is_excluded_from_pair"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
