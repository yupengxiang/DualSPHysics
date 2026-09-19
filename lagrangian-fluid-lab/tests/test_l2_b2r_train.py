import json
import hashlib
from pathlib import Path

import h5py
import numpy as np
import torch

from scripts import l2_b2r_train as worker
from scripts.l2_b2r_model import GraphBatch, graph_model_contract


def _toy_bundle(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(worker, "LAB", tmp_path)
    t_count, particle_count = 6, 8
    base = np.asarray(
        [
            [-0.40, -0.04, 0.02],
            [-0.30, -0.04, 0.02],
            [-0.20, -0.04, 0.02],
            [-0.10, -0.04, 0.02],
            [0.00, -0.04, 0.02],
            [0.10, -0.04, 0.02],
            [0.20, -0.04, 0.02],
            [0.30, -0.04, 0.02],
        ],
        dtype=np.float32,
    )
    velocity = np.zeros((t_count, particle_count, 3), dtype=np.float32)
    velocity[..., 0] = 0.01
    position = np.stack([base + velocity[0] * (0.1 * frame) for frame in range(t_count)])
    scalar = np.ones((t_count, particle_count), dtype=np.float32)
    for stem, offset in (("train", 0.0), ("eval", 0.002), ("eval2", 0.003)):
        hdf5 = tmp_path / f"{stem}.h5"
        with h5py.File(hdf5, "w") as handle:
            handle.create_dataset("time", data=np.arange(t_count, dtype=np.float64) * 0.1)
            handle.create_dataset("position", data=position + offset)
            handle.create_dataset("velocity", data=velocity)
            handle.create_dataset("mass", data=scalar * 0.001)
            handle.create_dataset("density", data=scalar * 1000.0)
            handle.create_dataset("pressure", data=scalar * 10.0)
            handle.create_dataset("particle_id", data=np.arange(particle_count, dtype=np.uint32))
            handle.create_dataset("valid", data=np.ones((t_count, particle_count), dtype=bool))
        control = tmp_path / f"{stem}.csv"
        control.write_text(
            "# Time;LinearAccX;LinearAccY;LinearAccZ\n"
            "0.0;0.0;0.0;-9.81\n"
            "0.5;0.0;0.0;-9.81\n"
        )

    registry = {
        "schema": worker.REGISTRY_SCHEMA,
        "cases": [
            {
                "case_id": "TRAIN_0",
                "physical_case_id": "TRAIN_0",
                "split": "train",
                "hdf5": "train.h5",
                "source_evidence": {"control": {"path": "train.csv"}},
            },
            {
                "case_id": "EVAL_0",
                "physical_case_id": "EVAL_0",
                "split": "validation",
                "hdf5": "eval.h5",
                "source_evidence": {"control": {"path": "eval.csv"}},
            },
            {
                "case_id": "EVAL_1",
                "physical_case_id": "EVAL_1",
                "split": "test",
                "hdf5": "eval2.h5",
                "source_evidence": {"control": {"path": "eval2.csv"}},
            },
        ],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    current_f3 = {
        "schema": "l2r.r2.current_f3_contract.v1",
        "data_contract": {
            "feature_width": 48,
            "recorded_feature_width": 48,
            "future_fluid_state_allowed": False,
            "future_free_body_state_allowed": False,
            "target_convention": "Next canonical position minus current canonical position",
            "identity_convention": "Full immutable native particle IDs",
        },
        "recipe": {"recipe_id": "TOY_F3_RECIPE"},
        "qualification": {"current_model_qualified": False},
    }
    current_f3_path = tmp_path / "current-f3.json"
    current_f3_path.write_text(json.dumps(current_f3))
    current_f3_sha = hashlib.sha256(current_f3_path.read_bytes()).hexdigest()
    contract = graph_model_contract(node_features=8, edge_features=7, hidden=8, message_steps=1)
    study = {
        "schema": "l2r.b2r.preparation_contract.v1",
        "study_id": "L2R_B2R_GRAPH_CONTROLLED_V1",
        "status": "prepared_not_launched",
        "execution_status": "prepared_not_launched",
        "launch_allowed": True,
        "dependencies": {
            "R0": {"status": "verified_for_design", "required": True},
            "R2": {
                "status": "satisfied",
                "launch_allowed": True,
                "reason": "toy explicit R2",
                "source": {"schema": "l2r.r2.f3_contract.v1", "status": "complete_with_findings"},
                "required": True,
            },
        },
        "historical_baseline_boundary": {"can_satisfy_B2R": False},
        "model_contract": contract,
        "data_contract": {
            "evaluation_case_registry": {
                "source": {"path": "registry.json"},
                "physical_case_ids": ["EVAL_0", "EVAL_1"],
            },
            "current_f3_contract": {
                "schema": "l2r.r2.current_f3_contract.v1",
                "source": {"path": "current-f3.json", "sha256": current_f3_sha},
                "feature_width": 48,
            },
            "future_reference_state_allowed": False,
        },
        "acceptance": {
            "B2R_terminal": False,
            "new_graph_model_contract_written": True,
            "raw_hybrid_controlled_matrix_declared": True,
            "new_training_attempts_executed": False,
            "full_failure_denominator_ready_for_records": True,
            "r2_dependency_satisfied": True,
            "waiting_for_R2": False,
        },
    }
    study_path = tmp_path / "study.json"
    study_path.write_text(json.dumps(study))
    return study_path


def _run_args(study_path: Path, output: Path, *, route="raw", **overrides):
    values = {
        "--study": str(study_path),
        "--route": route,
        "--seed": "17",
        "--train-case-id": "TRAIN_0",
        "--eval-case-id": "EVAL_0",
        "--output-dir": str(output),
        "--device": "cpu",
        "--allow-cpu": "",
        "--max-steps": "2",
        "--max-frames": "2",
        "--max-particles": "8",
        "--max-seconds": "30",
        "--max-neighbors": "4",
    }
    for key, value in overrides.items():
        values["--" + key.replace("_", "-")] = str(value)
    argv = []
    for key, value in values.items():
        argv.append(key)
        if value:
            argv.append(value)
    return worker.parser().parse_args(["run", *argv])


def test_shared_route_model_uses_one_trunk_and_declared_hybrid_prior():
    model = worker.SharedRouteModel(node_features=8, edge_features=7, hidden=8, message_steps=1)
    position = torch.tensor([[0.0, 0.0, 0.02], [0.01, 0.0, 0.02]], dtype=torch.float32)
    velocity = torch.zeros_like(position)
    edge_index, edge_features = worker.build_radius_graph(
        position, velocity, torch.tensor([1, 2]), radius_m=0.1, max_neighbors=2
    )
    batch = GraphBatch(
        position=position,
        velocity=velocity,
        node_features=torch.zeros((2, 8)),
        edge_index=edge_index,
        edge_features=edge_features,
        interval_s=0.1,
        control_acceleration=torch.tensor([0.0, 0.0, -9.81]),
        particle_id=torch.tensor([1, 2]),
    )
    raw, raw_diag = model(batch, route="raw", return_diagnostics=True)
    hybrid, hybrid_diag = model(batch, route="hybrid", return_diagnostics=True)
    assert raw.shape == hybrid.shape == (2, 3)
    assert raw_diag["shared_graph_trunk"] is True
    assert hybrid_diag["shared_graph_trunk"] is True
    assert raw_diag["posthoc_wall_projection"] is False
    assert hybrid_diag["output_clipping"] is False
    assert torch.allclose(hybrid_diag["prior_displacement"], torch.tensor([[0.0, 0.0, -0.04905]] * 2))
    assert next(model.graph_trunk.parameters()) is next(model.graph_trunk.parameters())


def test_bounded_run_records_unknown_physical_verdict_and_complete_denominator(tmp_path, monkeypatch):
    study_path = _toy_bundle(tmp_path, monkeypatch)
    output = tmp_path / "attempt"
    result = worker.run_attempt(_run_args(study_path, output, route="hybrid"))
    assert result["status"] == "completed"
    assert result["training_completed"] is True
    assert result["evaluation_completed"] is True
    assert result["model_physical_pass"] == "unknown"
    attempt = json.loads((output / "attempt.json").read_text())
    denominator = json.loads((output / "failure-denominator.json").read_text())
    assert attempt["worker_exit_status"] == "zero"
    assert attempt["model_physical_pass"] == "unknown"
    assert denominator["logical_run_denominator"]["outcome_counts"]["physical_unknown"] == 1
    assert denominator["evaluation_case_denominator"]["status_counts"]["unknown"] == 1
    assert denominator["evaluation_case_denominator"]["status_counts"]["missing"] == 11


def test_full_evaluation_scope_emits_one_row_per_registered_case(tmp_path, monkeypatch):
    study_path = _toy_bundle(tmp_path, monkeypatch)
    output = tmp_path / "full-attempt"
    args = _run_args(study_path, output, route="hybrid")
    args.eval_case_id = None
    args.eval_all_cases = True
    result = worker.run_attempt(args)
    assert result["status"] == "completed"
    assert result["evaluation_case_count"] == 2
    assert result["full_evaluation_denominator_complete"] is True
    report = json.loads((output / "attempt-report.json").read_text())
    denominator = json.loads((output / "failure-denominator.json").read_text())
    assert report["evaluation_scope"] == "full"
    assert report["full_evaluation_denominator_complete"] is True
    assert report["evaluation"]["case_count"] == 2
    assert denominator["evaluation_case_denominator"]["status_counts"]["unknown"] == 2
    assert denominator["evaluation_case_denominator"]["status_counts"]["missing"] == 10
    assert all(row["execution_attempt_id"] == report["execution_attempt_id"] for row in denominator["evaluation_case_denominator"]["rows"] if row["status"] == "unknown")


def test_missing_case_is_a_guarded_failed_attempt_not_a_physical_pass(tmp_path, monkeypatch):
    study_path = _toy_bundle(tmp_path, monkeypatch)
    output = tmp_path / "missing"
    args = _run_args(study_path, output, train_case_id="MISSING_TRAIN")
    result = worker.run_attempt(args)
    assert result["exit_code"] == 2
    attempt = json.loads((output / "attempt.json").read_text())
    assert attempt["status"] == "failed"
    assert attempt["worker_exit_status"] == "guard_terminated"
    assert attempt["training_completed"] is False
    assert attempt["model_physical_pass"] == "not_evaluated"


def test_over_budget_is_rejected_and_recorded(tmp_path, monkeypatch):
    study_path = _toy_bundle(tmp_path, monkeypatch)
    output = tmp_path / "over-budget"
    args = _run_args(study_path, output, max_steps=worker.HARD_MAX_STEPS + 1)
    result = worker.run_attempt(args)
    assert result["exit_code"] == 2
    assert json.loads((output / "attempt.json").read_text())["failure_reason"]
    assert json.loads((output / "failure-denominator.json").read_text())["status"] == "incomplete"


def test_preflight_does_not_touch_shared_resume_or_start_training(tmp_path, monkeypatch):
    study_path = _toy_bundle(tmp_path, monkeypatch)
    output = tmp_path / "preflight-output"
    args = _run_args(study_path, output)
    args.command = "preflight"
    result = worker.preflight(args)
    assert result["status"] == "ready"
    assert result["shared_resume_mutation"] is False
    assert result["qualification_claim"] is False
    assert not output.exists()
