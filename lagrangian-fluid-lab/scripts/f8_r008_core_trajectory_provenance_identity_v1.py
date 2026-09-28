#!/usr/bin/env python3
"""Verify a bounded synthetic scheduler-to-Core trajectory identity chain.

This bridge is deliberately narrower than the existing worker/runtime handoff
and Core trajectory materializer.  It delegates worker/runtime authentication
to the existing synthetic handoff contract, then binds a scheduler dispatch
projection to a Core trajectory *manifest*.  It never opens the trajectory or
any HDF5/BI4/solver artifact, does not authenticate a production scheduler,
and cannot mint execution authority or qualification credit.

All three inputs are caller-provided canonical JSON bytes.  A successful
verification therefore means only that the synthetic identity/provenance
claims are internally consistent and ready for a future independently
authorized terminal-evidence step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f8_r008_trusted_worker_runtime_handoff_v1 as handoff_contract
from scripts.core_strict_json import strict_json_object


SCOPE_ID = handoff_contract.SCOPE_ID
SCHEMA = "core.cfd.f8.r008_core_trajectory_provenance_identity_contract.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_core_trajectory_provenance_identity_report.v1"
RECORD_ID = "f8-r008-core-trajectory-provenance-identity-v1"
REPORT_RECORD_ID = "f8-r008-core-trajectory-provenance-identity-report-v1"
STATUS = "synthetic_core_trajectory_provenance_identity_consistent_non_authorizing"
REPORT_STATUS = "synthetic_only_non_authorizing_core_trajectory_provenance_contract_design"
DISPATCH_SCHEMA = "core.cfd.f8.r008.synthetic_scheduler_dispatch.v1"
DISPATCH_RECORD_ID = "f8-r008-synthetic-scheduler-dispatch-v1"
DISPATCH_STATUS = "synthetic_scheduler_dispatch_bound_non_authorizing"
TRAJECTORY_MANIFEST_SCHEMA = "core.cfd.f8.r008.synthetic_core_trajectory_manifest.v1"
TRAJECTORY_MANIFEST_RECORD_ID = "f8-r008-synthetic-core-trajectory-manifest-v1"
TRAJECTORY_MANIFEST_STATUS = "synthetic_core_trajectory_manifest_bound_non_authorizing"
CORE_TRAJECTORY_SCHEMA = "core.f8.r008.diagnostic_trajectory.v1"
HANDOFF_OUTPUT_SCHEMA = "core.cfd.f8.r008.synthetic_worker_output_manifest.v1"
PROVENANCE_DOMAIN = "CORE-F8-R008-SCHEDULER-TO-CORE-TRAJECTORY-PROVENANCE-V1"

MAX_JSON_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 1_000_000
MAX_PARTICLES = 100_000_000
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
SYNTHETIC_ID_RE = re.compile(r"synthetic-[a-z0-9][a-z0-9._-]{0,62}\Z", re.ASCII)
SYNTHETIC_SCHEDULER_ID_RE = re.compile(
    r"synthetic-scheduler-[a-z0-9][a-z0-9._-]{0,47}\Z", re.ASCII,
)
RELATIVE_ARTIFACT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z", re.ASCII)

DISPATCH_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin",
    "scope_id", "dispatch",
})
DISPATCH_BINDING_FIELDS = frozenset({
    "dispatch_id", "attempt_id", "case_id", "nonce_hex", "handoff_sha256",
    "scheduler_principal_id", "scheduler_runtime_sha256",
    "scheduler_manifest_sha256", "worker_principal_id", "runtime_principal_id",
    "source_manifest_sha256", "runtime_manifest_sha256", "definition_sha256",
    "control_sha256", "initial_state_sha256", "configuration_sha256",
    "output_manifest_sha256", "output_schema", "core_trajectory_artifact_id",
    "core_trajectory_schema",
})
TRAJECTORY_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin",
    "scope_id", "trajectory", "provenance", "authorization",
})
TRAJECTORY_BINDING_FIELDS = frozenset({
    "artifact_id", "relative_path", "trajectory_schema", "case_id", "split",
    "bytes", "sha256", "frame_count", "particle_count", "source_table_sha256",
    "particle_zone_semantics", "fluid_only",
})
PROVENANCE_FIELDS = frozenset({
    "dispatch_sha256", "handoff_sha256", "attempt_id", "case_id", "nonce_hex",
    "scheduler_principal_id", "scheduler_runtime_sha256",
    "scheduler_manifest_sha256", "worker_principal_id", "runtime_principal_id",
    "source_manifest_sha256", "runtime_manifest_sha256", "definition_sha256",
    "control_sha256", "initial_state_sha256", "configuration_sha256",
    "output_manifest_sha256",
})
AUTHORIZATION_FIELDS = frozenset({
    "diagnostic_only", "capability_minted", "execution_authority",
    "formal_admission", "readiness_pass", "formal_eligible", "T1_numerical",
    "qualification_credit", "artifact_content_verified",
    "terminal_evidence_verified", "scheduler_identity_authenticated",
    "production_identity_authenticated", "worker_started", "solver_started",
    "gpu_started", "queue_started", "registry_mutation", "ledger_mutation",
    "gate_mutation", "denominator_mutation",
})

NON_AUTHORIZATION = {
    "diagnostic_only": True,
    "capability_minted": False,
    "execution_authority": False,
    "formal_admission": False,
    "readiness_pass": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "qualification_credit": 0,
    "artifact_content_verified": False,
    "terminal_evidence_verified": False,
    "scheduler_identity_authenticated": False,
    "production_identity_authenticated": False,
    "worker_started": False,
    "solver_started": False,
    "gpu_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "gate_mutation": 0,
    "denominator_mutation": 0,
}


class CoreTrajectoryProvenanceIdentityError(ValueError):
    """A synthetic scheduler-to-Core identity chain fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CoreTrajectoryProvenanceIdentityError(message)


