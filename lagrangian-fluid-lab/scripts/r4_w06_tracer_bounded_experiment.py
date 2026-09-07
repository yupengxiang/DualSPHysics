#!/usr/bin/env python3
"""Bounded CPU wall-aware tracer experiment for ``W06_standard_slow_center``.

This is the smallest executable follow-up to the R4 tracer audit.  It uses one
already exported solver HDF5 and its release-linked finite-triangle sidecar,
then varies only the mass-weighted seed count and the explicit Heun substeps:

    32 seeds x {1, 4} substeps, 64 seeds x {1, 4} substeps.

The experiment records a candidate destination/open-face policy and writes a
source-by-destination mass ledger.  It never launches CFD, GenCase, CUDA, or
GPU work.  The policy is intentionally not promoted to a formal material
target: the current release does not link destination specifications and the
sidecar audit still leaves implicit caps/open-face semantics unresolved.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import audit_sidecar, sidecar_provider
    from scripts.passive_tracers import advect_hdf5, weighted_stratified_seeds
except ModuleNotFoundError:  # direct execution from scripts/
    from boundary_sidecars import audit_sidecar, sidecar_provider
    from passive_tracers import advect_hdf5, weighted_stratified_seeds


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
RELEASE = LAB / "release" / "v0.1-development"
MANIFEST = RELEASE / "manifest.json"
CASE_ID = "W06_standard_slow_center"
CASE_XML = CAMPAIGN / "cases" / "w06" / f"{CASE_ID}_Def.xml"
H5_PATH = RELEASE / "data" / f"{CASE_ID}.h5"
SIDECAR_PATH = RELEASE / "sidecars" / "r3-g2-boundary" / f"{CASE_ID}.h5"
CASE_ROOT = CAMPAIGN / "cases" / "r4-w06-tracer-bounded-experiment"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r4-w06-tracer-bounded-experiment"
REPORT_JSON = CAMPAIGN / "r4-w06-tracer-bounded-experiment.json"
REPORT_MD = CAMPAIGN / "R4-W06-TRACER-BOUNDED-EXPERIMENT.md"

SEED_COUNTS = (32, 64)
SUBSTEPS = (1, 4)
NEIGHBOURS = 24
REGULARIZATION_OVER_DP = 0.1
MAXIMUM_SUPPORT_OVER_DP = 1.75

# The receiver is fixed in world coordinates.  Its shell is declared in the
# source XML as point=(0.45,-0.30,0.0), size=(1.10,0.60,0.45).  The candidate
# destination excludes one nominal particle spacing from each wall so that a
# boundary sample is not silently counted as captured fluid.
DESTINATION_SPEC: dict[str, Any] = {
    "lifecycle_model": "closed",
    "sources": {"mode": "mk"},
    "destination_frame": {"kind": "world"},
    "destinations": [
        {
            "name": "inside_receiver",
            "type": "aabb",
            "min": [0.475, -0.275, 0.025],
            "max": [1.525, 0.275, 0.425],
        }
    ],
    "complement_labels": ["in_domain_unclassified", "outside_domain"],
    "exit_reason_names": {
        "wall_crossing": "candidate swept-wall rejection",
        "support_distance_exceedance": "interpolant support exceeded configured maximum",
        "support_gate_failure": "ESS/geometry/anisotropy/reconstruction gate failed",
        "support_nonfinite": "non-finite support or interpolation diagnostic",
        "numerical_loss": "non-finite or otherwise unclassified tracer failure",
    },
}

BOUNDARY_POLICY: dict[str, Any] = {
    "status": "candidate_only",
    "coordinate_frame": "world",
    "component_roles": {
        "17": {
            "role": "moving_cup_wall",
            "declared_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
            "rim_policy": "finite_generated_triangles_only",
            "supporting_policy": "not_assumed",
        },
        "18": {
            "role": "fixed_receiver_wall",
            "declared_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
            "rim_policy": "finite_generated_triangles_only",
            "supporting_policy": "not_assumed",
        },
        "19": {
            "role": "fixed_floor",
            "declared_faces": ["bottom"],
            "open_faces": ["top", "left", "right", "front", "back"],
            "rim_policy": "finite_generated_triangles_only",
            "supporting_policy": "not_assumed",
        },
    },
    "formal_wall_aware_admission": False,
    "reason": "release sidecar has finite triangles but no linked accepted open-face/destination contract",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB.resolve()))


def _attr_text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode()
    return str(value) if value is not None else None


def _read_domain(path: Path) -> dict[str, list[float]]:
    root = ET.parse(path).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError(f"{path}: missing simulationdomain")
    # The XML stores posmin/posmax as attributes on child elements.
    posmin = domain.find("./posmin")
    posmax = domain.find("./posmax")
    if posmin is None or posmax is None:
        raise ValueError(f"{path}: simulationdomain lacks posmin/posmax")
    lower = [float(posmin.get(axis)) for axis in "xyz"]
    upper = [float(posmax.get(axis)) for axis in "xyz"]
    if not np.all(np.asarray(upper) > np.asarray(lower)):
        raise ValueError(f"{path}: invalid simulationdomain bounds")
    return {"min": lower, "max": upper}


def _load_manifest_record() -> dict[str, Any]:
    payload = json.loads(MANIFEST.read_text())
    records = [item for item in payload.get("cases", []) if item.get("case_id") == CASE_ID]
    if len(records) != 1:
        raise ValueError(f"release manifest must contain exactly one {CASE_ID} record")
    record = records[0]
    if (RELEASE / record.get("hdf5", "")).resolve() != H5_PATH.resolve():
        raise ValueError("release manifest HDF5 link differs from the expected W06 artifact")
    sidecar_ref = (record.get("geometry") or {}).get("boundary_sidecar")
    if sidecar_ref != f"sidecars/r3-g2-boundary/{CASE_ID}.h5":
        raise ValueError("release manifest sidecar link is not the expected W06 sidecar")
    if not H5_PATH.is_file() or not SIDECAR_PATH.is_file():
        raise FileNotFoundError("W06 release HDF5 or linked sidecar is missing")
    return record


def _input_summary(record: dict[str, Any]) -> dict[str, Any]:
    sidecar_audit = audit_sidecar(SIDECAR_PATH)
    with h5py.File(H5_PATH, "r") as h5, h5py.File(SIDECAR_PATH, "r") as sidecar:
        solver_time = np.asarray(h5["time"][:], dtype=np.float64)
        sidecar_time = np.asarray(sidecar["time"][:], dtype=np.float64)
        if solver_time.shape != sidecar_time.shape or not np.allclose(
            solver_time, sidecar_time, atol=1e-10, rtol=0.0
        ):
            raise ValueError("W06 sidecar and solver time axes differ")
        component_dataset = "triangle_component" if "triangle_component" in sidecar else "triangle_mk"
        # The current release sidecar predates the redundant explicit component
        # dataset.  ``triangle_mk`` is a safe candidate fallback for this
        # single case, but the report records that formal component provenance
        # is still incomplete.
        component = np.asarray(sidecar[component_dataset][:], dtype=np.int64)
        kind = np.asarray(sidecar["triangle_type"][:], dtype=np.int8)
        component_summary = {
            str(int(value)): {
                "triangle_count": int(np.sum(component == value)),
                "types": sorted({int(item) for item in kind[component == value]}),
            }
            for value in np.unique(component)
        }
        fluid = h5["valid"][0] & (h5["type"][0] == 3)
        initial_fluid_mass = float(np.sum(h5["mass"][0, fluid], dtype=np.float64))
        fluid_count = int(np.sum(fluid))
        frame_cadence = float(np.median(np.diff(solver_time)))
    return {
        "case_id": CASE_ID,
        "family": record.get("family"),
        "lineage_group_id": record.get("lineage_group_id"),
        "split": record.get("split"),
        "hdf5": _relative(H5_PATH),
        "hdf5_sha256": _sha256(H5_PATH),
        "sidecar": _relative(SIDECAR_PATH),
        "sidecar_sha256": _sha256(SIDECAR_PATH),
        "manifest": _relative(MANIFEST),
        "manifest_sha256": _sha256(MANIFEST),
        "source_definition": _relative(CASE_XML),
        "source_definition_sha256": _sha256(CASE_XML),
        "frames": int(len(solver_time)),
        "time_start_s": float(solver_time[0]),
        "time_end_s": float(solver_time[-1]),
        "saved_cadence_median_s": frame_cadence,
        "particle_spacing_m": float(record["numerics"]["particle_spacing_m"]),
        "initial_fluid_particles": fluid_count,
        "initial_fluid_mass_kg": initial_fluid_mass,
        "sidecar_audit": sidecar_audit,
        "sidecar_components": component_summary,
        "sidecar_component_label_dataset": component_dataset,
        "sidecar_component_labels_explicit": component_dataset == "triangle_component",
        "simulation_domain_m": _read_domain(CASE_XML),
    }


def _region_mask(position: np.ndarray, region: dict[str, Any]) -> np.ndarray:
    if region["type"] != "aabb":
        raise ValueError("this bounded experiment only implements its explicit AABB destination")
    lower = np.asarray(region["min"], dtype=float)
    upper = np.asarray(region["max"], dtype=float)
    return np.all((position >= lower) & (position <= upper), axis=-1)


def _domain_mask(position: np.ndarray, domain: dict[str, list[float]]) -> np.ndarray:
    lower = np.asarray(domain["min"], dtype=float)
    upper = np.asarray(domain["max"], dtype=float)
    return np.all((position >= lower) & (position <= upper), axis=-1)


def _first_failure_reasons(trace: dict[str, Any], seed_count: int) -> tuple[list[str | None], np.ndarray]:
    reliability = np.asarray(trace["reliability_history"], dtype=bool)
    wall = np.asarray(trace["wall_crossing"], dtype=bool)
    support_gate = np.asarray(trace["support_gate_pass"], dtype=bool)
    support = np.asarray(trace["nearest_support_distance"], dtype=float)
    effective = np.asarray(trace["effective_sample_size"], dtype=float)
    rank = np.asarray(trace["support_geometry_rank"], dtype=float)
    anisotropy = np.asarray(trace["support_anisotropy"], dtype=float)
    reconstruction = np.asarray(trace["interpolation_reconstruction_error_mps"], dtype=float)
    gate = trace.get("support_gate") or {}
    maximum_support = MAXIMUM_SUPPORT_OVER_DP * 0.025
    reasons: list[str | None] = []
    first_frames = np.full(seed_count, -1, dtype=np.int64)
    for seed in range(seed_count):
        failed = np.flatnonzero(~reliability[:, seed])
        if not len(failed):
            reasons.append(None)
            continue
        frame = int(failed[0])
        first_frames[seed] = frame
        interval = max(0, frame - 1)
        if interval < len(wall) and wall[interval, seed]:
            reasons.append("wall_crossing")
        elif interval < len(support_gate) and not support_gate[interval, seed]:
            if not np.isfinite(support[interval, seed]):
                reasons.append("support_nonfinite")
            elif support[interval, seed] > maximum_support + 1e-12:
                reasons.append("support_distance_exceedance")
            elif effective[interval, seed] < float(gate.get("minimum_effective_sample_size", 1.0)):
                reasons.append("support_ess")
            elif rank[interval, seed] < float(gate.get("minimum_geometry_rank", 1)):
                reasons.append("support_geometry_rank")
            elif anisotropy[interval, seed] < float(gate.get("minimum_anisotropy", 1e-8)):
                reasons.append("support_anisotropy")
            elif not np.isfinite(reconstruction[interval, seed]):
                reasons.append("support_reconstruction_nonfinite")
            else:
                reasons.append("support_gate_failure")
        else:
            reasons.append("numerical_loss")
    return reasons, first_frames


def _mass_row(
    time_s: float,
    frame: int,
    trace: dict[str, Any],
    sources: np.ndarray,
    weights: np.ndarray,
    domain: dict[str, list[float]],
    destination: dict[str, Any],
) -> list[dict[str, Any]]:
    positions = np.asarray(trace["position"][frame], dtype=float)
    reliable = np.asarray(trace["reliability_history"][frame], dtype=bool)
    inside = _region_mask(positions, destination)
    in_domain = _domain_mask(positions, domain)
    reasons, first_frames = _first_failure_reasons(trace, len(weights))
    reason_array = np.asarray([item or "" for item in reasons], dtype=object)
    rows = []
    for source in sorted({int(value) for value in sources}):
        source_mask = sources == source
        masks: dict[str, np.ndarray] = {
            "inside_receiver": reliable & inside,
            "in_domain_unclassified": reliable & in_domain & ~inside,
            "outside_domain": reliable & ~in_domain,
        }
        for reason in sorted({item for item in reasons if item is not None}):
            masks[reason] = (~reliable) & (reason_array == reason) & (first_frames >= 0) & (first_frames <= frame)
        values = {
            name: float(np.sum(weights[source_mask & mask], dtype=np.float64))
            for name, mask in masks.items()
        }
        total = float(sum(values.values()))
        row = {
            "time_s": float(time_s),
            "frame": int(frame),
            "source_mk": source,
            **{f"mass_{name}_kg": value for name, value in values.items()},
            "total_represented_mass_kg": total,
        }
        rows.append(row)
    return rows


def _write_mass_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    preferred = ["time_s", "frame", "source_mk"]
    keys = preferred + [key for key in keys if key not in preferred]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _aggregate_final(rows: list[dict[str, Any]], represented_mass: float) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "mass_kg": {}, "closure_error_kg": None}
    final_frame = max(int(row["frame"]) for row in rows)
    selected = [row for row in rows if int(row["frame"]) == final_frame]
    columns = sorted({key for row in selected for key in row if key.startswith("mass_")})
    mass = {column: float(sum(float(row.get(column, 0.0)) for row in selected)) for column in columns}
    total = float(sum(mass.values()))
    return {
        "frame": final_frame,
        "time_s": float(selected[0]["time_s"]),
        "mass_kg": mass,
        "total_kg": total,
        "represented_initial_mass_kg": float(represented_mass),
        "closure_error_kg": float(represented_mass - total),
    }


def _config_summary(
    seed_count: int,
    substeps: int,
    trace: dict[str, Any],
    seeds: dict[str, Any],
    input_summary: dict[str, Any],
    mass_rows: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    reliability = np.asarray(trace["reliability_history"], dtype=bool)
    weights = np.asarray(seeds["mass_weight"], dtype=float)
    sources = np.asarray(seeds["source_mk"], dtype=np.int64)
    reasons, first_frames = _first_failure_reasons(trace, seed_count)
    reason_summary: dict[str, dict[str, Any]] = {}
    for reason in sorted({item for item in reasons if item is not None}):
        mask = np.asarray([item == reason for item in reasons], dtype=bool)
        reason_summary[reason] = {
            "seed_count": int(np.sum(mask)),
            "mass_kg": float(np.sum(weights[mask], dtype=np.float64)),
            "by_source_mk": {
                str(source): float(np.sum(weights[mask & (sources == source)], dtype=np.float64))
                for source in sorted({int(value) for value in sources[mask]})
            },
        }
    times = np.asarray(trace["time"], dtype=float)
    saved_dt = np.diff(times)
    actual_subdt = saved_dt / int(substeps)
    support_gate = np.asarray(trace["support_gate_pass"], dtype=bool)
    wall = np.asarray(trace["wall_crossing"], dtype=bool)
    visible = np.asarray(trace["minimum_visible_neighbours"], dtype=float)
    support = np.asarray(trace["nearest_support_distance"], dtype=float)
    finite_support = support[np.isfinite(support)]
    final_reliability_by_mass = float(
        np.sum(weights * reliability[-1], dtype=np.float64)
        / max(float(np.sum(weights)), 1e-30)
    )
    fluid_mass = float(input_summary["initial_fluid_mass_kg"])
    represented_mass = float(np.sum(weights, dtype=np.float64))
    final = _aggregate_final(mass_rows, represented_mass)
    return {
        "configuration": {
            "seed_count": int(seed_count),
            "substeps_per_saved_interval": int(substeps),
            "neighbours": NEIGHBOURS,
            "regularization_over_dp": REGULARIZATION_OVER_DP,
            "maximum_support_over_dp": MAXIMUM_SUPPORT_OVER_DP,
            "frame_stride": 1,
        },
        "execution_status": "completed",
        "frames": int(len(times)),
        "saved_cadence_median_s": float(np.median(saved_dt)),
        "actual_substep_dt_s": {
            "min": float(np.min(actual_subdt)),
            "median": float(np.median(actual_subdt)),
            "max": float(np.max(actual_subdt)),
        },
        "elapsed_seconds": float(elapsed_seconds),
        "seed_selection": seeds["selection"],
        "seed_source_counts": {
            str(source): int(np.sum(sources == source))
            for source in sorted({int(value) for value in sources})
        },
        "represented_initial_mass_kg": represented_mass,
        "initial_fluid_mass_kg": fluid_mass,
        "mass_weight_closure_error_kg": float(represented_mass - fluid_mass),
        "final_reliable_seed_count": int(np.sum(reliability[-1])),
        "final_reliable_mass_fraction": final_reliability_by_mass,
        "failure_reasons_first_failure": reason_summary,
        "first_failure_frame_by_seed": first_frames.tolist(),
        "support_gate_failure_events": int(np.size(support_gate) - np.count_nonzero(support_gate)),
        "wall_crossing_events": int(np.count_nonzero(wall)),
        "minimum_visible_neighbours": int(np.min(visible[np.isfinite(visible)])) if np.any(np.isfinite(visible)) else None,
        "support_distance_over_dp": {
            "median": float(np.median(finite_support) / input_summary["particle_spacing_m"])
            if len(finite_support) else None,
            "p95": float(np.quantile(finite_support, 0.95) / input_summary["particle_spacing_m"])
            if len(finite_support) else None,
        },
        "source_destination_final": final,
        "mass_ledger": {
            "rows": int(len(mass_rows)),
            "source_semantics": "initial Mk proxy; source label is not a post-mixing material identity",
        },
    }


def _run_one(
    seed_count: int,
    substeps: int,
    input_summary: dict[str, Any],
    barrier: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    seeds = weighted_stratified_seeds(H5_PATH, maximum=seed_count)
    started = time.perf_counter()
    trace = advect_hdf5(
        H5_PATH,
        seeds["position"],
        neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_OVER_DP * input_summary["particle_spacing_m"],
        maximum_support_distance=MAXIMUM_SUPPORT_OVER_DP * input_summary["particle_spacing_m"],
        frame_stride=1,
        substeps_per_interval=substeps,
        barrier_provider=barrier,
    )
    elapsed = time.perf_counter() - started
    if len(trace["time"]) != input_summary["frames"]:
        raise ValueError("tracer time axis length differs from solver HDF5")
    with h5py.File(H5_PATH, "r") as h5:
        solver_time = np.asarray(h5["time"][:], dtype=float)
    # The exact solver time axis is retained.  Nonuniform saved intervals are
    # allowed, but a tracer must use the same frame coordinates.
    if not np.allclose(trace["time"], solver_time, atol=1e-10, rtol=0.0):
        raise ValueError("tracer time axis differs from solver HDF5")
    rows: list[dict[str, Any]] = []
    destination = DESTINATION_SPEC["destinations"][0]
    sources = np.asarray(seeds["source_mk"], dtype=np.int64)
    weights = np.asarray(seeds["mass_weight"], dtype=float)
    for frame, time_s in enumerate(solver_time):
        rows.extend(_mass_row(
            float(time_s), frame, trace, sources, weights,
            input_summary["simulation_domain_m"], destination,
        ))
    return _config_summary(seed_count, substeps, trace, seeds, input_summary, rows, elapsed), rows


def _paired_substep_comparison(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (item["configuration"]["seed_count"], item["configuration"]["substeps_per_saved_interval"]): item
        for item in results
    }
    comparisons = []
    for seed_count in SEED_COUNTS:
        low = by_key.get((seed_count, 1))
        high = by_key.get((seed_count, 4))
        if low is None or high is None:
            continue
        low_mass = low["source_destination_final"]["mass_kg"]
        high_mass = high["source_destination_final"]["mass_kg"]
        columns = sorted(set(low_mass) | set(high_mass))
        delta = {
            column: float(high_mass.get(column, 0.0) - low_mass.get(column, 0.0))
            for column in columns
        }
        comparisons.append({
            "seed_count": seed_count,
            "comparison": "same physical case and same deterministic seed selection; 1 vs 4 tracer substeps",
            "final_mass_delta_4_minus_1_kg": delta,
            "max_absolute_final_mass_delta_kg": max((abs(value) for value in delta.values()), default=0.0),
        })
    return comparisons


def build_report(*, execute: bool = True) -> dict[str, Any]:
    record = _load_manifest_record()
    input_summary = _input_summary(record)
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if execute:
        barrier = sidecar_provider(SIDECAR_PATH)
        for seed_count in SEED_COUNTS:
            for substeps in SUBSTEPS:
                try:
                    summary, rows = _run_one(seed_count, substeps, input_summary, barrier)
                    ledger = ARTIFACT_ROOT / f"{CASE_ID}_seeds{seed_count}_substeps{substeps}_mass-ledger.csv"
                    _write_mass_csv(ledger, rows)
                    summary["mass_ledger"].update({
                        "path": _relative(ledger),
                        "sha256": _sha256(ledger),
                        "bytes": ledger.stat().st_size,
                    })
                    results.append(summary)
                except Exception as error:  # preserve a machine-readable partial handoff
                    errors.append({
                        "seed_count": seed_count,
                        "substeps_per_saved_interval": substeps,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    })
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": "R4_W06_TRACER_BOUNDED_EXPERIMENT",
        "scope": "one actual W06 HDF5/sidecar case; mass-weighted source/destination tracer audit",
        "execution_status": "completed" if len(results) == len(SEED_COUNTS) * len(SUBSTEPS) else (
            "prepared_only" if not execute else "partial_or_failed"
        ),
        "acceptance_status": "candidate_only_rejected",
        "formal_material_target_admitted": False,
        "validation_scope": [
            "W06_standard_slow_center actual release HDF5",
            "release-linked finite triangle boundary sidecar",
            "32 and 64 mass-weighted seeds",
            "1 and 4 explicit Heun substeps per saved interval",
            "source-by-destination mass ledger and first-failure reasons",
        ],
        "input": input_summary,
        "controls": {
            "seed_counts": list(SEED_COUNTS),
            "substeps_per_saved_interval": list(SUBSTEPS),
            "neighbours": NEIGHBOURS,
            "regularization_over_dp": REGULARIZATION_OVER_DP,
            "maximum_support_over_dp": MAXIMUM_SUPPORT_OVER_DP,
            "frame_stride": 1,
            "solver_is_not_rerun": True,
            "gpu_used": False,
            "cuda_used": False,
        },
        "candidate_boundary_policy": BOUNDARY_POLICY,
        "candidate_destination_spec": DESTINATION_SPEC,
        "results": results,
        "errors": errors,
        "paired_substep_comparisons": _paired_substep_comparison(results),
        "interpretation": {
            "source": "source_mk is initial Mk provenance only; it is not a post-mixing material identity",
            "wall": "sidecar triangles are used at every Heun substep with swept-wall rejection; formal wall-aware admission remains false",
            "destination": "inside_receiver is a candidate AABB; complement mass is reported rather than forced into a destination",
            "comparison": "only same-case, same-seed-count substep comparisons are made; no cross-resolution array-index matching",
            "release_decision": "this bounded result cannot promote a material task or trigger a 20-30 case tranche",
        },
        "open_blockers": [
            "candidate boundary policy is not linked into the production material writer",
            "the release sidecar uses triangle_mk as a component-label fallback rather than an explicit component registry",
            "release manifest has no accepted destination specification or source-destination closure",
            "implicit cap/rim/open-face semantics remain unresolved for the sidecar components",
            "support failures are reconstructed from current diagnostics; a full persisted per-step reason channel is still required",
            "no external physical material-transport observation is available",
        ],
    }
    REPORT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _write_markdown(payload)
    return payload


def _write_markdown(payload: dict[str, Any]) -> None:
    lines = [
        "# R4 W06 tracer bounded experiment",
        "",
        "状态：**candidate-only / rejected；不构成正式材料目标或物理验收。**",
        "",
        "本实验只复用 `W06_standard_slow_center` 已存在的 solver HDF5 和 release-linked finite-triangle sidecar，",
        "运行 32/64 个质量加权 seeds 与 1/4 个显式 Heun 子步，记录 source×destination 质量、支持门失败和 swept-wall 拒绝。",
        "没有启动 CFD、GenCase、CUDA 或 GPU。",
        "",
        "## 输入与语义",
        "",
        f"- HDF5：`{payload['input']['hdf5']}`，SHA-256 `{payload['input']['hdf5_sha256']}`。",
        f"- sidecar：`{payload['input']['sidecar']}`，SHA-256 `{payload['input']['sidecar_sha256']}`。",
        f"- 帧数/时长：`{payload['input']['frames']}` / `{payload['input']['time_end_s']:.6f} s`；保存 cadence 中位数 `{payload['input']['saved_cadence_median_s']:.9f} s`。",
        f"- 初始流体：`{payload['input']['initial_fluid_particles']}` 粒子、`{payload['input']['initial_fluid_mass_kg']:.9f} kg`。",
        f"- sidecar component labels：`{payload['input']['sidecar_component_label_dataset']}`（explicit registry={payload['input']['sidecar_component_labels_explicit']}）。",
        "- source label 只采用初始 `Mk`，不把它解释为混合后的材料身份。",
        "- `inside_receiver` 是候选 AABB；`in_domain_unclassified`、`outside_domain` 和显式失败原因均单独保留。",
        "",
        "## 结果",
        "",
        "| seeds | substeps | final reliable mass | wall-crossing events | support-gate failures | max support (p95/dp) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["results"]:
        config = item["configuration"]
        lines.append(
            f"| {config['seed_count']} | {config['substeps_per_saved_interval']} | "
            f"{item['final_reliable_mass_fraction']:.6f} | {item['wall_crossing_events']} | "
            f"{item['support_gate_failure_events']} | {item['support_distance_over_dp']['p95']} |"
        )
    if payload["errors"]:
        lines.extend(["", "执行错误：", ""])
        lines.extend(f"- `{item['seed_count']}×{item['substeps_per_saved_interval']}`：{item['error']}" for item in payload["errors"])
    lines.extend([
        "",
        "## Gate 结论",
        "",
        "- 四个配置全部完成时，结果仍只说明同一实际案例中的 wall-aware tracer 数值行为；不说明目的地真值。",
        "- sidecar 的有限三角面已实际参与每个子步，但 component 的 open-face/rim/supporting policy 尚未成为 release contract。",
        "- 只有在 destination specification、source-destination closure、完整 failure reason provenance 和物理锚点均闭合后，才可讨论 material target；本轮不允许生成 20–30 例 tranche。",
        "",
        f"机器可读结果：`{_relative(REPORT_JSON)}`。",
    ])
    REPORT_MD.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("audit", "run"), nargs="?", default="run")
    args = parser.parse_args()
    payload = build_report(execute=args.action == "run")
    print(json.dumps({
        "execution_status": payload["execution_status"],
        "acceptance_status": payload["acceptance_status"],
        "completed_configs": len(payload["results"]),
        "errors": payload["errors"],
        "report": _relative(REPORT_JSON),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
