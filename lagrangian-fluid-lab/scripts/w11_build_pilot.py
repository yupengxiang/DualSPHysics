#!/usr/bin/env python3
"""Materialize and audit the small W11 development package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import h5py
import numpy as np

try:  # package imports under pytest
    from scripts.passive_tracers import advect_hdf5, deterministic_seeds
    from scripts.protocol_metrics import require_finite_when_valid, require_strict_time, validate_affine_transforms, validate_split_lineage
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from passive_tracers import advect_hdf5, deterministic_seeds
    from protocol_metrics import require_finite_when_valid, require_strict_time, validate_affine_transforms, validate_split_lineage


REQUIRED_DATASETS = [
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "density", "pressure", "mass", "type", "mk",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def augment_material(h5_path: Path, dp: float, maximum: int) -> dict[str, Any] | None:
    with h5py.File(h5_path, "r") as h5:
        fluid_count = int(np.sum(h5["valid"][0] & (h5["type"][0] == 3)))
    if fluid_count == 0:
        return None
    seeds = deterministic_seeds(h5_path, maximum=maximum)
    traced = advect_hdf5(
        h5_path, seeds["position"], neighbours=24, regularization=0.1 * dp,
        maximum_support_distance=1.75 * dp,
    )
    support = traced["nearest_support_distance"]
    step_valid = support <= 1.75 * dp
    cumulative = np.vstack((np.ones((1, len(seeds["indices"])), dtype=bool), np.logical_and.accumulate(step_valid, axis=0)))
    with h5py.File(h5_path, "r+") as h5:
        if "material" in h5:
            del h5["material"]
        group = h5.create_group("material")
        group.attrs["semantics"] = "independent passive tracers; no solver Idp lookup after t0"
        group.attrs["velocity_interpolation"] = "24-neighbour inverse-distance Shepard"
        group.attrs["integration"] = "Heun"
        group.create_dataset("tracer_id", data=np.arange(len(seeds["indices"]), dtype=np.int64))
        group.create_dataset("seed_particle_id", data=seeds["particle_id"])
        group.create_dataset("seed_particle_zone", data=seeds["particle_zone"])
        group.create_dataset("source_label", data=seeds["source_mk"].astype(np.int16))
        group.create_dataset("valid", data=cumulative, compression="gzip")
        group.create_dataset("position", data=traced["position"].astype(np.float32), compression="gzip")
        group.create_dataset("nearest_support_distance", data=np.vstack((np.zeros((1, len(seeds["indices"]))), support)).astype(np.float32), compression="gzip")
    return {"tracers": len(seeds["indices"]), "reliable_at_end": int(cumulative[-1].sum())}


def audit_case(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        missing = [name for name in REQUIRED_DATASETS if name not in h5]
        if missing:
            raise ValueError(f"{expected['case_id']}: missing datasets {missing}")
        time = h5["time"][:]
        valid = h5["valid"][:]
        require_strict_time(time)
        require_finite_when_valid(h5["position"][:], valid)
        require_finite_when_valid(h5["velocity"][:], valid)
        keys = np.column_stack((h5["particle_zone"][:], h5["particle_id"][:]))
        if len(np.unique(keys, axis=0)) != len(keys):
            raise ValueError(f"{expected['case_id']}: duplicate compound identities")
        initial = valid[0]
        numerical_loss = float(np.sum(initial & ~valid[-1]) / max(1, np.sum(initial)))
        if numerical_loss > 0:
            raise ValueError(f"{expected['case_id']}: closed pilot has numerical loss {numerical_loss}")
        if "control/cup_world_from_body" in h5:
            validate_affine_transforms(h5["control/cup_world_from_body"][:])
        return {
            "frames": len(time),
            "identity_slots": valid.shape[1],
            "initial_particles": int(initial.sum()),
            "final_particles": int(valid[-1].sum()),
            "frame_interval_median_s": float(np.median(np.diff(time))),
            "numerical_loss_fraction": numerical_loss,
            "duration_s": float(time[-1] - time[0]),
            "material_tracers": int(h5["material/tracer_id"].shape[0]) if "material" in h5 else 0,
            "material_reliable_at_end": int(h5["material/valid"][-1].sum()) if "material" in h5 else 0,
        }


def build(selection_path: Path, lab_root: Path, release_root: Path) -> dict[str, Any]:
    selection = json.loads(selection_path.read_text())
    validate_split_lineage(selection["cases"])
    data_dir = release_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    checksums = []
    for record in selection["cases"]:
        source = lab_root / record["source_hdf5"]
        target = data_dir / f"{record['case_id']}.h5"
        partial = target.with_suffix(".h5.partial")
        shutil.copyfile(source, partial)
        with h5py.File(partial, "r+") as h5:
            h5.attrs.update({
                "schema_version": "0.1",
                "world_frame": "right-handed Cartesian; z up; SI",
                "time_units": "s", "length_units": "m", "mass_units": "kg",
                "development_pilot": True,
            })
        material = augment_material(partial, float(record["dp"]), int(selection["material_tracers_per_fluid_case"]))
        os.replace(partial, target)
        evidence = audit_case(target, record)
        digest = sha256(target)
        checksums.append(f"{digest}  data/{target.name}")
        manifest_cases.append({
            "case_id": record["case_id"], "family": record["family"],
            "lineage_group_id": record["lineage_group_id"], "split": record["split"],
            "hdf5": f"data/{target.name}", "source_hdf5": record["source_hdf5"],
            "sha256": digest, "bytes": target.stat().st_size,
            "physics": {"mechanism": record["mechanism"]},
            "geometry": {"variant": record["lineage_group_id"]},
            "control": {},
            "numerics": {"particle_spacing_m": record["dp"], "boundary_formulation": "source_case", "solver_version": "DualSPHysics 5.4.355"},
            "observation": {"frame_interval_s": evidence["frame_interval_median_s"], "event_sampling": "development_source_cadence_not_release_frozen"},
            "quality": {"gate_status": "development_pass", "numerical_loss_fraction": evidence["numerical_loss_fraction"], "validation_scope": record["validation_scope"]},
            "evidence": evidence,
            "material": material,
        })
    manifest = {"schema_version": "0.1", "release_id": selection["release_id"], "formal_release": False, "cases": manifest_cases}
    (release_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (release_root / "checksums.sha256").write_text("\n".join(checksums) + "\n")
    summary = {
        "schema_version": 1,
        "case_count": len(manifest_cases),
        "families": {family: sum(c["family"] == family for c in manifest_cases) for family in sorted({c["family"] for c in manifest_cases})},
        "splits": {split: sum(c["split"] == split for c in manifest_cases) for split in sorted({c["split"] for c in manifest_cases})},
        "total_bytes": sum(c["bytes"] for c in manifest_cases),
        "total_frames": sum(c["evidence"]["frames"] for c in manifest_cases),
        "total_material_tracers": sum(c["evidence"]["material_tracers"] for c in manifest_cases),
        "all_closed_cases_zero_numerical_loss": all(c["evidence"]["numerical_loss_fraction"] == 0 for c in manifest_cases),
        "formal_release": False,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.selection.resolve(), args.lab_root.resolve(), args.release_root.resolve())
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
