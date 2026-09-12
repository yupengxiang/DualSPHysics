"""Frozen F3 material candidates, aligned references and bounded CPU attempts.

Nothing runs on import. Registration and execution are explicit operations. An
execution success is never a T2 qualification; quadrature and matrix gates remain
separate. Production requires the newly calibrated, hash-bound interpolator.
"""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

import h5py
import numpy as np

from scripts import f3_nopen_stage_score as source_score
from scripts import f3_nopen_qualification as qualification
from scripts import l1r_continuation_evidence as resources
from scripts import passive_tracers
from scripts.f3_material_reference_score import THRESHOLDS, label_trace
from scripts.l1r_cpu_slots import cpu_slot


LAB = Path(__file__).resolve().parents[1]
OUT = LAB / "campaigns/l1-resume/continuation"
DATA = LAB / "campaigns/l1-resume/data/f3-material-reference"
PLAN_NAME = "F3-MATERIAL-REFERENCE-PLAN.json"
PLAN_SCHEMA = "f3.material.reference_plan.v1"
ATTEMPT_SCHEMA = "f3.material.reference_attempt.v1"
GRACE_SECONDS = 5.
POSTPROCESS_RESERVE_SECONDS = 600.
CPU_ACTIVITY_CORES = 17.6
SUPPORT = {"minimum_effective_sample_size": 4., "minimum_geometry_rank": 3,
           "minimum_anisotropy": .005,
           "maximum_reconstruction_error_mps": .05*math.sqrt(9.81*.09)}
DIAGNOSTICS = ("nearest_support_distance", "minimum_visible_neighbours", "visibility_search_width",
               "wall_crossing", "effective_sample_size", "support_geometry_rank",
               "support_anisotropy", "interpolation_reconstruction_error_mps", "support_gate_pass")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    os.replace(temporary, path)


def _path(relative):
    path = (LAB/relative).resolve()
    path.relative_to(LAB.resolve())
    return path


def _reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path)}


def frozen_seeds():
    axes = [lo+(np.arange(n)+.5)*width/n for lo, width, n in
            zip([-.45, -.09, 0.], [.9, .18, .09], [16, 8, 4])]
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return {"tracer_id": np.array([f"F3-material-{j:04d}" for j in range(512)]),
            "initial_position": points, "mass_fraction": np.full(512, 1/512),
            "source_label": (points[:, 0] >= 0).astype(np.int8)}


def configurations():
    dp = {"NP01": .01, "NP05": .0075, "NP06": .006, "NP10": .01, "NP12": .006}
    rows = [dict(config_id=f"{case}-s{substeps}", plan_case_id=case, dp_m=dp[case],
                 amplitude=1. if case in ("NP01", "NP05", "NP06") else 1.1,
                 output_interval_s=.01, substeps=substeps, seeds=512,
                 required_gate="nominal" if case in ("NP01", "NP05", "NP06") else "endpoints",
                 role="nominal" if case in ("NP01", "NP05", "NP06") else "fixed_a1.1_endpoint")
            for case in ("NP01", "NP05", "NP06", "NP10", "NP12") for substeps in (2, 4)]
    rows.append(dict(config_id="NP04-cadence-s4", plan_case_id="NP04", dp_m=.01, amplitude=1., output_interval_s=.002,
                     substeps=4, seeds=512, required_gate="nominal", role="preregistered_cadence_candidate"))
    return rows


def code_hashes():
    return {name: sha256(LAB/name) for name in (
        "scripts/f3_material_reference.py", "scripts/f3_material_reference_score.py",
        "scripts/f3_material_neighbors.py", "scripts/passive_tracers.py",
        "scripts/f3_material_calibration.py", "scripts/f3_material_labels.py",
        "scripts/f3_nopen_stage_score.py", "scripts/f3_reference_score.py")}


