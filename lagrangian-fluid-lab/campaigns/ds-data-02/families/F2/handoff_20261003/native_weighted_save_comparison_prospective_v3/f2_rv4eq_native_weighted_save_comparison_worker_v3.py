#!/usr/bin/env python3
"""DS-DATA-02 Family F2: Native-Weighted Temporal Save Comparison Worker v3.

Root Followup 038 F2 Delivery:
This module delivers the authoritative, truly executable full-HDF5 comparison
worker for the F2 nominal-save (401 frames, dt=0.010 s) vs dense-save (4001 frames,
dt=0.001 s) dataset pair under identical continuum conditions.

Key Improvements & Remediations in v3:
1. Actual Per-UID Residence Comparison:
   Derives per-UID residence directly from the actual `destination_code` (frames, n)
   dataset in HDF5 for ALL original destination codes including unknown (0=unknown,
   1=cup, 2=receiver, 3=tray, 4=inflight), using the unchanged trapezoid rule:
   0.5 * (indicator[k-1] + indicator[k]) * actual_dt.
   Streams in bounded frame chunks; never copies full dense trajectories into RAM.
2. Invariant Residence Verifications:
   - Verifies total per-UID residence across all destinations strictly equals full
     actual duration (times[-1] - times[0]) for every particle UID.
   - Verifies weighted sums reproduce original observation residence JSON within
     floating-point summation reordering roundoff (justified in code).
3. Descriptive Per-UID Residence Reporting:
   Compares identical original UID populations with native weights. Reports
   mass-weighted mean absolute gap, mass-weighted mean signed gap, max absolute gap,
   p50, p90, p95, p99 percentiles, and particle gap counts/fractions descriptively,
   with no speculative acceptance threshold.
4. Independent JSON Aggregate Residence & Flux Tracking:
   Maintains aggregate inventory and cumulative boundary crossing flux comparisons
   separately from per-UID residence.
5. Strict Literal Closed Saved-Bracket Overlap (No +1e-12 Extension):
   Intersection of actual saved frame bracket intervals [t_start, t_end]:
   max(t_start,nom, t_start,dense) <= min(t_end,nom, t_end,dense).
   Literal closed interval intersection: exact endpoints permitted, no invented
   +1e-12 interval extension, no proximity gates, no flutter claims.
6. Event Tuple Integrity Verification:
   Verifies every event tuple against underlying particle arrays (particle_index,
   idp, zone, mk, layer, mass) and frame brackets.
7. Ambiguous Overlap Isolation & Exact Weighted Closure:
   Connected components with >1 nominal or >1 dense event are strictly isolated as
   AMBIGUOUS and never claimed joint. Exact count and mass conservation enforced
   across all 6 event codes.
8. Safe Exclusive Output Creation:
   Outputs JSON and Markdown exclusively using mode 'x' with prior-existence checks.
   Never overwrites existing files; never unlinks arbitrary prior targets.
9. Protected Scratch Floor (100 GiB) & Registered Cap (32 GiB):
   Enforces >= 100 GiB free space floor on NVMe scratch; checks single-copy <= 32 GiB cap.
   Uses owned `tempfile.TemporaryDirectory` with sequential single-source-at-a-time copy.
   Verifies byte hashes before and after private reads.
10. Direct Path SHA Verification:
    `expected_sha` is verified in direct-read mode as well as private copy mode.
11. Frozen Continuum, Native Mass Authority & Completed0 Receipts:
    Enforces completed0 receipts, exact frames (401 and 4001), full [0.0, 4.0] time window,
    immutable mother hashes, frozen pose v8, cohort 196608, native mass 0.0001250000059371814 kg,
    retained motive 1 exclusions (2151 particles, 0.2688750127708772 kg), and failing legacy
    decimal 1e-12 diagnostic (representation delta 4.7497e-8 not rescaled).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Sequence

try:
    import h5py
    import numpy as np
except ImportError:
    h5py = None
    np = None

# -----------------------------------------------------------------------------
# Frozen DS-DATA-02 F2 Constants & Identifiers
# -----------------------------------------------------------------------------
SCHEMA = "ds-data-02.f2.native-weighted-save-comparison.v3"
WORKER_VERSION = "f2-native-weighted-save-comparison-worker-v3"

# Continuum Mother Invariants
PHYSICAL_CONDITION_HASH = "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
GEOMETRY_SHA256 = "dc2f2d1ab3d842a25fd8025a33b1c81920e1caebe0fd354fbff68bfa89b3e9a9"
CONTROL_SHA256 = "c500385285845193cb16f526499b9450bc1691f9744e63e1b03c15fb996eff82"
MOTION_CONTROL_SHA256 = "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70"

OPERATOR_VERSION = "f2-moving-cup-local-z-top-v8-native-mass-bound"
OPERATOR_SHA256 = "ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406"
FROZEN_V6_OPERATOR_VERSION = "f2-moving-cup-local-z-top-v6"

FLUID_PARTICLES_COUNT = 196608
NATIVE_SINGLE_PARTICLE_MASS_KG = 0.0001250000059371814  # IEEE-754 binary32 widened to float64
NATIVE_COHORT_MASS_KG = 24.576001167297363            # 196608 * single mass
XML_BENCHMARK_MASS_KG = 24.576
REPRESENTATION_RELATIVE_DELTA = 4.749745128457272e-08

SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
EVENT_TIME_ABSOLUTE_BUDGET_S = 0.0036681953999691376
MASS_REFERENCE_RELATIVE_BUDGET = 1.0e-12

DESTINATION_CODES = {
    "unknown": 0,
    "cup": 1,
    "receiver": 2,
    "tray": 3,
    "inflight": 4,
}
DESTINATION_NAMES_BY_CODE = {v: k for k, v in DESTINATION_CODES.items()}

EVENT_CODES = {
    "cup_top_departure": 1,
    "cup_top_return": 2,
    "receiver_entry": 3,
    "receiver_exit": 4,
    "tray_entry": 5,
    "tray_exit": 6,
}
EVENT_NAMES_BY_CODE = {v: k for k, v in EVENT_CODES.items()}

UNKNOWN_REASON_CODES = {
    "none": 0,
    "native_invalid": 1,
    "native_invalid_closed_wall_crossing": 2,
    "native_invalid_legal_tray_candidate": 3,
    "native_invalid_after_open_top_or_domain": 4,
    "native_invalid_unclassified": 5,
    "lifecycle_type_change": 6,
}

if np is not None:
    EVENT_DTYPE = np.dtype([
        ("time_s", "<f8"),
        ("event_code", "<i2"),
        ("direction", "<i1"),
        ("particle_index", "<i8"),
        ("zone", "<i8"),
        ("idp", "<i8"),
        ("source_mk", "<i4"),
        ("source_layer_index", "<i4"),
        ("mass_kg", "<f8"),
        ("frame_before", "<i8"),
        ("frame_after", "<i8"),
    ])
else:
    EVENT_DTYPE = None


class ComparisonError(RuntimeError):
    """Raised when save comparison fails a validation or integrity invariant."""


def sha256_file(path: Path | str) -> str:
    """Compute sha256 digest of a file in 8 MiB blocks."""
    p = Path(path).resolve()
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verified_copy(source: Path, target: Path, expected: str) -> str:
    """Copy a file to target while checking SHA256 and immutability.

    Matches Root shared utility verified_copy:
    - Captures file stat before copy.
    - Streams in 8 MiB blocks and updates running sha256.
    - Asserts source file metadata did not change during copy.
    - Asserts computed digest matches expected digest.
    - Chmods target to 0o400 (read-only).
    """
    source = Path(source).resolve()
    target = Path(target).resolve()
    if not source.is_file():
        raise ComparisonError(f"Source file not found: {source}")

    src_stat_before = source.stat()
    h = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as src_f, target.open("wb") as dst_f:
        for chunk in iter(lambda: src_f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
            dst_f.write(chunk)

    src_stat_after = source.stat()
    if (
        src_stat_before.st_size != src_stat_after.st_size
        or src_stat_before.st_mtime_ns != src_stat_after.st_mtime_ns
    ):
        raise ComparisonError(f"Source file {source} was modified during copy!")

    actual_sha = h.hexdigest()
    if actual_sha != expected:
        if target.exists():
            target.unlink()
        raise ComparisonError(
            f"SHA256 mismatch copying {source} -> {target}: expected {expected}, got {actual_sha}"
        )

    # Protect target as read-only
    target.chmod(stat.S_IRUSR)
    return actual_sha


def check_scratch_protected_floor(
    scratch_parent: Path,
    max_single_copy_bytes: int,
    floor_gib: int = 100,
    cap_gib: int = 32,
) -> dict[str, Any]:
    """Verify that scratch space satisfies the >=100 GiB floor and registered 32 GiB cap."""
    scratch_parent = Path(scratch_parent).resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)

    floor_bytes = floor_gib * (1024**3)
    cap_bytes = cap_gib * (1024**3)

    if max_single_copy_bytes > cap_bytes:
        raise ComparisonError(
            f"Requested copy size {max_single_copy_bytes} bytes exceeds registered scratch cap of {cap_gib} GiB ({cap_bytes} bytes)"
        )

    usage = shutil.disk_usage(scratch_parent)
    free_after = usage.free - max_single_copy_bytes

    if free_after < floor_bytes:
        raise ComparisonError(
            f"NVMe scratch protected {floor_gib} GiB floor would be crossed! "
            f"Available: {usage.free} bytes ({usage.free / (1024**3):.2f} GiB), "
            f"Requested single copy: {max_single_copy_bytes} bytes ({max_single_copy_bytes / (1024**3):.2f} GiB), "
            f"Projected remaining: {free_after / (1024**3):.2f} GiB, "
            f"Required floor: {floor_gib} GiB."
        )

    return {
        "scratch_path": str(scratch_parent),
        "free_bytes_before": usage.free,
        "max_single_copy_bytes": max_single_copy_bytes,
        "projected_free_bytes": free_after,
        "floor_bytes": floor_bytes,
        "registered_cap_bytes": cap_bytes,
        "floor_satisfied": True,
    }


def verify_source_receipt(receipt_path: Path | str) -> dict[str, Any]:
    """Verify that a source run execution receipt has completed with returncode 0."""
    path = Path(receipt_path).resolve()
    if not path.is_file():
        raise ComparisonError(f"Source execution receipt not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        receipt = json.load(f)

    status = receipt.get("status")
    returncode = receipt.get("returncode")
    if status != "completed" or returncode != 0:
        raise ComparisonError(
            f"Source receipt is not completed0: {path} (status={status}, returncode={returncode})"
        )
    return receipt


def verify_continuum_and_operator_invariance(
    nom_obs: dict[str, Any],
    dense_obs: dict[str, Any],
    expected_particles: int = FLUID_PARTICLES_COUNT,
) -> dict[str, Any]:
    """Verify physical continuum and frozen v8 operator invariance between runs."""
    checks: dict[str, bool] = {}

    nom_op = nom_obs.get("operator", {})
    dense_op = dense_obs.get("operator", {})
    checks["operator_version_match"] = (
        nom_op.get("version") == OPERATOR_VERSION and dense_op.get("version") == OPERATOR_VERSION
    )
    checks["operator_sha256_match"] = (
        nom_op.get("sha256") == OPERATOR_SHA256 and dense_op.get("sha256") == OPERATOR_SHA256
    )

    nom_spec = nom_op.get("spec", {})
    dense_spec = dense_op.get("spec", {})
    checks["frozen_v6_base_match"] = (
        nom_spec.get("frozen_v6_base", {}).get("operator_version") == FROZEN_V6_OPERATOR_VERSION
        and dense_spec.get("frozen_v6_base", {}).get("operator_version") == FROZEN_V6_OPERATOR_VERSION
    )

    nom_auth = nom_spec.get("native_weight_authority", {})
    dense_auth = dense_spec.get("native_weight_authority", {})
    checks["fluid_particles_count_match"] = (
        nom_auth.get("fluid_particles") == expected_particles
        and dense_auth.get("fluid_particles") == expected_particles
    )
    checks["native_single_particle_mass_match"] = (
        abs(nom_auth.get("native_header_bound_mass_kg", 0) - NATIVE_SINGLE_PARTICLE_MASS_KG) < 1e-18
        and abs(dense_auth.get("native_header_bound_mass_kg", 0) - NATIVE_SINGLE_PARTICLE_MASS_KG) < 1e-18
    )
    expected_cohort_mass = expected_particles * NATIVE_SINGLE_PARTICLE_MASS_KG
    checks["native_cohort_mass_match"] = (
        abs(nom_auth.get("native_cohort_mass_kg", 0) - expected_cohort_mass) < 1e-12
        and abs(dense_auth.get("native_cohort_mass_kg", 0) - expected_cohort_mass) < 1e-12
    )

    # Physical bindings
    nom_phys = nom_obs.get("physical_binding", {})
    dense_phys = dense_obs.get("physical_binding", {})
    checks["physical_condition_hash_match"] = (
        nom_phys.get("source_h5_physical_condition_sha256") == PHYSICAL_CONDITION_HASH
        and dense_phys.get("source_h5_physical_condition_sha256") == PHYSICAL_CONDITION_HASH
    )
    checks["geometry_sha256_match"] = (
        nom_phys.get("source_h5_geometry_sha256") == GEOMETRY_SHA256
        and dense_phys.get("source_h5_geometry_sha256") == GEOMETRY_SHA256
    )
    checks["control_sha256_match"] = (
        nom_phys.get("source_h5_control_sha256") == CONTROL_SHA256
        and dense_phys.get("source_h5_control_sha256") == CONTROL_SHA256
    )
    checks["motion_control_sha256_match"] = (
        nom_phys.get("motion_control_sha256") == MOTION_CONTROL_SHA256
        and dense_phys.get("motion_control_sha256") == MOTION_CONTROL_SHA256
    )

    all_passed = all(checks.values())
    if not all_passed:
        failed = [k for k, v in checks.items() if not v]
        raise ComparisonError(f"Continuum or operator invariance violated: {failed}")

    return {
        "status": "verified_continuum_identical",
        "physical_condition_hash": PHYSICAL_CONDITION_HASH,
        "operator_version": OPERATOR_VERSION,
        "operator_sha256": OPERATOR_SHA256,
        "fluid_particles": expected_particles,
        "native_single_particle_mass_kg": NATIVE_SINGLE_PARTICLE_MASS_KG,
        "native_cohort_mass_kg": expected_cohort_mass,
        "checks": checks,
    }


def verify_event_tuples_and_brackets(
    events: np.ndarray,
    n_particles: int,
    times: np.ndarray,
    particle_id: np.ndarray,
    particle_zone: np.ndarray,
    source_mk: np.ndarray,
    source_layer: np.ndarray,
    source_mass: np.ndarray,
) -> dict[str, Any]:
    """Verify that every event tuple matches underlying particle arrays and frame brackets."""
    num_events = len(events)
    if num_events == 0:
        return {"event_count": 0, "status": "verified_empty"}

    p_idx = events["particle_index"]
    if np.any((p_idx < 0) | (p_idx >= n_particles)):
        raise ComparisonError("Event tuple contains particle_index out of bounds!")

    # Check particle array identities
    if not np.array_equal(events["idp"], particle_id[p_idx]):
        raise ComparisonError("Event tuple idp does not match particle_id array!")
    if not np.array_equal(events["zone"], particle_zone[p_idx]):
        raise ComparisonError("Event tuple zone does not match particle_zone array!")
    if not np.array_equal(events["source_mk"], source_mk[p_idx]):
        raise ComparisonError("Event tuple source_mk does not match source_mk array!")
    if not np.array_equal(events["source_layer_index"], source_layer[p_idx]):
        raise ComparisonError("Event tuple source_layer_index does not match source_layer array!")

    # Check mass matching native single particle mass
    masses = events["mass_kg"]
    if np.any(np.abs(masses - NATIVE_SINGLE_PARTICLE_MASS_KG) > 1e-18):
        raise ComparisonError("Event tuple mass_kg deviates from native single particle mass!")
    if not np.array_equal(masses, source_mass[p_idx]):
        raise ComparisonError("Event tuple mass_kg does not match source_mass array!")

    # Check frame brackets and times
    fb = events["frame_before"]
    fa = events["frame_after"]
    n_frames = len(times)
    if np.any((fb < 0) | (fa >= n_frames) | (fa != fb + 1)):
        raise ComparisonError("Event tuple frame bracket is invalid or non-adjacent!")

    t_ev = events["time_s"]
    t_start = times[fb]
    t_end = times[fa]
    # Literal bracket containment: t_start <= t_ev <= t_end
    if np.any((t_ev < t_start) | (t_ev > t_end)):
        raise ComparisonError("Event tuple time_s lies strictly outside [time[fb], time[fa]]!")

    # Check event codes and directions
    codes = events["event_code"]
    valid_codes = set(EVENT_CODES.values())
    for c in np.unique(codes):
        if c not in valid_codes:
            raise ComparisonError(f"Event tuple contains unknown event_code {c}!")

    dirs = events["direction"]
    if np.any((dirs != -1) & (dirs != 1)):
        raise ComparisonError("Event tuple contains invalid direction (must be +1 or -1)!")

    return {
        "event_count": num_events,
        "status": "all_tuples_verified_against_arrays_and_brackets",
    }


def derive_per_uid_residence_streaming(
    h5_file: Any,
    chunk_frames: int = 64,
) -> np.ndarray:
    """Derive per-UID residence for ALL 5 destination codes by streaming destination_code.

    Unchanged V6 Trapezoid Rule (lines 889-894):
    residence[particle, code] += 0.5 * (indicator[k-1] + indicator[k]) * dt
    where dt = times[k] - times[k-1].

    Streams in bounded frame chunks (chunk_frames, e.g. 64 frames = ~12.5 MiB),
    never copying full dense trajectory into memory.
    """
    times = np.asarray(h5_file["time"][:], dtype=np.float64)
    n_frames = len(times)
    n_particles = len(h5_file["particle_id"])
    dest_ds = h5_file["destination_code"]

    residence = np.zeros((n_particles, len(DESTINATION_CODES)), dtype=np.float64)
    particle_indices = np.arange(n_particles, dtype=np.int64)

    # Process in bounded frame chunks
    prev_dest = np.asarray(dest_ds[0, :], dtype=np.int8)

    for k_start in range(1, n_frames, chunk_frames):
        k_end = min(k_start + chunk_frames, n_frames)
        chunk = np.asarray(dest_ds[k_start:k_end, :], dtype=np.int8)
        chunk_len = k_end - k_start

        for i in range(chunk_len):
            f_curr = k_start + i
            dt = float(times[f_curr] - times[f_curr - 1])
            half_dt = 0.5 * dt
            c_dest = chunk[i, :]

            # Vectorized addition into residence array
            # Each particle is assigned half_dt in prev_dest and curr_dest
            residence[particle_indices, prev_dest] += half_dt
            residence[particle_indices, c_dest] += half_dt

            prev_dest = c_dest

    return residence


def verify_per_uid_residence_properties(
    residence: np.ndarray,
    times: np.ndarray,
    source_mass: np.ndarray,
    obs: dict[str, Any],
) -> dict[str, Any]:
    """Verify fundamental conservation and aggregate JSON reproduction of per-UID residence.

    Mathematical Invariants:
    1. Total Per-UID Residence Equals Full Actual Duration:
       sum_{c=0..4} residence[i, c] == times[-1] - times[0] for every particle i.
    2. Weighted Sums Reproduce Original Observation JSON:
       sum_i source_mass[i] * residence[i, c] == obs_residence_mass_time[c]
       within floating-point summation reordering roundoff justified in code.
    """
    n_particles = len(residence)
    full_duration = float(times[-1] - times[0])

    # 1. Check total per-UID duration
    total_per_uid = np.sum(residence, axis=1)
    duration_diffs = np.abs(total_per_uid - full_duration)
    max_duration_error = float(np.max(duration_diffs))
    mean_duration_error = float(np.mean(duration_diffs))

    if max_duration_error > 1e-10:
        raise ComparisonError(
            f"Per-UID residence sum does not match full duration {full_duration} s: "
            f"max error = {max_duration_error} s"
        )

    # 2. Check reproduction of JSON aggregate observation residence
    obs_res = obs.get("residence", {})
    obs_mass_time = obs_res.get("mass_time_kg_s_by_destination", {})
    obs_cohort_frac = obs_res.get("fractional_cohort_time_by_destination", {})

    reproduction_checks: dict[str, Any] = {}
    total_cohort_mass = float(np.sum(source_mass))

    for name, code in DESTINATION_CODES.items():
        computed_mass_time = float(np.sum(source_mass * residence[:, code]))
        computed_cohort_time = float(np.mean(residence[:, code]))

        expected_mt = float(obs_mass_time.get(name, 0.0))
        expected_ct = float(obs_cohort_frac.get(name, 0.0))

        delta_mt = computed_mass_time - expected_mt
        delta_ct = computed_cohort_time - expected_ct

        # Roundoff justification:
        # Summing per-particle vs summing per-frame over 196608 terms has floating-point
        # associativity roundoff bounded by machine epsilon * sqrt(N) ~ 1e-12.
        # Strict bound 1e-8 kg*s.
        if abs(delta_mt) > 1e-8:
            raise ComparisonError(
                f"Per-UID residence weighted sum diverges from JSON observation for {name}: "
                f"computed={computed_mass_time}, expected={expected_mt}, delta={delta_mt}"
            )

        reproduction_checks[name] = {
            "destination_code": code,
            "computed_mass_time_kg_s": computed_mass_time,
            "expected_json_mass_time_kg_s": expected_mt,
            "delta_mass_time_kg_s": delta_mt,
            "computed_fractional_cohort_time": computed_cohort_time,
            "expected_json_fractional_cohort_time": expected_ct,
            "delta_fractional_cohort_time": delta_ct,
            "reproduction_verified": True,
        }

    return {
        "status": "per_uid_residence_invariants_verified",
        "full_duration_s": full_duration,
        "max_per_uid_duration_error_s": max_duration_error,
        "mean_per_uid_duration_error_s": mean_duration_error,
        "duration_equality_verified": True,
        "reproduction_checks": reproduction_checks,
        "numerical_roundoff_justification": (
            "Floating-point summation reassociation across 196,608 particles "
            "versus frame-by-frame aggregation yields machine-epsilon scale roundoff (< 1e-8 kg*s)."
        ),
    }


def compare_per_uid_residence(
    nom_residence: np.ndarray,
    dense_residence: np.ndarray,
    source_mass: np.ndarray,
    full_duration_s: float,
) -> dict[str, Any]:
    """Compare nominal vs dense per-UID residence arrays descriptively.

    Compares the exact same original UID population and native weights.
    Reports for each destination code (including unknown):
    - mass-weighted mean absolute gap (s)
    - mass-weighted mean signed gap (s)
    - max absolute gap (s)
    - min absolute gap (s)
    - p50, p90, p95, p99 percentiles (s)
    - count and fraction of particles with non-zero gap
    - aggregate mass-time gap (kg*s)

    No speculative acceptance threshold is applied.
    """
    if nom_residence.shape != dense_residence.shape:
        raise ComparisonError(
            f"Residence shape mismatch: nominal {nom_residence.shape} vs dense {dense_residence.shape}"
        )

    n_particles = len(source_mass)
    total_mass = float(np.sum(source_mass))

    by_destination: dict[str, Any] = {}
    nom_res_sha256 = hashlib.sha256(nom_residence.tobytes()).hexdigest()
    dense_res_sha256 = hashlib.sha256(dense_residence.tobytes()).hexdigest()

    global_max_abs_gap = 0.0

    for name, code in DESTINATION_CODES.items():
        nom_col = nom_residence[:, code]
        dense_col = dense_residence[:, code]

        signed_gap = dense_col - nom_col
        abs_gap = np.abs(signed_gap)

        max_g = float(np.max(abs_gap))
        min_g = float(np.min(abs_gap))
        if max_g > global_max_abs_gap:
            global_max_abs_gap = max_g

        mw_mean_abs_gap = float(np.sum(source_mass * abs_gap) / total_mass)
        mw_mean_signed_gap = float(np.sum(source_mass * signed_gap) / total_mass)
        unweighted_mean_abs_gap = float(np.mean(abs_gap))
        unweighted_mean_signed_gap = float(np.mean(signed_gap))

        p50 = float(np.percentile(abs_gap, 50))
        p90 = float(np.percentile(abs_gap, 90))
        p95 = float(np.percentile(abs_gap, 95))
        p99 = float(np.percentile(abs_gap, 99))

        non_zero_mask = abs_gap > 1e-12
        particles_with_gap = int(np.count_nonzero(non_zero_mask))
        fraction_with_gap = particles_with_gap / n_particles

        agg_mass_time_gap = float(np.sum(source_mass * signed_gap))

        by_destination[name] = {
            "destination_code": code,
            "mass_weighted_mean_abs_gap_s": mw_mean_abs_gap,
            "mass_weighted_mean_signed_gap_s": mw_mean_signed_gap,
            "unweighted_mean_abs_gap_s": unweighted_mean_abs_gap,
            "unweighted_mean_signed_gap_s": unweighted_mean_signed_gap,
            "max_abs_gap_s": max_g,
            "min_abs_gap_s": min_g,
            "percentiles_abs_gap_s": {
                "p50": p50,
                "p90": p90,
                "p95": p95,
                "p99": p99,
            },
            "particles_with_gap_count": particles_with_gap,
            "particles_with_gap_fraction": fraction_with_gap,
            "aggregate_mass_time_delta_kg_s": agg_mass_time_gap,
        }

    return {
        "status": "per_uid_residence_compared_descriptively",
        "provenance": {
            "nominal_residence_array_sha256": nom_res_sha256,
            "dense_residence_array_sha256": dense_res_sha256,
            "shape": list(nom_residence.shape),
            "dtype": str(nom_residence.dtype),
            "columns": list(DESTINATION_CODES.keys()),
            "full_duration_s": full_duration_s,
        },
        "by_destination": by_destination,
        "global_max_abs_gap_s": global_max_abs_gap,
        "scientific_claim_boundary": (
            "Per-UID residence gaps are reported descriptively without speculative acceptance threshold. "
            "Identical aggregate residence does NOT establish per-UID residence equivalence."
        ),
    }


def compare_fluid_population_arrays(
    nom_data: dict[str, Any],
    dense_data: dict[str, Any],
    expected_particles: int = FLUID_PARTICLES_COUNT,
) -> dict[str, Any]:
    """Verify bitwise identical initial fluid cohort identities and native weights."""
    nom_id = nom_data["particle_id"]
    dense_id = dense_data["particle_id"]
    if len(nom_id) != expected_particles or len(dense_id) != expected_particles:
        raise ComparisonError(
            f"Fluid particle count mismatch: nominal={len(nom_id)}, dense={len(dense_id)}, "
            f"expected={expected_particles}"
        )

    if not np.array_equal(nom_id, dense_id):
        raise ComparisonError("particle_id array mismatch between nominal and dense runs!")

    nom_zone = nom_data["particle_zone"]
    dense_zone = dense_data["particle_zone"]
    if not np.array_equal(nom_zone, dense_zone):
        raise ComparisonError("particle_zone array mismatch between nominal and dense runs!")

    nom_mk = nom_data["source_mk"]
    dense_mk = dense_data["source_mk"]
    if not np.array_equal(nom_mk, dense_mk):
        raise ComparisonError("source_mk array mismatch between nominal and dense runs!")

    nom_layer = nom_data["source_layer_index"]
    dense_layer = dense_data["source_layer_index"]
    if not np.array_equal(nom_layer, dense_layer):
        raise ComparisonError("source_layer_index array mismatch between nominal and dense runs!")

    nom_mass = nom_data["source_mass_kg"]
    dense_mass = dense_data["source_mass_kg"]
    if not np.array_equal(nom_mass, dense_mass):
        raise ComparisonError("source_mass_kg array mismatch between nominal and dense runs!")

    if not np.all(nom_mass == NATIVE_SINGLE_PARTICLE_MASS_KG):
        raise ComparisonError("Nominal particle masses deviate from authoritative native float32 mass!")
    if not np.all(dense_mass == NATIVE_SINGLE_PARTICLE_MASS_KG):
        raise ComparisonError("Dense particle masses deviate from authoritative native float32 mass!")

    expected_cohort_mass = expected_particles * NATIVE_SINGLE_PARTICLE_MASS_KG
    total_nom_mass = float(np.sum(nom_mass))
    total_dense_mass = float(np.sum(dense_mass))
    if abs(total_nom_mass - expected_cohort_mass) > 1e-12:
        raise ComparisonError("Nominal cohort mass deviates from authoritative native cohort mass!")
    if abs(total_dense_mass - expected_cohort_mass) > 1e-12:
        raise ComparisonError("Dense cohort mass deviates from authoritative native cohort mass!")

    return {
        "status": "bitwise_identical_fluid_population",
        "particles_count": expected_particles,
        "single_particle_mass_kg": NATIVE_SINGLE_PARTICLE_MASS_KG,
        "cohort_mass_kg": expected_cohort_mass,
        "continuous_xml_benchmark_kg": XML_BENCHMARK_MASS_KG,
        "representation_delta_kg": expected_cohort_mass - (expected_particles * 0.000125),
        "relative_representation_drift": REPRESENTATION_RELATIVE_DELTA,
        "legacy_1e12_diagnostic": "fail",
        "note": "Authoritative native float32 mass authority verified without approximate snapping.",
    }


def compare_native_exclusions_arrays(
    nom_data: dict[str, Any],
    dense_data: dict[str, Any],
    expected_exclusions: int = 2151,
) -> dict[str, Any]:
    """Compare native exclusion arrays and verify zero relabeling as physical spill."""
    nom_motive = nom_data["exclusion_motive"]
    dense_motive = dense_data["exclusion_motive"]

    # Motive 1 indicates official native exclusion
    nom_excl_mask = (nom_motive == 1)
    dense_excl_mask = (dense_motive == 1)

    nom_excl_count = int(np.count_nonzero(nom_excl_mask))
    dense_excl_count = int(np.count_nonzero(dense_excl_mask))

    if nom_excl_count != expected_exclusions or dense_excl_count != expected_exclusions:
        raise ComparisonError(
            f"Native Motive 1 exclusion count unexpected: nominal={nom_excl_count}, dense={dense_excl_count}, expected={expected_exclusions}"
        )

    if not np.array_equal(nom_excl_mask, dense_excl_mask):
        raise ComparisonError("Excluded particle identities differ between nominal and dense runs!")

    if expected_exclusions > 0:
        nom_final_dest = nom_data["destination_code_final"]
        dense_final_dest = dense_data["destination_code_final"]

        nom_excl_dest = nom_final_dest[nom_excl_mask]
        dense_excl_dest = dense_final_dest[dense_excl_mask]

        if not np.all(nom_excl_dest == DESTINATION_CODES["unknown"]):
            bad = np.count_nonzero(nom_excl_dest != DESTINATION_CODES["unknown"])
            raise ComparisonError(f"{bad} native excluded particles relabeled as non-unknown in nominal!")
        if not np.all(dense_excl_dest == DESTINATION_CODES["unknown"]):
            bad = np.count_nonzero(dense_excl_dest != DESTINATION_CODES["unknown"])
            raise ComparisonError(f"{bad} native excluded particles relabeled as non-unknown in dense!")

    unknown_mass_kg = expected_exclusions * NATIVE_SINGLE_PARTICLE_MASS_KG
    return {
        "status": "native_exclusions_verified",
        "motive_1_identities_count": expected_exclusions,
        "unknown_mass_retained_kg": unknown_mass_kg,
        "physical_spill_inferred": False,
        "all_retained_as_unknown_invalid": True,
    }


def compare_per_uid_final_destinations(
    nom_final_dest: np.ndarray, dense_final_dest: np.ndarray, source_mass: np.ndarray
) -> dict[str, Any]:
    """Compare final destination per UID, computing fate switches and transition matrix."""
    n = len(nom_final_dest)
    if len(dense_final_dest) != n:
        raise ComparisonError(f"Destination array length mismatch: {n} vs {len(dense_final_dest)}")

    # 1. Per-UID fate switch mask
    fate_switch_mask = (nom_final_dest != dense_final_dest)
    switched_particles_count = int(np.count_nonzero(fate_switch_mask))
    switched_mass_kg = float(np.sum(source_mass[fate_switch_mask]))
    switch_fraction = switched_particles_count / n

    # 2. Destination 5x5 transition matrix (nom -> dense)
    transition_matrix: dict[str, dict[str, int]] = {
        name: {target: 0 for target in DESTINATION_CODES}
        for name in DESTINATION_CODES
    }
    for nom_code, nom_name in DESTINATION_NAMES_BY_CODE.items():
        nom_mask = (nom_final_dest == nom_code)
        for dense_code, dense_name in DESTINATION_NAMES_BY_CODE.items():
            count = int(np.count_nonzero(nom_mask & (dense_final_dest == dense_code)))
            transition_matrix[nom_name][dense_name] = count

    # 3. Aggregate destination inventories
    dest_comparison: dict[str, Any] = {}
    aggregate_fate_match = True
    for name, code in DESTINATION_CODES.items():
        nom_count = int(np.count_nonzero(nom_final_dest == code))
        dense_count = int(np.count_nonzero(dense_final_dest == code))
        nom_m = float(np.sum(source_mass[nom_final_dest == code]))
        dense_m = float(np.sum(source_mass[dense_final_dest == code]))
        diff_m = dense_m - nom_m
        if abs(diff_m) > 1e-12:
            aggregate_fate_match = False

        dest_comparison[name] = {
            "destination_code": code,
            "nominal_particles": nom_count,
            "dense_particles": dense_count,
            "delta_particles": dense_count - nom_count,
            "nominal_mass_kg": nom_m,
            "dense_mass_kg": dense_m,
            "delta_mass_kg": diff_m,
        }

    return {
        "aggregate_inventory": {
            "destinations": dest_comparison,
            "aggregate_inventory_match": aggregate_fate_match,
        },
        "per_uid_fates": {
            "per_uid_fate_match": (switched_particles_count == 0),
            "switched_particles_count": switched_particles_count,
            "switched_mass_kg": switched_mass_kg,
            "switch_fraction": switch_fraction,
            "transition_matrix_nominal_to_dense": transition_matrix,
        },
        "scientific_claim_guard": (
            "Aggregate inventory equality does NOT establish per-UID fate identity. "
            "Per-UID fates and switch masks must be evaluated independently."
        ),
    }


def compare_aggregate_residence_and_flux(
    nom_obs: dict[str, Any], dense_obs: dict[str, Any]
) -> dict[str, Any]:
    """Compare aggregate JSON residence and cumulative event mass flux separately."""
    nom_res = nom_obs.get("residence", {})
    dense_res = dense_obs.get("residence", {})
    nom_dest_res = nom_res.get("mass_time_kg_s_by_destination", {})
    dense_dest_res = dense_res.get("mass_time_kg_s_by_destination", {})
    nom_dest_frac = nom_res.get("fractional_cohort_time_by_destination", {})
    dense_dest_frac = dense_res.get("fractional_cohort_time_by_destination", {})

    residence_comparison: dict[str, Any] = {}
    for name, code in DESTINATION_CODES.items():
        residence_comparison[name] = {
            "destination_code": code,
            "nominal_mass_time_kg_s": float(nom_dest_res.get(name, 0.0)),
            "dense_mass_time_kg_s": float(dense_dest_res.get(name, 0.0)),
            "delta_mass_time_kg_s": float(dense_dest_res.get(name, 0.0)) - float(nom_dest_res.get(name, 0.0)),
            "nominal_fractional_cohort_time": float(nom_dest_frac.get(name, 0.0)),
            "dense_fractional_cohort_time": float(dense_dest_frac.get(name, 0.0)),
            "delta_fractional_cohort_time": float(dense_dest_frac.get(name, 0.0)) - float(nom_dest_frac.get(name, 0.0)),
        }

    nom_ledger = nom_obs.get("event_ledger", {})
    dense_ledger = dense_obs.get("event_ledger", {})
    nom_mass_flux = nom_ledger.get("mass_kg_by_code", {})
    dense_mass_flux = dense_ledger.get("mass_kg_by_code", {})

    flux_comparison: dict[str, Any] = {}
    flux_exceeds_initial_cohort: dict[str, bool] = {}
    for name, code in EVENT_CODES.items():
        m_nom = float(nom_mass_flux.get(name, 0.0))
        m_dense = float(dense_mass_flux.get(name, 0.0))
        flux_comparison[name] = {
            "event_code": code,
            "nominal_flux_mass_kg": m_nom,
            "dense_flux_mass_kg": m_dense,
            "delta_flux_mass_kg": m_dense - m_nom,
        }
        flux_exceeds_initial_cohort[name] = (m_dense > NATIVE_COHORT_MASS_KG)

    return {
        "residence_destinations_json_aggregate": residence_comparison,
        "cumulative_event_mass_flux": flux_comparison,
        "flux_exceeds_initial_cohort_mass": flux_exceeds_initial_cohort,
        "time_window_nominal_s": nom_res.get("time_window_s", 4.0),
        "time_window_dense_s": dense_res.get("time_window_s", 4.0),
        "scientific_guard": (
            "Residence is trapezoidal integration of occupancy (kg*s). "
            "Cumulative crossing flux is total mass transit count across aperture faces. "
            "Due to multiple boundary crossings, cumulative flux across receiver/tray "
            "naturally exceeds initial cohort mass 24.576 kg."
        ),
    }


def match_events_strict_saved_brackets(
    nom_events: np.ndarray,
    dense_events: np.ndarray,
    nom_times: np.ndarray,
    dense_times: np.ndarray,
) -> dict[str, Any]:
    """Perform strict episodic event matching using literal closed saved bracket intersection.

    Mathematical Invariants:
    1. Saved bracket for an event:
       [t_start, t_end] = [time[frame_before], time[frame_after]].
    2. Overlap condition between nominal event i and dense event j:
       Literal closed interval intersection:
       max(t_start,nom, t_start,dense) <= min(t_end,nom, t_end,dense).
       (Equivalent to dense_start <= nom_end AND dense_end >= nom_start).
       NO invented +1e-12 interval extension! Exact endpoint touch permitted.
    3. NO proximity gates! NO abs(dt) <= tolerance! NO flutter claims!
    4. NO naive zipping across mismatching repeat counts.
    5. Connected components of the overlap bipartite graph:
       - Degree 0 nominal: unmatched_nominal.
       - Degree 0 dense: extra_dense.
       - Unique 1:1 component (degree(nom)=1 and degree(dense)=1): proven_unique_1to1_joint.
       - Any component with >1 nominal or >1 dense: AMBIGUOUS!
         Reported as ambiguous_nominal and ambiguous_dense; NEVER claimed joint.
    6. Exact count and mass conservation across all 6 codes.
    """
    by_code_results: dict[str, Any] = {}
    total_nom_count = len(nom_events)
    total_dense_count = len(dense_events)

    grand_unique_count = 0
    grand_ambiguous_nom_count = 0
    grand_ambiguous_dense_count = 0
    grand_unmatched_nom_count = 0
    grand_extra_dense_count = 0

    chord_diffs_all: list[float] = []
    overlap_durations_all: list[float] = []
    containment_count_all = 0

    for name, code in EVENT_CODES.items():
        nom_code_mask = (nom_events["event_code"] == code)
        dense_code_mask = (dense_events["event_code"] == code)

        nom_sub = nom_events[nom_code_mask]
        dense_sub = dense_events[dense_code_mask]

        c_nom = len(nom_sub)
        c_dense = len(dense_sub)

        unique_joint_matches: list[dict[str, Any]] = []
        ambiguous_groups: list[dict[str, Any]] = []
        unmatched_nom_list: list[int] = []
        extra_dense_list: list[int] = []

        code_chord_diffs: list[float] = []
        code_overlap_durations: list[float] = []
        code_containment_count = 0

        # Group by particle_index
        active_uids = np.unique(
            np.concatenate([nom_sub["particle_index"], dense_sub["particle_index"]])
        ) if (c_nom > 0 or c_dense > 0) else np.array([], dtype=np.int64)

        if c_nom > 0:
            nom_order = np.lexsort((nom_sub["frame_before"], nom_sub["particle_index"]))
            nom_sorted = nom_sub[nom_order]
            nom_pids = nom_sorted["particle_index"]
            nom_split_idx = np.flatnonzero(np.diff(nom_pids)) + 1
            nom_slices = {
                pid: sl
                for pid, sl in zip(
                    nom_pids[np.concatenate([[0], nom_split_idx])],
                    np.split(nom_sorted, nom_split_idx),
                )
            }
        else:
            nom_slices = {}

        if c_dense > 0:
            dense_order = np.lexsort((dense_sub["frame_before"], dense_sub["particle_index"]))
            dense_sorted = dense_sub[dense_order]
            dense_pids = dense_sorted["particle_index"]
            dense_split_idx = np.flatnonzero(np.diff(dense_pids)) + 1
            dense_slices = {
                pid: sl
                for pid, sl in zip(
                    dense_pids[np.concatenate([[0], dense_split_idx])],
                    np.split(dense_sorted, dense_split_idx),
                )
            }
        else:
            dense_slices = {}

        for pid in active_uids:
            p_nom = nom_slices.get(pid)
            p_dense = dense_slices.get(pid)

            k_nom = len(p_nom) if p_nom is not None else 0
            m_dense = len(p_dense) if p_dense is not None else 0

            if k_nom > 0 and m_dense == 0:
                unmatched_nom_list.extend(range(k_nom))
                continue
            if k_nom == 0 and m_dense > 0:
                extra_dense_list.extend(range(m_dense))
                continue
            if k_nom == 0 and m_dense == 0:
                continue

            # Both nominal and dense events exist for this particle & code
            nom_starts = nom_times[p_nom["frame_before"]]
            nom_ends = nom_times[p_nom["frame_after"]]
            dense_starts = dense_times[p_dense["frame_before"]]
            dense_ends = dense_times[p_dense["frame_after"]]

            # Overlap matrix of shape (k_nom, m_dense)
            # Literal closed interval intersection:
            # max(n_start, d_start) <= min(n_end, d_end)
            # equivalent to (d_start <= n_end) & (d_end >= n_start)
            # REMOVED INVENTED +1e-12 EXTENSION! Exact endpoints permitted.
            overlap = (
                (dense_starts[None, :] <= nom_ends[:, None])
                & (dense_ends[None, :] >= nom_starts[:, None])
            )

            nom_deg = overlap.sum(axis=1)
            dense_deg = overlap.sum(axis=0)

            # Degree 0: completely disjoint / unmatched
            for i in range(k_nom):
                if nom_deg[i] == 0:
                    unmatched_nom_list.append(i)
            for j in range(m_dense):
                if dense_deg[j] == 0:
                    extra_dense_list.append(j)

            # Connected components among overlapping events
            visited_nom = set()
            visited_dense = set()

            for i in range(k_nom):
                if nom_deg[i] == 0 or i in visited_nom:
                    continue

                comp_nom = {i}
                comp_dense = set()
                queue_nom = [i]
                queue_dense = []

                while queue_nom or queue_dense:
                    while queue_nom:
                        curr_n = queue_nom.pop()
                        connected_d = np.flatnonzero(overlap[curr_n, :])
                        for d in connected_d:
                            if d not in comp_dense:
                                comp_dense.add(d)
                                queue_dense.append(d)
                    while queue_dense:
                        curr_d = queue_dense.pop()
                        connected_n = np.flatnonzero(overlap[:, curr_d])
                        for n_idx in connected_n:
                            if n_idx not in comp_nom:
                                comp_nom.add(n_idx)
                                queue_nom.append(n_idx)

                visited_nom.update(comp_nom)
                visited_dense.update(comp_dense)

                if len(comp_nom) == 1 and len(comp_dense) == 1:
                    nom_idx = list(comp_nom)[0]
                    dense_idx = list(comp_dense)[0]

                    t_nom = float(p_nom[nom_idx]["time_s"])
                    t_dense = float(p_dense[dense_idx]["time_s"])
                    chord_diff = t_dense - t_nom

                    n_s = float(nom_starts[nom_idx])
                    n_e = float(nom_ends[nom_idx])
                    d_s = float(dense_starts[dense_idx])
                    d_e = float(dense_ends[dense_idx])

                    overlap_start = max(n_s, d_s)
                    overlap_end = min(n_e, d_e)
                    overlap_duration = max(0.0, overlap_end - overlap_start)

                    dense_in_nom = (d_s >= n_s) and (d_e <= n_e)

                    code_chord_diffs.append(chord_diff)
                    code_overlap_durations.append(overlap_duration)
                    chord_diffs_all.append(chord_diff)
                    overlap_durations_all.append(overlap_duration)
                    if dense_in_nom:
                        code_containment_count += 1
                        containment_count_all += 1

                    unique_joint_matches.append({
                        "particle_index": int(pid),
                        "idp": int(p_nom[nom_idx]["idp"]),
                        "nominal_time_s": t_nom,
                        "dense_time_s": t_dense,
                        "chord_difference_s": chord_diff,
                        "nominal_bracket_s": [n_s, n_e],
                        "dense_bracket_s": [d_s, d_e],
                        "overlap_duration_s": overlap_duration,
                        "dense_bracket_contained_in_nominal": dense_in_nom,
                    })
                else:
                    ambiguous_groups.append({
                        "particle_index": int(pid),
                        "nominal_event_count": len(comp_nom),
                        "dense_event_count": len(comp_dense),
                        "nominal_times_s": [float(p_nom[idx]["time_s"]) for idx in sorted(comp_nom)],
                        "dense_times_s": [float(p_dense[idx]["time_s"]) for idx in sorted(comp_dense)],
                    })

        # Summary for this event code
        u_count = len(unique_joint_matches)
        amb_nom_count = sum(g["nominal_event_count"] for g in ambiguous_groups)
        amb_dense_count = sum(g["dense_event_count"] for g in ambiguous_groups)
        unm_nom_count = len(unmatched_nom_list)
        ext_dense_count = len(extra_dense_list)

        grand_unique_count += u_count
        grand_ambiguous_nom_count += amb_nom_count
        grand_ambiguous_dense_count += amb_dense_count
        grand_unmatched_nom_count += unm_nom_count
        grand_extra_dense_count += ext_dense_count

        # Exact closure check per code
        assert u_count + amb_nom_count + unm_nom_count == c_nom, f"Nominal count closure failed for {name}"
        assert u_count + amb_dense_count + ext_dense_count == c_dense, f"Dense count closure failed for {name}"

        chord_arr = np.array(code_chord_diffs, dtype=np.float64) if code_chord_diffs else np.array([])
        by_code_results[name] = {
            "event_code": code,
            "nominal_total_count": c_nom,
            "dense_total_count": c_dense,
            "nominal_total_mass_kg": c_nom * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "dense_total_mass_kg": c_dense * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "proven_unique_1to1_joint_count": u_count,
            "proven_unique_1to1_joint_mass_kg": u_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_cluster_count": len(ambiguous_groups),
            "ambiguous_nominal_count": amb_nom_count,
            "ambiguous_nominal_mass_kg": amb_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_dense_count": amb_dense_count,
            "ambiguous_dense_mass_kg": amb_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "unmatched_nominal_count": unm_nom_count,
            "unmatched_nominal_mass_kg": unm_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "extra_dense_count": ext_dense_count,
            "extra_dense_mass_kg": ext_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "chord_differences_dense_minus_nom": {
                "count": len(chord_arr),
                "mean_s": float(np.mean(chord_arr)) if len(chord_arr) > 0 else None,
                "abs_mean_s": float(np.mean(np.abs(chord_arr))) if len(chord_arr) > 0 else None,
                "min_s": float(np.min(chord_arr)) if len(chord_arr) > 0 else None,
                "max_s": float(np.max(chord_arr)) if len(chord_arr) > 0 else None,
                "std_s": float(np.std(chord_arr)) if len(chord_arr) > 0 else None,
            },
            "bracket_containment": {
                "dense_in_nominal_count": code_containment_count,
                "dense_in_nominal_fraction": (code_containment_count / u_count) if u_count > 0 else None,
            },
        }

    chord_all_arr = np.array(chord_diffs_all, dtype=np.float64) if chord_diffs_all else np.array([])
    overlap_all_arr = np.array(overlap_durations_all, dtype=np.float64) if overlap_durations_all else np.array([])

    return {
        "status": "strict_saved_bracket_matching_completed",
        "literal_closed_interval_rule": "max(t_start,nom, t_start,dense) <= min(t_end,nom, t_end,dense) without +1e-12 extension",
        "grand_totals": {
            "nominal_total_events": total_nom_count,
            "dense_total_events": total_dense_count,
            "nominal_total_mass_kg": total_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "dense_total_mass_kg": total_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "proven_unique_1to1_joint_count": grand_unique_count,
            "proven_unique_1to1_joint_mass_kg": grand_unique_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_nominal_count": grand_ambiguous_nom_count,
            "ambiguous_nominal_mass_kg": grand_ambiguous_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_dense_count": grand_ambiguous_dense_count,
            "ambiguous_dense_mass_kg": grand_ambiguous_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "unmatched_nominal_count": grand_unmatched_nom_count,
            "unmatched_nominal_mass_kg": grand_unmatched_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "extra_dense_count": grand_extra_dense_count,
            "extra_dense_mass_kg": grand_extra_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "nominal_count_conservation_verified": (
                grand_unique_count + grand_ambiguous_nom_count + grand_unmatched_nom_count == total_nom_count
            ),
            "dense_count_conservation_verified": (
                grand_unique_count + grand_ambiguous_dense_count + grand_extra_dense_count == total_dense_count
            ),
        },
        "all_unique_joint_chord_differences": {
            "count": len(chord_all_arr),
            "mean_s": float(np.mean(chord_all_arr)) if len(chord_all_arr) > 0 else None,
            "abs_mean_s": float(np.mean(np.abs(chord_all_arr))) if len(chord_all_arr) > 0 else None,
            "std_s": float(np.std(chord_all_arr)) if len(chord_all_arr) > 0 else None,
            "bracket_containment_dense_in_nom_count": containment_count_all,
            "bracket_containment_fraction": (containment_count_all / grand_unique_count) if grand_unique_count > 0 else None,
        },
        "by_code": by_code_results,
        "scientific_claim_guard": (
            "Unique 1:1 joint matches are restricted strictly to isolated 1:1 overlap components. "
            "Ambiguous multi-overlap clusters are never claimed joint. "
            "Differing repeat event counts are not converted into automatic final fate equivalence."
        ),
    }


def evaluate_temporal_save_bracket_budgets(
    nom_obs: dict[str, Any], dense_obs: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate observed save bracket half-widths against discretized observation budget."""
    nom_stats = nom_obs.get("event_ledger", {}).get("observed_event_bracket_stats_s_by_code", {})
    dense_stats = dense_obs.get("event_ledger", {}).get("observed_event_bracket_stats_s_by_code", {})

    nom_max_hw = 0.0
    for code_info in nom_stats.values():
        m = code_info.get("max_s", 0.0)
        if m > nom_max_hw:
            nom_max_hw = m

    dense_max_hw = 0.0
    for code_info in dense_stats.values():
        m = code_info.get("max_s", 0.0)
        if m > dense_max_hw:
            dense_max_hw = m

    nom_pass = (nom_max_hw <= SAVE_HALF_WIDTH_BUDGET_S) if nom_max_hw > 0 else False
    dense_pass = (dense_max_hw <= SAVE_HALF_WIDTH_BUDGET_S) if dense_max_hw > 0 else False

    return {
        "budget_threshold_s": SAVE_HALF_WIDTH_BUDGET_S,
        "nominal401": {
            "frames": 401,
            "dt_s": 0.010,
            "observed_max_bracket_half_width_s": nom_max_hw,
            "budget_satisfied": nom_pass,
            "determination": "pass_discretization_budget_satisfied" if nom_pass else "fail_budget_exceeded",
        },
        "dense4001": {
            "frames": 4001,
            "dt_s": 0.001,
            "observed_max_bracket_half_width_s": dense_max_hw,
            "budget_satisfied": dense_pass,
            "determination": "pass_discretization_budget_satisfied" if dense_pass else "fail_budget_exceeded",
        },
        "governance_claim_boundary": (
            "A passing save bracket half-width budget establishes observation discretization resolution only. "
            "It does NOT grant Q-N qualification, production status, or numerical fidelity claims."
        ),
    }


