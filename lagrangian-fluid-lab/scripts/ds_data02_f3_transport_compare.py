#!/usr/bin/env python3
"""Compare F3 native transport labels on a fixed physical window.

This is a diagnostic reducer for immutable label HDF5 artifacts.  It compares
finite-event flux, saved-frame passage brackets, and residence in seconds and
kg*s while retaining the unnormalised initial mass.  It never converts an
unknown interval into an exit and never grants Q-N.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f3.transport-comparison.v1"
WINDOW_END_S = 10.0


class TransportCompareError(RuntimeError):
    """Raised when label artifacts cannot be compared under one operator."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _usage() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _attr_text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _weighted_stats(values: np.ndarray, weights: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    selected = mask & np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    mass = float(np.sum(weights[selected]))
    if not np.any(selected):
        return {"count": 0, "mass_kg": 0.0, "mean_s": None, "min_s": None, "max_s": None}
    return {
        "count": int(np.sum(selected)),
        "mass_kg": mass,
        "mean_s": float(np.sum(values[selected] * weights[selected]) / mass),
        "min_s": float(np.min(values[selected])),
        "max_s": float(np.max(values[selected])),
    }


def summarize_labels(path: Path, *, particle_chunk: int = 65536) -> dict[str, Any]:
    if not path.is_file():
        raise TransportCompareError(f"missing label artifact: {path}")
    if particle_chunk < 1:
        raise TransportCompareError("particle_chunk must be positive")
    with h5py.File(path, "r") as h5:
        required = {
            "time", "particle_id", "particle_zone", "source_label", "initial_fluid_mass_kg",
            "first_passage_interval", "first_passage_chord_time", "first_passage_censor",
            "forward_backward_mass_kg", "cumulative_net_flux_kg", "residence_time_s",
            "unknown_mass_kg", "numerical_loss_mass_kg", "invalid_state_mass_kg",
        }
        missing = sorted(required - set(h5.keys()))
        if missing:
            raise TransportCompareError(f"label artifact lacks fields: {missing}")
        if not bool(h5.attrs.get("complete", False)):
            raise TransportCompareError(f"label artifact is incomplete: {path}")
        times = np.asarray(h5["time"][:], dtype=float)
        if len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise TransportCompareError(f"label times are not finite/increasing: {path}")
        if times[0] > 1e-10 or times[-1] < WINDOW_END_S:
            raise TransportCompareError(f"label does not cover 0-{WINDOW_END_S:g}s: {path}")
        config = json.loads(_attr_text(h5.attrs["config_json"]))
        event_ids = [str(event["id"]) for event in config.get("events", [])]
        if not event_ids:
            raise TransportCompareError("label config has no events")
        event_count = len(event_ids)
        n_particles = int(h5["source_label"].shape[0])
        if h5["first_passage_interval"].shape != (n_particles, event_count, 2):
            raise TransportCompareError("first-passage interval shape disagrees with event config")
        if h5["first_passage_censor"].shape != (n_particles, event_count):
            raise TransportCompareError("first-passage censor shape disagrees with event config")
        if h5["first_passage_chord_time"].shape != (n_particles, event_count):
            raise TransportCompareError("first-passage chord shape disagrees with event config")
        source = np.asarray(h5["source_label"][:], dtype=np.int16)
        masses = np.asarray(h5["initial_fluid_mass_kg"][:], dtype=float)
        fluid = source > 0
        if not np.any(fluid) or not np.isfinite(masses[fluid]).all() or np.any(masses[fluid] <= 0):
            raise TransportCompareError("label initial fluid masses are not finite and positive")
        total_mass = float(np.sum(masses[fluid]))
        observed = np.zeros(event_count, dtype=np.int64)
        observed_mass = np.zeros(event_count, dtype=float)
        censored = np.zeros(event_count, dtype=np.int64)
        censored_mass = np.zeros(event_count, dtype=float)
        lower_sum = np.zeros(event_count, dtype=float)
        upper_sum = np.zeros(event_count, dtype=float)
        estimate_sum = np.zeros(event_count, dtype=float)
        residence_weighted = None
        residence_count = None
        residence_mass_time = None
        for begin in range(0, n_particles, particle_chunk):
            end = min(n_particles, begin + particle_chunk)
            sl = slice(begin, end)
            mass = masses[sl]
            fluid_chunk = fluid[sl]
            interval = np.asarray(h5["first_passage_interval"][sl], dtype=float)
            estimates = np.asarray(h5["first_passage_chord_time"][sl], dtype=float)
            censor = np.asarray(h5["first_passage_censor"][sl], dtype=int)
            for event in range(event_count):
                good = fluid_chunk & (censor[:, event] == 0) & np.isfinite(interval[:, event]).all(axis=1)
                cens = fluid_chunk & ~good
                observed[event] += int(np.sum(good))
                observed_mass[event] += float(np.sum(mass[good]))
                censored[event] += int(np.sum(cens))
                censored_mass[event] += float(np.sum(mass[cens]))
                lower_sum[event] += float(np.sum(interval[good, event, 0] * mass[good]))
                upper_sum[event] += float(np.sum(interval[good, event, 1] * mass[good]))
                estimate_good = good & np.isfinite(estimates[:, event])
                estimate_sum[event] += float(np.sum(estimates[estimate_good, event] * mass[estimate_good]))
            residence = np.asarray(h5["residence_time_s"][sl], dtype=float)
            if residence_weighted is None:
                region_count = residence.shape[1]
                residence_weighted = np.zeros(region_count, dtype=float)
                residence_count = np.zeros(region_count, dtype=np.int64)
                residence_mass_time = np.zeros(region_count, dtype=float)
            for region in range(residence.shape[1]):
                good = fluid_chunk & np.isfinite(residence[:, region]) & (residence[:, region] >= 0)
                residence_count[region] += int(np.sum(good))
                residence_weighted[region] += float(np.sum(residence[good, region] * mass[good]))
                residence_mass_time[region] += float(np.sum(residence[good, region] * mass[good]))
        assert residence_weighted is not None and residence_count is not None and residence_mass_time is not None
        passage = []
        for event, event_id in enumerate(event_ids):
            mass = observed_mass[event]
            passage.append({
                "event_id": event_id,
                "observed_count": int(observed[event]),
                "observed_mass_kg": float(mass),
                "censored_count": int(censored[event]),
                "censored_mass_kg": float(censored_mass[event]),
                "mass_weighted_lower_bracket_s": None if mass == 0 else float(lower_sum[event] / mass),
                "mass_weighted_upper_bracket_s": None if mass == 0 else float(upper_sum[event] / mass),
                "mass_weighted_chord_time_s": None if mass == 0 else float(estimate_sum[event] / mass),
                "semantics": "observed saved-frame bracket; censor preserves unknown/no crossing",
            })
        residence_rows = []
        for region, count in enumerate(residence_count):
            residence_rows.append({
                "region_index": region + 1,
                "particle_count": int(count),
                "mass_weighted_mean_residence_time_s": None if total_mass == 0 else float(residence_weighted[region] / total_mass),
                "residence_mass_time_kg_s": float(residence_mass_time[region]),
                "time_unit": "s",
                "mass_time_unit": "kg*s",
            })
        return {
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "schema": _attr_text(h5.attrs.get("schema", "")),
            "coordinate_frame": _attr_text(h5.attrs.get("coordinate_frame", "")),
            "source_hdf5_sha256": _attr_text(h5.attrs.get("source_hdf5_sha256", "")),
            "frames": int(len(times)),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "save_interval_min_s": float(np.min(np.diff(times))),
            "save_interval_max_s": float(np.max(np.diff(times))),
            "identity_count": n_particles,
            "fluid_identity_count": int(np.sum(fluid)),
            "initial_fluid_mass_kg": total_mass,
            "event_ids": event_ids,
            "passage": passage,
            "residence": residence_rows,
            "final_forward_backward_mass_kg": np.asarray(h5["forward_backward_mass_kg"][-1], dtype=float).tolist(),
            "final_cumulative_net_flux_kg": np.asarray(h5["cumulative_net_flux_kg"][-1], dtype=float).tolist(),
            "final_unknown_mass_kg": float(np.asarray(h5["unknown_mass_kg"][-1])),
            "final_numerical_loss_mass_kg": float(np.asarray(h5["numerical_loss_mass_kg"][-1])),
            "final_invalid_state_mass_kg": float(np.asarray(h5["invalid_state_mass_kg"][-1])),
            "q_n_status": _attr_text(h5.attrs.get("q_n_status", "not_assessed")),
        }


