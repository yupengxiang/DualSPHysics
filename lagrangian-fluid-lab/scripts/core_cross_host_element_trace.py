#!/usr/bin/env python3
"""Collect a bounded, versioned element trace for the cross-host canary.

This is an independent diagnostic entrypoint.  It follows the same public
causal update as ``core_cross_host_canary.py`` but writes a compact JSON
manifest plus a compressed ``.npz`` sidecar instead of changing the frozen
canary or reproduction bundle.  The sidecar contains all predicted native
position/velocity frames and first-chunk graph values.  Message tensors are
stored only for valid edges; the corresponding destination, source and slot
indices remain explicit so a comparator can calculate element errors without
guessing an ordering.

The entrypoint never reads a future CFD state.  It reads frame zero once,
then advances the public updater with the model prediction.  It is a bounded
20-step diagnostic and makes no full 835-frame reproduction claim.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import traceback
from typing import Any

import numpy as np
import torch


SCHEMA = "core.cross_host_canary.element_trace.v1"
PROGRESS_SCHEMA = "core.cross_host_canary.element_trace.progress.v1"
CANARY_SCHEMA = "core.cross_host_canary.v1"
EXPECTED_HIDDEN = 64
EXPECTED_SEED = 17
EXPECTED_UPDATE = 500
EXPECTED_CHUNK_SIZE = 256
EXPECTED_MAX_STEPS = 20
POSITION_ATOL_M = 1.0e-5
VELOCITY_ATOL_MPS = 1.0e-4
RELATIVE_TOLERANCE = 1.0e-4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_reference_canary():
    """Load the frozen canary helpers without importing or modifying it."""
    path = Path(__file__).with_name("core_cross_host_canary.py").resolve()
    spec = importlib.util.spec_from_file_location("core_cross_host_canary_frozen", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load frozen canary source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _finite_stats(array: np.ndarray) -> dict[str, Any]:
    array = np.asarray(array)
    if array.size == 0:
        return {"finite": True, "min": None, "max": None, "mean": None, "rms": None, "max_abs": None}
    if array.dtype.kind in "fc" and not np.isfinite(array).all():
        return {"finite": False, "min": None, "max": None, "mean": None, "rms": None, "max_abs": None}
    values = np.asarray(array, dtype=np.float64)
    return {
        "finite": True,
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "rms": float(np.sqrt(np.mean(values * values))),
        "max_abs": float(np.max(np.abs(values))),
    }


def _array_spec(array: Any, *, role: str) -> dict[str, Any]:
    value = np.ascontiguousarray(np.asarray(array))
    raw = value.view(np.uint8)
    return {
        "role": role,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "dtype": str(value.dtype),
        "shape": [int(item) for item in value.shape],
        "nbytes": int(value.nbytes),
        **_finite_stats(value),
    }


def _as_cpu(value: torch.Tensor) -> np.ndarray:
    return value.detach().to(device="cpu").contiguous().numpy().copy()


def _tensor_transparency(reference: torch.Tensor, captured: torch.Tensor) -> dict[str, Any]:
    """Summarize an independent original-forward versus capture-forward check."""
    a, b = _as_cpu(reference), _as_cpu(captured)
    result: dict[str, Any] = {
        "shape_equal": a.shape == b.shape,
        "dtype_equal": a.dtype == b.dtype,
        "left_dtype": str(a.dtype),
        "right_dtype": str(b.dtype),
        "left_shape": [int(item) for item in a.shape],
        "right_shape": [int(item) for item in b.shape],
        "exact_equal": False,
        "finite": bool(np.isfinite(a).all() and np.isfinite(b).all()),
    }
    if a.shape != b.shape or not result["finite"]:
        result["max_abs_error"] = None
        return result
    difference = np.abs(np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64))
    result["exact_equal"] = bool(np.array_equal(a, b))
    result["max_abs_error"] = float(np.max(difference)) if difference.size else 0.0
    result["mean_abs_error"] = float(np.mean(difference)) if difference.size else 0.0
    return result


def _capture_forward(
    model: Any,
    features: torch.Tensor,
    position: torch.Tensor,
    neighbors: torch.Tensor,
    h: float,
    centers: torch.Tensor,
    core_models: Any,
    *,
    capture: bool,
    capture_edge_input: bool = False,
) -> tuple[torch.Tensor, dict[str, Any] | None]:
    """Mirror the registered graph forward and capture raw reduction inputs.

    The arithmetic and ordering intentionally match ``DualIncrementModel``.
    Capture copies happen only after each tensor has been produced and never
    feed a value back into the model.
    """
    features = torch.as_tensor(features)
    position = torch.as_tensor(position, dtype=features.dtype, device=features.device)
    neighbors = torch.as_tensor(neighbors, dtype=torch.long, device=features.device)
    centers = torch.as_tensor(centers, dtype=torch.long, device=features.device).reshape(-1)
    encoded = model.encoder(features)
    trace: dict[str, Any] | None = None
    if capture:
        trace = {
            "centers": _as_cpu(centers),
            "encoder_node_index": None,
            "encoder": None,
            "normalized_features": _as_cpu(features[centers]),
            "layers": [],
            "head_input": None,
            "head_raw": None,
            "head_normalized": None,
        }
    if model.kind == "mlp":
        head_input = encoded[centers]
        head_raw = model.head(head_input)
        result = head_raw * model.target_scale
        if trace is not None:
            trace["encoder_node_index"] = _as_cpu(centers)
            trace["encoder"] = _as_cpu(encoded[centers])
            trace["head_input"] = _as_cpu(head_input)
            trace["head_raw"] = _as_cpu(head_raw)
            trace["head_normalized"] = _as_cpu(result)
        return result, trace

    s1, s2 = core_models.two_hop_halo(centers, neighbors, n=int(features.shape[0]))
    values = encoded[s2]
    sources = s2
    if trace is not None:
        trace["encoder_node_index"] = _as_cpu(s2)
        trace["encoder"] = _as_cpu(encoded[s2])
    for layer, destinations in enumerate((s1, centers)):
        lookup = torch.full((features.shape[0],), -1, dtype=torch.long, device=features.device)
        lookup[sources] = torch.arange(len(sources), device=features.device)
        nei = neighbors[destinations]
        valid = nei >= 0
        safe = nei.clamp_min(0)
        source_index = lookup[safe].clamp_min(0)
        target_index = lookup[destinations]
        if torch.any(target_index < 0) or torch.any(source_index < 0):
            raise RuntimeError("two-hop halo omitted a required source")
        src = values[source_index]
        dst = values[target_index]
        relative_position = (position[safe] - position[destinations, None]) / float(h)
        relative_velocity = features[safe, 3:6] - features[destinations, None, 3:6]
        distance = torch.linalg.vector_norm(relative_position, dim=-1, keepdim=True)
        edge = torch.cat((dst[:, None].expand_as(src), src,
                          relative_position, relative_velocity, distance), dim=-1)
        raw_message = model.messages[layer](edge)
        masked_message = raw_message * valid[..., None]
        aggregate = masked_message.sum(1) / valid.sum(1).clamp_min(1)[:, None]
        update_input = torch.cat((dst, aggregate), dim=-1)
        update_output = model.updates[layer](update_input)
        updated = dst + update_output
        if trace is not None:
            edge_destination = destinations[:, None].expand_as(nei)
            edge_slot = torch.arange(nei.shape[1], device=nei.device)[None, :].expand_as(nei)
            valid_flat = valid.reshape(-1)
            source_position = torch.where(valid, source_index, torch.full_like(source_index, -1))
            trace["layers"].append({
                "layer": int(layer),
                "destination": "one_hop" if layer == 0 else "centers",
                "destination_node_index": _as_cpu(destinations),
                "source_node_index": _as_cpu(sources),
                "destination_position": _as_cpu(target_index),
                "edge_neighbor_index": _as_cpu(nei),
                "edge_valid_mask": _as_cpu(valid),
                "edge_source_position": _as_cpu(source_position),
                "edge_destination_index_valid": _as_cpu(edge_destination.reshape(-1)[valid_flat]),
                "edge_neighbor_index_valid": _as_cpu(nei.reshape(-1)[valid_flat]),
                "edge_slot_index_valid": _as_cpu(edge_slot.reshape(-1)[valid_flat]),
                # Edge features are needed to distinguish message-MLP input
                # divergence from a reduction divergence.  The caller keeps
                # them only on the first transition to bound artifact size.
                "edge_input_valid": (
                    _as_cpu(edge.reshape(-1, edge.shape[-1])[valid_flat])
                    if capture_edge_input else None
                ),
                "message_raw_valid": _as_cpu(raw_message.reshape(-1, raw_message.shape[-1])[valid_flat]),
                "aggregate": _as_cpu(aggregate),
                "updated_node_embedding": _as_cpu(updated),
            })
        values = updated
        sources = destinations
    head_input = values
    head_raw = model.head(head_input)
    result = head_raw * model.target_scale
    if trace is not None:
        trace["head_input"] = _as_cpu(head_input)
        trace["head_raw"] = _as_cpu(head_raw)
        trace["head_normalized"] = _as_cpu(result)
    return result, trace


def _add_array(arrays: dict[str, np.ndarray], roles: dict[str, str], name: str, value: Any, role: str) -> str:
    if name in arrays:
        raise ValueError(f"duplicate element-trace array name: {name}")
    array = np.ascontiguousarray(np.asarray(value))
    if array.dtype.kind in "fc" and not np.isfinite(array).all():
        raise FloatingPointError(f"nonfinite captured array: {name}")
    arrays[name] = array.copy()
    roles[name] = role
    return name


def _write_npz(path: Path, arrays: dict[str, np.ndarray]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    os.replace(temporary, path)
    return sha256_file(path)


def _progress(path: Path, *, case_id: str, expected_steps: int, completed_steps: int,
              output: Path, arrays_output: Path, status: str, error: str | None = None) -> None:
    payload: dict[str, Any] = {
        "schema": PROGRESS_SCHEMA,
        "case_id": case_id,
        "expected_steps": int(expected_steps),
        "completed_steps": int(completed_steps),
        "status": status,
        "output": str(output),
        "arrays_output": str(arrays_output),
    }
    if error is not None:
        payload["error"] = error
    _atomic_json(path, payload)


def _array_store_metadata(arrays: dict[str, np.ndarray], roles: dict[str, str]) -> dict[str, Any]:
    return {
        name: _array_spec(value, role=roles[name])
        for name, value in sorted(arrays.items())
    }


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    arrays_output = Path(args.arrays_output).expanduser().resolve()
    progress_output = (Path(args.progress_output).expanduser().resolve()
                       if args.progress_output else output.with_name(output.stem + "-progress.json"))
    maximum_steps = min(int(args.maximum_steps), EXPECTED_MAX_STEPS)
    started = __import__("time").perf_counter()
    arrays: dict[str, np.ndarray] = {}
    roles: dict[str, str] = {}
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "canary_schema": CANARY_SCHEMA,
        "status": "started",
        "case_id": args.case_id,
        "model_kind": args.model_kind,
        "maximum_steps": maximum_steps,
        "expected_frames": maximum_steps + 1,
        "chunk_size": int(args.chunk_size),
        "capture_policy": {
            "state_frames": "all_frames_0_through_maximum_steps",
            "trace_chunk": {"start": 0, "stop": int(args.chunk_size), "full_field_neighbors": True},
            "message_output": "valid_edges_only_for_every_transition_step",
            "message_input": "valid_edges_only_on_transition_step_0",
            "array_format": "numpy_npz_compressed_allow_pickle_false",
        },
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "position_absolute_tolerance_m": POSITION_ATOL_M,
            "velocity_absolute_tolerance_mps": VELOCITY_ATOL_MPS,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "tolerances_frozen": True,
        },
        "steps": [],
        "events": [],
    }
    _progress(progress_output, case_id=args.case_id, expected_steps=maximum_steps,
              completed_steps=0, output=output, arrays_output=arrays_output, status="starting")
    try:
        if int(args.maximum_steps) != maximum_steps or maximum_steps < 1:
            raise ValueError(f"maximum_steps must be in [1,{EXPECTED_MAX_STEPS}]")
        if int(args.chunk_size) != EXPECTED_CHUNK_SIZE:
            raise ValueError(f"chunk_size is fixed at {EXPECTED_CHUNK_SIZE}")
        if args.model_kind not in ("graph_raw", "graph_residual"):
            raise ValueError("element trace requires a registered two-layer graph model")
        if str(args.device).startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

        reference = _load_reference_canary()
        reference._configure_determinism(bool(args.deterministic))
        bundle_root = Path(args.bundle_root).expanduser().resolve()
        modules = reference._load_bundle_modules(bundle_root)
        imported = [reference._module_identity(modules[name]) for name in sorted(modules)]
        environment = reference.capture_environment(
            device=args.device,
            deterministic_requested=bool(args.deterministic),
            imported_modules=imported,
        )
        result["environment"] = environment
        result["events"].append("environment_captured_before_model_construction")
        result["source"] = {
            "element_trace_script": str(Path(__file__).resolve()),
            "element_trace_script_sha256": sha256_file(Path(__file__).resolve()),
            "frozen_canary_script": str(Path(reference.__file__).resolve()),
            "frozen_canary_script_sha256": sha256_file(Path(reference.__file__).resolve()),
        }
        identity = reference._fixed_identity(
            bundle_root, modules,
            manifest_sha256=args.expected_manifest_sha256,
            checkpoint_sha256=args.expected_checkpoint_sha256,
            models_sha256=args.expected_models_sha256,
        )
        result["bundle"] = {"root": str(bundle_root), "identity": identity}
        manifest = bundle_root / "dataset.json"
        checkpoint = bundle_root / "models" / "checkpoint-001.pt"
        dataset = modules["core_dataset"].CoreDataset(manifest, bundle_root, max_open_files=2)
        record = dataset.record(args.case_id)
        times = dataset.times(args.case_id)
        if maximum_steps >= len(times):
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
        n = initial.count
        state_position = np.empty((maximum_steps + 1, n, 3), dtype=np.float64)
        state_velocity = np.empty((maximum_steps + 1, n, 3), dtype=np.float64)
        state_position[0] = initial.position
        state_velocity[0] = initial.velocity
        frame_time = np.empty((maximum_steps + 1,), dtype=np.float64)
        frame_time[0] = initial.time_s
        _add_array(arrays, roles, "frame_time_s", frame_time, "state.frame_time_s")
        # The arrays are filled in place below; the final metadata is created
        # after rollout so its digest describes the completed values.
        _add_array(arrays, roles, "state_position", state_position, "state.position")
        _add_array(arrays, roles, "state_velocity", state_velocity, "state.velocity")
        _add_array(arrays, roles, "particle_id", initial.particle_id, "state.particle_id")
        _add_array(arrays, roles, "particle_zone", initial.particle_zone, "state.particle_zone")
        _add_array(arrays, roles, "mass", initial.mass, "state.mass")
        _add_array(arrays, roles, "valid", initial.valid, "state.valid")

        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if payload.get("model_kind") != args.model_kind or int(payload.get("hidden", -1)) != EXPECTED_HIDDEN:
            raise ValueError("checkpoint model identity is not the registered hidden64 graph model")
        if int(payload.get("seed", -1)) != EXPECTED_SEED or int(payload.get("update", -1)) != EXPECTED_UPDATE:
            raise ValueError("checkpoint seed/update does not match the registered element-trace checkpoint")
        normalization = modules["core_models"].Normalization.from_dict(payload["normalization"])
        model = modules["core_models"].DualIncrementModel(args.model_kind, hidden=EXPECTED_HIDDEN)
        model.load_state_dict(payload.get("model_state", payload["state_dict"]))
        model.eval()
        result["events"].append("cpu_model_constructed_after_environment_capture")
        device = torch.device(args.device)
        model = model.to(device)
        result["events"].append("model_moved_after_environment_capture")
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)

        current = initial
        for step in range(maximum_steps):
            dt = float(times[step + 1] - times[step])
            features_np, acceleration = modules["core_models"].node_features(current, known, dt)
            neighbors_np, diagnostics = modules["core_models"].neighbor_table(
                current, float(known.numerics["h_m"])
            )
            features = torch.as_tensor(features_np, dtype=torch.float32, device=device)
            position = torch.as_tensor(current.position, dtype=torch.float32, device=device)
            neighbors = torch.as_tensor(neighbors_np, dtype=torch.long, device=device)
            if normalization is not None:
                features = normalization.normalize_features(features)
            prior_np = np.column_stack((
                current.velocity * dt + 0.5 * acceleration * dt * dt,
                acceleration * dt,
            ))
            prior = torch.as_tensor(prior_np, dtype=torch.float32, device=device)
            output_np = np.empty((n, modules["core_models"].OUTPUT_DIM), dtype=np.float64)
            first_trace: dict[str, Any] | None = None
            with torch.no_grad():
                for start in range(0, n, int(args.chunk_size)):
                    stop = min(start + int(args.chunk_size), n)
                    centers = torch.arange(start, stop, device=device)
                    prediction_normalized, trace = _capture_forward(
                        model, features, position, neighbors,
                        float(known.numerics["h_m"]), centers, modules["core_models"],
                        capture=(start == 0), capture_edge_input=(start == 0 and step == 0),
                    )
                    if start == 0:
                        first_trace = trace
                        if step == 0:
                            # This extra call is an explicit transparency
                            # witness.  It runs the registered model.forward
                            # on the same tensors after capture_forward and
                            # never contributes to the rollout prediction.
                            with torch.no_grad():
                                original_output = model(
                                    features, position, neighbors,
                                    float(known.numerics["h_m"]), centers=centers,
                                )
                            result["capture_transparency"] = {
                                "schema": "core.cross_host_canary.capture_transparency.v1",
                                "step": 0,
                                "frame": 1,
                                "chunk": {"start": 0, "stop": int(stop)},
                                "original_model_forward_vs_capture_forward": _tensor_transparency(
                                    original_output, prediction_normalized
                                ),
                            }
                    result_target = prediction_normalized
                    if normalization is not None:
                        target_std = torch.tensor(normalization.target_std, dtype=result_target.dtype, device=device)
                        target_mean = torch.tensor(normalization.target_mean, dtype=result_target.dtype, device=device)
                        result_target = result_target * target_std + target_mean
                    result_with_prior = result_target
                    if model.kind == "graph_residual":
                        result_with_prior = result_target + prior[start:stop]
                    output_np[start:stop] = result_with_prior.detach().to(device="cpu").numpy()
                    if start == 0 and first_trace is not None:
                        first_trace["head_target_space"] = _as_cpu(result_target)
                        first_trace["prior"] = np.ascontiguousarray(prior_np[start:stop])
                        first_trace["prediction_with_prior"] = _as_cpu(result_with_prior)
            if first_trace is None:
                raise RuntimeError("first chunk trace was not captured")
            prediction = modules["core_contract"].StepPrediction(output_np[:, :3], output_np[:, 3:])
            next_state = modules["core_contract"].apply_prediction(current, prediction, dt)
            frame = step + 1
            state_position[frame] = next_state.position
            state_velocity[frame] = next_state.velocity
            frame_time[frame] = next_state.time_s
            # Rebind the arrays to the filled buffers; the dictionary entries
            # already point at these buffers but this guards against future
            # helper changes that return a copied view.
            arrays["state_position"] = state_position
            arrays["state_velocity"] = state_velocity
            arrays["frame_time_s"] = frame_time
            step_prefix = f"step_{step:03d}"
            transition: dict[str, Any] = {
                "step": int(step),
                "frame": int(frame),
                "dt_s": dt,
                "diagnostics": diagnostics,
                "first_chunk": {"start": 0, "stop": min(int(args.chunk_size), n)},
                "arrays": {},
                "layers": [],
            }
            for name, value, role in (
                (f"{step_prefix}_normalized_features", first_trace["normalized_features"], "trace.normalized_features"),
                (f"{step_prefix}_encoder_node_index", first_trace["encoder_node_index"], "trace.encoder.node_index"),
                (f"{step_prefix}_encoder", first_trace["encoder"], "trace.encoder.values"),
                (f"{step_prefix}_centers", first_trace["centers"], "trace.centers"),
                (f"{step_prefix}_head_input", first_trace["head_input"], "trace.head.input"),
                (f"{step_prefix}_head_raw", first_trace["head_raw"], "trace.head.raw_output"),
                (f"{step_prefix}_head_normalized", first_trace["head_normalized"], "trace.head.normalized_output"),
                (f"{step_prefix}_head_target_space", first_trace["head_target_space"], "trace.head.target_space"),
                (f"{step_prefix}_prior", first_trace["prior"], "trace.prior"),
                (f"{step_prefix}_prediction_with_prior", first_trace["prediction_with_prior"], "trace.prediction_with_prior"),
            ):
                transition["arrays"][role] = _add_array(arrays, roles, name, value, role)
            for layer in first_trace["layers"]:
                layer_index = int(layer["layer"])
                layer_prefix = f"{step_prefix}_layer_{layer_index}"
                layer_record: dict[str, Any] = {
                    "layer": layer_index,
                    "destination": layer["destination"],
                    "arrays": {},
                }
                layer_fields = (
                    ("destination_node_index", "node.destination_index"),
                    ("source_node_index", "node.source_index"),
                    ("destination_position", "node.destination_position"),
                    ("edge_neighbor_index", "edge.neighbor_index"),
                    ("edge_valid_mask", "edge.valid_mask"),
                    ("edge_source_position", "edge.source_position"),
                    ("edge_destination_index_valid", "edge.destination_index_valid"),
                    ("edge_neighbor_index_valid", "edge.neighbor_index_valid"),
                    ("edge_slot_index_valid", "edge.slot_index_valid"),
                    ("message_raw_valid", "message.raw_valid_edges"),
                    ("aggregate", "aggregate.values"),
                    ("updated_node_embedding", "update.updated_node_embedding"),
                )
                for field, role in layer_fields:
                    name = f"{layer_prefix}_{field}"
                    layer_record["arrays"][role] = _add_array(arrays, roles, name, layer[field], f"layer{layer_index}.{role}")
                # Edge inputs are larger than message/aggregate tensors and
                # are retained only for the first transition by design.
                if step == 0:
                    if layer["edge_input_valid"] is None:
                        raise RuntimeError("first-transition edge input was not captured")
                    name = f"{layer_prefix}_edge_input_valid"
                    layer_record["arrays"]["edge.input_valid_edges"] = _add_array(
                        arrays, roles, name, layer["edge_input_valid"], f"layer{layer_index}.edge.input_valid_edges"
                    )
                transition["layers"].append(layer_record)
            result["steps"].append(transition)
            current = next_state
            completed = step + 1
            if completed % int(args.progress_every) == 0 or completed == maximum_steps:
                _progress(progress_output, case_id=args.case_id, expected_steps=maximum_steps,
                          completed_steps=completed, output=output, arrays_output=arrays_output, status="running")

        if any(frame != 0 for _, frame in dataset.read_log):
            raise AssertionError("element trace read a future fluid state")
        arrays_sha256 = _write_npz(arrays_output, arrays)
        result["status"] = "complete"
        result["completed_steps"] = maximum_steps
        result["expected_frames"] = maximum_steps + 1
        result["autonomous"] = True
        result["future_state_inputs"] = False
        result["read_log"] = [[str(case), int(frame)] for case, frame in dataset.read_log]
        result["array_store"] = {
            "path": arrays_output.name,
            "format": "npz",
            "compressed": True,
            "allow_pickle": False,
            "sha256": arrays_sha256,
            "arrays": _array_store_metadata(arrays, roles),
        }
        result["state_arrays"] = {
            "frame_time_s": "frame_time_s",
            "position": "state_position",
            "velocity": "state_velocity",
            "particle_id": "particle_id",
            "particle_zone": "particle_zone",
            "mass": "mass",
            "valid": "valid",
        }
        result["elapsed_seconds"] = float(__import__("time").perf_counter() - started)
        if device.type == "cuda":
            result["resource"] = {
                "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
            }
        _atomic_json(output, result)
        _progress(progress_output, case_id=args.case_id, expected_steps=maximum_steps,
                  completed_steps=maximum_steps, output=output, arrays_output=arrays_output, status="complete")
        return 0
    except Exception as error:
        result["status"] = "failed"
        result["completed_steps"] = len(result.get("steps", []))
        result["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        _atomic_json(output, result)
        _progress(progress_output, case_id=args.case_id, expected_steps=maximum_steps,
                  completed_steps=len(result.get("steps", [])), output=output, arrays_output=arrays_output,
                  status="failed", error=f"{type(error).__name__}: {error}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--model-kind", default="graph_residual")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--chunk-size", type=int, default=EXPECTED_CHUNK_SIZE)
    parser.add_argument("--maximum-steps", "--max-steps", type=int, default=EXPECTED_MAX_STEPS)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="element-trace JSON metadata")
    parser.add_argument("--arrays-output", type=Path, required=True, help="compressed element-trace NPZ")
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    parser.add_argument("--expected-models-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.checkpoint is not None:
        expected = (Path(args.bundle_root).resolve() / "models" / "checkpoint-001.pt").resolve()
        if Path(args.checkpoint).resolve() != expected:
            raise SystemExit("the element trace checkpoint is fixed to bundle/models/checkpoint-001.pt")
    if int(args.progress_every) < 1:
        raise SystemExit("--progress-every must be positive")
    return run(args)


if __name__ == "__main__":  # pragma: no cover - exercised by runtime workers
    raise SystemExit(main())