def _canonical(value: Any, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise CoreTrajectoryProvenanceIdentityError(
            f"{label} is not canonical-JSON serializable"
        ) from error


def _parse(raw: bytes, *, label: str) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES,
             f"{label} bytes are outside the fixed bounded JSON limit")
    try:
        value = strict_json_object(raw, label=label, max_bytes=MAX_JSON_BYTES)
    except ValueError as error:
        raise CoreTrajectoryProvenanceIdentityError(str(error)) from error
    _require(_canonical(value, label) == raw, f"{label} bytes are not exact canonical JSON")
    return value


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256(value: Any, label: str) -> None:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             f"{label} is not lowercase SHA-256")


def _identifier(value: Any, label: str) -> None:
    _require(type(value) is str and SYNTHETIC_ID_RE.fullmatch(value) is not None,
             f"{label} is not a synthetic identifier")


def _scheduler_identifier(value: Any, label: str) -> None:
    _require(
        type(value) is str and SYNTHETIC_SCHEDULER_ID_RE.fullmatch(value) is not None,
        f"{label} is not a synthetic scheduler identifier",
    )


def _require_keys(value: Any, expected: frozenset[str], label: str) -> None:
    _require(type(value) is dict and set(value) == expected,
             f"{label} fields are not exact")


def _validate_nonce(value: Any, label: str) -> None:
    _require(type(value) is str and NONCE_RE.fullmatch(value) is not None,
             f"{label} is not lowercase 128-bit hex")


def _validate_authorization(value: Any, label: str) -> None:
    _require_keys(value, AUTHORIZATION_FIELDS, label)
    _require(value == NON_AUTHORIZATION, f"{label} attempts to mint authority")


