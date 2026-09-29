"""Fail-closed solver-output descriptor to Core-input projection for F8/R008.

This module is the deliberately narrow boundary between a future verified
R008 output bundle and the existing Core trajectory materializer.  It accepts
only bounded canonical JSON bytes describing one qualification case.  It
checks the descriptor's case/attempt bindings, fixed artifact roles, safe
relative paths, frame ordinals, canonical binary64 time axis, byte/hash
limits, and the existing frozen case-id set.

The descriptor is still caller-supplied and therefore untrusted.  A valid
projection is a diagnostic input plan, not evidence that the files exist,
that a solver produced them, that a runtime is trusted, or that a terminal
observation occurred.  This module has no filesystem, HDF5, BI4, subprocess,
GPU, queue, registry, ledger, denominator, gate, or completion side effect.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping

from scripts import core_strict_json
from scripts import f8_r008_native_integrity_registry_v1 as native_registry
from scripts import f8_r008_safe_bi4_decoder_v1 as safe_bi4


SCHEMA = "core.cfd.f8.r008_solver_output_core_input_gate.v1"
PROJECTION_SCHEMA = "core.cfd.f8.r008_core_input_projection.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_solver_output_core_input_gate_report.v1"
RECORD_ID = "f8-r008-solver-output-core-input-gate-v1"
REPORT_RECORD_ID = "f8-r008-solver-output-core-input-gate-report-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
STATUS = "diagnostic_solver_output_core_input_projection"
INPUT_ORIGIN = "caller_supplied_diagnostic_descriptor"
MAX_JSON_BYTES = 256 * 1024
MAX_FRAME_COUNT = 1497
MAX_FRAME_BYTES = safe_bi4.MAX_RAW_BYTES
MAX_TABLE_BYTES = 2 * 1024**3
MAX_TOTAL_OUTPUT_BYTES = 2 * 1024**3
MAX_PARTICLE_COUNT = safe_bi4.MAX_ARRAY_COUNT
MAX_PATH_DEPTH = 8
MAX_IDENTIFIER_BYTES = 128
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z", re.ASCII)
_HEX = frozenset("0123456789abcdef")
_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)

ARTIFACT_FIELDS = frozenset({"role", "path", "bytes", "sha256"})
FRAME_FIELDS = frozenset({"ordinal", "path", "bytes", "sha256", "time_ieee754_hex"})
ATTEMPT_FIELDS = frozenset({"attempt_id", "nonce_hex"})
INPUT_BINDING_FIELDS = frozenset({
    "definition_sha256", "control_sha256", "initial_state_sha256",
    "configuration_sha256", "parameter_contract_sha256",
    "raw_solver_manifest_sha256", "decoded_frame_manifest_sha256",
    "native_table_sha256", "case_np", "fluid_particle_count",
    "fluid_id_order_sha256",
})
OUTPUT_FIELDS = frozenset({
    "case_id", "attempt_id", "nonce_hex",
    "raw_solver_manifest", "decoded_frame_manifest", "native_fluid_table",
    "frames", "frame_count", "case_np", "fluid_particle_count",
    "fluid_id_order_sha256", "frame_manifest_sha256", "time_axis_sha256",
})
CORE_PROJECTION_FIELDS = frozenset({
    "schema", "case_id", "output_filename", "trajectory_schema",
    "source_table_schema", "fluid_only", "particle_zone_semantics",
})
AUTHORIZATION_FIELDS = frozenset({
    "diagnostic_only", "source_authenticated", "runtime_authenticated",
    "terminal_observation_verified", "native_integrity_evaluated",
    "solver_execution_adjudicated", "T1_numerical", "readiness_pass",
    "formal_eligible", "solver_invoked", "worker_or_scheduler_launch_invoked",
    "gpu_or_queue_invoked", "qualification_credit", "registry_mutation",
    "ledger_mutation", "denominator_mutation", "gate_mutation",
    "completion_mutation",
})
TOP_LEVEL_FIELDS = frozenset({
    "schema", "scope_id", "input_origin", "case_id", "split", "attempt",
    "input_bindings", "output", "core_projection", "authorization",
})

EXPECTED_CORE_PROJECTION = {
    "schema": PROJECTION_SCHEMA,
    "output_filename": "core-trajectory-v1.h5",
    "trajectory_schema": "core.f8.r008.diagnostic_trajectory.v1",
    "source_table_schema": "core.cfd.f8.r008_native_fluid_frame_table.v2",
    "fluid_only": True,
    "particle_zone_semantics": "all_native_fluid_particles_zone_zero",
}
EXPECTED_AUTHORIZATION = {
    "diagnostic_only": True,
    "source_authenticated": False,
    "runtime_authenticated": False,
    "terminal_observation_verified": False,
    "native_integrity_evaluated": False,
    "solver_execution_adjudicated": False,
    "T1_numerical": False,
    "readiness_pass": False,
    "formal_eligible": False,
    "solver_invoked": False,
    "worker_or_scheduler_launch_invoked": False,
    "gpu_or_queue_invoked": False,
    "qualification_credit": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}


class SolverOutputCoreInputGateError(ValueError):
    """The untrusted solver-output descriptor is malformed or overclaims."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SolverOutputCoreInputGateError(message)


