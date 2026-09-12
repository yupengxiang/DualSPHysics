"""Billed F3 training worker and complete autonomous evaluation.

The CLI only operates inside its own running training-runner attempt. A frozen
plan, actual qualified development contract and inherited launch identity are
required; there is no CPU/engineering bypass flag. Unit tests replace those
external boundaries with temporary manufactured records and tiny CPU sources.
"""

import argparse
from dataclasses import asdict, fields
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time

import h5py
import numpy as np
import torch

from experiments.r3_g4_baselines import LocalInteraction, ParticleMLP
from scripts import f3_training_core as core
from scripts.f3_training_data import QualifiedF3Loader, target_grid
from scripts.f3_rollout import EngineeringF3Rollout
from scripts.f3_observation_v2 import observe_arrays, compare
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now

TRAINING_ROOT = LAB / "campaigns/l1-resume/training-attempts"
PLAN_SCHEMA = "f3.training.plan.v1"
MODULE = "scripts.f3_train_worker"
PROGRAMS = ("scripts/f3_train_worker.py", "scripts/f3_training_data.py", "scripts/f3_training_core.py",
            "scripts/f3_rollout.py", "scripts/f3_observation_v2.py", "scripts/finite_wall_audit.py",
            "scripts/f3_control.py", "scripts/f3_learning_inputs.py", "scripts/f3_local_neighbors.py",
            "experiments/r3_g4_baselines.py", "scripts/f3_training_runner.py",
            "scripts/l1r_continuation_evidence.py")
WALL_SPEC = {"container_interior": {"xmin": -.45, "xmax": .45, "ymin": -.09, "ymax": .09,
                                    "zmin": 0., "zmax": .51},
             "closed_faces": ["bottom", "left", "right", "front", "back"],
             "open_faces": ["top"], "obstacles": []}
WALL_TOLERANCE = .0051  # Same endpoint tolerance as the native continuation audit.


def _read(path):
    return json.loads(Path(path).read_text())


def _path(value):
    path = Path(value)
    if not path.is_absolute():
        path = LAB / path
    path = path.resolve()
    path.relative_to(LAB.resolve())
    return path


def _bound(value):
    path = _path(value["path"])
    digest = value.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest) or sha256(path) != digest:
        raise ValueError("bound plan/contract/checkpoint file changed")
    return {"path": str(path), "sha256": digest}


def _proc_argv():
    return [p.decode() for p in Path("/proc/self/cmdline").read_bytes().split(b"\0") if p]


def _cuda_identity():
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("worker requires exactly the one runner-selected visible CUDA device")
    return str(torch.cuda.get_device_properties(0).uuid)