def verify_calibration(reference):
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("new backend calibration requires path and SHA256")
    path = Path(reference["path"]).resolve()
    if not path.is_file() or sha256(path) != reference["sha256"]:
        raise ValueError("calibration file changed or is missing")
    value = json.loads(path.read_text())
    hashes = code_hashes()
    for field, filename in (("tracer_sha256", "scripts/passive_tracers.py"),
                            ("interpolator_sha256", "scripts/f3_material_neighbors.py"),
                            ("program_sha256", "scripts/f3_material_calibration.py")):
        if value.get(field) != hashes[filename]:
            raise ValueError("new backend calibration code mismatch: "+field)
    design = value.get("design", {})
    expected_acceptance = dict(maximum_path_error_m=.001, maximum_residence_error_s=.01,
                               required_reliable_fraction=1., terminal_disagreement_fraction=0.)
    if (value.get("status") != "completed" or value.get("calibrated") is not True
            or value.get("configuration_charge") != 4 or design.get("seeds") != 64
            or design.get("substeps") != 2 or design.get("time_window_s") != [0, .5]
            or design.get("output_interval_s") != .01 or design.get("neighbours") != 24
            or design.get("regularization_m") != .004 or design.get("maximum_support_distance_m") != .03
            or design.get("same_physical_seeds_across_resolutions") is not True
            or design.get("acceptance") != expected_acceptance):
        raise ValueError("new backend manufactured calibration has not passed its frozen design")
    axes = [[-.021, -.007, .007, .021], [-.021, -.007, .007, .021], [.024, .036, .048, .060]]
    seeds = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    if not np.array_equal(np.asarray(design.get("seed_positions_m")), seeds):
        raise ValueError("manufactured calibration changed physical seeds")
    rows = value.get("results", [])
    if len(rows) != 4 or {(r.get("flow"), r.get("dp_m")) for r in rows} != {
        (flow, dp) for flow in ("shear", "rotation") for dp in (.01, .006)
    }:
        raise ValueError("manufactured calibration lacks the four completed configurations")
    for row in rows:
        if (row.get("passed") is not True or not 0 <= row.get("max_path_error_m", math.inf) <= .001
                or not 0 <= row.get("maximum_residence_error_s", math.inf) <= .01
                or row.get("reliable_fraction") != 1 or row.get("terminal_disagreement_fraction") != 0):
            raise ValueError("manufactured calibration result failed")
        artifact = _path(row["artifact"])
        source = _path(row["source"]) if "source" in row else artifact.with_suffix(".h5")
        if sha256(artifact) != row["artifact_sha256"] or sha256(source) != row["source_sha256"]:
            raise ValueError("manufactured calibration evidence changed")
    return {"path": str(path), "sha256": reference["sha256"]}


def _plan(calibration):
    seeds = {k: v.tolist() for k, v in frozen_seeds().items()}
    return dict(schema=PLAN_SCHEMA, status="registered_candidate", configuration_charge=0,
                configurations=configurations(), seed_design=seeds,
                seed_design_sha256=hashlib.sha256(json.dumps(seeds, sort_keys=True).encode()).hexdigest(),
                seed_rule="independent 16x8x4 equal-volume points; not source particle identities",
                mass_rule="common fractions; kg weights use each audited initial source mass without editing solver masses",
                coordinate_frame="fixed tank coordinates", time_window_s=[0., 8.35],
                neighbours=24, regularization_m=.004, maximum_support_distance_m=.03,
                support_gate=dict(SUPPORT), thresholds=dict(THRESHOLDS),
                threshold_origin="new prospective CFD material definitions; not the old manufactured gates",
                calibration=calibration, code_sha256=code_hashes(),
                planned_total_material_count=25, prior_charged_configurations=10,
                prerequisite_new_backend_calibrations=4, main_configurations=10, cadence_configurations=1,
                quadrature_status="pending; no 64/512 substitution or post-result selection",
                qualified_T2_macro=False, qualified_T2_path=False, formal_release=False)


def register(calibration_reference, *, path=None):
    """Explicitly freeze all eleven candidates after new backend calibration."""
    value = _plan(verify_calibration(calibration_reference))
    path = Path(path) if path is not None else OUT/PLAN_NAME
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("registered material plan changed")
        return value
    atomic_json(path, value)
    return value


def verify_plan(path):
    value = json.loads(Path(path).read_text())
    expected = _plan(verify_calibration(value["calibration"]))
    if value != expected:
        raise ValueError("material plan, seed design, backend hash or thresholds changed")
    if "velocity_interpolator" not in inspect.signature(passive_tracers.advect_hdf5).parameters:
        raise RuntimeError("explicit calibrated interpolator injection is not installed")
    return value


