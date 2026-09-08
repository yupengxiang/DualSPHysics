#!/usr/bin/env python3
"""R5 bounded material-transport task for the F1 single-obstacle case.

The module is intentionally a small, executable contract rather than a claim
that numerical SPH particle identities are material labels.  It consumes an
already exported trajectory HDF5 and a finite-boundary sidecar, advects a
mass-weighted set of passive tracers on CPU, and writes an auditable HDF5
bundle plus a JSON summary.

Typical first bounded run (after the new F1 medium/fine HDF5 is available)::

    PYTHONUNBUFFERED=1 .venv/bin/python scripts/r5_f1_material_task.py run \
      --hdf5 campaigns/v0.1-candidate/data/R4_F1_center_obstacle_medium.h5 \
      --sidecar campaigns/v0.1-candidate/sidecars/r5-f1/R4_F1_center_obstacle_medium.h5 \
      --case-id R4_F1_center_obstacle_medium \
      --output-dir campaigns/v0.1-candidate/artifacts/r5-f1-material-task

No solver, GenCase, CUDA, or GPU process is launched here.  The default
matrix is four CPU groups: 128/256 seeds x 2/4 tracer substeps.  The CLI
accepts a bounded subset for smoke tests, but never more than eight groups.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import audit_sidecar, sidecar_provider
    from scripts.passive_tracers import advect_hdf5
    from scripts.transport_metrics import points_in_region, validate_transport_spec
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import audit_sidecar, sidecar_provider
    from passive_tracers import advect_hdf5
    from transport_metrics import points_in_region, validate_transport_spec


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
CONTRACT_ROOT = CAMPAIGN / "r5-f1-material-task"
DEFAULT_SPEC = CONTRACT_ROOT / "transport_spec.v1.json"
DEFAULT_OUTPUT_DIR = CAMPAIGN / "artifacts" / "r5-f1-material-task"
OUTPUT_SCHEMA_VERSION = "r6-f1-material-task-output.v2"
DEFAULT_SEED_COUNTS = (128, 256)
DEFAULT_SUBSTEPS = (2, 4)
MAX_CONFIGURATIONS = 8
FLUID_TYPE = 3
EPSILON = 1e-10

SOURCE_LABELS = ("lower", "middle", "upper")
TERMINAL_CATEGORIES = (
    "target",
    "domain",
    "legitimate_exit",
    "numerical_loss",
    "tracer_unknown",
)
FAILURE_REASONS = (
    "none",
    "wall_crossing",
    "support_gate_failure",
    "support_distance_exceedance",
    "support_nonfinite",
    "solver_identity_missing",
    "tracer_unknown",
    "censored_after_first_failure",
)
FIRST_PASSAGE_STATUSES = (
    "observed",
    "censored_by_tracer_failure",
    "censored_by_numerical_loss",
    "legitimate_exit_before_target",
    "right_censored_end_of_window",
)


class InputSnapshot:
    """Validated input metadata and initial mass/source information."""

    def __init__(self, *, hdf5_path: Path, sidecar_path: Path, case_id: str,
                 time: np.ndarray, identity: np.ndarray,
                 initial_fluid_indices: np.ndarray, initial_position: np.ndarray,
                 initial_mass: np.ndarray, initial_source_labels: np.ndarray,
                 solver_valid: np.ndarray, particle_spacing_m: float,
                 input_summary: dict[str, Any]):
        self.hdf5_path = hdf5_path
        self.sidecar_path = sidecar_path
        self.case_id = case_id
        self.time = time
        self.identity = identity
        self.initial_fluid_indices = initial_fluid_indices
        self.initial_position = initial_position
        self.initial_mass = initial_mass
        self.initial_source_labels = initial_source_labels
        self.solver_valid = solver_valid
        self.particle_spacing_m = particle_spacing_m
        self.input_summary = input_summary


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def _string_array(values: Iterable[str]) -> np.ndarray:
    return np.asarray([str(value) for value in values], dtype=object)


def load_transport_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    """Load the tracked, versioned transport contract."""
    payload = json.loads(Path(path).read_text())
    validate_r5_transport_spec(payload)
    return payload


def _validate_region_list(regions: Any, *, role: str) -> list[dict[str, Any]]:
    if not isinstance(regions, list):
        raise ValueError(f"{role} must be a list")
    names: list[str] = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            raise ValueError(f"{role}[{index}] must be an object")
        name = region.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{role}[{index}] requires a non-empty name")
        names.append(name)
        # Reuse the shared region validator for domain/exit regions too.  They
        # intentionally use the same explicit AABB/halfspace/sphere grammar
        # as destinations, even though they are not passed to audit_transport.
        validate_transport_spec({
            "lifecycle_model": "closed",
            "destination_frame": {"kind": "world"},
            "destinations": [dict(region)],
        })
    if len(names) != len(set(names)):
        raise ValueError(f"{role} names must be unique")
    return regions


def _region_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Exact overlap check for the region kinds used by the F1 contract.

    R5 currently freezes AABB target/domain/exit regions.  For other region
    kinds, the conservative result is ``True``; silently accepting a possible
    overlap would make mass categories ambiguous.
    """
    if first.get("type") == "aabb" and second.get("type") == "aabb":
        lower = np.maximum(np.asarray(first["min"], dtype=float), np.asarray(second["min"], dtype=float))
        upper = np.minimum(np.asarray(first["max"], dtype=float), np.asarray(second["max"], dtype=float))
        return bool(np.all(lower <= upper))
    return True


