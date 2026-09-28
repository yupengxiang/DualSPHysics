"""Source-bound, synthetic-only cross-evidence diagnostic for F8/R008.

The existing R008 components deliberately stop at different boundaries: the
native registry aggregates caller-supplied gate cells, the RunPARTs adapter
diagnoses an untrusted timestep claim, and the execution journal/termination
contracts inspect their own local shapes.  This additive sidecar binds those
three observations to one static source-semantic snapshot and one synthetic
attempt envelope.  It does not authenticate a production source, process,
loaded module, runtime, solver, worker, queue, or output.

The sidecar is intentionally not an execution or qualification adapter.  A
structurally consistent synthetic envelope is reported as *untrusted*;
``native_integrity_adjudicated``, ``solver_timestep_adjudicated``, normal
termination, T1, readiness, and credit remain false/zero.  Source binding
drift, cross-case rebinding, malformed evidence, and semantic inconsistencies
fail closed rather than being converted into a positive claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts import f8_r008_native_integrity_registry_v1 as native_registry
from scripts import f8_r008_runtime_timestep_adjudicator_v1 as runtime_adjudicator
from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts
from scripts import f8_r008_timestep_source_semantics_v1 as source_semantics


SCHEMA = "core.cfd.f8.r008.source_bound_native_timestep_termination_adjudication.v1"
INPUT_SCHEMA = "core.cfd.f8.r008.source_bound_native_timestep_termination_input.v1"
REPORT_SCHEMA = "core.f8.r008.source_bound_native_timestep_termination_report.v1"
RECORD_ID = "f8-r008-source-bound-native-timestep-termination-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SYNTHETIC_MODE = "synthetic_only"
NATIVE_SCHEMA = "core.cfd.f8.r008.synthetic_native_observation.v1"
TIMESTEP_SCHEMA = "core.cfd.f8.r008.synthetic_timestep_observation.v1"
TERMINATION_SCHEMA = "core.cfd.f8.r008.synthetic_termination_observation.v1"
CASE_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MAX_RAW_BYTES = 4 * 1024 * 1024
MAX_CASES = 15
MAX_EVENTS = 32
EARLY_STOP_FLAGS = (
    "nstepsbreak_observed",
    "minimum_fluid_stop_observed",
    "terminate_file_observed",
    "terminate_applied",
    "terminate_warning_observed",
    "unregistered_control_override_observed",
)
TERMINATION_EVENT_KINDS = ("solver_started", "output_finalized", "solver_exit")

TOP_INPUT_FIELDS = frozenset({"schema", "mode", "source_binding", "cases"})
SOURCE_BINDING_FIELDS = frozenset({
    "scope_id", "audit_schema", "audit_record_id", "source_files_sha256",
    "source_projection_sha256",
})
CASE_INPUT_FIELDS = frozenset({
    "case_id", "attempt_nonce_hex", "source_binding_sha256", "native",
    "timestep", "termination", "evidence_bindings",
})
NATIVE_INPUT_FIELDS = frozenset({
    "schema", "frame_count", "expected_frame_count", "particle_count",
    "all_required_state_values_finite", "validity_mismatch_count",
    "mass_error_kg", "gate_results",
})
TIMESTEP_INPUT_FIELDS = frozenset({
    "schema", "runparts_raw", "effective_step_algorithm_claim",
    "runtime_completion_evidence",
})
TERMINATION_INPUT_FIELDS = frozenset({
    "schema", "frozen_time_max_s", "observed_final_time_s", "tolerance_s",
    "process_exit_code", "early_stop_flags", "event_sequence",
    "output_coverage_complete_claim", "observed_frame_count",
})
EVIDENCE_BINDING_FIELDS = frozenset({
    "native_sha256", "timestep_sha256", "termination_sha256", "bundle_sha256",
})


class SourceBoundAdjudicationError(ValueError):
    """Synthetic input is malformed, rebinding is observed, or a claim is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceBoundAdjudicationError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any, label: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SourceBoundAdjudicationError(f"{label} is not canonical JSON") from error


def _json_sha256(value: Any, label: str) -> str:
    return _sha256(_canonical(value, label))


def _sha256_value(value: Any, label: str) -> str:
    _require(type(value) is str and SHA256.fullmatch(value) is not None,
             f"{label} must be a lowercase SHA-256")
    return value