def _validate_dispatch(value: dict[str, Any]) -> None:
    _require_keys(value, DISPATCH_FIELDS, "scheduler dispatch")
    _require(value["schema"] == DISPATCH_SCHEMA, "scheduler dispatch schema is unsupported")
    _require(value["record_id"] == DISPATCH_RECORD_ID,
             "scheduler dispatch record_id is unsupported")
    _require(value["status"] == DISPATCH_STATUS,
             "scheduler dispatch status is unsupported")
    _require(value["synthetic_only"] is True,
             "scheduler dispatch must be synthetic-only")
    _require(value["input_origin"] == "synthetic_fixture",
             "scheduler dispatch input origin must be synthetic_fixture")
    _require(value["scope_id"] == SCOPE_ID,
             "scheduler dispatch scope differs from F8 R008")

    dispatch = value["dispatch"]
    _require_keys(dispatch, DISPATCH_BINDING_FIELDS, "scheduler dispatch binding")
    for field in (
        "dispatch_id", "attempt_id", "case_id", "worker_principal_id",
        "runtime_principal_id", "core_trajectory_artifact_id",
    ):
        _identifier(dispatch[field], f"scheduler dispatch {field}")
    _scheduler_identifier(dispatch["scheduler_principal_id"],
                          "scheduler dispatch scheduler_principal_id")
    _validate_nonce(dispatch["nonce_hex"], "scheduler dispatch nonce_hex")
    for field in (
        "handoff_sha256", "scheduler_runtime_sha256", "scheduler_manifest_sha256",
        "source_manifest_sha256", "runtime_manifest_sha256", "definition_sha256",
        "control_sha256", "initial_state_sha256", "configuration_sha256",
        "output_manifest_sha256",
    ):
        _sha256(dispatch[field], f"scheduler dispatch {field}")
    _require(dispatch["output_schema"] == HANDOFF_OUTPUT_SCHEMA,
             "scheduler dispatch output schema is not the handoff schema")
    _require(dispatch["core_trajectory_schema"] == CORE_TRAJECTORY_SCHEMA,
             "scheduler dispatch Core trajectory schema is unsupported")


def _validate_trajectory_manifest(value: dict[str, Any]) -> None:
    _require_keys(value, TRAJECTORY_FIELDS, "Core trajectory manifest")
    _require(value["schema"] == TRAJECTORY_MANIFEST_SCHEMA,
             "Core trajectory manifest schema is unsupported")
    _require(value["record_id"] == TRAJECTORY_MANIFEST_RECORD_ID,
             "Core trajectory manifest record_id is unsupported")
    _require(value["status"] == TRAJECTORY_MANIFEST_STATUS,
             "Core trajectory manifest status is unsupported")
    _require(value["synthetic_only"] is True,
             "Core trajectory manifest must be synthetic-only")
    _require(value["input_origin"] == "synthetic_fixture",
             "Core trajectory manifest input origin must be synthetic_fixture")
    _require(value["scope_id"] == SCOPE_ID,
             "Core trajectory manifest scope differs from F8 R008")

    trajectory = value["trajectory"]
    _require_keys(trajectory, TRAJECTORY_BINDING_FIELDS, "Core trajectory binding")
    _identifier(trajectory["artifact_id"], "Core trajectory artifact_id")
    _require(type(trajectory["relative_path"]) is str
             and RELATIVE_ARTIFACT_RE.fullmatch(trajectory["relative_path"]) is not None
             and not trajectory["relative_path"].startswith(("/", "\\"))
             and "\\" not in trajectory["relative_path"]
             and all(part not in {"", ".", ".."}
                     for part in trajectory["relative_path"].split("/")),
             "Core trajectory relative_path is unsafe")
    _require(trajectory["trajectory_schema"] == CORE_TRAJECTORY_SCHEMA,
             "Core trajectory binding schema is unsupported")
    _identifier(trajectory["case_id"], "Core trajectory case_id")
    _require(trajectory["split"] == "qualification",
             "Core trajectory split must remain qualification")
    _require(type(trajectory["bytes"]) is int and not isinstance(trajectory["bytes"], bool)
             and 0 < trajectory["bytes"] <= MAX_ARTIFACT_BYTES,
             "Core trajectory byte count is outside the bounded artifact domain")
    _sha256(trajectory["sha256"], "Core trajectory artifact sha256")
    for field, upper in (("frame_count", MAX_FRAMES), ("particle_count", MAX_PARTICLES)):
        _require(type(trajectory[field]) is int and not isinstance(trajectory[field], bool)
                 and 0 < trajectory[field] <= upper,
                 f"Core trajectory {field} is outside the bounded integer domain")
    _sha256(trajectory["source_table_sha256"], "Core trajectory source_table_sha256")
    _require(trajectory["particle_zone_semantics"]
             == "all_native_fluid_particles_zone_zero",
             "Core trajectory particle-zone semantics are unsupported")
    _require(trajectory["fluid_only"] is True,
             "Core trajectory must declare fluid_only=true")

    provenance = value["provenance"]
    _require_keys(provenance, PROVENANCE_FIELDS, "Core trajectory provenance")
    for field in ("dispatch_sha256", "handoff_sha256", "scheduler_runtime_sha256",
                  "scheduler_manifest_sha256", "source_manifest_sha256",
                  "runtime_manifest_sha256", "definition_sha256", "control_sha256",
                  "initial_state_sha256", "configuration_sha256",
                  "output_manifest_sha256"):
        _sha256(provenance[field], f"Core trajectory provenance {field}")
    for field in ("attempt_id", "case_id", "worker_principal_id", "runtime_principal_id"):
        _identifier(provenance[field], f"Core trajectory provenance {field}")
    _scheduler_identifier(provenance["scheduler_principal_id"],
                          "Core trajectory provenance scheduler_principal_id")
    _validate_nonce(provenance["nonce_hex"], "Core trajectory provenance nonce_hex")
    _validate_authorization(value["authorization"], "Core trajectory authorization")