def _uuid(value):
    value = str(value).lower().removeprefix("gpu-")
    if not re.fullmatch("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
        raise ValueError("invalid selected GPU UUID")
    return value


def _running(output):
    record = _read(output / "attempt.json")
    if (record.get("schema") != "f3.training.attempt.v1" or record.get("resource_category") != "training"
            or record.get("status") != "running" or record.get("elapsed_seconds") is not None
            or record.get("pid") != os.getpid() or record.get("process_group_id") != os.getpid()):
        raise ValueError("worker must own a current running billed training attempt")
    return record


def _verify_attempt(args, argv):
    output = _path(args.output)
    # Popen and the parent's atomic PID update can race by a few milliseconds.
    deadline = time.monotonic() + 5.
    while True:
        pending = _read(output / "attempt.json")
        if pending.get("pid") is not None or pending.get("status") != "running" or time.monotonic() >= deadline:
            break
        time.sleep(.02)
    record = _running(output)
    for field in ("logical_run_id", "execution_attempt_id"):
        if not isinstance(record.get(field), str) or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_.-]*", record[field]):
            raise ValueError("unsafe billed training identity")
    output.relative_to(TRAINING_ROOT.resolve())
    expected = TRAINING_ROOT / record["logical_run_id"] / (record["execution_attempt_id"] + ".partial")
    if (output != expected.resolve() or not output.is_dir() or Path.cwd().resolve() != _path(record["cwd"])
            or record.get("shared_accounting_version") != "f3-training-v1"
            or record.get("cpu_cores") != 1 or record.get("gpu_index") not in (4, 5, 6, 7)
            or os.getpgid(0) != os.getpid() or os.getsid(0) != os.getpid()
            or sorted(os.sched_getaffinity(0)) != record.get("cpu_affinity")):
        raise ValueError("attempt output, process group, CPU/GPU identity or accounting contract differs")
    command = record.get("command", [])
    if (len(command) < 6 or Path(command[0]).name != "taskset" or command[1] != "--cpu-list"
            or command[2] != ",".join(map(str, record["cpu_affinity"]))
            or Path(command[3]).resolve() != Path(sys.executable).resolve()
            or command[4:6] != ["-m", MODULE] or command[6:] != list(argv)):
        raise ValueError("worker argv differs from its billed exact command")
    actual = _proc_argv()
    if not actual or Path(actual[0]).resolve() != Path(command[3]).resolve() or actual[1:] != command[4:]:
        raise ValueError("current process is not the recorded worker command")
    if args.device != "cuda:0":
        raise ValueError("production worker only uses the runner-selected cuda:0")
    for key in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        if os.environ.get(key) != record.get("gpu_uuid"):
            raise ValueError("visible GPU environment differs from the billed UUID")
    if (os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID"
            or os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8"
            or any(os.environ.get(k) != "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"))):
        raise ValueError("worker deterministic CUDA/one-core environment is not fixed")
    fd = record["inherited_solver_lock_fd"]
    stat, expected_stat = os.fstat(fd), (OUT / "solver.lock").stat()
    if (stat.st_dev, stat.st_ino) != (expected_stat.st_dev, expected_stat.st_ino):
        raise ValueError("worker did not inherit the shared solver/training lock")
    with (OUT / "solver.lock").open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise ValueError("shared solver/training lock is not held by the launch")
    if _uuid(_cuda_identity()) != _uuid(record["gpu_uuid"]):
        raise ValueError("actual CUDA device differs from the billed GPU UUID")
    _bound(record["development_contract"])
    _bound(record["qualification_contract"])
    if _path(args.development_contract) != _path(record["development_contract"]["path"]):
        raise ValueError("CLI development contract differs from the billed source")
    return output, record


def _plan(args, record):
    bound = _bound({"path": args.plan, "sha256": args.plan_sha256})
    plan = _read(bound["path"])
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "frozen":
        raise ValueError("a frozen complete training plan is required")
    bindings = plan.get("evidence_sha256", {})
    if not set(PROGRAMS).issubset(bindings):
        raise ValueError("training plan omits executing code/evaluation evidence")
    for path, digest in bindings.items():
        _bound({"path": path, "sha256": digest})
    if bindings["scripts/f3_train_worker.py"] != sha256(Path(__file__)):
        raise ValueError("frozen worker differs from the executing program")
    entries = plan.get("entries", [])
    names = [e["logical_run_id"] for e in entries]
    if len(set(names)) != len(names) or names.count(record["logical_run_id"]) != 1:
        raise ValueError("training plan must identify this logical run exactly once")
    entry = entries[names.index(record["logical_run_id"])]
    if set(entry["config"]) != {f.name for f in fields(core.TrainConfig)}:
        raise ValueError("plan must freeze every TrainConfig field, including optimizer defaults")
    config = core.TrainConfig(**entry["config"])
    if config.validation_patience is not None:
        raise ValueError("this worker uses the fixed final step; model selection is not registered")
    for name in ("route", "seed", "max_steps", "max_targets", "hidden", "learning_rate"):
        value = getattr(args, name)
        if value is not None and value != getattr(config, name):
            raise ValueError("CLI configuration differs from the frozen training plan")
    checkpoints = entry["checkpoint_steps"]
    if (not isinstance(checkpoints, list) or not checkpoints
            or any(type(k) is not int or not 0 < k <= config.max_steps for k in checkpoints)
            or checkpoints != sorted(set(checkpoints)) or checkpoints[-1] != config.max_steps
            or args.checkpoint_step is not None and args.checkpoint_step != checkpoints):
        raise ValueError("explicit checkpoint schedule must include the unchanged final maximum step")
    for key in ("development_contract", "qualification_contract"):
        if _bound(entry[key]) != _bound(record[key]):
            raise ValueError("plan source contract differs from the billed attempt")
    evaluation = entry["evaluation"]
    if (evaluation.get("selection") != "fixed_final_step_no_selection"
            or not isinstance(evaluation.get("case_ids"), list)
            or len(set(evaluation["case_ids"])) != len(evaluation["case_ids"])):
        raise ValueError("plan must freeze evaluation cases without test-based weight selection")
    return bound, entry, config


