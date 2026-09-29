#!/usr/bin/env python3
"""Fail-closed authority-envelope projection for residual seed17.

The current-manifest residual seed17 admission and runner already validate a
producer-issued receipt.  This adapter covers the narrower compatibility gap
where an older receipt has the bound identity but lacks the current
non-authorizing ``authority`` envelope.  It may project that envelope only
after the residual admission contract verifies a real external scheduler
document, Ed25519 trust anchor, nonce, namespace inode, plan, source and
resource bindings.

The projection is an in-memory diagnostic result.  It never rewrites a
receipt, creates a namespace, consumes a claim, launches a process, starts a
GPU/solver/worker/queue job, or changes Core state.  Missing producer-bound
fields are a projection gap, not an invitation to synthesize them.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_seed17_diagnostic_admission_v1 as admission


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f3.graph_residual.hidden16.seed17.current_manifest.authority_projection.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-residual-hidden16-seed17-authority-projection-v1"
DEFAULT_SOURCE_RECEIPT = Path(
    "/tmp/f3-graph_residual500-hidden16-currentmanifest-seed17-full835-"
    "authority-bound/.diagnostic-admission-receipt.json"
)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_RECEIPT_BYTES = admission.MAX_JSON_BYTES

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

# These are the contracts read by this adapter.  They are deliberately not
# edited here; the receipt's own source_sha256 remains authoritative for the
# producer-side source set.
CONTRACT_RELATIVE_PATHS = {
    "admission": Path("scripts/f3_graph_residual_hidden16_seed17_diagnostic_admission_v1.py"),
    "runner": Path("scripts/f3_graph_residual_hidden16_seed17_diagnostic_runner_v2.py"),
    "rollout_launcher": Path("scripts/f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1.py"),
    "terminal_identity": Path("scripts/f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py"),
    "terminal_runtime": Path("scripts/f3_graph_residual_hidden16_terminal_runtime_verifier_v1.py"),
}

AUTHORITY_FIELDS = (
    "schema",
    "receipt_authorizes_popen",
    "diagnostic_execute_allowed",
    "launch_allowed",
    "formal_promotion_allowed",
    "credit_promotion_allowed",
    "external_gate_required",
    "formal_state_touched",
    "credit",
)

REQUIRED_RECEIPT_FIELDS = (
    "schema",
    "status",
    "receipt_version",
    "report_id",
    "identity",
    "identity_sha256",
    "namespace_marker",
    "receipt_path",
    "consumption",
    "diagnostic_execute_only",
    "terminal_receipt_minting",
    "receipt_sha256",
)

# This is the exact identity shape emitted by the residual seed17 admission
# contract.  The list is intentionally explicit so a legacy receipt cannot
# be “completed” from caller-supplied claims.
REQUIRED_IDENTITY_FIELDS = (
    "model_kind",
    "hidden",
    "updates",
    "seed",
    "case_id",
    "split",
    "transitions",
    "frames",
    "run_id",
    "plan_sha256",
    "root",
    "manifest",
    "training_receipt",
    "checkpoint",
    "source_sha256",
    "resource_snapshot",
    "gpu",
    "gpu_identity_sha256",
    "command",
    "environment",
    "executable",
    "namespace_descriptor",
    "namespace",
    "nonce",
    "external_authority",
    "formal_state_touched",
)

REQUIRED_CONSUMPTION_FIELDS = (
    "one_shot",
    "state",
    "consumed",
    "state_file",
    "lock_path",
    "consumed_marker",
    "external_claim_path",
)


class ProjectionError(ValueError):
    """Malformed, drifting, or non-authorizing projection input."""


class ProjectionGap(ProjectionError):
    """A producer-issued reissue or external scheduler artifact is required."""

    def __init__(
        self,
        message: str,
        *,
        missing_fields: tuple[str, ...] = (),
        blockers: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields
        self.blockers = blockers


def _fail(message: str) -> None:
    raise ProjectionError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _absolute(value: Path | str, name: str) -> Path:
    try:
        return admission._absolute(value, name)
    except (admission.AdmissionError, TypeError, ValueError) as error:
        _fail(str(error))


def _receipt_core(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key not in {"receipt_sha256", "receipt_file"}}


def _receipt_digest(receipt: Mapping[str, Any], name: str = "receipt") -> str:
    digest = receipt.get("receipt_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        _fail(f"{name}.receipt_sha256 is missing or malformed")
    if digest != canonical_digest(_receipt_core(receipt)):
        _fail(f"{name}.receipt_sha256 does not bind the supplied receipt")
    return digest


def _validate_identity_digest(receipt: Mapping[str, Any], name: str = "receipt") -> None:
    identity = _mapping(receipt.get("identity"), f"{name}.identity")
    digest = receipt.get("identity_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        _fail(f"{name}.identity_sha256 is missing or malformed")
    if digest != canonical_digest(identity):
        _fail(f"{name}.identity_sha256 does not bind identity")


def _validate_zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        _exact(value, key, expected, name)


def _read_receipt(path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _absolute(path, "source admission receipt")
    try:
        raw, descriptor, payload = admission._read_file(
            candidate,
            "source admission receipt",
            max_bytes=MAX_RECEIPT_BYTES,
            parse_json=True,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: source admission receipt is unavailable or unreadable",
            blockers=(str(error), "producer-issued current-schema receipt is required"),
        ) from error
    if payload is None:
        raise ProjectionGap("projection-gap: source admission receipt is not a JSON object")
    receipt = dict(_mapping(payload, "source admission receipt"))
    _exact(receipt, "receipt_path", str(candidate), "source admission receipt")
    _receipt_digest(receipt, "source admission receipt")
    _validate_identity_digest(receipt, "source admission receipt")
    return receipt, {
        "path": str(candidate),
        "bytes": int(len(raw)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": int(descriptor.get("mode", 0)),
        "uid": int(descriptor.get("uid", -1)),
        "gid": int(descriptor.get("gid", -1)),
    }


def _missing_fields(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    for key in REQUIRED_RECEIPT_FIELDS:
        if key not in receipt:
            missing.append(key)
    if "authority" not in receipt:
        missing.append("authority")
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        missing.append("identity")
    else:
        for key in REQUIRED_IDENTITY_FIELDS:
            if key not in identity:
                missing.append(f"identity.{key}")
    consumption = receipt.get("consumption")
    if not isinstance(consumption, Mapping):
        missing.append("consumption")
    else:
        for key in REQUIRED_CONSUMPTION_FIELDS:
            if key not in consumption:
                missing.append(f"consumption.{key}")
    return tuple(dict.fromkeys(missing))


def _source_authority_path(receipt: Mapping[str, Any]) -> str | None:
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        return None
    external = identity.get("external_authority")
    if not isinstance(external, Mapping):
        return None
    path = external.get("path")
    return path if isinstance(path, str) else None


def describe_receipt_gap(receipt_path: Path | str) -> dict[str, Any]:
    """Return a bounded gap description without attempting projection."""

    try:
        receipt, file_info = _read_receipt(receipt_path)
    except ProjectionGap as error:
        return {
            "schema": f"{SCHEMA}.gap",
            "status": "blocked_projection_gap",
            "source_receipt": {"path": str(receipt_path), "observed": False},
            "source_receipt_schema": None,
            "source_receipt_sha256": None,
            "missing_fields": [],
            "projectable_missing_fields": ["authority"],
            "non_projectable_missing_fields": [],
            "external_authority_path_in_receipt": None,
            "blockers": list(error.blockers) or [str(error)],
            "source_observed": False,
        }

    missing = _missing_fields(receipt)
    projectable = tuple(key for key in missing if key == "authority")
    non_projectable = tuple(key for key in missing if key != "authority")
    authority_path = _source_authority_path(receipt)
    blockers: list[str] = []
    if projectable:
        blockers.append("top-level authority envelope is absent; only a real external scheduler may authorize projection")
    if non_projectable:
        blockers.append(
            "producer-bound receipt fields are missing and cannot be reconstructed locally: "
            + ", ".join(non_projectable)
        )
    if authority_path is None:
        blockers.append("identity.external_authority is absent; a caller claim or local GPU snapshot is not authority")
    else:
        blockers.append(f"identity.external_authority.path={authority_path}")
    scheduler_root_present = admission.EXTERNAL_SCHEDULER_ROOT.is_dir()
    if not scheduler_root_present:
        blockers.append("configured residual seed17 external scheduler root is absent")
    if non_projectable or authority_path is None or projectable:
        blockers.append("producer-issued current-schema receipt/reissue is required before runner retry")
    return {
        "schema": f"{SCHEMA}.gap",
        "status": "blocked_projection_gap" if (non_projectable or projectable or authority_path is None) else "projection_candidate",
        "source_receipt": file_info,
        "source_receipt_schema": receipt.get("schema"),
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "missing_fields": list(missing),
        "projectable_missing_fields": list(projectable),
        "non_projectable_missing_fields": list(non_projectable),
        "external_authority_path_in_receipt": authority_path,
        "configured_scheduler_root_present": scheduler_root_present,
        "blockers": list(dict.fromkeys(blockers)),
        "source_observed": True,
    }


def _authority_envelope() -> dict[str, Any]:
    return {
        "schema": admission.AUTHORITY_SCHEMA,
        "receipt_authorizes_popen": False,
        "diagnostic_execute_allowed": False,
        "launch_allowed": False,
        "formal_promotion_allowed": False,
        "credit_promotion_allowed": False,
        "external_gate_required": True,
        "formal_state_touched": False,
        "credit": 0,
    }


def _validate_existing_authority(value: Any) -> None:
    authority = dict(_mapping(value, "receipt.authority"))
    if set(authority) != set(AUTHORITY_FIELDS):
        _fail("receipt.authority has missing or unknown fields")
    _exact(authority, "schema", admission.AUTHORITY_SCHEMA, "receipt.authority")
    for key in (
        "receipt_authorizes_popen",
        "diagnostic_execute_allowed",
        "launch_allowed",
        "formal_promotion_allowed",
        "credit_promotion_allowed",
        "formal_state_touched",
    ):
        _exact(authority, key, False, "receipt.authority")
    _exact(authority, "external_gate_required", True, "receipt.authority")
    _exact(authority, "credit", 0, "receipt.authority")


def _validate_receipt_shell(receipt: Mapping[str, Any]) -> None:
    _exact(receipt, "schema", admission.SCHEMA, "receipt")
    _exact(receipt, "status", "issued", "receipt")
    _exact(receipt, "receipt_version", 1, "receipt")
    _exact(receipt, "report_id", admission.REPORT_ID, "receipt")
    _exact(receipt, "diagnostic_execute_only", True, "receipt")
    _exact(receipt, "terminal_receipt_minting", False, "receipt")
    _validate_zero_credit(receipt, "receipt")
    if "authority" in receipt:
        _validate_existing_authority(receipt["authority"])


def _validate_source_bindings(identity: Mapping[str, Any]) -> dict[str, str]:
    root = _absolute(identity["root"], "identity.root")
    records = _mapping(identity["source_sha256"], "identity.source_sha256")
    if set(records) != set(admission.SOURCE_RELATIVE_PATHS):
        _fail("identity.source_sha256 does not cover the residual admission source set")
    observed: dict[str, str] = {}
    for name, relative in admission.SOURCE_RELATIVE_PATHS.items():
        expected = _mapping(records[name], f"identity.source_sha256.{name}")
        current = admission._source_descriptor(root, relative, name)
        if current != expected:
            _fail(f"{name} source descriptor drifted from the receipt")
        observed[name] = str(current["sha256"])
    return observed


def project_authority(
    receipt: Mapping[str, Any],
    *,
    external_authority: Path | str | None,
    resource_admission: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project the non-authorizing envelope after real external verification."""

    original = copy.deepcopy(dict(_mapping(receipt, "source receipt")))
    _receipt_digest(original, "source receipt")
    _validate_identity_digest(original, "source receipt")
    _validate_receipt_shell(original)
    missing = _missing_fields(original)
    non_projectable = tuple(key for key in missing if key != "authority")
    if non_projectable:
        raise ProjectionGap(
            "projection-gap: producer-bound current-schema fields are missing",
            missing_fields=non_projectable,
            blockers=(
                "local projection cannot reconstruct " + ", ".join(non_projectable),
                "caller/local fields cannot substitute for external scheduler authority",
            ),
        )
    if external_authority is None:
        raise ProjectionGap(
            "projection-gap: external scheduler authority is required",
            missing_fields=("authority",),
            blockers=(
                "no real external scheduler document was supplied",
                "caller claim, local receipt field, or GPU probe cannot substitute for authority",
            ),
        )
    if resource_admission is None:
        raise ProjectionGap(
            "projection-gap: scheduler-owned resource snapshot is required",
            blockers=("no externally bound resource snapshot was supplied",),
        )

    identity = _mapping(original["identity"], "receipt.identity")
    authority_meta = _mapping(identity["external_authority"], "identity.external_authority")
    authority_path = _absolute(external_authority, "external scheduler authority")
    _exact(authority_meta, "path", str(authority_path), "identity.external_authority")
    try:
        resource_snapshot = admission._validate_resource(resource_admission)
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: resource snapshot is not scheduler-admissible",
            blockers=(str(error),),
        ) from error
    identity_resource = _mapping(identity["resource_snapshot"], "identity.resource_snapshot")
    if canonical_json(resource_snapshot) != canonical_json(dict(identity_resource)):
        raise ProjectionGap(
            "projection-gap: resource snapshot differs from receipt-bound resource",
            blockers=("caller-supplied resource claims cannot repair receipt drift",),
        )

    namespace = _absolute(identity["namespace"], "identity.namespace")
    namespace_descriptor = _mapping(identity["namespace_descriptor"], "identity.namespace_descriptor")
    try:
        plan = admission._build_reserved_plan(
            _absolute(identity["root"], "identity.root"),
            manifest=_mapping(identity["manifest"], "identity.manifest")["path"],
            training_receipt=_mapping(identity["training_receipt"], "identity.training_receipt")["path"],
            checkpoint=_mapping(identity["checkpoint"], "identity.checkpoint")["path"],
            nonce=str(identity["nonce"]),
            namespace=namespace,
            gpu_index=admission.GPU_INDEX,
            python_executable=_mapping(identity["executable"], "identity.executable")["path"],
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: nonce/namespace/current-manifest plan cannot be rebound",
            blockers=(str(error),),
        ) from error
    plan_sha256 = admission._plan_binding_digest(plan)
    _exact(identity, "plan_sha256", plan_sha256, "identity")
    try:
        external_meta = admission._validate_external_authority(
            authority_path,
            nonce=str(identity["nonce"]),
            namespace_descriptor=namespace_descriptor,
            plan_sha256=plan_sha256,
            resource_snapshot=resource_snapshot,
            expected_meta=authority_meta,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: external scheduler authority could not be verified",
            blockers=(str(error),),
        ) from error

    source_digests = _validate_source_bindings(identity)
    current_namespace = admission._existing_namespace_descriptor(namespace)
    for key in ("path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"):
        _exact(namespace_descriptor, key, current_namespace[key], "identity.namespace_descriptor")

    projected = copy.deepcopy(original)
    projected["authority"] = _authority_envelope()
    projected.pop("receipt_file", None)
    projected.pop("receipt_sha256", None)
    projected["receipt_sha256"] = canonical_digest(projected)
    bindings = {
        "nonce": str(identity["nonce"]),
        "namespace": str(namespace),
        "namespace_descriptor": dict(namespace_descriptor),
        "plan_sha256": plan_sha256,
        "source_sha256": source_digests,
        "source_binding_sha256": canonical_digest(source_digests),
        "resource_snapshot_sha256": canonical_digest(resource_snapshot),
        "external_authority_document_sha256": external_meta["document_sha256"],
        "external_authority_id": external_meta["authority_id"],
    }
    return {
        "schema": SCHEMA,
        "status": "authority_projection_ready",
        "source_receipt_sha256": str(original["receipt_sha256"]),
        "projected_receipt": projected,
        "authority": dict(projected["authority"]),
        "external_authority": external_meta,
        "bindings": bindings,
        "durable_receipt_written": False,
        "runner_consumable": False,
        "historical_receipt_rewritten": False,
        "popen_allowed": False,
        "formal_promotion_allowed": False,
        **ZERO_CREDIT,
    }


