"""Temporary billed-record fixtures and three-step CPU manufactured rollouts.

These tests do not establish numerical/model qualification and never touch the
real training attempts, data contracts, solver, GPU or resource ledger.
"""

from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest
import torch

from scripts import f3_train_worker as worker
from scripts.f3_control import AccelerationControl
from scripts.f3_training_data import QualifiedF3Loader as RealQualifiedF3Loader


UUID = "GPU-11111111-2222-3333-4444-555555555555"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


class ManufacturedLoader:
    """A four-particle fixture with a deliberately short engineering schedule."""
    reference = None
    events = None

    def __init__(self, path):
        self.contract_path = Path(path)
        self.contract_sha256 = worker.sha256(self.contract_path)
        self.contract = json.loads(Path(path).read_text())
        self.times = np.array([0., .01, .02, .03])
        self.ids = np.array([101, 7, 500, 13], dtype=np.int64)
        self.mass = np.array([.1, .2, .3, .4])
        control = np.zeros((4, 7))
        control[:, 0] = self.times
        control[:, 3] = -9.81
        self.control = AccelerationControl(control)
        self.initial_calls = []
        self.optimization_reads = []

    def case_ids(self, split):
        return {"train": ("train",), "validation": ("good",), "test": ("bad",)}[split]

    def _position(self, name, time_s):
        p = np.array([[.05, .0, .04], [.06, .01, .04], [.07, -.01, .05], [.08, .0, .03]])
        if name == "bad":
            p[:, 0] += .2
        p[:, 0] += time_s * .1
        return p

    def _batch(self, transition):
        frame = transition.frame
        p = self._position(transition.case_id, self.times[frame])
        velocity = np.zeros_like(p)
        if frame:
            velocity[:, 0] = .1
        displacement = np.zeros_like(p)
        displacement[:, 0] = .001
        return worker.core.TransitionBatch(position=p, velocity=velocity, particle_id=self.ids.copy(),
                    target_displacement=displacement, time_s=float(self.times[frame]), interval_s=.01,
                    dp_m=.01, amplitude=1., control=self.control)

    def optimization_transitions(self):
        return tuple(worker.core.Transition("train", i) for i in range(3))

    def __call__(self, transition):
        assert transition.case_id == "train"
        self.optimization_reads.append(transition)
        return self._batch(transition)

    def evaluation_batch(self, transition):
        assert transition.case_id in ("good", "bad")
        if self.events is not None:
            self.events.append(("reference", transition.case_id, transition.frame))
        return self._batch(transition)

    def rollout_initial(self, name):
        self.initial_calls.append(name)
        p = self._position(name, 0.)
        return dict(position=p, velocity=np.zeros_like(p), particle_id=self.ids.copy(), mass=self.mass.copy(),
                    time_s=0., interval_s=.01, dp_m=.01, amplitude=1., control=self.control)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def billed(tmp_path, monkeypatch):
    root = tmp_path
    out = root / "continuation"
    out.mkdir()
    monkeypatch.setattr(worker, "LAB", root)
    monkeypatch.setattr(worker, "OUT", out)
    monkeypatch.setattr(worker, "TRAINING_ROOT", root / "training-attempts")
    monkeypatch.setattr(worker, "QualifiedF3Loader", ManufacturedLoader)
    monkeypatch.setattr(worker, "_cuda_identity", lambda: UUID)  # No actual CUDA queries.
    monkeypatch.setattr(worker, "_runtime", lambda: ("cpu", ()))
    monkeypatch.setattr(worker, "_evaluation_grid", lambda: np.array([0., .01, .02, .03]))
    monkeypatch.setattr(os, "getpgid", lambda pid: os.getpid())
    monkeypatch.setattr(os, "getsid", lambda pid: os.getpid())
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {3})
    monkeypatch.chdir(root)
    for key, value in dict(CUDA_VISIBLE_DEVICES=UUID, NVIDIA_VISIBLE_DEVICES=UUID,
                           CUDA_DEVICE_ORDER="PCI_BUS_ID", CUBLAS_WORKSPACE_CONFIG=":4096:8",
                           OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1").items():
        monkeypatch.setenv(key, value)
    source_root = Path(worker.__file__).resolve().parents[1]
    for name in worker.PROGRAMS:
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((source_root / name).read_bytes())
    gate = out / "domain.json"
    dump(gate, {"manufactured": True, "not_real_qualification": True})
    gate_ref = {"path": str(gate), "sha256": worker.sha256(gate)}
    development = out / "development.json"
    dump(development, {"source_domain_gate": gate_ref, "manufactured": True})
    dev_ref = {"path": str(development), "sha256": worker.sha256(development)}
    config = worker.core.TrainConfig(route="particle_mlp", seed=17, max_steps=4, hidden=8,
                                    max_targets=2, learning_rate=.001, dtype="float64")
    entry = dict(logical_run_id="pilot", config=asdict(config), checkpoint_steps=[2, 4],
                 development_contract=dev_ref, qualification_contract=gate_ref,
                 evaluation={"case_ids": [], "selection": "fixed_final_step_no_selection"})
    plan_path = out / "plan.json"
    plan = dict(schema=worker.PLAN_SCHEMA, status="frozen", entries=[entry],
                evidence_sha256={name: worker.sha256(root / name) for name in worker.PROGRAMS})
    dump(plan_path, plan)
    lock = (out / "solver.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    active = {}

    def attempt(execution="first", resume=None, extra=()):
        partial = worker.TRAINING_ROOT / "pilot" / (execution + ".partial")
        partial.mkdir(parents=True)
        argv = ["--plan", str(plan_path), "--plan-sha256", worker.sha256(plan_path),
                "--development-contract", str(development), "--output", str(partial), "--device", "cuda:0"]
        if resume is not None:
            argv += ["--resume-manifest", resume["checkpoint"]["path"], "--resume-sha256", resume["checkpoint"]["sha256"]]
        argv += list(extra)
        command = ["/usr/bin/taskset", "--cpu-list", "3", sys.executable, "-m", worker.MODULE, *argv]
        record = dict(schema="f3.training.attempt.v1", status="running", resource_category="training",
                      logical_run_id="pilot", execution_attempt_id=execution, pid=os.getpid(),
                      process_group_id=os.getpid(), elapsed_seconds=None, cpu_cores=1, cpu_affinity=[3],
                      gpu_index=4, gpu_uuid=UUID, shared_accounting_version="f3-training-v1", cwd=str(root),
                      command=command, qualification_contract=gate_ref, development_contract=dev_ref,
                      inherited_solver_lock_fd=lock.fileno(), resume_from=resume)
        dump(partial / "attempt.json", record)
        active.update(command=command, output=partial, argv=argv, record=record)
        return partial, argv, record

    monkeypatch.setattr(worker, "_proc_argv", lambda: active["command"][3:])
    value = dict(root=root, out=out, plan=plan, plan_path=plan_path, config=config, gate=gate,
                 development=development, attempt=attempt, active=active, lock=lock)
    yield value
    lock.close()


def test_complete_cpu_worker_logs_all_steps_and_rename_safe_checkpoints(billed):
    output, argv, _ = billed["attempt"]()
    before = (output / "attempt.json").read_bytes()
    summary = worker.run_worker(argv)
    assert (output / "attempt.json").read_bytes() == before
    assert summary["status"] == "completed" and summary["model_qualified"] is False
    assert summary["current_execution_steps"] == 4 and summary["evaluation_status"] == "not_requested"
    rows = [json.loads(line) for line in (output / "steps.jsonl").read_text().splitlines()]
    assert [r["global_step"] for r in rows] == [1, 2, 3, 4]
    assert all(r["case_id"] == "train" and len(r["sampled_particle_ids"]) == 2 for r in rows)
    assert [c["global_step"] for c in summary["checkpoints"]] == [2, 4]
    for saved in summary["checkpoints"]:
        assert Path(saved["path"]).name == saved["path"]
        manifest = json.loads((output / saved["path"]).read_text())
        assert Path(manifest["payload_file"]).name == manifest["payload_file"]
        assert worker.sha256(output / manifest["payload_file"]) == saved["payload_sha256"]


def _terminal(output, record):
    record["status"] = "completed"
    record["elapsed_seconds"] = .01
    final = output.with_name(record["execution_attempt_id"] + ".complete")
    dump(output / "attempt.json", record)
    output.rename(final)
    return final


def test_real_core_resume_after_rename_matches_uninterrupted_steps_and_weights(billed):
    output, argv, record = billed["attempt"]()
    first = worker.run_worker(argv)
    complete = _terminal(output, record)
    checkpoint = first["checkpoints"][0]
    resume = {"execution_attempt_id": record["execution_attempt_id"],
              "checkpoint": {"path": str(complete / checkpoint["path"]), "sha256": checkpoint["sha256"]}}
    second_output, second_argv, _ = billed["attempt"]("resumed", resume=resume)
    second = worker.run_worker(second_argv)
    assert second["initial_global_step"] == 2 and second["current_execution_steps"] == 2
    original_steps = (complete / "steps.jsonl").read_text().splitlines()
    assert (second_output / "steps.jsonl").read_text().splitlines() == original_steps[2:]
    a = torch.load(complete / "weights.pt", weights_only=True)
    b = torch.load(second_output / "weights.pt", weights_only=True)
    assert a["config"] == b["config"] and a["data_hashes"] == b["data_hashes"]
    for name in a["state_dict"]:
        assert torch.equal(a["state_dict"][name], b["state_dict"][name])


@pytest.mark.parametrize("change", ["status", "pid", "command", "cpu", "uuid", "env", "process", "lock", "unsafe_id"])
def test_worker_refuses_launch_identity_or_budget_bypass(billed, monkeypatch, change):
    output, argv, record = billed["attempt"]()
    if change == "status":
        record["status"] = "completed"
    elif change == "pid":
        record["pid"] += 1
    elif change == "command":
        record["command"][-1] = "cpu"
    elif change == "cpu":
        record["cpu_affinity"] = [3, 4]
    elif change == "uuid":
        monkeypatch.setattr(worker, "_cuda_identity", lambda: "GPU-99999999-2222-3333-4444-555555555555")
    elif change == "env":
        monkeypatch.setenv("OPENBLAS_NUM_THREADS", "8")
    elif change == "process":
        monkeypatch.setattr(worker, "_proc_argv", lambda: [sys.executable, "unbilled.py"])
    elif change == "unsafe_id":
        record["logical_run_id"] = "../escape"
    else:
        fcntl.flock(billed["lock"], fcntl.LOCK_UN)
    dump(output / "attempt.json", record)
    with pytest.raises(ValueError):
        worker.run_worker(argv)
    assert not (output / "worker-start.json").exists()


@pytest.mark.parametrize("change", ["code", "defaults", "cli", "selection", "contract", "checkpoint"])
def test_worker_requires_complete_frozen_plan_and_matching_command_values(billed, change):
    plan = billed["plan"]
    extra = ()
    if change == "code":
        plan["evidence_sha256"]["scripts/f3_train_worker.py"] = "0" * 64
    elif change == "defaults":
        plan["entries"][0]["config"].pop("adam_eps")
    elif change == "cli":
        extra = ("--max-steps", "5")
    elif change == "selection":
        plan["entries"][0]["evaluation"]["selection"] = "best_test_subset"
    elif change == "contract":
        plan["entries"][0]["development_contract"] = plan["entries"][0]["qualification_contract"]
    else:
        plan["entries"][0]["checkpoint_steps"] = [2]
    dump(billed["plan_path"], plan)
    output, argv, _ = billed["attempt"](extra=extra)
    with pytest.raises(ValueError):
        worker.run_worker(argv)
    assert not (output / "steps.jsonl").exists()


def test_production_loader_is_real_and_rejects_manufactured_contract(billed, monkeypatch):
    monkeypatch.setattr(worker, "QualifiedF3Loader", RealQualifiedF3Loader)
    output, argv, _ = billed["attempt"]()
    with pytest.raises(ValueError):
        worker.run_worker(argv)
    assert not (output / "weights.pt").exists()
    assert json.loads((output / "worker-summary.json").read_text())["status"] == "failed"


def test_changed_maximum_is_not_a_resume(billed):
    output, argv, record = billed["attempt"]()
    first = worker.run_worker(argv)
    final = _terminal(output, record)
    saved = first["checkpoints"][0]
    billed["plan"]["entries"][0]["config"]["max_steps"] = 5
    billed["plan"]["entries"][0]["checkpoint_steps"] = [2, 5]
    dump(billed["plan_path"], billed["plan"])
    resume = {"execution_attempt_id": "first", "checkpoint": {"path": str(final / saved["path"]), "sha256": saved["sha256"]}}
    resumed, argv, _ = billed["attempt"]("changed", resume=resume)
    with pytest.raises(ValueError, match="checkpoint semantics/config/catalogue/data/code/runtime mismatch"):
        worker.run_worker(argv)
    assert not (resumed / "weights.pt").exists()


class RecordedModel(worker.ParticleMLP):
    def __init__(self, *, bad=None, events=None):
        super().__init__(48, 8)
        self.bad = bad
        self.events = events
        self.seen_positions = []

    def forward(self, base, local=None):
        if self.events is not None:
            self.events.append(("model",))
        self.seen_positions.append(base[:, :3].detach().cpu().clone())
        out = torch.zeros((len(base), 3), dtype=base.dtype, device=base.device)
        if self.bad == "nonfinite" and base[0, 0] > .2:
            out[:] = float("nan")
        elif self.bad == "wall":
            out[:, 0] = 100.
        return out


def test_autonomous_evaluation_scores_after_prediction_and_retains_all_states(billed, monkeypatch):
    events = []
    monkeypatch.setattr(ManufacturedLoader, "events", events)
    loader = ManufacturedLoader(billed["development"])
    model = RecordedModel(events=events).double()
    result = worker.evaluate_model(model, loader, ["good"], billed["root"] / "evaluation", "cpu")
    assert loader.initial_calls == ["good"]
    assert [e[0] for e in events] == ["model", "reference"] * 3
    # A stationary model must keep using its own unchanged positions, despite
    # the reference's positive x motion supplied to the independent scorer.
    assert all(torch.equal(p, model.seen_positions[0]) for p in model.seen_positions)
    assert result["expected_frames_per_case"] == 4  # Short fixture, not full qualification.
    assert result["status"] == "passed" and result["model_qualified"] is False
    panel = result["cases"][0]
    assert panel["completed_steps"] == 3 and panel["final_time_s"] == .03
    assert {"tv", "com_l2_over_length", "q90_over_length", "mean_velocity_over_U", "energy_difference",
            "common_support_velocity_over_U", "unmatched_support_mass", "position_same_id_rms",
            "position_same_id_mass_rms", "velocity_same_id_rms", "velocity_same_id_mass_rms"} == set(panel["metrics_maxima"])
    with h5py.File(billed["root"] / "evaluation" / panel["predicted_hdf5"]["path"], "r") as h:
        assert h["position"].shape == (4, 4, 3)
        assert h["normalized_displacement"].shape == (3, 4, 3)
        np.testing.assert_array_equal(h["particle_id"][:], loader.ids)
        np.testing.assert_array_equal(h["mass"][:], loader.mass)
        np.testing.assert_array_equal(h["time"][:], loader.times)


@pytest.mark.parametrize("failure", ["wall", "nonfinite"])
def test_failure_keeps_original_denominator_without_success_subset_ranking(billed, failure):
    loader = ManufacturedLoader(billed["development"])
    result = worker.evaluate_model(RecordedModel(bad=failure).double(), loader, ["good", "bad"],
                                   billed["root"] / "failed-evaluation", "cpu")
    assert result["declared_case_denominator"] == 2 and len(result["cases"]) == 2
    assert result["status"] == "failed" and result["ranking_eligible"] is False
    assert result["aggregate_metrics_mean"] is None
    assert loader.initial_calls == ["good", "bad"]
    if failure == "wall":
        assert result["failed_cases"] == 2
        for panel in result["cases"]:
            assert panel["saved_frames"] == 4 and panel["swept_crossing_count"] > 0
            with h5py.File(billed["root"] / "failed-evaluation" / panel["predicted_hdf5"]["path"], "r") as h:
                assert h["position"][-1, :, 0].min() > .45
    else:
        assert result["failed_cases"] == 1 and result["passed_cases"] == 1
        failed = result["cases"][1]
        assert failed["saved_frames"] == 1 and failed["completed_steps"] == 0
        assert "nonfinite" in failed["terminal_failure"]["message"]


def test_evaluation_rejects_training_cases_and_noncanonical_schedule(billed):
    loader = ManufacturedLoader(billed["development"])
    with pytest.raises(ValueError, match="validation/public"):
        worker.evaluate_model(RecordedModel(), loader, ["train"], billed["root"] / "bad", "cpu")
    loader.times = np.array([0., .02, .03])
    with pytest.raises(ValueError, match="fixed qualified"):
        worker.evaluate_model(RecordedModel(), loader, ["good"], billed["root"] / "bad", "cpu")
    assert not (billed["root"] / "bad").exists()


@pytest.mark.parametrize("route", ["particle_mlp", "local_interaction"])
def test_worker_connects_both_real_core_routes_to_frozen_evaluation(billed, route):
    entry = billed["plan"]["entries"][0]
    entry["config"]["route"] = route
    entry["evaluation"]["case_ids"] = ["good", "bad"]
    dump(billed["plan_path"], billed["plan"])
    output, argv, _ = billed["attempt"]()
    summary = worker.run_worker(argv)
    assert summary["training_status"] == "completed" and summary["completed_global_step"] == 4
    score_path = output / summary["evaluation_summary"]["path"]
    assert worker.sha256(score_path) == summary["evaluation_summary"]["sha256"]
    result = json.loads(score_path.read_text())
    assert result["case_ids"] == ["good", "bad"] and result["declared_case_denominator"] == 2
    assert all(panel["expected_frames"] == panel["saved_frames"] == 4 for panel in result["cases"])
    assert summary["config"]["route"] == route and summary["model_qualified"] is False


def test_training_failure_keeps_committed_log_and_preceding_checkpoint(billed, monkeypatch):
    real_step = worker.core.step

    def fail_after_checkpoint(state, loader):
        if state.global_step == 2:
            raise ValueError("manufactured failure after checkpoint")
        return real_step(state, loader)

    monkeypatch.setattr(worker.core, "step", fail_after_checkpoint)
    output, argv, _ = billed["attempt"]()
    with pytest.raises(ValueError, match="manufactured failure"):
        worker.run_worker(argv)
    summary = json.loads((output / "worker-summary.json").read_text())
    assert summary["status"] == "failed" and summary["last_committed_global_step"] == 2
    assert [c["global_step"] for c in summary["checkpoints"]] == [2]
    assert len((output / "steps.jsonl").read_text().splitlines()) == 2
    assert not (output / "weights.pt").exists()