def _finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    _require(type(value) in (int, float) and type(value) is not bool,
             f"{label} must be a finite builtin number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise SourceBoundAdjudicationError(f"{label} must be a finite builtin number") from error
    _require(math.isfinite(result), f"{label} must be a finite builtin number")
    if minimum is not None:
        _require(result >= minimum, f"{label} is below its minimum")
    return result


def _uint(value: Any, label: str, *, minimum: int = 0, maximum: int = 2**31 - 1) -> int:
    _require(type(value) is int and minimum <= value <= maximum,
             f"{label} must be an integer in the bounded domain")
    return value


def _source_anchor() -> dict[str, Any]:
    """Build the source snapshot used for static binding, never runtime trust."""
    try:
        audit = source_semantics.build_audit()
    except (OSError, source_semantics.TimestepSemanticsError) as error:
        raise SourceBoundAdjudicationError(
            f"static timestep source audit cannot be read: {error}"
        ) from error
    _require(type(audit) is dict and audit.get("schema") == source_semantics.SCHEMA,
             "static timestep source audit schema is not the expected version")
    _require(type(audit.get("record_id")) is str and audit["record_id"],
             "static timestep source audit record ID is missing")
    evidence = audit.get("source_evidence")
    _require(type(evidence) is dict and evidence,
             "static timestep source audit has no source evidence")
    source_files: dict[str, str] = {}
    source_projection_files: dict[str, dict[str, Any]] = {}
    for name in sorted(evidence):
        item = evidence[name]
        _require(type(name) is str and type(item) is dict,
                 "static source evidence entry is malformed")
        _require({"path", "bytes", "sha256"} <= set(item),
                 f"static source evidence entry lacks required fields: {name}")
        _uint(item["bytes"], f"static source evidence bytes: {name}", minimum=1,
              maximum=64 * 1024 * 1024)
        digest = _sha256_value(item["sha256"], f"static source evidence hash: {name}")
        _require(type(item["path"]) is str and item["path"] and ".." not in Path(item["path"]).parts,
                 f"static source evidence path is malformed: {name}")
        source_files[name] = digest
        source_projection_files[name] = dict(item)
    projection = {
        "scope_id": SCOPE_ID,
        "audit_schema": audit["schema"],
        "audit_record_id": audit["record_id"],
        "backend_scope": audit.get("backend_scope"),
        "source_evidence": source_projection_files,
        "static_findings": audit.get("static_findings"),
        "runtime_completion_evidence_contract": audit.get("runtime_completion_evidence_contract"),
    }
    public = {
        "scope_id": SCOPE_ID,
        "audit_schema": audit["schema"],
        "audit_record_id": audit["record_id"],
        "source_files_sha256": source_files,
        "source_projection_sha256": _json_sha256(projection, "source projection"),
    }
    return {"public": public, "digest": _json_sha256(public, "source binding")}


def _validate_source_binding(value: Any, anchor: dict[str, Any]) -> str:
    _require(type(value) is dict and set(value) == SOURCE_BINDING_FIELDS,
             "source_binding fields do not match the exact contract")
    _require(value == anchor["public"],
             "source_binding does not exactly match the current static source snapshot")
    return anchor["digest"]


def _validate_gate_results(value: Any, label: str) -> dict[str, dict[str, Any]]:
    _require(type(value) is dict and set(value) == set(native_registry.GATE_IDS),
             f"{label} must contain exactly the frozen eight gate IDs")
    normalized: dict[str, dict[str, Any]] = {}
    for gate_id in native_registry.GATE_IDS:
        cell = value[gate_id]
        _require(type(cell) is dict and set(cell) == {"status", "evidence_sha256"},
                 f"{label}.{gate_id} has unexpected fields")
        status = cell["status"]
        _require(status in native_registry.VALID_STATES,
                 f"{label}.{gate_id} has an invalid gate status")
        evidence = cell["evidence_sha256"]
        if status in ("defined_pass", "defined_fail"):
            _sha256_value(evidence, f"{label}.{gate_id}.evidence_sha256")
        else:
            _require(evidence is None or (type(evidence) is str and SHA256.fullmatch(evidence)),
                     f"{label}.{gate_id}.evidence_sha256 is malformed")
        normalized[gate_id] = {"status": status, "evidence_sha256": evidence}
    return normalized


def _validate_native(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == NATIVE_INPUT_FIELDS,
             f"{label} fields do not match the exact synthetic native schema")
    _require(value["schema"] == NATIVE_SCHEMA, f"{label}.schema is not synthetic-only")
    frame_count = _uint(value["frame_count"], f"{label}.frame_count", minimum=1, maximum=4096)
    expected = _uint(value["expected_frame_count"], f"{label}.expected_frame_count", minimum=1, maximum=4096)
    particle_count = _uint(value["particle_count"], f"{label}.particle_count", minimum=1, maximum=10_000_000)
    _require(type(value["all_required_state_values_finite"]) is bool,
             f"{label}.all_required_state_values_finite must be boolean")
    mismatch = _uint(value["validity_mismatch_count"], f"{label}.validity_mismatch_count", maximum=10_000_000)
    mass_error = _finite_number(value["mass_error_kg"], f"{label}.mass_error_kg", minimum=0.0)
    gates = _validate_gate_results(value["gate_results"], f"{label}.gate_results")
    return {
        "schema": NATIVE_SCHEMA,
        "frame_count": frame_count,
        "expected_frame_count": expected,
        "particle_count": particle_count,
        "all_required_state_values_finite": value["all_required_state_values_finite"],
        "validity_mismatch_count": mismatch,
        "mass_error_kg": mass_error,
        "gate_results": gates,
    }


def _validate_timestep(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == TIMESTEP_INPUT_FIELDS,
             f"{label} fields do not match the exact synthetic timestep schema")
    _require(value["schema"] == TIMESTEP_SCHEMA, f"{label}.schema is not synthetic-only")
    _require(type(value["runparts_raw"]) is bytes and 0 < len(value["runparts_raw"]) <= MAX_RAW_BYTES,
             f"{label}.runparts_raw must be bounded raw bytes")
    _require(type(value["effective_step_algorithm_claim"]) is str
             and value["effective_step_algorithm_claim"] in {"verlet", "symplectic"},
             f"{label}.effective_step_algorithm_claim is malformed")
    _require(type(value["runtime_completion_evidence"]) is dict,
             f"{label}.runtime_completion_evidence must be a builtin dict")
    return {
        "schema": TIMESTEP_SCHEMA,
        "runparts_raw": value["runparts_raw"],
        "effective_step_algorithm_claim": value["effective_step_algorithm_claim"],
        "runtime_completion_evidence": value["runtime_completion_evidence"].copy(),
    }


def _validate_termination(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == TERMINATION_INPUT_FIELDS,
             f"{label} fields do not match the exact synthetic termination schema")
    _require(value["schema"] == TERMINATION_SCHEMA, f"{label}.schema is not synthetic-only")
    frozen = _finite_number(value["frozen_time_max_s"], f"{label}.frozen_time_max_s", minimum=0.0)
    observed = _finite_number(value["observed_final_time_s"], f"{label}.observed_final_time_s", minimum=0.0)
    tolerance = _finite_number(value["tolerance_s"], f"{label}.tolerance_s", minimum=0.0)
    exit_code = value["process_exit_code"]
    _require(type(exit_code) is int and type(exit_code) is not bool,
             f"{label}.process_exit_code must be an integer")
    flags = value["early_stop_flags"]
    _require(type(flags) is dict and set(flags) == set(EARLY_STOP_FLAGS),
             f"{label}.early_stop_flags fields do not match the exact set")
    _require(all(type(flags[key]) is bool for key in EARLY_STOP_FLAGS),
             f"{label}.early_stop_flags values must be boolean")
    events = value["event_sequence"]
    _require(type(events) is list and 0 < len(events) <= MAX_EVENTS,
             f"{label}.event_sequence must be a bounded nonempty list")
    normalized_events = []
    for index, event in enumerate(events, start=1):
        _require(type(event) is dict and set(event) == {"seq", "kind"},
                 f"{label}.event_sequence[{index - 1}] has unexpected fields")
        _require(event["seq"] == index, f"{label}.event_sequence is not contiguous")
        _require(event["kind"] in TERMINATION_EVENT_KINDS,
                 f"{label}.event_sequence contains an unknown event kind")
        normalized_events.append({"seq": index, "kind": event["kind"]})
    _require(type(value["output_coverage_complete_claim"]) is bool,
             f"{label}.output_coverage_complete_claim must be boolean")
    observed_frames = _uint(value["observed_frame_count"], f"{label}.observed_frame_count",
                            minimum=0, maximum=4096)
    return {
        "schema": TERMINATION_SCHEMA,
        "frozen_time_max_s": frozen,
        "observed_final_time_s": observed,
        "tolerance_s": tolerance,
        "process_exit_code": exit_code,
        "early_stop_flags": {key: flags[key] for key in EARLY_STOP_FLAGS},
        "event_sequence": normalized_events,
        "output_coverage_complete_claim": value["output_coverage_complete_claim"],
        "observed_frame_count": observed_frames,
    }


def _timestep_projection(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": value["schema"],
        "runparts_raw_bytes": len(value["runparts_raw"]),
        "runparts_raw_sha256": _sha256(value["runparts_raw"]),
        "effective_step_algorithm_claim": value["effective_step_algorithm_claim"],
        "runtime_completion_evidence": value["runtime_completion_evidence"],
    }


def _case_bundle_projection(
    case_id: str,
    nonce: str,
    source_binding_sha256: str,
    bindings: dict[str, str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "attempt_nonce_hex": nonce,
        "source_binding_sha256": source_binding_sha256,
        "native_sha256": bindings["native_sha256"],
        "timestep_sha256": bindings["timestep_sha256"],
        "termination_sha256": bindings["termination_sha256"],
    }


def _validate_evidence_bindings(
    value: Any,
    *,
    case_id: str,
    nonce: str,
    source_binding_sha256: str,
    native: dict[str, Any],
    timestep: dict[str, Any],
    termination: dict[str, Any],
) -> dict[str, str]:
    _require(type(value) is dict and set(value) == EVIDENCE_BINDING_FIELDS,
             f"case {case_id}.evidence_bindings has unexpected fields")
    expected = {
        "native_sha256": _json_sha256(native, f"case {case_id} native observation"),
        "timestep_sha256": _json_sha256(_timestep_projection(timestep), f"case {case_id} timestep observation"),
        "termination_sha256": _json_sha256(termination, f"case {case_id} termination observation"),
    }
    for key, digest in expected.items():
        _require(value[key] == digest,
                 f"case {case_id}.{key} does not bind the exact synthetic observation")
    bundle_digest = _json_sha256(
        _case_bundle_projection(case_id, nonce, source_binding_sha256, expected),
        f"case {case_id} bundle projection",
    )
    _require(value["bundle_sha256"] == bundle_digest,
             f"case {case_id}.bundle_sha256 does not bind the case envelope")
    return {**expected, "bundle_sha256": bundle_digest}


def _diagnose_termination(
    termination: dict[str, Any],
    timestep: dict[str, Any],
    timestep_diagnostic: dict[str, Any],
    native: dict[str, Any],
) -> dict[str, Any]:
    runtime = timestep["runtime_completion_evidence"]
    violations: list[str] = []
    if termination["frozen_time_max_s"] != runtime["frozen_time_max_s"]:
        violations.append("frozen_time_max_rebound_between_timestep_and_termination")
    if termination["observed_final_time_s"] != runtime["final_time_s"]:
        violations.append("final_time_rebound_between_timestep_and_termination")
    if termination["process_exit_code"] != runtime["process_exit_code"]:
        violations.append("process_exit_code_rebound_between_timestep_and_termination")
    for key in EARLY_STOP_FLAGS:
        if termination["early_stop_flags"][key] != runtime[key]:
            violations.append(f"termination_flag_rebound:{key}")
    expected_tolerance = runtime["absolute_tolerance_s"] + runtime["relative_tolerance"] * abs(
        runtime["frozen_time_max_s"]
    )
    if termination["tolerance_s"] != expected_tolerance:
        violations.append("termination_tolerance_rebound_or_unrecomputed")
    if abs(termination["observed_final_time_s"] - termination["frozen_time_max_s"]) > termination["tolerance_s"]:
        violations.append("synthetic_final_time_outside_declared_tolerance")
    if termination["process_exit_code"] != 0:
        violations.append("synthetic_solver_exit_code_nonzero")
    if any(termination["early_stop_flags"].values()):
        violations.append("synthetic_early_stop_or_control_override_observed")
    event_kinds = [event["kind"] for event in termination["event_sequence"]]
    if event_kinds != list(TERMINATION_EVENT_KINDS):
        violations.append("synthetic_termination_event_sequence_incomplete_or_reordered")
    if termination["output_coverage_complete_claim"] is not True:
        violations.append("synthetic_output_coverage_not_claimed_complete")
    if termination["observed_frame_count"] != native["frame_count"]:
        violations.append("native_frame_count_rebound_at_termination")
    if termination["observed_frame_count"] != native["expected_frame_count"]:
        violations.append("termination_frame_count_does_not_match_expected_frame_count")
    if timestep_diagnostic["runparts_runtime_claims_consistent_untrusted"] is not True:
        violations.append("runparts_runtime_claims_not_consistent_untrusted")
    return {
        "schema": TERMINATION_SCHEMA,
        "status": (
            "synthetic_termination_observation_consistent_untrusted"
            if not violations else "synthetic_termination_observation_inconsistent_untrusted"
        ),
        "violations": violations,
        "event_sequence_complete_untrusted": event_kinds == list(TERMINATION_EVENT_KINDS),
        "output_coverage_complete_untrusted": termination["output_coverage_complete_claim"] is True,
        "normal_completion_verified": False,
        "termination_adjudicated": False,
        "source_runtime_authenticated": False,
        "production_authority": False,
    }


def _make_case_output(
    case: dict[str, Any],
    source_binding_sha256: str,
    native: dict[str, Any],
    timestep: dict[str, Any],
    termination: dict[str, Any],
    bindings: dict[str, str],
    timestep_diagnostic: dict[str, Any],
    native_registry_result: dict[str, Any],
) -> dict[str, Any]:
    native_consistent = (
        native["frame_count"] == native["expected_frame_count"]
        and native["all_required_state_values_finite"] is True
        and native["validity_mismatch_count"] == 0
        and native["mass_error_kg"] == 0.0
    )
    termination_diagnostic = _diagnose_termination(
        termination, timestep, timestep_diagnostic, native,
    )
    case_consistent = (
        native_consistent
        and timestep_diagnostic["runparts_runtime_claims_consistent_untrusted"] is True
        and not termination_diagnostic["violations"]
    )
    return {
        "case_id": case["case_id"],
        "attempt_nonce_sha256": _sha256(case["attempt_nonce_hex"].encode("ascii")),
        "source_binding_sha256": source_binding_sha256,
        "evidence_bindings": bindings,
        "diagnostic_status": (
            "source_bound_synthetic_observations_consistent_untrusted"
            if case_consistent else "source_bound_synthetic_observations_inconsistent_untrusted"
        ),
        "native_integrity": {
            "observation_consistent_untrusted": native_consistent,
            "registry_aggregation_status": native_registry_result["aggregation_status"],
            "registry_state_counts": native_registry_result["state_counts"],
            "native_integrity_adjudicated": False,
            "production_native_source_authenticated": False,
        },
        "solver_timestep": {
            "diagnostic": timestep_diagnostic,
            "solver_timestep_adjudicated": False,
            "production_runtime_authenticated": False,
        },
        "termination": termination_diagnostic,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


def adjudicate_source_bound_synthetic_input(value: Mapping[str, Any]) -> dict[str, Any]:
    """Cross-bind one complete synthetic 15-case envelope without authority."""
    _require(type(value) is dict and set(value) == TOP_INPUT_FIELDS,
             "top-level input fields do not match the exact source-bound contract")
    _require(value["schema"] == INPUT_SCHEMA and value["mode"] == SYNTHETIC_MODE,
             "input must explicitly declare the synthetic-only schema and mode")
    anchor = _source_anchor()
    source_binding_sha256 = _validate_source_binding(value["source_binding"], anchor)
    cases = value["cases"]
    _require(type(cases) is list and len(cases) == MAX_CASES,
             "source-bound synthetic input must contain exactly 15 cases")

    normalized_cases: list[dict[str, Any]] = []
    nonces: set[str] = set()
    registry_rows: list[dict[str, Any]] = []
    validated_parts: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]] = []
    for index, case in enumerate(cases):
        label = f"case row {index}"
        _require(type(case) is dict and set(case) == CASE_INPUT_FIELDS,
                 f"{label} fields do not match the exact source-bound case schema")
        case_id = case["case_id"]
        _require(case_id == native_registry.EXPECTED_QUALIFICATION_CASE_IDS[index],
                 f"{label} case_id is missing, duplicated, substituted, or out of order")
        nonce = case["attempt_nonce_hex"]
        _require(type(nonce) is str and CASE_NONCE.fullmatch(nonce) is not None,
                 f"{label}.attempt_nonce_hex is malformed")
        _require(nonce not in nonces, f"{label}.attempt_nonce_hex is reused")
        nonces.add(nonce)
        _require(case["source_binding_sha256"] == source_binding_sha256,
                 f"{label}.source_binding_sha256 is rebound")
        native = _validate_native(case["native"], f"{label}.native")
        timestep = _validate_timestep(case["timestep"], f"{label}.timestep")
        termination = _validate_termination(case["termination"], f"{label}.termination")
        bindings = _validate_evidence_bindings(
            case["evidence_bindings"], case_id=case_id, nonce=nonce,
            source_binding_sha256=source_binding_sha256, native=native,
            timestep=timestep, termination=termination,
        )
        normalized_case = {
            "case_id": case_id,
            "attempt_nonce_hex": nonce,
            "source_binding_sha256": source_binding_sha256,
            "native": native,
            "timestep": timestep,
            "termination": termination,
            "evidence_bindings": bindings,
        }
        normalized_cases.append(normalized_case)
        registry_rows.append({"case_id": case_id, "gate_results": native["gate_results"]})

    try:
        native_registry_result = native_registry.aggregate_native_integrity_statuses(registry_rows)
    except native_registry.NativeIntegrityRegistryError as error:
        raise SourceBoundAdjudicationError(
            f"native gate registry rejected the source-bound matrix: {error}"
        ) from error

    output_cases: list[dict[str, Any]] = []
    for case in normalized_cases:
        try:
            timestep_diagnostic = runtime_adjudicator.diagnose_runtime_timestep_case_v1(
                case_id=case["case_id"],
                runparts_raw=case["timestep"]["runparts_raw"],
                effective_step_algorithm_claim=case["timestep"]["effective_step_algorithm_claim"],
                runtime_completion_evidence=case["timestep"]["runtime_completion_evidence"],
            )
        except runtime_adjudicator.RuntimeTimestepAdjudicatorError as error:
            raise SourceBoundAdjudicationError(
                f"case {case['case_id']} runtime/timestep diagnostic failed closed: {error}"
            ) from error
        expected_files = _source_anchor()["public"]["source_files_sha256"]
        observed_files = {
            name: item["sha256"]
            for name, item in timestep_diagnostic["source_semantics"]["source_files"].items()
        }
        _require(observed_files == expected_files,
                 f"case {case['case_id']} timestep source evidence is not source-bound")
        output_cases.append(_make_case_output(
            case,
            source_binding_sha256,
            case["native"],
            case["timestep"],
            case["termination"],
            case["evidence_bindings"],
            timestep_diagnostic,
            native_registry_result,
        ))

    consistent_count = sum(
        item["diagnostic_status"] == "source_bound_synthetic_observations_consistent_untrusted"
        for item in output_cases
    )
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": (
            "source_bound_synthetic_observations_consistent_untrusted"
            if consistent_count == MAX_CASES
            else "source_bound_synthetic_observations_inconsistent_untrusted"
        ),
        "diagnostic_only": True,
        "synthetic_inputs_only": True,
        "source_binding": {
            **value["source_binding"],
            "binding_verified_against_current_static_audit": True,
            "production_source_authenticated": False,
            "loaded_module_identity_verified": False,
            "runtime_identity_verified": False,
        },
        "case_count": MAX_CASES,
        "consistent_case_count_untrusted": consistent_count,
        "native_registry": {
            "schema": native_registry_result["schema"],
            "aggregation_status": native_registry_result["aggregation_status"],
            "state_counts": native_registry_result["state_counts"],
            "gate_state_counts": native_registry_result["gate_state_counts"],
            "denominator_cells": native_registry_result["denominator_cells"],
            "evidence_bindings_verified": False,
            "native_integrity_evaluated": False,
        },
        "cases": output_cases,
        "native_integrity_adjudicated": False,
        "solver_timestep_adjudicated": False,
        "termination_adjudicated": False,
        "normal_completion_verified": False,
        "execution_authority": {
            "solver": False, "worker": False, "gpu": False, "queue": False,
            "root_or_capability_probe": False,
        },
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "gate_mutations": 0,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


