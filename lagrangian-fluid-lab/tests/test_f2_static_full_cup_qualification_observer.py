from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from scripts import f2_static_full_cup_qualification_observer as observer


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell_design() -> list[dict]:
    rows = []
    index = 0
    for q in (0.0, 0.5, 1.0):
        volume = 0.022950 + 0.001290 * q
        height = volume / (0.425 * 0.30)
        for dp in (0.01, 0.0075, 0.005):
            rows.append({
                "index": index,
                "case_id": f"case-{index:02d}",
                "q": q,
                "initial_volume_m3": volume,
                "initial_fill_height_m": height,
                "dp_m": dp,
                "design_cell": "spatial",
                "held_out": False,
                "status": "design_only_unprepared",
                "prepared": None,
                "job": None,
            })
            index += 1
    for q in (0.25, 0.75):
        volume = 0.022950 + 0.001290 * q
        height = volume / (0.425 * 0.30)
        for dp in (0.0075, 0.005):
            rows.append({
                "index": index,
                "case_id": f"case-{index:02d}",
                "q": q,
                "initial_volume_m3": volume,
                "initial_fill_height_m": height,
                "dp_m": dp,
                "design_cell": "spatial_held_out",
                "held_out": True,
                "status": "design_only_unprepared",
                "prepared": None,
                "job": None,
            })
            index += 1
    for kind in ("internal_time", "native_output"):
        rows.append({
            "index": index,
            "case_id": f"case-{index:02d}",
            "q": 0.5,
            "initial_volume_m3": 0.023595,
            "initial_fill_height_m": 0.023595 / (0.425 * 0.30),
            "dp_m": 0.0075,
            "design_cell": kind,
            "temporal_variant": kind,
            "held_out": False,
            "status": "design_only_unprepared",
            "prepared": None,
            "job": None,
        })
        index += 1
    assert len(rows) == 15
    return rows


def _candidate(path: Path) -> dict:
    cells = _cell_design()
    value = {
        "schema": "core.f2.static_full_cup_volume_candidate.v1",
        "candidate_id": "synthetic_f2_static_volume",
        "scope_id": "F2_static_full_cup_volume_hold_x_v1",
        "qualification_only": True,
        "qualified": False,
        "physical_contract": {
            "cup": {"low_m": [0.0, -0.15, 0.65], "size_m": [0.425, 0.30, 0.45], "mkbound": 0},
            "runtime_domain": {"posmin_m": [-0.7, -0.65, -0.4], "posmax_m": [2.2, 0.8, 1.8]},
            "motion": {"angle_degrees": 0.0},
        },
        "qualification_design": {
            "cell_count": 15,
            "cells": cells,
            "registered_window_s": 0.6,
            "output_interval_s": 0.02,
            "settle_hold_s": 0.2,
            "matrix_inputs_materialized": False,
            "matrix_jobs_materialized": False,
        },
        "gates": {
            "mass_change_relative_max": 1e-8,
            "static_speed_p95_m_s_max": 0.1,
            "static_kinetic_over_initial_potential_max": 0.05,
            "static_settle_hold_s": 0.2,
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_max_absolute_normalized_difference": 0.01,
        },
    }
    path.write_text(json.dumps(value, indent=2) + "\n")
    return value


def _write_ref(path: Path, role: str) -> dict:
    return {"path": str(path.resolve()), "sha256": _digest(path), "bytes": path.stat().st_size, "role": role}