def _expected_dispatch_binding(handoff: Mapping[str, Any], handoff_raw: bytes,
                              dispatch: Mapping[str, Any]) -> dict[str, Any]:
    attempt = handoff["attempt"]
    subject = handoff["subject"]
    execution = handoff["execution"]
    inputs = handoff["inputs"]
    outputs = handoff["outputs"]
    return {
        "attempt_id": attempt["attempt_id"],
        "case_id": attempt["case_id"],
        "nonce_hex": attempt["nonce_hex"],
        "handoff_sha256": _sha256_bytes(handoff_raw),
        "worker_principal_id": subject["worker_principal_id"],
        "runtime_principal_id": subject["runtime_principal_id"],
        "source_manifest_sha256": execution["source_manifest_sha256"],
        "runtime_manifest_sha256": execution["runtime_manifest_sha256"],
        "definition_sha256": inputs["definition_sha256"],
        "control_sha256": inputs["control_sha256"],
        "initial_state_sha256": inputs["initial_state_sha256"],
        "configuration_sha256": inputs["configuration_sha256"],
        "output_manifest_sha256": outputs["output_manifest_sha256"],
        "output_schema": outputs["output_schema"],
    }


def _expected_provenance(dispatch: Mapping[str, Any], dispatch_raw: bytes,
                         handoff: Mapping[str, Any], handoff_raw: bytes) -> dict[str, Any]:
    expected = _expected_dispatch_binding(handoff, handoff_raw, dispatch)
    return {
        "dispatch_sha256": _sha256_bytes(dispatch_raw),
        "handoff_sha256": expected["handoff_sha256"],
        "attempt_id": expected["attempt_id"],
        "case_id": expected["case_id"],
        "nonce_hex": expected["nonce_hex"],
        "scheduler_principal_id": dispatch["scheduler_principal_id"],
        "scheduler_runtime_sha256": dispatch["scheduler_runtime_sha256"],
        "scheduler_manifest_sha256": dispatch["scheduler_manifest_sha256"],
        "worker_principal_id": expected["worker_principal_id"],
        "runtime_principal_id": expected["runtime_principal_id"],
        "source_manifest_sha256": expected["source_manifest_sha256"],
        "runtime_manifest_sha256": expected["runtime_manifest_sha256"],
        "definition_sha256": expected["definition_sha256"],
        "control_sha256": expected["control_sha256"],
        "initial_state_sha256": expected["initial_state_sha256"],
        "configuration_sha256": expected["configuration_sha256"],
        "output_manifest_sha256": expected["output_manifest_sha256"],
    }


