#!/usr/bin/env python3
"""Build and verify the F2 submerged-orifice transfer candidate.

This module is an input-contract tool.  It writes a candidate card, a fixed
15-row design, a failure denominator, and a root-review-only contract.  It
does not run GenCase, decode a BI4, call a solver, allocate a GPU, create a
job, or mutate a queue, ledger, registry, or scientific result.

The proposed scene is deliberately independent of the failed F2
receiver/weir and rotating-cup inputs: a stationary upstream reservoir passes
under a fixed upper gate slab through a submerged aperture.  The first safe
runtime step, if root approves it, is fresh CPU/native preparation of a new
Definition for one anchor.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
SCOPE_ID = "F2_submerged_orifice_transfer_v1"
REVISION_ID = "F2_submerged_orifice_mdbc_orifice_v1"
CANDIDATE_ID = "F2_submerged_orifice_transfer_q0p5_anchor"
EXPECTED_ROWS = 15
CREATED_AT = "2026-09-21T00:00:00+00:00"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _rel(base: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB_ROOT.resolve()))
    except ValueError:
        return str(Path(path).resolve().relative_to(base.resolve()))


def _row_id(q: float, dp: float, kind: str) -> str:
    q_text = f"{q:.2f}".replace(".", "p")
    dp_text = {0.01: "010", 0.0075: "0075", 0.005: "005"}[dp]
    return f"F2_ORIFICE_q{q_text}_dp{dp_text}_{kind}"


def fixed_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 0
    for q in (0.0, 0.5, 1.0):
        for dp in (0.01, 0.0075, 0.005):
            rows.append({
                "index": index,
                "row_id": f"OR-q{q:g}-dp{dp:g}-spatial",
                "q": q,
                "orifice_height_m": 0.10 + 0.16 * q,
                "gate_slab_low_z_m": 0.10 + 0.16 * q,
                "dp_m": dp,
                "design_cell": "spatial",
                "case_id": _row_id(q, dp, "spatial"),
                "status": "not_started",
            })
            index += 1
    for q in (0.25, 0.75):
        for dp in (0.0075, 0.005):
            rows.append({
                "index": index,
                "row_id": f"OR-q{q:g}-dp{dp:g}-heldout",
                "q": q,
                "orifice_height_m": 0.10 + 0.16 * q,
                "gate_slab_low_z_m": 0.10 + 0.16 * q,
                "dp_m": dp,
                "design_cell": "held_out",
                "case_id": _row_id(q, dp, "heldout"),
                "status": "not_started",
            })
            index += 1
    for kind in ("internal_time", "native_output"):
        rows.append({
            "index": index,
            "row_id": f"OR-q0.5-dp0.0075-{kind}",
            "q": 0.5,
            "orifice_height_m": 0.18,
            "gate_slab_low_z_m": 0.18,
            "dp_m": 0.0075,
            "design_cell": kind,
            "case_id": _row_id(0.5, 0.0075, kind),
            "status": "not_started",
            "control_change": "internal timestep only" if kind == "internal_time" else "native output cadence only",
        })
        index += 1
    return rows


def candidate_card() -> dict[str, Any]:
    return {
        "schema": "core.f2.submerged_orifice_transfer.candidate_card.v1",
        "created_at_utc": CREATED_AT,
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_status": "root_review_only_contract_no_cpu_preflight",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "mechanism": {
            "class": "stationary_reservoir_submerged_orifice_transfer",
            "hypothesis": (
                "A stationary upstream reservoir drives a reproducible gravity jet through a "
                "fixed submerged aperture under an upper gate slab into a downstream receiver."
            ),
            "physical_question": (
                "Does aperture height control a gravity-driven underflow transfer event while "
                "preserving finite-wall and gate-shell integrity?"
            ),
            "scientific_difference": [
                "Transfer is underflow through a low aperture; no particle must cross an internal crest.",
                "The fixed gate is an upper solid slab with a real bottom opening, not the prior full-height weir box.",
                "The source is stationary and there is no rotating cup, prescribed wall motion, or source impulse.",
                "q changes only the aperture top height; the outer tank, source, receiver, horizon, and observer stay fixed.",
            ],
            "disallowed_shortcuts_not_used": [
                "no receiver-overflow-weir input, generated asset, or trajectory reuse",
                "no F1 suspended-obstacle input or boundary repair reuse",
                "no rotating-cup DBC duration reuse",
                "no F3 impulse-baffle source reuse",
                "no same-input retry, threshold relaxation, horizon extension before hard pass, or survivor renormalization",
            ],
        },
        "fixed_geometry": {
            "outer_tank": {
                "low_m": [0.0, 0.0, 0.0],
                "size_m": [1.6, 0.5, 0.8],
                "closed_faces": ["bottom", "left", "right", "front", "back"],
                "open_faces": ["top"],
                "mkbound": 0,
            },
            "upper_gate_slab": {
                "anchor_low_m": [0.72, 0.04, 0.18],
                "size_xy_m": [0.06, 0.42],
                "zmax_m": 0.8,
                "low_z_mapping": "z_low_m = orifice_height_m(q)",
                "closed_faces": ["top", "left", "right", "front", "back"],
                "bottom_opening_below_z_m": 0.18,
                "mkbound": 1,
            },
            "submerged_aperture": {
                "x_span_m": [0.72, 0.78],
                "y_span_m": [0.04, 0.46],
                "z_low_m": 0.04,
                "top_mapping": "orifice_height_m = 0.10 + 0.16*q",
                "anchor_top_m": 0.18,
                "q_values": [0.0, 0.25, 0.5, 0.75, 1.0],
                "top_values_m": [0.10, 0.14, 0.18, 0.22, 0.26],
            },
            "upstream_source": {
                "low_m": [0.04, 0.04, 0.04],
                "size_m": [0.64, 0.42, 0.36],
                "free_surface_m": 0.40,
                "continuous_volume_m3": 0.096768,
                "density_kg_m3": 1000.0,
                "initial_velocity_m_s": [0.0, 0.0, 0.0],
            },
            "downstream_receiver": {
                "region_m": {"xmin": 0.78, "xmax": 1.56, "ymin": 0.04, "ymax": 0.46, "zmin": 0.0, "zmax": 0.8},
                "initial_fluid": False,
                "containment": "outer tank floor and side walls; top open",
            },
            "runtime_domain_m": {"xmin": -0.30, "xmax": 1.90, "ymin": -0.15, "ymax": 0.65, "zmin": -0.15, "zmax": 1.20},
            "gravity_m_s2": [0.0, 0.0, -9.81],
        },
        "boundary_and_numerics": {
            "boundary": "native mDBC Boundary=2",
            "slip_mode": 1,
            "normal_generation": "outer tank and upper gate slab GeometryForNormals; explicit gate shell orientation",
            "dp_matrix_m": [0.01, 0.0075, 0.005],
            "cfl": 0.2,
            "visco_treatment": 1,
            "visco": 0.03,
            "mass_policy": "native rho*dp^3; no rescaling",
            "output_interval_s": 0.01,
            "time_max_s": 1.5,
        },
        "one_dimensional_parameter": {
            "name": "submerged_orifice_top_height_m",
            "coordinate": "q in [0,1]",
            "mapping": "orifice_height_m = 0.10 + 0.16*q",
            "q_values": [0.0, 0.25, 0.5, 0.75, 1.0],
            "orifice_height_values_m": [0.10, 0.14, 0.18, 0.22, 0.26],
            "free_surface_minus_orifice_range_m": [0.14, 0.30],
        },
        "registered_window": {
            "initial_time_max_s": 1.5,
            "maximum_extended_time_max_s": 3.0,
            "extension_policy": "one whole-scope extension only after a complete hard pass; event censoring stays in denominator",
            "event_completion_required": True,
        },
        "observer": {
            "hard_integrity": [
                "requested horizon reached",
                "native fluid IDs unique and no active fluid ID missing",
                "all active arrays finite",
                "zero closed outer-wall endpoint violations",
                "zero upper-gate-shell endpoint penetrations",
                "zero outer-wall or gate-shell saved chord crossings",
                "zero fluid particles outside the closed outer tank",
                "relative mass change <= 1e-8",
            ],
            "event": {
                "underflow_crossing": "at least 1% of initial fluid mass crosses x=0.78 m while z is at or below the registered aperture top plus 2dp",
                "receiver_contact": "at least 1% of initial fluid mass enters the downstream receiver region",
                "completion": "receiver contact is sustained for 0.20 s and the complete 1.5 s window is observed",
                "credit_policy": "hard pass and complete event are both required; contract and CPU/native evidence have zero T1 credit",
            },
            "mass": {
                "native_policy": "rho*dp^3",
                "source_relative_error_max": 0.025,
                "total_relative_error_max": 0.03,
                "mass_change_relative_max": 1e-8,
                "mass_rescaling": False,
            },
            "event_censoring_policy": "hard pass without underflow/receiver completion remains event_censored in the fixed denominator",
        },
        "fixed_matrix": {
            "path": "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/fixed-matrix-v1.json",
            "cell_count": EXPECTED_ROWS,
            "spatial_cells": 13,
            "temporal_cells": 2,
            "denominator_policy": "all 15 rows remain in the denominator regardless of outcome",
        },
        "lineage": {
            "path": "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/lineage-clarification-v1.json",
            "source_reuse": False,
            "input_identity_changed": True,
            "qualification_inheritance": False,
        },
        "preflight": {
            "status": "not_run_root_review_required",
            "solver_run": False,
            "gpu_launched": False,
            "matrix_prepared": False,
            "matrix_credit": 0,
            "generated_input_present": False,
        },
        "execution_controls": {
            "cpu_gencase_invoked": False,
            "cpu_native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "central_ledger_mutation": 0,
            "central_registry_mutation": 0,
            "controls_executed": False,
        },
        "launch_policy": {
            "root_review_only": True,
            "cpu_native_preflight_allowed_after_root_review": True,
            "solver_submit": False,
            "gpu_submit": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_claim_allowed_now": False,
        },
    }


def fixed_matrix() -> dict[str, Any]:
    return {
        "schema": "core.f2.submerged_orifice_transfer.fixed_matrix.v1",
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none",
        "qualified": False,
        "status": "fixed_not_prepared_not_submitted",
        "matrix_credit": 0,
        "cell_count": EXPECTED_ROWS,
        "spatial_cell_count": 13,
        "temporal_cell_count": 2,
        "denominator": {"planned": EXPECTED_ROWS, "executed": 0, "passed": 0, "failed": 0, "event_censored": 0, "unattempted": EXPECTED_ROWS, "credit": 0},
        "parameter_mapping": "orifice_height_m = 0.10 + 0.16*q",
        "fixed_geometry": {"tank_size_m": [1.6, 0.5, 0.8], "gate_upper_slab_anchor_low_m": [0.72, 0.04, 0.18], "gate_upper_slab_size_xy_m": [0.06, 0.42], "gate_slab_low_z_mapping": "z_low_m = orifice_height_m(q)", "source_free_surface_m": 0.40},
        "rows": fixed_rows(),
        "fixed_rules": [
            "No receiver/weir, F1 suspended-obstacle, rotating-cup DBC, or F3 impulse-baffle input reuse.",
            "No same-input retry under another label.",
            "No threshold relaxation, horizon extension or static substitution before a hard pass.",
            "Solver failure, hard-integrity failure and event censoring remain in the denominator.",
            "Root-review contract and CPU/native preflight earn zero T1 credit.",
        ],
    }


def lineage() -> dict[str, Any]:
    return {
        "schema": "core.f2.submerged_orifice_transfer.lineage_clarification.v1",
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none",
        "new_scope": {
            "family": "F2",
            "mechanism_class": "stationary_reservoir_submerged_orifice_underflow",
            "physical_geometry_changed": True,
            "input_identity_changed": True,
            "boundary_semantics": "native mDBC Boundary=2 with upper gate slab and real bottom aperture",
            "prescribed_motion": False,
            "source_exchange": False,
            "static_hold": False,
        },
        "comparison_and_noninheritance": [
            {
                "scope": "F2_receiver_overflow_weir_v1",
                "reference": "campaigns/core-v1/evidence/f2-receiver-overflow-weir-anchor-negative-evidence-v1.json",
                "difference": "The failed route used a full-height internal weir and crest-overflow observer; this route uses an upper slab with a low submerged underflow aperture.",
                "historical_execution_reused": False,
                "same_input_retry": False,
            },
            {
                "scope": "F1_suspended_obstacle_gap_v1",
                "reference": "campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json",
                "difference": "F1 is a suspended obstacle approach/split/rejoin scene; this route has a stationary reservoir, a gate aperture and downstream receiver transfer.",
                "historical_execution_reused": False,
                "same_input_retry": False,
            },
            {
                "scope": "F2_dynamic_third_family_dbc_duration_x_v1",
                "reference": "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json",
                "difference": "The dynamic scope rotates a full cup and varies duration; this route has no moving wall, cup or duration axis.",
                "historical_execution_reused": False,
                "same_input_retry": False,
            },
            {
                "scope": "F3_baffle_exchange_native_mdbc_x_v1",
                "reference": "campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1/candidate-card-v1.json",
                "difference": "F3 is a source-scope impulse/baffle exchange; this route is an F2 stationary gravity underflow with an aperture-height axis and no source impulse.",
                "historical_execution_reused": False,
                "qualification_inheritance": False,
            },
        ],
        "source_asset_policy": {
            "new_definition_required": True,
            "new_generated_native_required": True,
            "old_failed_trajectory_reused": False,
            "old_failed_definition_reused": False,
            "cpu_native_preflight_status": "not_run",
        },
        "lineage_decision": "A fresh F2 physical/topology hypothesis is proposed for root review; no prior runtime result or input contributes credit.",
    }


def _prior_refs() -> list[dict[str, Any]]:
    paths = [
        (LAB_ROOT / "campaigns/core-v1/evidence/f2-receiver-overflow-weir-anchor-negative-evidence-v1.json", "failed F2 receiver/weir anchor"),
        (LAB_ROOT / "campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json", "failed F1 suspended-obstacle anchor"),
        (LAB_ROOT / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json", "event-censored F2 rotating-cup anchor"),
        (LAB_ROOT / "campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1/candidate-card-v1.json", "F3 baffle lineage reference"),
    ]
    return [_ref(path, role) for path, role in paths]


def write_bundle(base: Path = DEFAULT_BASE) -> dict[str, Any]:
    """Write the candidate bundle; all output is design evidence only."""
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    card_path = base / "candidate-card-v1.json"
    matrix_path = base / "fixed-matrix-v1.json"
    failure_path = base / "failure-denominator-v1.json"
    lineage_path = base / "lineage-clarification-v1.json"
    write_json(card_path, candidate_card())
    write_json(matrix_path, fixed_matrix())
    write_json(failure_path, {
        "schema": "core.f2.submerged_orifice_transfer.failure_denominator.v1",
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualified": False,
        "qualification_claim": "none",
        "planned": EXPECTED_ROWS,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "event_censored": 0,
        "unattempted": EXPECTED_ROWS,
        "credit": 0,
        "preservation": {
            "all_rows_retained": True,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "horizon_extension_before_anchor": False,
            "static_hold_substitution": False,
            "survivor_renormalization": False,
            "prior_lineages_merged": False,
        },
    })
    write_json(lineage_path, lineage())
    contract = {
        "schema": "core.f2.submerged_orifice_transfer.root_review_contract.v1",
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "decision": "candidate_contract_only_root_review_required",
        "status": "prepared_design_not_cpu_preflight_not_runtime_authorized",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_anchor": False,
        "authorized_runtime_preparation": False,
        "authorization": {
            "cpu_gencase": False,
            "native_decode": False,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "novelty_review": {
            "new_physical_or_boundary_hypothesis": True,
            "underflow_aperture_not_crest_overflow": True,
            "stationary_source_no_rotating_cup": True,
            "no_suspended_obstacle": True,
            "no_f3_impulse_source": True,
            "old_failed_inputs_reused": False,
            "old_failed_trajectory_reused": False,
        },
        "hash_bindings": {
            "candidate_card": _ref(card_path, "new F2 candidate card"),
            "fixed_matrix": _ref(matrix_path, "new 15-row fixed matrix"),
            "failure_denominator": _ref(failure_path, "new zero-credit failure denominator"),
            "lineage": _ref(lineage_path, "new lineage clarification"),
            "adapter": _ref(Path(__file__).resolve(), "candidate contract implementation"),
            "prior_failures": _prior_refs(),
        },
        "preflight": {
            "status": "not_run",
            "new_definition_present": False,
            "new_native_bi4_present": False,
            "solver_product_present": False,
            "cpu_native_credit": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "required_next_step": "root review the independent mechanism and hashes; if accepted, prepare one fresh q=0.5 dp=0.0075 Definition/native anchor on CPU only",
        "blockers": [
            "No new Definition or generated native input has been produced in this read-only contract step.",
            "No solver-integrated trajectory or event result exists.",
            "No root authorization exists for CPU/native preparation, solver, GPU, queue, ledger, or registry.",
        ],
    }
    contract_path = base / "root-review-contract-v1.json"
    write_json(contract_path, contract)
    return verify_bundle(base)


def _verify_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item.get("path", "")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    expected = item.get("sha256")
    if expected != sha256(path):
        raise ValueError(f"{label} hash mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch")
    return path


def verify_bundle(base: Path = DEFAULT_BASE) -> dict[str, Any]:
    base = Path(base).resolve()
    card_path = base / "candidate-card-v1.json"
    matrix_path = base / "fixed-matrix-v1.json"
    failure_path = base / "failure-denominator-v1.json"
    lineage_path = base / "lineage-clarification-v1.json"
    contract_path = base / "root-review-contract-v1.json"
    card, matrix, failure, lineage, contract = [load_json(path) for path in (card_path, matrix_path, failure_path, lineage_path, contract_path)]
    for label, value in (("candidate", card), ("matrix", matrix), ("failure denominator", failure), ("lineage", lineage), ("contract", contract)):
        if value.get("scope_id") != SCOPE_ID or value.get("revision_id") != REVISION_ID:
            raise ValueError(f"{label} scope/revision mismatch")
        if value.get("qualification_claim") != "none":
            raise ValueError(f"{label} has a qualification claim")
    if card.get("candidate_status") != "root_review_only_contract_no_cpu_preflight":
        raise ValueError("candidate status is not contract-only")
    if card.get("matrix_credit") != 0 or card.get("qualified") is not False or card.get("T1_numerical") is not False:
        raise ValueError("candidate credit/qualification gate is open")
    rows = matrix.get("rows", [])
    if matrix.get("cell_count") != EXPECTED_ROWS or len(rows) != EXPECTED_ROWS:
        raise ValueError("fixed matrix is not 15 rows")
    if len({row.get("case_id") for row in rows}) != EXPECTED_ROWS or any(row.get("status") != "not_started" for row in rows):
        raise ValueError("matrix identities or status are not closed")
    if matrix.get("denominator", {}).get("unattempted") != EXPECTED_ROWS or matrix.get("matrix_credit") != 0:
        raise ValueError("matrix denominator/credit is open")
    if failure.get("planned") != EXPECTED_ROWS or failure.get("unattempted") != EXPECTED_ROWS or failure.get("credit") != 0:
        raise ValueError("failure denominator is not a zero-credit 15-row denominator")
    preservation = failure.get("preservation", {})
    for key in ("same_input_retry", "threshold_relaxation", "horizon_extension_before_anchor", "static_hold_substitution", "survivor_renormalization", "prior_lineages_merged"):
        if preservation.get(key) is not False:
            raise ValueError(f"failure preservation opened: {key}")
    if contract.get("decision") != "candidate_contract_only_root_review_required":
        raise ValueError("root contract decision is not review-only")
    auth = contract.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"contract authorization opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"contract mutation control opened: {key}")
    if contract.get("authorized_anchor") is not False or contract.get("authorized_runtime_preparation") is not False:
        raise ValueError("contract authorizes runtime")
    bindings = contract.get("hash_bindings", {})
    for label, path in (("candidate_card", card_path), ("fixed_matrix", matrix_path), ("failure_denominator", failure_path), ("lineage", lineage_path), ("adapter", Path(__file__).resolve())):
        item = bindings.get(label, {})
        _verify_ref(item, label)
        if Path(item["path"]).resolve() != path.resolve():
            raise ValueError(f"{label} path binding mismatch")
    for index, item in enumerate(bindings.get("prior_failures", [])):
        _verify_ref(item, f"prior failure {index}")
    if contract.get("novelty_review", {}).get("old_failed_inputs_reused") is not False:
        raise ValueError("novelty review permits old input reuse")
    if card.get("lineage", {}).get("source_reuse") is not False:
        raise ValueError("candidate lineage permits source reuse")
    return {
        "schema": "core.f2.submerged_orifice_transfer.bundle_verification.v1",
        "status": "root_review_only_contract_verified",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "candidate": {"path": str(card_path), "sha256": sha256(card_path), "candidate_id": card["candidate_id"]},
        "fixed_matrix": {"path": str(matrix_path), "sha256": sha256(matrix_path), "rows": len(rows), "all_not_started": True},
        "failure_denominator": {"path": str(failure_path), "sha256": sha256(failure_path), "planned": EXPECTED_ROWS, "credit": 0},
        "lineage": {"path": str(lineage_path), "sha256": sha256(lineage_path), "source_reuse": False},
        "contract": {"path": str(contract_path), "sha256": sha256(contract_path), "authorized_runtime_preparation": False},
        "prior_failure_count": len(bindings.get("prior_failures", [])),
        "execution_controls": {"solver": False, "gpu": False, "queue": 0, "ledger": 0, "registry": 0},
        "core_gate_effect": {"new_t1_family": False, "qualification_credit": 0, "core_can_finalize_changed": False},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    args = parser.parse_args(argv)
    result = write_bundle(args.base) if args.command == "write" else verify_bundle(args.base)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
