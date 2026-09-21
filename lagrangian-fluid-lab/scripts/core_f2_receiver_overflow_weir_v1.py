#!/usr/bin/env python3
"""Read-only contract and event observer for the F2 overflow-weir candidate.

This module deliberately stops before runtime preparation or solver submission.
It closes the candidate's hash-bound input contract and exposes pure observer
functions for a future trajectory product.  Calling it cannot start a solver,
touch CUDA, submit a queue job, or mutate the scientific ledger or registry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"
SCOPE_ID = "F2_receiver_overflow_weir_v1"
REVISION_ID = "F2_receiver_overflow_weir_mdbc_v1"
ROOT_SPEC = "root-review-only-job-spec-v2.json"
EXPECTED_ROWS = 15
WEIR_X_M = 0.78
RECEIVER_XMAX_M = 1.56
RECEIVER_YMIN_M = 0.04
RECEIVER_YMAX_M = 0.46
RECEIVER_ZMIN_M = 0.0
RECEIVER_ZMAX_M = 0.8
EVENT_MASS_FRACTION = 0.01
SUSTAINED_CONTACT_S = 0.20


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _path(base: Path, value: str | Path) -> Path:
    value = Path(value)
    return (value if value.is_absolute() else base / value).resolve()


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")


def _read_positions(frames: Iterable[Any]) -> np.ndarray:
    array = np.asarray(frames, dtype=float)
    if array.ndim != 3 or array.shape[-1] != 3 or array.shape[1] == 0:
        raise ValueError("frames must have shape [frame, particle, 3]")
    if not np.isfinite(array).all():
        raise ValueError("frames contain non-finite values")
    return array


def _read_masses(masses: Iterable[Any], particle_count: int) -> np.ndarray:
    array = np.asarray(masses, dtype=float)
    if array.shape != (particle_count,) or not np.isfinite(array).all() or np.any(array <= 0):
        raise ValueError("masses must be finite positive values for every particle")
    return array


def crest_crossing_mass_fraction(
    previous: Iterable[Any],
    current: Iterable[Any],
    masses: Iterable[Any],
    crest_height_m: float,
    *,
    weir_x_m: float = WEIR_X_M,
) -> dict[str, Any]:
    """Return the mass that crosses the weir plane above the crest.

    The predicate is intentionally conservative: a particle must be on the
    upstream side at the previous saved frame and on or beyond the downstream
    plane at the current frame while its current z coordinate is at least the
    registered crest height.  This function only consumes supplied states; it
    never reads a future reference state or launches a decoder.
    """
    before = np.asarray(previous, dtype=float)
    after = np.asarray(current, dtype=float)
    if before.shape != after.shape or before.ndim != 2 or before.shape[1] != 3:
        raise ValueError("previous and current positions must both have shape [particle, 3]")
    if not np.isfinite(before).all() or not np.isfinite(after).all():
        raise ValueError("positions contain non-finite values")
    weight = _read_masses(masses, before.shape[0])
    crossed = (before[:, 0] < float(weir_x_m)) & (after[:, 0] >= float(weir_x_m))
    crossed &= after[:, 2] >= float(crest_height_m)
    initial_mass = float(weight.sum())
    crossing_mass = float(weight[crossed].sum())
    return {
        "crossed_particle_count": int(crossed.sum()),
        "crossing_mass_kg": crossing_mass,
        "initial_mass_kg": initial_mass,
        "mass_fraction": crossing_mass / initial_mass,
    }


def receiver_contact_mass_fraction(
    positions: Iterable[Any],
    masses: Iterable[Any],
    *,
    x_min_m: float = WEIR_X_M,
    x_max_m: float = RECEIVER_XMAX_M,
    y_min_m: float = RECEIVER_YMIN_M,
    y_max_m: float = RECEIVER_YMAX_M,
    z_min_m: float = RECEIVER_ZMIN_M,
    z_max_m: float = RECEIVER_ZMAX_M,
) -> dict[str, Any]:
    """Return mass currently inside the registered downstream receiver."""
    points = np.asarray(positions, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("positions must have shape [particle, 3]")
    if not np.isfinite(points).all():
        raise ValueError("positions contain non-finite values")
    weight = _read_masses(masses, points.shape[0])
    inside = (
        (points[:, 0] >= float(x_min_m)) & (points[:, 0] <= float(x_max_m))
        & (points[:, 1] >= float(y_min_m)) & (points[:, 1] <= float(y_max_m))
        & (points[:, 2] >= float(z_min_m)) & (points[:, 2] <= float(z_max_m))
    )
    initial_mass = float(weight.sum())
    contact_mass = float(weight[inside].sum())
    return {
        "contact_particle_count": int(inside.sum()),
        "contact_mass_kg": contact_mass,
        "initial_mass_kg": initial_mass,
        "mass_fraction": contact_mass / initial_mass,
    }


def evaluate_event(
    frames: Iterable[Any],
    times_s: Iterable[Any],
    masses: Iterable[Any],
    crest_height_m: float,
    *,
    event_mass_fraction: float = EVENT_MASS_FRACTION,
    sustained_contact_s: float = SUSTAINED_CONTACT_S,
) -> dict[str, Any]:
    """Evaluate crest crossing and sustained receiver contact from a trajectory.

    This is a pure evaluator for already supplied model/reference states.  It
    requires the complete supplied window but makes no claim about rows whose
    trajectory is absent or truncated; callers must keep those rows censored in
    the fixed denominator.
    """
    positions = _read_positions(frames)
    times = np.asarray(times_s, dtype=float)
    if times.shape != (positions.shape[0],) or not np.isfinite(times).all():
        raise ValueError("times must have one finite value per frame")
    if times.shape[0] < 1 or np.any(np.diff(times) <= 0):
        raise ValueError("times must be strictly increasing")
    weight = _read_masses(masses, positions.shape[1])
    crossing = None
    contact_fractions: list[float] = []
    crest_fractions: list[float] = []
    for index in range(positions.shape[0]):
        contact = receiver_contact_mass_fraction(positions[index], weight)
        contact_fractions.append(float(contact["mass_fraction"]))
        if index:
            event = crest_crossing_mass_fraction(
                positions[index - 1], positions[index], weight, crest_height_m
            )
            crest_fractions.append(float(event["mass_fraction"]))
            if crossing is None and event["mass_fraction"] >= float(event_mass_fraction):
                crossing = {"frame_index": index, "time_s": float(times[index]), **event}
        else:
            crest_fractions.append(0.0)

    first_contact = next(
        (index for index, fraction in enumerate(contact_fractions)
         if fraction >= float(event_mass_fraction)),
        None,
    )
    max_sustained = 0.0
    run_start: int | None = None
    for index, fraction in enumerate(contact_fractions):
        if fraction >= float(event_mass_fraction):
            if run_start is None:
                run_start = index
            max_sustained = max(max_sustained, float(times[index] - times[run_start]))
        else:
            run_start = None
    sustained = max_sustained >= float(sustained_contact_s)
    return {
        "schema": "core.f2.receiver_overflow_weir.event_observation.v1",
        "crest_height_m": float(crest_height_m),
        "event_mass_fraction_threshold": float(event_mass_fraction),
        "sustained_contact_s_threshold": float(sustained_contact_s),
        "crest_crossing": crossing,
        "receiver_contact": None if first_contact is None else {
            "frame_index": first_contact,
            "time_s": float(times[first_contact]),
            "mass_fraction": float(contact_fractions[first_contact]),
        },
        "max_sustained_receiver_contact_s": float(max_sustained),
        "event_complete": bool(crossing is not None and sustained),
        "contact_mass_fraction_by_frame": contact_fractions,
        "crest_crossing_mass_fraction_by_interval": crest_fractions,
    }


def verify_candidate_bundle(base: Path = DEFAULT_BASE) -> dict[str, Any]:
    """Verify the static candidate contract without executing a workload."""
    base = Path(base).resolve()
    card_path = base / "candidate-card-v1.json"
    matrix_path = base / "fixed-matrix-v1.json"
    denominator_path = base / "failure-denominator-v1.json"
    lineage_path = base / "lineage-clarification-v1.json"
    preflight_path = base / "cpu-native-preflight-v1.json"
    root_path = base / ROOT_SPEC
    route_path = base / "route-audit-v1.json"
    card = load_json(card_path)
    matrix = load_json(matrix_path)
    denominator = load_json(denominator_path)
    lineage = load_json(lineage_path)
    preflight = load_json(preflight_path)
    root_review = load_json(root_path)
    route = load_json(route_path)

    for label, value in {
        "candidate": card,
        "matrix": matrix,
        "denominator": denominator,
        "lineage": lineage,
        "preflight": preflight,
        "root review": root_review,
        "route audit": route,
    }.items():
        if value.get("scope_id") != SCOPE_ID:
            raise ValueError(f"{label} scope mismatch")
        if value.get("revision_id") != REVISION_ID:
            raise ValueError(f"{label} revision mismatch")

    if card.get("qualification_claim") != "none" or card.get("qualified") is not False:
        raise ValueError("candidate is not explicitly unqualified")
    if card.get("T1_numerical") is not False or card.get("matrix_credit") != 0:
        raise ValueError("candidate has non-zero scientific credit")
    if card.get("execution_controls", {}).get("controls_executed") is not False:
        raise ValueError("candidate execution controls are open")

    if matrix.get("cell_count") != EXPECTED_ROWS or len(matrix.get("rows", [])) != EXPECTED_ROWS:
        raise ValueError("fixed matrix does not contain 15 rows")
    if matrix.get("denominator", {}).get("unattempted") != EXPECTED_ROWS:
        raise ValueError("fixed matrix denominator is not all unattempted")
    if any(row.get("status") != "not_started" for row in matrix["rows"]):
        raise ValueError("fixed matrix contains an executed row")
    if denominator.get("planned") != EXPECTED_ROWS or denominator.get("unattempted") != EXPECTED_ROWS:
        raise ValueError("failure denominator is not closed at 15 unattempted rows")
    if denominator.get("credit") != 0 or denominator.get("preservation", {}).get("same_input_retry") is not False:
        raise ValueError("failure denominator permits credit or same-input retry")

    if preflight.get("preflight_pass") is not True or preflight.get("matrix_credit") != 0:
        raise ValueError("native preflight is not a zero-credit pass")
    controls = preflight.get("execution_controls", {})
    if any(controls.get(key) not in (False, 0) for key in (
        "solver_invoked", "gpu_invoked", "queue_mutation", "central_ledger_mutation", "central_registry_mutation"
    )):
        raise ValueError("native preflight claims a workload or central mutation")
    native = preflight.get("native_initial", {})
    if native.get("ids_unique") is not True or native.get("arrays_finite") is not True:
        raise ValueError("native preflight identity/finite contract failed")
    if native.get("boundary_zero_normal_count") != 0:
        raise ValueError("native preflight has zero normals")

    if root_review.get("job_spec_status") != "root_review_only_adapter_implemented_not_submitted":
        raise ValueError("root review spec is not protected and unsubmitted")
    policy = root_review.get("execution_policy", {})
    for key in ("submit_allowed", "solver_launch", "gpu_launch", "same_input_retry", "threshold_relaxation", "horizon_extension_before_anchor"):
        if policy.get(key) is not False:
            raise ValueError(f"root review policy opened: {key}")
    if policy.get("one_anchor_only") is not True or policy.get("qualification_claim_none") is not True:
        raise ValueError("root review policy is not single-anchor zero-credit")

    binding_paths = {
        "candidate_card": card_path,
        "fixed_matrix": matrix_path,
        "failure_denominator": denominator_path,
        "lineage": lineage_path,
        "cpu_native_preflight": preflight_path,
        "route_audit": route_path,
    }
    bindings = root_review.get("sha256_binding", {})
    for label, path in binding_paths.items():
        _require_hash(path, str(bindings.get(label, "")), label)
    _require_hash(Path(__file__).resolve(), str(bindings.get("adapter", "")), "adapter")
    _require_hash(base / "adapter-contract-preflight-v1.json",
                  str(bindings.get("adapter_contract_preflight", "")),
                  "adapter contract preflight")
    if root_review.get("adapter", {}).get("present") is not True:
        raise ValueError("root review does not bind the implemented adapter")
    if root_review.get("execution_policy", {}).get("runtime_preparation_allowed") is not False:
        raise ValueError("root review opened runtime preparation")

    native_sha = preflight.get("artifacts", {}).get("sha256", {})
    for label, relative in (
        ("definition", "anchor/CORE_F2_receiver_overflow_weir_q0p50000000_crest0p26000000_dp0p007500000000_Def.xml"),
        ("gencase_log", "anchor/gencase-v4.log"),
        ("native_bi4", "anchor/generated_v4/CORE_F2_receiver_overflow_weir_q0p50000000_crest0p26000000_dp0p007500000000.bi4"),
        ("native_metadata", "anchor/generated_v4/CORE_F2_receiver_overflow_weir_q0p50000000_crest0p26000000_dp0p007500000000_.xml"),
    ):
        _require_hash(_path(base, relative), str(native_sha.get(label, "")), f"preflight {label}")

    return {
        "schema": "core.f2.receiver_overflow_weir.adapter_contract.v1",
        "created_at_utc": stamp(),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "status": "adapter_contract_only_root_review_required",
        "candidate": {
            "path": str(card_path),
            "sha256": sha256(card_path),
            "matrix_rows": EXPECTED_ROWS,
            "matrix_credit": 0,
            "qualification_claim": "none",
        },
        "native_anchor": {
            "preflight_path": str(preflight_path),
            "preflight_sha256": sha256(preflight_path),
            "definition_sha256": native_sha["definition"],
            "native_bi4_sha256": native_sha["native_bi4"],
            "fluid_particles": int(native["fluid_particles_decoded"]),
            "boundary_particles": int(native["boundary_particles_decoded"]),
            "zero_normals": int(native["boundary_zero_normal_count"]),
            "native_mass_error": float(preflight["mass_contract"]["relative_error"]),
        },
        "observer_contract": {
            "weir_x_m": WEIR_X_M,
            "receiver_region_m": {
                "xmin": WEIR_X_M,
                "xmax": RECEIVER_XMAX_M,
                "ymin": RECEIVER_YMIN_M,
                "ymax": RECEIVER_YMAX_M,
                "zmin": RECEIVER_ZMIN_M,
                "zmax": RECEIVER_ZMAX_M,
            },
            "event_mass_fraction": EVENT_MASS_FRACTION,
            "sustained_contact_s": SUSTAINED_CONTACT_S,
            "future_state_access": False,
            "trajectory_product_required": True,
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "central_ledger_mutation": 0,
            "central_registry_mutation": 0,
            "runtime_submission": False,
        },
        "root_review": {
            "path": str(root_path),
            "submit_allowed": False,
            "adapter_runtime_authorized": False,
        },
        "adapter": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
            "mode": "contract_and_pure_observer_only",
            "solver_calls": 0,
            "queue_mutations": 0,
            "ledger_mutations": 0,
            "registry_mutations": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verify", nargs="?", choices=["verify"], default="verify")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_candidate_bundle(args.base)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
