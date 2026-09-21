#!/usr/bin/env python3
"""Build a read-only, hash-bound audit of the H2 v5 batch-8 failure.

The eight solver attempts already exist and are retained as negative evidence.
This script reads only JSON sidecars and the hashes already recorded by the
observer.  It does not open or rehash a trajectory, rerun a case, change the
static gates, extend the horizon, launch a solver/GPU/queue, or touch the
ledger/registry.  The result closes this H2 static-hold lineage for T1
promotion and records two root-review-only attribution hypotheses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/"
    "f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json"
)
REPORT = LAB / "reports/F2-H2-MDBC-STATIC-HOLD-NEGATIVE-AUDIT-2026-09-21.zh-CN.md"

OBSERVATION = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "runtime-batch8-v3/observation-evidence-v1.json"
)
MATRIX = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "prepared-20260920-v5-all/matrix-preparation.json"
)

FIXED_GATES = {
    "time_max_s": 0.6,
    "output_interval_s": 0.02,
    "settle_hold_s": 0.2,
    "speed_p95_max_m_s": 0.1,
    "kinetic_over_initial_potential_max": 0.05,
    "cup_retention_mass_fraction_min": 0.95,
    "no_open_cup_escape_max_fraction": 0.0,
    "no_closed_cup_endpoint_particle_frames": 0,
    "no_closed_cup_saved_chord_crossings": 0,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else LAB / path


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def binding(path: Path, role: str) -> dict[str, Any]:
    path = as_path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": rel(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def load(path: Path) -> dict[str, Any]:
    path = as_path(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _binding_from_record(record: dict[str, Any], role: str) -> dict[str, Any]:
    """Bind a path from an existing receipt, checking its recorded size/hash.

    The trajectory itself is intentionally not reopened.  All trajectory
    digests below come from the already completed observer sidecars.
    """

    path = as_path(record["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if int(record["bytes"]) != path.stat().st_size:
        raise AssertionError(f"recorded byte count mismatch: {path}")
    if record.get("sha256") != sha256(path):
        raise AssertionError(f"recorded hash mismatch: {path}")
    return {
        "path": rel(path),
        "sha256": record["sha256"],
        "bytes": int(record["bytes"]),
        "role": role,
    }


def _worker_status_path(worker_audit_path: Path) -> Path:
    return worker_audit_path.parent / "worker-status.json"


def _common_failure_metrics(observer_records: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [record["observed"] for record in observer_records]
    checks = [record["hard_checks"] for record in observer_records]

    def count_false(name: str) -> int:
        return sum(not bool(item[name]) for item in checks)

    def count_true(name: str) -> int:
        return sum(bool(item[name]) for item in checks)

    def extrema(name: str) -> dict[str, float]:
        values = [float(item[name]) for item in observed]
        return {"min": min(values), "max": max(values)}

    return {
        "rows": len(observer_records),
        "static_speed_gate_false": count_false("static_speed_gate"),
        "static_kinetic_gate_false": count_false("static_kinetic_gate"),
        "no_open_cup_escape_false": count_false("no_open_cup_escape"),
        "no_closed_cup_saved_chord_crossings_false": count_false(
            "no_closed_cup_saved_chord_crossings"
        ),
        "no_closed_cup_endpoint_penetrations_false": count_false(
            "no_closed_cup_endpoint_penetrations"
        ),
        "cup_retention_gate_true": count_true("cup_retention_gate"),
        "no_unexpected_receiver_mass_true": count_true("no_unexpected_receiver_mass"),
        "no_unexpected_tray_mass_true": count_true("no_unexpected_tray_mass"),
        "maximum_outside_cup_mass_fraction": extrema(
            "maximum_outside_cup_mass_fraction"
        ),
        "maximum_speed_p95_m_s": extrema("maximum_speed_p95_m_s"),
        "maximum_kinetic_over_initial_potential": extrema(
            "maximum_kinetic_over_initial_potential"
        ),
        "stable_final_duration_s": extrema("stable_final_duration_s"),
    }


def build_contract() -> dict[str, Any]:
    observation = load(OBSERVATION)
    matrix = load(MATRIX)
    source_closure = observation["source_closure"]
    all_rows = observation["failure_denominator"]["rows"]
    rows = [row for row in all_rows if row.get("status") == "scientific_failed"]
    assert len(rows) == 8
    observer_paths = sorted(
        (
            OBSERVATION.parent / "observer" / f"cell{int(row['index']):02d}.json"
            for row in rows
        ),
        key=lambda path: path.name,
    )
    observer_records = [load(path) for path in observer_paths]

    assert observation["schema"] == "core.f2.h2_mdbc.static_range_v5.observation_evidence.v1"
    assert observation["scope_id"] == "F2_H2_mdbc_static_range_qualification_v5"
    assert observation["qualified"] is False
    assert observation["T1_numerical"] is False
    assert observation["matrix_credit"] == 0
    assert observation["failure_denominator"]["planned"] == 15
    assert observation["failure_denominator"]["attempted"] == 8
    assert observation["failure_denominator"]["scientific_failed"] == 8
    assert observation["failure_denominator"]["infrastructure_failed"] == 0
    assert observation["failure_denominator"]["unattempted"] == 7
    assert observation["failure_denominator"]["failed_rows_dropped"] is False
    assert observation["failure_denominator"]["survivor_renormalization"] is False
    assert observation["scope_decision"]["third_t1_family_established"] is False
    assert observation["execution_controls"]["solver_invoked_by_collector"] is False
    assert observation["execution_controls"]["gpu_invoked_by_collector"] is False
    assert observation["execution_controls"]["queue_mutation_by_collector"] == 0
    assert observation["execution_controls"]["ledger_mutation"] == 0
    assert observation["execution_controls"]["registry_mutation"] == 0
    assert observation["execution_controls"]["qualification_credit"] == 0

    assert matrix["registered_cell_count"] == 15
    assert matrix["prepared_cell_count"] == 15
    assert matrix["failed_cell_count"] == 0
    assert matrix["unattempted_cell_count"] == 0
    assert matrix["execution_controls"]["solver_invoked"] is False
    assert matrix["execution_controls"]["gpu_invoked"] is False
    assert matrix["execution_controls"]["queue_mutation"] == 0
    assert matrix["execution_controls"]["ledger_mutation"] == 0
    assert matrix["execution_controls"]["registry_mutation"] == 0

    hash_bindings: dict[str, dict[str, Any]] = {
        "observation_evidence": binding(OBSERVATION, "eight-cell negative observation evidence"),
        "batch_root_review": binding(
            as_path(source_closure["root_review"]["path"]), "eight-cell root review"
        ),
        "candidate": binding(
            as_path(source_closure["candidate"]["path"]), "H2 v5 candidate"
        ),
        "cpu_native_matrix": binding(
            as_path(source_closure["matrix"]["path"]), "fifteen-row CPU/native preparation matrix"
        ),
        "prior_repair_contract": binding(
            as_path(source_closure["repair_contract"]["path"]), "retained v4-to-v5 repair contract"
        ),
        "observer_implementation": binding(
            as_path(source_closure["observer_code"]["path"]), "fixed static-hold observer implementation"
        ),
        "evidence_collector": binding(
            as_path(source_closure["collector_code"]["path"]), "fixed-denominator evidence collector"
        ),
        "next_route_contract": binding(
            LAB
            / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v2/root-review-only-contract-v2.json",
            "independent F2 topology root-review-only contract",
        ),
        "next_route_preflight_contract": binding(
            LAB
            / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v2/preflight-contract-v3.json",
            "independent F2 future CPU/native preflight contract",
        ),
        "next_route_candidate": binding(
            LAB
            / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v2/normal-remediation-candidate-v2.json",
            "independent F2 normal-remediation candidate",
        ),
        "implementation": binding(Path(__file__), "negative audit implementation"),
        "test": binding(
            LAB / "tests/test_f2_h2_mdbc_static_hold_negative_audit_v1.py",
            "negative audit regression test",
        ),
    }

    cell_records: list[dict[str, Any]] = []
    trajectory_bindings: list[dict[str, Any]] = []
    preflight_records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: int(value["index"])):
        index = int(row["index"])
        assert row["status"] == "scientific_failed"
        assert row["qualification_credit"] is False
        observer_path = as_path(row["observer"]["path"])
        observer = load(observer_path)
        assert observer["cell_index"] == index
        assert observer["case_id"] == row["case_id"]
        assert observer["qualified"] is False
        assert observer["matrix_credit"] == 0
        assert observer["hard_integrity_pass"] is False
        assert observer["static_settled"] is False
        assert observer["event_window_complete"] is False

        runtime_prepared_path = as_path(row["prepared"]["path"])
        runtime_prepared = load(runtime_prepared_path)
        config = runtime_prepared["config"]
        assert runtime_prepared["preflight_pass"] is True
        assert runtime_prepared["qualified"] is False
        assert config["recipe"] == "mdbc_native"
        assert config["boundary_method"] == 2
        assert config["time_max_s"] == FIXED_GATES["time_max_s"]
        assert config["output_interval_s"] == FIXED_GATES["output_interval_s"]
        assert runtime_prepared["solver_arguments"] == ["-mdbc_noslip:1"]
        assert config["control_semantics"] == (
            "prescribed zero cup angle; gravity and initial fluid are fixed inputs"
        )

        matrix_cell = matrix["cells"][index]
        assert matrix_cell["case_id"] == row["case_id"]
        preflight_path = as_path(matrix_cell["preflight"])
        preflight = load(preflight_path)
        assert preflight["preflight_pass"] is True
        assert preflight["trajectory_or_solver_checked"] is False
        assert preflight["checks"]["native_initial_zero_velocity"] is True
        assert preflight["checks"]["mdbc_zero_boundary_normals_gate"] is True
        assert preflight["mdbc_normal_gate"]["zero_boundary_normals"] == 0
        assert preflight["mass_rescaling"] is False

        worker_audit_path = as_path(row["worker_audit"]["path"])
        worker_result_path = as_path(row["worker_result"]["path"])
        worker_audit = load(worker_audit_path)
        worker_result = load(worker_result_path)
        worker_status_path = _worker_status_path(worker_audit_path)
        worker_status = load(worker_status_path)
        assert worker_audit["hard_integrity_pass"] is True
        assert worker_audit["event_window_complete"] is False
        assert worker_audit["event_window_status"] == "not_assessed"
        assert worker_result["hard_integrity_pass"] is True
        assert worker_result["event_window_complete"] is False
        assert worker_status["status"] == "complete_with_evidence"
        assert worker_status["hard_integrity_pass"] is True

        observed = observer["observed"]
        checks = observer["hard_checks"]
        assert checks["static_speed_gate"] is False
        assert checks["static_kinetic_gate"] is False
        assert checks["no_open_cup_escape"] is False
        assert checks["cup_retention_gate"] is True
        assert checks["no_unexpected_receiver_mass"] is True
        assert checks["no_unexpected_tray_mass"] is True
        assert observed["frame_count"] == 31
        assert observed["time_end_s"] >= FIXED_GATES["time_max_s"] - 1e-6
        assert observed["stable_final_duration_s"] == 0.0

        # Bind every small sidecar.  The trajectory is retained only through
        # the observer's already recorded immutable hash; this audit never
        # opens the HDF5 file.
        hash_bindings[f"cell{index:02d}_observer"] = binding(
            observer_path, "static-hold observer sidecar"
        )
        hash_bindings[f"cell{index:02d}_job_spec"] = binding(
            as_path(row["job_spec"]["path"]), "runtime job specification"
        )
        hash_bindings[f"cell{index:02d}_runtime_prepared"] = binding(
            runtime_prepared_path, "runtime prepared input"
        )
        hash_bindings[f"cell{index:02d}_coordinator_receipt"] = binding(
            as_path(row["receipt"]["path"]), "coordinator execution receipt"
        )
        hash_bindings[f"cell{index:02d}_worker_result"] = binding(
            worker_result_path, "worker execution result"
        )
        hash_bindings[f"cell{index:02d}_worker_audit"] = binding(
            worker_audit_path, "generic worker audit"
        )
        hash_bindings[f"cell{index:02d}_worker_status"] = binding(
            worker_status_path, "worker completion status"
        )
        hash_bindings[f"cell{index:02d}_cpu_native_preflight"] = binding(
            preflight_path, "CPU/native material preflight"
        )

        trajectory = observer["trajectory"]
        assert trajectory["path"] == row["trajectory"]["path"]
        assert trajectory["sha256"] == row["trajectory"]["sha256"]
        assert int(trajectory["bytes"]) == int(row["trajectory"]["bytes"])
        trajectory_bindings.append(
            {
                "index": index,
                "case_id": row["case_id"],
                "path": trajectory["path"],
                "sha256": trajectory["sha256"],
                "bytes": int(trajectory["bytes"]),
                "hash_source": "existing observer sidecar; HDF5 not reopened or rehashed",
            }
        )
        preflight_records.append(
            {
                "index": index,
                "case_id": row["case_id"],
                "preflight": {
                    "path": rel(preflight_path),
                    "sha256": matrix_cell["preflight_sha256"],
                },
                "native_initial_zero_velocity": True,
                "zero_boundary_normals": 0,
                "mass_rescaling": False,
                "qualification_credit": 0,
            }
        )
        cell_records.append(
            {
                "index": index,
                "case_id": row["case_id"],
                "q": float(config["parameter"]["q"]),
                "dp_m": float(config["dp_m"]),
                "worker": {
                    "status": worker_status["status"],
                    "hard_integrity_pass": worker_status["hard_integrity_pass"],
                    "event_window_complete": worker_result["event_window_complete"],
                    "event_window_status": worker_audit["event_window_status"],
                },
                "observer": {
                    "hard_integrity_pass": observer["hard_integrity_pass"],
                    "static_settled": observer["static_settled"],
                    "event_window_complete": observer["event_window_complete"],
                    "failed_checks": [
                        name for name, passed in checks.items() if passed is False
                    ],
                    "maximum_outside_cup_mass_fraction": observed[
                        "maximum_outside_cup_mass_fraction"
                    ],
                    "maximum_speed_p95_m_s": observed["maximum_speed_p95_m_s"],
                    "maximum_kinetic_over_initial_potential": observed[
                        "maximum_kinetic_over_initial_potential"
                    ],
                    "stable_final_duration_s": observed["stable_final_duration_s"],
                    "closed_cup_endpoint_particle_frames": observed[
                        "closed_cup_endpoint_particle_frames"
                    ],
                    "closed_cup_saved_chord_crossings": observed[
                        "closed_cup_saved_chord_crossings"
                    ],
                },
                "trajectory_binding": trajectory_bindings[-1],
                "cpu_native_input": {
                    "native_initial_zero_velocity": True,
                    "mdbc_zero_boundary_normals": 0,
                    "mass_rescaling": False,
                    "trajectory_or_solver_checked_by_preflight": False,
                },
            }
        )

    summary = _common_failure_metrics(observer_records)
    assert summary["static_speed_gate_false"] == 8
    assert summary["static_kinetic_gate_false"] == 8
    assert summary["no_open_cup_escape_false"] == 8
    assert summary["cup_retention_gate_true"] == 8
    assert summary["no_unexpected_receiver_mass_true"] == 8
    assert summary["no_unexpected_tray_mass_true"] == 8
    assert summary["maximum_speed_p95_m_s"] == {
        "min": 1.5725231042319487,
        "max": 2.285871575979002,
    }
    assert summary["maximum_kinetic_over_initial_potential"] == {
        "min": 0.30256918804283056,
        "max": 0.34153798875825686,
    }
    assert summary["maximum_outside_cup_mass_fraction"] == {
        "min": 0.019342359767891684,
        "max": 0.0453168044077135,
    }
    assert all(item["native_initial_zero_velocity"] for item in preflight_records)

    next_route_root = (
        LAB / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
        "normal-remediation-v2"
    )
    next_route_contract = load(next_route_root / "root-review-only-contract-v2.json")
    next_route_preflight = load(next_route_root / "preflight-contract-v3.json")
    next_route_candidate = load(next_route_root / "normal-remediation-candidate-v2.json")
    assert next_route_contract["status"] == "prepared_design_only_cpu_not_authorized"
    assert next_route_preflight["proposal_only"] is True
    assert next_route_preflight["authorized_now"] is False
    assert next_route_preflight["matrix_credit"] == 0
    assert next_route_candidate["qualified"] is False
    assert next_route_candidate["T1_numerical"] is False

    hypotheses = [
        {
            "hypothesis_id": "H2_batch8_runtime_initial_rest_mdbc_handoff_v1",
            "class": "runtime_initial_rest_and_mdbc_boundary_semantics",
            "status": "proposal_only_untested",
            "evidence": [
                "all eight CPU/native preflights record native_initial_zero_velocity=true",
                "all eight runtime inputs use recipe=mdbc_native, Boundary=2, and -mdbc_noslip:1",
                "all eight independent q/dp rows fail the same fixed speed and kinetic gates with zero final stable duration",
            ],
            "scope": "attribute the common plume to runtime initial-state handoff or mDBC wall/normal semantics without changing gates",
            "fresh_input_identity": {
                "candidate_id": "F2_H2_mdbc_static_hold_runtime_semantics_v1",
                "revision_id": "F2_H2_mdbc_static_hold_runtime_semantics_v1",
                "parent_candidate_reused": False,
                "new_definition_required": True,
                "future_case_id": "CORE_F2_H2_mdbc_static_hold_runtime_semantics_v1_q0p50000000_dp0p007500000000_spatial",
                "future_output_stem": "campaigns/core-v1/cfd/f2-h2-mdbc-static-hold-runtime-semantics-v1/",
            },
            "bounded_review_checks": [
                "record native fluid Vel.bin zero state before any runtime launch",
                "record the first solver frame velocity/kinetic impulse and the first mDBC wall-normal impulse",
                "bind Boundary=2, -mdbc_noslip:1, vdp=-0.5, distanceh=3, and svshapes=true",
                "keep the existing 0.6 s horizon, 0.02 s cadence, 0.2 s hold, and every fixed static/retention/escape gate",
                "write a zero-credit receipt even when the fresh case fails; no retry of any batch-8 input",
            ],
            "falsifier": "If a fresh, separately hashed runtime shows zero first-step impulse and still fails the unchanged observer gates, reject this runtime-semantics attribution; if initial rest is not preserved, the proposal is invalid.",
            "authorization_now": False,
        },
        {
            "hypothesis_id": "H2_batch8_static_observer_contract_separation_v1",
            "class": "static_observer_contract_attribution",
            "status": "diagnostic_proposal_only_not_a_pass_repair",
            "evidence": [
                "all eight generic worker audits are hard_integrity_pass=true but event_window_status=not_assessed",
                "all eight observer sidecars independently fail static speed, kinetic, and open-cup escape gates",
                "saved-frame chord diagnostics vary by cell while the common speed/kinetic failure remains 8/8",
            ],
            "scope": "separate structural worker integrity from the registered static observer contract; preserve unknown/not_assessed as zero credit",
            "fresh_output_stem": "campaigns/core-v1/cfd/f2-h2-mdbc-static-hold-observer-contract-v1/",
            "bounded_review_checks": [
                "report worker structural fields, initial-rest input fields, and observer static fields as separate columns",
                "retain the exact observer implementation and fixed thresholds; do not reinterpret not_assessed as pass",
                "report endpoint frames, saved-frame chord crossings, outside mass, speed, kinetic ratio, and final stable duration independently",
                "do not reopen or re-audit an existing batch-8 HDF5 trajectory in this proposal",
            ],
            "falsifier": "If a fresh runtime with correctly bound initial rest and mDBC semantics passes the fixed physical gates but only the observer event bookkeeping disagrees, review the observer contract; until then the existing observer failures remain scientific negatives.",
            "authorization_now": False,
        },
    ]

    return {
        "schema": "core.f2.h2_mdbc.static_hold_negative_audit.root_review_only_contract.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "h2_static_hold_closed_after_eight_scientific_failures",
        "family": "F2",
        "scope_id": "F2_H2_mdbc_static_range_qualification_v5",
        "candidate_id": "F2_H2_mdbc_static_range_qualification_v5",
        "revision_id": "F2_H2_mdbc_static_range_mdbc_v5_top_layer_lateral_lattice",
        "qualification_claim": "none; read-only negative audit and root-review-only hypotheses",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "h2_decision": {
            "current_lineage": "closed_for_third_t1_promotion",
            "reason": "all eight attempted static-hold rows failed the fixed observer event contract; the remaining seven rows remain unattempted in the fixed denominator",
            "retry_same_input": False,
            "extend_horizon": False,
            "relax_thresholds": False,
            "drop_failed_rows": False,
            "survivor_renormalization": False,
            "third_t1_family_established": False,
        },
        "fixed_observer_contract": FIXED_GATES,
        "batch8_audit": {
            "attempted_rows": 8,
            "scientific_failed_rows": 8,
            "infrastructure_failed_rows": 0,
            "unattempted_rows": 7,
            "common_failure_summary": summary,
            "cells": cell_records,
            "trajectory_bindings": trajectory_bindings,
            "trajectory_hash_policy": "hashes are imported from immutable observer sidecars; this audit does not reopen or rehash HDF5",
        },
        "cpu_native_input_closure": {
            "rows": preflight_records,
            "all_native_initial_zero_velocity": True,
            "all_zero_boundary_normals": True,
            "all_mass_rescaling_false": True,
            "trajectory_or_solver_checked": False,
            "qualification_credit": 0,
        },
        "hypothesis_policy": {
            "maximum_hypothesis_classes": 2,
            "selected_hypothesis_classes": 2,
            "thresholds_are_fixed": True,
            "unknown_or_not_assessed_is_zero_credit": True,
        },
        "hypotheses": hypotheses,
        "next_independent_route": {
            "decision": "retain_as_root_review_only_candidate",
            "family": next_route_candidate["family"],
            "scope_id": next_route_candidate["scope_id"],
            "revision_id": next_route_candidate["revision_id"],
            "candidate_id": next_route_candidate["candidate_id"],
            "status": next_route_contract["status"],
            "proposal_only": next_route_preflight["proposal_only"],
            "authorized_now": next_route_preflight["authorized_now"],
            "matrix_credit": 0,
            "reason": "the submerged-orifice topology is independent of the closed-cup static-hold lineage and already has a separate hash-bound root-review contract; it is not a T1 qualification or denominator credit",
        },
        "failure_denominator": {
            "planned": 15,
            "attempted": 8,
            "scientific_failed": 8,
            "infrastructure_failed": 0,
            "unattempted": 7,
            "qualification_numerator": 0,
            "failed_rows_dropped": False,
            "survivor_renormalization": False,
            "threshold_relaxation": False,
            "horizon_extension": False,
            "same_input_retry": False,
            "unknown_or_not_assessed_credit": 0,
        },
        "execution_controls": {
            "this_audit_reads_json_sidecars_only": True,
            "trajectory_reopened": False,
            "trajectory_rehashed": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_credit": 0,
            "root_review_required_before_any_future_runtime": True,
        },
        "core_gate_effect": {
            "current_registered_t1_families": ["F3", "F4"],
            "third_t1_family_established": False,
            "core_gate_changed": False,
            "T2_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "hash_bindings": hash_bindings,
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.f2.h2_mdbc.static_hold_negative_audit.root_review_only_contract.v1"
    for item in value["hash_bindings"].values():
        bound = LAB / item["path"]
        assert bound.is_file(), bound
        assert bound.stat().st_size == item["bytes"], bound
        assert sha256(bound) == item["sha256"], bound
    assert value["qualified"] is False
    assert value["T1_numerical"] is False
    assert value["matrix_credit"] == 0
    assert value["core_gate_effect"]["core_gate_changed"] is False
    return value


def render_report(contract: dict[str, Any], contract_sha: str) -> str:
    summary = contract["batch8_audit"]["common_failure_summary"]
    cells = contract["batch8_audit"]["cells"]
    lines = [
        "# F2 H2 mDBC v5 batch8 静态保持负证据审计（2026-09-21）",
        "",
        "本报告是只读审计，不启动 solver、GPU 或 queue，不修改 registry/ledger，也不改变 Core gate。",
        "",
        "## 结论",
        "",
        "H2 v5 closed-cup static-hold lineage 关闭 T1 晋级：8/8 已执行行都是科学失败，7 行留在固定 15 行分母中未执行。matrix credit=0，T1_numerical=false，当前 F3/F4 Core gate 不变。",
        "",
        f"固定 observer 门槛没有改变：P95 速度≤{contract['fixed_observer_contract']['speed_p95_max_m_s']} m/s，动能/初始势能≤{contract['fixed_observer_contract']['kinetic_over_initial_potential_max']}，杯外质量≤{contract['fixed_observer_contract']['no_open_cup_escape_max_fraction']}，保留率≥{contract['fixed_observer_contract']['cup_retention_mass_fraction_min']}，时域 {contract['fixed_observer_contract']['time_max_s']} s，末端连续保持 {contract['fixed_observer_contract']['settle_hold_s']} s。",
        "",
        f"8/8 的 static_speed_gate、static_kinetic_gate 和 no_open_cup_escape 均失败；P95 速度范围 {summary['maximum_speed_p95_m_s']['min']:.6g}–{summary['maximum_speed_p95_m_s']['max']:.6g} m/s，动能比 {summary['maximum_kinetic_over_initial_potential']['min']:.6g}–{summary['maximum_kinetic_over_initial_potential']['max']:.6g}，杯外质量 {summary['maximum_outside_cup_mass_fraction']['min']:.6g}–{summary['maximum_outside_cup_mass_fraction']['max']:.6g}，stable_final_duration_s 全部为 0。",
        "",
        "## 证据分层",
        "",
        "8/8 worker 都是 complete_with_evidence 且 generic hard_integrity_pass=true，但 worker 的 event_window_status 都是 not_assessed。observer sidecar 对静态速度、动能、逃逸、端点和 saved-frame chord 才执行注册的静态保持合约；因此 worker 结构完整不构成静态保持通过。",
        "",
        "CPU/native 输入闭环 8/8 通过：native_initial_zero_velocity=true、zero boundary normals=0、mass rescaling=false，且该 preflight 明确没有检查 trajectory/solver。这个结果只证明输入材料/初始状态在 native 侧闭合，不能证明运行时初始状态交接或 mDBC 壁面冲量正确。",
        "",
        "trajectory.h5 的路径、大小和 SHA 直接沿用 observer 已记录的 immutable binding；本审计没有打开或重新哈希 HDF5，也没有重算任何同一输入。",
        "",
        "## 两类 root-review-only 假设",
        "",
        "1. **运行时初始静止与 mDBC 边界交接**：所有 native 输入先验静止，但八个 q/dp 组合在相同 mDBC_native、Boundary=2、-mdbc_noslip:1 下都产生静态门失败。后续新版本必须使用新的 Definition、case/output stem，并记录首个 solver frame 的速度/动能冲量和 mDBC 法向冲量；固定时域、cadence、阈值和 zero credit 规则。这个假设当前未执行，不能计入 T2。",
        "2. **observer 合约归因分离**：把 worker 结构字段、native 初始静止字段和 observer 静态字段分栏记录，保留 not_assessed/unknown 的 zero credit。它用于区分诊断归因，不是放宽 observer 门槛，也不把当前失败轨迹改判为通过。",
        "",
        "两类假设均为 proposal-only，均要求新的 root review。当前 H2 关闭，禁止重跑 batch8 同输入、延长时域或放宽门槛。",
        "",
        "## 下一独立路线",
        "",
        "保留已有 F2 submerged-orifice normal-remediation v2 作为独立拓扑的 root-review-only 候选。它有独立 candidate/contract，当前 authorized_now=false、matrix credit=0；这不是第三 T1 家族成立，也不改变分母或 Core gate。",
        "",
        f"合同：`{OUTPUT.relative_to(LAB)}`，SHA-256 `{contract_sha}`。",
        "",
        "## 8 行摘要",
        "",
        "| cell | P95 speed (m/s) | KE/PE | outside mass | endpoint frames | chord crossings |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        obs = cell["observer"]
        lines.append(
            f"| {cell['index']} | {obs['maximum_speed_p95_m_s']:.9g} | {obs['maximum_kinetic_over_initial_potential']:.9g} | {obs['maximum_outside_cup_mass_fraction']:.9g} | {obs['closed_cup_endpoint_particle_frames']} | {obs['closed_cup_saved_chord_crossings']} |"
        )
    lines.extend(
        [
            "",
            "改动只新增本次审计的 script、JSON contract、中文报告和 regression test；不改 registry、ledger、分母或旧 trace。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    contract = build_contract()
    output = as_path(args.output)
    report = as_path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report.write_text(
        render_report(contract, sha256(output)),
        encoding="utf-8",
    )
    print(output)
    print(report)
    print(sha256(output))
    print(sha256(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
