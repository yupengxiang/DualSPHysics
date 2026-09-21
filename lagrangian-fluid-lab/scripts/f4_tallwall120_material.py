#!/usr/bin/env python3
"""Versioned material overlay for the F4 1.2 m tall-wall source.

The existing F4 resting-pool tracer is deliberately tied to the older 0.6 m
wall geometry.  This module keeps its visible cKDTree/Shepard support model
and continuous event observer, but binds a new material scope to the terminal
1.2 m tall-wall source.  It is a diagnostic overlay: it does not modify the
CFD source, native ``Mk`` labels, a ledger, or any qualification gate.

The checkpoint sidecar uses immutable, content-addressed generations.  A
published generation is never overwritten before the manifest points at it;
therefore a process killed after generation publication and before manifest
publication can still resume from the previous manifest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

import h5py
import numpy as np

# Keep imports bound to this checkout when the worker invokes the script by
# absolute path rather than ``python -m``.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_material as cm


SCHEMA = "core.material.f4.tallwall120.v1"
CHECKPOINT_SCHEMA = "core.material.f4.tallwall120.checkpoint.v2"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
REVISION_ID = "F4_tallwall120_material_baseline24_v1"
SOURCE_RECIPE_ID = "F4_mdbc_laminar_nu1e6_tallwall120_v1"
MATERIAL_RECIPE_ID = "F4_tallwall120_material_overlay_baseline24_v1"
INTERFACE_Z_M = 0.18
WALL_HIGH = np.array([1.2, 0.4, 1.2], dtype=np.float64)
WALL_LOW = np.zeros(3, dtype=np.float64)
SOURCE_SIZE = np.array([0.26, 0.16, 0.14], dtype=np.float64)
DESTINATION_SIZE = np.array([1.2, 0.4, 0.18], dtype=np.float64)
INITIAL_HORIZON_S = 4.34
EXTENDED_HORIZON_S = 8.68
GRAVITY_TIME_S = 0.3497487083913345
NEIGHBOUR_VARIANT = "baseline24"
NEIGHBOUR_BACKEND = "f3_ckdtree_visible_shepard_distance_v1"
NEIGHBOURS = 24
REGULARIZATION_M = cm.REGULARIZATION_M
MAXIMUM_SUPPORT_DISTANCE_M = cm.MAXIMUM_SUPPORT_DISTANCE_M
GATE = cm.GATE
CHECKPOINT_FIELDS = tuple(cm.F4_CHECKPOINT_FIELDS)
HISTORY_FIELDS = ("time",) + CHECKPOINT_FIELDS


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return cm.digest(Path(path))


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def array_hash(value) -> str:
    return cm._hash_array(value)


def _tallwall_definition(q: float = 0.5, dp_m: float | None = None) -> dict:
    """Return the immutable tall-wall source/destination/event contract."""
    q = cm._f4_q(q)
    if dp_m is not None:
        dp_m = float(dp_m)
        if not np.isfinite(dp_m) or dp_m <= 0.0:
            raise ValueError("dp_m must be finite and positive")
    source = cm.f4_source_region(q)
    destination = cm.f4_destination_region()
    return {
        "family_id": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "source_recipe_id": SOURCE_RECIPE_ID,
        "material_recipe_id": MATERIAL_RECIPE_ID,
        "stage": "qualification_only",
        "qualification_claim": "none",
        "q": q,
        "dp_m": dp_m,
        "source_definition": source,
        "destination_definition": destination,
        "wall_bounds_m": {
            "xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4,
            "zmin": 0.0, "zmax": 1.2,
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "event_definition": {
            "path_interpolation": (
                "native support particle x/v are linearly interpolated only "
                "between the two registered reference frames; the independent "
                "tracer path is integrated by RK2 substeps"
            ),
            "contact": {
                "definition": "first downward crossing from z>0.18 to z<=0.18 after t=0",
                "interface_plane_z_m": INTERFACE_Z_M,
                "direction": "downward",
                "requires_vertical_velocity_mps_lt": 0.0,
            },
            "upward_propagation": {
                "definition": "first upward crossing after contact from z<=0.18 to z>0.18",
                "interface_plane_z_m": INTERFACE_Z_M,
                "direction": "upward",
                "requires_vertical_velocity_mps_gt": 0.0,
            },
            "return": {
                "definition": "first later downward crossing after upward from z>0.18 to z<=0.18",
                "interface_plane_z_m": INTERFACE_Z_M,
                "direction": "downward",
                "requires_vertical_velocity_mps_lt": 0.0,
            },
            "residence": {
                "definition": "time in the continuous destination box after contact",
                "right_censored_if_unresolved": True,
                "box": "destination_definition",
            },
            "post_return_window": {
                "gravity_time_s": GRAVITY_TIME_S,
                "initial_horizon_s": INITIAL_HORIZON_S,
                "maximum_extended_horizon_s": EXTENDED_HORIZON_S,
                "extension_policy": (
                    "one whole-scope doubling only when an event is right-censored; "
                    "a source ending at 4.34 s cannot claim the 8.68 s extension"
                ),
                "completion_required": True,
            },
            "unobserved_event_policy": "NaN/right-censored; no saved-chord imputation",
        },
        "source_labels": (
            "continuous initial source-box membership; native Mk and particle_id "
            "are provenance only"
        ),
        "seed_identity": "independent geometric seed-XXXXXX ids; never native particle_id",
        "provider_contract": {
            "reference": "may read only the two native support frames bracketing the current interval",
            "model": "must provide only current predicted x/v state and public parameters; no future CFD density/state",
            "native_density_mls": False,
        },
    }


def tallwall_walls() -> np.ndarray:
    """Finite bottom and four side walls through z=1.2 m; top is open."""
    return cm.box_surface_triangles(
        WALL_LOW, WALL_HIGH,
        sides=("xmin", "xmax", "ymin", "ymax", "zmin"),
    )


def _checkpoint_paths(output: Path) -> tuple[Path, Path, Path]:
    output = Path(output)
    return (
        output.with_name(output.name + ".checkpoint.json"),
        output.with_name(output.name + ".checkpoints"),
        output.with_name(output.name + ".checkpoint.npz"),
    )


def _atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def write_checkpoint(output: Path, binding: str, frame: int, state: dict, *,
                     fault_after_publish: bool = False) -> dict:
    """Publish a new immutable generation, then atomically publish its pointer."""
    manifest_path, generation_dir, _legacy = _checkpoint_paths(output)
    generation_dir.mkdir(parents=True, exist_ok=True)
    temporary = generation_dir / f".state-{int(frame):08d}.partial-{os.getpid()}.npz"
    np.savez_compressed(temporary, **{name: np.asarray(state[name]) for name in CHECKPOINT_FIELDS})
    state_sha256 = digest(temporary)
    generation = generation_dir / f"state-{int(frame):08d}-{state_sha256[:20]}.npz"
    os.replace(temporary, generation)
    if fault_after_publish or os.environ.get("F4_TALLWALL120_FAULT_AFTER_GENERATION") == "1":
        raise RuntimeError("fault injection after checkpoint generation publication")
    record = {
        "schema": CHECKPOINT_SCHEMA,
        "binding_sha256": hashlib.sha256(binding.encode()).hexdigest(),
        "committed": int(frame),
        "generation": generation.name,
        "generation_dir": generation_dir.name,
        "state_sha256": state_sha256,
        "fields": list(CHECKPOINT_FIELDS),
        "generation_count_policy": "append-only; no pre-manifest overwrite",
    }
    _atomic_json(manifest_path, record)
    return record


def read_checkpoint(output: Path, binding: str):
    manifest_path, generation_dir, _legacy = _checkpoint_paths(output)
    if not manifest_path.exists():
        return None
    record = json.loads(manifest_path.read_text())
    expected_binding = hashlib.sha256(binding.encode()).hexdigest()
    if record.get("schema") != CHECKPOINT_SCHEMA or record.get("binding_sha256") != expected_binding:
        raise ValueError("tallwall checkpoint provenance mismatch")
    if record.get("fields") != list(CHECKPOINT_FIELDS):
        raise ValueError("tallwall checkpoint field contract mismatch")
    generation = generation_dir / str(record.get("generation", ""))
    if generation.parent != generation_dir or not generation.is_file():
        raise ValueError("tallwall checkpoint generation is missing")
    if digest(generation) != record.get("state_sha256"):
        raise ValueError("tallwall checkpoint generation changed")
    with np.load(generation, allow_pickle=False) as archive:
        state = {name: np.array(archive[name], copy=True) for name in CHECKPOINT_FIELDS}
    return int(record["committed"]), state


def _create_output(out, initial, weight, labels, tracer_ids, binding, definition, provider_role):
    n = len(initial)
    out.attrs["schema"] = SCHEMA
    out.attrs["binding"] = binding
    out.attrs["committed"] = -1
    out.attrs["checkpoint_schema"] = CHECKPOINT_SCHEMA
    out.attrs["checkpoint_policy"] = "content_addressed_generation_append_only"
    out.attrs["provider_role"] = provider_role
    out.attrs["source_definition"] = json.dumps(definition, sort_keys=True)
    out.attrs["event_definition"] = json.dumps(definition["event_definition"], sort_keys=True)
    out.attrs["seed_identity"] = "independent_geometric_seed; no native particle id"
    out.create_dataset("initial_position", data=initial)
    out.create_dataset("weight", data=weight)
    out.create_dataset("source_label", data=labels)
    out.create_dataset("tracer_id", data=np.asarray(tracer_ids, dtype=h5py.string_dtype("utf-8")))
    out.create_dataset("source_membership", data=cm.f4_source_membership(initial, definition["q"]))
    out.create_dataset("destination_membership", data=cm.f4_destination_membership(initial))
    for name, shape, dtype in (
        ("time", (), "f8"), ("position", (n, 3), "f8"), ("reliable", (n,), "?"),
        ("contact_time", (n,), "f8"), ("upward_time", (n,), "f8"),
        ("return_time", (n,), "f8"), ("residence", (n,), "f8"),
        ("contacted", (n,), "?"), ("upward", (n,), "?"),
        ("returned", (n,), "?"), ("event_status", (n,), "i1"),
    ):
        out.create_dataset(name, shape=(0,) + shape, maxshape=(None,) + shape,
                           dtype=dtype, chunks=(1,) + shape)
    out.flush()


def _validate_resume_output(out, initial, weight, labels, tracer_ids, binding):
    if out.attrs.get("schema") != SCHEMA or out.attrs.get("binding") != binding:
        raise ValueError("tallwall restart provenance mismatch")
    for name in ("initial_position", "weight", "source_label", "tracer_id",
                 "source_membership", "destination_membership") + HISTORY_FIELDS + ("event_status",):
        if name not in out:
            raise ValueError(f"tallwall restart output missing dataset {name}")
    if not np.array_equal(out["initial_position"][:], initial) or not np.array_equal(out["weight"][:], weight):
        raise ValueError("tallwall restart seed metadata mismatch")
    if not np.array_equal(out["source_label"][:], labels):
        raise ValueError("tallwall restart source definition mismatch")
    stored_ids = np.asarray(out["tracer_id"].asstr()[:])
    if cm._hash_array(stored_ids) != cm._hash_array(tracer_ids):
        raise ValueError("tallwall restart tracer identity mismatch")
    return int(out.attrs.get("committed", -1))


def _append_frame(out, frame, frames, state, *, fault_after_append: bool = False):
    target = int(frame) + 1
    for name in HISTORY_FIELDS + ("event_status",):
        out[name].resize(target, axis=0)
    values = {
        "time": float(frames.times[frame]),
        **{name: state[name] for name in CHECKPOINT_FIELDS},
        "event_status": cm._f4_status(state),
    }
    for name, value in values.items():
        out[name][frame] = value
    out.flush()
    if fault_after_append or os.environ.get("F4_TALLWALL120_FAULT_AFTER_H5_APPEND") == "1":
        raise RuntimeError("fault injection after H5 append before committed pointer")
    out.attrs["committed"] = int(frame)
    out.flush()


def _state_from_h5(out, frame):
    return {name: np.array(out[name][frame], copy=True) for name in CHECKPOINT_FIELDS}


def event_summary(out, definition: dict) -> dict:
    result = cm.f4_event_summary(out)
    result.update({
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "material_recipe_id": MATERIAL_RECIPE_ID,
        "task": "F4 tallwall120 continuous drop source to resting-pool events",
        "qualification_claim": "none",
        "material_reliability_status": "uncalibrated",
        "wall_bounds_m": definition["wall_bounds_m"],
        "checkpoint_schema": CHECKPOINT_SCHEMA,
    })
    return result


def _build_binding(frames, source, initial, weight, labels, tracer_ids, walls, definition,
                   substeps: int, provider_role: str) -> dict:
    source_hash = getattr(frames, "source_sha256", None) or digest(source)
    binding = {
        "schema": SCHEMA,
        "scope_id": getattr(frames, "scope_id", SCOPE_ID),
        "revision_id": getattr(frames, "revision_id", REVISION_ID),
        "material_recipe_id": getattr(frames, "material_recipe_id", MATERIAL_RECIPE_ID),
        "source_sha256": source_hash,
        "source_case_scope": definition["source_recipe_id"],
        "code_sha256": digest(Path(__file__)),
        "core_material_sha256": digest(Path(cm.__file__)),
        "neighbor_code_sha256": digest(Path(__file__).with_name("f3_material_neighbors.py")),
        "passive_code_sha256": digest(Path(__file__).with_name("passive_tracers.py")),
        "initial_sha256": array_hash(initial),
        "weight_sha256": array_hash(weight),
        "source_label_sha256": array_hash(labels),
        "tracer_id_sha256": array_hash(tracer_ids),
        "walls_sha256": array_hash(walls),
        "f4_definition": definition,
        "substeps": substeps,
        "source_semantics": "reference_native_saved_frames",
        "provider_role": provider_role,
        "backend": NEIGHBOUR_BACKEND,
        "neighbour_variant": NEIGHBOUR_VARIANT,
        "neighbours": NEIGHBOURS,
        "error_estimator": "local_residual",
        "regularization_m": REGULARIZATION_M,
        "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": GATE,
    }
    interpolation = getattr(frames, "temporal_interpolation", None)
    if interpolation is not None:
        binding["temporal_interpolation"] = str(interpolation)
    implementation_path = getattr(frames, "implementation_path", None)
    if implementation_path is not None:
        implementation_path = Path(implementation_path).resolve()
        binding["repair_implementation_path"] = str(implementation_path)
        binding["repair_implementation_sha256"] = digest(implementation_path)
    candidate_id = getattr(frames, "candidate_id", None)
    if candidate_id is not None:
        binding["repair_candidate_id"] = str(candidate_id)
    return binding


def trace_tallwall120(source: Path, output: Path, *, q: float = 0.5,
                      dp_m: float | None = None, seeds: int = 512,
                      substeps: int = 2, stop_after: int | None = None,
                      resume: bool = False, kill_after: int | None = None,
                      provider=None):
    """Run the versioned tall-wall material overlay on a terminal source H5."""
    q = cm._f4_q(q)
    if seeds not in (512, 4096):
        raise ValueError("seeds must be 512 or 4096")
    substeps = cm._positive_integer(substeps, "substeps")
    if stop_after is not None and (isinstance(stop_after, bool) or int(stop_after) < 0):
        raise ValueError("stop_after must be nonnegative")
    if kill_after is not None and (isinstance(kill_after, bool) or int(kill_after) < 0):
        raise ValueError("kill_after must be nonnegative")
    source = Path(source).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    initial = cm.seeds_f4(seeds, q)
    labels = np.ones(len(initial), dtype=np.int8)
    initial, weight, labels, tracer_ids = cm._prepare_seed_metadata(initial, None, labels, None)
    walls = tallwall_walls()
    if not np.all(cm.f4_source_membership(initial, q)):
        raise ValueError("tallwall seeds are outside continuous source box")
    frames, owns_provider = cm._f4_provider(source, provider)
    definition = _tallwall_definition(q, dp_m)
    candidate_revision = getattr(frames, "revision_id", None)
    candidate_recipe = getattr(frames, "material_recipe_id", None)
    candidate_path_interpolation = getattr(frames, "path_interpolation", None)
    if candidate_revision is not None:
        definition["revision_id"] = str(candidate_revision)
    if candidate_recipe is not None:
        definition["material_recipe_id"] = str(candidate_recipe)
    if candidate_path_interpolation is not None:
        event_definition = dict(definition["event_definition"])
        event_definition["path_interpolation"] = str(candidate_path_interpolation)
        definition["event_definition"] = event_definition
    provider_role = getattr(frames, "provider_role", "reference")
    binding = _build_binding(frames, source, initial, weight, labels, tracer_ids, walls,
                             definition, substeps, provider_role)
    binding_text = canonical(binding)
    manifest_path, generation_dir, legacy_npz = _checkpoint_paths(output)
    tracker = cm.F4EventTracker(len(initial), definition=definition)
    started = time.monotonic()
    result = None
    try:
        if resume:
            if not output.exists():
                raise FileNotFoundError(f"cannot resume missing output {output}")
            mode = "r+"
        else:
            if output.exists() or manifest_path.exists() or generation_dir.exists() or legacy_npz.exists():
                raise FileExistsError(f"output/checkpoint already exists for {output}")
            mode = "x"
        with h5py.File(output, mode) as out:
            if resume:
                _validate_resume_output(out, initial, weight, labels, tracer_ids, binding_text)
                checkpoint = read_checkpoint(output, binding_text)
                if checkpoint is None:
                    committed = int(out.attrs.get("committed", -1))
                    if committed < 0:
                        raise ValueError("tallwall restart has no complete checkpoint")
                    state = _state_from_h5(out, committed)
                else:
                    committed, state = checkpoint
                if committed < 0 or committed >= len(frames.times):
                    raise ValueError("tallwall restart checkpoint is outside source frame range")
                for name in HISTORY_FIELDS + ("event_status",):
                    out[name].resize(committed + 1, axis=0)
                _append_frame(out, committed, frames, state)
            else:
                _create_output(out, initial, weight, labels, tracer_ids, binding_text,
                               definition, provider_role)
                state = cm._f4_initial_state(initial, frames, walls, NEIGHBOURS,
                                             "local_residual", tracker)
                write_checkpoint(output, binding_text, 0, state)
                if kill_after == 0:
                    os.kill(os.getpid(), signal.SIGKILL)
                _append_frame(out, 0, frames, state)
                committed = 0
            end = len(frames.times) - 1 if stop_after is None else min(int(stop_after), len(frames.times) - 1)
            if end < committed:
                end = committed
            for frame_index in range(committed, end):
                dt = (float(frames.times[frame_index + 1]) - float(frames.times[frame_index])) / substeps
                field0 = frames.field(frame_index, 0.0)
                for substep in range(substeps):
                    field1 = frames.field(frame_index, (substep + 1) / substeps)
                    cm._f4_advance_state(
                        state, tracker, field0, field1, walls,
                        float(frames.times[frame_index]) + substep * dt,
                        dt, NEIGHBOURS, "local_residual",
                    )
                    field0 = field1
                next_frame = frame_index + 1
                write_checkpoint(output, binding_text, next_frame, state)
                if os.environ.get("F4_TALLWALL120_FAULT_AFTER_CHECKPOINT") == str(next_frame):
                    raise RuntimeError("fault injection after checkpoint manifest before H5 append")
                if kill_after == next_frame:
                    os.kill(os.getpid(), signal.SIGKILL)
                _append_frame(out, next_frame, frames, state)
                committed = next_frame
            result = event_summary(out, definition)
            result.update({
                "status": "completed" if end == len(frames.times) - 1 else "partial",
                "elapsed_seconds": time.monotonic() - started,
                "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "committed_frame": int(out.attrs["committed"]),
                "native_frame_count": len(frames.times),
                "binding": binding,
                "checkpoint_manifest": str(manifest_path),
                "checkpoint_generation_dir": str(generation_dir),
            })
            out.attrs["result"] = json.dumps(result, sort_keys=True, allow_nan=False)
    finally:
        if owns_provider:
            frames.close()
    target = output.with_suffix(".json")
    temporary = target.with_suffix(".json.partial")
    if result is not None:
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
        os.replace(temporary, target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--seeds", type=int, choices=(512, 4096), default=512)
    parser.add_argument("--substeps", type=int, default=2)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--kill-after", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    result = trace_tallwall120(
        Path(args.source), Path(args.output), q=args.q, dp_m=args.dp_m,
        seeds=args.seeds, substeps=args.substeps, stop_after=args.stop_after,
        resume=args.resume, kill_after=args.kill_after,
    )
    if result is not None:
        print(json.dumps({
            "status": result.get("status"),
            "committed_frame": result.get("committed_frame"),
            "event_window_status": result.get("event_window_status"),
            "unknown_fraction_max": max((row.get("unknown_fraction_max", 1.0) for row in result.get("by_source", [])), default=1.0),
            "qualification_claim": result.get("qualification_claim"),
        }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
