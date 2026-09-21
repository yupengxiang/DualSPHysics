#!/usr/bin/env python3
"""Run the registered 20-step canary with an explicit float64 model path.

This is an independent diagnostic entrypoint for isolating arithmetic effects
between CUDA hosts.  The public dataset reader, feature builder, complete
field neighbor table, two-hop halo, checkpoint values, dual increment update,
and known-force prior are the same as the frozen float32 canary.  Only the
inference tensors and model parameters are promoted to ``torch.float64``.

The source node features are intentionally recorded as ``float32`` because
that is the versioned public feature contract in ``core_models.py``.  They are
promoted without changing their values before normalization and model
evaluation.  This keeps the diagnostic about model arithmetic rather than
silently changing the feature definition.  The checkpoint is never rewritten.

The result is a bounded numerical diagnostic.  It is not a formal training
run, a replacement for the default float32 bundle, or an 835-frame
cross-host reproduction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any

import numpy as np
import torch


SCHEMA = "core.cross_host_canary.float64.v1"
PROGRESS_SCHEMA = "core.cross_host_canary.float64.progress.v1"
MODEL_KIND = "graph_residual"
EXPECTED_HIDDEN = 64
EXPECTED_SEED = 17
EXPECTED_UPDATE = 500
EXPECTED_CHUNK_SIZE = 256
EXPECTED_MAX_STEPS = 20
EXPECTED_MANIFEST_SHA256 = "8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680"
EXPECTED_CHECKPOINT_SHA256 = "9af1dc3cb68991c38fd31b59d92895326e3abe89d5d29d33dd086d7fa462b8a8"
EXPECTED_MODELS_SHA256 = "73a98b262500c30e46f14aafd2a89f2bea34116c77b6e34ce5e33e7412c38c77"
POSITION_ATOL_M = 1.0e-5
VELOCITY_ATOL_MPS = 1.0e-4
RELATIVE_TOLERANCE = 1.0e-4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_stats(array: np.ndarray) -> dict[str, Any]:
    array = np.asarray(array)
    if array.size == 0:
        return {"finite": True, "min": None, "max": None, "mean": None,
                "rms": None, "max_abs": None}
    finite = bool(np.isfinite(array).all()) if array.dtype.kind in "fc" else True
    if not finite:
        return {"finite": False, "min": None, "max": None, "mean": None,
                "rms": None, "max_abs": None}
    values = np.asarray(array, dtype=np.float64)
    return {
        "finite": True,
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "rms": float(np.sqrt(np.mean(values * values))),
        "max_abs": float(np.max(np.abs(values))),
    }


def array_digest(value: Any) -> dict[str, Any]:
    array = np.ascontiguousarray(np.asarray(value))
    return {
        "sha256": hashlib.sha256(array.view(np.uint8)).hexdigest(),
        "dtype": str(array.dtype),
        "shape": [int(item) for item in array.shape],
        **_finite_stats(array),
    }


def tensor_digest(value: torch.Tensor) -> dict[str, Any]:
    return array_digest(value.detach().to(device="cpu").contiguous().numpy())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    allow_nan=False) + "\n")
    os.replace(temporary, path)


def atomic_trajectory_arrays(path: Path, *, positions: list[np.ndarray],
                             velocities: list[np.ndarray], times: list[float]) -> dict[str, Any]:
    """Persist exact state arrays for an independent comparator.

    JSON remains a bounded receipt of digests and metadata.  The actual
    position/velocity arrays are stored in a compressed NPZ sidecar so a
    comparator can compute element-wise tolerances without treating a digest
    as a numerical error bound.  A partial sidecar is also valid on failure
    and records the frames that were actually executed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not positions or len(positions) != len(velocities) or len(positions) != len(times):
        raise ValueError("trajectory arrays must have equal nonempty frame axes")
    position_array = np.ascontiguousarray(np.stack(positions, axis=0), dtype=np.float64)
    velocity_array = np.ascontiguousarray(np.stack(velocities, axis=0), dtype=np.float64)
    time_array = np.ascontiguousarray(np.asarray(times, dtype=np.float64))
    temporary = path.with_name(path.name + ".tmp")
    generated = temporary.with_suffix(temporary.suffix + ".npz")
    np.savez_compressed(temporary, position=position_array,
                        velocity=velocity_array, time_s=time_array)
    if not generated.exists():
        generated = temporary
    os.replace(generated, path)
    if temporary.exists():
        temporary.unlink()
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "frames": int(position_array.shape[0]),
        "particle_count": int(position_array.shape[1]),
        "position_shape": [int(item) for item in position_array.shape],
        "velocity_shape": [int(item) for item in velocity_array.shape],
        "dtype": "float64",
        "keys": ["position", "velocity", "time_s"],
    }