def _difference(base: float | None, variant: float | None) -> dict[str, Any]:
    if base is None or variant is None:
        return {"base": base, "variant": variant, "absolute": None, "relative_to_base": None}
    absolute = float(variant - base)
    return {"base": base, "variant": variant, "absolute": absolute,
            "relative_to_base": None if base == 0 else float(absolute / abs(base))}


def compare(baseline: Path, variants: list[Path], *, output: Path, particle_chunk: int = 65536) -> dict[str, Any]:
    before = _usage()
    base = summarize_labels(baseline, particle_chunk=particle_chunk)
    results: dict[str, Any] = {
        "schema": SCHEMA,
        "claim_boundary": "fixed physical-window transport bracket/mass-time diagnostic; Q-N and production remain unassessed",
        "window_s": [0.0, WINDOW_END_S],
        "operators": {
            "event_time": "saved-frame lower/upper bracket plus native chord estimate",
            "crossing_mass": "native kg, forward/backward and net reported separately",
            "residence": "seconds per particle and unnormalised kg*s mass-time",
            "unknown": "censored/unknown retained; never inferred as physical exit",
        },
        "budgets": {"macro_relative_starting_budget": 0.05, "event_time_relative_starting_budget": 0.02,
                    "save_or_integration_share_cap": 0.20, "status": "not_assessed"},
        "baseline": base,
        "variants": {},
        "resource_usage": {},
    }
    for path in variants:
        current = summarize_labels(path, particle_chunk=particle_chunk)
        if current["coordinate_frame"] != base["coordinate_frame"] or current["event_ids"] != base["event_ids"]:
            raise TransportCompareError(f"operator/frame mismatch: {path}")
        event_rows = []
        for base_event, current_event in zip(base["passage"], current["passage"]):
            event_rows.append({
                "event_id": base_event["event_id"],
                "observed_mass_kg": _difference(base_event["observed_mass_kg"], current_event["observed_mass_kg"]),
                "censored_mass_kg": _difference(base_event["censored_mass_kg"], current_event["censored_mass_kg"]),
                "lower_bracket_s": _difference(base_event["mass_weighted_lower_bracket_s"], current_event["mass_weighted_lower_bracket_s"]),
                "upper_bracket_s": _difference(base_event["mass_weighted_upper_bracket_s"], current_event["mass_weighted_upper_bracket_s"]),
                "chord_time_s": _difference(base_event["mass_weighted_chord_time_s"], current_event["mass_weighted_chord_time_s"]),
            })
        residence_rows = []
        for base_region, current_region in zip(base["residence"], current["residence"]):
            residence_rows.append({
                "region_index": base_region["region_index"],
                "mean_residence_time_s": _difference(base_region["mass_weighted_mean_residence_time_s"], current_region["mass_weighted_mean_residence_time_s"]),
                "residence_mass_time_kg_s": _difference(base_region["residence_mass_time_kg_s"], current_region["residence_mass_time_kg_s"]),
            })
        results["variants"][path.stem] = {
            "summary": current,
            "initial_mass_kg": _difference(base["initial_fluid_mass_kg"], current["initial_fluid_mass_kg"]),
            "frames": {"base": base["frames"], "variant": current["frames"], "base_end_s": base["time_end_s"], "variant_end_s": current["time_end_s"]},
            "final_net_flux_kg": [_difference(float(a), float(b)) for a, b in zip(base["final_cumulative_net_flux_kg"], current["final_cumulative_net_flux_kg"])],
            "event_brackets": event_rows,
            "residence": residence_rows,
            "qualification_status": "not_assessed",
        }
    results["resource_usage"] = {"before": before, "after": _usage()}
    if output.exists():
        raise TransportCompareError(f"refusing to overwrite comparison: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variant", type=Path, action="append", required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = compare(args.baseline, args.variant, output=args.output, particle_chunk=args.particle_chunk)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, TransportCompareError) as exc:
        print(f"F3 transport comparison failed: {exc}")
        return 2
    print(json.dumps({"output": str(args.output.resolve()), "variants": len(result["variants"]), "q_n_status": "not_assessed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