def _synthetic_runparts() -> bytes:
    def row(part: int, time_s: str, steps: int, dtmin: str, dtmax: str) -> str:
        cells = ["0"] * len(runparts.RUNPARTS_HEADER)
        cells[0] = str(part)
        cells[1] = time_s
        cells[2] = str(steps)
        cells[19] = dtmin
        cells[20] = dtmax
        return ";".join(cells)

    return ("\n".join((
        ";".join(runparts.RUNPARTS_HEADER),
        row(0, "0", 0, "0", "0"),
        row(1, "10.0", 10, "0.001", "0.002"),
        "",
        *runparts.RUNPARTS_FOOTER,
        "",
    ))).encode("utf-8")


def _synthetic_runtime_completion() -> dict[str, Any]:
    return {
        "backend": "standard_cpu_single",
        "frozen_time_max_s": 10.0,
        "effective_time_max_s": 10.0,
        "final_time_s": 10.0,
        "absolute_tolerance_s": 0.001,
        "relative_tolerance": 0.001,
        "tolerance_preregistration_claim": True,
        "tolerance_receipt_sha256": "a" * 64,
        "process_exit_code": 0,
        "nstepsbreak_observed": False,
        "minimum_fluid_stop_observed": False,
        "terminate_file_observed": False,
        "terminate_applied": False,
        "terminate_warning_observed": False,
        "unregistered_control_override_observed": False,
        "gpu_enabled": False,
        "openmp_enabled": False,
        "vres_enabled": False,
    }