def _module_identity(module: Any) -> dict[str, Any]:
    path = Path(module.__file__).resolve()
    return {"module": str(module.__name__), "path": str(path),
            "sha256": sha256_file(path)}


def _driver_query(device_index: int | None) -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"available": False, "error": "nvidia-smi not found"}
    command = [executable, "--query-gpu=driver_version,name,uuid",
               "--format=csv,noheader,nounits"]
    selector = os.environ.get("CUDA_VISIBLE_DEVICES")
    if selector and "," not in selector:
        command.extend(("-i", selector))
    elif device_index is not None:
        command.extend(("-i", str(int(device_index))))
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=10, check=False)
    except Exception as error:  # pragma: no cover - host utility
        return {"available": False, "error": f"{type(error).__name__}: {error}"}
    return {"available": completed.returncode == 0,
            "returncode": int(completed.returncode),
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip()}


def capture_environment(*, device: str, deterministic_requested: bool,
                        imported_modules: list[dict[str, Any]]) -> dict[str, Any]:
    """Capture facts before constructing the CUDA model."""
    result: dict[str, Any] = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "requested_device": str(device),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "deterministic_requested": bool(deterministic_requested),
        "deterministic_algorithms_enabled": bool(torch.are_deterministic_algorithms_enabled()),
        "deterministic_warn_only": bool(torch.is_deterministic_algorithms_warn_only_enabled()),
        "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
        "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "torch_tf32_matmul": getattr(torch.backends.cuda.matmul, "allow_tf32", None),
        "torch_tf32_cudnn": getattr(torch.backends.cudnn, "allow_tf32", None),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()),
        "modules_before_model": imported_modules,
    }
    device_index: int | None = None
    if result["cuda_available"]:
        try:
            requested = torch.device(device)
            device_index = (int(requested.index) if requested.index is not None
                            else int(torch.cuda.current_device()))
            properties = torch.cuda.get_device_properties(device_index)
            result["cuda"] = {
                "current_device": int(torch.cuda.current_device()),
                "device_index": device_index,
                "device_name": torch.cuda.get_device_name(device_index),
                "device_capability": [int(item) for item in torch.cuda.get_device_capability(device_index)],
                "total_memory_bytes": int(properties.total_memory),
                "multi_processor_count": int(properties.multi_processor_count),
                "major": int(properties.major),
                "minor": int(properties.minor),
                "arch_list": list(torch.cuda.get_arch_list()),
            }
        except Exception as error:  # pragma: no cover - host utility
            result["cuda_error"] = f"{type(error).__name__}: {error}"
    result["driver_query"] = _driver_query(device_index)
    return result


def _load_bundle_modules(bundle_root: Path) -> dict[str, Any]:
    code_root = (Path(bundle_root) / "code").resolve()
    if not (code_root / "scripts" / "core_models.py").is_file():
        raise FileNotFoundError(f"bundle code is missing: {code_root}")
    existing = sys.modules.get("scripts")
    if existing is not None:
        existing_path = getattr(existing, "__file__", None)
        if existing_path is not None and code_root not in Path(existing_path).resolve().parents:
            raise RuntimeError("run this canary as a direct script so the bundle scripts package is resolved")
    sys.path.insert(0, str(code_root))
    import importlib
    return {name: importlib.import_module(f"scripts.{name}")
            for name in ("core_contract", "core_dataset", "core_models")}


