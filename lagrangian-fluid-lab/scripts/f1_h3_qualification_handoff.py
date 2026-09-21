#!/usr/bin/env python3
"""Build a conditional F1 H3 qualification handoff.

This module only writes claim-free design and admission metadata.  It does not
run GenCase, create the expensive 15 native inputs, launch a solver, or write
the central campaign registry.  The H3 bottom-face canary is the gate for any
later materialization.  The handoff deliberately keeps the existing F1
geometry-aware observer and 13+2 design while changing the boundary recipe to
the evidence-backed H3 obstacle-bottom topology repair.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_f1 import _f1_wall_spec, f1_config
from scripts.core_f1_qualification import (
    BASE_TIME_CONTROL,
    HALF_TIME_CONTROL,
    EVENT_NAMES,
    OBSERVABLE_NAMES,
    REVISION_ID as OBSERVER_REVISION_ID,
    manufactured_calibration,
    observer_registration,
    formal_design,
)
from scripts.core_production import FIRST_EIGHT, register_scope


SCHEMA = "core.f1.h3.qualification_handoff.v1"
FAMILY = "F1"
SCOPE_ID = "F1_single_obstacle_mdbc_bottom_face_height_range_v1"
REVISION_ID = "F1_H3_obstacle_bottom_face_mdbc_13plus2_v1"
RECIPE_ID = "F1_H3_obstacle_bottom_face_mdbc_v1"
RECIPE = "mdbc_native_boundary_topology_repair"
PARAMETER_NAME = "initial_water_height_m"
PARAMETER_RANGE = (0.40, 0.52)
Q_VALUES = (0.0, 0.5, 1.0, 0.25, 0.75)
RESOLUTIONS = (0.010, 0.0075, 0.005)
CANARY_JOB_ID = "f1-h3-obstacle-bottom-face-mdbc-canary-001"
CANARY_CASE_ID = (
    "CORE_F1_H3_mdbc_obstacle_bottom_face_q0p50000000_h0p46000000_"
    "dp0p007500000000_canary"
)
CANARY_PREPARED = SOURCE_ROOT / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/"
    "candidate/prepared.json"
)
CANARY_JOB = SOURCE_ROOT / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/"
    "f1-h3-obstacle-bottom-face-mdbc-canary-job.json"
)
CANARY_PROPOSAL = SOURCE_ROOT / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/"
    "f1-h3-obstacle-bottom-face-canary-proposal-v1.json"
)
LEGACY_DESIGN = SOURCE_ROOT / "campaigns/core-v1/cfd/f1-reference-qualification-design.json"
LEGACY_EVALUATION = SOURCE_ROOT / "campaigns/core-v1/cfd/f1-qualification-evaluation.json"


class HandoffError(ValueError):
    """Raised when a conditional handoff cannot be bound or remains unsafe."""


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path).resolve()
    data = json.dumps(value, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text() != data:
            raise HandoffError(f"refusing to overwrite immutable handoff artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(data)
    temporary.replace(path)


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise HandoffError(f"required handoff input is missing ({role}): {path}")
    return {"path": str(path), "sha256": _sha256(path), "role": role}


def _token(value: float, places: int = 8) -> str:
    return f"{float(value):.{places}f}".replace("-", "m").replace(".", "p")


def _h3_case_id(config: Mapping[str, Any]) -> str:
    q = float(config["parameter"]["q"])
    height = float(config["parameter"]["value"])
    dp = float(config["dp_m"])
    suffix = ""
    if config["design_cell"] != "spatial":
        suffix = f"_{config['design_cell']}"
    return (
        f"CORE_F1_H3_obstacle_bottom_face_mdbc_q{_token(q)}"
        f"_h{_token(height)}_dp{float(dp):.12f}".replace(".", "p")
        + f"_qualification{suffix}"
    )


def _h3_cell(base: Mapping[str, Any]) -> dict[str, Any]:
    config = deepcopy(dict(base))
    config.update(
        {
            "scope_id": SCOPE_ID,
            "revision_id": REVISION_ID,
            "case_id": _h3_case_id(config),
            "recipe_id": RECIPE_ID,
            "recipe": RECIPE,
            "stage": "qualification",
            "qualification_only": True,
            "qualification_claim": "none",
            "qualified": False,
            "boundary_semantics": (
                "mDBC no-slip with complete tank and finite-obstacle normals; "
                "obstacle bottom face closed in mainlist and GeometryForNormals"
            ),
            "solver_arguments": ["-mdbc_noslip:1"],
            "observer_revision": OBSERVER_REVISION_ID,
            "observer_observable_names": list(OBSERVABLE_NAMES),
            "event_registration": observer_registration()["event_thresholds"],
            "time_control": deepcopy(
                HALF_TIME_CONTROL if config["design_cell"] == "internal_time" else BASE_TIME_CONTROL
            ),
            "h3_boundary_topology": {
                "mainlist_obstacle_boxfill": "bottom | top | left | right | front | back",
                "geometry_for_normals_obstacle_boxfill": "bottom | top | left | right | front | back",
                "continuum_geometry_changed": False,
                "mass_rescaling": False,
                "zero_normals_allowed": 0,
                "exact_fluid_boundary_overlap_allowed": 0,
            },
            "canary_dependency": {
                "job_id": CANARY_JOB_ID,
                "case_id": CANARY_CASE_ID,
                "required_before_materialization": True,
            },
        }
    )
    return config


def qualification_design() -> dict[str, Any]:
    """Return 13+2 H3 cards without generating any native input."""
    old = formal_design()
    cells = [_h3_cell(config) for config in old["cells"]]
    wall_spec = _f1_wall_spec()
    design = {
        "schema": SCHEMA,
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "recipe_id": RECIPE_ID,
        "recipe": RECIPE,
        "qualification_claim": "none",
        "candidate_status": "conditional_pre_registered_unqualified",
        "qualification_only": True,
        "qualification_inheritance": False,
        "cell_count": 15,
        "spatial_cells": 13,
        "temporal_cells": 2,
        "cells": cells,
        "parameter": {
            "name": PARAMETER_NAME,
            "q_values": list(Q_VALUES),
            "height_values_m": [0.40 + 0.12 * q for q in Q_VALUES],
            "range_m": list(PARAMETER_RANGE),
            "mapping": "h(q)=0.40+0.12*q m",
        },
        "spatial_resolutions_m": list(RESOLUTIONS),
        "fixed_geometry": {
            "tank": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.6]},
            "obstacle": {"id": "center_obstacle", "low": [0.68, 0.15, 0.0], "size": [0.12, 0.10, 0.34]},
            "runtime_domain": wall_spec["runtime_domain"],
            "continuum_geometry_changed": False,
            "boundary_topology_changed": True,
        },
        "registered_window": {
            "initial_time_max_s": 2.20,
            "output_interval_s": 0.02,
            "maximum_extended_time_max_s": 4.40,
            "extension_policy": "one whole-scope doubling after a frozen right-censor",
            "event_completion_required": True,
        },
        "observer": observer_registration(),
        "hard_integrity_contract": {
            "no_missing_native_fluid_ids": True,
            "no_nonfinite_active_values": True,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "full_solid_obstacle_audit": True,
            "obstacle_penetration_particle_frames_allowed": 0,
            "fluid_boundary_exact_overlap_allowed": 0,
        },
        "preregistered_gates": {
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_max_absolute_normalized_difference": 0.010,
            "event_time_relative_error_max": 0.05,
            "actual_dt_ratio_max_for_internal_time": 0.80,
            "actual_step_ratio_min_for_internal_time": 1.25,
            "native_output_interval_ratio_max": 0.30,
            "native_output_frame_ratio_min": 3.0,
            "source_initial_mass_relative_error_max": 0.025,
            "initial_mass_spread_over_continuous_mass_max": 0.03,
            "no_survivor_renormalization": True,
            "all_15_cells_required": True,
        },
        "canary_dependency": {
            "job_id": CANARY_JOB_ID,
            "case_id": CANARY_CASE_ID,
            "prepared": _ref(CANARY_PREPARED, "H3 canary prepared"),
            "job": _ref(CANARY_JOB, "H3 canary job"),
            "proposal": _ref(CANARY_PROPOSAL, "H3 canary proposal"),
            "required_status": "succeeded",
            "required_checks": [
                "hard_integrity_pass",
                "source_mass_gate_pass",
                "requested_horizon_reached",
                "event_window_complete",
                "full_solid_obstacle_audit",
            ],
        },
        "materialization_policy": {
            "gen_case_run": False,
            "solver_run": False,
            "prepared_matrix_written": False,
            "jobs_written": False,
            "reason": "H3 canary must pass before any H3-specific 15-cell GenCase preparation",
            "legacy_h1_matrix_reusable": False,
            "legacy_h1_matrix_reason": "native DBC recipe and H1 canary dependency differ from H3 mDBC topology recipe",
        },
    }
    return design


def production_design(design: Mapping[str, Any]) -> dict[str, Any]:
    """Register the conditional scalar 8 -> 32 production plan in memory."""
    if design.get("scope_id") != SCOPE_ID or design.get("qualification_only") is not True:
        raise HandoffError("production handoff design has wrong scope or qualification status")
    points = [float(cell["parameter"]["value"]) for cell in design["cells"]]
    registered = register_scope(FAMILY, SCOPE_ID, PARAMETER_NAME, *PARAMETER_RANGE, points)
    for row in registered["cases"]:
        row.update(
            revision_id=REVISION_ID,
            recipe_id=RECIPE_ID,
            recipe=RECIPE,
            observer_revision=OBSERVER_REVISION_ID,
            container_height_m=0.6,
            registered_window_s=2.20,
            maximum_extended_window_s=4.40,
            qualification_inheritance=False,
            canary_dependency=CANARY_JOB_ID,
            source_scope_qualification_inherited=False,
        )
    registered.update(
        {
            "schema": "core.f1.h3.production_design.v1",
            "scope_id": SCOPE_ID,
            "revision_id": REVISION_ID,
            "recipe_id": RECIPE_ID,
            "recipe": RECIPE,
            "family": FAMILY,
            "parameter_name": PARAMETER_NAME,
            "parameter_range": list(PARAMETER_RANGE),
            "qualification_parameters": points,
            "case_count": 32,
            "first_batch_indices": list(FIRST_EIGHT),
            "qualification_inheritance": False,
            "qualification_status": "blocked_until_hash_verified_T1_receipt",
            "canary_dependency": CANARY_JOB_ID,
            "prepared_inputs_written": False,
            "job_specs_written": False,
            "solver_launched": False,
            "ledger_written": False,
        }
    )
    return registered


def observer_audit() -> dict[str, Any]:
    """Bind the old F1 worker/evaluator source to the required geometry gates."""
    worker_path = SOURCE_ROOT / "scripts/core_f1.py"
    observer_path = SOURCE_ROOT / "scripts/core_f1_qualification.py"
    worker = worker_path.read_text()
    observer = observer_path.read_text()
    wall = _f1_wall_spec()
    obstacle = wall["obstacles"][0]
    checks = {
        "worker_execute_calls_wall_penetration": "wall_penetration(pos[valid], mass[valid], spec" in worker,
        "worker_execute_accumulates_obstacle_frames": "obstacle_frames += check[\"obstacle_penetration_count\"]" in worker,
        "worker_execute_accumulates_saved_chords": "finite_geometry_chord_crossings" in worker and "segment_crossing_events" in worker,
        "worker_wall_spec_has_full_obstacle": len(wall.get("obstacles", [])) == 1,
        "observer_uses_finite_obstacle_distance": "_signed_obstacle_distance" in observer,
        "observer_marks_geometry_aware": '"geometry_aware": True' in observer,
        "observer_requires_horizon_return_tail": "horizon and all(index is not None" in observer and "required_post_return_tail_s" in observer,
        "evaluator_requires_event_complete": "and obs.get(\"event_window_complete\")" in observer,
        "evaluator_reads_actual_run_metrics": "read_run_metrics(product)" in observer,
    }
    return {
        "schema": "core.f1.h3.observer_audit.v1",
        "observer_revision": OBSERVER_REVISION_ID,
        "worker": _ref(worker_path, "F1 worker source"),
        "observer_evaluator": _ref(observer_path, "F1 observer/evaluator source"),
        "wall_spec": wall,
        "finite_obstacle": obstacle,
        "observable_names": list(OBSERVABLE_NAMES),
        "event_names": list(EVENT_NAMES),
        "event_window": {
            "initial_time_max_s": 2.20,
            "maximum_extended_time_max_s": 4.40,
            "completion": "horizon reached + approach/downstream/split/rejoin/return + gravity-time tail",
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "limitations": [
            "observer calibration is manufactured geometry evidence, not external physical validation",
            "H1 prepared matrix/jobs are not H3 inputs because their boundary recipe is native DBC",
            "qualification remains false until H3 canary, all 15 products, and comparator gates pass",
        ],
    }


def manufactured_observer_calibration(output: Path) -> dict[str, Any]:
    """Write the existing CPU-only manufactured calibration under the handoff."""
    output = Path(output).resolve()
    if output.exists():
        try:
            payload = json.loads(output.read_text())
        except json.JSONDecodeError as exc:
            raise HandoffError(f"invalid existing calibration: {output}") from exc
        if payload.get("schema") != "core.f1.observer.calibration.v1" or payload.get("passed") is not True:
            raise HandoffError(f"existing calibration is not passing: {output}")
        return payload
    payload = manufactured_calibration(output)
    return payload


def audit_canary_product(product: Path) -> dict[str, Any]:
    """Read one terminal H3 product and return a fail-closed admission report."""
    product = Path(product).resolve()
    required = {name: product / name for name in ("result.json", "audit.json", "observations.json")}
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        # A finished worker product can legitimately contain result/audit but no
        # observer file (the generic F1 CFD executor does not emit one for this
        # mDBC branch).  That is a terminal admission failure, not a transient
        # scheduler state.  Keep the distinction so a missing observer can
        # never be mistaken for an unfinished canary or a passing event gate.
        result_present = required["result.json"].is_file()
        audit_present = required["audit.json"].is_file()
        terminal_product = result_present and audit_present
        existing_hashes = {
            name: _sha256(path)
            for name, path in required.items()
            if path.is_file()
        }
        return {
            "schema": "core.f1.h3.canary_admission.v1",
            "status": "failed" if terminal_product else "awaiting_terminal_product",
            "passed": False,
            "product": str(product),
            "missing": missing,
            "terminal_product_detected": terminal_product,
            "artifact_hashes": existing_hashes,
            "reasons": [
                "terminal result.json and audit.json exist but required observations.json is missing"
                if terminal_product
                else "required result/audit/observations JSON is not available"
            ],
            "result_summary": (
                {
                    key: json.loads(required["result.json"].read_text()).get(key)
                    for key in (
                        "case_id",
                        "hard_integrity_pass",
                        "event_window_complete",
                        "requested_horizon_reached",
                        "obstacle_penetration_particle_frames",
                        "finite_geometry_chord_crossings",
                        "endpoint_violation_particle_frames",
                        "closed_wall_endpoint_particle_frames",
                    )
                }
                if terminal_product
                else None
            ),
            "qualification_claim": "none",
        }
    docs = {key: json.loads(path.read_text()) for key, path in required.items()}
    result, audit, observations = docs["result"], docs["audit"], docs["observations"]
    reasons: list[str] = []
    if result.get("case_id") != CANARY_CASE_ID or audit.get("case_id") != CANARY_CASE_ID:
        reasons.append("terminal product case identity is not H3")
    for label, doc in (("result", result), ("audit", audit)):
        if doc.get("hard_integrity_pass") is not True:
            reasons.append(f"{label}.hard_integrity_pass is false")
        if doc.get("event_window_complete") is not True:
            reasons.append(f"{label}.event_window_complete is false")
        if doc.get("requested_horizon_reached") is not True:
            reasons.append(f"{label}.requested_horizon_reached is false")
        if doc.get("obstacle_penetration_particle_frames") != 0:
            reasons.append(f"{label} has obstacle penetration frames")
        if doc.get("finite_geometry_chord_crossings") != 0:
            reasons.append(f"{label} has finite geometry chord crossings")
        if doc.get("closed_wall_endpoint_particle_frames") != 0:
            reasons.append(f"{label} has closed-wall endpoint frames")
    if observations.get("event_window_complete") is not True:
        reasons.append("observer event window is incomplete")
    prepared = product / "prepared.json"
    mass_pass = False
    if prepared.is_file():
        payload = json.loads(prepared.read_text())
        mass_pass = bool(payload.get("mass_preflight", {}).get("mass_gate_pass"))
    if not mass_pass:
        reasons.append("product prepared mass gate is absent or false")
    return {
        "schema": "core.f1.h3.canary_admission.v1",
        "status": "passed" if not reasons else "failed",
        "passed": not reasons,
        "product": str(product),
        "artifact_hashes": {key: _sha256(path) for key, path in required.items()},
        "mass_gate_pass": mass_pass,
        "hard_integrity_pass": result.get("hard_integrity_pass"),
        "event_window_complete": observations.get("event_window_complete"),
        "requested_horizon_reached": result.get("requested_horizon_reached"),
        "full_solid_obstacle_audit": {
            "obstacle_penetration_particle_frames": result.get("obstacle_penetration_particle_frames"),
            "finite_geometry_chord_crossings": result.get("finite_geometry_chord_crossings"),
            "closed_wall_endpoint_particle_frames": result.get("closed_wall_endpoint_particle_frames"),
        },
        "reasons": reasons,
        "qualification_claim": "none; canary admission only",
    }


def build_handoff(output_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    design = qualification_design()
    production = production_design(design)
    calibration_path = output_dir / "manufactured-observer-calibration.json"
    calibration = manufactured_observer_calibration(calibration_path)
    audit = observer_audit()
    if calibration.get("passed") is not True:
        raise HandoffError("manufactured observer calibration did not pass")
    if audit.get("all_checks_pass") is not True:
        raise HandoffError("F1 full-obstacle/complete-window source audit did not pass")
    _write_once(output_dir / "qualification-design.json", design)
    _write_once(output_dir / "production-design.json", production)
    _write_once(output_dir / "observer-audit.json", audit)
    handoff = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "recipe_id": RECIPE_ID,
        "status": "conditional_blocked_until_h3_canary",
        "qualification_claim": "none",
        "qualification_design": _ref(output_dir / "qualification-design.json", "H3 15-cell conditional design"),
        "production_design": _ref(output_dir / "production-design.json", "H3 32-case conditional production design"),
        "observer_audit": _ref(output_dir / "observer-audit.json", "F1 observer/full-obstacle audit"),
        "manufactured_calibration": _ref(calibration_path, "F1 manufactured observer calibration"),
        "canary_dependency": {
            "job_id": CANARY_JOB_ID,
            "case_id": CANARY_CASE_ID,
            "prepared": _ref(CANARY_PREPARED, "H3 canary prepared"),
            "required_pass_fields": [
                "hard_integrity_pass",
                "source mass gate",
                "requested_horizon_reached",
                "event_window_complete",
                "full solid obstacle audit",
            ],
            "admission_command": "f1_h3_qualification_handoff.py audit-canary --product <terminal-product>",
        },
        "matrix_materialization": {
            "authorized_now": False,
            "gen_case_run": False,
            "solver_run": False,
            "jobs_written": False,
            "central_ledger_written": False,
            "after_canary_pass": "materialize H3-specific 15 cells with bottom face at each dp, then run static hash/mass/normal preflight before jobs",
        },
        "production_batches": {
            "registered_denominator": 32,
            "first_batch_indices": list(FIRST_EIGHT),
            "first_batch_size": 8,
            "remaining_batch_size": 24,
            "requires_hash_verified_T1_receipt": True,
            "qualification_inheritance": False,
        },
        "legacy_records": {
            "old_design": _ref(LEGACY_DESIGN, "retained H1 design"),
            "old_evaluation": _ref(LEGACY_EVALUATION, "retained H1 evaluation"),
            "old_matrix_reusable": False,
            "reason": "old H1 native-DBC inputs do not bind the H3 mDBC bottom-face recipe",
        },
        "no_gpu": True,
        "no_ledger": True,
    }
    _write_once(output_dir / "handoff.json", handoff)
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--output-dir", type=Path, required=True)
    p = commands.add_parser("audit-canary")
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = build_handoff(args.output_dir)
        print(json.dumps({"status": result["status"], "qualification_claim": result["qualification_claim"], "no_gpu": True, "no_ledger": True}, indent=2))
        return 0
    result = audit_canary_product(args.product)
    if args.output:
        _write_once(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"passed", "awaiting_terminal_product"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
