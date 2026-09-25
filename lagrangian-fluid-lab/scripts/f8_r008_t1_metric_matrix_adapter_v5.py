"""Compose frozen F8 R008 matrix-v4 and untrusted per-case diagnostics.

This layer takes original RunPARTs bytes and caller runtime claims for all
fifteen frozen cases. It invokes matrix-v4 itself (the caller cannot provide a
serialized matrix result), binds the two frozen timestep-pair inputs to the
RunPARTs files reparsed by matrix-v4, and delegates that pair to the existing
frozen-pair diagnostic. All outputs remain diagnostic-only and untrusted.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from typing import Any, Mapping

from scripts import f8_r008_runtime_timestep_adjudicator_v1 as case_adjudicator
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2
from scripts import f8_r008_t1_metric_matrix_adapter_v4 as matrix_v4
from scripts import f8_r008_timestep_comparison_diagnostic_v1 as pair_v1


SCHEMA = "core.cfd.f8.r008_t1_metric_matrix_adapter.v5"
CASE_COUNT = 15
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MATRIX_V4_RESULT_FIELDS = frozenset({
    "schema", "scope_id", "frozen_scope_receipt_sha256", "parameter_contract_sha256",
    "table_review_receipt_sha256", "metric_review_receipt_sha256", "status", "case_count",
    "case_result_bindings", "failed_case_metric_gate_ids", "case_metric_gates_passed",
    "cross_resolution", "cross_resolution_gates_passed", "time_step_comparison",
    "output_cadence_comparison", "all_metric_and_comparison_gates_passed",
    "case_failure_denominator_fixed", "per_case_B_C_D_chain_reverified_by_matrix",
    "external_receipt_authenticity_verified_by_matrix", "native_integrity_evaluated",
    "execution_source_identity_verified", "solver_completion_verified",
    "full_t1_decision", "readiness_pass", "qualification_credit",
})
CASE_RESULT_BINDING_FIELDS = frozenset({
    "metric_result_sha256", "receipt_sha256", "manifest_sha256",
    "native_fluid_table_sha256",
})
B_C_D_FIELDS = frozenset({"B", "C", "D"})
MATRIX_V4_TIME_FIELDS = frozenset({
    "baseline_case_id", "refined_case_id", "baseline_observed_recorded_part_dtmax_s",
    "refined_observed_recorded_part_dtmax_s", "baseline_runparts_parse_diagnostic",
    "refined_runparts_parse_diagnostic", "wrapped_center_phase_difference_rad",
    "adjudication_status", "unverified_source_observation_relation_code",
    "runparts_source_content_recomputed", "input_scope",
    "all_26_fields_type_and_range_checked", "cross_field_native_semantics_verified",
    "execution_attempt_identity_verified", "runtime_configuration_verified",
    "normal_completion_verified", "frozen_end_time_reached", "passed",
})
RUNPARTS_RECEIPT_FIELDS = frozenset({
    "schema", "status", "input_scope", "case_id_claim",
    "maximum_recorded_part_dtmax_s", "checks", "source_runparts", "parse_summary",
    "attempt_identity_verified", "runtime_configuration_verified",
    "cross_field_native_semantics_verified", "normal_completion_verified",
    "qualification_credit",
})
CASE_OBSERVATION_FIELDS = frozenset({
    "schema", "input_scope", "bytes", "sha256", "data_row_count",
    "last_recorded_time_s", "footer_present", "maximum_recorded_part_dtmax_s",
    "all_26_fields_type_and_range_checked", "cross_field_native_semantics_verified",
})
OUTPUT_FIELDS = frozenset({
    "schema", "status", "case_count", "case_ids", "case_failure_denominator_fixed",
    "matrix_v4_observations", "case_diagnostics", "runtime_horizon_claim_alignment_untrusted",
    "frozen_pair_diagnostic", "qualification_boundaries",
})


class MetricMatrixV5Error(ValueError):
    """The v5 diagnostic inputs do not match the frozen R008 contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MetricMatrixV5Error(message)