def _fixed_identity(bundle_root: Path, modules: dict[str, Any], *,
                    manifest_sha256: str, checkpoint_sha256: str,
                    models_sha256: str, checkpoint: Path) -> dict[str, Any]:
    manifest = (bundle_root / "dataset.json").resolve()
    checkpoint = Path(checkpoint).resolve()
    canonical_checkpoint = (bundle_root / "models" / "checkpoint-001.pt").resolve()
    if checkpoint != canonical_checkpoint:
        raise ValueError("float64 canary checkpoint is fixed to bundle/models/checkpoint-001.pt")
    models_path = Path(modules["core_models"].__file__).resolve()
    observed = {
        "manifest": {"path": str(manifest), "sha256": sha256_file(manifest)},
        "checkpoint": {"path": str(checkpoint), "sha256": sha256_file(checkpoint)},
        "core_models": {"path": str(models_path), "sha256": sha256_file(models_path)},
    }
    expected = {"manifest": manifest_sha256, "checkpoint": checkpoint_sha256,
                "core_models": models_sha256}
    mismatches = [f"{key}: expected {expected[key]}, observed {observed[key]['sha256']}"
                  for key in expected if expected[key] and expected[key] != observed[key]["sha256"]]
    if mismatches:
        raise ValueError("fixed reproduction identity mismatch: " + "; ".join(mismatches))
    return {"expected": expected, "observed": observed}


def _configure_determinism(requested: bool) -> None:
    if not requested:
        return
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def dtype_contract(inference_dtype: str) -> dict[str, Any]:
    if inference_dtype not in ("float32", "float64"):
        raise ValueError("inference_dtype must be float32 or float64")
    return {
        "variant": "float64_inference" if inference_dtype == "float64" else "float32_regression",
        "feature_construction_dtype": "float32 (core_models.node_features public contract)",
        "feature_promotion": inference_dtype == "float64",
        "model_input_dtype": inference_dtype,
        "parameter_compute_dtype": inference_dtype,
        "normalization_dtype": inference_dtype,
        "position_tensor_dtype": inference_dtype,
        "prior_tensor_dtype": inference_dtype,
        "neighbor_index_dtype": "int64",
        "output_dtype": "float64 numpy SI arrays",
        "checkpoint_values": "loaded from immutable checkpoint then promoted; checkpoint bytes unchanged",
        "default_float32_path": "core_cross_host_canary.py remains frozen float32",
    }


def _torch_dtype(name: str) -> torch.dtype:
    if name == "float32":
        return torch.float32
    if name == "float64":
        return torch.float64
    raise ValueError(f"unsupported inference dtype: {name}")


def build_inference_inputs(*, state: Any, known: Any, dt: float,
                           core_models: Any, device: torch.device,
                           inference_dtype: str) -> tuple[tuple[Any, ...], torch.Tensor, dict[str, Any]]:
    """Build complete-field inputs without changing public feature values."""
    dtype = _torch_dtype(inference_dtype)
    source_features, acceleration = core_models.node_features(state, known, dt)
    # node_features is registered as float32.  asarray here is an exact
    # promotion of those public values, not a new feature construction path.
    features = torch.as_tensor(source_features, dtype=dtype, device=device)
    neighbors, diagnostics = core_models.neighbor_table(state, float(known.numerics["h_m"]))
    # State arrays are intentionally read-only.  torch.tensor makes the same
    # value-preserving copy as the frozen float32 adapter and avoids exposing
    # a non-writable NumPy buffer to a CUDA/CPU tensor.
    position = torch.tensor(np.asarray(state.position), dtype=dtype, device=device)
    neighbor_tensor = torch.as_tensor(neighbors, dtype=torch.long, device=device)
    prior_np = np.column_stack((
        state.velocity * dt + 0.5 * acceleration * dt * dt,
        acceleration * dt,
    ))
    prior = torch.as_tensor(prior_np, dtype=dtype, device=device)
    args = (features, position, neighbor_tensor, float(known.numerics["h_m"]))
    metadata = {
        "source_features": array_digest(source_features),
        "promoted_features": tensor_digest(features),
        "positions": tensor_digest(position),
        "neighbors": array_digest(neighbors),
        "prior": tensor_digest(prior),
        "neighbor_diagnostics": diagnostics,
        "feature_source_dtype": str(np.asarray(source_features).dtype),
        "tensor_dtype": str(features.dtype).replace("torch.", ""),
    }
    return args, prior, metadata


def _check_model_dtype(model: Any, expected: torch.dtype) -> None:
    dtypes = {parameter.dtype for parameter in model.parameters()}
    dtypes.update(buffer.dtype for buffer in model.buffers()
                  if torch.is_floating_point(buffer))
    if dtypes != {expected}:
        observed = ",".join(sorted(str(dtype) for dtype in dtypes))
        raise ValueError(f"model dtype mismatch: expected {expected}, observed {observed}")


