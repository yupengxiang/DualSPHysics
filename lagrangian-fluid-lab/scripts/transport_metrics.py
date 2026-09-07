#!/usr/bin/env python3
"""Mass-conservative source-to-destination metrics in explicit coordinate frames."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


def _finite_vector(region: dict, name: str) -> np.ndarray:
    if name not in region:
        raise ValueError(f"{region.get('type', 'region')} destination requires {name}")
    try:
        value = np.asarray(region[name], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"region {name} must be numeric") from exc
    if value.shape != (3,) or not np.all(np.isfinite(value)):
        raise ValueError(f"region {name} must be a finite length-3 vector")
    return value


def _validate_region(region: dict, *, role: str) -> None:
    if not isinstance(region, dict):
        raise ValueError(f"{role} must be an object")
    name = region.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{role} name must be a non-empty string")
    kind = region.get("type")
    if kind not in {"aabb", "halfspace", "sphere"}:
        raise ValueError(f"{role} has unsupported region type: {kind!r}")
    if kind == "aabb":
        lower = _finite_vector(region, "min")
        upper = _finite_vector(region, "max")
        if np.any(upper < lower):
            raise ValueError(f"{role} max must be greater than or equal to min")
    elif kind == "halfspace":
        normal = _finite_vector(region, "normal")
        if np.linalg.norm(normal) <= 0:
            raise ValueError(f"{role} normal must be non-zero")
        offset = region.get("offset")
        if not isinstance(offset, (int, float, np.integer, np.floating)) or not np.isfinite(offset):
            raise ValueError(f"{role} offset must be finite")
        if region.get("side") not in {"le", "ge"}:
            raise ValueError(f"{role} side must be explicitly 'le' or 'ge'")
    else:
        _finite_vector(region, "center")
        radius = region.get("radius")
        if not isinstance(radius, (int, float, np.integer, np.floating)) or not np.isfinite(radius) or radius <= 0:
            raise ValueError(f"{role} radius must be finite and positive")


def _validate_frame(frame: dict, *, role: str) -> None:
    if not isinstance(frame, dict):
        raise ValueError(f"{role} must be an object")
    kind = frame.get("kind")
    if kind == "world":
        return
    if kind == "moving_affine":
        dataset = frame.get("world_from_frame_dataset")
        if not isinstance(dataset, str) or not dataset.strip():
            raise ValueError(f"{role} moving_affine requires world_from_frame_dataset")
        return
    raise ValueError(f"{role} has unsupported kind: {kind!r}")


def validate_transport_spec(spec: dict) -> None:
    """Reject ambiguous destination geometry before touching a trajectory.

    The original metric implementation accepted a destination with missing
    geometry fields and relied on implicit defaults.  That is unsafe for a
    material-history benchmark: an omitted half-space side or an inverted box
    can silently change the mass allocation.  This validator is deliberately
    dependency-free and mirrors the JSON schema shipped in ``protocol/``.
    """
    if not isinstance(spec, dict):
        raise ValueError("transport specification must be an object")
    if spec.get("lifecycle_model") not in {"closed", "open"}:
        raise ValueError("lifecycle_model must be explicitly 'closed' or 'open'")
    _validate_frame(spec.get("destination_frame"), role="destination_frame")

    sources = spec.get("sources", {"mode": "mk"})
    if not isinstance(sources, dict):
        raise ValueError("sources must be an object")
    mode = sources.get("mode", "mk")
    if mode not in {"mk", "regions"}:
        raise ValueError(f"unsupported source mode: {mode!r}")
    if "frame" in sources:
        _validate_frame(sources["frame"], role="sources.frame")
    if mode == "regions":
        source_regions = sources.get("regions")
        if not isinstance(source_regions, list) or not source_regions:
            raise ValueError("sources.regions must be a non-empty list")
        source_names = []
        for index, region in enumerate(source_regions):
            _validate_region(region, role=f"sources.regions[{index}]")
            source_names.append(region["name"])
        if len(source_names) != len(set(source_names)):
            raise ValueError("source region names must be unique")

    destinations = spec.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("destinations must be a non-empty list")
    names = []
    for index, region in enumerate(destinations):
        _validate_region(region, role=f"destinations[{index}]")
        names.append(region["name"])
    if len(names) != len(set(names)):
        raise ValueError("destination region names must be unique")

    exit_reason_names = spec.get("exit_reason_names")
    if exit_reason_names is not None:
        if not isinstance(exit_reason_names, dict) or any(
            not isinstance(name, str) or not name.strip() for name in exit_reason_names.values()
        ):
            raise ValueError("exit_reason_names must map codes to non-empty strings")


def points_in_region(points, region):
    kind = region["type"]
    if kind == "aabb":
        lower = np.asarray(region["min"], dtype=float)
        upper = np.asarray(region["max"], dtype=float)
        return np.all((points >= lower) & (points <= upper), axis=1)
    if kind == "halfspace":
        normal = np.asarray(region["normal"], dtype=float)
        signed = points @ normal - float(region["offset"])
        return signed <= 0 if region.get("side", "le") == "le" else signed >= 0
    if kind == "sphere":
        center = np.asarray(region["center"], dtype=float)
        return np.linalg.norm(points - center, axis=1) <= float(region["radius"])
    raise ValueError(f"unsupported region type: {kind}")


def positions_in_frame(h5, positions, frame_index, frame_spec):
    kind = frame_spec.get("kind", "world")
    if kind == "world":
        return positions
    if kind == "moving_affine":
        dataset = frame_spec.get("world_from_frame_dataset")
        if not dataset or dataset not in h5:
            raise ValueError(f"moving frame transform dataset is unavailable: {dataset!r}")
        world_from_frame = h5[dataset][frame_index]
        if world_from_frame.shape != (4, 4):
            raise ValueError("moving frame transform must have shape [T,4,4]")
        frame_from_world = np.linalg.inv(world_from_frame)
        homogeneous = np.column_stack((positions, np.ones(len(positions))))
        return (homogeneous @ frame_from_world.T)[:, :3]
    raise ValueError(f"unsupported coordinate frame: {kind}")


def source_masks(h5, spec, initial_fluid):
    sources = spec.get("sources", {"mode": "mk"})
    if sources.get("mode") == "mk":
        mk = h5["mk"][0]
        return {str(int(value)): initial_fluid & (mk == value)
                for value in np.unique(mk[initial_fluid])}
    if sources.get("mode") == "regions":
        points = positions_in_frame(h5, h5["position"][0], 0, sources.get("frame", {"kind": "world"}))
        return {region["name"]: initial_fluid & points_in_region(points, region)
                for region in sources["regions"]}
    raise ValueError(f"unsupported source mode: {sources.get('mode')}")


def audit_transport(h5_path, spec):
    """Classify all initial fluid mass; never renormalize onto final survivors."""
    validate_transport_spec(spec)
    with h5py.File(Path(h5_path), "r") as h5:
        initial_valid = h5["valid"][0]
        final_valid = h5["valid"][-1]
        initial_fluid = initial_valid & (h5["type"][0] == 3)
        initial_mass = h5["mass"][0]
        final_positions = h5["position"][-1]
        frame_spec = spec.get("destination_frame", {"kind": "world"})
        transformed = positions_in_frame(h5, final_positions, len(h5["time"]) - 1, frame_spec)
        sources = source_masks(h5, spec, initial_fluid)
        lifecycle = spec.get("lifecycle_model", "closed")
        reports = {}
        for source_name, source in sources.items():
            denominator = float(np.nansum(initial_mass[source]))
            unassigned = source & final_valid
            mass_by_category = {}
            for region in spec.get("destinations", []):
                selected = unassigned & points_in_region(transformed, region)
                mass_by_category[region["name"]] = float(np.nansum(initial_mass[selected]))
                unassigned &= ~selected
            mass_by_category["in_domain_unclassified"] = float(np.nansum(initial_mass[unassigned]))
            missing = source & ~final_valid
            missing_name = "numerical_loss" if lifecycle == "closed" else "unknown_exit"
            if "lifecycle_exit_reason" in h5:
                reasons = h5["lifecycle_exit_reason"][:]
                reason_names = spec.get("exit_reason_names", {})
                for code in np.unique(reasons[missing]):
                    name = reason_names.get(str(int(code)), f"exit_reason_{int(code)}")
                    mass_by_category[name] = float(np.nansum(initial_mass[missing & (reasons == code)]))
            else:
                mass_by_category[missing_name] = float(np.nansum(initial_mass[missing]))
            accounted = sum(mass_by_category.values())
            reports[source_name] = {
                "initial_count": int(source.sum()), "initial_mass_kg": denominator,
                "mass_kg": mass_by_category,
                "mass_fraction": {name: mass / max(denominator, 1e-30)
                                  for name, mass in mass_by_category.items()},
                "closure_error_kg": accounted - denominator,
            }
        return {
            "schema_version": 1, "case_id": h5.attrs.get("case_id", "unknown"),
            "coordinate_frame": frame_spec, "lifecycle_model": lifecycle,
            "sources": reports,
        }
