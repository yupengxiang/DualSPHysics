#!/usr/bin/env python3
"""Bounded P4 benchmark for the passive-tracer neighbour backend.

The benchmark compares the existing NumPy reference, the current exact CPU
Torch path, and an opt-in exact CUDA top-k prototype.  It uses two saved
windows from an existing plain-control fine trajectory.  CUDA is never the
default tracer device and the result is a performance recommendation only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence

import h5py
import numpy as np

try:
    from scripts import r6_n2_campaign as r6
    from scripts.campaign_runner import query_gpus, require_idle_allowed_gpu
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r6_n2_campaign as r6
    from campaign_runner import query_gpus, require_idle_allowed_gpu


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
INPUT_H5 = CAMPAIGN / "data" / "r6-n2-height" / "R6_F1_plain_dam_break_h11_fine.h5"
SIDECAR_H5 = CAMPAIGN / "sidecars" / "r6-n2-height" / "R6_F1_plain_dam_break_h11_fine.h5"
REPORT = CAMPAIGN / "r6-n3-performance.json"
BENCHMARK_GPU = 4
QUERY_COUNT = 256
NEIGHBOURS = 24
REGULARIZATION_M = 0.0014
WINDOWS = (
    {"label": "interior", "frame": 420},
    {"label": "reflux", "frame": 1120},
)


def relpath(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sync(tracer: Any) -> None:
    torch = getattr(tracer, "torch", None)
    if torch is not None and torch.cuda.is_available():
        requested = os.environ.get("LAGRANGIAN_TRACER_TORCH_DEVICE", "cpu")
        device = torch.device(requested)
        if device.type == "cuda":
            torch.cuda.synchronize(device)


def _load_window(frame: int) -> tuple[dict[str, Any], dict[str, Any]]:
    io_started = time.perf_counter()
    with h5py.File(INPUT_H5, "r") as h5:
        time_axis = np.asarray(h5["time"][:], dtype=np.float64)
        valid = np.asarray(h5["valid"][frame], dtype=bool)
        fluid = valid & (np.asarray(h5["type"][frame], dtype=np.int8) == 3)
        position0 = np.asarray(h5["position"][frame, fluid], dtype=np.float64)
        velocity0 = np.asarray(h5["velocity"][frame, fluid], dtype=np.float64)
        next_valid = np.asarray(h5["valid"][frame + 1], dtype=bool)
        next_fluid = next_valid & (np.asarray(h5["type"][frame + 1], dtype=np.int8) == 3)
        common = fluid & next_fluid
        position1 = np.asarray(h5["position"][frame + 1, common], dtype=np.float64)
        velocity1 = np.asarray(h5["velocity"][frame + 1, common], dtype=np.float64)
    with h5py.File(SIDECAR_H5, "r") as sidecar:
        barriers0 = np.asarray(sidecar["triangles_world"][frame], dtype=np.float64)
        barriers1 = np.asarray(sidecar["triangles_world"][frame + 1], dtype=np.float64)
    # Both frames contain the same numerical fluid identities in this input;
    # use the common prefix only if a future input violates that invariant.
    count = min(len(position0), len(position1), QUERY_COUNT)
    positions = position0[np.linspace(0, len(position0) - 1, count).round().astype(int)]
    query = positions.copy()
    io_seconds = time.perf_counter() - io_started
    return {
        "label": next(item["label"] for item in WINDOWS if item["frame"] == frame),
        "frame": frame,
        "time_s": float(time_axis[frame]),
        "next_time_s": float(time_axis[frame + 1]),
        "query": query,
        "position0": position0[:count],
        "velocity0": velocity0[:count],
        "position1": position1[:count],
        "velocity1": velocity1[:count],
        "barriers0": barriers0,
        "barriers1": barriers1,
        "io_seconds": io_seconds,
        "fluid_count": int(len(position0)),
        "triangle_count": int(len(barriers0)),
    }, {"h5_sha256": sha256(INPUT_H5), "sidecar_sha256": sha256(SIDECAR_H5)}


def _integrate(tracer: Any, window: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    query = np.asarray(window["query"], dtype=np.float64)
    position0 = np.asarray(window["position0"], dtype=np.float64)
    velocity0 = np.asarray(window["velocity0"], dtype=np.float64)
    position1 = np.asarray(window["position1"], dtype=np.float64)
    velocity1 = np.asarray(window["velocity1"], dtype=np.float64)
    dt = float(window["next_time_s"] - window["time_s"])
    no_wall_started = time.perf_counter()
    v0, _, _, metrics0 = tracer.shepard_velocity_with_diagnostics(
        query, position0, velocity0, neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_M, barrier_triangles=None,
    )
    _sync(tracer)
    neighbour_seconds = time.perf_counter() - no_wall_started
    predicted = query + np.nan_to_num(v0) * dt
    wall_started = time.perf_counter()
    crossing = tracer.spacetime_swept_wall_blocked(
        query, predicted, window["barriers0"], window["barriers1"],
    )
    wall_seconds = time.perf_counter() - wall_started
    integration_started = time.perf_counter()
    v0, _, _, metrics0 = tracer.shepard_velocity_with_diagnostics(
        query, position0, velocity0, neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_M, barrier_triangles=None,
    )
    predicted = query + np.nan_to_num(v0) * dt
    v1, _, _, metrics1 = tracer.shepard_velocity_with_diagnostics(
        predicted, position1, velocity1, neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_M, barrier_triangles=None,
    )
    candidate = query + 0.5 * np.nan_to_num(v0 + v1) * dt
    crossing = tracer.spacetime_swept_wall_blocked(
        query, candidate, window["barriers0"], window["barriers1"],
    )
    _sync(tracer)
    integration_seconds = time.perf_counter() - integration_started
    output_started = time.perf_counter()
    output_payload = {
        "position": candidate.tolist(),
        "velocity": np.asarray(v0).tolist(),
        "crossing": np.asarray(crossing).tolist(),
    }
    json.dumps(output_payload, separators=(",", ":"))
    output_seconds = time.perf_counter() - output_started
    result = {
        "label": window["label"],
        "query_count": int(len(query)),
        "fluid_count": int(window["fluid_count"]),
        "triangle_count": int(window["triangle_count"]),
        "time_s": window["time_s"],
        "next_time_s": window["next_time_s"],
        "visible_crossings": int(np.sum(crossing)),
        "finite_velocity_fraction": float(np.mean(np.all(np.isfinite(v0), axis=1))),
        "candidate_position": candidate.tolist(),
        "interpolated_velocity": np.asarray(v0).tolist(),
        "support_distance_max_m": float(np.nanmax(metrics0["support_distance"])),
        "visibility_mode": metrics0.get("visibility_mode"),
    }
    phases = {
        "io_seconds": float(window["io_seconds"]),
        "neighbour_probe_seconds": float(neighbour_seconds),
        "wall_probe_seconds": float(wall_seconds),
        "integration_seconds": float(integration_seconds),
        "output_seconds": float(output_seconds),
        "end_to_end_seconds": float(window["io_seconds"] + integration_seconds + output_seconds),
    }
    return result, phases


def run_backend(backend: str, device: str) -> dict[str, Any]:
    os.environ["LAGRANGIAN_TRACER_TORCH_DEVICE"] = device
    from scripts import passive_tracers as tracer
    if backend == "numpy":
        tracer.torch = None
        tracer._TORCH_NEIGHBOUR_CONFIGURED = True
        tracer._TORCH_NEIGHBOUR_DEVICE = None
    elif backend == "cuda":
        if tracer.torch is None or not tracer.torch.cuda.is_available():
            raise RuntimeError("Torch CUDA is unavailable")
    windows = []
    for spec in WINDOWS:
        window, hashes = _load_window(spec["frame"])
        warmup_query = window["query"][: min(8, len(window["query"]))]
        tracer.shepard_velocity_with_diagnostics(
            warmup_query, window["position0"], window["velocity0"],
            neighbours=NEIGHBOURS, regularization=REGULARIZATION_M,
        )
        _sync(tracer)
        warmup_seconds = 0.0
        started = time.perf_counter()
        tracer.shepard_velocity_with_diagnostics(
            warmup_query, window["position0"], window["velocity0"],
            neighbours=NEIGHBOURS, regularization=REGULARIZATION_M,
        )
        _sync(tracer)
        warmup_seconds = time.perf_counter() - started
        result, phases = _integrate(tracer, window)
        result["warmup_seconds"] = float(warmup_seconds)
        result["phases"] = phases
        result["input_hashes"] = hashes
        windows.append(result)
    device_info = {"requested": device, "backend": backend}
    if getattr(tracer, "torch", None) is not None:
        device_info["torch_version"] = str(tracer.torch.__version__)
        if tracer.torch.cuda.is_available():
            selected = tracer.torch.device(device)
            device_info["resolved_device"] = str(selected)
            if selected.type == "cuda":
                device_info["device_name"] = tracer.torch.cuda.get_device_name(selected)
    return {
        "backend": backend,
        "device": device_info,
        "windows": windows,
        "status": "completed",
    }


def _child_main(backend: str, device: str) -> int:
    try:
        print(json.dumps(run_backend(backend, device), ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"backend": backend, "status": "failed", "error": repr(error)}), flush=True)
        return 1


def _compare(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for left, right in zip(reference.get("windows", []), candidate.get("windows", [])):
        left_position = np.asarray(left["candidate_position"], dtype=np.float64)
        right_position = np.asarray(right["candidate_position"], dtype=np.float64)
        left_velocity = np.asarray(left["interpolated_velocity"], dtype=np.float64)
        right_velocity = np.asarray(right["interpolated_velocity"], dtype=np.float64)
        rows.append({
            "label": left.get("label", right.get("label")),
            "candidate_position_max_abs_delta_m": float(np.nanmax(np.abs(left_position - right_position))),
            "interpolated_velocity_max_abs_delta_mps": float(np.nanmax(np.abs(left_velocity - right_velocity))),
        })
    return {
        "windows": rows,
        "max_position_delta_m": max((item["candidate_position_max_abs_delta_m"] for item in rows), default=None),
        "max_velocity_delta_mps": max((item["interpolated_velocity_max_abs_delta_mps"] for item in rows), default=None),
        "status": "diagnostic_parity_only",
    }


def benchmark_all() -> dict[str, Any]:
    started = time.perf_counter()
    preflight = query_gpus()
    allowed = r6.allowed_uuids()
    gpu_guard = require_idle_allowed_gpu(BENCHMARK_GPU, allowed)
    backends = []
    for backend, device in (("numpy", "cpu"), ("cpu_torch", "cpu"), ("cuda", f"cuda:{BENCHMARK_GPU}")):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(LAB)
        env["LAGRANGIAN_TRACER_TORCH_DEVICE"] = device
        command = [sys.executable, str(Path(__file__).resolve()), "--child", "--backend", backend, "--device", device]
        process = subprocess.run(command, cwd=LAB, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        parsed = None
        for line in reversed(process.stdout.splitlines()):
            try:
                candidate = json.loads(line)
                if candidate.get("backend") == backend:
                    parsed = candidate
                    break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            parsed = {"backend": backend, "status": "failed", "returncode": process.returncode, "output_tail": process.stdout[-3000:]}
        parsed["returncode"] = process.returncode
        backends.append(parsed)
    by_backend = {item.get("backend"): item for item in backends}
    reference = by_backend.get("numpy", {})
    cpu = by_backend.get("cpu_torch", {})
    cuda = by_backend.get("cuda", {})
    def medians(item: dict[str, Any]) -> dict[str, float | None]:
        values = [float(window.get("phases", {}).get("end_to_end_seconds")) for window in item.get("windows", []) if window.get("phases", {}).get("end_to_end_seconds") is not None]
        return {"end_to_end_median_seconds": float(np.median(values)) if values else None}
    numpy_time = medians(reference)["end_to_end_median_seconds"]
    cpu_time = medians(cpu)["end_to_end_median_seconds"]
    cuda_time = medians(cuda)["end_to_end_median_seconds"]
    speedups = {
        "cpu_torch_vs_numpy": numpy_time / cpu_time if numpy_time and cpu_time else None,
        "cuda_vs_numpy": numpy_time / cuda_time if numpy_time and cuda_time else None,
        "cuda_vs_cpu_torch": cpu_time / cuda_time if cpu_time and cuda_time else None,
    }
    parity = _compare(reference, cuda) if cuda.get("status") == "completed" else {"status": "unavailable"}
    position_delta = parity.get("max_position_delta_m")
    velocity_delta = parity.get("max_velocity_delta_mps")
    cuda_gate = bool(
        cuda.get("status") == "completed"
        and speedups.get("cuda_vs_cpu_torch") is not None
        and speedups["cuda_vs_cpu_torch"] >= 2.0
        and position_delta is not None and position_delta <= 1.0e-9
        and velocity_delta is not None and velocity_delta <= 1.0e-8
    )
    payload = {
        "schema_version": "r6-n3-p4-performance-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_status": "completed" if all(item.get("status") == "completed" for item in backends) else "completed_with_findings",
        "scope": "two saved windows; exact no-barrier top-k probe plus unchanged finite-wall sweep",
        "input": {"hdf5": relpath(INPUT_H5), "sidecar": relpath(SIDECAR_H5), "hdf5_sha256": sha256(INPUT_H5), "sidecar_sha256": sha256(SIDECAR_H5)},
        "preflight_gpu": gpu_guard,
        "resource_snapshot_before": preflight,
        "resource_snapshot_after": query_gpus(),
        "controls": {
            "query_count": QUERY_COUNT,
            "neighbours": NEIGHBOURS,
            "regularization_m": REGULARIZATION_M,
            "transfer_included_in_torch_call": True,
            "cuda_synchronization": "before_and_after_each_cuda_call",
            "wall_path": "NumPy spacetime_swept_wall_blocked; unchanged across backends",
            "cache_policy": "normal filesystem/OS cache; no destructive cache flush",
            "production_switch": "not performed by benchmark",
        },
        "backends": backends,
        "median_end_to_end_seconds": {name: medians(item)["end_to_end_median_seconds"] for name, item in by_backend.items()},
        "speedups": speedups,
        "cuda_parity": parity,
        "decision": {
            "two_x_end_to_end_gate": cuda_gate,
            "status": "candidate_cuda_not_admitted" if not cuda_gate else "candidate_cuda_passes_bounded_gate_but_requires_long_window_retest",
            "reason": "production tracer remains on the existing CPU path unless an end-to-end >=2x gain and exact parity are demonstrated",
        },
        "elapsed_seconds": time.perf_counter() - started,
    }
    REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--backend", choices=("numpy", "cpu_torch", "cuda"), default="numpy")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    if args.child:
        return _child_main(args.backend, args.device)
    payload = benchmark_all()
    print(json.dumps({
        "execution_status": payload["execution_status"],
        "speedups": payload["speedups"],
        "cuda_gate": payload["decision"]["two_x_end_to_end_gate"],
        "report": relpath(REPORT),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