def _fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    candidate_path = tmp_path / "candidate.json"
    card = _candidate(candidate_path)
    report_root = tmp_path / "prepared-v4"
    rows = []
    for cell in card["qualification_design"]["cells"]:
        cell_dir = report_root / "cells" / f"{int(cell['index']):02d}"
        cell_dir.mkdir(parents=True)
        definition = cell_dir / f"{cell['case_id']}_Def.xml"
        motion = cell_dir / f"{cell['case_id']}_motion.dat"
        gencase = cell_dir / "gencase.log"
        generated = cell_dir / "generated.xml"
        bi4 = cell_dir / "generated.bi4"
        for path, text in ((definition, "<definition/>"), (motion, "#Time;Degrees\n0;0\n"),
                           (gencase, "synthetic\n"), (generated, "<generated/>"), (bi4, "bi4")):
            path.write_text(text)
        preflight_path = cell_dir / "preflight.json"
        preflight_path.write_text(json.dumps({
            "schema": "core.f2.static_full_cup.matrix_cell_preflight.v1",
            "case_id": cell["case_id"],
            "index": cell["index"],
            "preflight_pass": True,
            "trajectory_or_solver_checked": False,
            "mass_rescaling": False,
            "generated_particle_groups": {
                "fixed": [{"kind": "moving", "mkbound": 0, "begin": 4, "count": 1}],
                "fluid": [{"kind": "fluid", "mkfluid": 0, "begin": 0, "count": 4}],
            },
        }, indent=2) + "\n")
        closure_paths = [definition, motion, gencase, generated, bi4, preflight_path]
        closure = [_write_ref(path, f"cell artifact: {path.name}") for path in closure_paths]
        prepared_path = cell_dir / "prepared.json"
        prepared_path.write_text(json.dumps({
            "schema": "core.f2.static_full_cup.matrix_cell_prepared.v1",
            "candidate_id": card["candidate_id"],
            "scope_id": card["scope_id"],
            "index": cell["index"],
            "case_id": cell["case_id"],
            "q": cell["q"],
            "dp_m": cell["dp_m"],
            "design_cell": cell["design_cell"],
            "output_interval_s": 0.01 if cell["design_cell"] == "native_output" else 0.02,
            "preflight": str(preflight_path.resolve()),
            "preflight_pass": True,
            "hash_closure_pass": True,
            "hash_closure": closure,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutated": False,
            "ledger_mutated": False,
            "registry_mutated": False,
            "mass_rescaling": False,
        }, indent=2) + "\n")
        rows.append({
            "index": cell["index"], "case_id": cell["case_id"], "q": cell["q"], "dp_m": cell["dp_m"],
            "design_cell": cell["design_cell"], "status": "prepared", "preflight_pass": True,
            "prepared": str(prepared_path.resolve()), "prepared_sha256": _digest(prepared_path),
        })
    report_path = report_root / "matrix-preparation.json"
    candidate_binding = _write_ref(candidate_path, "15-cell candidate card")
    report_path.write_text(json.dumps({
        "schema": "core.f2.static_full_cup.matrix_preparation.v1",
        "status": "prepared", "candidate_id": card["candidate_id"], "scope_id": card["scope_id"],
        "candidate_card": candidate_binding, "registered_cell_count": 15, "prepared_cell_count": 15,
        "failed_cell_count": 0, "unattempted_cell_count": 0, "cells": rows,
        "failure_denominator": {"rows": [{"index": i, "status": "prepared"} for i in range(15)]},
        "candidate_matrix_jobs_materialized": False,
        "execution_controls": {
            "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0,
            "ledger_mutation": 0, "registry_mutation": 0, "matrix_jobs_materialized": False,
            "qualification_claim_allowed": False,
        },
    }, indent=2) + "\n")
    return report_path, card, {int(row["index"]): row for row in rows}


def _trajectory(path: Path, *, broken_index: bool = False, interval: float = 0.02) -> None:
    times = np.arange(0.0, 0.6 + interval / 2.0, interval)
    n = 4
    ids = np.arange(n, dtype=np.uint32)
    positions = np.tile(np.asarray([[0.1, -0.05, 0.75], [0.11, -0.05, 0.75], [0.1, -0.04, 0.75], [0.11, -0.04, 0.75]], dtype=float), (len(times), 1, 1))
    velocities = np.zeros_like(positions, dtype=np.float32)
    density = np.full((len(times), n), 1000.0, dtype=np.float32)
    pressure = np.zeros((len(times), n), dtype=np.float32)
    mass = np.full((len(times), n), 0.1, dtype=np.float32)
    valid = np.ones((len(times), n), dtype=bool)
    if broken_index:
        valid[-1, 0] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        handle["time"] = times
        handle["particle_id"] = ids
        handle["position"] = positions
        handle["velocity"] = velocities
        handle["density"] = density
        handle["pressure"] = pressure
        handle["mass"] = mass
        handle["valid"] = valid