def predict_step(*, state: Any, known: Any, dt: float, model: Any,
                 normalization: Any, device: torch.device, chunk_size: int,
                 core_models: Any, inference_dtype: str = "float64") -> tuple[Any, dict[str, Any]]:
    """Predict one full-field step using the requested explicit dtype.

    The returned ``StepPrediction`` has native SI displacement and velocity
    increments.  For the residual model the same SI known-force prior is added
    after target denormalization, exactly as in the frozen float32 path.
    """
    if int(chunk_size) < 1:
        raise ValueError("positive chunk size required")
    dtype = _torch_dtype(inference_dtype)
    _check_model_dtype(model, dtype)
    args, prior, metadata = build_inference_inputs(
        state=state, known=known, dt=dt, core_models=core_models,
        device=device, inference_dtype=inference_dtype,
    )
    if normalization is not None:
        args = (normalization.normalize_features(args[0]), *args[1:])
        metadata["normalized_features"] = tensor_digest(args[0])
    output = np.empty((state.count, core_models.OUTPUT_DIM), dtype=np.float64)
    chunks: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, state.count, int(chunk_size)):
            stop = min(start + int(chunk_size), state.count)
            centers = torch.arange(start, stop, device=device)
            result = model(*args, centers=centers)
            normalized_result = result
            if normalization is not None:
                result = normalization.denormalize_target(result)
            if model.kind == "graph_residual":
                result = result + prior[start:stop]
            if not torch.isfinite(result).all():
                raise FloatingPointError("nonfinite model prediction")
            output[start:stop] = result.detach().to(device="cpu").numpy()
            chunks.append({
                "start": int(start),
                "stop": int(stop),
                "normalized_output": tensor_digest(normalized_result),
                "decoded_output": array_digest(output[start:stop]),
            })
    return core_models.StepPrediction(output[:, :3], output[:, 3:], metadata), {
        "inputs": metadata,
        "chunks": chunks,
    }


def _state_trace(state: Any) -> dict[str, Any]:
    return {"time_s": float(state.time_s),
            "position": array_digest(state.position),
            "velocity": array_digest(state.velocity)}