def _resume(args, record):
    prior = record.get("resume_from")
    if prior is None:
        if args.resume_manifest is not None or args.resume_sha256 is not None:
            raise ValueError("resume arguments require a separately billed resume attempt")
        return None
    if args.resume_manifest is None or args.resume_sha256 is None:
        raise ValueError("billed resume requires its explicit manifest and SHA256")
    checkpoint = _bound({"path": args.resume_manifest, "sha256": args.resume_sha256})
    if checkpoint != _bound(prior["checkpoint"]):
        raise ValueError("resume checkpoint differs from the launcher-bound source")
    source = Path(checkpoint["path"]).parent
    expected = TRAINING_ROOT / record["logical_run_id"]
    if source.parent != expected.resolve() or source.name not in (
            prior["execution_attempt_id"] + ".complete", prior["execution_attempt_id"] + ".failed"):
        raise ValueError("resume checkpoint does not belong to the prior logical-run attempt")
    old = _read(source / "attempt.json")
    if (old.get("status") not in ("completed", "failed") or old.get("logical_run_id") != record["logical_run_id"]
            or old.get("execution_attempt_id") != prior["execution_attempt_id"]
            or any(_bound(old[k]) != _bound(record[k]) for k in ("development_contract", "qualification_contract"))):
        raise ValueError("resume requires the matching terminal source attempt and unchanged data")
    return checkpoint


def _runtime():
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    return "cuda:0", (0,)


def _evaluation_grid():
    return target_grid(.01)


def _route(model):
    if isinstance(model, ParticleMLP):
        return "particle_mlp"
    if isinstance(model, LocalInteraction):
        return "local_interaction"
    raise ValueError("evaluation requires one of the two registered direct-displacement models")


def _append(dataset, array):
    dataset.resize(len(dataset) + 1, axis=0)
    dataset[-1] = array


def _score(predicted_p, predicted_v, reference_p, reference_v, mass):
    total = float(mass.sum())
    metrics = compare(observe_arrays(predicted_p, predicted_v, mass, total),
                      observe_arrays(reference_p, reference_v, mass, total))
    for label, delta in (("position", predicted_p - reference_p), ("velocity", predicted_v - reference_v)):
        squared = np.sum(delta.astype(float)**2, axis=1)
        metrics[label + "_same_id_mass_rms"] = float(np.sqrt(np.sum(mass * squared) / total))
        metrics[label + "_same_id_rms"] = float(np.sqrt(squared.mean()))
    if not all(np.isfinite(v) for v in metrics.values()):
        raise ValueError("nonfinite complete-axis evaluation metric")
    return metrics