def _canonical(value: Any, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise SolverOutputCoreInputGateError(f"{label} is not canonical JSON") from error


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(value: Any, label: str) -> str:
    return _sha256_bytes(_canonical(value, label))


def _parse(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES,
             "solver-output descriptor is outside the bounded byte limit")
    try:
        value = core_strict_json.strict_json_object(
            raw, label="F8 R008 solver-output descriptor", max_bytes=MAX_JSON_BYTES,
        )
    except ValueError as error:
        raise SolverOutputCoreInputGateError(str(error)) from error
    _require(_canonical(value, "solver-output descriptor") == raw,
             "solver-output descriptor must be exact canonical JSON bytes")
    return value


def _identifier(value: Any, label: str) -> None:
    _require(type(value) is str and len(value.encode("utf-8")) <= MAX_IDENTIFIER_BYTES
             and bool(_IDENTIFIER.fullmatch(value)),
             f"{label} is not a bounded lowercase identifier")


def _sha256(value: Any, label: str) -> None:
    _require(type(value) is str and bool(_SHA256.fullmatch(value)),
             f"{label} is not lowercase SHA-256")


def _nonce(value: Any, label: str) -> None:
    _require(type(value) is str and bool(_NONCE.fullmatch(value)),
             f"{label} is not lowercase 128-bit hex")


def _relative_path(value: Any, label: str) -> None:
    _require(type(value) is str and bool(value) and "\\" not in value
             and not value.startswith("/") and not value.endswith("/"),
             f"{label} must be a relative POSIX path")
    parts = value.split("/")
    _require(len(parts) <= MAX_PATH_DEPTH and all(parts),
             f"{label} has too many or empty path components")
    for part in parts:
        _require(part not in {".", ".."} and bool(_PATH_COMPONENT.fullmatch(part)),
                 f"{label} contains an unsafe path component")


def _artifact(value: Any, *, role: str, max_bytes: int, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == ARTIFACT_FIELDS,
             f"{label} fields are not exact")
    _require(value["role"] == role, f"{label} role is not {role}")
    _relative_path(value["path"], f"{label}.path")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= max_bytes,
             f"{label}.bytes is outside the bounded artifact limit")
    _sha256(value["sha256"], f"{label}.sha256")
    return dict(value)


