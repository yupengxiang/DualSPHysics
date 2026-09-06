#!/usr/bin/env python3
"""Audit particle lifecycles in open-boundary and variable-resolution HDF5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


def _episodes(row: np.ndarray) -> int:
    padded = np.r_[False, row, False].astype(np.int8)
    return int(np.sum(np.diff(padded) == 1))


def audit_hdf5(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        valid = h5["valid"][:]
        mass = h5["mass"][:]
        particle_type = h5["type"][:]
        particle_id = h5["particle_id"][:]
        zone = h5["particle_zone"][:]
        time = h5["time"][:]
        fluid_valid = valid & (particle_type == 3)
        ever = valid.any(axis=0)
        initial = valid[0]
        final = valid[-1]
        episode_counts = np.asarray([_episodes(valid[:, i]) for i in range(valid.shape[1])])
        compound = np.column_stack((zone, particle_id))

        zones = {}
        for zone_value in np.unique(zone):
            slots = zone == zone_value
            zone_fluid = fluid_valid[:, slots]
            zone_mass = mass[:, slots]
            mass_values = np.unique(zone_mass[zone_fluid])
            zones[str(int(zone_value))] = {
                "identity_slots": int(slots.sum()),
                "valid_particles_per_frame": valid[:, slots].sum(axis=1).astype(int).tolist(),
                "fluid_particles_per_frame": zone_fluid.sum(axis=1).astype(int).tolist(),
                "resident_fluid_mass_kg_per_frame": [
                    float(np.nansum(zone_mass[i][zone_fluid[i]])) for i in range(len(time))
                ],
                "fluid_particle_mass_values_kg": [float(value) for value in mass_values],
            }

        return {
            "path": str(path),
            "case_id": str(h5.attrs.get("case_id", path.stem)),
            "identity_key_declared": str(h5.attrs.get("identity_key", "unknown")),
            "frames": int(valid.shape[0]),
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "identity_slots": int(valid.shape[1]),
            "identities_ever_valid": int(ever.sum()),
            "valid_initial": int(initial.sum()),
            "valid_final": int(final.sum()),
            "born_after_initial": int((ever & ~initial).sum()),
            "initial_missing_at_final": int((initial & ~final).sum()),
            "multiple_validity_episodes": int((episode_counts > 1).sum()),
            "raw_particle_id_duplicates": int(len(particle_id) - len(np.unique(particle_id))),
            "compound_identity_duplicates": int(len(compound) - len(np.unique(compound, axis=0))),
            "resident_fluid_mass_kg_per_frame": [
                float(np.nansum(mass[i][fluid_valid[i]])) for i in range(len(time))
            ],
            "zones": zones,
        }


def assess(open_result: dict[str, Any], vres_result: dict[str, Any]) -> dict[str, Any]:
    assert open_result["born_after_initial"] > 0
    assert vres_result["raw_particle_id_duplicates"] > 0
    assert vres_result["compound_identity_duplicates"] == 0
    vres_mass_values = sorted(
        value
        for zone in vres_result["zones"].values()
        for value in zone["fluid_particle_mass_values_kg"]
    )
    return {
        "open_boundary": {
            "status": "extension_only",
            "identity_semantics": "particle_id tracks a solver particle only during its valid lifetime",
            "mass_semantics": "resident mass is not conserved mass; a control-volume balance requires signed boundary flux and exterior destinations",
            "required_schema": ["birth_time", "death_time", "valid", "boundary_event", "boundary_id", "signed_mass_flux"],
            "evidence": open_result,
        },
        "variable_resolution": {
            "status": "extension_only",
            "identity_semantics": "(zone, particle_id) identifies a numerical node; no cross-zone material lineage is inferred",
            "mass_semantics": "zone outputs overlap and use different particle masses; summing all resident zone mass is not a global material balance",
            "fluid_particle_mass_values_kg": vres_mass_values,
            "required_schema": ["particle_zone", "valid", "zone_priority", "overlap_mask", "numerical_node_id"],
            "tracer_requirement": "advect independent passive tracers on a composite velocity field with an explicit finest-zone precedence/blending rule",
            "evidence": vres_result,
        },
        "core_release_decision": "exclude both features from v0.1 core trajectories; retain as bounded protocol extensions",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--open-h5", type=Path, required=True)
    parser.add_argument("--vres-h5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    open_result = audit_hdf5(args.open_h5.resolve())
    vres_result = audit_hdf5(args.vres_h5.resolve())
    report = {
        "schema_version": 1,
        "scope": "bounded W09 lifecycle audit",
        "software_evidence": {
            "solver": "DualSPHysics 5.4.355",
            "official_release_note": "https://github.com/DualSPHysics/DualSPHysics/blob/master/CHANGES.txt",
            "official_partvtk_help": "https://github.com/DualSPHysics/DualSPHysics/blob/master/doc/help/PartVTK_Help.out",
        },
        **assess(open_result, vres_result),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