def evaluate_model(model, loader, case_ids, output, device):
    """Stream every declared case on the complete fixed grid, without selection.

    This callable does not own resource accounting; production calls belong to
    run_worker. Only detached frame zero and known control enter the rollout.
    Reference batches are queried after predictions, solely for scoring at the
    already-predicted time. Finite wall-invalid predictions continue unchanged.
    """
    if not isinstance(loader, QualifiedF3Loader):
        raise ValueError("autonomous evaluation requires a verified qualified source loader")
    names = tuple(case_ids)
    allowed = set(loader.case_ids("validation")) | set(loader.case_ids("test"))
    if not names or len(set(names)) != len(names) or any(n not in allowed for n in names):
        raise ValueError("evaluation requires distinct registered validation/public development test cases")
    grid = _evaluation_grid()
    if not np.array_equal(loader.times, grid):
        raise ValueError("prediction schedule must be the fixed qualified 0..8.35 s grid")
    route = _route(model)
    model.eval()
    dtype = next(model.parameters()).dtype
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    panels = []
    started = time.monotonic()
    for name in names:
        begin = time.monotonic()
        panel = dict(case_id=name, status="failed", expected_frames=len(grid), saved_frames=0,
                     expected_final_time_s=float(grid[-1]), final_time_s=None, completed_steps=0,
                     hard_wall_passed=False, wall_invalid_frames=0, swept_crossing_count=0,
                     first_failure=None, metrics_maxima=None, metrics_mean=None,
                     ranking_eligible=False, raw_predictions_projected=False, particle_filtering=False)
        metrics_rows = []
        path = output / (name + "-predicted.h5")
        try:
            initial = loader.rollout_initial(name)  # The only rollout fluid-input read.
            ids = np.asarray(initial["particle_id"])
            mass = np.asarray(initial["mass"], dtype=float)
            if (ids.ndim != 1 or ids.dtype.kind not in "iu" or len(set(ids.tolist())) != len(ids)
                    or mass.shape != ids.shape or not np.isfinite(mass).all() or np.any(mass <= 0)):
                raise ValueError("complete initial identities and positive immutable mass are required")
            run = EngineeringF3Rollout(model, route=route,
                    position=torch.as_tensor(initial["position"], device=device, dtype=dtype),
                    velocity=torch.as_tensor(initial["velocity"], device=device, dtype=dtype),
                    particle_id=ids, time_s=initial["time_s"], dp_m=initial["dp_m"],
                    amplitude=initial["amplitude"], control=initial["control"], max_steps=len(grid) - 1)
            panel.update(particle_count=len(ids), initial_mass_kg=float(mass.sum()),
                         initial_velocity="native", mass_and_identity_axis_preserved=True)
            with h5py.File(path, "x") as h, (output / (name + "-scores.jsonl")).open("x") as log:
                h["particle_id"], h["mass"] = ids, mass
                h.attrs["prediction_semantics"] = "raw autonomous direct displacement; no clipping/projection/filtering"
                h.attrs["expected_frames"] = len(grid)
                datasets = {k: h.create_dataset(k, shape=(0, len(ids), 3), maxshape=(None, len(ids), 3),
                                             chunks=(1, len(ids), 3), dtype=str(run.state.position.cpu().numpy().dtype))
                            for k in ("position", "velocity", "normalized_displacement")}
                times = h.create_dataset("time", shape=(0,), maxshape=(None,), dtype="f8")
                previous = None
                for index, expected in enumerate(grid):
                    raw = None
                    if index:
                        step = run.step(float(grid[index] - grid[index - 1]))
                        raw = step.normalized_displacement.detach().cpu().numpy()
                    if run.state.time_s != float(expected) or run.state.particle_id != tuple(int(i) for i in ids):
                        raise ValueError("autonomous time or complete identity axis changed")
                    p = run.state.position.detach().cpu().numpy()
                    v = run.state.velocity.detach().cpu().numpy()
                    _append(datasets["position"], p)
                    _append(datasets["velocity"], v)
                    _append(times, float(expected))
                    if raw is not None:
                        _append(datasets["normalized_displacement"], raw)
                    panel.update(saved_frames=index + 1, completed_steps=index, final_time_s=float(expected))
                    walls = wall_penetration(p, mass, WALL_SPEC, WALL_TOLERANCE)
                    events = [] if previous is None else segment_crossing_events(previous, p, WALL_SPEC, WALL_TOLERANCE)
                    bad = bool(walls["outside_closed_container_count"] or walls["obstacle_penetration_count"] or events)
                    panel["wall_invalid_frames"] += int(bad)
                    panel["swept_crossing_count"] += len(events)
                    if bad and panel["first_failure"] is None:
                        crossing = None if not events else {**events[0], "particle_id": int(ids[events[0]["point_index"]]),
                                    "estimated_time_s": float(grid[index - 1] + events[0]["fraction"] * (expected - grid[index - 1]))}
                        panel["first_failure"] = {"kind": "hard_wall_or_crossing", "time_s": float(expected),
                                                  "walls": walls, "first_crossing": crossing}
                    if index == 0:
                        ref_p, ref_v = initial["position"], initial["velocity"]
                    else:
                        # Target is at the current predicted time, not a future
                        # teacher state. The model never receives this batch.
                        batch = loader.evaluation_batch(core.Transition(name, index - 1))
                        if not np.array_equal(np.asarray(batch.particle_id), ids):
                            raise ValueError("scoring reference changed native identity order")
                        ref_p = np.asarray(batch.position) + np.asarray(batch.target_displacement)
                        ref_v = np.asarray(batch.target_displacement) / batch.interval_s
                    metrics = _score(p, v, ref_p, ref_v, mass)
                    metrics_rows.append(metrics)
                    log.write(json.dumps({"frame": index, "time_s": float(expected), "metrics": metrics,
                                          "wall": walls, "swept_crossing_count": len(events)}, allow_nan=False) + "\n")
                    log.flush()
                    previous = p.copy()
                h.attrs["completed_full_grid"] = True
            panel["hard_wall_passed"] = panel["wall_invalid_frames"] == 0
            panel["status"] = "passed" if panel["hard_wall_passed"] else "failed"
            panel["ranking_eligible"] = panel["status"] == "passed"
        except Exception as error:
            failure = {"kind": "runtime_or_nonfinite_failure", "message": f"{type(error).__name__}: {error}",
                       "after_completed_steps": panel["completed_steps"]}
            if panel["first_failure"] is None:
                panel["first_failure"] = failure
            panel["terminal_failure"] = failure
        if metrics_rows:
            panel["metrics_maxima"] = {k: max(r[k] for r in metrics_rows) for k in metrics_rows[0]}
            panel["metrics_mean"] = {k: float(np.mean([r[k] for r in metrics_rows])) for k in metrics_rows[0]}
        if path.exists():
            panel["predicted_hdf5"] = {"path": path.name, "sha256": sha256(path)}
        scores = output / (name + "-scores.jsonl")
        if scores.exists():
            panel["scores_jsonl"] = {"path": scores.name, "sha256": sha256(scores)}
        panel["elapsed_seconds"] = time.monotonic() - begin
        atomic_json(output / (name + "-panel.json"), panel)
        panels.append(panel)
    passed = sum(p["status"] == "passed" for p in panels)
    complete = passed == len(names)
    result = dict(schema="f3.training.autonomous_evaluation.v1", case_ids=list(names), cases=panels,
                  declared_case_denominator=len(names), passed_cases=passed, failed_cases=len(names) - passed,
                  status="passed" if complete else "failed", ranking_eligible=complete,
                  aggregate_metrics_mean=({k: float(np.mean([p["metrics_mean"][k] for p in panels]))
                                           for k in panels[0]["metrics_mean"]} if complete else None),
                  failed_case_policy="All declared cases remain in the denominator; no successful-subset RMSE ranking",
                  status_semantics="Full declared rollout and hard wall integrity; no model accuracy threshold or qualification claim",
                  time_window_s=[float(grid[0]), float(grid[-1])], expected_frames_per_case=len(grid),
                  endpoint_wall_tolerance_m=WALL_TOLERANCE, crossing_semantics="saved-frame finite-face linear chord events",
                  posthoc_projection=False, model_qualified=False, material_layers_qualified=[],
                  elapsed_seconds=time.monotonic() - started)
    atomic_json(output / "summary.json", result)
    return result