def _time(value: Any, label: str) -> float:
    _require(type(value) is str and 0 < len(value) <= 32,
             f"{label} must be a bounded hexadecimal binary64 string")
    try:
        parsed = float.fromhex(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise SolverOutputCoreInputGateError(f"{label} is not hexadecimal binary64") from error
    _require(math.isfinite(parsed) and parsed.hex() == value,
             f"{label} is non-finite or non-canonical")
    return parsed


def _validate_attempt(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == ATTEMPT_FIELDS,
             "attempt fields are not exact")
    _identifier(value["attempt_id"], "attempt.attempt_id")
    _nonce(value["nonce_hex"], "attempt.nonce_hex")
    return dict(value)


def _validate_input_bindings(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == INPUT_BINDING_FIELDS,
             "input_bindings fields are not exact")
    for field in INPUT_BINDING_FIELDS - {"case_np", "fluid_particle_count", "fluid_id_order_sha256"}:
        _sha256(value[field], f"input_bindings.{field}")
    _require(type(value["case_np"]) is int and 0 < value["case_np"] <= MAX_PARTICLE_COUNT,
             "input_bindings.case_np is outside the bounded native particle domain")
    _require(type(value["fluid_particle_count"]) is int
             and 0 < value["fluid_particle_count"] <= value["case_np"],
             "input_bindings.fluid_particle_count is outside the case particle domain")
    _sha256(value["fluid_id_order_sha256"], "input_bindings.fluid_id_order_sha256")
    return dict(value)


def _validate_frames(value: Any, *, expected_case_np: int) -> tuple[list[dict[str, Any]], int, str, str, int]:
    _require(type(value) is list and 2 <= len(value) <= MAX_FRAME_COUNT,
             "output.frames must contain a bounded complete frame descriptor list")
    frames: list[dict[str, Any]] = []
    paths: set[str] = set()
    total_bytes = 0
    previous_time: float | None = None
    for ordinal, frame in enumerate(value):
        _require(type(frame) is dict and set(frame) == FRAME_FIELDS,
                 f"output.frames[{ordinal}] fields are not exact")
        _require(type(frame["ordinal"]) is int and frame["ordinal"] == ordinal,
                 "frame ordinals must be a contiguous zero-based sequence")
        expected_path = f"frames/Part_{ordinal:04d}.bi4"
        _relative_path(frame["path"], f"output.frames[{ordinal}].path")
        _require(frame["path"] == expected_path,
                 f"output.frames[{ordinal}].path is not the fixed R008 frame path")
        _require(frame["path"] not in paths, "output frame paths must be unique")
        paths.add(frame["path"])
        _require(type(frame["bytes"]) is int and 0 < frame["bytes"] <= MAX_FRAME_BYTES,
                 f"output.frames[{ordinal}].bytes is outside the BI4 bound")
        total_bytes += frame["bytes"]
        _require(total_bytes <= MAX_TOTAL_OUTPUT_BYTES,
                 "declared solver-output bytes exceed the aggregate bound")
        _sha256(frame["sha256"], f"output.frames[{ordinal}].sha256")
        current_time = _time(frame["time_ieee754_hex"],
                             f"output.frames[{ordinal}].time_ieee754_hex")
        _require(previous_time is None or current_time > previous_time,
                 "output frame times must be strictly increasing")
        previous_time = current_time
        frames.append(dict(frame))
    frame_manifest_sha256 = _sha256_json(frames, "output.frames")
    time_axis = [frame["time_ieee754_hex"] for frame in frames]
    time_axis_sha256 = _sha256_json(time_axis, "output time axis")
    return frames, len(frames), frame_manifest_sha256, time_axis_sha256, total_bytes


def _validate_output(
    value: Any,
    *,
    expected_case_id: str,
    expected_attempt: Mapping[str, Any],
    input_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == OUTPUT_FIELDS,
             "output fields are not exact")
    _require(value["case_id"] == expected_case_id,
             "output.case_id differs from the descriptor case binding")
    _require(value["attempt_id"] == expected_attempt["attempt_id"],
             "output.attempt_id differs from the descriptor attempt binding")
    _require(value["nonce_hex"] == expected_attempt["nonce_hex"],
             "output.nonce_hex differs from the descriptor attempt binding")
    _nonce(value["nonce_hex"], "output.nonce_hex")
    raw_manifest = _artifact(
        value["raw_solver_manifest"], role="raw_solver_manifest", max_bytes=MAX_JSON_BYTES,
        label="output.raw_solver_manifest",
    )
    decoded_manifest = _artifact(
        value["decoded_frame_manifest"], role="decoded_frame_manifest", max_bytes=MAX_JSON_BYTES,
        label="output.decoded_frame_manifest",
    )
    native_table = _artifact(
        value["native_fluid_table"], role="native_fluid_table", max_bytes=MAX_TABLE_BYTES,
        label="output.native_fluid_table",
    )
    _require(raw_manifest["path"] == "manifests/outputs-manifest.json",
             "raw solver manifest path is not the fixed D-stage path")
    _require(decoded_manifest["path"] == "manifests/decoded-frame-manifest.json",
             "decoded frame manifest path is not the fixed D-stage path")
    _require(native_table["path"] == "outputs/native-fluid-frame-table-v2.h5",
             "native table path is not the fixed D-stage path")
    _require(raw_manifest["sha256"] == input_bindings["raw_solver_manifest_sha256"],
             "raw solver manifest digest is not bound to input_bindings")
    _require(decoded_manifest["sha256"] == input_bindings["decoded_frame_manifest_sha256"],
             "decoded frame manifest digest is not bound to input_bindings")
    _require(native_table["sha256"] == input_bindings["native_table_sha256"],
             "native table digest is not bound to input_bindings")

    _require(type(value["frame_count"]) is int and 2 <= value["frame_count"] <= MAX_FRAME_COUNT,
             "output.frame_count is outside the bounded complete-frame domain")
    _require(type(value["case_np"]) is int and 0 < value["case_np"] <= MAX_PARTICLE_COUNT,
             "output.case_np is outside the bounded native particle domain")
    _require(value["case_np"] == input_bindings["case_np"],
             "output.case_np differs from the descriptor's frozen input binding")
    _require(type(value["fluid_particle_count"]) is int
             and 0 < value["fluid_particle_count"] <= value["case_np"],
             "output.fluid_particle_count is outside the case particle domain")
    _require(value["fluid_particle_count"] == input_bindings["fluid_particle_count"],
             "output.fluid_particle_count differs from the descriptor's frozen input binding")
    _sha256(value["fluid_id_order_sha256"], "output.fluid_id_order_sha256")
    _require(value["fluid_id_order_sha256"] == input_bindings["fluid_id_order_sha256"],
             "output.fluid_id_order_sha256 differs from the descriptor's frozen input binding")
    frames, frame_count, frame_manifest_sha256, time_axis_sha256, frame_bytes = _validate_frames(
        value["frames"], expected_case_np=value["case_np"],
    )
    _require(value["frame_count"] == frame_count,
             "output.frame_count differs from the descriptor frame list")
    _require(value["frame_manifest_sha256"] == frame_manifest_sha256,
             "output.frame_manifest_sha256 does not cover the exact frame list")
    _sha256(value["frame_manifest_sha256"], "output.frame_manifest_sha256")
    _require(value["time_axis_sha256"] == time_axis_sha256,
             "output.time_axis_sha256 does not cover the exact frame time axis")
    _sha256(value["time_axis_sha256"], "output.time_axis_sha256")
    total_bytes = frame_bytes + raw_manifest["bytes"] + decoded_manifest["bytes"] + native_table["bytes"]
    _require(total_bytes <= MAX_TOTAL_OUTPUT_BYTES,
             "declared solver-output artifact bytes exceed the aggregate bound")
    return {
        "raw_solver_manifest": raw_manifest,
        "decoded_frame_manifest": decoded_manifest,
        "native_fluid_table": native_table,
        "frames": frames,
        "frame_count": frame_count,
        "case_np": value["case_np"],
        "fluid_particle_count": value["fluid_particle_count"],
        "fluid_id_order_sha256": value["fluid_id_order_sha256"],
        "frame_manifest_sha256": frame_manifest_sha256,
        "time_axis_sha256": time_axis_sha256,
    }


def _validate_core_projection(value: Any, *, case_id: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == CORE_PROJECTION_FIELDS,
             "core_projection fields are not exact")
    expected = {**EXPECTED_CORE_PROJECTION, "case_id": case_id}
    _require(value == expected, "core_projection differs from the fixed diagnostic Core schema")
    return dict(value)


def _validate_authorization(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == AUTHORIZATION_FIELDS,
             "authorization fields are not exact")
    _require(value == EXPECTED_AUTHORIZATION,
             "solver-output descriptor contains an authority, terminal, or credit claim")
    return dict(value)


def project_solver_output_to_core_input(raw: bytes) -> dict[str, Any]:
    """Project one untrusted canonical descriptor into a diagnostic Core plan.

    The returned object contains only copied descriptor bindings and fixed
    false/zero authorization boundaries.  It does not return a file
    descriptor, capability, execution permission, or qualification result.
    """
    value = _parse(raw)
    _require(set(value) == TOP_LEVEL_FIELDS, "solver-output descriptor fields are not exact")
    _require(value["schema"] == SCHEMA, "solver-output descriptor schema is unsupported")
    _require(value["scope_id"] == SCOPE_ID, "solver-output descriptor scope is unsupported")
    _require(value["input_origin"] == INPUT_ORIGIN,
             "solver-output descriptor input origin is not the fixed diagnostic origin")
    _identifier(value["case_id"], "case_id")
    _require(value["case_id"] in native_registry.EXPECTED_QUALIFICATION_CASE_IDS,
             "case_id is outside the existing frozen R008 qualification set")
    _require(value["split"] == "qualification", "solver-output descriptor split is not qualification")
    attempt = _validate_attempt(value["attempt"])
    input_bindings = _validate_input_bindings(value["input_bindings"])
    output = _validate_output(
        value["output"], expected_case_id=value["case_id"], expected_attempt=attempt,
        input_bindings=input_bindings,
    )
    core_projection = _validate_core_projection(value["core_projection"], case_id=value["case_id"])
    authorization = _validate_authorization(value["authorization"])
    descriptor_digest = _sha256_bytes(raw)
    return {
        "schema": PROJECTION_SCHEMA,
        "status": STATUS,
        "scope_id": SCOPE_ID,
        "input_descriptor_sha256": descriptor_digest,
        "case_id": value["case_id"],
        "split": "qualification",
        "attempt": attempt,
        "input_bindings": dict(input_bindings),
        "core_projection": core_projection,
        "output": output,
        "authorization": authorization,
    }


def build_report() -> dict[str, Any]:
    """Return the immutable, non-authorizing implementation report."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": "synthetic_only_diagnostic_core_input_gate_implemented",
        "component": {
            "schema": SCHEMA,
            "projection_schema": PROJECTION_SCHEMA,
            "scope_id": SCOPE_ID,
            "input": "bounded canonical in-memory JSON bytes",
            "case_domain": "existing frozen R008 qualification IDs",
            "artifact_roles": [
                "raw_solver_manifest",
                "decoded_frame_manifest",
                "native_fluid_table",
                "ordered_native_bi4_frames",
            ],
            "core_output": "diagnostic Core trajectory input projection only",
        },
        "checks": [
            "strict UTF-8 JSON with duplicate-key and non-finite rejection",
            "exact top-level and nested field sets",
            "fixed R008 D-stage manifest/table paths",
            "case/attempt/input digest binding",
            "contiguous unique frame paths and ordinals",
            "canonical strictly increasing binary64 time axis",
            "per-frame, per-artifact, and aggregate byte caps",
            "fixed diagnostic/zero-credit authorization boundary",
        ],
        "non_authorizing_boundary": {
            "production_paths_read": False,
            "solver_invoked": False,
            "worker_or_scheduler_launch_invoked": False,
            "gpu_or_queue_invoked": False,
            "privileged_probe_invoked": False,
            "native_integrity_evaluated": False,
            "terminal_observation_verified": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "formal_eligible": False,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "remaining_blockers": [
            "caller descriptor is not producer-authenticated",
            "actual B/C/D bundle verifier and held-FD source-frame reader must run before materialization",
            "target kernel/source/build/runtime pins and trusted worker identity remain external blockers",
            "terminal/native-integrity/T1 adjudication remains absent",
        ],
    }


__all__ = [
    "AUTHORIZATION_FIELDS", "EXPECTED_AUTHORIZATION", "EXPECTED_CORE_PROJECTION",
    "MAX_FRAME_BYTES", "MAX_FRAME_COUNT", "MAX_JSON_BYTES", "MAX_PARTICLE_COUNT",
    "PROJECTION_SCHEMA", "REPORT_RECORD_ID", "REPORT_SCHEMA", "SCHEMA", "SCOPE_ID",
    "SolverOutputCoreInputGateError", "build_report", "project_solver_output_to_core_input",
]