def build_synthetic_input() -> dict[str, Any]:
    """Create a deterministic valid fixture for tests and the non-authorizing report."""
    anchor = _source_anchor()
    source_binding = anchor["public"]
    source_binding_sha256 = anchor["digest"]
    gates = {}
    for gate_id, definition_status, _outcomes in native_registry.GATE_REGISTRY:
        status = "open" if definition_status == "open" else "defined_pass"
        gates[gate_id] = {
            "status": status,
            "evidence_sha256": "a" * 64 if status == "defined_pass" else None,
        }
    cases: list[dict[str, Any]] = []
    for index, case_id in enumerate(native_registry.EXPECTED_QUALIFICATION_CASE_IDS, start=1):
        native = {
            "schema": NATIVE_SCHEMA,
            "frame_count": 2,
            "expected_frame_count": 2,
            "particle_count": 4,
            "all_required_state_values_finite": True,
            "validity_mismatch_count": 0,
            "mass_error_kg": 0.0,
            "gate_results": json.loads(json.dumps(gates)),
        }
        timestep = {
            "schema": TIMESTEP_SCHEMA,
            "runparts_raw": _synthetic_runparts(),
            "effective_step_algorithm_claim": "verlet",
            "runtime_completion_evidence": _synthetic_runtime_completion(),
        }
        termination = {
            "schema": TERMINATION_SCHEMA,
            "frozen_time_max_s": 10.0,
            "observed_final_time_s": 10.0,
            "tolerance_s": 0.011,
            "process_exit_code": 0,
            "early_stop_flags": {key: False for key in EARLY_STOP_FLAGS},
            "event_sequence": [
                {"seq": 1, "kind": "solver_started"},
                {"seq": 2, "kind": "output_finalized"},
                {"seq": 3, "kind": "solver_exit"},
            ],
            "output_coverage_complete_claim": True,
            "observed_frame_count": 2,
        }
        expected = {
            "native_sha256": _json_sha256(native, f"fixture {case_id} native"),
            "timestep_sha256": _json_sha256(_timestep_projection(timestep), f"fixture {case_id} timestep"),
            "termination_sha256": _json_sha256(termination, f"fixture {case_id} termination"),
        }
        bindings = {
            **expected,
            "bundle_sha256": _json_sha256(
                _case_bundle_projection(
                    case_id, f"{index:032x}", source_binding_sha256, expected,
                ),
                f"fixture {case_id} bundle",
            ),
        }
        cases.append({
            "case_id": case_id,
            "attempt_nonce_hex": f"{index:032x}",
            "source_binding_sha256": source_binding_sha256,
            "native": native,
            "timestep": timestep,
            "termination": termination,
            "evidence_bindings": bindings,
        })
    return {
        "schema": INPUT_SCHEMA,
        "mode": SYNTHETIC_MODE,
        "source_binding": source_binding,
        "cases": cases,
    }


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def build_synthetic_report() -> dict[str, Any]:
    """Return a compact JSON-serializable report for this static work package."""
    fixture = build_synthetic_input()
    result = adjudicate_source_bound_synthetic_input(fixture)
    implementation = Path(__file__).resolve()
    test = implementation.parents[1] / "tests/test_f8_r008_source_bound_native_timestep_termination_adjudication_v1.py"
    return {
        "schema": REPORT_SCHEMA,
        "report_id": "f8-r008-source-bound-native-timestep-termination-2026-09-28",
        "diagnostic_only": True,
        "audit": {
            "readiness_v8_blocker": "native_integrity_and_solver_timestep_adjudication_missing",
            "existing_contracts_checked": [
                "f8_r008_native_integrity_registry_v1",
                "f8_r008_native_state_finite_evidence_v1",
                "f8_r008_runtime_timestep_adjudicator_v1",
                "f8_r008_timestep_source_semantics_v1",
                "f8_r008_c_execution_journal_v5",
                "f8_r008_final_fput_join_reducer_v3",
            ],
            "concrete_gap": (
                "No existing contract exact-binds one static source snapshot, one attempt nonce, "
                "the 15-case native gate matrix, RunPARTs timestep observations, and termination/output "
                "coverage observations; each existing component remains local and non-authorizing."
            ),
            "increment_is_non_duplicate": True,
        },
        "contract": {
            "schema": SCHEMA,
            "input_schema": INPUT_SCHEMA,
            "mode": SYNTHETIC_MODE,
            "case_count": MAX_CASES,
            "native_gate_count": native_registry.GATE_COUNT,
            "source_binding_is_static_only": True,
            "caller_supplied_inputs_cannot_authenticate_production": True,
        },
        "result": {
            "status": result["status"],
            "case_count": result["case_count"],
            "consistent_case_count_untrusted": result["consistent_case_count_untrusted"],
            "native_registry_aggregation_status": result["native_registry"]["aggregation_status"],
            "native_integrity_adjudicated": result["native_integrity_adjudicated"],
            "solver_timestep_adjudicated": result["solver_timestep_adjudicated"],
            "termination_adjudicated": result["termination_adjudicated"],
            "normal_completion_verified": result["normal_completion_verified"],
            "T1_numerical": result["T1_numerical"],
            "readiness_pass": result["readiness_pass"],
            "qualification_credit": result["qualification_credit"],
        },
        "safety_boundary": {
            "production_source_authenticated": result["source_binding"]["production_source_authenticated"],
            "loaded_module_identity_verified": result["source_binding"]["loaded_module_identity_verified"],
            "runtime_identity_verified": result["source_binding"]["runtime_identity_verified"],
            "solver_started": result["execution_authority"]["solver"],
            "worker_started": result["execution_authority"]["worker"],
            "gpu_started": result["execution_authority"]["gpu"],
            "queue_started": result["execution_authority"]["queue"],
            "registry_mutations": result["registry_mutations"],
            "ledger_mutations": result["ledger_mutations"],
            "gate_mutations": result["gate_mutations"],
        },
        "artifacts": {
            "implementation": {
                "path": "scripts/f8_r008_source_bound_native_timestep_termination_adjudication_v1.py",
                "sha256": _file_sha256(implementation),
            },
            "test": {
                "path": "tests/test_f8_r008_source_bound_native_timestep_termination_adjudication_v1.py",
                "sha256": _file_sha256(test),
            },
        },
    }


__all__ = [
    "CASE_NONCE", "INPUT_SCHEMA", "NATIVE_SCHEMA", "REPORT_SCHEMA", "RECORD_ID",
    "SCHEMA", "SCOPE_ID", "SourceBoundAdjudicationError", "TERMINATION_SCHEMA",
    "TIMESTEP_SCHEMA", "adjudicate_source_bound_synthetic_input", "build_synthetic_input",
    "build_synthetic_report",
]
