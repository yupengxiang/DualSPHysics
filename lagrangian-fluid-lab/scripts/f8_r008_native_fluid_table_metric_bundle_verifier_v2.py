"""Close an R008 B→C→D chain and evaluate v2 table case metrics on one held FD.

This versioned additive orchestrator preserves the reviewed v1 verifier and
table schema. It performs no GenCase/native decoder/solver/worker/GPU/queue
execution, does not evaluate native integrity, and never grants T1 credit.
External authorization/review authenticity and loaded-module identity remain
caller/runtime trust inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as bundle_v1
from scripts import f8_r008_t1_metric_adapter_v2 as metric_adapter
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_fluid_table_metric_bundle_verifier.v2"
LAB = Path(__file__).resolve().parents[1]
METRIC_REVIEW_SCHEMA = "core.cfd.f8.r008_native_fluid_table_metric_implementation_review.v2"
METRIC_REVIEW_RECORD_ID = "f8-r008-native-fluid-table-metric-implementation-review-v2"
METRIC_CODE_PATHS = {
    "bundle_metric_verifier": "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
    "metric_adapter": "scripts/f8_r008_t1_metric_adapter_v2.py",
    "reviewed_v1_metric_helpers": "scripts/f8_r008_t1_metric_adapter_v1.py",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
AGENT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.ASCII)


class NativeFluidMetricBundleError(ValueError):
    """The metric result is not closed over reviewed code and a verified B/C/D chain."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidMetricBundleError(message)


def _validate_metric_review_document(receipt_bytes: bytes, expected_sha256: str) -> dict[str, Any]:
    _require(isinstance(receipt_bytes, bytes) and 0 < len(receipt_bytes) <= bundle.MAX_RECEIPT_BYTES,
             "caller-trusted Terra High metric review receipt is absent or oversized")
    _require(isinstance(expected_sha256, str) and bool(HEX64.fullmatch(expected_sha256))
             and hashlib.sha256(receipt_bytes).hexdigest() == expected_sha256,
             "caller-trusted metric review receipt SHA-256 mismatch")
    receipt = bundle._parse_json(receipt_bytes, "caller-trusted metric review receipt")
    _require(isinstance(receipt, dict)
             and set(receipt) == {
                 "schema", "record_id", "status", "reviewer", "reviewed_scope",
                 "review_boundary", "execution_authority", "findings", "evidence",
             }
             and receipt.get("schema") == METRIC_REVIEW_SCHEMA
             and receipt.get("record_id") == METRIC_REVIEW_RECORD_ID
             and receipt.get("status") == "static_metric_implementation_review_passed_no_execution_or_t1_credit",
             "caller-trusted metric review is not the registered v2 static PASS record")
    reviewer = receipt.get("reviewer")
    _require(isinstance(reviewer, dict)
             and reviewer.get("model") == "gpt-5.6-terra"
             and reviewer.get("reasoning_effort") == "high"
             and isinstance(reviewer.get("agent_id"), str)
             and bool(AGENT_ID.fullmatch(reviewer["agent_id"]))
             and reviewer.get("verdict") == "PASS"
             and reviewer.get("review_mode") == "read_only_static_implementation_review"
             and reviewer.get("execution_or_evidence_mutation") is False,
             "metric review receipt lacks a Terra High (high) read-only PASS")
    _require(receipt.get("reviewed_scope") == {
        "consumer_schema": table_v2.TABLE_SCHEMA,
        "B_C_D_chain_closed_on_held_table_fd": True,
        "v2_case_metric_gates": True,
        "15_case_matrix_adjudication": False,
        "native_integrity_or_T1_adjudication": False,
    }, "metric review scope differs from the implemented v2 held-FD case adapter")
    _require(receipt.get("review_boundary") == {
        "production_bundle_read": False,
        "solver_or_worker_invoked": False,
        "gpu_or_queue_invoked": False,
        "registry_or_ledger_mutated": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }, "metric review receipt expands the zero-execution boundary")
    _require(receipt.get("execution_authority") == {
        "solver": False, "worker": False, "gpu": False, "queue": False,
        "T1_numerical": False, "qualification_credit": 0,
    }, "metric review receipt expands execution or qualification authority")
    evidence = receipt.get("evidence")
    _require(isinstance(evidence, list), "metric review evidence must be a list")
    bindings: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if isinstance(item, dict) and item.get("path") in METRIC_CODE_PATHS.values():
            path = item["path"]
            _require(path not in bindings and set(item) == {"path", "bytes", "sha256"}
                     and isinstance(item.get("bytes"), int) and not isinstance(item.get("bytes"), bool)
                     and 0 < item["bytes"] <= bundle.MAX_RECEIPT_BYTES
                     and isinstance(item.get("sha256"), str) and bool(HEX64.fullmatch(item["sha256"])),
                     "metric review code-source binding is duplicate or malformed")
            bindings[path] = item
    _require(set(bindings) == set(METRIC_CODE_PATHS.values()),
             "metric review must bind the v2 verifier, adapter, and reviewed helper dependency")
    findings = receipt.get("findings")
    _require(isinstance(findings, list) and bool(findings)
             and all(isinstance(item, dict) and isinstance(item.get("topic"), str)
                     and item.get("verdict") == "PASS" for item in findings),
             "metric review receipt contains an absent or non-PASS finding")
    return {path: binding for path, binding in bindings.items()}


