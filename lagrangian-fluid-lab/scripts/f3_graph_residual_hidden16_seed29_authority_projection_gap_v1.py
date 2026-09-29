#!/usr/bin/env python3
"""Fail-closed authority projection gap boundary for residual seed29.

The residual seed29 admission contract already binds a producer-issued
external scheduler document through ``identity.external_authority``.  This
adapter records the narrower compatibility gap where a caller needs a
non-authorizing authority envelope for an in-memory diagnostic projection.
It can only produce that envelope after the existing receipt, a real
Ed25519-signed scheduler document, the one-shot namespace, the plan, the
source descriptors and the scheduler-owned resource snapshot all agree.

The projection is never a seed29 admission receipt.  It is not written back,
not consumed by the runner, and never authorizes Popen, a solver, a worker,
GPU/queue work, formal promotion, or Core state changes.  Missing producer
evidence is reported as a bounded gap rather than repaired from local claims.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
from pathlib import Path
import os
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_seed29_diagnostic_admission_v1 as admission


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 29
MODEL_KIND = "graph_residual"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
SPLIT = "test"

SCHEMA = "core.f3.graph_residual.hidden16.seed29.authority_projection_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-residual-hidden16-seed29-authority-projection-gap-v1"
DEFAULT_SOURCE_RECEIPT = Path(
    "/tmp/f3-graph-residual500-hidden16-currentmanifest-seed29-full835-"
    "authority-bound/.diagnostic-admission-receipt.json"
)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_RECEIPT_BYTES = admission.MAX_JSON_BYTES

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

# These are the current seed29 receipt fields.  ``authority`` is intentionally
# not one of them: the adapter-only envelope is never accepted by the
# seed29 admission validator or persisted as a source receipt.
REQUIRED_RECEIPT_FIELDS = (
    "schema",
    "report_id",
    "status",
    "receipt_path",
    "namespace",
    "namespace_nonce",
    "identity",
    "identity_sha256",
    "consumption",
    "diagnostic_execute_only",
    "terminal_receipt_minting",
    "receipt_sha256",
)
REQUIRED_IDENTITY_FIELDS = (
    "root",
    "seed",
    "run_id",
    "model_kind",
    "hidden",
    "updates",
    "case_id",
    "split",
    "transitions",
    "frames",
    "manifest",
    "training_receipt",
    "checkpoint",
    "source_files",
    "executable",
    "command",
    "outputs",
    "plan_sha256",
    "environment",
    "resource_admission",
    "gpu",
    "gpu_identity_sha256",
    "namespace",
    "namespace_descriptor",
    "nonce",
    "external_authority",
    "formal_state_touched",
)
REQUIRED_CONSUMPTION_FIELDS = ("one_shot", "lock_path", "consumed_marker", "consumed")
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


class ProjectionError(ValueError):
    """Malformed or non-authorizing projection input."""


class ProjectionGap(ProjectionError):
    """A producer-issued receipt or external scheduler artifact is absent."""

    def __init__(
        self,
        message: str,
        *,
        missing_fields: Sequence[str] = (),
        blockers: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.missing_fields = tuple(str(item) for item in missing_fields)
        self.blockers = tuple(str(item) for item in blockers)


def _fail(message: str) -> None:
    raise ProjectionError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _absolute(value: Path | str, name: str) -> Path:
    try:
        return admission._absolute(value, name)
    except (admission.AdmissionError, TypeError, ValueError) as error:
        _fail(str(error))


def _receipt_core(receipt: Mapping[str, Any]) -> dict[str, Any]:
    # Admission descriptors are written after the digest is sealed and are
    # explicitly outside the seed29 receipt digest.
    return {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_sha256", "receipt_descriptor", "namespace_marker_descriptor"}
    }


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
        raw, descriptor, payload = admission._read_bound(
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
        **{key: int(value) for key, value in descriptor.items() if key in {"mode", "uid", "gid", "nlink"}},
    }


def _missing_fields(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    for key in REQUIRED_RECEIPT_FIELDS:
        if key not in receipt:
            missing.append(key)
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        missing.append("identity")
    else:
        missing.extend(
            f"identity.{key}" for key in REQUIRED_IDENTITY_FIELDS if key not in identity
        )
    consumption = receipt.get("consumption")
    if not isinstance(consumption, Mapping):
        missing.append("consumption")
    else:
        missing.extend(
            f"consumption.{key}"
            for key in REQUIRED_CONSUMPTION_FIELDS
            if key not in consumption
        )
    return tuple(dict.fromkeys(missing))


def _external_authority_path(receipt: Mapping[str, Any]) -> str | None:
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        return None
    authority = identity.get("external_authority")
    if not isinstance(authority, Mapping):
        return None
    path = authority.get("path")
    return path if isinstance(path, str) else None


def _path_state(path: Path | str) -> dict[str, Any]:
    candidate = Path(path)
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        return {"path": str(candidate), "present": False, "kind": "absent"}
    except OSError as error:
        return {"path": str(candidate), "present": False, "kind": "uninspectable", "error": str(error)}
    if os.path.islink(candidate):
        kind = "symlink"
    elif os.path.isdir(candidate):
        kind = "directory"
    elif os.path.isfile(candidate):
        kind = "regular_file"
    else:
        kind = "other"
    return {
        "path": str(candidate),
        "present": True,
        "kind": kind,
        "mode": int(info.st_mode & 0o7777),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def describe_receipt_gap(receipt_path: Path | str) -> dict[str, Any]:
    """Inspect only a bounded receipt and describe the projection boundary."""

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
    authority_path = _external_authority_path(receipt)
    blockers: list[str] = []
    if missing:
        blockers.append(
            "producer-bound receipt fields are missing and cannot be reconstructed locally: "
            + ", ".join(missing)
        )
    if authority_path is None:
        blockers.append(
            "identity.external_authority is absent; a caller claim or local GPU snapshot is not authority"
        )
    if "authority" not in receipt:
        blockers.append(
            "adapter-only non-authorizing authority envelope is not present; it cannot be persisted into the source receipt"
        )
    root_state = _path_state(admission.EXTERNAL_SCHEDULER_ROOT)
    if root_state["kind"] != "directory":
        blockers.append("configured residual seed29 external scheduler root is absent")
    status = "projection_candidate" if not missing and authority_path is not None else "blocked_projection_gap"
    return {
        "schema": f"{SCHEMA}.gap",
        "status": status,
        "source_receipt": file_info,
        "source_receipt_schema": receipt.get("schema"),
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "missing_fields": list(missing),
        "projectable_missing_fields": [] if "authority" in receipt else ["authority"],
        "non_projectable_missing_fields": list(missing),
        "external_authority_path_in_receipt": authority_path,
        "configured_scheduler_root_present": root_state["kind"] == "directory",
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
    authority = dict(_mapping(value, "source receipt.authority"))
    if set(authority) != set(AUTHORITY_FIELDS):
        _fail("source receipt.authority has missing or unknown fields")
    _exact(authority, "schema", admission.AUTHORITY_SCHEMA, "source receipt.authority")
    for key in AUTHORITY_FIELDS[1:-2]:
        if key == "external_gate_required":
            _exact(authority, key, True, "source receipt.authority")
        else:
            _exact(authority, key, False, "source receipt.authority")
    _exact(authority, "formal_state_touched", False, "source receipt.authority")
    _exact(authority, "credit", 0, "source receipt.authority")


def _validate_receipt_shell(receipt: Mapping[str, Any]) -> None:
    # This invokes only the admission's bounded structural/digest checks.  It
    # deliberately does not call _validate_external_binding, which could open
    # a producer checkpoint or HDF5/trajectory artifact.
    try:
        admission._validate_shape(receipt, check_files=False)
    except (admission.AdmissionError, TypeError, KeyError) as error:
        raise ProjectionError(f"fail-closed: source receipt shell is invalid: {error}") from error
    _validate_zero_credit(receipt, "source receipt")
    if "authority" in receipt:
        _validate_existing_authority(receipt["authority"])


def _validate_scope(identity: Mapping[str, Any]) -> None:
    for key, expected in {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed": SEED,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }.items():
        _exact(identity, key, expected, "source receipt.identity")


def _validate_source_descriptors(identity: Mapping[str, Any]) -> dict[str, str]:
    records = _mapping(identity.get("source_files"), "source receipt.identity.source_files")
    expected = set(admission.SOURCE_RELATIVE_PATHS)
    if set(records) != expected:
        _fail("source receipt.identity.source_files does not cover the seed29 admission source set")
    digests: dict[str, str] = {}
    for name in sorted(expected):
        descriptor = _mapping(records[name], f"source receipt.identity.source_files.{name}")
        path = descriptor.get("path")
        digest = descriptor.get("sha256")
        if not isinstance(path, str) or not Path(path).is_absolute():
            _fail(f"source receipt.identity.source_files.{name}.path is not absolute")
        if not isinstance(digest, str) or len(digest) != 64:
            _fail(f"source receipt.identity.source_files.{name}.sha256 is malformed")
        digests[name] = digest
    return digests


def project_authority(
    receipt: Mapping[str, Any],
    *,
    external_authority: Path | str | None,
    resource_admission: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Verify external bindings and return an in-memory non-authorizing view."""

    original = copy.deepcopy(dict(_mapping(receipt, "source receipt")))
    _receipt_digest(original, "source receipt")
    _validate_identity_digest(original, "source receipt")
    _validate_receipt_shell(original)
    missing = _missing_fields(original)
    if missing:
        raise ProjectionGap(
            "projection-gap: producer-bound current-schema fields are missing",
            missing_fields=missing,
            blockers=(
                "local projection cannot reconstruct " + ", ".join(missing),
                "caller/local fields cannot substitute for external scheduler authority",
            ),
        )

    identity = _mapping(original["identity"], "source receipt.identity")
    _validate_scope(identity)
    source_digests = _validate_source_descriptors(identity)
    authority_meta = _mapping(identity["external_authority"], "source receipt.identity.external_authority")
    bound_authority_path = _absolute(authority_meta.get("path"), "source receipt.identity.external_authority.path")
    if external_authority is None:
        raise ProjectionGap(
            "projection-gap: external scheduler authority is required",
            missing_fields=("authority",),
            blockers=(
                "no real external scheduler document was supplied",
                "caller claim, local receipt field, or GPU probe cannot substitute for authority",
            ),
        )
    supplied_authority_path = _absolute(external_authority, "external scheduler authority")
    if supplied_authority_path != bound_authority_path:
        raise ProjectionGap(
            "projection-gap: supplied authority path does not match the receipt",
            blockers=("authority path is a producer-bound source field; local repair is prohibited",),
        )
    if resource_admission is None:
        raise ProjectionGap(
            "projection-gap: scheduler-owned resource snapshot is required",
            blockers=("no externally bound resource snapshot was supplied",),
        )
    try:
        resource_snapshot = admission._validate_resource(resource_admission)
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: resource snapshot is not scheduler-admissible",
            blockers=(str(error),),
        ) from error
    identity_resource = _mapping(identity["resource_admission"], "source receipt.identity.resource_admission")
    if canonical_json(resource_snapshot) != canonical_json(dict(identity_resource)):
        raise ProjectionGap(
            "projection-gap: resource snapshot differs from the receipt-bound resource",
            blockers=("caller-supplied resource claims cannot repair receipt drift",),
        )

    try:
        namespace = _absolute(identity["namespace"], "source receipt.identity.namespace")
        namespace_descriptor = _mapping(identity["namespace_descriptor"], "source receipt.identity.namespace_descriptor")
        current_namespace = admission._existing_namespace_descriptor(namespace)
        for key in (
            "path",
            "dev",
            "ino",
            "mode",
            "uid",
            "gid",
            "nlink",
            "parent_dev",
            "parent_ino",
        ):
            _exact(namespace_descriptor, key, current_namespace[key], "source receipt.identity.namespace_descriptor")
        plan = admission._identity_plan_binding(identity)
        plan_sha256 = admission._plan_binding_digest(plan)
        _exact(identity, "plan_sha256", plan_sha256, "source receipt.identity")
        external_meta = admission._validate_external_authority(
            supplied_authority_path,
            nonce=admission._validate_nonce(identity["nonce"], "source receipt.identity.nonce"),
            namespace_descriptor=namespace_descriptor,
            plan_sha256=plan_sha256,
            resource_snapshot=resource_snapshot,
            expected_meta=authority_meta,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        raise ProjectionGap(
            "projection-gap: external scheduler authority or bound namespace could not be verified",
            blockers=(str(error),),
        ) from error

    projected = copy.deepcopy(original)
    projected["authority"] = _authority_envelope()
    projected.pop("receipt_descriptor", None)
    projected.pop("namespace_marker_descriptor", None)
    projected.pop("receipt_sha256", None)
    projected["receipt_sha256"] = canonical_digest(_receipt_core(projected))
    return {
        "schema": SCHEMA,
        "status": "authority_projection_ready",
        "source_receipt_sha256": str(original["receipt_sha256"]),
        "projected_receipt": projected,
        "authority": dict(projected["authority"]),
        "external_authority": external_meta,
        "bindings": {
            "nonce": str(identity["nonce"]),
            "namespace": str(identity["namespace"]),
            "namespace_descriptor": dict(identity["namespace_descriptor"]),
            "plan_sha256": str(identity["plan_sha256"]),
            "source_files": source_digests,
            "source_binding_sha256": canonical_digest(source_digests),
            "resource_snapshot_sha256": canonical_digest(resource_snapshot),
            "external_authority_document_sha256": external_meta["document_sha256"],
            "external_authority_id": external_meta["authority_id"],
        },
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


def _base_report(receipt_path: Path | str = DEFAULT_SOURCE_RECEIPT) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_projection_gap",
        "scope": {
            "family": "F3",
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        },
        "source_receipt": {"path": str(receipt_path), "observed": False},
        "source_observed": False,
        "source_receipt_schema": None,
        "source_receipt_sha256": None,
        "missing_fields": [],
        "projectable_missing_fields": ["authority"],
        "non_projectable_missing_fields": [],
        "adapter_authority": {
            "present": False,
            "verified": False,
            "non_authorizing": True,
            "runner_consumable": False,
        },
        "external_authority": {
            "path_supplied": False,
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "trusted_scheduler_key": _path_state(admission.TRUSTED_SCHEDULER_PUBLIC_KEY_PATH),
            "configured_scheduler_root": _path_state(admission.EXTERNAL_SCHEDULER_ROOT),
        },
        "resource_binding": {
            "supplied": False,
            "verified": False,
            "scheduler_owned_snapshot_required": True,
            "caller_or_local_snapshot_accepted": False,
        },
        "projection_contract": {
            "authority_envelope_is_non_authorizing": True,
            "requires_external_signature": True,
            "requires_nonce_binding": True,
            "requires_namespace_inode_binding": True,
            "requires_plan_binding": True,
            "requires_source_descriptor_binding": True,
            "requires_resource_snapshot_binding": True,
            "requires_gpu_identity_binding": True,
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
    report = _base_report(receipt_path)
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
                "adapter_authority": {
                    "present": True,
                    "verified": True,
                    "non_authorizing": True,
                    "runner_consumable": False,
                },
                "external_authority": {
                    **report["external_authority"],
                    "path_supplied": True,
                    "verified": True,
                    "document": result["external_authority"],
                },
                "resource_binding": {
                    **report["resource_binding"],
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
        report["status"] = "blocked_projection_gap"
        report["blockers"] = list(
            dict.fromkeys([*report.get("blockers", []), *error.blockers, str(error)])
        )
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
    except (ProjectionError, admission.AdmissionError, OSError, TypeError, ValueError) as error:
        report["blockers"] = [f"fail-closed: {error}"]
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
        scope = _mapping(report.get("scope"), "report.scope")
        for key, expected in {
            "family": "F3",
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        }.items():
            _exact(scope, key, expected, "report.scope")
        for key, expected in {
            "historical_receipt_rewritten": False,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "popen_allowed": False,
        }.items():
            _exact(report, key, expected, "report")
        authority = _mapping(report.get("external_authority"), "report.external_authority")
        _exact(authority, "real_external_document_required", True, "report.external_authority")
        _exact(authority, "verified", report.get("status") == "authority_projection_ready", "report.external_authority")
        _exact(authority, "signature_algorithm", "ed25519", "report.external_authority")
        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        _exact(resource, "caller_or_local_snapshot_accepted", False, "report.resource_binding")
        _exact(resource, "verified", report.get("status") == "authority_projection_ready", "report.resource_binding")
        adapter = _mapping(report.get("adapter_authority"), "report.adapter_authority")
        _exact(adapter, "non_authorizing", True, "report.adapter_authority")
        _exact(adapter, "runner_consumable", False, "report.adapter_authority")
        contract = _mapping(report.get("projection_contract"), "report.projection_contract")
        for key, expected in {
            "authority_envelope_is_non_authorizing": True,
            "requires_external_signature": True,
            "requires_nonce_binding": True,
            "requires_namespace_inode_binding": True,
            "requires_plan_binding": True,
            "requires_source_descriptor_binding": True,
            "requires_resource_snapshot_binding": True,
            "requires_gpu_identity_binding": True,
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
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in _side_effects().items():
            _exact(effects, key, expected, "report.side_effects")
    except (ProjectionError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_residual hidden16 seed29 authority projection gap",
        "",
        f"- 状态：`{report.get('status')}`",
        "- 范围：`graph_residual / hidden16 / seed29 / test / 500 updates / 835 transitions / 836 frames`",
        f"- source receipt observed：`{report.get('source_observed')}`",
        f"- external scheduler authority verified：`{report.get('external_authority', {}).get('verified')}`",
        f"- adapter authority is non-authorizing：`{report.get('adapter_authority', {}).get('non_authorizing')}`",
        f"- runner consumable：`{report.get('runner_consumable')}`",
        f"- Popen allowed：`{report.get('popen_allowed')}`",
        f"- credit：`{report.get('credit')}`",
        "",
        "## Fail-closed gap",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("blockers", []) if isinstance(item, str))
    lines.extend(
        [
            "",
            "只有真实 external scheduler authority、部署拥有的 Ed25519 public key、nonce、namespace inode、plan/source/resource/GPU bindings 全部通过校验，才允许生成内存中的非授权 envelope。",
            "",
            "本 artifact 不写回 receipt，不让 runner 消费，不调用 Popen/solver/worker/GPU/queue，也不修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。",
            "",
        ]
    )
    return "\n".join(lines)


def _load_resource(path: Path) -> Mapping[str, Any]:
    try:
        _raw, _descriptor, payload = admission._read_bound(
            path,
            "resource admission JSON",
            max_bytes=256 * 1024,
            parse_json=True,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        _fail(str(error))
    return _mapping(payload, "resource admission JSON")


def write_reports(
    report: Mapping[str, Any],
    *,
    report_path: Path | str = DEFAULT_REPORT,
    markdown_path: Path | str = DEFAULT_MARKDOWN,
) -> tuple[Path, Path]:
    json_path = Path(report_path)
    md_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_SOURCE_RECEIPT)
    parser.add_argument("--external-authority", type=Path, default=None)
    parser.add_argument("--resource-admission", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
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
    write_reports(report, report_path=args.output, markdown_path=args.markdown)
    return 0 if report["status"] == "authority_projection_ready" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