def _side_effects() -> dict[str, Any]:
    return {
        "popen_attempted": False,
        "wait_attempted": False,
        "processes_started": 0,
        "processes_stopped": 0,
        "processes_restarted": 0,
        "solver_started": False,
        "worker_started": False,
        "queue_submissions": 0,
        "gpu_execution_started": False,
        "registry_writes": 0,
        "ledger_writes": 0,
        "denominator_writes": 0,
        "gate_writes": 0,
        "completion_writes": 0,
        "plan_writes": 0,
        "historical_receipt_writes": 0,
    }


def _base_report() -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_projection_gap",
        "source_receipt": {"path": str(DEFAULT_SOURCE_RECEIPT), "observed": False},
        "source_observed": False,
        "source_receipt_schema": None,
        "source_receipt_sha256": None,
        "missing_fields": [],
        "projectable_missing_fields": ["authority"],
        "non_projectable_missing_fields": [],
        "external_authority": {
            "path_supplied": False,
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "configured_scheduler_root": str(admission.EXTERNAL_SCHEDULER_ROOT),
            "configured_scheduler_root_present": admission.EXTERNAL_SCHEDULER_ROOT.is_dir(),
        },
        "resource_binding": {
            "supplied": False,
            "verified": False,
            "caller_or_local_snapshot_accepted": False,
        },
        "projection_contract": {
            "authority_envelope_is_non_authorizing": True,
            "requires_external_signature": True,
            "requires_nonce_binding": True,
            "requires_namespace_inode_binding": True,
            "requires_source_descriptor_binding": True,
            "requires_resource_snapshot_binding": True,
            "caller_claim_can_substitute": False,
            "diagnostic_only": True,
            "formal": False,
            "credit": 0,
            "durable_receipt_written": False,
            "historical_receipt_rewritten": False,
            "runner_consumable": False,
            "popen_allowed": False,
        },
        "historical_receipt_rewritten": False,
        "durable_receipt_written": False,
        "runner_consumable": False,
        "popen_allowed": False,
        "blockers": [],
        "side_effects": _side_effects(),
        **ZERO_CREDIT,
    }