def align_source(source, target, *, step_s=.01):
    """Stream a separate, exact-window same-ID HDF5 with every bracket/alpha."""
    target = Path(target)
    if target.exists():
        raise ValueError("aligned reference already exists")
    original = Path(source["hdf5_path"])
    before = sha256(original)
    if before != source["audit"]["hdf5_sha256"]:
        raise ValueError("source HDF5 changed before alignment")
    times = source_score.target_grid(step_s)
    temporary = target.with_name(target.name+".partial")
    with source_score.CachedSource(source) as cached, h5py.File(temporary, "w") as h:
        n, frames = len(cached.ids), len(times)
        h.attrs.update(schema="f3.material.aligned_reference.v1", source_sha256=before,
                       time_alignment=source_score.TIME_ALIGNMENT, source_case_id=source["case_id"])
        h["time"] = times
        h["particle_id"] = cached.ids
        if "particle_zone" in cached.h5:
            h["particle_zone"] = cached.h5["particle_zone"][:]
        for name in ("position", "velocity"):
            h.create_dataset(name, (frames, n, 3), dtype="f8", chunks=(1, n, 3), compression="lzf")
        for name, dtype in (("mass", "f8"), ("valid", "?"), ("type", "i1")):
            h.create_dataset(name, (frames, n), dtype=dtype, chunks=(1, n), compression="lzf")
        indices = np.empty((frames, 2), dtype=np.int64)
        brackets = np.empty((frames, 2), dtype=float)
        alpha = np.zeros(frames)
        for frame, t in enumerate(times):
            p, v, m, bracket = cached.state(float(t))
            right = int(np.searchsorted(cached.times, t, side="left"))
            left = right if cached.times[right] == t else right-1
            indices[frame] = left, right
            brackets[frame] = bracket
            alpha[frame] = 0. if left == right else (t-cached.times[left])/(cached.times[right]-cached.times[left])
            h["position"][frame], h["velocity"][frame], h["mass"][frame] = p, v, m
            h["valid"][frame], h["type"][frame] = True, 3
        h["native_bracket_indices"] = indices
        h["native_bracket_s"] = brackets
        h["native_alpha"] = alpha
    after = sha256(original)
    if after != before:
        raise ValueError("source HDF5 changed during alignment")
    os.replace(temporary, target)
    return dict(path=str(target.resolve()), sha256=sha256(target), input_path=str(original.resolve()),
                input_sha256_before=before, input_sha256_after=after, step_s=step_s,
                time_window_s=[0., 8.35], target_count=len(times),
                bracket_datasets=["native_bracket_indices", "native_bracket_s", "native_alpha"])


