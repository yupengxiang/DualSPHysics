#!/usr/bin/env python3
"""Mass-conservative source-to-destination metrics in explicit coordinate frames."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


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