def validate_r5_transport_spec(spec: Mapping[str, Any]) -> None:
    """Validate both the shared transport vocabulary and R5-specific fields."""
    if not isinstance(spec, Mapping):
        raise ValueError("R5 transport spec must be an object")
    if spec.get("spec_id") not in {
        "lagrangian-fluid.f1.single-obstacle.material-transport",
        "lagrangian-fluid.f1.plain-control.material-transport",
    }:
        raise ValueError("unexpected F1 transport spec id")
    if spec.get("version") not in {"r5.1.0", "r6.1.0"}:
        raise ValueError("F1 transport spec version must be r5.1.0 or r6.1.0")
    if spec.get("case_family") != "F1" or spec.get("case_variant") not in {"single_obstacle", "plain_control"}:
        raise ValueError("F1 material task requires single_obstacle or plain_control")
    # The shared validator is deliberately reused, while the source-label
    # semantics remain separate from its legacy source-mask implementation.
    validate_transport_spec(dict(spec))

    sources = spec.get("sources")
    if not isinstance(sources, Mapping) or sources.get("source_label") != "initial_depth_layer":
        raise ValueError("sources must declare initial_depth_layer source_label")
    if sources.get("measure_only") is not True:
        raise ValueError("source_label must be explicitly measure_only")
    if sources.get("labels_are_not_material_identity") is not True:
        raise ValueError("source labels must not be declared material identities")
    if list(sources.get("layer_order", ())) != list(SOURCE_LABELS):
        raise ValueError("source layer order must be lower, middle, upper")
    definition = sources.get("layer_definition")
    if not isinstance(definition, Mapping) or definition.get("axis") != "z":
        raise ValueError("source layers must be defined on initial z")
    if definition.get("reference") not in {
        "initial_valid_fluid_min_max",
        "declared_continuous_initial_fluid_bounds",
    }:
        raise ValueError("source layer reference must be declared continuous or legacy initial bounds")
    if definition.get("reference") == "declared_continuous_initial_fluid_bounds":
        default_bounds = definition.get("default_bounds_m")
        if not isinstance(default_bounds, list) or len(default_bounds) != 2:
            raise ValueError("declared continuous source layers require default_bounds_m")
        values = np.asarray(default_bounds, dtype=float)
        if not np.all(np.isfinite(values)) or values[1] <= values[0]:
            raise ValueError("default continuous source bounds are invalid")
    intervals = definition.get("intervals")
    if not isinstance(intervals, list) or len(intervals) != 3:
        raise ValueError("exactly three source layer intervals are required")
    fractions: list[tuple[float, float]] = []
    for expected, interval in zip(SOURCE_LABELS, intervals):
        if interval.get("name") != expected:
            raise ValueError(f"source interval order/name mismatch for {expected}")
        bounds = interval.get("z_fraction")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"source interval {expected} lacks z_fraction")
        pair = tuple(float(item) for item in bounds)
        if not np.all(np.isfinite(pair)) or pair[1] <= pair[0]:
            raise ValueError(f"source interval {expected} is invalid")
        fractions.append(pair)
    if fractions != [(0.0, 1.0 / 3.0), (1.0 / 3.0, 2.0 / 3.0), (2.0 / 3.0, 1.0)]:
        raise ValueError("source intervals must be the frozen thirds of initial depth")

    destinations = _validate_region_list(spec.get("destinations"), role="destinations")
    domain = spec.get("domain")
    if not isinstance(domain, Mapping):
        raise ValueError("domain region is required")
    _validate_region_list([dict(domain)], role="domain")
    exits = _validate_region_list(spec.get("legitimate_exit_regions"), role="legitimate_exit_regions")
    if any(_region_overlap(destination, exit_region)
           for destination in destinations for exit_region in exits):
        raise ValueError("destination and legitimate-exit regions overlap")
    if list(spec.get("terminal_categories", ())) != list(TERMINAL_CATEGORIES):
        raise ValueError("terminal categories are incomplete or reordered")

    wall = spec.get("wall")
    if not isinstance(wall, Mapping):
        raise ValueError("wall policy is required")
    if wall.get("coordinate_frame") != "world":
        raise ValueError("F1 wall policy must be in world coordinates")
    roles = wall.get("component_roles")
    expected_components = {"17", "18"} if spec.get("case_variant") == "single_obstacle" else {"17"}
    if not isinstance(roles, Mapping) or set(str(key) for key in roles) != expected_components:
        raise ValueError(f"F1 wall policy must freeze components {sorted(expected_components)}")
    for component, role in roles.items():
        if not isinstance(role, Mapping):
            raise ValueError(f"wall component {component} policy must be an object")
        if not role.get("declared_faces") or not role.get("open_faces"):
            raise ValueError(f"wall component {component} needs declared and open faces")
        if role.get("rim_policy") != "finite_generated_triangles_only":
            raise ValueError("F1 rim policy must be finite_generated_triangles_only")
    if wall.get("rim_policy") != "finite_generated_triangles_only":
        raise ValueError("global F1 rim policy is not frozen")
    if wall.get("wall_crossing_is_failure") is not True:
        raise ValueError("wall crossing must be a failure")

    identity = spec.get("identity")
    if not isinstance(identity, Mapping) or list(identity.get("reference_key", ())) != ["particle_zone", "particle_id"]:
        raise ValueError("reference identity must be (particle_zone, particle_id)")
    trace = spec.get("trace_contract")
    required = set(trace.get("required_fields", ())) if isinstance(trace, Mapping) else set()
    expected = {
        "tracer_id", "time", "position", "valid", "source_label", "mass_weight",
        "failure_reason", "first_failure", "destination", "first_passage", "censoring",
    }
    if not expected.issubset(required):
        raise ValueError("trace contract omits required material-task fields")
    accounting = spec.get("mass_accounting")
    if not isinstance(accounting, Mapping) or accounting.get("denominator") != "sum of initial valid fluid mass over all source layers":
        raise ValueError("mass denominator must be initial valid fluid mass")
    if accounting.get("no_survivor_renormalization") is not True:
        raise ValueError("survivor renormalization is forbidden")


def _source_labels_from_z(z_values: np.ndarray, lower: float, upper: float) -> np.ndarray:
    z_values = np.asarray(z_values, dtype=float)
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        raise ValueError("initial fluid z bounds must be finite and increasing")
    fraction = (z_values - lower) / (upper - lower)
    labels = np.full(z_values.shape, "source_label_unknown", dtype=object)
    finite = np.isfinite(fraction)
    labels[finite & (fraction >= -EPSILON) & (fraction < 1.0 / 3.0)] = "lower"
    labels[finite & (fraction >= 1.0 / 3.0) & (fraction < 2.0 / 3.0)] = "middle"
    labels[finite & (fraction >= 2.0 / 3.0) & (fraction <= 1.0 + EPSILON)] = "upper"
    if np.any(labels == "source_label_unknown"):
        raise ValueError("initial fluid particles cannot be assigned to one of three depth layers")
    return labels


def _resolved_spec(spec: dict[str, Any], z_lower: float, z_upper: float, case_id: str) -> dict[str, Any]:
    resolved = deepcopy(spec)
    definition = resolved["sources"]["layer_definition"]
    definition["resolved_initial_z_bounds_m"] = [float(z_lower), float(z_upper)]
    cuts = [z_lower, z_lower + (z_upper - z_lower) / 3.0,
            z_lower + 2.0 * (z_upper - z_lower) / 3.0, z_upper]
    definition["resolved_cut_points_m"] = [float(value) for value in cuts]
    for interval, lower, upper in zip(definition["intervals"], cuts[:-1], cuts[1:]):
        interval["resolved_z_bounds_m"] = [float(lower), float(upper)]
    resolved["resolved_case_id"] = str(case_id)
    return resolved