def verify_synthetic_core_trajectory_provenance(
    *,
    handoff_raw: bytes,
    identity_bundle_raw: bytes,
    trust_root_public_key_bytes: bytes,
    scheduler_dispatch_raw: bytes,
    core_trajectory_manifest_raw: bytes,
) -> dict[str, Any]:
    """Verify one synthetic scheduler-to-Core manifest identity chain.

    The worker/runtime handoff is cryptographically verified by the existing
    contract.  The scheduler and Core records are then bound to that exact
    handoff and to each other by canonical-byte digests.  Scheduler identity
    and trajectory artifact contents intentionally remain unauthenticated.
    """
    try:
        handoff_result = handoff_contract.verify_synthetic_worker_runtime_handoff(
            handoff_raw,
            identity_bundle_raw=identity_bundle_raw,
            trust_root_public_key_bytes=trust_root_public_key_bytes,
        )
    except handoff_contract.TrustedWorkerRuntimeHandoffError as error:
        raise CoreTrajectoryProvenanceIdentityError(
            f"trusted worker/runtime handoff verification failed: {error}"
        ) from error

    handoff = _parse(handoff_raw, label="F8 R008 synthetic worker/runtime handoff")
    dispatch = _parse(scheduler_dispatch_raw, label="F8 R008 synthetic scheduler dispatch")
    trajectory = _parse(
        core_trajectory_manifest_raw,
        label="F8 R008 synthetic Core trajectory manifest",
    )
    _validate_dispatch(dispatch)
    _validate_trajectory_manifest(trajectory)

    dispatch_binding = dispatch["dispatch"]
    expected_dispatch = _expected_dispatch_binding(handoff, handoff_raw, dispatch_binding)
    for field, expected in expected_dispatch.items():
        _require(dispatch_binding[field] == expected,
                 f"scheduler dispatch {field} does not bind to the verified handoff")

    trajectory_binding = trajectory["trajectory"]
    _require(trajectory_binding["artifact_id"]
             == dispatch_binding["core_trajectory_artifact_id"],
             "Core trajectory artifact identity differs from scheduler dispatch")
    _require(trajectory_binding["trajectory_schema"]
             == dispatch_binding["core_trajectory_schema"],
             "Core trajectory schema differs from scheduler dispatch")
    _require(trajectory_binding["case_id"] == dispatch_binding["case_id"],
             "Core trajectory case differs from scheduler dispatch")

    expected_provenance = _expected_provenance(
        dispatch_binding, scheduler_dispatch_raw, handoff, handoff_raw,
    )
    for field, expected in expected_provenance.items():
        _require(trajectory["provenance"][field] == expected,
                 f"Core trajectory provenance {field} does not bind to the chain")

    chain_payload = {
        "domain": PROVENANCE_DOMAIN,
        "scope_id": SCOPE_ID,
        "handoff_sha256": _sha256_bytes(handoff_raw),
        "dispatch_sha256": _sha256_bytes(scheduler_dispatch_raw),
        "trajectory_manifest_sha256": _sha256_bytes(core_trajectory_manifest_raw),
        "attempt_id": dispatch_binding["attempt_id"],
        "case_id": dispatch_binding["case_id"],
        "nonce_hex": dispatch_binding["nonce_hex"],
        "worker_principal_id": dispatch_binding["worker_principal_id"],
        "runtime_principal_id": dispatch_binding["runtime_principal_id"],
        "scheduler_principal_id": dispatch_binding["scheduler_principal_id"],
        "artifact_id": trajectory_binding["artifact_id"],
    }
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS,
        "scope_id": SCOPE_ID,
        "input_origin": "synthetic_fixture",
        "handoff_binding": {
            "raw_sha256": _sha256_bytes(handoff_raw),
            "identity_chain_consistent": handoff_result["identity_chain_consistent"],
            "active_key_handoff_signature_valid": handoff_result["active_key_handoff_signature_valid"],
            "attempt_scope_bound": handoff_result["attempt_scope_bound"],
            "worker_runtime_identity_verified": True,
        },
        "scheduler_binding": {
            "raw_sha256": _sha256_bytes(scheduler_dispatch_raw),
            "dispatch_to_handoff_consistent": True,
            "scheduler_identity_authenticated": False,
        },
        "core_trajectory_binding": {
            "manifest_raw_sha256": _sha256_bytes(core_trajectory_manifest_raw),
            "manifest_to_dispatch_consistent": True,
            "artifact_id": trajectory_binding["artifact_id"],
            "artifact_bytes_declared": trajectory_binding["bytes"],
            "artifact_content_verified": False,
            "terminal_evidence_verified": False,
        },
        "chain_binding_sha256": hashlib.sha256(_canonical(
            chain_payload, "scheduler-to-Core provenance binding",
        )).hexdigest(),
        "provenance_identity_verified": True,
        "production_identity_authenticated": False,
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "qualification_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "denominator_mutation": 0,
    }


