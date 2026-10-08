#!/usr/bin/env python3
"""Derive a small pure-data observer ledger from the guarded F2 stream JSON.

This consumer never opens BI4, HDF5, PartOut, RunPARTs, or solver output.  It
uses only the source-closed V3 active-stream report and its frozen observation
contract to expose whole-initial-mass screens and saved-frame space/time/output
comparison metadata.  It does not infer physical destination, legal flux,
continuous event time, or dynamics from saved-frame values.

The last saved RunPARTs ``DtMax`` is carried as a diagnostic statistic.  It is
not an integration-error upper bound: no integrator error estimator or
continuous event-time evidence is present in this JSON-only consumer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f2.coarse-pure-observer.v1"
ACTIVE_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v3"
CONTRACT_SCHEMA = "ds02.stage2.f2.coarse-observation-contract.v2"
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"


class ObserverError(ValueError):
    """Raised when an active report is not source-bound for this observer."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_json(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ObserverError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4"}:
        raise ObserverError(f"{label} points to forbidden raw/HDF5 content: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObserverError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ObserverError(f"{label} is not a JSON object: {path}")
    return value


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObserverError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ObserverError(f"{label} is not finite")
    return result


def stat_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256(path),
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise ObserverError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ObserverError("observer contract schema differs")
    frozen = contract.get("frozen_tolerances")
    if not isinstance(frozen, dict):
        raise ObserverError("observer contract lacks frozen tolerances")
    expected = {
        "whole_initial_unknown_mass_fraction_max": 0.003,
        "mk_region_flux_error_fraction_whole_initial": 0.03,
        "integration_error_allocation_fraction": 0.25,
        "output_sampling_error_allocation_fraction": 0.25,
    }
    for key, value in expected.items():
        if frozen.get(key) != value:
            raise ObserverError(f"observer contract changed frozen tolerance {key}")
    future = contract.get("future_observer_tolerances")
    if not isinstance(future, dict) or future.get("all_are_preregistration_metadata_not_qualification") is not True:
        raise ObserverError("future observer tolerances are not explicitly non-qualification metadata")
    half_cfl = contract.get("half_cfl_comparison")
    if not isinstance(half_cfl, dict) or half_cfl.get("status") != "NOT_MEASURED" or half_cfl.get("no_cross_case_credit") is not True:
        raise ObserverError("half-CFL comparison is not a non-qualification preregistration")
    output_projection = contract.get("native_output_projection")
    if not isinstance(output_projection, dict) or output_projection.get("status") != "NOT_MEASURED" or output_projection.get("saved_frame_interval_is_not_continuous_event_error") is not True:
        raise ObserverError("native output projection is not a non-qualification preregistration")
    return contract


def _union_saved_bounds(frame_summaries: list[dict[str, Any]]) -> dict[str, list[float]]:
    mins: list[float] | None = None
    maxs: list[float] | None = None
    for index, frame in enumerate(frame_summaries):
        active = frame.get("active_fluid")
        if not isinstance(active, dict):
            raise ObserverError(f"frame {index} lacks active-fluid summary")
        current_min = [finite(value, f"frame {index} position_min") for value in active.get("position_min_m", [])]
        current_max = [finite(value, f"frame {index} position_max") for value in active.get("position_max_m", [])]
        if len(current_min) != 3 or len(current_max) != 3:
            raise ObserverError(f"frame {index} active position bounds are not 3D")
        mins = current_min if mins is None else [min(a, b) for a, b in zip(mins, current_min)]
        maxs = current_max if maxs is None else [max(a, b) for a, b in zip(maxs, current_max)]
    if mins is None or maxs is None:
        raise ObserverError("active report has no saved frame summaries")
    return {"min_m": mins, "max_m": maxs}


def _last_dt_observation(integration_error: Any) -> dict[str, Any]:
    """Expose the final saved ``DtMax`` without promoting it to an error bound."""
    if not isinstance(integration_error, dict):
        return {
            "value_s": None,
            "source": "RunPARTs final saved record DtMax",
            "status": "UNKNOWN_UNMEASURED",
            "is_integration_error_upper_bound": False,
            "meaning": "no saved DtMax field was supplied; integration error upper bound is UNKNOWN",
        }
    fields = integration_error.get("fields")
    if fields is None:
        return {
            "value_s": None,
            "source": "RunPARTs final saved record DtMax",
            "status": "UNKNOWN_UNMEASURED",
            "is_integration_error_upper_bound": False,
            "meaning": "no saved DtMax field was supplied; integration error upper bound is UNKNOWN",
        }
    if not isinstance(fields, (list, tuple)) or len(fields) < 3 or fields[2] is None:
        raise ObserverError("active report integration fields do not contain a valid final DtMax")
    value_s = finite(fields[2], "RunPARTs final saved DtMax")
    if value_s < 0.0:
        raise ObserverError("RunPARTs final saved DtMax is negative")
    return {
        "value_s": value_s,
        "source": "RunPARTs final saved record DtMax",
        "status": "OBSERVED_SAVED_STEP_STATISTIC",
        "is_integration_error_upper_bound": False,
        "meaning": "saved-step statistic only; it is not an integrator error estimate, an integration-error upper bound, or a continuous event-time bound",
    }


def _velocity_ke_observation(frame_summaries: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    """Report only the velocity summary actually present in saved frame JSON.

    The active worker stores mass-weighted velocity, but does not store the
    second moment ``sum(m*|v|^2)`` needed for kinetic energy.  Therefore a
    nonzero velocity/KE reference denominator cannot be manufactured here.
    """
    observed: list[tuple[int, list[float]]] = []
    for index, frame in enumerate(frame_summaries):
        active = frame.get("active_fluid")
        if not isinstance(active, dict):
            raise ObserverError(f"frame {index} lacks active-fluid summary")
        value = active.get("mass_weighted_velocity_m_s")
        if value is None:
            continue
        if not isinstance(value, list) or len(value) != 3:
            raise ObserverError(f"frame {index} mass-weighted velocity is not 3D")
        vector = [finite(component, f"frame {index} mass-weighted velocity") for component in value]
        observed.append((index, vector))
    result: dict[str, Any] = {
        "mass_weighted_velocity_saved_frame_count": len(observed),
        "mass_weighted_velocity_final_m_s": observed[-1][1] if observed else None,
        "kinetic_energy_sum_m_v2_available": False,
        "nonzero_velocity_ke_reference_denominator": "UNKNOWN_NOT_MEASURED",
        "future_velocity_ke_reference_fraction": contract["future_observer_tolerances"]["velocity_ke_nonzero_reference_fraction"],
        "status": "DIAGNOSTIC_OR_PREREGISTRATION_ONLY",
        "meaning": "mass-weighted velocity is a saved-frame summary; no velocity/KE nonzero reference denominator or continuous velocity history is available",
    }
    return result


def derive(active: dict[str, Any], contract: dict[str, Any], active_path: Path, contract_path: Path) -> dict[str, Any]:
    if active.get("schema") != ACTIVE_SCHEMA or active.get("status") != "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_OBSERVATION":
        raise ObserverError("active report is not a completed V3 source product")
    if active.get("case_key") != CASE_KEY or active.get("physical_case_id") != CASE_KEY:
        raise ObserverError("active report physical identity differs")
    stability = active.get("input_stability")
    if not isinstance(stability, dict) or stability.get("all_equal") is not True:
        raise ObserverError("active report source inputs are not stable")
    policy = active.get("read_policy")
    if not isinstance(policy, dict) or policy.get("hdf5_opened") is not False or policy.get("solver_started") is not False:
        raise ObserverError("active report read policy is not closed")
    stream = active.get("active_fluid_stream")
    mass = active.get("mass_and_material")
    join = active.get("native_identity_join")
    timing = active.get("timing_and_error_separation")
    if not isinstance(stream, dict) or not isinstance(mass, dict) or not isinstance(join, dict) or not isinstance(timing, dict):
        raise ObserverError("active report lacks required scientific sections")
    if stream.get("frame_count") != 401 or stream.get("initial_fluid_count") != 27750:
        raise ObserverError("active report frame/fluid inventory differs from ROOT095 source")
    whole_initial = finite(stream.get("whole_initial_fluid_mass_kg"), "whole initial mass")
    if abs(whole_initial - 18.910848) > 1e-12:
        raise ObserverError("active report whole-initial mass is not the frozen 18.910848 kg denominator")
    native_count = int(join.get("native_row_count", -1))
    if native_count != 153:
        raise ObserverError("active report native identity count differs from ROOT105 153")
    native_mass = finite(mass.get("native_excluded_mass_lower_bound_kg"), "native lower-bound mass")
    fraction = finite(mass.get("native_excluded_mass_fraction_whole_initial"), "native lower-bound fraction")
    if abs(fraction - native_mass / whole_initial) > 1e-12:
        raise ObserverError("active report native mass fraction is not whole-initial normalized")
    frozen_unknown = contract["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"]
    frame_summaries = stream.get("frame_summaries")
    if not isinstance(frame_summaries, list) or len(frame_summaries) != 401:
        raise ObserverError("active report saved-frame summary count differs")
    bounds = _union_saved_bounds(frame_summaries)
    actual_axis = timing.get("actual_native_time_axis")
    saved_axis = timing.get("saved_output_time_axis")
    if not isinstance(actual_axis, dict) or not isinstance(saved_axis, dict):
        raise ObserverError("active report lacks separate native/saved time axes")
    saved_intervals = {
        "frame_count": int(saved_axis.get("frame_count", stream.get("frame_count", -1))),
        "first_time_s": finite(saved_axis.get("first_time_s"), "saved first time"),
        "last_time_s": finite(saved_axis.get("last_time_s"), "saved last time"),
        "interval_min_s": finite(saved_axis.get("interval_min_s"), "saved interval min"),
        "interval_max_s": finite(saved_axis.get("interval_max_s"), "saved interval max"),
        "interval_mean_s": finite(saved_axis.get("interval_mean_s"), "saved interval mean"),
    }
    if saved_intervals["frame_count"] != 401 or saved_intervals["last_time_s"] < saved_intervals["first_time_s"]:
        raise ObserverError("saved output time axis inventory is invalid")
    integration_error = timing.get("integration_error", {})
    output_error = timing.get("output_sampling_error", {})
    last_dt = _last_dt_observation(integration_error)
    velocity_ke = _velocity_ke_observation(frame_summaries, contract)
    initial_by_mk = mass.get("initial_mk_mass_denominators_kg")
    count_by_mk = mass.get("native_excluded_count_by_mk")
    if not isinstance(initial_by_mk, dict) or not isinstance(count_by_mk, dict):
        raise ObserverError("active report lacks per-MK initial/native accounting")
    per_mk = {}
    for mk, denominator in sorted(initial_by_mk.items()):
        denominator_kg = finite(denominator, f"initial MK {mk} mass")
        count = int(count_by_mk.get(mk, 0))
        per_mk[mk] = {
            "initial_mass_kg": denominator_kg,
            "native_excluded_count": count,
            "native_excluded_mass_lower_bound_kg": count * (native_mass / native_count),
            "native_lower_bound_fraction_of_mk": (count * (native_mass / native_count)) / denominator_kg,
        }
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_F2_COARSE_PURE_DATA_OBSERVER_DERIVED",
        "case_key": CASE_KEY,
        "family_id": "F2",
        "source": {
            "active_stream_report": stat_record(active_path),
            "observation_contract": stat_record(contract_path),
            "raw_bi4_opened_by_observer": False,
            "hdf5_opened_by_observer": False,
        },
        "whole_initial_mass_observer": {
            "denominator_kg": whole_initial,
            "basis": "source-bound generated XML fluid block count × BI4 MassFluid from completed V2 active stream",
            "native_excluded_lower_bound_kg": native_mass,
            "native_excluded_lower_bound_fraction": fraction,
            "unknown_mass_screen_max_fraction": frozen_unknown,
            "unknown_mass_screen_result_only": fraction <= frozen_unknown,
            "physical_fate": "UNKNOWN",
            "legal_flux_or_spill": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "per_mk_diagnostic": per_mk,
        "saved_space_observer": {
            "union_saved_active_position_bounds_m": bounds,
            "meaning": "envelope over saved active-fluid frames; not a continuous region, destination, spill, or flux proof",
            "future_position_reference_fraction": contract["future_observer_tolerances"]["space_position_reference_fraction"],
        },
        "saved_time_observer": {
            "timing_and_error_separation": timing,
            "native_time_axis_finite_observed": {
                "first_time_s": finite(actual_axis.get("first_time_s"), "native first time"),
                "last_time_s": finite(actual_axis.get("last_time_s"), "native last time"),
                "frame_count": int(actual_axis.get("frame_count", -1)),
            },
            "saved_output_axis_finite_observed": saved_intervals,
            "integration_error_status": integration_error.get("status", "UNKNOWN"),
            "output_sampling_error_status": output_error.get("status", "UNKNOWN"),
            "declared_endpoint_is_metadata_only": timing.get("declared_solver_endpoint", {}).get("used_as_observation_time") is False,
            "future_event_time_reference_fraction": contract["future_observer_tolerances"]["event_time_nonzero_window_fraction"],
            "meaning": "saved BI4/RunPARTs brackets only; hidden sub-frame crossings remain UNKNOWN",
        },
        "pure_time_output_observer": {
            "integrator_last_dt_statistic": last_dt,
            "saved_interval_statistics": saved_intervals,
            "continuous_event_time": "UNKNOWN",
            "event_time_reference_fraction": contract["future_observer_tolerances"]["event_time_nonzero_window_fraction"],
            "half_cfl_comparison": contract["half_cfl_comparison"],
            "native_output_projection": contract["native_output_projection"],
            "velocity_ke_observation": velocity_ke,
            "meaning": "pure saved-data diagnostics and preregistration metadata; saved cadence cannot establish hidden continuous crossings or integration error",
        },
        "saved_output_observer": {
            "future_velocity_ke_reference_fraction": contract["future_observer_tolerances"]["velocity_ke_nonzero_reference_fraction"],
            "integration_output_allocation_fraction_each": contract["future_observer_tolerances"]["integration_output_allocation_fraction_each"],
            "mk_region_flux_error_fraction_whole_initial": contract["future_observer_tolerances"]["mk_region_flux_error_fraction_whole_initial"],
            "status": "PREREGISTERED_COMPARISON_METADATA_ONLY",
            "meaning": "future same-source/control comparisons require a separate guarded product; current saved fields do not qualify QI/QN/QE",
        },
        "claim_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "continuous_event_time": "UNKNOWN", "physical_destination": "UNKNOWN", "dynamics": "UNKNOWN"},
    }


def audit(active_path: Path, contract_path: Path, output_path: Path) -> dict[str, Any]:
    active_path = require_json(active_path, "active stream report")
    contract_path = require_json(contract_path, "observation contract")
    result = derive(read_json(active_path, "active stream report"), validate_contract(read_json(contract_path, "observation contract")), active_path, contract_path)
    atomic_json(output_path, result)
    return {"schema": result["schema"], "status": result["status"], "native_fraction": result["whole_initial_mass_observer"]["native_excluded_lower_bound_fraction"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-report", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.active_report, args.contract, args.output), sort_keys=True))
    except Exception as exc:
        print(f"F2 active observer failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