def _verify_metric_review_sources(bindings: Mapping[str, Mapping[str, Any]], lab_fd: int) -> None:
    for path in METRIC_CODE_PATHS.values():
        source = bundle._stable_read_beneath(lab_fd, path, bundle.MAX_RECEIPT_BYTES)
        binding = bindings[path]
        _require(len(source) == binding.get("bytes")
                 and hashlib.sha256(source).hexdigest() == binding.get("sha256"),
                 f"metric implementation source differs from Terra High review binding: {path}")


def _metric_fd_identity(st: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        st.st_dev, st.st_ino, st.st_mode, st.st_size,
        st.st_mtime_ns, st.st_ctime_ns, st.st_nlink,
    )


def _finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _validate_case_metrics(
    result: Any,
    *,
    case_id: str,
    frozen_row: Mapping[str, Any],
    table_binding: Mapping[str, Any],
) -> dict[str, Any]:
    fields = {
        "schema", "scope_id", "frozen_scope_receipt_sha256", "parameter_contract_sha256",
        "case_id", "status", "source_table_schema", "source_table_bytes", "source_table_sha256",
        "semantic_source_checks", "selected_time_s", "maximum_saved_output_dt_s", "profile_z_m",
        "plane_coefficients", "center_coefficients", "metrics", "metric_gates",
        "metric_gates_passed", "solver_max_dt_s", "solver_timestep_audit",
        "native_integrity_gates_evaluated", "full_t1_decision", "qualification_credit",
    }
    _require(isinstance(result, dict) and set(result) == fields,
             "metric adapter result does not match the exact reviewed v2 case-result schema")
    _require(result.get("schema") == metric_adapter.SCHEMA
             and result.get("scope_id") == metric_adapter.SCOPE_ID
             and result.get("case_id") == case_id
             and result.get("status") == "case_metric_gates_evaluated_native_integrity_pending"
             and result.get("source_table_schema") == table_v2.TABLE_SCHEMA
             and result.get("source_table_bytes") == table_binding.get("bytes")
             and result.get("source_table_sha256") == table_binding.get("sha256")
             and result.get("frozen_scope_receipt_sha256")
             == metric_adapter.metric_v1.FROZEN_INPUT_SHA256["scope"]
             and result.get("parameter_contract_sha256")
             == metric_adapter.metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
             "metric adapter result is bound to a different schema, case, source table, or frozen inputs")
    expected_semantics = {
        "B_C_D_chain_required_by_caller": True,
        "full_time_axis_matches": True,
        "fluid_id_projection_matches": True,
        "position_velocity_density_mass_recomputed": True,
        "all_valid": True,
        "density_used_as_metric_input": False,
    }
    _require(result.get("semantic_source_checks") == expected_semantics,
             "metric adapter omitted required verified table semantics or changed metric input scope")
    _require(result.get("solver_max_dt_s") is None and result.get("solver_timestep_audit") is None
             and result.get("native_integrity_gates_evaluated") is False
             and result.get("full_t1_decision") is False
             and result.get("qualification_credit") == 0,
             "metric adapter result overstates solver timestep, native-integrity, T1, or qualification")

    parameters = json.loads(metric_adapter.metric_v1.FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    geometry = parameters["geometry_and_fluid"]
    forcing = parameters["parameterization"]
    gates = parameters["error_gates"]
    half_height = float(geometry["half_height_m"])
    dp = float(frozen_row["dp_m"])
    intervals = round(2.0 * half_height / dp)
    expected_z = [-half_height + index * dp for index in range(intervals + 1)]
    profile_z = result.get("profile_z_m")
    _require(isinstance(profile_z, list) and len(profile_z) == len(expected_z)
             and all(_finite_number(value) for value in profile_z)
             and all(math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-12)
                     for actual, expected in zip(profile_z, expected_z)),
             "metric adapter profile grid differs from the frozen R008 H/dp row")

    selected_times = result.get("selected_time_s")
    sample_count = (int(frozen_row["observation_cycles"])
                    * int(frozen_row["native_output_samples_per_period"]) + 1)
    output_dt = float(frozen_row["period_s"]) / int(frozen_row["native_output_samples_per_period"])
    _require(isinstance(selected_times, list) and len(selected_times) == sample_count
             and all(_finite_number(value) for value in selected_times)
             and all(float(b) > float(a) for a, b in zip(selected_times, selected_times[1:]))
             and all(math.isclose(float(actual), float(frozen_row["observation_start_s"]) + index * output_dt,
                                  rel_tol=0.0, abs_tol=1e-12)
                     for index, actual in enumerate(selected_times))
             and math.isclose(float(selected_times[0]), float(frozen_row["observation_start_s"]),
                              rel_tol=0.0, abs_tol=1e-12)
             and math.isclose(float(selected_times[-1]), float(frozen_row["observation_end_s"]),
                              rel_tol=0.0, abs_tol=1e-12),
             "metric adapter selected times do not match the exact frozen closed observation window")
    _require(_finite_number(result.get("maximum_saved_output_dt_s"))
             and math.isclose(float(result["maximum_saved_output_dt_s"]), output_dt,
                              rel_tol=0.0, abs_tol=1e-12),
             "metric adapter saved-output timestep does not match the frozen native cadence")

    coefficient_fields = {
        "mean_m_s", "sine_coefficient_a_m_s", "cosine_coefficient_b_m_s",
        "amplitude_m_s", "phase_rad",
    }
    coefficients = result.get("plane_coefficients")
    _require(isinstance(coefficients, dict) and set(coefficients) == coefficient_fields
             and all(isinstance(values, list) and len(values) == len(expected_z)
                     and all(_finite_number(value) for value in values)
                     for values in coefficients.values()),
             "metric adapter plane coefficient payload is incomplete or malformed")
    center = result.get("center_coefficients")
    _require(isinstance(center, dict) and set(center) == coefficient_fields
             and all(_finite_number(value) for value in center.values()),
             "metric adapter centerline coefficient payload is incomplete or malformed")

    metrics = result.get("metrics")
    metric_fields = {
        "profile_amplitude_relative_error_max", "profile_phase_absolute_error_max_rad",
        "cycle_mean_fluxes_m3_s_per_m", "cycle_mean_flux_ratio",
        "transverse_velocity_rms_m_s", "transverse_velocity_rms_ratio", "u_ref_m_s",
    }
    _require(isinstance(metrics, dict) and set(metrics) == metric_fields
             and all(_finite_number(value) for key, value in metrics.items()
                     if key != "cycle_mean_fluxes_m3_s_per_m")
             and isinstance(metrics.get("cycle_mean_fluxes_m3_s_per_m"), list)
             and len(metrics["cycle_mean_fluxes_m3_s_per_m"]) == 3
             and all(_finite_number(value) for value in metrics["cycle_mean_fluxes_m3_s_per_m"]),
             "metric adapter gate metrics are incomplete or non-finite")
    u_ref = float(forcing["acceleration_amplitude_m_s2"]) / float(frozen_row["omega_rad_s"])
    _require(metrics["profile_amplitude_relative_error_max"] >= 0.0
             and metrics["profile_phase_absolute_error_max_rad"] >= 0.0
             and metrics["cycle_mean_flux_ratio"] >= 0.0
             and metrics["transverse_velocity_rms_m_s"] >= 0.0
             and metrics["transverse_velocity_rms_ratio"] >= 0.0
             and math.isclose(float(metrics["u_ref_m_s"]), u_ref, rel_tol=0.0, abs_tol=1e-15),
             "metric adapter gate metrics violate frozen units, signs, or Uref")
    flux_ratio = max(abs(float(value)) for value in metrics["cycle_mean_fluxes_m3_s_per_m"])
    flux_ratio /= u_ref * 2.0 * half_height
    _require(math.isclose(float(metrics["cycle_mean_flux_ratio"]), flux_ratio,
                          rel_tol=1e-12, abs_tol=1e-15)
             and math.isclose(float(metrics["transverse_velocity_rms_ratio"]),
                              float(metrics["transverse_velocity_rms_m_s"]) / u_ref,
                              rel_tol=1e-12, abs_tol=1e-15),
             "metric adapter normalized gate metrics do not recompute from frozen denominators")
    expected_gates = {
        "profile_amplitude": metrics["profile_amplitude_relative_error_max"]
        <= float(gates["profile_amplitude_relative_max"]),
        "profile_phase": metrics["profile_phase_absolute_error_max_rad"]
        <= float(gates["profile_phase_absolute_max_rad"]),
        "cycle_mean_flux": flux_ratio <= float(gates["cycle_mean_flux_over_uref_area_max"]),
        "transverse_velocity_rms": metrics["transverse_velocity_rms_ratio"]
        <= float(gates["transverse_velocity_rms_over_uref_max"]),
    }
    actual_gates = result.get("metric_gates")
    _require(isinstance(actual_gates, dict) and actual_gates == expected_gates
             and all(type(value) is bool for value in actual_gates.values())
             and type(result.get("metric_gates_passed")) is bool
             and result["metric_gates_passed"] is all(expected_gates.values()),
             "metric adapter case-gate booleans do not recompute from metric values and frozen limits")
    return result


