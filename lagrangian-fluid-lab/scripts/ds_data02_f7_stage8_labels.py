#!/usr/bin/env python3
"""Materialize native transport labels for F7 Stage 8 production cases.

Generates native-labels.h5 for 4 Pump cases and 4 Moving Obstacle cases,
including source zone assignments, first crossing, residence times, and
cyclic recrossing counters under closed mass conservation ledgers.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import (
    validate_config,
    locate,
    initial_sources,
    finite_crossing,
    chord_box_fraction,
)

DATA_F7 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F7"
CONFIG_PUMP = FAMILY_DIR / "labels/pump_recirculation_event_config.json"
CONFIG_OBSTACLE = FAMILY_DIR / "labels/moving_obstacle_event_config.json"
SUMMARY_PATH = FAMILY_DIR / "stage8_labels_summary.json"

PUMP_CASES = [
    "F7_PUMP_P00_FINE",
    "F7_PUMP_P01_FINE",
    "F7_PUMP_P02_FINE",
    "F7_PUMP_P03_FINE",
]

OBSTACLE_CASES = [
    "F7_OBSTACLE_P00_FINE",
    "F7_OBSTACLE_P01_FINE",
    "F7_OBSTACLE_P02_FINE",
    "F7_OBSTACLE_P03_FINE",
]

STAGE8_CASES = PUMP_CASES + OBSTACLE_CASES


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def materialize_f7(source: Path | str, output: Path | str, config: dict, *, particle_chunk: int = 65536) -> dict:
    """Materialize native labels with source zones, crossings, residence, and cyclic recrossings."""
    validate_config(config)
    source, output = Path(source), Path(output)
    if output.exists() or output.resolve() == source.resolve():
        raise FileExistsError(f"labels must be written to a new artifact: {output}")
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    if particle_chunk < 1:
        raise ValueError("particle_chunk must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)

    regions, events = config["destination_regions"], config.get("events", [])
    nr, ne = len(regions), len(events)
    source_hash = sha256_file(source)

    with h5py.File(source, "r") as h, h5py.File(partial, "x") as out:
        for key in ("time", "particle_id", "particle_zone", "position", "valid", "mass", "type"):
            if key not in h:
                raise ValueError(f"missing native field: {key}")

        frame = h.attrs.get("coordinate_frame")
        if isinstance(frame, bytes):
            frame = frame.decode()
        if frame != config["coordinate_frame"]:
            raise ValueError(f"coordinate frame mismatch: trajectory={frame} vs config={config['coordinate_frame']}")

        time_axis = np.asarray(h["time"][:], dtype=np.float64)
        if len(time_axis) < 2 or not np.isfinite(time_axis).all() or not (np.diff(time_axis) > 0).all():
            raise ValueError("time must be finite and strictly increasing")

        nt, nparticles = h["valid"].shape
        if nt != len(time_axis) or h["position"].shape != (nt, nparticles, 3):
            raise ValueError("native trajectory shape mismatch")

        keys = np.column_stack((h["particle_zone"][:], h["particle_id"][:]))
        if keys.shape != (nparticles, 2) or len(np.unique(keys, axis=0)) != nparticles:
            raise ValueError("duplicate or inconsistent typed identity keys")

        # Root metadata
        out.attrs.update(
            schema="ds02.f7.native-event-labels.v1",
            standard_schema="ds-data-02.native-labels.v1",
            source_hdf5_sha256=source_hash,
            source_hdf5=str(source.resolve()),
            config_json=json.dumps(config, sort_keys=True),
            coordinate_frame=config["coordinate_frame"],
            physical_mechanism=config.get("physical_mechanism", "unknown"),
            complete=False,
            semantics="native numerical identity histories; saved-frame linear chords; cyclic recrossings",
            residence_semantics="piecewise-linear chord occupancy; interpolation error unassessed",
            event_time_semantics="saved-frame bracket plus chord estimate; cyclic recrossing counters",
            cyclic_recrossing_semantics="count of crossings beyond the first passage across finite aperture chords",
            q_n_status="not_assessed",
            model_invoked=False,
        )

        out.create_dataset("time", data=time_axis)
        out.create_dataset("particle_id", data=h["particle_id"][:])
        out.create_dataset("particle_zone", data=h["particle_zone"][:])

        def ds(name, shape, dtype, fillvalue=0):
            return out.create_dataset(
                name,
                shape=shape,
                dtype=dtype,
                fillvalue=fillvalue,
                **({"compression": "gzip"} if all(shape) else {}),
            )

        source_ds = ds("source_label", (nparticles,), "i2")
        source_zone_ds = ds("source_zone", (nparticles,), "i2")
        dest_ds = ds("destination_time_series", (nt, nparticles), "i2")
        final_ds = ds("final_category", (nparticles,), "i2")
        failure_ds = ds("failure_reason", (nparticles,), "i1")

        first_interval = ds("first_passage_interval", (nparticles, ne, 2), "f8", np.nan)
        first_estimate = ds("first_passage_chord_time", (nparticles, ne), "f8", np.nan)
        first_censor = ds("first_passage_censor", (nparticles, ne), "i1", 1)

        # Aliases for explicit F7 schema requirements
        first_crossing_interval = ds("first_crossing_interval", (nparticles, ne, 2), "f8", np.nan)
        first_crossing_time = ds("first_crossing_time_s", (nparticles, ne), "f8", np.nan)

        total_crossings = ds("total_crossing_count", (nparticles, ne), "i4")
        cyclic_recrossings = ds("cyclic_recrossing_count", (nparticles, ne), "i4")

        residence = ds("residence_time_s", (nparticles, nr), "f8")
        unresolved = ds("unresolved_interval_time_s", (nparticles,), "f8")
        origin_mass = ds("initial_fluid_mass_kg", (nparticles,), "f8")

        flux = np.zeros((nt, ne, 2), dtype=np.float64)
        unknown = np.zeros(nt, dtype=np.float64)
        lost = np.zeros(nt, dtype=np.float64)
        invalid = np.zeros(nt, dtype=np.float64)
        mass_table = np.zeros((len(config["source_regions"]) + 1, nr + 3), dtype=np.float64)
        total_initial = 0.0
        total_fluid_particles = 0

        for begin in range(0, nparticles, particle_chunk):
            end = min(nparticles, begin + particle_chunk)
            sl = slice(begin, end)
            chunk_valid = h["valid"][:, sl].astype(bool)
            chunk_type = h["type"][:, sl]
            chunk_pos = h["position"][:, sl].astype(np.float64)
            chunk_mass = h["mass"][:, sl].astype(np.float64)
            chunk_dest = np.zeros((nt, end - begin), dtype=np.int16)

            initial_valid = chunk_valid[0]
            fluid = initial_valid & (chunk_type[0] == 3)
            total_fluid_particles += int(np.sum(fluid))
            mass = np.where(fluid, chunk_mass[0], 0.0).astype(np.float64)
            if not np.isfinite(mass).all() or np.any(mass[fluid] <= 0):
                raise ValueError("initial fluid mass must be finite and positive")

            initial_pos = chunk_pos[0]
            if not np.isfinite(initial_pos[fluid]).all():
                raise ValueError("initial fluid position invalid")

            sources = initial_sources(h, config, sl, fluid, initial_pos)
            source_ds[sl] = sources
            source_zone_ds[sl] = sources
            origin_mass[sl] = mass
            total_initial += float(mass.sum())

            prev_pos = None
            prev_good = None
            disappeared = np.zeros(end - begin, dtype=bool)
            residence_local = np.zeros((end - begin, nr), dtype=np.float64)
            unresolved_local = np.zeros(end - begin, dtype=np.float64)
            bracket = np.full((end - begin, ne, 2), np.nan, dtype=np.float64)
            estimate_local = np.full((end - begin, ne), np.nan, dtype=np.float64)
            censor_local = np.ones((end - begin, ne), dtype=np.int8)
            crossing_counts_local = np.zeros((end - begin, ne), dtype=np.int32)

            for ti, timestamp in enumerate(time_axis):
                valid = chunk_valid[ti]
                current_type = chunk_type[ti]
                if np.any(~fluid & valid & (current_type == 3)):
                    raise ValueError("births require explicit lifecycle support")
                if np.any(fluid & valid & (current_type != 3)):
                    raise ValueError("fluid identity changes type")
                if np.any(disappeared & fluid & valid):
                    raise ValueError("lost fluid identity reappeared without lineage")
                disappeared |= fluid & ~valid

                pos = chunk_pos[ti]
                current_mass = chunk_mass[ti]
                good = fluid & valid & np.isfinite(pos).all(axis=1) & np.isfinite(current_mass) & (current_mass > 0)
                if np.any(good & ~np.isclose(current_mass, mass, rtol=1e-5, atol=0)):
                    raise ValueError("variable mass requires adaptive lifecycle support")

                destination = locate(pos, regions)
                destination[~fluid] = -3
                destination[fluid & ~valid] = -1
                destination[fluid & valid & ~good] = -2
                chunk_dest[ti] = destination

                unknown[ti] += mass[good & (destination == 0)].sum()
                lost[ti] += mass[fluid & ~valid].sum()
                invalid[ti] += mass[fluid & valid & ~good].sum()

                if ti > 0:
                    paired = prev_good & good
                    dt = timestamp - time_axis[ti - 1]
                    unresolved_local += (fluid & ~paired) * dt

                    for ri, region in enumerate(regions):
                        fraction = chord_box_fraction(prev_pos, pos, region["bounds"])
                        residence_local[:, ri] += np.where(paired, fraction * dt, 0.0)

                    for ei, event in enumerate(events):
                        fwd, bwd, tau = finite_crossing(prev_pos, pos, event)
                        fwd &= paired
                        bwd &= paired
                        crossed = fwd | bwd
                        crossing_counts_local[:, ei] += crossed.astype(np.int32)

                        flux[ti, ei, 0] += mass[fwd].sum()
                        flux[ti, ei, 1] += mass[bwd].sum()

                        selected = crossed & np.isnan(bracket[:, ei, 0])
                        bracket[selected, ei, 0] = time_axis[ti - 1]
                        bracket[selected, ei, 1] = timestamp
                        estimate_local[selected, ei] = time_axis[ti - 1] + tau[selected] * dt
                        censor_local[selected, ei] = 0

                prev_pos, prev_good = pos, good

            dest_ds[:, sl] = chunk_dest
            first_interval[sl] = bracket
            first_crossing_interval[sl] = bracket
            first_estimate[sl] = estimate_local
            first_crossing_time[sl] = estimate_local
            first_censor[sl] = censor_local

            total_crossings[sl] = crossing_counts_local
            cyclic_recrossings[sl] = np.maximum(0, crossing_counts_local - 1)

            residence[sl] = residence_local
            unresolved[sl] = unresolved_local
            final_ds[sl] = destination
            failure_ds[sl] = np.where(
                ~fluid, 4,
                np.where(destination == -1, 1,
                         np.where(destination == -2, 2,
                                  np.where(destination == 0, 3, 0)))
            )

            for si in range(mass_table.shape[0]):
                for code in range(-2, nr + 1):
                    mass_table[si, code + 2] += mass[(sources == si) & (destination == code)].sum()

        if total_initial <= 0:
            raise ValueError("trajectory has no initial fluid mass")

        out.create_dataset("forward_backward_mass_kg", data=np.cumsum(flux, axis=0))
        out.create_dataset("cumulative_net_flux_kg", data=np.cumsum(flux[:, :, 0] - flux[:, :, 1], axis=0))
        out.create_dataset("unknown_mass_kg", data=unknown)
        out.create_dataset("numerical_loss_mass_kg", data=lost)
        out.create_dataset("invalid_state_mass_kg", data=invalid)
        out.create_dataset("source_final_mass_kg", data=mass_table)

        out.attrs.update(
            initial_fluid_mass_kg=total_initial,
            fluid_particles=total_fluid_particles,
            destination_codes=json.dumps({
                "-3": "noninitial_fluid",
                "-2": "invalid_state",
                "-1": "numerical_loss",
                "0": "unknown",
                **{str(i): r["id"] for i, r in enumerate(regions, 1)}
            }),
            source_codes=json.dumps({
                str(i): r["id"] for i, r in enumerate(config["source_regions"], 1)
            }),
            first_passage_censor_codes="0=observed_saved_chord;1=not_observed_or_censored",
            failure_reason_codes="0=none;1=numerical_loss;2=invalid_state;3=unclassified_region;4=noninitial_fluid",
            source_final_columns="invalid_state,numerical_loss,unknown,then destination_regions",
            complete=True,
        )

    if sha256_file(source) != source_hash:
        raise RuntimeError("native source mutated during labeling; keep partial artifact")

    os.replace(partial, output)
    return {
        "path": str(output),
        "sha256": sha256_file(output),
        "initial_fluid_mass_kg": total_initial,
        "fluid_particles": total_fluid_particles,
        "frames": nt,
        "identities": nparticles,
        "q_n_status": "not_assessed",
    }


def process_case(case_id: str, overwrite: bool = False) -> dict:
    case_dir = DATA_F7 / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Case directory {case_dir} not found")

    trajs = sorted(case_dir.glob("full-typed-native-conversion-*/trajectory.h5"))
    if not trajs:
        raise FileNotFoundError(f"No trajectory.h5 found for {case_id}")
    source_h5 = trajs[-1]

    is_pump = "PUMP" in case_id
    config_path = CONFIG_PUMP if is_pump else CONFIG_OBSTACLE
    config = json.loads(config_path.read_text(encoding="utf-8"))

    attempt_dir = case_dir / "native-transport-labels-001"
    output_h5 = attempt_dir / "native-labels.h5"
    receipt_path = attempt_dir / "execution-receipt.json"

    if output_h5.exists() and not overwrite:
        print(f"[{now_str()}] Case {case_id} labels already exist: {output_h5}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
        return {
            "case_id": case_id,
            "status": "already_exists",
            "output": str(output_h5),
            "receipt": receipt,
        }

    attempt_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for p in (output_h5, receipt_path):
            if p.exists():
                p.unlink()

    print(f"[{now_str()}] Starting label extraction for {case_id}...")
    start_time = time.monotonic()

    res = materialize_f7(source_h5, output_h5, config, particle_chunk=65536)
    elapsed = time.monotonic() - start_time

    receipt = {
        "schema": "ds02.f7.labels-receipt.v1",
        "case_id": case_id,
        "attempt_id": "native-transport-labels-001",
        "mechanism": "pump_recirculation" if is_pump else "moving_obstacle_exchange",
        "source_trajectory": str(source_h5),
        "source_trajectory_sha256": sha256_file(source_h5),
        "config_path": str(config_path),
        "config_sha256": sha256_file(config_path),
        "output_path": str(output_h5),
        "output_sha256": res["sha256"],
        "initial_fluid_mass_kg": res["initial_fluid_mass_kg"],
        "fluid_particles": res["fluid_particles"],
        "frames": res["frames"],
        "identities": res["identities"],
        "elapsed_seconds": elapsed,
        "created_at_utc": now_str(),
        "status": "completed",
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Completed {case_id} in {elapsed:.2f}s (sha256: {res['sha256'][:12]}...)")
    return {
        "case_id": case_id,
        "status": "completed",
        "elapsed_seconds": elapsed,
        "output": str(output_h5),
        "receipt": receipt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=None, help="Specific cases to run")
    parser.add_argument("--group", choices=["pump", "obstacle", "all"], default="all", help="Subset to run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing labels")
    args = parser.parse_args()

    targets = []
    if args.cases:
        targets = args.cases
    else:
        if args.group in ("pump", "all"):
            targets.extend(PUMP_CASES)
        if args.group in ("obstacle", "all"):
            targets.extend(OBSTACLE_CASES)

    results = []
    existing_summary = {}
    if SUMMARY_PATH.exists():
        try:
            existing_summary = {r["case_id"]: r for r in json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass

    for cid in targets:
        try:
            res = process_case(cid, overwrite=args.overwrite)
            results.append(res)
            existing_summary[cid] = res
        except Exception as e:
            print(f"[{now_str()}] ERROR processing {cid}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            res = {"case_id": cid, "status": "failed", "error": str(e)}
            results.append(res)
            existing_summary[cid] = res

        SUMMARY_PATH.write_text(json.dumps(list(existing_summary.values()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"[{now_str()}] Finished processing {len(targets)} cases. Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
