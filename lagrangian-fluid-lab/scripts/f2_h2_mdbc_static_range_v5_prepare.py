#!/usr/bin/env python3
"""Prepare and audit the independent F2 H2 v5 sampling repair.

The v4 failure at q=.75, dp=.0075 is a source-layer quadrature failure: the
fixed 43 x 29 lateral lattice makes the nearest integer third-layer count
16, whose source mass is 2.8061% high.  v5 keeps the two lower source layers
and the continuous footprint unchanged, but chooses the third layer's
lateral integer lattice from a frozen, centered candidate set.  For cell 11
that produces 42 x 29 x 16 and a 0.4153% third-layer error.

This module reuses only the v4 GenCase/native conversion and hard preflight
plumbing.  Its sampling rule, case IDs, lineage checks and fixed-denominator
report are independent.  It can run CPU GenCase and the native decoder for
explicit cells; it never invokes DualSPHysics solver, CUDA, queue, ledger or
registry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f2_h2_mdbc_static_range_prepare as v4


CANDIDATE_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v5.json"
)
PARENT_CANDIDATE_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v2.json"
)
PARENT_MATRIX_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/prepared-20260920-v4/matrix-preparation.json"
)
PARENT_CELL_PREFLIGHT_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/prepared-20260920-v4/cells/11-CORE_F2_H2_mdbc_static_range_q0p75000000_dp0p007500000000_spatial_held_out/preflight.json"
)
SCHEMA = "core.f2.h2_mdbc.static_range_v5_preparation.v1"
EXPECTED_CELL_COUNT = 15
MASS_DENSITY_KG_M3 = 1000.0


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(lab: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = lab / path
    return path.resolve()


def _digest(path: Path) -> str:
    return v4._digest(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    v4._write_json(path, value)


def _ref(path: Path, lab: Path, role: str) -> dict[str, Any]:
    return v4._ref(path, lab, role)


def _candidate_cells(card: dict[str, Any]) -> list[dict[str, Any]]:
    # The parent validator checks the fixed 15-row shape and the frozen mDBC
    # controls.  This module adds v5-specific identity checks afterwards.
    cells = v4._validate_candidate(card)
    if card.get("candidate_id") != "F2_H2_mdbc_static_range_qualification_v5":
        raise ValueError("unexpected H2 v5 candidate identity")
    if card.get("scope_id") != "F2_H2_mdbc_static_range_qualification_v5":
        raise ValueError("unexpected H2 v5 scope")
    if card.get("revision_id") != "F2_H2_mdbc_static_range_mdbc_v5_top_layer_lateral_lattice":
        raise ValueError("unexpected H2 v5 sampling revision")
    if card.get("T1_numerical") is not False:
        raise ValueError("v5 candidate must explicitly retain T1_numerical=false")
    if card.get("registry_mutation") != 0 or card.get("central_ledger_mutation") != 0:
        raise ValueError("v5 candidate attempts registry or ledger mutation")
    if card.get("physical_contract", {}).get("initial_particle_spectrum_changed_from_v4") is not True:
        raise ValueError("v5 candidate must declare a new initial particle spectrum")
    if card.get("physical_contract", {}).get("continuous_geometry_changed_from_v4") is not False:
        raise ValueError("v5 continuous geometry must remain unchanged")
    policy = card.get("discrete_sampling_hypothesis", {})
    if policy.get("hypothesis_id") != "H2_v5_top_layer_lateral_lattice_balance":
        raise ValueError("v5 sampling hypothesis is not bound")
    if policy.get("cell_11_new_counts") != [42, 29, 16]:
        raise ValueError("v5 cell-11 repair counts changed")
    if policy.get("cell_11_new_third_source_error", 1.0) >= 0.025:
        raise ValueError("v5 cell-11 analytic repair does not meet the frozen source gate")
    parent_ids = {
        str(row.get("case_id"))
        for row in card.get("lineage", {}).get("parent_candidate", {}).get("qualification_design", {}).get("cells", [])
    }
    # The parent card stores its cells under the JSON file, so load it in
    # _load_inputs_and_lineage where the hash is checked.  Here we enforce the
    # simple, auditable suffix rule that makes v5 input identities new.
    for cell in cells:
        if "_v5_" not in str(cell.get("case_id")):
            raise ValueError(f"v5 cell {cell['index']} does not have a new case ID")
    return cells


def _load_inputs_and_lineage(
    lab: Path, candidate_path: Path, card: dict[str, Any],
    gencase_path: Path | None, decoder_path: Path | None,
) -> dict[str, Any]:
    inputs = v4._load_inputs(lab, candidate_path, card, gencase_path, decoder_path)
    lineage = card.get("lineage", {})
    parent_candidate = _resolve(lab, lineage.get("parent_candidate", {}).get("path", PARENT_CANDIDATE_RELATIVE))
    parent_matrix = _resolve(lab, lineage.get("parent_matrix", {}).get("path", PARENT_MATRIX_RELATIVE))
    parent_preflight = _resolve(lab, lineage.get("parent_failed_cell", {}).get("path", PARENT_CELL_PREFLIGHT_RELATIVE))
    for name, path, item in (
        ("parent candidate", parent_candidate, lineage.get("parent_candidate", {})),
        ("parent matrix", parent_matrix, lineage.get("parent_matrix", {})),
        ("parent cell-11 preflight", parent_preflight, lineage.get("parent_failed_cell", {})),
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
        if item.get("sha256") and _digest(path) != item["sha256"]:
            raise ValueError(f"{name} hash differs from the v5 lineage record")
    parent_card = json.loads(parent_candidate.read_text())
    parent_cells = parent_card.get("qualification_design", {}).get("cells", [])
    current_ids = {str(cell["case_id"]) for cell in card["qualification_design"]["cells"]}
    parent_ids = {str(cell["case_id"]) for cell in parent_cells}
    if current_ids & parent_ids:
        raise ValueError("v5 reuses a parent case ID")
    parent_preflight_payload = json.loads(parent_preflight.read_text())
    if parent_preflight_payload.get("preflight_pass") is not False:
        raise ValueError("v5 lineage parent cell 11 is not a retained failed preflight")
    old_source_errors = parent_preflight_payload.get("mass_gate", {}).get("source_relative_errors", [])
    if len(old_source_errors) != 3 or abs(float(old_source_errors[2]) - 0.02806106870228997) > 1e-12:
        raise ValueError("v5 lineage does not bind the known 0.0280611 parent failure")
    inputs["parent_lineage"] = {
        "parent_candidate": _ref(parent_candidate, lab, "H2 v4 parent candidate card"),
        "parent_matrix": _ref(parent_matrix, lab, "H2 v4 fixed-denominator matrix preparation"),
        "parent_failed_cell": _ref(parent_preflight, lab, "H2 v4 retained cell-11 failed preflight"),
        "parent_cell_11_source_relative_errors": [float(value) for value in old_source_errors],
    }
    # Hash the independent module as well as the v4 plumbing it deliberately
    # reuses.  A reviewer can therefore distinguish sampling logic from the
    # conversion and normal preflight implementation.
    inputs["tool_closure"].append(_ref(Path(__file__), lab, "H2 v5 independent sampling preparer code"))
    return inputs


def _centered_first(low: float, size: float, count: int, dp: float) -> float:
    span = (int(count) - 1) * float(dp)
    margin = float(size) - span
    if margin < -1e-10:
        raise ValueError(f"centered lattice span {span} exceeds source size {size}")
    return float(low) + max(0.0, margin) * 0.5


def _axis_candidates(size: float, dp: float) -> tuple[int, ...]:
    nominal = int(math.floor(float(size) / float(dp) + 1e-9))
    upper = int(math.ceil(float(size) / float(dp) - 1e-12))
    values = []
    for count in range(max(1, nominal - 1), max(1, upper) + 1):
        if (count - 1) * float(dp) <= float(size) + 1e-10:
            values.append(int(count))
    return tuple(sorted(set(values)))


def _select_top_lateral_lattice(
    x_size: float, y_size: float, dp: float, top_count: int, top_height: float,
    nominal_x: int, nominal_y: int,
) -> tuple[int, int, float]:
    area = float(x_size) * float(y_size)
    top_volume = area * float(top_height)
    choices: list[tuple[tuple[float, int, int, int, int], int, int, float]] = []
    for nx in _axis_candidates(x_size, dp):
        for ny in _axis_candidates(y_size, dp):
            error = (float(nx * ny * top_count) * float(dp) ** 3) / top_volume - 1.0
            score = (
                abs(float(error)),
                abs(int(nx) - int(nominal_x)) + abs(int(ny) - int(nominal_y)),
                int(nx) + int(ny),
                int(nx),
                int(ny),
            )
            choices.append((score, int(nx), int(ny), float(error)))
    if not choices:
        raise ValueError("v5 top-layer lateral candidate set is empty")
    _, nx, ny, error = min(choices, key=lambda item: item[0])
    return nx, ny, error


def _sampling_for_cell(cell: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    contract = card["physical_contract"]
    footprint = contract["fluid_initial_condition"]["footprint"]
    axis = card["parameter_axis"]
    q = float(cell["q"])
    volume = float(axis["volume_at_q_m3"][str(q)])
    x_size, y_size = (float(value) for value in footprint["size_m"][:2])
    area = x_size * y_size
    height = volume / area
    base_height = float(footprint["base_layer_height_m"])
    top_height = height - 2.0 * base_height
    if top_height <= 0.0:
        raise ValueError(f"q={q} has no positive third-layer height")
    dp = float(cell["dp_m"])
    low = [float(value) for value in footprint["low_m"]]
    nominal_x = v4._lattice_count(x_size, dp)
    nominal_y = v4._lattice_count(y_size, dp)
    base_count = v4._lattice_count(base_height, dp, z_layer=True)
    top_count, target_top_count = v4._select_third_layer_count(
        nominal_x, nominal_y, dp, area, top_height, volume, base_count
    )
    top_x, top_y, top_error = _select_top_lateral_lattice(
        x_size, y_size, dp, top_count, top_height, nominal_x, nominal_y
    )
    layers = [
        {"mkfluid": 0, "z_low": low[2], "z_size": base_height, "nx": nominal_x, "ny": nominal_y, "nz": base_count},
        {"mkfluid": 1, "z_low": low[2] + base_height, "z_size": base_height, "nx": nominal_x, "ny": nominal_y, "nz": base_count},
        {"mkfluid": 2, "z_low": low[2] + 2.0 * base_height, "z_size": top_height, "nx": top_x, "ny": top_y, "nz": top_count},
    ]
    boxes: list[dict[str, Any]] = []
    for layer in layers:
        count_x, count_y, count_z = (int(layer[key]) for key in ("nx", "ny", "nz"))
        first_x = (
            _centered_first(low[0], x_size, count_x, dp)
            if int(layer["mkfluid"]) == 2 else v4._first_center(low[0], dp)
        )
        first_y = (
            _centered_first(low[1], y_size, count_y, dp)
            if int(layer["mkfluid"]) == 2 else v4._first_center(low[1], dp)
        )
        first_z = v4._first_center(float(layer["z_low"]), dp)
        draw_size: list[float] = []
        endpoint_guards: list[float] = []
        for axis_name, count in zip("xyz", (count_x, count_y, count_z)):
            extent, guard = v4._draw_extent(axis_name, count, dp)
            draw_size.append(float(extent))
            endpoint_guards.append(float(guard))
        box_volume = x_size * y_size * float(layer["z_size"])
        discrete_mass = float(count_x * count_y * count_z * dp ** 3 * MASS_DENSITY_KG_M3)
        boxes.append({
            "continuous_low_m": [low[0], low[1], float(layer["z_low"])],
            "continuous_size_m": [x_size, y_size, float(layer["z_size"])],
            "first_center_m": [float(first_x), float(first_y), float(first_z)],
            "draw_size_m": draw_size,
            "drawbox_endpoint_guard_m": endpoint_guards,
            "counts": [count_x, count_y, count_z],
            "particle_count": int(count_x * count_y * count_z),
            "continuous_volume_m3": float(box_volume),
            "continuous_mass_kg": float(box_volume * MASS_DENSITY_KG_M3),
            "discrete_mass_kg": discrete_mass,
            "mkfluid": int(layer["mkfluid"]),
            "native_cell_centre_sampling": True,
            "top_layer_lateral_recentered": int(layer["mkfluid"]) == 2,
            "mass_policy": "native rho*dp^3; no mass rescaling",
        })
    expected_particles = int(sum(item["particle_count"] for item in boxes))
    discrete_mass = float(expected_particles * dp ** 3 * MASS_DENSITY_KG_M3)
    source_errors = [
        float(item["discrete_mass_kg"] / item["continuous_mass_kg"] - 1.0)
        for item in boxes
    ]
    return {
        "fluid_boxes": boxes,
        "expected_fluid_particles": expected_particles,
        "continuous_low_m": [low[0], low[1], low[2]],
        "continuous_size_m": [x_size, y_size, height],
        "continuous_volume_m3": volume,
        "continuous_mass_kg": float(volume * MASS_DENSITY_KG_M3),
        "sampled_mass_kg": discrete_mass,
        "counts": [nominal_x, nominal_y, int(2 * base_count + top_count)],
        "layer_counts": [item["counts"] for item in boxes],
        "z_layer_counts": [base_count, base_count, top_count],
        "target_total_native_layers": int(2 * base_count + top_count),
        "target_third_layer_count": float(target_top_count),
        "selected_third_layer_count": int(top_count),
        "selected_top_lateral_counts": [int(top_x), int(top_y)],
        "nominal_lateral_counts": [int(nominal_x), int(nominal_y)],
        "top_layer_lateral_error": float(top_error),
        "layer_count_selection": "v4 integer z-layer choice on nominal lower-layer footprint; v5 top-layer lateral count minimizes absolute top-source mass error",
        "lateral_candidate_rule": "floor(size/dp)-1 through ceil(size/dp), centered in the unchanged source footprint",
        "source_relative_errors": source_errors,
        "discrete_to_continuum_mass_error": float(discrete_mass / (volume * MASS_DENSITY_KG_M3) - 1.0),
        "mass_policy": "native rho*dp^3; no mass rescaling",
        "sampling_revision": "H2_v5_top_layer_lateral_lattice_balance",
    }


def _prepare_cell(
    lab: Path, output: Path, cell: dict[str, Any], card: dict[str, Any],
    inputs: dict[str, Any], native_output_interval_s: float | None = None,
    run_gencase_fn: Callable[..., None] = v4._run_gencase,
    decode_fn: Callable[..., tuple] = v4._decode_native,
) -> dict[str, Any]:
    cell_dir = output / "cells" / f"{int(cell['index']):02d}-{cell['case_id']}"
    cell_dir.mkdir(parents=True, exist_ok=False)
    sampling = _sampling_for_cell(cell, card)
    interval = v4._output_interval(cell, native_output_interval_s)
    definition = cell_dir / f"{cell['case_id']}_Def.xml"
    motion = cell_dir / f"{cell['case_id']}_motion.dat"
    audit = v4._rewrite_definition(inputs["source"], definition, cell, sampling, motion.name, interval, card)
    v4._write_zero_motion(motion, interval)
    prefix = cell_dir / "generated" / cell["case_id"]
    log_path = cell_dir / "gencase.log"
    run_gencase_fn(inputs["gencase"], definition, prefix, log_path, cell_dir, lab)
    generated_xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    decode_dir = cell_dir / "decoded"
    preflight = v4._preflight(generated_xml, bi4, decode_dir, inputs["decoder"], sampling, cell, card, decode_fn)
    _write_json(cell_dir / "preflight.json", preflight)
    closure = [
        _ref(path, lab, f"v5 cell artifact: {path.relative_to(cell_dir)}")
        for path in v4._closure_files(cell_dir, {cell_dir / "prepared.json"})
    ]
    closure.extend(inputs["tool_closure"])
    prepared = {
        "schema": "core.f2.h2_mdbc.static_range_v5.cell_prepared.v1",
        "created_at": _stamp(),
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "parent_scope_id": card["parent_scope_id"],
        "anchor_scope_id": card["anchor_evidence"]["prepared"]["scope_id"],
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "temporal_variant": cell.get("temporal_variant"),
        "time_max_s": v4.TIME_MAX_S,
        "output_interval_s": interval,
        "registered_output_interval_s": v4.REGISTERED_OUTPUT_INTERVAL_S,
        "sampling": sampling,
        "definition_audit": audit,
        "generated_prefix": str(prefix.resolve()),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_pass": bool(preflight["preflight_pass"]),
        "mdbc_normal_gate": preflight["mdbc_normal_gate"],
        "mass_gate": preflight["mass_gate"],
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutated": False,
        "ledger_mutated": False,
        "registry_mutated": False,
        "hash_closure": closure,
        "hash_closure_pass": all(item["sha256"] for item in closure),
        "qualification_only": True,
        "T1_numerical": False,
        "qualification_claim": "none; independent H2 v5 CPU Definition/GenCase/native decode preflight only",
    }
    _write_json(cell_dir / "prepared.json", prepared)
    return {
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "status": "prepared" if preflight["preflight_pass"] else "failed",
        "attempted": True,
        "preflight_pass": bool(preflight["preflight_pass"]),
        "qualification_credit": False,
        "mass_error_relative": float(preflight["mass_gate"]["mass_error_relative"]),
        "source_relative_errors": list(preflight["mass_gate"]["source_relative_errors"]),
        "selected_top_lateral_counts": list(sampling["selected_top_lateral_counts"]),
        "native_zero_boundary_normals": preflight["mdbc_normal_gate"]["zero_boundary_normals"],
        "prepared": str((cell_dir / "prepared.json").resolve()),
        "prepared_sha256": _digest(cell_dir / "prepared.json"),
        "preflight": str((cell_dir / "preflight.json").resolve()),
        "preflight_sha256": _digest(cell_dir / "preflight.json"),
        "hash_closure_pass": bool(prepared["hash_closure_pass"]),
        "failure": None if preflight["preflight_pass"] else "H2 v5 native preflight gate failed",
    }


def _failure_row(output: Path, cell: dict[str, Any], error: BaseException) -> dict[str, Any]:
    cell_dir = output / "cells" / f"{int(cell['index']):02d}-{cell['case_id']}"
    cell_dir.mkdir(parents=True, exist_ok=True)
    failure = {
        "schema": "core.f2.h2_mdbc.static_range_v5.cell_failure.v1",
        "created_at": _stamp(),
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "status": "failed",
        "error_type": type(error).__name__,
        "error": str(error),
        "qualification_only": True,
        "T1_numerical": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutated": False,
        "ledger_mutated": False,
        "registry_mutated": False,
        "qualification_claim": "none; raw H2 v5 CPU preparation failure retained",
    }
    path = cell_dir / "failure.json"
    _write_json(path, failure)
    return {
        "index": int(cell["index"]),
        "case_id": cell["case_id"],
        "q": float(cell["q"]),
        "dp_m": float(cell["dp_m"]),
        "design_cell": cell["design_cell"],
        "held_out": bool(cell.get("held_out", False)),
        "status": "failed",
        "attempted": True,
        "preflight_pass": False,
        "qualification_credit": False,
        "mass_error_relative": None,
        "source_relative_errors": None,
        "selected_top_lateral_counts": None,
        "native_zero_boundary_normals": None,
        "prepared": None,
        "prepared_sha256": None,
        "preflight": None,
        "preflight_sha256": None,
        "hash_closure_pass": False,
        "failure": {"type": type(error).__name__, "message": str(error)},
        "failure_artifact": str(path.resolve()),
        "failure_artifact_sha256": _digest(path),
    }


def _base_rows(cells: list[dict[str, Any]], card: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        sampling = _sampling_for_cell(cell, card)
        rows.append({
            "index": int(cell["index"]),
            "case_id": cell["case_id"],
            "q": float(cell["q"]),
            "dp_m": float(cell["dp_m"]),
            "design_cell": cell["design_cell"],
            "held_out": bool(cell.get("held_out", False)),
            "status": "unattempted",
            "attempted": False,
            "qualification_credit": False,
            "preflight_pass": False,
            "predicted_sampling": {
                "layer_counts": sampling["layer_counts"],
                "source_relative_errors": sampling["source_relative_errors"],
                "discrete_to_continuum_mass_error": sampling["discrete_to_continuum_mass_error"],
                "selected_top_lateral_counts": sampling["selected_top_lateral_counts"],
                "target_third_layer_count": sampling["target_third_layer_count"],
            },
            "failure": None,
        })
    return rows


def _report_base(card: dict[str, Any], inputs: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    design = card["qualification_design"]
    return {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "family": "F2",
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "parent_scope_id": card["parent_scope_id"],
        "anchor_scope_id": card["anchor_evidence"]["prepared"]["scope_id"],
        "qualification_only": True,
        "qualified": False,
        "T1_numerical": False,
        "candidate_card": inputs["candidate_ref"],
        "registered_cell_count": EXPECTED_CELL_COUNT,
        "registered_design": {
            "cell_count": int(design["cell_count"]),
            "spatial_cell_count": sum(str(cell["design_cell"]).startswith("spatial") for cell in cells),
            "temporal_cell_count": sum(str(cell["design_cell"]) in {"internal_time", "native_output"} for cell in cells),
            "registered_window_s": v4.TIME_MAX_S,
            "registered_output_interval_s": v4.REGISTERED_OUTPUT_INTERVAL_S,
            "parameter_axis": "q",
            "boundary_method": "mDBC Boundary=2",
            "normal_support": {"vdp": -0.5, "distanceh": 3.0, "svshapes": True},
            "sampling_revision": "H2_v5_top_layer_lateral_lattice_balance",
        },
        "failure_denominator": {
            "fixed_registered_cell_denominator": EXPECTED_CELL_COUNT,
            "all_rows_in_denominator": True,
            "unprepared_rows_are_not_successes": True,
            "failed_rows_are_not_dropped": True,
            "survivor_renormalization": False,
            "parent_v4_failed_cell_11_retained": True,
            "parent_v4_failure": inputs["parent_lineage"]["parent_failed_cell"],
            "parent_v4_cell_11_source_relative_errors": inputs["parent_lineage"]["parent_cell_11_source_relative_errors"],
            "rows": _base_rows(cells, card),
        },
        "execution_controls": {
            "cpu_gencase_allowed": True,
            "cpu_native_decoder_allowed": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "solver_binary_read_or_hashed": False,
            "matrix_jobs_materialized": False,
            "qualification_claim_allowed": False,
        },
        "dependency_closure": {
            "tool_inputs": inputs["tool_closure"],
            "frozen_anchor_inputs": inputs["frozen_anchor_inputs"],
            "parent_lineage": inputs["parent_lineage"],
            "solver_reference_skipped": inputs["solver_reference_skipped"],
        },
        "discrete_sampling_hypothesis": card["discrete_sampling_hypothesis"],
        "qualification_claim": "none; CPU-only H2 v5 sampling repair preparation; no solver trajectory or range qualification",
        "candidate_matrix_inputs_materialized": False,
        "candidate_matrix_jobs_materialized": False,
    }


def plan_matrix(
    lab: Path, candidate_path: Path, output: Path,
    gencase_path: Path | None = None, decoder_path: Path | None = None,
) -> dict[str, Any]:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _candidate_cells(card)
    inputs = _load_inputs_and_lineage(lab, candidate_path, card, gencase_path, decoder_path)
    report = _report_base(card, inputs, cells)
    report.update({
        "status": "plan_only",
        "selected_indices": [],
        "prepared_cell_count": 0,
        "failed_cell_count": 0,
        "unattempted_cell_count": EXPECTED_CELL_COUNT,
        "cells": _base_rows(cells, card),
        "execution_controls": {**report["execution_controls"], "plan_only": True, "gen_case_run": False, "decoder_run": False},
    })
    output = Path(output).resolve()
    if output.suffix.lower() == ".json":
        if output.exists() and output.is_dir():
            raise ValueError(f"v5 plan output is both a file and directory: {output}")
        report["matrix_output"] = str(output.parent)
        report["matrix_output_report"] = str(output)
        _write_json(output, report)
    else:
        if output.exists() and output.is_dir() and any(output.iterdir()):
            raise ValueError(f"v5 plan output must be fresh or empty: {output}")
        report["matrix_output"] = str(output)
        report["matrix_output_report"] = str((output / "matrix-preparation.json").resolve())
        _write_json(output / "matrix-preparation.json", report)
    return report


def prepare_matrix(
    lab: Path, candidate_path: Path, output: Path, cell_indices: list[int],
    all_cells: bool = False, gencase_path: Path | None = None,
    decoder_path: Path | None = None, native_output_interval_s: float | None = None,
    run_gencase_fn: Callable[..., None] = v4._run_gencase,
    decode_fn: Callable[..., tuple] = v4._decode_native,
) -> dict[str, Any]:
    lab = Path(lab).resolve()
    candidate_path = _resolve(lab, candidate_path)
    card = json.loads(candidate_path.read_text())
    cells = _candidate_cells(card)
    inputs = _load_inputs_and_lineage(lab, candidate_path, card, gencase_path, decoder_path)
    selected = list(range(EXPECTED_CELL_COUNT)) if all_cells else sorted(set(int(index) for index in cell_indices))
    if not selected:
        raise ValueError("v5 prepare requires explicit --cell-index values or --all-cells")
    if any(index < 0 or index >= EXPECTED_CELL_COUNT for index in selected):
        raise ValueError("v5 cell indices must be in the fixed range 0..14")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"v5 preparation output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    report = _report_base(card, inputs, cells)
    rows = _base_rows(cells, card)
    by_index = {int(cell["index"]): cell for cell in cells}
    materialized = []
    for index in selected:
        cell = by_index[index]
        try:
            result = _prepare_cell(
                lab, output, cell, card, inputs,
                native_output_interval_s=native_output_interval_s,
                run_gencase_fn=run_gencase_fn,
                decode_fn=decode_fn,
            )
        except Exception as error:  # retain every selected row and continue
            result = _failure_row(output, cell, error)
        rows[index] = result
        materialized.append(result)
    prepared_count = sum(row.get("status") == "prepared" for row in materialized)
    failed_count = sum(row.get("status") == "failed" for row in materialized)
    complete = len(selected) == EXPECTED_CELL_COUNT and prepared_count == EXPECTED_CELL_COUNT
    report["failure_denominator"]["rows"] = rows
    report.update({
        "status": "prepared_cpu_only" if complete else ("partial_with_failures" if failed_count else "partial_prepared"),
        "selected_indices": selected,
        "prepared_cell_count": int(prepared_count),
        "failed_cell_count": int(failed_count),
        "unattempted_cell_count": int(EXPECTED_CELL_COUNT - len(selected)),
        "cells": rows,
        "candidate_matrix_inputs_materialized": bool(complete),
        "candidate_matrix_jobs_materialized": False,
        "execution_controls": {**report["execution_controls"], "gen_case_run": True, "decoder_run": True},
        "matrix_output": str(output),
        "matrix_output_report": str((output / "matrix-preparation.json").resolve()),
    })
    _write_json(output / "matrix-preparation.json", report)
    return report


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_RELATIVE)
    parser.add_argument("--gencase", type=Path, default=None)
    parser.add_argument("--decoder", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="write a no-execution v5 repair plan")
    _common_parser(plan)
    plan.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare", help="materialize explicitly selected v5 CPU cells")
    _common_parser(prepare)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--cell-index", type=int, action="append", default=[])
    prepare.add_argument("--all-cells", action="store_true")
    prepare.add_argument("--native-output-interval-s", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lab = Path(args.lab_root).resolve()
    if args.command == "plan":
        report = plan_matrix(lab, args.candidate, args.output, args.gencase, args.decoder)
    else:
        report = prepare_matrix(
            lab, args.candidate, args.output, args.cell_index,
            all_cells=args.all_cells,
            gencase_path=args.gencase,
            decoder_path=args.decoder,
            native_output_interval_s=args.native_output_interval_s,
        )
    print(json.dumps({"status": report["status"], "report": report.get("matrix_output_report", str(Path(args.output).resolve()))}, indent=2))
    return 0 if report["status"] not in {"partial_with_failures"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
