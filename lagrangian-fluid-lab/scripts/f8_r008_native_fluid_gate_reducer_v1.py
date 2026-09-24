"""Reduce reviewed R008 fluid gates from a held, semantically verified table FD.

This reducer evaluates only density range, Mach, and inclusive three-period
window completeness. It does not validate B/C/D evidence bytes or adjudicate
the remaining native-integrity gates, T1, readiness, or qualification.
"""
from __future__ import annotations

import fcntl
import hashlib
import math
import os
import stat
import struct
from typing import Any, Mapping

import h5py
import numpy as np

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_native_integrity_registry_v1 as registry
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts.f8_observation_window_parser_v2 import select_closed_native_window


SCHEMA = "core.cfd.f8.r008_native_fluid_gate_reducer.v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
PARTICLE_CHUNK = 4096
MAX_SELECTED_TIME_PARTICLE_CELLS = 3_000_000
SAMPLED_GATE_IDS = (
    "density_range", "mach_limit", "inclusive_three_period_window_complete",
)
UNEVALUATED_GATE_IDS = (
    "native_state_finite", "wall_penetration_limit", "excluded_fluid_particles_zero",
    "particle_overlap_absent", "control_no_extrapolation",
)
TABLE_VERIFICATION_FIELDS = frozenset({
    "schema", "table_schema", "case_id", "table_bytes", "table_sha256",
    "time_rows", "fluid_particle_count", "raw_frames_recomputed",
    "full_time_axis_matches", "fluid_id_projection_matches",
    "position_velocity_density_mass_recomputed", "all_valid",
    "native_integrity_evaluated", "T1_numerical", "qualification_credit",
})
_SHA256_HEX = frozenset("0123456789abcdef")


