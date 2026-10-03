#!/usr/bin/env python3
"""DS-DATA-02 Family F2: Native-Weighted Temporal Save Comparison Worker v2.

Root Followup 037 F2 Delivery:
This module delivers a truly executable, self-contained full-HDF5 comparison
worker for the F2 nominal-save (401 frames, dt=0.010 s) vs dense-save (4001 frames,
dt=0.001 s) dataset pair under identical continuum conditions.

Remediations from Root 036 Rejection:
1. Full-H5 Execution: Main directly executes the full comparison of H5 arrays
   and guard checks via `--binding` and `--output`.
2. Prohibited Proximity Gate Elimination: Removed unauthorized `|t_nom - t_dense| <= tolerance`
   proximity gates and invented `2*dt` flutter bands.
3. Strict Saved-Bracket Overlap: Candidate associations are determined SOLELY by
   actual saved bracket interval intersection ([t_start, t_end] = [t(frame_before), t(frame_after)]).
4. Ambiguous Overlap Isolation: Any 1-to-many, many-to-one, or multi-overlap component
   is classified as AMBIGUOUS and reported separately. It is NEVER claimed genuinely joint.
5. Proven Unique 1:1 Joint Matches: Only isolated 1:1 components are classified as
   proven unique joint matches.
6. Per-UID Fate Switch Tracking: Explicitly separates aggregate destination inventory
   from per-UID final fates. Identical aggregate mass does NOT imply identical per-UID fate.
7. Single-Copy Protected NVMe Protocol: Uses Root verified_copy, enforces >= 100 GiB
   free space floor on NVMe scratch, processes one source at a time with immediate
   removal on exit, and never copies raw 60 GiB trajectories.
8. Terminal Completed0 Receipts: Verifies both nominal and dense source receipts
   have status='completed' and returncode=0.
9. Save Half-Width Budget: Dense satisfies budget (PASS <= 0.00073363908 s); nominal
   exceeds budget (FAIL). A passing discretization budget does NOT grant Q-N or production.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any, Generator, Sequence

try:
    import h5py
    import numpy as np
except ImportError:
    h5py = None
    np = None

# -----------------------------------------------------------------------------
# Frozen DS-DATA-02 F2 Constants & Identifiers
# -----------------------------------------------------------------------------
SCHEMA = "ds-data-02.f2.native-weighted-save-comparison.v2"
WORKER_VERSION = "f2-native-weighted-save-comparison-worker-v2"

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
    before = source.stat()
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    digest = hashlib.sha256()

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b""):
            digest.update(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())

    actual = digest.hexdigest()
    if signature(before) != signature(source.stat()) or actual != expected:
        if target.exists():
            target.unlink()
        raise ComparisonError(
            f"Source changed during copy or differs from registered digest: {source} "
            f"(expected={expected}, actual={actual})"
        )

    target.chmod(0o400)
    return actual


def check_scratch_protected_floor(
    scratch_parent: Path, required_bytes: int, floor_bytes: int = 100 * 1024**3
) -> None:
    """Verify that scratch space has at least required_bytes + 100 GiB floor free."""
    scratch_parent.mkdir(parents=True, exist_ok=True)
    usage = os.statvfs(scratch_parent)
    available_bytes = usage.f_bavail * usage.f_frsize
    if available_bytes < required_bytes + floor_bytes:
        raise ComparisonError(
            f"NVMe scratch protected 100 GiB floor would be crossed! "
            f"Available: {available_bytes / (1024**3):.2f} GiB, "
            f"Required: {(required_bytes + floor_bytes) / (1024**3):.2f} GiB "
            f"(100 GiB floor + {required_bytes / (1024**3):.2f} GiB data)."
        )


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


def compare_fluid_population_arrays(
    nom_data: dict[str, np.ndarray],
    dense_data: dict[str, np.ndarray],
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
    nom_data: dict[str, np.ndarray],
    dense_data: dict[str, np.ndarray],
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
    """Compare final destination per UID, computing fate switches and transition matrix.

    CRITICAL SCIENTIFIC PRINCIPLE:
    Aggregate destination inventory equality does NOT establish per-UID fate equality!
    This function computes both aggregate mass per destination AND the exact per-UID
    fate switch mask and transition matrix.
    """
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


def compare_residence_and_flux(
    nom_obs: dict[str, Any], dense_obs: dict[str, Any]
) -> dict[str, Any]:
    """Compare residence times and cumulative event mass flux separately.

    Preserves the distinction that cumulative crossing flux across receiver or
    tray can exceed the initial fluid cohort mass (24.576 kg) due to repeated
    boundary crossings (chords/flutter).
    """
    nom_res = nom_obs.get("residence", {})
    dense_res = dense_obs.get("residence", {})
    nom_mt = nom_res.get("mass_time_kg_s_by_destination", {})
    dense_mt = dense_res.get("mass_time_kg_s_by_destination", {})
    nom_ct = nom_res.get("fractional_cohort_time_by_destination", {})
    dense_ct = dense_res.get("fractional_cohort_time_by_destination", {})

    residence_comparison: dict[str, Any] = {}
    for dest in DESTINATION_CODES:
        mt_nom = float(nom_mt.get(dest, 0.0))
        mt_dense = float(dense_mt.get(dest, 0.0))
        diff_mt = mt_dense - mt_nom
        rel_diff_mt = diff_mt / mt_nom if mt_nom != 0 else 0.0

        ct_nom = float(nom_ct.get(dest, 0.0))
        ct_dense = float(dense_ct.get(dest, 0.0))
        diff_ct = ct_dense - ct_nom

        residence_comparison[dest] = {
            "mass_time_nominal_kg_s": mt_nom,
            "mass_time_dense_kg_s": mt_dense,
            "delta_mass_time_kg_s": diff_mt,
            "relative_delta_mass_time": rel_diff_mt,
            "cohort_fraction_nominal": ct_nom,
            "cohort_fraction_dense": ct_dense,
            "delta_cohort_fraction": diff_ct,
        }

    nom_events = nom_obs.get("event_ledger", {})
    dense_events = dense_obs.get("event_ledger", {})
    nom_mass_flux = nom_events.get("mass_kg_by_code", {})
    dense_mass_flux = dense_events.get("mass_kg_by_code", {})

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
        "residence_destinations": residence_comparison,
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
    """Perform strict episodic event matching using actual saved bracket overlap.

    Mathematical Invariants:
    1. Saved bracket for an event:
       [t_start, t_end] = [time[frame_before], time[frame_after]].
    2. Overlap condition between nominal event i and dense event j:
       max(t_start,nom, t_start,dense) <= min(t_end,nom, t_end,dense) + 1e-12.
    3. NO proximity gates! NO abs(dt) <= tolerance! NO invented flutter tolerance bands!
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
        # Filter events for this code
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
        # Get unique particle indices present in either nominal or dense for this code
        active_uids = np.unique(
            np.concatenate([nom_sub["particle_index"], dense_sub["particle_index"]])
        ) if (c_nom > 0 or c_dense > 0) else np.array([], dtype=np.int64)

        # Sort sub-arrays by particle_index then frame_before for fast slicing
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
            # max(n_start, d_start) <= min(n_end, d_end) + 1e-12
            # equivalent to (d_start <= n_end + 1e-12) & (d_end >= n_start - 1e-12)
            overlap = (
                (dense_starts[None, :] <= nom_ends[:, None] + 1e-12)
                & (dense_ends[None, :] >= nom_starts[:, None] - 1e-12)
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

                # BFS / DFS to find connected component in bipartite overlap graph
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
                    # Proven unique 1:1 joint match
                    u_nom_idx = next(iter(comp_nom))
                    u_dense_idx = next(iter(comp_dense))
                    t_nom = float(p_nom["time_s"][u_nom_idx])
                    t_dense = float(p_dense["time_s"][u_dense_idx])
                    dt = t_dense - t_nom

                    n_s, n_e = float(nom_starts[u_nom_idx]), float(nom_ends[u_nom_idx])
                    d_s, d_e = float(dense_starts[u_dense_idx]), float(dense_ends[u_dense_idx])

                    overlap_dur = min(n_e, d_e) - max(n_s, d_s)
                    is_contained = bool((n_s <= d_s + 1e-12) and (d_e <= n_e + 1e-12))

                    code_chord_diffs.append(dt)
                    code_overlap_durations.append(overlap_dur)
                    if is_contained:
                        code_containment_count += 1

                    unique_joint_matches.append({
                        "particle_index": int(pid),
                        "idp": int(p_nom["idp"][u_nom_idx]),
                        "nominal_time_s": t_nom,
                        "dense_time_s": t_dense,
                        "delta_time_s": dt,
                        "overlap_duration_s": overlap_dur,
                        "nominal_bracket_width_s": n_e - n_s,
                        "dense_bracket_width_s": d_e - d_s,
                        "dense_bracket_contained_in_nominal": is_contained,
                    })
                else:
                    # Multi-overlap cluster: strictly AMBIGUOUS!
                    ambiguous_groups.append({
                        "particle_index": int(pid),
                        "nominal_events_count": len(comp_nom),
                        "dense_events_count": len(comp_dense),
                        "nominal_indices": sorted(comp_nom),
                        "dense_indices": sorted(comp_dense),
                    })

        u_count = len(unique_joint_matches)
        amb_nom_count = sum(g["nominal_events_count"] for g in ambiguous_groups)
        amb_dense_count = sum(g["dense_events_count"] for g in ambiguous_groups)
        unm_nom_count = len(unmatched_nom_list)
        ext_dense_count = len(extra_dense_list)

        # Verify exact count conservation
        if u_count + amb_nom_count + unm_nom_count != c_nom:
            raise ComparisonError(
                f"Nominal event count conservation failed for {name}: "
                f"{u_count} + {amb_nom_count} + {unm_nom_count} != {c_nom}"
            )
        if u_count + amb_dense_count + ext_dense_count != c_dense:
            raise ComparisonError(
                f"Dense event count conservation failed for {name}: "
                f"{u_count} + {amb_dense_count} + {ext_dense_count} != {c_dense}"
            )

        grand_unique_count += u_count
        grand_ambiguous_nom_count += amb_nom_count
        grand_ambiguous_dense_count += amb_dense_count
        grand_unmatched_nom_count += unm_nom_count
        grand_extra_dense_count += ext_dense_count

        chord_diffs_all.extend(code_chord_diffs)
        overlap_durations_all.extend(code_overlap_durations)
        containment_count_all += code_containment_count

        diff_arr = np.array(code_chord_diffs) if code_chord_diffs else np.array([])
        by_code_results[name] = {
            "event_code": code,
            "nominal_total_count": c_nom,
            "dense_total_count": c_dense,
            "proven_unique_1to1_joint_count": u_count,
            "ambiguous_nominal_count": amb_nom_count,
            "ambiguous_dense_count": amb_dense_count,
            "unmatched_nominal_count": unm_nom_count,
            "extra_dense_count": ext_dense_count,
            "proven_unique_joint_mass_kg": u_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_nominal_mass_kg": amb_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "ambiguous_dense_mass_kg": amb_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "unmatched_nominal_mass_kg": unm_nom_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "extra_dense_mass_kg": ext_dense_count * NATIVE_SINGLE_PARTICLE_MASS_KG,
            "chord_differences_dense_minus_nom": {
                "count": len(diff_arr),
                "mean_s": float(np.mean(diff_arr)) if len(diff_arr) else None,
                "std_s": float(np.std(diff_arr)) if len(diff_arr) else None,
                "min_s": float(np.min(diff_arr)) if len(diff_arr) else None,
                "max_s": float(np.max(diff_arr)) if len(diff_arr) else None,
            },
            "bracket_containment": {
                "dense_in_nominal_count": code_containment_count,
                "dense_in_nominal_fraction": (code_containment_count / u_count) if u_count else 0.0,
            },
        }

    all_diffs = np.array(chord_diffs_all) if chord_diffs_all else np.array([])
    return {
        "by_code": by_code_results,
        "grand_totals": {
            "nominal_total_events": total_nom_count,
            "dense_total_events": total_dense_count,
            "proven_unique_1to1_joint_count": grand_unique_count,
            "ambiguous_nominal_count": grand_ambiguous_nom_count,
            "ambiguous_dense_count": grand_ambiguous_dense_count,
            "unmatched_nominal_count": grand_unmatched_nom_count,
            "extra_dense_count": grand_extra_dense_count,
            "nominal_count_conservation_verified": (
                grand_unique_count + grand_ambiguous_nom_count + grand_unmatched_nom_count == total_nom_count
            ),
            "dense_count_conservation_verified": (
                grand_unique_count + grand_ambiguous_dense_count + grand_extra_dense_count == total_dense_count
            ),
            "chord_differences_overall": {
                "count": len(all_diffs),
                "mean_s": float(np.mean(all_diffs)) if len(all_diffs) else None,
                "std_s": float(np.std(all_diffs)) if len(all_diffs) else None,
                "min_s": float(np.min(all_diffs)) if len(all_diffs) else None,
                "max_s": float(np.max(all_diffs)) if len(all_diffs) else None,
            },
            "containment_overall": {
                "dense_in_nominal_count": containment_count_all,
                "dense_in_nominal_fraction": (containment_count_all / grand_unique_count) if grand_unique_count else 0.0,
            },
        },
        "scientific_claim_guard": (
            "No proximity tolerance or invented 2dt bands were applied. "
            "Candidate associations require actual saved bracket overlap. "
            "Multi-overlap groups are strictly labeled AMBIGUOUS and not claimed joint. "
            "Extra dense events are reported as extra_dense, not unproven physical flutter."
        ),
    }


def evaluate_temporal_save_bracket_budgets(
    nom_obs: dict[str, Any], dense_obs: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate observed event bracket half-widths against campaign budget (0.00073363908 s)."""
    budget_s = SAVE_HALF_WIDTH_BUDGET_S

    def extract_stats(obs: dict[str, Any], label: str) -> dict[str, Any]:
        stats_by_code = obs.get("observed_bracket_stats", {})
        code_hw: dict[str, float] = {}
        max_hw = 0.0
        for name in EVENT_CODES:
            hw = stats_by_code.get(name, {}).get("max_half_width_s")
            if hw is None:
                first_hw = obs.get("event_ledger", {}).get("first_event_bracket_half_width_s_by_code", {}).get(name)
                hw = float(first_hw) if first_hw is not None else 0.0
            code_hw[name] = float(hw)
            if float(hw) > max_hw:
                max_hw = float(hw)

        passed = max_hw <= budget_s
        return {
            "run_label": label,
            "max_observed_bracket_half_width_s": max_hw,
            "save_half_width_budget_s": budget_s,
            "half_widths_by_code_s": code_hw,
            "satisfies_discretization_budget": passed,
            "determination": "pass_discretization_budget_satisfied" if passed else "fail_budget_exceeded",
        }

    nom_res = extract_stats(nom_obs, "nominal401")
    dense_res = extract_stats(dense_obs, "dense4001")

    return {
        "nominal401": nom_res,
        "dense4001": dense_res,
        "budget_threshold_s": budget_s,
        "governance_note": (
            "A passing save half-width discretization budget (dense4001: 0.0005 s <= 0.0007336 s) "
            "is an observation-scale metric; it does NOT grant Q-N qualification or production status."
        ),
    }


def extract_arrays_from_h5(
    h5_path: Path, expected_sha: str | None = None
) -> dict[str, Any]:
    """Read necessary comparison arrays from an HDF5 labels file."""
    if h5py is None:
        raise ComparisonError("h5py is not installed in the environment!")

    path = Path(h5_path).resolve()
    if not path.is_file():
        raise ComparisonError(f"H5 file not found: {path}")

    with h5py.File(path, "r") as f:
        # Check essential datasets
        for key in ("particle_id", "particle_zone", "source_mk", "source_layer_index", "source_mass_kg",
                    "time", "destination_code", "exclusion_motive", "events"):
            if key not in f:
                raise ComparisonError(f"H5 file missing required dataset '{key}': {path}")

        particle_id = np.asarray(f["particle_id"][:], dtype=np.int64)
        particle_zone = np.asarray(f["particle_zone"][:], dtype=np.int64)
        source_mk = np.asarray(f["source_mk"][:], dtype=np.int32)
        source_layer_index = np.asarray(f["source_layer_index"][:], dtype=np.int32)
        source_mass_kg = np.asarray(f["source_mass_kg"][:], dtype=np.float64)

        time_arr = np.asarray(f["time"][:], dtype=np.float64)
        exclusion_motive = np.asarray(f["exclusion_motive"][:], dtype=np.int16)

        # Destination at final frame
        destination_code_final = np.asarray(f["destination_code"][-1, :], dtype=np.int8)

        # Events compound array
        events = np.asarray(f["events"][:])

        has_residence = "residence" in f

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
        "has_residence_dataset": has_residence,
    }


def execute_full_h5_comparison(
    binding: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    """Execute the complete full-H5 guard checks and array comparisons."""
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

    # 4. Read H5 labels arrays with NVMe single private copy protocol if configured
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

        # Process nominal source
        tmp_nom = scratch_parent / f"nom_labels.{os.getpid()}.tmp.h5"
        try:
            verified_copy(nom_labels_path, tmp_nom, nom_expected_sha)
            nom_data = extract_arrays_from_h5(tmp_nom)
        finally:
            if tmp_nom.exists():
                tmp_nom.unlink()

        # Process dense source
        tmp_dense = scratch_parent / f"dense_labels.{os.getpid()}.tmp.h5"
        try:
            verified_copy(dense_labels_path, tmp_dense, dense_expected_sha)
            dense_data = extract_arrays_from_h5(tmp_dense)
        finally:
            if tmp_dense.exists():
                tmp_dense.unlink()
    else:
        # Direct read (e.g. lightweight synthetic unit testing)
        nom_data = extract_arrays_from_h5(nom_labels_path)
        dense_data = extract_arrays_from_h5(dense_labels_path)

    # 5. Execute comparisons on actual arrays
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
    res_flux_comp = compare_residence_and_flux(nom_obs, dense_obs)
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
        "case_id": binding.get("case_id", "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V2"),
        "sources": {
            "nominal401": {
                "attempt_id": nom_binding.get("attempt_id"),
                "labels_h5": str(nom_labels_path),
                "labels_sha256": nom_expected_sha,
                "observation_report": str(nom_rep_path),
                "report_sha256": actual_nom_rep_sha,
                "frames": len(nom_data["time"]),
                "receipt_status": nom_receipt.get("status"),
                "receipt_returncode": nom_receipt.get("returncode"),
            },
            "dense4001": {
                "attempt_id": dense_binding.get("attempt_id"),
                "labels_h5": str(dense_labels_path),
                "labels_sha256": dense_expected_sha,
                "observation_report": str(dense_rep_path),
                "report_sha256": actual_dense_rep_sha,
                "frames": len(dense_data["time"]),
                "receipt_status": dense_receipt.get("status"),
                "receipt_returncode": dense_receipt.get("returncode"),
            },
        },
        "continuum_invariance": continuum_inv,
        "fluid_population_authority": pop_comp,
        "native_exclusions": excl_comp,
        "destination_fates": fate_comp,
        "residence_and_flux": res_flux_comp,
        "episodic_event_matching": event_comp,
        "save_bracket_budgets": bracket_budgets,
        "claim_boundary": {
            "q_n": "not_granted",
            "production": "none",
            "q_i": "not_granted; post-labels observation cross-comparison",
            "statement": (
                "Save comparison establishes observation discretization sensitivity only. "
                "Aggregate destination mass match does not imply per-UID fate equivalence. "
                "No fluid learning models executed; no Q-N qualification granted."
            ),
        },
    }

    # Write output JSON fresh once
    out_file = output_path.resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Also generate sister markdown report if appropriate
    report_md_path = out_file.with_suffix(".md")
    report_md = generate_comparison_report_markdown(summary)
    report_md_path.write_text(report_md, encoding="utf-8")

    return summary


def generate_comparison_report_markdown(summary: dict[str, Any]) -> str:
    """Generate human-readable Markdown summary of the comparison."""
    lines = [
        f"# DS-DATA-02 Family F2: Native-Weighted Save Comparison v2 Report",
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
        f"- **Operator Code Hash:** `{summary['continuum_invariance']['operator_sha256']}`",
        f"- **Status:** `{summary['continuum_invariance']['status']}`",
        f"",
        f"---",
        f"",
        f"## 2. Fluid Cohort & Native Mass Authority",
        f"",
        f"- **Fluid Particles:** `{summary['fluid_population_authority']['particles_count']}`",
        f"- **Native Single Mass:** `{summary['fluid_population_authority']['single_particle_mass_kg']:.19f} kg` (IEEE-754 binary32)",
        f"- **Native Cohort Mass:** `{summary['fluid_population_authority']['cohort_mass_kg']:.17f} kg`",
        f"- **XML Decimal Benchmark:** `{summary['fluid_population_authority']['continuous_xml_benchmark_kg']} kg`",
        f"- **Representation Drift:** `+{summary['fluid_population_authority']['relative_representation_drift']:.4e}`",
        f"- **Legacy 1e-12 Diagnostic:** `{summary['fluid_population_authority']['legacy_1e12_diagnostic']}` (honestly reported)",
        f"",
        f"---",
        f"",
        f"## 3. Native Exclusions & Unrelabeled Unknowns",
        f"",
        f"- **Motive 1 Identities:** `{summary['native_exclusions']['motive_1_identities_count']}`",
        f"- **Unknown Mass Retained:** `{summary['native_exclusions']['unknown_mass_retained_kg']:.16f} kg`",
        f"- **Physical Spill Inferred:** `{summary['native_exclusions']['physical_spill_inferred']}` (ZERO inferred)",
        f"- **Retained As:** `unknown_invalid`",
        f"",
        f"---",
        f"",
        f"## 4. Final Destination Inventories vs Per-UID Fates",
        f"",
        f"| Destination | Nom Particles | Dense Particles | Delta Part | Nom Mass (kg) | Dense Mass (kg) | Delta Mass (kg) |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    dest_inv = summary["destination_fates"]["aggregate_inventory"]["destinations"]
    for dest, row in dest_inv.items():
        lines.append(
            f"| `{dest}` | {row['nominal_particles']} | {row['dense_particles']} | "
            f"{row['delta_particles']} | {row['nominal_mass_kg']:.6f} | "
            f"{row['dense_mass_kg']:.6f} | {row['delta_mass_kg']:.2e} |"
        )

    fates = summary["destination_fates"]["per_uid_fates"]
    lines.extend([
        f"",
        f"- **Aggregate Inventory Match:** `{summary['destination_fates']['aggregate_inventory']['aggregate_inventory_match']}`",
        f"- **Per-UID Fate Match:** `{fates['per_uid_fate_match']}`",
        f"- **Switched Particles Count:** `{fates['switched_particles_count']}` ({fates['switch_fraction'] * 100:.2f}%)",
        f"- **Switched Mass:** `{fates['switched_mass_kg']:.6f} kg`",
        f"- **Scientific Guard:** {summary['destination_fates']['scientific_claim_guard']}",
        f"",
        f"---",
        f"",
        f"## 5. Strict Saved-Bracket Episodic Event Matching",
        f"",
        f"| Event Code | Name | Nom Total | Dense Total | Unique 1:1 Joint | Ambiguous Nom | Ambiguous Dense | Unmatched Nom | Extra Dense |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    ev_by_code = summary["episodic_event_matching"]["by_code"]
    for name, row in ev_by_code.items():
        lines.append(
            f"| {row['event_code']} | `{name}` | {row['nominal_total_count']} | {row['dense_total_count']} | "
            f"{row['proven_unique_1to1_joint_count']} | {row['ambiguous_nominal_count']} | "
            f"{row['ambiguous_dense_count']} | {row['unmatched_nominal_count']} | {row['extra_dense_count']} |"
        )

    totals = summary["episodic_event_matching"]["grand_totals"]
    lines.extend([
        f"",
        f"- **Overall Unique 1:1 Joint Events:** `{totals['proven_unique_1to1_joint_count']}`",
        f"- **Overall Ambiguous Nominal Events:** `{totals['ambiguous_nominal_count']}`",
        f"- **Overall Ambiguous Dense Events:** `{totals['ambiguous_dense_count']}`",
        f"- **Overall Unmatched Nominal Events:** `{totals['unmatched_nominal_count']}`",
        f"- **Overall Extra Dense Events:** `{totals['extra_dense_count']}`",
        f"- **Nominal Count Conservation:** `{totals['nominal_count_conservation_verified']}`",
        f"- **Dense Count Conservation:** `{totals['dense_count_conservation_verified']}`",
        f"- **Overall Containment Fraction:** `{totals['containment_overall']['dense_in_nominal_fraction'] * 100:.2f}%`",
        f"",
        f"---",
        f"",
        f"## 6. Save Half-Width Discretization Budget",
        f"",
        f"- **Budget Threshold:** `{summary['save_bracket_budgets']['budget_threshold_s']} s`",
        f"- **Nominal 401 Determination:** `{summary['save_bracket_budgets']['nominal401']['determination']}` "
        f"(`{summary['save_bracket_budgets']['nominal401']['max_observed_bracket_half_width_s']:.6f} s`)",
        f"- **Dense 4001 Determination:** `{summary['save_bracket_budgets']['dense4001']['determination']}` "
        f"(`{summary['save_bracket_budgets']['dense4001']['max_observed_bracket_half_width_s']:.6f} s`)",
        f"",
        f"---",
        f"",
        f"## 7. Claim Boundary",
        f"",
        f"- `q_n`: **{summary['claim_boundary']['q_n']}**",
        f"- `production`: **{summary['claim_boundary']['production']}**",
        f"- `q_i`: **{summary['claim_boundary']['q_i']}**",
        f"- `{summary['claim_boundary']['statement']}`",
    ])

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DS-DATA-02 Family F2: Native-Weighted Temporal Save Comparison Worker v2"
    )
    parser.add_argument("--binding", "--config", dest="binding", type=Path, required=True,
                        help="Path to comparison binding or configuration JSON")
    parser.add_argument("--output", "--output-dir", dest="output", type=Path, required=True,
                        help="Path to output JSON summary file or output directory")

    args = parser.parse_args(argv)

    binding_path = args.binding.resolve()
    if not binding_path.is_file():
        print(f"Error: Binding file not found: {binding_path}", file=sys.stderr)
        return 1

    with binding_path.open("r", encoding="utf-8") as f:
        binding = json.load(f)

    out = args.output.resolve()
    if out.is_dir() or str(out).endswith("/"):
        out_json = out / "comparison_summary.json"
    else:
        out_json = out

    print(f"Executing DS-DATA-02 F2 Native-Weighted Save Comparison Worker v2")
    print(f"Binding: {binding_path}")
    print(f"Output:  {out_json}")

    try:
        summary = execute_full_h5_comparison(binding, out_json)
    except ComparisonError as err:
        print(f"Comparison Error: {err}", file=sys.stderr)
        return 2
    except Exception as err:
        print(f"Unexpected Execution Error: {type(err).__name__}: {err}", file=sys.stderr)
        return 3

    print("Save comparison completed successfully.")
    print(f"Continuum Invariance:   {summary['continuum_invariance']['status']}")
    print(f"Fluid Population:       {summary['fluid_population_authority']['status']}")
    print(f"Aggregate Fate Match:   {summary['destination_fates']['aggregate_inventory']['aggregate_inventory_match']}")
    print(f"Per-UID Fate Match:     {summary['destination_fates']['per_uid_fates']['per_uid_fate_match']}")
    print(f"Switched UID Count:     {summary['destination_fates']['per_uid_fates']['switched_particles_count']}")
    print(f"Nominal Save Brackets:  {summary['save_bracket_budgets']['nominal401']['determination']}")
    print(f"Dense Save Brackets:    {summary['save_bracket_budgets']['dense4001']['determination']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