def _validate_hdf5_schema(hdf5_path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    required = {
        "time", "particle_id", "particle_zone", "valid", "position", "velocity",
        "mass", "type", "mk",
    }
    with h5py.File(Path(hdf5_path), "r") as h5:
        missing = sorted(required - set(h5.keys()))
        if missing:
            raise ValueError(f"F1 HDF5 missing required datasets: {missing}")
        time = np.asarray(h5["time"][:], dtype=np.float64)
        particle_id = np.asarray(h5["particle_id"][:], dtype=np.int64)
        particle_zone = np.asarray(h5["particle_zone"][:], dtype=np.int64)
        valid = np.asarray(h5["valid"][:], dtype=bool)
        position = np.asarray(h5["position"][:], dtype=np.float64)
        velocity = np.asarray(h5["velocity"][:], dtype=np.float64)
        mass = np.asarray(h5["mass"][:], dtype=np.float64)
        ptype = np.asarray(h5["type"][:], dtype=np.int64)
        mk = np.asarray(h5["mk"][:], dtype=np.int64)
        case_id = h5.attrs.get("case_id", "unknown")
        particle_spacing = h5.attrs.get("particle_spacing_m", h5.attrs.get("dp", None))
        schema_version = h5.attrs.get("schema_version", "unknown")
        if isinstance(case_id, bytes):
            case_id = case_id.decode()
    if time.ndim != 1 or len(time) < 2 or not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError("HDF5 time must be finite and strictly increasing")
    frame_count = len(time)
    particle_count = len(particle_id)
    if particle_zone.shape != (particle_count,):
        raise ValueError("particle_zone must have shape [N]")
    expected_scalar = (frame_count, particle_count)
    if valid.shape != expected_scalar or mass.shape != expected_scalar or ptype.shape != expected_scalar or mk.shape != expected_scalar:
        raise ValueError("valid/mass/type/mk must all have shape [T,N]")
    if position.shape != (frame_count, particle_count, 3) or velocity.shape != (frame_count, particle_count, 3):
        raise ValueError("position and velocity must have shape [T,N,3]")
    identity = np.column_stack((particle_zone, particle_id))
    if len(np.unique(identity, axis=0)) != particle_count:
        raise ValueError("duplicate target/reference particle identity (particle_zone, particle_id)")
    initial_fluid = valid[0] & (ptype[0] == FLUID_TYPE)
    if not np.any(initial_fluid):
        raise ValueError("HDF5 contains no initial valid fluid particles")
    if not np.all(np.isfinite(position[0, initial_fluid])):
        raise ValueError("initial fluid positions must be finite")
    if not np.all(np.isfinite(mass[0, initial_fluid])) or np.any(mass[0, initial_fluid] <= 0.0):
        raise ValueError("initial fluid masses must be finite and positive")
    if particle_spacing is None:
        coordinate_steps: list[float] = []
        for axis in range(3):
            values = np.unique(position[0, initial_fluid, axis])
            steps = np.diff(values)
            coordinate_steps.extend(float(value) for value in steps if value > EPSILON)
        particle_spacing = min(coordinate_steps) if coordinate_steps else None
    if particle_spacing is None or not np.isfinite(float(particle_spacing)) or float(particle_spacing) <= 0.0:
        raise ValueError("particle spacing is unavailable; provide a valid HDF5 particle_spacing_m/dp attribute")
    metadata = {
        "case_id": str(case_id),
        "frames": int(frame_count),
        "particles": int(particle_count),
        "identity_key": ["particle_zone", "particle_id"],
        "identity_unique": True,
        "initial_fluid_particles": int(np.sum(initial_fluid)),
        "initial_fluid_mass_kg": float(np.sum(mass[0, initial_fluid], dtype=np.float64)),
        "particle_spacing_m": float(particle_spacing),
        "hdf5_schema_version": str(schema_version),
    }
    arrays = {
        "time": time,
        "identity": identity,
        "valid": valid,
        "position": position,
        "mass": mass,
        "ptype": ptype,
        "mk": mk,
        "initial_fluid": initial_fluid,
    }
    return metadata, arrays


def _validate_sidecar(sidecar_path: Path, snapshot_time: np.ndarray, spec: Mapping[str, Any]) -> dict[str, Any]:
    summary = audit_sidecar(Path(sidecar_path))
    with h5py.File(Path(sidecar_path), "r") as sidecar:
        time = np.asarray(sidecar["time"][:], dtype=np.float64)
        labels_name = "triangle_component" if "triangle_component" in sidecar else "triangle_mk"
        labels = np.asarray(sidecar[labels_name][:], dtype=np.int64)
        kinds = np.asarray(sidecar["triangle_type"][:], dtype=np.int8)
    if time.shape != snapshot_time.shape or not np.allclose(time, snapshot_time, atol=1e-8, rtol=0.0):
        raise ValueError("F1 sidecar and trajectory HDF5 time axes differ")
    expected = {int(key) for key in spec["wall"]["component_roles"]}
    actual = {int(value) for value in np.unique(labels)}
    if actual != expected:
        raise ValueError(f"F1 wall component labels differ: expected {sorted(expected)}, got {sorted(actual)}")
    if not np.all(kinds == 0):
        raise ValueError("F1 single-obstacle sidecar must contain fixed Type 0 walls")
    return {
        **summary,
        "component_label_dataset": labels_name,
        "component_labels_explicit": labels_name == "triangle_component",
        "component_triangle_counts": {
            str(component): int(np.sum(labels == component)) for component in sorted(actual)
        },
        "component_roles": deepcopy(spec["wall"]["component_roles"]),
        "open_face_policy": spec["wall"]["open_face_policy"],
        "rim_policy": spec["wall"]["rim_policy"],
    }


def _material_barrier_provider(sidecar_path: Path, spec: Mapping[str, Any]):
    """Build the full collision provider plus an exact F1 visibility subset.

    The tank component is a convex outer boundary.  Any segment connecting
    two valid fluid samples inside that tank cannot cross it, so it is safe to
    omit that component from interpolation line-of-sight tests.  The complete
    sidecar is still returned to ``spacetime_swept_wall_blocked`` for every
    candidate step, preserving tank-wall crossing failures.
    """
    provider = sidecar_provider(Path(sidecar_path))
    with h5py.File(Path(sidecar_path), "r") as sidecar:
        components = np.asarray(
            sidecar["triangle_component"][:] if "triangle_component" in sidecar else sidecar["triangle_mk"][:],
            dtype=np.int64,
        )
    obstacle_ids = {
        int(component_id)
        for component_id, role in spec["wall"]["component_roles"].items()
        if role.get("role") == "single_obstacle"
    }
    if len(obstacle_ids) > 1:
        raise ValueError("F1 material task supports at most one single_obstacle component")
    visibility_indices = np.flatnonzero(np.isin(components, sorted(obstacle_ids))).astype(np.int64)
    if spec.get("case_variant") == "single_obstacle" and len(visibility_indices) == 0:
        raise ValueError("single_obstacle material task sidecar has no obstacle triangles")
    provider.visibility_triangle_indices = visibility_indices  # type: ignore[attr-defined]
    provider.visibility_filter = (
        "only single_obstacle component; tank convexity proof; full collision sidecar retained"
        if len(obstacle_ids)
        else "no internal obstacle; tank convexity proof; full collision sidecar retained"
    )  # type: ignore[attr-defined]
    return provider


def load_input_snapshot(hdf5_path: Path, sidecar_path: Path, spec: Mapping[str, Any], *, case_id: str | None = None,
                        particle_spacing_m: float | None = None,
                        source_z_bounds_m: Sequence[float] | None = None) -> InputSnapshot:
    """Validate a real HDF5/sidecar pair and freeze its input metadata."""
    hdf5_path = Path(hdf5_path).resolve()
    sidecar_path = Path(sidecar_path).resolve()
    if not hdf5_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError("both --hdf5 and --sidecar must point to existing files")
    validate_r5_transport_spec(spec)
    metadata, arrays = _validate_hdf5_schema(hdf5_path)
    if particle_spacing_m is not None:
        value = float(particle_spacing_m)
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError("particle_spacing_m must be finite and positive")
        metadata["particle_spacing_m"] = value
    resolved_case_id = str(case_id or metadata["case_id"])
    if case_id is not None and metadata["case_id"] not in {"unknown", resolved_case_id}:
        raise ValueError(f"--case-id {case_id!r} does not match HDF5 case_id {metadata['case_id']!r}")
    initial_fluid_indices = np.flatnonzero(arrays["initial_fluid"])
    initial_position = arrays["position"][0, initial_fluid_indices]
    discrete_z_lower = float(np.min(initial_position[:, 2]))
    discrete_z_upper = float(np.max(initial_position[:, 2]))
    continuous_bounds: Sequence[float] | None = source_z_bounds_m
    if continuous_bounds is None:
        with h5py.File(hdf5_path, "r") as h5:
            if "continuous_initial_fluid_z_bounds_m" in h5.attrs:
                continuous_bounds = np.asarray(h5.attrs["continuous_initial_fluid_z_bounds_m"], dtype=float).tolist()
    layer_definition = spec.get("sources", {}).get("layer_definition", {})
    if continuous_bounds is None and layer_definition.get("reference") == "declared_continuous_initial_fluid_bounds":
        continuous_bounds = layer_definition.get("default_bounds_m")
    if continuous_bounds is None:
        continuous_bounds = (discrete_z_lower, discrete_z_upper)
    if len(continuous_bounds) != 2:
        raise ValueError("source_z_bounds_m must contain exactly two values")
    z_lower, z_upper = (float(continuous_bounds[0]), float(continuous_bounds[1]))
    if not np.isfinite(z_lower) or not np.isfinite(z_upper) or z_upper <= z_lower:
        raise ValueError("continuous initial fluid z bounds must be finite and increasing")
    if discrete_z_lower < z_lower - 1e-8 or discrete_z_upper > z_upper + 1e-8:
        raise ValueError(
            "continuous initial fluid bounds do not contain all discrete initial fluid positions: "
            f"bounds=({z_lower}, {z_upper}) discrete=({discrete_z_lower}, {discrete_z_upper})"
        )
    initial_labels = _source_labels_from_z(initial_position[:, 2], z_lower, z_upper)
    sidecar_summary = _validate_sidecar(sidecar_path, arrays["time"], spec)
    source_mass = {
        label: float(np.sum(arrays["mass"][0, initial_fluid_indices][initial_labels == label], dtype=np.float64))
        for label in SOURCE_LABELS
    }
    summary = {
        **metadata,
        "case_id": resolved_case_id,
        "hdf5": _relative(hdf5_path),
        "sidecar": _relative(sidecar_path),
        "hdf5_sha256": _sha256_file(hdf5_path),
        "sidecar_sha256": _sha256_file(sidecar_path),
        "time_start_s": float(arrays["time"][0]),
        "time_end_s": float(arrays["time"][-1]),
        "saved_cadence_median_s": float(np.median(np.diff(arrays["time"]))),
        "initial_z_bounds_m": [discrete_z_lower, discrete_z_upper],
        "continuous_initial_fluid_z_bounds_m": [z_lower, z_upper],
        "source_label_counts": {label: int(np.sum(initial_labels == label)) for label in SOURCE_LABELS},
        "source_label_mass_kg": source_mass,
        "source_label_measure_only": True,
        "sidecar": _relative(sidecar_path),
        "sidecar_audit": sidecar_summary,
    }
    return InputSnapshot(
        hdf5_path=hdf5_path,
        sidecar_path=sidecar_path,
        case_id=resolved_case_id,
        time=arrays["time"],
        identity=arrays["identity"],
        initial_fluid_indices=initial_fluid_indices,
        initial_position=initial_position,
        initial_mass=arrays["mass"][0, initial_fluid_indices],
        initial_source_labels=initial_labels,
        # Keep the full HDF5 particle axis here: seed reference_index is a
        # global HDF5 slot, not a compact initial-fluid ordinal.  This avoids
        # silently checking the wrong identity when boundary/floating slots
        # precede fluid slots in a future export.
        solver_valid=arrays["valid"] & (arrays["ptype"] == FLUID_TYPE),
        particle_spacing_m=float(metadata["particle_spacing_m"]),
        input_summary=summary,
    )


def _farthest_indices(points: np.ndarray, count: int) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if count >= len(points):
        return np.arange(len(points), dtype=np.int64)
    center = points.mean(axis=0)
    first = int(np.argmin(np.linalg.norm(points - center, axis=1)))
    chosen = [first]
    nearest2 = np.sum((points - points[first]) ** 2, axis=1)
    for _ in range(1, count):
        next_index = int(np.argmax(nearest2))
        chosen.append(next_index)
        nearest2 = np.minimum(nearest2, np.sum((points - points[next_index]) ** 2, axis=1))
    return np.asarray(chosen, dtype=np.int64)


def _layer_quotas(labels: np.ndarray, masses: np.ndarray, count: int) -> dict[str, int]:
    if count < len(SOURCE_LABELS):
        raise ValueError("seed count must cover all three source layers")
    layer_mass = np.asarray([masses[labels == label].sum() for label in SOURCE_LABELS], dtype=float)
    if np.any(layer_mass <= 0.0):
        raise ValueError("all three source layers must contain positive initial mass")
    raw = count * layer_mass / layer_mass.sum()
    quotas = np.maximum(1, np.floor(raw).astype(int))
    while int(quotas.sum()) < count:
        residual = raw - quotas
        quotas[int(np.argmax(residual))] += 1
    while int(quotas.sum()) > count:
        removable = np.where(quotas > 1, quotas - raw, -np.inf)
        quotas[int(np.argmax(removable))] -= 1
    return {label: int(quota) for label, quota in zip(SOURCE_LABELS, quotas)}


def select_weighted_seeds(snapshot: InputSnapshot, count: int, config_id: str) -> dict[str, Any]:
    """Select layer-stratified seeds and assign exact initial mass weights."""
    count = int(count)
    candidate_count = len(snapshot.initial_fluid_indices)
    if count > candidate_count:
        raise ValueError(f"requested {count} seeds but input has only {candidate_count} initial fluid particles")
    labels = snapshot.initial_source_labels
    positions = snapshot.initial_position
    masses = snapshot.initial_mass
    quotas = _layer_quotas(labels, masses, count)
    selected_local: list[int] = []
    weights: list[float] = []
    selected_labels: list[str] = []
    for label in SOURCE_LABELS:
        group = np.flatnonzero(labels == label)
        chosen_local = group[_farthest_indices(positions[group], quotas[label])]
        delta = positions[group, None, :] - positions[chosen_local][None, :, :]
        assignment = np.argmin(np.sum(delta * delta, axis=2), axis=1)
        group_weights = np.bincount(assignment, weights=masses[group], minlength=len(chosen_local))
        selected_local.extend(chosen_local.tolist())
        weights.extend(group_weights.tolist())
        selected_labels.extend([label] * len(chosen_local))
    selected_local_array = np.asarray(selected_local, dtype=np.int64)
    reference_indices = snapshot.initial_fluid_indices[selected_local_array]
    reference_identity = snapshot.identity[reference_indices]
    tracer_ids = [
        f"{snapshot.case_id}|{config_id}|seed={index:04d}|zone={int(zone)}|id={int(pid)}"
        for index, (zone, pid) in enumerate(reference_identity)
    ]
    if len(set(tracer_ids)) != len(tracer_ids):
        raise ValueError("duplicate tracer_id generated")
    represented_mass = float(np.sum(weights, dtype=np.float64))
    initial_mass = float(np.sum(snapshot.initial_mass, dtype=np.float64))
    if not np.isclose(represented_mass, initial_mass, atol=1e-8, rtol=0.0):
        raise ValueError("seed mass weights do not close to the initial fluid mass")
    return {
        "tracer_id": _string_array(tracer_ids),
        "reference_index": reference_indices,
        "reference_particle_zone": reference_identity[:, 0].astype(np.int64),
        "reference_particle_id": reference_identity[:, 1].astype(np.int64),
        "initial_position": positions[selected_local_array].astype(np.float64),
        "source_label": _string_array(selected_labels),
        "source_mk": np.asarray([], dtype=np.int64),
        "mass_weight": np.asarray(weights, dtype=np.float64),
        "represented_initial_mass_kg": represented_mass,
        "selection": "three initial-depth layers; farthest-point seeds; nearest-seed exact mass assignment within each layer",
        "layer_quotas": quotas,
    }


def _trace_array(trace: Mapping[str, Any], name: str, fallback: Any = None) -> np.ndarray:
    if name in trace:
        return np.asarray(trace[name])
    if fallback is None:
        raise ValueError(f"trace is missing {name}")
    return np.asarray(fallback)


def _derive_failure_channels(trace: Mapping[str, Any], solver_valid: np.ndarray, dp: float) -> dict[str, np.ndarray]:
    position = np.asarray(trace["position"], dtype=float)
    tracer_valid = np.asarray(
        trace["valid"] if "valid" in trace else trace["reliability_history"],
        dtype=bool,
    )
    if tracer_valid.shape != position.shape[:2]:
        raise ValueError("trace valid/reliability_history shape differs from position")
    if not tracer_valid[0].all():
        raise ValueError("all initial tracer states must be valid")
    intervals, count = position.shape[0] - 1, position.shape[1]
    if solver_valid.shape != (position.shape[0], count):
        raise ValueError("solver_valid shape differs from trace")
    wall = np.asarray(trace.get("wall_crossing", np.zeros((intervals, count), dtype=bool)), dtype=bool)
    gate = np.asarray(trace.get("support_gate_pass", np.ones((intervals, count), dtype=bool)), dtype=bool)
    support = np.asarray(trace.get("nearest_support_distance", np.zeros((intervals, count))), dtype=float)
    effective = np.asarray(trace.get("effective_sample_size", np.ones((intervals, count))), dtype=float)
    rank = np.asarray(trace.get("support_geometry_rank", np.ones((intervals, count))), dtype=float)
    anisotropy = np.asarray(trace.get("support_anisotropy", np.ones((intervals, count))), dtype=float)
    reconstruction = np.asarray(trace.get("interpolation_reconstruction_error_mps", np.zeros((intervals, count))), dtype=float)
    for name, array in {"wall_crossing": wall, "support_gate_pass": gate, "nearest_support_distance": support,
                        "effective_sample_size": effective, "support_geometry_rank": rank,
                        "support_anisotropy": anisotropy, "interpolation_reconstruction_error_mps": reconstruction}.items():
        if array.shape != (intervals, count):
            raise ValueError(f"trace {name} must have shape [T-1,Q]")
    max_support = float(trace.get("maximum_support_distance", 1.75 * float(dp)))
    reason = np.full((intervals, count), "none", dtype=object)
    prior_failure = np.zeros(count, dtype=bool)
    for step in range(intervals):
        already_invalid = (~tracer_valid[step]) | (~solver_valid[step]) | prior_failure
        reason[step, already_invalid] = "censored_after_first_failure"
        active = ~already_invalid
        reason[step, active & wall[step]] = "wall_crossing"
        active &= ~wall[step]
        finite_support = (
            np.isfinite(support[step]) & np.isfinite(effective[step]) &
            np.isfinite(rank[step]) & np.isfinite(anisotropy[step]) &
            np.isfinite(reconstruction[step])
        )
        reason[step, active & ~finite_support] = "support_nonfinite"
        active &= finite_support
        reason[step, active & (support[step] > max_support)] = "support_distance_exceedance"
        active &= support[step] <= max_support
        reason[step, active & ~gate[step]] = "support_gate_failure"
        active &= gate[step]
        reason[step, active & ~solver_valid[step + 1]] = "solver_identity_missing"
        active &= solver_valid[step + 1]
        reason[step, active & ~tracer_valid[step + 1]] = "tracer_unknown"
        prior_failure |= reason[step] != "none"
    first_reason = np.full(count, "none", dtype=object)
    first_frame = np.full(count, -1, dtype=np.int64)
    for q in range(count):
        candidates = np.flatnonzero(reason[:, q] != "none")
        if len(candidates):
            first = int(candidates[0])
            first_reason[q] = reason[first, q]
            first_frame[q] = first + 1
    return {
        "tracer_valid": tracer_valid,
        "reason": reason,
        "first_reason": first_reason,
        "first_frame": first_frame,
    }


def _validate_trace_identity(trace: Mapping[str, Any], seeds: Mapping[str, Any], snapshot: InputSnapshot) -> None:
    tracer_id = np.asarray(trace.get("tracer_id", seeds["tracer_id"]), dtype=object)
    if len(tracer_id) != len(seeds["tracer_id"]) or len(set(str(value) for value in tracer_id)) != len(tracer_id):
        raise ValueError("duplicate or missing tracer_id")
    for field in ("reference_particle_zone", "reference_particle_id"):
        if field in trace and not np.array_equal(np.asarray(trace[field]), np.asarray(seeds[field])):
            raise ValueError(f"trace {field} does not match frozen seed identity")
    reference_index = np.asarray(seeds["reference_index"], dtype=np.int64)
    if len(np.unique(reference_index)) != len(reference_index):
        raise ValueError("duplicate target/reference seed index")
    expected_identity = snapshot.identity[reference_index]
    actual_identity = np.column_stack((seeds["reference_particle_zone"], seeds["reference_particle_id"]))
    if not np.array_equal(expected_identity, actual_identity):
        raise ValueError("seed reference identity mismatch")


def _classify_trace(
    trace: Mapping[str, Any],
    seeds: Mapping[str, Any],
    snapshot: InputSnapshot,
    resolved_spec: Mapping[str, Any],
    config_id: str,
    seed_count: int,
    substeps: int,
) -> dict[str, Any]:
    position = np.asarray(trace["position"], dtype=float)
    time = np.asarray(trace["time"], dtype=float)
    if position.ndim != 3 or position.shape[-1] != 3:
        raise ValueError("tracer position must have shape [T,Q,3]")
    count = position.shape[1]
    if count != len(seeds["mass_weight"]):
        raise ValueError("tracer and seed axes differ")
    if time.shape != (position.shape[0],) or not np.allclose(time, snapshot.time, atol=1e-8, rtol=0.0):
        raise ValueError("tracer time axis differs from solver HDF5")
    _validate_trace_identity(trace, seeds, snapshot)
    source_labels = np.asarray(seeds["source_label"], dtype=object)
    weights = np.asarray(seeds["mass_weight"], dtype=float)
    if source_labels.shape != (count,) or not set(str(value) for value in source_labels).issubset(set(SOURCE_LABELS)):
        raise ValueError("source_label must contain only the three frozen initial-depth labels")
    if weights.shape != (count,) or not np.all(np.isfinite(weights)) or np.any(weights <= 0.0):
        raise ValueError("mass_weight must be finite and positive")
    initial_mass = float(np.sum(snapshot.initial_mass, dtype=np.float64))
    represented_mass = float(np.sum(weights, dtype=np.float64))
    tolerance = float(resolved_spec["mass_accounting"]["closure_tolerance_kg"])
    if not np.isclose(represented_mass, initial_mass, atol=tolerance, rtol=0.0):
        raise ValueError(f"mass leak in seed weights: represented={represented_mass} initial={initial_mass}")

    solver_valid = np.asarray(snapshot.solver_valid[:, np.asarray(seeds["reference_index"], dtype=np.int64)], dtype=bool)
    dp = float(trace.get("particle_spacing_m", 0.0) or 0.0)
    if dp <= 0.0:
        maximum_support = float(trace.get("maximum_support_distance", 1.75))
        dp = maximum_support / 1.75 if maximum_support > 0.0 else 1.0
    failure = _derive_failure_channels(trace, solver_valid, dp)
    support_fields = {
        "nearest_support_distance": np.asarray(
            trace.get("nearest_support_distance", np.zeros((len(time) - 1, count))), dtype=np.float64
        ),
        "effective_sample_size": np.asarray(
            trace.get("effective_sample_size", np.ones((len(time) - 1, count))), dtype=np.float64
        ),
        "support_geometry_rank": np.asarray(
            trace.get("support_geometry_rank", np.ones((len(time) - 1, count))), dtype=np.int8
        ),
        "support_anisotropy": np.asarray(
            trace.get("support_anisotropy", np.ones((len(time) - 1, count))), dtype=np.float64
        ),
        "interpolation_reconstruction_error_mps": np.asarray(
            trace.get("interpolation_reconstruction_error_mps", np.zeros((len(time) - 1, count))), dtype=np.float64
        ),
        "minimum_visible_neighbours": np.asarray(
            trace.get("minimum_visible_neighbours", np.zeros((len(time) - 1, count))), dtype=np.int64
        ),
        "visibility_search_width": np.asarray(
            trace.get("visibility_search_width", np.zeros((len(time) - 1, count))), dtype=np.int64
        ),
        "support_gate_pass": np.asarray(
            trace.get("support_gate_pass", np.ones((len(time) - 1, count))), dtype=bool
        ),
    }
    for name, values in support_fields.items():
        if values.shape != (len(time) - 1, count):
            raise ValueError(f"trace {name} must have shape [T-1,Q]")
    tracer_valid = failure["tracer_valid"]
    task_valid = tracer_valid & solver_valid
    for q, frame in enumerate(failure["first_frame"]):
        if int(frame) >= 0:
            task_valid[int(frame):, q] = False

    destinations = list(resolved_spec["destinations"])
    domain = dict(resolved_spec["domain"])
    exits = list(resolved_spec["legitimate_exit_regions"])
    destination_mask = np.zeros((len(time), count), dtype=bool)
    destination_name = np.full((len(time), count), "none", dtype=object)
    exit_mask = np.zeros((len(time), count), dtype=bool)
    for frame in range(len(time)):
        valid_position = task_valid[frame] & np.all(np.isfinite(position[frame]), axis=1)
        hits = np.zeros((count, len(destinations)), dtype=bool)
        for index, destination in enumerate(destinations):
            hits[:, index] = valid_position & points_in_region(position[frame], destination)
        if np.any(hits.sum(axis=1) > 1):
            raise ValueError("duplicate target assignment: a tracer is in multiple destination regions")
        if hits.shape[1]:
            selected = hits.any(axis=1)
            destination_mask[frame] = selected
            for index, destination in enumerate(destinations):
                destination_name[frame, selected & hits[:, index]] = destination["name"]
        for exit_region in exits:
            exit_mask[frame] |= valid_position & points_in_region(position[frame], exit_region)
    if np.any(destination_mask & exit_mask):
        raise ValueError("duplicate target assignment: destination overlaps legitimate exit")

    first_passage_frame = np.full(count, -1, dtype=np.int64)
    first_passage_time = np.full(count, np.nan, dtype=np.float64)
    first_passage_status = np.full(count, "right_censored_end_of_window", dtype=object)
    first_passage_censored = np.zeros(count, dtype=bool)
    terminal_category = np.full(count, "numerical_loss", dtype=object)
    terminal_frame = np.full(count, -1, dtype=np.int64)
    outside_domain = np.zeros(count, dtype=bool)

    for q in range(count):
        bad = np.flatnonzero(~task_valid[:, q])
        first_bad = int(bad[0]) if len(bad) else len(time)
        event_candidates = np.flatnonzero(destination_mask[:first_bad, q])
        exit_candidates = np.flatnonzero(exit_mask[:first_bad, q])

        # First passage is an event-time task.  It is intentionally evaluated
        # only before the first invalid frame; a stale coordinate after a
        # tracer/solver failure cannot invent an observed arrival.
        if len(event_candidates):
            event = int(event_candidates[0])
            first_passage_frame[q] = event
            first_passage_time[q] = time[event]
            first_passage_status[q] = "observed"
        elif len(exit_candidates):
            first_passage_status[q] = "legitimate_exit_before_target"
        elif first_bad < len(time):
            first_reason = str(failure["first_reason"][q])
            if first_reason == "solver_identity_missing":
                first_passage_status[q] = "censored_by_numerical_loss"
            else:
                first_passage_status[q] = "censored_by_tracer_failure"
            first_passage_censored[q] = True
        else:
            first_passage_censored[q] = True

        # Terminal category is a separate final-state task.  In particular,
        # arrival followed by later return is ``first_passage=observed`` but
        # terminal_category=domain (or another final region); arrival followed
        # by failure is observed historically but has unknown final outcome.
        if first_bad < len(time):
            terminal_frame[q] = first_bad - 1
            terminal_category[q] = (
                "numerical_loss"
                if str(failure["first_reason"][q]) == "solver_identity_missing"
                else "tracer_unknown"
            )
        else:
            terminal_frame[q] = len(time) - 1
            final_position = position[-1, q]
            if not np.all(np.isfinite(final_position)):
                terminal_category[q] = "numerical_loss"
            elif points_in_region(final_position[None, :], destinations[0])[0]:
                terminal_category[q] = "target"
            elif exits and any(points_in_region(final_position[None, :], region)[0] for region in exits):
                terminal_category[q] = "legitimate_exit"
            elif points_in_region(final_position[None, :], domain)[0]:
                terminal_category[q] = "domain"
            else:
                outside_domain[q] = True
                terminal_category[q] = "numerical_loss"

    # If an event was observed before a later failure, it remains an observed
    # event; the terminal task outcome is target/exit, not an invented failure.
    # Conversely, a failure before an event is explicitly censored and never
    # converted into a negative first-passage label.
    categories = {category: float(np.sum(weights[terminal_category == category], dtype=np.float64))
                  for category in TERMINAL_CATEGORIES}
    category_sum = float(sum(categories.values()))
    closure_error = category_sum - initial_mass
    if not np.isclose(closure_error, 0.0, atol=tolerance, rtol=0.0):
        raise ValueError(f"terminal mass ledger is not closed: error={closure_error}")

    source_mass = {label: float(np.sum(weights[source_labels == label], dtype=np.float64)) for label in SOURCE_LABELS}
    by_source: dict[str, Any] = {}
    for label in SOURCE_LABELS:
        mask = source_labels == label
        label_categories = {category: float(np.sum(weights[mask & (terminal_category == category)], dtype=np.float64))
                            for category in TERMINAL_CATEGORIES}
        label_initial = float(snapshot.input_summary["source_label_mass_kg"][label])
        label_error = sum(label_categories.values()) - label_initial
        if not np.isclose(label_error, 0.0, atol=tolerance, rtol=0.0):
            raise ValueError(f"source layer mass ledger is not closed for {label}: error={label_error}")
        by_source[label] = {
            "initial_mass_kg": label_initial,
            "represented_seed_mass_kg": source_mass[label],
            "categories_kg": label_categories,
            "fractions_of_initial_mass": {
                category: value / max(label_initial, 1e-30) for category, value in label_categories.items()
            },
        }

    finite_support = support_fields["nearest_support_distance"][np.isfinite(support_fields["nearest_support_distance"])]
    finite_effective = support_fields["effective_sample_size"][np.isfinite(support_fields["effective_sample_size"])]
    support_summary = {
        "maximum_support_distance_m": float(trace.get("maximum_support_distance", 1.75 * dp)),
        "minimum_observed_support_distance_m": float(np.min(finite_support)) if finite_support.size else None,
        "maximum_observed_support_distance_m": float(np.max(finite_support)) if finite_support.size else None,
        "minimum_effective_sample_size": float(np.min(finite_effective)) if finite_effective.size else None,
        "support_gate_failure_intervals": int(np.sum(~support_fields["support_gate_pass"])),
        "minimum_visible_candidate_neighbours": int(np.min(support_fields["minimum_visible_neighbours"])) if support_fields["minimum_visible_neighbours"].size else None,
        "visibility_search_width_max": int(np.max(support_fields["visibility_search_width"])) if support_fields["visibility_search_width"].size else None,
        "visibility_mode": str(trace.get("visibility_mode", "unknown")),
    }
    return {
        "config_id": config_id,
        "seed_count": int(seed_count),
        "substeps": int(substeps),
        "status": "completed",
        "tracer_id": np.asarray(seeds["tracer_id"], dtype=object),
        "reference_particle_zone": np.asarray(seeds["reference_particle_zone"], dtype=np.int64),
        "reference_particle_id": np.asarray(seeds["reference_particle_id"], dtype=np.int64),
        "source_label": source_labels,
        "mass_weight": weights,
        "time": time,
        "position": position,
        "valid": task_valid,
        "tracer_valid": tracer_valid,
        "solver_identity_valid": solver_valid,
        "failure_reason": failure["reason"],
        "first_failure_reason": failure["first_reason"],
        "first_failure_frame": failure["first_frame"],
        "first_failure_time": np.asarray([
            time[frame] if frame >= 0 else np.nan for frame in failure["first_frame"]
        ], dtype=np.float64),
        "in_destination": destination_mask,
        "destination_name": destination_name,
        "first_passage_frame": first_passage_frame,
        "first_passage_time": first_passage_time,
        "first_passage_status": first_passage_status,
        "first_passage_censored": first_passage_censored,
        "terminal_category": terminal_category,
        "final_category": terminal_category.copy(),
        "terminal_frame": terminal_frame,
        "outside_domain": outside_domain,
        **support_fields,
        "support_diagnostics": support_summary,
        "summary": {
            "config_id": config_id,
            "seed_count": int(seed_count),
            "substeps": int(substeps),
            "status": "completed",
            "tracer_reliable_final_fraction_by_count": float(np.mean(tracer_valid[-1])),
            "tracer_reliable_final_fraction_by_initial_mass": float(
                np.sum(weights * tracer_valid[-1], dtype=np.float64) / max(initial_mass, 1e-30)
            ),
            "support_diagnostics": support_summary,
            "material_task_valid_final_fraction_by_count": float(np.mean(task_valid[-1])),
            "material_task_valid_final_fraction_by_initial_mass": float(
                np.sum(weights * task_valid[-1], dtype=np.float64) / max(initial_mass, 1e-30)
            ),
            "wall_crossing_events": int(np.sum(failure["reason"] == "wall_crossing")),
            "failure_reason_counts": {
                reason: int(np.sum(failure["reason"] == reason)) for reason in FAILURE_REASONS if np.any(failure["reason"] == reason)
            },
            "first_failure_counts": {
                reason: int(np.sum(failure["first_reason"] == reason))
                for reason in FAILURE_REASONS if np.any(failure["first_reason"] == reason)
            },
            "first_passage_status_counts": {
                status: int(np.sum(first_passage_status == status)) for status in FIRST_PASSAGE_STATUSES
                if np.any(first_passage_status == status)
            },
            "first_passage_status_mass_kg": {
                status: float(np.sum(weights[first_passage_status == status], dtype=np.float64))
                for status in FIRST_PASSAGE_STATUSES
            },
            "first_passage_status_mass_fractions": {
                status: float(np.sum(weights[first_passage_status == status], dtype=np.float64) / max(initial_mass, 1e-30))
                for status in FIRST_PASSAGE_STATUSES
            },
            "terminal_category_counts": {
                category: int(np.sum(terminal_category == category)) for category in TERMINAL_CATEGORIES
            },
            "final_category_counts": {
                category: int(np.sum(terminal_category == category)) for category in TERMINAL_CATEGORIES
            },
            "mass_accounting": {
                "initial_mass_kg": initial_mass,
                "categories_kg": categories,
                "fractions_of_initial_mass": {
                    category: value / max(initial_mass, 1e-30) for category, value in categories.items()
                },
                "closure_error_kg": float(closure_error),
                "by_source_label": by_source,
                "denominator": "initial valid fluid mass; no survivor renormalization",
            },
            "checks": {
                "identity_unique": True,
                "reference_identity_match": True,
                "destination_disjoint": True,
                "mass_closed": bool(np.isclose(closure_error, 0.0, atol=tolerance, rtol=0.0)),
                "wall_policy_explicit": True,
                "tracer_failure_is_censored": True,
                "source_label_measure_only": True,
                "first_passage_requires_valid": True,
                "support_diagnostics_present": True,
            },
        },
    }


def write_trajectory_bundle(path: Path, result: Mapping[str, Any], resolved_spec: Mapping[str, Any], hashes: Mapping[str, str]) -> None:
    """Persist the full trace/evaluator contract in a self-contained HDF5."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(path, "w") as h5:
        h5.attrs["schema_version"] = OUTPUT_SCHEMA_VERSION
        h5.attrs["case_id"] = resolved_spec.get("resolved_case_id", "unknown")
        h5.attrs["transport_spec_id"] = resolved_spec["spec_id"]
        h5.attrs["transport_spec_version"] = resolved_spec["version"]
        h5.attrs["transport_spec_sha256"] = hashes["transport_spec_sha256"]
        h5.attrs["input_hdf5_sha256"] = hashes["input_hdf5_sha256"]
        h5.attrs["input_sidecar_sha256"] = hashes["input_sidecar_sha256"]
        h5.attrs["evaluator_sha256"] = hashes["evaluator_sha256"]
        h5.attrs["source_label_measure_only"] = True
        h5.attrs["mass_denominator"] = "initial_valid_fluid_mass"
        h5.attrs["censoring_semantics"] = "tracer failure is unknown/censored, never a negative event"
        h5.attrs["destination_semantics"] = (
            "first_passage is first valid arrival; final_category is the last valid state, "
            "or unknown when failure occurs after any earlier arrival"
        )

        h5.create_dataset("tracer_id", data=np.asarray(result["tracer_id"], dtype=object), dtype=string_dtype)
        h5.create_dataset("time", data=np.asarray(result["time"], dtype=np.float64))
        h5.create_dataset("position", data=np.asarray(result["position"], dtype=np.float64), compression="gzip")
        h5.create_dataset("valid", data=np.asarray(result["valid"], dtype=bool), compression="gzip")
        h5.create_dataset("tracer_valid", data=np.asarray(result["tracer_valid"], dtype=bool), compression="gzip")
        h5.create_dataset("solver_identity_valid", data=np.asarray(result["solver_identity_valid"], dtype=bool), compression="gzip")
        h5.create_dataset("source_label", data=np.asarray(result["source_label"], dtype=object), dtype=string_dtype)
        h5.create_dataset("mass_weight", data=np.asarray(result["mass_weight"], dtype=np.float64))
        h5.create_dataset("reference_particle_zone", data=np.asarray(result["reference_particle_zone"], dtype=np.int64))
        h5.create_dataset("reference_particle_id", data=np.asarray(result["reference_particle_id"], dtype=np.int64))

        support = h5.create_group("support")
        support.create_dataset("nearest_support_distance", data=np.asarray(result["nearest_support_distance"], dtype=np.float64), compression="gzip")
        support.create_dataset("effective_sample_size", data=np.asarray(result["effective_sample_size"], dtype=np.float64), compression="gzip")
        support.create_dataset("geometry_rank", data=np.asarray(result["support_geometry_rank"], dtype=np.int8), compression="gzip")
        support.create_dataset("anisotropy", data=np.asarray(result["support_anisotropy"], dtype=np.float64), compression="gzip")
        support.create_dataset("interpolation_reconstruction_error_mps", data=np.asarray(result["interpolation_reconstruction_error_mps"], dtype=np.float64), compression="gzip")
        support.create_dataset("minimum_visible_neighbours", data=np.asarray(result["minimum_visible_neighbours"], dtype=np.int64), compression="gzip")
        support.create_dataset("visibility_search_width", data=np.asarray(result["visibility_search_width"], dtype=np.int64), compression="gzip")
        support.create_dataset("gate_pass", data=np.asarray(result["support_gate_pass"], dtype=bool), compression="gzip")
        for key, value in result["support_diagnostics"].items():
            if value is not None:
                support.attrs[key] = value

        failure = h5.create_group("failure")
        failure.create_dataset("reason", data=np.asarray(result["failure_reason"], dtype=object), dtype=string_dtype)
        failure.create_dataset("first_reason", data=np.asarray(result["first_failure_reason"], dtype=object), dtype=string_dtype)
        failure.create_dataset("first_frame", data=np.asarray(result["first_failure_frame"], dtype=np.int64))
        failure.create_dataset("first_time", data=np.asarray(result["first_failure_time"], dtype=np.float64))

        destination = h5.create_group("destination")
        destination.create_dataset("in_destination", data=np.asarray(result["in_destination"], dtype=bool), compression="gzip")
        destination.create_dataset("name", data=np.asarray(result["destination_name"], dtype=object), dtype=string_dtype)
        destination.create_dataset("first_passage_frame", data=np.asarray(result["first_passage_frame"], dtype=np.int64))
        destination.create_dataset("first_passage_time", data=np.asarray(result["first_passage_time"], dtype=np.float64))
        destination.create_dataset("first_passage_status", data=np.asarray(result["first_passage_status"], dtype=object), dtype=string_dtype)
        destination.create_dataset("first_passage_censored", data=np.asarray(result["first_passage_censored"], dtype=bool))
        destination.create_dataset("terminal_category", data=np.asarray(result["terminal_category"], dtype=object), dtype=string_dtype)
        destination.create_dataset("final_category", data=np.asarray(result["final_category"], dtype=object), dtype=string_dtype)
        destination.create_dataset("terminal_frame", data=np.asarray(result["terminal_frame"], dtype=np.int64))
        destination.create_dataset("outside_domain", data=np.asarray(result["outside_domain"], dtype=bool))


def _json_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return dict(result["summary"])


def run_bounded(
    hdf5_path: Path,
    sidecar_path: Path,
    *,
    case_id: str | None = None,
    particle_spacing_m: float | None = None,
    source_z_bounds_m: Sequence[float] | None = None,
    spec_path: Path = DEFAULT_SPEC,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    seed_counts: Sequence[int] = DEFAULT_SEED_COUNTS,
    substeps: Sequence[int] = DEFAULT_SUBSTEPS,
) -> dict[str, Any]:
    """Run at most eight CPU tracer groups on one actual F1 HDF5 pair."""
    spec = load_transport_spec(Path(spec_path))
    pairs = [(int(count), int(step)) for count in seed_counts for step in substeps]
    if not pairs or len(pairs) > MAX_CONFIGURATIONS:
        raise ValueError(f"bounded material run requires 1..{MAX_CONFIGURATIONS} configurations")
    if len(set(pairs)) != len(pairs):
        raise ValueError("bounded material run configurations must be unique")
    if any(count < len(SOURCE_LABELS) or step < 1 for count, step in pairs):
        raise ValueError("seed counts must cover three layers and substeps must be positive")
    snapshot = load_input_snapshot(
        Path(hdf5_path), Path(sidecar_path), spec,
        case_id=case_id, particle_spacing_m=particle_spacing_m,
        source_z_bounds_m=source_z_bounds_m,
    )
    resolved_spec = _resolved_spec(
        spec,
        snapshot.input_summary["initial_z_bounds_m"][0],
        snapshot.input_summary["initial_z_bounds_m"][1],
        snapshot.case_id,
    )
    spec_hash = _sha256_bytes(_canonical_json(resolved_spec))
    evaluator_hash = _sha256_file(Path(__file__).resolve())
    hashes = {
        "input_hdf5_sha256": snapshot.input_summary["hdf5_sha256"],
        "input_sidecar_sha256": snapshot.input_summary["sidecar_sha256"],
        "transport_spec_sha256": spec_hash,
        "evaluator_sha256": evaluator_hash,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    barrier = _material_barrier_provider(snapshot.sidecar_path, spec)
    configurations: list[dict[str, Any]] = []
    mass_by_config: dict[str, Any] = {}
    all_checks: list[dict[str, Any]] = []
    for count, step in pairs:
        config_id = f"{snapshot.case_id}_seeds{count}_substeps{step}"
        seeds = select_weighted_seeds(snapshot, count, config_id)
        trace = advect_hdf5(
            snapshot.hdf5_path,
            seeds["initial_position"],
            neighbours=24,
            regularization=0.1 * snapshot.particle_spacing_m,
            maximum_support_distance=1.75 * snapshot.particle_spacing_m,
            frame_stride=1,
            substeps_per_interval=step,
            barrier_provider=barrier,
        )
        trace = dict(trace)
        trace["tracer_id"] = seeds["tracer_id"]
        trace["reference_particle_zone"] = seeds["reference_particle_zone"]
        trace["reference_particle_id"] = seeds["reference_particle_id"]
        trace["particle_spacing_m"] = snapshot.particle_spacing_m
        trace["maximum_support_distance"] = 1.75 * trace["particle_spacing_m"]
        result = _classify_trace(trace, seeds, snapshot, resolved_spec, config_id, count, step)
        bundle_path = output_dir / f"{config_id}.h5"
        write_trajectory_bundle(bundle_path, result, resolved_spec, hashes)
        summary = _json_summary(result)
        summary["trajectory_bundle"] = _relative(bundle_path)
        summary["trajectory_bundle_sha256"] = _sha256_file(bundle_path)
        summary["trajectory_bundle_bytes"] = bundle_path.stat().st_size
        configurations.append(summary)
        mass_by_config[config_id] = summary["mass_accounting"]
        all_checks.append(summary["checks"])

    checks = {
        key: bool(all(item.get(key, False) for item in all_checks))
        for key in sorted({key for item in all_checks for key in item})
    }
    report = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": "R5_F1_MATERIAL_TASK",
        "execution_status": "completed",
        "acceptance_status": "candidate_only_not_physical_acceptance",
        "formal_material_target_admitted": False,
        "scope": f"bounded CPU source-layer material task on one F1 {spec.get('case_variant')} trajectory",
        "transport_spec": resolved_spec,
        "input": snapshot.input_summary,
        "hashes": hashes,
        "controls": {
            "seed_counts": sorted({count for count, _ in pairs}),
            "substeps": sorted({step for _, step in pairs}),
            "configuration_count": len(pairs),
            "max_configurations": MAX_CONFIGURATIONS,
            "solver_rerun": False,
            "gencase_rerun": False,
            "cuda_used": False,
            "gpu_used": False,
            "wall_provider": "release finite-triangle sidecar via boundary_sidecars.sidecar_provider",
            "visibility_provider": getattr(barrier, "visibility_filter", "full sidecar"),
            "collision_provider": "full finite sidecar; tank and obstacle components retained for swept wall crossing",
        },
        "configurations": configurations,
        "mass_accounting": {
            "denominator_kg": snapshot.input_summary["initial_fluid_mass_kg"],
            "initial_mass_kg": snapshot.input_summary["initial_fluid_mass_kg"],
            "categories": list(TERMINAL_CATEGORIES),
            "no_survivor_renormalization": True,
            "closure_error_kg": {
                config_id: values["closure_error_kg"] for config_id, values in mass_by_config.items()
            },
            "per_configuration": mass_by_config,
        },
        "checks": checks,
        "open_blockers": [
            "source_label is an initial-depth measurement stratum, not a physical material identity",
            "source layers use declared continuous initial-fluid bounds; discrete particle extrema are recorded separately",
            "formal destination and wall acceptance still require physical/reference validation",
            "solver-exported material identity is still numerical-node identity; the task reports solver identity loss separately",
        ],
    }
    report_path = output_dir / "r5-f1-material-task.json"
    report["report"] = _relative(report_path)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _preferred_hdf5_candidates(level: str | None = None) -> list[Path]:
    """Return explicit medium/fine-first discovery candidates for handoff."""
    names = ["medium", "fine"] if level is None else [str(level)]
    candidates: list[Path] = []
    for item in names:
        candidates.extend([
            CAMPAIGN / "data" / f"R4_F1_center_obstacle_{item}.h5",
            CAMPAIGN / "data" / f"F1_center_obstacle_{item}.h5",
            CAMPAIGN / "data" / f"R5_F1_center_obstacle_{item}.h5",
        ])
    return candidates


def audit_contract(spec_path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = load_transport_spec(Path(spec_path))
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "execution_status": "contract_ready",
        "acceptance_status": "not_run",
        "transport_spec": {
            "spec_id": spec["spec_id"],
            "version": spec["version"],
            "source_label_measure_only": spec["sources"]["measure_only"],
            "wall_components": sorted(spec["wall"]["component_roles"]),
            "destination": spec["destinations"][0]["name"],
        },
        "preferred_input_candidates": [str(path) for path in _preferred_hdf5_candidates()],
        "run_command_shape": "python scripts/r5_f1_material_task.py run --hdf5 <F1-medium-or-fine.h5> --sidecar <linked-sidecar.h5>",
        "bounded_matrix": {
            "seed_counts": list(DEFAULT_SEED_COUNTS),
            "substeps": list(DEFAULT_SUBSTEPS),
            "max_configurations": MAX_CONFIGURATIONS,
        },
        "no_solver_or_gpu": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "run"), nargs="?", default="audit")
    parser.add_argument("--hdf5", type=Path)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--particle-spacing", type=float,
                        help="override particle spacing when the HDF5 lacks particle_spacing_m/dp")
    parser.add_argument("--source-z-bounds", type=float, nargs=2, metavar=("Z_MIN", "Z_MAX"),
                        help="declared continuous initial-fluid z bounds used for source layers")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed-counts", type=int, nargs="+", default=list(DEFAULT_SEED_COUNTS))
    parser.add_argument("--substeps", type=int, nargs="+", default=list(DEFAULT_SUBSTEPS))
    args = parser.parse_args()
    if args.action == "audit":
        print(json.dumps(audit_contract(args.spec), indent=2, ensure_ascii=False))
        return
    if args.hdf5 is None or args.sidecar is None:
        parser.error("run requires both --hdf5 and --sidecar")
    report = run_bounded(
        args.hdf5,
        args.sidecar,
        case_id=args.case_id,
        particle_spacing_m=args.particle_spacing,
        source_z_bounds_m=args.source_z_bounds,
        spec_path=args.spec,
        output_dir=args.output_dir,
        seed_counts=args.seed_counts,
        substeps=args.substeps,
    )
    print(json.dumps({
        "execution_status": report["execution_status"],
        "acceptance_status": report["acceptance_status"],
        "configurations": len(report["configurations"]),
        "report": report["report"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