def _snapshot_mapping(
    value: Any,
    expected_keys: set[str],
    label: str,
) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    try:
        snapshot = dict(value)
    except (TypeError, ValueError) as error:
        raise MetricMatrixV5Error(f"{label} cannot be snapshotted") from error
    _require(set(snapshot) == expected_keys,
             f"{label} must contain exactly the frozen 15 case IDs")
    return snapshot


def _frozen_rows() -> tuple[list[str], dict[str, dict[str, Any]]]:
    try:
        loaded = matrix_v2._load_frozen_contract()
    except Exception as error:
        raise MetricMatrixV5Error(f"frozen matrix contract could not be loaded: {error}") from error
    _require(type(loaded) is tuple and len(loaded) == 7
             and type(loaded[0]) is dict
             and type(loaded[0].get("matrix")) is dict,
             "matrix-v2 frozen contract has an unexpected shape")
    rows = loaded[0]["matrix"].get("rows")
    _require(type(rows) is list and len(rows) == CASE_COUNT
             and all(type(row) is dict for row in rows),
             "frozen R008 matrix must contain exactly 15 rows")
    case_ids = [row.get("case_id") for row in rows]
    _require(all(type(case_id) is str and case_id for case_id in case_ids)
             and len(set(case_ids)) == CASE_COUNT,
             "frozen R008 matrix case IDs must be unique strings")
    row_by_id = {row["case_id"]: dict(row) for row in rows}
    _require(all(type(row.get("observation_end_s")) in (int, float)
                 and math.isfinite(row["observation_end_s"])
                 and row["observation_end_s"] > 0.0
                 for row in row_by_id.values()),
             "each frozen row must declare a finite positive observation_end_s")
    _require(pair_v1.BASELINE_CASE_ID in row_by_id
             and pair_v1.REFINED_CASE_ID in row_by_id,
             "frozen timestep pair IDs are not in the 15-case matrix")
    return case_ids, row_by_id


def _snapshot_inputs(
    *,
    case_results: Any,
    solver_timestep_sources: Any,
    runparts_raw_by_case: Any,
    effective_step_algorithm_claims: Any,
    runtime_completion_evidence: Any,
    case_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes], dict[str, str], dict[str, dict[str, Any]]]:
    frozen_ids = set(case_ids)
    pair_ids = {pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID}
    results = _snapshot_mapping(case_results, frozen_ids, "case_results")
    for case_id, row in results.items():
        _require(type(row) is dict,
                 f"case_results[{case_id}] must be an original per-case v2 input mapping")
        # The v4 envelope is not a per-case row and may never be accepted as one.
        _require(row.get("schema") != matrix_v4.SCHEMA,
                 f"case_results[{case_id}] looks like serialized matrix-v4 output")
        results[case_id] = dict(row)

    sources = _snapshot_mapping(
        solver_timestep_sources, pair_ids, "solver_timestep_sources",
    )
    for case_id, path in sources.items():
        _require(isinstance(path, (str, Path)),
                 f"solver_timestep_sources[{case_id}] must be a filesystem path")

    raw_by_case = _snapshot_mapping(runparts_raw_by_case, frozen_ids, "runparts_raw_by_case")
    for case_id, raw in raw_by_case.items():
        _require(type(raw) is bytes,
                 f"runparts_raw_by_case[{case_id}] must be exact original bytes, not a diagnostic")

    algorithms = _snapshot_mapping(
        effective_step_algorithm_claims, frozen_ids, "effective_step_algorithm_claims",
    )
    for case_id, algorithm in algorithms.items():
        _require(type(algorithm) is str and algorithm in {"verlet", "symplectic"},
                 f"effective StepAlgorithm claim is invalid for {case_id}")

    runtime = _snapshot_mapping(
        runtime_completion_evidence, frozen_ids, "runtime_completion_evidence",
    )
    for case_id, evidence in runtime.items():
        _require(type(evidence) is dict,
                 f"runtime_completion_evidence[{case_id}] must be a builtin dict")
        runtime[case_id] = evidence.copy()

    return results, sources, raw_by_case, algorithms, runtime