class NativeFluidGateReducerError(ValueError):
    """A table or frozen R008 observation contract cannot support gate reduction."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidGateReducerError(message)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(char in _SHA256_HEX for char in value)
    )


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _text_attr(value: Any, name: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise NativeFluidGateReducerError(f"table {name} is not valid UTF-8") from error
    raise NativeFluidGateReducerError(f"table {name} attribute is not text")


def _frozen_case_contract(case_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _require(case_id in registry.frozen_qualification_case_ids(),
             "case_id is outside the frozen 15-case qualification denominator")
    scope, _pack = registry._read_frozen_inputs()
    _require(scope.get("scope_id") == SCOPE_ID,
             "frozen R008 scope identity differs from the gate reducer")
    matrix = scope.get("matrix")
    _require(isinstance(matrix, dict), "frozen R008 scope matrix is malformed")
    rows = matrix.get("rows")
    _require(isinstance(rows, list), "frozen R008 matrix rows are absent")
    matches = [row for row in rows if isinstance(row, dict) and row.get("case_id") == case_id]
    _require(len(matches) == 1 and matches[0].get("qualification_only") is True,
             "case_id is not exactly one frozen qualification row")
    pack_row = bundle._frozen_qualification_row(case_id)
    case_row = matches[0]
    for field in (
        "observation_start_s", "observation_end_s", "period_s",
        "native_output_samples_per_period", "expected_observation_output_count",
    ):
        _require(case_row.get(field) == pack_row.get(field),
                 f"scope/Definition-control mismatch in frozen field {field}")

    integrity = scope.get("predeclared_t1_gates", {}).get("source_hard_integrity_gates")
    _require(isinstance(integrity, dict), "frozen source hard-integrity gates are absent")
    density_range = integrity.get("density_kg_m3")
    mach_limit = integrity.get("mach_max")
    physics = scope.get("frozen_physics_and_control")
    _require(isinstance(physics, dict), "frozen R008 physics/control contract is malformed")
    sound_speed = physics.get("sound_speed_m_s")
    _require(isinstance(density_range, list) and len(density_range) == 2
             and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(float(value)) for value in density_range),
             "frozen density interval is malformed")
    _require(isinstance(mach_limit, (int, float)) and not isinstance(mach_limit, bool)
             and math.isfinite(float(mach_limit)), "frozen Mach limit is malformed")
    _require(isinstance(sound_speed, (int, float)) and not isinstance(sound_speed, bool)
             and math.isfinite(float(sound_speed)) and float(sound_speed) > 0.0,
             "frozen sound speed is malformed")
    _require(tuple(float(value) for value in density_range) == (950.0, 1050.0)
             and float(mach_limit) == 0.0010125 and float(sound_speed) == 10.0,
             "frozen R008 density/Mach semantics changed; a reviewed contract revision is required")
    return case_row, pack_row, {
        "density_min_kg_m3": float(density_range[0]),
        "density_max_kg_m3": float(density_range[1]),
        "mach_max": float(mach_limit),
        "sound_speed_m_s": float(sound_speed),
    }


def _validate_table_verification(
    verified: Mapping[str, Any], *, case_id: str, expected_bytes: int, expected_sha256: str,
) -> tuple[int, int]:
    _require(isinstance(verified, Mapping) and set(verified) == TABLE_VERIFICATION_FIELDS,
             "native table verification result fields are not exact")
    _require(isinstance(verified.get("table_bytes"), int)
             and not isinstance(verified.get("table_bytes"), bool)
             and isinstance(verified.get("table_sha256"), str)
             and isinstance(verified.get("qualification_credit"), int)
             and not isinstance(verified.get("qualification_credit"), bool),
             "native table verification byte/hash/credit types are malformed")
    _require(verified.get("schema") == table_v2.SCHEMA
             and verified.get("table_schema") == table_v2.TABLE_SCHEMA
             and verified.get("case_id") == case_id
             and verified.get("table_bytes") == expected_bytes
             and verified.get("table_sha256") == expected_sha256
             and verified.get("full_time_axis_matches") is True
             and verified.get("fluid_id_projection_matches") is True
             and verified.get("position_velocity_density_mass_recomputed") is True
             and verified.get("all_valid") is True
             and verified.get("native_integrity_evaluated") is False
             and verified.get("T1_numerical") is False
             and verified.get("qualification_credit") == 0,
             "gate reducer requires the complete zero-credit native-table v2 verification")
    time_rows, particle_count = verified.get("time_rows"), verified.get("fluid_particle_count")
    _require(isinstance(time_rows, int) and not isinstance(time_rows, bool)
             and 2 <= time_rows <= table_v2.MAX_TIME_ROWS
             and isinstance(particle_count, int) and not isinstance(particle_count, bool)
             and 1 <= particle_count <= table_v2.MAX_PARTICLE_ROWS
             and time_rows * particle_count <= table_v2.MAX_TIME_PARTICLE_CELLS
             and verified.get("raw_frames_recomputed") == time_rows,
             "verified table dimensions/source-frame count are outside frozen bounds")
    return time_rows, particle_count


def _reduce_window(
    density_ds: h5py.Dataset,
    velocity_ds: h5py.Dataset,
    selected_indices: np.ndarray,
    particle_count: int,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    density_min = math.inf
    density_max = -math.inf
    mach_max = 0.0
    density_outside_count = 0
    mach_exceedance_count = 0
    for row_value in selected_indices:
        row = int(row_value)
        for start in range(0, particle_count, PARTICLE_CHUNK):
            stop = min(particle_count, start + PARTICLE_CHUNK)
            density = np.asarray(density_ds[row, start:stop], dtype=np.float64)
            velocity = np.asarray(velocity_ds[row, start:stop, :], dtype=np.float64)
            _require(density.shape == (stop - start,)
                     and velocity.shape == (stop - start, 3)
                     and np.isfinite(density).all() and np.isfinite(velocity).all(),
                     "selected native fluid density/velocity contains missing or non-finite values")
            density_min = min(density_min, float(np.min(density)))
            density_max = max(density_max, float(np.max(density)))
            density_outside_count += int(np.count_nonzero(
                (density < thresholds["density_min_kg_m3"])
                | (density > thresholds["density_max_kg_m3"])
            ))
            speed = np.hypot(np.hypot(velocity[:, 0], velocity[:, 1]), velocity[:, 2])
            mach = speed / thresholds["sound_speed_m_s"]
            _require(np.isfinite(mach).all(), "selected native fluid Mach values are non-finite")
            local_max = float(np.max(mach))
            mach_max = max(mach_max, local_max)
            mach_exceedance_count += int(np.count_nonzero(mach > thresholds["mach_max"]))
    return {
        "density_min_kg_m3": density_min,
        "density_max_kg_m3": density_max,
        "density_outside_count": density_outside_count,
        "mach_max": mach_max,
        "mach_exceedance_count": mach_exceedance_count,
    }


def evaluate_native_fluid_window_gates_fd(
    table_fd: int,
    *,
    table_verification: Mapping[str, Any],
    expected_table_bytes: int,
    expected_table_sha256: str,
) -> dict[str, Any]:
    """Evaluate the three frozen fluid/window gates from one held read-only table FD.

    The caller must keep the D table descriptor open and revalidate its B/C/D
    provenance chain before and after this call. Evidence hashes here identify
    the exact table bytes; this function does not authenticate caller inputs.
    """
    _require(isinstance(expected_table_bytes, int) and not isinstance(expected_table_bytes, bool)
             and 0 < expected_table_bytes <= table_v2.MAX_TABLE_FILE_BYTES,
             "expected native table byte count is malformed")
    _require(_sha256(expected_table_sha256), "expected native table SHA-256 is malformed")
    case_id = table_verification.get("case_id") if isinstance(table_verification, Mapping) else None
    _require(isinstance(case_id, str) and case_id, "native table verification has no case identity")
    time_rows, particle_count = _validate_table_verification(
        table_verification, case_id=case_id, expected_bytes=expected_table_bytes,
        expected_sha256=expected_table_sha256,
    )
    case_row, pack_row, thresholds = _frozen_case_contract(case_id)

    before = os.fstat(table_fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_size == expected_table_bytes,
             "native table FD is not the expected single-link regular file")
    try:
        access_mode = fcntl.fcntl(table_fd, fcntl.F_GETFL) & os.O_ACCMODE
    except OSError as error:
        raise NativeFluidGateReducerError("native table FD access mode could not be verified") from error
    _require(access_mode == os.O_RDONLY, "native gate reducer requires a read-only held table FD")
    _require(table_v2._sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "held native table bytes differ from the semantic verification binding")

    time_count = int(case_row["observation_cycles"]) * int(
        case_row["native_output_samples_per_period"],
    ) + 1
    _require(case_row.get("expected_observation_output_count") == time_count,
             "frozen inclusive observation count differs from cycles × cadence + endpoints")

    file_obj = os.fdopen(os.dup(table_fd), "rb", buffering=0)
    try:
        with h5py.File(file_obj, "r", driver="fileobj") as handle:
            _require(set(handle.keys()) == {
                "time", "particle_id", "position", "velocity", "density", "mass", "valid",
            }, "native table datasets differ from the closed v2 schema")
            _require(_text_attr(handle.attrs.get("f8_table_schema"), "f8_table_schema")
                     == table_v2.TABLE_SCHEMA
                     and _text_attr(handle.attrs.get("scope_id"), "scope_id") == SCOPE_ID
                     and _text_attr(handle.attrs.get("case_id"), "case_id") == case_id,
                     "native table root identity differs from the frozen R008 case")
            time_ds, ids_ds = handle["time"], handle["particle_id"]
            position_ds, velocity_ds = handle["position"], handle["velocity"]
            density_ds, mass_ds, valid_ds = handle["density"], handle["mass"], handle["valid"]
            _require(time_ds.shape == (time_rows,) and time_ds.dtype == np.dtype("<f8")
                     and ids_ds.shape == (particle_count,) and ids_ds.dtype == np.dtype("<u4")
                     and position_ds.shape == (time_rows, particle_count, 3)
                     and position_ds.dtype == np.dtype("<f8")
                     and velocity_ds.shape == (time_rows, particle_count, 3)
                     and velocity_ds.dtype == np.dtype("<f4")
                     and density_ds.shape == (time_rows, particle_count)
                     and density_ds.dtype == np.dtype("<f4")
                     and mass_ds.shape == (time_rows, particle_count)
                     and mass_ds.dtype == np.dtype("<f4")
                     and valid_ds.shape == (time_rows, particle_count)
                     and valid_ds.dtype == np.dtype("?"),
                     "native table dimensions/dtypes differ from the closed v2 schema")
            times = np.asarray(time_ds[:], dtype=np.float64)
            particle_ids = np.asarray(ids_ds[:], dtype=np.uint32)
            _require(np.isfinite(times).all() and times[0] == 0.0
                     and np.all(np.diff(times) > 0.0)
                     and len(np.unique(particle_ids)) == particle_count,
                     "native table time or fluid-ID axis is invalid")
            expected_axis = bundle.expected_time_axis_hex(pack_row)
            _require(len(expected_axis) == time_rows
                     and all(struct.pack("<d", float.fromhex(value))
                             == struct.pack("<d", float(observed))
                             for value, observed in zip(expected_axis, times)),
                     "native table time axis differs from the exact frozen full axis")

            selected_times, selected_indices = select_closed_native_window(
                times, np.arange(time_rows, dtype=np.float64),
                start_s=float(case_row["observation_start_s"]),
                end_s=float(case_row["observation_end_s"]),
                period_s=float(case_row["period_s"]),
                output_samples_per_period=int(case_row["native_output_samples_per_period"]),
                cycles=int(case_row["observation_cycles"]),
            )
            indices = np.asarray(selected_indices, dtype=np.int64)
            _require(len(selected_times) == time_count and len(indices) == time_count
                     and np.array_equal(indices, np.arange(indices[0], indices[-1] + 1))
                     and selected_times[0] == times[int(indices[0])]
                     and selected_times[-1] == times[int(indices[-1])],
                     "native table does not contain the exact inclusive three-period window")
            _require(time_count * particle_count <= MAX_SELECTED_TIME_PARTICLE_CELLS,
                     "selected native window exceeds the frozen table working-set bound")
            reduced = _reduce_window(density_ds, velocity_ds, indices, particle_count, thresholds)
    except NativeFluidGateReducerError:
        raise
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        raise NativeFluidGateReducerError("native table could not be reduced under the frozen R008 contract") from error
    finally:
        file_obj.close()

    after = os.fstat(table_fd)
    _require(_identity(before) == _identity(after)
             and table_v2._sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "held native table changed during fluid/window gate reduction")
    evidence_sha = expected_table_sha256
    gate_results = {
        "density_range": {
            "status": "defined_pass" if reduced["density_outside_count"] == 0 else "defined_fail",
            "evidence_sha256": evidence_sha,
        },
        "mach_limit": {
            "status": "defined_pass" if reduced["mach_exceedance_count"] == 0 else "defined_fail",
            "evidence_sha256": evidence_sha,
        },
        "inclusive_three_period_window_complete": {
            "status": "defined_pass",
            "evidence_sha256": evidence_sha,
        },
    }
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "case_id": case_id,
        "status": "partial_native_fluid_gate_subset_evaluated",
        "source_table_schema": table_v2.TABLE_SCHEMA,
        "source_table_bytes": expected_table_bytes,
        "source_table_sha256": expected_table_sha256,
        "frozen_scope_sha256": registry.FROZEN_SCOPE_SHA256,
        "frozen_definition_pack_sha256": registry.FROZEN_DEFINITION_PACK_SHA256,
        "observation_window": {
            "start_s": float(case_row["observation_start_s"]),
            "end_s": float(case_row["observation_end_s"]),
            "start_ordinal": int(indices[0]),
            "end_ordinal": int(indices[-1]),
            "sample_count": time_count,
            "expected_sample_count": time_count,
            "cycles": int(case_row["observation_cycles"]),
            "samples_per_period": int(case_row["native_output_samples_per_period"]),
        },
        "thresholds": dict(thresholds),
        "observed": reduced,
        "evaluated_gate_ids": list(SAMPLED_GATE_IDS),
        "unevaluated_gate_ids": list(UNEVALUATED_GATE_IDS),
        "gate_results": gate_results,
        "caller_must_revalidate_B_C_D_chain": True,
        "B_C_D_chain_validation_performed_by_reducer": False,
        "evidence_bindings_verified": False,
        "native_integrity_gates_evaluated": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = [
    "NativeFluidGateReducerError", "SCHEMA", "SAMPLED_GATE_IDS",
    "UNEVALUATED_GATE_IDS", "evaluate_native_fluid_window_gates_fd",
]
