#!/usr/bin/env python3
"""Build a hash-bound, qualification-only H2 mDBC static-range design.

This command consumes the already completed H2 mDBC v2 single-cell canary,
its evidence, and the canary root review.  It emits a new 15-cell design and
CPU/native preparation plan.  It does not invoke GenCase, the native decoder,
the solver, a scheduler, a queue, a ledger, or the registry.  Every cell is
left unmaterialized until a new root review authorizes the independent CPU
preflight.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.h2_mdbc_static_qualification_design.v1"
CANARY_SCHEMA = "core.f2.h2_mdbc_boundary_repair.canary_evidence.v1"
REVIEW_SCHEMA = "core.root_review.v1"
PREPARED_SCHEMA = "core.cfd.v1"
EXPECTED_CELLS = 15
QUALIFICATION_Q = (0.0, 0.5, 1.0)
HELD_OUT_Q = (0.25, 0.75)
DP_VALUES = (0.01, 0.0075, 0.005)
REGISTERED_WINDOW_S = 0.6
REGISTERED_OUTPUT_INTERVAL_S = 0.02
NATIVE_OUTPUT_INTERVAL_S = 0.01


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (LAB_ROOT / path).resolve()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(binding: dict[str, Any], label: str, *, expected_path: Path | None = None) -> Path:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise ValueError(f"{label} has no path")
    path = resolve_path(binding["path"])
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ValueError(f"{label} path mismatch: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if binding.get("sha256") != digest(path):
        raise ValueError(f"{label} hash mismatch: {path}")
    if binding.get("bytes") is not None and int(binding["bytes"]) != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch: {path}")
    return path


def _token(value: float, places: int) -> str:
    return f"{value:.{places}f}".replace(".", "p")


def _volume(q: float) -> float:
    # The q=.5 value is exactly the H2 canary volume.  The endpoints define a
    # new static range; no qualification is inherited from the old F2 card.
    return 0.022950 + 0.001290 * q


def _fluid_boxes(q: float) -> list[dict[str, Any]]:
    volume = _volume(q)
    area = 0.325 * 0.22
    total_height = volume / area
    upper_height = total_height - 0.22
    if upper_height <= 0.0:
        raise ValueError(f"q={q} produces a non-positive third fluid layer")
    heights = (0.11, 0.11, upper_height)
    return [
        {
            "continuous_low_m": [0.05, -0.11, 0.70 + 0.11 * index],
            "continuous_size_m": [0.325, 0.22, height],
            "mkfluid": index,
        }
        for index, height in enumerate(heights)
    ]


def _cell_id(index: int, q: float, dp: float, kind: str) -> str:
    return (
        f"CORE_F2_H2_mdbc_static_volume_q{_token(q, 8)}_dp{_token(dp, 12)}_{kind}_{index:02d}"
    )


def _cell(index: int, q: float, dp: float, kind: str, *, held_out: bool = False) -> dict[str, Any]:
    native_variant = kind == "native_output"
    output_interval = NATIVE_OUTPUT_INTERVAL_S if native_variant else REGISTERED_OUTPUT_INTERVAL_S
    boxes = _fluid_boxes(q)
    input_contract = {
        "q": q,
        "dp_m": dp,
        "design_cell": kind,
        "held_out": held_out,
        "temporal_variant": kind if kind in {"internal_time", "native_output"} else None,
        "initial_volume_m3": _volume(q),
        "initial_fill_height_m": _volume(q) / (0.425 * 0.30),
        "fluid_boxes": boxes,
        "output_interval_s": output_interval,
        "registered_window_s": REGISTERED_WINDOW_S,
        "mdbc_normal_support": {
            "boundary_method": 2,
            "normal_layers_vdp": -0.5,
            "normal_distanceh": 3.0,
            "svshapes": True,
        },
        "native_sampling": {
            "mode": "cell-centre lattice pointref=dp/2",
            "decode_each_cell": True,
            "expected_particle_axis_from_preflight": True,
            "mass_policy": "native rho*dp^3; no mass rescaling",
        },
    }
    return {
        "index": index,
        "case_id": _cell_id(index, q, dp, kind),
        "q": q,
        "dp_m": dp,
        "design_cell": kind,
        "temporal_variant": kind if kind in {"internal_time", "native_output"} else None,
        "held_out": held_out,
        "initial_volume_m3": _volume(q),
        "initial_fill_height_m": _volume(q) / (0.425 * 0.30),
        "output_interval_s": output_interval,
        "status": "design_only_unprepared",
        "prepared": None,
        "job": None,
        "trajectory": None,
        "input_contract": input_contract,
        "design_cell_sha256": canonical_digest(input_contract),
        "materialization": {
            "definition_required": True,
            "motion_required": True,
            "gencase_required": True,
            "native_decode_required": True,
            "preflight_required": True,
            "independent_input_hash_required": True,
            "reuse_canary_trajectory": False,
            "status": "not_materialized",
        },
        "failure_categories_if_unavailable": ["not_materialized", "missing_runtime_product"],
    }


def _cells() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    index = 0
    for q in QUALIFICATION_Q:
        for dp in DP_VALUES:
            cells.append(_cell(index, q, dp, "spatial"))
            index += 1
    for q in HELD_OUT_Q:
        for dp in (0.0075, 0.005):
            cells.append(_cell(index, q, dp, "spatial_held_out", held_out=True))
            index += 1
    cells.append(_cell(index, 0.5, 0.0075, "internal_time"))
    index += 1
    cells.append(_cell(index, 0.5, 0.0075, "native_output"))
    assert len(cells) == EXPECTED_CELLS
    return cells


def _validate_canary(
    canary_path: Path, evidence_path: Path, review_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    canary = load(canary_path)
    if canary.get("schema") != PREPARED_SCHEMA:
        raise ValueError("H2 canary prepared schema mismatch")
    config = canary.get("config", {})
    if config.get("family") != "F2" or config.get("scope_id") != "F2_H2_mdbc_boundary_repair_canary_v1":
        raise ValueError("H2 canary scope mismatch")
    if canary.get("preflight_pass") is not True:
        raise ValueError("H2 canary CPU preflight is not passed")
    if canary.get("mass_preflight", {}).get("mass_rescaling") is not False:
        raise ValueError("H2 canary mass rescaling contract changed")
    if canary.get("native_initial", {}).get("zero_boundary_normals") != 0:
        raise ValueError("H2 canary has zero boundary normals")
    if canary.get("static_diagnostic_preflight", {}).get("mdbc_normals_complete_nonzero") is not True:
        raise ValueError("H2 canary normal preflight is not complete")
    runtime_domain = config.get("runtime_domain", {})
    changed_zmax = runtime_domain.get("changed_zmax_m", runtime_domain.get("changed_zmax"))
    if config.get("boundary_method") != 2 or changed_zmax != 2.4:
        raise ValueError("H2 canary boundary/domain contract mismatch")
    evidence = load(evidence_path)
    if evidence.get("schema") != CANARY_SCHEMA:
        raise ValueError("H2 canary evidence schema mismatch")
    if evidence.get("scope_id") != config.get("scope_id") or evidence.get("case_id") != config.get("case_id"):
        raise ValueError("H2 canary evidence identity mismatch")
    status = evidence.get("scientific_status", {})
    decision = evidence.get("decision", {})
    if status.get("T1_numerical") is not False or status.get("registry_mutation") != 0:
        raise ValueError("H2 canary evidence claims T1 or registry mutation")
    if decision.get("qualification_scope_ready") is not False or decision.get("expand_to_15_cell_matrix") is not False:
        raise ValueError("H2 canary evidence already authorizes a matrix")
    verify_ref(evidence.get("prepared", {}), "H2 canary evidence prepared", expected_path=canary_path)
    verify_ref(evidence.get("root_review", {}), "H2 canary evidence root review", expected_path=review_path)
    review = load(review_path)
    if review.get("schema") != REVIEW_SCHEMA or review.get("scope_id") != config.get("scope_id"):
        raise ValueError("H2 canary root review identity mismatch")
    if review.get("decision") != "approved_for_runtime_smoke" or review.get("authorized_cell_indices") != [0]:
        raise ValueError("H2 canary root review is not the single-cell smoke review")
    if review.get("registry_mutation") != 0 or review.get("qualification_claim") != "none":
        raise ValueError("H2 canary root review claims qualification or registry mutation")
    return canary, evidence, review


def build_design(
    canary_prepared: str | Path,
    canary_evidence: str | Path,
    root_review: str | Path,
) -> dict[str, Any]:
    canary_path = resolve_path(canary_prepared)
    evidence_path = resolve_path(canary_evidence)
    review_path = resolve_path(root_review)
    canary, evidence, review = _validate_canary(canary_path, evidence_path, review_path)
    config = canary["config"]
    source_template = resolve_path(canary["source_template"])
    if canary.get("source_template_sha256") != digest(source_template):
        raise ValueError("H2 canary source template hash mismatch")
    prepared_ref = ref(canary_path, "H2 mDBC v2 prepared canary; historical input only")
    evidence_ref = ref(evidence_path, "positive single-cell H2 hard/static evidence")
    review_ref = ref(review_path, "single-cell H2 root smoke review")
    source_ref = ref(source_template, "H2 Definition source template; future cells must copy/adapt")
    cells = _cells()
    fluid_area = 0.325 * 0.22
    return {
        "schema": SCHEMA,
        "created_at_utc": stamp(),
        "family": "F2",
        "candidate_id": "F2_H2_mdbc_static_range_hold",
        "scope_id": "F2_H2_mdbc_static_range_hold_x_v1",
        "revision_id": "F2_H2_mdbc_static_range_qualification_v1",
        "status": "design_only_cpu_preparation_plan",
        "qualification_only": True,
        "qualification_claim": "none; independent H2 static-range candidate only",
        "qualified": False,
        "central_registry_mutation": 0,
        "gpu_launch_by_subagent": False,
        "canary_support": {
            "historical_canary": evidence_ref,
            "prepared": prepared_ref,
            "root_review": review_ref,
            "source_template": source_ref,
            "positive_scope": "single-cell hard/static hold only",
            "inheritance": "geometry and H2 normal hypothesis inform this design; no runtime, range, temporal, or T1 result is inherited",
            "canary_event_window_complete": evidence.get("scientific_status", {}).get("event_window_complete"),
            "canary_minimum_retention": evidence.get("diagnostics", {}).get("minimum_cup_retention_mass_fraction"),
        },
        "physical_contract": {
            "scene": "fixed cup at zero angle; static hold only",
            "physical_geometry_changed_from_h2_canary": False,
            "cup": deepcopy(config["cup"]),
            "receiver": deepcopy(config["receiver"]),
            "tray": deepcopy(config["tray"]),
            "runtime_domain": deepcopy(config["runtime_domain"]),
            "boundary_method": "mDBC Boundary=2 with -mdbc_noslip:1 in a future root-reviewed runtime only",
            "normal_hypothesis": "three-layer normal support with expanded normal search",
            "motion": {"angle_degrees": 0.0, "motion_file": "fresh zero-angle file per cell"},
            "continuum_fluid_footprint": {
                "x_low_m": 0.05,
                "y_low_m": -0.11,
                "x_size_m": 0.325,
                "y_size_m": 0.22,
                "area_m2": fluid_area,
                "volume_mapping": "V(q)=0.022950 + 0.001290*q m3",
                "fill_height_mapping": "h(q)=V(q)/(0.425*0.30)",
                "fluid_layer_policy": "two 0.11 m lower layers plus q-dependent upper layer; q=.5 reproduces canary continuum volume",
            },
        },
        "normal_contract": {
            "boundary_method": 2,
            "solver_argument_reference": "-mdbc_noslip:1; declaration only, no solver invocation here",
            "normal_layers_vdp": -0.5,
            "main_boundary_layers_vdp": [0, 1, 2],
            "normal_distanceh": 3.0,
            "svshapes": True,
            "required_groups": ["cup", "receiver", "tray"],
            "every_cell_fresh_normal_preflight": True,
            "zero_boundary_normals_max": 0,
            "normal_count_equals_boundary_count": True,
            "normal_vectors_finite_nonzero": True,
        },
        "sampling_contract": {
            "native_sampling": "cell-centre pointref=dp/2 lattice; actual generated groups and positions must be decoded per cell",
            "fresh_definition_motion_gencase_decode_preflight_per_cell": True,
            "native_identity_axis_from_actual_preflight": True,
            "native_mass_policy": "native rho*dp^3; no mass rescaling",
            "canary_trajectory_reuse": False,
            "temporal_rows_are_independent_inputs": True,
        },
        "qualification_design": {
            "cell_count": EXPECTED_CELLS,
            "qualification_q": list(QUALIFICATION_Q),
            "held_out_q": list(HELD_OUT_Q),
            "dp_m": list(DP_VALUES),
            "registered_window_s": REGISTERED_WINDOW_S,
            "output_interval_s": REGISTERED_OUTPUT_INTERVAL_S,
            "native_output_interval_s": NATIVE_OUTPUT_INTERVAL_S,
            "settle_hold_s": 0.2,
            "cells": cells,
            "matrix_inputs_materialized": False,
            "matrix_jobs_materialized": False,
            "temporal_rows": {
                "internal_time": "q=.5, dp=.0075, fresh input and .02 s declared output; explicit actual-step evidence required",
                "native_output": "q=.5, dp=.0075, fresh input and independently declared .01 s native output",
            },
            "held_out_policy": "q=.25/.75 rows are independent denominator rows and are excluded from qualification-q numerator",
        },
        "gates": {
            "source_initial_mass_relative_error_max": 0.025,
            "total_discrete_to_continuum_mass_error_max": 0.03,
            "mass_change_relative_max": 1e-8,
            "mass_rescaling_allowed": False,
            "no_missing_native_fluid_ids": True,
            "no_unexpected_native_ids": True,
            "no_nonfinite_active_values": True,
            "no_runtime_domain_endpoint_outside": True,
            "no_cup_closed_face_endpoint_or_saved_chord_crossings": True,
            "no_open_cup_escape": True,
            "cup_retention_mass_fraction_min": 0.95,
            "static_speed_p95_m_s_max": 0.1,
            "static_kinetic_over_initial_potential_max": 0.05,
            "static_settle_hold_s": 0.2,
            "event_window_complete_required": True,
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_max_absolute_normalized_difference": 0.01,
            "internal_time_actual_step_evidence_required": True,
            "thresholds_changed": False,
            "survivor_renormalization": False,
        },
        "failure_denominator": {
            "fixed": EXPECTED_CELLS,
            "survivor_renormalization": False,
            "categories": [
                "not_materialized",
                "missing_runtime_product",
                "mass_quality",
                "native_identity_axis",
                "nonfinite_active_value",
                "mdbc_normal_zero_or_incomplete",
                "runtime_domain_endpoint",
                "cup_closed_face_endpoint_or_saved_chord",
                "open_cup_escape",
                "static_settle",
                "event_window_incomplete",
                "spatial_comparison",
                "temporal_comparison",
                "temporal_control_evidence",
            ],
            "rows": [
                {
                    "index": cell["index"],
                    "case_id": cell["case_id"],
                    "status": cell["status"],
                    "failure_categories": cell["failure_categories_if_unavailable"],
                }
                for cell in cells
            ],
        },
        "admission_controls": {
            "cpu_design_only": True,
            "solver_launch_allowed": False,
            "gpu_launch_allowed": False,
            "job_spec_creation_allowed": False,
            "queue_mutation_allowed": False,
            "ledger_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "anchor_trajectory_reuse_allowed": False,
            "threshold_relaxation_allowed": False,
            "survivor_renormalization_allowed": False,
            "qualification_claim_allowed": False,
        },
        "materialization_decision": {
            "cpu_materialization_safe_now": False,
            "status": "blocked_until_new_root_review",
            "blockers": [
                "existing root review authorizes only canary cell 0 smoke and explicitly rejects matrix expansion",
                "q endpoints and dp=.010/.005 have no H2 Definition/GenCase/native preflight hashes",
                "canary event_window_complete is false and supplies no range or temporal comparison evidence",
                "each temporal row must be independently materialized even though geometry is equal",
            ],
            "next_step": "obtain a new root review for CPU/native preflight only; then materialize each cell independently without creating jobs",
        },
        "execution_controls": {
            "definition_generated_by_this_command": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_spec_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary-prepared", type=Path, required=True)
    parser.add_argument("--canary-evidence", type=Path, required=True)
    parser.add_argument("--root-review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    design = build_design(args.canary_prepared, args.canary_evidence, args.root_review)
    write_json(args.output, design)
    print(json.dumps({
        "schema": design["schema"],
        "scope_id": design["scope_id"],
        "cell_count": design["qualification_design"]["cell_count"],
        "materialized": design["qualification_design"]["matrix_inputs_materialized"],
        "cpu_materialization_safe_now": design["materialization_decision"]["cpu_materialization_safe_now"],
        "execution_controls": design["execution_controls"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