def _validate_matrix_v4_result(
    result: Any,
    *,
    case_ids: list[str],
    raw_by_case: Mapping[str, bytes],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float]:
    _require(type(result) is dict and set(result) == MATRIX_V4_RESULT_FIELDS
             and result.get("schema") == matrix_v4.SCHEMA
             and result.get("status")
             == "fresh_segment_matrix_diagnostics_evaluated_execution_provenance_pending"
             and result.get("case_count") == CASE_COUNT
             and result.get("case_failure_denominator_fixed") is True
             and isinstance(result.get("case_result_bindings"), dict)
             and set(result["case_result_bindings"]) == set(case_ids)
             and result.get("native_integrity_evaluated") is False
             and result.get("execution_source_identity_verified") is False
             and result.get("solver_completion_verified") is False
             and result.get("full_t1_decision") is False
             and result.get("readiness_pass") is False
             and type(result.get("qualification_credit")) is int
             and result["qualification_credit"] == 0,
             "matrix-v4 recomputation returned an unexpected schema or qualification state")

    case_result_bindings: dict[str, dict[str, Any]] = {}
    for case_id, binding in result["case_result_bindings"].items():
        _require(type(binding) is dict and set(binding) == CASE_RESULT_BINDING_FIELDS
                 and type(binding.get("metric_result_sha256")) is str
                 and SHA256.fullmatch(binding["metric_result_sha256"]) is not None
                 and type(binding.get("native_fluid_table_sha256")) is str
                 and SHA256.fullmatch(binding["native_fluid_table_sha256"]) is not None
                 and all(type(binding.get(field)) is dict
                         and set(binding[field]) == B_C_D_FIELDS
                         and all(type(binding[field].get(axis)) is str
                                 and SHA256.fullmatch(binding[field][axis]) is not None
                                 for axis in B_C_D_FIELDS)
                         for field in ("receipt_sha256", "manifest_sha256")),
                 f"matrix-v4 case-result binding is malformed for {case_id}")
        # Keep only the four reviewed digest bindings; never forward an
        # upstream nested success, trust, or qualification field.
        case_result_bindings[case_id] = {
            "metric_result_sha256": binding["metric_result_sha256"],
            "receipt_sha256": {
                axis: binding["receipt_sha256"][axis] for axis in sorted(B_C_D_FIELDS)
            },
            "manifest_sha256": {
                axis: binding["manifest_sha256"][axis] for axis in sorted(B_C_D_FIELDS)
            },
            "native_fluid_table_sha256": binding["native_fluid_table_sha256"],
        }

    comparison = result.get("time_step_comparison")
    _require(type(comparison) is dict and set(comparison) == MATRIX_V4_TIME_FIELDS
             and comparison.get("baseline_case_id") == pair_v1.BASELINE_CASE_ID
             and comparison.get("refined_case_id") == pair_v1.REFINED_CASE_ID
             and comparison.get("adjudication_status")
             == "diagnostic_only_fresh_segment_identity_and_completion_unverified"
             and comparison.get("runparts_source_content_recomputed") is True
             and comparison.get("input_scope")
             == "fresh_single_segment_part0_time0_only"
             and comparison.get("all_26_fields_type_and_range_checked") is True
             and comparison.get("cross_field_native_semantics_verified") is False
             and comparison.get("execution_attempt_identity_verified") is False
             and comparison.get("runtime_configuration_verified") is False
             and comparison.get("normal_completion_verified") is False
             and comparison.get("frozen_end_time_reached") is False
             and comparison.get("passed") is False,
             "matrix-v4 timestep observation no longer matches the diagnostic-only contract")

    pair_inputs: dict[str, dict[str, Any]] = {}
    pair_parse_receipts: dict[str, dict[str, Any]] = {}
    for role, case_id, dt_field, receipt_field in (
        ("baseline", pair_v1.BASELINE_CASE_ID,
         "baseline_observed_recorded_part_dtmax_s", "baseline_runparts_parse_diagnostic"),
        ("refined", pair_v1.REFINED_CASE_ID,
         "refined_observed_recorded_part_dtmax_s", "refined_runparts_parse_diagnostic"),
    ):
        raw = raw_by_case[case_id]
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        receipt = comparison[receipt_field]
        _require(type(receipt) is dict and set(receipt) == RUNPARTS_RECEIPT_FIELDS
                 and receipt.get("schema") == "core.cfd.f8.r008_runparts_timestep_diagnostic.v2"
                 and receipt.get("status")
                 == "diagnostic_only_fresh_segment_execution_unverified"
                 and receipt.get("input_scope") == comparison["input_scope"]
                 and receipt.get("case_id_claim") == case_id
                 and receipt.get("attempt_identity_verified") is False
                 and receipt.get("runtime_configuration_verified") is False
                 and receipt.get("cross_field_native_semantics_verified") is False
                 and receipt.get("normal_completion_verified") is False
                 and type(receipt.get("qualification_credit")) is int
                 and receipt["qualification_credit"] == 0,
                 f"matrix-v4 {role} RunPARTs parse receipt is malformed")
        source = receipt.get("source_runparts")
        _require(type(source) is dict and set(source) == {"path", "bytes", "sha256"}
                 and source.get("path") == "RunPARTs.csv"
                 and type(source.get("bytes")) is int
                 and source["bytes"] == len(raw)
                 and type(source.get("sha256")) is str
                 and SHA256.fullmatch(source["sha256"]) is not None
                 and source["sha256"] == raw_sha256,
                 f"raw RunPARTs bytes do not match matrix-v4 {role} source path")
        checks = receipt.get("checks")
        _require(type(checks) is dict
                 and checks == {
                     "all_26_fields_type_and_range_checked": True,
                     "single_segment_part0_time0_input_policy": True,
                 }, f"matrix-v4 {role} RunPARTs parser checks drifted")
        parsed_dt = receipt.get("maximum_recorded_part_dtmax_s")
        compared_dt = comparison.get(dt_field)
        _require(type(parsed_dt) in (int, float) and math.isfinite(parsed_dt)
                 and parsed_dt > 0.0
                 and type(compared_dt) in (int, float) and math.isfinite(compared_dt)
                 and compared_dt == parsed_dt,
                 f"matrix-v4 {role} recorded DtMax does not match its parse diagnostic")
        parse_summary = receipt.get("parse_summary")
        _require(type(parse_summary) is dict
                 and parse_summary.get("maximum_recorded_part_dtmax_s") == parsed_dt,
                 f"matrix-v4 {role} parse summary DtMax is inconsistent")
        pair_parse_receipts[case_id] = receipt
        pair_inputs[case_id] = {
            "bytes": source["bytes"],
            "sha256": source["sha256"],
            "maximum_recorded_part_dtmax_s": parsed_dt,
        }

    phase = comparison.get("wrapped_center_phase_difference_rad")
    _require(type(phase) in (int, float) and math.isfinite(phase)
             and 0.0 <= phase <= math.pi,
             "matrix-v4 wrapped center phase difference is invalid")
    return pair_inputs, pair_parse_receipts, case_result_bindings, float(phase)