def _progress_payload(*, case_id: str, expected_steps: int, completed_steps: int,
                      output: Path, started: float, status: str,
                      error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": PROGRESS_SCHEMA,
        "case_id": case_id,
        "expected_steps": int(expected_steps),
        "completed_steps": int(completed_steps),
        "status": status,
        "elapsed_seconds": float(time.perf_counter() - started),
        "output": str(output),
    }
    if error is not None:
        payload["error"] = error
    return payload


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    arrays_output = (Path(args.arrays_output).expanduser().resolve()
                     if args.arrays_output else output.with_suffix(".npz"))
    progress = (Path(args.progress_output).expanduser().resolve()
                if args.progress_output else output.with_name(output.stem + "-progress.json"))
    started = time.perf_counter()
    expected_steps = min(int(args.maximum_steps), EXPECTED_MAX_STEPS)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "started",
        "variant": "float64_inference",
        "case_id": args.case_id,
        "model_kind": args.model_kind,
        "maximum_steps": expected_steps,
        "expected_frames": expected_steps + 1,
        "chunk_size": int(args.chunk_size),
        "inference_dtype": args.inference_dtype,
        "dtype_contract": dtype_contract(args.inference_dtype),
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "identity_time_mass_valid": "exact",
            "position_absolute_tolerance_m": POSITION_ATOL_M,
            "velocity_absolute_tolerance_mps": VELOCITY_ATOL_MPS,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "tolerances_frozen": True,
        },
        "diagnostic_scope": {
            "formal_training": False,
            "formal_evaluation": False,
            "full_835_frame_reproduction": False,
            "description": "bounded 20-step arithmetic isolation only",
        },
        "trajectory_arrays_output": str(arrays_output),
        "events": [],
        "steps": [],
    }
    trajectory_positions: list[np.ndarray] = []
    trajectory_velocities: list[np.ndarray] = []
    trajectory_times: list[float] = []
    atomic_json(progress, _progress_payload(case_id=args.case_id,
                                            expected_steps=expected_steps,
                                            completed_steps=0, output=output,
                                            started=started, status="starting"))
    try:
        if expected_steps < 1 or int(args.maximum_steps) != expected_steps:
            raise ValueError(f"canary maximum_steps must be in [1,{EXPECTED_MAX_STEPS}]")
        if int(args.chunk_size) != EXPECTED_CHUNK_SIZE:
            raise ValueError(f"canary chunk_size is fixed at {EXPECTED_CHUNK_SIZE}")
        if args.model_kind != MODEL_KIND:
            raise ValueError(f"canary model_kind is fixed at {MODEL_KIND}")
        if args.inference_dtype != "float64":
            raise ValueError("the scheduled variant is fixed to float64")
        _configure_determinism(bool(args.deterministic))
        bundle_root = Path(args.bundle_root).expanduser().resolve()
        checkpoint = (Path(args.checkpoint).expanduser().resolve()
                      if args.checkpoint else (bundle_root / "models" / "checkpoint-001.pt").resolve())
        modules = _load_bundle_modules(bundle_root)
        imported = [_module_identity(modules[name]) for name in sorted(modules)]
        environment = capture_environment(
            device=args.device, deterministic_requested=bool(args.deterministic),
            imported_modules=imported,
        )
        result["environment"] = environment
        result["events"].append("environment_captured_before_model_construction")
        identity = _fixed_identity(
            bundle_root, modules,
            manifest_sha256=args.expected_manifest_sha256,
            checkpoint_sha256=args.expected_checkpoint_sha256,
            models_sha256=args.expected_models_sha256,
            checkpoint=checkpoint,
        )
        result["bundle"] = {"root": str(bundle_root), "identity": identity,
                            "variant_runner": {"path": str(Path(__file__).resolve()),
                                               "sha256": sha256_file(Path(__file__))},
                            "default_runner": {"path": str(Path(__file__).with_name("core_cross_host_canary.py").resolve()),
                                                "sha256": sha256_file(Path(__file__).with_name("core_cross_host_canary.py"))}}
        if not environment.get("cuda_available") and str(args.device).startswith("cuda"):
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
        manifest = bundle_root / "dataset.json"
        dataset = modules["core_dataset"].CoreDataset(manifest, bundle_root, max_open_files=2)
        record = dataset.record(args.case_id)
        times = dataset.times(args.case_id)
        if expected_steps >= len(times):
            raise ValueError(f"case has only {len(times) - 1} transitions")
        known = dataset.known_inputs(args.case_id)
        result["case"] = {
            "physical_case_id": record["physical_case_id"],
            "lineage_group_id": record["lineage_group_id"],
            "family": record["family"],
            "split": record["split"],
            "hdf5": record["hdf5"],
            "hdf5_sha256_declared": record["sha256"],
            "known_inputs_sha256": record["known_inputs_sha256"],
        }
        initial = dataset.read_state(args.case_id, 0)
        result["events"].append("initial_state_read_only")
        result["initial_state"] = _state_trace(initial)
        trajectory_positions.append(np.array(initial.position, dtype=np.float64, copy=True))
        trajectory_velocities.append(np.array(initial.velocity, dtype=np.float64, copy=True))
        trajectory_times.append(float(initial.time_s))
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if payload.get("model_kind") != MODEL_KIND or int(payload.get("hidden", -1)) != EXPECTED_HIDDEN:
            raise ValueError("checkpoint model identity is not the registered graph_residual hidden64 model")
        if int(payload.get("seed", -1)) != EXPECTED_SEED or int(payload.get("update", -1)) != EXPECTED_UPDATE:
            raise ValueError("checkpoint seed/update does not match the registered canary")
        normalization = modules["core_models"].Normalization.from_dict(payload["normalization"])
        model = modules["core_models"].DualIncrementModel(MODEL_KIND, hidden=EXPECTED_HIDDEN)
        model.load_state_dict(payload.get("model_state", payload["state_dict"]))
        checkpoint_dtypes = {name: str(value.dtype)
                             for name, value in model.state_dict().items()}
        result["checkpoint_parameter_dtypes_before_promotion"] = checkpoint_dtypes
        model.eval()
        result["events"].append("cpu_model_constructed_after_environment_capture")
        device = torch.device(args.device)
        model = model.to(device)
        model = model.to(dtype=torch.float64)
        _check_model_dtype(model, torch.float64)
        result["events"].append(
            "cuda_float64_model_constructed_after_environment_capture"
            if device.type == "cuda" else "cpu_float64_model_moved_after_environment_capture"
        )
        result["model_parameter_dtype_after_promotion"] = "float64"
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        current = initial
        for step in range(expected_steps):
            dt = float(times[step + 1] - times[step])
            prediction, trace = predict_step(
                state=current, known=known, dt=dt, model=model,
                normalization=normalization, device=device,
                chunk_size=int(args.chunk_size), core_models=modules["core_models"],
                inference_dtype=args.inference_dtype,
            )
            if not (np.isfinite(prediction.displacement).all()
                    and np.isfinite(prediction.delta_velocity).all()):
                raise FloatingPointError(f"nonfinite prediction at step {step}")
            next_state = modules["core_contract"].apply_prediction(current, prediction, dt)
            result["steps"].append({
                "step": int(step),
                "frame": int(step + 1),
                "dt_s": dt,
                "state_before": _state_trace(current),
                "trace": trace,
                "prediction": {
                    "displacement": array_digest(prediction.displacement),
                    "delta_velocity": array_digest(prediction.delta_velocity),
                },
                "state_after": _state_trace(next_state),
            })
            trajectory_positions.append(np.array(next_state.position, dtype=np.float64, copy=True))
            trajectory_velocities.append(np.array(next_state.velocity, dtype=np.float64, copy=True))
            trajectory_times.append(float(next_state.time_s))
            current = next_state
            completed = step + 1
            if completed % int(args.progress_every) == 0 or completed == expected_steps:
                atomic_json(progress, _progress_payload(
                    case_id=args.case_id, expected_steps=expected_steps,
                    completed_steps=completed, output=output, started=started,
                    status="running" if completed < expected_steps else "complete"))
        result["status"] = "complete"
        result["completed_steps"] = expected_steps
        result["read_log"] = [[str(case), int(frame)] for case, frame in dataset.read_log]
        if any(frame != 0 for _, frame in dataset.read_log):
            raise AssertionError("diagnostic read a future fluid state")
        result["autonomous"] = True
        result["future_state_inputs"] = False
        result["trajectory_arrays"] = atomic_trajectory_arrays(
            arrays_output, positions=trajectory_positions,
            velocities=trajectory_velocities, times=trajectory_times)
        if device.type == "cuda":
            result["resource"] = {
                "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
            }
    except Exception as error:
        result["status"] = "failed"
        result["completed_steps"] = len(result.get("steps", []))
        if trajectory_positions:
            try:
                result["trajectory_arrays"] = atomic_trajectory_arrays(
                    arrays_output, positions=trajectory_positions,
                    velocities=trajectory_velocities, times=trajectory_times)
            except Exception as array_error:  # pragma: no cover - disk failure
                result["trajectory_arrays_error"] = f"{type(array_error).__name__}: {array_error}"
        result["error"] = {"type": type(error).__name__, "message": str(error),
                            "traceback": traceback.format_exc()}
        atomic_json(progress, _progress_payload(
            case_id=args.case_id, expected_steps=expected_steps,
            completed_steps=len(result.get("steps", [])), output=output,
            started=started, status="failed",
            error=f"{type(error).__name__}: {error}"))
        atomic_json(output, result)
        return 1
    result["elapsed_seconds"] = float(time.perf_counter() - started)
    atomic_json(output, result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--chunk-size", type=int, default=EXPECTED_CHUNK_SIZE)
    parser.add_argument("--maximum-steps", "--max-steps", type=int, default=EXPECTED_MAX_STEPS)
    parser.add_argument("--model-kind", default=MODEL_KIND)
    parser.add_argument("--inference-dtype", choices=("float64", "float32"), default="float64")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--arrays-output", type=Path,
                        help="compressed NPZ sidecar containing exact state arrays")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", default=EXPECTED_MANIFEST_SHA256)
    parser.add_argument("--expected-checkpoint-sha256", default=EXPECTED_CHECKPOINT_SHA256)
    parser.add_argument("--expected-models-sha256", default=EXPECTED_MODELS_SHA256)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.checkpoint is not None:
        expected = (Path(args.bundle_root).resolve() / "models" / "checkpoint-001.pt").resolve()
        if Path(args.checkpoint).resolve() != expected:
            raise SystemExit("the canary checkpoint is fixed to bundle/models/checkpoint-001.pt")
    if int(args.progress_every) < 1:
        raise SystemExit("--progress-every must be positive")
    return run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
