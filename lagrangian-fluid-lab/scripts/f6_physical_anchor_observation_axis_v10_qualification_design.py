#!/usr/bin/env python3
"""Create the proposal-only F6 v10 13+2 qualification matrix.

The matrix is a design and static contract artifact.  It does not call GenCase,
the solver, CUDA, the runtime queue, the registry, the ledger, or the
qualification matrix.  Every cell requires a fresh Definition/XML/BI4; the
single v10 canary is hash-only context and contributes no qualification credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921"
)
PREFLIGHT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921/preflight.json"
)
CANARY = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/"
    "attempt-001/execution-receipt.json"
)
OUTPUT_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-qualification-design-20260921"
)

SCOPE_ID = "F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3"
REVISION_ID = "F6_observation_axis_13plus2_v4"
FAMILY = "F6"
PARAMETER_NAME = "body_release_com_z_m"
PARAMETER_RANGE = (0.49, 0.61)
Q_POINTS = (0.0, 0.5, 1.0, 0.25, 0.75)
ANCHOR_Q = (0.0, 0.5, 1.0)
HELD_OUT_Q = (0.25, 0.75)
RESOLUTIONS = (0.025, 0.020, 0.015)
PRODUCTION_DP = 0.020
FINE_DP = 0.015
TIME_END_S = 1.5
MAX_EXTENDED_TIME_S = 3.0
OUTPUT_INTERVAL_S = 0.005
NATIVE_OUTPUT_INTERVAL_S = 0.0025
MAX_GAP_S = 0.0055
NATIVE_MAX_GAP_S = 0.00275
BODY_SIZE = (0.20, 0.16, 0.12)
BODY_COM_XY = (0.75, 0.30)
FLUID_LOW = (0.175, 0.05, 0.04)
FLUID_SIZE = (1.14, 0.465, 0.24)
FLUID_SURFACE_Z = FLUID_LOW[2] + FLUID_SIZE[2]
GRAVITY_Z = -9.81


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ref(path: Path, role: str, *, hash_only: bool = False) -> dict[str, Any]:
    path = path.resolve()
    try:
        display = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {
        "path": display,
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "role": role,
        "hash_only": hash_only,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def q_text(q: float) -> str:
    return f"{q:.2f}".replace(".", "p")


def dp_text(dp: float) -> str:
    return f"{dp:.3f}".replace(".", "p")


def release_z(q: float) -> float:
    return PARAMETER_RANGE[0] + q * (PARAMETER_RANGE[1] - PARAMETER_RANGE[0])


def event_prediction(q: float) -> dict[str, Any]:
    com_z = release_z(q)
    contact_com_z = FLUID_SURFACE_Z + BODY_SIZE[2] / 2.0
    drop = com_z - contact_com_z
    if drop <= 0:
        raise ValueError(f"q={q} starts below/inside the fluid surface")
    contact_time = math.sqrt(2.0 * drop / abs(GRAVITY_Z))
    window = [max(0.0, contact_time - 0.02), contact_time + 0.02]
    return {
        "initial_body_com_z_m": com_z,
        "fluid_surface_z_m": FLUID_SURFACE_Z,
        "predicted_contact_com_z_m": contact_com_z,
        "predicted_drop_distance_m": drop,
        "predicted_contact_time_s": contact_time,
        "contact_prediction_window_s": window,
        "analytic_only": True,
    }


def expected_frame_count(output_interval_s: float) -> int:
    return int(round((TIME_END_S / output_interval_s))) + 1


def design_signature() -> list[tuple[float, float, str]]:
    cells: list[tuple[float, float, str]] = []
    for q in (0.0, 0.5, 1.0):
        cells.extend((q, dp, "spatial") for dp in RESOLUTIONS)
    for q in HELD_OUT_Q:
        cells.extend((q, dp, "spatial_held_out") for dp in (PRODUCTION_DP, FINE_DP))
    cells.extend(
        (
            (0.5, PRODUCTION_DP, "internal_time"),
            (0.5, PRODUCTION_DP, "native_output"),
        )
    )
    return cells


def cell(q: float, dp: float, kind: str) -> dict[str, Any]:
    role = "production" if math.isclose(dp, PRODUCTION_DP) else "fine_reference"
    event = event_prediction(q)
    cell_id = (
        f"F6_OBS_V10_Q{q_text(q)}_DP{dp_text(dp)}_{kind}"
    ).upper()
    case_id = f"{cell_id}_fresh_case"
    definition_id = f"CORE_{cell_id}_Definition"
    if kind == "internal_time":
        time = {
            "variant": "internal_time_step",
            "cfl": 0.10,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "max_native_gap_s": MAX_GAP_S,
            "comparison_to": "F6_OBS_V10_Q0P50_DP0P020_spatial",
            "actual_step_count_required": True,
        }
    elif kind == "native_output":
        time = {
            "variant": "native_output_cadence",
            "cfl": 0.20,
            "output_interval_s": NATIVE_OUTPUT_INTERVAL_S,
            "max_native_gap_s": NATIVE_MAX_GAP_S,
            "comparison_to": "F6_OBS_V10_Q0P50_DP0P020_spatial",
            "actual_step_count_unchanged_by_design": True,
        }
    else:
        time = {
            "variant": "baseline",
            "cfl": 0.20,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "max_native_gap_s": MAX_GAP_S,
        }
    frame_count = expected_frame_count(float(time["output_interval_s"]))
    time["expected_frame_count"] = frame_count
    return {
        "schema": "core.cfd.v1",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "cell_id": cell_id,
        "case_id": case_id,
        "definition_id": definition_id,
        "design_cell": kind,
        "stage": "qualification",
        "qualification_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "split": "qualification_only",
        "parameter": {
            "name": PARAMETER_NAME,
            "q": q,
            "value_m": release_z(q),
            "candidate_range_m": list(PARAMETER_RANGE),
            "interpretation": "initial floating-body center-of-mass release height",
        },
        "resolution": {"dp_m": dp, "role": role, "registered_resolutions_m": list(RESOLUTIONS)},
        "geometry": {
            "fluid_low_m": list(FLUID_LOW),
            "fluid_size_m": list(FLUID_SIZE),
            "body_size_m": list(BODY_SIZE),
            "body_com_xy_m": list(BODY_COM_XY),
            "body_com_z_m": release_z(q),
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
        },
        "physics": {
            "gravity_m_s2": [0.0, 0.0, GRAVITY_Z],
            "fluid_density_kg_m3": 1000.0,
            "body_density_kg_m3": 780.0,
            "initial_fluid_velocity_m_s": [0.0, 0.0, 0.0],
            "initial_body_velocity_m_s": [0.0, 0.0, 0.0],
        },
        "time_contract": {
            **time,
            "time_start_s": 0.0,
            "time_end_target_s": TIME_END_S,
            "maximum_extended_time_s": MAX_EXTENDED_TIME_S,
            "terminal_overshoot_max_s": 0.0005 if time["output_interval_s"] == OUTPUT_INTERVAL_S else 0.00025,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "observation_hold_s": [1.0, 1.5],
            "equilibrium_status": "not_claimed",
        },
        "event_contract": {
            **event,
            "expected_frame_count": frame_count,
            "observation_window_s": [1.0, 1.5],
            "event_window_complete_required": True,
            "one_whole_scope_extension_allowed": True,
            "extension_policy": "if_hard_complete_but_event_censored_extend_all_cells_to_2T_once",
        },
        "fresh_input_contract": {
            "fresh_definition_required": True,
            "fresh_generated_xml_required": True,
            "fresh_generated_bi4_required": True,
            "old_v10_canary_used_as_input": False,
            "old_v10_canary_context_hash_only": True,
            "prior_scope_qualification_inherited": False,
        },
        "hard_gates": [
            "fresh Definition/XML/BI4 hashes match this cell identity",
            "native particle IDs unique and fixed; arrays finite",
            "fluid/body counts and continuous-mass error pass per-cell gate",
            "body mass/COM/inertia metadata match this cell contract",
            f"{frame_count} native frames with actual TimeStep gaps within cell bound",
            "terminal actual time brackets target without overshoot violation",
            "contact time lies in the independently recomputed window",
            "closed-face contact and penetration remain zero",
            "open-top mass flux is zero",
            "observation hold is bracketed without equilibrium claim",
        ],
        "execution_policy": {
            "exactly_one_initial_attempt_per_cell": True,
            "same_input_retry": False,
            "infrastructure_retry_requires_new_attempt_record": True,
            "science_failure_retry": False,
            "queue_submission": False,
            "registry_mutation": False,
            "ledger_mutation": False,
            "matrix_credit": 0,
        },
    }


def build_design() -> dict[str, Any]:
    if not SOURCE.is_dir() or not PREFLIGHT.is_file() or not CANARY.is_file():
        raise FileNotFoundError("F6 v10 source/preflight/canary evidence is incomplete")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    canary = json.loads(CANARY.read_text(encoding="utf-8"))
    if preflight.get("T1") is not False or preflight.get("qualification_credit") != 0:
        raise ValueError("v10 preflight is not non-qualifying")
    if canary.get("T1") is not False or canary.get("qualification_credit") != 0:
        raise ValueError("v10 canary is not non-qualifying")
    cells = [cell(*row) for row in design_signature()]
    spatial = [item for item in cells if item["design_cell"] in {"spatial", "spatial_held_out"}]
    comparisons = [item for item in cells if item["design_cell"] in {"internal_time", "native_output"}]
    assert len(spatial) == 13 and len(comparisons) == 2
    return {
        "schema": "core.f6.observation_axis.qualification_design.v1",
        "record_id": "F6_observation_axis_v10_qualification_design_v4_20260921",
        "created_at_utc": stamp(),
        "status": "root_review_only_not_submitted",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "qualification_only": True,
        "matrix_cell_count": len(cells),
        "spatial_cell_count": len(spatial),
        "time_output_comparison_count": len(comparisons),
        "parameter": {
            "name": PARAMETER_NAME,
            "range_m": list(PARAMETER_RANGE),
            "q_points": list(Q_POINTS),
            "anchor_q": list(ANCHOR_Q),
            "held_out_q": list(HELD_OUT_Q),
            "axis_interpretation": "initial body center-of-mass release height",
            "geometry_revision": "aligned_sampling_box_v3",
        },
        "resolutions_m": list(RESOLUTIONS),
        "registered_window": {
            "initial_time_max_s": TIME_END_S,
            "maximum_extended_time_s": MAX_EXTENDED_TIME_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "observation_hold_s": [1.0, 1.5],
            "baseline_expected_frame_count": expected_frame_count(OUTPUT_INTERVAL_S),
            "native_output_expected_frame_count": expected_frame_count(NATIVE_OUTPUT_INTERVAL_S),
            "event_complete_required": True,
            "one_whole_scope_extension_allowed": True,
        },
        "cells": cells,
        "source_bindings": {
            "fresh_v10_definition_contract": ref(SOURCE / "definition-contract.json", "v10 base contract", hash_only=True),
            "fresh_v10_preflight": ref(PREFLIGHT, "v10 input preflight; context only", hash_only=True),
            "fresh_v10_solver_canary": ref(CANARY, "v10 runtime canary; context only", hash_only=True),
        },
        "execution_controls": {
            "definition_written": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "admission_requirements": [
            "root reviews all 15 cell identities and hard gates",
            "static GenCase/native preflight executes once per fresh cell before solver authorization",
            "all source binaries and generated inputs are content-hash bound",
            "qualification-only outputs remain outside train/validation/model-selection splits",
            "no cell is credited from the v10 canary without its own matrix evidence",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    design = build_design()
    write_json(output / "design.json", design)
    write_json(output / "matrix.json", {"schema": "core.f6.observation_axis.qualification_matrix.v1", "design_ref": ref(output / "design.json", "matrix design"), "cells": design["cells"], "submitted": False, "qualification_credit": 0})
    write_json(output / "candidate-card.json", {"schema": "core.f6.observation_axis.candidate_card.v1", "status": design["status"], "family": FAMILY, "scope_id": SCOPE_ID, "revision_id": REVISION_ID, "parameter": design["parameter"], "matrix_cell_count": design["matrix_cell_count"], "qualification_claim": "none", "T1": False, "source_bindings": design["source_bindings"], "execution_controls": design["execution_controls"]})
    print(json.dumps({"status": design["status"], "cell_count": design["matrix_cell_count"], "spatial": design["spatial_cell_count"], "time_output": design["time_output_comparison_count"], "output_dir": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