def build_report(
    receipt_path: Path | str = DEFAULT_SOURCE_RECEIPT,
    *,
    external_authority: Path | str | None = None,
    resource_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = _base_report()
    try:
        receipt, file_info = _read_receipt(receipt_path)
        gap = describe_receipt_gap(receipt_path)
        report.update(
            {
                "source_receipt": file_info,
                "source_observed": True,
                "source_receipt_schema": receipt.get("schema"),
                "source_receipt_sha256": receipt.get("receipt_sha256"),
                "missing_fields": gap["missing_fields"],
                "projectable_missing_fields": gap["projectable_missing_fields"],
                "non_projectable_missing_fields": gap["non_projectable_missing_fields"],
            }
        )
        result = project_authority(
            receipt,
            external_authority=external_authority,
            resource_admission=resource_admission,
        )
        report.update(
            {
                "status": "authority_projection_ready",
                "external_authority": {
                    "path_supplied": True,
                    "verified": True,
                    "real_external_document_required": True,
                    **result["external_authority"],
                },
                "resource_binding": {
                    "supplied": True,
                    "verified": True,
                    "caller_or_local_snapshot_accepted": False,
                },
                "projection": {
                    "bindings": result["bindings"],
                    "authority": result["authority"],
                },
            }
        )
        return report
    except ProjectionGap as error:
        gap = describe_receipt_gap(receipt_path)
        report.update(
            {
                "status": "blocked_projection_gap",
                "source_receipt": gap.get("source_receipt", report["source_receipt"]),
                "source_observed": bool(gap.get("source_observed", False)),
                "source_receipt_schema": gap.get("source_receipt_schema"),
                "source_receipt_sha256": gap.get("source_receipt_sha256"),
                "missing_fields": gap.get("missing_fields", list(error.missing_fields)),
                "projectable_missing_fields": gap.get("projectable_missing_fields", []),
                "non_projectable_missing_fields": gap.get(
                    "non_projectable_missing_fields", list(error.missing_fields)
                ),
                "blockers": list(dict.fromkeys([*gap.get("blockers", []), *error.blockers, str(error)])),
                "external_authority": {
                    **report["external_authority"],
                    "path_supplied": external_authority is not None,
                    "verified": False,
                },
                "resource_binding": {
                    **report["resource_binding"],
                    "supplied": resource_admission is not None,
                    "verified": False,
                },
            }
        )
        return report
    except (ProjectionError, admission.AdmissionError, OSError, TypeError, ValueError) as error:
        report["blockers"] = [str(error)]
        report["external_authority"] = {
            **report["external_authority"],
            "path_supplied": external_authority is not None,
            "verified": False,
        }
        report["resource_binding"] = {
            **report["resource_binding"],
            "supplied": resource_admission is not None,
            "verified": False,
        }
        return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        if report.get("status") not in {"blocked_projection_gap", "authority_projection_ready"}:
            _fail("report.status is not a projection status")
        _validate_zero_credit(report, "report")
        for key, expected in {
            "historical_receipt_rewritten": False,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "popen_allowed": False,
        }.items():
            _exact(report, key, expected, "report")
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in _side_effects().items():
            _exact(effects, key, expected, "report.side_effects")
        authority = _mapping(report.get("external_authority"), "report.external_authority")
        _exact(authority, "real_external_document_required", True, "report.external_authority")
        _exact(authority, "signature_algorithm", "ed25519", "report.external_authority")
        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        _exact(resource, "caller_or_local_snapshot_accepted", False, "report.resource_binding")
        contract = _mapping(report.get("projection_contract"), "report.projection_contract")
        for key, expected in {
            "authority_envelope_is_non_authorizing": True,
            "requires_external_signature": True,
            "requires_nonce_binding": True,
            "requires_namespace_inode_binding": True,
            "requires_source_descriptor_binding": True,
            "requires_resource_snapshot_binding": True,
            "caller_claim_can_substitute": False,
            "diagnostic_only": True,
            "formal": False,
            "credit": 0,
            "durable_receipt_written": False,
            "historical_receipt_rewritten": False,
            "runner_consumable": False,
            "popen_allowed": False,
        }.items():
            _exact(contract, key, expected, "report.projection_contract")
        blockers = report.get("blockers")
        if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
            _fail("report.blockers must be a string list")
        if report.get("status") == "blocked_projection_gap" and not blockers:
            _fail("blocked report must expose at least one blocker")
    except (ProjectionError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_residual hidden16 seed17 authority projection",
        "",
        f"- status: `{report.get('status')}`",
        f"- source observed: `{report.get('source_observed')}`",
        f"- source receipt: `{report.get('source_receipt', {}).get('path')}`",
        f"- external authority verified: `{report.get('external_authority', {}).get('verified')}`",
        f"- runner consumable: `{report.get('runner_consumable')}`",
        f"- Popen allowed: `{report.get('popen_allowed')}`",
        f"- credit: `{report.get('credit')}`",
        "",
        "## Boundary",
        "",
        "Only a real external scheduler document with Ed25519, nonce, namespace, source and resource bindings can pass this projection. The result is in-memory, diagnostic-only and zero-credit.",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("blockers", []) if isinstance(item, str))
    if not report.get("blockers"):
        lines.append("- none")
    lines.extend(
        [
            "",
            "No Popen, solver, worker, GPU or queue execution occurs; no historical receipt or Core state is written.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_SOURCE_RECEIPT)
    parser.add_argument("--external-authority", type=Path, default=None)
    parser.add_argument("--resource-admission", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def _load_resource(path: Path) -> Mapping[str, Any]:
    try:
        _raw, _descriptor, payload = admission._read_file(
            path, "resource admission JSON", max_bytes=256 * 1024, parse_json=True
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        _fail(str(error))
    return _mapping(payload, "resource admission JSON")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_report is not None:
        try:
            payload = json.loads(args.verify_report.read_text(encoding="utf-8"))
            errors = validate_report(_mapping(payload, "report"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"invalid projection report: {error}", file=sys.stderr)
            return 2
        for error in errors:
            print(error, file=sys.stderr)
        return 0 if not errors else 2

    resource = _load_resource(args.resource_admission) if args.resource_admission else None
    report = build_report(
        args.receipt,
        external_authority=args.external_authority,
        resource_admission=resource,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    return 0 if report["status"] == "authority_projection_ready" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