def resource_preflight(timeout_seconds, reserve_bytes):
    """CPU/material/storage pools only; do not consume qualification attempts."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or reserve_bytes < 0:
        raise ValueError("positive finite timeout and output storage reserve required")
    resources.begin_activity_window()
    resources.ledger()
    budget = json.loads((OUT/"RESOURCE-LEDGER.json").read_text())
    limits = resources.resource_limits()
    used = resources.material_usage()
    seconds = timeout_seconds+GRACE_SECONDS+POSTPROCESS_RESERVE_SECONDS
    if used >= limits["materials"]:
        raise RuntimeError("material configuration cap includes failed and incomplete attempts")
    if budget["cpu_core_hours_upper_bound"]+seconds*CPU_ACTIVITY_CORES/3600 > limits["cpu_core_hours"]:
        raise RuntimeError("CPU timeout reserve exceeds the remaining activity budget")
    if datetime.now(timezone.utc)+timedelta(seconds=seconds) > datetime.fromisoformat(budget["conservative_expiry_utc"]):
        raise RuntimeError("material timeout exceeds campaign expiry")
    total = sum(p.stat().st_size for name in ("l1-qualification", "l1-resume")
                for p in (LAB/"campaigns"/name).rglob("*") if p.is_file())
    disk = shutil.disk_usage(LAB)
    if total+reserve_bytes > limits["storage_gib"]*1024**3:
        raise RuntimeError("material output reserve exceeds campaign storage cap")
    if disk.free-reserve_bytes < max(100*1024**3, .1*disk.total):
        raise RuntimeError("material output violates physical disk reserve")
    return dict(material_used=used, cpu_core_hours=budget["cpu_core_hours_upper_bound"],
                cpu_forward_reserve_core_hours=seconds*CPU_ACTIVITY_CORES/3600,
                output_reserve_bytes=reserve_bytes, campaign_storage_bytes=total)


def _worker(payload_path):
    payload = json.loads(Path(payload_path).read_text())
    attempt = json.loads(Path(payload["attempt_record_path"]).read_text())
    if (attempt.get("schema") != ATTEMPT_SCHEMA or attempt.get("status") != "running"
            or attempt.get("configuration_charge") != 1
            or attempt.get("payload_sha256") != sha256(payload_path)
            or attempt.get("controller_pid") != os.getppid()
            or attempt.get("directory") != payload["directory"]
            or attempt.get("configuration") != payload["configuration"]
            or attempt.get("plan", {}).get("sha256") != payload["plan_sha256"]):
        raise ValueError("worker lacks a current charged registration from its controller")
    plan = verify_plan(payload["plan_path"])
    if sha256(payload["plan_path"]) != payload["plan_sha256"]:
        raise ValueError("worker plan differs from charged registration")
    from scripts.f3_material_neighbors import shepard_velocity_with_diagnostics
    cfg, source = payload["configuration"], payload["source"]
    if cfg not in plan["configurations"]:
        raise ValueError("worker configuration is outside the frozen matrix")
    folder = Path(payload["directory"])
    alignment = align_source(source, folder/"aligned.h5", step_s=cfg["output_interval_s"])
    triangles = passive_tracers.box_surface_triangles([-.45, -.09, 0], [.45, .09, .51],
        sides=("xmin", "xmax", "ymin", "ymax", "zmin"))
    trace = passive_tracers.advect_hdf5(alignment["path"], frozen_seeds()["initial_position"],
        neighbours=24, regularization=.004, maximum_support_distance=.03,
        substeps_per_interval=cfg["substeps"], barrier_provider=lambda h, a, b, t: triangles,
        support_gate=dict(SUPPORT), velocity_interpolator=shepard_velocity_with_diagnostics)
    expected_shape = (alignment["target_count"]-1, 512)
    for field in DIAGNOSTICS:
        if field not in trace or np.asarray(trace[field]).shape != expected_shape:
            raise ValueError("tracer omitted complete support/failure diagnostics: "+field)
    if not np.array_equal(trace["time"], source_score.target_grid(cfg["output_interval_s"])):
        raise ValueError("tracer changed the full aligned reference time axis")
    labels = label_trace(trace, frozen_seeds())
    arrays = {key: np.asarray(json.dumps(value, sort_keys=True) if isinstance(value, dict) else value)
              for key, value in labels.items()}
    if any(value.dtype.kind == "O" for value in arrays.values()):
        raise ValueError("material bundle must not require pickle")
    arrays["mass_weight_kg"] = frozen_seeds()["mass_fraction"]*source["audit"]["initial_fluid_mass_kg"]
    arrays["boundary_triangles_m"] = triangles
    artifact = folder/"material.npz"
    with artifact.with_suffix(".npz.partial").open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    os.replace(artifact.with_suffix(".npz.partial"), artifact)
    source_score._verify_bindings(payload["source_evidence_sha256"])
    if code_hashes() != plan["code_sha256"]:
        raise ValueError("material implementation changed during execution")
    result = dict(schema="f3.material.reference_result.v1", status="candidate", alignment=alignment,
                  material=_reference(artifact), source_evidence_sha256=payload["source_evidence_sha256"],
                  initial_fluid_mass_kg=source["audit"]["initial_fluid_mass_kg"],
                  seed_count=512, frame_count=len(trace["time"]), code_sha256=plan["code_sha256"],
                  quadrature_status="pending", matrix_coverage_status="not_evaluated",
                  qualified_T2_macro=False, qualified_T2_path=False,
                  event_semantics="saved-frame linear crossing; observed/valid_no_event/censored; historical observed arrivals survive later failure")
    atomic_json(folder/"result.json", result)


def _run_process(command, folder, timeout_seconds, env, *, on_spawn=None):
    with (folder/"worker.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=LAB, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            if on_spawn is not None:
                on_spawn(process.pid)
            code = process.wait(timeout=timeout_seconds)
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            except ProcessLookupError:
                pass
    if code != 0:
        raise RuntimeError("material worker failed; inspect retained worker.log")


def run_one(config_id, *, timeout_seconds, plan_path=None, retry_of=None):
    """Run one explicit configuration; failures consume a retained configuration."""
    plan_path = Path(plan_path) if plan_path is not None else OUT/PLAN_NAME
    plan = verify_plan(plan_path)
    cfg = next((c for c in plan["configurations"] if c["config_id"] == config_id), None)
    if cfg is None:
        raise ValueError("unknown frozen material configuration")
    qualification.verify_stage_gate(cfg["required_gate"])
    bindings = {}
    source = source_score._source(cfg["plan_case_id"], bindings)
    if any(source["entry"][key] != cfg[key] for key in ("dp_m", "amplitude")):
        raise ValueError("qualified source changed the frozen material dp or amplitude")
    gate_path = OUT/source_score.GATES[cfg["required_gate"]]
    bindings[str(gate_path.relative_to(LAB))] = sha256(gate_path)
    source["hdf5_path"] = str(source["hdf5_path"])
    frames = len(source_score.target_grid(cfg["output_interval_s"]))
    reserve_bytes = int(frames*(source["audit"]["particle_axis_count"]*64+512*256)*1.1)
    taskset = shutil.which("taskset")
    if taskset is None:
        raise RuntimeError("CPU affinity enforcement is unavailable")
    affinity = min(os.sched_getaffinity(0))
    with cpu_slot():
        with (OUT/"material-registration.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            prior = [json.loads(p.read_text()) for p in OUT.glob(f"F3-MATERIAL-REFERENCE-{config_id}-*.json")]
            if any(r.get("status") in ("running", "completed") for r in prior):
                raise RuntimeError("configuration is running or completed; do not automatically relaunch")
            if prior and retry_of not in {r["execution_attempt_id"] for r in prior if r["status"] == "failed"}:
                raise ValueError("failed material configuration requires explicit retry_of")
            if not prior and retry_of is not None:
                raise ValueError("retry_of has no prior material attempt")
            budget = resource_preflight(timeout_seconds, reserve_bytes)
            execution = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-")+uuid.uuid4().hex[:10]
            folder = DATA/execution
            folder.mkdir(parents=True, exist_ok=False)
            record_path = OUT/f"F3-MATERIAL-REFERENCE-{config_id}-{execution}.json"
            payload = dict(plan_path=str(plan_path.resolve()), plan_sha256=sha256(plan_path),
                           configuration=cfg, source=source, source_evidence_sha256=bindings,
                           directory=str(folder.resolve()), attempt_record_path=str(record_path.resolve()))
            atomic_json(folder/"payload.json", payload)
            record = dict(schema=ATTEMPT_SCHEMA, configuration_charge=1, status="running",
                          execution_attempt_id=execution, config_id=config_id, retry_of=retry_of,
                          started_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=None,
                          timeout_seconds=timeout_seconds, cpu_cores=1, cpu_affinity=[affinity],
                          cpu_budget=budget, configuration=cfg, plan=_reference(plan_path),
                          calibration=plan["calibration"], code_sha256=plan["code_sha256"],
                          controller_pid=os.getpid(), payload_sha256=sha256(folder/"payload.json"),
                          directory=str(folder.resolve()), qualified_T2_macro=False, qualified_T2_path=False)
            atomic_json(record_path, record)
        start = time.monotonic()
        try:
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                       CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="void",
                       LAGRANGIAN_TRACER_TORCH_THREADS="1", LAGRANGIAN_TRACER_TORCH_DEVICE="cpu")
            command = [taskset, "--cpu-list", str(affinity), sys.executable, "-m",
                       "scripts.f3_material_reference", "--worker", str(folder/"payload.json")]
            record["command"] = command
            atomic_json(record_path, record)
            def spawned(pid):
                record.update(worker_pid=pid, process_group_id=pid)
                atomic_json(record_path, record)
            _run_process(command, folder, timeout_seconds, env, on_spawn=spawned)
            result = json.loads((folder/"result.json").read_text())
            if result.get("status") != "candidate" or result.get("qualified_T2_macro") is not False or result.get("qualified_T2_path") is not False:
                raise ValueError("worker cannot publish material qualification")
            for ref in (result["material"], result["alignment"]):
                if sha256(ref["path"]) != ref["sha256"]:
                    raise ValueError("material worker output hash mismatch")
            record.update(status="completed", result=_reference(folder/"result.json"))
        except BaseException as error:
            record.update(status="failed", error=repr(error))
            raise
        finally:
            record.update(elapsed_seconds=time.monotonic()-start,
                          finished_at_utc=datetime.now(timezone.utc).isoformat())
            atomic_json(record_path, record)
            resources.ledger()
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    _worker(parser.parse_args().worker)