def _diagnose_case(
    *, case_id: str, raw: bytes, algorithm: str, runtime_evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        diagnostic = case_adjudicator.diagnose_runtime_timestep_case_v1(
            case_id=case_id,
            runparts_raw=raw,
            effective_step_algorithm_claim=algorithm,
            runtime_completion_evidence=runtime_evidence,
        )
    except case_adjudicator.RuntimeTimestepAdjudicatorError as error:
        raise MetricMatrixV5Error(
            f"per-case diagnostic failed for frozen case {case_id}: {error}"
        ) from error

    _require(type(diagnostic) is dict
             and set(diagnostic) == pair_v1.CASE_DIAGNOSTIC_FIELDS
             and diagnostic.get("schema") == case_adjudicator.SCHEMA
             and diagnostic.get("status")
             == "untrusted_per_case_runtime_timestep_diagnostic_only"
             and diagnostic.get("case_id_claim") == case_id
             and diagnostic.get("effective_step_algorithm_claim") == algorithm
             and type(diagnostic.get("runtime_completion_diagnostic")) is dict
             and type(diagnostic.get("source_semantics")) is dict
             and type(diagnostic.get("runparts_observation")) is dict
             and set(diagnostic["runparts_observation"]) == CASE_OBSERVATION_FIELDS
             and diagnostic["runparts_observation"].get("schema")
             == case_adjudicator.runparts_v2.SCHEMA
             and diagnostic["runparts_observation"].get("input_scope")
             == case_adjudicator.runparts_v2.INPUT_SCOPE
             and type(diagnostic["runparts_observation"].get("data_row_count")) is int
             and diagnostic["runparts_observation"]["data_row_count"] >= 2
             and type(diagnostic["runparts_observation"].get("last_recorded_time_s"))
             in (int, float)
             and math.isfinite(diagnostic["runparts_observation"]["last_recorded_time_s"])
             and diagnostic["runparts_observation"]["last_recorded_time_s"] >= 0.0
             and diagnostic["runparts_observation"].get("footer_present") is True
             and diagnostic["runparts_observation"].get(
                 "all_26_fields_type_and_range_checked"
             ) is True
             and diagnostic["runparts_observation"].get("cross_field_native_semantics_verified") is False
             and diagnostic.get("effective_step_algorithm_verified") is False
             and diagnostic.get("runtime_configuration_verified") is False
             and diagnostic.get("runparts_attempt_identity_verified") is False
             and diagnostic.get("runparts_footer_proves_normal_completion") is False
             and diagnostic.get("normal_completion_verified") is False
             and diagnostic.get("runparts_completion_evidence_sufficient") is False
             and diagnostic.get("solver_timestep_adjudicated") is False
             and diagnostic.get("native_integrity_adjudicated") is False
             and diagnostic.get("T1_numerical") is False
             and diagnostic.get("readiness_pass") is False
             and type(diagnostic.get("qualification_credit")) is int
             and diagnostic["qualification_credit"] == 0,
             f"per-case diagnostic for {case_id} drifted from the non-authorizing schema")
    observation = diagnostic["runparts_observation"]
    _require(type(observation.get("bytes")) is int
             and observation["bytes"] == len(raw)
             and type(observation.get("sha256")) is str
             and SHA256.fullmatch(observation["sha256"]) is not None
             and observation["sha256"] == hashlib.sha256(raw).hexdigest()
             and type(observation.get("maximum_recorded_part_dtmax_s")) in (int, float)
             and math.isfinite(observation["maximum_recorded_part_dtmax_s"])
             and observation["maximum_recorded_part_dtmax_s"] > 0.0,
             f"per-case diagnostic for {case_id} is not bound to its raw bytes")
    completion = diagnostic["runtime_completion_diagnostic"]
    _require(set(completion) == pair_v1.COMPLETION_DIAGNOSTIC_FIELDS
             and completion.get("schema")
             == case_adjudicator.source_semantics_v1.RUNTIME_EVIDENCE_SCHEMA
             and completion.get("state") == "untrusted_runtime_evidence_diagnostic_only"
             and type(completion.get("conditions_satisfied_untrusted")) is bool
             and completion.get("evidence_authenticated") is False
             and completion.get("solver_timestep_adjudicated") is False
             and completion.get("normal_completion_verified") is False
             and completion.get("trusted_acceptance_verdict_issued") is False
             and type(completion.get("tolerance_s")) in (int, float)
             and math.isfinite(completion["tolerance_s"])
             and completion["tolerance_s"] >= 0.0,
             f"per-case runtime completion diagnostic schema/state/safety flags drifted for {case_id}")
    tolerance_fields = (
        "frozen_time_max_s", "absolute_tolerance_s", "relative_tolerance",
    )
    _require(all(type(runtime_evidence.get(field)) in (int, float)
                 for field in tolerance_fields),
             f"runtime tolerance inputs are malformed for {case_id}")
    try:
        frozen_time = float(runtime_evidence["frozen_time_max_s"])
        absolute_tolerance = float(runtime_evidence["absolute_tolerance_s"])
        relative_tolerance = float(runtime_evidence["relative_tolerance"])
        expected_tolerance = absolute_tolerance + relative_tolerance * abs(frozen_time)
    except (OverflowError, ValueError) as error:
        raise MetricMatrixV5Error(
            f"runtime tolerance inputs cannot be recomputed for {case_id}"
        ) from error
    _require(math.isfinite(frozen_time)
             and frozen_time > 0.0
             and math.isfinite(absolute_tolerance)
             and absolute_tolerance >= 0.0
             and math.isfinite(relative_tolerance)
             and relative_tolerance >= 0.0
             and math.isfinite(expected_tolerance)
             and completion["tolerance_s"] == expected_tolerance,
             f"per-case tolerance does not match the original runtime claims for {case_id}")
    source_semantics = diagnostic["source_semantics"]
    _require(set(source_semantics) == pair_v1.SOURCE_SEMANTICS_FIELDS
             and source_semantics.get("schema") == case_adjudicator.source_semantics_v1.SCHEMA
             and source_semantics.get("audited_backend") == "standard_cpu_single_only"
             and source_semantics.get("source_authenticated") is False
             and source_semantics.get("runtime_binary_identity_verified") is False
             and source_semantics.get("effective_integrator_verified") is False,
             f"per-case source-semantics schema or trust flags drifted for {case_id}")
    return diagnostic


def _row_horizon_claim_alignment(
    *, case_id: str, row: Mapping[str, Any], runtime_evidence: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    expected_end = row["observation_end_s"]
    tolerance = diagnostic["runtime_completion_diagnostic"]["tolerance_s"]
    claim_fields = (
        "frozen_time_max_s", "effective_time_max_s", "final_time_s",
    )
    claims: dict[str, float] = {}
    for field in claim_fields:
        value = runtime_evidence.get(field)
        _require(type(value) in (int, float) and math.isfinite(value),
                 f"runtime {field} claim is not finite for frozen case {case_id}")
        claims[field] = float(value)
    matches = {field: abs(value - expected_end) <= tolerance
               for field, value in claims.items()}
    _require(all(matches.values()),
             f"runtime horizon claims for {case_id} do not match frozen observation_end_s "
             "within the caller-claimed registered tolerance")
    return {
        "semantics": "caller_claim_consistency_only_not_authenticated_completion",
        "expected_frozen_observation_end_s": expected_end,
        "tolerance_s_from_untrusted_runtime_claims": tolerance,
        "frozen_time_max_s_claim": claims["frozen_time_max_s"],
        "effective_time_max_s_claim": claims["effective_time_max_s"],
        "final_time_s_claim": claims["final_time_s"],
        "frozen_time_max_matches_frozen_row_within_claimed_tolerance_untrusted": matches[
            "frozen_time_max_s"
        ],
        "effective_time_max_matches_frozen_row_within_claimed_tolerance_untrusted": matches[
            "effective_time_max_s"
        ],
        "final_time_matches_frozen_row_within_claimed_tolerance_untrusted": matches[
            "final_time_s"
        ],
    }


def _validate_pair_diagnostic(result: Any, case_diagnostics: Mapping[str, dict[str, Any]]) -> None:
    _require(type(result) is dict
             and set(result) == pair_v1.OUTPUT_FIELDS
             and result.get("schema") == pair_v1.SCHEMA
             and result.get("status") == "untrusted_frozen_timestep_pair_diagnostic_only"
             and set(result.get("case_diagnostics", {})) == {"baseline", "refined"}
             and type(result.get("qualification_boundaries")) is dict
             and result["qualification_boundaries"] == {
                 "input_evidence_authenticated": False,
                 "execution_attempt_identity_verified": False,
                 "runtime_configuration_verified": False,
                 "effective_step_algorithm_verified": False,
                 "native_integrity_adjudicated": False,
                 "normal_completion_verified": False,
                 "solver_timestep_adjudicated": False,
                 "T1_numerical": False,
                 "readiness_pass": False,
                 "qualification_credit": 0,
             }, "frozen-pair diagnostic contains unexpected qualification state")
    observations = result.get("untrusted_pair_observations")
    _require(type(observations) is dict
             and set(observations) == pair_v1.PAIR_OBSERVATION_FIELDS,
             "frozen-pair diagnostic observations do not match the v1 contract")
    for role, case_id in (("baseline", pair_v1.BASELINE_CASE_ID),
                          ("refined", pair_v1.REFINED_CASE_ID)):
        _require(result["case_diagnostics"][role] == case_diagnostics[case_id],
                 f"frozen-pair {role} diagnostic differs from the v5 raw-byte recomputation")


def evaluate_metric_matrix_v5(
    case_results: Mapping[str, Mapping[str, Any]],
    *,
    solver_timestep_sources: Mapping[str, Path | str],
    runparts_raw_by_case: Mapping[str, bytes],
    effective_step_algorithm_claims: Mapping[str, str],
    runtime_completion_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute a 15-case diagnostic composition from original raw inputs.

    The two matrix-v4 RunPARTs source paths must match the corresponding raw
    byte mappings exactly. Runtime horizon claims for every case must also
    align to that frozen row's ``observation_end_s`` within the tolerance
    recomputed from caller-supplied (and still untrusted) tolerance claims.
    No serialized v4 result or per-case diagnostic is an API input.
    """
    case_ids, rows_by_id = _frozen_rows()
    (results, sources, raw_by_case, algorithms,
     runtime_by_case) = _snapshot_inputs(
        case_results=case_results,
        solver_timestep_sources=solver_timestep_sources,
        runparts_raw_by_case=runparts_raw_by_case,
        effective_step_algorithm_claims=effective_step_algorithm_claims,
        runtime_completion_evidence=runtime_completion_evidence,
        case_ids=case_ids,
    )

    # Call v4 directly on its original inputs; never accept a caller's v4 output.
    try:
        matrix_result = matrix_v4.evaluate_metric_matrix_v4(
            results, solver_timestep_sources=sources,
        )
    except Exception as error:
        raise MetricMatrixV5Error(f"matrix-v4 direct recomputation failed: {error}") from error
    (matrix_pair_observations, _matrix_pair_receipts,
     matrix_case_result_bindings, phase_difference) = (
        _validate_matrix_v4_result(
            matrix_result, case_ids=case_ids, raw_by_case=raw_by_case,
        )
    )

    diagnostics: dict[str, dict[str, Any]] = {}
    horizon_alignment: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        diagnostic = _diagnose_case(
            case_id=case_id,
            raw=raw_by_case[case_id],
            algorithm=algorithms[case_id],
            runtime_evidence=runtime_by_case[case_id],
        )
        horizon_alignment[case_id] = _row_horizon_claim_alignment(
            case_id=case_id,
            row=rows_by_id[case_id],
            runtime_evidence=runtime_by_case[case_id],
            diagnostic=diagnostic,
        )
        diagnostics[case_id] = diagnostic

    # The two frozen inputs must agree in raw-byte identity and recomputed DtMax
    # across matrix-v4 parsing and the per-case diagnostic parser.
    for case_id in (pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID):
        v4_observation = matrix_pair_observations[case_id]
        per_case_observation = diagnostics[case_id]["runparts_observation"]
        _require(per_case_observation["bytes"] == v4_observation["bytes"]
                 and per_case_observation["sha256"] == v4_observation["sha256"]
                 and per_case_observation["maximum_recorded_part_dtmax_s"]
                 == v4_observation["maximum_recorded_part_dtmax_s"],
                 f"matrix-v4 and per-case RunPARTs observations differ for {case_id}")

    baseline_case = {
        "case_id": pair_v1.BASELINE_CASE_ID,
        "runparts_raw": raw_by_case[pair_v1.BASELINE_CASE_ID],
        "effective_step_algorithm_claim": algorithms[pair_v1.BASELINE_CASE_ID],
        "runtime_completion_evidence": runtime_by_case[pair_v1.BASELINE_CASE_ID],
    }
    refined_case = {
        "case_id": pair_v1.REFINED_CASE_ID,
        "runparts_raw": raw_by_case[pair_v1.REFINED_CASE_ID],
        "effective_step_algorithm_claim": algorithms[pair_v1.REFINED_CASE_ID],
        "runtime_completion_evidence": runtime_by_case[pair_v1.REFINED_CASE_ID],
    }
    try:
        pair_diagnostic = pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline_case,
            refined_case=refined_case,
            wrapped_phase_difference_rad=phase_difference,
        )
    except pair_v1.TimestepComparisonDiagnosticError as error:
        raise MetricMatrixV5Error(f"frozen-pair diagnostic failed: {error}") from error
    _validate_pair_diagnostic(pair_diagnostic, diagnostics)
    _require(pair_diagnostic["untrusted_pair_observations"][
        "wrapped_phase_difference_rad"
    ] == phase_difference,
        "frozen-pair diagnostic phase must be the matrix-v4 recomputed phase")

    comparison_projection = {
        "schema": matrix_v4.SCHEMA,
        "case_count": CASE_COUNT,
        "case_result_binding_case_ids": list(case_ids),
        "case_result_bindings": matrix_case_result_bindings,
        "runparts_binding_case_ids": [
            pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID,
        ],
        "pair_runparts_observations": matrix_pair_observations,
        "wrapped_center_phase_difference_rad_from_matrix_v4": phase_difference,
        "observation_semantics": (
            "matrix_v4_recomputed_frozen_pair_only_no_other_case_pairwise_dtmax_claim"
        ),
    }
    output = {
        "schema": SCHEMA,
        "status": "frozen_15_case_composed_diagnostics_only_no_qualification",
        "case_count": CASE_COUNT,
        "case_ids": list(case_ids),
        "case_failure_denominator_fixed": True,
        "matrix_v4_observations": comparison_projection,
        "case_diagnostics": diagnostics,
        "runtime_horizon_claim_alignment_untrusted": horizon_alignment,
        "frozen_pair_diagnostic": pair_diagnostic,
        "qualification_boundaries": {
            "input_evidence_authenticated": False,
            "execution_source_identity_verified": False,
            "runtime_configuration_verified": False,
            "effective_step_algorithm_verified": False,
            "native_integrity_evaluated": False,
            "native_integrity_adjudicated": False,
            "normal_completion_verified": False,
            "solver_completion_verified": False,
            "solver_timestep_adjudicated": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "qualification_credit": 0,
        },
    }
    _require(set(output) == OUTPUT_FIELDS,
             "internal matrix-v5 output fields drifted from the v5 contract")
    return output


__all__ = ["MetricMatrixV5Error", "SCHEMA", "evaluate_metric_matrix_v5"]