def _runtime_manifest(path: Path, report: dict, prepared_rows: dict[int, dict], trajectories: dict[int, Path]) -> None:
    cells = []
    for index, trajectory in trajectories.items():
        row = prepared_rows[index]
        item = {
            "index": index,
            "case_id": row["case_id"],
            "prepared_sha256": row["prepared_sha256"],
            "trajectory": _write_ref(trajectory, "runtime trajectory"),
        }
        if index == 13:
            item["control_evidence"] = {"actual_step_count": 100}
        cells.append(item)
    path.write_text(json.dumps({
        "schema": observer.RUNTIME_SCHEMA,
        "scope_id": report["scope_id"],
        "job_spec_creation": False,
        "queue_mutation": 0,
        "cells": cells,
    }, indent=2) + "\n")


def test_no_runtime_keeps_all_15_rows_and_candidate_only_receipt(tmp_path: Path) -> None:
    report_path, _card, _rows = _fixture(tmp_path)
    output = tmp_path / "receipt.json"
    result = observer.evaluate_matrix(report_path, output=output)
    assert result["registered_cell_count"] == 15
    assert len(result["failure_denominator"]["rows"]) == 15
    assert len(result["failures"]) == 15
    assert all("missing_runtime_product" in row["categories"] for row in result["failures"])
    assert result["T1_numerical"] is False
    assert result["qualification_claim"].startswith("none; candidate-scope-only")
    assert result["execution_controls"]["solver_invoked_by_evaluator"] is False
    assert result["execution_controls"]["registry_mutation"] == 0


def test_all_synthetic_cells_compare_and_write_only_derived_receipt(tmp_path: Path) -> None:
    report_path, _card, rows = _fixture(tmp_path)
    report = json.loads(report_path.read_text())
    trajectories = {}
    for index in range(15):
        trajectory = tmp_path / "runtime" / f"cell-{index:02d}.h5"
        _trajectory(trajectory, interval=0.01 if index == 14 else 0.02)
        trajectories[index] = trajectory
    runtime = tmp_path / "runtime-products.json"
    _runtime_manifest(runtime, report, rows, trajectories)
    output = tmp_path / "receipt.json"
    result = observer.evaluate_matrix(report_path, runtime_products=runtime, output=output)
    assert result["candidate_scope_pass"] is True
    assert result["T1_numerical"] is False
    assert result["checks"]["spatial"] is True
    assert result["checks"]["temporal"] is True
    assert result["checks"]["temporal_control_evidence"] is True
    assert len(result["failures"]) == 0
    assert all(row["status"] == "observed" for row in result["cells"])
    assert not any(path.name.endswith(".observation.json") for path in (tmp_path / "runtime").iterdir())
    assert (tmp_path / "receipt.observations").is_dir()
    native_observation = json.loads(
        (tmp_path / "receipt.observations" / "cell-14.observation.json").read_text()
    )
    assert native_observation["declared_output_interval_s"] == 0.01
    assert native_observation["hard_checks"]["saved_output_cadence_matches_declared"] is True
    assert result["admission_contract"]["admission_controls"]["job_spec_creation_allowed"] is False


def test_one_runtime_identity_loss_is_classified_without_denominator_drop(tmp_path: Path) -> None:
    report_path, _card, rows = _fixture(tmp_path)
    report = json.loads(report_path.read_text())
    trajectories = {}
    for index in range(15):
        trajectory = tmp_path / "runtime" / f"cell-{index:02d}.h5"
        _trajectory(trajectory, broken_index=index == 4)
        trajectories[index] = trajectory
    runtime = tmp_path / "runtime-products.json"
    _runtime_manifest(runtime, report, rows, trajectories)
    result = observer.evaluate_matrix(report_path, runtime_products=runtime)
    assert len(result["failure_denominator"]["rows"]) == 15
    failed = result["failure_denominator"]["rows"][4]
    assert failed["status"] == "failed_static_gate"
    assert "missing_native_id" in failed["failure_categories"]
    assert len(result["failures"]) >= 1
    assert result["checks"]["matrix_complete"] is False
    assert result["candidate_scope_pass"] is False