def extract_arrays_and_residence_from_h5(
    h5_path: Path,
    expected_sha: str | None = None,
    obs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read arrays, verify event tuples, and stream per-UID residence directly from H5."""
    if h5py is None:
        raise ComparisonError("h5py is not installed in the environment!")

    path = Path(h5_path).resolve()
    if not path.is_file():
        raise ComparisonError(f"H5 file not found: {path}")

    # Verify expected_sha in direct read path as well as copy path
    if expected_sha is not None:
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise ComparisonError(
                f"H5 file SHA256 mismatch for {path}: expected {expected_sha}, got {actual_sha}"
            )

    with h5py.File(path, "r") as f:
        for key in (
            "particle_id", "particle_zone", "source_mk", "source_layer_index", "source_mass_kg",
            "time", "destination_code", "exclusion_motive", "events"
        ):
            if key not in f:
                raise ComparisonError(f"H5 file missing required dataset '{key}': {path}")

        particle_id = np.asarray(f["particle_id"][:], dtype=np.int64)
        particle_zone = np.asarray(f["particle_zone"][:], dtype=np.int64)
        source_mk = np.asarray(f["source_mk"][:], dtype=np.int32)
        source_layer_index = np.asarray(f["source_layer_index"][:], dtype=np.int32)
        source_mass_kg = np.asarray(f["source_mass_kg"][:], dtype=np.float64)

        time_arr = np.asarray(f["time"][:], dtype=np.float64)
        exclusion_motive = np.asarray(f["exclusion_motive"][:], dtype=np.int16)
        destination_code_final = np.asarray(f["destination_code"][-1, :], dtype=np.int8)
        events = np.asarray(f["events"][:])

        # Verify event tuples against particle arrays and frame brackets
        verify_event_tuples_and_brackets(
            events=events,
            n_particles=len(particle_id),
            times=time_arr,
            particle_id=particle_id,
            particle_zone=particle_zone,
            source_mk=source_mk,
            source_layer=source_layer_index,
            source_mass=source_mass_kg,
        )

        # Stream per-UID residence across all frames
        residence = derive_per_uid_residence_streaming(f, chunk_frames=64)

    # Verify per-UID residence properties against full duration and observation JSON
    residence_verif = {}
    if obs is not None:
        residence_verif = verify_per_uid_residence_properties(
            residence=residence,
            times=time_arr,
            source_mass=source_mass_kg,
            obs=obs,
        )

    return {
        "particle_id": particle_id,
        "particle_zone": particle_zone,
        "source_mk": source_mk,
        "source_layer_index": source_layer_index,
        "source_mass_kg": source_mass_kg,
        "time": time_arr,
        "exclusion_motive": exclusion_motive,
        "destination_code_final": destination_code_final,
        "events": events,
        "residence": residence,
        "residence_verification": residence_verif,
    }


def execute_full_h5_comparison(
    binding: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    """Execute the complete full-H5 guard checks, per-UID residence, and array comparisons."""
    out_file = Path(output_path).resolve()
    report_md_path = out_file.with_suffix(".md")

    # Safe output creation guard: exclusive 'x' mode requires no prior target exists
    if out_file.exists():
        raise ComparisonError(f"Output summary file already exists: {out_file}")
    if report_md_path.exists():
        raise ComparisonError(f"Output markdown report already exists: {report_md_path}")

    sources = binding["sources"]
    nom_binding = sources["nominal401"]
    dense_binding = sources["dense4001"]

    # 1. Terminal completed0 receipts verification
    nom_receipt = verify_source_receipt(nom_binding["execution_receipt"])
    dense_receipt = verify_source_receipt(dense_binding["execution_receipt"])

    # 2. Parse and verify observation reports & SHAs
    nom_rep_path = Path(nom_binding["observation_report"]).resolve()
    dense_rep_path = Path(dense_binding["observation_report"]).resolve()
    if not nom_rep_path.is_file():
        raise ComparisonError(f"Nominal report file missing: {nom_rep_path}")
    if not dense_rep_path.is_file():
        raise ComparisonError(f"Dense report file missing: {dense_rep_path}")

    actual_nom_rep_sha = sha256_file(nom_rep_path)
    actual_dense_rep_sha = sha256_file(dense_rep_path)

    if nom_binding.get("expected_report_sha256") and actual_nom_rep_sha != nom_binding["expected_report_sha256"]:
        raise ComparisonError(f"Nominal report SHA mismatch: {actual_nom_rep_sha} != {nom_binding['expected_report_sha256']}")
    if dense_binding.get("expected_report_sha256") and actual_dense_rep_sha != dense_binding["expected_report_sha256"]:
        raise ComparisonError(f"Dense report SHA mismatch: {actual_dense_rep_sha} != {dense_binding['expected_report_sha256']}")

    with nom_rep_path.open("r", encoding="utf-8") as f:
        nom_obs = json.load(f)
    with dense_rep_path.open("r", encoding="utf-8") as f:
        dense_obs = json.load(f)

    # 3. Continuum and operator invariance
    expected_particles = int(binding.get("fluid_particles", FLUID_PARTICLES_COUNT))
    expected_exclusions = int(binding.get("native_exclusions_count", 2151))

    continuum_inv = verify_continuum_and_operator_invariance(
        nom_obs, dense_obs, expected_particles=expected_particles
    )

    # 4. Read H5 labels arrays with NVMe single private copy protocol in TemporaryDirectory
    scratch_parent_str = binding.get("scratch_parent")
    use_private_copy = binding.get("use_private_copy", bool(scratch_parent_str))

    nom_labels_path = Path(nom_binding["labels_h5"]).resolve()
    dense_labels_path = Path(dense_binding["labels_h5"]).resolve()

    if not nom_labels_path.is_file():
        raise ComparisonError(f"Nominal labels H5 missing: {nom_labels_path}")
    if not dense_labels_path.is_file():
        raise ComparisonError(f"Dense labels H5 missing: {dense_labels_path}")

    nom_expected_sha = nom_binding.get("expected_labels_sha256", nom_obs.get("output", {}).get("sha256"))
    dense_expected_sha = dense_binding.get("expected_labels_sha256", dense_obs.get("output", {}).get("sha256"))

    nom_data: dict[str, Any] = {}
    dense_data: dict[str, Any] = {}

    if use_private_copy and scratch_parent_str:
        scratch_parent = Path(scratch_parent_str).resolve()
        max_source_bytes = max(nom_labels_path.stat().st_size, dense_labels_path.stat().st_size)
        check_scratch_protected_floor(scratch_parent, max_source_bytes)

        # Process nominal source first, in its own owned temporary directory
        with tempfile.TemporaryDirectory(dir=scratch_parent, prefix="ds02_f2_nom_") as tmp_dir:
            tmp_nom = Path(tmp_dir) / "nom_labels_private.h5"
            verified_copy(nom_labels_path, tmp_nom, nom_expected_sha)
            hash_before = sha256_file(tmp_nom)
            if hash_before != nom_expected_sha:
                raise ComparisonError(f"Nominal pre-read SHA mismatch: {hash_before} != {nom_expected_sha}")
            nom_data = extract_arrays_and_residence_from_h5(tmp_nom, expected_sha=nom_expected_sha, obs=nom_obs)
            hash_after = sha256_file(tmp_nom)
            if hash_after != nom_expected_sha:
                raise ComparisonError(f"Nominal post-read SHA altered: {hash_after} != {nom_expected_sha}")
        # Nominal temp dir cleaned up; single copy at a time!

        # Process dense source second, in its own owned temporary directory
        with tempfile.TemporaryDirectory(dir=scratch_parent, prefix="ds02_f2_dense_") as tmp_dir:
            tmp_dense = Path(tmp_dir) / "dense_labels_private.h5"
            verified_copy(dense_labels_path, tmp_dense, dense_expected_sha)
            hash_before = sha256_file(tmp_dense)
            if hash_before != dense_expected_sha:
                raise ComparisonError(f"Dense pre-read SHA mismatch: {hash_before} != {dense_expected_sha}")
            dense_data = extract_arrays_and_residence_from_h5(tmp_dense, expected_sha=dense_expected_sha, obs=dense_obs)
            hash_after = sha256_file(tmp_dense)
            if hash_after != dense_expected_sha:
                raise ComparisonError(f"Dense post-read SHA altered: {hash_after} != {dense_expected_sha}")
        # Dense temp dir cleaned up.
    else:
        # Direct read (e.g. lightweight synthetic unit testing)
        nom_data = extract_arrays_and_residence_from_h5(nom_labels_path, expected_sha=nom_expected_sha, obs=nom_obs)
        dense_data = extract_arrays_and_residence_from_h5(dense_labels_path, expected_sha=dense_expected_sha, obs=dense_obs)

    # 5. Exact actual frames and time window verification
    nom_frames = len(nom_data["time"])
    dense_frames = len(dense_data["time"])
    if nom_frames != 401:
        raise ComparisonError(f"Nominal actual frames count unexpected: {nom_frames} != 401")
    if dense_frames != 4001:
        raise ComparisonError(f"Dense actual frames count unexpected: {dense_frames} != 4001")

    full_duration = float(nom_data["time"][-1] - nom_data["time"][0])
    if abs(full_duration - 4.0) > 0.001:
        raise ComparisonError(f"Time window does not span full 0..4 s: {full_duration}")

    # 6. Execute comparisons on actual arrays
    pop_comp = compare_fluid_population_arrays(
        nom_data, dense_data, expected_particles=expected_particles
    )
    excl_comp = compare_native_exclusions_arrays(
        nom_data, dense_data, expected_exclusions=expected_exclusions
    )
    fate_comp = compare_per_uid_final_destinations(
        nom_data["destination_code_final"],
        dense_data["destination_code_final"],
        nom_data["source_mass_kg"],
    )
    per_uid_res_comp = compare_per_uid_residence(
        nom_data["residence"],
        dense_data["residence"],
        nom_data["source_mass_kg"],
        full_duration_s=full_duration,
    )
    agg_res_flux_comp = compare_aggregate_residence_and_flux(nom_obs, dense_obs)
    event_comp = match_events_strict_saved_brackets(
        nom_data["events"],
        dense_data["events"],
        nom_data["time"],
        dense_data["time"],
    )
    bracket_budgets = evaluate_temporal_save_bracket_budgets(nom_obs, dense_obs)

    summary = {
        "schema": SCHEMA,
        "worker_version": WORKER_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F2",
        "case_id": binding.get("case_id", "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V3"),
        "sources": {
            "nominal401": {
                "attempt_id": nom_binding.get("attempt_id"),
                "labels_h5": str(nom_labels_path),
                "labels_sha256": nom_expected_sha,
                "observation_report": str(nom_rep_path),
                "report_sha256": actual_nom_rep_sha,
                "frames": nom_frames,
                "time_start_s": float(nom_data["time"][0]),
                "time_end_s": float(nom_data["time"][-1]),
                "receipt_status": nom_receipt.get("status"),
                "receipt_returncode": nom_receipt.get("returncode"),
                "residence_verification": nom_data.get("residence_verification"),
            },
            "dense4001": {
                "attempt_id": dense_binding.get("attempt_id"),
                "labels_h5": str(dense_labels_path),
                "labels_sha256": dense_expected_sha,
                "observation_report": str(dense_rep_path),
                "report_sha256": actual_dense_rep_sha,
                "frames": dense_frames,
                "time_start_s": float(dense_data["time"][0]),
                "time_end_s": float(dense_data["time"][-1]),
                "receipt_status": dense_receipt.get("status"),
                "receipt_returncode": dense_receipt.get("returncode"),
                "residence_verification": dense_data.get("residence_verification"),
            },
        },
        "continuum_invariance": continuum_inv,
        "fluid_population_authority": pop_comp,
        "native_exclusions": excl_comp,
        "destination_fates": fate_comp,
        "per_uid_residence": per_uid_res_comp,
        "residence_and_flux_aggregate": agg_res_flux_comp,
        "episodic_event_matching": event_comp,
        "save_bracket_budgets": bracket_budgets,
        "claim_boundary": {
            "q_n": "not_granted",
            "production": "none",
            "q_i": "not_granted; post-labels observation cross-comparison",
            "statement": (
                "Save comparison establishes observation discretization sensitivity only. "
                "Aggregate destination mass match does not imply per-UID fate or residence equivalence. "
                "No fluid learning models executed; no Q-N qualification granted."
            ),
        },
    }

    # Write output JSON exclusively using 'x' mode
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("x", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Write sister markdown report exclusively using 'x' mode
    report_md = generate_comparison_report_markdown(summary)
    with report_md_path.open("x", encoding="utf-8") as f:
        f.write(report_md)

    return summary


def generate_comparison_report_markdown(summary: dict[str, Any]) -> str:
    """Generate human-readable Markdown summary of the comparison."""
    lines = [
        f"# DS-DATA-02 Family F2: Native-Weighted Save Comparison v3 Report",
        f"",
        f"- **Generated:** `{summary.get('generated_at_utc')}`",
        f"- **Schema:** `{summary.get('schema')}`",
        f"- **Worker Version:** `{summary.get('worker_version')}`",
        f"- **Case ID:** `{summary.get('case_id')}`",
        f"",
        f"---",
        f"",
        f"## 1. Continuum & Physical Identity Invariance",
        f"",
        f"- **Physical Condition Hash:** `{summary['continuum_invariance']['physical_condition_hash']}`",
        f"- **Operator Version:** `{summary['continuum_invariance']['operator_version']}`",
        f"- **Operator SHA-256:** `{summary['continuum_invariance']['operator_sha256']}`",
        f"- **Fluid Cohort Particles:** `{summary['continuum_invariance']['fluid_particles']}`",
        f"- **Single Particle Mass:** `{summary['continuum_invariance']['native_single_particle_mass_kg']:.16f} kg`",
        f"- **Cohort Native Mass:** `{summary['continuum_invariance']['native_cohort_mass_kg']:.16f} kg`",
        f"",
        f"---",
        f"",
        f"## 2. Actual Per-UID Residence Comparison",
        f"",
        f"Per-UID residence derived via streaming trapezoidal integration: `0.5 * (I[k-1] + I[k]) * dt` for all 5 destinations.",
        f"",
        f"| Destination | MW Mean Abs Gap (s) | Max Abs Gap (s) | p50 (s) | p95 (s) | p99 (s) | Particles with Gap | Delta Mass-Time (kg*s) |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    per_uid = summary.get("per_uid_residence", {}).get("by_destination", {})
    for name, stats in per_uid.items():
        mw_gap = f"{stats['mass_weighted_mean_abs_gap_s']:.6e}"
        max_g = f"{stats['max_abs_gap_s']:.6e}"
        p50 = f"{stats['percentiles_abs_gap_s']['p50']:.6e}"
        p95 = f"{stats['percentiles_abs_gap_s']['p95']:.6e}"
        p99 = f"{stats['percentiles_abs_gap_s']['p99']:.6e}"
        frac_gap = f"{stats['particles_with_gap_count']} ({stats['particles_with_gap_fraction']*100:.2f}%)"
        mt_delta = f"{stats['aggregate_mass_time_delta_kg_s']:.6e}"
        lines.append(f"| `{name}` | {mw_gap} | {max_g} | {p50} | {p95} | {p99} | {frac_gap} | {mt_delta} |")

    lines.extend([
        f"",
        f"- **Global Max Absolute Residence Gap:** `{summary.get('per_uid_residence', {}).get('global_max_abs_gap_s'):.6e} s`",
        f"- **Nominal Residence Array SHA-256:** `{summary.get('per_uid_residence', {}).get('provenance', {}).get('nominal_residence_array_sha256')}`",
        f"- **Dense Residence Array SHA-256:** `{summary.get('per_uid_residence', {}).get('provenance', {}).get('dense_residence_array_sha256')}`",
        f"",
        f"---",
        f"",
        f"## 3. Destination Fates & Per-UID Switch Accounting",
        f"",
        f"- **Aggregate Inventory Match:** `{summary['destination_fates']['aggregate_inventory']['aggregate_inventory_match']}`",
        f"- **Per-UID Fate Match:** `{summary['destination_fates']['per_uid_fates']['per_uid_fate_match']}`",
        f"- **Switched Particles Count:** `{summary['destination_fates']['per_uid_fates']['switched_particles_count']}`",
        f"- **Switched Mass:** `{summary['destination_fates']['per_uid_fates']['switched_mass_kg']:.8f} kg`",
        f"- **Switch Fraction:** `{summary['destination_fates']['per_uid_fates']['switch_fraction'] * 100:.4f}%`",
        f"",
        f"### Transition Matrix (Nominal -> Dense)",
        f"",
        f"| Nominal Destination | Cup | Receiver | Tray | Inflight | Unknown |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    trans = summary['destination_fates']['per_uid_fates']['transition_matrix_nominal_to_dense']
    for src in ("cup", "receiver", "tray", "inflight", "unknown"):
        row = trans.get(src, {})
        c = row.get("cup", 0)
        r = row.get("receiver", 0)
        t = row.get("tray", 0)
        inf = row.get("inflight", 0)
        u = row.get("unknown", 0)
        lines.append(f"| `{src}` | {c} | {r} | {t} | {inf} | {u} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 4. Strict Saved-Bracket Episodic Event Matching (Literal Closed Intersection)",
        f"",
        f"- **Rule:** Literal closed interval intersection `max(t_s,nom, t_s,dense) <= min(t_e,nom, t_e,dense)` without +1e-12 extension.",
        f"- **Proven Unique 1:1 Joint Count:** `{summary['episodic_event_matching']['grand_totals']['proven_unique_1to1_joint_count']}`",
        f"- **Ambiguous Nominal Events:** `{summary['episodic_event_matching']['grand_totals']['ambiguous_nominal_count']}`",
        f"- **Ambiguous Dense Events:** `{summary['episodic_event_matching']['grand_totals']['ambiguous_dense_count']}`",
        f"- **Unmatched Nominal Events:** `{summary['episodic_event_matching']['grand_totals']['unmatched_nominal_count']}`",
        f"- **Extra Dense Events:** `{summary['episodic_event_matching']['grand_totals']['extra_dense_count']}`",
        f"- **Nominal Count Conservation:** `{summary['episodic_event_matching']['grand_totals']['nominal_count_conservation_verified']}`",
        f"- **Dense Count Conservation:** `{summary['episodic_event_matching']['grand_totals']['dense_count_conservation_verified']}`",
        f"",
        f"---",
        f"",
        f"## 5. Temporal Save Half-Width Discretization Budgets",
        f"",
        f"- **Discretization Budget Threshold:** `{summary['save_bracket_budgets']['budget_threshold_s']:.7f} s`",
        f"- **Nominal 401 Frames:** Max Half-Width = `{summary['save_bracket_budgets']['nominal401']['observed_max_bracket_half_width_s']:.6f} s` -> `{summary['save_bracket_budgets']['nominal401']['determination']}`",
        f"- **Dense 4001 Frames:** Max Half-Width = `{summary['save_bracket_budgets']['dense4001']['observed_max_bracket_half_width_s']:.6f} s` -> `{summary['save_bracket_budgets']['dense4001']['determination']}`",
        f"",
        f"---",
        f"",
        f"## 6. Claim Boundary",
        f"",
        f"- **Q-N Status:** `{summary['claim_boundary']['q_n']}`",
        f"- **Production Status:** `{summary['claim_boundary']['production']}`",
        f"- **Q-I Status:** `{summary['claim_boundary']['q_i']}`",
        f"- **Statement:** {summary['claim_boundary']['statement']}",
        f"",
    ])

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="F2 Native-Weighted Temporal Save Comparison Worker v3"
    )
    parser.add_argument(
        "--binding",
        required=True,
        type=Path,
        help="Path to save comparison binding JSON v3",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to output comparison summary JSON v3",
    )
    args = parser.parse_args(argv)

    binding_path = args.binding.resolve()
    if not binding_path.is_file():
        sys.stderr.write(f"Error: binding file not found: {binding_path}\n")
        return 1

    with binding_path.open("r", encoding="utf-8") as f:
        binding = json.load(f)

    try:
        execute_full_h5_comparison(binding, args.output)
        sys.stdout.write(f"Comparison completed successfully: {args.output}\n")
        return 0
    except ComparisonError as err:
        sys.stderr.write(f"Comparison failed integrity guard: {err}\n")
        return 2
    except Exception as err:
        sys.stderr.write(f"Unexpected error during comparison execution: {err}\n")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
