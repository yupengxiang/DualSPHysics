#!/usr/bin/env python3
"""Reconcile F8 R008 metric-semantics closure with remaining execution gaps.

This audit reads only frozen design/evidence files and the retained zero-credit
CPU/native anchor. It does not launch native tools or grant execution authority.
"""
from __future__ import annotations

import hashlib
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts import f8_r008_t1_metric_adapter_v1 as adapter
from scripts import f8_r008_t1_metric_adapter_review_v1 as adapter_review


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
V3_RECEIPT = ROOT / "t1-execution-readiness-audit-v3/receipt.json"
V3_RECEIPT_SHA256 = "18d44fcfa1c4df26bf437e1438e0a220757fd9a5b7cc4e2b6cab2d710b2df4e0"
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_execution_readiness_audit_v4.py")
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v4/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v4"
GAP_RESOLUTION_MAP = {
    "production_z_plane_interval_semantics_not_frozen": {
        "proposal_fields": ["geometry_semantics.interval_rule", "geometry_semantics.plane_rule"],
        "adapter_symbols": ["_validate_frozen_case_geometry", "generated_xml_cohorts", "assign_plane_cohorts"],
        "test_symbols": ["test_build_rejects_caller_selected_geometry_instead_of_frozen_case_values",
                         "test_real_r008_preflight_inputs_bind_xml_definition_receipt_and_fluid_table",
                         "test_plane_cohorts_include_wall_endpoints_and_reject_off_plane_rows"],
    },
    "profile_sampling_definition_not_frozen": {
        "proposal_fields": ["observation_semantics.initial_particle_plane_assignment",
                            "observation_semantics.plane_velocity_profile"],
        "adapter_symbols": ["assign_plane_cohorts", "mass_weighted_velocity_profile", "evaluate_case_metrics"],
        "test_symbols": ["test_plane_cohorts_include_wall_endpoints_and_reject_off_plane_rows",
                         "test_metric_adapter_matches_analytic_solution_and_keeps_zero_credit"],
    },
    "reference_velocity_definition_not_frozen": {
        "proposal_fields": ["normalization.u_ref_m_s", "metric_definitions.continuum_profile.reference"],
        "adapter_symbols": ["evaluate_case_metrics"],
        "test_symbols": ["test_metric_adapter_matches_analytic_solution_and_keeps_zero_credit"],
    },
    "transverse_rms_definition_not_frozen": {
        "proposal_fields": ["metric_definitions.transverse_velocity_rms.formula",
                            "metric_definitions.transverse_velocity_rms.normalization",
                            "metric_definitions.transverse_velocity_rms.limit_from_frozen_scope",
                            "normalization.u_ref_m_s"],
        "adapter_symbols": ["transverse_velocity_rms", "evaluate_case_metrics"],
        "test_symbols": ["test_v4_transverse_rms_normalization_and_gate_are_exercised_with_nonzero_signal"],
    },
    "flux_normalization_definition_not_frozen": {
        "proposal_fields": ["metric_definitions.cycle_mean_flux", "observation_semantics.cycle_partition"],
        "adapter_symbols": ["three_cycle_mean_fluxes", "evaluate_case_metrics"],
        "test_symbols": ["test_three_cycle_integrals_use_exact_inclusive_shared_seams",
                         "test_metric_adapter_matches_analytic_solution_and_keeps_zero_credit"],
    },
    "cross_resolution_alignment_definition_not_frozen": {
        "proposal_fields": ["metric_definitions.cross_resolution_profile_alignment"],
        "adapter_symbols": ["compare_profile_coefficients", "evaluate_metric_matrix"],
        "test_symbols": ["test_cross_resolution_interpolates_coefficients_and_forbids_extrapolation",
                         "test_metric_matrix_rejects_caller_selected_cross_grid_geometry"],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": str(absolute.relative_to(LAB)),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _lookup(value: dict[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"adopted metric proposal is missing {dotted_path}")
        current = current[part]
    if current is None or current == "" or current == [] or current == {}:
        raise ValueError(f"adopted metric proposal has an empty field: {dotted_path}")
    return current


def _defined_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _verify_gap_resolution_map(v3: dict[str, Any], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = v3.get("blocking_gaps", [])
    codes = {item.get("code") for item in gaps}
    if codes != set(GAP_RESOLUTION_MAP) or len(gaps) != len(GAP_RESOLUTION_MAP):
        raise ValueError("R008 v3 does not contain the exact six audited semantics blockers")
    adapter_functions = _defined_functions(LAB / "scripts/f8_r008_t1_metric_adapter_v1.py")
    test_functions = (
        _defined_functions(LAB / "tests/test_f8_r008_t1_metric_adapter_v1.py")
        | _defined_functions(LAB / TEST)
    )
    resolutions = []
    for code, mapping in GAP_RESOLUTION_MAP.items():
        for field in mapping["proposal_fields"]:
            _lookup(proposal, field)
        if not set(mapping["adapter_symbols"]).issubset(adapter_functions):
            raise ValueError(f"adapter implementation symbols are missing for v3 gap {code}")
        if not set(mapping["test_symbols"]).issubset(test_functions):
            raise ValueError(f"adapter regression tests are missing for v3 gap {code}")
        resolutions.append({"v3_gap_code": code, **mapping, "resolved": True})
    return resolutions


def _verify_generic_receipt_fails_closed() -> None:
    receipt = {
        "schema": "core.cfd.f8.r008_gencase_materialization.v1",
        "scope_id": adapter.SCOPE_ID,
        "qualification_credit": 0,
        "case_id": adapter.ANCHOR_CASE_ID,
        "status": "gencase_materialization_passed_zero_credit",
    }
    with tempfile.TemporaryDirectory(prefix="f8-r008-readiness-v4-") as folder:
        path = Path(folder) / "self-asserted-receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        try:
            adapter.verify_gencase_receipt(path, adapter.ANCHOR_CASE_ID)
        except ValueError as error:
            if "untrusted per-case GenCase receipt schema" not in str(error):
                raise
        else:
            raise ValueError("unreviewed per-case GenCase receipt was not rejected")


def build_audit() -> dict[str, Any]:
    adapter._assert_frozen_inputs()
    v3_path = (LAB / V3_RECEIPT).resolve()
    if not v3_path.is_file() or sha256(v3_path) != V3_RECEIPT_SHA256:
        raise ValueError("the immutable R008 readiness audit v3 changed")

    review = _load(adapter.FROZEN_METRIC_REVIEW.relative_to(LAB))
    if not (
        review.get("status") == "independent_review_passed_static_semantics_frozen"
        and review.get("reviewer", {}).get("verdict") == "PASS"
        and review.get("disposition", {}).get("scope_inputs_or_thresholds_changed") is False
        and review.get("disposition", {}).get("solver_or_worker_authorized") is False
        and review.get("disposition", {}).get("gpu_or_queue_authorized") is False
    ):
        raise ValueError("the adopted R008 metric semantics review is not a zero-authority PASS")
    findings = review.get("findings", [])
    if not findings or any(item.get("verdict") != "PASS" for item in findings):
        raise ValueError("the adopted R008 metric semantics review contains a non-PASS finding")

    proposal = _load(adapter.FROZEN_METRIC_PROPOSAL.relative_to(LAB))
    parameters = _load(adapter.FROZEN_PARAMETER_CONTRACT.relative_to(LAB))
    transverse = proposal["metric_definitions"]["transverse_velocity_rms"]
    transverse_limit = float(parameters["error_gates"]["transverse_velocity_rms_over_uref_max"])
    if not (
        transverse["normalization"] == "divide by the case-specific Uref"
        and float(transverse["limit_from_frozen_scope"]) == transverse_limit
    ):
        raise ValueError("transverse RMS normalization or limit differs from the accepted frozen contracts")

    v3 = _load(V3_RECEIPT)
    gap_resolutions = _verify_gap_resolution_map(v3, proposal)
    adapter_review_receipt = adapter_review.verify_receipt(adapter_review.OUTPUT)
    if adapter_review_receipt.get("reviewer", {}).get("verdict") != "PASS":
        raise ValueError("the static metric adapter has no archived independent PASS review")
    _verify_generic_receipt_fails_closed()

    generation = adapter.verify_gencase_receipt(adapter.FROZEN_ANCHOR_PREFLIGHT, adapter.ANCHOR_CASE_ID)
    if (generation["fluid_particle_count"], generation["registered_nonfluid_particle_count"]) != (6656, 4096):
        raise ValueError("the pinned R008 anchor no longer binds the reviewed native identity cohorts")

    remaining = [
        {
            "code": "reviewed_per_case_materialization_verifier_missing",
            "severity": "high",
            "detail": (
                "The metric adapter intentionally trusts only the existing anchor preflight. "
                "No separately reviewed per-case GenCase/native-output receipt verifier or "
                "worker evidence contract is available, so unreviewed receipts fail closed."
            ),
        },
        {
            "code": "formal_15_case_t1_results_not_materialized",
            "severity": "high",
            "detail": (
                "No complete, provenance-verified 15-row solver result matrix has been evaluated. "
                "Metric-adapter tests and the zero-credit CPU/native anchor are not T1 results."
            ),
        },
    ]
    evidence = [
        binding(V3_RECEIPT, "immutable corrected R008 readiness audit v3"),
        binding(adapter.FROZEN_METRIC_PROPOSAL.relative_to(LAB), "adopted static metric-semantics contract v2"),
        binding(adapter.FROZEN_METRIC_REVIEW.relative_to(LAB), "independent Terra High PASS review of metric semantics"),
        binding(adapter_review.OUTPUT.relative_to(LAB), "independent Terra High PASS review archive for the static adapter"),
        binding(Path("scripts/f8_r008_t1_metric_adapter_v1.py"), "static metric adapter with fixed trust anchors"),
        binding(Path("tests/test_f8_r008_t1_metric_adapter_v1.py"), "metric adapter and fail-closed provenance tests"),
        binding(adapter.FROZEN_WINDOW_PARSER.relative_to(LAB), "pinned native observation-window parser dependency"),
        binding(adapter.FROZEN_WOMERSLEY_ORACLE.relative_to(LAB), "pinned Womersley reference-oracle dependency"),
        binding(adapter.FROZEN_ANCHOR_PREFLIGHT.relative_to(LAB), "pinned zero-credit R008 CPU/native anchor receipt"),
        binding(Path(generation["generated_xml"]["path"]).relative_to(LAB), "verified anchor generated XML and ID cohorts"),
        binding(Path(generation["definition"]["path"]).relative_to(LAB), "verified anchor frozen Definition"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-execution-readiness-audit-v4",
        "scope_id": adapter.SCOPE_ID,
        "status": "metric_semantics_closed_execution_integration_pending",
        "supersedes": {
            "path": V3_RECEIPT.as_posix(),
            "sha256": V3_RECEIPT_SHA256,
            "reason": "v3's six pre-execution metric/geometry gaps are closed by the adopted v2 semantics and reviewed static adapter; runtime provenance and formal T1 results remain absent",
        },
        "metric_semantics": {
            "reviewed": True,
            "missing_definitions": [],
            "profile_plane_rule": "z_j=-H+j*dp for j=0..round(2H/dp), including both endpoints; fixed ID cohorts and mass-weighted mean axial velocity",
            "reference_velocity": "acceleration_amplitude/omega for each frozen case row",
            "transverse_rms": f"sqrt(sum(m*(v_y^2+v_z^2))/sum(m)) over selected native samples, divided by case-specific Uref; pass when ratio <= {transverse_limit:g}",
            "cycle_flux": "trapezoidal per-unit-span z integral; each of three inclusive full periods has N+1 samples; normalize maximum absolute cycle mean by Uref*(2H)",
            "cross_resolution": "linearly interpolate fixed-frequency sine/cosine coefficients separately to the frozen interior production z grid; no extrapolation",
            "zero_credit_boundary": True,
            "v3_gap_resolutions": gap_resolutions,
        },
        "adapter_static_state": {
            "schema": adapter.SCHEMA,
            "frozen_input_hashes_checked": True,
            "independent_adapter_review_pass": adapter_review_receipt["reviewer"]["verdict"] == "PASS",
            "anchor_fluid_particles": generation["fluid_particle_count"],
            "anchor_registered_nonfluid_particles": generation["registered_nonfluid_particle_count"],
            "self_asserted_per_case_receipt_probe_rejected": True,
            "matrix_requires_exactly_15_recomputed_case_results": True,
            "native_integrity_gates_evaluated": False,
        },
        "blocking_gaps": remaining,
        "readiness_pass": False,
        "full_t1_decision": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_authority": {
            "solver": False,
            "gpu": False,
            "worker": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "evidence": evidence,
        "implementation": binding(SCRIPT, "R008 readiness audit v4 builder"),
        "test": binding(TEST, "R008 readiness audit v4 regression tests"),
    }


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_audit():
        raise ValueError("R008 execution-readiness audit v4 no longer matches its pinned evidence")
    return value


def write_audit(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v4: {target}")
    payload = json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    created = True
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if created:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable audit receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        print(json.dumps(build_audit(), indent=2, sort_keys=True))