def _saved_checkpoint(state, output):
    path = output / f"checkpoint-step-{state.global_step:08d}.json"
    if path.exists():
        raise ValueError("worker checkpoint manifest already exists")
    bound = core.save_checkpoint(state, path)
    manifest = _read(path)
    # Both references survive the parent's .partial -> .complete/.failed rename.
    return dict(path=path.name, sha256=bound["sha256"], payload_file=manifest["payload_file"],
                payload_sha256=bound["payload_sha256"], global_step=state.global_step)


def run_worker(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    output, attempt = _verify_attempt(args, argv)
    plan_bound, entry, config = _plan(args, attempt)
    resume = _resume(args, attempt)
    for name in ("steps.jsonl", "worker-summary.json", "weights.pt", "worker-start.json"):
        if (output / name).exists():
            raise ValueError("attempt already has worker artifacts; relaunch requires another billed attempt")
    summary = dict(schema="f3.training.worker.v1", status="failed", logical_run_id=attempt["logical_run_id"],
                   execution_attempt_id=attempt["execution_attempt_id"], plan=plan_bound,
                   config=asdict(config), checkpoints=[], resume_from=resume,
                   model_qualified=False, material_layers_qualified=[], formal_release=False)
    started = time.monotonic()
    atomic_json(output / "worker-start.json", {**summary, "started_at_utc": utc_now()})
    try:
        # QualifiedF3Loader performs the complete real development/domain guard.
        # No contract-bypass parameter or alternate production loader is offered.
        with QualifiedF3Loader(args.development_contract) as loader:
            source = _bound(loader.contract["source_domain_gate"])
            if (source != _bound(attempt["qualification_contract"])
                    or loader.contract_sha256 != attempt["development_contract"]["sha256"]):
                raise ValueError("verified loader sources differ from the billed contracts")
            allowed = set(loader.case_ids("validation")) | set(loader.case_ids("test"))
            if any(n not in allowed for n in entry["evaluation"]["case_ids"]):
                raise ValueError("frozen evaluation contains an uncompleted or training case")
            catalogue = loader.optimization_transitions()
            data_hashes = dict(development_contract=loader.contract_sha256, qualification_contract=source["sha256"],
                               training_plan=plan_bound["sha256"], worker_program=sha256(Path(__file__)))
            device, cuda_devices = _runtime()
            if resume is None:
                state = core.TrainState.create(config, catalogue, data_hashes, device=device, cuda_devices=cuda_devices)
            else:
                state = core.load_checkpoint(resume["path"], expected_sha256=resume["sha256"], config=config,
                                             transitions=catalogue, data_hashes=data_hashes,
                                             device=device, cuda_devices=cuda_devices)
            summary.update(initial_global_step=state.global_step, data_hashes=data_hashes,
                           transition_count=len(catalogue), runtime=state.runtime)
            with (output / "steps.jsonl").open("x") as log:
                while state.global_step < config.max_steps:
                    _running(output)
                    row = core.step(state, loader)
                    log.write(json.dumps(row, allow_nan=False) + "\n")
                    log.flush()
                    summary["last_committed_global_step"] = state.global_step
                    if state.global_step in entry["checkpoint_steps"]:
                        os.fsync(log.fileno())
                        summary["checkpoints"].append(_saved_checkpoint(state, output))
            if not summary["checkpoints"] or summary["checkpoints"][-1]["global_step"] != config.max_steps:
                summary["checkpoints"].append(_saved_checkpoint(state, output))
            weights = {k: v.detach().cpu().clone() for k, v in state.model.state_dict().items()}
            torch.save({"state_dict": weights, "config": asdict(config), "data_hashes": data_hashes,
                        "global_step": state.global_step, "selection": "fixed_final_step_no_selection"}, output / "weights.pt")
            summary.update(training_status="completed", completed_global_step=state.global_step,
                           current_execution_steps=state.global_step - summary["initial_global_step"],
                           weights={"path": "weights.pt", "sha256": sha256(output / "weights.pt")})
            names = entry["evaluation"]["case_ids"]
            evaluation = evaluate_model(state.model, loader, names, output / "evaluation", device) if names else None
            summary.update(evaluation_status=evaluation["status"] if evaluation else "not_requested",
                           evaluation_summary=({"path": "evaluation/summary.json", "sha256": sha256(output / "evaluation/summary.json")}
                                               if evaluation else None),
                           status="completed" if evaluation is None or evaluation["status"] == "passed" else "failed")
    except Exception as error:
        summary["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        summary["elapsed_seconds"] = time.monotonic() - started
        atomic_json(output / "worker-summary.json", summary)
    return summary


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for flag in ("development-contract", "output", "device", "plan", "plan-sha256"):
        result.add_argument("--" + flag, required=True)
    result.add_argument("--route", choices=("particle_mlp", "local_interaction"))
    for flag in ("seed", "max-steps", "max-targets", "hidden"):
        result.add_argument("--" + flag, type=int)
    result.add_argument("--learning-rate", type=float)
    result.add_argument("--checkpoint-step", type=int, action="append")
    result.add_argument("--resume-manifest")
    result.add_argument("--resume-sha256")
    return result


def main(argv=None):
    summary = run_worker(argv)
    print(json.dumps({k: summary[k] for k in ("status", "logical_run_id", "training_status", "evaluation_status")}), flush=True)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