def verify_native_fluid_table_chain_and_metrics(
    bundle_roots: Mapping[str, Path | str],
    *,
    trusted_authorization_bytes: Mapping[str, bytes],
    trusted_authorization_sha256: Mapping[str, str],
    expected_authorization_envelopes: Mapping[str, Mapping[str, Any]],
    trusted_table_review_receipt_bytes: bytes,
    trusted_table_review_receipt_sha256: str,
    trusted_metric_review_receipt_bytes: bytes,
    trusted_metric_review_receipt_sha256: str,
    trusted_code_review_receipt_bytes: bytes,
    trusted_runtime_assumption: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute B/C/D and evaluate case metrics while the D table FD stays held."""
    table_review_binding = bundle_v1._validate_table_review_document(
        trusted_table_review_receipt_bytes, trusted_table_review_receipt_sha256,
    )
    metric_review_bindings = _validate_metric_review_document(
        trusted_metric_review_receipt_bytes, trusted_metric_review_receipt_sha256,
    )
    _require(set(bundle_roots) == {"B", "C", "D"}
             and set(trusted_authorization_bytes) == {"B", "C", "D"}
             and set(trusted_authorization_sha256) == {"B", "C", "D"}
             and set(expected_authorization_envelopes) == {"B", "C", "D"},
             "v2 metric verification requires exactly B/C/D roots and trust bindings")
    stage_results = {
        stage: bundle.verify_stage_bundle(
            bundle_roots[stage], stage,
            trusted_authorization_bytes=trusted_authorization_bytes[stage],
            trusted_authorization_sha256=trusted_authorization_sha256[stage],
            expected_authorization_envelope=expected_authorization_envelopes[stage],
            trusted_code_review_receipt_bytes=(
                trusted_code_review_receipt_bytes if stage == "D" else None
            ),
            trusted_runtime_assumption=(trusted_runtime_assumption if stage == "D" else None),
        )
        for stage in ("B", "C", "D")
    }
    _require(all(stage_results[stage]["status"] == "passed" for stage in ("B", "C", "D")),
             "v2 metrics require passed B, C, and D stage receipts")
    case_ids = {stage_results[stage]["case_id"] for stage in ("B", "C", "D")}
    _require(len(case_ids) == 1, "B/C/D metric source case identities differ")
    case_id = next(iter(case_ids))
    frozen_row = bundle._frozen_qualification_row(case_id)
    metric_scope_row, _metric_parameters = metric_adapter._frozen_inputs(case_id)
    expected_axis = bundle.expected_time_axis_hex(frozen_row)
    c_manifest = stage_results["C"]["_manifest_document"]
    c_frames = c_manifest.get("frames")
    _require(isinstance(c_frames, list) and len(c_frames) == len(expected_axis),
             "C raw frame manifest does not equal the complete frozen time axis")

    stage_roots, stage_outputs = bundle_v1._open_stage_outputs(stage_results)
    lab_fd: int | None = None
    table_fd: int | None = None
    try:
        lab_fd, _lab_absolute = bundle._open_absolute_directory(bundle.LAB)
        bundle_v1._verify_table_review_source(table_review_binding, lab_fd)
        _verify_metric_review_sources(metric_review_bindings, lab_fd)
        b_receipt = stage_results["B"]["_receipt_document"]
        definition_binding = bundle_v1._check_frozen_source_binding(
            b_receipt, frozen_row, "definition", lab_fd,
        )
        control_binding = bundle_v1._check_frozen_source_binding(
            b_receipt, frozen_row, "control", lab_fd,
        )
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, bundle_v1.PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(hashlib.sha256(parameter_contract).hexdigest() == bundle_v1.PARAMETER_CONTRACT_SHA256,
                 "frozen F8 parameter contract differs from its pinned SHA-256")

        cohorts, mass_bits_hex = bundle._verify_b_materialization_semantics(
            stage_outputs["B"], stage_results["B"]["_output_file_manifest"], b_receipt,
        )
        fluid_ids = bundle_v1._fluid_ids_from_cohorts(cohorts)
        _require(isinstance(mass_bits_hex, str) and bool(bundle_v1.HEX16.fullmatch(mass_bits_hex)),
                 "B initial MassFluid is not exact canonical binary64 hexadecimal")
        initial_mass_bits = bytes.fromhex(mass_bits_hex)

        table_attributes = table_v2.expected_root_attributes(
            case_id=case_id,
            generated_xml_sha256=b_receipt["generated_xml_path"]["sha256"],
            definition_sha256=definition_binding["sha256"],
            materialization_receipt_sha256=stage_results["B"]["receipt_sha256"],
            raw_solver_manifest_sha256=stage_results["C"]["manifest_sha256"],
            scope_receipt_sha256=bundle.FROZEN_INPUT_SHA256["scope"],
            parameter_contract_sha256=bundle_v1.PARAMETER_CONTRACT_SHA256,
        )
        d_receipt = stage_results["D"]["_receipt_document"]
        table_binding = d_receipt["native_fluid_table_binding"]
        _require(table_binding.get("path") == "outputs/native-fluid-frame-table-v2.h5",
                 "D receipt does not bind the registered v2 native-fluid table path")
        table_fd = decoder.open_regular_beneath(
            stage_outputs["D"], table_binding["path"][len("outputs/"):],
        )
        table_open_identity = _metric_fd_identity(os.fstat(table_fd))
        _require(stat.S_ISREG(os.fstat(table_fd).st_mode) and table_open_identity[-1] == 1
                 and table_open_identity[3] == table_binding.get("bytes"),
                 "held D table FD is not the expected single-link regular file")

        def iter_source_frames():
            for ordinal, entry in enumerate(c_frames):
                _require(entry.get("ordinal") == ordinal
                         and entry.get("expected_time_s_ieee754_hex") == expected_axis[ordinal],
                         "C raw frame ordinal/time differs from the complete frozen axis")
                raw_fd = decoder.open_regular_beneath(stage_outputs["C"], entry["path"])
                try:
                    yield table_v2.read_native_source_frame_fd(
                        raw_fd, entry["sha256"], expected_bytes=entry["bytes"],
                    )
                finally:
                    os.close(raw_fd)

        source_frames = iter_source_frames()
        try:
            table_result = table_v2.verify_native_fluid_table_fd(
                table_fd,
                expected_table_bytes=table_binding["bytes"],
                expected_table_sha256=table_binding["sha256"],
                expected_attributes=table_attributes,
                expected_time_axis_hex=expected_axis,
                expected_fluid_ids=fluid_ids,
                expected_case_np=cohorts["case_np"],
                initial_massfluid_binary64_le=initial_mass_bits,
                source_frames=source_frames,
            )
        finally:
            source_frames.close()

        _require(_metric_fd_identity(os.fstat(table_fd)) == table_open_identity,
                 "D native-fluid table changed during semantic verification")
        case_metrics = _validate_case_metrics(
            metric_adapter.evaluate_case_metrics_fd(
                table_fd,
                table_verification=table_result,
                expected_table_bytes=table_binding["bytes"],
                expected_table_sha256=table_binding["sha256"],
            ),
            case_id=case_id,
            frozen_row=metric_scope_row,
            table_binding=table_binding,
        )

        chain = bundle.verify_provenance_chain(
            bundle_roots,
            trusted_authorization_bytes=trusted_authorization_bytes,
            trusted_authorization_sha256=trusted_authorization_sha256,
            expected_authorization_envelopes=expected_authorization_envelopes,
            trusted_code_review_receipt_bytes=trusted_code_review_receipt_bytes,
            trusted_runtime_assumption=trusted_runtime_assumption,
        )
        for stage in ("B", "C", "D"):
            _require(chain["receipt_sha256"][stage] == stage_results[stage]["receipt_sha256"]
                     and chain["manifest_sha256"][stage] == stage_results[stage]["manifest_sha256"],
                     f"{stage} receipt/manifest changed during v2 metric evaluation")
        _require(chain["all_stages_passed"] is True,
                 "revalidated B/C/D chain contains a non-passed stage")
        final_row = bundle._frozen_qualification_row(case_id)
        _require(final_row == frozen_row,
                 "frozen R008 Definition/control/scope row changed during metric evaluation")
        bundle_v1._check_frozen_source_binding(b_receipt, final_row, "definition", lab_fd)
        bundle_v1._check_frozen_source_binding(b_receipt, final_row, "control", lab_fd)
        parameter_contract = bundle._stable_read_beneath(
            lab_fd, bundle_v1.PARAMETER_CONTRACT_RELATIVE, bundle.MAX_RECEIPT_BYTES,
        )
        _require(hashlib.sha256(parameter_contract).hexdigest() == bundle_v1.PARAMETER_CONTRACT_SHA256,
                 "frozen F8 parameter contract changed during metric evaluation")
        bundle_v1._verify_table_review_source(table_review_binding, lab_fd)
        _verify_metric_review_sources(metric_review_bindings, lab_fd)
        held_after = os.fstat(table_fd)
        _require(_metric_fd_identity(held_after) == table_open_identity
                 and table_v2._sha256_fd(table_fd, table_binding["bytes"]) == table_binding["sha256"],
                 "held D native-fluid table changed before B/C/D metric-chain closure")
        named_table_fd = decoder.open_regular_beneath(
            stage_outputs["D"], table_binding["path"][len("outputs/"):],
        )
        try:
            named_table_stat = os.fstat(named_table_fd)
            _require(_metric_fd_identity(named_table_stat) == table_open_identity
                     and named_table_stat.st_nlink == 1
                     and table_v2._sha256_fd(named_table_fd, table_binding["bytes"])
                     == table_binding["sha256"],
                     "D table path no longer resolves without following links to the original held inode")
        finally:
            os.close(named_table_fd)
        return {
            "schema": SCHEMA,
            "case_id": case_id,
            "provenance_chain_references_closed": True,
            "definition_control_bindings_match_frozen_pack_and_source_bytes": True,
            "native_fluid_table": table_result,
            "case_metrics": case_metrics,
            "stage_statuses": chain["stage_statuses"],
            "receipt_sha256": chain["receipt_sha256"],
            "manifest_sha256": chain["manifest_sha256"],
            "native_table_review_receipt_sha256": trusted_table_review_receipt_sha256,
            "native_table_review_authenticity": "caller_supplied_trust_not_authenticated_here",
            "metric_review_receipt_sha256": trusted_metric_review_receipt_sha256,
            "metric_review_authenticity": "caller_supplied_trust_not_authenticated_here",
            "reviewed_metric_code_sources_match": True,
            "loaded_module_code_identity_verified": False,
            "authorization_authenticity": chain["authority_authenticity"],
            "runtime_environment_assumption": chain["runtime_environment_assumption"],
            "native_integrity_evaluated": False,
            "metrics_evaluated": True,
            "metric_gates_passed": case_metrics["metric_gates_passed"],
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }
    finally:
        if table_fd is not None:
            os.close(table_fd)
        if lab_fd is not None:
            os.close(lab_fd)
        for fd in (*stage_outputs.values(), *stage_roots.values()):
            os.close(fd)


__all__ = [
    "METRIC_CODE_PATHS", "METRIC_REVIEW_RECORD_ID", "METRIC_REVIEW_SCHEMA",
    "NativeFluidMetricBundleError", "SCHEMA", "verify_native_fluid_table_chain_and_metrics",
]