def build_report() -> dict[str, Any]:
    """Return the deterministic synthetic-only contract report."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": REPORT_STATUS,
        "contract_schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "input_boundary": {
            "mode": "bounded_in_memory_canonical_json",
            "synthetic_only": True,
            "input_origin": "synthetic_fixture",
            "max_json_bytes": MAX_JSON_BYTES,
            "production_paths_read": False,
            "trajectory_hdf5_bi4_solver_frames_read": False,
        },
        "verified_chain": [
            "existing_signed_worker_runtime_handoff_is_verified_first",
            "scheduler_dispatch_exactly_binds_handoff_digest_and_attempt_identity",
            "scheduler_dispatch_binds_source_runtime_input_and_output_pins",
            "Core_trajectory_manifest_exactly_binds_dispatch_and_case_identity",
            "canonical_chain_digest_covers_handoff_dispatch_and_Core_manifest",
        ],
        "not_verified": [
            "production_scheduler_identity_or_runtime_authenticity",
            "trajectory_artifact_presence_or_content",
            "terminal_supervisor_final_fput_or_fanotify_evidence",
            "target_kernel_source_build_runtime_identity",
            "native_integrity_15_by_8_cells",
            "15_case_T1_adjudication",
        ],
        "non_authorizing_boundary": NON_AUTHORIZATION,
        "integration_boundary": {
            "trusted_worker_runtime_handoff": "delegated and not replaced",
            "core_trajectory_materializer": "not invoked; no artifact is opened",
            "scheduler_or_worker": "not started, stopped, or queued",
            "ledger_registry_and_completion": "not read for mutation and never written",
            "readiness_and_T1": "not promoted or credited",
        },
        "blocking_gaps": [
            {
                "code": "scheduler_identity_not_authenticated",
                "detail": "The dispatch projection is synthetic and digest-bound only; a production scheduler signature/runtime identity is absent.",
            },
            {
                "code": "core_trajectory_artifact_content_unverified",
                "detail": "Only a bounded manifest is checked. The referenced trajectory bytes are deliberately not opened or read.",
            },
            {
                "code": "terminal_execution_evidence_missing",
                "detail": "No worker terminal receipt, supervisor witness, final-fput witness, or native-integrity cell is consumed.",
            },
            {
                "code": "target_kernel_source_build_runtime_identity_unproven",
                "detail": "This bridge does not resolve or promote the separate target-kernel/source/build/runtime readiness blockers.",
            },
        ],
        "prohibited_operations": [
            "production_trajectory_hdf5_bi4_solver_frame_read",
            "native_or_solver",
            "worker_gpu_or_queue",
            "scheduler_start_stop_or_restart",
            "production_identity_authentication_claim",
            "registry_ledger_completion_gate_mutation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-report", action="store_true",
                        help="print the deterministic synthetic-only contract report")
    args = parser.parse_args()
    if args.print_report:
        print(json.dumps(build_report(), indent=2, sort_keys=True, allow_nan=False))
    else:
        print(json.dumps({
            "schema": SCHEMA,
            "status": STATUS,
            "synthetic_only": True,
            "diagnostic_only": True,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CORE_TRAJECTORY_SCHEMA", "CoreTrajectoryProvenanceIdentityError",
    "DISPATCH_RECORD_ID", "DISPATCH_SCHEMA", "DISPATCH_STATUS", "MAX_JSON_BYTES",
    "HANDOFF_OUTPUT_SCHEMA", "NON_AUTHORIZATION", "REPORT_RECORD_ID", "REPORT_SCHEMA", "RECORD_ID",
    "SCHEMA", "SCOPE_ID", "STATUS", "TRAJECTORY_MANIFEST_RECORD_ID",
    "TRAJECTORY_MANIFEST_SCHEMA", "TRAJECTORY_MANIFEST_STATUS", "build_report",
    "verify_synthetic_core_trajectory_provenance",
]
